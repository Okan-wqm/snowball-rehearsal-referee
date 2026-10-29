"""Batch 2 of the gap register (`docs/eksik-kaydi.md`, E06-E13, E20, E27, E33): the rival, its reproducers and
what the referee remembers of them. Each class names the register item it closes."""

import contextlib
import datetime
import hashlib
import http.server
import io
import json
import os
import re
import tarfile
import tempfile
import threading
import time
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from snowball_bootstrap import canon, cli, ghapi, reproduce, rival, state as st
from snowball_bootstrap.config import ConfigError, RivalConfig, Summary
from snowball_bootstrap.container import RunResult
from snowball_bootstrap.decide import decide

import test_flow
from helpers import (EVERY_GROUP, PINNED_CLI, STATS, FakeRunner, commit, good_init, install_fake_claude, ok_result,
                     posix_only, submit)

A, B, C = "a" * 40, "b" * 40, "c" * 40
NOW = "2026-10-29T12:00:00Z"
CFG = RivalConfig(model="claude-sonnet-5-5", effort="medium", max_turns=5, per_run_cap_usd_micros=5_000_000)
CODE_JOBS = {"getir": "success", "kos": "success", "cagir": "success", "yeniden": "success"}
REFS = [{"path": "referee/a.py", "line_start": 1, "line_end": 1}]
REP = {"cmd": "python -m referee.ledger.chain verify /vec/chain.jsonl", "expect_exit": None,
       "expect_stdout_contains": '"valid": true', "expect_stderr_contains": None}
WORKFLOW = (Path(__file__).resolve().parents[1] / "workflow" / "bootstrap.yml").read_text(encoding="utf-8")


def state2(**kw):
    s = {"schema": "snowball-bootstrap-state/2", "origin": "artifact", "last_accepted_sha": A,
         "last_evaluated_sha": None, "frozen_specs": {}, "rival_artifacts": [], "month": "2026-10",
         "month_spend_usd_micros": 1000, "stage_spend_usd_micros": 2000, "runs": 4, "reject_streaks": {},
         "repeat_events": 0, "outage_sha": None, "outage_count": 0, "outage_since": None, "outage_stop": None,
         "rival_side_streak": 0, "open_refutations": [], "open_claims": [], "pending_rival": None}
    s.update(kw)
    return s


def meta2(kind, state, **kw):
    m = {"head": B, "base": A, "kind": kind, "state": state, "changed": [], "pre_reasons": [], "evaluate": True,
         "run_tests": kind in ("code", "exit"), "run_rival": kind in ("spec", "code"), "manifest": None,
         "exit_request": None, "referee_tree_sha256": None, "spec_dir_hashes": {}, "state_repro": [],
         "reuse_rival": False, "waived": []}
    m.update(kw)
    return m


def green():
    return {"controls": [{"id": "exit_one", "ok": True}], "tests": [{"id": "T13", "cmd_sha256": "c", "ok": True,
                                                                      "output_tail": ""}],
            "vectors": [], "licenses": [], "green": True}


def key_of(rep):
    """The reproducer's signature, written out here so that a change of the formula is noticed (E08)."""
    doc = {k: rep.get(k) for k in ("cmd", "expect_exit", "expect_stdout_contains", "expect_stderr_contains")}
    return hashlib.sha256(canon.canonical(doc)).hexdigest()[:16]


def attempt(claim, rep=REP, **kw):
    a = {"claim": claim, "evidence_refs": list(REFS), "refs_valid": True}
    if rep is not None:
        a["reproducer"] = dict(rep)
    a.update(kw)
    return a


def refuted_by(*attempts, cost=7):
    return {"verdict": "refuted", "attempts": list(attempts), "reasons": [], "cost_usd_micros": cost,
            "reproducer_count": sum(1 for a in attempts if "reproducer" in a)}


def not_refuted(cost=7):
    return {"verdict": "not_refuted", "attempts": [], "reasons": [], "cost_usd_micros": cost, "reproducer_count": 0}


def unresolved(*reasons, cost=0):
    return {"verdict": "unresolved", "attempts": [], "reasons": list(reasons), "cost_usd_micros": cost,
            "reproducer_count": 0}


def ran(i, reproduced, rep=REP, tautological=None, **kw):
    r = {"attempt_index": i, "key": key_of(rep), "reproduced": reproduced, "shown": reproduced or bool(tautological),
         "tautological": tautological, "runner_fault": False, "exit": 1, "timed_out": False,
         "stdout_tail": "out", "stderr_tail": "err"}
    r.update(kw)
    return r


def state_ran(key, source, reproduced, **kw):
    r = {"key": key, "source": source, "reproduced": reproduced, "shown": reproduced, "tautological": None,
         "runner_fault": False, "exit": 1, "timed_out": False, "stdout_tail": "o", "stderr_tail": "e"}
    r.update(kw)
    return r


def refutation_entry(rep=REP, claim="the chain accepts a broken row", head=C):
    return {"key": key_of(rep), "claim": claim, "evidence_refs": list(REFS), "reproducer": dict(rep),
            "first_head": head, "last_head": head}


def claim_entry(claim="cp_lower is the Wilson bound", rep=REP, rewritten=False):
    return {"id": hashlib.sha256(claim.encode()).hexdigest()[:12], "claim": claim, "evidence_refs": list(REFS),
            "reproducer": None if rep is None else dict(rep), "observed": None, "first_head": C,
            "rewritten": rewritten}


def run_decide(meta, run=None, rival_doc=None, repro=None, jobs=None, state_repro=None, limit=3, min_attempts=2,
               now=NOW):
    return decide(meta, run, rival_doc, repro, jobs or {}, min_attempts, limit, state_repro=state_repro, now=now)


class Returns(FakeRunner):
    """A runner that answers every command the same way."""

    def __init__(self, code=0, out=b"", err=b"", timed_out=False):
        super().__init__(Path("."))
        self.result = RunResult(code, out, err, 1, timed_out=timed_out)

    def run(self, cmd, **kw):
        self.calls.append((cmd, kw.get("cwd", ".")))
        return self.result


# ---------------------------------------------------------------- E06 reproducer contract


class E06ReproducerContract(unittest.TestCase):
    def test_the_protocol_and_the_tool_state_the_contract(self):
        text = rival.PROTOCOL
        for phrase in ("because of the defect", "if the code were correct", "2>&1", "substring",
                       "expect_stderr_contains", "At most 5", "empty tree"):
            self.assertIn(phrase, text)
        tool = next(t for t in rival.TOOLS if t["name"] == "submit_verdict")
        rep = tool["input_schema"]["properties"]["attempts"]["items"]["properties"]["reproducer"]
        self.assertEqual(set(rep["properties"]),
                         {"cmd", "expect_exit", "expect_stdout_contains", "expect_stderr_contains"})
        self.assertEqual(rep["properties"]["expect_stderr_contains"]["maxLength"], rival.MAX_EXPECT_CHARS)
        self.assertIn("because of the defect", tool["description"] + rep["description"])

    def test_a_stderr_expectation_is_accepted_and_kept(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "referee").mkdir()
            (Path(tmp) / "referee" / "a.py").write_text("x = 1\n")
            box = rival.ToolBox(Path(tmp))
            got = rival.validate_verdict({"verdict": "refuted", "attempts": [
                {"claim": "c", "evidence_refs": REFS, "reproducer": {"cmd": "python -m x", "expect_stderr_contains":
                                                                      "ValueError: boom"}}]}, box)
            self.assertEqual(got["attempts"][0]["reproducer"]["expect_stderr_contains"], "ValueError: boom")
            with self.assertRaises(ValueError):
                rival.validate_verdict({"verdict": "refuted", "attempts": [
                    {"claim": "c", "evidence_refs": REFS, "reproducer": {"cmd": "x", "expect_stderr_contains": ""}}]},
                    box)

    def test_a_traceback_only_on_stderr_is_reproduced_and_both_tails_are_kept(self):
        """The second rehearsal: a real defect, its traceback thrown away with 2>/dev/null and never matched."""
        head = Returns(1, b"partial out", b"Traceback (most recent call last):\n  ...\nValueError: boom\n")
        control = Returns(1, b"", b"/tmp/venv/bin/python: No module named x\n")
        rep = {"cmd": "python -m x", "expect_stderr_contains": "ValueError: boom"}
        res = reproduce.run_reproducers(head, [attempt("c", rep)], 5, control=control)[0]
        self.assertTrue(res["reproduced"], res)
        self.assertEqual(res["stdout_tail"], "partial out")
        self.assertTrue(res["stderr_tail"].endswith("ValueError: boom\n"))
        self.assertEqual(len(res["stderr_sha256"]), 64)

    def test_the_tails_are_bounded_and_never_carry_a_secret(self):
        token = "gh" + "p_" + "A" * 36
        head = Returns(1, b"x" * 5000 + b"\nwrong hash\n", b"leak " + token.encode() + b"\n")
        res = reproduce.run_reproducers(head, [attempt("c", {"cmd": "x", "expect_stdout_contains": "wrong hash"})], 5,
                                        control=Returns(0))[0]
        self.assertTrue(res["reproduced"])
        self.assertLessEqual(len(res["stdout_tail"]), reproduce.TAIL_CHARS)
        self.assertTrue(res["stdout_tail"].endswith("wrong hash\n"))
        self.assertNotIn(token, json.dumps(res))

    def test_a_run_that_timed_out_never_reproduces(self):
        """R3: a timed-out run whose stdout matched used to count."""
        for rep in ({"cmd": "x", "expect_stdout_contains": "wrong"}, {"cmd": "x", "expect_stderr_contains": "wrong"},
                    {"cmd": "x", "expect_exit": 124}):
            head = Returns(124, b"wrong", b"wrong", timed_out=True)
            res = reproduce.run_reproducers(head, [attempt("c", rep)], 5, control=Returns(0))[0]
            self.assertEqual((res["reproduced"], res["timed_out"]), (False, True), rep)


