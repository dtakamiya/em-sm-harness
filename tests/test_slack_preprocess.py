import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import slack_preprocess as sp  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures" / "slack-paste"
FIRST = FIXTURES / "2026-10-05-ex-team-01.md"
OVERLAP = FIXTURES / "2026-10-06-ex-team-02-overlap.md"
SENSITIVE = FIXTURES / "2026-10-07-ex-team-03-sensitive.md"


class SlackPreprocessTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.words = self.dir / "words.txt"
        self.words.write_text("# 架空の機微語\n査定\n退職\n", encoding="utf-8")
        self.out = self.dir / "parsed"

    def run_paste(self, path, dry_run=False):
        return sp.run(path, self.words, self.out, dry_run)

    def test_splits_paste_into_messages_with_meta(self):
        out = self.run_paste(FIRST)
        self.assertEqual([m["speaker"] for m in out["messages"]], ["Alice Example", "Bob Sample"])
        self.assertEqual(out["messages"][1]["text"], "確認待ちです。\n金曜までに決めたいです")
        self.assertEqual(out["meta"], {"channel_alias": "ex-team", "thread": "true", "pasted_on": "2026-10-05"})
        self.assertEqual(out["messages"][0]["id"], "m-001")
        self.assertEqual(len(list(self.out.glob("2026-10-05-ex-team-01-*.json"))), 1)

    def test_overlapping_repaste_keeps_only_new_messages(self):
        self.run_paste(FIRST)
        out = self.run_paste(OVERLAP)
        self.assertEqual([m["speaker"] for m in out["messages"]], ["Carol Demo"])
        self.assertEqual(out["duplicates_excluded"], 1)
        self.assertEqual(out["unparsed_lines"], 1)
        self.assertIn("未解釈 1 行", out["notes"])

    def test_identical_paste_is_skipped_and_not_written_again(self):
        self.run_paste(FIRST)
        copy = self.dir / "copy.md"
        copy.write_text(FIRST.read_text(encoding="utf-8"), encoding="utf-8")
        out = self.run_paste(copy)
        self.assertEqual(out["skipped"], "duplicate_paste")
        self.assertEqual(out["messages"], [])
        self.assertEqual(list(self.out.glob("copy-*.json")), [])

    def test_sensitive_paste_is_skipped_without_any_output_or_ledger(self):
        out = self.run_paste(SENSITIVE)
        self.assertEqual(out["skipped"], "sensitive")
        self.assertEqual(out["messages"], [])
        self.assertNotIn("査定", json.dumps(out, ensure_ascii=False))
        self.assertFalse(self.out.exists())

    def test_dry_run_writes_nothing(self):
        out = self.run_paste(FIRST, dry_run=True)
        self.assertEqual(len(out["messages"]), 2)
        self.assertFalse(self.out.exists())

    def test_missing_or_empty_words_file_stops(self):
        with self.assertRaises(sp.PreprocessError):
            sp.run(FIRST, self.dir / "nope.txt", self.out, False)
        self.words.write_text("# コメントだけ\n", encoding="utf-8")
        with self.assertRaises(sp.PreprocessError):
            self.run_paste(FIRST)

    def test_corrupt_ledger_stops_without_overwrite(self):
        self.out.mkdir()
        (self.out / sp.LEDGER_NAME).write_text("{broken", encoding="utf-8")
        with self.assertRaises(sp.PreprocessError):
            self.run_paste(FIRST)
        self.assertEqual((self.out / sp.LEDGER_NAME).read_text(encoding="utf-8"), "{broken")

    def test_no_headers_reports_unparsed_not_crash(self):
        plain = self.dir / "plain.md"
        plain.write_text("ただの文章\nもう一行\n", encoding="utf-8")
        out = self.run_paste(plain)
        self.assertEqual(out["messages"], [])
        self.assertEqual(out["unparsed_lines"], 2)

    def test_oversize_paste_asks_to_split(self):
        big = self.dir / "big.md"
        big.write_text("".join(f"U{i % 7}  10:{i % 60:02d}\n本文{i}\n" for i in range(sp.MESSAGE_SOFT_LIMIT + 1)),
                       encoding="utf-8")
        out = self.run_paste(big)
        self.assertTrue(any("分割" in n for n in out["notes"]))

    def test_same_name_paste_in_other_dir_does_not_overwrite_previous_output(self):
        other = self.dir / "other"
        other.mkdir()
        same_name = other / FIRST.name
        same_name.write_text("Dave Mock  12:00\n別の内容です\n", encoding="utf-8")
        self.run_paste(FIRST)
        self.run_paste(same_name)
        outputs = sorted(self.out.glob("2026-10-05-ex-team-01-*.json"))
        self.assertEqual(len(outputs), 2)
        texts = [json.loads(p.read_text(encoding="utf-8"))["messages"][0]["speaker"] for p in outputs]
        self.assertCountEqual(texts, ["Alice Example", "Dave Mock"])

    def test_existing_output_target_aborts_without_overwrite_or_ledger_update(self):
        out = self.run_paste(FIRST, dry_run=True)
        target = sp.output_path(self.out, FIRST, out["text_sha256"])
        self.out.mkdir()
        target.write_text("keep", encoding="utf-8")
        with self.assertRaises(sp.PreprocessError):
            self.run_paste(FIRST)
        self.assertEqual(target.read_text(encoding="utf-8"), "keep")
        self.assertFalse((self.out / sp.LEDGER_NAME).exists())

    def test_dotfile_or_empty_stem_is_rejected(self):
        for name in (".seen.json", ".hidden.md"):
            path = self.dir / name
            path.write_text("Alice Example  10:00\nhi\n", encoding="utf-8")
            with self.assertRaises(sp.PreprocessError):
                self.run_paste(path)

    def test_body_line_ending_with_time_is_not_a_header(self):
        paste = self.dir / "body-time.md"
        paste.write_text("Alice Example  10:00\n会議は 10:30\n次回の開始は10:30\n決定です、たぶん  11:00\n", encoding="utf-8")
        out = self.run_paste(paste)
        self.assertEqual(len(out["messages"]), 1)
        self.assertIn("会議は 10:30", out["messages"][0]["text"])
        self.assertIn("決定です、たぶん  11:00", out["messages"][0]["text"])

    def test_sensitive_word_matches_after_width_case_and_invisible_char_folding(self):
        for body in ("来期の査 定の件", "来期の査\u200b定の件", "ＨＲ評価の件 SALARY"):
            paste = self.dir / "s.md"
            paste.write_text(f"Alice Example  09:00\n{body}\n", encoding="utf-8")
            self.words.write_text("査定\nhr評価\n", encoding="utf-8")
            self.assertEqual(self.run_paste(paste)["skipped"], "sensitive", body)

    def test_unreadable_inputs_become_preprocess_errors_without_byte_fragments(self):
        bad = self.dir / "bad.md"
        bad.write_bytes(b"\xff\xfeSECRETBYTES")
        with self.assertRaises(sp.PreprocessError) as ctx:
            self.run_paste(bad)
        self.assertNotIn("SECRETBYTES", str(ctx.exception))
        with self.assertRaises(sp.PreprocessError):
            self.run_paste(self.dir)  # ディレクトリ指定
        bad_words = self.dir / "bad-words.txt"
        bad_words.write_bytes(b"\xff\xfe")
        with self.assertRaises(sp.PreprocessError):
            sp.run(FIRST, bad_words, self.out, False)

    def test_crlf_front_matter_is_read(self):
        paste = self.dir / "crlf.md"
        paste.write_bytes("---\r\nchannel_alias: ex-team\r\n---\r\nAlice Example  10:00\r\nhi\r\n".encode("utf-8"))
        out = self.run_paste(paste)
        self.assertEqual(out["meta"], {"channel_alias": "ex-team"})
        self.assertEqual(out["messages"][0]["text"], "hi")

    def test_main_never_prints_sensitive_word(self):
        import contextlib
        import io
        buf_out, buf_err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(buf_out), contextlib.redirect_stderr(buf_err):
            code = sp.main([str(SENSITIVE), "--words-file", str(self.words), "--out-dir", str(self.out)])
        self.assertEqual(code, 0)
        self.assertNotIn("査定", buf_out.getvalue() + buf_err.getvalue())

    def test_main_returns_1_with_reason_on_error(self):
        code = sp.main([str(FIRST), "--words-file", str(self.dir / "nope.txt"), "--out-dir", str(self.out)])
        self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main()
