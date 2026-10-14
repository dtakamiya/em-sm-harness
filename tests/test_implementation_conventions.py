import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = sorted((ROOT / "scripts").glob("*.py"))
JOB_LIST = ROOT / "docs" / "design" / "12-secretary-job-list.md"
CONVENTIONS = ROOT / "docs" / "design" / "27-implementation-conventions.md"

CATEGORY_LABELS = {"先": "先回り", "下": "下書き", "決": "EM が決める"}
ROW_RE = re.compile(r"^\| [A-Z]\d+ \|", re.MULTILINE)
SUMMARY_RE = re.compile(r"先回り (\d+) / 下書き (\d+) / EM が決める (\d+)")
TOTAL_RE = re.compile(r"計(\d+)項目")


def job_rows():
    """12 §3 の仕事の行を (id, 分類) で返す。"""
    text = JOB_LIST.read_text(encoding="utf-8")
    rows = [line for line in text.splitlines() if ROW_RE.match(line)]
    return [(r.split("|")[1].strip(), r.split("|")[3].strip()) for r in rows]


class JobListCountTest(unittest.TestCase):
    def test_summary_counts_match_table_rows(self):
        text = JOB_LIST.read_text(encoding="utf-8")
        summary = tuple(int(n) for n in SUMMARY_RE.search(text).groups())
        categories = [c for _, c in job_rows()]
        actual = tuple(categories.count(k) for k in CATEGORY_LABELS)
        self.assertEqual(summary, actual)

    def test_total_matches_table_rows(self):
        text = JOB_LIST.read_text(encoding="utf-8")
        self.assertEqual(int(TOTAL_RE.search(text).group(1)), len(job_rows()))

    def test_every_row_has_a_known_category_and_unique_id(self):
        rows = job_rows()
        self.assertTrue(all(c in CATEGORY_LABELS for _, c in rows))
        ids = [i for i, _ in rows]
        self.assertEqual(len(ids), len(set(ids)))


class ScriptConventionTest(unittest.TestCase):
    def test_scripts_exist(self):
        self.assertTrue(SCRIPTS)

    def test_no_cwd_dependent_paths(self):
        for path in SCRIPTS:
            text = path.read_text(encoding="utf-8")
            with self.subTest(script=path.name):
                self.assertNotIn("os.getcwd", text)
                self.assertNotIn("Path.cwd", text)

    def test_default_paths_are_anchored_on_file(self):
        for path in SCRIPTS:
            text = path.read_text(encoding="utf-8")
            if "DEFAULT_" not in text and "ROOT" not in text:
                continue
            with self.subTest(script=path.name):
                self.assertIn("Path(__file__)", text)

    def test_os_replace_is_paired_with_tmp_file(self):
        for path in SCRIPTS:
            text = path.read_text(encoding="utf-8")
            if "os.replace(" not in text:
                continue
            with self.subTest(script=path.name):
                self.assertIn(".tmp", text)

    def test_backup_names_are_distinct_per_writer(self):
        names = re.findall(r'BACKUP_NAME = "([^"]+)"', "".join(p.read_text(encoding="utf-8") for p in SCRIPTS))
        self.assertEqual(len(names), len(set(names)))

    def test_convention_doc_lists_each_backup_name(self):
        doc = CONVENTIONS.read_text(encoding="utf-8")
        for path in SCRIPTS:
            for name in re.findall(r'BACKUP_NAME = "([^"]+)"', path.read_text(encoding="utf-8")):
                with self.subTest(backup=name):
                    self.assertIn(name, doc)


if __name__ == "__main__":
    unittest.main()
