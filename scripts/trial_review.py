#!/usr/bin/env python3
"""試用 2 週間後の見直し指標 M2/M3/M4/M6 を監査ログと tasks.json から数える。読み取り専用・stdlib のみ・外部接続なし。

設計: docs/design/26-trial-review-metrics.md。数字・分母・取れなかった理由の 3 点だけを出し、解釈・原因は書かない。
日付は全て JST（UTC+9）基準。タイムゾーン無しの時刻は JST とみなす。
"""
import argparse
import json
import re
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
JST = timezone(timedelta(hours=9))
PERIOD_DAYS = 14
MIN_DENOMINATOR = 5
STALE_DAYS = 3
ACTIVE = ("open", "doing")
CLEARING_OPS = ("defer", "done", "drop")
MATCHED_RESULTS = ("edited", "adopted_as_is")
START_DATE_RE = re.compile(r"^\s*start_date\s*:\s*[\"']?([^\"'#\s]*)", re.M)
TRIAL_BLOCK_RE = re.compile(r"^trial\s*:\s*\n((?:[ \t]+.*\n?|\n)*)", re.M)


class TrialReviewError(Exception):
    """EM に返す理由つきの停止。数字は出さない。"""


def read_config_start_date(config_path):
    """config/local.yaml の trial.start_date を返す。無い・空なら ""。YAML ライブラリに依存しない最小実装。"""
    try:
        text = Path(config_path).read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""
    block = TRIAL_BLOCK_RE.search(text)
    found = START_DATE_RE.search(block.group(1)) if block else None
    return found.group(1) if found else ""


def parse_start_date(raw, today):
    """不正値・未来日はエラー停止（仮開始日へ黙って切り替えない）。空は None。"""
    if not raw:
        return None
    try:
        parsed = date.fromisoformat(raw)
    except ValueError:
        raise TrialReviewError(
            "trial.start_date は ISO 日付（YYYY-MM-DD）ではありません。直すまで集計しません"
            "（空に戻せば監査ログ最古日を仮の開始日にします）") from None
    if parsed > today:
        raise TrialReviewError(f"trial.start_date が未来日です（今日 {today.isoformat()}・JST）。直すまで集計しません")
    return parsed


def _row_day(row):
    """監査行の ts を JST の日付にする。読めなければ None。"""
    try:
        stamp = datetime.fromisoformat(str(row.get("ts")))
    except ValueError:
        return None
    return (stamp if stamp.tzinfo else stamp.replace(tzinfo=JST)).astimezone(JST).date()


def load_audit(audit_dir):
    """日付つきの行。summary/ は読まない。壊れた行・ts が読めない行・UTF-8 外は数字がずれるので停止する（27 §8）。"""
    rows, unreadable = [], 0
    for path in sorted(Path(audit_dir).glob("*.jsonl")) if Path(audit_dir).is_dir() else []:
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except UnicodeDecodeError:
            raise TrialReviewError("監査ログに UTF-8 として読めないファイルがあります。直すまで集計しません") from None
        for line in lines:
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                unreadable += 1
                continue
            day = _row_day(row) if isinstance(row, dict) else None
            if day is None:
                unreadable += 1
                continue
            rows.append({**row, "_day": day})
    if unreadable:
        raise TrialReviewError(f"監査ログに読めない行が {unreadable} 行あります（壊れた JSON か ts 不明）。直すまで集計しません")
    return rows


