# 16. policy lint（委任ポリシーの検査）

- 根拠: [ADR 0001](../adr/0001-delegation-policy-approval-audit.md) の条件「最初の grants 付与前に lint」。実装: `scripts/policy_lint.py`
- 使い方: `python3 scripts/policy_lint.py [policy.yaml]`（省略時は `policy/delegation.yaml`）。EM が grants を足したら**コミット前に必ず実行**
- 読み取り専用。外部接続・書込なし。終了コード 0=OK / 1=error あり / 2=実行不能（YAML を読めない等。**fail-closed**）

## 検査ルール

| code | level | 内容 |
|---|---|---|
| hard-deny-tag | error | grant の `tags` が hard_deny タグ（人事評価・懲戒等）に触れる |
| tags-missing / unknown-tag | error | `tags` が空・未定義。タグ無し = L1 止まりなので、許可タグを明示させる |
| scope-missing | error | L2 に `scope`（`template_id` と `recipients` の固定）が無い |
| until-missing / until-invalid | error | 期限なし・日付形式不正 |
| until-expired | warning | 期限切れ（自動で L1 に戻る。掃除の促し） |
| action-unknown / action-not-l2-eligible | error | `action_kinds` に無い、または `l2_eligible: false`（jira.comment 等は永続 L1） |
| max-level-invalid | error | `max_level` が L2 以外 |
| default-not-deny / hard-deny-unknown-tag | error | ポリシー本体の自己検査 |
| daily-limit-missing | warning | 1 日の上限が無い（推奨） |

grant の書式は `policy/delegation.yaml` のコメント例に `tags: [none]` を加えたもの。サンプル: `tests/fixtures/policy/`（NG / OK、架空）。

## YAML 依存の扱い（暫定）
stdlib に YAML パーサが無い。自前パーサは安全ゲートで誤読すると致命的なので、**PyYAML を必須とし、無ければ NG（終了コード 2）**にした。lint 以外のスクリプトは従来どおり stdlib のみ。判断は [Q-018](open-questions.md)。

## 限界
- lint は grants の**形**を検査するだけ。内容の機微の判定（タグ付け）は秘書の自己申告で、lint では捕まえられない（ADR 0001 の懸念どおり。だから自由文は L2 にしない）
- `reversible: false` の扱い（Q-014 b）は実行時の判定で、設定の lint 対象外
