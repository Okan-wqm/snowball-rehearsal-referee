"""The live loop's runs, visible to the Founder (`29y`; the owner's decision of 2026-11-15, E596).

Before each session the launcher reads, with the operator's own `gh` login, the referee repo's newest `loop.yml` runs on
main and writes them to `/work/logs/loop-runs.jsonl`: a `read` row, then each run and its jobs with the job's own
summary line, or the class that kept it out. Nothing reaches GitHub here: `launch.run` is a fake `gh` that answers by
the API path. The summary lines are shaped like the referee's real ones (runs 43534260172, 43685908138, 43686181570).
"""

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from helpers import quiet_pilot
from test_founder_capsule import load_launch

ROOT = Path(__file__).resolve().parents[3]
REPO = "o/referee"
ACTIONS = f"repos/{REPO}/actions"
STAMP = "2026-11-15T06:32:49.9447193Z "
TOKEN = "gh" + "p_" + "A" * 36  # built at run time, never written
AWS = "AK" + "IA" + "ABCDEFGHIJKLMNOP"
NAME = "Zorbalix"

CEK = ('{"accepted": {"brain_sha": "4dc2c697afa023475c46e24b63abf7dbe28f69d8"}, "checked": true, "done": ["D1"], '
       '"job": "cek", "mfs": [1, 4], "ok": true}')  # sorted keys: `job` is not the first
KOS = '{"job": "kos", "mfs": [3, 6, 12], "ok": true, "steps": ["D3", "D7"], "targets": [{"target": "toy"}]}'
YAZ = '{"job": "yaz", "ok": false, "reason": "activation_refused", "reasons": ["base_run_missing"]}'
EXIT2 = ["unusable input: kos: policy: operating.unit_inputs_bytes missing", '{"ok": false, "reason": null}']


def getir(size=9795):
    head = '{"job": "getir", "ok": true, "targets": [{"deps": "'
    return head + "d" * (size - len(head) - 4) + '"}]}'


def log(*lines, setup=True, eol="\n"):
    """A job's log as GitHub serves it: a byte order mark, a time stamp before each line, the step's group."""
    pre = ["Current runner version: '2.338.2'", "##[group]Run python3 -m loop.job", "shell: /usr/bin/bash -e {0}",
           "##[endgroup]"] if setup else []
    return ("\ufeff" + eol.join(STAMP + line for line in [*pre, *lines]) + eol).encode("utf-8")


def failed(*step):
    return log(*step, "##[error]Process completed with exit code 2.", "Post job cleanup.",
               "Cleaning up orphan processes")


def job(jid, name, conclusion="success", status="completed"):
    return {"id": jid, "name": name, "status": status, "conclusion": conclusion, "steps": [{"name": "Run"}]}


def run_row(rid, created, conclusion="failure", attempt=1):
    return {"id": rid, "created_at": created, "event": "workflow_dispatch", "status": "completed",
            "conclusion": conclusion, "run_attempt": attempt, "name": "loop"}


class FakeGh:
    """`launch.run` for `gh api <path>`: the reply by path, a list of every argv it was asked for."""

    def __init__(self, routes):
        self.routes, self.calls = routes, []

    def __call__(self, *args, check=True, timeout=None, stdin=None):
        self.calls.append((args, timeout))
        reply = self.routes.get(args[2] if len(args) > 2 else None, (1, b"", b"gh: Not Found (HTTP 404)"))
        if isinstance(reply, BaseException):
            raise reply
        if callable(reply):
            reply = reply()
        if isinstance(reply, (dict, list)):
            reply = (0, json.dumps(reply).encode(), b"")
        elif isinstance(reply, bytes):
            reply = (0, reply, b"")
        return subprocess.CompletedProcess(args, reply[0], reply[1], reply[2])

    def paths(self):
        return [args[2] for args, _t in self.calls]


