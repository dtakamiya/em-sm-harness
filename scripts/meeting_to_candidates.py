#!/usr/bin/env python3
"""会議メモの構造化データ（28 §3）から、議事録下書き（M2）と個人タスク候補（M3）を作る。

既存の下書きは .bak に退避してから上書きする。ローカルのみ・stdlib のみ・外部接続なし。設計: docs/design/28-meeting-notes-input.md §6〜§7。
検証・書込は slack_to_candidates.py と共通（全件検証してから書く／更新前は退避／既出 source_ref は再提案しない）。
未決・担当不明・除外行は議事録下書きに必ず残す（落とさない）。候補になるのは EM 本人の action_item
（confidence が high/medium）だけ。下書きは未送信で、Confluence 等への掲載は EM。
"""
import argparse
import json
import sys
from pathlib import Path

import slack_to_candidates as sc

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT_DIR = ROOT / "data" / "outputs" / "drafts"
BACKUP_NAME = "candidates.json.pre-meeting.bak"  # slack 取り込み・apply_reply の退避とは別名
KINDS = ("decision", "action_item", "open_question")
BANNER = "【下書き・未送信】"
ID_PATTERN_KEYS = ("id", "kind", "observation", "confidence")


def validate(structured):
    """スキーマ不一致は何も書かずに止める（13 §8）。"""
    if not isinstance(structured, dict) or structured.get("schema_version") != 1:
        raise sc.IngestError("schema_version 1 の構造化データではありません")
    if structured.get("skipped"):
        raise sc.IngestError(f"skipped={structured['skipped']} のファイルは取り込みません")
    source, items = structured.get("source"), structured.get("items")
    excluded = structured.get("excluded", [])
    if not isinstance(source, dict) or not isinstance(source.get("file"), str) or not source["file"]:
        raise sc.IngestError("source（file を持つ object）が必要です")
    if not isinstance(items, list) or not isinstance(excluded, list):
        raise sc.IngestError("items と excluded は配列にしてください")
    for item in items:
        if not isinstance(item, dict):
            raise sc.IngestError("items の要素が object ではありません")
        missing = [k for k in ID_PATTERN_KEYS if not isinstance(item.get(k), str)]
        if missing:
            raise sc.IngestError(f"item {item.get('id', '?')} の {', '.join(missing)} が文字列ではありません")
        if item["kind"] not in KINDS:
            raise sc.IngestError(f"item {item['id']} の kind が不正です: {item['kind']}")
        if item["kind"] == "action_item" and not isinstance(item.get("to_em"), bool):
            raise sc.IngestError(f"item {item['id']} の to_em が真偽値ではありません")
    for row in excluded:
        if not isinstance(row, dict) or not isinstance(row.get("reason"), str):
            raise sc.IngestError("excluded の要素は reason（文字列）を持つ object にしてください")
    return source, items, excluded


def eligible(item):
    return (item["kind"] == "action_item" and item.get("owner") == "em" and item["to_em"] is True
            and item["confidence"] in sc.ACCEPTED_CONFIDENCE)


def build_candidates(source_file, items, known_refs, start_number):
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
        fresh.append({"id": f"c-{start_number + len(fresh):04d}", "title": sc._title(item["observation"]),
                      "source": "meeting", "source_ref": ref, "suggested_due": sc._due(item.get("due_raw"))})
        counts["added"] += 1
    return fresh, counts


def _action_line(item):
    owner = item.get("owner") or "未記載"
    due = item.get("due_raw") or "未記載"
    flag = "（要確認: 担当が読み取れない）" if item.get("owner") is None else ""
    return f"- {item['observation']}（担当: {owner}、期限: {due}）{flag}"


