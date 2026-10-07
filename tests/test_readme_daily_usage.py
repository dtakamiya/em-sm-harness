import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
README = (ROOT / "README.md").read_text(encoding="utf-8")
DAILY_SKILLS = ("morning-plan", "slack-to-candidates", "draft-reply", "evening-wrapup", "weekly-review", "proactive-scan")
SCRIPT_RE = re.compile(r"scripts/([a-z_]+\.py)")
FLAG_RE = re.compile(r"(?<![\w-])(--[a-z][a-z-]*)")


def daily_section():
    m = re.search(r"^## 毎日の使い方\n(.*?)(?=^## )", README, re.S | re.M)
    assert m, "README に『毎日の使い方』節がない"
    return m.group(1)


class ReadmeDailyUsageTest(unittest.TestCase):
    def setUp(self):
        self.body = daily_section()

    def test_every_script_mentioned_exists(self):
        scripts = set(SCRIPT_RE.findall(self.body))
        self.assertTrue(scripts)
        for name in scripts:
            self.assertTrue((ROOT / "scripts" / name).is_file(), name)

    def test_every_flag_is_defined_in_some_script(self):
        sources = "".join(p.read_text(encoding="utf-8") for p in (ROOT / "scripts").glob("*.py"))
        for flag in set(FLAG_RE.findall(self.body)):
            self.assertIn(f'"{flag}"', sources, flag)

    def test_all_daily_skills_are_listed_and_exist(self):
        for name in DAILY_SKILLS:
            self.assertIn(f"`{name}`", self.body, name)
            self.assertTrue((ROOT / "skills" / name / "SKILL.md").is_file(), name)

    def test_covers_morning_paste_evening_friday(self):
        for label in ("朝", "Slack を貼った後", "夕方", "金曜"):
            self.assertIn(f"| {label}", self.body, label)

    def test_no_real_data_markers(self):
        self.assertNotRegex(self.body, r"https?://|xox[bp]-|@[\w.-]+\.\w+")

    def test_linked_docs_exist(self):
        for rel in re.findall(r"\]\((docs/[^)#]+)", self.body):
            self.assertTrue((ROOT / rel).is_file(), rel)


if __name__ == "__main__":
    unittest.main()
