import io
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import meeting_preprocess as mp  # noqa: E402
import slack_anonymize as sa  # noqa: E402
import slack_preprocess as sp  # noqa: E402

TEMPLATE = ROOT / "config" / "templates" / "local.roster.json.example"
RAW = ROOT / "tests" / "fixtures" / "meeting-paste" / "raw-ex-planning.md"
KEY = "test-key-not-secret"
REAL_NAMES = ("Alice", "Bob", "Carol", "Eve", "Example", "Demo", "アリス", "ボブ", "example.com")
FRONT = "---\nmeeting_alias: ex-planning\nheld_on: 2026-10-05\n---\n"


class MeetingPreprocessTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.words = self.dir / "words.txt"
        self.words.write_text("# 架空\n査定\n懲戒\n", encoding="utf-8")
        self.out = self.dir / "meeting"
        original = mp.ALLOWED_OUT_ROOT
        mp.ALLOWED_OUT_ROOT = self.dir  # 実 data/ には書かない
        self.addCleanup(setattr, mp, "ALLOWED_OUT_ROOT", original)
        self.roster = sa.load_roster(TEMPLATE, KEY)
        self.words_list = sp.load_sensitive_words(self.words)

    def anonymize(self, body):
        return mp.anonymize_note(FRONT + body, self.roster, self.words_list)

    def run_main(self, paste=RAW, *extra, key=KEY):
        old = os.environ.get(sa.KEY_ENV)
        os.environ[sa.KEY_ENV] = key
        self.addCleanup(lambda: os.environ.__setitem__(sa.KEY_ENV, old) if old is not None else os.environ.pop(sa.KEY_ENV, None))
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = mp.main([str(paste), "--roster", str(TEMPLATE), "--words-file", str(self.words),
                            "--out-dir", str(self.out), *extra])
        return code, out.getvalue(), err.getvalue()

    def test_fictional_note_becomes_anonymized_input_in_28_format(self):
        code, stdout, _ = self.run_main()
        self.assertEqual(code, 0)
        written = (self.out / "2026-10-05-ex-planning.md").read_text(encoding="utf-8")
        self.assertTrue(written.startswith(FRONT))
        for name in REAL_NAMES:
            self.assertNotIn(name, written)
        self.assertIn("[URL]", written)
        self.assertRegex(written, r"- m_[0-9a-f]{6}: デモ環境")
        self.assertIn("- em: 見積もりの前提を m_", written)
        self.assertIn("## 決定", written)  # 見出しは残る（28 §2）
        self.assertIn("8 行", stdout)  # 見出し 3 + 箇条書き 5

    def test_output_is_private_and_not_overwritten(self):
        self.run_main()
        target = self.out / "2026-10-05-ex-planning.md"
        self.assertEqual(target.stat().st_mode & 0o777, 0o600)
        code, _, err = self.run_main()
        self.assertEqual(code, 2)
        self.assertIn("同名の匿名化済みファイルが既にあります", err)

    def test_reuses_slack_parts_instead_of_reimplementing(self):
        self.assertIs(mp.sa.mask, sa.mask)
        self.assertIs(mp.sp.is_sensitive, sp.is_sensitive)
        source = (ROOT / "scripts" / "meeting_preprocess.py").read_text(encoding="utf-8")
        for duplicate in ("def mask(", "def count_suspects(", "def is_sensitive(", "def write_new_private(", "hmac"):
            self.assertNotIn(duplicate, source)

    def test_sensitive_note_is_skipped_without_writing_or_echoing_the_word(self):
        paste = self.dir / "hr.md"
        paste.write_text(FRONT + "- 査定の件を話した\n", encoding="utf-8")
        code, _, err = self.run_main(paste)
        self.assertEqual(code, 2)
        self.assertIn("読みません", err)
        self.assertNotIn("査定", err)
        self.assertFalse(self.out.exists())

    def test_unknown_person_stops_and_writes_nothing(self):
        paste = self.dir / "unknown.md"
        paste.write_text(FRONT + "- ok\n- Zed Unknown がレビューする\n", encoding="utf-8")
        code, _, err = self.run_main(paste)
        self.assertEqual(code, 2)
        self.assertIn("2 行目", err)
        self.assertNotIn("Zed", err)
        self.assertFalse(self.out.exists())

    def test_honorific_without_roster_entry_also_stops(self):
        with self.assertRaises(sa.AnonymizeError):
            self.anonymize("- 田中さんが確認する\n")

    def test_front_matter_is_required_and_validated(self):
        for bad in ("- 本文だけ\n", "---\nmeeting_alias: ex-planning\n---\n- x\n",
                    "---\nmeeting_alias: Real Meeting Name\nheld_on: 2026-10-05\n---\n- x\n",
                    "---\nmeeting_alias: ex-planning\nheld_on: 10/05\n---\n- x\n"):
            with self.assertRaises(sa.AnonymizeError, msg=bad):
                mp.anonymize_note(bad, self.roster, self.words_list)

    def test_missing_key_stops_before_reading(self):
        code, _, err = self.run_main(key="")
        self.assertEqual(code, 2)
        self.assertIn(sa.KEY_ENV, err)

    def test_dry_run_writes_nothing(self):
        code, stdout, _ = self.run_main(RAW, "--dry-run")
        self.assertEqual(code, 0)
        self.assertIn("dry-run", stdout)
        self.assertFalse(self.out.exists())

    def test_long_note_is_flagged_for_splitting(self):
        paste = self.dir / "long.md"
        paste.write_text(FRONT + "".join(f"- 項目 {i}\n" for i in range(mp.LINE_SOFT_LIMIT + 1)), encoding="utf-8")
        _, stdout, _ = self.run_main(paste, "--dry-run")
        self.assertIn("分割", stdout)

    def test_out_dir_outside_data_is_rejected(self):
        mp.ALLOWED_OUT_ROOT = self.dir / "allowed"
        for bad in (self.dir / "elsewhere", self.dir / "allowed" / ".." / "x"):
            code, _, err = self.run_main(RAW, "--out-dir", str(bad))
            self.assertEqual(code, 2, bad)
            self.assertIn("配下に限ります", err)
            self.assertFalse((self.dir / "elsewhere").exists())

    def test_out_dir_symlink_escape_is_rejected(self):
        (self.dir / "allowed").mkdir()
        (self.dir / "outside").mkdir()
        (self.dir / "allowed" / "link").symlink_to(self.dir / "outside")
        mp.ALLOWED_OUT_ROOT = self.dir / "allowed"
        code, _, _ = self.run_main(RAW, "--out-dir", str(self.dir / "allowed" / "link"))
        self.assertEqual(code, 2)
        self.assertEqual(list((self.dir / "outside").iterdir()), [])

    def test_default_out_dir_is_under_gitignored_data(self):
        self.assertEqual(mp.DEFAULT_OUT_DIR, ROOT / "data" / "inbox" / "meeting")
        self.assertIn("data/", (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines())

    def test_unknown_speaker_head_without_honorific_stops(self):
        for line in ("- 田中: 来週までに確認します", "- Tanaka: I will check", "鈴木太郎：やります", "tanaka taro: ok"):
            with self.assertRaises(sa.AnonymizeError, msg=line):
                self.anonymize(line + "\n")

    def test_speaker_head_reports_line_number_only(self):
        paste = self.dir / "head.md"
        paste.write_text(FRONT + "## 決定\n- ok\n- 山本: 対応する\n", encoding="utf-8")
        code, _, err = self.run_main(paste)
        self.assertEqual(code, 2)
        self.assertIn("3 行目", err)
        self.assertNotIn("山本", err)
        self.assertFalse(self.out.exists())

    def test_known_labels_handles_and_ticket_keys_are_not_speaker_heads(self):
        text, _, count = self.anonymize("- 決定: EX-102 は回す\n- アクション: 手順書\n- em: 共有する\n- EX-102: 保留\n- Alice: 確認\n- 10:00 開始\n")
        self.assertEqual(count, 6)
        self.assertIn("m_", text)

    def test_allow_words_can_clear_a_speaker_head_false_positive(self):
        roster = {**self.roster, "allow": [*self.roster["allow"], "背景"]}
        mp.anonymize_note(FRONT + "- 背景: 経緯\n", roster, self.words_list)

    def test_held_on_must_be_a_real_ascii_date(self):
        for bad in ("2026-13-45", "2026-02-30", "２０２６-１０-０５", "2026-1-5"):
            with self.assertRaises(sa.AnonymizeError, msg=bad):
                mp.anonymize_note(f"---\nmeeting_alias: ex-planning\nheld_on: {bad}\n---\n- x\n", self.roster, self.words_list)

    def test_dry_run_reports_existing_target_and_message_is_clear(self):
        self.run_main()
        code, _, err = self.run_main(RAW, "--dry-run")
        self.assertEqual(code, 2)
        self.assertIn("同名の匿名化済みファイルが既にあります", err)

    def test_unreadable_paste_error_does_not_echo_path(self):
        missing = self.dir / "secret-name-田中.md"
        code, _, err = self.run_main(missing)
        self.assertEqual(code, 2)
        self.assertNotIn("田中", err)
        self.assertNotIn(str(self.dir), err)

    def test_slack_preprocess_front_matter_keys_are_unchanged(self):
        meta, _ = sp.split_front_matter("---\nchannel_alias: ex-team\nheld_on: 2026-10-05\n---\nx\n")
        self.assertEqual(meta, {"channel_alias": "ex-team"})


if __name__ == "__main__":
    unittest.main()
