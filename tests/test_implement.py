import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from api.agent import ChatTurn, ToolsUnsupported
from api.implement import run_implementer
from api.tools import IsolatedTools
from utils.workspace import Room, Workspace


class _FakeView:
    def confirm(self, question):
        return True

    def display(self, *outputs):
        return None

    def job_start(self, snap):
        return None

    def job_update(self, snap):
        return None

    def job_finish(self, snap):
        return None


class ScriptedAI:
    def __init__(self, turns):
        self.turns = list(turns)
        self.model = "test-model"
        self.provider_id = "test"
        self.ready = True
        self.fallback = ""

    def chat_turn(self, messages, tools=None, on_event=None, temperature=0.2):
        if on_event:
            on_event("waiting")
        if not self.turns:
            return ChatTurn(content="")
        item = self.turns.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item

    def chat(self, messages, temperature=0.2, on_event=None):
        if on_event:
            on_event("delta", text=self.fallback, full=self.fallback)
        return self.fallback


def _call(name, ident, **args):
    return {"id": ident, "name": name, "arguments": json.dumps(args)}


class ImplementLoopTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = patch.dict("os.environ", {"ZHUQUE_WORKSPACE": self.tmp.name})
        self.env.start()
        self.ws = Workspace("acme", "cipher")
        self.ws.prepare()
        self.ws.write_text(Room.SPEC, "specification.md", "Encrypt A-Z with a repeating key.")
        (self.ws.dirty_dir / "secret.py").write_text("ORIGINAL = 1\n", encoding="utf-8")

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def test_tool_loop_writes_clean_files_and_finishes(self):
        ai = ScriptedAI(
            [
                ChatTurn(
                    tool_calls=[
                        _call("write_file", "1", path="LICENSE", content="MIT License"),
                        _call("write_file", "2", path="ASSUMPTIONS.md", content="- modulo 26"),
                        _call("write_file", "3", path="src/cipher.py", content="print('ok')\n"),
                        _call("finish", "4", summary="cipher from spec"),
                    ]
                )
            ]
        )
        output = run_implementer(
            ws=self.ws,
            ai=ai,
            view=_FakeView(),
            license_name="MIT",
            confirm=lambda q: True,
        )
        self.assertIn("3 files", output)
        self.assertIn("src/cipher.py", output)
        self.assertTrue(self.ws.exists(Room.CLEAN, "src/cipher.py"))
        self.assertIn("print('ok')", self.ws.read_text(Room.CLEAN, "src/cipher.py"))
        session = self.ws.load_session()
        self.assertEqual(session["status"], "done")
        self.assertEqual(self.ws.pipeline_stage(), "done")
        self.assertNotIn("ORIGINAL", self.ws.read_text(Room.CLEAN, "src/cipher.py"))

    def test_finish_rejected_without_license(self):
        tools = IsolatedTools(self.ws)
        payload, meta = tools.dispatch("finish", {"summary": "nope"})
        self.assertIn("LICENSE", payload)
        self.assertFalse(meta.get("finished"))

    def test_resume_picks_up_paused_session(self):
        self.ws.write_text(Room.CLEAN, "LICENSE", "MIT License")
        self.ws.write_text(Room.CLEAN, "ASSUMPTIONS.md", "- keep going")
        self.ws.save_session(
            {
                "version": 1,
                "phase": "implement",
                "status": "paused",
                "turn": 2,
                "written": ["LICENSE", "ASSUMPTIONS.md"],
                "messages": [
                    {"role": "system", "content": "old prompt"},
                    {"role": "user", "content": "Implement this specification."},
                ],
            }
        )
        ai = ScriptedAI(
            [
                ChatTurn(
                    tool_calls=[
                        _call("write_file", "9", path="src/more.py", content="x = 1\n"),
                        _call("finish", "10", summary="resumed"),
                    ]
                )
            ]
        )
        output = run_implementer(
            ws=self.ws,
            ai=ai,
            view=_FakeView(),
            license_name="MIT",
            confirm=lambda q: False,
        )
        self.assertIn("src/more.py", output)
        self.assertIn("resumed", output)
        self.assertTrue(self.ws.exists(Room.CLEAN, "LICENSE"))
        self.assertEqual(self.ws.load_session()["status"], "done")

    def test_interrupt_saves_paused_session(self):
        ai = ScriptedAI([KeyboardInterrupt()])
        output = run_implementer(
            ws=self.ws,
            ai=ai,
            view=_FakeView(),
            license_name="MIT",
            confirm=lambda q: True,
        )
        self.assertIn("paused", output.lower())
        session = self.ws.load_session()
        self.assertEqual(session["status"], "paused")
        self.assertEqual(self.ws.pipeline_stage(), "implement")

    def test_file_block_fallback_when_tools_unsupported(self):
        ai = ScriptedAI([ToolsUnsupported("no tools")])
        ai.fallback = """
### FILE: LICENSE
```
MIT License
```

### FILE: ASSUMPTIONS.md
```
- none
```

### FILE: app.py
```
print("ok")
```
"""
        output = run_implementer(
            ws=self.ws,
            ai=ai,
            view=_FakeView(),
            license_name="MIT",
            confirm=lambda q: True,
        )
        self.assertIn("3 files", output)
        self.assertTrue(self.ws.exists(Room.CLEAN, "app.py"))
        self.assertEqual(self.ws.load_session()["status"], "done")


if __name__ == "__main__":
    unittest.main()
