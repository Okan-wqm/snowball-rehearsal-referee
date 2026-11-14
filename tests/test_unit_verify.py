"""Test 48 (asama-0/09) and group ``recipe`` (tohum/29d): ``unit.verify``, with the fake runner.

- static check: image ``@sha256``, official ``node`` image of the toolchain's version, the nearest version
  file, ``inputs`` (valid, cover the unit, not reserved, not excluded: MF4), commands, ``services``,
  ``limits`` keys of ``operating{}`` that may tighten but not loosen, the lock and its marks (MF5);
- the run: only the inputs' closure enters the worktree (exclusions apply under ``.``), dependencies come
  from the MF5 artifact taken by its hash and are unpacked without scripts, ``.bin`` links; lint and tests
  3/3 in fresh contained runs without network, with a red control; an insufficient closure, one red
  attempt, a non-deterministic lint, a green red control and every limit are caught;
- the command line: exit 0 / 1 / 2, never a traceback.

The fake runner is ``fake_docker.py`` (Python commands only; what it does not emulate is listed there).
"""

from __future__ import annotations

import copy
import json
import os
import shutil
import subprocess
import sys
import unittest
from unittest import mock

REFEREE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REFEREE)

from profile import unit_verify as U  # noqa: E402
import refusal  # noqa: E402
from runner import contained as C  # noqa: E402
from runner import deps_npm as N  # noqa: E402
from runner import lint_record as R  # noqa: E402
from fake_docker import FakeDocker  # noqa: E402
from profile_tree import writable_base, write_tree  # noqa: E402
from test_deps_npm import sri, tgz, url  # noqa: E402

DIGEST = "@sha256:" + "ab" * 32
IMAGE = "node:20.11.1-bookworm-slim" + DIGEST

NO_VAR = {"ruleId": "no-var", "severity": 2, "line": 1, "column": 1, "fix": {"range": [0, 10], "text": "let a = 1;"}}


def lint_script(results: list, code: int = 1) -> str:
    """A lint command printing ``results`` as ESLint's ``--format json`` does, paths under ``/work``."""
    return "import sys\nsys.stdout.write(%r)\nsys.exit(%d)\n" % (json.dumps(results), code)


def eslint_result(path: str, *messages, suppressed=()) -> dict:
    return {"filePath": "/work/" + path, "messages": list(messages), "suppressedMessages": list(suppressed)}


LINT = lint_script([eslint_result("pkg/a.js", NO_VAR)])
RECORD = {"tool": "eslint", "violations": [{"rule_id": "no-var", "path": "pkg/a.js", "line": 1, "fix": [1, 1]}]}
TESTS = """import os, sys
sys.path.insert(0, "lib")
import shared
problems = []
if shared.VALUE != 42:
    problems.append("shared")
for p in ("pkg/node_modules/left-pad/index.js",):
    if not os.path.isfile(p):
        problems.append("missing " + p)
link = "pkg/node_modules/.bin/left-pad"
if not (os.path.islink(link) and os.path.isfile(link)):
    problems.append("bin link")
for p in ("other", ".claude", "CLAUDE.md", "vendored", ".git", "pkg/node_modules/stale"):
    if os.path.lexists(p):
        problems.append("present " + p)
if os.path.exists("pkg/node_modules/left-pad/BUILT"):
    print("built")
print("problems:", problems)
sys.exit(1 if problems else 0)
"""


def operating(**over) -> dict:
    values = {"unit_inputs_bytes": 10 ** 6, "deps_bytes": 10 ** 6, "worktree_bytes": 10 ** 7,
              "container_mem_bytes": 512 * 1024 * 1024, "kos_wall_s": 60, "test_total_s": 60,
              "output_bytes": 10 ** 6}
    values.update(over)
    return {k: {"value": v, "band": [1, 10 ** 12]} for k, v in values.items()}


def policy(**over) -> dict:
    return {"operating": operating(**over)}


def recipe(**over) -> dict:
    r = {"unit_id": "pkg", "path": "pkg", "inputs": ["pkg", "lib"], "toolchain": "node@20.11.1",
         "env_image": IMAGE, "lockfiles": ["pkg/package-lock.json"], "install_scripts_required": [],
         "lint_cmd": ["python", "pkg/lint.py"], "test_cmd": ["python", "pkg/run_tests.py"],
         "affected_test_cmd": ["python", "pkg/affected.py"], "services": [], "limits": {}}
    r.update(over)
    return r


RED = {"cmd": ["python", "pkg/red.py"]}


class Clockless:
    """A runner with no wall clock: the command ending in ``script`` is taken to need ``seconds`` and times out
    under any smaller timeout; every other command runs on the fake docker with no binding timeout. So a limit
    test asserts the timeout each run is given and the reason a timeout maps to, whatever the machine's load
    (a real 1 s limit timed out the red control's own python start under load; how the docker runner kills a
    container on timeout is test_contained's)."""

    def __init__(self, script: str, seconds: float) -> None:
        self.script, self.seconds, self.inner, self.timeouts = script, seconds, FakeDocker(), []

    def __call__(self, argv: list, env: dict, timeout: float) -> C.RunnerResult:
        self.timeouts.append((argv[-1], timeout))
        if argv[-1] == self.script and timeout < self.seconds:
            return C.RunnerResult(None, b"", b"", True)
        return self.inner(argv, env, 600)



def unknown_limit(name: str) -> str:
    """The reason for a ``limits`` name not in ``operating``, built so no line reads as an assignment."""
    return "limit_key_unknown" + ":" + name

