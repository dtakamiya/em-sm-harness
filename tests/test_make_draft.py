import copy
import json
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import make_draft as md  # noqa: E402

EXAMPLES = ROOT / "skills" / "draft-reply" / "examples"


def _sample(name):
    return json.loads((EXAMPLES / f"{name}.sample.json").read_text(encoding="utf-8"))


def _with(data, **changes):
    return {**copy.deepcopy(data), **changes}


class MakeDraftTest(unittest.TestCase):
    def setUp(self):
        self.slack = _sample("slack-reply")
        self.jira = _sample("jira-comment")

    def test_render_matches_expected_output_for_both_scenes(self):
        for scene, name in (("slack-reply", "slack-reply"), ("jira-comment", "jira-comment")):
            expected = (EXAMPLES / f"expected-{name}.md").read_text(encoding="utf-8")
            self.assertEqual(md.render(scene, _sample(name)), expected)

    def test_output_is_marked_unsent_and_has_em_decides_slot(self):
        for scene, data in (("slack-reply", self.slack), ("jira-comment", self.jira)):
            text = md.render(scene, data)
            self.assertTrue(text.startswith(md.BANNER))
            self.assertIn("⟦EM が決める⟧", text)

    def test_rejects_unknown_scene_and_type(self):
        with self.assertRaises(md.DraftError):
            md.render("one-on-one", self.slack)
        with self.assertRaises(md.DraftError):
            md.render("slack-reply", _with(self.slack, type="雑談"))

    def test_rejects_three_variants_and_empty_variants(self):
        for variants in (["a", "b", "c"], [], ["  "]):
            with self.assertRaises(md.DraftError):
                md.render("slack-reply", _with(self.slack, variants=variants))

    def test_rejects_sent_phrasing_judgement_and_commitment_words(self):
        for bad in ("送信しました", "おそらく遅れています", "金曜までにお願いします", "私が担当します"):
            with self.assertRaises(md.DraftError, msg=bad):
                md.render("slack-reply", _with(self.slack, variants=[bad]))

    def test_rejects_url_and_non_anonymous_handle(self):
        with self.assertRaises(md.DraftError):
            md.render("slack-reply", _with(self.slack, variants=["https://example.com を見てください"]))
        with self.assertRaises(md.DraftError):
            md.render("slack-reply", _with(self.slack, handle="Taro Yamada"))

    def test_jira_comment_allows_only_one_question_per_variant(self):
        two_questions = ["着手は済んでいますか。見込みはいつですか。"]
        with self.assertRaises(md.DraftError):
            md.render("jira-comment", _with(self.jira, variants=two_questions))

    def test_requires_em_decides_and_valid_source_date(self):
        with self.assertRaises(md.DraftError):
            md.render("slack-reply", _with(self.slack, em_decides=[]))
        with self.assertRaises(md.DraftError):
            md.render("slack-reply", _with(self.slack, source_date="10/5"))

    def test_write_draft_never_overwrites_existing_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            first = md.write_draft(out, "slack-reply", "a", date(2026, 10, 6))
            second = md.write_draft(out, "slack-reply", "b", date(2026, 10, 6))
            self.assertEqual((first.name, second.name), ("2026-10-06-slack-reply-01.md", "2026-10-06-slack-reply-02.md"))
            self.assertEqual(first.read_text(encoding="utf-8"), "a")
            self.assertEqual(list(out.glob("*.tmp")), [])

    def test_main_writes_nothing_when_validation_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "bad.json"
            bad.write_text(json.dumps(_with(self.slack, variants=["送信しました"])), encoding="utf-8")
            out = Path(tmp) / "out"
            self.assertEqual(md.main(["slack-reply", str(bad), "--out-dir", str(out)]), 1)
            self.assertFalse(out.exists())

    def test_main_reports_broken_json_without_writing(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "bad.json"
            bad.write_text("{", encoding="utf-8")
            self.assertEqual(md.main(["slack-reply", str(bad), "--out-dir", str(Path(tmp) / "out")]), 1)


if __name__ == "__main__":
    unittest.main()
