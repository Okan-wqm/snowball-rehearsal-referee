import io
import json
import re
import shlex
import tarfile
import tempfile
import time
import unittest
import zipfile
from pathlib import Path

from unittest import mock

from snowball_bootstrap import canon, licenses, secretscan, stages, vectors
from snowball_bootstrap.classify import classify, spec_stage_dirs
from snowball_bootstrap.config import ConfigError, load_bootstrap
from snowball_bootstrap.container import RunResult
from snowball_bootstrap.controls import run_controls
from snowball_bootstrap.manifest import ManifestError, check_stage0, parse_lockfile, parse_manifest
from snowball_bootstrap.treehash import TreeError, extract
from snowball_bootstrap.vectors import missing_groups, run_vectors

from helpers import DRILL, EVERY_GROUP, STATS, FakeRunner

BOOTSTRAP = Path(__file__).resolve().parents[1]
VECTORS = BOOTSTRAP / "vectors"
# Stage 0's groups the seed has vectors for; every other group the table names is still missing (`29d`, E161).
STAGE0_SEEDED = ("chain", "secrets", "contained", "profile", "npmlock", "recipe", "diffguard")
DATA_GROUPS = STAGE0_SEEDED[1:]
POLICY_DEFAULTS = BOOTSTRAP.parents[1] / "spec" / "tohum" / "18a-politika-baslangic-degerleri.md"
Z = "0" * 64


class CanonTest(unittest.TestCase):
    def test_seed_vectors_v1_v2(self):
        v1 = {"row_id": "r1", "ts": "2026-10-28T00:00:00Z", "part": "events", "kind": "genesis", "payload": {},
              "derivation": "tool", "trust": "verified", "snapshot_id": "s0", "evidence_refs": [], "prev_hash": Z}
        h1 = canon.row_hash(v1)
        self.assertEqual(h1, "3bae91580aca99362572e9f5f41b3e46c2bc0c29236f72e867faa5cd46ca603a")
        v2 = {"row_id": "r2", "ts": "2026-10-28T00:00:01Z", "part": "cost", "kind": "run",
              "payload": {"usd_micros": 0}, "derivation": "tool", "trust": "observed", "snapshot_id": "s0",
              "evidence_refs": [], "prev_hash": h1}
        self.assertEqual(canon.row_hash(v2), "3b10a5bb06351b0933c0e30f7dd55d3a57245743b97fb1faba348351a554a45c")

    def test_row_hash_ignores_own_hash_field(self):
        row = {"a": 1, "prev_hash": Z}
        self.assertEqual(canon.row_hash(row), canon.row_hash(dict(row, row_hash="x" * 64)))

    def test_floats_and_surrogates_rejected(self):
        with self.assertRaises(canon.CanonicalError):
            canon.canonical({"x": 0.5})
        with self.assertRaises(canon.CanonicalError):
            canon.canonical({"x": "\ud800"})
        with self.assertRaises(canon.CanonicalError):
            canon.canonical({"x": 2**60})

    def test_keys_sorted_by_utf16(self):
        self.assertEqual(canon.canonical({"b": 1, "a": 2, "é": 3}), '{"a":2,"b":1,"é":3}'.encode())


class ClassifyTest(unittest.TestCase):
    def test_kinds(self):
        self.assertEqual(classify([]), ("none", []))
        self.assertEqual(classify(["spec/asama-0/01-amac.md", "spec/INDEX.md"]), ("spec", []))
        self.assertEqual(classify(["referee/ledger/chain.py", "snowball-tests.json"]), ("code", []))
        self.assertEqual(classify(["spec/asama-0/x.md", "referee/a.py"]), ("rejected", ["mixed_spec_and_code"]))
        self.assertEqual(classify(["spec/tohum/00-cekirdek.md"]), ("rejected", ["seed_modified"]))
        self.assertEqual(classify(["seed/bootstrap/x.py"]), ("rejected", ["seed_modified"]))
        self.assertEqual(classify([".github/workflows/x.yml"]), ("rejected", ["root_workflow_modified"]))
        self.assertEqual(classify(["referee/.github/workflows/x.yml"]), ("code", []))

    def test_the_founders_ledger_and_reports_are_neither_spec_nor_code(self):
        # A spec request that also appends the Founder's ledger is still a spec request, not a mixed push.
        self.assertEqual(classify(["spec/asama-0/x.md", "founder-ledger.jsonl"]), ("spec", []))
        self.assertEqual(classify(["referee/a.py", "reports/r1.json", "founder-ledger.jsonl"]), ("code", []))
        # Nothing but the Founder's records: nothing to judge.
        self.assertEqual(classify(["founder-ledger.jsonl"]), ("none", []))
        self.assertEqual(classify(["founder-ledger.jsonl", "reports/a/b.json"]), ("none", []))
        # Only the root ledger and the root reports/ directory; look-alikes are code, the seed stays the seed.
        self.assertEqual(classify(["referee/founder-ledger.jsonl"]), ("code", []))
        self.assertEqual(classify(["reportsx/a.json"]), ("code", []))
        self.assertEqual(classify(["founder-ledger.jsonl", "seed/x.py"]), ("rejected", ["seed_modified"]))

    def test_spec_dirs(self):
        self.assertEqual(spec_stage_dirs(["spec/asama-0/a.md", "spec/asama-1/b.md", "spec/INDEX.md"]),
                         ["spec/asama-0", "spec/asama-1"])


