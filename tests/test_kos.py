"""``runner.kos``: ``koş``'s result files, made from contained runs of the base tree and of each candidate's tree,
read by the gate (MF8) as they are written; with the fake runner (``fake_docker.py``, Python commands only).

- the base: three lint runs become ``base.jsonl``; a failing, unconvertible or uncontained base gives no file and
  no candidate runs;
- a candidate: a fresh copy of the base worktree with its diff applied (refusals of a diff that does not apply
  in place, a path outside the worktree or behind a symlink, the runs' own directory), three lint runs and one
  test run, ``checks.json`` from the TAP, ``hashes.json`` of the bytes written; ``gate.check decide`` (MF8's own
  command) then merges the good candidate and rejects a test-breaking, a ratchet-raising, a non-deterministic and
  a red-control-passing one for their own reasons;
- the sentinel (D7, ``watch``): only with a watched merge; the recipe's ``affected_test_cmd`` at the base worktree,
  each run contained with the red control; green after one run, red and flaky after four; ``sentinel.json`` holds
  every run used and ``gate.sentinel decide`` (MF12's own command) gives the same verdict on them; no verdict and
  no file for a base that did not stage, a run that tells nothing (a green red control, a time limit; the runs stop
  there) or runs of the wrong shape; a base lint that fails does not stop it; what the base's lint says of the head's
  build, read by ``loop.watch.base_build`` (a parse error ESLint reports is no build);
- the TAP reader on ``node --test``'s real output (the toy's captured run) and on its edge cases;
- the command line: exit 0 / 1 / 2, never a traceback.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import unittest

REFEREE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BRAIN = os.path.dirname(REFEREE)
sys.path.insert(0, REFEREE)

from runner import contained as C  # noqa: E402
from runner import kos as K  # noqa: E402
from runner import lint_record as R  # noqa: E402
from loop import watch as WT  # noqa: E402
from fake_docker import FakeDocker  # noqa: E402
from profile_tree import writable_base, write_tree  # noqa: E402

IMAGE = "node:20.11.1-bookworm-slim@sha256:" + "ab" * 32

# ESLint's --format json for two files: no-var (fixable) on every line starting "var ", no-eval (no fix) on every
# line holding "eval(". A file holding NOISE adds one violation of a random rule id per run (a non-deterministic tool
# whose count does not change). A file with a line holding PARSE_ERROR is one ESLint cannot parse: its one message is
# fatal, without a rule id (ESLint's parse error), and the run exits 1.
LINT = r'''import json, os, sys
out = []
for name in ("pkg/a.js", "pkg/b.js"):
    src = open(name).read()
    msgs, off = [], 0
    for i, line in enumerate(src.split("\n"), 1):
        if line.startswith("var "):
            msgs.append({"ruleId": "no-var", "severity": 2, "line": i, "column": 1,
                         "fix": {"range": [off, off + 3], "text": "let"}})
        if "eval(" in line:
            msgs.append({"ruleId": "no-eval", "severity": 2, "line": i, "column": 1})
        off += len(line) + 1
    if "NOISE" in src:
        msgs.append({"ruleId": "noise-" + os.urandom(8).hex(), "severity": 2, "line": 1, "column": 1})
    if "PARSE_ERROR" in src:
        line = src[:src.index("PARSE_ERROR")].count("\n") + 1
        msgs = [{"ruleId": None, "fatal": True, "severity": 2, "message": "Parsing error: Unexpected token",
                 "line": line, "column": 1}]
    out.append({"filePath": "/work/" + name, "messages": msgs, "suppressedMessages": []})
if "LINTCRASH" in open("pkg/a.js").read():
    sys.exit(2)
if "GARBAGE" in open("pkg/a.js").read():
    print("not json")
    sys.exit(1)
sys.stdout.write(json.dumps(out))
sys.exit(1 if any(r["messages"] for r in out) else 0)
'''
# node --test's TAP: top-level lines at column 0, a subtest indented, a skipped test, an escaped '#'.
TESTS = r'''import sys
src = open("pkg/a.js").read()
if "CRASH" in src:
    sys.exit(7)
ok = "BROKEN" not in src
print("TAP version 13")
print("# Subtest: a loads")
print("    ok 1 - nested subtest")
print("ok 1 - a loads")
print(("ok" if ok else "not ok") + " 2 - a is not broken \\# really")
print("ok 3 - not run yet # SKIP")
print("1..3")
sys.exit(0 if ok else 1)
'''
A_JS = "var a = 1;\nconst b = 2;\n"


def operating() -> dict:
    values = {"unit_inputs_bytes": 10 ** 6, "deps_bytes": 10 ** 6, "worktree_bytes": 10 ** 7,
              "container_mem_bytes": 512 * 1024 * 1024, "kos_wall_s": 60, "test_total_s": 60,
              "output_bytes": 10 ** 6}
    return {k: {"value": v, "band": [1, 10 ** 12]} for k, v in values.items()}


def recipe(**over) -> dict:
    r = {"unit_id": "pkg", "path": "pkg", "inputs": ["pkg"], "toolchain": "node@20.11.1", "env_image": IMAGE,
         "lockfiles": ["pkg/package-lock.json"], "install_scripts_required": [],
         "lint_cmd": ["python", "pkg/lint.py"], "test_cmd": ["python", "pkg/run_tests.py"],
         "affected_test_cmd": ["python", "pkg/run_tests.py"], "services": [], "limits": {}}
    r.update(over)
    return r


RED = {"cmd": ["python", "pkg/red.py"]}
GREEN_RED = {"cmd": ["python", "pkg/green.py"]}


def diff(path: str, old: list[str], new: list[str], start: int = 1) -> bytes:
    body = "".join("-%s\n" % line for line in old) + "".join("+%s\n" % line for line in new)
    return ("diff --git a/{p} b/{p}\nindex 1111111..2222222 100644\n--- a/{p}\n+++ b/{p}\n@@ -{s},{o} +{s},{n} @@\n"
            .format(p=path, s=start, o=len(old), n=len(new)) + body).encode()


GOOD = diff("pkg/a.js", ["var a = 1;"], ["let a = 1;"])
BREAKS_TEST = diff("pkg/a.js", ["var a = 1;"], ["let a = 1; // BROKEN"])
RAISES = diff("pkg/a.js", ["var a = 1;"], ["let a = 1;", "eval(a);", "eval(a);"])
NOISY = diff("pkg/a.js", ["var a = 1;"], ["let a = 1; // NOISE"])
FINDING = {"rule_id": "no-var", "path": "pkg/a.js", "line": 1, "fix_range": [1, 1], "tool_output_sha256": "0" * 64}


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read(path: str) -> bytes:
    with open(path, "rb") as fh:
        return fh.read()


class Base(unittest.TestCase):
    def setUp(self) -> None:
        self.base = writable_base("t-kos-")
        self.addCleanup(shutil.rmtree, self.base, ignore_errors=True)
        self.tree = os.path.join(self.base, "tree")
        write_tree(self.tree, {
            ".nvmrc": "v20.11.1\n",
            "pkg/package.json": {"name": "pkg", "version": "1.0.0"},
            "pkg/package-lock.json": {"lockfileVersion": 3, "packages": {"": {"name": "pkg", "version": "1.0.0"}}},
            "pkg/lint.py": LINT, "pkg/run_tests.py": TESTS, "pkg/a.js": A_JS, "pkg/b.js": "const c = 3;\n",
            "pkg/red.py": "raise SystemExit(1)\n", "pkg/green.py": "raise SystemExit(0)\n",
            "other/outside.js": "var o = 1;\n",
        })
        self.out = os.path.join(self.base, "out")
        self.runs = os.path.join(self.base, "runs")
        os.mkdir(self.runs)

    def results(self, candidates: dict, red=RED, rec=None, runner=None) -> dict:
        return K.results(rec or recipe(), self.tree, {"operating": operating()}, red, candidates, self.out,
                         runner=runner or FakeDocker(), base=self.runs)

    def decide(self, cid: str, diff_bytes: bytes, merge_paused=False) -> dict:
        """MF8's own command on the files this module wrote."""
        cand_dir = os.path.join(self.base, "cand-" + cid)
        os.makedirs(cand_dir, exist_ok=True)
        with open(os.path.join(cand_dir, "finding.json"), "w") as fh:
            json.dump(FINDING, fh)
        with open(os.path.join(cand_dir, "diff.patch"), "wb") as fh:
            fh.write(diff_bytes)
        run_dir = os.path.join(self.out, "c", cid)
        proc = subprocess.run(
            [sys.executable, "-m", "gate.check", "decide", cand_dir, os.path.join(self.out, "base.jsonl"), run_dir,
             os.path.join(run_dir, "hashes.json")],
            input=json.dumps({"control": {"merge_paused": merge_paused}, "unfinished_sentinels": []}).encode(),
            cwd=REFEREE, capture_output=True)
        return json.loads(proc.stdout)


