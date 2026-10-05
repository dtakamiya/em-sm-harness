# Slack 貼り付け取り込み設計（inbox 形式・匿名化・構造化スキーマ）

状態: ドラフト（設計のみ・emh-005）。Slack への接続・書き込みはしない。EM が手でコピーして貼った文章だけを入力にする。
サンプルはすべて架空（`#ex-team` / `member-a`）。会社固有情報は書かない。

## 1. ねらい
EM の時間を最も食う「返信・依頼対応」（[12](12-secretary-job-list.md) T1）の入口。貼り付けた会話から **決定 / 依頼 / リスク / 障害物 / 感情の兆候** を取り出し、EM 宛ての依頼は個人タスクの**候補**（[04](04-personal-tasks.md)）にする。返信案（T3）は別設計で、本書の構造化データを入力に使う。

## 2. 委任ラダー上の位置づけ
- L1。`data/` 配下への書き込みのみ。Slack へは何も送らない・取得もしない
- 「依頼」は `candidates.json` までしか入れない（`tasks.json` への確定は EM。04 §取り込み）
- 取り込みの実行は監査ログに件数だけ残す（§9）

## 3. 全体の流れ
```
EM が Slack から手でコピー → data/inbox/slack/ に保存（raw）
  ① 前処理: 正規化・重複除去・機微判定
  ② 匿名化: 人名 → ハンドル（ローカルのみ・§5）
  ③ 構造化: 匿名化済みテキストから抽出（§6）→ data/structured/slack/
  ④ 突合: 依頼 → candidates.json、Jira キー → キャッシュと照合（analyst の仕事）
```
①②はスクリプト（決定的）。③は Claude が匿名化済みテキストのみを読んで行う。④は 04 / 02 §6 の規則に従う。

## 4. inbox 形式（EM が貼る側の約束）
置き場: `data/inbox/slack/YYYY-MM-DD-<channel_alias>-NN.md`（`channel_alias` はローカル設定上の別名。実チャンネル名はファイル名に出さない）。

先頭に任意の見出し行（無くてもよい。無ければ ① が補えない項目は `null`）:
```
---
channel_alias: ex-team
thread: true          # スレッドの貼り付けなら true
pasted_on: 2026-10-05 # 省略時はファイルの日付
---
Alice Example  10:32
明日のデモ、環境は誰が用意しますか？
Bob Sample  10:40
@EM さんに確認待ちです。金曜までに決めたいです
```
- 貼り付けは Slack のコピー結果のまま（整形不要）。「発言者 + 時刻」行 + 本文行の繰り返しとして**緩く**解釈する
- 解釈できない行は捨てず `raw_block` として残し、`notes` に「未解釈 N 行」と書く（誤抽出より取りこぼしを選ぶ）
- 絵文字リアクション・添付・画像は入力に含めなくてよい。含まれていても `[未解釈]` 扱い（読み取らない）
- 1ファイル = 1チャンネル・1まとまり（スレッド or 時間帯）。上限は 300 メッセージ程度を目安にし、超える場合は分割を促す

## 5. 匿名化
- **目的**: Claude に渡す前の多層防御（Claude 処理自体は可。Q-012）。raw はローカルに残り、匿名化済みだけを読ませる
- **方式**: 発言者名・メンション・本文中の人名を、ローカル名簿（`config/local.*` の `roster`）で `m_` + HMAC-SHA256(ローカル鍵, 正規化した名前) の先頭 6 桁に置換。**状態を持たない**ので対応表の破損が起きない（[06 §2](06-cache-schema.md) の `assignee_ref` と同じ考え方）。鍵は環境変数名のみ設計書に記載
- EM 本人は固定ハンドル `em`。`@EM` / 名前呼びはすべて `em` に寄せる
- 逆引き（ハンドル → 実名）は**ローカルのスクリプトが出力を整形する最後の段階でのみ**行う。構造化データには実名を戻さない
- 名簿に無い人名は置換できない。漏れの検出として「大文字始まりの連続語・敬称付き語」を `unmasked_suspects[]` に数だけ記録し、EM に名簿追加を促す（内容は出さない）
- 社外の組織名・顧客名・URL は `[URL]` / `[org]` に置換。Jira キー形式はそのまま残す（突合に使う）
- 匿名化済みは `data/inbox/slack/anon/` に書く。保持は raw と同じ（§8）

