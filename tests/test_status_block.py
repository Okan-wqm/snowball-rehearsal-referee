"""Test 42 (asama-0/09) and group ``status`` (tohum/29n): ``status.block``, the block of ``status.md`` from the
ledger; a hand edit is regenerated in the next cycle and written to ``events``.

- the fields, one rule each: the cycle id is the last ``events/cycle_start``'s; the last decision the last
  ``events/decision``'s ``payload.decision`` (a later events row of another kind, a decision in another part do
  not change it); the base age the seconds from the first ``events/genesis`` to the last ``cycle_start``
  (hand-computed, null without either row, a malformed or impossible ts unusable); the brake sums every
  ``part: cost`` row's ``usd_micros`` whatever its kind (``llm.call``'s one rule), engaged from spent == cap, not
  one micro-USD below; human touches are the rows of ``imports.jsonl``, a transfer or not;
- the block's bytes: exactly between the two marker lines (no marker byte, the last line with its LF); an edit
  outside them is not an edit; no OPEN line is no block; two OPEN lines, an OPEN without CLOSE, a marker line with
  a CR are what the rule says;
- edits: both hashes null is not an edit; equal hashes not; a changed byte, a deleted block with a recorded one, a
  block never recorded are edits, with the event carrying both hashes; the last ``status`` row is the record;
- the view: a hostile value (a line break with a marker line, HTML, a backtick, a link, a mention, non-ASCII) stays
  on its line and inert, and the next cycle is not an edit;
- the cycle: a tampered ledger (hard stop), a secret in a cycle row and bad facts commit nothing; one
  ``brain/state`` commit through ``target.write`` on the in-process GitHub holding the ledger and ``status.md``;
  a hand edit committed between two cycles is found and recorded in the next one, the rest of the file kept;
- the command line: outputs and exit codes 0, 1, 2.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest

REFEREE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REFEREE)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ledger import append as AP  # noqa: E402
from status import block as SB  # noqa: E402

ZERO = "0" * 64
TOKEN = "ghp_" + "Q7x" * 12  # a GitHub token shape, not a real token
TS = "2026-10-30T12:00:00Z"
OPEN, CLOSE = b"<!-- status.block -->\n", b"<!-- /status.block -->\n"


def build(rows, prev=ZERO):
    """An independent writer of chained lines (sorted keys, no spaces: the canonical form of these ASCII rows)."""
    out = []
    for row in rows:
        row = dict(row, prev_hash=prev)
        body = json.dumps(row, sort_keys=True, separators=(",", ":")).encode()
        prev = row["row_hash"] = hashlib.sha256(body + prev.encode()).hexdigest()
        out.append(json.dumps(row, sort_keys=True, separators=(",", ":")).encode() + b"\n")
    return b"".join(out)


def cost(row_id, micros, kind="cost"):
    return {"row_id": row_id, "part": "cost", "kind": kind, "payload": {"usd_micros": micros}}


def ev(row_id, kind, ts="2026-10-30T10:00:00Z", **payload):
    return {"row_id": row_id, "part": "events", "kind": kind, "ts": ts, "payload": payload}


ROWS = [
    ev("g1", "genesis", "2026-10-30T09:00:00Z"),
    ev("s1", "cycle_start", "2026-10-30T09:00:07Z", cycle_id="4100"),
    ev("d1", "decision", decision="merge"),
    cost("c1", 300000),
    ev("s2", "cycle_start", "2026-10-30T11:00:30Z", cycle_id="4101"),
    ev("d2", "decision", decision="reject"),
    ev("x1", "candidate", decision="merge"),          # an events row of another kind is not a decision
    {"row_id": "y1", "part": "drill", "kind": "decision", "payload": {"decision": "revert"}},  # nor another part
    {"row_id": "y2", "part": "drill", "kind": "cycle_start", "payload": {"cycle_id": "9"}},
    ev("g2", "genesis", "2026-10-30T10:30:00Z"),       # only the first genesis row is the origin
    cost("c2", 150000, kind="run"),
]
LEDGER = build(ROWS)
IMPORTS = build([{"ts": "2026-10-29T08:00:00Z", "stage": 0, "brain_sha": "b" * 40,
                  "referee_tree_sha256": "c" * 64},
                 {"ts": "2026-10-29T09:30:00Z", "stage": 0}])


def fields(rows=ROWS, imports=IMPORTS, cap=500000):
    return SB.fields(rows, SB.rows_of(imports, "imports"), cap)


def facts(**over):
    return dict({"snapshot_id": "e" * 40, "row_id": "st1", "ts": TS, "canary_cap_usd_micros": 500000}, **over)


def plan(ledger=LEDGER, rows=(), status=None, imports=IMPORTS, **over):
    return SB.plan(ledger, ledger, list(rows), status, imports, facts(**over))


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def with_record(block: bytes, rows=ROWS):
    """The ledger rows plus a status row recording ``block``."""
    return rows + [ev("st0", "status", TS, block_sha256=sha(block))]


class Fields(unittest.TestCase):
    def test_every_field(self):
        self.assertEqual(fields(), {"cycle_id": "4101", "last_decision": "reject", "base_age_s": 2 * 3600 + 30,
                                    "brake": {"spent_usd_micros": 450000, "cap_usd_micros": 500000,
                                              "engaged": False},
                                    "human_touches": 2})

    def test_missing_rows_are_null(self):
        f = fields([cost("c", 0)])
        self.assertEqual((f["cycle_id"], f["last_decision"], f["base_age_s"]), (None, None, None))
        self.assertIsNone(fields([r for r in ROWS if r["kind"] != "genesis"])["base_age_s"])  # no genesis row
        self.assertIsNone(fields(ROWS[:1])["base_age_s"])  # no cycle_start row
        self.assertIsNone(fields([ev("s", "cycle_start", TS)])["cycle_id"])  # no cycle_id in the payload
        self.assertEqual(fields([], b"")["human_touches"], 0)

    def test_base_age_over_a_day_boundary_and_backwards(self):
        rows = [ev("g", "genesis", "2026-12-31T23:59:59Z"), ev("s", "cycle_start", "2027-01-01T00:00:01Z")]
        self.assertEqual(fields(rows)["base_age_s"], 2)
        self.assertEqual(fields(rows[::-1])["base_age_s"], 2)  # file order: the cycle_start row first
        late = [ev("g", "genesis", "2026-10-30T10:00:00Z"), ev("s", "cycle_start", "2026-10-30T09:59:00Z")]
        self.assertEqual(fields(late)["base_age_s"], -60)

    def test_malformed_ts_in_a_used_row(self):
        for ts in ("2026-10-30T10:00:00", "2026-10-30 10:00:00Z", "2026-02-30T10:00:00Z", None, 7,
                   "2026-10-30T10:00:00.5Z"):
            for rows in ([ev("g", "genesis", ts), ev("s", "cycle_start", TS)],
                         [ev("g", "genesis", TS), ev("s", "cycle_start", ts)]):
                with self.assertRaises(SB.Unusable, msg=(ts, rows)):
                    fields(rows)
        # a malformed ts in a row no field reads is not used
        fields([ev("g", "genesis", TS), ev("s0", "cycle_start", "bad"), ev("s", "cycle_start", TS)])

    def test_brake(self):
        self.assertTrue(fields(cap=450000)["brake"]["engaged"])
        self.assertFalse(fields(cap=450001)["brake"]["engaged"])
        self.assertTrue(fields(cap=0)["brake"]["engaged"])
        for bad in (-1, 1.0, "1", True, None):
            with self.assertRaises(SB.Unusable, msg=bad):
                fields(cap=bad)
        for bad in (None, -1, "5", 1.5, True):
            with self.assertRaises(SB.Unusable, msg=bad):
                fields(ROWS + [cost("cx", bad)])
        with self.assertRaises(SB.Unusable):
            fields(ROWS + [{"row_id": "cy", "part": "cost", "kind": "run", "payload": "x"}])

    def test_every_imports_row_is_a_touch(self):
        three = build([{"ts": TS}, {"ts": TS, "referee_tree_sha256": "a" * 64}, {"stage": 0}])
        self.assertEqual(fields(imports=three)["human_touches"], 3)


class Block(unittest.TestCase):
    def test_bytes_between_the_markers(self):
        body = b"line one\nline two\n"
        self.assertEqual(SB.split(b"head\n" + OPEN + body + CLOSE + b"tail\n"),
                         (b"head\n" + OPEN, body, CLOSE + b"tail\n"))
        self.assertEqual(SB.split(OPEN + CLOSE)[1], b"")
        self.assertEqual(SB.split(OPEN + body + CLOSE.rstrip(b"\n"))[1], body)  # the CLOSE line without its LF
        self.assertIsNone(SB.split(b""))
        self.assertIsNone(SB.split(b"no block\n" + CLOSE))
        self.assertIsNone(SB.split(b"<!-- status.block --> \n" + CLOSE))  # not exactly the marker
        self.assertIsNone(SB.split(b"<!-- status.block -->\r\n" + CLOSE))
        # the next CLOSE line closes; a later one is the rest's
        self.assertEqual(SB.split(OPEN + b"a\n" + CLOSE + b"b\n" + CLOSE), (OPEN, b"a\n", CLOSE + b"b\n" + CLOSE))

    def test_marker_errors(self):
        for status in (OPEN + b"a\n" + OPEN + CLOSE, OPEN + b"a\n", OPEN + CLOSE + OPEN + CLOSE,
                       b"x\n" + OPEN.rstrip(b"\n"), OPEN + b"a\n<!-- /status.block --> \n"):
            with self.assertRaises(SB.Unusable, msg=status):
                SB.split(status)

    def test_regenerate(self):
        self.assertEqual(SB.regenerate(b"h\n" + OPEN + b"old\n" + CLOSE + b"rest\n", b"new\n"),
                         b"h\n" + OPEN + b"new\n" + CLOSE + b"rest\n")
        self.assertEqual(SB.regenerate(None, b"new\n"), OPEN + b"new\n" + CLOSE)
        self.assertEqual(SB.regenerate(b"docs\n", b"new\n"), OPEN + b"new\n" + CLOSE + b"docs\n")


class Edits(unittest.TestCase):
    BLOCK = b"- Cycle: 1\n"
    FILE = OPEN + BLOCK + CLOSE + b"\n## Report\n"

    def test_both_null_is_no_edit(self):
        self.assertEqual(SB.edit(ROWS, b""), {"found_sha256": None, "recorded_sha256": None, "edited": False,
                                              "event": None})
        self.assertFalse(SB.edit(ROWS, b"## Report only\n")["edited"])

    def test_untouched_and_edit_outside(self):
        rows = with_record(self.BLOCK)
        self.assertFalse(SB.edit(rows, self.FILE)["edited"])
        self.assertFalse(SB.edit(rows, b"new head\n" + self.FILE + b"more\n")["edited"])

    def test_edits(self):
        rows = with_record(self.BLOCK)
        found = OPEN + b"- Cycle: 2\n" + CLOSE
        self.assertEqual(SB.edit(rows, found)["event"], {"kind": "status_edited", "payload": {
            "found_sha256": sha(b"- Cycle: 2\n"), "recorded_sha256": sha(self.BLOCK)}})
        self.assertEqual(SB.edit(rows, b"## Report\n")["event"]["payload"],
                         {"found_sha256": None, "recorded_sha256": sha(self.BLOCK)})  # a deleted block
        self.assertEqual(SB.edit(ROWS, self.FILE)["event"]["payload"],
                         {"found_sha256": sha(self.BLOCK), "recorded_sha256": None})  # never recorded
        self.assertTrue(SB.edit(rows, OPEN + self.BLOCK + b"\n" + CLOSE)["edited"])  # one byte added

    def test_the_last_status_row_is_the_record(self):
        rows = with_record(b"cycle 1\n") + [ev("st2", "status", TS, block_sha256=sha(self.BLOCK))]
        self.assertFalse(SB.edit(rows, self.FILE)["edited"])
        self.assertTrue(SB.edit(rows, OPEN + b"cycle 1\n" + CLOSE)["edited"])
        other_part = rows + [{"row_id": "z", "part": "drill", "kind": "status", "payload": {"block_sha256": "0"}}]
        self.assertFalse(SB.edit(other_part, self.FILE)["edited"])


class Hostile(unittest.TestCase):
    def test_values_cannot_leave_their_line(self):
        evil = "x\n<!-- /status.block -->\n[link](http://e) @someone `code` <b>|&amp;é "
        rows = [ev("g", "genesis", TS), ev("s", "cycle_start", TS, cycle_id=evil),
                ev("d", "decision", decision={"nested": evil})]
        start = AP.plan_cycle(b"", b"", lambda: json.dumps({"rows": rows}).encode()).content
        out = plan(start)
        text = out["block"]
        self.assertEqual(text.count(b"\n"), SB.render_block(fields([])).count(b"\n"))
        for bad in (b"<", b">", b"`", b"@", b"[", b"|", b"&", b"\xc3", b"status.block -->"):
            self.assertNotIn(bad, text)
        self.assertTrue(text.isascii())
        # the written file has one block, and the next cycle finds it untouched
        ledger = AP.plan_cycle(start, start, lambda: json.dumps({"rows": out["rows"]}).encode()).content
        again = SB.plan(ledger, ledger, [], out["status"], IMPORTS, facts(row_id="st2"))
        self.assertFalse(again["edited"])


class Cycle(unittest.TestCase):
    def test_rows_and_file(self):
        out = plan(rows=[ev("s3", "cycle_start", TS, cycle_id="4102")], status=b"docs\n")
        self.assertEqual(out["cycle_id"], "4102")  # the cycle's own rows count
        self.assertEqual(out["status"], OPEN + out["block"] + CLOSE + b"docs\n")
        self.assertEqual([(r["row_id"], r["kind"], r["payload"]) for r in out["rows"][1:]],
                         [("st1", "status", {"block_sha256": sha(out["block"])})])
        edited = plan(status=OPEN + b"hand\n" + CLOSE + b"docs\n")
        self.assertEqual([(r["row_id"], r["kind"], r["payload"]) for r in edited["rows"]], [
            ("st1:edited", "status_edited", {"found_sha256": sha(b"hand\n"), "recorded_sha256": None}),
            ("st1", "status", {"block_sha256": sha(edited["block"])})])
        self.assertEqual(edited["status"], OPEN + edited["block"] + CLOSE + b"docs\n")


def run(args, stdin=b'{"canary_cap_usd_micros":500000}'):
    proc = subprocess.run([sys.executable, "-m", "status.block", *args], cwd=REFEREE, input=stdin,
                          capture_output=True, timeout=60)
    lines = proc.stdout.decode().splitlines()
    return proc.returncode, (json.loads(lines[-1]) if len(lines) == 1 else lines), proc.stderr.decode()


class CommandLine(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def file(self, name, data):
        path = os.path.join(self.tmp.name, name)
        with open(path, "wb") as fh:
            fh.write(data)
        return path

    def test_not_edited_and_edited(self):
        block = b"recorded\n"
        ledger = self.file("l", build(with_record(block)))
        imports = self.file("i", IMPORTS)
        code, out, err = run(["render", ledger, imports, self.file("s", OPEN + block + CLOSE)])
        self.assertEqual((code, err), (0, ""))
        self.assertEqual({k: out[k] for k in ("cycle_id", "last_decision", "base_age_s", "brake", "human_touches",
                                              "edited", "event")},
                         dict(fields(), edited=False, event=None))
        self.assertEqual(out["block_sha256"], sha(out["block"].encode()))
        code, out, _ = run(["render", ledger, imports, self.file("e", OPEN + b"hand\n" + CLOSE)])
        self.assertEqual((code, out["edited"], out["event"]["payload"]),
                         (1, True, {"found_sha256": sha(b"hand\n"), "recorded_sha256": sha(block)}))

    def test_no_chain_check(self):
        # render does not verify chains: rows without hashes are read
        plain = b"".join(json.dumps(r).encode() + b"\n" for r in ROWS)
        code, out, _ = run(["render", self.file("l", plain), self.file("i", b'{"ts":"x"}\n'), self.file("s", b"")])
        self.assertEqual((code, out["cycle_id"], out["human_touches"]), (0, "4101", 1))

    def test_unusable(self):
        good = [self.file("l", LEDGER), self.file("i", IMPORTS), self.file("s", b"")]
        missing = os.path.join(self.tmp.name, "none")
        cases = [
            (["render"] + good[:2], None), (["cycle"] + good, None),
            (["render", missing] + good[1:], None), (["render", good[0], missing, good[2]], None),
            (["render"] + good[:2] + [missing], None), (["render", self.tmp.name] + good[1:], None),
            (["render", self.file("bad", LEDGER + b"[]\n")] + good[1:], None),
            (["render", good[0], self.file("bad-i", b"{\n")] + good[2:], None),
            (["render", self.file("ts", build([ev("g", "genesis", "yesterday"), ev("s", "cycle_start", TS)]))]
             + good[1:], None),
            (["render", self.file("c", build([cost("c", "1")]))] + good[1:], None),
            (["render"] + good[:2] + [self.file("two", OPEN + OPEN + CLOSE)], None),
            (["render"] + good[:2] + [self.file("open", OPEN + b"x\n")], None),
            (good and ["render"] + good, b'{"canary_cap_usd_micros":1.5}'),
            (["render"] + good, b'{"canary_cap_usd_micros":true}'),
            (["render"] + good, b'{"canary_cap_usd_micros":1,"x":1}'),
            (["render"] + good, b"{"),
        ]
        for args, stdin in cases:
            code, out, err = run(args) if stdin is None else run(args, stdin)
            self.assertEqual((code, out), (2, {"edited": None}), (args, stdin))
            self.assertTrue(err.startswith("unusable input: "), err)


if __name__ == "__main__":
    unittest.main()