# ---------------------------------------------------------------- E09 tautology


class E09Tautology(unittest.TestCase):
    def test_an_observable_that_shows_on_an_empty_tree_does_not_count(self):
        """R3: {"cmd": "true", "expect_exit": 0} was a reproduced refutation."""
        res = reproduce.run_reproducers(Returns(0), [attempt("c", {"cmd": "true", "expect_exit": 0})], 5,
                                        control=Returns(0))[0]
        self.assertEqual((res["shown"], res["tautological"], res["reproduced"]), (True, True, False))
        exit_only = reproduce.run_reproducers(Returns(1, b"", b"AssertionError"), [attempt("c", {"cmd": "python -m t",
                                                                                                 "expect_exit": 1})],
                                              5, control=Returns(1, b"", b"No module named t"))[0]
        self.assertEqual((exit_only["tautological"], exit_only["reproduced"]), (True, False))  # exit 1 says nothing
        real = reproduce.run_reproducers(Returns(1, b"", b"AssertionError: prev_hash ignored"),
                                         [attempt("c", {"cmd": "python -m t", "expect_exit": 1,
                                                        "expect_stderr_contains": "prev_hash ignored"})], 5,
                                         control=Returns(1, b"", b"No module named t"))[0]
        self.assertEqual((real["tautological"], real["reproduced"]), (False, True))

    def test_a_docker_failure_in_the_control_run_is_a_runner_fault(self):
        res = reproduce.run_reproducers(Returns(1, b"wrong"), [attempt("c", {"cmd": "x", "expect_stdout_contains":
                                                                             "wrong"})], 5, control=Returns(125))[0]
        self.assertEqual((res["reproduced"], res["runner_fault"]), (False, True))

    def test_decide_never_counts_a_tautological_reproducer(self):
        res = run_decide(meta2("code", state2()), green(), refuted_by(attempt("c")),
                         [ran(0, False, tautological=True)], CODE_JOBS)
        self.assertEqual((res["verdict"], res["reasons"]), ("accepted", []))
        self.assertEqual(res["state"]["open_refutations"], [])

    def test_the_control_tree_is_empty_and_installs_no_lock_files(self):
        flow = test_flow.Flow("test_full_stage0_path")
        flow.setUp()
        self.addCleanup(flow.tearDown)
        base = Path(flow.tmp.name)
        src = base / "tree"
        (src / "referee").mkdir(parents=True)
        (src / "referee" / "a.py").write_text("x = 1\n")
        pulled = base / "pulled_x"
        pulled.mkdir()
        cli.pack_dir(src, pulled / "brain.tar")
        (pulled / "meta.json").write_text(json.dumps(meta2("code", state2(), manifest={"lockfiles": ["req.lock"]})))
        (base / "rv").mkdir()
        (base / "rv" / "rival.json").write_text(json.dumps(refuted_by(attempt("c", {"cmd": "true", "expect_exit": 0}))))
        (base / "deps").mkdir()
        made = []

        def runner(boot, tree, deps, vectors, locks):
            made.append((Path(tree), list(locks)))
            return Returns(0)
        with mock.patch.object(cli, "_runner", runner):
            rc = cli.main(["reproduce", "--root", str(flow.referee), "--pulled", str(pulled), "--deps", str(base / "deps"),
                           "--rival", str(base / "rv"), "--work", str(base / "work"), "--out", str(base / "repro")])
        self.assertEqual(rc, 0)
        doc = json.loads((base / "repro" / "repro.json").read_text())
        self.assertEqual((doc["results"][0]["tautological"], doc["results"][0]["reproduced"]), (True, False))
        trees = {str(tree): locks for tree, locks in made}
        self.assertEqual(len(trees), 2, made)
        control = [tree for tree, locks in made if locks == []]
        self.assertTrue(control and not any(control[0].iterdir()), made)  # an empty tree, no lock file to install
        if os.name != "nt":  # the container runs as 65534 and copies /src: a 0700 directory would fail every control
            self.assertEqual(control[0].stat().st_mode & 0o777, 0o755)
        self.assertIn(["req.lock"], [locks for _t, locks in made])


# ---------------------------------------------------------------- E10 the Founder's ledger


class E10LedgerHidden(unittest.TestCase):
    def test_the_tools_cannot_read_list_or_search_the_ledger(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "sub").mkdir()
            for rel in ("founder-ledger.jsonl", "sub/founder-ledger.jsonl"):
                (root / rel).write_text('{"note": "PLAN-FOR-THE-RIVAL"}\n')
            (root / "a.py").write_text("x = 1\n")
            box = rival.ToolBox(root)
            for rel in ("founder-ledger.jsonl", "sub/founder-ledger.jsonl"):
                with self.assertRaises(ValueError, msg=rel):
                    box.read_file(rel)
                self.assertIsNone(box.line_count(rel))
            self.assertEqual(box.glob("**/*"), "a.py")
            self.assertEqual(box.grep("PLAN-FOR"), "(no matches)")
            self.assertEqual(box.grep("PLAN-FOR", "sub"), "(no matches)")

    def test_the_request_and_the_diff_leave_the_ledger_out(self):
        flow = test_flow.Flow("test_full_stage0_path")
        flow.setUp()
        self.addCleanup(flow.tearDown)
        seats = flow.referee / "seats"
        seats.mkdir()
        source = Path(test_flow.__file__).resolve().parents[3] / "spec" / "tohum" / cli.SEATS_FILE
        (seats / cli.SEATS_FILE).write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
        commit(flow.brain, {"referee/a.py": "x = 1\n", "founder-ledger.jsonl": '{"plan": "PLAN-FOR-THE-RIVAL"}\n'},
               "code and ledger")
        meta = flow.pull()
        pulled = Path(flow.tmp.name) / f"pulled{flow.n}"
        diff = (pulled / "diff.patch").read_text(encoding="utf-8")
        self.assertIn("referee/a.py", diff)
        self.assertNotIn("PLAN-FOR-THE-RIVAL", diff)
        self.assertNotIn("founder-ledger", diff)
        bin_dir = Path(flow.tmp.name) / "bin"
        bin_dir.mkdir()
        claude = install_fake_claude(bin_dir)
        (bin_dir / "scenario.json").write_text(json.dumps({"calls": [submit()], "result": ok_result()}))
        with mock.patch.dict(os.environ, {"GITHUB_OUTPUT": str(Path(flow.tmp.name) / "gh")}), \
                contextlib.redirect_stdout(io.StringIO()):
            rc = cli.main(["rival", "--root", str(flow.referee), "--pulled", str(pulled), "--work",
                           str(Path(flow.tmp.name) / "work_r"), "--out", str(Path(flow.tmp.name) / "rival"),
                           "--claude", str(claude)])
        self.assertEqual(rc, 0)
        stdin = json.loads((bin_dir / "seen.json").read_text())["stdin"]
        self.assertIn("referee/a.py", stdin)
        self.assertNotIn("founder-ledger", stdin)
        self.assertNotIn("PLAN-FOR-THE-RIVAL", stdin)
        self.assertIn("founder-ledger.jsonl", meta["changed"])  # classification still sees every change


