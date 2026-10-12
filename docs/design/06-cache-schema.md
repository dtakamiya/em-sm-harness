# キャッシュスキーマ（Jira / Confluence）

状態: ドラフト（設計のみ・実接続なし）。判断の背景は [ADR 0002](../adr/0002-cache-schema-and-retention.md)。
スキーマの値はすべて架空例（`ex-proj` / `EX-123`）。会社固有情報は書かない。TTL は EM 回答済み（Q-006: 14日）。`structured/` の保持は 90 日（Q-007: a）、`summary` は既定で保存しない（Q-008: a）。いずれも EM 回答済み。

## 1. 原則
- **必要フィールドのみ保存**。API レスポンスそのものは保存しない（取得直後に項目を絞り、元データは破棄）
- 保存前に JSON Schema（`additionalProperties: false`）で検証。不一致ならファイルを書かず「失敗」として報告（部分的に書かない）
- 値が無い項目は `null`。`0` と `null` を区別する（`story_points: 0` を `null` に潰さない）。スキーマに無い項目は足さない
- 取得・整形・書出しは**決定的スクリプト**が行う。em-fetcher（haiku）は実行して結果を報告するだけ（[07](07-fetcher-boundary.md)）
- 全ファイルに `schema_version` と `fetched_at`（ISO 8601）。項目を足すときは版を上げ、EM の承認を経る
- 取得しない: コメント本文・description・添付・メール・アバター・表示名・ラベル（自由記述）・sprint goal

## 2. Jira: `data/jira-cache/<project_alias>/<YYYY-MM-DD>.json`
`project_alias` はローカル設定上の別名（実プロジェクトキーはパスに出さない）。1 同期 = 1 日次スナップショット。同日の再同期は上書き。

| 階層 | フィールド |
|---|---|
| envelope | `schema_version` / `fetched_at` / `project_alias` / `jql_sha256`（JQL 本文は残さない。変更検知用）/ `complete`(bool) / `partial_reason` / `issue_count` |
| `issues[]` | `key` / `summary`（※下記）/ `status` / `status_category`（API の値そのまま: new・indeterminate・done）/ `issuetype` / `priority` / `assignee_ref` / `created` / `updated` / `resolved` / `story_points` / `flagged` / `parent_key` |
| `issues[].sprints[]` | `id` / `name` / `state` / `start` / `end`（繰り越しで複数。無ければ空配列） |
| `issues[].links[]` | `link_type` / `direction`（inward・outward）/ `issue_key`。取得は blocks 系のみ |
| `issues[].transitions[]` | `field`（`status` / `story_points` / `sprint` のいずれか）/ `from` / `to` / `at`。変更者（author）は持たない |

- `assignee_ref`: `u_` + HMAC-SHA256(ローカル鍵, accountId) の先頭 8 桁。**状態を持たない**ので採番表の破損が起きない。鍵は `config/local.*`（環境変数名のみ設計書に書く）。表示名との対応表はローカルスクリプトが `config/local.*` 側にだけ作る。キャッシュには表示名・メールを入れない
- `summary`: 課題の中身そのもの（機微になりうる）。設定 `store_summary`。false にすると `null` を書く「最小モード」（スキーマ変更なしで切替）。**既定は false**（EM 回答済み: Q-008=a）。保存したくなったら Q-003（会社ポリシー確認）後に再相談
- `transitions` の対象を status / story_points / sprint に絞る理由: ステータス滞留・見積もり乖離・スコープ変動の入力に要るため。**assignee の遷移は含めない**（人の割当履歴は評価に転用されやすい。担当偏りは現在値の `assignee_ref` で足りる。再アサイン分析が必要になれば emh-004 で理由を示し EM 承認を経て版を上げる）
- `resolved` は status 遷移から導けるが、遷移が TTL で消えた古い課題でも使えるよう保存する
- カスタムフィールド ID（story points・sprint）は `config/local.*` に置く

## 3. Confluence: `data/confluence-cache/<space_alias>/index.json` + `<pageId>.md`
本文 `.md` は本文のみ（メタは入れない）。メタは `index.json` に一本化。

| 階層 | フィールド |
|---|---|
| envelope | `schema_version` / `space_alias` / `fetched_at` / `complete` / `partial_reason` / `page_count` |
| `pages[]` | `page_id` / `title` / `version` / `last_modified` / `parent_id` / `labels[]` / `url` / `body_file` / `body_status` / `unconverted[]` / `body_sha256` / `fetched_at` |

