#!/usr/bin/env python3
"""架空の 1 週間（2026-10-05 月〜10-09 金）を、README「毎日の使い方」の順に実コマンドで再現する。

L1・ローカル完結: 外部接続・送信・書込なし。ワークスペース（simulation/out/workspace/）に架空 fixture をコピーして使い、
元 fixture と data/ は触らない（実行後に fixture のハッシュと data/ の有無を検証する）。
出力（out/）は gitignore。結果は out/run-log.json と out/run-log.md に残す。
使い方: python3 simulation/run_week.py [--fixture monday|snapshot]   （終了コード 0=全ステップ成功 / 1=失敗ステップあり / 2=安全検査 NG）
"""
import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SIM = Path(__file__).resolve().parent
OUT = SIM / "out"
WS = OUT / "workspace"
FIXTURES = {"monday": ROOT / "tests" / "fixtures" / "sample-week-monday",
            "snapshot": ROOT / "tests" / "fixtures" / "sample-week"}  # snapshot = 10/8（水）時点の断面（未来日付を読む）
FIXTURE = FIXTURES["monday"]
SKILLS = ROOT / "skills"
SCRIPTS = ROOT / "scripts"

# 「60 秒で読める」の目安: 日本語の黙読を 1 分 500 字として 60 秒 = 500 字。余裕を見て警告は 800 字超・40 行超
READ_CHARS_PER_MINUTE = 500
WARN_CHARS = 800
WARN_LINES = 40
SECONDS_PER_MINUTE = 60

DAYS = {"mon": "2026-10-05", "tue": "2026-10-06", "wed": "2026-10-07", "thu": "2026-10-08", "fri": "2026-10-09"}


@dataclass
class Step:
    day: str
    name: str
    argv: list
    em_minutes_target: float  # README の「EM の時間」。dry-run → 本番は 1 組で 1 回分なので dry-run 側は 0
    returncode: int = 0
    seconds: float = 0.0
    out_chars: int = 0
    out_lines: int = 0
    read_minutes: float = 0.0
    stdout: str = ""
    stderr: str = ""
    notes: list = field(default_factory=list)


def sha_tree(path):
    digest = hashlib.sha256()
    for item in sorted(p for p in Path(path).rglob("*") if p.is_file()):
        digest.update(str(item.relative_to(path)).encode())
        digest.update(item.read_bytes())
    return digest.hexdigest()


def prepare_workspace():
    """fixture と skills の架空入力をワークスペースへコピーする（元は書き換えない）。"""
    if OUT.exists():
        shutil.rmtree(OUT)
    (WS / "tasks").mkdir(parents=True)
    for name in ("tasks.json", "candidates.json"):
        shutil.copy(FIXTURE / "tasks" / name, WS / "tasks" / name)
    shutil.copytree(FIXTURE / "jira-cache", WS / "jira-cache")
    (WS / "structured" / "slack").mkdir(parents=True)
    (WS / "structured" / "meeting").mkdir(parents=True)
    (WS / "drafts-in").mkdir()
    (WS / "meetings").mkdir()
    for f in (SKILLS / "slack-to-candidates" / "examples").glob("*.json"):
        shutil.copy(f, WS / "structured" / "slack" / f.name)
    for f in (SKILLS / "meeting-to-candidates" / "examples").glob("*.json"):
        shutil.copy(f, WS / "structured" / "meeting" / f.name)
    for f in (SKILLS / "draft-reply" / "examples").glob("*.sample.json"):
        shutil.copy(f, WS / "drafts-in" / f.name)
    meetings = FIXTURE / "meetings" / "meetings.json"
    shutil.copy(meetings if meetings.exists() else SKILLS / "proactive-scan" / "examples" / "meetings.sample.json",
                WS / "meetings" / "meetings.json")


def py(script, *args):
    return [sys.executable, str(SCRIPTS / script), *map(str, args)]


def paths():
    return {
        "tasks": WS / "tasks" / "tasks.json",
        "cands": WS / "tasks" / "candidates.json",
        "tasks_dir": WS / "tasks",
        "jira": WS / "jira-cache",
        "meetings": WS / "meetings" / "meetings.json",
        "state": WS / "state" / "proactive.json",
        "audit": WS / "audit",
        "drafts": WS / "outputs" / "drafts",
    }


