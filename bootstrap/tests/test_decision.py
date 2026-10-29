"""The referee's decision logic, measured. Written from a mutation run (102 mutants of decide, state, classify, cli,
controls and vectors; 69 survived the earlier tests). The trailing comment on each test names the mutants it kills.
"""

import hashlib
import io
import json
import os
import unittest
import zipfile
from pathlib import Path

from snowball_bootstrap import cli, ghapi, state as st
from snowball_bootstrap.classify import classify
from snowball_bootstrap.config import ConfigError, Policy
from snowball_bootstrap.container import RunResult
from snowball_bootstrap.controls import run_controls
from snowball_bootstrap.decide import decide
from snowball_bootstrap.reproduce import reproducer_key

import test_flow
import test_state
from helpers import DRILL, EVERY_GROUP, STATS, FakeRunner, commit, install_fake_claude, ok_result, posix_only, sh, submit

A, B, C = "a" * 40, "b" * 40, "c" * 40


def state0(**kw):
    s = {"schema": "snowball-bootstrap-state/2", "origin": "artifact", "last_accepted_sha": A,
         "last_evaluated_sha": None, "frozen_specs": {}, "rival_artifacts": [], "month": "2026-10",
         "month_spend_usd_micros": 1000, "stage_spend_usd_micros": 2000, "runs": 4, "reject_streaks": {},
         "repeat_events": 0, "outage_sha": None, "outage_count": 0, "outage_since": None, "outage_stop": None,
         "rival_side_streak": 0, "open_refutations": [], "open_claims": [], "pending_rival": None}
    s.update(kw)
    return s


def survived(*shas):
    return [{"sha": s, "outcome": "survived"} for s in shas]


def meta_(kind, state, **kw):
    m = {"head": B, "base": A, "kind": kind, "state": state, "changed": [], "pre_reasons": [], "evaluate": True,
         "run_tests": kind in ("code", "exit"), "run_rival": kind in ("spec", "code"), "manifest": None,
         "exit_request": None, "referee_tree_sha256": None, "spec_dir_hashes": {}}
    m.update(kw)
    return m


def green_run():
    return {"controls": [{"id": "exit_one", "ok": True}],
            "tests": [{"id": "T13", "cmd_sha256": "c", "ok": True, "output_tail": ""}],
            "vectors": [], "licenses": [], "green": True}


def refuted(*claims, cost=7):
    """One attempt per claim, each with its own reproducer: a proven defect is named by its reproducer (E08)."""
    attempts = [{"claim": c, "evidence_refs": [], "reproducer": {"cmd": f"check {c}", "expect_exit": 1}} for c in claims]
    return {"verdict": "refuted", "attempts": attempts, "reasons": [], "cost_usd_micros": cost,
            "reproducer_count": len(attempts)}


def not_refuted(cost=7):
    return {"verdict": "not_refuted", "attempts": [], "reasons": [], "cost_usd_micros": cost, "reproducer_count": 0}


def unresolved(*reasons, cost=0):
    return {"verdict": "unresolved", "attempts": [], "reasons": list(reasons), "cost_usd_micros": cost,
            "reproducer_count": 0}


CODE_JOBS = {"getir": "success", "kos": "success", "cagir": "success", "yeniden": "skipped"}


def run_decide(meta, run=None, rival=None, repro=None, jobs=None, min_attempts=2, limit=3):
    return decide(meta, run, rival, repro, jobs or {}, min_attempts, limit)


