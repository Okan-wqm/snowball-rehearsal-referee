"""The measurement mirror (`seed/founder/mirror.py`; the owner's decision of 2026-11-19, E647).

Before each session the launcher writes `/work/logs/mirror.json`: facts the Founder reads at its start, counted from the
launcher's own records on disk (`pilot-metrics.jsonl`, each session folder's `previous-session.json`, `loop-runs.jsonl`
and transcript) and from the referee repository's tarball the launcher already downloads for /vec. Facts only: no advice,
no ranking, no judgement of what could have been seen before a transfer. Every section names its source and window; a
metric that cannot be computed is null with its reason; a section that fails is null and the others stand; every list
is capped; the same files give the same bytes. Nothing reaches GitHub here.
"""

import no_real_delays  # noqa: F401  (first: no test waits on a real delay, E751)
import importlib.util
import json
import re
import subprocess
import tempfile
from datetime import datetime, timezone
import unittest
from pathlib import Path
from unittest import mock

from snowball_bootstrap.treehash import RESERVED_TOP

from helpers import quiet_pilot
from test_founder_capsule import VECTORS, files_under, load_launch, tarball

ROOT = Path(__file__).resolve().parents[3]
STAMP = "20261119T120000Z"
A, B, C = "a" * 40, "b" * 40, "c" * 40
TOP = "o-referee-1a2b3c4/"
NAME = "Zorbalix"
TOKEN = "gh" + "p_" + "A" * 36  # built at run time, never written
STAMP_RE = re.compile(r"[0-9]{8}T[0-9]{6}Z")


