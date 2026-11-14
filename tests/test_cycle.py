"""``ledger.cycle``: the cycle's one ``brain/state`` commit (rows, ``status.md``, signed root), planned in one place.

Moved here from test_anchor (``anchor_cycle``) and test_status_block (``status_cycle``), the two compositions
``ledger.cycle`` replaced, with schema rows (``ledger.cycle`` refuses a ledger of another shape); added: the schema
check of the new ledger, the root row checked before the signer is asked, the orphan plan the activation commits.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import unittest

REFEREE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REFEREE)
sys.path.insert(0, os.path.join(REFEREE, "tests"))

from ledger import anchor as AN  # noqa: E402
from ledger import append as AP  # noqa: E402
from ledger import chain  # noqa: E402
from ledger import cycle as CY  # noqa: E402
from ledger import schema  # noqa: E402
from status import block as SB  # noqa: E402
from target import branches as B  # noqa: E402
from target import write as W  # noqa: E402
from fake_github import FakeGitHub  # noqa: E402
from test_revert_drill import ledger_with, row  # noqa: E402

TOKEN = "ghp_" + "Q7x" * 12  # a GitHub token shape, not a real token
TS = "2026-10-30T12:00:00Z"
WORKFLOW = "https://github.com/acme/referee/.github/workflows/loop.yml@refs/heads/main"
OPEN, CLOSE = b"<!-- status.block -->\n", b"<!-- /status.block -->\n"
MERGE = "a" * 40
LEDGER = ledger_with([row("s1", "events", "cycle_start", {"cycle_id": "4100"}),
                      row("d1", "events", "decision", {"decision": "merge", "candidate": "c1"}),
                      row("m1", "events", "merge", {"candidate": "c1", "path": "src/a.js", "pull": 1,
                                                    "head_sha": "b" * 40, "merge_sha": MERGE, "hunk_covered": []})])
IMPORTS = ledger_with([{"ts": "2026-10-29T08:00:00Z", "stage": 0}])


def facts(**over):
    return dict({"snapshot_id": "e" * 40, "row_id": "st1", "ts": TS, "canary_cap_usd_micros": 500000}, **over)


def start(row_id="s2", cycle_id="4101"):
    return row(row_id, "events", "cycle_start", {"cycle_id": cycle_id})


def reject(row_id="d2", reasons=("scope_violation",)):
    return row(row_id, "events", "decision", {"decision": "reject", "candidate": "c2", "reasons": list(reasons)},
               "scope_violation")


def signer(uuid="uuid-1", available=True):
    return AN.FakeSigner(available, WORKFLOW if available else None, uuid if available else None)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def plan(ledger=LEDGER, previous=None, roots=b"", previous_roots=None, status=None, rows=None, fx=None, sign=None,
         root_row_id="r1"):
    return CY.plan(ledger, ledger if previous is None else previous, roots,
                   roots if previous_roots is None else previous_roots, status,
                   [start()] if rows is None else rows, IMPORTS, facts() if fx is None else fx,
                   signer() if sign is None else sign, root_row_id)


def roots_file(*pairs):
    out = b""
    for i, (root, uuid) in enumerate(pairs):
        out = AN.root_row(out, "r%d" % i, TS, root, uuid)
    return out


class Plan(unittest.TestCase):
    def test_the_files_hold_the_rows_the_block_and_the_signed_root(self):
        sign = signer()
        out = plan(rows=[start(), reject()], status=b"docs\n", sign=sign)
        self.assertEqual(set(out["files"]), {".brain/ledger.jsonl", ".brain/chain/root.jsonl", ".brain/status.md",
                                             ".brain/chain/%s.sigstore.json" % out["root"]})
        ledger, roots = out["files"][".brain/ledger.jsonl"], out["files"][".brain/chain/root.jsonl"]
        self.assertTrue(chain.verify_bytes(ledger, LEDGER)["valid"])
        self.assertEqual(schema.ledger_reasons(ledger), [])
        new = [json.loads(line) for line in ledger.splitlines()[3:]]
        self.assertEqual([(r["row_id"], r["kind"]) for r in new], [("s2", "cycle_start"), ("d2", "decision"),
                                                                   ("st1", "status")])
        self.assertEqual(out["row_hashes"], [r["row_hash"] for r in new])
        # the block counts the cycle's own rows and is recorded by the status row
        block = SB.split(out["files"][".brain/status.md"])[1]
        self.assertIn(b'"4101"', block)
        self.assertEqual(out["files"][".brain/status.md"], OPEN + block + CLOSE + b"docs\n")
        self.assertEqual(new[-1]["payload"], {"block_sha256": sha(block)})
        self.assertEqual((out["block_sha256"], out["edited"]), (sha(block), False))
        self.assertEqual(schema.status_reasons(out["files"][".brain/status.md"], ledger), [])
        # the signed root is the new ledger's, recorded in one chained root row
        self.assertEqual(out["root"], AN.root_of(AN.tips(ledger)))
        self.assertEqual([sha(p) for p in sign.payloads], [out["root"]])  # the data signed hashes to the root itself
        # the signer's bundle, as it gave it, beside the root row that names the root (tohum/26d "Yer")
        last = json.loads(roots.splitlines()[-1])
        self.assertEqual(last["root"], out["root"])
        self.assertEqual(json.loads(out["files"][".brain/chain/%s.sigstore.json" % last["root"]]),
                         {"uuid": "uuid-1", "identity": WORKFLOW, "fake_signed_sha256": out["root"]})
        self.assertEqual(schema.roots_reasons(roots), [])
        self.assertEqual(json.loads(roots)["root"], out["root"])
        self.assertEqual(AN.verify(ledger, roots, {"entries": {"uuid-1": out["entry"]}}, WORKFLOW),
                         {"valid": True, "reasons": []})

    def test_the_next_cycle_chains_onto_this_one(self):
        first = plan()
        led, roots = first["files"][".brain/ledger.jsonl"], first["files"][".brain/chain/root.jsonl"]
        second = plan(ledger=led, roots=roots, status=first["files"][".brain/status.md"], rows=[start("s3", "4102")],
                      fx=facts(row_id="st2"), sign=signer("uuid-2"), root_row_id="r2")
        led2, roots2 = second["files"][".brain/ledger.jsonl"], second["files"][".brain/chain/root.jsonl"]
        self.assertTrue(chain.verify_bytes(led2, led)["valid"])
        self.assertTrue(chain.verify_bytes(roots2, roots)["valid"])
        self.assertFalse(second["edited"])
        rekor = {"entries": {"uuid-1": first["entry"], "uuid-2": second["entry"]}}
        self.assertTrue(AN.verify(led2, roots2, rekor, WORKFLOW)["valid"])
        self.assertEqual(AN.verify(led, roots2, rekor, WORKFLOW)["reasons"], ["root_mismatch"])

    def test_a_hand_edited_block_is_regenerated_and_recorded(self):
        first = plan(status=b"docs\n")
        led = first["files"][".brain/ledger.jsonl"]
        block = SB.split(first["files"][".brain/status.md"])[1]
        hand = OPEN + b"hand\n" + CLOSE + b"docs\n"
        second = plan(ledger=led, roots=first["files"][".brain/chain/root.jsonl"], status=hand, rows=[],
                      fx=facts(row_id="st2"), root_row_id="r2")
        self.assertTrue(second["edited"])
        new = [json.loads(line) for line in second["files"][".brain/ledger.jsonl"].splitlines()[len(led.splitlines()):]]
        self.assertEqual([(r["kind"], r["payload"]) for r in new],
                         [("status_edited", {"found_sha256": sha(b"hand\n"), "recorded_sha256": sha(block)}),
                          ("status", {"block_sha256": second["block_sha256"]})])
        self.assertTrue(second["files"][".brain/status.md"].endswith(CLOSE + b"docs\n"))

    def test_the_orphan_plan_of_the_activation(self):
        out = plan(ledger=b"", roots=b"", rows=[row("g", "events", "cycle_start", {"cycle_id": "1"})])
        self.assertTrue(chain.verify_bytes(out["files"][".brain/ledger.jsonl"])["valid"])
        self.assertEqual(len(out["files"][".brain/ledger.jsonl"].splitlines()), 2)
        self.assertEqual(json.loads(out["files"][".brain/chain/root.jsonl"])["prev_hash"], chain.ZERO_HASH)


class Refusals(unittest.TestCase):
    """Every refusal signs nothing and returns nothing; the order is the module docstring's."""

    def refused(self, exc, **kw):
        sign = kw.pop("sign", None) or signer()
        with self.assertRaises(exc):
            plan(sign=sign, **kw)
        self.assertEqual(sign.payloads, [])

    def test_a_roots_file_that_is_no_extension_stops_before_the_ledger_and_the_facts(self):
        roots = roots_file(("a" * 64, "u1"), ("b" * 64, "u2"))
        for current in (roots_file(("c" * 64, "u1"), ("b" * 64, "u2")), roots[:-10], roots.replace(b"u2", b"u3")):
            with self.subTest(current=current):
                self.refused(AP.HardStop, roots=current, previous_roots=roots, fx=None)  # facts unread

    def test_a_ledger_that_is_no_extension_stops_before_the_facts(self):
        tampered = LEDGER.replace(b'"cycle_id":"4100"', b'"cycle_id":"4109"', 1)
        self.refused(AP.HardStop, ledger=tampered, previous=LEDGER)
        self.refused(AP.HardStop, ledger=tampered, previous=LEDGER, fx={"not": "facts"})

    def test_the_facts_and_the_status_file(self):
        for bad in (facts(extra=1), facts(ts="now"), facts(row_id=""), facts(canary_cap_usd_micros=-1),
                    {k: v for k, v in facts().items() if k != "snapshot_id"}):
            with self.subTest(facts=bad):
                self.refused(SB.Unusable, fx=bad)
        self.refused(SB.Unusable, status=OPEN + b"x\n")

    def test_a_secret_in_a_row(self):
        self.refused(AP.SecretRow, rows=[reject(reasons=["leak:" + TOKEN])])

    def test_a_row_id_the_ledger_already_has(self):
        self.refused(AP.Unusable, rows=[start("d1")])
        self.refused(AP.Unusable, fx=facts(row_id="s1"))

    def test_a_ledger_not_of_the_schema(self):
        cases = {"unknown type": [row("x1", "events", "candidate", {})],
                 "payload shape": [row("x1", "events", "merge", {"candidate": "c"})],
                 "reject without cause": [row("x1", "events", "decision",
                                              {"decision": "reject", "candidate": "c", "reasons": ["r"]})]}
        for name, rows in cases.items():
            with self.subTest(case=name):
                self.refused(CY.Unusable, rows=rows)
        self.refused(AP.Unusable, rows=[dict(start("x1"), payload={"cycle_id": "1", "n": 1.5})])  # no canonical form
        # an old row of no schema type is refused too: the whole ledger is the loop's
        old = ledger_with([{"row_id": "o1", "part": "events", "kind": "a"}])
        self.refused(CY.Unusable, ledger=old)

    def test_the_root_row_is_checked_before_the_signer_is_asked(self):
        roots = roots_file(("a" * 64, "u1"))
        for row_id in ("r0", "", None):
            with self.subTest(row_id=row_id):
                self.refused(CY.Unusable, roots=roots, root_row_id=row_id)

    def test_unsignable(self):
        sign = signer(available=False)
        with self.assertRaises(AN.Unsignable):
            plan(sign=sign)
        self.assertTrue(issubclass(AN.Unsignable, AP.HardStop))


