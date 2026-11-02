"""The Founder's capsule and launcher (`seed/founder`, register E90, E91, E112): the isolation the pilot relies on
is pinned here, so a later edit that loosens it fails a test instead of passing unnoticed."""

from __future__ import annotations

import argparse
import contextlib
import dataclasses
import hashlib
import importlib.util
import io
import json
import os
import re
import subprocess
import tarfile
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from snowball_bootstrap import rival, vectors

from helpers import (commit, definition, ledger_bytes, ledger_rows, load_brain_defs, make_repo, quiet_pilot, sh,
                     tree_repo)

FOUNDER = Path(__file__).resolve().parents[2] / "founder"
VECTORS = Path(__file__).resolve().parents[1] / "vectors"


def load_launch():
    spec = importlib.util.spec_from_file_location("founder_launch", FOUNDER / "launch.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class CapsuleArgvTest(unittest.TestCase):
    def setUp(self):
        self.launch = load_launch()
        self.work = Path(tempfile.mkdtemp())
        pilot = self.launch.Pilot(self.work, "owner/brain", "owner/referee", "target")
        pilot.seed = "a" * 40
        self.argv = pilot.capsule_argv("20261029T000000Z", "claude-opus-5-5", 200, 50)
        self.joined = " ".join(self.argv)

    def mounts(self) -> dict[str, str]:
        out = {}
        for i, arg in enumerate(self.argv):
            if arg == "--mount":
                spec = dict(part.split("=", 1) if "=" in part else (part, "") for part in self.argv[i + 1].split(","))
                out[spec["dst"]] = "readonly" if "readonly" in spec else "rw"
        return out

    def test_the_capsule_is_locked_down(self):
        for flag in ("--read-only", "--rm"):
            self.assertIn(flag, self.argv)
        self.assertEqual(self.argv[self.argv.index("--cap-drop") + 1], "ALL")
        self.assertEqual(self.argv[self.argv.index("--security-opt") + 1], "no-new-privileges")
        for flag in ("--privileged", "--cap-add", "--pid", "--userns", "--ipc", "--device", "-v", "--volume",
                     "--network", "--net"):  # the default bridge only: never the host's network or namespaces
            self.assertFalse(any(a == flag or a.startswith(flag + "=") for a in self.argv), flag)
        self.assertNotIn("docker.sock", self.joined)
        self.assertEqual(self.argv[-1], self.launch.IMAGE)

    def test_secrets_referee_result_and_target_are_read_only_and_the_brain_lives_in_memory(self):
        self.assertEqual(self.mounts(), {"/run/secrets/founder.env": "readonly", "/work/referee": "readonly",
                                         "/work/target": "readonly", "/work/logs": "rw", "/vec": "readonly"})
        self.assertIn("/work/brain:rw,exec,size=2g,mode=1777", self.argv)  # a fresh clone every session, never on disk
        for i, arg in enumerate(self.argv):
            if arg == "-e":
                self.assertNotRegex(self.argv[i + 1], r"TOKEN|KEY|SECRET", "a secret passed as an environment flag")

    def test_a_session_sees_only_its_own_transcript_folder_and_gets_the_seed(self):  # E155, E154
        logs = [self.argv[i + 1] for i, a in enumerate(self.argv) if a == "--mount" and "dst=/work/logs" in self.argv[i + 1]]
        self.assertEqual(len(logs), 1)
        src = Path(re.search(r"src=([^,]+)", logs[0]).group(1))
        self.assertEqual(src, self.work / "logs" / "20261029T000000Z")
        self.assertIn("BRAIN_SEED=" + "a" * 40, self.argv)

    def test_the_vector_inputs_are_mounted_read_only_where_the_commands_read_them(self):  # E244
        vec = [self.argv[i + 1] for i, a in enumerate(self.argv)
               if a == "--mount" and "dst=/vec," in self.argv[i + 1] + ","]
        self.assertEqual(len(vec), 1)
        self.assertEqual(self.mounts()["/vec"], "readonly")  # the Founder reads the inputs, never rewrites them
        self.assertEqual(Path(re.search(r"src=([^,]+)", vec[0]).group(1)), self.work / "vec")

    def test_every_mount_stays_inside_the_one_work_folder(self):
        for i, arg in enumerate(self.argv):
            if arg == "--mount":
                src = re.search(r"src=([^,]+)", self.argv[i + 1]).group(1)
                self.assertTrue(Path(src).is_relative_to(self.work), src)


class ResultShadowTest(unittest.TestCase):  # E344: a noop on the launcher's own commit never hides the Founder's verdict
    def setUp(self):
        self.launch = load_launch()
        self.work = Path(tempfile.mkdtemp())
        self.pilot = self.launch.Pilot(self.work, "o/brain", "o/referee", "target")
        self.pilot.result_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def zipped(result: dict) -> bytes:
        import zipfile
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("result.json", json.dumps(result))
        return buf.getvalue()

    def mounted(self, newest: dict, older: dict, committers: list[tuple[str, str]], status: str = "ahead"):
        listing = {"artifacts": [
            {"id": 2, "expired": False, "created_at": "2026-11-01T02:00:00Z", "workflow_run": {"head_branch": "main"}},
            {"id": 1, "expired": False, "created_at": "2026-11-01T01:00:00Z", "workflow_run": {"head_branch": "main"}}]}
        compare = {"status": status, "commits": [{"commit": {"committer": {"name": n, "email": e}}} for n, e in committers]}
        zips = {"2": self.zipped(newest), "1": self.zipped(older)}

        def gh_json(*args):
            return listing if "artifacts?" in args[1] else compare

        def gh_read(*args, timeout=120):
            return zips[args[1].split("/")[-2]]

        with mock.patch.object(self.launch, "gh_json", side_effect=gh_json), \
                mock.patch.object(self.launch, "gh_read", side_effect=gh_read):
            got = self.pilot.fetch_result()
        on_disk = json.loads((self.pilot.result_dir / "result.json").read_text(encoding="utf-8"))
        self.assertEqual(got, on_disk)
        return got

    def test_a_noop_on_the_launchers_cost_commit_mounts_the_founders_verdict(self):
        launcher = (self.launch.LAUNCHER_NAME, self.launch.LAUNCHER_EMAIL)
        got = self.mounted({"head": "c" * 40, "kind": "none", "verdict": "noop"},
                           {"head": "f" * 40, "kind": "code", "verdict": "accepted"}, [launcher])
        self.assertEqual(got["head"], "f" * 40)

    def test_a_noop_over_any_other_commit_is_mounted_as_it_is(self):
        launcher = (self.launch.LAUNCHER_NAME, self.launch.LAUNCHER_EMAIL)
        for committers in ([launcher, ("Founder", "founder@example.invalid")],
                           [(self.launch.LAUNCHER_NAME, "someone@example.invalid")],
                           [("Founder", self.launch.LAUNCHER_EMAIL)], []):
            got = self.mounted({"head": "c" * 40, "kind": "none", "verdict": "noop"},
                               {"head": "f" * 40, "kind": "code", "verdict": "accepted"}, committers)
            self.assertEqual(got["head"], "c" * 40, committers)
        got = self.mounted({"head": "c" * 40, "kind": "none", "verdict": "noop"},
                           {"head": "f" * 40, "kind": "code", "verdict": "accepted"}, [launcher], status="diverged")
        self.assertEqual(got["head"], "c" * 40)

    def test_a_real_verdict_is_mounted_as_it_is(self):
        launcher = (self.launch.LAUNCHER_NAME, self.launch.LAUNCHER_EMAIL)
        for kind in ("code", "spec", "seed_update", "exit"):
            got = self.mounted({"head": "c" * 40, "kind": kind, "verdict": "accepted"},
                               {"head": "f" * 40, "kind": "code", "verdict": "accepted"}, [launcher])
            self.assertEqual(got["head"], "c" * 40, kind)

    def test_broken_record_lines_never_stop_the_launcher(self):
        self.pilot.metrics.write_text('{"stamp": "s1", "session_exit": 0, "minutes": 3, "pushed": true}\n\n{"stamp": "s2"',
                                      encoding="utf-8")
        self.pilot.previous_session_note("20261101T000000Z", 10800)
        note = json.loads((self.work / "logs" / "20261101T000000Z" / "previous-session.json").read_text(encoding="utf-8"))
        self.assertEqual(note["stamp"], "s1")


class PreviousSessionTest(unittest.TestCase):  # E360: how the last session ended is an observation, never its transcript
    def setUp(self):
        self.launch = load_launch()
        self.work = Path(tempfile.mkdtemp())
        self.pilot = self.launch.Pilot(self.work, "owner/brain", "owner/referee", "target")
        self.pilot.verdict_on = lambda head: None  # the look-up has its own tests below; no test here reaches GitHub

    def note(self, stamp="20261031T210000Z"):
        path = self.work / "logs" / stamp / "previous-session.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None

    def test_a_seed_epoch_between_does_not_hide_the_heads_verdict(self):  # E420: the live 20261101T045525Z case
        head, epoch = "b" * 40, "d" * 40
        row = {"stamp": "20261101T012022Z", "brain_before": "a" * 40, "brain_after": head, "pushed": True,
               "session_exit": 0, "minutes": 51.9, "ledger_new": {"decision": 4}, "verdict": None,
               "session_timeout_s": 10800}
        self.pilot.metrics.write_text(json.dumps(row) + "\n", encoding="utf-8")
        noop = {"head": epoch, "kind": "seed_update", "verdict": "noop", "state": {"last_evaluated_sha": epoch}}
        on_head = {"head": head, "kind": "code", "verdict": "accepted", "state": {"last_evaluated_sha": head}}
        self.pilot.verdict_on = lambda h: on_head if h == head else None
        self.pilot.previous_session_note("20261101T045525Z", 10800, noop)
        self.assertEqual(self.note("20261101T045525Z")["verdict"], "accepted")
        self.pilot.verdict_on = lambda h: None  # not among the recent results: unknown, never another head's
        self.pilot.previous_session_note("20261101T045525Z", 10800, noop)
        self.assertIsNone(self.note("20261101T045525Z")["verdict"])

    def test_the_look_up_finds_the_newest_result_that_evaluated_the_head(self):  # E420
        pilot = self.launch.Pilot(self.work, "owner/brain", "owner/referee", "target")
        head = "b" * 40
        results = [{"head": "d" * 40, "verdict": "noop", "state": {"last_evaluated_sha": "d" * 40}},
                   {"head": head, "verdict": "accepted", "state": {"last_evaluated_sha": None}},  # did not evaluate it
                   {"head": head, "verdict": "rejected", "state": {"last_evaluated_sha": head}},
                   {"head": head, "verdict": "accepted", "state": {"last_evaluated_sha": head}}]
        pilot.state_artifacts = lambda: [{"id": i} for i in range(len(results))]
        pilot.artifact_files = lambda art: {"result.json": json.dumps(results[art["id"]]).encode()}
        self.assertEqual(pilot.verdict_on(head)["verdict"], "rejected")
        self.assertIsNone(pilot.verdict_on("e" * 40))
        pilot.state_artifacts = lambda: [{"id": 0}] * self.launch.VERDICT_LOOKBACK + [{"id": 3}]
        self.assertIsNone(pilot.verdict_on(head))  # bounded: an old head is not searched for without end

        def down():
            raise self.launch.GitHubUnavailable("down")
        pilot.state_artifacts = down
        self.assertIsNone(pilot.verdict_on(head))

    def test_a_timed_out_session_is_named_for_the_next_one(self):
        rows = [{"stamp": "20261031T170731Z", "session_exit": 0, "minutes": 18.5, "pushed": True,
                 "ledger_new": {"decision": 3, "build": 1}, "verdict": "accepted", "session_timeout_s": 10800},
                {"stamp": "20261031T174316Z", "session_exit": -1, "minutes": 180.2, "pushed": False,
                 "ledger_new": {}, "verdict": None, "session_timeout_s": 10800}]
        self.pilot.metrics.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
        self.pilot.previous_session_note("20261031T210000Z", 10800)
        self.assertEqual(self.note(), {"stamp": "20261031T174316Z", "ended": "timeout", "exit": -1, "minutes": 180.2,
                                       "limit_minutes": 180.0, "pushed": False, "ledger_rows_added": 0, "verdict": None})

    def test_a_normal_end_and_the_limit_it_ran_under(self):
        row = {"stamp": "20261031T170731Z", "session_exit": 0, "minutes": 18.5, "pushed": True,
               "ledger_new": {"decision": 3, "build": 1}, "verdict": "accepted", "session_timeout_s": 7200}
        self.pilot.metrics.write_text(json.dumps(row) + "\n", encoding="utf-8")
        self.pilot.previous_session_note("20261031T210000Z", 10800)
        note = self.note()
        self.assertEqual((note["ended"], note["limit_minutes"], note["ledger_rows_added"], note["pushed"]),
                         ("exit", 120.0, 4, True))

    def test_the_restart_after_a_timeout_still_names_the_timeout(self):
        """A timed-out session stops the launcher, and every start appends its intervention row before cycle 1 (E313):
        the note reads the last cycle's row, never that start row (E360)."""
        row = {"stamp": "20261031T174316Z", "session_exit": -1, "minutes": 180.2, "pushed": False,
               "ledger_new": {}, "verdict": None, "session_timeout_s": 10800}
        self.pilot.metrics.write_text(json.dumps(row) + "\n", encoding="utf-8")
        args = argparse.Namespace(work=self.work, cycles=1, no_build=True)
        with mock.patch.object(self.pilot, "image_prompt", return_value="p" * 64), \
                mock.patch.object(self.pilot, "image", return_value=None), mock.patch.object(self.launch, "say"):
            self.pilot.intervention(args)
            self.pilot.intervention(args)  # two starts in a row (a preflight failure, then a start that ran)
        self.pilot.previous_session_note("20261031T210000Z", 10800)
        self.assertEqual(self.note(), {"stamp": "20261031T174316Z", "ended": "timeout", "exit": -1, "minutes": 180.2,
                                       "limit_minutes": 180.0, "pushed": False, "ledger_rows_added": 0, "verdict": None})

    def test_no_earlier_cycle_writes_nothing(self):
        self.pilot.previous_session_note("20261031T210000Z", 10800)
        self.assertIsNone(self.note())
        self.pilot.record_metrics({"kind": "intervention", "ts": "2026-10-31T21:01:35Z", "args": {}})
        self.pilot.previous_session_note("20261031T210000Z", 10800)  # a first start's own row is not a session
        self.assertIsNone(self.note())

    def test_a_verdict_caught_up_after_the_cycle_is_the_one_named(self):  # E381: the live 20261031T223452Z case
        head, other = "b" * 40, "c" * 40
        row = {"stamp": "20261031T215701Z", "brain_before": "a" * 40, "brain_after": head, "pushed": True,
               "session_exit": 0, "minutes": 37.0, "ledger_new": {"decision": 4}, "verdict": None,
               "session_timeout_s": 10800}
        self.pilot.metrics.write_text(json.dumps(row) + "\n", encoding="utf-8")

        def signed(on, evaluated=True, verdict="accepted"):
            return {"head": on, "verdict": verdict, "state": {"last_evaluated_sha": on if evaluated else None}}

        for prior, expected in ((signed(head), "accepted"), (signed(head, verdict="rejected"), "rejected"),
                                (signed(other), None),  # another head's verdict is never lent (E241)
                                (signed(head, evaluated=False), None),  # a run that did not evaluate it
                                (None, None)):
            self.pilot.previous_session_note("20261031T210000Z", 10800, prior)
            self.assertEqual(self.note()["verdict"], expected, prior)
        self.pilot.metrics.write_text(json.dumps(dict(row, brain_after="a" * 40, pushed=False)) + "\n",
                                      encoding="utf-8")
        self.pilot.previous_session_note("20261031T210000Z", 10800, signed("a" * 40))
        self.assertIsNone(self.note()["verdict"])  # no push: the verdict on its head is an earlier session's
        self.assertEqual(self.pilot.metrics.read_text(encoding="utf-8").count("\n"), 1)  # the row is never rewritten

    def test_the_cycle_hands_the_caught_up_verdict_to_the_note(self):  # E381
        launch = load_launch()
        head = "b" * 40
        notes = []

        class Fake(quiet_pilot(launch)):  # the cycle's reads after the session never reach GitHub
            dispatched = False

            def fetch_result(self):  # the newest result is an older head's until the catch-up run
                on = head if self.dispatched else "a" * 40
                return {"head": on, "verdict": "accepted", "state": {"last_evaluated_sha": on}}

            def dispatch_referee(self, timeout_s):
                self.dispatched = True
                return {"id": "1", "conclusion": "success", "url": "u"}

            def brain_head(self):
                return head

            def ledger_rows(self, sha):
                return []

            def refresh_inputs(self):
                pass

            def previous_session_note(self, stamp, timeout_s, prior=None):
                notes.append(prior)

            def session(self, *a):
                return {"exit": 0, "minutes": 1}

            def write(self, text):
                pass

        pilot = Fake(self.work, "o/brain", "o/referee", "target")
        pilot.idle, pilot.seed = 0, "s" * 40
        args = type("Args", (), dict(model="m", max_turns=1, budget_usd=1, session_timeout=1, referee_timeout=1))
        with mock.patch.object(launch, "say"):
            pilot.cycle(1, args)
        self.assertEqual([(n or {}).get("head") for n in notes], [head])

    def test_the_prompt_says_where_it_is(self):
        self.assertIn("/work/logs/previous-session.json", (FOUNDER / "prompt.md").read_text(encoding="utf-8"))


class BuildContextTest(unittest.TestCase):
    def test_a_windows_checkout_reaches_the_image_with_lf_and_nothing_else(self):  # E152
        launch = load_launch()
        seed = Path(tempfile.mkdtemp())
        for rel in launch.BUILD_FILES:
            (seed / rel).parent.mkdir(parents=True, exist_ok=True)
            (seed / rel).write_bytes(b"#!/bin/sh\r\nset -eu\r\n" if rel.endswith(".sh") else b"line\r\nline\r\n")
        (seed / "founder" / "secret-notes.txt").write_bytes(b"not for the image\n")
        launch.SEED = seed
        ctx = Path(tempfile.mkdtemp())
        launch.write_build_context(ctx)
        files = sorted(p.relative_to(ctx).as_posix() for p in ctx.rglob("*") if p.is_file())
        self.assertEqual(files, sorted(launch.BUILD_FILES))
        for rel in files:
            self.assertNotIn(b"\r", (ctx / rel).read_bytes(), rel)
        self.assertEqual((ctx / "founder/entrypoint.sh").read_bytes(), b"#!/bin/sh\nset -eu\n")


def tarball(files: dict[str, bytes]) -> bytes:
    """A repository tarball as GitHub serves it: every path under one `<owner>-<repo>-<sha>/` folder."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def files_under(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


class VectorInputsTest(unittest.TestCase):
    """E244, Founder report f97: the capsule holds the vectors' inputs at `/vec` (each case's command, stdin and
    fixtures, as the referee runs them) and never their expected values: inputs yes, answers never."""

    SEED = json.loads((VECTORS / "vectors.json").read_text(encoding="utf-8"))
    DATA = [case for group in SEED.values() if isinstance(group, dict) and group.get("runner") == vectors.DATA_RUNNER
            for case in group["cases"]]
    TOP = "o-referee-1a2b3c4/"

    def test_the_inputs_are_every_data_case_with_no_expected_value_at_any_depth(self):
        def keys(value):
            if isinstance(value, dict):
                return set(value) | {k for v in value.values() for k in keys(v)}
            return {k for v in value for k in keys(v)} if isinstance(value, list) else set()

        with tempfile.TemporaryDirectory() as tmp:
            vec = vectors.founder_inputs(VECTORS, Path(tmp) / "vec")  # the real seed: no fixture carries an answer
            given = files_under(vec)
            referee = files_under(vectors.fixtures(VECTORS, Path(tmp) / "referee"))
        cases = json.loads(given.pop("cases.json").decode("utf-8"))
        self.assertEqual(given, referee)  # the files the referee's containers read, nothing more
        self.assertNotIn("vectors.json", given)
        self.assertEqual(len(cases), len(self.DATA))
        self.assertFalse(keys(cases) & {"expect", "expect_not"})
        for got, case in zip(cases, self.DATA):
            changed = case["changed"]
            self.assertEqual(got, {"id": case["id"], "purpose": case["purpose"], "cmd": case["cmd"],
                                   "stdin": case.get("stdin", ""), "fixture": case["fixture"],
                                   "changed": {"description": changed["description"], "cmd": changed["cmd"],
                                               "stdin": changed.get("stdin", ""), "fixture": changed["fixture"]}})

    @staticmethod
    def probe_seed(root: Path, files: dict[str, str]) -> Path:
        answer = "ab" * 32  # what the command must compute from its input
        case = {"id": "probe.one", "purpose": "a made-up case", "cmd": "python -m probe.x root /vec/probe/a.txt",
                "fixture": ["probe/a.txt"], "expect": {"root": answer},
                "changed": {"description": "another row", "cmd": "python -m probe.x root /vec/probe/b.txt",
                            "fixture": ["probe/b.txt"], "expect_not": {"root": answer}}}
        (root / "probe").mkdir(parents=True)
        (root / "vectors.json").write_text(json.dumps({"probe": {"owner": "asama-0", "runner": "data",
                                                                 "cases": [case]}}), encoding="utf-8")
        for rel, text in {"probe/a.txt": "row 1\n", "probe/b.txt": "row 2\n", **files}.items():
            (root / rel).write_text(text.replace("ANSWER", answer), encoding="utf-8")
        return root

    def test_a_fixture_that_carries_a_computed_answer_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            echo = self.probe_seed(Path(tmp, "echo"), {"probe/a.txt": "row 1 ANSWER\n"})  # its own input: an echo
            self.assertTrue((vectors.founder_inputs(echo, Path(tmp, "vec")) / "cases.json").is_file())
            lookup = self.probe_seed(Path(tmp, "lookup"), {"probe/answers.json": '{"probe.one": "ANSWER"}'})
            with self.assertRaisesRegex(ValueError, r"probe\.one: probe/answers\.json"):
                vectors.founder_inputs(lookup, Path(tmp, "vec2"))
            self.assertFalse(Path(tmp, "vec2").exists())  # refused before anything reaches the capsule's folder

    def test_the_launcher_builds_them_with_the_referees_own_function(self):  # one source: no copy of the rule
        self.assertIs(load_launch().founder_inputs, vectors.founder_inputs)

    def test_only_the_referee_repos_vectors_are_unpacked(self):
        launch = load_launch()
        blob = tarball({self.TOP + "bootstrap/snowball_bootstrap/decide.py": b"the referee's code",
                        self.TOP + "bootstrap/vectors/old.json": b"{}", self.TOP + "setup/summary.json": b"{}",
                        self.TOP + "vectors/vectors.json": b"{}", self.TOP + "vectors/g/a.txt": b"input"})
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(launch.referee_vectors(blob, Path(tmp)), Path(tmp, self.TOP, "vectors"))
            self.assertEqual(sorted(files_under(Path(tmp))), [self.TOP + "vectors/g/a.txt",
                                                              self.TOP + "vectors/vectors.json"])
            with self.assertRaises(tarfile.FilterError):  # filter="data": nothing lands outside the folder
                launch.referee_vectors(tarball({self.TOP + "vectors/../../../out.txt": b"x"}), Path(tmp, "x"))
            self.assertFalse(Path(tmp, "out.txt").exists())

    def test_the_inputs_are_rebuilt_from_the_referee_repos_main(self):
        launch = load_launch()
        repo = {self.TOP + "vectors/" + rel: data for rel, data in files_under(VECTORS).items()}
        repo[self.TOP + "bootstrap/snowball_bootstrap/decide.py"] = b"the referee's code"
        calls = []

        def gh(*args, **kw):
            calls.append(args)
            return subprocess.CompletedProcess(args, 0, tarball(repo), b"")

        work = Path(tempfile.mkdtemp())
        (work / "vec").mkdir()
        (work / "vec" / "stale.json").write_text("{}")  # an earlier session's copy
        with mock.patch.object(launch, "run", gh):
            launch.Pilot(work, "o/brain", "o/referee", "target").refresh_inputs()
        self.assertEqual(calls, [("gh", "api", "repos/o/referee/tarball/main")])
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(files_under(work / "vec"), files_under(vectors.founder_inputs(VECTORS, Path(tmp))))

    def run_cycle(self, gh):
        launch = load_launch()
        head, calls, report = "a" * 40, [], []

        class Fake(quiet_pilot(launch)):
            def fetch_result(self):
                return {"head": head, "verdict": "accepted", "state": {"last_evaluated_sha": head}}

            def brain_head(self):
                return head

            def ledger_rows(self, sha):
                return []

            def refresh_inputs(self):
                calls.append("refresh")
                super().refresh_inputs()

            def session(self, *a):
                calls.append("session")
                return {"exit": 0, "minutes": 1}

            def write(self, text):
                report.append(text)

        pilot = Fake(Path(tempfile.mkdtemp()), "o/brain", "o/referee", "target")
        pilot.idle, pilot.seed = 0, "s" * 40
        args = type("Args", (), dict(model="m", max_turns=1, budget_usd=1, session_timeout=1, referee_timeout=1))
        with mock.patch.object(launch, "say"), mock.patch.object(launch, "run", gh), \
                mock.patch.object(launch.time, "sleep"):
            try:
                go_on = pilot.cycle(1, args)
            except launch.GitHubUnavailable:
                go_on = "outage"  # run_cycles waits it out (E245)
        return calls, go_on, "".join(report), pilot.work / "vec"

    def test_the_inputs_are_rebuilt_before_each_session_and_a_failed_fetch_stops_the_cycle(self):
        seed = tarball({self.TOP + "vectors/vectors.json": b'{"schema": "x"}'})
        calls, go_on, _, vec = self.run_cycle(lambda *a, **kw: subprocess.CompletedProcess(a, 0, seed, b""))
        self.assertEqual((calls, go_on), (["refresh", "session"], True))
        self.assertEqual(json.loads((vec / "cases.json").read_text(encoding="utf-8")), [])
        calls, go_on, report, vec = self.run_cycle(lambda *a, **kw: subprocess.CompletedProcess(a, 1, b"", b"HTTP 502"))
        self.assertEqual((calls, go_on), (["refresh"], "outage"))  # no session on stale inputs; the outage is waited out
        self.assertIn("HTTP 502", report)
        broken = lambda *a, **kw: subprocess.CompletedProcess(a, 0, b"not a tarball", b"")  # noqa: E731
        calls, go_on, report, vec = self.run_cycle(broken)
        self.assertEqual((calls, go_on), (["refresh"], False))  # a broken tarball is a defect: stop


class RefereeRetryTest(unittest.TestCase):  # E166: the loop never waits on the Founder for the rival's own failure
    def run_cycle(self, evaluated_on):
        launch = load_launch()
        before, after = "a" * 40, "b" * 40
        report = []

        class Fake(quiet_pilot(launch)):
            dispatches = 0
            heads = [before, after]

            def fetch_result(self):
                if not self.dispatches:
                    return None
                done = self.dispatches >= evaluated_on
                return {"head": after, "verdict": "accepted" if done else "rejected",
                        "warnings": [] if done else [f"rival_side_retry:{self.dispatches}"],
                        "state": {"last_evaluated_sha": after if done else None}}

            def dispatch_referee(self, timeout_s):
                self.dispatches += 1
                return {"id": str(self.dispatches), "conclusion": "success", "url": "u"}

            def brain_head(self):
                return self.heads.pop(0)

            def ledger_rows(self, sha):
                return []

            def refresh_inputs(self):  # VectorInputsTest's subject
                pass

            def session(self, *a):
                return {"exit": 0, "minutes": 1}

            def write(self, text):
                report.append(text)

        pilot = Fake(Path(tempfile.mkdtemp()), "o/brain", "o/referee", "target")
        pilot.idle = 0
        pilot.seed = before  # a fresh pilot: nothing to judge before the first session
        args = type("Args", (), dict(model="m", max_turns=1, budget_usd=1, session_timeout=1, referee_timeout=1))
        with mock.patch.object(launch, "say"):
            pilot.cycle(1, args)
        self.metrics = [json.loads(line) for line in pilot.metrics.read_text(encoding="utf-8").splitlines()]
        return pilot.dispatches, "".join(report), launch.MAX_REFEREE_RETRIES

    def test_every_cycle_leaves_one_measurable_line(self):  # what docs/pilot-gunlugu.md counts
        self.run_cycle(evaluated_on=2)
        self.assertEqual(len(self.metrics), 1)
        m = self.metrics[0]
        self.assertEqual((m["pushed"], m["verdict"], m["referee_retries"], m["brain_after"]), (True, "accepted", 1, "b" * 40))
        for key in ("reasons", "warnings", "rival_attempts", "reproduced", "old_refutations_still_reproducing",
                    "ledger_new", "reports_new", "minutes", "cost_usd"):
            self.assertIn(key, m)

    def catch_up(self, prior_head):
        launch = load_launch()
        head, calls = "b" * 40, []

        class Fake(quiet_pilot(launch)):
            dispatches = 0

            def fetch_result(self):
                judged = head if self.dispatches else prior_head
                return {"head": judged, "verdict": "rejected", "state": {"last_evaluated_sha": judged},
                        "warnings": [], "reasons": []}

            def dispatch_referee(self, timeout_s):
                self.dispatches += 1
                calls.append("referee")
                return {"id": "1", "conclusion": "success", "url": "u"}

            def brain_head(self):
                return head  # the session pushes nothing

            def ledger_rows(self, sha):
                return []

            def refresh_inputs(self):  # VectorInputsTest's subject
                pass

            def session(self, *a):
                calls.append("session")
                return {"exit": 0, "minutes": 1}

            def write(self, text):
                pass

        pilot = Fake(Path(tempfile.mkdtemp()), "o/brain", "o/referee", "target")
        pilot.idle, pilot.seed = 0, "s" * 40
        args = type("Args", (), dict(model="m", max_turns=1, budget_usd=1, session_timeout=1, referee_timeout=1))
        with mock.patch.object(launch, "say"):
            pilot.cycle(1, args)
        return calls

    def test_an_unfinished_run_never_lends_an_older_heads_verdict(self):  # E241
        launch = load_launch()
        before, after = "a" * 40, "b" * 40
        report = []

        class Fake(quiet_pilot(launch)):
            heads = [before, after]

            def fetch_result(self):  # the newest signed result is still the previous head's
                return {"head": before, "verdict": "accepted", "reasons": [], "warnings": [],
                        "state": {"last_evaluated_sha": before}}

            def dispatch_referee(self, timeout_s):  # STOP arrived while waiting: the run is still going
                return {"id": "1", "conclusion": "still_running", "url": ""}

            def brain_head(self):
                return self.heads.pop(0)

            def ledger_rows(self, sha):
                return []

            def refresh_inputs(self):  # VectorInputsTest's subject
                pass

            def session(self, *a):
                return {"exit": 0, "minutes": 1}

            def write(self, text):
                report.append(text)

        pilot = Fake(Path(tempfile.mkdtemp()), "o/brain", "o/referee", "target")
        pilot.idle, pilot.seed = 0, before
        args = type("Args", (), dict(model="m", max_turns=1, budget_usd=1, session_timeout=1, referee_timeout=1))
        with mock.patch.object(launch, "say"):
            pilot.cycle(1, args)
        row = json.loads(pilot.metrics.read_text(encoding="utf-8").splitlines()[-1])
        self.assertEqual((row["brain_after"], row["verdict"], row["reasons"]), (after, None, []))
        self.assertNotIn("Hakemin kararı", "".join(report))
        self.assertIn("still_running", "".join(report))

    def test_a_github_read_is_retried_and_a_lasting_failure_is_an_outage(self):  # E245
        launch = load_launch()
        ok = mock.Mock(returncode=0, stdout=b'{"sha": "x"}', stderr=b"")
        down = mock.Mock(returncode=1, stdout=b"", stderr=b"error connecting to api.github.com")
        with mock.patch.object(launch, "run", side_effect=[down, down, ok]) as run, \
                mock.patch.object(launch.time, "sleep") as sleep:
            self.assertEqual(launch.gh_json("api", "repos/o/b/commits/main"), {"sha": "x"})
        self.assertEqual(run.call_count, 3)
        self.assertEqual(sleep.call_count, 2)
        with mock.patch.object(launch, "run", return_value=down) as run, mock.patch.object(launch.time, "sleep"):
            with self.assertRaises(launch.GitHubUnavailable):
                launch.gh_read("run", "view", "1")
        self.assertEqual(run.call_count, len(launch.GH_RETRY_DELAYS_S) + 1)

    def test_an_outage_is_waited_out_and_the_unjudged_push_judged_next(self):  # E245
        launch = load_launch()
        calls, waits = [], []

        class Fake:
            def stopped(self):
                return False

            def cycle(self, n, args):
                calls.append(n)
                if n == 1:
                    raise launch.GitHubUnavailable("gh api: error connecting to api.github.com")
                return False

            def wait(self, seconds):
                waits.append(seconds)

        args = type("Args", (), dict(cycles=5))
        with mock.patch.object(launch, "say"):
            launch.run_cycles(Fake(), args)
        self.assertEqual((calls, waits), ([1, 2], [launch.GH_OUTAGE_WAIT_S]))

        class Unreadable(launch.Pilot):
            def dispatch_referee(self, timeout_s):
                return {"id": "1", "conclusion": "success", "url": "u"}

            def fetch_result(self):
                raise launch.GitHubUnavailable("gh api: timed out")

        pilot = Unreadable(Path(tempfile.mkdtemp()), "o/brain", "o/referee", "target")
        with mock.patch.object(launch, "say"):
            self.assertEqual(pilot.judge(1, "b" * 40, 1)[1], None)

    def test_no_session_works_blind_on_an_unjudged_push(self):  # E168, E248: the live f07f215 -> d0dc433 case
        launch = load_launch()
        calls = []

        class Fake(quiet_pilot(launch)):
            def fetch_result(self):  # GitHub cannot be read: the newest result stays an older head's
                return {"head": "a" * 40, "verdict": "accepted", "state": {"last_evaluated_sha": "a" * 40}}

            def dispatch_referee(self, timeout_s):
                calls.append("referee")
                return {"id": "1", "conclusion": "github_unavailable", "url": ""}

            def brain_head(self):
                return "b" * 40

            def ledger_rows(self, sha):
                return []

            def refresh_inputs(self):
                calls.append("refresh")

            def session(self, *a):
                calls.append("session")
                return {"exit": 0, "minutes": 1}

            def write(self, text):
                pass

        pilot = Fake(Path(tempfile.mkdtemp()), "o/brain", "o/referee", "target")
        pilot.idle, pilot.seed = 0, "s" * 40
        args = type("Args", (), dict(model="m", max_turns=1, budget_usd=1, session_timeout=1, referee_timeout=1))
        with mock.patch.object(launch, "say"), self.assertRaises(launch.NoVerdict):
            pilot.cycle(1, args)
        self.assertEqual(calls, ["referee"])

    def test_a_dispatch_that_cannot_reach_github_is_an_outage(self):  # E248
        launch = load_launch()
        down = mock.Mock(returncode=1, stdout=b"", stderr=b"error connecting to api.github.com")
        pilot = launch.Pilot(Path(tempfile.mkdtemp()), "o/brain", "o/referee", "target")
        with mock.patch.object(launch, "run", return_value=down), mock.patch.object(launch.time, "sleep"):
            with self.assertRaisesRegex(launch.GitHubUnavailable, "workflow run"):
                pilot.dispatch_referee(1)
        self.assertTrue(issubclass(launch.NoVerdict, launch.Outage) and issubclass(launch.GitHubUnavailable, launch.Outage))

    def test_the_dispatched_run_is_mains_never_a_branch_trial_of_the_same_minute(self):  # E461
        launch = load_launch()
        pilot = launch.Pilot(Path(tempfile.mkdtemp()), "o/brain", "o/referee", "target")
        ok = mock.Mock(returncode=0, stdout=b"", stderr=b"")
        later = (datetime.now(timezone.utc) + timedelta(seconds=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
        latest = (datetime.now(timezone.utc) + timedelta(seconds=40)).strftime("%Y-%m-%dT%H:%M:%SZ")
        listed = [{"databaseId": 7, "createdAt": later, "headBranch": "ops/trial"},
                  {"databaseId": 8, "createdAt": latest, "headBranch": "main"}]
        asked = []

        def gh(*args):
            asked.append(args)
            if args[:2] == ("run", "list"):
                return listed
            return {"status": "completed", "conclusion": "success", "url": "u"}

        with mock.patch.object(launch, "run", return_value=ok), mock.patch.object(launch, "gh_json", side_effect=gh), \
                mock.patch.object(launch.time, "sleep"):
            got = pilot.dispatch_referee(60)
        self.assertEqual(got["id"], "8")  # the earlier run was a branch's, not this dispatch's
        listing = next(a for a in asked if a[:2] == ("run", "list"))
        self.assertIn("--branch", listing)
        self.assertEqual(listing[listing.index("--branch") + 1], "main")

    def test_the_usage_limit_reset_is_read_from_the_cli(self):  # E243
        wait = load_launch().usage_limit_wait
        at = datetime(2026, 10, 30, 2, 1, 20, tzinfo=timezone.utc)
        hit = {"api_error": "usage_limit_reached", "api_error_status": 429}
        self.assertEqual(wait(dict(hit, final="You've hit your session limit · resets 3:50am (UTC)"), at),
                         (3600 + 48 * 60 + 40) + 120)
        self.assertEqual(wait(dict(hit, final="resets 1pm (UTC)"), at), 6 * 3600)  # capped
        self.assertEqual(wait(dict(hit, final="resets 1:00am (UTC)"), at), 6 * 3600)  # tomorrow, capped
        self.assertEqual(wait(dict(hit, final="limit reached"), at), 30 * 60)  # no reset named: the fallback
        self.assertIsNone(wait({"api_error": None, "api_error_status": None, "final": "pushed MF1"}, at))

    def test_a_session_stopped_by_the_usage_limit_is_an_outage_not_idle(self):  # E243
        launch = load_launch()
        head, waits = "a" * 40, []

        class Fake(quiet_pilot(launch)):
            def fetch_result(self):
                return {"head": head, "verdict": "accepted", "state": {"last_evaluated_sha": head}}

            def brain_head(self):
                return head  # nothing pushed: the session could not work

            def ledger_rows(self, sha):
                return []

            def refresh_inputs(self):  # VectorInputsTest's subject
                pass

            def session(self, *a):
                return {"exit": 0, "minutes": 0.1, "api_error": "usage_limit_reached", "api_error_status": 429,
                        "final": "You've hit your session limit · resets 3:50am (UTC)"}

            def write(self, text):
                pass

            def wait(self, seconds):
                waits.append(seconds)

        pilot = Fake(Path(tempfile.mkdtemp()), "o/brain", "o/referee", "target")
        pilot.idle, pilot.seed = 0, "s" * 40
        args = type("Args", (), dict(model="m", max_turns=1, budget_usd=1, session_timeout=1, referee_timeout=1))
        with mock.patch.object(launch, "say"):
            self.assertTrue(pilot.cycle(1, args))
            self.assertTrue(pilot.cycle(2, args))  # two limited sessions in a row do not stop the pilot
        self.assertEqual(pilot.idle, 0)
        self.assertEqual(len(waits), 2)
        self.assertTrue(all(w > 0 for w in waits))
        rows = [json.loads(line) for line in pilot.metrics.read_text(encoding="utf-8").splitlines()]
        self.assertEqual([r["api_error"] for r in rows], ["usage_limit_reached"] * 2)

    def test_a_push_the_referee_never_judged_is_judged_before_the_next_session(self):  # E168
        self.assertEqual(self.catch_up(prior_head="a" * 40), ["referee", "session"])
        self.assertEqual(self.catch_up(prior_head="b" * 40), ["session"])  # already judged: straight to work

    def test_a_reasons_owner_is_the_referees_own_rule(self):
        owner = load_launch().reason_owner
        self.assertEqual(owner({"kind": "refutation_reproduced", "ref": "repro:x"}), "founder")
        self.assertEqual(owner({"kind": "rival_unresolved", "ref": "secret_in_prompt:generic_assignment"}), "founder")
        self.assertEqual(owner({"kind": "rival_unresolved", "ref": "secret_in_verdict:generic_assignment_bare"}), "rival")
        self.assertEqual(owner({"kind": "rival_missing", "ref": ""}), "rival")
        self.assertEqual(owner({"kind": "infra", "ref": "kos"}), "referee")
        self.assertEqual(owner({"kind": "budget", "ref": ""}), "referee")

    def test_an_unevaluated_commit_goes_back_to_the_referee_before_the_next_session(self):
        dispatches, report, _ = self.run_cycle(evaluated_on=2)
        self.assertEqual(dispatches, 2)
        self.assertIn("1 kez yeniden incelendi", report)
        self.assertIn("**accepted**", report)

    def test_an_evaluated_commit_is_not_sent_again_and_retries_are_capped(self):
        self.assertEqual(self.run_cycle(evaluated_on=1)[0], 1)
        dispatches, report, cap = self.run_cycle(evaluated_on=99)
        self.assertEqual(dispatches, 1 + cap)
        self.assertIn(f"{cap} kez yeniden incelendi", report)


class CycleRecordTest(unittest.TestCase):
    """E313 and the debate's N4: every cycle's line names what its outcome is attributed to, every launcher start is a
    row of its own, and the open brain reports with their age reach the report (N1: a report with no reader)."""

    def cycle(self, verdict_rival=None, sess=None):
        launch = load_launch()
        before, after = "a" * 40, "b" * 40
        report = []

        class Fake(quiet_pilot(launch)):
            heads = [before, after]
            dispatches = 0

            def fetch_result(self):
                if not self.dispatches:
                    return None
                return {"head": after, "verdict": "accepted", "warnings": [], "rival": verdict_rival,
                        "state": {"last_evaluated_sha": after, "last_accepted_sha": after}}

            def dispatch_referee(self, timeout_s):
                self.dispatches += 1
                return {"id": "1", "conclusion": "success", "url": "u"}

            def brain_head(self):
                return self.heads.pop(0)

            def ledger_rows(self, sha):
                return []

            def refresh_inputs(self):
                pass

            def session(self, *a):
                return sess or {"exit": 0, "minutes": 1, "cli_version": "2.1.293", "model_served": "claude-opus-5-5",
                                "timed_out": False}

            def write(self, text):
                report.append(text)

        pilot = Fake(Path(tempfile.mkdtemp()), "o/brain", "o/referee", "target")
        pilot.idle, pilot.seed = 0, before
        pilot.prompt_sha256, pilot.image_id = "p" * 64, "sha256:" + "i" * 64
        args = type("Args", (), dict(model="claude-opus-5-5", max_turns=1, budget_usd=1, session_timeout=1,
                                     referee_timeout=1))
        with mock.patch.object(launch, "say"):
            pilot.cycle(1, args)
        return pilot, json.loads(pilot.metrics.read_text(encoding="utf-8").splitlines()[-1]), "".join(report)

    def test_every_attribution_field_is_on_the_cycles_line(self):
        rival_block = {"prompt_sha256": "r" * 64, "model_served": "claude-sonnet-5-5", "effort": "medium",
                       "cli_version": "2.1.290", "attempts": [], "cost_usd_micros": 320527}
        pilot, m, _ = self.cycle(verdict_rival=rival_block)
        self.assertEqual({k: m[k] for k in ("prompt_sha256", "image_id", "model", "cli_version", "model_served",
                                            "seed_commit", "spec_tohum_tree", "target_sha", "timed_out")},
                         {"prompt_sha256": "p" * 64, "image_id": "sha256:" + "i" * 64, "model": "claude-opus-5-5",
                          "cli_version": "2.1.293", "model_served": "claude-opus-5-5", "seed_commit": "a" * 40,
                          "spec_tohum_tree": "t" * 40, "target_sha": "c" * 40, "timed_out": False})
        self.assertEqual(m["rival_config"], {"prompt_sha256": "r" * 64, "model_served": "claude-sonnet-5-5",
                                             "effort": "medium", "cli_version": "2.1.290"})
        self.assertEqual((m["cost_row"], m["reports_open"]), ("stub", 0))
        self.assertEqual(pilot.cost_calls, [(pilot.cost_calls[0][0], "b" * 40, "b" * 40)])  # after the referee's verdict

    def test_no_rival_block_is_no_rival_configuration_and_a_timeout_is_named(self):
        _, m, _ = self.cycle(sess={"exit": -1, "minutes": 180.2, "timed_out": True})
        self.assertEqual((m["rival_config"], m["timed_out"], m["cli_version"]), (None, True, None))

    def test_a_launcher_start_writes_one_intervention_row(self):
        launch = load_launch()
        pilot = launch.Pilot(Path(tempfile.mkdtemp()), "o/brain", "o/referee", "target")
        pilot.seed = "s" * 40
        args = argparse.Namespace(cycles=3, model="claude-opus-5-5", no_build=True)
        with mock.patch.object(launch.Pilot, "image", return_value="sha256:" + "i" * 64), \
                mock.patch.object(launch.Pilot, "image_prompt", return_value="q" * 64), \
                mock.patch.object(launch, "say") as said:
            pilot.intervention(args)
        self.assertIn("the sessions run the image's", said.call_args[0][0])  # the difference is said
        rows = [json.loads(line) for line in pilot.metrics.read_text(encoding="utf-8").splitlines()]
        # --no-build: the sessions run the image's prompt, so that is the one attributed; the checkout's is beside it.
        self.assertEqual(rows, [{"kind": "intervention", "ts": rows[0]["ts"], "image_id": "sha256:" + "i" * 64,
                                 "prompt_sha256": "q" * 64, "checkout_prompt_sha256": launch.prompt_sha256(),
                                 "seed_commit": "s" * 40,
                                 "args": {"cycles": "3", "model": "claude-opus-5-5", "no_build": "True"}}])
        self.assertEqual(pilot.prompt_sha256, "q" * 64)  # what every cycle row of this start names
        built = (FOUNDER / "prompt.md").read_bytes().replace(b"\r\n", b"\n")  # the bytes a build now would copy
        self.assertEqual(launch.prompt_sha256(), hashlib.sha256(built).hexdigest())
        self.assertIn("pilot.intervention(args)", (FOUNDER / "launch.py").read_text(encoding="utf-8"))

    def test_the_build_labels_the_image_with_its_prompt_and_a_start_reads_the_label(self):  # E313
        launch = load_launch()
        pilot = launch.Pilot(Path(tempfile.mkdtemp()), "o/brain", "o/referee", "target")
        calls = []

        def fake_run(*argv, **kw):
            calls.append(argv)
            return subprocess.CompletedProcess(argv, 0, b"sha256:x\n", b"")
        with mock.patch.object(launch, "run", side_effect=fake_run), mock.patch.object(launch, "say"):
            pilot.build()
        built = calls[0]
        label = built[built.index("--label") + 1]
        self.assertEqual(label, launch.PROMPT_LABEL + "=" + launch.prompt_sha256())  # the context's LF bytes
        for stdout, rc, expected in ((json.dumps({launch.PROMPT_LABEL: "a" * 64, "other": "x"}).encode(), 0, "a" * 64),
                                     (b"null\n", 0, None),  # an image built before the label: unknown
                                     (json.dumps({launch.PROMPT_LABEL: "not a hash"}).encode(), 0, None),
                                     (b"", 1, None), (b"{broken", 0, None)):
            with mock.patch.object(launch, "run", return_value=subprocess.CompletedProcess([], rc, stdout, b"")):
                self.assertEqual(pilot.image_prompt(), expected, stdout)

    def test_the_transcripts_init_event_gives_the_cli_and_the_served_model(self):
        launch = load_launch()
        path = Path(tempfile.mkdtemp()) / "s.jsonl"
        path.write_text("not json\n" + json.dumps({"type": "system", "subtype": "init", "model": "claude-opus-5-5",
                                                   "claude_code_version": "2.1.293"}) + "\n", encoding="utf-8")
        self.assertEqual(launch.Pilot.transcript_init(path), {"cli_version": "2.1.293", "model_served": "claude-opus-5-5"})
        self.assertEqual(launch.Pilot.transcript_init(path.with_name("none.jsonl")),
                         {"cli_version": None, "model_served": None})

    def test_the_open_reports_and_their_age_reach_the_report(self):
        launch = load_launch()
        seen = {}
        reports = [{"file": "seed-040.json", "id": "seed-040", "state": "open"},
                   {"file": "spec-004.json", "id": "spec-004", "state": "confirmed"}]
        self.assertEqual(launch.report_ages(reports, seen, "2026-10-31T20:00:00Z"), [("seed-040", 0)])
        reports.append({"file": "seed-041.json", "id": "seed-041", "state": "open"})
        self.assertEqual(launch.report_ages(reports, seen, "2026-11-01T01:30:00Z"), [("seed-040", 5), ("seed-041", 0)])
        self.assertEqual(seen["seed-040"], "2026-10-31T20:00:00Z")  # the first sighting is kept
        pilot = launch.Pilot(Path(tempfile.mkdtemp()), "o/brain", "o/referee", "target")
        with mock.patch.object(launch.Pilot, "open_reports", return_value=reports[:1]), \
                mock.patch.object(launch.Pilot, "spec_tohum_tree", return_value="t" * 40), \
                mock.patch.object(launch.Pilot, "target_head", return_value="c" * 40):
            seen_now = pilot.observe("b" * 40)
        self.assertEqual(seen_now, {"spec_tohum_tree": "t" * 40, "target_sha": "c" * 40, "reports_open": [("seed-040", 0)]})
        self.assertIn("seed-040", json.loads((pilot.work / launch.REPORTS_SEEN).read_text(encoding="utf-8")))
        _, _, text = self.cycle()
        self.assertIn("- Açık raporlar (0, beyin `bbbbbbb`", text)
        self.assertIn("- Maliyet satırı (`kind: cost`): stub", text)

    def test_the_reads_are_get_only(self):
        source = (FOUNDER / "launch.py").read_text(encoding="utf-8")
        for name in ("spec_tohum_tree", "open_reports"):
            body = source.split(f"def {name}(", 1)[1].split("\n    def ", 1)[0]
            self.assertNotIn("--method", body)
            self.assertNotIn("-X", body)


class CostRowTest(unittest.TestCase):
    """The seed's launcher contract (`tohum/24a` 4, the debate's N3): after each session the launcher writes the CLI's
    cost as a `kind: cost` founder row, chained by `26`'s rule, as its own identity, and only as a commit the referee
    reads as memory alone. Before delivery it was tried on a mirror (docs/eksik-kaydi.md, E344)."""

    FACT = {"stamp": "20261031T174316Z", "head": "9" * 40, "exit": -1, "minutes": 180.2, "turns": None,
            "cost_usd": None, "subtype": None}

    def test_the_row_is_bare_facts_chained_to_the_last_row_and_passes_the_referees_check(self):
        from snowball_bootstrap import canon, ledgercheck
        launch = load_launch()
        ledger = ledger_bytes(ledger_rows(3))
        line = launch.cost_line(ledger, self.FACT, "2026-10-31T21:00:00Z")
        row = json.loads(line)
        self.assertEqual(row["prev_hash"], ledger_rows(3)[-1]["row_hash"])
        self.assertEqual(row["row_hash"], canon.row_hash(row))
        self.assertEqual({k: row[k] for k in ("row_id", "part", "kind", "derivation", "trust", "snapshot_id")},
                         {"row_id": "f4", "part": "founder", "kind": "cost", "derivation": "tool", "trust": "observed",
                          "snapshot_id": "9" * 40})
        self.assertEqual(row["payload"], {
            "summary": "session 20261031T174316Z: exit -1, 180.2 min, turns unknown, cost_usd_micros unknown, "
                       "CLI result none",
            "refs": ["logs/20261031T174316Z/session-20261031T174316Z.jsonl"]})
        self.assertEqual(ledgercheck.check(ledger + line, ledger, whole=False), [])
        paid = launch.cost_summary(dict(self.FACT, exit=0, minutes=14.5, turns=88, cost_usd=2.3456789, subtype="success"))
        self.assertEqual(paid, "session 20261031T174316Z: exit 0, 14.5 min, turns 88, cost_usd_micros 2345679, "
                               "CLI result success")
        first = json.loads(launch.cost_line(b"", self.FACT, "2026-10-31T21:00:00Z"))
        self.assertEqual((first["row_id"], first["prev_hash"]), ("f1", "0" * 64))

    def test_a_ledger_that_cannot_take_an_appended_row_gets_none(self):
        launch = load_launch()
        ledger = ledger_bytes(ledger_rows(2))
        for broken in (ledger[:-1], ledger + b'{"kind": "x"}\n', ledger + b"not json\n"):
            with self.assertRaises(ValueError):
                launch.cost_line(broken, self.FACT, "2026-10-31T21:00:00Z")

    def mirror(self, extra=None):
        tmp = Path(tempfile.mkdtemp())
        work = tmp / "work"
        make_repo(work, {"referee/a.py": "x = 1\n"})
        accepted = commit(work, {"founder-ledger.jsonl": ledger_bytes(ledger_rows(2))}, "accepted")  # bytes as given
        if extra:
            commit(work, extra, "the Founder's next push")
        bare = tmp / "brain.git"
        subprocess.run(["git", "clone", "--quiet", "--bare", str(work), str(bare)], check=True, capture_output=True)
        return bare, accepted

    def test_on_an_accepted_head_the_row_is_pushed_as_the_launcher(self):
        from snowball_bootstrap import gitio, ledgercheck
        launch = load_launch()
        bare, accepted = self.mirror()
        head = launch.push_cost_rows(str(bare), [self.FACT, dict(self.FACT, stamp="20261031T210135Z")], accepted,
                                     "2026-10-31T22:00:00Z", credential=False)
        self.assertRegex(head, r"^[0-9a-f]{40}$")
        self.assertEqual(gitio.git(bare, "rev-parse", "main").decode().strip(), head)
        self.assertEqual(gitio.git(bare, "log", "-1", "--format=%an <%ae>|%cn", head).decode().strip(),
                         f"{launch.LAUNCHER_NAME} <{launch.LAUNCHER_EMAIL}>|{launch.LAUNCHER_NAME}")
        self.assertEqual(gitio.git(bare, "diff", "--name-only", accepted, head).decode().split(), ["founder-ledger.jsonl"])
        old = gitio.git(bare, "show", f"{accepted}:founder-ledger.jsonl")
        new = gitio.git(bare, "show", f"{head}:founder-ledger.jsonl")
        self.assertEqual(ledgercheck.check(new, old, whole=True), [])
        self.assertEqual([json.loads(x)["kind"] for x in new.splitlines()], ["decision", "decision", "cost", "cost"])

    def test_a_head_with_work_the_referee_has_not_accepted_gets_no_commit(self):
        from snowball_bootstrap import gitio
        launch = load_launch()
        bare, accepted = self.mirror(extra={"referee/a.py": "x = 2\n"})  # rejected or unjudged: judged again otherwise
        before = gitio.git(bare, "rev-parse", "main").decode().strip()
        outcome = launch.push_cost_rows(str(bare), [self.FACT], accepted, "2026-10-31T22:00:00Z", credential=False)
        self.assertTrue(outcome.startswith("deferred: 1 path(s) changed since the last accepted"), outcome)
        self.assertEqual(gitio.git(bare, "rev-parse", "main").decode().strip(), before)
        self.assertTrue(launch.push_cost_rows(str(bare), [self.FACT], None, "t", credential=False).startswith("deferred"))
        bare2, accepted2 = self.mirror(extra={"reports/r.json": "{}\n"})  # memory above the accepted head is fine
        self.assertRegex(launch.push_cost_rows(str(bare2), [self.FACT], accepted2, "2026-10-31T22:00:00Z",
                                               credential=False), r"^[0-9a-f]{40}$")

    def test_a_seed_delivery_above_the_accepted_head_is_the_operators_not_work(self):
        """As the referee reads it (`cli._pull_classify`, E88): while the head's seed is the last epoch commit's, the
        seed paths since the last accepted commit are the delivery; any other seed is work, and waits."""
        from snowball_bootstrap import gitio
        launch = load_launch()
        bare, accepted = self.mirror(extra={"spec/tohum/00-cekirdek.md": "# core, epoch 2\n"})
        epoch = gitio.git(bare, "rev-parse", "main").decode().strip()
        self.assertRegex(launch.push_cost_rows(str(bare), [self.FACT], accepted, "2026-10-31T22:00:00Z", epoch,
                                               credential=False), r"^[0-9a-f]{40}$")
        bare2, accepted2 = self.mirror(extra={"spec/tohum/00-cekirdek.md": "# core, epoch 2\n"})
        for named in (None, accepted2):  # no epoch named, or one whose seed is not the head's
            self.assertTrue(launch.push_cost_rows(str(bare2), [self.FACT], accepted2, "t", named,
                                                  credential=False).startswith("deferred"), named)

    def test_a_deferred_row_waits_in_the_work_folder_and_goes_out_first_next_time(self):
        launch = load_launch()
        pilot = launch.Pilot(Path(tempfile.mkdtemp()), "o/brain", "o/referee", "target")
        calls = []

        def fake_push(remote, facts, last_accepted, ts, epoch=None, credential=True):
            calls.append([f["stamp"] for f in facts])
            return "deferred: 1 path(s)" if len(calls) == 1 else "f" * 40
        with mock.patch.object(launch, "push_cost_rows", side_effect=fake_push):
            self.assertIn("1 satır bekliyor", pilot.record_cost("S1", {"exit": 0}, "b" * 40, "a" * 40))
            self.assertTrue((pilot.work / launch.COST_PENDING).is_file())
            self.assertIn("2 satır yazıldı", pilot.record_cost("S2", {"exit": 0}, "b" * 40, "b" * 40))
        self.assertEqual(calls, [["S1"], ["S1", "S2"]])
        self.assertFalse((pilot.work / launch.COST_PENDING).exists())

    def test_a_session_already_written_is_not_written_again_and_every_git_call_has_a_limit(self):
        """A push that timed out after it reached GitHub leaves its facts pending; the next attempt finds their rows
        and writes only the new ones. A stalled clone or push ends in GitError, which defers the rows (E344)."""
        from snowball_bootstrap import gitio
        launch = load_launch()
        bare, accepted = self.mirror()
        first = launch.push_cost_rows(str(bare), [self.FACT], accepted, "2026-10-31T22:00:00Z", credential=False)
        self.assertEqual(launch.push_cost_rows(str(bare), [self.FACT], first, "t", credential=False), first)  # no commit
        later = dict(self.FACT, stamp="20261101T010000Z")
        limits = []
        real = gitio.git

        def bounded(repo, *args, **kw):
            rest = list(args)
            while rest[0] == "-c":  # `-c name=value` pairs before the command
                rest = rest[2:]
            limits.append((rest[0], kw.get("timeout")))
            return real(repo, *args, **kw)
        with mock.patch.object(launch.gitio, "git", side_effect=bounded):
            second = launch.push_cost_rows(str(bare), [self.FACT, later], first, "2026-11-01T02:00:00Z",
                                           credential=False)
        self.assertEqual([c for c, _ in limits], ["clone", "rev-parse", "add", "commit", "push", "rev-parse"])
        self.assertTrue(all(t for _, t in limits), limits)
        ledger = gitio.git(bare, "show", f"{second}:founder-ledger.jsonl")
        self.assertEqual(sorted(launch.cost_stamps(ledger)), [self.FACT["stamp"], later["stamp"]])
        self.assertEqual(sum(1 for x in ledger.splitlines() if json.loads(x)["kind"] == "cost"), 2)
        with mock.patch.object(gitio.subprocess, "run", side_effect=subprocess.TimeoutExpired(["git"], 1)):
            with self.assertRaisesRegex(gitio.GitError, "timed out"):
                gitio.git(bare, "fetch", timeout=1)
            with self.assertRaisesRegex(gitio.GitError, "timed out"):
                gitio.same_under(bare, first, second, ("seed",), timeout=1)
        pilot = launch.Pilot(Path(tempfile.mkdtemp()), "o/brain", "o/referee", "target")
        with mock.patch.object(launch.gitio, "git", side_effect=gitio.GitError("git push timed out after 300 s")):
            self.assertIn("1 satır bekliyor (deferred: GitError: git push timed out", pilot.record_cost(
                "S1", {"exit": 0}, "b" * 40, "a" * 40))

    def test_the_launchers_cost_commit_is_not_judged_before_the_next_session(self):
        """The cost commit above the Founder's accepted push is memory alone: the referee would read it as a `noop`,
        and judging it first would put that `noop` where the Founder reads the verdict on its own push, cost a referee
        run and, in an outage, hold the Founder on the launcher's commit. Any work above the last accepted commit is
        still judged first (E168)."""
        from snowball_bootstrap import gitio
        launch = load_launch()
        bare, accepted = self.mirror()
        cost = launch.push_cost_rows(str(bare), [self.FACT], accepted, "2026-10-31T22:00:00Z", credential=False)
        alone = lambda remote, last, evaluated, head, epoch=None: launch.memory_alone(  # noqa: E731
            str(remote), last, evaluated, head, epoch, credential=False)
        self.assertTrue(alone(bare, accepted, accepted, cost))
        self.assertFalse(alone(bare, accepted, accepted, accepted))  # main moved on past the head the cycle read
        self.assertFalse(alone(bare, None, accepted, cost))
        self.assertFalse(alone(bare, accepted, None, cost))  # the newest result did not evaluate its own head
        self.assertFalse(alone(bare, "0" * 40, accepted, cost))  # not in the clone
        self.assertFalse(alone(bare, accepted, "0" * 40, cost))
        work, work_accepted = self.mirror(extra={"referee/a.py": "x = 2\n"})
        head = gitio.git(work, "rev-parse", "main").decode().strip()
        self.assertFalse(alone(work, work_accepted, work_accepted, head))  # work above the accepted commit
        # A memory-only push above a rejected one: the referee judges the rejected work again there (E168).
        rejected, last_ok = self.mirror(extra={"referee/a.py": "x = 2\n"})
        bad = gitio.git(rejected, "rev-parse", "main").decode().strip()
        above = launch.push_cost_rows(str(rejected), [self.FACT], bad, "t", credential=False)  # as if bad were accepted
        self.assertFalse(alone(rejected, last_ok, bad, above))
        # A seed epoch above the accepted head is judged first (its `seed_update` result opens a scorecard segment);
        # a cost commit above the judged epoch is memory alone.
        delivered, ok = self.mirror(extra={"spec/tohum/00-cekirdek.md": "# core, epoch 2\n"})
        epoch = gitio.git(delivered, "rev-parse", "main").decode().strip()
        self.assertFalse(alone(delivered, ok, ok, epoch, epoch))
        after_epoch = launch.push_cost_rows(str(delivered), [self.FACT], ok, "t", epoch, credential=False)
        self.assertTrue(alone(delivered, ok, epoch, after_epoch, epoch))
        self.assertFalse(alone(delivered, ok, epoch, after_epoch, None))  # the seed is no delivery without the epoch
        verdict = {"head": accepted, "verdict": "accepted", "rival": {"attempts": [{"claim": "c"}]},
                   "state": {"last_evaluated_sha": accepted, "last_accepted_sha": accepted}}

        class Fake(quiet_pilot(launch)):
            dispatches = 0

            def fetch_result(self):
                return verdict

            def dispatch_referee(self, timeout_s):
                self.dispatches += 1
                return {"id": "1", "conclusion": "success", "url": "u"}

            def memory_alone(self, prior, head_):
                self.brain_remote = str(bare)
                with mock.patch.object(launch, "GH_CREDENTIAL", "credential.helper="):  # a local mirror: none
                    return launch.Pilot.memory_alone(self, prior, head_)

            def brain_head(self):
                return cost

            def ledger_rows(self, sha):
                return []

            def refresh_inputs(self):
                pass

            def session(self, *a):
                return {"exit": 0, "minutes": 1}

            def write(self, text):
                report.append(text)

        report = []
        pilot = Fake(Path(tempfile.mkdtemp()), "o/brain", "o/referee", "target")
        pilot.idle, pilot.seed = 0, "a" * 40
        args = type("Args", (), dict(model="m", max_turns=1, budget_usd=1, session_timeout=1, referee_timeout=1))
        with mock.patch.object(launch, "say"):
            pilot.cycle(1, args)
        self.assertEqual(pilot.dispatches, 0)  # no referee run before the session, so no `noop` artifact
        self.assertIn("- Hakemin önceki kararı (Kurucu'nun okuduğu): accepted", "".join(report))

    def test_the_launchers_own_commit_is_not_a_founder_push(self):
        """The two-sessions-without-a-push stop counts the Founder's pushes: the cost commit lands after the head is
        read, so a session that pushed nothing is idle even when the launcher wrote a row (N3 (d))."""
        launch = load_launch()
        head = "a" * 40

        class Fake(quiet_pilot(launch)):
            def fetch_result(self):
                return {"head": head, "verdict": "accepted", "state": {"last_evaluated_sha": head,
                                                                       "last_accepted_sha": head}}

            def brain_head(self):
                return head

            def ledger_rows(self, sha):
                return []

            def refresh_inputs(self):
                pass

            def session(self, *a):
                return {"exit": 0, "minutes": 1}

            def write(self, text):
                pass

            def record_cost(self, stamp, sess, head_, last_accepted):
                return "1 satır yazıldı, beyin `ccccccc`"

        pilot = Fake(Path(tempfile.mkdtemp()), "o/brain", "o/referee", "target")
        pilot.idle, pilot.seed = 0, head
        args = type("Args", (), dict(model="m", max_turns=1, budget_usd=1, session_timeout=1, referee_timeout=1))
        with mock.patch.object(launch, "say"):
            self.assertTrue(pilot.cycle(1, args))
            self.assertFalse(pilot.cycle(2, args))  # two sessions without a Founder push stop the pilot
        m = json.loads(pilot.metrics.read_text(encoding="utf-8").splitlines()[-1])
        self.assertEqual((m["pushed"], pilot.idle), (False, 2))


class TranscriptTest(unittest.TestCase):
    def test_the_closing_result_event_is_what_the_report_reads(self):
        launch = load_launch()
        path = Path(tempfile.mkdtemp()) / "s.jsonl"
        events = [{"type": "system", "subtype": "init"}, {"type": "result", "num_turns": 1, "total_cost_usd": 0.1},
                  "not json", {"type": "result", "subtype": "success", "num_turns": 7, "total_cost_usd": 1.5,
                               "result": "pushed MF1"}]
        path.write_text("\n".join(e if isinstance(e, str) else json.dumps(e) for e in events), encoding="utf-8")
        self.assertEqual(launch.Pilot.transcript_summary(path),
                         {"turns": 7, "cost_usd": 1.5, "subtype": "success", "final": "pushed MF1",
                          "api_error": None, "api_error_status": None})
        self.assertEqual(launch.Pilot.transcript_summary(path.with_name("missing.jsonl")), {"transcript": "missing"})


class ImageAndEntrypointTest(unittest.TestCase):
    def setUp(self):
        self.dockerfile = (FOUNDER / "Dockerfile").read_text(encoding="utf-8")
        self.entry = (FOUNDER / "entrypoint.sh").read_text(encoding="utf-8")

    def test_base_images_are_pinned_by_digest_and_the_founder_is_not_root(self):
        froms = re.findall(r"(?m)^FROM (\S+)", self.dockerfile)
        self.assertEqual(len(froms), 2)
        for image in froms:
            self.assertRegex(image, r"@sha256:[0-9a-f]{64}$")
        self.assertRegex(self.dockerfile, r"(?m)^USER founder$")
        self.assertIn("COPY bootstrap/requirements/claude-cli/", self.dockerfile)  # the referee's own CLI pin
        self.assertIn("npm ci", self.dockerfile)

    def test_the_capsule_pins_the_cli_like_the_referee_does(self):
        env_block = self.dockerfile[self.dockerfile.index("ENV "):self.dockerfile.index("USER ")]
        for key, value in rival.PINNED_ENV.items():
            self.assertRegex(env_block, rf"\b{key}={value}\b", f"{key} differs from the referee's rival pin")

    def test_the_founder_is_asked_for_its_own_ideas_and_given_none(self):  # E207, owner 2026-10-29
        """The owner: the system must come up with ideas such as using what it learned in a later repository in an
        earlier one, or finding similarities between repositories. Those ideas are kept off the prompt, in the
        operator's private idea benchmark; the prompt only asks for the Founder's own ideas."""
        prompt = " ".join((FOUNDER / "prompt.md").read_text(encoding="utf-8").split())
        self.assertIn("kimsenin sana söylemediği, sistemi daha iyi yapacak kendi fikrini çıkar", prompt)
        for idea in ("her iki yönde", "başka repolarda", "benzediğini", "kütüphane", "geriye dönük"):
            self.assertNotIn(idea, prompt)

    def test_disagreements_between_its_agents_are_settled_by_evidence(self):  # E208, owner 2026-10-29
        prompt = " ".join((FOUNDER / "prompt.md").read_text(encoding="utf-8").split())
        for phrase in ("Anlaşmazlık kanıtla çözülür", "oyla, otoriteyle, ilk ya da son gelenle karar verilmez",
                       "kanıtı tutan sonuç alınır", "ikisini ayıran deney tasarlanır"):
            self.assertIn(phrase, prompt)

    def test_documents_are_hints_and_the_founders_own_docs_are_generated(self):  # E206, owner 2026-10-29
        prompt = " ".join((FOUNDER / "prompt.md").read_text(encoding="utf-8").split())
        for phrase in ("Belge ipucudur, gerçek koddur", "her iddiayı kodla, yapılandırmayla ve testle doğrula",
                       "bayat belge", "doğrulanmış haritandan üretilir", "kod değişince yeniden üretilir",
                       "hem hedefin hem kendi kodunun (beynin)", "bir insanın okuyup anlayacağı bir harita",
                       "bayat çizim bayat belgedir",  # E301, owner 2026-10-30
                       "Defterin de belgedir", "Eski bir satıra dayanmadan önce onu bugünkü kodla, testle ve hakemin son "
                       "kararıyla doğrula",  # E302, owner 2026-10-30
                       "Hedef, sahibin ürünüdür", "AI kredisi kısıt değildir, zaman değerlidir",
                       "Yol, yöntem ve sıra senindir",  # E305, owner 2026-10-30
                       "Değer hedefte ölçülür", "bugün değmiyorsa değecek hâle getir",  # E337, owner 2026-10-31
                       "duvar saati sınırı 3 saattir",  # E340, the session limit as an observation
                       "Hedefin iyi yazıldığını varsayma", "yürütmedir, görüş değil",  # E361, owner 2026-10-31
                       "Açığı mimariyle kapat, yamayla değil", "çelik gibi çalışan, hatasız, her yoldan sınanmış",
                       "yama ve tekrar",  # E362, owner 2026-10-31
                       "Bir kez sağlam yaz, tekrar kullan", "daha iyi bir mimari ya da yol var mı"):  # E363, owner 2026-10-31
            self.assertIn(phrase, prompt)

    def test_the_founder_keeps_one_source_and_chooses_its_own_architecture(self):  # E205, owner 2026-10-29
        prompt = " ".join((FOUNDER / "prompt.md").read_text(encoding="utf-8").split())
        for phrase in ("Yazmadan önce aynı ya da benzer işi yapan kodu ara", "tek bir yetkili kaynağı olsun",
                       "duruma bakarak sen karar verirsin", "danışma içindir, reçete değil", "`decision` satırı"):
            self.assertIn(phrase, prompt)

    def test_the_founder_fixes_root_causes_and_never_hides_them(self):  # E204, owner 2026-10-29
        prompt = " ".join((FOUNDER / "prompt.md").read_text(encoding="utf-8").split())
        for phrase in ("kök nedeninden ve mimari olarak onar", "`except: pass`", "susturmak",
                       "özel durum olarak kodlamak", "düzeltilmiş gibi yapma"):
            self.assertIn(phrase, prompt)

    def test_the_founder_measures_its_own_coverage_on_the_real_target(self):  # E203: the muscle, not a per-repo patch
        prompt = " ".join((FOUNDER / "prompt.md").read_text(encoding="utf-8").split())
        for phrase in ("`/work/target` üzerinde salt okunur çalıştır", "kapsamını ölç", "`missing_capability:`",
                       "tek bir repoya özel yama değil", "hedefte yeniden ölçüp farkı yaz", "herkese açıktır"):
            self.assertIn(phrase, prompt)
        self.assertNotIn("project.json", prompt)  # the duty is general; what is missing is the Founder's to find
        self.assertNotIn("Nx", prompt)

    def test_every_kind_the_prompt_asks_for_and_the_launcher_surfaces_is_in_the_closed_sets(self):
        """The Founder's report seed-006 (E158): the ledger's and the reports' kind sets are closed (`26`, `26c`), and
        the prompt said "write it as `missing_capability`", a kind no valid row can carry. A missing capability is a
        `seed_issue` row whose text starts `missing_capability:`; the launcher surfaces only kinds a row can have."""
        from snowball_bootstrap import ledgercheck
        prompt = " ".join((FOUNDER / "prompt.md").read_text(encoding="utf-8").split())
        page = (Path(__file__).resolve().parents[3] / "spec" / "tohum" / "26c-semalar-asama-0.md").read_text(encoding="utf-8")
        notices = set(re.search(r"kind: ([a-z_|]+)", page.split("**reports/*.json**", 1)[1]).group(1).split("|"))
        asked = re.findall(r"`([a-z_]+)` (?:olarak yaz|satırı)", prompt)
        asked += re.findall(r"`[a-z_]+:` diye başlayan bir `([a-z_]+)`", prompt)
        asked += [k for pair in re.findall(r"`([a-z_]+)` ya da `([a-z_]+)` satırı", prompt) for k in pair]
        self.assertIn("seed_issue", asked)
        for kind in asked:
            self.assertIn(kind, set(ledgercheck.FOUNDER_KINDS) | notices, kind)
        self.assertNotIn("`missing_capability` olarak yaz", prompt)
        launch = load_launch()
        self.assertTrue(launch.REPORT_KINDS)
        self.assertLessEqual(set(launch.REPORT_KINDS), set(ledgercheck.FOUNDER_KINDS))
        source = (FOUNDER / "launch.py").read_text(encoding="utf-8")
        self.assertNotIn('"missing_capability"', source)  # no tuple or comparison names it as a kind
        self.assertEqual(source.count('row.get("kind") in REPORT_KINDS') + source.count('r.get("kind") in REPORT_KINDS'), 2)

    OWNER_AIM = "**Sahibin amacı (sahip, 2026-10-30 – 2026-11-01).**"  # E463: the owner's directions, one section

    @classmethod
    def owner_aim(cls, prompt: str) -> str:
        """The owner's section in the whitespace-joined prompt: from its title to the next bold title."""
        start = prompt.index(cls.OWNER_AIM)
        return prompt[start:prompt.index("**", start + len(cls.OWNER_AIM))]

    def test_the_owners_aim_is_one_section_right_after_the_real_target_duty(self):  # E463, owner 2026-11-01
        """The owner's eight directions (E305, E337, E361-E364, E460, E462) are one section, merged by three experts
        and a judge and approved by the owner. The eight old headings are gone; the section stands once, right after
        the coverage duty that E364's "Kapsamını ölçtüğünde" leans on; it keeps the prompt's wrapping; and it names
        no domain, tool, seed page or practice the operator holds back to measure what the Founder finds itself."""
        raw = (FOUNDER / "prompt.md").read_text(encoding="utf-8").replace("\r\n", "\n")
        prompt = " ".join(raw.split())
        self.assertEqual(prompt.count(self.OWNER_AIM), 1)
        self.assertEqual(prompt.count("Sahibin amacı"), 1)
        self.assertNotIn("Sahibin hedefi", prompt)  # 'hedef' is the target repository in this prompt
        for heading in ("**Sahibin önceliği (sahip, 2026-10-30).**", "**Değer hedefte ölçülür (sahip, 2026-10-31).**",
                        "**Hedefin iyi yazıldığını varsayma (sahip, 2026-10-31).**",
                        "**Açığı mimariyle kapat, yamayla değil (sahip, 2026-10-31).**",
                        "**Bir kez sağlam yaz, tekrar kullan; her zaman daha iyi yolu sor (sahip, 2026-10-31).**",
                        "**Bilmediğin alan (sahip, 2026-10-31).**",
                        "**Her repo için, en ileri düzeyde (sahip, 2026-11-01).**",
                        "**Sıra muhakemesi (sahip, 2026-11-01).**"):
            self.assertNotIn(heading, prompt)
        section = self.owner_aim(prompt)
        blocks = raw.split("\n\n")
        first = next(i for i, block in enumerate(blocks) if block.startswith(self.OWNER_AIM))
        end = next(i for i in range(first + 1, len(blocks)) if blocks[i].startswith("**"))
        self.assertTrue(blocks[first - 1].startswith("**Gerçek hedefte sına ve eksiğini kendin bul.**"))
        self.assertTrue(blocks[end].startswith("**Anlaşmazlık kanıtla çözülür"))
        self.assertEqual(" ".join(" ".join(blocks[first:end]).split()), section.strip())  # its paragraphs, no more
        for line in "\n".join(blocks[first:end]).split("\n"):
            self.assertLessEqual(len(line), 120, line)
        for phrase in (self.OWNER_AIM, "bir çıtadır, iddia değil", "ürünün iş akışını da anla",
                       "refactor davranışı korur, bir düzeltme yalnız düzelttiği davranışı bilerek değiştirir",
                       "o işe dokunan derslerin de görevle gider", "sonuç dersi sınar, ders sonucu değil",
                       "Neyi önce yapacağını değer ve risk belirler",
                       "bekleyemeyecek bir risk bu sırayı bozmayı gerektiriyorsa riski önce kapat",
                       "neyi neden sonraya bıraktığınla birlikte",
                       "bu hedefe özgü bir varsayıma dayandığın her yeri açıkça yaz"):
            self.assertIn(phrase, section)
        self.assertIsNone(re.search(r"\byem", section, re.IGNORECASE))  # at a word start: 'işleyemediği' is pinned
        for hint in ("besle", "balık", "akuakült", "alarm", "oksijen", "tank", "sensör", "müdahale",  # no domain
                     "planlayıcı", "dispatcher", "görünüm", "enjeksiyon", "withheld", "lessons_injected",  # no seed
                     "düzeltici", "`22`", "`05`", "Aşama 2",  # mechanism, page or stage timing
                     "etki kümesi", "karakterizasyon", "golden", "mutant", "mutasyon", "sözleşme testi", "canary",
                     "FMEA", "HAZOP", "uçtan",  # held-back practices
                     "adaptör", "Nx", "Rust", "Zig", "cargo", "depmap", "profile.fit", "mermaid",  # no tool, no format
                     "kütüphane", "arayüz", "lint", "K0", "K2", "önce ortak"):  # no layer, no concrete order
            self.assertNotIn(hint.casefold(), section.casefold(), hint)
        self.assertNotIn("mimari", section[section.index("Neyi önce yapacağını"):])  # E362/E363 use it before

    def test_the_order_of_work_is_chosen_so_nothing_is_done_twice(self):  # E462, owner 2026-11-01; in E463's section
        """The owner, in their own analogy: sweep the counter before the floor, or the crumbs make you sweep the floor
        twice. The duty is general: choose an order in which a later step does not undo an earlier one, write why,
        and write when a place had to be reopened. It names no layer, tool, class or concrete order. Since E463 it is
        the order half of the priority paragraph of the owner's section, and its closing is the section's one."""
        prompt = " ".join((FOUNDER / "prompt.md").read_text(encoding="utf-8").split())
        section = self.owner_aim(prompt)
        paragraph = section[section.index("Neyi önce yapacağını"):]
        for phrase in ("önce tezgâhı yaparsan",
                       "birinin sonucu bir öncekini bozmayacak ve aynı işi yeniden yaptırmayacak",
                       "aynı yeri yeniden açmak zorunda kaldığında bunu ve nedenini de yaz",
                       "Yol, yöntem ve sıra senindir"):
            self.assertIn(phrase, paragraph)
        for hint in ("mimari", "arayüz", "kütüphane", "lint", "K0", "K2", "Nx", "önce ortak"):
            self.assertNotIn(hint, paragraph)

    FINISH_WORK = "**İşi bitirerek ilerle (sahip, 2026-11-01).**"  # E500

    def test_a_problem_is_closed_at_its_root_before_the_next_and_no_pr_is_left_open(self):  # E500, owner 2026-11-01
        """The owner: on the target, never move to the next problem before this one is solved at its root; when the
        tokens run out, go on from where it stopped; never leave a PR open; work in commits. One section, its own
        title, after the Founder's duties and before what it may not do, in the prompt's wrapping. Unfinished work
        lives on a work branch (never the brain's main nor the target's brain/integration), a cut session leaves the
        next step in its last commit, and the session after a cut first resumes and closes what was left open; a
        rejection still comes first, and the one-job-per-session rule stands."""
        raw = (FOUNDER / "prompt.md").read_text(encoding="utf-8").replace("\r\n", "\n")
        prompt = " ".join(raw.split())
        self.assertEqual(prompt.count(self.FINISH_WORK), 1)
        blocks = raw.split("\n\n")
        at = next(i for i, block in enumerate(blocks) if block.startswith(self.FINISH_WORK))
        self.assertTrue(blocks[at - 1].startswith("**Görevlerin (operatör, 2026-10-29).**"))
        self.assertTrue(blocks[at + 1].startswith("**Yapamazsın:**"))
        for line in blocks[at].split("\n"):
            self.assertLessEqual(len(line), 120, line)
        section = " ".join(blocks[at].split())
        for phrase in ("bir problemi kökten çözmeden diğerine geçmesin",
                       "kanıtı hakemden geçtiğinde biter; bitmeden sıradakine geçmezsin",
                       "her oturumda yine tek iş yaparsın",
                       "beyinde `wip/<konu>`, hedefte `brain/` altındaki dalın",
                       "yarım iş beynin `main`'ine ve hedefin `brain/integration`'ına girmez",
                       "çalışma dalının son commit mesajına sıradaki adımı yaz",
                       "hakemin bir reddi varsa onu giderdikten sonra",
                       "açtığın her PR oturum bitmeden ya birleşir ya kapanır",
                       "yeni bir işe başlamadan kapanır",
                       "Biten işin çalışma dalını sil"):
            self.assertIn(phrase, section)
        self.assertIn("Ret varsa bu oturumun ilk işi o nedeni düzeltmektir", prompt)  # the rejection rule is unchanged
        self.assertNotIn("force", section.casefold())  # a work branch is pushed forward, never rewritten

    def test_the_system_is_for_every_repository_and_its_lessons_are_claims(self):  # E460, owner 2026-11-01; E463
        """The owner: Snowball is a general application for every kind of repository, not tailored to this target; it
        knows and closes its own gaps, understands the given repository fully, gives its agents the repository's map
        with their task, and tests whether what it learned is right. The duty is general: it names no tool, adaptor,
        ecosystem or format, and how stays the Founder's. Since E463 it is part of the owner's section."""
        prompt = " ".join((FOUNDER / "prompt.md").read_text(encoding="utf-8").split())
        section = self.owner_aim(prompt)
        for phrase in ("her çeşit repoya göre tasarlanmış kapsayıcı bir uygulama olmalı",
                       "Bu hedef senin ilk sınavındır, son değil",
                       "hiç görmediğin bir repoda da doğru çalışacak kadar genel olmalı",
                       "hedefin koddan üretilmiş güncel haritasını ve işin ilgili kısmını görevle birlikte ver",
                       "Öğrendiğin her şey bir iddiadır"):
            self.assertIn(phrase, section)
        for hint in ("Nx", "Rust", "Zig", "cargo", "depmap", "profile.fit", "mermaid", "adaptör"):
            self.assertNotIn(hint, section)

    def test_the_founder_owns_the_whole_target_even_a_domain_it_does_not_know(self):  # E364, owner 2026-10-31; E463
        """The owner: in a domain it does not know at all, with no muscles for it, the system must understand it,
        learn and apply it, solve what it meets and become expert in it, by itself. The duty is general: it names no
        language, tool, mechanism, curriculum or timing, it does not answer the Founder's own earlier closure, and
        it does not point at the seed pages that are held (E304: the owner's decision, never a hint). Since E463 its
        body stands word for word in the owner's section, after the coverage duty it leans on; the sealed generality
        exam (sha256 e901b772...) measures that body."""
        prompt = " ".join((FOUNDER / "prompt.md").read_text(encoding="utf-8").split())
        section = self.owner_aim(prompt)
        body = ("Hedefin bütün kodu, içerdiği her dil, ekosistem ve yapıyla senin alanındır; sıradaki aşamanın "
                "ihtiyacıyla sınırlı değildir. Kapsamını ölçtüğünde işleyemediğin her parça, hiç bilmediğin ve hiçbir "
                "aletinin işleyemediği bir alan olsa da, senin işindir: onu kendin anla, öğren ve uygula, "
                "karşılaştığın problemleri anlayıp çöz, o alanda uzmanlaş.")
        for phrase in (body, "sıradaki aşamanın ihtiyacıyla sınırlı değildir",
                       "hiçbir aletinin işleyemediği bir alan olsa da", "o alanda uzmanlaş",
                       "neyi, ne zaman, hangi sırayla ve nasıl öğreneceğine ve yapacağına sen karar verirsin"):
            self.assertIn(phrase, section)
        self.assertLess(prompt.index("**kapsamını ölç**"), prompt.index(body))
        for hint in ("Rust", "Zig", "cargo", "Cargo", "clippy", "rustfmt", "build.rs",  # no domain, no tool
                     "kas büyüt", "kasın", "müfredat",  # no mechanism, no curriculum
                     "f284", "f360", "kapalı sayılmaz",  # not the answer to its own closure
                     "tohum/17", "tohum/21", "`17`", "`21`"):  # no routing to the held pages
            self.assertNotIn(hint, prompt)

    def test_the_founder_gets_the_vector_inputs_and_reports_a_vector_that_contradicts_its_page(self):  # E244, f97
        prompt = " ".join((FOUNDER / "prompt.md").read_text(encoding="utf-8").split())
        for phrase in ("`/vec`'te salt okunurdur", "`/vec/cases.json`", "Beklenen değerler orada yoktur",
                       "`stdin`'iyle, olduğu gibi", "sayfasıyla çelişiyorsa kırmızı kalır",
                       "operatör bir tohum dönemiyle yanıt verene kadar kabulü engeller",
                       "kanıtıyla (vaka, sayfanın satırı, çıktı) `seed_issue` yaz, etrafından dolaşma",
                       "Bir girdiyi (bir fikstürü, bir yolu, bir vaka adını) özel durum olarak kodlamak gizlemedir",
                       "rakip taze girdilerle çürütür", "Hakem reposunu ve `snowball-mcp`'yi okuma yasağı sürer"):
            self.assertIn(phrase, prompt)
        for claim in ("tartışmalı", "askıya", "disputed"):  # a seed_issue sets no vector aside: nothing implements that
            self.assertNotIn(claim, prompt)

    def test_the_session_has_no_inherited_configuration_and_no_mcp(self):
        self.assertIn('--setting-sources ""', self.entry)
        self.assertIn("--strict-mcp-config", self.entry)
        self.assertIn("--no-session-persistence", self.entry)
        self.assertIn('CLAUDE_CONFIG_DIR="$(mktemp -d)"', self.entry)
        self.assertNotIn("ANTHROPIC_API_KEY", self.entry + self.dockerfile)

    def test_four_tools_are_denied_and_no_other_is_narrowed(self):  # E380
        """RemoteTrigger is the one default tool whose effect can outlive the capsule; the Cron tools die with the
        session and were never used. Every other default tool stays: the session's tool set is the Founder's."""
        call = self.entry[self.entry.index("claude -p"):self.entry.index('> "/work/logs/session-')]
        denied = re.findall(r'--disallowedTools "([^"]*)"', self.entry)
        self.assertEqual(len(denied), 1)
        self.assertIn(f'--disallowedTools "{denied[0]}"', call)
        self.assertEqual(denied[0].split(","), ["RemoteTrigger", "CronCreate", "CronDelete", "CronList"])
        for narrowing in ("--tools", "--allowedTools", "--allowed-tools", "--disallowed-tools"):
            self.assertNotRegex(self.entry, rf"(?m){re.escape(narrowing)}(\s|=|$)", narrowing)

    def test_git_trusts_the_brain_clone_on_its_root_owned_tmpfs(self):  # E152: without it no commit, no push
        self.assertIn("safe.directory /work/brain", self.entry)

    def test_the_clone_holds_no_history_before_the_seed(self):  # E154: earlier rehearsal code is not the Founder's
        cut = self.entry[self.entry.index('if [ -n "${BRAIN_SEED:-}" ]'):]
        self.assertIn('merge-base --is-ancestor "$BRAIN_SEED" HEAD', cut)
        self.assertIn("> /work/brain/.git/shallow", cut)
        self.assertIn("reflog expire --expire=now --all", cut)
        self.assertIn("gc --quiet --prune=now", cut)
        self.assertLess(self.entry.index("git clone"), self.entry.index('if [ -n "${BRAIN_SEED:-}" ]'))
        self.assertLess(self.entry.index("gc --quiet --prune=now"), self.entry.index("claude -p"))

    def test_the_github_token_never_reaches_a_url_a_command_line_or_the_log(self):
        self.assertIn("http.https://github.com/.extraheader", self.entry)
        self.assertIn("unset GITHUB_TOKEN basic", self.entry)
        self.assertNotRegex(self.entry, r"https://[^\"\s]*\$\{?GITHUB_TOKEN")
        self.assertNotRegex(self.entry, r"echo[^\n]*\$\{?(GITHUB_TOKEN|CLAUDE_CODE_OAUTH_TOKEN|basic)")
        self.assertNotIn("set -x", self.entry)


