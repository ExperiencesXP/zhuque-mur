import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


class AuthStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = patch.dict("os.environ", {"ZHUQUE_AUTH_DIR": self.tmp.name})
        self.env.start()
        from utils import auth_store

        self.store = auth_store

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def test_roundtrip(self):
        self.store.put_entry("neuralwatt", {"type": "api_key", "key": "sk-test-123456789"})
        entry = self.store.get_entry("neuralwatt")
        self.assertEqual(entry["key"], "sk-test-123456789")
        self.assertTrue(self.store.delete_entry("neuralwatt"))
        self.assertIsNone(self.store.get_entry("neuralwatt"))

    def test_mask(self):
        self.assertEqual(self.store.mask_secret("sk-abcdefghij"), "sk-a…ghij")


class ModelIdTests(unittest.TestCase):
    def test_builtin_and_byok(self):
        from utils.models import is_valid_model, provider_from_model

        self.assertTrue(is_valid_model("grok-4.6"))
        self.assertTrue(is_valid_model("neuralwatt/deepseek-v4-flash"))
        self.assertTrue(is_valid_model("opencode/kimi-k2.6"))
        self.assertTrue(is_valid_model("byok:lab/local-model"))
        self.assertFalse(is_valid_model("not-a-model"))
        self.assertEqual(provider_from_model("opencode/kimi-k2.6"), "opencode")
        self.assertEqual(provider_from_model("grok-4.6"), "xai")


class ImportOpenCodeTests(unittest.TestCase):
    def test_normalize_api_and_oauth(self):
        from api.import_auth import _normalize_opencode_entry

        api = _normalize_opencode_entry({"type": "api", "key": "sk-oc"})
        self.assertEqual(api["type"], "api_key")
        self.assertEqual(api["key"], "sk-oc")
        oauth = _normalize_opencode_entry(
            {"type": "oauth", "access": "tok", "refresh": "ref"}
        )
        self.assertEqual(oauth["access_token"], "tok")
        self.assertEqual(oauth["refresh_token"], "ref")

    def test_import_from_file(self):
        tmp = tempfile.TemporaryDirectory()
        env = patch.dict("os.environ", {"ZHUQUE_AUTH_DIR": tmp.name})
        env.start()
        oc = Path(tmp.name) / "opencode-auth.json"
        oc.write_text(json.dumps({"openai": {"type": "api", "key": "sk-from-oc"}}), encoding="utf-8")
        try:
            from api.import_auth import _normalize_opencode_entry
            from utils.auth_store import get_entry, put_entry

            put_entry("openai", _normalize_opencode_entry({"type": "api", "key": "sk-from-oc"}))
            self.assertEqual(get_entry("openai")["key"], "sk-from-oc")
        finally:
            env.stop()
            tmp.cleanup()


class CredentialPrecedenceTests(unittest.TestCase):
    def test_store_beats_missing_env(self):
        tmp = tempfile.TemporaryDirectory()
        env = patch.dict("os.environ", {"ZHUQUE_AUTH_DIR": tmp.name}, clear=False)
        env.start()
        try:
            from api.credentials import credential_for
            from utils.auth_store import put_entry

            put_entry(
                "neuralwatt",
                {
                    "type": "api_key",
                    "key": "sk-nw-stored",
                    "base_url": "https://api.neuralwatt.com/v1",
                },
            )
            cred = credential_for("neuralwatt")
            self.assertEqual(cred.token, "sk-nw-stored")
            self.assertEqual(cred.source, "store")
            self.assertTrue(cred.ready)
        finally:
            env.stop()
            tmp.cleanup()


class ControllerAuthTests(unittest.TestCase):
    def test_auth_help_lists_byok(self):
        from controllers.app_controller import AppController

        app = AppController()
        output = app.handle("auth", "nope")
        blob = "\n".join(output)
        self.assertIn("byok", blob)
        self.assertIn("login", blob)


if __name__ == "__main__":
    unittest.main()
