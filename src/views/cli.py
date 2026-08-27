import getpass
import shutil
import sys
import textwrap
import threading

import constants.info as ci
import constants.synonyms as cs
import constants.textual as ct
from art import text2art
from utils.progress import estimate_tokens, format_seconds


class CLI:
    def __init__(self):
        self._job_lock = threading.Lock()
        self._live = False
    def welcome(self):
        print(f"{ct.BRIGHT_BLUE}{text2art(ci.PROGRAM_NAME)}{ct.RESET}")
        print(f"{ct.BRIGHT_BLACK}v{ci.VERSION}{ct.RESET}")

    def warning(self):
        print(
            f"{ct.BRIGHT_RED}{ct.DIM}{ct.BOLD}"
            f"WARNING: Educational use only. Do not use on repositories unless you\n"
            f"fully understand and comply with their licenses. All misuse of this\n"
            f"tool is your own responsibility.{ct.RESET}"
            f"{ct.DIM}\nThe wall: analyst reads the original; implementer reads the spec only.\n"
            f'For a list of all available commands try "help".{ct.RESET}'
        )

    def get_input(self, lowercase=False):
        value = input(f"{ct.RESET}< ").strip()
        return value.lower() if lowercase else value

    def confirm(self, question: str) -> bool:
        self.display(f"{question} {ct.DIM}y/n{ct.RESET}")
        return self.get_input(lowercase=True) in cs.YES

    def get_secret(self, prompt="API key (input hidden):"):
        self.display(prompt)
        try:
            return getpass.getpass("").strip()
        except Exception:
            return self.get_input()

    def job_start(self, snap: dict):
        self._end_live()
        self.display(f"{ct.DIM}{snap['title']}{ct.RESET}")
        if snap.get("detail"):
            self.display(f"{ct.DIM}{snap['detail']}{ct.RESET}")
        self._draw_live(snap)

    def job_update(self, snap: dict):
        self._draw_live(snap)

    def job_finish(self, snap: dict):
        self._end_live()
        self.display(self._summary_line(snap))

    def _draw_live(self, snap: dict):
        if not sys.stdout.isatty():
            return
        line = self._status_line(snap)
        width = shutil.get_terminal_size().columns
        if len(line) > width:
            line = line[: max(1, width - 1)]
        with self._job_lock:
            print(f"\r\033[2K{ct.BRIGHT_BLACK}> {ct.RESET}{line}", end="", flush=True)
            self._live = True

    def _end_live(self):
        with self._job_lock:
            if self._live:
                print(flush=True)
                self._live = False

    def _status_line(self, snap: dict) -> str:
        elapsed = format_seconds(snap["elapsed"])
        phase = snap["phase"]
        if phase in {"connecting", "waiting"}:
            wait = snap.get("wait") or snap["elapsed"]
            hint = "waiting for first token"
            if wait >= 30:
                hint = "still thinking — no tokens yet"
            if wait >= 90:
                hint = "no tokens after 90s — may be stalled"
            return f"{ct.YELLOW}[{elapsed}]{ct.RESET} {hint}"
        if phase == "streaming":
            stall = snap.get("stall") or 0
            tokens = estimate_tokens("x" * snap["chars"])
            if snap.get("usage") and snap["usage"].get("completion_tokens"):
                tokens = snap["usage"]["completion_tokens"]
            rate = f"{snap['rate']:.0f}/s" if snap["rate"] else "…"
            stall_bit = ""
            if stall >= 8:
                stall_bit = f" {ct.YELLOW}quiet {format_seconds(stall)}{ct.RESET}"
            preview = snap.get("preview") or ""
            tail = f"  {ct.DIM}{preview}{ct.RESET}" if preview else ""
            return (
                f"{ct.CYAN}[{elapsed}]{ct.RESET} streaming {tokens} tok {rate}"
                f"{stall_bit}{tail}"
            )
        if phase == "tool":
            preview = snap.get("preview") or "tool"
            return f"{ct.CYAN}[{elapsed}]{ct.RESET} {preview}"
        return f"{ct.DIM}[{elapsed}] {phase}{ct.RESET}"

    def _summary_line(self, snap: dict) -> str:
        elapsed = format_seconds(snap["elapsed"])
        usage = snap.get("usage") or {}
        out = usage.get("completion_tokens") or estimate_tokens("x" * snap["chars"])
        inp = usage.get("prompt_tokens")
        extra = snap.get("extra") or ""
        if snap["phase"] == "failed":
            return f"{ct.RED}Failed after {elapsed}.{ct.RESET} {extra}".strip()
        bits = [f"{ct.GREEN}Done{ct.RESET} in {elapsed}", f"{out} output tok"]
        if inp:
            bits.append(f"{inp} input tok")
        if snap["rate"]:
            bits.append(f"{snap['rate']:.0f} tok/s")
        if extra:
            bits.append(extra)
        return " · ".join(bits)

    def display(self, *outputs):
        self._end_live()
        prefix = "> "
        terminal_width = shutil.get_terminal_size().columns
        wrap_width = max(20, terminal_width - len(prefix))

        for output in outputs:
            if output is None:
                continue
            if isinstance(output, (list, tuple)):
                for item in output:
                    self.display(item)
                continue
            text = str(output)
            for raw_line in text.splitlines() or [""]:
                if raw_line == "":
                    print(f"{ct.BRIGHT_BLACK}{prefix}{ct.RESET}")
                    continue
                wrapped = textwrap.fill(raw_line, width=wrap_width)
                for line in wrapped.splitlines():
                    print(f"{ct.BRIGHT_BLACK}{prefix}{ct.RESET}{line}")
