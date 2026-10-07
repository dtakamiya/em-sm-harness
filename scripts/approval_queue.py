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
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
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
ID_RE = re.compile(r"[A-Za-z0-9_-]{1,32}")
KIND_RE = re.compile(r"[a-z_]{1,32}")
# 部分一致の誤除外を避ける: 「更新しましたか？」「tokenizer」は通し、断定の送信済み表現・URL・トークンだけ弾く
SENT_CLAIM = re.compile(r"(送信|更新|投稿|送り)(しました|済み)(?![かの？?])|送りました")
EVAL_WORDS = re.compile(r"遅い人|やる気がない|低パフォーマー")
SENSITIVE = re.compile(r"https?://|xox[a-z]-|(?<![A-Za-z])token(?![A-Za-z])", re.I)
# 一括確認は fail-closed: 題名にも本文にも A 段（期限）・B 段（約束）・C 段（変更）らしき語があれば個別承認へ回す（21 §1・§2）
COMMIT_WORDS = re.compile(
    r"\d{1,2}/\d{1,2}|\d{4}-\d{2}-\d{2}|\d{1,2}月\d{1,2}日|\d{1,2}:\d{2}|[月火水木金土日]曜|今日中|今週|来週|来月|明日|明後日|本日"
    r"|EOD|\d+ ?日以内|までに|期限|期日|締切|至急|お願いします"
    r"|(確認|対応|連絡|調整|検討|共有|返信|回答)(します|いたします|させていただきます)|引き取|やっておき|お約束"
    r"|(替え|上げ|下げ|外し|変更し|延期し)ます")


def _day(value):
    return date.fromisoformat(value) if value else None


def _one_line(label, text):
    if "\n" in text or "\r" in text:
        return f"{label} に改行は使えません"
    if any(m in text for m in MARKERS):
        return f"{label} に型の見出し用の文字列（■ ⟦ ⟧ 出典: 等）は使えません"
    return None


def validate_action(raw):
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
        try:
            _day(raw.get(key))
        except (TypeError, ValueError):
            return f"{key} は YYYY-MM-DD にしてください"
    decides = raw.get("em_decides", [])
    if not isinstance(decides, list) or not all(isinstance(d, str) and d.strip() for d in decides):
        return "em_decides は空でない文字列の配列にしてください"
    for label, text in [("title", raw["title"]), ("target", raw["target"]),
                        *[("em_decides", d) for d in decides]]:
        reason = _one_line(label, text)
        if reason:
            return reason
    if any(m in raw["body"] for m in MARKERS):
        return "body に型の見出し用の文字列（■ ⟦ ⟧ 出典: 等）は使えません"
    text = " ".join([raw["title"], raw["target"], raw["body"], *decides])
    if SENSITIVE.search(text) or SENT_CLAIM.search(text) or EVAL_WORDS.search(text):
        return "URL・トークンらしき文字列、または送信済み表現・評価語があります"
    return None


def load_actions(actions_dir):
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
        reason = validate_action(raw)
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
    text = f"{action['title']} {action['body']}"
    return (action.get("commit_stage", "none") == "none" and not action.get("em_decides")
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


def render(queue, slot):
    ind, bulk, exp = queue["individual"], queue["bulk"], queue["expired"]
    carried = len(queue["carried"]) + len(queue["bulk_carried"])
    minutes = max(1, math.ceil(len(ind) * MINUTES_PER_INDIVIDUAL + len(bulk) * MINUTES_PER_BULK))
    span = "1" if len(ind) == 1 else f"1〜{len(ind)}"
    todo = f"{span} の ⟦EM が決める⟧ 欄を埋めて送る" if ind else "一括確認の項目を見る" if bulk else "対応不要"
    out = [f"{BANNER}承認キュー {queue['today'].isoformat()} {SLOT_LABEL[slot]}",
           f"結論: 要判断 {len(ind)} 件 / 一括確認 {len(bulk)} 件 / 期限切れ {len(exp)} 件（目安 {minutes} 分・仮置き）",
           *_notes(queue),
           f"あなたがやること: {todo}", "", "■ 個別承認（優先度順・最大 5 件）"]
    for n, a in enumerate(ind, 1):
        out += _item(n, a, a["action_id"] in queue["urgent_ids"])
    out += ["", "■ 一括確認（低リスク定型）"]
    out += [f"- [ ] {a['title']}（{a['kind']}）" for a in bulk]
    out.append(f"- ほか {carried} 件は{NEXT_SLOT[slot]}に回しました")
    out += ["", "■ 期限切れ（自動で下書きから外しました）"]
    out += [f"- {a['title']}（{a['expires']}）" for a in exp[:MAX_EXPIRED]]
    if len(exp) > MAX_EXPIRED:
        out.append(f"- ほか {len(exp) - MAX_EXPIRED} 件")
    if queue["personal"]:
        out += ["", "■ EM 本人対応（本文なし）"]
        out += [f"- {a['kind']} {a['action_id']}" for a in queue["personal"]]
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
        actions, rejected = load_actions(args.actions_dir)
    except OSError as exc:
        print(f"actions を読めません: {exc}", file=sys.stderr)
        return 1
    for line in rejected:
        print(f"除外: {line}", file=sys.stderr)
    queue = build_queue(actions, now.date(), len(rejected), not args.actions_dir.is_dir())
    sys.stdout.write(render(queue, args.slot))
    if not args.dry_run:
        append_audit(args.audit_dir, now, audit_rows(queue, args.slot, now))
    return 0


if __name__ == "__main__":
    sys.exit(main())
