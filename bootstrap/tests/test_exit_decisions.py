"""What kept the Stage 0 exit from being decided (`asama-0/10`; E280, E282, E287, E293, E294, E296, E297).

- #kurucu-defteri (E280): an accepted Founder ledger row that breaks one of `tohum/26`'s meaning rules (`part`, `kind`,
  `supersedes`) stays in the chain and is closed by a later valid row that names it in ``supersedes`` (`13`); broken
  bytes or chains are never closed; what is left unclosed is the Founder's to fix. No push is refused for a row the
  referee accepted.
- #is-akisi (E282, E296): the seed's `control` command has the loop's interface (`29p`), and every loop job is held to
  it; above the control step stand only the keys the rule names.
- #durustluk (E287, E294, E297): when the plant was missed, it is taken off the exit only by the owner's named
  exception, read from `setup/summary.json`, written into the signed result and carried to the next stage, and only
  with that stage's plant beside it.
- E293, E297: Stage 0 starts only from a setup summary that names the copy target's identifiers and the honesty
  commitment, so the setup day's items 10a and 10c cannot be skipped again.

The trailing comment on a test names the mutants it kills (`local/mutate.py`).
"""

import contextlib
import io
import json
import re
import shlex
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from snowball_bootstrap import cli, config, decide as decide_module, ledgercheck, wiring
from snowball_bootstrap.config import ConfigError, load_summary

import test_exit_checks
import test_state
from helpers import CONTROL_STEP, GO, LOOP_YML, commit, ledger_bytes, ledger_rows, posix_only
from test_exit_checks import TARGET, in_job, workflow

INVALID, ACCEPTED = "founder_ledger_invalid", "founder_ledger_accepted_invalid"
EXIT_JOBS = {"getir": "success", "kos": "success"}
ROOT = Path(__file__).resolve().parents[3]
EXCEPTION = {"stage": 0, "carry_to": 1, "reason": "E287: the plant was not made before the Founder started"}
CARRY = "c" * 64  # sha256(canonical(key)) of the plant the carried stage measures (`25` 10c)
HANDED = dict(EXCEPTION, carry_commitment=CARRY)  # as pull hands it to decide


# ---------------------------------------------------------------- #kurucu-defteri: closing an accepted row (E280)


def closing(rows, target, start=None, **fields):
    """One valid row after ``rows`` that names ``target`` in ``supersedes``."""
    return ledger_rows(1, start=start or len(rows) + 1, prev=rows[-1]["row_hash"],
                       edits={0: dict({"supersedes": target}, **fields)})


