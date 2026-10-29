"""Boundaries of the rival code, from a mutation run (142 mutants of rival, rival_mcp, cmd_rival, config and
treehash; 82 survived the earlier tests). Each test names the mutants it kills in its docstring."""

import io
import json
import re
import os
import signal
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from snowball_bootstrap import cli, container, rival, rival_mcp
from snowball_bootstrap.config import ConfigError, RivalConfig, load_bootstrap
from snowball_bootstrap.rival import ToolBox, run_rival, validate_verdict
from snowball_bootstrap.rival_mcp import RivalServer, serve
from snowball_bootstrap.treehash import TreeError, extract, iter_files, tree_hash

from helpers import install_fake_claude, ok_result, posix_only, submit

CFG = RivalConfig(model="claude-sonnet-5-5", effort="medium", max_turns=5, per_run_cap_usd_micros=5_000_000)
REFS = [{"path": "referee/a.py", "line_start": 1, "line_end": 1}]


class FakeCliMixin:
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        self.root = base / "tree"
        (self.root / "referee").mkdir(parents=True)
        (self.root / "referee" / "a.py").write_text("x = 1\ny = 2\n")
        self.bin_dir = base / "bin"
        self.bin_dir.mkdir()
        self.claude = install_fake_claude(self.bin_dir)

    def run_with(self, scenario, **kw):
        (self.bin_dir / "scenario.json").write_text(json.dumps(scenario))
        return run_rival(kw.pop("cfg", CFG), claude_bin=kw.pop("claude_bin", str(self.claude)),
                         seat_prompt=kw.pop("seat", "seat"), context=kw.pop("context", "ctx"), tree_root=self.root,
                         budget_usd_micros=kw.pop("budget", 10_000_000), max_prompt_chars=kw.pop("max_chars", 100_000))

    def seen(self, name):
        return json.loads((self.bin_dir / name).read_text())


