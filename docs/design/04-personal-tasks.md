# EM 個人タスク管理（操作仕様・スキーマ確定版）

状態: スキーマ・操作仕様を確定（emh-015）。優先順位づけと催促日数は [17](17-task-priority-and-waiting.md) で確定案（emh-016）。
データはすべて `data/tasks/`（gitignore）。実データ・実名は repo に入れない。

## ねらい
EM 自身がやるべきことを一箇所に集め、「今日やること」を秘書が段取りする。
Slack の依頼・Jira のアサイン・Confluence のアクションアイテムが散らばっても取りこぼさない。

## 委任ラダー上の位置づけ
- 個人タスクは EM 自身のデータ。**`data/tasks/` への書き込みは秘書が直接やってよい**（L1 の範囲内。外部ツールへの書き込みではないため）
- 他者・Jira / Confluence / Slack への波及（催促の送信、Jira ステータス更新など）は**下書きまで**。実行は EM
- 全操作を `data/audit/` に1行追記（誰が=`actor`・何を=`op`/`target_id`/対象ファイル・いつ=`ts`。タスク本文は入れず id・操作名・前後ハッシュのみ。形式は [05](05-approval-and-audit.md)・[24](24-reply-apply.md)）

## タスクの出所
Slack 貼り付けの「依頼」（EM 宛て）/ Jira の EM アサイン・レビュー待ち / Confluence 議事録のアクションアイテム（担当が EM）/ 手動追加 / 秘書が先回りで起こすもの（会議前準備・催促）。

## ファイル構成
```
data/tasks/
  tasks.json        # 現役タスク（open/doing/waiting）
  archive/YYYY-MM.json  # done/dropped を月次で移送（直近の参照用に30日は tasks.json に残す）
  candidates.json   # 取り込みで見つかった「タスク候補」。EM が確定するまでここ
  rejected.json     # 却下した候補の出典（記録のみ。再提案の抑止は取り込み実装時に参照する）
  *.bak / .last-reply.json  # 返答反映の直前状態と取り消し用の記録（24 参照）
```
更新は「一時ファイルに書いて rename」で原子的に行う（途中で壊れて全タスクを失わない）。更新前の `tasks.json` は `tasks.json.bak` に1世代残す。

## スキーマ（`tasks.json`）
```json
{ "version": 1,
  "tasks": [
    { "id": "t-0001", "title": "設計レビューの観点をまとめる",
      "status": "open", "priority": "soon", "due": "2026-10-09",
      "source": "manual", "source_ref": null,
      "waiting_on": null, "next_check": null,
      "blocks": [], "tags": [],
      "notes": "", "created": "2026-10-03", "updated": "2026-10-03",
      "history": [ {"at": "2026-10-03", "op": "add"} ] } ] }
```

| フィールド | 型・値 | 規則 |
|---|---|---|
| `id` | `t-NNNN` | 連番。**再利用しない**（done/dropped 後も欠番のまま） |
| `title` | 文字列 | 動詞で始まる1行（「〜をレビューする」）。80字目安 |
| `status` | `open`/`doing`/`waiting`/`done`/`dropped` | 遷移は下表 |
| `priority` | `now`/`soon`/`later` | 判定基準は emh-016。未設定は `soon` |
| `due` | `YYYY-MM-DD` / null | 外部期限。EM 自身の目標日は `notes` に書く（期限超過の誤検知を避ける） |
| `source` | `slack`/`jira`/`confluence`/`meeting`/`manual`/`secretary` | |
| `source_ref` | 文字列 / null | Jira キー・貼り付けファイル名・ページ ID など**参照のみ**。Slack 本文・Jira summary は写さない |
| `waiting_on` | 文字列 / null | **匿名化済みハンドル**（例 `member-a`）。実名は入れない。`waiting` のとき必須 |
| `next_check` | 日付 / null | `waiting` のとき必須。到来で催促下書きの対象 |
| `blocks` | `id` の配列 | このタスクが止めている他タスク（優先順位の入力） |
| `history` | 配列 | 操作ごとに `{at, op, from?, to?}`。削除しない |

不変条件（検証対象）: `waiting` なら `waiting_on` と `next_check` が必須 / `done`・`dropped` なら `next_check` は null / `blocks` の参照先が存在する / `id` 重複なし。

