"""D5's criterion 8 (asama-0/08), tohum/07's serial merges: ``ledger.serial.unfinished`` on ``brain/state`` ledgers
written by ``ledger.append`` (the cycle's writer) with rows of ``ledger.schema``.

- no merge (a genesis without a ready candidate): nothing unfinished; a reject is no merge;
- a gate merge (an ``events``/``merge`` row, tohum/26d; its ``decision`` row is no merge) and a planted drill merge
  are unfinished until a later revert or sentinel end row (green or flaky, tohum/26f) names them; order is file
  order;
- a ledger that is not a chain, or holds a row of no known type or of a wrong shape, answers nothing (``Unusable``);
- a revert or end row of no earlier merge (also one written before its merge), a second finisher of one merge (a
  revert after an end, two ends) and the same SHA merged twice answer nothing;
- the reasons are all collected;
- ``lint_before``: the merge's own cycle's last ratchet base before it; a planted merge's likewise (D8 writes
  its cycle's ratchet base before the plant row); none for another cycle's, a later one, a merge without a cycle start
  or a planted merge whose cycle has none; a SHA no merge row names and an unreadable ledger answer nothing.
"""

from __future__ import annotations

import os
import sys
import unittest

REFEREE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REFEREE)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ledger import serial as SE  # noqa: E402
from test_revert_drill import ledger_with, plant, reverted, row  # noqa: E402

M1, M2, M3 = "1" * 40, "2" * 40, "3" * 40
START = row("s", "events", "cycle_start", {"cycle_id": "7"})


def merge(row_id: str, sha: str) -> dict:
    """The gate's merge row (tohum/26d ``kind: merge``)."""
    return row(row_id, "events", "merge", {"candidate": row_id, "path": "pkg/a.js", "pull": 1, "head_sha": "f" * 40,
                                           "merge_sha": sha, "hunk_covered": []})


def decided_merge(row_id: str) -> dict:
    """The decision row a merge row follows (``ledger.events.decided``): not itself a merge."""
    return row(row_id, "events", "decision", {"decision": "merge", "candidate": row_id})


def ended(row_id: str, sha: str, verdict: str = "green") -> dict:
    return row(row_id, "events", "sentinel", {"merge_sha": sha, "verdict": verdict, "red": [],
                                              "flaky": ["a"] if verdict == "flaky" else []})


def reject(row_id: str) -> dict:
    return row(row_id, "events", "decision", {"decision": "reject", "candidate": row_id, "reasons": ["tests_red"]},
               "test_regression")


class Unfinished(unittest.TestCase):
    def unfinished(self, *rows: dict) -> list[str]:
        return SE.unfinished(ledger_with(list(rows)))

    def refused(self, ledger: bytes) -> list[str]:
        with self.assertRaises(SE.Unusable) as ctx:
            SE.unfinished(ledger)
        return ctx.exception.reasons

    def test_no_merge_nothing_unfinished(self):
        self.assertEqual(self.unfinished(START), [])
        self.assertEqual(self.unfinished(START, reject("c1")), [])
        # tohum/26f: a merge is an events/merge or drill/plant row; a merge's decision row alone is none
        self.assertEqual(self.unfinished(START, decided_merge("c1")), [])
        self.assertEqual(self.unfinished(START, decided_merge("c1"), merge("m1", M1)), [M1])

    def test_a_merge_is_unfinished_until_its_revert(self):
        self.assertEqual(self.unfinished(START, merge("c1", M1)), [M1])
        self.assertEqual(self.unfinished(START, merge("c1", M1), reverted("r1", M1, "test_regression")), [])

    def test_a_green_or_flaky_end_row_finishes_a_merge(self):
        for verdict in ("green", "flaky"):
            with self.subTest(verdict=verdict):
                self.assertEqual(self.unfinished(START, merge("c1", M1), ended("e1", M1, verdict)), [])
                self.assertEqual(self.unfinished(START, plant("p1", "i1", M2), ended("e1", M2, verdict)), [])
                self.assertEqual(self.unfinished(START, merge("c1", M1), ended("e1", M1, verdict), merge("c2", M2)),
                                 [M2])

    def test_a_planted_merge_counts(self):
        self.assertEqual(self.unfinished(START, plant("p1", "i1", M2)), [M2])
        self.assertEqual(self.unfinished(START, plant("p1", "i1", M2), reverted("r1", M2, "impact_miss")), [])

    def test_only_the_named_merge_finishes_and_order_is_file_order(self):
        rows = (START, merge("c2", M2), plant("p1", "i1", M3), merge("c1", M1), reverted("r1", M3, "unknown"))
        self.assertEqual(self.unfinished(*rows), [M2, M1])

    def test_a_ledger_not_of_the_schema_answers_nothing(self):
        for bad, fragment in ((b"{}\n", "not a valid chain"),
                              (ledger_with([row("x", "events", "merged", {"merge_sha": M1})]), "unknown_row_type"),
                              (ledger_with([row("x", "events", "revert", {"merge_sha": "1"}, "unknown")]),
                               "not 40 lowercase hex"),
                              (ledger_with([row("x", "events", "revert", {"merge_sha": M1})]), "cause: missing")):
            with self.subTest(fragment=fragment):
                reasons = self.refused(bad)
                self.assertTrue(any(fragment in r for r in reasons), reasons)

    def test_a_revert_before_or_without_its_merge(self):
        self.assertEqual(self.refused(ledger_with([START, reverted("r1", M1, "unknown")])),
                         ["finish_without_merge:%s" % M1])
        self.assertEqual(self.refused(ledger_with([START, reverted("r1", M1, "unknown"), merge("c1", M1)])),
                         ["finish_without_merge:%s" % M1])

    def test_an_end_row_of_no_merge_or_a_second_finisher(self):
        self.assertEqual(self.refused(ledger_with([START, ended("e1", M1)])), ["finish_without_merge:%s" % M1])
        self.assertEqual(self.refused(ledger_with([START, ended("e1", M1), merge("c1", M1)])),
                         ["finish_without_merge:%s" % M1])
        for second in (reverted("r1", M1, "unknown"), ended("e2", M1, "flaky")):
            with self.subTest(second=second["kind"]):
                self.assertEqual(self.refused(ledger_with([START, merge("c1", M1), ended("e1", M1), second])),
                                 ["finished_twice:%s" % M1])
        self.assertEqual(self.refused(ledger_with([START, merge("c1", M1), reverted("r1", M1, "unknown"),
                                                   ended("e1", M1)])), ["finished_twice:%s" % M1])

    def test_merged_twice_and_all_reasons_together(self):
        self.assertEqual(self.refused(ledger_with([merge("c1", M1), plant("p1", "i1", M1)])), ["merged_twice:%s" % M1])
        self.assertEqual(self.refused(ledger_with([reverted("r2", M2, "unknown"), merge("c1", M1), merge("c3", M1)])),
                         ["finish_without_merge:%s" % M2, "merged_twice:%s" % M1])



