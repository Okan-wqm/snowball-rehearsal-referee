"""``tests/mutate.py``, the kept-mutant runner (a session tool, run with test 42's session tools): each outcome
on a small brain made here, the brain left unchanged, and every kept mutant still applicable to today's code."""

from __future__ import annotations

import ast
import contextlib
import glob
import io
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import git_store  # noqa: E402
import mutate  # noqa: E402
from profile_tree import write_tree  # noqa: E402

MOD = "def add(a, b):\n    return a + b\n\n\ndef twice(a):\n    return a + a\n"
TEST = ("import os, sys, unittest\nsys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))\n"
        "import mod\n\n\nclass T(unittest.TestCase):\n    def test_add(self):\n"
        "        self.assertEqual(mod.add(2, 3), 5)\n")
RED = "import unittest\n\n\nclass T(unittest.TestCase):\n    def test_red(self):\n        self.fail()\n"
SLOW = "import time, unittest\n\n\nclass T(unittest.TestCase):\n    def test_slow(self):\n        time.sleep(30)\n"
# Two classes, so an id can name one: T tests add (and that its run sees tests/helper.py before referee/helper.py
# and runs in referee/, as discover does); U does not test add.
IDS = ("import helper\n" + TEST
       + "        self.assertEqual(helper.VALUE, 5)\n        self.assertTrue(os.path.isdir('tests'))\n\n"
       "    def test_other(self):\n        pass\n\n\nclass U(unittest.TestCase):\n    def test_nothing(self):\n"
       "        pass\n")


# How long a held mutant waits for the event that frees it before it goes on by itself. The event comes however slow
# the machine is, so the wait ends by the clock only in a run that has one worker where the test asked for two (the
# event cannot come), and the test then fails by its events, this many seconds late.
HELD = 600.0


def mutant(id_: str, old: str, new: str, tests: list[str] | None = None, file: str = "mod.py") -> dict:
    return {"id": id_, "file": file, "old": old, "new": new, "tests": tests or ["test_mod.py"]}


def fp_of(brain: str, m: dict) -> str:
    """Today's fingerprint of the mutant ``m`` (``root`` ``referee`` when it has none) in ``brain``."""
    m = {"root": "referee"} | m
    return mutate.fingerprint(brain, m, mutate.reach(brain, {m["root"]}, set())(m)[1])


def plan(selected: int, tiers: list[int], lists: int, changed: int | None = None, reused: int = 0) -> dict:
    return {"plan": {"changed": changed, "selected": selected, "reused": reused, "to_run": selected - reused,
                     "tiers": tiers, "lists": lists}}


