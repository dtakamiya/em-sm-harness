#!/usr/bin/env python3
"""カレンダー表示を貼ったテキストを meetings.json（proactive_scan の入力）に変換する（emh-078）。

ローカルのみ・stdlib のみ・外部接続なし（カレンダーには接続しない。EM が貼ったテキストを読むだけ）。
- 日付見出し行（10/12 (月)・10月12日(月)・2026-10-12・Mon, Oct 12 など）の下の「時刻 + 題名」行を会議として拾う。
  時刻は 10:00 / 10:00-11:00 / 10:00am / 終日 / All day。時刻と題名が同じ行で、日付見出しの直後に並ぶ形を想定。
- 読めなかった行は捨てず、行番号つきで stderr に報告する（1 件でもあれば終了コード 1。変換結果は出す）。
- prep_task_id は常に null（準備タスクの紐付けは EM が後で決める）。
- --out は既存ファイルを上書きしない。省略時は標準出力。
"""
import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path

SCHEMA_VERSION = 1
ID_PREFIX = "m-"
MONTHS = {m: i for i, m in enumerate(
    ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), 1)}
WEEKDAY = r"(?:\s*[（(][^()（）]*[)）])?"
HEADER_RES = (
    re.compile(rf"^(?:(?P<y>\d{{4}})[-/.])?(?P<m>\d{{1,2}})[-/.](?P<d>\d{{1,2}}){WEEKDAY}$"),
    re.compile(rf"^(?:(?P<y>\d{{4}})年\s*)?(?P<m>\d{{1,2}})月\s*(?P<d>\d{{1,2}})日{WEEKDAY}$"),
    re.compile(r"^(?:[A-Za-z]+,?\s+)?(?P<mon>[A-Za-z]{3})[A-Za-z]*\.?\s+(?P<d>\d{1,2})(?:,?\s+(?P<y>\d{4}))?$"),
)
TIME = r"\d{1,2}:\d{2}(?:\s*[ap]m)?"
EVENT_RE = re.compile(
    rf"^(?P<time>終日|all[- ]day|{TIME}(?:\s*[-–—~〜～]\s*{TIME})?)\s+(?P<title>\S.*)$", re.I)


def parse_header(line, default_year):
    """日付見出しなら date、そうでなければ None（存在しない日付も None）。"""
    for pattern in HEADER_RES:
        match = pattern.match(line)
        if not match:
            continue
        groups = match.groupdict()
        month = MONTHS.get(groups["mon"].lower()) if "mon" in groups else int(groups["m"])
        if month is None:
            continue
        try:
            return date(int(groups["y"] or default_year), month, int(groups["d"]))
        except ValueError:
            return None
    return None


def convert(text, default_year):
    """戻り値: (meetings, unreadable)。unreadable は (行番号, 行) のリスト。入力は変更しない。"""
    current = None
    found = []
    unreadable = []
    for number, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line:
            continue
        header = parse_header(line, default_year)
        if header:
            current = header
            continue
        event = EVENT_RE.match(line)
        if event and current:
            found.append((current, event.group("title").strip()))
        else:
            unreadable.append((number, line))
    ordered = sorted(found, key=lambda pair: pair[0])
    meetings = [{"id": f"{ID_PREFIX}{i:04d}", "title": title, "start": day.isoformat(), "prep_task_id": None}
                for i, (day, title) in enumerate(ordered, 1)]
    return meetings, unreadable


def build_document(meetings):
    return {"version": SCHEMA_VERSION, "meetings": meetings}


def write_new(path, text):
    """既存ファイルは上書きしない（排他的に作成）。"""
    with open(path, "x", encoding="utf-8") as fh:
        fh.write(text)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("paste", help="カレンダー表示を貼ったテキストファイル（'-' で標準入力）")
    ap.add_argument("--year", type=int, default=date.today().year, help="見出しに年がないときの年（既定: 今年）")
    ap.add_argument("--out", help="書き出し先（省略時は標準出力）。既存ファイルは上書きしない")
    args = ap.parse_args(argv)
    try:
        text = sys.stdin.read() if args.paste == "-" else Path(args.paste).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        print(f"貼り付けファイルを読めません: {exc.__class__.__name__}", file=sys.stderr)
        return 2
    meetings, unreadable = convert(text, args.year)
    payload = json.dumps(build_document(meetings), ensure_ascii=False, indent=1) + "\n"
    if args.out:
        try:
            write_new(args.out, payload)
        except FileExistsError:
            print("出力先が既にあります。上書きしないので、別名にするか退避してから再実行してください", file=sys.stderr)
            return 2
        except OSError as exc:
            print(f"書き出せません: {exc.__class__.__name__}", file=sys.stderr)
            return 2
        print(f"会議 {len(meetings)} 件を書き出しました")
    else:
        sys.stdout.write(payload)
    if unreadable:
        print(f"読めなかった行 {len(unreadable)} 件（変換結果には入っていません。手で足すか貼り直してください）:", file=sys.stderr)
        for number, line in unreadable:
            print(f"  {number} 行目: {line}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
