"""A stand-in for ``docker run`` for tests 20 and 21 (asama-0/14: "taklit koşucu"; the real one is 10a #kanarya).

It reads the argv on its own -- it does not call ``runner.contained.check_argv`` -- and acts on what the
flags mean, so a builder that drops a flag gets a container without that protection:

- ``--env NAME=VALUE`` sets a variable; ``--env NAME`` copies it from the docker CLI's own environment
  (docker's behaviour); nothing else from the host reaches the command.
- ``--network none``: every ``socket.connect`` fails. Any other network: connections go through.
- ``--read-only``: writes outside the writable mounts fail. Without it they reach the host, which is how
  a missing flag shows up in the host hashes. A ``readonly`` mount refuses writes either way.
- Paths in the command that start with a mount's container path are mapped to its host source, the
  working directory too; ``python``/``python3`` is this interpreter. Only Python commands run.

Blocking is done by an audit hook in the child (``fake_docker_hook.py``), installed before the command.
Not emulated: the user id, capabilities, memory limit and the image (it is ignored).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

from runner.contained import RunnerResult

HERE = os.path.dirname(os.path.abspath(__file__))
HOOK = os.path.join(HERE, "fake_docker_hook.py")
NO_VALUE = {"--rm", "--read-only", "--privileged", "-i", "-t", "-d", "--init"}


def parse(argv: list[str]) -> dict:
    if argv[:2] != ["docker", "run"]:
        raise AssertionError("fake docker only runs: docker run")
    opts: list[tuple[str, str | None]] = []
    i = 2
    while i < len(argv) and argv[i].startswith("-"):
        tok = argv[i]
        if "=" in tok and tok.startswith("--"):
            flag, value = tok.split("=", 1)
            i += 1
        elif tok in NO_VALUE:
            flag, value = tok, None
            i += 1
        else:
            flag, value = tok, argv[i + 1]
            i += 2
        opts.append((flag, value))
    return {"opts": opts, "image": argv[i], "cmd": argv[i + 1:]}


class FakeDocker:
    """Callable with the ``runner.contained`` runner signature; records every call."""

    def __init__(self, exit_override: int | None = None) -> None:
        self.calls: list[dict] = []
        self.exit_override = exit_override

    def __call__(self, argv: list[str], env: dict, timeout: float) -> RunnerResult:
        spec = parse(argv)
        cenv: dict[str, str] = {}
        network, read_only, workdir, name = "default", False, "/", None
        mounts: list[dict] = []
        for flag, value in spec["opts"]:
            if flag in ("--env", "-e"):
                key, sep, val = value.partition("=")
                if sep:
                    cenv[key] = val
                elif key in env:
                    cenv[key] = env[key]
            elif flag in ("--network", "--net"):
                network = value
            elif flag == "--read-only":
                read_only = True
            elif flag in ("--workdir", "-w"):
                workdir = value
            elif flag == "--name":
                name = value
            elif flag == "--mount":
                fields = dict(f.split("=", 1) if "=" in f else (f, "true") for f in value.split(","))
                mounts.append({"src": fields.get("src") or fields.get("source"),
                               "dst": fields.get("dst") or fields.get("target"),
                               "ro": fields.get("readonly", fields.get("ro", "false")) != "false"})
        def host(path: str) -> str:
            for m in mounts:
                if path == m["dst"] or path.startswith(m["dst"] + "/"):
                    return m["src"] + path[len(m["dst"]):]
            return path
        cmd = [host(c) for c in spec["cmd"]]
        if cmd[0] not in ("python", "python3"):
            raise AssertionError("fake docker runs Python commands only")
        cfg = {"network": network, "read_only": read_only,
               "rw": [m["src"] for m in mounts if not m["ro"]], "ro": [m["src"] for m in mounts if m["ro"]]}
        call = {"argv": argv, "env": dict(env), "container_env": cenv, "name": name, "killed": False,
                "mounts": mounts}
        self.calls.append(call)
        try:
            proc = subprocess.run([sys.executable, "-I", HOOK, json.dumps(cfg)] + cmd[1:], env=cenv,
                                  cwd=host(workdir), capture_output=True, timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            call["killed"] = True
            return RunnerResult(None, exc.stdout or b"", exc.stderr or b"", True)
        call["stdout"], call["stderr"] = proc.stdout, proc.stderr
        code = proc.returncode if self.exit_override is None else self.exit_override
        return RunnerResult(code, proc.stdout, proc.stderr, False)


class FixedRunner:
    """Runs nothing; returns a fixed exit code (docker failures: 125, 126, 127) or a timeout."""

    def __init__(self, exit_code: int | None, timed_out: bool = False, action=None) -> None:
        self.exit_code, self.timed_out, self.action = exit_code, timed_out, action
        self.calls: list[list[str]] = []

    def __call__(self, argv: list[str], env: dict, timeout: float) -> RunnerResult:
        self.calls.append(argv)
        if self.action:
            self.action(argv)
        return RunnerResult(self.exit_code, b"", b"", self.timed_out)