class ManifestTest(unittest.TestCase):
    def manifest(self, tests, done, locks=()):
        return json.dumps({"tests": tests, "done_mf": list(done), "lockfiles": list(locks)})

    def all_tests(self, done):
        table = stages.load(0)
        return [{"id": f"T{n}", "cmd": f"python -m unittest t{n}", "stage": 0} for k in done
                for n in table.feature(k).tests]

    def test_valid_and_complete(self):
        m = parse_manifest(self.manifest([{"id": "T13", "cmd": "python -m unittest", "stage": 0},
                                          {"id": "T38", "cmd": "python -m unittest t38", "stage": 0}], [1, 2]))
        self.assertEqual(check_stage0(m), [])

    def test_missing_test_and_zero_tests_and_order(self):
        m = parse_manifest(self.manifest([{"id": "T13", "cmd": "x", "stage": 0}], [1, 2]))
        self.assertEqual(check_stage0(m), ["missing_test:MF2:T38"])
        m = parse_manifest(self.manifest([], []))
        self.assertEqual(check_stage0(m), ["zero_tests"])
        m = parse_manifest(self.manifest([{"id": "T13", "cmd": "x", "stage": 0}], [2]))
        self.assertEqual(check_stage0(m), ["done_mf_not_in_order"])

    def test_the_stage_table_says_what_each_micro_feature_needs(self):
        """The 18 micro-features of `asama-0/14`, read from `stages/stage0.json`, not from a copy in the code."""
        self.assertEqual(check_stage0(parse_manifest(self.manifest(self.all_tests(range(1, 19)), range(1, 19)))), [])
        two_tests = [t for t in self.all_tests(range(1, 4)) if t["id"] != "T21"]  # MF3 is T20 and T21
        self.assertEqual(check_stage0(parse_manifest(self.manifest(two_tests, [1, 2, 3]))), ["missing_test:MF3:T21"])
        last = [t for t in self.all_tests(range(1, 19)) if t["id"] != "T14"]  # MF18 is T45 and T14
        self.assertEqual(check_stage0(parse_manifest(self.manifest(last, range(1, 19)))), ["missing_test:MF18:T14"])
        too_many = parse_manifest(self.manifest(self.all_tests(range(1, 19)), range(1, 20)))
        self.assertEqual(check_stage0(too_many), ["done_mf_not_in_order"])  # there is no MF19
        old = parse_manifest(self.manifest([{"id": "T13", "cmd": "x", "stage": 0}, {"id": "T30", "cmd": "x", "stage": 0}],
                                           [1, 2]))
        self.assertEqual(check_stage0(old), ["missing_test:MF2:T38"])  # the 30-MF table's MF2 test is not enough

    def test_malformed(self):
        for bad in ['{"tests": []}', self.manifest([{"id": "13", "cmd": "x", "stage": 0}], []),
                    self.manifest([{"id": "T1", "cmd": "", "stage": 0}], []),
                    self.manifest([], [], ["../x.txt"]),
                    self.manifest([{"id": "T1", "cmd": "x", "stage": 0, "extra": 1}], [])]:
            with self.assertRaises(ManifestError):
                parse_manifest(bad)

    def test_lockfile(self):
        h = "a" * 64
        self.assertEqual(len(parse_lockfile(f"x==1 \\\n    --hash=sha256:{h}\ny==2 --hash=sha256:{h}\n")), 2)
        for bad in [f"x>=1 --hash=sha256:{h}", "x==1", f"--index-url https://evil\nx==1 --hash=sha256:{h}",
                    f"x==1 --hash=sha256:{h} --trusted-host evil", "git+https://x/y"]:
            with self.assertRaises(ManifestError):
                parse_lockfile(bad)


class VectorsTest(unittest.TestCase):
    def test_correct_implementation_passes_every_vector(self):
        results = run_vectors(FakeRunner(VECTORS), VECTORS, STATS, table=EVERY_GROUP)
        self.assertTrue(results)
        self.assertEqual([r for r in results if not r["ok"]], [])

    def test_groups_wait_for_their_micro_feature(self):
        self.assertEqual(run_vectors(FakeRunner(VECTORS), VECTORS, (2,), table=EVERY_GROUP)[0]["id"],
                         "cp_lower.60/60")
        ids = {r["id"].split(".")[0] for r in run_vectors(FakeRunner(VECTORS), VECTORS, (2,))}
        self.assertEqual(ids, {"secrets"})  # Stage 0's MF2
        ids = {r["id"].split(".")[0] for r in run_vectors(FakeRunner(VECTORS), VECTORS, (1,))}
        self.assertEqual(ids, {"chain"})

    def test_a_group_no_stage0_micro_feature_owns_never_runs_in_stage0(self):
        """`29d`: `cp_lower`, `mcnemar`, `match` (P1) and `drill` (Stage 2 batch) have no owner in the Stage 0
        table; with every micro-feature done only Stage 0's groups run (`chain`, owned by MF1 and MF10, once)."""
        ids = [r["id"] for r in run_vectors(FakeRunner(VECTORS), VECTORS, tuple(range(1, 19)))]
        self.assertEqual({i.split(".")[0] for i in ids}, set(STAGE0_SEEDED))
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(stages.load(0).groups_of((10,)), ("chain", "append"))

    def test_a_group_the_seed_has_no_vectors_for_is_named_not_invented(self):
        """The Stage 0 groups after `diffguard` come with a later seed epoch (`29d`); until they do the referee says
        which a finished micro-feature owns, and runs nothing in their place. MF2-MF7's groups no longer warn."""
        self.assertEqual(missing_groups(VECTORS, (1,), stages.load(0)), [])
        self.assertEqual(missing_groups(VECTORS, tuple(range(1, 8)), stages.load(0)), [])
        self.assertEqual(missing_groups(VECTORS, (1, 8), stages.load(0)), ["k0map"])
        self.assertEqual(missing_groups(VECTORS, tuple(range(1, 11)), stages.load(0)), ["k0map", "refs", "append"])
        self.assertEqual(missing_groups(VECTORS, tuple(range(1, 19)), stages.load(0)),
                         ["k0map", "refs", "append", "root", "flaky", "cause", "revert_drill", "prompt", "status",
                          "genesis"])
        self.assertEqual(missing_groups(VECTORS, STATS + DRILL, EVERY_GROUP), [])

    def test_wrong_implementations_fail(self):
        for wrong, prefix in [("chain_ignores_input", "chain.V1.hash_changed_input"),
                              ("verify_always_valid", "chain.V3"), ("cp_wilson", "cp_lower.60/60"),
                              ("score_counts_twice", "match.3")]:
            failed = {r["id"] for r in run_vectors(FakeRunner(VECTORS, wrong={wrong}), VECTORS, STATS,
                                                   table=EVERY_GROUP) if not r["ok"]}
            self.assertIn(prefix, failed, wrong)

    def test_drill_vectors_need_a_judge_that_fails_non_learners(self):
        honest = run_vectors(FakeRunner(VECTORS), VECTORS, DRILL, table=EVERY_GROUP)
        self.assertEqual(len(honest), 19)
        self.assertEqual([r for r in honest if not r["ok"]], [])
        lenient = {r["id"] for r in run_vectors(FakeRunner(VECTORS, wrong={"drill_lenient"}), VECTORS, DRILL,
                                                table=EVERY_GROUP) if not r["ok"]}
        self.assertEqual(lenient, {r["id"] for r in honest} - {"drill.learner"})
        blind = {r["id"] for r in run_vectors(FakeRunner(VECTORS, wrong={"drill_ignores_commitment"}), VECTORS,
                                             DRILL, table=EVERY_GROUP) if not r["ok"]}
        self.assertEqual(blind, {"drill.tampered_key"})


