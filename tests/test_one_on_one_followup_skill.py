import io
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKILL = ROOT / "skills" / "one-on-one-followup"
sys.path.insert(0, str(ROOT / "scripts"))
import one_on_one_followup as ooo  # noqa: E402

BANNED_WORDS = ("遅れ", "怠", "サボ", "優秀", "問題あり", "停滞している", "評価", "送信しました", "更新しました")


def _run_sample_command():
    """SKILL.md の「試す」に書かれたコマンドの引数をそのまま実行して標準出力を返す。"""
    text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    line = next(l for l in text.splitlines() if l.startswith("`python3 scripts/one_on_one_followup.py"))
    args = line.split("`")[1].split()[2:]
    args = [str(ROOT / a) if a.startswith("skills/") else a for a in args]
    buf = io.StringIO()
    with redirect_stdout(buf):
        ooo.main(args)
    return buf.getvalue()


class OneOnOneFollowupSkillTest(unittest.TestCase):
    def test_frontmatter_and_boundaries(self):
        text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
        self.assertTrue(text.startswith("---\nname: one-on-one-followup\n"))
        for phrase in ("L0", "毎回", "保存せず", "Q-017", "実名", "書き込み・送信", "全部完了"):
            self.assertIn(phrase, text)

    def test_try_it_command_reproduces_expected_output(self):
        expected = (SKILL / "examples" / "expected-output.md").read_text(encoding="utf-8")
        self.assertEqual(_run_sample_command().strip(), expected.strip())

    def test_expected_output_has_no_evaluative_words(self):
        expected = (SKILL / "examples" / "expected-output.md").read_text(encoding="utf-8")
        self.assertEqual([w for w in BANNED_WORDS if w in expected], [])

    def test_readme_lists_skill_but_not_in_daily_table(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        daily = readme.split("## 毎日の使い方", 1)[1].split("\n\n", 2)[1]
        self.assertIn("`one-on-one-followup`", readme)
        self.assertNotIn("one_on_one_followup", daily)

    def test_sample_is_synthetic(self):
        sample = (SKILL / "examples" / "tasks.sample.json").read_text(encoding="utf-8")
        self.assertNotRegex(sample, r"https?://|xox[bp]-|@[\w.-]+\.\w+")


if __name__ == "__main__":
    unittest.main()
