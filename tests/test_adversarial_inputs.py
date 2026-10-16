"""敵対入力の共通テスト表（docs/design/35）と、既存の前処理 4 本の対応づけ（emh-085）。

表の各セルは `OK <test名>`（止まる・何も書かない）、`NG D-xxx <test名>`（後回し台帳 34 に載せた未対応。
expectedFailure で固定。直ると「想定外の成功」で落ちるので、表と台帳を更新する）、`—（理由）`（対象外）のどれか。
入力は全て架空。実データ・実接続は使わない。
"""
import io
import json
import os
import re
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import calendar_paste_to_meetings as cp  # noqa: E402
import meeting_preprocess as mp  # noqa: E402
import slack_anonymize as sa  # noqa: E402
import slack_preprocess as sp  # noqa: E402

TABLE_DOC = ROOT / "docs" / "design" / "35-adversarial-input-table.md"
LEDGER_DOC = ROOT / "docs" / "design" / "34-deferred-review-findings.md"
ROSTER = ROOT / "config" / "templates" / "local.roster.json.example"
KEY = "test-key-not-secret"
STOP_CODE = 2  # 27 §8: 判定不能で止めたときの終了コード
FRONT = "---\nmeeting_alias: ex-planning\nheld_on: 2026-10-05\n---\n"
SLACK_OK = "Alice Example  10:00\nお疲れさまです\n"


class AdversarialBase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.out = self.dir / "out"
        self.words = self.write("words.txt", "# 架空\n査定\n")
        original = mp.ALLOWED_OUT_ROOT
        mp.ALLOWED_OUT_ROOT = self.dir  # 実 data/ には書かない
        self.addCleanup(setattr, mp, "ALLOWED_OUT_ROOT", original)
        old = os.environ.get(sa.KEY_ENV)
        os.environ[sa.KEY_ENV] = KEY
        self.addCleanup(lambda: os.environ.__setitem__(sa.KEY_ENV, old) if old is not None else os.environ.pop(sa.KEY_ENV, None))

    def write(self, name, data):
        path = self.dir / name
        path.parent.mkdir(parents=True, exist_ok=True)
        (path.write_bytes if isinstance(data, bytes) else path.write_text)(data)
        return path

    def written(self):
        """出力先に残ったファイル（台帳 .seen.json も含む）。何も書いていなければ空。"""
        return sorted(p.name for p in self.out.rglob("*") if p.is_file()) if self.out.exists() else []

    def call(self, main, *args):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main([str(a) for a in args])
        return code, out.getvalue()

    # 4 本の呼び出し口。出力先は self.out に揃える
    def slack_pre(self, paste, words=None, extra=()):
        return self.call(sp.main, paste, "--words-file", words or self.words, "--out-dir", self.out, *extra)

    def slack_anon(self, parsed, roster=ROSTER):
        return self.call(sa.main, parsed, "--roster", roster, "--anon-dir", self.out)

    def meeting_pre(self, paste, words=None, roster=ROSTER):
        return self.call(mp.main, paste, "--roster", roster, "--words-file", words or self.words, "--out-dir", self.out)

    def calendar(self, paste, out_name="meetings.json"):
        self.out.mkdir(parents=True, exist_ok=True)  # calendar は出力先ディレクトリを作らない
        return self.call(cp.main, paste, "--year", 2026, "--out", self.out / out_name)

    def parsed_json(self, speaker="Alice Example", text="x", meta=None):
        body = {"source": {"file": "p.md"}, "meta": meta or {}, "notes": [],
                "messages": [{"id": "m-001", "speaker": speaker, "time": "10:00", "text": text}]}
        return self.write("in/parsed.json", json.dumps(body, ensure_ascii=False))

    def assert_stopped(self, code, msg=""):
        self.assertNotEqual(code, 0, msg)
        self.assertEqual(self.written(), [], "止まったのに出力が残っている")


