# アーキテクチャ（初版ドラフト）

状態: ドラフト（em-harness 部門が週次で改訂する）

## 目的
多忙な EM に代わって EM/スクラムマスター業務を進める秘書。「集める → 管理する（個人タスク）→ 先回りする → 下書きする → 判断材料を整える」を、Claude Code のスキルとスクリプトで行う。
権限は委任ラダー（[03-secretary-model.md](03-secretary-model.md)）で管理。現在は L1（下書きまで）で、送信・更新は EM 本人。

## データフロー

```
 Jira / Confluence (API トークン)   Slack（手で貼る）
        │ 読み取りのみ                 │
        ▼                            ▼
 data/jira-cache/*.json        data/inbox/slack/YYYY-MM-DD-*.md
 data/confluence-cache/*.json         │ 匿名化 → 構造化
        └──────────────┬─────────────┘
                       ▼
            data/structured/*.json   （正規化データ: 決定/依頼/リスク/障害物/チケット状態）
                       │
                       │      ＋ data/tasks/tasks.json（EM の個人タスク。04-personal-tasks.md）
                       ▼
        秘書スキル（今日の計画 / 先回り検知 / 下書き生成 / スプリント健全性 / レトロ・1on1準備）
                       │
                       ▼
            data/outputs/YYYY-MM-DD-*.md  （EM が読む成果物・下書き）
            data/actions/*.json           （秘書が「やりたいこと」をデータで提示。実行は EM。L2 付与後は policy 判定）
            data/audit/*.jsonl            （何を・いつ・どの判定で扱ったかの記録。本文は持たない。05-approval-and-audit.md）
```

## 設計方針
- **実データはすべて `data/`（gitignore）**。リポジトリに入るのはコード・テンプレ・設計書・架空サンプルのみ
- **外部依存は Jira / Confluence のみ**（Atlassian 認証を共通化）。他の MCP/SaaS 連携を前提にしない
- **段階的**: まず Slack 貼り付け取り込み＋モック Jira で出力を磨き、Jira 実接続は最後（GO 後）
- **事実と解釈の分離**: 出力は「観察（事実・出典付き）」と「解釈の候補」を別セクションにする
- **60秒で読める**: 出力は結論→要対応→詳細の順。長いものは詳細に回す

## 非ゴール
- Jira / Confluence / Slack への書き込み・自動投稿（L2 付与までは非ゴール）
- チームメンバーへの展開、人事評価の自動判定
- 実接続（現フェーズ）

## 最初に作る機能（emh-002 で見直し）
1. 朝の「今日の計画」（個人タスク + 期限 + ブロッカー + 会議準備 + 催促候補）
2. Slack 貼り付け取り込み → 依頼のタスク化・返信案
3. スプリント健全性チェック / レトロ・1on1 準備の下書き

## 未決事項
- Cloud か Data Center か → **Cloud**（Q-001 回答済み）
- 対象プロジェクト・ボード・Confluence スペースの範囲
- Slack 貼り付けの標準フォーマット（チャンネル名・日時・スレッド構造をどこまで含めるか）