def ratchet(row_id: str, counts: dict) -> dict:
    return row(row_id, "events", "ratchet_base", {"base_run_sha256": "e" * 64, "counts": counts})


def start(row_id: str) -> dict:
    return row(row_id, "events", "cycle_start", {"cycle_id": row_id})


class LintBefore(unittest.TestCase):
    """``lint_before``: the ratchet base of the merge's own cycle, else ``None``."""

    def before(self, sha: str, *rows: dict):
        return SE.lint_before(ledger_with(list(rows)), sha)

    def test_the_merges_cycle_ratchet_base(self):
        self.assertEqual(self.before(M1, start("s1"), ratchet("b1", {"eslint": 4}), merge("c1", M1)), {"eslint": 4})
        # the last one before the merge in that cycle; a later cycle's does not count
        rows = (start("s1"), ratchet("b1", {"eslint": 4}), ratchet("b2", {"eslint": 2}), merge("c1", M1),
                start("s2"), ratchet("b3", {"eslint": 9}), merge("c2", M2))
        self.assertEqual((self.before(M1, *rows), self.before(M2, *rows)), ({"eslint": 2}, {"eslint": 9}))

    def test_none_without_its_own_cycles_ratchet_base(self):
        # an earlier cycle's ratchet base is another base; a ratchet base after the merge is not its before
        self.assertIsNone(self.before(M1, start("s1"), ratchet("b1", {"eslint": 4}), start("s2"), merge("c1", M1)))
        self.assertIsNone(self.before(M1, start("s1"), merge("c1", M1), ratchet("b1", {"eslint": 4})))
        self.assertIsNone(self.before(M1, merge("c1", M1)))

    def test_a_planted_merge_reads_its_cycles_ratchet_base(self):
        self.assertEqual(self.before(M2, start("s1"), ratchet("b1", {"eslint": 4}), plant("p1", "i1", M2)),
                         {"eslint": 4})
        self.assertIsNone(self.before(M2, start("s1"), plant("p1", "i1", M2)))
        self.assertIsNone(self.before(M2, start("s1"), ratchet("b1", {"eslint": 4}), start("s2"), plant("p1", "i1", M2)))

    def test_refusals(self):
        for ledger, want in ((ledger_with([START, merge("c1", M1)]), ["not_merged:%s" % M2]),
                             (ledger_with([START, reject("c1")]), ["not_merged:%s" % M2])):
            with self.subTest(want=want), self.assertRaises(SE.Unusable) as ctx:
                SE.lint_before(ledger, M2)
            self.assertEqual(ctx.exception.reasons, want)
        with self.assertRaises(SE.Unusable):
            SE.lint_before(ledger_with([row("x", "events", "nope", {})]), M1)

if __name__ == "__main__":
    unittest.main()
