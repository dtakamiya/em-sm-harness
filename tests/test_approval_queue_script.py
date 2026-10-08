import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import approval_queue as aq  # noqa: E402

TODAY = date(2026, 10, 5)
SAMPLE_MAX_CHARS = 900
SAMPLE_MAX_LINES = 30
NOW = datetime(2026, 10, 5, 9, 0, tzinfo=timezone(timedelta(hours=9)))


def action(aid, **kw):
    base = {"action_id": aid, "kind": "minutes", "title": f"件名 {aid}", "target": "example-channel",
            "body": "共有ありがとうございます。", "priority": "medium"}
    return {**base, **kw}


def with_decides(aid, **kw):
    return action(aid, commit_stage="A", em_decides=["期限を置くか（おすすめ: 置かない）"], **kw)


class BuildQueueTest(unittest.TestCase):
    def test_low_risk_without_commit_goes_to_bulk(self):
        q = aq.build_queue([action("a-1")], TODAY)
        self.assertEqual([a["action_id"] for a in q["bulk"]], ["a-1"])
        self.assertEqual(q["individual"], [])

    def test_commit_candidate_goes_to_individual(self):
        q = aq.build_queue([with_decides("a-1")], TODAY)
        self.assertEqual(len(q["individual"]), 1)
        self.assertEqual(q["bulk"], [])

    def test_bulk_title_with_a_stage_word_goes_to_individual(self):
        q = aq.build_queue([action("a-1", title="金曜の定例の議事録を転記")], TODAY)
        self.assertEqual(len(q["individual"]), 1)

    def test_over_limit_is_carried_over_by_priority(self):
        acts = [with_decides(f"a-{i}", priority="low") for i in range(1, 6)] + [with_decides("a-9", priority="high")]
        q = aq.build_queue(acts, TODAY)
        self.assertEqual(len(q["individual"]), aq.MAX_INDIVIDUAL)
        self.assertEqual(q["individual"][0]["action_id"], "a-9")
        self.assertEqual(len(q["carried"]), 1)

    def test_urgent_is_first_and_counted_in_limit(self):
        acts = [with_decides("a-1", priority="high", due="2026-10-04"),
                with_decides("a-2", priority="medium", due="2026-10-01"),
                with_decides("a-3", priority="high", due="2026-10-05")]
        q = aq.build_queue(acts, TODAY)
        self.assertEqual(q["urgent_ids"], {"a-1", "a-3"})
        self.assertEqual([a["action_id"] for a in q["individual"]][:2], ["a-1", "a-3"])

    def test_expired_is_removed_and_listed(self):
        q = aq.build_queue([action("a-1", expires="2026-10-04"), action("a-2", expires="2026-10-05")], TODAY)
        self.assertEqual([a["action_id"] for a in q["expired"]], ["a-1"])
        self.assertEqual([a["action_id"] for a in q["bulk"]], ["a-2"])

    def test_sensitive_never_shows_body(self):
        acts = [action("a-1", sensitive=True, body="機微な本文")]
        q = aq.build_queue(acts, TODAY)
        out = aq.render(q, "morning")
        self.assertNotIn("機微な本文", out)
        self.assertIn("EM 本人対応", out)
        self.assertEqual((q["individual"], q["bulk"]), ([], []))

    def test_does_not_mutate_input(self):
        acts = [with_decides("a-1")]
        before = json.dumps(acts, ensure_ascii=False)
        aq.build_queue(acts, TODAY)
        self.assertEqual(json.dumps(acts, ensure_ascii=False), before)


