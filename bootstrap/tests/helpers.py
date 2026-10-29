"""Test doubles for the outside world: the container runtime and git remotes."""

from __future__ import annotations

import json
import math
import shlex
import stat
import subprocess
import sys
import textwrap
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import os
import unittest

from snowball_bootstrap.canon import row_hash
from snowball_bootstrap.container import RunResult
from snowball_bootstrap.rival import TOOL_NAMES

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "drill"))
from snowball_drill import judge as drill_judge  # noqa: E402  (reference judge, `tohum/29c`)

# ---------------------------------------------------------------- reference founder implementation


def _beta_cdf(a: float, b: float, x: float, steps: int = 4000) -> float:
    """Regularized incomplete beta by Simpson's rule in log space (reference only)."""
    if x <= 0:
        return 0.0
    if x >= 1:
        return 1.0
    lb = math.lgamma(a) + math.lgamma(b) - math.lgamma(a + b)

    def f(t: float) -> float:
        if t <= 0 or t >= 1:
            return 0.0
        return math.exp((a - 1) * math.log(t) + (b - 1) * math.log(1 - t) - lb)

    h = x / steps
    s = f(0) + f(x)
    for i in range(1, steps):
        s += (4 if i % 2 else 2) * f(i * h)
    return s * h / 3


def cp_lower(x: float, n: int, alpha: float) -> float:
    if x <= 0:
        return 0.0
    if x >= n:
        return alpha ** (1 / n)
    lo, hi = 0.0, 1.0
    for _ in range(60):
        mid = (lo + hi) / 2
        if _beta_cdf(x, n - x + 1, mid) > alpha:
            hi = mid
        else:
            lo = mid
    return lo


def mcnemar(b: int, c: int) -> float:
    m = b + c
    return sum(math.comb(m, k) for k in range(c, m + 1)) / 2 ** m


def score(findings: list[dict], cases: list[dict]) -> int:
    hits, used = 0, set()
    for case in cases:
        for i, f in enumerate(findings):
            if i in used:
                continue
            if (f.get("tool") == case.get("tool") and f.get("rule_id") == case.get("rule_id")
                    and any(ref["path"] == tp["path"] and any(h["start"] <= ref["line_start"] <= h["end"]
                                                              for h in tp["hunks"])
                            for ref in f["evidence_refs"] for tp in case["touched_paths"])):
                hits += 1
                used.add(i)
                break
    return hits


def verify_file(path: Path) -> dict[str, Any]:
    prev = "0" * 64
    for line in path.read_text().splitlines():
        row = json.loads(line)
        if row["prev_hash"] != prev or row_hash(row) != row["row_hash"]:
            return {"valid": False, "broken_row": row["row_id"]}
        prev = row["row_hash"]
    return {"valid": True}


@dataclass
class FakeRunner:
    """Emulates the container: answers the vector interface with a reference implementation.

    ``vec_dir`` stands in for the /vec mount. ``wrong`` names behaviours to break on purpose.
    ``commands`` maps other commands to (exit, stdout).
    """

    vec_dir: Path
    wrong: set[str] = field(default_factory=set)
    commands: dict[str, tuple[int, bytes]] = field(default_factory=dict)
    calls: list[tuple[str, str]] = field(default_factory=list)

    def run(self, cmd: str, *, cwd: str = ".", stdin: bytes = b"", timeout_s: int) -> RunResult:
        self.calls.append((cmd, cwd))
        if cmd in self.commands:
            code, out = self.commands[cmd]
            return RunResult(code, out, b"", 1)
        argv = shlex.split(cmd)

        def ok(value: dict) -> RunResult:
            return RunResult(0, (json.dumps(value) + "\n").encode(), b"", 1)

        if argv[:3] == ["python", "-m", "ledger.chain"]:
            if argv[3] == "hash":
                row = json.loads(stdin)
                if "chain_ignores_input" in self.wrong:
                    return ok({"row_hash": "3bae91580aca99362572e9f5f41b3e46c2bc0c29236f72e867faa5cd46ca603a"})
                return ok({"row_hash": row_hash(row)})
            if argv[3] == "verify":
                path = self.vec_dir / argv[4].removeprefix("/vec/")
                if "verify_always_valid" in self.wrong:
                    return ok({"valid": True})
                return ok(verify_file(path))
        if argv[:3] == ["python", "-m", "harness.stats"]:
            if argv[3] == "cp_lower":
                x, n, alpha = float(argv[4]), int(argv[5]), float(argv[6])
                lb = cp_lower(x, n, alpha)
                if "cp_wilson" in self.wrong:
                    lb = lb + 0.01
                return ok({"lb": f"{lb:.6f}"})
            if argv[3] == "mcnemar":
                return ok({"p": f"{mcnemar(int(argv[4]), int(argv[5])):.6f}"})
        if argv[:3] == ["python", "-m", "harness.score"]:
            findings = json.loads((self.vec_dir / argv[3].removeprefix("/vec/")).read_text())
            cases = json.loads((self.vec_dir / argv[4].removeprefix("/vec/")).read_text())
            hits = score(findings, cases)
            if "score_counts_twice" in self.wrong:
                hits = len(cases)
            return ok({"hits": hits})
        if argv[:4] == ["python", "-m", "harness.drill", "judge"]:
            doc = json.loads((self.vec_dir / argv[4].removeprefix("/vec/")).read_text())
            if "drill_ignores_commitment" in self.wrong:
                doc["commitment_sha256"] = drill_judge.commitment(doc["answer_key"])
            result = drill_judge.judge(doc)
            if "drill_lenient" in self.wrong:
                result = {"drill": "PASS", "verdicts": {q: "PASS" for q in drill_judge.QUESTIONS}}
            return ok(result)
        if cmd == "exit 0":
            return RunResult(0, b"", b"", 1)
        return RunResult(1, b"", b"unknown command", 1)


