#!/usr/bin/env python3
"""先回り検知（期限接近・ブロッカー・返信待ち・会議準備・放置）。モック試作・stdlib のみ・外部接続なし。

設計: docs/design/18-proactive-detection.md。読むのは tasks・Jira キャッシュ・meetings.json。
書くのは data/state/proactive.json と data/audit/ だけ（L1: 送信・更新はしない）。
"""
import argparse
import json
import os
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TASK_STATUSES = ("open", "doing", "waiting", "done", "dropped")
LEVELS = {"高": 0, "中": 1, "低": 2}
MAX_SHOWN = 5
MAX_NUDGES = 3
DUE_SOON_DAYS = 3
BLOCKER_QUIET_BDAYS = 3
JIRA_STALE_BDAYS = 7
TASK_STALE_DAYS = 14
JIRA_CACHE_OLD_BDAYS = 2
MEDIUM_QUIET_BDAYS = 2
PROMOTE_AFTER_SHOWS = 3
NUDGES_BEFORE_DECISION = 2
PRUNE_DAYS = 90
RULE_LABELS = {"due": "期限", "blocker": "ブロッカー", "waiting": "返信待ち", "meeting": "会議準備", "stale": "動きなし"}
ACTIVE = ("open", "doing")
EXIT_NONE, EXIT_NOTIFY, EXIT_BROKEN = 0, 10, 2


class BrokenInput(Exception):
    pass


def _day(value):
    return date.fromisoformat(str(value)[:10]) if value else None


def bdays_between(start, end):
    """start の翌日から end まで（end を含む）の平日の数。土日のみ除く（祝日は見ない）。"""
    count, cur = 0, start
    while cur < end:
        cur += timedelta(days=1)
        count += cur.weekday() < 5
    return count


def next_bday(today):
    nxt = today + timedelta(days=1)
    while nxt.weekday() >= 5:
        nxt += timedelta(days=1)
    return nxt


def finding(rule, ref, level, fact, **extra):
    return {"key": f"{rule}:{ref}", "rule": rule, "ref": ref, "level": level, "fact": fact, **extra}


# ---- 検知ルール（純関数: 入力, 今日 → 所見の一覧） ----

def detect_due(tasks, today):
    out = []
    for t in tasks:
        due = _day(t.get("due"))
        if t["status"] not in ACTIVE or not due:
            continue
        gap = (due - today).days
        if gap > DUE_SOON_DAYS:
            continue
        fact = f"期限超過 {-gap} 日" if gap < 0 else "期限は今日" if gap == 0 else f"期限まで {gap} 日"
        out.append(finding("due", t["id"], "高" if gap <= 0 else "中", fact, title=t["title"], gap=gap))
    return out


def detect_blockers(issues, tasks, today):
    by_key = {i["key"]: i for i in issues}
    urgent = {t.get("source_ref") for t in tasks
              if t.get("source") == "jira" and t["status"] in ACTIVE and _day(t.get("due"))
              and (_day(t["due"]) - today).days <= DUE_SOON_DAYS}
    out = []
    for issue in issues:
        quiet = bdays_between(_day(issue["updated"]), today)
        if issue["status_category"] == "done" or quiet < BLOCKER_QUIET_BDAYS:
            continue
        blocked = [lk["issue_key"] for lk in issue.get("links", [])
                   if lk["link_type"] == "blocks" and lk["direction"] == "outward"
                   and by_key.get(lk["issue_key"], {}).get("status_category") != "done"]
        if not blocked:
            continue
        level = "高" if any(b in urgent for b in blocked) else "中"
        out.append(finding("blocker", issue["key"], level,
                           f"{len(blocked)} 件を止めていて {quiet} 営業日 更新なし"))
    return out


def detect_waiting(tasks, today):
    out = []
    for t in tasks:
        nxt = _day(t.get("next_check"))
        if t["status"] != "waiting" or not nxt or nxt > today:
            continue
        nudges = sum(h["op"] == "nudge" for h in t.get("history", []))
        fact = f"{t['waiting_on']} 待ち・催促 {nudges} 回済み"
        if nudges >= NUDGES_BEFORE_DECISION:
            out.append(finding("waiting", t["id"], "高", fact, decision=True,
                               ask="直接話す・別経路で聞く / 別の人に振る・drop（おすすめ: 前者・今週中）"))
        else:
            out.append(finding("waiting", t["id"], "中", fact, nudge=True))
    return out


