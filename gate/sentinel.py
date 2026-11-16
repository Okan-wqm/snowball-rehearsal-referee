"""``sentinel.run``: after a merge, the affected tests at ``brain/integration``'s new head; on red, the 3/3 rule
(stage 0, MF12).

Rules: asama-0/14 row 12, asama-0/09 test 36, tohum/07 (the sentinel; on red, first the 3/3 rule that it is not
flaky, then ``gate.revert``), tohum/04 (zero tests is red), tohum/29j (group ``flaky``).

A run is ``{"results": [{"id", "status"}]}``: ``id`` a non-empty string, ``status`` ``pass`` or ``fail``, no other
key in a run or a result, an id at most once per run. Run 1 is the first run at the new head, runs 2.. are reruns,
each in a fresh container.

- **Green** (``decide``): run 1 has at least one result and no ``fail``. Later runs are not read (neither judged
  nor checked for shape).
- **Otherwise** (a ``fail`` in run 1, or run 1 has zero results): the 3/3 rule is run 1 plus three reruns, so
  the first four runs are judged and any run after the fourth is not read. With fewer than four runs (also with
  none) the verdict is ``rerun`` and no test is named. With four: ``red`` are the ids that fail in every one of
  the four, ``flaky`` the ids that fail in at least one and not in all; an id absent from a run did not fail in
  that run. The verdict is ``red`` when ``red`` is not empty or when none of the four runs has a result, else
  ``flaky``. ``red`` and ``flaky`` are sorted by code point; both are ``[]`` for ``green`` and ``rerun``.
  ``revert`` is true exactly for ``red``.
- **The loop** (``watch``): ``decide`` on run 1; while the verdict is ``rerun``, one more run from the
  ``rerun`` callable, then ``decide`` again. So a green first run asks for no rerun, a red one for exactly
  three, and ``watch`` and the command line judge with the same rule.

Out of scope here, stated: which tests are affected (stage 0's affected set is the unit's whole service-free
test set, asama-0/08 item 6; the recipe's ``affected_test_cmd``), how a contained run's output becomes
``results`` (the seed names no producer; this repository's is ``runner.kos``'s sentinel, which calls ``watch``
with contained runs of ``affected_test_cmd`` read by ``runner.kos.tap_tests``: calls 3 -> 12), and the revert
itself (``gate.revert``, MF13).

Command line (tohum/29j), run from ``referee/``, one JSON line on stdout, the cause on stderr::

    python -m gate.sentinel decide   stdin {"runs": [...]}   -> {verdict, red, flaky, revert}
    exit 0 green, 1 red, flaky or rerun, 2 unusable input ({"verdict": null, "red": [], "flaky": [], "revert": false})

stdin takes exactly the key ``runs``, a list of runs.
"""

from __future__ import annotations

import json
import sys
from typing import Any, Callable

from ledger import chain
import cli

RERUNS = 3
JUDGED = 1 + RERUNS
STATUSES = ("pass", "fail")


class Unusable(ValueError):
    pass


def _results(run: Any, index: int) -> dict[str, str]:
    """One run as ``{id: status}``; ``Unusable`` for any other shape."""
    if not isinstance(run, dict) or set(run) != {"results"} or not isinstance(run["results"], list):
        raise Unusable('run %d must be {"results": [...]} and nothing else' % index)
    out: dict[str, str] = {}
    for result in run["results"]:
        if not isinstance(result, dict) or set(result) != {"id", "status"}:
            raise Unusable('run %d: a result must be {"id", "status"} and nothing else' % index)
        test_id, status = result["id"], result["status"]
        if not isinstance(test_id, str) or not test_id:
            raise Unusable("run %d: id must be a non-empty string" % index)
        if status not in STATUSES:  # a tuple of str: no other type is equal to a member
            raise Unusable("run %d: status of %r must be pass or fail" % (index, test_id))
        if test_id in out:
            raise Unusable("run %d: id %r appears twice" % (index, test_id))
        out[test_id] = status
    return out


def _verdict(verdict: str, red: list[str] | None = None, flaky: list[str] | None = None) -> dict:
    return {"verdict": verdict, "red": red or [], "flaky": flaky or [], "revert": verdict == "red"}


def decide(runs: Any) -> dict:
    """The sentinel's verdict over the runs so far (see the module docstring)."""
    if not isinstance(runs, list):
        raise Unusable("runs must be a list")
    if runs:
        first = _results(runs[0], 1)
        if first and "fail" not in first.values():
            return _verdict("green")
    if len(runs) < JUDGED:
        return _verdict("rerun")
    judged = [_results(run, index) for index, run in enumerate(runs[:JUDGED], 1)]
    failing = [{test_id for test_id, status in run.items() if status == "fail"} for run in judged]
    red = set.intersection(*failing)
    flaky = set.union(*failing) - red
    if red or not any(judged):
        return _verdict("red", sorted(red), sorted(flaky))
    return _verdict("flaky", [], sorted(flaky))


def watch(first: dict, rerun: Callable[[], dict]) -> dict:
    """Run 1, then reruns from ``rerun`` while ``decide`` asks for one; ``{..., runs}`` with every run used."""
    runs = [first]
    result = decide(runs)
    while result["verdict"] == "rerun":
        runs.append(rerun())
        result = decide(runs)
    return dict(result, runs=runs)


# ---------------------------------------------------------------- command line

USAGE = 'usage: python -m gate.sentinel decide < {"runs": [...]}'
EMPTY = {"verdict": None, "red": [], "flaky": [], "revert": False}


def _emit(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj, sort_keys=True) + "\n")


def main(argv: list[str]) -> int:
    try:
        if argv != ["decide"]:
            raise Unusable(USAGE)
        request = chain.parse_row(sys.stdin.buffer.read().decode("utf-8"))
        if set(request) != {"runs"}:
            raise Unusable('stdin must be {"runs": [...]} and nothing else')
        result = decide(request["runs"])
        _emit(result)
        return 0 if result["verdict"] == "green" else 1
    except (Unusable, UnicodeDecodeError, chain.ChainError) as exc:
        sys.stderr.write("unusable input: %s\n" % cli.cause(exc))
    _emit(EMPTY)
    return 2


FAULT_LINE = EMPTY


if __name__ == "__main__":
    sys.exit(cli.run(main, sys.argv[1:], FAULT_LINE))
