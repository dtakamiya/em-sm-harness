import contextlib
import io
import json
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import proactive_scan as ps  # noqa: E402

EXAMPLES = ROOT / "skills" / "proactive-scan" / "examples"
TODAY = date(2026, 10, 7)  # 水曜


def quiet_main(argv):
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        return ps.main(argv)


def task(tid, **kw):
    base = {"id": tid, "title": "x", "status": "open", "priority": "soon", "due": None, "waiting_on": None,
            "next_check": None, "blocks": [], "source": "manual", "source_ref": None,
            "created": "2026-10-01", "updated": "2026-10-01", "history": []}
    return {**base, **kw}


def issue(key, **kw):
    base = {"key": key, "status": "In Progress", "status_category": "indeterminate", "updated": "2026-10-07",
            "assignee_ref": "u_a1b2c3d4", "links": []}
    return {**base, **kw}


class Workspace:
    def __init__(self, test, tasks, issues=None, meetings=None):
        tmp = tempfile.TemporaryDirectory()
        test.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.tasks_p = self.dir / "tasks.json"
        self.jira_d = self.dir / "jira"
        self.meet_p = self.dir / "meetings.json"
        self.state_p = self.dir / "state" / "proactive.json"
        if tasks is not None:
            self.tasks_p.write_text(json.dumps({"tasks": tasks}), encoding="utf-8")
        if issues is not None:
            (self.jira_d / "ex-proj").mkdir(parents=True)
            doc = {"fetched_at": "2026-10-07T08:00:00+09:00", "issues": issues}
            (self.jira_d / "ex-proj" / "2026-10-07.json").write_text(json.dumps(doc), encoding="utf-8")
        if meetings is not None:
            self.meet_p.write_text(json.dumps({"meetings": meetings}), encoding="utf-8")

    def run(self, today=TODAY, digest=False):
        return ps.collect((self.tasks_p, self.jira_d, self.meet_p, self.state_p), today, digest)

    def state(self):
        return json.loads(self.state_p.read_text(encoding="utf-8"))


class DetectionTest(unittest.TestCase):
    def test_due_in_three_days_is_medium_and_four_days_is_not_shown(self):  # 受入 1
        tasks = [task("t-1", due="2026-10-10"), task("t-2", due="2026-10-11")]
        found = {f["ref"]: f["level"] for f in ps.detect_due(tasks, TODAY)}
        self.assertEqual(found, {"t-1": "中"})

    def test_overdue_and_today_are_high(self):
        found = ps.detect_due([task("t-1", due="2026-10-06"), task("t-2", due="2026-10-07")], TODAY)
        self.assertEqual([f["level"] for f in found], ["高", "高"])

    def test_done_task_is_not_detected(self):
        self.assertEqual(ps.detect_due([task("t-1", status="done", due="2026-10-01")], TODAY), [])

    def test_blocker_quiet_three_bdays_is_medium_and_urgent_blocked_task_makes_it_high(self):
        issues = [issue("EX-1", updated="2026-10-02", links=[{"link_type": "blocks", "direction": "outward", "issue_key": "EX-2"}]),
                  issue("EX-2", status_category="new")]
        self.assertEqual(ps.detect_blockers(issues, [], TODAY)[0]["level"], "中")
        urgent = task("t-9", source="jira", source_ref="EX-2", due="2026-10-09")
        self.assertEqual(ps.detect_blockers(issues, [urgent], TODAY)[0]["level"], "高")

    def test_recently_updated_blocker_is_not_detected(self):
        issues = [issue("EX-1", updated="2026-10-06", links=[{"link_type": "blocks", "direction": "outward", "issue_key": "EX-2"}]),
                  issue("EX-2", status_category="new")]
        self.assertEqual(ps.detect_blockers(issues, [], TODAY), [])

    def test_stale_jira_seven_bdays_and_task_fourteen_days_are_low(self):
        issues = [issue("EX-1", updated="2026-09-25"), issue("EX-2", updated="2026-09-29")]
        tasks = [task("t-1", updated="2026-09-23"), task("t-2", updated="2026-09-24")]
        refs = {f["ref"] for f in ps.detect_stale(issues, tasks, TODAY)}
        self.assertEqual(refs, {"EX-1", "t-1"})

    def test_meeting_without_prep_next_bday_is_medium_and_far_meeting_is_ignored(self):
        meetings = json.loads((EXAMPLES / "meetings.sample.json").read_text(encoding="utf-8"))["meetings"]
        tasks = [task("t-0003", status="open")]
        found = ps.detect_meetings(meetings, tasks, TODAY)
        self.assertEqual([f["ref"] for f in found], ["m-0001", "m-0002"])

    def test_meeting_with_done_prep_is_not_detected(self):
        meetings = [{"id": "m-1", "title": "x", "start": "2026-10-08", "prep_task_id": "t-1"}]
        self.assertEqual(ps.detect_meetings(meetings, [task("t-1", status="done")], TODAY), [])

    def test_friday_looks_ahead_to_monday(self):
        meetings = [{"id": "m-1", "title": "x", "start": "2026-10-12", "prep_task_id": None}]
        self.assertEqual(len(ps.detect_meetings(meetings, [], date(2026, 10, 9))), 1)

    def test_same_target_is_one_line_with_higher_level_and_both_rule_names(self):
        tasks = [task("t-1", due="2026-10-09", updated="2026-09-01")]
        found = ps.scan(tasks, [], None, TODAY)
        self.assertEqual([(f["ref"], f["level"], f["rules"]) for f in found], [("t-1", "中", ["due", "stale"])])


