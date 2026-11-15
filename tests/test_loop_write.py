"""Test 46 (asama-0/09), MF17, D6: ``yaz`` writes the cycle on the target (``loop.write_cycle``, ``loop.job run yaz``),
on the in-process GitHub at ``pulled``'s heads, after ``kos`` ran the candidates with the fake runner; and the
pieces D6 shares with ``activate`` (``ledger.events``, ``target.land``). Unless said otherwise one target, t1, is
served: ``in/pulled/t1``, ``in/results/t1``, ``in/response/t1``, and the line checked is the job line's one target line.

- a cycle with a merge: the candidate's branch, pull request, check and merge on ``brain/integration``, then one
  ``brain/state`` commit on the head D1 read: the rows in order (cycle start, the base's ratchet base, decisions, the
  response's cost row, status), the whole ledger of ``ledger.schema``, an append-only extension, the root signed once and its row, the
  ``status.md`` block, and the merge unfinished for the next cycle, which merges nothing and writes its own commit;
- a cycle without a merge writes only ``brain/state``;
- two served targets (t1 then t2, each a toy on its own repository and fake GitHub behind one transport): both
  written, every request to t1 before the first to t2 and their roots signed in that order, each ledger's rows under
  the one cycle id of the run; a first target refused (its response missing) stops the job with its reason and id,
  and the second is not served (no line for it): no request to either repository, nothing signed;
- nothing is written when a head moved (a rerun of the same cycle included), when the response is not this cycle's,
  when a row carries a secret, or when the roots file is no chain (a hard stop); a root that cannot be signed after
  the merge is a hard stop naming the refs written; a block edited by hand is regenerated and recorded;
- ``ledger.events.cause``: each rule by name, ``kos:`` reasons and look-alikes are ``unknown``; every reason
  ``gate.diffguard.path_reasons`` gives is in ``PATH_REASONS``;
- D7's red (``loop.watch``, ``target.land.revert``): a cycle merges a candidate whose affected test fails; the next
  cycle's ``kos`` watches the merge at the head and its sentinel is red; ``yaz`` reverts it (the revert commit has
  the first parent's tree, its pull request is checked and merged) and writes the ``revert`` row with the cause from
  the facts (the impact set, the lint before from the merge's ``ratchet_base`` row and after from the base run),
  which finishes the merge; a green sentinel leaves the merge on ``brain/integration`` and writes the ``sentinel``
  end row (seed-043's draft) with the verified file's hash, which finishes the merge, so the cycle after it merges
  the next candidate; a sentinel file that is missing, changed or not its index's hash is refused before any
  write; ``loop.write_cycle.write`` given an end whose runs do not give its verdict (a green claimed of failing runs,
  a red claimed of passing runs, runs that ask for a rerun, a flaky list that differs) or of another merge than the
  head writes nothing; ``target.land.revert`` of runs that are not red (green, too few, flaky) writes nothing;
- D8, the revert drill (``loop.drill``) over four cycles on one target, each cycle's ``pulled`` read back from what the
  previous one wrote (``next_cycle``): a commitment (the hash only, the key nowhere in the line), the key's instance
  planted as the cycle's one merge on ``brain/drill/<cycle>`` with its ratchet base and plant rows, the next cycle's
  ``kos`` watching it red and ``yaz`` reverting it (D7) while the drill waits, then the key revealed and judged
  ``PASS`` (by the loop and by ``harness.revert_drill``'s command) and the next drill committed, for a planted test
  regression and a planted lint regression, the fixtures (``DRILL_FIXTURES``, tohum/26f) bound to the checkout's
  counter; the fixtures' build break, which stage 0's D7 reverts as a test regression, is judged ``FAIL`` and the
  job ends ``drill_fail``; the plant waits for a candidate's merge and its sentinel; a changed seed or a patch that
  no longer applies commits again, and fixtures that do not fit commit nothing; without the seed the drill is off,
  and with it on a target of kind ``copy`` too (the drill is the toy's: no D8, no drill row, nothing planted) where
  the toy with the same seed commits; without the fixtures, or with fixtures bound to another import, it is off
  with the reason named and the cycle written; fixtures ``loop.drill.fixtures`` refuses (each rule broken once; the
  message names no value of the secret), a counter with no import, no workspace and a run id that is not digits
  write nothing; ``loop.write_cycle`` refuses a plant beside a merge or an
  end and an action ``loop.drill`` does not give; ``harness.pass_row`` judges the state these cycles wrote (one root
  and one status row per cycle, the drill ``PASS`` or ``FAIL`` as the loop judged it);
- the copy's genesis gate (``Gate``, tohum/25a row 7) on a toy whose ``pulled`` state is test_pass_row's passing
  toy world, with the drill seed and the checkout's counter: an open gate writes the ``copy_gate`` row (the
  referee's own, after D8's row, before the cost and status rows; the ledger an append-only extension of the
  schema), and the next cycle neither judges it again nor writes a second; without the seed it is closed with
  ``drill_inputs_missing`` and no row, a flaky sentinel closes it with the seed; an ``expect.json`` it cannot use
  keeps it closed with ``unusable`` and the cycle written; a copy is not judged; ``loop.write_cycle`` writes the
  row it is given at ``<cycle>:gate``;
- the PASS row (``Pass``, tohum/26d) on a toy whose run holds the gate's row, served with the copy (test_pass_row's
  passing worlds) and the checkout's counter and (A) result: a PASS writes the ``pass`` row with the judge's payload
  on the toy's cycle (the referee's own, after D8's row, before the cost and status rows; the copy's state
  untouched), the state written is judged PASS again, and the next cycle neither judges it again nor writes a
  second; without the seed it fails with ``drill_inputs_missing`` and the cycle is written; the copy's own state
  is judged (a model mismatch of its canary fails it); before the gate's row, on a copy, it is not judged, without
  a served copy, with the copy in its genesis form or only another toy it waits; a result that is not the import's
  and an ``expect.json`` of the copy it cannot use fail it with ``unusable``; a missing result (nothing written)
  and a second copy are unusable; ``loop.write_cycle`` writes the row it is given at ``<cycle>:pass``;
- the genesis cycle (``Genesis``): ``kos`` then ``yaz`` on a toy's ``pulled`` in loop.pulled's genesis form;
  ``yaz`` runs ``activate`` with D5's answer, D3's base run and D4's cost row (the cut at main, the merge, the
  orphan state with the genesis payload naming the counter's transfer, the checkout's security ledger, the pulled
  policy and unit), and the next cycle is an ordinary one on it (D7 ends the merge's green sentinel); an
  activation reason (``toy_workflows``, ``base_moved``) writes nothing and ends the job ``activation_refused``; a
  base run that is not its index's is ``base_run_hash_mismatch``, no base run ``base_run_missing``, and no security
  ledger is no verdict, nothing written;
- ``target.land.applied``: one file applied; more than one file, a missing or linked base, a hunk that does not
  apply, a creation and an unusable diff each refused with their reason.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

REFEREE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REFEREE)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from gate import diffguard as G  # noqa: E402
from ledger import anchor as AN  # noqa: E402
from ledger import chain as CH  # noqa: E402
from ledger import cycle as CY  # noqa: E402
from ledger import events as EV  # noqa: E402
from ledger import schema as SC  # noqa: E402
from ledger import serial as SE  # noqa: E402
from harness import pass_row as PR  # noqa: E402
from harness import revert_drill as RD  # noqa: E402
from loop import accepted as AC  # noqa: E402
from loop import drill as DR  # noqa: E402
from loop import job as J  # noqa: E402
from loop import pulled as P  # noqa: E402
from loop import watch as WT  # noqa: E402
from loop import write_cycle as WC  # noqa: E402
from status import block as SB  # noqa: E402
from target import branches as B  # noqa: E402
from target import land as LN  # noqa: E402
from target import write as W  # noqa: E402
from profile_tree import write_tree  # noqa: E402
from test_kos import BREAKS_TEST, FINDING, GOOD, diff, recipe  # noqa: E402
from test_loop_kos import A_JS, HEADS, TARGET, RedAs, candidate  # noqa: E402
from test_loop_yaz import OPEN, YazBase  # noqa: E402
from test_pass_row import RD_BUILD, RD_LINT, RD_TEST  # noqa: E402
import activation_world as AW  # noqa: E402
import yaz_world as YW  # noqa: E402

GENESIS_TS = "2026-10-30T12:00:00Z"
CYCLE = "9-1"


def genesis_state() -> dict[str, bytes]:
    """``brain/state``'s files as an activation leaves them: a ``cycle_start`` row, the status block, a signed root."""
    rows = [EV.start({"cycle_id": "g", "ts": GENESIS_TS, "snapshot_id": HEADS[B.INTEGRATION]})]
    facts = {"ts": GENESIS_TS, "snapshot_id": HEADS[B.INTEGRATION], "row_id": "g:status",
             "canary_cap_usd_micros": 1_000_000}
    return CY.plan(b"", b"", b"", b"", None, rows, YW.chained(YW.IMPORTS_ROWS), facts,
                   AN.FakeSigner(True, YW.IDENTITY, "rekor-g"), "g:root")["files"]


def rows_of(data: bytes) -> list[dict]:
    return [json.loads(line) for line in data.splitlines()]


class StateBase(YazBase):
    """``yaz`` on a target whose ``brain/state`` is ``genesis_state``'s, as D1 hands it over."""

    def setUp(self) -> None:
        super().setUp()
        self.state = genesis_state()

    def write_pulled(self, cands=None, **kw) -> dict:
        kw.setdefault("state", {p: self.state[p] for p in B.STATE_CHAINS})
        kw.setdefault("status", self.state[B.STATE_STATUS])
        return super().write_pulled(cands, **kw)

    def github(self) -> None:
        super().github()
        art = P.read(self.pulled)
        self.gh = YW.github_at(art.heads, YW.files_of(self.src), self.state)

    def cycle(self, cands: dict, control=None) -> dict:
        self.kos(cands)
        self.control(OPEN if control is None else control)
        self.github()
        return self.run_yaz()

    def control(self, doc) -> None:
        write_tree(os.path.join(self.temp, "control"), {"control.json": doc})

    def next_cycle(self, cands: dict, run_id: str, units=None) -> dict:
        """Cycle ``<run_id>-1`` on what the previous cycle wrote, as D1 would pull it: ``brain/state``'s files, both
        heads and ``brain/integration``'s tree read back from the fake GitHub (the same GitHub stays the target),
        the previous ``pulled`` and results cleared, ``kos`` run, the cycle's response written. Returns t1's line
        of ``kos``'s line; ``self.state`` is the state the cycle reads."""
        self.state = {p: self.state_file(p) for p in B.STATE_CHAINS + (B.STATE_STATUS,)}
        heads = {b: self.gh.refs[b] for b in P.HEAD_BRANCHES}
        tree = self.gh.trees[self.gh.commits[heads[B.INTEGRATION]]["tree"]]
        shutil.rmtree(self.src)
        for path, blob in tree.items():
            os.makedirs(os.path.dirname(os.path.join(self.src, path)), exist_ok=True)
            with open(os.path.join(self.src, path), "wb") as fh:
                fh.write(self.gh.blobs[blob])
        shutil.rmtree(self.pulled)
        shutil.rmtree(self.results())
        out = self.kos(cands, heads=heads, units=units)
        art = P.read(self.pulled)
        YW.write_response(self.temp, "t1", art.heads, [YW.cost_row("cagir-%s-1" % run_id, art.heads[B.INTEGRATION])])
        return out

    def run_yaz(self, **env) -> dict:
        """The job's line's one target line (``Cycle.line``: t1's, the job's ``ok`` and refusal its)."""
        return self.line(super().run_yaz(**env))

    def writes(self) -> list[tuple]:
        return [(m, p) for m, p, _ in self.gh.requests if m != "GET"]

    def state_file(self, path: str) -> bytes:
        return self.gh.read_file(B.STATE, path)