def task_id_by_title(fragments):
    """タイトルの一部（文字列か、候補の組）から task id を引く（採用で振られる id は実行時に決まる）。無ければ空文字（返答が拒否され失敗として残る）。"""
    try:
        rows = json.loads(paths()["tasks"].read_text(encoding="utf-8"))["tasks"]
    except (OSError, ValueError, KeyError):
        return ""
    wanted = (fragments,) if isinstance(fragments, str) else fragments
    return next((r["id"] for r in rows if any(f in r["title"] for f in wanted)), "")


def first_candidate_ids(limit):
    """EM が「採用」と返す候補 id。いま candidates.json にある先頭から取る（ID は実行時に決まる）。"""
    try:
        rows = json.loads(paths()["cands"].read_text(encoding="utf-8"))["candidates"]
    except (OSError, ValueError, KeyError):
        return []
    return [r["id"] for r in rows[:limit]]


def run(step):
    start = time.monotonic()
    proc = subprocess.run(step.argv, capture_output=True, text=True, cwd=ROOT, check=False)
    step.seconds = round(time.monotonic() - start, 2)
    step.returncode, step.stdout, step.stderr = proc.returncode, proc.stdout, proc.stderr
    step.out_chars, step.out_lines = len(proc.stdout), len(proc.stdout.splitlines())
    step.read_minutes = round(step.out_chars / READ_CHARS_PER_MINUTE, 1)
    if proc.returncode != 0:
        step.notes.append(f"終了コード {proc.returncode}")
    if step.out_chars > WARN_CHARS or step.out_lines > WARN_LINES:
        step.notes.append(f"60秒で読めない恐れ（{step.out_chars}字・{step.out_lines}行）")
    return step


def morning(day, p):
    return Step(day, "morning_plan", py("morning_plan.py", "--proactive", "--tasks", p["tasks"], "--candidates", p["cands"],
                                        "--today", DAYS[day], "--jira-dir", p["jira"], "--meetings", p["meetings"],
                                        "--state", p["state"]), 2)


def slack(day, name, p, dry_run):
    argv = py("slack_to_candidates.py", WS / "structured" / "slack" / name, "--tasks-dir", p["tasks_dir"])
    return Step(day, "slack_to_candidates" + (" --dry-run" if dry_run else ""), argv + (["--dry-run"] if dry_run else []), 0 if dry_run else 3)


def meeting(day, name, p, dry_run):
    argv = py("meeting_to_candidates.py", WS / "structured" / "meeting" / name, "--tasks-dir", p["tasks_dir"],
              "--out-dir", p["drafts"], "--audit-dir", p["audit"])
    return Step(day, "meeting_to_candidates" + (" --dry-run" if dry_run else ""), argv + (["--dry-run"] if dry_run else []), 0 if dry_run else 3)


def draft(day, scene, name, p):
    return Step(day, f"make_draft {scene}", py("make_draft.py", scene, WS / "drafts-in" / name, "--out-dir", p["drafts"],
                                              "--today", DAYS[day]), 2)


def reply(day, replies, dry_run=False):
    args = ["--data-dir", WS, "--today", DAYS[day], *(["--dry-run"] if dry_run else []), *replies]
    return Step(day, "apply_reply" + (" --dry-run" if dry_run else ""), py("apply_reply.py", *args), 1)


def evening(day, p):
    return Step(day, "evening_wrapup", py("evening_wrapup.py", "--tasks", p["tasks"], "--today", DAYS[day]), 1)


def weekly(day, p):
    return [Step(day, "weekly_review", py("weekly_review.py", "--tasks", p["tasks"], "--today", DAYS[day]), 3),
            Step(day, "proactive_scan --digest", py("proactive_scan.py", "--digest", "--tasks", p["tasks"], "--jira-dir", p["jira"],
                                                  "--meetings", p["meetings"], "--state", p["state"], "--audit-dir", p["audit"],
                                                  "--today", DAYS[day]), 1)]


