import re
import unittest
from pathlib import Path

DOC = Path(__file__).resolve().parent.parent / "docs" / "design" / "21-approval-queue.md"
BANNER = "【下書き・未送信】"
MAX_ITEMS = 5
MAX_SAMPLE_CHARS = 900
SENSITIVE = re.compile(r"https?://|@[\w.-]+\.(com|jp)|xox[bp]-|token", re.I)
BANNED = re.compile(r"送信しました|更新しました|送りました")


def blocks(text):
    return re.findall(r"^```[^\n]*\n(.*?)^```", text, re.S | re.M)


class ApprovalQueueDocTest(unittest.TestCase):
    def setUp(self):
        self.text = DOC.read_text(encoding="utf-8")
        found = blocks(self.text)
        self.assertEqual(len(found), 2)
        self.template, self.sample = found

    def test_template_and_sample_have_all_sections(self):
        for block in (self.template, self.sample):
            self.assertIn(BANNER, block)
            for heading in ["■ 個別承認", "■ 一括確認", "■ 期限切れ", "あなたがやること"]:
                self.assertIn(heading, block)

    def test_sample_individual_items_within_limit(self):
        individual = self.sample.split("■ 個別承認")[1].split("■ 一括確認")[0]
        items = re.findall(r"^\d+\. ", individual, re.M)
        self.assertGreaterEqual(len(items), 1)
        self.assertLessEqual(len(items), MAX_ITEMS)

    def test_each_individual_item_has_commit_slot(self):
        individual = self.sample.split("■ 個別承認")[1].split("■ 一括確認")[0]
        self.assertEqual(len(re.findall(r"^\d+\. ", individual, re.M)), individual.count("⟦EM が決める⟧"))

    def test_bulk_section_has_no_commit_slot(self):
        bulk = self.sample.split("■ 一括確認")[1].split("■ 期限切れ")[0]
        self.assertNotIn("⟦EM", bulk)

    def test_sample_counts_match_header(self):
        header = re.search(r"要判断 (\d+) 件 / 一括確認 (\d+) 件 / 期限切れ (\d+) 件", self.sample)
        self.assertIsNotNone(header)
        review, bulk, expired = map(int, header.groups())
        individual = self.sample.split("■ 個別承認")[1].split("■ 一括確認")[0]
        bulk_text = self.sample.split("■ 一括確認")[1].split("■ 期限切れ")[0]
        expired_text = self.sample.split("■ 期限切れ")[1]
        self.assertEqual(review, len(re.findall(r"^\d+\. ", individual, re.M)))
        self.assertEqual(bulk, len(re.findall(r"^- \[ \]", bulk_text, re.M)))
        self.assertEqual(expired, len(re.findall(r"^- ", expired_text, re.M)))

    def test_sample_is_short_and_clean(self):
        self.assertLessEqual(len(self.sample), MAX_SAMPLE_CHARS)
        self.assertIsNone(SENSITIVE.search(self.text))
        self.assertIsNone(BANNED.search(self.sample))

    def test_detection_table_covers_commit_and_non_commit(self):
        for word in ["非コミット", "コミット（A）", "コミット（B）", "コミット（C）"]:
            self.assertIn(word, self.text)
        self.assertIn("判定不能は **コミット扱い**", self.text)

    def test_deadline_request_is_defined_as_stage_a(self):
        self.assertIn("相手に期限を課す依頼", self.text)
        self.assertIn("Q-025", self.text)
        self.assertIn("未決事項・受け入れ基準", self.text)


if __name__ == "__main__":
    unittest.main()
