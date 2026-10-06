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

    def _task(self, tid, status="open", blocks=()):
        return {"id": tid, "title": "x", "status": status, "priority": "soon",
                "due": "2026-10-20", "blocks": list(blocks), "history": []}

    def test_task_blocking_more_comes_first_in_same_band(self):
        tasks = [self._task("t-1"), self._task("t-2", blocks=["t-3", "t-4"]),
                 self._task("t-3"), self._task("t-4")]
        plan = mp.build_plan(tasks, [], TODAY)
        self.assertEqual(plan["top"][0]["id"], "t-2")

    def test_done_task_is_not_counted_as_blocked(self):
        tasks = [self._task("t-1"), self._task("t-2", blocks=["t-9"]), self._task("t-9", status="done")]
        plan = mp.build_plan(tasks, [], TODAY)
        self.assertEqual([t["id"] for t in plan["top"]], ["t-1", "t-2"])

    def test_order_is_deterministic(self):
        first = mp.build_plan(self.tasks, self.cands, TODAY)["top"]
        second = mp.build_plan(list(reversed(self.tasks)), self.cands, TODAY)["top"]
        self.assertEqual([t["id"] for t in first], [t["id"] for t in second])

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


class MorningPlanProactiveTest(unittest.TestCase):
    def test_proactive_section_is_added_only_when_requested(self):
        import contextlib
        import io
        import tempfile
        argv = ["--tasks", str(SAMPLES / "tasks.sample.json"), "--candidates", str(SAMPLES / "candidates.sample.json"),
                "--today", "2026-10-04"]
        with tempfile.TemporaryDirectory() as tmp:
            extra = ["--proactive", "--jira-dir", f"{tmp}/jira", "--meetings", f"{tmp}/none.json", "--state", f"{tmp}/s.json"]
            outs = []
            for flags in ([], extra):
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    mp.main(argv + flags)
                outs.append(buf.getvalue())
        self.assertNotIn("## 先回り", outs[0])
        self.assertIn("## 先回り（観察）", outs[1])
        self.assertLess(outs[1].index("## 先回り"), outs[1].index("## 詳細"))

    def test_waiting_task_with_two_nudges_is_decision_only_not_draft_target(self):
        import contextlib
        import io
        import json
        import tempfile
        t = {"id": "t-1", "title": "x", "status": "waiting", "waiting_on": "member-a", "next_check": "2026-10-04",
             "due": None, "blocks": [], "updated": "2026-10-04",
             "history": [{"at": "2026-10-01", "op": "nudge"}, {"at": "2026-10-02", "op": "nudge"}]}
        with tempfile.TemporaryDirectory() as tmp:
            tasks = f"{tmp}/t.json"
            Path(tasks).write_text(json.dumps({"tasks": [t]}), encoding="utf-8")
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mp.main(["--tasks", tasks, "--candidates", f"{tmp}/c.json", "--today", "2026-10-04", "--proactive",
                         "--jira-dir", f"{tmp}/j", "--meetings", f"{tmp}/m.json", "--state", f"{tmp}/s.json"])
        out = buf.getvalue()
        self.assertNotIn("返信待ちの催促候補", out)
        self.assertIn("判断依頼", out)

    def _run_with(self, tasks_text):
        import contextlib
        import io
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            Path(f"{tmp}/t.json").write_text(tasks_text, encoding="utf-8")
            argv = ["--tasks", f"{tmp}/t.json", "--candidates", f"{tmp}/c.json", "--today", "2026-10-04",
                    "--proactive", "--jira-dir", f"{tmp}/j", "--meetings", f"{tmp}/m.json", "--state", f"{tmp}/s.json"]
            with contextlib.redirect_stdout(io.StringIO()):
                mp.main(argv)

    def test_failure_after_collect_leaves_state_unchanged(self):
        import contextlib
        import io
        import json
        import tempfile
        t = {"id": "t-1", "title": "x", "status": "open", "due": "2026-10-05", "updated": "2026-10-01", "history": []}
        with tempfile.TemporaryDirectory() as tmp:
            Path(f"{tmp}/t.json").write_text(json.dumps({"tasks": [t]}), encoding="utf-8")
            Path(f"{tmp}/c.json").write_text("[]", encoding="utf-8")  # 候補ファイルが不正 → collect の後で失敗
            state = f"{tmp}/s.json"
            Path(state).write_text(json.dumps({"due:t-1": {"level": "中", "shown_count": 2, "last_shown": "2026-09-29",
                                                          "first_seen": "2026-10-01", "snooze_until": None}}))
            before = Path(state).read_text()
            argv = ["--tasks", f"{tmp}/t.json", "--candidates", f"{tmp}/c.json", "--today", "2026-10-04", "--proactive",
                    "--jira-dir", f"{tmp}/j", "--meetings", f"{tmp}/m.json", "--state", state]
            with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(SystemExit):
                mp.main(argv)
            self.assertEqual(Path(state).read_text(), before)
            Path(f"{tmp}/c.json").write_text('{"candidates": []}', encoding="utf-8")
            with contextlib.redirect_stdout(io.StringIO()):
                mp.main(argv)
            self.assertEqual(json.loads(Path(state).read_text())["due:t-1"]["shown_count"], 3)

    def test_malformed_inputs_stop_with_message_instead_of_traceback(self):
        for text in ("[]", '{"tasks": [{"id": "t-1", "title": "x"}]}',
                     '{"tasks": [{"id": "t-1", "title": "x", "status": "open", "updated": null}]}',
                     '{"tasks": [{"id": "t-1", "title": "x", "status": "open", "updated": "2026-10-01", "due": "bad"}]}'):
            with self.subTest(text=text), self.assertRaises(SystemExit) as cm:
                self._run_with(text)
            self.assertIsInstance(cm.exception.code, str)


if __name__ == "__main__":
    unittest.main()
