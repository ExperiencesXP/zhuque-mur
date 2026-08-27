import re
import threading
import time


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4) if text else 0


def preview_text(text: str, limit: int = 72) -> str:
    cleaned = re.sub(r"\s+", " ", (text or "")).strip()
    if not cleaned:
        return ""
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[-limit:]


def format_seconds(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes, rem = divmod(int(seconds), 60)
    return f"{minutes}m{rem:02d}s"


class Job:
    """Background ticker so a blocked HTTP call still shows elapsed time."""

    def __init__(self, view, title: str, detail: str = ""):
        self.view = view
        self.title = title
        self.detail = detail
        self.phase = "connecting"
        self.started = time.monotonic()
        self.first_token_at: float | None = None
        self.last_token_at: float | None = None
        self.chars = 0
        self.chunks = 0
        self.preview = ""
        self.usage: dict | None = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._start_view()
        self._thread = threading.Thread(target=self._tick, daemon=True)
        self._thread.start()

    def _start_view(self) -> None:
        start = getattr(self.view, "job_start", None)
        if start:
            start(self.snapshot())

    def snapshot(self) -> dict:
        now = time.monotonic()
        with self._lock:
            elapsed = now - self.started
            wait = None if self.first_token_at else elapsed
            stall = None
            if self.last_token_at:
                stall = now - self.last_token_at
            rate = 0.0
            if self.first_token_at and now > self.first_token_at:
                out_tokens = self.usage.get("completion_tokens") if self.usage else estimate_tokens(
                    "x" * self.chars
                )
                rate = out_tokens / max(0.001, now - self.first_token_at)
            return {
                "title": self.title,
                "detail": self.detail,
                "phase": self.phase,
                "elapsed": elapsed,
                "wait": wait,
                "stall": stall,
                "chars": self.chars,
                "chunks": self.chunks,
                "preview": self.preview,
                "usage": self.usage,
                "rate": rate,
            }

    def _tick(self) -> None:
        while not self._stop.wait(0.4):
            update = getattr(self.view, "job_update", None)
            if update:
                update(self.snapshot())

    def event(self, kind: str, **payload) -> None:
        with self._lock:
            now = time.monotonic()
            if kind == "waiting":
                self.phase = "waiting"
            elif kind == "delta":
                text = payload.get("text") or ""
                self.phase = "streaming"
                self.chars += len(text)
                self.chunks += 1
                if self.first_token_at is None:
                    self.first_token_at = now
                self.last_token_at = now
                full = payload.get("full") or ""
                self.preview = preview_text(full)
            elif kind == "tool":
                self.phase = "tool"
                name = payload.get("name") or "tool"
                path = payload.get("path") or ""
                self.preview = preview_text(f"{name} {path}".strip())
                self.chunks += 1
                self.last_token_at = now
            elif kind == "usage":
                self.usage = {
                    "prompt_tokens": payload.get("prompt_tokens"),
                    "completion_tokens": payload.get("completion_tokens"),
                    "total_tokens": payload.get("total_tokens"),
                }
        update = getattr(self.view, "job_update", None)
        if update:
            update(self.snapshot())

    def finish(self, ok: bool = True, extra: str = "") -> dict:
        self.phase = "done" if ok else "failed"
        self._stop.set()
        self._thread.join(timeout=1)
        snap = self.snapshot()
        snap["extra"] = extra
        finish = getattr(self.view, "job_finish", None)
        if finish:
            finish(snap)
        return snap

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type:
            self.finish(ok=False, extra=str(exc))
        return False