def real_routes():
    """The referee repo as it is on 2026-11-15: `loop.yml`'s record `deleted` after the reverted import, its runs
    listed oldest first here so that the order the file shows is the launcher's own."""
    runs = {"total_count": 4, "workflow_runs": [run_row(43534260172, "2026-11-14T00:27:02Z"),
                                                run_row(43686181570, "2026-11-15T06:36:02Z"),
                                                run_row(43685908138, "2026-11-15T06:32:29Z")]}
    routes = {f"{ACTIONS}/workflows/loop.yml": {"id": 417882374, "state": "deleted"},
              f"{ACTIONS}/workflows/loop.yml/runs?branch=main&per_page=3": runs}
    for rid in (43686181570, 43685908138):
        routes[f"{ACTIONS}/runs/{rid}/jobs?filter=latest&per_page=30"] = {
            "total_count": 5, "jobs": [job(rid * 10 + 1, "cek"), job(rid * 10 + 2, "getir"), job(rid * 10 + 3, "kos"),
                                       job(rid * 10 + 4, "yaz", "failure")]}
        routes[f"{ACTIONS}/jobs/{rid * 10 + 1}/logs"] = log("noise {not json", CEK)
        routes[f"{ACTIONS}/jobs/{rid * 10 + 2}/logs"] = log(getir())
        routes[f"{ACTIONS}/jobs/{rid * 10 + 3}/logs"] = log(KOS, eol="\r\n")
        routes[f"{ACTIONS}/jobs/{rid * 10 + 4}/logs"] = failed(YAZ)
    rid = 43534260172
    routes[f"{ACTIONS}/runs/{rid}/jobs?filter=latest&per_page=30"] = {
        "total_count": 3, "jobs": [job(1, "cek"), job(2, "kos", "failure"), job(3, "yaz", "skipped")]}
    routes[f"{ACTIONS}/jobs/1/logs"] = log(CEK)
    routes[f"{ACTIONS}/jobs/2/logs"] = failed(*EXIT2)
    routes[f"{ACTIONS}/jobs/3/logs"] = b'<?xml version="1.0"?><Error><Code>BlobNotFound</Code></Error>'
    return routes


class LoopRunsBase(unittest.TestCase):
    def setUp(self):
        self.launch = load_launch()
        self.work = Path(tempfile.mkdtemp())

    def pilot(self, names=()):
        pilot = self.launch.Pilot(self.work, "o/brain", REPO, "target")
        pilot.withheld = list(names)
        return pilot

    def rows(self, routes, names=(), clock=None):
        """The rows the launcher writes for one session, as read back from the file, and the fake gh."""
        gh = FakeGh(routes)
        patches = [mock.patch.object(self.launch, "run", side_effect=gh),
                   mock.patch.object(self.launch, "say"),
                   mock.patch.object(self.launch.time, "sleep", side_effect=AssertionError("a loop read waited"))]
        if clock is not None:
            patches.append(mock.patch.object(self.launch.time, "monotonic", side_effect=clock))
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.pilot(names).loop_note("20261115T080000Z")
        self.said = [c.args[0] for c in self.launch.say.call_args_list]
        self.data = (self.work / "logs" / "20261115T080000Z" / self.launch.LOOP_NOTE).read_bytes()
        return [json.loads(line) for line in self.data.decode("ascii").splitlines()], gh

    def names(self):
        launch = self.launch
        return launch.target_names((launch.config.target({
            "id": "copy", "repo": "o/r", "kind": "copy", "base_sha": None, "identifiers": [NAME],
            "excluded_paths": [], "unit_candidates": []}, "t"),))

    @staticmethod
    def jobs(rows, run_id=None):
        return {r["name"]: r for r in rows if r["kind"] == "job" and (run_id is None or r["run"] == run_id)}