class SupersedingAnAcceptedRow(unittest.TestCase):
    """`tohum/13`, `26`: a row the referee accepted is never rewritten; one that breaks a meaning rule is closed by a
    later row, and the exit names both."""

    def accepted(self):
        """Three rows the referee accepted before it checked rows, the second outside the kind set."""
        return ledger_rows(3, edits={1: {"kind": "learning"}})

    def test_a_later_valid_row_closes_an_accepted_row_outside_the_kind_set(self):  # ledger_supersession_ignored
        rows = self.accepted()
        base = ledger_bytes(rows)
        self.assertEqual(ledgercheck.check(ledger_bytes(rows + ledger_rows(1, start=4, prev=rows[-1]["row_hash"])), base,
                                           whole=True), [f"{ACCEPTED}:kind:L2"])
        head = ledger_bytes(rows + closing(rows, rows[1]["row_hash"]))
        self.assertEqual(ledgercheck.check(head, base, whole=False), [])
        self.assertEqual(ledgercheck.judge(head, base, whole=True), ([], [(2, 4)]))
        self.assertEqual(ledgercheck.check(head, base, whole=True), [])

    def test_each_meaning_rule_is_closed_alike_and_a_second_closer_changes_nothing(self):
        rows = ledger_rows(3, edits={0: {"part": "events"}, 1: {"supersedes": "0" * 64}})
        base = ledger_bytes(rows)
        self.assertEqual(ledgercheck.check(base, base, whole=True), [f"{ACCEPTED}:part:L1", f"{ACCEPTED}:supersedes:L2"])
        closers = ledger_rows(3, start=4, prev=rows[-1]["row_hash"], edits={
            0: {"supersedes": rows[0]["row_hash"]}, 1: {"supersedes": rows[1]["row_hash"]},
            2: {"supersedes": rows[0]["row_hash"]}})
        self.assertEqual(ledgercheck.judge(ledger_bytes(rows + closers), base, whole=True), ([], [(1, 4), (2, 5)]))

    def test_supersedes_names_an_earlier_row_that_breaks_a_meaning_rule_and_nothing_else(self):
        # ledger_supersedes_unchecked ledger_supersedes_names_any_row
        rows = self.accepted()
        for target in (rows[0]["row_hash"], "f" * 64, [rows[1]["row_hash"]], None):
            head = ledger_bytes(rows + closing(rows, target))
            with self.subTest(target=target):
                self.assertEqual(ledgercheck.check(head, ledger_bytes(rows), whole=False), [f"{INVALID}:supersedes:L4"])
                self.assertEqual(ledgercheck.check(head, ledger_bytes(rows), whole=True),
                                 [f"{ACCEPTED}:kind:L2", f"{INVALID}:supersedes:L4"])

    def test_a_row_the_push_adds_is_refused_whatever_follows_it(self):  # ledger_new_rows_closable
        rows = ledger_rows(2)
        bad = ledger_rows(1, start=3, prev=rows[-1]["row_hash"], edits={0: {"kind": "learning"}})
        head = ledger_bytes(rows + bad + closing(rows + bad, bad[0]["row_hash"]))
        self.assertEqual(ledgercheck.check(head, ledger_bytes(rows), whole=False), [f"{INVALID}:kind:L3"])
        self.assertEqual(ledgercheck.judge(head, ledger_bytes(rows), whole=True), ([f"{INVALID}:kind:L3"], []))

    def test_broken_bytes_or_chains_are_never_closed(self):  # ledger_integrity_closable
        good = ledger_rows(3)
        tampered = ledger_bytes([good[0], dict(good[1], payload={"summary": "edited", "refs": []}), good[2]])
        head = tampered + ledger_bytes(closing(good, good[1]["row_hash"]))
        self.assertEqual(ledgercheck.check(head, tampered, whole=False), [f"{INVALID}:supersedes:L4"])
        self.assertEqual(ledgercheck.check(head, tampered, whole=True),
                         [f"{ACCEPTED}:row_hash:L2", f"{INVALID}:supersedes:L4"])

    def test_only_a_valid_row_closes(self):
        rows = self.accepted()
        for fields in ({"kind": "lesson"}, {"part": "events"}):
            head = ledger_bytes(rows + closing(rows, rows[1]["row_hash"], **fields))
            rule = "kind" if "kind" in fields else "part"
            self.assertEqual(ledgercheck.judge(head, ledger_bytes(rows), whole=True),
                             ([f"{ACCEPTED}:kind:L2", f"{INVALID}:{rule}:L4"], []), fields)

    def test_an_unclosed_meaning_break_is_the_founders_and_broken_bytes_are_not(self):
        # meaning_break_not_the_founders integrity_break_counted
        for rule, founders in (("kind", True), ("part", True), ("supersedes", True), ("row_hash", False),
                               ("prev_hash", False), ("not_json", False), ("too_deep", False)):
            reason = {"kind": "exit_condition", "ref": f"{ACCEPTED}:{rule}:L7"}
            self.assertEqual(decide_module.counts_against_founder(reason), founders, rule)
        self.assertTrue(decide_module.counts_against_founder({"kind": "exit_condition", "ref": f"{INVALID}:row_hash:L9"}))
        self.assertFalse(decide_module.counts_against_founder({"kind": "exit_condition", "ref": "not_checked:spec"}))