class D6(StateBase):
    def test_a_cycle_merges_and_writes_one_state_commit(self):
        write_tree(self.src, {"pkg/b.js": "var b = 1;\n"})  # the next cycle's candidate's finding
        out = self.cycle({"good": candidate(GOOD), "breaks": candidate(BREAKS_TEST)})
        self.assertEqual((out["ok"], "reason" in out, out["done"], out["merge"], out["drill"]),
                         (True, False, ["D5", "D6"], "good", {"action": "off"}))  # no DRILL_SEED: D8 is off
        written = out["written"]
        merge = written["merge"]
        self.assertEqual({k: merge[k] for k in ("candidate", "path", "pull")}, {"candidate": "good", "path": "pkg/a.js",
                                                                              "pull": 1})
        # the merge: on brain/integration, the candidate's file changed as its diff says, the gate's check on its head
        self.assertEqual(self.gh.refs[B.INTEGRATION], merge["merge_sha"])
        self.assertEqual(self.gh.commits[merge["merge_sha"]]["parents"], [HEADS[B.INTEGRATION], merge["head_sha"]])
        self.assertEqual(self.gh.read_file(B.INTEGRATION, "pkg/a.js"), A_JS.replace("var a = 1;", "let a = 1;").encode())
        self.assertEqual([(c["name"], c["head_sha"], c["conclusion"]) for c in self.gh.checks],
                         [(B.CHECK, merge["head_sha"], "success")])
        # one brain/state commit, on the head D1 read
        head = self.gh.refs[B.STATE]
        self.assertEqual((written["state_sha"], self.gh.commits[head]["parents"]), (head, [HEADS[B.STATE]]))
        self.assertEqual([p for m, p in self.writes() if p.endswith("git/refs/heads/brain/state")],
                         ["/repos/acme/t1/git/refs/heads/brain/state"])
        old, new = self.state[B.STATE_LEDGER], self.state_file(B.STATE_LEDGER)
        self.assertTrue(CH.verify_bytes(new, old)["valid"])
        self.assertEqual(SC.ledger_reasons(new), [])
        added = rows_of(new)[len(rows_of(old)):]
        self.assertEqual([(r["row_id"], r["kind"]) for r in added],
                         [("9-1:start", "cycle_start"), ("9-1:ratchet", "ratchet_base"), ("9-1:c:breaks", "decision"),
                          ("9-1:c:good", "decision"), ("9-1:m:good", "merge"), ("cagir-9-1", "cost"),
                          ("9-1:status", "status")])
        # the merge's lint before: the base kos ran, its sha256 and its first record's violations per tool
        with open(self.results("base.jsonl"), "rb") as fh:
            base_run = fh.read()
        first = json.loads(base_run.splitlines()[0])
        counts = {first["tool"]: len(first["violations"])}
        self.assertEqual(added[1]["payload"], {"base_run_sha256": hashlib.sha256(base_run).hexdigest(), "counts": counts})
        self.assertEqual(counts, {first["tool"]: 2})  # pkg/a.js's var and pkg/b.js's
        self.assertEqual(SE.lint_before(new, merge["merge_sha"]), counts)
        self.assertEqual(added[2]["payload"], {"decision": "reject", "candidate": "breaks", "reasons": ["tests_red"]})
        self.assertEqual(added[2]["cause"], "test_regression")
        # the merge: its decision row, then tohum/26d's merge row carrying target.land's answer (ledger.events.decided)
        self.assertEqual(added[3]["payload"], {"decision": "merge", "candidate": "good"})
        # and asama-0/08's coverage record of GOOD's one hunk, @@ -1,1 +1,1 @@ (ledger.events.hunk_covered)
        self.assertEqual((added[4]["part"], added[4]["payload"]), ("events", dict(merge, hunk_covered=[
            {"path": "pkg/a.js", "old_start": 1, "old_count": 1, "new_start": 1, "new_count": 1,
             "covered": "unmeasured", "reason": "no_coverage_tool"}])))
        self.assertNotIn("cause", added[3])
        self.assertNotIn("cause", added[4])
        self.assertEqual({(r["ts"], r["snapshot_id"]) for r in added if r["part"] == "events"},
                         {(YW.TS, HEADS[B.INTEGRATION])})
        self.assertEqual((written["rows"], written["revert"]), (7, None))
        # the root of the new ledger, signed once, its row appended; status.md's block is the last status row's
        root = AN.root_of(AN.tips(new))
        self.assertEqual([hashlib.sha256(p).hexdigest() for p in self.signer.payloads], [root])
        # its bundle as the signer gave it, beside the root row (tohum/26d "Yer")
        self.assertEqual(json.loads(self.state_file(".brain/chain/%s.sigstore.json" % root)),
                         dict(self.signer.answer(), fake_signed_sha256=root))
        roots = rows_of(self.state_file(B.STATE_ROOTS))
        self.assertEqual((roots[-1]["row_id"], roots[-1]["root"], roots[-1]["rekor_uuid"]), ("9-1:root", root, "rekor-yaz"))
        self.assertTrue(CH.verify_bytes(self.state_file(B.STATE_ROOTS), self.state[B.STATE_ROOTS])["valid"])
        self.assertEqual((written["root"], written["rekor_uuid"], written["edited"]), (root, "rekor-yaz", False))
        self.assertEqual(SC.status_reasons(self.state_file(B.STATE_STATUS), new), [])
        # every ref written is under brain/: created (POST git/refs) or moved (PATCH git/refs/heads/...)
        refs = [b["ref"] for m, p, b in self.gh.requests if m == "POST" and p.endswith("/git/refs")]
        refs += [p.split("/git/", 1)[1] for m, p, _ in self.gh.requests if m == "PATCH"]
        self.assertEqual(sorted(refs), ["refs/heads/brain/c/good", "refs/heads/brain/c/good", "refs/heads/brain/state"])
        self.assertEqual(sorted(self.gh.refs), ["brain/c/good", B.INTEGRATION, B.STATE])
        # the next cycle: the merge is unfinished (its sentinel is D7's), so nothing merges; its own commit is written
        self.assertEqual(SE.unfinished(new), [merge["merge_sha"]])
        heads = dict(self.gh.refs)
        # GOOD is on the head now; the next candidate is another file's
        other = dict(candidate(diff("pkg/b.js", ["var b = 1;"], ["let b = 1;"])),
                     **{"finding.json": json.dumps(dict(FINDING, path="pkg/b.js")).encode()})
        self.next_cycle({"good": other}, "10")
        out = self.run_yaz(GITHUB_RUN_ID="10")  # D7 ends the merge's green sentinel; D5 merges nothing beside it
        self.assertEqual((out["done"], out["written"]["merge"], out["sentinel"]["verdict"]),
                         (["D5", "D6", "D7"], None, "green"))
        added = rows_of(self.state_file(B.STATE_LEDGER))[len(rows_of(self.state[B.STATE_LEDGER])):]
        self.assertEqual([(r["row_id"], r["payload"].get("reasons")) for r in added if r["kind"] == "decision"],
                         [("10-1:c:good", ["sentinel_pending"])])
        self.assertEqual(self.gh.commits[self.gh.refs[B.STATE]]["parents"], [heads[B.STATE]])

    def test_without_a_merge_only_brain_state_is_written(self):
        out = self.cycle({"good": candidate(GOOD)}, control={"merge_paused": True})
        self.assertEqual((out["done"], out["written"]["merge"]), (["D5", "D6"], None))
        self.assertEqual([p for m, p in self.writes() if "/git/refs" in p], ["/repos/acme/t1/git/refs/heads/brain/state"])
        self.assertEqual(self.gh.refs[B.INTEGRATION], HEADS[B.INTEGRATION])
        [decision] = [r for r in rows_of(self.state_file(B.STATE_LEDGER)) if r["kind"] == "decision"]
        self.assertEqual((decision["payload"]["reasons"], decision["cause"]), (["merge_paused"], "unknown"))

    def test_a_moved_head_writes_nothing(self):
        self.kos({"good": candidate(GOOD)})
        self.control(OPEN)
        for branch in P.HEAD_BRANCHES:
            with self.subTest(branch=branch):
                self.github()
                self.gh.commits["c" * 40] = {"tree": self.gh.commits[HEADS[branch]]["tree"], "parents": [HEADS[branch]],
                                             "message": "pushed by someone else"}
                self.gh.refs[branch] = "c" * 40
                out = self.run_yaz()
                self.assertEqual((out["reason"], out["reasons"], out["done"]),
                                 ("write_refused", ["head_moved:%s" % branch], ["D5"]))
                self.assertEqual(self.writes(), [])

    def test_a_rerun_of_the_same_cycle_writes_nothing(self):
        self.cycle({"good": candidate(GOOD)})
        before = len(self.writes())
        out = self.run_yaz(GITHUB_RUN_ATTEMPT="2")
        self.assertEqual((out["reason"], out["reasons"]),
                         ("write_refused", ["head_moved:brain/state", "head_moved:brain/integration"]))
        self.assertEqual(len(self.writes()), before)

    def test_a_response_that_is_not_this_cycles_writes_nothing(self):
        self.kos({"good": candidate(GOOD)})
        self.control(OPEN)
        self.github()
        art = P.read(self.pulled)
        response = os.path.join(self.temp, "in", "response", "t1")
        other = dict(art.heads, **{B.STATE: "d" * 40})
        cases = (
            (lambda: None, ["response_missing"]),
            (lambda: YW.write_response(self.temp, "t1", other, []), ["heads_mismatch"]),
            (lambda: YW.write_response(self.temp, "t2", art.heads, []), ["target_mismatch"]),
            (lambda: YW.write_response(self.temp, "t1", art.heads, {}), ["rows_invalid"]),
            (lambda: YW.write_response(self.temp, "t1", art.heads, [], schema="snowball-response/2"), ["schema_unknown"]),
            (lambda: YW.write_response(self.temp, "t1", art.heads, [], extra=1), ["response_unreadable"]),
            (lambda: write_tree(response, {"response.json": "{"}), ["response_unreadable"]),
            (lambda: write_tree(response, {"response.json": {"schema": 1}, "other.json": "x"}),
             ["unlisted:other.json", "response_unreadable"]),
        )
        for make, want in cases:
            with self.subTest(want=want):
                shutil.rmtree(response, ignore_errors=True)
                make()
                out = self.run_yaz()
                self.assertEqual((out["reason"], out["reasons"]), ("response_invalid", want))
                self.assertEqual(self.gh.requests, [])

    def test_a_secret_in_a_row_is_refused_before_any_write(self):
        self.kos({"good": candidate(GOOD)})
        self.control(OPEN)
        self.github()
        art = P.read(self.pulled)
        token = "ghp_" + "Q7x" * 12  # a GitHub token shape, not a real token
        YW.write_response(self.temp, "t1", art.heads, [YW.cost_row(reason="leak " + token)])
        out = self.run_yaz()
        self.assertEqual(out["reason"], "write_refused")
        [reason] = out["reasons"]
        self.assertTrue(reason.startswith("state_unwritable: "), reason)
        self.assertEqual(self.writes(), [])

    def test_a_row_id_already_in_the_ledger_is_refused_before_any_write(self):
        self.kos({"good": candidate(GOOD)})
        self.control(OPEN)
        self.github()
        art = P.read(self.pulled)
        YW.write_response(self.temp, "t1", art.heads, [YW.cost_row("g:start")])  # the genesis cycle's start row
        out = self.run_yaz()
        self.assertEqual(out["reason"], "write_refused")
        self.assertIn("repeats row_id", out["reasons"][0])
        self.assertEqual(self.writes(), [])

    def test_a_roots_file_that_is_no_chain_is_a_hard_stop_before_any_write(self):
        self.state = dict(self.state, **{B.STATE_ROOTS: self.state[B.STATE_ROOTS].replace(b'"g:root"', b'"g:r00t"')})
        out = self.cycle({"good": candidate(GOOD)})
        self.assertEqual((out["reason"], out["written"]), ("hard_stop", []))
        self.assertEqual(self.writes(), [])

    def test_a_root_that_cannot_be_signed_after_the_merge_is_a_hard_stop_naming_the_writes(self):
        self.signer = YW.signer(available=False)
        out = self.cycle({"good": candidate(GOOD)})
        self.assertEqual((out["reason"], out["done"]), ("hard_stop", ["D5"]))
        self.assertEqual(out["written"], ["refs/heads/brain/c/good", "refs/heads/brain/integration"])  # the merge
        self.assertIn("Unsignable", out["reasons"][0])
        self.assertEqual(self.gh.refs[B.STATE], HEADS[B.STATE])  # brain/state untouched

    def test_a_block_edited_by_hand_is_regenerated_and_recorded(self):
        status = self.state[B.STATE_STATUS]
        start = status.index(SB.OPEN) + len(SB.OPEN)
        self.state = dict(self.state, **{B.STATE_STATUS: status[:start] + b"\nEDITED-BY-HAND\n" + status[start:]})
        out = self.cycle({"good": candidate(GOOD)}, control={"merge_paused": True})
        self.assertTrue(out["written"]["edited"])
        new = self.state_file(B.STATE_LEDGER)
        self.assertEqual([r["kind"] for r in rows_of(new)][-2:], ["status_edited", "status"])
        self.assertEqual(SC.status_reasons(self.state_file(B.STATE_STATUS), new), [])
        self.assertNotIn(b"EDITED-BY-HAND", self.state_file(B.STATE_STATUS))

    def two_targets(self, cands: dict) -> dict[str, "Router"]:
        """``in/pulled`` serving t1 then t2 (``served.json``), each a toy on its own repository at ``HEADS`` with
        ``cands``; ``kos`` run on both and its ``out/results/<id>`` handed over; ``control.json``. Returns each target's
        fake GitHub by id (``acme/t1``, ``acme/t2``), the cycle's responses not written yet."""
        served = os.path.dirname(self.pulled)
        os.makedirs(served)
        P.write_served(served, ["t1", "t2"])
        for tid in ("t1", "t2"):
            self.pulled = os.path.join(served, tid)
            self.write_pulled(cands, target=dict(TARGET, id=tid, repo="acme/" + tid))
        kos = J.run("kos", {"RUNNER_TEMP": self.temp}, runner=RedAs())
        self.assertEqual((kos["ok"], [t["target"] for t in kos["targets"]]), (True, ["t1", "t2"]), kos)
        shutil.move(os.path.join(self.temp, "out", "results"), os.path.join(self.temp, "in", "results"))
        self.control(OPEN)
        return {tid: YW.github_at(HEADS, YW.files_of(self.src), self.state, repo="acme/" + tid) for tid in ("t1", "t2")}

    def test_two_served_targets_are_written_in_order_with_one_cycle_id(self):
        ghs = self.two_targets({"good": candidate(GOOD)})
        for tid in ("t1", "t2"):
            YW.write_response(self.temp, tid, HEADS, [YW.cost_row(snapshot=HEADS[B.INTEGRATION])], at=tid)
        router = Router(ghs)
        out = J.run("yaz", YW.env(self.temp, self.workspace), transport=router, signer=self.signer,
                    now=lambda: YW.NOW)
        self.assertEqual((out["ok"], "reason" in out, "target" in out), (True, False, False), out)
        self.assertEqual([t["target"] for t in out["targets"]], ["t1", "t2"])
        roots = []
        for line, (tid, gh) in zip(out["targets"], ghs.items()):
            with self.subTest(target=tid):
                self.assertEqual((line["ok"], line["done"], line["merge"]), (True, ["D5", "D6"], "good"))
                self.assertEqual(line["written"]["state_sha"], gh.refs[B.STATE])
                self.assertEqual(gh.refs[B.INTEGRATION], line["written"]["merge"]["merge_sha"])
                # the rows of one cycle: the run's id on each target, each its own ledger's extension
                old, new = self.state[B.STATE_LEDGER], gh.read_file(B.STATE, B.STATE_LEDGER)
                self.assertTrue(CH.verify_bytes(new, old)["valid"])
                added = rows_of(new)[len(rows_of(old)):]
                self.assertEqual([r["row_id"] for r in added if r["part"] == "events"][0], "9-1:start")
                self.assertEqual(added[0]["payload"]["cycle_id"], CYCLE)
                self.assertEqual(rows_of(gh.read_file(B.STATE, B.STATE_ROOTS))[-1]["row_id"], "9-1:root")
                roots.append(AN.root_of(AN.tips(new)))
        # served.json's order: every request to t1 before the first to t2, each root signed in that order
        repos = [repo for repo, _ in router.calls]
        self.assertEqual(repos, sorted(repos))
        self.assertEqual(set(repos), {"acme/t1", "acme/t2"})
        self.assertEqual([hashlib.sha256(p).hexdigest() for p in self.signer.payloads], roots)

    def test_a_refused_first_target_stops_the_job_before_the_second(self):
        ghs = self.two_targets({"good": candidate(GOOD)})
        # t1's response is missing (cagir's artifact without its directory), t2's is right
        YW.write_response(self.temp, "t2", HEADS, [YW.cost_row(snapshot=HEADS[B.INTEGRATION])], at="t2")
        router = Router(ghs)
        out = J.run("yaz", YW.env(self.temp, self.workspace), transport=router, signer=self.signer,
                    now=lambda: YW.NOW)
        [line] = out["targets"]  # t2 is not served
        self.assertEqual((line["target"], line["ok"], line["reason"], line["reasons"], line["done"]),
                         ("t1", False, "response_invalid", ["response_missing"], ["D5"]))
        self.assertEqual((out["ok"], out["target"], out["reason"], out["reasons"]),
                         (False, "t1", "response_invalid", ["response_missing"]))
        self.assertEqual((router.calls, ghs["t1"].requests, ghs["t2"].requests, self.signer.payloads), ([], [], [], []))

    def test_the_environment_and_the_target_repository(self):
        self.kos({"good": candidate(GOOD)})
        self.control(OPEN)
        self.github()
        for name in J.YAZ_ENV:
            with self.subTest(unset=name):
                with self.assertRaisesRegex(J.Unusable, name):
                    self.run_yaz(**{name: ""})
        shutil.rmtree(self.pulled)
        self.write_pulled({"good": candidate(GOOD)}, target={"id": "t1", "kind": "toy", "excluded_paths": [],
                                                             "unit_candidates": [], "repo": "../x"})
        self.github()
        self.assertEqual(self.run_yaz()["reason"], "target_repo_unsafe")
        self.assertEqual(self.gh.requests, [])


