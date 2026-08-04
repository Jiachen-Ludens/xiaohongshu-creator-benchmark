from __future__ import annotations

import json
import os
from pathlib import Path
import ssl
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).parents[1]
SCRIPTS = ROOT / "xiaohongshu-creator-benchmark" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import tikhub_xhs as tx  # noqa: E402


class TikHubXhsTests(unittest.TestCase):
    def test_catalog_contains_only_six_xhs_actions(self) -> None:
        self.assertEqual(len(tx.TOOLS), 6)
        self.assertEqual(
            set(tx.TOOLS),
            {
                "xhs_search_users",
                "xhs_get_user_info",
                "xhs_get_user_posted_notes",
                "xhs_get_image_note_detail",
                "xhs_get_video_note_detail",
                "xhs_get_note_comments",
            },
        )
        self.assertTrue(
            all("/xiaohongshu/" in spec["path"] for spec in tx.TOOLS.values())
        )

    def test_collect_args_accepts_json_and_pairs(self) -> None:
        values = tx.collect_args('{"page": 2}', ["keyword=某AI博主"])
        self.assertEqual(values, {"page": 2, "keyword": "某AI博主"})

    def test_collect_args_rejects_invalid_pair(self) -> None:
        with self.assertRaises(tx.CliError):
            tx.collect_args(None, ["keyword"])

    def test_validation_rejects_unknown_argument(self) -> None:
        with self.assertRaises(tx.CliError):
            tx.validate("xhs_search_users", {"keyword": "x", "cookie": "no"})

    def test_validation_requires_keyword(self) -> None:
        with self.assertRaises(tx.CliError):
            tx.validate("xhs_search_users", {})

    def test_validation_accepts_one_of_user_id_or_share(self) -> None:
        self.assertEqual(
            tx.validate("xhs_get_user_info", {"user_id": "123"})["user_id"],
            "123",
        )
        with self.assertRaises(tx.CliError):
            tx.validate("xhs_get_user_info", {})

    def test_dry_run_does_not_require_token(self) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                str(SCRIPTS / "tikhub_xhs.py"),
                "call",
                "xhs_search_users",
                "--arg",
                "keyword=creator_keyword",
            ],
            capture_output=True,
            text=True,
            check=False,
            env={key: value for key, value in os.environ.items() if key != "TIKHUB_API_KEY"},
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertTrue(payload["dry_run"])
        self.assertEqual(payload["would_issue_tikhub_api_calls"], 1)

    def test_missing_token_discloses_affiliate_and_plain_links(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "missing-token"
            with mock.patch.object(tx, "TOKEN_FILE", missing), mock.patch.dict(
                os.environ, {}, clear=True
            ):
                with self.assertRaises(tx.CliError) as raised:
                    tx.require_token()
        message = str(raised.exception)
        self.assertIn(tx.AFFILIATE_REGISTER_URL, message)
        self.assertIn(tx.PLAIN_REGISTER_URL, message)
        self.assertIn("这是作者的邀请码", message)
        self.assertIn("少量佣金", message)
        self.assertIn("不想使用邀请码", message)

    def test_token_file_requires_0600(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            token_file = Path(tmp) / "token"
            token_file.write_text("a" * 30, encoding="utf-8")
            token_file.chmod(0o644)
            with mock.patch.object(tx, "TOKEN_FILE", token_file), mock.patch.dict(
                os.environ, {}, clear=True
            ):
                with self.assertRaises(tx.CliError):
                    tx.token_source()

    def test_token_status_never_prints_token(self) -> None:
        completed = subprocess.run(
            [sys.executable, str(SCRIPTS / "tikhub_xhs.py"), "token-status"],
            capture_output=True,
            text=True,
            check=False,
            env={**os.environ, "TIKHUB_API_KEY": "z" * 30},
        )
        self.assertEqual(completed.returncode, 0)
        self.assertNotIn("z" * 30, completed.stdout)
        self.assertEqual(json.loads(completed.stdout)["source"], "environment")

    def test_cache_reader_rejects_other_hosts_before_network(self) -> None:
        with self.assertRaises(tx.CliError):
            tx.fetch_cache(
                "https://example.invalid/cache",
                out_path=None,
                timeout=1,
            )

    def test_find_cache_url_handles_nested_payload(self) -> None:
        self.assertEqual(
            tx.find_cache_url({"data": [{"cache_url": "https://cache.invalid"}]}),
            "https://cache.invalid",
        )

    def test_tls_context_keeps_verification_enabled(self) -> None:
        context = tx.tls_context()
        self.assertTrue(context.check_hostname)
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)


if __name__ == "__main__":
    unittest.main()
