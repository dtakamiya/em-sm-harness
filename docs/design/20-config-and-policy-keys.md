# 20. 委任ポリシーと現地設定のキー一覧（再構築用）

**結論: この表が正。`docs/` だけ持ち込んでも、ここから `policy/delegation.yaml` と `config/templates/local.yaml.example` を再生成できる。**

## 目的と使い方
- 根拠: [10 再構築ガイド](10-rebuild-guide.md) §5 のギャップ（emh-027。コードにしか無い仕様があると再構築で食い違う、という指摘）
- 食い違いを見つけたら設計書が正。現地で補った仕様は匿名化した一言で開発側へ返す
- 値はすべて架空。会社固有値は `config/local.*`（gitignore）にだけ書く

## 用語（初出の説明）
- **委任ラダー L0 / L1 / L2**（[03](03-secretary-model.md)）: L0=外部への書込でない（個人タスクの更新など。承認不要）/ L1=下書きまで（EM が自分で送信・更新する。**現在はここまで**）/ L2=EM が種別ごとに付与した範囲だけ秘書が実行
- **hard_deny（ハードデナイ）**: どう設定しても L2 にできないタグ。人事評価など EM 本人の判断領域
- **KILL**: `policy/KILL`（空ファイル）を置くと、付与済みの L2 も全て止まる非常停止
- **ADR**: Architecture Decision Record。設計判断の記録。委任ポリシーの根拠は [ADR 0001](../adr/0001-delegation-policy-approval-audit.md)

## 検査の範囲（事実）
`tests/test_design_keys.py` が検査するのは次の範囲のみ。
- §1 最上位キー、§2 `action_kinds` のキーと `default_level` / `l2_eligible`、§3 タグ、§5 の設定キーが、実ファイルと一致すること
- 表から組み立てたポリシーが `scripts/policy_lint.py` を通ること（受け入れ基準。下記）

**検査しない**: §4 `grants[]` の書式（実ファイルの grants は空のため突き合わせる対象が無い。書式の正しさは [16 policy lint](16-policy-lint.md) が grants 付与時に検査する）、`note` 等の文言、§5 の値。

## 受け入れ基準
`docs/` の表だけからポリシーを組み立て（`default: deny`・§2 の種別とレベル・§3 のタグ・`grants: []`）、`policy_lint` がエラー 0 で通ること。テストが機械的に確認する。

## 1. `policy/delegation.yaml` 最上位キー

| キー | 型 | 値（雛形） | 意味 |
|---|---|---|---|
| `version` | int | `1` | スキーマ版 |
| `default` | str | `deny` | 書かれていない種別・タグは拒否。`deny` 以外は lint エラー |
| `action_kinds` | map | §2 | 外部書込の種別ごとの既定 |
| `sensitivity_tags` | list | §3 | 内容の機微タグの定義 |
| `hard_deny_tags` | map | §3 | L2 付与不可のタグと理由 |
| `grants` | list | `[]` | L2 付与。空 = 現状（L1）。書式は §4 |

判定順（ADR 0001）: (1) hard_deny タグ該当 → L2 不可 (2) タグ無し・不明 → L1 止まり (3) grants 不一致 → L1 (4) `reversible: false` / 宛先が scope 外 → L1 (5) 上限・期限・KILL・不在 → L1。全 L2 即停止は `policy/KILL`（空ファイル）。

## 2. `action_kinds`（各項目は `default_level` / `l2_eligible` / `note`）

| キー | default_level | l2_eligible | 理由（要点） |
|---|---|---|---|
| `action_kinds.jira.comment` | L1 | false | 他人が読み EM の声に見える。永続 L1 |
| `action_kinds.jira.transition` | L1 | false | 自動化の連鎖がある。永続 L1 |
| `action_kinds.jira.update_own_task` | L1 | false | 候補。EM が付与するまで L1 |
| `action_kinds.slack.send` | L1 | true | 自由文は L2 不可。テンプレ固定＋宛先固定の定型のみ候補 |
| `action_kinds.confluence.update` | L1 | false | — |
| `action_kinds.task.update` | L0 | false | 秘書自身のローカルデータ操作。承認不要・監査ログは取る |

