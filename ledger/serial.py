"""Merges are serial: which merges of a ``brain/state`` ledger have an unfinished sentinel (stage 0, D5's criterion 8).

Rules: tohum/26f (a merge's sentinel ends at the first later ``sentinel`` or ``revert`` row naming its
``merge_sha``; no merge while one is unfinished), tohum/07 (the gate merges one candidate at a time; the next one waits until the previous merge's sentinel
run has finished; on a verified red the referee reverts that merge), asama-0/08 criterion 8 (no other merge whose
sentinel is unfinished), asama-0/01 (D5 reads the cycle's state; D7, the sentinel, runs in the next cycle's ``koş``
and ``yaz``), tohum/26 (the ledger row), ``ledger.schema`` (the row types the loop writes, one table).

**Input**: the bytes of ``brain/state``'s ``ledger.jsonl`` (``pulled``'s ``state/ledger.jsonl``, which D1 verified as
a chain). **Rules** (``unfinished``):

1. The ledger must conform to ``ledger.schema`` (``ledger_reasons``: a chain, every row of a known type with its
   payload's shape); else ``Unusable`` with those reasons, and nothing is answered (fail closed: a row this reader
   cannot read could be a merge).
2. A **merge** is a row of ``MERGES``, tohum/26f's two: ``events``/``merge`` (the gate's merge, tohum/26d's merge
   row, ``activate`` and D6) and ``drill``/``plant`` (the revert drill's planted merge, which the sentinel must see
   red, tohum/22a). Its id is ``payload.merge_sha``. The same SHA merged twice is ``merged_twice:<sha>``.
3. A merge **finishes** at a row of ``FINISHERS``, read in file order, naming its ``merge_sha``: ``events``/``revert``
   (D7's revert of a red) or ``events``/``sentinel`` (D7's end of a green or flaky sentinel; both tohum/26f's). A finisher naming a SHA that no earlier row merged is
   ``finish_without_merge:<sha>`` (the ledger is append-only, so a revert before its merge is a broken state, not
   an unknown one); a second finisher of one merge is ``finished_twice:<sha>`` (a merge's sentinel ends once: a
   revert after a green end, or two ends, is a broken state).
4. ``unfinished`` is every merge without a finisher, in file order.

Reasons 2 and 3 are all collected, sorted, and raised together as ``Unusable``.

**A merge's lint before** (``lint_before``, read by ``loop.watch`` for ``gate.revert``'s ``lint``): the
``counts`` of the last ``events``/``ratchet_base`` row between the merge row's cycle start (the last
``events``/``cycle_start`` before it) and the merge row: the lint totals of the base the merge's cycle judged, which
is the merge's first parent (``activate`` and D6 write that row before their decisions; D8 writes it before its
``drill``/``plant`` row, the planted merge's base being the head the cycle's ``kos`` ran). ``None`` when the merge's
cycle has no ratchet base row (a plant ``harness.revert_drill.run_drill`` wrote outside the loop has none).
The same schema check as ``unfinished`` first; a SHA no merge row names is ``Unusable`` (``not_merged:<sha>``).

Out of scope, stated: whether a finisher's verdict is true (D7 writes it from a sentinel ``loop.watch`` verified;
this reader reads rows); whether a merge row's SHA is on ``brain/integration`` (D1's and D6's).
"""

from __future__ import annotations

from typing import Any

from ledger import chain
from ledger import schema

MERGES = (("events", "merge"), ("drill", "plant"))
FINISHERS = (("events", "revert"), ("events", "sentinel"))
CYCLE_START = ("events", "cycle_start")
RATCHET_BASE = ("events", "ratchet_base")


class Unusable(ValueError):
    def __init__(self, reasons: list[str]):
        super().__init__("; ".join(reasons))
        self.reasons = reasons


def _type(row: dict) -> tuple[Any, Any]:
    return row.get("part"), row.get("kind")


def _is_merge(row: dict) -> bool:
    return _type(row) in MERGES


def _rows(ledger: bytes) -> list[dict]:
    """The rows of ``ledger`` once it conforms to ``ledger.schema`` (rule 1), else ``Unusable``: one reading for
    ``unfinished`` and ``lint_before``."""
    reasons = schema.ledger_reasons(ledger)
    if reasons:
        raise Unusable(reasons)
    return [chain.parse_row(line.decode("utf-8")) for line in chain._lines(ledger)]


def unfinished(ledger: bytes) -> list[str]:
    """The merge SHAs of ``ledger`` whose sentinel has not finished, in file order; see the module docstring."""
    open_: dict[str, bool] = {}  # merge sha -> still unfinished, in file order
    bad: set[str] = set()
    for row in _rows(ledger):
        sha = row["payload"].get("merge_sha")
        if _is_merge(row):
            if sha in open_:
                bad.add("merged_twice:%s" % sha)
            open_[sha] = True
        elif _type(row) in FINISHERS:
            if sha not in open_:
                bad.add("finish_without_merge:%s" % sha)
            elif not open_[sha]:
                bad.add("finished_twice:%s" % sha)
            else:
                open_[sha] = False
    if bad:
        raise Unusable(sorted(bad))
    return [sha for sha, is_open in open_.items() if is_open]


def lint_before(ledger: bytes, merge_sha: str) -> dict[str, int] | None:
    """The ratchet base counts of the cycle that merged ``merge_sha``, or ``None``; see the module docstring."""
    counts = None
    for row in _rows(ledger):
        if _type(row) == CYCLE_START:
            counts = None
        elif _type(row) == RATCHET_BASE:
            counts = row["payload"]["counts"]
        elif _is_merge(row) and row["payload"].get("merge_sha") == merge_sha:
            return counts
    raise Unusable(["not_merged:%s" % merge_sha])
