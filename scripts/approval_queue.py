#!/usr/bin/env python3
"""承認キュー（朝夕 1 枚）を data/actions の下書きから生成する。モック試作。

L1（下書きまで）。stdlib のみ・外部接続なし。Jira / Slack へは書かない。
書くのは標準出力と、本文なしの監査 2 種（queue_rendered / queue_item）のローカル追記だけ。
設計: docs/design/21-approval-queue.md、監査の書式は docs/design/26-trial-review-metrics.md §2。
入力: data/actions/*.json（1 ファイル 1 件。必須キーは REQUIRED）。壊れた・不正な入力は除外して stderr に出す（fail-closed）。
"""
import argparse
import json
import math
import re
import sys
import unicodedata
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_no_leak import INTERNAL_RES, TOKEN_RES, load_local_patterns  # noqa: E402
from make_draft import BANNER, MARKERS  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
MAX_INDIVIDUAL = 5
MAX_BULK = 5
URGENT_PRIORITY = "high"
PRIORITY_RANK = {"high": 0, "medium": 1, "low": 2}
BAND_SOON_DAYS = 3
MINUTES_PER_INDIVIDUAL = 1.0
MINUTES_PER_BULK = 0.25
REQUIRED = ("action_id", "kind", "title", "target", "body", "priority")
STAGES = ("none", "A", "B", "C")
NEXT_SLOT = {"morning": "夕", "evening": "翌朝"}
SLOT_LABEL = {"morning": "朝", "evening": "夕"}
MAX_EXPIRED = 5
MAX_PERSONAL = 5
MAX_TITLE_CHARS = 50
MAX_TARGET_CHARS = 30
MAX_BODY_CHARS = 100
MAX_DECIDES = 2
MAX_DECIDE_CHARS = 60
MAX_RENDER_CHARS = 3000  # 上限いっぱいの入力でも超えない紙面の長さ（最悪ケースの天井。典型は 900 字前後。60 秒で読めるかは 21 §3 で実測して調整）
# 一括確認に入れてよい種別の許可リスト（定型の下書きだけ）。これ以外は個別承認（21 §2）
BULK_KINDS = ("minutes", "retro_agenda")
ID_RE = re.compile(r"[A-Za-z0-9_-]{1,32}")
KIND_RE = re.compile(r"[a-z_]{1,32}")
# 制御文字（Cc）・書式制御（Cf: U+202E など）・行/段落区切り（Zl・Zp）は紙面の偽装に使えるので全項目で拒否する
FORBIDDEN_CATEGORIES = ("Cc", "Cf", "Zl", "Zp")
URGENT_FORGERY = re.compile(r"[【\[]緊急[】\]]")
# 部分一致の誤除外を避ける: 「更新しましたか？」「tokenizer」は通し、断定の送信済み表現・URL・トークンだけ弾く
SENT_CLAIM = re.compile(r"(送信|更新|投稿|送り)(しました|済み)(?![かの？?])|送りました|(送|投稿|更新|返信)(っ|し)ておきました")
EVAL_WORDS = re.compile(r"遅い人|やる気がない|低パフォーマー")
SENSITIVE = re.compile(r"https?://|www\.|xox[a-z]-|gh[pousr]_\w+|Bearer\s+\S+|password\s*[:=]|(?<![A-Za-z])token(?![A-Za-z])", re.I)
# 一括確認は fail-closed: 題名にも本文にも A 段（期限）・B 段（約束）・C 段（変更）らしき語があれば個別承認へ回す（21 §1・§2）
COMMIT_WORDS = re.compile(
    r"\d{1,2}/\d{1,2}|\d{4}-\d{2}-\d{2}|\d{1,2}月\d{1,2}日|\d{1,2}:\d{2}|[月火水木金土日]曜|今日中|今週|来週|来月|月末|月初|明日|明後日|本日"
    r"|EOD|\d+ ?(日|週間|営業日)(以内|で|後)|までに|間に合|期限|期日|締切|至急|予定|見込み"
    r"|お願い|承知|了解|引き受け|引き取|やっておき|やっとき|やっとく|お約束"
    r"|割り?当|担当|変更|延期|優先度|にする|にします|ASAP|納期|あした|あす|引き継|いたしました|致しました|回す|出す|対応する"
    r"|(確認|対応|連絡|調整|検討|共有|返信|回答|報告)(します|いたします|致します|させていただきます)"
    r"|(出し|直し|進め|やり|おき|行い|致し|いたし|させていただき)ます"
    r"|(替え|上げ|下げ|外し|変更し|延期し|送り|届け|伝え|出し|入れ|報告し|連絡し)ます|お送り|お届け|ご連絡|ご報告|ておきます",
    re.I)  # 否定語リスト（denylist）方式のため漏れは残る。判定前に NFKC 正規化して全角・半角の揺れを吸収する