posix_only = unittest.skipIf(os.name == "nt", "needs a POSIX shell (shebang scripts, symlinks, /bin/false)")


# ---------------------------------------------------------------- the claude CLI double

# A stand-in for the `claude` binary. It reads the real argv, starts the MCP server named in
# --mcp-config, speaks the real protocol to it with the scripted tool calls, and prints the stream a
# real `claude -p --output-format stream-json` run would print.
FAKE_CLAUDE = textwrap.dedent('''\
    #!{python}
    import json, os, subprocess, sys, time
    here = os.path.dirname(os.path.abspath(__file__))
    scenario = json.load(open(os.path.join(here, "scenario.json")))
    argv = sys.argv[1:]
    mcp_cfg = json.load(open(argv[argv.index("--mcp-config") + 1]))["mcpServers"]["snowball"] if "--mcp-config" in argv else {{}}
    open(os.path.join(here, "claude.pid"), "w").write(str(os.getpid()))
    stdin = sys.stdin.buffer.read()
    system_path = argv[argv.index("--system-prompt-file") + 1] if "--system-prompt-file" in argv else None
    pinned = ("DISABLE_AUTOUPDATER", "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC", "CLAUDE_CODE_DISABLE_AUTO_MEMORY",
              "CLAUDE_CODE_NO_MODEL_FALLBACK")
    json.dump({{"argv": argv, "stdin": stdin.decode("utf-8", "replace"), "stdin_hex": stdin.hex(),
                "cwd": os.getcwd(), "mcp_args": mcp_cfg.get("args"), "env": sorted(os.environ), "env_values": {{k: os.environ.get(k) for k in pinned}},
                "system_hex": open(system_path, "rb").read().hex() if system_path else None}},
              open(os.path.join(here, "seen.json"), "w"))
    if scenario.get("grandchild"):
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
        open(os.path.join(here, "grandchild.pid"), "w").write(str(child.pid))
    if scenario.get("sleep"):
        time.sleep(scenario["sleep"])
    if scenario.get("garbage"):
        print("not json"); sys.exit(1)
    cfg = mcp_cfg
    proc = subprocess.Popen([cfg["command"]] + cfg["args"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    def rpc(i, method, params=None):
        proc.stdin.write(json.dumps({{"jsonrpc": "2.0", "id": i, "method": method, "params": params or {{}}}}) + "\\n")
        proc.stdin.flush()
        return json.loads(proc.stdout.readline())
    rpc(0, "initialize", {{"protocolVersion": "2024-11-05"}})
    listed = rpc(1, "tools/list")["result"]["tools"]
    replies = []
    for n, (name, args) in enumerate(scenario.get("calls", []), start=2):
        replies.append(rpc(n, "tools/call", {{"name": name, "arguments": args}})["result"])
    proc.stdin.close(); proc.wait()
    if scenario.get("write_verdict_raw") is not None:  # a verdict file that did not come through the server
        open(cfg["args"][cfg["args"].index("--verdict-out") + 1], "w").write(json.dumps(scenario["write_verdict_raw"]))
    json.dump({{"tools": [t["name"] for t in listed], "replies": replies}}, open(os.path.join(here, "mcp.json"), "w"))
    if scenario.get("raw") is not None:
        sys.stdout.buffer.write(scenario["raw"].encode("utf-8")); sys.stdout.flush(); sys.exit(scenario.get("exit", 0))
    if scenario.get("raw_hex") is not None:
        sys.stdout.buffer.write(bytes.fromhex(scenario["raw_hex"])); sys.stdout.flush(); sys.exit(scenario.get("exit", 0))
    events = scenario.get("events")
    if events is None:
        result = scenario.get("result", {{}})
        allowed = [a.split("=", 1)[1] for a in argv if a.startswith("--allowedTools=")]
        init = scenario.get("init", {{"type": "system", "subtype": "init", "model": "x", "apiKeySource": "none",
                                      "tools": allowed[0].split(",") if allowed else [], "skills": [],
                                      "slash_commands": [],
                                      "mcp_servers": [{{"name": "snowball", "status": "connected"}}]}})
        usage = result.get("modelUsage", {{}}) if isinstance(result, dict) else {{}}
        models = scenario.get("api_models", list(usage) if isinstance(usage, dict) else [])
        events = ([init] if init is not None else []) + [
            {{"type": "assistant", "message": {{"model": m, "content": [{{"type": "text"}}]}}}} for m in models]
        events.append(result)
    for event in events:
        print(json.dumps(event))
    sys.exit(scenario.get("exit", 0))
''')


