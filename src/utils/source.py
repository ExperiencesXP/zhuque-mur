import re
from pathlib import Path

SKIP_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    "dist",
    "build",
    "target",
    "vendor",
    ".idea",
    ".vscode",
}

SKIP_EXTS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".ico",
    ".bmp",
    ".pdf",
    ".zip",
    ".gz",
    ".tar",
    ".7z",
    ".exe",
    ".dll",
    ".so",
    ".dylib",
    ".wasm",
    ".pyc",
    ".pyo",
    ".class",
    ".o",
    ".a",
    ".woff",
    ".woff2",
    ".ttf",
    ".eot",
    ".mp3",
    ".mp4",
    ".wav",
    ".lock",
}

TEXT_HINTS = {
    ".md",
    ".txt",
    ".rst",
    ".py",
    ".js",
    ".ts",
    ".tsx",
    ".jsx",
    ".mjs",
    ".cjs",
    ".java",
    ".kt",
    ".go",
    ".rs",
    ".c",
    ".h",
    ".cc",
    ".cpp",
    ".hpp",
    ".cs",
    ".rb",
    ".php",
    ".swift",
    ".m",
    ".mm",
    ".scala",
    ".sh",
    ".bash",
    ".zsh",
    ".ps1",
    ".json",
    ".yml",
    ".yaml",
    ".toml",
    ".ini",
    ".cfg",
    ".xml",
    ".html",
    ".css",
    ".scss",
    ".sql",
    ".graphql",
    ".vue",
    ".svelte",
}

MAX_FILE_BYTES = 80_000
MAX_TOTAL_BYTES = 350_000

FILE_BLOCK = re.compile(
    r"^### FILE:\s*(?P<path>[^\n]+)\s*\n```(?:[^\n]*)\n(?P<body>.*?)\n```",
    re.MULTILINE | re.DOTALL,
)


def is_probably_text(path: Path) -> bool:
    if path.suffix.lower() in SKIP_EXTS:
        return False
    if path.suffix.lower() in TEXT_HINTS:
        return True
    try:
        chunk = path.read_bytes()[:512]
    except OSError:
        return False
    if b"\x00" in chunk:
        return False
    return True


def iter_source_files(root: Path) -> list[Path]:
    files = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if not is_probably_text(path):
            continue
        files.append(path)
    return files


def pack_source(root: Path, budget: int = MAX_TOTAL_BYTES) -> tuple[str, list[str], list[str]]:
    """Return (packed text, included relative paths, omitted relative paths)."""
    included = []
    omitted = []
    parts = []
    used = 0
    for path in iter_source_files(root):
        relative = path.relative_to(root).as_posix()
        try:
            size = path.stat().st_size
        except OSError:
            omitted.append(relative)
            continue
        if size > MAX_FILE_BYTES or used + min(size, MAX_FILE_BYTES) > budget:
            omitted.append(relative)
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        block = f"### FILE: {relative}\n```\n{text}\n```\n"
        parts.append(block)
        included.append(relative)
        used += len(block.encode("utf-8"))
    return "\n".join(parts), included, omitted


def tree_listing(root: Path, limit: int = 400) -> str:
    lines = []
    for path in iter_source_files(root):
        lines.append(path.relative_to(root).as_posix())
        if len(lines) >= limit:
            lines.append("…")
            break
    return "\n".join(lines)


def safe_relative(path: str | None) -> str | None:
    """Return a room-relative path, or None if it would escape."""
    relative = (path or "").strip().replace("\\", "/")
    while relative.startswith("./"):
        relative = relative[2:]
    if not relative or relative.startswith("/") or relative.startswith("../") or relative == "..":
        return None
    if Path(relative).is_absolute():
        return None
    if any(part in {"..", ""} for part in Path(relative).parts):
        return None
    return relative


def parse_file_blocks(text: str) -> list[tuple[str, str]]:
    files = []
    for match in FILE_BLOCK.finditer(text):
        relative = safe_relative(match.group("path"))
        if not relative:
            continue
        files.append((relative, match.group("body")))
    return files