class TheBase(Base):
    def test_base_jsonl_is_three_records_of_the_base_tree(self):
        index = self.results({})
        record = {"tool": "eslint", "violations": [{"rule_id": "no-var", "path": "pkg/a.js", "line": 1,
                                                    "fix": [1, 1]}]}
        data = read(os.path.join(self.out, "base.jsonl"))
        self.assertEqual(data, R.run_file([record] * 3))
        self.assertEqual(index["base"], {"verdict": "verified", "reasons": []})
        self.assertEqual(index["base_run_sha256"], sha(data))
        self.assertEqual(json.loads(read(os.path.join(self.out, "index.json"))), index)

    def test_only_the_inputs_are_in_the_worktree(self):
        self.results({})
        self.assertNotIn(b"other/outside.js", read(os.path.join(self.out, "base.jsonl")))

    def test_each_lint_run_is_its_own_contained_run_with_a_red_control(self):
        docker = FakeDocker()
        self.results({}, runner=docker)
        cmds = [c["argv"][c["argv"].index(IMAGE) + 1:] for c in docker.calls]
        self.assertEqual(cmds, [["python", "pkg/red.py"], ["python", "pkg/lint.py"]] * 3)
        self.assertTrue(all("none" == c["argv"][c["argv"].index("--network") + 1] for c in docker.calls))
        self.assertEqual(len({c["name"] for c in docker.calls}), 6)

    def test_a_failing_lint_gives_no_base_and_no_candidate_runs(self):
        write_tree(self.tree, {"pkg/a.js": "LINTCRASH\n"})
        docker = FakeDocker()
        index = self.results({"good": GOOD}, runner=docker)
        self.assertEqual(index["base"]["verdict"], "refused")
        self.assertEqual(index["base"]["reasons"], ["lint_failed:1", "lint_failed:2", "lint_failed:3"])
        self.assertIsNone(index["base_run_sha256"])
        self.assertFalse(os.path.exists(os.path.join(self.out, "base.jsonl")))
        self.assertEqual(index["candidates"]["good"], {"verdict": "no_verdict", "reasons": ["base_unavailable"]})
        self.assertEqual(len(docker.calls), 6)

    def test_output_that_does_not_convert_gives_no_base(self):
        write_tree(self.tree, {"pkg/a.js": "GARBAGE\n"})
        index = self.results({})
        self.assertEqual(index["base"]["reasons"], ["lint_output:not_eslint_json"])
        self.assertFalse(os.path.exists(os.path.join(self.out, "base.jsonl")))

    def test_a_green_red_control_gives_no_base(self):
        index = self.results({"good": GOOD}, red=GREEN_RED)
        self.assertEqual(index["base"], {"verdict": "no_verdict", "reasons": ["red_control_green"]})
        self.assertFalse(os.path.exists(os.path.join(self.out, "base.jsonl")))
        self.assertEqual(index["candidates"]["good"]["reasons"], ["base_unavailable"])

    def test_a_recipe_the_static_check_refuses_runs_nothing(self):
        docker = FakeDocker()
        index = self.results({}, rec=recipe(services=["db"]), runner=docker)
        self.assertEqual(index["base"]["verdict"], "refused")
        self.assertIn("services_not_empty", index["base"]["reasons"])
        self.assertEqual(docker.calls, [])

    def test_out_must_not_exist(self):
        os.mkdir(self.out)
        with self.assertRaises(K.KosError):
            self.results({})


