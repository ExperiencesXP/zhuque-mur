import os

import constants.textual as ct
from api.agent import ChatTurn, ToolsUnsupported
from api.tools import IMPLEMENT_TOOLS, IsolatedTools, parse_tool_args
from utils.paths import load_prompt
from utils.progress import Job, estimate_tokens
from utils.source import parse_file_blocks
from utils.workspace import IsolationError, Room, Workspace

DEFAULT_TURNS = 48
PHASE = "implement"


def max_turns() -> int:
    raw = os.environ.get("ZHUQUE_IMPLEMENT_TURNS")
    if not raw:
        return DEFAULT_TURNS
    try:
        return max(1, int(raw))
    except ValueError:
        return DEFAULT_TURNS


def run_implementer(
    *,
    ws: Workspace,
    ai,
    view,
    license_name: str,
    confirm,
    resume: bool = True,
) -> str:
    tools = IsolatedTools(ws)
    session = ws.load_session() if resume else None
    messages, written, start_turn, resumed = _seed_messages(
        ws, session, license_name, confirm, resume
    )
    if messages is None:
        return written  # cancellation message reused as return

    limit = max_turns()
    model = getattr(ai, "model", None) or "?"
    provider = getattr(ai, "provider_id", None) or "?"
    detail = f"{model} via {provider} · isolated tools · up to {limit} turns"
    if resumed:
        detail += f" · resume turn {start_turn}"
        view.display(
            f"{ct.DIM}Resuming clean-room implementer at turn {start_turn} "
            f"({len(written)} files already on disk).{ct.RESET}"
        )
    job = Job(view, title="implement · clean room", detail=detail)

    def persist(status: str, turn: int, summary: str = "") -> None:
        ws.save_session(
            {
                "version": 1,
                "phase": PHASE,
                "status": status,
                "model": model,
                "provider": provider,
                "turn": turn,
                "written": _uniq(written),
                "summary": summary,
                "messages": messages,
            }
        )

    try:
        persist("in_progress", start_turn)
        for turn in range(start_turn + 1, start_turn + limit + 1):
            job.event("waiting")
            try:
                result = ai.chat_turn(
                    messages,
                    tools=IMPLEMENT_TOOLS,
                    on_event=job.event,
                )
            except ToolsUnsupported:
                job.finish(ok=True, extra="no tools; FILE-block fallback")
                return _oneshot_fallback(ws, ai, view, license_name, messages, written)
            except KeyboardInterrupt:
                persist("paused", turn - 1)
                job.finish(ok=False, extra="interrupted")
                ws.log(f"IMPLEMENT paused turn={turn - 1} files={len(_uniq(written))}")
                return (
                    f"{ct.YELLOW}Implementer paused at turn {turn - 1}. "
                    f'Run "continue" to pick up from {ws.label}.{ct.RESET}'
                )

            assistant = _assistant_message(result)
            messages.append(assistant)
            from_blocks = _write_file_blocks(ws, result.content, written)
            finished, summary = _apply_tool_calls(tools, result, messages, written, job)

            persist("in_progress" if not finished else "done", turn, summary)
            if finished:
                job.finish(ok=True, extra=f"{len(_uniq(written))} files")
                files = _uniq(written) or ws.relative_files(Room.CLEAN)
                ws.log(f"IMPLEMENT model={model} files={len(files)} turns={turn} isolated=true")
                return _done_message(files, summary)

            if not result.tool_calls:
                if from_blocks:
                    messages.append(
                        {
                            "role": "user",
                            "content": (
                                f"Wrote {from_blocks} FILE-block file(s) to the clean room. "
                                "Continue with tools, or call finish if LICENSE and "
                                "ASSUMPTIONS.md are in place."
                            ),
                        }
                    )
                    persist("in_progress", turn)
                    continue
                if result.content:
                    messages.append(
                        {
                            "role": "user",
                            "content": (
                                "Use the tools (read_spec, write_file, finish). "
                                "Do not only chat. Work file by file."
                            ),
                        }
                    )
                    persist("in_progress", turn)
                    continue
                persist("paused", turn)
                job.finish(ok=False, extra="empty response")
                return (
                    f"{ct.YELLOW}Implementer returned an empty turn. "
                    f'Session saved. Run "continue".{ct.RESET}'
                )

        persist("paused", start_turn + limit)
        job.finish(ok=True, extra=f"turn limit {limit}")
        ws.log(f"IMPLEMENT paused turn_limit={limit} files={len(_uniq(written))}")
        return (
            f"{ct.YELLOW}Turn limit ({limit}) reached with {len(_uniq(written))} clean-room "
            f'files. Run "continue" to keep going.{ct.RESET}'
        )
    except KeyboardInterrupt:
        persist("paused", start_turn)
        job.finish(ok=False, extra="interrupted")
        ws.log(f"IMPLEMENT paused files={len(_uniq(written))}")
        return (
            f"{ct.YELLOW}Implementer paused. "
            f'Run "continue" to pick up from {ws.label}.{ct.RESET}'
        )
    except Exception:
        persist("paused", start_turn)
        job.finish(ok=False)
        raise


