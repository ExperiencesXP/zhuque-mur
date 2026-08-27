import time

import requests

from api.oauth import OAuthError, refresh_tokens
from constants.providers import PROVIDERS, provider_meta
from utils.auth_store import get_entry, list_entries, put_entry
from utils.secrets import env_val


class Credential:
    def __init__(
        self,
        provider: str,
        token: str | None,
        base_url: str | None,
        source: str,
        compat: str = "openai",
        model_id: str | None = None,
    ):
        self.provider = provider
        self.token = token
        self.base_url = base_url
        self.source = source
        self.compat = compat
        self.model_id = model_id

    @property
    def ready(self) -> bool:
        meta = provider_meta(self.provider) or {}
        if meta.get("optional_key"):
            return bool(self.base_url)
        return bool(self.token and self.base_url)


def split_model(name: str) -> tuple[str | None, str]:
    if "/" in name:
        provider, _, model = name.partition("/")
        if provider_meta(provider) or provider.startswith("byok"):
            return provider, model
        if provider_meta(provider) is None and get_entry(provider):
            return provider, model
    return None, name


def base_url_for(provider: str, entry: dict | None = None) -> str | None:
    if entry and entry.get("base_url"):
        return entry["base_url"].rstrip("/")
    meta = provider_meta(provider) or {}
    env_name = meta.get("base_url_env")
    if env_name:
        value = env_val(env_name)
        if value:
            return value.rstrip("/")
    url = meta.get("base_url")
    return url.rstrip("/") if url else None


def _oauth_token(provider: str, entry: dict) -> str | None:
    expires = int(entry.get("expires_at") or 0)
    if expires and expires < time.time() + 60:
        try:
            refreshed = refresh_tokens(entry)
        except OAuthError:
            return entry.get("access_token")
        put_entry(provider, refreshed)
        return refreshed.get("access_token")
    return entry.get("access_token")


def credential_for(provider: str) -> Credential:
    meta = provider_meta(provider) or {}
    entry = get_entry(provider)
    compat = (entry or {}).get("compat") or meta.get("compat") or "openai"
    url = base_url_for(provider, entry)

    if entry:
        kind = entry.get("type")
        if kind == "oauth":
            return Credential(provider, _oauth_token(provider, entry), url, "oauth", compat)
        if kind in {"api_key", "api"}:
            return Credential(
                provider,
                entry.get("key") or entry.get("api_key") or entry.get("token"),
                url,
                "store",
                compat,
            )

    env_name = meta.get("env")
    token = env_val(env_name) if env_name else None
    if token or meta.get("optional_key"):
        return Credential(provider, token, url, "env" if token else "none", compat)

    return Credential(provider, None, url, "missing", compat)


def _row_value(row, key: str):
    if isinstance(row, dict):
        return row.get(key)
    return getattr(row, key, None)


def _dedupe(values: list[str]) -> list[str]:
    seen = set()
    ordered = []
    for item in values:
        if not item or item in seen:
            continue
        seen.add(item)
        ordered.append(item)
    return ordered


def _model_ids_from_payload(payload) -> list[str]:
    rows = payload
    if isinstance(payload, dict):
        for key in ("data", "models", "items", "result"):
            value = payload.get(key)
            if isinstance(value, list):
                rows = value
                break
    ids = []
    if isinstance(rows, list):
        for row in rows:
            if isinstance(row, str):
                ids.append(row)
                continue
            for key in ("id", "name", "model", "slug"):
                value = _row_value(row, key)
                if isinstance(value, str) and value.strip():
                    ids.append(value.strip())
                    break
    return _dedupe(ids)


def _openai_sdk_models(cred: Credential) -> list[str]:
    from openai import OpenAI

    client = OpenAI(api_key=cred.token or "local", base_url=cred.base_url)
    listing = client.models.list()
    data = getattr(listing, "data", listing)
    return _model_ids_from_payload(data)


def list_remote_models(provider: str, cred: Credential) -> list[str]:
    if not cred.base_url:
        return []
    provider = (provider or "").lower()
    base_url = cred.base_url.rstrip("/")

    if provider == "openai":
        models = _openai_sdk_models(cred)
        if models:
            return models

    headers = {"Accept": "application/json"}
    if cred.token:
        headers["Authorization"] = f"Bearer {cred.token}"
    if provider == "anthropic" and cred.token:
        headers["x-api-key"] = cred.token
        headers["anthropic-version"] = "2023-06-01"

    if provider == "ollama":
        ollama_root = base_url[:-3] if base_url.endswith("/v1") else base_url
        response = requests.get(f"{ollama_root}/api/tags", headers=headers, timeout=20)
        response.raise_for_status()
        return _model_ids_from_payload(response.json())

    endpoint = f"{base_url}/models"
    if provider == "anthropic":
        endpoint = f"{base_url}/v1/models"

    response = requests.get(endpoint, headers=headers, timeout=20)
    response.raise_for_status()
    return _model_ids_from_payload(response.json())


def known_providers() -> list[str]:
    names = set(PROVIDERS)
    names.update(list_entries())
    return sorted(names)
