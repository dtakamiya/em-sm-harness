import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import check_no_leak as cnl  # noqa: E402

# 偽トークンは実行時に組み立てる（このファイル自体が検知に引っかからないように）
FAKE_SLACK = "xox" + "b-" + "1234567890-abcdefghij"
FAKE_GITHUB = "gh" + "p_" + "a" * 36
FAKE_ATLASSIAN = "AT" + "ATT" + "x" * 24


def codes(findings):
    return {f.code for f in findings}


class CheckPathTest(unittest.TestCase):
    def test_data_dir_is_error(self):
        self.assertEqual(codes(cnl.check_path("data/inbox/slack.txt")), {"forbidden-path"})

    def test_env_and_local_config_are_errors(self):
        for p in (".env", ".env.prod", "config/local.yaml", "secrets/key.txt"):
            self.assertTrue(cnl.check_path(p), p)

    def test_normal_paths_pass(self):
        for p in ("docs/design/01-jira-connection.md", "tests/fixtures/sample.json", "templates/drafts/x.md"):
            self.assertEqual(cnl.check_path(p), [], p)


class ScanTest(unittest.TestCase):
    def scan(self, line, local=()):
        return cnl.scan_added_lines("f.md", [(3, line)], local)

    def test_token_formats_are_errors_and_value_not_echoed(self):
        for tok in (FAKE_SLACK, FAKE_GITHUB, FAKE_ATLASSIAN):
            found = self.scan(f"token = {tok}")
            self.assertEqual({f.level for f in found}, {"error"}, tok)
            self.assertNotIn(tok, " ".join(f.message + f.where for f in found))

    def test_internal_urls_and_emails_are_warnings(self):
        for line in ("see https://acme-corp.atlassian.net/browse/X-1", "mail taro@acme-corp.co.jp"):
            found = self.scan(line)
            self.assertEqual({f.level for f in found}, {"warning"}, line)

    def test_example_domain_and_plain_text_pass(self):
        self.assertEqual(self.scan("連絡先は taro@example.com（架空）"), [])
        self.assertEqual(self.scan("環境変数 JIRA_API_TOKEN を参照する"), [])

    def test_allow_mark_skips_line(self):
        self.assertEqual(self.scan(f"例: {FAKE_SLACK} leak-ok"), [])

    def test_local_patterns_warn(self):
        local = (("local-pattern:1", __import__("re").compile(r"ProjectOrion")),)
        self.assertEqual(codes(self.scan("ProjectOrion の件", local)), {"local-pattern:1"})


class DiffTest(unittest.TestCase):
    DIFF = "\n".join([
        "diff --git a/a.md b/a.md", "--- a/a.md", "+++ b/a.md", "@@ -1,0 +5,2 @@",
        "+ok line", f"+key {FAKE_GITHUB}", "-removed",
    ])

    def test_only_added_lines_with_line_numbers(self):
        self.assertEqual(cnl.parse_added_lines(self.DIFF), {"a.md": [(5, "ok line"), (6, f"key {FAKE_GITHUB}")]})

    def test_run_check_reports_line(self):
        found = cnl.run_check(self.DIFF, ["a.md"])
        self.assertEqual([(f.code, f.where) for f in found], [("token-github", "a.md:6")])

    def test_deleted_file_diff_is_ignored(self):
        self.assertEqual(cnl.parse_added_lines("--- a/x\n+++ /dev/null\n@@ -1 +0,0 @@\n-gone"), {})


class LocalPatternsFileTest(unittest.TestCase):
    def test_missing_file_is_empty(self):
        self.assertEqual(cnl.load_local_patterns(ROOT / "nonexistent.txt"), ())

    def test_comments_skipped_and_bad_regex_fails_closed(self):
        with tempfile.TemporaryDirectory() as d:
            ok = Path(d) / "ok.txt"
            ok.write_text("# c\n\nfoo\\d+\n", encoding="utf-8")
            self.assertEqual(len(cnl.load_local_patterns(ok)), 1)
            bad = Path(d) / "bad.txt"
            bad.write_text("(unclosed\n", encoding="utf-8")
            with self.assertRaises(SystemExit):
                cnl.load_local_patterns(bad)


if __name__ == "__main__":
    unittest.main()
