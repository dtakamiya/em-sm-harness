import sys
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import policy_lint as pl  # noqa: E402

TODAY = date(2026, 10, 4)


def base_policy(grants):
    return {
        "version": 1,
        "default": "deny",
        "action_kinds": {
            "slack.send": {"default_level": "L1", "l2_eligible": True},
            "jira.comment": {"default_level": "L1", "l2_eligible": False},
        },
        "sensitivity_tags": ["none", "hr_eval", "escalation_upward"],
        "hard_deny_tags": {"hr_eval": "x", "escalation_upward": "y"},
        "grants": grants,
    }


def good_grant(**over):
    grant = {
        "action": "slack.send",
        "max_level": "L2",
        "tags": ["none"],
        "scope": {"template_id": "weekly-reminder-v1", "recipients": ["team-channel-example"]},
        "until": "2027-01-01",
        "daily_limit": 1,
    }
    return {**grant, **over}


def codes(policy):
    return {f.code for f in pl.lint(policy, TODAY) if f.level == "error"}


class PolicyLintTest(unittest.TestCase):
    def test_empty_grants_is_ok(self):
        self.assertEqual(pl.lint(base_policy([]), TODAY), [])

    def test_valid_grant_is_ok(self):
        self.assertEqual(codes(base_policy([good_grant()])), set())

    def test_grant_touching_hard_deny_tag_is_rejected(self):
        self.assertIn("hard-deny-tag", codes(base_policy([good_grant(tags=["none", "hr_eval"])])))

    def test_grant_without_tags_is_rejected(self):
        grant = good_grant()
        del grant["tags"]
        self.assertIn("tags-missing", codes(base_policy([grant])))

    def test_unknown_tag_is_rejected(self):
        self.assertIn("unknown-tag", codes(base_policy([good_grant(tags=["typo"])])))

    def test_l2_without_scope_is_rejected(self):
        grant = good_grant()
        del grant["scope"]
        self.assertIn("scope-missing", codes(base_policy([grant])))

    def test_scope_without_recipients_is_rejected(self):
        self.assertIn("scope-missing", codes(base_policy([good_grant(scope={"template_id": "t"})])))

    def test_grant_without_until_is_rejected(self):
        grant = good_grant()
        del grant["until"]
        self.assertIn("until-missing", codes(base_policy([grant])))

    def test_invalid_until_is_rejected(self):
        self.assertIn("until-invalid", codes(base_policy([good_grant(until="soon")])))

    def test_expired_grant_is_warning_not_error(self):
        findings = pl.lint(base_policy([good_grant(until="2026-01-01")]), TODAY)
        self.assertEqual([(f.level, f.code) for f in findings], [("warning", "until-expired")])

    def test_ineligible_action_is_rejected(self):
        self.assertIn("action-not-l2-eligible", codes(base_policy([good_grant(action="jira.comment")])))

    def test_unknown_action_is_rejected(self):
        self.assertIn("action-unknown", codes(base_policy([good_grant(action="slack.dm")])))

    def test_max_level_above_l2_is_rejected(self):
        self.assertIn("max-level-invalid", codes(base_policy([good_grant(max_level="L3")])))

    def test_missing_daily_limit_is_warning(self):
        grant = good_grant()
        del grant["daily_limit"]
        self.assertEqual([f.code for f in pl.lint(base_policy([grant]), TODAY)], ["daily-limit-missing"])

    def test_default_must_be_deny(self):
        policy = {**base_policy([]), "default": "allow"}
        self.assertIn("default-not-deny", codes(policy))

    def test_hard_deny_tag_must_be_declared_tag(self):
        policy = {**base_policy([]), "hard_deny_tags": {"ghost": "z"}}
        self.assertIn("hard-deny-unknown-tag", codes(policy))


class RepoPolicyTest(unittest.TestCase):
    def test_shipped_policy_passes_with_no_grants(self):
        policy = pl.load_policy(ROOT / "policy" / "delegation.yaml")
        self.assertEqual(pl.lint(policy, TODAY), [])

    def test_ng_sample_is_rejected(self):
        policy = pl.load_policy(ROOT / "tests" / "fixtures" / "policy" / "ng-grants.yaml")
        self.assertTrue(codes(policy) >= {"hard-deny-tag", "scope-missing", "until-missing"})

    def test_ok_sample_passes(self):
        policy = pl.load_policy(ROOT / "tests" / "fixtures" / "policy" / "ok-grant.yaml")
        self.assertEqual(codes(policy), set())


if __name__ == "__main__":
    unittest.main()