class E153ReportsHidden(unittest.TestCase):
    """The Founder's root reports/ are not the rival's to see (`asama-0/03`): the rival judges the work, not
    the Founder's account of it. Found in the pilot's first cycle, where the rival read them."""

    def test_the_tools_cannot_read_list_or_search_root_reports_but_see_a_nested_reports_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "reports").mkdir()
            (root / "reports" / "seed-001.json").write_text('{"note": "REPORT-FOR-THE-RIVAL"}\n')
            (root / "referee" / "reports").mkdir(parents=True)
            (root / "referee" / "reports" / "fmt.py").write_text("NESTED = 1\n")
            box = rival.ToolBox(root)
            with self.assertRaises(ValueError):
                box.read_file("reports/seed-001.json")
            self.assertIsNone(box.line_count("reports/seed-001.json"))
            self.assertEqual(box.grep("REPORT-FOR"), "(no matches)")
            self.assertEqual(box.glob("**/*.json"), "(no matches)")
            self.assertIn("NESTED = 1", box.read_file("referee/reports/fmt.py"))  # only the root one is hidden
        self.assertTrue(rival.hidden("reports/a.json"))
        self.assertFalse(rival.hidden("referee/reports/a.py"))

    def test_the_request_and_the_diff_leave_root_reports_out(self):
        flow = test_flow.Flow("test_full_stage0_path")
        flow.setUp()
        self.addCleanup(flow.tearDown)
        seats = flow.referee / "seats"
        seats.mkdir()
        source = Path(test_flow.__file__).resolve().parents[3] / "spec" / "tohum" / cli.SEATS_FILE
        (seats / cli.SEATS_FILE).write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
        commit(flow.brain, {"referee/a.py": "x = 1\n", "reports/r1.json": '{"note": "REPORT-FOR-THE-RIVAL"}\n'},
               "code and a report")
        meta = flow.pull()
        pulled = Path(flow.tmp.name) / f"pulled{flow.n}"
        diff = (pulled / "diff.patch").read_text(encoding="utf-8")
        self.assertIn("referee/a.py", diff)
        self.assertNotIn("REPORT-FOR-THE-RIVAL", diff)
        bin_dir = Path(flow.tmp.name) / "bin"
        bin_dir.mkdir()
        claude = install_fake_claude(bin_dir)
        (bin_dir / "scenario.json").write_text(json.dumps({"calls": [submit()], "result": ok_result()}))
        with mock.patch.dict(os.environ, {"GITHUB_OUTPUT": str(Path(flow.tmp.name) / "gh")}), \
                contextlib.redirect_stdout(io.StringIO()):
            rc = cli.main(["rival", "--root", str(flow.referee), "--pulled", str(pulled), "--work",
                           str(Path(flow.tmp.name) / "work_r"), "--out", str(Path(flow.tmp.name) / "rival"),
                           "--claude", str(claude)])
        self.assertEqual(rc, 0)
        stdin = json.loads((bin_dir / "seen.json").read_text())["stdin"]
        self.assertIn("referee/a.py", stdin)
        self.assertNotIn("reports/r1.json", stdin)
        self.assertNotIn("REPORT-FOR-THE-RIVAL", stdin)
        self.assertIn("reports/r1.json", meta["changed"])


# ---------------------------------------------------------------- E11 what counts against the Founder


class E11LearningSplit(unittest.TestCase):
    STREAKS = {"test_failed:T13": 2}

    def test_the_rivals_own_failures_leave_the_founders_streaks_as_they_were(self):
        for reason in ("model_mismatch", "malformed_verdict:x", "no_verdict:end_turn", "no_verdict_after:x",
                       "secret_in_verdict:aws_access_key", "refusal", "budget", "request_rejected:http_400", None):
            st_ = state2(reject_streaks=dict(self.STREAKS), repeat_events=1)
            rival_doc = unresolved(reason) if reason else None
            res = run_decide(meta2("code", st_), green(), rival_doc, [], dict(CODE_JOBS, yeniden="skipped"))
            self.assertEqual(res["verdict"], "rejected", reason)
            self.assertEqual(res["state"]["last_evaluated_sha"], B, reason)  # evaluated, not an outage
            self.assertEqual((res["state"]["reject_streaks"], res["state"]["repeat_events"]), (self.STREAKS, 1), reason)

    def test_budget_and_a_pull_error_leave_the_streaks_as_they_were_too(self):
        for pre in ("budget", "pull_error"):
            res = run_decide(meta2("spec", state2(reject_streaks=dict(self.STREAKS)), pre_reasons=[pre],
                                   run_rival=False))
            self.assertEqual(res["state"]["reject_streaks"], self.STREAKS, pre)

    def test_what_the_founder_can_fix_still_counts(self):
        for reason in ("prompt_too_large", "max_turns"):
            st_ = state2()
            for n in range(3):
                res = run_decide(meta2("code", st_, head=f"{n + 1:040d}"), green(), unresolved(reason), [],
                                 dict(CODE_JOBS, yeniden="skipped"))
                st_ = res["state"]
            self.assertEqual(res["learning"]["not_learning"], [f"rival_unresolved:{reason}"], reason)

    def test_a_secret_in_the_rivals_own_verdict_is_never_the_founders_streak(self):
        """K6: three `secret_in_verdict` in a row gave {'rival_unresolved:secret_in_verdict:...': 3} and not_learning.
        The secret is in what the rival wrote; one in the Founder's diff (`secret_in_prompt`) stays the Founder's."""
        st_ = state2()
        for n in range(3):
            res = run_decide(meta2("code", st_, head=f"{n + 1:040d}"), green(),
                             unresolved("secret_in_verdict:generic_assignment"), [], dict(CODE_JOBS, yeniden="skipped"))
            st_ = res["state"]
        self.assertEqual((res["learning"]["not_learning"], st_["reject_streaks"]), ([], {}))
        st_ = state2()
        for n in range(3):
            res = run_decide(meta2("code", st_, head=f"{n + 1:040d}"), green(),
                             unresolved("secret_in_prompt:aws_access_key"), [], dict(CODE_JOBS, yeniden="skipped"))
            st_ = res["state"]
        self.assertEqual(res["learning"]["not_learning"], ["rival_unresolved:secret_in_prompt:aws_access_key"])

    def test_three_rival_side_failures_in_a_row_warn_the_operator(self):
        st_ = state2()
        for n in range(3):
            res = run_decide(meta2("code", st_, head=f"{n + 1:040d}"), green(), unresolved("model_mismatch"), [],
                             dict(CODE_JOBS, yeniden="skipped"))
            st_ = res["state"]
        self.assertEqual(st_["rival_side_streak"], 3)
        self.assertIn("rival_side_streak:3", res["warnings"])
        self.assertEqual(res["learning"]["not_learning"], [])
        res = run_decide(meta2("code", st_, head=C), green(), not_refuted(), [], dict(CODE_JOBS, yeniden="skipped"))
        self.assertEqual((res["state"]["rival_side_streak"], res["warnings"]), (0, []))

    def test_the_decide_command_raises_the_warning(self):
        import test_decision
        wiring = test_decision.CommandWiring("test_decide_command_hands_artifacts_jobs_and_policy_to_decide")
        wiring.setUp()
        self.addCleanup(wiring.tearDown)
        self.addCleanup(wiring.doCleanups)
        meta = meta2("code", state2(rival_side_streak=2))
        shown = io.StringIO()
        with contextlib.redirect_stdout(shown):
            result = wiring.decide_cmd(meta, green(), unresolved("refusal"), {"results": [], "state": []},
                                       ["getir=success", "kos=success", "cagir=success", "yeniden=skipped"])
        self.assertIn("rival_side_streak:3", result["warnings"])
        self.assertIn("::warning title=Rival", shown.getvalue())


# ---------------------------------------------------------------- E12 permanent failures and operator stops