class AdversarialInputTest(AdversarialBase):
    # A1 空入力
    def test_a1_slack_preprocess_empty(self):
        code, _ = self.slack_pre(self.write("in/empty.md", ""))
        self.assert_stopped(code)

    test_a1_slack_preprocess_empty = unittest.expectedFailure(test_a1_slack_preprocess_empty)  # D-016

    def test_a1_slack_anonymize_empty(self):
        code, _ = self.slack_anon(self.write("in/empty.json", ""))
        self.assert_stopped(code)

    def test_a1_meeting_preprocess_empty(self):
        code, _ = self.meeting_pre(self.write("in/empty.md", "  \n\n"))
        self.assert_stopped(code)

    def test_a1_calendar_empty(self):
        code, _ = self.calendar(self.write("in/empty.txt", ""))
        self.assert_stopped(code)

    # A2 UTF-8 として読めないバイト列
    def test_a2_slack_preprocess_invalid_utf8(self):
        code, _ = self.slack_pre(self.write("in/bad.md", b"\xff\xfe\x00bad"))
        self.assert_stopped(code)

    def test_a2_slack_anonymize_invalid_utf8(self):
        code, _ = self.slack_anon(self.write("in/bad.json", b"\xff\xfe\x00bad"))
        self.assert_stopped(code)

    def test_a2_meeting_preprocess_invalid_utf8(self):
        code, _ = self.meeting_pre(self.write("in/bad.md", b"\xff\xfe\x00bad"))
        self.assert_stopped(code)

    def test_a2_calendar_invalid_utf8(self):
        code, _ = self.calendar(self.write("in/bad.txt", b"\xff\xfe\x00bad"))
        self.assert_stopped(code)

    # A3 判定の材料（機微語・名簿・鍵）が無い／空
    def test_a3_slack_preprocess_empty_words(self):
        code, _ = self.slack_pre(self.write("in/p.md", SLACK_OK), words=self.write("empty-words.txt", "\n# だけ\n"))
        self.assert_stopped(code)

    def test_a3_slack_anonymize_missing_key(self):
        parsed = self.parsed_json()
        os.environ[sa.KEY_ENV] = ""
        code, _ = self.slack_anon(parsed)
        self.assert_stopped(code)

    def test_a3_meeting_preprocess_missing_roster(self):
        code, _ = self.meeting_pre(self.write("in/n.md", FRONT + "- 確認: ok\n"), roster=self.dir / "no-such-roster.json")
        self.assert_stopped(code)

    # A4 行末コロンだけの話者行（「- 山田:」）・名簿外の話者
    def test_a4_slack_anonymize_unmapped_speaker_after_preprocess(self):
        paste = self.write("in/p.md", "山田:  10:00\nよろしくお願いします\n")
        parsed_dir = self.dir / "parsed"
        sp.run(paste, self.words, parsed_dir, False)  # 前処理は通る（匿名化段で止める設計）
        parsed = next(parsed_dir.glob("p-*.json"))
        code, _ = self.slack_anon(parsed)
        self.assert_stopped(code)

    def test_a4_meeting_preprocess_trailing_colon_speaker(self):
        code, _ = self.meeting_pre(self.write("in/n.md", FRONT + "- 山田:\n  - 件A\n"))
        self.assert_stopped(code)

    # A5 不正な見出し・メタ
    def test_a5_slack_preprocess_invalid_meta(self):
        code, _ = self.slack_pre(self.write("in/p.md", "---\nchannel_alias: ../../x\n---\n" + SLACK_OK))
        self.assert_stopped(code)

    test_a5_slack_preprocess_invalid_meta = unittest.expectedFailure(test_a5_slack_preprocess_invalid_meta)  # D-017

    def test_a5_slack_anonymize_person_name_in_meta(self):
        code, _ = self.slack_anon(self.parsed_json(speaker="em", meta={"channel_alias": "Taro Yamada"}))
        self.assert_stopped(code)

    def test_a5_meeting_preprocess_invalid_meta(self):
        for name, front in {"alias": "meeting_alias: ../x\nheld_on: 2026-10-05\n", "date": "meeting_alias: ex\nheld_on: 2026-02-30\n",
                            "missing": ""}.items():
            with self.subTest(case=name):
                code, _ = self.meeting_pre(self.write(f"in/{name}.md", f"---\n{front}---\nok\n"))
                self.assert_stopped(code)

    def test_a5_calendar_invalid_date_header_does_not_attach_to_previous_day(self):
        paste = self.write("in/c.txt", "10/12\n10:00 前の会議\n2/30\n11:00 不正見出しの下の会議\n")
        code, stdout = self.call(cp.main, paste, "--year", 2026)  # 標準出力側で、付いた日付を確かめる
        self.assertNotEqual(code, 0)
        starts = {m["title"]: m["start"] for m in json.loads(stdout)["meetings"]}
        self.assertEqual(starts, {"前の会議": "2026-10-12"})
        code, _ = self.calendar(paste)  # --out には書かない
        self.assert_stopped(code)

    # A6 出力先に同名ファイルが既にある
    def test_a6_slack_preprocess_existing_output(self):
        paste = self.write("in/p.md", SLACK_OK)
        self.assertEqual(self.slack_pre(paste)[0], 0)
        (self.out / sp.LEDGER_NAME).unlink()  # 台帳が無い状態で同じ貼り付けを再投入する
        target = next(self.out.glob("p-*.json"))
        before = target.read_bytes()
        code, _ = self.slack_pre(paste)
        self.assertNotEqual(code, 0)
        self.assertEqual(target.read_bytes(), before, "既存の出力を上書きした")

    def test_a6_slack_anonymize_existing_output(self):
        parsed = self.parsed_json()
        self.assertEqual(self.slack_anon(parsed)[0], 0)
        target = next(self.out.glob("slack-anon-*.json"))
        before = target.read_bytes()
        code, _ = self.slack_anon(parsed)
        self.assertNotEqual(code, 0)
        self.assertEqual(target.read_bytes(), before)

    def test_a6_meeting_preprocess_existing_output(self):
        paste = self.write("in/n.md", FRONT + "- 確認: ok\n")
        self.assertEqual(self.meeting_pre(paste)[0], 0)
        target = self.out / "2026-10-05-ex-planning.md"
        before = target.read_bytes()
        code, _ = self.meeting_pre(paste)
        self.assertNotEqual(code, 0)
        self.assertEqual(target.read_bytes(), before)

    def test_a6_calendar_existing_output(self):
        paste = self.write("in/c.txt", "10/12\n10:00 会議A\n")
        self.assertEqual(self.calendar(paste)[0], 0)
        target = self.out / "meetings.json"
        before = target.read_bytes()
        code, _ = self.calendar(paste)
        self.assertNotEqual(code, 0)
        self.assertEqual(target.read_bytes(), before)

    # A7 同じ内容の再投入・入力内の重複
    def test_a7_slack_preprocess_repaste_writes_nothing_new(self):
        paste = self.write("in/p.md", SLACK_OK)
        self.assertEqual(self.slack_pre(paste)[0], 0)
        before = self.written()
        code, stdout = self.slack_pre(paste)
        self.assertEqual(code, 0)  # 取り込み済みスキップは正常終了（何も書かない）
        self.assertIn("取り込み済み", stdout)
        self.assertEqual(self.written(), before)

    def test_a7_calendar_duplicate_events_in_one_paste(self):
        paste = self.write("in/c.txt", "10/12\n10:00 会議A\n10/12\n10:00 会議A\n")
        _, stdout = self.call(cp.main, paste, "--year", 2026)
        self.assertEqual(len(json.loads(stdout)["meetings"]), 1)

    test_a7_calendar_duplicate_events_in_one_paste = unittest.expectedFailure(test_a7_calendar_duplicate_events_in_one_paste)  # D-019