class Scripted:
    """A container that answers each (command, stdin) pair with a fixed (exit, stdout); anything else exits 1."""

    def __init__(self, answers):
        self.answers, self.calls = answers, []

    def run(self, cmd, *, cwd=".", stdin=b"", timeout_s):
        self.calls.append((cmd, cwd, stdin))
        code, out = self.answers.get((cmd, stdin), (1, b""))
        return RunResult(code, out, b"", 1)


class DataRunnerTest(unittest.TestCase):
    """The generic data runner (`29d`) on a made-up group: one case, its changed input, and every way to fail."""

    TABLE = stages.parse_table(json.dumps({"stage": 0, "mfs": [
        {"mf": 1, "tests": [13], "groups": ["probe"], "module": "probe/x.py", "calls": []}]}), 0)
    CASE = {"id": "probe.one", "purpose": "a made-up case", "cmd": "python -m probe.x run /vec/probe/a.txt",
            "stdin": '{"n": 1}', "fixture": ["probe/a.txt"], "expect": {"ok": True, "n": 1},
            "changed": {"description": "one field", "cmd": "python -m probe.x run /vec/probe/b.txt",
                        "stdin": '{"n": 2}', "fixture": ["probe/b.txt"], "expect_not": {"ok": True, "n": 1}}}
    GOOD = (0, b'{"ok": true, "n": 1, "argv": ["docker", "run"], "reason": "free text"}\n')
    OTHER = (1, b'{"ok": false, "n": 1}\n')

    def run_case(self, original, changed, group=None):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "vectors.json").write_text(json.dumps(
                {"probe": group or {"owner": "asama-0", "runner": "data", "cases": [self.CASE]}}), encoding="utf-8")
            runner = Scripted({(self.CASE["cmd"], b'{"n": 1}'): original,
                               (self.CASE["changed"]["cmd"], b'{"n": 2}'): changed})
            results = run_vectors(runner, Path(tmp), (1,), table=self.TABLE)
        return {r["id"]: r for r in results}, runner

    def test_the_named_fields_are_compared_and_the_others_are_the_commands_own(self):
        results, runner = self.run_case(self.GOOD, self.OTHER)
        self.assertEqual({k: r["ok"] for k, r in results.items()}, {"probe.one": True, "probe.one.changed_input": True})
        self.assertEqual(runner.calls, [(self.CASE["cmd"], "referee", b'{"n": 1}'),
                                        (self.CASE["changed"]["cmd"], "referee", b'{"n": 2}')])
        results, _ = self.run_case((0, b"progress...\n" + self.GOOD[1]), self.OTHER)
        self.assertTrue(results["probe.one"]["ok"])  # the last line of stdout is the answer

    def test_values_are_compared_as_json_not_as_python(self):
        for wrong in (b'{"ok": 1, "n": 1}', b'{"ok": true, "n": 1.0}', b'{"ok": true, "n": true}', b'{"ok": true}',
                      b'{"ok": true, "n": "1"}', b'[true, 1]', b'not json'):
            results, _ = self.run_case((0, wrong), self.OTHER)
            self.assertEqual((results["probe.one"]["ok"], results["probe.one.changed_input"]["ok"]), (False, True),
                             wrong)

    def test_a_changed_input_must_answer_the_same_fields_and_differently(self):
        for changed in (self.GOOD, (0, b'{"ok": false}'), (0, b"{}"), (1, b""), (1, b"Traceback")):
            results, _ = self.run_case(self.GOOD, changed)
            self.assertEqual((results["probe.one"]["ok"], results["probe.one.changed_input"]["ok"]), (True, False),
                             changed)

    def test_exit_125_stays_a_runner_fault(self):
        results, _ = self.run_case((125, b""), self.OTHER)
        self.assertEqual((results["probe.one"]["ok"], results["probe.one"]["runner_fault"]), (False, True))
        results, _ = self.run_case((1, b""), self.OTHER)
        self.assertEqual((results["probe.one"]["ok"], results["probe.one"]["runner_fault"]), (False, False))

    def test_values_inside_lists_and_objects_are_compared_as_json_too(self):
        """Most compared fields are lists or objects (`lines`, `mounts`, `reasons`): `[true]` is not `[1]` there either,
        nor `[7.0]` `[7]`, nor `{"k": 1}` `{"k": true}`."""
        case = dict(self.CASE, expect={"lines": [1, 7], "m": {"k": 1}},
                    changed=dict(self.CASE["changed"], expect_not={"lines": [1, 7], "m": {"k": 1}}))
        group = {"owner": "asama-0", "runner": "data", "cases": [case]}
        other = (1, b'{"lines": [], "m": {}}')
        results, _ = self.run_case((0, b'{"lines": [1, 7], "m": {"k": 1}}'), other, group)
        self.assertTrue(results["probe.one"]["ok"])
        for wrong in (b'{"lines": [true, 7], "m": {"k": 1}}', b'{"lines": [1, 7.0], "m": {"k": 1}}',
                      b'{"lines": [1, 7], "m": {"k": true}}', b'{"lines": [1, 7], "m": {"k": 1.0}}',
                      b'{"lines": [[1], 7], "m": {"k": 1}}'):
            results, _ = self.run_case((0, wrong), other, group)
            self.assertFalse(results["probe.one"]["ok"], wrong)

    def test_an_answer_nested_deeper_than_the_parser_goes_is_red_not_a_crash(self):
        """A last line 100 000 levels deep made `json.loads` raise RecursionError through `run-tests`: the job failed and
        the push became an outage instead of the Founder's vector_failed."""
        deep = b'{"ok": ' + b"[" * 100_000 + b"]" * 100_000 + b"}"
        results, _ = self.run_case((0, deep), self.OTHER)
        self.assertEqual((results["probe.one"]["ok"], results["probe.one"]["detail"]), (False, "no JSON object"))
        results, _ = self.run_case(self.GOOD, (0, deep))
        self.assertFalse(results["probe.one.changed_input"]["ok"])

    def test_a_data_group_runs_only_on_a_tree_whose_seed_has_its_interface_page(self):
        """The page (`29f`, `29g`) is all the Founder reads of a group. Vectors the referee got before the Founder's seed
        has the page are the seed's gap (`vector_group_missing`), not a red push for an interface it was never shown."""
        group = {"owner": "asama-0", "runner": "data", "interface": "spec/tohum/29x-probe.md", "cases": [self.CASE]}
        with tempfile.TemporaryDirectory() as tmp:
            seed, tree = Path(tmp, "seed"), Path(tmp, "tree")
            seed.mkdir()
            (seed / "vectors.json").write_text(json.dumps({"probe": group}), encoding="utf-8")
            (tree / "spec" / "tohum").mkdir(parents=True)
            self.assertEqual(missing_groups(seed, (1,), self.TABLE, tree=tree), ["probe"])
            self.assertEqual(run_vectors(Scripted({}), seed, (1,), table=self.TABLE, tree=tree), [])
            (tree / "spec" / "tohum" / "29x-probe.md").write_text("# probe" + chr(10), encoding="utf-8")
            self.assertEqual(missing_groups(seed, (1,), self.TABLE, tree=tree), [])
            self.assertEqual(len(run_vectors(Scripted({}), seed, (1,), table=self.TABLE, tree=tree)), 2)
            self.assertEqual(missing_groups(seed, (1,), self.TABLE), [])  # the seed checked on its own
            no_page = dict(group)
            del no_page["interface"]
            (seed / "vectors.json").write_text(json.dumps({"probe": no_page}), encoding="utf-8")
            self.assertEqual(missing_groups(seed, (1,), self.TABLE, tree=tree), ["probe"])

    def test_the_vectors_of_one_push_run_within_one_time_budget(self):
        """A command that hangs on every input cost 2 tries x 120 s per call: 94 calls outlived the 60-minute `kos` job,
        which books the push as an outage the Founder never hears of. Within the budget the first hang is on the
        record; what the budget leaves is red as `not_run:time_budget`, the Founder's, never a runner fault."""
        cases = [dict(self.CASE, id=f"probe.c{i}") for i in range(30)]
        clock = [0.0]

        class Hangs:
            calls = []

            def run(self, cmd, *, cwd=".", stdin=b"", timeout_s):
                self.calls.append(timeout_s)
                clock[0] += timeout_s
                return RunResult(124, b"", b"", timeout_s * 1000, timed_out=True)
        runner = Hangs()
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(vectors, "_now", lambda: clock[0]):
            Path(tmp, "vectors.json").write_text(json.dumps(
                {"probe": {"owner": "asama-0", "runner": "data", "cases": cases}}), encoding="utf-8")
            results = run_vectors(runner, Path(tmp), (1,), table=self.TABLE)
        self.assertEqual(len(results), 60)  # every vector is on the record
        self.assertLessEqual(sum(runner.calls), vectors.BUDGET_S)
        self.assertEqual(len(runner.calls), vectors.BUDGET_S // 120)
        self.assertEqual([r for r in results if r["ok"] or r["runner_fault"]], [])
        self.assertIn("timed out", results[0]["detail"])
        self.assertIn("not_run:time_budget", results[-1]["detail"])
        self.assertIsNone(results[-1]["exit"])

    def test_the_fixtures_are_mounted_without_the_expected_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            vec = vectors.fixtures(VECTORS, Path(tmp) / "vec")
            self.assertFalse((vec / "vectors.json").exists())
            seed = json.loads((VECTORS / "vectors.json").read_text(encoding="utf-8"))
            for name in DATA_GROUPS:
                for case in seed[name]["cases"]:
                    for rel in case["fixture"] + case["changed"]["fixture"]:  # a file, or a tree (a registry mirror)
                        files = [p for p in [VECTORS / rel, *(VECTORS / rel).rglob("*")] if p.is_file()]
                        self.assertTrue(files, rel)
                        for path in files:
                            copy = vec / path.relative_to(VECTORS)
                            self.assertEqual(copy.read_bytes(), path.read_bytes(), copy)
            self.assertTrue((vec / "chain" / "good.jsonl").is_file())
            (vec / "stale").write_text("from an earlier run")
            self.assertFalse((vectors.fixtures(VECTORS, vec) / "stale").exists())  # a used work dir gets a fresh copy

    def test_only_a_group_marked_as_data_has_a_judge(self):
        for group, missing in (({"owner": "asama-0", "runner": "data", "cases": [self.CASE]}, []),
                               ({"owner": "asama-0", "runner": "other", "cases": [self.CASE]}, ["probe"]),
                               ({"owner": "asama-0", "cases": [self.CASE]}, ["probe"])):
            with tempfile.TemporaryDirectory() as tmp:
                Path(tmp, "vectors.json").write_text(json.dumps({"probe": group}), encoding="utf-8")
                self.assertEqual(missing_groups(Path(tmp), (1,), self.TABLE), missing, group)
                ran = run_vectors(Scripted({}), Path(tmp), (1,), table=self.TABLE)
                self.assertEqual(len(ran), 0 if missing else 2, group)  # a group without a judge runs nothing


class SeedDataVectorsTest(unittest.TestCase):
    """MF2-MF7's seed vectors as the data runner reads them (`29d`): the format, the fixtures, nothing dead."""

    SEED = json.loads((VECTORS / "vectors.json").read_text(encoding="utf-8"))

    def test_every_data_group_has_the_29d_format(self):
        self.assertEqual([n for n, g in self.SEED.items() if isinstance(g, dict) and g.get("runner") == "data"],
                         list(DATA_GROUPS))
        ids = []
        for name in DATA_GROUPS:
            group = self.SEED[name]
            self.assertEqual(set(group), {"owner", "runner", "interface", "source", "cases"})
            for case in group["cases"]:
                with self.subTest(case=case["id"]):
                    changed = case["changed"]
                    self.assertTrue(case["id"].startswith(name + "."))
                    self.assertTrue({"id", "purpose", "cmd", "fixture", "expect", "changed"} <= set(case)
                                    <= {"id", "purpose", "cmd", "stdin", "fixture", "expect", "changed"})
                    self.assertTrue({"description", "cmd", "fixture", "expect_not"} <= set(changed)
                                    <= {"description", "cmd", "stdin", "fixture", "expect_not"})
                    self.assertTrue(case["expect"])
                    self.assertEqual(json.dumps(changed["expect_not"], sort_keys=True),
                                     json.dumps(case["expect"], sort_keys=True))  # "does not give expect"
                    self.assertNotEqual((case["cmd"], case.get("stdin")), (changed["cmd"], changed.get("stdin")))
                    for variant in (case, changed):
                        self.assertTrue(variant["cmd"].startswith("python -m "))
                        self.assertEqual(variant["fixture"], [p[len("/vec/"):] for p in shlex.split(variant["cmd"])
                                                              if p.startswith("/vec/")])
                    ids.append(case["id"])
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(len(ids), 46)

    def test_expected_values_carry_no_floats(self):
        """`tohum/26`: hashed artefacts carry no floats; nor do the vectors' answers (the runner tells 1 from 1.0)."""
        def walk(value):
            if isinstance(value, dict):
                return any(walk(v) for v in value.values())
            if isinstance(value, list):
                return any(walk(v) for v in value)
            return isinstance(value, float)
        for name in DATA_GROUPS:
            for case in self.SEED[name]["cases"]:
                self.assertFalse(walk(case["expect"]), case["id"])

    def test_every_fixture_exists_and_every_fixture_file_is_used(self):
        for name in DATA_GROUPS:
            used = set()
            for case in self.SEED[name]["cases"]:
                for variant in (case, case["changed"]):
                    for rel in variant["fixture"]:
                        self.assertTrue(rel.startswith(name + "/") and (VECTORS / rel).exists(), rel)
                        used.add(rel)
            base = VECTORS / name
            files = [p.relative_to(VECTORS).as_posix() for p in base.rglob("*") if p.is_file()] if base.exists() else []
            for rel in files:
                self.assertTrue(any(rel == u or rel.startswith(u + "/") for u in used), f"{rel} is no case's fixture")

    def test_every_secret_in_the_fixtures_is_marked_fake(self):
        """The `secrets` fixtures are the one place the seed holds secret-shaped strings (.gitignore lets them in):
        each is a made-up value marked FAKE, also inside a decoded ledger row."""
        formats = (re.compile("gh[pousr]_[A-Za-z0-9]{36}"), re.compile("(?:AKIA|ASIA)[A-Z0-9]{16}"))
        found = 0
        for path in sorted((VECTORS / "secrets").iterdir()):
            text = path.read_text(encoding="utf-8")
            texts = [text]
            for line in text.splitlines() if path.suffix == ".jsonl" else []:
                try:
                    texts.append(json.dumps(json.loads(line), ensure_ascii=False))
                except ValueError:
                    pass
            for candidate in texts:
                for fmt in formats:
                    for match in fmt.finditer(candidate):
                        found += 1
                        self.assertIn("FAKE", match.group(0), path.name)
        self.assertGreaterEqual(found, 8)  # one per matching line of the fixtures as written today


class ControlsTest(unittest.TestCase):
    def test_honest_runner_passes(self):
        runner = FakeRunner(VECTORS, commands={"exit 1": (1, b"")})
        self.assertTrue(all(c["ok"] for c in run_controls(runner)))

    def test_always_green_runner_fails(self):
        class Green(FakeRunner):
            def run(self, cmd, **kw):
                from snowball_bootstrap.container import RunResult
                return RunResult(0, b"", b"", 1)
        results = {c["id"]: c["ok"] for c in run_controls(Green(VECTORS))}
        self.assertFalse(results["exit_one"])
        self.assertFalse(results["network_blocked"])
        self.assertFalse(results["source_read_only"])


class SecretScanTest(unittest.TestCase):
    def test_patterns(self):
        fake = "gh" + "p_" + "A" * 36
        self.assertEqual(secretscan.scan(f"token: {fake}"), ["github_token"])
        self.assertEqual(secretscan.scan("-----BEGIN " + "RSA PRIVATE KEY-----"), ["private_key"])
        self.assertEqual(secretscan.scan("nothing here"), [])


if __name__ == "__main__":
    unittest.main()


def spec_allowlist() -> frozenset[str]:
    """The recommended allowlist as `tohum/18a` writes it: the backticked ids before the first ';'."""
    row = next(line for line in POLICY_DEFAULTS.read_text(encoding="utf-8").splitlines()
               if line.startswith("| `license_allowlist` |"))
    return frozenset(re.findall(r"`([^`]+)`", row.split("|")[2].split(";")[0]))


def make_wheel(directory: Path, name: str, headers: list[str], files: dict[str, str] | None = None) -> Path:
    path = directory / f"{name}-1.0-py3-none-any.whl"
    with zipfile.ZipFile(path, "w") as zf:
        meta = "Metadata-Version: 2.4\nName: " + name + "\nVersion: 1.0\n" + "".join(h + "\n" for h in headers)
        zf.writestr(f"{name}-1.0.dist-info/METADATA", meta)
        for rel, text in (files or {}).items():
            zf.writestr(f"{name}-1.0.dist-info/{rel}", text)
    return path


GPL3 = "GNU GENERAL PUBLIC LICENSE\n   Version 3, 29 June 2007\n Everyone is permitted to copy..."
MIT_TEXT = ("Permission is hereby granted, free of charge, to any person obtaining a copy of this software... "
            "The above copyright notice and this permission notice shall be included in all copies.")
PSF_TEXT = ("PYTHON SOFTWARE FOUNDATION LICENSE VERSION 2\n... material that was previously distributed under "
            "the GNU General Public License (GPL), the law of the Commonwealth of Virginia shall govern ...")


class LicenseTest(unittest.TestCase):
    ALLOW = frozenset({"MIT", "Apache-2.0", "BSD-3-Clause", "PSF-2.0"})

    def judge(self, headers, files=None, exceptions=None):
        with tempfile.TemporaryDirectory() as tmp:
            make_wheel(Path(tmp), "pkg", headers, files)
            report = licenses.check_dir(Path(tmp), self.ALLOW, exceptions or {})
        self.assertEqual(len(report), 1)
        return report[0]

    def test_expressions(self):
        for expr, ok in (("MIT", True), ("mit", True), ("MIT OR GPL-3.0-only", True),
                         ("MIT AND GPL-3.0-only", False), ("(MIT OR GPL-3.0-only) AND Apache-2.0", True),
                         ("GPL-3.0-only OR (MIT AND AGPL-3.0-only)", False),
                         ("Apache-2.0 WITH LLVM-exception", True), ("Apache-2.0+", True)):
            self.assertEqual(licenses.allowed(expr, self.ALLOW), ok, expr)
        for bad in ("", "MIT OR", "(MIT", "MIT)", "AND MIT", "MIT GPL-3.0-only"):
            with self.assertRaises(licenses.ExpressionError, msg=bad):
                licenses.allowed(bad, self.ALLOW)

    def test_every_place_that_names_a_license_must_allow(self):
        r = self.judge(["License-Expression: MIT"], {"licenses/LICENSE": MIT_TEXT})
        self.assertEqual((r["expression"], r["allowed"]), ("MIT", True))
        r = self.judge(["License-Expression: MIT",
                        "Classifier: License :: OSI Approved :: GNU General Public License v3 (GPLv3)"])
        self.assertFalse(r["allowed"])
        r = self.judge(["License: MIT"], {"licenses/COPYING": GPL3})
        self.assertFalse(r["allowed"])
        r = self.judge(["Classifier: License :: Other/Proprietary License"])
        self.assertFalse(r["allowed"])

    def test_license_found_only_in_a_file_and_unknown_is_refused(self):
        r = self.judge([], {"licenses/LICENSE": MIT_TEXT})
        self.assertEqual((r["expression"], r["allowed"]), ("MIT", True))
        r = self.judge(["Classifier: License :: OSI Approved :: BSD License"], {"licenses/AUTHORS": "someone"})
        self.assertEqual((r["expression"], r["allowed"]), ("unknown", False))
        r = self.judge(["License: see the website"])
        self.assertEqual((r["expression"], r["allowed"]), ("unknown", False))

    def test_a_mention_is_not_a_license(self):
        r = self.judge(["License-Expression: PSF-2.0"], {"licenses/LICENSE": PSF_TEXT})
        self.assertEqual((r["expression"], r["allowed"]), ("PSF-2.0", True))
        self.assertEqual([s["expression"] for s in r["sources"]], ["PSF-2.0", "PSF-2.0"])

    def test_operator_exception_must_itself_be_allowed(self):
        r = self.judge([], exceptions={"pkg==1.0": "MIT"})
        self.assertEqual((r["basis"], r["allowed"]), ("exception", True))
        r = self.judge([], exceptions={"pkg==1.0": "GPL-3.0-only"})
        self.assertFalse(r["allowed"])
        r = self.judge([], exceptions={"pkg==2.0": "MIT"})
        self.assertEqual((r["expression"], r["allowed"]), ("unknown", False))

    def test_oversized_license_file_is_not_read(self):
        r = self.judge([], {"licenses/LICENSE": MIT_TEXT + " " * licenses.MAX_READ})
        self.assertEqual(r["expression"], "unknown")

    def test_cli_stops_on_a_violation(self):
        from snowball_bootstrap import cli
        with tempfile.TemporaryDirectory() as tmp:
            root, wheels = Path(tmp), Path(tmp) / "w"
            wheels.mkdir()
            (root / "policy.json").write_text(json.dumps({"constitutional": {
                "monthly_cap_usd": 1, "stage_params": {"rival_min_attempts": 1, "repeat_reject_limit": 3},
                "stage_budgets": {"asama_0": {"rival_usd": 1}}, "license_allowlist": ["MIT"],
                "license_exceptions": {}}}))
            argv = ["licenses", "--root", str(root), "--wheels", str(wheels), "--out", str(root / "r.json")]
            self.assertEqual(cli.main(argv), 2)  # no wheels at all is not a pass
            make_wheel(wheels, "good", ["License-Expression: MIT"])
            self.assertEqual(cli.main(argv), 0)
            make_wheel(wheels, "bad", [], {"licenses/LICENSE": GPL3})
            self.assertEqual(cli.main(argv), 2)
            report = json.loads((root / "r.json").read_text())
            self.assertEqual([(r["name"], r["allowed"]) for r in report], [("bad", False), ("good", True)])


class LicensePolicyTest(unittest.TestCase):
    def policy(self, **const):
        from snowball_bootstrap.config import load_policy
        base = {"monthly_cap_usd": 1, "stage_params": {"rival_min_attempts": 1, "repeat_reject_limit": 3},
                "stage_budgets": {"asama_0": {"rival_usd": 1}}, "license_allowlist": ["MIT"],
                "license_exceptions": {}}
        base.update(const)
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "policy.json").write_text(json.dumps({"constitutional": base}))
            return load_policy(Path(tmp))

    def test_allowlist_and_exceptions_are_strict(self):
        from snowball_bootstrap.config import ConfigError
        good = self.policy(license_exceptions={"pkg==1.0": {"expression": "MIT", "evidence": "LICENSE in sdist"}})
        self.assertEqual((good.license_allowlist, good.license_exceptions), (frozenset({"MIT"}), {"pkg==1.0": "MIT"}))
        for bad in ({"license_allowlist": []}, {"license_allowlist": ["MIT OR GPL-3.0-only"]},
                    {"license_exceptions": {"pkg==1.0": {"expression": "MIT"}}},
                    {"license_exceptions": {"Pkg_X==1.0": {"expression": "MIT", "evidence": "x"}}}):
            with self.assertRaises(ConfigError, msg=bad):
                self.policy(**bad)

    def test_a_wheel_that_is_not_allowed_makes_the_run_red(self):
        from snowball_bootstrap.cli import is_green
        ok = [{"ok": True}]
        self.assertTrue(is_green(ok, ok, ok, [{"allowed": True}]))
        self.assertFalse(is_green(ok, ok, ok, [{"allowed": True}, {"allowed": False}]))
        self.assertFalse(is_green(ok, [], ok, []))


