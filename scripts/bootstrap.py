#!/usr/bin/env python3
"""data/ の置き場を作り、config/local.yaml を雛形から用意し、最後に check_env を実行する。

設計: docs/design/08-portability.md・10-rebuild-guide.md §4。冪等・既存ファイルは上書きしない。
ネットワーク・Jira/Confluence/Slack には触れない。終了コードは check_env に従う（0=OK / 1=NG）。
"""
import argparse
import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_env  # noqa: E402

DIR_MODE = 0o700  # 06-cache-schema §権限: ディレクトリ 0700・ファイル 0600
FILE_MODE = 0o600


def create_data_dirs(root):
    """data/ 配下の置き場を作る。新規に作ったものだけ返す。既存の中身・権限は触らない。"""
    created = []
    data = Path(root) / "data"
    for rel in ("", *check_env.DATA_DIRS):
        path = data / rel if rel else data
        if path.is_dir():
            continue
        path.mkdir(parents=True, mode=DIR_MODE, exist_ok=True)
        os.chmod(path, DIR_MODE)  # umask に左右されず 0700
        created.append(path.relative_to(root).as_posix())
    return created


def ensure_local_config(root):
    """config/local.yaml が無ければ雛形からコピー。あれば何もしない。戻り値: コピーしたか。"""
    root = Path(root)
    dest = root / check_env.LOCAL_CONFIG
    if dest.exists():
        return False
    src = root / check_env.LOCAL_CONFIG_EXAMPLE
    if not src.is_file():
        raise SystemExit(f"雛形 {check_env.LOCAL_CONFIG_EXAMPLE} が見つかりません。設計書 20 §5 から再生成してください")
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dest)
    os.chmod(dest, FILE_MODE)
    return True


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", default=str(check_env.ROOT), help="対象 repo ルート（既定: この repo）")
    args = parser.parse_args(argv)
    root = Path(args.root)
    created = create_data_dirs(root)
    print(f"bootstrap: data/ 新規作成 {len(created)} 件" + (f"（{', '.join(created)}）" if created else "（既にあり）"))
    copied = ensure_local_config(root)
    print("bootstrap: config/local.yaml を雛形から作成。会社固有値を埋めてください" if copied else "bootstrap: config/local.yaml は既にあり（上書きしない）")
    print("--- check-env ---")
    return check_env.main(["--root", str(root)])


if __name__ == "__main__":
    sys.exit(main())
