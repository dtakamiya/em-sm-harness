# em-sm-harness

多忙な EM（エンジニアリングマネージャー）に代わって、EM 業務とスクラムマスター業務を進める **秘書ハーネス**（Claude Code）。

秘書の仕事: 集める / EM の個人タスクを管理する / 先回りする / 下書きする / 判断材料を整える。
権限は委任ラダーで段階的に広げる（現在 L1 = 下書きまで。送信・更新は EM 本人）。詳細は [秘書モデル](docs/design/03-secretary-model.md)。

- **入力**: Jira・Confluence（Atlassian API トークン接続・読み取り中心）／ Slack の内容を手動で貼り付けたテキスト
- **入力（ほか）**: EM の個人タスク（`data/tasks/`）
- **出力**: 今日の計画・日次ブリーフ・スプリント健全性チェック・リスク/障害物台帳・各種下書き（Slack 返信・Jira コメント・議事録・レトロ・1on1・報告）

## ステータス

設計フェーズ。**Jira / Confluence への実接続は未実施**（接続方式を設計書で固めている段階）。
設計書は [docs/design/](docs/design/) を参照。

## 原則

- 実データ（Jira / Confluence 取得結果・Slack 貼り付け・個人名を含む出力）は `data/` に置く。`data/` は gitignore 済みでコミットしない
- API トークン等の秘密値はコード・設計書・コミットに含めない（環境変数名のみ記載）
- 外部ツール前提は Jira / Confluence + ローカル Markdown/JSON のみ
- 人に関する出力は「観察された事実」と「解釈の候補」を分ける

## セットアップ

```
python3 scripts/bootstrap.py   # data/ の置き場を作り、config/local.yaml を雛形から用意し、環境チェックまで実行（冪等・既存は上書きしない）
python3 scripts/check_env.py   # 環境チェックだけ（読み取り専用）。NG には「EM がやること」が1行付く。終了コード 0=OK / 1=NG
python3 scripts/check_no_leak.py  # コミット前の持ち出し検知（git add の後）
```

`config/local.yaml` に会社固有値を書く（gitignore 済み）。秘密値は書かない。

## 毎日の使い方

秘書（Claude Code）に話しかけるのが入口。下のコマンドは秘書が実行する（自分で打ってもよい）。所要時間は EM が使う目安。初回は先に `python3 scripts/bootstrap.py`。
以下は架空の1日。すべてローカル完結で、Slack / Jira / Confluence へは何も送らない（送信は EM 本人）。