def load_mirror():
    spec = importlib.util.spec_from_file_location("founder_mirror", ROOT / "seed" / "founder" / "mirror.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


M = load_mirror()


def flat(text):
    return " ".join(text.split())


def cycle(stamp, **kw):
    row = {"stamp": stamp, "model": "claude-x", "model_served": "claude-x", "effort": "medium", "pushed": True,
           "kind": "code", "verdict": "accepted", "reasons": [], "cost_usd": 2.0, "minutes": 30.0, "end": "exit"}
    row.update(kw)
    return row


def run(rid, created, conclusion="success", status="completed"):
    return {"kind": "run", "id": rid, "created_at": created, "conclusion": conclusion, "status": status}


def job(rid, name, conclusion="success", summary=None, output=None, why=None):
    return {"kind": "job", "run": rid, "name": name, "conclusion": conclusion, "status": "completed",
            "summary": summary, "summary_why": why, "output": output}


def cek(rid, transfer):
    return job(rid, "cek", summary={"job": "cek", "ok": True, "accepted": {"transfer_sha": transfer}})


def referee(reverted=(), imports=(), extra=None):
    files = {TOP + "control.json": json.dumps({"kill_switch": False, "reverted_exits": list(reverted)}).encode(),
             TOP + "setup/imports.jsonl": b"".join(json.dumps(r).encode() + b"\n" for r in imports)}
    files.update(extra or {})
    return M.referee_facts(tarball(files), RESERVED_TOP)


class Work:
    """A launcher work folder: `pilot-metrics.jsonl` and `logs/<stamp>/` folders."""

    def __init__(self):
        self.root = Path(tempfile.mkdtemp())
        self.logs = self.root / "logs"
        self.logs.mkdir()
        self.metrics = self.root / "pilot-metrics.jsonl"

    def rows(self, *rows):
        self.metrics.write_text("".join(json.dumps(r) + "\n" for r in rows) + "not json\n", encoding="utf-8")

    def folder(self, stamp, **files):
        folder = self.logs / stamp
        folder.mkdir(exist_ok=True)
        for name, content in files.items():
            name = name.replace("_", "-").replace("-jsonl", ".jsonl").replace("-json", ".json")
            text = (content if isinstance(content, str) else
                    "".join(json.dumps(r) + "\n" for r in content) if isinstance(content, list) else json.dumps(content))
            (folder / name).write_text(text, encoding="utf-8")
        return folder

    def mirror(self, stamp=STAMP, facts=None, spec=None, accepted=None, stages=None):
        return M.mirror(stamp, self.metrics, self.logs, facts, spec or self.root / "no-spec", accepted, stages)


class PerModelTest(unittest.TestCase):
    """Per model version (model id and effort): sessions, pushes, verdicts, rejection reasons, the CLI's USD estimate,
    USD per accepted change and the median session minutes, from the cycle rows before this session."""

    def test_versions_are_grouped_and_counted(self):
        # mirror_version_ignores_effort mirror_median_is_the_mean mirror_rejection_reasons_of_accepted
        w = Work()
        w.rows(cycle("20261118T010000Z", minutes=10.0, cost_usd=1.0),
               cycle("20261118T020000Z", minutes=20.0, cost_usd=2.5, verdict="rejected",
                     reasons=[{"kind": "refutation_reproduced"}, {"kind": "budget"}]),
               cycle("20261118T030000Z", minutes=90.0, cost_usd=0.5, pushed=False, verdict=None, kind=None),
               cycle("20261118T040000Z", effort="high", cost_usd=3.0, reasons=[{"kind": "ignored_when_accepted"}]),
               {"kind": "intervention", "ts": "2026-11-18T00:30:00Z"},
               cycle(STAMP, cost_usd=99.0), cycle("20261119T130000Z", cost_usd=99.0))
        out = w.mirror()["per_model"]
        self.assertEqual([(m["model"], m["effort"]) for m in out["models"]], [("claude-x", "high"), ("claude-x", "medium")])
        medium = next(m for m in out["models"] if m["effort"] == "medium")
        high = next(m for m in out["models"] if m["effort"] == "high")
        self.assertEqual((medium["sessions"], medium["pushes"], medium["accepted"]), (3, 2, 1))
        self.assertEqual(medium["verdicts"], {"code:accepted": 1, "code:rejected": 1})
        self.assertEqual(medium["rejected_rows_by_reason"], {"refutation_reproduced": 1, "budget": 1})
        self.assertEqual((medium["founder_cli_usd"], medium["usd_label"], medium["founder_cli_usd_per_accepted"]),
                         (4.0, "cli_estimate", 4.0))
        self.assertEqual(medium["median_session_minutes"], 20.0)
        self.assertEqual((high["sessions"], high["rejected_rows_by_reason"], high["founder_cli_usd_per_accepted"]),
                         (1, {}, 3.0))
        self.assertEqual(out["window"], "20261118T010000Z..20261118T040000Z")  # this session and later are not there

    def test_a_push_without_a_verdict_takes_the_next_sessions_record(self):  # mirror_late_verdict_ignored
        w = Work()
        w.rows(cycle("20261118T010000Z", verdict=None, kind=None), cycle("20261118T020000Z", verdict=None, kind=None),
               cycle("20261118T030000Z", verdict=None, kind=None, pushed=False))
        w.folder("20261118T020000Z", previous_session_json={"stamp": "20261118T010000Z", "verdict": "accepted"})
        w.folder("20261118T030000Z", previous_session_json={"stamp": "20261118T020000Z", "verdict": None})
        m = w.mirror()["per_model"]["models"][0]
        self.assertEqual((m["verdicts"], m["verdicts_from_next_session"], m["pushes_without_verdict"], m["accepted"]),
                         ({}, {"accepted": 1}, 1, 1))

    def test_an_unrecorded_model_or_effort_is_said_and_never_guessed(self):
        w = Work()
        old = cycle("20261101T010000Z")
        for key in ("model", "model_served", "effort"):
            del old[key]
        w.rows(old, cycle("20261102T010000Z", effort=None))
        got = {(m["model"], m["effort"]) for m in w.mirror()["per_model"]["models"]}
        self.assertEqual(got, {("unrecorded", "unrecorded"), ("claude-x", "default")})

    def test_what_cannot_be_computed_is_null_with_its_reason(self):  # mirror_usd_per_accepted_without_reason
        w = Work()
        w.rows(cycle("20261118T010000Z", verdict="rejected", cost_usd=None, minutes=None))
        m = w.mirror()["per_model"]["models"][0]
        self.assertEqual((m["founder_cli_usd"], m["founder_cli_usd_per_accepted"], m["median_session_minutes"]),
                         (None, None, None))
        self.assertEqual(set(m["null_reasons"]),
                         {"founder_cli_usd", "founder_cli_usd_per_accepted", "median_session_minutes"})
        self.assertEqual(m["null_reasons"]["founder_cli_usd_per_accepted"], "no accepted verdict")
        self.assertEqual((m["sessions_with_usd"], m["sessions_without_usd"]), (0, 1))

    def test_a_row_counts_once_per_reason_kind_and_accepted_counts_code_and_exit(self):
        # mirror_reason_kinds_per_reason
        w = Work()
        four = [{"kind": "exit_condition", "ref": f"r{i}"} for i in range(4)]
        w.rows(cycle("20261112T105003Z", verdict="rejected", kind="exit", reasons=four),
               cycle("20261112T120000Z", verdict="accepted", kind="exit"), cycle("20261112T130000Z"),
               cycle("20261112T140000Z", model_served="claude-x[1m]"))
        out = w.mirror()["per_model"]["models"]
        plain = next(m for m in out if m["model"] == "claude-x")
        self.assertEqual((plain["rejected_rows_by_reason"], plain["accepted"]), ({"exit_condition": 1}, 2))
        self.assertIn("claude-x[1m]", [m["model"] for m in out])  # a bracketed id stays itself
        self.assertIn("not the total cost per accepted change", M.SOURCES["per_model"])
        self.assertIn("code and exit alike", M.SOURCES["per_model"])

    def test_the_versions_are_capped_newest_first(self):  # mirror_models_keep_the_oldest
        w = Work()
        w.rows(*(cycle(f"202610{10 + i:02d}T010000Z", model_served=f"m{i:02d}") for i in range(M.MODELS_MAX + 2)))
        out = w.mirror()["per_model"]
        self.assertEqual(len(out["models"]), M.MODELS_MAX)
        self.assertEqual((out["models"][0]["model"], out["left_out"]), (f"m{M.MODELS_MAX + 1:02d}", 2))


class LiveAttemptsTest(unittest.TestCase):
    """Each transfer (the referee's import rows and `control.json` `reverted_exits`) with the loop runs whose `cek`
    named it, the first red's job and recorded reason; facts only, no judgement of what was visible before."""

    def work(self):
        w = Work()
        w.folder("20261118T010000Z", loop_runs_jsonl=[
            {"kind": "read"}, run(1, "2026-11-18T00:30:00Z", None, "in_progress"), cek(1, A)])
        w.folder("20261118T020000Z", loop_runs_jsonl=[
            {"kind": "read"}, run(1, "2026-11-18T00:30:00Z", "failure"), cek(1, A),
            job(1, "yaz", "failure", summary={"job": "yaz", "ok": False, "reason": "activation_refused",
                                              "steps": ["D5", "D6"]}),
            run(2, "2026-11-18T01:30:00Z"), cek(2, B),
            run(3, "2026-11-17T23:00:00Z", "failure"),
            job(3, "cek", "failure", summary={"job": "cek", "ok": False, "reason": "head_missing:brain/state"})])
        return w

    def test_runs_are_tied_to_their_transfer_and_the_newest_read_wins(self):
        # mirror_newest_read_loses mirror_red_job_ignored mirror_transfer_not_from_cek
        w = self.work()
        facts = referee(reverted=[A], imports=[{"ts": "2026-11-18T01:00:00Z", "stage": 0, "brain_sha": B}])
        out = w.mirror(facts=facts)["live_attempts"]
        first, second = out["transfers"]
        self.assertEqual((first["brain_sha"], first["reverted"], first["import_row"], first["outcome"]),
                         (A, True, None, "red"))
        self.assertEqual(first["conclusions"], {"failure": 1})
        red = first["first_red"]["red_jobs"]
        self.assertEqual([(j["job"], j["reason"], j["steps"]) for j in red], [("yaz", "activation_refused", ["D5", "D6"])])
        self.assertEqual((second["brain_sha"], second["reverted"], second["import_row"], second["outcome"]),
                         (B, False, {"ts": "2026-11-18T01:00:00Z", "stage": 0}, "no_red_in_runs_seen"))
        self.assertEqual([r["id"] for r in out["unattributed_runs"]], [3])
        self.assertEqual(out["unattributed_red_runs"], 1)  # mirror_unattributed_reds_unsaid
        self.assertEqual(out["unattributed_runs"][0]["red_jobs"][0]["reason"], "head_missing:brain/state")
        self.assertEqual(out["null_reasons"], {})

    def test_a_transfer_without_runs_and_an_unread_tarball_are_said(self):  # mirror_unread_tarball_reads_as_none
        w = self.work()
        out = w.mirror(facts=referee(reverted=[C]))["live_attempts"]
        self.assertEqual([(t["brain_sha"], t["outcome"]) for t in out["transfers"]],
                         [(C, "no_run_seen"), (A, "red"), (B, "no_red_in_runs_seen")])
        for facts in (None, {"error": "ReadError"}):
            out = w.mirror(facts=facts)["live_attempts"]
            self.assertEqual([t["reverted"] for t in out["transfers"]], [None, None])
            self.assertIn("the referee tarball was not read this cycle", out["null_reasons"]["reverted_exits"])

    def test_the_transfers_are_capped_and_the_newest_kept(self):
        shas = [f"{i:040x}" for i in range(M.TRANSFERS_MAX + 2)]
        out = Work().mirror(facts=referee(reverted=shas))["live_attempts"]
        self.assertEqual(([t["brain_sha"] for t in out["transfers"]], out["transfers_left_out"]), (shas[2:], 2))
        self.assertEqual(out["unattributed_red_runs"], 0)

    def test_the_runs_of_a_transfer_are_capped(self):
        w = Work()
        n = M.RUNS_MAX + 2
        w.folder("20261118T010000Z", loop_runs_jsonl=[x for i in range(n) for x in
                                                      (run(i + 1, f"2026-11-18T00:{i:02d}:00Z"), cek(i + 1, A))])
        t = w.mirror(facts=referee())["live_attempts"]["transfers"][0]
        self.assertEqual((t["runs_seen"], len(t["runs"]), t["runs_left_out"]), (n, M.RUNS_MAX, 2))


class RepeatsTest(unittest.TestCase):
    """Rejection and red classes seen more than once in the window, with their count and dates."""

    def test_classes_seen_more_than_once_in_the_window(self):
        # mirror_repeats_list_singles mirror_repeats_window_ignored mirror_red_class_without_output
        w = Work()
        rejected = dict(verdict="rejected", reasons=[{"kind": "refutation_reproduced"}])
        w.rows(cycle("20261101T010000Z", **rejected), cycle("20261110T010000Z", **rejected),
               cycle("20261118T010000Z", **rejected), cycle("20261118T020000Z", verdict="frozen", kind="spec",
                                                            reasons=[{"kind": "budget"}]))
        refused = {"job": "yaz", "ok": False, "reason": "activation_refused"}
        unusable = ["unusable input: getir: fetch failed", '{"ok": false}']
        w.folder("20261118T030000Z", loop_runs_jsonl=[
            run(1, "2026-11-15T01:00:00Z", "failure"), job(1, "yaz", "failure", summary=refused),
            run(2, "2026-11-18T01:00:00Z", "failure"), job(2, "yaz", "failure", summary=refused),
            run(3, "2026-11-16T01:00:00Z", "failure"), job(3, "getir", "failure", output=unusable, why="none"),
            run(4, "2026-11-17T01:00:00Z", "failure"), job(4, "getir", "failure", output=unusable, why="none"),
            run(5, "2026-10-01T01:00:00Z", "failure"), job(5, "kos", "failure", why="none")])
        out = w.mirror()["repeats"]
        self.assertEqual(out["window"], "20261105T120000Z..20261119T120000Z")
        got = {(r["kind"], r["class"]): (r["count"], r["dates"]) for r in out["repeats"]}
        self.assertEqual(got, {("rejection", "refutation_reproduced"): (2, ["20261110", "20261118"]),
                               ("red", "yaz:activation_refused"): (2, ["20261115", "20261118"]),
                               ("red", "getir:unusable_input"): (2, ["20261116", "20261117"])})


class RepeatCountTest(unittest.TestCase):
    """The review of 2026-11-19: a repeat counts rows or runs, each once per class; the list is in class order; the
    window's edges and frozen verdicts are pinned."""

    def test_a_row_or_a_run_counts_once_per_class(self):
        # mirror_repeats_count_reasons mirror_red_class_per_job
        w = Work()
        four = [{"kind": "exit_condition", "ref": f"r{i}"} for i in range(4)]
        w.rows(cycle("20261112T105003Z", verdict="rejected", kind="exit", reasons=four))
        refused = {"job": "yaz", "ok": False, "reason": "activation_refused"}
        w.folder("20261118T030000Z", loop_runs_jsonl=[
            run(1, "2026-11-18T01:00:00Z", "failure"), job(1, "yaz", "failure", summary=refused),
            job(1, "yaz", "failure", summary=refused)])
        self.assertEqual(w.mirror()["repeats"]["repeats"], [])

    def test_frozen_counts_the_window_edges_hold_and_the_order_is_by_class(self):
        # mirror_repeats_ranked mirror_repeats_window_ignored
        w = Work()
        frozen = dict(verdict="frozen", kind="spec", reasons=[{"kind": "budget"}])
        rejected = dict(verdict="rejected", reasons=[{"kind": "zz_last"}])
        w.rows(cycle("20261105T115959Z", **rejected), cycle("20261105T120000Z", **rejected),
               cycle("20261106T000000Z", **rejected), cycle("20261107T000000Z", **rejected),
               cycle("20261108T000000Z", **frozen), cycle("20261109T000000Z", **frozen))
        out = w.mirror()["repeats"]["repeats"]
        self.assertEqual([(r["class"], r["count"], r["first"]) for r in out],
                         [("budget", 2, "20261108"), ("zz_last", 3, "20261105")])

    def test_the_repeats_are_capped(self):
        w = Work()
        w.rows(*(cycle(f"202611{10 + d}T0{h}0000Z", verdict="rejected", reasons=[{"kind": f"k{i:02d}"}])
                 for i in range(M.REPEATS_MAX + 2) for d, h in ((0, 1), (1, 2))))
        out = w.mirror()["repeats"]
        self.assertEqual((len(out["repeats"]), out["left_out"], out["repeats"][0]["class"]), (M.REPEATS_MAX, 2, "k00"))


class SizeTest(unittest.TestCase):
    """The transferred referee/ tree's size from this cycle's referee tarball, the spec's page count from the launcher's
    checkout; the brain's fan-in and a CI duration are not on disk: null with a reason."""

    TREE = {TOP + "activate.py": b"a = 1\nb = 2\n", TOP + "loop/job.py": b"x\ny\nz\n",
            TOP + "tests/test_x.py": b"class T:\n    def test_a(self):\n        pass\n    async def test_b(self):\n"
                                     b"        pass\n    def helper(self):\n        pass\n",
            TOP + "tests/mutants/a.json": json.dumps({"mutants": [{"id": 1}, {"id": 2}, {"id": 3}]}).encode(),
            TOP + "tests/mutants/broken.json": b"not json",
            TOP + "status/off_live.json": json.dumps({"ledger.founder": {}, "profile.fit": {}}).encode(),
            TOP + "bootstrap/snowball_bootstrap/cli.py": b"1\n" * 50, TOP + "vectors/x/run.py": b"1\n" * 50,
            TOP + "setup/results/r.py": b"1\n", TOP + ".github/workflows/w.py": b"1\n"}

    def test_the_referee_tree_is_counted_and_the_operators_files_are_not(self):
        # mirror_operator_tree_counted mirror_tests_counted_as_code mirror_mutants_by_file
        facts = referee(imports=[{"brain_sha": A}, {"brain_sha": B}], extra=self.TREE)
        self.assertEqual(facts["tree"], {"py_files_code": 2, "py_lines_code": 5, "py_files_tests": 1, "py_lines_tests": 7,
                                         "test_functions": 2, "mutant_files": 1, "mutants": 3,
                                         "mutant_files_unreadable": 1, "files_too_large": 0, "off_live_modules": 2})
        spec = Path(tempfile.mkdtemp())
        for rel in ("INDEX.md", "tohum/00.md", "tohum/01.md", "asama-0/00.md", "tohum/notes.txt"):
            (spec / rel).parent.mkdir(parents=True, exist_ok=True)
            (spec / rel).write_text("x", encoding="utf-8")
        out = Work().mirror(facts=facts, spec=spec)["size"]
        self.assertEqual((out["referee_tree"], out["referee_tree_transfer"]), (facts["tree"], B))
        self.assertEqual(out["spec_pages"], {"total": 4, "by_folder": {".": 1, "tohum": 2, "asama-0": 1}})
        self.assertEqual((out["fan_in_top"], out["ci_duration_s"]), (None, None))
        self.assertEqual(set(out["null_reasons"]), {"fan_in_top", "ci_duration_s"})

    def test_a_missing_tarball_or_spec_is_null_with_its_reason(self):
        out = Work().mirror(facts=None)["size"]
        self.assertEqual((out["referee_tree"], out["spec_pages"]), (None, None))
        self.assertIn("not read this cycle", out["null_reasons"]["referee_tree"])
        self.assertIn("spec_pages", out["null_reasons"])


class DelegationTest(unittest.TestCase):
    """Subagent calls per session and their models, read from the transcripts the launcher keeps."""

    @staticmethod
    def assistant(*tools):
        return {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": n, "input": i}
                                                             for n, i in tools]}}

    def test_agent_calls_and_their_models_are_counted(self):  # mirror_agent_model_dropped mirror_task_tool_missed
        w = Work()
        stamp = "20261118T010000Z"
        w.folder(stamp, **{f"session-{stamp}.jsonl": [
            {"type": "system", "subtype": "init"},
            self.assistant(("Agent", {"model": "sonnet", "subagent_type": "Explore"}), ("Bash", {"command": "ls"})),
            self.assistant(("Task", {"prompt": "p"}), ("Workflow", {})),
            {"type": "user", "message": {"content": [{"type": "tool_result", "content": "tool_use Agent"}]}},
            {"type": "result", "modelUsage": {"claude-x": {}, "claude-sonnet": {}}}]})
        w.folder("20261118T020000Z")  # a folder without a transcript
        w.folder(STAMP)  # this session's own folder is never read
        out = w.mirror()["delegation"]
        one, two = out["sessions"]
        self.assertEqual((one["agent_calls"], one["agent_models"], one["agent_types"], one["workflow_calls"],
                          one["models_used"]),
                         (2, {"sonnet": 1, "inherit": 1}, {"Explore": 1, "default": 1}, 1,
                          ["claude-sonnet", "claude-x"]))
        self.assertEqual((two["stamp"], two["agent_calls"], two["reason"]), ("20261118T020000Z", None, "no transcript"))
        self.assertEqual((out["sessions_read"], out["sessions_with_agent_calls"], out["agent_calls"]), (1, 1, 2))

    def test_the_newest_sessions_are_read(self):  # mirror_delegation_keeps_the_oldest
        w = Work()
        stamps = [f"202610{10 + i:02d}T010000Z" for i in range(M.SESSIONS_MAX + 2)]
        for stamp in stamps:
            w.folder(stamp)
        self.assertEqual([s["stamp"] for s in w.mirror()["delegation"]["sessions"]], stamps[2:])


