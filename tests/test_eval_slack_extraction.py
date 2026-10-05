import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import eval_slack_extraction as ev  # noqa: E402

EXAMPLES = ROOT / "skills" / "slack-to-candidates" / "examples"
EXPECTED_PATH = ROOT / "tests" / "fixtures" / "slack-extraction" / "expected.json"
SOURCE = "f.md"


def item(kind="request", idx=1, who="m_a1a1a1", **extra):
    return {"id": "s-01", "kind": kind, "evidence": {"msg_index": idx, "quote": "q"},
            "actors": {"from": who, "to": []}, **extra}


def expected_of(items, excluded=()):
    return {"files": [{"source": SOURCE, "items": items, "excluded": list(excluded)}]}


def run_eval(expected_items, actual_items, excluded=()):
    results, unevaluated = ev.evaluate(expected_of(expected_items, excluded), {SOURCE: actual_items})
    return results[0], unevaluated


class EvalSlackExtractionTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)

    def write(self, name, data):
        path = self.dir / name
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return path

    def cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = ev.main([str(a) for a in args])
        return code, out.getvalue(), err.getvalue()

    def test_identical_output_matches_everything(self):
        r, _ = run_eval([item(), item("blocker", 2)], [item(), item("blocker", 2)])
        self.assertEqual((len(r["matched"]), r["missed"], r["extra"]), (2, [], []))

    def test_missing_item_is_counted_as_missed(self):
        r, _ = run_eval([item(), item("blocker", 2)], [item()])
        self.assertEqual(r["missed"], [("blocker", 2, "m_a1a1a1")])

    def test_extra_item_is_counted_and_flagged_when_on_an_excluded_message(self):
        r, _ = run_eval([item()], [item(), item("request", 3), item("risk", 5)], [{"msg_index": 3, "reason": "x"}])
        self.assertEqual(len(r["extra"]), 2)
        self.assertEqual(r["extra_in_excluded"], [("request", 3, "m_a1a1a1")])

    def test_wrong_kind_on_same_message_is_missed_and_extra(self):
        r, _ = run_eval([item("decision")], [item("request")])
        self.assertEqual((len(r["missed"]), len(r["extra"])), (1, 1))

    def test_field_mismatch_is_reported_for_matched_items_only(self):
        r, _ = run_eval([item(confidence="high", to_em=True)], [item(confidence="medium", to_em=True)])
        self.assertEqual(r["field_mismatches"], [(("request", 1, "m_a1a1a1"), "confidence")])

    def test_wording_differences_are_not_counted(self):
        r, _ = run_eval([item(observation="a")], [item(observation="b")])
        self.assertEqual((r["missed"], r["extra"], r["field_mismatches"]), ([], [], []))

    def test_missing_actual_file_marks_all_expected_as_missed(self):
        results, unevaluated = ev.evaluate(expected_of([item()]), {"other.md": []})
        self.assertFalse(results[0]["found"])
        self.assertEqual(len(results[0]["missed"]), 1)
        self.assertEqual(unevaluated, ["other.md"])

    def test_totals_compute_recall_and_precision_and_handle_empty(self):
        r, _ = run_eval([item(), item("blocker", 2)], [item(), item("risk", 4)])
        t = ev.totals([r])
        self.assertEqual((t["recall"], t["precision"]), (0.5, 0.5))
        empty = ev.totals([run_eval([], [])[0]])
        self.assertEqual((empty["recall"], empty["precision"]), (None, None))

    def test_input_is_not_mutated(self):
        exp, act = [item()], [item("risk", 4)]
        snapshot = json.dumps([exp, act])
        run_eval(exp, act)
        self.assertEqual(json.dumps([exp, act]), snapshot)

    def test_shipped_examples_match_expected_fully(self):
        code, out, _ = self.cli(EXAMPLES, "--min-recall", "1", "--max-extra", "0")
        self.assertEqual(code, 0)
        self.assertIn("再現率 100%（6/6 件）", out)

    def test_min_recall_and_max_extra_gates_return_one(self):
        partial = self.write("a.json", {"source": {"file": "2026-10-05-ex-team-01.md"}, "items": []})
        self.assertEqual(self.cli(partial, "--min-recall", "0.5")[0], 1)
        self.assertEqual(self.cli(partial)[0], 0)
        extra = self.write("b.json", {"source": {"file": "2026-10-05-ex-team-01.md"}, "items": [item("risk", 9)]})
        self.assertEqual(self.cli(extra, "--max-extra", "0")[0], 1)

    def test_broken_inputs_stop_with_exit_two_and_reason(self):
        bad = self.dir / "bad.json"
        bad.write_text("{", encoding="utf-8")
        for args in ([bad], [self.dir / "none.json"], [self.write("noshape.json", {"items": []})],
                     [self.write("nokey.json", {"source": {"file": SOURCE}, "items": [{"id": "s-1"}]}),
                      "--expected", self.write("e.json", expected_of([item()]))]):
            code, _, err = self.cli(*args)
            self.assertEqual(code, 2, args)
            self.assertIn("評価を中止しました", err)

    def test_duplicate_source_files_are_rejected(self):
        data = {"source": {"file": SOURCE}, "items": []}
        self.write("1.json", data)
        self.write("2.json", data)
        with self.assertRaises(ev.EvalError):
            ev.load_actuals([self.dir])

    def test_default_expected_path_exists(self):
        self.assertTrue(EXPECTED_PATH.exists())


if __name__ == "__main__":
    unittest.main()
