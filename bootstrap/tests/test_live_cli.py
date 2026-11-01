"""The real `claude` CLI against the contract rival.py relies on. Runs only where the CLI is installed.

No model call is made and nothing is spent: the CLI is run with a made-up token, so the API answers 401.
That is enough to tell a drifted contract from a healthy one, because the CLI only prints the result
this module parses when it accepted every flag in `_cli_argv`.
"""

import json
import os
import re
import shlex
import subprocess
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from unittest import mock

from snowball_bootstrap import rival
from snowball_bootstrap.config import RivalConfig

from helpers import definition, load_brain_defs, tree_repo

PIN_FILE = Path(__file__).resolve().parents[1] / "requirements" / "claude-cli" / "package.json"
ENTRYPOINT = Path(__file__).resolve().parents[2] / "founder" / "entrypoint.sh"
CLAUDE = rival.resolve_claude(None)
CFG = RivalConfig(model="claude-sonnet-5-5", effort="medium", max_turns=5, per_run_cap_usd_micros=1_000_000)
# Flags the CLI accepts but leaves out of `claude --help` (verified against 2.1.293).
HIDDEN_FLAGS = {"--system-prompt-file", "--max-turns"}
DENIED = {"RemoteTrigger", "CronCreate", "CronDelete", "CronList"}  # E380
# The default tools the Founder keeps. A signed-out CLI never offers WebFetch (nor RemoteTrigger), with the flag or
# without it (2.1.293 on Windows and in the capsule's image); under a login it does, and the flag drops RemoteTrigger
# only (checked with the API pointed at a closed port, E380). So a made-up token checks the rest.
KEPT = {"Bash", "Read", "Write", "Edit", "Task", "Workflow", "WebSearch", "ScheduleWakeup", "ToolSearch", "TaskStop",
        "ListAgents"}
SIGNED_IN_ONLY = {"WebFetch"}
# On Linux, the capsule's platform, the session lists no Glob or Grep (its Bash searches; on Windows it does), yet a
# brain agent that names them gets them (CapsuleBrainDefinitionsTest, 2.1.293 in the capsule's image).
SEARCH_TOOLS = {"Glob", "Grep"}


def entrypoint_argv(claude: str, config_dir: Path, deny: bool = True) -> list[str]:
    """The capsule's own `claude -p` call from entrypoint.sh, its shell defaults filled in and a one-word prompt; with
    deny=False, without its --disallowedTools (the control: the tools the flag removes are there without it)."""
    text = ENTRYPOINT.read_text(encoding="utf-8")
    call = text[text.index("claude -p "):text.index('> "/work/logs/session-')]
    call = re.sub(r"\$\{\w+:-([^}]*)\}", r"\1", call.replace("\\\n", " ").replace("\\\r\n", " "))
    argv = [arg.replace("$CLAUDE_CONFIG_DIR", str(config_dir)) for arg in shlex.split(call)]
    argv[argv.index("-p") + 1] = "hello"  # was "$(cat /opt/founder/prompt.md)"
    if not deny:
        i = argv.index("--disallowedTools")
        del argv[i:i + 2]
    return [claude, *argv[1:]]


def init_event(argv: list[str], env: dict[str, str], cwd: Path) -> dict:
    """The CLI's init event; the CLI (behind a Windows .cmd shim too) is killed as soon as it is printed, before its
    first request."""
    group = {"start_new_session": True} if os.name != "nt" else {}
    proc = subprocess.Popen(argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL, text=True, encoding="utf-8", errors="replace", **group)
    try:
        for line in proc.stdout:
            if line.startswith("{"):
                event = json.loads(line)
                if event.get("type") == "system" and event.get("subtype") == "init":
                    return event
        raise AssertionError("the CLI printed no init event")
    finally:
        rival._kill_tree(proc)
        proc.wait()
        proc.stdout.close()


def init_tools(argv: list[str], env: dict[str, str], cwd: Path) -> list[str]:
    """The tools the CLI's init event names."""
    return sorted(map(str, init_event(argv, env, cwd).get("tools") or []))


