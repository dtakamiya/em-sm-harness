import re
import unittest
from pathlib import Path

DIR = Path(__file__).resolve().parent.parent / "templates" / "drafts"
TEMPLATES = ["slack-reply", "one-on-one-agenda", "sprint-status-summary", "stakeholder-report", "jira-comment", "meeting-minutes", "retro-facilitation"]
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
        for name in ["one-on-one-agenda", "sprint-status-summary", "retro-facilitation"]:
            sample = blocks(self.read(name))[1]
            for word in FACT_INTERP:
                self.assertIn(word, sample, name)

    def test_interpretations_at_most_two_and_cooccurrence_noted(self):
        for name in ["one-on-one-agenda", "sprint-status-summary", "retro-facilitation"]:
            sample = blocks(self.read(name))[1]
            self.assertLessEqual(len(re.findall(r"^\s*[①②③④]", sample, re.M)), 2, name)
            self.assertIn("共起", sample, name)

    def test_meeting_minutes_has_three_headings(self):
        text = self.read("meeting-minutes")
        for heading in ["■ 決定事項", "■ 未決事項", "■ アクション"]:
            self.assertIn(heading, blocks(text)[0])
            self.assertIn(heading, blocks(text)[1])

    def test_retro_time_allocation_sums_to_total(self):
        for block in blocks(self.read("retro-facilitation")):
            total = re.search(r"（(\d+)分）", block)
            parts = re.findall(r"(\d+)分 ", block)
            if total is None or not parts:
                total, parts = re.search(r"（\{分\}分）", block), re.findall(r"\{分\}分 ", block)
                self.assertTrue(total and parts, "template placeholders")
                continue
            self.assertEqual(sum(map(int, parts)), int(total.group(1)))

    def test_sample_is_short_enough_to_read(self):
        for name in TEMPLATES:
            self.assertLessEqual(len(blocks(self.read(name))[1]), MAX_SAMPLE_CHARS, name)


class OneOnOneAgendaTest(unittest.TestCase):
    """emh-047: 1on1 テンプレを 14（A/B/D）と 22 §1（Jira 指標を入力にしない）で検証する。"""

    JIRA_DERIVED = re.compile(r"jira_metrics|In Progress|他チケット|平均|中央値|サイクルタイム|ベロシティ|\bSP\b|ランキング順")

    def sample(self):
        return blocks((DIR / "one-on-one-agenda.md").read_text(encoding="utf-8"))[1]

    def test_second_line_has_conclusion_and_em_action(self):
        for block in blocks((DIR / "one-on-one-agenda.md").read_text(encoding="utf-8")):
            self.assertRegex(block.split("\n")[1], r"^結論: .*EM がやること")

    def test_observations_and_questions_within_limits(self):
        sample = self.sample()
        observations = sample.split("2. 観察（事実）")[1].split("3. 解釈の候補")[0]
        questions = sample.split("4. 聞く問い")[1].split("5. 相手のターン")[0]
        self.assertLessEqual(len(re.findall(r"^\s+- ", observations, re.M)), 3)
        self.assertLessEqual(len(re.findall(r"^\s+- ", questions, re.M)), 3)

    def test_sample_does_not_use_jira_derived_comparisons(self):
        self.assertIsNone(self.JIRA_DERIVED.search(self.sample()))

    def test_template_declares_jira_metrics_are_not_input(self):
        text = (DIR / "one-on-one-agenda.md").read_text(encoding="utf-8")
        self.assertIn("Jira 指標", text.split("## 必須項目")[0])
        self.assertIn("入力にしない", text.split("## 必須項目")[0])


if __name__ == "__main__":
    unittest.main()