class StopExitCodeTest(AdversarialBase):
    """27 §8: 判定不能で止めたときの終了コードは 2（1 は『直して再実行』の警告に使われていて区別できない）。"""

    def test_exit_code_slack_anonymize(self):
        self.assertEqual(self.slack_anon(self.write("in/bad.json", b"\xff"))[0], STOP_CODE)

    def test_exit_code_meeting_preprocess(self):
        self.assertEqual(self.meeting_pre(self.write("in/bad.md", b"\xff"))[0], STOP_CODE)

    def test_exit_code_slack_preprocess(self):
        self.assertEqual(self.slack_pre(self.write("in/bad.md", b"\xff"))[0], STOP_CODE)

    test_exit_code_slack_preprocess = unittest.expectedFailure(test_exit_code_slack_preprocess)  # D-018

    def test_exit_code_calendar_empty(self):
        self.assertEqual(self.calendar(self.write("in/empty.txt", ""))[0], STOP_CODE)

    test_exit_code_calendar_empty = unittest.expectedFailure(test_exit_code_calendar_empty)  # D-018


CELL_RE = re.compile(r"^(?:(OK) (test_\w+)|(NG) (D-\d+) (test_\w+)|—.+)$")


def table_cells():
    """35 の表（| で始まる行のうち 1 列目が A<n> / E<n> のもの）を [(行ID, 列名, セル)] で返す。"""
    cells, header = [], None
    for line in TABLE_DOC.read_text(encoding="utf-8").splitlines():
        if not line.startswith("|"):
            continue
        cols = [c.strip() for c in line.strip().strip("|").split("|")]
        if cols[0] == "種別":
            header = cols
        elif header and re.fullmatch(r"[AE]\d", cols[0].split(" ")[0]):
            cells += [(cols[0].split(" ")[0], header[i], cols[i]) for i in range(1, len(cols))]
    return cells


