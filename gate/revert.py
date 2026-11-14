"""``gate.revert``: on the sentinel's verified red, the referee reverts the merge, with a mechanical ``cause``
(stage 0, MF13).

Rules: asama-0/14 row 13, asama-0/09 test 25, tohum/07 (on red, first the 3/3 rule, then ``gate.revert``
reverts that merge; a revert is written with a ``cause``; it passes the gate like a merge), tohum/26 (``cause``
is a closed set), tohum/29j (group ``cause``), tohum/26a (``gate.revert``: merge SHA and ``cause`` -> a revert
committed with ``target.write``).

**The rule** (``cause``). The request is exactly ``{red_tests, impact, build_ok, lint}``: ``red_tests`` the
verified red tests (the sentinel's ``red``), ``impact`` the impact set declared at the merge, each a list of
non-empty strings read as a set (a repeated id changes nothing); ``build_ok`` a bool, whether the code at the
red head built and loaded; ``lint`` an object ``{tool: {"before": int, "after": int}}`` (tool a non-empty string,
counts non-negative integers, a bool is not one; ``{}`` allowed), each tool's total at the merge's first parent
and at the head. The first rule that holds is the cause:

1. ``build_break``: ``build_ok`` is false (red tests at code that does not build are its result);
2. ``lint_regression``: some tool's ``after`` is greater than its ``before``, per tool (asama-0/08 item 5): one
   tool's drop does not offset another's rise;
3. ``test_regression``: at least one red test is in ``impact``;
4. ``impact_miss``: there are red tests and none is in ``impact``;
5. ``unknown``: otherwise (no red test, the build is fine and no tool rose).

Only these five of tohum/26's ten causes are mechanical at stage 0 (asama-0/09 test 25); the others are never
returned here. Any other shape is unusable (``Unusable``), never a cause.

**The assessment** (``assess``, pure). It judges the runs itself with ``sentinel.decide`` (calls 12 -> 13), so
only a verified red reverts and ``red_tests`` is the sentinel's ``red`` by construction, not a second input that
could disagree. ``facts`` is ``{impact, build_ok, lint}``, checked as the request is, except that ``lint`` may
be ``null``: the totals could not be read (the loop's base lint gave no file, or the merge's cycle recorded no
ratchet base). Then rule 1 still holds when ``build_ok`` is false, and otherwise the cause is ``unknown``: rule 2
comes before rule 3, so without the totals neither ``lint_regression`` nor a later rule can be stated
mechanically. ``build_ok`` may be ``null`` too: whether the head built could not be read (``loop.watch.base_build``).
Then no rule can be stated (rule 1 is the question, and every later rule holds only when it does not), so the
cause is ``unknown``, whatever ``lint`` is. The command line's ``cause`` takes no ``null`` (29j's request has the
facts).

**The revert** (``revert_red``). ``assess`` first. Not red (``green``, ``flaky``, ``rerun``): nothing is sent and
``reverted`` is false. Red: the cause is computed first (an unusable request sends nothing), then ``target.write``'s
``Writer.revert`` (calls 9 -> 13) puts a commit whose tree is the merge's first parent's tree on ``revert_branch``
(refused, nothing written, if the merge is not ``onto``'s head or not a merge), and a pull request from that branch to
``onto`` is opened. The message and the title carry the cause.

Out of scope here, stated: merging that pull request (it passes the gate like any candidate: the gate's
check, then ``Writer.merge``; ``brain/integration`` takes no direct push, tohum/01b; the loop's is
``target.land.revert``), the ledger row that records the revert and its cause (``ledger.events.revert``, written
by ``loop.write_cycle``), and who produces ``build_ok`` and the lint totals (the Founder's code, tohum/29j; the
loop's producers, with their stated rules, are ``loop.watch.base_build`` and ``loop.watch.facts``).

Command line (tohum/29j), run from ``referee/``, one JSON line on stdout, the cause of an error on stderr::

    python -m gate.revert cause   stdin {"red_tests", "impact", "build_ok", "lint"}   -> {"cause": ...}
    exit 0, 2 unusable input ({"cause": null})
"""

from __future__ import annotations

import json
import sys
from typing import Any

from gate import sentinel
from ledger import chain
import cli

CAUSES = ("build_break", "lint_regression", "test_regression", "impact_miss", "unknown")
REQUEST = {"red_tests", "impact", "build_ok", "lint"}
COUNTS = {"before", "after"}


class Unusable(ValueError):
    pass