# D7: the affected tests at the head; "SENTINEL_RED" in pkg/a.js fails one, which the candidate's own test command
# (pkg/run_tests.py) does not read, so a candidate carrying it merges and its sentinel is red in the next cycle.
SENTINEL_PY = r'''import sys
red = "SENTINEL_RED" in open("pkg/a.js").read()
print("ok 1 - a loads")
print(("not ok" if red else "ok") + " 2 - a holds at the head")
sys.exit(1 if red else 0)
'''
SENTINEL_UNITS = {"units": [recipe(affected_test_cmd=["python", "pkg/sentinel.py"])]}
RED_AT_HEAD = diff("pkg/a.js", ["var a = 1;"], ["let a = 1; // SENTINEL_RED"])


class D7(StateBase):
    """Cycle 9-1 merges a candidate; cycle 10-1's ``kos`` runs the sentinel at the merge (the head) and ``yaz``
    reads it: red is reverted with its cause in the cycle's one ``brain/state`` commit."""

    def setUp(self) -> None:
        super().setUp()
        write_tree(self.src, {"pkg/sentinel.py": SENTINEL_PY})

    def merged_then_watched(self, cand: bytes) -> tuple[dict, dict]:
        """Cycle 9-1 merges ``cand``; then cycle 10-1's ``kos`` on the merged tree at the new heads. Returns
        ``(cycle 9-1's written, the new heads)``; ``self.state`` is cycle 9-1's state."""
        self.kos({"c": candidate(cand)}, units=SENTINEL_UNITS)
        self.control(OPEN)
        self.github()
        first = self.run_yaz()
        self.assertEqual((first["merge"], first["sentinel"]), ("c", None), first)
        watched = self.next_cycle({}, "10", units=SENTINEL_UNITS)
        heads = P.read(self.pulled).heads
        self.assertEqual((watched["done"], watched["index"]["sentinel"]["merge_sha"]),
                         (["D3", "D7"], heads[B.INTEGRATION]))  # kos ends ok after D7 whatever the verdict
        return first["written"], heads

    def test_a_red_merge_is_reverted_with_its_cause(self):
        first, heads = self.merged_then_watched(RED_AT_HEAD)
        merge_sha = first["merge"]["merge_sha"]
        self.assertEqual(heads[B.INTEGRATION], merge_sha)
        with open(self.results("sentinel.json")) as fh:
            self.assertEqual(json.load(fh)["verdict"], "red")
        old_ledger = self.state[B.STATE_LEDGER]
        out = self.run_yaz(GITHUB_RUN_ID="10")
        self.assertEqual((out["ok"], "reason" in out, out["done"], out["merge"], out["drill"]),
                         (True, False, ["D5", "D6", "D7"], None, {"action": "off"}))
        [ratchet] = [r for r in rows_of(old_ledger) if r["kind"] == "ratchet_base"]
        (name, before), = ratchet["payload"]["counts"].items()
        self.assertEqual(out["sentinel"], {
            "merge_sha": merge_sha, "verdict": "red", "red": ["a holds at the head"], "flaky": [],
            "sha256": out["sentinel"]["sha256"], "facts": {"impact": ["a holds at the head", "a loads"], "build_ok": True,
                      "lint": {name: {"before": before, "after": 0}}}})
        self.assertEqual(before, 1)  # the base's var; the merged a.js has none
        revert = out["written"]["revert"]
        self.assertEqual((revert["reverted"], revert["cause"]), (merge_sha, "test_regression"))
        # brain/integration: the revert commit (the merge's first parent's tree) merged by pull request after the check
        self.assertEqual(self.gh.refs[B.INTEGRATION], revert["merge_sha"])
        self.assertEqual(self.gh.commits[revert["commit"]]["parents"], [merge_sha])
        self.assertEqual(self.gh.commits[revert["commit"]]["tree"], self.gh.commits[HEADS[B.INTEGRATION]]["tree"])
        self.assertEqual(self.gh.read_file(B.INTEGRATION, "pkg/a.js"), A_JS.encode())
        self.assertEqual(self.gh.refs["brain/revert/" + merge_sha], revert["commit"])
        self.assertEqual(self.gh.pulls[revert["pull"]]["head"], "brain/revert/" + merge_sha)
        self.assertEqual([(c["name"], c["head_sha"], c["conclusion"]) for c in self.gh.checks][-1],
                         (B.CHECK, revert["commit"], "success"))
        # brain/state: one commit; the revert row with its cause finishes the merge, so the next cycle may merge
        new = self.state_file(B.STATE_LEDGER)
        self.assertTrue(CH.verify_bytes(new, old_ledger)["valid"])
        self.assertEqual(SC.ledger_reasons(new), [])
        added = rows_of(new)[len(rows_of(old_ledger)):]
        self.assertEqual([(r["row_id"], r["kind"]) for r in added],
                         [("10-1:start", "cycle_start"), ("10-1:revert", "revert"), ("cagir-10-1", "cost"),
                          ("10-1:status", "status")])
        self.assertEqual((added[1]["payload"], added[1]["cause"]), ({"merge_sha": merge_sha}, "test_regression"))
        self.assertEqual(SE.unfinished(new), [])
        self.assertEqual(self.gh.commits[self.gh.refs[B.STATE]]["parents"], [heads[B.STATE]])

    def test_a_green_merge_is_ended_and_the_next_cycle_merges(self):
        write_tree(self.src, {"pkg/b.js": "var b = 1;\n"})  # the next candidate's finding
        first, heads = self.merged_then_watched(GOOD)
        merge_sha = first["merge"]["merge_sha"]
        old_ledger = self.state[B.STATE_LEDGER]
        with open(self.results("sentinel.json"), "rb") as fh:
            file_sha = hashlib.sha256(fh.read()).hexdigest()
        out = self.run_yaz(GITHUB_RUN_ID="10")
        self.assertEqual((out["sentinel"]["verdict"], out["written"]["revert"], out["merge"]), ("green", None, None))
        self.assertEqual(out["sentinel"]["sha256"], file_sha)  # the verified file's hash is the line's, not the row's
        self.assertEqual(self.gh.refs[B.INTEGRATION], heads[B.INTEGRATION])  # the merge is left
        new = self.state_file(B.STATE_LEDGER)
        self.assertTrue(CH.verify_bytes(new, old_ledger)["valid"])
        self.assertEqual(SC.ledger_reasons(new), [])
        added = rows_of(new)[len(rows_of(old_ledger)):]
        self.assertEqual([(r["row_id"], r["kind"]) for r in added],
                         [("10-1:start", "cycle_start"), ("10-1:sentinel", "sentinel"), ("cagir-10-1", "cost"),
                          ("10-1:status", "status")])
        self.assertEqual((added[1]["payload"], "cause" in added[1]),
                         ({"merge_sha": merge_sha, "verdict": "green", "red": [], "flaky": []}, False))  # tohum/26f
        self.assertEqual(SE.unfinished(new), [])
        # cycle 11-1: nothing is watched, and the next ready candidate merges on the green merge
        nxt = dict(candidate(diff("pkg/b.js", ["var b = 1;"], ["let b = 1;"])),
                   **{"finding.json": json.dumps(dict(FINDING, path="pkg/b.js")).encode()})
        watched = self.next_cycle({"d": nxt}, "11", units=SENTINEL_UNITS)
        self.assertEqual((watched["done"], watched["index"]["sentinel"]), (["D3"], None))
        third = self.run_yaz(GITHUB_RUN_ID="11")
        self.assertEqual((third["merge"], third["sentinel"]), ("d", None), third)
        self.assertEqual(SE.unfinished(self.state_file(B.STATE_LEDGER)), [third["written"]["merge"]["merge_sha"]])

    def test_an_end_its_runs_do_not_give_writes_nothing(self):
        """``loop.write_cycle`` judges the end it is handed again (``loop.watch.read``'s answer replaced here, after
        the real read of a green sentinel), so a wrong verdict reaching it writes nothing."""
        self.merged_then_watched(GOOD)
        real = WT.read
        fail = {"results": [{"id": "a loads", "status": "pass"}, {"id": "a holds at the head", "status": "fail"}]}
        facts = {"impact": ["a holds at the head", "a loads"], "build_ok": True, "lint": None}
        for name, change in (("red of green runs", lambda g: dict(g, verdict="red", facts=facts)),
                             ("green of a failing run", lambda g: dict(g, runs=[fail])),
                             ("a rerun", lambda g: dict(g, runs=[fail], verdict="rerun")),
                             ("another flaky list", lambda g: dict(g, flaky=["a loads"])),
                             ("another merge", lambda g: dict(g, merge_sha="0" * 40))):
            with self.subTest(name), mock.patch.object(J.WT, "read", lambda r, w: change(real(r, w))):
                writes = len(self.writes())
                with self.assertRaises(J.Unusable):
                    self.run_yaz(GITHUB_RUN_ID="10")
                self.assertEqual(len(self.writes()), writes)
        self.assertEqual(self.run_yaz(GITHUB_RUN_ID="10")["sentinel"]["verdict"], "green")  # unchanged, it ends

    def test_a_sentinel_it_cannot_verify_writes_nothing(self):
        self.merged_then_watched(RED_AT_HEAD)
        path = self.results("sentinel.json")
        with open(path, "rb") as fh:
            kept = fh.read()
        for changed, want in ((None, ["sentinel_hash_mismatch"]), (kept + b" ", ["sentinel_hash_mismatch"]),
                              (kept.replace(b'"red"', b'"green"', 1), ["sentinel_hash_mismatch"])):
            with self.subTest(want=want, removed=changed is None):
                if os.path.exists(path):
                    os.remove(path)
                if changed is not None:
                    with open(path, "wb") as fh:
                        fh.write(changed)
                writes = len(self.writes())
                out = self.run_yaz(GITHUB_RUN_ID="10")
                self.assertEqual((out["reason"], out["reasons"], out["done"]), ("sentinel_refused", want, ["D5"]))
                self.assertEqual(len(self.writes()), writes)


