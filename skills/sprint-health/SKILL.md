---
name: sprint-health
description: Jira キャッシュ（06 準拠）の指標を 31 のテンプレに流し込み、スプリント健全性（S1）を 1 枚の下書きにする。「スプリント健全性」「スプリントの状況」と言われたときに使う。L1（ローカル出力のみ）。Jira・Confluence・Slack への書き込み・送信はしない。
---

# スプリント健全性（S1）

設計: `docs/design/31-sprint-health-template.md`（型 §4・状態語 §2・解釈 §3・検証 §6）/ 指標: `docs/design/22-jira-metrics-catalog.md` / 品質基準: `docs/design/14-output-quality-checklist.md`

## 手順
1. `python3 scripts/jira_metrics.py <cache>.json` を実行する（`<cache>` = `data/jira-cache/<alias>/<YYYY-MM-DD>.json`。読み取り専用）
2. 出力が「再取得が必要」の 1 行なら、それだけを EM に返して終える（指標を推測しない・31 §2）
3. 31 §4 のテンプレに流し込む。
   - 観察: 出力の「観察」行を**一字一句そのまま**貼る（先頭の試作バナー行は除く。数え直し・言い換えをしない）
   - 状態語: 31 §2 の件数規則（更新なし・追加・除外のどれかが 1 件以上なら 🟡、全て 0 なら 🟢）。🔴 は使わない。N < 5 では更新なしを 0 件扱いにしない
   - 解釈の候補: 31 §3 の固定文言から最大 2 つ。両方出るときは「共起。関係は未確認」の一文を足す。除外だけの 🟡 は「解釈の候補: なし」
   - 限界: 本文は 1 行に縮め、出力の限界行を末尾「詳細」に全文で置く
4. 31 §6（H1〜H6）で内部点検する（合否は出力に載せない）。本文 600 字以内
5. EM に 1 枚を返す。前置き・経緯説明は不要。担当への確認・共有は EM（下書きまで）

## してはいけないこと
- Jira / Confluence / Slack への書き込み・送信・接続、実キャッシュ・実データのコミット
- 原因の断定（共起を原因と書かない）、評価語、担当者名・個人別の並び
- 解釈の候補の自由記述（固定文言のみ）。判断依頼を本文に混ぜる（スコープ・ゴール変更は選択肢 2 つ以内 + おすすめ + 期限で別欄）
- 1on1 の準備に jira_metrics の数字を使う（22 §1）

## 試す
`python3 scripts/jira_metrics.py tests/fixtures/jira-metrics/jira-cache.sample.json` の出力を流し込むと `examples/expected-output.md` になる（全て架空）。不完全キャッシュ（`jira-cache.incomplete.json`）は再取得メッセージ 1 行だけ（`examples/expected-incomplete.md`）。
