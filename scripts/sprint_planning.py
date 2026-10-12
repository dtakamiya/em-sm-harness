#!/usr/bin/env python3
"""Jira キャッシュ（06 準拠）と過去の完了 SP の集計値から、プランニング用の候補一覧と容量の材料（S2）を出す。読み取り専用・stdlib のみ・外部接続なし。

設計: docs/design/33-sprint-planning-material.md（型 §5・固定文言 §3・検証 P1〜P6 §6）。事実と目安だけを出す。
何 SP・何を入れるかは出さない（決めるのは EM とチーム）。平均・予測・達成率・担当者情報も出さない。

【試作・架空サンプル専用】実キャッシュ・実集計値は渡さない。委任ラダー L1 では実データを扱わない。
"""
import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from jira_metrics import REFETCH_MESSAGE, active_sprint  # noqa: E402

HISTORY_WINDOW = 3  # 幅を出すのに要る終了済みスプリント件数（Q-035 a）。K = 3 固定
MAX_LISTED = 10  # 詳細に並べる候補の上限。超過は件数のみ（14 A2）
MAX_BODY_CANDIDATES = 3  # 本文に出す候補。残りは詳細へ
MAX_WORKDAYS = 60
PRIORITY_ORDER = ("highest", "high", "medium", "low", "lowest")
HISTORY_KEYS = {"schema_version", "project_alias", "sprints"}
HISTORY_SPRINT_KEYS = {"id", "name", "end", "done_sp"}  # 個人別・課題別は持ち込まない（06 §4）

NOTICE = "容量は過去の実績から見た目安で、約束ではありません。入れる量と中身は EM とチームが決めます"
RANGE_NOTE = ("過去 {k} 件の完了 SP の最小〜最大です。予測ではありません"
              "（SP はチーム内の相対値で、課題の大きさ・休暇・見積もりの粒度で変わります）")
NOT_CORRECTED = "幅は稼働日数で補正していません"
CANDIDATE_HEADING = "候補（Jira の priority 順。EM の優先順位ではありません）"
ASK = "EM がやること: 候補と材料を見て入れるものを決める。判断依頼: なし"


def _natural_key(key):
    prefix, _, number = key.rpartition("-")
    return (prefix, int(number)) if number.isdigit() else (key, 0)


def _priority_rank(issue):
    name = (issue.get("priority") or "").lower()
    return PRIORITY_ORDER.index(name) if name in PRIORITY_ORDER else len(PRIORITY_ORDER)


def is_carried(issue):
    """複数スプリントに属し、未完了（22 §2.3 の繰り越し）。"""
    return len(issue.get("sprints", [])) >= 2 and issue["status_category"] != "done"


def is_blocked(issue, status_by_key):
    """blocks 系リンクの inward（塞がれている側）で、相手が done でないもの。相手がキャッシュに無ければ塞がれていると見る。"""
    return any(
        "block" in link["link_type"].lower() and link["direction"] == "inward"
        and status_by_key.get(link["issue_key"]) != "done"
        for link in issue.get("links", []))


def candidates(issues):
    """現在 active スプリントに属さず done でない課題を、priority → 繰り越し → キー順で返す。"""
    active = active_sprint(issues)
    active_id = active["id"] if active else None
    pool = [i for i in issues
            if i["status_category"] != "done" and all(s["id"] != active_id for s in i.get("sprints", []))]
    return sorted(pool, key=lambda i: (_priority_rank(i), not is_carried(i), _natural_key(i["key"])))


def validate_history(history, alias):
    """集計値の形式を検査して、終了日の新しい順に並べた sprints を返す。不正なら何も出さず終了する。"""
    if not isinstance(history, dict) or set(history) != HISTORY_KEYS:
        raise SystemExit(f"完了 SP の集計値の形式が不正です（キーは {sorted(HISTORY_KEYS)} のみ）。何も出力しません")
    if history["project_alias"] != alias:
        raise SystemExit("完了 SP の集計値の project_alias がキャッシュと一致しません。何も出力しません")
    sprints = history["sprints"]
    if not isinstance(sprints, list):
        raise SystemExit("完了 SP の集計値の sprints が配列ではありません。何も出力しません")
    for i, s in enumerate(sprints):
        if not isinstance(s, dict) or set(s) != HISTORY_SPRINT_KEYS:
            raise SystemExit(f"sprints[{i}] の形式が不正です（キーは {sorted(HISTORY_SPRINT_KEYS)} のみ）。何も出力しません")
        points = s["done_sp"]
        if isinstance(points, bool) or not isinstance(points, int) or points < 0:
            raise SystemExit(f"sprints[{i}].done_sp は 0 以上の整数にしてください（0 は有効）。何も出力しません")
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(s["end"])):
            raise SystemExit(f"sprints[{i}].end は YYYY-MM-DD で指定してください。何も出力しません")
    if len({s["id"] for s in sprints}) != len(sprints):
        raise SystemExit("完了 SP の集計値に重複したスプリント id があります。何も出力しません")
    return sorted(sprints, key=lambda s: s["end"], reverse=True)


