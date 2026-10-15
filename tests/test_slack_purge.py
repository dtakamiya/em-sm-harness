import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import slack_purge as sp  # noqa: E402

NOW = 1_800_000_000.0
DAY = 86400


class SlackPurgeTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.base = self.tmp / "data" / "inbox" / "slack"
        for sub in ("", "parsed", "anon"):
            (self.base / sub).mkdir(parents=True, exist_ok=True)
        self.audit = self.tmp / "data" / "audit"

    def put(self, rel, age_days, body="x"):
        path = self.base / rel
        path.write_text(body, encoding="utf-8")
        os.utime(path, (NOW - age_days * DAY, NOW - age_days * DAY))
        return path

    def run_cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        argv = ["--base", str(self.base), "--audit-dir", str(self.audit), *args]
        with redirect_stdout(out), redirect_stderr(err):
            code = sp.main(argv, now=NOW)
        return code, out.getvalue(), err.getvalue()

    def test_keeps_13_days_and_deletes_15_days(self):
        young, old = self.put("anon/a.json", 13), self.put("anon/b.json", 15)
        code, _, _ = self.run_cli("--apply")
        self.assertEqual(code, 0)
        self.assertTrue(young.exists())
        self.assertFalse(old.exists())

    def test_default_is_dry_run_and_deletes_nothing(self):
        old = self.put("anon/b.json", 30)
        code, out, _ = self.run_cli()
        self.assertEqual(code, 0)
        self.assertTrue(old.exists())
        self.assertIn("dry-run", out)
        self.assertFalse(self.audit.exists())

    def test_covers_raw_parsed_and_anon_but_not_ledger_or_dotfiles(self):
        raw, parsed, anon = self.put("paste.md", 20), self.put("parsed/p.json", 20), self.put("anon/a.json", 20)
        ledger, dot = self.put("parsed/.seen.json", 99), self.put(".gitkeep", 99)
        self.run_cli("--apply")
        self.assertFalse(any(p.exists() for p in (raw, parsed, anon)))
        self.assertTrue(ledger.exists() and dot.exists())

    def test_does_not_touch_subdirectories_or_other_dirs(self):
        (self.base / "structured").mkdir()
        other = self.put("structured/s.json", 99)
        nested = self.put("anon/a.json", 1)
        (self.base / "anon" / "sub").mkdir()
        deep = self.base / "anon" / "sub" / "d.json"
        deep.write_text("x", encoding="utf-8")
        os.utime(deep, (NOW - 99 * DAY, NOW - 99 * DAY))
        self.run_cli("--apply")
        self.assertTrue(other.exists() and nested.exists() and deep.exists())

    def test_symlink_entry_refuses_and_deletes_nothing(self):
        outside = self.tmp / "outside.txt"
        outside.write_text("keep", encoding="utf-8")
        os.utime(outside, (NOW - 99 * DAY, NOW - 99 * DAY))
        (self.base / "anon" / "link.json").symlink_to(outside)
        old = self.put("anon/b.json", 30)
        code, _, err = self.run_cli("--apply")
        self.assertEqual(code, 2)
        self.assertTrue(outside.exists() and old.exists())
        self.assertIn("シンボリックリンク", err)

    def test_symlinked_subdir_refuses(self):
        real = self.tmp / "elsewhere"
        real.mkdir()
        victim = real / "v.json"
        victim.write_text("keep", encoding="utf-8")
        os.utime(victim, (NOW - 99 * DAY, NOW - 99 * DAY))
        (self.base / "anon").rmdir()
        (self.base / "anon").symlink_to(real)
        code, _, _ = self.run_cli("--apply")
        self.assertEqual(code, 2)
        self.assertTrue(victim.exists())

    def test_symlinked_base_refuses(self):
        link = self.tmp / "linkbase"
        link.symlink_to(self.base)
        old = self.put("anon/b.json", 30)
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = sp.main(["--base", str(link), "--audit-dir", str(self.audit), "--apply"], now=NOW)
        self.assertEqual(code, 2)
        self.assertTrue(old.exists())

    def test_missing_base_refuses(self):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = sp.main(["--base", str(self.tmp / "nope"), "--apply"], now=NOW)
        self.assertEqual(code, 2)

    def test_apply_writes_one_audit_line_without_names_or_bodies(self):
        self.put("anon/secret-name.json", 20, body="SECRET-BODY")
        self.put("paste.md", 20)
        self.put("anon/new.json", 1)
        self.run_cli("--apply")
        files = list(self.audit.glob("*.jsonl"))
        self.assertEqual(len(files), 1)
        lines = files[0].read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 1)
        row = json.loads(lines[0])
        self.assertEqual(row["event"], "retention_purged")
        self.assertEqual(row["deleted"], {"raw": 1, "parsed": 0, "anon": 1})
        self.assertNotIn("secret-name", lines[0])
        self.assertNotIn("SECRET-BODY", lines[0])

    def test_no_audit_line_when_nothing_deleted(self):
        self.put("anon/new.json", 1)
        self.run_cli("--apply")
        self.assertFalse(self.audit.exists())

    def test_unwritable_audit_stops_before_deleting(self):
        old = self.put("anon/b.json", 30)
        self.audit.parent.mkdir(parents=True, exist_ok=True)
        self.audit.write_text("not a dir", encoding="utf-8")
        code, _, err = self.run_cli("--apply")
        self.assertEqual(code, 2)
        self.assertTrue(old.exists())
        self.assertIn("監査", err)

    def test_output_never_shows_file_names(self):
        self.put("anon/secret-name.json", 20)
        _, out, err = self.run_cli()
        self.assertNotIn("secret-name", out + err)
        _, out, err = self.run_cli("--apply")
        self.assertNotIn("secret-name", out + err)

    def test_dry_run_reports_counts_by_area(self):
        self.put("anon/a.json", 20)
        self.put("anon/b.json", 20)
        _, out, _ = self.run_cli()
        self.assertIn("anon: 2", out)

    def test_exactly_14_days_is_kept(self):
        keep = self.put("anon/a.json", 14)
        self.run_cli("--apply")
        self.assertTrue(keep.exists())

    def test_symlink_inside_parsed_refuses(self):
        outside = self.tmp / "o.txt"
        outside.write_text("keep", encoding="utf-8")
        (self.base / "parsed" / "l.json").symlink_to(outside)
        old = self.put("paste.md", 30)
        code, _, _ = self.run_cli("--apply")
        self.assertEqual(code, 2)
        self.assertTrue(old.exists())

    def test_dry_run_with_symlink_exits_2(self):
        (self.base / "anon" / "l.json").symlink_to(self.tmp)
        code, _, _ = self.run_cli()
        self.assertEqual(code, 2)

    def test_unlink_failure_counts_only_and_still_audits(self):
        ok, bad = self.put("anon/a.json", 30), self.put("anon/secret-name.json", 30)
        real = Path.unlink

        def flaky(path, *a, **k):
            if path.name == "secret-name.json":
                raise PermissionError(13, "Permission denied", str(path))
            return real(path, *a, **k)

        from unittest import mock
        with mock.patch.object(Path, "unlink", flaky):
            code, out, err = self.run_cli("--apply")
        self.assertEqual(code, 2)
        self.assertFalse(ok.exists())
        self.assertTrue(bad.exists())
        self.assertNotIn("secret-name", out + err)
        row = json.loads(next(self.audit.glob("*.jsonl")).read_text(encoding="utf-8"))
        self.assertEqual((row["deleted"]["anon"], row["failed"]), (1, 1))

    def test_scan_oserror_exits_2_without_names(self):
        from unittest import mock
        self.put("anon/secret-name.json", 30)
        err_ = PermissionError(13, "Permission denied", str(self.base / "anon" / "secret-name.json"))
        with mock.patch.object(Path, "iterdir", side_effect=err_):
            code, out, err = self.run_cli("--apply")
        self.assertEqual(code, 2)
        self.assertNotIn("secret-name", out + err)

    def test_audit_file_is_0600(self):
        self.put("anon/a.json", 30)
        self.run_cli("--apply")
        mode = next(self.audit.glob("*.jsonl")).stat().st_mode & 0o777
        self.assertEqual(mode, 0o600)


if __name__ == "__main__":
    unittest.main()
