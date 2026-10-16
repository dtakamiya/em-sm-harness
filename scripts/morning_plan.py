#!/usr/bin/env python3
"""今日の計画（朝）を tasks.json から生成する。読み取り専用・stdlib のみ・外部接続なし。

設計: docs/design/15-morning-plan.md。ルールは docs/design/17-task-priority-and-waiting.md。
"""
import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import slack_purge  # noqa: E402

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
    items = data.get(key, []) if isinstance(data, dict) else None
    if not isinstance(items, list):
        raise SystemExit(f"{path} の形式が不正です。上書きはしません")
    return items


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


def already_shown_in_plan(plan):
    """先回りの所見が、同じ計画の「今日やる順」「催促候補」に同じ情報で既出かを返す判定関数（18 §2 まとめ）。

    畳むのは次の 3 つだけ。
    - 期限接近だけ・段が中・対象が今日やる順にある（行に期限日が出ている）
    - 期限接近だけ・期限超過・対象が今日やる順にある（行に「期限超過 N 日」が出て、結論行も 🔴 になる）
    - 返信待ちだけで、対象が催促候補にある（行に待ち先と確認予定が出る。催促回数も行に足してある）
    期限が今日の高、ブロッカー等ほかのルールを含む件は畳まない。判断依頼は呼び出し側（select）が畳まない。
    """
    top_ids = {t["id"] for t in plan["top"]}
    nudge_ids = {t["id"] for t in plan["nudges"]}

    def already(f):
        if f["rules"] == ["due"] and f["ref"] in top_ids:
            return f["level"] == "中" or f.get("gap", 0) < 0
        return f["rules"] == ["waiting"] and f["ref"] in nudge_ids

    return already


def _nudge_count(task):
    return sum(h["op"] == "nudge" for h in task.get("history", []))


def _md(d):
    return f"{d.month}/{d.day}"


def _line(task, today):
    due = _day(task.get("due"))
    tail = ""
    if due:
        gap = (due - today).days
        tail = f"（期限超過 {-gap} 日・{_md(due)}）" if gap < 0 else f"（期限 {_md(due)}）"
    return f"{task['id']} {task['title']}{tail}"


def render(plan, proactive_lines=(), detail_extra=(), proactive=False, purge_notice=None):
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
        out += [f"- {t['id']} {t['waiting_on']} 待ち（確認予定 {_md(_day(t['next_check']))}・催促 {_nudge_count(t)} 回済み）"
                for t in plan["nudges"]]
    if plan["defer_asks"]:
        out += ["", "## 判断依頼"]
        for t in plan["defer_asks"]:
            out += [f"- {t['id']} は先送りが続いています。A) 中止 B) 分割。おすすめ: B。期限: 今週中（返答: 中止 {t['id']} / 分割 {t['id']} 案1 案2）"]
    if plan["candidates"]:
        out += ["", "## 新規タスク候補（未確定）"]
        out += [f"- {c['id']} {c['title']}（出典 {c['source_ref']}）" for c in plan["candidates"]]
        if plan["candidate_overflow"]:
            out.append(f"- ほか {plan['candidate_overflow']} 件")
    if proactive_lines:
        out += ["", *proactive_lines]
    # --proactive のときは Jira・会議の入力有無を上の detail_extra が示す。固定文で「Jira 未反映」と言い切らない
    unreflected = ("- Confluence は入力未接続のため未反映（Jira・会議の入力有無は上の行のとおり）" if proactive
                   else "- 会議準備・Jira・Confluence は入力未接続のため未反映（現フェーズは tasks と候補のみ）")
    out += ["", "## 詳細", *detail_extra, *([f"- {purge_notice}"] if purge_notice else []), unreflected,
            "- 並べ順は暫定: 期限超過 → 今日 → 3日以内 → 優先度 now/soon/later → 他を止めている数 → 期限順"]
    return "\n".join(out) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description="今日の計画を生成する（読み取り専用）")
    ap.add_argument("--tasks", default=str(ROOT / "data/tasks/tasks.json"))
    ap.add_argument("--candidates", default=str(ROOT / "data/tasks/candidates.json"))
    ap.add_argument("--today", default=date.today().isoformat())
    ap.add_argument("--proactive", action="store_true", help="先回り節を載せる（状態ファイルを更新する）")
    ap.add_argument("--jira-dir", default=str(ROOT / "data/jira-cache"))
    ap.add_argument("--meetings", default=str(ROOT / "data/meetings/meetings.json"))
    ap.add_argument("--state", default=str(ROOT / "data/state/proactive.json"))
    ap.add_argument("--slack-base", default=str(ROOT / "data/inbox/slack"))
    ap.add_argument("--slack-structured", default=str(ROOT / "data/structured/slack"))
    args = ap.parse_args(argv)
    try:
        today = _day(args.today)
    except ValueError:
        raise SystemExit("--today の日付が不正です")
    lines, detail, new_state = (), (), None
    try:
        plan = build_plan(_load(args.tasks, "tasks"), _load(args.candidates, "candidates"), today)
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise SystemExit(f"入力の形式が不正です（{type(exc).__name__}）。上書きはしません")
    if args.proactive:
        import proactive_scan as ps
        try:
            shown, overflow, decisions, notes, new_state = ps.collect_with_state(
                (args.tasks, args.jira_dir, args.meetings, args.state), today, fold=already_shown_in_plan(plan))
        except ps.BrokenInput as exc:
            raise SystemExit(f"先回り入力エラー: {exc}。状態は変更していません")
        detail = ps.detail_lines(notes)
        # 判断依頼に回った返信待ちは、催促の下書き対象から外す（17 §2: 3 回目は下書きを出さない）
        asked = {f["ref"] for f in shown if f["key"] in decisions and f["rule"] == "waiting"}
        plan = {**plan, "nudges": [t for t in plan["nudges"] if t["id"] not in asked]}
        kept = [f for f in shown if not f.get("folded")]
        folded = [f for f in shown if f.get("folded")]
        lines = ps.render_section(kept, overflow, decisions, today, folded)
    # 14 日超の一時ファイル件数を1行だけ出す（読み取りのみ・削除しない）
    purge_notice = slack_purge.pending_notice(args.slack_base, args.slack_structured)
    output = render(plan, lines, detail, proactive=args.proactive, purge_notice=purge_notice)
    if args.proactive:
        try:
            ps.save_state(args.state, new_state)  # 出力が組み立てられた後にだけ保存する
        except ps.WriteFailed as exc:
            sys.stderr.write(f"先回りの書き込みエラー: {exc}。状態は更新していません（朝の計画は出力していません）\n")
            raise SystemExit(ps.EXIT_BROKEN)
    sys.stdout.write(output)


if __name__ == "__main__":
    main()
