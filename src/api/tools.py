import json

from utils.source import safe_relative
from utils.workspace import IsolationError, Room, Workspace

MAX_READ_CHARS = 80_000

IMPLEMENT_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "list_spec",
            "description": "List files in the specification room. That room is the only original-side material you may see.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_spec",
            "description": "Read a specification-room file. Default path is specification.md. Use offset to page through a long spec.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Relative path under spec/. Defaults to specification.md.",
                    },
                    "offset": {
                        "type": "integer",
                        "description": "Character offset to start reading from.",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum characters to return.",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_clean",
            "description": "List files already written in the clean room.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a file you previously wrote in the clean room (or a spec file, if you pass a spec path).",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "offset": {"type": "integer"},
                    "limit": {"type": "integer"},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Create or replace a file in the clean room. Paths are relative and cannot escape clean/.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_file",
            "description": "Delete a file from the clean room.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "finish",
            "description": "Stop the implementer loop. Write LICENSE and ASSUMPTIONS.md first.",
            "parameters": {
                "type": "object",
                "properties": {
                    "summary": {
                        "type": "string",
                        "description": "Short description of what was implemented.",
                    }
                },
            },
        },
    },
]


class IsolatedTools:
    """Clean-room tools. Bound to Room.CLEAN so dirty/ and analysis/ are unreachable."""

    def __init__(self, ws: Workspace, room: Room = Room.CLEAN):
        if room != Room.CLEAN:
            raise IsolationError("Agent tools are only bound to the clean room")
        self.ws = ws
        self.room = room

    def dispatch(self, name: str, args: dict | None) -> tuple[str, dict]:
        args = args if isinstance(args, dict) else {}
        handler = {
            "list_spec": self.list_spec,
            "read_spec": self.read_spec,
            "list_clean": self.list_clean,
            "read_file": self.read_file,
            "write_file": self.write_file,
            "delete_file": self.delete_file,
            "finish": self.finish,
        }.get(name)
        if handler is None:
            return _result({"ok": False, "error": f"unknown tool: {name}"}), {}
        try:
            return handler(args)
        except IsolationError as exc:
            return _result({"ok": False, "error": f"isolation: {exc}"}), {}
        except FileNotFoundError as exc:
            return _result({"ok": False, "error": str(exc)}), {}
        except (TypeError, ValueError, OSError) as exc:
            return _result({"ok": False, "error": str(exc)}), {}

    def list_spec(self, args: dict) -> tuple[str, dict]:
        files = self.ws.relative_files(Room.SPEC)
        return _result({"ok": True, "files": files, "count": len(files)}), {}

    def list_clean(self, args: dict) -> tuple[str, dict]:
        files = self.ws.relative_files(Room.CLEAN)
        return _result({"ok": True, "files": files, "count": len(files)}), {}

    def read_spec(self, args: dict) -> tuple[str, dict]:
        path = safe_relative(str(args.get("path") or "specification.md"))
        if not path:
            return _result({"ok": False, "error": "invalid path"}), {}
        return self._read(path, args)

    def read_file(self, args: dict) -> tuple[str, dict]:
        path = safe_relative(str(args.get("path") or ""))
        if not path:
            return _result({"ok": False, "error": "invalid path"}), {}
        return self._read(path, args)

    def write_file(self, args: dict) -> tuple[str, dict]:
        path = safe_relative(str(args.get("path") or ""))
        if not path:
            return _result({"ok": False, "error": "invalid path"}), {}
        content = args.get("content")
        if content is None:
            return _result({"ok": False, "error": "content is required"}), {}
        if not isinstance(content, str):
            content = str(content)
        written = self.ws.write_text(self.room, path, content)
        relative = written.relative_to(self.ws.clean_dir).as_posix()
        return (
            _result({"ok": True, "path": relative, "bytes": len(content.encode("utf-8"))}),
            {"written": relative},
        )

    def delete_file(self, args: dict) -> tuple[str, dict]:
        path = safe_relative(str(args.get("path") or ""))
        if not path:
            return _result({"ok": False, "error": "invalid path"}), {}
        deleted = self.ws.delete_text(self.room, path)
        relative = deleted.relative_to(self.ws.clean_dir).as_posix()
        return _result({"ok": True, "path": relative, "deleted": True}), {"deleted": relative}

    def finish(self, args: dict) -> tuple[str, dict]:
        missing = []
        if not (
            self.ws.exists(Room.CLEAN, "LICENSE") or self.ws.exists(Room.CLEAN, "LICENSE.md")
        ):
            missing.append("LICENSE")
        if not self.ws.exists(Room.CLEAN, "ASSUMPTIONS.md"):
            missing.append("ASSUMPTIONS.md")
        if missing:
            return (
                _result(
                    {
                        "ok": False,
                        "error": f"write {', '.join(missing)} before finish",
                        "missing": missing,
                    }
                ),
                {},
            )
        summary = str(args.get("summary") or "")
        files = self.ws.relative_files(Room.CLEAN)
        return (
            _result({"ok": True, "finished": True, "summary": summary, "files": files}),
            {"finished": True, "summary": summary},
        )

    def _read(self, path: str, args: dict) -> tuple[str, dict]:
        text = self.ws.read_text(self.room, path)
        offset = _int_arg(args.get("offset"), 0)
        limit = _int_arg(args.get("limit"), MAX_READ_CHARS)
        offset = max(0, offset)
        limit = min(max(1, limit), MAX_READ_CHARS)
        chunk = text[offset : offset + limit]
        return (
            _result(
                {
                    "ok": True,
                    "path": path,
                    "offset": offset,
                    "length": len(chunk),
                    "total": len(text),
                    "truncated": offset + len(chunk) < len(text),
                    "content": chunk,
                }
            ),
            {},
        )


def parse_tool_args(raw) -> dict:
    if isinstance(raw, dict):
        return raw
    if raw is None:
        return {}
    text = str(raw).strip()
    if not text:
        return {}
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return {"_error": "invalid json", "_raw": text[:500]}
    return data if isinstance(data, dict) else {"_error": "arguments must be an object"}


def _int_arg(value, default: int) -> int:
    if value is None or value == "":
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _result(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False)
