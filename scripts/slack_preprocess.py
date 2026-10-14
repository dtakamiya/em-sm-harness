#!/usr/bin/env python3
"""Slack 貼り付け（13 §4）をメッセージ単位に分解し、重複の除外と機微語ファイルのスキップを行う前処理。

ローカルのみ・stdlib のみ・外部接続なし。設計: docs/design/13-slack-paste-input.md §4 / §8 / §10-1。
匿名化はここでは行わない（別項目）。出力は raw 相当なので data/ 配下（gitignore）にだけ書く。
- 機微語に当たる貼り付けは skipped="sensitive" とし、メッセージを一切出さない（語は報告にも出さない）。
- 同一貼り付け（text_sha256）は取り込まない。重なる再貼り付けはメッセージ単位のハッシュで既出を除外する。
- 機微語ファイルが無い／空のときは止める（fail-closed。判定できないまま通さない）。
- 解釈できない行は捨てず unparsed_lines に数だけ残す（誤抽出より取りこぼしを選ぶ）。
"""
import argparse
import hashlib
import json
import os
import re
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_WORDS_FILE = ROOT / "config" / "local.sensitive-words.txt"
DEFAULT_OUT_DIR = ROOT / "data" / "inbox" / "slack" / "parsed"
LEDGER_NAME = ".seen.json"
MESSAGE_SOFT_LIMIT = 300  # 13 §4: これを超える貼り付けは分割を促す
FRONT_MATTER = re.compile(r"\A---\n(.*?)\n---\n", re.DOTALL)
# 発言者は短い名前だけ（文末記号を含む本文行の誤認を避ける）。区切りは 2 個以上の空白かタブ（13 §4 の例）
SPEAKER_MAX = 40
HEADER = re.compile(r"^(?P<speaker>[^\s。、，．！？!?;；「」『』()（）][^。、，．！？!?;；「」『』]*?)(?:\t|\s{2,})(?P<time>\d{1,2}:\d{2}(?:\s?[AP]M)?)\s*$")
META_LINE = re.compile(r"^(?P<key>[a-z_]+):\s*(?P<value>[^#]*?)\s*(?:#.*)?$")
META_KEYS = ("channel_alias", "thread", "pasted_on")


class PreprocessError(Exception):
    """EM に返す理由つきの拒否。"""


