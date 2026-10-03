# 可搬性設計（別 PC 運用・emh-019）

状態: ドラフト（EM レビュー待ち）

## 前提
開発は個人 Mac、運用は EM の会社 Mac。会社 Mac では実データ（Jira / Confluence / Slack 貼り付け / 個人タスク）を扱い、**その内容は会社 Mac の外に出さない**。したがって「repo は道具、データは現地」と割り切る。

## 原則
1. **clone（または同等の持ち込み）だけで動く** — 個人 Mac 固有の絶対パス・ユーザー名・ホスト名を書かない。パスは repo ルート相対のみ
2. **repo に入るのは コード・テンプレ・設計書・架空サンプルのみ**。実データと会社固有値は `data/` と `config/local.*`（どちらも gitignore 済み）
3. **セットアップはネットワーク不要・追加インストール不要**を原則（macOS 標準の bash / python3 だけ）。足す場合は EM 判断（open-questions に載せる）
4. **repo 更新が現地データを壊さない** — データ形式の変更は追加のみ。データ・設定ファイルに `schema_version` を持たせ、古い版は読めるか明示的に拒否する（黙って壊さない）
5. **会社 Mac から外へ出る経路は人手のみ** — 自動送信・自動 push をしない（L1 の方針と同じ）

## 置き場の区分

| 区分 | 場所 | git | 例 |
|---|---|---|---|
| コード・設計・雛形 | `docs/` `policy/` `config/templates/` `scripts/`（予定） | 入る | 設計書、委任ポリシー雛形 |
| 現地の設定 | `config/local.*` | 入らない | 対象プロジェクト、Jira フィールド対応、委任の実付与（`config/local.delegation.yaml`） |
| 現地のデータ | `data/` | 入らない | キャッシュ、inbox、tasks、outputs、audit |
| 秘密値 | macOS Keychain | 入らない | API トークン（環境変数名のみ設計書に書く） |
| Claude Code のローカル設定 | `.claude/settings.local.json` | 入らない | 個人の許可設定 |

雛形は `config/templates/` に架空値で置く。現地では `cp config/templates/local.yaml.example config/local.yaml` して埋める（`config/local.*` は gitignore なので雛形名は `local.` で始めない）。

## 現地セットアップの流れ（目標形）
1. repo を持ち込む（経路は Q-007）
2. 雛形を `config/local.*` にコピーして埋める（会社固有値はここだけ）
3. `data/` 配下のディレクトリを作る（`scripts/bootstrap`、未実装・backlog）
4. 環境チェック（`scripts/check-env`、未実装・backlog）: 必要コマンド有無、`data/` と `config/local.*` が gitignore されているか、repo 内に秘密値らしき文字列が無いか
5. 実接続は別途 GO 条件（emh-020）を満たしてから。それまではモックと貼り付けのみ

## 更新の流れ
- 個人 Mac で feat ブランチ → PR → だいすけがマージ。現地は `git pull`（または同等の持ち込み）で追従
- 現地データの形式が変わるときは CHANGELOG に「データ移行の要否」を必ず書く。移行が要る場合は移行手順を設計書に残し、移行前に `data/` のバックアップを取る手順を先頭に置く
- 現地の `config/local.*` は更新で上書きされない（gitignore なので pull で触れない）。雛形側にキーが増えたら CHANGELOG で告知

## フィードバック経路（現地 → 開発）
現地の実データは持ち出せないので、**匿名化した一言**だけを人手で運ぶ。

- 書く場所（現地）: `data/feedback-outbox.md`（gitignore）に `- YYYY-MM-DD 一言` で追記
- 書く時の規則: 実名・社内固有名・Jira キー・Slack 本文・URL を書かない（`<人A>`、`<チケットX>` に置換）。迷ったら書かない
- 運ぶ方法: EM が内容を読み、問題なければ [feedback-inbox.md](feedback-inbox.md) に追記（repo に入れられる場合）、または Ryoko に直接伝える（経路は Q-008）
- 秘書は feedback-outbox を**書くだけ**（EM の一言を整形して追記）。送信・同期はしない
- 開発側は inbox を拾い、バックログに `proposed` として載せる（既存運用どおり）

## 持ち出し事故の防止
- `.gitignore` が `data/` `config/local.*` `.env*` `secrets/` `.claude/settings.local.json` を除外していること（環境チェックで毎回確認）
- コミット前チェック（`scripts/check-no-leak`、未実装・backlog）: staged に `data/` 配下があれば停止、トークン形式・社内ドメインらしき文字列があれば警告。社内ドメインの検出パターン自体は `config/local.*` に置く（repo に書かない）
- 出力物（`data/outputs/`）を外部に貼る時は EM が読んでから。秘書は貼らない

## 非ゴール
- 複数 EM への配布・汎用化
- 自動同期（個人 Mac ↔ 会社 Mac）。同期は人手のみ
- 実接続の手順（emh-020 / Jira・Confluence 接続設計書の担当）

## 未決（open-questions）
- Q-007: repo の持ち込み経路
- Q-008: フィードバックの運び方
