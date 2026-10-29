"""Run the rival's reproducers in the same sandbox as the tests (`tohum/29`).

A refutation counts only when its reproducer, run by the referee, shows every observable the
rival named. A reproducer that names no observable cannot count.
"""

from __future__ import annotations

import hashlib

from .container import Runner
from .rival import MAX_REPRODUCERS

DOCKER_ERROR = 125  # `docker run` exits with this when docker itself failed, before the command ran


def run_reproducers(runner: Runner, attempts: list[dict], timeout_s: int) -> list[dict]:
    results = []
    with_repro = [(i, a) for i, a in enumerate(attempts) if "reproducer" in a][:MAX_REPRODUCERS]
    for index, attempt in with_repro:
        rep = attempt["reproducer"]
        res = runner.run(rep["cmd"], timeout_s=timeout_s)
        checks = []
        if rep.get("expect_exit") is not None:
            checks.append(res.exit_code == rep["expect_exit"] and not res.timed_out)
        if rep.get("expect_stdout_contains") is not None:
            checks.append(rep["expect_stdout_contains"] in res.stdout.decode("utf-8", "replace"))
        results.append({
            "attempt_index": index,
            "reproduced": bool(checks) and all(checks),
            "runner_fault": res.exit_code == DOCKER_ERROR,  # the sandbox failed: nothing was shown either way
            "exit": res.exit_code,
            "timed_out": res.timed_out,
            "stdout_sha256": hashlib.sha256(res.stdout).hexdigest(),
        })
    return results
