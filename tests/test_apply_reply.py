import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from unittest import mock
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import apply_reply as ar  # noqa: E402
import morning_plan as mp  # noqa: E402

TODAY = date(2026, 10, 5)
NOW = datetime(2026, 10, 5, 9, 0, tzinfo=timezone.utc)


def task(tid, status="open", due="2026-10-09", history=()):
    return {"id": tid, "title": "架空タスク " + tid, "status": status, "priority": "soon", "due": due,
            "source": "manual", "source_ref": None, "waiting_on": "member-a" if status == "waiting" else None,
            "next_check": "2026-10-08" if status == "waiting" else None, "blocks": [], "tags": [],
            "notes": "", "created": "2026-10-01", "updated": "2026-10-01", "history": list(history)}


def cand(cid, ref="sample-1.md"):
    return {"id": cid, "title": "架空の候補 " + cid, "source": "slack", "source_ref": ref, "suggested_due": "2026-10-12"}


class ApplyReplyTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.data = Path(self._tmp.name)
        (self.data / "tasks").mkdir()
        self.write("tasks.json", "tasks", [task("t-0001"), task("t-0002", "waiting"), task("t-0003", "done", None)])
        self.write("candidates.json", "candidates", [cand("c-0001"), cand("c-0002", "sample-2.md"), cand("c-0003", "sample-3.md")])

    def write(self, name, key, items):
        (self.data / "tasks" / name).write_text(json.dumps({"version": 1, key: items}, ensure_ascii=False), encoding="utf-8")

    def read(self, name, key):
        return json.loads((self.data / "tasks" / name).read_text(encoding="utf-8"))[key]

    def run_replies(self, *lines, **kw):
        return ar.apply_replies(self.data, list(lines), TODAY, NOW, **kw)

    def audit_rows(self):
        f = self.data / "audit" / "2026-10-05.jsonl"
        return [json.loads(x) for x in f.read_text(encoding="utf-8").splitlines()]

    def test_adopt_creates_open_task_with_new_id_and_removes_candidate(self):
        out = self.run_replies("採用 c-0001")
        tasks = self.read("tasks.json", "tasks")
        self.assertEqual(tasks[-1]["id"], "t-0004")
        self.assertEqual((tasks[-1]["status"], tasks[-1]["due"], tasks[-1]["source_ref"]), ("open", "2026-10-12", "sample-1.md"))
        self.assertNotIn("c-0001", [c["id"] for c in self.read("candidates.json", "candidates")])
        self.assertTrue(out[0].startswith("+ t-0004"))

    def test_new_id_skips_ids_in_archive(self):
        (self.data / "tasks" / "archive").mkdir()
        (self.data / "tasks" / "archive" / "2026-09.json").write_text(json.dumps({"tasks": [task("t-0009", "done")]}))
        self.run_replies("採用 c-0001")
        self.assertEqual(self.read("tasks.json", "tasks")[-1]["id"], "t-0010")

    def test_reject_records_source_ref_and_drops_candidate(self):
        self.run_replies("却下 c-0002")
        self.assertEqual(self.read("rejected.json", "rejected")[0]["source_ref"], "sample-2.md")
        self.assertNotIn("c-0002", [c["id"] for c in self.read("candidates.json", "candidates")])

    def test_later_hides_candidate_from_morning_plan_until_date(self):
        self.run_replies("後で c-0003")
        cands = self.read("candidates.json", "candidates")
        self.assertEqual([c for c in cands if c["id"] == "c-0003"][0]["snooze_until"], "2026-10-06")
        self.assertNotIn("c-0003", [c["id"] for c in mp.build_plan([], cands, TODAY)["candidates"]])
        self.assertIn("c-0003", [c["id"] for c in mp.build_plan([], cands, date(2026, 10, 6))["candidates"]])

    def test_wait_sets_waiting_fields_default_check_is_3_business_days(self):
        out = self.run_replies("待ち t-0001 member-b")
        t = self.read("tasks.json", "tasks")[0]
        self.assertEqual((t["status"], t["waiting_on"], t["next_check"]), ("waiting", "member-b", "2026-10-08"))
        self.assertEqual(t["history"][-1], {"at": "2026-10-05", "op": "wait", "from": "open"})
        self.assertEqual(out, ["⏳ t-0001 member-b 待ち（10/8 に確認）"])

    def test_wait_default_check_skips_weekend(self):
        self.assertEqual(ar._add_business_days(date(2026, 10, 9), 3), date(2026, 10, 14))

    def test_wait_accepts_explicit_check_date_and_doing_task(self):
        self.write("tasks.json", "tasks", [task("t-0001", "doing")])
        self.run_replies("待ち t-0001 m_ab12cd 2026-10-20")
        self.assertEqual(self.read("tasks.json", "tasks")[0]["next_check"], "2026-10-20")

    def test_wait_rejects_bad_input_without_writing(self):
        before = (self.data / "tasks" / "tasks.json").read_bytes()
        for line in ("待ち t-0001 田中", "待ち t-0001 member-a 10/9", "待ち t-0001 member-a 2026-10-04",
                     "待ち t-0003 member-a", "待ち t-0002 member-a", "待ち t-0001", "待ち t-0001 member-a 2026-10-09 x"):
            with self.subTest(line=line), self.assertRaises(ar.ReplyError):
                self.run_replies(line)
        self.assertEqual((self.data / "tasks" / "tasks.json").read_bytes(), before)

    def test_wait_appears_in_morning_nudges_and_evening_new_waiting_and_audit_has_no_handle(self):
        import evening_wrapup as ew
        self.run_replies("待ち t-0001 member-b 2026-10-05")
        tasks = self.read("tasks.json", "tasks")
        self.assertIn("t-0001", [t["id"] for t in mp.build_plan(tasks, [], TODAY)["nudges"]])
        self.assertIn("t-0001", [t["id"] for t in ew.build_wrapup(tasks, TODAY)["new_waiting"]])
        self.assertNotIn("member-b", (self.data / "audit" / "2026-10-05.jsonl").read_text(encoding="utf-8"))

    def test_wait_undo_restores_original_bytes(self):
        before = (self.data / "tasks" / "tasks.json").read_bytes()
        self.run_replies("待ち t-0001 member-b")
        ar.undo(self.data, now=NOW)
        self.assertEqual((self.data / "tasks" / "tasks.json").read_bytes(), before)

    def test_done_clears_next_check_and_appends_history(self):
        self.run_replies("完了 t-0002")
        t = [x for x in self.read("tasks.json", "tasks") if x["id"] == "t-0002"][0]
        self.assertEqual((t["status"], t["next_check"]), ("done", None))
        self.assertEqual(t["history"][-1], {"at": "2026-10-05", "op": "done", "from": "waiting"})

    def test_drop_marks_dropped_with_reason_and_clears_next_check(self):
        out = self.run_replies("中止 t-0002 不要になった")
        t = [x for x in self.read("tasks.json", "tasks") if x["id"] == "t-0002"][0]
        self.assertEqual((t["status"], t["next_check"]), ("dropped", None))
        self.assertEqual(t["history"][-1], {"at": "2026-10-05", "op": "drop", "from": "waiting", "reason": "不要になった"})
        self.assertEqual(out[0], "✗ t-0002 中止")

    def test_drop_without_reason_is_allowed(self):
        self.run_replies("中止 t-0001")
        t = self.read("tasks.json", "tasks")[0]
        self.assertEqual((t["status"], t["history"][-1]["op"]), ("dropped", "drop"))
        self.assertNotIn("reason", t["history"][-1])

    def test_split_drops_parent_and_creates_open_children_inheriting_due(self):
        out = self.run_replies("分割 t-0001 調査 実装")
        tasks = self.read("tasks.json", "tasks")
        parent, kids = tasks[0], tasks[-2:]
        self.assertEqual((parent["status"], parent["history"][-1]["op"]), ("dropped", "split"))
        self.assertEqual([(k["id"], k["title"], k["status"], k["due"]) for k in kids],
                         [("t-0004", "調査", "open", "2026-10-09"), ("t-0005", "実装", "open", "2026-10-09")])
        self.assertIn("分割元 t-0001", kids[0]["notes"])
        self.assertEqual(out[0], "✂ t-0001 を分割 → t-0004 調査 / t-0005 実装")

    def test_split_needs_at_least_two_titles(self):
        before = (self.data / "tasks" / "tasks.json").read_bytes()
        with self.assertRaises(ar.ReplyError):
            self.run_replies("分割 t-0001 調査")
        self.assertEqual((self.data / "tasks" / "tasks.json").read_bytes(), before)

    def test_drop_and_split_reject_closed_tasks(self):
        for line in ("中止 t-0003", "分割 t-0003 甲 乙"):
            with self.assertRaises(ar.ReplyError, msg=line):
                self.run_replies(line)

    def test_split_audit_lists_all_new_ids_and_undo_restores(self):
        before = (self.data / "tasks" / "tasks.json").read_bytes()
        self.run_replies("分割 t-0001 調査 実装")
        row = self.audit_rows()[-1]
        self.assertEqual((row["op"], row["new_task_ids"]), ("split", ["t-0004", "t-0005"]))
        ar.undo(self.data, now=NOW)
        self.assertEqual((self.data / "tasks" / "tasks.json").read_bytes(), before)

    def test_decision_request_is_cleared_after_drop(self):
        hist = [{"at": "2026-10-01", "op": "defer"}] * 3
        self.write("tasks.json", "tasks", [task("t-0001", history=hist)])
        self.run_replies("中止 t-0001")
        self.assertEqual(self.read("tasks.json", "tasks")[0]["status"], "dropped")

    def test_defer_changes_due_and_warns_on_third(self):
        hist = [{"at": "2026-10-01", "op": "defer"}, {"at": "2026-10-02", "op": "defer"}]
        self.write("tasks.json", "tasks", [task("t-0001", history=hist)])
        out = self.run_replies("先送り t-0001 2026-10-16")
        self.assertIn("3回目", out[0])
        self.assertIn("中止 t-0001", out[0])
        self.assertIn("分割 t-0001", out[0])
        self.assertEqual(self.read("tasks.json", "tasks")[0]["due"], "2026-10-16")

    def test_unknown_id_rejects_whole_batch_without_writing(self):
        before = (self.data / "tasks" / "tasks.json").read_bytes()
        with self.assertRaises(ar.ReplyError):
            self.run_replies("完了 t-0001", "完了 t-9999")
        self.assertEqual((self.data / "tasks" / "tasks.json").read_bytes(), before)
        self.assertFalse((self.data / "audit").exists())

    def test_rejects_closed_task_ambiguous_phrase_and_bad_date(self):
        for line in ("完了 t-0003", "いい感じに片付けて", "採用", "先送り t-0001", "先送り t-0001 来週"):
            with self.subTest(line=line), self.assertRaises(ar.ReplyError):
                self.run_replies(line)

    def test_broken_json_is_not_overwritten(self):
        (self.data / "tasks" / "tasks.json").write_text("{broken")
        with self.assertRaises(ar.ReplyError):
            self.run_replies("完了 t-0001")
        self.assertEqual((self.data / "tasks" / "tasks.json").read_text(), "{broken")

    def test_dry_run_writes_nothing(self):
        before = (self.data / "tasks" / "tasks.json").read_bytes()
        out = self.run_replies("完了 t-0001", dry_run=True)
        self.assertEqual(out, ["✓ t-0001 完了"])
        self.assertEqual((self.data / "tasks" / "tasks.json").read_bytes(), before)

    def test_audit_has_ids_and_hashes_but_no_task_text(self):
        self.run_replies("採用 c-0001", "完了 t-0001")
        rows = self.audit_rows()
        self.assertEqual([r["op"] for r in rows], ["adopt", "done"])
        self.assertTrue(all(c["before_sha256"] != c["after_sha256"] for r in rows for c in r["changes"]))
        raw = (self.data / "audit" / "2026-10-05.jsonl").read_text(encoding="utf-8")
        self.assertNotIn("架空", raw)
        self.assertEqual({r["action"] for r in rows}, {"task.update"})

    def test_undo_restores_all_files_and_logs_revert(self):
        orig = {n: (self.data / "tasks" / n).read_bytes() for n in ("tasks.json", "candidates.json")}
        self.run_replies("採用 c-0001", "却下 c-0002")
        self.assertTrue((self.data / "tasks" / "rejected.json").exists())
        ar.undo(self.data, now=NOW)
        for n, content in orig.items():
            self.assertEqual((self.data / "tasks" / n).read_bytes(), content)
        self.assertFalse((self.data / "tasks" / "rejected.json").exists())
        self.assertEqual(self.audit_rows()[-1]["event"], "task_reverted")
        with self.assertRaises(ar.ReplyError):
            ar.undo(self.data, now=NOW)

    def test_undo_refuses_after_manual_edit_unless_forced(self):
        self.run_replies("完了 t-0001")
        self.write("tasks.json", "tasks", [task("t-0001", "doing")])
        with self.assertRaises(ar.ReplyError):
            ar.undo(self.data, now=NOW)
        ar.undo(self.data, force=True, now=NOW)
        self.assertEqual(self.read("tasks.json", "tasks")[0]["status"], "open")

    def test_input_state_is_not_mutated(self):
        tasks = [task("t-0001")]
        state = {"tasks": tasks, "candidates": [], "rejected": []}
        new_state, _ = ar.apply_one(state, "done", "t-0001", [], TODAY, self.data / "none")
        self.assertEqual(tasks[0]["status"], "open")
        self.assertEqual(new_state["tasks"][0]["status"], "done")

    def test_later_accepts_explicit_date(self):
        out = self.run_replies("後で c-0003 2026-10-20")
        self.assertIn("10/20", out[0])
        self.assertEqual([c for c in self.read("candidates.json", "candidates") if c["id"] == "c-0003"][0]["snooze_until"], "2026-10-20")

    def test_crash_midway_then_undo_restores_original(self):
        orig = {n: (self.data / "tasks" / n).read_bytes() for n in ("tasks.json", "candidates.json")}
        real = ar._atomic_write_bytes
        calls = []

        def flaky(path, content):
            if path.name in ar.TRACKED:  # .bak 退避は通し、本体の2つ目で落とす
                calls.append(path.name)
                if len(calls) == 2:
                    raise OSError("disk full")
            return real(path, content)

        with mock.patch.object(ar, "_atomic_write_bytes", flaky), self.assertRaises(OSError):
            self.run_replies("採用 c-0001", "却下 c-0002")
        ar.undo(self.data, now=NOW)
        for n, content in orig.items():
            self.assertEqual((self.data / "tasks" / n).read_bytes(), content)
        self.assertFalse((self.data / "tasks" / "rejected.json").exists())

    def test_undo_refuses_without_touching_when_bak_missing(self):
        self.run_replies("完了 t-0001")
        (self.data / "tasks" / "tasks.json.bak").unlink()
        snapshot = (self.data / "tasks" / "tasks.json").read_bytes()
        with self.assertRaises(ar.ReplyError):
            ar.undo(self.data, force=True, now=NOW)
        self.assertEqual((self.data / "tasks" / "tasks.json").read_bytes(), snapshot)
        self.assertTrue((self.data / "tasks" / ar.UNDO_MANIFEST).exists())

    def test_undo_refuses_when_bak_does_not_match_pre_apply_hash(self):
        self.run_replies("完了 t-0001")
        (self.data / "tasks" / "tasks.json.bak").write_text("{}")
        with self.assertRaises(ar.ReplyError):
            ar.undo(self.data, now=NOW)

    def test_stale_bak_from_failed_apply_cannot_fake_undo(self):
        self.run_replies("完了 t-0001")
        (self.data / "tasks" / ar.UNDO_MANIFEST).unlink()
        with self.assertRaises(ar.ReplyError):
            ar.undo(self.data, now=NOW)

    def test_unwritable_audit_blocks_update_before_any_write(self):
        before = (self.data / "tasks" / "tasks.json").read_bytes()
        (self.data / "audit").write_text("file, not dir")
        with self.assertRaises(ar.ReplyError):
            self.run_replies("完了 t-0001")
        self.assertEqual((self.data / "tasks" / "tasks.json").read_bytes(), before)
        self.assertFalse((self.data / "tasks" / "tasks.json.bak").exists())

    def test_cli_rejects_undo_with_replies_and_force_alone(self):
        for argv in (["--undo", "完了 t-0001"], ["--force", "完了 t-0001"]):
            with self.subTest(argv=argv), contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as cm:
                ar.main(["--data-dir", str(self.data), *argv])
            self.assertEqual(cm.exception.code, 2)
        self.assertEqual(self.read("tasks.json", "tasks")[0]["status"], "open")

    def test_audit_points_at_real_changes_and_new_task_id(self):
        self.run_replies("採用 c-0001", "却下 c-0002", "後で c-0003", "完了 t-0001")
        adopt, reject, later, done = self.audit_rows()
        self.assertEqual([c["file"] for c in adopt["changes"]], ["tasks.json", "candidates.json"])
        self.assertEqual(adopt["new_task_id"], "t-0004")
        self.assertEqual([c["file"] for c in reject["changes"]], ["candidates.json", "rejected.json"])
        self.assertEqual([c["file"] for c in later["changes"]], ["candidates.json"])
        self.assertEqual([c["file"] for c in done["changes"]], ["tasks.json"])
        self.assertNotIn("new_task_id", done)

    def test_cli_rejects_undo_with_dry_run_and_does_not_undo(self):
        self.run_replies("完了 t-0001")
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as cm:
            ar.main(["--data-dir", str(self.data), "--undo", "--dry-run"])
        self.assertEqual(cm.exception.code, 2)
        self.assertEqual(self.read("tasks.json", "tasks")[0]["status"], "done")

    def test_reject_output_says_resuggestion_blocked_when_source_ref_exists(self):
        self.assertIn("同じ出典は再提案されません", self.run_replies("却下 c-0002")[0])

    def test_reject_output_warns_when_source_ref_is_missing(self):
        self.write("candidates.json", "candidates", [cand("c-0009", None)])
        self.assertIn("再提案は止まりません", self.run_replies("却下 c-0009")[0])

    def test_invalid_schema_is_reported_not_traceback(self):
        bad = ('[]', '{}', '{"tasks": {}}', '{"tasks": [1]}', '{"tasks": [{"title": "idなし"}]}')
        for text in bad:
            with self.subTest(text=text):
                (self.data / "tasks" / "tasks.json").write_text(text)
                with self.assertRaises(ar.ReplyError):
                    self.run_replies("完了 t-0001")
                self.assertEqual((self.data / "tasks" / "tasks.json").read_text(), text)

    def test_invalid_manifest_is_reported(self):
        self.run_replies("完了 t-0001")
        (self.data / "tasks" / ar.UNDO_MANIFEST).write_text("[]")
        with self.assertRaises(ar.ReplyError):
            ar.undo(self.data, now=NOW)


if __name__ == "__main__":
    unittest.main()
