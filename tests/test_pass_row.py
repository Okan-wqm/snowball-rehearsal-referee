"""``harness.pass_row``: asama-0/10a's conditions that the toy's and the copy's ``brain/state`` record, judged from
those files (stage 0, (B) step 9; the row of tohum/26d; seed-046's draft for the rest).

The states are written by ``ledger.cycle.plan`` (the cycle's one writer: chained rows, the status row and block, one
signed root per cycle) with ``ledger.events``' rows, the ones ``activate`` and D6-D8 write:

- a world in which every judged condition holds is ``PASS``, with the payload (the copy's genesis and merge row
  hashes, the judged and the listed conditions); the command line gives the same line, exit 0;
- each condition's every reason, one change of the world at a time: the genesis row's place, the
  genesis cycle's ratchet base, a candidate undecided, not merged, merged against its reject or rejected for
  another reason (its first decision is its verdict: a later reject of a merged candidate is not), a candidate
  merge unfinished, flaky or reverted, a ledger ``ledger.serial`` refuses, each drill cause unshown, a drill
  judged ``FAIL`` (cause, not reverted), a plant with no commitment before it, no drill inputs, a root missing
  for a cycle and a root that is not the ledger's, a cycle without its status row, no canary, no ``ok`` canary, a
  served model that is not the requested one, a cost over its cap;
- tohum/26d: the payload's ``stage`` (the integer 0), ``verdict``, ``import_line_sha256`` (the counter's last import
  line) and the (A) result's ``owner_exception`` as written, absent when it has none; the last genesis naming
  another import (each of its three keys); a run with no merge row (``merge_missing``); only the run from the last
  genesis counts (its decisions, merges, ratchet base, canary, plants and their commitments; the copy's last genesis
  and its later merge rows in the payload), and an earlier run's PASS does not refuse the next;
- a state that does not conform to ``ledger.schema`` is ``state_invalid`` under every condition and nothing else;
- expectations that are not ``{decision: merge}`` or ``{decision: reject, reason}``, a counter with no import or not
  a chain, a result the import does not name, without an ``exit`` object or with an owner exception not of
  tohum/02's form, and unreadable command-line inputs are unusable (exit 2);
- the copy's genesis gate (``gate``): the toy's state alone, ``open`` on the world above with no copy state at all,
  ``closed`` with exactly the toy's reasons ``judge`` gives (no drill inputs, a cause unshown, a flaky sentinel, a
  reject expected for another reason, a model mismatch, another import), every condition ``state_invalid`` on a
  toy state ``ledger.schema`` refuses, unusable expectations and counter; an empty copy state fails ``judge``
  without error;
- ``passed`` reads the PASS row as ``gate_opened`` reads the gate's (one reader, ``Held``): the referee's own row
  after the last genesis, not a proposal, not another kind, not before a later genesis; a ledger not of the schema,
  not a chain or empty holds neither; the two kinds are not each other's;
- ``result_path``: the last import's ``setup/results/<result_sha256>.json`` (tohum/26c, 29s); a ``result_sha256``
  absent or not 64 lowercase hex (a path, upper case, short, a trailing LF or path, a number) and a counter with no
  import name no file (unusable).

The PASS row's write (the toy's cycle in ``yaz``, ``loop.write_cycle``) is tested in test_loop_write.Pass.

The loop's own drill ledger (D8 over four cycles) is judged in test_loop_write.D8.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest

REFEREE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REFEREE)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from harness import pass_row as PR  # noqa: E402
from harness import revert_drill as RD  # noqa: E402
from ledger import anchor as AN  # noqa: E402
from ledger import chain as CH  # noqa: E402
from ledger import cycle as CY  # noqa: E402
from ledger import events as EV  # noqa: E402
from ledger import schema as SC  # noqa: E402
from target import branches as B  # noqa: E402
from profile_tree import write_tree  # noqa: E402
from test_revert_drill import ledger_with  # noqa: E402
import yaz_world as YW  # noqa: E402

TS = "2026-11-02T10:00:00Z"
COUNTER = YW.transfer()  # the counter's last import and the (A) result it names
IMPORTS, RESULT = COUNTER["imports"], COUNTER["result"]
OWNER_EXCEPTIONS = YW.OWNER_EXCEPTIONS  # (A)'s list of the owner's exceptions: durustluk, then spec
DURUSTLUK, SPEC = OWNER_EXCEPTIONS
# tohum/26f: a drill instance's id is 32 lowercase hex that does not tell its cause; these three are the tests'
# (test_loop_write and test_rehearsal use them too), in the code point order of the causes' names.
RD_BUILD, RD_LINT, RD_TEST = "b0" * 16, "c0" * 16, "d0" * 16
CATALOG = {"instances": [{"id": RD_BUILD, "cause": "build_break"}, {"id": RD_LINT, "cause": "lint_regression"},
                         {"id": RD_TEST, "cause": "test_regression"}]}
SEED = {"seed": "pass-row-seed"}
TOY_EXPECT = {"bad-path": {"decision": "reject", "reason": "security_path:src/p.js"},
              "bad-test": {"decision": "reject", "reason": "tests_red"}, "good": {"decision": "merge"}}
COPY_EXPECT = {"bad-unit": {"decision": "reject", "reason": "tests_red"}, "fix": {"decision": "merge"}}


def h(n: int, width: int = 40) -> str:
    return ("%x" % n).rjust(width, "0")


def genesis_payload(target: str, counter: dict = COUNTER) -> dict:
    return {"target": target, "base_sha": h(1), "referee_tree_sha256": "2" * 64,
            "result_sha256": hashlib.sha256(counter["result"]).hexdigest(),
            "import_line_sha256": counter["line_sha256"], "seed_epoch": {"commit": h(5), "spec_tohum_sha256": h(6, 64),
                                                           "seed_sha256": h(7, 64), "bootstrap_sha256": h(8, 64)},
            "policy_sha256": h(9, 64), "summary_sha256": h(10, 64), "seed_security_ledger_sha256": h(11, 64),
            "seed_security_last_row_hash": h(12, 64), "recipe_sha256": h(13, 64), "facts_sha256": h(14, 64)}


def run_for(instance_id: str, after: int) -> str:
    """The first run id above ``after`` whose key under ``SEED`` selects ``instance_id``."""
    for n in range(after + 1, after + 1000):
        if RD.key(SEED, str(n), CATALOG)["instance_id"] == instance_id:
            return str(n)
    raise AssertionError("no run selects %s" % instance_id)


def cost(c: dict, served=None, outcome="ok", usd=1234, cap=1_000_000) -> dict:
    row = YW.cost_row("cagir-" + c["cycle_id"], usd=usd, outcome=outcome, cap_usd_micros=cap,
                      models_served=["m"] if served is None else served)
    return dict(row, ts=TS)


class State:
    """One target's ``brain/state`` written cycle by cycle with ``ledger.cycle.plan``."""

    def __init__(self, target: str):
        self.target, self.ledger, self.roots, self.status, self.run = target, b"", b"", None, 100

    def cycle(self, *makers, genesis: bool | dict = False, run: str | None = None) -> dict:
        """``genesis``: ``True``, or the genesis payload's changed keys (another import)."""
        self.run = int(run) if run else self.run + 1
        c = {"cycle_id": "%d-1" % self.run, "ts": TS, "snapshot_id": h(99)}
        payload = dict(genesis_payload(self.target), **(genesis if isinstance(genesis, dict) else {}))
        rows = [EV.row(c, "genesis", "genesis", payload)] if genesis is not False else []
        rows += [EV.start(c)]
        for m in makers:  # a maker gives a row or a list of rows (ledger.events.decided)
            made = m(c)
            rows += made if isinstance(made, list) else [made]
        facts = {"ts": TS, "snapshot_id": h(99), "row_id": c["cycle_id"] + ":status",
                 "canary_cap_usd_micros": 1_000_000}
        planned = CY.plan(self.ledger, self.ledger, self.roots, self.roots, self.status, rows, IMPORTS, facts,
                          AN.FakeSigner(True, YW.IDENTITY, "rekor-%d" % self.run), c["cycle_id"] + ":root")
        files = planned["files"]
        self.ledger, self.roots, self.status = files[B.STATE_LEDGER], files[B.STATE_ROOTS], files[B.STATE_STATUS]
        return c

    def files(self) -> dict:
        return {"ledger": self.ledger, "roots": self.roots}