class Candidates(Base):
    def test_good_candidate_files_and_the_gate_merges_it(self):
        index = self.results({"good": GOOD})
        self.assertEqual(index["candidates"]["good"], {"verdict": "verified", "reasons": []})
        run_dir = os.path.join(self.out, "c", "good")
        self.assertEqual(read(os.path.join(run_dir, "cand.jsonl")), R.run_file([{"tool": "eslint", "violations": []}] * 3))
        self.assertEqual(json.loads(read(os.path.join(run_dir, "checks.json"))), {
            "red_control": "fail",
            "tests": [{"id": "a loads", "status": "pass"}, {"id": "a is not broken # really", "status": "pass"}]})
        self.assertEqual(json.loads(read(os.path.join(run_dir, "hashes.json"))), {
            name: sha(read(os.path.join(self.out if name == "base.jsonl" else run_dir, name)))
            for name in ("base.jsonl", "cand.jsonl", "checks.json")})
        self.assertEqual(self.decide("good", GOOD), {"decision": "merge", "reasons": []})

    def test_each_bad_candidate_is_rejected_by_the_gate_for_its_own_reason(self):
        self.results({"breaks": BREAKS_TEST, "raises": RAISES, "noisy": NOISY})
        self.assertEqual(self.decide("breaks", BREAKS_TEST)["reasons"], ["tests_red"])
        self.assertEqual(self.decide("raises", RAISES)["reasons"], ["ratchet_increase"])
        self.assertEqual(self.decide("noisy", NOISY)["reasons"], ["tool_nondeterministic"])

    def test_candidates_do_not_see_each_other_or_change_the_base(self):
        self.results({"a-breaks": BREAKS_TEST, "b-good": GOOD})
        self.assertEqual(self.decide("b-good", GOOD), {"decision": "merge", "reasons": []})
        self.assertEqual(read(os.path.join(self.tree, "pkg/a.js")).decode(), A_JS)

    def test_a_green_red_control_is_written_for_the_gate(self):
        # base ran with the real red control; the candidate's runs then meet a green one
        docker = FakeDocker()
        calls = {"n": 0}

        def runner(argv, env, timeout):
            calls["n"] += 1
            if calls["n"] > 6 and "pkg/red.py" in argv:
                argv = argv[:-1] + ["pkg/green.py"]
            return docker(argv, env, timeout)
        index = self.results({"good": GOOD}, runner=runner)
        self.assertEqual(index["candidates"]["good"], {"verdict": "no_verdict", "reasons": ["red_control_green"]})
        checks = json.loads(read(os.path.join(self.out, "c", "good", "checks.json")))
        self.assertEqual(checks["red_control"], "pass")
        self.assertEqual(self.decide("good", GOOD)["reasons"], ["red_control_green"])

    def test_a_run_that_tells_nothing_writes_no_file(self):
        # the red control of the candidate's test run cannot run (docker's 125; calls 1-6 are the base's lint
        # runs, 7-12 the candidate's, 13 the test run's red control): that run is not valid, whatever it printed
        docker = FakeDocker()
        calls = {"n": 0}

        def runner(argv, env, timeout):
            calls["n"] += 1
            if calls["n"] == 13:
                self.assertIn("pkg/red.py", argv)
                return C.RunnerResult(125, b"", b"", False)
            return docker(argv, env, timeout)
        index = self.results({"good": GOOD}, runner=runner)
        self.assertEqual(index["candidates"]["good"]["verdict"], "no_verdict")
        self.assertEqual(index["candidates"]["good"]["reasons"], ["red_control_fault"])
        self.assertFalse(os.path.exists(os.path.join(self.out, "c", "good")))

    def test_a_test_run_over_its_time_limit_writes_no_file(self):
        slow = diff("pkg/a.js", ["var a = 1;"], ["let a = 1; // SLOW"])
        write_tree(self.tree, {"pkg/run_tests.py": "import time\nif 'SLOW' in open('pkg/a.js').read():\n"
                                                   "    time.sleep(5)\nprint('ok 1 - a')\n"})
        index = self.results({"slow": slow}, rec=recipe(limits={"test_total_s": 2}))
        self.assertEqual(index["candidates"]["slow"], {"verdict": "no_verdict", "reasons": ["limit_hit:test_total_s"]})
        self.assertFalse(os.path.exists(os.path.join(self.out, "c", "slow")))

    def test_a_crashing_test_command_is_red_not_zero_tests(self):
        crash = diff("pkg/a.js", ["var a = 1;"], ["let a = 1; // CRASH"])
        self.results({"crash": crash})
        checks = json.loads(read(os.path.join(self.out, "c", "crash", "checks.json")))
        self.assertEqual(checks["tests"], [{"id": "test_cmd exit 7", "status": "fail"}])
        self.assertEqual(self.decide("crash", crash)["reasons"], ["tests_red"])

    def test_a_candidate_whose_lint_fails_has_no_files(self):
        bad = diff("pkg/a.js", ["var a = 1;"], ["LINTCRASH"])
        index = self.results({"bad": bad})
        self.assertEqual(index["candidates"]["bad"]["verdict"], "refused")
        self.assertEqual(index["candidates"]["bad"]["reasons"], ["lint_failed:1", "lint_failed:2", "lint_failed:3"])
        self.assertFalse(os.path.exists(os.path.join(self.out, "c", "bad")))

    def test_diffs_that_do_not_apply_in_place_are_refused_before_any_run(self):
        os.symlink("a.js", os.path.join(self.tree, "pkg", "link.js"))
        create = ("diff --git a/pkg/new.js b/pkg/new.js\nnew file mode 100644\nindex 0000000..2222222\n"
                  "--- /dev/null\n+++ b/pkg/new.js\n@@ -0,0 +1,1 @@\n+let n = 1;\n").encode()
        cases = {
            "stale": (diff("pkg/a.js", ["var z = 9;"], ["let z = 9;"]), ["patch_does_not_apply"]),
            "outside": (diff("other/outside.js", ["var o = 1;"], ["let o = 1;"]), ["base_file_missing"]),
            "symlink": (diff("pkg/link.js", ["var a = 1;"], ["let a = 1;"]), ["base_file_missing"]),
            "escape": (diff("pkg/../pkg/a.js", ["var a = 1;"], ["let a = 1;"]), ["patch_path_invalid"]),
            "reserved": (diff(".snowball/x.js", ["a"], ["b"]), ["reserved_path"]),
            "create": (create, ["patch_not_in_place"]),
            "garbage": (b"not a diff\n", ["patch_unusable"]),
            "two-one-bad": (GOOD + diff("pkg/b.js", ["nope"], ["x"]), ["patch_does_not_apply"]),
        }
        docker = FakeDocker()
        index = self.results({cid: d for cid, (d, _) in cases.items()}, runner=docker)
        for cid, (_, reasons) in cases.items():
            self.assertEqual(index["candidates"][cid], {"verdict": "refused", "reasons": reasons}, cid)
            self.assertFalse(os.path.exists(os.path.join(self.out, "c", cid)), cid)
        self.assertEqual(len(docker.calls), 6)  # the base's three lint runs and their red controls only

    def test_an_invalid_candidate_id_writes_nothing(self):
        index = self.results({"../x": GOOD, ".hidden": GOOD})
        for cid in ("../x", ".hidden"):
            self.assertEqual(index["candidates"][cid]["reasons"], ["candidate_id_invalid"])
        self.assertEqual(sorted(os.listdir(self.out)), ["base.jsonl", "index.json"])