def detect_meetings(meetings, tasks, today):
    by_id = {t["id"]: t for t in tasks}
    limit = next_bday(today)
    out = []
    for m in meetings:
        start = _day(m["start"])
        if not today <= start <= limit:
            continue
        prep = by_id.get(m.get("prep_task_id"))
        if prep and prep["status"] in ("done", "dropped"):
            continue
        state = "準備タスクなし" if not prep else "準備タスク未完了"
        out.append(finding("meeting", m["id"], "中", f"{start.month}/{start.day} の会議（{m['title']}）・{state}"))
    return out


def detect_stale(issues, tasks, today):
    out = []
    for i in issues:
        quiet = bdays_between(_day(i["updated"]), today)
        if i["status_category"] == "indeterminate" and quiet >= JIRA_STALE_BDAYS:
            out.append(finding("stale", i["key"], "低", f"進行中で {quiet} 営業日 更新なし"))
    for t in tasks:
        idle = (today - _day(t["updated"])).days
        if t["status"] in ACTIVE and idle >= TASK_STALE_DAYS:
            out.append(finding("stale", t["id"], "低", f"{idle} 日 動きなし", title=t["title"]))
    return out


def scan(tasks, issues, meetings, today):
    """入力が None のルールは走らせない（呼び出し側が「入力なし」を詳細に出す）。"""
    found = detect_due(tasks, today) + detect_waiting(tasks, today) + detect_stale(issues or [], tasks, today)
    if issues is not None:
        found += detect_blockers(issues, tasks, today)
    if meetings is not None:
        found += detect_meetings(meetings, tasks, today)
    merged = {}
    for f in found:  # 同じ対象は 1 行（ルール名を併記）
        prev = merged.get(f["ref"])
        if prev is None:
            merged[f["ref"]] = {**f, "rules": [f["rule"]]}
        else:
            top = min((prev, f), key=lambda x: LEVELS[x["level"]])
            merged[f["ref"]] = {**top, "rules": prev["rules"] + [f["rule"]],
                                "fact": prev["fact"] + " / " + f["fact"] if prev["level"] == f["level"] else top["fact"]}
    return sorted(merged.values(), key=lambda f: (LEVELS[f["level"]], f.get("gap", 10**6), f["ref"]))


# ---- 状態・絞り込み ----

def _muted(entry, f, today):
    """EM が --ack / --snooze で明示した間だけ true（高でも尊重する）。"""
    if entry is None:
        return False
    snooze = _day(entry.get("snooze_until"))
    return bool(snooze and snooze > today) or entry.get("acked_level") == f["level"]


def _entry_visible(entry, f, today, digest):
    """状態 1 件に対して、この所見を今日出すか決める。(出すか, 判断依頼にするか) を返す。"""
    if entry is None or entry.get("level") != f["level"]:
        return True, False  # 新規、または段が変わった（再掲）
    if _muted(entry, f, today):
        return False, False
    last = _day(entry.get("last_shown"))
    if last == today:  # 同日の再実行: 表示済みを同じ形で再表示
        return True, entry.get("decision_on") == today.isoformat()
    if entry.get("decision_on"):
        return False, False  # 判断依頼は 1 回きり
    if f["level"] == "中" and last and bdays_between(last, today) < MEDIUM_QUIET_BDAYS:
        return False, False
    return True, entry.get("shown_count", 0) >= PROMOTE_AFTER_SHOWS


