import copy
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import make_draft as md  # noqa: E402

EXAMPLES = ROOT / "skills" / "draft-reply" / "examples"
SCENE = "one-on-one-agenda"


def _sample():
    return json.loads((EXAMPLES / f"{SCENE}.sample.json").read_text(encoding="utf-8"))


def _with(**changes):
    return {**copy.deepcopy(_sample()), **changes}


class AgendaDraftTest(unittest.TestCase):
    def test_render_matches_expected_output(self):
        expected = (EXAMPLES / f"expected-{SCENE}.md").read_text(encoding="utf-8")
        self.assertEqual(md.render(SCENE, _sample()), expected)

    def test_output_is_unsent_and_conclusion_is_on_second_line(self):
        lines = md.render(SCENE, _sample()).split("\n")
        self.assertTrue(lines[0].startswith(md.BANNER))
        self.assertRegex(lines[1], r"^結論: .*EM がやること")
        self.assertIn("⟦EM だけが扱う⟧", "\n".join(lines))

    def test_interpretations_are_capped_at_two(self):  # D-002
        extra = {"candidate": "担当が偏っていた可能性", "check": "直近の依頼元"}
        three = _sample()["interpretations"] + [extra]
        with self.assertRaises(md.DraftError):
            md.render(SCENE, _with(interpretations=three))
        self.assertEqual(len(_sample()["interpretations"]), md.MAX_INTERPRETATIONS)

    def test_interpretation_must_not_assert(self):
        bad = [{"candidate": "見積もりが甘かった", "check": "当初の想定"}]
        with self.assertRaises(md.DraftError):
            md.render(SCENE, _with(interpretations=bad))

    def test_observations_and_questions_are_capped_at_three(self):
        obs = _sample()["observations"] * 2
        with self.assertRaises(md.DraftError):
            md.render(SCENE, _with(observations=obs))
        with self.assertRaises(md.DraftError):
            md.render(SCENE, _with(questions=["a？", "b？", "c？", "d？"]))

    def test_observations_are_required_and_zero_interpretations_is_allowed(self):
        with self.assertRaises(md.DraftError):
            md.render(SCENE, _with(observations=[]))
        text = md.render(SCENE, _with(interpretations=[]))
        self.assertIn("なし（観察のみ）", text)
        self.assertNotIn("共起", text)

    def test_rejects_jira_derived_comparisons(self):
        obs = [{"fact": "他チケットより滞留が長い", "source": "tasks の EX-12"}]
        with self.assertRaises(md.DraftError):
            md.render(SCENE, _with(observations=obs))

    def test_rejects_evaluation_words_non_anonymous_handle_and_bad_status(self):
        obs = [{"fact": "やる気がない発言", "source": "貼り付け 10/6"}]
        with self.assertRaises(md.DraftError):
            md.render(SCENE, _with(observations=obs))
        with self.assertRaises(md.DraftError):
            md.render(SCENE, _with(handle="Taro Yamada"))
        carry = [{"action": "手順書", "source_date": "2026-09-25", "status": "遅延"}]
        with self.assertRaises(md.DraftError):
            md.render(SCENE, _with(carryovers=carry))

    def test_cannot_forge_template_headings(self):
        with self.assertRaises(md.DraftError):
            md.render(SCENE, _with(em_only="■ 案A"))


if __name__ == "__main__":
    unittest.main()