class LocalApi:
    """A Messages API on 127.0.0.1 that records every request body; `answer(n, body)` gives the n-th request's
    server-sent events, or None for a 401. The CLI is pointed at it (ANTHROPIC_BASE_URL): nothing leaves the machine
    and no model is called, so what the model would be shown, a subagent's own request included, is read here."""

    def __init__(self, answer=lambda n, body: None):
        self.bodies: list[dict] = []
        self.changed = threading.Condition()
        api = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                raw = self.rfile.read(int(self.headers.get("content-length") or 0))
                if not self.path.startswith("/v1/messages") or "count_tokens" in self.path:
                    self.send_response(404)
                    self.end_headers()
                    return
                body = json.loads(raw or b"{}")
                with api.changed:
                    n = len(api.bodies)
                    api.bodies.append(body)
                    api.changed.notify_all()
                events = answer(n, body)
                self.send_response(401 if events is None else 200)
                self.send_header("content-type", "application/json" if events is None else "text/event-stream")
                self.end_headers()
                self.wfile.write(b'{"type":"error","error":{"type":"authentication_error","message":"made-up"}}'
                                 if events is None else
                                 "".join(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n" for e in events).encode())

            def log_message(self, *args):
                pass

        self.handler = Handler

    def run(self, argv: list[str], env: dict[str, str], cwd: Path, done, timeout: float = 180) -> list[dict]:
        """The request bodies once done(bodies) holds; the CLI is then killed."""
        server = HTTPServer(("127.0.0.1", 0), self.handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        group = {"start_new_session": True} if os.name != "nt" else {}
        proc = subprocess.Popen(argv, cwd=cwd, env={**env, "ANTHROPIC_BASE_URL": f"http://127.0.0.1:{server.server_port}"},
                                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **group)
        try:
            with self.changed:
                if not self.changed.wait_for(lambda: done(self.bodies), timeout):
                    raise AssertionError(f"the CLI sent {len(self.bodies)} model requests, not the ones awaited")
                return list(self.bodies)
        finally:
            rival._kill_tree(proc)
            proc.wait()
            server.shutdown()
            server.server_close()


def assistant(blocks: list[dict], stop: str) -> list[dict]:
    """One streamed assistant message of these content blocks (each a list of its own events)."""
    start = {"type": "message_start", "message": {"id": "msg_local", "type": "message", "role": "assistant",
             "model": "claude-opus-5-5", "content": [], "stop_reason": None, "stop_sequence": None,
             "usage": {"input_tokens": 1, "output_tokens": 1}}}
    return [start, *blocks, {"type": "message_delta", "delta": {"stop_reason": stop, "stop_sequence": None},
                             "usage": {"output_tokens": 1}}, {"type": "message_stop"}]


def agent_call(index: int, agent: str) -> list[dict]:
    """The content block of an `Agent` tool call that starts the subagent `agent` in the foreground."""
    args = json.dumps({"description": "probe", "prompt": "Say done.", "subagent_type": agent, "run_in_background": False})
    return [{"type": "content_block_start", "index": index,
             "content_block": {"type": "tool_use", "id": f"toolu_local_{index}", "name": "Agent", "input": {}}},
            {"type": "content_block_delta", "index": index, "delta": {"type": "input_json_delta", "partial_json": args}},
            {"type": "content_block_stop", "index": index}]


def text_block(text: str) -> list[dict]:
    return [{"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
            {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": text}},
            {"type": "content_block_stop", "index": 0}]


def request_text(body: dict) -> str:
    """Every text block of a request's messages and system prompt, one string."""
    parts = [block.get("text", "") for block in body.get("system") or [] if isinstance(block, dict)]
    for message in body.get("messages") or []:
        content = message.get("content")
        parts += [content] if isinstance(content, str) else [b.get("text", "") for b in content if isinstance(b, dict)]
    return "\n".join(parts)


def cli_env(**extra: str) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith(("ANTHROPIC_", "CLAUDE_"))}
    env.update(extra)
    return env


@unittest.skipUnless(CLAUDE, "the claude CLI is not on PATH")
class LiveCliContractTest(unittest.TestCase):
    def test_a_signed_out_cli_reports_an_outage_the_way_rival_py_expects(self):
        with tempfile.TemporaryDirectory() as tmp:
            tree = Path(tmp) / "tree"
            tree.mkdir()
            (tree / "a.py").write_text("x = 1" + chr(10))
            env = {"CLAUDE_CODE_OAUTH_TOKEN": "not-a-real-token", "CLAUDE_CONFIG_DIR": str(Path(tmp) / "cfg")}
            installed = subprocess.run([CLAUDE, "--version"], capture_output=True, text=True).stdout.split()[0]
            with mock.patch.dict(os.environ, env):  # the installed CLI may be newer than the pin: judge its contract
                out = rival.run_rival(CFG, claude_bin=CLAUDE, seat_prompt="seat", context="context", tree_root=tree,
                                      budget_usd_micros=1_000_000, max_prompt_chars=100_000, pinned_version=installed)
        # A renamed flag or a changed output format gives cli_exit_N or bad_cli_result instead.
        self.assertEqual(out.verdict, "unresolved")
        self.assertEqual(len(out.reasons), 1, out.reasons)
        self.assertRegex(out.reasons[0], r"^api_error:(http_[0-9]+|not_logged_in|unknown)$", out.reasons)
        self.assertEqual(out.cost_usd_micros, 0)

    def test_every_visible_flag_in_use_is_still_in_the_help(self):
        helptext = subprocess.run([CLAUDE, "--help"], capture_output=True, text=True, encoding="utf-8").stdout
        with tempfile.TemporaryDirectory() as tmp:
            argv = rival._cli_argv(CLAUDE, CFG, Path(tmp), Path(tmp), 1_000_000)
        flags = {arg.split("=", 1)[0] for arg in argv if arg.startswith("--")}
        self.assertTrue(flags - HIDDEN_FLAGS)
        for flag in sorted(flags - HIDDEN_FLAGS):
            self.assertIn(flag, helptext, f"{flag} is no longer documented by `claude --help`")

    def test_the_installed_version_is_the_pinned_one(self):
        pin = json.loads(PIN_FILE.read_text())["dependencies"]["@anthropic-ai/claude-code"]
        version = subprocess.run([CLAUDE, "--version"], capture_output=True, text=True).stdout.split()[0]
        if version != pin:
            self.skipTest(f"claude {version} is installed, the pin is {pin}; the contract tests above still apply")


@unittest.skipUnless(CLAUDE, "the claude CLI is not on PATH")
class CapsuleToolSurfaceTest(unittest.TestCase):  # E380
    """The Founder's own call (entrypoint.sh) against the real CLI, with a made-up token: nothing reaches a model."""

    def tools(self, deny: bool) -> list[str]:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            cfg, cwd = Path(tmp) / "cfg", Path(tmp) / "cwd"
            cfg.mkdir()
            cwd.mkdir()
            (cfg / "no-mcp.json").write_text('{"mcpServers":{}}\n', encoding="utf-8")
            env = cli_env(**rival.PINNED_ENV, CLAUDE_CODE_OAUTH_TOKEN="not-a-real-token", CLAUDE_CONFIG_DIR=str(cfg))
            return init_tools(entrypoint_argv(CLAUDE, cfg, deny), env, cwd)

    def test_the_four_are_gone_and_the_founders_tools_stay(self):
        tools = set(self.tools(deny=True))
        self.assertEqual(tools & DENIED, set(), sorted(tools))
        self.assertEqual(KEPT - tools, set(), sorted(tools))

    def test_the_flag_is_what_removes_them(self):  # the control: without it the CLI offers the Cron tools
        without = set(self.tools(deny=False))
        self.assertLessEqual({"CronCreate", "CronDelete", "CronList"}, without, sorted(without))
        self.assertEqual(set(self.tools(deny=True)), without - DENIED)

    def test_an_agent_of_the_brain_may_name_every_tool_the_session_has_and_no_other(self):  # E450
        tools, allowed = set(self.tools(deny=True)), load_brain_defs().ALLOWED_TOOLS
        self.assertLessEqual(tools, allowed, sorted(tools - allowed))
        self.assertLessEqual(allowed - tools, {"Agent"} | SIGNED_IN_ONLY | SEARCH_TOOLS, sorted(allowed - tools))

    @unittest.skipUnless(os.environ.get("SNOWBALL_CLI_LOGIN") == "1",
                         "set SNOWBALL_CLI_LOGIN=1 to check the signed-in tool set with your own login")
    def test_signed_in_the_flag_drops_remote_trigger_and_keeps_web_fetch(self):
        """Opt-in, the operator's own login: the API is pointed at a closed port and the CLI is killed at init, so no
        request leaves the machine. A custom API address turns ToolSearch off, so it is not asked for here."""
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            (Path(tmp) / "no-mcp.json").write_text('{"mcpServers":{}}\n', encoding="utf-8")
            env = {k: v for k, v in os.environ.items() if not k.startswith("ANTHROPIC_")
                   and k != "CLAUDE_CODE_OAUTH_TOKEN"}
            env.update(rival.PINNED_ENV, ANTHROPIC_BASE_URL="http://127.0.0.1:9")
            argv = entrypoint_argv(CLAUDE, Path(tmp))
            tools = set(init_tools(argv, env, Path(tmp)))
            without = set(init_tools(entrypoint_argv(CLAUDE, Path(tmp), deny=False), env, Path(tmp)))
        self.assertIn("RemoteTrigger", without)
        self.assertEqual(tools & DENIED, set())
        self.assertEqual((KEPT | SIGNED_IN_ONLY) - {"ToolSearch"} - tools, set(), sorted(tools))
        allowed = load_brain_defs().ALLOWED_TOOLS  # E450: signed in too, an agent of the brain may name each of them
        self.assertLessEqual(tools, allowed, sorted(tools - allowed))


REVIEWER = 'Reviews: "quoted" code, a\\b, ç ş ğ ı İ # not a comment'
PROBE = "Probe: türkçe açıklama, iki nokta: tamam"
NEVER_SHOWN = "Instructions this session must never be shown."


@unittest.skipUnless(CLAUDE, "the claude CLI is not on PATH")
class CapsuleBrainDefinitionsTest(unittest.TestCase):  # E450, owner 2026-11-01
    """The capsule's loader (brain_defs.py) on a brain with three agents and a skill, then the capsule's own `claude -p`
    call (entrypoint.sh, its `--plugin-dir` included) against the real CLI with a made-up token: what the init event
    lists, what the first model request (to 127.0.0.1) shows the model, and the tools a brain agent's subagent gets."""

    BRAIN = {
        "agents/reviewer.md": definition("reviewer", json.dumps(REVIEWER, ensure_ascii=False), "You are the reviewer probe.\n",
                                         extra={"tools": "Read, Grep, Glob"}),
        "agents/scheduler.md": definition("scheduler", extra={"tools": "Read, CronCreate"}),
        "agents/wide.md": definition("wide", "Has the session's tools.", "You are the wide probe.\n"),
        "skills/probe/SKILL.md": definition("probe", PROBE, body="Run the probe.\n"),
        "skills/probe/notes.md": b"notes\n",
        "CLAUDE.md": NEVER_SHOWN.encode("utf-8") + b"\n",
    }

    def setUp(self):
        tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        cfg, self.cwd = root / "cfg", root / "brain"
        cfg.mkdir()
        (cfg / "no-mcp.json").write_text('{"mcpServers":{}}\n', encoding="utf-8")
        tree_repo(self.cwd, self.BRAIN)
        (self.cwd / "CLAUDE.md").write_bytes(self.BRAIN["CLAUDE.md"])  # checked out where the session runs, as in /work/brain
        self.assertEqual(load_brain_defs().main([str(self.cwd), str(cfg / "brain-plugin"),
                                                 str(root / "brain-definitions.json")]), 0)
        self.record = json.loads((root / "brain-definitions.json").read_text(encoding="utf-8"))
        self.argv = entrypoint_argv(CLAUDE, cfg)
        self.env = cli_env(**rival.PINNED_ENV, CLAUDE_CODE_OAUTH_TOKEN="not-a-real-token", CLAUDE_CONFIG_DIR=str(cfg))

    def test_the_init_event_lists_the_brains_agent_and_skill_and_not_the_agent_with_a_denied_tool(self):
        event = init_event(self.argv, self.env, self.cwd)
        self.assertEqual([a for a in event.get("agents") or [] if a.startswith("brain:")], ["brain:reviewer", "brain:wide"])
        self.assertEqual([s for s in event.get("skills") or [] if s.startswith("brain:")], ["brain:probe"])
        self.assertIn("brain", [p.get("name") for p in event.get("plugins") or []])
        self.assertEqual(set(event.get("tools") or []) & DENIED, set())
        self.assertEqual(self.record["skipped"], [{"path": "agents/scheduler.md", "reasons": ["tool_denied:CronCreate"]}])
        self.assertEqual([a["loaded_as"] for a in self.record["agents"]], ["brain:reviewer", "brain:wide"])

    def test_the_model_is_shown_them_as_the_record_says_and_nothing_else_of_the_brain(self):
        text = request_text(LocalApi().run(self.argv, self.env, self.cwd, done=lambda bodies: bodies)[0])
        self.assertIn(f"- brain:reviewer: {REVIEWER} (Tools: Read, Grep, Glob)", text)  # quotes, '#', ':', tools as written
        self.assertIn(f"- brain:probe: {PROBE}", text)
        self.assertNotIn("brain:scheduler", text)
        self.assertNotIn(NEVER_SHOWN, text)  # the clone's CLAUDE.md: setting sources stay off

    def test_a_brain_agent_gets_only_its_own_tools_and_never_the_denied_four(self):
        """The first request is answered with two `Agent` calls; each subagent's own first request names its tools."""
        def answer(n, body):
            if n == 0:
                return assistant([*agent_call(0, "brain:reviewer"), *agent_call(1, "brain:wide")], "tool_use")
            return assistant(text_block("done"), "end_turn")

        def subagent(bodies, marker):
            return next((b for b in bodies if marker in request_text(b)), None)

        markers = ("You are the reviewer probe.", "You are the wide probe.")
        bodies = LocalApi(answer).run(self.argv, self.env, self.cwd,
                                      done=lambda bodies: all(subagent(bodies, m) for m in markers))
        reviewer, wide = ({t["name"] for t in subagent(bodies, m).get("tools") or []} for m in markers)
        self.assertEqual(reviewer, {"Read", "Grep", "Glob"})  # its `tools`, as the CLI enforces them (SEARCH_TOOLS too)
        self.assertIn("Bash", wide)  # without `tools`: the session's
        self.assertEqual(wide & DENIED, set())
        self.assertLessEqual(wide, load_brain_defs().ALLOWED_TOOLS, sorted(wide))
        self.assertEqual({t["name"] for t in bodies[0].get("tools") or []} & DENIED, set())


if __name__ == "__main__":
    unittest.main()
