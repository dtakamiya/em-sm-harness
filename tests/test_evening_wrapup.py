import json
import sys
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import evening_wrapup as ew  # noqa: E402

SAMPLE = ROOT / "skills" / "evening-wrapup" / "examples"
TODAY = date(2026, 10, 5)


def _tasks():
    return json.loads((SAMPLE / "tasks.sample.json").read_text(encoding="utf-8"))["tasks"]


class EveningWrapupTest(unittest.TestCase):
    def setUp(self):
        self.w = ew.build_wrapup(_tasks(), TODAY)
        self.ids = lambda key: [t["id"] for t in self.w[key]]

    def test_counts_only_tasks_done_today(self):
        tasks = _tasks() + [{"id": "t-0199", "title": "x", "status": "done",
                             "history": [{"at": "2026-10-04", "op": "done"}]}]
        self.assertEqual([t["id"] for t in ew.build_wrapup(tasks, TODAY)["done"]], ["t-0101"])

    def test_overdue_open_task_is_carried_over(self):
        self.assertEqual(self.ids("carry"), ["t-0102"])

    def test_task_deferred_today_is_not_carry_over(self):
        self.assertNotIn("t-0103", self.ids("carry"))
        self.assertEqual(self.ids("deferred"), ["t-0103"])

    def test_newly_waiting_only_when_wait_op_is_today(self):
        self.assertEqual(self.ids("new_waiting"), ["t-0104"])

    def test_tomorrow_seeds_cover_due_and_next_check(self):
        self.assertEqual(self.ids("seeds_due"), ["t-0106"])
        self.assertEqual(self.ids("seeds_check"), ["t-0105"])

    def test_defer_ask_after_two_defers(self):
        self.assertEqual(self.ids("defer_asks"), ["t-0103"])

    def test_snoozed_task_is_hidden_from_carry(self):
        tasks = [dict(t, snooze_until="2026-10-20") if t["id"] == "t-0102" else t for t in _tasks()]
        self.assertEqual(ew.build_wrapup(tasks, TODAY)["carry"], [])

    def test_empty_day_is_calm_and_needs_no_action(self):
        out = ew.render(ew.build_wrapup([], TODAY))
        self.assertIn("🟢 順調", out)
        self.assertIn("対応不要", out)

    def test_render_matches_expected_sample_and_stays_short(self):
        out = ew.render(self.w)
        self.assertEqual(out, (SAMPLE / "expected-output.md").read_text(encoding="utf-8"))
        self.assertLess(len(out), 900)

    def test_does_not_mutate_input(self):
        tasks = _tasks()
        before = json.dumps(tasks, sort_keys=True)
        ew.render(ew.build_wrapup(tasks, TODAY))
        self.assertEqual(json.dumps(tasks, sort_keys=True), before)

    def test_missing_tasks_file_gives_empty_report(self):
        self.assertEqual(ew._load("/nonexistent/tasks.json", "tasks"), [])


if __name__ == "__main__":
    unittest.main()
