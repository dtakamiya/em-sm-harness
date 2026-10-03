import json
import re
import sys
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import morning_plan as mp  # noqa: E402

SAMPLE = ROOT / "tests" / "fixtures" / "sample-week"
TODAY = date(2026, 10, 8)
JIRA_ISSUE_KEYS = {"key", "summary", "status", "status_category", "issuetype", "priority", "assignee_ref",
                   "created", "updated", "resolved", "story_points", "flagged", "parent_key",
                   "sprints", "links", "transitions"}
JIRA_ENVELOPE_KEYS = {"schema_version", "fetched_at", "project_alias", "jql_sha256", "complete",
                      "partial_reason", "issue_count", "issues"}
TRANSITION_FIELDS = {"status", "story_points", "sprint"}
SENSITIVE = re.compile(r"https?://(?!example\.invalid)|@[\w.-]+\.(com|jp)|xox[bp]-|token", re.I)


def load(rel):
    return json.loads((SAMPLE / rel).read_text(encoding="utf-8"))


class SampleWeekTest(unittest.TestCase):
    def setUp(self):
        self.jira = load("jira-cache/ex-proj/2026-10-08.json")
        self.tasks = load("tasks/tasks.json")["tasks"]
        self.cands = load("tasks/candidates.json")["candidates"]

    def test_jira_matches_cache_schema(self):
        self.assertEqual(set(self.jira), JIRA_ENVELOPE_KEYS)
        self.assertEqual(self.jira["issue_count"], len(self.jira["issues"]))
        for issue in self.jira["issues"]:
            self.assertEqual(set(issue), JIRA_ISSUE_KEYS, issue["key"])
            self.assertTrue(issue["assignee_ref"].startswith("u_"))
            self.assertIsNone(issue["summary"])
            for tr in issue["transitions"]:
                self.assertIn(tr["field"], TRANSITION_FIELDS)

    def test_zero_story_points_is_kept_distinct_from_null(self):
        points = {i["key"]: i["story_points"] for i in self.jira["issues"]}
        self.assertEqual(points["EX-103"], 0)
        self.assertIsNone(points["EX-104"])

    def test_confluence_index_matches_body_files(self):
        base = SAMPLE / "confluence-cache" / "ex-space"
        index = json.loads((base / "index.json").read_text(encoding="utf-8"))
        self.assertEqual(index["page_count"], len(index["pages"]))
        for page in index["pages"]:
            self.assertTrue((base / page["body_file"]).exists())
            if page["body_status"] == "partial_unconverted":
                self.assertTrue(page["unconverted"])

    def test_slack_pastes_have_front_matter_and_only_fictional_names(self):
        files = sorted((SAMPLE / "slack").glob("*.md"))
        self.assertEqual(len(files), 2)
        for path in files:
            text = path.read_text(encoding="utf-8")
            self.assertTrue(text.startswith("---\nchannel_alias: ex-team"))
            speakers = set(re.findall(r"^(\S+)\s+\d{2}:\d{2}$", text, re.M))
            self.assertTrue(speakers <= {"member-a", "member-b", "member-c"}, speakers)

    def test_task_references_resolve(self):
        ids = {t["id"] for t in self.tasks}
        for task in self.tasks:
            self.assertTrue(set(task["blocks"]) <= ids, task["id"])
            if task["source"] == "slack":
                self.assertTrue((SAMPLE / "slack" / task["source_ref"].split(":")[0]).exists())

    def test_no_real_looking_data_anywhere(self):
        for path in SAMPLE.rglob("*"):
            if path.is_file():
                self.assertIsNone(SENSITIVE.search(path.read_text(encoding="utf-8")), str(path))

    def test_morning_plan_runs_on_dataset_and_surfaces_planted_situations(self):
        plan = mp.build_plan(self.tasks, self.cands, TODAY)
        out = mp.render(plan)
        self.assertEqual([t["id"] for t in plan["overdue"]], ["t-0004"])
        self.assertEqual([t["id"] for t in plan["nudges"]], ["t-0002"])
        self.assertEqual([t["id"] for t in plan["defer_asks"]], ["t-0003"])
        self.assertEqual(len(plan["candidates"]), 1)
        self.assertLess(len(out), 900)


if __name__ == "__main__":
    unittest.main()
