"""Test 39 (asama-0/09) and group ``append`` (tohum/29i): ``ledger.append``, one ``brain/state`` commit per cycle.

- step 1 before the request: a broken tip, a line cut while written, a rewritten old row (a valid chain on
  its own), a re-serialized row (same canonical form, other bytes), a shorter file: hard stop, the request
  is never read, nothing is committed, even when the request is unusable;
- the request: exactly ``{"rows": [...]}``, rows are objects without ``prev_hash``/``row_hash``, row ids
  unique against each other and the ledger, the canonical form holds them; each refusal is exit 2;
- secrets: a token spelled with ``\\u`` escapes is caught in the decoded row; exit 1, not a hard stop;
- ``proposed_by`` (top level, any value) stores ``trust: inferred``; the hash is the stored row's;
- chaining: rows in request order onto the ledger's last row whatever its part (the ledger may have grown
  since the previous version); a row hash checked against a hand-written canonical text; a missing final
  newline; an empty ledger;
- step 6: a wrong new line is caught by the re-verification and not committed;
- one commit per cycle through ``target.write`` on the in-process GitHub: ``brain/state`` holds the new file,
  which verifies as an append-only extension, ``main`` never moves, a stale head writes nothing;
- the command lines: ``ledger.append cycle`` outputs and exits, ``ledger.chain verify --previous`` on a
  rewritten and a truncated file.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

REFEREE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REFEREE)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ledger import append as AP  # noqa: E402
from ledger import chain  # noqa: E402
from target import write as W  # noqa: E402
from fake_github import FakeGitHub  # noqa: E402

ZERO = "0" * 64
TOKEN = "ghp_" + "Q7x" * 12  # a GitHub token shape, not a real token


def build(rows, prev=ZERO):
    """An independent writer of chained lines (json.dumps with sorted keys; for these ASCII rows that is the
    canonical form)."""
    out = []
    for row in rows:
        row = dict(row, prev_hash=prev)
        body = json.dumps(row, sort_keys=True, separators=(",", ":")).encode()
        prev = row["row_hash"] = hashlib.sha256(body + prev.encode()).hexdigest()
        out.append(json.dumps(row, sort_keys=True, separators=(",", ":")).encode() + b"\n")
    return b"".join(out), prev


BASE, TIP = build([{"row_id": "e1", "part": "events", "kind": "x"}, {"row_id": "c1", "part": "cost", "kind": "y"}])


def req(*rows):
    return json.dumps({"rows": list(rows)}).encode()


class Reader:
    def __init__(self, data):
        self.data, self.calls = data, 0

    def __call__(self):
        self.calls += 1
        return self.data


def cycle(ledger, previous, request):
    state, reader = AP.CountingState(), Reader(request)
    return AP.append_cycle(ledger, previous, reader, state), state, reader


class Step1HardStop(unittest.TestCase):
    def assertStops(self, ledger, previous=BASE, request=req({"row_id": "n1"})):
        state, reader = AP.CountingState(), Reader(request)
        with self.assertRaises(AP.HardStop):
            AP.append_cycle(ledger, previous, reader, state)
        self.assertEqual((state.commits, reader.calls), (0, 0))

    def test_refuse_broken_tip(self):
        # the last line edited after its hash: append-only alone would let it through
        grown, _ = build([{"row_id": "e2", "part": "events"}], TIP)
        ledger = BASE + grown.replace(b'"e2"', b'"e3"')
        self.assertTrue(ledger.startswith(BASE))
        self.assertStops(ledger)

    def test_refuse_unparsable_ledger(self):
        self.assertStops(BASE[:-20])  # cut while written: a chain break, not unusable input
        self.assertStops(BASE + b'{"row_id": "e2", "part"')

    def test_refuse_broken_chain_first(self):
        tampered = BASE.replace(b'"kind":"y"', b'"kind":"z"')
        for bad in (b"", b"[]", b'{"rows": 1}', b"\xff", req({"row_id": "e1"})):
            self.assertStops(tampered, request=bad)

    def test_refuse_rewritten_history(self):
        rewritten, _ = build([{"row_id": "e1", "part": "events", "kind": "EDITED"},
                              {"row_id": "c1", "part": "cost", "kind": "y"}])
        self.assertTrue(chain.verify_bytes(rewritten)["valid"])  # valid on its own
        self.assertStops(rewritten)

    def test_refuse_reserialized_row(self):
        first = BASE.split(b"\n")[0]
        row = json.loads(first)
        spaced = json.dumps(row, sort_keys=False, separators=(", ", ": ")).encode()
        self.assertEqual(chain.canonical(json.loads(spaced)), chain.canonical(row))
        self.assertStops(BASE.replace(first, spaced, 1))
        reordered = json.dumps(dict(reversed(list(row.items()))), separators=(",", ":")).encode()
        self.assertNotEqual(reordered, first)
        self.assertStops(BASE.replace(first, reordered, 1))

    def test_shorter_than_previous(self):
        self.assertStops(BASE.split(b"\n", 1)[0] + b"\n")
        self.assertStops(b"")


class Request(unittest.TestCase):
    def assertUnusable(self, request, ledger=BASE):
        state, reader = AP.CountingState(), Reader(request)
        with self.assertRaises(AP.Unusable):
            AP.append_cycle(ledger, ledger, reader, state)
        self.assertEqual((state.commits, reader.calls), (0, 1))

    def test_shape(self):
        for bad in (b"", b"\xff\xfe", b"[]", b'{"rows": {}}', b'{"rows": []}', b'{"rows": [1]}',
                    b'{"rows": [{"row_id": "n"}], "part": "events"}', b'{"rows": [{"a": 1, "a": 2}]}',
                    b'{"rows": [{"a": NaN}]}', b'{"rows": [{"row_id": "n"}]} x'):
            self.assertUnusable(bad)

    def test_hash_fields_are_written_here(self):
        self.assertUnusable(req({"row_id": "n", "prev_hash": TIP}))
        self.assertUnusable(req({"row_id": "n", "row_hash": TIP}))

    def test_row_ids_are_unique(self):
        self.assertUnusable(req({"row_id": "n"}, {"row_id": "n"}))
        self.assertUnusable(req({"row_id": "c1"}))  # already in the ledger
        hashes, state, _ = cycle(BASE, BASE, req({"row_id": "n"}, {"row_id": "m"}, {"part": "events"}))
        self.assertEqual(len(hashes), 3)

    def test_a_row_too_deep_to_read_is_unusable_not_clean(self):
        deep = '{"rows": [{"row_id": "n", "p": ' + "[" * 900 + "]" * 900 + "}]}"
        json.loads(deep)  # the parser alone takes it; the scanner's recursion would give out (before cli rule 8's
        with self.assertRaises(chain.ChainError):  # bound, it did); now the parse refuses it (cli.DEPTH)
            chain.parse_row(deep)
        self.assertUnusable(deep.encode())

    def test_what_the_canonical_form_cannot_hold(self):
        self.assertUnusable(req({"row_id": "n", "ms": 1.5}))
        self.assertUnusable(req({"row_id": "n", "n": 2 ** 53}))


class Secrets(unittest.TestCase):
    def test_refuse_secret_row(self):
        escaped = "".join("\\u%04x" % ord(c) for c in TOKEN)
        raw = ('{"rows": [{"row_id": "n1", "payload": {"summary": "ok"}}, '
               '{"row_id": "n2", "payload": {"summary": "' + escaped + '"}}]}').encode()
        self.assertNotIn(TOKEN.encode(), raw)
        state, reader = AP.CountingState(), Reader(raw)
        with self.assertRaises(AP.SecretRow) as ctx:
            AP.append_cycle(BASE, BASE, reader, state)
        self.assertEqual(ctx.exception.rows, [2])
        self.assertEqual(state.commits, 0)

    def test_clean_rows_pass(self):
        hashes, state, _ = cycle(BASE, BASE, req({"row_id": "n1", "payload": {"summary": "tokens_in 40"}}))
        self.assertEqual(state.commits, 1)


class Stored(unittest.TestCase):
    def new_rows(self, ledger, content):
        return [json.loads(line) for line in content[len(ledger):].splitlines()]

    def test_proposed_by_stored_inferred(self):
        rows = [{"row_id": "p1", "trust": "verified", "proposed_by": "founder"},
                {"row_id": "p2", "proposed_by": None},
                {"row_id": "p3", "trust": "observed", "proposed_by": {"seat": "x"}},
                {"row_id": "k1", "trust": "verified"},
                {"row_id": "k2", "trust": "observed", "payload": {"proposed_by": "x"}}]
        hashes, state, _ = cycle(BASE, BASE, req(*rows))
        stored = self.new_rows(BASE, state.content)
        self.assertEqual([r.get("trust") for r in stored], ["inferred", "inferred", "inferred", "verified", "observed"])
        self.assertEqual([r["row_hash"] for r in stored], hashes)
        for r in stored:  # the hash is the stored row's
            self.assertEqual(chain.row_hash(r), r["row_hash"])

    def test_cycle_one_commit(self):
        rows = [{"row_id": "e2", "part": "events", "kind": "x"}, {"row_id": "c2", "part": "cost", "kind": "y"}]
        hashes, state, _ = cycle(BASE, BASE, req(*rows))
        self.assertEqual(state.commits, 1)
        expected, _ = build(rows, TIP)  # an independent chain of the same rows
        self.assertEqual(state.content, BASE + expected)
        self.assertEqual(hashes, [json.loads(line)["row_hash"] for line in expected.splitlines()])
        self.assertEqual(chain.verify_bytes(state.content, BASE), {"valid": True, "broken_row": None, "line": None,
                                                                   "reason": None})

    def test_chains_onto_current_tip(self):
        grown, tip = build([{"row_id": "e2", "part": "events"}], TIP)
        ledger = BASE + grown
        hashes, state, _ = cycle(ledger, BASE, req({"row_id": "s1", "part": "security"}))
        stored = self.new_rows(ledger, state.content)
        self.assertEqual(stored[0]["prev_hash"], tip)
        self.assertNotEqual(tip, TIP)

    def test_hand_written_canonical_hash(self):
        hashes, state, _ = cycle(b"", b"", req({"row_id": "r1", "n": 7, "s": "ç\n"}))
        text = '{"n":7,"prev_hash":"%s","row_id":"r1","s":"ç\\n"}' % ZERO
        self.assertEqual(hashes, [hashlib.sha256(text.encode() + ZERO.encode()).hexdigest()])
        stored = '{"n":7,"prev_hash":"%s","row_hash":"%s","row_id":"r1","s":"ç\\n"}\n' % (ZERO, hashes[0])
        self.assertEqual(state.content, stored.encode())

    def test_missing_final_newline(self):
        ledger = BASE[:-1]
        hashes, state, _ = cycle(ledger, ledger, req({"row_id": "n1"}))
        self.assertTrue(state.content.startswith(BASE))
        self.assertTrue(chain.verify_bytes(state.content, ledger)["valid"])

    def test_step6_reverifies_before_committing(self):
        real = AP._chained

        def wrong(rows, tip):
            lines, hashes = real(rows, tip)
            return [lines[0].replace(b'"n1"', b'"n9"')], hashes

        state = AP.CountingState()
        with mock.patch.object(AP, "_chained", wrong):
            with self.assertRaises(AP.HardStop):
                AP.append_cycle(BASE, BASE, Reader(req({"row_id": "n1"})), state)
        self.assertEqual(state.commits, 0)


class OnTheTarget(unittest.TestCase):
    """``TargetState``: the cycle's one commit through ``target.write`` on ``brain/state``."""

    def world(self):
        gh = FakeGitHub("acme/toy")
        root = gh.seed_commit("t0")
        gh.refs["main"] = root
        head = gh.seed_commit("s0", files={".brain/ledger.jsonl": BASE, ".brain/status.md": b"s\n"})
        gh.refs["brain/state"] = head
        return gh, W.Writer("acme/toy", gh), head, root

    def test_one_commit_per_cycle(self):
        gh, wr, head, root = self.world()
        state = AP.TargetState(wr, head)
        hashes = AP.append_cycle(BASE, BASE, Reader(req({"row_id": "e2"}, {"row_id": "c2"})), state)
        new = gh.read_file("brain/state", ".brain/ledger.jsonl")
        self.assertTrue(chain.verify_bytes(new, BASE)["valid"])
        self.assertEqual([json.loads(line)["row_hash"] for line in new[len(BASE):].splitlines()], hashes)
        self.assertEqual(gh.commits[gh.refs["brain/state"]]["parents"], [head])
        self.assertEqual(len(state.commits_made), 1)
        self.assertEqual([r for r in gh.requests if r[1].endswith("/git/commits")][0][0], "POST")
        self.assertEqual(sum(1 for r in gh.requests if r[0] == "POST" and r[1].endswith("/git/commits")), 1)
        self.assertEqual(gh.read_file("brain/state", ".brain/status.md"), b"s\n")
        self.assertEqual(gh.refs["main"], root)
        # the next cycle reads the new head and extends the new file
        nxt = AP.TargetState(wr, gh.refs["brain/state"])
        AP.append_cycle(new, new, Reader(req({"row_id": "e3"})), nxt)
        self.assertTrue(chain.verify_bytes(gh.read_file("brain/state", ".brain/ledger.jsonl"), new)["valid"])

    def test_hard_stop_and_secret_send_nothing(self):
        gh, wr, head, _ = self.world()
        tampered = BASE.replace(b'"kind":"y"', b'"kind":"z"')
        with self.assertRaises(AP.HardStop):
            AP.append_cycle(tampered, BASE, Reader(req({"row_id": "n"})), AP.TargetState(wr, head))
        with self.assertRaises(AP.SecretRow):
            AP.append_cycle(BASE, BASE, Reader(req({"row_id": "n", "note": TOKEN})), AP.TargetState(wr, head))
        self.assertEqual(gh.requests, [])
        self.assertEqual(gh.refs["brain/state"], head)

    def test_a_stale_head_writes_nothing(self):
        gh, wr, head, _ = self.world()
        moved = gh.seed_commit("s1", [head], files={".brain/ledger.jsonl": BASE})
        gh.refs["brain/state"] = moved
        with self.assertRaises(W.Refused):
            AP.append_cycle(BASE, BASE, Reader(req({"row_id": "n"})), AP.TargetState(wr, head))
        self.assertEqual([r[0] for r in gh.requests], ["GET"])
        self.assertEqual(gh.refs["brain/state"], moved)


