"""The Founder's capsule and launcher (`seed/founder`, register E90, E91, E112): the isolation the pilot relies on
is pinned here, so a later edit that loosens it fails a test instead of passing unnoticed."""

from __future__ import annotations

import importlib.util
import io
import json
import re
import subprocess
import tarfile
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from snowball_bootstrap import rival, vectors

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

        class Fake(launch.Pilot):
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

        class Fake(launch.Pilot):
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

        class Fake(launch.Pilot):
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

        class Fake(launch.Pilot):
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

        class Fake(launch.Pilot):
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

        class Fake(launch.Pilot):
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
                       "bayat belge", "doğrulanmış haritandan üretilir", "kod değişince yeniden üretilir"):
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


if __name__ == "__main__":
    unittest.main()
