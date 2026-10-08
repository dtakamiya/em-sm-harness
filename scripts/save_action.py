#!/usr/bin/env python3
"""承認キューの入力（data/actions/<action_id>.json）を検証して 1 件保存する。モック試作。

L1（下書きまで）。stdlib のみ・外部接続なし。Slack / Jira / Confluence へは書かない。
入力 JSON は秘書（Claude）が make_draft の出力などから組み立てる（キーは docs/design/21 §3）。
検証は approval_queue.validate_action と同じ（14 相当の機械検査）。落ちたら何も書かない。
保持期間: 05 は「保持期間付き」とだけ定める。expires を省略すると今日から DEFAULT_RETENTION_DAYS、
指定しても MAX_RETENTION_DAYS を超えるものは拒否する（日数は仮置き。会社ポリシー確認後に見直す）。
"""
import argparse
import json
import os
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from approval_queue import validate_action  # noqa: E402
from check_no_leak import load_local_patterns  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ACTIONS_DIR = ROOT / "data" / "actions"
KNOWN_KEYS = ("action_id", "kind", "title", "target", "body", "priority", "due", "expires",
              "commit_stage", "em_decides", "sensitive")  # docs/design/21 §3。これ以外のキーは保存しない
DEFAULT_RETENTION_DAYS = 14
MAX_RETENTION_DAYS = 90


class SaveError(Exception):
    """EM に返す理由つきの拒否。"""


def prepare(raw, today, extra_patterns=()):
    """検証済みの新しい dict を返す（入力は変更しない）。不正なら SaveError。"""
    if not isinstance(raw, dict):
        raise SaveError("JSON オブジェクトではありません")
    action = {**{k: raw[k] for k in KNOWN_KEYS if k in raw}, "expires": raw.get("expires") or (today + timedelta(days=DEFAULT_RETENTION_DAYS)).isoformat()}
    reason = validate_action(action, extra_patterns)
    if reason:
        raise SaveError(reason)
    limit = today + timedelta(days=MAX_RETENTION_DAYS)
    if date.fromisoformat(action["expires"]) > limit:
        raise SaveError(f"expires は今日から {MAX_RETENTION_DAYS} 日以内にしてください（保持期間の上限）")
    return action


def write_action(actions_dir, action):
    """排他作成（既存の同 ID は上書きしない）。途中で落ちても壊れたファイルを残さない。"""
    actions_dir = Path(actions_dir)
    actions_dir.mkdir(parents=True, exist_ok=True)
    path = actions_dir / f"{action['action_id']}.json"
    if path.exists():
        raise SaveError(f"action_id {action['action_id']} は保存済みです（上書きしません）")
    fd, tmp = tempfile.mkstemp(dir=actions_dir, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(action, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
        os.link(tmp, path)  # 既存なら FileExistsError。競合しても上書きしない
    except FileExistsError:
        raise SaveError(f"action_id {action['action_id']} は保存済みです（上書きしません）")
    finally:
        os.unlink(tmp)
    return path


def main(argv=None):
    ap = argparse.ArgumentParser(description="承認キューの入力 data/actions/<id>.json を検証して保存する。送信・投稿はしない")
    ap.add_argument("input", type=Path, help="action 入力 JSON（匿名化済み）")
    ap.add_argument("--actions-dir", type=Path, default=DEFAULT_ACTIONS_DIR)
    ap.add_argument("--today", type=date.fromisoformat, default=None, help="テスト用。YYYY-MM-DD")
    ap.add_argument("--dry-run", action="store_true", help="検証だけして保存しない")
    args = ap.parse_args(argv)
    try:
        raw = json.loads(args.input.read_text(encoding="utf-8"))
        action = prepare(raw, args.today or date.today(), load_local_patterns())
        if args.dry_run:
            print(f"検証 OK（保存していません）: {action['action_id']}")
            return 0
        path = write_action(args.actions_dir, action)
    except FileNotFoundError:
        print(f"入力が見つかりません: {args.input}", file=sys.stderr)
        return 1
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        print(f"入力 JSON を読めません（{type(exc).__name__}）。何も書いていません", file=sys.stderr)
        return 1
    except SaveError as exc:
        print(f"保存しませんでした: {exc}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"保存できませんでした（{type(exc).__name__}）。何も書いていません", file=sys.stderr)
        return 1
    print(f"承認キューに載せる準備ができました（未送信・送信は EM）: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