## 状態遷移
| 現在 → 次 | 操作 | 備考 |
|---|---|---|
| (新規) → open | add | 候補確定時も同じ |
| open/doing → doing | start | |
| open/doing → waiting | delegate / wait | `waiting_on`・`next_check` を必須入力 |
| waiting → open | resume | 返信が来た・期限が来た |
| open/doing/waiting → done | done | 履歴に完了日 |
| open/doing/waiting → dropped | drop | 理由を `history` に1行 |
| done/dropped → open | reopen | 誤操作の取り消し用。新規 id は作らない |

## 操作仕様
EM は自然言語で依頼 → 秘書が下記の操作に解釈して実行し、**変更後の1行を必ず返す**（誤解釈に EM が気付ける）。曖昧なら実行前に確認（選択肢2つ以内）。

| 操作 | 入力 | 動作 | 結果の返し方 |
|---|---|---|---|
| add | title（+due/priority/source_ref） | 新規 `open`。重複候補があれば先に提示 | `+ t-0012 …（期限 10/9・soon）` |
| done | id（完全一致）。title から探すときは秘書が候補を番号付きで提示し、EM が id を選ぶ | `done` | `✓ t-0007 完了` |
| defer | id, 新 due | `due` 変更。理由は任意。**3回目の defer** で「drop か分割か」を問う | `→ t-0003 期限 10/9→10/16（2回目）` |
| delegate | id, waiting_on, next_check | `waiting` へ。next_check 省略時は既定（仮: 3営業日後） | `⏳ t-0005 member-a 待ち（10/8 に確認）` |
| snooze | id, until | 今日の計画・棚卸しから一時的に外す（`snooze_until`）。status は変えない | `💤 t-0009 10/14 まで非表示` |
| drop | id, 理由 | `dropped` | `✗ t-0004 中止` |
| reopen | id | `open` に戻す | |

- `snooze_until` は任意フィールド（スキーマに追加可）。期日到来で自動的に表示対象へ戻る
- 一括操作（「今日のを全部 done」等）は件数と一覧を見せて確認してから実行

返答（採用/却下/後で・完了・先送り）を反映する定型語の書式と取り消しは [24](24-reply-apply.md)（emh-035）。

## 取り込みとタスク候補
1. 取り込み（Slack 構造化データの「依頼」・Jira の EM アサイン・Confluence アクション）から **候補**を `candidates.json` に作る。`tasks.json` へは直接入れない
2. 重複判定: `source` + `source_ref` が同一なら同一候補とみなし、新規にしない。参照が無いものは title の類似で「重複の疑い」と表示するだけ（自動マージしない）
3. 朝の計画で候補を最大5件まとめて提示 → EM が「採用/却下/後で」を返す。却下は `source_ref` を `rejected.json` に記録するのみ（再提案の抑止は未実装。[24](24-reply-apply.md)）
4. 外部の状態変化（Jira が Done になった等）は、該当タスクを「**完了候補**」として EM に提示するだけ。自動で `done` にしない

## 秘書の動き
- **朝の「今日の計画」**: 上位3〜5件 + 会議準備 + 催促候補 + 新規候補。60秒で読める量。並べ順は emh-016 の基準
- **waiting-for 追跡**: `next_check` 到来で催促の**下書き**を用意（送信は EM）。催促済みは `history` に記録し、`next_check` を再設定
- **夕の棚卸し**: 繰り越し・期限超過・長期放置（既定: 14日動きなし）を「まだ要る？」と確認。問いは1タスク1行・選択肢は keep/defer/drop
- **週次**: 完了数・繰り越し・waiting の滞留を要約（人の評価に見える書き方はしない。数と事実のみ）

## 起動方法（常駐しない）
EM がコマンド/スキルを叩いたときだけ動く。朝（今日の計画）・夕（棚卸し）・随時（add/done 等）。cron などの常駐起動は実接続 GO 後に別途検討。

## 壊れたとき・失敗時
- `tasks.json` が壊れていたら `.bak` から復元を提案し、**勝手に上書きしない**
- 不変条件に反する操作は拒否して理由を返す（例: waiting_on 無しの delegate）
- 実装時の最小テスト: 遷移表の全行・不変条件・重複判定・原子的書き込み（架空データ）

## 既存の仕組みとの関係
Ryoko の `knowledge/personal-tasks.md`（生活全般の個人 TODO）とは別。ここは**仕事上の EM/SM タスク**専用で、実データは `data/tasks/` に閉じる。

## 未決事項
- 優先順位・催促日数は [17](17-task-priority-and-waiting.md) に確定案（Q-019 / Q-020 は EM 回答待ち）
- 起動の自動化の要否（EM の使用感を見て判断）
