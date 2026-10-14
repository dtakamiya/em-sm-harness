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
from datetime import date
from pathlib import Path

import slack_anonymize as sa
import slack_preprocess as sp

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT_DIR = ROOT / "data" / "inbox" / "meeting"
ALLOWED_OUT_ROOT = DEFAULT_OUT_DIR  # 出力はここ（gitignore 済みの data/ 配下）の中だけ。テストは差し替える
MEETING_KEYS = ("meeting_alias", "held_on")
ALIAS_RE = re.compile(r"[a-z0-9][a-z0-9-]{0,39}")
DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}", re.ASCII)
# 会議メモ特有の行頭「名前: 発言」。置換後にハンドル・既知ラベル以外が残れば名簿外の人名の疑いとして数える
SPEAKER_HEAD_RE = re.compile(r"^\s*(?:[-*・]\s*|\d+[.)]\s*)?(?P<head>[^:：、。]{1,24}?)\s*[:：]\s*\S")
PAREN_RE = re.compile(r"\s*[（(][^()（）]*[)）]")  # 「山田 (PM)」の役割括弧は外して名前だけ見る
CJK_WORD = r"[一-鿿ぁ-ゟァ-ヿー]{1,8}"
LATIN_WORD = r"[A-Za-z][A-Za-z.'-]*"
SPEAKER_HEAD_NAME_RE = re.compile(rf"{CJK_WORD}(?: {CJK_WORD})?|{LATIN_WORD}(?: {LATIN_WORD}){{0,2}}")
LABEL_WORDS = frozenset(w.casefold() for w in (
    "決定", "アクション", "未決", "議題", "備考", "注意", "結論", "課題", "確認", "宿題", "次回", "共有", "報告", "質問",
    "担当", "期限", "参加者", "出席", "欠席", "日時", "日付", "時間", "場所", "背景", "目的", "目標", "議事", "概要", "対応",
    "理由", "進捗", "状況", "内容", "資料", "リスク", "懸念", "補足", "要約", "まとめ", "次のアクション", "決定事項", "確認事項",
    "owner", "due", "status", "date", "time", "location", "attendees", "absent", "summary", "background", "purpose",
    "goal", "issue", "risk", "result", "progress", "reason", "decisions", "actions", "agenda", "decision", "action",
    "todo", "note", "notes", "memo", "next", "http", "https"))
EXISTS_MESSAGE = "同名の匿名化済みファイルが既にあります。上書きしないので、別名にするか既存を EM が退避してから再実行してください"
LINE_SOFT_LIMIT = 200  # 28 §2: これを超えるメモは分割を促す


def _fail(message):
    raise sa.AnonymizeError(message)


def check_out_dir(out_dir, allowed_root=None):
    """出力先は ALLOWED_OUT_ROOT（data/ 配下）の中に限る。.. やシンボリックリンクも解決して判定する。"""
    allowed = Path(allowed_root or ALLOWED_OUT_ROOT).resolve()
    resolved = Path(out_dir).resolve()
    if resolved != allowed and allowed not in resolved.parents:
        _fail("出力先は data/inbox/meeting/ 配下に限ります（実データを repo の追跡対象に置かないため）")
    return resolved


def speaker_head_suspects(line, roster):
    """行頭「名前: 発言」の名前が、ハンドル・既知ラベル・allow_words のどれでもなければ 1（敬称なしの人名を拾う）。"""
    match = SPEAKER_HEAD_RE.match(line)
    if not match:
        return 0
    head = PAREN_RE.sub("", match.group("head")).strip()
    if not SPEAKER_HEAD_NAME_RE.fullmatch(head) or sa.HANDLE_RE.match(head):
        return 0
    known = {w.casefold() for w in roster["allow"]} | LABEL_WORDS
    return 0 if head.casefold() in known else 1


def check_meta(meta):
    """出力名に使う 2 キーを検証する。別名は実会議名を出さないための設定上の名前（28 §2）。"""
    missing = [k for k in MEETING_KEYS if not meta.get(k)]
    if missing:
        _fail(f"front matter に {', '.join(missing)} が必要です（28 §2。例: meeting_alias: ex-planning）")
    if not ALIAS_RE.fullmatch(meta["meeting_alias"]):
        _fail("meeting_alias は英小文字・数字・ハイフンの別名にしてください（実会議名はファイル名に出しません）")
    try:
        if not DATE_RE.fullmatch(meta["held_on"]):
            raise ValueError
        date.fromisoformat(meta["held_on"])
    except ValueError:
        _fail("held_on は実在する日付を YYYY-MM-DD で書いてください")
    return {k: meta[k] for k in MEETING_KEYS}


def anonymize_note(raw, roster, words):
    """純粋関数。(匿名化済み本文, 検証済み front matter, 本文の空でない行数) を返す。機微語・名簿外の人名は例外。"""
    text = raw.replace("\r\n", "\n").replace("\r", "\n")
    if sp.is_sensitive(text, words):
        _fail("人事系の可能性があるので秘書は読みません（何も書いていません）")
    meta, body = sp.split_front_matter(text, MEETING_KEYS)
    meta = check_meta(meta)
    lines = [sa.mask(line, roster).rstrip() for line in body.splitlines()]
    offset = text[:len(text) - len(body)].count("\n")  # front matter の行数。報告は元ファイルの行番号にする
    flagged = [(offset + n, sa.count_suspects(line, roster) + speaker_head_suspects(line, roster))
               for n, line in enumerate(lines, start=1) if line.strip()]
    flagged = [(n, hits) for n, hits in flagged if hits]
    if flagged:
        rows = ", ".join(f"元ファイルの {n} 行目" for n, _ in flagged)
        _fail(f"名簿外の人名の疑いが {sum(h for _, h in flagged)} 件残っています（{rows}）。"
              "名簿に追加するか、普通の語なら allow_words に足してから再実行してください。何も書いていません")
    front = "\n".join(f"{k}: {meta[k]}" for k in MEETING_KEYS)
    count = sum(1 for line in lines if line.strip())
    return f"---\n{front}\n---\n" + "\n".join(lines).strip("\n") + "\n", meta, count


def _read_paste(path):
    """読めないときの理由にパスを含めない（ファイル名に実名が入り得る）。"""
    try:
        return Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        _fail("貼り付けファイルを読めません（存在・UTF-8・ディレクトリでないことを確認してください。パスは表示しません）")


def run(paste_path, roster_path, words_file, out_dir, key, dry_run):
    out_dir = check_out_dir(out_dir)
    roster = sa.load_roster(roster_path, key)
    try:
        words = sp.load_sensitive_words(words_file)
    except sp.PreprocessError as exc:
        _fail(str(exc))
    raw = _read_paste(paste_path)
    text, meta, count = anonymize_note(raw, roster, words)
    target = Path(out_dir) / f"{meta['held_on']}-{meta['meeting_alias']}.md"
    if target.exists():
        _fail(EXISTS_MESSAGE)
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