def _day(value):
    return date.fromisoformat(value) if value else None


def _norm(text):
    return unicodedata.normalize("NFKC", text)


def _check_field(label, text):
    """全項目共通: 制御文字・見出しの偽装・【緊急】の偽装を拒否（1 行に限る）。"""
    if any(unicodedata.category(ch) in FORBIDDEN_CATEGORIES for ch in text):
        return f"{label} に制御文字・改行・書式制御文字は使えません（1 行にしてください）"
    norm = _norm(text)
    if any(m in text or m in norm for m in MARKERS):
        return f"{label} に型の見出し用の文字列（■ ⟦ ⟧ 出典: 等）は使えません"
    if URGENT_FORGERY.search(norm):
        return f"{label} に【緊急】は書けません（緊急は優先度と期限から自動で付きます）"
    return None


def _check_date(key, value):
    if value is None:
        return None
    if not isinstance(value, str):
        return f"{key} は YYYY-MM-DD の文字列か省略にしてください"
    try:
        date.fromisoformat(value)
    except ValueError:
        return f"{key} は YYYY-MM-DD にしてください"
    return None


def validate_action(raw, extra_patterns=()):
    """不正なら理由（str）、正常なら None を返す。"""
    if not isinstance(raw, dict):
        return "JSON オブジェクトではありません"
    missing = [k for k in REQUIRED if not isinstance(raw.get(k), str) or not raw[k].strip()]
    if missing:
        return f"必須キーが空: {', '.join(missing)}"
    if not ID_RE.fullmatch(raw["action_id"]):
        return "action_id は英数字・-・_ の 32 字以内にしてください"
    if not KIND_RE.fullmatch(raw["kind"]):
        return "kind は小文字英字と _ の 32 字以内にしてください"
    if raw["priority"] not in PRIORITY_RANK:
        return f"priority は {'/'.join(PRIORITY_RANK)} のいずれか"
    if raw.get("commit_stage", "none") not in STAGES:
        return f"commit_stage は {'/'.join(STAGES)} のいずれか"
    if not isinstance(raw.get("sensitive", False), bool):
        return "sensitive は true / false にしてください"
    for key in ("due", "expires"):
        reason = _check_date(key, raw.get(key))
        if reason:
            return reason
    decides = raw.get("em_decides", [])
    if not isinstance(decides, list) or not all(isinstance(d, str) and d.strip() for d in decides):
        return "em_decides は空でない文字列の配列にしてください"
    if len(decides) > MAX_DECIDES or any(len(d) > MAX_DECIDE_CHARS for d in decides):
        return f"em_decides は {MAX_DECIDES} 件・各 {MAX_DECIDE_CHARS} 字以内にしてください（60 秒で読める量）"
    for key, limit in (("title", MAX_TITLE_CHARS), ("target", MAX_TARGET_CHARS), ("body", MAX_BODY_CHARS)):
        if len(raw[key]) > limit:
            return f"{key} は {limit} 字以内にしてください（60 秒で読める量）"
    for label, text in [("title", raw["title"]), ("target", raw["target"]), ("body", raw["body"]),
                        *[("em_decides", d) for d in decides]]:
        reason = _check_field(label, text)
        if reason:
            return reason
    text = _norm(" ".join([raw["title"], raw["target"], raw["body"], *decides]))
    if SENSITIVE.search(text) or SENT_CLAIM.search(text) or EVAL_WORDS.search(text):
        return "URL・トークンらしき文字列、または送信済み表現・評価語があります"
    if any(rx.search(text) for _, rx in (*TOKEN_RES, *INTERNAL_RES, *extra_patterns)):
        return "秘密値・実ドメイン・社内固有情報らしき文字列があります（check_no_leak と同じ検査）"
    return None


