import contextlib
import copy
import io
import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import sprint_planning as sp  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures" / "sprint-planning"
BANNED = re.compile(r"推奨|妥当|入れられる|達成率|平均|中央値|assignee_ref|u_\w+|🔴|🟢")
MAX_BODY_CHARS = 600


def _load(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _body(text):
    return text.split("\n\n詳細\n", 1)[0]


def _material(history="done-sp.three.json", workdays=9, cache="jira-cache.planning.json"):
    return sp.build_material(_load(cache), _load(history) if history else None, workdays)


class CandidatesTest(unittest.TestCase):
    def test_excludes_done_and_active_sprint_members(self):
        keys = [i["key"] for i in sp.candidates(_load("jira-cache.planning.json")["issues"])]
        self.assertEqual(len(keys), 8)
        for excluded in ("EX-210", "EX-211", "EX-212", "EX-299"):
            self.assertNotIn(excluded, keys)

    def test_sorted_by_priority_then_carried_then_key(self):
        keys = [i["key"] for i in sp.candidates(_load("jira-cache.planning.json")["issues"])]
        self.assertEqual(keys, ["EX-206", "EX-201", "EX-202", "EX-203", "EX-204", "EX-208", "EX-205", "EX-207"])

    def test_carried_comes_before_non_carried_at_same_priority(self):
        issues = _load("jira-cache.planning.json")["issues"]
        carried_high = next(i for i in issues if i["key"] == "EX-201")
        plain_high = next(i for i in issues if i["key"] == "EX-202")
        order = [i["key"] for i in sp.candidates([plain_high, carried_high])]
        self.assertEqual(order, ["EX-201", "EX-202"])

    def test_keys_sort_naturally_not_lexically(self):
        base = _load("jira-cache.planning.json")["issues"][1]
        issues = [dict(base, key=k) for k in ("EX-10", "EX-9")]
        self.assertEqual([i["key"] for i in sp.candidates(issues)], ["EX-9", "EX-10"])

    def test_blocker_is_noted_only_while_blocking_issue_is_not_done(self):
        cache = _load("jira-cache.planning.json")
        self.assertIn("EX-205 low 2SP（ブロッカー有）", _material())
        for i in cache["issues"]:
            if i["key"] == "EX-299":
                i["status_category"] = "done"
        self.assertNotIn("ブロッカー", sp.build_material(cache, _load("done-sp.three.json"), 9))

    def test_flagged_issue_is_noted_as_blocker(self):
        cache = _load("jira-cache.planning.json")
        next(i for i in cache["issues"] if i["key"] == "EX-202")["flagged"] = True
        self.assertIn("EX-202 high 3SP（ブロッカー有）", sp.build_material(cache, _load("done-sp.three.json"), 9))

    def test_blocker_outside_fetched_range_is_unknown_not_assumed_blocked(self):
        cache = _load("jira-cache.planning.json")
        cache["issues"] = [i for i in cache["issues"] if i["key"] != "EX-299"]
        text = sp.build_material(cache, _load("done-sp.three.json"), 9)
        self.assertIn("EX-205 low 2SP（ブロッカー状態不明）", text)
        self.assertNotIn("ブロッカー有", text)


class MaterialTest(unittest.TestCase):
    def test_p1_notice_comes_first_in_body_and_in_incomplete(self):
        body_lines = _body(_material()).split("\n")
        self.assertEqual(body_lines[2], sp.NOTICE)  # 0=試作バナー・1=状態行
        self.assertTrue(sp.build_material(_load("jira-cache.incomplete.json")).startswith(sp.NOTICE))

    def test_p2_no_banned_words_or_numbers_of_prediction(self):
        for hist in ("done-sp.three.json", "done-sp.two.json", None):
            self.assertIsNone(BANNED.search(_material(history=hist)))

    def test_p3_range_is_min_to_max_of_latest_three_by_end_date(self):
        # 古い 40 SP のスプリントは直近 3 件に入らない
        self.assertIn("過去 3 件の完了 SP: 18〜26（予測ではありません）", _material())
        self.assertNotIn("40", _material())

    def test_p3_fewer_than_three_sprints_shows_count_only(self):
        text = _material(history="done-sp.two.json")
        self.assertIn("過去の終了済みスプリント 2 件（3 件未満のため幅は出しません）", text)
        self.assertNotIn("〜", _body(text).split("容量の材料")[1])
        self.assertIn("材料が足りません", text)

    def test_p3_no_history_means_zero_sprints(self):
        self.assertIn("過去の終了済みスプリント 0 件", _material(history=None))

    def test_zero_done_sp_counts_in_range(self):
        history = _load("done-sp.three.json")
        history["sprints"][2] = dict(history["sprints"][2], done_sp=0)
        text = sp.build_material(_load("jira-cache.planning.json"), history, 9)
        self.assertIn("0〜26", text)

    def test_p4_no_assignee_or_person_info(self):
        cache = _load("jira-cache.planning.json")
        for issue in cache["issues"]:
            issue["assignee_ref"] = "u_deadbeef"
        text = sp.build_material(cache, _load("done-sp.three.json"), 9)
        self.assertNotIn("u_deadbeef", text)

    def test_p5_incomplete_cache_has_no_numbers_besides_message(self):
        text = sp.build_material(_load("jira-cache.incomplete.json"), _load("done-sp.three.json"), 9)
        self.assertEqual(text, f"{sp.NOTICE}\n{sp.REFETCH_MESSAGE}")
        self.assertIsNone(re.search(r"\d", text))

    def test_p6_body_within_600_chars_and_candidates_capped(self):
        body = _body(_material())
        self.assertLessEqual(len(body), MAX_BODY_CHARS)
        cache = _load("jira-cache.planning.json")
        base = cache["issues"][1]
        cache["issues"] += [dict(base, key=f"EX-{900 + n}") for n in range(15)]
        text = sp.build_material(cache, _load("done-sp.three.json"), 9)
        self.assertLessEqual(len(_body(text)), MAX_BODY_CHARS)
        self.assertLessEqual(len(re.findall(r"EX-\d+ ", _body(text).split("候補（")[1].split("容量の材料")[0])), 10)
        detail = text.split("\n\n詳細\n", 1)[1]
        self.assertEqual(len(re.findall(r"^  - EX-", detail, re.M)), 23)  # 詳細は全件

    def test_status_word_is_always_caution(self):
        for hist in ("done-sp.three.json", "done-sp.two.json"):
            self.assertIn("🟡 S2", _material(history=hist))

    def test_workdays_shown_as_input_or_unset_and_not_used_to_correct_range(self):
        self.assertIn("稼働日数: 9 日（EM 入力）", _material())
        self.assertIn("稼働日数: 未入力", _material(workdays=None))
        self.assertIn(sp.NOT_CORRECTED, _material())
        self.assertEqual(_material(workdays=5).count("18〜26"), _material(workdays=20).count("18〜26"))

    def test_zero_candidates_says_so(self):
        cache = _load("jira-cache.planning.json")
        cache["issues"] = [i for i in cache["issues"] if i["key"] in ("EX-210", "EX-211")]
        text = sp.build_material(cache, _load("done-sp.three.json"), 9)
        self.assertIn("候補 0 件（未見積もり 0 件）", text)
        self.assertIn("- 候補なし", text)
        self.assertIn("候補が 0 件", text)

    def test_unestimated_count_is_separate_and_total_sp_is_not_shown(self):
        text = _material()
        self.assertIn("未見積もり 2 件", text)
        self.assertNotIn("合計 SP:", text)
        self.assertIn("未見積もりは幅に含まれません", text)
        self.assertIn("未見積もりは幅に含まれない", _body(text))  # 限界の行（33 §4）

    def test_matches_design_sample_shape(self):
        design = (ROOT / "docs" / "design" / "33-sprint-planning-material.md").read_text(encoding="utf-8")
        sample = re.search(r"## 5\. 出力の型.*?```\n(.*?)```", design, re.S).group(1).split("\n")
        body = _body(_material()).split("\n")[1:]
        for index in (1, 2, 4, 6):  # 固定文言・候補の見出し・容量の見出し・EM がやること
            self.assertEqual(body[index], sample[index])


class HistoryValidationTest(unittest.TestCase):
    def _assert_rejected(self, history):
        with self.assertRaises(SystemExit):
            sp.validate_history(history, "ex-proj", "2026-10-09")

    def test_rejects_unknown_keys_that_could_carry_personal_data(self):
        history = copy.deepcopy(_load("done-sp.three.json"))
        history["sprints"][0]["assignee_ref"] = "u_deadbeef"
        self._assert_rejected(history)

    def test_rejects_alias_mismatch_negative_bool_and_bad_date(self):
        base = _load("done-sp.three.json")
        self._assert_rejected(dict(base, project_alias="other"))
        for mutate in ({"done_sp": -1}, {"done_sp": True}, {"done_sp": 1.5}, {"end": "2026/09/25"}):
            history = copy.deepcopy(base)
            history["sprints"][0].update(mutate)
            self._assert_rejected(history)

    def test_rejects_duplicate_sprint_ids(self):
        history = copy.deepcopy(_load("done-sp.three.json"))
        history["sprints"][1]["id"] = history["sprints"][0]["id"]
        self._assert_rejected(history)


class FutureAndEdgeTest(unittest.TestCase):
    def test_rejects_sprint_ending_after_fetch_date_but_accepts_same_day(self):
        history = copy.deepcopy(_load("done-sp.three.json"))
        history["sprints"][0]["end"] = "2026-10-10"
        with self.assertRaises(SystemExit):
            sp.build_material(_load("jira-cache.planning.json"), history, 9)
        history["sprints"][0]["end"] = "2026-10-09"
        self.assertIn("過去 3 件", sp.build_material(_load("jira-cache.planning.json"), history, 9))

    def test_range_note_only_when_range_is_shown(self):
        short = _material(history="done-sp.two.json")
        self.assertNotIn("の最小〜最大です", short)
        self.assertIn("の最小〜最大です", _material())

    def test_empty_issues_gives_zero_candidates_without_error(self):
        cache = dict(_load("jira-cache.planning.json"), issues=[], issue_count=0)
        self.assertIn("候補 0 件（未見積もり 0 件）", sp.build_material(cache, _load("done-sp.three.json"), 9))

    def test_done_and_out_of_range_blockers_mixed_on_one_issue(self):
        cache = _load("jira-cache.planning.json")
        issue = next(i for i in cache["issues"] if i["key"] == "EX-202")
        issue["links"] = [{"link_type": "Blocks", "direction": "inward", "issue_key": "EX-212"},
                          {"link_type": "Blocks", "direction": "inward", "issue_key": "ZZ-1"}]
        self.assertIn("EX-202 high 3SP（ブロッカー状態不明）", sp.build_material(cache, _load("done-sp.three.json"), 9))


class HardeningTest(unittest.TestCase):
    """emh-065: 集計値の鮮度・小数 SP・不正キャッシュ（traceback でなく原因つきメッセージ）。"""

    def _exit_message(self, cache, history=None):
        with self.assertRaises(SystemExit) as ctx:
            sp.build_material(cache, history, 9)
        return str(ctx.exception)

    def test_stale_history_adds_note_but_fresh_does_not(self):
        self.assertNotIn("古い", _material())
        history = _load("done-sp.three.json")
        history["fetched_at"] = "2026-09-01T08:40:00+09:00"
        text = sp.build_material(_load("jira-cache.planning.json"), history, 9)
        self.assertIn("集計値は 38 日前の取得です", text)
        self.assertLessEqual(len(_body(text)), MAX_BODY_CHARS + 60)

    def test_history_at_stale_boundary_has_no_note(self):
        history = _load("done-sp.three.json")
        history["fetched_at"] = "2026-09-25T08:40:00+09:00"  # 14 日前
        self.assertNotIn("日前の取得です", sp.build_material(_load("jira-cache.planning.json"), history, 9))

    def test_rejects_history_with_bad_fetched_at(self):
        history = _load("done-sp.three.json")
        history["fetched_at"] = "yesterday"
        self.assertIn("fetched_at", self._exit_message(_load("jira-cache.planning.json"), history))

    def test_fractional_story_points_are_shown_without_trailing_zero(self):
        cache = _load("jira-cache.planning.json")
        next(i for i in cache["issues"] if i["key"] == "EX-202")["story_points"] = 2.5
        next(i for i in cache["issues"] if i["key"] == "EX-201")["story_points"] = 5.0
        text = sp.build_material(cache, _load("done-sp.three.json"), 9)
        self.assertIn("EX-202 high 2.5SP", text)
        self.assertIn("EX-201 high 5SP", text)
        self.assertNotIn("5.0SP", text)

    def test_rejects_invalid_story_points(self):
        for bad in ("3", True, -1, float("nan")):
            cache = _load("jira-cache.planning.json")
            cache["issues"][0]["story_points"] = bad
            self.assertIn("story_points", self._exit_message(cache), repr(bad))

    def test_malformed_cache_gives_cause_not_traceback(self):
        def broken(mutate):
            cache = _load("jira-cache.planning.json")
            mutate(cache)
            return self._exit_message(cache)
        self.assertIn("issues", broken(lambda c: c.update(issues={"a": 1})))
        self.assertIn("issues", broken(lambda c: c["issues"].__setitem__(0, "EX-1")))
        self.assertIn("sprints", broken(lambda c: c["issues"][0].update(sprints="x")))
        self.assertIn("links", broken(lambda c: c["issues"][0].update(links=[1])))
        self.assertIn("fetched_at", broken(lambda c: c.update(fetched_at=20261009)))
        with self.assertRaises(SystemExit):
            sp.build_material([], None, 9)


class CliTest(unittest.TestCase):
    def test_main_prints_material(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            sp.main([str(FIXTURES / "jira-cache.planning.json"), "--history", str(FIXTURES / "done-sp.three.json"),
                     "--workdays", "9"])
        self.assertEqual(out.getvalue().rstrip("\n"), _material())

    def test_main_rejects_unreadable_input_and_bad_workdays(self):
        with self.assertRaises(SystemExit):
            sp.main([str(FIXTURES / "missing.json")])
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
            sp.main([str(FIXTURES / "jira-cache.planning.json"), "--workdays", "0"])


if __name__ == "__main__":
    unittest.main()