def _ids(value: Any, name: str) -> set[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise Unusable("%s must be a list of non-empty strings" % name)
    return set(value)


def _count(value: Any) -> bool:
    return type(value) is int and value >= 0


def _lint(value: Any) -> dict[str, dict]:
    if not isinstance(value, dict):
        raise Unusable("lint must be an object {tool: {before, after}}")
    for tool, counts in value.items():
        if not tool:
            raise Unusable("lint: a tool name must be a non-empty string")
        if not isinstance(counts, dict) or set(counts) != COUNTS or not all(_count(counts[k]) for k in COUNTS):
            raise Unusable("lint: %r must be {before, after}, non-negative integers" % tool)
    return value


def cause(request: Any) -> str:
    """The mechanical cause of a verified red (see the module docstring)."""
    if not isinstance(request, dict) or set(request) != REQUEST:
        raise Unusable("the request must be {red_tests, impact, build_ok, lint} and nothing else")
    red = _ids(request["red_tests"], "red_tests")
    impact = _ids(request["impact"], "impact")
    if type(request["build_ok"]) is not bool:
        raise Unusable("build_ok must be true or false")
    lint = _lint(request["lint"])
    if not request["build_ok"]:
        return "build_break"
    if any(counts["after"] > counts["before"] for counts in lint.values()):
        return "lint_regression"
    if red & impact:
        return "test_regression"
    if red:
        return "impact_miss"
    return "unknown"


def assess(runs: Any, facts: Any) -> dict:
    """``{revert, verdict, red, cause}`` of ``runs`` and ``facts`` (see the module docstring); ``cause`` is null
    unless ``revert``. Malformed runs raise ``sentinel.Unusable``, malformed facts of a red ``Unusable``."""
    verdict = sentinel.decide(runs)
    out = {"revert": verdict["revert"], "verdict": verdict["verdict"], "red": verdict["red"], "cause": None}
    if not verdict["revert"]:
        return out
    if not isinstance(facts, dict) or "red_tests" in facts:
        raise Unusable("facts must be {impact, build_ok, lint}; red_tests is the sentinel's red")
    request = dict(facts, red_tests=verdict["red"])
    if "build_ok" in facts and facts["build_ok"] is None:
        checked = dict(request, build_ok=True)  # the shape checked as the request's; no rule can be judged
        if "lint" in checked and checked["lint"] is None:
            checked["lint"] = {}
        cause(checked)
        return dict(out, cause="unknown")
    if "lint" in facts and facts["lint"] is None:
        found = cause(dict(request, lint={}))  # the shape checked as the request's; the lint rule cannot be judged
        return dict(out, cause="build_break" if found == "build_break" else "unknown")
    return dict(out, cause=cause(request))


def revert_red(writer: Any, runs: Any, facts: Any, merge: str, onto: str, revert_branch: str) -> dict:
    """Revert ``merge`` (``onto``'s head) when ``runs`` are a verified red; ``facts`` is ``{impact, build_ok,
    lint}``. Returns ``{reverted, verdict, red, cause, commit, tree, parents, pull}`` (the last five null when
    not reverted). Malformed runs raise ``sentinel.Unusable``, malformed facts ``Unusable``; a refused revert
    ``target.write.Refused``; in each case before anything is written."""
    judged = assess(runs, facts)
    out = {"reverted": False, "verdict": judged["verdict"], "red": judged["red"], "cause": None,
           "commit": None, "tree": None, "parents": None, "pull": None}
    if not judged["revert"]:
        return out
    found = judged["cause"]
    title = "revert %s: %s" % (merge, found)
    done = writer.revert(merge, onto, revert_branch, title)
    pull = writer.open_pull(revert_branch, onto, title, "cause: %s; red: %s" % (found, ", ".join(judged["red"])))
    return dict(out, reverted=True, cause=found, commit=done["commit"], tree=done["tree"],
                parents=done["parents"], pull=pull)


# ---------------------------------------------------------------- command line

USAGE = 'usage: python -m gate.revert cause < {"red_tests", "impact", "build_ok", "lint"}'


def _emit(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj, sort_keys=True) + "\n")


def main(argv: list[str]) -> int:
    try:
        if argv != ["cause"]:
            raise Unusable(USAGE)
        _emit({"cause": cause(chain.parse_row(sys.stdin.buffer.read().decode("utf-8")))})
        return 0
    except (Unusable, UnicodeDecodeError, chain.ChainError) as exc:
        sys.stderr.write("unusable input: %s\n" % cli.cause(exc))
    _emit({"cause": None})
    return 2


FAULT_LINE = {"cause": None}


if __name__ == "__main__":
    sys.exit(cli.run(main, sys.argv[1:], FAULT_LINE))