class SelectionTest(unittest.TestCase):
    def test_same_input_twice_gives_same_output_and_count_stays(self):  # 受入 2
        ws = Workspace(self, [task("t-1", due="2026-10-09")])
        first = ps.render(*ws.run()[:3], TODAY)
        count = ws.state()["due:t-1"]["shown_count"]
        second = ps.render(*ws.run()[:3], TODAY)
        self.assertEqual(first, second)
        self.assertEqual(ws.state()["due:t-1"]["shown_count"], count)

    def test_waiting_with_two_nudges_becomes_decision_request(self):  # 受入 3
        t = task("t-1", status="waiting", waiting_on="member-a", next_check="2026-10-07",
                 history=[{"at": "2026-10-01", "op": "nudge"}, {"at": "2026-10-03", "op": "nudge"}])
        ws = Workspace(self, [t])
        shown, _, decisions, _ = ws.run()
        self.assertEqual(decisions, {"waiting:t-1"})
        self.assertEqual(shown[0]["level"], "高")
        text = ps.render(shown, 0, decisions, TODAY)
        self.assertIn("判断依頼", text)
        self.assertNotIn("下書き", text)

    def test_eight_findings_show_five_plus_other_three_with_nudges_capped_at_three(self):  # 受入 4
        due = [task(f"t-{i}", due="2026-10-06") for i in range(2)]
        nudges = [task(f"w-{i}", status="waiting", waiting_on="member-a", next_check="2026-10-06") for i in range(6)]
        ws = Workspace(self, due + nudges)
        shown, overflow, _, _ = ws.run()
        self.assertEqual((len(shown), overflow), (5, 3))
        self.assertEqual([f["level"] for f in shown][:2], ["高", "高"])
        self.assertEqual(sum(f["rule"] == "waiting" for f in shown), 3)

    def test_overdue_keeps_showing_after_three_or_more_displays(self):  # 受入 5
        ws = Workspace(self, [task("t-1", due="2026-10-01")])
        for day in (5, 6, 7, 8, 9):
            shown, _, decisions, _ = ws.run(date(2026, 10, day))
            self.assertEqual([f["ref"] for f in shown], ["t-1"])
            self.assertEqual(decisions, set())

    def test_missing_meetings_only_notes_that_rule_and_others_continue(self):  # 受入 6
        ws = Workspace(self, [task("t-1", due="2026-10-07")], issues=[])
        shown, _, decisions, notes = ws.run()
        self.assertEqual([f["ref"] for f in shown], ["t-1"])
        self.assertTrue(any("会議一覧: 入力なし" in n for n in notes))
        self.assertIn("会議一覧: 入力なし", ps.render(shown, 0, decisions, TODAY, notes))

    def test_medium_is_suppressed_for_two_bdays_then_returns(self):
        ws = Workspace(self, [task("t-1", due="2026-10-09")])
        self.assertEqual(len(ws.run(TODAY)[0]), 1)
        self.assertEqual(len(ws.run(date(2026, 10, 8))[0]), 0)
        self.assertEqual(len(ws.run(date(2026, 10, 9))[0]), 1)

    def test_medium_shown_three_times_is_promoted_once_then_silent(self):
        ws = Workspace(self, [task("t-1", due="2026-10-30", updated="2026-09-01")])  # 低は digest のみ
        days = [date(2026, 10, 7), date(2026, 10, 12), date(2026, 10, 14), date(2026, 10, 19)]
        results = [ws.run(d, digest=True) for d in days]
        self.assertEqual([r[2] for r in results], [set(), set(), set(), {"stale:t-1"}])
        self.assertEqual(ws.run(date(2026, 10, 26), digest=True)[0], [])

    def test_ack_hides_until_level_rises(self):
        ws = Workspace(self, [task("t-1", due="2026-10-15")])
        ws.run(date(2026, 10, 12))
        ps.save_state(ws.state_p, ps.apply_ack(ws.state(), "due:t-1"))
        self.assertEqual(ws.run(date(2026, 10, 14))[0], [])
        self.assertEqual([f["level"] for f in ws.run(date(2026, 10, 15))[0]], ["高"])  # 当日期限 = 段が上がり再掲

    def test_snooze_hides_even_high_until_date(self):
        ws = Workspace(self, [task("t-1", due="2026-10-01")])
        ws.run(TODAY)
        ps.save_state(ws.state_p, ps.apply_ack(ws.state(), "due:t-1", date(2026, 10, 9)))
        self.assertEqual(ws.run(date(2026, 10, 8))[0], [])
        self.assertEqual(len(ws.run(date(2026, 10, 9))[0]), 1)

    def test_zero_findings_says_no_action_needed(self):
        ws = Workspace(self, [task("t-1")], issues=[], meetings=[])
        shown, overflow, decisions, notes = ws.run()
        self.assertIn("先回り対応不要", ps.render(shown, overflow, decisions, TODAY, notes))

    def test_state_keeps_only_keys_and_counts_and_prunes_old_resolved(self):
        ws = Workspace(self, [task("t-1", due="2026-10-09")])
        ws.state_p.parent.mkdir(parents=True)
        ws.state_p.write_text(json.dumps({"due:gone": {"level": "中", "last_shown": "2026-06-01"}}))
        ws.run()
        state = ws.state()
        self.assertNotIn("due:gone", state)
        self.assertEqual(set(state["due:t-1"]), {"first_seen", "shown_count", "level", "snooze_until", "last_shown"})

    def test_corrupt_state_is_treated_as_new_and_backup_kept(self):
        ws = Workspace(self, [task("t-1", due="2026-10-09")])
        ws.state_p.parent.mkdir(parents=True)
        ws.state_p.write_text("{broken")
        self.assertEqual(len(ws.run()[0]), 1)
        ws.run(date(2026, 10, 8))
        self.assertTrue(ws.state_p.with_suffix(".json.bak").exists())


