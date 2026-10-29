"""Stdio MCP server that gives the seed rival (`tohum/29`) its four tools.

The ``claude`` CLI spawns it for exactly one rival run (see ``rival.run_rival``). The model reaches
the extracted tree only through ``read_file``, ``grep`` and ``glob`` here, and every result passes
the secret scan before it leaves. ``submit_verdict`` writes the raw submission to a file; the
bootstrap validates it afterwards, so a malformed verdict is still ``unresolved`` and never
acceptance. Nothing here talks to the network.

Run as a script under ``python -I`` so the directory of this file is not put on ``sys.path``.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import signal
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from snowball_bootstrap import secretscan
    from snowball_bootstrap.rival import SecretWithheld, TOOLS, ToolBox, validate_verdict
else:
    from . import secretscan
    from .rival import SecretWithheld, TOOLS, ToolBox, validate_verdict

PROTOCOL_VERSION = "2024-11-05"
READ_TOOLS = ("read_file", "grep", "glob")
MAX_INVALID_SUBMISSIONS = 3
TOOL_TIMEOUT_S = 20


class _Deadline(BaseException):
    """Not an Exception, and above all not an OSError: pathlib's directory walk swallows OSError and would
    silently spend the one-shot timer, leaving the call without any limit."""


@contextmanager
def _deadline(seconds: float) -> Iterator[None]:
    """Interrupt a tool call that runs too long (a model-chosen regex can take minutes). POSIX only: the
    interval timer does not exist on Windows, where the CLI's own timeout and process-tree kill remain."""
    if not hasattr(signal, "setitimer"):
        yield
        return

    def expired(signum: int, frame: Any) -> None:
        raise _Deadline

    previous = signal.signal(signal.SIGALRM, expired)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


class RivalServer:
    def __init__(self, box: ToolBox, verdict_path: Path, stats_path: Path, tool_timeout_s: float = TOOL_TIMEOUT_S):
        self.box = box
        self.tool_timeout_s = tool_timeout_s
        self.verdict_path = verdict_path
        self.stats_path = stats_path
        self.withheld = 0
        self.submitted = False
        self.invalid = 0
        self.last_invalid = ""

    def _write_stats(self) -> None:
        tmp = self.stats_path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"withheld": self.withheld, "last_invalid": self.last_invalid}), encoding="utf-8")
        os.replace(tmp, self.stats_path)

    def call(self, name: str, args: Any) -> tuple[str, bool]:
        """Run one tool; returns (text, is_error)."""
        args = args if isinstance(args, dict) else {}
        if name == "submit_verdict":
            if self.submitted:
                return "error: a verdict was already submitted", True
            if self.invalid >= MAX_INVALID_SUBMISSIONS:
                return "error: too many invalid submissions; no further verdict is accepted", True
            try:
                with _deadline(self.tool_timeout_s):
                    validate_verdict(args, self.box)
            except _Deadline:
                return f"error: checking the verdict took longer than {self.tool_timeout_s:g} s", True
            except ValueError as exc:
                self.invalid += 1
                self.last_invalid = str(exc)[:300]
                self._write_stats()
                return f"error: invalid verdict: {exc}. Correct it and call submit_verdict again.", True
            self.submitted = True
            tmp = self.verdict_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(args), encoding="utf-8")
            os.replace(tmp, self.verdict_path)
            return "verdict recorded; stop here", False
        if name not in READ_TOOLS:
            return f"error: unknown tool {name}", True
        try:
            with _deadline(self.tool_timeout_s):
                if name == "read_file":
                    text = self.box.read_file(args.get("path"), args.get("start_line", 1), args.get("end_line"))
                elif name == "grep":
                    text = self.box.grep(args.get("pattern"), args.get("path_prefix", ""))
                else:
                    text = self.box.glob(args.get("pattern"))
        except _Deadline:
            self._write_stats()
            return f"error: the call took longer than {self.tool_timeout_s:g} s and was stopped", True
        except SecretWithheld as exc:
            self.withheld += 1
            self._write_stats()
            return str(exc), True
        except Exception as exc:  # whatever a tool raises is an error result, never the end of the session
            self._write_stats()
            return f"error: {exc}", True
        if secretscan.scan(text):  # file contents were checked whole in ToolBox; this guards what it cannot see, e.g. a file name
            self.withheld += 1
            self._write_stats()
            return "withheld: the result matched a secret pattern", True
        self._write_stats()
        return text, False

    def handle(self, msg: dict[str, Any]) -> dict[str, Any] | None:
        mid, method = msg.get("id"), msg.get("method")
        if mid is None:  # notifications need no reply
            return None
        params = msg.get("params")
        params = params if isinstance(params, dict) else {}
        if method == "initialize":
            version = params.get("protocolVersion") or PROTOCOL_VERSION
            result: dict[str, Any] = {"protocolVersion": version, "capabilities": {"tools": {}},
                                      "serverInfo": {"name": "snowball", "version": "1"}}
        elif method == "ping":
            result = {}
        elif method == "tools/list":
            result = {"tools": [{"name": t["name"], "description": t["description"],
                                 "inputSchema": t["input_schema"]} for t in TOOLS]}
        elif method == "tools/call":
            text, is_error = self.call(str(params.get("name")), params.get("arguments"))
            result = {"content": [{"type": "text", "text": text}], "isError": is_error}
        else:
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": "method not found"}}
        return {"jsonrpc": "2.0", "id": mid, "result": result}


def serve(server: RivalServer, stdin: Any, stdout: Any) -> None:
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except (ValueError, RecursionError):
            continue
        if not isinstance(msg, dict):
            continue
        try:
            reply = server.handle(msg)
        except Exception as exc:  # one bad request must not end the run
            mid = msg.get("id")
            reply = None if mid is None else {"jsonrpc": "2.0", "id": mid,
                                              "error": {"code": -32603, "message": type(exc).__name__}}
        if reply is not None:
            stdout.write(json.dumps(reply) + "\n")
            stdout.flush()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tree", required=True)
    parser.add_argument("--verdict-out", required=True)
    parser.add_argument("--stats-out", required=True)
    args = parser.parse_args(argv)
    sys.stdin.reconfigure(encoding="utf-8", errors="replace", newline="\n")
    sys.stdout.reconfigure(encoding="utf-8", newline="\n")
    server = RivalServer(ToolBox(Path(args.tree)), Path(args.verdict_out), Path(args.stats_out))
    serve(server, sys.stdin, sys.stdout)
    return 0


if __name__ == "__main__":
    sys.exit(main())
