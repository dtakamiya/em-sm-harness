import io
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKILL = ROOT / "skills" / "one-on-one-agenda" / "SKILL.md"
sys.path.insert(0, str(ROOT / "scripts"))
import make_draft as md  # noqa: E402


class OneOnOneAgendaSkillTest(unittest.TestCase):
    def test_frontmatter_and_boundaries(self):
        text = SKILL.read_text(encoding="utf-8")
        self.assertTrue(text.startswith("---\nname: one-on-one-agenda\n"))
        for phrase in ("L1", "one-on-one-followup", "Jira 指標", "最大 2 つ", "共起", "書き込み・送信", "⟦EM だけが扱う⟧"):
            self.assertIn(phrase, text)

    def test_try_it_command_reproduces_expected_output(self):
        text = SKILL.read_text(encoding="utf-8")
        line = next(l for l in text.splitlines() if l.startswith("`python3 scripts/make_draft.py"))
        args = [str(ROOT / a) if a.startswith("skills/") else a for a in line.split("`")[1].split()[2:]]
        buf = io.StringIO()
        with redirect_stdout(buf):
            self.assertEqual(md.main(args), 0)
        expected = (ROOT / "skills" / "draft-reply" / "examples" / "expected-one-on-one-agenda.md").read_text(encoding="utf-8")
        self.assertEqual(buf.getvalue(), expected)

    def test_skill_limits_match_script_constants(self):
        self.assertEqual((md.MAX_OBSERVATIONS, md.MAX_INTERPRETATIONS, md.MAX_QUESTIONS), (3, 2, 3))

    def test_draft_reply_skill_no_longer_says_one_on_one_is_unsupported(self):
        text = (ROOT / "skills" / "draft-reply" / "SKILL.md").read_text(encoding="utf-8")
        self.assertNotIn("1on1・報告", text)


if __name__ == "__main__":
    unittest.main()