class Runner(unittest.TestCase):
    def setUp(self):
        self.brain = tempfile.mkdtemp(prefix="t-mutate-")
        self.addCleanup(shutil.rmtree, self.brain, ignore_errors=True)
        write_tree(self.brain, {"referee/mod.py": MOD, "referee/tests/test_mod.py": TEST,
                                "referee/tests/test_red.py": RED, "referee/tests/test_slow.py": SLOW})

    def outcomes(self, mutants: list[dict], timeout: float = 120.0, emit=None, roots: dict | None = None,
                 jobs: int = 4, **limits) -> dict[str, str]:
        """Outcomes of ``mutants`` written to one file, and of each ``roots`` file (``{root: mutants}``) beside it."""
        paths = []
        for i, (root, ms) in enumerate([(None, mutants)] + sorted((roots or {}).items())):
            paths.append(os.path.join(self.brain, "m%d.json" % i if i else "m.json"))
            with open(paths[-1], "w") as fh:
                json.dump({"mutants": ms} | ({"root": root} if root else {}), fh)
        return {r["id"]: r["outcome"] for r in mutate.run(self.brain, paths, jobs, timeout, emit=emit, **limits)}

    def test_a_root_mutant_runs_on_its_roots_file_with_its_roots_tests_from_its_root(self):
        # The brain's root has its own mod.py (twice differs from referee's) and tests/: test_root checks twice
        # and that it runs from the root (referee/ is below it), and the root's test_mod.py is red, so a referee
        # mutant and a root mutant with the same tests list have different baselines.
        root_test = ("import os, sys, unittest\nsys.path.insert(0, os.path.dirname(os.path.dirname("
                     "os.path.abspath(__file__))))\nimport mod\n\n\nclass T(unittest.TestCase):\n"
                     "    def test_twice(self):\n        self.assertEqual(mod.twice(3), 6)\n"
                     "        self.assertTrue(os.path.isdir('referee'))\n")
        write_tree(self.brain, {"mod.py": MOD.replace("return a + a", "return a * 2"), "tests/test_root.py": root_test,
                                "tests/test_mod.py": RED})
        got = self.outcomes([mutant("referee_side", "return a + b", "return a - b")], roots={".": [
            mutant("root_file", "return a * 2", "return a * 3", ["test_root.py"]),
            mutant("root_id", "return a * 2", "return a * 4", ["test_root.T.test_twice"]),
            mutant("root_untested", "return a + b", "return a - b", ["test_root.py"]),
            mutant("root_red_baseline", "return a + b", "return a - b", ["test_mod.py"]),
            mutant("not_in_root", "return a + a", "return 2 * a", ["test_root.py"])]})
        self.assertEqual(got, {"referee_side": "killed", "root_file": "killed", "root_id": "killed",
                               "root_untested": "survived", "root_red_baseline": "baseline_red",
                               "not_in_root": "stale"})
        with open(os.path.join(self.brain, "mod.py")) as fh:
            self.assertEqual(fh.read(), MOD.replace("return a + a", "return a * 2"))

    def test_an_id_runs_only_the_tests_it_names_as_discover_would(self):
        write_tree(self.brain, {"referee/tests/test_ids.py": IDS, "referee/tests/helper.py": "VALUE = 5\n",
                                "referee/helper.py": "VALUE = 6\n"})
        got = self.outcomes([
            mutant("class_testing_add", "return a + b", "return a - b", ["test_ids.T"]),
            mutant("method_testing_add", "return a + b", "return a * b", ["test_ids.T.test_add"]),
            mutant("class_not_testing_add", "return a + b", "return a - 1", ["test_ids.U"]),
            mutant("method_not_testing_add", "return a + b", "return b - a", ["test_ids.T.test_other"]),
            mutant("unknown_name", "return a + b", "return 0", ["test_ids.Nope"]),
            mutant("no_such_module", "return a + b", "return 1", ["test_none.T"]),
            mutant("id_then_red_file", "return a + b", "return 2", ["test_ids.U", "test_red.py"]),
        ])
        self.assertEqual(got, {"class_testing_add": "killed", "method_testing_add": "killed",
                               "class_not_testing_add": "survived", "method_not_testing_add": "survived",
                               "unknown_name": "baseline_red", "no_such_module": "baseline_red",
                               "id_then_red_file": "baseline_red"})

    def test_each_row_is_emitted_as_its_mutant_finishes(self):
        # Two workers; the file's first mutant is held until the third starts, and the third starts only when the
        # worker that ran the second is free again: the second's row must be out by then, and first in the output.
        # Events hold the order, no pause does (``HELD``).
        emitted, release, real = [], threading.Event(), mutate.run_one
        out_at_third: list[str] = []

        def held(brain, m, limit):
            if m["id"] == "held_first":
                release.wait(HELD)
            elif m["id"] == "third":
                out_at_third.extend(r["id"] for r in emitted if "id" in r)
                release.set()
            return real(brain, m, limit)

        second = mutant("second", "return a + a", "return 2 * a")
        with mock.patch.object(mutate, "run_one", held):
            got = self.outcomes([mutant("held_first", "return a + b", "return a - b"), second,
                                 mutant("third", "return a + b", "return a * b")], emit=emitted.append, jobs=2)
        self.assertEqual(got, {"held_first": "killed", "second": "survived", "third": "killed"})
        self.assertEqual(emitted[0], plan(3, [0, 0, 3], 1))  # the plan comes before every row
        self.assertEqual(out_at_third, ["second"])
        self.assertEqual(emitted[1], {"file": "m.json", "id": "second", "outcome": "survived",
                                      "fp": fp_of(self.brain, second)})
        self.assertEqual(sorted(r["id"] for r in emitted[2:]), ["held_first", "third"])

    def test_each_outcome(self):
        got = self.outcomes([
            mutant("killed", "return a + b", "return a - b"),
            mutant("survived", "return a + a", "return 2 * a"),  # twice is not tested
            mutant("stale", "return a * b", "return a"),
            mutant("ambiguous", "return a + ", "return 1 + "),
            mutant("missing_file", "x", "y", file="nope.py"),
            mutant("baseline_red", "return a + b", "return a - b", ["test_mod.py", "test_red.py"]),
        ])
        self.assertEqual(got, {"killed": "killed", "survived": "survived", "stale": "stale",
                               "ambiguous": "ambiguous", "missing_file": "stale", "baseline_red": "baseline_red"})

    def test_a_baseline_over_the_limit_is_baseline_red(self):
        got = self.outcomes([mutant("slow", "return a + b", "return a - b", ["test_slow.py"])], timeout=2.0)
        self.assertEqual(got, {"slow": "baseline_red"})

    def test_the_mutant_runs_in_a_copy(self):
        self.outcomes([mutant("killed", "return a + b", "return a - b")])
        with open(os.path.join(self.brain, "referee", "mod.py")) as fh:
            self.assertEqual(fh.read(), MOD)

    def test_exit_is_zero_only_when_every_mutant_is_killed(self):
        path = os.path.join(self.brain, "m.json")
        for mutants, code in (([mutant("k", "return a + b", "return a - b")], 0),
                              ([mutant("k", "return a + b", "return a - b"),
                                mutant("s", "return a + a", "return 2 * a")], 1)):
            with self.subTest(mutants=[m["id"] for m in mutants]):
                with open(path, "w") as fh:
                    json.dump({"mutants": mutants}, fh)
                out = io.StringIO()
                with contextlib.redirect_stdout(out):
                    self.assertEqual(mutate.main(["--brain", self.brain, "-j", "2", path]), code)
                first, *rows, total = [json.loads(line) for line in out.getvalue().splitlines()]
                self.assertEqual(first, plan(len(mutants), [0, 0, len(mutants)], 1))
                self.assertEqual(sorted((r["file"], r["id"]) for r in rows), sorted(("m.json", m["id"]) for m in mutants))
                self.assertEqual(total, mutate.summary([path], rows))
                self.assertEqual(total["ok"], code == 0)

    def test_the_summary_line_counts_the_run_and_comes_last(self):
        path = os.path.join(self.brain, "m.json")
        other = os.path.join(self.brain, "m1.json")
        with open(path, "w") as fh:
            json.dump({"mutants": [mutant("k", "return a + b", "return a - b"),
                                   mutant("s", "return a + a", "return 2 * a")]}, fh)
        with open(other, "w") as fh:
            json.dump({"mutants": [mutant("st", "return a * b", "return a")]}, fh)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(mutate.main(["--brain", self.brain, "-j", "2", path, other]), 1)
        lines = [json.loads(line) for line in out.getvalue().splitlines()]
        self.assertEqual(len(lines), 5)
        self.assertEqual(lines[0], plan(3, [0, 0, 3], 1))  # the stale mutant's list is not one to run
        self.assertTrue(all("id" in r for r in lines[1:4]))
        self.assertEqual(lines[-1], {"ok": False, "files": 2, "mutants": 3, "reused": 0,
                                     "outcomes": {"killed": 1, "survived": 1, "stale": 1}})
        self.assertEqual({r["id"]: r["fp"] for r in lines[1:4]}["st"], "")  # no fingerprint: it cannot be applied

    def test_summary(self):
        row = lambda outcome: {"file": "m.json", "id": outcome, "outcome": outcome}  # noqa: E731
        for rows, ok in (([], False), ([row("killed")], True), ([row("killed"), row("killed")], True),
                         ([row("killed"), row("timeout")], False), ([row("stale")], False),
                         ([row("baseline_red")], False)):
            with self.subTest(rows=[r["outcome"] for r in rows]):
                got = mutate.summary(["a.json", "b.json"], rows)
                self.assertEqual(got["ok"], ok)
                self.assertEqual((got["files"], got["mutants"]), (2, len(rows)))
                self.assertEqual(sum(got["outcomes"].values()), len(rows))
        self.assertEqual(mutate.summary([], [row("killed"), row("timeout"), row("killed")])["outcomes"],
                         {"killed": 2, "timeout": 1})
        self.assertEqual(mutate.summary([], [row("killed") | {"reused": True}, row("killed")])["reused"], 1)

    def test_a_cut_run_prints_no_summary(self):
        path = os.path.join(self.brain, "m.json")
        with open(path, "w") as fh:
            json.dump({"mutants": [mutant("k", "return a + b", "return a - b"),
                                   mutant("s", "return a + a", "return 2 * a")]}, fh)
        real = mutate.run_one

        def cut(brain, m, limit):  # the run is cut while its second mutant runs
            if m["id"] == "s":
                raise KeyboardInterrupt
            return real(brain, m, limit)

        out = io.StringIO()
        with mock.patch.object(mutate, "run_one", cut), contextlib.redirect_stdout(out):
            with self.assertRaises(KeyboardInterrupt):
                mutate.main(["--brain", self.brain, "-j", "1", path])
        lines = [json.loads(line) for line in out.getvalue().splitlines()]
        self.assertEqual(lines, [plan(2, [0, 0, 2], 1), {"file": "m.json", "id": "k", "outcome": "killed",
                                                         "fp": fp_of(self.brain, mutant("k", "return a + b",
                                                                                        "return a - b"))}])

    def test_a_mutant_over_the_limit_is_a_timeout(self):
        # The baseline's seconds are set (0.1 s, so the limit is the 2 s floor); the mutant's entry sleeps 30 s. A
        # slow machine only makes the entry later still.
        slow = "import mod, time\nif mod.add(2, 3) != 5:\n    time.sleep(30)\n"
        write_tree(self.brain, {"referee/tests/test_hang.py": TEST.replace("import mod\n", "import mod\n" + slow)})
        with mock.patch.object(mutate, "baseline", lambda *a: ("green", [0.1])):
            got = self.outcomes([mutant("hang", "return a + b", "return a - b", ["test_hang.py"])], floor=2.0)
        self.assertEqual(got, {"hang": "timeout"})

    def handed_on(self, seconds: list[float], call) -> list[list[float]]:
        """The limits ``run_one`` is given in ``call()``, the baseline of every list set to ``seconds``; nothing
        is run, so no clock is read."""
        limits: list[list[float]] = []

        def run_one(brain, m, limit):
            limits.append(limit)
            return "killed"

        with mock.patch.object(mutate, "baseline", lambda *a: ("green", seconds)), \
                mock.patch.object(mutate, "run_one", run_one):
            call()
        return limits

    def test_a_mutant_limit_is_derived_from_its_baseline(self):
        # Three entries whose baselines took 0.1 s, 4 s and 50 s: the floor, five baselines, the ceiling.
        m = mutant("m", "return a + b", "return a - b", ["test_mod.py", "test_mod.T", "test_mod.T.test_add"])
        got = self.handed_on([0.1, 4.0, 50.0], lambda: self.outcomes([m], timeout=120.0, factor=5.0, floor=2.0))
        self.assertEqual(got, [[2.0, 20.0, 120.0]])

    def test_each_entry_is_timed_on_its_own(self):
        # The entries really run; the clock is a list read in turn (how long a process takes to start is the
        # machine's load, not the rule): the first entry starts at 0 and ends at 7, the second runs from 10 to 12.
        ticks = iter([0.0, 7.0, 10.0, 12.0])
        with mock.patch.object(mutate.time, "monotonic", lambda: next(ticks)):
            verdict, seconds = mutate.baseline(self.brain, "referee", ["test_mod.py", "test_mod.py"], 120.0)
        self.assertEqual((verdict, seconds), ("green", [7.0, 2.0]))
        self.assertEqual(list(ticks), [])

    def test_the_command_line_passes_its_limits(self):
        path = os.path.join(self.brain, "m.json")
        with open(path, "w") as fh:
            json.dump({"mutants": [mutant("m", "return a + b", "return a - b",
                                          ["test_mod.py", "test_mod.T", "test_mod.T.test_add"])]}, fh)

        def main(*flags):
            with contextlib.redirect_stdout(io.StringIO()):
                mutate.main(["--brain", self.brain, *flags, path])

        # Baselines of 2 s, 20 s and 500 s: each flag's value shows in one entry's limit, and so does its default.
        self.assertEqual(self.handed_on([2.0, 20.0, 500.0], main), [[60.0, 100.0, 900.0]])
        self.assertEqual(self.handed_on([2.0, 20.0, 500.0],
                                        lambda: main("--timeout", "120", "--factor", "4", "--floor", "3")),
                         [[8.0, 80.0, 120.0]])

    def test_limits(self):
        self.assertEqual(mutate.limits([0.1, 4.0, 50.0], 120.0, 5.0, 2.0), [2.0, 20.0, 120.0])
        self.assertEqual(mutate.limits([1.0], 120.0, 3.0, 0.0), [3.0])
        self.assertEqual(mutate.limits([], 120.0, 5.0, 60.0), [])

    def test_bad_limits_are_refused(self):
        for flag in (["--factor", "0"], ["--timeout", "-1"], ["--floor", "-1"]):
            with self.subTest(flag=flag), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as raised:
                    mutate.main(["--brain", self.brain, *flag])
                self.assertEqual(raised.exception.code, 2)

    def test_malformed_files(self):
        good = mutant("k", "return a + b", "return a - b")
        for label, data in (("no list", {}), ("empty", {"mutants": []}), ("extra field", {"mutants": [good | {"x": 1}]}),
                            ("no change", {"mutants": [good | {"new": good["old"]}]}),
                            ("no tests", {"mutants": [good | {"tests": []}]}),
                            ("a bare module", {"mutants": [good | {"tests": ["test_mod"]}]}),
                            ("an id too deep", {"mutants": [good | {"tests": ["test_mod.T.test_add.x"]}]}),
                            ("an id not dotted names", {"mutants": [good | {"tests": ["test_mod.T-1"]}]}),
                            ("an id with a path", {"mutants": [good | {"tests": ["../test_mod.T"]}]}),
                            ("an empty entry", {"mutants": [good | {"tests": [""]}]}),
                            ("duplicate id", {"mutants": [good, good]}),
                            ("a root not in ROOTS", {"root": "referee/tests", "mutants": [good]}),
                            ("a root not a string", {"root": ["."], "mutants": [good]}),
                            ("an empty root", {"root": "", "mutants": [good]}),
                            ("an unknown file field", {"mutants": [good], "roots": "."})):
            with self.subTest(label=label):
                path = os.path.join(self.brain, "bad.json")
                with open(path, "w") as fh:
                    json.dump(data, fh)
                with self.assertRaises(ValueError):
                    mutate.load(path)

    def test_well_formed_entries(self):
        path = os.path.join(self.brain, "good.json")
        tests = ["test_mod.py", "test_*.py", "test_mod.T", "test_mod.T.test_add"]
        with open(path, "w") as fh:
            json.dump({"mutants": [mutant("k", "return a + b", "return a - b", tests)]}, fh)
        self.assertEqual(mutate.load(path)[0]["tests"], tests)

    def test_a_files_root_is_given_to_each_of_its_mutants(self):
        path = os.path.join(self.brain, "good.json")
        for data, root in (({}, "referee"), ({"root": "referee"}, "referee"), ({"root": "."}, ".")):
            with self.subTest(data=data):
                with open(path, "w") as fh:
                    json.dump(data | {"mutants": [mutant("k", "a", "b"), mutant("l", "a", "c")]}, fh)
                self.assertEqual([m["root"] for m in mutate.load(path)], [root, root])


