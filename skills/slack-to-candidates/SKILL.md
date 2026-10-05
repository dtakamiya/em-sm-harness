---
name: slack-to-candidates
description: 匿名化・構造化済みの Slack 貼り付け（structured JSON）から、EM 宛ての依頼をタスク候補（candidates.json）に追加する。「Slack の依頼を候補に」と言われたときに使う。L1（ローカル出力のみ）。Slack への書き込み・送信はしない。
---

# Slack 構造化データ → タスク候補

設計: `docs/design/13-slack-paste-input.md` §9 / 抽出観点: `docs/design/23-slack-extraction-guide.md`

## 手順
1. 構造化 JSON（`data/structured/slack/<file>.json`、匿名化済みのみ）を用意する。作り方は 13 §4〜§6・23 に従う（実名・原文は書かない）
2. `python3 scripts/slack_to_candidates.py <file>.json --dry-run` で追加予定を見せる
3. EM が問題なければ `--dry-run` を外して実行する（`data/tasks/candidates.json` に追記。直前の内容は `candidates.json.pre-slack.bak` に退避。返答反映の `.bak` とは別名）
4. 結果の 1 行をそのまま EM に返す。候補の採用/却下は朝の計画（`morning-plan`）で聞く

## 取り込む条件（13 §9）
`kind=request` かつ `to_em=true` かつ `confidence` が high / medium。`low`・EM 宛てでない依頼・decision/risk/blocker/signal は入れない（signal は個人別に蓄積しない）。

## してはいけないこと
- `tasks.json` へ直接入れる（確定は EM）/ 候補に引用・原文を写す（`source_ref` はファイル名 + item id のみ）
- 期限の推測（`due_raw` が `YYYY-MM-DD` のときだけ `suggested_due` に入れる。それ以外は null）
- Slack / Jira / Confluence への書き込み・接続

## 重複・失敗時
同じ `source_ref` は候補・現役タスク・却下済みのいずれにあっても再追加しない。検証失敗・壊れた JSON は何も書かず理由だけ返す。

## 試す
`python3 scripts/slack_to_candidates.py skills/slack-to-candidates/examples/2026-10-07-ex-team-02.json --tasks-dir /tmp/x --dry-run`（全て架空）