def ok_result(model="claude-sonnet-5-5", **extra):
    result = {"type": "result", "subtype": "success", "is_error": False, "num_turns": 3,
              "total_cost_usd": 0.0123, "stop_reason": "end_turn", "terminal_reason": "completed",
              "modelUsage": {model: {"costUSD": 0.0123}}}
    result.update(extra)
    return result


def submit(verdict="not_refuted", attempts=None):
    return ["submit_verdict", {"verdict": verdict, "attempts": attempts or []}]


def good_init(**over):
    """The init event of a correctly isolated run (shape recorded from the real CLI)."""
    init = {"type": "system", "subtype": "init", "model": "x", "apiKeySource": "none", "skills": [],
            "slash_commands": [], "tools": list(TOOL_NAMES), "mcp_servers": [{"name": "snowball", "status": "connected"}]}
    init.update(over)
    return init


def install_fake_claude(bin_dir: Path) -> Path:
    """A POSIX shebang script, or on Windows a claude.cmd that runs the same script like the real npm shim."""
    script = bin_dir / ("fake_claude.py" if os.name == "nt" else "claude")
    script.write_text(FAKE_CLAUDE.format(python=sys.executable))
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    if os.name != "nt":
        return script
    shim = bin_dir / "claude.cmd"
    shim.write_bytes(("@echo off" + chr(13) + chr(10) + f'"{sys.executable}" "{script}" %*' + chr(13) + chr(10)).encode())
    return shim


def process_alive(pid: int) -> bool:
    if os.name == "nt":
        listing = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True).stdout
        return str(pid) in listing.split()
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    try:  # a dead child nobody has reaped yet (no init in the container) still answers kill(pid, 0)
        with open(f"/proc/{pid}/stat") as handle:
            return handle.read().rsplit(")", 1)[1].split()[0] != "Z"
    except OSError:
        return True


# ---------------------------------------------------------------- git helpers


def sh(cwd: Path, *argv: str) -> str:
    return subprocess.run(argv, cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def make_repo(path: Path, files: dict[str, str]) -> str:
    path.mkdir(parents=True, exist_ok=True)
    sh(path, "git", "init", "-q", "-b", "main")
    sh(path, "git", "config", "user.email", "t@example.invalid")
    sh(path, "git", "config", "user.name", "t")
    return commit(path, files, "seed")


def commit(path: Path, files: dict[str, str | None], message: str) -> str:
    for rel, content in files.items():
        target = path / rel
        if content is None:
            target.unlink()
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
    sh(path, "git", "add", "-A")
    sh(path, "git", "commit", "-q", "-m", message)
    return sh(path, "git", "rev-parse", "HEAD")