def merged(sha: str, pull: int = 1) -> dict:
    return {"path": "src/a.js", "pull": pull, "head_sha": h(0xbeef), "merge_sha": sha,
            "hunks": [{"old_start": 2, "old_count": 1, "new_start": 2, "new_count": 1}]}


def genesis_cycle(state: State, decisions, genesis: bool | dict = True) -> None:
    state.cycle(lambda c: EV.row(c, "cut", "integration_cut", {"branch": B.INTEGRATION, "base_sha": h(1)}),
                lambda c: EV.ratchet_base(c, h(20, 64), {"no-unused-vars": 0}),
                *[(lambda c, d=d: EV.decided(c, *d)) for d in decisions], genesis=genesis)


def drill(state: State, instance_id: str, cause: str, merge_sha: str, revert_cause: str | None = None,
          reverted: bool = True) -> None:
    """Three cycles: the commitment, the plant (with its ratchet base), the revert with ``revert_cause``."""
    run = run_for(instance_id, state.run)
    key = RD.key(SEED, run, CATALOG)
    assert key["cause"] == cause
    state.cycle(lambda c: EV.drill(c, "commit", RD.commit_payload(key)), cost, run=run)
    state.cycle(lambda c: EV.ratchet_base(c, h(21, 64), {"no-unused-vars": 0}),
                lambda c: EV.drill(c, "plant", RD.plant_payload(instance_id, merge_sha)), cost)
    if reverted:
        state.cycle(lambda c: EV.revert(c, merge_sha, revert_cause or cause), cost)


def runs(state: State) -> int:
    """The genesis rows already on ``state``: a later run's merges are other commits (shas shifted by 0x1000)."""
    return sum(1 for line in state.ledger.splitlines() if json.loads(line)["kind"] == "genesis")


def toy_world(toy: State | None = None, **over) -> State:
    """The toy's (B) run; on ``toy`` it is a run after a new genesis (``over["genesis"]``)."""
    toy = toy or State("toy")
    shift = 0x1000 * runs(toy)
    genesis_cycle(toy, over.get("decisions", [("bad-path", ["security_path:src/p.js"]), ("bad-test", ["tests_red"]),
                                              ("good", [], merged(h(0xa1 + shift)))]), over.get("genesis", True))
    toy.cycle(lambda c: EV.sentinel(c, h(0xa1 + shift), over.get("verdict", "green"), []),
              lambda c: cost(c, **over.get("cost", {})))
    for n, (instance_id, cause) in enumerate(over.get("drills", [(RD_TEST, "test_regression"),
                                                                 (RD_BUILD, "build_break"),
                                                                 (RD_LINT, "lint_regression")])):
        drill(toy, instance_id, cause, h(0xd0 + n + shift), **over.get("drill_over", {}).get(instance_id, {}))
    return toy