# D8: the live drill fixtures, yaz's DRILL_FIXTURES secret (tohum/26f). Each patch turns pkg/a.js red for the
# sentinel (SENTINEL_RED); RD_LINT also adds a ``var`` line, so the lint after rises over the plant cycle's ratchet
# base; RD_BUILD's line does not parse (PARSE_ERROR: test_kos's lint reports a fatal message), so the watching cycle
# has no base run and D7 reverts it as a build break (``loop.watch.base_build``). 26f asks every cause once.
DRILL_PATCHES = {RD_TEST: RED_AT_HEAD,
                 RD_LINT: diff("pkg/a.js", ["var a = 1;"], ["var a = 1; // SENTINEL_RED", "var z = 2;"]),
                 RD_BUILD: diff("pkg/a.js", ["var a = 1;"], ["var a = 1; // SENTINEL_RED PARSE_ERROR"])}
DRILL_CAUSES = {RD_TEST: "test_regression", RD_LINT: "lint_regression", RD_BUILD: "build_break"}
# A catalog that names RD_TEST's and RD_BUILD's causes the other way round: what the loop gives is not the key's.
SWAPPED_CAUSES = dict(DRILL_CAUSES, **{RD_TEST: "build_break", RD_BUILD: "test_regression"})


def drill_catalog(causes: dict[str, str], patches: dict[str, bytes] | None = None) -> dict:
    """The fixtures' instances (tohum/26f ``{id, cause, patch}``), each patch from ``patches`` (``DRILL_PATCHES``)."""
    return {"instances": [{"id": i, "cause": c, "patch": (patches or DRILL_PATCHES)[i].decode()}
                          for i, c in sorted(causes.items())]}


def fixtures_value(doc: dict, imports: bytes) -> str:
    """``DRILL_FIXTURES``'s value: base64 of the RFC 8785 ``{import_line_sha256, instances}``, bound to the counter's
    last transfer line (``imports``)."""
    _, line = AC.last_import(imports)
    body = {"import_line_sha256": hashlib.sha256(line).hexdigest(), "instances": doc["instances"]}
    return base64.b64encode(CH.canonical(body)).decode()


def seed_for(catalog: dict, instance_id: str, run: str) -> dict:
    """A drill seed whose key for ``run`` selects ``instance_id`` (searched, so no selection is written here)."""
    for n in range(1000):
        seed = {"seed": "drill-seed-%d" % n}
        if RD.key(seed, run, catalog)["instance_id"] == instance_id:
            return seed
    raise AssertionError("no seed selects %s" % instance_id)


