import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import trial_review as tr  # noqa: E402

TODAY = date(2026, 10, 20)
START = date(2026, 10, 6)


def row(day, event, hour="09:00:00", tz="+09:00", **kw):
    return {"ts": f"{day}T{hour}{tz}", "event": event, **kw}


def with_day(rows):
    return [{**r, "_day": tr._row_day(r)} for r in rows]


def item(aid, day="2026-10-07", bucket="bulk", stage="none"):
    return row(day, "queue_item", action_id=aid, slot="morning", bucket=bucket, kind="minutes", commit_stage=stage)


def reviewed(aid, result, day="2026-10-08"):
    return row(day, "em_reviewed", action_id=aid, result=result)


class StartDateTest(unittest.TestCase):
    def test_invalid_format_stops_with_error(self):
        with self.assertRaises(tr.TrialReviewError):
            tr.parse_start_date("2026/10/01", TODAY)

    def test_future_date_stops_with_error(self):
        with self.assertRaises(tr.TrialReviewError):
            tr.parse_start_date("2026-10-21", TODAY)

    def test_empty_means_provisional(self):
        self.assertIsNone(tr.parse_start_date("", TODAY))

    def test_reads_nested_key_from_config(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "local.yaml"
            path.write_text('jira:\n  start_date: "1999-01-01"\ntrial:\n  start_date: "2026-10-06"  # 試用開始\n', encoding="utf-8")
            self.assertEqual(tr.read_config_start_date(path), "2026-10-06")
            self.assertEqual(tr.read_config_start_date(Path(d) / "none.yaml"), "")


class TimezoneTest(unittest.TestCase):
    def test_utc_late_evening_is_next_day_in_jst(self):
        self.assertEqual(tr._row_day(row("2026-10-06", "x", "16:00:00", "+00:00")), date(2026, 10, 7))

    def test_naive_timestamp_is_treated_as_jst(self):
        self.assertEqual(tr._row_day(row("2026-10-06", "x", "23:30:00", "")), date(2026, 10, 6))


class BuildReviewTest(unittest.TestCase):
    def test_zero_audit_rows_and_no_start_date_is_undetermined(self):
        review = tr.build_review([], [], None, TODAY)
        self.assertTrue(review["undetermined"])
        self.assertEqual(review["metrics"]["M2"]["value"], "未計測")
        self.assertIn("開始日不明・未計測", tr.render(review, 0))

    def test_provisional_start_is_oldest_audit_day(self):
        rows = with_day([row("2026-10-08", "queue_rendered", individual=1, bulk=0, carried_over=0)])
        review = tr.build_review(rows, [], None, TODAY)
        self.assertEqual(review["start"], date(2026, 10, 8))
        self.assertTrue(review["provisional"])
        self.assertIn("仮の開始日", tr.render(review, 0))

    def test_rows_outside_window_are_ignored(self):
        rows = with_day([item("a-1", "2026-10-05"), item("a-2", "2026-10-20")])
        review = tr.build_review(rows, [], START, TODAY)
        self.assertEqual(review["metrics"]["M3"]["denominator"], 0)

    def test_in_progress_flag_before_day_14(self):
        review = tr.build_review([], [], START, date(2026, 10, 10))
        self.assertTrue(review["in_progress"])
        self.assertEqual(review["as_of"], date(2026, 10, 10))


class M2M4Test(unittest.TestCase):
    def _rows(self, results):
        rows = []
        for i, res in enumerate(results):
            rows.append(item(f"a-{i}", stage="A"))
            if res:
                rows.append(reviewed(f"a-{i}", res))
        return with_day(rows)

    def test_below_five_is_undecidable(self):
        m = tr.metric_m2(self._rows(["edited", "adopted_as_is", "edited"]))
        self.assertEqual(m["value"], "判定不能（分母 3）")

    def test_ratio_and_unmatched_excluded_from_denominator(self):
        m = tr.metric_m2(self._rows(["edited", "edited", "adopted_as_is", "adopted_as_is", "adopted_as_is", None, "rejected"]))
        self.assertEqual((m["denominator"], m["unmatched"]), (5, 2))
        self.assertIn("2/5（40%）", m["value"])
        self.assertIn("em_reviewed が無い", m["reason"])

    def test_m2_counts_only_bulk_bucket(self):
        rows = with_day([item("a-1", bucket="individual"), reviewed("a-1", "edited")])
        self.assertEqual(tr.metric_m2(rows)["denominator"], 0)

    def test_m4_counts_only_commit_stages_and_adoption(self):
        m = tr.metric_m4(self._rows(["adopted_as_is"] * 4 + ["edited"]))
        self.assertIn("検知 5 件", m["value"])
        self.assertIn("4/5（80%）", m["value"])
        none_stage = with_day([item("a-9", stage="none"), reviewed("a-9", "edited")])
        self.assertEqual(tr.metric_m4(none_stage)["denominator"], 0)

    def test_empty_queue_events_report_reason_not_zero_percent(self):
        m = tr.metric_m2([])
        self.assertIn("判定不能", m["value"])
        self.assertIn("未実装", m["reason"])


class M3Test(unittest.TestCase):
    def test_counts_carried_days_and_total(self):
        rows = with_day([row(f"2026-10-{d:02d}", "queue_rendered", individual=5, bulk=0, carried_over=c)
                         for d, c in ((7, 2), (8, 0), (9, 1), (10, 0), (11, 3))])
        m = tr.metric_m3(rows)
        self.assertIn("延べ 6 件", m["value"])
        self.assertIn("3/5（60%）", m["value"])


class M6Test(unittest.TestCase):
    AS_OF = date(2026, 10, 19)

    def task(self, tid, due, status="open", history=()):
        return {"id": tid, "status": status, "due": due, "history": list(history)}

    def test_flags_only_overdue_more_than_three_days_without_clearing_op(self):
        tasks = [self.task("t-1", "2026-10-15"),                                   # 4日超過 → 対象
                 self.task("t-2", "2026-10-16"),                                   # 3日ちょうど → 対象外
                 self.task("t-3", "2026-10-10", history=[{"at": "2026-10-12", "op": "defer"}]),
                 self.task("t-4", "2026-10-10", history=[{"at": "2026-10-09", "op": "defer"}]),  # 期限前の defer は効かない
                 self.task("t-5", "2026-10-01", status="done")]
        m = tr.metric_m6(tasks, self.AS_OF)
        self.assertIn("2 件（id: t-1, t-4）", m["value"])
        self.assertEqual(m["denominator"], 4)

    def test_missing_tasks_file_is_unmeasured(self):
        self.assertEqual(tr.metric_m6(None, self.AS_OF)["value"], "未計測")


class MainTest(unittest.TestCase):
    def run_main(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = tr.main(list(args))
        return code, out.getvalue(), err.getvalue()

    def test_invalid_start_date_exits_2_without_report(self):
        with tempfile.TemporaryDirectory() as d:
            code, out, err = self.run_main("--data-dir", d, "--start-date", "2026/10/01", "--today", "2026-10-20")
        self.assertEqual((code, out), (2, ""))
        self.assertIn("ISO 日付", err)

    def test_end_to_end_writes_nothing_and_skips_broken_lines(self):
        with tempfile.TemporaryDirectory() as d:
            audit = Path(d) / "audit"
            audit.mkdir()
            lines = [json.dumps(item("a-1", stage="A")), "{broken", json.dumps(reviewed("a-1", "edited"))]
            (audit / "2026-10-07.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
            before = sorted(p.name for p in Path(d).rglob("*"))
            code, out, _ = self.run_main("--data-dir", d, "--start-date", "2026-10-06", "--today", "2026-10-20",
                                         "--config", str(Path(d) / "none.yaml"))
            self.assertEqual(sorted(p.name for p in Path(d).rglob("*")), before)
        self.assertEqual(code, 0)
        self.assertIn("読めない監査行が 1 行", out)
        self.assertIn("開始日 2026-10-06 〜 2026-10-19（暦日 14 日・JST）", out)
        self.assertNotIn("仮の開始日", out)


if __name__ == "__main__":
    unittest.main()
