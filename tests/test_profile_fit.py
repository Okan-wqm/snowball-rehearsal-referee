"""``profile.fit``: each unit candidate's recipe composed from its own npm scripts, judged by ``check_recipe``.

- the composition: unit id, nearest lock and version file, minimal inputs with what a candidate reaches: the
  workspace folders it declares (Node's lookup through the lock's keys, transitive), its imports, tsconfig
  ``extends`` and a jest config's ``preset`` (aliases, links, relative paths; the deepest project or the file;
  seeds followed; links, missing paths, commented and quoted imports bring nothing), the flat config an npm lint
  script's ``eslint`` finds by its own lookup (nearest directory, ESLint's name order, files only; only the program
  ``eslint``, only the lint script), install-script marks from the lock,
  the image map, the three ``npm --prefix <path> run --silent`` commands;
- the result: one row per candidate in the derivation's order, its reasons exactly ``check_recipe``'s (the one
  judge), the passing paths;
- the command line: ``--units`` writes the first passing recipe and nothing when none passes; exit 0 / 1 / 2;
- the toy target: the composed recipe passes and agrees with ``targets/toy/units.json`` on every field but the
  commands.
"""

from __future__ import annotations

import io
import json
import os
import shutil
import sys
import unittest
from contextlib import redirect_stdout

REFEREE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BRAIN = os.path.dirname(REFEREE)
sys.path.insert(0, REFEREE)

from profile import fit as F  # noqa: E402
from profile import nx as X  # noqa: E402
from profile import unit_verify as U  # noqa: E402
from profile_tree import writable_base, write_tree  # noqa: E402
from test_deps_npm import sri, url  # noqa: E402

IMAGE = "node:20.11.1-bookworm-slim@sha256:" + "ab" * 32
IMAGES = {"20.11.1": IMAGE}


def entry(name: str, **extra) -> dict:
    return dict({"version": "1.0.0", "resolved": url(name, "1.0.0"), "integrity": sri(name.encode())}, **extra)


def lock(**packages) -> dict:
    return {"lockfileVersion": 3, "packages": dict({"": {"name": "root"}}, **packages)}


GOOD_SCRIPTS = {"lint": "eslint .", "test": "node --test"}


def package(scripts=None, **fields) -> dict:
    return dict({"name": "p", "version": "1.0.0", "scripts": GOOD_SCRIPTS if scripts is None else scripts}, **fields)


class Base(unittest.TestCase):
    def setUp(self) -> None:
        self.base = writable_base("t-fit-")
        self.addCleanup(shutil.rmtree, self.base, ignore_errors=True)
        self.tree = os.path.join(self.base, "tree")
        write_tree(self.tree, {
            ".nvmrc": "v20.11.1\n",
            "package-lock.json": lock(**{"node_modules/eslint": entry("eslint", bin={"eslint": "bin/eslint.js"}),
                                         "node_modules/esbuild": entry("esbuild", hasInstallScript=True),
                                         "node_modules/a/node_modules/b": entry("b", hasInstallScript=True),
                                         "node_modules/c": entry("c", hasInstallScript=False)}),
            "package.json": package({}, devDependencies={"eslint": "9"}),
            "pkgs/good/package.json": package(),
            "pkgs/nolint/package.json": package({"test": "node --test"}),
            "pkgs/vitest/package.json": package({"lint": "eslint .", "test": "vitest run"},
                                                devDependencies={"vitest": "1"}),
        })


