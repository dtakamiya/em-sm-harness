import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import sprint_planning as sp  # noqa: E402

SKILL = ROOT / "skills" / "sprint-planning"
FIXTURES = ROOT / "tests" / "fixtures" / "sprint-planning"
EXAMPLES = SKILL / "examples"


def _load(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _banner_less(text):
    return text.split("\n", 1)[1]


class SprintPlanningSkillTest(unittest.TestCase):
    def test_frontmatter_and_boundaries(self):
        text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
        self.assertTrue(text.startswith("---\nname: sprint-planning\n"))
        for phrase in ("L1", "書き込み・送信", "一字一句そのまま", "再取得が必要", "約束ではない", "S4", "morning-plan", "P1〜P6"):
            self.assertIn(phrase, text)

    def test_examples_match_script_output(self):
        cache = _load("jira-cache.planning.json")
        cases = {
            "expected-output.md": _banner_less(sp.build_material(cache, _load("done-sp.three.json"), 9)),
            "expected-short-history.md": _banner_less(sp.build_material(cache, _load("done-sp.two.json"), None)),
            "expected-incomplete.md": sp.build_material(_load("jira-cache.incomplete.json")),
        }
        for name, actual in cases.items():
            with self.subTest(name):
                self.assertEqual((EXAMPLES / name).read_text(encoding="utf-8").rstrip("\n"), actual)

    def test_design_sample_body_equals_script_body(self):
        design = (ROOT / "docs" / "design" / "33-sprint-planning-material.md").read_text(encoding="utf-8")
        sample = design.split("## 5. 出力の型", 1)[1].split("```\n")[1].split("\n")
        body = _banner_less(sp.build_material(_load("jira-cache.planning.json"), _load("done-sp.three.json"), 9))
        self.assertEqual(sample[:-2], body.split("\n\n詳細\n")[0].split("\n"))


if __name__ == "__main__":
    unittest.main()