def copy_world(copy: State | None = None, genesis: bool | dict = True) -> State:
    copy = copy or State("copy")
    sha = h(0xc1 + 0x1000 * runs(copy))
    genesis_cycle(copy, [], genesis)
    copy.cycle(lambda c: EV.decided(c, "bad-unit", ["tests_red"]), lambda c: EV.decided(c, "fix", [], merged(sha)),
               cost)
    copy.cycle(lambda c: EV.sentinel(c, sha, "green", []), cost)
    return copy


def judge(toy: State | None = None, copy: State | None = None, drill_inputs=True, toy_expect=None, copy_expect=None,
          counter: dict = COUNTER) -> dict:
    return PR.judge((toy or toy_world()).files(), (copy or copy_world()).files(),
                    TOY_EXPECT if toy_expect is None else toy_expect, COPY_EXPECT if copy_expect is None else copy_expect,
                    {"seed": SEED, "catalog": CATALOG} if drill_inputs else None, counter["imports"], counter["result"])


def raw_cycle(state: State, rows) -> None:
    """Rows chained onto the ledger with no status row and no root: not a cycle ``ledger.cycle`` writes."""
    state.ledger = ledger_with(rows, state.ledger)


class Passes(unittest.TestCase):
    def test_every_judged_condition_holds(self):
        copy = copy_world()
        got = judge(copy=copy)
        self.assertEqual((got["verdict"], got["state"]), ("PASS", {}), got["conditions"])
        self.assertEqual(got["conditions"], {cond: [] for cond in PR.CONDITIONS})
        self.assertEqual(got["not_checked"], PR.NOT_CHECKED)
        rows = [json.loads(line) for line in copy.ledger.splitlines()]
        merge = [r for r in rows if r["kind"] == "merge"]  # tohum/26d's merge rows, not the decision rows
        self.assertEqual([r["payload"]["merge_sha"] for r in merge], [h(0xc1)])
        # tohum/26d's fields: stage the integer 0, the import's line hash, no owner_exception when (A) has none
        self.assertEqual(got["payload"], {"stage": 0, "verdict": "PASS", "import_line_sha256": COUNTER["line_sha256"],
                                          "copy_genesis_row_hash": rows[0]["row_hash"],
                                          "copy_merge_row_hashes": [merge[0]["row_hash"]],
                                          "conditions": sorted(PR.CONDITIONS), "not_checked": sorted(PR.NOT_CHECKED)})
        self.assertIs(type(got["payload"]["stage"]), int)
        self.assertEqual(COUNTER["line_sha256"], hashlib.sha256(IMPORTS.splitlines()[-1]).hexdigest())
        self.assertEqual(SC.payload_reasons("events", "pass", got["payload"]), [])
        self.assertFalse(set(PR.CONDITIONS) & set(PR.NOT_CHECKED))

    def test_the_owner_exceptions_of_the_a_result_are_carried_as_written(self):
        """tohum/26d:45-47 and stage-open's check 7: the PASS payload's ``owner_exception`` is the (A) result's
        list with the same RFC 8785 bytes, for the owner's two exceptions and for an empty list (present in the
        result, so present in the row)."""
        for exceptions in (OWNER_EXCEPTIONS, []):
            with self.subTest(exceptions=len(exceptions)):
                counter = YW.transfer({"requested": True, "transferable": True, "owner_exception": exceptions})
                toy, copy = State("toy"), State("copy")
                toy_world(toy, genesis=genesis_payload("toy", counter))
                copy_world(copy, genesis=genesis_payload("copy", counter))
                got = judge(toy, copy, counter=counter)
                self.assertEqual(got["verdict"], "PASS", got["conditions"])
                self.assertIn("owner_exception", got["payload"])
                self.assertEqual(CH.canonical(got["payload"]["owner_exception"]),
                                 CH.canonical(json.loads(counter["result"])["exit"]["owner_exception"]))
                self.assertEqual(CH.canonical(got["payload"]["owner_exception"]), CH.canonical(exceptions))
                self.assertEqual(got["payload"]["import_line_sha256"], counter["line_sha256"])
                self.assertEqual(SC.payload_reasons("events", "pass", got["payload"]), [])

    def test_the_forms_of_owner_exception_that_are_read(self):
        """``imported`` on a result named by its own import: a list in the order of ``anchor`` is read as written
        whatever no seed page states (one exception, either anchor; an anchor twice; another anchor; values of any
        type), and a result without the key gives none."""
        again = dict(DURUSTLUK, reason="a second reason")
        free = {"anchor": "kok", "stage": "0", "carry_to": None, "reason": ["r"], "carry_commitment": 7,
                "measured": False}
        for exceptions in ([DURUSTLUK], [SPEC], [DURUSTLUK, again], [DURUSTLUK, free, SPEC], [free]):
            with self.subTest(exceptions=exceptions):
                counter = YW.transfer({"requested": True, "owner_exception": exceptions})
                got = PR.imported(counter["imports"], counter["result"])
                self.assertEqual(CH.canonical(got["owner_exception"]), CH.canonical(exceptions))
        self.assertNotIn("owner_exception", PR.imported(IMPORTS, RESULT))

    def test_a_merged_candidate_offered_again_is_judged_by_its_first_decision(self):
        toy = toy_world()
        toy.cycle(lambda c: EV.decided(c, "good", ["kos:patch_does_not_apply"]), cost)
        self.assertEqual(judge(toy)["verdict"], "PASS")