class RivalOutcomeJudgement(unittest.TestCase):
    def test_a_failed_reproduction_job_is_an_outage_not_an_acceptance(self):  # D02 D03
        res = run_decide(meta_("code", state0()), green_run(), refuted("c"), None,
                         dict(CODE_JOBS, yeniden="failure"))
        self.assertEqual(res["verdict"], "rejected")
        self.assertEqual([(r["kind"], r["ref"]) for r in res["reasons"]], [("infra", "yeniden:failure")])
        self.assertIsNone(res["state"]["last_evaluated_sha"])
        self.assertEqual(res["state"]["reject_streaks"], {})
        self.assertEqual((res["state"]["outage_sha"], res["state"]["outage_count"]), (B, 1))  # it is counted as an outage

    def test_an_unresolved_rival_is_rejected_even_without_a_reason(self):  # D04
        for rival in (unresolved(), {"verdict": "approved", "attempts": [], "reasons": [], "cost_usd_micros": 0,
                                     "reproducer_count": 0}):
            res = run_decide(meta_("code", state0()), green_run(), rival, [], CODE_JOBS)
            self.assertEqual(res["verdict"], "rejected", rival)
            self.assertEqual([(r["kind"], r["ref"]) for r in res["reasons"]], [("rival_unresolved", "unresolved")])
            self.assertEqual(res["state"]["last_evaluated_sha"], B)  # a verdict-less rival is a judgement, not an outage

    def test_every_rival_call_is_charged_to_both_budgets_and_they_add_up(self):  # D09 D10 D11 D12
        first = run_decide(meta_("code", state0()), green_run(), unresolved("max_turns", cost=500), [], CODE_JOBS)
        self.assertEqual((first["state"]["month_spend_usd_micros"], first["state"]["stage_spend_usd_micros"]),
                         (1500, 2500))
        timeout = run_decide(meta_("spec", first["state"], head=C), None,
                             unresolved("api_error:TimeoutExpired", cost=300), None, {"cagir": "success"})
        self.assertEqual((timeout["state"]["month_spend_usd_micros"], timeout["state"]["stage_spend_usd_micros"]),
                         (1800, 2800))
        valid = run_decide(meta_("code", timeout["state"], head="d" * 40), green_run(), not_refuted(cost=700), [],
                           CODE_JOBS)
        self.assertEqual((valid["state"]["month_spend_usd_micros"], valid["state"]["stage_spend_usd_micros"]),
                         (2500, 3500))

    def test_a_reproducer_that_did_not_reproduce_does_not_block(self):  # D13
        res = run_decide(meta_("code", state0()), green_run(), refuted("c"), [{"attempt_index": 0, "reproduced": False}],
                         dict(CODE_JOBS, yeniden="success"))
        self.assertEqual((res["verdict"], res["reasons"]), ("accepted", []))

    def test_the_reason_names_the_attempt_that_reproduced(self):  # D14
        rival = refuted("first claim", "second claim")
        res = run_decide(meta_("code", state0()), green_run(), rival,
                         [{"attempt_index": 0, "reproduced": False}, {"attempt_index": 1, "reproduced": True}],
                         dict(CODE_JOBS, yeniden="success"))
        key = reproducer_key(rival["attempts"][1]["reproducer"])
        self.assertEqual([(r["kind"], r["ref"], r["detail"]) for r in res["reasons"]],
                         [("refutation_reproduced", f"repro:{key}", "second claim")])

    def test_failed_vectors_controls_and_an_empty_run_each_reject(self):  # D15 D16 D17
        for mutate, kind in ((lambda r: r.update(vectors=[{"id": "chain.V1.hash", "ok": False, "detail": "x"}]),
                              "vector_failed"),
                             (lambda r: r.update(controls=[{"id": "network_blocked", "ok": False}]), "infra"),
                             (lambda r: r.update(tests=[]), "zero_tests")):
            run = green_run()
            mutate(run)
            run["green"] = False
            res = run_decide(meta_("code", state0()), run, None, None, dict(CODE_JOBS, cagir="skipped"))
            self.assertEqual([r["kind"] for r in res["reasons"]], [kind])
            self.assertEqual(res["verdict"], "rejected")

    def test_a_missing_run_is_one_outage_not_also_a_zero_tests_rejection(self):  # D18
        res = run_decide(meta_("code", state0()), None, None, None, {"getir": "success", "kos": "failure",
                                                                     "cagir": "skipped"})
        self.assertEqual([r["kind"] for r in res["reasons"]], ["infra"])

    def test_a_secret_in_a_failing_vectors_detail_is_not_republished(self):  # V4
        token = "gh" + "p_" + "A" * 36
        run = green_run()
        run.update(vectors=[{"id": "chain.V1.hash", "ok": False, "detail": "got " + token}], green=False)
        res = run_decide(meta_("code", state0()), run, None, None, dict(CODE_JOBS, cagir="skipped"))
        self.assertEqual([r["kind"] for r in res["reasons"]], ["vector_failed"])
        self.assertNotIn(token, json.dumps(res))

    def test_an_unresolved_rival_is_not_an_independent_review(self):  # D28
        res = run_decide(meta_("code", state0()), green_run(), unresolved("max_turns", cost=5), [], CODE_JOBS)
        self.assertEqual(res["state"]["rival_artifacts"], [])

    def test_a_retried_commit_is_listed_as_reviewed_once(self):  # D29, E20
        first = run_decide(meta_("code", state0()), green_run(), refuted("c"), None, dict(CODE_JOBS, yeniden="failure"))
        self.assertEqual(first["state"]["rival_artifacts"], [])  # its reproducers never ran: not yet reviewed
        reuse = meta_("code", first["state"], run_rival=False, reuse_rival=True)
        again = run_decide(reuse, green_run(), None, None, dict(CODE_JOBS, cagir="skipped", yeniden="failure"))
        self.assertEqual(again["state"]["pending_rival"], first["state"]["pending_rival"])
        done = run_decide(meta_("code", again["state"], run_rival=False, reuse_rival=True), green_run(), None,
                          [{"attempt_index": 0, "reproduced": False}], dict(CODE_JOBS, cagir="skipped", yeniden="success"))
        again2 = run_decide(meta_("code", done["state"]), green_run(), not_refuted(), [], CODE_JOBS)
        self.assertEqual(again2["state"]["rival_artifacts"], [{"sha": B, "outcome": "survived"}])

    def test_a_refutation_without_a_reproducer_does_not_block(self):  # D42
        rival = {"verdict": "refuted", "attempts": [{"claim": "c", "evidence_refs": []}], "reasons": [],
                 "cost_usd_micros": 7, "reproducer_count": 0}
        res = run_decide(meta_("code", state0()), green_run(), rival, [], CODE_JOBS)
        self.assertEqual((res["verdict"], res["reasons"]), ("accepted", []))

    FAKE_TOKEN = "gh" + "p_" + "A" * 36

    def failing_run_with_secret(self):
        run = green_run()
        run["tests"][0].update(ok=False, output_tail="AssertionError: token " + self.FAKE_TOKEN)
        run["green"] = False
        return run

    def test_the_signed_result_does_not_republish_a_secret_from_test_output(self):
        res = run_decide(meta_("code", state0()), self.failing_run_with_secret(), None, None,
                         dict(CODE_JOBS, cagir="skipped"))
        self.assertNotIn(self.FAKE_TOKEN, json.dumps(res))  # result["tests"][i]["output_tail"] carries it

    def test_a_secret_in_a_failing_tests_output_is_not_quoted_in_the_reason_and_every_run_is_counted(self):  # D34 D35
        res = run_decide(meta_("code", state0()), self.failing_run_with_secret(), None, None,
                         dict(CODE_JOBS, cagir="skipped"))
        reason = res["reasons"][0]
        self.assertEqual(reason["kind"], "test_failed")
        self.assertNotIn("detail", reason)
        self.assertEqual(len(reason["detail_sha256"]), 64)
        run = green_run()
        run["tests"][0].update(ok=False)
        run["green"] = False
        run["tests"][0]["output_tail"] = "AssertionError: 1 != 2"
        self.assertEqual(run_decide(meta_("code", state0()), run, None, None,
                                    dict(CODE_JOBS, cagir="skipped"))["reasons"][0]["detail"], "AssertionError: 1 != 2")
        self.assertEqual(res["state"]["runs"], 5)

    def test_a_rejected_spec_request_freezes_nothing(self):  # D25 D41
        res = run_decide(meta_("spec", state0(), spec_dir_hashes={"spec/asama-0": "e" * 64}), None, refuted("c"),
                         [{"attempt_index": 0, "reproduced": True}], {"cagir": "success", "yeniden": "success"})
        self.assertEqual((res["verdict"], res["state"]["frozen_specs"]), ("rejected", {}))
        self.assertEqual(res["state"]["last_accepted_sha"], A)

    def test_different_defects_are_not_the_same_rejection(self):
        st_ = state0()
        for n, claim in enumerate(("hash ignores prev_hash", "cp_lower is Wilson", "score counts twice"), start=1):
            res = run_decide(meta_("spec", st_, head=f"{n:040d}"), None, refuted(claim),
                             [{"attempt_index": 0, "reproduced": True}], {"cagir": "success", "yeniden": "success"})
            st_ = res["state"]
        self.assertEqual(res["learning"]["not_learning"], [])
        self.assertEqual(res["state"]["repeat_events"], 0)


class ReproducersReportRunnerFaults(unittest.TestCase):
    def test_exit_125_is_docker_failing_not_the_defect_being_absent(self):
        from snowball_bootstrap.reproduce import run_reproducers

        class DockerDown(FakeRunner):
            def run(self, cmd, **kw):
                return RunResult(125, b"", b"docker: error", 1)

        class Ordinary(FakeRunner):
            def run(self, cmd, **kw):
                return RunResult(1, b"boom", b"", 1)

        class EmptyTree(FakeRunner):  # the control run (E09): the command finds nothing to run
            def run(self, cmd, **kw):
                return RunResult(2, b"", b"no such file", 1)

        attempts = [{"claim": "c", "evidence_refs": [], "reproducer": {"cmd": "x", "expect_exit": 1}}]
        down = run_reproducers(DockerDown(Path(".")), attempts, 5, control=EmptyTree(Path(".")))[0]
        self.assertEqual((down["reproduced"], down["runner_fault"]), (False, True))
        ordinary = run_reproducers(Ordinary(Path(".")), attempts, 5, control=EmptyTree(Path(".")))[0]
        self.assertEqual((ordinary["reproduced"], ordinary["runner_fault"]), (True, False))


