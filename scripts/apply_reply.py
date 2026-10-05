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


def _read_list(path, key):
    """{key: [ {id,...}, ... ]} 形式を検証して返す。不正なら上書きせず止まる。"""
    data = _read(path, {key: []})
    items = data.get(key) if isinstance(data, dict) else None
    ok = isinstance(items, list) and all(isinstance(i, dict) and ("id" in i or key == "rejected") for i in items)
    if not ok:
        raise ReplyError(f"{path.name} の形式が不正です（{key} の配列が必要）。.bak からの復元を提案します。上書きはしません")
    return items


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
        ids += [t["id"] for t in _read_list(f, "tasks")]
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
            return {**state, "candidates": rest, "rejected": [*rejected, entry]}, f"✗ {target} 却下（出典を記録。再提案の抑止は未実装）"
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


ACTOR = "secretary"


OP_FILES = {"adopt": ("tasks.json", "candidates.json"), "reject": ("candidates.json", "rejected.json"),
            "later": ("candidates.json",), "done": ("tasks.json",), "defer": ("tasks.json",)}


def _audit_rows(now, batch_id, parsed, before, after, new_ids):
    """操作ごとに、実際に変わったファイルとその前後ハッシュを記録する（本文は入れない）。"""
    base = {"ts": now.isoformat(timespec="seconds"), "event": "task_updated", "action": "task.update",
            "actor": ACTOR, "level_applied": "L0", "batch_id": batch_id}
    rows = []
    for i, (op, target, _) in enumerate(parsed):
        changes = [{"file": f, "before_sha256": before[f], "after_sha256": after[f]}
                   for f in OP_FILES[op] if before[f] != after[f]]
        extra = {"new_task_id": new_ids[i]} if i in new_ids else {}
        rows.append({**base, "op": op, "target_id": target, **extra, "changes": changes})
    return rows


def _append_audit(audit_dir, now, rows):
    with (audit_dir / f"{now.date().isoformat()}.jsonl").open("a", encoding="utf-8") as fh:
        fh.write("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))


def _ensure_audit_writable(audit_dir, now):
    """監査を書けないなら、タスクを書く前に止める（監査なしの更新を作らない）。"""
    try:
        audit_dir.mkdir(parents=True, exist_ok=True)
        (audit_dir / f"{now.date().isoformat()}.jsonl").open("a", encoding="utf-8").close()
    except OSError as exc:
        raise ReplyError(f"監査ログに書けません（{exc.strerror}）。監査なしでは更新しません")


def _bytes_sha(content):
    return "sha256:" + hashlib.sha256(content).hexdigest()


def apply_replies(data_dir, lines, today, now=None, dry_run=False):
    tasks_dir, audit_dir = data_dir / "tasks", data_dir / "audit"
    now = now or datetime.now().astimezone()
    parsed = [parse(line) for line in lines]
    if not parsed:
        raise ReplyError("返答がありません")
    state = {key: _read_list(tasks_dir / f"{key}.json", key) for key in ("tasks", "candidates", "rejected")}
    results, new_ids = [], {}
    for i, (op, target, extra) in enumerate(parsed):
        known = {t["id"] for t in state["tasks"]}
        state, line = apply_one(state, op, target, extra, today, tasks_dir / "archive")
        created = [t["id"] for t in state["tasks"] if t["id"] not in known]
        if created:
            new_ids[i] = created[0]
        results.append(line)
    if dry_run:
        return results
    _ensure_audit_writable(audit_dir, now)
    tasks_dir.mkdir(parents=True, exist_ok=True)
    batch_id = now.strftime("r-%Y%m%dT%H%M%S")
    payload = {n: (json.dumps({"version": 1, k: state[k]}, ensure_ascii=False, indent=1) + "\n").encode("utf-8")
               for n, k in (("tasks.json", "tasks"), ("candidates.json", "candidates"), ("rejected.json", "rejected"))}
    before = {n: _sha(tasks_dir / n) for n in TRACKED}
    after = {n: _bytes_sha(payload[n]) for n in TRACKED}
    existed = [n for n in TRACKED if (tasks_dir / n).exists()]
    for n in existed:
        _atomic_write_bytes(tasks_dir / (n + ".bak"), (tasks_dir / n).read_bytes())
    # 先にマニフェストを書く: 途中で落ちても --undo が .bak と反映前ハッシュで検証できる
    _atomic_write(tasks_dir / UNDO_MANIFEST,
                  {"batch_id": batch_id, "existed": existed, "before": before, "after": after})
    for n in TRACKED:
        _atomic_write_bytes(tasks_dir / n, payload[n])
    _append_audit(audit_dir, now, _audit_rows(now, batch_id, parsed, before, after, new_ids))
    return results


def _check_undo_preconditions(tasks_dir, manifest, force):
    """何も触る前に全部確認する。1つでも合わなければ拒否。"""
    for n in manifest["existed"]:
        bak = tasks_dir / (n + ".bak")
        if not bak.exists():
            raise ReplyError(f"{bak.name} がありません。戻せないため何も触りません")
        if _sha(bak) != manifest["before"][n]:
            raise ReplyError(f"{bak.name} の内容が反映前と一致しません。戻せないため何も触りません")
    # 途中で落ちた反映は「反映前」と「反映後」が混在してよい。どちらでもなければ手編集
    changed = [n for n in TRACKED if _sha(tasks_dir / n) not in (manifest["before"][n], manifest["after"][n])]
    if changed and not force:
        raise ReplyError(f"反映後に {', '.join(changed)} が手編集されています。戻すと編集が消えます（--force で実行）")


def undo(data_dir, force=False, now=None):
    tasks_dir, audit_dir = data_dir / "tasks", data_dir / "audit"
    now = now or datetime.now().astimezone()
    manifest = _read(tasks_dir / UNDO_MANIFEST, None)
    if manifest is None:
        raise ReplyError("戻せる直前の返答反映がありません")
    if not isinstance(manifest, dict) or not {"batch_id", "existed", "before", "after"} <= manifest.keys():
        raise ReplyError(f"{UNDO_MANIFEST} の形式が不正です。戻せないため何も触りません")
    _check_undo_preconditions(tasks_dir, manifest, force)
    _ensure_audit_writable(audit_dir, now)
    for n in TRACKED:
        if n in manifest["existed"]:
            _atomic_write_bytes(tasks_dir / n, (tasks_dir / (n + ".bak")).read_bytes())
        else:
            (tasks_dir / n).unlink(missing_ok=True)
    (tasks_dir / UNDO_MANIFEST).unlink()
    _append_audit(audit_dir, now, [{"ts": now.isoformat(timespec="seconds"), "event": "task_reverted",
                                    "action": "task.update", "actor": ACTOR, "level_applied": "L0",
                                    "batch_id": manifest["batch_id"]}])
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
    if args.undo and args.replies:
        ap.error("--undo と返答は同時に指定できません")
    if args.undo and args.dry_run:
        ap.error("--undo と --dry-run は同時に指定できません（取り消しは確認なしで実行されるため）")
    if args.force and not args.undo:
        ap.error("--force は --undo と一緒に指定してください")
    try:
        if args.undo:
            print(undo(data_dir, args.force))
        else:
            for line in apply_replies(data_dir, args.replies, _day(args.today, "--today"), dry_run=args.dry_run):
                print(line)
    except ReplyError as exc:
        print(f"拒否: {exc}（事前チェックで止めたため、tasks は変更していません）", file=sys.stderr)
        sys.exit(1)
    except OSError as exc:
        print(f"失敗: 書込中にエラー（{exc}）。--undo で直前の状態へ戻せるか確認してください", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
