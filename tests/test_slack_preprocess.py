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
        self.assertTrue((self.out / "2026-10-05-ex-team-01.json").exists())

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
        self.assertFalse((self.out / "copy.json").exists())

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
        big.write_text("".join(f"U{i % 7} 10:{i % 60:02d}\n本文{i}\n" for i in range(sp.MESSAGE_SOFT_LIMIT + 1)),
                       encoding="utf-8")
        out = self.run_paste(big)
        self.assertTrue(any("分割" in n for n in out["notes"]))

    def test_main_returns_1_with_reason_on_error(self):
        code = sp.main([str(FIRST), "--words-file", str(self.dir / "nope.txt"), "--out-dir", str(self.out)])
        self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main()
