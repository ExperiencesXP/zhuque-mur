from constants.models import DEFAULT_MODEL
from constants.providers import PROVIDERS, provider_meta
from utils.auth_store import list_entries


def sdk_from_model(model: str) -> list[str] | None:
    meta = meta_from_model(model)
    return meta["sdks"] if meta else None


def _sdk_options_for(provider: str | None, compat: str | None) -> list[str]:
    if compat == "anthropic":
        return ["Anthropic API"]
    if provider == "openai":
        return ["OpenAI SDK"]
    return ["OpenAI SDK"]


def _known_provider_for_unqualified(model: str) -> str | None:
    for name, meta in PROVIDERS.items():
        listed = meta.get("models") or []
        if model in listed:
            return name
    return None


def provider_from_model(model: str) -> str | None:
    if "/" in model:
        provider, _, rest = model.partition("/")
        if rest and (provider_meta(provider) or provider in list_entries() or provider.startswith("byok")):
            return provider
    return _known_provider_for_unqualified(model)


def meta_from_model(model: str) -> dict | None:
    provider = provider_from_model(model)
    if not provider:
        return None
    meta = provider_meta(provider) or {}
    return {
        "provider": provider,
        "env": meta.get("env"),
        "base_url": meta.get("base_url"),
        "sdks": _sdk_options_for(provider, meta.get("compat")),
    }


def is_valid_model(model: str) -> bool:
    if not model:
        return False
    model = model.strip()
    if not model:
        return False
    if model in {item for meta in PROVIDERS.values() for item in (meta.get("models") or [])}:
        return True
    if "/" not in model:
        return False
    provider, _, rest = model.partition("/")
    if not rest:
        return False
    return bool(provider_meta(provider) or provider in list_entries() or provider.startswith("byok"))


def resolve_model(name: str | None) -> str | None:
    if not name:
        return DEFAULT_MODEL
    return name if is_valid_model(name) else None


def catalog_models_for(provider: str) -> list[str]:
    extra = list((provider_meta(provider) or {}).get("models") or [])
    seen = []
    for item in extra:
        if item not in seen:
            seen.append(item)
    return seen


def all_provider_ids() -> list[str]:
    names = set(PROVIDERS)
    names.update(list_entries())
    return sorted(names)
