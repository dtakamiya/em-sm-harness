# 承認フローと監査ログ（初版ドラフト）

状態: ドラフト。設計判断の背景は [ADR 0001](../adr/0001-delegation-policy-approval-audit.md)。
現フェーズは **L1（下書きまで）**。ここに書く L2 の仕組みは「後から安全に足せる形」の設計で、有効化しない。

## 1. 判定の入力（ポリシー）
秘書が出す全アクションは [03](03-secretary-model.md) のデータ形式（`action` / `target` / `content` / `sensitivity` / `reversible` / `audience`）で表す。
**`level_required` / `reversible` / `sensitivity` は秘書の自己申告であり、権威は `policy/delegation.yaml`**。秘書の申告とポリシーが食い違えば、厳しい側を採る。

判定は2軸（`action` 種別 × `sensitivity` タグ）。順序:
1. hard_deny タグに該当 → L2 不可（理由付きで拒否ログ）
2. タグ無し・不明 → L1 止まり（「タグ無し = 安全」にしない）
3. `grants` に一致しない → L1
4. `reversible: false`、または宛先が `scope` 外 → L1 止まり
5. 期限切れ・日次上限超過・`policy/KILL` あり・EM 不在 → L1（承認キューに回す）

用語: `reversible` = 受け手に通知が届かずに元へ戻せるか。Slack 送信は削除できても通知は取り消せないので `false`。
L2 の付与は種別だけでなく **`scope`（テンプレ ID + 固定宛先）** で縛る。秘書が自由に書いた本文は L2 にしない（タグ付けの漏れが事故に直結しないため）。

## 2. 承認フロー
### 現在（L1）
`drafted → em_reviewed（編集/却下）→ em_sent | discarded | stale`
- 送信・更新は EM 本人。秘書は送信を直接観測できない
- **送信結果の把握**: 主は「次回の Slack 貼付取り込み時などに、下書きと照合して自動で推定」。照合できないものだけ EM が任意で報告（EM 決定 2026-10-03）
- 下書きの `expires` は種別ごとに持つ（既定は短め。期限付きの判断ほど短く）。超過で `stale`（自動破棄、監査には残す）

### 承認疲れの防止
- **朝夕の承認キュー1枚**: 各件は「1行の結論 + コピペできる本文 + 対象リンク」。1バッチ最大5件、優先度順。低リスク定型は「一括確認」欄にまとめる
- 通知は即時に割り込まない（緊急度が高いものを除く）
- 毎回編集される種別は「下書き品質の課題」として扱う（backlog 化）
- **L2 昇格の提案**は秘書が出せるが、付与は EM のみ。提案条件は明示する（例: 直近 N 件・M 日で、無修正採用率が高く、承認までの滞留が短くない = ゴム印でない）。無修正は「無関心な承認」と区別できないため、件数・修正率・確認時間の3点で見る。閾値は運用で調整（要 EM 確認）

### 将来（L2。有効化しない）
`dry_run → diff → em_approve（content_hash 束縛）→ execute → audit`
- 承認は1アクション1回。本文が変わったら `content_hash` が変わり、再承認
- 付与: EM が policy の diff を自分でコミット。必須項目 = 種別 / `scope` / `until` / `daily_limit` / `shadow_runs`
- 付与手順: 追記 → lint 通過 → 影子運用（初回 N 件は L1 のまま並走、実績を昇格判断の入力にする）→ 有効化
- 失効: `until` 超過で自動 L1 復帰。取り消しは policy の1行を戻す、または `policy/KILL` で全 L2 即停止
- 上限超過・EM 不在は fail-closed（書込せず承認キューに溜める）。秘書は代理承認者にならない

## 3. 監査ログ
### 位置づけ
- `data/actions/` = 下書き・アクション本体（本文を含む。保持期間付き）
- `data/audit/` = 「何を・いつ・どの判定で」扱ったかの記録（**本文を含まない**）
- L1 でも取る理由: (1) 修正率・採用率が L2 昇格判断の根拠になる (2) 拒否（hard_deny）の記録が残る (3) 形式を L2 前に実戦で試せる (4) 後付けでは取れない

### 形式（`data/audit/YYYY-MM-DD.jsonl`、追記専用・1行1イベント）
```json
{"ts":"2026-01-01T09:00:00+09:00","event":"drafted","action_id":"a-0001","action":"slack.send",
 "level_required":"L1","level_applied":"L1","tags":["none"],"target_ref":"example-channel",
 "audience":"team","content_sha256":"sha256:...","content_chars":120,"source_refs":["inbox-0003"],
 "policy_sha256":"sha256:...","decision":"L1_only","reason":"no_grant"}
```
- `event`: `drafted | em_reviewed | em_sent | discarded | stale | denied | executed`（`executed` は L2 まで出ない）。ローカルのタスク更新は別系統で `task_updated | task_reverted`、承認キューの本文なし記録 `queue_rendered | queue_item`（書式は [26 §2](26-trial-review-metrics.md)。**未実装**）。タスク更新の詳細は（[24](24-reply-apply.md)。`action=task.update`・`actor`・`op`・`target_id`・`changes`（変更ファイルごとの前後 `sha256`。同一 `batch_id` 内ではバッチ全体の反映前後の値）・`new_task_id`、本文なし）
- `result`（`em_reviewed` 以降）: `adopted_as_is | edited | rejected`。EM が実際に送った文面のハッシュを照合に使う
- 記録しない: 本文・Slack/Jira の文面・人への評価や所感・実名（ID か匿名ラベル）
- `policy_sha256`: 判定に使った policy の内容ハッシュ。付与状態を `config/local.*` に置く場合は、repo の雛形と local の結合結果のハッシュとする
- **日次サマリ**（先頭1行で把握）は別ファイル `data/audit/summary/YYYY-MM-DD.md` に生成する（追記専用ログを書き換えない）。例:「L2 実行 0 / ブロック 1 / 要確認 3」
- 改ざん検知: 行ごとの `prev_hash` 連鎖は **L2 付与時に必須化**（EM 単独運用の L1 では任意）
- 保持: 日次ファイル。12か月（本文を持たないため長めで可）。会社ポリシー確認後に見直し

### 事故時の追跡
誤送信・機微漏洩が起きたら `action_id` から 下書き → 出典 → policy 版 をたどる。EM が実際に送った文面のハッシュと突き合わせ、「秘書の下書きどおり」か「EM の編集後」かを切り分ける。

## 4. 非ゴール・残る論点
- 非ゴール: 実際の書込の実装、自動承認、秘書による代理承認
- 「新規コミット」の検知基準と承認キューのテンプレは [21](21-approval-queue.md) に定義（emh-023）
- policy lint の実装（hard_deny に触れる grants を弾く）は未着手 → backlog に追加
- EM 決定済み（2026-10-03）: 送信結果の把握は自動照合、Jira コメントと状態遷移は永続 L1
