import re
import unittest
from pathlib import Path

DOC = Path(__file__).resolve().parent.parent / "docs" / "design" / "34-deferred-review-findings.md"
ALLOWED_STATES = ("open", "不明", "解消（")


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
            self.assertTrue(row[5].startswith(ALLOWED_STATES), row)

    def test_source_names_pr_number(self):
        for row in table_rows():
            self.assertRegex(row[1], r"#\d+", row)

    def test_unrecoverable_items_are_marked_unknown(self):
        text = DOC.read_text(encoding="utf-8")
        self.assertIn("内容は不明", text)

    def test_no_secrets_or_urls(self):
        text = DOC.read_text(encoding="utf-8")
        self.assertIsNone(re.search(r"https?://|@[A-Za-z0-9.-]+\.[a-z]{2,}", text))


if __name__ == "__main__":
    unittest.main()
