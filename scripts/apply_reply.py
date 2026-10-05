#!/usr/bin/env python3
"""EM の返答（定型語）を data/tasks に反映する。ローカルのみ・stdlib のみ・外部接続なし。

設計: docs/design/24-reply-apply.md。操作仕様: docs/design/04-personal-tasks.md。
全件検証してから書く（1件でも不正なら何も書かない）。更新前は .bak に退避し、--undo で直前の状態へ戻す。
"""
import argparse
import hashlib
import json
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

LATER_DAYS = 1
DEFER_ASK_COUNT = 3
UNDO_MANIFEST = ".last-reply.json"
TRACKED = ("tasks.json", "candidates.json", "rejected.json")
OPEN_STATES = ("open", "doing", "waiting")


class ReplyError(Exception):
    """EM に返す理由つきの拒否。"""


def _read(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default
    except json.JSONDecodeError as exc:
        raise ReplyError(f"{path.name} が壊れています（{exc.msg}）。.bak からの復元を提案します。上書きはしません")


def _sha(path):
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


def _atomic_write(path, data):
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _md(d):
    return f"{d.month}/{d.day}"


def _day(text, label):
    try:
        return date.fromisoformat(text)
    except ValueError:
        raise ReplyError(f"{label} は YYYY-MM-DD で指定してください（受け取った値: {text}）")


def parse(line):
    """定型語 1 行 → (op, id, 追加引数)。曖昧なものは拒否する（推測しない）。"""
    parts = line.split()
    ops = {"採用": ("adopt", 0, 0), "却下": ("reject", 0, 0), "後で": ("later", 0, 1),
           "完了": ("done", 0, 0), "先送り": ("defer", 1, 1)}
    if not parts or parts[0] not in ops:
        raise ReplyError(f"解釈できません: 「{line}」。書式は 採用/却下/後で/完了/先送り + id（先送りは日付も）")
    op, need, optional = ops[parts[0]]
    args = parts[1:]
    if not args:
        raise ReplyError(f"id がありません: 「{line}」")
    target, extra = args[0], args[1:]
    if len(extra) < need or len(extra) > need + optional:
        raise ReplyError(f"引数の数が合いません: 「{line}」")
    return op, target, extra


def _next_task_id(tasks, archive_dir):
    ids = [t["id"] for t in tasks]
    for f in sorted(archive_dir.glob("*.json")) if archive_dir.exists() else []:
        ids += [t["id"] for t in _read(f, {}).get("tasks", [])]
    return "t-{:04d}".format(max((int(i.split("-")[1]) for i in ids), default=0) + 1)


def _with_history(task, today, entry, **changes):
    return {**task, **changes, "updated": today.isoformat(),
            "history": [*task.get("history", []), {"at": today.isoformat(), **entry}]}


def _find(items, target, kind):
    hits = [i for i in items if i["id"] == target]
    if not hits:
        raise ReplyError(f"{kind} {target} が見つかりません（id の完全一致のみ受け付けます）")
    return hits[0]


def apply_one(state, op, target, extra, today, archive_dir):
    """state = {tasks, candidates, rejected}。新しい state と結果1行を返す（入力は変更しない）。"""
    tasks, cands, rejected = state["tasks"], state["candidates"], state["rejected"]
    if op in ("adopt", "reject", "later"):
        cand = _find(cands, target, "候補")
        rest = [c for c in cands if c["id"] != target]
        if op == "reject":
            entry = {"source": cand.get("source"), "source_ref": cand.get("source_ref"), "at": today.isoformat()}
            return {**state, "candidates": rest, "rejected": [*rejected, entry]}, f"✗ {target} 却下（同じ出典は再提案しない）"
        if op == "later":
            until = _day(extra[0], "日付") if extra else today + timedelta(days=LATER_DAYS)
            kept = [{**c, "snooze_until": until.isoformat()} if c["id"] == target else c for c in cands]
            return {**state, "candidates": kept}, f"💤 {target} {_md(until)} まで非表示"
        new_id = _next_task_id(tasks, archive_dir)
        task = {"id": new_id, "title": cand["title"], "status": "open", "priority": "soon",
                "due": cand.get("suggested_due"), "source": cand.get("source", "manual"),
                "source_ref": cand.get("source_ref"), "waiting_on": None, "next_check": None,
                "blocks": [], "tags": [], "notes": "", "created": today.isoformat(),
                "updated": today.isoformat(), "history": [{"at": today.isoformat(), "op": "add"}]}
        due = f"（期限 {_md(_day(task['due'], 'due'))}）" if task["due"] else ""
        return {**state, "tasks": [*tasks, task], "candidates": rest}, f"+ {new_id} {task['title']}{due}（{target} から採用）"
    task = _find(tasks, target, "タスク")
    if task["status"] not in OPEN_STATES:
        raise ReplyError(f"{target} は {task['status']} のため操作できません（戻すなら reopen を EM が指示）")
    if op == "done":
        new = _with_history(task, today, {"op": "done", "from": task["status"]}, status="done", next_check=None)
        line = f"✓ {target} 完了"
    else:
        new_due = _day(extra[0], "新しい期限")
        count = sum(h["op"] == "defer" for h in task.get("history", [])) + 1
        old = _md(_day(task["due"], "due")) if task.get("due") else "未設定"
        new = _with_history(task, today, {"op": "defer", "from": task.get("due"), "to": new_due.isoformat()},
                            due=new_due.isoformat())
        line = f"→ {target} 期限 {old}→{_md(new_due)}（{count}回目）"
        if count >= DEFER_ASK_COUNT:
            line += " ※先送りが続いています。drop か分割かを決めてください"
    return {**state, "tasks": [new if t["id"] == target else t for t in tasks]}, line


def _audit(audit_dir, now, batch_id, op, target, before, after):
    audit_dir.mkdir(parents=True, exist_ok=True)
    row = {"ts": now.isoformat(timespec="seconds"), "event": "task_updated", "action": "task.update",
           "level_applied": "L0", "batch_id": batch_id, "op": op, "target_id": target,
           "before_sha256": before, "after_sha256": after}
    with (audit_dir / f"{now.date().isoformat()}.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def apply_replies(data_dir, lines, today, now=None, dry_run=False):
    tasks_dir, audit_dir = data_dir / "tasks", data_dir / "audit"
    now = now or datetime.now().astimezone()
    parsed = [parse(line) for line in lines]
    if not parsed:
        raise ReplyError("返答がありません")
    state = {"tasks": _read(tasks_dir / "tasks.json", {"tasks": []})["tasks"],
             "candidates": _read(tasks_dir / "candidates.json", {"candidates": []})["candidates"],
             "rejected": _read(tasks_dir / "rejected.json", {"rejected": []})["rejected"]}
    results = []
    for op, target, extra in parsed:
        state, line = apply_one(state, op, target, extra, today, tasks_dir / "archive")
        results.append(line)
    if dry_run:
        return results
    tasks_dir.mkdir(parents=True, exist_ok=True)
    batch_id = now.strftime("r-%Y%m%dT%H%M%S")
    before = {n: _sha(tasks_dir / n) for n in TRACKED}
    existed = [n for n in TRACKED if (tasks_dir / n).exists()]
    for n in existed:
        (tasks_dir / (n + ".bak")).write_bytes((tasks_dir / n).read_bytes())
    for name, key in (("tasks.json", "tasks"), ("candidates.json", "candidates"), ("rejected.json", "rejected")):
        _atomic_write(tasks_dir / name, {"version": 1, key: state[key]})
    after = {n: _sha(tasks_dir / n) for n in TRACKED}
    _atomic_write(tasks_dir / UNDO_MANIFEST, {"batch_id": batch_id, "existed": existed, "after": after})
    for op, target, _ in parsed:
        file = "candidates.json" if op in ("adopt", "reject", "later") else "tasks.json"
        _audit(audit_dir, now, batch_id, op, target, before[file], after[file])
    return results


def undo(data_dir, force=False, now=None):
    tasks_dir, audit_dir = data_dir / "tasks", data_dir / "audit"
    now = now or datetime.now().astimezone()
    manifest = _read(tasks_dir / UNDO_MANIFEST, None)
    if manifest is None:
        raise ReplyError("戻せる直前の返答反映がありません")
    changed = [n for n in TRACKED if _sha(tasks_dir / n) != manifest["after"][n]]
    if changed and not force:
        raise ReplyError(f"反映後に {', '.join(changed)} が手編集されています。戻すと編集が消えます（--force で実行）")
    for n in TRACKED:
        if n in manifest["existed"]:
            _atomic_write_bytes(tasks_dir / n, (tasks_dir / (n + ".bak")).read_bytes())
        else:
            (tasks_dir / n).unlink(missing_ok=True)
    (tasks_dir / UNDO_MANIFEST).unlink()
    audit_dir.mkdir(parents=True, exist_ok=True)
    row = {"ts": now.isoformat(timespec="seconds"), "event": "task_reverted", "action": "task.update",
           "level_applied": "L0", "batch_id": manifest["batch_id"]}
    with (audit_dir / f"{now.date().isoformat()}.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    return f"↩ {manifest['batch_id']} を取り消しました"


def _atomic_write_bytes(path, content):
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(content)
    os.replace(tmp, path)


def main(argv=None):
    ap = argparse.ArgumentParser(description="EM の返答を data/tasks に反映する（ローカルのみ）")
    ap.add_argument("replies", nargs="*", help="1返答=1引数（引用符で囲む）。例: 採用 c-0001 / 却下 c-0002 / 後で c-0003 [日付] / 完了 t-0001 / 先送り t-0003 2026-10-16")
    ap.add_argument("--data-dir", default="data")
    ap.add_argument("--today", default=date.today().isoformat())
    ap.add_argument("--dry-run", action="store_true", help="書かずに結果だけ表示")
    ap.add_argument("--undo", action="store_true", help="直前の反映を取り消す")
    ap.add_argument("--force", action="store_true", help="--undo で手編集を上書きして戻す")
    args = ap.parse_args(argv)
    data_dir = Path(args.data_dir)
    try:
        if args.undo:
            print(undo(data_dir, args.force))
        else:
            for line in apply_replies(data_dir, args.replies, _day(args.today, "--today"), dry_run=args.dry_run):
                print(line)
    except ReplyError as exc:
        print(f"拒否: {exc}（何も書き込んでいません）", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
