import json
from pathlib import Path

from utils.auth_store import get_entry, put_entry
from utils.secrets import env_map


def opencode_auth_paths() -> list[Path]:
    home = Path.home()
    return [
        home / ".local" / "share" / "opencode" / "auth.json",
        home / "AppData" / "Roaming" / "opencode" / "auth.json",
        home / "AppData" / "Local" / "opencode" / "auth.json",
        home / ".config" / "opencode" / "auth.json",
    ]


def _normalize_opencode_entry(raw: dict) -> dict | None:
    if not isinstance(raw, dict):
        return None
    kind = raw.get("type")
    if kind in {"api", "api_key"} or raw.get("key") or raw.get("apiKey"):
        key = raw.get("key") or raw.get("apiKey") or raw.get("api_key")
        if not key:
            return None
        entry = {"type": "api_key", "key": key}
        if raw.get("baseURL") or raw.get("base_url"):
            entry["base_url"] = raw.get("baseURL") or raw.get("base_url")
        return entry
    if kind == "oauth" or raw.get("access") or raw.get("access_token") or raw.get("refresh"):
        access = raw.get("access_token") or raw.get("access")
        refresh = raw.get("refresh_token") or raw.get("refresh")
        if not access and not refresh:
            return None
        return {
            "type": "oauth",
            "access_token": access,
            "refresh_token": refresh,
            "expires_at": raw.get("expires_at") or raw.get("expires"),
            "client_id": raw.get("client_id") or raw.get("clientID"),
            "token_endpoint": raw.get("token_endpoint"),
        }
    return None


def import_opencode() -> list[str]:
    imported = []
    for path in opencode_auth_paths():
        if not path.is_file():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        for name, raw in payload.items():
            if get_entry(name):
                continue
            entry = _normalize_opencode_entry(raw)
            if not entry:
                continue
            entry["imported_from"] = str(path)
            put_entry(name, entry)
            imported.append(name)
    return imported


def import_env_keys() -> list[str]:
    from constants.providers import PROVIDERS

    imported = []
    values = env_map()
    for name, meta in PROVIDERS.items():
        env_name = meta.get("env")
        if not env_name or not values.get(env_name):
            continue
        if get_entry(name):
            continue
        entry = {"type": "api_key", "key": values[env_name], "imported_from": "env"}
        if meta.get("base_url"):
            entry["base_url"] = meta["base_url"]
        put_entry(name, entry)
        imported.append(name)
    return imported