class RunnerFaults(unittest.TestCase):
    """A sandbox that failed says nothing about the push: outage, never a verdict (found by an Opus verifier)."""

    def test_a_failed_control_voids_the_whole_run(self):
        run = green_run()
        run.update(controls=[{"id": "exit_zero", "ok": False}], tests=[], green=False)
        for n in range(1, 4):  # three pushes in a row must not stop the Founder as not learning
            res = run_decide(meta_("code", state0(), head=f"{n:040d}"), run, None, None, dict(CODE_JOBS, cagir="skipped"))
            self.assertEqual([(r["kind"], r["ref"]) for r in res["reasons"]], [("infra", "kos:exit_zero")])
            self.assertEqual((res["state"]["reject_streaks"], res["learning"]["not_learning"]), ({}, []))
            self.assertIsNone(res["state"]["last_evaluated_sha"])
            self.assertEqual(res["state"]["outage_count"], 1)

    def test_docker_failing_in_the_middle_of_the_tests_is_an_outage(self):
        run = green_run()
        run["tests"][0].update(ok=False, exit=125)
        run["green"] = False
        res = run_decide(meta_("code", state0()), run, None, None, dict(CODE_JOBS, cagir="skipped"))
        self.assertEqual([(r["kind"], r["ref"]) for r in res["reasons"]], [("infra", "kos:docker")])
        self.assertIsNone(res["state"]["last_evaluated_sha"])
        self.assertEqual((res["state"]["outage_sha"], res["state"]["outage_count"]), (B, 1))

    def test_a_docker_fault_in_the_reproduction_container_is_an_outage_not_an_acceptance(self):
        res = run_decide(meta_("code", state0()), green_run(), refuted("c"),
                         [{"attempt_index": 0, "reproduced": False, "runner_fault": True, "exit": 125}],
                         dict(CODE_JOBS, yeniden="success"))
        self.assertEqual(res["verdict"], "rejected")  # never "accepted": a refutation nobody could test is no clearance
        self.assertEqual([(r["kind"], r["ref"]) for r in res["reasons"]], [("infra", "yeniden:docker")])
        self.assertIsNone(res["state"]["last_evaluated_sha"])
        self.assertEqual((res["state"]["outage_sha"], res["state"]["outage_count"]), (B, 1))

    def test_reproducers_that_were_not_run_cannot_clear_a_refutation(self):
        for yeniden in ("skipped", None):
            jobs = dict(CODE_JOBS)
            jobs.pop("yeniden") if yeniden is None else jobs.update(yeniden=yeniden)
            res = run_decide(meta_("code", state0()), green_run(), refuted("c"), None, jobs)
            self.assertEqual([(r["kind"], r["ref"]) for r in res["reasons"]], [("infra", f"yeniden:{yeniden}")], yeniden)
            self.assertEqual(res["state"]["outage_count"], 1, yeniden)

    def test_an_exhausted_budget_halts_the_run_but_is_never_the_founders_fault(self):
        st_ = state0()
        for n in range(1, 5):
            meta = meta_("spec", st_, head=f"{n:040d}", pre_reasons=["budget"], run_rival=False)
            res = run_decide(meta, None, None, None, {})
            self.assertEqual(res["verdict"], "rejected")
            self.assertEqual((res["state"]["reject_streaks"], res["learning"]["not_learning"]), ({}, []))
            st_ = res["state"]

    def test_the_run_of_a_real_but_unresolved_outage_week_never_reaches_not_learning(self):
        """A timeout books the per-run cap; ten of them empty a 30 USD stage budget. The budget then stops the
        run, and what follows must still not count against the Founder."""
        st_ = state0(stage_spend_usd_micros=29_000_000)
        for n in range(1, 4):
            res = run_decide(meta_("spec", st_, head=f"{n:040d}"), None, unresolved("api_error:TimeoutExpired", cost=3_000_000),
                             None, {"cagir": "success"})
            st_ = res["state"]
        for n in range(4, 8):
            res = run_decide(meta_("spec", st_, head=f"{n:040d}", pre_reasons=["budget"], run_rival=False), None, None, None, {})
            st_ = res["state"]
        self.assertEqual(res["learning"]["not_learning"], [])


class KindsAndExit(unittest.TestCase):
    def test_a_commit_with_nothing_to_judge_changes_no_memory(self):  # D24 D27 D40
        streaks = {"test_failed:T13": 2}
        res = run_decide(meta_("none", state0(reject_streaks=streaks, repeat_events=1)), None, None, None, {})
        self.assertEqual(res["verdict"], "noop")
        self.assertEqual(res["state"]["last_accepted_sha"], A)
        self.assertEqual((res["state"]["reject_streaks"], res["state"]["repeat_events"]), (streaks, 1))

    def exit_meta(self, state, done=range(1, 19), tree="f" * 64):
        manifest = {"tests": [], "done_mf": list(done), "lockfiles": []}
        return meta_("exit", state, manifest=manifest, referee_tree_sha256=tree,
                     exit_request={"stage": 0, "sha": A, "spec_sha256": "e" * 64})

    def test_exit_conditions_are_each_enforced(self):  # D19 D22 D23
        ready = state0(rival_artifacts=survived(A, "1" * 40, "2" * 40))
        good = run_decide(self.exit_meta(ready), green_run(), None, None, {"getir": "success", "kos": "success"})
        self.assertEqual((good["verdict"], good["exit"]["transferable"]), ("accepted", True))
        cases = ((dict(done=range(1, 18)), ready, "not_all_micro_features_done"),
                 (dict(), dict(ready, rival_artifacts=survived("1" * 40, "2" * 40)), "no_rival_attempt_on_exit_sha"),
                 (dict(tree=None), ready, "referee_tree_hash"))
        for kw, state, missing in cases:
            res = run_decide(self.exit_meta(state, **kw), green_run(), None, None, {"getir": "success", "kos": "success"})
            self.assertEqual(res["verdict"], "rejected", missing)
            self.assertEqual(res["exit"]["missing"], [missing])
            self.assertFalse(res["exit"]["transferable"], missing)  # D37

    def test_the_exit_needs_all_eighteen_micro_features_of_the_stage_table(self):
        """`asama-0/10` #testler: the 18 of `stage0.json`, not the 30 of the old table."""
        ready = state0(rival_artifacts=survived(A, "1" * 40, "2" * 40))
        jobs = {"getir": "success", "kos": "success"}
        for done, missing in ((range(1, 19), []), (range(1, 18), ["not_all_micro_features_done"]),
                              (range(1, 31), ["not_all_micro_features_done"])):
            res = run_decide(self.exit_meta(ready, done=done), green_run(), None, None, jobs)
            self.assertEqual(res["exit"]["missing"], missing, done)

    def test_the_exit_waits_for_every_vector_group_the_seed_still_lacks(self):
        """`asama-0/10` #testler: every group passes. A group the seed has no vectors for cannot, so the exit is
        refused until a seed epoch brings it; on a code push the same gap is a warning (below)."""
        ready = state0(rival_artifacts=survived(A, "1" * 40, "2" * 40))
        run = dict(green_run(), vector_groups_missing=["secrets", "genesis"])
        res = run_decide(self.exit_meta(ready), run, None, None, {"getir": "success", "kos": "success"})
        self.assertEqual(res["verdict"], "rejected")
        self.assertEqual(res["exit"]["missing"], ["vector_group_missing:secrets", "vector_group_missing:genesis"])
        self.assertFalse(res["exit"]["transferable"])

    def test_the_exit_block_carries_the_founders_repeat_count(self):  # D36
        res = run_decide(self.exit_meta(state0(rival_artifacts=survived(A, "1" * 40, "2" * 40), repeat_events=4)),
                         green_run(), None, None, {"getir": "success", "kos": "success"})
        self.assertEqual(res["exit"]["repeat_events"], 4)


