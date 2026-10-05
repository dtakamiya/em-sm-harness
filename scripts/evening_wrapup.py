#!/usr/bin/env python3
"""夕方の締めレポートを tasks.json から生成する。読み取り専用・stdlib のみ・外部接続なし。

設計: docs/design/25-evening-wrapup.md。朝の計画（scripts/morning_plan.py）と同じ入力を読む。
"""
import argparse
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from morning_plan import ACTIVE, DEFER_ASK_COUNT, _day, _load, _md, _visible  # noqa: E402

MAX_LINES = 5
WAIT_OPS = ("wait", "delegate")


def _ops_on(task, today, ops):
    return [h for h in task.get("history", []) if h.get("op") in ops and _day(h.get("at")) == today]


def build_wrapup(tasks, today):
    tomorrow = today + timedelta(days=1)
    live = [t for t in tasks if _visible(t, today)]
    active = [t for t in live if t["status"] in ACTIVE]
    deferred_today = [t for t in live if _ops_on(t, today, ("defer",))]
    deferred_ids = {t["id"] for t in deferred_today}
    return {
        "today": today,
        "done": [t for t in tasks if _ops_on(t, today, ("done",))],
        "carry": [t for t in active if _day(t.get("due")) and _day(t["due"]) <= today and t["id"] not in deferred_ids],
        "deferred": deferred_today,
        "new_waiting": [t for t in live if t["status"] == "waiting" and _ops_on(t, today, WAIT_OPS)],
        "seeds_due": [t for t in active if _day(t.get("due")) == tomorrow],
        "seeds_check": [t for t in live if t["status"] == "waiting" and _day(t.get("next_check")) == tomorrow],
        "defer_asks": [t for t in active
                       if sum(h["op"] == "defer" for h in t.get("history", [])) >= DEFER_ASK_COUNT - 1],
    }


def _section(title, rows, fmt):
    if not rows:
        return []
    out = ["", f"## {title}（{len(rows)} 件）"]
    out += [f"- {fmt(t)}" for t in rows[:MAX_LINES]]
    if len(rows) > MAX_LINES:
        out.append(f"- ほか {len(rows) - MAX_LINES} 件")
    return out


def _carry_line(t, today):
    gap = (today - _day(t["due"])).days
    return f"{t['id']} {t['title']}（" + (f"期限超過 {gap} 日・{_md(_day(t['due']))}" if gap else "今日期限") + "）"


def render(w):
    today = w["today"]
    if w["carry"]:
        status, head = "🔴 要対応", f"期限が今日以前の未完了が {len(w['carry'])} 件残っています"
    elif w["new_waiting"] or w["deferred"] or w["defer_asks"]:
        status, head = "🟡 注意", "持ち越し・新しい返信待ちあり"
    else:
        status, head = "🟢 順調", "持ち越しなし"
    todo = []
    if w["carry"]:
        todo.append("期限が今日以前の未完了の扱い（今日やる / 先送り / drop）を決める")
    if w["defer_asks"]:
        todo.append("先送りが続くタスクの扱いを決める")
    if w["new_waiting"]:
        todo.append("新しい返信待ちの確認予定日を見る")
    out = [f"# 夕方の締め {today.isoformat()}", "", f"{status}: {head}", "",
           f"**EM がやること**: {'、'.join(todo) if todo else '対応不要'}",
           "", f"今日の完了: {len(w['done'])} 件"]
    out += _section("持ち越し（観察）", w["carry"], lambda t: _carry_line(t, today))
    out += _section("今日先送りした", w["deferred"], lambda t: f"{t['id']} {t['title']}")
    out += _section("新たな返信待ち", w["new_waiting"],
                    lambda t: f"{t['id']} {t['waiting_on']} 待ち（確認予定 {_md(_day(t['next_check']))}）")
    seeds = w["seeds_due"] + w["seeds_check"]
    out += _section("明日の計画の種", seeds,
                    lambda t: f"{t['id']} {t['title']}（" + ("期限" if t in w["seeds_due"] else "返信確認") + "が明日）")
    if w["defer_asks"]:
        out += ["", "## 判断依頼"]
        out += [f"- {t['id']} は先送りが続いています。A) drop B) 分割。おすすめ: B。期限: 今週中"
                for t in w["defer_asks"]]
    out += ["", "## 詳細",
            "- 読み取り専用。tasks.json は変更しません（反映は返答→定型語→apply_reply。docs/design/24）",
            "- 持ち越し = 状態が open/doing で期限が今日以前、かつ今日先送りしていないもの。理由は推測しません",
            "- 「今日の完了・先送り・待ちになった」は各タスクの history の今日付けの操作から数えます"]
    return "\n".join(out) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description="夕方の締めレポートを生成する（読み取り専用）")
    ap.add_argument("--tasks", default="data/tasks/tasks.json")
    ap.add_argument("--today", default=date.today().isoformat())
    args = ap.parse_args(argv)
    sys.stdout.write(render(build_wrapup(_load(args.tasks, "tasks"), _day(args.today))))


if __name__ == "__main__":
    main()