class RivalRunGaps(FakeCliMixin, unittest.TestCase):
    def test_the_rival_prompt_stops_at_the_end_of_its_own_quote(self):
        """R64: tohum/29 quotes two more seats below the rival; the shipped test only uses assertIn."""
        seats = Path(__file__).resolve().parents[3] / "spec" / "tohum" / "29-tohum-koltuklari.md"
        prompt = rival.extract_seat_prompt(seats.read_text(encoding="utf-8"))
        self.assertTrue(prompt.startswith("Görevin, sana verilen artefaktın yanlış"))
        self.assertTrue(prompt.endswith("reproducer?}]}`."), prompt[-80:])
        for other_seat in ("Düzeltme yazmazsın", "küçük testi yazmak"):
            self.assertNotIn(other_seat, prompt)

    def test_the_mcp_server_is_started_in_isolated_mode(self):
        """R11"""
        self.run_with({"calls": [submit()], "result": ok_result()})
        self.assertEqual(self.seen("seen.json")["mcp_args"][0], "-I")

    def test_the_prompt_limit_is_inclusive_and_counts_the_protocol(self):
        """R05 R06"""
        system = len("seat") + len(rival.PROTOCOL)
        out = self.run_with({"calls": [submit()], "result": ok_result()}, context="x" * 1000, max_chars=system + 1000)
        self.assertEqual((out.verdict, out.reasons), ("not_refuted", []))
        out = self.run_with({"calls": [submit()], "result": ok_result()}, context="x" * 1001, max_chars=system + 1000)
        self.assertEqual(out.reasons, ["prompt_too_large"])

    def test_a_secret_in_the_seat_prompt_is_refused_too(self):
        """R07"""
        out = self.run_with({}, seat="AKIA" + "ABCDEFGHIJKLMNOP")
        self.assertEqual(out.reasons, ["secret_in_prompt:aws_access_key"])

    def test_a_timeout_charges_the_remaining_budget_not_the_per_run_cap(self):
        """R25: with 0.12 USD left the run must not be booked at the 5 USD cap."""
        with mock.patch.object(rival, "CLI_TIMEOUT_S", 1):
            out = self.run_with({"sleep": 5, "calls": [submit()], "result": ok_result()}, budget=123_456)
        self.assertEqual((out.reasons, out.cost_usd_micros), (["api_error:TimeoutExpired"], 123_456))

    def test_a_cli_that_never_reads_its_prompt_is_still_stopped_by_the_timeout(self):
        """V2: on Windows `communicate` wrote the whole request into a pipe before the timeout began to count."""
        stalled = [sys.executable, "-c", "import time; time.sleep(30)"]
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(rival, "CLI_TIMEOUT_S", 2):
            started = time.monotonic()
            with self.assertRaises(subprocess.TimeoutExpired):
                rival._run_cli(stalled, "x" * 3_000_000, Path(tmp), dict(os.environ))
            self.assertLess(time.monotonic() - started, 15)

    def test_sigterm_is_handled_before_the_cli_starts_and_ignored_while_it_is_killed(self):
        """V2: a SIGTERM between Popen and the handler, or during the kill, used to leave the CLI running."""
        before = signal.getsignal(signal.SIGTERM)
        at_start, at_kill = [], []
        real_popen, real_kill = subprocess.Popen, rival._kill_tree

        def spy_popen(*args, **kw):
            at_start.append(signal.getsignal(signal.SIGTERM))
            return real_popen(*args, **kw)

        def spy_kill(proc):
            at_kill.append(signal.getsignal(signal.SIGTERM))
            real_kill(proc)

        stalled = [sys.executable, "-c", "import time; time.sleep(30)"]
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(rival, "CLI_TIMEOUT_S", 1), \
                mock.patch.object(rival.subprocess, "Popen", spy_popen), mock.patch.object(rival, "_kill_tree", spy_kill):
            with self.assertRaises(subprocess.TimeoutExpired):
                rival._run_cli(stalled, "", Path(tmp), dict(os.environ))
        self.assertIs(at_start[0], rival._terminate)
        self.assertEqual(at_kill, [signal.SIG_IGN])
        self.assertEqual(signal.getsignal(signal.SIGTERM), before)  # and put back afterwards

    @posix_only
    def test_a_descendant_that_left_the_process_group_cannot_hold_the_run_open(self):
        """V4: it keeps the stdout pipe open, so a second `communicate` without a limit waits for it."""
        code = ("import subprocess, sys, time; subprocess.Popen([sys.executable, '-c', "
                "'import os, time; os.setsid(); time.sleep(8)']); time.sleep(8)")
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(rival, "CLI_TIMEOUT_S", 1), \
                mock.patch.object(rival, "CLI_KILL_WAIT_S", 1):
            started = time.monotonic()
            with self.assertRaises(subprocess.TimeoutExpired):
                rival._run_cli([sys.executable, "-c", code], "", Path(tmp), dict(os.environ))
            self.assertLess(time.monotonic() - started, 6)

    def test_an_init_that_does_not_name_its_api_key_source_is_not_trusted(self):
        """V4: the check compares with "none"; a missing key must not pass for it."""
        init = {"type": "system", "subtype": "init", "tools": rival.TOOL_NAMES, "skills": [], "slash_commands": [],
                "mcp_servers": [{"name": "snowball", "status": "connected"}]}
        self.assertEqual(rival._isolation_fault(init, {}), "api_key")
        self.assertIsNone(rival._isolation_fault(dict(init, apiKeySource="none"), {}))

    @posix_only
    def test_a_binary_that_cannot_be_executed_fails_closed_as_an_outage(self):
        """R26"""
        plain = self.bin_dir / "plain"
        plain.write_text("not executable")
        out = self.run_with({}, claude_bin=str(plain))
        self.assertEqual((out.verdict, out.reasons), ("unresolved", ["api_error:PermissionError"]))

    @posix_only
    def test_killing_an_already_finished_process_group_is_not_an_error(self):
        """R21: the CLI can exit between the timeout and the kill."""
        proc = subprocess.Popen(["true"], start_new_session=True)
        proc.wait()
        rival._kill_tree(proc)

    @posix_only
    def test_the_kill_cannot_be_ignored_by_the_cli(self):
        """R22: SIGTERM is trappable, so the whole group must get SIGKILL."""
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(rival, "CLI_TIMEOUT_S", 1):
            started = time.monotonic()
            with self.assertRaises(subprocess.TimeoutExpired):
                rival._run_cli(["sh", "-c", "trap '' TERM; sleep 30"], "", Path(tmp), dict(os.environ))
            self.assertLess(time.monotonic() - started, 15)

    @posix_only
    def test_stderr_of_the_cli_is_never_read_as_the_stream(self):
        """R24"""
        with tempfile.TemporaryDirectory() as tmp:
            code, out = rival._run_cli(["sh", "-c", "echo '{\"type\":\"result\"}' >&2"], "", Path(tmp), dict(os.environ))
        self.assertEqual((code, out), (0, ""))

    def test_synthetic_and_modelless_assistant_events_do_not_change_the_served_model(self):
        """R29 R30"""
        init = {"type": "system", "subtype": "init", "apiKeySource": "none", "tools": rival.TOOL_NAMES,
                "skills": [], "slash_commands": [], "mcp_servers": [{"name": "snowball", "status": "connected"}]}
        events = [init, {"type": "assistant", "message": {"model": "<synthetic>"}},
                  {"type": "assistant", "message": {"content": []}}, {"type": "assistant", "message": "text"},
                  {"type": "assistant", "message": {"model": "claude-sonnet-5-5"}}, ok_result()]
        out = self.run_with({"calls": [submit()], "events": events})
        self.assertEqual((out.verdict, out.reasons, out.model_served), ("not_refuted", [], "claude-sonnet-5-5"))

    def test_the_isolation_attestation_is_exact_not_a_subset_or_superset_check(self):
        """R31 R32 R33 R34"""
        good = {"type": "system", "subtype": "init", "apiKeySource": "none", "skills": [], "slash_commands": [],
                "tools": list(rival.TOOL_NAMES), "mcp_servers": [{"name": "snowball", "status": "connected"}]}
        cases = {
            "tools": [dict(good, tools=rival.TOOL_NAMES[:-1])],
            "mcp_servers": [dict(good, mcp_servers=[{"name": "snowball", "status": "connected"},
                                                    {"name": "extra", "status": "connected"}])],
            "skills": [dict(good, slash_commands=["/review"])],
            "api_key": [dict(good, apiKeySource=src) for src in ("user", "project", "org", "temporary")],
        }
        for fault, inits in cases.items():
            for init in inits:
                out = self.run_with({"calls": [submit()], "result": ok_result(), "init": init})
                self.assertEqual(out.reasons, [f"api_error:isolation_{fault}"], (fault, init))

    def test_cost_is_rounded_up_and_a_free_run_is_still_a_run(self):
        """R40 R41"""
        out = self.run_with({"calls": [submit()], "result": ok_result(total_cost_usd=0.0000001)})
        self.assertEqual((out.verdict, out.cost_usd_micros), ("not_refuted", 1))
        out = self.run_with({"calls": [submit()], "result": ok_result(total_cost_usd=0)})
        self.assertEqual((out.verdict, out.cost_usd_micros, out.reasons), ("not_refuted", 0, []))


