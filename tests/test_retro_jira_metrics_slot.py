import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import jira_metrics as jm  # noqa: E402

TEMPLATE = ROOT / "templates" / "drafts" / "retro-facilitation.md"
FIXTURE = ROOT / "tests" / "fixtures" / "jira-metrics" / "jira-cache.sample.json"
PERSON_ORDER = re.compile(r"assignee_ref|u_\w+|担当者別|ランキング")


def _sample():
    text = TEMPLATE.read_text(encoding="utf-8")
    section = text.split("## 匿名化サンプル", 1)[1]
    return re.search(r"```\n(.*?)```", section, re.S).group(1)


def _report_lines():
    return jm.build_report(json.loads(FIXTURE.read_text(encoding="utf-8"))).split("\n")


class RetroJiraMetricsSlotTest(unittest.TestCase):
    def test_sample_metric_lines_match_script_output_verbatim(self):
        # Arrange
        lines, sample = _report_lines(), _sample()
        # Act / Assert（先頭の試作バナー行と限界行は除く。観察行は「指標:」に続けて貼る）
        observation = [ln for ln in lines[1:] if not ln.startswith("限界")]
        self.assertIn("指標: " + observation[0], sample)
        for line in observation[1:]:
            self.assertIn(line, sample)

    def test_limits_line_goes_to_detail_not_body(self):
        sample = _sample()
        body, detail = sample.split("詳細（限界）:", 1)
        self.assertNotIn("限界:", body)
        self.assertIn("updated 基準", detail)
        self.assertNotIn("■", detail)  # 末尾配置（以降に見出しが来ない）

    def test_template_documents_slot_rules(self):
        text = TEMPLATE.read_text(encoding="utf-8")
        for phrase in ("そのまま貼る", "complete: false", "1on1 には流用しない", "担当者別の並びは出さない"):
            self.assertIn(phrase, text)

    def test_sample_has_no_person_breakdown(self):
        self.assertIsNone(PERSON_ORDER.search(_sample()))


if __name__ == "__main__":
    unittest.main()
