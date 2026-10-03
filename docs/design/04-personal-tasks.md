# EM 個人タスク管理（初版ドラフト）

状態: ドラフト。データはすべて `data/tasks/`（gitignore）。

## ねらい
EM 自身がやるべきことを一箇所に集め、「今日やること」を秘書が段取りする。
Slack の依頼・Jira のアサイン・Confluence のアクションアイテムが散らばっても、取りこぼさない。

## タスクの出所
- Slack 貼り付けの「依頼」（EM 宛て）
- Jira: EM がアサインされた課題 / EM がレビュー・承認待ちの課題
- Confluence: 議事録のアクションアイテム（担当が EM）
- 手動追加（口頭・思いつき）
- 秘書自身が先回りで起こすもの（例: 会議前の準備、返信待ちの催促）

## データモデル（`data/tasks/tasks.json`）
```json
{ "id": "t-0001", "title": "...", "status": "open|doing|waiting|done|dropped",
  "due": "YYYY-MM-DD|null", "source": "slack|jira|confluence|manual|secretary",
  "source_ref": "ABC-123 / ページURL / 貼り付けファイル名", "waiting_on": "人名(匿名化可)|null",
  "next_check": "YYYY-MM-DD|null", "priority": "now|soon|later", "notes": "...",
  "created": "...", "updated": "..." }
```
- 完了・中止は物理削除せず `done` / `dropped` にして履歴を残す
- `waiting`（waiting-for）= 他者待ち。`next_check` に催促・確認日を持つ

## 操作
add / done / defer（期限変更）/ delegate（他者へ委譲し waiting に）/ snooze / drop。
操作は EM が秘書に自然言語で依頼 → 秘書が `tasks.json` を更新（個人タスクは EM 自身のデータなので、秘書が直接更新してよい。他者・外部ツールへの書き込みは別）。

## 秘書の動き
- **朝の「今日の計画」**: 期限・重要度・ブロック影響で並べ、今日の上位3〜5件 + 会議準備 + 催促候補。60秒で読める量
- **取り込み時**: 新しい貼り付け/同期のたびに、新規タスク候補と重複を提示（確定は EM）
- **waiting-for 追跡**: `next_check` 到来で催促の下書きを用意（送信は EM）
- **夕の棚卸し**: 未完了の繰り越し / 期限超過 / 長期放置（例: 14日以上動かないタスク）を「まだ要る？」と確認
- **週次**: 完了数・繰り越し・waiting の滞留を要約

## 既存の仕組みとの関係
Ryoko の `knowledge/personal-tasks.md`（生活全般の個人 TODO）とは別。ここは**仕事上の EM/SM タスク**専用で、実データは `data/tasks/` に閉じる。

## 未決事項
- 優先順位づけの基準（emh-016）、催促までの日数
- 秘書の起動方法（EM がコマンドを叩く / 朝に1回実行 など。常駐はしない前提）
