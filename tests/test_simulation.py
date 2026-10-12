import hashlib
import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RUNNER = ROOT / "simulation" / "run_week.py"
FIXTURE = ROOT / "tests" / "fixtures" / "sample-week"
OUT_LOG = ROOT / "simulation" / "out" / "run-log.json"
EXPECTED_DAYS = ["mon", "tue", "wed", "thu", "fri"]


def tree_hash(path):
    digest = hashlib.sha256()
    for item in sorted(p for p in path.rglob("*") if p.is_file()):
        digest.update(str(item.relative_to(path)).encode())
        digest.update(item.read_bytes())
    return digest.hexdigest()


class SimulationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.before = tree_hash(FIXTURE)
        cls.proc = subprocess.run([sys.executable, str(RUNNER)], capture_output=True, text=True, cwd=ROOT, check=False)
        cls.steps = json.loads(OUT_LOG.read_text(encoding="utf-8")) if OUT_LOG.exists() else []

    def test_week_runs_without_failed_steps(self):
        self.assertEqual(self.proc.returncode, 0, self.proc.stdout + self.proc.stderr)
        self.assertEqual([s["name"] for s in self.steps if s["returncode"]], [])

    def test_covers_monday_to_friday_in_readme_order(self):
        self.assertEqual(sorted({s["day"] for s in self.steps}, key=EXPECTED_DAYS.index), EXPECTED_DAYS)
        names = [s["name"] for s in self.steps]
        self.assertEqual(names[0], "morning_plan")
        self.assertEqual(names[-2:], ["weekly_review", "proactive_scan --digest"])

    def test_source_fixture_is_not_modified(self):
        self.assertEqual(tree_hash(FIXTURE), self.before)

    def test_output_dir_is_gitignored(self):
        result = subprocess.run(["git", "check-ignore", "-q", "simulation/out/run-log.md"], cwd=ROOT, check=False)
        self.assertEqual(result.returncode, 0)

    def test_runner_does_not_target_data_dir(self):
        self.assertNotIn("data/", " ".join(" ".join(s["argv"]) for s in self.steps).replace("simulation/out/workspace/", ""))


if __name__ == "__main__":
    unittest.main()