def select(findings, tasks, state, today, digest=False):
    """表示対象を決める。戻り値: (表示する所見, 超過件数, 判断依頼の key 集合)。高は抑止しない。"""
    touched = {t["id"] for t in tasks if t["status"] in ("done", "dropped")}
    prev = today - timedelta(days=1)
    while prev.weekday() >= 5:
        prev -= timedelta(days=1)
    touched_recently = {t["id"] for t in tasks if _day(t["updated"]) >= prev}
    wanted = [f for f in findings if (f["level"] == "低") == digest]
    shown, decisions = [], set()
    for f in wanted:
        if f["ref"] in touched or (f["level"] != "高" and f["ref"] in touched_recently):
            continue
        entry = state.get(f["key"])
        if f["level"] == "高":
            visible, decision = not _muted(entry, f, today), False
        else:
            visible, decision = _entry_visible(entry, f, today, digest)
        if visible:
            shown.append(f)
            if decision or f.get("decision"):
                decisions.add(f["key"])
    nudges, picked = 0, []
    for f in shown:
        if f.get("nudge"):
            if nudges >= MAX_NUDGES:
                continue
            nudges += 1
        picked.append(f)
    top = picked[:MAX_SHOWN]
    return top, len(shown) - len(top), decisions


def update_state(state, shown, decisions, today):
    """表示した key の回数を進める（同日の再実行では増やさない）。新しい辞書を返す。"""
    new = {k: dict(v) for k, v in state.items()}
    iso = today.isoformat()
    for f in shown:
        old = new.get(f["key"])
        if old and old.get("level") == f["level"]:
            entry = dict(old)
        else:
            entry = {"first_seen": iso, "shown_count": 0, "level": f["level"], "snooze_until": None}
        if entry.get("last_shown") != iso:
            entry["shown_count"] = entry.get("shown_count", 0) + 1
            entry["last_shown"] = iso
        if f["key"] in decisions and f["level"] != "高":
            entry["decision_on"] = entry.get("decision_on") or iso
        new[f["key"]] = entry
    return new


def prune_state(state, live_keys, today):
    cutoff = today - timedelta(days=PRUNE_DAYS)
    return {k: v for k, v in state.items()
            if k in live_keys or (_day(v.get("last_shown")) or today) > cutoff}


def apply_ack(state, key, snooze_until=None):
    if key not in state:
        raise KeyError(key)
    entry = dict(state[key])
    if snooze_until:
        entry["snooze_until"] = snooze_until.isoformat()
    else:
        entry["acked_level"] = entry["level"]
    return {**state, key: entry}


# ---- 入出力 ----

def _read_json(path, required=False):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        if required:
            raise BrokenInput(f"{path} がありません")
        return None
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise BrokenInput(f"{path} が壊れています（{exc}）")


def _need_date(value, where, required=True):
    if value is None:
        if required:
            raise BrokenInput(f"{where} の日付がありません")
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        raise BrokenInput(f"{where} の日付が不正です")


def _need_dict(value, where):
    if not isinstance(value, dict):
        raise BrokenInput(f"{where} の形式が不正です")
    return value


def _need_list(value, where):
    if not isinstance(value, list):
        raise BrokenInput(f"{where} の形式が不正です")
    return value


def validate_tasks(tasks, where):
    for i, t in enumerate(_need_list(tasks, where)):
        at = f"{where}[{i}]"
        _need_dict(t, at)
        if not isinstance(t.get("id"), str) or not isinstance(t.get("title"), str) \
                or t.get("status") not in TASK_STATUSES:
            raise BrokenInput(f"{at} の id/title/status が不正です")
        if t["status"] == "waiting" and not isinstance(t.get("waiting_on"), str):
            raise BrokenInput(f"{at} は waiting ですが waiting_on がありません")
        _need_date(t.get("due"), at, required=False)
        _need_date(t.get("next_check"), at, required=False)
        _need_date(t.get("updated"), at)
        for h in _need_list(t.get("history", []), at):
            if not isinstance(h, dict) or "op" not in h:
                raise BrokenInput(f"{at} の history が不正です")
    return tasks


def validate_issues(issues, where):
    for i, it in enumerate(_need_list(issues, where)):
        at = f"{where}[{i}]"
        _need_dict(it, at)
        if not isinstance(it.get("key"), str) or "status_category" not in it:
            raise BrokenInput(f"{at} の key/status_category が不正です")
        _need_date(it.get("updated"), at)
        for lk in _need_list(it.get("links", []), at):
            if not isinstance(lk, dict) or not {"link_type", "direction", "issue_key"} <= set(lk) \
                    or not isinstance(lk["issue_key"], str):
                raise BrokenInput(f"{at} の links が不正です")
    return issues


