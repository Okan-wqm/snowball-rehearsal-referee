"""MF12 sentinel.run's decision: affected tests after a merge, 3/3 on red (tohum/07:26-28, tohum/04a:24-25,
tohum/04:38).

    python -m gate.sentinel decide   (stdin: {"runs": [{"results": [{"id", "status": pass|fail}]}, ...]})
        -> {"verdict": green|red|flaky|rerun, "red": [...], "flaky": [...], "revert": bool}

The first run green (at least one result, no fail) ends it. Otherwise the first run plus three reruns are
considered (later runs are not read); fewer than four, none too, gives rerun. red = ids failing in every considered
run, flaky = ids failing in some but not all; a test absent from a run did not fail in it. A run that is not read is
not checked for its form either (tohum/29j).
"""

from __future__ import annotations

import sys
from typing import Any

from ._strict import Unusable, emit, loads

CONSIDERED = 4  # the first red run and three reruns


def _failed(run: dict[str, Any]) -> set[str]:
    return {r["id"] for r in run["results"] if r["status"] == "fail"}


def decide(runs: list[Any]) -> dict[str, Any]:
    first = _read(runs[0]) if runs else {"results": []}
    if first["results"] and not _failed(first):
        return {"verdict": "green", "red": [], "flaky": [], "revert": False}
    considered = [_read(run) for run in runs[:CONSIDERED]]  # the runs after these are never read
    if len(considered) < CONSIDERED:
        return {"verdict": "rerun", "red": [], "flaky": [], "revert": False}
    failed = [_failed(run) for run in considered]
    ever = set().union(*failed)
    red = sorted(t for t in ever if all(t in f for f in failed))
    flaky = sorted(t for t in ever if t not in red)
    no_results = not any(run["results"] for run in considered)
    verdict = "red" if red or no_results else "flaky"
    return {"verdict": verdict, "red": red, "flaky": flaky, "revert": verdict == "red"}


def _read(run: Any) -> dict[str, Any]:
    """A run as it is read: checked for its form only then."""
    ok = (isinstance(run, dict) and isinstance(run.get("results"), list)
          and all(isinstance(r, dict) and isinstance(r.get("id"), str) and r.get("status") in ("pass", "fail")
                  for r in run["results"]))
    if not ok:
        raise Unusable("a run is not {results: [{id, status: pass|fail}]}")
    return run


def _parse(stdin: bytes) -> list[Any]:
    req = loads(stdin)
    runs = req.get("runs") if isinstance(req, dict) else None
    if not isinstance(runs, list):
        raise Unusable("stdin has no runs list")
    return runs


def main(argv: list[str]) -> None:
    if argv != ["decide"]:
        emit({"verdict": None, "error": "usage: decide"}, 2)
    try:
        out = decide(_parse(sys.stdin.buffer.read()))
    except Unusable as exc:
        emit({"verdict": None, "red": [], "flaky": [], "revert": False, "error": str(exc)}, 2)
    emit(out, 0 if out["verdict"] == "green" else 1)


if __name__ == "__main__":
    main(sys.argv[1:])
