# 19. check-no-leak（コミット前の持ち出し検知）

- 根拠: [08 可搬性](08-portability.md)・[09 GO チェックリスト D3](09-go-checklist.md)。実装: `scripts/check_no_leak.py`（emh-025）
- 使い方: `git add` の後、**コミット前に** `python3 scripts/check_no_leak.py`。終了コード 0=OK / 1=error（コミット停止）/ 2=実行不能（git が使えない等。fail-closed）
- 読み取り専用。staged の差分のうち**追加された行だけ**を見る。検出した値そのものは出力しない（ログ経由の二次流出を避ける）

## 検査ルール
| code | level | 内容 |
|---|---|---|
| forbidden-path | error | `data/` `secrets/` 配下、`.env*`、`local.*` が staged（`add -f` された時の最後の砦） |
| token-slack / token-github / token-atlassian / token-aws / token-private-key | error | トークン・秘密鍵の形式に一致。消して環境変数名に置換する |
| url-atlassian / url-slack-archive / email-real-domain | warning | 社内情報らしき URL・メール。`example.com` 以外のドメインは警告 |
| local-pattern:N | warning | `config/local.leak-patterns.txt`（gitignore）に書いた社内固有パターンに一致 |

- 社内固有の語（組織名・プロジェクト名等）は repo に書けないので、1 行 1 正規表現・`#` コメント可のローカルファイルに置く。正規表現が不正なら fail-closed（終了コード 2）
- 説明文などで例として書く行には `leak-ok` を付けると見逃す（付けた行は目視で確認する）

## 限界
- 形式で見るだけ。形式の無い秘密（社内の言い回し・人名）は捕まえられない → ローカルパターンと EM の目視が最後の砦
- 警告は誤検知を含む。「警告 = 止める」にしない（error のみ停止）
- git フック化（自動実行）は未実装。まず手動で使い、うるさくないか EM の所感を待つ
