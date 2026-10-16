# 実装規約（スクリプトを書くときの4つの決まり）

状態: ドラフト（emh-040）。`scripts/` を新しく書く・直すときに最初に読む1枚。ローカルのみ・stdlib のみ・外部接続なし（現フェーズは L1）。
サンプルは全て架空。会社固有の情報は書かない。

## 1. 結論
- PR レビューの指摘は「実装の落とし穴」「文書間の矛盾」「手順抜け」の3型に偏った（観察。原因は仮説で、共起を因果とは見ない）。ここは落とし穴型への先回り
- 決まりは4つ: ① パスは `__file__` 基準 ② JSON は読んだ直後に型を検証 ③ 書き込みは tmp → rename、上書き前は `.bak` ④ 入力を読む script は fail-closed（§8）
- 判断が要る論点はない（既存スクリプトの共通部分を書き出しただけ）

## 2. パスは `__file__` 基準
- repo 内の既定パスは `Path(__file__).resolve().parent.parent` を `ROOT` として組み立てる。カレントディレクトリ（cwd）に依存しない
- 同じ `scripts/` 内の import は `sys.path.insert(0, str(Path(__file__).resolve().parent))` の後に行う
- `data/` 配下はコマンドライン引数で差し替えられるようにする（テストは一時ディレクトリを渡す）
- 対象は `ROOT` や `DEFAULT_` の既定パスを持つ script。入力パスを引数で受けるだけの `apply_reply.py` / `calendar_paste_to_meetings.py` / `slack_to_candidates.py` は `__file__` を持たず、対象外
- 例: `approval_queue.py` / `save_action.py` / `morning_plan.py`

## 3. JSON は読んだ直後に型を検証
- 読めない（`JSONDecodeError`）・形が違う（期待は `{key: [...]}` なのに別型）のとき、**何も書かずに止まり**、理由と「`.bak` からの復元」を EM に返す。黙って空扱いにして上書きしない
- ファイルが無い（`FileNotFoundError`）は「空の初期状態」と壊れを区別して扱う
- 検証は全件終えてから書く（1件でも不正なら何も書かない）
- 例: `apply_reply._read` / `_read_list`

## 4. 書き込みは tmp → rename、上書き前は `.bak`
- 書き込みは同じディレクトリの `<name>.tmp` に書いてから `os.replace`。途中で落ちても元ファイルは壊れない
- 既存ファイルを更新する前に `.bak` へ退避する。**書き手ごとに別名**にして互いの退避を上書きしない

| 書き手 | 退避ファイル名 |
|---|---|
| `apply_reply.py`（`--undo` の戻り先） | `<name>.bak` |
| `slack_to_candidates.py` | `candidates.json.pre-slack.bak` |
| `meeting_to_candidates.py` | `candidates.json.pre-meeting.bak` |
| `proactive_scan.py`（状態ファイル） | `<name>.json.bak`（tmp 経由で書く。追従済み） |

- 例: `apply_reply._atomic_write` / `slack_to_candidates._atomic_write_bytes`

## 5. 守られているかの機械確認
- `tests/test_implementation_conventions.py` が、`ROOT` / `DEFAULT_` を持つ script で `Path(__file__)` を使うこと、`os.getcwd` / `Path.cwd` を使わないこと、`os.replace` を使う script が `.tmp` を扱うこと、`BACKUP_NAME` が重複せず本書の表にあることを確かめる
- 限界: 判定は文字列の有無（substring）で、書き込みごとの tmp 経由までは見ない。レビューで補う
- 同テストは [12](12-secretary-job-list.md) の件数（§1 の「先回り 14 / 下書き 10 / EM が決める 6」と §3 の表の行数）の照合も持つ。行を足して §1 を直し忘れると失敗する

## 6. 検証の観点（受け入れ基準）
- 12 の §1 の件数をずらすと規約テストが失敗する
- `ROOT` / `DEFAULT_` を持つ新 script が `__file__` を使わないと失敗する
- 全 script の `BACKUP_NAME` が互いに別名で、§4 の表に載っている
- 例外（§4 の表の注記）を除き、`.bak` は tmp → rename で書かれている

## 7. 非ゴール
- 既存スクリプトの全面書き換え（新規・修正時に寄せる）
- 外部ライブラリの導入

## 8. 入力を読む script は fail-closed（判定不能は止めて何も書かない）
- fail-closed ＝ 入力を判定できないとき、通さずに**止めて何も書かない**（黙って通す fail-open にしない）。対象は貼り付け・JSON など外から来る入力を読む script
- 止めるのは次のとき: 入力が空・UTF-8 で読めない／判定の材料（機微語ファイル・名簿・鍵）が無い・空／メタ（front matter・見出し）が不正／話者・人名を判定できない／出力先に同名ファイルがある。不正な見出しの後の行を前の見出しに黙って付けない
- 止めるときの作法: 終了コードは **2**（1 は「直して再実行」の警告用で、止めた場合と区別できなくなる）／理由と EM がやることを1行で stderr に返す／入力の中身（人名・本文）とパスは出さない／検証を全件終えてから書く（1件でも不正なら何も書かない。§3 と同じ）
- 例外（止めずに正常終了してよい）: 取り込み済みの再投入は「スキップ」と表示し、何も書かず終了コード 0
- 新しい入力 script は、共通の敵対入力表（[35](35-adversarial-input-table.md)）の A1〜A7 に当てはめ、列を足してから出す。既存の前処理4本の対応状況と未対応（D-016〜D-019）も 35 にある
- 機械確認: `tests/test_adversarial_inputs.py`（表と実テストのずれも検知）。限界: 1マス1入力の代表例のみ。別形はレビューで補う