class Base(unittest.TestCase):
    def setUp(self) -> None:
        self.base = writable_base("t-unit-")
        self.addCleanup(shutil.rmtree, self.base, ignore_errors=True)
        self.tree = os.path.join(self.base, "tree")
        self.pad = tgz({"package.json": {"name": "left-pad", "version": "1.3.0", "license": "MIT",
                                         "bin": "cli.js"},
                        "index.js": b"module.exports = 1\n", "cli.js": b"#!/usr/bin/env node\n"})
        self.lock = {"lockfileVersion": 3, "packages": {
            "": {"name": "pkg", "version": "1.0.0"},
            "node_modules/left-pad": {"version": "1.3.0", "resolved": url("left-pad", "1.3.0"),
                                      "integrity": sri(self.pad)}}}
        write_tree(self.tree, {
            ".nvmrc": "v20.11.1\n",
            "pkg/package.json": {"name": "pkg", "version": "1.0.0"},
            "pkg/package-lock.json": self.lock,
            "pkg/lint.py": LINT, "pkg/a.js": "var a = 1;\n", "pkg/token.js": "var a = 1;\n",
            "pkg/run_tests.py": TESTS, "pkg/affected.py": "raise SystemExit(0)\n",
            "pkg/red.py": "raise SystemExit(1)\n",
            "pkg/node_modules/stale/index.js": "stale",
            "lib/shared.py": "VALUE = 42\n",
            "other/big.txt": "x" * 100,
        })
        self.mirror = os.path.join(self.base, "mirror")
        self.put(url("left-pad", "1.3.0"), self.pad)
        self.deps = self.fetch()

    def put(self, u: str, data: bytes) -> None:
        path = os.path.join(self.mirror, *u.split("://", 1)[1].split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as fh:
            fh.write(data)

    def fetch(self, marks=None) -> str:
        out = os.path.join(self.base, "deps")
        os.makedirs(out, exist_ok=True)
        report = N.fetch(os.path.join(self.tree, "pkg", "package-lock.json"), out,
                         N.mirror_fetcher(self.mirror), marks=marks)
        self.assertTrue(report["ok"], report)
        return os.path.join(out, report["address"])

    def lock_bytes(self) -> bytes:
        with open(os.path.join(self.tree, "pkg", "package-lock.json"), "rb") as fh:
            return fh.read()

    def write_lock(self, lock: dict) -> None:
        with open(os.path.join(self.tree, "pkg", "package-lock.json"), "w", encoding="utf-8") as fh:
            json.dump(lock, fh)

    def verify(self, r=None, pol=None, runner=None, red=RED, deps="default", **kw) -> dict:
        self.runner = runner or FakeDocker()
        return U.verify(r or recipe(), self.tree, pol or policy(), red,
                        self.deps if deps == "default" else deps, runner=self.runner, base=self.base, **kw)


# ---------------------------------------------------------------- static check

class StaticCheck(Base):
    def reasons(self, pol=None, tree=False, **over) -> list:
        return U.check_recipe(recipe(**over), pol, self.tree if tree else None)

    def test_good_recipe_passes_without_and_with_tree(self):
        self.assertEqual(self.reasons(), [])
        self.assertEqual(self.reasons(pol=policy(), tree=True), [])

    def test_every_field_required_and_no_other(self):
        r = recipe()
        del r["services"]
        r["install_cmd"] = ["npm", "ci"]
        self.assertEqual(U.check_recipe(r), ["missing:services", "field_not_in_recipe:install_cmd"])
        self.assertEqual(U.check_recipe(["not", "an", "object"]), ["malformed:recipe"])

    def test_image_must_be_pinned_official_and_the_toolchain_version(self):
        cases = {
            "node:20.11.1": "image_not_pinned",
            "node:20.11.1@sha256:" + "AB" * 32: "image_not_pinned",
            "node@sha256:" + "ab" * 31: "image_not_pinned",
            "myorg/node:20.11.1" + DIGEST: "image_not_official",
            "ghcr.io/library/node:20.11.1" + DIGEST: "image_not_official",
            "nodejs:20.11.1" + DIGEST: "image_not_official",
            "node:20.11.0" + DIGEST: "image_version_mismatch",
            "node:20.11.10" + DIGEST: "image_version_mismatch",
            "node:20.11.1alpine" + DIGEST: "image_version_mismatch",
            "node" + DIGEST: "image_version_mismatch",
            "node:lts" + DIGEST: "image_version_mismatch",
        }
        for image, reason in cases.items():
            with self.subTest(image=image):
                self.assertEqual(self.reasons(env_image=image), [reason])
        for image in ("node:20.11.1" + DIGEST, "docker.io/library/node:20.11.1-alpine3.19" + DIGEST):
            with self.subTest(image=image):
                self.assertEqual(self.reasons(env_image=image), [])

    def test_toolchain_is_exact_node_version(self):
        for tc in ("node@20", "node@v20.11.1", "python@3.12.0", "node 20.11.1", 20,
                   "node@20.11", "node@20.11.1.0", "node@20.11.1-rc.1", "node@20.11.1 ", "node@^20.11.1"):
            with self.subTest(tc=tc):
                self.assertIn("invalid:toolchain", self.reasons(toolchain=tc))

    def test_inputs(self):
        self.assertEqual(self.reasons(inputs=["lib"]), ["inputs_miss_unit_path", "lockfile_not_in_inputs"])
        self.assertIn("invalid:inputs", self.reasons(inputs=["pkg", "../outside"]))
        self.assertIn("invalid:inputs", self.reasons(inputs=["/pkg"]))
        self.assertIn("invalid:inputs", self.reasons(inputs=[]))
        self.assertIn("invalid:inputs", self.reasons(inputs="pkg"))
        self.assertEqual(self.reasons(inputs=["pkg", ".snowball/x"]), ["reserved_path"])
        self.assertEqual(self.reasons(inputs=["pkg", ".SNOWBALL"]), ["reserved_path"])
        self.assertEqual(self.reasons(inputs=["."]), [])

    def test_commands(self):
        for field in ("lint_cmd", "test_cmd"):
            for bad in ([], "npm test", ["npm", ""], ["npm", 3], ["npm\x00x"], None):
                with self.subTest(field=field, bad=bad):
                    self.assertEqual(self.reasons(**{field: bad}), ["invalid:%s" % field])
        for bad in ([], "npm test", ["npm", ""]):
            with self.subTest(field="affected_test_cmd", bad=bad):
                self.assertEqual(self.reasons(affected_test_cmd=bad), ["invalid:affected_test_cmd"])

    def test_services_empty_in_stage_0(self):
        self.assertEqual(self.reasons(services=["postgres"]), ["services_not_empty"])
        self.assertEqual(self.reasons(services={}), ["services_not_empty"])

    def test_limits_are_operating_keys_that_only_tighten(self):
        self.assertEqual(self.reasons(limits={"cpu_s": 3}), ["limit_key_unknown:cpu_s"])
        self.assertEqual(self.reasons(limits={"kos_wall_s": True}), ["invalid:limits.kos_wall_s"])
        self.assertEqual(self.reasons(limits={"kos_wall_s": 0}), ["invalid:limits.kos_wall_s"])
        self.assertEqual(self.reasons(limits=[]), ["invalid:limits"])
        self.assertEqual(self.reasons(pol=policy(), limits={"kos_wall_s": 61}), ["limit_above_operating:kos_wall_s"])
        tight = policy()
        tight["operating"]["kos_wall_s"]["band"] = [10, 100]
        self.assertEqual(self.reasons(pol=tight, limits={"kos_wall_s": 9}), ["limit_below_band:kos_wall_s"])
        self.assertEqual(self.reasons(pol=tight, limits={"kos_wall_s": 10}), [])
        self.assertEqual(self.reasons(limits={k: 5 for k in U.OPERATING_NAMES}), [])

    def test_lockfiles(self):
        self.assertEqual(self.reasons(lockfiles=["pkg/package-lock.json", "pkg/npm-shrinkwrap.json"]),
                         ["invalid:lockfiles"])
        self.assertEqual(self.reasons(lockfiles=["pkg/yarn.lock"]), ["invalid:lockfiles"])
        self.assertEqual(self.reasons(lockfiles=["other/package-lock.json"]),
                         ["lockfile_not_in_inputs", "lockfile_not_for_unit"])
        self.assertEqual(self.reasons(inputs=["pkg", "lib", "other"], lockfiles=["other/package-lock.json"]),
                         ["lockfile_not_for_unit"])
        self.assertEqual(self.reasons(inputs=["."], lockfiles=["package-lock.json"]), [])

    def test_nearest_version_file_must_be_exact_and_equal(self):
        self.assertEqual(self.reasons(tree=True), [])
        write_tree(self.tree, {"pkg/.node-version": "20.11.0"})
        self.assertEqual(self.reasons(tree=True), ["toolchain_version_mismatch"])
        write_tree(self.tree, {"pkg/.nvmrc": "20.11.1"})
        self.assertEqual(self.reasons(tree=True), [], "in one directory .nvmrc comes before .node-version")
        for text in ("lts/*", "20", "20.11", "node", "20.11.1.1", "^20.11.1", "~20.11.1", ">=20.11.1",
                     "20.11.1 || 22.0.0"):
            write_tree(self.tree, {"pkg/.nvmrc": text})
            with self.subTest(text=text):
                self.assertEqual(self.reasons(tree=True), ["version_file_not_exact"])
        os.remove(os.path.join(self.tree, "pkg/.nvmrc"))
        os.remove(os.path.join(self.tree, "pkg/.node-version"))
        os.remove(os.path.join(self.tree, ".nvmrc"))
        write_tree(self.tree, {".tool-versions": "python 3.12.0\nnodejs 20.11.1\n"})
        self.assertEqual(self.reasons(tree=True), [])
        os.remove(os.path.join(self.tree, ".tool-versions"))
        reasons = self.reasons(tree=True)
        self.assertIn("version_file_missing", reasons)

    def test_with_tree_profile_and_lock_are_judged(self):
        write_tree(self.tree, {".claude/settings.json": "{}"})
        self.assertIn("profile:units[0]:input_excluded:.claude", self.reasons(tree=True, inputs=["pkg", ".claude"]))
        self.assertIn("profile:units[0]:input_missing:nope", self.reasons(tree=True, inputs=["pkg", "nope"]))
        write_tree(self.tree, {"other/package.json": {"name": "other"}})
        reasons = self.reasons(tree=True, path="other", inputs=["other", "lib"], lockfiles=["other/package-lock.json"])
        self.assertIn("profile:units[0]:unit_not_eligible:other", reasons)
        self.assertIn("lockfile_missing", reasons)
        lock = copy.deepcopy(self.lock)
        lock["packages"]["node_modules/left-pad"]["hasInstallScript"] = True
        self.write_lock(lock)
        self.assertEqual(self.reasons(tree=True), ["lock:install_script_not_marked:node_modules/left-pad"])
        self.assertEqual(self.reasons(tree=True, install_scripts_required=["left-pad@1.3.0"]), [])
        self.assertEqual(self.reasons(tree=True, install_scripts_required=["node_modules/left-pad"]), [])
        self.assertEqual(self.reasons(tree=True, install_scripts_required=["left-pad@1.3.0", "left-pad"]),
                         ["lock:mark_not_usable:left-pad"])
        os.remove(os.path.join(self.tree, "pkg/package-lock.json"))
        os.symlink("../lib/shared.py", os.path.join(self.tree, "pkg/package-lock.json"))
        self.assertIn("lockfile_missing", self.reasons(tree=True))


class CommandsAgainstLock(Base):
    """``cmd_not_installed``: a ``node_modules`` path in a command must be one the lock installs."""

    def reasons(self, **over) -> list:
        return U.check_recipe(recipe(**over), None, self.tree)

    def rich(self) -> dict:
        """A lock with a bin by string, a scoped package with a bin object, and a nested package."""
        tool = tgz({"package.json": {"name": "@s/tool", "version": "1.0.0", "bin": {"tl": "t.js"}}, "t.js": b"x"})
        inner = tgz({"package.json": {"name": "inner", "version": "2.0.0", "bin": "i.js"}, "i.js": b"x"})
        self.put(url("@s/tool", "1.0.0"), tool)
        self.put(url("inner", "2.0.0"), inner)
        lock = copy.deepcopy(self.lock)
        lock["packages"]["node_modules/left-pad"]["bin"] = {"left-pad": "cli.js"}
        lock["packages"]["node_modules/@s/tool"] = {"version": "1.0.0", "resolved": url("@s/tool", "1.0.0"),
                                                    "integrity": sri(tool), "bin": {"tl": "t.js"}}
        lock["packages"]["node_modules/left-pad/node_modules/inner"] = {
            "version": "2.0.0", "resolved": url("inner", "2.0.0"), "integrity": sri(inner), "bin": "i.js"}
        lock["packages"]["node_modules/ghost/node_modules/inner"] = dict(
            lock["packages"]["node_modules/left-pad/node_modules/inner"])  # its parent is no key of the lock
        self.write_lock(lock)
        return lock

    def test_a_package_of_the_lock_is_installed_and_another_is_not(self):
        self.assertEqual(self.reasons(lint_cmd=["node", "pkg/node_modules/left-pad/cli.js", "--format", "json"]), [])
        self.assertEqual(self.reasons(lint_cmd=["node", "pkg/node_modules/eslint/bin/eslint.js", "pkg"]),
                         ["cmd_not_installed:lint_cmd:pkg/node_modules/eslint/bin/eslint.js"])
        self.assertEqual(self.reasons(lint_cmd=["node", "/work/pkg/node_modules/eslint/bin/eslint.js"]),
                         ["cmd_not_installed:lint_cmd:/work/pkg/node_modules/eslint/bin/eslint.js"])
        self.assertEqual(self.reasons(lint_cmd=["node", "/work/pkg/node_modules/left-pad/cli.js"]), [])

    def test_every_command_field_is_judged_and_every_element_listed(self):
        bad = "pkg/node_modules/vitest/vitest.mjs"
        self.assertEqual(self.reasons(lint_cmd=["node", bad], test_cmd=["node", bad, "pkg/node_modules/x"],
                                      affected_test_cmd=["node", bad]),
                         ["cmd_not_installed:lint_cmd:" + bad, "cmd_not_installed:test_cmd:" + bad,
                          "cmd_not_installed:test_cmd:pkg/node_modules/x",
                          "cmd_not_installed:affected_test_cmd:" + bad])

    def test_a_path_outside_the_locks_directory_is_not_installed(self):
        for element in ("node_modules/left-pad/cli.js", "lib/node_modules/left-pad/cli.js",
                        "other/pkg/node_modules/left-pad/cli.js", "pkgx/node_modules/left-pad/cli.js"):
            self.assertEqual(self.reasons(test_cmd=["node", element]), ["cmd_not_installed:test_cmd:" + element])

    def test_a_case_variant_of_node_modules_is_not_installed(self):
        for element in ("pkg/Node_Modules/left-pad/cli.js", "pkg/node_modules/Left-Pad/cli.js"):
            self.assertEqual(self.reasons(test_cmd=[element]), ["cmd_not_installed:test_cmd:" + element])

    def test_a_nested_package_only_by_its_own_key(self):
        self.rich()
        for element in ("pkg/node_modules/left-pad/node_modules/inner/i.js", "pkg/node_modules/@s",
                        "pkg/node_modules/ghost", "pkg/node_modules/left-pad/node_modules"):
            self.assertEqual(self.reasons(test_cmd=["node", element]), [], element)
        for element in ("pkg/node_modules/left-pad/node_modules/other/i.js", "pkg/node_modules/@s/tool/node_modules/x",
                        "pkg/node_modules/@s/other/t.js", "pkg/node_modules/gho"):
            self.assertEqual(self.reasons(test_cmd=["node", element]), ["cmd_not_installed:test_cmd:" + element])

    def test_bin_links_by_the_locks_bin(self):
        self.assertEqual(self.reasons(test_cmd=["pkg/node_modules/.bin/left-pad"]),
                         ["cmd_not_installed:test_cmd:pkg/node_modules/.bin/left-pad"], "no bin in the lock")
        self.rich()
        for ok in ("pkg/node_modules/.bin/left-pad", "pkg/node_modules/.bin/tl",
                   "pkg/node_modules/left-pad/node_modules/.bin/inner",
                   "pkg/node_modules/ghost/node_modules/.bin/inner"):
            self.assertEqual(self.reasons(test_cmd=[ok]), [], ok)
        for bad in ("pkg/node_modules/.bin/tool", "pkg/node_modules/.bin/inner", "pkg/node_modules/.bin/i.js",
                    "pkg/node_modules/left-pad/node_modules/.bin/left-pad",
                    "pkg/node_modules/zz/node_modules/.bin/inner",
                    "pkg/node_modules/.bin/tl/x", "node_modules/.bin/tl"):
            self.assertEqual(self.reasons(test_cmd=[bad]), ["cmd_not_installed:test_cmd:" + bad], bad)

    def test_a_string_bin_is_named_after_the_entrys_name(self):
        lock = copy.deepcopy(self.lock)
        lock["packages"]["node_modules/left-pad"].update(bin="cli.js", name="@x/padder",
                                                         resolved=url("@x/padder", "1.3.0"))
        self.write_lock(lock)
        self.assertEqual(self.reasons(test_cmd=["pkg/node_modules/.bin/padder"]), [])
        self.assertEqual(self.reasons(test_cmd=["pkg/node_modules/.bin/left-pad"]),
                         ["cmd_not_installed:test_cmd:pkg/node_modules/.bin/left-pad"])

    def test_elements_that_are_not_node_modules_paths_are_not_judged(self):
        for element in ("python", "--format", "pkg/lint.py", "/usr/lib/node_modules/npm/bin/npm-cli.js",
                        "../node_modules/x", "--config=pkg/node_modules/x", "npx", "vitest"):
            self.assertEqual(self.reasons(test_cmd=["node", element]), [], element)

    def test_listed_beside_the_locks_own_reasons(self):
        lock = copy.deepcopy(self.lock)
        lock["packages"]["node_modules/left-pad"]["hasInstallScript"] = True
        self.write_lock(lock)
        self.assertEqual(self.reasons(test_cmd=["pkg/node_modules/eslint/x"]),
                         ["lock:install_script_not_marked:node_modules/left-pad",
                          "cmd_not_installed:test_cmd:pkg/node_modules/eslint/x"])

    def test_the_rule_agrees_with_what_the_install_writes(self):
        """Every probe the rule calls installed exists in the staged worktree, and none it refuses does."""
        self.rich()
        self.deps = self.fetch()
        probes = ["pkg/node_modules/left-pad", "pkg/node_modules/left-pad/cli.js", "pkg/node_modules/@s/tool/t.js",
                  "pkg/node_modules/left-pad/node_modules/inner/i.js", "pkg/node_modules/.bin/left-pad",
                  "pkg/node_modules/.bin/tl", "pkg/node_modules/left-pad/node_modules/.bin/inner",
                  "pkg/node_modules/.bin/tool", "pkg/node_modules/.bin/inner", "pkg/node_modules/eslint/x",
                  "pkg/node_modules/stale/index.js", "node_modules/left-pad/cli.js", "pkg/Node_Modules/left-pad/cli.js",
                  "pkg/node_modules/@s/other", "pkg/node_modules/left-pad/node_modules/.bin/left-pad",
                  "pkg/node_modules/ghost/node_modules/.bin/inner", "pkg/node_modules/ghost",
                  "pkg/node_modules/zz/node_modules/.bin/inner"]
        root = os.path.join(self.base, "stage")
        os.mkdir(root)
        reasons, _, context = U.stage(recipe(), self.tree, policy(), RED, self.deps, None, FakeDocker(), root)
        self.assertEqual(reasons, [])
        lock = json.loads(self.lock_bytes())
        for probe in probes:
            self.assertEqual(U.installed(probe, "pkg", lock),
                             os.path.lexists(os.path.join(context["staging"], probe)), probe)


class Workspaces(Base):
    """npm workspaces (tohum/29g) in the static rules and the staging: the link becomes a symlink to its folder,
    a nested package is unpacked under its key with its own ``.bin``, and the rules agree with what is written."""

    def setUp(self) -> None:
        super().setUp()
        self.deep = tgz({"package.json": {"name": "deep", "version": "4.0.0", "bin": "cli.js"}, "cli.js": b"x"})
        self.put(url("deep", "4.0.0"), self.deep)
        lock = copy.deepcopy(self.lock)
        lock["packages"][""]["workspaces"] = ["libs/ui"]
        lock["packages"]["node_modules/left-pad"]["bin"] = {"left-pad": "cli.js"}  # as npm writes the tarball's
        lock["packages"]["node_modules/@acme/ui"] = {"resolved": "libs/ui", "link": True}
        lock["packages"]["libs/ui"] = {"name": "@acme/ui", "version": "1.0.0", "devDependencies": {"deep": "4.0.0"}}
        lock["packages"]["libs/ui/node_modules/deep"] = {"version": "4.0.0", "resolved": url("deep", "4.0.0"),
                                                         "integrity": sri(self.deep), "bin": {"deep": "cli.js"}}
        self.write_lock(lock)
        write_tree(self.tree, {"pkg/libs/ui/package.json": {"name": "@acme/ui", "version": "1.0.0",
                                                            "scripts": {"lint": "deep src", "test": "left-pad"},
                                                            "devDependencies": {"deep": "4.0.0"}},
                               "pkg/libs/ui/index.js": "module.exports = 2\n",
                               "pkg/package.json": {"name": "pkg", "version": "1.0.0",
                                                    "devDependencies": {"left-pad": "1.3.0"}}})
        self.deps = self.fetch()

    def staged(self) -> str:
        root = os.path.join(self.base, "stage")
        os.mkdir(root)
        reasons, _, context = U.stage(recipe(), self.tree, policy(), RED, self.deps, None, FakeDocker(), root)
        self.assertEqual(reasons, [])
        return context["staging"]

    def test_the_link_is_a_symlink_to_its_folder_and_the_nested_package_is_under_its_key(self):
        staging = self.staged()
        link = os.path.join(staging, "pkg/node_modules/@acme/ui")
        self.assertEqual(os.readlink(link), "../../libs/ui")
        with open(os.path.join(link, "index.js")) as fh:
            self.assertEqual(fh.read(), "module.exports = 2\n")
        self.assertTrue(os.path.isfile(os.path.join(staging, "pkg/libs/ui/node_modules/deep/cli.js")))
        self.assertEqual(os.readlink(os.path.join(staging, "pkg/libs/ui/node_modules/.bin/deep")), "../deep/cli.js")

    def test_an_entry_already_at_the_link_refuses_the_artifact(self):
        staging = os.path.join(self.base, "stage")
        os.makedirs(os.path.join(staging, "pkg/node_modules/@acme/ui"))
        bad, _ = U.install_deps(staging, "pkg/package-lock.json", self.deps, self.lock_bytes(), 10 ** 7)
        self.assertEqual(bad, ["deps_unpack_unsafe:node_modules/@acme/ui"])
        self.assertEqual(os.listdir(os.path.join(staging, "pkg/node_modules/@acme/ui")), [])

    def test_a_link_the_live_path_does_not_take_is_refused_before_staging(self):
        lock = json.loads(self.lock_bytes())
        lock["packages"]["node_modules/@acme/ui"]["resolved"] = "../ui"
        self.write_lock(lock)
        self.assertIn("lock:file_dependency:node_modules/@acme/ui", U.check_recipe(recipe(), None, self.tree))

    def test_a_members_script_finds_its_own_nested_bin(self):
        member = "pkg/libs/ui"
        reasons = U.check_recipe(recipe(lint_cmd=npm_run("lint", member), test_cmd=npm_run("test", member),
                                        affected_test_cmd=npm_run("test", member)), None, self.tree)
        self.assertEqual(reasons, [])
        lock = json.loads(self.lock_bytes())
        del lock["packages"]["libs/ui/node_modules/deep"]["bin"]
        self.write_lock(lock)
        reasons = U.check_recipe(recipe(lint_cmd=npm_run("lint", "pkg/libs/ui")), None, self.tree)
        self.assertEqual(reasons, ["script_not_installed:lint_cmd:deep"])

    def test_the_rule_agrees_with_what_the_install_writes(self):
        staging = self.staged()
        lock = json.loads(self.lock_bytes())
        for probe in ("pkg/node_modules/@acme/ui", "pkg/node_modules/@acme", "pkg/libs/ui/node_modules/deep/cli.js",
                      "pkg/libs/ui/node_modules/.bin/deep", "pkg/libs/ui/node_modules",
                      "pkg/libs/ui/node_modules/other", "pkg/libs/x/node_modules/deep",
                      "pkg/node_modules/.bin/deep", "pkg/node_modules/deep", "pkg/libs/ui/node_modules/.bin/left-pad"):
            self.assertEqual(U.installed(probe, "pkg", lock), os.path.lexists(os.path.join(staging, probe)), probe)


def npm_run(script: str, directory: str = "pkg", *rest: str) -> list:
    return ["npm", "--prefix", directory, "run", "--silent", script] + list(rest)


class NpmRunScripts(Base):
    """``script_missing`` / ``script_not_installed``: an ``npm --prefix D run --silent S`` command's script exists
    and every program of it known as an npm program is on npm's PATH in the worktree."""

    def setUp(self) -> None:
        super().setUp()
        self.eslint = {"version": "9.0.0", "resolved": url("eslint", "9.0.0"), "integrity": sri(b"e"),
                       "bin": {"eslint": "bin/eslint.js"}}
        self.manifest({"lint": "eslint src", "test": "node --test"}, devDependencies={"eslint": "9.0.0"})

    def manifest(self, scripts: dict, where: str = "pkg", **fields) -> None:
        write_tree(self.tree, {where + "/package.json": dict({"name": "pkg", "version": "1.0.0", "scripts": scripts},
                                                             **fields)})

    def reasons(self, **over) -> list:
        return U.check_recipe(recipe(**dict({"lint_cmd": npm_run("lint", "pkg", "--", "--format", "json"),
                                             "test_cmd": npm_run("test"), "affected_test_cmd": npm_run("test")},
                                            **over)), None, self.tree)

    def with_eslint(self, key: str = "node_modules/eslint") -> None:
        lock = copy.deepcopy(self.lock)
        lock["packages"][key] = self.eslint
        self.write_lock(lock)

    def test_the_command_form(self):
        self.assertEqual(U.npm_run(npm_run("lint")), ("pkg", "lint"))
        self.assertEqual(U.npm_run(npm_run("lint", "/work/pkg", "--", "--format", "json")), ("pkg", "lint"))
        self.assertEqual(U.npm_run(npm_run("test", ".")), (".", "test"))
        for argv in (["npm", "run", "--silent", "lint"], ["npm", "--prefix", "pkg", "run", "lint"],
                     ["npm", "--prefix", "pkg", "run-script", "--silent", "lint"], npm_run("lint", "pkg", "x"),
                     npm_run("-lint"), npm_run("lint", "/elsewhere"), npm_run("lint", "../up"),
                     ["npx", "--prefix", "pkg", "run", "--silent", "lint"]):
            self.assertIsNone(U.npm_run(argv), argv)

    def test_the_programs_of_a_script(self):
        cases = {"eslint src": ["eslint"], "vitest run": ["vitest"],
                 "a x && b || c; d | e & f": ["a", "b", "c", "d", "e", "f"],
                 "FOO=1 BAR='x y' vitest run": ["vitest"], "eslint . 2>&1 > out.txt": ["eslint"],
                 "jest >out <in": ["jest"], "(cd sub && jest)": ["cd", "jest"], "a&&b": ["a", "b"],
                 "node tools/run.mjs nx affected": ["node"], "": [], "tsc -p . ; ": ["tsc"]}
        for text, programs in cases.items():
            self.assertEqual(U.script_programs(text), programs, text)
        self.assertIsNone(U.script_programs("eslint 'src"))

    def test_a_declared_program_the_lock_does_not_install_is_refused(self):
        self.assertEqual(self.reasons(), ["script_not_installed:lint_cmd:eslint"])
        self.with_eslint()
        self.assertEqual(self.reasons(), [])

    def test_a_program_declared_above_the_directory_is_judged(self):
        """A workspace member's tools are declared at the root (the class f409 measured on the target)."""
        self.manifest({"lint": "vitest run && eslint src", "test": "node --test"})
        write_tree(self.tree, {"package.json": {"name": "root", "devDependencies": {"vitest": "1", "eslint": "9"}}})
        self.assertEqual(self.reasons(),
                         ["script_not_installed:lint_cmd:vitest", "script_not_installed:lint_cmd:eslint"])

    def test_a_bin_name_of_a_lock_above_is_judged(self):
        self.manifest({"lint": "tsc --noEmit", "test": "node --test"})
        write_tree(self.tree, {"package-lock.json": {"lockfileVersion": 3, "packages": {
            "": {}, "node_modules/typescript": {"version": "5.0.0", "bin": {"tsc": "bin/tsc"}}}}})
        self.assertEqual(self.reasons(), ["script_not_installed:lint_cmd:tsc"])

    def test_a_program_known_nowhere_is_not_judged(self):
        self.manifest({"lint": "rm -rf out && mytool src && node_modules/.bin/eslint && $X", "test": "node --test"})
        self.assertEqual(self.reasons(), [])

    def test_only_the_locks_top_level_bin_is_on_the_path(self):
        self.with_eslint("node_modules/left-pad/node_modules/eslint")
        self.assertEqual(self.reasons(), ["script_not_installed:lint_cmd:eslint"])

    def test_a_directory_the_locks_node_modules_is_not_above(self):
        self.with_eslint()
        self.manifest({"lint": "eslint src"}, where="lib", devDependencies={"eslint": "9.0.0"})
        self.assertEqual(self.reasons(lint_cmd=npm_run("lint", "lib")), ["script_not_installed:lint_cmd:eslint"])
        self.manifest({"lint": "eslint src"}, where="pkg/sub", devDependencies={"eslint": "9.0.0"})
        self.assertEqual(self.reasons(lint_cmd=npm_run("lint", "pkg/sub")), [])

    def test_a_missing_script_and_every_field(self):
        self.with_eslint()
        self.assertEqual(self.reasons(test_cmd=npm_run("unit"), affected_test_cmd=npm_run("lint", "lib")),
                         ["script_missing:test_cmd:unit", "script_missing:affected_test_cmd:lint"])
        write_tree(self.tree, {"pkg/package.json": "not json"})
        self.assertEqual(self.reasons(), ["profile:units[0]:unit_not_eligible:pkg", "script_missing:lint_cmd:lint",
                                          "script_missing:test_cmd:test", "script_missing:affected_test_cmd:test"])

    def test_an_unreadable_script_is_not_judged(self):
        self.manifest({"lint": "eslint 'src", "test": "node --test"}, devDependencies={"eslint": "9.0.0"})
        self.assertEqual(self.reasons(), [])


class TreeChecksBesideOtherReasons(Base):
    """Reasons about fields the tree checks never read do not hide the tree's reasons."""

    def test_tree_reasons_listed_beside_image_limits_services_and_id(self):
        write_tree(self.tree, {"pkg/.nvmrc": "20.11.0"})
        r = recipe(env_image="node:20.11.1", unit_id="-x", services=["pg"], limits={"cpu_s": 1})
        self.assertEqual(U.check_recipe(r, None, self.tree),
                         ["invalid:unit_id", "image_not_pinned", "services_not_empty", "limit_key_unknown:cpu_s",
                          "toolchain_version_mismatch"])

    def test_a_field_the_tree_checks_read_still_stops_them(self):
        write_tree(self.tree, {"pkg/.nvmrc": "20.11.0"})
        for over, reasons in (({"lockfiles": ["pkg/yarn.lock"]}, ["invalid:lockfiles"]),
                              ({"toolchain": "node@20"}, ["invalid:toolchain", "image_version_mismatch"]),
                              ({"test_cmd": []}, ["invalid:test_cmd"]),
                              ({"extra": 1}, ["field_not_in_recipe:extra"])):
            self.assertEqual(U.check_recipe(recipe(**over), None, self.tree), reasons, over)
        r = recipe()
        del r["path"]
        self.assertEqual(U.check_recipe(r, None, self.tree), ["missing:path"])


# ---------------------------------------------------------------- the run

class Run(Base):
    def test_verified_3_of_3_contained_with_only_the_inputs(self):
        report = self.verify()
        self.assertEqual(report["verdict"], "verified", report)
        self.assertEqual(len(report["runs"]["lint"]), 3)
        self.assertEqual(len(report["runs"]["test"]), 3)
        self.assertTrue(all(r["exit"] == 1 for r in report["runs"]["lint"]))
        self.assertTrue(all(r["exit"] == 0 for r in report["runs"]["test"]))
        self.assertTrue(all(r["red_control_exit"] == 1 for r in report["runs"]["test"]))
        self.assertEqual(report["deps_address"], os.path.basename(self.deps))
        self.assertEqual(report["bin_links"], ["pkg/node_modules/.bin/left-pad"])
        self.assertEqual(report["recipe"], recipe())
        self.assertEqual(report["recipe_sha256"], __import__("hashlib").sha256(U.canonical(recipe())).hexdigest())
        calls = self.runner.calls
        self.assertEqual(len(calls), 12, "every command and its red control, each in its own run")
        roots = set()
        for call in calls:
            argv = call["argv"]
            self.assertTrue(C.check_argv(argv)["ok"])
            self.assertEqual(argv[argv.index("--network") + 1], "none")
            self.assertIn(IMAGE, argv)
            self.assertIn("--env", argv)
            self.assertEqual(call["container_env"]["HOME"], "/work/.snowball/home")
            roots.add(call["mounts"][0]["src"])
            self.assertNotIn("affected.py", " ".join(argv))
        self.assertEqual(len(roots), 12, "a fresh host directory per run")
        self.assertFalse(any(os.path.exists(r) for r in roots), "run directories are removed afterwards")
        self.assertIn(b"problems: []", calls[3]["stdout"])

    def test_exclusions_apply_under_dot(self):
        write_tree(self.tree, {".claude/x": "x", "CLAUDE.md": "x", "vendored/x.js": "x", ".git/HEAD": "x"})
        target = {"excluded_paths": ["vendored"]}
        r = recipe(inputs=["."])
        report = self.verify(r, target=target)
        self.assertEqual(report["verdict"], "refused", "other/ is an input now")
        self.assertIn(b"problems: ['present other']", self.runner.calls[3]["stdout"])

    def test_insufficient_inputs_closure_is_refused(self):
        report = self.verify(recipe(inputs=["pkg"]))
        self.assertEqual(report["verdict"], "refused")
        self.assertEqual(report["reasons"], ["test_red:1", "test_red:2", "test_red:3"])
        self.assertNotIn("recipe", report)

    def test_one_red_attempt_of_three_is_refused(self):
        inner = FakeDocker()
        seen = []

        def flaky(argv, env, timeout):
            res = inner(argv, env, timeout)
            if argv[-1] == "pkg/run_tests.py":
                seen.append(1)
                if len(seen) == 2:
                    return C.RunnerResult(1, res.stdout, res.stderr, False)
            return res
        report = self.verify(runner=flaky)
        self.assertEqual(report["reasons"], ["test_red:2"])
        self.assertEqual(report["verdict"], "refused")

    def test_lint_must_finish_and_be_deterministic(self):
        inner = FakeDocker()
        seen = []

        def vary(argv, env, timeout):
            res = inner(argv, env, timeout)
            if argv[-1] == "pkg/lint.py":
                seen.append(1)
                if len(seen) == 3:
                    return C.RunnerResult(res.exit, res.stdout + b"extra\n", res.stderr, False)
            return res
        self.assertEqual(self.verify(runner=vary)["reasons"], ["lint_not_deterministic"])
        write_tree(self.tree, {"pkg/lint.py": "raise SystemExit(2)\n"})
        report = self.verify()
        self.assertEqual(report["reasons"], ["lint_failed:1", "lint_failed:2", "lint_failed:3"])
        write_tree(self.tree, {"pkg/lint.py": LINT})
        self.assertEqual(self.verify()["verdict"], "verified")

    def test_lint_runs_must_agree_on_the_exit_code(self):
        """tohum/26c "Birim tarifi": the three runs end with the same exit code; 0 and 1 are each green, a mix of
        them over the same stdout is not."""
        inner = FakeDocker()
        exits = []

        def flip(argv, env, timeout):
            res = inner(argv, env, timeout)
            if argv[-1] == "pkg/lint.py":
                exits.append(res.exit)
                if len(exits) == 3:
                    return C.RunnerResult(1 - res.exit, res.stdout, res.stderr, False)
            return res
        self.assertEqual(self.verify(runner=flip)["reasons"], ["lint_not_deterministic"])
        self.assertEqual(sorted(set(exits)), [1], "the fixture's lint exits 1 on its finding, so the third was 0")

    def test_lint_records_are_in_the_verified_report(self):
        report = self.verify()
        self.assertEqual(report["lint_records"], [RECORD] * 3)
        self.assertEqual(R.run_file(report["lint_records"]).split(b"\n")[:3], [R.line(RECORD)] * 3)

    def test_unit_criteria_4_and_5_on_the_lint_output(self):
        """asama-0/08 unit selection: the tool gives rule, line and fix (4); a fixable violation outside the
        security path, inside the inputs (5)."""
        no_fix = dict(NO_VAR, fix=None)
        cases = [
            ("print('pkg/a.js:1:1 no-var')\nraise SystemExit(1)\n", ["lint_output:not_eslint_json"]),
            (lint_script([], 0), ["no_fixable_violation"]),
            (lint_script([eslint_result("pkg/a.js", no_fix)]), ["no_fixable_violation"]),
            (lint_script([eslint_result("pkg/token.js", NO_VAR)]), ["no_fixable_violation"]),
            (lint_script([eslint_result("pkg/a.js", dict(NO_VAR, ruleId=None, fatal=True))]),
             ["lint_output:fatal:pkg/a.js"]),
            (lint_script([eslint_result("other/big.txt", NO_VAR)]), ["lint_output:file_unreadable:other/big.txt"]),
            (lint_script([eslint_result("pkg/a.js", dict(NO_VAR, line=3))]),
             ["lint_output:message_unusable:pkg/a.js"]),
        ]
        for script, reasons in cases:
            write_tree(self.tree, {"pkg/lint.py": script})
            report = self.verify()
            self.assertEqual((report["verdict"], report["reasons"]), ("refused", reasons), script)
            self.assertNotIn("lint_records", report)
        both = [eslint_result("pkg/token.js", NO_VAR), eslint_result("pkg/a.js", no_fix, suppressed=[NO_VAR])]
        write_tree(self.tree, {"pkg/lint.py": lint_script(both)})
        report = self.verify()
        self.assertEqual(report["verdict"], "verified", report["reasons"])
        self.assertEqual([v["path"] for v in report["lint_records"][0]["violations"]],
                         ["pkg/token.js", "pkg/a.js", "pkg/a.js"])

    def test_an_invalid_lint_run_is_no_verdict_not_a_lint_difference(self):
        inner = FakeDocker()
        seen = []

        def stall(argv, env, timeout):
            if argv[-1] == "pkg/lint.py":
                seen.append(1)
                if len(seen) == 2:
                    return C.RunnerResult(None, b"", b"", True)
            return inner(argv, env, timeout)
        report = self.verify(runner=stall)
        self.assertEqual((report["verdict"], report["reasons"]), ("no_verdict", ["limit_hit:kos_wall_s"]))

    def test_green_red_control_is_no_verdict(self):
        write_tree(self.tree, {"pkg/green.py": "raise SystemExit(0)\n"})
        report = self.verify(red={"cmd": ["python", "pkg/green.py"]})
        self.assertEqual(report["verdict"], "no_verdict")
        self.assertEqual(report["reasons"], ["red_control_green"])
        with self.assertRaises(U.VerifyError):
            self.verify(red={})

    def test_network_is_none_in_every_run(self):
        write_tree(self.tree, {"pkg/run_tests.py": "import socket\nsocket.create_connection(('127.0.0.1', 9))\n"})
        report = self.verify()
        self.assertEqual(report["reasons"], ["test_red:1", "test_red:2", "test_red:3"])
        self.assertIn(b"Network is unreachable", self.runner.calls[3]["stderr"])

    def test_unit_inputs_bytes(self):
        size = self.verify()["inputs_bytes"]
        self.assertEqual(self.verify(pol=policy(unit_inputs_bytes=size))["verdict"], "verified")
        report = self.verify(pol=policy(unit_inputs_bytes=size - 1))
        self.assertEqual((report["verdict"], report["reasons"]), ("no_verdict", ["limit_hit:unit_inputs_bytes"]))
        self.assertEqual(self.runner.calls, [])
        report = self.verify(recipe(limits={"unit_inputs_bytes": 100}))
        self.assertEqual(report["reasons"], ["limit_hit:unit_inputs_bytes"])

    def test_copy_stops_once_over_unit_inputs_bytes(self):
        write_tree(self.tree, {"lib/%02d.txt" % i: "y" * 1000 for i in range(20)})
        derived = U.D.derive(self.tree)
        staging = os.path.join(self.base, "stage")
        os.mkdir(staging)
        total = U.copy_inputs(self.tree, ["lib"], derived, staging, 1500)
        self.assertLessEqual(total, 2500)
        copied = sum(len(f) for _, _, f in os.walk(staging))
        self.assertLessEqual(copied, 2)

    def test_test_total_s_caps_the_test_command(self):
        runner = Clockless("pkg/run_tests.py", 5)
        report = self.verify(recipe(limits={"test_total_s": 1}), runner=runner)
        self.assertEqual(report["verdict"], "no_verdict")
        self.assertEqual(report["reasons"], ["limit_hit:test_total_s"])
        self.assertIn(("pkg/run_tests.py", 1), runner.timeouts)
        self.assertIn(("pkg/red.py", 1), runner.timeouts, "the attempt's red control is capped too")
        self.assertIn(("pkg/lint.py", 60), runner.timeouts)

    def test_kos_wall_s_and_worktree_bytes(self):
        runner = Clockless("pkg/run_tests.py", 5)
        report = self.verify(pol=policy(kos_wall_s=1, test_total_s=5), runner=runner)
        self.assertEqual(report["reasons"], ["limit_hit:kos_wall_s"])
        self.assertIn(("pkg/run_tests.py", 1), runner.timeouts)
        report = self.verify(pol=policy(worktree_bytes=300))
        self.assertEqual((report["verdict"], report["reasons"]), ("no_verdict", ["limit_hit:worktree_bytes"]))


class Deps(Base):
    def test_artifact_is_taken_by_its_hash(self):
        blob = os.path.join(self.deps, "tarballs", os.listdir(os.path.join(self.deps, "tarballs"))[0])
        with open(blob, "rb") as fh:
            data = bytearray(fh.read())
        data[-5] ^= 1
        with open(blob, "wb") as fh:
            fh.write(bytes(data))
        report = self.verify()
        self.assertEqual(report["verdict"], "no_verdict")
        self.assertEqual(report["reasons"], ["deps:tarball_mismatch:node_modules/left-pad"])
        self.assertEqual(self.runner.calls, [])

    def test_artifact_must_belong_to_the_trees_lock(self):
        self.lock["packages"][""]["version"] = "1.0.1"
        self.write_lock(self.lock)
        report = self.verify()
        self.assertEqual(report["reasons"], ["deps_lock_mismatch"])
        self.assertEqual(self.runner.calls, [])

    def test_lock_without_packages_needs_no_artifact_and_with_packages_does(self):
        with self.assertRaises(U.VerifyError):
            self.verify(deps=None)
        self.write_lock({"lockfileVersion": 3, "packages": {"": {"name": "pkg"}}})
        write_tree(self.tree, {"pkg/run_tests.py": "print('ok')\n"})
        report = self.verify(deps=None)
        self.assertEqual(report["verdict"], "verified", report)
        self.assertIsNone(report["deps_address"])

    def _evil(self, files: dict) -> None:
        data = tgz(files)
        name = "evil"
        u = url(name, "1.0.0")
        self.put(u, data)
        self.lock["packages"]["node_modules/evil"] = {"version": "1.0.0", "resolved": u, "integrity": sri(data)}
        self.write_lock(self.lock)
        self.deps = self.fetch()

    def test_unsafe_member_names_refuse_the_artifact_and_write_nothing_outside(self):
        for member in ("../../../escaped.txt", "a/../../../../escaped.txt"):
            with self.subTest(member=member):
                self.lock["packages"].pop("node_modules/evil", None)
                self._evil({"package.json": {"name": "evil", "version": "1.0.0"}, member: b"x"})
                report = self.verify()
                self.assertEqual(report["reasons"], ["deps_unpack_unsafe:node_modules/evil"])
                self.assertEqual(report["verdict"], "no_verdict")
                for root, _, files in os.walk(self.base):
                    self.assertNotIn("escaped.txt", files, root)

    def test_links_in_tarballs_are_skipped_and_bins_stay_inside(self):
        self._evil({"package.json": {"name": "evil", "version": "1.0.0", "bin": {"x": "../../../etc/passwd",
                                                                                   "../y": "y.js", "ok": "y.js"}},
                    "link": ("symlink", "/etc/passwd"), "y.js": b"1"})
        staging = os.path.join(self.base, "stage")
        os.makedirs(os.path.join(staging, "pkg"))
        bad, info = U.install_deps(staging, "pkg/package-lock.json", self.deps,
                                   self.lock_bytes(), 10 ** 7)
        self.assertEqual(bad, [])
        self.assertEqual(info["skipped"], 1)
        self.assertFalse(os.path.lexists(os.path.join(staging, "pkg/node_modules/evil/link")))
        self.assertEqual(sorted(info["links"]), ["pkg/node_modules/.bin/left-pad", "pkg/node_modules/.bin/ok"])
        self.assertEqual(os.readlink(os.path.join(staging, "pkg/node_modules/.bin/ok")), "../evil/y.js")
        self.assertEqual(os.stat(os.path.join(staging, "pkg/node_modules/evil/y.js")).st_mode & 0o777, 0o755)

    def test_unpacking_refuses_a_symlink_on_the_way(self):
        staging = os.path.join(self.base, "stage")
        os.makedirs(os.path.join(staging, "pkg"))
        outside = os.path.join(self.base, "outside")
        os.makedirs(outside)
        os.symlink(outside, os.path.join(staging, "pkg", "node_modules"))
        bad, _ = U.install_deps(staging, "pkg/package-lock.json", self.deps,
                                self.lock_bytes(), 10 ** 7)
        self.assertEqual(bad, ["deps_unpack_unsafe:node_modules/left-pad"])
        self.assertEqual(os.listdir(outside), [])

    def test_unpacked_bytes_are_bounded(self):
        self._evil({"package.json": {"name": "evil", "version": "1.0.0"}, "big.bin": b"\0" * 50000})
        report = self.verify(pol=policy(worktree_bytes=20000))
        self.assertEqual(report["reasons"], ["limit_hit:worktree_bytes"])
        self.assertEqual(report["platform"]["os"], "linux", "a refusal of the install names the platform it was for")
        self.assertEqual(self.runner.calls, [])

    def test_marked_install_scripts_run_contained_before_the_runs(self):
        self.lock["packages"]["node_modules/left-pad"]["hasInstallScript"] = True
        self.write_lock(self.lock)
        self.deps = self.fetch(marks=["left-pad@1.3.0"])
        inner = FakeDocker()
        npm = []

        def runner(argv, env, timeout):
            image_at = argv.index(IMAGE)
            if argv[image_at + 1] == "npm":
                npm.append(argv[image_at + 1:])
                work = argv[argv.index("--mount") + 1].split(",")[1][len("src="):]
                with open(os.path.join(work, "pkg/node_modules/left-pad/BUILT"), "w") as fh:
                    fh.write("1")
                return C.RunnerResult(self.npm_exit, b"", b"", False)
            return inner(argv, env, timeout)
        self.npm_exit = 0
        report = self.verify(recipe(install_scripts_required=["left-pad@1.3.0"]), runner=runner)
        self.assertEqual(report["verdict"], "verified", report)
        self.assertEqual(npm, [["npm", "--prefix", "/work/pkg", "rebuild", "--offline", "--foreground-scripts",
                                "left-pad"]])
        self.assertIn(b"built", inner.calls[-1]["stdout"], "the runs start from the install's worktree")
        self.assertEqual(report["install"]["exit"], 0)
        del npm[:]
        self.npm_exit = 1
        report = self.verify(recipe(install_scripts_required=["left-pad@1.3.0"]), runner=runner)
        self.assertEqual((report["verdict"], report["reasons"]), ("verified", []), report)
        self.assertEqual([cmd[6:] for cmd in npm], [["left-pad"], ["left-pad"]], "the install, then the name alone")
        self.assertEqual((report["install"]["exit"], [(e["name"], e["exit"], e["dropped"])
                                                      for e in report["install_each"]]),
                         (1, [("left-pad", 1, [])]))
        self.assertNotIn(b"built", inner.calls[-1]["stdout"], "a failed script's worktree is not the runs'")


# ---------------------------------------------------------------- the install as npm makes it

class InstallAsNpm(Base):
    """Steps 2 and 3 (tohum/26c "Birim tarifi": a package that is not unpacked and a script that does not run or
    ends nonzero refuse nothing): a row the container's platform excludes is not installed; a failed install
    run is followed by each name alone, and a name that fails alone is dropped when all its rows are optional
    and stays as unpacked otherwise. The npm of these tests is the fake runner's: the rule is bound here, npm's
    own behaviour in the image is asama-0/10a #birim's."""

    def add(self, name: str, marks=None, **entry) -> None:
        data = tgz({"package.json": {"name": name, "version": "1.0.0", "license": "MIT", "bin": "cli.js"},
                    "cli.js": b"#!/usr/bin/env node\n"})
        u = url(name, "1.0.0")
        self.put(u, data)
        row = {"version": "1.0.0", "resolved": u, "integrity": sri(data)}
        row.update(entry)
        self.lock["packages"]["node_modules/" + name] = row
        self.write_lock(self.lock)
        self.marks = list(marks) if marks is not None else getattr(self, "marks", [])
        self.deps = self.fetch(marks=self.marks)

    def npm_runner(self, exits: dict):
        """A runner whose ``npm rebuild`` exits by ``exits["*"]`` when it has several names and that key is set, else
        by the largest ``exits[name]`` of its names (0 when absent), after writing ``BUILT`` into every named package
        it finds; ``self.npm`` lists the rebuilds as ``(names, packages present)``. ``self.roots`` lists, per call
        that is not the red control's, what the verifier's directory held at that moment."""
        inner = FakeDocker()
        self.npm, self.inner, self.roots = [], inner, []

        def runner(argv, env, timeout):
            image_at = max(i for i, a in enumerate(argv) if a.endswith(DIGEST))
            cmd = argv[image_at + 1:]
            work = argv[argv.index("--mount") + 1].split(",")[1][len("src="):]
            if cmd != self.red["cmd"]:
                self.roots.append(sorted(os.listdir(os.path.dirname(os.path.dirname(work)))))
            if cmd[:1] != ["npm"]:
                return inner(argv, env, timeout)
            self.assertEqual(cmd[:5], ["npm", "--prefix", "/work/pkg", "rebuild", "--offline"])
            self.assertEqual(cmd[5], "--foreground-scripts")
            names = cmd[6:]
            modules = os.path.join(work, "pkg", "node_modules")
            self.npm.append((names, sorted(n for n in os.listdir(modules) if not n.startswith("."))))
            for name in names:
                if os.path.isdir(os.path.join(modules, name)):
                    with open(os.path.join(modules, name, "BUILT"), "w") as fh:
                        fh.write("1")
            code = exits["*"] if len(names) > 1 and "*" in exits else max(exits.get(name, 0) for name in names)
            return C.RunnerResult(code, b"", b"", False)
        return runner

    def each(self, report: dict) -> list:
        return [(e["name"], e["exit"], e["dropped"]) for e in report["install_each"]]

    def worktree_of_last_run(self) -> tuple[list, list]:
        """``(packages, bin links)`` of ``pkg/node_modules`` as the last test run saw them."""
        out = self.inner.calls[-1]["stdout"].decode()
        line = [x for x in out.splitlines() if x.startswith("modules:")][0]
        return json.loads(line[len("modules:"):])

    def setUp(self) -> None:
        super().setUp()
        self.red = RED
        write_tree(self.tree, {"pkg/run_tests.py": (
            "import json, os\n"
            "m = 'pkg/node_modules'\n"
            "b = sorted(os.listdir(m + '/.bin')) if os.path.isdir(m + '/.bin') else []\n"
            "built = sorted(n for n in os.listdir(m) if os.path.exists(m + '/' + n + '/BUILT'))\n"
            "print('modules:' + json.dumps([sorted(n for n in os.listdir(m) if n != '.bin'), b, built]))\n")})

    def test_an_optional_row_the_platform_excludes_is_not_installed_and_its_script_not_run(self):
        self.add("mac-only", marks=["node_modules/mac-only"], optional=True, os=["darwin"], hasInstallScript=True)
        inner_data = tgz({"package.json": {"name": "inner", "version": "1.0.0", "license": "MIT"}})
        self.put(url("inner", "1.0.0"), inner_data)
        self.lock["packages"]["node_modules/mac-only/node_modules/inner"] = {
            "version": "1.0.0", "resolved": url("inner", "1.0.0"), "integrity": sri(inner_data), "optional": True}
        self.write_lock(self.lock)
        self.deps = self.fetch(marks=self.marks)
        report = self.verify(recipe(install_scripts_required=self.marks), runner=self.npm_runner({}))
        self.assertEqual(report["verdict"], "verified", report)
        self.assertEqual(self.npm, [], "no script of a row that is not installed runs")
        self.assertIsNone(report["install"])
        self.assertEqual(report["not_installed"], ["node_modules/mac-only", "node_modules/mac-only/node_modules/inner"])
        self.assertEqual(report["platform"]["os"], "linux")
        self.assertEqual(report["bin_links"], ["pkg/node_modules/.bin/left-pad"])
        self.assertEqual(self.worktree_of_last_run(), [["left-pad"], ["left-pad"], []])

    def test_a_row_the_platform_admits_is_installed_as_before(self):
        self.add("linux-only", optional=True, os=["linux"])
        self.add("not-windows", os=["!win32"])
        report = self.verify(runner=self.npm_runner({}))
        self.assertEqual(report["verdict"], "verified", report)
        self.assertEqual(report["not_installed"], [])
        self.assertEqual(self.worktree_of_last_run()[0], ["left-pad", "linux-only", "not-windows"])

    def test_libc_is_the_image_s(self):
        self.add("musl-binding", optional=True, os=["linux"], libc=["musl"])
        self.add("glibc-binding", optional=True, os=["linux"], libc=["glibc"])
        report = self.verify(runner=self.npm_runner({}))
        self.assertEqual((report["verdict"], report["not_installed"], report["platform"]["libc"]),
                         ("verified", ["node_modules/musl-binding"], "glibc"), report)
        alpine = recipe(env_image="node:20.11.1-alpine3.19" + DIGEST)
        report = self.verify(alpine, runner=self.npm_runner({}))
        self.assertEqual((report["verdict"], report["not_installed"], report["platform"]["libc"]),
                         ("verified", ["node_modules/glibc-binding"], "musl"), report)

    def test_a_row_that_is_not_optional_and_excluded_is_not_installed_and_is_named(self):
        for flags in ({}, {"devOptional": True}, {"dev": True}, {"optional": False}):
            with self.subTest(flags=flags):
                for key in [k for k in self.lock["packages"] if k.startswith("node_modules/mac-only")]:
                    del self.lock["packages"][key]
                self.add("mac-only", marks=["node_modules/mac-only"], os=["darwin"], hasInstallScript=True, **flags)
                self.nested("mac-only", "below", hasInstallScript=True)
                report = self.verify(recipe(install_scripts_required=self.marks), runner=self.npm_runner({}))
                self.assertEqual((report["verdict"], report["reasons"]), ("verified", []), report)
                self.assertEqual(report["unsupported"], ["node_modules/mac-only"])
                self.assertEqual(report["not_installed"],
                                 ["node_modules/mac-only", "node_modules/mac-only/node_modules/below"])
                self.assertEqual(report["platform"], {"os": "linux", "cpu": U.NODE_CPU[os.uname().machine],
                                                      "libc": "glibc"})
                self.assertEqual(self.npm, [], "no script of a row that is not installed runs")
                self.assertEqual(self.worktree_of_last_run(), [["left-pad"], ["left-pad"], []])

    def both(self) -> None:
        """``left-pad`` (not optional) and ``opt-native`` (optional), each with an install script, marked."""
        self.lock["packages"]["node_modules/left-pad"]["hasInstallScript"] = True
        self.add("opt-native", marks=["left-pad@1.3.0", "node_modules/opt-native"], optional=True,
                 hasInstallScript=True)

    def test_an_install_that_passes_is_one_run_and_its_worktree_is_the_runs(self):
        self.both()
        report = self.verify(recipe(install_scripts_required=self.marks), runner=self.npm_runner({}))
        self.assertEqual(report["verdict"], "verified", report)
        self.assertEqual(self.npm, [(["left-pad", "opt-native"], ["left-pad", "opt-native"])])
        self.assertEqual((report["install"]["exit"], report["install_each"]), (0, []))
        self.assertEqual(self.worktree_of_last_run(),
                         [["left-pad", "opt-native"], ["left-pad", "opt-native"], ["left-pad", "opt-native"]])

    def test_an_optional_name_that_fails_alone_is_dropped_and_the_install_goes_on(self):
        self.both()
        report = self.verify(recipe(install_scripts_required=self.marks), runner=self.npm_runner({"opt-native": 1}))
        self.assertEqual(report["verdict"], "verified", report)
        self.assertEqual(self.npm, [(["left-pad", "opt-native"], ["left-pad", "opt-native"]),
                                    (["left-pad"], ["left-pad", "opt-native"]),
                                    (["opt-native"], ["left-pad", "opt-native"])],
                         "the failed install is followed by each name alone, in name order")
        self.assertEqual(report["install"]["exit"], 1)
        self.assertEqual(self.each(report), [("left-pad", 0, []), ("opt-native", 1, ["node_modules/opt-native"])])
        self.assertEqual(report["bin_links"], ["pkg/node_modules/.bin/left-pad"])
        self.assertEqual(self.worktree_of_last_run(), [["left-pad"], ["left-pad"], ["left-pad"]],
                         "the dropped package, its bin link and what its failed script wrote are gone")

    def test_only_an_optional_name_and_it_fails(self):
        self.add("opt-native", marks=["node_modules/opt-native"], optional=True, hasInstallScript=True)
        report = self.verify(recipe(install_scripts_required=self.marks), runner=self.npm_runner({"opt-native": 1}))
        self.assertEqual(report["verdict"], "verified", report)
        self.assertEqual([names for names, _ in self.npm], [["opt-native"], ["opt-native"]])
        self.assertEqual(self.each(report), [("opt-native", 1, ["node_modules/opt-native"])])
        self.assertEqual(self.worktree_of_last_run(), [["left-pad"], ["left-pad"], []])

    def test_a_name_that_is_not_optional_and_fails_alone_stays_as_unpacked(self):
        self.both()
        report = self.verify(recipe(install_scripts_required=self.marks), runner=self.npm_runner({"left-pad": 1}))
        self.assertEqual((report["verdict"], report["reasons"]), ("verified", []), report)
        self.assertEqual([names for names, _ in self.npm], [["left-pad", "opt-native"], ["left-pad"], ["opt-native"]])
        self.assertEqual(self.each(report), [("left-pad", 1, []), ("opt-native", 0, [])])
        self.assertEqual(report["bin_links"], ["pkg/node_modules/.bin/left-pad", "pkg/node_modules/.bin/opt-native"])
        self.assertEqual(self.worktree_of_last_run(),
                         [["left-pad", "opt-native"], ["left-pad", "opt-native"], ["opt-native"]],
                         "the package is there; what its failed script and the failed install wrote is not")

    def test_an_install_that_fails_where_each_name_passes_alone_builds_each_on_the_one_before(self):
        self.both()
        report = self.verify(recipe(install_scripts_required=self.marks), runner=self.npm_runner({"*": 1}))
        self.assertEqual(report["verdict"], "verified", report)
        self.assertEqual(self.each(report), [("left-pad", 0, []), ("opt-native", 0, [])])
        self.assertEqual(self.worktree_of_last_run()[2], ["left-pad", "opt-native"])

    def test_a_name_with_a_row_that_is_not_optional_is_not_dropped(self):
        # npm rebuild names packages, not lock rows: two rows of one name, one of them not optional, both stay
        self.add("twin", marks=["twin@1.0.0"], hasInstallScript=True)
        data = tgz({"package.json": {"name": "twin", "version": "1.0.0", "license": "MIT"}})
        self.lock["packages"]["node_modules/left-pad/node_modules/twin"] = {
            "version": "1.0.0", "resolved": url("twin", "1.0.0"), "integrity": sri(data), "optional": True,
            "hasInstallScript": True}
        self.put(url("twin", "1.0.0"), tgz({"package.json": {"name": "twin", "version": "1.0.0", "license": "MIT",
                                                              "bin": "cli.js"}, "cli.js": b"#!/usr/bin/env node\n"}))
        self.lock["packages"]["node_modules/left-pad/node_modules/twin"]["integrity"] = \
            self.lock["packages"]["node_modules/twin"]["integrity"]
        self.write_lock(self.lock)
        self.deps = self.fetch(marks=self.marks)
        report = self.verify(recipe(install_scripts_required=self.marks), runner=self.npm_runner({"twin": 1}))
        self.assertEqual((report["verdict"], report["reasons"]), ("verified", []), report)
        self.assertEqual([names for names, _ in self.npm], [["twin"], ["twin"]])
        self.assertEqual(self.each(report), [("twin", 1, [])])
        self.assertEqual(self.worktree_of_last_run()[0], ["left-pad", "twin"])
        self.assertIn("pkg/node_modules/.bin/twin", report["bin_links"])

    def nested(self, parent: str, name: str, **entry) -> None:
        """A lock row of ``name`` below ``node_modules/<parent>``, fetched; marked when it has a script."""
        data = tgz({"package.json": {"name": name, "version": "2.0.0", "license": "MIT"}})
        self.put(url(name, "2.0.0"), data)
        key = "node_modules/%s/node_modules/%s" % (parent, name)
        self.lock["packages"][key] = dict({"version": "2.0.0", "resolved": url(name, "2.0.0"),
                                           "integrity": sri(data)}, **entry)
        self.write_lock(self.lock)
        if entry.get("hasInstallScript"):
            self.marks = self.marks + [key]
        self.deps = self.fetch(marks=self.marks)

    def test_a_dropped_row_takes_the_rows_below_it_and_their_names_are_not_run(self):
        # ``outer`` fails and goes with all below it: its own name again, an optional name run before it
        # (``inner``), an optional name not yet run (``zeta``) and a name that is not optional (``req``)
        self.add("outer", marks=["node_modules/outer"], optional=True, hasInstallScript=True)
        self.nested("outer", "outer", optional=True, hasInstallScript=True)
        self.nested("outer", "inner", optional=True, hasInstallScript=True)
        self.nested("outer", "zeta", optional=True, hasInstallScript=True)
        self.nested("outer", "req", hasInstallScript=True)
        self.nested("outer", "plain", optional=True)
        report = self.verify(recipe(install_scripts_required=self.marks), runner=self.npm_runner({"outer": 1}))
        self.assertEqual(report["verdict"], "verified", report)
        self.assertEqual([names for names, _ in self.npm], [["inner", "outer", "req", "zeta"], ["inner"], ["outer"]],
                         "a name whose rows are all gone is not run alone")
        self.assertEqual(self.each(report),
                         [("inner", 0, []),
                          ("outer", 1, ["node_modules/outer", "node_modules/outer/node_modules/inner",
                                        "node_modules/outer/node_modules/outer",
                                        "node_modules/outer/node_modules/plain",
                                        "node_modules/outer/node_modules/req",
                                        "node_modules/outer/node_modules/zeta"])])
        self.assertEqual(self.worktree_of_last_run(), [["left-pad"], ["left-pad"], []])

    def test_a_name_with_a_row_left_after_a_drop_is_still_run(self):
        self.add("outer", marks=["node_modules/outer"], optional=True, hasInstallScript=True)
        self.nested("outer", "req", hasInstallScript=True)
        self.add("req", marks=self.marks + ["node_modules/req"], hasInstallScript=True)
        report = self.verify(recipe(install_scripts_required=self.marks), runner=self.npm_runner({"outer": 1}))
        self.assertEqual(report["verdict"], "verified", report)
        self.assertEqual([names for names, _ in self.npm], [["outer", "req"], ["outer"], ["req"]])
        self.assertEqual(self.worktree_of_last_run(), [["left-pad", "req"], ["left-pad", "req"], ["req"]])

    def test_the_copies_of_finished_runs_do_not_pile_up(self):
        self.both()
        self.add("zz", marks=self.marks + ["node_modules/zz"], optional=True, hasInstallScript=True)
        self.verify(recipe(install_scripts_required=self.marks), runner=self.npm_runner({"*": 1, "opt-native": 1}))
        self.assertEqual([names for names, _ in self.npm],
                         [["left-pad", "opt-native", "zz"], ["left-pad"], ["opt-native"], ["zz"]])
        counts = [len(held) for held in self.roots]
        # held at each run: the first copy (``tree``), the worktree it starts from when that is an earlier
        # run's, its red control's copy and its own; an earlier control's copy, a failed run's and a superseded
        # one's are gone
        self.assertEqual(counts[:4], [3, 3, 4, 4])
        self.assertEqual(set(counts[4:]), {4}, self.roots)
        self.assertEqual(len(counts), 4 + 6)

    def test_drop_rows_removes_what_is_there_and_names_every_row_removed(self):
        staging = os.path.join(self.base, "drop")
        write_tree(staging, {"pkg/node_modules/a/index.js": "", "pkg/node_modules/a/node_modules/b/index.js": "",
                             "pkg/node_modules/ab/index.js": "", "pkg/node_modules/c/cli.js": ""})
        os.makedirs(os.path.join(staging, "pkg", "node_modules", ".bin"))
        for name, target in (("c", "../c/cli.js"), ("b", "../a/node_modules/b/index.js")):
            os.symlink(target, os.path.join(staging, "pkg", "node_modules", ".bin", name))
        installed = ["node_modules/a", "node_modules/a/node_modules/b", "node_modules/ab", "node_modules/c",
                     "node_modules/empty"]             # ``empty``: a row whose tarball unpacked no file
        removed, links = U.drop_rows(staging, "pkg", ["node_modules/a/node_modules/b", "node_modules/a",
                                                      "node_modules/empty"], installed,
                                     ["pkg/node_modules/.bin/b", "pkg/node_modules/.bin/c"])
        self.assertEqual(removed, ["node_modules/a", "node_modules/a/node_modules/b", "node_modules/empty"])
        self.assertEqual(links, ["pkg/node_modules/.bin/c"])
        self.assertEqual(sorted(os.listdir(os.path.join(staging, "pkg", "node_modules"))), [".bin", "ab", "c"])
        self.assertEqual(os.listdir(os.path.join(staging, "pkg", "node_modules", ".bin")), ["c"])

    def test_an_install_run_that_is_no_valid_run_gives_no_verdict(self):
        self.both()
        write_tree(self.tree, {"pkg/green.py": "raise SystemExit(0)\n"})
        self.red = {"cmd": ["python", "pkg/green.py"]}
        report = self.verify(recipe(install_scripts_required=self.marks), runner=self.npm_runner({"opt-native": 1}),
                             red=self.red)
        self.assertEqual((report["verdict"], report["reasons"]), ("no_verdict", ["red_control_green"]))
        self.assertEqual((report["install"]["valid"], report["install_each"]), (False, []))
        self.assertEqual(report["runs"], {"lint": [], "test": []})

    def test_a_name_s_run_that_is_no_valid_run_gives_no_verdict(self):
        self.both()
        npm = self.npm_runner({"opt-native": 1})
        controls = []

        def runner(argv, env, timeout):
            if argv[-len(RED["cmd"]):] == RED["cmd"]:
                controls.append(1)
                if len(controls) == 3:                      # the install's, left-pad's, opt-native's
                    return C.RunnerResult(0, b"", b"", False)
            return npm(argv, env, timeout)
        report = self.verify(recipe(install_scripts_required=self.marks), runner=runner)
        self.assertEqual((report["verdict"], report["reasons"]), ("no_verdict", ["red_control_green"]))
        self.assertEqual([(e["name"], e["valid"], e["dropped"]) for e in report["install_each"]],
                         [("left-pad", True, []), ("opt-native", False, [])])
        self.assertEqual(report["runs"], {"lint": [], "test": []})

    def test_container_platform(self):
        cases = {
            ("node:20.11.1-bookworm-slim" + DIGEST, "x86_64"): ("x64", "glibc"),
            ("node:20.11.1" + DIGEST, "aarch64"): ("arm64", "glibc"),
            ("docker.io/library/node:20.11.1-alpine3.19" + DIGEST, "arm64"): ("arm64", "musl"),
            ("node:20.11.1-alpine" + DIGEST, "amd64"): ("x64", "musl"),
            ("node:alpine" + DIGEST, "x86_64"): ("x64", "musl"),
            ("node:lts-alpine3.20" + DIGEST, "x86_64"): ("x64", "musl"),
            ("node" + DIGEST, "x86_64"): ("x64", "glibc"),
            ("node:20.11.1-bullseye" + DIGEST, "armv7l"): ("arm", "glibc"),
            ("node:20.11.1-slim" + DIGEST, "ppc64le"): ("ppc64", "glibc"),
            ("node:20.11.1-bookworm" + DIGEST, "s390x"): ("s390x", "glibc"),
        }
        for (image, machine), (cpu, libc) in cases.items():
            with self.subTest(image=image, machine=machine):
                self.assertEqual(U.container_platform(image, machine), {"os": "linux", "cpu": cpu, "libc": libc})
        self.assertEqual(U.container_platform(IMAGE)["cpu"], U.container_platform(IMAGE, os.uname().machine)["cpu"])
        for machine in ("mips", "", "X86_64"):
            with self.subTest(machine=machine), self.assertRaises(U.VerifyError):
                U.container_platform(IMAGE, machine)


# ---------------------------------------------------------------- command line

class Cli(Base):
    def cli(self, *args) -> tuple[int, dict, str]:
        proc = subprocess.run([sys.executable, "-m", "profile.unit_verify"] + list(args), cwd=REFEREE,
                              capture_output=True, text=True, timeout=120)
        lines = proc.stdout.strip().splitlines()
        self.assertEqual(len(lines), 1, proc.stdout + proc.stderr)
        self.assertNotIn("Traceback", proc.stderr)
        return proc.returncode, json.loads(lines[0]), proc.stderr

    def file(self, name: str, obj) -> str:
        path = os.path.join(self.base, name)
        with open(path, "w", encoding="utf-8") as fh:
            if isinstance(obj, str):
                fh.write(obj)
            else:
                json.dump(obj, fh)
        return path

    def test_check_is_the_vector_form(self):
        code, out, _ = self.cli("check", self.file("r.json", recipe()), self.file("p.json", policy()))
        self.assertEqual((code, out), (0, {"ok": True, "reasons": []}))
        code, out, _ = self.cli("check", self.file("r.json", recipe(env_image="node:20.11.1")),
                                self.file("p.json", policy()))
        self.assertEqual((code, out), (1, {"ok": False, "reasons": ["image_not_pinned"]}))

    def test_unusable_input_is_exit_2(self):
        pol = self.file("pol.json", policy())
        for args in (["check", self.file("bad0.json", "{not json"), pol],
                     ["check", self.file("deep1.json", "[" * 100000 + "]" * 100000), pol],
                     ["check", os.path.join(self.base, "missing.json"), pol],
                     ["check", self.file("r2.json", recipe())],
                     ["check", self.file("r3.json", recipe()), "--policy", pol],
                     ["check", self.file("r4.json", recipe()), pol, "--tree", self.tree],
                     ["verify", self.file("v7.json", {"recipe": recipe()})],
                     ["verify", self.file("v8.json", {"recipe": recipe(), "tree": self.tree, "policy": policy(),
                                                      "red_control": RED}), "extra"],
                     ["check"], ["frobnicate", "x"]):
            with self.subTest(args=args):
                code, out, err = self.cli(*args)
                refusal.assert_refused(self, U, list(args), code, out, err)
                self.assertIn("error", out)
                self.assertIs(out["ok"], False)

    def test_verify_refusal_is_exit_1_before_any_run(self):
        req = {"recipe": recipe(services=["redis"]), "tree": self.tree, "policy": policy(), "red_control": RED}
        code, out, _ = self.cli("verify", self.file("v.json", req))
        self.assertEqual((code, out["verdict"], out["reasons"]), (1, "refused", ["services_not_empty"]))

    def test_unexpected_exception_is_exit_2_not_a_traceback(self):
        from test_cli import MARK, run_boundary
        with mock.patch.object(U, "vector_check", side_effect=ZeroDivisionError(MARK)):
            got = run_boundary(U.main, ["check", self.file("r.json", recipe()), self.file("p.json", policy())],
                               U.FAULT_LINE)
        self.assertEqual(got, (2, '{"error": "internal error", "ok": false}\n', "internal error: ZeroDivisionError\n"))


# ---------------------------------------------------------------- group recipe (tohum/29g), vector form

class VectorRecipe(unittest.TestCase):
    """``check RECIPE POLICY`` as the seed's runner calls it: a subprocess from ``referee/``, files only."""

    def setUp(self) -> None:
        self.dir = writable_base("t-recipe-")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.n = 0

    def run_check(self, r, pol=None) -> tuple[int, dict]:
        self.n += 1
        paths = []
        for name, obj in (("recipe", r), ("policy", policy() if pol is None else pol)):
            path = os.path.join(self.dir, "%s%d.json" % (name, self.n))
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(obj if isinstance(obj, str) else json.dumps(obj))
            paths.append(path)
        proc = subprocess.run([sys.executable, "-m", "profile.unit_verify", "check"] + paths, cwd=REFEREE,
                              stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=120)
        self.assertNotIn("Traceback", proc.stderr)
        last = proc.stdout.strip().splitlines()[-1]
        self.assertNotIn("\n", last)
        return proc.returncode, json.loads(last)

    def expect(self, r, reasons: list, pol=None) -> None:
        code, out = self.run_check(r, pol)
        self.assertEqual((code, out["ok"], out["reasons"]), (0 if not reasons else 1, not reasons, reasons))
        self.assertIs(out["ok"], not reasons)

    def case(self, name: str, r, reasons: list, changed, pol=None, changed_pol=None) -> None:
        """The named case gives ``reasons``; the one-field-changed variant must not give the same result."""
        with self.subTest(case=name):
            self.expect(r, reasons, pol)
            code, out = self.run_check(changed, changed_pol)
            self.assertNotEqual((code, out.get("ok"), out.get("reasons")), (0 if not reasons else 1, not reasons, reasons))

    def test_good(self):
        self.case("good", recipe(), [], recipe(env_image="node:20.11.1"))

    def test_image_tag_only(self):
        self.case("image_tag_only", recipe(env_image="node:20.11.1"), ["image_not_pinned"], recipe())
        for image in ("node:20.11.1-bookworm-slim", "node@sha256:", None, 3):
            with self.subTest(image=image):
                self.expect(recipe(env_image=image), ["image_not_pinned"])
        r = recipe()
        del r["env_image"]
        self.expect(r, ["image_not_pinned"])

    def test_image_digest_malformed(self):
        self.case("image_digest_malformed", recipe(env_image="node:20.11.1@sha256:" + "a" * 63),
                  ["image_not_pinned"], recipe(env_image="node:20.11.1@sha256:" + "a" * 64))
        for digest in ("a" * 65, "A" * 64, "g" * 64, "a" * 64 + " "):
            with self.subTest(digest=digest):
                self.expect(recipe(env_image="node:20.11.1@sha256:" + digest), ["image_not_pinned"])
        self.expect(recipe(env_image="node:20.11.1@sha512:" + "a" * 64), ["image_not_pinned"])

    def test_inputs_missing_unit_dir(self):
        self.case("inputs_missing_unit_dir", recipe(inputs=["lib"]), ["inputs_missing_unit"],
                  recipe(inputs=["lib", "pkg"]))
        for inputs in (["pk", "lib"], ["PKG", "lib"], ["pkg/sub"], [], ["pkgx"]):
            with self.subTest(inputs=inputs):
                self.expect(recipe(inputs=inputs), ["inputs_missing_unit"])
        for inputs in (["pkg/"], ["pkg//"], ["lib", "pkg"]):
            with self.subTest(inputs=inputs):
                self.expect(recipe(inputs=inputs), [])
        self.expect(recipe(path="pkg/sub", inputs=["pkg"]), [])
        self.expect(recipe(path="pkg/sub", inputs=["pkg/su"]), ["inputs_missing_unit"])

    def test_inputs_agent_config(self):
        self.case("inputs_agent_config", recipe(inputs=["pkg", ".Claude"]), ["input_excluded:.Claude"],
                  recipe(inputs=["pkg", ".Claudex"]))
        for e in (".claude", ".CLAUDE/settings.json", "pkg/.vscode", ".DevContainer/x", "CLAUDE.md",
                  "docs/claude.MD", "Agents.md", "pkg/.MCP.json", ".envrc", ".ENVRC/", "a/.vscode/b"):
            with self.subTest(input=e):
                self.expect(recipe(inputs=["pkg", e]), ["input_excluded:%s" % e])
        for e in ("claude", "CLAUDE.md.bak", "CLAUDE.md/notes", "pkg/.envrc.d", "x.mcp.json"):
            with self.subTest(input=e):
                self.expect(recipe(inputs=["pkg", e]), [])

    def test_inputs_not_plain(self):
        self.case("inputs_not_plain", recipe(inputs=["pkg", "/etc"]), ["input_not_plain:/etc"],
                  recipe(inputs=["pkg", "etc"]))
        for e in ("/pkg", "lib\\x", "./lib", "lib/./x", "lib/..", "../lib", "."):
            with self.subTest(input=e):
                self.expect(recipe(inputs=["pkg", e]), ["input_not_plain:%s" % e])
        for e in ("..lib", "lib.", "lib/...", "lib/"):
            with self.subTest(input=e):
                self.expect(recipe(inputs=["pkg", e]), [])
        self.expect(recipe(inputs=["/pkg"]), ["input_not_plain:/pkg", "inputs_missing_unit"])

    def test_limit_key_unknown(self):
        self.case("limit_key_unknown", recipe(limits={"cpu_s": 3}), [unknown_limit("cpu_s")],
                  recipe(limits={"kos_wall_s": 3}))
        self.expect(recipe(limits={"kos_wall_s": -1, "test_total_s": "x", "output_bytes": None}), [])
        pol = policy()
        del pol["operating"]["test_total_s"]
        self.expect(recipe(limits={"test_total_s": 5}), [unknown_limit("test_total_s")], pol)
        self.expect(recipe(limits={"Kos_wall_s": 5}), [unknown_limit("Kos_wall_s")])
        self.expect(recipe(limits={"z": 1, "a": 1}), [unknown_limit("a"), unknown_limit("z")])

    def test_test_cmd_empty(self):
        self.case("test_cmd_empty", recipe(test_cmd=[]), ["cmd_empty:test_cmd"], recipe(test_cmd=["npm", "test"]))
        for bad in ([""], ["npm", ""], ["npm", 3], None, "npm test", {}):
            with self.subTest(bad=bad):
                self.expect(recipe(test_cmd=bad), ["cmd_empty:test_cmd"])
        r = recipe()
        del r["test_cmd"]
        self.expect(r, ["cmd_empty:test_cmd"])

    def test_cmd_entries(self):
        for field in ("lint_cmd", "affected_test_cmd"):
            self.case("cmd_entries:" + field, recipe(**{field: []}), ["cmd_empty:%s" % field],
                      recipe(**{field: ["npm", "run", "x"]}))
            for bad in ([""], [None], "x"):
                with self.subTest(field=field, bad=bad):
                    self.expect(recipe(**{field: bad}), ["cmd_empty:%s" % field])
            r = recipe()
            del r[field]
            self.expect(r, ["cmd_empty:%s" % field])
        self.expect(recipe(lint_cmd=[], test_cmd=[""], affected_test_cmd=[]),
                    ["cmd_empty:affected_test_cmd", "cmd_empty:lint_cmd", "cmd_empty:test_cmd"])

    def test_services_not_empty(self):
        self.case("services", recipe(services=["redis"]), ["services_not_empty"], recipe(services=[]))
        for bad in ({}, None, "", [[]]):
            with self.subTest(bad=bad):
                self.expect(recipe(services=bad), ["services_not_empty"])
        r = recipe()
        del r["services"]
        self.expect(r, ["services_not_empty"])

    def test_every_reason_listed_and_sorted(self):
        r = recipe(env_image="node:20", inputs=["/z", "lib", ".claude", "./.vscode"], lint_cmd=[],
                   affected_test_cmd=None, services=["db"], limits={"zz": 1, "aa": 1})
        self.expect(r, ["cmd_empty:affected_test_cmd", "cmd_empty:lint_cmd", "image_not_pinned",
                        "input_excluded:./.vscode", "input_excluded:.claude", "input_not_plain:./.vscode",
                        "input_not_plain:/z", "inputs_missing_unit", unknown_limit("aa"),
                        unknown_limit("zz"), "services_not_empty"])
        self.expect(recipe(inputs=["pkg", "lib", "lib"]), [])
        self.expect(recipe(inputs=["pkg", "/x", "/x"]), ["input_not_plain:/x"])

    def test_other_fields_are_not_looked_at(self):
        self.expect(recipe(toolchain="python@3", lockfiles="x", unit_id=None, install_cmd=["npm", "ci"]), [])

    def test_unusable_input_is_exit_2(self):
        good = recipe()
        cases = [("recipe_not_json", "{x", policy()), ("recipe_list", [good], policy()),
                 ("policy_not_json", good, "{"), ("policy_no_operating", good, {}),
                 ("operating_list", good, {"operating": []}), ("policy_list", good, [])]
        for field, bad in (("path", None), ("path", 3), ("inputs", None), ("inputs", "pkg"), ("inputs", ["pkg", 1]),
                           ("limits", None), ("limits", [])):
            r = recipe()
            if bad is None:
                del r[field]
            else:
                r[field] = bad
            cases.append(("%s=%r" % (field, bad), r, policy()))
        for name, r, pol in cases:
            with self.subTest(case=name):
                code, out = self.run_check(r, pol)
                self.assertEqual(code, 2)
                self.assertIs(out["ok"], False)
                self.assertNotIn("reasons", out)
        proc = subprocess.run([sys.executable, "-m", "profile.unit_verify", "check",
                               os.path.join(self.dir, "missing.json"), os.path.join(self.dir, "missing2.json")],
                              cwd=REFEREE, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=120)
        self.assertEqual(proc.returncode, 2)
        self.assertNotIn("Traceback", proc.stderr)


if __name__ == "__main__":
    unittest.main()
