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
import approval_queue as aq  # noqa: E402
import save_action as sa  # noqa: E402

TODAY = date(2026, 10, 5)


def sample(**kw):
    base = {"action_id": "a-0001", "kind": "minutes", "title": "会議メモ共有", "target": "example-channel",
            "body": "共有ありがとうございます。", "priority": "medium"}
    return {**base, **kw}


class PrepareTest(unittest.TestCase):
    def test_fills_default_expires_without_mutating_input(self):
        raw = sample()
        action = sa.prepare(raw, TODAY)
        self.assertEqual(action["expires"], "2026-10-19")
        self.assertNotIn("expires", raw)

    def test_rejects_expires_beyond_retention_limit(self):
        with self.assertRaises(sa.SaveError):
            sa.prepare(sample(expires="2027-03-01"), TODAY)

    def test_rejects_url_in_body(self):
        with self.assertRaises(sa.SaveError):
            sa.prepare(sample(body="詳細は https://example.com"), TODAY)

    def test_drops_unknown_keys(self):
        action = sa.prepare(sample(extra_note="x", owner_name="y"), TODAY)
        self.assertNotIn("extra_note", action)
        self.assertNotIn("owner_name", action)
        self.assertEqual(action["action_id"], "a-0001")

    def test_rejects_non_object(self):
        with self.assertRaises(sa.SaveError):
            sa.prepare(["x"], TODAY)


class MainTest(unittest.TestCase):
    def run_main(self, tmp, raw, *extra):
        src = Path(tmp) / "in.json"
        src.write_text(raw if isinstance(raw, str) else json.dumps(raw, ensure_ascii=False), encoding="utf-8")
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = sa.main([str(src), "--actions-dir", str(Path(tmp) / "actions"), "--today", "2026-10-05", *extra])
        return code, out.getvalue(), err.getvalue()

    def test_saved_file_is_readable_by_approval_queue(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, _, _ = self.run_main(tmp, sample())
            actions, rejected = aq.load_actions(Path(tmp) / "actions")
        self.assertEqual(code, 0)
        self.assertEqual([a["action_id"] for a in actions], ["a-0001"])
        self.assertEqual(rejected, [])

    def test_invalid_input_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, _, err = self.run_main(tmp, sample(body="送信しました"))
            self.assertEqual(code, 1)
            self.assertIn("保存しませんでした", err)
            self.assertFalse((Path(tmp) / "actions").exists())

    def test_broken_json_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, _, _ = self.run_main(tmp, "{")
            self.assertEqual(code, 1)
            self.assertFalse((Path(tmp) / "actions").exists())

    def test_does_not_overwrite_existing_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.run_main(tmp, sample())
            code, _, err = self.run_main(tmp, sample(title="別の件名"))
            saved = json.loads((Path(tmp) / "actions" / "a-0001.json").read_text(encoding="utf-8"))
            leftovers = list((Path(tmp) / "actions").glob("*.tmp"))
        self.assertEqual(code, 1)
        self.assertIn("保存済み", err)
        self.assertEqual(saved["title"], "会議メモ共有")
        self.assertEqual(leftovers, [])

    def test_unknown_keys_not_saved_to_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.run_main(tmp, sample(extra_note="x"))
            saved = json.loads((Path(tmp) / "actions" / "a-0001.json").read_text(encoding="utf-8"))
        self.assertNotIn("extra_note", saved)

    def test_path_traversal_action_id_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, _, err = self.run_main(tmp, sample(action_id="../x"))
            self.assertEqual(code, 1)
            self.assertIn("保存しませんでした", err)
            self.assertFalse((Path(tmp) / "actions").exists())
            self.assertFalse((Path(tmp) / "x.json").exists())

    def test_os_error_returns_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            blocker = Path(tmp) / "actions"
            blocker.write_text("file, not dir", encoding="utf-8")
            code, _, err = self.run_main(tmp, sample())
        self.assertEqual(code, 1)
        self.assertIn("保存できませんでした", err)

    def test_dry_run_does_not_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, out, _ = self.run_main(tmp, sample(), "--dry-run")
            self.assertEqual(code, 0)
            self.assertIn("保存していません", out)
            self.assertFalse((Path(tmp) / "actions").exists())

    def test_missing_input_returns_error(self):
        err = io.StringIO()
        with redirect_stderr(err):
            code = sa.main(["/nonexistent/in.json"])
        self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main()
