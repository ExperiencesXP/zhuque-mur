import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from api.github import GithubClient, parse_repo_ref


class ParseRepoRefTests(unittest.TestCase):
    def test_owner_repo(self):
        self.assertEqual(parse_repo_ref("yt-dlp/yt-dlp"), ("yt-dlp", "yt-dlp"))

    def test_https_url(self):
        self.assertEqual(
            parse_repo_ref("https://github.com/yt-dlp/yt-dlp"),
            ("yt-dlp", "yt-dlp"),
        )

    def test_url_with_git_suffix_and_slash(self):
        self.assertEqual(
            parse_repo_ref("https://github.com/yt-dlp/yt-dlp.git/"),
            ("yt-dlp", "yt-dlp"),
        )

    def test_ssh(self):
        self.assertEqual(
            parse_repo_ref("git@github.com:yt-dlp/yt-dlp.git"),
            ("yt-dlp", "yt-dlp"),
        )

    def test_bare_host(self):
        self.assertEqual(
            parse_repo_ref("github.com/yt-dlp/yt-dlp"),
            ("yt-dlp", "yt-dlp"),
        )

    def test_rejects_garbage(self):
        self.assertIsNone(parse_repo_ref("https://gitlab.com/foo/bar"))
        self.assertIsNone(parse_repo_ref("just-a-name"))


class GithubClientAuthTests(unittest.TestCase):
    def test_invalid_token_is_dropped(self):
        with patch("api.github.requests.Session") as session_cls:
            session = session_cls.return_value
            session.headers = {}
            response = MagicMock()
            response.status_code = 401
            session.get.return_value = response
            client = GithubClient("ghp_not-a-real-token")
            self.assertFalse(client.valid_token)
            self.assertIsNone(client.token)
            self.assertNotIn("Authorization", session.headers)

    def test_lookup_retries_without_bad_token(self):
        client = GithubClient.__new__(GithubClient)
        client.base_url = "https://api.github.com"
        client.session = MagicMock()
        client.session.headers = {"Authorization": "Bearer bad"}
        client.valid_token = True
        client.token = "bad"
        denied = MagicMock(status_code=401)
        ok = MagicMock(status_code=200)
        ok.json.return_value = {"full_name": "yt-dlp/yt-dlp"}
        client.session.get.side_effect = [denied, ok]
        meta, error = client.lookup_repo("yt-dlp", "yt-dlp")
        self.assertIsNone(error)
        self.assertEqual(meta["full_name"], "yt-dlp/yt-dlp")
        self.assertFalse(client.valid_token)
        self.assertEqual(client.session.get.call_count, 2)


if __name__ == "__main__":
    unittest.main()
