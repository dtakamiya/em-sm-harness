# 可搬性設計（別 PC 運用・再構築前提）

状態: ドラフト（EM レビュー待ち）。改訂: emh-026（Q-003 / Q-011=a 反映）

## 前提
開発は個人 Mac、運用は EM の会社 Mac。会社 Mac では実データ（Jira / Confluence / Slack 貼り付け / 個人タスク）を扱い、**その内容は会社 Mac の外に出さない**。逆に**個人 repo も会社 Mac に持ち込まない**（Q-003 回答）。したがって「**設計書は持ち込む・コードは現地で作り直す・データは現地**」と割り切る。

## 原則
1. **持ち込むのは `docs/` のみ**（Q-011=a）。`policy/` `config/templates/` `scripts/` は持ち込まない。現地の Claude が設計書から再生成する（手順は [10-rebuild-guide.md](10-rebuild-guide.md)）。そのため**設計書だけで再構築できる**ことが設計書の品質基準（スキーマ・ルール・禁止事項は docs に文章で書く。コードにしか無い仕様を作らない）
2. **repo に入るのは 設計書・テンプレ・架空サンプルのみ**。実データと会社固有値は現地の `data/` と `config/local.*`（gitignore）。個人 Mac の絶対パス・ユーザー名は書かない
3. **再構築はネットワーク不要・追加インストール不要**を原則（macOS 標準の bash / python3）。足す場合は EM 判断（open-questions）
4. **設計書の更新が現地データを壊さない** — データ形式の変更は追加のみ。`schema_version` を持たせ、古い版は読めるか明示的に拒否する
5. **会社 Mac から外へ出る経路は人手のみ** — 自動送信・自動 push をしない（L1 の方針と同じ）
6. **トークンは Claude から見えない**（[09](09-go-checklist.md) C0）。取得は EM が自分のターミナルで実行し、再構築側は出力ファイルだけを読む

## 置き場の区分

| 区分 | 場所 | git | 例 |
|---|---|---|---|
| 設計書 | `docs/` | 開発 repo に入る。**会社 Mac へ持ち込むのはこれだけ** | 設計書、ADR |
| 再構築物（現地で生成） | `policy/` `config/templates/` `scripts/` | 開発側 repo にはある（参照実装）が持ち込まない。現地で設計書から作る | 委任ポリシー、雛形 |
| 現地の設定 | `config/local.*` | 入らない | 対象プロジェクト、Jira フィールド対応、委任の実付与（`config/local.delegation.yaml`） |
| 現地のデータ | `data/` | 入らない | キャッシュ、inbox、tasks、outputs、audit |
| 秘密値 | macOS Keychain | 入らない | API トークン（環境変数名のみ設計書に書く） |
| Claude Code のローカル設定 | `.claude/settings.local.json` | 入らない | 個人の許可設定 |

雛形は `config/templates/` に架空値で置く。現地では `cp config/templates/local.yaml.example config/local.yaml` して埋める（`config/local.*` は gitignore なので雛形名は `local.` で始めない）。

## 現地セットアップの流れ（再構築）
詳細は [10-rebuild-guide.md](10-rebuild-guide.md)。要点:
1. 設計書（`docs/` のみ）を人手で会社 Mac に置く（経路は EM が会社ポリシーに沿って選ぶ。自動同期しない）
2. 現地の Claude が 10 の読み順で設計書を読み、`policy/`・`config/templates/`・スクリプトを再生成する
3. `config/local.*` を雛形から作って会社固有値を埋める（固有値はここだけ）。`data/` を作る
4. 環境チェック（gitignore・秘密値の混入が無いか）。`scripts/bootstrap.py`（置き場作成・local.yaml コピー・check_env 呼び出し。冪等・上書きしない）と `scripts/check_env.py`（読み取り専用）は作成済み（emh-024）。現地では設計書（本節・[10](10-rebuild-guide.md) §4）から同じ仕様で再生成する
5. 取得コマンドは EM 側が準備済み。その出力を入力契約（10 §3）どおりに `data/` へ置く。実接続は [09](09-go-checklist.md) の GO 後

## 更新の流れ（git pull は使えない）
- 個人 Mac で feat ブランチ → PR → だいすけがマージ。**現地への反映は設計書の差分を人手で持ち込む**（`docs/` のみ）
- 設計書の変更履歴は PR 説明に書く。**データ移行の要否**（`schema_version` 変更）を必ず明記し、移行が要る場合は手順を設計書に残す。移行前に現地 `data/` のバックアップを取る
- 現地の `config/local.*` は設計書の更新で触れない。雛形にキーが増えたら PR 説明で告知し、現地で追記
- 再構築物（スクリプト等）と設計書がずれたら**設計書が正**。現地で直した点は匿名化した一言で開発側へ返す（下記）

## 改善はどう回るか（EM 決定: 案A）
改善ループ（board 選択 → 分析 → 実装 → レビュー → PR → ログ）は **Ryoko 側（個人 Mac 環境）で継続**する。会社 Mac には設計書（`docs/`）だけを持っていき、会社 Mac 上で改善ループを自動で回さない。
現地で気づいた改善点は、下の「匿名化した一言」の経路で開発側へ戻す。開発側の更新は PR → EM がマージ → 設計書の差分を人手で現地へ持ち込む。

## フィードバック経路（現地 → 開発）
現地の実データは持ち出せないので、**匿名化した一言**だけを人手で運ぶ。

- 書く場所（現地）: `data/feedback-outbox.md`（gitignore）に `- YYYY-MM-DD 一言` で追記
- 書く時の規則: 実名・社内固有名・Jira キー・Slack 本文・URL を書かない（`<人A>`、`<チケットX>` に置換）。迷ったら書かない
- 運ぶ方法: EM が内容を読み、問題なければ **Ryoko に直接伝える**（Q-010 回答済み。push 権限や会社ポリシーに依存しない）。feedback-inbox.md への追記は、Ryoko 側が開発環境で行う
- 秘書は feedback-outbox を**書くだけ**（EM の一言を整形して追記）。送信・同期はしない
- 開発側は inbox を拾い、バックログに `proposed` として載せる（既存運用どおり）

## 持ち出し事故の防止
- `.gitignore` が `data/` `config/local.*` `.env*` `secrets/` `.claude/settings.local.json` を除外していること（環境チェックで毎回確認）
- コミット前チェック（`scripts/check_no_leak.py`、仕様は [19](19-check-no-leak.md)。個人 Mac 側の開発用。会社 Mac は repo を持たないので、現地版は再構築後に位置づけ再検討）: staged に `data/` 配下・トークン形式があれば停止、社内ドメインらしき文字列があれば警告。社内ドメインの検出パターン自体は `config/local.*` に置く（repo に書かない）
- 出力物（`data/outputs/`）を外部に貼る時は EM が読んでから。秘書は貼らない

## 非ゴール
- 複数 EM への配布・汎用化
- 自動同期（個人 Mac ↔ 会社 Mac）。同期は人手のみ
- 実接続の手順（emh-020 / Jira・Confluence 接続設計書の担当）

## 決定済み・未決（open-questions）
- Q-003 / Q-009 / Q-011=a / Q-012=可: 回答済み。持ち込み不可・設計書のみ持ち込み・再構築で確定。本書はその反映版
- Q-010: 匿名化した一言を EM が Ryoko に直接伝える（確定）
- Q-013（未回答）: 取得コマンドの出力形式の確認（10 §3 の契約案との差分）
