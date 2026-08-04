from __future__ import annotations

from pathlib import Path
import shutil
import sys
import tempfile
import unittest


ROOT = Path(__file__).parents[1]
TOOLS = ROOT / "tools"
sys.path.insert(0, str(TOOLS))

import public_check as pc  # noqa: E402


class PublicCheckTests(unittest.TestCase):
    def test_current_repository_passes(self) -> None:
        self.assertEqual(pc.check_repository(ROOT), [])

    def test_personal_path_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "README.md").write_text(
                "https://user.tikhub.io/register?ref=Gqosvz0l\n"
                "https://user.tikhub.io/register\n少量佣金\n不使用邀请码\n",
                encoding="utf-8",
            )
            (root / "bad.md").write_text(
                "/" + "Users" + "/private/report.json",
                encoding="utf-8",
            )
            errors = pc.check_repository(root)
        self.assertTrue(any("个人绝对路径" in error for error in errors))

    def test_secret_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "README.md").write_text(
                "https://user.tikhub.io/register?ref=Gqosvz0l\n"
                "https://user.tikhub.io/register\n少量佣金\n不使用邀请码\n",
                encoding="utf-8",
            )
            (root / "bad.txt").write_text(
                "gho_" + "A" * 30,
                encoding="utf-8",
            )
            errors = pc.check_repository(root)
        self.assertTrue(any("疑似密钥" in error for error in errors))

    def test_compiled_artifact_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "README.md").write_text(
                "https://user.tikhub.io/register?ref=Gqosvz0l\n"
                "https://user.tikhub.io/register\n少量佣金\n不使用邀请码\n",
                encoding="utf-8",
            )
            (root / "bad.pyc").write_bytes(b"compiled")
            errors = pc.check_repository(root)
        self.assertTrue(any("编译产物" in error for error in errors))

    def test_real_creator_identity_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "README.md").write_text(
                "https://user.tikhub.io/register?ref=Gqosvz0l\n"
                "https://user.tikhub.io/register\n少量佣金\n不使用邀请码\n",
                encoding="utf-8",
            )
            (root / "example.md").write_text(
                "xiao" + "gaifun",
                encoding="utf-8",
            )
            errors = pc.check_repository(root)
        self.assertTrue(any("真实博主标识" in error for error in errors))

    def test_hard_tikhub_call_cap_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "README.md").write_text(
                "https://user.tikhub.io/register?ref=Gqosvz0l\n"
                "https://user.tikhub.io/register\n少量佣金\n不使用邀请码\n"
                + "一次完整研"
                + "究默认最"
                + "多使用 "
                + str(6)
                + " 次 TikHub API 调用。\n",
                encoding="utf-8",
            )
            errors = pc.check_repository(root)
        self.assertTrue(any("调用次数硬上限" in error for error in errors))

    def test_skill_supports_configurable_report_root(self) -> None:
        skill_text = (
            ROOT / "xiaohongshu-creator-benchmark" / "SKILL.md"
        ).read_text(encoding="utf-8")
        self.assertIn(
            "~/.config/xiaohongshu-creator-benchmark/report-root",
            skill_text,
        )
        self.assertIn("没有合适目录时", skill_text)
        self.assertIn("只把最终 Markdown 报告写入知识库", skill_text)


if __name__ == "__main__":
    unittest.main()
