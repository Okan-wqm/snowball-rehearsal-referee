"""`kos` in parts (E440): the parts and their join write the single job's `run.json`, byte for byte.

The differential: the same fixture push through `run-tests` (the single job) and through `run-part K/N` for every K,
each in its own work directory with its own sandbox, then `join-parts` over the packed artifacts and their hashes, for
several N. `run.json` and the signed result `decide` makes of it must be the same bytes. Every Stage 0 group runs, with
answers right, wrong, silent, killed once, timed out, unparseable, nested too deep, noisy and docker failures, and
module-less red is spread over the parts. Then the join is handed parts that do not add up: a part's records dropped,
duplicated, reordered, swapped, from another push or plan, a part's sandbox that failed its controls, module-less
runs left out on a green push. Each one stops the join (an outage), or, for a failed sandbox, gives the single job's
run on that sandbox.
"""

import copy
import hashlib
import json
import shutil
import tempfile
import unittest
from collections import Counter
from pathlib import Path

from snowball_bootstrap import canon, cli, parts, stages, vectors
from snowball_bootstrap.container import RunResult
from snowball_bootstrap.decide import decide

from helpers import FakeRunner

BOOT = Path(__file__).resolve().parents[1]
VECTORS = BOOT / "vectors"
SEED = json.loads((VECTORS / "vectors.json").read_text(encoding="utf-8"))
TABLE = stages.load(0)
A, B = "a" * 40, "b" * 40
NOW = "2026-11-01T00:00:00Z"
MODULE_LESS = [3, 4, 18]  # six module-less runs, so every part count below has some and some parts none
FLAVOURS = ("right", "right", "right", "right", "wrong", "silent", "killed_once", "hangs", "not_json", "deep",
            "noisy", "list")


def _answers():
    """What an honest brain prints for each data input: every field a changed input must answer, each different from
    `expect_not`, then the `expect` of every case whose input it is (an input is often another case's changed input,
    E273; the seed's expected values never ask one answer to be both)."""
    avoid, expect = {}, {}
    for group in SEED.values():
        if not (isinstance(group, dict) and group.get("runner") == "data"):
            continue
        for case in group["cases"]:
            expect.setdefault((case["cmd"], case.get("stdin", "").encode("utf-8")), {}).update(case["expect"])
            changed = case["changed"]
            other = {k: ["not", v] for k, v in changed["expect_not"].items()}
            avoid.setdefault((changed["cmd"], changed.get("stdin", "").encode("utf-8")), {}).update(other)
    return {key: dict(avoid.get(key, {}), **expect.get(key, {})) for key in list(expect) + list(avoid)}


ANSWERS = _answers()


def flavour(cmd, stdin, scenario):
    if scenario["vectors"] == "honest":
        return "right"
    digest = hashlib.sha256(cmd.encode("utf-8") + b"\0" + stdin).digest()
    return FLAVOURS[int.from_bytes(digest[:4], "big") % len(FLAVOURS)]