class WaitingTest(unittest.TestCase):
    """From a session's end to the next session's start, and the launcher starts in that gap."""

    def test_the_gap_and_the_launcher_starts_in_it(self):  # mirror_gap_from_the_start mirror_restarts_uncounted
        w = Work()
        w.rows(cycle("20261119T100000Z", minutes=30.0), {"kind": "intervention", "ts": "2026-11-19T10:45:00Z"},
               cycle("20261119T110000Z", minutes=60.0), cycle("20261119T113000Z", minutes=None, pushed=False))
        out = w.mirror()["waiting"]
        got = [(s["stamp"], s["gap_to_next_start_min"], s["launcher_starts_in_gap"]) for s in out["sessions"]]
        self.assertEqual(got, [("20261119T100000Z", 30.0, 1), ("20261119T110000Z", 0.0, 0),
                               ("20261119T113000Z", None, None)])
        self.assertEqual(out["sessions"][2]["reason"], "the row carries no minutes")
        self.assertEqual((out["gap_total_min"], out["gap_with_launcher_start_min"]), (30.0, 30.0))


ADVICE = re.compile(r"\b(should|must|ought|recommend\w*|suggest\w*|consider|please|try|avoid|prefer\w*|improve\w*|"
                    r"better|worse|best|good|bad|fix(?:es|ing)?|need to|needs to|you|your|build|add|do not|don't|"
                    r"meli|malı|gerek\w*)\b", re.IGNORECASE)


def strings(value):
    if isinstance(value, dict):
        for key, item in value.items():
            yield key
            yield from strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from strings(item)
    elif isinstance(value, str):
        yield value


