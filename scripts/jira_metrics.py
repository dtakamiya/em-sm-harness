#!/usr/bin/env python3
"""Jira キャッシュ（06 準拠）から更新なし日数とスコープ変動を数える。読み取り専用・stdlib のみ・外部接続なし。

設計: docs/design/22-jira-metrics-catalog.md §2.1・§2.3。事実の数だけを出す。評価語・原因の推測・担当者情報は出さない。
"""
import argparse
import json
import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from proactive_scan import bdays_between  # noqa: E402

STALE_BDAYS = 7  # 進行中の更新なしのしきい値（18 §1・Q-022）
SCOPE_GRACE_BDAYS = 1  # 開始からこの営業日以内の変更は計画の一部（Q-027）
MIN_POPULATION = 5  # N がこれ未満なら件数のみ（22 §1）
MAX_KEYS = 5
REFETCH_MESSAGE = "再取得が必要（キャッシュが不完全です。指標は出しません）"


def _day(value):
    return date.fromisoformat(value[:10])


def active_sprint(issues):
    """現在の active スプリントを返す。無ければ None。"""
    found = [s for i in issues for s in i.get("sprints", []) if s.get("state") == "active"]
    return min(found, key=lambda s: s["start"]) if found else None


def stagnation(issues, fetched):
    """進行中の課題のうち updated から fetched まで STALE_BDAYS 営業日以上動いていないもの。"""
    in_progress = [i for i in issues if i["status_category"] == "indeterminate"]
    stale = sorted(i["key"] for i in in_progress if bdays_between(_day(i["updated"]), fetched) >= STALE_BDAYS)
    return {"population": len(in_progress), "stale_keys": stale}


def _points(issue):
    return issue.get("story_points")


def _sum_points(issues):
    """(SP 合計, SP が null で除外した件数)。0 は計算に含める。"""
    known = [_points(i) for i in issues if _points(i) is not None]
    return sum(known), len(issues) - len(known)


def scope_change(issues, sprint, grace=SCOPE_GRACE_BDAYS):
    """開始から grace 営業日を超えて起きた sprint 遷移を、追加・除外・繰り越しに分けて数える。"""
    start, name = _day(sprint["start"]), sprint["name"]
    added, removed, carried = [], [], []
    for issue in issues:
        for tr in issue.get("transitions", []):
            if tr["field"] != "sprint" or bdays_between(start, _day(tr["at"])) <= grace:
                continue
            if tr["to"] == name:
                added.append(issue)
            elif tr["from"] == name:
                removed.append(issue)
        older = [s for s in issue.get("sprints", []) if s["id"] != sprint["id"] and s["state"] == "closed"]
        if older and any(s["id"] == sprint["id"] for s in issue.get("sprints", [])):
            carried.append(issue)
    return {name: {"added": added, "removed": removed, "carried": carried}}[name]


def _scope_line(label, group):
    points, unknown = _sum_points(group)
    tail = f"（SP なし {unknown} 件は除外）" if unknown else ""
    return f"{label} {len(group)} 件（計 {points}SP）{tail}"


def build_report(cache):
    if not cache.get("complete", False):
        return REFETCH_MESSAGE
    issues, fetched = cache["issues"], _day(cache["fetched_at"])
    alias = cache["project_alias"]
    st = stagnation(issues, fetched)
    lines = [f"観察（{alias}・{fetched.isoformat()}・進行中 N={st['population']}・取得: 完全）"]
    if st["population"] < MIN_POPULATION:
        lines.append(f"- 更新なし: 進行中 {st['population']} 件（件数が少ないため割合は出さない）")
    else:
        keys = ", ".join(st["stale_keys"][:MAX_KEYS]) or "なし"
        lines.append(f"- 更新なし: 進行中 {st['population']} 件のうち {len(st['stale_keys'])} 件が"
                     f" {STALE_BDAYS} 営業日以上更新なし（{keys}）")
    sprint = active_sprint(issues)
    if sprint is None:
        lines.append("- スコープ: active なスプリントがないため数えない")
    else:
        sc = scope_change(issues, sprint)
        lines += [f"- スコープ（{sprint['name']}）: " + _scope_line("開始後に追加", sc["added"]),
                  "  " + _scope_line("除外", sc["removed"]),
                  "  " + _scope_line("繰り越し", sc["carried"])]
    lines.append(f"限界: 更新なしは updated 基準の営業日（土日を除く・祝日は見ない）。開始から {SCOPE_GRACE_BDAYS} 営業日以内の"
                 "スプリント変更は計画として除外。追加の経緯は Jira から分からない（確認先: 担当者）。")
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Jira キャッシュから更新なし・スコープ変動を数える（読み取り専用）")
    parser.add_argument("cache", help="data/jira-cache/<alias>/<YYYY-MM-DD>.json")
    args = parser.parse_args(argv)
    try:
        cache = json.loads(Path(args.cache).read_text(encoding="utf-8"))
        print(build_report(cache))
    except (OSError, ValueError, KeyError) as exc:
        raise SystemExit(f"キャッシュを読めません（{type(exc).__name__}: {exc}）。何も出力しません")


if __name__ == "__main__":
    main()
