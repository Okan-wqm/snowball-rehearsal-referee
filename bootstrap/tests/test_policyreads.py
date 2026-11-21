"""The loop's reads of `policy.json`, asked of the loop itself (`tohum/29v`; the Founder's report seed-053, E588).

The seed's fixtures hold every `18a` and `18b` key under its section, and the hoisted copy the same file with the
stage's required paths moved to the top level; `required.json` is `18a`'s readers, derived here from the page. `kos` runs
``python -m policy.reads`` over both; the judge holds each named path to the fixture; the join takes the run from the map
owner's part; `decide` warns in Stage 0 and rejects from Stage 1. The Founder's canary at 91bbd27 (the cap read at the
top level, its tests agreeing with its code) is red here, and the seed's reference answer is clean.
"""

import json
import re
import unittest
from pathlib import Path

import test_decision
import test_flow
from snowball_bootstrap import cli, parts, policyreads, stages
from snowball_bootstrap.container import RunResult
from snowball_bootstrap.decide import counts_against_founder, decide
from test_decision import CODE_JOBS, green_run, meta_, not_refuted, state0
from test_reference_brain import BRAIN, LocalRunner

from helpers import FakeRunner

BOOT = Path(__file__).resolve().parents[1]
ROOT = BOOT.parents[1]
VECTORS = BOOT / "vectors"
FIXTURES = VECTORS / policyreads.FIXTURE_DIR
PLAN = policyreads.plan(VECTORS, 0)
CANARY = "constitutional.stage_budgets.asama_0.canary_usd"
LOOP_TOOLS = ("llm.call", "profile.derive", "deps.fetch", "run.contained", "unit.verify")  # Stage 0's loop readers


def page(prefix):
    [found] = sorted((ROOT / "spec" / "tohum").glob(f"{prefix}-*.md"))
    return found.read_text(encoding="utf-8")


def key_rows(prefix):
    """``(full paths, row)`` of every row of the page's key tables: the first cell's backticked paths, a bare sibling
    (`K2` after `constitutional.class_floors.K1`) completed from the path before it."""
    rows = []
    for line in page(prefix).splitlines():
        if not line.startswith("| `"):
            continue
        first = line.split(" | ")[0]
        paths = []
        for token in re.findall(r"`([^`]+)`", first):
            paths.append(token if "." in token else paths[-1].rsplit(".", 1)[0] + "." + token)
        rows.append((paths, line))
    return rows


def reads_of(doc, paths):
    """What a loop that reads ``paths`` (walking each from the top) answers over ``doc``."""
    return {p: (lambda v: None if v is policyreads._ABSENT else v)(policyreads.at(doc, p.split("."))) for p in paths}


def answer(line, code=0, timed_out=False, err=b""):
    out = (line if isinstance(line, bytes) else json.dumps(line).encode()) + b"\n"
    return policyreads._record(RunResult(code, out, err, 1, timed_out))


def record(first, second=None):
    return {"runs": [first, second or answer({})]}


def loop(reader):
    """The record of a loop whose reads are ``reader(doc)`` over each fixture."""
    return record(answer(reader(PLAN["full"])), answer(reader(PLAN["hoisted"])))


def names(found):
    return sorted((name, path) for name, path, _detail in found)