class E12PermanentFailures(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "tree"
        (self.root / "referee").mkdir(parents=True)
        (self.root / "referee" / "a.py").write_text("x = 1\n")
        self.bin_dir = Path(self.tmp.name) / "bin"
        self.bin_dir.mkdir()
        self.claude = install_fake_claude(self.bin_dir)

    def run_with(self, scenario):
        (self.bin_dir / "scenario.json").write_text(json.dumps(scenario))
        return rival.run_rival(CFG, claude_bin=str(self.claude), seat_prompt="seat", context="ctx", tree_root=self.root,
                               budget_usd_micros=10_000_000, max_prompt_chars=100_000)

    def test_400_404_413_422_are_request_rejected_and_the_rest_stay_outages(self):
        for status in (400, 404, 413, 422):
            out = self.run_with({"calls": [], "result": ok_result(is_error=True, api_error_status=status, modelUsage={})})
            self.assertEqual(out.reasons, [f"request_rejected:http_{status}"], status)
        for status in (401, 403, 429, 500, 529):
            out = self.run_with({"calls": [], "result": ok_result(is_error=True, api_error_status=status, modelUsage={})})
            self.assertEqual(out.reasons, [f"api_error:http_{status}"], status)

    def test_a_rejected_request_is_evaluated_not_counted_and_warns(self):
        res = run_decide(meta2("code", state2(reject_streaks={"x:y": 1})), green(), unresolved("request_rejected:http_400"),
                         [], dict(CODE_JOBS, yeniden="skipped"))
        self.assertEqual((res["verdict"], res["state"]["last_evaluated_sha"]), ("rejected", B))
        self.assertEqual((res["state"]["outage_sha"], res["state"]["outage_count"]), (None, 0))
        self.assertEqual(res["state"]["reject_streaks"], {"x:y": 1})
        self.assertIn("request_rejected:http_400", res["warnings"])

    def test_an_isolation_fault_is_an_operator_stop(self):
        res = run_decide(meta2("code", state2()), green(), unresolved("api_error:isolation_tools"), [],
                         dict(CODE_JOBS, yeniden="skipped"))
        self.assertIsNone(res["state"]["last_evaluated_sha"])
        self.assertEqual((res["state"]["outage_sha"], res["state"]["outage_stop"]), (B, "isolation_tools"))
        self.assertEqual(res["state"]["outage_since"], NOW)
        ok = run_decide(meta2("code", res["state"]), green(), not_refuted(), [], dict(CODE_JOBS, yeniden="skipped"))
        self.assertEqual((ok["state"]["outage_stop"], ok["state"]["outage_since"]), (None, None))

    def test_the_first_outage_of_a_head_starts_the_clock_and_a_repeat_keeps_it(self):
        first = run_decide(meta2("spec", state2()), None, unresolved("api_error:http_529"), None, {"cagir": "success"})
        again = run_decide(meta2("spec", first["state"]), None, unresolved("api_error:http_529"), None,
                           {"cagir": "success"}, now="2026-10-30T12:00:00Z")
        self.assertEqual((again["state"]["outage_count"], again["state"]["outage_since"]), (2, NOW))


class PollStops(unittest.TestCase):
    """E12 and E13 at the poll: what is parked, what is given up, what the operator overrides."""

    setUp = test_flow.Flow.setUp
    tearDown = test_flow.Flow.tearDown

    def poll(self, prev_state, age_hours, head=C, event="schedule", failed_run=None):
        created = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=age_hours)
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("result.json", json.dumps({"state": prev_state}))
            zf.writestr("result.json.sigstore.json", "{}")
        gh = Path(self.tmp.name) / "poll_gh"
        gh.write_text("")
        env = {"GH_TOKEN": "t", "GITHUB_REPOSITORY": "o/r", "GITHUB_OUTPUT": str(gh), "GITHUB_EVENT_NAME": event,
               "GITHUB_RUN_ID": "99"}
        shown = io.StringIO()
        with contextlib.ExitStack() as stack:
            stack.enter_context(mock.patch.dict(os.environ, env))
            stack.enter_context(mock.patch.object(cli.gitio, "remote_head", return_value=head))
            stack.enter_context(mock.patch.object(cli.ghapi, "latest_artifact", return_value={
                "id": 1, "created_at": created.isoformat().replace("+00:00", "Z")}))
            stack.enter_context(mock.patch.object(cli.ghapi, "download_zip", side_effect=lambda repo, aid, token:
                                                  archive.getvalue() if aid == 1 else failed_run["zip"]))
            stack.enter_context(mock.patch.object(cli.ghapi, "latest_failed_run", create=True,
                                                  return_value=None if failed_run is None else failed_run["run"]))
            stack.enter_context(mock.patch.object(cli.ghapi, "run_jobs", create=True,
                                                  return_value=(failed_run or {}).get("jobs", {})))
            stack.enter_context(mock.patch.object(cli.ghapi, "run_artifact", create=True,
                                                  return_value={"id": 2, "name": "rival"}))
            stack.enter_context(contextlib.redirect_stdout(shown))
            rc = cli.main(["poll", "--root", str(self.referee), "--out", str(Path(self.tmp.name) / "poll_out"),
                           "--remote", "x"])
        outputs = dict(line.split("=", 1) for line in gh.read_text().split())
        return rc, outputs.get("skip"), shown.getvalue()

    @staticmethod
    def ago(days):
        when = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=days)
        return when.strftime("%Y-%m-%dT%H:%M:%SZ")

    def test_an_isolation_stop_is_red_until_the_operator_dispatches(self):
        stopped = state2(outage_sha=C, outage_count=1, outage_since=self.ago(0), outage_stop="isolation_tools")
        rc, skip, shown = self.poll(stopped, age_hours=30)
        self.assertEqual((rc, skip), (1, "true"))
        self.assertIn("::error", shown)
        self.assertEqual(self.poll(stopped, age_hours=30, event="workflow_dispatch")[:2], (0, "false"))
        self.assertEqual(self.poll(stopped, age_hours=30, head="e" * 40)[:2], (0, "false"))  # a new push runs

    def test_a_head_that_failed_for_seven_days_is_given_up_visibly(self):
        week = state2(outage_sha=C, outage_count=9, outage_since=self.ago(8))
        rc, skip, shown = self.poll(week, age_hours=30)
        self.assertEqual((rc, skip), (1, "true"))
        self.assertIn("7 days", shown)
        self.assertEqual(self.poll(state2(outage_sha=C, outage_count=9, outage_since=self.ago(2)), age_hours=30)[:2],
                         (0, "false"))  # still within the week: the daily retry
        self.assertEqual(self.poll(week, age_hours=30, event="workflow_dispatch")[:2], (0, "false"))

    def failed(self, head, jobs, hours_ago=1):
        when = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=hours_ago))
        stamp = when.strftime("%Y-%m-%dT%H:%M:%SZ")
        tar = io.BytesIO()
        with tarfile.open(fileobj=tar, mode="w") as t:
            data = json.dumps({"head": head, "verdict": "not_refuted"}).encode()
            info = tarfile.TarInfo("rival.json")
            info.size = len(data)
            t.addfile(info, io.BytesIO(data))
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("rival.tar", tar.getvalue())
        return {"run": {"id": 7, "created_at": stamp, "updated_at": stamp}, "jobs": jobs, "zip": archive.getvalue()}

    def test_a_head_whose_rival_ran_but_whose_result_was_never_signed_is_parked(self):
        """E13, W4: `yaz` failed after `cagir` succeeded; the whole pipeline (and the rival) re-ran every hour."""
        jobs = {"cek": "success", "cagir": "success", "yaz": "failure"}
        rc, skip, shown = self.poll(state2(), age_hours=30, failed_run=self.failed(C, jobs))
        self.assertEqual((rc, skip), (0, "true"))
        self.assertIn("::notice", shown)
        self.assertEqual(self.poll(state2(), 30, failed_run=self.failed(C, jobs, hours_ago=30))[:2], (0, "false"))
        self.assertEqual(self.poll(state2(), 30, failed_run=self.failed("e" * 40, jobs))[:2], (0, "false"))
        self.assertEqual(self.poll(state2(), 30, failed_run=self.failed(C, dict(jobs, yaz="success")))[:2], (0, "false"))
        self.assertEqual(self.poll(state2(), 30, failed_run=self.failed(C, dict(jobs, cagir="skipped")))[:2], (0, "false"))
        self.assertEqual(self.poll(state2(), 0.1, failed_run=self.failed(C, jobs, hours_ago=1))[:2], (0, "false"))  # signed since
        self.assertEqual(self.poll(state2(), 30, event="workflow_dispatch", failed_run=self.failed(C, jobs))[:2],
                         (0, "false"))


class GhApiRuns(unittest.TestCase):
    """The three runs-API calls the poll uses, against a local server (no network)."""

    def setUp(self):
        seen = self.seen = []

        class Api(http.server.BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                seen.append(self.path)
                if "/actions/workflows/bootstrap.yml/runs?" in self.path:
                    body = {"workflow_runs": [{"id": 11, "created_at": "2026-10-29T10:00:00Z", "conclusion": "failure"}]}
                elif self.path.startswith("/repos/o/r/actions/runs/11/jobs"):
                    body = {"jobs": [{"name": "cagir", "conclusion": "success"}, {"name": "yaz", "conclusion": "failure"}]}
                elif self.path.startswith("/repos/o/r/actions/runs/11/artifacts"):
                    body = {"artifacts": [{"id": 3, "name": "rival", "expired": False}]}
                else:
                    self.send_response(404)
                    self.end_headers()
                    return
                data = json.dumps(body).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args):
                pass

        self.server = http.server.HTTPServer(("127.0.0.1", 0), Api)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        patcher = mock.patch.dict(os.environ, {"GITHUB_API_URL": f"http://127.0.0.1:{self.server.server_port}"})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_the_failed_run_its_jobs_and_its_rival_artifact(self):
        self.assertEqual(ghapi.latest_failed_run("o/r", "t")["id"], 11)
        self.assertEqual(ghapi.run_jobs("o/r", 11, "t"), {"cagir": "success", "yaz": "failure"})
        self.assertEqual(ghapi.run_artifact("o/r", 11, "rival", "t")["id"], 3)
        self.assertIn("branch=main", self.seen[0])
        self.assertIn("status=failure", self.seen[0])


# ---------------------------------------------------------------- E13 spend never lost