def module_less(mf, test_id, stayed_green=False, exit_code=None, present=True):
    code = exit_code if exit_code is not None else (0 if stayed_green else 1)
    return {"mf": mf, "test_id": test_id, "module": "referee/x.py", "module_present": present, "exit": code,
            "timed_out": False, "stayed_green": stayed_green, "runner_fault": code == 125}


class ModuleLessRed(unittest.TestCase):
    """`asama-0/14`: a push that finishes MF k has k's tests run without k's module; a test that stays green there
    rejects the push as `module_less_green:MFk` (`tohum/04` 1)."""

    def code(self, run, module_less_mfs=(3,)):
        meta = meta_("code", state0(), module_less=list(module_less_mfs))
        return run_decide(meta, run, not_refuted(), [], CODE_JOBS)

    def test_a_test_that_stays_green_without_its_module_rejects_the_push(self):
        run = dict(green_run(), module_less=[module_less(3, "T20"), module_less(3, "T21", stayed_green=True)],
                   green=False)  # as run-tests says it, so the rival is not called on it
        res = self.code(run)
        self.assertEqual(res["verdict"], "rejected")
        self.assertEqual([(r["kind"], r["ref"]) for r in res["reasons"]], [("module_less_green", "MF3")])
        self.assertIn("T21 stayed green without referee/x.py", res["reasons"][0]["detail"])
        self.assertEqual(res["state"]["reject_streaks"], {"module_less_green:MF3": 1})  # the Founder's to fix

    def test_tests_that_all_fail_without_the_module_pass(self):
        run = dict(green_run(), module_less=[module_less(3, "T20"), module_less(3, "T21")])
        self.assertEqual(self.code(run)["verdict"], "accepted")

    def test_a_missing_module_path_is_said_in_the_detail(self):
        run = dict(green_run(), module_less=[module_less(3, "T20", stayed_green=True, present=False)], green=False)
        self.assertIn("the path was not in the tree", self.code(run)["reasons"][0]["detail"])

    def test_docker_failing_under_module_less_red_is_an_outage(self):
        run = dict(green_run(), module_less=[module_less(3, "T20", exit_code=125), module_less(3, "T21")], green=False)
        res = self.code(run)
        self.assertEqual([(r["kind"], r["ref"]) for r in res["reasons"]], [("infra", "kos:docker")])
        self.assertIsNone(res["state"]["last_evaluated_sha"])

    def test_a_green_run_without_the_module_less_results_pull_asked_for_is_an_outage(self):
        """E05's rule for module-less red: a check that never ran is not a check that passed."""
        res = self.code(dict(green_run(), module_less=[module_less(2, "T38")]), module_less_mfs=(2, 3))
        self.assertEqual([(r["kind"], r["ref"]) for r in res["reasons"]], [("infra", "kos:module_less_incomplete")])
        self.assertIsNone(res["state"]["last_evaluated_sha"])
        red = dict(green_run(), tests=[dict(green_run()["tests"][0], ok=False)], green=False)
        res = self.code(red, module_less_mfs=(2, 3))  # a red run skips it on purpose: the push is rejected anyway
        self.assertEqual([r["kind"] for r in res["reasons"]], ["test_failed"])

    def test_a_vector_group_the_seed_lacks_warns_on_a_code_push_and_never_counts_against_the_founder(self):
        """The group's vectors are the seed's to bring (`29a`, `29d`), never the Founder's: the push is judged on
        what exists and the operator is told; the exit waits for the group (`KindsAndExit`)."""
        res = self.code(dict(green_run(), vector_groups_missing=["secrets"]), module_less_mfs=())
        self.assertEqual(res["verdict"], "accepted")
        self.assertEqual(res["warnings"], ["vector_group_missing:secrets"])
        self.assertEqual(res["state"]["reject_streaks"], {})


class StateRules(unittest.TestCase):
    def test_rollover_zeroes_only_the_month_and_records_it(self):  # S01 S02
        s = state0(month="2026-10", month_spend_usd_micros=5, stage_spend_usd_micros=7)
        new = st.rollover(s, "2026-11")
        self.assertEqual((new["month"], new["month_spend_usd_micros"], new["stage_spend_usd_micros"]),
                         ("2026-11", 0, 7))

    def test_negative_spend_and_malformed_shape_are_refused(self):  # S03 S04 S05 S07 S08
        for bad in (state0(stage_spend_usd_micros=-1), state0(month_spend_usd_micros=-1),
                    dict(state0(), extra=1), {k: v for k, v in state0().items() if k != "runs"},
                    state0(last_accepted_sha="xyz"), state0(frozen_specs={"spec/asama-0": "short"}),
                    state0(frozen_specs=[])):
            with self.assertRaises(ConfigError, msg=str(bad)[:80]):
                st.validate(bad)

    def test_remaining_budget_is_the_smaller_of_month_and_stage(self):  # L01 L02 L03 L05
        policy = Policy(300_000_000, 30_000_000, 2, 3, frozenset({"MIT"}), {})
        for month, stage, left in ((0, 0, 30_000_000), (299_500_000, 0, 500_000), (0, 29_000_000, 1_000_000),
                                   (300_000_000, 0, 0), (0, 30_000_000, 0)):
            prev = state0(month_spend_usd_micros=month, stage_spend_usd_micros=stage)
            self.assertEqual(cli.remaining_budget(policy, prev), left, (month, stage))