class SupersedingAtTheExit(test_exit_checks.ExitFlow):
    def test_the_closing_row_rides_along_with_the_exit_request_and_the_result_names_both(self):
        # exit_closures_not_signed
        self.freeze_stage0()
        self.accept({"referee/ledger/chain.py": "x = 1\n"})
        rows = ledger_rows(3, edits={1: {"kind": "learning"}})
        self.state["last_accepted_sha"] = commit(self.brain, {"founder-ledger.jsonl": ledger_bytes(rows)},
                                                 "accepted under the seed that did not check rows")
        meta = self.ask_exit({"founder-ledger.jsonl": ledger_bytes(rows + closing(rows, rows[1]["row_hash"]))})
        self.assertEqual(meta["exit_checks"]["kurucu-defteri"], {"status": "ok", "reasons": [],
                                                                 "why": "L2 superseded by L4"})
        result = self.finish(meta, run=self.green_run(meta), jobs=EXIT_JOBS)
        self.assertEqual(result["exit"]["checks"]["kurucu-defteri"]["why"], "L2 superseded by L4")
        self.assertFalse([m for m in result["exit"]["missing"] if m.startswith("founder_ledger")])

    def test_left_unclosed_it_keeps_the_exit_closed_and_counts(self):
        self.freeze_stage0()
        self.accept({"referee/ledger/chain.py": "x = 1\n"})
        rows = ledger_rows(3, edits={1: {"kind": "learning"}})
        self.state["last_accepted_sha"] = commit(self.brain, {"founder-ledger.jsonl": ledger_bytes(rows)}, "accepted")
        meta = self.ask_exit()
        result = self.finish(meta, run=self.green_run(meta), jobs=EXIT_JOBS)
        self.assertIn(f"{ACCEPTED}:kind:L2", result["exit"]["missing"])
        self.assertEqual(result["state"]["reject_streaks"].get(f"exit_condition:{ACCEPTED}:kind:L2"), 1)


# ---------------------------------------------------------------- #is-akisi: the control command (E282)


class LoopControlCommand(unittest.TestCase):
    """`asama-0/01` D0, `29p`: every loop job's first step runs the seed's `control` on the referee repository's
    `control.json`. A kill switch that is not explicitly off, or a budget brake, stops the job (exit 2, no `go`); a
    scheduled run while `loop_schedule` is not `true` is paused (`go=false`, green); the operator's dispatch goes."""

    ON = {"kill_switch": False, "budget_state": "ok", "loop_schedule": True}

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "control.json"
        self.out = Path(self.tmp.name) / "github_output"

    def control(self, data, job="cek", event="schedule", argv=None):
        if data is not None:
            self.path.write_text(json.dumps(data))
        self.out.write_text("")
        argv = argv or ["--control", str(self.path), "--job", job, "--event", event, "--github-output", str(self.out)]
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            try:
                rc = cli.main(["control", *argv])
            except SystemExit as exc:  # argparse refuses a malformed command line
                rc = exc.code
        return rc, self.out.read_text()

    def test_a_scheduled_run_goes_only_while_the_schedule_is_on(self):  # loop_schedule_ignored loop_schedule_truthy
        self.assertEqual(self.control(self.ON), (0, "go=true\n"))
        for paused in ({"kill_switch": False, "budget_state": "ok"}, dict(self.ON, loop_schedule=False),
                       dict(self.ON, loop_schedule="true"), dict(self.ON, loop_schedule=1)):
            self.assertEqual(self.control(paused), (0, "go=false\n"), paused)

    def test_the_operators_dispatch_goes_whatever_the_schedule(self):
        for data in (self.ON, {"kill_switch": False, "budget_state": "ok"}):
            for job in wiring.JOBS:
                self.assertEqual(self.control(data, job=job, event="workflow_dispatch"), (0, "go=true\n"), job)

    def test_the_kill_switch_or_the_budget_brake_stops_the_job(self):  # loop_control_ignores_the_switch
        for data in (dict(self.ON, kill_switch=True), {"budget_state": "ok", "loop_schedule": True},
                     dict(self.ON, kill_switch="false"), {"kill_switch": False, "loop_schedule": True},
                     dict(self.ON, budget_state="monthly_cap_usd"), ["not", "an object"]):
            for event in ("schedule", "workflow_dispatch"):
                self.assertEqual(self.control(data, event=event), (2, ""), (data, event))
        self.path.unlink()
        self.assertEqual(self.control(None), (2, ""))

    def test_any_other_event_or_job_stops_the_job(self):  # loop_event_unchecked loop_job_unchecked
        for event in ("push", "pull_request", ""):
            self.assertEqual(self.control(self.ON, event=event), (2, ""), event)
        for job in ("lint", "", "CEK"):
            self.assertEqual(self.control(self.ON, job=job), (2, ""), job)

    def test_the_loop_reading_needs_all_four_flags(self):  # loop_flags_partial
        self.path.write_text(json.dumps(self.ON))
        for missing in range(4):
            pairs = [["--control", str(self.path)], ["--job", "cek"], ["--event", "schedule"],
                     ["--github-output", str(self.out)]]
            del pairs[missing]
            rc, written = self.control(None, argv=[a for pair in pairs for a in pair])
            self.assertEqual((rc != 0, written), (True, ""), missing)

    def test_the_command_in_the_step_is_one_the_seed_accepts(self):
        line = CONTROL_STEP.splitlines()[-1].strip()
        argv = shlex.split(line)
        self.assertEqual(argv[:4], ["python3", "-m", "snowball_bootstrap", "control"])
        args = cli.build_parser().parse_args(argv[3:])
        self.assertEqual((args.control, args.job, args.event, args.github_output),
                         ("../control.json", "$LOOP_JOB", "$GITHUB_EVENT_NAME", "$GITHUB_OUTPUT"))


