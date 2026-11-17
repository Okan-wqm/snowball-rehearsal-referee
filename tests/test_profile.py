"""Test 19 (asama-0/09) and group ``profile`` (tohum/29d): the profile is derived again and a proposal
that differs from it, or narrows it, is refused.

- languages by extension, excluded entries not counted, symlinks not followed;
- security paths by keyword substring (casefolded, any component, topmost path kept) and by an
  ownership-file line whose owner holds a keyword; the policy's keywords replace the default ones;
- excluded directories, the operator's patterns, test path rules and inline Rust tests;
- ``check``: an equal proposal passes; each field narrowed or widened is refused; ``excluded_paths`` may
  only widen; a field the derivation does not produce is refused;
- unusable input (a pattern that does not compile, in the target or in an ownership file; a policy of the
  wrong shape) is a ``DeriveError``; a tree deeper than Python's recursion limit is walked;
- the command line, the seed's vector interface (tohum/29f ``profile``), in ``VectorTest``: each named
  case and a one-field variant that must not give the same result, coverage boundaries, trailing ``/``,
  widening accepted, unusable input exit 2 with one JSON line and no traceback, any other exception in
  ``main`` exit 2, not a refusal.
"""

from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import sys
import unittest
from unittest import mock

REFEREE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REFEREE)

from profile import derive as D  # noqa: E402
import refusal  # noqa: E402
import tarfile  # noqa: E402

from profile_tree import LOCK_OK, writable_base, write_tar, write_tree  # noqa: E402

TREE = {
    "package.json": {"name": "toy"},
    "package-lock.json": LOCK_OK,
    ".nvmrc": "20.11.1\n",
    "src/auth/login.js": "x",
    "src/auth/deep/more.js": "x",
    "src/Session.TS": "x",
    "src/util.js": "x",
    "src/util.test.js": "x",
    "lib/helpers.js": "x",
    "lib/plain.py": "x",
    "tests/a.py": "x",
    "go/x_test.go": "x",
    "go/x.go": "x",
    "rs/lib.rs": "fn a() {}\n#[cfg(test)]\nmod t {}\n",
    "rs/other.rs": "fn b() {}\n",
    "rs/spaced.rs": "# [ cfg( all(test, unix) ) ]\nmod t {}\n",
    "rs/attr.rs": "#[test]\nfn t() {}\n",
    "rs/feature.rs": "#[cfg(feature = \"tests\")]\nfn f() {}\n",
    "README": "no extension",
    "notes.txt": "x",
    "node_modules/auth-lib/index.js": "x",
    "pkg/dist/bundle.js": "x",
    "vendor/token.js": "x",
    "a/vendor/b.js": "x",
    "legacy/old.js": "x",
    "legacy/keep.ts": "x",
    ".github/CODEOWNERS": "# owners\n/lib/ @org/Security-Team\n*.md @org/docs\nhelpers.py @org/auth-guild\n"
                          "/go/ @org/web @org/payments-oncall\n",
}