MERGE = "c" * 40
AFFECTED = ["python", "pkg/affected.py"]
# The affected tests: three top-level tests; BROKEN in pkg/a.js fails "a is not broken", TWICE prints one
# description twice; run with the argument "flip", "a flips" fails (a contained run keeps no state between runs, so
# the flaky test's first run is the runner's: Sentinel.flip).
AFFECTED_PY = r'''import sys
src = open("pkg/a.js").read()
fail = ["a flips"] if sys.argv[1:] == ["flip"] else []
if "BROKEN" in src:
    fail.append("a is not broken")
if "SLOW" in src:
    import time
    time.sleep(5)
names = ["a loads", "a is not broken", "a flips"] + (["a loads"] if "TWICE" in src else [])
for i, name in enumerate(names, 1):
    print(("not ok" if name in fail else "ok") + " %d - %s" % (i, name))
sys.exit(1 if fail else 0)
'''


class Sentinel(Base):
    def setUp(self) -> None:
        super().setUp()
        write_tree(self.tree, {"pkg/affected.py": AFFECTED_PY})

    def watch(self, a_js: str | None = None, runner=None, rec=None, red=RED) -> dict:
        if a_js is not None:
            write_tree(self.tree, {"pkg/a.js": a_js})
        return K.results(rec or recipe(affected_test_cmd=AFFECTED), self.tree, {"operating": operating()}, red, {},
                         self.out, runner=runner or FakeDocker(), base=self.runs, watch=MERGE)

    def file(self) -> dict:
        return json.loads(read(os.path.join(self.out, K.SENTINEL)))

    def mf12(self, runs: list) -> dict:
        proc = subprocess.run([sys.executable, "-m", "gate.sentinel", "decide"], cwd=REFEREE, capture_output=True,
                              input=json.dumps({"runs": runs}).encode())
        return json.loads(proc.stdout)

    def affected_runs(self, docker) -> int:
        return sum(1 for c in docker.calls if c["argv"][-len(AFFECTED):] == AFFECTED)

    def test_nothing_watched_runs_no_test_and_writes_no_file(self):
        docker = FakeDocker()
        index = self.results({}, runner=docker)
        self.assertIsNone(index["sentinel"])
        self.assertEqual(self.affected_runs(docker), 0)
        self.assertFalse(os.path.exists(os.path.join(self.out, K.SENTINEL)))

    def test_green_after_one_run_of_the_affected_tests(self):
        docker = FakeDocker()
        index = self.watch(runner=docker)
        got = self.file()
        self.assertEqual(index["sentinel"], {"merge_sha": MERGE, "verdict": "green", "reasons": [],
                                             "sha256": sha(read(os.path.join(self.out, K.SENTINEL)))})
        self.assertEqual(got, {"merge_sha": MERGE, "verdict": "green", "red": [], "flaky": [], "runs": [
            {"results": [{"id": n, "status": "pass"} for n in ("a loads", "a is not broken", "a flips")]}]})
        self.assertEqual(self.affected_runs(docker), 1)
        # the run is contained: the red control first, no network, its own container
        cmds = [c["argv"][c["argv"].index(IMAGE) + 1:] for c in docker.calls]
        self.assertEqual(cmds[-2:], [RED["cmd"], AFFECTED])
        self.assertEqual(docker.calls[-1]["argv"][docker.calls[-1]["argv"].index("--network") + 1], "none")
        self.assertEqual(json.loads(read(os.path.join(self.out, K.INDEX))), index)
        self.assertEqual(self.mf12(got["runs"])["verdict"], "green")

    def test_red_after_four_runs_names_the_test(self):
        docker = FakeDocker()
        index = self.watch("var a = 1; // BROKEN\n", runner=docker)
        got = self.file()
        self.assertEqual((index["sentinel"]["verdict"], got["red"], got["flaky"]), ("red", ["a is not broken"], []))
        self.assertEqual((len(got["runs"]), self.affected_runs(docker)), (4, 4))
        self.assertEqual({c["name"] for c in docker.calls}.__len__(), len(docker.calls))
        self.assertEqual({k: v for k, v in self.mf12(got["runs"]).items()},
                         {"verdict": "red", "red": ["a is not broken"], "flaky": [], "revert": True})

    def test_flaky_when_a_rerun_passes(self):
        docker = FakeDocker()
        seen = {"n": 0}

        def flip(argv, env, timeout):
            if argv[-len(AFFECTED):] == AFFECTED:
                seen["n"] += 1
                if seen["n"] == 1:
                    argv = argv + ["flip"]
            return docker(argv, env, timeout)
        index = self.watch(runner=flip)
        got = self.file()
        self.assertEqual((index["sentinel"]["verdict"], got["red"], got["flaky"]), ("flaky", [], ["a flips"]))
        self.assertEqual(len(got["runs"]), 4)
        self.assertEqual(self.mf12(got["runs"])["verdict"], "flaky")

    def test_a_failing_base_lint_does_not_stop_it(self):
        index = self.watch("LINTCRASH\n")
        self.assertEqual(index["base"]["verdict"], "refused")
        self.assertEqual(index["sentinel"]["verdict"], "green")

    def test_the_heads_lint_tells_whether_it_built(self):
        """``loop.watch.base_build`` on what this module writes: a head ESLint cannot parse is refused with
        ``lint_output:fatal:<path>`` and is no build; a head that lints is one; a crashing lint tells nothing; a lint
        whose red control passed tells nothing even with the fatal reason."""
        index = self.watch("var a = 1; // BROKEN PARSE_ERROR\n")
        self.assertEqual(index["base"], {"verdict": "refused", "reasons": ["lint_output:fatal:pkg/a.js"]})
        self.assertEqual((index["sentinel"]["verdict"], self.file()["red"]), ("red", ["a is not broken"]))
        self.assertIs(WT.base_build(self.out), False)
        for a_js, want in (("var a = 1; // BROKEN\n", True), ("var a = 1; // BROKEN LINTCRASH\n", None)):
            with self.subTest(a_js=a_js):
                shutil.rmtree(self.out)
                self.watch(a_js)
                self.assertIs(WT.base_build(self.out), want)
        shutil.rmtree(self.out)
        docker = FakeDocker()

        def runner(argv, env, timeout):  # the lint runs' red controls pass
            if len(docker.calls) < 6 and "pkg/red.py" in argv:
                argv = argv[:-1] + ["pkg/green.py"]
            return docker(argv, env, timeout)
        index = self.watch("var a = 1; // PARSE_ERROR\n", runner=runner)
        self.assertEqual(index["base"]["reasons"], ["red_control_green", "lint_output:fatal:pkg/a.js"])
        self.assertIsNone(WT.base_build(self.out))

    def test_a_green_red_control_judges_no_test(self):
        # calls 1-6: the base's lint runs and their red controls; call 7 is the sentinel's red control
        docker = FakeDocker()
        calls = {"n": 0}

        def runner(argv, env, timeout):
            calls["n"] += 1
            if calls["n"] > 6 and "pkg/red.py" in argv:
                argv = argv[:-1] + ["pkg/green.py"]
            return docker(argv, env, timeout)
        index = self.watch("var a = 1; // BROKEN\n", runner=runner)
        self.assertEqual(index["sentinel"], {"merge_sha": MERGE, "verdict": None, "reasons": ["red_control_green"],
                                             "sha256": None})
        self.assertFalse(os.path.exists(os.path.join(self.out, K.SENTINEL)))
        self.assertEqual(self.affected_runs(docker), 1)  # the runs stop at the first that tells nothing

    def test_a_rerun_that_tells_nothing_stops_the_runs(self):
        # run 1 is red; the red control of run 2 (call 9) cannot run
        docker = FakeDocker()
        calls = {"n": 0}

        def runner(argv, env, timeout):
            calls["n"] += 1
            if calls["n"] == 9:
                self.assertIn("pkg/red.py", argv)
                return C.RunnerResult(125, b"", b"", False)
            return docker(argv, env, timeout)
        index = self.watch("var a = 1; // BROKEN\n", runner=runner)
        self.assertEqual((index["sentinel"]["verdict"], index["sentinel"]["reasons"]), (None, ["red_control_fault"]))
        self.assertEqual(self.affected_runs(docker), 2)
        self.assertFalse(os.path.exists(os.path.join(self.out, K.SENTINEL)))

    def test_a_run_over_its_time_limit_judges_no_test(self):
        index = self.watch("var a = 1; // SLOW\n", rec=recipe(affected_test_cmd=AFFECTED, limits={"test_total_s": 2}))
        self.assertEqual((index["sentinel"]["verdict"], index["sentinel"]["reasons"]),
                         (None, ["limit_hit:test_total_s"]))

    def test_one_description_twice_is_no_verdict(self):
        index = self.watch("var a = 1; // TWICE\n")
        self.assertEqual((index["sentinel"]["verdict"], index["sentinel"]["reasons"]), (None, ["sentinel_unusable"]))
        self.assertFalse(os.path.exists(os.path.join(self.out, K.SENTINEL)))

    def test_a_base_that_does_not_stage_runs_nothing(self):
        docker = FakeDocker()
        index = self.watch(runner=docker, rec=recipe(affected_test_cmd=AFFECTED, services=["db"]))
        self.assertIsNone(index["sentinel"]["verdict"])
        self.assertIn("services_not_empty", index["sentinel"]["reasons"])
        self.assertEqual(docker.calls, [])

    def test_watch_must_be_a_merge_sha(self):
        for bad in ("C" * 40, "c" * 39, 1, ""):
            with self.subTest(bad=bad), self.assertRaises(K.KosError):
                K.results(recipe(), self.tree, {"operating": operating()}, RED, {}, self.out, runner=FakeDocker(),
                          base=self.runs, watch=bad)