class PinnedRequirementLicenseTest(unittest.TestCase):
    """The bootstrap's own pinned wheels: every one has a recorded, allowed license."""

    def test_record_matches_the_lock_file_and_the_spec_allowlist(self):
        allow = spec_allowlist()
        self.assertIn("MIT", allow)
        self.assertNotIn("GPL-3.0-only", allow)
        record = json.loads((BOOTSTRAP / "requirements" / "licenses.json").read_text())["packages"]
        pins = set()
        for req in parse_lockfile((BOOTSTRAP / "requirements" / "sign.txt").read_text()):
            pins.add(f"{re.sub(r'[-_.]+', '-', req.name).lower()}=={req.version}")
        self.assertEqual(pins, set(record))
        for pin, expr in record.items():
            self.assertTrue(licenses.allowed(expr, allow), f"{pin}: {expr}")


class ClaudeCliPinTest(unittest.TestCase):
    """The claude CLI is the one npm package the workflow installs: an exact version, every package by sha512."""

    def test_the_lock_file_pins_one_exact_version_with_integrity(self):
        folder = BOOTSTRAP / "requirements" / "claude-cli"
        pin = json.loads((folder / "package.json").read_text())["dependencies"]
        lock = json.loads((folder / "package-lock.json").read_text())
        main, platform = "@anthropic-ai/claude-code", "@anthropic-ai/claude-code-linux-x64"
        self.assertEqual(sorted(pin), [main, platform])
        version = pin[main]
        self.assertEqual(pin[platform], version)
        self.assertRegex(version, r"^[0-9]+\.[0-9]+\.[0-9]+$")
        self.assertEqual(lock["packages"][""]["dependencies"], pin)
        # npm 12 blocks install scripts unless allowed; without them the binary stays a 500-byte stub
        package = json.loads((folder / "package.json").read_text())
        self.assertEqual(package["allowScripts"], {f"{main}@{version}": True})
        binary = lock["packages"]["node_modules/" + platform]
        # The package holding the real binary is a hard dependency: npm skips an optional package whose digest
        # is wrong (and re-resolves it without the lock), a required one fails the install with EINTEGRITY.
        self.assertFalse(binary.get("optional"))
        self.assertEqual((binary["os"], binary["libc"]), (["linux"], ["glibc"]))
        for path, entry in lock["packages"].items():
            if path:
                self.assertTrue(entry["integrity"].startswith("sha512-"), path)
                self.assertTrue(entry["resolved"].startswith("https://registry.npmjs.org/"), path)
                self.assertEqual(entry["version"], version, path)


