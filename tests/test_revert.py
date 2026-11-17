"""Test 25 (asama-0/09) and group ``cause`` (tohum/29j): ``gate.revert``'s mechanical cause and the revert.

- the rule: each of the five causes from its own case, the order (a build break wins over lint and tests, lint
  over tests), lint per tool (one tool's drop does not offset another's rise; an equal count is not a rise),
  one red test inside the set is enough for ``test_regression``, a repeated id changes nothing;
- shapes: every malformed request is unusable, never a cause (missing or extra key, wrong types, bool counts,
  negative counts, empty ids or tool names);
- the revert on the in-process GitHub: a verified red reverts the merge with a commit whose tree is the merge's
  first parent's tree, on a branch, with a pull request carrying the cause; after the gate's check and merge,
  ``brain/integration`` has the first parent's tree again; green, flaky and too few runs send nothing; the red
  tests are the sentinel's, not the caller's; unusable facts and a merge that is not the head write nothing;
- a red with no red test: a green or flaky verdict whose facts state ``build_break`` or ``lint_regression`` is a
  revert (29j's ``lint_regression`` and ``lint_per_tool`` cases have no red test); one whose facts state nothing
  is not; a ``rerun`` reverts nothing and reads no facts; a green or flaky verdict without usable facts is unusable;
- ``assess``: the same verdict and cause with nothing sent; ``build_ok`` null (the build unread) is ``unknown``
  whatever the lint, with the other fields' shapes still checked; ``lint`` null (the totals unreadable) is ``unknown``
  unless the build broke, the other facts still checked; the command line refuses a null ``lint`` or ``build_ok``;
- the command line's outputs and exits 0/2.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest

REFEREE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REFEREE)

from gate import revert as R  # noqa: E402
from gate import sentinel  # noqa: E402
from target import write as W  # noqa: E402
from test_write import GATE, candidate, world, writes  # noqa: E402


def req(red=(), impact=(), build_ok=True, lint=None):
    return {"red_tests": list(red), "impact": list(impact), "build_ok": build_ok,
            "lint": {"eslint": {"before": 3, "after": 3}} if lint is None else lint}


def cli(stdin: bytes, *argv: str):
    proc = subprocess.run([sys.executable, "-m", "gate.revert", *argv], cwd=REFEREE, input=stdin,
                          capture_output=True, timeout=60)
    lines = proc.stdout.decode().splitlines()
    return proc.returncode, (json.loads(lines[0]) if len(lines) == 1 else lines), proc.stderr.decode()


class Rule(unittest.TestCase):
    def test_test_regression(self):
        self.assertEqual(R.cause(req(red=["a"], impact=["a", "b"])), "test_regression")

    def test_impact_miss(self):
        self.assertEqual(R.cause(req(red=["c"], impact=["a", "b"])), "impact_miss")
        self.assertEqual(R.cause(req(red=["c"], impact=[])), "impact_miss")

    def test_one_red_inside_the_set_is_test_regression(self):
        self.assertEqual(R.cause(req(red=["c", "a"], impact=["a"])), "test_regression")

    def test_build_break_first(self):
        lint = {"eslint": {"before": 1, "after": 9}}
        self.assertEqual(R.cause(req(red=["a"], impact=["a"], build_ok=False, lint=lint)), "build_break")
        self.assertEqual(R.cause(req(build_ok=False)), "build_break")

    def test_lint_regression(self):
        self.assertEqual(R.cause(req(lint={"eslint": {"before": 3, "after": 4}})), "lint_regression")

    def test_lint_before_tests(self):
        lint = {"eslint": {"before": 3, "after": 4}}
        self.assertEqual(R.cause(req(red=["a"], impact=["a"], lint=lint)), "lint_regression")
        self.assertEqual(R.cause(req(red=["c"], impact=["a"], lint=lint)), "lint_regression")

    def test_lint_per_tool(self):
        lint = {"eslint": {"before": 10, "after": 2}, "stylelint": {"before": 0, "after": 1}}
        self.assertEqual(R.cause(req(lint=lint)), "lint_regression")

    def test_equal_or_lower_lint_is_not_a_rise(self):
        lint = {"eslint": {"before": 3, "after": 3}, "stylelint": {"before": 5, "after": 0}}
        self.assertEqual(R.cause(req(red=["a"], impact=["a"], lint=lint)), "test_regression")

    def test_unknown(self):
        self.assertEqual(R.cause(req()), "unknown")
        self.assertEqual(R.cause(req(impact=["a"], lint={})), "unknown")

    def test_repeated_ids_change_nothing(self):
        self.assertEqual(R.cause(req(red=["c", "c"], impact=["a", "a"])), "impact_miss")
        self.assertEqual(R.cause(req(red=["a", "a"], impact=["a", "a"])), "test_regression")

    def test_only_the_five_causes(self):
        self.assertEqual(R.CAUSES, ("build_break", "lint_regression", "test_regression", "impact_miss",
                                    "unknown"))


class Shapes(unittest.TestCase):
    def assertUnusable(self, request):
        with self.assertRaises(R.Unusable):
            R.cause(request)

    def test_missing_or_extra_key(self):
        for key in R.REQUEST:
            bad = req(red=["a"], impact=["a"])
            del bad[key]
            self.assertUnusable(bad)
        self.assertUnusable(dict(req(), cause="unknown"))
        self.assertUnusable([req()])
        self.assertUnusable(None)

    def test_ids(self):
        for value in ("a", ["a", ""], ["a", 1], [None], {"a": 1}, None):
            self.assertUnusable(dict(req(), red_tests=value))
            self.assertUnusable(dict(req(), impact=value))

    def test_build_ok_is_a_bool(self):
        for value in (0, 1, "false", None):
            self.assertUnusable(req(build_ok=value))

    def test_lint(self):
        self.assertUnusable(dict(req(), lint=None))
        for lint in ([], {"": {"before": 0, "after": 0}}, {"eslint": {"before": 0}},
                     {"eslint": {"before": 0, "after": 1, "fixable": 0}}, {"eslint": [0, 1]},
                     {"eslint": {"before": True, "after": 2}}, {"eslint": {"before": 0, "after": False}},
                     {"eslint": {"before": -1, "after": 0}}, {"eslint": {"before": 0, "after": 1.0}},
                     {"eslint": {"before": "0", "after": 1}}):
            self.assertUnusable(req(lint=lint))


RED_A = {"results": [{"id": "a", "status": "fail"}, {"id": "b", "status": "pass"}]}
GREEN_RUN = {"results": [{"id": "a", "status": "pass"}, {"id": "b", "status": "pass"}]}
FACTS = {"impact": ["a"], "build_ok": True, "lint": {"eslint": {"before": 3, "after": 3}}}


class Revert(unittest.TestCase):
    def merged(self):
        gh, wr, root = world()
        n, sha = candidate(gh, wr)
        wr.check(sha, GATE, "success")
        return gh, wr, root, wr.merge(n, sha)

    def test_red_reverts_to_the_first_parents_tree(self):
        gh, wr, root, merge = self.merged()
        first, second = gh.commits[merge]["parents"]
        self.assertNotEqual(gh.commits[first]["tree"], gh.commits[merge]["tree"])
        out = R.revert_red(wr, [RED_A] * 4, FACTS, merge, "brain/integration", "brain/c/revert-1")
        self.assertEqual((out["reverted"], out["verdict"], out["red"], out["cause"]),
                         (True, "red", ["a"], "test_regression"))
        self.assertEqual(out["tree"], gh.commits[first]["tree"])
        self.assertNotIn(out["tree"], (gh.commits[merge]["tree"], gh.commits[second]["tree"]))
        self.assertEqual(out["parents"], [merge])
        self.assertEqual(gh.commits[out["commit"]]["message"], "revert %s: test_regression" % merge)
        self.assertEqual(gh.refs["brain/c/revert-1"], out["commit"])
        self.assertEqual(gh.refs["brain/integration"], merge)  # a branch and a pull request, not a push
        self.assertEqual(gh.pulls[out["pull"]]["head"], "brain/c/revert-1")
        self.assertEqual(gh.pulls[out["pull"]]["base"], "brain/integration")
        opened = [body for method, path, body in gh.requests if method == "POST" and path.endswith("/pulls")]
        self.assertEqual(opened[-1]["title"], "revert %s: test_regression" % merge)
        # the gate passes it like any candidate; then integration has the first parent's tree again
        wr.check(out["commit"], GATE, "success")
        reverted = wr.merge(out["pull"], out["commit"])
        self.assertEqual(gh.commits[gh.refs["brain/integration"]]["tree"], gh.commits[root]["tree"])
        self.assertEqual(gh.refs["brain/integration"], reverted)
        self.assertEqual(gh.refs["main"], root)

    def test_cause_reaches_the_commit(self):
        gh, wr, root, merge = self.merged()
        facts = dict(FACTS, impact=["z"])
        out = R.revert_red(wr, [RED_A] * 4, facts, merge, "brain/integration", "brain/c/revert-1")
        self.assertEqual(out["cause"], "impact_miss")
        self.assertEqual(gh.commits[out["commit"]]["message"], "revert %s: impact_miss" % merge)

    def test_not_red_sends_nothing(self):
        flaky = [RED_A, GREEN_RUN, GREEN_RUN, GREEN_RUN]
        for runs, verdict in (([GREEN_RUN], "green"), ([RED_A], "rerun"), ([RED_A] * 3, "rerun"), (flaky, "flaky")):
            gh, wr, root, merge = self.merged()
            before = len(gh.requests)
            out = R.revert_red(wr, runs, FACTS, merge, "brain/integration", "brain/c/revert-1")
            self.assertEqual(out, {"reverted": False, "verdict": verdict, "red": [], "cause": None,
                                   "commit": None, "tree": None, "parents": None, "pull": None})
            self.assertEqual(len(gh.requests), before)
            self.assertNotIn("brain/c/revert-1", gh.refs)

    def test_red_tests_are_the_sentinels(self):
        gh, wr, root, merge = self.merged()
        with self.assertRaises(R.Unusable):
            R.revert_red(wr, [RED_A] * 4, dict(FACTS, red_tests=[]), merge, "brain/integration", "brain/c/r")
        # the red the cause sees is decide's red: "a" is in the set, so not impact_miss
        self.assertEqual(sentinel.decide([RED_A] * 4)["red"], ["a"])

    def test_unusable_facts_or_runs_write_nothing(self):
        gh, wr, root, merge = self.merged()
        before = len(gh.requests)
        for facts in (None, dict(FACTS, build_ok="no"), {"impact": ["a"]}):
            with self.assertRaises(R.Unusable):
                R.revert_red(wr, [RED_A] * 4, facts, merge, "brain/integration", "brain/c/revert-1")
        with self.assertRaises(sentinel.Unusable):
            R.revert_red(wr, [RED_A, {"results": 1}, RED_A, RED_A], FACTS, merge, "brain/integration", "brain/c/r")
        self.assertEqual(len(gh.requests), before)

    def test_a_merge_that_is_not_the_head_is_not_reverted(self):
        gh, wr, root, merge = self.merged()
        n, sha = candidate(gh, wr, "brain/c/2", "t2")
        wr.check(sha, GATE, "success")
        wr.merge(n, sha)
        sent = len(writes(gh))
        with self.assertRaises(W.Refused) as ctx:
            R.revert_red(wr, [RED_A] * 4, FACTS, merge, "brain/integration", "brain/c/revert-1")
        self.assertEqual(ctx.exception.reasons, ["revert_not_head"])
        self.assertEqual(len(writes(gh)), sent)

    def test_a_lint_rise_with_green_tests_is_reverted(self):
        """The planted ``lint_regression`` of tohum/26f (tests and build clean): the merge is reverted to its first
        parent's tree with that cause; the same facts with an equal total send nothing."""
        gh, wr, root, merge = self.merged()
        before = len(gh.requests)
        same = R.revert_red(wr, [GREEN_RUN], FACTS, merge, "brain/integration", "brain/c/revert-1")
        self.assertEqual((same["reverted"], len(gh.requests)), (False, before))
        rising = dict(FACTS, lint={"eslint": {"before": 3, "after": 4}})
        out = R.revert_red(wr, [GREEN_RUN], rising, merge, "brain/integration", "brain/c/revert-1")
        self.assertEqual((out["reverted"], out["verdict"], out["red"], out["cause"]),
                         (True, "green", [], "lint_regression"))
        self.assertEqual(out["tree"], gh.commits[gh.commits[merge]["parents"][0]]["tree"])
        self.assertEqual(gh.commits[out["commit"]]["message"], "revert %s: lint_regression" % merge)

    def test_build_break_reverts_with_build_break(self):
        gh, wr, root, merge = self.merged()
        empty = {"results": []}
        out = R.revert_red(wr, [empty] * 4, dict(FACTS, build_ok=False), merge, "brain/integration",
                           "brain/c/revert-1")
        self.assertEqual((out["verdict"], out["red"], out["cause"]), ("red", [], "build_break"))


