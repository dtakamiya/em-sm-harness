#!/usr/bin/env python3
"""コミット前の持ち出し検知。staged の変更に実データ・秘密値・社内情報らしきものが混ざっていないかを見る。

設計: docs/design/19-check-no-leak.md（emh-025）。読み取り専用・外部接続なし。
終了コード: 0=OK（warning のみ含む）/ 1=error あり（コミット停止）/ 2=実行不能（git が使えない等。fail-closed）。
"""
import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parent.parent
LOCAL_PATTERNS_FILE = ROOT / "config" / "local.leak-patterns.txt"

# 置いてあるだけで error になるパス（gitignore の対象と同じ。add -f されたときの最後の砦）
FORBIDDEN_DIRS = ("data", "secrets")
FORBIDDEN_NAME_RES = (re.compile(r"^\.env"), re.compile(r".+\.env$"), re.compile(r"^local\."))

# トークン形式（error）。検出器自身が誤検知しないよう、前置きを分割して書く
TOKEN_RES = (
    ("token-slack", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}")),
    ("token-github", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}")),
    ("token-atlassian", re.compile(r"\bAT" + r"ATT[A-Za-z0-9_=-]{20,}")),
    ("token-aws", re.compile(r"\bAK" + r"IA[0-9A-Z]{16}\b")),
    ("token-private-key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
)

# 社内情報らしきもの（warning）。サンプルは example.* / 架空ドメインに限る
INTERNAL_RES = (
    ("url-atlassian", re.compile(r"https?://[\w.-]+\.atlassian\.net\b")),
    ("url-slack-archive", re.compile(r"https?://[\w.-]+\.slack\.com/archives/\w+")),
    ("email-real-domain", re.compile(r"\b[\w.+-]+@(?!example\.(?:com|org|net)\b)[\w-]+(?:\.[\w-]+)+\b")),
)

# 説明文・テストで例として書く行を許す印
ALLOW_MARK = "leak-ok"


@dataclass(frozen=True)
class Finding:
    level: str  # "error" | "warning"
    code: str
    where: str
    message: str


def check_path(path):
    parts = PurePosixPath(path).parts
    if parts and parts[0] in FORBIDDEN_DIRS:
        return [Finding("error", "forbidden-path", path, f"{parts[0]}/ 配下は実データ置き場。コミットしない（git reset して除外）")]
    name = parts[-1] if parts else ""
    if name.endswith(".example"):  # 雛形（架空値のみ）はコミットしてよい
        return []
    if any(rx.search(name) for rx in FORBIDDEN_NAME_RES):
        return [Finding("error", "forbidden-path", path, "ローカル設定・環境変数ファイルはコミットしない")]
    return []


def load_local_patterns(path=LOCAL_PATTERNS_FILE):
    """社内固有の検出パターン（1行1正規表現、# はコメント）。repo には置かない。無ければ空。"""
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return ()
    except OSError as exc:
        raise SystemExit(f"{path} を読めません（{exc}）。NG 扱いです（fail-closed）")
    compiled = []
    for no, line in enumerate(lines, 1):
        text = line.strip()
        if not text or text.startswith("#"):
            continue
        try:
            compiled.append((f"local-pattern:{no}", re.compile(text)))
        except re.error as exc:
            raise SystemExit(f"{path}:{no} の正規表現が不正です（{exc}）。NG 扱いです（fail-closed）")
    return tuple(compiled)


def scan_added_lines(path, added_lines, local_patterns=()):
    """追加行だけを検査する。マッチした文字列そのものは出力しない（ログへの二次流出を避ける）。"""
    findings = []
    for no, line in added_lines:
        if ALLOW_MARK in line:
            continue
        findings += [Finding("error", code, f"{path}:{no}", "トークン形式に一致。値は表示しない。消して環境変数名に置換") for code, rx in TOKEN_RES if rx.search(line)]
        findings += [Finding("warning", code, f"{path}:{no}", "社内情報らしき文字列。架空サンプルか確認") for code, rx in INTERNAL_RES if rx.search(line)]
        findings += [Finding("warning", code, f"{path}:{no}", "ローカル定義の社内パターンに一致") for code, rx in local_patterns if rx.search(line)]
    return findings


def parse_added_lines(diff_text):
    """`git diff --cached -U0` の出力を {path: [(行番号, 本文)]} にする。"""
    result, path, no = {}, None, 0
    for raw in diff_text.splitlines():
        if raw.startswith("+++ "):
            path = raw[6:] if raw.startswith("+++ b/") else None
        elif raw.startswith("@@"):
            m = re.search(r"\+(\d+)", raw)
            no = int(m.group(1)) if m else 0
        elif raw.startswith("+") and path:
            result.setdefault(path, []).append((no, raw[1:]))
            no += 1
    return result


def _git(*args):
    try:
        return subprocess.run(["git", *args], cwd=ROOT, check=True, capture_output=True, text=True).stdout
    except (OSError, subprocess.CalledProcessError) as exc:
        raise SystemExit(f"git を実行できません（{exc}）。NG 扱いです（fail-closed）")


def run_check(diff_text, paths, local_patterns=()):
    findings = [f for p in paths for f in check_path(p)]
    for path, lines in parse_added_lines(diff_text).items():
        findings += scan_added_lines(path, lines, local_patterns)
    return findings


def main(argv=None):
    argparse.ArgumentParser(description=__doc__.splitlines()[0]).parse_args(argv)
    paths = [p for p in _git("diff", "--cached", "--name-only", "--diff-filter=ACMR").splitlines() if p]
    findings = run_check(_git("diff", "--cached", "-U0", "--no-color"), paths, load_local_patterns())
    for f in findings:
        print(f"[{f.level}] {f.code} {f.where}: {f.message}")
    errors = sum(f.level == "error" for f in findings)
    print(f"check-no-leak: staged {len(paths)} 件 / error {errors} / warning {len(findings) - errors}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