class SmallGates(unittest.TestCase):
    def test_classify_edges(self):  # C01 C04
        self.assertEqual(classify(["seedling/readme.md"]), ("code", []))
        self.assertEqual(classify(["spec/asama-12/a.md"]), ("spec", []))

    def test_is_green_needs_every_part(self):  # L22 L23 L24
        ok, bad = [{"ok": True}], [{"ok": False}]
        lic = [{"allowed": True}]
        self.assertTrue(cli.is_green(ok, ok, ok, lic))
        self.assertFalse(cli.is_green(bad, ok, ok, lic))
        self.assertFalse(cli.is_green(ok, bad, ok, lic))
        self.assertFalse(cli.is_green(ok, ok, bad, lic))

    def test_a_container_that_the_host_killed_once_is_asked_again_before_the_judge_is_blamed(self):
        """Under load a vector container was killed and two vectors were recorded as the Founder's failure."""
        from snowball_bootstrap.vectors import run_vectors
        vectors = Path(test_state.__file__).resolve().parents[1] / "vectors"

        class KilledOnce(FakeRunner):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.asked = set()

            def run(self, cmd, **kw):
                key = (cmd, kw.get("stdin"))
                if key not in self.asked:
                    self.asked.add(key)
                    return RunResult(-9, b"", b"killed by the host", 1, timed_out=True)
                return super().run(cmd, **kw)

        results = run_vectors(KilledOnce(vectors), vectors, STATS, table=EVERY_GROUP)
        self.assertTrue(results)
        self.assertEqual([r["id"] for r in results if not r["ok"]], [])

        class AlwaysKilled(FakeRunner):
            def run(self, cmd, **kw):
                return RunResult(-9, b"", b"out of memory", 1, timed_out=True)

        failed = [r for r in run_vectors(AlwaysKilled(vectors), vectors, STATS, table=EVERY_GROUP) if not r["ok"]]
        self.assertTrue(failed)
        self.assertIn("no answer: exit -9, timed out", failed[0]["detail"])  # the reason is on the record

    def test_a_control_that_hangs_is_not_a_passed_control(self):  # K01
        class Hangs(FakeRunner):
            def run(self, cmd, **kw):
                return RunResult(-9, b"", b"", 1, timed_out=True)
        results = {c["id"]: c["ok"] for c in run_controls(Hangs(Path(".")))}
        self.assertEqual(results, {"exit_zero": False, "exit_one": False, "network_blocked": False,
                                   "source_read_only": False})

    def test_the_isolation_controls_probe_what_they_claim_to(self):  # K02 K03
        from snowball_bootstrap.controls import CONTROLS
        commands = {cid: cmd for cid, cmd, _ in CONTROLS}
        self.assertNotIn("127.0.0.1", commands["network_blocked"])
        self.assertNotIn("localhost", commands["network_blocked"])
        self.assertIn("/src/", commands["source_read_only"])

    def failed_vectors(self, tamper, done=STATS, timed_out=False):
        from snowball_bootstrap.vectors import run_vectors
        vectors = Path(test_state.__file__).resolve().parents[1] / "vectors"

        class Wrong(FakeRunner):
            def run(self, cmd, **kw):
                res = super().run(cmd, **kw)
                return RunResult(res.exit_code, tamper(cmd, res.stdout), res.stderr, 1, timed_out=timed_out)
        results = run_vectors(Wrong(vectors), vectors, done, table=EVERY_GROUP)
        self.assertTrue(results)
        return {r["id"] for r in results if not r["ok"]}

    def test_a_drill_judge_with_the_right_headline_and_wrong_verdicts_fails(self):  # V08
        def flip(cmd, out):
            if "harness.drill judge" not in cmd:
                return out
            doc = json.loads(out)
            doc["verdicts"] = {q: ("FAIL" if v == "PASS" else "PASS") for q, v in doc["verdicts"].items()}
            return (json.dumps(doc) + chr(10)).encode()
        failed = self.failed_vectors(flip, done=DRILL)
        self.assertTrue(failed and all(f.startswith("drill.") for f in failed))

    def test_the_output_of_a_command_that_timed_out_is_never_an_answer(self):  # V09b
        failed = self.failed_vectors(lambda cmd, out: out, timed_out=True)
        self.assertTrue(failed)
        from snowball_bootstrap.vectors import run_vectors
        vectors = Path(test_state.__file__).resolve().parents[1] / "vectors"

        class Slow(FakeRunner):
            def run(self, cmd, **kw):
                res = super().run(cmd, **kw)
                return RunResult(res.exit_code, res.stdout, res.stderr, 1, timed_out=True)
        self.assertEqual([r for r in run_vectors(Slow(vectors), vectors, STATS, table=EVERY_GROUP) if r["ok"]], [])

    def test_vector_checks_reject_wrong_answers(self):  # V01 V02 V04
        def wrong(cmd, out):
            if "ledger.chain hash" in cmd:
                return (json.dumps({"row_hash": "0" * 64}) + chr(10)).encode()
            if "stats cp_lower" in cmd:
                return (json.dumps({"lb": "0.123456"}) + chr(10)).encode()
            if "stats mcnemar" in cmd:
                return (json.dumps({"p": "0.123456"}) + chr(10)).encode()
            return out
        failed = self.failed_vectors(wrong)
        self.assertIn("chain.V1.hash", failed)
        self.assertTrue(any(f.startswith("cp_lower.") and not f.endswith("changed_input") for f in failed))
        self.assertTrue(any(f.startswith("mcnemar.") and not f.endswith("changed_input") for f in failed))

    def test_vector_checks_reject_an_implementation_that_ignores_its_input(self):  # V03 V05
        seen = {}

        def blind(cmd, out):
            argv = cmd.split()
            if "stats cp_lower" in cmd:
                key = ("cp", argv[5], argv[6])  # n and alpha, never x
            elif "stats mcnemar" in cmd:
                key = ("mc", argv[5])  # c, never b
            else:
                return out
            return seen.setdefault(key, out)
        failed = self.failed_vectors(blind)
        self.assertTrue(any(f.startswith("cp_lower.") and f.endswith("changed_input") for f in failed))
        self.assertTrue(any(f.startswith("mcnemar.") and f.endswith("changed_input") for f in failed))