class WordingTest(unittest.TestCase):
    """Every text the mirror writes is a fact or a label: no advice, no imperative, no pointer to what to build."""

    def test_no_string_of_a_full_mirror_advises(self):
        w = LiveAttemptsTest().work()
        w.rows(cycle("20261118T010000Z", verdict="rejected", reasons=[{"kind": "budget"}]),
               cycle("20261118T020000Z", verdict="rejected", reasons=[{"kind": "budget"}], cost_usd=None,
                     minutes=None), {"kind": "intervention", "ts": "2026-11-18T03:00:00Z"})
        note = w.mirror(facts=referee(reverted=[C]))
        self.assertTrue(all("value" not in v for v in note.values() if isinstance(v, dict)))
        found = [s for s in strings(note) if ADVICE.search(s)]
        self.assertEqual(found, [])
        self.assertEqual(note["size"]["null_reasons"]["fan_in_top"], "not available in this launcher's inputs")
        self.assertIsNotNone(ADVICE.search("you should build a check"))

    def test_a_too_deeply_nested_line_is_skipped_alone(self):
        w = Work()
        w.metrics.write_text("[" * 100000 + "]" * 100000 + "\n" + json.dumps(cycle("20261118T010000Z")) + "\n",
                             encoding="utf-8")
        self.assertEqual(w.mirror()["per_model"]["models"][0]["sessions"], 1)


class FailOpenTest(unittest.TestCase):
    def test_a_failing_section_is_null_and_the_others_stand(self):  # mirror_one_section_fails_all
        w = Work()
        w.rows(cycle("20261118T010000Z"))
        with mock.patch.object(M, "size", side_effect=RuntimeError("secret text")):
            note = w.mirror()
        self.assertEqual(note["size"], {"value": None, "reason": "not computed: RuntimeError",
                                        "source": M.SOURCES["size"]})
        self.assertEqual(note["per_model"]["models"][0]["sessions"], 1)
        for name in ("per_model", "live_attempts", "repeats", "delegation", "waiting"):
            self.assertEqual(note[name]["source"], M.SOURCES[name])
        self.assertEqual(note["facts_only"], M.FACTS_ONLY)

    def test_the_same_files_give_the_same_bytes_and_no_clock_is_read(self):
        w = LiveAttemptsTest().work()
        w.rows(cycle("20261118T010000Z"))
        with mock.patch.object(M, "datetime", wraps=M.datetime) as clock:
            one = json.dumps(w.mirror(facts=referee()), sort_keys=True)
            two = json.dumps(w.mirror(facts=referee()), sort_keys=True)
        self.assertEqual(one, two)
        self.assertFalse(any(c[0] in ("now", "utcnow", "today") for c in clock.method_calls))
        with self.assertRaises(ValueError):
            w.mirror(stamp="now")


class LauncherTest(unittest.TestCase):
    """The launcher writes the file before the session, after this session's loop runs, from this cycle's tarball; a
    mirror that fails leaves no file and a warning naming the class; the inputs never wait on it."""

    def setUp(self):
        self.launch = load_launch()

    def pilot(self):
        return self.launch.Pilot(Path(tempfile.mkdtemp()), "o/brain", "o/referee", "target")

    def test_the_note_is_written_shown_by_the_name_rule(self):  # mirror_note_not_written mirror_names_shown
        launch = self.launch
        pilot = self.pilot()
        pilot.withheld = launch.target_names((launch.config.target({
            "id": "copy", "repo": "o/r", "kind": "copy", "base_sha": None, "identifiers": [NAME],
            "excluded_paths": [], "unit_candidates": []}, "t"),))
        pilot.metrics.write_text(json.dumps(cycle("20261118T010000Z", model_served=f"{NAME}-model")) + "\n",
                                 encoding="utf-8")
        with mock.patch.object(launch, "say") as said:
            pilot.mirror_note(STAMP)
        data = (pilot.session_logs(STAMP) / "mirror.json").read_text(encoding="utf-8")
        self.assertNotIn(NAME.lower(), data.lower())
        self.assertEqual(json.loads(data)["stamp"], STAMP)
        self.assertEqual(said.call_args_list, [])

    def test_a_failing_mirror_or_a_secret_leaves_no_file_and_names_the_class(self):
        # mirror_failure_stops_the_cycle mirror_say_carries_the_text mirror_secret_unscanned
        launch = self.launch
        for effect, word in ((RuntimeError("secret text"), "RuntimeError"), (None, "secret_shape")):
            pilot = self.pilot()
            fake = mock.Mock(side_effect=effect, return_value={"x": "send " + TOKEN})
            with self.subTest(word=word), mock.patch.object(launch.MIRROR, "mirror", fake), \
                    mock.patch.object(launch, "say") as said:
                pilot.mirror_note(STAMP)
                self.assertFalse((pilot.session_logs(STAMP) / "mirror.json").exists())
                text = " ".join(c.args[0] for c in said.call_args_list)
                self.assertIn(f"mirror.json not written for {STAMP}: {word}", text)
                self.assertNotIn("secret text", text)

    def test_the_file_is_there_when_the_session_starts(self):  # mirror_note_not_called mirror_note_after_the_session
        launch = self.launch
        seen = {}

        class Fake(quiet_pilot(launch)):
            def fetch_result(self):
                return None

            def brain_head(self):
                return "a" * 40

            def ledger_bytes(self, sha):
                return b""

            def refresh_inputs(self):
                pass

            def session(self, stamp, *a):
                note = self.session_logs(stamp) / launch.MIRROR_NOTE
                seen["note"] = json.loads(note.read_text(encoding="utf-8")) if note.exists() else None
                return {"exit": 0, "minutes": 1, "timed_out": False}

            def write(self, text):
                pass

        pilot = Fake(Path(tempfile.mkdtemp()), "o/brain", "o/referee", "target")
        pilot.idle, pilot.seed = 0, "a" * 40
        args = type("Args", (), dict(model="m", max_turns=1, budget_usd=1, session_timeout=1, referee_timeout=1))
        with mock.patch.object(launch, "say"), \
                mock.patch.object(launch, "run", side_effect=AssertionError("the cycle reached gh")):
            pilot.cycle(1, args)
        self.assertEqual(seen["note"]["mirror"], 1)
        self.assertTrue(STAMP_RE.fullmatch(seen["note"]["stamp"]))

    def test_the_inputs_keep_the_tarballs_facts_and_never_wait_on_them(self):
        # mirror_facts_failure_stops_the_inputs mirror_facts_kept_across_cycles
        launch = self.launch
        repo = {TOP + "vectors/" + rel: data for rel, data in files_under(VECTORS).items()}
        repo[TOP + "control.json"] = b'{"reverted_exits": []}'
        blob = tarball(repo)

        def gh(*args, **kw):
            return type("P", (), {"returncode": 0, "stdout": blob, "stderr": b""})()
        pilot = self.pilot()
        (pilot.work / "vec").mkdir()
        with mock.patch.object(launch, "run", gh):
            pilot.refresh_inputs()
        self.assertEqual(pilot.referee_facts["control"], b'{"reverted_exits": []}')
        with mock.patch.object(launch, "run", gh), \
                mock.patch.object(launch.MIRROR, "referee_facts", side_effect=RuntimeError("x")):
            pilot.refresh_inputs()
        self.assertEqual(pilot.referee_facts, {"error": "RuntimeError"})
        self.assertTrue((pilot.work / "vec" / "cases.json").is_file())
        with mock.patch.object(launch, "gh_read", side_effect=launch.GitHubUnavailable("down")):
            with self.assertRaises(launch.GitHubUnavailable):
                pilot.refresh_inputs()
        self.assertIsNone(pilot.referee_facts)


