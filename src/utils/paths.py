import os
from importlib.resources import files
from pathlib import Path


def project_root() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "pyproject.toml").is_file():
            return parent
    return Path.cwd()


def src_root() -> Path:
    candidate = project_root() / "src"
    if candidate.is_dir():
        return candidate
    return Path(__file__).resolve().parents[1]


def prompts_dir() -> Path:
    try:
        return Path(str(files("prompts")))
    except (ModuleNotFoundError, TypeError, ValueError):
        return src_root() / "prompts"


def workspace_root() -> Path:
    override = os.environ.get("ZHUQUE_WORKSPACE")
    if override:
        return Path(override)
    in_repo = src_root() / "workspace"
    if in_repo.exists() or (project_root() / "pyproject.toml").is_file():
        return in_repo
    return Path.cwd() / "workspace"


def load_prompt(name: str) -> str:
    try:
        return files("prompts").joinpath(name).read_text(encoding="utf-8")
    except (ModuleNotFoundError, FileNotFoundError, OSError):
        path = src_root() / "prompts" / name
        return path.read_text(encoding="utf-8")
