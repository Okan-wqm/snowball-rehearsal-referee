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

The image store. A ``FakeDocker`` is a host: ``images`` is what it holds (nothing by default, a fresh runner)
and ``registry`` what a pull can get (``None``: any reference). ``docker run`` of an image the host does not
hold ends 125 and starts nothing, as ``docker run --pull never`` does; ``--pull always`` or ``missing`` pulls
first; ``docker image inspect REF`` exits 0 or 1; ``docker pull REF`` stores it and exits 0, or exits 1. Every
call that is not ``docker run`` is recorded in ``other`` (``calls`` holds the runs). The image's content is not
emulated (every image runs this interpreter), nor a digest check. The stderr texts of these three are written
from docker's documented behaviour, not captured from a docker (this sandbox has none): tests may rely on the
exit codes only.

The user id (``--user UID[:GID]``), by its one effect the host can see: what the command makes under a writable
mount is owned by UID. When UID is not this process's uid and this process is not root, the host is "other" for
those entries (the container's group is taken not to be one of the host's), so after the command every entry it
made that lacks the others' read bit (a directory: read and search) is set to mode 0, which is what the host
then meets: it cannot open or list it. Entries that were there before the run keep their owner and are left
alone. ``release()`` gives those entries back to the owner (0700) so a test can delete its directory. With UID
equal to this process's uid, or this process root, nothing is changed.

Not emulated: the group id, capabilities and the memory limit.
"""

from __future__ import annotations

import json
import os
import stat
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


def _entries(roots: list[str]) -> set:
    """Every path under ``roots``, symlinks not followed."""
    found = set()
    for root in roots:
        for dirpath, dirnames, filenames in os.walk(root):
            found.update(os.path.join(dirpath, n) for n in dirnames + filenames)
    return found


class FakeDocker:
    """Callable with the ``runner.contained`` runner signature; records every call."""

    def __init__(self, exit_override: int | None = None, images=(), registry=None) -> None:
        self.calls: list[dict] = []
        self.other: list[list[str]] = []
        self.exit_override = exit_override
        self.images = set(images)
        self.registry = None if registry is None else set(registry)
        self.foreign: list[str] = []

    def release(self) -> None:
        """Owner access back on every entry ``_disown`` closed, outermost first."""
        for path in sorted(self.foreign):
            os.chmod(path, 0o700)
        self.foreign = []

    def _disown(self, before: set, roots: list[str]) -> None:
        """The module docstring's user id rule, for the entries under ``roots`` that are not in ``before``."""
        closed = []
        for path in sorted(_entries(roots) - before):
            st = os.lstat(path)
            need = stat.S_IROTH | stat.S_IXOTH if stat.S_ISDIR(st.st_mode) else stat.S_IROTH
            if not stat.S_ISLNK(st.st_mode) and st.st_mode & need != need:
                closed.append(path)
        for path in reversed(closed):  # innermost first: a closed directory hides its entries
            os.chmod(path, 0)
        self.foreign += closed

    def _pull(self, ref: str) -> RunnerResult:
        if self.registry is not None and ref not in self.registry:
            return RunnerResult(1, b"", b"Error response from daemon: manifest for %s not found: manifest unknown\n"
                                % ref.encode(), False)
        self.images.add(ref)
        return RunnerResult(0, ref.encode() + b"\n", b"", False)

    def __call__(self, argv: list[str], env: dict, timeout: float) -> RunnerResult:
        if argv[:3] == ["docker", "image", "inspect"]:
            self.other.append(argv)
            if argv[-1] in self.images:
                return RunnerResult(0, b"sha256:" + b"0" * 64 + b"\n", b"", False)
            return RunnerResult(1, b"\n", b"Error response from daemon: No such image: %s\n" % argv[-1].encode(),
                                False)
        if argv[:2] == ["docker", "pull"]:
            self.other.append(argv)
            return self._pull(argv[-1])
        spec = parse(argv)
        if spec["image"] not in self.images:
            policy = dict((f, v) for f, v in spec["opts"]).get("--pull", "missing")
            if policy == "never" or self._pull(spec["image"]).exit != 0:
                self.other.append(argv)
                return RunnerResult(125, b"", b"Unable to find image '%s' locally\n" % spec["image"].encode(), False)
        cenv: dict[str, str] = {}
        network, read_only, workdir, name, user = "default", False, "/", None, None
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
            elif flag in ("--user", "-u"):
                user = value.split(":")[0]
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
        foreign = os.geteuid() != 0 and user is not None and user != str(os.geteuid())
        before = _entries(cfg["rw"]) if foreign else set()
        try:
            proc = subprocess.run([sys.executable, "-I", HOOK, json.dumps(cfg)] + cmd[1:], env=cenv,
                                  cwd=host(workdir), capture_output=True, timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            call["killed"] = True
            return RunnerResult(None, exc.stdout or b"", exc.stderr or b"", True)
        finally:
            if foreign:
                self._disown(before, cfg["rw"])
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


def runs_of(docker):
    """Decorator for a test's own runner: the function sees the ``docker run`` calls only, so its call counts
    and argv positions are the contained runs'; every other docker call (inspect, pull) goes to ``docker``."""
    def wrap(fn):
        def runner(argv: list[str], env: dict, timeout: float) -> RunnerResult:
            if argv[:2] != ["docker", "run"]:
                return docker(argv, env, timeout)
            return fn(argv, env, timeout)
        return runner
    return wrap