class SessionTimeTest(unittest.TestCase):
    """Epoch Z (E677): per session, the wall time the launcher measured, the model's API time, the time a session waited
    on its own checks (the heartbeat method, a lower bound) and the seven-day quota at its start and end."""

    @staticmethod
    def bash(tid, command, background=False):
        given = {"command": command, **({"run_in_background": True} if background else {})}
        return {"type": "assistant", "message": {"content": [{"type": "tool_use", "id": tid, "name": "Bash",
                                                             "input": given}]}}

    @staticmethod
    def beat(tid, seconds, tool="Bash"):
        return {"type": "tool_progress", "tool_name": tool, "parent_tool_use_id": tid, "elapsed_time_seconds": seconds,
                "heartbeat": True}

    @staticmethod
    def quota(overage, seven_day, five_hour=None):
        windows = {"seven_day": {"utilization": seven_day}, "seven_day_overage_included": {"utilization": overage}}
        if five_hour is not None:
            windows["five_hour"] = {"utilization": five_hour}
        return {"type": "rate_limit_event", "rate_limit_info": {"unifiedWindows": windows}}

    def test_the_four_facts_of_a_session(self):
        # mirror_wall_from_transcript mirror_api_takes_last mirror_blocked_counts_all mirror_blocked_counts_background
        # mirror_quota_wrong_window mirror_quota_end_first mirror_blocked_zero_without_result
        w = Work()
        one, two = "20261118T010000Z", "20261118T020000Z"
        w.rows(cycle(one, minutes=50.5), cycle(two, minutes=None))
        w.folder(one, **{f"session-{one}.jsonl": [
            {"type": "system", "subtype": "init"}, self.quota(0.25, 0.50, 0.10),
            self.bash("t1", "python3 local/mutate.py --only x"), self.beat("t1", 30), self.beat("t1", 59),
            self.bash("t2", "python3 tests/prepush.py"), self.beat("t2", 120),
            self.bash("t3", "sleep 300; ls"), self.beat("t3", 300),
            self.bash("t4", "python3 -m unittest discover", background=True), self.beat("t4", 900),
            self.beat("t9", 40), self.beat("t1", 70, tool="Read"),
            {"type": "result", "duration_ms": 1000, "duration_api_ms": 600_400},
            self.quota(0.31, 0.56), {"type": "result", "duration_ms": 10, "duration_api_ms": 2_000}]})
        w.folder(two)
        out = w.mirror()["session_time"]
        first, second = out["sessions"]
        self.assertEqual((first["wall_s"], first["api_s"], first["blocked_on_own_checks_s"], first["null_reasons"]),
                         (3030, 600, 179, {}))
        self.assertEqual(first["quota_start"], {"seven_day_overage_included": 0.25, "seven_day": 0.50, "five_hour": 0.10})
        self.assertEqual(first["quota_end"], {"seven_day_overage_included": 0.31, "seven_day": 0.56, "five_hour": 0.10})
        self.assertIn("so it can exceed wall_s", out["blocked_on_own_checks_is"])
        self.assertEqual((second["stamp"], second["wall_s"], second["api_s"]), (two, None, None))
        self.assertEqual(second["null_reasons"]["wall_s"], "no cycle row of this session carries minutes")
        self.assertEqual(second["null_reasons"]["blocked_on_own_checks_s"], "no transcript")
        self.assertEqual((out["own_checks_pattern"], out["quota_buckets"]),
                         (M.OWN_CHECKS.pattern, ["seven_day_overage_included", "seven_day", "five_hour"]))
        w.folder(one, **{f"session-{one}.jsonl": [self.bash("t1", "python3 local/mutate.py"), self.beat("t1", 59)]})
        cut = w.mirror()["session_time"]["sessions"][0]  # a transcript cut before its result event
        self.assertEqual((cut["blocked_on_own_checks_s"], cut["null_reasons"]["blocked_on_own_checks_s"]),
                         (None, "no result event: the transcript does not reach the session's end"))

    def test_a_transcript_without_the_events_says_so(self):
        w = Work()
        w.rows(cycle("20261118T010000Z"))
        w.folder("20261118T010000Z", **{"session-20261118T010000Z.jsonl": [{"type": "system", "subtype": "init"}]})
        fact = w.mirror()["session_time"]["sessions"][0]
        self.assertEqual((fact["wall_s"], fact["api_s"], fact["blocked_on_own_checks_s"], fact["quota_start"]),
                         (1800, None, None, {"seven_day_overage_included": None, "seven_day": None, "five_hour": None}))
        self.assertEqual(fact["null_reasons"], {
            "api_s": "no result event with duration_api_ms",
            "blocked_on_own_checks_s": "no result event: the transcript does not reach the session's end",
            **{f"quota.{b}": f"no rate_limit_event with {b}.utilization" for b in M.QUOTA_WINDOWS}})


class PathTest(unittest.TestCase):
    """Epoch Z (E677, `26h`): the first slice's micro-features not accepted yet, from the seed's P1 table and the
    accepted manifest's `done_mf` the launcher read; Stage 1's own ones apart; `organ_merges_copy` is null, said why."""

    STAGES = ROOT / "seed" / "bootstrap" / "stages"

    def path(self, accepted, facts):
        return Work().mirror(facts=facts, accepted=accepted, stages=self.STAGES)["path"]

    def test_the_p1_rows_not_in_the_accepted_done_mf(self):
        # mirror_path_counts_done mirror_organ_merges_guessed
        out = self.path({"sha": A, "done_mf": [1, 2, 3, 4, 5, 6]}, referee(imports=[{"stage": 0, "brain_sha": B}]))
        self.assertEqual((out["accepted_sha"], out["path_mfs_left"], out["path_mfs_left_count"]),
                         (A, ["P1:MF7", "P1:MF8", "P1:MF9", "P1:MF10", "P1:MF11", "P1:MF12"], 6))  # MF10-MF12: E688
        self.assertEqual(out["path_mfs_unrecorded"], ["stage1:MF1", "stage1:MF2", "stage1:MF3", "stage1:MF5",
                                                      "stage1:MF6"])
        self.assertIsNone(out["organ_merges_copy"])
        self.assertIn("tells an organ's merge from a ready-made candidate's", out["null_reasons"]["organ_merges_copy"])

    def test_a_transferred_p1_leaves_none_and_an_unread_input_is_null(self):
        # mirror_path_ignores_transfer mirror_path_unread_tarball
        done = {"stage": 1, "batch": "P1", "brain_sha": C}
        self.assertEqual(self.path({"sha": A, "done_mf": [1]}, referee(imports=[done]))["path_mfs_left"], [])
        unread = self.path({"sha": A, "done_mf": [1]}, None)
        self.assertEqual((unread["path_mfs_left"], unread["null_reasons"]["path_mfs_left"]),
                         (None, "the referee tarball was not read this cycle"))
        failed = self.path({"error": "GitHubUnavailable"}, referee())
        self.assertEqual(failed["null_reasons"]["path_mfs_left"], "the accepted manifest was not read: GitHubUnavailable")
        other = self.path({"sha": A, "done_mf": [1, 2, 18]}, referee())
        self.assertEqual(other["null_reasons"]["path_mfs_left"], "the accepted done_mf is not P1's numbering")
        self.assertEqual(Work().mirror()["path"]["null_reasons"]["path_mfs_left"], "the seed's P1 table was not given")

    def test_the_launcher_reads_the_accepted_manifest_and_passes_it(self):
        # launcher_accepted_not_passed launcher_accepted_wrong_ref
        launch = load_launch()
        pilot = launch.Pilot(Path(tempfile.mkdtemp()), "o/brain", "o/referee", "target")
        calls = []

        def gh(*args, **kw):
            calls.append(args)
            return json.dumps({"tests": [], "done_mf": [1, 2], "lockfiles": []}).encode()
        prior = {"state": {"last_accepted_sha": A}}
        with mock.patch.object(launch, "gh_read", gh), mock.patch.object(launch, "say"):
            self.assertEqual(pilot.accepted_manifest(prior), {"sha": A, "done_mf": [1, 2]})
            pilot.mirror_note(STAMP, prior)
        self.assertEqual(calls[0][:2], ("api", f"repos/o/brain/contents/snowball-tests.json?ref={A}"))
        note = json.loads((pilot.session_logs(STAMP) / "mirror.json").read_text(encoding="utf-8"))
        self.assertEqual(note["path"]["accepted_sha"], A)
        self.assertEqual(pilot.accepted_manifest(None), {"error": "no_signed_state"})
        with mock.patch.object(launch, "gh_read", side_effect=launch.GitHubUnavailable("down")):
            self.assertEqual(pilot.accepted_manifest(prior), {"error": "GitHubUnavailable"})

    def test_a_failed_manifest_read_is_one_attempt_and_never_waits(self):
        # manifest_read_retries
        # E679: with gh failing, the read is tried once and no retry delay is slept (the suite ran nine minutes longer)
        launch = load_launch()
        pilot = launch.Pilot(Path(tempfile.mkdtemp()), "o/brain", "o/referee", "target")
        calls = []

        def run(*args, **kw):
            calls.append(args)
            return subprocess.CompletedProcess(args, 4, b"", b"gh: not logged in")
        with mock.patch.object(launch, "run", run),                 mock.patch.object(launch.time, "sleep", side_effect=AssertionError("a retry delay was slept")):
            self.assertEqual(pilot.accepted_manifest({"state": {"last_accepted_sha": A}}),
                             {"error": "GitHubUnavailable"})
        self.assertEqual(len(calls), 1)