# Discovery's world: each test file kills a mutant of add (or not) in one way the collector tells apart.
SLOW_KILL = ("import time\n" + TEST.replace("    def test_add(self):\n",
                                           "    def test_add(self):\n        time.sleep(1.5)\n"))
SUBTESTS = TEST.replace("        self.assertEqual(mod.add(2, 3), 5)\n",
                        "        for b in (3, 4):\n            with self.subTest(b=b):\n"
                        "                self.assertEqual(mod.add(2, b), 2 + b)\n")
EXPECTED = TEST.replace("    def test_add(self):\n",
                        "    @unittest.expectedFailure\n    def test_add(self):\n"
                        "        assert mod.add(2, 4) == 7\n\n"
                        "    def test_sum(self):\n")
FIXTURE = TEST.replace("class T(unittest.TestCase):\n",
                       "class T(unittest.TestCase):\n    @classmethod\n    def setUpClass(cls):\n"
                       "        assert mod.add(2, 3) == 5\n\n").replace("mod.add(2, 3), 5", "1, 1")
TEARDOWN = FIXTURE.replace("setUpClass", "tearDownClass")  # its test runs and passes, then the fixture fails


class Discover(unittest.TestCase):
    """``--discover``: which tests kill each candidate, and the kept file written from them."""

    def setUp(self):
        self.brain = tempfile.mkdtemp(prefix="t-mutate-")
        self.addCleanup(shutil.rmtree, self.brain, ignore_errors=True)
        write_tree(self.brain, {"referee/mod.py": MOD, "referee/tests/test_mod.py": TEST,
                                "referee/tests/test_ids.py": IDS, "referee/tests/helper.py": "VALUE = 5\n",
                                "referee/tests/test_slowkill.py": SLOW_KILL, "referee/tests/test_red.py": RED,
                                "referee/tests/test_sub.py": SUBTESTS, "referee/tests/test_expected.py": EXPECTED,
                                "referee/tests/test_fixture.py": FIXTURE,
                                "referee/tests/test_teardown.py": TEARDOWN, "referee/tests/deep/__init__.py": "",
                                "referee/tests/deep/test_deep.py": TEST})
        self.out = os.path.join(self.brain, "kept.json")

    def discover(self, mutants: list[dict], root: str | None = None, jobs: int = 4, **kw) -> dict[str, dict]:
        path = os.path.join(self.brain, "c.json")
        with open(path, "w") as fh:
            json.dump({"mutants": mutants} | ({"root": root} if root else {}), fh)
        rows = mutate.discover(self.brain, path, self.out, jobs, kw.pop("timeout", 120.0), **kw)
        self.assertEqual([r["id"] for r in rows], [m["id"] for m in mutants])  # candidate order
        return {r["id"]: r for r in rows}

    def kept(self) -> dict:
        with open(self.out) as fh:
            return json.load(fh)

    def test_the_killers_are_the_failed_tests_of_every_entry_and_the_fastest_is_kept(self):
        tests = ["test_slowkill.py", "test_ids.py", "test_mod.T", "test_mod.py"]  # a test found twice is one killer
        got = self.discover([mutant("k", "return a + b", "return a - b", tests)])["k"]
        self.assertEqual((got["outcome"], got["killers"], got["timeouts"]),
                         ("killed", ["test_slowkill.T.test_add", "test_ids.T.test_add", "test_mod.T.test_add"], []))
        self.assertIn(got["tests"], (["test_ids.T.test_add"], ["test_mod.T.test_add"]))  # not the slow one
        self.assertEqual(self.kept(), {"mutants": [mutant("k", "return a + b", "return a - b", got["tests"])]})

    def test_keep_takes_that_many_by_baseline_seconds(self):
        got = self.discover([mutant("k", "return a + b", "return a - b", ["test_slowkill.py", "test_mod.py"])],
                            keep=2)["k"]
        self.assertEqual(got["tests"], ["test_mod.T.test_add", "test_slowkill.T.test_add"])
        self.assertEqual(self.kept()["mutants"][0]["tests"], got["tests"])

    def test_choose(self):
        seconds = {"b": 1.0, "a": 1.0, "c": 0.5}
        self.assertEqual(mutate.choose(["x", "b", "a", "c"], seconds, 3), ["c", "a", "b"])
        self.assertEqual(mutate.choose(["x", "b"], seconds, 2), ["b", "x"])  # no baseline time: last
        self.assertEqual(mutate.choose(["x", "b", "a"], seconds, 1), ["a"])

    def test_a_failure_not_a_tests_own_makes_the_entry_its_own_killer(self):
        broken = "return a +"  # mod no longer imports
        write_tree(self.brain, {  # the tests pass; the process then exits 3, or it exits 0 before the record
            "referee/tests/test_atexit.py": TEST.replace("import mod\n", "import mod, atexit\natexit.register("
                                                         "lambda: mod.add(1, 2) != 3 and os._exit(3))\n"),
            "referee/tests/test_exit0.py": TEST.replace("        self.assertEqual(mod.add(2, 3), 5)\n",
                                                        "        if mod.add(2, 3) != 5:\n            os._exit(0)\n")})
        got = self.discover([
            mutant("import_by_pattern", "return a + b", broken, ["test_mod.py"]),
            mutant("import_by_id", "return a + b", broken, ["test_ids.T.test_add"]),
            mutant("class_fixture", "return a + b", "return a - b", ["test_fixture.py"]),
            mutant("class_fixture_after_its_tests", "return a + b", "return a - b", ["test_teardown.py"]),
            mutant("id_not_an_entry", "return a + b", "return a - b", ["test_deep.py"]),
            mutant("no_test_run", "return a + b", "return a - b", ["test_ids.U", "test_none*.py"]),
            mutant("exit_after_record", "return a + b", "return a + b if a > 1 else 0", ["test_atexit.py"]),
            mutant("exit_zero_without_record", "return a + b", "return a * b", ["test_exit0.py"]),
        ])
        self.assertEqual({k: (r["outcome"], r["killers"]) for k, r in got.items()},
                         {"import_by_pattern": ("killed", ["test_mod.py"]),
                          "import_by_id": ("killed", ["test_ids.T.test_add"]),
                          "class_fixture": ("killed", ["test_fixture.py"]),
                          "class_fixture_after_its_tests": ("killed", ["test_teardown.py"]),
                          "id_not_an_entry": ("killed", ["test_deep.py"]),
                          "no_test_run": ("baseline_red", []),
                          "exit_after_record": ("killed", ["test_atexit.py"]),
                          "exit_zero_without_record": ("killed", ["test_exit0.py"])})

    def test_a_subtest_failure_is_its_tests_and_an_unexpected_success_is_a_failure(self):
        got = self.discover([mutant("sub", "return a + b", "return a + b if b == 3 else 0", ["test_sub.py"]),
                             mutant("unexpected", "return a + b", "return a + b + (b == 4)", ["test_expected.py"])])
        self.assertEqual((got["sub"]["killers"], got["unexpected"]["killers"]),
                         (["test_sub.T.test_add"], ["test_expected.T.test_add"]))

    def test_survivors_and_unrun_candidates_are_reported_not_kept(self):
        got = self.discover([
            mutant("survived", "return a + a", "return 2 * a", ["test_mod.py", "test_ids.py"]),
            mutant("stale", "return a * b", "return a"),
            mutant("ambiguous", "return a + ", "return 1 + "),
            mutant("baseline_red", "return a + b", "return a - b", ["test_mod.py", "test_red.py"]),
            mutant("killed", "return a + b", "return a - b"),
        ])
        self.assertEqual({k: (r["outcome"], r["killers"], r["tests"]) for k, r in got.items()},
                         {"survived": ("survived", [], []), "stale": ("stale", [], []),
                          "ambiguous": ("ambiguous", [], []), "baseline_red": ("baseline_red", [], []),
                          "killed": ("killed", ["test_mod.T.test_add"], ["test_mod.T.test_add"])})
        self.assertEqual([m["id"] for m in self.kept()["mutants"]], ["killed"])

    def test_a_baseline_over_the_limit_is_baseline_red(self):
        write_tree(self.brain, {"referee/tests/test_slow.py": SLOW})
        got = self.discover([mutant("slow", "return a + b", "return a - b", ["test_mod.py", "test_slow.py"])],
                            timeout=2.0)
        self.assertEqual(got["slow"]["outcome"], "baseline_red")

    def test_an_existing_kept_file_is_not_overwritten(self):
        with open(self.out, "w") as fh:
            fh.write("keep me")
        with self.assertRaises(FileExistsError):
            self.discover([mutant("k", "return a + b", "return a - b")])
        with open(self.out) as fh:
            self.assertEqual(fh.read(), "keep me")

    def test_nothing_killed_writes_nothing(self):
        self.discover([mutant("survived", "return a + a", "return 2 * a")])
        self.assertFalse(os.path.exists(self.out))

    def test_an_entry_over_its_limit_is_a_timeout_and_the_others_still_run(self):
        # Every run's seconds are set: test_hang.py's 0.5 s (its limit five of them, 2.5 s, which the mutant's 30 s
        # sleep passes on any machine), test_mod.py's 30 s (its limit 150 s, which nothing here comes near).
        hang = "import mod, time\nif mod.add(2, 3) != 5:\n    time.sleep(30)\n"
        write_tree(self.brain, {"referee/tests/test_hang.py": TEST.replace("import mod\n", "import mod\n" + hang)})
        took = {"test_hang.py": 0.5, "test_mod.py": 30.0}
        caps, real = [], mutate._collect

        def collect(copy, root, entry, limit):
            caps.append((entry, limit))
            return real(copy, root, entry, limit)[0], took[entry]

        with mock.patch.object(mutate, "_collect", collect):
            got = self.discover([mutant("hang_then_kill", "return a + b", "return a - b",
                                        ["test_hang.py", "test_mod.py"]),
                                 mutant("hang_only", "return a + b", "return a * b", ["test_hang.py"])],
                                timeout=200.0, floor=2.0)
        self.assertEqual({k: (r["outcome"], r["killers"], r["timeouts"]) for k, r in got.items()},
                         {"hang_then_kill": ("killed", ["test_mod.T.test_add"], ["test_hang.py"]),
                          "hang_only": ("timeout", [], ["test_hang.py"])})
        # two baselines under the ceiling (three entries), then each candidate's entries under their own limits
        self.assertEqual(sorted(caps), [("test_hang.py", 2.5), ("test_hang.py", 2.5), ("test_hang.py", 200.0),
                                        ("test_hang.py", 200.0), ("test_mod.py", 150.0), ("test_mod.py", 200.0)])

    def test_the_kept_file_keeps_its_root_and_is_killed_in_the_normal_mode(self):
        write_tree(self.brain, {"tests/test_root.py": TEST.replace("import mod\n",
                                                                   "sys.path.insert(0, 'referee')\nimport mod\n")})
        m = mutant("k", "return a + b", "return a - b", ["test_root.py"], file="referee/mod.py")
        got = self.discover([m], root=".")["k"]
        self.assertEqual(self.kept(), {"root": ".", "mutants": [m | {"tests": ["test_root.T.test_add"]}]})
        self.assertEqual([r["outcome"] for r in mutate.run(self.brain, [self.out], 2, 120.0)], ["killed"])
        self.assertEqual(got["tests"], ["test_root.T.test_add"])
        with open(os.path.join(self.brain, "referee", "mod.py")) as fh:
            self.assertEqual(fh.read(), MOD)  # the brain is only read

    def test_the_command_line(self):
        path = os.path.join(self.brain, "c.json")
        with open(path, "w") as fh:
            json.dump({"mutants": [mutant("k", "return a + b", "return a - b"),
                                   mutant("s", "return a + a", "return 2 * a")]}, fh)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = mutate.main(["--brain", self.brain, "-j", "2", "--discover", "--out", self.out, path])
        *rows, total = [json.loads(line) for line in out.getvalue().splitlines()]
        self.assertEqual((code, total), (1, {"ok": False, "files": 1, "mutants": 2, "reused": 0,
                                             "outcomes": {"killed": 1, "survived": 1}}))
        self.assertEqual(sorted(r["id"] for r in rows), ["k", "s"])
        self.assertEqual([m["id"] for m in self.kept()["mutants"]], ["k"])
        os.unlink(self.out)
        with open(path, "w") as fh:
            json.dump({"mutants": [mutant("k", "return a + b", "return a - b")]}, fh)
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(mutate.main(["--brain", self.brain, "--discover", "--out", self.out, path]), 0)

    def test_the_command_line_passes_its_limits_and_keep(self):
        tests = ["test_mod.py", "test_ids.py", "test_mod.T.test_add"]  # two killers: test_add of each file
        path = os.path.join(self.brain, "c.json")
        with open(path, "w") as fh:
            json.dump({"mutants": [mutant("k", "return a + b", "return a - b", tests)]}, fh)
        took, real = dict(zip(tests, (2.0, 20.0, 500.0), strict=True)), mutate._collect

        def main(*flags):
            caps: list[float] = []

            def collect(copy, root, entry, limit):
                caps.append(limit)
                return real(copy, root, entry, limit)[0], took[entry]

            with mock.patch.object(mutate, "_collect", collect), contextlib.redirect_stdout(io.StringIO()):
                mutate.main(["--brain", self.brain, "--discover", "--out", self.out, *flags, path])
            kept = len(self.kept()["mutants"][0]["tests"])
            os.unlink(self.out)
            return caps, kept

        # The baseline's three entries under the ceiling, then the candidate's under their own limits (set baselines
        # of 2 s, 20 s and 500 s): each flag's value shows in one number, and so does its default.
        self.assertEqual(main(), ([900.0] * 3 + [60.0, 100.0, 900.0], 1))
        self.assertEqual(main("--timeout", "120", "--factor", "4", "--floor", "3", "--keep", "2"),
                         ([120.0] * 3 + [8.0, 80.0, 120.0], 2))

    def test_the_command_line_refuses(self):
        path = os.path.join(self.brain, "c.json")
        with open(path, "w") as fh:
            json.dump({"mutants": [mutant("k", "return a + b", "return a - b")]}, fh)
        with open(os.path.join(self.brain, "there.json"), "w") as fh:
            fh.write("keep me")
        there = os.path.join(self.brain, "there.json")
        for label, argv in (("no --out", ["--discover", path]), ("--out alone", ["--out", self.out, path]),
                            ("two files", ["--discover", "--out", self.out, path, path]),
                            ("no file", ["--discover", "--out", self.out]),
                            ("with --touched", ["--discover", "--out", self.out, "--touched", "HEAD", path]),
                            ("with --record", ["--discover", "--out", self.out, "--record", there, path]),
                            ("with --plan", ["--discover", "--out", self.out, "--plan", path]),
                            ("keep 0", ["--discover", "--out", self.out, "--keep", "0", path]),
                            ("out exists", ["--discover", "--out", there, path])):
            with self.subTest(label=label), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as raised:
                    mutate.main(["--brain", self.brain, *argv])
                self.assertEqual(raised.exception.code, 2)
        self.assertFalse(os.path.exists(self.out))
        with open(there) as fh:
            self.assertEqual(fh.read(), "keep me")

    def test_each_row_is_emitted_as_its_candidate_finishes(self):
        # As Runner's test of the same name: two workers, the first candidate held until the third starts, which
        # needs the worker that ran the second; the second's row is out by then. The rows returned keep the
        # candidates' order (``discover`` above compares it).
        emitted, release, real = [], threading.Event(), mutate._search
        out_at_third: list[str] = []

        def held(brain, root, tests, limit, m=None):
            if m and m["id"] == "held_first":
                release.wait(HELD)
            elif m and m["id"] == "third":
                out_at_third.extend(r["id"] for r in emitted)
                release.set()
            return real(brain, root, tests, limit, m)

        with mock.patch.object(mutate, "_search", held):
            self.discover([mutant("held_first", "return a + b", "return a - b"),
                           mutant("second", "return a + a", "return 2 * a"),
                           mutant("third", "return a + b", "return a * b")], emit=emitted.append, jobs=2)
        self.assertEqual(out_at_third, ["second"])
        self.assertEqual(emitted[0], {"file": "c.json", "id": "second", "outcome": "survived", "killers": [],
                                      "timeouts": [], "tests": []})
        self.assertEqual(sorted(r["id"] for r in emitted[1:]), ["held_first", "third"])