class RenderTest(unittest.TestCase):
    def setUp(self):
        self.acts = [with_decides("a-1", priority="high", due="2026-10-05"), with_decides("a-2"),
                     action("a-3"), action("a-4", expires="2026-10-01")]
        self.out = aq.render(aq.build_queue(self.acts, TODAY), "morning")

    def test_banner_header_and_sections(self):
        self.assertTrue(self.out.startswith("【下書き・未送信】承認キュー 2026-10-05 朝"))
        self.assertIn("結論: 要判断 2 件 / 一括確認 1 件 / 期限切れ 1 件", self.out)
        for h in ("あなたがやること", "■ 個別承認", "■ 一括確認", "■ 期限切れ"):
            self.assertIn(h, self.out)

    def test_urgent_marker_appears_once_on_the_first_item(self):
        self.assertEqual(self.out.count("【緊急】"), 1)
        self.assertIn("1. 【緊急】", self.out)

    def test_every_individual_item_has_commit_slot_and_bulk_has_none(self):
        ind = self.out.split("■ 個別承認")[1].split("■ 一括確認")[0]
        bulk = self.out.split("■ 一括確認")[1].split("■ 期限切れ")[0]
        self.assertEqual(ind.count("⟦EM が決める⟧"), 2)
        self.assertNotIn("⟦EM", bulk)

    def test_next_slot_label_and_no_sent_claim(self):
        evening = aq.render(aq.build_queue(self.acts, TODAY), "evening")
        self.assertNotIn("に回しました", self.out)  # 持ち越し 0 件の行は出さない
        acts = [with_decides(f"a-{i}") for i in range(1, 7)]
        self.assertIn("ほか 1 件は夕に回しました", aq.render(aq.build_queue(acts, TODAY), "morning"))
        self.assertIn("翌朝に回しました", aq.render(aq.build_queue(acts, TODAY), "evening"))
        self.assertNotRegex(self.out, aq.SENT_CLAIM)

    def test_sample_page_stays_within_char_and_line_budget(self):
        # 「60 秒で読める」の代理指標。時間は測らず、文字数・行数の上限だけで決定的に判定する（実測は 21 §3）
        self.assertLessEqual(len(self.out), SAMPLE_MAX_CHARS)
        self.assertLessEqual(len(self.out.splitlines()), SAMPLE_MAX_LINES)

    def test_empty_queue(self):
        out = aq.render(aq.build_queue([], TODAY), "morning")
        self.assertIn("要判断 0 件 / 一括確認 0 件 / 期限切れ 0 件", out)
        self.assertIn("対応不要", out)