def render_minutes(source, items, excluded):
    """議事録下書き。観察された事実（observation）だけを並べ、補完しない。"""
    by_kind = {k: [i for i in items if i["kind"] == k] for k in KINDS}
    head = f"{BANNER}議事録: {source.get('meeting_alias', '（別名なし）')}（{source.get('held_on', '日付未記載')}）"
    lines = [head, f"出典: {source['file']}（匿名化済みの構造化データ）", "", "■ 決定事項"]
    lines += [f"- {i['observation']}" for i in by_kind["decision"]] or ["- なし"]
    lines += ["", "■ アクション"]
    lines += [_action_line(i) for i in by_kind["action_item"]] or ["- なし"]
    lines += ["", "■ 未決事項"]
    lines += [f"- {i['observation']}（要確認）" for i in by_kind["open_question"]] or ["- なし"]
    lines += ["", "■ 抽出しなかった行（落とさないための記録）"]
    lines += [f"- {r.get('line', '?')} 行目: {r['reason']}" for r in excluded] or ["- なし"]
    lines += ["", "⟦EM が決める⟧"]
    undecided = [i for i in by_kind["action_item"] if i.get("owner") is None or not i.get("due_raw")]
    lines.append(f"- 担当または期限が空欄のアクション {len(undecided)} 件の確定（おすすめ: 参加者に確認してから）")
    lines += ["- 共有範囲（おすすめ: 参加者のみ）", "- 掲載先への反映（送るのは EM）"]
    return "\n".join(lines) + "\n"


def ingest(structured_path, tasks_dir, out_dir, dry_run):
    source, items, excluded = validate(sc._read_json(structured_path, "構造化データ"))
    cand_path = tasks_dir / "candidates.json"
    candidates = sc._read_list(cand_path, "candidates")
    tasks = sc._read_list(tasks_dir / "tasks.json", "tasks")
    rejected = sc._read_list(tasks_dir / "rejected.json", "rejected")
    known = {x.get("source_ref") for x in (*candidates, *tasks, *rejected) if x.get("source_ref")}
    fresh, counts = build_candidates(source["file"], items, known, sc._next_number(candidates))
    minutes = render_minutes(source, items, excluded)
    minutes_path = out_dir / f"{Path(source['file']).stem}-minutes.md"
    if not dry_run:
        out_dir.mkdir(parents=True, exist_ok=True)
        if minutes_path.exists():  # EM が手で直した下書きを黙って上書きしない
            sc._atomic_write_bytes(minutes_path.with_name(minutes_path.name + ".bak"), minutes_path.read_bytes())
        sc._atomic_write_bytes(minutes_path, minutes.encode("utf-8"))
        if fresh:
            tasks_dir.mkdir(parents=True, exist_ok=True)
            if cand_path.exists():
                sc._atomic_write_bytes(tasks_dir / BACKUP_NAME, cand_path.read_bytes())
            body = json.dumps({"version": 1, "candidates": [*candidates, *fresh]}, ensure_ascii=False, indent=1) + "\n"
            sc._atomic_write_bytes(cand_path, body.encode("utf-8"))
    return fresh, counts, minutes, minutes_path


def summary(counts, dry_run, minutes_path):
    verb, cand_verb = ("作成予定", "追加予定（--dry-run: 書き込みなし）") if dry_run else ("作成", "追加")
    return (f"議事録下書きを{verb}: {minutes_path.name} / タスク候補を {counts['added']} 件{cand_verb}"
            f" / 既出 {counts['duplicate']} 件・対象外 {counts['not_eligible']} 件")


def main(argv=None):
    ap = argparse.ArgumentParser(description="会議メモ構造化データ → 議事録下書き + タスク候補")
    ap.add_argument("structured", type=Path, help="data/structured/meeting/<file>.json")
    ap.add_argument("--tasks-dir", type=Path, default=Path("data/tasks"))
    ap.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    try:
        fresh, counts, minutes, minutes_path = ingest(args.structured, args.tasks_dir, args.out_dir, args.dry_run)
    except sc.IngestError as exc:
        print(f"取り込みを中止しました: {exc}", file=sys.stderr)
        return 1
    print(summary(counts, args.dry_run, minutes_path))
    for c in fresh:
        print(f"- {c['id']} {c['title']}（出典 {c['source_ref']}）")
    if args.dry_run:
        print("\n" + minutes)
    return 0


if __name__ == "__main__":
    sys.exit(main())