def validate_meetings(meetings, where):
    for i, m in enumerate(_need_list(meetings, where)):
        at = f"{where}[{i}]"
        _need_dict(m, at)
        if not isinstance(m.get("id"), str) or not isinstance(m.get("title"), str):
            raise BrokenInput(f"{at} の id/title が不正です")
        _need_date(m.get("start"), at)
    return meetings


def load_inputs(tasks_path, jira_dir, meetings_path):
    """戻り値: (tasks|None, issues|None, jira_fetched_at|None, meetings|None)。不在は None、破損は BrokenInput。"""
    tasks_doc = _read_json(tasks_path)
    tasks = None
    if tasks_doc is not None:
        tasks = validate_tasks(_need_dict(tasks_doc, str(tasks_path)).get("tasks"), str(tasks_path))
    issues, fetched = None, None
    files = sorted(Path(jira_dir).glob("*/*.json")) if Path(jira_dir).is_dir() else []
    if files:
        latest = max(files, key=lambda p: p.name)
        doc = _need_dict(_read_json(latest), str(latest))
        issues = validate_issues(doc.get("issues"), str(latest))
        fetched = _need_date(doc.get("fetched_at"), f"{latest} の fetched_at")
    meetings_doc = _read_json(meetings_path)
    meetings = None
    if meetings_doc is not None:
        meetings = validate_meetings(_need_dict(meetings_doc, str(meetings_path)).get("meetings"), str(meetings_path))
    return tasks, issues, fetched, meetings


def load_state(path):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, UnicodeDecodeError):
        return {}  # 読めなければ全 key を新規扱い（通知が増える側に倒す）
    if not isinstance(data, dict) or not all(isinstance(v, dict) for v in data.values()):
        raise BrokenInput(f"{path} の形式が不正です")  # 読めるが形が違う: 推測で上書きしない
    return data


def save_state(path, state):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.with_suffix(".json.bak").write_bytes(path.read_bytes())
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(state, fh, ensure_ascii=False, indent=1, sort_keys=True)
    os.replace(tmp, path)


