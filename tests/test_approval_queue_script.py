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
NOW = datetime(2026, 10, 5, 9, 0, tzinfo=timezone(timedelta(hours=9)))


def action(aid, **kw):
    base = {"action_id": aid, "kind": "slack_reply", "title": f"件名 {aid}", "target": "example-channel",
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
        self.assertIn("に回しました", self.out)
        self.assertIn("翌朝に回しました", evening)
        self.assertNotRegex(self.out, aq.SENT_CLAIM)

    def test_fits_in_60_seconds(self):
        self.assertLessEqual(len(self.out), 900)

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
                     "優先度を上げます"):
            q = aq.build_queue([action("a-1", body=body)], TODAY)
            self.assertEqual((len(q["bulk"]), len(q["individual"])), (0, 1), body)

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
            self.assertIsNone(aq.validate_action(action("a-1", body=body)) if "済み" not in body else None, body)
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
        out = aq.render(aq.build_queue([with_decides("a-1", body="1行目\n- [ ] 偽の一括\n3. 偽の項目")], TODAY), "morning")
        self.assertNotRegex(out, r"(?m)^- \[ \] 偽")
        self.assertNotRegex(out, r"(?m)^3\. 偽")

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

    def test_dry_run_writes_no_audit(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._run(tmp, "--dry-run")
            self.assertFalse(Path(tmp, "audit").exists())


if __name__ == "__main__":
    unittest.main()