- `body_status`: `ok` / `partial_unconverted` / `skipped_excluded`（除外対象のため本文を取得・保存しなかった）
- `unconverted[]`: `{kind, anchor}`。変換できなかったマクロ・表の種類と位置（EM が元ページを見に行く導線）。本文中には `[未変換:<kind>]` を置く
- 作成者・更新者は持たない。コメント・添付は取らない
- **取得範囲は許可リスト方式**（取得してよい space・ラベルを設定で列挙）。さらに取得後に除外ラベル（人事・評価など）を二重チェックし、該当は本文を破棄して `skipped_excluded`
- Jira キー（`ABC-123`）の抽出はここでは行わない（structured 工程。[02](02-confluence-input.md)）

## 4. 保持期間（TTL）と自動削除
- 基準: Jira は日次ファイルの `fetched_at`、Confluence はページの `fetched_at`（mtime は使わない。コピーで変わる）
- 日数: `config/local.*` の `ttl_days`。**コード側に固定の上限 30 日**（変更は PR 経由）。既定 **14 日**（EM 回答済み: Q-006）。この上限はキャッシュ（`jira-cache` / `confluence-cache`）にだけ適用。`structured/` は別設定・別上限（下記）
- 削除の契機（常駐・cron は使わない）:
  1. 同期コマンドと共通ローダの**起動時に `purge_expired()` を実行**（遅延パージ）
  2. **ローダは期限切れを読まない**（fail-closed。パージが失敗しても期限切れは使われない）
  3. 明示コマンド `cache purge [--dry-run]` / `cache purge --all`（緊急・異動・退職時）
  4. 期限切れ残置が検出されたら起動時に警告
- 部分取得（`complete: false`）も TTL で消える。消えた分は「再取得が必要」と表示
- 削除は監査ログに件数と alias のみ記録（本文・タイトルは書かない）
- 履歴の持ち越し（EM 回答済み: Q-007=a、90 日）: キャッシュは 14 日で消えるので、指標の入力は本文なし・`summary` なしの集計値として `data/structured/` に確定させる。保持は 90 日。**`assignee_ref` と遷移の個別履歴は持ち込まない**（担当者別の件数・SP の分布など集計値のみ。少人数だと鍵があれば逆引きでき、個人別データが長く残ると評価転用のリスクがあるため）。保持期間は `structured_ttl_days`（キャッシュの `ttl_days` とは別設定。コード側上限 90 日）。`summary` や本文を含む派生物（`structured/`・`outputs/`）はキャッシュと同じ 14 日を継承する
- 終了済みスプリントごとの完了 SP 合計（S2 用・[33](33-sprint-planning-material.md)）: `data/structured/sprint-done-sp/<project_alias>.json` = `{schema_version, project_alias, sprints: [{id, name, end, done_sp}]}`。`done_sp` = そのスプリントで `status_category = done` の課題の SP 合計（`null` は除外・`0` は含む。0 以上の整数）。キーはこの 4 つだけ（`assignee_ref`・課題キー・個人別の値は持たない）。読む側は `end` が新しい順に直近 3 件だけ使う。保持は上記の `structured_ttl_days`（90 日）

## 5. 会社データが会社 PC に残るリスクへの対策
1. 最小保存（上記）。表示名・メール・コメント・description は元から持たない
2. gitignore: `data/` と `config/local.*`（済）。コミット前検査で `git ls-files data config/local*` が空であることを確認（emh 項目として追加）
3. 権限: `umask 077`、ディレクトリ 0700・ファイル 0600。tmp に書いて rename（中途半端なファイルを残さない）
4. 保管環境（EM が実接続 GO 前に確認する前提条件）: FileVault 有効 / Time Machine・クラウド同期の対象外 / 個人 repo の clone 先が会社管理外に同期されない
5. ログ・エラーに本文・URL・Authorization・トークンを出さない（件数・HTTP ステータス・alias のみ）
6. 退役手順: `cache purge --all`
7. 本文はローカルでは原文のまま保存する（仮名化しない）。Claude に渡す前の人名マスクの要否は、会社ポリシー確認（Q-003）の結果で決める
