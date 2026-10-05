---
name: evening-wrapup
description: EM の夕方の「締めレポート」を 60 秒で読める 1 枚にする（今日の完了・持ち越し・新たな返信待ち・明日の計画の種）。「夕方の締め」「今日の振り返り」と言われたときに使う。L0（読み取り専用）。
---

# 夕方の締めレポート

設計: `docs/design/25-evening-wrapup.md` / 品質基準: `docs/design/14-output-quality-checklist.md`

## 手順
1. `python3 scripts/evening_wrapup.py` を実行する（既定で `data/tasks/tasks.json` を読む。読み取り専用）
2. 出力を 14 の A〜E で自己点検する（合否は内部判定のみ。出力に載せない）
3. EM に出力をそのまま返す。前置き・経緯説明は不要
4. EM の返答（done・defer・drop 等）は朝の計画と同じ手順で定型語に直し、実行前に見せてから `apply_reply.py` で反映する（`docs/design/24-reply-apply.md`）

## してはいけないこと
- `data/` への書き込み、Slack / Jira / Confluence への書き込み・送信、トークン使用
- 持ち越しの理由を推測して書く（事実 = 期限と日数だけ）。人の属性づけ（`waiting_on` は匿名ハンドルのまま）

## 試す
`python3 scripts/evening_wrapup.py --tasks skills/evening-wrapup/examples/tasks.sample.json --today 2026-10-05`（期待出力は `examples/expected-output.md`。全て架空）