| いつ | 秘書に言う | 実行されるコマンド | EM の時間 | 出力の置き場 |
|---|---|---|---|---|
| 週頭（週1回） | **貼るだけで足りる。変換スクリプトも使える。**<br>・手で貼る: 今週の会議一覧を `data/meetings/meetings.json` に貼る（形は `skills/proactive-scan/examples/meetings.sample.json`。各会議に `id`＝連番の識別子・`title`・`start`＝日付、準備タスクがあれば `prep_task_id`＝会議準備タスクの紐付け ID）<br>・変換する: カレンダー表示をテキストで保存し `python3 scripts/calendar_paste_to_meetings.py 貼ったファイル.txt --out data/meetings/meetings.json`（前週のファイルがあるときだけ、先に `[ -f data/meetings/meetings.json ] && mv data/meetings/meetings.json data/meetings/meetings.$(date +%F).json` で退避。上書きはされない）<br>・変換の注意: `prep_task_id` は空で出る（準備タスクとの紐付けは後で EM が決める）／`id` は貼り直すと変わる／見出しに年が無ければ `--year`（既定は今年）の年とみなす。12月→1月の週は1月側の見出しに年（2027-01-04）を付ける<br>・読めない行や会議0件のときは何も書かず行番号を報告する。直して再実行すればよい（この時点では何も書かれていないので mv は再度不要）<br>・会社の実データなのでコミットしない（`data/` は gitignore）。貼らない週は会議準備の検知だけ「入力なし」と1行出て、他の検知は動く | 貼ったあとは朝の計画（`python3 scripts/morning_plan.py --proactive`）で会議準備が出る | 約3分 | `data/meetings/meetings.json` |
| 朝 | 「今日の計画」 | `python3 scripts/morning_plan.py --proactive`（先回り検知つき） | 約2分 | 画面に1枚。催促の下書きは `data/outputs/drafts/`（`make_draft.py nudge`） |
| Slack を貼った後 | 生の貼り付けは gitignore 済みの `data/inbox/slack/` 配下に置く（コミットしない）。①前処理 `python3 scripts/slack_preprocess.py <貼り付け>.md`（メッセージ単位に分解・既出の除外。機微語ファイル `config/local.sensitive-words.txt`（1 行 1 語）が無い／空・読めない、出力先に同名がある、既出台帳が壊れているときは何も書かず終了コード 1 で中止。機微語に当たる貼り付けと取り込み済みの同一貼り付けは「スキップ」と表示して何も書かず終了コード 0。`--dry-run` で書き込みなしの確認ができ、書いた後に同じ貼り付けを再実行すると既出でスキップ）→ ②匿名化 `python3 scripts/slack_anonymize.py data/inbox/slack/parsed/<①の出力>.json`（環境変数 `EM_HARNESS_ANON_KEY`（16 文字以上）と名簿 `config/local.roster.json`（雛形 `config/templates/local.roster.json.example`）が要る。名簿外の人名らしきものが残る・鍵／名簿が不正・同名の出力が既にあるときは何も書かず終了コード 2 で中止。誤検知で止まったら名簿の `allow_words` に追加して再実行。何も書かれていないので再実行可、ただし出力ができた後の再実行は同名で中止。`--dry-run` あり）→ ③匿名化済み（`data/inbox/slack/anon/`）から構造化 JSON を EM と秘書が手で用意し `data/structured/slack/` に置く（抽出スキル本体は未実装で、設計書 13 §10 の未実装部分。形は 13 §6・23。手順は `slack-to-candidates` の SKILL.md）。そのうえで「Slack の依頼を候補に」 | ④`python3 scripts/slack_to_candidates.py <file>.json --dry-run` → 問題なければ `--dry-run` を外す（形式が不正・`skipped` 付き・JSON が壊れているときは何も書かず終了コード 1。同じ出典は再追加しない） | 約3分 | 途中: `data/inbox/slack/parsed/`・`data/inbox/slack/anon/`（gitignore 済み。保持は暫定 14 日でパージ未実装）。最終: `data/tasks/candidates.json` |
| 会議が終わった後 | 生メモは gitignore 済みの `data/` 配下に置く（コミットしない）。front matter（`meeting_alias` / `held_on`）付きで貼り、環境変数 `EM_HARNESS_ANON_KEY`（16 文字以上）を設定して `python3 scripts/meeting_preprocess.py <メモ>.md` で匿名化（名簿・機微語ファイルは Slack と共通。名簿外の人名が残る（行頭の「X:」は既知ラベル・名簿・allow_words 以外なら停止。文中の名前は検出できない。誤検知で止まったら `allow_words` に追加して再実行。何も書かれていないので再実行可）・機微語に当たる・同名の出力が既にある場合は何も書かず終了コード 2 で中止。同名があると再実行できない）。匿名化後の構造化 JSON は現状 EM と秘書が手で用意（抽出器＝匿名化済みメモから決定・アクション・未決を自動で取り出すプログラムは未実装で、設計書 28 §9 の未決事項 2 番。`meeting_alias` は会議の別名で実会議名・人名は入れない。emh-077＝board 上の「会議メモの前処理・匿名化」項目の ID。手順は `meeting-to-candidates` の SKILL.md）。そのうえで「会議メモを議事録と候補に」 | `python3 scripts/meeting_to_candidates.py <file>.json --dry-run` → 問題なければ `--dry-run` を外す | 約3分 | `data/outputs/drafts/`（議事録下書き・未送信）と `data/tasks/candidates.json` |
| 返信案が要る | 「返信案を作って」 | `python3 scripts/make_draft.py slack-reply <input>.json --dry-run` → 外して保存 | 約2分/件 | `data/outputs/drafts/`（未送信。送るのは EM） |
| 返答を反映 | 「採用 c-0001」「完了 t-0001」「分割 t-0003 案1 案2」など | `python3 scripts/apply_reply.py "採用 c-0001" "完了 t-0001"`（`--dry-run` で確認、`--undo` で直前を戻す） | 約1分 | `data/tasks/tasks.json` |
| 夕方 | 「夕方の締め」 | `python3 scripts/evening_wrapup.py` | 約1分 | 画面に1枚（読み取り専用。出す内容がない日は1行） |
| 金曜 | 「週次棚卸し」 | `python3 scripts/weekly_review.py`（先回りの放置要約は `python3 scripts/proactive_scan.py --digest`） | 約3分 | 画面に1枚（読み取り専用） |

