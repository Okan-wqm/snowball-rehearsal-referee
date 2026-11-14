"""Physical safety paths (tohum/05 "Fiziksel güvenlik", tohum/14, tohum/26c ``targets[].safety_paths``) in
``profile.derive`` and the unit selection that reads it (test 19 and 47's rules, asama-0/09; MF4).

- every word of ``SAFETY_KEYWORDS`` marks a path in any case and component, the path is in ``safety_paths``
  and in ``security_paths`` (the one list the path gates read), and the policy's security keywords do not
  remove it; excluded entries are no safety path;
- an ownership-file owner holding a safety word, and the owner's ``targets[].safety_paths`` patterns, widen
  the derivation (anchored and unanchored; an entry that matches nothing adds nothing); a malformed list or
  pattern is unusable; an empty owner's list narrows nothing;
- unit candidates: a candidate that is a safety or security path, or lies under one, is not eligible
  (``safety_path`` first, else ``security_path``), whatever else holds; one that only holds such a path below
  it, or shares a name prefix with one, stays eligible;
- ``profile.fit`` passes over a guarded candidate to the next one, and ``gate.diffguard`` refuses a change to
  a derived safety path (``security_path:``).
"""

from __future__ import annotations

import os
import shutil
import sys
import unittest

REFEREE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REFEREE)

from gate import diffguard as G  # noqa: E402
from profile import derive as D  # noqa: E402
from profile import fit as F  # noqa: E402
from profile_tree import LOCK_OK, writable_base, write_tree  # noqa: E402
from test_profile_fit import IMAGES, entry, lock, package  # noqa: E402

PKG = {"name": "p", "version": "1.0.0"}
TREE = {
    ".nvmrc": "20\n",
    "package.json": PKG,
    "package-lock.json": LOCK_OK,
    "libs/alarm-core/package.json": PKG,                 # itself a safety path (alarm)
    "apps/plant/package.json": PKG,                       # holds a safety path below it
    "apps/plant/src/PumpDriver.ts": "x",
    "apps/plant/src/view.ts": "x",
    "devices/package.json": PKG,                          # no word: only the owner's list names it
    "devices/motor.ts": "x",
    "devicesx/package.json": PKG,                         # shares the prefix "devices"
    "ops/scada/hmi/package.json": PKG,                    # under a safety path
    "ops/scada/hmi/alarms.ts": "x",                       # a word below a safety path: covered
    "web/tenant-admin/package.json": PKG,                 # under a security path (tenant)
    "web/plain/package.json": PKG,
    "node_modules/valve-lib/index.js": "x",               # excluded: no safety path
    "vendor/oxygen/x.js": "x",                            # excluded by the operator
    "CODEOWNERS": "/rigs/ @farm/Safety-Team\n/web/plain/x.js @org/docs\n",
    "rigs/run.ts": "x",
}
CANDIDATES = ["libs/alarm-core", "apps/plant", "devices", "devicesx", "ops/scada/hmi", "web/tenant-admin",
              "web/plain"]


class Base(unittest.TestCase):
    def setUp(self):
        self.base = writable_base("t-safety-")
        self.addCleanup(shutil.rmtree, self.base, True)
        self.tree = write_tree(os.path.join(self.base, "tree"), TREE)

    def derive(self, safety=None, policy=None, **target):
        t = {"excluded_paths": ["vendor"], "unit_candidates": CANDIDATES}
        if safety is not None:
            t["safety_paths"] = safety
        t.update(target)
        return D.derive(self.tree, t, policy)


class Derivation(Base):
    def test_every_safety_word_marks_a_path_in_both_lists(self):
        words = {"kw/x%sy.js" % w.upper(): "x" for w in D.SAFETY_KEYWORDS}
        write_tree(self.tree, words)
        d = self.derive()
        for path in words:
            self.assertIn(path, d["safety_paths"], path)
            self.assertIn(path, d["security_paths"], path)
        self.assertEqual(d["safety_keywords"], list(D.SAFETY_KEYWORDS))

    def test_topmost_and_excluded(self):
        d = self.derive()
        self.assertIn("libs/alarm-core", d["safety_paths"])
        self.assertIn("ops/scada", d["safety_paths"])
        self.assertNotIn("ops/scada/hmi", d["safety_paths"])         # covered by ops/scada
        self.assertNotIn("ops/scada/hmi/alarms.ts", d["safety_paths"])
        self.assertIn("apps/plant/src/PumpDriver.ts", d["safety_paths"])
        self.assertNotIn("apps/plant/src/view.ts", d["safety_paths"])
        self.assertFalse([p for p in d["safety_paths"] if p.startswith(("node_modules", "vendor"))])
        self.assertNotIn("web/tenant-admin", d["safety_paths"])      # a security word, not a safety one

    def test_policy_security_keywords_do_not_remove_safety_paths(self):
        d = self.derive(policy={"constitutional": {"security_keywords": ["nothing-here"]}})
        self.assertIn("libs/alarm-core", d["security_paths"])
        self.assertNotIn("web/tenant-admin", d["security_paths"])

    def test_ownership_file_owner_with_a_safety_word(self):
        d = self.derive()
        self.assertIn("rigs", d["safety_paths"])
        self.assertIn("rigs", d["security_paths"])
        self.assertNotIn("web/plain/x.js", d["safety_paths"])
        self.assertNotIn("/rigs/", d["security_owner_patterns"])  # that list holds security owners only

    def test_the_owners_list_widens(self):
        self.assertNotIn("devices", self.derive()["safety_paths"])
        d = self.derive(["/devices", "**/motor.ts", "not/in/tree"])
        self.assertIn("devices", d["safety_paths"])
        self.assertIn("devices", d["security_paths"])
        self.assertNotIn("devicesx", d["safety_paths"])
        self.assertFalse([p for p in d["safety_paths"] if p.startswith("not")])
        unanchored = self.derive(["motor.ts"])
        self.assertIn("devices/motor.ts", unanchored["safety_paths"])

    def test_an_empty_owners_list_narrows_nothing(self):
        self.assertEqual(self.derive([])["safety_paths"], self.derive()["safety_paths"])

    def test_malformed_owners_list_is_unusable(self):
        for bad in ("devices", [1], [""], ["/"], ["[z-a]"]):
            with self.assertRaises(D.DeriveError, msg=repr(bad)):
                self.derive(bad)

    def test_check_refuses_a_proposal_that_drops_a_safety_path(self):
        d = self.derive()
        proposal = {"safety_paths": [p for p in d["safety_paths"] if p != "rigs"]}
        self.assertEqual(D.check(d, proposal)["reasons"], ["differs:safety_paths"])
        self.assertEqual(D.check(d, {"safety_paths": d["safety_paths"]})["reasons"], [])