class D8(StateBase):
    """The revert drill over four cycles on one target: 9-1 commits, 10-1 plants the key's instance as the cycle's
    one merge, 11-1's ``kos`` watches it red and its ``yaz`` reverts it (D7), 12-1 reveals and judges it and commits
    the next drill."""

    def setUp(self) -> None:
        super().setUp()
        write_tree(self.src, {"pkg/sentinel.py": SENTINEL_PY})
        with open(os.path.join(self.workspace, "setup", "imports.jsonl"), "wb") as fh:  # the fixtures' import
            fh.write(YW.transfer()["imports"])
        self.catalog(DRILL_CAUSES)

    def catalog(self, causes: dict[str, str], patches: dict[str, bytes] | None = None) -> dict:
        """Sets the fixtures ``yaz`` is given from now on (bound to the checkout's counter); returns them."""
        doc = drill_catalog(causes, patches)
        self.fixtures = fixtures_value(doc, self.imports())
        return doc

    def imports(self) -> bytes:
        with open(os.path.join(self.workspace, "setup", "imports.jsonl"), "rb") as fh:
            return fh.read()

    def yaz(self, run: str, seed: dict | None, **env) -> dict:
        if seed is not None:
            env[DR.SEED_ENV] = seed["seed"]
            env.setdefault(DR.FIXTURES_ENV, self.fixtures)
        return self.run_yaz(GITHUB_RUN_ID=run, **env)

    def added(self, old: bytes) -> list[dict]:
        new = self.state_file(B.STATE_LEDGER)
        self.assertTrue(CH.verify_bytes(new, old)["valid"])
        self.assertEqual(SC.ledger_reasons(new), [])
        return rows_of(new)[len(rows_of(old)):]

    def commit_cycle(self, seed: dict) -> dict:
        """Cycle 9-1 with no candidate: the drill's commitment, nothing on ``brain/integration``."""
        self.kos({}, units=SENTINEL_UNITS)
        self.control(OPEN)
        self.github()
        integration = self.gh.refs[B.INTEGRATION]
        out = self.yaz("9", seed)
        self.assertEqual((out["ok"], out["done"]), (True, ["D5", "D6", "D8"]), out)
        self.assertEqual(self.gh.refs[B.INTEGRATION], integration)
        return out

    def chain(self, instance_id: str, causes: dict[str, str]) -> tuple[dict, dict]:
        """Cycles 9-1 to 12-1 with the seed that selects ``instance_id``; returns (cycle 12-1's line, the key)."""
        doc = self.catalog(causes)
        seed = seed_for(doc, instance_id, "9")
        key = RD.key(seed, "9", doc)
        old = self.state[B.STATE_LEDGER]
        out = self.commit_cycle(seed)
        self.assertEqual(out["drill"], {"action": "commit", "payload": RD.commit_payload(key)})
        self.assertNotIn(key["selection"], json.dumps(out))  # the key is not in the public line before the run
        added = self.added(old)
        self.assertEqual([(r["row_id"], r["part"], r["kind"]) for r in added],
                         [("9-1:start", "events", "cycle_start"), ("9-1:drill", "drill", "commit"),
                          ("cagir-9-1", "cost", "cost"), ("9-1:status", "events", "status")])
        self.assertEqual(added[1]["payload"]["commitment_sha256"], RD.commitment(key))
        # 10-1: nothing unfinished, no candidate: the key's instance is planted as the cycle's one merge
        self.assertEqual(self.next_cycle({}, "10", units=SENTINEL_UNITS)["done"], ["D3"])
        old, base = self.state[B.STATE_LEDGER], self.gh.refs[B.INTEGRATION]
        out = self.yaz("10", seed)
        self.assertEqual((out["ok"], out["done"], out["drill"]),
                         (True, ["D5", "D6", "D8"], {"action": "plant", "instance_id": instance_id, "path": "pkg/a.js"}))
        plant = out["written"]["plant"]
        self.assertEqual((self.gh.refs[B.INTEGRATION], plant["instance_id"]), (plant["merge_sha"], instance_id))
        self.assertEqual(self.gh.commits[plant["merge_sha"]]["parents"][0], base)
        self.assertEqual(self.gh.refs["brain/drill/10-1"], plant["head_sha"])
        self.assertEqual(self.gh.pulls[plant["pull"]]["head"], "brain/drill/10-1")
        check = [c for c in self.gh.checks if c["head_sha"] == plant["head_sha"]]
        self.assertEqual([(c["name"], c["conclusion"]) for c in check], [(B.CHECK, "success")])
        self.assertIn("not a gate decision", json.dumps(check))
        added = self.added(old)
        self.assertEqual([(r["row_id"], r["kind"]) for r in added],
                         [("10-1:start", "cycle_start"), ("10-1:ratchet", "ratchet_base"), ("10-1:drill", "plant"),
                          ("cagir-10-1", "cost"), ("10-1:status", "status")])
        self.assertEqual(added[2]["payload"], RD.plant_payload(instance_id, plant["merge_sha"]))
        self.assertEqual(SE.unfinished(self.state_file(B.STATE_LEDGER)), [plant["merge_sha"]])
        # 11-1: kos watches the planted merge (red); yaz reverts it with gate.revert's cause; the drill waits
        watched = self.next_cycle({}, "11", units=SENTINEL_UNITS)
        self.assertEqual((watched["done"], watched["index"]["sentinel"]["merge_sha"]),
                         (["D3", "D7"], plant["merge_sha"]))
        old = self.state[B.STATE_LEDGER]
        out = self.yaz("11", seed)
        self.assertEqual((out["ok"], out["done"], out["sentinel"]["verdict"], out["drill"]),
                         (True, ["D5", "D6", "D7", "D8"], "red", {"action": "wait", "why": "drill_unfinished"}))
        self.assertEqual(out["written"]["revert"]["reverted"], plant["merge_sha"])
        self.assertEqual(self.gh.read_file(B.INTEGRATION, "pkg/a.js"), A_JS.encode())
        added = self.added(old)
        self.assertEqual([(r["kind"], r.get("cause")) for r in added],
                         [("cycle_start", None), ("revert", out["written"]["revert"]["cause"]), ("cost", None),
                          ("status", None)])
        # 12-1: the planted merge is finished: the key is revealed and judged, and the next drill committed
        self.next_cycle({}, "12", units=SENTINEL_UNITS)
        old = self.state[B.STATE_LEDGER]
        out = self.yaz("12", seed)
        self.assertEqual(out["drill"]["judged"]["key"], key)
        self.assertEqual((out["drill"]["action"], out["drill"]["payload"]),
                         ("commit", RD.commit_payload(RD.key(seed, "12", doc))))
        self.assertEqual([(r["row_id"], r["kind"]) for r in self.added(old)][1], ("12-1:drill", "commit"))
        return out, key

    def test_each_planted_cause_is_reverted_with_the_keys_cause_and_judged_pass(self):
        for instance_id in (RD_LINT, RD_TEST, RD_BUILD):
            with self.subTest(instance_id):
                self.setUp()
                out, key = self.chain(instance_id, DRILL_CAUSES)
                self.assertEqual((out["ok"], "reason" in out, out["drill"]["judged"]["verdict"],
                                  out["drill"]["judged"]["reasons"]), (True, False, "PASS", []))
                self.assertEqual(key["cause"], DRILL_CAUSES[instance_id])
                # the seed's own judge, on the ledger as written, with the revealed key
                ledger = os.path.join(self.base, "ledger.jsonl")
                with open(ledger, "wb") as fh:
                    fh.write(self.state_file(B.STATE_LEDGER))
                keyfile = os.path.join(self.base, "key.json")
                with open(keyfile, "w") as fh:
                    json.dump(key, fh)
                with mock.patch("sys.stdout", new=io.StringIO()) as printed:
                    self.assertEqual(RD.main(["judge", ledger, keyfile]), 0)
                self.assertEqual(json.loads(printed.getvalue()), {"verdict": "PASS", "reasons": []})

    def test_a_catalog_cause_the_loop_does_not_give_is_judged_fail(self):
        """The fixtures say RD_TEST's planted merge (a red test, code that parses) is a build break; the loop
        reverts it as a test regression: the judge's cause_mismatch makes the job red after its writes."""
        out, key = self.chain(RD_TEST, SWAPPED_CAUSES)
        self.assertEqual((out["ok"], out["reason"], out["drill"]["judged"]["verdict"],
                          out["drill"]["judged"]["reasons"]), (False, "drill_fail", "FAIL", ["cause_mismatch"]))
        self.assertIn("written", out)

    def test_the_pass_row_judge_reads_the_drills_the_loop_wrote(self):
        """``harness.pass_row`` on the state these cycles wrote: one root and one status row per cycle, the drill
        judged as the loop judged it; the causes not planted here are unshown."""
        for planted, causes, geri in (
                (RD_TEST, DRILL_CAUSES, ["toy:cause_unshown:build_break", "toy:cause_unshown:lint_regression"]),
                (RD_BUILD, DRILL_CAUSES, ["toy:cause_unshown:test_regression", "toy:cause_unshown:lint_regression"]),
                (RD_TEST, SWAPPED_CAUSES, ["toy:drill_fail:%s:cause_mismatch" % RD_TEST,
                                           "toy:cause_unshown:test_regression", "toy:cause_unshown:build_break",
                                           "toy:cause_unshown:lint_regression"])):
            with self.subTest(planted=planted, causes=causes):
                self.setUp()
                self.chain(planted, causes)
                doc = drill_catalog(causes)
                state = {"ledger": self.state_file(B.STATE_LEDGER), "roots": self.state_file(B.STATE_ROOTS)}
                counter = YW.transfer()
                got = PR.judge(state, state, {}, {}, {"seed": seed_for(doc, planted, "9"), "catalog": doc},
                               counter["imports"], counter["result"])
                self.assertEqual(got["conditions"]["#geri-alma"], geri)
                self.assertEqual([got["conditions"][c] for c in ("#kok", "#durum", "#nobetci #hayatta")],
                                 [[], [], []])

    def test_the_drill_waits_for_a_candidates_merge_and_its_sentinel(self):
        seed = seed_for(drill_catalog(DRILL_CAUSES), RD_TEST, "9")
        write_tree(self.src, {"pkg/b.js": "var b = 1;\n"})  # the candidate's finding, on the target from cycle 9-1
        self.commit_cycle(seed)
        nxt = dict(candidate(diff("pkg/b.js", ["var b = 1;"], ["let b = 1;"])),
                   **{"finding.json": json.dumps(dict(FINDING, path="pkg/b.js")).encode()})
        self.next_cycle({"d": nxt}, "10", units=SENTINEL_UNITS)
        out = self.yaz("10", seed)
        self.assertEqual((out["merge"], out["drill"], out["written"]["plant"]),
                         ("d", {"action": "wait", "why": "candidate_merges"}, None))
        self.next_cycle({}, "11", units=SENTINEL_UNITS)
        out = self.yaz("11", seed)
        self.assertEqual((out["sentinel"]["verdict"], out["drill"]), ("green", {"action": "wait", "why": "merge_unfinished"}))
        self.next_cycle({}, "12", units=SENTINEL_UNITS)
        self.assertEqual(self.yaz("12", seed)["drill"]["action"], "plant")

    def test_a_changed_seed_or_a_patch_that_no_longer_applies_commits_again(self):
        doc = drill_catalog(DRILL_CAUSES)
        seed = seed_for(doc, RD_TEST, "9")
        self.commit_cycle(seed)
        self.next_cycle({}, "10", units=SENTINEL_UNITS)
        other = {"seed": seed["seed"] + "-changed"}
        out = self.yaz("10", other)
        self.assertEqual(out["drill"], {"action": "commit", "replaces": "commitment_mismatch",
                                        "payload": RD.commit_payload(RD.key(other, "10", doc))})
        self.assertIsNone(out["written"]["plant"])
        # the key's patch no longer applies at the head: abandoned; no instance fits, so nothing is committed
        self.next_cycle({}, "11", units=SENTINEL_UNITS)
        self.catalog(DRILL_CAUSES, {i: diff("pkg/a.js", ["var q = 9;"], ["let q = 9;"]) for i in DRILL_CAUSES})
        out = self.yaz("11", other)
        self.assertEqual(out["drill"], {"action": "none", "replaces": "patch_does_not_apply",
                                        "why": "patch_does_not_apply", "instances": sorted(DRILL_CAUSES)})
        self.assertEqual([r["part"] for r in self.added(self.state[B.STATE_LEDGER])].count("drill"), 0)

    def test_off_without_the_seed_and_unusable_inputs_write_nothing(self):
        """``loop.drill.fixtures``'s rules, each broken once: ``yaz`` stops before any write (exit 2), and the
        message names the rule, never a value of the secret (no patch, no id)."""
        self.kos({}, units=SENTINEL_UNITS)
        self.control(OPEN)
        self.github()
        doc = self.catalog(DRILL_CAUSES)
        good = json.loads(base64.b64decode(self.fixtures))

        def enc(body) -> str:
            return base64.b64encode(CH.canonical(body)).decode()

        def instances(change) -> str:
            items = [dict(i) for i in good["instances"]]
            change(items)
            return enc(dict(good, instances=items))

        cases = {
            "not base64": "@" * 8,
            "base64 with an LF": self.fixtures + "\n",
            "base64 unpadded": self.fixtures.rstrip("=") if self.fixtures.endswith("=") else self.fixtures[:-1],
            "base64 with a blank": self.fixtures[:4] + " " + self.fixtures[4:],
            "not ASCII": "\u00c4" * 8,
            "not JSON": base64.b64encode(b"not json").decode(),
            "not a JSON object": enc([good]),
            "JSON that is not RFC 8785": base64.b64encode(json.dumps(good, indent=1).encode()).decode(),
            "a key more": enc(dict(good, more=1)),
            "an import hash that is not hex": enc(dict(good, import_line_sha256="Z" * 64)),
            "no instances": enc(dict(good, instances=[])),
            "an instance key more": instances(lambda items: items[0].update(file="x")),
            "an id that is not 32 hex": instances(lambda items: items[0].update(id="rd-test")),
            "an id in upper case": instances(lambda items: items[0].update(id=items[0]["id"].upper())),
            # a fourth instance, so the three causes stay balanced and only the cause rule refuses it
            "a cause outside 26f's three": instances(lambda items: items.append(dict(items[0], id="e0" * 16,
                                                                                    cause="unknown"))),
            "an empty patch": instances(lambda items: items[0].update(patch="")),
            "a repeated id": instances(lambda items: items[1].update(id=items[0]["id"])),
            "a cause given twice": instances(lambda items: items.append(dict(items[0], id="e0" * 16))),
            "a cause missing": instances(lambda items: items.pop()),
        }
        for name, value in cases.items():
            with self.subTest(name):
                with self.assertRaises(J.Unusable) as raised:
                    self.yaz("9", {"seed": "s"}, **{DR.FIXTURES_ENV: value})
                for item in doc["instances"]:
                    self.assertNotIn(item["id"], str(raised.exception))
                    self.assertNotIn(item["patch"].splitlines()[-1], str(raised.exception))
                self.assertEqual(self.writes(), [])
        imports = os.path.join(self.workspace, "setup", "imports.jsonl")
        for name, change in (("no workspace", None), ("a counter with no import", b"")):
            with self.subTest(name), self.assertRaises(J.Unusable):
                if change is not None:
                    with open(imports, "wb") as fh:
                        fh.write(change)
                self.yaz("9", {"seed": "s"}, **({"GITHUB_WORKSPACE": ""} if change is None else {}))
            self.assertEqual(self.writes(), [])
        with self.assertRaises(J.Unusable):  # a run id that is not decimal digits
            self.yaz("9x", {"seed": "s"})
        self.assertEqual(self.writes(), [])
        out = self.yaz("9", None, **{DR.FIXTURES_ENV: self.fixtures})  # the fixtures without the seed: off
        self.assertEqual((out["ok"], out["done"], out["drill"]), (True, ["D5", "D6"], {"action": "off"}))
        self.assertNotIn("drill", [r["part"] for r in rows_of(self.state_file(B.STATE_LEDGER))])

    def test_without_fixtures_or_with_another_imports_the_drill_is_off_and_the_cycle_is_written(self):
        """tohum/26f: the seed without the fixtures secret turns D8 off (``fixtures_absent``), and fixtures bound to
        another import than the counter's last are off too, the reason named (``fixtures_import_mismatch``); the
        cycle's state is written as without the seed."""
        doc = self.catalog(DRILL_CAUSES)
        bound = json.loads(base64.b64decode(self.fixtures))
        self.assertEqual(bound["import_line_sha256"], hashlib.sha256(AC.last_import(self.imports())[1]).hexdigest())
        # another import's line: the counter's previous line, the one a red (B)'s burnt set was bound to (25a)
        other = hashlib.sha256(self.imports().rstrip(b"\n").split(b"\n")[0]).hexdigest()
        self.assertNotEqual(other, bound["import_line_sha256"])
        stale = base64.b64encode(CH.canonical(dict(bound, import_line_sha256=other))).decode()
        for name, value, why in (("absent", "", "fixtures_absent"), ("stale", stale, "fixtures_import_mismatch")):
            with self.subTest(name):
                self.setUp()
                self.kos({}, units=SENTINEL_UNITS)
                self.control(OPEN)
                self.github()
                out = self.yaz("9", {"seed": "s"}, **{DR.FIXTURES_ENV: value})
                self.assertEqual((out["ok"], out["done"], out["drill"]),
                                 (True, ["D5", "D6"], {"action": "off", "why": why}))
                self.assertEqual([p for m, p in self.writes() if p.endswith("git/refs/heads/brain/state")],
                                 ["/repos/acme/t1/git/refs/heads/brain/state"])
                self.assertNotIn("drill", [r["part"] for r in rows_of(self.state_file(B.STATE_LEDGER))])

    def test_the_drill_is_the_toys_a_copy_with_the_seed_is_off(self):
        doc = self.catalog(DRILL_CAUSES)
        seed = seed_for(doc, RD_TEST, "9")
        for kind, want in (("copy", {"action": "off"}),
                           ("toy", {"action": "commit", "payload": RD.commit_payload(RD.key(seed, "9", doc))})):
            with self.subTest(kind=kind):
                shutil.rmtree(os.path.join(self.temp, "in"), ignore_errors=True)
                self.kos({}, target=dict(TARGET, kind=kind, repo=YW.REPO), units=SENTINEL_UNITS)
                self.control(OPEN)
                self.github()
                self.assertEqual(P.read(self.pulled).target["kind"], kind)
                out = self.yaz("9", seed)
                self.assertEqual((out["ok"], out["done"], out["drill"]),
                                 (True, ["D5", "D6"] + (["D8"] if kind == "toy" else []), want))
                parts = [r["part"] for r in rows_of(self.state_file(B.STATE_LEDGER))]
                self.assertEqual(parts.count("drill"), 0 if kind == "copy" else 1)
                self.assertEqual([p for m, p in self.writes() if "/git/refs" in p],
                                 ["/repos/acme/t1/git/refs/heads/brain/state"])  # nothing planted

    def test_write_cycle_refuses_a_plant_beside_a_merge_or_an_end_and_an_unknown_action(self):
        self.kos({"c": candidate(GOOD)}, units=SENTINEL_UNITS)
        self.control(OPEN)
        self.github()
        art = P.read(self.pulled)
        tree = self.tree()
        plant = {"action": "plant", "instance_id": RD_TEST, "path": "pkg/a.js", "content": b"x\n"}
        lint = WT.base_lint(self.results())
        for name, decided, end, drill in (
                ("beside a merge", {"decisions": {"c": {"reasons": []}}, "merge": "c"}, None, plant),
                ("beside an end", {"decisions": {}, "merge": None}, {"merge_sha": art.heads[B.INTEGRATION]}, plant),
                ("unknown", {"decisions": {}, "merge": None}, None, {"action": "reveal"})):
            with self.subTest(name), self.assertRaises(WC.Unusable):
                WC.write(art, tree, decided, [], W.Writer(YW.REPO, self.gh), self.signer, b"", "9-1", YW.TS, lint,
                         end, drill)
        self.assertEqual(self.writes(), [])


