import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from utils.progress import Job, estimate_tokens, format_seconds, preview_text


class FormatTests(unittest.TestCase):
    def test_preview_collapses_and_tails(self):
        self.assertEqual(preview_text("alpha   beta"), "alpha beta")
        long = "word " * 40
        shown = preview_text(long, limit=20)
        self.assertLessEqual(len(shown), 20)

    def test_estimate_and_clock(self):
        self.assertEqual(estimate_tokens("abcd" * 10), 10)
        self.assertEqual(format_seconds(12.34), "12.3s")
        self.assertEqual(format_seconds(75), "1m15s")


class JobTests(unittest.TestCase):
    def test_waiting_then_streaming(self):
        view = MagicMock()
        job = Job(view, title="analyze · reverse_engineer.md", detail="grok-4.6")
        job.event("waiting")
        snap = job.snapshot()
        self.assertEqual(snap["phase"], "waiting")
        self.assertIsNotNone(snap["wait"])
        job.event("delta", text="Hello", full="Hello")
        job.event("delta", text=" world", full="Hello world")
        snap = job.snapshot()
        self.assertEqual(snap["phase"], "streaming")
        self.assertEqual(snap["chars"], 11)
        self.assertIn("Hello world", snap["preview"])
        done = job.finish(ok=True)
        self.assertEqual(done["phase"], "done")
        view.job_start.assert_called()
        view.job_finish.assert_called()


class StreamAssembleTests(unittest.TestCase):
    def test_openai_stream_concatenates(self):
        from api.agent import UniversalClient

        client = UniversalClient.__new__(UniversalClient)
        client.compat = "openai"
        client.api_model = "grok-4.6"
        client.model = "grok-4.6"
        chunks = [
            SimpleNamespace(
                usage=None,
                choices=[SimpleNamespace(delta=SimpleNamespace(content="A-Z "))],
            ),
            SimpleNamespace(
                usage=None,
                choices=[SimpleNamespace(delta=SimpleNamespace(content="modulo 26"))],
            ),
            SimpleNamespace(
                usage=SimpleNamespace(prompt_tokens=10, completion_tokens=4, total_tokens=14),
                choices=[],
            ),
        ]
        client._openai = lambda: SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(create=lambda **kwargs: iter(chunks))
            )
        )
        seen = []
        text = client._chat_openai_stream([], 0.2, lambda kind, **p: seen.append((kind, p)))
        self.assertEqual(text, "A-Z modulo 26")
        self.assertTrue(any(kind == "delta" for kind, _ in seen))
        self.assertTrue(any(kind == "usage" for kind, _ in seen))

    def test_openai_stream_assembles_tool_calls(self):
        from api.agent import UniversalClient

        client = UniversalClient.__new__(UniversalClient)
        chunks = [
            SimpleNamespace(
                usage=None,
                choices=[
                    SimpleNamespace(
                        finish_reason=None,
                        delta=SimpleNamespace(
                            content=None,
                            tool_calls=[
                                SimpleNamespace(
                                    index=0,
                                    id="call_1",
                                    function=SimpleNamespace(
                                        name="write_file", arguments='{"path":'
                                    ),
                                )
                            ],
                        ),
                    )
                ],
            ),
            SimpleNamespace(
                usage=None,
                choices=[
                    SimpleNamespace(
                        finish_reason="tool_calls",
                        delta=SimpleNamespace(
                            content=None,
                            tool_calls=[
                                SimpleNamespace(
                                    index=0,
                                    id=None,
                                    function=SimpleNamespace(
                                        name=None, arguments='"app.py","content":"x"}'
                                    ),
                                )
                            ],
                        ),
                    )
                ],
            ),
        ]
        turn = client._consume_openai_stream_turn(iter(chunks), None)
        self.assertEqual(len(turn.tool_calls), 1)
        self.assertEqual(turn.tool_calls[0]["name"], "write_file")
        self.assertIn("app.py", turn.tool_calls[0]["arguments"])

    def test_job_tool_phase(self):
        view = MagicMock()
        job = Job(view, title="implement · clean room")
        job.event("tool", name="write_file", path="src/app.py")
        snap = job.snapshot()
        self.assertEqual(snap["phase"], "tool")
        self.assertIn("write_file", snap["preview"])
        job.finish(ok=True)


if __name__ == "__main__":
    unittest.main()
