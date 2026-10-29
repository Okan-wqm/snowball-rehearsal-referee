"""Red controls: known answers about the runner itself (`tohum/08` 3).

If any control gives the wrong answer, the runner cannot be trusted and every result of that run
is void. A runner that reports green for everything fails ``exit_one``; one that leaks network or
lets code write its source fails the other two.
"""

from __future__ import annotations

from .container import Runner

CONTROLS: tuple[tuple[str, str, bool], ...] = (
    # (id, command, must_succeed)
    ("exit_zero", "exit 0", True),
    ("exit_one", "exit 1", False),
    ("network_blocked",
     "python -c \"import socket; socket.create_connection(('1.1.1.1', 53), 3)\"", False),
    ("source_read_only", "touch /src/.snowball-write-probe", False),
)


def run_controls(runner: Runner, timeout_s: int = 120) -> list[dict]:
    results = []
    for cid, cmd, must_succeed in CONTROLS:
        res = runner.run(cmd, timeout_s=timeout_s)
        passed = (res.ok if must_succeed else (res.exit_code != 0 and not res.timed_out))
        results.append({"id": cid, "exit": res.exit_code, "timed_out": res.timed_out, "ok": passed})
    return results