def load_actions(actions_dir, extra_patterns=()):
    """(正常な action のリスト, 除外理由のリスト)。1 件の不備で全体を止めない。重複 action_id は後のものを除外する。"""
    actions, rejected, seen = [], [], set()
    for path in sorted(Path(actions_dir).glob("*.json")):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            rejected.append(f"{path.name}: JSON が壊れています（{exc.msg}）")
            continue
        except (UnicodeDecodeError, OSError) as exc:
            rejected.append(f"{path.name}: 読めません（{type(exc).__name__}）")
            continue
        reason = validate_action(raw, extra_patterns)
        if not reason and raw["action_id"] in seen:
            reason = f"action_id {raw['action_id']} が重複しています"
        if reason:
            rejected.append(f"{path.name}: {reason}")
            continue
        seen.add(raw["action_id"])
        actions.append(raw)
    return actions, rejected


def _band(due, today):
    if due is None:
        return 3
    gap = (due - today).days
    return 0 if gap < 0 else 1 if gap == 0 else 2 if gap <= BAND_SOON_DAYS else 3


def _is_urgent(action, today):
    due = _day(action.get("due"))
    return action["priority"] == URGENT_PRIORITY and due is not None and due <= today


def _sort_key(action, today):
    due = _day(action.get("due"))
    return (not _is_urgent(action, today), _band(due, today), PRIORITY_RANK[action["priority"]],
            due or date.max, action["action_id"])


def _is_bulk(action):
    text = _norm(f"{action['title']} {action['body']}")
    return (action["kind"] in BULK_KINDS and action.get("commit_stage", "none") == "none"
            and not action.get("em_decides")
            and not COMMIT_WORDS.search(text))


def build_queue(actions, today, rejected=0, source_missing=False):
    # 機微を最初に分ける。期限切れでもタイトルを紙面に出さない
    personal = [a for a in actions if a.get("sensitive")]
    rest = [a for a in actions if not a.get("sensitive")]
    expired = sorted((a for a in rest if _day(a.get("expires")) and _day(a["expires"]) < today),
                     key=lambda a: (a["expires"], a["action_id"]))
    live = sorted((a for a in rest if a not in expired), key=lambda a: _sort_key(a, today))
    individual_all = [a for a in live if not _is_bulk(a)]
    bulk_all = [a for a in live if _is_bulk(a)]
    individual, bulk = individual_all[:MAX_INDIVIDUAL], bulk_all[:MAX_BULK]
    return {
        "today": today, "individual": individual, "bulk": bulk, "expired": expired, "personal": personal,
        "carried": individual_all[MAX_INDIVIDUAL:],  # 26 M3: 個別承認の超過のみ
        "bulk_carried": bulk_all[MAX_BULK:],
        "urgent_carried": sum(_is_urgent(a, today) for a in individual_all[MAX_INDIVIDUAL:]),
        "urgent_ids": {a["action_id"] for a in individual if _is_urgent(a, today)},
        "rejected": rejected, "source_missing": source_missing,
    }


def _item(n, a, urgent):
    due = f"・期限 {a['due']}" if a.get("due") else ""
    decides = a.get("em_decides") or ["コミット候補の有無を確認する"]
    body = a["body"].strip().replace("\n", "\n      ")
    lines = [f"{n}. {'【緊急】' if urgent else ''}{a['title']}［{a['kind']}{due}］",
             f"   対象: {a['target']}", f"   本文: {body}"]
    return lines + [f"   ⟦EM が決める⟧ {d}" for d in decides]


def _notes(queue):
    notes = []
    if queue["source_missing"]:
        notes.append("⚠ data/actions が見つかりません。キューは空です（下書きがまだ無いのか、置き場の誤りかは未確認）")
    if queue["rejected"]:
        notes.append(f"⚠ 除外 {queue['rejected']} 件（形式不正・重複。理由は標準エラー）。キューに載っていない下書きがあります")
    return notes


def _summary(queue):
    ind, bulk, exp, personal = queue["individual"], queue["bulk"], queue["expired"], queue["personal"]
    minutes = max(1, math.ceil(len(ind) * MINUTES_PER_INDIVIDUAL + len(bulk) * MINUTES_PER_BULK))
    parts = [f"要判断 {len(ind)} 件", f"一括確認 {len(bulk)} 件"]
    parts += [f"本人対応 {len(personal)} 件"] if personal else []
    parts += [f"緊急ほか {queue['urgent_carried']} 件（枠超過）"] if queue["urgent_carried"] else []
    parts += [f"期限切れ {len(exp)} 件"]
    parts += [f"除外 {queue['rejected']} 件"] if queue["rejected"] else []
    todo = []
    if ind:
        todo.append(f"{'1' if len(ind) == 1 else f'1〜{len(ind)}'} の ⟦EM が決める⟧ 欄を埋めて送る")
    if bulk:
        todo.append("一括確認の項目を見る")
    if personal:
        todo.append(f"本人対応 {len(personal)} 件を自分で扱う")
    if queue["rejected"]:
        todo.append(f"除外 {queue['rejected']} 件の入力を直す")
    if queue["source_missing"]:
        todo.append("data/actions の場所を確認する")
    return f"結論: {' / '.join(parts)}（目安 {minutes} 分・仮置き）", f"あなたがやること: {'、'.join(todo) or '対応不要'}"