def _issue_label(issue, status_by_key):
    points = issue.get("story_points")
    notes = (["繰り越し"] if is_carried(issue) else []) + (["ブロッカー有"] if is_blocked(issue, status_by_key) else [])
    tail = f"（{'・'.join(notes)}）" if notes else ""
    return f"{issue['key']} {(issue.get('priority') or '未設定').lower()} {'未見積もり' if points is None else f'{points}SP'}{tail}"


def _capacity_line(past, workdays):
    recent = [s["done_sp"] for s in past[:HISTORY_WINDOW]]
    if len(recent) < HISTORY_WINDOW:
        done = f"過去の終了済みスプリント {len(recent)} 件（{HISTORY_WINDOW} 件未満のため幅は出しません）"
    else:
        done = f"過去 {HISTORY_WINDOW} 件の完了 SP: {min(recent)}〜{max(recent)}（予測ではありません）"
    days = f"稼働日数: {workdays} 日（EM 入力）" if workdays is not None else "稼働日数: 未入力"
    return done, days


def build_material(cache, history=None, workdays=None):
    if not cache.get("complete", False):
        return f"{NOTICE}\n{REFETCH_MESSAGE}"
    issues = cache["issues"]
    status_by_key = {i["key"]: i["status_category"] for i in issues}
    pool = candidates(issues)
    unestimated = sum(1 for i in pool if i.get("story_points") is None)
    carried = sum(1 for i in pool if is_carried(i))
    past = validate_history(history, cache["project_alias"]) if history is not None else []
    done_line, days_line = _capacity_line(past, workdays)

    shown = [_issue_label(i, status_by_key) for i in pool[:MAX_BODY_CANDIDATES]]
    rest = len(pool) - len(shown)
    candidate_line = ("- " + " ／ ".join(shown) + (f" ほか {rest} 件（詳細に）" if rest else "")) if pool else "- 候補なし"
    shortage = [text for text, lacking in (
        ("候補が 0 件", not pool),
        (f"過去スプリントが {HISTORY_WINDOW} 件未満（幅なし）", len(past) < HISTORY_WINDOW),
        ("稼働日数が未入力", workdays is None)) if lacking]
    window = min(len(past), HISTORY_WINDOW)
    limit = f"限界: 完了 SP は終了済みスプリント {window} 件・SP なしは除外・{NOT_CORRECTED}・取得完全"
    body = [f"🟡 S2 プランニング材料: 候補 {len(pool)} 件（未見積もり {unestimated} 件）。入れる量は EM が決める",
            NOTICE, CANDIDATE_HEADING, candidate_line,
            "容量の材料", f"- {done_line} ／ 繰り越し {carried} 件 ／ {days_line}", ASK, limit]
    if shortage:
        body.append("材料が足りません: " + "・".join(shortage))
    detail = [f"- 候補一覧（{cache['project_alias']}・{cache['fetched_at'][:10]}）"]
    detail += [f"  - {_issue_label(i, status_by_key)}" for i in pool[:MAX_LISTED]]
    if len(pool) > MAX_LISTED:
        detail.append(f"  - ほか {len(pool) - MAX_LISTED} 件（件数のみ）")
    detail += [f"- 見積もり状況: 候補 {len(pool)} 件のうち SP 未見積もり {unestimated} 件（合計 SP は出しません。未見積もりは幅に含まれません）",
               f"- 固定文言: {NOTICE}",
               "- " + RANGE_NOTE.format(k=HISTORY_WINDOW)]
    return "\n".join(["【試作・架空サンプル専用】"] + body + ["", "詳細"] + detail)


def _read_json(path, what):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SystemExit(f"{what}を読めません（{type(exc).__name__}: {exc}）。何も出力しません")


def _workdays(value):
    days = int(value)
    if not 0 < days <= MAX_WORKDAYS:
        raise argparse.ArgumentTypeError(f"1〜{MAX_WORKDAYS} の整数で指定してください（日数のみ。人別の休暇は入力にしない）")
    return days


def main(argv=None):
    parser = argparse.ArgumentParser(description="【試作・架空サンプル専用。実データは渡さない】プランニング用の候補一覧と容量の材料（読み取り専用）")
    parser.add_argument("cache", help="data/jira-cache/<alias>/<YYYY-MM-DD>.json")
    parser.add_argument("--history", help="data/structured/ 側の終了済みスプリントごとの完了 SP 集計値（06 §4）。無ければ過去 0 件として件数のみ")
    parser.add_argument("--workdays", type=_workdays, help="次スプリントの稼働日数（EM が貼った日数のみ）")
    args = parser.parse_args(argv)
    cache = _read_json(args.cache, "キャッシュ")
    history = _read_json(args.history, "完了 SP の集計値") if args.history else None
    try:
        print(build_material(cache, history, args.workdays))
    except KeyError as exc:
        raise SystemExit(f"キャッシュの必須キー {exc} がありません。何も出力しません")


if __name__ == "__main__":
    main()
