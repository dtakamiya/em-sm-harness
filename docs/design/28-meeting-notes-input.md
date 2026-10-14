# 会議メモ取り込み設計（貼り付けメモ → 決定・アクション・未決 → candidates）

**結論**: 貼り付けた会議メモから「決定・アクション（担当・期限）・未決」を取り出し、EM 本人のアクションだけをタスク候補にする設計。メモの全行を「抽出」か「除外（理由つき）」に振り分けて取りこぼしを防ぐ。検証は架空メモ 3 本の期待出力の形式・自己整合の確認まで（抽出器の実装は後続）。

状態: ドラフト（設計のみ・emh-037＝board 上の本件の項目 ID）。会議メモは EM が手で貼った文章だけを入力にする。Confluence・Slack・Jira へは接続も書き込みもしない（L1＝秘書は下書きまで・外部への書き込みや送信はしない権限段階。L2 は EM が種別ごとに明示した場合のみ）。サンプルはすべて架空（`member-a` 等）。会社固有情報は書かない。
位置づけ: [12](12-secretary-job-list.md) M2（議事録の下書き）・M3（アクションのタスク化案）の入口（M2 = 職務一覧の「議事録の下書き」、M3 = 「アクションのタスク化案」）。Slack 専用の [13](13-slack-paste-input.md) と同じ流れで、入力が「会話」ではなく「箇条書きのメモ」である点だけ違う。Confluence の議事録ページは [30](30-confluence-page-types.md)（emh-012）で扱う（抽出の形は本書の `items` / `excluded` を共用）。

## 1. 設計方針（13 / 23 から流用するもの）
- 匿名化・機微判定・重複除去・保持期間は 13 §5・§8 と同じ（名簿の HMAC ハンドル、人事系の語句はスキップ、14 日で削除）。メモは `data/inbox/meeting/` に置く
- 「取りこぼしを選ぶ」は**抽出の誤り**に対する原則。ただし M2 は「落とさない」が目的なので、**メモの全行を `items` か `excluded`（理由つき）のどちらかに必ず振り分ける**（§5）。黙って捨てる行を作らない
- 観察された事実だけを書く。担当・期限・理由を補わない。評価語・因果語を使わない（[14](14-output-quality-checklist.md)）

## 2. inbox 形式
置き場: `data/inbox/meeting/YYYY-MM-DD-<meeting_alias>.md`（`meeting_alias` はローカル設定上の別名。実会議名はファイル名に出さない）。

```
---
meeting_alias: ex-planning
held_on: 2026-10-05
---
## 決定
- EX-102 は次スプリントに回す（member-a 承認）
## アクション
- member-b: デモ環境の手順書を 2026-10-09 までに更新
```
- 見出し・箇条書きの有無は問わない。見出し行（`#` 始まり）は構造の手がかりであり、`items` の対象にしない
- 生メモから §2 の形への変換は `scripts/meeting_preprocess.py`（emh-077。機微語スキップ・名簿置換・名簿外の人名で停止は Slack 側 `slack_preprocess` / `slack_anonymize` の部品をそのまま使う。出力は 0600・上書きなし）
- 解釈できない行は捨てず `excluded` に理由つきで残す
- 1 ファイル = 1 会議。上限は 200 行を目安にし、超えるときは分割を促す

## 3. 構造化スキーマ
出力: `data/structured/meeting/<元ファイル名>.json`。`additionalProperties: false` で検証し、不一致なら何も書かない（13 §8）。

```json
{ "schema_version": 1,
  "source": { "file": "2026-10-05-ex-planning.md", "meeting_alias": "ex-planning",
              "held_on": "2026-10-05", "line_count": 7, "text_sha256": "…" },
  "extracted_at": "2026-10-05T18:00:00+09:00", "skipped": null,
  "items": [ { "id": "m-03", "kind": "action_item", "owner": "em", "to_em": true,
               "due_raw": "来週水曜まで",
               "observation": "em が見積もりの前提を m_a1a1a1 に共有する、とメモにある",
               "evidence": { "line": 5, "quote": "見積もりの前提を m_a1a1a1 に共有" },
               "confidence": "high" } ],
  "excluded": [],
  "notes": [] }
```

### 共通項目
| 項目 | 規則 |
|---|---|
| `kind` | `decision` / `action_item` / `open_question` |
| `observation` | 「〜とメモにある」の形で 1 文。評価語・因果語・補完なし |
| `evidence` | `line`（front matter を除く空でない行の 1 始まり番号。見出し行も数える）+ `quote`（匿名化済み原文の部分文字列・**40 字以内**） |
| `confidence` | `high`（明示）/ `medium`（読めるが一部が暗黙）/ `low`（担当や対象を読めない） |

### 種別ごとの項目
| kind | 追加項目 | 抽出する（目印） | 抽出しない（`excluded` へ） |
|---|---|---|---|
| `decision` | `decided_by[]`, `jira_keys[]` | 「決定」見出し配下、「決まった」「〜に回す」等の確定表現。承認者が読めれば `decided_by`、読めなければ空 + `medium` | 「〜しようか」等の提案。疑問形 |
| `action_item` | `owner`, `to_em`, `due_raw` | 「担当: 内容」「〜が〜する」。`owner` は匿名化ハンドル。`due_raw` は原文のまま | 「〜かも」「〜しておくといいね」など確約でない発言 |
| `open_question` | `asked_of[]`, `needs_em` | 「未定」「確認が必要」「確認中」。確認先が読めれば `asked_of` | 次回日程・雑談（`excluded`） |

