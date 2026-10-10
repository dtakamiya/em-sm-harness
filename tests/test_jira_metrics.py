import copy
import json
import sys
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import jira_metrics as jm  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures" / "jira-metrics"
BANNED_WORDS = ("遅れ", "怠", "サボ", "放置", "停滞している", "問題あり", "原因は", "assignee_ref", "u_")


def _cache(name="jira-cache.sample.json"):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class StagnationTest(unittest.TestCase):
    def test_counts_issues_at_or_over_threshold_by_updated(self):
        # Arrange / Act
        result = jm.stagnation(_cache()["issues"], date(2026, 10, 9))
        # Assert（EX-102 は 9/30→10/9 でちょうど 7 営業日、EX-103 は 6 営業日）
        self.assertEqual(result["stale_keys"], ["EX-101", "EX-102"])
        self.assertEqual(result["population"], 7)


class ScopeChangeTest(unittest.TestCase):
    def setUp(self):
        issues = _cache()["issues"]
        self.sc = jm.scope_change(issues, jm.active_sprint(issues))
        self.keys = lambda g: [i["key"] for i in self.sc[g]]

    def test_change_on_grace_boundary_is_excluded_and_one_day_later_is_added(self):
        self.assertEqual(self.keys("added"), ["EX-105"])  # EX-104 は猶予ちょうど→計画の一部

    def test_removed_and_carried_over_are_separate(self):
        self.assertEqual(self.keys("removed"), ["EX-106"])
        self.assertEqual(self.keys("carried"), ["EX-107"])

    def test_null_story_points_are_excluded_and_zero_is_included(self):
        self.assertEqual(jm._sum_points(self.sc["added"]), (0, 1))
        self.assertEqual(jm._sum_points(self.sc["removed"]), (0, 0))


    def test_carried_over_issue_is_not_double_counted_as_added(self):
        # Arrange: 繰り越し課題の移動が猶予を超えて記録されている
        issues = _cache()["issues"]
        sprint = jm.active_sprint(issues)
        issues[6]["transitions"] = [{"field": "sprint", "from": "Sprint 10", "to": "Sprint 11", "at": "2026-10-02"}]
        # Act
        sc = jm.scope_change(issues, sprint)
        # Assert
        self.assertEqual([i["key"] for i in sc["carried"]], ["EX-107"])
        self.assertNotIn("EX-107", [i["key"] for i in sc["added"]])


class ProgressTest(unittest.TestCase):
    def test_sums_done_and_remaining_points_of_active_sprint_and_counts_unestimated(self):
        # Arrange
        issues = _cache()["issues"]
        sprint = jm.active_sprint(issues)
        members = [i for i in issues if any(s["id"] == sprint["id"] for s in i["sprints"])]
        expected_done = sum(i["story_points"] or 0 for i in members if i["status_category"] == "done")
        expected_open = sum(i["story_points"] or 0 for i in members if i["status_category"] != "done")
        expected_null = sum(1 for i in members if i["story_points"] is None)
        # Act
        result = jm.progress(issues, sprint)
        # Assert
        self.assertEqual(result, {"done": expected_done, "remaining": expected_open, "unestimated": expected_null})

    def test_null_points_are_not_counted_as_zero_and_issues_outside_sprint_are_ignored(self):
        # Arrange
        sprint = {"id": 11}
        issues = [
            {"status_category": "done", "story_points": 3, "sprints": [{"id": 11}]},
            {"status_category": "indeterminate", "story_points": 0, "sprints": [{"id": 11}]},
            {"status_category": "new", "story_points": None, "sprints": [{"id": 11}]},
            {"status_category": "done", "story_points": 8, "sprints": [{"id": 10}]},
        ]
        # Act / Assert
        self.assertEqual(jm.progress(issues, sprint), {"done": 3, "remaining": 0, "unestimated": 1})

    def test_report_shows_progress_line_without_plan_or_rate(self):
        # Act
        out = jm.build_report(_cache())
        # Assert
        self.assertRegex(out, r"進捗（Sprint 11）: 完了 \d+ SP / 残 \d+ SP")
        for word in ("達成率", "計画", "%"):
            self.assertNotIn(word, out.split("進捗")[1].split("\n")[0])


class ReportTest(unittest.TestCase):
    def test_incomplete_cache_reports_refetch_only(self):
        self.assertEqual(jm.build_report(_cache("jira-cache.incomplete.json")), jm.REFETCH_MESSAGE)

    def test_four_in_progress_shows_count_only_and_five_shows_ratio(self):
        cache = _cache()
        for i in cache["issues"][4:]:
            i["status_category"] = "new"
        self.assertIn("割合は出さない", jm.build_report(cache))  # 進行中 4
        cache["issues"][4]["status_category"] = "indeterminate"
        self.assertIn("のうち", jm.build_report(cache))  # 進行中 5

    def test_output_has_no_evaluative_words_or_assignee_info(self):
        cache = copy.deepcopy(_cache())
        cache["issues"][0]["assignee_ref"] = "u_a1b2c3d4"
        report = jm.build_report(cache)
        for word in BANNED_WORDS:
            self.assertNotIn(word, report)

    def test_no_active_sprint_is_stated_not_guessed(self):
        cache = _cache()
        for i in cache["issues"]:
            i["sprints"] = []
        self.assertIn("active なスプリントがない", jm.build_report(cache))

    def test_report_and_help_label_prototype_and_explain_terms(self):
        report = jm.build_report(_cache())
        for text in ("試作・架空サンプル専用", "SP=ストーリーポイント", "N=対象の課題数"):
            self.assertIn(text, report)
        self.assertIn("試作・架空サンプル専用", jm.__doc__)

    def test_cli_rejects_missing_file_without_output(self):
        with self.assertRaises(SystemExit) as ctx:
            jm.main([str(FIXTURES / "nope.json")])
        self.assertIn("キャッシュを読めません", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
