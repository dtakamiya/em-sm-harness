#!/usr/bin/env python3
"""今日の計画（朝）を tasks.json から生成する。読み取り専用・stdlib のみ・外部接続なし。

設計: docs/design/15-morning-plan.md。ルールは docs/design/17-task-priority-and-waiting.md。
"""
import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path

MAX_TOP = 5
MAX_CANDIDATES = 5
SOON_DAYS = 3
DEFER_ASK_COUNT = 3
PRIORITY_RANK = {"now": 0, "soon": 1, "later": 2}
ACTIVE = ("open", "doing")


def _day(value):
    return date.fromisoformat(value) if value else None


def _load(path, key):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    except json.JSONDecodeError as exc:
        raise SystemExit(f"{path} が壊れています（{exc.msg}）。.bak からの復元を提案します。上書きはしません")
    return data.get(key, [])


def _visible(task, today):
    snooze = _day(task.get("snooze_until"))
    return snooze is None or snooze <= today


def _blocking_count(task, open_ids):
    return sum(ref in open_ids for ref in task.get("blocks", []))


def sort_key(task, today, open_ids=frozenset()):
    due = _day(task.get("due"))
    days = (due - today).days if due else 10**6
    band = 0 if days < 0 else 1 if days == 0 else 2 if days <= SOON_DAYS else 3
    blocking = -_blocking_count(task, open_ids)
    return (band, PRIORITY_RANK.get(task.get("priority", "soon"), 1), blocking, days, task["id"])


def build_plan(tasks, candidates, today):
    live = [t for t in tasks if _visible(t, today)]
    open_ids = frozenset(t["id"] for t in live if t["status"] in ACTIVE + ("waiting",))
    active = sorted((t for t in live if t["status"] in ACTIVE), key=lambda t: sort_key(t, today, open_ids))
    overdue = [t for t in active if _day(t.get("due")) and _day(t["due"]) < today]
    nudges = sorted(
        (t for t in live if t["status"] == "waiting" and _day(t["next_check"]) <= today),
        key=lambda t: t["next_check"],
    )
    visible_cands = [c for c in candidates if _visible(c, today)]
    defer_asks = [t for t in active if sum(h["op"] == "defer" for h in t.get("history", [])) >= DEFER_ASK_COUNT - 1]
    return {
        "today": today,
        "top": active[:MAX_TOP],
        "overflow": max(0, len(active) - MAX_TOP),
        "overdue": overdue,
        "nudges": nudges,
        "defer_asks": defer_asks,
        "candidates": visible_cands[:MAX_CANDIDATES],
        "candidate_overflow": max(0, len(visible_cands) - MAX_CANDIDATES),
    }


def _md(d):
    return f"{d.month}/{d.day}"


def _line(task, today):
    due = _day(task.get("due"))
    tail = ""
    if due:
        gap = (due - today).days
        tail = f"（期限超過 {-gap} 日・{_md(due)}）" if gap < 0 else f"（期限 {_md(due)}）"
    return f"{task['id']} {task['title']}{tail}"


def render(plan):
    today = plan["today"]
    if plan["overdue"]:
        status, head = "🔴 要対応", f"期限超過 {len(plan['overdue'])} 件"
    elif plan["nudges"] or plan["defer_asks"]:
        status, head = "🟡 注意", "催促・判断の候補あり"
    else:
        status, head = "🟢 順調", "期限超過なし"
    todo = []
    if plan["nudges"]:
        todo.append(f"催促案 {len(plan['nudges'])} 件を確認（未送信の下書き）")
    if plan["candidates"]:
        todo.append(f"タスク候補 {len(plan['candidates'])} 件に 採用/却下/後で を返す")
    if plan["defer_asks"]:
        todo.append("先送りが続くタスクの扱いを決める")
    out = [f"# 今日の計画 {today.isoformat()}", "", f"{status}: {head}", "",
           "**EM がやること**: " + ("、".join(todo) if todo else "対応不要"), "", "## 今日やる順（観察）"]
    out += [f"{i}. {_line(t, today)}" for i, t in enumerate(plan["top"], 1)] or ["- なし"]
    if plan["overflow"]:
        out.append(f"- ほか {plan['overflow']} 件は一覧に回しました")
    if plan["nudges"]:
        out += ["", "## 返信待ちの催促候補（下書き対象）"]
        out += [f"- {t['id']} {t['waiting_on']} 待ち（確認予定 {_md(_day(t['next_check']))}）" for t in plan["nudges"]]
    if plan["defer_asks"]:
        out += ["", "## 判断依頼"]
        for t in plan["defer_asks"]:
            out += [f"- {t['id']} は先送りが続いています。A) drop B) 分割。おすすめ: B。期限: 今週中"]
    if plan["candidates"]:
        out += ["", "## 新規タスク候補（未確定）"]
        out += [f"- {c['id']} {c['title']}（出典 {c['source_ref']}）" for c in plan["candidates"]]
        if plan["candidate_overflow"]:
            out.append(f"- ほか {plan['candidate_overflow']} 件")
    out += ["", "## 詳細", "- 会議準備・Jira・Confluence は入力未接続のため未反映（現フェーズは tasks と候補のみ）",
            "- 並べ順は暫定: 期限超過 → 今日 → 3日以内 → 優先度 now/soon/later → 他を止めている数 → 期限順"]
    return "\n".join(out) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description="今日の計画を生成する（読み取り専用）")
    ap.add_argument("--tasks", default="data/tasks/tasks.json")
    ap.add_argument("--candidates", default="data/tasks/candidates.json")
    ap.add_argument("--today", default=date.today().isoformat())
    args = ap.parse_args(argv)
    plan = build_plan(_load(args.tasks, "tasks"), _load(args.candidates, "candidates"), _day(args.today))
    sys.stdout.write(render(plan))


if __name__ == "__main__":
    main()
