import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import jira_metrics as jm  # noqa: E402

SKILL = ROOT / "skills" / "sprint-health"
FIXTURES = ROOT / "tests" / "fixtures" / "jira-metrics"
DOC = ROOT / "docs" / "design" / "31-sprint-health-template.md"
BANNED = re.compile(r"送信しました|更新しました|遅い|おそらく|放置|原因は|assignee_ref|u_\w+|🔴")
MAX_BODY_CHARS = 600


def _load(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class SprintHealthSkillTest(unittest.TestCase):
    def test_frontmatter_and_l1_boundary(self):
        text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
        self.assertTrue(text.startswith("---\nname: sprint-health\n"))
        for phrase in ("L1", "書き込み・送信", "一字一句そのまま", "再取得が必要", "共起を原因と書かない", "1on1"):
            self.assertIn(phrase, text)

    def test_expected_output_matches_design_sample(self):
        sample = DOC.read_text(encoding="utf-8").split("## 5. 匿名化サンプル", 1)[1]
        sample = re.search(r"```\n(.*?)```", sample, re.S).group(1)
        self.assertEqual((SKILL / "examples" / "expected-output.md").read_text(encoding="utf-8"), sample)

    def test_expected_output_embeds_script_output_verbatim(self):
        # Arrange
        expected = (SKILL / "examples" / "expected-output.md").read_text(encoding="utf-8")
        lines = jm.build_report(_load("jira-cache.sample.json")).split("\n")[1:]
        # Act / Assert
        for line in lines:
            self.assertIn(line, expected)

    def test_expected_output_follows_template_rules(self):
        expected = (SKILL / "examples" / "expected-output.md").read_text(encoding="utf-8")
        self.assertIsNone(BANNED.search(expected))
        self.assertIn("共起", expected)
        self.assertLessEqual(len(re.findall(r"^[①②③]", expected, re.M)), 2)
        self.assertLessEqual(len(expected.split("詳細:", 1)[0]), MAX_BODY_CHARS)

    def test_green_case_has_no_candidates_and_zero_counts(self):
        # Arrange
        expected = (SKILL / "examples" / "expected-green.md").read_text(encoding="utf-8")
        lines = jm.build_report(_load("jira-cache.green.json")).split("\n")[1:]
        # Act / Assert
        for line in lines:
            self.assertIn(line, expected)
        self.assertTrue(expected.startswith("🟢"))
        self.assertIn("解釈の候補: なし", expected)
        self.assertIsNone(BANNED.search(expected))

    def test_small_population_removed_only_is_yellow_without_zero_stale(self):
        # Arrange
        expected = (SKILL / "examples" / "expected-small-removed.md").read_text(encoding="utf-8")
        report = jm.build_report(_load("jira-cache.small-removed.json"))
        # Act / Assert
        for line in report.split("\n")[1:]:
            self.assertIn(line, expected)
        self.assertTrue(expected.startswith("🟡"))
        self.assertNotIn("のうち", expected)  # 更新なしを 0 件扱いにしない
        self.assertIn("解釈の候補: なし", expected)
        self.assertIsNone(BANNED.search(expected))

    def test_all_examples_state_sp_meaning_within_body_limit(self):
        for name in ("expected-output.md", "expected-green.md", "expected-small-removed.md"):
            with self.subTest(name):
                text = (SKILL / "examples" / name).read_text(encoding="utf-8")
                self.assertIn("SP=見積もり値", text.split("\n")[0])
                self.assertLessEqual(len(text.split("詳細:", 1)[0]), MAX_BODY_CHARS)

    def test_incomplete_cache_yields_only_refetch_message(self):
        expected = (SKILL / "examples" / "expected-incomplete.md").read_text(encoding="utf-8").strip()
        self.assertEqual(expected, jm.build_report(_load("jira-cache.incomplete.json")))
        self.assertNotRegex(expected, r"\d")


if __name__ == "__main__":
    unittest.main()
