import re
import unittest
from pathlib import Path

DIR = Path(__file__).resolve().parent.parent / "templates" / "drafts"
TEMPLATES = ["slack-reply", "one-on-one-agenda", "sprint-status-summary", "stakeholder-report", "jira-comment"]
SECTIONS = ["## 必須項目", "## テンプレ", "## EM が直す手間を減らす工夫", "## 匿名化サンプル"]
BANNER = "【下書き・未送信】"
COMMIT_SLOT = "⟦EM"
BANNED = re.compile(r"送信しました|更新しました|送りました|遅い人|やる気がない|低パフォーマー|おそらく")
SENSITIVE = re.compile(r"https?://|@[\w.-]+\.(com|jp)|xox[bp]-|token", re.I)
FACT_INTERP = ["観察", "解釈の候補"]
MAX_SAMPLE_CHARS = 700


def blocks(text):
    return re.findall(r"```\n(.*?)```", text, re.S)


class DraftTemplateTest(unittest.TestCase):
    def read(self, name):
        return (DIR / f"{name}.md").read_text(encoding="utf-8")

    def test_required_sections_present(self):
        for name in TEMPLATES:
            text = self.read(name)
            for section in SECTIONS:
                self.assertIn(section, text, f"{name}: {section}")

    def test_template_and_sample_are_marked_unsent(self):
        for name in TEMPLATES:
            found = blocks(self.read(name))
            self.assertEqual(len(found), 2, name)
            for block in found:
                self.assertIn(BANNER, block, name)
                self.assertIn(COMMIT_SLOT, block, name)

    def test_sample_has_no_banned_or_sensitive_text(self):
        for name in TEMPLATES:
            text = self.read(name)
            self.assertIsNone(BANNED.search(blocks(text)[1]), name)
            self.assertIsNone(SENSITIVE.search(text), name)

    def test_people_related_templates_separate_fact_and_interpretation(self):
        for name in ["one-on-one-agenda", "sprint-status-summary"]:
            sample = blocks(self.read(name))[1]
            for word in FACT_INTERP:
                self.assertIn(word, sample, name)

    def test_interpretations_at_most_two_and_cooccurrence_noted(self):
        for name in ["one-on-one-agenda", "sprint-status-summary"]:
            sample = blocks(self.read(name))[1]
            self.assertLessEqual(len(re.findall(r"^\s*[①②③④]", sample, re.M)), 2, name)
            self.assertIn("共起", sample, name)

    def test_sample_is_short_enough_to_read(self):
        for name in TEMPLATES:
            self.assertLessEqual(len(blocks(self.read(name))[1]), MAX_SAMPLE_CHARS, name)


if __name__ == "__main__":
    unittest.main()