class Compose(Base):
    def test_unit_id(self):
        cases = {".": "root", "pkgs/good": "pkgs-good", "@s/x y": "s-x-y", ".hidden/a": "hidden-a",
                 "a" * 200: "a" * 128, "___": "root"}
        for path, uid in cases.items():
            self.assertEqual(F.unit_id(path), uid, path)
            self.assertTrue(U.UNIT_ID.fullmatch(F.unit_id(path)), path)

    def test_the_recipe_of_a_member_below_the_root_lock(self):
        npm = ["npm", "--prefix", "pkgs/good", "run", "--silent"]
        self.assertEqual(F.compose(self.tree, "pkgs/good", IMAGES), {
            "unit_id": "pkgs-good", "path": "pkgs/good", "inputs": [".nvmrc", "package-lock.json", "pkgs/good"],
            "toolchain": "node@20.11.1", "env_image": IMAGE, "lockfiles": ["package-lock.json"],
            "install_scripts_required": ["node_modules/a/node_modules/b", "node_modules/esbuild"],
            "lint_cmd": npm + ["lint", "--", "--format", "json"], "test_cmd": npm + ["test"],
            "affected_test_cmd": npm + ["test"], "services": [], "limits": {}})

    def test_nearest_files_and_minimal_inputs(self):
        write_tree(self.tree, {"pkgs/good/.node-version": "20.11.2", "pkgs/good/package-lock.json": lock()})
        r = F.compose(self.tree, "pkgs/good", {"20.11.2": "x"})
        self.assertEqual((r["inputs"], r["lockfiles"], r["toolchain"], r["env_image"], r["install_scripts_required"]),
                         (["pkgs/good"], ["pkgs/good/package-lock.json"], "node@20.11.2", "x", []))
        write_tree(self.tree, {"pkgs/good/npm-shrinkwrap.json": lock()})
        self.assertEqual(F.compose(self.tree, "pkgs/good")["lockfiles"], ["pkgs/good/npm-shrinkwrap.json"])
        self.assertEqual(F.compose(self.tree, ".")["inputs"], ["."])

    def test_no_lock_no_version_no_image(self):
        bare = os.path.join(self.base, "bare")
        write_tree(bare, {"x/package.json": package()})
        r = F.compose(bare, "x", IMAGES)
        self.assertEqual((r["lockfiles"], r["toolchain"], r["env_image"], r["inputs"], r["install_scripts_required"]),
                         ([], "node@", "", ["x"], []))
        self.assertEqual(F.compose(self.tree, "pkgs/good", {"20.11.1": 3})["env_image"], "")


class WorkspaceFolders(unittest.TestCase):
    """``reached`` by declared names: the folders of the workspace packages a candidate declares, by Node's lookup
    through the lock's keys, transitively."""

    def setUp(self) -> None:
        self.base = writable_base("t-fit-ws-")
        self.addCleanup(shutil.rmtree, self.base, ignore_errors=True)
        self.tree = os.path.join(self.base, "tree")

    def write(self, prefix: str = "") -> None:
        link = lambda folder: {"resolved": folder, "link": True}  # noqa: E731
        write_tree(self.tree, {
            prefix + "package-lock.json": lock(**{
                "node_modules/@w/a": link("libs/a"), "node_modules/@w/b": link("libs/b"),
                "node_modules/@w/c": link("libs/c"), "node_modules/@w/far": link("../far"),
                "node_modules/@w/tool": link("tools/tool"),  # an in-repo file: dependency, same form
                "node_modules/@w/shadow": link("libs/shadow"),
                "node_modules/@w/dot": link("./libs/c"),  # a link MF5's live path does not take
                "apps/web/node_modules/@w/shadow": entry("@w/shadow"),  # nearer: a registry package
                "node_modules/left-pad": entry("left-pad"), "libs/a": {"name": "@w/a"}}),
            prefix + "apps/web/package.json": package(dependencies={"@w/a": "*", "left-pad": "1"},
                                                      devDependencies={"@w/shadow": "*", "@w/far": "*", "@w/dot": "*",
                                                                       "@w/undeclared-in-lock": "*"},
                                                      peerDependencies={"@w/tool": "file:../../tools/tool"}),
            prefix + "libs/a/package.json": package(dependencies={"@w/b": "*"}),
            prefix + "libs/b/package.json": package(dependencies={"@w/a": "*"}),  # a cycle ends
            prefix + "libs/c/package.json": package(),  # nobody declares it
        })

    def test_declared_links_transitively_by_nodes_lookup(self):
        self.write()
        self.assertEqual(F.reached(self.tree, "apps/web", "package-lock.json"),
                         ["libs/a", "libs/b", "tools/tool"])
        self.assertEqual(F.compose(self.tree, "apps/web")["inputs"],
                         ["apps/web", "libs/a", "libs/b", "package-lock.json", "tools/tool"])

    def test_below_a_lock_in_a_subdirectory(self):
        self.write("sub/")
        self.assertEqual(F.reached(self.tree, "sub/apps/web", "sub/package-lock.json"),
                         ["sub/libs/a", "sub/libs/b", "sub/tools/tool"])

    def test_no_lock_or_unreadable_lock_or_manifest(self):
        self.write()
        self.assertEqual(F.reached(self.tree, "apps/web", None), [])
        write_tree(self.tree, {"package-lock.json": "not json"})
        self.assertEqual(F.reached(self.tree, "apps/web", "package-lock.json"), [])
        self.write()
        write_tree(self.tree, {"libs/a/package.json": "not json"})
        self.assertEqual(F.reached(self.tree, "apps/web", "package-lock.json"), ["libs/a", "tools/tool"])


