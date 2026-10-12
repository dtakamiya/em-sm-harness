import re
import unittest
from pathlib import Path

DOC = Path(__file__).resolve().parent.parent / "docs" / "design" / "34-deferred-review-findings.md"
STATE_RE = re.compile(r"^(open|不明|解消（#\d+.*）)$")


def table_rows():
    in_list = False
    rows = []
    for line in DOC.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            in_list = line.startswith("## 2.")
        if in_list and line.startswith("| D-"):
            rows.append([c.strip() for c in line.strip().strip("|").split("|")])
    return rows


class DeferredFindingsTest(unittest.TestCase):
    def test_every_row_has_six_columns(self):
        rows = table_rows()
        self.assertGreater(len(rows), 0)
        for row in rows:
            self.assertEqual(len(row), 6, row)
            self.assertTrue(all(row), row)

    def test_ids_are_sequential_without_gaps(self):
        ids = [int(r[0].split("-")[1]) for r in table_rows()]
        self.assertEqual(ids, list(range(1, len(ids) + 1)))

    def test_state_is_one_of_allowed(self):
        for row in table_rows():
            self.assertRegex(row[5], STATE_RE, row)

    def test_source_names_pr_number(self):
        for row in table_rows():
            self.assertRegex(row[1], r"#\d+", row)

    def test_unrecoverable_items_are_marked_unknown(self):
        text = DOC.read_text(encoding="utf-8")
        self.assertIn("内容は不明", text)

    def test_no_urls_emails_or_token_shapes(self):
        text = DOC.read_text(encoding="utf-8")
        pattern = r"https?://|@[A-Za-z0-9.-]+\.[a-z]{2,}|xox[bp]-|ghp_|AKIA[0-9A-Z]{8}|sk-[A-Za-z0-9]{10}"
        self.assertIsNone(re.search(pattern, text))

    def test_high_severity_is_not_deferred(self):
        for row in table_rows():
            self.assertNotIn("HIGH", row[1].upper(), row)

    def test_status_summary_matches_table(self):
        rows = table_rows()
        states = [r[5] for r in rows]
        open_n = sum(s == "open" for s in states)
        unknown_n = sum(s == "不明" for s in states)
        solved_n = sum(s.startswith("解消") for s in states)
        expected = f"全{len(rows)}件 = open {open_n} / 不明 {unknown_n} / 解消 {solved_n}"
        self.assertIn(expected, DOC.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