### 判定の境界
- **担当が読めない**アクション（「誰かが〜する」）: `owner: null`・`to_em: false`・`confidence: low` で**残す**。落とさないための扱いで、タスク候補には流さない
- **複数担当**が 1 行にある（「member-c が出す。em がレビュー」）: 担当ごとに別 item。それぞれ別の `quote` を付ける
- **EM 以外のアクション**（`to_em: false`）も残す。先回り検知（[18](18-proactive-detection.md)）の入力と、M2 の議事録下書きに必要なため
- 決定に「承認を確認中」が続く場合: `decision`（`decided_by` 空・`medium`）と `open_question` を別々に出す。承認済みと断定しない
- `needs_em: true` にするのは、メモ上で EM への確認・判断が明示されているときだけ

## 4. 感情の兆候・個人評価
メモからは `signal` を抽出しない（会議メモは公式記録に近く、発言の背景が欠けるため誤読しやすい）。人事・評価・報酬を含む行はファイルごとスキップ（13 §8）。

## 5. 落ちゼロの定義（受入基準）
- 決定・担当・期限・未決が**明示された**行は `items` に出る。確約でない行・日程だけの行は `excluded` に理由がある
- **見出し以外の全行が `items` か `excluded` のどちらか**に必ず入る（テストで検証）
- 「〜かも」「〜しておくといいね」のような確約でない発言は `items` に出さず、`excluded` に理由つきで残す（§3）。「落とさない」は黙って消さないことで、確約でない発言を item にすることではない
- 期限は原文のまま `due_raw`。日付への変換は §7 の candidates 作成時（曖昧なら null）

## 6. 出力の種類（誰に何を見せるか）
- M2 議事録下書き: `items` を「決定 → アクション（担当別）→ 未決」の順に並べた 1 枚。下書きとして `data/outputs/drafts/` に保存し、Confluence へは書かない（書込は L2・[11](11-l2-candidates.md)）。実装: `scripts/meeting_to_candidates.py`（emh-050。構造化 JSON → 下書き + candidates。抽出自体は秘書が行う。既存の下書きは .bak に退避してから上書き。監査ログは §7 末尾・emh-055 で実装済み）
- M3 タスク化: §7

## 7. candidates への流し方（`candidates.json` 形式）
条件: `kind: action_item` かつ `owner: "em"`（`to_em: true`）かつ `confidence` が high / medium。

| candidates の項目 | 値 |
|---|---|
| `title` | `observation` から作る（80 字目安・13 §9 と同じ） |
| `source` | `meeting`（[04](04-personal-tasks.md) の `source` に追加） |
| `source_ref` | `<ファイル名>:<item id>` のみ。メモ本文は写さない |
| `suggested_due` | `due_raw` が `YYYY-MM-DD` のときだけ。「来週水曜まで」等は null |

- EM 以外のアクション・`low`・`decision`・`open_question` は流さない（EM が確定するのは自分のタスクだけ）
- 書き込みは 13 §9 と同じ（アトミック書込・更新前の退避・型不正は理由つき拒否・既出 `source_ref` の再提案なし）。実装は `scripts/meeting_to_candidates.py`（`slack_to_candidates.py` の検証・書込処理を流用。退避ファイルは `candidates.json.pre-meeting.bak`。`--audit-dir` で監査先を指定）
- 監査: `data/audit/` に `{event:"meeting_ingest", file, items:{decision:n,…}, excluded:n, skipped}` を 1 行（本文・引用は入れない）。取り込み成功時のみ（`--dry-run` では書かない）。承認キューの proposed 上限には数えない。`file` は basename のみ記録する。`skipped` は現状常に null（skipped 付きの入力は取り込み前に止めるため）。重複のみで候補が増えない取り込みも記録する。監査行だけ書けなかった場合は stderr に「取り込み済み・監査のみ失敗」と出して非 0（2）で終了する

## 8. 検証
**テストの範囲**: `expected.json` の形式・自己整合（引用が原文にある・全行の振り分け・候補の条件）の検証のみ。メモから自動で抽出する処理（抽出器）は未実装で、後続で追加する。

架空メモ 3 本（`tests/fixtures/meeting-notes/`）と期待出力（`expected.json`）。`python3 -m unittest tests.test_meeting_extraction` で次を確認:
- 全 item に 40 字以内の `quote` があり、匿名化済みの該当行に含まれる
- 人物欄はハンドルのみ。メモ・出力に実名がない
- 全行が `items` か `excluded` に入る（落ちゼロ）
- candidates は EM 本人のアクションだけ（他メンバー・`low` は入らない）。`medium` の EM 本人アクションは入る（§7 の条件）
- `needs_em: true` は、行に EM が明示されているときだけ

## 9. 未決事項
| # | 内容 | 担当 | 期限 |
|---|---|---|---|
| 1 | 実際のメモ形式が §2 の想定と違う場合に、EM が匿名化した数行の見本を示す（open-questions の Q-013＝取得出力の形式差を匿名化して一言で返す項目、と同じ要領。それまでは緩い解釈で吸収） | EM | 2026-10-13（試作の着手前） |
| 2 | candidates 連携スクリプト（`slack_to_candidates` の検証・書込の共通化）と抽出器の試作 | em-builder（実装担当） | 2026-10-20 |
| 3 | 抽出の自動評価（23 §8 の会議メモ版） | em-sm-analyst（要件・検証担当） | 2026-10-20 |

用語: HMAC ハンドル＝人名をローカル鍵つきハッシュで `m_xxxxxx` に置き換えた匿名名（13 §5。状態を持たないので対応表が壊れない）。
