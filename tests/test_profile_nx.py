"""``profile.nx``: an Nx project's ``lint`` and ``test`` targets as the commands their executors run, and their use
by ``profile.fit`` when the candidate has no npm script.

- Nx's token rules: ``resolveNxTokensInOptions`` and the lint executor's ``interpolate``, case by case as Nx
  22.7.12's code does them;
- the target's refusals, one reason each: no workspace, a lock below the root, no target, a key, an executor, an
  option, a ``targetDefaults`` entry by executor, name or glob;
- lint: default and explicit patterns, the nearest flat config in Nx's name order, no flat config, ESLint's major;
- test: the command, the config as an input, the missing option;
- lint inferred by ``@nx/eslint/plugin``: the command and its inputs (a project.json or package.json project, the
  root candidate's ``src``/``lib``), run by ``/bin/sh`` from the candidate's directory; every plugin, config,
  lintable-file and ``targetDefaults`` refusal; an explicit target still replacing the inferred one;
- fit: the npm script wins, an Nx command is judged by ``check_recipe`` like any other (``.bin`` against the lock),
  ``sources`` says which form each command took.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import unittest

REFEREE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REFEREE)

import cli  # noqa: E402
from profile import fit as F  # noqa: E402
from profile import nx as X  # noqa: E402
from profile import unit_verify as U  # noqa: E402
from profile_tree import writable_base, write_tree  # noqa: E402
from test_deps_npm import sri, url  # noqa: E402
from test_profile_fit import IMAGES, lock, package  # noqa: E402

LINT = {"executor": "@nx/eslint:lint"}
JEST = {"executor": "@nx/jest:jest", "options": {"jestConfig": "libs/a/jest.config.ts"}}
TS = "TS_NODE_COMPILER_OPTIONS=" + '{"moduleResolution":"Node10","module":"commonjs","customConditions":null}'


def entry(name: str, version: str = "1.0.0", **extra) -> dict:
    """A registry entry MF5 takes, its tarball URL naming ``version``."""
    return dict({"version": version, "resolved": url(name, version), "integrity": sri(name.encode())}, **extra)


def eslint_cmd(config: str, *patterns: str) -> list:
    return ["node_modules/.bin/eslint", "--config", config, "--no-error-on-unmatched-pattern", "--format", "json",
            *patterns]


class Tokens(unittest.TestCase):
    def test_interpolate_as_the_lint_executor(self):
        cases = [("{projectRoot}", "libs/a", "libs/a"), ("{projectRoot}", ".", "."),
                 ("libs/a/src/**/*.{ts,tsx}", "libs/a", "libs/a/src/**/*.{ts,tsx}"),  # no token: as written
                 ("{projectRoot}/src/**/*.{ts,tsx}", "libs/a", "libs/a/src/**/*.{ts,tsx}"),
                 ("{workspaceRoot}/libs/a", "libs/a", "libs/a"), ("./{projectRoot}/", "libs/a", "libs/a"),
                 ("{projectRoot}/../b", "libs/a", "libs/b"), ("{projectRoot}/src", ".", "src"),
                 ("/abs/{projectRoot}", "libs/a", "/abs/{projectRoot}"), ("{projectName}/x", "libs/a", "n/x"),
                 ("{ projectRoot }", "libs/a", "libs/a"), ("{nope}/x", "libs/a", "{nope}/x")]
        for template, root, want in cases:
            self.assertEqual(X.nx_interpolate(template, root, "n"), want, (template, root))
        self.assertEqual(X.nx_interpolate("{projectName}/x", "libs/a", None), "{projectName}/x")
        for template, root, reason in [("a/{workspaceRoot}", "libs/a", "token:workspaceRoot"),
                                       ("src/{projectRoot}", ".", "token:projectRoot")]:
            with self.assertRaises(X.NotComposed) as cm:
                X.nx_interpolate(template, root, "n")
            self.assertEqual(cm.exception.reasons, [reason])

    def test_resolve_tokens_as_nx_options(self):
        self.assertEqual(X.resolve_tokens("{workspaceRoot}/a/{projectRoot}/{projectRoot}", "p", None), "a/p/p")
        self.assertEqual(X.resolve_tokens("{workspaceRoot}x", "p", None), "x")
        self.assertEqual(X.resolve_tokens("{projectName}.js", "p", "n"), "n.js")
        for value, name, reason in [("a/{workspaceRoot}", "n", "token:workspaceRoot"),
                                    ("{projectName}", None, "token:projectName"),
                                    ("{projectName}", "", "token:projectName")]:
            with self.assertRaises(X.NotComposed) as cm:
                X.resolve_tokens(value, "p", name)
            self.assertEqual(cm.exception.reasons, [reason])


class Base(unittest.TestCase):
    def setUp(self) -> None:
        self.base = writable_base("t-nx-")
        self.addCleanup(shutil.rmtree, self.base, ignore_errors=True)
        self.tree = os.path.join(self.base, "tree")
        write_tree(self.tree, {
            ".nvmrc": "v20.11.1\n",
            "nx.json": {"targetDefaults": {"lint": {"inputs": ["default"], "cache": True},
                                           "test": {"outputs": ["{projectRoot}/coverage"]}}},
            "eslint.config.mjs": "export default [];\n",
            "package-lock.json": lock(**{
                "node_modules/eslint": entry("eslint", "9.39.4", bin={"eslint": "bin/eslint.js"}),
                "node_modules/jest": entry("jest", "30.5.2", bin={"jest": "bin/jest.js"})}),
            "package.json": package({}),
            "libs/a/package.json": package({}, name="@w/a"),
            "libs/a/project.json": {"name": "a", "targets": {"lint": LINT, "test": JEST}},
        })

    def project(self, **targets) -> None:
        write_tree(self.tree, {"libs/a/project.json": {"name": "a", "targets": targets}})

    def refused(self, fn, reason: str, path: str = "libs/a") -> None:
        with self.assertRaises(X.NotComposed) as cm:
            fn(self.tree, path)
        self.assertEqual(cm.exception.reasons, [reason])


class Target(Base):
    def test_no_workspace_or_a_lock_below_the_root(self):
        os.remove(os.path.join(self.tree, "nx.json"))
        self.refused(X.lint, "no_workspace")
        write_tree(self.tree, {"nx.json": "[]"})
        self.refused(X.lint, "no_workspace")
        write_tree(self.tree, {"nx.json": {}, "libs/a/package-lock.json": lock()})
        self.refused(X.lint, "lock_not_at_workspace_root")

    def test_no_target(self):
        self.project(build=LINT)
        self.refused(X.lint, "no_target")
        os.remove(os.path.join(self.tree, "libs/a/project.json"))
        self.refused(X.test, "no_target")
        write_tree(self.tree, {"libs/a/project.json": {"targets": {"lint": "x"}}})
        self.refused(X.lint, "no_target")

    def test_keys_executors_and_options_outside_the_rules(self):
        for spec, reason in [(dict(LINT, dependsOn=["^build"]), "target_key:dependsOn"),
                             (dict(LINT, defaultConfiguration="ci"), "target_key:defaultConfiguration"),
                             (dict(LINT, command="eslint ."), "target_key:command"),
                             ({"executor": "nx:run-commands"}, "executor:nx:run-commands"),
                             ({}, "executor:None"),
                             (dict(LINT, options={"format": "json"}), "option:format"),
                             (dict(LINT, options={"eslintConfig": "x.mjs"}), "option:eslintConfig"),
                             (dict(LINT, options=[]), "option:options")]:
            self.project(lint=spec)
            self.refused(X.lint, reason)
        self.project(lint=dict(LINT, inputs=["default"], outputs=[], cache=True, configurations={"ci": {}}))
        self.assertEqual(X.lint(self.tree, "libs/a")[0], eslint_cmd("eslint.config.mjs", "libs/a"))
        self.project(test=dict(JEST, options={"jestConfig": "j.ts", "ci": True}))
        self.refused(X.test, "option:ci")

    def test_target_defaults_by_executor_then_name_then_longest_glob(self):
        for defaults, reason in [
                ({"@nx/eslint:lint": {"dependsOn": ["^build"]}, "lint": {"cache": True}}, "target_defaults_key:dependsOn"),
                ({"lint": {"options": {"quiet": True}}}, "target_defaults_key:options"),
                ({"l*": {"cache": True}, "li*": {"executor": "x"}}, "target_defaults_key:executor"),
                ({"lint": True}, "target_defaults_key:lint")]:
            write_tree(self.tree, {"nx.json": {"targetDefaults": defaults}})
            self.refused(X.lint, reason)
        # The executor's key wins over the name's, as readTargetDefaultsForTarget reads them.
        write_tree(self.tree, {"nx.json": {"targetDefaults": {"@nx/eslint:lint": {"cache": True},
                                                              "lint": {"dependsOn": ["^build"]}}}})
        self.assertEqual(X.lint(self.tree, "libs/a")[0], eslint_cmd("eslint.config.mjs", "libs/a"))


class Lint(Base):
    def test_default_and_explicit_patterns(self):
        self.assertEqual(X.lint(self.tree, "libs/a"), (eslint_cmd("eslint.config.mjs", "libs/a"),
                                                       ["eslint.config.mjs"]))
        self.project(lint=dict(LINT, options={"lintFilePatterns": ["{projectRoot}/src/**/*.{ts,tsx}",
                                                                    "{workspaceRoot}/libs/a/x.ts", "{projectName}.ts"]}))
        self.assertEqual(X.lint(self.tree, "libs/a")[0],
                         eslint_cmd("eslint.config.mjs", "libs/a/src/**/*.{ts,tsx}", "libs/a/x.ts", "a.ts"))
        for patterns, reason in [([], "option:lintFilePatterns"), ("libs/a", "option:lintFilePatterns"),
                                 ([""], "option:lintFilePatterns"), (["--fix"], "pattern_option"),
                                 (["a/{workspaceRoot}"], "token:workspaceRoot")]:
            self.project(lint=dict(LINT, options={"lintFilePatterns": patterns}))
            self.refused(X.lint, reason)

    def test_the_nearest_flat_config_in_nxs_name_order(self):
        write_tree(self.tree, {"libs/eslint.config.js": "", "libs/eslint.config.cjs": ""})
        self.assertEqual(X.lint(self.tree, "libs/a")[1], ["libs/eslint.config.cjs"])
        write_tree(self.tree, {"libs/a/eslint.config.mts": ""})
        self.assertEqual(X.lint(self.tree, "libs/a")[0][2], "libs/a/eslint.config.mts")
        self.assertEqual(X.flat_config(self.tree, "."), "eslint.config.mjs")

    def test_no_flat_config_or_eslint_before_9(self):
        os.remove(os.path.join(self.tree, "eslint.config.mjs"))
        write_tree(self.tree, {".eslintrc.json": {}})
        self.refused(X.lint, "no_flat_config")
        write_tree(self.tree, {"eslint.config.mjs": ""})
        for version in ("8.57.0", "x", None):
            eslint = entry("eslint", "1.0.0", bin={"eslint": "bin/eslint.js"})
            eslint["version"] = version
            write_tree(self.tree, {"package-lock.json": lock(**{"node_modules/eslint": eslint})})
            self.refused(X.lint, "eslint_version")
        write_tree(self.tree, {"package-lock.json": lock()})
        self.refused(X.lint, "eslint_version")
        write_tree(self.tree, {"package-lock.json": lock(**{"node_modules/eslint": entry("eslint", "10.0.0")})})
        self.assertEqual(X.lint(self.tree, "libs/a")[0][0], "node_modules/.bin/eslint")


class Test(Base):
    def test_the_command_and_its_config_input(self):
        self.assertEqual(X.test(self.tree, "libs/a"),
                         (["env", TS, "node_modules/.bin/jest", "--config", "libs/a/jest.config.ts"],
                          ["libs/a/jest.config.ts"]))
        self.project(test=dict(JEST, options={"jestConfig": "{projectRoot}/jest.config.cts"}))
        self.assertEqual(X.test(self.tree, "libs/a")[0][-1], "libs/a/jest.config.cts")
        self.project(test=dict(JEST, options={"jestConfig": "/abs/jest.config.js"}))
        self.assertEqual(X.test(self.tree, "libs/a"),
                         (["env", TS, "node_modules/.bin/jest", "--config", "/abs/jest.config.js"], []))

    def test_refused(self):
        for options, reason in [({}, "option_missing:jestConfig"), ({"jestConfig": ""}, "option:jestConfig"),
                                ({"jestConfig": 3}, "option:jestConfig"), ({"jestConfig": "-c"}, "pattern_option")]:
            self.project(test=dict(JEST, options=options))
            self.refused(X.test, reason)


def inferred(path: str, pattern: str = ".") -> list:
    return ["/bin/sh", "-c", X.CD_EXEC, path, "/work/node_modules/.bin/eslint", pattern, "--format", "json"]


class Inferred(Base):
    def setUp(self) -> None:
        super().setUp()
        write_tree(self.tree, {"nx.json": {"plugins": ["@nx/eslint/plugin"],
                                           "targetDefaults": {"lint": {"inputs": ["default"], "cache": True}}},
                               "libs/a/src/x.ts": "export {};\n"})
        self.project(test=JEST)

    def plugins(self, *entries) -> None:
        write_tree(self.tree, {"nx.json": {"plugins": list(entries)}})

    def test_the_plugins_target_as_nx_runs_it(self):
        self.assertEqual(X.lint(self.tree, "libs/a"), (inferred("libs/a"), ["eslint.config.mjs"]))
        self.plugins({"plugin": "@nx/eslint/plugin", "options": {"targetName": "lint", "extensions": [".ts"]}},
                     {"plugin": "@nx/eslint/plugin", "options": {"targetName": "eslint"}})
        self.assertEqual(X.lint(self.tree, "libs/a")[0], inferred("libs/a"))
        # Every flat config at the root joins the inputs; a project declared by package.json alone is a project.
        write_tree(self.tree, {"eslint.config.js": ""})
        os.remove(os.path.join(self.tree, "libs/a/project.json"))
        self.assertEqual(X.lint(self.tree, "libs/a"), (inferred("libs/a"), ["eslint.config.js", "eslint.config.mjs"]))
        # An explicit target replaces the inferred one, refusals included.
        self.project(lint=LINT)  # (its flat config by Nx's name order: .js before .mjs)
        self.assertEqual(X.lint(self.tree, "libs/a")[0], eslint_cmd("eslint.config.js", "libs/a"))
        self.project(lint={"executor": "nx:run-commands"})
        self.refused(X.lint, "executor:nx:run-commands")

    def test_the_root_candidate_lints_src_then_lib(self):
        write_tree(self.tree, {"lib/x.js": ""})
        self.assertEqual(X.lint(self.tree, ".")[0], inferred(".", "./lib"))
        write_tree(self.tree, {"src/x.js": ""})
        self.assertEqual(X.lint(self.tree, ".")[0], inferred(".", "./src"))
        shutil.rmtree(os.path.join(self.tree, "src"))
        shutil.rmtree(os.path.join(self.tree, "lib"))
        write_tree(self.tree, {"x.js": ""})
        self.refused(X.lint, "no_standalone_src", ".")

    def test_plugins_outside_the_rules(self):
        for plugins, reason in [
                ("@nx/eslint/plugin", "plugins"),
                (["@nx/eslint/plugin", "@nx/jest/plugin"], "plugin:@nx/jest/plugin"),
                ([{"plugin": 5}], "plugin:5"),
                ([{"plugin": "@nx/eslint/plugin", "include": ["libs/**/*"]}], "plugin_key:include"),
                ([{"plugin": "@nx/eslint/plugin", "options": "x"}], "plugin_option:options"),
                ([{"plugin": "@nx/eslint/plugin", "options": {"cacheLocation": "x"}}], "plugin_option:cacheLocation"),
                ([{"plugin": "@nx/eslint/plugin", "options": {"targetName": 3}}], "plugin_option:targetName"),
                ([{"plugin": "@nx/eslint/plugin", "options": {"extensions": "ts"}}], "plugin_option:extensions"),
                (["@nx/eslint/plugin", {"plugin": "@nx/eslint/plugin"}], "plugin_entries"),
                ([{"plugin": "@nx/eslint/plugin", "options": {"targetName": "eslint"}}], "no_target"),
                ([], "no_target")]:
            write_tree(self.tree, {"nx.json": {"plugins": plugins}})
            self.refused(X.lint, reason)
        write_tree(self.tree, {"nx.json": {}})
        self.refused(X.lint, "no_target")

    def test_the_project_and_its_eslint_root(self):
        write_tree(self.tree, {"libs/a/package.json": package({}, name="@w/a", nx={"targets": {"lint": {}}})})
        self.refused(X.lint, "package_nx_target")
        write_tree(self.tree, {"libs/b/src/x.ts": ""})
        self.refused(X.lint, "no_target", "libs/b")
        write_tree(self.tree, {"libs/a/package.json": package({}, name="@w/a")})
        for config in ("libs/eslint.config.mjs", "libs/a/.eslintrc.json"):
            write_tree(self.tree, {config: ""})
            self.refused(X.lint, "config_below_root")
            os.remove(os.path.join(self.tree, config))
        write_tree(self.tree, {".eslintrc.yml": ""})
        self.refused(X.lint, "eslintrc")
        os.remove(os.path.join(self.tree, ".eslintrc.yml"))
        os.remove(os.path.join(self.tree, "eslint.config.mjs"))
        self.refused(X.lint, "no_target")
        write_tree(self.tree, {"eslint.config.cjs": "", "package-lock.json": lock(**{
            "node_modules/eslint": entry("eslint", "8.57.0", bin={"eslint": "bin/eslint.js"})})})
        self.refused(X.lint, "eslint_version")

    def test_a_lintable_file_of_the_project(self):
        os.remove(os.path.join(self.tree, "libs/a/src/x.ts"))
        write_tree(self.tree, {"libs/a/x.py": "", "libs/a/node_modules/m/i.js": "", "libs/a/.git/h.js": "",
                               "libs/a/sub/package.json": {}, "libs/a/sub/y.ts": "",
                               "libs/a/nest/project.json": {}, "libs/a/nest/z.tsx": "",
                               "libs/a/dir.ts/README": ""})
        self.refused(X.lint, "no_lintable_files")
        write_tree(self.tree, {"libs/a/deep/er/w.vue": ""})
        self.assertEqual(X.lint(self.tree, "libs/a")[0], inferred("libs/a"))
        self.plugins({"plugin": "@nx/eslint/plugin", "options": {"extensions": ["..py"]}})
        os.remove(os.path.join(self.tree, "libs/a/deep/er/w.vue"))
        self.assertEqual(X.lint(self.tree, "libs/a")[0], inferred("libs/a"))
        # The root's files are those under no other project: libs/a's are libs/a's.
        self.assertFalse(X.has_lintable(self.tree, ".", ["ts", "py"]))
        write_tree(self.tree, {"tools/t.ts": ""})
        self.assertTrue(X.has_lintable(self.tree, ".", ["ts"]))

    def test_target_defaults_read_for_run_commands(self):
        for defaults, reason in [({"nx:run-commands": {"dependsOn": ["^build"]}, "lint": {"cache": True}},
                                  "target_defaults_key:dependsOn"),
                                 ({"lint": {"options": {"quiet": True}}}, "target_defaults_key:options"),
                                 ({"l*": {"command": "x"}}, "target_defaults_key:command")]:
            write_tree(self.tree, {"nx.json": {"plugins": ["@nx/eslint/plugin"], "targetDefaults": defaults}})
            self.refused(X.lint, reason)
        write_tree(self.tree, {"nx.json": {"plugins": ["@nx/eslint/plugin"], "targetDefaults": {
            "@nx/eslint:lint": {"dependsOn": ["^build"]}, "lint": {"cache": True}}}})
        self.assertEqual(X.lint(self.tree, "libs/a")[0], inferred("libs/a"))

    def test_the_command_runs_from_the_candidates_directory(self):
        # The composed argv run as is, /work standing for the tree: the shell gives ESLint the candidate's directory.
        write_tree(self.tree, {"node_modules/.bin/eslint": "#!/bin/sh\npwd -P\nprintf '%s\\n' \"$@\"\n"})
        os.chmod(os.path.join(self.tree, "node_modules/.bin/eslint"), 0o755)
        # A directory name the shell would read as an option, a word break, a command or a substitution is only an
        # argument: the path is the script's $0, never its text.
        hostile = "-a b;touch x$(touch y)"
        write_tree(self.tree, {hostile + "/project.json": {"name": "h"}, hostile + "/src/x.ts": ""})
        for path in ("libs/a", hostile):
            cmd = [self.tree + e[len("/work"):] if e.startswith("/work/") else e for e in X.lint(self.tree, path)[0]]
            out = subprocess.run(cmd, cwd=self.tree, capture_output=True, text=True, check=True).stdout.splitlines()
            self.assertEqual(out, [os.path.realpath(os.path.join(self.tree, path)), ".", "--format", "json"])
            self.assertEqual([f for f in ("x", "y") if os.path.exists(os.path.join(self.tree, f))], [])


class Fit(Base):
    def test_an_nx_recipe_is_judged_like_any_other(self):
        recipe = F.compose(self.tree, "libs/a", IMAGES)
        self.assertEqual((recipe["lint_cmd"], recipe["test_cmd"], recipe["affected_test_cmd"], recipe["inputs"]),
                         (eslint_cmd("eslint.config.mjs", "libs/a"),
                          ["env", TS, "node_modules/.bin/jest", "--config", "libs/a/jest.config.ts"],
                          ["env", TS, "node_modules/.bin/jest", "--config", "libs/a/jest.config.ts"],
                          [".nvmrc", "eslint.config.mjs", "libs/a", "package-lock.json"]))
        row = {r["path"]: r for r in F.fit(self.tree, None, None, IMAGES)["rows"]}["libs/a"]
        self.assertEqual((row["reasons"], row["sources"]), ([], {"lint": "nx_target", "test": "nx_target"}))
        # The lock without jest's bin: check_recipe, the one judge, refuses the .bin path.
        write_tree(self.tree, {"package-lock.json": lock(**{
            "node_modules/eslint": entry("eslint", "9.39.4", bin={"eslint": "bin/eslint.js"})})})
        row = {r["path"]: r for r in F.fit(self.tree, None, None, IMAGES)["rows"]}["libs/a"]
        self.assertEqual(row["reasons"], ["cmd_not_installed:test_cmd:node_modules/.bin/jest",
                                          "cmd_not_installed:affected_test_cmd:node_modules/.bin/jest"])

    def test_a_project_without_a_package_json_fits_by_its_targets(self):
        """``project.json`` alone is an Nx project: a candidate by default, eligible, composed from its targets."""
        with_manifest = F.compose(self.tree, "libs/a", IMAGES)
        os.remove(os.path.join(self.tree, "libs/a/package.json"))
        out = F.fit(self.tree, None, None, IMAGES)
        row = {r["path"]: r for r in out["rows"]}["libs/a"]
        self.assertEqual((row["reasons"], row["sources"]), ([], {"lint": "nx_target", "test": "nx_target"}))
        self.assertEqual(row["recipe"], with_manifest)
        self.assertEqual(row["reasons"], U.check_recipe(row["recipe"], None, self.tree))
        # named by the operator too; a project.json that is no object is no candidate to compose for
        row = F.fit(self.tree, {"id": "t", "unit_candidates": ["libs/a"]}, None, IMAGES)["rows"][0]
        self.assertEqual((row["path"], row["reasons"]), ("libs/a", []))
        write_tree(self.tree, {"libs/a/project.json": "[]"})
        row = F.fit(self.tree, {"id": "t", "unit_candidates": ["libs/a"]}, None, IMAGES)["rows"][0]
        self.assertEqual(row["reasons"][0], "profile:units[0]:unit_not_eligible:libs/a")

    def test_the_npm_script_wins_and_sources_say_why(self):
        write_tree(self.tree, {"libs/a/package.json": package({"lint": "eslint ."}, name="@w/a")})
        sources = F.commands(self.tree, "libs/a")["sources"]
        self.assertEqual(sources, {"lint": "npm_script", "test": "nx_target"})
        recipe = F.compose(self.tree, "libs/a", IMAGES)
        self.assertEqual(recipe["lint_cmd"][:3], ["npm", "--prefix", "libs/a"])
        self.assertIn("eslint.config.mjs", recipe["inputs"])  # the script's own eslint looks the same file up
        self.project(lint={"executor": "nx:run-commands"})
        write_tree(self.tree, {"libs/a/package.json": package({}, name="@w/a")})
        row = {r["path"]: r for r in F.fit(self.tree, None, None, IMAGES)["rows"]}["libs/a"]
        self.assertEqual(row["sources"], {"lint": "none:executor:nx:run-commands", "test": "none:no_target"})
        self.assertEqual(row["recipe"]["lint_cmd"], ["npm", "--prefix", "libs/a"] + list(F.LINT_CMD))
        self.assertEqual(row["reasons"], U.check_recipe(row["recipe"], None, self.tree))
        self.assertIn("script_missing:lint_cmd:lint", row["reasons"])

    def test_an_inferred_lint_recipe_is_judged_like_any_other(self):
        write_tree(self.tree, {"nx.json": {"plugins": ["@nx/eslint/plugin"]}, "libs/a/src/x.ts": ""})
        self.project(test=JEST)
        row = {r["path"]: r for r in F.fit(self.tree, None, None, IMAGES)["rows"]}["libs/a"]
        self.assertEqual((row["reasons"], row["sources"], row["recipe"]["lint_cmd"], row["recipe"]["inputs"]),
                         ([], {"lint": "nx_target", "test": "nx_target"}, inferred("libs/a"),
                          [".nvmrc", "eslint.config.mjs", "libs/a", "package-lock.json"]))
        write_tree(self.tree, {"package-lock.json": lock(**{
            "node_modules/eslint": entry("eslint", "9.39.4"),
            "node_modules/jest": entry("jest", "30.5.2", bin={"jest": "bin/jest.js"})})})
        row = {r["path"]: r for r in F.fit(self.tree, None, None, IMAGES)["rows"]}["libs/a"]
        self.assertEqual(row["reasons"], ["cmd_not_installed:lint_cmd:/work/node_modules/.bin/eslint"])


class Deep(Base):
    """cli rule 8 at a command: a ``project.json`` nested deeper than ``cli.DEPTH`` is unusable JSON, so
    ``profile.fit`` answers for it as for a ``project.json`` that does not parse (measured before the bound: 3000
    lists deep in a lint option, ``resolved`` faulted and the command exited 2 with ``internal error``)."""

    def fit(self) -> tuple[int, bytes, bytes]:
        r = subprocess.run([sys.executable, "-m", "profile.fit", self.tree], cwd=REFEREE, capture_output=True,
                           stdin=subprocess.DEVNULL, timeout=120)
        return r.returncode, r.stdout, r.stderr

    def test_deeper_than_the_bound_answers_as_unparsable(self):
        write_tree(self.tree, {"libs/a/project.json": "{"})
        unparsable = self.fit()
        self.assertIn(unparsable[0], (0, 1))
        for lists in (cli.DEPTH, 3000):
            deep = "[" * lists + '"x"' + "]" * lists
            write_tree(self.tree, {"libs/a/project.json": '{"name": "a", "targets": {"lint": {"executor": "%s", '
                                   '"options": {"lintFilePatterns": %s}}}}' % (LINT["executor"], deep)})
            self.assertEqual(self.fit(), unparsable, lists)


if __name__ == "__main__":
    unittest.main()
