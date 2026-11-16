"""Test 14 (asama-0/09): every artifact the stage 0 loop writes (the genesis, ``events``, ``cost`` and ``drill``
rows, the root, the ``status.md`` block) conforms to tohum/26, 26b and 26c and the seed's vector pages' row words
(29m, 29n, 29o), as ``ledger.schema`` writes them.

- the artifacts of a real activation on the in-process GitHub (genesis, cycle start, cut, ratchet base, decision,
  merge (tohum/26d) and status rows, the root, the block), a cost row from ``llm.call``'s own constructor, the drill commit, plant and
  revert rows from ``harness.revert_drill``'s payloads, a status-edited row from ``status.block``: no reason;
- each rule, broken on one of those artifacts at a time, gives its reason: a missing and an extra key, a float, a
  timestamp, a part, an unknown kind, each closed set, a reject without a cause, a revert without a cause, a merge
  decision with a reject's field or a merge row's, a merge row with a decision's field or without its SHA, a genesis payload field missing, extra, or of the wrong form, a bad hash,
  evidence lines out of order, a root row with an extra key, a hand-edited block, a file without a block, a broken
  chain;
- the sentinel end row (tohum/26f): ``{merge_sha, verdict: green|flaky, red: [], flaky}``, no other key;
- a writer that hands ``activate`` a row of the wrong shape writes nothing;
- the PASS row (seed-046's draft): its payload conforms; a missing or extra key, a negative stage, a short hash and
  an unsorted condition list do not.
"""

from __future__ import annotations

import copy
import json
import os
import sys
import unittest

REFEREE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REFEREE)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import activate  # noqa: E402
import activation_world as AW  # noqa: E402
from dispatcher import llm_call  # noqa: E402
from harness import revert_drill  # noqa: E402
from ledger import chain, cycle, events, schema  # noqa: E402
from status import block  # noqa: E402


def lines(data: bytes) -> list[dict]:
    return [json.loads(line) for line in data.decode().splitlines()]


def rechain(rows: list[dict]) -> bytes:
    return AW.chained([{k: v for k, v in r.items() if k not in ("prev_hash", "row_hash")} for r in rows])


def stored(row: dict) -> dict:
    """A row with the chain's two hash fields (their values are the chain's check, not the schema's; a float
    cannot be chained at all, so the hash fields are set by hand)."""
    return dict(row, prev_hash=chain.ZERO_HASH, row_hash="0" * 64)


