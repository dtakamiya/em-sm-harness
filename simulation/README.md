# simulation/ — 架空の 1 週間の模擬運用

README「毎日の使い方」の順（朝 → Slack/会議の取り込み → 返信案 → 返答の反映 → 夕方 → 金曜の棚卸し）を、実コマンドで月〜金（2026-10-05〜10-09、日付固定）通して再現する。

```
python3 simulation/run_week.py                      # 終了コード 0=全成功 / 1=失敗ステップあり / 2=安全検査 NG
```

- 既定の入力は月曜起点の `tests/fixtures/sample-week-monday`（月曜朝の時点より後の履歴・Jira 更新を含まない）。`--fixture snapshot` で 10/8（水）時点の断面 `sample-week` も使える（月曜から通すと未来日付を読む）
- **L1・ローカル完結**: 送信・書込・外部接続なし。実データは使わない（入力は `tests/fixtures/sample-week` と各 skill の `examples/` の架空データ）
- 毎回 `simulation/out/workspace/` を作り直し、そこへ fixture をコピーして使う。各スクリプトの `--tasks` / `--tasks-dir` / `--data-dir` 等でワークスペースを向け、`data/` は触らない。実行後に元 fixture と `data/` のハッシュ不変を検証する
- `simulation/out/`（ワークスペース・`run-log.md` / `run-log.json`）は gitignore。コミットしない
- 結果と摩擦の記録: [FINDINGS.md](FINDINGS.md)

## 計測していないこと

- Slack / 会議メモを匿名化・構造化 JSON にする手間（秘書の作業）。入力は用意済みの `examples/` を使うため、README の「約3分」の大半はここで未測定
- EM が判断・返答を考える時間。「出力を読む時間」は 1 分 500 字の目安で、README の目標時間とは別物
