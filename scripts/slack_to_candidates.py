#!/usr/bin/env python3
"""Slack 構造化データ（13 §6）から個人タスク候補を candidates.json に追加する。

ローカルのみ・stdlib のみ・外部接続なし。設計: docs/design/13-slack-paste-input.md §9。
対象は kind=request かつ to_em=true かつ confidence が high/medium の項目だけ。
全件検証してから書く（1件でも不正なら何も書かない）。更新前は candidates.json.pre-slack.bak に退避する
（apply_reply.py --undo の candidates.json.bak とは別名。互いに上書きしない）。
"""
import argparse
import json
import os
import re
import sys
from pathlib import Path

ACCEPTED_CONFIDENCE = ("high", "medium")
TITLE_MAX = 80
ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
ID_NUMBER = re.compile(r"^c-(\d+)$")
SEQUENCE_NAME = "candidate-seq.json"  # 採番済みの最大番号。採用・却下で candidates.json が空でも id を再利用しない
BACKUP_NAME = "candidates.json.pre-slack.bak"  # apply_reply.py の .bak とは別名
REQUIRED_ITEM_KEYS = ("id", "kind", "observation", "confidence")


class IngestError(Exception):
    """EM に返す理由つきの拒否。"""


def _read_json(path, label):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise IngestError(f"{label} が見つかりません: {path}")
    except json.JSONDecodeError as exc:
        raise IngestError(f"{label} が壊れています（{exc.msg}）。上書きはしません")


def _read_list(path, key):
    if not path.exists():
        return []
    data = _read_json(path, path.name)
    items = data.get(key) if isinstance(data, dict) else None
    if not isinstance(items, list) or not all(isinstance(i, dict) for i in items):
        raise IngestError(f"{path.name} の形式が不正です（{key} の配列が必要）。上書きはしません")
    return items


def validate(structured):
    """スキーマ不一致は何も書かずに止める。13 §8: 部分出力しない。"""
    if not isinstance(structured, dict) or structured.get("schema_version") != 1:
        raise IngestError("schema_version 1 の構造化データではありません")
    if structured.get("skipped"):
        raise IngestError(f"skipped={structured['skipped']} のファイルは取り込みません")
    items = structured.get("items")
    source = structured.get("source")
    source_file = source.get("file") if isinstance(source, dict) else None
    if not isinstance(items, list) or not isinstance(source_file, str) or not source_file:
        raise IngestError("source（file を持つ object）と items（配列）が必要です")
    for item in items:
        if not isinstance(item, dict):
            raise IngestError("items の要素が object ではありません")
        missing = [k for k in REQUIRED_ITEM_KEYS if k not in item]
        if missing:
            raise IngestError(f"item {item.get('id', '?')} に必須項目がありません: {', '.join(missing)}")
        wrong = [k for k in ("id", "observation", "confidence") if not isinstance(item[k], str)]
        if wrong:
            raise IngestError(f"item {item['id']!s} の {', '.join(wrong)} が文字列ではありません")
        if item["kind"] == "request" and not isinstance(item.get("to_em"), bool):
            raise IngestError(f"item {item['id']} の to_em が真偽値ではありません")
    return source_file, items


def eligible(item):
    return (item["kind"] == "request" and item["to_em"] is True
            and item["confidence"] in ACCEPTED_CONFIDENCE)


def _title(observation):
    text = observation.strip()
    return text if len(text) <= TITLE_MAX else text[: TITLE_MAX - 1] + "…"


def _due(due_raw):
    """確定日（YYYY-MM-DD）として読めるときだけ日付にする。曖昧なら null（13 §6）。"""
    return due_raw if isinstance(due_raw, str) and ISO_DATE.match(due_raw) else None


def _last_issued(tasks_dir):
    """採番済みの最大番号。ファイルが無い・壊れているときは 0（現存候補の最大番号との大きい方を呼び出し側で取る）。"""
    try:
        value = json.loads((tasks_dir / SEQUENCE_NAME).read_text(encoding="utf-8")).get("last")
    except (OSError, ValueError, AttributeError):
        return 0
    return value if isinstance(value, int) and value >= 0 else 0


def _next_number(candidates, tasks_dir):
    numbers = [int(m.group(1)) for c in candidates if (m := ID_NUMBER.match(str(c.get("id", ""))))]
    return max([*numbers, _last_issued(tasks_dir)], default=0) + 1


def write_sequence(tasks_dir, last):
    body = json.dumps({"last": last}, indent=1) + "\n"
    _atomic_write_bytes(tasks_dir / SEQUENCE_NAME, body.encode("utf-8"))


def build_candidates(source_file, items, known_refs, start_number):
    """新規候補と、除外件数の内訳を返す（入力は変更しない）。"""
    fresh, counts = [], {"added": 0, "duplicate": 0, "not_eligible": 0}
    seen = set(known_refs)
    for item in items:
        if not eligible(item):
            counts["not_eligible"] += 1
            continue
        ref = f"{source_file}:{item['id']}"
        if ref in seen:
            counts["duplicate"] += 1
            continue
        seen.add(ref)
        fresh.append({"id": f"c-{start_number + len(fresh):04d}", "title": _title(item["observation"]),
                      "source": "slack", "source_ref": ref, "suggested_due": _due(item.get("due_raw"))})
        counts["added"] += 1
    return fresh, counts


def _atomic_write_bytes(path, content):
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(content)
    os.replace(tmp, path)


def ingest(structured_path, tasks_dir, dry_run):
    source_file, items = validate(_read_json(structured_path, "構造化データ"))
    cand_path = tasks_dir / "candidates.json"
    candidates = _read_list(cand_path, "candidates")
    tasks = _read_list(tasks_dir / "tasks.json", "tasks")
    rejected = _read_list(tasks_dir / "rejected.json", "rejected")
    # 採用済み・却下済みの出典は再提案しない（04: source + source_ref が同一なら同一候補）
    known = {x.get("source_ref") for x in (*candidates, *tasks, *rejected) if x.get("source_ref")}
    fresh, counts = build_candidates(source_file, items, known, _next_number(candidates, tasks_dir))
    if fresh and not dry_run:
        tasks_dir.mkdir(parents=True, exist_ok=True)
        if cand_path.exists():
            _atomic_write_bytes(tasks_dir / BACKUP_NAME, cand_path.read_bytes())
        body = json.dumps({"version": 1, "candidates": [*candidates, *fresh]}, ensure_ascii=False, indent=1) + "\n"
        _atomic_write_bytes(cand_path, body.encode("utf-8"))
        write_sequence(tasks_dir, max(int(c["id"][2:]) for c in fresh))
    return fresh, counts


def summary(counts, dry_run):
    mode = "（--dry-run: 書き込みなし）" if dry_run else ""
    return (f"タスク候補を {counts['added']} 件追加{mode}"
            f" / 既出 {counts['duplicate']} 件・対象外 {counts['not_eligible']} 件")


def main(argv=None):
    ap = argparse.ArgumentParser(description="Slack 構造化データ → タスク候補（candidates.json）")
    ap.add_argument("structured", type=Path, help="data/structured/slack/<file>.json")
    ap.add_argument("--tasks-dir", type=Path, default=Path("data/tasks"))
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    try:
        fresh, counts = ingest(args.structured, args.tasks_dir, args.dry_run)
    except IngestError as exc:
        print(f"取り込みを中止しました: {exc}", file=sys.stderr)
        return 1
    print(summary(counts, args.dry_run))
    for c in fresh:
        print(f"- {c['id']} {c['title']}（出典 {c['source_ref']}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
