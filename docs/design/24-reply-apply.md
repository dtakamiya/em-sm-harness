# EM の返答を data/tasks に反映する（emh-035 / Q-028 回答 a）

状態: 実装済み（`scripts/apply_reply.py`、テスト `tests/test_apply_reply.py`）。ローカルのみ。Jira / Confluence / Slack へは書かない。

## 結論
- 返答の書式は**定型語 + id**（決定）。自由文は秘書が定型語に直して、実行前に EM へ見せる。曖昧なら実行しない
- 書込は委任ラダー L1 の範囲内（[04](04-personal-tasks.md) §委任ラダー上の位置づけ、policy の `task.update` = L0）。外部ツールへは何も出ない
- 更新前後は `data/audit/` に残し、直前の反映は `--undo` で戻せる

## 書式
| 返答 | 動作 | 結果の1行 |
|---|---|---|
| `採用 c-0001` | 候補 → 新規 `open` タスク（`t-` の新 id、期限は候補の `suggested_due`、priority は `soon`） | `+ t-0004 …（期限 10/12）` |
| `却下 c-0002` | 候補を消し、`source_ref` を `rejected.json` に記録（再提案しない） | `✗ c-0002 却下` |
| `後で c-0003 [日付]` | 候補を残し `snooze_until`（既定は翌日）まで朝の計画から外す | `💤 c-0003 10/6 まで非表示` |
| `完了 t-0001` | `done`。`next_check` は null | `✓ t-0001 完了` |
| `先送り t-0001 2026-10-16` | `due` 変更。3回目で drop か分割かを促す | `→ t-0001 期限 10/9→10/16（3回目）` |

- 1返答 = 1引数（引用符で囲む）。複数は1回の呼び出しにまとめる。**全件を検証してから書く**（1件でも不正なら何も書かない）
- id は完全一致のみ。タイトルの曖昧一致はしない（誤操作を避ける。曖昧一致は秘書が候補を提示して EM が id を選ぶ）
- 閉じたタスク（done/dropped）への操作、日付形式の誤りは拒否して理由を返す
- 実行は `python3 scripts/apply_reply.py "採用 c-0001" "完了 t-0002"`、確認だけなら `--dry-run`

## 監査と取り消し
- 監査: `data/audit/YYYY-MM-DD.jsonl` に操作ごと1行（`event=task_updated`、`op`、`target_id`、前後ファイルの sha256）。**タスク本文は入れない**（[05](05-approval-and-audit.md) §3）
- 戻す: 反映前の `tasks.json` / `candidates.json` / `rejected.json` を `.bak` に退避し、`.last-reply.json` に反映後のハッシュを持つ。`--undo` で全ファイルを戻し、`event=task_reverted` を記録
- 反映後に EM が手編集していたら `--undo` は拒否する（`--force` で上書き）。戻せるのは直前の1回のみ
- 書込は一時ファイル → rename で原子的。壊れた JSON は上書きせず `.bak` 復元を提案して止まる

## 範囲外（次の候補）
- `delegate`（waiting へ）・`snooze`・`drop`・`reopen` の返答（朝の計画が求めるのは上の5種のみのため見送り）
- 完了済みタスクの月次アーカイブ移送
