# 0002. Jira / Confluence キャッシュのスキーマ・保持期間・fetcher 境界

- 状態: 提案（EM が Q-006 に回答し PR をマージしたら採用）
- 日付: 2026-10-03
- 関連: emh-003 / docs/design/06-cache-schema.md / 07-fetcher-boundary.md / Q-006

## 背景・決めること
em-fetcher（haiku）導入に伴い、(a) 生レスポンスか必要項目のみか (b) フィールド一覧 (c) TTL と自動削除 (d) 会社データが PC に残るリスクへの対策、および fetcher と analyst/lead の責務境界を決める。後から変えにくい。制約: 設計のみ・実接続なし・cron 不使用（同期は明示実行）・会社固有情報は repo に書かない。

## 案
### 案A（出した人: em-builder 役）
必要項目のみ・日次スナップショット・JSON Schema 検証・遅延パージ + ローダの fail-closed・TTL 14 日（または 30 日）・取得/書出しは決定的スクリプトで haiku は実行報告のみ。transitions は status のみ、`assignee_id` は表示名を持たない実 ID。
### 案B（出した人: em-sm-analyst 役）
必要項目のみ・仮名 ID・`summary` 退避モード・TTL 45 日（または 90 日）+ 本文なしの集計値を長期保持・raw/derived 分離。transitions に story_points / sprint / assignee、`resolved` / `labels` / `parent` / sprint goal まで保存。

## 批評（互いの案への指摘）
- A への指摘（B 担当から）: story_points・sprint の履歴が無く見積もり乖離とスコープ変動が計算できない／assignee の実 ID はキャッシュに個人を直接残す／TTL 14 日は履歴不足（確定値を structured に出すのが必須条件）／fetched_at 基準だと差分同期で延命／Markdown 変換の欠落箇所が分からない
- B への指摘（A 担当から）: 仮名 ID の採番表を fetcher が持つと状態を持つ／assignee 遷移は評価転用リスク・01 に無い／labels・goal は自由記述で機微／jira_keys は fetcher でなく structured（偽陽性）／機密ページ除外は CQL だけでは漏れる（許可リスト + 取得後二重チェック）／Claude 入力は仮名化のみ、と本文全文保存は両立しない／削除契機が同期時だけだと消えない

## 決定
**A の骨格（スキーマ検証・決定的スクリプト・遅延パージ + fail-closed）に、B の指標入力と機微対策を取り込む。** em-lead 役の集約:
1. 必要項目のみ保存。生レスポンスは保存しない
2. `transitions` は status / story_points / sprint（指標 3 種の入力）。assignee 遷移・labels・goal は含めない。`resolved`・`parent_key` は含める
3. 担当は `assignee_ref`（HMAC 先頭 8 桁。状態を持たない）。表示名・メールはキャッシュに入れない
4. `summary` は既定で保存、設定で `null` にする最小モードを用意（スキーマ不変）
5. TTL: `ttl_days` は設定、コード側上限 30 日。既定は EM 判断（Q-006。推奨 14 日）。基準は `fetched_at`（日次ファイル／ページ単位）
6. 削除: 同期・ローダ起動時の遅延パージ + ローダが期限切れを読まない + `cache purge`。履歴は本文・summary なしの集計値を `structured/` に確定（90 日）
7. Confluence は許可リスト + 取得後の除外ラベル二重チェック。`unconverted[{kind, anchor}]`。Jira キー抽出は structured 工程
8. fetcher は決定的スクリプトの実行・報告のみ。境界の基準は「同じ入力 → 同じ出力か」

Ryoko の design-review 判定: **条件付き GO**。根拠: 必要最小保存・fail-closed・読み取り専用で、現フェーズ（設計のみ・L1）の逸脱なし。条件: (1) EM が Q-006 に回答 (2) 実接続 GO 前に保管環境の確認（FileVault・バックアップ除外）を前提条件に含める (3) 採用ステータスへの更新は EM のマージ後。

## 影響・残る論点
- 追加 backlog 候補: スキーマ検証と purge のモック実装、コミット前検査（data/ 混入防止）、structured 履歴スキーマ（emh-004 と連動）
- TTL 14 日では 1 スプリント分しか持てない。指標の確定値を毎回 structured に出す運用が前提（B の指摘。A も同意）
- 本文を Claude に渡す際の人名マスク要否は Q-003（会社ポリシー確認）の結果次第
