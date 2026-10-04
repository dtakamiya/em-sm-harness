# 再構築ガイド（会社 Mac 側の Claude 向け）

状態: ドラフト（EM レビュー待ち）。emh-026。前提: [08](08-portability.md)（`docs/` のみ持ち込み・Q-011=a）

会社 Mac の Claude が、設計書だけからハーネスを作り直すための手順書。会社固有値・トークン・実データは扱わない。

## 1. 読み順

| 順 | 文書 | 得るもの |
|---|---|---|
| 1 | [CLAUDE.md の必須ルール相当](#2-最初に守るルール) | 越えてはいけない線（この文書の §2 に要約） |
| 2 | [00-architecture](00-architecture.md) | 全体像・データフロー・ディレクトリ・非ゴール |
| 3 | [03-secretary-model](03-secretary-model.md) | 秘書の仕事・委任ラダー（現在 L1） |
| 4 | [05-approval-and-audit](05-approval-and-audit.md)・[ADR 0001](../adr/0001-delegation-policy-approval-audit.md) | 委任ポリシー・承認・監査ログ |
| 5 | [06-cache-schema](06-cache-schema.md)・[ADR 0002](../adr/0002-cache-schema-and-retention.md)・[07-fetcher-boundary](07-fetcher-boundary.md) | `data/` のスキーマ・保持期間・機械処理と判断の境界 |
| 6 | [01-jira-connection](01-jira-connection.md)・[02-confluence-input](02-confluence-input.md) | 取得対象と変換ルール（実接続はしない） |
| 7 | [04-personal-tasks](04-personal-tasks.md) | 個人タスクの形式と操作 |
| 8 | [09-go-checklist](09-go-checklist.md) | 実接続 GO の条件（満たすまで実接続しない） |
| 9 | [20-config-and-policy-keys](20-config-and-policy-keys.md) | `policy/` と `config/templates` の全キー表（再生成の正） |
| 10 | [open-questions](open-questions.md) | 未回答の論点（勝手に決めない） |

## 2. 最初に守るルール
開発側 CLAUDE.md は持ち込まれないため、**会社 Mac 側で `CLAUDE.md` を作り、次を必ず書く**。
- 現在は委任ラダー **L1（下書きまで）**。Jira / Confluence / Slack への書込・送信を実装しない・実行しない。人事評価・懲戒・報酬・採用・1on1 の機微・新規コミットは常に EM 本人
- 60 秒で読める・結論ファースト・判断依頼は「選択肢 2 つ以内＋おすすめ＋期限」。人に関する出力は「観察された事実」＋「解釈の候補」。共起を因果として書かない
- **トークンは Claude から見えない**: 取得コマンドは EM が自分のターミナルで実行。Claude セッションでは走らせない・認証情報ファイルや Keychain を読まない（[09](09-go-checklist.md) C0）
- 実データは `data/`、会社固有値は `config/local.*`（どちらも gitignore）。設計書・コミットに実名・社内 URL・フィールド ID を書かない
- 不明点は推測で埋めず、EM に聞く（open-questions 形式で）

## 3. 入力契約（EM の取得コマンドの出力を受ける形）
EM 側に取得コマンド（トークン使用）が準備済み（Q-003）。Claude は**その出力ファイルだけ**を読む。出力は次を満たす前提で再構築する。**EM の実コマンドの形式は未確認**（Q-013）。差があれば契約側ではなく取り込み層（変換スクリプト）で吸収する。

| 項目 | 契約 |
|---|---|
| 置き場 | Jira: `data/jira-cache/<project_alias>/<YYYY-MM-DD>.json` / Confluence: `data/confluence-cache/<space_alias>/index.json` + `<page_id>.md`（[06](06-cache-schema.md) §2–3） |
| 形式 | JSON（UTF-8）と Markdown。1 同期 = 1 日次スナップショット、同日再同期は上書き |
| 必須メタ | `schema_version` / `fetched_at`（ISO 8601）/ `complete`（bool）/ `partial_reason` |
| 項目 | 06 のスキーマにある項目のみ。`additionalProperties: false`。値なしは `null`（`0` と区別） |
| 禁止項目 | トークン・Authorization ヘッダ・認証付き URL・表示名・メール・コメント本文・description・添付。含まれていたらそのファイルは使わず EM に報告 |
| 失敗時 | `complete: false` か、スキーマ不一致のファイルは**読まずに止まり**「再取得が必要」と報告（部分データで指標を断定しない） |
| Slack | EM が貼った本文を `data/inbox/slack/YYYY-MM-DD-*.md` に保存（匿名化ルールは emh-005 で設計中） |

受け入れ確認（再構築後に 1 回）: 架空サンプルを 06 のスキーマに通し、①正常 ②`complete:false` ③禁止項目混入 ④`schema_version` 不一致 の 4 ケースが期待どおり（使う/使わない）になること。

## 4. 再構築の手順
1. §2 の `CLAUDE.md` を作る
2. `.gitignore` を確認/作成（`data/` `config/local.*` `.env*` `secrets/` `.claude/settings.local.json`）。会社 Mac で git を使わない場合も、同等の「持ち出し除外」を EM が決める
3. `policy/delegation.yaml` を [03](03-secretary-model.md)・[05](05-approval-and-audit.md)・ADR 0001 から再生成（**grants は空**・default deny・hard_deny タグ）
4. `config/templates/local.yaml.example` を作り、EM が `config/local.yaml` に会社固有値を記入
5. `data/` 配下を作成（権限 0700、ファイル 0600、`umask 077`）
6. 環境チェック（gitignore 有効・repo/設計書内に秘密値らしき文字列が無い）。これは [08](08-portability.md) の `check-env` 相当で、emh-024 の仕様はこの再構築物として現地で作る
7. §3 の受け入れ確認 → モック/貼り付けで日次の流れを 1 周（実接続なし）
8. 実接続は [09](09-go-checklist.md) が全 ✅ で EM が GO と明示してから

## 5. 設計書だけでは足りない点（既知のギャップ）
持ち込みが `docs/` のみのため、コードにしか無い仕様は再構築で失われる。現時点で疑わしい箇所:
- `policy/delegation.yaml` の `action_kinds` の個別設定は ADR 0001 と 03 に分散して書かれている。**再構築で食い違う恐れ** → [20](20-config-and-policy-keys.md) に集約済み（emh-027）
- `config/templates/local.yaml.example` のキー一覧は 06 / 01 / 02 に散在 → 同上（[20](20-config-and-policy-keys.md) §5）
- 食い違いを見つけたら**設計書が正**。現地で補った仕様は匿名化した一言で開発側へ返し、設計書に戻す