def run(args, stdin=b""):
    proc = subprocess.run([sys.executable, "-m"] + args, input=stdin, capture_output=True, cwd=REFEREE, timeout=60)
    return proc.returncode, json.loads(proc.stdout), proc.stderr.decode()


class CommandLine(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def file(self, name, data):
        path = os.path.join(self.tmp.name, name)
        with open(path, "wb") as fh:
            fh.write(data)
        return path

    def cycle(self, ledger, previous, stdin):
        return run(["ledger.append", "cycle", self.file("l", ledger), self.file("p", previous)], stdin)

    def test_written(self):
        code, out, _ = self.cycle(BASE, BASE, req({"row_id": "e2", "part": "events"}, {"row_id": "c2", "part": "cost"}))
        expected, _ = build([{"row_id": "e2", "part": "events"}, {"row_id": "c2", "part": "cost"}], TIP)
        self.assertEqual((code, out), (0, {"ok": True, "commits": 1, "hard_stop": False,
                                           "row_hashes": [json.loads(x)["row_hash"] for x in expected.splitlines()]}))

    def test_refused(self):
        refused = {"ok": False, "row_hashes": [], "commits": 0}
        tampered = BASE.replace(b'"kind":"y"', b'"kind":"z"')
        self.assertEqual(self.cycle(tampered, BASE, b"not json")[:2], (1, dict(refused, hard_stop=True)))
        self.assertEqual(self.cycle(BASE[:-5], BASE, req({"row_id": "n"}))[:2], (1, dict(refused, hard_stop=True)))
        code, out, err = self.cycle(BASE, BASE, req({"row_id": "n", "note": TOKEN}))
        self.assertEqual((code, out), (1, dict(refused, hard_stop=False)))
        self.assertNotIn(TOKEN, err)
        for bad in (b"not json", req({"row_id": "c1"}), req({"row_hash": TIP})):
            self.assertEqual(self.cycle(BASE, BASE, bad)[:2], (2, dict(refused, hard_stop=False)), bad)

    def test_unusable_command(self):
        refused = {"ok": False, "row_hashes": [], "commits": 0, "hard_stop": False}
        missing = os.path.join(self.tmp.name, "missing")
        self.assertEqual(run(["ledger.append", "cycle", missing, self.file("p", BASE)], req({}))[:2], (2, refused))
        self.assertEqual(run(["ledger.append", "cycle", self.file("l", BASE), missing], req({}))[:2], (2, refused))
        self.assertEqual(run(["ledger.append", "cycle", self.file("l", BASE)], req({}))[:2], (2, refused))
        self.assertEqual(run(["ledger.append", "verify", self.file("l", BASE), self.file("p", BASE)])[:2], (2, refused))

    def test_chain_previous_rewrite_and_truncated(self):
        rewritten, _ = build([{"row_id": "e1", "part": "events", "kind": "EDITED"},
                              {"row_id": "c1", "part": "cost", "kind": "y"}])
        truncated = BASE.split(b"\n", 1)[0] + b"\n"
        prev = self.file("p", BASE)
        for data in (rewritten, truncated):
            code, out, _ = run(["ledger.chain", "verify", self.file("l", data), "--previous", prev])
            self.assertEqual((code, out["valid"]), (1, False))
        self.assertEqual(run(["ledger.chain", "verify", self.file("l", BASE), "--previous", prev])[1]["valid"], True)


if __name__ == "__main__":
    unittest.main()
