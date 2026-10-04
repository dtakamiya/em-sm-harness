# アーキテクチャ

状態: 全体像・データフロー・ディレクトリ・非ゴールを確定（emh-001）。詳細は各設計書へ。em-harness 部門が改訂する

## 目的
多忙な EM に代わって EM/スクラムマスター業務を進める秘書。「集める → 管理する（個人タスク）→ 先回りする → 下書きする → 判断材料を整える」を、Claude Code のスキルとスクリプトで行う。
権限は委任ラダー（[03-secretary-model.md](03-secretary-model.md)）で管理。現在は L1（下書きまで）で、送信・更新は EM 本人。

## 全体像（4層）

| 層 | 役割 | 触るデータ | 詳細 |
|---|---|---|---|
| 取り込み | Jira / Confluence を読み取り専用で取得、Slack は貼り付けを受ける | `data/jira-cache` `data/confluence-cache` `data/inbox` | [01](01-jira-connection.md) [02](02-confluence-input.md) [13](13-slack-paste-input.md) |
| 正規化 | 匿名化・構造化して共通スキーマにする | `data/structured` `data/tasks` | [06](06-cache-schema.md) [04](04-personal-tasks.md) |
| 秘書スキル | 計画・先回り検知・下書き・健全性チェックを生成 | 上記を読むだけ | [03](03-secretary-model.md) [12](12-secretary-job-list.md) |
| 承認・監査 | 提案を `actions` に出し、実行は EM。判定と記録は本文なし | `data/actions` `data/audit` | [05](05-approval-and-audit.md) [11](11-l2-candidates.md) |

責務境界: 取得（fetcher）は読み取りとキャッシュ書き込みだけ。解釈・下書きは analyst / lead 側。互いの領域に入らない（[07](07-fetcher-boundary.md)）。
横断ルール: 出力の品質基準は出力品質チェックリスト、別PC運用は [08](08-portability.md) / [10](10-rebuild-guide.md)、実接続の前提は [09](09-go-checklist.md)。

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

## ディレクトリ

```
docs/design/       設計書（00〜13）・open-questions.md（EM 判断待ち）
docs/adr/          設計判断の記録
policy/            委任ポリシー（delegation.yaml。L2 は当面 0 件）
config/templates/  設定の雛形（架空値のみ）。現地用は config/local.*（gitignore）
scripts/           bootstrap.py / check_env.py / check_no_leak.py ほか（作成済み）
skills/            秘書スキル（SKILL.md）。実装時に追加（未作成）
data/              実データ置き場（gitignore。inbox / jira-cache / confluence-cache /
                   structured / tasks / outputs / actions / audit）
```

`skills/` は実装フェーズで作る。現フェーズは設計のみのため空ディレクトリは置かない。

## 設計方針
- **実データはすべて `data/`（gitignore）**。リポジトリに入るのはコード・テンプレ・設計書・架空サンプルのみ
- **外部依存は Jira / Confluence のみ**（Atlassian 認証を共通化）。他の MCP/SaaS 連携を前提にしない
- **段階的**: まず Slack 貼り付け取り込み＋モック Jira で出力を磨き、Jira 実接続は最後（GO 後）
- **事実と解釈の分離**: 出力は「観察（事実・出典付き）」と「解釈の候補」を別セクションにする
- **60秒で読める**: 出力は結論→要対応→詳細の順。長いものは詳細に回す

## 非ゴール
- Jira / Confluence / Slack への書き込み・自動投稿（L2 付与までは非ゴール）
- チームメンバーへの展開、人事評価の自動判定
- 実接続（現フェーズ。接続コードを書くならインターフェースとモックまで）
- Jira / Confluence 以外の外部サービス（他 MCP / SaaS）を前提にした設計
- 人事評価・懲戒・報酬・採用判断・新規コミットの代行（L2 付与不可。常に EM 本人）

## 最初に作る機能（[12-secretary-job-list.md](12-secretary-job-list.md) §4 で見直し済み。順番は Q-015 で EM 確認）
1. 朝の「今日の計画」（個人タスク + 期限 + ブロッカー + 会議準備 + 催促候補）
2. Slack 貼り付け取り込み → 依頼のタスク化・返信案
3. スプリント健全性チェック / レトロ・1on1 準備の下書き

## 未決事項
- Cloud か Data Center か → **Cloud**（Q-001 回答済み）
- 対象プロジェクト・ボード・Confluence スペースの範囲
- 出力品質の受け入れ基準 → [14-output-quality-checklist.md](14-output-quality-checklist.md)（60秒・事実/解釈・因果/共起・レッテル・委任ラダー）
- Slack 貼り付けの標準フォーマット → [13-slack-paste-input.md](13-slack-paste-input.md) で設計済み（緩い解釈 + 任意の見出し行。実際のコピー形式との差は EM 確認）