class SafetyTest(unittest.TestCase):
    def test_corrupt_tasks_exits_2_and_leaves_state_unchanged(self):  # 受入 7
        ws = Workspace(self, None)
        ws.tasks_p.write_text("{broken")
        ws.state_p.parent.mkdir(parents=True)
        ws.state_p.write_text('{"a": {}}')
        code = quiet_main(["--tasks", str(ws.tasks_p), "--jira-dir", str(ws.jira_d), "--meetings", str(ws.meet_p),
                        "--state", str(ws.state_p), "--audit-dir", str(ws.dir / "audit"), "--today", "2026-10-07"])
        self.assertEqual(code, ps.EXIT_BROKEN)
        self.assertEqual(ws.state_p.read_text(), '{"a": {}}')

    def test_output_has_no_assignee_ref_or_judgmental_words(self):  # 受入 8
        issues = [issue("EX-1", updated="2026-09-20", assignee_ref="u_deadbeef",
                        links=[{"link_type": "blocks", "direction": "outward", "issue_key": "EX-2"}]),
                  issue("EX-2", status_category="new", assignee_ref="u_cafef00d")]
        ws = Workspace(self, [task("t-1", due="2026-10-01", updated="2026-09-01"),
                              task("w-1", status="waiting", waiting_on="member-a", next_check="2026-10-06")],
                       issues=issues, meetings=[{"id": "m-1", "title": "x", "start": "2026-10-08", "prep_task_id": None}])
        text = ps.render(*ws.run()[:3], TODAY) + ps.render(*ws.run(TODAY, digest=True)[:3], TODAY)
        for banned in ("u_deadbeef", "u_cafef00d", "assignee", "遅い", "放置", "怠", "サボ"):
            self.assertNotIn(banned, text)
        self.assertIn("EX-1", text)

    def test_exit_code_is_10_when_notified_and_0_when_not(self):
        ws = Workspace(self, [task("t-1", due="2026-10-07")])
        argv = ["--tasks", str(ws.tasks_p), "--jira-dir", str(ws.jira_d), "--meetings", str(ws.meet_p),
                "--state", str(ws.state_p), "--audit-dir", str(ws.dir / "audit"), "--today", "2026-10-07"]
        self.assertEqual(quiet_main(argv), ps.EXIT_NOTIFY)
        ws.tasks_p.write_text(json.dumps({"tasks": []}))
        self.assertEqual(quiet_main(argv), ps.EXIT_NONE)

    def test_ack_writes_audit_line_with_key_and_op_only(self):
        ws = Workspace(self, [task("t-1", due="2026-10-09")])
        ws.run()
        audit = ws.dir / "audit"
        quiet_main(["--state", str(ws.state_p), "--audit-dir", str(audit), "--today", "2026-10-07", "--ack", "due:t-1"])
        rows = [json.loads(line) for line in (audit / "2026-10-07.jsonl").read_text().splitlines()]
        self.assertEqual(rows, [{"at": "2026-10-07", "op": "ack", "key": "due:t-1"}])


