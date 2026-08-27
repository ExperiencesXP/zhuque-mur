import io
import re
import zipfile
from pathlib import Path
from urllib.parse import urlparse

import requests

from constants.info import USER_AGENT


def parse_repo_ref(value: str) -> tuple[str, str] | None:
    """Accept owner/repo, a github.com URL, or git@github.com:owner/repo.git."""
    raw = (value or "").strip().strip("\"'")
    if not raw:
        return None

    ssh = re.match(r"^git@github\.com:([^/]+)/([^/]+?)(?:\.git)?/?$", raw, re.I)
    if ssh:
        return ssh.group(1), ssh.group(2)

    candidate = raw
    if candidate.lower().startswith("github.com/"):
        candidate = "https://" + candidate
    if "://" in candidate:
        parsed = urlparse(candidate)
        host = (parsed.netloc or "").lower()
        if host not in {"github.com", "www.github.com"}:
            return None
        parts = [p for p in parsed.path.split("/") if p]
        if len(parts) < 2:
            return None
        owner, repo = parts[0], parts[1]
        if repo.endswith(".git"):
            repo = repo[:-4]
        return owner, repo

    if "/" not in raw:
        return None
    owner, repo = raw.split("/", 1)
    repo = repo.split("/")[0]
    if repo.endswith(".git"):
        repo = repo[:-4]
    owner, repo = owner.strip(), repo.strip()
    if not owner or not repo or ":" in owner:
        return None
    return owner, repo


class GithubClient:
    def __init__(self, token: str | None = None):
        self.token = token if token and not _is_placeholder_token(token) else None
        self.base_url = "https://api.github.com"
        self.session = requests.Session()
        self.session.headers["Accept"] = "application/vnd.github+json"
        self.session.headers["User-Agent"] = USER_AGENT
        self.valid_token = False
        if self.token:
            self.session.headers["Authorization"] = f"Bearer {self.token}"
            self.valid_token = bool(self._is_token_valid(self.token))
            if not self.valid_token:
                self.session.headers.pop("Authorization", None)
                self.token = None

    def _is_token_valid(self, token: str | None) -> bool:
        if not token:
            return False
        try:
            response = self.session.get(f"{self.base_url}/user", timeout=10)
        except requests.RequestException:
            return False
        return response.status_code == 200

    def _get(self, path: str, **kwargs):
        url = f"{self.base_url}{path}"
        timeout = kwargs.pop("timeout", 10)
        response = self.session.get(url, timeout=timeout, **kwargs)
        if response.status_code == 401 and "Authorization" in self.session.headers:
            self.session.headers.pop("Authorization", None)
            self.valid_token = False
            self.token = None
            response = self.session.get(url, timeout=timeout, **kwargs)
        return response

    def check_repo(self, owner: str, repo: str) -> bool:
        try:
            response = self._get(f"/repos/{owner}/{repo}")
        except requests.RequestException:
            return False
        return response.status_code == 200

    def get_repo(self, owner: str, repo: str) -> dict:
        try:
            response = self._get(f"/repos/{owner}/{repo}")
            response.raise_for_status()
            return response.json()
        except requests.RequestException:
            return {}

    def lookup_repo(self, owner: str, repo: str) -> tuple[dict, str | None]:
        try:
            response = self._get(f"/repos/{owner}/{repo}")
        except requests.RequestException as exc:
            return {}, f"GitHub request failed: {exc}"
        if response.status_code == 200:
            return response.json(), None
        if response.status_code == 404:
            return {}, f"{owner}/{repo} was not found (or it is private and the token cannot see it)."
        if response.status_code == 401:
            return {}, "GitHub rejected the credentials. Check GITHUB_TOKEN or run without a token."
        if response.status_code == 403:
            reset = from_reset_header(response)
            return {}, (
                "GitHub rate-limited or forbade this request"
                + (f" (resets {reset})" if reset else "")
                + ". Set a valid GITHUB_TOKEN."
            )
        return {}, f"GitHub returned HTTP {response.status_code}."

    def api_stat(self) -> dict:
        try:
            response = self._get("/rate_limit")
            response.raise_for_status()
            core = response.json().get("resources", {}).get("core", {})
        except requests.RequestException:
            core = {}
        return {
            "limit": core.get("limit", 0),
            "used": core.get("used", 0),
            "remaining": core.get("remaining", 0),
            "reset": core.get("reset", 0),
        }

    def get_license(self, owner: str, repo: str) -> dict:
        try:
            response = self._get(f"/repos/{owner}/{repo}/license")
        except requests.RequestException:
            return {}
        if response.status_code == 404:
            return {"spdx_id": "NONE", "name": "No license found", "html_url": ""}
        if response.status_code != 200:
            return {}
        payload = response.json()
        info = payload.get("license") or {}
        return {
            "spdx_id": info.get("spdx_id") or "NOASSERTION",
            "name": info.get("name") or "Unknown",
            "html_url": payload.get("html_url") or "",
            "path": payload.get("path") or "",
        }

    def get_readme(self, owner: str, repo: str) -> str:
        try:
            response = self._get(
                f"/repos/{owner}/{repo}/readme",
                headers={"Accept": "application/vnd.github.raw"},
            )
        except requests.RequestException:
            return ""
        if response.status_code != 200:
            return ""
        return response.text

    def get_code(self, owner: str, repo: str, dest: Path, ref: str = "HEAD") -> Path:
        response = self._get(f"/repos/{owner}/{repo}/zipball/{ref}", timeout=120)
        response.raise_for_status()
        dest = Path(dest)
        dest.mkdir(parents=True, exist_ok=True)
        extract_root = dest
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            _safe_extract(archive, extract_root)
        children = [p for p in extract_root.iterdir() if p.is_dir()]
        files = [p for p in extract_root.iterdir() if p.is_file()]
        if len(children) == 1 and not files:
            return children[0]
        return extract_root


def _safe_extract(archive: zipfile.ZipFile, dest: Path) -> None:
    dest = dest.resolve()
    for info in archive.infolist():
        target = (dest / info.filename).resolve()
        if dest not in target.parents and target != dest:
            raise RuntimeError(f"Refusing to extract unsafe path: {info.filename}")
        if info.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        with archive.open(info) as src, open(target, "wb") as out:
            out.write(src.read())


def _is_placeholder_token(token: str) -> bool:
    stripped = token.strip()
    return stripped.endswith("...") or stripped in {"ghp_...", "github_pat_..."}


def from_reset_header(response: requests.Response) -> str:
    raw = response.headers.get("X-RateLimit-Reset")
    if not raw:
        return ""
    try:
        from utils.time import from_timestamp

        return from_timestamp(int(raw))
    except (TypeError, ValueError):
        return ""


class Repo:
    _instances: list["Repo"] = []

    def __init__(self, github: GithubClient, owner: str, repo: str):
        self.owner = owner
        self.repo = repo
        self.github = github
        self._instances.append(self)
        self.meta, self.error = self.github.lookup_repo(self.owner, self.repo)
        self.exists = bool(self.meta)

    def __str__(self) -> str:
        return f"{self.owner}/{self.repo}"

    def license(self) -> dict:
        return self.github.get_license(self.owner, self.repo)

    def readme(self) -> str:
        return self.github.get_readme(self.owner, self.repo)

    def fetch(self, dest: Path, ref: str | None = None) -> Path:
        ref = ref or self.meta.get("default_branch") or "HEAD"
        return self.github.get_code(self.owner, self.repo, dest, ref=ref)

    @classmethod
    def list_repos(cls) -> list["Repo"]:
        return cls._instances.copy()
