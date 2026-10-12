---
name: one-on-one-followup
description: EM の 1on1 前に「前回の約束がどうなったか」を 60 秒で読める 1 枚にする（未完了・返信待ち・完了・中止）。「1on1 の前回アクション」「前回の約束の確認」と言われたときに使う。L0（読み取り専用）。
---

# 1on1 前回アクションの追跡（O2）

設計: `docs/design/32-one-on-one-followup.md` / 品質基準: `docs/design/14-output-quality-checklist.md`
試作: 日次手順にはまだ含めない。EM が次の 1on1 前に 1 回使い、前回の約束が漏れなく出たかを見る。

## 手順
1. EM に次の 2 つを**毎回**聞く。保存せず、前回の実行や過去のセッションから推測しない（個人別の時系列を作らないため。Q-017）
   - 前回の 1on1 の日（`--since YYYY-MM-DD`）
   - 対象: 前回メモ名（`--ref`）か相手の匿名ハンドル（`--member`。例 `member-a`）。実名は聞かず、ハンドルに変換もしない。EM が匿名ハンドルで答えられないときは `--ref` だけ使う
2. `python3 scripts/one_on_one_followup.py --since <日> --ref <メモ名>`（`--member <ハンドル>` を足すと相手待ちの返信待ちも拾う）を実行する。既定で `data/tasks/tasks.json` と隣の `archive/` を読む。読み取り専用
3. 出力を 14 の A〜E で自己点検する（合否は内部判定のみ。出力に載せない）
4. EM に出力をそのまま返す。前置き・経緯説明は不要。未完了の扱い（今回の議題にする / 閉じる）の判断は EM。反映は `apply_reply.py`（`docs/design/24-reply-apply.md`）で、実行前に見せる

## してはいけないこと
- `data/` への書き込み、Slack / Jira / Confluence への書き込み・送信、トークン使用
- 前回日・対象・結果の保存、個人別の件数比較・時系列、未完了の理由の推測、評価語
- 「該当なし」を「全部完了」と言い換える（タスク化されていない口頭の約束は拾えない。出力の詳細にも書いてある）

## 試す
`python3 scripts/one_on_one_followup.py --tasks skills/one-on-one-followup/examples/tasks.sample.json --since 2026-09-26 --ref 1on1-member-a-2026-09-26.md --today 2026-10-10`（期待出力は `examples/expected-output.md`。全て架空）