class WriteFailureTest(unittest.TestCase):
    """状態・監査ファイルに書けないときは traceback でなく、原因つき 1 行で exit 2。"""

    def _blocked(self, ws):
        blocker = ws.dir / "blocker"
        blocker.write_text("x")  # ファイルを親ディレクトリ扱いさせて書込失敗を作る（権限に依存しない）
        return blocker

    def _run(self, argv):
        err = io.StringIO()
        with contextlib.redirect_stdout(io.StringIO()) as out, contextlib.redirect_stderr(err):
            code = ps.main(argv)
        return code, out.getvalue(), err.getvalue()

    def test_scan_with_unwritable_state_exits_2_with_cause_and_no_report(self):
        ws = Workspace(self, [task("t-1", due="2026-10-09")])
        blocked = self._blocked(ws)
        code, out, err = self._run(["--tasks", str(ws.tasks_p), "--jira-dir", str(ws.jira_d), "--meetings", str(ws.meet_p),
                                    "--state", str(blocked / "p.json"), "--today", "2026-10-07"])
        self.assertEqual(code, ps.EXIT_BROKEN)
        self.assertEqual(out, "")
        self.assertIn("書き込めません", err)
        self.assertIn("状態は更新していません", err)
        self.assertNotIn("Traceback", err)
        self.assertEqual(len(err.strip().splitlines()), 1)

    def test_failed_replace_leaves_old_state_and_no_tmp_file(self):
        ws = Workspace(self, [task("t-1", due="2026-10-09")])
        ws.run()
        before = ws.state_p.read_text()
        with mock.patch.object(ps.os, "replace", side_effect=PermissionError(13, "Permission denied")):
            with self.assertRaises(ps.WriteFailed):
                ps.save_state(ws.state_p, {"k": {}})
        self.assertEqual(ws.state_p.read_text(), before)
        self.assertEqual(list(ws.state_p.parent.glob("*.tmp")), [])

    def test_ack_with_unwritable_state_exits_2_and_says_not_updated(self):
        ws = Workspace(self, [task("t-1", due="2026-10-09")])
        ws.run()
        with mock.patch.object(ps, "save_state", side_effect=ps.WriteFailed("p に書き込めません（x）")):
            code, _, err = self._run(["--state", str(ws.state_p), "--audit-dir", str(ws.dir / "a"),
                                      "--today", "2026-10-07", "--ack", "due:t-1"])
        self.assertEqual(code, ps.EXIT_BROKEN)
        self.assertIn("状態は更新していません", err)
        self.assertFalse((ws.dir / "a").exists())

    def test_ack_with_unwritable_audit_says_state_updated_but_audit_missing(self):
        ws = Workspace(self, [task("t-1", due="2026-10-09")])
        ws.run()
        blocked = self._blocked(ws)
        code, _, err = self._run(["--state", str(ws.state_p), "--audit-dir", str(blocked / "a"),
                                  "--today", "2026-10-07", "--ack", "due:t-1"])
        self.assertEqual(code, ps.EXIT_BROKEN)
        self.assertIn("状態は更新済み", err)
        self.assertIn("監査ログ", err)
        self.assertNotIn("Traceback", err)
        self.assertEqual(ws.state()["due:t-1"]["acked_level"], "中")


