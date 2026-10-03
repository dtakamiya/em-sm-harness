#!/usr/bin/env python3
"""policy/delegation.yaml の lint。grants が安全ルールに反していないかを検査する。読み取り専用・外部接続なし。

設計: docs/design/16-policy-lint.md / ADR 0001。fail-closed: 読めない・解釈できないときは NG（終了コード 2）。
終了コード: 0=OK（warning のみ含む）/ 1=error あり / 2=lint 自体が実行不能。
"""
import argparse
import sys
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

DEFAULT_POLICY = Path(__file__).resolve().parent.parent / "policy" / "delegation.yaml"
MAX_GRANT_LEVEL = "L2"


@dataclass(frozen=True)
class Finding:
    level: str  # "error" | "warning"
    code: str
    where: str
    message: str


def _err(code, where, message):
    return Finding("error", code, where, message)


def _warn(code, where, message):
    return Finding("warning", code, where, message)


def load_policy(path):
    try:
        import yaml
    except ImportError:
        raise SystemExit("PyYAML が見つかりません。lint を実行できないため NG 扱いです（fail-closed）。docs/design/16-policy-lint.md 参照")
    try:
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise SystemExit(f"{path} を読めません（{exc}）。NG 扱いです（fail-closed）")
    if not isinstance(data, dict):
        raise SystemExit(f"{path} の最上位がマッピングではありません。NG 扱いです（fail-closed）")
    return data


def _as_day(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError:
            return None
    return None


def _lint_policy_level(policy):
    findings = []
    if policy.get("default") != "deny":
        findings.append(_err("default-not-deny", "default", "default は deny でなければなりません"))
    declared = set(policy.get("sensitivity_tags") or [])
    for tag in policy.get("hard_deny_tags") or {}:
        if tag not in declared:
            findings.append(_err("hard-deny-unknown-tag", f"hard_deny_tags.{tag}", "sensitivity_tags に無いタグです"))
    return findings


def _lint_scope(scope, where):
    ok = isinstance(scope, dict) and scope.get("template_id") and scope.get("recipients")
    if ok and isinstance(scope["recipients"], list):
        return []
    return [_err("scope-missing", where, "L2 には scope（template_id と recipients の固定）が必要です")]


def _lint_tags(grant, policy, where):
    tags = grant.get("tags")
    if not tags or not isinstance(tags, list):
        return [_err("tags-missing", where, "許可する sensitivity タグを明示してください（タグ無し = L1 止まり）")]
    declared = set(policy.get("sensitivity_tags") or [])
    hard_deny = set(policy.get("hard_deny_tags") or {})
    findings = []
    for tag in tags:
        if tag in hard_deny:
            findings.append(_err("hard-deny-tag", where, f"hard_deny タグ {tag} は L2 付与不可です"))
        elif tag not in declared:
            findings.append(_err("unknown-tag", where, f"未定義のタグ {tag} です"))
    return findings


def _lint_until(grant, where, today):
    if "until" not in grant or grant["until"] is None:
        return [_err("until-missing", where, "期限（until）が必要です")]
    day = _as_day(grant["until"])
    if day is None:
        return [_err("until-invalid", where, "until は YYYY-MM-DD で書いてください")]
    if day < today:
        return [_warn("until-expired", where, "期限切れです（自動的に L1 に戻ります。不要なら削除を）")]
    return []


def _lint_action(grant, policy, where):
    kinds = policy.get("action_kinds") or {}
    action = grant.get("action")
    if action not in kinds:
        return [_err("action-unknown", where, f"action_kinds に無い種別 {action} です")]
    if not kinds[action].get("l2_eligible"):
        return [_err("action-not-l2-eligible", where, f"{action} は l2_eligible: false のため付与できません")]
    return []


def _lint_grant(grant, index, policy, today):
    where = f"grants[{index}]"
    if not isinstance(grant, dict):
        return [_err("grant-invalid", where, "grant はマッピングで書いてください")]
    findings = [
        *_lint_action(grant, policy, where),
        *_lint_tags(grant, policy, where),
        *_lint_until(grant, where, today),
        *_lint_scope(grant.get("scope"), where),
    ]
    if grant.get("max_level") != MAX_GRANT_LEVEL:
        findings.append(_err("max-level-invalid", where, f"max_level は {MAX_GRANT_LEVEL} のみ指定できます"))
    limit = grant.get("daily_limit")
    if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
        findings.append(_warn("daily-limit-missing", where, "daily_limit（1 以上の整数）の指定を推奨します"))
    return findings


def lint(policy, today):
    grants = policy.get("grants") or []
    if not isinstance(grants, list):
        return [_err("grants-invalid", "grants", "grants はリストで書いてください")]
    findings = _lint_policy_level(policy)
    for index, grant in enumerate(grants):
        findings.extend(_lint_grant(grant, index, policy, today))
    return findings


def main(argv=None):
    parser = argparse.ArgumentParser(description="委任ポリシーの lint")
    parser.add_argument("path", nargs="?", default=str(DEFAULT_POLICY))
    args = parser.parse_args(argv)
    findings = lint(load_policy(args.path), date.today())
    for f in findings:
        print(f"{f.level.upper()} [{f.code}] {f.where}: {f.message}")
    errors = [f for f in findings if f.level == "error"]
    print(f"policy lint: {'NG' if errors else 'OK'}（error {len(errors)} / warning {len(findings) - len(errors)}）")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
