# Confluence 入力設計（初版ドラフト・実接続はしない）

状態: ドラフト。**実接続は EM 本人の明示 GO まで行わない。** 認証・レート制御・失敗時挙動は [01-jira-connection.md](01-jira-connection.md) と共通。

## 認証
- Atlassian Cloud なら Jira と**同じ API トークン**（`JIRA_USER_EMAIL` / `JIRA_API_TOKEN` を流用。Confluence 用 base URL は `CONFLUENCE_BASE_URL`）。Data Center なら PAT（要確認）
- 読み取り専用のスコープ/アカウントを推奨。値はコード・設計書・ログに出さない

## 取得範囲（読み取り専用）
- 対象: 設定ファイルで指定したスペース/ページツリー（例: スプリント議事録・レトロ・意思決定記録・仕様・ステークホルダー報告）
- 取得: タイトル / 本文（storage 形式 → Markdown 変換）/ 最終更新日・版 / 親子関係 / ラベル / URL
- 取得しない: 添付・コメント・個人プロファイル（必要になれば別途設計・承認）
- 範囲は広げすぎない（最小スペース/ラベル指定から始める）

## 取得方式
- CQL 検索（`space`・`label`・`lastmodified >= 前回同期`）で差分取得 + ページネーション
- 結果は `data/confluence-cache/<space>/<pageId>.md`（本文）と索引 JSON に保存（gitignore）。スキルはキャッシュを読む
- 同期はコマンド明示実行のみ（常駐・定期実行はしない）

## フォールバック: 手動入力
トークン不可・権限不足の場合に備え、ページを Markdown/HTML エクスポート（またはコピー）して
`data/inbox/confluence/YYYY-MM-DD-<slug>.md` に置けば、同じ構造化パイプラインに入る。

## 構造化（Jira・Slack と突合できる形）
ページ種別ごとに以下を抽出し `data/structured/` に出力（種別と観点は emh-012）:
決定事項 / 期限 / 担当 / 未決事項 / 参照 Jira キー（本文中の `ABC-123` を検出して課題と紐付け）。
要約は元ページ URL と版を必ず添える。原文にないことを補わない。

## 失敗時
401/403 は即中断、429 はバックオフ、部分取得は出力に明記（Jira 設計と同じ）。
変換できないマクロ/表は「未変換」と明示して元 URL を残す。

## 書き込み
なし。

## 未決事項
- 対象スペース・ページ範囲、Cloud / Data Center
- 取り込んでよいページの機密区分（人事・評価に関わるページは対象外にする）

> キャッシュの詳細スキーマ・保持期間・削除は [06-cache-schema.md](06-cache-schema.md)、fetcher の責務境界は [07-fetcher-boundary.md](07-fetcher-boundary.md) を正とする。
