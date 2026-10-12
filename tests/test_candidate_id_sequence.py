import json
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import apply_reply as ar  # noqa: E402
import meeting_to_candidates as mc  # noqa: E402
import slack_to_candidates as sc  # noqa: E402

TODAY = date(2026, 10, 6)


def slack_input(file, item_id="s-01"):
    item = {"id": item_id, "kind": "request", "to_em": True, "observation": "確認を求めている",
            "confidence": "high", "due_raw": None}
    return {"schema_version": 1, "source": {"file": file}, "skipped": None, "items": [item]}


def meeting_input(file):
    item = {"id": "m-01", "kind": "action_item", "owner": "em", "to_em": True, "due_raw": None,
            "observation": "em が資料を確認する、とメモにある", "confidence": "high"}
    return {"schema_version": 1, "source": {"file": file, "meeting_alias": "ex-sync", "held_on": "2026-10-06"},
            "skipped": None, "items": [item], "excluded": []}


class CandidateIdSequenceTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        self.tasks = self.dir / "tasks"

    def write(self, name, data):
        path = self.dir / name
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return path

    def slack(self, file):
        fresh, _ = sc.ingest(self.write(file + ".json", slack_input(file)), self.tasks, dry_run=False)
        return [c["id"] for c in fresh]

    def meeting(self, file):
        fresh, *_ = mc.ingest(self.write(file + ".json", meeting_input(file)), self.tasks, self.dir / "out", dry_run=False)
        return [c["id"] for c in fresh]

    def test_id_is_not_reused_after_adopting_every_candidate(self):
        first = self.slack("a.md")
        ar.apply_replies(self.dir, [f"採用 {first[0]}"], TODAY)
        self.assertEqual(self.slack("b.md"), ["c-0002"])

    def test_id_is_not_reused_after_rejecting_every_candidate(self):
        first = self.slack("a.md")
        ar.apply_replies(self.dir, [f"却下 {first[0]}"], TODAY)
        self.assertEqual(self.meeting("c.md"), ["c-0002"])

    def test_slack_and_meeting_share_one_sequence(self):
        self.assertEqual(self.slack("a.md"), ["c-0001"])
        self.assertEqual(self.meeting("b.md"), ["c-0002"])

    def test_dry_run_does_not_consume_a_number(self):
        sc.ingest(self.write("a.json", slack_input("a.md")), self.tasks, dry_run=True)
        self.assertFalse((self.tasks / sc.SEQUENCE_NAME).exists())
        self.assertEqual(self.slack("a.md"), ["c-0001"])

    def test_broken_sequence_file_falls_back_to_existing_candidates(self):
        self.slack("a.md")
        (self.tasks / sc.SEQUENCE_NAME).write_text("{broken", encoding="utf-8")
        self.assertEqual(self.slack("b.md"), ["c-0002"])


if __name__ == "__main__":
    unittest.main()
