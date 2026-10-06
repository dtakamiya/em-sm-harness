import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures" / "meeting-notes"
EXPECTED = json.loads((FIXTURES / "expected.json").read_text(encoding="utf-8"))
KINDS = {"decision", "action_item", "open_question"}
CONFIDENCE = {"high", "medium", "low"}
QUOTE_MAX = 40
COMMON = {"id", "kind", "observation", "evidence", "confidence"}
EXTRA = {
    "decision": {"decided_by", "jira_keys"},
    "action_item": {"owner", "to_em", "due_raw"},
    "open_question": {"asked_of", "needs_em"},
}
HANDLE = re.compile(r"^(m_[0-9a-f]{6}|em)$")
ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
EVALUATIVE = re.compile(r"原因|のせい|能力|やる気|怠|だらしない")
RAW_NAME = re.compile(r"member-[a-z]")
CANDIDATE_CONFIDENCE = ("high", "medium")


def body_lines(source):
    """front matter を除いた空でない行（見出し行を含む）。evidence.line はこの 1 始まりの番号。"""
    text = (FIXTURES / source).read_text(encoding="utf-8").split("---\n", 2)[2]
    return [ln for ln in text.splitlines() if ln.strip()]


def anonymized(lines):
    out = []
    for ln in lines:
        for name, handle in EXPECTED["handles"].items():
            ln = re.sub(rf"\b{re.escape(name)}\b", handle, ln)
        out.append(ln)
    return out


def derive_candidates(source, items):
    """設計 28 §7 の規則: EM 本人の action_item のうち confidence が high/medium のものだけ。"""
    return [{"source_ref": f"{source}:{i['id']}",
             "suggested_due": i["due_raw"] if ISO_DATE.match(i["due_raw"] or "") else None}
            for i in items
            if i["kind"] == "action_item" and i["owner"] == "em" and i["to_em"] is True
            and i["confidence"] in CANDIDATE_CONFIDENCE]


class MeetingExtractionTest(unittest.TestCase):
    def each_file(self):
        for f in EXPECTED["files"]:
            yield f, anonymized(body_lines(f["source"]))

    def test_items_have_exact_shape_per_kind(self):
        for f, _ in self.each_file():
            for item in f["items"]:
                self.assertIn(item["kind"], KINDS)
                self.assertIn(item["confidence"], CONFIDENCE)
                self.assertEqual(set(item), COMMON | EXTRA[item["kind"]], item["id"])

    def test_every_quote_is_short_and_found_in_the_anonymized_line(self):
        for f, lines in self.each_file():
            for item in f["items"]:
                ev = item["evidence"]
                self.assertLessEqual(len(ev["quote"]), QUOTE_MAX, item["id"])
                self.assertIn(ev["quote"], lines[ev["line"] - 1], item["id"])

    def test_people_fields_are_handles_only(self):
        for f, _ in self.each_file():
            for item in f["items"]:
                people = [*item.get("decided_by", []), *item.get("asked_of", [])]
                if item["kind"] == "action_item" and item["owner"] is not None:
                    people.append(item["owner"])
                for h in people:
                    self.assertRegex(h, HANDLE, item["id"])
                self.assertIsNone(RAW_NAME.search(item["observation"]), item["id"])

    def test_observations_have_no_evaluative_or_causal_words(self):
        for f, _ in self.each_file():
            for item in f["items"]:
                self.assertIsNone(EVALUATIVE.search(item["observation"]), item["id"])

    def test_no_note_line_is_dropped(self):
        for f, lines in self.each_file():
            covered = {i["evidence"]["line"] for i in f["items"]} | {e["line"] for e in f["excluded"]}
            content = {n for n, ln in enumerate(lines, 1) if not ln.startswith("#")}
            self.assertEqual(content, covered, f["source"])
            for ex in f["excluded"]:
                self.assertTrue(ex["reason"])

    def test_unreadable_owner_is_low_and_never_a_candidate(self):
        for f, _ in self.each_file():
            refs = {c["source_ref"] for c in f["candidates"]}
            for item in f["items"]:
                if item["kind"] == "action_item" and item["owner"] is None:
                    self.assertEqual(item["confidence"], "low", item["id"])
                    self.assertFalse(item["to_em"], item["id"])
                if item["confidence"] == "low":
                    self.assertNotIn(f"{f['source']}:{item['id']}", refs, item["id"])

    def test_candidates_are_exactly_the_em_action_items(self):
        for f, _ in self.each_file():
            self.assertEqual(derive_candidates(f["source"], f["items"]), f["candidates"], f["source"])
            self.assertTrue(f["candidates"], f["source"])

    def test_medium_em_action_flows_to_candidates(self):
        items = [i for f in EXPECTED["files"] for i in f["items"]]
        medium = [i for i in items if i["kind"] == "action_item" and i["confidence"] == "medium" and i["owner"] == "em"]
        self.assertTrue(medium)
        refs = {c["source_ref"] for f in EXPECTED["files"] for c in f["candidates"]}
        for f in EXPECTED["files"]:
            for i in f["items"]:
                if i in medium:
                    self.assertIn(f"{f['source']}:{i['id']}", refs)

    def test_needs_em_true_only_when_em_is_named_in_the_line(self):
        found = False
        for f, lines in self.each_file():
            for i in f["items"]:
                if i["kind"] == "open_question" and i["needs_em"]:
                    found = True
                    self.assertEqual(i["asked_of"], ["em"])
                    self.assertRegex(lines[i["evidence"]["line"] - 1], r"\bem\b")
        self.assertTrue(found)

    def test_fixture_notes_contain_only_fictional_handles_and_no_urls(self):
        for f in EXPECTED["files"]:
            text = (FIXTURES / f["source"]).read_text(encoding="utf-8")
            for name in RAW_NAME.findall(text):
                self.assertIn(name, EXPECTED["handles"])
            self.assertNotRegex(text, r"https?://")


if __name__ == "__main__":
    unittest.main()
