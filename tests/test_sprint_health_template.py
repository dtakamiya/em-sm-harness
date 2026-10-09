import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import jira_metrics as jm  # noqa: E402

DOC = ROOT / "docs" / "design" / "31-sprint-health-template.md"
FIXTURE = ROOT / "tests" / "fixtures" / "jira-metrics" / "jira-cache.sample.json"
BANNED = re.compile(r"送信しました|更新しました|遅い|やる気がない|おそらく|放置|原因は|assignee_ref|u_\w+|🔴")
MAX_BODY_CHARS = 600  # 14 A2（詳細行を除く本文）


def _sample():
    text = DOC.read_text(encoding="utf-8")
    section = text.split("## 5. 匿名化サンプル", 1)[1]
    return re.search(r"```\n(.*?)```", section, re.S).group(1)


def _report_lines():
    cache = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return jm.build_report(cache).split("\n")


class SprintHealthTemplateTest(unittest.TestCase):
    def test_observation_lines_match_script_output_verbatim(self):
        # Arrange
        lines, sample = _report_lines(), _sample()
        # Act / Assert（先頭の試作バナー行は除く。限界行は「詳細」に全文）
        for line in lines[1:]:
            self.assertIn(line, sample)

    def test_state_word_follows_count_rule(self):
        # Arrange（更新なし・追加・除外のどれかが 1 件以上なら 🟡）
        report = "\n".join(_report_lines())
        counts = [int(n) for m in re.findall(r"のうち (\d+) 件が|追加 (\d+) 件|除外 (\d+) 件", report) for n in m if n]
        # Act
        first = _sample().splitlines()[0]
        # Assert
        self.assertEqual(len(counts), 3)
        self.assertEqual(first[0], "🟡" if any(counts) else "🟢")

    def test_sample_has_two_candidates_cooccurrence_and_no_banned_words(self):
        sample = _sample()
        self.assertLessEqual(len(re.findall(r"^[①②③]", sample, re.M)), 2)
        self.assertIn("共起", sample)
        self.assertIsNone(BANNED.search(sample))

    def test_sample_body_is_short_enough_to_read(self):
        body = _sample().split("詳細:", 1)[0]
        self.assertLessEqual(len(body), MAX_BODY_CHARS)

    def test_incomplete_cache_yields_only_refetch_message(self):
        cache = json.loads((FIXTURE.parent / "jira-cache.incomplete.json").read_text(encoding="utf-8"))
        self.assertEqual(jm.build_report(cache), jm.REFETCH_MESSAGE)


if __name__ == "__main__":
    unittest.main()
