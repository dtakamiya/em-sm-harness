import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import meeting_to_candidates as mc  # noqa: E402
import slack_to_candidates as sc  # noqa: E402

EXAMPLES = ROOT / "skills" / "meeting-to-candidates" / "examples"
EXPECTED = json.loads((ROOT / "tests" / "fixtures" / "meeting-notes" / "expected.json").read_text(encoding="utf-8"))


def action(item_id="m-01", **overrides):
    base = {"id": item_id, "kind": "action_item", "owner": "em", "to_em": True, "due_raw": None,
            "observation": "em が資料を確認する、とメモにある", "confidence": "high"}
    return {**base, **overrides}


def structured(items, excluded=(), file="2026-10-09-ex-sync.md"):
    return {"schema_version": 1, "source": {"file": file, "meeting_alias": "ex-sync", "held_on": "2026-10-09"},
            "skipped": None, "items": items, "excluded": list(excluded)}


class MeetingToCandidatesTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        self.tasks, self.out = self.dir / "tasks", self.dir / "out"

    def write(self, data):
        path = self.dir / "in.json"
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return path

    def run_ingest(self, data, dry_run=False):
        return mc.ingest(self.write(data), self.tasks, self.out, dry_run)

    def test_examples_produce_the_expected_candidates(self):
        for f in EXPECTED["files"]:
            path = EXAMPLES / (f["source"][:-3] + ".json")
            fresh, _, _, _ = mc.ingest(path, self.dir / f["source"], self.dir / "o", True)
            got = [(c["source_ref"], c["suggested_due"]) for c in fresh]
            want = [(c["source_ref"], c["suggested_due"]) for c in f["candidates"]]
            self.assertEqual(got, want, f["source"])

    def test_only_confident_em_actions_become_candidates(self):
        items = [action("m-01"), action("m-02", owner="m_b2b2b2", to_em=False),
                 action("m-03", confidence="low"), action("m-04", kind="decision", decided_by=[])]
        fresh, counts, _, _ = self.run_ingest(structured(items))
        self.assertEqual([c["source_ref"] for c in fresh], ["2026-10-09-ex-sync.md:m-01"])
        self.assertEqual(counts, {"added": 1, "duplicate": 0, "not_eligible": 3})
        self.assertEqual(fresh[0]["source"], "meeting")

    def test_vague_due_is_null_and_iso_due_is_kept(self):
        fresh, _, _, _ = self.run_ingest(structured([action("m-01", due_raw="来週水曜まで"),
                                                     action("m-02", due_raw="2026-10-12")]), dry_run=True)
        self.assertEqual([c["suggested_due"] for c in fresh], [None, "2026-10-12"])

    def test_minutes_keep_open_questions_unowned_actions_and_excluded_lines(self):
        items = [action("m-01", owner=None, to_em=False, confidence="low", observation="ログを確認する、とメモにある"),
                 {"id": "m-02", "kind": "open_question", "observation": "リスク確認が必要、とメモにある",
                  "confidence": "medium"}]
        _, _, minutes, _ = self.run_ingest(structured(items, [{"line": 3, "reason": "日程のみ"}]), dry_run=True)
        for text in ("【下書き・未送信】", "ログを確認する", "担当が読み取れない", "リスク確認が必要", "3 行目: 日程のみ", "⟦EM が決める⟧"):
            self.assertIn(text, minutes)

    def test_dry_run_writes_nothing(self):
        self.run_ingest(structured([action()]), dry_run=True)
        self.assertFalse(self.tasks.exists() or self.out.exists())

    def test_write_creates_draft_and_candidates_then_skips_duplicates(self):
        data = structured([action()])
        self.run_ingest(data)
        self.assertTrue((self.out / "2026-10-09-ex-sync-minutes.md").exists())
        cands = json.loads((self.tasks / "candidates.json").read_text(encoding="utf-8"))["candidates"]
        self.assertEqual([c["id"] for c in cands], ["c-0001"])
        _, counts, _, _ = self.run_ingest(data)
        self.assertEqual(counts["duplicate"], 1)
        self.assertEqual(len(json.loads((self.tasks / "candidates.json").read_text(encoding="utf-8"))["candidates"]), 1)

    def test_existing_candidates_are_backed_up_under_a_separate_name(self):
        self.tasks.mkdir()
        (self.tasks / "candidates.json").write_text('{"version": 1, "candidates": []}\n', encoding="utf-8")
        self.run_ingest(structured([action()]))
        self.assertTrue((self.tasks / "candidates.json.pre-meeting.bak").exists())
        self.assertFalse((self.tasks / "candidates.json.pre-slack.bak").exists())

    def test_existing_minutes_are_backed_up_before_overwrite(self):
        self.out.mkdir()
        draft = self.out / "2026-10-09-ex-sync-minutes.md"
        draft.write_text("EM が手で直した版\n", encoding="utf-8")
        self.run_ingest(structured([action()]))
        self.assertEqual((self.out / (draft.name + ".bak")).read_text(encoding="utf-8"), "EM が手で直した版\n")
        self.assertIn("【下書き・未送信】", draft.read_text(encoding="utf-8"))

    def test_dry_run_summary_says_planned(self):
        _, counts, _, path = self.run_ingest(structured([action()]), dry_run=True)
        text = mc.summary(counts, True, path)
        self.assertIn("作成予定", text)
        self.assertIn("追加予定", text)
        self.assertNotIn("作成:", text)

    def test_invalid_input_writes_nothing(self):
        bad = [structured([action(to_em="yes")]), structured([action(kind="signal")]),
               {**structured([action()]), "skipped": "hr"}, {**structured([action()]), "schema_version": 2}]
        for data in bad:
            with self.assertRaises(sc.IngestError):
                self.run_ingest(data)
        self.assertFalse(self.tasks.exists() or self.out.exists())

    def audit_rows(self):
        files = sorted((self.dir / "audit").glob("*.jsonl"))
        return [json.loads(line) for f in files for line in f.read_text(encoding="utf-8").splitlines()]

    def run_audited(self, data, dry_run=False):
        now = datetime(2026, 10, 10, 9, 0, tzinfo=timezone.utc)
        return mc.ingest(self.write(data), self.tasks, self.out, dry_run, self.dir / "audit", now)

    def test_ingest_appends_one_count_only_audit_row(self):
        items = [action("m-01", observation="秘密の本文ABC"), action("m-02", kind="decision", decided_by=[]),
                 {"id": "m-03", "kind": "open_question", "observation": "未決の本文XYZ", "confidence": "medium"}]
        self.run_audited(structured(items, [{"line": 3, "reason": "日程のみ"}]))
        rows = self.audit_rows()
        self.assertEqual(rows, [{"ts": "2026-10-10T09:00:00+00:00", "event": "meeting_ingest",
                                 "file": "2026-10-09-ex-sync.md",
                                 "items": {"decision": 1, "action_item": 1, "open_question": 1},
                                 "excluded": 1, "skipped": None}])
        raw = "".join(f.read_text(encoding="utf-8") for f in (self.dir / "audit").glob("*.jsonl"))
        for leaked in ("秘密の本文", "未決の本文", "日程のみ"):
            self.assertNotIn(leaked, raw)
        self.assertEqual((self.dir / "audit" / "2026-10-10.jsonl").read_text(encoding="utf-8").count("\n"), 1)

    def test_audit_rows_append_and_duplicates_still_logged(self):
        data = structured([action()])
        self.run_audited(data)
        self.run_audited(data)
        self.assertEqual([r["event"] for r in self.audit_rows()], ["meeting_ingest", "meeting_ingest"])

    def test_dry_run_and_invalid_input_write_no_audit(self):
        self.run_audited(structured([action()]), dry_run=True)
        with self.assertRaises(sc.IngestError):
            self.run_audited(structured([action(kind="signal")]))
        self.assertFalse((self.dir / "audit").exists())

    def test_audit_is_off_when_no_audit_dir_given(self):
        self.run_ingest(structured([action()]))
        self.assertFalse((self.dir / "audit").exists())

    def test_audit_does_not_touch_approval_queue_state(self):
        self.run_audited(structured([action()]))
        self.assertEqual({p.name for p in self.dir.iterdir()} - {"in.json"}, {"tasks", "out", "audit"})

    def test_no_real_names_in_examples(self):
        for path in EXAMPLES.glob("*.json"):
            self.assertNotRegex(path.read_text(encoding="utf-8"), r"member-[a-z]")


if __name__ == "__main__":
    unittest.main()