def render(queue, slot):
    ind, bulk, exp = queue["individual"], queue["bulk"], queue["expired"]
    carried = len(queue["carried"]) + len(queue["bulk_carried"])
    head, todo = _summary(queue)
    out = [f"{BANNER}承認キュー {queue['today'].isoformat()} {SLOT_LABEL[slot]}", head, *_notes(queue), todo,
           "", "■ 個別承認（優先度順・最大 5 件）"]
    for n, a in enumerate(ind, 1):
        out += _item(n, a, a["action_id"] in queue["urgent_ids"])
    out += ["", "■ 一括確認（低リスク定型）"]
    out += [f"- [ ] {a['title']}（{a['kind']}）" for a in bulk]
    if carried:
        out.append(f"- ほか {carried} 件は{NEXT_SLOT[slot]}に回しました")
    out += ["", "■ 期限切れ（今回のキューから外しました。下書きは data/actions に残っています）"]
    out += [f"- {a['title']}（{a['expires']}）" for a in exp[:MAX_EXPIRED]]
    if len(exp) > MAX_EXPIRED:
        out.append(f"- ほか {len(exp) - MAX_EXPIRED} 件")
    if queue["personal"]:
        out += ["", "■ EM 本人対応（本文なし）"]
        out += [f"- {a['kind']} {a['action_id']}" for a in queue["personal"][:MAX_PERSONAL]]
        if len(queue["personal"]) > MAX_PERSONAL:
            out.append(f"- ほか {len(queue['personal']) - MAX_PERSONAL} 件")
    return "\n".join(out) + "\n"


def audit_rows(queue, slot, now):
    ts = now.isoformat(timespec="seconds")
    rows = [{"ts": ts, "event": "queue_rendered", "slot": slot, "individual": len(queue["individual"]),
             "bulk": len(queue["bulk"]), "carried_over": len(queue["carried"])}]
    for bucket in ("individual", "bulk"):
        rows += [{"ts": ts, "event": "queue_item", "action_id": a["action_id"], "slot": slot, "bucket": bucket,
                  "kind": a["kind"], "commit_stage": a.get("commit_stage", "none")} for a in queue[bucket]]
    return rows


def append_audit(audit_dir, now, rows):
    audit_dir = Path(audit_dir)
    audit_dir.mkdir(parents=True, exist_ok=True)
    with (audit_dir / f"{now.date().isoformat()}.jsonl").open("a", encoding="utf-8") as fh:
        fh.writelines(json.dumps(r, ensure_ascii=False) + "\n" for r in rows)


def main(argv=None):
    ap = argparse.ArgumentParser(description="承認キュー（朝夕 1 枚）を生成する。送信・投稿はしない")
    ap.add_argument("--slot", choices=sorted(SLOT_LABEL), required=True)
    ap.add_argument("--actions-dir", type=Path, default=ROOT / "data" / "actions")
    ap.add_argument("--audit-dir", type=Path, default=ROOT / "data" / "audit")
    ap.add_argument("--now", type=datetime.fromisoformat, default=None, help="テスト用。ISO 8601")
    ap.add_argument("--dry-run", action="store_true", help="監査ログを追記しない")
    args = ap.parse_args(argv)
    now = args.now or datetime.now().astimezone()
    try:
        actions, rejected = load_actions(args.actions_dir, load_local_patterns())
    except OSError as exc:
        print(f"actions を読めません: {exc}", file=sys.stderr)
        return 1
    for line in rejected:
        print(f"除外: {line}", file=sys.stderr)
    queue = build_queue(actions, now.date(), len(rejected), not args.actions_dir.is_dir())
    sys.stdout.write(render(queue, args.slot))
    if not args.dry_run and not queue["source_missing"]:  # 置き場が無いときは「0 件で出した」記録を残さない（M3・M4 を汚さない）
        append_audit(args.audit_dir, now, audit_rows(queue, args.slot, now))
    return 0


if __name__ == "__main__":
    sys.exit(main())