class Reached(unittest.TestCase):
    """``reached`` by references: imports and tsconfig ``extends``, through aliases, links and relative paths, to
    the deepest project directory or the file itself, transitively, from the candidate and the seeds."""

    def setUp(self) -> None:
        self.base = writable_base("t-fit-reach-")
        self.addCleanup(shutil.rmtree, self.base, ignore_errors=True)
        self.tree = os.path.join(self.base, "tree")
        link = lambda folder: {"resolved": folder, "link": True}  # noqa: E731
        write_tree(self.tree, {
            "package-lock.json": lock(**{"node_modules/@w/linked": link("libs/linked"),
                                         "node_modules/@w/cfg": link("tools/cfg"),
                                         "node_modules/react": entry("react")}),
            "tsconfig.base.json": "// the aliases, in tsconfig's dialect\n" + json.dumps({"compilerOptions": {"paths": {
                "@w/exact": ["libs/exact/src/index.ts"], "@w/wild/*": ["libs/wild/src/*"],
                "@w/chained": ["libs/chained/src/index.ts"], "@w/testing/*": ["libs/testing/src/*"],
                "@w/nowhere": ["libs/none/index.ts"]}}}),
            "eslint.config.mjs": "import shared from './tools/eslint-shared.mjs';\n",
            "tools/eslint-shared.mjs": "export default [];\n",
            "tools/cfg/package.json": package(name="@w/cfg"),
            "tools/cfg/base.json": "{}",
            "apps/web/package.json": package(dependencies={"react": "1"}),
            "apps/web/tsconfig.json": json.dumps({"extends": "../../tsconfig.base"}),
            "apps/web/tsconfig.lib.json": json.dumps({"extends": ["./tsconfig.json", "@w/cfg/base.json"]}),
            "apps/web/src/main.ts": "\n".join([
                "import { e } from '@w/exact';",
                "import { w } from '@w/wild/deep/x';",
                "import { l } from '@w/linked/sub/path';",       # undeclared, linked in the lock
                "import React from 'react';",                    # a registry package: nothing
                "import { n } from '@w/nowhere';",               # an alias to no file: nothing
                "import { own } from './own';",                  # the candidate's own file
                "import { h } from '../../../../libs/helper';",   # leaves the tree: nothing
                "import { u } from '../../../loose/util';",      # a file of no project
                "import { d } from '../../../loose/dir';",       # a directory of no project: itself
                "// import { c } from '../../../libs/commented';",
                "const q = \"import { s } from '../../../libs/quoted'\";",
                "import { k } from '../../../libs/linked/src/k';",  # reached already, by the link
                "",
            ]),
            "apps/web/src/own.ts": "export const own = 1;\n",
            "apps/web/vitest.config.ts": "import policy from '@w/testing/vitest';\n",  # no such file, its project
            "libs/exact/project.json": json.dumps({"name": "exact"}),
            "libs/exact/src/index.ts": "export * from '@w/chained';\n",
            "libs/wild/package.json": package(name="@w/wild"),
            "libs/wild/src/deep/x.ts": "export const w = 1;\n",
            "libs/linked/package.json": package(name="@w/linked"),
            "libs/linked/src/k.ts": "export const k = 1;\n",
            "libs/chained/project.json": json.dumps({"name": "chained"}),
            "libs/chained/src/index.ts": "export const c = 1;\n",
            "libs/commented/project.json": json.dumps({"name": "commented"}),
            "libs/quoted/project.json": json.dumps({"name": "quoted"}),
            "libs/testing/package.json": package(name="@w/testing"),
            "libs/testing/src/index.ts": "export const t = 1;\n",
            "libs/helper.ts": "export const h = 1;\n",
            "loose/util.ts": "export const u = 1;\n",
            "loose/dir/index.ts": "export const d = 1;\n",
        })

    WEB = ["libs/chained", "libs/exact", "libs/linked", "libs/testing", "libs/wild", "loose/dir",
           "loose/util.ts", "tools/cfg", "tsconfig.base.json"]

    def test_every_route_from_the_candidate(self):
        self.assertEqual(F.reached(self.tree, "apps/web", "package-lock.json"), self.WEB)

    def test_the_seeds_are_followed_and_the_root_reaches_nothing_more(self):
        self.assertEqual(F.reached(self.tree, "apps/web", "package-lock.json", ["eslint.config.mjs"]),
                         sorted(self.WEB + ["tools/eslint-shared.mjs"]))
        memo: dict = {}
        self.assertEqual(F.reached(self.tree, ".", "package-lock.json", ["eslint.config.mjs"], memo), [])
        self.assertEqual(memo, {})  # nothing read: "." covers the tree

    def test_without_a_lock_links_are_not_followed(self):
        # libs/linked stays, reached by main.ts's relative import of libs/linked/src/k
        self.assertEqual(F.reached(self.tree, "apps/web", None), [p for p in self.WEB if p != "tools/cfg"])

    def test_extensions_and_directories(self):
        write_tree(self.tree, {"apps/web/src/more.ts": "import a from '../../../loose/a';\n"
                                                       "import b from '../../../loose/b';\n",
                               "loose/a.mjs": "export default 1;\n", "loose/b/index.tsx": "export default 1;\n"})
        self.assertEqual(F.reached(self.tree, "apps/web", None),
                         sorted([p for p in self.WEB if p != "tools/cfg"] + ["loose/a.mjs", "loose/b"]))

    def test_a_link_or_a_missing_target_brings_nothing(self):
        write_tree(self.tree, {"apps/web/src/more.ts": "import a from '../../../real/a';\n"
                                                       "import b from '../../../gone/b';\n"
                                                       "import c from '../../../loose/missing/c';\n",
                               "elsewhere/a.ts": "export const a = 1;\n", "elsewhere/package.json": package(),
                               "real": ("symlink", "elsewhere")})
        self.assertEqual(F.reached(self.tree, "apps/web", "package-lock.json"), self.WEB)

    def test_a_reached_projects_own_references_are_followed(self):
        write_tree(self.tree, {"libs/chained/tsconfig.json": json.dumps({"extends": "../../tools/ts/strict.json"}),
                               "tools/ts/strict.json": "{}"})
        self.assertIn("tools/ts/strict.json", F.reached(self.tree, "apps/web", "package-lock.json"))

    def test_a_jest_configs_preset(self):
        write_tree(self.tree, {"libs/exact/jest.config.ts": "export default { preset: '../../jest.preset.js' };\n",
                               "jest.preset.js": "module.exports = require('./tools/jest-base.js');\n",
                               "tools/jest-base.js": "module.exports = {};\n",
                               "apps/web/jest.config.cts": "module.exports = { preset: '@w/cfg' };\n",
                               "apps/web/src/jest.config.notes.ts": "export default { preset: '../../../nope.js' };\n",
                               "nope.js": "\n"})
        self.assertEqual(F.reached(self.tree, "apps/web", "package-lock.json"),
                         sorted(self.WEB + ["jest.preset.js", "tools/jest-base.js"]))

    def test_the_memo_gives_the_same_answer(self):
        memo: dict = {}
        first = F.reached(self.tree, "apps/web", "package-lock.json", (), memo)
        self.assertIn("apps/web", memo)
        self.assertEqual(F.reached(self.tree, "apps/web", "package-lock.json", (), memo), first)
        self.assertEqual(F.reached(self.tree, "libs/exact", "package-lock.json", (), memo), ["libs/chained"])

    def test_the_composed_inputs(self):
        self.assertEqual(F.compose(self.tree, "apps/web")["inputs"],
                         sorted(["apps/web", "package-lock.json"] + self.WEB  # and the lint script's ESLint config
                                + ["eslint.config.mjs", "tools/eslint-shared.mjs"]))


