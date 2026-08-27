from dataclasses import dataclass, field

from constants.models import DEFAULT_MODEL, DEFAULT_MODEL_PROVIDER
from api.credentials import credential_for, split_model
from constants.providers import provider_meta
from utils.models import is_valid_model, meta_from_model
from utils.secrets import env_val


class ToolsUnsupported(RuntimeError):
    """The bound provider/model rejected function calling."""


@dataclass
class ChatTurn:
    content: str = ""
    tool_calls: list[dict] = field(default_factory=list)
    finish_reason: str | None = None


class UniversalClient:
    def __init__(self, model: str | None = None, token: str | None = None):
        requested = model or env_val("MODEL") or DEFAULT_MODEL
        self.model = requested if is_valid_model(requested) else None
        self._forced_token = token
        self._client = None
        self._bind()

    def _bind(self) -> None:
        self.provider_id, self.api_model = self._split()
        catalog = meta_from_model(self.api_model) if self.model else None
        if not self.provider_id and catalog:
            self.provider_id = catalog["provider"]
        if not self.provider_id:
            self.provider_id = DEFAULT_MODEL_PROVIDER
        self.meta = provider_meta(self.provider_id) or catalog or {}
        self.cred = credential_for(self.provider_id)
        if self._forced_token:
            self.cred.token = self._forced_token
        self.token = self.cred.token
        self.base_url = self.cred.base_url
        self.compat = self.cred.compat or self.meta.get("compat") or "openai"
        self.sdk_options = (catalog or {}).get("sdks") or ["OpenAI SDK"]
        self.sdk = self.sdk_options[0]
        self._client = None

    def _split(self) -> tuple[str | None, str]:
        if not self.model:
            return None, ""
        return split_model(self.model)

    @staticmethod
    def _validate_model(model: str) -> bool:
        return is_valid_model(model)

    def _openai(self):
        if self._client is None:
            try:
                from openai import OpenAI
            except ImportError as exc:
                raise RuntimeError("Install the openai package: pip install openai") from exc
            if not self.ready:
                raise RuntimeError(self.status_line())
            kwargs = {"api_key": self.token or "local", "base_url": self.base_url}
            self._client = OpenAI(**kwargs)
        return self._client

    @property
    def ready(self) -> bool:
        if not self.model or not self.base_url:
            return False
        if self.meta.get("optional_key"):
            return True
        return bool(self.token)

    def status_line(self) -> str:
        if not self.model:
            return "AI model is unset or invalid"
        via = self.provider_id or "?"
        how = self.cred.source if hasattr(self, "cred") else "missing"
        if how == "missing" or not self.token:
            env_name = self.meta.get("env") or "API key"
            return (
                f"AI model {self.model} ({via}) — not signed in. "
                f'Try "auth login {via}" or set {env_name}'
            )
        return f"AI model {self.model} via {via} [{how}] ({self.base_url})"

    def set_model(self, model: str) -> str | None:
        if not is_valid_model(model):
            return None
        self.__init__(model=model, token=self._forced_token)
        return self.model

    def reload(self) -> None:
        self._bind()

    def chat(self, messages: list[dict], temperature: float = 0.2, on_event=None) -> str:
        turn = self.chat_turn(messages, tools=None, temperature=temperature, on_event=on_event)
        return turn.content

    def chat_turn(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        temperature: float = 0.2,
        on_event=None,
    ) -> ChatTurn:
        if not self.ready:
            raise RuntimeError(self.status_line())
        if on_event:
            on_event("waiting")
        if not tools:
            if self.compat == "anthropic":
                text = self._chat_anthropic(messages, temperature, on_event=on_event)
            else:
                try:
                    text = self._chat_openai_stream(messages, temperature, on_event)
                except KeyboardInterrupt:
                    raise
                except Exception:
                    text = self._chat_openai_block(messages, temperature, on_event)
            return ChatTurn(content=text)
        if self.compat == "anthropic":
            return self._chat_anthropic_turn(messages, tools, temperature, on_event)
        try:
            return self._chat_openai_turn(messages, tools, temperature, on_event, stream=True)
        except KeyboardInterrupt:
            raise
        except ToolsUnsupported:
            raise
        except Exception:
            return self._chat_openai_turn(messages, tools, temperature, on_event, stream=False)

    def _emit_usage(self, on_event, usage) -> None:
        if not on_event or not usage:
            return
        on_event(
            "usage",
            prompt_tokens=getattr(usage, "prompt_tokens", None),
            completion_tokens=getattr(usage, "completion_tokens", None),
            total_tokens=getattr(usage, "total_tokens", None),
        )

    def _chat_openai_stream(self, messages, temperature, on_event) -> str:
        kwargs = {
            "model": self.api_model or self.model,
            "messages": messages,
            "stream": True,
        }
        if temperature is not None:
            kwargs["temperature"] = temperature
        try:
            stream = self._openai().chat.completions.create(
                **kwargs, stream_options={"include_usage": True}
            )
        except Exception:
            stream = self._openai().chat.completions.create(**kwargs)
        parts = []
        for chunk in stream:
            usage = getattr(chunk, "usage", None)
            if usage:
                self._emit_usage(on_event, usage)
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            text = getattr(delta, "content", None) or ""
            if not text:
                continue
            parts.append(text)
            if on_event:
                on_event("delta", text=text, full="".join(parts))
        return "".join(parts).strip()

    def _chat_openai_block(self, messages, temperature, on_event) -> str:
        kwargs = {
            "model": self.api_model or self.model,
            "messages": messages,
        }
        if temperature is not None:
            kwargs["temperature"] = temperature
        response = self._openai().chat.completions.create(**kwargs)
        self._emit_usage(on_event, getattr(response, "usage", None))
        text = (response.choices[0].message.content or "").strip()
        if on_event and text:
            on_event("delta", text=text, full=text)
        return text

    def _chat_openai_turn(self, messages, tools, temperature, on_event, stream: bool) -> ChatTurn:
        kwargs = {
            "model": self.api_model or self.model,
            "messages": messages,
            "tools": tools,
            "tool_choice": "auto",
            "stream": stream,
        }
        if temperature is not None:
            kwargs["temperature"] = temperature
        try:
            if stream:
                try:
                    stream_obj = self._openai().chat.completions.create(
                        **kwargs, stream_options={"include_usage": True}
                    )
                except Exception:
                    stream_obj = self._openai().chat.completions.create(**kwargs)
                return self._consume_openai_stream_turn(stream_obj, on_event)
            response = self._openai().chat.completions.create(**kwargs)
            return self._openai_block_turn(response, on_event)
        except KeyboardInterrupt:
            raise
        except ToolsUnsupported:
            raise
        except Exception as exc:
            if _looks_like_no_tools(exc):
                raise ToolsUnsupported(str(exc)) from exc
            raise

    def _consume_openai_stream_turn(self, stream, on_event) -> ChatTurn:
        parts = []
        acc: dict[int, dict] = {}
        finish_reason = None
        for chunk in stream:
            usage = getattr(chunk, "usage", None)
            if usage:
                self._emit_usage(on_event, usage)
            if not chunk.choices:
                continue
            choice = chunk.choices[0]
            finish_reason = _attr(choice, "finish_reason") or finish_reason
            delta = choice.delta
            text = _attr(delta, "content") or ""
            if text:
                parts.append(text)
                if on_event:
                    on_event("delta", text=text, full="".join(parts))
            for tc in _attr(delta, "tool_calls") or []:
                idx = _attr(tc, "index", 0) or 0
                slot = acc.setdefault(idx, {"id": "", "name": "", "arguments": ""})
                ident = _attr(tc, "id")
                if ident:
                    slot["id"] = ident
                fn = _attr(tc, "function")
                if fn is not None:
                    name = _attr(fn, "name") or ""
                    args = _attr(fn, "arguments") or ""
                    if name:
                        slot["name"] += name
                    if args:
                        slot["arguments"] += args
        calls = []
        for idx in sorted(acc):
            slot = acc[idx]
            if not slot["name"]:
                continue
            calls.append(
                {
                    "id": slot["id"] or f"call_{idx}",
                    "name": slot["name"],
                    "arguments": slot["arguments"] or "{}",
                }
            )
        return ChatTurn(
            content="".join(parts).strip(),
            tool_calls=calls,
            finish_reason=finish_reason,
        )

    def _openai_block_turn(self, response, on_event) -> ChatTurn:
        self._emit_usage(on_event, getattr(response, "usage", None))
        message = response.choices[0].message
        text = (_attr(message, "content") or "").strip()
        if on_event and text:
            on_event("delta", text=text, full=text)
        calls = []
        for tc in _attr(message, "tool_calls") or []:
            fn = _attr(tc, "function") or {}
            name = _attr(fn, "name") or ""
            if not name:
                continue
            calls.append(
                {
                    "id": _attr(tc, "id") or f"call_{len(calls)}",
                    "name": name,
                    "arguments": _attr(fn, "arguments") or "{}",
                }
            )
        return ChatTurn(
            content=text,
            tool_calls=calls,
            finish_reason=_attr(response.choices[0], "finish_reason"),
        )

    def _chat_anthropic(self, messages: list[dict], temperature: float, on_event=None) -> str:
        import json

        import requests

        system = "\n\n".join(
            m["content"] for m in messages if m.get("role") == "system" and m.get("content")
        )
        converted = [
            {"role": m["role"], "content": m["content"]}
            for m in messages
            if m.get("role") in {"user", "assistant"}
        ]
        response = requests.post(
            f"{self.base_url.rstrip('/')}/v1/messages",
            headers={
                "x-api-key": self.token,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": self.api_model or self.model,
                "max_tokens": 8192,
                "temperature": temperature,
                "system": system or None,
                "messages": converted,
                "stream": True,
            },
            timeout=300,
            stream=True,
        )
        if response.status_code >= 400:
            return self._chat_anthropic_block(messages, temperature, on_event)
        parts = []
        for raw in response.iter_lines(decode_unicode=True):
            if not raw or not raw.startswith("data:"):
                continue
            payload = raw[5:].strip()
            if payload == "[DONE]":
                break
            try:
                event = json.loads(payload)
            except json.JSONDecodeError:
                continue
            if event.get("type") == "content_block_delta":
                text = (event.get("delta") or {}).get("text") or ""
                if text:
                    parts.append(text)
                    if on_event:
                        on_event("delta", text=text, full="".join(parts))
            if event.get("type") == "message_delta":
                usage = (event.get("usage") or {})
                if on_event and usage:
                    on_event(
                        "usage",
                        prompt_tokens=usage.get("input_tokens"),
                        completion_tokens=usage.get("output_tokens"),
                    )
        return "".join(parts).strip()

    def _chat_anthropic_block(self, messages: list[dict], temperature: float, on_event=None) -> str:
        import requests

        system = "\n\n".join(
            m["content"] for m in messages if m.get("role") == "system" and m.get("content")
        )
        converted = [
            {"role": m["role"], "content": m["content"]}
            for m in messages
            if m.get("role") in {"user", "assistant"}
        ]
        response = requests.post(
            f"{self.base_url.rstrip('/')}/v1/messages",
            headers={
                "x-api-key": self.token,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": self.api_model or self.model,
                "max_tokens": 8192,
                "temperature": temperature,
                "system": system or None,
                "messages": converted,
            },
            timeout=300,
        )
        response.raise_for_status()
        blocks = response.json().get("content") or []
        text = "".join(block.get("text", "") for block in blocks if isinstance(block, dict)).strip()
        if on_event and text:
            on_event("delta", text=text, full=text)
        return text

    def _chat_anthropic_turn(self, messages, tools, temperature, on_event) -> ChatTurn:
        import json

        import requests

        system, converted = _openai_messages_to_anthropic(messages)
        response = requests.post(
            f"{self.base_url.rstrip('/')}/v1/messages",
            headers={
                "x-api-key": self.token,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": self.api_model or self.model,
                "max_tokens": 8192,
                "temperature": temperature,
                "system": system or None,
                "messages": converted,
                "tools": _openai_tools_to_anthropic(tools),
            },
            timeout=300,
        )
        if response.status_code >= 400:
            if _looks_like_no_tools(RuntimeError(response.text)):
                raise ToolsUnsupported(response.text)
            response.raise_for_status()
        payload = response.json()
        usage = payload.get("usage") or {}
        if on_event and usage:
            on_event(
                "usage",
                prompt_tokens=usage.get("input_tokens"),
                completion_tokens=usage.get("output_tokens"),
            )
        parts = []
        calls = []
        for block in payload.get("content") or []:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "text":
                text = block.get("text") or ""
                if text:
                    parts.append(text)
                    if on_event:
                        on_event("delta", text=text, full="".join(parts))
            elif block.get("type") == "tool_use":
                calls.append(
                    {
                        "id": block.get("id") or f"call_{len(calls)}",
                        "name": block.get("name") or "",
                        "arguments": json.dumps(block.get("input") or {}, ensure_ascii=False),
                    }
                )
        return ChatTurn(
            content="".join(parts).strip(),
            tool_calls=[c for c in calls if c["name"]],
            finish_reason=payload.get("stop_reason"),
        )