class WriteFailureEdgeTest(unittest.TestCase):
    _blocked = WriteFailureTest._blocked
    _run = WriteFailureTest._run

    def test_unreadable_state_exits_2_with_cause_instead_of_treating_as_new(self):
        ws = Workspace(self, [task("t-1", due="2026-10-09")])
        ws.run()
        real_read = Path.read_text

        def deny_state(self, *args, **kwargs):
            if self == ws.state_p:
                raise PermissionError(13, "Permission denied")
            return real_read(self, *args, **kwargs)

        with mock.patch.object(Path, "read_text", deny_state):
            code, out, err = self._run(["--tasks", str(ws.tasks_p), "--jira-dir", str(ws.jira_d), "--meetings", str(ws.meet_p),
                                        "--state", str(ws.state_p), "--today", "2026-10-07"])
        self.assertEqual(code, ps.EXIT_BROKEN)
        self.assertEqual(out, "")
        self.assertIn("読めません", err)
        self.assertIn("状態は変更していません", err)

    def test_state_under_a_file_is_treated_as_missing(self):
        ws = Workspace(self, [])
        self.assertEqual(ps.load_state(self._blocked(ws) / "p.json"), {})

    def test_backup_write_failure_keeps_old_state(self):
        ws = Workspace(self, [task("t-1", due="2026-10-09")])
        ws.run()
        before = ws.state_p.read_text()
        with mock.patch.object(Path, "write_bytes", side_effect=PermissionError(13, "Permission denied")):
            with self.assertRaises(ps.WriteFailed):
                ps.save_state(ws.state_p, {"k": {}})
        self.assertEqual(ws.state_p.read_text(), before)

    def test_mkdir_failure_is_write_failed(self):
        ws = Workspace(self, [])
        with mock.patch.object(Path, "mkdir", side_effect=PermissionError(13, "Permission denied")):
            with self.assertRaises(ps.WriteFailed):
                ps.save_state(ws.dir / "new" / "p.json", {})

    def test_non_oserror_during_dump_still_removes_tmp(self):
        ws = Workspace(self, [])
        ws.state_p.parent.mkdir(parents=True)
        with self.assertRaises(TypeError):
            ps.save_state(ws.state_p, {"k": object()})
        self.assertEqual(list(ws.state_p.parent.glob("*.tmp")), [])

    def test_fdopen_failure_closes_fd_and_removes_tmp(self):
        ws = Workspace(self, [])
        ws.state_p.parent.mkdir(parents=True)
        with mock.patch.object(ps.os, "fdopen", side_effect=OSError(24, "Too many open files")), \
                mock.patch.object(ps.os, "close", wraps=ps.os.close) as closer:
            with self.assertRaises(ps.WriteFailed):
                ps.save_state(ws.state_p, {})
        closer.assert_called_once()
        self.assertEqual(list(ws.state_p.parent.glob("*.tmp")), [])


