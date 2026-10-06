# Confluence 入力設計（詳細版ドラフト・実接続はしない）

状態: ドラフト（emh-011）。**実接続は EM 本人の明示 GO まで行わない。** 認証・レート制御・失敗時挙動は [01-jira-connection.md](01-jira-connection.md) と共通。
保存スキーマ・TTL・削除は [06](06-cache-schema.md)、fetcher の責務境界は [07](07-fetcher-boundary.md)、GO 前提は [09](09-go-checklist.md) を正とする。
値はすべて架空例（`ex-space` / `EX-123`）。会社固有情報は `config/local.*` にのみ置く。

## 1. 認証と権限
- Cloud: Jira と**同じ API トークン**を共用（`JIRA_USER_EMAIL` / `JIRA_API_TOKEN`）。Confluence 用 base URL のみ `CONFLUENCE_BASE_URL`。**Cloud 確定**（Q-001・EM 回答済み）。Data Center（PAT）は対象外
- 権限は**読み取りのみ**。書込権限を含むトークンしか無い場合は、書込 API を呼ぶコードを一切持たないこと（HTTP メソッドは GET のみ許可。テストで固定）で担保する
- **トークンは Claude から見えない運用が必須**（Q-003 回答）。取得コマンドは EM が自分のターミナルで直接実行し、Claude は結果のキャッシュだけ読む。詳細は [09 C0](09-go-checklist.md)
- ログ・エラーにトークン・Authorization ヘッダ・認証付き URL・ページ本文・タイトルを出さない（件数・HTTP ステータス・`space_alias` のみ）

## 2. 取得範囲（許可リスト方式）
- 初期スコープ: **議事録・レトロのみ**（Q-002 回答済み・EM 2026-10-04。仕様・意思決定記録・報告資料は将来候補で、現状は取得しない。該当ページが無くてもエラーにしない。[30](30-confluence-page-types.md)）
- 設定（`config/local.*`、gitignore）で列挙するもの:
  - `spaces`: 取得してよい space の `space_alias` ↔ 実キーの対応
  - `include_labels`: 取得対象ラベル（例: `ex-minutes` / `ex-retro`）
  - `exclude_labels`: 除外ラベル（人事・評価・採用・個人の機微など）
  - `root_page_ids`（任意）: ページツリーで絞る場合の起点
- 許可リストに無い space・ページは**取りに行かない**。さらに取得後に `exclude_labels` を二重チェックし、該当は本文を破棄して `body_status: skipped_excluded`（[06 §3](06-cache-schema.md)）
- 取得する: タイトル / 本文 / 最終更新日・版 / 親ページ ID / ラベル / URL
- 取得しない: 添付・コメント・作成者・更新者・個人プロファイル・ページ履歴の本文（版番号のみ）。必要になれば別途設計し EM 承認

## 3. 取得方式（読み取りのみ・コマンド明示実行）
1. **検索**: CQL で対象 ID を列挙（本文は取らない）
   - 例（架空）: `space = "EX" AND label IN ("ex-minutes","ex-retro") AND label NOT IN (<exclude_labels>) AND lastmodified >= "<前回同期日>" AND type = page`
   - 初回は `lastmodified >= now("-14d")`（キャッシュ TTL と同じ 14 日。[06 §4](06-cache-schema.md)）
   - ラベルでの絞り込みを必須にする。**CQL が空条件・space のみで発行されないようスクリプト側で拒否**（意図しない全量取得の防止）
2. **ページネーション**: 検索結果の `limit` は固定上限（既定 25）。次ページ URL を辿り、重複 ID は排除。総件数に上限（既定 100 ページ／回）を設け、超えたら `complete: false` / `partial_reason: "page_limit"` で打ち切る
3. **本文取得**: ページ ID ごとに storage 形式で取得 → §5 の機械変換 → `<pageId>.md`。メタは `index.json` へ（スキーマは 06）
4. **差分判定**: `version` が前回キャッシュと同じなら本文を再取得しない（`fetched_at` のみ更新）。`body_sha256` で変換結果の変化も検知
5. **書出し**: JSON Schema 検証 → tmp に書いて rename（部分書きしない）。権限 0600
6. **キャッシュ保持**: TTL 14 日・遅延パージ（06 §4）。常駐・cron・定期実行はしない

### レート制御・失敗時（Jira と同方針）
| 事象 | 挙動 |
|---|---|
| 401 / 403 | 即中断。「トークン失効 or 権限不足」と表示。再試行しない。取得済み分は保持 |
| 404（ページ削除・移動） | そのページを `index.json` から外し、件数だけ報告（他は続行） |
| 429 | `Retry-After` に従い指数バックオフ（上限回数あり）。連続失敗で中断し `complete: false` |
| 5xx / タイムアウト | 数回リトライ後に中断。`partial_reason` に HTTP ステータスのみ記録 |
| スキーマ不一致 | そのページは書かず「失敗」として報告。部分的に書かない |
| 部分取得 | 出力冒頭に「取得範囲が不完全」と明記。後段の要約・突合は断定しない |