## 6. 構造化スキーマ
出力: `data/structured/slack/<元ファイル名>.json`。保存前に JSON Schema（`additionalProperties: false`）で検証し、不一致なら書かない。

```json
{ "schema_version": 1,
  "source": { "file": "2026-10-05-ex-team-01.md", "channel_alias": "ex-team",
              "thread": true, "message_count": 12, "text_sha256": "…" },
  "extracted_at": "2026-10-05T09:00:00+09:00",
  "skipped": null,
  "items": [
    { "id": "s-01", "kind": "request", "to_em": true,
      "actors": { "from": "m_a1b2c3", "to": ["em"] },
      "observation": "金曜までに環境の担当を決めたい、と em に確認を求めている",
      "evidence": { "msg_index": 3, "quote": "金曜までに決めたいです" },
      "due_raw": "金曜まで", "answered_in_thread": false,
      "confidence": "high", "interpretation_candidates": [] } ],
  "jira_keys": [], "unmasked_suspects": 0, "notes": [] }
```

### 共通フィールド
| フィールド | 規則 |
|---|---|
| `kind` | `decision` / `request` / `risk` / `blocker` / `signal`（感情の兆候） |
| `observation` | **観察された事実**を 1 文で。評価語・推測を入れない |
| `evidence` | `msg_index`（貼り付け内の通し番号）+ `quote`（原文の一部。**40 字以内**）。引用できない抽出は出さない |
| `actors` | ハンドルのみ。実名・表示名は入れない |
| `confidence` | `high`（明示的な表現）/ `medium` / `low`（文脈からの推定）。`low` は `candidates.json` に自動で流さない |
| `interpretation_candidates[]` | 解釈の候補。`signal` は**ちょうど 2 つ**、`risk` は 0〜2 つ、他の種別は空。事実欄とは別に置く |

### 種別ごとの追加項目と抽出ルール
| kind | 追加項目 | ルール |
|---|---|---|
| `decision` | `decided_by[]`、`scope_raw` | 「決まった」と読める**明示**表現のみ。提案・雑談は `decision` にしない。承認者が読み取れないときは空 |
| `request` | `to_em`(bool)、`due_raw`、`answered_in_thread` | 日付が解釈できても `due_raw` は原文のまま。**日付化は candidates 作成時に行い、曖昧なら null**。EM 宛てでない依頼は `to_em: false` で記録（先回り検知用） |
| `risk` | `likelihood_hint` を持たない | 将来への懸念の**発言そのもの**を記録。発言者の見立てと事実を混ぜない。「リスクがある」と秘書が断定しない |
| `blocker` | `blocked_what_raw`、`jira_keys[]` | 「待ち・止まっている」と本人が述べているものに限る |
| `signal` | `signal_type`（`fatigue`/`frustration`/`confusion`/`positive`/`other`）、`interpretation_candidates` 2 つ必須 | §7 の規則に従う |

### 共通禁止事項
- 原文にないことを補わない（担当・期限・理由の推測を書かない。空欄 + `notes`）
- 因果と共起を区別する。「A の後に B が起きた」を「A が原因」と書かない
- 人の能力・性格・意欲の評価を書かない

## 7. 感情の兆候（`signal`）の扱い
最も誤読しやすいので、他より厳しくする。
- **観察は発言上の表現**（例: 「また夜中までかかりました」）だけを書く。「疲れている人」とは書かない（レッテル貼り禁止）
- `interpretation_candidates` に**複数の解釈**を並べる（例: 「直近の負荷が高い可能性」「たまたま今回だけの作業」）。確かめ方（1on1 で聞く等）を 1 つ添えてよい
- **個人別の時系列を作らない**。`signal` を人ごとに集計・蓄積・比較する処理は実装しない。`structured/` に残る `signal` は 14 日で削除（本文由来の引用を含むため。06 §4 の「本文を含む派生物は 14 日」を適用）
- 出力に出すときは「観察 → 解釈の候補 → 確かめ方」の順。1on1 の機微な共有・人事評価に使う経路は作らない（EM 本人のみ）
- 既定は抽出する。EM がオフにできる（`extract_signals: false`）。Q-017 は回答済み: a（既定で抽出・個人別集計なし）2026-10-04