class CommandWiring(unittest.TestCase):
    """cmd_decide, cmd_poll and cmd_fetch_state end to end (the existing tests call decide() and the helpers only)."""

    setUp = test_state.StateTest.setUp
    tearDown = test_state.StateTest.tearDown

    def policy_file(self, root):
        (root / "policy.json").write_text(json.dumps({"constitutional": {
            "monthly_cap_usd": 300, "stage_params": {"rival_min_attempts": 2, "repeat_reject_limit": 3},
            "stage_budgets": {"asama_0": {"rival_usd": 30}}, "license_allowlist": ["MIT"], "license_exceptions": {}}}))

    def decide_cmd(self, meta, run=None, rival=None, repro=None, jobs=()):
        root = self.root / "operator"
        root.mkdir(exist_ok=True)
        self.policy_file(root)
        pulled = self.root / "pulled"
        pulled.mkdir(exist_ok=True)
        (pulled / "meta.json").write_text(json.dumps(meta))
        argv = ["decide", "--root", str(root), "--pulled", str(pulled), "--out", str(self.root / "out")]
        for flag, doc, name in (("--run", run, "run.json"), ("--rival", rival, "rival.json"),
                                ("--repro", repro, "repro.json")):
            folder = self.root / flag[2:]
            folder.mkdir(exist_ok=True)
            if doc is not None:
                (folder / name).write_text(json.dumps(doc))
            argv += [flag, str(folder)]
        for job in jobs:
            argv += ["--job", job]
        self.assertEqual(cli.main(argv), 0)
        return json.loads((self.root / "out" / "result.json").read_text())

    def test_decide_command_hands_artifacts_jobs_and_policy_to_decide(self):  # L29 L30 L31
        defect = "refutation:" + reproducer_key(refuted("c")["attempts"][0]["reproducer"])  # named by its reproducer (E08)
        meta = meta_("code", state0(reject_streaks={defect: 1}))
        result = self.decide_cmd(meta, green_run(), refuted("c"), {"results": [{"attempt_index": 0, "reproduced": True}]},
                                 ["getir=success", "kos=success", "cagir=success", "yeniden=success"])
        self.assertEqual([r["kind"] for r in result["reasons"]], ["refutation_reproduced"])
        self.assertEqual(result["learning"]["not_learning"], [])  # limit 3, streak 2
        self.assertEqual(result["learning"]["repeated"], [defect])

    def test_decide_command_survives_the_artifact_of_a_failed_job_being_absent(self):  # L34
        result = self.decide_cmd(meta_("spec", state0()), None, None, None, ["cagir=failure"])
        self.assertIn(("infra", "cagir:failure"), [(r["kind"], r["ref"]) for r in result["reasons"]])
        self.assertEqual((result["verdict"], result["state"]["reject_streaks"]), ("rejected", {}))
        self.assertIsNone(result["state"]["last_evaluated_sha"])

    def previous_state_zip(self, state, created="2020-01-01T00:00:00Z"):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("result.json", json.dumps({"state": state}))
            zf.writestr("result.json.sigstore.json", "{}")
        _Api = test_state._Api
        _Api.artifacts = [{"id": 5, "name": "bootstrap-state", "expired": False, "workflow_run": {"head_branch": "main"}, "created_at": created}]
        self.original_download = ghapi.download_zip
        ghapi.download_zip = lambda repo, aid, token: buf.getvalue()
        self.addCleanup(setattr, ghapi, "download_zip", self.original_download)

    def fetch_ok(self):
        return cli.main(["fetch-state", "--root", str(self.root), "--out", str(self.root / "state"),
                         "--identity", "id", "--sigstore-python", "/bin/true"])

    @posix_only
    def test_fetch_state_validates_rolls_the_month_over_and_asks_for_a_refresh(self):  # L08 L09 L10
        outputs = self.root / "o.txt"
        os.environ["GITHUB_OUTPUT"] = str(outputs)
        self.previous_state_zip(state0(month="2000-01", month_spend_usd_micros=5, stage_spend_usd_micros=7))
        self.assertEqual(self.fetch_ok(), 0)
        got = json.loads((self.root / "state" / "state.json").read_text())
        self.assertEqual((got["month"], got["month_spend_usd_micros"], got["stage_spend_usd_micros"]),
                         (cli.month_now(), 0, 7))
        self.assertIn("reupload=true", outputs.read_text())
        self.previous_state_zip(state0(stage_spend_usd_micros=-1))
        self.assertEqual(self.fetch_ok(), 2)

    def test_poll_skips_a_head_that_was_already_judged_and_never_trusts_an_unreadable_state(self):  # L06 L07
        brain = self.root / "brain"
        head = test_flow.make_repo(brain, {"a.txt": "1\n"})
        (self.root / "bootstrap.json").write_text(json.dumps({
            "brain_repo": "owner/brain", "brain_branch": "main",
            "image": "docker.io/library/python:3.12-slim@sha256:" + "a" * 64,
            "rival": {"model": "claude-sonnet-5-5", "effort": "medium", "max_turns": 30, "per_run_cap_usd_micros": 1},
            "limits": {"test_timeout_s": 1, "reproducer_timeout_s": 1, "max_prompt_chars": 1, "max_tree_bytes": 1}}))
        outputs = self.root / "outputs.txt"
        os.environ["GITHUB_OUTPUT"] = str(outputs)

        def poll(state):
            outputs.write_text("")
            self.previous_state_zip(state)
            self.assertEqual(cli.main(["poll", "--root", str(self.root), "--out", str(self.root / "p"),
                                       "--remote", str(brain)]), 0)
            return dict(line.split("=", 1) for line in outputs.read_text().splitlines())

        self.assertEqual(poll({"last_accepted_sha": A, "last_evaluated_sha": head})["skip"], "true")
        self.assertEqual(poll({"last_accepted_sha": A, "last_evaluated_sha": None})["skip"], "false")
        self.assertEqual(poll({})["skip"], "false")