class EveryJobStartsWithTheControlStep(unittest.TestCase):
    """Test 46 (`asama-0/09`; `tohum/08` 1): "her işin ilk adımı `control` ve kill switch açıkken iş durur", decided by
    reading the file (`29p`): the first step is the seed's step exactly, with the job's own name; every later step waits
    for its `go`; nothing above it changes where or how it runs."""

    def check(self, text):
        return wiring.check({"loop.yml": text})

    def test_the_fixture_keeps_the_rule(self):  # control_run_drifts
        self.assertEqual(self.check(workflow()), [])
        doc = wiring.parse(LOOP_YML.encode())
        for name in wiring.JOBS:
            self.assertEqual(doc["jobs"][name]["steps"][0], wiring.control_step(name), name)

    def test_the_first_step_is_the_seeds_control_step_exactly(self):  # control_step_unchecked control_step_any_job
        python = 'python3 -m snowball_bootstrap control --control ../control.json'
        for old, new in ((python, 'echo go=true >> "$GITHUB_OUTPUT"\n          ' + python),
                         ("LOOP_JOB: getir", "LOOP_JOB: cek"), ("        id: control\n", ""),
                         ("        id: control\n", "        id: control\n        continue-on-error: true\n"),
                         ("        id: control\n", "        id: control\n        if: always()\n"),
                         ("        id: control\n", "        id: control\n        shell: python {0}\n"),
                         ("          LOOP_JOB: getir\n", "          LOOP_JOB: getir\n          PYTHONSAFEPATH: '1'\n")):
            with self.subTest(old=old, new=new):
                self.assertEqual(self.check(workflow(*in_job("getir", old, new))), ["workflow_control_step:getir"])
        for job in wiring.JOBS:  # the steps of one job swapped: the control step is no longer the first
            control = CONTROL_STEP.replace("@JOB@", job)
            rest = test_exit_checks.job_block(job).split(control, 1)[1]
            first = re.match(r"(      - [^\n]*\n(?:        [^\n]*\n|          [^\n]*\n)*)", rest).group(1)
            swapped = workflow(control + first, first + control)
            self.assertIn(f"workflow_control_step:{job}", self.check(swapped), job)

    def test_every_later_step_waits_for_go(self):  # control_gate_unchecked control_gate_second_step_only
        gate = f"        if: {GO}\n"
        fetch = "        run: python3 -m loop fetch\n" + gate
        for new in ("", "        if: always()\n", f"        if: {GO} || always()\n", "        if: ${{ " + GO + " }}\n",
                    "        if: steps.control.outputs.go != 'false'\n"):
            with self.subTest(new=new):
                self.assertEqual(self.check(workflow(fetch, "        run: python3 -m loop fetch\n" + new)),
                                 ["workflow_control_gate:getir:2"])
        # Past the second step too: `kos` runs the Founder's code in its third.
        for job, script in (("kos", "python3 -m loop run"), ("cek", 'python3 -m loop pull --out "$RUNNER_TEMP/pulled"')):
            with self.subTest(job=job):
                self.assertEqual(self.check(workflow(*in_job(job, f"{script}\n{gate}", f"{script}\n"))),
                                 [f"workflow_control_gate:{job}:3"])

    def test_nothing_above_the_control_step_changes_how_it_runs(self):
        # control_context_unchecked control_context_container control_context_workflow control_context_services
        self.assertEqual(self.check(workflow("permissions: {}\njobs:", "permissions: {}\nenv:\n  PYTHONSAFEPATH: '1'\njobs:")),
                         ["workflow_control_context:workflow"])
        service = "    services:\n      warm:\n        image: docker.io/library/busybox:1.36\n"
        for above in ("    env:\n      PYTHONSAFEPATH: '1'\n", "    defaults:\n      run:\n        working-directory: x\n",
                      "    container: docker.io/library/python:3.12\n", service,
                      service + "        volumes:\n          - /home/runner/work/_temp:/t\n",
                      "    snapshot: image\n"):
            with self.subTest(above=above):
                self.assertEqual(self.check(workflow(*in_job("kos", "    steps:\n", above + "    steps:\n"))),
                                 ["workflow_control_context:kos"])

    def test_what_stands_above_the_control_step_is_named_not_guessed(self):
        """E296: a list of what may not stand there missed `services`, whose containers start before step 1; the rule
        names what may. Each key it names passes, as the live loop's keys do."""
        # control_context_allows_too_little
        above = ("    name: k\n    timeout-minutes: 60\n    concurrency:\n      group: kos\n    environment: e\n"
                 "    continue-on-error: false\n    outputs:\n      x: y\n    strategy:\n      fail-fast: true\n")
        top = "name: loop\nrun-name: loop\nconcurrency:\n  group: loop\n  cancel-in-progress: false\n"
        self.assertEqual(self.check(workflow(*in_job("kos", "    steps:\n", above + "    steps:\n"), "name: loop\n", top)),
                         [])
        self.assertEqual(set(wiring.JOB_KEYS) & {"env", "defaults", "container", "services"}, set())
        self.assertEqual(set(wiring.WORKFLOW_KEYS) & {"env", "defaults"}, set())

    def test_the_page_says_what_the_check_holds(self):
        page = (ROOT / "spec" / "tohum" / "29p-kontrol-komutu.md").read_text(encoding="utf-8")
        for line in wiring.CONTROL_RUN.splitlines():
            self.assertIn(line, page)
        for text in (GO, "LOOP_JOB", "go=true", "go=false", "loop_schedule", "workflow_dispatch",
                     "workflow_control_step", "workflow_control_gate", "workflow_control_context", "`services`"):
            self.assertIn(text, page)
        rule = page.split("**`wiring` kuralı**", 1)[1].split("**Sınır.**", 1)[0]
        for key in wiring.WORKFLOW_KEYS + wiring.JOB_KEYS:  # the keys the rule names are the page's (E296)
            self.assertIn(f"`{key}`", rule, key)


