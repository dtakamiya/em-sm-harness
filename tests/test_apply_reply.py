import json
import sys
import tempfile
import unittest
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

    def test_done_clears_next_check_and_appends_history(self):
        self.run_replies("完了 t-0002")
        t = [x for x in self.read("tasks.json", "tasks") if x["id"] == "t-0002"][0]
        self.assertEqual((t["status"], t["next_check"]), ("done", None))
        self.assertEqual(t["history"][-1], {"at": "2026-10-05", "op": "done", "from": "waiting"})

    def test_defer_changes_due_and_warns_on_third(self):
        hist = [{"at": "2026-10-01", "op": "defer"}, {"at": "2026-10-02", "op": "defer"}]
        self.write("tasks.json", "tasks", [task("t-0001", history=hist)])
        out = self.run_replies("先送り t-0001 2026-10-16")
        self.assertIn("3回目", out[0])
        self.assertIn("drop か分割", out[0])
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
        self.assertTrue(all(r["before_sha256"] != r["after_sha256"] for r in rows))
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


if __name__ == "__main__":
    unittest.main()
