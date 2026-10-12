# 朝の「今日の計画」（試作の仕様）

状態: 試作（emh-007）。tasks と候補だけで動く。Confluence は入力未接続。Jira・会議は `--proactive` のときだけ読む（入力があれば反映、無ければ詳細に「入力なし」と出す）。サンプルは全て架空。

## 結論
- 着手順 1 位（[12](12-secretary-job-list.md) §4）を、実接続なしで動く形にした: `skills/morning-plan/SKILL.md` + `scripts/morning_plan.py`
- 対応する仕事は D1・D2・D3・D6 の一部。読み取り専用で、`data/` への書き込みも外部送信もしない（L0）
- 催促の文面は SKILL 手順 3 で `make_draft.py nudge` の下書きに回す（L1。型は `templates/drafts/nudge.md`）。送信は EM

## 入力と出力
| 入力 | 扱い |
|---|---|
| `data/tasks/tasks.json`（[04](04-personal-tasks.md) のスキーマ） | `snooze_until` が未来のものは除外 |
| `data/tasks/candidates.json` | 最大 5 件。`{id,title,source,source_ref,suggested_due}` |
| 出力 | 標準出力の Markdown 1 枚（結論 → EM がやること → 今日やる順 → 催促候補 → 判断依頼 → 候補 → 詳細） |

## ルール（確定案は [17](17-task-priority-and-waiting.md)）
- 並べ順: 期限超過 → 今日期限 → 3 日以内 → それ以外。同じ帯では priority（now/soon/later）→ 他を止めている数（`blocks`）→ 期限順
- 上位 5 件まで表示。超過分は件数だけ
- 結論: 🔴 期限超過あり / 🟡 催促候補か判断依頼あり / 🟢 それ以外
- 催促候補: `waiting` で `next_check` が今日以前
- 判断依頼: defer 履歴が 2 回以上（次が 3 回目）。選択肢は drop / 分割の 2 つ、おすすめ付き
- 期限超過の「日数」は `due` との差のみ。理由は推測しない（事実だけを出す）

## 受け入れ基準と結果
- 架空サンプルで出力が 900 字未満（テストで確認。仮置きの A2 基準 約 600 字は EM の FB で調整）
- 14 の A（60 秒）・E1（下書きは未送信と明記）を満たす。B〜D は、人の評価に当たる出力を持たないため該当なし
- `python3 -m unittest discover -s tests` で 11 件（順序・snooze・催促・defer・上限・非破壊・欠損ファイル）

## 未決・次の一手
- 会議準備（M1）: カレンダー入力の形が未定。EM に入力方法を確認（Q 起票候補）
- Jira / Confluence 反映: 構造化スキーマ（[06](06-cache-schema.md)）と指標（emh-004）の後
- 「今日の計画」の長さ・並べ順は、EM が実際に使った FB（[feedback-inbox](feedback-inbox.md)）で調整
