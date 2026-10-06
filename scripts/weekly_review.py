#!/usr/bin/env python3
"""金曜用の週次棚卸しを tasks.json から生成する。読み取り専用・stdlib のみ・外部接続なし。

設計: docs/design/29-weekly-review.md。数と事実のみ。評価語・解釈・人別の集計は出さない。
"""
import argparse
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from morning_plan import ACTIVE, _day, _load, _md, _visible  # noqa: E402

MAX_LINES = 5
WAIT_OPS = ("wait", "delegate")
DEFER_REPEAT = 2  # 週内に先送りが 2 回以上＝事実として並べる（判断依頼は朝・夕の仕事）


def week_start(today):
    return today - timedelta(days=today.weekday())


def _ops_in(task, start, today, ops):
    return [h for h in task.get("history", []) if h.get("op") in ops and start <= _day(h.get("at")) <= today]


def _wait_since(task):
    """返信待ちにした日。wait/delegate の最後の操作日。無ければ None（推測しない）。"""
    days = [_day(h["at"]) for h in task.get("history", []) if h.get("op") in WAIT_OPS]
    return max(days) if days else None


def build_review(tasks, today):
    start = week_start(today)
    live = [t for t in tasks if _visible(t, today)]
    active = [t for t in live if t["status"] in ACTIVE]
    waiting = [t for t in live if t["status"] == "waiting"]
    return {
        "today": today,
        "start": start,
        "added": [t for t in tasks if _ops_in(t, start, today, ("add",))],
        "done": [t for t in tasks if _ops_in(t, start, today, ("done",))],
        "deferrals": sum(len(_ops_in(t, start, today, ("defer",))) for t in tasks),
        "deferred_repeat": [t for t in active if len(_ops_in(t, start, today, ("defer",))) >= DEFER_REPEAT],
        "active": active,
        "overdue": [t for t in active if _day(t.get("due")) and _day(t["due"]) < today],
        "carry_in": [t for t in active if _ops_in(t, date.min, start - timedelta(days=1), ("add",))],
        "waiting": waiting,
        "wait_overdue": [t for t in waiting if _day(t.get("next_check")) and _day(t["next_check"]) < today],
        "wait_unset": [t for t in waiting if not t.get("next_check")],
    }


def _section(title, rows, fmt):
    if not rows:
        return []
    out = ["", f"## {title}（{len(rows)} 件）"]
    out += [f"- {fmt(t)}" for t in rows[:MAX_LINES]]
    if len(rows) > MAX_LINES:
        out.append(f"- ほか {len(rows) - MAX_LINES} 件")
    return out


def _overdue_line(t, today):
    return f"{t['id']} {t['title']}（期限超過 {(today - _day(t['due'])).days} 日・{_md(_day(t['due']))}）"


def _wait_line(t, today):
    since = _wait_since(t)
    age = f"返信待ちにして {(today - since).days} 日" if since else "返信待ちにした日は記録なし"
    check = f"確認予定 {_md(_day(t['next_check']))}" if t.get("next_check") else "確認予定未設定"
    return f"{t['id']} {t['waiting_on']} 待ち（{age}・{check}）"


def render(w):
    today = w["today"]
    if w["overdue"]:
        status, head = "🔴 要対応", f"期限超過の未完了が {len(w['overdue'])} 件あります"
    elif w["wait_overdue"] or w["wait_unset"] or w["deferred_repeat"]:
        status, head = "🟡 注意", "確認予定超過・未設定の返信待ち、または週内に繰り返し先送りしたタスクがあります"
    else:
        status, head = "🟢 順調", "期限超過・確認予定超過なし"
    todo = []
    if w["overdue"]:
        todo.append("期限超過の扱い（やる / 先送り / drop）を決める")
    if w["wait_overdue"] or w["wait_unset"]:
        todo.append("確認予定を過ぎた・未設定の返信待ちを見る")
    if w["deferred_repeat"]:
        todo.append("週内に繰り返し先送りしたタスクの扱いを決める")
    out = [f"# 週次棚卸し {_md(w['start'])}〜{_md(today)}", "", f"{status}: {head}", "",
           f"**EM がやること**: {'、'.join(todo) if todo else '対応不要'}", "",
           "## 今週の数",
           f"- 完了 {len(w['done'])} 件 / 追加 {len(w['added'])} 件 / 先送り操作 {w['deferrals']} 回",
           f"- 未完了 {len(w['active'])} 件のうち、週の前から持ち越し {len(w['carry_in'])} 件",
           f"- 返信待ち {len(w['waiting'])} 件（確認予定超過 {len(w['wait_overdue'])}・未設定 {len(w['wait_unset'])}）"]
    out += _section("期限超過（観察）", w["overdue"], lambda t: _overdue_line(t, today))
    out += _section("週内に繰り返し先送り", w["deferred_repeat"], lambda t: f"{t['id']} {t['title']}")
    out += _section("返信待ちの滞留", w["waiting"], lambda t: _wait_line(t, today))
    out += ["", "## 詳細",
            "- 読み取り専用。tasks.json は変更しません（反映は返答→定型語→apply_reply。docs/design/24）",
            f"- 週 = 月曜（{_md(w['start'])}）から今日まで。完了・追加・先送りは history の日付で数えます",
            "- 持ち越し = 状態が open/doing で、週の前に追加されたもの。理由は推測しません",
            "- 前週との比較はしません（週ごとの保存先が未設計。docs/design/29）。評価・解釈は載せません"]
    return "\n".join(out) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description="週次棚卸しを生成する（読み取り専用）")
    ap.add_argument("--tasks", default="data/tasks/tasks.json")
    ap.add_argument("--today", default=date.today().isoformat())
    args = ap.parse_args(argv)
    sys.stdout.write(render(build_review(_load(args.tasks, "tasks"), _day(args.today))))


if __name__ == "__main__":
    main()
