import json
import shutil

import constants.info as ci
import constants.licenses as cl
from constants.models import DEFAULT_MODEL
import constants.textual as ct
from api.agent import UniversalClient
from api.credentials import credential_for, list_remote_models
from api.github import GithubClient, Repo, parse_repo_ref
from api.implement import run_implementer
from api.import_auth import import_env_keys, import_opencode
from api.oauth import OAuthError, device_login
from constants.providers import BYOK_PRESETS, OAUTH_PROVIDERS, PROVIDERS, provider_meta
from utils.auth_store import auth_path, delete_entry, list_entries, mask_secret, put_entry
from utils.models import catalog_models_for
from utils.paths import load_prompt
from utils.progress import Job, estimate_tokens
from utils.secrets import env_val
from utils.source import pack_source, tree_listing
from utils.time import from_timestamp
from utils.workspace import IsolationError, Room, Workspace


class Commands:
    def __init__(self, app):
        self.app = app
        self.github = GithubClient(env_val("GITHUB_TOKEN"))
        self.repo = None
        self.ws = None
        self.ai = UniversalClient()
        self.last_verdict = None
        self._restore_workspace()

    def help(self):
        return [
            "Commands:",
            "  help                 List commands",
            "  status               Session, token, model, rooms",
            "  target [owner/repo]  Set the GitHub repository (URL ok)",
            "  untarget             Clear the target",
            "  inspect / license    License check and repo metadata",
            "  fetch                Download original source into the dirty room",
            "  analyze              Dirty room: brief + reverse-engineering notes",
            "  specify              Airlock: requirements spec from notes only",
            "  implement            Clean room: new code from the spec only (tool loop)",
            "  continue [owner/repo] Resume the last (or named) workspace where it left off",
            "  run                  License gate, then remaining steps (skips finished rooms)",
            "  model [name|list]    Show, list, or set the AI model",
            "  auth                 OAuth / BYOK credentials",
            "  rooms [list|repo]    Show on-disk rooms (no live target needed)",
            "  clear [clean|all]    Wipe rooms on disk (optional owner/repo)",
            "  exit                 Quit",
            "The wall: analyze may read the original. specify may not. implement may read only spec/.",
        ]

    def status(self):
        color = ct.RED if not self.repo else ct.CYAN
        parts = [
            f"{ci.PROGRAM_NAME} version {ci.VERSION}.",
            f'Target repository is "{color}{self.repo}{ct.RESET}".',
        ]
        if self.github.valid_token:
            session_info = self.github.api_stat()
            parts.append(
                f"GITHUB_TOKEN is valid: limit {session_info.get('limit')} with "
                f"{session_info.get('remaining')} remaining requests that reset on "
                f"{from_timestamp(session_info.get('reset'))}."
            )
        else:
            parts.append("GITHUB_TOKEN is invalid or missing (public repos still work).")
        parts.append(f"{self.ai.status_line()}.")
        if self.ws:
            counts = self.ws.summary()
            live = "targeted" if self.repo else "on disk, not targeted this session"
            stage = self.ws.pipeline_stage()
            session = self.ws.load_session()
            extra = ""
            if session:
                extra = (
                    f" Implement session {session.get('status')} "
                    f"turn {session.get('turn') or 0}."
                )
            parts.append(
                f"Workspace {self.ws.label} ({live}) — dirty {counts['dirty']}, "
                f"analysis {counts['analysis']}, spec {counts['spec']}, "
                f"clean {counts['clean']}; stage {stage}.{extra}"
            )
        else:
            found = Workspace.discover()
            if found:
                labels = ", ".join(ws.label for ws in found[:4])
                extra = f" (+{len(found) - 4} more)" if len(found) > 4 else ""
                parts.append(f"On-disk workspaces: {labels}{extra}. Use rooms / rooms list.")
        return " ".join(parts)

    def target(self, arg=None):
        if self.repo:
            if not self.app.view.confirm(
                f'Target repository: "{ct.CYAN}{self.repo}{ct.RESET}". Set a new target?'
            ):
                return f'Target repository: "{ct.CYAN}{self.repo}{ct.RESET}".'

        parsed = parse_repo_ref(arg) if arg else None
        if parsed:
            owner, repo = parsed
        else:
            if arg:
                return (
                    f'{ct.RED}Could not parse "{arg}" as owner/repo or a github.com URL.{ct.RESET}'
                )
            self.app.view.display("Repository owner:")
            owner = self.app.view.get_input()
            self.app.view.display("Repository name:")
            repo = self.app.view.get_input()

        owner, repo = owner.strip(), repo.strip()
        if not owner or not repo:
            return f"{ct.RED}Owner and repository name are required.{ct.RESET}"

        self.repo = Repo(self.github, owner, repo)
        if not self.repo.exists:
            detail = self.repo.error or "not found"
            output = f'{ct.RED}Target repository: "{self.repo}" — {detail}{ct.RESET}'
            self.repo = None
            self.ws = None
            return output

        self.ws = Workspace(self.repo.owner, self.repo.repo)
        self.ws.prepare()
        self.ws.remember()
        self.ws.log(f"TARGET {self.repo}")
        return f'Target repository: "{ct.CYAN}{self.repo}{ct.RESET}".'

    def untarget(self):
        label = self.ws.label if self.ws else None
        self.repo = None
        self.ws = None
        self.last_verdict = None
        Workspace.forget_current()
        extra = f' Folders for {label} stay on disk. Use "rooms" or "clear".' if label else ""
        return f'Target repository: "{ct.RED}None{ct.RESET}".{extra}'

    def inspect(self):
        missing = self._need_target()
        if missing:
            return missing

        meta = self.repo.meta or {}
        license_info = self.repo.license()
        spdx = license_info.get("spdx_id")
        verdict = cl.classify(spdx)
        self.last_verdict = verdict
        report = self._license_report(license_info, verdict, meta)
        if self.ws:
            self.ws.write_root("LICENSE_VERDICT.md", report)
            self.ws.write_root(
                "inspect.json",
                json.dumps({"repo": str(self.repo), "license": license_info, "verdict": verdict, "meta": {
                    "description": meta.get("description"),
                    "language": meta.get("language"),
                    "default_branch": meta.get("default_branch"),
                    "html_url": meta.get("html_url"),
                    "license": (meta.get("license") or {}).get("spdx_id"),
                }}, indent=2),
            )
            self.ws.log(f"INSPECT {self.repo} license={spdx} verdict={verdict}")
        return report

    def fetch(self):
        missing = self._need_target()
        if missing:
            return missing
        self.ws.prepare()
        if any(self.ws.dirty_dir.iterdir()) if self.ws.dirty_dir.exists() else False:
            if not self.app.view.confirm("Dirty room already has files. Replace them?"):
                return "Fetch cancelled. Existing dirty-room files kept."
            shutil.rmtree(self.ws.dirty_dir)
            self.ws.dirty_dir.mkdir(parents=True, exist_ok=True)
        self.app.view.display(
            f"{ct.DIM}Downloading {self.repo} zipball from GitHub…{ct.RESET}"
        )
        try:
            extracted = self.repo.fetch(self.ws.dirty_dir)
        except Exception as exc:
            return f"{ct.RED}Fetch failed: {exc}{ct.RESET}"
        count = len(self.ws.list_files(Room.DIRTY))
        self.ws.log(f"FETCH {self.repo} files={count} root={extracted}")
        return (
            f"Fetched {ct.CYAN}{self.repo}{ct.RESET} into dirty room "
            f"({count} files). Source root: {extracted}."
        )

    def analyze(self):
        missing = self._need_pipeline_workspace() or self._need_ai() or self._need_dirty()
        if missing:
            return missing
        if not self.ws.exists(Room.ANALYSIS, "brief.md"):
            self.app.view.display(f"{ct.DIM}Step 1/2 · brief (tree + README, no full source).{ct.RESET}")
            brief_result = self._customize()
            if brief_result and brief_result.startswith(ct.RED):
                return brief_result
        self.app.view.display(f"{ct.DIM}Packing dirty-room source for analysis…{ct.RESET}")
        packed, included, omitted = pack_source(self.ws.source_root())
        if not packed:
            return f"{ct.RED}No readable source files in the dirty room.{ct.RESET}"
        self.app.view.display(
            f"{ct.DIM}Step 2/2 · reverse-engineer {len(included)} files "
            f"({len(packed):,} chars, ~{estimate_tokens(packed):,} tok est.); "
            f"omitted {len(omitted)}.{ct.RESET}"
        )
        brief = ""
        if self.ws.exists(Room.ANALYSIS, "brief.md"):
            brief = self.ws.read_text(Room.ANALYSIS, "brief.md")
        user = (
            f"Target: {self._repo_label()}\n\n"
            f"## Brief\n{brief or '(none)'}\n\n"
            f"## Included files ({len(included)})\n"
            f"{chr(10).join(included)}\n\n"
            f"## Omitted files ({len(omitted)})\n"
            f"{chr(10).join(omitted) or '(none)'}\n\n"
            f"## Source\n{packed}"
        )
        try:
            notes = self._complete("reverse_engineer.md", user, step="analyze")
        except Exception as exc:
            return f"{ct.RED}Analyze failed: {exc}{ct.RESET}"
        path = self.ws.write_text(Room.ANALYSIS, "analysis.md", notes)
        self.ws.log(f"ANALYZE model={self.ai.model} included={len(included)} omitted={len(omitted)}")
        return (
            f"Dirty-room analysis written to {path}. "
            f"Read {len(included)} files, omitted {len(omitted)}."
        )

    def specify(self):
        missing = self._need_pipeline_workspace() or self._need_ai()
        if missing:
            return missing
        if not self.ws.exists(Room.ANALYSIS, "analysis.md"):
            return f'{ct.RED}No analysis yet. Run "analyze" first.{ct.RESET}'
        try:
            notes = self.ws.read_text(Room.SPEC, "analysis.md")
            brief = (
                self.ws.read_text(Room.SPEC, "brief.md")
                if self.ws.exists(Room.ANALYSIS, "brief.md")
                else ""
            )
        except IsolationError as exc:
            return f"{ct.RED}Isolation: {exc}{ct.RESET}"
        user = (
            f"Target purpose (from brief, not source):\n{brief or '(no brief)'}\n\n"
            f"## Analysis notes\n{notes}"
        )
        try:
            spec = self._complete("specification_creator.md", user, step="specify")
        except Exception as exc:
            return f"{ct.RED}Specify failed: {exc}{ct.RESET}"
        path = self.ws.write_text(Room.SPEC, "specification.md", spec)
        self.ws.log(f"SPECIFY model={self.ai.model} isolated=true")
        return f"Airlock specification written to {path}. The implementer will see only spec/."

    def implement(self):
        missing = self._need_pipeline_workspace() or self._need_ai()
        if missing:
            return missing
        if not self.ws.exists(Room.SPEC, "specification.md"):
            return f'{ct.RED}No specification yet. Run "specify" first.{ct.RESET}'
        try:
            self.ws.read_text(Room.CLEAN, "specification.md")
        except IsolationError as exc:
            return f"{ct.RED}Isolation: {exc}{ct.RESET}"
        license_name = env_val("OUTPUT_LICENSE") or "MIT"
        try:
            return run_implementer(
                ws=self.ws,
                ai=self.ai,
                view=self.app.view,
                license_name=license_name,
                confirm=self.app.view.confirm,
                resume=True,
            )
        except Exception as exc:
            return f"{ct.RED}Implement failed: {exc}{ct.RESET}"

    def continue_session(self, arg=None):
        missing = self._need_workspace(arg)
        if missing:
            return missing
        self.ws.remember()
        stage = self.ws.pipeline_stage()
        self.app.view.display(
            f"{ct.DIM}Continuing {self.ws.label} · stage {stage}{ct.RESET}"
        )
        if stage == "fetch":
            if not self.repo:
                return (
                    f"{ct.RED}Fetch needs a live GitHub target.{ct.RESET} "
                    f'Run "target {self.ws.label}" then continue.'
                )
            missing = self._need_ai()
            if missing:
                return missing
            return self.fetch()
        if stage == "analyze":
            return self.analyze()
        if stage == "specify":
            return self.specify()
        if stage == "implement":
            return self.implement()
        session = self.ws.load_session()
        status = (session or {}).get("status")
        extra = f" Implement session is {status}." if status else ""
        return (
            f"Nothing left to continue for {self.ws.label}. "
            f"Clean-room files are on disk.{extra} "
            'Use implement to add more, or "clear clean" to start the clean room over.'
        )

    def run_pipeline(self):
        self._restore_workspace()
        if not self.ws or not self.ws.present:
            missing = self._need_target()
            if missing:
                return missing
        missing = self._need_ai()
        if missing:
            return missing
        self.ws.remember()
        stage = self.ws.pipeline_stage()
        if stage == "done":
            return (
                f"Pipeline already complete for {self.ws.label}. "
                "Use implement to keep adding files, or clear clean to restart the clean room."
            )
        results = []
        if stage == "fetch":
            live = self._need_target()
            if live:
                return live
            gate = self._license_gate()
            if gate:
                return gate
        elif self.repo:
            results.append(self.inspect())
        steps = []
        if stage == "fetch":
            steps.append(("fetch", self.fetch))
        if stage in {"fetch", "analyze"}:
            steps.append(("analyze", self.analyze))
        if stage in {"fetch", "analyze", "specify"}:
            steps.append(("specify", self.specify))
        steps.append(("implement", self.implement))
        for index, (name, step) in enumerate(steps, start=1):
            self.app.view.display(
                f"{ct.CYAN}Pipeline {index}/{len(steps)} · {name}{ct.RESET}"
            )
            result = step()
            results.append(result)
            if isinstance(result, str) and ct.RED in result:
                results.append(f"{ct.RED}Pipeline stopped at {name}.{ct.RESET}")
                break
        return results

    def model(self, arg=None):
        if not arg:
            return self.ai.status_line() + "."
        verb, _, rest = arg.partition(" ")
        if verb.lower() == "list":
            return self._model_list(rest.strip() or None)
        chosen = self.ai.set_model(arg)
        if not chosen:
            return (
                f"{ct.RED}Unknown model: \"{arg}\".{ct.RESET} "
                f'{ct.DIM}Use provider/model (e.g. neuralwatt/deepseek-v4-flash) or "model list".{ct.RESET}'
            )
        return self.ai.status_line() + "."

    def auth(self, arg=None):
        if not arg:
            return self._auth_status()
        verb, _, rest = arg.strip().partition(" ")
        verb = verb.lower()
        target = rest.strip() or None
        match verb:
            case "list" | "status":
                return self._auth_status()
            case "login" | "oauth":
                return self._auth_login(target)
            case "logout" | "remove":
                return self._auth_logout(target)
            case "key":
                return self._auth_key(target)
            case "byok":
                return self._auth_byok(target)
            case "import":
                return self._auth_import()
            case _:
                if provider_meta(verb) or verb in list_entries():
                    return self._auth_login(verb)
                return [
                    f'{ct.RED}Unknown auth command: "{verb}".{ct.RESET}',
                    "  auth                 Show stored credentials",
                    "  auth login <name>    OAuth if the vendor publishes it, else paste a key",
                    "  auth key <name>      Bring your own API key",
                    "  auth byok [preset]   Neuralwatt, OpenCode, OpenRouter, Ollama, or custom URL",
                    "  auth import          Pull keys from .env and OpenCode's auth.json",
                    "  auth logout <name>   Forget a stored credential",
                ]

    def _auth_status(self):
        stored = list_entries()
        lines = [
            f"Credentials file: {auth_path()}",
            "OAuth is available for: " + ", ".join(OAUTH_PROVIDERS) + ".",
            "BYOK presets: " + ", ".join(BYOK_PRESETS) + ".",
        ]
        for name, meta in PROVIDERS.items():
            cred = credential_for(name)
            mark = "ok" if cred.ready or cred.token else "—"
            how = cred.source if cred.token or cred.ready else "signed out"
            kinds = "/".join(meta.get("auth", ()))
            extra = " byok" if meta.get("byok") else ""
            lines.append(f"  {mark:2} {name:14} {kinds}{extra:5}  {how}")
        extras = [name for name in stored if name not in PROVIDERS]
        for name in extras:
            entry = stored[name]
            lines.append(f"  ok {name:14} {entry.get('type', '?')}  store")
        lines.append(f'Active: {self.ai.status_line()}.')
        return lines

    def _auth_login(self, name: str | None):
        if not name:
            self.app.view.display("Provider (xai, openai, anthropic, google, neuralwatt, opencode, …):")
            name = self.app.view.get_input(lowercase=True)
        name = (name or "").lower()
        meta = provider_meta(name)
        if not meta and name not in list_entries():
            return f'{ct.RED}Unknown provider: "{name}".{ct.RESET} Try "auth" for the list.'
        if meta and "oauth" in meta.get("auth", ()):
            self.app.view.display(
                f"{meta['name']} supports device-code OAuth (SuperGrok / X Premium+). "
                "Paste a key instead?"
            )
            if not self.app.view.confirm("Use OAuth now?"):
                return self._auth_key(name)
            return self._auth_oauth(name)
        if meta and meta.get("key_url"):
            self.app.view.display(f"Create a key at {meta['key_url']}")
            note = meta.get("note")
            if note:
                self.app.view.display(note)
        return self._auth_key(name)

    def _auth_oauth(self, name: str):
        meta = provider_meta(name)
        oauth = dict(meta["oauth"])

        def announce(uri, code, complete):
            self.app.view.display(
                f"Open {complete or uri} and enter code {ct.CYAN}{code}{ct.RESET}. "
                "Waiting for approval…"
            )

        try:
            tokens = device_login(oauth, announce)
        except OAuthError as exc:
            return f"{ct.RED}OAuth failed: {exc}{ct.RESET}"
        import time as _time

        expires_in = int(tokens.get("expires_in") or 3600)
        put_entry(
            name,
            {
                "type": "oauth",
                "access_token": tokens["access_token"],
                "refresh_token": tokens.get("refresh_token"),
                "expires_at": int(_time.time()) + expires_in,
                "token_endpoint": tokens.get("_token_endpoint"),
                "client_id": tokens.get("_client_id"),
                "base_url": meta.get("base_url"),
            },
        )
        self.ai.reload()
        return f"Signed in to {meta['name']} with OAuth. Access token stored in ~/.zhuque-mur/auth.json."

    def _auth_key(self, name: str | None):
        if not name:
            self.app.view.display("Provider:")
            name = self.app.view.get_input(lowercase=True)
        name = (name or "").lower()
        meta = provider_meta(name) or {}
        key = self.app.view.get_secret()
        if not key and not meta.get("optional_key"):
            return f"{ct.RED}No key entered.{ct.RESET}"
        entry = {
            "type": "api_key",
            "key": key or "local",
            "base_url": meta.get("base_url"),
            "compat": meta.get("compat") or "openai",
        }
        if meta.get("base_url_env"):
            endpoint = env_val(meta["base_url_env"])
            if not endpoint:
                self.app.view.display(f"{meta['base_url_env']} (base URL):")
                endpoint = self.app.view.get_input()
            entry["base_url"] = endpoint
        put_entry(name, entry)
        self.ai.reload()
        label = meta.get("name") or name
        return f"Stored BYOK key for {label} ({mask_secret(key)})."

    def _auth_byok(self, preset: str | None):
        if not preset:
            self.app.view.display(
                "Preset: " + ", ".join(BYOK_PRESETS) + ", or custom"
            )
            preset = self.app.view.get_input(lowercase=True)
        preset = (preset or "").lower()
        if preset in {"custom", "url", "compat"}:
            return self._auth_custom()
        if preset in BYOK_PRESETS or provider_meta(preset):
            return self._auth_key(preset)
        return (
            f'{ct.RED}Unknown BYOK preset: "{preset}".{ct.RESET} '
            f"Try {', '.join(BYOK_PRESETS)} or custom."
        )

    def _auth_custom(self):
        self.app.view.display("Label (e.g. home-lab):")
        label = self.app.view.get_input(lowercase=True).replace(" ", "-")
        if not label:
            return f"{ct.RED}Label is required.{ct.RESET}"
        name = label if label.startswith("byok:") else f"byok:{label}"
        self.app.view.display("OpenAI-compatible base URL (…/v1):")
        base_url = self.app.view.get_input().rstrip("/")
        if not base_url:
            return f"{ct.RED}Base URL is required.{ct.RESET}"
        key = self.app.view.get_secret("API key (blank if the server needs none):")
        self.app.view.display("Default model id on that server:")
        default_model = self.app.view.get_input()
        put_entry(
            name,
            {
                "type": "api_key",
                "key": key or "local",
                "base_url": base_url,
                "compat": "openai",
                "default_model": default_model or None,
            },
        )
        if default_model:
            self.ai.set_model(f"{name}/{default_model}")
        else:
            self.ai.reload()
        return f"Stored custom BYOK endpoint {name} → {base_url}."

    def _auth_logout(self, name: str | None):
        if not name:
            self.app.view.display("Provider to forget:")
            name = self.app.view.get_input(lowercase=True)
        name = (name or "").lower()
        if not delete_entry(name):
            return f'{ct.RED}No stored credential named "{name}".{ct.RESET}'
        self.ai.reload()
        return f"Forgot stored credential for {name}."

    def _auth_import(self):
        from_env = import_env_keys()
        from_oc = import_opencode()
        self.ai.reload()
        if not from_env and not from_oc:
            return "Nothing new to import. Already stored, or no .env / OpenCode auth.json found."
        parts = []
        if from_env:
            parts.append("env: " + ", ".join(from_env))
        if from_oc:
            parts.append("opencode: " + ", ".join(from_oc))
        return "Imported " + "; ".join(parts) + "."

    def _model_list(self, provider: str | None):
        lines = ["Models:"]
        if provider:
            provider = provider.strip().lower()
            if not provider_meta(provider) and provider not in list_entries():
                return [f'{ct.RED}Unknown provider: "{provider}".{ct.RESET}']
            cred = credential_for(provider)
            catalog = catalog_models_for(provider)
            remote = []
            if cred.base_url:
                try:
                    remote = list_remote_models(provider, cred)
                except Exception as exc:
                    lines.append(f"{ct.DIM}Could not list remote models: {exc}{ct.RESET}")
            seen = []
            for item in remote + catalog:
                if item not in seen:
                    seen.append(item)
            if not seen:
                return [f"No models listed for {provider}."]
            for item in seen:
                qualified = f"{provider}/{item}"
                mark = "*" if self.ai.model in {item, qualified} else " "
                lines.append(f"  {mark} {qualified}")
            return lines
        lines.append("Use model list <provider> to query that provider's /v1/models endpoint.")
        lines.append("Providers:")
        for name, meta in PROVIDERS.items():
            if meta.get("compat") == "none":
                continue
            auth = "/".join(meta.get("auth", ()))
            sample = ", ".join((meta.get("models") or [])[:2]) or "(discover from API)"
            lines.append(f"  {name:14} auth={auth:12} sample={sample}")
        lines.append("Gateway / BYOK (set provider/model):")
        for name in BYOK_PRESETS:
            meta = provider_meta(name)
            cred = credential_for(name)
            state = cred.source if cred.token or cred.ready else "signed out"
            lines.append(f"     {name:14} {meta['base_url']}  [{state}]")
        lines.append(f"Default is {DEFAULT_MODEL}. After BYOK: model neuralwatt/deepseek-v4-flash")
        return lines

    def rooms(self, arg=None):
        verb, ref = self._split_workspace_arg(arg)
        if verb == "list" or (not ref and not self.ws and len(Workspace.discover()) != 1):
            return self._rooms_index()
        missing = self._need_workspace(ref)
        if missing:
            return missing
        live = "targeted" if self.repo else "on disk"
        session = self.ws.load_session()
        session_bit = ""
        if session:
            session_bit = (
                f" · implement {session.get('status')} turn {session.get('turn') or 0}"
            )
        lines = [
            f"Workspace {self.ws.label} ({live}) — {self.ws.root}",
            f"stage {self.ws.pipeline_stage()}{session_bit}",
            "dirty/     original source — analyst only",
            "analysis/  brief + notes — analyst and specifier",
            "spec/      requirements — the only bridge",
            "clean/     new implementation — implementer only",
        ]
        for room in Room:
            files = self.ws.list_files(room)
            lines.append(f"{room.value}: {len(files)} files")
            for path in files[:12]:
                lines.append(f"  - {path.relative_to(self.ws.root).as_posix()}")
            if len(files) > 12:
                lines.append(f"  - … {len(files) - 12} more")
        return lines

    def clear(self, arg=None):
        scope, ref = self._parse_clear_arg(arg)
        if scope is None:
            return f"{ct.RED}Usage: clear [clean|all] [owner/repo]{ct.RESET}"
        missing = self._need_workspace(ref)
        if missing:
            return missing
        if scope == "all":
            if not self.app.view.confirm(
                f"Wipe dirty, analysis, spec, and clean rooms for {self.ws.label}?"
            ):
                return "Clear cancelled."
            label = self.ws.label
            if self.ws.root.exists():
                shutil.rmtree(self.ws.root)
            if not self.repo:
                self.ws = None
                Workspace.forget_current()
            self.last_verdict = None
            return f"All rooms cleared for {label}. Workspace folder deleted."
        if self.ws.clean_dir.exists():
            shutil.rmtree(self.ws.clean_dir)
        self.ws.clean_dir.mkdir(parents=True, exist_ok=True)
        self.ws.clear_session()
        self.ws.log("CLEAR clean")
        return f"Clean room cleared for {self.ws.label}."

    def unknown(self, value: str):
        return (
            f'{ct.RED}Unknown command: "{value}"!{ct.RESET}'
            f'{ct.DIM} For a list of all available commands try "help".{ct.RESET}'
        )

    def _need_target(self):
        if self.repo and self.ws:
            return None
        self._restore_workspace()
        if self.ws:
            return (
                f"{ct.RED}No live target.{ct.RESET} Workspace {self.ws.label} is on disk. "
                f'Run "target {self.ws.label}" to attach it for inspect/fetch, '
                f'or "continue" to resume specify/implement from disk.'
            )
        return f'{ct.RED}No target. Use "target owner/repo" first.{ct.RESET}'

    def _need_pipeline_workspace(self, ref: str | None = None):
        missing = self._need_workspace(ref)
        if missing:
            return missing
        if self.ws:
            self.ws.remember()
        return None

    def _repo_label(self) -> str:
        if self.repo:
            return str(self.repo)
        return self.ws.label if self.ws else "unknown"

    def _need_workspace(self, ref: str | None = None):
        if ref:
            attached = self._attach_workspace(ref)
            if attached:
                return attached
            return None
        if self.ws and self.ws.present:
            return None
        self._restore_workspace()
        if self.ws and self.ws.present:
            return None
        found = Workspace.discover()
        if len(found) == 1:
            self.ws = found[0]
            return None
        if found:
            return (
                f"{ct.RED}Multiple workspaces on disk.{ct.RESET} "
                f'{ct.DIM}Use "rooms list" then "rooms owner/repo" or "clear all owner/repo".{ct.RESET}'
            )
        return f'{ct.RED}No workspace on disk. Use "target owner/repo" first.{ct.RESET}'

    def _restore_workspace(self):
        if self.ws and self.ws.present:
            return
        current = Workspace.load_current()
        if current:
            self.ws = current
            return
        found = Workspace.discover()
        if len(found) == 1:
            self.ws = found[0]

    def _attach_workspace(self, ref: str) -> str | None:
        parsed = parse_repo_ref(ref)
        if not parsed:
            return f'{ct.RED}Could not parse "{ref}" as owner/repo.{ct.RESET}'
        owner, repo = parsed
        ws = Workspace(owner, repo)
        if not ws.present:
            return f'{ct.RED}No on-disk workspace for {owner}/{repo}.{ct.RESET}'
        self.ws = ws
        if self.repo and str(self.repo) != ws.label:
            self.repo = None
        return None

    def _rooms_index(self):
        found = Workspace.discover()
        if not found:
            return 'No workspaces on disk. Use "target owner/repo" first.'
        current = self.ws.label if self.ws else None
        remembered = Workspace.load_current()
        remembered_label = remembered.label if remembered else None
        lines = [f"On-disk workspaces ({len(found)}):"]
        for ws in found:
            counts = ws.summary()
            mark = "*" if ws.label == current else " "
            tags = []
            if ws.label == current:
                tags.append("current")
            if remembered_label == ws.label and ws.label != current:
                tags.append("last")
            tag = f" ({', '.join(tags)})" if tags else ""
            lines.append(
                f"  {mark} {ws.label:28} dirty {counts['dirty']:<4} "
                f"analysis {counts['analysis']:<4} spec {counts['spec']:<4} "
                f"clean {counts['clean']:<4} stage {ws.pipeline_stage()}{tag}"
            )
        lines.append('Use "rooms owner/repo", "continue owner/repo", or "clear all owner/repo".')
        return lines

    def _split_workspace_arg(self, arg: str | None) -> tuple[str | None, str | None]:
        if not arg:
            return None, None
        verb, _, rest = arg.strip().partition(" ")
        verb = verb.lower()
        if verb == "list":
            return "list", rest.strip() or None
        return None, arg.strip()

    def _parse_clear_arg(self, arg: str | None) -> tuple[str | None, str | None]:
        if not arg:
            return "clean", None
        parts = arg.split()
        scope = "clean"
        ref_parts = []
        for part in parts:
            low = part.lower()
            if low in {"clean", "all"}:
                scope = low
            else:
                ref_parts.append(part)
        ref = " ".join(ref_parts) or None
        if ref and parse_repo_ref(ref) is None and "/" not in ref:
            return None, None
        return scope, ref

    def _need_ai(self):
        if self.ai.ready:
            return None
        return f"{ct.RED}{self.ai.status_line()}.{ct.RESET}"

    def _need_dirty(self):
        if self.ws and self.ws.list_files(Room.DIRTY):
            return None
        return f'{ct.RED}Dirty room is empty. Run "fetch" first.{ct.RESET}'

    def _customize(self):
        if self.repo:
            meta = self.repo.meta or {}
            readme = self.repo.readme()
            label = str(self.repo)
        else:
            inspect = self.ws.inspect_data()
            meta = inspect.get("meta") or {}
            readme = self._local_readme()
            label = self.ws.label
        tree = tree_listing(self.ws.source_root())
        user = (
            f"Repository: {label}\n"
            f"Description: {meta.get('description') or '(none)'}\n"
            f"Language: {meta.get('language') or '(unknown)'}\n"
            f"Default branch: {meta.get('default_branch') or '?'}\n\n"
            f"## README\n{readme or '(no README)'}\n\n"
            f"## File tree\n{tree or '(empty)'}"
        )
        try:
            brief = self._complete("prompt_customizer.md", user, step="brief")
        except Exception as exc:
            return f"{ct.RED}Brief failed: {exc}{ct.RESET}"
        path = self.ws.write_text(Room.ANALYSIS, "brief.md", brief)
        self.ws.log(f"CUSTOMIZE model={self.ai.model}")
        self.app.view.display(f"Dirty-room brief written to {path}.")
        return None

    def _local_readme(self) -> str:
        root = self.ws.source_root()
        for name in ("README.md", "README.rst", "README.txt", "Readme.md", "README"):
            path = root / name
            if path.is_file():
                return path.read_text(encoding="utf-8", errors="replace")[:20_000]
        return ""

    def _complete(self, prompt_name: str, user_content: str, step: str) -> str:
        system = load_prompt(prompt_name)
        sent = len(system) + len(user_content)
        detail = (
            f"{self.ai.model} via {self.ai.provider_id} · "
            f"sending {sent:,} chars (~{estimate_tokens(system + user_content):,} tok est.)"
        )
        job = Job(self.app.view, title=f"{step} · {prompt_name}", detail=detail)
        try:
            text = self.ai.chat(
                [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_content},
                ],
                on_event=job.event,
            )
        except Exception:
            job.finish(ok=False)
            raise
        job.finish(ok=True)
        return text

    def _license_report(self, license_info: dict, verdict: str, meta: dict) -> str:
        spdx = license_info.get("spdx_id") or "NONE"
        name = license_info.get("name") or "Unknown"
        desc = meta.get("description") or "(no description)"
        language = meta.get("language") or "?"
        notes = {
            cl.VERDICT_PERMISSIVE: (
                "Permissive. You may study this repo. Clean-room is still the way "
                "to keep the new work from being a derivative of the source text."
            ),
            cl.VERDICT_WEAK: (
                "Weak copyleft. Studying is usually fine; file-level obligations "
                "do not vanish if you copy source. Stay behind the wall."
            ),
            cl.VERDICT_STRONG: (
                "Strong copyleft. A clean-room clone you then license permissively "
                "is legally sensitive. This tool does not make that safe."
            ),
            cl.VERDICT_NONE: (
                "No license or all rights reserved. You need permission from the "
                "copyright holder before using this repo as a clean-room source."
            ),
            cl.VERDICT_UNKNOWN: (
                "Unrecognised SPDX id. Read the actual license before you continue."
            ),
        }
        return (
            f"{self.repo} — {desc}\n"
            f"Language: {language}. License: {name} ({spdx}). Verdict: {verdict}.\n"
            f"{notes[verdict]}\n"
            f"This is a process check, not a legal audit."
        )

    def _license_gate(self):
        report = self.inspect()
        self.app.view.display(report)
        verdict = self.last_verdict
        if verdict == cl.VERDICT_NONE:
            self.app.view.display(
                f"{ct.RED}Type PERMISSION if you have written permission "
                f"from the copyright holder.{ct.RESET}"
            )
            answer = self.app.view.get_input()
            if answer != "PERMISSION":
                self.ws.log("GATE denied no-license")
                return f"{ct.RED}Pipeline stopped: no license / no permission.{ct.RESET}"
            self.ws.log("GATE override PERMISSION")
            return None
        if verdict in {cl.VERDICT_STRONG, cl.VERDICT_UNKNOWN}:
            if not self.app.view.confirm("Continue the clean-room pipeline anyway?"):
                self.ws.log(f"GATE denied {verdict}")
                return f"{ct.RED}Pipeline stopped at the license gate.{ct.RESET}"
            self.ws.log(f"GATE accepted {verdict}")
            return None
        if not self.app.view.confirm("Proceed with fetch → analyze → specify → implement?"):
            self.ws.log(f"GATE declined {verdict}")
            return "Pipeline cancelled."
        self.ws.log(f"GATE accepted {verdict}")
        return None