class TreeHardeningTest(unittest.TestCase):
    def test_unsafe_member_names_never_reach_the_filesystem(self):
        names = ("..\\..\\x", "C:\\x", "a:b", "/abs", "a/../b", "x\\y")  # a NUL cannot be written into a tar name
        with tempfile.TemporaryDirectory() as tmp:
            for name in names:
                buf = io.BytesIO()
                with tarfile.open(fileobj=buf, mode="w") as tar:
                    info = tarfile.TarInfo(name)
                    info.size = 1
                    tar.addfile(info, io.BytesIO(b"x"))
                with self.assertRaises(TreeError, msg=name):
                    extract(buf.getvalue(), Path(tmp) / "dest" / "tree", 1000)
            self.assertEqual(list(Path(tmp).rglob("x")), [])
            buf = io.BytesIO()  # a legal git member name longer than the file system allows: a TreeError, not a traceback
            with tarfile.open(fileobj=buf, mode="w") as tar:
                info = tarfile.TarInfo("a/" + "b" * 1000)
                info.size = 1
                tar.addfile(info, io.BytesIO(b"x"))
            with self.assertRaises(TreeError):
                extract(buf.getvalue(), Path(tmp) / "long", 1000)


class BootstrapConfigTest(unittest.TestCase):
    BASE = {"brain_repo": "owner/brain", "brain_branch": "main",
            "image": "docker.io/library/python:3.12-slim@sha256:" + "a" * 64,
            "rival": {"model": "claude-sonnet-5-5", "effort": "medium", "max_turns": 30,
                      "per_run_cap_usd_micros": 3_000_000},
            "limits": {"test_timeout_s": 600, "reproducer_timeout_s": 120, "max_prompt_chars": 600_000,
                       "max_tree_bytes": 50_000_000}}

    def load(self, mutate):
        doc = json.loads(json.dumps(self.BASE))
        mutate(doc)
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "bootstrap.json").write_text(json.dumps(doc))
            return load_bootstrap(Path(tmp))

    def test_the_shipped_shape_loads(self):
        boot = self.load(lambda d: None)
        self.assertEqual((boot.rival.model, boot.rival.max_turns, boot.rival.per_run_cap_usd_micros),
                         ("claude-sonnet-5-5", 30, 3_000_000))

    def test_keys_of_the_old_api_design_are_refused_by_name(self):
        for key in ("max_tokens", "price_micros_per_mtok"):
            with self.assertRaisesRegex(ConfigError, f"{key} was removed"):
                self.load(lambda d: d["rival"].update({key: 1}))

    def test_unknown_keys_are_refused_everywhere(self):
        for where, mutate in (("top", lambda d: d.update(api_key="x")),
                              ("rival", lambda d: d["rival"].update(fallback_model="claude-opus-5-5")),
                              ("limits", lambda d: d["limits"].update(extra=1))):
            with self.assertRaisesRegex(ConfigError, "unknown key", msg=where):
                self.load(mutate)

    def test_the_model_must_be_a_full_id(self):
        for model in ("sonnet", "", "  ", "claude-sonnet-5-5[1m]", "gpt-5"):
            with self.assertRaisesRegex(ConfigError, "full model id", msg=model):
                self.load(lambda d: d["rival"].update(model=model))