class Commit(unittest.TestCase):
    def test_one_commit_or_none(self):
        state = AP.CountingState()
        out = CY.commit(state, "m", LEDGER, LEDGER, b"", b"", None, [start()], IMPORTS, facts(), signer(), "r1")
        self.assertEqual((state.commits, state.files), (1, out["files"]))
        with self.assertRaises(AP.HardStop):
            CY.commit(state, "m", LEDGER, LEDGER, b"", b"", None, [start()], IMPORTS, facts(), signer(available=False),
                      "r1")
        self.assertEqual(state.commits, 1)

    def test_two_cycles_on_the_target_and_a_hand_edit_between(self):
        gh = FakeGitHub("acme/toy")
        gh.refs["main"] = main = gh.seed_commit("t0")
        gh.refs["brain/state"] = head = gh.seed_commit("s0", files={".brain/ledger.jsonl": LEDGER})
        wr = W.Writer("acme/toy", gh)
        with self.assertRaises(AN.Unsignable):
            CY.commit(AP.TargetState(wr, head), "m", LEDGER, LEDGER, b"", b"", None, [start()], IMPORTS, facts(),
                      signer(available=False), "r1")
        self.assertEqual(gh.requests, [])
        first = CY.commit(AP.TargetState(wr, head), "cycle 4101", LEDGER, LEDGER, b"", b"", None, [start()], IMPORTS,
                          facts(), signer(), "r1")
        self.assertEqual(sum(1 for r in gh.requests if r[0] == "POST" and r[1].endswith("/git/commits")), 1)
        self.assertEqual(gh.commits[gh.refs["brain/state"]]["parents"], [head])
        for path, data in first["files"].items():
            self.assertEqual(gh.read_file("brain/state", path), data)
        led1, roots1 = first["files"][".brain/ledger.jsonl"], first["files"][".brain/chain/root.jsonl"]
        hand = gh.read_file("brain/state", ".brain/status.md").replace(b"4101", b"9999") + b"## Report\n"
        gh.refs["brain/state"] = gh.seed_commit("s-hand", [gh.refs["brain/state"]],
                                                files=dict(first["files"], **{".brain/status.md": hand}))
        second = CY.commit(AP.TargetState(wr, gh.refs["brain/state"]), "cycle 4102", led1, led1, roots1, roots1,
                           gh.read_file("brain/state", ".brain/status.md"), [start("s3", "4102")], IMPORTS,
                           facts(row_id="st2"), signer("uuid-2"), "r2")
        self.assertTrue(second["edited"])
        status = gh.read_file("brain/state", ".brain/status.md")
        self.assertTrue(status.endswith(CLOSE + b"## Report\n"))
        self.assertEqual(schema.status_reasons(status, gh.read_file("brain/state", ".brain/ledger.jsonl")), [])
        rekor = {"entries": {"uuid-1": first["entry"], "uuid-2": second["entry"]}}
        self.assertTrue(AN.verify(gh.read_file("brain/state", ".brain/ledger.jsonl"),
                                  gh.read_file("brain/state", ".brain/chain/root.jsonl"), rekor, WORKFLOW)["valid"])
        self.assertEqual(gh.refs["main"], main)
        # every file of the state is under .brain/, and the first root's bundle stays beside the second's
        self.assertNotEqual(first["root"], second["root"])
        self.assertEqual(set(gh.trees[gh.commits[gh.refs["brain/state"]]["tree"]]), {
            ".brain/ledger.jsonl", ".brain/chain/root.jsonl", ".brain/status.md",
            ".brain/chain/%s.sigstore.json" % first["root"], ".brain/chain/%s.sigstore.json" % second["root"]})
        for made in (first, second):
            self.assertEqual(json.loads(gh.read_file("brain/state", ".brain/chain/%s.sigstore.json" % made["root"])),
                             {"uuid": made["entry"]["uuid"], "identity": WORKFLOW, "fake_signed_sha256": made["root"]})