class PullGates(unittest.TestCase):
    setUp = test_flow.Flow.setUp
    tearDown = test_flow.Flow.tearDown
    pull = test_flow.Flow.pull
    finish = test_flow.Flow.finish
    rival_ok = test_flow.Flow.rival_ok

    def freeze(self):
        commit(self.brain, {"spec/asama-0/00-ozet.md": "# stage 0 v2\n"}, "spec")
        self.finish(self.pull(), rival=self.rival_ok(), jobs={"cagir": "success"})
        self.assertIn("spec/asama-0", self.state["frozen_specs"])

    def test_code_with_an_edited_frozen_spec_is_refused(self):  # L12
        self.freeze()
        self.state["frozen_specs"]["spec/asama-0"] = "0" * 64
        commit(self.brain, {"referee/a.py": "x = 1\n", "snowball-tests.json": test_flow.all_tests_manifest([1])}, "mf1")
        meta = self.pull()
        self.assertIn("spec_changed_after_freeze", meta["pre_reasons"])
        self.assertEqual((meta["run_tests"], meta["run_rival"]), (False, False))

    def test_a_manifest_that_leaves_a_finished_micro_feature_untested_is_refused_at_pull(self):  # L13
        self.freeze()
        commit(self.brain, {"referee/a.py": "x = 1\n", "snowball-tests.json": json.dumps(
            {"tests": [], "done_mf": [1], "lockfiles": []})}, "mf1 without its test")
        meta = self.pull()
        self.assertIn("zero_tests", meta["pre_reasons"])
        self.assertIn("missing_test:MF1:T13", meta["pre_reasons"])

    def test_exit_requests_are_checked_for_stage_hash_and_company(self):  # L14 L15 L16
        self.freeze()
        base = self.state["last_accepted_sha"]
        request = {"stage": 1, "sha": base, "spec_sha256": "0" * 64}
        commit(self.brain, {"exit-request.json": json.dumps(request)}, "bad exit")
        meta = self.pull()
        self.assertEqual(meta["kind"], "exit")
        self.assertIn("exit_request_wrong_stage", meta["pre_reasons"])
        self.assertIn("exit_request_spec_hash_mismatch", meta["pre_reasons"])
        commit(self.brain, {"referee/a.py": "x = 1\n"}, "company")
        self.assertIn("exit_request_not_alone", self.pull()["pre_reasons"])

    def test_the_founders_ledger_rides_along_with_any_push(self):
        """Ledger rows written in the same session never make a spec request mixed or an exit request
        accompanied; a push of ledger rows alone is a no-op, not a judgement."""
        commit(self.brain, {"spec/asama-0/00-ozet.md": "# stage 0 v2\n",
                            "founder-ledger.jsonl": '{"kind":"session"}\n'}, "spec and ledger")
        meta = self.pull()
        self.assertEqual((meta["kind"], meta["pre_reasons"]), ("spec", []))
        self.finish(meta, rival=self.rival_ok(), jobs={"cagir": "success"})
        self.assertIn("spec/asama-0", self.state["frozen_specs"])
        commit(self.brain, {"founder-ledger.jsonl": '{"kind":"session"}\n{"kind":"seed_issue"}\n'}, "ledger only")
        meta = self.pull()
        self.assertEqual((meta["kind"], meta["run_tests"], meta["run_rival"]), ("none", False, False))
        request = {"stage": 0, "sha": self.state["last_accepted_sha"], "spec_sha256": "0" * 64}
        commit(self.brain, {"exit-request.json": json.dumps(request),
                            "founder-ledger.jsonl": '{"kind":"session"}\n{"kind":"seed_issue"}\n{"kind":"exit"}\n'},
               "exit and ledger")
        meta = self.pull()
        self.assertEqual(meta["kind"], "exit")
        self.assertNotIn("exit_request_not_alone", meta["pre_reasons"])

    def test_an_oversized_tree_is_refused(self):  # L20
        path = self.referee / "bootstrap.json"
        doc = json.loads(path.read_text())
        doc["limits"]["max_tree_bytes"] = 1000
        path.write_text(json.dumps(doc))
        commit(self.brain, {"spec/asama-0/00-ozet.md": "# stage 0 v2\n"}, "spec")
        self.assertIn("tree_too_large", self.pull()["pre_reasons"])

    def test_a_head_with_an_unchanged_tree_is_not_polled_forever(self):
        sh(self.brain, "git", "commit", "-q", "--allow-empty", "-m", "empty")
        out = Path(self.tmp.name) / "gh_output"
        os.environ["GITHUB_OUTPUT"] = str(out)
        self.addCleanup(os.environ.pop, "GITHUB_OUTPUT", None)
        meta = self.pull()
        self.assertEqual(meta["kind"], "none")
        self.finish(meta, jobs={})
        out.write_text("")
        self.pull()
        self.assertIn("skip=true", out.read_text())

    def test_an_unreachable_base_is_a_typed_rejection_not_a_noop(self):  # L21
        self.state["last_accepted_sha"] = "9" * 40
        commit(self.brain, {"spec/asama-0/00-ozet.md": "# stage 0 v2\n"}, "spec")
        meta = self.pull()
        self.assertEqual(meta["kind"], "rejected")
        self.assertIn("base_unreachable", meta["pre_reasons"])

    def stage_pulled(self, meta, files=("referee/a.py",)):
        vectors = Path(test_state.__file__).resolve().parents[1] / "vectors"
        if not (self.referee / "vectors").exists():
            import shutil
            shutil.copytree(vectors, self.referee / "vectors")
        src = Path(self.tmp.name) / "tree"
        for rel in files:
            (src / rel).parent.mkdir(parents=True, exist_ok=True)
            (src / rel).write_text("x = 1" + chr(10))
        pulled = Path(self.tmp.name) / "pulled_x"
        pulled.mkdir(exist_ok=True)
        cli.pack_dir(src, pulled / "brain.tar")
        (pulled / "meta.json").write_text(json.dumps(meta))
        return pulled, vectors

    def test_run_tests_does_not_run_the_founders_tests_on_a_runner_whose_controls_failed(self):  # L33
        manifest = {"tests": [{"id": "T13", "cmd": "python -m unittest t13", "stage": 0}], "done_mf": [1],
                    "lockfiles": []}
        pulled, vectors = self.stage_pulled({"manifest": manifest})
        deps = Path(self.tmp.name) / "deps"
        deps.mkdir()
        calls = []

        class AlwaysGreen(FakeRunner):
            def run(self, cmd, **kw):
                calls.append(cmd)
                return RunResult(0, b"", b"", 1)
        real = cli._runner
        cli._runner = lambda *a, **k: AlwaysGreen(vectors)
        self.addCleanup(setattr, cli, "_runner", real)
        rc = cli.main(["run-tests", "--root", str(self.referee), "--pulled", str(pulled), "--deps", str(deps),
                       "--work", str(Path(self.tmp.name) / "work"), "--out", str(Path(self.tmp.name) / "run")])
        self.assertEqual(rc, 0)
        run = json.loads((Path(self.tmp.name) / "run" / "run.json").read_text())
        self.assertEqual((run["tests"], run["vectors"], run["green"]), ([], [], False))
        self.assertNotIn("python -m unittest t13", calls)

    def run_tests_with(self, meta, lazy=False, docker_fails=False):
        """run-tests with containers that run the Founder's T13 for real enough: it imports its module, so it is
        green with `referee/ledger/chain.py` in the mounted tree and red without (``lazy``: green either way)."""
        files = ("referee/ledger/chain.py", "referee/ledger/__init__.py", "referee/other.py")
        pulled, vectors = self.stage_pulled(meta, files=files)
        deps = Path(self.tmp.name) / "deps"
        deps.mkdir(exist_ok=True)
        trees = []

        class TreeRunner(FakeRunner):
            def run(self, cmd, **kw):
                if cmd != "python -m unittest t13":
                    return super().run(cmd, **kw)
                if docker_fails and self.src != trees[0]:
                    return RunResult(125, b"", b"docker: Error response from daemon", 1)
                imports = (self.src / "referee" / "ledger" / "chain.py").exists()
                return RunResult(0 if imports or lazy else 1, b"", b"", 1)

        def make(boot, src, *a, **k):
            trees.append(Path(src))
            runner = TreeRunner(vectors)
            runner.src = Path(src)
            return runner
        real = cli._runner
        cli._runner = make
        self.addCleanup(setattr, cli, "_runner", real)
        out = Path(self.tmp.name) / f"run{len(trees)}{lazy}{docker_fails}"
        rc = cli.main(["run-tests", "--root", str(self.referee), "--pulled", str(pulled), "--deps", str(deps),
                       "--work", str(Path(self.tmp.name) / f"work{lazy}{docker_fails}"), "--out", str(out)])
        self.assertEqual(rc, 0)
        return json.loads((out / "run.json").read_text()), trees

    def test_run_tests_runs_a_finished_micro_features_tests_again_without_its_module(self):  # `asama-0/14`
        manifest = {"tests": [{"id": "T13", "cmd": "python -m unittest t13", "stage": 0}], "done_mf": [1],
                    "lockfiles": []}
        run, trees = self.run_tests_with({"manifest": manifest, "module_less": [1]})
        self.assertEqual([(m["mf"], m["test_id"], m["module"], m["module_present"], m["stayed_green"])
                          for m in run["module_less"]], [(1, "T13", "referee/ledger/chain.py", True, False)])
        self.assertEqual((run["green"], run["vector_groups_missing"]), (True, []))
        self.assertEqual(len(trees), 2)  # the pushed tree, then MF1's own module-less copy
        self.assertTrue((trees[0] / "referee" / "ledger" / "chain.py").exists())
        self.assertFalse((trees[1] / "referee" / "ledger" / "chain.py").exists())
        self.assertTrue((trees[1] / "referee" / "other.py").exists())  # only the module is gone
        result = run_decide(meta_("code", state0(), module_less=[1]), run, not_refuted(), [], CODE_JOBS)
        self.assertEqual(result["verdict"], "accepted", result["reasons"])

        lazy, _ = self.run_tests_with({"manifest": manifest, "module_less": [1]}, lazy=True)
        self.assertEqual(([m["stayed_green"] for m in lazy["module_less"]], lazy["green"]), ([True], False))
        result = run_decide(meta_("code", state0(), module_less=[1]), lazy, None, [], CODE_JOBS)
        self.assertEqual([(r["kind"], r["ref"]) for r in result["reasons"]], [("module_less_green", "MF1")])

        faulted, _ = self.run_tests_with({"manifest": manifest, "module_less": [1]}, docker_fails=True)
        self.assertEqual(([m["runner_fault"] for m in faulted["module_less"]], faulted["green"]), ([True], False))

        nothing_new, trees = self.run_tests_with({"manifest": manifest, "module_less": []})
        self.assertEqual((nothing_new["module_less"], len(trees)), ([], 1))

    def test_run_tests_names_the_vector_groups_the_seed_still_lacks(self):  # `29d`
        manifest = {"tests": [{"id": "T13", "cmd": "python -m unittest t13", "stage": 0},
                              {"id": "T38", "cmd": "python -m unittest t38", "stage": 0}], "done_mf": [1, 2],
                    "lockfiles": []}
        run, _ = self.run_tests_with({"manifest": manifest, "module_less": []})
        self.assertEqual(run["vector_groups_missing"], ["secrets"])
        self.assertEqual({v["id"].split(".")[0] for v in run["vectors"]}, {"chain"})

    def test_reproducers_run_with_the_reproducer_timeout(self):  # L32
        pulled, vectors = self.stage_pulled({"manifest": None})
        rival_dir = Path(self.tmp.name) / "rivaldir"
        rival_dir.mkdir()
        (rival_dir / "rival.json").write_text(json.dumps({"attempts": []}))
        deps = Path(self.tmp.name) / "deps"
        deps.mkdir()
        seen = {}
        real_runner, real_repro = cli._runner, cli.run_reproducers
        cli._runner = lambda *a, **k: FakeRunner(vectors)
        cli.run_reproducers = lambda runner, attempts, timeout_s, **kw: seen.setdefault("timeout", timeout_s) and []
        self.addCleanup(setattr, cli, "_runner", real_runner)
        self.addCleanup(setattr, cli, "run_reproducers", real_repro)
        rc = cli.main(["reproduce", "--root", str(self.referee), "--pulled", str(pulled), "--deps", str(deps),
                       "--rival", str(rival_dir), "--work", str(Path(self.tmp.name) / "work"),
                       "--out", str(Path(self.tmp.name) / "repro")])
        self.assertEqual((rc, seen["timeout"]), (0, 120))  # bootstrap.json: reproducer_timeout_s 120, test_timeout_s 600

    def test_rival_command_reports_reproducers_and_is_limited_by_the_remaining_budget(self):  # L25 L28
        seats = self.referee / "seats"
        seats.mkdir()
        source = Path(test_flow.__file__).resolve().parents[3] / "spec" / "tohum" / cli.SEATS_FILE
        (seats / cli.SEATS_FILE).write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
        self.state["stage_spend_usd_micros"] = 29_500_000  # 0.5 USD left of the 30 USD stage budget
        commit(self.brain, {"spec/asama-0/00-ozet.md": "# stage 0, revised\n"}, "spec")
        self.pull()
        pulled = Path(self.tmp.name) / f"pulled{self.n}"
        bin_dir = Path(self.tmp.name) / "bin"
        bin_dir.mkdir()
        claude = install_fake_claude(bin_dir)
        gh_output = Path(self.tmp.name) / "gh_output"
        os.environ["GITHUB_OUTPUT"] = str(gh_output)
        self.addCleanup(os.environ.pop, "GITHUB_OUTPUT", None)
        attempt = {"claim": "c", "evidence_refs": [{"path": "spec/asama-0/00-ozet.md", "line_start": 1, "line_end": 1}],
                   "reproducer": {"cmd": "python -m x", "expect_exit": 1}}
        (bin_dir / "scenario.json").write_text(json.dumps({"calls": [submit("refuted", [attempt])],
                                                           "result": ok_result()}))
        rc = cli.main(["rival", "--root", str(self.referee), "--pulled", str(pulled), "--work",
                       str(Path(self.tmp.name) / "work"), "--out", str(Path(self.tmp.name) / "rival"),
                       "--claude", str(claude)])
        self.assertEqual(rc, 0)
        self.assertIn("has_repro=true", gh_output.read_text())
        argv = json.loads((bin_dir / "seen.json").read_text())["argv"]
        self.assertEqual(argv[argv.index("--max-budget-usd") + 1], "0.500000")


if __name__ == "__main__":
    unittest.main()
