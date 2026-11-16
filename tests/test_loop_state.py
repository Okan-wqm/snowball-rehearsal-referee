"""Test 46 (asama-0/09), MF17 with MF1, D1: ``loop.state``, the target's ``brain/state`` head verified against its
previous version (``verify --previous`` of ``ledger.jsonl`` and ``chain/root.jsonl``).

The commits are ``git_store``'s (git's own object format; ``test_gitobj.Parents`` binds ``parents`` to real git):

- ``parent``: none for an orphan genesis, the one parent, ``state_merge`` for two, an unreadable commit marked
  ``state:``;
- ``verify``: a genesis head verified as chains only; a head appending rows to both files of its parent; every
  refusal, each file judged on its own and every reason listed together: a file absent, a link or a tree where the
  file belongs, an empty file, a broken chain (with its line, and no append-only verdict on it), a file the parent
  lacks, and a parent line changed, gone, moved, rewritten into another valid chain or re-serialised with the same
  canonical row (bytes count, not the canonical form); a missing object of either commit as ``state:``.
"""

from __future__ import annotations

import json
import os
import sys
import unittest

REFEREE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REFEREE)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from loop import gitobj as G  # noqa: E402
from loop import state as ST  # noqa: E402
from loop.pulled import PulledError  # noqa: E402
import git_store as S  # noqa: E402
from test_accepted import chained  # noqa: E402

LEDGER, ROOTS = ".brain/ledger.jsonl", ".brain/chain/root.jsonl"


def rows(part: str, n: int, start: int = 1) -> list[dict]:
    return [{"row_id": "%s%d" % (part, i), "part": part, "payload": {"n": i}} for i in range(start, start + n)]


def files(ledger_rows: int, root_rows: int) -> dict:
    return {LEDGER: chained(rows("e", ledger_rows)), ROOTS: chained(rows("r", root_rows)), ".brain/status.md": b"s\n"}


def lines(data: bytes) -> list[bytes]:
    return data.splitlines(keepends=True)


class StateTest(unittest.TestCase):
    def setUp(self) -> None:
        self.objects: dict = {}
        _, self.genesis = S.store(files(2, 1), objects=self.objects)

    def head(self, content: dict, parents: tuple | None = None) -> str:
        return S.store(content, (self.genesis,) if parents is None else parents, self.objects)[1]

    def verify(self, head: str, prev: str | None = None) -> dict:
        source = self.objects.__getitem__
        return ST.verify(source, head, source, prev)

    def refused(self, head: str, prev: str | None = None) -> list[str]:
        with self.assertRaises(PulledError) as cm:
            self.verify(head, prev)
        return cm.exception.reasons


class Parent(StateTest):
    def test_genesis_one_parent_and_a_merge(self):
        source = self.objects.__getitem__
        self.assertIsNone(ST.parent(source, self.genesis))
        self.assertEqual(ST.parent(source, self.head(files(3, 2))), self.genesis)
        merge = self.head(files(3, 2), (self.genesis, self.head(files(3, 1))))
        with self.assertRaises(PulledError) as cm:
            ST.parent(source, merge)
        self.assertEqual(cm.exception.reasons, ["state_merge"])

    def test_an_unreadable_head(self):
        bad = S.put(self.objects, "commit", b"author x\n\nm\n")
        for sha, reason in ((bad, "state:commit_unreadable"), ("d" * 40, "state:object_missing:%s" % ("d" * 40))):
            with self.subTest(reason=reason), self.assertRaises(PulledError) as cm:
                ST.parent(self.objects.__getitem__, sha)
            self.assertEqual(cm.exception.reasons, [reason])


