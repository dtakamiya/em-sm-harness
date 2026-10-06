---
name: proactive-scan
description: EM が見落としそうな期限接近・ブロッカー・返信待ち・会議準備・放置を先回りで拾う（モック試作）。「先回りして」「見落としない?」と言われたとき、または朝の計画の先回り節として使う。L1（読むだけ・状態ファイル以外は書かない）。
---

# 先回り検知

設計: `docs/design/18-proactive-detection.md` / 品質基準: `docs/design/14-output-quality-checklist.md`

## 手順
1. 朝の計画に載せる: `python3 scripts/morning_plan.py --proactive`（先回り節が「詳細」の前に入る）。単独なら `python3 scripts/proactive_scan.py`
2. 週 1 回: `--digest`（低＝放置の要約）
3. EM が「既読」「あとで」と言ったら `--ack <key>` / `--snooze <key> <日付>`
4. 出力はそのまま EM に返す。足す前置き・原因の推測は不要

## 終了コード
0 = 通知なし / 10 = 通知あり / 2 = 入力破損（状態は変えない・`.bak` 復元を提案）

## 入力
- `data/tasks/tasks.json`、`data/jira-cache/`（最新日次）、`data/meetings/meetings.json`（EM が週頭に貼る。形は `examples/meetings.sample.json`）
- 無い入力は「入力なし」を 1 行出して他のルールは続行する

## してはいけないこと
- Slack / Jira / カレンダーへの接続・送信・更新（L1 の範囲外）
- 担当者の識別子を出す / 評価語を使う / ブロッカーと放置を原因と結ぶ（共起として並べる）

## 試す
`python3 scripts/proactive_scan.py --tasks skills/proactive-scan/examples/tasks.sample.json --jira-dir tests/fixtures/sample-week/jira-cache --meetings skills/proactive-scan/examples/meetings.sample.json --state /tmp/s.json --today 2026-10-08`（期待出力は `examples/expected-output.md`・全て架空）