class ReviewRegressionTest(unittest.TestCase):
    """PR #52 レビュー指摘（HIGH 1〜4・MEDIUM）の再発防止。"""

    def test_expired_sensitive_title_is_never_printed(self):
        acts = [action("a-1", sensitive=True, title="機微な件名", expires="2026-10-01")]
        q = aq.build_queue(acts, TODAY)
        out = aq.render(q, "morning")
        self.assertNotIn("機微な件名", out)
        self.assertEqual(q["expired"], [])
        self.assertIn("EM 本人対応", out)

    def test_body_with_commitment_or_deadline_is_not_bulk(self):
        for body in ("確認します。", "金曜にお送りします", "明日までに回答", "10/20 までに共有", "引き取ります",
                     "優先度を上げます", "承知しました", "やります", "送ります", "引き受けます", "間に合わせます",
                     "3日で戻します", "月末の予定です", "来週お願いします"):
            q = aq.build_queue([action("a-1", body=body)], TODAY)
            self.assertEqual((len(q["bulk"]), len(q["individual"])), (0, 1), body)

    def test_bulk_is_allowlist_by_kind(self):
        for kind in ("slack_reply", "jira_comment", "unknown_kind"):
            q = aq.build_queue([action("a-1", kind=kind, body="内容を確認しました。")], TODAY)
            self.assertEqual((len(q["bulk"]), len(q["individual"])), (0, 1), kind)
        for kind in aq.BULK_KINDS:
            q = aq.build_queue([action("a-1", kind=kind)], TODAY)
            self.assertEqual(len(q["bulk"]), 1, kind)

    def test_headline_counts_include_personal_and_rejected_and_never_idle_when_rejected(self):
        q = aq.build_queue([action("p-1", sensitive=True)], TODAY, rejected=2)
        out = aq.render(q, "morning")
        self.assertIn("本人対応 1 件", out.split("\n")[1])
        self.assertIn("除外 2 件", out.split("\n")[1])
        self.assertNotIn("対応不要", out)
        only_rejected = aq.render(aq.build_queue([], TODAY, rejected=1), "morning")
        self.assertNotIn("対応不要", only_rejected)
        self.assertIn("除外 1 件の入力を直す", only_rejected)
        missing = aq.render(aq.build_queue([], TODAY, source_missing=True), "morning")
        self.assertNotIn("対応不要", missing)

    def test_personal_section_is_capped(self):
        acts = [action(f"p-{i}", sensitive=True) for i in range(1, 9)]
        out = aq.render(aq.build_queue(acts, TODAY), "morning")
        self.assertEqual(out.split("■ EM 本人対応")[1].count("\n- minutes"), aq.MAX_PERSONAL)
        self.assertIn("ほか 3 件", out.split("■ EM 本人対応")[1])

    def test_input_limits(self):
        for kw in ({"title": "あ" * (aq.MAX_TITLE_CHARS + 1)}, {"target": "x" * (aq.MAX_TARGET_CHARS + 1)},
                   {"body": "あ" * (aq.MAX_BODY_CHARS + 1)}, {"em_decides": ["a"] * (aq.MAX_DECIDES + 1)},
                   {"em_decides": ["あ" * (aq.MAX_DECIDE_CHARS + 1)]}):
            self.assertIsNotNone(aq.validate_action(action("a-1", **kw)), list(kw))

    def test_worst_case_page_fits_reading_budget(self):
        worst = dict(title="あ" * aq.MAX_TITLE_CHARS, target="x" * aq.MAX_TARGET_CHARS, body="あ" * aq.MAX_BODY_CHARS,
                     em_decides=["あ" * aq.MAX_DECIDE_CHARS] * aq.MAX_DECIDES, commit_stage="A", due="2026-10-05",
                     priority="high")
        acts = ([action(f"i-{i}", **worst) for i in range(9)] + [action(f"b-{i}", title="あ" * aq.MAX_TITLE_CHARS) for i in range(9)]
                + [action(f"e-{i}", title="あ" * aq.MAX_TITLE_CHARS, expires="2026-10-01") for i in range(9)]
                + [action(f"p-{i}", sensitive=True) for i in range(9)])
        out = aq.render(aq.build_queue(acts, TODAY, rejected=3), "morning")
        self.assertLessEqual(len(out), aq.MAX_RENDER_CHARS)

    def test_secret_like_strings_are_rejected(self):
        for body in ("Authorization: Bearer abc.def", "ghp_abc123", "password: x", "www.example.org を見る",
                     "someone@" + "real-company.co.jp へ", "xox" + "b-1234567890-abc", "送っておきました", "更新済み"):
            self.assertIsNotNone(aq.validate_action(action("a-1", body=body)), body)
        self.assertIsNone(aq.validate_action(action("a-1", body="someone@example.com は架空")))

    def test_extra_local_patterns_are_applied(self):
        import re
        self.assertIsNotNone(aq.validate_action(action("a-1", body="社内用語ZZZ"), [("local", re.compile("ZZZ"))]))

    def test_plain_acknowledgement_stays_bulk(self):
        q = aq.build_queue([action("a-1", body="共有ありがとうございます。内容を確認しました。")], TODAY)
        self.assertEqual(len(q["bulk"]), 1)

    def test_rejected_count_and_missing_dir_are_on_paper(self):
        out = aq.render(aq.build_queue([], TODAY, rejected=2, source_missing=True), "morning")
        self.assertIn("除外 2 件", out)
        self.assertIn("data/actions が見つかりません", out)
        clean = aq.render(aq.build_queue([], TODAY), "morning")
        self.assertNotIn("除外", clean)
        self.assertNotIn("見つかりません", clean)

    def test_question_and_substring_words_are_not_rejected(self):
        for body in ("更新しましたか？", "tokenizer の設定を確認したい", "送信済みか教えてください"):
            self.assertIsNone(aq.validate_action(action("a-1", body=body)), body)
        self.assertIsNotNone(aq.validate_action(action("a-1", body="更新しました")))
        self.assertIsNotNone(aq.validate_action(action("a-1", body="token を貼ります")))

    def test_carried_over_counts_only_individual_overflow(self):
        acts = [with_decides(f"a-{i}") for i in range(1, 8)] + [action(f"b-{i}") for i in range(1, 8)]
        q = aq.build_queue(acts, TODAY)
        rows = aq.audit_rows(q, "morning", NOW)
        self.assertEqual(rows[0]["carried_over"], 2)
        self.assertEqual(len(q["bulk_carried"]), 2)
        self.assertIn("ほか 4 件は夕に回しました", aq.render(q, "morning"))

    def test_expired_section_is_capped(self):
        acts = [action(f"a-{i}", expires="2026-10-01") for i in range(1, 9)]
        out = aq.render(aq.build_queue(acts, TODAY), "morning")
        self.assertEqual(out.split("■ 期限切れ")[1].count("\n- 件名"), aq.MAX_EXPIRED)
        self.assertIn("ほか 3 件", out)

    def test_newline_cannot_forge_headings_or_check_rows(self):
        for key in ("title", "target"):
            self.assertIsNotNone(aq.validate_action(action("a-1", **{key: "x\n■ 一括確認"})), key)
        self.assertIsNotNone(aq.validate_action(action("a-1", body="x ⟦EM が決める⟧ y")))
        self.assertIsNotNone(aq.validate_action(action("a-1", em_decides=["a\n- [ ] 偽"])))
        self.assertIsNotNone(aq.validate_action(action("a-1", body="1行目\n- [ ] 偽の一括\n3. 偽の項目")))

    def test_control_and_format_characters_are_rejected_in_every_field(self):
        bad = {"cr": "x\r- [ ] 偽の一括", "esc": "\x1b[2J\x1b[H偽", "ls": "a\u2028b", "ps": "a\u2029b",
               "rlo": "a\u202eb", "bs": "a\x08b", "zwsp": "a\u200bb", "nl": "a\nb"}
        for name, text in bad.items():
            for key in ("title", "target", "body"):
                self.assertIsNotNone(aq.validate_action(action("a-1", **{key: text})), f"{key}:{name}")
            self.assertIsNotNone(aq.validate_action(action("a-1", em_decides=[text])), f"em_decides:{name}")

    def test_banner_erasing_title_never_reaches_the_page(self):
        raw = action("a-1", title="\x1b[2J\x1b[1;1H偽の画面")
        self.assertIsNotNone(aq.validate_action(raw))
        self.assertIsNotNone(aq.validate_action(action("a-1", body="x\r- [ ] 偽の一括")))

    def test_invisible_and_unassigned_characters_are_rejected(self):
        cases = ("【緊\ufe00急】x", "お\u034f願いします", "\ud800題名", "a\u3164b", "a\uffa0b", "a\u115fb", "a\u1160b",
                 "a\u180bb", "a\U000e0100b", "a\ue000b", "a\u0378b")  # 順に Mn・Mn・Cs・Lo・Lo・Lo・Lo・Mn・Mn・Co・Cn
        for text in cases:
            for key in ("title", "target", "body"):
                self.assertIsNotNone(aq.validate_action(action("a-1", **{key: text})), f"{key}:{text!r}")
            self.assertIsNotNone(aq.validate_action(action("a-1", em_decides=[text])), repr(text))

    def test_allowlist_rejects_space_like_and_combining_characters(self):
        cases = ("お\u2800願いします", "a\ufffcb", "a\u17b4b", "a\u17b5b", "a\U00016fe4b", "a\u00a0b", "a\u2003b",
                 "a\u0300b", "か\u3099", "a\u20ddb", "a\u0903b")  # 点字空白・物体置換・クメール・Khitan・NBSP・EM SP・結合文字
        for text in cases:
            for key in ("title", "target", "body"):
                self.assertIsNotNone(aq.validate_action(action("a-1", **{key: text})), f"{key}:{text!r}")

    def test_normal_japanese_text_is_still_accepted(self):
        raw = action("a-1", title="議事録の確定版（第２回）", body="共有ありがとうございます。ＡＢＣ　１２３ → ok", target="example-channel",
                     em_decides=["次回の確認日を決める（おすすめ: 決めない）"])
        self.assertIsNone(aq.validate_action(raw))

    def test_urgent_word_is_banned_in_title_and_em_decides_only(self):
        self.assertIsNotNone(aq.validate_action(action("a-1", title="緊急の件")))
        self.assertIsNotNone(aq.validate_action(action("a-1", em_decides=["緊 急 対応"])))
        self.assertIsNone(aq.validate_action(action("a-1", body="緊急ではありません")))

    def test_lone_surrogate_does_not_crash_loading(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "a.json").write_text('{"action_id":"a-1","kind":"minutes","title":"\\ud800題名","target":"x",'
                                           '"body":"b","priority":"low"}', encoding="utf-8")
            actions, rejected = aq.load_actions(tmp)
        self.assertEqual((actions, len(rejected)), ([], 1))

    def test_urgent_marker_forgery_is_rejected(self):
        for text in ("【緊急】対応", "［緊急］対応", "[緊急] x", "【 緊急 】x", "〔緊急〕x", "〖緊急〗x", "【緊 急】x", "（緊急）x",
                     "【緊急対応】x", "《緊急》x", "「緊急」x", "〘緊急〙x", "【緊\u0300急】x", "緊/急"):
            self.assertIsNotNone(aq.validate_action(action("a-1", title=text)), text)
            self.assertIsNotNone(aq.validate_action(action("a-1", em_decides=[text])), text)

    def test_falsy_or_non_string_dates_are_rejected(self):
        for key in ("due", "expires"):
            for bad in (0, [], False, "", {}, 20261005):
                self.assertIsNotNone(aq.validate_action(action("a-1", **{key: bad})), f"{key}={bad!r}")
            self.assertIsNone(aq.validate_action(action("a-1", **{key: None})))

    def test_twelve_missed_commitment_phrases_are_not_bulk(self):
        bodies = ("担当は田中に変更", "私が対応する", "延期", "優先度を高にする", "１０／２０に出す", "あした出す",
                  "ASAP", "納期は来月", "やっときます", "引き継ぐ", "対応いたしました", "次回に回す")
        self.assertEqual(len(bodies), 12)
        for body in bodies:
            q = aq.build_queue([action("a-1", body=body)], TODAY)
            self.assertEqual((len(q["bulk"]), len(q["individual"])), (0, 1), body)

    def test_urgent_overflow_is_on_the_headline(self):
        acts = [with_decides(f"u-{i}", priority="high", due="2026-10-04") for i in range(1, 8)]
        q = aq.build_queue(acts, TODAY)
        self.assertEqual(q["urgent_carried"], 2)
        self.assertIn("緊急ほか 2 件", aq.render(q, "morning").split("\n")[1])
        self.assertNotIn("緊急ほか", aq.render(aq.build_queue(acts[:5], TODAY), "morning"))

    def test_id_kind_sensitive_validation(self):
        for kw in ({"action_id": "a 1"}, {"action_id": "x" * 33}, {"kind": "Slack Reply"}, {"kind": "a\nb"},
                   {"sensitive": "false"}):
            self.assertIsNotNone(aq.validate_action(action("a-1", **kw)), kw)

    def test_duplicate_id_and_non_utf8_are_excluded_per_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            (d / "a.json").write_text(json.dumps(action("a-1")), encoding="utf-8")
            (d / "b.json").write_text(json.dumps(action("a-1", title="重複")), encoding="utf-8")
            (d / "c.json").write_bytes(b"\xff\xfe\x00bad")
            (d / "d.json").write_text(json.dumps(action("a-4")), encoding="utf-8")
            actions, rejected = aq.load_actions(d)
        self.assertEqual([a["action_id"] for a in actions], ["a-1", "a-4"])
        self.assertEqual(len(rejected), 2)