class RealShapesTest(LoopRunsBase):
    def test_the_real_runs_reach_the_session_newest_first_with_each_jobs_summary(self):
        # loop_note_not_written loop_runs_not_newest_first loop_deleted_workflow_not_listed loop_attempt_dropped
        rows, gh = self.rows(real_routes())
        head = rows[0]
        self.assertEqual({k: head[k] for k in ("kind", "state", "why", "workflow_state")},
                         {"kind": "read", "state": "runs", "why": None, "workflow_state": "deleted"})
        self.assertRegex(head["read_at"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
        runs = [r for r in rows if r["kind"] == "run"]
        self.assertEqual([r["id"] for r in runs], [43686181570, 43685908138, 43534260172])
        self.assertEqual(runs[0], {"kind": "run", "id": 43686181570, "created_at": "2026-11-15T06:36:02Z",
                                   "event": "workflow_dispatch", "status": "completed", "conclusion": "failure",
                                   "attempt": 1, "jobs_total": 5})
        order = [r["kind"] for r in rows]
        self.assertEqual(order, ["read", "run", "job", "job", "job", "job", "run", "job", "job", "job", "job", "run",
                                 "job", "job", "job"])
        new = self.jobs(rows, 43686181570)
        self.assertEqual(new["cek"]["summary"], json.loads(CEK))
        self.assertEqual(new["getir"]["summary"], json.loads(getir()))
        self.assertEqual(new["kos"]["summary"], json.loads(KOS))
        self.assertEqual((new["yaz"]["conclusion"], new["yaz"]["summary"]), ("failure", json.loads(YAZ)))
        self.assertEqual((new["yaz"]["output"], new["yaz"]["output_why"]), (None, None))  # it printed its summary
        for row in new.values():
            self.assertEqual((row["status"], row["summary_why"]), ("completed", None))
        self.assertEqual(set(new["cek"]), {"kind", "run", "name", "status", "conclusion", "summary", "summary_why",
                                           "output", "output_why"})
        self.assertTrue(all(p.startswith(f"repos/{REPO}/") for p in gh.paths()))

    def test_a_failed_job_without_a_summary_shows_its_failing_steps_own_last_lines(self):
        # loop_output_for_every_job loop_output_beyond_the_step loop_log_read_for_a_skipped_job
        rows, gh = self.rows(real_routes())
        first = self.jobs(rows, 43534260172)
        self.assertEqual((first["kos"]["summary"], first["kos"]["summary_why"]), (None, "none"))
        self.assertEqual((first["kos"]["output"], first["kos"]["output_why"]), (EXIT2, None))
        self.assertEqual((first["cek"]["output"], first["cek"]["output_why"]), (None, None))
        self.assertEqual((first["yaz"]["summary"], first["yaz"]["summary_why"], first["yaz"]["output"]),
                         (None, "not_run", None))
        self.assertNotIn(f"{ACTIONS}/jobs/3/logs", gh.paths())  # a skipped job's log is never asked for

    def test_a_log_that_is_an_error_page_is_unread_never_a_job_without_a_summary(self):  # loop_xml_body_read_as_log
        routes = real_routes()
        routes[f"{ACTIONS}/runs/43534260172/jobs?filter=latest&per_page=30"]["jobs"][2]["conclusion"] = "failure"
        rows, _gh = self.rows(routes)
        yaz = self.jobs(rows, 43534260172)["yaz"]
        self.assertEqual((yaz["summary_why"], yaz["output"], yaz["output_why"]), ("unread", None, "unread"))

    def test_the_failing_step_is_the_one_the_log_marks(self):  # loop_output_unbounded loop_output_beyond_the_step
        launch = self.launch
        many = [f"line {i}" for i in range(9)]
        lines = launch.log_lines(failed(*many))
        self.assertEqual(launch.job_output(lines, []), (many[-5:], None))
        self.assertEqual(launch.job_output(launch.log_lines(failed()), []), ([], None))  # read; the step printed none
        self.assertEqual(launch.job_output(launch.log_lines(log(*EXIT2)), []), (None, "unread"))  # no failing step
        no_group = launch.log_lines(log("a", "##[error]Process completed with exit code 2.", setup=False))
        self.assertEqual(launch.job_output(no_group, []), (None, "unread"))
        long = "x" * 1000
        self.assertEqual(launch.job_output(launch.log_lines(failed(long)), [])[0], ["x" * launch.LOOP_OUTPUT_LINE_MAX])


class GateTest(LoopRunsBase):
    def test_a_404_is_no_loop_only_when_the_same_repo_answers(self):
        # loop_absent_proved_by_a_404_alone loop_other_error_is_no_loop
        rows, gh = self.rows({f"{ACTIONS}/workflows?per_page=1": {"total_count": 1, "workflows": []}})
        self.assertEqual([(r["state"], r["why"]) for r in rows], [("no_loop", None)])
        self.assertEqual(gh.paths(), [f"{ACTIONS}/workflows/loop.yml", f"{ACTIONS}/workflows?per_page=1"])
        rows, _gh = self.rows({})  # the repo itself does not answer: a private repo says 404 for "no access" too
        self.assertEqual([(r["state"], r["why"]) for r in rows], [("unavailable", "gh")])
        rows, gh = self.rows({f"{ACTIONS}/workflows/loop.yml": (1, b"", b"HTTP 502: Bad Gateway"),
                              f"{ACTIONS}/workflows?per_page=1": {"total_count": 1}})
        self.assertEqual([(r["state"], r["why"]) for r in rows], [("unavailable", "gh")])
        self.assertEqual(len(gh.calls), 1)

    def test_what_could_not_be_read_says_so_and_is_never_empty(self):
        # loop_unreadable_written_as_empty loop_job_unread_written_as_none loop_run_id_unchecked
        for routes, why in (({f"{ACTIONS}/workflows/loop.yml": subprocess.TimeoutExpired("gh", 30)}, "timeout"),
                            ({f"{ACTIONS}/workflows/loop.yml": b"<html>"}, "bad_reply"),
                            ({f"{ACTIONS}/workflows/loop.yml": {"state": "active"}}, "bad_reply"),
                            ({f"{ACTIONS}/workflows/loop.yml": {"id": True, "state": "active"}}, "bad_reply")):
            with self.subTest(why=why):
                rows, _gh = self.rows(routes)
                self.assertEqual([(r["kind"], r["state"], r["why"]) for r in rows], [("read", "unavailable", why)])
        flow = {f"{ACTIONS}/workflows/loop.yml": {"id": 1, "state": "active"}}
        listing = f"{ACTIONS}/workflows/loop.yml/runs?branch=main&per_page=3"
        for runs in ({"workflow_runs": [{"id": "43534260172"}]}, {"workflow_runs": None}, {"total_count": 0}):
            with self.subTest(runs=runs):
                rows, _gh = self.rows({**flow, listing: runs})
                self.assertEqual([(r["state"], r["why"]) for r in rows], [("unavailable", "bad_reply")])
        rows, _gh = self.rows({**flow, listing: {"total_count": 0, "workflow_runs": []}})
        self.assertEqual([(r["kind"], r["state"]) for r in rows], [("read", "runs")])  # read, and there are none
        rows, _gh = self.rows({**flow, listing: {"workflow_runs": [run_row(5, "2026-11-15T00:00:00Z")]}})
        self.assertEqual([(r["kind"], r["jobs_total"] if r["kind"] == "run" else None) for r in rows],
                         [("read", None), ("run", None)])  # the jobs could not be listed: null, no job row
        routes = {**flow, listing: {"workflow_runs": [run_row(5, "2026-11-15T00:00:00Z")]},
                  f"{ACTIONS}/runs/5/jobs?filter=latest&per_page=30": {"total_count": 2, "jobs": [
                      job(7, "kos", "failure"), job(8, "yaz", None, "in_progress")]}}
        rows, _gh = self.rows(routes)  # kos's log does not answer, yaz is still running
        jobs = self.jobs(rows)
        self.assertEqual((jobs["kos"]["summary"], jobs["kos"]["summary_why"], jobs["kos"]["output_why"]),
                         (None, "unread", "unread"))
        self.assertEqual((jobs["yaz"]["summary_why"], jobs["yaz"]["conclusion"]), ("unread", None))

    def test_a_github_word_or_time_of_another_shape_is_null(self):  # loop_field_token_unchecked
        flow = {f"{ACTIONS}/workflows/loop.yml": {"id": 1, "state": "Active state; see https://x"}}
        odd = {"id": 9, "created_at": "yesterday", "event": "push\nforged", "status": "completed",
               "conclusion": "failure", "run_attempt": "2"}
        rows, _gh = self.rows({**flow, f"{ACTIONS}/workflows/loop.yml/runs?branch=main&per_page=3":
                               {"workflow_runs": [odd]}})
        self.assertIsNone(rows[0]["workflow_state"])
        self.assertEqual({k: rows[1][k] for k in ("created_at", "event", "attempt", "conclusion")},
                         {"created_at": None, "event": None, "attempt": None, "conclusion": "failure"})


class AttributionTest(LoopRunsBase):
    def test_the_summary_is_the_last_line_whose_job_is_the_jobs_own_name(self):
        # loop_summary_by_prefix loop_summary_first_not_last loop_summary_any_job_key
        launch = self.launch
        first = '{"job": "kos", "ok": false}'
        last = '{"job": "kos", "ok": true}'
        other = '{"job": "other", "ok": true}'
        self.assertEqual(launch.job_summary(launch.log_lines(log(first, last, other)), "kos", []),
                         (json.loads(last), None))
        self.assertEqual(launch.job_summary(launch.log_lines(log(other)), "kos", []), (None, "none"))
        self.assertEqual(launch.job_summary(launch.log_lines(log(CEK)), "cek", []), (json.loads(CEK), None))
        self.assertEqual(launch.job_summary(launch.log_lines(log('{"job": "kos2", "ok": 1}')), "kos", []),
                         (None, "none"))
        self.assertEqual(launch.job_summary(launch.log_lines(log("[" * 5000)), "kos", []), (None, "none"))


class ClassesTest(LoopRunsBase):
    def summary(self, line, names=()):
        return self.launch.job_summary(self.launch.log_lines(log(line)), "kos", list(names))

    def test_each_class_keeps_out_only_that_summary(self):
        # loop_summary_size_unbounded loop_summary_depth_unbounded escaped_secret_unscanned overflow_float_passes
        launch = self.launch
        deep = lambda n: '{"job": "kos", "x": ' + "[" * (n - 1) + "1" + "]" * (n - 1) + "}"
        cases = {'{"job": "kos", "a": 1, "a": 2}': "duplicate_key",
                 '{"job": "kos", "a": NaN}': "non_finite",
                 '{"job": "kos", "a": 1e999}': "non_finite",
                 '{"job": "kos", "a": [-1E400]}': "non_finite",
                 deep(launch.LOOP_DEPTH_MAX + 1): "too_deep",
                 '{"job": "kos", "note": "' + TOKEN + '"}': "secret_shape",
                 '{"job": "kos", "note": "\\u0041' + AWS[1:] + '"}': "secret_shape",
                 '{"job": "kos", "\\u0041' + AWS[1:] + '": 1}': "secret_shape"}
        for line, why in cases.items():
            with self.subTest(why=why):
                self.assertEqual(self.summary(line), (None, why))
        self.assertEqual(self.summary(deep(launch.LOOP_DEPTH_MAX))[1], None)
        pad = '{"job": "kos", "p": "'
        exact = pad + "a" * (launch.LOOP_SUMMARY_MAX - len(pad) - 2) + '"}'
        self.assertEqual(len(exact), launch.LOOP_SUMMARY_MAX)
        self.assertEqual(self.summary(exact)[1], None)
        self.assertEqual(self.summary(exact[:-2] + 'a"}'), (None, "too_large"))
        named = '{"job": "kos", "p": "' + "a" * launch.LOOP_SUMMARY_MAX + NAME + '"}'  # small once its name is hashed
        self.assertEqual(self.summary(named, self.names()), (None, "too_large"))
        self.assertEqual(launch.LOOP_SUMMARY_MAX, 16 * 1024)

    def test_the_cap_holds_for_the_summary_as_written(self):
        # loop_summary_cap_not_after_redaction loop_names_not_given
        names = self.names()
        line = '{"job": "kos", "n": [' + ", ".join(['"' + NAME + '"'] * 700) + "]}"
        self.assertLess(len(line), self.launch.LOOP_SUMMARY_MAX)
        self.assertEqual(self.summary(line, names), (None, "too_large"))
        self.assertEqual(self.summary(line)[1], None)
        routes = real_routes()  # and through the launcher, which hands the job's summary the targets' names
        routes[f"{ACTIONS}/jobs/{43686181570 * 10 + 3}/logs"] = log(line)
        rows, _gh = self.rows(routes, names)
        self.assertEqual(self.jobs(rows, 43686181570)["kos"]["summary_why"], "too_large")

    def test_a_class_row_leaves_its_neighbours_whole_and_the_file_written(self):
        routes = real_routes()
        routes[f"{ACTIONS}/jobs/{43686181570 * 10 + 3}/logs"] = log('{"job": "kos", "note": "' + TOKEN + '"}')
        rows, _gh = self.rows(routes)
        new = self.jobs(rows, 43686181570)
        self.assertEqual((new["kos"]["summary"], new["kos"]["summary_why"]), (None, "secret_shape"))
        self.assertEqual(new["cek"]["summary"], json.loads(CEK))
        self.assertNotIn(b"ghp_", self.data)


class NamesTest(LoopRunsBase):
    def test_a_targets_name_is_hashed_string_by_string_and_the_rest_stays(self):
        # loop_summary_name_not_hashed loop_key_name_not_hashed loop_names_not_given loop_job_name_unscanned
        launch = self.launch
        names = self.names()
        routes = real_routes()
        rid = 43686181570
        routes[f"{ACTIONS}/jobs/{rid * 10 + 3}/logs"] = log(
            '{"job": "kos", "ok": true, "reasons": ["path src/zorbalix/x.py"], "zorbalix_n": 1}')
        routes[f"{ACTIONS}/runs/{rid}/jobs?filter=latest&per_page=30"]["jobs"] += [
            job(91, f"deploy {NAME}"), job(92, "send " + TOKEN)]
        rows, _gh = self.rows(routes, names)
        new = self.jobs(rows, rid)
        hashed = launch.withheld("path src/zorbalix/x.py", names)
        self.assertRegex(hashed, r"^sha256:[0-9a-f]{16}$")
        self.assertEqual(new["kos"]["summary"], {"job": "kos", "ok": True, "reasons": [hashed],
                                                 launch.withheld("zorbalix_n", names): 1})
        self.assertIn(launch.withheld(f"deploy {NAME}", names), new)
        self.assertEqual(sum(1 for r in rows if r["kind"] == "job" and r["run"] == rid and r["name"] is None), 1)
        self.assertNotIn(b"zorbalix", self.data.lower())
        self.assertNotIn(b"ghp_", self.data)

    def test_an_output_line_is_scanned_whole_and_hashed_before_its_cut(self):
        # loop_output_cut_before_redaction loop_output_secret_unscanned
        launch = self.launch
        names = self.names()
        line = "x" * (launch.LOOP_OUTPUT_LINE_MAX - 3) + NAME
        self.assertEqual(launch.job_output(launch.log_lines(failed(line)), names),
                         ([launch.withheld(line, names)], None))
        late = "x" * 400 + " " + TOKEN
        self.assertEqual(launch.job_output(launch.log_lines(failed("ok", late)), names), (None, "secret_shape"))


class BoundsTest(LoopRunsBase):
    def test_runs_and_jobs_are_bounded_and_every_call_is_a_plain_read(self):
        # loop_runs_unbounded loop_jobs_unbounded loop_runs_all_branches loop_log_over_cap_accepted
        flow = {f"{ACTIONS}/workflows/loop.yml": {"id": 1, "state": "active"}}
        runs = [run_row(100 + i, f"2026-11-1{i}T00:00:00Z") for i in range(5)]
        routes = {**flow, f"{ACTIONS}/workflows/loop.yml/runs?branch=main&per_page=3": {"workflow_runs": runs}}
        for i in range(5):
            routes[f"{ACTIONS}/runs/{100 + i}/jobs?filter=latest&per_page=30"] = {
                "total_count": 12, "jobs": [job(1000 * i + k, f"j{k}") for k in range(12)]}
            for k in range(12):
                routes[f"{ACTIONS}/jobs/{1000 * i + k}/logs"] = log(f'{{"job": "j{k}"}}')
        routes[f"{ACTIONS}/jobs/4000/logs"] = log("x" * (self.launch.LOOP_LOG_MAX + 1))
        rows, gh = self.rows(routes)
        self.assertEqual([r["id"] for r in rows if r["kind"] == "run"], [104, 103, 102])
        self.assertEqual([r["jobs_total"] for r in rows if r["kind"] == "run"], [12, 12, 12])
        self.assertEqual(len([r for r in rows if r["kind"] == "job"]), 3 * 8)
        self.assertEqual(self.jobs(rows, 104)["j0"]["summary_why"], "unread")
        for args, timeout in gh.calls:
            self.assertEqual(args[:2], ("gh", "api"))
            self.assertEqual(len(args), 3)
            self.assertLessEqual(timeout, self.launch.LOOP_CALL_S)
        self.assertEqual(len(gh.calls), 1 + 1 + 3 + 24)

    def test_one_attempt_per_call_and_the_whole_read_within_its_budget(self):
        # loop_read_retries loop_read_not_budgeted
        routes = real_routes()
        rows, gh = self.rows({**routes, f"{ACTIONS}/jobs/{43686181570 * 10 + 1}/logs": (1, b"", b"HTTP 502")})
        self.assertEqual(gh.paths().count(f"{ACTIONS}/jobs/{43686181570 * 10 + 1}/logs"), 1)
        new = self.jobs(rows, 43686181570)
        self.assertEqual((new["cek"]["summary"], new["cek"]["summary_why"]), (None, "unread"))
        self.assertEqual(new["kos"]["summary"], json.loads(KOS))  # the next call is made at once
        ticks = iter([0.0] * 3 + [self.launch.LOOP_BUDGET_S + 1.0] * 100)  # the budget, the flow, the listing
        rows, gh = self.rows(real_routes(), clock=lambda: next(ticks))
        self.assertEqual(len(gh.calls), 2)  # past the budget no call is made: the rest is unread, never empty
        self.assertEqual([(r["kind"], r.get("jobs_total")) for r in rows],
                         [("read", None), ("run", None), ("run", None), ("run", None)])

    def test_the_worst_file_is_bounded_by_construction(self):
        launch = self.launch
        worst = launch.LOOP_RUNS_MAX * launch.LOOP_JOBS_MAX * (
            launch.LOOP_SUMMARY_MAX + launch.LOOP_OUTPUT_LINES * launch.LOOP_OUTPUT_LINE_MAX * 12 + 1024)
        self.assertLess(worst, 1024 * 1024)  # a character outside the BMP is two escapes, twelve ASCII bytes
        self.assertEqual((launch.LOOP_RUNS_MAX, launch.LOOP_JOBS_MAX, launch.LOOP_CALL_S, launch.LOOP_BUDGET_S),
                         (3, 8, 30, 90))


class LivePathTest(unittest.TestCase):
    def cycle(self, loop_runs=None):
        launch = load_launch()
        seen = {}

        class Fake(quiet_pilot(launch)):
            heads = ["a" * 40, "a" * 40]

            def fetch_result(self):
                return None

            def brain_head(self):
                return self.heads.pop(0)

            def ledger_rows(self, sha):
                return []

            def refresh_inputs(self):
                pass

            def session(self, stamp, *a):
                note = self.session_logs(stamp) / launch.LOOP_NOTE
                seen["note"] = note.read_bytes() if note.exists() else None
                return {"exit": 0, "minutes": 1, "timed_out": False}

            def write(self, text):
                pass

        if loop_runs is not None:
            Fake.loop_runs = loop_runs
        pilot = Fake(Path(tempfile.mkdtemp()), "o/brain", "o/referee", "target")
        pilot.idle, pilot.seed = 0, "a" * 40
        args = type("Args", (), dict(model="m", max_turns=1, budget_usd=1, session_timeout=1, referee_timeout=1))
        with mock.patch.object(launch, "say") as said, \
                mock.patch.object(launch, "run", side_effect=AssertionError("the cycle reached gh")):
            pilot.cycle(1, args)
        return seen["note"], [c.args[0] for c in said.call_args_list]

    def test_the_file_is_there_when_the_session_starts(self):
        # loop_note_not_called loop_note_after_the_session
        note, _said = self.cycle()
        self.assertEqual(json.loads(note)["state"], "no_loop")

    def test_a_read_that_breaks_still_starts_the_session_and_says_only_the_class(self):
        # loop_note_failure_stops_the_cycle loop_say_carries_the_text
        def broken(self):
            raise RuntimeError("log text " + TOKEN)
        note, said = self.cycle(broken)
        row = json.loads(note)
        self.assertEqual((row["state"], row["why"]), ("unavailable", "launcher_error"))
        self.assertTrue(any("RuntimeError" in s for s in said))
        self.assertNotIn("ghp_", " ".join(said))
        self.assertNotIn("log text", " ".join(said))


class PolicySharedGateTest(unittest.TestCase):
    def test_the_policy_copy_refuses_an_escaped_secret_shape_too(self):  # escaped_secret_unscanned
        launch = load_launch()
        for raw in (b'{"a": "\\u0041' + AWS[1:].encode() + b'"}', b'{"\\u0041' + AWS[1:].encode() + b'": 1}'):
            with self.subTest(raw=raw):
                self.assertNotIn(AWS.encode(), raw)
                with self.assertRaises(ValueError) as caught:
                    launch.policy_copy(raw, [])
                self.assertIn("secret_shape", str(caught.exception))
                self.assertNotIn("KIA", str(caught.exception))
        self.assertEqual(launch.policy_copy(b'{"a": "\\u0041BC"}', []), b'{"a": "\\u0041BC"}')


class PageTest(LoopRunsBase):
    def setUp(self):
        super().setUp()
        self.page = (ROOT / "spec" / "tohum" / "29y-dongu-kosulari.md").read_text(encoding="utf-8")
        self.flat = " ".join(self.page.split())

    def paragraph(self, title):
        start = self.page.index(title)
        return " ".join(self.page[start:self.page.index("\n\n", start)].split())

    def test_the_page_names_every_field_and_class_the_file_writes_and_no_other(self):
        # loop_page_drops_a_class loop_page_numbers_drift
        launch = self.launch
        import re
        written = {"read": ["kind", "read_at", "state", "why", "workflow_state"],
                   "run": ["kind", "id", "created_at", "event", "status", "conclusion", "attempt", "jobs_total"],
                   "job": ["kind", "run", "name", "status", "conclusion", "summary", "summary_why", "output",
                           "output_why"]}
        for kind, keys in written.items():
            text = self.paragraph(f"**`{kind}`.**")
            for key in keys[1:]:
                self.assertIn(f"`{key}`", text, (kind, key))
        rows, _ = self.rows(real_routes())
        for row in rows:
            self.assertEqual(sorted(row), sorted(written[row["kind"]]))
        words = set(launch.LOOP_STATE + launch.LOOP_WHY + launch.LOOP_SUMMARY_WHY + launch.LOOP_OUTPUT_WHY)
        for word in words:
            self.assertIn(f"`{word}`", self.flat, word)
        classes = self.paragraph("**Dışarıda tutma.**")
        self.assertEqual({w for w in re.findall(r"`([a-z_]+)` \(", classes)},
                         set(launch.LOOP_SUMMARY_WHY) - {"none", "unread", "not_run"})
        for phrase in ("en yeni üç koşusu", "en çok sekiz `job` satırı", "16 KiB", "32 düzeyden", "30 saniyeyi",
                       "90 saniyeyi", "300 karakter", "beş satır", "`/work/logs/loop-runs.jsonl`", "`loop.yml`"):
            self.assertIn(phrase, self.flat, phrase)
        self.assertEqual((launch.LOOP_RUNS_MAX, launch.LOOP_JOBS_MAX, launch.LOOP_SUMMARY_MAX, launch.LOOP_DEPTH_MAX,
                          launch.LOOP_OUTPUT_LINES, launch.LOOP_OUTPUT_LINE_MAX, launch.LOOP_NOTE,
                          launch.LOOP_WORKFLOW),
                         (3, 8, 16 * 1024, 32, 5, 300, "loop-runs.jsonl", "loop.yml"))
        self.assertLessEqual(len(self.page.splitlines()), 80)

    def test_the_prompt_the_index_and_the_task_map_point_at_the_page(self):
        # prompt_loop_note_unnamed loop_page_not_indexed task_map_drops_29y changelog_drops_loop_runs
        prompt = (ROOT / "seed" / "founder" / "prompt.md").read_text(encoding="utf-8")
        start = prompt.index("**Döngünün koşuları (gözlem).**")
        text = " ".join(prompt[start:prompt.index("\n\n", start)].split())
        self.assertIn(f"`/work/logs/{self.launch.LOOP_NOTE}`'dadır (`spec/tohum/29y`)", text)
        index = (ROOT / "spec" / "INDEX.md").read_text(encoding="utf-8")
        self.assertIn("| `tohum/29y-dongu-kosulari.md` |", index)
        task = (ROOT / "spec" / "tohum" / "00b-gorev-haritasi.md").read_text(encoding="utf-8")
        for row in ("| Kurulum, aktarım ve etkinleştirme |", "| Hakem bileşeni yazma"):
            self.assertIn("`29y`", next(line for line in task.splitlines() if line.startswith(row)), row)
        log = (ROOT / "spec" / "tohum" / "CHANGELOG-8.md").read_text(encoding="utf-8")  # moved by the cap (E634)
        self.assertIn("`/work/logs/loop-runs.jsonl`", " ".join(log.split()))


class HostileTest(LoopRunsBase):
    def test_no_secret_shape_and_no_targets_name_in_any_field_reaches_the_file(self):  # loop_token_name_not_hashed
        """The class, not a net: every string a run, a job, a summary or a failing step can carry holds a secret's
        shape and a target's name, and neither is in the file's bytes or in a warning."""
        names = self.names()
        bad = f"{NAME} {TOKEN}"
        flow = {f"{ACTIONS}/workflows/loop.yml": {"id": 1, "state": bad}}
        runs = [{"id": 5, "created_at": bad, "event": NAME.lower(), "status": bad, "conclusion": bad,
                 "run_attempt": bad,
                 "name": bad, "display_title": bad, "head_branch": bad}]
        routes = {**flow, f"{ACTIONS}/workflows/loop.yml/runs?branch=main&per_page=3": {"workflow_runs": runs},
                  f"{ACTIONS}/runs/5/jobs?filter=latest&per_page=30": {"total_count": 4, "jobs": [
                      job(1, bad), job(2, "kos", "failure"), job(3, "cek", "failure"), job(4, NAME.lower())]},
                  f"{ACTIONS}/jobs/2/logs": failed(bad, NAME),
                  f"{ACTIONS}/jobs/3/logs": log(json.dumps({"job": "cek", bad: [bad], "n": NAME})),
                  f"{ACTIONS}/jobs/4/logs": log(json.dumps({"job": NAME.lower(), "path": f"src/{NAME}/a.py"}))}
        rows, _gh = self.rows(routes, names)
        self.assertNotIn(b"zorbalix", self.data.lower())
        self.assertNotIn(b"ghp_", self.data)
        self.assertNotIn("zorbalix", " ".join(self.said).lower())
        self.assertNotIn("ghp_", " ".join(self.said))
        self.assertEqual(len([r for r in rows if r["kind"] == "job"]), 4)


if __name__ == "__main__":
    unittest.main()
