---
name: one-on-one-followup
description: EM の 1on1 前に「前回の約束がどうなったか」を 60 秒で読める 1 枚にする（未完了・返信待ち・完了・中止）。「1on1 の前回アクション」「前回の約束の確認」と言われたときに使う。L0（読み取り専用）。
---

# 1on1 前回アクションの追跡（O2）

設計: `docs/design/32-one-on-one-followup.md` / 品質基準: `docs/design/14-output-quality-checklist.md`
用語: **O2** = [12](docs/design/12-secretary-job-list.md) §3.3 の仕事番号（前回アクションの追跡）/ **14 の A〜E** = 出力品質チェックリストの観点（A=60秒で読める、B=事実と解釈の分離、C=因果と共起、D=レッテルなし、E=判断依頼の型）/ **L0** = 読み取り専用 / **EM** = Engineering Manager（使い手）
試作: 日次手順にはまだ含めない。EM が次の 1on1 前に 1 回使い、前回の約束が漏れなく出たかを見る。

## 手順
1. EM に次の 2 つを**毎回**聞く。保存せず、前回の実行や過去のセッションから推測しない（個人別の時系列を作らないため。Q-017）
   - 前回の 1on1 の日（`--since YYYY-MM-DD`）
   - 対象: 前回メモ名（`--ref`）か相手の匿名ハンドル（`--member`。例 `member-a`）。実名は聞かず、ハンドルに変換もしない。EM が匿名ハンドルで答えられないときは `--ref` だけ使う
2. `python3 scripts/one_on_one_followup.py --since <日> --ref <メモ名>`（`--member <ハンドル>` を足すと相手待ちの返信待ちも拾う。1on1 以外で同じ相手を待っている件も混ざるので、`source_ref` で見分ける）を実行する。既定で `data/tasks/tasks.json` と隣の `archive/` を読む。読み取り専用
3. 出力を 14 の A〜E で自己点検する（合否は内部判定のみ。出力に載せない）
4. EM に出力をそのまま返す。前置き・経緯説明は不要。未完了の扱い（今回の議題にする / 閉じる）の判断は EM。反映は `apply_reply.py`（`docs/design/24-reply-apply.md`）で、実行前に見せる。**反映できるのは「完了」「先送り」まで。中止（drop）は未対応**なので、閉じる場合の中止は EM が手で `tasks.json` を直す

## 受け入れ基準（EM の手間が実際に減るか）
- 基準: 前回の約束が漏れなく出る。照合元は前回メモ（`source_ref`）と EM の記憶。出なかったものは、タスク化されていなかったのか紐付けが違ったのかを分けて見る
- 日次手順に組む合否ライン: EM が次の 1on1 前に 1〜2 回使い、前回の約束の確認で記憶頼みの探し直しが要らなくなったら組む。漏れが多ければ紐付け規則（メモ名）を直してから再判定する（実運用では未検証）
- 出力が 60 秒で読める・評価語なしは `tests/test_one_on_one_followup.py` と `tests/test_one_on_one_followup_skill.py` が見本で検証

## してはいけないこと
- `data/` への書き込み、Slack / Jira / Confluence への書き込み・送信、トークン使用
- 前回日・対象・結果の保存、個人別の件数比較・時系列、未完了の理由の推測、評価語
- 「該当なし」を「全部完了」と言い換える（タスク化されていない口頭の約束は拾えない。出力の詳細にも書いてある）

## 試す
`python3 scripts/one_on_one_followup.py --tasks skills/one-on-one-followup/examples/tasks.sample.json --since 2026-09-26 --ref 1on1-member-a-2026-09-26.md --today 2026-10-10`（期待出力は `examples/expected-output.md`。全て架空）
