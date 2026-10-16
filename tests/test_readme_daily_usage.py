import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
README = (ROOT / "README.md").read_text(encoding="utf-8")
DAILY_SKILLS = ("morning-plan", "slack-to-candidates", "draft-reply", "evening-wrapup", "weekly-review", "proactive-scan")
sys.path.insert(0, str(ROOT / "scripts"))
import proactive_scan  # noqa: E402

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

    def test_flags_exist_in_the_script_on_the_same_line(self):
        checked = 0
        for line in self.body.splitlines():
            # 1行=1表の行。各 `python3 scripts/X.py ...` の断片ごとに、そのスクリプト内のフラグだけを照合する
            for script, args in re.findall(r"python3 scripts/([a-z_]+\.py)([^`]*)`", line):
                source = (ROOT / "scripts" / script).read_text(encoding="utf-8")
                for flag in FLAG_RE.findall(args):
                    self.assertIn(f'"{flag}"', source, f"{script} に {flag} がない")
                    checked += 1
            # 「→ 問題なければ `--dry-run` を外す」のような後続のフラグは、行内の直前のスクリプトに対して見る
            for flag in FLAG_RE.findall(line):
                scripts = re.findall(r"scripts/([a-z_]+\.py)", line)
                self.assertTrue(
                    any(f'"{flag}"' in (ROOT / "scripts" / sc).read_text(encoding="utf-8") for sc in scripts),
                    f"{flag} を持つスクリプトがこの行にない",
                )
        self.assertGreater(checked, 0)

    def test_all_daily_skills_are_listed_and_exist(self):
        for name in DAILY_SKILLS:
            self.assertIn(f"`{name}`", self.body, name)
            self.assertTrue((ROOT / "skills" / name / "SKILL.md").is_file(), name)

    def test_covers_morning_paste_evening_friday(self):
        for label in ("朝", "Slack を貼った後", "夕方", "金曜"):
            self.assertIn(f"| {label}", self.body, label)

    def test_weekly_meetings_paste_step_is_listed(self):
        self.assertIn("| 週頭", self.body)
        self.assertIn("data/meetings/meetings.json", self.body)
        self.assertTrue((ROOT / "skills/proactive-scan/examples/meetings.sample.json").is_file())
        doc15 = (ROOT / "docs/design/15-morning-plan.md").read_text(encoding="utf-8")
        self.assertNotIn("カレンダー入力の形が未定", doc15)

    def test_sample_meetings_pass_the_real_loader(self):
        sample = ROOT / "skills/proactive-scan/examples/meetings.sample.json"
        with tempfile.TemporaryDirectory() as tmp:
            *_, meetings = proactive_scan.load_inputs(Path(tmp) / "none.json", Path(tmp) / "none", sample)
        self.assertTrue(meetings)

    def test_loader_rejects_a_broken_meetings_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "meetings.json"
            bad.write_text(json.dumps({"version": 1, "meetings": [{"id": "m-1", "title": "x"}]}), encoding="utf-8")
            with self.assertRaises(proactive_scan.BrokenInput):
                proactive_scan.load_inputs(Path(tmp) / "none.json", Path(tmp) / "none", bad)

    def test_no_real_data_markers(self):
        self.assertNotRegex(self.body, r"https?://|xox[bp]-|@[\w.-]+\.\w+")

    def test_long_table_cells_link_to_existing_detail_sections(self):
        # 表のセルは短く保ち、長い手順は ### 節に移して表からリンクする（emh-088）
        headings = {h.lower().replace(" ", "-") for h in re.findall(r"^### (.+)$", self.body, re.M)}
        for label in ("週頭", "Slack を貼った後", "会議が終わった後"):
            row = next((l for l in self.body.splitlines() if l.startswith(f"| {label}")), None)
            self.assertIsNotNone(row, label)
            self.assertLessEqual(max(len(c) for c in row.split("|")), 300, label)
            self.assertNotIn("<br>", row, label)
            anchors = re.findall(r"\]\(#([^)]+)\)", row)
            self.assertTrue(anchors, label)
            for a in anchors:
                self.assertIn(a, headings, a)

    def test_linked_docs_exist(self):
        for rel in re.findall(r"\]\((docs/[^)#]+)", self.body):
            self.assertTrue((ROOT / rel).is_file(), rel)


if __name__ == "__main__":
    unittest.main()