class FixtureTest(unittest.TestCase):
    """The fixtures are `26b`'s shape with every key of `18a` and `18b`, and `required.json` is `18a`'s readers."""

    def test_every_key_the_pages_write_is_a_full_path_in_the_fixture(self):
        # policy_key_column_loses_its_section
        self.assertEqual(sorted(PLAN["full"]), sorted(policyreads.SECTIONS))
        seen = 0
        for prefix, section in (("18a", None), ("18b", "performance")):
            for paths, row in key_rows(prefix):
                for path in paths:
                    seen += 1
                    with self.subTest(path=path):
                        self.assertIn(path.split(".")[0], policyreads.SECTIONS, row)
                        if section:
                            self.assertTrue(path.startswith(section + "."), row)
                        self.assertIsNot(policyreads.at(PLAN["full"], path.split(".")), policyreads._ABSENT)
        self.assertGreater(seen, 60)
        rule = " ".join(page("18a").split())
        self.assertIn("Anahtar sütunu her anahtarı bölümüyle, tam yoluyla yazar; başka sayfada bölümsüz geçen ad bu "
                      "yoldur (`29v`).", rule)

    def test_the_required_paths_are_18as_rows_a_stage_0_loop_tool_reads(self):  # required_json_drifts_from_18a
        """Every constitutional row whose readers name a Stage 0 loop tool, and every `operating` row (`18a` names
        `run.contained`, `unit.verify` and `deps.fetch` as their readers): a new such row without its path here is red
        in the seed, the class seed-053 named."""
        text = page("18a")
        self.assertIn("`run.contained`, `unit.verify` ve `deps.fetch`'tir", " ".join(text.split()))
        derived = set()
        for paths, row in key_rows("18a"):
            readers = row.rsplit(" | ", 1)[-1]
            if paths[0].startswith("operating.") or any(f"`{tool}`" in readers for tool in LOOP_TOOLS):
                derived.update(paths)
        rows = json.loads((FIXTURES / policyreads.REQUIRED).read_text(encoding="utf-8"))
        self.assertEqual(sorted(rows), ["0", "1"])
        self.assertEqual(sorted(rows["0"]), sorted(derived))
        self.assertIn(CANARY, derived)
        self.assertEqual(len(derived), 11)
        self.assertEqual(PLAN["required"], sorted(derived))
        self.assertEqual(policyreads.required_paths({"0": ["operating.a"], "1": ["operating.b"]}, 0), ["operating.a"])
        self.assertEqual(policyreads.required_paths({"0": ["operating.a"], "1": ["operating.b"]}, 1),
                         ["operating.a", "operating.b"])
        for bad in ([], {"x": []}, {"0": ["stage_budgets.asama_0.canary_usd"]}, {"0": "operating.a"}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                policyreads.required_paths(bad, 0)

    def test_stage_1_reads_the_harness_keys_29v_names(self):  # required_stage_1_row_dropped required_gozcu_path_dropped
        """seed-076 (independent review panel, 2026-11-20): Stage 1's row is the harness's five keys, each a row of
        `18a`, named on `29v`; a stage reads the rows before it too. seed-084 (2026-11-21, epoch AA): the watcher's
        seven keys join it, each a row of `18a` or `18b`."""
        rows = json.loads((FIXTURES / policyreads.REQUIRED).read_text(encoding="utf-8"))
        five = ["constitutional.confidence_level", "constitutional.stage_params.census_min_groups",
                "constitutional.stage_params.evidence_ref_max_lines", "constitutional.stage_params.match_window_lines",
                "constitutional.stage_params.planted_max_cases"]
        seven = ["constitutional.gate_rules.soft_freeze_limit", "constitutional.monthly_cap_usd",
                 "constitutional.regression_freeze.min_merges", "constitutional.regression_freeze.min_reverts",
                 "constitutional.regression_freeze.revert_rate", "constitutional.regression_freeze.window_days",
                 "performance.windows.measure"]
        self.assertEqual(sorted(rows["1"]), sorted(five + seven))
        keyed = {path for prefix in ("18a", "18b") for paths, _row in key_rows(prefix) for path in paths}
        self.assertTrue(set(five + seven) <= keyed)
        self.assertEqual(policyreads.required_paths(rows, 1), sorted(set(rows["0"]) | set(five) | set(seven)))
        self.assertEqual(policyreads.required_paths(rows, 0), sorted(rows["0"]))
        said = " ".join(page("29v").split())
        self.assertIn("Aşama 1'in satırı (bağımsız inceleme ekibi kararı, 2026-11-20, seed-076) harness'in beş yoludur", said)
        self.assertIn("**Gözcü'nün yolları** (bağımsız inceleme ekibi kararı (2026-11-21), seed-084). AA döneminden "
                      "Aşama 1'in satırında Gözcü'nün yedi yolu da vardır", said)
        self.assertIn("teslimden itibaren onlar da okunması zorunlu yollardır", said)
        for path in five + seven:
            self.assertIsNot(policyreads.at(PLAN["full"], path.split(".")), policyreads._ABSENT, path)

    def test_the_fixtures_hold_no_float(self):  # fixture_float_kept
        """seed-082 (2026-11-21, epoch AA): `policy.json` holds no float anywhere (`01c` "Politikanın sayıları"); a
        fraction is a string of an integer part, a point and exactly six decimals, in both fixtures."""
        fraction = re.compile(r"(0|[1-9][0-9]*)\.[0-9]{6}")

        def walk(value, where):
            self.assertNotIsInstance(value, float, where)
            if isinstance(value, dict):
                for key, item in value.items():
                    walk(item, f"{where}.{key}")
            elif isinstance(value, list):
                for i, item in enumerate(value):
                    walk(item, f"{where}[{i}]")
        for name in (policyreads.FULL, policyreads.HOISTED):
            raw = (FIXTURES / name).read_text(encoding="utf-8")
            walk(json.loads(raw), name)
            self.assertNotRegex(raw, r":\s*-?[0-9]+[.eE]")  # no JSON number with a point or an exponent
        for path in ("constitutional.confidence_level", "constitutional.regression_freeze.revert_rate",
                     "constitutional.stage_params.fix_acceptance_min", "performance.rules.drift_bound"):
            with self.subTest(path=path):
                self.assertRegex(policyreads.at(PLAN["full"], path.split(".")), fraction)

    def test_the_hoisted_file_moves_each_required_path_to_the_top_with_another_value(self):
        # fixture_decoy_equals_the_section_value gozcu_decoy_equals_section
        full, hoisted = PLAN["full"], PLAN["hoisted"]
        stage1 = policyreads.plan(VECTORS, 1)  # seed-076: Stage 1's five paths are hoisted too, so a fallback shows
        self.assertTrue(set(PLAN["required"]) < set(stage1["required"]))
        for path in stage1["required"]:
            keys = path.split(".")
            with self.subTest(path=path):
                self.assertIs(policyreads.at(hoisted, keys), policyreads._ABSENT)
                decoy = policyreads.at(hoisted, keys[1:])
                self.assertIsNot(decoy, policyreads._ABSENT)
                self.assertFalse(policyreads._same(decoy, policyreads.at(full, keys)))
                self.assertEqual(type(decoy), type(policyreads.at(full, keys)))
        rest = {k: v for k, v in hoisted.items() if k in policyreads.SECTIONS}
        for path in PLAN["required"]:
            keys = path.split(".")
            parent = policyreads.at(full, keys[:-1])
            self.assertIn(keys[-1], parent)
        self.assertEqual(sorted(rest), sorted(policyreads.SECTIONS))
        # the sectioned licence lists and keywords are not the loop's built-in defaults (`18a`'s list, an empty one)
        allow = policyreads.at(full, ["constitutional", "license_allowlist"])
        self.assertNotIn("MPL-2.0", allow)
        self.assertTrue(policyreads.at(full, ["constitutional", "license_exceptions"]))

    def test_the_fixtures_are_byte_for_byte_and_hold_no_answer_shape(self):
        attributes = (ROOT / ".gitattributes").read_text(encoding="utf-8")
        self.assertIn("seed/bootstrap/vectors/policy/** -text", attributes)
        for name in (policyreads.FULL, policyreads.HOISTED, policyreads.REQUIRED):
            self.assertNotIn(b"\r", (FIXTURES / name).read_bytes())


class JudgeTest(unittest.TestCase):
    """The judge: each named path is a section's, the fixture's, with the fixture's value; each required path is named;
    the hoisted file's top level is never read for a required path."""

    def test_the_seeds_reference_answer_is_clean(self):  # the contract is satisfiable
        runner = LocalRunner(BRAIN)
        found = policyreads.run(runner, 60)
        self.assertEqual([r["exit"] for r in found["runs"]], [0, 0])
        self.assertTrue(policyreads.complete(found))
        self.assertEqual(policyreads.findings(PLAN, found), [])

    def test_91bbd27s_canary_is_red(self):  # policy_reads_section_unchecked policy_reads_required_ignored
        """The cap read at the top level, named as it was read: unsectioned, and the required path is not named."""
        others = [p for p in PLAN["required"] if p != CANARY]
        read = lambda doc: dict(reads_of(doc, others), **{"stage_budgets.asama_0.canary_usd": None})  # noqa: E731
        found = names(policyreads.findings(PLAN, loop(read)))
        self.assertIn((policyreads.UNSECTIONED, "stage_budgets.asama_0.canary_usd"), found)
        self.assertIn((policyreads.REQUIRED_ABSENT, CANARY), found)

    def test_a_top_level_read_named_by_its_full_path_is_a_wrong_value(self):  # policy_reads_value_unchecked
        read = lambda doc: dict(reads_of(doc, PLAN["required"]),  # noqa: E731
                                **{CANARY: policyreads.at(doc, CANARY.split(".")[1:])
                                   if policyreads.at(doc, CANARY.split(".")[1:]) is not policyreads._ABSENT else None})
        self.assertEqual(names(policyreads.findings(PLAN, loop(read))),  # and on the hoisted file, the top's value
                         [(policyreads.ROOT_FALLBACK, CANARY), (policyreads.WRONG_VALUE, CANARY)])

    def test_a_loop_that_falls_back_to_the_top_level_is_named(self):  # policy_reads_hoisted_run_skipped
        def read(doc):
            out = reads_of(doc, PLAN["required"])
            for path, value in out.items():
                top = policyreads.at(doc, path.split(".")[1:])
                if value is None and top is not policyreads._ABSENT:
                    out[path] = top
            return out
        found = names(policyreads.findings(PLAN, loop(read)))
        self.assertEqual(found, [(policyreads.ROOT_FALLBACK, p) for p in PLAN["required"]])
        strict = names(policyreads.findings(PLAN, loop(lambda doc: reads_of(doc, PLAN["required"]))))
        self.assertEqual(strict, [])  # null where the path is absent: no finding

    def test_a_stage_1_loop_that_falls_back_to_the_top_level_is_named(self):
        """seed-076: with Stage 1's plan, a loop that reads `stage_params` at the top level of the hoisted file is
        named; one that names its paths in their section is clean."""
        stage1 = policyreads.plan(VECTORS, 1)
        clean = record(answer(reads_of(stage1["full"], stage1["required"])),
                       answer(reads_of(stage1["hoisted"], stage1["required"])))
        self.assertEqual(policyreads.findings(stage1, clean), [])
        path = "constitutional.stage_params.match_window_lines"
        decoy = policyreads.at(stage1["hoisted"], path.split(".")[1:])
        fell = record(answer(reads_of(stage1["full"], stage1["required"])),
                      answer(dict(reads_of(stage1["hoisted"], stage1["required"]), **{path: decoy})))
        self.assertEqual(names(policyreads.findings(stage1, fell)), [(policyreads.ROOT_FALLBACK, path)])
        missing = record(answer(reads_of(stage1["full"], PLAN["required"])),
                         answer(reads_of(stage1["hoisted"], PLAN["required"])))
        self.assertEqual({name for name, _path in names(policyreads.findings(stage1, missing))},
                         {policyreads.REQUIRED_ABSENT})  # seed-076: red until the brain's reads name the five

    def test_a_hoisted_run_that_fails_or_defaults_is_no_finding(self):  # policy_reads_root_fallback_accepted
        good = answer(reads_of(PLAN["full"], PLAN["required"]))
        for second in (answer({}, code=1), answer(b"", timed_out=True), answer(b"not json"),
                       answer(dict(reads_of(PLAN["hoisted"], PLAN["required"]), **{CANARY: 1}))):
            with self.subTest(second=second["line"]):
                self.assertEqual(policyreads.findings(PLAN, record(good, second)), [])
        decoy = policyreads.at(PLAN["hoisted"], CANARY.split(".")[1:])
        fell = answer(dict(reads_of(PLAN["hoisted"], PLAN["required"]), **{CANARY: decoy}))
        self.assertEqual(names(policyreads.findings(PLAN, record(good, fell))), [(policyreads.ROOT_FALLBACK, CANARY)])

    def test_paths_unknown_to_the_pages_and_type_changes_are_named(self):  # policy_reads_value_unchecked
        reads = reads_of(PLAN["full"], PLAN["required"])
        reads["constitutional.no_such_key"] = 1
        reads[CANARY] = float(reads[CANARY])  # 3 read as 3.0: another JSON value
        found = names(policyreads.findings(PLAN, record(answer(reads))))
        self.assertEqual(found, [(policyreads.UNKNOWN, "constitutional.no_such_key"), (policyreads.WRONG_VALUE, CANARY)])

    def test_a_named_path_reaches_the_signed_result_only_when_it_is_safe(self):  # policy_reads_path_not_withheld
        reads = reads_of(PLAN["full"], PLAN["required"])
        secret = "constitutional.ghp_" + "A" * 36
        reads[secret] = 1
        reads["operating." + "x" * 200] = 1
        found = policyreads.findings(PLAN, record(answer(reads)))
        text = json.dumps(found)
        self.assertNotIn("ghp_", text)
        self.assertNotIn("x" * 200, text)
        self.assertEqual(sorted(name for name, _p, _d in found), [policyreads.UNKNOWN] * 2)
        self.assertTrue(all(p.startswith("sha256:") for _n, p, _d in found))
        self.assertEqual(policyreads.shown("operating.kos_wall_s"), "operating.kos_wall_s")

    def test_an_ancestor_covers_on_a_dot_boundary_only(self):  # policy_reads_ancestor_without_dot
        whole = {"operating": PLAN["full"]["operating"], "constitutional": PLAN["full"]["constitutional"]}
        self.assertEqual(policyreads.findings(PLAN, record(answer(whole))), [])
        reads = reads_of(PLAN["full"], [p for p in PLAN["required"] if p != "operating.kos_wall_s"])
        reads["operating.kos"] = None
        found = names(policyreads.findings(PLAN, record(answer(reads))))
        self.assertIn((policyreads.REQUIRED_ABSENT, "operating.kos_wall_s"), found)

    def test_a_command_that_does_not_answer_is_one_failure(self):  # policy_reads_exit_ignored
        for first in (answer({}, code=1), answer(reads_of(PLAN["full"], PLAN["required"]), code=2),
                      answer(b"", timed_out=True), answer(b"[1]"), answer(b"no json"), answer(b"x" * 70000)):
            with self.subTest(line=(first["line"] or "")[:20], code=first["exit"]):
                [(name, path, _detail)] = policyreads.findings(PLAN, record(first))
                self.assertEqual((name, path), (policyreads.FAILED, policyreads.MODULE_FILE))

    def test_the_commands_are_the_two_fixtures_in_referee(self):  # policy_reads_hoisted_run_skipped
        seen = []

        class Runner:
            def run(self, cmd, *, cwd=".", stdin=b"", timeout_s):
                seen.append((cmd, cwd, timeout_s))
                return RunResult(0, b"{}\n", b"", 1)
        found = policyreads.run(Runner(), 77)
        self.assertEqual(seen, [("python -m policy.reads /vec/policy/policy.json", "referee", 77),
                                ("python -m policy.reads /vec/policy/policy_hoisted.json", "referee", 77)])
        self.assertTrue(policyreads.complete(found))
        self.assertFalse(policyreads.complete({"runs": found["runs"][:1]}))
        self.assertFalse(policyreads.complete(dict(found, extra=1)))
        with self.assertRaises(ValueError):
            policyreads.command("../x.json")

    def test_no_seed_directory_asks_nothing(self):
        self.assertIsNone(policyreads.plan(BOOT / "tests", 0))


class DecideTest(unittest.TestCase):
    """`decide`: a warning in Stage 0 that moves nothing else, a reason the Founder can fix from Stage 1, an outage when
    docker broke under the run."""

    STAGE1 = stages.load(1)

    def judge(self, reads, table=None, state=None):
        meta = meta_("code", state or state0())
        return decide(meta, dict(green_run(), policy_reads=reads), not_refuted(), None, CODE_JOBS, 2, 3,
                      now="2026-11-14T00:00:00Z", table=table)

    def strip(self, result):
        return {k: v for k, v in result.items() if k != "warnings"}

    def found(self, *items):
        return {"runs": [answer({}), answer({})], "findings": [list(i) for i in items]}

    def test_stage0_only_warns_and_moves_nothing_else(self):  # policy_reads_stage0_rejects
        base = self.judge(None)
        self.assertEqual(base["verdict"], "accepted")
        result = self.judge(self.found((policyreads.REQUIRED_ABSENT, CANARY, "d")))
        self.assertEqual(result["warnings"], base["warnings"] + [f"{policyreads.REQUIRED_ABSENT}:{CANARY}"])
        self.assertEqual(self.strip(result), self.strip(base))

    def test_stage1_rejects_for_it_and_counts_it(self):  # policy_reads_stage1_only_warns
        self.assertEqual(self.judge(self.found(), self.STAGE1)["verdict"], "accepted")
        result = self.judge(self.found((policyreads.WRONG_VALUE, CANARY, "detail")), self.STAGE1)
        self.assertEqual(result["verdict"], "rejected")
        [reason] = result["reasons"]
        self.assertEqual((reason["kind"], reason["ref"]), (policyreads.WRONG_VALUE, CANARY))
        self.assertTrue(counts_against_founder(reason))

    def test_docker_failing_under_the_run_is_an_outage(self):  # policy_reads_docker_fault_is_a_finding
        broken = {"runs": [answer(b"", code=125), answer({})], "findings": [[policyreads.FAILED, "x", "d"]]}
        for table in (None, self.STAGE1):
            result = self.judge(broken, table)
            self.assertEqual([(r["kind"], r["ref"]) for r in result["reasons"]], [("infra", "kos:docker")])


class Sandbox:
    def run(self, cmd, *, cwd=".", stdin=b"", timeout_s):
        if cmd == "exit 0":
            return RunResult(0, b"", b"", 1)
        if cmd.startswith("python -m unittest t"):
            return RunResult(0, b"", b"", 1)
        return RunResult(1, b"", b"", 1)


TESTS = [{"id": f"T{n}", "cmd": f"python -m unittest t{n}", "stage": 0} for n in range(1, 6)]


def push(reads=PLAN):
    return parts.Push(head="a" * 40, tests=list(TESTS), groups=[], asked=[], units=[], lic=[], missing=[],
                      policy_reads=reads)


class PartsTest(unittest.TestCase):
    """The join takes the run from exactly the part that owns the place after the last test, and judges it."""

    def records(self, p, n, made=None):
        made = made or (lambda: loop(lambda doc: reads_of(doc, PLAN["required"][1:])))
        return [parts.run_part(p, k, n, Sandbox(), 60, lambda own: [], policy_reads=made) for k in range(n)]

    def test_every_part_count_writes_the_single_jobs_run_with_its_findings(self):  # policy_reads_join_skips_findings
        p = push()
        single = parts.join(p, self.records(p, 1))
        self.assertEqual(single["policy_reads"]["findings"],
                         [[policyreads.REQUIRED_ABSENT, PLAN["required"][0],
                           f"{PLAN['required'][0]} is read by the loop (`18a`) and the command does not name it"]])
        self.assertTrue(single["green"])  # the finding is `decide`'s, never the tests' colour
        for n in (2, 4, 5, 7):
            with self.subTest(parts=n):
                records = self.records(p, n)
                self.assertEqual([k for k, r in enumerate(records) if r["policy_reads"] is not None], [len(TESTS) % n])
                self.assertEqual(json.dumps(parts.join(p, records), sort_keys=True),
                                 json.dumps(single, sort_keys=True))
        self.assertIsNone(parts.join(push(None), self.records(push(None), 2))["policy_reads"])

    def test_a_missing_or_foreign_run_stops_the_join(self):  # policy_reads_join_takes_any_part
        p = push()
        for bad in (None, {"runs": []}, {"runs": [answer({})]}):
            records = self.records(p, 3)
            records[len(TESTS) % 3]["policy_reads"] = bad
            with self.subTest(bad=bad), self.assertRaises(parts.PartError):
                parts.join(p, records)
        records = self.records(p, 4)
        records[0]["policy_reads"] = loop(lambda doc: {})
        with self.assertRaises(parts.PartError):
            parts.join(p, records)
        q = push(None)
        records = self.records(q, 2)
        records[1]["policy_reads"] = loop(lambda doc: {})
        with self.assertRaises(parts.PartError):
            parts.join(q, records)

    def test_the_plan_is_part_of_the_plans_hash(self):  # policy_reads_plan_hash_leaves_it_out
        self.assertNotEqual(push(None).plan_sha256(), push().plan_sha256())
        with self.assertRaises(parts.PartError):
            parts.join(push(), self.records(push(None), 1))


class CommandsTest(unittest.TestCase):
    """The real `run-tests` asks the loop through the referee's runner, over the seed's fixtures at `/vec/policy/`, and
    `run.json` carries both runs and their findings."""

    setUp = test_flow.Flow.setUp
    tearDown = test_flow.Flow.tearDown
    stage_pulled = test_decision.PullGates.stage_pulled

    def test_run_tests_asks_the_loop(self):  # policy_reads_not_run_in_kos
        manifest = {"tests": [{"id": "T13", "cmd": "python -m unittest t13", "stage": 0}], "done_mf": [],
                    "lockfiles": []}
        pulled, vectors = self.stage_pulled({"manifest": manifest}, files=("referee/policy/reads.py",))
        deps = Path(self.tmp.name) / "deps"
        deps.mkdir()
        seen = []
        local = LocalRunner(BRAIN)

        class Tree(FakeRunner):
            def run(self, cmd, **kw):
                if cmd.startswith("python -m policy.reads "):
                    seen.append((cmd, kw.get("cwd")))
                    return local.run(cmd, cwd="referee", timeout_s=60)
                return RunResult(0, b"", b"", 1) if cmd != "exit 1" and "socket" not in cmd and "touch" not in cmd \
                    else RunResult(1, b"", b"", 1)
        real = cli._runner
        cli._runner = lambda *a, **k: Tree(vectors)
        self.addCleanup(setattr, cli, "_runner", real)
        out = Path(self.tmp.name) / "run"
        rc = cli.main(["run-tests", "--root", str(self.referee), "--pulled", str(pulled), "--deps", str(deps),
                       "--work", str(Path(self.tmp.name) / "work"), "--out", str(out)])
        self.assertEqual(rc, 0)
        run = json.loads((out / "run.json").read_text(encoding="utf-8"))
        self.assertEqual(seen, [(policyreads.command(policyreads.FULL), "referee"),
                                (policyreads.command(policyreads.HOISTED), "referee")])
        self.assertEqual(run["policy_reads"]["findings"], [])
        self.assertEqual([r["exit"] for r in run["policy_reads"]["runs"]], [0, 0])


class PageTest(unittest.TestCase):
    """`29v` names each finding the code uses and the command; the pages that name a key the loop reads write it with
    its section; `29b` and `24a` point to it."""

    def test_29v_names_each_finding_and_the_command(self):  # policy_page_searches_the_root
        text = page("29v")
        self.assertEqual(set(re.findall(r"policy_reads_[a-z_]+", text)) - {"policy_reads_"}, set(policyreads.NAMES))
        flat = " ".join(text.split())
        for fact in ("`python -m policy.reads <dosya>`, `referee/` dizininde", "Dosyada olmayan yol `null`'dır",
                     "onun yerini tutmaz", "`policy.json`", "`policy_hoisted.json`", "`required.json`",
                     "en çok 256 KiB", f"`{policyreads.MODULE_FILE}`"):
            self.assertIn(fact, flat)
        lines = text.splitlines()
        self.assertLessEqual(len(lines), 80)
        self.assertEqual([n for n, line in enumerate(lines, 1) if len(line) > 120], [])

    def test_the_pages_that_name_a_read_key_carry_its_section(self):  # policy_29b_reads_lose_their_section
        flat = " ".join(page("29b").split())
        self.assertIn("Politikadan okudukları, hepsi `constitutional` altında (`29v`):", flat)
        self.assertIn("`constitutional.stage_budgets.asama_<k>.rival_usd`'sidir", " ".join(page("26e").split()))
        self.assertIn("Bütünü `/work/logs/policy.json`'dadır.", " ".join(page("24a").split()))

    def test_seed_053_is_answered_by_lines_that_say_it(self):  # changelog_drops_seed_053
        """E342's rule: the epoch's entry names seed-053 whole on one line (the launcher's reader, E527) and each page
        range of its answer holds what the answer says."""
        log = (ROOT / "spec" / "tohum" / "CHANGELOG-8.md").read_text(encoding="utf-8")  # moved by the cap (E634)
        rid = "seed-053-policy-shape-unseen-before-b"
        self.assertTrue(any(f"`{rid}` →" in line for line in log.splitlines()))
        entry = " ".join(log[log.index("- 2.2 (2026-11-14, E588"):log.index("- 2.2 (2026-11-14, E585")].split())
        answer = entry[entry.index(f"`{rid}` →"):]
        says = {("24a", 34, 35): ("`/work/logs/operating.json`'dadır", "Bütünü `/work/logs/policy.json`'dadır."),
                ("29v", 16, 19): ("**Oturumun kopyası.**", "`/work/logs/policy.json`'da görür", "en çok 256 KiB"),
                ("29v", 21, 31): ("`python -m policy.reads <dosya>`", "`policy_hoisted.json`", "`required.json`"),
                ("29v", 36, 47): ("`policy_reads_required_absent`", "Aşama 0'da bulgu imzalı sonucun `warnings`'ine"),
                ("18a", 12, 12): ("başka sayfada bölümsüz geçen ad bu yoldur",),
                ("18a", 49, 50): ("`constitutional.license_allowlist`", "`deps.fetch`"),
                ("29b", 79, 79): ("hepsi `constitutional` altında (`29v`)",),
                ("26e", 46, 46): ("`constitutional.stage_budgets.asama_<k>.rival_usd`",),
                ("15", 28, 32): ("**Kurucu'nun hafızası yalnız `main`'dedir**",)}
        for (prefix, first, last), words in says.items():
            ref = f"`{prefix}:{first}`" if first == last else f"`{prefix}:{first}-{last}`"
            self.assertIn(ref, entry, ref)
            lines = " ".join(" ".join(page(prefix).splitlines()[first - 1:last]).split())
            for phrase in words:
                self.assertIn(phrase, lines, ref)
        self.assertIn("`seed-053-policy-shape-unseen-before-b` →", answer)


if __name__ == "__main__":
    unittest.main()