class SecretScanCoverageTest(unittest.TestCase):
    """Found by a real run: the model read GITHUB_TOKEN-style lines through grep, quoted them in its claims, and
    they went to the provider and into rival.json, because the scan only knew a few shapes."""

    TOK = "A" * 10 + "b" * 10 + "7" * 8

    def test_the_commonest_credential_shapes_are_found(self):
        cases = {
            "generic_assignment": ['GITHUB_TOKEN = "' + self.TOK + '"', "db_password: '" + self.TOK + "'",
                                   '{"password": "' + self.TOK + '"}', "{'api_key': '" + self.TOK + "'}",
                                   "a_very_long_name_" * 4 + "token = '" + self.TOK + "'",
                                   'AWS_SECRET_ACCESS_KEY = "' + "wJalrXUtnFEMI/K7MDENG" + "bPxRfiCY" + '"'],
            "generic_assignment_bare": ["AWS_SECRET_ACCESS_KEY=" + "wJalrXUtnFEMI/K7MDENG" + "bPxRfiCY",
                                        "api_key: " + self.TOK, "TOKEN=" + "0123456789abcdef" * 2],
            "openai_key": ["OPENAI = " + "sk-" + "proj-" + "A" * 40],
            "stripe_key": ["sk_" + "live_" + "A" * 24, "rk_" + "live_" + "A" * 24, "sk_" + "test_" + "A" * 24],
            "google_api_key": ["AI" + "za" + "A" * 35],
            "npm_token": ["npm" + "_" + "A" * 36],
            "jwt": ["ey" + "J" + "A" * 12 + ".ey" + "J" + "A" * 12 + "." + "A" * 12],
            "url_credentials": ["DATABASE_URL=postgres://app:" + "Pa55w0rd" + "Xyz9@db.internal:5432/app",
                                "git+https://builder:" + "ci9Token8Value" + "@example.com/org/repo.git"],
        }
        for name, samples in cases.items():
            for sample in samples:
                self.assertIn(name, secretscan.scan(sample), sample)

    def test_identifiers_numbers_and_lookups_are_not_secrets(self):
        for line in ("token = tokenizer_pretrained_model_name_v2", "secret = get_secret_value_from_vault_1",
                     "token_count = 12345678901234567890", 'api_key = os.environ["API_KEY"]', "max_tokens = 100000",
                     "postgres://user:password@localhost:5432/db", "https://example.com:8080/a/b?c=d",
                     "git@github.com:owner/repo.git", "http://user:pass@localhost/",
                     'password = "changeme"', "password_field = hash_password_with_salt_and_pepper",
                     "SECRET_KEY = config.get('secret_key_name')", "token: Bearer",
                     "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"):
            self.assertEqual(secretscan.scan(line), [], line)

    def test_the_repository_itself_has_no_false_positive(self):
        root = Path(__file__).resolve().parents[3]
        checked = 0
        for base in (root / "seed", root / "spec", root / "README.md"):
            for path in ([base] if base.is_file() else base.rglob("*")):
                parts = path.parts
                if (not path.is_file() or "node_modules" in parts or "__pycache__" in parts or path.stat().st_size > 2_000_000
                        or path.suffix not in (".py", ".md", ".json", ".yml", ".txt", ".cjs")):
                    continue
                checked += 1
                self.assertEqual(secretscan.scan(path.read_text(encoding="utf-8", errors="replace")), [],
                                 str(path.relative_to(root)))
        self.assertGreater(checked, 100)


