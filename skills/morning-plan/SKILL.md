---
name: morning-plan
description: EM の朝の「今日の計画」を 60 秒で読める 1 枚にする（個人タスク + 催促候補 + 新規タスク候補）。「今日の計画」「朝の段取り」と言われたときに使う。L1（下書きまで）。送信・外部更新はしない。
---

# 朝の「今日の計画」

設計: `docs/design/15-morning-plan.md` / 品質基準: `docs/design/14-output-quality-checklist.md`

## 手順
1. `python3 scripts/morning_plan.py` を実行する（既定で `data/tasks/tasks.json` と `candidates.json` を読む。読み取り専用）
2. 出力を 14 の A〜E で自己点検する（合否は内部判定のみ。出力に載せない）
3. 催促候補があれば、下書き入力 JSON（形は `skills/draft-reply/examples/nudge.sample.json`）を組み、`python3 scripts/make_draft.py nudge <input>.json --dry-run` で見せてから `--dry-run` を外して保存する（`data/outputs/drafts/YYYY-MM-DD-nudge-NN.md`、未送信）。型は `templates/drafts/nudge.md`。送信は EM
4. EM に計画をそのまま返す。足す前置き・経緯説明は不要
5. EM の返答（採用/却下/後で・完了・先送り）は定型語に直し、実行前に見せてから `python3 scripts/apply_reply.py "<定型語1>" "<定型語2>"` で `data/tasks` に反映する（`--dry-run` で確認、`--undo` で直前を戻す。書式は `docs/design/24-reply-apply.md`）。結果の1行をそのまま EM に返す

## してはいけないこと
- Slack / Jira / Confluence への書き込み・送信、トークン使用（L1 の範囲外）
- 「送った」「更新した」と書く / EM 名義の新規コミット（期限・約束）を本文に埋める
- 人の属性づけ。`waiting_on` は匿名ハンドルのまま出す

## 入力が壊れていたら
スクリプトが停止して `.bak` 復元を提案する。勝手に上書きしない。

## 試す
`python3 scripts/morning_plan.py --tasks skills/morning-plan/examples/tasks.sample.json --candidates skills/morning-plan/examples/candidates.sample.json --today 2026-10-04`（期待出力は `examples/expected-output.md`。全て架空）