# ---------------------------------------------------------------- #durustluk: the owner's exception (E287, E294)


class OwnerExceptionRead(unittest.TestCase):
    """`26c`, `02` "Sahip istisnası": one anchor, one stage, one carry target; a commitment beside it is the plant the
    carried stage measures (made before that stage starts)."""

    BASE = {"seed_commit": "a" * 40, "seed_tree_sha256": "b" * 64}

    def load(self, doc):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "setup").mkdir()
            (Path(tmp) / "setup" / "summary.json").write_text(json.dumps(doc))
            return load_summary(Path(tmp))

    def test_the_commitment_and_the_exception_are_read_strictly(self):
        # honesty_exception_keys_unchecked honesty_exception_stage_unchecked honesty_exception_carry_unchecked
        # honesty_commitment_unchecked honesty_exception_stage_bool honesty_exception_carry_bool
        self.assertEqual((self.load(self.BASE).honesty_commitment, self.load(self.BASE).honesty_exception), (None, None))
        self.assertEqual(self.load(dict(self.BASE, honesty_commitment="c" * 64)).honesty_commitment, "c" * 64)
        self.assertEqual(self.load(dict(self.BASE, honesty_exception=EXCEPTION)).honesty_exception,
                         config.HonestyException(0, 1, EXCEPTION["reason"]))
        both = self.load(dict(self.BASE, honesty_commitment="c" * 64, honesty_exception=EXCEPTION))
        self.assertEqual((both.honesty_commitment, both.honesty_exception.carry_to), ("c" * 64, 1))
        for bad in ({"honesty_commitment": "C" * 64}, {"honesty_commitment": "c" * 63}, {"honesty_commitment": None},
                    {"honesty_exception": dict(EXCEPTION, anchor="durustluk")},
                    {"honesty_exception": {k: v for k, v in EXCEPTION.items() if k != "reason"}},
                    {"honesty_exception": dict(EXCEPTION, stage=1, carry_to=2)},
                    {"honesty_exception": dict(EXCEPTION, stage=False)}, {"honesty_exception": dict(EXCEPTION, carry_to=2)},
                    {"honesty_exception": dict(EXCEPTION, stage=True)}, {"honesty_exception": dict(EXCEPTION, carry_to=True)},
                    {"honesty_exception": dict(EXCEPTION, reason=" ")}, {"honesty_exception": [EXCEPTION]}):
            with self.subTest(bad=bad), self.assertRaises(ConfigError):
                self.load(dict(self.BASE, **bad))


