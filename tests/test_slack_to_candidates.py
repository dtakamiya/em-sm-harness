import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import slack_to_candidates as sc  # noqa: E402

EXAMPLES = ROOT / "skills" / "slack-to-candidates" / "examples"
FIRST = EXAMPLES / "2026-10-05-ex-team-01.json"
SECOND = EXAMPLES / "2026-10-07-ex-team-02.json"


def request(item_id="s-01", **overrides):
    base = {"id": item_id, "kind": "request", "to_em": True, "observation": "確認を求めている",
            "confidence": "high", "due_raw": None, "answered_in_thread": False}
    return {**base, **overrides}


def structured(items, file="2026-10-09-ex-team-03.md"):
    return {"schema_version": 1, "source": {"file": file}, "skipped": None, "items": items}


class SlackToCandidatesTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)

    def write_structured(self, data):
        path = self.dir / "in.json"
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return path

    def candidates(self):
        return json.loads((self.dir / "candidates.json").read_text(encoding="utf-8"))["candidates"]

    def test_only_confident_requests_to_em_become_candidates(self):
        items = [request("s-01"), request("s-02", confidence="low"), request("s-03", to_em=False),
                 {"id": "s-04", "kind": "risk", "observation": "懸念", "confidence": "high"}]
        fresh, counts = sc.build_candidates("f.md", items, set(), 1)
        self.assertEqual([c["source_ref"] for c in fresh], ["f.md:s-01"])
        self.assertEqual(counts["not_eligible"], 3)

    def test_candidate_carries_only_file_and_item_id_as_source_ref(self):
        fresh, _ = sc.build_candidates("f.md", [request()], set(), 7)
        self.assertEqual(fresh[0], {"id": "c-0007", "title": "確認を求めている", "source": "slack",
                                    "source_ref": "f.md:s-01", "suggested_due": None})

    def test_due_is_filled_only_for_an_iso_date(self):
        self.assertEqual(sc._due("2026-10-09"), "2026-10-09")
        self.assertIsNone(sc._due("金曜まで"))
        self.assertIsNone(sc._due(None))

    def test_long_observation_is_truncated_for_title(self):
        self.assertEqual(len(sc._title("あ" * 200)), sc.TITLE_MAX)

    def test_rerun_does_not_add_duplicates(self):
        path = self.write_structured(structured([request()]))
        sc.ingest(path, self.dir, False)
        _, counts = sc.ingest(path, self.dir, False)
        self.assertEqual((counts["added"], counts["duplicate"]), (0, 1))
        self.assertEqual(len(self.candidates()), 1)

    def test_rejected_and_adopted_sources_are_not_proposed_again(self):
        (self.dir / "rejected.json").write_text(json.dumps(
            {"rejected": [{"source": "slack", "source_ref": "f.md:s-01"}]}), encoding="utf-8")
        (self.dir / "tasks.json").write_text(json.dumps(
            {"tasks": [{"id": "t-0001", "source_ref": "f.md:s-02"}]}), encoding="utf-8")
        path = self.write_structured(structured([request("s-01"), request("s-02"), request("s-03")], "f.md"))
        fresh, _ = sc.ingest(path, self.dir, False)
        self.assertEqual([c["source_ref"] for c in fresh], ["f.md:s-03"])

    def test_new_ids_continue_after_the_largest_existing_number(self):
        (self.dir / "candidates.json").write_text(json.dumps(
            {"version": 1, "candidates": [{"id": "c-0004", "source_ref": "old:s-01"}]}), encoding="utf-8")
        sc.ingest(self.write_structured(structured([request()])), self.dir, False)
        self.assertEqual([c["id"] for c in self.candidates()], ["c-0004", "c-0005"])

    def test_dry_run_writes_nothing(self):
        fresh, _ = sc.ingest(self.write_structured(structured([request()])), self.dir, True)
        self.assertEqual(len(fresh), 1)
        self.assertFalse((self.dir / "candidates.json").exists())

    def test_previous_candidates_are_backed_up_before_overwrite(self):
        sc.ingest(self.write_structured(structured([request("s-01")])), self.dir, False)
        before = (self.dir / "candidates.json").read_bytes()
        sc.ingest(self.write_structured(structured([request("s-02")])), self.dir, False)
        self.assertEqual((self.dir / "candidates.json.pre-slack.bak").read_bytes(), before)

    def test_wrong_typed_input_is_rejected_without_traceback_or_writing(self):
        bad = [{"schema_version": 1, "source": {"file": "f.md"}, "skipped": None, "items": [1]},
               {"schema_version": 1, "source": "x", "skipped": None, "items": [request()]},
               structured([request(observation=None)]),
               structured([request(id=5)]),
               structured([request(confidence=["high"])])]
        for data in bad:
            with self.assertRaises(sc.IngestError):
                sc.ingest(self.write_structured(data), self.dir, False)
            self.assertFalse((self.dir / "candidates.json").exists())

    def test_non_dict_entries_in_existing_files_are_rejected_without_overwrite(self):
        original = json.dumps({"candidates": [1]})
        (self.dir / "candidates.json").write_text(original, encoding="utf-8")
        with self.assertRaises(sc.IngestError):
            sc.ingest(self.write_structured(structured([request()])), self.dir, False)
        self.assertEqual((self.dir / "candidates.json").read_text(encoding="utf-8"), original)

    def test_cli_wrong_typed_input_exits_nonzero_without_traceback(self):
        path = self.write_structured(structured([request(observation=None)]))
        self.assertEqual(sc.main([str(path), "--tasks-dir", str(self.dir)]), 1)

    def test_apply_reply_backup_is_not_overwritten(self):
        sc.ingest(self.write_structured(structured([request("s-01")])), self.dir, False)
        reply_bak = self.dir / "candidates.json.bak"
        reply_bak.write_bytes(b"reply-undo-state")
        sc.ingest(self.write_structured(structured([request("s-02")])), self.dir, False)
        self.assertEqual(reply_bak.read_bytes(), b"reply-undo-state")

    def test_invalid_input_stops_without_writing(self):
        bad = [structured([{"id": "s-01", "kind": "request"}]),
               structured([request(to_em="yes")]),
               {**structured([request()]), "skipped": "sensitive"},
               {**structured([request()]), "schema_version": 2}]
        for data in bad:
            with self.assertRaises(sc.IngestError):
                sc.ingest(self.write_structured(data), self.dir, False)
            self.assertFalse((self.dir / "candidates.json").exists())

    def test_broken_candidates_file_is_not_overwritten(self):
        (self.dir / "candidates.json").write_text("{broken", encoding="utf-8")
        with self.assertRaises(sc.IngestError):
            sc.ingest(self.write_structured(structured([request()])), self.dir, False)
        self.assertEqual((self.dir / "candidates.json").read_text(encoding="utf-8"), "{broken")

    def test_example_files_yield_the_expected_candidates(self):
        fresh1, _ = sc.ingest(FIRST, self.dir, False)
        fresh2, _ = sc.ingest(SECOND, self.dir, False)
        self.assertEqual([c["source_ref"] for c in fresh1], ["2026-10-05-ex-team-01.md:s-01"])
        self.assertEqual([c["source_ref"] for c in fresh2], ["2026-10-07-ex-team-02.md:s-04"])
        self.assertEqual(len(self.candidates()), 2)

    def test_cli_reports_failure_with_nonzero_exit(self):
        code = sc.main([str(self.dir / "missing.json"), "--tasks-dir", str(self.dir)])
        self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main()