class E13SpendNeverLost(unittest.TestCase):
    setUp = E12PermanentFailures.setUp

    def run_with(self, scenario, budget=10_000_000):
        (self.bin_dir / "scenario.json").write_text(json.dumps(scenario))
        return rival.run_rival(CFG, claude_bin=str(self.claude), seat_prompt="seat", context="ctx", tree_root=self.root,
                               budget_usd_micros=budget, max_prompt_chars=100_000)

    def test_a_cli_that_started_and_left_no_cost_is_booked_at_what_it_was_allowed(self):
        out = self.run_with({"calls": [], "result": None, "exit": 1})  # init, then the CLI dies without a result
        self.assertEqual((out.reasons, out.cost_usd_micros), (["api_error:cli_exit_1"], 5_000_000))  # the per-run cap
        out = self.run_with({"calls": [], "result": None, "exit": 1}, budget=1_234_567)
        self.assertEqual(out.cost_usd_micros, 1_234_567)  # less was left than the cap
        out = self.run_with({"calls": [submit()], "result": {k: v for k, v in ok_result().items()
                                                             if k != "total_cost_usd"}})
        self.assertEqual((out.reasons, out.cost_usd_micros), (["api_error:bad_cli_result"], 5_000_000))

    def test_the_spend_of_a_rival_whose_run_record_is_missing_is_still_booked(self):
        """K7: the cost was booked only when the rival was expected, which needs a green run.json; with run.json
        missing (`kos` failed after the rival ran, or an upload failed) 4 USD of real spend vanished."""
        res = run_decide(meta2("code", state2()), None, not_refuted(cost=4_000_000), None,
                         {"getir": "success", "kos": "failure", "cagir": "success"})
        self.assertEqual([r["ref"] for r in res["reasons"]], ["kos:failure"])  # an outage, retried later ...
        self.assertEqual((res["state"]["month_spend_usd_micros"], res["state"]["stage_spend_usd_micros"]),
                         (4_001_000, 4_002_000))  # ... with what the rival spent on the books
        red = dict(green(), green=False, tests=[{"id": "T13", "cmd_sha256": "c", "ok": False, "output_tail": ""}])
        res = run_decide(meta2("code", state2()), red, unresolved("api_error:http_529", cost=250), None,
                         dict(CODE_JOBS, yeniden="skipped"))
        self.assertEqual(res["state"]["month_spend_usd_micros"], 1250)

    def test_a_cli_that_never_started_cost_nothing(self):
        out = rival.run_rival(CFG, claude_bin=str(self.bin_dir / "missing"), seat_prompt="s", context="c",
                              tree_root=self.root, budget_usd_micros=10_000_000, max_prompt_chars=100_000)
        self.assertEqual((out.reasons, out.cost_usd_micros), (["api_error:FileNotFoundError"], 0))

    def test_an_interrupted_rival_command_still_writes_its_record(self):
        flow = test_flow.Flow("test_full_stage0_path")
        flow.setUp()
        self.addCleanup(flow.tearDown)
        seats = flow.referee / "seats"
        seats.mkdir()
        source = Path(test_flow.__file__).resolve().parents[3] / "spec" / "tohum" / cli.SEATS_FILE
        (seats / cli.SEATS_FILE).write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
        commit(flow.brain, {"spec/asama-0/00-ozet.md": "# revised\n"}, "spec")
        meta = flow.pull()
        pulled = Path(flow.tmp.name) / f"pulled{flow.n}"
        out = Path(flow.tmp.name) / "rival"
        with mock.patch.object(rival, "_run_cli", side_effect=KeyboardInterrupt), \
                mock.patch.dict(os.environ, {"GITHUB_OUTPUT": str(Path(flow.tmp.name) / "gh")}):
            with self.assertRaises(KeyboardInterrupt):
                cli.main(["rival", "--root", str(flow.referee), "--pulled", str(pulled), "--work",
                          str(Path(flow.tmp.name) / "w"), "--out", str(out), "--claude", str(self.claude)])
        doc = json.loads((out / "rival.json").read_text())
        self.assertEqual((doc["verdict"], doc["reasons"], doc["cost_usd_micros"]),
                         ("unresolved", ["api_error:KeyboardInterrupt"], 3_000_000))  # bootstrap.json's per-run cap
        self.assertEqual(doc["head"], meta["head"])


# ---------------------------------------------------------------- E20 one rival attempt per artifact


class E20OneAttemptPerArtifact(unittest.TestCase):
    def exit_meta(self, state):
        return meta2("exit", state, manifest={"tests": [], "done_mf": list(range(1, 19)), "lockfiles": []},
                     referee_tree_sha256="f" * 64, exit_request={"stage": 0, "sha": A, "spec_sha256": "e" * 64},
                     run_rival=False)

    def test_only_artifacts_that_survived_the_rival_count_at_exit(self):
        arts = [{"sha": A, "outcome": "survived"}, {"sha": "1" * 40, "outcome": "refuted"},
                {"sha": "2" * 40, "outcome": "survived"}, {"sha": "3" * 40, "outcome": "unknown"}]
        res = run_decide(self.exit_meta(state2(rival_artifacts=arts)), green(), None, None,
                         {"getir": "success", "kos": "success"})
        self.assertEqual(res["exit"]["missing"], ["rival_attempts:1<2"])
        arts.append({"sha": "4" * 40, "outcome": "survived"})
        res = run_decide(self.exit_meta(state2(rival_artifacts=arts)), green(), None, None,
                         {"getir": "success", "kos": "success"})
        self.assertEqual((res["verdict"], res["exit"]["missing"]), ("accepted", []))
        arts[0]["outcome"] = "refuted"
        res = run_decide(self.exit_meta(state2(rival_artifacts=arts)), green(), None, None,
                         {"getir": "success", "kos": "success"})
        self.assertIn("no_rival_attempt_on_exit_sha", res["exit"]["missing"])

    def test_each_reviewed_head_is_recorded_once_with_its_outcome(self):
        res = run_decide(meta2("code", state2()), green(), refuted_by(attempt("c")), [ran(0, True)], CODE_JOBS)
        self.assertEqual(res["state"]["rival_artifacts"], [{"sha": B, "outcome": "refuted"}])
        res = run_decide(meta2("code", state2()), green(), not_refuted(), [], dict(CODE_JOBS, yeniden="skipped"))
        self.assertEqual(res["state"]["rival_artifacts"], [{"sha": B, "outcome": "survived"}])
        res = run_decide(meta2("code", state2()), green(), unresolved("refusal"), [], dict(CODE_JOBS, yeniden="skipped"))
        self.assertEqual(res["state"]["rival_artifacts"], [])

    def test_a_retry_after_a_reproduction_outage_reuses_the_rival_result(self):
        """D11: the retry called the rival again, against tohum/29 (one attempt per artifact)."""
        rival_doc = refuted_by(attempt("c"), cost=700)
        first = run_decide(meta2("code", state2()), green(), rival_doc, None, dict(CODE_JOBS, yeniden="failure"))
        self.assertEqual(first["state"]["pending_rival"]["sha"], B)
        self.assertEqual(first["state"]["pending_rival"]["rival"]["attempts"], rival_doc["attempts"])
        self.assertEqual(first["state"]["rival_artifacts"], [])  # not yet: its reproducers never ran
        self.assertEqual(first["state"]["month_spend_usd_micros"], 1700)
        retry = run_decide(meta2("code", first["state"], run_rival=False, reuse_rival=True), green(), None,
                           [ran(0, False)], dict(CODE_JOBS, cagir="skipped"))
        self.assertEqual(retry["verdict"], "accepted", retry["reasons"])
        self.assertTrue(retry["rival_reused"])
        self.assertEqual(retry["rival"]["cost_usd_micros"], 700)  # what it cost is still on record ...
        self.assertEqual((retry["state"]["month_spend_usd_micros"], retry["state"]["stage_spend_usd_micros"]),
                         (1700, 2700))  # ... and booked once
        self.assertEqual(retry["state"]["rival_artifacts"], [{"sha": B, "outcome": "survived"}])
        self.assertIsNone(retry["state"]["pending_rival"])

    def test_pull_reuses_the_pending_rival_of_the_same_head_and_asks_only_for_its_reproducers(self):
        flow = test_flow.Flow("test_full_stage0_path")
        flow.setUp()
        self.addCleanup(flow.tearDown)
        commit(flow.brain, {"spec/asama-0/00-ozet.md": "# revised\n"}, "spec")
        head = flow.pull()["head"]
        flow.state = state2(last_accepted_sha=flow.seed_sha,
                            pending_rival={"sha": head, "rival": refuted_by(attempt("c"))})
        gh = Path(flow.tmp.name) / "gh"
        with mock.patch.dict(os.environ, {"GITHUB_OUTPUT": str(gh)}), contextlib.redirect_stdout(io.StringIO()):
            meta = flow.pull()
        self.assertEqual((meta["kind"], meta["run_rival"], meta["reuse_rival"]), ("spec", False, True))
        self.assertIn("repro=true", gh.read_text())
        flow.state["pending_rival"]["sha"] = "9" * 40
        meta = flow.pull()
        self.assertEqual((meta["run_rival"], meta["reuse_rival"]), (True, False))


# ---------------------------------------------------------------- E07 open claims