class Fails(unittest.TestCase):
    def reasons(self, got: dict, cond: str) -> list[str]:
        self.assertEqual(got["verdict"], "FAIL")
        self.assertIsNone(got["payload"])
        return got["conditions"][cond]

    def test_genesis(self):
        toy = State("toy")
        toy.cycle(lambda c: EV.ratchet_base(c, h(20, 64), {}))
        toy.cycle(lambda c: EV.row(c, "genesis", "genesis", genesis_payload("toy")))
        self.assertEqual(self.reasons(judge(toy), "#genesis"), ["toy:genesis_not_first"])
        # the last genesis names another import than the counter's last one: each of the three keys (26d 2, 5)
        other = YW.transfer({"requested": False})
        got = judge(copy=copy_world(State("copy"), genesis_payload("copy", other)))
        self.assertEqual(self.reasons(got, "#genesis"), ["copy:genesis_import:import_line_sha256",
                                                         "copy:genesis_import:result_sha256"])
        got = judge(copy=copy_world(State("copy"), {"referee_tree_sha256": "3" * 64}))
        self.assertEqual(self.reasons(got, "#genesis"), ["copy:genesis_import:referee_tree_sha256"])

    def test_the_genesis_cycles_ratchet_base(self):
        toy = State("toy")
        toy.cycle(genesis=True)
        toy.cycle(lambda c: EV.ratchet_base(c, h(20, 64), {}))
        self.assertEqual(self.reasons(judge(toy), "#taban"), ["toy:base_missing"])

    def test_merge_and_reject_expectations(self):
        toy = toy_world(decisions=[("bad-path", [], merged(h(0xb1))), ("good", ["tests_red"])])
        got = judge(toy, toy_expect=dict(TOY_EXPECT, **{"bad-x": {"decision": "reject", "reason": "tests_red"}}))
        self.assertEqual(got["conditions"]["#merge"], ["toy:not_merged:good"])
        self.assertEqual(got["conditions"]["#ret"], ["toy:merged:bad-path", "toy:undecided:bad-test",
                                                     "toy:undecided:bad-x"])
        toy = toy_world(decisions=[("bad-path", ["security_path:src/p.js", "tests_red"]),
                                   ("bad-test", ["ratchet_increase"])])
        got = judge(toy)
        self.assertEqual(got["conditions"]["#merge"], ["toy:merge_missing", "toy:undecided:good"])
        self.assertEqual(got["conditions"]["#ret"], ["toy:reason_mismatch:bad-path", "toy:reason_mismatch:bad-test"])

    def test_candidate_merges_end_green_and_stay(self):
        self.assertEqual(self.reasons(judge(toy_world(verdict="flaky")), "#nobetci #hayatta"),
                         ["toy:sentinel_flaky:" + h(0xa1)])
        toy = State("toy")
        genesis_cycle(toy, [("good", [], merged(h(0xa1)))])
        self.assertEqual(self.reasons(judge(toy), "#nobetci #hayatta"), ["toy:sentinel_unfinished:" + h(0xa1)])
        toy = State("toy")
        genesis_cycle(toy, [("good", [], merged(h(0xa1)))])
        toy.cycle(lambda c: EV.revert(c, h(0xa1), "test_regression"))
        self.assertEqual(self.reasons(judge(toy), "#nobetci #hayatta"), ["toy:reverted:" + h(0xa1)])
        toy = toy_world()
        toy.cycle(lambda c: EV.revert(c, h(0xa1), "test_regression"), cost)
        self.assertEqual(self.reasons(judge(toy), "#nobetci #hayatta"), ["toy:serial:finished_twice:" + h(0xa1)])

    def test_each_drill_cause_is_shown_by_a_pass(self):
        got = judge(toy_world(drills=[(RD_TEST, "test_regression")]))
        self.assertEqual(self.reasons(got, "#geri-alma"), ["toy:cause_unshown:build_break",
                                                           "toy:cause_unshown:lint_regression"])
        self.assertEqual(self.reasons(judge(drill_inputs=False), "#geri-alma"), ["toy:drill_inputs_missing"])

    def test_a_drill_judged_fail_is_named(self):
        toy = toy_world(drill_over={RD_BUILD: {"revert_cause": "test_regression"}})
        self.assertEqual(self.reasons(judge(toy), "#geri-alma"), ["toy:drill_fail:%s:cause_mismatch" % RD_BUILD,
                                                                  "toy:cause_unshown:build_break"])
        toy = toy_world(drill_over={RD_LINT: {"reverted": False}})
        self.assertEqual(self.reasons(judge(toy), "#geri-alma"), ["toy:drill_fail:%s:not_reverted" % RD_LINT,
                                                                  "toy:cause_unshown:lint_regression"])

    def test_a_plant_without_commitment(self):
        toy = toy_world()
        toy.cycle(lambda c: EV.drill(c, "plant", RD.plant_payload(RD_TEST, h(0xe1))), cost)
        toy.cycle(lambda c: EV.revert(c, h(0xe1), "test_regression"), cost)
        # judged against the last commitment before it, rd-lint's, already used
        self.assertEqual(self.reasons(judge(toy), "#geri-alma"), ["toy:drill_fail:%s:cause_mismatch" % RD_TEST,
                                                                  "toy:drill_fail:%s:instance_mismatch" % RD_TEST])
        toy = State("toy")
        genesis_cycle(toy, [("bad-path", ["security_path:src/p.js"]), ("bad-test", ["tests_red"]),
                            ("good", [], merged(h(0xa1)))])
        toy.cycle(lambda c: EV.drill(c, "plant", RD.plant_payload(RD_TEST, h(0xe1))), cost)
        self.assertIn("toy:drill_uncommitted:%s" % RD_TEST, self.reasons(judge(toy), "#geri-alma"))

    def test_roots_and_status(self):
        toy = toy_world()
        raw_cycle(toy, [EV.start({"cycle_id": "900-1", "ts": TS, "snapshot_id": h(99)})])
        got = judge(toy)
        self.assertEqual(got["conditions"]["#kok"], ["toy:roots_per_cycle:11/12", "toy:root_mismatch"])
        self.assertEqual(got["conditions"]["#durum"], ["toy:status_count:900-1:0"])

    def test_the_canary(self):
        toy = State("toy")
        genesis_cycle(toy, [])
        self.assertEqual(self.reasons(judge(toy), "#model #belirtec"), ["toy:canary_missing"])
        toy.cycle(lambda c: cost(c, served=[], outcome="outage"))
        self.assertEqual(self.reasons(judge(toy), "#model #belirtec"), ["toy:canary_not_ok"])
        got = judge(toy_world(cost={"served": ["other"], "usd": 2_000_000}))
        self.assertEqual(got["conditions"]["#model #belirtec"], ["toy:model_mismatch:cagir-102-1",
                                                                 "toy:cap_exceeded:cagir-102-1"])

    def test_a_run_with_no_merge_row(self):
        """26d: the toy's PASS needs a merge row between its last genesis and it; the copy's payload at least one."""
        got = judge(copy_expect={"bad-unit": {"decision": "reject", "reason": "tests_red"}},
                    copy=self.copy_without_merge())
        self.assertEqual(self.reasons(got, "#merge"), ["copy:merge_missing"])
        toy = toy_world(decisions=[("bad-path", ["security_path:src/p.js"]), ("bad-test", ["tests_red"])])
        got = judge(toy, toy_expect={k: v for k, v in TOY_EXPECT.items() if k != "good"})
        self.assertEqual(got["conditions"]["#merge"], ["toy:merge_missing"])

    @staticmethod
    def copy_without_merge() -> State:
        copy = State("copy")
        genesis_cycle(copy, [])
        copy.cycle(lambda c: EV.decided(c, "bad-unit", ["tests_red"]), cost)
        return copy

    def test_the_copy_is_judged_the_same_way_but_for_the_drill(self):
        copy = State("copy")
        genesis_cycle(copy, [("fix", ["tests_red"])])
        got = judge(copy=copy)
        self.assertEqual(got["conditions"]["#merge"], ["copy:merge_missing", "copy:not_merged:fix"])
        self.assertEqual(got["conditions"]["#ret"], ["copy:undecided:bad-unit"])
        self.assertEqual(got["conditions"]["#model #belirtec"], ["copy:canary_missing"])
        self.assertEqual(got["conditions"]["#geri-alma"], [])

    def test_a_merge_row_without_its_coverage_record(self):
        """#kapsama-kaydi (asama-0/08, 10a): each merge row carries ``hunk_covered``; the copy's merge row without it,
        the chain otherwise intact, makes the copy's state not of the schema, so no condition holds for it. The
        judged conditions name #kapsama-kaydi and NOT_CHECKED no longer does."""
        self.assertIn("#kapsama-kaydi", PR.CONDITIONS)
        self.assertNotIn("#kapsama-kaydi", PR.NOT_CHECKED)
        copy = copy_world()
        rows = []
        for line in copy.ledger.splitlines():
            r = {k: v for k, v in json.loads(line).items() if k not in ("prev_hash", "row_hash")}
            if r["kind"] == "merge":
                self.assertEqual(r["payload"]["hunk_covered"], [
                    {"path": "src/a.js", "old_start": 2, "old_count": 1, "new_start": 2, "new_count": 1,
                     "covered": "unmeasured", "reason": "no_coverage_tool"}])
                del r["payload"]["hunk_covered"]
            rows.append(r)
        copy.ledger = ledger_with(rows)
        self.assertTrue(CH.verify_bytes(copy.ledger)["valid"])
        got = judge(copy=copy)
        self.assertEqual(got["verdict"], "FAIL")
        self.assertEqual(got["conditions"], {cond: ["copy:state_invalid"] for cond in PR.CONDITIONS})
        self.assertTrue(any("payload.hunk_covered: missing" in r for r in got["state"]["copy"]), got["state"])

    def test_a_state_not_of_the_schema_is_judged_no_further(self):
        toy = toy_world()
        toy.ledger += b'{"not": "a row"}\n'
        got = judge(toy)
        self.assertEqual(got["conditions"], {cond: ["toy:state_invalid"] for cond in PR.CONDITIONS})
        self.assertTrue(got["state"]["toy"])
        self.assertNotIn("copy", got["state"])