def append_audit(audit_dir, today, key, op):
    Path(audit_dir).mkdir(parents=True, exist_ok=True)
    row = {"at": today.isoformat(), "op": op, "key": key}
    with (Path(audit_dir) / f"{today.isoformat()}.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


# ---- 出力 ----

def detail_lines(notes):
    return [f"- {n}" for n in notes]


def render_section(shown, overflow, decisions, today, folded=()):
    """朝の計画に載せる「先回り」節（見出しを含む）。folded = 同じ朝の計画の別の節に既出で、畳んだ所見。"""
    out = ["## 先回り（観察）"]
    if not shown and not folded:
        out.append("- 先回り対応不要")
    for f in shown:
        if f["key"] in decisions:
            continue
        rules = "・".join(RULE_LABELS[r] for r in f["rules"]) if len(f["rules"]) > 1 else ""
        out.append(f"- [{f['level']}] {f['ref']} {f.get('title', '')} {f['fact']}".replace("  ", " ") + (f"（{rules}）" if rules else "") + f" `{f['key']}`")
    if folded:
        out.append("- 既出のため畳んだ件: " + "・".join(f["ref"] for f in folded) + "（上の節のとおり）")
    if overflow:
        out.append(f"- ほか {overflow} 件")
    asks = [f for f in shown if f["key"] in decisions]
    if asks:
        out += ["", "### 判断依頼"]
        for f in asks:
            ask = f.get("ask") or "A) keep B) drop（おすすめ: A・来週まで）。表示 3 回で動きがなかったため、以後は繰り返しません"
            out.append(f"- {f['ref']} {f.get('title', '')} {f['fact']}。{ask} `{f['key']}`".replace("  ", " "))
    return out


def render(shown, overflow, decisions, today, notes=()):
    highs = sum(f["level"] == "高" for f in shown)
    if highs:
        head = f"🔴 要対応: 先回り（高）{highs} 件"
    elif shown:
        head = f"🟡 注意: 先回り {len(shown)} 件"
    else:
        head = "🟢 順調: 先回り対応不要"
    todo = "先回りの各件を確認" if shown else "対応不要"
    body = render_section(shown, overflow, decisions, today)
    detail = ["", "## 詳細"] + detail_lines(notes) if notes else []
    return "\n".join([f"# 先回り {today.isoformat()}", "", head, "", f"**EM がやること**: {todo}", ""] + body + detail) + "\n"


def collect_with_state(args_paths, today, digest=False):
    """スキャン〜絞り込みまで（保存はしない）。戻り値: (shown, overflow, decisions, notes, new_state)。破損は BrokenInput。"""
    tasks_p, jira_d, meet_p, state_p = args_paths
    tasks, issues, fetched, meetings = load_inputs(tasks_p, jira_d, meet_p)
    notes = []
    if tasks is None:
        notes.append("タスク一覧: 入力なし（期限・返信待ち・放置は未判定）")
        tasks = []
    if issues is None:
        notes.append("Jira キャッシュ: 入力なし（ブロッカー・放置の Jira 分は未判定）")
    elif bdays_between(fetched, today) > JIRA_CACHE_OLD_BDAYS:
        notes.append("Jira キャッシュのデータが古い")
    if meetings is None:
        notes.append("会議一覧: 入力なし（会議準備は未判定）")
    findings = scan(tasks, issues, meetings, today)
    state = load_state(state_p)
    shown, overflow, decisions = select(findings, tasks, state, today, digest)
    new_state = prune_state(update_state(state, shown, decisions, today), {f["key"] for f in findings}, today)
    return shown, overflow, decisions, notes, new_state


def collect(args_paths, today, digest=False):
    """collect_with_state して状態を保存する。戻り値: (shown, overflow, decisions, notes)。"""
    *result, new_state = collect_with_state(args_paths, today, digest)
    save_state(args_paths[3], new_state)
    return tuple(result)


def build_parser():
    ap = argparse.ArgumentParser(description="先回り検知（読み取り＋状態ファイルのみ）")
    ap.add_argument("--tasks", default=str(ROOT / "data/tasks/tasks.json"))
    ap.add_argument("--jira-dir", default=str(ROOT / "data/jira-cache"))
    ap.add_argument("--meetings", default=str(ROOT / "data/meetings/meetings.json"))
    ap.add_argument("--state", default=str(ROOT / "data/state/proactive.json"))
    ap.add_argument("--audit-dir", default=str(ROOT / "data/audit"))
    ap.add_argument("--today", default=date.today().isoformat())
    ap.add_argument("--digest", action="store_true", help="低（放置）の週次要約")
    ap.add_argument("--ack", metavar="KEY")
    ap.add_argument("--snooze", nargs=2, metavar=("KEY", "DATE"))
    return ap


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        today = _need_date(args.today, "--today")
    except BrokenInput as exc:
        sys.stderr.write(f"入力エラー: {exc}。状態は変更していません\n")
        return EXIT_BROKEN
    if args.ack or args.snooze:
        key = args.ack or args.snooze[0]
        try:
            until = _need_date(args.snooze[1], "--snooze") if args.snooze else None
            save_state(args.state, apply_ack(load_state(args.state), key, until))
        except BrokenInput as exc:
            sys.stderr.write(f"入力エラー: {exc}。状態は変更していません\n")
            return EXIT_BROKEN
        except KeyError:
            sys.stderr.write(f"key {key} は状態にありません\n")
            return EXIT_BROKEN
        append_audit(args.audit_dir, today, key, "snooze" if args.snooze else "ack")
        sys.stdout.write(f"{key} を{'スヌーズ' if args.snooze else '既読'}にしました\n")
        return EXIT_NONE
    try:
        shown, overflow, decisions, notes = collect(
            (args.tasks, args.jira_dir, args.meetings, args.state), today, args.digest)
    except BrokenInput as exc:
        sys.stderr.write(f"入力エラー: {exc}。状態は変更していません\n")
        return EXIT_BROKEN
    sys.stdout.write(render(shown, overflow, decisions, today, notes))
    return EXIT_NOTIFY if shown else EXIT_NONE


if __name__ == "__main__":
    sys.exit(main())
