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

## ディレクトリ

```
docs/design/   設計書（別PC運用: [08-portability.md](docs/design/08-portability.md) / 会社 Mac での再構築: [10-rebuild-guide.md](docs/design/10-rebuild-guide.md)）
config/templates/  設定の雛形（架空値）。現地用は config/local.*（gitignore）
data/          実データ置き場（gitignore）
```
