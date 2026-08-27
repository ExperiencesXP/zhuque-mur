from pathlib import Path

from dotenv import dotenv_values

from utils.paths import project_root


def _env_files() -> list[Path]:
    files = []
    cwd = Path.cwd() / ".env"
    root = project_root() / ".env"
    if cwd.exists():
        files.append(cwd)
    if root.exists() and root != cwd:
        files.append(root)
    return files


def env_map() -> dict:
    merged = {}
    for path in _env_files():
        merged.update({k: v for k, v in dotenv_values(path).items() if v})
    return merged


def env_val(key: str) -> str | None:
    return env_map().get(key)
