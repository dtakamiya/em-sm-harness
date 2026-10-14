#!/usr/bin/env python3
"""会議メモの貼り付け（28 §2）を、機微語スキップ → 匿名化 → inbox 形式で書き出す前処理（emh-077）。

ローカルのみ・stdlib のみ・外部接続なし。設計: docs/design/28-meeting-notes-input.md §1〜§2 / §4。
部品は Slack 側（slack_preprocess の機微語判定・front matter 解釈、slack_anonymize の名簿置換・人名検知・
排他的書込）をそのまま使う。ここに置くのは会議メモ固有の「front matter 検証・行単位の検知・出力名」だけ。
- 機微語に当たるメモは何も書かず止める（人事系はファイルごとスキップ。語は出さない）。
- 名簿外の人名らしきものが残れば何も書かず停止する（行番号と件数だけ報告。語は出さない）。
- 出力は匿名化済みの 28 §2 形式（`<held_on>-<meeting_alias>.md`）。入力ファイル名は出力に持ち込まない。
"""
import argparse
import os
import re
import sys
from pathlib import Path

import slack_anonymize as sa
import slack_preprocess as sp

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT_DIR = ROOT / "data" / "inbox" / "meeting"
MEETING_KEYS = ("meeting_alias", "held_on")
ALIAS_RE = re.compile(r"[a-z0-9][a-z0-9-]{0,39}")
DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
LINE_SOFT_LIMIT = 200  # 28 §2: これを超えるメモは分割を促す


def _fail(message):
    raise sa.AnonymizeError(message)


def check_meta(meta):
    """出力名に使う 2 キーを検証する。別名は実会議名を出さないための設定上の名前（28 §2）。"""
    missing = [k for k in MEETING_KEYS if not meta.get(k)]
    if missing:
        _fail(f"front matter に {', '.join(missing)} が必要です（28 §2。例: meeting_alias: ex-planning）")
    if not ALIAS_RE.fullmatch(meta["meeting_alias"]):
        _fail("meeting_alias は英小文字・数字・ハイフンの別名にしてください（実会議名はファイル名に出しません）")
    if not DATE_RE.fullmatch(meta["held_on"]):
        _fail("held_on は YYYY-MM-DD にしてください")
    return {k: meta[k] for k in MEETING_KEYS}


def anonymize_note(raw, roster, words):
    """純粋関数。(匿名化済み本文, 本文の空でない行数) を返す。機微語・名簿外の人名は例外。"""
    text = raw.replace("\r\n", "\n").replace("\r", "\n")
    if sp.is_sensitive(text, words):
        _fail("人事系の可能性があるので秘書は読みません（何も書いていません）")
    meta, body = sp.split_front_matter(text, MEETING_KEYS)
    meta = check_meta(meta)
    lines = [sa.mask(line, roster).rstrip() for line in body.splitlines()]
    flagged = [(n, sa.count_suspects(line, roster))
               for n, line in enumerate((l for l in lines if l.strip()), start=1)]
    flagged = [(n, hits) for n, hits in flagged if hits]
    if flagged:
        rows = ", ".join(f"{n} 行目" for n, _ in flagged)
        _fail(f"名簿外の人名の疑いが {sum(h for _, h in flagged)} 件残っています（{rows}）。"
              "名簿に追加するか、普通の語なら allow_words に足してから再実行してください。何も書いていません")
    front = "\n".join(f"{k}: {meta[k]}" for k in MEETING_KEYS)
    count = sum(1 for line in lines if line.strip())
    return f"---\n{front}\n---\n" + "\n".join(lines).strip("\n") + "\n", meta, count


def run(paste_path, roster_path, words_file, out_dir, key, dry_run):
    roster = sa.load_roster(roster_path, key)
    try:
        words = sp.load_sensitive_words(words_file)
        raw = sp._read_text(paste_path, "貼り付けファイル")
    except sp.PreprocessError as exc:
        _fail(str(exc))
    text, meta, count = anonymize_note(raw, roster, words)
    target = Path(out_dir) / f"{meta['held_on']}-{meta['meeting_alias']}.md"
    if not dry_run:
        sa.write_new_private(target, text)
    return {"file": target.name, "line_count": count, "over_limit": count > LINE_SOFT_LIMIT}


def main(argv=None):
    parser = argparse.ArgumentParser(description="会議メモ貼り付けの前処理（機微語スキップ・匿名化。名簿外の人名が残れば停止）")
    parser.add_argument("paste", type=Path, help="EM が貼った会議メモ（front matter に meeting_alias / held_on）")
    parser.add_argument("--roster", type=Path, default=sa.DEFAULT_ROSTER)
    parser.add_argument("--words-file", type=Path, default=sp.DEFAULT_WORDS_FILE)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    try:
        out = run(args.paste, args.roster, args.words_file, args.out_dir, os.environ.get(sa.KEY_ENV, ""), args.dry_run)
    except sa.AnonymizeError as exc:
        print(f"中止: {exc}", file=sys.stderr)
        return 2
    except Exception:  # 想定外でも例外文（名前を含み得る）は出さない
        print("中止: 内部エラー（詳細は出しません。何も書いていない可能性が高いので出力先を確認してください）", file=sys.stderr)
        return 2
    note = f"。{LINE_SOFT_LIMIT} 行を超えています。分割してください（28 §2）" if out["over_limit"] else ""
    print(f"匿名化 {out['line_count']} 行 → {out['file']}{'（dry-run: 書き込みなし）' if args.dry_run else ''}{note}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
