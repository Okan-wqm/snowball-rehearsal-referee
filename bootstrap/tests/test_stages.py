"""The stage table loader (`asama-0/14`, `tohum/26c` "Aşama tablosu"). A table it refuses stops the run.

`test_wiring.StageTableMatchesTheSpecTest` holds the seed's `stages/stage0.json` to the spec pages; here every rule
the loader enforces is broken once on a copy of it, and module-less red's tree is built from it.
"""

import copy
import io
import json
import tarfile
import tempfile
import unittest
from pathlib import Path

from snowball_bootstrap import stages
from snowball_bootstrap.config import ConfigError
from snowball_bootstrap.container import RunResult
from snowball_bootstrap.moduleless import module_less_tree, run_module_less

SEED_TABLE = json.loads((stages.STAGES_DIR / "stage0.json").read_text(encoding="utf-8"))


def broken(edit):
    """The seed table with one edit applied, as text."""
    table = copy.deepcopy(SEED_TABLE)
    edit(table)
    return json.dumps(table)


def tar_of(files):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:") as tar:
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


class SeedTableTest(unittest.TestCase):
    def test_the_seed_table_is_the_eighteen_micro_features(self):
        table = stages.load(0)
        self.assertEqual(table.count, 18)
        self.assertEqual([f.mf for f in table.mfs], list(range(1, 19)))
        self.assertEqual(table.feature(1).tests, (13,))
        self.assertEqual(table.feature(18).tests, (45, 14))  # in the page's order
        self.assertEqual(table.feature(1).module_path, "referee/ledger/chain.py")
        self.assertEqual(table.feature(17).groups, ())  # `wiring` is the seed's check, not a vector group
        self.assertEqual(sum(len(f.tests) for f in table.mfs), 21)
        with self.assertRaises(KeyError):
            table.feature(19)


class LoaderRefusesTest(unittest.TestCase):
    def refused(self, text, says):
        with self.assertRaises(ConfigError) as caught:
            stages.parse_table(text, 0)
        self.assertIn(says, str(caught.exception))

    def test_a_called_micro_feature_after_its_caller(self):
        """`asama-0/14` "Sıra": the referee checks the order when it loads the table."""
        self.refused(broken(lambda t: t["mfs"][1].update(calls=[3])), "MF2 calls MF3")
        self.refused(broken(lambda t: t["mfs"][4].update(calls=[4, 5])), "MF5 calls MF5")  # nor itself
        self.refused(broken(lambda t: t["mfs"][16].update(calls=list(range(1, 19)))), "MF17 calls MF17")

    def test_micro_features_not_numbered_one_to_n_in_order(self):
        self.refused(broken(lambda t: t["mfs"][2].update(mf=4)), "numbered 1..N")
        self.refused(broken(lambda t: t["mfs"].pop(0)), "numbered 1..N")
        self.refused(broken(lambda t: t["mfs"][0].update(mf=True)), "numbered 1..N")

    def test_a_test_of_two_micro_features(self):
        self.refused(broken(lambda t: t["mfs"][1].update(tests=[38, 13])), "test 13 is already MF1's")

    def test_malformed_tests(self):
        for tests in ([], [0], [1000], ["13"], [True], None):
            self.refused(broken(lambda t: t["mfs"][0].update(tests=tests)), "tests must be")

    def test_malformed_groups(self):
        for groups in (["Chain"], ["chain", "chain"], [""], [1], "chain", ["a-b"]):
            self.refused(broken(lambda t: t["mfs"][0].update(groups=groups)), "groups must be")

    def test_unsafe_or_shared_module_paths(self):
        for module in ("../x.py", "/abs.py", "a" + chr(92) + "b.py", "a:b.py", "ledger//chain.py", "ledger/",
                       "./chain.py", "", 7, ".git/hooks/x"):
            with self.subTest(module=module):
                with self.assertRaises(ConfigError):
                    stages.parse_table(broken(lambda t: t["mfs"][0].update(module=module)), 0)
        self.refused(broken(lambda t: t["mfs"][1].update(module="ledger/chain.py")), "another micro-feature's")

    def test_calls_that_are_not_increasing_numbers(self):
        for calls in ([3, 3], [5, 3], ["3"], [True], [0], None):
            self.refused(broken(lambda t: t["mfs"][5].update(calls=calls)), "calls must be")

    def test_wrong_shape(self):
        self.refused("{", "not valid JSON")
        self.refused("[" * 100000, "not valid JSON")
        self.refused(broken(lambda t: t.update(extra=1)), "exactly: stage, mfs")
        self.refused(broken(lambda t: t.update(stage=1)), "says stage 1")
        self.refused(broken(lambda t: t.update(stage=False)), "says stage False")
        self.refused(broken(lambda t: t.update(mfs=[])), "mfs must be")
        self.refused(broken(lambda t: t["mfs"][0].update(note="x")), "must have exactly")
        self.refused(broken(lambda t: t["mfs"][0].pop("calls")), "must have exactly")

    def test_an_unreadable_table_is_a_stop_too(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ConfigError):
                stages.load(0, Path(tmp))  # no stage0.json at all
            (Path(tmp) / "stage0.json").write_bytes(b"\xff\xfe")
            with self.assertRaises(ConfigError):
                stages.load(0, Path(tmp))
            (Path(tmp) / "stage0.json").write_text(broken(lambda t: t["mfs"][1].update(calls=[3])), encoding="utf-8")
            with self.assertRaises(ConfigError):
                stages.load(0, Path(tmp))