## 8. 保持と機微の扱い
| 対象 | 保持 | 備考 |
|---|---|---|
| raw（`inbox/slack/`）と匿名化済み（`anon/`） | 14 日（案。Q-016） | 起動時の遅延パージ（06 §4 と同じ方式）。期限切れは読まない |
| `structured/slack/` | 14 日（`quote`・`signal` を含むため） | 90 日の集計値は引用を含まない件数のみ（例: 週あたりの依頼件数） |
- **機微判定**: ローカル設定の語句リスト（人事評価・査定・報酬・退職・採用・懲戒など。具体語は `config/local.*`）に当たるファイルは `skipped: "sensitive"` とし、**抽出も匿名化済みの生成もしない**。EM に「人事系の可能性があるので秘書は読みません」とだけ返す
- 重複: `text_sha256` が同じ貼り付けは取り込まない。重なる範囲の再貼り付けは、メッセージ単位（発言者 + 時刻 + 本文のハッシュ）で既出を除外し、新規分だけ抽出
- 失敗時は部分出力しない（スキーマ検証失敗＝何も書かず、件数と理由だけ報告）

## 9. 下流との接続
- **個人タスク**: `kind: request` かつ `to_em: true` かつ `confidence ≥ medium` → `candidates.json`（アトミックに書き、更新前は `candidates.json.pre-slack.bak` に退避。24 の `--undo` が使う `.bak` とは別名で互いに上書きしない。型不正の入力は理由つきで拒否し何も書かない）。`source: slack`、`source_ref` はファイル名 + `item id` のみ（本文は写さない）。`due` は `due_raw` が確定日として読める場合のみ、それ以外は null
- **先回り検知**（[12](12-secretary-job-list.md) §4 ③ 返信待ち・放置）: `to_em: false` かつ `answered_in_thread: false` の依頼は「放置候補」の入力
- **返信案**: 匿名化済みの構造化データ + 必要なら原文の該当メッセージのみを入力に、ローカルで実名へ戻して下書きを作る。送信は EM（L1）
- **送信結果の照合**（[05](05-approval-and-audit.md)）: 次回の貼り付けで、下書きと一致する発言があれば「送信済みの可能性」と推定する
- **監査**: `data/audit/` に `{event:"slack_ingest", file, items:{decision:n,…}, skipped, unmasked_suspects}` を 1 行追記。本文・引用は入れない

## 10. 実装段階
1. 前処理・匿名化スクリプト（ローカル決定的）+ 架空サンプル（`tests/fixtures/slack/`）で単体テスト: 緩い形式の解釈 / 名簿外の人名 / 機微語 / 重複再貼り付け / 40字超の引用
2. JSON Schema と検証（不一致で書かない）
3. 抽出スキル（匿名化済みのみ読む）を架空サンプルで磨く。評価観点は emh-006（抽出観点の定義）
4. candidates 連携（04）: 実装済み `scripts/slack_to_candidates.py` / スキル `skills/slack-to-candidates`（emh-032）。前処理・匿名化・抽出スキル本体（1〜3）は未実装で、構造化 JSON は §6 の形で用意されている前提

## 11. 未決事項
- Slack 貼り付けの保持期間（Q-016）
- `signal` 抽出の既定（Q-017）は回答済み: a（既定で抽出・個人別集計なし）2026-10-04
- 実際のコピー形式が §4 の想定と違う場合は、EM が匿名化した数行の見本を示す（Q-013 と同様の差分確認）。それまでは緩い解釈で吸収
- 抽出観点の詳細と架空サンプルでの抽出例は [23](23-slack-extraction-guide.md)（emh-006）