class LintConfig(Base):
    """An npm lint script whose program is ``eslint``: the flat config ESLint's own lookup finds is an input."""

    CONFIG = "import rules from './lint/rules.mjs';\nimport plug from './tools/plug/index.js';\nexport default [];\n"
    FILES = {"eslint.config.mjs": CONFIG, "lint/rules.mjs": "export default {};\n",
             "tools/plug/package.json": {"name": "plug"}, "tools/plug/index.js": "module.exports = {};\n"}
    PLAIN = [".nvmrc", "package-lock.json", "pkgs/good"]

    def inputs(self, path: str = "pkgs/good") -> list:
        return F.compose(self.tree, path)["inputs"]

    def script(self, text: str) -> list:
        write_tree(self.tree, {"pkgs/good/package.json": package({"lint": text, "test": "node --test"})})
        return F.commands(self.tree, "pkgs/good")["inputs"]

    def test_the_nearest_config_is_an_input_with_what_it_imports(self):
        self.assertEqual(self.inputs(), self.PLAIN)  # no flat config in the tree: nothing joins
        write_tree(self.tree, self.FILES)
        self.assertEqual(F.commands(self.tree, "pkgs/good")["inputs"], ["eslint.config.mjs"])
        self.assertEqual(F.commands(self.tree, "pkgs/good")["sources"], {"lint": "npm_script", "test": "npm_script"})
        self.assertEqual(self.inputs(), sorted(self.PLAIN + ["eslint.config.mjs", "lint/rules.mjs", "tools/plug"]))
        write_tree(self.tree, {"pkgs/eslint.config.cjs": "module.exports = [];\n"})  # a nearer one wins
        self.assertEqual(self.inputs(), sorted(self.PLAIN + ["pkgs/eslint.config.cjs"]))
        write_tree(self.tree, {"pkgs/good/eslint.config.js": "export default [];\n"})  # the candidate's own
        self.assertEqual(F.commands(self.tree, "pkgs/good")["inputs"], ["pkgs/good/eslint.config.js"])
        self.assertEqual(self.inputs(), self.PLAIN)

    def test_eslints_name_order_in_one_directory(self):
        order = ["eslint.config.js", "eslint.config.mjs", "eslint.config.cjs", "eslint.config.ts",
                 "eslint.config.mts", "eslint.config.cts"]
        self.assertEqual(list(X.ESLINT_FLAT_CONFIGS), order)
        self.assertEqual(sorted(X.ESLINT_FLAT_CONFIGS), sorted(X.FLAT_CONFIGS))
        for i in range(len(order) - 1, -1, -1):  # written from the last name to the first: each new one wins
            write_tree(self.tree, {order[i]: ""})
            self.assertEqual(F.commands(self.tree, "pkgs/good")["inputs"], [order[i]])

    def test_a_directory_of_that_name_is_passed_over(self):
        write_tree(self.tree, {"pkgs/eslint.config.js/x": "", "eslint.config.mjs": ""})
        self.assertEqual(F.commands(self.tree, "pkgs/good")["inputs"], ["eslint.config.mjs"])

    def test_only_a_script_with_the_program_eslint(self):
        write_tree(self.tree, self.FILES)
        for text in ("eslint src", "tsc --noEmit && eslint src --max-warnings 0", "CI=1 eslint .",
                     "eslint -c other.mjs ."):
            self.assertEqual(self.script(text), ["eslint.config.mjs"], text)
        for text in ("biome lint", "echo eslint", "npx eslint .", "node run.mjs eslint src", "eslint 'src",
                     "node_modules/.bin/eslint ."):
            self.assertEqual(self.script(text), [], text)

    def test_the_test_script_and_a_missing_lint_script_bring_nothing(self):
        write_tree(self.tree, self.FILES)
        write_tree(self.tree, {"pkgs/good/package.json": package({"test": "eslint ."})})
        self.assertEqual(F.commands(self.tree, "pkgs/good")["inputs"], [])
        self.assertEqual(F.commands(self.tree, "pkgs/good")["sources"]["lint"], "none:no_workspace")


