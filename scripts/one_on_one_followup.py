#!/usr/bin/env python3
"""1on1 の前回アクション追跡（O2）を tasks から生成する。試作。読み取り専用・stdlib のみ・外部接続なし。

設計: docs/design/32-one-on-one-followup.md。観察のみ。評価語・解釈・個人別の時系列は出さない。
前回の 1on1 日・対象（メモのファイル名 / 匿名ハンドル）は実行のたびに EM が渡し、保存しない。
"""
import argparse
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from morning_plan import ACTIVE, _day, _md  # noqa: E402
from weekly_review import _parse_day, _wait_since, validate_tasks  # noqa: E402

MAX_LINES = 5
NOT_FOUND_HINT = "前回の約束の記録が見つかりません（「全部完了」という意味ではありません）。EM の記憶・前回のメモで確認してください"


def _read_tasks(path):
    """(タスク配列, ファイルがあったか)。壊れていれば場所つきで終了（上書きしない）。"""
    path = Path(path)
    if not path.exists():
        return [], False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"{path} が壊れています（{exc.msg}）。上書きはしません")
    items = data.get("tasks") if isinstance(data, dict) else None
    if not isinstance(items, list):
        raise SystemExit(f"{path} の形式が不正です。上書きはしません")
    return items, True


def load_tasks(tasks_path, archive_dir):
    """tasks.json と archive/*.json を合わせる（同じ id は tasks.json を優先）。(タスク, tasks.json の有無, archive 件数)。"""
    tasks, exists = _read_tasks(tasks_path)
    seen = {t.get("id") for t in tasks if isinstance(t, dict)}
    archives = sorted(Path(archive_dir).glob("*.json")) if archive_dir and Path(archive_dir).is_dir() else []
    merged = list(tasks)
    for file in archives:
        for t in _read_tasks(file)[0]:
            if isinstance(t, dict) and t.get("id") not in seen:
                merged.append(t)
                seen.add(t.get("id"))
    return merged, exists, len(archives)


def _done_day(task):
    days = [_day(h["at"]) for h in task.get("history", []) if h.get("op") == "done"]
    return max(days) if days else None


def build_followup(tasks, since, today, ref=None, member=None):
    validate_tasks(tasks)
    matched = [t for t in tasks if (ref and t.get("source_ref") == ref) or (member and t.get("waiting_on") == member)]
    done, before = [], 0
    for t in matched:
        if t["status"] == "done":
            d = _done_day(t)
            if d is not None and d < since:
                before += 1  # 前回より前に完了＝持ち越しではない
            else:
                done.append(t)
    known = ACTIVE + ("waiting", "dropped", "done")
    return {
        "unclassified": [t for t in matched if t["status"] not in known],
        "since": since, "today": today, "ref": ref, "member": member, "matched": len(matched),
        "done": done, "done_before": before,
        "active": [t for t in matched if t["status"] in ACTIVE],
        "waiting": [t for t in matched if t["status"] == "waiting"],
        "dropped": [t for t in matched if t["status"] == "dropped"],
    }


def _section(title, rows, fmt):
    if not rows:
        return []
    out = ["", f"## {title}（{len(rows)} 件）"]
    out += [f"- {fmt(t)}" for t in rows[:MAX_LINES]]
    if len(rows) > MAX_LINES:
        out.append(f"- ほか {len(rows) - MAX_LINES} 件")
    return out


def _done_line(t):
    d = _done_day(t)
    return f"{t['id']} {t['title']}（{_md(d)} 完了）" if d else f"{t['id']} {t['title']}（完了日の記録なし）"


def _active_line(t, today):
    due = _day(t.get("due"))
    tail = f"（期限 {_md(due)}・超過 {(today - due).days} 日）" if due and due < today else (f"（期限 {_md(due)}）" if due else "")
    return f"{t['id']} {t['title']}{tail}"


def _waiting_line(t, today):
    since = _wait_since(t, today)
    age = f"返信待ちにして {(today - since).days} 日" if since else "返信待ちにした日は記録なし"
    return f"{t['id']} {t['title']}（{t['waiting_on']} 待ち・{age}）"