def _sha256(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _read_text(path, label):
    """読めないときは理由だけ返す。不正バイト列の断片は出さない。"""
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise PreprocessError(f"{label}が見つかりません: {path}")
    except UnicodeDecodeError:
        raise PreprocessError(f"{label}が UTF-8 として読めません: {path}")
    except IsADirectoryError:
        raise PreprocessError(f"{label}にディレクトリが指定されています: {path}")
    except OSError as exc:
        raise PreprocessError(f"{label}を読めません（{type(exc).__name__}）: {path}")


def _fold(text):
    """機微語照合用の正規化。全角半角・大小・空白・制御・ゼロ幅文字の差で取りこぼさない。"""
    folded = unicodedata.normalize("NFKC", text).casefold()
    return "".join(c for c in folded if not c.isspace() and unicodedata.category(c) not in ("Cc", "Cf"))


def load_sensitive_words(path):
    lines = _read_text(path, "機微語ファイル").splitlines()
    words = [w.strip() for w in lines if w.strip() and not w.lstrip().startswith("#")]
    words = [f for f in (_fold(w) for w in words) if f]
    if not words:
        raise PreprocessError(f"機微語ファイルが空です: {path}（判定できないので止めます）")
    return words


def is_sensitive(text, words):
    folded = _fold(text)
    return any(w in folded for w in words)


def split_front_matter(text):
    """先頭の任意見出し（--- で囲む）を読む。既知キー以外は無視する。"""
    match = FRONT_MATTER.match(text)
    if not match:
        return {}, text
    meta = {}
    for line in match.group(1).splitlines():
        m = META_LINE.match(line.strip())
        if m and m.group("key") in META_KEYS:
            meta[m.group("key")] = m.group("value")
    return meta, text[match.end():]


def parse_messages(body):
    """「発言者 + 時刻」行 + 本文行の繰り返しとして緩く解釈する。戻りは (messages, 未解釈行数)。"""
    messages, unparsed, current = [], 0, None
    for line in body.splitlines():
        header = HEADER.match(line)
        if header and len(header.group("speaker").strip()) <= SPEAKER_MAX:
            current = {"speaker": header.group("speaker").strip(), "time": header.group("time").strip(), "lines": []}
            messages.append(current)
        elif current is not None:
            current["lines"].append(line.rstrip())
        elif line.strip():
            unparsed += 1  # 最初の見出し行より前の行
    parsed = []
    for m in messages:
        text = "\n".join(m["lines"]).strip()
        parsed.append({"speaker": m["speaker"], "time": m["time"], "text": text,
                       "msg_sha256": _sha256(f"{m['speaker']}\0{m['time']}\0{text}")})
    return parsed, unparsed


def _read_ledger(path):
    if not path.exists():
        return {"files": [], "messages": []}
    try:
        data = json.loads(_read_text(path, "既出台帳"))
        if isinstance(data.get("files"), list) and isinstance(data.get("messages"), list):
            return data
    except (ValueError, AttributeError):
        pass
    raise PreprocessError(f"既出台帳 {path.name} が壊れています。上書きはしません")


def _atomic_write(path, body):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(body, encoding="utf-8")
    os.replace(tmp, path)


def _dump(data):
    return json.dumps(data, ensure_ascii=False, indent=1) + "\n"


def preprocess(paste_path, words, ledger):
    """純粋関数。(出力 dict, 更新後の台帳 or None) を返す。台帳が None のときは更新しない。"""
    raw = _read_text(paste_path, "貼り付けファイル").replace("\r\n", "\n").replace("\r", "\n")
    base = {"schema_version": 1, "source": {"file": paste_path.name}, "text_sha256": _sha256(raw),
            "skipped": None, "meta": {}, "messages": [], "duplicates_excluded": 0, "unparsed_lines": 0, "notes": []}
    if is_sensitive(raw, words):
        return {**base, "skipped": "sensitive", "text_sha256": None,
                "notes": ["人事系の可能性があるので秘書は読みません"]}, None
    if base["text_sha256"] in ledger["files"]:
        return {**base, "skipped": "duplicate_paste", "notes": ["同一内容の貼り付けは取り込み済みです"]}, None
    meta, body = split_front_matter(raw)
    parsed, unparsed = parse_messages(body)
    known = set(ledger["messages"])
    fresh, seen = [], set()
    for message in parsed:
        digest = message["msg_sha256"]
        if digest in known or digest in seen:
            continue
        seen.add(digest)
        fresh.append({"id": f"m-{len(fresh) + 1:03d}", **message})
    excluded = len(parsed) - len(fresh)
    notes = []
    if unparsed:
        notes.append(f"未解釈 {unparsed} 行")
    if len(parsed) > MESSAGE_SOFT_LIMIT:
        notes.append(f"{len(parsed)} メッセージあります。{MESSAGE_SOFT_LIMIT} 程度を目安に分割してください")
    if not parsed:
        notes.append("メッセージを解釈できませんでした（発言者 + 時刻の行が見つかりません）")
    out = {**base, "meta": meta, "messages": fresh, "duplicates_excluded": excluded,
           "unparsed_lines": unparsed, "notes": notes}
    new_ledger = {"files": [*ledger["files"], base["text_sha256"]],
                  "messages": [*ledger["messages"], *(m["msg_sha256"] for m in fresh)]}
    return out, new_ledger


def output_path(out_dir, paste_path, text_sha256):
    """出力名に内容ハッシュを付け、同名の別貼り付けや台帳（.seen.json）を上書きしない。"""
    stem = paste_path.stem
    if not stem or stem.startswith("."):
        raise PreprocessError(f"貼り付けファイル名が不正です（空・先頭ドットは不可）: {paste_path.name}")
    return out_dir / f"{stem}-{text_sha256[:8]}.json"


def run(paste_path, words_file, out_dir, dry_run):
    words = load_sensitive_words(words_file)
    ledger_path = out_dir / LEDGER_NAME
    out, new_ledger = preprocess(paste_path, words, _read_ledger(ledger_path))
    if not dry_run and new_ledger is not None:
        target = output_path(out_dir, paste_path, out["text_sha256"])
        if target.exists():
            raise PreprocessError(f"出力先が既にあります。上書きしません: {target.name}")
        _atomic_write(target, _dump(out))
        _atomic_write(ledger_path, _dump(new_ledger))
    return out


def summary(out):
    if out["skipped"] == "sensitive":
        return "スキップ: 人事系の可能性があるので秘書は読みません（何も書いていません）"
    if out["skipped"]:
        return f"スキップ: {out['notes'][0]}"
    line = f"新規 {len(out['messages'])} 件 / 既出で除外 {out['duplicates_excluded']} 件 / 未解釈 {out['unparsed_lines']} 行"
    return "\n".join([line, *out["notes"]])


def main(argv=None):
    parser = argparse.ArgumentParser(description="Slack 貼り付けの前処理（分解・重複除外・機微語スキップ）")
    parser.add_argument("paste", type=Path, help="data/inbox/slack/ の貼り付けファイル")
    parser.add_argument("--words-file", type=Path, default=DEFAULT_WORDS_FILE, help="機微語ファイル（1 行 1 語）")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--dry-run", action="store_true", help="何も書かず結果だけ表示")
    args = parser.parse_args(argv)
    try:
        print(summary(run(args.paste, args.words_file, args.out_dir, args.dry_run)))
    except PreprocessError as exc:
        print(f"中止: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
