"""A fake ``claude`` CLI for test 37 (asama-0/14 row 15, "Kum": a Python script on PATH).

``install(directory)`` writes an executable ``claude`` into ``directory``. When run, it reads what to answer from
``behavior.json`` beside itself (``{"stdout": str, "sleep": seconds}``; the environment cannot carry it, since
``llm.call`` passes almost none) and appends one JSON line to ``calls.jsonl`` beside itself: its argv, its whole
environment as exec'd, its working directory and what that directory and ``CLAUDE_CONFIG_DIR`` held at start, and stdin.
"""

from __future__ import annotations

import json
import os
import stat
import sys

SCRIPT = '''#!%s
import json, os, sys, time
here = os.path.dirname(os.path.abspath(__file__))
stdin = sys.stdin.read()
config = os.environ.get("CLAUDE_CONFIG_DIR")
try:  # the environment as exec'd: Python itself may add LC_CTYPE to os.environ on start (PEP 538)
    with open("/proc/self/environ", "rb") as fh:
        env = dict(item.decode().split("=", 1) for item in fh.read().split(b"\\0") if item)
except OSError:
    env = dict(os.environ)
record = {"argv": sys.argv[1:], "env": env, "cwd": os.getcwd(), "cwd_listing": os.listdir("."),
          "config_listing": os.listdir(config) if config and os.path.isdir(config) else None, "stdin": stdin}
with open(os.path.join(here, "calls.jsonl"), "a") as fh:
    fh.write(json.dumps(record) + "\\n")
with open(os.path.join(here, "behavior.json")) as fh:
    behavior = json.load(fh)
time.sleep(behavior.get("sleep", 0))
sys.stdout.write(behavior["stdout"])
sys.exit(behavior.get("exit", 0))
'''


def install(directory: str) -> str:
    path = os.path.join(directory, "claude")
    with open(path, "w") as fh:
        fh.write(SCRIPT % sys.executable)
    os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR)
    return path


def install_for_loop(runner_temp: str) -> str:
    """The fake CLI where the loop's ``claude`` step leaves the real one (``loop.inputs.CLAUDE_CLI`` under
    ``$RUNNER_TEMP``, tohum/29s); its ``calls.jsonl`` and ``behavior.json`` are beside it (``os.path.dirname``)."""
    from loop import inputs
    directory = os.path.join(runner_temp, *inputs.CLAUDE_CLI[:-1])
    os.makedirs(directory, exist_ok=True)
    return install(directory)


def behave(directory: str, stdout: str, sleep: float = 0, exit: int = 0) -> None:
    with open(os.path.join(directory, "behavior.json"), "w") as fh:
        json.dump({"stdout": stdout, "sleep": sleep, "exit": exit}, fh)


def calls(directory: str) -> list[dict]:
    path = os.path.join(directory, "calls.jsonl")
    if not os.path.exists(path):
        return []
    with open(path) as fh:
        return [json.loads(line) for line in fh]
