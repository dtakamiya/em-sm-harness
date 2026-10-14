# 実装規約（スクリプトを書くときの3つの決まり）

状態: ドラフト（emh-040）。`scripts/` を新しく書く・直すときに最初に読む1枚。ローカルのみ・stdlib のみ・外部接続なし（現フェーズは L1）。
サンプルは全て架空。会社固有の情報は書かない。

## 1. 結論
- PR レビューの指摘は「実装の落とし穴」「文書間の矛盾」「手順抜け」の3型に偏った（観察。原因は仮説で、共起を因果とは見ない）。ここは落とし穴型への先回り
- 決まりは3つ: ① パスは `__file__` 基準 ② JSON は読んだ直後に型を検証 ③ 書き込みは tmp → rename、上書き前は `.bak`
- 判断が要る論点はない（既存スクリプトの共通部分を書き出しただけ）

## 2. パスは `__file__` 基準
- repo 内の既定パスは `Path(__file__).resolve().parent.parent` を `ROOT` として組み立てる。カレントディレクトリ（cwd）に依存しない
- 同じ `scripts/` 内の import は `sys.path.insert(0, str(Path(__file__).resolve().parent))` の後に行う
- `data/` 配下はコマンドライン引数で差し替えられるようにする（テストは一時ディレクトリを渡す）
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

- 例: `apply_reply._atomic_write` / `slack_to_candidates._atomic_write_bytes`

## 5. 守られているかの機械確認
- `tests/test_implementation_conventions.py` が、`scripts/` 全体で `__file__` 基準の `ROOT`／既定パスを使うこと、`os.replace` を使う書き込みが `.tmp` 経由であることを確かめる
- 同テストは [12](12-secretary-job-list.md) の件数（§1 の「先回り 14 / 下書き 10 / EM が決める 6」と §3 の表の行数）の照合も持つ。行を足して §1 を直し忘れると失敗する

## 6. 非ゴール
- 既存スクリプトの全面書き換え（新規・修正時に寄せる）
- 外部ライブラリの導入
