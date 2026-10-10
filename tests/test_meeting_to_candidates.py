import json
import sys
import tempfile
import unittest
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

    def test_invalid_input_writes_nothing(self):
        bad = [structured([action(to_em="yes")]), structured([action(kind="signal")]),
               {**structured([action()]), "skipped": "hr"}, {**structured([action()]), "schema_version": 2}]
        for data in bad:
            with self.assertRaises(sc.IngestError):
                self.run_ingest(data)
        self.assertFalse(self.tasks.exists() or self.out.exists())

    def test_no_real_names_in_examples(self):
        for path in EXAMPLES.glob("*.json"):
            self.assertNotRegex(path.read_text(encoding="utf-8"), r"member-[a-z]")


if __name__ == "__main__":
    unittest.main()