class Regenesis(unittest.TestCase):
    """tohum/26d: after a new import each target gets a new genesis and (B) runs again; only its rows count."""

    def test_only_the_run_from_the_last_genesis_counts(self):
        toy, copy = toy_world(), copy_world()
        old_copy_merges = [json.loads(line)["row_hash"] for line in copy.ledger.splitlines()
                           if json.loads(line)["kind"] == "merge"]
        toy.cycle(genesis=True)  # a new genesis, nothing after it yet: the earlier run's rows do not count
        got = judge(toy, copy)
        self.assertEqual(got["conditions"]["#genesis"], [])
        self.assertEqual(got["conditions"]["#merge"], ["toy:merge_missing", "toy:undecided:good"])
        self.assertEqual(got["conditions"]["#ret"], ["toy:undecided:bad-path", "toy:undecided:bad-test"])
        self.assertEqual(got["conditions"]["#geri-alma"], ["toy:cause_unshown:" + c for c in PR.DRILL_CAUSES])
        self.assertEqual(got["conditions"]["#model #belirtec"], ["toy:canary_missing"])
        self.assertEqual(got["conditions"]["#taban"], ["toy:base_missing"])
        # the whole run again on both after a re-import (the first genesis names the earlier import, 26d: it stays):
        # PASS, judged by the last genesis's import; the copy's last genesis and only its later merge rows in the payload
        earlier = {k: v for k, v in genesis_payload("toy", YW.transfer({"requested": False})).items()
                   if k in PR.IMPORT_KEYS}
        toy, copy = toy_world(toy_world(genesis=earlier)), copy_world(copy_world(genesis=earlier))
        got = judge(toy, copy)
        self.assertEqual(got["verdict"], "PASS", got["conditions"])
        rows = [json.loads(line) for line in copy.ledger.splitlines()]
        last = max(i for i, r in enumerate(rows) if r["kind"] == "genesis")
        self.assertGreater(last, 0)
        self.assertEqual(got["payload"]["copy_genesis_row_hash"], rows[last]["row_hash"])
        self.assertEqual(got["payload"]["copy_merge_row_hashes"],
                         [r["row_hash"] for r in rows[last:] if r["kind"] == "merge"])
        self.assertFalse(set(got["payload"]["copy_merge_row_hashes"]) & set(old_copy_merges))

    def test_a_plant_and_its_commitment_count_only_in_the_run(self):
        toy = toy_world(drills=[(RD_TEST, "test_regression")])
        run = run_for(RD_BUILD, toy.run)
        key = RD.key(SEED, run, CATALOG)
        toy.cycle(lambda c: EV.drill(c, "commit", RD.commit_payload(key)), cost, run=run)  # before the new genesis
        toy_world(toy, drills=[])
        toy.cycle(lambda c: EV.ratchet_base(c, h(21, 64), {"no-unused-vars": 0}),
                  lambda c: EV.drill(c, "plant", RD.plant_payload(RD_BUILD, h(0xe2))), cost)
        toy.cycle(lambda c: EV.revert(c, h(0xe2), "build_break"), cost)
        got = judge(toy)
        self.assertEqual(got["conditions"]["#geri-alma"], ["toy:drill_uncommitted:%s" % RD_BUILD,
                                                           "toy:cause_unshown:test_regression",
                                                           "toy:cause_unshown:build_break",
                                                           "toy:cause_unshown:lint_regression"])