class OwnerExceptionAtTheExit(unittest.TestCase):
    state = test_exit_checks.ExitDecision.state
    meta = test_exit_checks.ExitDecision.meta
    run_ = test_exit_checks.ExitDecision.run_
    ok = staticmethod(test_exit_checks.ExitDecision.ok)

    def test_it_takes_durustluk_and_nothing_else_off_the_missing_list(self):
        # owner_exception_ignored owner_exception_takes_any_anchor owner_exception_not_signed owner_exception_carry_unsigned
        res = self.run_(self.meta(self.state(), self.ok(), honesty_exception=HANDED))
        self.assertEqual(res["exit"]["missing"], ["not_checked:spec"])
        self.assertEqual(res["exit"]["owner_exception"], {"anchor": "durustluk", "stage": 0, "carry_to": 1,
                                                          "reason": EXCEPTION["reason"], "carry_commitment": CARRY,
                                                          "measured": False})
        failed = dict(self.ok(), genellik={"status": "failed", "reasons": ["target_name_in_referee:x"], "why": ""})
        res = self.run_(self.meta(self.state(), failed, honesty_exception=HANDED))
        self.assertEqual(res["exit"]["missing"], ["target_name_in_referee:x", "not_checked:spec"])
        res = self.run_(self.meta(self.state(), self.ok()))
        self.assertNotIn("owner_exception", res["exit"])
        self.assertIn("not_checked:durustluk", res["exit"]["missing"])

    def test_with_everything_else_measured_the_exit_passes_by_the_owners_exception(self):
        only = {"durustluk": decide_module.EXIT_NOT_CHECKED["durustluk"]}
        with mock.patch.object(decide_module, "EXIT_NOT_CHECKED", only):
            res = self.run_(self.meta(self.state(), self.ok()))
            self.assertEqual((res["verdict"], res["exit"]["missing"]), ("rejected", ["not_checked:durustluk"]))
            res = self.run_(self.meta(self.state(), self.ok(), honesty_exception=HANDED))
        self.assertEqual((res["verdict"], res["exit"]["transferable"]), ("accepted", True))
        self.assertEqual(res["exit"]["owner_exception"]["anchor"], "durustluk")

    def test_without_the_carried_stages_plant_it_takes_nothing_off(self):
        """E297: the exception carries #durustluk to Stage 1, which measures it on a plant made before it starts. With
        no commitment beside the exception, Stage 1 would open unplanted and its exit, with no second exception, could
        never close: Stage 0's stays closed instead, as not_checked (not the Founder's), saying why."""
        # owner_exception_without_its_carry carry_unplanted_unsaid
        only = {"durustluk": decide_module.EXIT_NOT_CHECKED["durustluk"]}
        with mock.patch.object(decide_module, "EXIT_NOT_CHECKED", only):
            for carry in (None, "C" * 64, "c" * 63, 64, ["c" * 64]):
                handed = dict(EXCEPTION, carry_commitment=carry)
                with self.subTest(carry=carry):
                    res = self.run_(self.meta(self.state(), self.ok(), honesty_exception=handed))
                    self.assertEqual((res["verdict"], res["exit"]["missing"]), ("rejected", ["not_checked:durustluk"]))
                    self.assertNotIn("owner_exception", res["exit"])
                    reason = next(r for r in res["reasons"] if r["ref"] == "not_checked:durustluk")
                    self.assertIn("no honesty_commitment beside it", reason["detail"])
                    self.assertIn("E79", reason["detail"])
                    self.assertFalse(decide_module.counts_against_founder(reason))
            res = self.run_(self.meta(self.state(), self.ok(), honesty_exception=EXCEPTION))
            self.assertEqual(res["exit"]["missing"], ["not_checked:durustluk"])
            res = self.run_(self.meta(self.state(), self.ok()))
            reason = next(r for r in res["reasons"] if r["ref"] == "not_checked:durustluk")
            self.assertNotIn("honesty_commitment", reason["detail"])


