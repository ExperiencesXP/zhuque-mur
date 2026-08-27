import json
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

from utils.paths import workspace_root

CURRENT_NAME = "current.json"
SESSION_NAME = "session.json"

STAGE_FETCH = "fetch"
STAGE_ANALYZE = "analyze"
STAGE_SPECIFY = "specify"
STAGE_IMPLEMENT = "implement"
STAGE_DONE = "done"


class Room(str, Enum):
    DIRTY = "dirty"
    ANALYSIS = "analysis"
    SPEC = "spec"
    CLEAN = "clean"


class IsolationError(PermissionError):
    """Raised when a room tries to read or write across the firewall."""


class Workspace:
    """On-disk rooms for one target repository.

    dirty/     original source — analyst only
    analysis/  brief + reverse-engineering notes — analyst and specifier
    spec/      requirements spec — the only bridge into the clean room
    clean/     independent implementation — implementer only
    """

    def __init__(self, owner: str, repo: str, root: Path | None = None):
        self.owner = owner
        self.repo = repo
        self.root = Path(root) if root else workspace_root() / f"{owner}__{repo}"
        self.dirty_dir = self.root / Room.DIRTY.value
        self.analysis_dir = self.root / Room.ANALYSIS.value
        self.spec_dir = self.root / Room.SPEC.value
        self.clean_dir = self.root / Room.CLEAN.value
        self.log_path = self.root / "run.log"

    def prepare(self) -> None:
        for path in (self.dirty_dir, self.analysis_dir, self.spec_dir, self.clean_dir):
            path.mkdir(parents=True, exist_ok=True)

    def _dir_for(self, room: Room) -> Path:
        return {
            Room.DIRTY: self.dirty_dir,
            Room.ANALYSIS: self.analysis_dir,
            Room.SPEC: self.spec_dir,
            Room.CLEAN: self.clean_dir,
        }[room]

    def _allowed_read(self, room: Room) -> tuple[Path, ...]:
        if room == Room.DIRTY:
            return (self.dirty_dir,)
        if room == Room.ANALYSIS:
            return (self.dirty_dir, self.analysis_dir)
        if room == Room.SPEC:
            return (self.analysis_dir, self.spec_dir)
        return (self.spec_dir, self.clean_dir)

    def _allowed_write(self, room: Room) -> Path:
        if room == Room.DIRTY:
            return self.dirty_dir
        if room == Room.ANALYSIS:
            return self.analysis_dir
        if room == Room.SPEC:
            return self.spec_dir
        return self.clean_dir

    def _resolve_under(self, base: Path, relative: str | Path) -> Path:
        candidate = (base / relative).resolve()
        base_resolved = base.resolve()
        if candidate != base_resolved and base_resolved not in candidate.parents:
            raise IsolationError(f"Path escapes room: {relative}")
        return candidate

    def _assert_readable(self, room: Room, path: Path) -> None:
        allowed = tuple(p.resolve() for p in self._allowed_read(room))
        resolved = path.resolve()
        for root in allowed:
            if resolved == root or root in resolved.parents:
                return
        raise IsolationError(
            f"{room.value} room cannot read {path}. "
            f"Allowed: {', '.join(p.name for p in allowed)}."
        )

    def read_text(self, room: Room, relative: str | Path) -> str:
        roots = self._allowed_read(room)
        escapes = 0
        for root in roots:
            try:
                path = self._resolve_under(root, relative)
            except IsolationError:
                escapes += 1
                continue
            if path.is_file():
                self._assert_readable(room, path)
                return path.read_text(encoding="utf-8", errors="replace")
        if escapes == len(roots):
            raise IsolationError(f"{room.value} room cannot read {relative}.")
        raise FileNotFoundError(f"{relative} is not visible to the {room.value} room")

    def write_text(self, room: Room, relative: str | Path, content: str) -> Path:
        dest_root = self._allowed_write(room)
        path = self._resolve_under(dest_root, relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def delete_text(self, room: Room, relative: str | Path) -> Path:
        dest_root = self._allowed_write(room)
        path = self._resolve_under(dest_root, relative)
        if not path.is_file():
            raise FileNotFoundError(f"{relative} is not in the {room.value} room")
        path.unlink()
        return path

    def exists(self, room: Room, relative: str | Path) -> bool:
        path = self._dir_for(room) / relative
        return path.is_file()

    def list_files(self, room: Room) -> list[Path]:
        root = self._dir_for(room)
        if not root.exists():
            return []
        return sorted(p for p in root.rglob("*") if p.is_file())

    def relative_files(self, room: Room) -> list[str]:
        root = self._dir_for(room)
        return [path.relative_to(root).as_posix() for path in self.list_files(room)]

    def source_root(self) -> Path:
        if not self.dirty_dir.exists():
            return self.dirty_dir
        children = [p for p in self.dirty_dir.iterdir() if p.is_dir()]
        files = [p for p in self.dirty_dir.iterdir() if p.is_file()]
        if len(children) == 1 and not files:
            return children[0]
        return self.dirty_dir

    def write_root(self, name: str, content: str) -> Path:
        if Path(name).name != name:
            raise IsolationError("Workspace root writes must be a single filename")
        self.root.mkdir(parents=True, exist_ok=True)
        path = self.root / name
        path.write_text(content, encoding="utf-8")
        return path

    def log(self, event: str) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        with self.log_path.open("a", encoding="utf-8") as handle:
            handle.write(f"{stamp} {event}\n")

    def summary(self) -> dict[str, int]:
        return {room.value: len(self.list_files(room)) for room in Room}

    def inspect_data(self) -> dict:
        path = self.root / "inspect.json"
        if not path.is_file():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return data if isinstance(data, dict) else {}

    def pipeline_stage(self) -> str:
        if not self.list_files(Room.DIRTY):
            return STAGE_FETCH
        if not self.exists(Room.SPEC, "specification.md"):
            if not self.exists(Room.ANALYSIS, "analysis.md"):
                return STAGE_ANALYZE
            return STAGE_SPECIFY
        session = self.load_session()
        status = (session or {}).get("status")
        if status in {"in_progress", "paused"}:
            return STAGE_IMPLEMENT
        if status == "done":
            return STAGE_DONE
        if self.list_files(Room.CLEAN):
            return STAGE_DONE
        return STAGE_IMPLEMENT

    def session_path(self) -> Path:
        return self.root / SESSION_NAME

    def load_session(self) -> dict | None:
        path = self.session_path()
        if not path.is_file():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return data if isinstance(data, dict) else None

    def save_session(self, data: dict) -> Path:
        payload = dict(data)
        payload["updated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        messages = payload.get("messages")
        raw = json.dumps(payload, ensure_ascii=False)
        if isinstance(messages, list) and len(raw.encode("utf-8")) > 2_000_000:
            payload["messages"] = _compact_messages(messages)
            raw = json.dumps(payload, ensure_ascii=False)
        self.root.mkdir(parents=True, exist_ok=True)
        path = self.session_path()
        path.write_text(raw + "\n", encoding="utf-8")
        return path

    def clear_session(self) -> None:
        path = self.session_path()
        if path.is_file():
            path.unlink()

    @property
    def label(self) -> str:
        return f"{self.owner}/{self.repo}"

    @property
    def present(self) -> bool:
        return self.root.is_dir()

    @classmethod
    def from_folder(cls, path: Path) -> "Workspace | None":
        if not path.is_dir() or "__" not in path.name:
            return None
        owner, repo = path.name.split("__", 1)
        if not owner or not repo:
            return None
        return cls(owner, repo, root=path)

    @classmethod
    def discover(cls) -> list["Workspace"]:
        root = workspace_root()
        if not root.exists():
            return []
        found = []
        for child in sorted(root.iterdir()):
            ws = cls.from_folder(child)
            if ws:
                found.append(ws)
        return found

    def remember(self) -> Path:
        folder = workspace_root()
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / CURRENT_NAME
        path.write_text(
            json.dumps({"owner": self.owner, "repo": self.repo}, indent=2) + "\n",
            encoding="utf-8",
        )
        return path

    @classmethod
    def forget_current(cls) -> None:
        path = workspace_root() / CURRENT_NAME
        if path.is_file():
            path.unlink()

    @classmethod
    def load_current(cls) -> "Workspace | None":
        path = workspace_root() / CURRENT_NAME
        if not path.is_file():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        owner, repo = data.get("owner"), data.get("repo")
        if not owner or not repo:
            return None
        ws = cls(str(owner), str(repo))
        return ws if ws.present else None


def _compact_messages(messages: list) -> list:
    keep_tail = 8
    head, tail = messages[:-keep_tail], messages[-keep_tail:]
    compacted = []
    for message in head:
        if not isinstance(message, dict) or message.get("role") != "tool":
            compacted.append(message)
            continue
        compacted.append(
            {
                **message,
                "content": json.dumps({"ok": True, "compacted": True}),
            }
        )
    return compacted + tail