class TableConsistencyTest(unittest.TestCase):
    """表と実テストがずれない: 表のテスト名は実在し、NG は expectedFailure、台帳の D-ID も実在する。"""

    def all_tests(self):
        return {**vars(AdversarialInputTest), **vars(StopExitCodeTest)}

    def test_every_cell_has_a_known_shape(self):
        cells = table_cells()
        self.assertGreaterEqual(len(cells), 7 * 4)
        for row, col, cell in cells:
            self.assertRegex(cell, CELL_RE, f"{row}/{col}")

    def test_between_five_and_eight_adversarial_kinds(self):
        kinds = {row for row, _, _ in table_cells() if row.startswith("A")}
        self.assertTrue(5 <= len(kinds) <= 8, kinds)

    def test_ok_cells_name_existing_plain_tests(self):
        tests = self.all_tests()
        for row, col, cell in table_cells():
            m = CELL_RE.match(cell)
            if m and m.group(1):
                with self.subTest(cell=f"{row}/{col}"):
                    self.assertIn(m.group(2), tests)
                    self.assertFalse(getattr(tests[m.group(2)], "__unittest_expecting_failure__", False))

    def test_ng_cells_name_expected_failure_tests_and_existing_ledger_rows(self):
        tests = self.all_tests()
        ledger = LEDGER_DOC.read_text(encoding="utf-8")
        for row, col, cell in table_cells():
            m = CELL_RE.match(cell)
            if m and m.group(3):
                with self.subTest(cell=f"{row}/{col}"):
                    self.assertTrue(getattr(tests[m.group(5)], "__unittest_expecting_failure__", False))
                    self.assertIsNotNone(re.search(rf"^\| {m.group(4)} \|.*\| open \|$", ledger, re.M), "台帳 34 に open の行が無い")

    def test_every_test_is_listed_in_the_table(self):
        listed = {m.group(2) or m.group(5) for _, _, c in table_cells() for m in [CELL_RE.match(c)] if m and (m.group(2) or m.group(5))}
        for name in self.all_tests():
            if name.startswith("test_"):
                with self.subTest(test=name):
                    self.assertIn(name, listed)


if __name__ == "__main__":
    unittest.main()
