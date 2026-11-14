"""Test 40 (asama-0/09) and group ``root`` (tohum/29j): ``rekor.anchor`` with a fake signer.

- root: interleaved parts give each part's last stored ``row_hash`` (neither the file's last row nor the part's
  first row); the root is checked against a hand-written canonical text; a new row moves only its part's tip;
  a ledger broken in the middle (where no tip sees it), a row without ``part`` and an empty ledger are unusable;
- anchor: the signer signs the root's hex text as its payload, the entry is ``{uuid, hash: root, identity}``;
  an unavailable signer or one that answers no entry is a hard stop; malformed requests and signers are exit 2;
- verify: each reason from its own case and alone, the closed order when several hold, ``entry_missing``
  suppressing the other two, only the last line of the root file read, unusable files exit 2;
- the cycle: one commit with the new ledger and the chained root row, which the next D1 verifies; an
  unsignable root, a rewritten root file and a repeated root row id commit nothing; on the in-process GitHub
  one ``POST git/commits`` sets both files on ``brain/state`` and ``main`` never moves;
- the command lines, outputs and exits.
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

from ledger import anchor as AN  # noqa: E402
from ledger import append as AP  # noqa: E402

ZERO = "0" * 64
WORKFLOW = "https://github.com/acme/referee/.github/workflows/loop.yml@refs/heads/main"


def build(rows, prev=ZERO):
    """An independent writer of chained lines (sorted-key json.dumps is the canonical form for these ASCII rows)."""
    out, hashes = [], []
    for row in rows:
        row = dict(row, prev_hash=prev)
        body = json.dumps(row, sort_keys=True, separators=(",", ":")).encode()
        prev = row["row_hash"] = hashlib.sha256(body + prev.encode()).hexdigest()
        hashes.append(prev)
        out.append(json.dumps(row, sort_keys=True, separators=(",", ":")).encode() + b"\n")
    return b"".join(out), hashes


ROWS = [{"row_id": "e1", "part": "events", "kind": "a"}, {"row_id": "c1", "part": "cost", "kind": "b"},
        {"row_id": "e2", "part": "events", "kind": "c"}, {"row_id": "d1", "part": "drill", "kind": "d"},
        {"row_id": "c2", "part": "cost", "kind": "e"}, {"row_id": "e3", "part": "events", "kind": "f"},
        {"row_id": "c3", "part": "cost", "kind": "g"}]
LEDGER, H = build(ROWS)


def hand_canonical(tips):
    return ("{" + ",".join('"%s":"%s"' % (k, tips[k]) for k in sorted(tips)) + "}").encode()


def hand_root(tips):
    return hashlib.sha256(hand_canonical(tips)).hexdigest()


class Root(unittest.TestCase):
    def test_part_tips(self):
        tips = AN.tips(LEDGER)
        self.assertEqual(tips, {"events": H[5], "cost": H[6], "drill": H[3]})
        # the events tip is neither the file's last row nor the part's first row
        self.assertNotEqual(tips["events"], H[-1])
        self.assertNotEqual(tips["events"], H[0])
        self.assertEqual(AN.root_of(tips), hand_root({"events": H[5], "cost": H[6], "drill": H[3]}))

    def test_a_new_row_moves_only_its_part(self):
        more, h2 = build(ROWS + [{"row_id": "d2", "part": "drill", "kind": "h"}])
        before, after = AN.tips(LEDGER), AN.tips(more)
        self.assertEqual(after, dict(before, drill=h2[-1]))
        self.assertNotEqual(AN.root_of(after), AN.root_of(before))

    def test_root_depends_on_the_part_name(self):
        renamed, _ = build([dict(r, part="drills" if r["part"] == "drill" else r["part"]) for r in ROWS])
        self.assertIn("drills", AN.tips(renamed))
        self.assertNotEqual(AN.root_of(AN.tips(renamed)), AN.root_of(AN.tips(LEDGER)))

    def test_a_break_no_tip_sees_is_unusable(self):
        # row e2 edited, hashes not recomputed: every tip is unchanged, the chain is not
        broken = LEDGER.replace(b'"kind":"c"', b'"kind":"X"')
        self.assertEqual(broken.count(b'"kind":"X"'), 1)
        with self.assertRaisesRegex(AN.Unusable, "not a valid chain"):
            AN.tips(broken)

    def test_rows_need_a_part_and_a_ledger_needs_a_row(self):
        for bad in ({"row_id": "x", "kind": "a"}, {"row_id": "x", "part": ""}, {"row_id": "x", "part": 7}):
            data, _ = build([ROWS[0], bad])
            with self.assertRaisesRegex(AN.Unusable, "line 2 has no part"):
                AN.tips(data)
        with self.assertRaisesRegex(AN.Unusable, "empty ledger"):
            AN.tips(b"")


class Signer(unittest.TestCase):
    def test_anchor_signs_the_roots_preimage(self):
        tip_map = AN.tips(LEDGER)
        root = AN.root_of(tip_map)
        signer = AN.FakeSigner(True, WORKFLOW, "uuid-1")
        entry, bundle = AN.anchor(tip_map, signer)
        self.assertEqual(entry, {"uuid": "uuid-1", "hash": root, "identity": WORKFLOW})
        # tohum/26d "Kök": the hash of the signed data is the root itself, the sha256 of the tips' RFC 8785 bytes
        self.assertEqual(signer.payloads, [hand_canonical(tip_map)])
        self.assertEqual([hashlib.sha256(p).hexdigest() for p in signer.payloads], [root])
        # the stand-in's bundle names what it was asked to sign; it is no Sigstore bundle
        self.assertEqual(json.loads(bundle), {"uuid": "uuid-1", "identity": WORKFLOW, "fake_signed_sha256": root})
        self.assertTrue(bundle.endswith(b"\n"))

    def test_unsignable_hard_stop(self):
        signer = AN.FakeSigner(False)
        with self.assertRaises(AN.Unsignable):
            AN.anchor(AN.tips(LEDGER), signer)
        with self.assertRaises(AN.Unsignable):
            signer.answer()
        self.assertTrue(issubclass(AN.Unsignable, AP.HardStop))
        self.assertEqual(signer.payloads, [])

    def test_a_signer_that_answers_no_entry_or_no_bundle_is_a_hard_stop(self):
        class Silent:
            def __init__(self, answer):
                self.answer = answer

            def sign(self, payload):
                return self.answer

        good = {"uuid": "u", "identity": WORKFLOW, "bundle": b"{}"}
        self.assertEqual(AN.anchor(AN.tips(LEDGER), Silent(good))[1], b"{}")
        for answer in (None, {}, {"uuid": "u", "bundle": b"{}"}, dict(good, uuid=""), dict(good, identity=3),
                       {"uuid": "u", "identity": WORKFLOW}, dict(good, bundle=b""), dict(good, bundle="{}"),
                       dict(good, bundle=None)):
            with self.assertRaises(AN.Unsignable):
                AN.anchor(AN.tips(LEDGER), Silent(answer))

    def test_root_text_is_64_lowercase_hex(self):
        for bad in ("A" * 64, "a" * 63, "a" * 65, 7, None, "g" * 64):
            with self.assertRaises(AN.Unusable):
                AN.entry_of(bad, {"uuid": "u", "identity": WORKFLOW})
        self.assertEqual(AN.entry_of("a" * 64, {"uuid": "u", "identity": WORKFLOW}),
                         {"uuid": "u", "hash": "a" * 64, "identity": WORKFLOW})

    def test_signer_file_shape(self):
        for bad in ({"available": "true", "identity": WORKFLOW, "uuid": "u"}, {"available": 1, "identity": WORKFLOW, "uuid": "u"},
                    {"available": True, "identity": WORKFLOW}, {"available": True, "identity": "", "uuid": "u"}, []):
            with self.assertRaises(AN.Unusable):
                AN.FakeSigner.from_json(bad)
        self.assertFalse(AN.FakeSigner.from_json({"available": False}).available)


def roots_file(*pairs):
    data = b""
    for i, (root, uuid) in enumerate(pairs, 1):
        data = AN.root_row(data, "r%d" % i, "2026-10-30T00:00:0%dZ" % i, root, uuid)
    return data


class Verify(unittest.TestCase):
    def setUp(self):
        self.root = AN.root_of(AN.tips(LEDGER))
        self.roots = roots_file(("b" * 64, "old"), (self.root, "uuid-1"))
        self.rekor = {"entries": {"uuid-1": {"hash": self.root, "identity": WORKFLOW}, "old": {"hash": "b" * 64, "identity": WORKFLOW}}}

    def check(self, ledger=None, roots=None, rekor=None, identity=WORKFLOW):
        return AN.verify(LEDGER if ledger is None else ledger, self.roots if roots is None else roots,
                         self.rekor if rekor is None else rekor, identity)

    def test_verify_good(self):
        self.assertEqual(self.check(), {"valid": True, "reasons": []})

    def test_verify_tip_moved(self):
        moved, _ = build(ROWS + [{"row_id": "e4", "part": "events", "kind": "z"}])
        self.assertEqual(self.check(ledger=moved), {"valid": False, "reasons": ["root_mismatch"]})

    def test_verify_identity_pin(self):
        self.rekor["entries"]["uuid-1"]["identity"] = WORKFLOW.replace("loop.yml", "other.yml")
        self.assertEqual(self.check(), {"valid": False, "reasons": ["identity_mismatch"]})
        self.assertEqual(self.check(identity=WORKFLOW + "x"), {"valid": False, "reasons": ["identity_mismatch"]})

    def test_verify_entry_other_root(self):
        self.rekor["entries"]["uuid-1"]["hash"] = "c" * 64
        self.assertEqual(self.check(), {"valid": False, "reasons": ["entry_root_mismatch"]})

    def test_verify_entry_missing(self):
        del self.rekor["entries"]["uuid-1"]
        self.assertEqual(self.check(), {"valid": False, "reasons": ["entry_missing"]})
        # the entry is missing: neither its hash nor its identity is judged, the root still is
        moved, _ = build(ROWS[:-1])
        self.assertEqual(self.check(ledger=moved, identity="other"), {"valid": False, "reasons": ["root_mismatch", "entry_missing"]})

    def test_reasons_in_order(self):
        moved, _ = build(ROWS[:-1])
        self.rekor["entries"]["uuid-1"] = {"hash": "c" * 64, "identity": "someone"}
        self.assertEqual(self.check(ledger=moved)["reasons"], ["root_mismatch", "entry_root_mismatch", "identity_mismatch"])

    def test_entry_hash_is_compared_with_the_recorded_root(self):
        # the ledger moved and the entry signs the ledger's new root: the record still names the old one
        moved, _ = build(ROWS[:-1])
        self.rekor["entries"]["uuid-1"]["hash"] = AN.root_of(AN.tips(moved))
        self.assertEqual(self.check(ledger=moved)["reasons"], ["root_mismatch", "entry_root_mismatch"])

    def test_only_the_last_root_row_is_read(self):
        # an earlier row naming a missing entry does not count; only the last row decides
        roots = roots_file(("d" * 64, "nowhere"), (self.root, "uuid-1"))
        self.assertTrue(self.check(roots=roots)["valid"])
        # the same rows reversed: the last row now names the missing entry
        roots = roots_file((self.root, "uuid-1"), ("d" * 64, "nowhere"))
        self.assertEqual(self.check(roots=roots)["reasons"], ["root_mismatch", "entry_missing"])

    def test_unusable_inputs(self):
        cases = [dict(roots=b""), dict(roots=b"not json\n"), dict(roots=b'{"root": "%s"}\n' % self.root.encode()),
                 dict(roots=b'{"root": "%s", "rekor_uuid": ""}\n' % self.root.encode()),
                 dict(roots=b'{"root": "%s", "rekor_uuid": "u"}\n' % self.root.upper().encode()),
                 dict(rekor={}), dict(rekor={"entries": []}), dict(rekor={"entries": {"uuid-1": {"hash": self.root}}}),
                 dict(identity=""), dict(identity=None), dict(ledger=LEDGER.replace(b'"kind":"c"', b'"kind":"X"'))]
        for case in cases:
            with self.subTest(case=case), self.assertRaises(AN.Unusable):
                self.check(**case)


class CommandLine(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def file(self, name, data):
        path = os.path.join(self.tmp.name, name)
        with open(path, "wb") as fh:
            fh.write(data if isinstance(data, bytes) else json.dumps(data).encode())
        return path

    def run_cli(self, args, stdin=b""):
        proc = subprocess.run([sys.executable, "-m", "ledger.anchor"] + args, input=stdin, capture_output=True,
                              cwd=REFEREE, timeout=60)
        lines = proc.stdout.decode().splitlines()
        self.assertEqual(len(lines), 1, proc.stdout)
        return proc.returncode, json.loads(lines[0]), proc.stderr.decode()

    def test_root(self):
        code, out, _ = self.run_cli(["root", self.file("l", LEDGER)])
        self.assertEqual((code, out), (0, {"tips": {"events": H[5], "cost": H[6], "drill": H[3]},
                                           "root": hand_root({"events": H[5], "cost": H[6], "drill": H[3]})}))
        code, out, err = self.run_cli(["root", self.file("b", LEDGER.replace(b'"kind":"c"', b'"kind":"X"'))])
        self.assertEqual((code, out), (2, {"tips": None, "root": None}))
        self.assertIn("not a valid chain", err)
        self.assertEqual(self.run_cli(["root", os.path.join(self.tmp.name, "missing")])[:2], (2, {"tips": None, "root": None}))

    def test_anchor(self):
        root = "ab" * 32
        signer = self.file("s", {"available": True, "identity": WORKFLOW, "uuid": "uuid-1", "note": "ignored"})
        code, out, _ = self.run_cli(["anchor", signer], json.dumps({"root": root}).encode())
        self.assertEqual((code, out), (0, {"ok": True, "hard_stop": False, "entry": {"uuid": "uuid-1", "hash": root, "identity": WORKFLOW}}))
        code, out, err = self.run_cli(["anchor", self.file("n", {"available": False, "identity": WORKFLOW, "uuid": "u"})],
                                      json.dumps({"root": root}).encode())
        self.assertEqual((code, out), (1, {"ok": False, "hard_stop": True, "entry": None}))
        self.assertIn("hard stop", err)
        for stdin in (b'{"root": "%s", "x": 1}' % root.encode(), b'{"root": "%s"}' % root.upper().encode(), b"",
                      b'{"root": "%s", "root": "%s"}' % (root.encode(), root.encode())):
            self.assertEqual(self.run_cli(["anchor", signer], stdin)[:2], (2, {"ok": False, "hard_stop": False, "entry": None}))
        self.assertEqual(self.run_cli(["anchor", self.file("x", {"available": "yes"})], json.dumps({"root": root}).encode())[:2],
                         (2, {"ok": False, "hard_stop": False, "entry": None}))

    def test_verify(self):
        root = AN.root_of(AN.tips(LEDGER))
        roots = self.file("r", roots_file((root, "uuid-1")))
        rekor = {"entries": {"uuid-1": {"hash": root, "identity": WORKFLOW, "logIndex": 7}}}
        args = ["verify", self.file("l", LEDGER), roots, self.file("k", rekor)]
        self.assertEqual(self.run_cli(args, json.dumps({"identity": WORKFLOW}).encode())[:2], (0, {"valid": True, "reasons": []}))
        self.assertEqual(self.run_cli(args, json.dumps({"identity": "x"}).encode())[:2],
                         (1, {"valid": False, "reasons": ["identity_mismatch"]}))
        self.assertEqual(self.run_cli(args, json.dumps({"identity": WORKFLOW, "more": 1}).encode())[:2],
                         (2, {"valid": False, "reasons": []}))
        self.assertEqual(self.run_cli(["verify", self.file("l", LEDGER), roots], json.dumps({"identity": WORKFLOW}).encode())[:2],
                         (2, {"error": "usage"}))


if __name__ == "__main__":
    unittest.main()