class SecretScanSpeedTest(unittest.TestCase):
    """V3: a pattern with two open-ended repeats around a keyword took 24 s on 2000 characters of `token` and
    minutes on one long hex line; the diff, whole files and verdicts reach the scan unbounded."""

    def test_hostile_lines_are_scanned_in_linear_time(self):
        hostile = {"keyword run": "token" * 10_000, "name tail": "api_key" * 7_000, "hex line": "0123456789abcdef" * 3_125,
                   "jwt alphabet": "eyJ-" * 50_000, "url prefix": "a://b:c1" * 6_250, "long value": "token=" + "Aa1" * 16_000}
        for label, text in hostile.items():
            started = time.perf_counter()
            secretscan.scan(text)
            self.assertLess(time.perf_counter() - started, 1.0, label)


class SecretScanBoundaryTest(unittest.TestCase):
    def test_a_token_glued_to_other_characters_is_still_a_token(self):
        for text in ("x" + "gh" + "p_" + "A" * 36, "_" + "gh" + "p_" + "A" * 36, "a-" + "AKIA" + "ABCDEFGHIJKLMNOP",
                     "-----BEGIN PGP PRIV" + "ATE KEY BLOCK-----"):
            self.assertNotEqual(secretscan.scan(text), [], text)

    def test_every_whole_string_pattern_rejects_a_trailing_newline(self):
        """V3: `$` matches before a final newline, so `<sha>\n` passed for a sha; `\Z` does not."""
        import re
        from snowball_bootstrap import config, manifest, state as st
        for module in (config, st, manifest):
            for name, value in vars(module).items():
                if isinstance(value, re.Pattern) and value.pattern.startswith("^"):
                    self.assertTrue(value.pattern.endswith("\Z"), f"{module.__name__}.{name}: {value.pattern}")
        self.assertIsNone(st.SHA_RE.match("a" * 40 + chr(10)))
        self.assertIsNotNone(st.SHA_RE.match("a" * 40))

    def test_a_jwt_shape_inside_a_longer_word_is_not_one(self):
        jwt = "ey" + "J" + "A" * 12 + ".ey" + "J" + "A" * 12 + "." + "A" * 12
        self.assertIn("jwt", secretscan.scan(" " + jwt))
        self.assertNotIn("jwt", secretscan.scan("x" + jwt))