class StatePaths(unittest.TestCase):
    """``target.branches``: the commit paths of the state files (tohum/26d "Yer") and a file's name under them."""

    def test_every_commit_path_is_under_the_one_directory(self):
        self.assertEqual((B.STATE_LEDGER, B.STATE_ROOTS, B.STATE_STATUS),
                         (".brain/ledger.jsonl", ".brain/chain/root.jsonl", ".brain/status.md"))
        self.assertEqual(B.STATE_CHAINS, (".brain/ledger.jsonl", ".brain/chain/root.jsonl"))
        self.assertEqual(B.state_bundle("ab" * 32), ".brain/chain/" + "ab" * 32 + ".sigstore.json")
        self.assertEqual((AN.LEDGER_PATH, AN.ROOTS_PATH, SB.STATUS_PATH, AN.bundle_path("cd" * 32)),
                         (B.STATE_LEDGER, B.STATE_ROOTS, B.STATE_STATUS, B.state_bundle("cd" * 32)))

    def test_the_name_under_the_directory(self):
        self.assertEqual([B.state_name(p) for p in (B.STATE_LEDGER, B.STATE_ROOTS, B.STATE_STATUS,
                                                    B.state_bundle("ab" * 32))],
                         ["ledger.jsonl", "chain/root.jsonl", "status.md", "chain/" + "ab" * 32 + ".sigstore.json"])
        for path in ("ledger.jsonl", "chain/root.jsonl", ".brain", ".brain/", "", "x/.brain/ledger.jsonl",
                     ".brainx/ledger.jsonl", "/.brain/ledger.jsonl"):
            with self.subTest(path=path):
                with self.assertRaises(ValueError):
                    B.state_name(path)


if __name__ == "__main__":
    unittest.main()
