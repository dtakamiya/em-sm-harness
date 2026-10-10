import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKILL = ROOT / "skills" / "stakeholder-report"
# u_\w+ は Jira/Slack のユーザー ID 風の文字列（実名・実 ID の混入）を弾く意図
BANNED = re.compile(r"送信しました|更新しました|遅い人|おそらく|放置|原因は|u_\w+|https?://")
DATE_OR_COUNT = re.compile(r"\d+日|\d+/\d+")
MAX_BODY_CHARS = 600
CHECKLIST_MARK = "--- 別添: 事実確認リスト ---"


def _expected():
    return (SKILL / "examples" / "expected-output.md").read_text(encoding="utf-8")


def unsourced_numbers(text):
    """Body numbers/dates neither sourced on their line nor listed in the checklist."""
    body, checklist = text.split(CHECKLIST_MARK, 1)
    found = []
    for line in body.splitlines():
        if "⟦EM が決める⟧" in line or "出典" in line:
            continue
        found += [m for m in DATE_OR_COUNT.findall(line) if m not in checklist]
    return found


class StakeholderReportSkillTest(unittest.TestCase):
    def test_frontmatter_and_l1_boundary(self):
        text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
        self.assertTrue(text.startswith("---\nname: stakeholder-report\n"))
        for phrase in ("L1", "書き込み・送信", "R3", "出典未確認", "⟦EM が決める⟧", "共起を原因と書かない"):
            self.assertIn(phrase, text)

    def test_expected_output_follows_template_order_and_banner(self):
        expected = _expected()
        self.assertTrue(expected.startswith("【下書き・未送信】"))
        positions = [expected.index(h) for h in ("■ 現状", "■ 見通し", "■ リスク", "■ ご判断", "⟦EM が決める⟧", CHECKLIST_MARK)]
        self.assertEqual(positions, sorted(positions))
        self.assertIsNone(BANNED.search(expected))

    def test_body_within_limit_and_risks_at_most_three(self):
        expected = _expected()
        self.assertLessEqual(len(expected.split(CHECKLIST_MARK, 1)[0]), MAX_BODY_CHARS)
        risks = expected.split("■ リスク", 1)[1].split("■ ご判断", 1)[0]
        self.assertLessEqual(len(re.findall(r"^- ", risks, re.M)), 3)

    def test_promised_date_stays_in_em_slot_only(self):
        # Arrange
        expected = _expected()
        body = expected.split(CHECKLIST_MARK, 1)[0]
        slot = re.search(r"⟦EM が決める⟧.*", body).group(0)
        # Act
        outside_slot = body.replace(slot, "")
        # Assert
        self.assertIn("10/13", slot)
        self.assertNotIn("10/13", outside_slot)

    def test_unsourced_claim_goes_to_checklist_not_body(self):
        # Arrange
        source = (SKILL / "examples" / "input.sample.md").read_text(encoding="utf-8")
        expected = _expected()
        body, checklist = expected.split(CHECKLIST_MARK, 1)
        # Act / Assert
        self.assertIn("連携先の準備は順調らしい", source)
        self.assertNotIn("連携先の準備", body)
        self.assertIn("出典未確認: 連携先の準備", checklist)

    def test_body_numbers_have_source_or_checklist(self):
        # Arrange
        expected = _expected()
        mistaken = expected.replace("連携テストが遅れる可能性（日数は未確認）", "連携テストが 3日 遅れる可能性")
        # Act / Assert
        self.assertEqual(unsourced_numbers(expected), [])
        self.assertEqual(unsourced_numbers(mistaken), ["3日"])

    def test_every_checklist_line_has_source_and_check_place(self):
        checklist = _expected().split(CHECKLIST_MARK, 1)[1]
        lines = [l for l in checklist.splitlines() if l.startswith("- [ ]")]
        self.assertGreaterEqual(len(lines), 3)
        for line in lines:
            if "出典未確認" in line:
                continue
            self.assertIn("出典=", line)
            self.assertIn("確認=", line)


if __name__ == "__main__":
    unittest.main()
