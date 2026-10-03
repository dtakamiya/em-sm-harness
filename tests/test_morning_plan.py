import json
import sys
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import morning_plan as mp  # noqa: E402

SAMPLES = ROOT / "skills" / "morning-plan" / "examples"
TODAY = date(2026, 10, 4)


def load(name, key):
    return json.loads((SAMPLES / name).read_text(encoding="utf-8"))[key]


class MorningPlanTest(unittest.TestCase):
    def setUp(self):
        self.tasks = load("tasks.sample.json", "tasks")
        self.cands = load("candidates.sample.json", "candidates")
        self.plan = mp.build_plan(self.tasks, self.cands, TODAY)

    def test_overdue_task_comes_first(self):
        self.assertEqual(self.plan["top"][0]["id"], "t-0001")

    def test_snoozed_task_is_hidden(self):
        ids = [t["id"] for t in self.plan["top"]]
        self.assertNotIn("t-0007", ids)

    def test_snoozed_task_returns_after_snooze_date(self):
        plan = mp.build_plan(self.tasks, [], date(2026, 10, 14))
        self.assertIn("t-0007", [t["id"] for t in plan["top"]])

    def test_only_due_waiting_tasks_are_nudged(self):
        self.assertEqual([t["id"] for t in self.plan["nudges"]], ["t-0004"])

    def test_third_defer_asks_for_decision(self):
        self.assertEqual([t["id"] for t in self.plan["defer_asks"]], ["t-0003"])

    def test_top_is_capped(self):
        many = [dict(self.tasks[0], id=f"t-{i:04d}") for i in range(10, 20)]
        plan = mp.build_plan(many, [], TODAY)
        self.assertEqual(len(plan["top"]), mp.MAX_TOP)
        self.assertEqual(plan["overflow"], 5)

    def test_inputs_are_not_mutated(self):
        before = json.dumps(self.tasks, sort_keys=True)
        mp.render(self.plan)
        self.assertEqual(before, json.dumps(self.tasks, sort_keys=True))

    def test_render_starts_with_conclusion_and_says_unsent(self):
        text = mp.render(self.plan)
        self.assertIn("🔴 要対応: 期限超過 1 件", text)
        self.assertIn("未送信の下書き", text)
        self.assertNotIn("送信しました", text)

    def test_render_is_short_enough_for_60_seconds(self):
        self.assertLess(len(mp.render(self.plan)), 900)

    def test_no_work_says_not_needed(self):
        text = mp.render(mp.build_plan([], [], TODAY))
        self.assertIn("対応不要", text)
        self.assertIn("🟢 順調", text)

    def test_missing_file_is_empty(self):
        self.assertEqual(mp._load("/nonexistent/tasks.json", "tasks"), [])


if __name__ == "__main__":
    unittest.main()