class ModuleLessTreeTest(unittest.TestCase):
    """The tree module-less red runs on: the pushed tree minus one path of the stage table (`asama-0/14`)."""

    TREE = {"referee/ledger/chain.py": b"x = 1\n", "referee/ledger/__init__.py": b"", "referee/gate/check.py": b"y\n",
            "referee/runner/contained.py": b"z\n", "snowball-tests.json": b"{}"}

    def test_only_the_module_is_gone(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "MF1"
            self.assertTrue(module_less_tree(tar_of(self.TREE), dest, "referee/ledger/chain.py", 10_000))
            self.assertFalse((dest / "referee" / "ledger" / "chain.py").exists())
            self.assertEqual(sorted(p.relative_to(dest).as_posix() for p in dest.rglob("*") if p.is_file()),
                             ["referee/gate/check.py", "referee/ledger/__init__.py", "referee/runner/contained.py",
                              "snowball-tests.json"])
            self.assertFalse(module_less_tree(tar_of(self.TREE), Path(tmp) / "MF2", "referee/gate/secrets.py", 10_000))
            module_less_tree(tar_of(self.TREE), Path(tmp) / "dir", "referee/ledger", 10_000)  # a directory goes whole
            self.assertFalse((Path(tmp) / "dir" / "referee" / "ledger").exists())

    def test_each_test_of_each_micro_feature_runs_on_its_own_tree(self):
        seen = []

        class Runner:
            def __init__(self, src):
                self.src = src

            def run(self, cmd, *, cwd=".", stdin=b"", timeout_s):
                seen.append((self.src.name, cmd, timeout_s))
                present = (self.src / "referee" / "runner" / "contained.py").exists()
                return RunResult(0 if cmd == "t21" or present else 1, b"", b"", 1)  # T21 never looks at the module

        tests = [{"id": "T13", "cmd": "t13", "stage": 0}, {"id": "T20", "cmd": "t20", "stage": 0},
                 {"id": "T21", "cmd": "t21", "stage": 0}, {"id": "T38", "cmd": "t38", "stage": 1}]
        with tempfile.TemporaryDirectory() as tmp:
            results = run_module_less(Runner, tar_of(self.TREE), Path(tmp), stages.load(0), [2, 3], tests, 77, 10_000)
        self.assertEqual(seen, [("MF3", "t20", 77), ("MF3", "t21", 77)])  # MF2's T38 is not a stage 0 test here
        self.assertEqual([(r["mf"], r["test_id"], r["stayed_green"], r["module_present"]) for r in results],
                         [(3, "T20", False, True), (3, "T21", True, True)])
        self.assertEqual({r["module"] for r in results}, {"referee/runner/contained.py"})


if __name__ == "__main__":
    unittest.main()