class Assess(unittest.TestCase):
    """``assess``: the verdict and the cause before anything is written; a red whose lint totals are unreadable."""

    def test_the_cause_without_writing(self):
        self.assertEqual(R.assess([RED_A] * 4, FACTS), {"revert": True, "verdict": "red", "red": ["a"],
                                                        "cause": R.cause(dict(FACTS, red_tests=["a"]))})
        self.assertEqual(R.assess([GREEN_RUN], FACTS), {"revert": False, "verdict": "green", "red": [], "cause": None})

    FLAKY = [RED_A, GREEN_RUN, GREEN_RUN, GREEN_RUN]
    RISING = {"eslint": {"before": 3, "after": 4}}
    PER_TOOL = {"eslint": {"before": 3, "after": 2}, "stylelint": {"before": 0, "after": 1}}

    def test_a_lint_rise_or_a_broken_build_is_a_red_with_no_red_test(self):
        """tohum/29j's cases ``lint_regression`` and ``lint_per_tool`` (``red_tests: []``) and a head that did
        not build: reverted on a green and on a flaky verdict, ``red`` staying the tests'."""
        for runs, verdict in (([GREEN_RUN], "green"), (self.FLAKY, "flaky")):
            for facts, cause in ((dict(FACTS, lint=self.RISING), "lint_regression"),
                                 (dict(FACTS, lint=self.PER_TOOL), "lint_regression"),
                                 (dict(FACTS, build_ok=False), "build_break"),
                                 (dict(FACTS, build_ok=False, lint=None), "build_break"),
                                 (dict(FACTS, build_ok=False, lint=self.RISING), "build_break")):
                with self.subTest(verdict=verdict, facts=facts):
                    self.assertEqual(R.assess(runs, facts),
                                     {"revert": True, "verdict": verdict, "red": [], "cause": cause})

    def test_no_red_test_and_no_stated_cause_is_no_red(self):
        """``unknown`` with no red test reverts nothing: equal or falling totals, unread totals, an unread build
        (whatever the lint)."""
        falling = {"eslint": {"before": 3, "after": 2}}
        for runs, verdict in (([GREEN_RUN], "green"), (self.FLAKY, "flaky")):
            for facts in (FACTS, dict(FACTS, lint=falling), dict(FACTS, lint={}), dict(FACTS, lint=None),
                          dict(FACTS, build_ok=None), dict(FACTS, build_ok=None, lint=self.RISING),
                          dict(FACTS, build_ok=None, lint=None)):
                with self.subTest(verdict=verdict, facts=facts):
                    self.assertEqual(R.assess(runs, facts),
                                     {"revert": False, "verdict": verdict, "red": [], "cause": None})

    def test_a_rerun_reverts_nothing_and_reads_no_facts(self):
        for runs in ([], [RED_A], [RED_A] * 3):
            for facts in (None, dict(FACTS, build_ok=False), dict(FACTS, lint=self.RISING), {"x": 1}):
                with self.subTest(runs=len(runs), facts=facts):
                    self.assertEqual(R.assess(runs, facts),
                                     {"revert": False, "verdict": "rerun", "red": [], "cause": None})

    def test_a_green_or_flaky_verdict_needs_its_facts(self):
        """No verdict of the tests ends without the facts read: missing or malformed facts are unusable."""
        for runs in ([GREEN_RUN], self.FLAKY):
            for facts in (None, {}, {"impact": ["a"]}, dict(FACTS, build_ok="no"), dict(FACTS, lint={"x": {}}),
                          dict(FACTS, red_tests=[]), dict(FACTS, lint=None, impact=[""]),
                          dict(FACTS, build_ok=None, lint={"x": {}})):
                with self.subTest(runs=len(runs), facts=facts), self.assertRaises(R.Unusable):
                    R.assess(runs, facts)

    def test_unreadable_lint_is_unknown_unless_the_build_broke(self):
        rising = dict(FACTS, lint={"eslint": {"before": 0, "after": 9}})
        self.assertEqual(R.assess([RED_A] * 4, rising)["cause"], "lint_regression")
        # without the totals neither lint_regression nor a later rule can be stated: unknown, not test_regression
        self.assertEqual(R.cause(dict(FACTS, red_tests=["a"], lint={})), "test_regression")
        self.assertEqual(R.assess([RED_A] * 4, dict(FACTS, lint=None))["cause"], "unknown")
        self.assertEqual(R.assess([RED_A] * 4, dict(FACTS, lint=None, build_ok=False))["cause"], "build_break")

    def test_an_unknown_build_is_unknown_whatever_the_lint(self):
        rising = {"eslint": {"before": 0, "after": 9}}
        for lint in (FACTS["lint"], rising, None):
            with self.subTest(lint=lint):
                self.assertEqual(R.assess([RED_A] * 4, dict(FACTS, build_ok=None, lint=lint))["cause"], "unknown")
        self.assertEqual(R.assess([GREEN_RUN], dict(FACTS, build_ok=None))["cause"], None)  # not red: no cause

    def test_an_unknown_build_keeps_the_other_shapes(self):
        for facts in (dict(FACTS, build_ok=None, impact=[""]), dict(FACTS, build_ok=None, lint={"x": {}}),
                      {"impact": ["a"], "build_ok": None}, {"impact": ["a"], "build_ok": None, "lint": None, "x": 1}):
            with self.subTest(facts=facts), self.assertRaises(R.Unusable):
                R.assess([RED_A] * 4, facts)

    def test_unreadable_lint_keeps_the_other_shapes(self):
        for facts in (dict(FACTS, lint=None, build_ok="no"), dict(FACTS, lint=None, impact=[""]),
                      {"impact": ["a"], "lint": None}):
            with self.subTest(facts=facts), self.assertRaises(R.Unusable):
                R.assess([RED_A] * 4, facts)

    def test_the_command_line_takes_no_null_lint(self):
        code, out, _ = cli(json.dumps(dict(req(red=["a"], impact=["a"]), lint=None)).encode(), "cause")
        self.assertEqual((code, out), (2, {"cause": None}))
        code, out, _ = cli(json.dumps(dict(req(red=["a"], impact=["a"]), build_ok=None)).encode(), "cause")
        self.assertEqual((code, out), (2, {"cause": None}))


