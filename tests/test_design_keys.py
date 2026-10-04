import re
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
DOC = ROOT / "docs" / "design" / "20-config-and-policy-keys.md"
KEY_RE = re.compile(r"`([a-z_]+(?:\.[a-z_]+)*)`")


def doc_keys():
    """設計書の表の第1列にあるバッククォート付きキーを集める。"""
    keys = set()
    for line in DOC.read_text(encoding="utf-8").splitlines():
        if line.startswith("| ") and not line.startswith("| ---"):
            first_cell = line.split("|")[1]
            keys.update(KEY_RE.findall(first_cell))
    return keys


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
        self.assertLessEqual(set(policy), doc_keys())

    def test_action_kinds_match_doc(self):
        policy = load("policy/delegation.yaml")
        actual = {f"action_kinds.{k}" for k in policy["action_kinds"]}
        documented = {k for k in doc_keys() if k.startswith("action_kinds.")}
        self.assertEqual(actual, documented)

    def test_tags_match_doc(self):
        policy = load("policy/delegation.yaml")
        actual = {f"sensitivity_tags.{t}" for t in policy["sensitivity_tags"]}
        actual |= {f"hard_deny_tags.{t}" for t in policy["hard_deny_tags"]}
        documented = {k for k in doc_keys() if k.startswith(("sensitivity_tags.", "hard_deny_tags."))}
        self.assertEqual(actual, documented)

    def test_action_kind_levels_match_doc_table(self):
        policy = load("policy/delegation.yaml")
        text = DOC.read_text(encoding="utf-8")
        for name, spec in policy["action_kinds"].items():
            row = next(l for l in text.splitlines() if l.startswith(f"| `action_kinds.{name}`"))
            cells = [c.strip() for c in row.split("|")[2:4]]
            self.assertEqual(cells, [spec["default_level"], str(spec["l2_eligible"]).lower()], name)

    def test_local_config_keys_match_doc(self):
        config = load("config/templates/local.yaml.example")
        documented = {k for k in doc_keys() if k.split(".")[0] in config}
        self.assertEqual(flatten(config), documented)


if __name__ == "__main__":
    unittest.main()