class OwnerExceptionFlow(test_exit_checks.ExitFlow):
    def test_pull_hands_the_exception_to_the_exit_and_to_nothing_else(self):
        # owner_exception_not_handed owner_exception_carry_not_handed
        self.write_summary(honesty_exception=EXCEPTION, honesty_commitment=CARRY)
        self.freeze_stage0()
        commit(self.brain, {"referee/ledger/chain.py": "x = 1\n",
                            "snowball-tests.json": test_exit_checks.test_flow.all_tests_manifest([1])}, "code")
        self.assertIsNone(self.pull()["honesty_exception"])
        self.state["last_evaluated_sha"] = None
        self.accept({"referee/ledger/chain.py": "x = 2\n"})
        meta = self.ask_exit()
        self.assertEqual(meta["honesty_exception"], HANDED)
        result = self.finish(meta, run=self.green_run(meta), jobs=EXIT_JOBS)
        self.assertNotIn("not_checked:durustluk", result["exit"]["missing"])
        self.assertEqual((result["exit"]["owner_exception"]["measured"],
                          result["exit"]["owner_exception"]["carry_commitment"]), (False, CARRY))

    def test_an_exception_without_the_commitment_reaches_the_exit_and_keeps_it_closed(self):
        self.write_summary(honesty_exception=EXCEPTION)
        self.freeze_stage0()
        self.accept({"referee/ledger/chain.py": "x = 1\n"})
        meta = self.ask_exit()
        self.assertEqual(meta["honesty_exception"], dict(EXCEPTION, carry_commitment=None))
        result = self.finish(meta, run=self.green_run(meta), jobs=EXIT_JOBS)
        self.assertIn("not_checked:durustluk", result["exit"]["missing"])
        self.assertNotIn("owner_exception", result["exit"])

    def test_a_target_name_in_the_reason_is_withheld(self):  # owner_exception_reason_published
        self.write_summary(targets=[TARGET], honesty_exception=dict(EXCEPTION, reason="E287, as Zorbalix asked"))
        self.freeze_stage0()
        self.accept({"referee/ledger/chain.py": "x = 1\n"})
        meta = self.ask_exit()
        self.assertRegex(meta["honesty_exception"]["reason"], r"^sha256:[0-9a-f]{16}$")
        self.assertNotIn("zorbalix", json.dumps(self.finish(meta, jobs=EXIT_JOBS)).casefold())