class Artifacts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        w = AW.World()
        cls.out = w.run()
        cls.ledger = w.gh.read_file("brain/state", ".brain/ledger.jsonl")
        cls.roots = w.gh.read_file("brain/state", ".brain/chain/root.jsonl")
        cls.status = w.gh.read_file("brain/state", ".brain/status.md")
        cls.rows = lines(cls.ledger)

    def test_activation_artifacts_conform(self):
        self.assertEqual({r["kind"] for r in self.rows},
                         {"genesis", "cycle_start", "integration_cut", "ratchet_base", "decision", "merge", "status"})
        merges = [r for r in self.rows if r["kind"] == "merge"]
        decided = [r for r in self.rows if r["kind"] == "decision" and r["payload"]["decision"] == "merge"]
        self.assertEqual([r["payload"]["candidate"] for r in merges], [r["payload"]["candidate"] for r in decided])
        for d, m in zip(decided, merges):  # each merge row follows its decision row (ledger.events.decided)
            self.assertEqual(self.rows.index(m), self.rows.index(d) + 1)
            self.assertEqual(sorted(d["payload"]), ["candidate", "decision"])
        self.assertEqual(schema.ledger_reasons(self.ledger), [])
        self.assertEqual(schema.roots_reasons(self.roots), [])
        self.assertEqual(schema.status_reasons(self.status, self.ledger), [])

    def other_writers_rows(self) -> list[dict]:
        verdict = llm_call.classify(None, "claude-sonnet-5-5", 1000, None)
        planned = {"prompt_sha256": "1" * 64, "cap_micros": 1000}
        cost = llm_call.cost_row({"fields": {}, "text": "canary"}, planned, "claude-sonnet-5-5", verdict, 12, "c1",
                                 AW.TS, AW.SNAP)
        key = revert_drill.key({"seed": "s"}, "41", {"instances": [{"id": "i1", "cause": "test_regression"}]})
        common = {"ts": AW.TS, "derivation": "tool", "trust": "verified", "snapshot_id": AW.SNAP, "evidence_refs": []}
        drill = [dict(common, row_id="d1", part="drill", kind="commit", payload=revert_drill.commit_payload(key)),
                 dict(common, row_id="d2", part="drill", kind="plant", payload=revert_drill.plant_payload("i1", "a" * 40)),
                 dict(common, row_id="d3", part="events", kind="revert", payload=revert_drill.revert_payload("a" * 40),
                      cause=key["cause"])]
        facts = {"ts": AW.TS, "snapshot_id": AW.SNAP, "row_id": "42:status", "canary_cap_usd_micros": 1000}
        planned = block.plan(self.ledger, self.ledger, [cost] + drill, b"hand edit\n", AW.World().imports, facts)
        return planned["rows"]

    def test_other_writers_rows_conform(self):
        rows = self.other_writers_rows()
        self.assertEqual([(r["part"], r["kind"]) for r in rows], [
            ("cost", "cost"), ("drill", "commit"), ("drill", "plant"), ("events", "revert"),
            ("events", "status_edited"), ("events", "status")])
        self.assertEqual(schema.ledger_reasons(rechain(self.rows + rows)), [])

    # ---- each rule caught

    def assert_reason(self, row: dict, fragment: str):
        reasons = schema.row_reasons(stored(row))
        self.assertTrue(any(fragment in r for r in reasons), (fragment, reasons))

    def row(self, kind: str, decision: str | None = None) -> dict:
        r = copy.deepcopy(next(r for r in self.rows if r["kind"] == kind and (
            decision is None or r["payload"].get("decision") == decision)))
        return {k: v for k, v in r.items() if k not in ("prev_hash", "row_hash")}

    def test_row_rules(self):
        merge = self.row("merge")
        self.assertEqual(schema.row_reasons(stored(merge)), [])
        decided = self.row("decision", "merge")
        self.assertEqual(schema.row_reasons(stored(decided)), [])
        reject = self.row("decision", "reject")
        cases = [
            ({k: v for k, v in merge.items() if k != "trust"}, "row.trust: missing"),
            (dict(merge, extra=1), "row.extra: not a field"),
            (dict(merge, ts="2026-10-30T12:00:00.5Z"), "row.ts"),
            (dict(merge, part="ledger"), "row.part"),
            (dict(merge, kind="merged"), "unknown_row_type events/merged"),
            (dict(merge, part="drill"), "unknown_row_type drill/merge"),
            (dict(merge, derivation="guess"), "row.derivation"),
            (dict(merge, trust="sure"), "row.trust"),
            (dict(merge, cause="bad_luck"), "row.cause"),
            (dict(merge, miss_reason="other"), "row.miss_reason"),
            (dict(merge, snapshot_id=""), "row.snapshot_id"),
            (dict(merge, evidence_refs=[{"path": "a", "line_start": 3, "line_end": 2}]), "line_start after line_end"),
            (dict(merge, evidence_refs=[{"path": "a", "line_start": 0, "line_end": 2}]), "line_start"),
            (dict(merge, payload=dict(merge["payload"], pull=1.0)), "a float"),
            (dict(merge, payload=dict(merge["payload"], merge_sha="A" * 40)), "payload.merge_sha"),
            (dict(merge, payload=dict(merge["payload"], note="x")), "payload.note"),
            (dict(merge, payload=dict(merge["payload"], reasons=["x"])), "payload.reasons"),
            (dict(merge, payload=dict(merge["payload"], decision="merge")), "payload.decision: not a field"),
            (dict(merge, payload={k: v for k, v in merge["payload"].items() if k != "merge_sha"}),
             "payload.merge_sha: missing"),
            (dict(decided, payload=dict(decided["payload"], decision="revert")), "payload.decision: not one of"),
            (dict(decided, payload=dict(decided["payload"], merge_sha="a" * 40)), "payload.merge_sha: not a field"),
            (dict(decided, payload=dict(decided["payload"], pull=3)), "payload.pull: not a field"),
            ({k: v for k, v in reject.items() if k != "cause"}, "row.cause: missing"),
            (dict(reject, payload=dict(reject["payload"], reasons=[])), "payload.reasons"),
            (dict(reject, payload=dict(reject["payload"], pull=3)), "payload.pull"),
            (dict(self.row("status"), payload={"block_sha256": "0" * 64, "cycle_id": "1"}), "payload.cycle_id"),
            (dict(self.row("cycle_start"), payload={}), "payload.cycle_id: missing"),
            (dict(self.row("ratchet_base"), payload={"base_run_sha256": "0" * 64, "counts": {"eslint": -1}}),
             "payload.counts.eslint"),
            (dict(self.row("integration_cut"), payload={"branch": "main", "base_sha": "0" * 40}), "payload.branch"),
        ]
        for row, fragment in cases:
            self.assert_reason(row, fragment)
        others = {(r["part"], r["kind"]): r for r in self.other_writers_rows()}
        revert = others[("events", "revert")]
        self.assert_reason({k: v for k, v in revert.items() if k != "cause"}, "row.cause: missing")
        plant = others[("drill", "plant")]
        self.assert_reason(dict(plant, payload=dict(plant["payload"], drill="lesson")), "payload.drill")
        commit = others[("drill", "commit")]
        self.assert_reason(dict(commit, payload=dict(commit["payload"], instance_id="i1")), "payload.instance_id")
        cost = others[("cost", "cost")]
        self.assert_reason(dict(cost, payload=dict(cost["payload"], usd_micros=0.5)), "a float")
        self.assert_reason(dict(cost, payload={k: v for k, v in cost["payload"].items() if k != "usd_micros"}),
                           "payload.usd_micros: missing")

    def test_sentinel_end_row_rules(self):
        """D7's end of a green or flaky sentinel (tohum/26f): ``ledger.events.sentinel`` is exactly ``{merge_sha,
        verdict, red: [], flaky}``, without a cause; a red (which ends at its revert), a rerun, a non-empty or
        missing ``red``, a key 26f does not name and an unsorted flaky list do not conform."""
        cyc = {"cycle_id": "43", "ts": AW.TS, "snapshot_id": AW.SNAP}
        for verdict, flaky in (("green", []), ("flaky", ["a", "b"])):
            end = events.sentinel(cyc, "a" * 40, verdict, flaky)
            self.assertEqual((end["part"], end["kind"], end["row_id"], "cause" in end),
                             ("events", "sentinel", "43:sentinel", False))
            self.assertEqual(end["payload"], {"merge_sha": "a" * 40, "verdict": verdict, "red": [], "flaky": flaky})
            self.assertEqual(schema.row_reasons(stored(end)), [])
        end = events.sentinel(cyc, "a" * 40, "green", [])
        for payload, fragment in ((dict(end["payload"], verdict="red"), "payload.verdict: not one of"),
                                  (dict(end["payload"], verdict="rerun"), "payload.verdict: not one of"),
                                  (dict(end["payload"], red=["t1"]), "payload.red: not an empty list"),
                                  (dict(end["payload"], red={}), "payload.red: not an empty list"),
                                  ({k: v for k, v in end["payload"].items() if k != "red"}, "payload.red: missing"),
                                  (dict(end["payload"], sentinel_sha256="b" * 64),
                                   "payload.sentinel_sha256: not a field"),
                                  (dict(end["payload"], flaky=["b", "a"]), "payload.flaky")):
            with self.subTest(fragment=fragment):
                self.assert_reason(dict(end, payload=payload), fragment)

    def test_pass_row_rules(self):
        """The PASS row (tohum/26d, ``harness.pass_row``): its payload conforms, without a cause, with or without
        (A)'s owner exceptions (tohum/26d:45-47: a list in the order of ``anchor``, read by code point; empty, one,
        two, an anchor twice, an upper case anchor before a lower case one); a missing or extra key, a stage that is not the integer 0 (``False`` included), a verdict other than
        PASS, a hash that is not one, an empty or repeating merge list, an unsorted condition list and owner
        exceptions not of tohum/02's form (the one object of the seed before E563, an element with ``#`` in its
        anchor, a ``measured`` that is not ``false``, a missing or extra key, a list out of the anchors' order, a
        lower case anchor before an upper case one) do not."""
        cyc = {"cycle_id": "46", "ts": AW.TS, "snapshot_id": AW.SNAP}
        owner = {"anchor": "durustluk", "stage": 0, "carry_to": 1, "reason": "r", "carry_commitment": "c" * 64,
                 "measured": False}
        payload = {"stage": 0, "verdict": "PASS", "import_line_sha256": "c" * 64, "copy_genesis_row_hash": "a" * 64,
                   "copy_merge_row_hashes": ["b" * 64, "a" * 64], "conditions": ["#genesis", "#kok"],
                   "not_checked": ["#aktarim"]}
        spec, upper = dict(owner, anchor="spec"), dict(owner, anchor="Spec")
        for good in (payload, dict(payload, owner_exception=[owner, spec]), dict(payload, owner_exception=[]),
                     dict(payload, owner_exception=[spec]), dict(payload, owner_exception=[owner, owner, spec]),
                     dict(payload, owner_exception=[upper, owner])):
            row = events.row(cyc, "pass", "pass", good)
            self.assertEqual(schema.row_reasons(stored(row)), [])
        for bad, fragment in (({k: v for k, v in payload.items() if k != "stage"}, "payload.stage: missing"),
                              ({k: v for k, v in payload.items() if k != "import_line_sha256"},
                               "payload.import_line_sha256: missing"),
                              (dict(payload, extra=1), "payload.extra: not a field"),
                              (dict(payload, stage=1), "payload.stage"),
                              (dict(payload, stage=False), "payload.stage"),
                              (dict(payload, verdict="FAIL"), "payload.verdict"),
                              (dict(payload, copy_merge_row_hashes=["b" * 63]), "payload.copy_merge_row_hashes[0]"),
                              (dict(payload, copy_merge_row_hashes=[]), "payload.copy_merge_row_hashes: empty"),
                              (dict(payload, copy_merge_row_hashes=["b" * 64] * 2),
                               "payload.copy_merge_row_hashes: an element repeated"),
                              (dict(payload, conditions=["#kok", "#genesis"]), "payload.conditions"),
                              (dict(payload, owner_exception=owner), "payload.owner_exception: not a list"),
                              (dict(payload, owner_exception=[owner, dict(spec, anchor="#spec")]),
                               "payload.owner_exception[1].anchor"),
                              (dict(payload, owner_exception=[dict(owner, measured=0)]),
                               "payload.owner_exception[0].measured"),
                              (dict(payload, owner_exception=[{k: v for k, v in owner.items() if k != "reason"}]),
                               "payload.owner_exception[0].reason: missing"),
                              (dict(payload, owner_exception=[dict(owner, extra=1)]),
                               "payload.owner_exception[0].extra: not a field"),
                              (dict(payload, owner_exception=[spec, owner]),
                               "payload.owner_exception: not in the order of anchor"),
                              (dict(payload, owner_exception=[owner, spec, owner]),
                               "payload.owner_exception: not in the order of anchor"),
                              (dict(payload, owner_exception=[owner, upper]),
                               "payload.owner_exception: not in the order of anchor")):
            with self.subTest(fragment=fragment):
                self.assert_reason(dict(row, payload=bad), fragment)

    def test_merge_row_coverage_record(self):
        """asama-0/08's coverage record on the merge row (``ledger.events.hunk_covered``): one entry per hunk, in the
        hunks' order, each ``unmeasured`` with ``no_coverage_tool`` and the merge's path; an empty record for a diff
        with no hunk conforms. A merge row without the record, with an extra key in an entry, a ``covered`` other than
        ``unmeasured`` (``true`` and ``false`` included: stage 0 measures nothing), another reason or none, a
        negative or non-integer range, or an entry of another file than the row's does not."""
        cyc = {"cycle_id": "46", "ts": AW.TS, "snapshot_id": AW.SNAP}
        hunks = [{"old_start": 3, "old_count": 2, "new_start": 3, "new_count": 1},
                 {"old_start": 9, "old_count": 0, "new_start": 9, "new_count": 2}]
        merged = {"path": "src/a.js", "pull": 4, "head_sha": "b" * 40, "merge_sha": "c" * 40, "hunks": hunks}
        decision, merge = events.decided(cyc, "good", [], merged)
        self.assertEqual(merge["payload"], {"candidate": "good", "path": "src/a.js", "pull": 4, "head_sha": "b" * 40,
                                            "merge_sha": "c" * 40, "hunk_covered": [
            dict(h, path="src/a.js", covered="unmeasured", reason="no_coverage_tool") for h in hunks]})
        self.assertEqual(schema.row_reasons(stored(merge)), [])
        self.assertEqual(events.decided(cyc, "good", [], dict(merged, hunks=[]))[1]["payload"]["hunk_covered"], [])
        self.assertEqual(schema.row_reasons(stored(events.decided(cyc, "good", [], dict(merged, hunks=[]))[1])), [])
        payload, entry = merge["payload"], merge["payload"]["hunk_covered"][0]

        def with_entry(**over):
            return dict(payload, hunk_covered=[dict(entry, **over)] + payload["hunk_covered"][1:])
        for bad, fragment in (({k: v for k, v in payload.items() if k != "hunk_covered"}, "payload.hunk_covered: missing"),
                              (dict(payload, hunk_covered=None), "payload.hunk_covered: not a list"),
                              (with_entry(extra=1), "payload.hunk_covered[0].extra: not a field"),
                              (with_entry(covered=True), "payload.hunk_covered[0].covered"),
                              (with_entry(covered=False), "payload.hunk_covered[0].covered"),
                              (with_entry(covered="covered"), "payload.hunk_covered[0].covered"),
                              (with_entry(reason="no_tool"), "payload.hunk_covered[0].reason"),
                              ({**payload, "hunk_covered": [{k: v for k, v in entry.items() if k != "reason"}]},
                               "payload.hunk_covered[0].reason: missing"),
                              (with_entry(old_start=-1), "payload.hunk_covered[0].old_start"),
                              (with_entry(new_count=True), "payload.hunk_covered[0].new_count"),
                              (with_entry(path="src/b.js"), "payload.hunk_covered[0].path: not the merge's path")):
            with self.subTest(fragment=fragment):
                self.assert_reason(dict(merge, payload=bad), fragment)

    def test_copy_gate_row_rules(self):
        """The copy's genesis gate row (``harness.pass_row``, seed-048's draft): ``{conditions}``, a non-empty sorted
        list of distinct strings, no cause; a missing or extra key, an empty, unsorted or repeating list do not."""
        cyc = {"cycle_id": "46", "ts": AW.TS, "snapshot_id": AW.SNAP}
        row = events.row(cyc, "gate", "copy_gate", {"conditions": ["#genesis", "#kok"]})
        self.assertEqual(schema.row_reasons(stored(row)), [])
        for bad, fragment in (({}, "payload.conditions: missing"),
                              ({"conditions": ["#genesis"], "verdict": "open"}, "payload.verdict: not a field"),
                              ({"conditions": []}, "payload.conditions: empty"),
                              ({"conditions": ["#kok", "#genesis"]}, "payload.conditions"),
                              ({"conditions": ["#kok", "#kok"]}, "payload.conditions"),
                              ({"conditions": [1]}, "payload.conditions[0]")):
            with self.subTest(fragment=fragment):
                self.assert_reason(dict(row, payload=bad), fragment)

    def test_genesis_payload_rules(self):
        gen = self.row("genesis")
        p = gen["payload"]
        cases = [
            ({k: v for k, v in p.items() if k != "recipe_sha256"}, "payload.recipe_sha256: missing"),
            (dict(p, extra="x"), "payload.extra"),
            (dict(p, target=""), "payload.target"),
            (dict(p, base_sha="A" * 40), "payload.base_sha"),
            (dict(p, facts_sha256="0" * 63), "payload.facts_sha256"),
            (dict(p, seed_epoch=dict(p["seed_epoch"], commit="x")), "payload.seed_epoch.commit"),
            (dict(p, seed_security_last_row_hash=None), "payload.seed_security_last_row_hash"),
        ]
        for payload, fragment in cases:
            self.assert_reason(dict(gen, payload=payload), fragment)

    def test_root_status_and_chain_rules(self):
        root = lines(self.roots)[0]
        bad_root = rechain([dict(root, signer="x")])
        self.assertTrue(any("roots line 1.signer" in r for r in schema.roots_reasons(bad_root)))
        self.assertTrue(any("roots line 1.root" in r for r in schema.roots_reasons(rechain([dict(root, root="0" * 63)]))))
        edited = self.status.replace(b"Human touches: 2", b"Human touches: 9")
        self.assertNotEqual(edited, self.status)
        self.assertIn("status.md: block sha256 is not the last status row's block_sha256",
                      schema.status_reasons(edited, self.ledger))
        self.assertEqual(schema.status_reasons(b"docs above\n" + self.status + b"docs below\n", self.ledger), [])
        no_close = b"\n".join(l for l in self.status.split(b"\n") if l != block.CLOSE)
        self.assertTrue(any("CLOSE" in r for r in schema.status_reasons(no_close, self.ledger)))
        self.assertIn("status.md: has no block", schema.status_reasons(b"x\n", self.ledger))
        no_status = rechain([r for r in self.rows if r["kind"] != "status"])
        self.assertIn("status.md: the ledger has no status row", schema.status_reasons(self.status, no_status))
        broken = self.ledger.replace(b'"decision":"merge"', b'"decision":"reject"')
        self.assertTrue(schema.ledger_reasons(broken)[0].startswith("ledger: not a valid chain"))

    def test_activate_refuses_a_row_of_the_wrong_shape_before_writing(self):
        w = AW.World()
        w.decided["decisions"]["bad-test"]["reasons"] = "tests_red"  # a reject's reasons not a list of strings
        with self.assertRaises(activate.Refused) as ctx:  # the dry plan, before the cut: nothing written
            w.run()
        self.assertTrue(ctx.exception.reasons[0].startswith("state_unwritable: "), ctx.exception.reasons)
        self.assertEqual(w.writes(), [])
        with self.assertRaises(cycle.Unusable):
            cycle.plan(b"", b"", b"", b"", None,
                       [dict(self.row("merge"), payload={"decision": "merge", "candidate": "x"})],
                       AW.World().imports, {"ts": AW.TS, "snapshot_id": "s", "row_id": "1:status",
                                            "canary_cap_usd_micros": 0}, AW.World().signer, "1:root")


if __name__ == "__main__":
    unittest.main()
