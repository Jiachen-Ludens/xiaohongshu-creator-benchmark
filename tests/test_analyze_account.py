from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).parents[1]
SCRIPTS = ROOT / "xiaohongshu-creator-benchmark" / "scripts"
FIXTURES = Path(__file__).parent / "fixtures"
sys.path.insert(0, str(SCRIPTS))

import analyze_account as aa  # noqa: E402


AS_OF = dt.datetime(2026, 8, 4, 12, 0, tzinfo=dt.timezone.utc)


class AnalyzeAccountTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.data = aa.build_output(
            FIXTURES / "profile.json",
            FIXTURES / "posts.json",
            [FIXTURES / "detail-high.json", FIXTURES / "detail-low.json"],
            [FIXTURES / "comments.json"],
            as_of=AS_OF,
            immature_hours=24,
        )

    def test_parse_count_supports_common_units(self) -> None:
        self.assertEqual(aa.parse_count("3.2万"), 32000)
        self.assertEqual(aa.parse_count("1.5k+"), 1500)
        self.assertIsNone(aa.parse_count("unknown"))

    def test_even_median_is_true_statistical_median(self) -> None:
        self.assertEqual(aa.median([1, 2, 3, 4]), 2.5)

    def test_percentile_uses_linear_interpolation(self) -> None:
        self.assertEqual(aa.percentile([0, 10], 0.9), 9)

    def test_profile_fields_are_normalized(self) -> None:
        self.assertEqual(self.data["profile"]["fans"], 50000)
        self.assertEqual(self.data["profile"]["posted"], 100)
        self.assertEqual(self.data["profile"]["red_id"], "synthetic_creator")

    def test_twenty_posts_are_loaded(self) -> None:
        self.assertEqual(self.data["metrics"]["sample_count"], 20)

    def test_recent_post_is_marked_immature(self) -> None:
        self.assertEqual(self.data["metrics"]["mature_count"], 19)
        self.assertEqual(self.data["metrics"]["immature_count"], 1)
        newest = next(
            row for row in self.data["posts"] if row["note_id"] == "note-20"
        )
        self.assertFalse(newest["mature"])
        self.assertEqual(newest["age_hours"], 6)

    def test_immature_viral_post_is_not_selected_high(self) -> None:
        selected = {
            row["note_id"] for row in self.data["selected_samples"]["high"]
        }
        self.assertNotIn("note-20", selected)
        self.assertEqual(selected, {"note-17", "note-18", "note-19"})

    def test_low_samples_are_account_internal_counterexamples(self) -> None:
        selected = [
            row["note_id"] for row in self.data["selected_samples"]["low"]
        ]
        self.assertEqual(selected, ["note-01", "note-02"])

    def test_median_and_p90_are_computed_from_mature_posts(self) -> None:
        self.assertEqual(self.data["metrics"]["engagement_median"], 1650)
        self.assertEqual(self.data["metrics"]["engagement_p90"], 2838)

    def test_top3_concentration_and_collect_ratio(self) -> None:
        self.assertEqual(self.data["metrics"]["top3_concentration"], 0.2842)
        self.assertEqual(self.data["metrics"]["collect_like_ratio"], 0.5)

    def test_frequency_uses_visible_date_span(self) -> None:
        self.assertEqual(self.data["metrics"]["active_days"], 20)
        self.assertEqual(self.data["metrics"]["span_days"], 20)
        self.assertEqual(self.data["metrics"]["posts_per_week"], 7)

    def test_media_types_are_preserved(self) -> None:
        self.assertEqual(self.data["metrics"]["video_posts"], 1)
        self.assertEqual(self.data["metrics"]["image_posts"], 19)

    def test_details_preserve_full_body_and_metrics(self) -> None:
        self.assertEqual(len(self.data["details"]), 2)
        high = next(
            row for row in self.data["details"] if row["note_id"] == "note-19"
        )
        self.assertIn("具体工作流", high["body"])
        self.assertEqual(high["collects"], 950)

    def test_comments_are_normalized_without_claiming_demand(self) -> None:
        self.assertEqual(len(self.data["comments"]), 4)
        self.assertEqual(
            self.data["comments"][0]["evidence_layer"], "public_comment"
        )
        self.assertTrue(self.data["comment_pages"][0]["has_more"])

    def test_bio_is_explicitly_creator_self_report(self) -> None:
        evidence = next(
            row
            for row in self.data["evidence"]
            if row["evidence_id"] == "profile-bio-self-report"
        )
        self.assertEqual(evidence["layer"], "creator_self_report")
        self.assertIn("未独立核验", evidence["warning"])

    def test_report_contains_placeholders_not_invented_causes(self) -> None:
        report = aa.render_report(self.data)
        self.assertIn("成功原因、内容机制和策略建议必须由 Agent", report)
        self.assertIn("注意力获取：待分析", report)
        self.assertIn("Top 3 互动占比 | 28.4%", report)
        self.assertNotIn("该账号成功是因为", report)

    def test_missing_details_and_comments_degrade_explicitly(self) -> None:
        data = aa.build_output(
            FIXTURES / "profile.json",
            FIXTURES / "posts.json",
            [],
            [],
            as_of=AS_OF,
            immature_hours=24,
        )
        report = aa.render_report(data)
        self.assertIn("未提供详情", report)
        self.assertIn("未提供评论", report)

    def test_metadata_call_count_is_summed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            profile = tmp_path / "profile.json"
            posts = tmp_path / "posts.json"
            users = tmp_path / "users.json"
            profile.write_text(
                (FIXTURES / "profile.json").read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            posts.write_text(
                (FIXTURES / "posts.json").read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            users.write_text('{"data": {"users": []}}', encoding="utf-8")
            profile.with_name("profile.json.meta.json").write_text(
                json.dumps({"billable_api_calls": 1, "tool": "xhs_get_user_info"}),
                encoding="utf-8",
            )
            posts.with_name("posts.json.meta.json").write_text(
                json.dumps({"billable_api_calls": 0, "tool": "fetch-cache"}),
                encoding="utf-8",
            )
            users.with_name("users.json.meta.json").write_text(
                json.dumps({"billable_api_calls": 1, "tool": "xhs_search_users"}),
                encoding="utf-8",
            )
            data = aa.build_output(
                profile,
                posts,
                [],
                [],
                as_of=AS_OF,
                immature_hours=24,
                extra_source_paths=[profile, users],
            )
        self.assertEqual(data["api_calls"], 2)
        self.assertTrue(data["used_cache"])
        self.assertEqual(data["source_files"].count(str(profile)), 1)
        self.assertIn(str(users), data["source_files"])

    def test_cli_writes_normalized_and_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS / "analyze_account.py"),
                    "--profile",
                    str(FIXTURES / "profile.json"),
                    "--posts",
                    str(FIXTURES / "posts.json"),
                    "--detail",
                    str(FIXTURES / "detail-high.json"),
                    "--detail",
                    str(FIXTURES / "detail-low.json"),
                    "--comments",
                    str(FIXTURES / "comments.json"),
                    "--out-dir",
                    tmp,
                    "--as-of",
                    "2026-08-04T12:00:00Z",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertTrue((Path(tmp) / "normalized.json").is_file())
            self.assertTrue((Path(tmp) / "report-skeleton.md").is_file())

    def test_invalid_json_returns_nonzero_and_names_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            broken = Path(tmp) / "broken.json"
            broken.write_text("{", encoding="utf-8")
            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS / "analyze_account.py"),
                    "--profile",
                    str(broken),
                    "--posts",
                    str(FIXTURES / "posts.json"),
                    "--out-dir",
                    str(Path(tmp) / "out"),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
        self.assertEqual(completed.returncode, 2)
        self.assertIn(str(broken), completed.stderr)


if __name__ == "__main__":
    unittest.main()