def _seed_messages(ws: Workspace, session: dict | None, license_name: str, confirm, resume: bool):
    system = load_prompt("implementer.md")
    existing = ws.relative_files(Room.CLEAN)
    if resume and session and session.get("phase") == PHASE and session.get("messages"):
        messages = session["messages"]
        if messages and messages[0].get("role") == "system":
            messages[0]["content"] = system
        written = list(session.get("written") or existing)
        start_turn = int(session.get("turn") or 0)
        status = session.get("status")
        if status == "done":
            if confirm and not confirm(
                f"Implementation already finished ({len(existing)} files). Continue adding files?"
            ):
                return None, "Implement cancelled.", 0, False
            messages.append(
                {
                    "role": "user",
                    "content": (
                        "Continue improving the clean-room implementation. "
                        "Call list_clean, then add or revise files. Call finish when done."
                    ),
                }
            )
        return messages, written, start_turn, True

    if existing:
        if confirm and not confirm(
            f"Clean room already has {len(existing)} files. Continue from them?"
        ):
            return None, "Implement cancelled.", 0, False

    user = (
        f"Implement this specification as original work.\n"
        f"Apply this license to the output: {license_name}\n"
        f"Workspace: {ws.label} (clean-room implementer). You cannot see the original source.\n\n"
        "Start by calling list_spec and read_spec. Write files with write_file. "
        "Call finish when LICENSE and ASSUMPTIONS.md exist and the spec's MUSTs are covered.\n"
        "Do not try to emit the whole project in one message."
    )
    if existing:
        user += (
            f"\n\nThe clean room already contains {len(existing)} files. "
            "Call list_clean and continue from what is there."
        )
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    return messages, list(existing), 0, False


def _assistant_message(result: ChatTurn) -> dict:
    message = {"role": "assistant", "content": result.content or None}
    if result.tool_calls:
        message["tool_calls"] = [
            {
                "id": call["id"],
                "type": "function",
                "function": {"name": call["name"], "arguments": call["arguments"]},
            }
            for call in result.tool_calls
        ]
        if not result.content:
            message["content"] = None
    else:
        message["content"] = result.content or ""
    return message


def _apply_tool_calls(tools: IsolatedTools, result: ChatTurn, messages: list, written: list, job):
    finished = False
    summary = ""
    for call in result.tool_calls:
        name = call["name"]
        path_hint = ""
        args = parse_tool_args(call.get("arguments"))
        if isinstance(args.get("path"), str):
            path_hint = args["path"]
        if job:
            job.event("tool", name=name, path=path_hint)
        payload, meta = tools.dispatch(name, args)
        if meta.get("written"):
            written.append(meta["written"])
        deleted = meta.get("deleted")
        if deleted:
            written[:] = [item for item in written if item != deleted]
        if meta.get("finished"):
            finished = True
            summary = meta.get("summary") or ""
        messages.append(
            {
                "role": "tool",
                "tool_call_id": call["id"],
                "name": name,
                "content": payload,
            }
        )
    return finished, summary


def _write_file_blocks(ws: Workspace, content: str, written: list) -> int:
    if not content:
        return 0
    count = 0
    for relative, body in parse_file_blocks(content):
        try:
            path = ws.write_text(Room.CLEAN, relative, body)
        except IsolationError:
            continue
        written.append(path.relative_to(ws.clean_dir).as_posix())
        count += 1
    return count


def _oneshot_fallback(ws: Workspace, ai, view, license_name: str, messages: list, written: list) -> str:
    spec = ws.read_text(Room.CLEAN, "specification.md")
    user = (
        f"Implement this specification as original work.\n"
        f"Apply this license to the output: {license_name}\n\n"
        f"## Specification\n{spec}"
    )
    sent = load_prompt("implementer.md") + user
    job = Job(
        view,
        title="implement · FILE-block fallback",
        detail=f"{ai.model} via {ai.provider_id} · ~{estimate_tokens(sent):,} tok est.",
    )
    try:
        raw = ai.chat(
            [
                {"role": "system", "content": load_prompt("implementer.md")},
                {"role": "user", "content": user},
            ],
            on_event=job.event,
        )
    except Exception:
        job.finish(ok=False)
        raise
    _write_file_blocks(ws, raw, written)
    files = _uniq(written)
    if not files:
        path = ws.write_text(Room.CLEAN, "IMPLEMENTATION.md", raw)
        ws.save_session(
            {
                "version": 1,
                "phase": PHASE,
                "status": "paused",
                "model": getattr(ai, "model", None),
                "turn": 1,
                "written": [],
                "messages": messages,
            }
        )
        ws.log(f"IMPLEMENT model={ai.model} files=0 fallback=IMPLEMENTATION.md")
        job.finish(ok=True, extra="no FILE blocks")
        return (
            f"{ct.YELLOW}Model did not emit FILE blocks. "
            f"Raw output saved to {path}.{ct.RESET}"
        )
    ws.save_session(
        {
            "version": 1,
            "phase": PHASE,
            "status": "done",
            "model": getattr(ai, "model", None),
            "turn": 1,
            "written": files,
            "messages": messages,
        }
    )
    ws.log(f"IMPLEMENT model={ai.model} files={len(files)} isolated=true fallback=blocks")
    job.finish(ok=True, extra=f"{len(files)} files")
    return _done_message(files, "")


def _done_message(files: list[str], summary: str) -> str:
    preview = ", ".join(files[:8])
    extra = f" (+{len(files) - 8} more)" if len(files) > 8 else ""
    note = f" {summary}" if summary else ""
    return f"Clean-room implementation wrote {len(files)} files: {preview}{extra}.{note}".strip()


def _uniq(items: list[str]) -> list[str]:
    seen = set()
    out = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out
