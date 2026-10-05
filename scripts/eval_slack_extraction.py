#!/usr/bin/env python3
"""Slack 抽出スキルの出力を expected.json と突き合わせ、再現率・誤抽出を件数で出す。

ローカルのみ・stdlib のみ・外部接続なし・読み取り専用（ファイルは書かない）。
設計: docs/design/23-slack-extraction-guide.md §8。
突き合わせの鍵は (kind, evidence.msg_index, actors.from)。文言（observation / quote）の揺れは数えない。
"""
import argparse
import json
import sys
from pathlib import Path

DEFAULT_EXPECTED = Path("tests/fixtures/slack-extraction/expected.json")
CHECKED_FIELDS = ("confidence", "to_em")  # 鍵が一致した item で値の食い違いを数える項目


class EvalError(Exception):
    """EM に返す理由つきの拒否。"""


def _read_json(path, label):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise EvalError(f"{label} が見つかりません: {path}")
    except json.JSONDecodeError as exc:
        raise EvalError(f"{label} が壊れています（{exc.msg}）: {path}")


def _key(item):
    try:
        return (item["kind"], item["evidence"]["msg_index"], item["actors"]["from"])
    except (KeyError, TypeError):
        raise EvalError(f"item {item.get('id', '?') if isinstance(item, dict) else '?'} に kind / evidence.msg_index / actors.from がありません")


def load_actuals(paths):
    """構造化データ（13 §6）を source.file ごとに集める。ディレクトリは *.json を読む。"""
    files = []
    for p in paths:
        files.extend(sorted(p.glob("*.json")) if p.is_dir() else [p])
    actuals = {}
    for f in files:
        data = _read_json(f, "抽出結果")
        source = data.get("source") if isinstance(data, dict) else None
        name = source.get("file") if isinstance(source, dict) else None
        if not isinstance(name, str) or not isinstance(data.get("items"), list):
            raise EvalError(f"抽出結果の形式が不正です（source.file と items が必要）: {f}")
        if name in actuals:
            raise EvalError(f"同じ source.file の抽出結果が複数あります: {name}")
        actuals[name] = data["items"]
    return actuals


def evaluate_file(expected_file, actual_items):
    """1 貼り付け分の比較結果。入力は変更しない。"""
    expected = {_key(i): i for i in expected_file["items"]}
    actual = {_key(i): i for i in actual_items}
    matched = expected.keys() & actual.keys()
    excluded_idx = {e["msg_index"] for e in expected_file.get("excluded", [])}
    extra = [k for k in actual if k not in expected]
    return {
        "source": expected_file["source"],
        "matched": sorted(matched),
        "missed": sorted(expected.keys() - actual.keys()),
        "extra": sorted(extra),
        "extra_in_excluded": sorted(k for k in extra if k[1] in excluded_idx),
        "field_mismatches": sorted(
            (k, f) for k in matched for f in CHECKED_FIELDS
            if f in expected[k] and expected[k][f] != actual[k].get(f)),
        "found": True,
    }


def evaluate(expected, actuals):
    results = []
    for ef in expected["files"]:
        items = actuals.get(ef["source"])
        result = evaluate_file(ef, items or [])
        results.append({**result, "found": items is not None})
    unevaluated = sorted(set(actuals) - {ef["source"] for ef in expected["files"]})
    return results, unevaluated


def totals(results):
    tp = sum(len(r["matched"]) for r in results)
    missed = sum(len(r["missed"]) for r in results)
    extra = sum(len(r["extra"]) for r in results)
    return {
        "expected": tp + missed, "matched": tp, "missed": missed, "extra": extra,
        "extra_in_excluded": sum(len(r["extra_in_excluded"]) for r in results),
        "field_mismatches": sum(len(r["field_mismatches"]) for r in results),
        "recall": tp / (tp + missed) if tp + missed else None,
        "precision": tp / (tp + extra) if tp + extra else None,
    }


def _pct(value):
    return "-" if value is None else f"{value:.0%}"


def _label(key):
    return f"{key[0]}@{key[1]}({key[2]})"


def report(results, unevaluated):
    t = totals(results)
    lines = [f"再現率 {_pct(t['recall'])}（{t['matched']}/{t['expected']} 件）"
             f" / 誤抽出 {t['extra']} 件（うち除外対象 {t['extra_in_excluded']} 件）"
             f" / 精度 {_pct(t['precision'])} / 値の食い違い {t['field_mismatches']} 件"]
    for r in results:
        if not r["found"]:
            lines.append(f"- {r['source']}: 抽出結果なし（期待 {len(r['missed'])} 件が未抽出）")
            continue
        parts = [f"{name} {', '.join(_label(k) for k in r[field])}"
                 for name, field in (("取りこぼし", "missed"), ("誤抽出", "extra")) if r[field]]
        parts += [f"食い違い {_label(k)}.{f}" for k, f in r["field_mismatches"]]
        lines.append(f"- {r['source']}: " + ("; ".join(parts) if parts else "差分なし"))
    if unevaluated:
        lines.append(f"期待値がなく未評価: {', '.join(unevaluated)}")
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Slack 抽出結果 vs expected.json の比較")
    ap.add_argument("actual", nargs="+", type=Path, help="構造化データの JSON ファイルまたはディレクトリ")
    ap.add_argument("--expected", type=Path, default=DEFAULT_EXPECTED)
    ap.add_argument("--min-recall", type=float, default=None, help="下回ったら終了コード 1")
    ap.add_argument("--max-extra", type=int, default=None, help="誤抽出がこの件数を超えたら終了コード 1")
    args = ap.parse_args(argv)
    try:
        expected = _read_json(args.expected, "期待値")
        results, unevaluated = evaluate(expected, load_actuals(args.actual))
    except (EvalError, KeyError, TypeError) as exc:
        print(f"評価を中止しました: {exc}", file=sys.stderr)
        return 2
    print(report(results, unevaluated))
    t = totals(results)
    failed = ((args.min_recall is not None and (t["recall"] or 0) < args.min_recall)
              or (args.max_extra is not None and t["extra"] > args.max_extra))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