class MalformedInputTest(unittest.TestCase):
    T_OK = {"id": "t-1", "title": "x", "status": "open", "updated": "2026-10-01"}
    ISSUE_OK = {"key": "EX-1", "status_category": "new", "updated": "2026-10-01", "links": []}

    def _exit_code(self, tasks=None, jira=None, meetings=None, extra=()):
        ws = Workspace(self, None)
        if tasks is not None:
            ws.tasks_p.write_text(json.dumps(tasks), encoding="utf-8")
        if jira is not None:
            (ws.jira_d / "ex-proj").mkdir(parents=True)
            (ws.jira_d / "ex-proj" / "2026-10-07.json").write_text(json.dumps(jira), encoding="utf-8")
        if meetings is not None:
            ws.meet_p.write_text(json.dumps(meetings), encoding="utf-8")
        ws.state_p.parent.mkdir(parents=True)
        ws.state_p.write_text('{"k": {}}')
        code = quiet_main(["--tasks", str(ws.tasks_p), "--jira-dir", str(ws.jira_d), "--meetings", str(ws.meet_p),
                           "--state", str(ws.state_p), "--audit-dir", str(ws.dir / "audit"),
                           "--today", "2026-10-07", *extra])
        self.assertEqual(ws.state_p.read_text(), '{"k": {}}')
        return code

    def test_each_malformed_shape_exits_2_and_keeps_state(self):
        ok_jira = {"fetched_at": "2026-10-07T08:00:00+09:00", "issues": [self.ISSUE_OK]}
        cases = {
            "tasks top-level list": dict(tasks=[]),
            "tasks missing status": dict(tasks={"tasks": [{"id": "t-1", "title": "x", "updated": "2026-10-01"}]}),
            "tasks updated null": dict(tasks={"tasks": [{**self.T_OK, "updated": None}]}),
            "tasks bad due": dict(tasks={"tasks": [{**self.T_OK, "due": "soon"}]}),
            "tasks no title": dict(tasks={"tasks": [{k: v for k, v in self.T_OK.items() if k != "title"}]}),
            "waiting without waiting_on": dict(tasks={"tasks": [{**self.T_OK, "status": "waiting", "next_check": "2026-10-06"}]}),
            "jira link issue_key not str": dict(tasks={"tasks": []}, jira={**ok_jira, "issues": [{**self.ISSUE_OK,
                "links": [{"link_type": "blocks", "direction": "outward", "issue_key": 5}]}]}),
            "tasks entry not object": dict(tasks={"tasks": ["x"]}),
            "jira top-level list": dict(tasks={"tasks": []}, jira=[]),
            "jira no fetched_at": dict(tasks={"tasks": []}, jira={"issues": [self.ISSUE_OK]}),
            "jira issue updated null": dict(tasks={"tasks": []}, jira={**ok_jira, "issues": [{**self.ISSUE_OK, "updated": None}]}),
            "meetings top-level list": dict(tasks={"tasks": []}, meetings=[]),
            "meeting start null": dict(tasks={"tasks": []}, meetings={"meetings": [{"id": "m-1", "title": "x", "start": None}]}),
            "bad --today": dict(tasks={"tasks": []}, extra=["--today", "xx"]),
        }
        for name, kw in cases.items():
            with self.subTest(name):
                self.assertEqual(self._exit_code(**kw), ps.EXIT_BROKEN)

    def test_state_with_non_dict_value_exits_2_and_is_not_overwritten(self):
        for text in ('{"due:t-1": 3}', '[]'):
            with self.subTest(text=text):
                ws = Workspace(self, [task("t-1", due="2026-10-09")])
                ws.state_p.parent.mkdir(parents=True)
                ws.state_p.write_text(text)
                code = quiet_main(["--tasks", str(ws.tasks_p), "--jira-dir", str(ws.jira_d), "--meetings", str(ws.meet_p),
                                   "--state", str(ws.state_p), "--audit-dir", str(ws.dir / "a"), "--today", "2026-10-07"])
                self.assertEqual(code, ps.EXIT_BROKEN)
                self.assertEqual(ws.state_p.read_text(), text)

    def test_snooze_with_bad_date_exits_2_and_keeps_state(self):
        ws = Workspace(self, [task("t-1", due="2026-10-09")])
        ws.run()
        before = ws.state_p.read_text()
        code = quiet_main(["--state", str(ws.state_p), "--audit-dir", str(ws.dir / "a"), "--today", "2026-10-07",
                           "--snooze", "due:t-1", "10/9"])
        self.assertEqual(code, ps.EXIT_BROKEN)
        self.assertEqual(ws.state_p.read_text(), before)
        self.assertFalse((ws.dir / "a").exists())

    def test_missing_tasks_file_is_noted_not_silent(self):
        ws = Workspace(self, None, issues=[], meetings=[])
        shown, _, decisions, notes = ws.run()
        self.assertTrue(any("タスク一覧: 入力なし" in n for n in notes))
        self.assertIn("タスク一覧: 入力なし", ps.render(shown, 0, decisions, TODAY, notes))