class Select(unittest.TestCase):
    """``--touched``'s rule: which mutants a set of changed paths selects, on a small brain made here."""

    TREE = {
        "referee/pkg/__init__.py": "",
        "referee/pkg/util.py": "def one():\n    return 1\n",
        "referee/mod.py": "from pkg import util\n\n\ndef add(a, b):\n    return a + b + util.one() - 1\n",
        "referee/other.py": "def sub(a, b):\n    return a - b\n",
        "referee/data.json": "{}\n",
        "referee/helper.py": "VALUE = 6\n",
        "referee/tests/helper.py": "VALUE = 5\n",
        "referee/tests/test_mod.py": TEST.replace("import mod\n", "import helper\nimport mod\n"),
        "referee/tests/test_other.py": "import other\n",
        "referee/tests/mutants/a.json": {"mutants": [
            mutant("on_mod", "return a + b", "return a - b"),
            mutant("on_other", "return a - b", "return a + b", ["test_other.py"], "other.py"),
            mutant("on_other_by_glob", "return a - b", "return a * b", ["test_o*.py"], "other.py"),
            mutant("not_imported", "return a - b", "return a", ["test_mod.py"], "other.py")]},  # e.g. a subprocess
        "referee/tests/mutants/b.json": {"mutants": [mutant("b_on_other", "return a - b", "return b",
                                                            ["test_other.py"], "other.py")]},
        # The brain's root tests: tests/helper.py shadows referee/tests/helper.py for them (discover's start
        # directory first); pkg is referee's, which the root tests put on sys.path.
        "tests/tool.py": "def go():\n    return 1\n",
        "tests/helper.py": "VALUE = 7\n",
        "tests/test_tool.py": "import helper\nimport tool\nfrom pkg import util\n",
        "referee/tests/mutants/c.json": {"root": ".", "mutants": [mutant("on_tool", "return 1", "return 2",
                                                                        ["test_tool.py"], "tests/tool.py")]},
    }
    BY_TEST = ["on_mod", "not_imported"]
    ROOT = ["on_tool"]
    ON_OTHER = ["on_other", "on_other_by_glob", "not_imported", "b_on_other"]

    def setUp(self):
        self.brain = tempfile.mkdtemp(prefix="t-select-")
        self.addCleanup(shutil.rmtree, self.brain, ignore_errors=True)
        write_tree(self.brain, self.TREE)

    def selected(self, changed: set[str]) -> list[str]:
        files = sorted(glob.glob(os.path.join(self.brain, "referee", "tests", "mutants", "*.json")))
        items = [(path, m) for path in files for m in mutate.load(path)]
        return [m["id"] for _, m in mutate.select(self.brain, items, changed)]

    def test_nothing_changed_selects_nothing(self):
        self.assertEqual(self.selected(set()), [])

    def test_each_path_a_mutant_is_concerned_by(self):
        for rel, ids in (("referee/mod.py", self.BY_TEST),                 # its file, imported by its test
                         ("referee/other.py", self.ON_OTHER),
                         ("referee/tests/test_mod.py", self.BY_TEST),       # its test file
                         ("referee/tests/helper.py", self.BY_TEST),         # imported by its test; for the root
                                                                            # tests shadowed by tests/helper.py
                         ("referee/pkg/util.py", self.BY_TEST + self.ROOT),  # imported by an imported file
                         ("referee/pkg/__init__.py", self.BY_TEST + self.ROOT),  # the package run first
                         ("referee/tests/mutants/b.json", ["b_on_other"]),  # its mutant file
                         ("referee/tests/mutants/c.json", self.ROOT),
                         ("referee/helper.py", []),                         # shadowed by tests/helper.py
                         ("referee/data.json", []),                         # not Python: stated out of scope
                         ("tests/test_mod.py", []),                         # no root test has that name
                         ("tests/tool.py", self.ROOT),                      # a root mutant's file
                         ("tests/test_tool.py", self.ROOT),                 # its test file
                         ("tests/helper.py", self.ROOT)):                   # imported by its test, from tests/
            with self.subTest(rel=rel):
                self.assertEqual(self.selected({rel}), ids)

    def test_a_module_the_tree_no_longer_has_is_reached_by_its_name(self):
        for old, new in (("referee/tests/helper.py", "referee/tests/helper2.py"),  # its shadow is not taken
                         ("referee/pkg/util.py", "referee/pkg/util2.py")):
            with self.subTest(removed=old):
                write_tree(self.brain, self.TREE)
                os.rename(os.path.join(self.brain, old), os.path.join(self.brain, new))
                self.assertEqual(self.selected({old}), self.BY_TEST + (self.ROOT if "pkg" in old else []))
                self.assertEqual(self.selected({new}), [])
                os.remove(os.path.join(self.brain, new))

    def test_an_id_is_concerned_by_its_modules_file(self):
        items = [("x.json", mutant(id_, "return a - b", new, [test], "other.py") | {"root": "referee"})
                 for id_, new, test in (("by_id", "return a", "test_mod.T"), ("by_other_id", "return b", "test_other.T"))]
        for rel, ids in (("referee/tests/helper.py", ["by_id"]), ("referee/tests/test_mod.py", ["by_id"]),
                         ("referee/pkg/util.py", ["by_id"]), ("referee/other.py", ["by_id", "by_other_id"])):
            with self.subTest(rel=rel):
                self.assertEqual([m["id"] for _, m in mutate.select(self.brain, items, {rel})], ids)

    def test_a_file_that_does_not_parse_is_selected_by_its_own_path(self):
        write_tree(self.brain, {"referee/other.py": "def (\n", "referee/tests/helper.py": "def (\n"})
        self.assertEqual(self.selected({"referee/other.py"}), self.ON_OTHER)
        self.assertEqual(self.selected({"referee/tests/helper.py"}), self.BY_TEST)