def _attr(obj, name, default=None):
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _looks_like_no_tools(exc) -> bool:
    text = str(exc).lower()
    needles = (
        "does not support tools",
        "tools are not supported",
        "unknown parameter: 'tools'",
        'unknown parameter: "tools"',
        "unrecognized key: tools",
        "unrecognized request argument: tools",
        "function calling is not enabled",
        "tool use is not supported",
        "tools parameter is not supported",
    )
    return any(needle in text for needle in needles)


def _openai_tools_to_anthropic(tools: list[dict]) -> list[dict]:
    converted = []
    for tool in tools:
        fn = tool.get("function") if isinstance(tool, dict) else None
        if not isinstance(fn, dict):
            continue
        converted.append(
            {
                "name": fn.get("name"),
                "description": fn.get("description") or "",
                "input_schema": fn.get("parameters") or {"type": "object", "properties": {}},
            }
        )
    return converted


def _openai_messages_to_anthropic(messages: list[dict]) -> tuple[str, list[dict]]:
    import json

    system_parts = []
    converted = []
    pending_tools = []

    def flush_tools():
        if pending_tools:
            converted.append({"role": "user", "content": pending_tools[:]})
            pending_tools.clear()

    for message in messages:
        role = message.get("role")
        if role == "system":
            if message.get("content"):
                system_parts.append(message["content"])
            continue
        if role == "tool":
            pending_tools.append(
                {
                    "type": "tool_result",
                    "tool_use_id": message.get("tool_call_id"),
                    "content": message.get("content") or "",
                }
            )
            continue
        flush_tools()
        if role == "assistant":
            blocks = []
            if message.get("content"):
                blocks.append({"type": "text", "text": message["content"]})
            for tc in message.get("tool_calls") or []:
                fn = tc.get("function") or {}
                raw = fn.get("arguments") or "{}"
                if isinstance(raw, dict):
                    args = raw
                else:
                    try:
                        args = json.loads(raw) if str(raw).strip() else {}
                    except json.JSONDecodeError:
                        args = {}
                    if not isinstance(args, dict):
                        args = {}
                blocks.append(
                    {
                        "type": "tool_use",
                        "id": tc.get("id"),
                        "name": fn.get("name"),
                        "input": args,
                    }
                )
            converted.append({"role": "assistant", "content": blocks or ""})
        elif role == "user":
            converted.append({"role": "user", "content": message.get("content") or ""})
    flush_tools()
    return "\n\n".join(system_parts), converted
