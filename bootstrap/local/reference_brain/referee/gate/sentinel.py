"""MF12 sentinel.run's decision: affected tests after a merge, 3/3 on red (tohum/07:26-28, tohum/04a:24-25,
tohum/04:38).

    python -m gate.sentinel decide   (stdin: {"runs": [{"results": [{"id", "status": pass|fail}]}, ...]})
        -> {"verdict": green|red|flaky|rerun, "red": [...], "flaky": [...], "revert": bool}

The first run green (at least one result, no fail) ends it. Otherwise the first run plus three reruns are
considered (later runs are not read); fewer than four gives rerun. red = ids failing in every considered run,
flaky = ids failing in some but not all; a test absent from a run did not fail in it.
"""

from __future__ import annotations

import sys
from typing import Any

from ._strict import Unusable, emit, loads

CONSIDERED = 4  # the first red run and three reruns


def _failed(run: dict[str, Any]) -> set[str]:
    return {r["id"] for r in run["results"] if r["status"] == "fail"}


def decide(runs: list[dict[str, Any]]) -> dict[str, Any]:
    first = runs[0]
    if first["results"] and not _failed(first):
        return {"verdict": "green", "red": [], "flaky": [], "revert": False}
    if len(runs) < CONSIDERED:
        return {"verdict": "rerun", "red": [], "flaky": [], "revert": False}
    considered = runs[:CONSIDERED]
    failed = [_failed(run) for run in considered]
    ever = set().union(*failed)
    red = sorted(t for t in ever if all(t in f for f in failed))
    flaky = sorted(t for t in ever if t not in red)
    no_results = not any(run["results"] for run in considered)
    verdict = "red" if red or no_results else "flaky"
    return {"verdict": verdict, "red": red, "flaky": flaky, "revert": verdict == "red"}


def _parse(stdin: bytes) -> list[dict[str, Any]]:
    req = loads(stdin)
    runs = req.get("runs") if isinstance(req, dict) else None
    if not (isinstance(runs, list) and runs):
        raise Unusable("stdin has no runs")
    for run in runs:
        ok = (isinstance(run, dict) and isinstance(run.get("results"), list)
              and all(isinstance(r, dict) and isinstance(r.get("id"), str) and r.get("status") in ("pass", "fail")
                      for r in run["results"]))
        if not ok:
            raise Unusable("a run is not {results: [{id, status: pass|fail}]}")
    return runs


def main(argv: list[str]) -> None:
    if argv != ["decide"]:
        emit({"verdict": None, "error": "usage: decide"}, 2)
    try:
        runs = _parse(sys.stdin.buffer.read())
    except Unusable as exc:
        emit({"verdict": None, "red": [], "flaky": [], "revert": False, "error": str(exc)}, 2)
    out = decide(runs)
    emit(out, 0 if out["verdict"] == "green" else 1)


if __name__ == "__main__":
    main(sys.argv[1:])
