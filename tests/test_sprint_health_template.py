import copy
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
# 禁止語の走査はサンプル（人に見せる本文）だけが対象。設計書の説明文には規則の引用として「🔴」「放置」等が正当に出る
BANNED = re.compile(r"送信しました|更新しました|遅い|やる気がない|おそらく|放置|原因は|assignee_ref|u_\w+|🔴")
MAX_BODY_CHARS = 600  # 14 A2（詳細行を除く本文）


def _sample():
    text = DOC.read_text(encoding="utf-8")
    section = text.split("## 5. 匿名化サンプル", 1)[1]
    return re.search(r"```\n(.*?)```", section, re.S).group(1)


def _report_lines():
    cache = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return jm.build_report(cache).split("\n")


def health_state(report):
    """31 §2 の規則: 更新なし・追加・除外のどれかが 1 件以上なら 🟡。N<5 で更新なしが出ていなければ 0 扱いにせず追加・除外だけで判定。"""
    counts = [int(n) for m in re.findall(r"のうち (\d+) 件が|追加 (\d+) 件|除外 (\d+) 件", report) for n in m if n]
    return "🟡" if any(counts) else "🟢"


class SprintHealthTemplateTest(unittest.TestCase):
    def test_observation_lines_match_script_output_verbatim(self):
        # Arrange
        lines, sample = _report_lines(), _sample()
        # Act / Assert（先頭の試作バナー行は除く。限界行は「詳細」に全文）
        for line in lines[1:]:
            self.assertIn(line, sample)

    def test_sample_state_word_follows_count_rule(self):
        self.assertEqual(_sample()[0], health_state("\n".join(_report_lines())))

    def test_state_rule_on_minimal_caches(self):
        # Arrange: 進行中 5 件・全件新しく、スコープ変動なし／N<5 で除外のみ／更新なし 1 件
        base = json.loads(FIXTURE.read_text(encoding="utf-8"))
        fresh = [dict(i, updated="2026-10-08", transitions=[], sprints=[s for s in i["sprints"] if s["state"] == "active"]) for i in base["issues"][:5]]
        green = dict(base, issues=fresh, issue_count=5)
        removed = {**fresh[0], "transitions": [{"field": "sprint", "from": "Sprint 11", "to": "Sprint 12", "at": "2026-10-02"}]}
        removed_only = dict(base, issues=[removed] + fresh[1:4], issue_count=4)  # 進行中 4 件（N<5）
        stale_only = dict(base, issues=[dict(fresh[0], updated="2026-09-28")] + fresh[1:], issue_count=5)
        cases = [("更新なし0・追加0・除外0", green, "🟢"), ("N<5・除外のみ", removed_only, "🟡"), ("更新なしのみ", stale_only, "🟡")]
        for label, cache, expected in cases:
            with self.subTest(label):
                # Act / Assert
                self.assertEqual(health_state(jm.build_report(cache)), expected)
        self.assertNotIn("のうち", jm.build_report(removed_only))  # N<5 は更新なしの件数を出さない（0 扱いにしない）

    def test_doc_states_n_under_5_and_removed_only_rules(self):
        text = DOC.read_text(encoding="utf-8")
        for phrase in ("更新なしを 0 件扱いにしない", "解釈の候補を出さない", "先頭の試作バナー行を除く"):
            self.assertIn(phrase, text)

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
