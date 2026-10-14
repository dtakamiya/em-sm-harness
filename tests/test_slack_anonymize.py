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
import slack_anonymize as sa  # noqa: E402
import slack_preprocess as sp  # noqa: E402

TEMPLATE = ROOT / "config" / "templates" / "local.roster.json.example"
FIRST = ROOT / "tests" / "fixtures" / "slack-paste" / "2026-10-05-ex-team-01.md"
KEY = "test-key-not-secret"
REAL_NAMES = ("Alice", "Bob", "Carol", "Example", "Sample", "アリス", "ボブ")


def message(mid, speaker, text, time="10:00"):
    return {"id": mid, "speaker": speaker, "time": time, "text": text, "msg_sha256": "x"}


def parsed_of(*messages, skipped=None):
    return {"schema_version": 1, "source": {"file": "p.md"}, "text_sha256": "abc", "skipped": skipped,
            "meta": {"channel_alias": "ex-team"}, "messages": list(messages), "notes": []}


class SlackAnonymizeTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.anon = self.dir / "anon"
        self.roster_path = TEMPLATE
        self.roster = sa.load_roster(TEMPLATE, KEY)

    def anonymize(self, *messages):
        return sa.anonymize(parsed_of(*messages), self.roster)

    def test_replaces_speaker_and_body_names_with_stable_handles(self):
        out = self.anonymize(message("m-001", "Alice Example", "Bob Sampleさんに確認します。@EM さんも見てください"),
                             message("m-002", "ボブ", "アリスです"))
        alice, bob = out["messages"][0]["speaker"], out["messages"][1]["speaker"]
        self.assertRegex(alice, r"^m_[0-9a-f]{6}$")
        self.assertEqual(out["messages"][0]["text"], f"{bob}さんに確認します。@em さんも見てください")
        self.assertEqual(out["messages"][1]["text"], f"{alice}です")
        again = sa.anonymize(parsed_of(message("m-001", "Alice", "x")), self.roster)
        self.assertEqual(again["messages"][0]["speaker"], alice)

    def test_handle_depends_on_key(self):
        other = sa.load_roster(TEMPLATE, "another-key")
        a = sa.anonymize(parsed_of(message("m-001", "Alice", "x")), self.roster)["messages"][0]["speaker"]
        b = sa.anonymize(parsed_of(message("m-001", "Alice", "x")), other)["messages"][0]["speaker"]
        self.assertNotEqual(a, b)

    def test_url_and_org_are_masked_and_jira_key_kept(self):
        out = self.anonymize(message("m-001", "Bob", "EXAMPLE-12 は https://example.invalid/x/y で Example Corp が見ます"))
        self.assertEqual(out["messages"][0]["text"], "EXAMPLE-12 は [URL] で [org] が見ます")

    def test_stops_when_name_outside_roster_remains_in_body(self):
        for body in ("Dave Fixture が担当です", "Daveさんに聞きます", "田中さんに確認", "@dave に依頼", "Dave-san ok"):
            with self.subTest(body=body), self.assertRaises(sa.AnonymizeError) as ctx:
                self.anonymize(message("m-007", "Alice", body))
            self.assertIn("m-007", str(ctx.exception))
            self.assertIn("何も書いていません", str(ctx.exception))

    def test_stops_when_speaker_is_outside_roster(self):
        with self.assertRaises(sa.AnonymizeError):
            self.anonymize(message("m-003", "Zed Unknown", "こんにちは"))

    def test_error_message_does_not_echo_the_unknown_name(self):
        with self.assertRaises(sa.AnonymizeError) as ctx:
            self.anonymize(message("m-001", "Alice", "Dave Fixture と田中さんが担当"))
        for leaked in ("Dave", "Fixture", "田中"):
            self.assertNotIn(leaked, str(ctx.exception))

    def test_allow_words_and_everyday_phrases_do_not_stop(self):
        out = self.anonymize(message("m-001", "Alice", "Slack Bot から皆さんへ。@here お願いします"))
        self.assertEqual(out["unmasked_suspects"], 0)

    def test_latin_name_next_to_cjk_is_still_replaced(self):
        out = self.anonymize(message("m-001", "Alice", "確認Bob Sampleさん"))
        self.assertNotIn("Bob", out["messages"][0]["text"])

    def test_refuses_skipped_input(self):
        with self.assertRaises(sa.AnonymizeError):
            sa.anonymize(parsed_of(skipped="sensitive"), self.roster)

    def test_roster_validation_fail_closed(self):
        with self.assertRaises(sa.AnonymizeError):
            sa.load_roster(TEMPLATE, "")
        with self.assertRaises(sa.AnonymizeError):
            sa.load_roster(self.dir / "missing.json", KEY)
        bad = {"em": {"names": ["EM"]}, "people": [{"names": ["Al"]}, {"names": ["x"]}]}
        dup = {"em": {"names": ["EM"]}, "people": [{"names": ["Alice"]}, {"names": ["alice"]}]}
        for name, data in (("bad", bad), ("dup", dup), ("shape", {"people": []})):
            path = self.dir / f"{name}.json"
            path.write_text(json.dumps(data), encoding="utf-8")
            with self.subTest(name=name), self.assertRaises(sa.AnonymizeError):
                sa.load_roster(path, KEY)

    def preprocess_fixture(self):
        words = self.dir / "words.txt"
        words.write_text("査定\n", encoding="utf-8")
        sp.run(FIRST, words, self.dir / "parsed", False)
        return next((self.dir / "parsed").glob("2026-10-05-ex-team-01-*.json"))

    def test_end_to_end_writes_anon_without_any_roster_name_or_hash(self):
        parsed = self.preprocess_fixture()
        sa.run(parsed, TEMPLATE, self.anon, KEY, False)
        written = (self.anon / parsed.name).read_text(encoding="utf-8")
        for name in REAL_NAMES:
            self.assertNotIn(name, written)
        self.assertNotIn("msg_sha256", written)
        self.assertEqual(sa.load_anon(self.anon / parsed.name, self.anon)["kind"], "slack_anon")

    def test_nothing_is_written_when_stopped_or_dry_run(self):
        path = self.dir / "p.json"
        path.write_text(json.dumps(parsed_of(message("m-001", "Alice", "Dave Fixture"))), encoding="utf-8")
        with self.assertRaises(sa.AnonymizeError):
            sa.run(path, TEMPLATE, self.anon, KEY, False)
        self.assertFalse(self.anon.exists())
        path.write_text(json.dumps(parsed_of(message("m-001", "Alice", "ok"))), encoding="utf-8")
        sa.run(path, TEMPLATE, self.anon, KEY, True)
        self.assertFalse(self.anon.exists())

    def test_existing_output_is_not_overwritten(self):
        path = self.dir / "p.json"
        path.write_text(json.dumps(parsed_of(message("m-001", "Alice", "ok"))), encoding="utf-8")
        sa.run(path, TEMPLATE, self.anon, KEY, False)
        with self.assertRaises(sa.AnonymizeError):
            sa.run(path, TEMPLATE, self.anon, KEY, False)

    def test_anon_reader_rejects_raw_equivalent_outside_symlink_and_unmarked(self):
        parsed = self.preprocess_fixture()
        self.anon.mkdir()
        with self.assertRaises(sa.AnonymizeError):
            sa.load_anon(parsed, self.anon)  # parsed/ は raw 相当
        link = self.anon / "link.json"
        link.symlink_to(parsed)
        with self.assertRaises(sa.AnonymizeError):
            sa.load_anon(link, self.anon)  # anon/ 内のリンクで raw を読ませない
        unmarked = self.anon / "plain.json"
        unmarked.write_text(json.dumps({"messages": []}), encoding="utf-8")
        with self.assertRaises(sa.AnonymizeError):
            sa.load_anon(unmarked, self.anon)

    def test_anon_reader_rejects_files_older_than_retention(self):
        path = self.dir / "p.json"
        path.write_text(json.dumps(parsed_of(message("m-001", "Alice", "ok"))), encoding="utf-8")
        sa.run(path, TEMPLATE, self.anon, KEY, False)
        target = self.anon / "p.json"
        mtime = target.stat().st_mtime
        sa.load_anon(target, self.anon, now=mtime + (sa.RETENTION_DAYS - 1) * 86400)
        with self.assertRaises(sa.AnonymizeError):
            sa.load_anon(target, self.anon, now=mtime + (sa.RETENTION_DAYS + 1) * 86400)

    def test_cli_exit_codes_and_stderr_has_no_names(self):
        path = self.dir / "p.json"
        path.write_text(json.dumps(parsed_of(message("m-001", "Alice", "Dave Fixture"))), encoding="utf-8")
        os.environ[sa.KEY_ENV] = KEY
        self.addCleanup(os.environ.pop, sa.KEY_ENV, None)
        err = io.StringIO()
        with redirect_stderr(err), redirect_stdout(io.StringIO()):
            code = sa.main([str(path), "--roster", str(TEMPLATE), "--anon-dir", str(self.anon)])
        self.assertEqual(code, 2)
        self.assertNotIn("Dave", err.getvalue())


if __name__ == "__main__":
    unittest.main()
