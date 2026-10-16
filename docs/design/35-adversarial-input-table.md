# 35. 敵対入力の共通テスト表（fail-closed の確認表）

**状態（2026-10-16）: 7種 × 前処理4本 + 終了コード。OK 22 マス、未対応 5 マス（後回し台帳 34 の D-016〜D-019 の4件）。EM の対応は不要。**

入力を読むスクリプトは、判定できないとき「止めて何も書かない」（fail-closed）。その規約は [27 §8](27-implementation-conventions.md)。
本書は、規約を破りやすい入力を7種に絞り、既存の前処理スクリプトが通るかをテストに対応づけた表（emh-085）。入力は全て架空。
観察: 別目（実装者とは別のレビュー担当）の指摘が同じ型の穴に集まった（#88・#89・#90・#91）。ただし往復数は入力の複雑さにも依り、共起のみで原因は未確認。

## 1. 表の読み方

用語: emh-085 = この作業の board 上の項目 ID／fail-open = 判定できないのに通してしまうこと（fail-closed の逆）／front matter = 貼り付け先頭の `---` で囲む見出し／sa = slack_anonymize／D-xxx = 後回し台帳 34 の行 ID。

| 記号 | 意味 |
|---|---|
| `OK <テスト名>` | 止まる（または安全に何も書かない）ことを `tests/test_adversarial_inputs.py` が確かめている |
| `NG D-xxx <テスト名>` | 未対応。あるべき挙動を `known_gap（AssertionError のときだけ期待どおりとするテスト用の印）` で固定し、後回し台帳 [34](34-deferred-review-findings.md) に載せた。直ると「想定外の成功」でテストが落ちるので、表と台帳を更新する |
| `—（理由）` | その入力が来ない、または別の段で止まる |

「止まる」の判定: 終了コードが 0 以外、かつ出力先に何も残らない。**§2 の OK は終了コードが 2 であることまでは保証しない**（2 の確認は §3 の E1 のみ）。取り込み済みスキップ（A7）は終了コード 0 でも何も書かなければ可。

## 2. 敵対入力 × 前処理4本

| 種別 | slack_preprocess | slack_anonymize | meeting_preprocess | calendar_paste_to_meetings |
|---|---|---|---|---|
| A1 空入力（空ファイル・空白のみ） | NG D-016 test_a1_slack_preprocess_empty | OK test_a1_slack_anonymize_empty | OK test_a1_meeting_preprocess_empty | OK test_a1_calendar_empty |
| A2 UTF-8 として読めないバイト列 | OK test_a2_slack_preprocess_invalid_utf8 | OK test_a2_slack_anonymize_invalid_utf8 | OK test_a2_meeting_preprocess_invalid_utf8 | OK test_a2_calendar_invalid_utf8 |
| A3 判定の材料（機微語・名簿・鍵）が無い／空 | OK test_a3_slack_preprocess_empty_words | OK test_a3_slack_anonymize_missing_key | OK test_a3_meeting_preprocess_missing_roster | —（機微語・名簿を使わない） |
| A4 行末コロンだけの話者行・名簿外の話者 | —（匿名化段で止める。sa の A4 テストが前処理の出力を通して確認） | OK test_a4_slack_anonymize_unmapped_speaker_after_preprocess | OK test_a4_meeting_preprocess_trailing_colon_speaker | —（話者を読まない） |
| A5 不正な見出し・メタ（不正日付・別名・front matter） | NG D-017 test_a5_slack_preprocess_invalid_meta | OK test_a5_slack_anonymize_person_name_in_meta | OK test_a5_meeting_preprocess_invalid_meta | OK test_a5_calendar_invalid_date_header_does_not_attach_to_previous_day |
| A6 出力先に同名ファイルが既にある | OK test_a6_slack_preprocess_existing_output | OK test_a6_slack_anonymize_existing_output | OK test_a6_meeting_preprocess_existing_output | OK test_a6_calendar_existing_output |
| A7 同じ内容の再投入・入力内の重複 | OK test_a7_slack_preprocess_repaste_writes_nothing_new | —（A6 と同じ経路。出力名が内容ハッシュ由来） | —（A6 と同じ経路。同名は拒否） | NG D-019 test_a7_calendar_duplicate_events_in_one_paste |

## 3. 停止時の終了コード（27 §8 の「2」）

| 種別 | slack_preprocess | slack_anonymize | meeting_preprocess | calendar_paste_to_meetings |
|---|---|---|---|---|
| E1 判定不能で止めたときのコードが 2 | NG D-018 test_exit_code_slack_preprocess | OK test_exit_code_slack_anonymize | OK test_exit_code_meeting_preprocess | NG D-018 test_exit_code_calendar_empty |

calendar は「空・読めない行あり」を 1（直して再実行）、「読めない・書けない」を 2 に分けている。slack_preprocess は全ての停止が 1。
どちらも既存の挙動なので今回は直さず、27 の §7（全面書き換えは非ゴール）に従い新規・修正時に寄せる。

## 4. 表を足す・直すとき

- 新しい「入力を読む script」を足したら、列を1つ足し、A1〜A7 のどれが当てはまるかを埋める。当てはまらない種別は理由つきで `—`
- 敵対入力の種別を足すのは、別目の指摘が同型で2回以上出たとき（種別は5〜8種の範囲に保つ。増やすなら統合を先に考える）
- `tests/test_adversarial_inputs.py` が、表のテスト名の実在・NG が `known_gap（AssertionError のときだけ期待どおりとするテスト用の印）` であること・後回し台帳に `open` の行があること・テストが表から漏れていないことを確かめる
- 限界: 表の1マスは代表的な1入力で確かめる。同じ種別の別形（例: 全角コロン）は別目レビューで補う

## 5. 非ゴール

- 未対応 4 件の修正（D-016〜D-019。台帳の「拾う条件」で拾う）
- 実データ・会社固有情報・実接続を使ったテスト
- 前処理4本以外の script への展開（必要になった時点で列を足す）