class Sandbox:
    """One part's sandbox: a container that answers the vector interface, the declared tests and the red controls by
    the scenario. It counts its own attempts, as a real sandbox would kill only its own first try."""

    def __init__(self, vec, src, scenario, broken=False, part=0):
        self.vec, self.src, self.scenario, self.broken, self.part = Path(vec), Path(src), scenario, broken, part
        self.reference = FakeRunner(Path(vec))
        self.tries = Counter()

    def run(self, cmd, *, cwd=".", stdin=b"", timeout_s):
        self.tries[(cmd, stdin)] += 1
        if cmd == "exit 0":
            return RunResult(0, b"", b"", 2)
        if cmd == "exit 1":
            return RunResult(1, b"", b"", 2)
        if "socket.create_connection" in cmd:
            return RunResult(0 if self.broken else 1, b"", b"OSError: [Errno 101] Network is unreachable", 2)
        if cmd.startswith("touch /src/"):
            return RunResult(1, b"", b"touch: Read-only file system", 2)
        if cmd.startswith("python -m unittest t"):
            number = int(cmd.rsplit("t", 1)[1])
            without = "module-less" in self.src.parts
            failing = number in self.scenario.get("failing_tests", ()) or (without and not self.scenario.get("lazy"))
            return RunResult(1 if failing else 0, f"T{number}\n".encode(), f"Ran 1 test in 0.{number:03d}s\n".encode(),
                             1000 + number)
        kind = flavour(cmd, stdin, self.scenario)
        if kind == "silent":
            return RunResult(1, b"", b"Traceback (most recent call last): boom", 3)
        if kind == "killed_once" and self.tries[(cmd, stdin)] == 1:
            return RunResult(137, b"", b"Killed", 3)
        if kind == "hangs":
            return RunResult(124, b"", b"", timeout_s * 1000, timed_out=True)
        if kind == "not_json":
            return RunResult(0, b"{not json\n", b"", 3)
        if kind == "deep":
            return RunResult(0, b'{"ok": ' + b"[" * 100_000 + b"]" * 100_000 + b"}\n", b"", 3)
        if kind == "list":
            return RunResult(0, b"[1, 2]\n", b"", 3)
        if (cmd, stdin) in ANSWERS:
            answer = ANSWERS[(cmd, stdin)]
        else:
            res = self.reference.run(cmd, cwd=cwd, stdin=stdin, timeout_s=timeout_s)  # `chain`: the reference
            if not res.ok or (self.scenario.get("docker") and "verify" in cmd):
                return RunResult(125 if self.scenario.get("docker") else res.exit_code, b"", b"docker: Error", 3)
            answer = json.loads(res.stdout)
        if kind == "wrong":
            answer = {k: ["wrong", v] for k, v in answer.items()}
        if kind == "noisy":  # progress lines, blank lines, the fields in reverse order: only the last line counts
            line = json.dumps(dict(reversed(list(answer.items()))))
            return RunResult(0, f"progress 1/2\n\n{line}\n  \n".encode(), b"warning: noisy", 3)
        return RunResult(0, (json.dumps(answer) + "\n").encode(), b"", 3)


def manifest():
    """Every Stage 0 micro-feature done with its declared tests, and one Stage 1 test that `kos` never runs."""
    tests = [{"id": f"T{n}", "cmd": f"python -m unittest t{n}", "stage": 0} for f in TABLE.mfs for n in f.tests]
    tests.append({"id": "T99", "cmd": "python -m unittest t99", "stage": 1})
    return {"tests": tests, "done_mf": list(range(1, TABLE.count + 1)), "lockfiles": []}