# ---------------------------------------------------------------- E293: Stage 0 starts with its setup


class StageZeroStartsWithItsSetup(unittest.TestCase):
    """`25` 10a and 10c, `25` "Aşama 0 bu özet olmadan başlamaz": the referee builds no first state from a summary
    without the copy target's identifiers and the honesty commitment, with or without the owner's exception (E297:
    beside it, the commitment is the carried stage's plant). A state that already exists is never held to it: the
    gate is where Stage 0 starts, or restarts from a lost state (`25` "Durum kaybolursa")."""

    setUp = test_state.StateTest.setUp
    tearDown = test_state.StateTest.tearDown
    fetch = test_state.StateTest.fetch
    BASE = {"seed_commit": "a" * 40, "seed_tree_sha256": "b" * 64}
    TOY = dict(TARGET, id="toy", repo="owner/toy", kind="toy", base_sha=None, identifiers=[], unit_candidates=[])

    def start(self, **fields):
        (self.root / "state" / "state.json").unlink(missing_ok=True)  # each start is judged on its own
        (self.root / "setup" / "summary.json").write_text(json.dumps(dict(self.BASE, **fields)))
        err = io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            rc = self.fetch()
        return rc, err.getvalue()

    def test_without_its_setup_stage_zero_does_not_start(self):
        # start_gate_off start_without_commitment start_without_copy start_on_the_exception_alone
        targets = [TARGET, self.TOY]
        for fields, named in (({}, ("targets[]", "honesty_commitment")), ({"targets": targets}, ("honesty_commitment",)),
                              ({"targets": targets, "honesty_exception": EXCEPTION}, ("honesty_commitment",)),
                              ({"honesty_commitment": "c" * 64}, ("targets[]",)),
                              ({"targets": [self.TOY], "honesty_commitment": "c" * 64}, ("targets[]",)),
                              ({"targets": [dict(TARGET, identifiers=[])], "honesty_commitment": "c" * 64}, ("targets[]",))):
            rc, err = self.start(**fields)
            with self.subTest(fields=sorted(fields)):
                self.assertEqual(rc, 2)
                for name in named:
                    self.assertIn(name, err)
                self.assertFalse((self.root / "state" / "state.json").exists())

    def test_with_it_the_first_state_is_built(self):  # start_refuses_the_exception
        for fields in ({"targets": [TARGET], "honesty_commitment": "c" * 64},
                       {"targets": [TARGET, self.TOY], "honesty_exception": EXCEPTION, "honesty_commitment": "c" * 64}):
            self.assertEqual(self.start(**fields)[0], 0, sorted(fields))
            state = json.loads((self.root / "state" / "state.json").read_text())
            self.assertEqual((state["origin"], state["last_accepted_sha"]), ("initial", "a" * 40))


@posix_only
class AStateThatExistsIsNeverHeldToTheSetup(unittest.TestCase):
    def test_a_running_pilot_reads_its_state_from_a_bare_summary(self):
        import test_decision
        case = test_decision.CommandWiring("test_decide_command_hands_artifacts_jobs_and_policy_to_decide")
        case.setUp()
        self.addCleanup(case.tearDown)
        self.addCleanup(case.doCleanups)
        case.previous_state_zip(test_decision.state0())
        self.assertEqual(case.fetch_ok(), 0)


if __name__ == "__main__":
    unittest.main()
