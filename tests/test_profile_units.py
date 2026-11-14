"""Test 47 (asama-0/09) and group ``profile`` (tohum/29d): unit candidates and excluded paths are derived;
agent configuration is excluded everywhere and case-insensitively, the operator's ``excluded_paths`` too;
a proposal that narrows the list, or a recipe that reaches into it, is refused.

- every one of the seven agent configuration names, in other cases and at any depth, file or directory,
  is listed in ``excluded_paths``, adds no language, test rule or security path, and ``excluded`` says so
  for paths not in the tree as well;
- unit candidates: the operator's order, or ``package.json`` directories; each static reason;
- ``check`` on recipes: eligible path, inputs not excluded, inputs cover the unit, recipe fields only.
"""

from __future__ import annotations

import copy
import os
import shutil
import sys
import unittest

REFEREE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REFEREE)

from profile import derive as D  # noqa: E402
from profile_tree import LOCK_OK, writable_base, write_tree  # noqa: E402

AGENT_FILES = {
    ".Claude/settings.json": "x",
    ".claude/auth.js": "x",
    "sub/claude.MD": "x",
    "deep/a/b/Agents.md": "x",
    ".MCP.json": "{}",
    ".VSCode/x.test.js": "x",
    "svc/.ENVRC": "x",
    ".devContainer/token.py": "x",
    "pkgs/web/CLAUDE.md/inner.ts": "x",
}

BASE = {
    "package.json": {"name": "toy"},
    "package-lock.json": LOCK_OK,
    ".nvmrc": "20\n",
    "src/index.js": "x",
    "pkgs/web/package.json": {"name": "web"},
    "pkgs/api/package.json": {"name": "api"},
    "pkgs/api/package-lock.json": {"lockfileVersion": 1, "dependencies": {}},
    "pkgs/old/package.json": "{ not json",
    "pkgs/nolock/x.js": "x",
    "node_modules/dep/package.json": {"name": "dep"},
    "vendor/pkg/package.json": {"name": "v"},
    ".claude/pkg/package.json": {"name": "agent"},
}


def recipe(path=".", inputs=None, **extra):
    unit = {"unit_id": "u1", "path": path, "inputs": inputs if inputs is not None else [path],
            "toolchain": "node", "env_image": "node:20@sha256:" + "0" * 64, "lockfiles": ["package-lock.json"],
            "install_scripts_required": [], "lint_cmd": ["npx", "eslint", "."], "test_cmd": ["npm", "test"],
            "affected_test_cmd": [], "services": [], "limits": {}}
    unit.update(extra)
    return unit