class Push:
    """A referee snapshot, a pulled push and empty wheels on disk, as the workflow's jobs unpack them."""

    def __init__(self, base: Path, meta: dict):
        self.base = base
        self.root, self.pulled, self.deps = base / "snap", base / "pulled", base / "deps"
        self.root.mkdir()
        shutil.copytree(VECTORS, self.root / "vectors")
        (self.root / "bootstrap.json").write_text(json.dumps({
            "brain_repo": "owner/brain", "brain_branch": "main",
            "image": "docker.io/library/python:3.12-slim@sha256:" + "a" * 64,
            "rival": {"model": "claude-sonnet-5-5", "effort": "medium", "max_turns": 30, "per_run_cap_usd_micros": 1},
            "limits": {"test_timeout_s": 600, "reproducer_timeout_s": 120, "max_prompt_chars": 600_000,
                       "max_tree_bytes": 50_000_000}}), encoding="utf-8")
        (self.root / "policy.json").write_text(json.dumps({"constitutional": {
            "monthly_cap_usd": 300, "stage_params": {"rival_min_attempts": 2, "repeat_reject_limit": 3},
            "stage_budgets": {"asama_0": {"rival_usd": 30}}, "license_allowlist": ["MIT"], "license_exceptions": {}}}),
            encoding="utf-8")
        tree = base / "tree"
        pages = {g["interface"] for g in SEED.values() if isinstance(g, dict) and g.get("interface")}
        for rel in sorted(pages) + [f"referee/{f.module}" for f in TABLE.mfs] + ["referee/other.py"]:
            (tree / rel).parent.mkdir(parents=True, exist_ok=True)
            (tree / rel).write_text("x = 1\n", encoding="utf-8")
        self.pulled.mkdir()
        cli.pack_dir(tree, self.pulled / "brain.tar")
        self.meta = meta
        (self.pulled / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
        self.deps.mkdir()
        self.n = 0

    def args(self, *extra):
        self.n += 1
        work = self.base / f"work{self.n}"
        return ["--root", str(self.root), "--pulled", str(self.pulled), "--deps", str(self.deps), "--work", str(work),
                *extra]


class PartsTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.push = Push(Path(self.tmp.name), {
            "head": B, "base": A, "kind": "code", "manifest": manifest(), "module_less": MODULE_LESS})
        self.sandboxes = []
        self.broken_part = None
        self.current_part = 0
        real = cli._runner
        self.addCleanup(setattr, cli, "_runner", real)
        cli._runner = self.make_runner
        self.scenario = {"vectors": "honest"}

    def make_runner(self, boot, src, deps, vec, locks):
        sandbox = Sandbox(vec, src, self.scenario, broken=self.current_part == self.broken_part, part=self.current_part)
        self.sandboxes.append(sandbox)
        return sandbox

    def single(self):
        out = Path(self.tmp.name) / f"single{len(self.sandboxes)}"
        self.current_part = 0
        self.assertEqual(cli.main(["run-tests", *self.push.args("--out", str(out))]), 0)
        return (out / "run.json").read_bytes()

    def part_records(self, count):
        """Every part run as its own job: own work directory, own sandbox; its artifact packed with its hash."""
        packed = []
        for k in range(count):
            self.current_part = k
            out = Path(self.tmp.name) / f"part{count}-{k}-{len(self.sandboxes)}"
            self.assertEqual(cli.main(["run-part", "--part", f"{k}/{count}", *self.push.args("--out", str(out))]), 0)
            tar = out.parent / f"{out.name}.tar"
            packed.append((tar, cli.pack_dir(out, tar)))
        return packed

    def joined(self, packed, expect_rc=0):
        out = Path(self.tmp.name) / f"joined{len(self.sandboxes)}-{id(packed)}"
        argv = ["join-parts", *self.push.args("--out", str(out))]
        for tar, sha in packed:
            argv += ["--part", f"{tar}={sha}"]
        self.assertEqual(cli.main(argv), expect_rc)
        return (out / "run.json").read_bytes() if expect_rc == 0 else None

    def signed(self, run_bytes):
        meta = dict(self.push.meta, state={
            "schema": "snowball-bootstrap-state/4", "origin": "artifact", "last_accepted_sha": A,
            "last_evaluated_sha": None, "frozen_specs": {}, "rival_artifacts": [], "month": "2026-11",
            "month_spend_usd_micros": 0, "stage_spend_usd_micros": 0, "runs": 1, "reject_streaks": {},
            "repeat_events": 0, "outage_sha": None, "outage_count": 0, "outage_since": None, "outage_stop": None,
            "rival_side_streak": 0, "open_refutations": [], "open_claims": [], "pending_rival": None,
            "rejected_exit_request": None, "exit_accepted_sha": None},
            changed=[], pre_reasons=[], evaluate=True, run_tests=True, run_rival=True, exit_request=None,
            referee_tree_sha256=None, spec_dir_hashes={})
        rival = {"verdict": "not_refuted", "attempts": [], "reasons": [], "cost_usd_micros": 7, "reproducer_count": 0}
        jobs = {"getir": "success", "kos": "success", "cagir": "success", "yeniden": "skipped"}
        return canon.dump(decide(meta, json.loads(run_bytes), rival, [], jobs, 2, 3, now=NOW)).encode("utf-8")


class DifferentialTest(PartsTestCase):
    """The same push, the single job against N parts: the same `run.json` and the same signed result, byte for byte."""

    def same(self, counts=(2, 4)):
        single = self.single()
        run = json.loads(single)
        for count in counts:
            with self.subTest(parts=count):
                joined = self.joined(self.part_records(count))
                self.assertEqual(joined, single)
                self.assertEqual(self.signed(joined), self.signed(single))
        return run

    def test_an_honest_push_is_the_same_green_run_with_module_less_red_spread_over_the_parts(self):
        run = self.same(counts=(2, 3, 7))
        self.assertTrue(run["green"])
        self.assertEqual(len(run["vectors"]), 2 * sum(len(g["cases"]) for g in SEED.values()
                                                      if isinstance(g, dict) and g.get("runner") == "data") + 6)
        self.assertEqual([t["id"] for t in run["tests"]], [t["id"] for t in manifest()["tests"] if t["stage"] == 0])
        self.assertEqual([(m["mf"], m["test_id"]) for m in run["module_less"]],
                         [(k, f"T{n}") for k in MODULE_LESS for n in TABLE.feature(k).tests])
        self.assertTrue(all(not m["stayed_green"] for m in run["module_less"]))
        self.assertEqual(json.loads(self.signed(json.dumps(run)))["verdict"], "accepted")

    def test_every_way_a_call_answers_is_judged_the_same(self):
        self.scenario = {"vectors": "mixed"}
        run = self.same()
        details = " ".join(v["detail"] for v in run["vectors"])
        for seen in ("timed out", "no answer: exit 1", "no JSON object", "got "):
            self.assertIn(seen, details)
        self.assertTrue(any(v["ok"] for v in run["vectors"]) and not all(v["ok"] for v in run["vectors"]))
        self.assertEqual(run["module_less"], [])  # red: the single job spares module-less red, and so do the parts
        self.assertEqual([s for s in self.sandboxes if "module-less" in s.src.parts], [])  # each part saw red
        reasons = json.loads(self.signed(json.dumps(run)))["reasons"]
        self.assertTrue(any(r["kind"] == "vector_failed" for r in reasons))

    def test_a_failing_test_a_lazy_module_and_a_docker_fault_are_the_same(self):
        self.scenario = {"vectors": "honest", "failing_tests": (38, 45)}
        self.assertEqual([t["id"] for t in self.same(counts=(3,))["tests"] if not t["ok"]], ["T38", "T45"])
        self.scenario = {"vectors": "honest", "lazy": True}
        self.assertTrue(all(m["stayed_green"] for m in self.same(counts=(3,))["module_less"]))
        self.scenario = {"vectors": "honest", "docker": True}
        self.assertTrue(any(v["runner_fault"] for v in self.same(counts=(3,))["vectors"]))

    def test_a_part_whose_sandbox_fails_its_controls_is_the_single_job_on_that_sandbox(self):
        self.broken_part = 0
        single = self.single()  # the single job on a sandbox that lets the network through
        run = json.loads(single)
        self.assertEqual((run["tests"], run["vectors"], run["module_less"], run["green"]), ([], [], [], False))
        for count, broken in ((3, 2), (4, 1)):
            self.broken_part = broken  # one part's sandbox, the others behave
            self.assertEqual(self.joined(self.part_records(count)), single)
        self.assertEqual([r["ref"] for r in json.loads(self.signed(single))["reasons"]], ["kos:network_blocked"])

    def test_the_single_job_is_the_plain_vector_run(self):
        """N=1 is the old single job: its records are those `run_vectors` writes running every call itself."""
        self.scenario = {"vectors": "mixed"}
        run = json.loads(self.single())
        src = Path(self.tmp.name) / "plain"
        cli.extract((self.push.pulled / "brain.tar").read_bytes(), src, 50_000_000)
        plain = vectors.run_vectors(Sandbox(VECTORS, src, self.scenario), self.push.root / "vectors",
                                    tuple(range(1, TABLE.count + 1)), tree=src)
        self.assertEqual(run["vectors"], json.loads(json.dumps(plain)))

    def test_each_input_is_asked_by_one_part_once_and_the_parts_share_the_calls(self):
        self.part_records(4)
        asked, by_part = Counter(), Counter()
        for sandbox in self.sandboxes:
            for (cmd, stdin), tries in sandbox.tries.items():
                if not cmd.startswith(("exit ", "python -c", "touch ", "python -m unittest")):
                    asked[(cmd, stdin)] += tries
                    by_part[sandbox.part] += tries
        groups = vectors.applied(VECTORS, tuple(range(1, TABLE.count + 1)))
        self.assertEqual(len(asked), len(set(vectors.call_inputs(groups))))  # every input of the push, and no other
        self.assertEqual(set(asked.values()), {1})  # honest answers: each once, in one part only
        self.assertEqual(sorted(by_part), [0, 1, 2, 3])
        self.assertLessEqual(max(by_part.values()) - min(by_part.values()), 1)  # place mod 4: a quarter each


class JoinRefusesTest(PartsTestCase):
    """What a part reports is held against what the join computes itself: any gap stops it."""

    def records(self, count=3):
        return [json.loads(cli.tar_file(Path(tar).read_bytes(), "part.json")) for tar, _ in self.part_records(count)]

    def kos(self):
        return cli._kos(cli.build_parser().parse_args(["join-parts", *self.push.args("--out", "unused")]))

    def refused(self, records, message):
        with self.assertRaisesRegex(parts.PartError, message):
            parts.join(self.kos().push, records)

    def test_the_untouched_records_join_and_any_dropped_duplicated_or_reordered_answer_stops_the_join(self):
        records = self.records()
        self.assertTrue(parts.join(self.kos().push, copy.deepcopy(records))["green"])
        dropped = copy.deepcopy(records)
        del dropped[1]["tape"][3]
        self.refused(dropped, "part 1 of 3 does not hold vector call")
        duplicated = copy.deepcopy(records)
        duplicated[2]["tape"].append(duplicated[2]["tape"][-1])
        self.refused(duplicated, "part 2 of 3 reported 1 vector call not its own")
        reordered = copy.deepcopy(records)
        tape = reordered[0]["tape"]
        tape[0], tape[1] = tape[1], tape[0]
        self.refused(reordered, "part 0 of 3 does not hold vector call 0")
        moved = copy.deepcopy(records)
        moved[1]["tape"].append(moved[0]["tape"].pop())
        self.refused(moved, "part 0 of 3 does not hold vector call")
        answer = copy.deepcopy(records)
        answer[0]["tape"][0]["exit"] = True
        self.refused(answer, "a tape entry is not")

    def test_a_part_that_is_another_part_or_of_another_push_stops_the_join(self):
        records = self.records()
        self.refused([records[1], records[0], records[2]], "part 0 of 3 holds the record of part 1 of 3")
        self.refused(records[:2], "part 0 of 2 holds the record of part 0 of 3")
        other = copy.deepcopy(records)
        other[2]["head"] = A
        self.refused(other, "part 2 ran another push")
        plan = copy.deepcopy(records)
        plan[1]["plan_sha256"] = "0" * 64
        self.refused(plan, "part 1 ran another push or another plan")
        self.refused([], "0 parts")

    def test_a_test_record_dropped_duplicated_or_out_of_place_stops_the_join(self):
        records = self.records()
        dropped = copy.deepcopy(records)
        dropped[0]["tests"].pop()
        self.refused(dropped, "part 0 of 3 does not hold test")
        extra = copy.deepcopy(records)
        extra[1]["tests"].append(extra[1]["tests"][0])
        self.refused(extra, "part 1 of 3 reported 1 test not its own")
        swapped = copy.deepcopy(records)
        swapped[0]["tests"][0], swapped[1]["tests"][0] = swapped[1]["tests"][0], swapped[0]["tests"][0]
        self.refused(swapped, "does not hold test 0")

    def test_module_less_runs_left_out_or_misplaced_on_a_green_push_stop_the_join(self):
        records = self.records()
        spared = copy.deepcopy(records)
        spared[1]["module_less"] = None
        self.refused(spared, "left out its module-less runs, yet the push is green")
        dropped = copy.deepcopy(records)
        dropped[2]["module_less"].pop()
        self.refused(dropped, "part 2 of 3 does not hold module-less run")
        reordered = copy.deepcopy(records)
        reordered[0]["module_less"].reverse()
        self.refused(reordered, "part 0 of 3 does not hold module-less run")

    def test_sandboxes_that_answer_the_controls_differently_stop_the_join(self):
        records = self.records()
        records[2]["controls"][1]["exit"] = 2  # still a passing control, but not the answer the other sandboxes gave
        self.refused(records, "answered the red controls differently")

    def test_join_parts_reads_an_artifact_only_by_its_hash_and_a_missing_part_stops_it(self):
        packed = self.part_records(2)
        self.joined(packed)
        tar, sha = packed[1]
        with self.assertRaisesRegex(SystemExit, "artifact hash mismatch"):
            self.joined([packed[0], (tar, "0" * 64)])
        self.joined([packed[0], (tar, "")], expect_rc=2)  # its job output never came: the part did not finish
        self.joined([packed[0], (Path(self.tmp.name) / "nothing.tar", sha)], expect_rc=2)
        self.joined([packed[0]], expect_rc=2)  # part 0 of 1, but the record is part 0 of 2

    def test_a_part_is_k_of_n(self):
        self.assertEqual(parts.part_of("3/4"), (3, 4))
        for bad in ("4/4", "-1/4", "0/0", "1", "a/b", f"0/{parts.MAX_PARTS + 1}"):
            with self.assertRaises(parts.PartError, msg=bad):
                parts.part_of(bad)


PROBE_TABLE = stages.parse_table(json.dumps({"stage": 0, "mfs": [
    {"mf": 1, "tests": [13], "groups": ["probe"], "module": "probe/x.py", "calls": []}]}), 0)


class ReplayTest(unittest.TestCase):
    """The join's judges take each answer only for its own call, in the judges' order, and every answer is asked for."""

    def test_a_tape_is_replayed_only_call_by_call(self):
        cases = [{"id": f"probe.c{i}", "purpose": "p", "cmd": f"python -m probe.x {i}", "fixture": [],
                  "expect": {"n": i}, "changed": {"description": "d", "cmd": f"python -m probe.x {i + 1}",
                                                  "fixture": [], "expect_not": {"n": i}}} for i in range(3)]

        class Echo:
            def run(self, cmd, *, cwd=".", stdin=b"", timeout_s):
                n = int(cmd.rsplit(" ", 1)[1])
                return RunResult(n % 2, (json.dumps({"n": n}) + "\n").encode(), b"", 1)
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "vectors.json").write_text(json.dumps(
                {"probe": {"owner": "asama-0", "runner": "data", "cases": cases}}), encoding="utf-8")
            groups = vectors.applied(Path(tmp), (1,), table=PROBE_TABLE)
            plain = vectors.run_vectors(Echo(), Path(tmp), (1,), table=PROBE_TABLE)
        tape, known = vectors.run_part(Echo(), groups, set(vectors.call_inputs(groups)))
        self.assertEqual(vectors.replay(tape, groups), plain)
        self.assertEqual(known, plain)  # one part owning every input is the single job
        self.assertEqual([r["exit"] for r in plain], [0, 1, 1, 0, 0, 1])  # the cases share inputs: each its own exit
        swapped = list(tape)
        swapped[0], swapped[1] = swapped[1], swapped[0]
        for wrong, message in ((swapped, "call 0 of the judges"), (tape[:-1], "call 5 of the judges"),
                               (tape + tape[-1:], "answered 1 calls the judges never make")):
            with self.assertRaisesRegex(vectors.TapeError, message):
                vectors.replay(wrong, groups)