def render(f, tasks_file_exists=True, archive_count=0):
    since, today = f["since"], f["today"]
    target = "・".join(x for x in (f"メモ {f['ref']}" if f["ref"] else "", f"相手 {f['member']}" if f["member"] else "") if x)
    head = [f"# 1on1 前回アクションの追跡（前回 {_md(since)}〜今日 {_md(today)}・{target}）", ""]
    if not tasks_file_exists and archive_count == 0:
        return "\n".join(head + [f"🟡 注意: tasks.json が見つかりません。{NOT_FOUND_HINT}", "", "**EM がやること**: 前回のメモを見て約束を確認する", ""])
    if f["matched"] == 0:
        return "\n".join(head + [f"🟡 注意: 該当するタスクがありません。{NOT_FOUND_HINT}", "", "**EM がやること**: 前回のメモを見て約束を確認する（タスク化していなければ、今回のアジェンダ作成時に起こす）", ""])
    carried = len(f["active"]) + len(f["waiting"])
    unknown, no_ref = len(f["unclassified"]), not f["ref"]
    status = "🟡 注意" if carried or unknown or no_ref else "🟢 順調"
    summary = f"前回の約束のうち未完了 {carried} 件・完了 {len(f['done'])} 件・中止 {len(f['dropped'])} 件"
    if unknown:
        summary += f"・分類不能 {unknown} 件"
    todo = []
    if carried:
        todo.append("未完了の扱い（今回の議題にする / 閉じる）を決める")
    if unknown:
        todo.append("分類不能のタスクの状態を確認する")
    if no_ref:
        todo.append("--ref なしのため EM 側のタスクは未確認。前回メモ名を付けて再実行する")
    head += [f"{status}: {summary}", "", f"**EM がやること**: {'、'.join(todo) if todo else '対応不要'}"]
    out = head
    out += _section("分類不能（状態が未知）", f["unclassified"], lambda t: f"{t['id']} {t['title']}（状態 {t['status']}）")
    out += _section("未完了（EM のタスク）", f["active"], lambda t: _active_line(t, today))
    out += _section("返信待ち（相手の約束）", f["waiting"], lambda t: _waiting_line(t, today))
    out += _section("前回以降に完了", f["done"], _done_line)
    out += _section("中止", f["dropped"], lambda t: f"{t['id']} {t['title']}")
    out += ["", "## 詳細",
            "- 読み取り専用。tasks.json は変更しません。前回日・対象は保存しません（個人別の時系列を作らないため。Q-017）",
            f"- 照合: `source_ref` がメモ名と一致、または `waiting_on` が相手ハンドルと一致したタスクのみ。archive {archive_count} ファイルも読みました"
            + (f"。前回より前に完了済みの {f['done_before']} 件は除外" if f["done_before"] else ""),
            "- 観察のみ。未完了の理由は推測しません（本人に聞く）。タスク化されていない口頭の約束は拾えません"]
    return "\n".join(out) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description="1on1 の前回アクション追跡（読み取り専用）")
    ap.add_argument("--since", required=True, help="前回の 1on1 の日（YYYY-MM-DD）。保存しません")
    ap.add_argument("--ref", help="前回の 1on1 メモ/アジェンダ名（tasks の source_ref と照合）")
    ap.add_argument("--member", help="相手の匿名ハンドル（例 member-a。waiting_on と照合）")
    ap.add_argument("--tasks", default="data/tasks/tasks.json")
    ap.add_argument("--archive-dir", default=None, help="既定は tasks.json の隣の archive/")
    ap.add_argument("--today", default=date.today().isoformat())
    args = ap.parse_args(argv)
    if not (args.ref or args.member):
        raise SystemExit("--ref（前回メモ名）か --member（匿名ハンドル）のどちらかを指定してください。指定なしでは全タスクを人に紐付けて出してしまうため、何も出しません")
    since, today = _parse_day(args.since, "--since"), _parse_day(args.today, "--today")
    archive_dir = args.archive_dir or Path(args.tasks).parent / "archive"
    tasks, exists, n_archive = load_tasks(args.tasks, archive_dir)
    sys.stdout.write(render(build_followup(tasks, since, today, args.ref, args.member), exists, n_archive))


if __name__ == "__main__":
    main()
