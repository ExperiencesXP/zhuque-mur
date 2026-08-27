import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from utils.source import parse_file_blocks
from utils.workspace import IsolationError, Room, Workspace


class IsolationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ws = Workspace("acme", "cipher", root=Path(self.tmp.name) / "acme__cipher")
        self.ws.prepare()
        (self.ws.dirty_dir / "vigenere.py").write_text("SECRET_ORIGINAL = 1\n", encoding="utf-8")
        self.ws.write_text(Room.ANALYSIS, "analysis.md", "alphabet A-Z, modulo 26")
        self.ws.write_text(Room.SPEC, "specification.md", "Encrypt A-Z with repeating key.")

    def tearDown(self):
        self.tmp.cleanup()

    def test_clean_room_cannot_read_dirty(self):
        with self.assertRaises(IsolationError):
            self.ws.read_text(Room.CLEAN, Path("..") / "dirty" / "vigenere.py")

    def test_clean_room_cannot_read_analysis(self):
        with self.assertRaises((IsolationError, FileNotFoundError)):
            text = self.ws.read_text(Room.CLEAN, "analysis.md")
            self.assertNotIn("modulo 26", text)

    def test_specifier_cannot_read_dirty(self):
        with self.assertRaises(IsolationError):
            self.ws.read_text(Room.SPEC, Path("..") / "dirty" / "vigenere.py")

    def test_specifier_can_read_analysis(self):
        text = self.ws.read_text(Room.SPEC, "analysis.md")
        self.assertIn("modulo 26", text)

    def test_implementer_can_read_spec(self):
        text = self.ws.read_text(Room.CLEAN, "specification.md")
        self.assertIn("Encrypt A-Z", text)

    def test_implementer_cannot_write_dirty(self):
        with self.assertRaises(IsolationError):
            self.ws.write_text(Room.CLEAN, Path("..") / "dirty" / "leak.py", "nope")

    def test_implementer_cannot_delete_dirty(self):
        with self.assertRaises(IsolationError):
            self.ws.delete_text(Room.CLEAN, Path("..") / "dirty" / "vigenere.py")

    def test_clean_room_tools_cannot_read_dirty(self):
        from api.tools import IsolatedTools, parse_tool_args

        tools = IsolatedTools(self.ws)
        payload, meta = tools.dispatch(
            "read_file", parse_tool_args('{"path": "../dirty/vigenere.py"}')
        )
        self.assertIn("invalid path", payload)
        self.assertEqual(meta, {})
        payload, _ = tools.dispatch("write_file", {"path": "../dirty/leak.py", "content": "nope"})
        self.assertIn("invalid path", payload)
        self.assertFalse((self.ws.dirty_dir / "leak.py").exists())

    def test_analyst_can_read_dirty(self):
        text = self.ws.read_text(Room.ANALYSIS, Path("..") / "dirty" / "vigenere.py")
        self.assertIn("SECRET_ORIGINAL", text)


class FileBlockTests(unittest.TestCase):
    def test_parse_and_reject_escape(self):
        raw = """
### FILE: src/cipher.py
```
print("ok")
```

### FILE: ../dirty/stolen.py
```
stolen
```
"""
        files = parse_file_blocks(raw)
        paths = [path for path, _ in files]
        self.assertIn("src/cipher.py", paths)
        self.assertNotIn("../dirty/stolen.py", paths)
        self.assertNotIn("dirty/stolen.py", paths)

    def test_nested_parent_escape_rejected(self):
        raw = """
### FILE: src/../../dirty/stolen.py
```
stolen
```
"""
        files = parse_file_blocks(raw)
        self.assertEqual(files, [])


if __name__ == "__main__":
    unittest.main()
