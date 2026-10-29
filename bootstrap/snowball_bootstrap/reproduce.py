"""Run reproducers in the same sandbox as the tests (`tohum/29`, "Rakibin kuralları").

A refutation counts only when its reproducer, run by the referee, shows every observable the rival
named (exit code, a substring of stdout, a substring of stderr) because of the defect. Three rules make
that hold (E06, E09):

- a run that timed out never shows anything;
- a reproducer that shows its observable is run again on an empty control tree (same image, prelude and
  working directory, no lock file to install); if the observable shows there too it is ``tautological``
  and does not count: a missing module or a bare ``true`` would show it whatever the code did;
- what the command printed is kept, as secret-scanned tails, so the rival and the operator can see it.

The rival's own reproducers (``run_reproducers``) and those the signed state keeps (``run_state_reproducers``:
proven defects and open claims, E07 E08) run the same way.
"""

from __future__ import annotations

import hashlib
from typing import Any

from . import canon, secretscan
from .container import Runner, RunResult
from .rival import MAX_REPRODUCERS

DOCKER_ERROR = 125  # `docker run` exits with this when docker itself failed, before the command ran
TAIL_CHARS = 2000
WITHHELD = "(withheld: the output matches a secret pattern)"
EXPECTATIONS = ("expect_exit", "expect_stdout_contains", "expect_stderr_contains")


def reproducer_key(rep: dict[str, Any]) -> str:
    """What makes two reproducers the same defect: the command and what it expects, not the claim's wording (E08)."""
    doc = {"cmd": rep["cmd"], **{k: rep.get(k) for k in EXPECTATIONS}}
    return hashlib.sha256(canon.canonical(doc)).hexdigest()[:16]


def _tail(data: bytes) -> str:
    tail = data.decode("utf-8", "replace")[-TAIL_CHARS:]
    return WITHHELD if secretscan.scan(tail) else tail


def _shows(rep: dict[str, Any], res: RunResult) -> bool:
    """Every expectation the reproducer names holds, and the run finished on its own."""
    if res.timed_out:  # whatever a killed run printed is no answer
        return False
    checks = []
    if rep.get("expect_exit") is not None:
        checks.append(res.exit_code == rep["expect_exit"])
    if rep.get("expect_stdout_contains") is not None:
        checks.append(rep["expect_stdout_contains"] in res.stdout.decode("utf-8", "replace"))
    if rep.get("expect_stderr_contains") is not None:
        checks.append(rep["expect_stderr_contains"] in res.stderr.decode("utf-8", "replace"))
    return bool(checks) and all(checks)


def run_one(runner: Runner, control: Runner, rep: dict[str, Any], timeout_s: int) -> dict[str, Any]:
    res = runner.run(rep["cmd"], timeout_s=timeout_s)
    shown = _shows(rep, res)
    fault = res.exit_code == DOCKER_ERROR  # the sandbox failed: nothing was shown either way
    tautological = None
    if shown and not fault:  # only an observable that showed needs the empty tree to tell it from the defect
        empty = control.run(rep["cmd"], timeout_s=timeout_s)
        fault = empty.exit_code == DOCKER_ERROR
        tautological = _shows(rep, empty)
    return {
        "key": reproducer_key(rep),
        "reproduced": shown and not fault and tautological is False,
        "shown": shown,
        "tautological": tautological,
        "runner_fault": fault,
        "exit": res.exit_code,
        "timed_out": res.timed_out,
        "stdout_sha256": hashlib.sha256(res.stdout).hexdigest(),
        "stderr_sha256": hashlib.sha256(res.stderr).hexdigest(),
        "stdout_tail": _tail(res.stdout),
        "stderr_tail": _tail(res.stderr),
    }


def run_reproducers(runner: Runner, attempts: list[dict], timeout_s: int, *, control: Runner) -> list[dict]:
    """The rival's reproducers of this run (at most five, E05)."""
    with_repro = [(i, a) for i, a in enumerate(attempts) if "reproducer" in a][:MAX_REPRODUCERS]
    return [dict(run_one(runner, control, attempt["reproducer"], timeout_s), attempt_index=index)
            for index, attempt in with_repro]


def run_state_reproducers(runner: Runner, entries: list[dict], timeout_s: int, *, control: Runner) -> list[dict]:
    """The signed state's reproducers: ``{key, source, reproducer}``, source ``refutation`` or ``claim``."""
    return [dict(run_one(runner, control, entry["reproducer"], timeout_s), key=entry["key"], source=entry["source"])
            for entry in entries]