class UnitsTest(unittest.TestCase):
    def setUp(self):
        self.base = writable_base("t-units-")
        self.addCleanup(shutil.rmtree, self.base, True)
        self.tree = write_tree(os.path.join(self.base, "tree"), dict(BASE, **AGENT_FILES))
        self.target = {"excluded_paths": ["vendor"], "unit_candidates": []}

    def derive(self, target=None):
        return D.derive(self.tree, self.target if target is None else target)

    # ------------------------------------------------------------ agent configuration

    def test_agent_config_everywhere_any_case(self):
        d = self.derive()
        # .claude is covered by .Claude: entries are compared after casefold
        want = {".Claude", "sub/claude.MD", "deep/a/b/Agents.md", ".MCP.json", ".VSCode", "svc/.ENVRC",
                ".devContainer", "pkgs/web/CLAUDE.md"}
        self.assertEqual(set(d["excluded_paths"]) - {"vendor"}, want)
        self.assertEqual(d["languages"], {"javascript": {"files": 2}})  # src/index.js, pkgs/nolock/x.js
        self.assertEqual(d["test_path_rules"], [])
        self.assertEqual(d["security_paths"], [])  # .claude/auth.js and .devContainer/token.py are excluded
        for name in D.AGENT_CONFIG:
            for spelled in (name, name.upper(), name.swapcase()):
                for path in (spelled, "a/" + spelled, "a/b/" + spelled + "/c.js"):
                    self.assertEqual(D.excluded(d, path), "agent_config", path)
        self.assertIsNone(D.excluded(d, "src/claude.js"))
        self.assertIsNone(D.excluded(d, "docs/AGENTS.md.txt"))

    def test_symlink_to_agent_config_is_agent_config(self):
        self.add({"docs/notes.md": ("symlink", "../sub/claude.MD"), "docs/cfg": ("symlink", "..\\.Claude"),
                  "docs/auth-ok.js": ("symlink", "../src/index.js")})
        d = self.derive()
        self.assertIn("docs/notes.md", d["excluded_paths"])
        self.assertIn("docs/cfg", d["excluded_paths"])
        self.assertNotIn("docs/auth-ok.js", d["excluded_paths"])
        self.assertEqual(D.check(d, {"excluded_paths": [e for e in d["excluded_paths"] if e != "docs/notes.md"]})
                         ["reasons"], ["narrowed:excluded_paths:docs/notes.md"])

    def test_operator_excluded_paths_are_carried_and_excluded(self):
        d = self.derive()
        self.assertIn("vendor", d["excluded_paths"])
        self.assertEqual(D.excluded(d, "x/Vendor/y.js"), "excluded_path")
        d2 = self.derive({"excluded_paths": [], "unit_candidates": []})
        self.assertNotIn("vendor", d2["excluded_paths"])
        self.assertIsNone(D.excluded(d2, "vendor/pkg"))
        with self.assertRaises(D.DeriveError):
            self.derive({"excluded_paths": ["/"], "unit_candidates": []})

    def test_proposal_dropping_any_excluded_path_is_refused(self):
        d = self.derive()
        for entry in d["excluded_paths"]:
            narrowed = [e for e in d["excluded_paths"] if e != entry]
            self.assertEqual(D.check(d, {"excluded_paths": narrowed})["reasons"],
                             ["narrowed:excluded_paths:%s" % entry], entry)
        self.assertTrue(D.check(d, {"excluded_paths": [e.upper() for e in d["excluded_paths"]]})["ok"])
        self.assertEqual(D.check(d, {"agent_config": list(D.AGENT_CONFIG[1:])})["reasons"], ["differs:agent_config"])

    # ------------------------------------------------------------ unit candidates

    def test_default_candidates_are_package_dirs_not_excluded(self):
        got = {c["path"]: c["reasons"] for c in self.derive()["unit_candidates"]}
        # pkgs/old and pkgs/web use the root lock and .nvmrc; pkgs/api its own v1 lock; node_modules/dep,
        # vendor/pkg and .claude/pkg are excluded, so they are not candidates
        self.assertEqual(got, {".": [], "pkgs/api": ["lock_v1_unsupported"], "pkgs/old": ["package_json_unparsable"],
                               "pkgs/web": []})

    def test_operator_candidates_keep_order_and_reasons(self):
        self.add({"pkgs/linked": ("symlink", "web"), "pkgs/web/package-lock.json": {"lockfileVersion": 3,
                  "packages": {"": {}, "node_modules/a": {"version": "1"}}}})
        self.target["unit_candidates"] = ["vendor/pkg", ".claude/pkg", "../up", "pkgs/linked", "pkgs/nolock",
                                          "src/index.js", "pkgs/web", "pkgs/api", "./pkgs/../"]
        got = [(c["path"], c["eligible"], c["reasons"]) for c in self.derive()["unit_candidates"]]
        self.assertEqual(got, [
            ("vendor/pkg", False, ["excluded"]),
            (".claude/pkg", False, ["excluded"]),
            ("../up", False, ["path_invalid"]),
            ("pkgs/linked", False, ["path_symlink"]),
            ("pkgs/nolock", False, ["no_package_json"]),
            ("src/index.js", False, ["not_a_directory"]),
            ("pkgs/web", False, ["lock_without_integrity"]),
            ("pkgs/api", False, ["lock_v1_unsupported"]),
            (".", True, []),
        ])

    def add(self, files):
        write_tree(self.tree, files)

    def test_version_file_and_lock_rules(self):
        os.remove(os.path.join(self.tree, ".nvmrc"))
        self.target["unit_candidates"] = ["."]
        self.assertEqual(self.derive()["unit_candidates"][0]["reasons"], ["no_version_file"])
        self.add({".nvmrc": "  \n"})
        self.assertEqual(self.derive()["unit_candidates"][0]["reasons"], ["no_version_file"])
        os.remove(os.path.join(self.tree, ".nvmrc"))
        self.add({".tool-versions": "python 3.12\nnodejs 20.11.1\n"})
        self.assertTrue(self.derive()["unit_candidates"][0]["eligible"])
        os.remove(os.path.join(self.tree, "package-lock.json"))
        self.assertEqual(self.derive()["unit_candidates"][0]["reasons"], ["no_lockfile"])
        bad = copy.deepcopy(LOCK_OK)
        del bad["packages"]["node_modules/left-pad"]["integrity"]
        self.add({"npm-shrinkwrap.json": bad})
        self.assertEqual(self.derive()["unit_candidates"][0]["reasons"], ["lock_without_integrity"])
        self.add({"npm-shrinkwrap.json": "[1]"})
        self.assertEqual(self.derive()["unit_candidates"][0]["reasons"], ["lock_unparsable"])
        os.remove(os.path.join(self.tree, "npm-shrinkwrap.json"))
        write_tree(self.base, {"elsewhere.json": LOCK_OK})
        self.add({"package-lock.json": ("symlink", os.path.join(self.base, "elsewhere.json"))})
        self.assertEqual(self.derive()["unit_candidates"][0]["reasons"], ["lock_not_regular"])

    def test_lock_and_version_file_found_in_ancestor(self):
        self.add({"pkgs/web/x.js": "x"})
        self.target["unit_candidates"] = ["pkgs/web"]
        self.assertEqual(self.derive()["unit_candidates"][0], {"path": "pkgs/web", "eligible": True, "reasons": []})

    # ------------------------------------------------------------ recipes

    def test_recipe_checks(self):
        d = self.derive()
        self.assertEqual(D.check(d, {"units": [recipe()]}), {"ok": True, "reasons": []})
        self.assertEqual(D.check(d, [recipe(inputs=["src", "package.json", "."])])["reasons"], [])
        cases = [
            (recipe("pkgs/api"), ["units[0]:unit_not_eligible:pkgs/api"]),
            (recipe("pkgs/nolock"), ["units[0]:unit_not_candidate:pkgs/nolock"]),
            (recipe("/abs"), ["units[0]:path_invalid", "units[0]:input_invalid:/abs"]),
            (recipe(inputs=[".", ".claude/settings.json"]), ["units[0]:input_excluded:.claude/settings.json"]),
            (recipe(inputs=[".", "sub/CLAUDE.md"]), ["units[0]:input_excluded:sub/CLAUDE.md"]),
            (recipe(inputs=[".", "vendor/pkg"]), ["units[0]:input_excluded:vendor/pkg"]),
            (recipe(inputs=[".", "node_modules"]), ["units[0]:input_excluded:node_modules"]),
            (recipe(inputs=[".", "../x"]), ["units[0]:input_invalid:../x"]),
            (recipe(inputs=["src"]), ["units[0]:inputs_miss_unit_path"]),
            (recipe(inputs=[]), ["units[0]:malformed:inputs"]),
            (recipe(excluded_paths=[]), ["units[0]:field_not_in_recipe:excluded_paths"]),
            (recipe(security_paths=[]), ["units[0]:field_not_in_recipe:security_paths"]),
        ]
        for unit, want in cases:
            self.assertEqual(D.check(d, {"units": [unit]})["reasons"], want, unit)
        self.assertEqual(D.check(d, {"units": []})["reasons"], ["malformed:units"])

    def test_recipe_inputs_exist_without_symlink(self):
        outside = write_tree(os.path.join(self.base, "outside"), {"x.js": "x"})
        self.add({"src/out": ("symlink", outside)})
        d = self.derive()
        unit = recipe(inputs=[".", "src/out/x.js", "src/gone", "src/index.js"])
        self.assertEqual(D.check(d, {"units": [unit]}, self.tree)["reasons"],
                         ["units[0]:input_symlink:src/out/x.js", "units[0]:input_missing:src/gone"])
        self.assertTrue(D.check(d, {"units": [unit]})["ok"])  # without the tree only the paths are judged

    def test_check_recipe_with_tree(self):
        d = self.derive()
        for unit, ok in ((recipe(), True), (recipe(inputs=[".", "CLAUDE.md"]), False)):
            self.assertEqual(D.check(d, {"units": [unit]}, self.tree)["ok"], ok, unit)


if __name__ == "__main__":
    unittest.main()
