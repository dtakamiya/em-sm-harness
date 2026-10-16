"""14 日超の Slack 一時ファイル件数の1行表示（emh-087）。架空日付・一時ディレクトリのみ。削除・書き込みは一切しない。"""
import contextlib
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import check_env  # noqa: E402
import morning_plan as mp  # noqa: E402
import slack_purge as sp  # noqa: E402

NOW = 1_800_000_000.0
DAY = 86400
SAMPLES = ROOT / "skills" / "morning-plan" / "examples"
SECRET_NAME = "secret-name"


class PendingNoticeTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.base = self.tmp / "data" / "inbox" / "slack"
        self.structured = self.tmp / "data" / "structured" / "slack"
        for d in (self.base, self.base / "parsed", self.base / "anon", self.structured):
            d.mkdir(parents=True)

    def put(self, rel, age_days, root=None):
        path = (root or self.base) / rel
        path.write_text("x", encoding="utf-8")
        os.utime(path, (NOW - age_days * DAY, NOW - age_days * DAY))
        return path

    def notice(self):
        return sp.pending_notice(self.base, self.structured, now=NOW)

    def test_13_days_shows_nothing(self):
        self.put("a.md", 13)
        self.assertIsNone(self.notice())

    def test_15_days_shows_count_and_command_only(self):
        self.put(f"{SECRET_NAME}.md", 15)
        self.put("p.json", 20, self.base / "parsed")
        self.put("s.json", 30, self.structured)
        line = self.notice()
        self.assertIn("3 件", line)
        self.assertIn("python3 scripts/slack_purge.py", line)
        self.assertNotIn(SECRET_NAME, line)
        self.assertNotIn("\n", line)

    def test_zero_expired_adds_nothing(self):
        self.assertIsNone(self.notice())

    def test_missing_base_adds_nothing(self):
        self.assertIsNone(sp.pending_notice(self.tmp / "nope", self.structured, now=NOW))

    def test_never_deletes_or_writes(self):
        old = self.put("a.md", 30)
        self.notice()
        self.assertTrue(old.exists())
        self.assertFalse((self.tmp / "data" / "audit").exists())

    def test_unexpected_extension_reports_purge_blocked(self):
        self.put(f"{SECRET_NAME}.txt", 30, self.structured)
        line = self.notice()
        self.assertIn("止まる状態", line)
        self.assertNotIn(SECRET_NAME, line)

    def test_symlink_reports_purge_blocked(self):
        os.symlink(self.base / "parsed", self.base / "link")
        self.assertIn("止まる状態", self.notice())


class WiringTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.base = self.tmp / "data" / "inbox" / "slack"
        self.structured = self.tmp / "data" / "structured" / "slack"
        for d in (self.base, self.structured):
            d.mkdir(parents=True)

    def expire(self):
        path = self.base / "old.md"
        path.write_text("x", encoding="utf-8")
        os.utime(path, (1.0, 1.0))

    def morning(self):
        argv = ["--tasks", str(SAMPLES / "tasks.sample.json"), "--candidates", str(SAMPLES / "candidates.sample.json"),
                "--today", "2026-10-04", "--slack-base", str(self.base), "--slack-structured", str(self.structured)]
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            mp.main(argv)
        return buf.getvalue()

    def test_morning_plan_shows_one_line_in_detail_when_expired(self):
        self.expire()
        out = self.morning()
        self.assertEqual(out.count("slack_purge.py"), 1)
        self.assertGreater(out.index("slack_purge.py"), out.index("## 詳細"))

    def test_morning_plan_unchanged_when_nothing_expired(self):
        self.assertNotIn("slack_purge", self.morning())

    def test_check_env_prints_notice_without_changing_exit_code(self):
        self.expire()
        with contextlib.redirect_stdout(io.StringIO()) as plain:
            base_code = check_env.main(["--root", str(self.tmp / "other")])
        with contextlib.redirect_stdout(io.StringIO()) as buf:
            code = check_env.main(["--root", str(self.tmp)])
        self.assertEqual(code, base_code)
        self.assertEqual(buf.getvalue().count("slack_purge.py"), 1)
        self.assertNotIn("slack_purge", plain.getvalue())
        self.assertTrue((self.base / "old.md").exists())


if __name__ == "__main__":
    unittest.main()