class Fit(Base):
    def test_rows_are_check_recipes_reasons_in_the_derivations_order(self):
        report = F.fit(self.tree, None, None, IMAGES)
        paths = [r["path"] for r in report["rows"]]
        self.assertEqual(paths, [".", "pkgs/good", "pkgs/nolint", "pkgs/vitest"])
        for row in report["rows"]:
            recipe = F.compose(self.tree, row["path"], IMAGES)
            self.assertEqual(row["recipe"], recipe)
            self.assertEqual(row["reasons"], U.check_recipe(recipe, None, self.tree), row["path"])
            # Group recipe's plainness (29g) on the composed inputs: every input is plain except the root unit's
            # ".", which 29g refuses and check_recipe accepts (an open divergence, founder-ledger; stated here).
            plain = [r for r in U.vector_check(recipe, {"operating": {}}) if r.startswith("input")]
            self.assertEqual(plain, ["input_not_plain:."] if row["path"] == "." else [], row["path"])
        by = {r["path"]: r["reasons"] for r in report["rows"]}
        self.assertEqual(by["pkgs/good"], [])
        self.assertEqual(by["pkgs/nolint"], ["script_missing:lint_cmd:lint"])
        self.assertEqual(by["pkgs/vitest"], ["script_not_installed:test_cmd:vitest",
                                             "script_not_installed:affected_test_cmd:vitest"])
        self.assertEqual(by["."], ["script_missing:lint_cmd:lint", "script_missing:test_cmd:test",
                                   "script_missing:affected_test_cmd:test"])
        self.assertEqual((report["candidates"], report["fit"]), (4, ["pkgs/good"]))

    def test_the_operators_order_and_an_ineligible_candidate(self):
        target = {"id": "t", "unit_candidates": ["pkgs/vitest", "pkgs/none", "pkgs/good"]}
        report = F.fit(self.tree, target, None, IMAGES)
        self.assertEqual([r["path"] for r in report["rows"]], ["pkgs/vitest", "pkgs/none", "pkgs/good"])
        self.assertIn("profile:units[0]:unit_not_eligible:pkgs/none", report["rows"][1]["reasons"])

    def test_without_an_image_the_tree_reasons_still_show(self):
        by = {r["path"]: r["reasons"] for r in F.fit(self.tree)["rows"]}
        self.assertEqual(by["pkgs/good"], ["image_not_pinned"])
        self.assertEqual(by["pkgs/nolint"], ["image_not_pinned", "script_missing:lint_cmd:lint"])