def load_tasks(tasks_path):
    try:
        data = json.loads(Path(tasks_path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except json.JSONDecodeError as exc:
        raise TrialReviewError(f"tasks.json が壊れています（{exc.msg}）。直すまで集計しません") from None
    tasks = data.get("tasks") if isinstance(data, dict) else None
    if not isinstance(tasks, list):
        raise TrialReviewError("tasks.json の形式が不正です。直すまで集計しません")
    for index, task in enumerate(tasks, 1):
        _check_task(task, index)
    return tasks


def _check_task(task, index):
    """M6 が読む形（dict・id・status・due・history）を検査する。"""
    problem = None
    if not isinstance(task, dict):
        problem = "オブジェクトではありません"
    elif not isinstance(task.get("id"), str) or not task["id"]:
        problem = "id がありません"
    elif task.get("due") is not None and not _is_iso_date(task["due"]):
        problem = "due が ISO 日付ではありません"
    elif not isinstance(task.get("history", []), list) or not all(
            isinstance(h, dict) for h in task.get("history", [])):
        problem = "history が不正です"
    if problem:
        raise TrialReviewError(f"tasks.json の {index} 件目: {problem}。直すまで集計しません")


def _is_iso_date(value):
    try:
        date.fromisoformat(value)
    except (TypeError, ValueError):
        return False
    return True


def resolve_period(start, rows, today):
    """(開始日 or None, 仮か, 終了日 or None)。開始日が決まらなければ None。"""
    provisional = start is None
    if provisional:
        start = min((r["_day"] for r in rows), default=None)
    if start is None:
        return None, True, None
    return start, provisional, start + timedelta(days=PERIOD_DAYS - 1)


def _ratio(numerator, denominator):
    if denominator < MIN_DENOMINATOR:
        return f"判定不能（分母 {denominator}）"
    return f"{numerator}/{denominator}（{numerator / denominator:.0%}）"


def _results_by_action(rows):
    """action_id → 最後の em_reviewed の result。"""
    results = {}
    for r in rows:
        if r.get("event") == "em_reviewed" and r.get("action_id"):
            results[r["action_id"]] = r.get("result")
    return results


def _unique_items(rows):
    """action_id → 最初の queue_item 行（持ち越しの重複を除く）。"""
    items = {}
    for r in rows:
        if r.get("event") == "queue_item" and r.get("action_id"):
            items.setdefault(r["action_id"], r)
    return items


def _matched(items, results):
    """照合できた件・照合不能（em_reviewed が無い等）の件数・却下（rejected）の件数。"""
    matched = {aid: results[aid] for aid in items if results.get(aid) in MATCHED_RESULTS}
    rejected = sum(results.get(aid) == "rejected" for aid in items)
    return matched, len(items) - len(matched) - rejected, rejected


def metric_m2(rows):
    items = {aid: r for aid, r in _unique_items(rows).items() if r.get("bucket") == "bulk"}
    matched, unmatched, rejected = _matched(items, _results_by_action(rows))
    edited = sum(v == "edited" for v in matched.values())
    return {"value": _ratio(edited, len(matched)), "denominator": len(matched), "unmatched": unmatched,
            "rejected": rejected, "reason": _reason(rows, "queue_item", unmatched)}


def metric_m3(rows):
    rendered = [r for r in rows if r.get("event") == "queue_rendered"]
    days = {r["_day"] for r in rendered}
    carried_days = {r["_day"] for r in rendered if (r.get("carried_over") or 0) >= 1}
    carried = sum(r.get("carried_over") or 0 for r in rendered)
    reason = "" if rendered else "queue_rendered の行が期間内に無い（承認キューの入力 data/actions を作る元が未実装）"
    return {"value": f"持ち越し延べ {carried} 件・持ち越しのあった日 {_ratio(len(carried_days), len(days))}", "denominator": len(days),
            "unmatched": 0, "reason": reason}


def metric_m4(rows):
    items = {aid: r for aid, r in _unique_items(rows).items() if r.get("commit_stage", "none") != "none"}
    matched, unmatched, rejected = _matched(items, _results_by_action(rows))
    adopted = sum(v == "adopted_as_is" for v in matched.values())
    reason = _reason(rows, "queue_item", unmatched)
    return {"value": f"検知 {len(items)} 件・採用 {_ratio(adopted, len(matched))}", "denominator": len(matched),
            "unmatched": unmatched, "rejected": rejected, "reason": reason}


def _reason(rows, event, unmatched):
    if not any(r.get("event") == event for r in rows):
        return f"{event} の行が期間内に無い（承認キューの入力 data/actions を作る元が未実装）"
    if unmatched:
        return "em_reviewed が無い（送信文面の自動照合が未実装）件は分母から除いた"
    return ""


def metric_m6(tasks, as_of):
    """as_of 時点のスナップショット。期限から暦日 3 日超で、期限以降に defer/done/drop が無い open/doing。"""
    if tasks is None:
        return {"value": "未計測", "denominator": 0, "unmatched": 0, "reason": "tasks.json が無い"}
    active = [t for t in tasks if t.get("status") in ACTIVE and t.get("due")]  # load_tasks が形を検査済み
    stale = []
    for task in active:
        due = date.fromisoformat(task["due"])
        cleared = any(h.get("op") in CLEARING_OPS and str(h.get("at", ""))[:10] >= due.isoformat()
                      for h in task.get("history", []))
        if (as_of - due).days > STALE_DAYS and not cleared:
            stale.append(task["id"])
    return {"value": f"{len(stale)} 件（id: {', '.join(stale) or 'なし'}）", "denominator": len(active),
            "unmatched": 0, "reason": "" if active else "期限つきの open/doing が 0 件"}


def build_review(rows, tasks, start, today):
    """集計結果（dict）。rows は全期間の監査行。期間内だけを数える。"""
    start, provisional, end = resolve_period(start, rows, today)
    if start is None:
        # 監査ログ 0 行 かつ 開始日未設定: 期間が決まらないので M2〜M4 は数えない。M6 は今日時点で出す。
        return {"start": None, "end": None, "provisional": True, "as_of": today, "in_progress": False,
                "undetermined": True, "metrics": {"M2": _unmeasured(), "M3": _unmeasured(), "M4": _unmeasured(),
                                                  "M6": metric_m6(tasks, today)}}
    in_window = [r for r in rows if start <= r["_day"] <= end]
    as_of = min(today, end)
    return {"start": start, "end": end, "provisional": provisional, "as_of": as_of, "in_progress": today < end,
            "undetermined": False, "metrics": {"M2": metric_m2(in_window), "M3": metric_m3(in_window),
                                               "M4": metric_m4(in_window), "M6": metric_m6(tasks, as_of)}}


def _unmeasured():
    return {"value": "未計測", "denominator": 0, "unmatched": 0, "reason": "開始日不明（監査ログ 0 行で trial.start_date も空）"}


METRIC_TITLES = {"M2": "M2 一括確認の編集率（代用）", "M3": "M3 承認キューの持ち越し", "M4": "M4 検知の採用率",
                 "M6": "M6 期限超過の放置タスク（スナップショット）"}


def render(review):
    lines = ["# 試用 2 週間後の集計（読み取り専用・解釈なし）", ""]
    if review["undetermined"]:
        lines.append("期間: **開始日不明・未計測**（監査ログ 0 行で、`trial.start_date` も空）。M2〜M4 は数えていません")
    else:
        tag = "仮の開始日（監査ログ最古日）" if review["provisional"] else "開始日"
        lines.append(f"期間: {tag} {review['start']} 〜 {review['end']}（暦日 {PERIOD_DAYS} 日・JST）"
                     + (f"。**途中経過**（M6 は {review['as_of']} 時点）" if review["in_progress"] else ""))
    lines.append(f"分母 {MIN_DENOMINATOR} 件未満の割合は「判定不能」。除外した「照合不能」は件数を別に出す")
    for key, metric in review["metrics"].items():
        lines += ["", f"## {METRIC_TITLES[key]}", f"- 数字: {metric['value']}", f"- 分母: {metric['denominator']}"]
        if metric.get("rejected"):
            lines.append(f"- 却下: {metric['rejected']} 件（分母から除外。照合不能とは別）")
        if metric["unmatched"]:
            lines.append(f"- 照合不能: {metric['unmatched']} 件（分母から除外）")
        lines.append(f"- 取れなかった理由: {metric['reason'] or 'なし'}")
    lines += ["", "M1・M5 は Jira 実接続後のため未計測。M7 は推定版のみで、この集計の対象外（26 §2）。"]
    lines.append("数字は調整の材料で、原因の説明ではありません。しきい値の変更は EM が決めます。")
    return "\n".join(lines) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description="試用 2 週間後の指標 M2/M3/M4/M6 を集計して標準出力に出す。何も書き込まない")
    ap.add_argument("--data-dir", type=Path, default=ROOT / "data")
    ap.add_argument("--config", type=Path, default=ROOT / "config" / "local.yaml")
    ap.add_argument("--start-date", default=None, help="config の trial.start_date を上書き（ISO 日付）")
    ap.add_argument("--today", default=None, help="テスト用。ISO 日付（JST の今日）")
    args = ap.parse_args(argv)
    try:
        today = date.fromisoformat(args.today) if args.today else datetime.now(JST).date()
        raw = args.start_date if args.start_date is not None else read_config_start_date(args.config)
        start = parse_start_date(raw, today)
        rows = load_audit(args.data_dir / "audit")
        tasks = load_tasks(args.data_dir / "tasks" / "tasks.json")
    except (TrialReviewError, ValueError) as exc:
        print(f"trial_review: {exc}", file=sys.stderr)
        return 2
    sys.stdout.write(render(build_review(rows, tasks, start, today)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
