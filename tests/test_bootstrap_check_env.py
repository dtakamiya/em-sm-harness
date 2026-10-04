"""bootstrap / check_env のテスト。git init した一時ディレクトリ（架空）で検証する。実 repo の data/ には触れない。"""
import contextlib
import io
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import bootstrap  # noqa: E402
import check_env  # noqa: E402

GITIGNORE = (ROOT / ".gitignore").read_text(encoding="utf-8")
EXAMPLE = ROOT / "config" / "templates" / "local.yaml.example"


def make_repo(tmp, gitignore=GITIGNORE):
    subprocess.run(["git", "init", "-q", str(tmp)], check=True)
    (tmp / ".gitignore").write_text(gitignore, encoding="utf-8")
    (tmp / "config" / "templates").mkdir(parents=True)
    shutil.copyfile(EXAMPLE, tmp / "config" / "templates" / "local.yaml.example")
    return tmp


def run_main(fn, root):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = fn(["--root", str(root)])
    return code, buf.getvalue()


class TmpRepoCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)


class CheckEnvTest(TmpRepoCase):
    def test_fresh_repo_reports_missing_dirs_and_config_with_next_action(self):
        make_repo(self.root)
        code, out = run_main(check_env.main, self.root)
        self.assertEqual(code, 1)
        self.assertIn("[NG] data/ 置き場 0/", out)
        self.assertIn("bootstrap.py", out)
        self.assertIn("[NG] config/local.yaml", out)
        self.assertIn("local.yaml.example", out)

    def test_detects_missing_gitignore_entries(self):
        make_repo(self.root, gitignore="# nothing\n")
        results = check_env.check_gitignore(self.root)
        self.assertTrue(results)
        self.assertFalse(any(r.ok for r in results))
        self.assertTrue(all(r.todo for r in results))

    def test_detects_partial_gitignore(self):
        make_repo(self.root, gitignore="data/\n")
        by_name = {r.name: r.ok for r in check_env.check_gitignore(self.root)}
        self.assertTrue(by_name["gitignore: data/"])
        self.assertFalse(by_name["gitignore: secrets/"])

    def test_non_git_directory_is_ng_not_crash(self):
        results = check_env.check_gitignore(self.root)
        self.assertFalse(any(r.ok for r in results))

    def test_old_python_is_ng(self):
        results = check_env.check_tools(version_info=(3, 8))
        self.assertFalse(results[0].ok)

    def test_tracked_real_data_is_ng_with_filenames_only(self):
        make_repo(self.root)
        (self.root / "data").mkdir()
        (self.root / "data" / "real.json").write_text("SECRET-CONTENT", encoding="utf-8")
        (self.root / "config" / "local.yaml").write_text("SECRET-CONTENT", encoding="utf-8")
        subprocess.run(["git", "add", "-f", "data/real.json", "config/local.yaml"], cwd=self.root, check=True)
        code, out = run_main(check_env.main, self.root)
        self.assertEqual(code, 1)
        self.assertIn("[NG] git 追跡済みの実データ 2 件", out)
        self.assertIn("data/real.json", out)
        self.assertIn("config/local.yaml", out)
        self.assertNotIn("SECRET-CONTENT", out)

    def test_no_tracked_data_is_ok(self):
        make_repo(self.root)
        self.assertTrue(all(r.ok for r in check_env.check_tracked_data(self.root)))

    def test_loose_permissions_are_ng_with_chmod_hint_and_untouched(self):
        make_repo(self.root)
        (self.root / "data" / "tasks").mkdir(parents=True)
        (self.root / "data").chmod(0o755)
        (self.root / "data" / "tasks").chmod(0o700)
        (self.root / "config" / "local.yaml").write_text("x: 1\n", encoding="utf-8")
        (self.root / "config" / "local.yaml").chmod(0o644)
        code, out = run_main(check_env.main, self.root)
        self.assertEqual(code, 1)
        self.assertIn("[NG] data/ 権限 0700 -> EM がやること: chmod 700 data", out)
        self.assertNotIn("data/tasks", out.split("権限 0700")[1].splitlines()[0])
        self.assertIn("chmod 600 config/local.yaml", out)
        self.assertEqual(stat.S_IMODE((self.root / "data").stat().st_mode), 0o755)

    def test_strict_permissions_are_ok(self):
        make_repo(self.root)
        run_main(bootstrap.main, self.root)
        self.assertTrue(all(r.ok for r in check_env.check_permissions(self.root)))

    def test_check_env_is_read_only(self):
        make_repo(self.root)
        before = sorted(p.relative_to(self.root).as_posix() for p in self.root.rglob("*") if ".git/" not in p.as_posix())
        run_main(check_env.main, self.root)
        after = sorted(p.relative_to(self.root).as_posix() for p in self.root.rglob("*") if ".git/" not in p.as_posix())
        self.assertEqual(before, after)


class BootstrapTest(TmpRepoCase):
    def test_creates_dirs_and_config_then_check_env_passes(self):
        make_repo(self.root)
        code, out = run_main(bootstrap.main, self.root)
        self.assertEqual(code, 0, out)
        for d in check_env.DATA_DIRS:
            self.assertTrue((self.root / "data" / d).is_dir(), d)
        self.assertTrue((self.root / "config" / "local.yaml").is_file())
        self.assertIn("check-env: OK", out)

    def test_dirs_are_0700(self):
        make_repo(self.root)
        run_main(bootstrap.main, self.root)
        mode = stat.S_IMODE((self.root / "data" / "audit").stat().st_mode)
        self.assertEqual(mode, 0o700)

    def test_idempotent(self):
        make_repo(self.root)
        run_main(bootstrap.main, self.root)
        first = sorted(p.relative_to(self.root).as_posix() for p in self.root.rglob("*") if ".git/" not in p.as_posix())
        code, out = run_main(bootstrap.main, self.root)
        second = sorted(p.relative_to(self.root).as_posix() for p in self.root.rglob("*") if ".git/" not in p.as_posix())
        self.assertEqual(code, 0)
        self.assertEqual(first, second)
        self.assertIn("既にあり", out)

    def test_does_not_overwrite_existing_config_or_data(self):
        make_repo(self.root)
        (self.root / "config" / "local.yaml").write_text("mine: 1\n", encoding="utf-8")
        (self.root / "data" / "tasks").mkdir(parents=True)
        keep = self.root / "data" / "tasks" / "tasks.json"
        keep.write_text("{}", encoding="utf-8")
        run_main(bootstrap.main, self.root)
        self.assertEqual((self.root / "config" / "local.yaml").read_text(encoding="utf-8"), "mine: 1\n")
        self.assertEqual(keep.read_text(encoding="utf-8"), "{}")

    def test_still_fails_when_gitignore_is_missing(self):
        make_repo(self.root, gitignore="")
        code, out = run_main(bootstrap.main, self.root)
        self.assertEqual(code, 1)
        self.assertIn("[NG] gitignore: data/", out)

    def test_missing_template_stops_with_message(self):
        make_repo(self.root)
        (self.root / "config" / "templates" / "local.yaml.example").unlink()
        with self.assertRaises(SystemExit):
            bootstrap.ensure_local_config(self.root)

    def test_data_dirs_only_those_in_design(self):
        design = "\n".join(p.read_text(encoding="utf-8") for p in (ROOT / "docs" / "design").glob("*.md"))
        for d in check_env.DATA_DIRS:
            # 直後が / 以外（data/state が data/state/proactive だけで通らない）
            self.assertRegex(design, rf"data/{re.escape(d)}(?![\w-])(?!/[a-z])", d)


if __name__ == "__main__":
    unittest.main()