class Tap(unittest.TestCase):
    def test_node_test_real_output(self):
        with open(os.path.join(BRAIN, "tests", "fixtures", "toy-candidates", "bad-test.json")) as fh:
            got = json.load(fh)
        tests = K.tap_tests(got["test_stdout"].encode(), got["test_exit"])
        self.assertEqual(len(tests), 8)
        self.assertEqual([t["id"] for t in tests if t["status"] == "fail"],
                         ["slugify lowers, joins words with dashes and trims dashes"])

    def test_edges(self):
        out = ("ok 1 - a\n  ok 1 - sub\nnot ok 2 - b # TODO later\nok 3 - c # skip\nok 4\n"
               "ok 5 - x \\# y \\\\ z\nnot ok 6 - d # some other directive\nok 7 - e\r\n").encode()
        self.assertEqual(K.tap_tests(out, 1), [
            {"id": "a", "status": "pass"}, {"id": "4", "status": "pass"}, {"id": "x # y \\ z", "status": "pass"},
            {"id": "d", "status": "fail"}, {"id": "e", "status": "pass"}])

    def test_exit_code_without_a_failing_line_is_a_failure(self):
        self.assertEqual(K.tap_tests(b"ok 1 - a\nBail out!\n", 1)[-1], {"id": "test_cmd exit 1", "status": "fail"})
        self.assertEqual(K.tap_tests(b"", None), [{"id": "test_cmd exit None", "status": "fail"}])
        self.assertEqual(K.tap_tests(b"", 0), [])
        self.assertEqual(K.tap_tests(b"ok 1 - a # SKIP\n", 0), [])


class CommandLine(Base):
    def run_cli(self, req) -> subprocess.CompletedProcess:
        path = os.path.join(self.base, "req.json")
        with open(path, "w") as fh:
            json.dump(req, fh)
        return subprocess.run([sys.executable, "-m", "runner.kos", "run", path], cwd=REFEREE, capture_output=True)

    def test_unusable_input_is_exit_2_without_a_traceback(self):
        for req in ({}, {"tree": self.tree, "out": self.out, "candidates": {"x": 1}},
                    {"tree": self.tree, "out": self.out, "candidates": {"x": "/nonexistent"}}):
            proc = self.run_cli(req)
            self.assertEqual(proc.returncode, 2)
            self.assertFalse(json.loads(proc.stdout)["ok"])
            self.assertNotIn(b"Traceback", proc.stderr)


if __name__ == "__main__":
    unittest.main()
