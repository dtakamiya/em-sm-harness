---
name: one-on-one-agenda
description: EM の 1on1 前に、前回の持ち越しと本人の発言から「アジェンダ案（未送信の下書き）」を作る。「1on1 のアジェンダ」「1on1 の準備」と言われたときに使う。L1（下書きまで）。送信はしない。
---

# 1on1 アジェンダ案（O1）

用語: **O1** = [12](../../docs/design/12-secretary-job-list.md) §3.3 の仕事番号（アジェンダ案）/ **14 の A〜E** = 出力品質チェックリスト / **L1** = 下書きまで（送信は EM）/ **EM** = Engineering Manager（使い手）
型: `templates/drafts/one-on-one-agenda.md` / 品質基準: `docs/design/14-output-quality-checklist.md` / 入力の制約: `docs/design/22-jira-metrics-catalog.md` §1

## 手順
1. 前回の持ち越しを出す: `one-on-one-followup` スキル（O2）を先に実行する（EM に前回の日と対象を毎回聞く。保存しない）。出力の「未完了」「返信待ち」「前回以降に完了」を持ち越し欄に写す。`status` は 完了 / 継続 / 未確認（中止は載せない）
2. 観察（事実）は 3 点まで。材料は **tasks と、EM が貼った本人の発言（日付つき）だけ**。Jira 指標・滞留日数・他の人との比較は入れない（個人の評価材料に化けるため）。出典はタスク ID か発言日付
3. 解釈の候補は **最大 2 つ**。「〜の可能性」の形で、確認する問いを 1 つ添える。観察が複数あるときは、同時期に並んでいるだけで関係は未確認（共起）であることを下書きが自動で添える。因果として書かない
4. 聞く問いは 3 つまで。「はい/いいえ」で終わらない形にする
5. 入力 JSON（匿名ハンドル。形は `skills/draft-reply/examples/one-on-one-agenda.sample.json`）を組み、`python3 scripts/make_draft.py one-on-one-agenda <input>.json --dry-run` で見せる。問題なければ `--dry-run` を外す（`data/outputs/drafts/` に保存。既存は上書きしない）
6. 14 の A〜E で自己点検し、保存先と本文を EM に返す。実名への差し替えと送信・共有は EM

## 落とす条件（何も書かない）
観察 4 件以上 / 解釈 3 件以上 / 問い 4 件以上 / 解釈が「〜の可能性」でない / 評価語・推測語・送信済み表現 / Jira 指標・比較の語 / 匿名ハンドル以外 / 本文中の型見出し（■ ⟦ ⟧ 出典: 等）/ URL・トークン。語彙検査は代表語のみなので、最終確認は EM の目視。

## してはいけないこと
- Slack / Jira / Confluence への書き込み・送信、トークン使用
- 評価・報酬・懲戒・機微な共有の結論・推奨（材料の有無だけを `⟦EM だけが扱う⟧` に書く）
- 個人別の時系列・ランキング・他メンバーや平均との比較、前回との差の「推移」づくり
- 感情・動機の断定（発言の近い言い換えにとどめる）

## 試す（模擬実行・全て架空）
`python3 scripts/make_draft.py one-on-one-agenda skills/draft-reply/examples/one-on-one-agenda.sample.json --dry-run`（期待出力は `skills/draft-reply/examples/expected-one-on-one-agenda.md`）
