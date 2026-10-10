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
| 朝 | 「今日の計画」 | `python3 scripts/morning_plan.py --proactive`（先回り検知つき） | 約2分 | 画面に1枚。催促の下書きは `data/outputs/` |
| Slack を貼った後 | 先に匿名化済みの構造化 JSON を用意（手順は `slack-to-candidates` の SKILL.md）。そのうえで「Slack の依頼を候補に」 | `python3 scripts/slack_to_candidates.py <file>.json --dry-run` → 問題なければ `--dry-run` を外す | 約3分 | `data/tasks/candidates.json` |
| 会議が終わった後 | 先に匿名化済みの構造化 JSON を用意（手順は `meeting-to-candidates` の SKILL.md）。そのうえで「会議メモを議事録と候補に」 | `python3 scripts/meeting_to_candidates.py <file>.json --dry-run` → 問題なければ `--dry-run` を外す | 約3分 | `data/outputs/drafts/`（議事録下書き・未送信）と `data/tasks/candidates.json` |
| 返信案が要る | 「返信案を作って」 | `python3 scripts/make_draft.py slack-reply <input>.json --dry-run` → 外して保存 | 約2分/件 | `data/outputs/drafts/`（未送信。送るのは EM） |
| 返答を反映 | 「採用 c-0001」「完了 t-0001」など | `python3 scripts/apply_reply.py "採用 c-0001" "完了 t-0001"`（`--dry-run` で確認、`--undo` で直前を戻す） | 約1分 | `data/tasks/tasks.json` |
| 夕方 | 「夕方の締め」 | `python3 scripts/evening_wrapup.py` | 約1分 | 画面に1枚（読み取り専用） |
| 金曜 | 「週次棚卸し」 | `python3 scripts/weekly_review.py`（先回りの放置要約は `python3 scripts/proactive_scan.py --digest`） | 約3分 | 画面に1枚（読み取り専用） |

- Jira 指標（`scripts/jira_metrics.py`、[22](docs/design/22-jira-metrics-catalog.md)）は**試作・架空サンプルのみ**: 更新なし日数とスプリント途中のスコープ変動を数える（SP＝ストーリーポイント＝見積もりの相対値、N＝対象の課題数。見積もり乖離・ブロッカー・担当偏りは未実装）。実接続のキャッシュにはまだ使わない
- 承認キュー（`scripts/approval_queue.py`、[21](docs/design/21-approval-queue.md)）は**試作・架空サンプルのみ**: 入力は `python3 scripts/save_action.py <input>.json --dry-run` で検証して `data/actions/` に保存し（`--dry-run` を外すと保存）、`python3 scripts/approval_queue.py --slot morning --dry-run`（夕は `--slot evening`）で朝・夕それぞれ1枚を出す（個別承認・一括承認とも最大5件ずつ、超過は次の枠へ繰越。`--dry-run` は監査ログ `data/audit/` を追記しない）。送信はしない。上の毎日の手順にはまだ含めない（試用開始時に EM が使うか決める）
- 計画・締め・棚卸しは、返答を定型語にして `apply_reply.py` で反映する（書式は [24-reply-apply.md](docs/design/24-reply-apply.md)）
- 秘書の手順書は `skills/<名前>/SKILL.md`（`morning-plan` / `slack-to-candidates` / `meeting-to-candidates` / `draft-reply` / `evening-wrapup` / `weekly-review` / `proactive-scan` / `sprint-health`）
- 実データは `data/`（gitignore）に置く。サンプルで試すだけなら各 SKILL.md の「試す」を実行

## ディレクトリ

```
templates/drafts/  下書きテンプレ群（Slack 返信・1on1・スプリントサマリ・報告。[README](templates/drafts/README.md)）
docs/design/   設計書（別PC運用: [08-portability.md](docs/design/08-portability.md) / 会社 Mac での再構築: [10-rebuild-guide.md](docs/design/10-rebuild-guide.md)）
config/templates/  設定の雛形（架空値）。現地用は config/local.*（gitignore）
data/          実データ置き場（gitignore）
```
