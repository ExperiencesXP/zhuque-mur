# Auth catalog. OAuth is only wired where the vendor publishes a third-party
# or public native-app flow. Subscription logins that vendors forbid for
# third-party tools (Claude Pro/Max, ChatGPT Codex client impersonation)
# are not implemented.

XAI_PUBLIC_CLIENT_ID = "b1a00492-073a-47ea-816f-4c329264a828"

PROVIDERS = {
    "xai": {
        "name": "xAI (SpaceXAI)",
        "auth": ("oauth", "api_key"),
        "env": "XAI_API_KEY",
        "base_url": "https://api.x.ai/v1",
        "key_url": "https://console.x.ai/team/default/api-keys",
        "compat": "openai",
        "oauth": {
            "kind": "device",
            "issuer": "https://auth.x.ai",
            "client_id_env": "XAI_OAUTH_CLIENT_ID",
            "client_id": XAI_PUBLIC_CLIENT_ID,
            "scope": "openid profile email offline_access grok-cli:access api:access",
        },
        "models": ["grok-4.6", "grok-4.5", "grok-4.3", "grok-build-0.1"],
    },
    "openai": {
        "name": "OpenAI",
        "auth": ("api_key",),
        "env": "OPENAI_API_KEY",
        "base_url": "https://api.openai.com/v1",
        "key_url": "https://platform.openai.com/api-keys",
        "compat": "openai",
        "note": "ChatGPT subscription OAuth is first-party (Codex). Paste an API key.",
        "models": ["gpt-4o", "gpt-4o-mini", "gpt-5", "o1-preview", "o1-mini"],
    },
    "anthropic": {
        "name": "Anthropic",
        "auth": ("api_key",),
        "env": "ANTHROPIC_API_KEY",
        "base_url": "https://api.anthropic.com",
        "key_url": "https://console.anthropic.com/settings/keys",
        "compat": "anthropic",
        "note": "Claude Pro/Max OAuth is not offered to third-party tools. Use an API key.",
        "models": ["claude-sonnet-4-5", "claude-haiku-4-5", "claude-opus-4-5"],
    },
    "google": {
        "name": "Google Gemini",
        "auth": ("api_key",),
        "env": "GEMINI_API_KEY",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "key_url": "https://aistudio.google.com/apikey",
        "compat": "openai",
        "note": "Gemini Developer API uses an API key. Vertex uses ADC (gcloud auth application-default login).",
        "models": ["gemini-2.0-flash", "gemini-1.5-pro", "gemini-1.5-flash"],
    },
    "mistral": {
        "name": "Mistral",
        "auth": ("api_key",),
        "env": "MISTRAL_API_KEY",
        "base_url": "https://api.mistral.ai/v1",
        "key_url": "https://console.mistral.ai/api-keys",
        "compat": "openai",
        "models": ["mistral-large-latest", "pixtral-large-latest"],
    },
    "deepseek": {
        "name": "DeepSeek",
        "auth": ("api_key",),
        "env": "DEEPSEEK_API_KEY",
        "base_url": "https://api.deepseek.com",
        "key_url": "https://platform.deepseek.com/api_keys",
        "compat": "openai",
        "models": ["deepseek-chat", "deepseek-coder"],
    },
    "github": {
        "name": "GitHub",
        "auth": ("api_key",),
        "env": "GITHUB_TOKEN",
        "base_url": "https://api.github.com",
        "key_url": "https://github.com/settings/tokens",
        "compat": "none",
        "note": "Used for the GitHub repo API, not model inference.",
    },
    "azure": {
        "name": "Azure OpenAI",
        "auth": ("api_key",),
        "env": "AZURE_OPENAI_API_KEY",
        "base_url_env": "AZURE_OPENAI_ENDPOINT",
        "key_url": "https://ai.azure.com/",
        "compat": "openai",
        "note": "BYOK: set AZURE_OPENAI_ENDPOINT (…/openai/v1) and the resource key.",
        "models": ["gpt-4o"],
    },
    "neuralwatt": {
        "name": "Neuralwatt",
        "auth": ("api_key",),
        "byok": True,
        "env": "NEURALWATT_API_KEY",
        "base_url": "https://api.neuralwatt.com/v1",
        "key_url": "https://portal.neuralwatt.com",
        "compat": "openai",
        "discover": True,
        "models": ["deepseek-v4-flash"],
    },
    "opencode": {
        "name": "OpenCode Zen",
        "auth": ("api_key",),
        "byok": True,
        "env": "OPENCODE_API_KEY",
        "base_url": "https://opencode.ai/zen/v1",
        "key_url": "https://opencode.ai/auth",
        "compat": "openai",
        "discover": True,
        "models": ["kimi-k2.6", "glm-5.1", "deepseek-v4-flash", "grok-4.6"],
    },
    "opencode-go": {
        "name": "OpenCode Go",
        "auth": ("api_key",),
        "byok": True,
        "env": "OPENCODE_GO_API_KEY",
        "base_url": "https://opencode.ai/zen/go/v1",
        "key_url": "https://opencode.ai/go",
        "compat": "openai",
        "discover": True,
        "models": ["kimi-k2.6", "glm-5.1"],
    },
    "openrouter": {
        "name": "OpenRouter",
        "auth": ("api_key",),
        "byok": True,
        "env": "OPENROUTER_API_KEY",
        "base_url": "https://openrouter.ai/api/v1",
        "key_url": "https://openrouter.ai/settings/keys",
        "compat": "openai",
        "discover": True,
        "models": ["openai/gpt-4o-mini"],
    },
    "groq": {
        "name": "Groq",
        "auth": ("api_key",),
        "byok": True,
        "env": "GROQ_API_KEY",
        "base_url": "https://api.groq.com/openai/v1",
        "key_url": "https://console.groq.com/keys",
        "compat": "openai",
        "discover": True,
        "models": ["llama-3.3-70b-versatile"],
    },
    "together": {
        "name": "Together AI",
        "auth": ("api_key",),
        "byok": True,
        "env": "TOGETHER_API_KEY",
        "base_url": "https://api.together.xyz/v1",
        "key_url": "https://api.together.ai/",
        "compat": "openai",
        "discover": True,
        "models": ["meta-llama/Meta-Llama-3.1-70B-Instruct-Turbo"],
    },
    "ollama": {
        "name": "Ollama (local)",
        "auth": ("api_key",),
        "byok": True,
        "env": "OLLAMA_API_KEY",
        "base_url": "http://127.0.0.1:11434/v1",
        "compat": "openai",
        "discover": True,
        "optional_key": True,
        "models": ["llama3.2"],
    },
}

BYOK_PRESETS = [
    name for name, meta in PROVIDERS.items() if meta.get("byok")
]

OAUTH_PROVIDERS = [
    name for name, meta in PROVIDERS.items() if "oauth" in meta.get("auth", ())
]


def provider_meta(name: str) -> dict | None:
    return PROVIDERS.get((name or "").lower())