class PartBudgetTest(unittest.TestCase):
    """The vectors' budget is a part's: every part is its own job with its own timeout (E440)."""

    TABLE = PROBE_TABLE

    def test_each_part_spends_its_own_budget(self):
        from unittest import mock
        cases = [{"id": f"probe.c{i}", "purpose": "p", "cmd": f"python -m probe.x {i}", "fixture": [],
                  "expect": {"ok": True}, "changed": {"description": "d", "cmd": f"python -m probe.x -{i}",
                                                       "fixture": [], "expect_not": {"ok": True}}} for i in range(30)]
        clock = [0.0]

        class Hangs:
            def __init__(self):
                self.calls = 0

            def run(self, cmd, *, cwd=".", stdin=b"", timeout_s):
                self.calls += 1
                clock[0] += timeout_s
                return RunResult(124, b"", b"", timeout_s * 1000, timed_out=True)
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(vectors, "_now", lambda: clock[0]):
            Path(tmp, "vectors.json").write_text(json.dumps(
                {"probe": {"owner": "asama-0", "runner": "data", "cases": cases}}), encoding="utf-8")
            groups = vectors.applied(Path(tmp), (1,), table=self.TABLE)
            inputs = list(dict.fromkeys(vectors.call_inputs(groups)))
            spent = []
            for k in range(3):
                runner = Hangs()
                tape, _known = vectors.run_part(runner, groups, {key for i, key in enumerate(inputs) if i % 3 == k})
                spent.append(runner.calls)
                self.assertIn("not_run:time_budget", tape[-1]["fault"])
        self.assertEqual(spent, [vectors.BUDGET_S // 120] * 3)  # a third of the inputs each, each part its own 1200 s


if __name__ == "__main__":
    unittest.main()
