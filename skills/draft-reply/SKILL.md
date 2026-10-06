---
name: draft-reply
description: Slack 返信案・Jira コメント案を、templates/drafts の型で「未送信の下書き」として作る。「返信案を作って」「Jira にコメントする案」と言われたときに使う。L1（下書きまで）。送信・投稿はしない。
---

# 下書き（Slack 返信案・Jira コメント案）

型: `templates/drafts/slack-reply.md` / `jira-comment.md` / 品質基準: `docs/design/14-output-quality-checklist.md`

## 手順
1. 場面を選ぶ: `slack-reply`（入力は 13（Slack 貼り付け入力。`docs/design/13-slack-paste-input.md`）の構造化 JSON の request / question / decision 項目）か `jira-comment`（入力は Jira キャッシュ + 先回り検知の放置チケット / ブロッカー）
2. 上記テンプレの「必須項目」「EM が直す手間を減らす工夫」に従い、下書き入力 JSON（匿名化済み）を組み立てる。形は `skills/draft-reply/examples/*.sample.json`
3. `python3 scripts/make_draft.py <scene> <input>.json --dry-run` で内容を見せる。問題なければ `--dry-run` を外す（`data/outputs/drafts/YYYY-MM-DD-<scene>-NN.md` に保存。既存は上書きしない）
4. 出力を 14（出力品質チェックリスト。`docs/design/14-output-quality-checklist.md`）の A〜E で自己点検し、保存先と下書き本文を EM に返す。EM が読んで送る（秘書は送らない）

## スクリプトが落とす条件（何も書かない）
`type` が型の外 / 案が 3 つ以上・空 / 本文 300 字超 / 送信済み表現・評価語・推測語 / 約束・催促の語（「〜までにお願い」等。⟦EM が決める⟧ に寄せる）/ URL・トークン / 匿名ハンドル以外（接頭辞 member/m/em/ex + 英数字 12 字以内のみ可）/ 出典系の改行・本文中の型見出し文字列（■ ⟦ 出典: 等）/ `em_decides` が 6 件以上/ Jira コメントで 1 案に問いが 2 つ以上 / `em_decides` が空。

## 検査の限界
語彙検査は代表語のみ。最終確認は 14 の目視。本文中の実名は検査できないので目視必須。

## してはいけないこと
- Slack / Jira への書き込み・送信、トークン使用
- 相手の意図の断定、評価語。人への評価に読める言い回し
- 1on1・報告・議事録・レトロの下書きは未対応（emh-008 の設計待ち）

## 試す
`python3 scripts/make_draft.py slack-reply skills/draft-reply/examples/slack-reply.sample.json --dry-run`（全て架空）