class Order(unittest.TestCase):
    """The plan, the tiers and the order the mutants start in, on ``Select``'s brain; nothing is really run
    (``baseline`` and ``run_one`` are stood in for), so only the order and the counts are shown here."""

    CHANGED = {"referee/pkg/util.py", "referee/tests/test_other.py", "referee/tests/mutants/c.json"}
    # c.json is on_tool's own file (0); test_other.py is named by the three (1); util.py is only reached (2).
    ORDER = ["on_tool", "on_other", "on_other_by_glob", "b_on_other", "on_mod", "not_imported"]

    def setUp(self):
        self.brain = tempfile.mkdtemp(prefix="t-order-")
        self.addCleanup(shutil.rmtree, self.brain, ignore_errors=True)
        write_tree(self.brain, Select.TREE)
        self.files = sorted(glob.glob(os.path.join(self.brain, "referee", "tests", "mutants", "*.json")))
        self.events: list[tuple[str, str]] = []
        for name, fake in (("baseline", lambda brain, root, tests, timeout: (
                               self.events.append(("base", root + ":" + ",".join(tests))) or ("green", [0.1]))),
                           ("run_one", lambda brain, m, limit: self.events.append(("run", m["id"])) or "killed")):
            patcher = mock.patch.object(mutate, name, fake)
            patcher.start()
            self.addCleanup(patcher.stop)

    def run_(self, changed: set[str] | None, jobs: int = 1, **kw) -> list[dict]:
        return mutate.run(self.brain, self.files, jobs, 120.0, changed,
                          lambda row: self.events.append(("plan", "") if "plan" in row else ("row", row["id"])), **kw)

    def test_the_nearest_tier_starts_first_and_the_rows_return_in_file_order(self):
        rows = self.run_(self.CHANGED)
        self.assertEqual([i for kind, i in self.events if kind == "run"], self.ORDER)
        self.assertEqual([r["id"] for r in rows], ["on_mod", "on_other", "on_other_by_glob", "not_imported",
                                                   "b_on_other", "on_tool"])

    def test_tier(self):
        items = {m["id"]: (os.path.relpath(path, self.brain), m) for path in self.files for m in mutate.load(path)}
        for changed, tiers in (
                ({"referee/other.py"}, {"on_other": 0, "on_other_by_glob": 0, "not_imported": 0, "b_on_other": 0}),
                ({"referee/tests/mutants/b.json"}, {"b_on_other": 0}),
                ({"referee/tests/test_mod.py"}, {"on_mod": 1, "not_imported": 1}),
                ({"referee/tests/helper.py"}, {"on_mod": 2, "not_imported": 2}),
                ({"referee/tests/helper.py", "referee/mod.py"}, {"on_mod": 0, "not_imported": 2}),  # the nearest
                ({"referee/tests/test_mod.py", "referee/mod.py"}, {"on_mod": 0, "not_imported": 1}),
                ({"referee/data.json"}, {})):
            with self.subTest(changed=sorted(changed)):
                of = mutate.reach(self.brain, {"referee", "."}, changed)
                got = {i: mutate.tier(rel, *of(m), changed) for i, (rel, m) in items.items()}
                self.assertEqual({i: t for i, t in got.items() if t is not None}, tiers)

    def test_the_plan_is_emitted_before_anything_runs(self):
        self.run_(self.CHANGED)
        self.assertEqual(self.events[0], ("plan", ""))
        emitted = []
        mutate.run(self.brain, self.files, 1, 120.0, self.CHANGED, emitted.append)
        self.assertEqual(emitted[0], plan(6, [1, 3, 2], 4, changed=3))

    def test_a_lists_baseline_runs_when_its_first_mutant_is_reached(self):
        self.run_(None)
        self.assertEqual(self.events, [
            ("plan", ""), ("base", "referee:test_mod.py"), ("run", "on_mod"), ("row", "on_mod"),
            ("base", "referee:test_other.py"), ("run", "on_other"), ("row", "on_other"),
            ("base", "referee:test_o*.py"), ("run", "on_other_by_glob"), ("row", "on_other_by_glob"),
            ("run", "not_imported"), ("row", "not_imported"), ("run", "b_on_other"), ("row", "b_on_other"),
            ("base", ".:test_tool.py"), ("run", "on_tool"), ("row", "on_tool")])

    def test_a_list_reached_by_two_threads_at_once_has_one_baseline(self):
        def slow(brain, root, tests, timeout):
            self.events.append(("base", root + ":" + ",".join(tests)))
            time.sleep(0.3)
            return "green", [0.1]

        with mock.patch.object(mutate, "baseline", slow):
            self.run_({"referee/other.py"}, jobs=4)  # on_other and b_on_other have the one list test_other.py
        self.assertEqual(sorted(i for kind, i in self.events if kind == "base"),
                         ["referee:test_mod.py", "referee:test_o*.py", "referee:test_other.py"])

    def test_plan_only_counts_each_file_and_runs_nothing(self):
        emitted = []
        rows = mutate.run(self.brain, self.files, 1, 120.0, self.CHANGED, emitted.append, plan_only=True)
        want = plan(6, [1, 3, 2], 4, changed=3)
        want["plan"]["by_file"] = {"referee/tests/mutants/a.json": [4, 4], "referee/tests/mutants/b.json": [1, 1],
                                   "referee/tests/mutants/c.json": [1, 1]}
        self.assertEqual((rows, emitted, self.events), ([], [want], []))


