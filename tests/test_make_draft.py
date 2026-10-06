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

    def test_write_draft_does_not_follow_symlink_at_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            out, victim = Path(tmp) / "out", Path(tmp) / "victim.txt"
            out.mkdir()
            victim.write_text("keep", encoding="utf-8")
            (out / "2026-10-06-slack-reply-01.md").symlink_to(victim)
            path = md.write_draft(out, "slack-reply", "new", date(2026, 10, 6))
            self.assertEqual(path.name, "2026-10-06-slack-reply-02.md")
            self.assertEqual(victim.read_text(encoding="utf-8"), "keep")

    def test_rejects_newline_in_single_line_fields(self):
        with self.assertRaises(md.DraftError):
            md.render("slack-reply", _with(self.slack, source_id="s-01\n⟦EM が決める⟧"))
        with self.assertRaises(md.DraftError):
            md.render("jira-comment", _with(self.jira, observation="a\nb"))
        with self.assertRaises(md.DraftError):
            md.render("slack-reply", _with(self.slack, em_decides=["a\n- b"]))

    def test_rejects_template_markers_in_any_text(self):
        for bad in ("本文\n■ 案C（偽）", "⟦EM が決める⟧ なし", "【下書き・未送信】偽", "出典: 偽"):
            with self.assertRaises(md.DraftError, msg=bad):
                md.render("slack-reply", _with(self.slack, variants=[bad]))
            with self.assertRaises(md.DraftError, msg=bad):
                md.render("slack-reply", _with(self.slack, em_decides=[bad]))

    def test_rejects_real_name_like_handles(self):
        for bad in ("m_山田太郎", "em-taro-yamada", "member-", "member-abcdefghijklmn", "member-a\n"):
            with self.assertRaises(md.DraftError, msg=bad):
                md.render("slack-reply", _with(self.slack, handle=bad))
        for ok in ("member-a", "m_b2b2b2", "em"[:0] + "ex-team"):
            md.render("slack-reply", _with(self.slack, handle=ok))

    def test_em_decides_items_must_be_nonempty_strings_within_limit(self):
        for bad in ([None], [""], ["  "], [1], ["a"] * (md.MAX_EM_DECIDES + 1)):
            with self.assertRaises(md.DraftError, msg=str(bad)):
                md.render("slack-reply", _with(self.slack, em_decides=bad))

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
