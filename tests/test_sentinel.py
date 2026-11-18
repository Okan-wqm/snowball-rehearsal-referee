"""Test 36 (asama-0/09) and group ``flaky`` (tohum/29j): ``sentinel.run``'s decision and its rerun loop.

- green: a first run with results and no fail is green and later runs are not read (even malformed ones);
  a first run with zero results is not green (tohum/04);
- 3/3: one red run, and a red run with two reruns, are ``rerun`` and name no test; the first four runs are
  judged and a fifth is not read; per test, failing in all four is red, in some is flaky, absence is not a fail;
  four runs without a result are red; ``revert`` only for red; lists sorted by code point;
- the loop: ``watch`` asks for no rerun after a green run and exactly three after a red one, and its verdict is
  ``decide``'s on the runs it used;
- shapes: every malformed run, result, id, status and duplicate id is unusable; the command line's outputs and
  exits 0/1/2.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest

REFEREE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REFEREE)

from gate import sentinel as S  # noqa: E402


def run(**statuses):
    return {"results": [{"id": test_id, "status": status} for test_id, status in statuses.items()]}


def ids(*pairs):
    return {"results": [{"id": test_id, "status": status} for test_id, status in pairs]}


GREEN = run(a="pass", b="pass")
RED_A = run(a="fail", b="pass")
EMPTY_RUN = {"results": []}
BROKEN = {"results": "not a list"}


def cli(stdin: bytes, *argv: str):
    proc = subprocess.run([sys.executable, "-m", "gate.sentinel", *argv], cwd=REFEREE, input=stdin,
                          capture_output=True, timeout=60)
    lines = proc.stdout.decode().splitlines()
    return proc.returncode, (json.loads(lines[0]) if len(lines) == 1 else lines), proc.stderr.decode()


class Green(unittest.TestCase):
    def test_green_first_run(self):
        self.assertEqual(S.decide([GREEN]),
                         {"verdict": "green", "red": [], "flaky": [], "revert": False})

    def test_later_runs_not_read_after_green(self):
        # a malformed or red second run changes nothing: it is not read
        self.assertEqual(S.decide([GREEN, BROKEN, RED_A, 7])["verdict"], "green")

    def test_zero_tests_is_not_green(self):
        self.assertEqual(S.decide([EMPTY_RUN])["verdict"], "rerun")

    def test_one_fail_among_passes_is_not_green(self):
        self.assertEqual(S.decide([run(a="pass", b="pass", c="fail")])["verdict"], "rerun")


class ThreeOfThree(unittest.TestCase):
    def test_one_red_run_never_reverts(self):
        self.assertEqual(S.decide([RED_A]), {"verdict": "rerun", "red": [], "flaky": [], "revert": False})

    def test_two_reruns_rerun(self):
        self.assertEqual(S.decide([RED_A, RED_A, RED_A]),
                         {"verdict": "rerun", "red": [], "flaky": [], "revert": False})

    def test_no_runs_rerun(self):
        self.assertEqual(S.decide([])["verdict"], "rerun")

    def test_red_three_reruns(self):
        self.assertEqual(S.decide([RED_A] * 4), {"verdict": "red", "red": ["a"], "flaky": [], "revert": True})

    def test_per_test_rule(self):
        runs = [run(a="fail", b="fail"), run(a="fail", b="pass"), run(a="fail", b="pass"), run(a="fail", b="pass")]
        self.assertEqual(S.decide(runs), {"verdict": "red", "red": ["a"], "flaky": ["b"], "revert": True})

    def test_failing_in_three_of_four_is_flaky_not_red(self):
        # a passes in exactly one of the four runs (b keeps run 1 red when a passes there)
        for passing in range(4):
            runs = [run(a="fail", b="fail")] + [RED_A] * 3
            runs[passing] = run(a="pass", b="fail")
            with self.subTest(passing_run=passing + 1):
                result = S.decide(runs)
                self.assertNotIn("a", result["red"])
                self.assertIn("a", result["flaky"])

    def test_flaky_only_does_not_revert(self):
        runs = [RED_A, GREEN, GREEN, GREEN]
        self.assertEqual(S.decide(runs), {"verdict": "flaky", "red": [], "flaky": ["a"], "revert": False})

    def test_absent_is_not_a_fail(self):
        # a fails in runs 1-3 and is missing from run 4: not failing everywhere, so flaky
        runs = [RED_A, RED_A, RED_A, run(b="pass")]
        self.assertEqual(S.decide(runs), {"verdict": "flaky", "red": [], "flaky": ["a"], "revert": False})

    def test_fifth_run_not_read(self):
        self.assertEqual(S.decide([RED_A] * 4 + [GREEN])["red"], ["a"])
        self.assertEqual(S.decide([RED_A] * 4 + [BROKEN])["red"], ["a"])
        self.assertEqual(S.decide([RED_A, GREEN, GREEN, GREEN, RED_A])["verdict"], "flaky")

    def test_no_result_in_any_judged_run_is_red(self):
        self.assertEqual(S.decide([EMPTY_RUN] * 4), {"verdict": "red", "red": [], "flaky": [], "revert": True})

    def test_zero_test_first_run_then_passing_reruns_is_flaky(self):
        self.assertEqual(S.decide([EMPTY_RUN, GREEN, GREEN, GREEN]),
                         {"verdict": "flaky", "red": [], "flaky": [], "revert": False})

    def test_judged_runs_are_checked(self):
        for bad in range(1, 4):
            runs = [RED_A] * 4
            runs[bad] = BROKEN
            with self.subTest(run=bad + 1), self.assertRaises(S.Unusable):
                S.decide(runs)

    def test_sorted_by_code_point(self):
        names = ["b", "B", "a", "é", "a2", "Z"]
        runs = [run(**{n: "fail" for n in names})] * 4
        self.assertEqual(S.decide(runs)["red"], sorted(names))
        self.assertEqual(S.decide(runs)["red"], ["B", "Z", "a", "a2", "b", "é"])
        flaky = [run(**{n: "fail" for n in names})] + [GREEN] * 3
        self.assertEqual(S.decide(flaky)["flaky"], ["B", "Z", "a", "a2", "b", "é"])


class Watch(unittest.TestCase):
    def counter(self, runs):
        calls = []

        def rerun():
            calls.append(1)
            return runs[len(calls) - 1]
        return rerun, calls

    def test_green_asks_no_rerun(self):
        rerun, calls = self.counter([])
        result = S.watch(GREEN, rerun)
        self.assertEqual((result["verdict"], len(calls), len(result["runs"])), ("green", 0, 1))

    def test_red_asks_exactly_three(self):
        rerun, calls = self.counter([RED_A, RED_A, RED_A, GREEN, GREEN])
        result = S.watch(RED_A, rerun)
        self.assertEqual(len(calls), 3)
        self.assertEqual(result["runs"], [RED_A] * 4)
        self.assertEqual({k: result[k] for k in ("verdict", "red", "flaky", "revert")}, S.decide([RED_A] * 4))

    def test_zero_tests_asks_three(self):
        rerun, calls = self.counter([GREEN] * 5)
        self.assertEqual((S.watch(EMPTY_RUN, rerun)["verdict"], len(calls)), ("flaky", 3))

    def test_flaky_through_watch(self):
        rerun, calls = self.counter([GREEN, GREEN, GREEN])
        result = S.watch(RED_A, rerun)
        self.assertEqual((result["verdict"], result["flaky"], result["revert"], len(calls)), ("flaky", ["a"], False, 3))

    def test_malformed_rerun_unusable(self):
        rerun, _ = self.counter([RED_A, BROKEN, RED_A])
        with self.assertRaises(S.Unusable):
            S.watch(RED_A, rerun)


class Shapes(unittest.TestCase):
    BAD_RUNS = {
        "not_object": [1],
        "extra_run_member": [{"results": [], "name": "x"}],
        "no_results": [{}],
        "results_not_list": [BROKEN],
        "results_empty_object": [{"results": {}}],
        "results_empty_string": [{"results": ""}],
        "result_not_object": [{"results": ["a"]}],
        "extra_result_member": [{"results": [{"id": "a", "status": "pass", "ms": 1}]}],
        "missing_status": [{"results": [{"id": "a"}]}],
        "empty_id": [ids(("", "pass"))],
        "id_not_string": [{"results": [{"id": 1, "status": "pass"}]}],
        "status_skip": [ids(("a", "skip"))],
        "status_case": [ids(("a", "PASS"))],
        "status_list": [{"results": [{"id": "a", "status": ["pass"]}]}],
        "status_bool": [{"results": [{"id": "a", "status": True}]}],
        "duplicate_id": [ids(("a", "pass"), ("a", "fail"))],
        "duplicate_same": [ids(("a", "pass"), ("a", "pass"))],
    }

    def test_each_bad_first_run_unusable(self):
        for name, runs in self.BAD_RUNS.items():
            with self.subTest(name), self.assertRaises(S.Unusable):
                S.decide(runs)

    def test_runs_not_list(self):
        for value in ({}, None, "runs", GREEN):
            with self.subTest(value=value), self.assertRaises(S.Unusable):
                S.decide(value)


class CommandLine(unittest.TestCase):
    def test_green_exit_0(self):
        code, out, _ = cli(json.dumps({"runs": [GREEN]}).encode(), "decide")
        self.assertEqual((code, out), (0, {"verdict": "green", "red": [], "flaky": [], "revert": False}))

    def test_red_exit_1(self):
        code, out, _ = cli(json.dumps({"runs": [RED_A] * 4}).encode(), "decide")
        self.assertEqual((code, out), (1, {"verdict": "red", "red": ["a"], "flaky": [], "revert": True}))

    def test_rerun_and_flaky_exit_1(self):
        for runs, verdict in (([RED_A], "rerun"), ([RED_A, GREEN, GREEN, GREEN], "flaky")):
            code, out, _ = cli(json.dumps({"runs": runs}).encode(), "decide")
            self.assertEqual((code, out["verdict"]), (1, verdict))

    def test_unusable_exit_2(self):
        empty = {"verdict": None, "red": [], "flaky": [], "revert": False}
        cases = {
            "not_json": (b"{", ("decide",)),
            "not_utf8": (b"\xff", ("decide",)),
            "extra_stdin_member": (json.dumps({"runs": [GREEN], "x": 1}).encode(), ("decide",)),
            "no_runs_member": (b"{}", ("decide",)),
            "duplicate_member": (b'{"runs": [], "runs": []}', ("decide",)),
            "bad_run": (json.dumps({"runs": [BROKEN]}).encode(), ("decide",)),
            "no_command": (json.dumps({"runs": [GREEN]}).encode(), ()),
            "other_command": (json.dumps({"runs": [GREEN]}).encode(), ("judge",)),
            "extra_arg": (json.dumps({"runs": [GREEN]}).encode(), ("decide", "x")),
            "array": (b"[]", ("decide",)),
        }
        for name, (stdin, argv) in cases.items():
            with self.subTest(name):
                code, out, err = cli(stdin, *argv)
                self.assertEqual((code, out), (2, empty))
                self.assertTrue(err.startswith("unusable input:"), err)


if __name__ == "__main__":
    unittest.main()
