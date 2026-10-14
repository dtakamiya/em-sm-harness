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

## 貼り付けから候補までの詳細（README「Slack を貼った後」の補足）
4 段階。①前処理・②匿名化は機械、③構造化 JSON は人手、④候補化。①②④は停止時に何も書かない。実装は `scripts/slack_preprocess.py` / `slack_anonymize.py` / `slack_to_candidates.py`。

用語
- **機微語**: 人事系の話題を示す語。`config/local.sensitive-words.txt`（1 行 1 語・`#` 始まりはコメント・gitignore 済み）に置く。貼り付けに 1 語でも含まれたら秘書は読まない
- **既出台帳**: 取り込み済みの貼り付け・メッセージのハッシュだけを持つ `data/inbox/slack/parsed/.seen.json`（本文なし）。重複除外の根拠
- **`allow_words`**: 名簿 `config/local.roster.json` の項目。人名と誤検知される普通の語（例: `Slack Bot`）を登録して匿名化の停止を避ける
- **`skipped`**: 前処理出力の項目。`sensitive`（機微語に当たった）か `duplicate_paste`（同一貼り付けが取り込み済み）

| 段 | コマンド | 停止（何も書かない） | 再実行 | 出力先 |
|---|---|---|---|---|
| ① 前処理 | `python3 scripts/slack_preprocess.py <貼り付け>.md [--words-file F] [--out-dir D] [--dry-run]` | 終了コード 1: 機微語ファイルが無い／空・読めない、貼り付けが読めない、出力先に同名、台帳が壊れている。機微語に当たる・同一内容が取り込み済みのときは「スキップ」表示で終了コード 0（出力も台帳も作らない） | 同じ貼り付けを再実行すると既出でスキップ。重なる再貼り付けは既出メッセージだけ除外 | `data/inbox/slack/parsed/<名前>-<ハッシュ先頭8桁>.json` と台帳 |
| ② 匿名化 | `python3 scripts/slack_anonymize.py <①の出力>.json [--roster F] [--anon-dir D] [--dry-run]`（環境変数 `EM_HARNESS_ANON_KEY` は 16 文字以上） | 終了コード 2: 鍵が未設定／短い、名簿が無い／不正、前処理でスキップ済み、名簿外の人名らしきものが残る（件数とメッセージ ID だけ表示）、同名の出力が既にある | 停止後は何も書かれていないので、名簿か `allow_words` を直して再実行可。出力ができた後の再実行は「同名」で中止 | `data/inbox/slack/anon/slack-anon-[日付-]<ハッシュ先頭8桁>.json`（0600） |
| ③ 構造化 | EM と秘書が手で作る（形は 13 §6・23。抽出スキル本体は未実装） | — | — | `data/structured/slack/<file>.json` |
| ④ 候補化 | `python3 scripts/slack_to_candidates.py <file>.json [--tasks-dir D] [--dry-run]` | 終了コード 1: `schema_version` 不一致・`skipped` 付き・必須項目欠け・JSON が壊れている（1 件でも不正なら何も書かない） | 同じ出典（ファイル名 + item id）は候補・現役タスク・却下済みのどれにあっても再追加しない | `data/tasks/candidates.json`（直前は `candidates.json.pre-slack.bak`） |

保持: `parsed/`（raw 相当）・`anon/`・`structured/slack/`・台帳はいずれも暫定 14 日（Q-016 で確定）。削除（パージ）は未実装で今は残る。

台帳が壊れたとき: ①は「既出台帳が壊れています。上書きはしません」で終了コード 1 になる。自動復旧は無い。EM が `parsed/.seen.json` を別の場所へ退避すると、次の①から空の台帳で再開する。ただし過去に取り込んだ貼り付けも新規として扱われるので、④の「同じ出典は再追加しない」に頼って重複を防ぐ。
