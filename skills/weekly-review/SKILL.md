---
name: weekly-review
description: EM の金曜用「週次棚卸し」を 60 秒で読める 1 枚にする（今週の完了・追加・先送り、期限超過、返信待ちの滞留）。「週次棚卸し」「今週の振り返り」と言われたときに使う。L0（読み取り専用）。数と事実のみ。
---

# 週次棚卸し

設計: `docs/design/29-weekly-review.md` / 品質基準: `docs/design/14-output-quality-checklist.md`

## 手順
1. `python3 scripts/weekly_review.py` を実行する（既定で `data/tasks/tasks.json` を読む。読み取り専用）
2. 出力を 14 の A〜E で自己点検する（合否は内部判定のみ。出力に載せない）
3. EM に出力をそのまま返す。前置き・経緯説明は不要
4. EM の返答（done・defer・drop 等）は朝の計画と同じ手順で定型語に直し、実行前に見せてから `apply_reply.py` で反映する（`docs/design/24-reply-apply.md`）

## してはいけないこと
- `data/` への書き込み、Slack / Jira / Confluence への書き込み・送信、トークン使用
- 評価語・解釈・理由の推測（事実 = 件数・日付・日数だけ）。人別の集計・比較（`waiting_on` は匿名ハンドルのまま、件数も人別に出さない）

## 試す
`python3 scripts/weekly_review.py --tasks skills/weekly-review/examples/tasks.sample.json --today 2026-10-09`（期待出力は `examples/expected-output.md`。全て架空）
