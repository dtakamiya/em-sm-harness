#!/usr/bin/env python3
"""現地環境チェック。gitignore・python/git・data/ の置き場・config/local.yaml を確認する。

設計: docs/design/08-portability.md（持ち出し事故の防止）・09 D2。読み取り専用・外部接続なし。
終了コード: 0=全項目 OK / 1=NG あり。各行に「EM が次にやること」を1行で添える。
"""
import argparse
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

MIN_PYTHON = (3, 9)

# gitignore されているべきパス（実在しなくても git check-ignore はパターンで判定できる）
MUST_IGNORE = ("data/x", "config/local.yaml", ".env", ".env.local", "secrets/x")

# data/ 配下の置き場（docs/design の既存設計に出てくるものだけ。bootstrap と共有）
DATA_DIRS = (
    "inbox",
    "inbox/slack",
    "jira-cache",
    "confluence-cache",
    "structured",
    "tasks",
    "outputs",
    "actions",
    "audit",
    "state",
)

LOCAL_CONFIG = Path("config/local.yaml")
LOCAL_CONFIG_EXAMPLE = Path("config/templates/local.yaml.example")


@dataclass(frozen=True)
class Result:
    ok: bool
    name: str
    todo: str  # OK のときは空


def _is_ignored(root, rel):
    """git check-ignore。戻り値 True=無視される / False=無視されない / None=判定不能。"""
    try:
        proc = subprocess.run(["git", "check-ignore", "-q", "--no-index", rel], cwd=root, capture_output=True)
    except OSError:
        return None
    if proc.returncode == 0:
        return True
    return False if proc.returncode == 1 else None


def check_tools(version_info=None):
    version = tuple(version_info or sys.version_info[:2])
    py = Result(
        version >= MIN_PYTHON,
        f"python3 {version[0]}.{version[1]}",
        f"python3 を {MIN_PYTHON[0]}.{MIN_PYTHON[1]} 以上にする",
    )
    has_git = shutil.which("git") is not None
    git = Result(has_git, "git の有在", "git を入れる（Xcode Command Line Tools: xcode-select --install）")
    return [py, git]


def check_gitignore(root):
    if shutil.which("git") is None:
        return [Result(False, "gitignore 判定", "git を入れてから再実行する")]
    results = []
    for rel in MUST_IGNORE:
        ignored = _is_ignored(root, rel)
        shown = rel.removesuffix("/x") + ("/" if rel.endswith("/x") else "")
        if ignored is None:
            results.append(Result(False, f"gitignore: {shown}", "git repo か確認する（git init 済みの repo 直下で実行）"))
        else:
            results.append(Result(ignored, f"gitignore: {shown}", f".gitignore に {shown} を追加する（実データ混入防止）"))
    return results


def check_data_dirs(root):
    missing = [d for d in DATA_DIRS if not (root / "data" / d).is_dir()]
    names = f"data/ 置き場 {len(DATA_DIRS) - len(missing)}/{len(DATA_DIRS)}"
    todo = "python3 scripts/bootstrap.py を実行して置き場を作る（不足: " + ", ".join(missing) + "）" if missing else ""
    return [Result(not missing, names, todo)]


def check_local_config(root):
    ok = (root / LOCAL_CONFIG).is_file()
    todo = f"cp {LOCAL_CONFIG_EXAMPLE} {LOCAL_CONFIG} して会社固有値を埋める（python3 scripts/bootstrap.py でも可）"
    return [Result(ok, str(LOCAL_CONFIG), "" if ok else todo)]


def run_checks(root=ROOT):
    root = Path(root)
    return [*check_tools(), *check_gitignore(root), *check_data_dirs(root), *check_local_config(root)]


def format_results(results):
    lines = []
    for r in results:
        lines.append(f"[OK] {r.name}" if r.ok else f"[NG] {r.name} -> EM がやること: {r.todo}")
    ng = sum(not r.ok for r in results)
    lines.append(f"check-env: OK {len(results) - ng} / NG {ng}")
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", default=str(ROOT), help="検査する repo ルート（既定: この repo）")
    args = parser.parse_args(argv)
    results = run_checks(args.root)
    print(format_results(results))
    return 0 if all(r.ok for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