def week_plan(p):
    """(Step か、実行時に Step を作る関数) の列。返答は直前の取り込み結果を見て決める。"""
    adopt = lambda day, n: (lambda: reply(day, [f"採用 {i}" for i in first_candidate_ids(n)] or ["採用 c-0001"]))
    done = lambda day, title: (lambda: reply(day, [f"完了 {task_id_by_title(title)}"]))
    defer = lambda day, title, until: (lambda: reply(day, [f"先送り {task_id_by_title(title)} {until}"]))
    return [
        morning("mon", p), slack("mon", "2026-10-05-ex-team-01.json", p, True), slack("mon", "2026-10-05-ex-team-01.json", p, False),
        meeting("mon", "2026-10-05-ex-planning.json", p, True), meeting("mon", "2026-10-05-ex-planning.json", p, False),
        adopt("mon", 3), evening("mon", p),
        morning("tue", p), done("tue", "ステークホルダー週次報告"), defer("tue", "リリース判断の準備メモ", "2026-10-12"),
        evening("tue", p),
        morning("wed", p), defer("wed", "リリース判断の準備メモ", "2026-10-13"), slack("wed", "2026-10-07-ex-team-02.json", p, False),
        meeting("wed", "2026-10-07-ex-sync.json", p, False),
        draft("wed", "slack-reply", "slack-reply.sample.json", p), adopt("wed", 2), evening("wed", p),
        morning("thu", p), reply("thu", ["催促済 t-0002"]), meeting("thu", "2026-10-08-ex-review.json", p, False),
        draft("thu", "jira-comment", "jira-comment.sample.json", p), done("thu", ("金曜までに決めたい", "デモ環境の担当")), evening("thu", p),
        morning("fri", p), reply("fri", ["再開 t-0002"]), done("fri", "staging データ準備"), evening("fri", p), *weekly("fri", p),
    ]


def render_md(steps, safety):
    lines = ["# シミュレーション実行ログ（架空データ・L1）", "", f"- 安全検査: {safety}", f"- ステップ数: {len(steps)} / 失敗: "
             f"{sum(1 for s in steps if s.returncode)} / 注意あり: {sum(1 for s in steps if s.notes)}", "",
             "| 日 | ステップ | rc | 出力(字/行) | 読む目安(分) | README目標(分) | 注意 |", "|---|---|---|---|---|---|---|"]
    for s in steps:
        lines.append(f"| {s.day} | {s.name} | {s.returncode} | {s.out_chars}/{s.out_lines} | {s.read_minutes} | "
                     f"{s.em_minutes_target:g} | {'; '.join(s.notes)} |")
    lines += ["", f"README 目標の合計: {sum(s.em_minutes_target for s in steps):g} 分 / 出力を読む時間の合計（目安）: "
              f"{sum(s.read_minutes for s in steps):.1f} 分", "", "## 出力・エラー本文"]
    for i, s in enumerate(steps, 1):
        lines += [f"### {i}. {s.day} {s.name}", "```", s.stdout.rstrip() or "(stdout なし)", "```"]
        if s.stderr.strip():
            lines += ["stderr:", "```", s.stderr.rstrip(), "```"]
    return "\n".join(lines) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description="架空の 1 週間を通しで再現する（L1・ローカル完結）")
    ap.add_argument("--fixture", choices=sorted(FIXTURES), default="monday",
                    help="monday=月曜起点（既定） / snapshot=10/8（水）時点の断面（月曜から通すと未来日付を読む）")
    args = ap.parse_args(argv)
    global FIXTURE
    FIXTURE = FIXTURES[args.fixture]
    fixture_before = sha_tree(FIXTURE)
    data_existed = (ROOT / "data").exists()
    data_before = sha_tree(ROOT / "data") if data_existed else None
    prepare_workspace()
    p = paths()
    steps = []
    for item in week_plan(p):
        step = run(item() if callable(item) else item)
        steps.append(step)
        mark = "OK " if step.returncode == 0 else "NG "
        print(f"{mark}{step.day} {step.name} ({step.out_chars}字, {step.seconds}s){' ⚠ ' + '; '.join(step.notes) if step.notes else ''}")
    safety_ok = sha_tree(FIXTURE) == fixture_before and (sha_tree(ROOT / "data") == data_before if data_existed else not (ROOT / "data").exists())
    safety = "OK（元 fixture 不変・data/ 不変）" if safety_ok else "NG（fixture か data/ が変わった）"
    (OUT / "run-log.json").write_text(json.dumps([asdict(s) for s in steps], ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    (OUT / "run-log.md").write_text(render_md(steps, safety), encoding="utf-8")
    print(f"\n安全検査: {safety}\nログ: {OUT.relative_to(ROOT)}/run-log.md")
    if not safety_ok:
        return 2
    return 1 if any(s.returncode for s in steps) else 0


if __name__ == "__main__":
    sys.exit(main())