class ValidateAndLoadTest(unittest.TestCase):
    def test_rejects_bad_inputs(self):
        cases = [[], action("a-1", priority="urgent"), action("a-1", commit_stage="Z"),
                 action("a-1", due="10/05"), action("a-1", body="https://example.com/x"),
                 action("a-1", body="送信しました"), action("a-1", em_decides="x"),
                 {k: v for k, v in action("a-1").items() if k != "body"}]
        for raw in cases:
            self.assertIsNotNone(aq.validate_action(raw), raw)

    def test_accepts_valid(self):
        self.assertIsNone(aq.validate_action(with_decides("a-1", due="2026-10-06")))

    def test_load_skips_broken_and_invalid_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            (d / "a.json").write_text(json.dumps(action("a-1")), encoding="utf-8")
            (d / "b.json").write_text("{broken", encoding="utf-8")
            (d / "c.json").write_text(json.dumps(action("a-3", priority="x")), encoding="utf-8")
            actions, rejected = aq.load_actions(d)
        self.assertEqual([a["action_id"] for a in actions], ["a-1"])
        self.assertEqual(len(rejected), 2)

    def test_missing_dir_is_empty(self):
        self.assertEqual(aq.load_actions(Path("/nonexistent-dir-x")), ([], []))


class AuditAndMainTest(unittest.TestCase):
    def test_audit_rows_have_no_body_and_match_26(self):
        q = aq.build_queue([with_decides("a-1"), action("a-2", body="本文テキスト")], TODAY)
        rows = aq.audit_rows(q, "morning", NOW)
        self.assertEqual(rows[0], {"ts": "2026-10-05T09:00:00+09:00", "event": "queue_rendered", "slot": "morning",
                                   "individual": 1, "bulk": 1, "carried_over": 0})
        self.assertEqual([r["bucket"] for r in rows[1:]], ["individual", "bulk"])
        self.assertEqual(rows[1]["commit_stage"], "A")
        self.assertNotIn("本文テキスト", json.dumps(rows, ensure_ascii=False))

    def _run(self, tmp, *extra):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = aq.main(["--slot", "morning", "--actions-dir", f"{tmp}/actions", "--audit-dir", f"{tmp}/audit",
                            "--now", NOW.isoformat(), *extra])
        return code, out.getvalue(), err.getvalue()

    def test_main_appends_audit_and_reports_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            actions = Path(tmp, "actions")
            actions.mkdir()
            (actions / "a.json").write_text(json.dumps(with_decides("a-1")), encoding="utf-8")
            (actions / "b.json").write_text("{", encoding="utf-8")
            code, out, err = self._run(tmp)
            self._run(tmp)
            lines = Path(tmp, "audit", "2026-10-05.jsonl").read_text(encoding="utf-8").splitlines()
        self.assertEqual(code, 0)
        self.assertIn("要判断 1 件", out)
        self.assertIn("除外: b.json", err)
        self.assertIn("除外 1 件", out)
        self.assertEqual(len(lines), 4)  # 2 回実行 × (queue_rendered + queue_item)

    def test_main_with_missing_actions_dir_says_so(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, out, _ = self._run(tmp, "--dry-run")
        self.assertEqual(code, 0)
        self.assertIn("data/actions が見つかりません", out)

    def test_missing_actions_dir_writes_no_audit(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._run(tmp)
            self.assertFalse(Path(tmp, "audit").exists())

    def test_dry_run_writes_no_audit(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._run(tmp, "--dry-run")
            self.assertFalse(Path(tmp, "audit").exists())


if __name__ == "__main__":
    unittest.main()
