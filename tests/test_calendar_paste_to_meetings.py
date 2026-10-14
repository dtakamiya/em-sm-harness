import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import calendar_paste_to_meetings as cp  # noqa: E402
import proactive_scan  # noqa: E402

JP = """10/12 (月)
10:00-11:00 架空の定例A
終日 架空の祝祭

10/13 (火)
13:30 架空のレビュー
"""


class ConvertTest(unittest.TestCase):
    def test_japanese_slash_headers_with_times_and_all_day(self):
        meetings, unreadable = cp.convert(JP, 2026)
        self.assertEqual([m["start"] for m in meetings], ["2026-10-12", "2026-10-12", "2026-10-13"])
        self.assertEqual([m["title"] for m in meetings], ["架空の定例A", "架空の祝祭", "架空のレビュー"])
        self.assertEqual(unreadable, [])

    def test_ids_are_sequential_and_prep_task_id_is_null(self):
        meetings, _ = cp.convert(JP, 2026)
        self.assertEqual([m["id"] for m in meetings], ["m-0001", "m-0002", "m-0003"])
        self.assertTrue(all(m["prep_task_id"] is None for m in meetings))

    def test_kanji_header_with_year(self):
        meetings, _ = cp.convert("2027年1月5日(火)\n9:00 テスト会議\n", 2026)
        self.assertEqual(meetings[0]["start"], "2027-01-05")

    def test_iso_header(self):
        meetings, _ = cp.convert("2026-10-12\n10:00 Sync\n", 2000)
        self.assertEqual(meetings[0]["start"], "2026-10-12")

    def test_english_header_and_am_pm(self):
        meetings, unreadable = cp.convert("Monday, Oct 12\n10:00am - 11:00am Demo Sync\nAll day Holiday\n", 2026)
        self.assertEqual([(m["start"], m["title"]) for m in meetings],
                         [("2026-10-12", "Demo Sync"), ("2026-10-12", "Holiday")])
        self.assertEqual(unreadable, [])

    def test_unreadable_lines_are_reported_not_dropped_silently(self):
        text = "10:00 日付の前の会議\n10/12\n何かのメモ\n10:00 ok\n2/30\n"
        meetings, unreadable = cp.convert(text, 2026)
        self.assertEqual([m["title"] for m in meetings], ["ok"])
        self.assertEqual(unreadable, [(1, "10:00 日付の前の会議"), (3, "何かのメモ"), (5, "2/30")])

    def test_meetings_after_invalid_header_are_unreadable_not_attached_to_previous_date(self):
        text = "10/12\n9:00 A\n2/30\n10:00 B\n12.10.2026\n11:00 C\n10/13\n9:00 D\n"
        meetings, unreadable = cp.convert(text, 2026)
        self.assertEqual([(m["start"], m["title"]) for m in meetings], [("2026-10-12", "A"), ("2026-10-13", "D")])
        self.assertEqual([n for n, _ in unreadable], [3, 4, 5, 6])

    def test_pm_suffix_not_confused_with_word(self):
        meetings, unreadable = cp.convert("10/12\n10:00 pmo 定例\n", 2026)
        self.assertEqual(meetings[0]["title"], "pmo 定例")

    def test_sorted_by_date_even_if_pasted_out_of_order(self):
        meetings, _ = cp.convert("10/14\n9:00 B\n10/12\n9:00 A\n", 2026)
        self.assertEqual([m["title"] for m in meetings], ["A", "B"])

    def test_empty_input_gives_no_meetings(self):
        self.assertEqual(cp.convert("\n \n", 2026), ([], []))

    def test_output_is_accepted_by_proactive_scan_validator(self):
        meetings, _ = cp.convert(JP, 2026)
        doc = json.loads(json.dumps(cp.build_document(meetings)))
        self.assertEqual(proactive_scan.validate_meetings(doc["meetings"], "t"), doc["meetings"])


class MainTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.paste = self.dir / "paste.txt"
        self.paste.write_text(JP, encoding="utf-8")

    def run_main(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = cp.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def test_stdout_json_when_no_out(self):
        code, out, _ = self.run_main(str(self.paste), "--year", "2026")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["version"], 1)
        self.assertEqual(len(json.loads(out)["meetings"]), 3)

    def test_writes_out_file_and_refuses_overwrite(self):
        target = self.dir / "meetings.json"
        code, _, _ = self.run_main(str(self.paste), "--year", "2026", "--out", str(target))
        self.assertEqual(code, 0)
        before = target.read_text(encoding="utf-8")
        code, _, err = self.run_main(str(self.paste), "--year", "2026", "--out", str(target))
        self.assertEqual(code, 2)
        self.assertIn("上書きしない", err)
        self.assertEqual(target.read_text(encoding="utf-8"), before)

    def test_bom_is_ignored(self):
        self.paste.write_bytes(b"\xef\xbb\xbf" + JP.encode("utf-8"))
        code, out, _ = self.run_main(str(self.paste), "--year", "2026")
        self.assertEqual(code, 0)
        self.assertEqual(len(json.loads(out)["meetings"]), 3)

    def test_unreadable_lines_do_not_write_out_file(self):
        self.paste.write_text(JP + "謎の行\n", encoding="utf-8")
        target = self.dir / "meetings.json"
        code, _, err = self.run_main(str(self.paste), "--year", "2026", "--out", str(target))
        self.assertEqual(code, 1)
        self.assertFalse(target.exists())
        self.assertIn("7 行目: 謎の行", err)
        self.paste.write_text(JP, encoding="utf-8")
        self.assertEqual(self.run_main(str(self.paste), "--year", "2026", "--out", str(target))[0], 0)

    def test_unreadable_lines_exit_1_with_line_numbers_but_still_output(self):
        self.paste.write_text(JP + "謎の行\n", encoding="utf-8")
        code, out, err = self.run_main(str(self.paste), "--year", "2026")
        self.assertEqual(code, 1)
        self.assertEqual(len(json.loads(out)["meetings"]), 3)
        self.assertIn("7 行目: 謎の行", err)

    def test_missing_paste_file_exits_2(self):
        code, _, err = self.run_main(str(self.dir / "none.txt"))
        self.assertEqual(code, 2)
        self.assertIn("読めません", err)


if __name__ == "__main__":
    unittest.main()