def gate(toy: State | None = None, drill_inputs=True, toy_expect=None, imports: bytes = IMPORTS) -> dict:
    return PR.gate((toy or toy_world()).files(), TOY_EXPECT if toy_expect is None else toy_expect,
                   {"seed": SEED, "catalog": CATALOG} if drill_inputs else None, imports)


def gate_row(c: dict, **over) -> dict:
    return dict(EV.row(c, "gate", "copy_gate", PR.gate_payload()), **over)


class Gate(unittest.TestCase):
    """The copy's genesis gate (tohum/25a row 7): the toy's half of ``judge``, on the toy's state alone."""

    def test_open_when_every_condition_holds_on_the_toy(self):
        got = gate()
        self.assertEqual(got, {"verdict": "open", "conditions": {cond: [] for cond in PR.CONDITIONS}, "state": {}})
        # no (A) result is read: the counter's last import alone gives #genesis its keys
        self.assertEqual(PR.import_keys(IMPORTS), {"referee_tree_sha256": "2" * 64,
                                                   "result_sha256": hashlib.sha256(RESULT).hexdigest(),
                                                   "import_line_sha256": COUNTER["line_sha256"]})
        self.assertEqual(SC.payload_reasons("events", "copy_gate", PR.gate_payload()), [])
        self.assertEqual(PR.gate_payload(), {"conditions": sorted(PR.CONDITIONS)})

    def test_closed_by_any_toy_condition_judge_names(self):
        """The same reasons ``judge`` gives for the toy, one change of the toy's world at a time."""
        cases = {"no drill inputs": (toy_world(), {"drill_inputs": False}),
                 "a cause unshown": (toy_world(drills=[(RD_TEST, "test_regression")]), {}),
                 "a flaky sentinel": (toy_world(verdict="flaky"), {}),
                 "a reject expected for another reason": (toy_world(), {"toy_expect": dict(
                     TOY_EXPECT, **{"bad-test": {"decision": "reject", "reason": "ratchet_increase"}})}),
                 "a model mismatch": (toy_world(cost={"served": ["other"]}), {}),
                 "another import": (toy_world(), {"counter": YW.transfer({"requested": False})})}
        for name, (toy, kw) in cases.items():
            with self.subTest(name):
                counter = kw.pop("counter", COUNTER)
                got = gate(toy, imports=counter["imports"], **kw)
                judged = judge(toy, counter=counter, **kw)
                self.assertEqual(got["verdict"], "closed")
                self.assertTrue(any(got["conditions"].values()))
                self.assertEqual(got["conditions"], {c: [r for r in rs if r.startswith("toy:")]
                                                     for c, rs in judged["conditions"].items()})

    def test_the_copy_is_not_read(self):
        """A copy with no state at all does not close it; a copy's failing state only fails ``judge``."""
        self.assertEqual(gate()["verdict"], "open")
        self.assertEqual(judge(copy=State("copy"))["verdict"], "FAIL")

    def test_a_toy_state_not_of_the_schema(self):
        toy = toy_world()  # a chain still, with a row ledger.schema refuses
        raw_cycle(toy, [dict(EV.start({"cycle_id": "900-1", "ts": TS, "snapshot_id": h(99)}), trust="nope")])
        got = gate(toy)
        self.assertEqual(got["verdict"], "closed")
        self.assertEqual(got["conditions"], {cond: ["toy:state_invalid"] for cond in PR.CONDITIONS})
        self.assertIn("toy", got["state"])

    def test_unusable_inputs(self):
        with self.assertRaises(PR.Unusable):
            gate(toy_expect={"good": {"decision": "maybe"}})
        with self.assertRaises(PR.Unusable):
            gate(imports=b"")