class Gate(StateBase):
    """The copy's genesis gate (tohum/25a row 7): ``yaz`` judges it on the toy's ``pulled`` state with the drill seed
    and the checkout's counter, and an open gate's ``copy_gate`` row is written in the toy's cycle, once."""

    def setUp(self) -> None:
        super().setUp()
        import test_pass_row as TP
        self.TP = TP
        self.toy = TP.toy_world()  # every condition holds on it (test_pass_row.Gate)
        self.state = {B.STATE_LEDGER: self.toy.ledger, B.STATE_ROOTS: self.toy.roots, B.STATE_STATUS: self.toy.status}
        with open(os.path.join(self.workspace, "setup", "imports.jsonl"), "wb") as fh:
            fh.write(TP.IMPORTS)
        doc = drill_catalog(DRILL_CAUSES)
        self.assertEqual([(i["id"], i["cause"]) for i in doc["instances"]],
                         [(i["id"], i["cause"]) for i in TP.CATALOG["instances"]])  # the same keys
        self.seed = {DR.SEED_ENV: TP.SEED["seed"], DR.FIXTURES_ENV: fixtures_value(doc, TP.IMPORTS)}

    def cycle_on(self, target=None, run="300", **env) -> dict:
        shutil.rmtree(os.path.join(self.temp, "in"), ignore_errors=True)
        self.kos({}, target=target or dict(TARGET, repo=YW.REPO), units=SENTINEL_UNITS)
        self.control(OPEN)
        self.github()
        art = P.read(self.pulled)  # this run's response (its cost row id is the run's)
        shutil.rmtree(os.path.join(self.temp, "in", "response"))
        YW.write_response(self.temp, "t1", art.heads, [YW.cost_row("cagir-%s-1" % run, art.heads[B.INTEGRATION])])
        return self.run_yaz(GITHUB_RUN_ID=run, **env)

    def test_an_open_gate_writes_its_row_once(self):
        old = self.state[B.STATE_LEDGER]
        out = self.cycle_on(**self.seed)
        self.assertEqual((out["ok"], out["gate"]), (True, {"verdict": "open", "conditions": {}}), out)
        new = self.state_file(B.STATE_LEDGER)
        self.assertTrue(CH.verify_bytes(new, old)["valid"])
        self.assertEqual(SC.ledger_reasons(new), [])
        added = rows_of(new)[len(rows_of(old)):]
        [row] = [r for r in added if r["kind"] == "copy_gate"]
        self.assertEqual((row["row_id"], row["part"], row["payload"], "proposed_by" in row),
                         ("300-1:gate", "events", PR.gate_payload(), False))
        kinds = [r["kind"] for r in added]  # after D8's row, before the cost and status rows
        self.assertEqual(kinds[kinds.index("copy_gate") + 1:], ["cost", "status"])
        self.assertTrue(PR.gate_opened(new))
        # the next cycle on that state does not judge it again: no gate in the line, no second row
        self.state = {p: self.state_file(p) for p in B.STATE_CHAINS + (B.STATE_STATUS,)}
        out = self.cycle_on(run="301", **self.seed)
        self.assertEqual(out["ok"], True, out)
        self.assertNotIn("gate", out)
        self.assertEqual([r["kind"] for r in rows_of(self.state_file(B.STATE_LEDGER))].count("copy_gate"), 1)

    def test_a_closed_gate_writes_no_row_and_names_its_reasons(self):
        old = self.state[B.STATE_LEDGER]
        out = self.cycle_on()  # no seed: the drill is off and #geri-alma cannot be judged
        self.assertEqual((out["ok"], out["gate"]),
                         (True, {"verdict": "closed", "conditions": {"#geri-alma": ["toy:drill_inputs_missing"]}}))
        self.assertNotIn("copy_gate", [r["kind"] for r in rows_of(self.state_file(B.STATE_LEDGER))])
        self.assertTrue(CH.verify_bytes(self.state_file(B.STATE_LEDGER), old)["valid"])
        # the toy's own state judged: a flaky sentinel closes it whatever the seed
        self.toy = self.TP.toy_world(verdict="flaky")
        self.state = {B.STATE_LEDGER: self.toy.ledger, B.STATE_ROOTS: self.toy.roots, B.STATE_STATUS: self.toy.status}
        out = self.cycle_on(**self.seed)
        self.assertEqual(out["gate"]["conditions"], {"#nobetci #hayatta": ["toy:sentinel_flaky:" + self.TP.h(0xa1)]})

    def test_an_expectation_it_cannot_use_keeps_it_closed_and_the_cycle_goes_on(self):
        bad = dict(candidate(GOOD), **{"expect.json": b'{"decision": "maybe"}'})
        shutil.rmtree(os.path.join(self.temp, "in"), ignore_errors=True)
        self.kos({"good": bad}, target=dict(TARGET, repo=YW.REPO), units=SENTINEL_UNITS)
        self.control(OPEN)
        self.github()
        out = self.run_yaz(GITHUB_RUN_ID="300", **self.seed)
        self.assertEqual((out["ok"], out["gate"]["verdict"], out["gate"]["conditions"]), (True, "closed", {}), out)
        self.assertIn("expect.json", out["gate"]["unusable"])
        self.assertNotIn("copy_gate", [r["kind"] for r in rows_of(self.state_file(B.STATE_LEDGER))])

    def test_only_the_toy_is_judged(self):
        out = self.cycle_on(target=dict(TARGET, kind="copy", repo=YW.REPO), **self.seed)
        self.assertEqual(out["ok"], True, out)
        self.assertNotIn("gate", out)
        self.assertNotIn("copy_gate", [r["kind"] for r in rows_of(self.state_file(B.STATE_LEDGER))])

    def test_write_cycle_writes_the_gate_row_it_is_given(self):
        self.kos({}, units=SENTINEL_UNITS)
        self.control(OPEN)
        self.github()
        art = P.read(self.pulled)
        got = WC.write(art, self.src, {"decisions": {}, "merge": None}, [], W.Writer(YW.REPO, self.gh), self.signer,
                       self.TP.IMPORTS, "301-1", "2026-11-02T10:00:00Z", gate={"conditions": ["#kok"]})
        rows = rows_of(self.state_file(B.STATE_LEDGER))[len(rows_of(self.state[B.STATE_LEDGER])):]
        self.assertEqual([(r["row_id"], r["kind"]) for r in rows],
                         [("301-1:start", "cycle_start"), ("301-1:gate", "copy_gate"), ("301-1:status", "status")])
        self.assertEqual(rows[1]["payload"], {"conditions": ["#kok"]})
        self.assertEqual(got["rows"], 3)