class BrainDefinitionsTest(unittest.TestCase):  # E450, owner 2026-11-01: the brain's agents/ and skills/ load, checked
    """The capsule loads the agent and skill definitions the Founder keeps in its brain, at the start of every session,
    and nothing else of the brain. Each guardrail is held here; the real CLI reading the result is in test_live_cli."""

    def setUp(self):
        self.defs = load_brain_defs()
        self.tmp = Path(tempfile.mkdtemp())

    def brain(self, entries: dict) -> Path:
        path = self.tmp / f"brain{sum(1 for _ in self.tmp.iterdir())}"
        tree_repo(path, entries)
        return path

    def load(self, entries: dict, limits=None) -> tuple[dict, Path]:
        brain = self.brain(entries)
        plugin = brain.with_name(brain.name + "-plugin")
        with mock.patch.object(self.defs, "LIMITS", limits or self.defs.LIMITS):
            record = self.defs.build(brain, plugin).record()
        return record, plugin

    @staticmethod
    def files(plugin: Path) -> list[str]:
        return sorted(p.relative_to(plugin).as_posix() for p in plugin.rglob("*") if p.is_file())

    @staticmethod
    def skipped(record: dict) -> dict[str, list[str]]:
        return {row["path"]: row["reasons"] for row in record["skipped"]}

    def test_only_agents_and_skills_become_the_plugin(self):
        brain = self.brain({
            "agents/reviewer.md": definition("reviewer"), "skills/probe/SKILL.md": definition("probe"),
            "CLAUDE.md": b"# instructions\n", "AGENTS.md": b"x\n", ".mcp.json": b'{"mcpServers": {"x": {}}}\n',
            ".claude/settings.json": b'{"hooks": {}}\n', ".claude/agents/inner.md": definition("inner"),
            ".claude/skills/inner/SKILL.md": definition("inner"), "hooks/hooks.json": b'{"hooks": {}}\n',
            "commands/c.md": b"c\n", "output-styles/s.md": b"s\n", "settings.json": b"{}\n",
            ".claude-plugin/plugin.json": b'{"name": "other", "hooks": "./h.json"}\n', "monitors/monitors.json": b"{}\n",
            "bin/tool": ("100755", b"#!/bin/sh\n"), "referee/agents/x.md": definition("x"),
            "docs/skills/y/SKILL.md": definition("y")})
        (brain / "agents").mkdir()  # in the working tree, not committed: git's objects are what is read
        (brain / "agents" / "extra.md").write_bytes(definition("extra"))
        plugin = self.tmp / "plugin"
        record = self.defs.build(brain, plugin).record()
        self.assertEqual(self.files(plugin), [".claude-plugin/plugin.json", "agents/reviewer.md", "skills/probe/SKILL.md"])
        self.assertEqual(json.loads((plugin / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8")),
                         {"name": "brain"})
        self.assertEqual([a["loaded_as"] for a in record["agents"]], ["brain:reviewer"])
        self.assertEqual([s["loaded_as"] for s in record["skills"]], ["brain:probe"])
        self.assertEqual(record["skipped"], [])  # nothing outside the two folders is even looked at
        self.assertIsNone(record["error"])

    def test_every_definition_is_written_anew_from_its_checked_fields(self):
        agent = ('---\r\nname: reviewer\r\ndescription: "Reviews: \\"quoted\\" code, ç # text"\r\n\r\n'
                 'tools: Read,  Grep ,Read\r\nmodel: sonnet\r\n---\r\nYou review.\r\n---\r\nstill the body\r\n')
        script = b"#!/bin/sh\r\necho run\r\n"
        record, plugin = self.load({
            "agents/reviewer.md": agent.encode("utf-8"),
            "skills/probe/SKILL.md": b"---\nname: probe\ndescription: 'It''s a probe: run it'\n---\nRun it.",
            "skills/probe/scripts/run.sh": ("100755", script), "skills/probe/notes.md": b"notes\n"})
        self.assertEqual((plugin / "agents" / "reviewer.md").read_text(encoding="utf-8"),
                         '---\nname: reviewer\ndescription: "Reviews: \\"quoted\\" code, ç # text"\ntools: Read, Grep\n'
                         "model: sonnet\n---\nYou review.\n---\nstill the body\n")
        self.assertEqual((plugin / "skills" / "probe" / "SKILL.md").read_text(encoding="utf-8"),
                         '---\nname: probe\ndescription: "It\'s a probe: run it"\n---\nRun it.\n')
        self.assertEqual((plugin / "skills" / "probe" / "scripts" / "run.sh").read_bytes(), script)  # as it is
        if os.name != "nt":
            self.assertEqual((plugin / "skills" / "probe" / "scripts" / "run.sh").stat().st_mode & 0o777, 0o755)
            self.assertEqual((plugin / "skills" / "probe" / "notes.md").stat().st_mode & 0o777, 0o644)
        self.assertEqual(record["agents"][0]["tools"], ["Read", "Grep"])
        self.assertEqual(record["agents"][0]["model"], "sonnet")

    def test_a_key_outside_the_format_drops_the_definition(self):
        keys = ("hooks", "mcpServers", "permissionMode", "skills", "isolation", "disallowedTools", "color")
        entries = {f"agents/a{i}.md": definition(f"a{i}", extra={key: "x"}) for i, key in enumerate(keys)}
        skill_keys = ("allowed-tools", "hooks", "model", "context", "tools")  # a skill takes name and description only
        entries.update({f"skills/s{i}/SKILL.md": definition(f"s{i}", extra={key: "x"}) for i, key in enumerate(skill_keys)})
        record, plugin = self.load(entries)
        self.assertEqual(record["agents"] + record["skills"], [])
        self.assertEqual(self.skipped(record), {**{f"agents/a{i}.md": [f"key_not_allowed:{k}"] for i, k in enumerate(keys)},
                                                **{f"skills/s{i}/": [f"key_not_allowed:{k}"] for i, k in enumerate(skill_keys)}})
        self.assertEqual(self.files(plugin), [".claude-plugin/plugin.json"])

    def test_an_agent_whose_tools_leave_the_capsules_is_dropped_and_named(self):
        entries = {"agents/ok.md": definition("ok", extra={"tools": "Read, Grep, Bash, Agent, Task, WebFetch, Skill"})}
        for tool in self.defs.DENIED_TOOLS:
            entries[f"agents/deny-{tool.lower()}.md"] = definition(f"deny-{tool.lower()}", extra={"tools": f"Read, {tool}"})
        unknown = ("Foo", "Bash(git *)", "mcp__x__y", "read", "PowerShell")
        for i, tool in enumerate(unknown):
            entries[f"agents/unknown-{i}.md"] = definition(f"unknown-{i}", extra={"tools": f"Read, {tool}"})
        entries["agents/empty.md"] = definition("empty", extra={"tools": ""})
        entries["agents/hole.md"] = definition("hole", extra={"tools": "Read,,Grep"})
        record, plugin = self.load(entries)
        self.assertEqual([(a["name"], a["tools"]) for a in record["agents"]],
                         [("ok", ["Read", "Grep", "Bash", "Agent", "Task", "WebFetch", "Skill"])])
        skipped = self.skipped(record)
        for tool in self.defs.DENIED_TOOLS:
            self.assertEqual(skipped[f"agents/deny-{tool.lower()}.md"], [f"tool_denied:{tool}"])
        for i, tool in enumerate(unknown):
            self.assertEqual(skipped[f"agents/unknown-{i}.md"], [f"tool_not_allowed:{tool}"])
        self.assertEqual(skipped["agents/empty.md"], ["bad_tools"])
        self.assertEqual(skipped["agents/hole.md"], ["bad_tools"])
        self.assertEqual(self.files(plugin), [".claude-plugin/plugin.json", "agents/ok.md"])

    def test_the_tool_sets_are_the_capsules(self):  # E380: the four the entrypoint denies, never one of them allowed
        entry = (FOUNDER / "entrypoint.sh").read_text(encoding="utf-8")
        self.assertEqual(re.findall(r'--disallowedTools "([^"]*)"', entry), [",".join(self.defs.DENIED_TOOLS)])
        self.assertEqual(self.defs.ALLOWED_TOOLS & set(self.defs.DENIED_TOOLS), set())
        self.assertTrue(all(self.defs.TOOL_RE.fullmatch(tool) for tool in self.defs.ALLOWED_TOOLS))

    def test_the_limits_are_one_named_constant_and_each_is_enforced(self):
        Limits = self.defs.Limits
        self.assertIsInstance(self.defs.LIMITS, Limits)
        big = definition("big", body="x" * 300 + "\n")
        cases = [  # (limits, brain, skipped, loaded)
            (Limits(agents=2), {f"agents/{n}.md": definition(n) for n in "abc"}, {"agents/c.md": ["over_limit:agents"]},
             ["a", "b"]),
            (Limits(skills=1), {f"skills/{n}/SKILL.md": definition(n) for n in "ab"}, {"skills/b/": ["over_limit:skills"]},
             ["a"]),
            (Limits(definition_bytes=200), {"agents/big.md": big, "skills/big/SKILL.md": big, "agents/a.md": definition("a")},
             {"agents/big.md": ["over_limit:definition_bytes"], "skills/big/": ["over_limit:definition_bytes"]}, ["a"]),
            (Limits(skill_files=2), {"skills/s/SKILL.md": definition("s"), "skills/s/a": b"a", "skills/s/b": b"b",
                                     "skills/t/SKILL.md": definition("t"), "skills/t/a": b"a"},
             {"skills/s/": ["over_limit:skill_files"]}, ["t"]),
            (Limits(skill_bytes=100), {"skills/s/SKILL.md": definition("s"), "skills/s/a": b"a" * 60,
                                       "skills/t/SKILL.md": definition("t")},
             {"skills/s/": ["over_limit:skill_bytes"]}, ["t"]),
            (Limits(skill_depth=1), {"skills/s/SKILL.md": definition("s"), "skills/s/a/c/d.txt": b"d",
                                     "skills/t/SKILL.md": definition("t"), "skills/t/a/b.txt": b"b"},
             {"skills/s/": ["over_limit:skill_depth:skills/s/a/c/d.txt"]}, ["t"]),
            (Limits(total_bytes=100), {f"agents/{n}.md": definition(n) for n in "ab"},  # 64 bytes each
             {"agents/b.md": ["over_limit:total_bytes"]}, ["a"]),
            (Limits(entries=3), {**{f"agents/{n}.md": definition(n) for n in "abcd"}, "skills/s/SKILL.md": definition("s")},
             {"agents/": ["over_limit:entries"]}, ["s"]),
        ]
        for limits, entries, skipped, loaded in cases:
            with self.subTest(limits=limits):
                record, _ = self.load(entries, limits)
                self.assertEqual(self.skipped(record), skipped)
                self.assertEqual([d["name"] for d in record["agents"] + record["skills"]], loaded)
                self.assertEqual(record["limits"], dataclasses.asdict(limits))
        record, _ = self.load({f"agents/{n}.md": b"broken\n" for n in "abc"}, Limits(skipped_listed=2))
        self.assertEqual((len(record["skipped"]), record["skipped_total"]), (2, 3))  # the rest are counted

    def test_names_are_checked_and_nothing_leads_out_of_the_brain(self):
        record, plugin = self.load({
            "agents/Upper.md": definition("Upper"), "agents/under_score.md": definition("under_score"),
            "agents/-dash.md": definition("-dash"), f"agents/{'a' * 65}.md": definition("a" * 65),
            "agents/mismatch.md": definition("other"), "agents/claude.md": definition("claude"),
            "agents/agents.md": definition("agents"), "agents/link.md": ("120000", b"../../../run/secrets/founder.env"),
            "agents/sub.md": ("160000", b"a" * 40), "agents/readme.txt": b"x\n", "agents/nested/x.md": definition("x"),
            "skills/linked/SKILL.md": ("120000", b"../../CLAUDE.md"),
            "skills/inner-link/SKILL.md": definition("inner-link"), "skills/inner-link/data": ("120000", b"/etc/passwd"),
            "skills/sub/SKILL.md": definition("sub"), "skills/sub/vendor": ("160000", b"b" * 40),
            "skills/conf/SKILL.md": definition("conf"), "skills/conf/.claude/settings.json": b"{}\n",
            "skills/conf2/SKILL.md": definition("conf2"), "skills/conf2/docs/CLAUDE.md": b"x\n",
            "skills/odd/SKILL.md": definition("odd"), "skills/odd/a b.txt": b"x\n",
            "skills/uni/SKILL.md": definition("uni"), "skills/uni/\u00f6.txt": b"x\n",
            "skills/Bad_Name/SKILL.md": definition("Bad_Name"), "skills/README.md": b"x\n",
            "skills/ok/SKILL.md": definition("ok"), "skills/ok/.gitkeep": b""})
        self.assertEqual(record["agents"], [])
        self.assertEqual([s["name"] for s in record["skills"]], ["ok"])
        self.assertEqual(self.skipped(record), {
            "agents/Upper.md": ["bad_name"], "agents/under_score.md": ["bad_name"], "agents/-dash.md": ["bad_name"],
            f"agents/{'a' * 65}.md": ["bad_name"], "agents/mismatch.md": ["name_mismatch"],
            "agents/claude.md": ["agent_config"], "agents/agents.md": ["agent_config"], "agents/link.md": ["symlink"],
            "agents/sub.md": ["submodule"], "agents/readme.txt": ["not_a_definition"],
            "agents/nested/": ["not_a_definition"], "skills/README.md": ["not_a_definition"],
            "skills/linked/": ["symlink:skills/linked/SKILL.md"], "skills/inner-link/": ["symlink:skills/inner-link/data"],
            "skills/sub/": ["submodule:skills/sub/vendor"],
            "skills/conf/": ["agent_config:skills/conf/.claude/settings.json"],
            "skills/conf2/": ["agent_config:skills/conf2/docs/CLAUDE.md"], "skills/odd/": ["bad_path:skills/odd/a b.txt"],
            "skills/uni/": ["bad_path:skills/uni/\u00f6.txt"], "skills/Bad_Name/": ["bad_name"]})
        self.assertEqual(self.files(plugin), [".claude-plugin/plugin.json", "skills/ok/.gitkeep", "skills/ok/SKILL.md"])

    def test_the_record_names_what_loaded_with_the_sha256_of_its_source(self):
        agent, skill, notes = definition("reviewer", extra={"model": "inherit"}), definition("probe"), b"notes\n"
        brain = self.brain({"agents/reviewer.md": agent, "skills/probe/SKILL.md": skill, "skills/probe/notes.md": notes,
                            "agents/bad.md": b"no front matter\n"})
        logs = self.tmp / "logs"
        logs.mkdir()
        rc = self.defs.main([str(brain), str(self.tmp / "plugin"), str(logs / "brain-definitions.json")])
        self.assertEqual(rc, 0)
        record = json.loads((logs / "brain-definitions.json").read_text(encoding="utf-8"))
        sha = lambda data: hashlib.sha256(data).hexdigest()  # noqa: E731  the blob's bytes: `git cat-file blob | sha256sum`
        self.assertEqual(record["schema"], "snowball-brain-definitions/1")
        self.assertEqual(record["brain"], sh(brain, "git", "rev-parse", "HEAD"))
        self.assertIsNone(record["error"])
        self.assertEqual(record["agents"], [{"name": "reviewer", "loaded_as": "brain:reviewer", "path": "agents/reviewer.md",
                                             "sha256": sha(agent), "tools": None, "model": "inherit"}])
        self.assertEqual(record["skills"], [{"name": "probe", "loaded_as": "brain:probe", "path": "skills/probe/SKILL.md",
                                             "sha256": sha(skill), "files": {"skills/probe/SKILL.md": sha(skill),
                                                                             "skills/probe/notes.md": sha(notes)}}])
        self.assertEqual(record["skipped"], [{"path": "agents/bad.md", "reasons": ["no_frontmatter"]}])
        self.assertEqual(record["limits"], dataclasses.asdict(self.defs.LIMITS))
        self.assertEqual(record["denied_tools"], list(self.defs.DENIED_TOOLS))
        self.assertEqual(record["allowed_tools"], sorted(self.defs.ALLOWED_TOOLS))
        self.assertEqual(sorted(p.name for p in logs.iterdir()), ["brain-definitions.json"])  # no temporary left

    def test_a_broken_definition_is_skipped_and_the_rest_load(self):
        record, plugin = self.load({
            "agents/good.md": definition("good"),
            "agents/latin.md": "---\nname: latin\ndescription: café\n---\nx\n".encode("latin-1"),
            "agents/bare.md": b"You review.\n", "agents/open.md": b"---\nname: open\ndescription: d\nno end\n",
            "agents/line.md": b"---\nname: line\n  indented: x\ndescription: d\n---\nx\n",
            "agents/twice.md": b"---\nname: twice\nname: twice\ndescription: d\n---\nx\n",
            "agents/nodesc.md": b"---\nname: nodesc\n---\nx\n", "agents/empty.md": b"---\nname: empty\ndescription: d\n---\n\n \n",
            "agents/quote.md": b'---\nname: quote\ndescription: "open\n---\nx\n',
            "agents/ctrl.md": b'---\nname: ctrl\ndescription: "a\\u0007b"\n---\nx\n',
            "agents/sep.md": "---\nname: sep\ndescription: a\u2028b\n---\nx\n".encode("utf-8"),
            "agents/long.md": definition("long", description="d" * 1025),
            "agents/model.md": definition("model", extra={"model": "sonnet; rm -rf /"}),
            "skills/good/SKILL.md": definition("good"),
            "skills/nobody/SKILL.md": b"---\nname: nobody\ndescription: d\n---\n"})
        self.assertEqual([a["name"] for a in record["agents"]], ["good"])
        self.assertEqual([s["name"] for s in record["skills"]], ["good"])
        self.assertEqual(self.skipped(record), {
            "agents/latin.md": ["not_utf8"], "agents/bare.md": ["no_frontmatter"], "agents/open.md": ["no_frontmatter"],
            "agents/line.md": ["bad_frontmatter_line"], "agents/twice.md": ["duplicate_key:name"],
            "agents/nodesc.md": ["missing:description"], "agents/empty.md": ["empty_body"],
            "agents/quote.md": ["bad_quotes:description", "missing:description"], "agents/ctrl.md": ["bad_description"],
            "agents/sep.md": ["bad_description"], "agents/long.md": ["bad_description"], "agents/model.md": ["bad_model"],
            "skills/nobody/": ["empty_body"]})
        self.assertIsNone(record["error"])

    def test_an_unforeseen_failure_in_one_definition_names_it_and_the_rest_load(self):
        real = self.defs.check_fields

        def failing(fields, name):
            if name == "boom":
                raise RuntimeError("unforeseen")
            return real(fields, name)

        with mock.patch.object(self.defs, "check_fields", failing):
            record, plugin = self.load({"agents/boom.md": definition("boom"), "agents/good.md": definition("good"),
                                        "skills/boom/SKILL.md": definition("boom"), "skills/boom/a.txt": b"a",
                                        "skills/good/SKILL.md": definition("good")})
        self.assertEqual(self.skipped(record), {"agents/boom.md": ["error:RuntimeError"],
                                                "skills/boom/": ["error:RuntimeError"]})
        self.assertEqual(self.files(plugin), [".claude-plugin/plugin.json", "agents/good.md", "skills/good/SKILL.md"])

    def test_a_loader_that_cannot_read_the_brain_leaves_no_plugin_and_says_why(self):
        plugin, record_file = self.tmp / "plugin", self.tmp / "brain-definitions.json"
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertEqual(self.defs.main([str(self.tmp / "no-brain"), str(plugin), str(record_file)]), 0)
        self.assertIn("brain definitions not loaded: CalledProcessError", err.getvalue())  # the container's log
        record = json.loads(record_file.read_text(encoding="utf-8"))
        self.assertTrue(record["error"].startswith("CalledProcessError"), record["error"])
        self.assertEqual((record["agents"], record["skills"]), ([], []))
        self.assertFalse(plugin.exists())  # the CLI starts without a plugin it cannot find (test_live_cli)
        self.assertFalse(plugin.with_name("plugin.partial").exists())

    def test_the_capsule_loads_them_after_the_clone_and_before_claude_and_never_stops_on_them(self):
        entry = (FOUNDER / "entrypoint.sh").read_text(encoding="utf-8")
        loader = ('python3 /opt/founder/brain_defs.py /work/brain "$CLAUDE_CONFIG_DIR/brain-plugin" '
                  '/work/logs/brain-definitions.json \\\n  || echo ')
        self.assertEqual(entry.count("/opt/founder/brain_defs.py"), 1)
        self.assertIn(loader, entry)  # `||`: under `set -e` a failed loader never stops the session
        self.assertLess(entry.index("gc --quiet --prune=now"), entry.index(loader))
        self.assertLess(entry.index(loader), entry.index("claude -p"))
        call = entry[entry.index("claude -p"):entry.index('> "/work/logs/session-')]
        self.assertEqual(re.findall(r"--plugin-dir \S+", entry), ['--plugin-dir "$CLAUDE_CONFIG_DIR/brain-plugin"'])
        self.assertIn('--plugin-dir "$CLAUDE_CONFIG_DIR/brain-plugin"', call)
        self.assertIn('--setting-sources ""', call)
        for other in ("--agents", "--agent ", "--add-dir", "--settings", "--plugin-url", "--bare", "--safe-mode"):
            self.assertNotIn(other, call)  # the plugin is the one way in
        self.assertIn('CLAUDE_CONFIG_DIR="$(mktemp -d)"', entry)  # the plugin's folder is this session's own
        self.assertIn("COPY founder/brain_defs.py /opt/founder/brain_defs.py", (FOUNDER / "Dockerfile").read_text(
            encoding="utf-8"))
        self.assertIn("founder/brain_defs.py", load_launch().BUILD_FILES)
        self.assertEqual(self.defs.PLUGIN, "brain")

    def test_the_prompt_states_which_brain_folders_load_and_where_their_record_is(self):  # E450, owner 2026-11-01
        prompt = " ".join((FOUNDER / "prompt.md").read_text(encoding="utf-8").split())
        title = "**Beynin tanımları (gözlem).**"
        paragraph = prompt[prompt.index(title):]
        paragraph = paragraph[:paragraph.index("**", len(title))]
        for phrase in ("her oturumun başında", "`agents/` ve `skills/`", "`brain:<ad>`", "`spec/tohum/24a`",
                       "başka hiçbir dosyasını yapılandırma olarak yüklemez", "`/work/logs/brain-definitions.json`"):
            self.assertIn(phrase, paragraph)
        for nudge in ("yaz", "kullan", "öner", "oluştur", "faydal", "yararl", "gerekirse", "istersen", "senindir", "meli",
                      "malı"):
            self.assertNotIn(nudge, paragraph.casefold())  # a fact: whether, when and why is the Founder's own choice
        self.assertEqual(prompt.count("brain-definitions.json"), 1)
        self.assertIn("`.claude/`", prompt[prompt.index("**Yapamazsın:**"):])  # its own .claude/ still loads nothing

    def test_the_referee_judges_a_push_of_them_as_the_founders_code(self):  # E450: not out of scope, not a record
        from snowball_bootstrap import classify
        paths = ["agents/reviewer.md", "skills/probe/SKILL.md", "skills/probe/scripts/run.sh"]
        self.assertEqual(classify.classify(paths), ("code", []))
        self.assertEqual(classify.classify(paths + [classify.LEDGER_FILE]), ("code", []))
        self.assertEqual(classify.classify(["spec/asama-0/a.md", "agents/reviewer.md"]),
                         ("rejected", [classify.MIXED]))  # like any code beside a spec request
        for path in paths:
            self.assertFalse(classify.is_agent_config(path), path)
            self.assertFalse(classify.is_founder_record(path), path)
            self.assertFalse(classify.is_seed_path(path), path)
            self.assertFalse(rival.hidden(path), path)  # the rival reads them like the rest of the push
        self.assertEqual(self.defs.AGENT_CONFIG_DIRS, classify.AGENT_DIRS)  # one rule for both
        self.assertEqual(self.defs.AGENT_CONFIG_FILES, classify.AGENT_FILES)


if __name__ == "__main__":
    unittest.main()