def pass_row(c: dict, **over) -> dict:
    return dict(EV.row(c, "pass", "pass", judge()["payload"]), **over)


class Held(unittest.TestCase):
    """``gate_opened`` and ``passed``, one reader of the referee's own row after the last genesis."""

    def test_the_referees_own_row_after_the_last_genesis(self):
        for name, held, make in (("gate_opened", PR.gate_opened, gate_row), ("passed", PR.passed, pass_row)):
            with self.subTest(name):
                toy = toy_world()
                self.assertFalse(held(toy.ledger))
                toy.cycle(make, cost)
                self.assertEqual(SC.ledger_reasons(toy.ledger), [])
                self.assertTrue(held(toy.ledger))
                # a later genesis (a re-import) starts a run without it: an earlier run's row is not this run's
                toy_world(toy, genesis=genesis_payload("toy"))
                self.assertFalse(held(toy.ledger))
                # a player's proposal of the row counts for nothing (tohum/26d: proposed_by)
                toy.cycle(lambda c: make(c, proposed_by="founder"), cost)
                self.assertFalse(held(toy.ledger))
                toy.cycle(make, cost)
                self.assertTrue(held(toy.ledger))
                # another row kind of the same part is not it
                other = State("toy")
                toy_world(other)
                other.cycle(lambda c: EV.row(c, "gate", "status_edited", {"found_sha256": None,
                                                                          "recorded_sha256": None}), cost)
                self.assertFalse(held(other.ledger))
        # the two kinds are not each other's
        toy = toy_world()
        toy.cycle(gate_row, cost)
        self.assertEqual((PR.gate_opened(toy.ledger), PR.passed(toy.ledger)), (True, False))
        toy.cycle(pass_row, cost)
        self.assertEqual((PR.gate_opened(toy.ledger), PR.passed(toy.ledger)), (True, True))

    def test_a_ledger_not_of_the_schema_holds_nothing(self):
        for name, held, make in (("gate_opened", PR.gate_opened, gate_row), ("passed", PR.passed, pass_row)):
            with self.subTest(name):
                toy = toy_world()
                toy.cycle(make, cost)
                self.assertTrue(held(toy.ledger))
                bad = State("toy")
                bad.ledger = toy.ledger
                raw_cycle(bad, [dict(EV.start({"cycle_id": "900-1", "ts": TS, "snapshot_id": h(99)}), trust="nope")])
                self.assertFalse(held(bad.ledger))
                self.assertFalse(held(toy.ledger[:-2]))  # not a chain
                self.assertFalse(held(b""))


class ResultPath(unittest.TestCase):
    """tohum/26c, 29s: the (A) result is ``setup/results/<result_sha256>.json`` of the last import."""

    def test_the_last_imports_result(self):
        self.assertEqual(PR.result_path(IMPORTS), "setup/results/%s.json" % hashlib.sha256(RESULT).hexdigest())
        later = YW.transfer({"requested": False})  # a later import names another result
        self.assertEqual(PR.result_path(later["imports"]),
                         "setup/results/%s.json" % hashlib.sha256(later["result"]).hexdigest())

    def test_a_result_sha256_that_is_no_hash_names_no_file(self):
        for value in (None, "", "../../etc/passwd", "A" * 64, "a" * 63, "a" * 64 + "\n", "a" * 64 + "/x", 7):
            with self.subTest(value=value):
                row = {"ts": TS, "stage": 0, "referee_tree_sha256": "2" * 64}
                if value is not None:
                    row["result_sha256"] = value
                with self.assertRaises(PR.Unusable):
                    PR.result_path(YW.chained(YW.IMPORTS_ROWS + [row]))
        for imports in (b"", YW.chained(YW.IMPORTS_ROWS)):  # no import at all
            with self.subTest(imports=imports), self.assertRaises(PR.Unusable):
                PR.result_path(imports)


