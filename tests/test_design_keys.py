import re
import sys
import unittest
from datetime import date
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
DOC = ROOT / "docs" / "design" / "20-config-and-policy-keys.md"
sys.path.insert(0, str(ROOT / "scripts"))
import policy_lint as pl  # noqa: E402

KEY_RE = re.compile(r"`([a-z_]+(?:\.[a-z_]+)*)`")


def doc_rows(section_prefix=None):
    """設計書の表の行を返す。section_prefix（例 "## 1."）を渡すとその節の表だけ。"""
    rows, current = [], ""
    for line in DOC.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            current = line
        in_scope = section_prefix is None or current.startswith(section_prefix)
        if in_scope and line.startswith("| ") and not line.startswith("| ---"):
            rows.append([c.strip() for c in line.strip().strip("|").split("|")])
    return rows


def doc_keys(section_prefix=None):
    """表の第1列にあるバッククォート付きキーを集める。"""
    return {k for row in doc_rows(section_prefix) for k in KEY_RE.findall(row[0])}


def flatten(node, prefix=""):
    if not isinstance(node, dict):
        return {prefix} if prefix else set()
    out = set()
    for key, value in node.items():
        out |= flatten(value, f"{prefix}.{key}" if prefix else str(key))
    return out


def load(path):
    return yaml.safe_load((ROOT / path).read_text(encoding="utf-8"))


class DesignKeysTest(unittest.TestCase):
    def test_policy_top_level_keys_are_documented(self):
        policy = load("policy/delegation.yaml")
        self.assertEqual(set(policy), doc_keys("## 1."))

    def test_action_kinds_match_doc(self):
        policy = load("policy/delegation.yaml")
        actual = {f"action_kinds.{k}" for k in policy["action_kinds"]}
        documented = doc_keys("## 2.")
        self.assertEqual(actual, documented)

    def test_tags_match_doc(self):
        policy = load("policy/delegation.yaml")
        actual = {f"sensitivity_tags.{t}" for t in policy["sensitivity_tags"]}
        actual |= {f"hard_deny_tags.{t}" for t in policy["hard_deny_tags"]}
        documented = doc_keys("## 3.")
        self.assertEqual(actual, documented)

    def test_action_kind_levels_match_doc_table(self):
        policy = load("policy/delegation.yaml")
        rows = {row[0]: row for row in doc_rows("## 2.")}
        for name, spec in policy["action_kinds"].items():
            row = rows.get(f"`action_kinds.{name}`")
            self.assertIsNotNone(row, f"{name} が §2 の表に無い")
            self.assertEqual(row[1:3], [spec["default_level"], str(spec["l2_eligible"]).lower()], name)

    def test_policy_rebuilt_from_doc_passes_lint(self):
        """受け入れ基準: docs の表だけから組み立てたポリシーが policy_lint を通る。"""
        action_kinds = {
            row[0].strip("`").removeprefix("action_kinds."): {
                "default_level": row[1],
                "l2_eligible": row[2] == "true",
            }
            for row in doc_rows("## 2.")
            if row[0].startswith("`action_kinds.")
        }
        tag_keys = [k for row in doc_rows("## 3.") for k in KEY_RE.findall(row[0])]
        rebuilt = {
            "version": 1,
            "default": "deny",
            "action_kinds": action_kinds,
            "sensitivity_tags": [k.split(".", 1)[1] for k in tag_keys if k.startswith("sensitivity_tags.")],
            "hard_deny_tags": {k.split(".", 1)[1]: "doc" for k in tag_keys if k.startswith("hard_deny_tags.")},
            "grants": [],
        }
        errors = [f for f in pl.lint(rebuilt, date(2026, 10, 4)) if f.level == "error"]
        self.assertEqual(errors, [])
        actual = load("policy/delegation.yaml")
        self.assertEqual(rebuilt["action_kinds"], {k: {"default_level": v["default_level"], "l2_eligible": v["l2_eligible"]} for k, v in actual["action_kinds"].items()})

    def test_local_config_keys_match_doc(self):
        config = load("config/templates/local.yaml.example")
        documented = doc_keys("## 5.")
        self.assertEqual(flatten(config), documented)


if __name__ == "__main__":
    unittest.main()
