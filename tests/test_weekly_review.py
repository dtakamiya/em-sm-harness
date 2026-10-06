import copy
import json
import sys
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import weekly_review as wr  # noqa: E402

SAMPLE = ROOT / "skills" / "weekly-review" / "examples"
TODAY = date(2026, 10, 9)  # 金曜
BANNED_WORDS = ("遅れ", "怠", "サボ", "優秀", "問題あり", "停滞している", "評価")


def _tasks():
    return json.loads((SAMPLE / "tasks.sample.json").read_text(encoding="utf-8"))["tasks"]


class WeeklyReviewTest(unittest.TestCase):
    def setUp(self):
        self.w = wr.build_review(_tasks(), TODAY)
        self.ids = lambda key: [t["id"] for t in self.w[key]]

    def test_week_starts_on_monday(self):
        self.assertEqual(wr.week_start(TODAY), date(2026, 10, 5))
        self.assertEqual(wr.week_start(date(2026, 10, 5)), date(2026, 10, 5))

    def test_counts_done_only_within_this_week(self):
        self.assertEqual(self.ids("done"), ["t-0201"])

    def test_counts_added_within_this_week(self):
        self.assertEqual(self.ids("added"), ["t-0204", "t-0206", "t-0207"])

    def test_counts_deferral_operations(self):
        self.assertEqual(self.w["deferrals"], 2)
        self.assertEqual(self.ids("deferred_repeat"), ["t-0203"])

    def test_carry_in_is_active_task_added_before_this_week(self):
        self.assertEqual(self.ids("carry_in"), ["t-0202", "t-0203"])

    def test_overdue_excludes_task_due_today(self):
        tasks = _tasks() + [{"id": "t-0299", "title": "x", "status": "open", "due": "2026-10-09", "history": []}]
        self.assertEqual([t["id"] for t in wr.build_review(tasks, TODAY)["overdue"]], ["t-0202"])

    def test_waiting_overdue_and_unset_are_separate(self):
        self.assertEqual(self.ids("wait_overdue"), ["t-0205"])
        self.assertEqual(self.ids("wait_unset"), ["t-0206"])

    def test_wait_age_uses_last_wait_op_and_admits_missing(self):
        out = wr.render(self.w)
        self.assertIn("返信待ちにして 6 日", out)
        self.assertIn("返信待ちにした日は記録なし", out)

    def test_snoozed_task_is_excluded(self):
        tasks = _tasks()
        tasks[1] = {**tasks[1], "snooze_until": "2026-10-20"}
        self.assertNotIn("t-0202", [t["id"] for t in wr.build_review(tasks, TODAY)["overdue"]])

    def test_matches_expected_output_sample(self):
        expected = (SAMPLE / "expected-output.md").read_text(encoding="utf-8")
        self.assertEqual(wr.render(self.w), expected)

    def test_body_is_under_600_chars_and_has_no_evaluative_words(self):
        out = wr.render(self.w)
        self.assertLess(len(out.split("## 詳細")[0]), 600)
        for word in BANNED_WORDS:
            self.assertNotIn(word, out)

    def test_each_section_shows_at_most_five_lines(self):
        many = [{"id": f"t-{i:04d}", "title": "x", "status": "open", "due": "2026-10-01",
                 "history": [{"at": "2026-09-20", "op": "add"}]} for i in range(8)]
        out = wr.render(wr.build_review(many, TODAY))
        self.assertIn("ほか 3 件", out)

    def test_empty_week_reports_nothing_to_do(self):
        out = wr.render(wr.build_review([], TODAY))
        self.assertIn("🟢 順調", out)
        self.assertIn("対応不要", out)

    def test_does_not_mutate_input(self):
        tasks = _tasks()
        before = copy.deepcopy(tasks)
        wr.render(wr.build_review(tasks, TODAY))
        self.assertEqual(tasks, before)

    def test_missing_file_gives_empty_review(self):
        self.assertEqual(wr._load(str(ROOT / "nope.json"), "tasks"), [])


if __name__ == "__main__":
    unittest.main()