class Unusable(unittest.TestCase):
    def test_expectations(self):
        for bad in ([], {"c": {"decision": "merge", "reason": "x"}}, {"c": {"decision": "reject"}},
                    {"c": {"decision": "reject", "reason": ""}}, {"c": {"decision": "hold"}}, {"": {"decision": "merge"}}):
            with self.subTest(bad=bad), self.assertRaises(PR.Unusable):
                PR.judge(toy_world().files(), copy_world().files(), bad, COPY_EXPECT, None, IMPORTS, RESULT)

    def test_the_import_and_the_a_result(self):
        """``imported``: the counter must hold an import, the result must be the one it names and carry an
        ``exit`` object, and ``exit.owner_exception`` must be of tohum/02's form (26d:45-47): a list (not the one
        object of the seed before E563, not a string, not null), each element the six keys with ``anchor`` without
        ``#`` and ``measured`` false, in the order of ``anchor``."""
        toy, copy = toy_world().files(), copy_world().files()
        no_transfer = YW.chained(YW.IMPORTS_ROWS)
        cases = [(no_transfer, RESULT, "imports_no_transfer"), (IMPORTS[:-5], RESULT, "imports_broken"),
                 (IMPORTS, RESULT + b" ", "not the (A) result")]
        docs = [({"exit": "closed"}, "no exit object"), ([], "not a JSON object")]
        docs += [({"exit": {"owner_exception": bad}}, "owner_exception")
                 for bad in ("durustluk", None, DURUSTLUK, ["durustluk"], [SPEC, DURUSTLUK],
                             [DURUSTLUK, dict(SPEC, anchor="#spec")], [dict(DURUSTLUK, measured=0)],
                             [DURUSTLUK, {k: v for k, v in SPEC.items() if k != "stage"}],
                             [dict(DURUSTLUK, extra=1)], [dict(DURUSTLUK, anchor="")], [dict(DURUSTLUK, anchor=3)])]
        for doc, fragment in docs:  # each result named by its own import, so only its form is wrong
            result = json.dumps(doc).encode()
            imports = YW.chained(YW.IMPORTS_ROWS + [{"stage": 0, "referee_tree_sha256": "2" * 64,
                                                     "result_sha256": hashlib.sha256(result).hexdigest()}])
            cases.append((imports, result, fragment))
        for imports, result, fragment in cases:
            with self.subTest(fragment=fragment, result=result[:60]):
                with self.assertRaises(PR.Unusable) as caught:
                    PR.judge(toy, copy, TOY_EXPECT, COPY_EXPECT, None, imports, result)
                self.assertIn(fragment, str(caught.exception))


def write_state(root: str, state: State) -> str:
    write_tree(root, {B.STATE_LEDGER: state.ledger, B.STATE_ROOTS: state.roots})
    return root


def write_expect(root: str, expect: dict) -> str:
    write_tree(root, {"%s/expect.json" % cid: doc for cid, doc in expect.items()})
    return root


class CommandLine(unittest.TestCase):
    def run_cli(self, *argv: str):
        proc = subprocess.run([sys.executable, "-m", "harness.pass_row", *argv], cwd=REFEREE, capture_output=True,
                              timeout=120)
        lines = proc.stdout.decode().splitlines()
        return proc.returncode, json.loads(lines[0]) if len(lines) == 1 else lines

    def test_judge_from_files(self):
        with tempfile.TemporaryDirectory() as base:
            toy, copy = write_state(os.path.join(base, "toy"), toy_world()), write_state(os.path.join(base, "copy"),
                                                                                          copy_world())
            te, ce = write_expect(os.path.join(base, "te"), TOY_EXPECT), write_expect(os.path.join(base, "ce"),
                                                                                       COPY_EXPECT)
            write_tree(base, {"catalog.json": CATALOG, "seed.json": SEED, "imports.jsonl": IMPORTS,
                              "result.json": RESULT})
            catalog, seed = os.path.join(base, "catalog.json"), os.path.join(base, "seed.json")
            imports, result = os.path.join(base, "imports.jsonl"), os.path.join(base, "result.json")
            code, line = self.run_cli("judge", toy, copy, te, ce, imports, result, catalog, seed)
            self.assertEqual((code, line), (0, json.loads(json.dumps(judge()))))
            code, line = self.run_cli("judge", toy, copy, te, ce, imports, result)
            self.assertEqual((code, line["verdict"], line["conditions"]["#geri-alma"]),
                             (1, "FAIL", ["toy:drill_inputs_missing"]))
            for argv in (("judge", toy, copy, te, ce), ("judge", toy, copy, te, ce, imports, catalog),
                         ("judge", toy, copy, te, ce, imports, os.path.join(base, "none")),
                         ("judge", toy, copy, te, ce, imports, result, catalog),
                         ("judge", os.path.join(base, "none"), copy, te, ce, imports, result),
                         ("other", toy, copy, te, ce, imports, result)):
                with self.subTest(argv=argv):
                    self.assertEqual(self.run_cli(*argv), (2, {"verdict": "FAIL"}))


if __name__ == "__main__":
    unittest.main()
