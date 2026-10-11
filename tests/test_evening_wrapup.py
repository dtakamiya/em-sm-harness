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
    @staticmethod
    def _waiting(tid, **kw):
        return {"id": tid, "title": "x", "status": "waiting", "waiting_on": "member-a", "due": None, **kw}

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

    def test_waiting_touched_today_by_wait_op(self):
        self.assertEqual(self.ids("new_waiting"), ["t-0104"])

    def test_waiting_with_only_updated_today_is_picked_up(self):
        task = self._waiting("t-9", next_check="2026-10-09", updated="2026-10-05", history=[])
        self.assertEqual([t["id"] for t in ew.build_wrapup([task], TODAY)["new_waiting"]], ["t-9"])

    def test_waiting_without_next_check_does_not_crash(self):
        task = self._waiting("t-9", next_check=None, updated="2026-10-05", history=[])
        out = ew.render(ew.build_wrapup([task], TODAY))
        self.assertIn("確認予定未設定", out)

    def test_overdue_check_waiting_gets_own_section_and_yellow(self):
        task = self._waiting("t-9", next_check="2026-10-05", updated="2026-10-01", history=[])
        w = ew.build_wrapup([task], TODAY)
        out = ew.render(w)
        self.assertEqual([t["id"] for t in w["nudge_due"]], ["t-9"])
        self.assertIn("確認予定を過ぎた返信待ち", out)
        self.assertIn("🟡 注意", out)

    def test_due_today_open_task_is_carried_over_as_today(self):
        task = {"id": "t-9", "title": "x", "status": "open", "due": "2026-10-05", "history": []}
        out = ew.render(ew.build_wrapup([task], TODAY))
        self.assertIn("今日期限", out)

    def test_more_than_five_items_collapse_to_count(self):
        tasks = [{"id": f"t-{i}", "title": "x", "status": "open", "due": "2026-10-01", "history": []}
                 for i in range(7)]
        self.assertIn("ほか 2 件", ew.render(ew.build_wrapup(tasks, TODAY)))

    def test_single_defer_does_not_trigger_decision_request(self):
        task = {"id": "t-9", "title": "x", "status": "open", "due": "2026-10-20",
                "history": [{"at": "2026-10-05", "op": "defer"}]}
        w = ew.build_wrapup([task], TODAY)
        self.assertEqual(w["defer_asks"], [])
        self.assertIn("🟡 注意", ew.render(w))

    def test_second_defer_triggers_decision_request(self):
        task = {"id": "t-9", "title": "x", "status": "open", "due": "2026-10-20",
                "history": [{"at": "2026-10-03", "op": "defer"}, {"at": "2026-10-04", "op": "defer"}]}
        self.assertEqual([t["id"] for t in ew.build_wrapup([task], TODAY)["defer_asks"]], ["t-9"])

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

    def test_has_report_only_for_carry_new_waiting_or_defer_ask(self):
        # Q-029 b): 持ち越し・新しい返信待ち・判断依頼のある日だけ出す
        self.assertTrue(ew.has_report(self.w))
        self.assertFalse(ew.has_report(ew.build_wrapup([], TODAY)))
        done_only = [{"id": "t-0199", "title": "x", "status": "done",
                      "history": [{"at": "2026-10-05", "op": "done"}]}]
        self.assertFalse(ew.has_report(ew.build_wrapup(done_only, TODAY)))

    def test_has_report_true_for_new_waiting_alone(self):
        tasks = [self._waiting("t-0200", next_check="2026-10-09",
                               history=[{"at": "2026-10-05", "op": "wait"}])]
        self.assertTrue(ew.has_report(ew.build_wrapup(tasks, TODAY)))

    def test_quiet_day_prints_one_line_unless_always(self):
        quiet = ew.render_for_day(ew.build_wrapup([], TODAY), always=False)
        self.assertEqual(quiet.count("\n"), 1)
        self.assertIn("出す内容なし", quiet)
        self.assertNotIn("## 詳細", quiet)
        full = ew.render_for_day(ew.build_wrapup([], TODAY), always=True)
        self.assertIn("対応不要", full)

    def test_busy_day_prints_full_report_by_default(self):
        self.assertEqual(ew.render_for_day(self.w, always=False), ew.render(self.w))

    def test_render_matches_expected_sample_and_stays_short(self):
        out = ew.render(self.w)
        self.assertEqual(out, (SAMPLE / "expected-output.md").read_text(encoding="utf-8"))
        self.assertLess(len(out.split("## 詳細")[0]), 600)

    def test_does_not_mutate_input(self):
        tasks = _tasks()
        before = json.dumps(tasks, sort_keys=True)
        ew.render(ew.build_wrapup(tasks, TODAY))
        self.assertEqual(json.dumps(tasks, sort_keys=True), before)

    def test_missing_tasks_file_gives_empty_report(self):
        self.assertEqual(ew._load("/nonexistent/tasks.json", "tasks"), [])


if __name__ == "__main__":
    unittest.main()