class ProfileTest(unittest.TestCase):
    def setUp(self):
        self.base = writable_base("t-profile-")
        self.addCleanup(shutil.rmtree, self.base, True)
        self.tree = write_tree(os.path.join(self.base, "tree"), TREE)
        self.target = {"excluded_paths": ["vendor", "/legacy/*.js"], "unit_candidates": []}

    def derive(self, **kw):
        return D.derive(self.tree, kw.get("target", self.target), kw.get("policy"))

    def add(self, files):
        write_tree(self.tree, files)

    # ------------------------------------------------------------ languages

    def test_languages_by_extension_excluded_not_counted(self):
        d = self.derive()
        # js: src/auth/login.js, src/auth/deep/more.js, src/util.js, src/util.test.js, lib/helpers.js;
        # not node_modules, pkg/dist, vendor, a/vendor, legacy/old.js (operator), nor README/notes.txt.
        self.assertEqual(d["languages"], {"javascript": {"files": 5}, "typescript": {"files": 2},
                                          "python": {"files": 2}, "go": {"files": 2}, "rust": {"files": 5}})

    def test_symlinks_not_followed_or_counted(self):
        outside = write_tree(os.path.join(self.base, "outside"), {"x1.js": "x", "x2.js": "x", "secret.c": "x"})
        self.add({"link-dir": ("symlink", outside), "link.js": ("symlink", "src/util.js")})
        d = self.derive()
        self.assertEqual(d["languages"]["javascript"], {"files": 5})
        self.assertNotIn("c", d["languages"])
        self.assertFalse(any("link-dir/" in p for p in d["security_paths"]))

    # ------------------------------------------------------------ security paths

    def test_security_paths_keyword_topmost_and_casefold(self):
        d = self.derive()
        self.assertIn("src/auth", d["security_paths"])
        self.assertIn("src/Session.TS", d["security_paths"])
        self.assertNotIn("src/auth/login.js", d["security_paths"])  # covered by src/auth
        self.assertNotIn("src/util.js", d["security_paths"])
        # excluded entries are not security paths: node_modules/auth-lib, vendor/token.js
        self.assertFalse(any(p.startswith(("node_modules", "vendor")) for p in d["security_paths"]))

    def test_every_default_keyword_marks_a_path(self):
        for word in D.SECURITY_KEYWORDS:
            self.add({"kw/x%sy.js" % word.upper(): "x"})
        d = self.derive()
        for word in D.SECURITY_KEYWORDS:
            self.assertIn("kw/x%sy.js" % word.upper(), d["security_paths"], word)

    def test_symlink_named_by_keyword_is_security_path(self):
        self.add({"src/guards": ("symlink", "util.js")})
        self.assertIn("src/guards", self.derive()["security_paths"])

    def test_policy_keywords_replace_default(self):
        d = self.derive(policy={"constitutional": {"security_keywords": ["UTIL"]}})
        self.assertIn("src/util.js", d["security_paths"])
        self.assertNotIn("src/auth", d["security_paths"])
        self.assertEqual(d["security_keywords"], ["util"])
        with self.assertRaises(D.DeriveError):
            self.derive(policy={"constitutional": {"security_keywords": []}})

    def test_ownership_file_owner_with_keyword(self):
        d = self.derive()
        self.assertIn("lib", d["security_paths"])             # /lib/ @org/Security-Team
        self.assertIn("go", d["security_paths"])              # second owner holds "payment"
        self.assertEqual(d["security_owner_patterns"], ["/go/", "/lib/", "helpers.py"])
        self.assertNotIn("README", d["security_paths"])       # *.md @org/docs: no keyword
        self.add({"x/y/helpers.py": "x"})                     # unanchored: any depth
        self.assertIn("x/y/helpers.py", self.derive()["security_paths"])

    def test_ownership_file_symlink_not_read(self):
        os.remove(os.path.join(self.tree, ".github/CODEOWNERS"))
        write_tree(self.base, {"own": "/src/ @org/security\n"})
        self.add({"CODEOWNERS": ("symlink", os.path.join(self.base, "own"))})
        self.assertEqual(self.derive()["security_owner_patterns"], [])

    # ------------------------------------------------------------ excluded, tests

    def test_excluded_dirs_and_operator_patterns(self):
        d = self.derive()
        self.assertEqual(d["excluded_dirs"], ["node_modules", "pkg/dist"])
        self.assertEqual(d["excluded_paths"], ["/legacy/*.js", "vendor"])
        self.assertEqual(D.excluded(d, "a/vendor/b.js"), "excluded_path")
        self.assertEqual(D.excluded(d, "LEGACY/old.js"), "excluded_path")
        self.assertIsNone(D.excluded(d, "legacy/keep.ts"))
        self.assertIsNone(D.excluded(d, "legacy/sub/old.js"))  # * does not cross /
        self.assertEqual(D.excluded(d, "x/Node_Modules/y.js"), "excluded_dir")
        self.assertIsNone(D.excluded(d, "src/util.js"))

    def test_test_path_rules_and_inline_rust(self):
        d = self.derive()
        self.assertEqual(d["test_path_rules"], ["**/*.test.*", "**/*_test.go", "**/tests/**", "rs/attr.rs",
                                                "rs/lib.rs", "rs/spaced.rs"])

    def test_unreadable_directory_stops_derivation(self):
        real = os.listdir

        def listdir(path):
            if path.endswith(os.sep + "src"):
                raise PermissionError(13, "Permission denied")
            return real(path)
        with mock.patch.object(D.os, "listdir", listdir):
            with self.assertRaises(D.DeriveError):
                self.derive()

    def test_pattern_syntax(self):
        cases = [("vendor", "a/vendor/x", True), ("/vendor", "a/vendor", False), ("/vendor", "vendor/x", True),
                 ("a/*.js", "a/b.js", True), ("a/*.js", "a/b/c.js", False), ("a/**/c.js", "a/b/d/c.js", True),
                 ("**/c.js", "c.js", True), ("x?.js", "xy.js", True), ("x[ab].js", "xb.js", True),
                 ("x[!ab].js", "xb.js", False), ("docs/", "docs", True), ("Docs", "dOCS/x", True)]
        for pattern, path, want in cases:
            self.assertEqual(D.pattern_matches(pattern, path), want, (pattern, path))

    # ------------------------------------------------------------ check

    def proposal(self, d):
        return {k: (list(d[k]) if k != "languages" else dict(d[k])) for k in D.PROPOSABLE if k != "units"}

    def test_equal_proposal_passes(self):
        d = self.derive()
        self.assertEqual(D.check(d, self.proposal(d)), {"ok": True, "reasons": []})

    def test_each_field_narrowed_or_widened_is_refused(self):
        d = self.derive()
        for field in D.SET_FIELDS:
            for change in ("narrow", "widen"):
                p = self.proposal(d)
                if change == "narrow":
                    if not p[field]:
                        continue
                    p[field] = p[field][1:]
                else:
                    p[field] = p[field] + ["zz/extra"]
                report = D.check(d, p)
                self.assertFalse(report["ok"], (field, change))
                self.assertEqual(report["reasons"], ["differs:%s" % field], (field, change))
        p = self.proposal(d)
        p["languages"] = {k: v for k, v in p["languages"].items() if k != "rust"}
        self.assertEqual(D.check(d, p)["reasons"], ["differs:languages"])
        p["languages"] = dict(d["languages"], cobol={"files": 1})
        self.assertEqual(D.check(d, p)["reasons"], ["differs:languages"])

    def test_security_path_replaced_by_narrower_child_is_refused(self):
        d = self.derive()
        p = self.proposal(d)
        p["security_paths"] = [x for x in p["security_paths"] if x != "src/auth"] + ["src/auth/login.js"]
        self.assertEqual(D.check(d, p)["reasons"], ["differs:security_paths"])

    def test_excluded_paths_only_widen(self):
        d = self.derive()
        p = {"excluded_paths": d["excluded_paths"] + ["more"]}
        self.assertTrue(D.check(d, p)["ok"])
        p = {"excluded_paths": ["vendor"]}
        self.assertEqual(D.check(d, p)["reasons"], ["narrowed:excluded_paths:/legacy/*.js"])
        # anchoring "vendor" (any depth) to "/vendor" (root only) narrows it
        p = {"excluded_paths": ["/vendor", "/legacy/*.js"]}
        self.assertEqual(D.check(d, p)["reasons"], ["narrowed:excluded_paths:vendor"])
        # a wider directory covers an anchored path below it; a pattern is kept only as written
        self.add({"sub/CLAUDE.md": "x"})
        d = self.derive()
        self.assertTrue(D.check(d, {"excluded_paths": ["vendor", "/legacy/*.js", "sub"]})["ok"])
        self.assertFalse(D.check(d, {"excluded_paths": ["vendor", "/legacy/*", "sub"]})["ok"])

    def test_unknown_and_malformed_fields_are_refused(self):
        d = self.derive()
        self.assertEqual(D.check(d, {"banned_constructs": {}})["reasons"], ["field_not_derived:banned_constructs"])
        self.assertEqual(D.check(d, {"security_paths": "src"})["reasons"], ["malformed:security_paths"])
        self.assertEqual(D.check(d, "x")["reasons"], ["malformed:proposal"])

    # ------------------------------------------------------------ unusable input: exit 2, never a traceback

    def test_invalid_pattern_is_derive_error(self):
        for bad in ("[z-a]", "x[!]y]", "a/[9-0]/b"):
            with self.assertRaises(D.DeriveError, msg=bad):
                D.pattern_regex(bad)
            with self.assertRaises(D.DeriveError, msg=bad):
                self.derive(target={"excluded_paths": [bad]})

    def test_invalid_ownership_pattern_stops_derivation(self):
        # skipping the line could drop a security path, so the tree is not derived
        self.add({"CODEOWNERS": "x[z-a] @org/security\n"})
        with self.assertRaises(D.DeriveError):
            self.derive()
        # a line whose owner names no keyword is not compiled, as before
        self.add({"CODEOWNERS": "x[z-a] @org/docs\n"})
        self.derive()

    def test_policy_constitutional_of_wrong_shape(self):
        for policy in ([1], {"constitutional": [1]}, {"constitutional": "x"}, {"constitutional": {}}):
            with self.assertRaises(D.DeriveError, msg=repr(policy)):
                self.derive(policy=policy)

    def test_deep_tree_is_walked_without_recursion_limit(self):
        depth = sys.getrecursionlimit() + 100
        cur = os.path.join(self.base, "deep")
        os.mkdir(cur)
        rel = []
        for _ in range(depth):
            cur = os.path.join(cur, "d")
            os.mkdir(cur)
            rel.append("d")
        with open(os.path.join(cur, "auth.py"), "w") as fh:
            fh.write("x")
        d = D.derive(os.path.join(self.base, "deep"))
        self.assertEqual(d["security_paths"], ["/".join(rel + ["auth.py"])])
        self.assertEqual(d["languages"], {"python": {"files": 1}})

    def test_deeply_nested_tree_json_is_unparsable(self):
        deep = "[" * 200000
        self.add({"app/package.json": {"name": "a"}, "app/package-lock.json": deep})
        cand = D.derive(self.tree, {"unit_candidates": ["app"]})["unit_candidates"][0]
        self.assertEqual(cand["reasons"], ["lock_unparsable"])
        self.add({"app/package.json": deep, "app/package-lock.json": LOCK_OK})
        cand = D.derive(self.tree, {"unit_candidates": ["app"]})["unit_candidates"][0]
        self.assertEqual(cand["reasons"], ["package_json_unparsable"])