class Fingerprint(unittest.TestCase):
    """``fp``: what a mutant's fingerprint follows and what it does not, on ``Select``'s brain."""

    ON_MOD = mutant("on_mod", "return a + b", "return a - b")

    def setUp(self):
        self.brain = tempfile.mkdtemp(prefix="t-fp-")
        self.addCleanup(shutil.rmtree, self.brain, ignore_errors=True)
        write_tree(self.brain, Select.TREE)

    def touch(self, rel: str) -> None:
        with open(os.path.join(self.brain, rel), "a") as fh:
            fh.write("\n")

    def test_it_is_the_same_for_the_same_tree_and_mutant(self):
        self.assertEqual(fp_of(self.brain, self.ON_MOD), fp_of(self.brain, dict(self.ON_MOD)))
        self.assertRegex(fp_of(self.brain, self.ON_MOD), r"\A[0-9a-f]{64}\Z")

    def test_it_follows_the_bytes_of_each_file_the_mutant_reaches(self):
        for rel in ("referee/mod.py", "referee/tests/test_mod.py", "referee/tests/helper.py", "referee/pkg/util.py",
                    "referee/pkg/__init__.py"):
            with self.subTest(rel=rel):
                before = fp_of(self.brain, self.ON_MOD)
                self.touch(rel)
                self.assertNotEqual(fp_of(self.brain, self.ON_MOD), before)

    def test_it_does_not_follow_a_file_the_mutant_does_not_reach(self):
        before = fp_of(self.brain, self.ON_MOD)
        for rel in ("referee/other.py", "referee/helper.py", "referee/data.json", "referee/tests/test_other.py",
                    "tests/helper.py", "referee/tests/mutants/a.json"):
            self.touch(rel)
        self.assertEqual(fp_of(self.brain, self.ON_MOD), before)

    def test_its_own_file_is_followed_when_it_is_not_python(self):
        on_data = mutant("on_data", "{}", "[]", file="data.json")
        before = fp_of(self.brain, on_data)
        self.touch("referee/data.json")
        self.assertNotEqual(fp_of(self.brain, on_data), before)

    def test_it_follows_each_field_but_the_id(self):
        before = fp_of(self.brain, self.ON_MOD)
        for field, value in (("old", "return a"), ("new", "return a * b"), ("tests", ["test_mod.T"]),
                             ("tests", ["test_mod.py", "test_mod.py"])):
            with self.subTest(field=field, value=value):
                self.assertNotEqual(fp_of(self.brain, self.ON_MOD | {field: value}), before)
        self.assertEqual(fp_of(self.brain, self.ON_MOD | {"id": "renamed"}), before)  # a row's key carries the id
        # The same words on another file or under another root are another mutant.
        write_tree(self.brain, {"tests/mod.py": Select.TREE["referee/mod.py"], "tests/test_mod.py": "import mod\n",
                                "referee/mod2.py": Select.TREE["referee/mod.py"]})
        self.assertNotEqual(fp_of(self.brain, self.ON_MOD | {"file": "mod2.py"}), before)
        on_root = self.ON_MOD | {"root": ".", "file": "tests/mod.py"}
        self.assertNotEqual(fp_of(self.brain, on_root), fp_of(self.brain, on_root | {"root": "referee",
                                                                                     "file": "tests/../mod.py"}))


