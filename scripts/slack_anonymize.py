#!/usr/bin/env python3
"""Slack 前処理済み（parsed/）を匿名化して anon/ に書く（13 §5）。ローカルのみ・stdlib のみ・外部接続なし。

- 名簿（config/local.roster.json）の名前を m_ + HMAC-SHA256(鍵, 正規化名) の先頭 6 桁に置換。EM は固定ハンドル em。
- 名簿外の人名らしきものが残ったら**何も書かず停止**する（件数とメッセージ ID だけ報告。語は出さない）。
- 鍵（環境変数 EM_HARNESS_ANON_KEY）・名簿が無い／不正なら止める（fail-closed）。
- anon を読む側は load_anon() だけを使う。anon/ 直下の匿名化済みマーカー付きファイル以外（raw 相当の parsed/ 等）は読まない。
- 14 日を過ぎた anon は load_anon() が拒否する（削除は未実装。13 §8）。
"""
import argparse
import hashlib
import hmac
import json
import os
import re
import sys
import time
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ROSTER = ROOT / "config" / "local.roster.json"
DEFAULT_ANON_DIR = ROOT / "data" / "inbox" / "slack" / "anon"
KEY_ENV = "EM_HARNESS_ANON_KEY"
EM_HANDLE = "em"
HANDLE_DIGITS = 6
MIN_NAME_LEN = 2
RETENTION_DAYS = 14
ANON_KIND = "slack_anon"
ASCII_WORD = "A-Za-z0-9_"
HANDLE_RE = re.compile(r"^(?:em|m_[0-9a-f]{6})$")
URL_RE = re.compile(r"https?://\S+")
# 名簿外の人名らしきもの（語は報告しない）。\b は CJK を語文字扱いするので ASCII の lookaround を使う
LATIN_NAME_RE = re.compile(rf"(?<![{ASCII_WORD}])[A-Z][a-z]+(?:[ \t]+[A-Z][a-z]+)+(?![{ASCII_WORD}])")
LATIN_HONORIFIC_RE = re.compile(rf"(?<![{ASCII_WORD}])[A-Z][a-z]+(?:-san|-sama|-kun|-chan|さん|様|くん|君)")
CJK_HONORIFIC_RE = re.compile(r"[一-鿿ァ-ヿー]{1,8}(?:さん|様|くん|君|氏|先生)")
MENTION_RE = re.compile(r"@([^\s@,，、。]+)")
SAFE_MENTIONS = frozenset({"here", "channel", "everyone"})
DEFAULT_ALLOW = ("皆さん", "みなさん", "お客様", "皆様", "各位", "担当者様")


class AnonymizeError(Exception):
    """EM に返す理由つきの拒否。人名の中身は含めない。"""


def _normalize(text):
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", text).casefold()).strip()


def _handle(key, name):
    return "m_" + hmac.new(key.encode("utf-8"), _normalize(name).encode("utf-8"), hashlib.sha256).hexdigest()[:HANDLE_DIGITS]


def _string_list(value, label):
    if not isinstance(value, list) or not all(isinstance(v, str) and v.strip() for v in value):
        raise AnonymizeError(f"名簿の {label} は空でない文字列の配列にしてください")
    return [v.strip() for v in value]


def load_roster(path, key):
    """名簿を読み、{正規化名: ハンドル} と orgs / allow を返す。不正は理由だけ返す。"""
    if not key:
        raise AnonymizeError(f"環境変数 {KEY_ENV} が未設定です（鍵なしでは匿名化しません）")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise AnonymizeError(f"名簿が見つかりません: {path}（config/templates/local.roster.json.example を参照）")
    except (ValueError, UnicodeDecodeError, OSError):
        raise AnonymizeError(f"名簿を JSON として読めません: {path}")
    if not isinstance(data, dict) or not isinstance(data.get("em"), dict) or not isinstance(data.get("people"), list):
        raise AnonymizeError("名簿は {em: {names}, people: [{names}]} の形にしてください")
    groups = [(EM_HANDLE, _string_list(data["em"].get("names"), "em.names"))]
    people = [_string_list(p.get("names") if isinstance(p, dict) else None, "people[].names") for p in data["people"]]
    handles = {}
    for names in people:
        handle = _handle(key, names[0])
        if handle in handles:
            raise AnonymizeError("名簿内でハンドルが衝突しました（同一人物の重複か、まれな衝突）。名簿を見直してください")
        handles[handle] = names
        groups.append((handle, names))
    mapping = {}
    for handle, names in groups:
        for name in names:
            norm = _normalize(name)
            if len(norm) < MIN_NAME_LEN:
                raise AnonymizeError(f"名簿の名前は {MIN_NAME_LEN} 文字以上にしてください（短い名前は普通の語を誤置換する）")
            if mapping.get(norm, handle) != handle:
                raise AnonymizeError("名簿で同じ名前が複数人に載っています。重複を直してください")
            mapping[norm] = handle
    orgs = _string_list(data.get("orgs", []), "orgs")
    allow = _string_list(data.get("allow_words", []), "allow_words")
    return {"mapping": mapping, "orgs": orgs, "allow": [*DEFAULT_ALLOW, *allow]}


def _name_pattern(name):
    parts = [re.escape(p) for p in _normalize(name).split(" ")]
    body = r"[ \t]+".join(parts)
    if re.fullmatch(rf"[{ASCII_WORD} ]+", _normalize(name)):
        return rf"(?<![{ASCII_WORD}]){body}(?![{ASCII_WORD}])"
    return body


