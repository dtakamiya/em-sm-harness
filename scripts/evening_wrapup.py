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


def _touched_today(task, today):
    """apply_reply は wait/delegate を履歴に書かないため、updated が今日の返信待ちも拾う。"""
    return bool(_ops_on(task, today, WAIT_OPS)) or _day(task.get("updated")) == today


def _check_text(task):
    return f"確認予定 {_md(_day(task['next_check']))}" if task.get("next_check") else "確認予定未設定"


def build_wrapup(tasks, today, candidates=()):
    tomorrow = today + timedelta(days=1)
    live = [t for t in tasks if _visible(t, today)]
    active = [t for t in live if t["status"] in ACTIVE]
    deferred_today = [t for t in live if _ops_on(t, today, ("defer",))]
    deferred_ids = {t["id"] for t in deferred_today}
    return {
        "today": today,
        "pending_candidates": [c for c in candidates if _visible(c, today)],
        "done": [t for t in tasks if _ops_on(t, today, ("done",))],
        "carry": [t for t in active if _day(t.get("due")) and _day(t["due"]) <= today and t["id"] not in deferred_ids],
        "deferred": deferred_today,
        "new_waiting": [t for t in live if t["status"] == "waiting" and _touched_today(t, today)],
        "nudge_due": [t for t in live if t["status"] == "waiting" and _day(t.get("next_check"))
                      and _day(t["next_check"]) <= today and not _touched_today(t, today)],
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
    elif w["new_waiting"] or w["nudge_due"] or w["deferred"] or w["defer_asks"]:
        status, head = "🟡 注意", "先送り・返信待ち・判断依頼あり"
    else:
        status, head = "🟢 順調", "持ち越しなし"
    todo = []
    if w["carry"]:
        todo.append("期限が今日以前の未完了の扱い（今日やる / 先送り / drop）を決める")
    if w["defer_asks"]:
        todo.append("先送りが続くタスクの扱いを決める")
    if w["nudge_due"]:
        todo.append("確認予定を過ぎた返信待ちを見る（催促の下書きは朝の計画）")
    if w["new_waiting"]:
        todo.append("今日動いた返信待ちの確認予定日を見る")
    out = [f"# 夕方の締め {today.isoformat()}", "", f"{status}: {head}", "",
           f"**EM がやること**: {'、'.join(todo) if todo else '対応不要'}",
           "", f"今日の完了: {len(w['done'])} 件"]
    if w["pending_candidates"]:
        out.append(f"未確認の候補: {len(w['pending_candidates'])} 件")
    out += _section("持ち越し（観察）", w["carry"], lambda t: _carry_line(t, today))
    out += _section("今日先送りした", w["deferred"], lambda t: f"{t['id']} {t['title']}")
    out += _section("今日動いた返信待ち（新規を含む）", w["new_waiting"],
                    lambda t: f"{t['id']} {t['waiting_on']} 待ち（{_check_text(t)}）")
    out += _section("確認予定を過ぎた返信待ち", w["nudge_due"],
                    lambda t: f"{t['id']} {t['waiting_on']} 待ち（{_check_text(t)}）")
    seeds = w["seeds_due"] + w["seeds_check"]
    out += _section("明日の計画の種", seeds,
                    lambda t: f"{t['id']} {t['title']}（" + ("期限" if t in w["seeds_due"] else "返信確認") + "が明日）")
    if w["defer_asks"]:
        out += ["", "## 判断依頼"]
        out += [f"- {t['id']} は先送りが続いています。A) 中止 B) 分割。おすすめ: B。期限: 今週中（返答: 中止 {t['id']} / 分割 {t['id']} 案1 案2）"
                for t in w["defer_asks"]]
    out += ["", "## 詳細",
            "- 読み取り専用。tasks.json は変更しません（反映は返答→定型語→apply_reply。docs/design/24）",
            "- 持ち越し = 状態が open/doing で期限が今日以前、かつ今日先送りしていないもの。理由は推測しません",
            "- 今日の完了・先送りは history の今日付けの操作、返信待ちは wait/delegate の操作か updated が今日かで数えます"]
    return "\n".join(out) + "\n"


def has_report(w):
    """Q-029 b): 持ち越し・新しい返信待ち・判断依頼のある日だけ全文を出す。"""
    return bool(w["carry"] or w["new_waiting"] or w["defer_asks"])


def _quiet_line(w):
    parts = [f"{label} {len(w[key])} 件" for label, key in (("確認予定超過", "nudge_due"), ("今日先送り", "deferred"),
                                                       ("未確認の候補", "pending_candidates")) if w[key]]
    tail = f"。{'・'.join(parts)}は明朝の計画へ" if parts else ""
    return f"夕方の締め {w['today'].isoformat()}: 🟢 対応不要（出す内容なし{tail}）\n"


def render_for_day(w, always):
    return render(w) if always or has_report(w) else _quiet_line(w)


def _load_candidates(path):
    """候補は付加情報。壊れていても締め全体は止めず、0 件扱いにして stderr に警告する。"""
    try:
        return _load(path, "candidates")
    except SystemExit as exc:
        print(f"警告: 候補を読めないため 0 件として扱います（{exc}）", file=sys.stderr)
        return []


def main(argv=None):
    ap = argparse.ArgumentParser(description="夕方の締めレポートを生成する（読み取り専用）")
    ap.add_argument("--tasks", default="data/tasks/tasks.json")
    ap.add_argument("--candidates", default="data/tasks/candidates.json")
    ap.add_argument("--today", default=date.today().isoformat())
    ap.add_argument("--always", action="store_true", help="出す内容がない日も全文を出す")
    args = ap.parse_args(argv)
    wrapup = build_wrapup(_load(args.tasks, "tasks"), _day(args.today), _load_candidates(args.candidates))
    sys.stdout.write(render_for_day(wrapup, args.always))


if __name__ == "__main__":
    main()