class Cli(Base):
    def run_main(self, *argv) -> tuple[int, dict]:
        out = io.StringIO()
        with redirect_stdout(out):
            code = F.main(list(argv))
        return code, json.loads(out.getvalue().splitlines()[-1])

    def json_file(self, name: str, value) -> str:
        path = os.path.join(self.base, name)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(value, fh)
        return path

    def test_units_written_with_the_first_passing_recipe(self):
        out = os.path.join(self.base, "units.json")
        write_tree(self.tree, {"pkgs/good2/package.json": package()})
        target = self.json_file("target.json", {"id": "t", "unit_candidates": ["pkgs/nolint", "pkgs/good", ".",
                                                                               "pkgs/good2"]})
        code, report = self.run_main(self.tree, "--images", self.json_file("i.json", IMAGES), "--target", target,
                                     "--units", out)
        self.assertEqual((code, report["ok"], report["fit"]), (0, True, ["pkgs/good", "pkgs/good2"]))
        with open(out, encoding="utf-8") as fh:
            self.assertEqual(json.load(fh), {"units": [F.compose(self.tree, "pkgs/good", IMAGES)]})

    def test_nothing_written_when_none_passes(self):
        out = os.path.join(self.base, "units.json")
        target = self.json_file("target.json", {"id": "t", "unit_candidates": ["pkgs/nolint", "pkgs/vitest"]})
        code, report = self.run_main(self.tree, "--images", self.json_file("i.json", IMAGES), "--target", target,
                                     "--units", out)
        self.assertEqual((code, report["ok"], report["fit"], report["candidates"]), (1, False, [], 2))
        self.assertFalse(os.path.lexists(out))

    def test_unusable_input(self):
        bad = [(), ("--images",), (self.tree, "--images"), (self.tree, "--other", "x"),
               (self.tree, "--images", "x", "--images", "y"), ("--units", "x", self.tree),
               (self.tree, "--images", self.json_file("l.json", [1])),
               (self.tree, "--target", self.json_file("t.json", "t")),
               (self.tree, "--policy", os.path.join(self.base, "missing.json")),
               (self.tree, "--images", self.json_file("n.json", "{")),
               (os.path.join(self.base, "no-tree"),)]
        for argv in bad:
            code, report = self.run_main(*argv)
            self.assertEqual((code, report["ok"]), (2, False), argv)
            self.assertIn("error", report)


class ToyTarget(unittest.TestCase):
    def test_the_toy_unit_fits_and_agrees_with_its_units_json(self):
        with open(os.path.join(BRAIN, "targets", "toy", "units.json"), encoding="utf-8") as fh:
            toy = json.load(fh)["units"][0]
        version = toy["toolchain"].split("@", 1)[1]
        report = F.fit(os.path.join(BRAIN, "tests", "fixtures", "toy-repo"), None, None,
                       {version: toy["env_image"]})
        self.assertEqual(report["fit"], ["textkit"])
        recipe = report["rows"][0]["recipe"]
        for field in U.RECIPE_FIELDS:
            if field not in U.CMD_FIELDS:
                self.assertEqual(recipe[field], toy[field], field)


if __name__ == "__main__":
    unittest.main()