## 4. 手動入力フォールバック
トークン不可・権限不足で API が使えない場合は、ページを Markdown/HTML エクスポート（またはコピー）して
`data/inbox/confluence/YYYY-MM-DD-<slug>.md` に置く。同じ構造化パイプラインに入る。
- 先頭に任意のメタ（YAML front matter）: `title` / `url` / `version` / `last_modified`。無ければ `null` とし、要約には「出典メタ不明」と明記
- `exclude_labels` 相当（機微ページ）は貼らない運用。貼られた場合に備え、取り込み時に EM 宛てに「機微ページは貼らない」と一言警告
- 変換できなかった表・図は `[未変換:<kind>]` を手で残してよい

## 5. 本文変換: storage 形式 → Markdown（機械的・決定的）
変換は決定的スクリプトが行い、LLM に変換させない（[07](07-fetcher-boundary.md)）。変換不能は欠落させず `[未変換:<kind>]` を本文に置き、`index.json` の `unconverted[]` に `{kind, anchor}` を記録、`body_status: partial_unconverted`。

| storage 要素 | 変換 |
|---|---|
| 見出し `h1`〜`h6` | `#`〜`######` |
| 段落・リスト・番号リスト・入れ子リスト | Markdown リスト（入れ子維持） |
| 単純な表（結合セル・入れ子なし） | Markdown 表 |
| 結合セル・入れ子表 | `[未変換:table]`（行数・列数を anchor に） |
| タスクリスト `ac:task-list` | `- [ ]` / `- [x]`（担当・期限メンションは本文文字列として残す） |
| コードブロック macro | フェンス付きコード |
| 情報/注意/メモ panel macro | 引用ブロック（種別を先頭に `> [info]`） |
| 内部リンク `ac:link` | `[タイトル](ページURL)`。ページ ID が許可リスト外なら URL を残さずタイトルのみ |
| ユーザーメンション | `@[user]`（表示名は持たない。[06](06-cache-schema.md) と同じ） |
| Jira macro / 課題リンク | 課題キーのみ残す（`EX-123`）。macro 本体は未変換扱いにしない |
| 日付 `time` | ISO 8601 |
| 画像・添付・draw.io・その他 macro | `[未変換:<macro名>]` |

変換は冪等（同じ入力 → 同じ出力）にし、`body_sha256` で検証する。

## 6. 構造化（Jira・Slack と突合できる形）
ページ種別ごとの抽出観点は [30](30-confluence-page-types.md)（emh-012）。ここでは**共通の出力形**だけ定める。抽出は [28](28-meeting-notes-input.md) の `items` / `excluded` で行い、下表の配列はそこから導出する（30 §2）。（出力先 `data/structured/`、保持 90 日。06 §4）:

| 項目 | 内容 |
|---|---|
| `source` | `page_id` / `version` / `url`（要約・抽出結果には必ず添える） |
| `decisions[]` | 決定事項（原文の該当箇所の引用 or 見出し位置を付ける） |
| `deadlines[]` | 期限（日付が解釈できない記述は原文のまま `raw` に残し、日付化しない） |
| `owners[]` | 担当（原文表記。`assignee_ref` と照合せず、突合は analyst の仕事） |
| `open_items[]` | 未決事項 |
| `jira_keys[]` | 本文中のキー（正規表現 `\b[A-Z][A-Z0-9]+-\d+\b`）。**キー形式の一致のみ**で、実在確認・課題への紐付けはキャッシュ側と突合して analyst が行う（バージョン番号など偽陽性があり得るため） |
| `notes` | 抽出できなかった・曖昧だった箇所（未変換部分を含む） |

- 原文にないことを補わない。推測した担当・期限は書かない（空欄 + `notes`）
- 人に関する抽出（担当者・発言）は「観察された事実」のみ。評価的な言い換えをしない

## 7. 実装段階
1. インターフェース（`ConfluenceSource`）+ モック実装（`tests/fixtures/` の架空 storage 形式サンプルを返す）
2. 変換器（§5）を架空サンプルでテスト: 単純表 / 結合セル / task-list / 未知 macro / 課題キー / 除外ラベル
3. キャッシュ読み取り型スキル（モックで動作確認）
4. 実 HTTP 実装（**GO 後のみ**）。接続テストは検索 1 クエリ（本文なし）から

## 8. 書き込み
なし（GET のみ）。将来必要になった場合は別設計で「ドライラン → 差分表示 → 本人承認 → 実行」。

## 9. 未決事項
- 初期の取得範囲は Q-002 で確定（議事録・レトロのみ）。Cloud / Data Center は Cloud で確定（Q-001）
- 除外ラベルの具体名（会社側の運用に依存。EM が `config/local.*` に設定）
- Confluence の Claude 処理可否は **可**（Q-012・EM 回答済み）。Slack 貼り付けは別途