class Record(unittest.TestCase):
    """``--record``: which outcomes are kept, when a kept one stands for a run, and what a whole run leaves."""

    K = mutant("k", "return a + b", "return a - b")
    S = mutant("s", "return a + a", "return 2 * a")
    MUTANTS = [K, S, mutant("st", "return a * b", "return a"),
               mutant("r", "return a + b", "return a * b", ["test_red.py"])]

    def setUp(self):
        self.brain = tempfile.mkdtemp(prefix="t-record-")
        self.addCleanup(shutil.rmtree, self.brain, ignore_errors=True)
        write_tree(self.brain, {"referee/mod.py": MOD, "referee/tests/test_mod.py": TEST,
                                "referee/tests/test_red.py": RED, "m.json": {"mutants": self.MUTANTS}})
        self.path = os.path.join(self.brain, "m.json")
        self.dir = tempfile.mkdtemp(prefix="t-record-rows-")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.record = os.path.join(self.dir, "rows.jsonl")

    def run_(self, jobs: int = 2) -> tuple[dict, list[dict]]:
        emitted = []
        rows = mutate.run(self.brain, [self.path], jobs, 120.0, emit=emitted.append, record=self.record)
        self.assertEqual(emitted[1:] and sorted(emitted[1:], key=str), sorted(rows, key=str))
        return emitted[0], rows

    def row(self, m: dict, outcome: str, **more) -> dict:
        return {"file": "m.json", "id": m["id"], "outcome": outcome, "fp": fp_of(self.brain, m)} | more

    def lines(self) -> list[dict]:
        with open(self.record) as fh:
            return [json.loads(line) for line in fh.read().splitlines()]

    def no_run(self):
        """Nothing may be run under this: a kept outcome stands for the run."""
        return mock.patch.object(mutate, "run_one", mock.Mock(side_effect=AssertionError("run again")))

    def test_a_killed_or_survived_outcome_is_kept_and_stands_for_the_next_run(self):
        first, rows = self.run_()
        self.assertEqual(first, plan(4, [0, 0, 4], 2))
        self.assertEqual([r["outcome"] for r in rows], ["killed", "survived", "stale", "baseline_red"])
        self.assertEqual(self.lines(), [self.row(self.K, "killed"), self.row(self.S, "survived")])
        with self.no_run():
            second, again = self.run_()
        self.assertEqual(second, plan(4, [0, 0, 2], 1, reused=2))  # stale and baseline_red are judged again
        self.assertEqual(again, [self.row(self.K, "killed", reused=True), self.row(self.S, "survived", reused=True),
                                 rows[2], rows[3]])
        self.assertEqual(mutate.summary([self.path], again)["reused"], 2)
        self.assertEqual(self.lines(), [self.row(self.K, "killed"), self.row(self.S, "survived")])

    def test_a_change_to_a_reached_file_runs_the_mutant_again_and_its_old_row_goes(self):
        self.run_()
        old = self.lines()
        with open(os.path.join(self.brain, "referee", "tests", "test_mod.py"), "a") as fh:
            fh.write("# one more line\n")
        first, rows = self.run_()
        self.assertEqual(first, plan(4, [0, 0, 4], 2))
        self.assertEqual(self.lines(), [self.row(self.K, "killed"), self.row(self.S, "survived")])
        self.assertFalse([r for r in self.lines() if r in old])

    def test_a_timeout_or_rows_that_disagree_are_not_reused(self):
        k, s = self.row(self.K, "killed"), self.row(self.S, "survived")
        for label, rows, reused in (("one outcome", [k, s, k], 2), ("timeout", [k | {"outcome": "timeout"}, s], 1),
                                    ("baseline_red", [k | {"outcome": "baseline_red"}], 0),
                                    ("stale", [k | {"outcome": "stale"}], 0),
                                    ("disagree", [k, k | {"outcome": "survived"}, s], 1),
                                    ("another fp", [k | {"fp": "0" * 64}], 0),
                                    # st cannot be applied: it has no fp, and no row stands for it
                                    ("no fp", [{"file": "m.json", "id": "st", "outcome": "killed", "fp": ""}], 0),
                                    ("another file", [k | {"file": "m1.json"}], 0)):
            with self.subTest(label=label):
                with open(self.record, "w") as fh:
                    fh.write("".join(json.dumps(r) + "\n" for r in rows))
                emitted = []
                mutate.run(self.brain, [self.path], 1, 120.0, emit=emitted.append, record=self.record,
                           plan_only=True)
                self.assertEqual(emitted[0]["plan"]["reused"], reused)

    def test_a_line_that_is_not_a_row_is_passed_over(self):
        k = self.row(self.K, "killed")
        with open(self.record, "w") as fh:
            fh.write("\n".join([json.dumps(plan(1, [0, 0, 1], 1)), json.dumps(mutate.summary([], [k])), "",
                                json.dumps({j: k[j] for j in ("file", "id", "outcome")}),  # a row of the old shape
                                json.dumps(k | {"outcome": 1}), json.dumps([k]), "not json",
                                json.dumps(k | {"reused": True, "more": 1}), json.dumps(k)[:40]]))  # cut in the middle
        self.assertEqual(mutate.record_rows(self.record), [k])
        self.assertEqual(mutate.record_rows(os.path.join(self.dir, "none.jsonl")), [])

    def test_a_cut_run_leaves_the_rows_it_finished_and_the_next_run_goes_on_from_them(self):
        real = mutate.run_one

        def cut(brain, m, limit):
            if m["id"] == "s":
                raise KeyboardInterrupt
            return real(brain, m, limit)

        write_tree(self.brain, {"m.json": {"mutants": [self.MUTANTS[2], self.MUTANTS[3], self.K, self.S]}})
        with open(self.record, "w") as fh:
            fh.write(json.dumps(self.row(self.K, "killed") | {"fp": "0" * 64}) + "\n")
        with mock.patch.object(mutate, "run_one", cut), self.assertRaises(KeyboardInterrupt):
            self.run_(jobs=1)
        # Appended as it finished (the stale and the baseline_red before it are not kept); a cut run rewrites
        # nothing, the earlier row is still there.
        self.assertEqual(self.lines(), [self.row(self.K, "killed") | {"fp": "0" * 64}, self.row(self.K, "killed")])
        first, _ = self.run_()
        self.assertEqual(first, plan(4, [0, 0, 3], 2, reused=1))
        self.assertEqual(self.lines(), [self.row(self.K, "killed"), self.row(self.S, "survived")])

    def test_a_tree_changed_while_a_mutant_ran_ends_the_run_and_gives_that_mutant_no_row(self):
        def write(mode: str, text: str):
            def change(path: str) -> None:
                with open(path, mode) as fh:
                    fh.write(text)
            return change

        for label, change in (("changed", write("a", "# moved\n")), ("removed", os.remove),
                              ("no longer applies", write("w", "import mod\n"))):
            with self.subTest(label=label):
                write_tree(self.brain, {"referee/mod.py": MOD, "referee/tests/test_mod.py": TEST})
                if os.path.exists(self.record):
                    os.remove(self.record)
                target = os.path.join(self.brain, "referee", "mod.py" if label == "no longer applies"
                                      else "tests/test_mod.py")

                def moved(brain, m, limit, change=change, target=target):
                    if m["id"] == "s":  # s's copy is made and judged, and the tree is another by then
                        change(target)
                    return "killed"

                emitted = []
                with mock.patch.object(mutate, "run_one", moved), self.assertRaises(RuntimeError) as raised:
                    mutate.run(self.brain, [self.path], 1, 120.0, emit=emitted.append, record=self.record)
                self.assertIn("m.json s:", str(raised.exception))
                self.assertEqual([r["id"] for r in emitted[1:]], ["k"])
                self.assertEqual([r["id"] for r in self.lines()], ["k"])  # k ran before the change: its row stands

    def test_a_whole_run_keeps_the_rows_of_the_files_it_did_not_read(self):
        other = [{"file": "other.json", "id": "x", "outcome": "survived", "fp": "1" * 64},
                 {"file": "other.json", "id": "x", "outcome": "killed", "fp": "2" * 64}]
        with open(self.record, "w") as fh:
            fh.write("".join(json.dumps(r) + "\n" for r in [other[0], self.row(self.S, "survived"), other[1],
                                                           self.row(self.S, "survived")]))
        with mock.patch.object(mutate, "run_one", lambda brain, m, limit: "killed"):
            self.run_()
        self.assertEqual(self.lines(), [self.row(self.K, "killed"), self.row(self.S, "survived"), *other])

    def test_the_command_line(self):
        def main(*flags: str) -> tuple[int, list[dict]]:
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = mutate.main(["--brain", self.brain, "-j", "2", "--record", self.record, *flags, self.path])
            return code, [json.loads(line) for line in out.getvalue().splitlines()]

        by_file = {"by_file": {"m.json": [4, 4]}}
        with self.no_run(), mock.patch.object(mutate, "baseline", mock.Mock(side_effect=AssertionError("run"))):
            self.assertEqual(main("--plan"), (0, [{"plan": plan(4, [0, 0, 4], 2)["plan"] | by_file}]))
        self.assertFalse(os.path.exists(self.record))  # --plan writes nothing
        code, lines = main()
        self.assertEqual((code, lines[0], lines[-1]["reused"]), (1, plan(4, [0, 0, 4], 2), 0))
        with open(self.record, "rb") as fh:
            kept = fh.read()
        with self.no_run():
            code, lines = main()
            self.assertEqual((code, lines[0], lines[-1]["reused"]), (1, plan(4, [0, 0, 2], 1, reused=2), 2))
            self.assertEqual(sorted(r["id"] for r in lines[1:-1] if r.get("reused")), ["k", "s"])
            self.assertEqual(main("--plan")[1][0]["plan"]["by_file"], {"m.json": [4, 2]})
        with open(self.record, "rb") as fh:
            self.assertEqual(fh.read(), kept)


