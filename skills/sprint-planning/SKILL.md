---
name: sprint-planning
description: Jira キャッシュ（06 準拠）と過去の完了 SP の集計値から、スプリントプランニング用の候補一覧と容量の材料（S2）を 1 枚の下書きにする。「プランニングの材料」「次スプリントの候補」と言われたときに使う。L1（ローカル出力のみ）。Jira・Confluence・Slack への書き込み・送信はしない。
---

# プランニング材料（S2）

用語: **S2** = 秘書の仕事の番号（プランニング用の候補一覧と容量の材料）。**33** = 出力の型の設計書、**P1〜P6** = 33 §6 の出す前の点検項目（固定文言・禁止語なし・幅は最小〜最大のみ・担当者情報なし・不完全時の数字なし・本文 600 字）。**SP** = ストーリーポイント（見積もりの相対値）、**EM** = エンジニアリングマネージャー（利用者）。

設計: `docs/design/33-sprint-planning-material.md`（型 §5・固定文言 §3・検証 §6）/ 集計値の置き場: `docs/design/06-cache-schema.md` §4 / 品質基準: `docs/design/14-output-quality-checklist.md`

## 手順
1. EM に次スプリントの稼働日数（日数のみ。人別の休暇は聞かない）を 1 行で確認する。無ければ「未入力」で進める
2. `python3 scripts/sprint_planning.py <cache>.json --history <done-sp>.json --workdays <日数>` を実行する（`<cache>` = `data/jira-cache/<alias>/<YYYY-MM-DD>.json`、`<done-sp>` = `data/structured/sprint-done-sp/<alias>.json`。読み取り専用。集計値が無ければ `--history` を省く＝過去 0 件で件数のみ）
3. 出力が「固定文言 + 再取得が必要」の 2 行なら、それだけを EM に返して終える（数字を推測しない）
4. 出力の本文（「詳細」より上）を**一字一句そのまま**EM に返す。詳細は聞かれたら出す。書き換え・要約・数え直しをしない
5. 返す前に 33 §6（P1〜P6）で内部点検する（合否は出力に載せない）。1 つでも外れたら出さずにスクリプトを見直す
6. EM に 1 枚を返す。前置き・経緯説明は不要。入れるものを決めるのは EM とチーム

## してはいけないこと
- 「容量は目安であり約束ではない」の固定文言を省く・言い換える。幅の上端を強調する
- 何 SP・何件入れるかの提案、平均・中央値・予測・達成率、担当者別の容量や過去実績、稼働日数での補正
- 幅（過去の完了 SP）をチーム向けサマリ（S4）や上長向け資料に流用する
- Jira / Confluence / Slack への書き込み・送信・接続、実キャッシュ・実データのコミット
- 日次の朝の表（morning-plan）に S2 を入れる（プランニング前に EM が呼ぶときだけ出す）

## 試す
`python3 scripts/sprint_planning.py tests/fixtures/sprint-planning/jira-cache.planning.json --history tests/fixtures/sprint-planning/done-sp.three.json --workdays 9` の本文が `examples/expected-output.md`（全て架空）。過去 2 件（`done-sp.two.json`）は幅を出さず件数のみ（`expected-short-history.md`）。不完全キャッシュ（`jira-cache.incomplete.json`）は 2 行だけ（`expected-incomplete.md`）。
