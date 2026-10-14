---
name: meeting-to-candidates
description: 匿名化・構造化済みの会議メモ（structured JSON）から、議事録の下書きと EM 本人のタスク候補（candidates.json）を作る。「会議メモを議事録とタスク候補に」と言われたときに使う。L1（ローカル出力のみ）。Confluence・Slack・Jira への書き込みはしない。
---

# 会議メモ → 議事録下書き + タスク候補

設計: `docs/design/28-meeting-notes-input.md` §6〜§7 / 下書きの型: `templates/drafts/meeting-minutes.md`

## 手順
前提（emh-077＝board 上の「会議メモの前処理・匿名化」項目の ID。`meeting_alias` は会議の別名で、実会議名・人名・プロジェクト名は入れない）: 生メモは gitignore 済みの `data/` 配下に置く（コミットしない）。環境変数 `EM_HARNESS_ANON_KEY`（16 文字以上）と名簿 `config/local.roster.json`・機微語ファイルが要る。出力先は `data/inbox/meeting/` 配下のみ。終了コード 2 = 中止（機微語・名簿外の人名・鍵/名簿不正・同名の出力が既にある）で、何も書かれていない。同名の出力があると上書きしないので再実行できない（別名にするか既存を EM が退避する）
1. 貼られた生メモは先に `python3 scripts/meeting_preprocess.py <メモ>.md` で匿名化する（`data/inbox/meeting/<held_on>-<alias>.md` に出る。人事系の語・名簿外の人名があれば何も書かず止まる）。抽出は匿名化済みのファイルだけを読む。匿名化後 → 構造化 JSON は現状手動（抽出器＝匿名化済みメモから決定・アクション・未決を自動で取り出すプログラム。未実装で、設計書 28 §9 の未決事項 2 番）
2. 構造化 JSON（`data/structured/meeting/<file>.json`、匿名化済みのみ）を用意する。形は 28 §3（実名・メモ原文は書かない）
3. `python3 scripts/meeting_to_candidates.py <file>.json --dry-run` で議事録下書きと追加予定の候補を見せる
4. EM が問題なければ `--dry-run` を外して実行する（下書きは `data/outputs/drafts/<元名>-minutes.md`、候補は `data/tasks/candidates.json` に追記。直前の候補は `candidates.json.pre-meeting.bak` に退避）
5. 結果の 1 行を EM に返す。候補の採用/却下は朝の計画（`morning-plan`）で聞く。議事録の掲載・共有は EM

## 候補にする条件（28 §7）
`action_item` かつ `owner` が `em` かつ `to_em=true` かつ `confidence` が high / medium。他メンバーのアクション・`low`・決定・未決は候補にしない（議事録下書きには全部載る）。

## 落とさない
決定・アクション・未決はすべて下書きに並ぶ。担当が読めない行は「要確認」付きで残し、抽出しなかった行は理由つきで「抽出しなかった行」に並ぶ。担当・期限は補完しない（空欄は ⟦EM が決める⟧ へ）。

## してはいけないこと
- `tasks.json` へ直接入れる（確定は EM）/ 候補にメモ原文を写す（`source_ref` はファイル名 + item id のみ）
- 期限の推測（`due_raw` が `YYYY-MM-DD` のときだけ `suggested_due` に入れる。それ以外は null）
- Confluence / Slack / Jira への書き込み・接続

## 重複・失敗時
同じ `source_ref` は候補・現役タスク・却下済みのいずれにあっても再追加しない。検証失敗・壊れた JSON は何も書かず理由だけ返す。

## 試す
`python3 scripts/meeting_to_candidates.py skills/meeting-to-candidates/examples/2026-10-07-ex-sync.json --tasks-dir /tmp/x --out-dir /tmp/xo --dry-run`（全て架空）