class ValidatorBoundaryGaps(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        (Path(self.tmp.name) / "referee").mkdir()
        (Path(self.tmp.name) / "referee" / "a.py").write_text("x = 1\ny = 2\n")
        self.box = ToolBox(Path(self.tmp.name))

    def attempt(self, **kw):
        a = {"claim": "c", "evidence_refs": list(REFS)}
        a.update(kw)
        return {"verdict": "refuted", "attempts": [a]}

    def test_limits_are_inclusive_and_exactly_as_the_schema_promises(self):
        """R44 R45 R46 R47"""
        validate_verdict({"verdict": "refuted", "attempts": [self.attempt()["attempts"][0]] * rival.MAX_ATTEMPTS}, self.box)
        with self.assertRaises(ValueError):
            validate_verdict({"verdict": "refuted", "attempts": [self.attempt()["attempts"][0]] * (rival.MAX_ATTEMPTS + 1)},
                             self.box)
        validate_verdict(self.attempt(reproducer={"cmd": "x" * rival.MAX_CMD_CHARS, "expect_exit": 0}), self.box)
        with self.assertRaises(ValueError):
            validate_verdict(self.attempt(reproducer={"cmd": "x" * (rival.MAX_CMD_CHARS + 1), "expect_exit": 0}), self.box)
        validate_verdict(self.attempt(reproducer={"cmd": "x", "expect_stdout_contains": "y" * rival.MAX_EXPECT_CHARS}), self.box)
        with self.assertRaises(ValueError):
            validate_verdict(self.attempt(reproducer={"cmd": "x", "expect_stdout_contains": "y" * (rival.MAX_EXPECT_CHARS + 1)}),
                             self.box)
        kept = validate_verdict(self.attempt(claim="z" * (rival.MAX_CLAIM_CHARS + 50)), self.box)["attempts"][0]["claim"]
        self.assertEqual(len(kept), rival.MAX_CLAIM_CHARS)

    def test_control_characters_and_bool_line_numbers_are_refused(self):
        """V4: only NUL and a bool line_start were tried"""
        for char in (chr(27), chr(13), chr(0), chr(8)):
            with self.assertRaises(ValueError, msg=repr(char)):
                validate_verdict(self.attempt(reproducer={"cmd": "echo" + char + "x", "expect_exit": 0}), self.box)
        validate_verdict(self.attempt(reproducer={"cmd": "a" + chr(10) + chr(9) + "b", "expect_exit": 0}), self.box)
        for field in ("line_start", "line_end"):
            with self.assertRaises(ValueError, msg=field):
                validate_verdict(self.attempt(evidence_refs=[dict(REFS[0], **{field: True})]), self.box)

    def test_a_reference_into_a_file_past_the_size_limit_is_marked_invalid(self):
        """V4: line_count gives up on it, so the reference cannot be checked"""
        (Path(self.tmp.name) / "referee" / "big.txt").write_bytes(b"a" + chr(10).encode() * rival.MAX_FILE_BYTES)
        item = validate_verdict(self.attempt(evidence_refs=[{"path": "referee/big.txt", "line_start": 1, "line_end": 1}]),
                                self.box)["attempts"][0]
        self.assertFalse(item["refs_valid"])

    def test_malformed_attempts_are_refused(self):
        """R48 R50 R51"""
        for bad in (self.attempt(claim="   "), self.attempt(evidence_refs=[]),
                    self.attempt(reproducer={"cmd": "x", "expect_exit": True})):
            with self.assertRaises(ValueError, msg=bad):
                validate_verdict(bad, self.box)

    def test_a_reference_past_the_end_of_the_file_is_marked_invalid(self):
        """R49"""
        refs = [{"path": "referee/a.py", "line_start": 1, "line_end": 3}, {"path": "referee/missing.py", "line_start": 1, "line_end": 1}]
        for one in refs:
            item = validate_verdict(self.attempt(evidence_refs=[one]), self.box)["attempts"][0]
            self.assertFalse(item["refs_valid"], one)


class ToolBoxLimitGaps(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "tree"
        (self.root / "d").mkdir(parents=True)
        self.box = ToolBox(self.root)

    def test_read_file_window_start_and_text_caps(self):
        """R52 R53 R54"""
        (self.root / "d" / "big.txt").write_text("".join(f"{'y' * 200}\n" for _ in range(1000)))
        text = self.box.read_file("d/big.txt")
        self.assertLessEqual(len(text), rival.MAX_TOOL_CHARS)
        small = self.root / "d" / "n.txt"
        small.write_text("".join(f"l{i}\n" for i in range(1, 1001)))
        body = self.box.read_file("d/n.txt").splitlines()
        self.assertEqual((len(body) - 1, body[1], body[-1]), (rival.MAX_READ_LINES, "1: l1", f"{rival.MAX_READ_LINES}: l{rival.MAX_READ_LINES}"))
        self.assertTrue(self.box.read_file("d/n.txt", 0).splitlines()[1].startswith("1: "))
        far = self.box.read_file("d/n.txt", 1, 5000).splitlines()  # an end_line past the window is clamped to it
        self.assertEqual(len(far) - 1, rival.MAX_READ_LINES)

    def test_grep_and_glob_stop_at_their_caps_and_say_so_only_when_they_stop(self):
        """R55 R56 R57 R58"""
        (self.root / "d" / "m.txt").write_text("hit\n" * 300)
        out = self.box.grep("hit").splitlines()
        self.assertEqual((len(out), out[-1]), (rival.MAX_GREP_MATCHES + 1, "(truncated at 200 matches)"))
        (self.root / "d" / "bin.dat").write_bytes(b"\x00hit\n")
        self.assertNotIn("bin.dat", self.box.grep("hit"))
        with self.assertRaises(ValueError):
            self.box.grep("a" * 201)
        for n in range(rival.MAX_GLOB_RESULTS):
            (self.root / f"f{n:04d}.txt").write_text("")
        self.assertEqual(len(self.box.glob("f*.txt").splitlines()), rival.MAX_GLOB_RESULTS)  # exactly the cap: no notice
        (self.root / "f9999.txt").write_text("")
        self.assertTrue(self.box.glob("f*.txt").endswith(f"(truncated at {rival.MAX_GLOB_RESULTS})"))

    def test_a_file_of_exactly_the_size_limit_is_readable(self):
        """R59"""
        (self.root / "d" / "edge.txt").write_bytes(b"a\n" * (rival.MAX_FILE_BYTES // 2))
        self.assertIn("1: a", self.box.read_file("d/edge.txt"))

    @posix_only
    def test_a_tree_reached_through_a_symlink_is_still_readable(self):
        """R60"""
        (self.root / "d" / "a.txt").write_text("hello\n")
        link = Path(self.tmp.name) / "link"
        link.symlink_to(self.root)
        self.assertIn("1: hello", ToolBox(link).read_file("d/a.txt"))

    def test_an_absolute_glob_is_a_value_error_like_every_other_bad_pattern(self):
        """R63 (on POSIX Path.glob raises NotImplementedError itself, which the server also turns into an error result)"""
        with self.assertRaises(ValueError):
            self.box.glob("/etc/*")


class McpServerGaps(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        self.tree = base / "tree"
        (self.tree / "referee").mkdir(parents=True)
        (self.tree / "referee" / "k.txt").write_text("key = " + "gh" + "p_" + "B" * 36 + "\n")
        (self.tree / "referee" / "a.py").write_text("x = 1\n")
        self.stats = base / "s.json"
        self.server = RivalServer(ToolBox(self.tree), base / "v.json", self.stats)

    def test_withheld_results_are_counted_not_flagged(self):
        """S01 S02"""
        for _ in range(2):
            self.server.call("read_file", {"path": "referee/k.txt"})
        self.assertEqual(json.loads(self.stats.read_text())["withheld"], 2)
        bad = {"verdict": "maybe", "attempts": []}
        self.server.call("submit_verdict", bad)
        self.assertIn("verdict must be refuted or not_refuted", json.loads(self.stats.read_text())["last_invalid"])

    def test_three_invalid_submissions_each_get_the_validation_error_and_only_the_fourth_is_refused(self):
        """S03"""
        bad = {"verdict": "maybe", "attempts": []}
        replies = [self.server.call("submit_verdict", bad)[0] for _ in range(4)]
        self.assertTrue(all("invalid verdict" in r for r in replies[:3]), replies)
        self.assertIn("too many invalid submissions", replies[3])

    def test_garbage_and_non_object_lines_do_not_end_the_session(self):
        """S07 S08"""
        lines = ["not json", "[1, 2]", "5", '"text"', "null", json.dumps({"jsonrpc": "2.0", "id": 9, "method": "ping"})]
        out = io.StringIO()
        serve(self.server, io.StringIO("\n".join(lines) + "\n"), out)
        self.assertEqual([json.loads(x) for x in out.getvalue().splitlines()],
                         [{"jsonrpc": "2.0", "id": 9, "result": {}}])

    def test_tool_arguments_that_are_not_an_object_give_an_error_result_not_a_protocol_error(self):
        """S09"""
        msg = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "read_file", "arguments": "a.py"}}
        reply = self.server.handle(msg)
        self.assertIn("result", reply)
        self.assertTrue(reply["result"]["isError"])

    def test_the_production_deadline_is_seconds_not_something_that_never_fires(self):
        """S10"""
        self.assertTrue(0 < rival_mcp.TOOL_TIMEOUT_S <= 60)
        self.assertEqual(self.server.tool_timeout_s, rival_mcp.TOOL_TIMEOUT_S)


class CmdRivalGaps(unittest.TestCase):
    """C01 C05 C06 C07 C08 C12: cmd_rival wiring that only the stubbed e2e test touches."""

    def setUp(self):
        from test_flow import Flow  # reuse the repository fixtures of the shipped flow test
        self.flow = Flow("test_full_stage0_path")
        self.flow.setUp()
        self.addCleanup(self.flow.tearDown)
        f = self.flow
        seats = f.referee / "seats"
        seats.mkdir()
        src = Path(__file__).resolve().parents[3] / "spec" / "tohum" / cli.SEATS_FILE
        (seats / cli.SEATS_FILE).write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
        from helpers import commit
        commit(f.brain, {"spec/asama-0/00-ozet.md": "# stage 0, revised\n", "spec/tohum/04-kod.md": "# a page only code requests see\n"}, "spec only")
        f.meta = f.pull()
        self.pulled = Path(f.tmp.name) / f"pulled{f.n}"
        self.bin_dir = Path(f.tmp.name) / "bin"
        self.bin_dir.mkdir()
        self.claude = install_fake_claude(self.bin_dir)
        self.gh = Path(f.tmp.name) / "gh_output"
        os.environ["GITHUB_OUTPUT"] = str(self.gh)
        self.addCleanup(os.environ.pop, "GITHUB_OUTPUT", None)
        self.k = 0

    def run_cmd(self, scenario, claude=True, extra=()):
        self.k += 1
        (self.bin_dir / "scenario.json").write_text(json.dumps(scenario))
        out = Path(self.flow.tmp.name) / f"rival_{self.k}"
        argv = ["rival", "--root", str(self.flow.referee), "--pulled", str(self.pulled),
                "--work", str(Path(self.flow.tmp.name) / f"work_{self.k}"), "--out", str(out), *extra]
        if claude:
            argv += ["--claude", str(self.claude)]
        rc = cli.main(argv)
        return rc, json.loads((out / "rival.json").read_text())

    def test_a_refutation_with_a_reproducer_switches_the_reproduce_job_on(self):
        """C01: has_repro=true is what makes the workflow run `reproduce`; no shipped test ever sees it."""
        attempt = {"claim": "c", "evidence_refs": [{"path": "spec/asama-0/00-ozet.md", "line_start": 1, "line_end": 1}],
                   "reproducer": {"cmd": "exit 3", "expect_exit": 3}}
        rc, rival_json = self.run_cmd({"calls": [submit("refuted", [attempt])], "result": ok_result()})
        self.assertEqual((rc, rival_json["verdict"], rival_json["reproducer_count"]), (0, "refuted", 1))
        self.assertIn("has_repro=true", self.gh.read_text())

    def test_the_cli_gets_what_is_left_of_the_budget_and_the_configured_prompt_limit(self):
        """C05 C06"""
        self.flow.state["month_spend_usd_micros"] = 299_900_000   # 0.10 USD left of the 300 USD month
        meta_path = self.pulled / "meta.json"
        meta = json.loads(meta_path.read_text())
        meta["state"] = self.flow.state
        meta_path.write_text(json.dumps(meta))
        self.run_cmd({"calls": [submit()], "result": ok_result()})
        argv = json.loads((self.bin_dir / "seen.json").read_text())["argv"]
        self.assertEqual(argv[argv.index("--max-budget-usd") + 1], "0.100000")
        # the limit comes from limits.max_prompt_chars, not from another number in the same file
        doc = json.loads((self.flow.referee / "bootstrap.json").read_text())
        doc["limits"]["max_prompt_chars"] = 10
        (self.flow.referee / "bootstrap.json").write_text(json.dumps(doc))
        rc, rival_json = self.run_cmd({"calls": [submit()], "result": ok_result()})
        self.assertEqual((rc, rival_json["reasons"]), (0, ["prompt_too_large"]))

    def test_without_claude_the_one_on_path_is_used(self):
        """C07: local/e2e.py --rival runs `rival` without --claude."""
        with mock.patch.dict(os.environ, {"PATH": str(self.bin_dir) + os.pathsep + os.environ["PATH"]}):
            rc, rival_json = self.run_cmd({"calls": [submit()], "result": ok_result()}, claude=False)
        self.assertEqual((rc, rival_json["verdict"]), (0, "not_refuted"))

    def test_a_code_request_gets_the_code_pages_in_its_context(self):
        """C08"""
        meta_path = self.pulled / "meta.json"
        meta = json.loads(meta_path.read_text())
        meta["kind"] = "code"
        meta_path.write_text(json.dumps(meta))
        self.run_cmd({"calls": [submit()], "result": ok_result()})
        stdin = json.loads((self.bin_dir / "seen.json").read_text())["stdin"]
        self.assertIn("Review request: code push", stdin)
        fence = re.search(r"=== ([0-9a-f]{16}) ", stdin).group(1)
        self.assertIn(f'=== {fence} seed page "spec/tohum/04-kod.md" ===', stdin)
        self.assertEqual(stdin, rival.build_context("code", meta["base"], meta["head"], meta["changed"],
                                                    (self.pulled / "diff.patch").read_text(encoding="utf-8"),
                                                    cli._pages((self.pulled / "brain.tar").read_bytes(), "code"),
                                                    fence=fence))

    @posix_only
    def test_a_command_cannot_claim_dockers_own_exit_code(self):
        """E01: 125 means docker failed; the command's 125 becomes 1, every other code and stdin pass through."""
        def run(cmd, stdin=b""):
            env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "SNOWBALL_CMD": cmd}
            return subprocess.run(["sh", "-c", container.RUN], env=env, input=stdin, capture_output=True)
        self.assertEqual(run("exit 125").returncode, 1)
        self.assertEqual(run("exit 3").returncode, 3)
        self.assertEqual(run("exit 0").returncode, 0)
        done = run("cat; echo done", stdin=b"in ")
        self.assertEqual((done.returncode, done.stdout), (0, b"in done" + bytes([10])))
        self.assertIn(container.RUN, container.PRELUDE)
        self.assertNotIn("exec sh", container.PRELUDE)

    def test_a_tree_that_reaches_into_git_metadata_is_neither_hashed_nor_extracted(self):
        """E04, X1: `referee/.git/hooks/pre-commit` in an accepted tree ran as the operator at import."""
        from snowball_bootstrap.treehash import path_problem
        for name, problem in (("referee/.git/hooks/pre-commit", ".git component"), ("a/.GiT/config", ".git component"),
                              ("a" + chr(10) + "b", "control character"), ("a" + chr(127), "control character"),
                              ("a:b", "backslash or colon"), ("a" + chr(92) + "b", "backslash or colon"),
                              ("referee/.gitignore", None), ("referee/x.git", None), ("referee/a.py", None)):
            self.assertEqual(path_problem(name), problem, name)
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w") as tar:
            for member in ("referee/a.py", "referee/.git/hooks/pre-commit"):
                info = tarfile.TarInfo(member)
                info.size, info.mode = 1, 0o755
                tar.addfile(info, io.BytesIO(b"x"))
        with self.assertRaises(TreeError):
            tree_hash(buf.getvalue(), "referee")
        dest = Path(self.flow.tmp.name) / "import_target"
        with self.assertRaises(TreeError):
            extract(buf.getvalue(), dest, 10**6, prefix="referee")
        self.assertFalse((dest / ".git").exists())

    def test_an_unsafe_archive_is_a_stop_not_a_traceback(self):
        """C12"""
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w") as tar:
            info = tarfile.TarInfo("a\\b")
            info.size = 1
            tar.addfile(info, io.BytesIO(b"x"))
        (self.pulled / "brain.tar").write_bytes(buf.getvalue())
        out = Path(self.flow.tmp.name) / "rival_unsafe"
        rc = cli.main(["rival", "--root", str(self.flow.referee), "--pulled", str(self.pulled),
                       "--work", str(Path(self.flow.tmp.name) / "work_unsafe"), "--out", str(out)])
        self.assertEqual(rc, 2)


class ConfigGaps(unittest.TestCase):
    BASE = {"brain_repo": "owner/brain", "brain_branch": "main",
            "image": "docker.io/library/python:3.12-slim@sha256:" + "a" * 64,
            "rival": {"model": "claude-sonnet-5-5", "effort": "medium", "max_turns": 30,
                      "per_run_cap_usd_micros": 3_000_000},
            "limits": {"test_timeout_s": 600, "reproducer_timeout_s": 120, "max_prompt_chars": 600_000,
                       "max_tree_bytes": 50_000_000}}

    def load(self, mutate=lambda d: None, raw=None):
        doc = json.loads(json.dumps(self.BASE))
        mutate(doc)
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "bootstrap.json").write_text(raw if raw is not None else json.dumps(doc))
            return load_bootstrap(Path(tmp))

    def test_a_file_that_is_not_an_object_is_a_config_error_not_a_crash(self):
        """K02"""
        for raw in ("[1]", "[{}]", "[]", '"x"', "5"):
            with self.assertRaises(ConfigError, msg=raw):
                self.load(raw=raw)

    def test_the_hint_names_the_removed_key_and_says_why(self):
        """K01 K04 K05"""
        with self.assertRaisesRegex(ConfigError, r"max_tokens was removed: the rival runs through the claude CLI"):
            self.load(lambda d: d["rival"].update(max_tokens=1))
        with self.assertRaisesRegex(ConfigError, r"price_micros_" r"per_mtok was removed: cost is the CLI's own"):
            self.load(lambda d: d["rival"].update({"price_micros_" + "per_mtok": {}}))
        with self.assertRaises(ConfigError) as ctx:
            self.load(lambda d: d["limits"].update({k: 1 for k in ("zz", "yy", "xx", "ww", "vv", "aa")}))
        self.assertIn("unknown key(s) aa, vv, ww, xx, yy, zz", str(ctx.exception))
        self.assertNotIn("was removed", str(ctx.exception))
        with self.assertRaisesRegex(ConfigError, "unknown key"):
            self.load(lambda d: d["limits"].update(api_key="x"))
        with self.assertRaisesRegex(ConfigError, "unknown key"):
            self.load(lambda d: d["rival"].update(max_tokens=1) or d["rival"].pop("model"))

    def test_every_effort_level_the_cli_knows_loads_and_others_do_not(self):
        """K06"""
        for effort in ("low", "medium", "high", "xhigh", "max"):
            self.assertEqual(self.load(lambda d: d["rival"].update(effort=effort)).rival.effort, effort)
        with self.assertRaisesRegex(ConfigError, "effort"):
            self.load(lambda d: d["rival"].update(effort="extreme"))

    def test_zero_is_not_a_positive_limit(self):
        """K07"""
        for where, key in (("rival", "max_turns"), ("rival", "per_run_cap_usd_micros"), ("limits", "max_prompt_chars")):
            with self.assertRaisesRegex(ConfigError, "must be positive", msg=key):
                self.load(lambda d: d[where].update({key: 0}))

    def test_a_model_with_a_trailing_newline_is_refused(self):
        """K08: `$` also matches before a final newline; the served model could never equal this string."""
        with self.assertRaisesRegex(ConfigError, "full model id"):
            self.load(lambda d: d["rival"].update(model="claude-sonnet-5-5\n"))


def tar_with(name=None, pax_path=None, kind=tarfile.REGTYPE, data=b"x", mode=0o644):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w", format=tarfile.PAX_FORMAT) as tar:
        info = tarfile.TarInfo(name or "placeholder")
        info.type = kind
        info.size = len(data) if kind == tarfile.REGTYPE else 0
        info.mode = mode
        if kind in (tarfile.SYMTYPE, tarfile.LNKTYPE):
            info.linkname = "target"
        if pax_path is not None:
            info.pax_headers = {"path": pax_path}
        tar.addfile(info, io.BytesIO(data) if kind == tarfile.REGTYPE else None)
    return buf.getvalue()


class TreeHardeningGaps(unittest.TestCase):
    def test_a_nul_in_a_pax_path_is_a_tree_error_not_a_value_error(self):
        """T02: tar's own name field cannot hold a NUL, a PAX `path` record can (checked with tarfile itself)."""
        data = tar_with(pax_path="a\x00b")
        self.assertEqual([m.name for m in tarfile.open(fileobj=io.BytesIO(data)).getmembers()], ["a\x00b"])
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(TreeError):
                extract(data, Path(tmp) / "dest", 1000)

    def test_a_name_that_is_not_utf8_is_a_tree_error_that_can_be_reported(self):
        """V3: it crashed `tree_hash` with UnicodeEncodeError, and a message holding it could not be written either."""
        data = tar_with(name="spec/tohum/bad" + chr(0xDCFF) + ".md")
        with self.assertRaises(TreeError) as ctx:
            tree_hash(data, "spec/tohum")
        str(ctx.exception).encode("utf-8")  # a lone surrogate in the message would raise here

    def test_an_archive_that_is_not_one_is_a_tree_error(self):
        """V3: tarfile.ReadError escaped as itself."""
        for data in (b"not a tar", b"x" * 1024):
            with self.assertRaises(TreeError, msg=data[:5]):
                tree_hash(data, "referee")

    def test_unsafe_names_are_refused_by_iter_files_itself_not_only_by_extract(self):
        """T01 T03 T04: hash and import paths use iter_files/tree_hash and never reach extract's resolve check."""
        for name in ("/abs", "a/../b", "x\\y", "a:b"):
            with self.assertRaises(TreeError, msg=name):
                list(iter_files(tar_with(name=name)))
        with self.assertRaises(TreeError):
            tree_hash(tar_with(name="/abs"), "referee")

    def test_the_size_limit_is_inclusive(self):
        """T06"""
        data = tar_with(name="f.txt", data=b"x" * 10)
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(extract(data, Path(tmp) / "ok", 10), 10)
            with self.assertRaises(TreeError):
                extract(data, Path(tmp) / "over", 9)

    def test_every_kind_of_non_regular_member_is_refused(self):
        """T07"""
        for kind in (tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.FIFOTYPE, tarfile.CHRTYPE):
            with tempfile.TemporaryDirectory() as tmp, self.assertRaises(TreeError, msg=kind):
                extract(tar_with(name="n", kind=kind), Path(tmp) / "dest", 100)

    def test_operator_only_names_and_empty_prefix(self):
        """T08 T09"""
        with self.assertRaises(TreeError):
            tree_hash(tar_with(name="referee/policy.json"), "referee")
        with self.assertRaises(TreeError):
            tree_hash(tar_with(name="other/x"), "referee")


class EarlyReturnGaps(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        self.root = base / "tree"
        (self.root / "referee").mkdir(parents=True)
        (self.root / "referee" / "a.py").write_text("x = 1\ny = 2\n")
        self.bin_dir = base / "bin"
        self.bin_dir.mkdir()
        self.claude = install_fake_claude(self.bin_dir)

    def run_with(self, scenario, **kw):
        (self.bin_dir / "scenario.json").write_text(json.dumps(scenario))
        return run_rival(CFG, claude_bin=str(self.claude), seat_prompt="seat", context="ctx", tree_root=self.root,
                         budget_usd_micros=kw.pop("budget", 10_000_000), max_prompt_chars=100_000)

    def test_no_budget_means_no_call_and_no_verdict(self):
        """D03: the earlier test asserted only `reasons == ['budget']`; without the early return the CLI is run with a
        0 USD budget and its not_refuted is kept next to that reason (decide ignores the reasons of a valid verdict)."""
        (self.bin_dir / "seen.json").unlink(missing_ok=True)
        out = self.run_with({"calls": [submit()], "result": ok_result()}, budget=0)
        self.assertEqual((out.verdict, out.reasons), ("unresolved", ["budget"]))
        self.assertFalse((self.bin_dir / "seen.json").exists(), "the CLI must not be started")

    def test_a_failed_run_carries_exactly_one_reason(self):
        """D06: a failed run says why once; an earlier check matched with any(startswith), so a stray second reason passed."""
        out = self.run_with({"garbage": True, "exit": 1})
        self.assertEqual(out.reasons, ["api_error:cli_exit_1"])

    def test_a_verdict_file_the_server_never_validated_is_validated_again(self):
        """D13: the second validation in run_rival is only reached when verdict.json did not come through the server."""
        bad = {"verdict": "refuted", "attempts": []}
        out = self.run_with({"calls": [], "result": ok_result(), "write_verdict_raw": bad})
        self.assertEqual((out.verdict, out.attempts), ("unresolved", []))
        self.assertEqual(out.reasons, ["malformed_verdict:a refutation needs at least one attempt"])

    def test_the_requested_model_is_recorded(self):
        """D23"""
        out = self.run_with({"calls": [submit()], "result": ok_result()})
        self.assertEqual(out.as_dict()["model_requested"], "claude-sonnet-5-5")


if __name__ == "__main__":
    unittest.main()
