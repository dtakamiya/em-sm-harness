# em-sm-harness — 作業ルール

このリポジトリは EM/SM 業務ハーネスの開発リポジトリ。AI 組織の `em-harness` 部門が継続開発する。

## 必須ルール
- 現フェーズは設計のみ。**Jira / Confluence への実接続・API トークンの取得/保存/使用をしない**。接続コードを書くならインターフェースとモックまで
- 実データは `data/`（gitignore）。コミット・PR・報告に実名・Slack 本文・Jira / Confluence 実データを載せない。テストは架空/匿名化サンプルで
- 秘密値を書かない（環境変数名のみ）
- 作業は `feat/<topic>` ブランチ → push → PR 作成まで必ず行う。main 直 push 禁止。マージは人間（だいすけ）
- 人に関する出力は「観察された事実」+「解釈の候補」に分ける。断定・レッテル貼りをしない
- 因果と共起を区別する。共起を原因として書かない
- 外部ツール依存を主設計に混ぜない（Jira / Confluence + ローカル Markdown/JSON が前提）

## 参照
- 設計書: docs/design/
- 旧調査資料（参考のみ）: ~/work/claudecode-harness-em-patterns