class Pass(StateBase):
    """The PASS row (tohum/26d, asama-0/08 row 9): once the toy's run holds the gate's row, ``yaz`` judges
    ``harness.pass_row.judge`` on the toy's and the copy's ``pulled`` states with the checkout's counter and the (A)
    result it names, and a PASS row is added to the toy's cycle, once."""

    def setUp(self) -> None:
        super().setUp()
        import test_pass_row as TP
        self.TP = TP
        self.counted(TP.COUNTER)

    def counted(self, counter: dict) -> None:
        """The toy and the copy of ``counter``'s import (their genesis rows name it), the checkout holding that
        counter and the (A) result it names, and the drill's fixtures bound to its line."""
        TP = self.TP
        toy, copy = TP.State("toy"), TP.State("copy")
        # every condition holds on the toy and on the copy world (test_pass_row.Passes)
        TP.toy_world(toy, genesis=TP.genesis_payload("toy", counter))
        toy.cycle(TP.gate_row, TP.cost)  # the gate opened in an earlier cycle of the run
        self.toy, self.copy = toy, TP.copy_world(copy, genesis=TP.genesis_payload("copy", counter))
        for path, data in (("imports.jsonl", counter["imports"]),
                           ("results/%s.json" % hashlib.sha256(counter["result"]).hexdigest(), counter["result"])):
            write_tree(os.path.join(self.workspace, "setup"), {path: data})
        doc = drill_catalog(DRILL_CAUSES)
        self.seed = {DR.SEED_ENV: TP.SEED["seed"], DR.FIXTURES_ENV: fixtures_value(doc, counter["imports"])}

    def states(self) -> dict:
        return {tid: {B.STATE_LEDGER: w.ledger, B.STATE_ROOTS: w.roots, B.STATE_STATUS: w.status}
                for tid, w in (("t1", self.toy), ("t2", self.copy))}

    def served(self, kinds=(("t1", "toy"), ("t2", "copy")), run="300", genesis=(), cands=None) -> dict:
        """``in/pulled`` serving ``kinds`` in order, each on its own state (``states``; a target in ``genesis`` in
        loop.pulled's genesis form) with ``cands[tid]`` (none by default), ``kos`` run on all, the run's responses
        written. Returns the fake GitHubs."""
        shutil.rmtree(os.path.join(self.temp, "in"), ignore_errors=True)
        served = os.path.dirname(self.pulled)
        os.makedirs(served)
        P.write_served(served, [tid for tid, _ in kinds])
        states = self.states()
        for tid, kind in kinds:
            self.pulled = os.path.join(served, tid)
            state = states.get(tid, states["t2"])
            offered = (cands or {}).get(tid, {})
            if tid in genesis:
                self.write_pulled(offered, target=dict(TARGET, id=tid, kind=kind, repo="acme/" + tid),
                                  units=SENTINEL_UNITS, heads={B.STATE: None, B.INTEGRATION: HEADS[B.INTEGRATION]},
                                  state={p: b"" for p in B.STATE_CHAINS}, status=None)
            else:
                self.write_pulled(offered, target=dict(TARGET, id=tid, kind=kind, repo="acme/" + tid),
                                  units=SENTINEL_UNITS, state={p: state[p] for p in B.STATE_CHAINS},
                                  status=state[B.STATE_STATUS])
        self.pulled = os.path.join(served, "t1")
        kos = J.run("kos", {"RUNNER_TEMP": self.temp}, runner=RedAs())
        self.assertEqual(kos["ok"], True, kos)
        shutil.move(os.path.join(self.temp, "out", "results"), os.path.join(self.temp, "in", "results"))
        self.control(OPEN)
        for tid, _ in kinds:
            YW.write_response(self.temp, tid, HEADS, [YW.cost_row("cagir-%s-%s" % (run, tid), HEADS[B.INTEGRATION])],
                              at=tid)
        return {tid: YW.github_at(HEADS, YW.files_of(self.src), states.get(tid, states["t2"]), repo="acme/" + tid)
                for tid, _ in kinds}

    def run_both(self, ghs: dict, run="300", **env) -> dict:
        return J.run("yaz", YW.env(self.temp, self.workspace, GITHUB_RUN_ID=run, **env), transport=Router(ghs),
                     signer=self.signer, now=lambda: YW.NOW)

    def judged(self, **env) -> tuple:
        """``loop.job.yaz_pass`` on t1's ``pulled`` as served."""
        return J.yaz_pass(YW.env(self.temp, self.workspace, **env), "t1", P.read(self.pulled))

    def test_a_pass_writes_its_row_on_the_toys_cycle_once(self):
        ghs = self.served()
        out = self.run_both(ghs, **self.seed)
        self.assertEqual(out["ok"], True, out)
        toy, copy = out["targets"]
        self.assertEqual(toy["pass"], {"verdict": "PASS", "conditions": {}}, toy)
        self.assertNotIn("pass", copy)  # the copy is not judged on its own cycle
        old, new = self.toy.ledger, ghs["t1"].read_file(B.STATE, B.STATE_LEDGER)
        self.assertTrue(CH.verify_bytes(new, old)["valid"])
        self.assertEqual(SC.ledger_reasons(new), [])
        added = rows_of(new)[len(rows_of(old)):]
        [row] = [r for r in added if r["kind"] == "pass"]
        want = PR.judge(self.TP.State.files(self.toy), self.copy.files(), {}, {},
                        {"seed": self.TP.SEED, "catalog": self.TP.CATALOG}, self.TP.IMPORTS, self.TP.RESULT)
        self.assertEqual(want["verdict"], "PASS")
        # tohum/26d: the referee's own row, part events, the judge's payload (the copy's genesis and merge rows)
        self.assertEqual((row["row_id"], row["part"], row["trust"], row["derivation"], "proposed_by" in row),
                         ("300-1:pass", "events", "verified", "tool", False))
        self.assertEqual(row["payload"], want["payload"])
        copy_rows = rows_of(self.copy.ledger)
        self.assertEqual(row["payload"]["copy_genesis_row_hash"], copy_rows[0]["row_hash"])
        self.assertEqual(row["payload"]["copy_merge_row_hashes"],
                         [r["row_hash"] for r in copy_rows if r["kind"] == "merge"])
        kinds = [r["kind"] for r in added]  # after D8's row, before the cost and status rows
        self.assertEqual(kinds[kinds.index("pass") - 1:], ["commit", "pass", "cost", "status"])
        self.assertNotIn("pass", [r["kind"] for r in rows_of(ghs["t2"].read_file(B.STATE, B.STATE_LEDGER))])
        # the state written: PASS again, and its run holds the row
        written = {"ledger": new, "roots": ghs["t1"].read_file(B.STATE, B.STATE_ROOTS)}
        self.assertEqual(PR.judge(written, self.copy.files(), {}, {}, {"seed": self.TP.SEED, "catalog":
                                  self.TP.CATALOG}, self.TP.IMPORTS, self.TP.RESULT)["verdict"], "PASS")
        self.assertTrue(PR.passed(new))
        # the next cycle on that state does not judge it again: no pass in the line, no second row
        self.toy.ledger, self.toy.roots = new, written["roots"]
        self.toy.status = ghs["t1"].read_file(B.STATE, B.STATE_STATUS)
        ghs = self.served(run="301")
        out = self.run_both(ghs, run="301", **self.seed)
        self.assertEqual(out["ok"], True, out)
        self.assertNotIn("pass", out["targets"][0])
        self.assertEqual([r["kind"] for r in rows_of(ghs["t1"].read_file(B.STATE, B.STATE_LEDGER))].count("pass"), 1)

    def test_the_row_written_carries_the_owner_exceptions_of_the_a_result(self):
        """(A)'s result with the owner's two exceptions (tohum/02 "Sahip istisnası", 26d:45-47): ``yaz`` judges
        ``PASS`` and the row on the toy's ``brain/state`` carries the result's ``exit.owner_exception`` with the
        same RFC 8785 bytes, which is stage-open's check 7; the ledger written conforms to ``ledger.schema``."""
        counter = YW.transfer({"requested": True, "transferable": True, "owner_exception": YW.OWNER_EXCEPTIONS})
        self.counted(counter)
        ghs = self.served()
        out = self.run_both(ghs, **self.seed)
        self.assertEqual(out["ok"], True, out)
        self.assertEqual(out["targets"][0]["pass"], {"verdict": "PASS", "conditions": {}})
        new = ghs["t1"].read_file(B.STATE, B.STATE_LEDGER)
        self.assertEqual(SC.ledger_reasons(new), [])
        [row] = [r for r in rows_of(new) if r["kind"] == "pass"]
        in_result = json.loads(counter["result"])["exit"]["owner_exception"]
        self.assertEqual([e["anchor"] for e in in_result], ["durustluk", "spec"])
        self.assertEqual(CH.canonical(row["payload"]["owner_exception"]), CH.canonical(in_result))
        self.assertEqual(row["payload"]["import_line_sha256"], counter["line_sha256"])

    def test_a_fail_writes_no_row_and_names_its_reasons(self):
        ghs = self.served()
        out = self.run_both(ghs)  # no seed: the drill is off and #geri-alma cannot be judged
        self.assertEqual(out["ok"], True, out)
        self.assertEqual(out["targets"][0]["pass"],
                         {"verdict": "FAIL", "conditions": {"#geri-alma": ["toy:drill_inputs_missing"]}})
        new = ghs["t1"].read_file(B.STATE, B.STATE_LEDGER)
        self.assertTrue(CH.verify_bytes(new, self.toy.ledger)["valid"])  # the cycle is written
        self.assertNotIn("pass", [r["kind"] for r in rows_of(new)])
        # the copy's own state judged: a served model of the copy's canary that is not the requested one fails it
        # whatever the seed
        row = self.copy.cycle(lambda c: self.TP.cost(c, served=["other"]))["cycle_id"]
        self.served()
        line, payload = self.judged(**self.seed)
        self.assertEqual((line, payload), ({"verdict": "FAIL", "conditions": {
            "#model #belirtec": ["copy:model_mismatch:cagir-%s" % row]}}, None))

    def test_not_judged_before_the_gate_or_on_a_copy_or_without_a_copy_with_a_state(self):
        self.toy = self.TP.toy_world()  # no gate row: the gate's cycle, not the PASS's
        self.served()
        self.assertEqual(self.judged(**self.seed), (None, None))
        self.setUp()
        self.served(kinds=(("t1", "copy"), ("t2", "toy")))  # t1 is a copy: never judged on it
        self.assertEqual(self.judged(**self.seed), (None, None))
        self.setUp()
        self.served(kinds=(("t1", "toy"),))
        self.assertEqual(self.judged(**self.seed), ({"waiting": "copy_not_served"}, None))
        self.served(genesis=("t2",))
        self.assertEqual(self.judged(**self.seed), ({"waiting": "copy_genesis"}, None))
        self.served(kinds=(("t1", "toy"), ("t2", "toy")))  # another toy is no copy
        self.assertEqual(self.judged(**self.seed), ({"waiting": "copy_not_served"}, None))

    def test_inputs_it_cannot_use_fail_it_and_the_cycle_goes_on(self):
        result = os.path.join(self.workspace, "setup", "results", "%s.json" % hashlib.sha256(self.TP.RESULT).hexdigest())
        with open(result, "wb") as fh:  # at the right name, other bytes: not the result the import names
            fh.write(self.TP.RESULT + b" ")
        ghs = self.served()
        out = self.run_both(ghs, **self.seed)
        self.assertEqual(out["ok"], True, out)
        got = out["targets"][0]["pass"]
        self.assertEqual((got["verdict"], got["conditions"]), ("FAIL", {}))
        self.assertIn("result_sha256", got["unusable"])
        self.assertNotIn("pass", [r["kind"] for r in rows_of(ghs["t1"].read_file(B.STATE, B.STATE_LEDGER))])
        # an expect.json of the copy's candidates it cannot use
        with open(result, "wb") as fh:
            fh.write(self.TP.RESULT)
        self.served(cands={"t2": {"bad": dict(candidate(GOOD), **{"expect.json": b'{"decision": "maybe"}'})}})
        line, payload = self.judged(**self.seed)
        self.assertEqual((line["verdict"], line["conditions"], payload), ("FAIL", {}, None))
        self.assertIn("expect.json", line["unusable"])

    def test_a_missing_result_or_a_second_copy_is_unusable_before_any_write(self):
        os.remove(os.path.join(self.workspace, "setup", "results", "%s.json" % hashlib.sha256(self.TP.RESULT).hexdigest()))
        ghs = self.served()
        with self.assertRaises(J.Unusable) as caught:
            self.run_both(ghs, **self.seed)
        self.assertIn("setup/results/", str(caught.exception))
        self.assertEqual([r for gh in ghs.values() for r in gh.requests if r[0] != "GET"], [])
        self.setUp()
        self.served(kinds=(("t1", "toy"), ("t2", "copy"), ("t3", "copy")))
        with self.assertRaises(J.Unusable) as caught:
            self.judged(**self.seed)
        self.assertIn("more than one copy", str(caught.exception))

    def test_write_cycle_writes_the_pass_row_it_is_given(self):
        self.served(kinds=(("t1", "toy"),))
        art = P.read(self.pulled)
        gh = YW.github_at(art.heads, YW.files_of(self.src), self.states()["t1"], repo="acme/t1")
        payload = self.TP.judge()["payload"]
        got = WC.write(art, self.src, {"decisions": {}, "merge": None}, [], W.Writer("acme/t1", gh), self.signer,
                       self.TP.IMPORTS, "301-1", "2026-11-02T10:00:00Z", passed=payload)
        new = gh.read_file(B.STATE, B.STATE_LEDGER)
        rows = rows_of(new)[len(rows_of(self.toy.ledger)):]
        self.assertEqual([(r["row_id"], r["kind"]) for r in rows],
                         [("301-1:start", "cycle_start"), ("301-1:pass", "pass"), ("301-1:status", "status")])
        self.assertEqual(rows[1]["payload"], payload)
        self.assertEqual((got["rows"], SC.ledger_reasons(new)), (3, []))