def _compile(names):
    if not names:
        return None
    ordered = sorted(names, key=len, reverse=True)
    return re.compile("|".join(f"(?:{_name_pattern(n)})" for n in ordered), re.IGNORECASE)


def mask(text, roster):
    """URL・org・名簿の名前を置換した新しい文字列を返す。"""
    text = URL_RE.sub("[URL]", unicodedata.normalize("NFKC", text))
    org_re = _compile([_normalize(o) for o in roster["orgs"]])
    if org_re:
        text = org_re.sub("[org]", text)
    name_re = _compile(list(roster["mapping"]))
    return name_re.sub(lambda m: roster["mapping"][_normalize(m.group(0))], text)


def count_suspects(masked, roster):
    """置換後に残った名簿外の人名らしきものの数。"""
    scrubbed = masked
    for phrase in roster["allow"]:
        scrubbed = scrubbed.replace(phrase, " ")
    mentions = [m for m in MENTION_RE.findall(scrubbed) if not (HANDLE_RE.match(m) or m in SAFE_MENTIONS)]
    return (len(mentions) + len(LATIN_NAME_RE.findall(scrubbed)) + len(LATIN_HONORIFIC_RE.findall(scrubbed))
            + len(CJK_HONORIFIC_RE.findall(scrubbed)))


def _speaker_unmapped(masked_speaker):
    return not HANDLE_RE.match(masked_speaker.strip())


def anonymize(parsed, roster):
    """純粋関数。parsed（前処理出力）→ anon dict。名簿外の人名らしきものが残れば AnonymizeError。"""
    if parsed.get("skipped") is not None:
        raise AnonymizeError("スキップ済みの貼り付けは匿名化しません")
    messages, flagged = [], []
    for message in parsed.get("messages", []):
        speaker, text = mask(message["speaker"], roster), mask(message["text"], roster)
        hits = count_suspects(text, roster) + (1 if _speaker_unmapped(speaker) else 0)
        if hits:
            flagged.append((message["id"], hits))
        messages.append({"id": message["id"], "speaker": speaker, "time": message["time"], "text": text})
    if flagged:
        ids = ", ".join(i for i, _ in flagged)
        total = sum(n for _, n in flagged)
        raise AnonymizeError(f"名簿外の人名の疑いが {total} 件残っています（メッセージ {ids}）。"
                             "名簿に追加するか、普通の語なら allow_words に足してから再実行してください。何も書いていません")
    meta = {k: mask(str(v), roster) for k, v in parsed.get("meta", {}).items()}
    return {"schema_version": 1, "kind": ANON_KIND, "anonymized": True,
            "source": {"file": parsed["source"]["file"], "text_sha256": parsed.get("text_sha256")},
            "meta": meta, "messages": messages, "unmasked_suspects": 0, "notes": list(parsed.get("notes", []))}


def load_anon(path, anon_dir=DEFAULT_ANON_DIR, now=None):
    """anon を読む唯一の入口。anon/ 直下（シンボリックリンク解決後）の匿名化済みマーカー付きファイルだけ読む。"""
    resolved = Path(path).resolve()
    if resolved.parent != Path(anon_dir).resolve():
        raise AnonymizeError("anon/ 直下のファイル以外は読みません（raw 相当は対象外）")
    if (now if now is not None else time.time()) - resolved.stat().st_mtime > RETENTION_DAYS * 86400:
        raise AnonymizeError(f"保持期間（{RETENTION_DAYS} 日）を過ぎた匿名化済みファイルは読みません")
    try:
        data = json.loads(resolved.read_text(encoding="utf-8"))
    except (ValueError, UnicodeDecodeError):
        raise AnonymizeError("匿名化済みファイルを JSON として読めません")
    if not isinstance(data, dict) or data.get("kind") != ANON_KIND or data.get("anonymized") is not True:
        raise AnonymizeError("匿名化済みマーカーがないファイルは読みません")
    return data


def run(parsed_path, roster_path, anon_dir, key, dry_run):
    roster = load_roster(roster_path, key)
    try:
        parsed = json.loads(Path(parsed_path).read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeDecodeError):
        raise AnonymizeError(f"前処理済みファイルを読めません: {parsed_path}")
    if not isinstance(parsed, dict) or "messages" not in parsed or "source" not in parsed:
        raise AnonymizeError("前処理済み（slack_preprocess の出力）ではありません")
    out = anonymize(parsed, roster)
    if not dry_run:
        target = Path(anon_dir) / Path(parsed_path).name
        if target.exists():
            raise AnonymizeError(f"出力先が既にあります。上書きしません: {target.name}")
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(target.name + ".tmp")
        tmp.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        os.replace(tmp, target)
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(description="Slack 前処理済み JSON の匿名化（名簿外の人名が残れば停止）")
    parser.add_argument("parsed", type=Path, help="data/inbox/slack/parsed/ の前処理済み JSON")
    parser.add_argument("--roster", type=Path, default=DEFAULT_ROSTER)
    parser.add_argument("--anon-dir", type=Path, default=DEFAULT_ANON_DIR)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    try:
        out = run(args.parsed, args.roster, args.anon_dir, os.environ.get(KEY_ENV, ""), args.dry_run)
    except AnonymizeError as exc:
        print(f"中止: {exc}", file=sys.stderr)
        return 2
    print(f"匿名化 {len(out['messages'])} 件{'（dry-run: 書き込みなし）' if args.dry_run else ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
