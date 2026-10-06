#!/usr/bin/env python3
"""下書き（Slack 返信案・Jira コメント案）を templates/drafts の型に流し込み、未送信の下書きとして保存する。

L1（下書きまで）。stdlib のみ・外部接続なし。送信・投稿はしない。設計: templates/drafts/*.md と docs/design/14。
入力 JSON は秘書（Claude）が組み立てる。このスクリプトは型への流し込みと 14 の機械検査（E1/E2/B4/D1 相当）だけを行う。
検査に落ちたら何も書かない。
"""
import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT_DIR = ROOT / "data" / "outputs" / "drafts"
BANNER = "【下書き・未送信】"
MAX_VARIANTS = 2
MAX_BODY_CHARS = 300
BANNED = re.compile(r"送信しました|更新しました|送りました|投稿しました|遅い人|やる気がない|低パフォーマー|おそらく")
# 約束・催促になる語は本文に入れず ⟦EM が決める⟧ に寄せる（E2）
COMMITMENT = re.compile(r"までにお願い|までにやります|担当します|対応します|お約束")
SENSITIVE = re.compile(r"https?://|xox[bp]-|token", re.I)
HANDLE = re.compile(r"(member|m|em|ex)[-_][A-Za-z0-9]{1,12}", re.ASCII)
MARKERS = ("■", "⟦", "⟧", BANNER, "出典:", "出典：", "対象:", "対象：", "観察:", "観察：")  # 型の見出しを本文で偽造させない
MAX_EM_DECIDES = 5
QUESTION = re.compile(r"[？?]|か。")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

SCENES = {
    "slack-reply": {
        "types": ("回答", "受領のみ", "確認質問", "期限の相談"),
        "type_label": "返信の型",
        "source_keys": ("source_date", "source_id", "handle"),
    },
    "jira-comment": {
        "types": ("状況確認", "ブロッカー確認", "仕様確認", "完了確認"),
        "type_label": "コメントの型",
        "source_keys": ("ticket_key", "handle", "observation"),
    },
}


class DraftError(Exception):
    """EM に返す理由つきの拒否。"""


def _need(data, key):
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise DraftError(f"{key} が空です")
    return value.strip()


def _check_text(label, text, single_line=True):
    if single_line and ("\n" in text or "\r" in text):
        raise DraftError(f"{label} に改行は使えません")
    if any(m in text for m in MARKERS):
        raise DraftError(f"{label} に型の見出し用の文字列（■ ⟦ ⟧ 出典: 等）は使えません")
    if len(text) > MAX_BODY_CHARS:
        raise DraftError(f"{label} が {MAX_BODY_CHARS} 字を超えています")
    if BANNED.search(text):
        raise DraftError(f"{label} に送信済み表現・評価語・推測語があります")
    if COMMITMENT.search(text):
        raise DraftError(f"{label} に約束・催促の語があります。⟦EM が決める⟧ に寄せてください")
    if SENSITIVE.search(text):
        raise DraftError(f"{label} に URL・トークンらしき文字列があります")


def validate(scene, data):
    if scene not in SCENES:
        raise DraftError(f"未対応の場面です: {scene}（対応: {', '.join(SCENES)}）")
    spec = SCENES[scene]
    if not isinstance(data, dict):
        raise DraftError("入力は JSON オブジェクトにしてください")
    draft_type = _need(data, "type")
    if draft_type not in spec["types"]:
        raise DraftError(f"type は {'/'.join(spec['types'])} のいずれか: {draft_type}")
    for key in spec["source_keys"]:
        _check_text(key, _need(data, key))
    handle = _need(data, "handle")
    if not HANDLE.fullmatch(handle):
        raise DraftError(f"handle は匿名ハンドルにしてください: {handle}")
    if scene == "slack-reply" and not DATE_RE.match(_need(data, "source_date")):
        raise DraftError("source_date は YYYY-MM-DD にしてください")
    variants = data.get("variants")
    if not isinstance(variants, list) or not 1 <= len(variants) <= MAX_VARIANTS:
        raise DraftError(f"variants は 1〜{MAX_VARIANTS} 案にしてください")
    for i, body in enumerate(variants, 1):
        if not isinstance(body, str) or not body.strip():
            raise DraftError(f"variants[{i}] が空です")
        _check_text(f"variants[{i}]", body, single_line=False)
        if scene == "jira-comment" and len(QUESTION.findall(body)) > 1:
            raise DraftError(f"variants[{i}] は 1 コメント 1 問にしてください")
    decides = data.get("em_decides")
    if not isinstance(decides, list) or not 1 <= len(decides) <= MAX_EM_DECIDES:
        raise DraftError(f"em_decides は 1〜{MAX_EM_DECIDES} 件にしてください。なければ「なし」と 1 件書いてください")
    for i, item in enumerate(decides, 1):
        if not isinstance(item, str) or not item.strip():
            raise DraftError(f"em_decides[{i}] は空でない文字列にしてください")
        _check_text(f"em_decides[{i}]", item)
    return draft_type


def render(scene, data):
    draft_type = validate(scene, data)
    spec = SCENES[scene]
    head = f"{BANNER}{spec['type_label']}: {draft_type}"
    if scene == "slack-reply":
        head += f"\n出典: {data['source_date']}:{data['source_id']}（相手: {data['handle']}）"
    else:
        head += f"\n対象: {data['ticket_key']}（担当: {data['handle']}）\n観察: {data['observation']}"
    labels = ("案A（短く）", "案B（丁寧に）")
    body = [f"■ {labels[i]}\n{text.strip()}" for i, text in enumerate(data["variants"])]
    decides = "\n".join(f"- {item}" for item in data["em_decides"])
    return f"{head}\n\n" + "\n\n".join(body) + f"\n\n⟦EM が決める⟧\n{decides}\n"


def write_draft(out_dir, scene, text, today):
    out_dir.mkdir(parents=True, exist_ok=True)
    n = 1
    while True:
        path = out_dir / f"{today.isoformat()}-{scene}-{n:02d}.md"
        try:
            # 排他作成（O_EXCL）。既存ファイル・symlink があれば開けず、番号を進める
            with open(path, "x", encoding="utf-8") as fh:
                fh.write(text)
            return path
        except FileExistsError:
            n += 1


def main(argv=None):
    ap = argparse.ArgumentParser(description="未送信の下書き（Slack 返信案・Jira コメント案）を作る")
    ap.add_argument("scene", choices=sorted(SCENES))
    ap.add_argument("input", type=Path, help="下書き入力 JSON（匿名化済み）")
    ap.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    ap.add_argument("--today", type=date.fromisoformat, default=None)
    ap.add_argument("--dry-run", action="store_true", help="保存せず標準出力に出す")
    args = ap.parse_args(argv)
    try:
        data = json.loads(args.input.read_text(encoding="utf-8"))
        text = render(args.scene, data)
    except FileNotFoundError:
        print(f"入力が見つかりません: {args.input}", file=sys.stderr)
        return 1
    except json.JSONDecodeError as exc:
        print(f"入力 JSON が壊れています（{exc.msg}）。何も書いていません", file=sys.stderr)
        return 1
    except DraftError as exc:
        print(f"下書きを作りませんでした: {exc}", file=sys.stderr)
        return 1
    if args.dry_run:
        print(text, end="")
        return 0
    path = write_draft(args.out_dir, args.scene, text, args.today or date.today())
    print(f"下書きを保存しました（未送信・送信は EM）: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