NO_OP = {"security_keywords": [], "excluded_paths": [], "unit_candidates": []}


class VectorTest(unittest.TestCase):
    """The command line: tohum/29f group ``profile``, run as the seed's general runner runs it."""

    def setUp(self):
        self.base = writable_base("t-pvec-")
        self.addCleanup(shutil.rmtree, self.base, True)
        self.n = 0

    def path(self, suffix):
        self.n += 1
        return os.path.join(self.base, "f%d%s" % (self.n, suffix))

    def tar(self, files, dirs=(), extra=()):
        return write_tar(self.path(".tar.gz"), files, dirs, extra)

    def json_file(self, obj):
        path = self.path(".json")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(obj if isinstance(obj, str) else json.dumps(obj))
        return path

    def cli(self, *args):
        proc = subprocess.run([sys.executable, "-m", "profile.derive", *args], cwd=REFEREE, stdin=subprocess.DEVNULL,
                              capture_output=True, text=True, timeout=60)
        self.assertNotIn("Traceback", proc.stderr, args)
        lines = proc.stdout.splitlines()
        self.assertEqual(len(lines), 1, proc.stdout + proc.stderr)
        self.stderr = proc.stderr
        return proc.returncode, json.loads(lines[-1])

    def derive(self, files, operator, dirs=()):
        code, out = self.cli("derive", self.tar(files, dirs), self.json_file(operator))
        self.assertEqual(code, 0, out)
        self.assertEqual(sorted(out), ["excluded_paths", "languages", "security_paths", "unit_candidates"])
        return out

    def check(self, files, operator, proposal):
        return self.cli("check", self.tar(files), self.json_file(operator), self.json_file(proposal))

    # ------------------------------------------------------------ named cases

    AGENT = [".Claude/settings.json", "a/b/.VSCODE/x.py", "x/.devContainer/y.ts", "deep/q/claude.MD", "Agents.md",
             "z/.MCP.JSON", "w/.EnvRc", "src/main.py", "src/claude.py", "CLAUDE.md/inner.js", "docs/AGENTS.md.txt"]

    def test_agent_config_case_insensitive(self):
        out = self.derive(self.AGENT, NO_OP, dirs=[".vscode", "empty/.claude"])
        self.assertEqual(out, {
            # CLAUDE.md as a directory is not agent configuration (only as the last component)
            "languages": ["javascript", "python"],
            "security_paths": [],
            "excluded_paths": [".Claude/settings.json", "Agents.md", "a/b/.VSCODE/x.py", "deep/q/claude.MD",
                               "w/.EnvRc", "x/.devContainer/y.ts", "z/.MCP.JSON"],
            "unit_candidates": [],
        })
        # one byte changed: .devContainer_ is not agent configuration, so its .ts file counts
        changed = [f.replace(".devContainer/", ".devContainer_/") for f in self.AGENT]
        out2 = self.derive(changed, NO_OP)
        self.assertNotEqual(out2["excluded_paths"], out["excluded_paths"])
        self.assertEqual(out2["languages"], ["javascript", "python", "typescript"])

    def test_operator_excluded_paths(self):
        files = ["src/a.py", "legacy/old.ts", "legacy/pkg/index.js"]
        op = {"security_keywords": [], "excluded_paths": ["legacy/"], "unit_candidates": ["legacy/pkg", "src"]}
        out = self.derive(files, op)
        self.assertEqual(out, {"languages": ["python"], "security_paths": [],
                               "excluded_paths": ["legacy/old.ts", "legacy/pkg/index.js"], "unit_candidates": ["src"]})
        changed = self.derive(files, dict(op, excluded_paths=["legacy/pkg"]))
        self.assertEqual(changed["languages"], ["python", "typescript"])
        self.assertEqual(changed["excluded_paths"], ["legacy/pkg/index.js"])
        self.assertEqual(changed["unit_candidates"], ["src"])
        unexcluded = self.derive(files, dict(op, excluded_paths=[]))
        self.assertEqual(unexcluded["unit_candidates"], ["legacy/pkg", "src"])
        self.assertEqual(unexcluded["languages"], ["javascript", "python", "typescript"])

    def test_coverage_boundary_case_and_trailing_slash(self):
        files = ["src/a.py", "srcx/b.ts", "SRC/c.js", "src", "lib/m.py"]
        for entry in ("src", "src/", "src//"):
            out = self.derive(files, dict(NO_OP, excluded_paths=[entry]))
            # covers the file named src and everything below src/, not srcx/ nor SRC/ (case-sensitive)
            self.assertEqual(out["excluded_paths"], ["src", "src/a.py"], entry)
            self.assertEqual(out["languages"], ["javascript", "python", "typescript"], entry)
        out = self.derive(files, dict(NO_OP, excluded_paths=["sr"], unit_candidates=["sr", "src/", "SRC", "lib/m.py"]))
        self.assertEqual(out["excluded_paths"], [])
        self.assertEqual(out["unit_candidates"], ["src/", "SRC", "lib/m.py"])

    def test_security_keyword_substring(self):
        files = ["src/oauth2/handler.py", "lib/TokenStore.ts", "lib/plain.py", "docs/authors.txt", ".claude/auth.py",
                 "vendor/token.js", "AUTH", "lib/to/ken.js"]
        op = {"security_keywords": ["Auth", "token"], "excluded_paths": ["vendor"], "unit_candidates": []}
        out = self.derive(files, op)
        self.assertEqual(out["security_paths"], ["AUTH", "docs/authors.txt", "lib/TokenStore.ts",
                                                 "src/oauth2/handler.py"])
        changed = self.derive(files, dict(op, security_keywords=["token"]))
        self.assertEqual(changed["security_paths"], ["lib/TokenStore.ts"])

    def test_unit_candidates_order_and_filter(self):
        files = ["pkgs/web/package.json", "pkgs/api/index.js", "apps/b/x.py", "vendor/lib/a.js", ".claude/pkg/p.json",
                 "tools/AGENTS.md", "docs/CLAUDE.md"]
        cands = ["pkgs/web", "missing", ".claude/pkg", "apps/b/", "vendor/lib", "pkgs/api", "tools/AGENTS.md", "pkg",
                 "docs"]
        op = {"security_keywords": [], "excluded_paths": ["vendor"], "unit_candidates": cands}
        out = self.derive(files, op)
        # docs covers only an excluded file and is kept; pkg does not cover pkgs/
        self.assertEqual(out["unit_candidates"], ["pkgs/web", "apps/b/", "pkgs/api", "docs"])
        swapped = self.derive(files, dict(op, unit_candidates=["pkgs/api"] + cands[:5] + cands[6:]))
        self.assertEqual(swapped["unit_candidates"], ["pkgs/api", "pkgs/web", "apps/b/", "docs"])

    TREE = ["src/auth.py", "web/app.ts", ".vscode/settings.json", "old/x.js"]
    OP = {"security_keywords": ["auth"], "excluded_paths": ["old"], "unit_candidates": ["web", "src"]}

    def proposal(self):
        return {"languages": ["python", "typescript"], "security_paths": ["src/auth.py"],
                "excluded_paths": [".vscode/settings.json", "old/x.js"], "unit_candidates": ["web", "src"]}

    def test_proposal_equal_to_derivation_accepted(self):
        self.assertEqual(self.derive(self.TREE, self.OP), self.proposal())
        self.assertEqual(self.check(self.TREE, self.OP, self.proposal()), (0, {"accepted": True, "reasons": []}))

    def test_reject_narrowed_excluded(self):
        p = self.proposal()
        p["excluded_paths"] = ["old/x.js"]
        self.assertEqual(self.check(self.TREE, self.OP, p),
                         (1, {"accepted": False, "reasons": ["narrows:excluded_paths"]}))
        p["excluded_paths"] = ["old", ".vscode"]  # a covering directory is not the derived path
        self.assertEqual(self.check(self.TREE, self.OP, p)[0], 1)

    def test_reject_different_languages(self):
        for langs in (["python"], ["python", "typescript", "javascript"], ["python", "TypeScript"]):
            p = self.proposal()
            p["languages"] = langs
            self.assertEqual(self.check(self.TREE, self.OP, p),
                             (1, {"accepted": False, "reasons": ["differs:languages"]}), langs)
        p = self.proposal()
        p["languages"] = ["typescript", "python", "python"]  # compared as sets
        self.assertEqual(self.check(self.TREE, self.OP, p), (0, {"accepted": True, "reasons": []}))

    def test_other_reasons_and_their_order(self):
        p = self.proposal()
        p["unit_candidates"] = ["src", "web"]
        self.assertEqual(self.check(self.TREE, self.OP, p)[1]["reasons"], ["differs:unit_candidates"])
        p = self.proposal()
        p["security_paths"] = []
        self.assertEqual(self.check(self.TREE, self.OP, p)[1]["reasons"], ["narrows:security_paths"])
        empty = {"languages": [], "security_paths": [], "excluded_paths": [], "unit_candidates": []}
        self.assertEqual(self.check(self.TREE, self.OP, empty),
                         (1, {"accepted": False, "reasons": ["differs:languages", "differs:unit_candidates",
                                                             "narrows:excluded_paths", "narrows:security_paths"]}))

    def test_widening_only_is_accepted(self):
        # tohum/14's specific rule (widening allowed); 29f notes no vector judges this case
        p = self.proposal()
        p["excluded_paths"].append("web/app.ts")
        p["security_paths"].append("web/app.ts")
        self.assertEqual(self.check(self.TREE, self.OP, p), (0, {"accepted": True, "reasons": []}))

    def test_tree_member_forms(self):
        out = self.derive({"./src/a.py": b"", "b.js": b"x" * 10}, NO_OP, dirs=["./", "./src/", "lone/.claude/"])
        self.assertEqual(out["languages"], ["javascript", "python"])
        self.assertEqual(out["excluded_paths"], [])

    # ------------------------------------------------------------ unusable input: exit 2

    def assert_unusable(self, *args):
        code, out = self.cli(*args)
        refusal.assert_refused(self, D, list(args), code, out, self.stderr)
        self.assertIn("error", out)
        if args and args[0] == "check":
            self.assertIs(out["accepted"], False)
        return out["error"]

    def test_unusable_tree(self):
        op = self.json_file(NO_OP)
        plain = self.path(".tar")
        with tarfile.open(plain, "w") as tar:
            tar.addfile(tarfile.TarInfo("a.py"), io.BytesIO(b""))
        garbage = self.json_file("not a tar")
        link = tarfile.TarInfo("ln")
        link.type, link.linkname = tarfile.SYMTYPE, "a.py"
        trees = [os.path.join(self.base, "missing.tar.gz"), plain, garbage, self.base,
                 self.tar(["a.py"], extra=[link]), self.tar(["/abs.py"]), self.tar(["a/../b.py"]),
                 self.tar(["a//b.py"]), self.tar(["a/./b.py"])]
        for tree in trees:
            self.assert_unusable("derive", tree, op)
            self.assert_unusable("check", tree, op, self.json_file(self.proposal()))

    def test_unusable_operator_and_proposal(self):
        tree = self.tar(self.TREE)
        for bad in ("{", "[]", "[" * 200000, {}, dict(NO_OP, excluded_paths="old"), dict(NO_OP, unit_candidates=[1]),
                    {"excluded_paths": [], "unit_candidates": []}):
            self.assert_unusable("derive", tree, self.json_file(bad))
        self.assert_unusable("derive", tree, os.path.join(self.base, "missing.json"))
        op = self.json_file(self.OP)
        bad_proposals = ["{", "[" * 200000, [], {k: v for k, v in self.proposal().items() if k != "languages"},
                         dict(self.proposal(), languages="python"), dict(self.proposal(), security_paths=[None])]
        for bad in bad_proposals:
            self.assert_unusable("check", tree, op, self.json_file(bad))

    def test_usage(self):
        tree, op = self.tar(self.TREE), self.json_file(self.OP)
        self.assert_unusable("derive", tree)
        self.assert_unusable("check", tree, op)
        self.assert_unusable("derive", tree, op, op)
        self.assert_unusable("verify", tree, op)
        self.assert_unusable()

    def test_unexpected_exception_is_exit_2_not_refusal(self):
        tree, op, prop = self.tar(self.TREE), self.json_file(self.OP), self.json_file(self.proposal())
        for args in (["derive", tree, op], ["check", tree, op, prop]):
            from test_cli import MARK, run_boundary
            with mock.patch.object(D, "derive_vector", side_effect=TypeError(MARK)):
                code, out, err = run_boundary(D.main, args, D.FAULT_LINE)
            want = {"error": "internal error"}
            if args[0] == "check":
                want["accepted"] = False
            self.assertEqual((code, json.loads(out), err), (2, want, "internal error: TypeError\n"))


if __name__ == "__main__":
    unittest.main()