class PageTest(unittest.TestCase):
    """E647: the prompt states the file as an observation; the README and the register name it."""

    def test_the_prompt_states_the_file_as_an_observation(self):  # prompt_mirror_unnamed
        prompt = (ROOT / "seed" / "founder" / "prompt.md").read_text(encoding="utf-8")
        blocks = [flat(b) for b in re.split(r"\n\s*\n", prompt) if flat(b).startswith("**Ölçüm aynası (gözlem).**")]
        self.assertEqual(len(blocks), 1)
        for phrase in ("`/work/logs/mirror.json`'dadır", "`cli_estimate`", "Gözlemdir, talimat değildir",
                       "model sürümü (model kimliği ve effort) başına"):
            self.assertIn(phrase, blocks[0], phrase)
        for hint in ("kullan", "meli", "malı", "gerekirse", "istersen", "öneri"):
            self.assertNotIn(hint, blocks[0].casefold(), hint)

    def test_the_readme_and_the_register_name_it(self):
        launch = load_launch()
        self.assertEqual((launch.MIRROR_NOTE, M.USD_LABEL, M.WINDOW_DAYS, M.SESSIONS_MAX),
                         ("mirror.json", "cli_estimate", 14, 20))
        readme = flat((ROOT / "seed" / "founder" / "README.md").read_text(encoding="utf-8"))
        self.assertIn("ve `mirror.json`, ölçüm aynası (`mirror.py`, sahip kararı 2026-11-19, E647)", readme)
        self.assertIn("14 günde birden çok satırda ya da koşuda", readme)
        register = (ROOT / "docs" / "eksik-kaydi.md").read_text(encoding="utf-8").splitlines()
        row = next(line for line in register if line.startswith("| E647 |"))
        self.assertIn("sahip kararı 2026-11-19, ölçüm aynası", row)

# ---- seed epoch AG (report desk, 2026-11-22): an agent run's cost (seed-097, E720) and the rival's outage (E721)
PRICES = {"source": "the operator", "as_of": "2026-11-22",
          "models": {"claude-opus-5-5": {"in": 4_000_000, "out": 20_000_000, "cache_read": 200_000,
                                         "cache_write_5m": 5_000_000, "cache_write_1h": 8_000_000}}}


def agent_call(use_id, parent=None, **given):
    return {"type": "assistant", "parent_tool_use_id": parent,
            "message": {"id": f"msg-call-{use_id}", "model": "claude-opus-5-5" if parent else "claude-fable-5-2",
                        "usage": {"input_tokens": 1, "output_tokens": 1, "cache_read_input_tokens": 500,
                                  "cache_creation_input_tokens": 0},
                        "content": [{"type": "tool_use", "id": use_id, "name": "Agent", "input": given}]}}


def agent_message(parent, mid, model="claude-opus-5-5", **usage):
    full = {"input_tokens": 2, "output_tokens": 8, "cache_read_input_tokens": 1000,
            "cache_creation": {"ephemeral_5m_input_tokens": 100, "ephemeral_1h_input_tokens": 10}}
    full.update(usage)
    return {"type": "assistant", "parent_tool_use_id": parent, "message": {"id": mid, "model": model, "usage": full,
                                                                           "content": [{"type": "text", "text": "x"}]}}


def closing(**models):
    return {"type": "result", "modelUsage": {m: dict({"inputTokens": 4, "outputTokens": 5000, "cacheReadInputTokens": 2000,
                                                       "cacheCreationInputTokens": 220, "costUSD": 0.5}, **u)
                                             for m, u in models.items()}}


def ended(use_id, ms, status="completed"):
    return {"type": "system", "subtype": "task_notification", "tool_use_id": use_id, "status": status,
            "usage": {"total_tokens": 1, "tool_uses": 1, "duration_ms": ms}}


