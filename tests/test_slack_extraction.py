import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SLACK = ROOT / "tests" / "fixtures" / "sample-week" / "slack"
EXPECTED = json.loads((ROOT / "tests" / "fixtures" / "slack-extraction" / "expected.json").read_text(encoding="utf-8"))
KINDS = {"decision", "request", "risk", "blocker", "signal"}
CONFIDENCE = {"high", "medium", "low"}
QUOTE_MAX = 40
COMMON = {"id", "kind", "actors", "observation", "evidence", "confidence", "interpretation_candidates"}
EXTRA = {
    "decision": {"decided_by", "scope_raw", "jira_keys"},
    "request": {"to_em", "due_raw", "answered_in_thread"},
    "risk": set(),
    "blocker": {"blocked_what_raw", "jira_keys"},
    "signal": {"signal_type", "check_hint"},
}
EVALUATIVE = re.compile(r"原因|のせい|能力|やる気|怠|だらしない|疲れている人")
HANDLE = re.compile(r"^(m_[0-9a-f]{6}|em)$")


def anonymized_messages(source):
    text = (SLACK / source).read_text(encoding="utf-8").split("---\n", 2)[2]
    for name, handle in EXPECTED["handles"].items():
        text = re.sub(rf"\b{re.escape(name)}\b", handle, text)
    lines = text.strip().splitlines()
    return [lines[i + 1] for i in range(0, len(lines) - 1, 2)]


class SlackExtractionTest(unittest.TestCase):
    def each_item(self):
        for f in EXPECTED["files"]:
            msgs = anonymized_messages(f["source"])
            for item in f["items"]:
                yield f, msgs, item

    def test_items_have_allowed_shape_per_kind(self):
        for _, _, item in self.each_item():
            self.assertIn(item["kind"], KINDS)
            self.assertIn(item["confidence"], CONFIDENCE)
            self.assertLessEqual(set(item), COMMON | EXTRA[item["kind"]], item["id"])
            self.assertGreaterEqual(set(item), COMMON, item["id"])

    def test_every_quote_is_short_and_found_in_the_anonymized_message(self):
        for _, msgs, item in self.each_item():
            ev = item["evidence"]
            self.assertLessEqual(len(ev["quote"]), QUOTE_MAX, item["id"])
            self.assertIn(ev["quote"], msgs[ev["msg_index"] - 1], item["id"])

    def test_actors_are_handles_only(self):
        for _, _, item in self.each_item():
            ids = [item["actors"]["from"], *item["actors"]["to"], *item.get("decided_by", [])]
            for h in ids:
                self.assertRegex(h, HANDLE, item["id"])

    def test_interpretations_only_for_risk_and_signal_and_signal_has_two(self):
        for _, _, item in self.each_item():
            n = len(item["interpretation_candidates"])
            if item["kind"] == "signal":
                self.assertEqual(n, 2, item["id"])
                self.assertTrue(item["check_hint"])
            elif item["kind"] == "risk":
                self.assertLessEqual(n, 2, item["id"])
            else:
                self.assertEqual(n, 0, item["id"])

    def test_observations_have_no_evaluative_or_causal_words(self):
        for _, _, item in self.each_item():
            texts = [item["observation"], *item["interpretation_candidates"]]
            for t in texts:
                self.assertIsNone(EVALUATIVE.search(t), t)

    def test_to_em_request_requires_explicit_em_and_low_confidence_is_absent(self):
        for _, msgs, item in self.each_item():
            self.assertNotEqual(item["confidence"], "low", item["id"])
            if item["kind"] == "request" and item["to_em"]:
                self.assertEqual(item["actors"]["to"], ["em"])
                self.assertRegex(msgs[item["evidence"]["msg_index"] - 1], r"\bem\b")

    def test_signal_and_risk_are_medium(self):
        for _, _, item in self.each_item():
            if item["kind"] in {"signal", "risk"}:
                self.assertEqual(item["confidence"], "medium", item["id"])

    def test_each_paste_covers_planted_kinds_and_excluded_have_reasons(self):
        kinds = {f["source"]: {i["kind"] for i in f["items"]} for f in EXPECTED["files"]}
        self.assertEqual(kinds["2026-10-05-ex-team-01.md"], {"request", "blocker"})
        self.assertEqual(kinds["2026-10-07-ex-team-02.md"], {"decision", "signal", "risk", "request"})
        for f in EXPECTED["files"]:
            for ex in f["excluded"]:
                self.assertTrue(ex["reason"])


if __name__ == "__main__":
    unittest.main()
