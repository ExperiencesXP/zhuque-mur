import json
import os
import stat
from pathlib import Path


def auth_dir() -> Path:
    override = os.environ.get("ZHUQUE_AUTH_DIR")
    if override:
        return Path(override)
    return Path.home() / ".zhuque-mur"


def auth_path() -> Path:
    return auth_dir() / "auth.json"


def load_store() -> dict:
    path = auth_path()
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def save_store(data: dict) -> Path:
    folder = auth_dir()
    folder.mkdir(parents=True, exist_ok=True)
    path = auth_path()
    payload = json.dumps(data, indent=2, sort_keys=True)
    path.write_text(payload + "\n", encoding="utf-8")
    try:
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass
    return path


def get_entry(provider: str) -> dict | None:
    entry = load_store().get(provider)
    return entry if isinstance(entry, dict) else None


def put_entry(provider: str, entry: dict) -> Path:
    data = load_store()
    data[provider] = entry
    return save_store(data)


def delete_entry(provider: str) -> bool:
    data = load_store()
    if provider not in data:
        return False
    del data[provider]
    save_store(data)
    return True


def list_entries() -> dict:
    return load_store()


def mask_secret(value: str | None) -> str:
    if not value:
        return "(none)"
    if len(value) <= 8:
        return "••••"
    return f"{value[:4]}…{value[-4:]}"