class Genesis(StateBase):
    """The genesis cycle (``loop.pulled.genesis``): ``kos`` then ``yaz`` on a toy with neither head, whose
    ``pulled`` was read from its ``main``; ``yaz`` runs ``activate`` with D5's answer, D3's base run and D4's cost
    rows, and the next cycle is an ordinary one on what it wrote."""

    def setUp(self) -> None:
        super().setUp()
        self.state = dict({p: b"" for p in B.STATE_CHAINS}, **{B.STATE_STATUS: None})
        self.transfer = YW.transfer()
        summary = {"seed_epochs": [{"commit": "1" * 40, "spec_tohum_sha256": "2" * 64, "seed_sha256": "3" * 64,
                                    "bootstrap_sha256": "4" * 64}],
                   "targets": [dict(TARGET, repo=YW.REPO, base_sha="c" * 40, identifiers=[])]}
        self.security = YW.chained([{"row_id": "sec-1", "part": "security", "kind": "note", "payload": {}}])
        write_tree(self.workspace, {"setup/summary.json": json.dumps(summary), "setup/imports.jsonl":
                                    self.transfer["imports"].decode(), J.SECURITY_LEDGER: self.security.decode()})
        self.gh = None

    def write_pulled(self, cands=None, **kw) -> dict:
        kw.setdefault("heads", {B.STATE: None, B.INTEGRATION: self.main_at()})
        return super().write_pulled(cands, **kw)

    def main_at(self) -> str:
        """The toy's GitHub: ``main`` only, at a commit holding the tree, and the facts genesis reads."""
        if self.gh is None:
            self.gh = YW.FakeGitHub(YW.REPO, required_check=B.CHECK)
            self.gh.refs["main"] = self.gh.seed_commit("toy-main", files=YW.files_of(self.src))
            self.gh.overrides.update(AW.facts("toy", YW.REPO))
        return self.gh.refs["main"]

    def github(self) -> None:
        art = P.read(self.pulled)
        shutil.rmtree(os.path.join(self.temp, "in", "response"), ignore_errors=True)
        YW.write_response(self.temp, "t1", art.heads, [YW.cost_row(snapshot=art.heads[B.INTEGRATION])])

    def test_the_activation_writes_the_cycle_and_the_next_cycle_extends_it(self):
        write_tree(self.src, {"pkg/b.js": "var b = 1;\n"})
        main = self.main_at()
        out = self.cycle({"good": candidate(GOOD), "breaks": candidate(BREAKS_TEST)})
        self.assertEqual((out["ok"], out["done"], out["merge"], out["drill"]),
                         (True, ["D5", "D6"], "good", {"action": "off", "why": "genesis"}), out)
        written = out["written"]
        self.assertEqual(set(written), set(J.GENESIS_WRITTEN) | {"genesis"})
        self.assertEqual((written["genesis"], written["integration_sha"]), (True, main))
        # the cut at main, D5's merge on it, brain/state an orphan; main untouched
        merge = written["merge"]
        self.assertEqual((merge["candidate"], merge["path"]), ("good", "pkg/a.js"))
        self.assertEqual(self.gh.refs[B.INTEGRATION], merge["merge_sha"])
        self.assertEqual(self.gh.commits[merge["merge_sha"]]["parents"][0], main)
        self.assertEqual(self.gh.refs["main"], main)
        self.assertEqual(self.gh.commits[self.gh.refs[B.STATE]]["parents"], [])
        ledger = self.state_file(B.STATE_LEDGER)
        self.assertEqual(SC.ledger_reasons(ledger), [])
        rows = rows_of(ledger)
        self.assertEqual([(r["row_id"], r["kind"]) for r in rows],
                         [("9-1:genesis", "genesis"), ("9-1:start", "cycle_start"), ("9-1:cut", "integration_cut"),
                          ("9-1:ratchet", "ratchet_base"), ("9-1:c:breaks", "decision"), ("9-1:c:good", "decision"),
                          ("9-1:m:good", "merge"), ("cagir-9-1", "cost"), ("9-1:status", "status")])
        payload = rows[0]["payload"]
        self.assertEqual((payload["target"], payload["base_sha"]), ("t1", main))
        self.assertEqual(payload["import_line_sha256"], self.transfer["line_sha256"])
        self.assertEqual(payload["seed_security_ledger_sha256"], hashlib.sha256(self.security).hexdigest())
        art = P.read(self.pulled)
        self.assertEqual(payload["policy_sha256"], hashlib.sha256(art.policy_bytes).hexdigest())
        self.assertEqual(payload["recipe_sha256"], hashlib.sha256(CH.canonical(art.units["units"][0])).hexdigest())
        with open(self.results("base.jsonl"), "rb") as fh:
            base_run = fh.read()
        self.assertEqual(rows[3]["payload"]["base_run_sha256"], hashlib.sha256(base_run).hexdigest())
        self.assertEqual(rows[4]["payload"], {"decision": "reject", "candidate": "breaks", "reasons": ["tests_red"]})
        self.assertEqual(SE.unfinished(ledger), [merge["merge_sha"]])
        self.assertEqual([hashlib.sha256(p).hexdigest() for p in self.signer.payloads], [AN.root_of(AN.tips(ledger))])
        # the next cycle: an ordinary one on the state the activation wrote; D7 ends the merge's green sentinel
        other = dict(candidate(diff("pkg/b.js", ["var b = 1;"], ["let b = 1;"])),
                     **{"finding.json": json.dumps(dict(FINDING, path="pkg/b.js")).encode()})
        self.next_cycle({"good": other}, "10")
        self.assertFalse(P.genesis(P.read(self.pulled)))
        out = self.run_yaz(GITHUB_RUN_ID="10")
        self.assertEqual((out["ok"], out["done"], out["sentinel"]["verdict"]), (True, ["D5", "D6", "D7"], "green"), out)
        new = self.state_file(B.STATE_LEDGER)
        self.assertTrue(CH.verify_bytes(new, ledger)["valid"])
        self.assertEqual(self.gh.commits[self.gh.refs[B.STATE]]["parents"], [written["state_sha"]])
        self.assertEqual(SE.unfinished(new), [])

    def test_nothing_is_written_when_the_activation_refuses(self):
        self.main_at()
        self.gh.overrides[("GET", "/repos/%s/actions/workflows" % YW.REPO)] = (200, {"workflows": [{"id": 1}]})
        out = self.cycle({"good": candidate(GOOD)})
        self.assertEqual((out["ok"], out["reason"], out["reasons"], out["done"]),
                         (False, "activation_refused", ["toy_workflows"], ["D5"]))
        self.assertEqual(self.writes(), [])
        # main moved after D1 read it: base_moved
        self.gh.overrides[("GET", "/repos/%s/actions/workflows" % YW.REPO)] = (200, {"workflows": []})
        self.gh.refs["main"] = self.gh.seed_commit("toy-main-2", [self.gh.refs["main"]], files={"x": b"y"})
        self.assertEqual(self.run_yaz()["reasons"], ["base_moved"])
        self.assertEqual(self.writes(), [])

    def test_inputs_the_genesis_cycle_needs(self):
        """The checkout's seed security ledger (tohum/29o) and D3's base run; without either nothing is written."""
        self.main_at()
        self.kos({"good": candidate(GOOD)})
        self.control(OPEN)
        self.github()
        path = os.path.join(self.workspace, *J.SECURITY_LEDGER.split("/"))
        os.rename(path, path + ".away")
        with self.assertRaises(J.Unusable) as ctx:
            self.run_yaz()
        self.assertIn(J.SECURITY_LEDGER, str(ctx.exception))
        self.assertEqual(self.writes(), [])
        os.rename(path + ".away", path)
        with open(self.results("base.jsonl"), "ab") as fh:  # not the base run D3's index names
            fh.write(b"\n")
        out = self.run_yaz()
        self.assertEqual((out["reason"], out["reasons"]), ("activation_refused", ["base_run_hash_mismatch"]))
        self.assertEqual(self.writes(), [])
        os.remove(self.results("base.jsonl"))
        out = self.run_yaz()
        self.assertEqual((out["reason"], out["reasons"]), ("activation_refused", ["base_run_missing"]))
        self.assertEqual(self.writes(), [])


class Router:
    """One transport for the targets' fake GitHubs, by the repository a request's path names (``/repos/<o>/<n>/``);
    ``calls`` is ``(repository, path)`` in request order."""

    def __init__(self, ghs: dict) -> None:
        self.ghs = {gh.prefix: gh for gh in ghs.values()}
        self.calls: list[tuple[str, str]] = []

    def __call__(self, method: str, path: str, body):
        [prefix] = [p for p in self.ghs if path.startswith(p)]
        self.calls.append((prefix[len("/repos/"):-1], path))
        return self.ghs[prefix](method, path, body)


class LandRevert(unittest.TestCase):
    def test_runs_that_are_not_red_write_nothing(self):
        gh = YW.github_at(HEADS, {"pkg/a.js": A_JS.encode()})
        writer = W.Writer(YW.REPO, gh)
        passing, failing = {"results": [{"id": "a", "status": "pass"}]}, {"results": [{"id": "a", "status": "fail"}]}
        for runs in ([passing], [failing], [failing, passing, passing, passing]):  # green, rerun, flaky
            with self.subTest(runs=len(runs)), self.assertRaises(LN.Unusable):
                LN.revert(writer, HEADS[B.INTEGRATION], runs, None, B.CHECK)
        self.assertEqual([m for m, _, _ in gh.requests if m != "GET"], [])


class Cause(unittest.TestCase):
    def test_each_rule_by_name(self):
        for reasons, want in ((["scope_violation"], "scope_violation"), (["manifest:pkg/package.json"], "scope_violation"),
                              (["tests_red"], "test_regression"), (["zero_tests"], "test_regression"),
                              (["ratchet_increase"], "lint_regression"), (["merge_paused"], "unknown"),
                              (["tests_red", "security_path:a"], "scope_violation"), ([], "unknown")):
            with self.subTest(reasons=reasons):
                self.assertEqual(EV.cause(reasons), want)

    def test_kos_reasons_and_look_alikes_are_unknown(self):
        for reason in ("kos:patch_does_not_apply", "kos:base_file_missing", "kos:tests_red", "manifest", "x:manifest",
                       "scope_violation:x"):
            with self.subTest(reason=reason):
                self.assertEqual(EV.cause([reason]), "unknown")

    def test_every_path_reason_of_diffguard_is_named(self):
        profile = {"security_paths": ["s/"], "excluded_dirs": ["e/"]}
        paths = ["/abs", "../up", "s/x.js", "e/x.js", "CLAUDE.md", ".github/w.yml", "package.json",
                 "yarn.lock", ".gitattributes", "out/x.js"]
        found = set()
        for path in paths:
            found.update(r.split(":", 1)[0] for r in G.path_reasons(path, [G.SYMLINK, G.SUBMODULE], profile,
                                                                     {"inputs": ["s/", "e/", "a/"]}))
        self.assertEqual(found, set(G.PATH_REASONS))


class Applied(unittest.TestCase):
    def setUp(self) -> None:
        self.tree = tempfile.mkdtemp(prefix="t-land-")
        self.addCleanup(shutil.rmtree, self.tree, ignore_errors=True)
        write_tree(self.tree, {"pkg/a.js": "var a = 1;\nvar b = 2;\n", "pkg/b.js": "var c = 3;\n"})

    def applied(self, patch: bytes) -> dict:
        return LN.applied(self.tree, patch.decode())

    def test_one_file(self):
        self.assertEqual(self.applied(diff("pkg/a.js", ["var a = 1;"], ["let a = 1;"])),
                         {"reasons": [], "path": "pkg/a.js", "content": b"let a = 1;\nvar b = 2;\n",
                          "hunks": [{"old_start": 1, "old_count": 1, "new_start": 1, "new_count": 1}]})

    def test_hunks_in_diff_order(self):
        """The ranges of every hunk of the one block, as their ``@@`` headers give them (a missing count is 1; an
        insertion's ``-a,0``), in diff order: the merge row's coverage record lists exactly these."""
        write_tree(self.tree, {"pkg/c.js": "".join("l%d\n" % i for i in range(1, 11))})
        patch = (b"diff --git a/pkg/c.js b/pkg/c.js\nindex 1111111..2222222 100644\n--- a/pkg/c.js\n+++ b/pkg/c.js\n"
                 b"@@ -2 +2 @@\n-l2\n+L2\n@@ -5,0 +6,2 @@\n+n1\n+n2\n@@ -8,2 +10,1 @@\n-l8\n-l9\n+L8\n")
        got = self.applied(patch)
        self.assertEqual((got["reasons"], got["content"]),
                         ([], b"l1\nL2\nl3\nl4\nl5\nn1\nn2\nl6\nl7\nL8\nl10\n"))
        self.assertEqual(got["hunks"], [{"old_start": 2, "old_count": 1, "new_start": 2, "new_count": 1},
                                        {"old_start": 5, "old_count": 0, "new_start": 6, "new_count": 2},
                                        {"old_start": 8, "old_count": 2, "new_start": 10, "new_count": 1}])

    def test_refusals(self):
        two = diff("pkg/a.js", ["var a = 1;"], ["let a = 1;"]) + diff("pkg/b.js", ["var c = 3;"], ["let c = 3;"])
        create = (b"diff --git a/pkg/n.js b/pkg/n.js\nnew file mode 100644\nindex 0000000..1111111\n--- /dev/null\n"
                  b"+++ b/pkg/n.js\n@@ -0,0 +1 @@\n+x\n")
        os.symlink("a.js", os.path.join(self.tree, "pkg", "l.js"))
        for patch, want in ((two, "diff_not_one_file"), (diff("pkg/z.js", ["x"], ["y"]), "base_file_missing"),
                            (diff("pkg/l.js", ["var a = 1;"], ["y"]), "base_file_missing"),
                            (diff("pkg/a.js", ["var zz = 9;"], ["y"]), "patch_does_not_apply"),
                            (create, "base_file_missing"), (b"not a diff\n", "diff_unusable")):
            with self.subTest(want=want):
                got = self.applied(patch)
                self.assertEqual((got["reasons"], got["content"], got["hunks"]), ([want], None, None))


if __name__ == "__main__":
    unittest.main()