class CommandLine(unittest.TestCase):
    def test_cause(self):
        code, out, err = cli(json.dumps(req(red=["a"], impact=["b"])).encode(), "cause")
        self.assertEqual((code, out, err), (0, {"cause": "impact_miss"}, ""))

    def test_each_cause(self):
        cases = {"build_break": req(build_ok=False), "lint_regression": req(lint={"x": {"before": 0, "after": 1}}),
                 "test_regression": req(red=["a"], impact=["a"]), "unknown": req()}
        for want, request in cases.items():
            self.assertEqual(cli(json.dumps(request).encode(), "cause")[:2], (0, {"cause": want}))

    def test_unusable(self):
        for stdin, argv in ((b"{", ["cause"]), (b"[]", ["cause"]), (b'{"red_tests": []}', ["cause"]),
                            (b"\xff", ["cause"]), (json.dumps(req()).encode(), []),
                            (json.dumps(req()).encode(), ["decide"]),
                            (b'{"red_tests": [], "red_tests": [], "impact": [], "build_ok": true, "lint": {}}',
                             ["cause"]),
                            (b'{"red_tests": [], "impact": [], "build_ok": true, "lint": {"x": {"before": NaN, '
                             b'"after": 1}}}', ["cause"])):
            code, out, err = cli(stdin, *argv)
            self.assertEqual((code, out), (2, {"cause": None}), stdin)
            self.assertTrue(err.startswith("unusable input: "), err)


if __name__ == "__main__":
    unittest.main()