- レベル: L0=外部書込でない（承認不要）/ L1=下書きまで（EM が送信）/ L2=EM が種別ごとに付与した範囲のみ秘書が実行
- `l2_eligible: false` の種別を grants に書くと lint エラー（[16](16-policy-lint.md)）

## 3. タグ

| キー | 区分 | 理由（`hard_deny_tags` の値） |
|---|---|---|
| `sensitivity_tags.none` | 通常 | — |
| `sensitivity_tags.hr_eval` / `hard_deny_tags.hr_eval` | L2 不可 | 人事評価は EM 本人の判断 |
| `sensitivity_tags.discipline` / `hard_deny_tags.discipline` | L2 不可 | 懲戒は EM 本人の判断 |
| `sensitivity_tags.comp` / `hard_deny_tags.comp` | L2 不可 | 報酬は EM 本人の判断 |
| `sensitivity_tags.hiring` / `hard_deny_tags.hiring` | L2 不可 | 採用判断は EM 本人の判断 |
| `sensitivity_tags.one_on_one_sensitive` / `hard_deny_tags.one_on_one_sensitive` | L2 不可 | 1on1 の機微な内容は共有先を EM が決める |
| `sensitivity_tags.new_commitment` / `hard_deny_tags.new_commitment` | L2 不可 | 上長・他部門への新規の約束は EM 本人のみ |
| `sensitivity_tags.escalation_upward` / `hard_deny_tags.escalation_upward` | L2 不可 | 上長・他部門宛の連絡は EM の声として出す |

`none` 以外はすべて `hard_deny_tags` にも入る（`hard_deny_tags` のキーは `sensitivity_tags` に含まれること）。迷ったらタグを付ける（厳しい側）。

## 4. `grants[]` の項目（雛形では空）

| キー | 必須 | 意味 |
|---|---|---|
| `action` | ✔ | `action_kinds` のキー。`l2_eligible: true` のみ |
| `max_level` | ✔ | `L2` のみ |
| `tags` | ✔ | 許可する内容タグ（hard_deny は不可） |
| `scope.template_id` / `scope.recipients` | ✔ | テンプレと宛先の固定。自由文は不可 |
| `until` | ✔ | 期限（ISO 日付）。切れると自動で L1 に戻る |
| `daily_limit` | 推奨 | 1 日の上限。超過分は承認キューへ |
| `shadow_runs` | 任意 | 初回 N 件は L1 で並走 |

## 5. `config/templates/local.yaml.example`（現地で `config/local.yaml` にコピーして埋める）

| キー | 型 | 雛形の値 | 備考 |
|---|---|---|---|
| `schema_version` | int | `1` | |
| `jira.enabled` | bool | `false` | 実接続は GO（[09](09-go-checklist.md)）まで false |
| `jira.base_url` | str | `https://example.invalid` | 現地で書き換え。repo に実値を書かない |
| `jira.project_keys` | list | `["EXAMPLE"]` | 対象プロジェクト（架空） |
| `jira.token_env` | str | `JIRA_API_TOKEN` | **環境変数名のみ**。値は Keychain |
| `confluence.enabled` | bool | `false` | |
| `confluence.base_url` | str | `https://example.invalid/wiki` | |
| `confluence.space_keys` | list | `["EXAMPLE"]` | |
| `confluence.token_env` | str | `CONFLUENCE_API_TOKEN` | 環境変数名のみ |
| `feedback.outbox` | str | `data/feedback-outbox.md` | 秘書が EM の一言を追記する先（[08](08-portability.md)） |
| `trial.start_date` | str | `""`（空） | 試用開始日（ISO 日付 `YYYY-MM-DD`）。EM が試用を始めた日に1回書く。空なら監査ログの最古日を**仮の開始日**として使い、出力に「仮」と明記する（[26 §1](26-trial-review-metrics.md)） |

社内固有の語（組織名・プロジェクト名等）の検出パターンは `local.yaml` ではなく `config/local.leak-patterns.txt`（1 行 1 正規表現・gitignore 済み）に置く（[19](19-check-no-leak.md)。Q-024=①で一本化。EM・2026-10-04）。