class RunCostTest(unittest.TestCase):
    """seed-097 (E720): each agent run keyed by its call's tool_use_id, with its tokens by kind, wall time and a cost
    derived from the operator's price table; what cannot be measured is null with its reason."""

    def session(self, events, prices=PRICES):
        w = Work()
        stamp = "20261118T010000Z"
        w.folder(stamp, **{f"session-{stamp}.jsonl": [{"type": "system", "subtype": "init", "model": "claude-fable-5-2"},
                                                     *events]})
        return M.mirror(STAMP, w.metrics, w.logs, None, w.root / "no-spec", None, None, prices)["delegation"]

    def test_a_runs_tokens_wall_time_and_derived_cost(self):
        # run_tokens_counted_per_event run_cost_not_derived run_out_from_another_line run_wall_dropped run_effort_dropped
        out = self.session([agent_call("toolu_a", subagent_type="brain:push-reviewer", effort="high"),
                            agent_message("toolu_a", "m1"), agent_message("toolu_a", "m1"),  # one message, two events
                            agent_message("toolu_a", "m2", cache_read_input_tokens=3000),
                            ended("toolu_a", 514818), closing(**{"claude-opus-5-5": {"costBasis": "list"},
                                                                 "claude-fable-5-2": {"costBasis": "unknown"}})])
        session = out["sessions"][0]
        self.assertEqual(session["session_model"], "claude-fable-5-2")
        run, = session["runs"]
        self.assertEqual({k: run[k] for k in ("tool_use_id", "subagent_type", "model", "effort", "parent", "status",
                                              "wall_ms", "out_from", "cost_basis", "not_measured")},
                         {"tool_use_id": "toolu_a", "subagent_type": "brain:push-reviewer", "model": "claude-opus-5-5",
                          "effort": "high", "parent": None, "status": "completed", "wall_ms": 514818,
                          "out_from": "cli_model_line", "cost_basis": "derived:price_table", "not_measured": None})
        self.assertEqual(run["tokens"], {"in": 4, "cache_read": 4000, "cache_write_5m": 200, "cache_write_1h": 20,
                                         "out": 5000})  # out: the model's line, the only run on it
        floor = (4 * 4_000_000 + 4000 * 200_000 + 200 * 5_000_000 + 20 * 8_000_000 + 500_000) // 1_000_000
        self.assertEqual(run["cost_floor_usd_micros"], floor)
        self.assertEqual(run["cost_usd_micros"], (4 * 4_000_000 + 4000 * 200_000 + 200 * 5_000_000 + 20 * 8_000_000
                                                  + 5000 * 20_000_000 + 500_000) // 1_000_000)
        self.assertEqual(session["models_cli"]["claude-opus-5-5"], {"in": 4, "out": 5000, "cache_read": 2000,
                                                                    "cache_write": 220, "cost_usd_micros": 500000,
                                                                    "cost_basis": "list"})
        self.assertEqual(out["prices"]["models"], PRICES["models"])
        self.assertIn("never the CLI's figure", out["cost_is"])
        self.assertIn("only when the session ran that agent once on that model", out["exactness"])

    def test_a_foreground_runs_last_message_is_its_calls_result(self):  # run_last_message_dropped
        """The transcript holds a foreground run's messages but its last; the Agent call's tool_use_result carries that
        message's usage (session 20261122T130912Z: with it the run's input, cache read and cache write tokens are the
        CLI's opus line exactly, and the derived cost is the CLI's 2071132 micros)."""
        last = {"type": "user", "tool_use_result": {"status": "completed", "resolvedModel": "claude-opus-5-5",
                                                     "usage": {"input_tokens": 2, "output_tokens": 3504,
                                                               "cache_read_input_tokens": 201930,
                                                               "cache_creation": {"ephemeral_5m_input_tokens": 1163,
                                                                                  "ephemeral_1h_input_tokens": 0}}},
                "message": {"content": [{"type": "tool_result", "tool_use_id": "toolu_a", "content": "{}"}]}}
        out = self.session([agent_call("toolu_a"), agent_message("toolu_a", "m1"), last,
                            closing(**{"claude-opus-5-5": {"costBasis": "list"}})])
        run = out["sessions"][0]["runs"][0]
        self.assertEqual(run["tokens"], {"in": 4, "cache_read": 202930, "cache_write_5m": 1263, "cache_write_1h": 10,
                                         "out": 5000})

    def test_two_runs_on_one_model_and_a_nested_run_leave_output_unmeasured(self):
        # run_nested_merged run_out_shared run_floor_dropped
        out = self.session([agent_call("toolu_a", subagent_type="x"), agent_message("toolu_a", "m1"),
                            agent_call("toolu_b", parent="toolu_a", subagent_type="y"), agent_message("toolu_b", "m2"),
                            closing(**{"claude-opus-5-5": {"costBasis": "list"}})])
        one, two = out["sessions"][0]["runs"]
        self.assertEqual((one["parent"], two["parent"]), (None, "toolu_a"))
        # each its own messages: the call's message is the calling run's, the nested run's message its own
        self.assertEqual((one["tokens"]["cache_read"], two["tokens"]["cache_read"]), (1500, 1000))
        for run in (one, two):
            self.assertEqual((run["tokens"]["out"], run["out_from"], run["cost_usd_micros"], run["not_measured"]),
                             (None, None, None, "output_tokens_unlogged"))
        self.assertEqual(two["cost_floor_usd_micros"], (2 * 4_000_000 + 1000 * 200_000 + 100 * 5_000_000
                                                        + 10 * 8_000_000 + 500_000) // 1_000_000)
        self.assertEqual(one["cost_floor_usd_micros"], (3 * 4_000_000 + 1500 * 200_000 + 100 * 5_000_000
                                                        + 10 * 8_000_000 + 500_000) // 1_000_000)
        self.assertEqual(out["sessions"][0]["agent_calls"], 2)

    def test_a_run_on_the_sessions_own_model_has_no_output_of_its_own(self):  # run_out_from_the_sessions_model
        out = self.session([agent_call("toolu_a"), agent_message("toolu_a", "m1", model="claude-fable-5-2"),
                            closing(**{"claude-fable-5-2": {"costBasis": "list"}})],
                           prices=dict(PRICES, models=dict(PRICES["models"], **{"claude-fable-5-2": PRICES["models"]["claude-opus-5-5"]})))
        run = out["sessions"][0]["runs"][0]
        self.assertEqual((run["tokens"]["out"], run["not_measured"]), (None, "output_tokens_unlogged"))

    def test_what_cannot_be_priced_or_read_is_null_with_its_reason(self):
        # run_unknown_basis_priced run_unpriced_model_priced run_no_usage_priced run_unsplit_writes_priced
        cases = [([agent_message("toolu_a", "m1")], {"claude-opus-5-5": {"costBasis": "unknown"}},
                  "price_unknown:claude-opus-5-5"),
                 ([agent_message("toolu_a", "m1", model="claude-sonnet-x")], {"claude-sonnet-x": {"costBasis": "list"}},
                  "price_unknown:claude-sonnet-x"),
                 ([agent_message("toolu_a", "m1")], {}, "price_unknown:claude-opus-5-5"),  # no closing line: no basis
                 ([], {"claude-opus-5-5": {"costBasis": "list"}}, "no_usage"),
                 ([agent_message("toolu_a", "m1", cache_creation=None, cache_creation_input_tokens=5)],
                  {"claude-opus-5-5": {"costBasis": "list"}}, "usage_unreadable")]
        for messages, models, why in cases:
            with self.subTest(why=why):
                events = [agent_call("toolu_a"), *messages] + ([closing(**models)] if models else [])
                run = self.session(events)["sessions"][0]["runs"][0]
                self.assertEqual((run["cost_usd_micros"], run["not_measured"]), (None, why))
        run = self.session([agent_call("toolu_a"), agent_message("toolu_a", "m1"),
                            closing(**{"claude-opus-5-5": {"costBasis": "list"}})], prices=None)["sessions"][0]["runs"][0]
        self.assertEqual(run["not_measured"], "price_unknown:claude-opus-5-5")  # no table at all
        unsplit = self.session([agent_call("toolu_a"), agent_message("toolu_a", "m1", cache_creation=None,
                                                                     cache_creation_input_tokens=0),
                                closing(**{"claude-opus-5-5": {"costBasis": "list"}})])["sessions"][0]["runs"][0]
        self.assertEqual(unsplit["tokens"]["cache_write_5m"], 0)  # nothing written needs no split
        unfinished = self.session([agent_call("toolu_a"), closing()])["sessions"][0]["runs"][0]
        self.assertEqual((unfinished["status"], unfinished["wall_ms"], unfinished["tokens"]), ("unfinished", None, None))

    def test_the_price_table_is_read_in_its_form_or_said_unread(self):  # prices_form_unchecked
        good = M.price_table(PRICES)
        self.assertEqual((good["source"], good["as_of"], good["unit"]),
                         ("the operator", "2026-11-22", "usd_micros_per_million_tokens"))
        row = PRICES["models"]["claude-opus-5-5"]
        for bad in ({"error": "FileNotFoundError"}, None, dict(PRICES, models=[]), dict(PRICES, as_of="today"),
                    dict(PRICES, models={"claude-opus-5-5": dict(row, out=1.5)}),
                    dict(PRICES, models={"claude-opus-5-5": dict(row, out=-1)}),
                    dict(PRICES, models={"claude-opus-5-5": {"in": 1}}),
                    dict(PRICES, models={"bad model!": row})):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                M.price_table(bad)
        out = self.session([], prices={"error": "ValueError"})
        self.assertIsNone(out["prices"])
        self.assertEqual(out["null_reasons"]["prices"], "seed/founder/prices.json: not read: ValueError")
        shipped = json.loads((ROOT / "seed" / "founder" / "prices.json").read_text(encoding="utf-8"))
        self.assertEqual(sorted(M.price_table(shipped)["models"]), ["claude-fable-5-2", "claude-opus-5-5"])

    def test_the_runs_of_a_session_are_capped(self):  # runs_uncapped
        events = [agent_call(f"toolu_{i}") for i in range(M.RUNS_MAX + 3)]
        session = self.session(events)["sessions"][0]
        self.assertEqual((len(session["runs"]), session["runs_left_out"], session["agent_calls"]),
                         (M.RUNS_MAX, 3, M.RUNS_MAX + 3))
        self.assertEqual(session["runs"][0]["tool_use_id"], "toolu_0")  # in the order the calls were made


class OutageCountTest(unittest.TestCase):
    """E721: a push the rival's outage left unjudged is counted under outages, never as a verdict or a rejection."""

    def test_an_outage_is_no_rejection_in_any_form(self):
        # mirror_outage_counted_rejected mirror_old_outage_row_rejected mirror_outage_takes_an_unevaluated_late_verdict
        w = Work()
        outage = [{"kind": "rival_unresolved", "ref": "api_error:http_429", "owner": "rival"}]
        w.rows(cycle("20261118T010000Z", verdict=None, unjudged={"cause": "outage", "owner": "rival"}, reasons=outage),
               cycle("20261118T020000Z", verdict="rejected", reasons=outage),  # written before E721
               cycle("20261118T030000Z", verdict="rejected", reasons=outage),
               cycle("20261118T040000Z", verdict=None, unjudged={"cause": "outage", "owner": "rival"}, reasons=outage),
               cycle("20261118T050000Z", verdict="rejected", reasons=[{"kind": "refutation_reproduced"}]))
        w.folder("20261118T030000Z", previous_session_json={"stamp": "20261118T020000Z", "verdict": "rejected"})
        w.folder("20261118T050000Z", previous_session_json={"stamp": "20261118T040000Z", "verdict": "accepted",
                                                            "evaluated": True})
        m = w.mirror()["per_model"]["models"][0]
        self.assertEqual((m["outages"], m["verdicts"], m["verdicts_from_next_session"], m["rejected_rows_by_reason"],
                          m["pushes_without_verdict"], m["accepted"]),
                         (3, {"code:rejected": 1}, {"accepted": 1}, {"refutation_reproduced": 1}, 0, 1))
        self.assertIn("outages", M.SOURCES["per_model"])
        repeats = w.mirror()["repeats"]["repeats"]
        self.assertEqual([r["class"] for r in repeats], [])  # the outage is no repeated rejection class

    def test_only_the_rivals_own_api_errors_are_an_outage(self):
        self.assertTrue(M.rival_outage([{"kind": "rival_unresolved", "ref": "api_error:http_429"}]))
        for reasons in ([], None, [{"kind": "rival_unresolved", "ref": "api_error:isolation_network"}],
                        [{"kind": "rival_unresolved", "ref": "max_turns"}],
                        [{"kind": "rival_unresolved", "ref": "api_error:http_429"}, {"kind": "infra", "ref": "kos"}]):
            with self.subTest(reasons=reasons):
                self.assertFalse(M.rival_outage(reasons))
        self.assertFalse(M.outage({"verdict": "accepted", "reasons": [{"kind": "rival_unresolved",
                                                                       "ref": "api_error:http_429"}]}))
        self.assertTrue(M.outage({"verdict": None, "unjudged": {"cause": "outage"}}))


# ---- seed epoch AK (owner's hint E742, 2026-11-23): context is a measured resource; per session, the compactions
def own(at, usage=None, parent=None):
    return {"type": "assistant", "timestamp": at, "parent_tool_use_id": parent,
            "message": {"id": f"msg-{at}", "model": "claude-x", "content": [], "usage": usage or {}}}


def compacted(pre=None, parent=None):
    event = {"type": "system", "subtype": "compact_boundary", "uuid": "u", "session_id": "s"}
    if pre is not None:
        event["compact_metadata"] = {"trigger": "auto", "pre_tokens": pre, "post_tokens": 6000}
    if parent is not None:
        event["parent_tool_use_id"] = parent
    return event


class ContextTest(unittest.TestCase):
    """E742: per session, how often its context was compacted, the minute of the first compaction and the input tokens
    before each, from the transcript's own compact_boundary events; not_measured says why a value is not there."""

    def test_two_compactions_of_the_session_and_none_of_a_subagent(self):
        # context_subagent_counted context_pre_tokens_ignored context_usage_fallback_dropped context_subagent_usage_read
        # context_minute_from_the_first_event context_first_is_last context_cache_uncounted context_section_unwired
        w = Work()
        one = "20261118T010000Z"
        w.rows(cycle(one))
        w.folder(one, **{f"session-{one}.jsonl": [
            {"type": "system", "subtype": "init"},
            own("2026-11-18T01:00:30.000Z", {"input_tokens": 10, "cache_read_input_tokens": 1000,
                                             "cache_creation_input_tokens": 200}),
            own("2026-11-18T01:01:00Z", {"input_tokens": 5, "cache_read_input_tokens": 90000}, parent="toolu_a"),
            {"type": "user", "timestamp": "2026-11-18T01:03:30.250Z", "message": {"content": []}},
            compacted(171318),
            compacted(50000, parent="toolu_a"),  # a subagent's compaction is not the session's
            own("2026-11-18T01:10:00Z", {"input_tokens": 7, "cache_read_input_tokens": 3000,
                                         "cache_creation_input_tokens": 40}),
            own("2026-11-18T01:11:00Z", {"input_tokens": 9, "cache_read_input_tokens": 80000}, parent="toolu_a"),
            own("2026-11-18T01:12:00Z", {"input_tokens": "x", "cache_read_input_tokens": 99}),
            compacted()]})
        note = w.mirror()
        out = note["context"]
        self.assertEqual(out["source"], M.SOURCES["context"])
        self.assertEqual((out["sessions_read"], out["sessions_compacted"]), (1, 1))
        fact = out["sessions"][0]
        self.assertEqual(fact, {"stamp": one, "compactions": 2, "first_compaction_min": 3.5, "each": [
            {"minute": 3.5, "input_tokens_before": 171318, "tokens_from": "pre_tokens", "not_measured": {}},
            {"minute": 12.0, "input_tokens_before": 3047, "tokens_from": "last_usage", "not_measured": {}}],
            "each_left_out": 0, "not_measured": {}})
        self.assertEqual(json.dumps(note, sort_keys=True), json.dumps(w.mirror(), sort_keys=True))

    def test_no_compaction_and_no_transcript_are_said(self):  # context_zero_unsaid context_no_transcript_zero
        w = Work()
        one, two = "20261118T010000Z", "20261118T020000Z"
        w.rows(cycle(one), cycle(two))
        w.folder(one, **{f"session-{one}.jsonl": [{"type": "system", "subtype": "init"},
                                                    own("2026-11-18T01:00:30Z", {"input_tokens": 3})]})
        w.folder(two)
        out = w.mirror()["context"]
        first, second = out["sessions"]
        self.assertEqual(first, {"stamp": one, "compactions": 0, "first_compaction_min": None, "each": [],
                                 "each_left_out": 0,
                                 "not_measured": {"first_compaction_min": "no compaction in the transcript"}})
        self.assertEqual(second, {"stamp": two, "compactions": None, "first_compaction_min": None, "each": None,
                                  "each_left_out": None, "not_measured": {
                                      "compactions": "no transcript", "first_compaction_min": "no transcript",
                                      "each": "no transcript"}})
        self.assertEqual((out["sessions_read"], out["sessions_compacted"]), (1, 0))

    def test_a_compaction_without_its_time_or_tokens_says_so(self):  # context_minute_unsaid context_tokens_unsaid
        w = Work()
        one = "20261118T010000Z"
        w.rows(cycle(one))
        w.folder(one, **{f"session-{one}.jsonl": [{"type": "system", "subtype": "init"}, compacted()]})
        fact = w.mirror()["context"]["sessions"][0]
        self.assertEqual(fact["compactions"], 1)
        self.assertEqual(fact["each"], [{"minute": None, "input_tokens_before": None, "tokens_from": None,
                                         "not_measured": {
                                             "minute": "no event before it carries a timestamp",
                                             "input_tokens_before": "no pre_tokens and no usage of an own message "
                                                                    "before it"}}])
        self.assertEqual(fact["not_measured"], {"first_compaction_min": "no event before it carries a timestamp"})

    def test_many_compactions_are_capped_and_counted(self):
        # context_uncapped context_left_out_uncounted context_count_capped
        w = Work()
        one = "20261118T010000Z"
        w.rows(cycle(one))
        events = []
        for k in range(M.COMPACTIONS_MAX + 3):
            events += [own(f"2026-11-18T02:{k:02d}:00Z", {"input_tokens": k}), compacted(160000 + k)]
        w.folder(one, **{f"session-{one}.jsonl": events})
        fact = w.mirror()["context"]["sessions"][0]
        self.assertEqual((fact["compactions"], fact["each_left_out"], len(fact["each"])), (23, 3, 20))
        self.assertEqual(fact["first_compaction_min"], 60.0)
        self.assertEqual([e["input_tokens_before"] for e in fact["each"]], [160000 + k for k in range(20)])

    def test_the_newest_sessions_are_read(self):  # context_keeps_the_oldest
        w = Work()
        stamps = [f"20261117T{h:02d}0000Z" for h in range(M.SESSIONS_MAX + 2)]
        for stamp in stamps:
            w.folder(stamp)
        out = w.mirror()["context"]
        self.assertEqual([s["stamp"] for s in out["sessions"]], stamps[2:])

    def test_a_too_large_transcript_is_said_in_each_section_that_reads_it(self):
        # context_too_large_unread session_time_too_large_unread delegation_too_large_unread
        w = Work()
        one = "20261118T010000Z"
        w.rows(cycle(one))
        w.folder(one, **{f"session-{one}.jsonl": [{"type": "system", "subtype": "init"}, compacted(5)]})
        with mock.patch.object(M, "TRANSCRIPT_MAX", 10):
            note = w.mirror()
        self.assertEqual(note["context"]["sessions"][0]["not_measured"],
                         {k: "transcript too large" for k in ("compactions", "first_compaction_min", "each")})
        self.assertEqual(note["session_time"]["sessions"][0]["null_reasons"]["api_s"], "transcript too large")
        self.assertEqual(note["delegation"]["sessions"][0]["reason"], "transcript too large")

    def test_the_minute_reads_any_events_timestamp_and_the_tokens_their_keys(self):
        # context_minute_own_only context_cache_key_required context_input_unrequired
        w = Work()
        one = "20261118T010000Z"
        w.rows(cycle(one))
        w.folder(one, **{f"session-{one}.jsonl": [own("2026-11-18T01:01:00Z", {"input_tokens": 4}),
                                                    own("2026-11-18T01:05:00Z", {"input_tokens": 9}, parent="toolu_a"),
                                                    compacted()]})
        each = w.mirror()["context"]["sessions"][0]["each"]
        self.assertEqual([(e["minute"], e["input_tokens_before"]) for e in each], [(5.0, 4)])  # SOURCES: any event
        self.assertEqual(M.context_tokens({"input_tokens": 5, "cache_read_input_tokens": 7}), 12)
        for usage in ({"cache_read_input_tokens": 7}, {"input_tokens": True}, None):
            self.assertIsNone(M.context_tokens(usage), usage)

    def test_an_event_time_keeps_its_fraction(self):  # context_fraction_dropped
        self.assertEqual(M.event_time("2026-11-18T01:03:30.25Z"),
                         datetime(2026, 11, 18, 1, 3, 30, 250000, tzinfo=timezone.utc))
        self.assertEqual(M.event_time("2026-11-18T01:03:30Z"), datetime(2026, 11, 18, 1, 3, 30, tzinfo=timezone.utc))
        for text in ("2026-13-18T01:03:30Z", "2026-11-18 01:03:30Z", 5, None, "2026-11-18T01:03:30.1234567Z"):
            self.assertIsNone(M.event_time(text), text)



if __name__ == "__main__":
    unittest.main()