class E07OpenClaims(unittest.TestCase):
    def test_an_unreproduced_refutation_is_kept_as_an_open_claim(self):
        rival_doc = refuted_by(attempt("cp_lower is the Wilson bound"), attempt("no reproducer here", rep=None))
        res = run_decide(meta2("code", state2()), green(), rival_doc, [ran(0, False, stdout_tail="lb 0.31")], CODE_JOBS)
        self.assertEqual(res["verdict"], "accepted")
        claims = res["state"]["open_claims"]
        self.assertEqual([c["claim"] for c in claims], ["cp_lower is the Wilson bound", "no reproducer here"])
        self.assertEqual(claims[0]["id"], hashlib.sha256(b"cp_lower is the Wilson bound").hexdigest()[:12])
        self.assertEqual((claims[0]["reproducer"]["cmd"], claims[0]["first_head"], claims[0]["rewritten"]),
                         (REP["cmd"], B, False))
        self.assertEqual(claims[0]["observed"]["stdout_tail"], "lb 0.31")
        self.assertIsNone(claims[1]["reproducer"])
        not_refuting = run_decide(meta2("code", state2()), green(), dict(not_refuted(), attempts=[attempt("tried x")],
                                                                         reproducer_count=1),
                                  [ran(0, False)], CODE_JOBS)
        self.assertEqual(not_refuting["state"]["open_claims"], [])  # the paths a not_refuted verdict tried are no claims

    def test_open_claims_are_bounded_newest_kept(self):
        claims = [claim_entry(f"claim {n}") for n in range(st.MAX_OPEN_CLAIMS)]
        res = run_decide(meta2("code", state2(open_claims=claims)), green(), refuted_by(attempt("the newest", rep=None)),
                         [], dict(CODE_JOBS, yeniden="skipped"))
        kept = [c["claim"] for c in res["state"]["open_claims"]]
        self.assertEqual(len(kept), st.MAX_OPEN_CLAIMS)
        self.assertEqual((kept[0], kept[-1]), ("claim 1", "the newest"))

    def test_the_next_rival_run_is_shown_the_open_claims(self):
        claim = dict(claim_entry(), observed={"exit": 0, "timed_out": False, "tautological": None,
                                              "stdout_tail": "lb 0.31", "stderr_tail": ""})
        ctx = rival.build_context("code", A, B, ["x.py"], "diff", {}, fence="f" * 16, open_claims=[claim])
        section = ctx.split("=== " + "f" * 16 + " open claims", 1)[1].split("=== " + "f" * 16, 1)[0]
        self.assertIn(claim["id"], section)
        self.assertIn("cp_lower is the Wilson bound", section)
        self.assertIn("lb 0.31", section)
        self.assertIn('"rewrite_allowed": true', section)
        self.assertNotIn("open claims", rival.build_context("code", A, B, [], "", {}, fence="f" * 16))

    def test_the_rival_command_hands_the_open_claims_over(self):
        flow = test_flow.Flow("test_full_stage0_path")
        flow.setUp()
        self.addCleanup(flow.tearDown)
        seats = flow.referee / "seats"
        seats.mkdir()
        source = Path(test_flow.__file__).resolve().parents[3] / "spec" / "tohum" / cli.SEATS_FILE
        (seats / cli.SEATS_FILE).write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
        claim = claim_entry()
        flow.state = state2(last_accepted_sha=flow.seed_sha, open_claims=[claim])
        commit(flow.brain, {"spec/asama-0/00-ozet.md": "# revised\n"}, "spec")
        flow.pull()
        bin_dir = Path(flow.tmp.name) / "bin"
        bin_dir.mkdir()
        claude = install_fake_claude(bin_dir)
        (bin_dir / "scenario.json").write_text(json.dumps({"calls": [submit()], "result": ok_result()}))
        with mock.patch.dict(os.environ, {"GITHUB_OUTPUT": str(Path(flow.tmp.name) / "gh")}), \
                contextlib.redirect_stdout(io.StringIO()):
            rc = cli.main(["rival", "--root", str(flow.referee), "--pulled", str(Path(flow.tmp.name) / f"pulled{flow.n}"),
                           "--work", str(Path(flow.tmp.name) / "w"), "--out", str(Path(flow.tmp.name) / "rival"),
                           "--claude", str(claude)])
        self.assertEqual(rc, 0)
        stdin = json.loads((bin_dir / "seen.json").read_text())["stdin"]
        self.assertIn('"id": "' + claim["id"] + '"', stdin)

    def test_the_rival_may_rewrite_a_claims_reproducer_once(self):
        claim = claim_entry()
        new_rep = {"cmd": "python -m harness.stats cp_lower 3 10 0.05", "expect_exit": None,
                   "expect_stdout_contains": "0.0667", "expect_stderr_contains": None}
        first = run_decide(meta2("code", state2(open_claims=[claim])), green(),
                           refuted_by(attempt("restated", new_rep, open_claim=claim["id"])),
                           [ran(0, False, rep=new_rep)], CODE_JOBS)
        got = first["state"]["open_claims"]
        self.assertEqual(len(got), 1)
        self.assertEqual((got[0]["id"], got[0]["reproducer"]["cmd"], got[0]["rewritten"]),
                         (claim["id"], new_rep["cmd"], True))
        third = dict(new_rep, cmd="python -m harness.stats cp_lower 4 10 0.05")
        second = run_decide(meta2("code", first["state"], head=C), green(),
                            refuted_by(attempt("again", third, open_claim=claim["id"])), [ran(0, False, rep=third)],
                            CODE_JOBS)
        self.assertEqual([c["reproducer"]["cmd"] for c in second["state"]["open_claims"] if c["id"] == claim["id"]],
                         [new_rep["cmd"]])  # no second rewrite

    def test_a_reference_to_an_open_claim_is_validated(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "referee").mkdir()
            (Path(tmp) / "referee" / "a.py").write_text("x = 1\n")
            box = rival.ToolBox(Path(tmp))
            ok = {"claim": "c", "evidence_refs": REFS, "open_claim": "0123456789ab",
                  "reproducer": {"cmd": "x", "expect_exit": 1}}
            self.assertEqual(rival.validate_verdict({"verdict": "refuted", "attempts": [ok]}, box)["attempts"][0]
                             ["open_claim"], "0123456789ab")
            with self.assertRaises(ValueError):
                rival.validate_verdict({"verdict": "refuted", "attempts": [dict(ok, open_claim="nothex")]}, box)

    def test_an_open_claim_that_reproduces_on_a_later_head_blocks_it_and_becomes_a_proven_defect(self):
        claim = claim_entry()
        res = run_decide(meta2("code", state2(open_claims=[claim]), state_repro=[claim["id"]]), green(), not_refuted(),
                         [], CODE_JOBS, state_repro=[state_ran(claim["id"], "claim", True)])
        self.assertEqual(res["verdict"], "rejected")
        self.assertEqual([(r["kind"], r["ref"]) for r in res["reasons"]],
                         [("refutation_reproduced", "repro:" + key_of(REP))])
        self.assertEqual(res["state"]["open_claims"], [])
        self.assertEqual([e["key"] for e in res["state"]["open_refutations"]], [key_of(REP)])

    def test_a_claim_the_rival_proves_is_no_longer_open(self):
        claim, named = claim_entry(rep=None), claim_entry("named by id", rep=None)
        res = run_decide(meta2("code", state2(open_claims=[claim, named])), green(),
                         refuted_by(attempt(claim["claim"]), attempt("other words", dict(REP, cmd="python -m y"),
                                                                     open_claim=named["id"])),
                         [ran(0, True), ran(1, True, rep=dict(REP, cmd="python -m y"))], CODE_JOBS)
        self.assertEqual(res["verdict"], "rejected")
        self.assertEqual(res["state"]["open_claims"], [])
        self.assertEqual(len(res["state"]["open_refutations"]), 2)

    def test_the_exit_lists_the_open_claims(self):
        claim = claim_entry()
        meta = E20OneAttemptPerArtifact.exit_meta(None, state2(
            open_claims=[claim], rival_artifacts=[{"sha": s, "outcome": "survived"} for s in (A, "1" * 40, "2" * 40)]))
        meta["state_repro"] = [claim["id"]]
        res = run_decide(meta, green(), None, None, {"getir": "success", "kos": "success", "yeniden": "success"},
                         state_repro=[state_ran(claim["id"], "claim", False)])
        self.assertEqual(res["verdict"], "accepted", res["reasons"])
        self.assertEqual(res["exit"]["open_claims"], [{"id": claim["id"], "claim": claim["claim"], "first_head": C}])


# ---------------------------------------------------------------- E08 proven defects are remembered


