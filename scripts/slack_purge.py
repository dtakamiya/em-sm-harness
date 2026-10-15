#!/usr/bin/env python3
"""Slack の raw / parsed / anon のうち 14 日を過ぎたファイルを消す（13 §8, Q-016）。ローカルのみ・stdlib のみ・外部接続なし。

- 既定は --dry-run（件数だけ出す）。--apply を付けたときだけ削除する。
- 対象は base（既定 data/inbox/slack/）直下の通常ファイル（raw）と parsed/・anon/ 直下の通常ファイルだけ。
  サブディレクトリの中・structured/・先頭ドットのファイル（台帳 .seen.json 等）は触らない。
- シンボリックリンク（base・対象ディレクトリ・ファイル）や範囲外に解決されるものが1つでもあれば、何も消さずに終了コード 2。
- 期限は更新時刻（mtime）で判定。load_anon() と同じく 14 日を超えたもの（13 日は残る・15 日は消える）。
- 出力・監査にファイル名は出さない（raw のファイル名に実名が入り得るため）。件数のみ。
- 監査は data/audit/YYYY-MM-DD.jsonl に 1 行（本文・ファイル名なし）。書けないときは消す前に止める。
"""
import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_BASE = ROOT / "data" / "inbox" / "slack"
DEFAULT_AUDIT_DIR = ROOT / "data" / "audit"
RETENTION_DAYS = 14
SECONDS_PER_DAY = 86400
AREAS = (("raw", ""), ("parsed", "parsed"), ("anon", "anon"))  # (監査上の名前, base からの相対ディレクトリ)
EXIT_REFUSED = 2


class PurgeError(Exception):
    """EM に返す理由つきの拒否。ファイル名は含めない。"""


def _real_dir(path, label):
    if path.is_symlink():
        raise PurgeError(f"{label} がシンボリックリンクです。削除しません")
    if not path.is_dir():
        raise PurgeError(f"{label} がディレクトリではありません")
    return path.resolve()


def _scan_area(base, resolved_base, name, sub, cutoff):
    """1 領域の期限切れ通常ファイルを返す。対象外は黙って除き、リンク・範囲外は PurgeError。"""
    directory = base / sub if sub else base
    if sub and not directory.exists():
        return []
    resolved_dir = resolved_base if not sub else _real_dir(directory, f"{name} ディレクトリ")
    if sub and resolved_dir.parent != resolved_base:
        raise PurgeError(f"{name} が base の外に解決されます。削除しません")
    expired = []
    for entry in sorted(directory.iterdir()):
        if entry.name.startswith("."):
            continue
        info = entry.lstat()
        if entry.is_symlink():
            raise PurgeError(f"{name} にシンボリックリンクがあります。何も削除しません")
        if not entry.is_file() or entry.resolve().parent != resolved_dir:
            continue
        if info.st_mtime < cutoff:
            expired.append(entry)
    return expired


def collect(base, now):
    """{領域名: [期限切れファイル]} を返す。1 つでも拒否条件があれば PurgeError。"""
    base = Path(base)
    resolved_base = _real_dir(base, "base")
    cutoff = now - RETENTION_DAYS * SECONDS_PER_DAY
    return {name: _scan_area(base, resolved_base, name, sub, cutoff) for name, sub in AREAS}


def _ensure_audit_writable(audit_dir, now):
    try:
        audit_dir.mkdir(parents=True, exist_ok=True)
        (audit_dir / f"{_day(now)}.jsonl").open("a", encoding="utf-8").close()
    except OSError as exc:
        raise PurgeError(f"監査ログに書けません（{exc.strerror}）。監査なしでは削除しません")


def _day(now):
    return datetime.fromtimestamp(now).date().isoformat()


def _append_audit(audit_dir, now, deleted):
    row = {"ts": datetime.fromtimestamp(now).astimezone().isoformat(timespec="seconds"), "event": "retention_purged",
           "action": "slack.purge", "level_applied": "L0", "retention_days": RETENTION_DAYS, "deleted": deleted}
    with (audit_dir / f"{_day(now)}.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def _delete(found):
    """直前に再確認して unlink。消えていた・リンクに変わっていたものは数えない。"""
    deleted = {name: 0 for name, _ in AREAS}
    for name, files in found.items():
        for path in files:
            if path.is_symlink() or not path.is_file():
                continue
            try:
                path.unlink()
            except FileNotFoundError:
                continue
            deleted[name] += 1
    return deleted


def main(argv=None, now=None):
    parser = argparse.ArgumentParser(description="Slack の raw/parsed/anon の 14 日経過分を消す（既定は dry-run）")
    parser.add_argument("--base", type=Path, default=DEFAULT_BASE, help="data/inbox/slack/ 相当")
    parser.add_argument("--audit-dir", type=Path, default=DEFAULT_AUDIT_DIR)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="件数だけ出す（既定）")
    mode.add_argument("--apply", action="store_true", help="期限切れを実際に削除する")
    args = parser.parse_args(argv)
    now = time.time() if now is None else now
    try:
        found = collect(args.base, now)
        total = sum(len(v) for v in found.values())
        counts = ", ".join(f"{name}: {len(files)}" for name, files in found.items())
        if not args.apply:
            print(f"dry-run: 期限切れ（{RETENTION_DAYS} 日超）{total} 件 / {counts}。削除するには --apply")
            return 0
        if total == 0:
            print("期限切れはありません")
            return 0
        _ensure_audit_writable(args.audit_dir, now)
        deleted = _delete(found)
        _append_audit(args.audit_dir, now, deleted)
        print(f"削除しました: {sum(deleted.values())} 件 / " + ", ".join(f"{k}: {v}" for k, v in deleted.items()))
        return 0
    except PurgeError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_REFUSED


if __name__ == "__main__":
    sys.exit(main())