class DefaultPathTest(unittest.TestCase):
    def test_defaults_are_absolute_under_repo_root(self):
        args = ps.build_parser().parse_args([])
        for value in (args.tasks, args.jira_dir, args.meetings, args.state, args.audit_dir):
            self.assertTrue(value.startswith(str(ROOT / "data")), value)

    def test_runs_from_another_cwd_without_touching_it(self):
        import subprocess
        with tempfile.TemporaryDirectory() as tmp:
            out = subprocess.run([sys.executable, str(ROOT / "scripts" / "proactive_scan.py"),
                                  "--state", f"{tmp}/s.json", "--audit-dir", f"{tmp}/a",
                                  "--tasks", str(EXAMPLES / "tasks.sample.json"), "--today", "2026-10-08"],
                                 cwd=tmp, capture_output=True, text=True)
            self.assertEqual(out.returncode, ps.EXIT_NOTIFY, out.stderr)
            self.assertEqual(sorted(p.name for p in Path(tmp).iterdir()), ["s.json"])


class ExpectedOutputTest(unittest.TestCase):
    def test_sample_output_matches_expected_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            argv = ["--tasks", str(EXAMPLES / "tasks.sample.json"),
                    "--jira-dir", str(ROOT / "tests" / "fixtures" / "sample-week" / "jira-cache"),
                    "--meetings", str(EXAMPLES / "meetings.sample.json"), "--state", f"{tmp}/s.json",
                    "--audit-dir", f"{tmp}/a", "--today", "2026-10-08"]
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                ps.main(argv)
        self.assertEqual(buf.getvalue(), (EXAMPLES / "expected-output.md").read_text(encoding="utf-8"))

def now_tasks(n, **kw):
    return [task(f"t-{i}", priority="now", **kw) for i in range(1, n + 1)]


class NowCapTest(unittest.TestCase):  # emh-073 / Q-020: priority: now は 3 件まで。超えたら 1 回だけ聞く
    def test_three_now_tasks_produce_no_finding(self):
        self.assertEqual(ps.detect_now_cap(now_tasks(3)), [])

    def test_four_now_tasks_produce_one_decision_finding(self):
        found = ps.detect_now_cap(now_tasks(4))
        self.assertEqual([(f["key"], f["level"], f["decision"]) for f in found], [("now_cap:now", "中", True)])
        self.assertIn("4 件", found[0]["fact"])
        self.assertIn("soon", found[0]["ask"])

    def test_only_open_and_doing_now_tasks_are_counted(self):
        tasks = now_tasks(3) + [task("t-9", priority="now", status="done"), task("t-8", priority="now", status="waiting",
                                waiting_on="member-a", next_check="2026-10-09"), task("t-7", priority="soon")]
        self.assertEqual(ps.detect_now_cap(tasks), [])

    def test_shown_once_then_silent_on_following_days(self):
        ws = Workspace(self, now_tasks(4))
        shown, _, decisions, _ = ws.run(date(2026, 10, 7))
        self.assertEqual(decisions, {"now_cap:now"})
        self.assertIn("下げ", ps.render(shown, 0, decisions, TODAY))
        for day in (8, 9, 12, 13):
            shown, _, decisions, _ = ws.run(date(2026, 10, day))
            self.assertEqual((shown, decisions), ([], set()))

    def test_same_day_rerun_shows_the_same_request(self):
        ws = Workspace(self, now_tasks(4))
        first = ps.render(*ws.run()[:3], TODAY)
        self.assertEqual(first, ps.render(*ws.run()[:3], TODAY))

    def test_asks_again_after_count_dropped_to_three_and_rose_again(self):
        ws = Workspace(self, now_tasks(4))
        ws.run(date(2026, 10, 7))
        ws.tasks_p.write_text(json.dumps({"tasks": now_tasks(3)}), encoding="utf-8")
        ws.run(date(2026, 10, 8))
        ws.tasks_p.write_text(json.dumps({"tasks": now_tasks(5)}), encoding="utf-8")
        _, _, decisions, _ = ws.run(date(2026, 10, 9))
        self.assertEqual(decisions, {"now_cap:now"})

    def test_does_not_modify_tasks_file(self):
        ws = Workspace(self, now_tasks(5))
        before = ws.tasks_p.read_bytes()
        ws.run()
        self.assertEqual(ws.tasks_p.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
