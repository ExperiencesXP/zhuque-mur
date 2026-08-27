import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from controllers.app_controller import AppController


class FakeView:
    def __init__(self):
        self.shown = []

    def welcome(self):
        return None

    def warning(self):
        return None

    def get_input(self, lowercase=False):
        return ""

    def confirm(self, question):
        return False

    def display(self, *outputs):
        self.shown.extend(outputs)

    def get_secret(self, prompt=""):
        return ""

    def job_start(self, snap):
        return None

    def job_update(self, snap):
        return None

    def job_finish(self, snap):
        return None


class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = patch.dict("os.environ", {"ZHUQUE_WORKSPACE": self.tmp.name})
        self.env.start()
        self.app = AppController()
        self.app.view = FakeView()
        self.app.commands.app = self.app

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def test_help_lists_pipeline(self):
        lines = self.app.handle("help")
        blob = "\n".join(lines)
        self.assertIn("analyze", blob)
        self.assertIn("specify", blob)
        self.assertIn("implement", blob)
        self.assertIn("continue", blob)
        self.assertIn("auth", blob)

    def test_unknown(self):
        output = self.app.handle("explode")
        self.assertIn("Unknown command", output)

    def test_pipeline_requires_target(self):
        output = self.app.handle("analyze")
        self.assertTrue(
            "No target" in output or "No live target" in output or "No workspace" in output,
            output,
        )

    def test_continue_routes(self):
        output = self.app.handle("continue")
        self.assertTrue(
            "No workspace" in output or "No target" in output,
            output,
        )

    def test_exit_stops_loop(self):
        output = self.app.handle("exit")
        self.assertFalse(self.app.running)
        self.assertIn("Goodbye", output)


if __name__ == "__main__":
    unittest.main()