- Jira 指標（`scripts/jira_metrics.py`、[22](docs/design/22-jira-metrics-catalog.md)）は**試作・架空サンプルのみ**: 更新なし日数とスプリント途中のスコープ変動を数える（SP＝ストーリーポイント＝見積もりの相対値、N＝対象の課題数。見積もり乖離・ブロッカー・担当偏りは未実装）。実接続のキャッシュにはまだ使わない
- 承認キュー（`scripts/approval_queue.py`、[21](docs/design/21-approval-queue.md)）は**試作・架空サンプルのみ**: 入力は `python3 scripts/save_action.py <input>.json --dry-run` で検証して `data/actions/` に保存し（`--dry-run` を外すと保存）、`python3 scripts/approval_queue.py --slot morning --dry-run`（夕は `--slot evening`）で朝・夕それぞれ1枚を出す（個別承認・一括承認とも最大5件ずつ、超過は次の枠へ繰越。`--dry-run` は監査ログ `data/audit/` を追記しない）。送信はしない。上の毎日の手順にはまだ含めない（試用開始時に EM が使うか決める）
- ステークホルダー報告（`skills/stakeholder-report`、[12](docs/design/12-secretary-job-list.md) R1/R2）は**試作・架空サンプルのみ**: 結論→リスク→要判断の下書きと、数字・日付の出典チェックリストを出す。上の毎日の手順にはまだ含めない（EM が実案件で試して手間が減るか判定する）
- 1on1 前回アクション追跡（`skills/one-on-one-followup`、[32](docs/design/32-one-on-one-followup.md)、O2）は**試作・架空サンプルのみ**: 前回の約束の未完了・返信待ち・完了・中止を tasks から1枚で出す（O2＝1on1 の前回アクション追跡）。前回の 1on1 日と対象は毎回 EM が渡す（保存しない）。上の毎日の手順にはまだ含めない（EM が次の 1on1 前に使って、前回の約束が漏れなく出たか判定する）
- 計画・締め・棚卸しは、返答を定型語にして `apply_reply.py` で反映する（書式は [24-reply-apply.md](docs/design/24-reply-apply.md)）
- 1on1 アジェンダ案（`skills/one-on-one-agenda`、O1＝1on1 のアジェンダ案）は**試作・架空サンプルのみ**: 前回の持ち越し（上の O2 の出力）と本人の発言から、未送信の下書きを作る（`make_draft.py one-on-one-agenda`）。観察 3 点・解釈 2 つまで。Jira 指標は入力にしない。上の毎日の手順にはまだ含めない（EM が次の 1on1 前に使い、60 秒で読めて前回の持ち越しが漏れなく出たと判定したら組む）
- 秘書の手順書は `skills/<名前>/SKILL.md`（`morning-plan` / `slack-to-candidates` / `meeting-to-candidates` / `draft-reply` / `evening-wrapup` / `weekly-review` / `proactive-scan` / `sprint-health` / `sprint-planning` / `stakeholder-report` / `one-on-one-followup` / `one-on-one-agenda`）
- 実データは `data/`（gitignore）に置く。サンプルで試すだけなら各 SKILL.md の「試す」を実行

## ディレクトリ

```
templates/drafts/  下書きテンプレ群（Slack 返信・1on1・スプリントサマリ・報告。[README](templates/drafts/README.md)）
docs/design/   設計書（別PC運用: [08-portability.md](docs/design/08-portability.md) / 会社 Mac での再構築: [10-rebuild-guide.md](docs/design/10-rebuild-guide.md)）
config/templates/  設定の雛形（架空値）。現地用は config/local.*（gitignore）
data/          実データ置き場（gitignore）
simulation/    架空の 1 週間の模擬運用ランナーと所見（[README](simulation/README.md)。出力 `simulation/out/` は gitignore）
```