class Verify(StateTest):
    def test_genesis_is_verified_as_chains(self):
        self.assertEqual(self.verify(self.genesis), {"head": self.genesis, "previous": None,
                                                      "rows": {LEDGER: 2, ROOTS: 1}})

    def test_a_cycle_appended_to_both(self):
        head = self.head(files(5, 2))
        self.assertEqual(self.verify(head, self.genesis), {"head": head, "previous": self.genesis,
                                                           "rows": {LEDGER: 5, ROOTS: 2}})
        # the same files, nothing appended, is an extension too (a cycle that wrote only status.md)
        same = self.head(dict(files(2, 1), **{".brain/status.md": b"t\n"}))
        self.assertEqual(self.verify(same, self.genesis)["rows"], {LEDGER: 2, ROOTS: 1})

    def test_a_file_that_is_not_there(self):
        content = files(3, 2)
        for change, reason in (({LEDGER: None}, "file_missing:%s" % LEDGER),
                               ({LEDGER: ("120000", b".brain/status.md")}, "file_missing:%s" % LEDGER),
                               ({LEDGER: None, LEDGER + "/x": b"1\n"}, "file_missing:%s" % LEDGER),
                               ({ROOTS: None}, "file_missing:%s" % ROOTS)):
            with self.subTest(reason=reason, change=change):
                head = self.head({p: d for p, d in dict(content, **change).items() if d is not None})
                self.assertEqual(self.refused(head, self.genesis), [reason])
                self.assertEqual(self.refused(head), [reason])  # a genesis head too

    def test_an_empty_file(self):
        head = self.head(dict(files(0, 1), **{LEDGER: b""}))
        self.assertEqual(self.refused(head), ["chain_empty:%s" % LEDGER])
        self.assertIn("chain_empty:%s" % LEDGER, self.refused(head, self.genesis))

    def test_a_broken_chain_names_its_line_and_is_not_judged_further(self):
        ledger = lines(chained(rows("e", 4)))
        row = json.loads(ledger[2])
        row["payload"] = {"n": 99}  # row_hash no longer matches
        ledger[2] = (json.dumps(row) + "\n").encode()
        head = self.head(dict(files(4, 2), **{LEDGER: b"".join(ledger)}))
        self.assertEqual(self.refused(head, self.genesis), ["chain_broken:%s:3" % LEDGER])
        head = self.head(dict(files(4, 2), **{ROOTS: b"not json\n"}))
        self.assertEqual(self.refused(head, self.genesis), ["chain_broken:%s:1" % ROOTS])

    def test_a_file_the_parent_lacks(self):
        parent = self.head({LEDGER: chained(rows("e", 2))}, ())
        head = self.head(files(3, 1), (parent,))
        self.assertEqual(self.refused(head, parent), ["previous_missing:%s" % ROOTS])

    def test_every_rewrite_of_the_parents_lines(self):
        old = rows("e", 2)
        respaced = lines(chained(old))[0].replace(b'", "', b'","')  # the same canonical row, other bytes
        self.assertNotEqual(respaced, lines(chained(old))[0])
        for name, ledger, line in (
                ("changed", chained([dict(old[0], payload={"n": 7}), old[1]] + rows("e", 1, 3)), 1),
                ("gone", chained(rows("e", 1)), 2),
                ("moved", chained([old[1], old[0]] + rows("e", 1, 3)), 1),
                ("second changed", chained([old[0], dict(old[1], part="x")]), 2),
                ("respaced", respaced + b"".join(lines(chained(old))[1:]), 1)):
            with self.subTest(name):
                head = self.head(dict(files(2, 2), **{LEDGER: ledger}))
                if name != "respaced":
                    self.assertEqual(self.verify(head)["rows"][LEDGER], len(lines(ledger)))  # a valid chain alone
                self.assertEqual(self.refused(head, self.genesis), ["not_append_only:%s:%d" % (LEDGER, line)])

    def test_both_files_judged_and_listed_together(self):
        head = self.head({LEDGER: chained(rows("e", 1)), ROOTS: b""})
        self.assertEqual(self.refused(head, self.genesis),
                         ["not_append_only:%s:2" % LEDGER, "chain_empty:%s" % ROOTS,
                          "not_append_only:%s:1" % ROOTS])

    def test_a_missing_object_of_either_commit(self):
        head = self.head(files(3, 2))
        blob = G.lookup(self.objects.__getitem__, self.genesis, ROOTS)[1]
        del self.objects[blob]
        self.assertEqual(self.refused(head, self.genesis), ["state:object_missing:%s" % blob])
        self.assertEqual(self.refused(self.genesis), ["state:object_missing:%s" % blob])
        self.assertEqual(self.refused(head, "e" * 40), ["state:object_missing:%s" % ("e" * 40)])


if __name__ == "__main__":
    unittest.main()
