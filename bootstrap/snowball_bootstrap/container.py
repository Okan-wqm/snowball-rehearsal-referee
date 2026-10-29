"""Run untrusted code in a nested, network-less, unprivileged container (`tohum/08` 2).

The job that calls this holds no secret. Results that matter (exit code, stdout, stderr) are
captured by this process outside the container and hashed here; nothing the container writes to
disk is trusted.
"""

from __future__ import annotations

import subprocess
import time
import uuid
from dataclasses import dataclass, field
from typing import Protocol

# Runs inside the container. Copies the read-only source to tmpfs, installs locked wheels with no
# index and no network, then runs the requested command. Values come in through environment
# variables so nothing is interpolated into the script.
PRELUDE = r"""set -eu
cp -R /src /tmp/work
python -m venv /tmp/venv >/dev/null
for lock in ${SNOWBALL_LOCKS:-}; do
  /tmp/venv/bin/pip install --quiet --no-index --find-links /deps --require-hashes \
    --only-binary=:all: --no-deps -r "/tmp/work/$lock"
done
export PATH=/tmp/venv/bin:$PATH
cd "/tmp/work/${SNOWBALL_CWD:-.}"
exec sh -c "$SNOWBALL_CMD"
"""


@dataclass(frozen=True)
class RunResult:
    exit_code: int
    stdout: bytes
    stderr: bytes
    duration_ms: int
    timed_out: bool = False

    @property
    def ok(self) -> bool:
        return self.exit_code == 0 and not self.timed_out


class Runner(Protocol):
    def run(self, cmd: str, *, cwd: str = ".", stdin: bytes = b"", timeout_s: int) -> RunResult: ...


@dataclass
class DockerRunner:
    """Each call is one fresh container with the source, wheels and vectors mounted read-only."""

    image: str
    src_dir: str
    deps_dir: str
    vectors_dir: str
    lockfiles: tuple[str, ...] = ()
    docker: str = "docker"
    executed: list[list[str]] = field(default_factory=list)

    def argv(self, name: str, cmd: str, cwd: str) -> list[str]:
        return [
            self.docker, "run", "--rm", "-i", "--name", name,
            "--network", "none",
            "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges",
            "--read-only",
            "--tmpfs", "/tmp:rw,exec,nosuid,size=1g",
            "--user", "65534:65534",
            "--pids-limit", "512",
            "--memory", "4g",
            "--cpus", "2",
            "--mount", f"type=bind,src={self.src_dir},dst=/src,readonly",
            "--mount", f"type=bind,src={self.deps_dir},dst=/deps,readonly",
            "--mount", f"type=bind,src={self.vectors_dir},dst=/vec,readonly",
            "--env", "HOME=/tmp",
            "--env", "PYTHONDONTWRITEBYTECODE=1",
            "--env", "PIP_DISABLE_PIP_VERSION_CHECK=1",
            "--env", f"SNOWBALL_LOCKS={' '.join(self.lockfiles)}",
            "--env", f"SNOWBALL_CWD={cwd}",
            "--env", f"SNOWBALL_CMD={cmd}",
            "--entrypoint", "sh",
            self.image,
            "-c", PRELUDE,
        ]

    def run(self, cmd: str, *, cwd: str = ".", stdin: bytes = b"", timeout_s: int) -> RunResult:
        if ".." in cwd.split("/") or cwd.startswith("/"):
            raise ValueError("cwd must be a relative path inside the source tree")
        name = f"snowball-{uuid.uuid4().hex[:16]}"
        argv = self.argv(name, cmd, cwd)
        self.executed.append(argv)
        start = time.monotonic()
        try:
            proc = subprocess.run(argv, input=stdin, capture_output=True, timeout=timeout_s, check=False)
        except subprocess.TimeoutExpired as exc:
            subprocess.run([self.docker, "rm", "-f", name], capture_output=True, check=False)
            return RunResult(124, exc.stdout or b"", exc.stderr or b"",
                             int((time.monotonic() - start) * 1000), timed_out=True)
        return RunResult(proc.returncode, proc.stdout, proc.stderr, int((time.monotonic() - start) * 1000))