class Candidates(Base):
    def reasons(self, d):
        return {c["path"]: c["reasons"] for c in d["unit_candidates"]}

    def test_guarded_candidates_are_not_eligible(self):
        got = self.reasons(self.derive())
        self.assertEqual(got["libs/alarm-core"], ["safety_path"])
        self.assertEqual(got["ops/scada/hmi"], ["safety_path"])
        self.assertEqual(got["web/tenant-admin"], ["security_path"])
        self.assertEqual(got["apps/plant"], [])      # holds PumpDriver.ts below it: the gates guard that file
        self.assertEqual(got["devices"], [])
        self.assertEqual(got["web/plain"], [])

    def test_the_owners_list_guards_a_candidate_and_not_its_prefix_sibling(self):
        got = self.reasons(self.derive(["/devices"]))
        self.assertEqual(got["devices"], ["safety_path"])
        self.assertEqual(got["devicesx"], [])

    def test_guarded_by_order_and_root(self):
        d = {"safety_paths": ["a/pump"], "security_paths": ["a", "a/pump"]}
        self.assertEqual(D.guarded_by(d, "a/pump/x"), "safety_path")
        self.assertEqual(D.guarded_by(d, "a/Pump"), "safety_path")   # covers is casefolded
        self.assertEqual(D.guarded_by(d, "a/b"), "security_path")
        self.assertIsNone(D.guarded_by(d, "."))
        self.assertIsNone(D.guarded_by(d, "ab"))

    def test_a_guarded_candidate_keeps_its_other_reasons(self):
        got = self.reasons(self.derive(excluded_paths=["vendor", "libs"]))
        self.assertEqual(got["libs/alarm-core"], ["excluded"])  # excluded: not derived, so not guarded either
        write_tree(self.tree, {"pumps/x.js": "x"})
        got = self.reasons(self.derive(unit_candidates=["pumps"]))
        self.assertEqual(got["pumps"], ["safety_path"])  # the package checks run only on an otherwise clean path


class Selection(unittest.TestCase):
    def setUp(self):
        self.base = writable_base("t-safety-fit-")
        self.addCleanup(shutil.rmtree, self.base, True)
        self.tree = write_tree(os.path.join(self.base, "tree"), {
            ".nvmrc": "v20.11.1\n",
            "package-lock.json": lock(**{"node_modules/eslint": entry("eslint", bin={"eslint": "bin/eslint.js"})}),
            "package.json": package({}, devDependencies={"eslint": "9"}),
            "pkgs/aerator-ctl/package.json": package(),
            "pkgs/good/package.json": package(),
        })

    def test_fit_passes_over_a_safety_candidate(self):
        report = F.fit(self.tree, {"unit_candidates": ["pkgs/aerator-ctl", "pkgs/good"]}, None, IMAGES)
        self.assertEqual(report["fit"], ["pkgs/good"])
        first = report["rows"][0]
        self.assertEqual(first["path"], "pkgs/aerator-ctl")
        self.assertTrue([r for r in first["reasons"] if "unit_not_eligible" in r], first["reasons"])

    def test_fit_without_the_word_takes_the_first_unless_the_owner_names_it(self):
        os.rename(os.path.join(self.tree, "pkgs/aerator-ctl"), os.path.join(self.tree, "pkgs/rig"))
        target = {"unit_candidates": ["pkgs/rig", "pkgs/good"]}
        self.assertEqual(F.fit(self.tree, target, None, IMAGES)["fit"], ["pkgs/rig", "pkgs/good"])
        self.assertEqual(F.fit(self.tree, dict(target, safety_paths=["pkgs/rig"]), None, IMAGES)["fit"],
                         ["pkgs/good"])

    def test_diffguard_refuses_a_change_to_a_derived_safety_path(self):
        d = D.derive(self.tree, {"unit_candidates": []})
        profile = {"security_paths": d["security_paths"], "excluded_dirs": d["excluded_dirs"]}
        diff = ("diff --git a/pkgs/aerator-ctl/package.json b/pkgs/aerator-ctl/package.json\n"
                "--- a/pkgs/aerator-ctl/package.json\n+++ b/pkgs/aerator-ctl/package.json\n"
                "@@ -1 +1 @@\n-a\n+b\n")
        reasons = G.check(diff, profile, {"inputs": ["pkgs/"]})
        self.assertIn("security_path:pkgs/aerator-ctl/package.json", reasons)


if __name__ == "__main__":
    unittest.main()