class E08ProvenDefects(unittest.TestCase):
    def test_a_reproduced_refutation_is_remembered_by_its_command_and_expectation(self):
        self.assertEqual(reproduce.reproducer_key(REP), key_of(REP))
        res = run_decide(meta2("code", state2()), green(), refuted_by(attempt("the chain accepts a broken row")),
                         [ran(0, True)], CODE_JOBS)
        self.assertEqual([(r["kind"], r["ref"]) for r in res["reasons"]],
                         [("refutation_reproduced", "repro:" + key_of(REP))])
        entry = res["state"]["open_refutations"][0]
        self.assertEqual((entry["key"], entry["claim"], entry["first_head"]),
                         (key_of(REP), "the chain accepts a broken row", B))

    def test_a_later_push_is_rejected_while_it_still_reproduces_even_when_the_rival_finds_nothing(self):
        """R1: the same tree pushed as a new commit was accepted when the new rival missed the defect."""
        entry = refutation_entry()
        res = run_decide(meta2("code", state2(open_refutations=[entry]), state_repro=[entry["key"]]), green(),
                         not_refuted(), [], CODE_JOBS, state_repro=[state_ran(entry["key"], "refutation", True)])
        self.assertEqual(res["verdict"], "rejected")
        self.assertEqual([(r["kind"], r["ref"]) for r in res["reasons"]],
                         [("refutation_still_reproduces", "repro:" + entry["key"])])
        self.assertEqual(res["state"]["open_refutations"][0]["last_head"], B)
        self.assertEqual(res["state"]["rival_artifacts"], [{"sha": B, "outcome": "refuted"}])

    def test_rewording_the_claim_does_not_hide_a_repeat(self):
        """D9: the signature was sha256(claim); the same defect in other words started a new streak."""
        st_ = state2()
        for n, claim in enumerate(("hash ignores prev_hash", "the chain is not linked"), start=1):
            res = run_decide(meta2("code", st_, head=f"{n:040d}", state_repro=[e["key"] for e in st_["open_refutations"]]),
                             green(), refuted_by(attempt(claim)), [ran(0, True)], CODE_JOBS,
                             state_repro=[state_ran(e["key"], "refutation", True) for e in st_["open_refutations"]])
            st_ = res["state"]
        res = run_decide(meta2("code", st_, head="3" * 40, state_repro=[key_of(REP)]), green(), not_refuted(), [],
                         CODE_JOBS, state_repro=[state_ran(key_of(REP), "refutation", True)])
        self.assertEqual(res["learning"]["not_learning"], ["refutation:" + key_of(REP)])
        self.assertEqual(len(res["state"]["open_refutations"]), 1)

    def test_it_closes_only_on_an_accepted_head_where_it_no_longer_reproduces(self):
        entry = refutation_entry()
        other = refutation_entry(dict(REP, cmd="python -m other"), claim="other")
        meta = meta2("code", state2(open_refutations=[entry, other]), state_repro=[entry["key"], other["key"]])
        still = run_decide(meta, green(), not_refuted(), [], CODE_JOBS,
                           state_repro=[state_ran(entry["key"], "refutation", False),
                                        state_ran(other["key"], "refutation", True)])
        self.assertEqual(len(still["state"]["open_refutations"]), 2)  # rejected head: nothing closes
        fixed = run_decide(meta, green(), not_refuted(), [], CODE_JOBS,
                           state_repro=[state_ran(entry["key"], "refutation", False),
                                        state_ran(other["key"], "refutation", False)])
        self.assertEqual((fixed["verdict"], fixed["state"]["open_refutations"]), ("accepted", []))
        spec = run_decide(meta2("spec", state2(open_refutations=[entry])), None, not_refuted(), [], {"cagir": "success"})
        self.assertEqual((spec["verdict"], len(spec["state"]["open_refutations"])), ("frozen", 1))  # never ran there

    def test_an_operator_waiver_closes_it(self):
        entry = refutation_entry()
        res = run_decide(meta2("spec", state2(open_refutations=[entry]), waived=[entry["key"]]), None, not_refuted(),
                         [], {"cagir": "success"})
        self.assertEqual(res["state"]["open_refutations"], [])
        self.assertEqual(res["waived"], [entry["key"]])

    def test_a_state_reproducer_that_did_not_run_is_an_outage(self):
        entry = refutation_entry()
        meta = meta2("code", state2(open_refutations=[entry]), state_repro=[entry["key"]])
        for jobs, results, ref in ((dict(CODE_JOBS, yeniden="skipped"), None, "yeniden:skipped"),
                                   (CODE_JOBS, [], "yeniden:incomplete"),
                                   (CODE_JOBS, [state_ran(entry["key"], "refutation", False, runner_fault=True)],
                                    "yeniden:docker")):
            res = run_decide(meta, green(), not_refuted(), [], jobs, state_repro=results)
            self.assertEqual([(r["kind"], r["ref"]) for r in res["reasons"]], [("infra", ref)], ref)
            self.assertIsNone(res["state"]["last_evaluated_sha"], ref)

    def test_pull_asks_for_the_state_reproducers_on_code_and_exit_heads_only(self):
        flow = test_flow.Flow("test_full_stage0_path")
        flow.setUp()
        self.addCleanup(flow.tearDown)
        flow.state = state2(last_accepted_sha=flow.seed_sha)
        commit(flow.brain, {"spec/asama-0/00-ozet.md": "# frozen\n"}, "spec")
        flow.finish(flow.pull(), rival=flow.rival_ok(), jobs={"cagir": "success"})
        entry, claim = refutation_entry(), claim_entry(rep=dict(REP, cmd="python -m other"))
        flow.state.update(open_refutations=[entry], open_claims=[claim, claim_entry("no reproducer", rep=None)])
        commit(flow.brain, {"referee/a.py": "x = 1\n", "snowball-tests.json": test_flow.all_tests_manifest([1])}, "mf1")
        gh = Path(flow.tmp.name) / "gh"
        with mock.patch.dict(os.environ, {"GITHUB_OUTPUT": str(gh)}), contextlib.redirect_stdout(io.StringIO()):
            meta = flow.pull()
        self.assertEqual((meta["kind"], meta["state_repro"]), ("code", [entry["key"], claim["id"]]))
        self.assertIn("repro=true", gh.read_text())
        commit(flow.brain, {"referee/a.py": None, "snowball-tests.json": None, "spec/asama-1/00.md": "# next\n"}, "spec")
        self.assertEqual(flow.pull()["state_repro"], [])

    def test_the_reproduce_command_runs_the_state_reproducers(self):
        flow = test_flow.Flow("test_full_stage0_path")
        flow.setUp()
        self.addCleanup(flow.tearDown)
        base = Path(flow.tmp.name)
        src = base / "tree"
        (src / "referee").mkdir(parents=True)
        (src / "referee" / "a.py").write_text("x = 1\n")
        pulled = base / "pulled_x"
        pulled.mkdir()
        cli.pack_dir(src, pulled / "brain.tar")
        entry, claim = refutation_entry(), claim_entry(rep=dict(REP, cmd="python -m other"))
        meta = meta2("code", state2(open_refutations=[entry], open_claims=[claim]),
                     state_repro=[entry["key"], claim["id"]], manifest={"lockfiles": []})
        (pulled / "meta.json").write_text(json.dumps(meta))
        (base / "rv").mkdir()  # no rival.json: the rival was not called on this head
        (base / "deps").mkdir()
        runner = FakeRunner(Path("."), commands={REP["cmd"]: (1, b'{"valid": true}\n'),
                                                 "python -m other": (1, b"")})
        with mock.patch.object(cli, "_runner", lambda boot, tree, deps, vectors, locks: runner if locks or
                               any(Path(tree).iterdir()) else Returns(1)):
            rc = cli.main(["reproduce", "--root", str(flow.referee), "--pulled", str(pulled), "--deps", str(base / "deps"),
                           "--rival", str(base / "rv"), "--work", str(base / "work"), "--out", str(base / "repro")])
        self.assertEqual(rc, 0)
        doc = json.loads((base / "repro" / "repro.json").read_text())
        self.assertEqual(doc["results"], [])
        self.assertEqual([(r["key"], r["source"], r["reproduced"]) for r in doc["state"]],
                         [(entry["key"], "refutation", True), (claim["id"], "claim", False)])

    def test_the_workflow_runs_the_reproduction_job_for_the_states_reproducers(self):
        cek = WORKFLOW[WORKFLOW.index("  cek:"):WORKFLOW.index("  getir:")]
        self.assertIn("repro: ${{ steps.pull.outputs.repro }}", cek)
        yeniden = WORKFLOW[WORKFLOW.index("  yeniden:"):WORKFLOW.index("  yaz:")]
        condition = yeniden.split("steps:", 1)[0]
        self.assertIn("needs.cek.outputs.repro == 'true'", condition)
        self.assertIn("needs.cagir.outputs.has_repro == 'true'", condition)
        self.assertIn("if: needs.cagir.result == 'success'", yeniden)  # the rival artifact exists only then
        self.assertIn("if [ -f rival.tar ]", yeniden)


# ---------------------------------------------------------------- E27 isolation found at the init event


class E27EarlyInit(unittest.TestCase):
    setUp = E12PermanentFailures.setUp

    def run_with(self, scenario):
        (self.bin_dir / "scenario.json").write_text(json.dumps(scenario))
        started = time.monotonic()
        out = rival.run_rival(CFG, claude_bin=str(self.claude), seat_prompt="seat", context="ctx", tree_root=self.root,
                              budget_usd_micros=10_000_000, max_prompt_chars=100_000)
        return out, time.monotonic() - started

    def test_a_bad_init_kills_the_cli_before_any_tool_call(self):
        cases = {"api_error:isolation_tools": good_init(tools=[*rival.TOOL_NAMES, "Bash"]),
                 "api_error:isolation_version": good_init(claude_code_version="0.0.1"),
                 "model_mismatch": good_init(model="claude-opus-5-5"),
                 "api_error:isolation_api_key": good_init(apiKeySource="user", model="claude-opus-5-5")}  # isolation first
        for reason, init in cases.items():
            (self.bin_dir / "calls.started").unlink(missing_ok=True)
            out, seconds = self.run_with({"init_first": True, "init": init, "sleep": 60, "calls": [submit()],
                                          "result": ok_result()})
            self.assertEqual((out.verdict, out.reasons, out.cost_usd_micros), ("unresolved", [reason], 0), reason)
            self.assertLess(seconds, 10, reason)  # the fake CLI would sleep 60 s after its init event
            self.assertFalse((self.bin_dir / "calls.started").exists(), reason)

    def test_a_good_init_lets_the_run_go_on(self):
        out, _ = self.run_with({"init_first": True, "calls": [submit()], "result": ok_result()})
        self.assertEqual((out.verdict, out.reasons), ("not_refuted", []))


# ---------------------------------------------------------------- E33 provenance


