import copy
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import one_on_one_followup as ooo  # noqa: E402

FIX = ROOT / "tests" / "fixtures" / "one-on-one"
REF = "1on1-member-a-2026-09-26.md"
SINCE, TODAY = date(2026, 9, 26), date(2026, 10, 10)
BANNED_WORDS = ("遅れ", "怠", "サボ", "優秀", "問題あり", "停滞している", "評価")


def _tasks():
    return ooo.load_tasks(FIX / "tasks.sample.json", FIX / "archive")[0]


def _ids(rows):
    return [t["id"] for t in rows]


class FollowupTest(unittest.TestCase):
    def setUp(self):
        self.f = ooo.build_followup(_tasks(), SINCE, TODAY, ref=REF, member="member-a")

    def test_matches_by_source_ref_only_for_that_memo(self):
        self.assertNotIn("t-0305", _ids(self.f["active"]))

    def test_buckets_by_status(self):
        self.assertEqual(_ids(self.f["active"]), ["t-0302"])
        self.assertEqual(_ids(self.f["waiting"]), ["t-0303"])
        self.assertEqual(_ids(self.f["dropped"]), ["t-0304"])

    def test_done_since_previous_includes_archived_task(self):
        self.assertEqual(sorted(_ids(self.f["done"])), ["t-0290", "t-0301"])

    def test_done_before_previous_is_excluded_and_counted(self):
        self.assertNotIn("t-0306", _ids(self.f["done"]))
        self.assertEqual(self.f["done_before"], 1)

    def test_member_only_matches_waiting_on(self):
        f = ooo.build_followup(_tasks(), SINCE, TODAY, member="member-a")
        self.assertEqual(_ids(f["waiting"]), ["t-0303"])
        self.assertEqual(f["matched"], 1)

    def test_tasks_json_wins_over_archive_for_same_id(self):
        with tempfile.TemporaryDirectory() as d:
            arch = Path(d) / "archive"
            arch.mkdir()
            dup = json.loads((FIX / "tasks.sample.json").read_text(encoding="utf-8"))["tasks"][0]
            (arch / "2026-09.json").write_text(json.dumps({"tasks": [{**dup, "status": "dropped"}]}), encoding="utf-8")
            tasks, _, _ = ooo.load_tasks(FIX / "tasks.sample.json", arch)
        self.assertEqual([t["status"] for t in tasks if t["id"] == "t-0301"], ["done"])

    def test_does_not_mutate_input(self):
        tasks = _tasks()
        before = copy.deepcopy(tasks)
        ooo.build_followup(tasks, SINCE, TODAY, ref=REF)
        self.assertEqual(tasks, before)


class RenderTest(unittest.TestCase):
    def test_sample_output_has_no_banned_words_and_stays_short(self):
        out = ooo.render(ooo.build_followup(_tasks(), SINCE, TODAY, ref=REF, member="member-a"), True, 1)
        self.assertFalse([w for w in BANNED_WORDS if w in out])
        self.assertLess(len(out.split("## 詳細")[0]), 600)

    def test_no_match_says_record_not_found_not_all_done(self):
        out = ooo.render(ooo.build_followup(_tasks(), SINCE, TODAY, ref="none.md"), True, 0)
        self.assertIn("記録が見つかりません", out)
        self.assertNotIn("対応不要", out)
        self.assertNotIn("完了", out.replace("「全部完了」という意味ではありません", ""))

    def test_missing_tasks_file_is_distinct_from_no_match(self):
        out = ooo.render(ooo.build_followup([], SINCE, TODAY, ref=REF), False, 0)
        self.assertIn("tasks.json が見つかりません", out)

    def test_all_done_shows_no_action_needed(self):
        tasks = [t for t in _tasks() if t["id"] == "t-0301"]
        out = ooo.render(ooo.build_followup(tasks, SINCE, TODAY, ref=REF), True, 0)
        self.assertIn("🟢 順調", out)
        self.assertIn("対応不要", out)

    def test_more_than_five_rows_are_folded(self):
        base = _tasks()[1]
        tasks = [{**base, "id": f"t-09{i:02d}"} for i in range(7)]
        out = ooo.render(ooo.build_followup(tasks, SINCE, TODAY, ref=REF), True, 0)
        self.assertIn("ほか 2 件", out)


class CliTest(unittest.TestCase):
    def _run(self, *args):
        buf = io.StringIO()
        with redirect_stdout(buf):
            ooo.main(["--tasks", str(FIX / "tasks.sample.json"), "--today", "2026-10-10", *args])
        return buf.getvalue()

    def test_requires_ref_or_member(self):
        with self.assertRaises(SystemExit) as cm:
            self._run("--since", "2026-09-26")
        self.assertIn("--ref", str(cm.exception))

    def test_invalid_since_reports_location(self):
        with self.assertRaises(SystemExit) as cm:
            self._run("--since", "9/26", "--ref", REF)
        self.assertIn("--since", str(cm.exception))

    def test_invalid_json_exits_without_writing(self):
        with tempfile.TemporaryDirectory() as d:
            bad = Path(d) / "tasks.json"
            bad.write_text("{oops", encoding="utf-8")
            with self.assertRaises(SystemExit) as cm:
                ooo.main(["--tasks", str(bad), "--since", "2026-09-26", "--ref", REF])
            self.assertIn("壊れています", str(cm.exception))
            self.assertEqual(bad.read_text(encoding="utf-8"), "{oops")

    def test_missing_file_runs_and_says_not_found(self):
        with tempfile.TemporaryDirectory() as d:
            buf = io.StringIO()
            with redirect_stdout(buf):
                ooo.main(["--tasks", str(Path(d) / "tasks.json"), "--since", "2026-09-26", "--ref", REF])
        self.assertIn("tasks.json が見つかりません", buf.getvalue())

    def test_cli_output_reads_archive_next_to_tasks(self):
        self.assertIn("t-0290", self._run("--since", "2026-09-26", "--ref", REF))


if __name__ == "__main__":
    unittest.main()
