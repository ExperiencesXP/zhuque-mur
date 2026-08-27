import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from utils.workspace import Room, Workspace


class _FakeReadyAI:
    ready = True
    model = "test-model"
    provider_id = "test"

    def __init__(self, text="ok"):
        self.text = text

    def status_line(self):
        return "AI model test-model via test [test]"

    def chat(self, messages, temperature=0.2, on_event=None):
        if on_event:
            on_event("delta", text=self.text, full=self.text)
        return self.text


class _FakeView:
    def welcome(self):
        return None

    def warning(self):
        return None

    def get_input(self, lowercase=False):
        return ""

    def confirm(self, question):
        return True

    def display(self, *outputs):
        return None

    def get_secret(self, prompt=""):
        return ""

    def job_start(self, snap):
        return None

    def job_update(self, snap):
        return None

    def job_finish(self, snap):
        return None


class WorkspaceSessionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = patch.dict("os.environ", {"ZHUQUE_WORKSPACE": self.tmp.name})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def _make(self, owner: str, repo: str, files: dict[str, str] | None = None) -> Workspace:
        ws = Workspace(owner, repo)
        ws.prepare()
        if files:
            for name, body in files.items():
                (ws.dirty_dir / name).write_text(body, encoding="utf-8")
        return ws

    def test_discover_and_remember(self):
        first = self._make("yt-dlp", "yt-dlp", {"a.py": "print(1)\n"})
        self._make("acme", "cipher")
        found = {ws.label: ws for ws in Workspace.discover()}
        self.assertIn("yt-dlp/yt-dlp", found)
        self.assertIn("acme/cipher", found)
        first.remember()
        current = Workspace.load_current()
        self.assertIsNotNone(current)
        self.assertEqual(current.label, "yt-dlp/yt-dlp")
        Workspace.forget_current()
        self.assertIsNone(Workspace.load_current())

    def test_from_folder_ignores_noise(self):
        noise = Path(self.tmp.name) / "notes.txt"
        noise.write_text("x", encoding="utf-8")
        self.assertIsNone(Workspace.from_folder(noise))
        self.assertEqual(Workspace.discover(), [])

    def test_pipeline_stage_and_session(self):
        ws = self._make("acme", "cipher", {"a.py": "print(1)\n"})
        self.assertEqual(ws.pipeline_stage(), "analyze")
        ws.write_text(Room.ANALYSIS, "analysis.md", "notes")
        self.assertEqual(ws.pipeline_stage(), "specify")
        ws.write_text(Room.SPEC, "specification.md", "MUST encrypt")
        self.assertEqual(ws.pipeline_stage(), "implement")
        ws.save_session({"phase": "implement", "status": "paused", "turn": 3, "messages": []})
        self.assertEqual(ws.pipeline_stage(), "implement")
        ws.save_session({"phase": "implement", "status": "done", "turn": 4, "messages": []})
        ws.write_text(Room.CLEAN, "app.py", "print(1)\n")
        self.assertEqual(ws.pipeline_stage(), "done")


class RoomsWithoutTargetTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = patch.dict("os.environ", {"ZHUQUE_WORKSPACE": self.tmp.name})
        self.env.start()
        from controllers.app_controller import AppController

        ws = Workspace("yt-dlp", "yt-dlp")
        ws.prepare()
        (ws.dirty_dir / "main.py").write_text("print(1)\n", encoding="utf-8")
        ws.remember()
        self.app = AppController()
        self.app.view = _FakeView()
        self.app.commands.app = self.app

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def test_rooms_uses_disk_without_live_repo(self):
        self.assertIsNone(self.app.commands.repo)
        lines = self.app.handle("rooms")
        blob = "\n".join(lines)
        self.assertIn("yt-dlp/yt-dlp", blob)
        self.assertIn("dirty: 1 files", blob)
        self.assertIn("on disk", blob)

    def test_rooms_list(self):
        Workspace("acme", "cipher").prepare()
        lines = self.app.handle("rooms", "list")
        blob = "\n".join(lines)
        self.assertIn("yt-dlp/yt-dlp", blob)
        self.assertIn("acme/cipher", blob)

    def test_clear_clean_without_target(self):
        self.app.commands.ws.clean_dir.mkdir(parents=True, exist_ok=True)
        (self.app.commands.ws.clean_dir / "out.py").write_text("x", encoding="utf-8")
        output = self.app.handle("clear", "clean")
        self.assertIn("Clean room cleared", output)
        self.assertEqual(list(self.app.commands.ws.clean_dir.iterdir()), [])

    def test_clear_all_without_target_removes_workspace_folder(self):
        root = self.app.commands.ws.root
        output = self.app.handle("clear", "all")
        self.assertIn("All rooms cleared", output)
        self.assertIn("Workspace folder deleted", output)
        self.assertFalse(root.exists())
        self.assertIsNone(self.app.commands.ws)
        self.assertIsNone(Workspace.load_current())

    def test_status_mentions_on_disk(self):
        output = self.app.handle("status")
        self.assertIn("yt-dlp/yt-dlp", output)
        self.assertIn("on disk", output)
        self.assertIn("stage analyze", output)

    def test_continue_fetch_needs_live_target(self):
        empty = Workspace("acme", "blank")
        empty.prepare()
        empty.remember()
        self.app.commands.ws = empty
        self.app.commands.repo = None
        output = self.app.handle("continue")
        self.assertIn("Fetch needs a live GitHub target", output)

    def test_continue_specify_without_live_repo(self):
        self.app.commands.ws.write_text(Room.ANALYSIS, "analysis.md", "alphabet A-Z, modulo 26")
        self.app.commands.ai = _FakeReadyAI("# Spec\nMUST wrap A-Z modulo 26.")
        self.app.commands.repo = None
        output = self.app.handle("continue")
        self.assertIn("Airlock specification written", output)
        self.assertTrue(self.app.commands.ws.exists(Room.SPEC, "specification.md"))
        self.assertIsNone(self.app.commands.repo)
        self.assertEqual(self.app.commands.ws.pipeline_stage(), "implement")


if __name__ == "__main__":
    unittest.main()