class Touched(unittest.TestCase):
    """``touched``, git's half of ``--touched``, against a fake ``git`` (the referee's sandbox has none): what it
    asks git and how it joins the answers. Real git's answers to the same questions are not tested here."""

    def setUp(self):
        self.bin = tempfile.mkdtemp(prefix="t-touched-")
        self.addCleanup(shutil.rmtree, self.bin, ignore_errors=True)
        self.brain = tempfile.mkdtemp(prefix="t-touched-brain-")
        self.addCleanup(shutil.rmtree, self.brain, ignore_errors=True)
        write_tree(self.brain, Select.TREE)
        patcher = mock.patch.dict(os.environ, {"PATH": self.bin + os.pathsep + os.environ.get("PATH", "")})
        patcher.start()
        self.addCleanup(patcher.stop)

    def fake(self, diff: bytes, others: bytes, exits: dict | None = None) -> None:
        git_store.install_git(self.bin, {}, exits=exits,
                              outputs={"rev-parse": b"1" * 40 + b"\n", "diff": diff, "ls-files": others})

    def test_the_questions_and_the_union_of_their_answers(self):
        self.fake(b"referee/mod.py\nreferee/pkg/util.py\n", b"referee/tests/mutants/c.json\n")
        self.assertEqual(mutate.touched(self.brain, "REV"),
                         {"referee/mod.py", "referee/pkg/util.py", "referee/tests/mutants/c.json"})
        self.assertEqual([c["argv"] for c in git_store.calls(self.bin)], [
            ["-C", self.brain, "rev-parse", "--verify", "--quiet", "REV^{commit}"],
            ["-C", self.brain, "diff", "--name-only", "--no-renames", "REV", "--"],
            ["-C", self.brain, "ls-files", "--others", "--exclude-standard"]])

    def test_a_rev_git_cannot_read_raises(self):
        for failing in ("rev-parse", "diff", "ls-files"):
            with self.subTest(failing=failing):
                self.fake(b"", b"", exits={failing: 128})
                with self.assertRaises(ValueError):
                    mutate.touched(self.brain, "REV")

    def test_main_runs_only_the_selected(self):
        self.fake(b"referee/mod.py\n", b"")
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = mutate.main(["--brain", self.brain, "-j", "2", "--touched", "REV"])
        first, *rows, total = [json.loads(line) for line in out.getvalue().splitlines()]
        # The selection's size is the first line, before anything runs: on_mod's file changed (tier 0),
        # not_imported only reaches it through its test's import (tier 2); both have one tests list.
        self.assertEqual(first, plan(2, [1, 0, 1], 1, changed=1))
        self.assertEqual(sorted((r["id"], r["outcome"]) for r in rows),
                         [("not_imported", "survived"), ("on_mod", "killed")])
        self.assertEqual((total["mutants"], total["ok"]), (2, False))
        self.assertEqual(code, 1)


def defines(path: str, names: list[str]) -> bool:
    """Whether the module at ``path`` defines the class ``names[0]`` at its top level (and its method ``names[1]``)."""
    with open(path, encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    classes = [n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == names[0]]
    if not classes or len(names) == 1:
        return bool(classes)
    return any(isinstance(n, ast.FunctionDef) and n.name == names[1] for n in classes[0].body)


class Kept(unittest.TestCase):
    def test_every_kept_mutant_is_well_formed_and_applies_to_todays_code(self):
        files = sorted(glob.glob(os.path.join(mutate.BRAIN, "referee", "tests", "mutants", "*.json")))
        self.assertTrue(files)
        for path in files:
            for m in mutate.load(path):
                with self.subTest(file=os.path.basename(path), id=m["id"]):
                    self.assertIsNone(mutate.applicable(mutate.BRAIN, m))
                    for entry in m["tests"]:
                        found = glob.glob(os.path.join(mutate.BRAIN, m["root"], "tests", mutate.test_file(entry)))
                        self.assertTrue(found, entry)
                        if not entry.endswith(".py"):  # the id's class (and method) are defined in its module
                            self.assertTrue(defines(found[0], entry.split(".")[1:]), entry)


if __name__ == "__main__":
    unittest.main()