class E33Provenance(unittest.TestCase):
    setUp = E12PermanentFailures.setUp

    def test_the_record_says_how_the_run_was_made(self):
        usage = {"input_tokens": 6, "output_tokens": 210, "cache_read_input_tokens": 6041,
                 "cache_creation_input_tokens": 244, "service_tier": "standard"}
        (self.bin_dir / "scenario.json").write_text(json.dumps({"calls": [submit()], "result": ok_result(usage=usage)}))
        out = rival.run_rival(CFG, claude_bin=str(self.claude), seat_prompt="seat", context="ctx", tree_root=self.root,
                              budget_usd_micros=10_000_000, max_prompt_chars=100_000).as_dict()
        self.assertEqual((out["cli_version"], out["effort"]), (PINNED_CLI, "medium"))
        self.assertEqual(out["prompt_sha256"], hashlib.sha256(("seat" + rival.PROTOCOL + "\n" + "ctx").encode()).hexdigest())
        self.assertEqual(out["tokens"], {"input_tokens": 6, "output_tokens": 210, "cache_read_input_tokens": 6041,
                                         "cache_creation_input_tokens": 244})
        self.assertIsInstance(out["duration_ms"], int)
        canon.canonical(out)  # every field can be signed

    def test_a_cli_of_another_version_is_an_isolation_fault(self):
        events = [good_init(claude_code_version="9.9.9"),
                  {"type": "assistant", "message": {"model": "claude-sonnet-5-5"}}, ok_result()]
        (self.bin_dir / "scenario.json").write_text(json.dumps({"calls": [submit()], "events": events}))
        out = rival.run_rival(CFG, claude_bin=str(self.claude), seat_prompt="seat", context="ctx", tree_root=self.root,
                              budget_usd_micros=10_000_000, max_prompt_chars=100_000)
        self.assertEqual((out.reasons, out.cli_version), (["api_error:isolation_version"], "9.9.9"))

    def test_a_drifted_version_is_caught_after_the_run_too(self):
        """Should the init event escape the check as it streams (it never has), the finished run is checked again."""
        stream = "\n".join(json.dumps(e) for e in (good_init(claude_code_version="9.9.9"),
                                                   {"type": "assistant", "message": {"model": "claude-sonnet-5-5"}},
                                                   ok_result())) + "\n"
        (self.bin_dir / "scenario.json").write_text(json.dumps({"calls": [submit()], "raw": ""}))
        with mock.patch.object(rival, "_run_cli", lambda *a, **k: (0, stream)):
            out = rival.run_rival(CFG, claude_bin=str(self.claude), seat_prompt="seat", context="ctx",
                                  tree_root=self.root, budget_usd_micros=10_000_000, max_prompt_chars=100_000)
        self.assertEqual(out.reasons, ["api_error:isolation_version"])


# ---------------------------------------------------------------- E141 docker failing during the vectors


class E141DockerFailingDuringVectors(unittest.TestCase):
    """K2: the E01 class again. Since E01 the prelude turns a command's own 125 into 1, so 125 only ever means docker
    itself failed; the vectors kept no exit code and such a run became `vector_failed`, judged and counted."""

    def vectors(self):
        from snowball_bootstrap.vectors import run_vectors
        vec_dir = Path(test_flow.__file__).resolve().parents[1] / "vectors"
        return run_vectors(Returns(125, b"", b"docker: Error response from daemon"), vec_dir, STATS, table=EVERY_GROUP)

    def test_a_vector_run_that_docker_failed_says_so(self):
        results = self.vectors()
        self.assertTrue(results)
        self.assertTrue(all(r["runner_fault"] and r["exit"] == 125 and not r["ok"] for r in results), results[:2])
        from snowball_bootstrap.vectors import run_vectors
        vec_dir = Path(test_flow.__file__).resolve().parents[1] / "vectors"
        wrong = run_vectors(Returns(1, b"", b"Traceback"), vec_dir, (1,))  # the Founder's code failing is not docker
        self.assertTrue(wrong and not any(r["runner_fault"] for r in wrong))

    def test_it_is_an_outage_never_the_founders_rejection(self):
        run = dict(green(), vectors=self.vectors(), green=False)
        st_ = state2(reject_streaks={"test_failed:T13": 1})
        for n in range(3):
            res = run_decide(meta2("code", st_, head=f"{n + 1:040d}"), run, None, None,
                             dict(CODE_JOBS, cagir="skipped", yeniden="skipped"))
            self.assertEqual([(r["kind"], r["ref"]) for r in res["reasons"]], [("infra", "kos:docker")])
            self.assertIsNone(res["state"]["last_evaluated_sha"])
            self.assertEqual((res["state"]["reject_streaks"], res["learning"]["not_learning"]),
                             ({"test_failed:T13": 1}, []))
            st_ = res["state"]


# ---------------------------------------------------------------- the state schema


class StateSchemaV2(unittest.TestCase):
    def v1(self):
        return {"schema": "snowball-bootstrap-state/1", "origin": "artifact", "last_accepted_sha": A,
                "last_evaluated_sha": B, "frozen_specs": {"spec/asama-0": "e" * 64}, "rival_artifacts": [A, "1" * 40],
                "month": "2026-10", "month_spend_usd_micros": 5, "stage_spend_usd_micros": 7, "runs": 9,
                "reject_streaks": {"test_failed:T13": 2}, "repeat_events": 3, "outage_sha": C, "outage_count": 2}

    def test_a_v1_state_is_carried_forward(self):
        new = st.validate(st.migrate(self.v1(), NOW))
        self.assertEqual(new["schema"], "snowball-bootstrap-state/2")
        for key in ("last_accepted_sha", "last_evaluated_sha", "frozen_specs", "month", "month_spend_usd_micros",
                    "stage_spend_usd_micros", "runs", "reject_streaks", "repeat_events", "outage_sha", "outage_count"):
            self.assertEqual(new[key], self.v1()[key], key)
        self.assertEqual(new["rival_artifacts"], [{"sha": A, "outcome": "survived"}, {"sha": "1" * 40, "outcome": "unknown"}])
        self.assertEqual((new["outage_since"], new["open_refutations"], new["open_claims"], new["pending_rival"]),
                         (NOW, [], [], None))
        self.assertEqual(st.migrate(new, NOW), new)  # a current state passes unchanged

    def test_states_of_unknown_shape_are_still_refused(self):
        for bad in ({"schema": "snowball-bootstrap-state/9"}, dict(self.v1(), extra=1), "x",
                    {k: v for k, v in self.v1().items() if k != "runs"}):
            with self.assertRaises(ConfigError, msg=str(bad)[:60]):
                st.validate(st.migrate(bad, NOW))

    def test_the_new_fields_are_validated(self):
        good = st.initial(Summary(A, "b" * 64), "2026-10")
        st.validate(good)
        for bad in (dict(good, rival_artifacts=[A]), dict(good, rival_artifacts=[{"sha": A, "outcome": "maybe"}]),
                    dict(good, outage_since="yesterday"), dict(good, rival_side_streak=-1),
                    dict(good, open_refutations=[{"key": "x"}]), dict(good, open_claims=[{"id": 1}]),
                    dict(good, pending_rival={"sha": "x"}),
                    dict(good, open_claims=[claim_entry(f"c{n}") for n in range(st.MAX_OPEN_CLAIMS + 1)])):
            with self.assertRaises(ConfigError, msg=str(bad)[:80]):
                st.validate(bad)
        st.validate(dict(good, open_refutations=[refutation_entry()], open_claims=[claim_entry()],
                         pending_rival={"sha": B, "rival": refuted_by(attempt("c"))},
                         rival_artifacts=[{"sha": A, "outcome": "refuted"}], outage_since=NOW))

    @posix_only
    def test_fetch_state_migrates_instead_of_stopping(self):
        import test_decision
        case = test_decision.CommandWiring("test_decide_command_hands_artifacts_jobs_and_policy_to_decide")
        case.setUp()
        self.addCleanup(case.tearDown)
        self.addCleanup(case.doCleanups)  # the case's own cleanups put ghapi.download_zip back
        case.previous_state_zip(self.v1())
        self.assertEqual(case.fetch_ok(), 0)
        got = json.loads((case.root / "state" / "state.json").read_text())
        self.assertEqual((got["schema"], got["reject_streaks"], got["frozen_specs"]),
                         ("snowball-bootstrap-state/2", {"test_failed:T13": 2}, {"spec/asama-0": "e" * 64}))


class PullOutputsWiring(unittest.TestCase):
    def test_the_workflow_reads_exactly_what_pull_prints(self):
        flow = test_flow.Flow("test_full_stage0_path")
        flow.setUp()
        self.addCleanup(flow.tearDown)
        commit(flow.brain, {"spec/asama-0/00-ozet.md": "# revised\n"}, "spec")
        gh = Path(flow.tmp.name) / "gh"
        with mock.patch.dict(os.environ, {"GITHUB_OUTPUT": str(gh)}), contextlib.redirect_stdout(io.StringIO()):
            flow.pull()
        printed = {line.split("=", 1)[0] for line in gh.read_text().splitlines() if line}
        read = set(re.findall(r"steps\.pull\.outputs\.([a-z_]+)", WORKFLOW))
        self.assertIn("repro", read)
        self.assertLessEqual(read, printed)  # an output the workflow reads but pull never prints is always empty


if __name__ == "__main__":
    unittest.main()
