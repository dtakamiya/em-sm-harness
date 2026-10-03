# 架空の 1 週間データセット（emh-021）

模擬運用・テスト用。**すべて架空**（`ex-proj` / `EX-101` / `member-a`〜`c`）。実データ・会社固有情報は入れない。
想定の「今日」は `2026-10-08`（水）。形式は設計書 [04](../../../docs/design/04-personal-tasks.md) / [06](../../../docs/design/06-cache-schema.md) / [13](../../../docs/design/13-slack-paste-input.md) に従う。

| 置き場 | 内容 |
|---|---|
| `slack/` | 貼り付け 2 件（依頼・決定・障害物・リスク・感情の兆候を 1 つずつ含む） |
| `jira-cache/` | 4 課題（滞留・見積もり変更・スコープ移動・ブロック関係・完了） |
| `confluence-cache/` | 2 ページ（未解決の決定事項・未変換の表あり） |
| `tasks/` | 個人タスク 4 件 + 候補 1 件（期限超過・催促・defer 2 回・Slack/Confluence 由来を含む） |

仕込んだ状況（先回り検知 emh-017 の検証用）: EX-101 は flagged で EX-103 を止めている / デモ環境の担当が未決（期限 10/09）/ member-c の staging データ待ち / 期限超過タスク 1 件。
いずれも「観察された事実」のみで、原因や人物評価は含めない。

実行例: `python3 scripts/morning_plan.py --tasks tests/fixtures/sample-week/tasks/tasks.json --candidates tests/fixtures/sample-week/tasks/candidates.json --today 2026-10-08`
