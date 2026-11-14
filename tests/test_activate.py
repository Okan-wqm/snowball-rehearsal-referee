"""Test 45 (asama-0/09): activation on the in-process GitHub, no git: the genesis row, the ``brain/integration``
cut, the ratchet base, D5's answer on the ready candidates (its merge landed, each reject recorded with its reason
and cause), one orphan ``brain/state`` commit; and group ``genesis`` (tohum/29o): genesis reads the facts and hashes
them. Deciding is D5's (``loop.decide``, test_loop_yaz, its guard profile included); the genesis cycle through the
jobs is test_loop_write's ``Genesis``.

- genesis: every payload value recomputed here from the input bytes and the facts; exactly the reads of the kind,
  each once (the copy's ``main`` is not read); the toy's base is the API's ``main``, the copy's the summary's; the
  last transfer row, not a later counter row; the recipe's canonical hash; each reason alone on its own fact,
  several at once; every malformed input and unrecorded read unusable;
- activation: D5's merge is applied and merged through a pull request with the gate's check; four rejects recorded
  with their reasons and a cause, nothing written for them; no merge: only the cut and the state; the canary's
  cost row as it is; a merge whose diff does not apply to the base file, or whose base file is absent or linked,
  writes nothing; the copy cut at ``targets[].base_sha``; ``brain/state`` is an orphan holding the ledger
  (genesis, cycle_start, cut, ratchet base, decisions, cost, status), the signed root and ``status.md``, which the
  chain, the anchor, the schema and the status block read back;
- refusals before any write: a genesis reason, ``base_moved`` (the toy's main moved after D1, a copy pulled at
  another commit), a ``pulled`` that is no genesis cycle's, a base run hash that is not 64 hex, the ratchet base,
  an existing state or integration branch, the wrong repository, a missing base commit, rows the dry plan refuses
  (a secret, a cost row the schema refuses) and a policy without the canary's cap; an integration branch GitHub
  refuses to create; a hard stop after the cut names the refs written;
- ``gate.diffguard.apply``: context and removed lines must match, end of file, no fuzz;
- the command line over a recorded API (``target.write.Replay``).
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

import activate  # noqa: E402
import activation_world as AW  # noqa: E402
import yaz_world as YW  # noqa: E402
from gate import diffguard  # noqa: E402
from ledger import anchor, chain  # noqa: E402
from ledger import schema as SC  # noqa: E402
from target import write as W  # noqa: E402

sha = AW.sha


def canon_sha(value) -> str:
    return hashlib.sha256(chain.canonical(value)).hexdigest()


def rows_of(data: bytes) -> list[dict]:
    return [json.loads(line) for line in data.decode().splitlines()]


def toy_reads(w: AW.World) -> dict:
    """``{"GET <path>": body}`` of every read a toy genesis makes on the world, written out here."""
    p = "/repos/%s" % AW.REPO
    names = ["/app", "/installation/repositories", p + "/rules/branches/brain/state",
             p + "/rules/branches/brain/integration", p + "/rules/branches/main", p + "/rulesets/1",
             p + "/rulesets/2", p + "/rulesets/3", p + "/actions/workflows"]
    out = {"GET " + n: w.gh.overrides[("GET", n)][1] for n in names}
    out["GET %s/git/ref/heads/main" % p] = {"ref": "refs/heads/main", "object": {"sha": w.main, "type": "commit"}}
    return out


def fact(w: AW.World, path: str):
    return w.gh.overrides[("GET", "/repos/%s%s" % (AW.REPO, path) if not path.startswith("/app")
                           and not path.startswith("/installation") else path)][1]


class Genesis(unittest.TestCase):
    def gen(self, w: AW.World, target="toy"):
        return activate.genesis(w.gh, w.files, target)

    def test_every_field_and_hash(self):
        w = AW.World()
        got = self.gen(w)
        self.assertEqual((got["ok"], got["hard_stop"], got["reasons"]), (True, False, []))
        transfer_line = w.imports.split(b"\n")[0]
        sec = json.loads(w.security.rstrip(b"\n").split(b"\n")[-1])
        self.assertEqual(got["payload"], {
            "target": "toy", "base_sha": w.main, "referee_tree_sha256": "e" * 64, "result_sha256": "d" * 64,
            "import_line_sha256": sha(transfer_line), "seed_epoch": json.loads(w.summary)["seed_epochs"][-1],
            "policy_sha256": sha(AW.POLICY), "summary_sha256": sha(w.summary),
            "seed_security_ledger_sha256": sha(w.security), "seed_security_last_row_hash": sec["row_hash"],
            "recipe_sha256": canon_sha(json.loads(w.recipe)), "facts_sha256": canon_sha(toy_reads(w))})

    def test_exactly_the_reads_of_the_kind(self):
        w = AW.World()
        self.gen(w)
        reads = [p for m, p, _ in w.gh.requests if m == "GET"]
        self.assertEqual(sorted(reads), sorted(k[4:] for k in toy_reads(w)))
        w = AW.World(kind="copy")
        got = self.gen(w)
        reads = [p for m, p, _ in w.gh.requests if m == "GET"]
        self.assertEqual(len(reads), len(set(reads)))
        self.assertNotIn("/repos/%s/git/ref/heads/main" % AW.REPO, reads)
        self.assertNotIn("/repos/%s/actions/workflows" % AW.REPO, reads)
        self.assertIn("/repos/%s/actions/permissions" % AW.REPO, reads)
        self.assertEqual(got["payload"]["facts_sha256"],
                         canon_sha({"GET " + p: w.gh.overrides[("GET", p)][1] for p in reads}))

    def test_bases(self):
        w = AW.World()
        summary = json.loads(w.files["summary.json"])
        summary["targets"][0]["base_sha"] = "9" * 40  # the toy's summary base is not read
        w.files["summary.json"] = json.dumps(summary).encode()
        self.assertEqual(self.gen(w)["payload"]["base_sha"], w.main)
        w = AW.World(kind="copy")
        summary = json.loads(w.files["summary.json"])
        summary["targets"][0]["base_sha"] = "9" * 40
        w.files["summary.json"] = json.dumps(summary).encode()
        self.assertEqual(self.gen(w)["payload"]["base_sha"], "9" * 40)

    def test_each_change_shows_in_its_own_field(self):
        first = self.gen(AW.World())["payload"]
        self.assertEqual(self.gen(AW.World())["payload"], first)
        later = {"commit": "5" * 40, "spec_tohum_sha256": "6" * 64, "seed_sha256": "7" * 64,
                 "bootstrap_sha256": "8" * 64}

        def epoch(w):
            summary = json.loads(w.files["summary.json"])
            summary["seed_epochs"].append(later)
            w.files["summary.json"] = json.dumps(summary).encode()

        def transfer(w):
            w.files["imports.jsonl"] = AW.chained([json.loads(line) for line in w.imports.splitlines()] + [
                {"ts": "2026-10-30T11:00:00Z", "stage": 0, "referee_tree_sha256": "a" * 64,
                 "result_sha256": "b" * 64}])
        changes = {
            "policy_sha256": lambda w: w.files.update({"policy.json": b'{"p": 2}\n'}),
            "recipe_sha256": lambda w: w.files.update({"recipe.json": json.dumps(
                dict(json.loads(w.recipe), unit_id="other")).encode()}),
            "seed_security_ledger_sha256": lambda w: w.files.update({"security-ledger.jsonl": AW.chained(
                [{"row_id": "sec-1", "part": "security", "kind": "note", "payload": {}},
                 {"row_id": "sec-2", "part": "security", "kind": "note", "payload": {}}])}),
            "facts_sha256": lambda w: fact(w, "/rulesets/1").update(name="renamed"),
            "seed_epoch": epoch,
        }
        for field, change in changes.items():
            w = AW.World()
            change(w)
            got = self.gen(w)["payload"]
            self.assertNotEqual(got[field], first[field], field)
            moved = {k for k in first if got[k] != first[k]}
            self.assertEqual(moved, {field, "summary_sha256"} if field == "seed_epoch" else
                             {field, "seed_security_last_row_hash"} if field == "seed_security_ledger_sha256" else
                             {field}, field)
        w = AW.World()
        transfer(w)
        got = self.gen(w)["payload"]
        self.assertEqual((got["referee_tree_sha256"], got["result_sha256"]), ("a" * 64, "b" * 64))
        self.assertEqual(got["import_line_sha256"], sha(w.files["imports.jsonl"].rstrip(b"\n").split(b"\n")[-1]))

    def test_recipe_canonical(self):
        w = AW.World()
        w.files["recipe.json"] = json.dumps(dict(reversed(list(json.loads(w.recipe).items()))), indent=3).encode()
        self.assertEqual(self.gen(w)["payload"], self.gen(AW.World())["payload"])

    def reasons(self, change, kind="toy"):
        w = AW.World(kind=kind)
        change(w)
        got = self.gen(w)
        if got["reasons"]:
            self.assertEqual((got["ok"], got["hard_stop"], got["payload"]), (False, True, None))
        return got["reasons"]

    def test_each_reason_on_its_own_fact(self):
        def rules(w, branch):
            return fact(w, "/rules/branches/" + branch)

        def drop(branch, kind):
            return lambda w: rules(w, branch).__setitem__(slice(None), [r for r in rules(w, branch)
                                                                        if r["type"] != kind])

        def check(w, **params):
            rule = [r for r in rules(w, "brain/integration") if r["type"] == "required_status_checks"][0]
            rule["parameters"].update(params)

        def review(n):
            return lambda w: [r for r in rules(w, "main") if r["type"] == "pull_request"][0][
                "parameters"].update(required_approving_review_count=n)

        cases = [
            (lambda w: fact(w, "/installation/repositories")["repositories"].append({"full_name": "acme/other"}),
             "app_scope"),
            (lambda w: fact(w, "/installation/repositories").update(repositories=[]), "app_scope"),
            (drop("brain/state", "non_fast_forward"), "state_rules_missing"),
            (drop("brain/state", "deletion"), "state_rules_missing"),
            (drop("brain/integration", "deletion"), "integration_rules_missing"),
            (drop("brain/integration", "non_fast_forward"), "integration_rules_missing"),
            (drop("brain/integration", "pull_request"), "integration_rules_missing"),
            (drop("brain/integration", "required_status_checks"), "integration_rules_missing"),
            (lambda w: check(w, strict_required_status_checks_policy=False), "integration_check_not_writer"),
            (lambda w: check(w, strict_required_status_checks_policy=1), "integration_check_not_writer"),
            (lambda w: check(w, required_status_checks=[]), "integration_check_not_writer"),
            (lambda w: check(w, required_status_checks=[{"context": AW.GATE, "integration_id": 1}]),
             "integration_check_not_writer"),
            (lambda w: check(w, required_status_checks=[{"context": AW.GATE, "integration_id": AW.APP_ID},
                                                        {"context": "ci"}]), "integration_check_not_writer"),
            (lambda w: fact(w, "/rulesets/1").update(current_user_can_bypass="exempt"), "rules_bypassable"),
            (lambda w: fact(w, "/rulesets/2").update(current_user_can_bypass="pull_requests_only"),
             "rules_bypassable"),
            (lambda w: fact(w, "/rulesets/2").pop("current_user_can_bypass"), "rules_bypassable"),
            (lambda w: fact(w, "/rulesets/3").update(current_user_can_bypass="always"), "main_writable"),
            (review(0), "main_writable"), (review("1"), "main_writable"), (review(True), "main_writable"),
            (drop("main", "pull_request"), "main_writable"),
            (lambda w: fact(w, "/actions/workflows").update(workflows=[{"id": 1}]), "toy_workflows"),
            (lambda w: w.files.update({"security-ledger.jsonl": b""}), "security_ledger_broken"),
            (lambda w: w.files.update({"security-ledger.jsonl": w.security.replace(b"note", b"nope")}),
             "security_ledger_broken"),
        ]
        for change, reason in cases:
            self.assertEqual(self.reasons(change), [reason], reason)
        # main held by an update rule alone, with no review asked, is not writable
        self.assertEqual(self.reasons(lambda w: (drop("main", "pull_request")(w), rules(w, "main").append(
            {"type": "update", "ruleset_id": 3}))), [])
        self.assertEqual(self.reasons(review(2)), [])

    def test_copy_actions(self):
        for enabled, reasons in ((False, []), (True, ["copy_actions_enabled"]), ("false", ["copy_actions_enabled"]),
                                 (None, ["copy_actions_enabled"])):
            w = AW.World(kind="copy")
            fact(w, "/actions/permissions").update(enabled=enabled)
            self.assertEqual(self.gen(w)["reasons"], reasons, enabled)

    def test_several_reasons_at_once(self):
        def change(w):
            fact(w, "/actions/workflows").update(workflows=[{"id": 1}])
            fact(w, "/rulesets/1").update(current_user_can_bypass="exempt")
            w.files["security-ledger.jsonl"] = b"{}\n"
        self.assertEqual(self.reasons(change), ["rules_bypassable", "security_ledger_broken", "toy_workflows"])

    def test_unusable(self):
        def unrecorded(path):
            return lambda w: w.gh.overrides.pop(("GET", path))
        p = "/repos/%s" % AW.REPO
        cases = [
            unrecorded("/app"), unrecorded(p + "/rules/branches/main"), unrecorded(p + "/rulesets/2"),
            unrecorded(p + "/actions/workflows"),
            lambda w: w.gh.refs.pop("main"),
            lambda w: fact(w, "/rules/branches/main").append({"type": "update"}),
            lambda w: fact(w, "/rules/branches/main").append({"type": "update", "ruleset_id": "3"}),
            lambda w: fact(w, "/rules/branches/main").append("deletion"),
            lambda w: w.gh.overrides.update({("GET", p + "/rules/branches/main"): (200, {"rules": []})}),
            lambda w: w.gh.overrides.update({("GET", "/app"): (200, [])}),
            lambda w: w.gh.overrides.update({("GET", "/app"): (500, {})}),
            lambda w: fact(w, "/installation/repositories").update(repositories=[{"name": "x"}]),
            lambda w: fact(w, "/actions/workflows").pop("workflows"),
            lambda w: w.files.update({"summary.json": b"{"}),
            lambda w: w.files.update({"summary.json": b'{"targets": [], "seed_epochs": [{}]}'}),
            lambda w: w.files.update({"summary.json": w.summary.replace(b'"kind": "toy"', b'"kind": "fork"')}),
            lambda w: w.files.update({"summary.json": w.summary.replace(b'"seed_epochs": [{', b'"seed_epochs": [], '
                                                                                             b'"x": [{')}),
            lambda w: w.files.update({"policy.json": b"nope"}),
            lambda w: w.files.update({"recipe.json": b'{"a": 1, "a": 2}'}),
            lambda w: w.files.update({"imports.jsonl": AW.chained([{"ts": "t", "stage": 0}])}),
            lambda w: w.files.update({"imports.jsonl": b""}),
            lambda w: w.files.update({"imports.jsonl": w.imports.replace(b'"stage":0', b'"stage":1', 1)}),
            lambda w: w.files.pop("recipe.json"),
            lambda w: w.files.update({"imports.jsonl": AW.chained([{"referee_tree_sha256": "short",
                                                                     "result_sha256": "d" * 64}])}),
        ]
        for i, change in enumerate(cases):
            w = AW.World()
            change(w)
            with self.assertRaises(activate.Unusable, msg=i):
                self.gen(w)
        for target in ("other", None, 1):
            with self.assertRaises(activate.Unusable):
                self.gen(AW.World(), target)
        w = AW.World()  # a target id twice in targets[]
        summary = json.loads(w.files["summary.json"])
        summary["targets"].append(dict(summary["targets"][0]))
        w.files["summary.json"] = json.dumps(summary).encode()
        with self.assertRaises(activate.Unusable):
            self.gen(w)


class Activation(unittest.TestCase):
    def test_d5s_merge_landed_rejects_recorded_one_orphan_state(self):
        w = AW.World()
        w.cost = [YW.cost_row("cagir-41-1", w.main)]
        out = w.run()
        gh = w.gh
        # the cut, then D5's merge on top of it
        merge = gh.refs["brain/integration"]
        self.assertEqual(out["integration_sha"], w.main)
        self.assertEqual(gh.commits[merge]["parents"][0], w.main)
        self.assertEqual(gh.read_file("brain/integration", "src/a.js"), AW.SOURCE.replace(b"var x", b"let x"))
        self.assertEqual(gh.refs["main"], w.main)
        self.assertEqual(out["merge"]["candidate"], "good")
        self.assertEqual(out["merge"]["merge_sha"], merge)
        self.assertEqual(gh.pulls[out["merge"]["pull"]]["base"], "brain/integration")
        self.assertTrue(any(c["head_sha"] == out["merge"]["head_sha"] and c["conclusion"] == "success"
                            and c["name"] == AW.GATE for c in gh.checks))
        for cid in AW.EXPECTED_REJECTS:  # a reject writes nothing on the target
            self.assertNotIn("brain/c/" + cid, gh.refs)
        # brain/state: an orphan holding exactly the state files, all under .brain/ (tohum/26d "Yer"), the root's
        # bundle beside the root row among them
        state = gh.refs["brain/state"]
        self.assertEqual(state, out["state_sha"])
        self.assertEqual(gh.commits[state]["parents"], [])
        self.assertEqual(set(gh.trees[gh.commits[state]["tree"]]),
                         {".brain/ledger.jsonl", ".brain/chain/root.jsonl", ".brain/status.md",
                          ".brain/chain/%s.sigstore.json" % out["root"]})
        self.assertEqual(json.loads(gh.read_file("brain/state", ".brain/chain/%s.sigstore.json" % out["root"])),
                         dict(w.signer.answer(), fake_signed_sha256=out["root"]))
        ledger = gh.read_file("brain/state", ".brain/ledger.jsonl")
        roots = gh.read_file("brain/state", ".brain/chain/root.jsonl")
        self.assertTrue(chain.verify_bytes(ledger)["valid"])
        self.assertEqual(SC.ledger_reasons(ledger), [])
        rows = rows_of(ledger)
        self.assertEqual([(r["kind"], r["row_id"]) for r in rows], [
            ("genesis", AW.CYCLE + ":genesis"), ("cycle_start", AW.CYCLE + ":start"),
            ("integration_cut", AW.CYCLE + ":cut"), ("ratchet_base", AW.CYCLE + ":ratchet"),
            ("decision", AW.CYCLE + ":c:bad-path"), ("decision", AW.CYCLE + ":c:bad-ratchet"),
            ("decision", AW.CYCLE + ":c:bad-scope"), ("decision", AW.CYCLE + ":c:bad-test"),
            ("decision", AW.CYCLE + ":c:good"), ("merge", AW.CYCLE + ":m:good"), ("cost", "cagir-41-1"),
            ("status", AW.CYCLE + ":status")])
        self.assertEqual(rows[0]["payload"], activate.genesis(AW.World().gh, w.files, "toy")["payload"])
        self.assertEqual(rows[1]["payload"], {"cycle_id": AW.CYCLE})
        self.assertEqual(rows[2]["payload"], {"branch": "brain/integration", "base_sha": w.main})
        self.assertEqual(rows[3]["payload"], {"base_run_sha256": sha(AW.BASE_RUN), "counts": {"eslint": 2}})
        self.assertEqual({(r["ts"], r["snapshot_id"]) for r in rows if r["part"] == "events"}, {(AW.TS, w.main)})
        for r in rows[4:8]:
            cid = r["payload"]["candidate"]
            self.assertEqual(r["payload"], {"decision": "reject", "candidate": cid,
                                            "reasons": [AW.EXPECTED_REJECTS[cid][0]]})
            self.assertEqual(r["cause"], AW.EXPECTED_REJECTS[cid][1], r["row_id"])
        # the merge: its decision row, then tohum/26d's merge row with target.land's answer and asama-0/08's
        # coverage record of the good candidate's one hunk (@@ -2 +2 @@ of src/a.js), unmeasured at stage 0
        self.assertEqual(rows[8]["payload"], {"decision": "merge", "candidate": "good"})
        self.assertEqual((rows[9]["part"], rows[9]["payload"]), ("events", dict(out["merge"], hunk_covered=[
            {"path": "src/a.js", "old_start": 2, "old_count": 1, "new_start": 2, "new_count": 1,
             "covered": "unmeasured", "reason": "no_coverage_tool"}])))
        self.assertEqual(out["merge"]["path"], "src/a.js")
        self.assertNotIn("cause", rows[8])
        self.assertNotIn("cause", rows[9])
        self.assertEqual(rows[10]["payload"], w.cost[0]["payload"])  # the canary's cost row as it is
        self.assertEqual([r["row_hash"] for r in rows], out["row_hashes"])
        self.assertEqual(out["rows"], len(rows))
        # the signed root verifies as the next D1 reads it
        rekor = {"entries": {out["entry"]["uuid"]: {"hash": out["entry"]["hash"], "identity": "referee@example"}}}
        self.assertEqual(anchor.verify(ledger, roots, rekor, "referee@example"), {"valid": True, "reasons": []})
        self.assertEqual([sha(p) for p in w.signer.payloads], [out["root"]])  # signed once: the root's preimage
        self.assertEqual((out["rekor_uuid"], out["edited"]), (out["entry"]["uuid"], False))
        status = gh.read_file("brain/state", ".brain/status.md").decode()
        self.assertIn('- Cycle: "%s"\n- Last decision: "merge"\n- Base age: 0 s' % AW.CYCLE, status)
        self.assertEqual(SC.status_reasons(status.encode(), ledger), [])
        # refs written: the cut, the candidate branch, the merge into the cut, the state; never main
        self.assertEqual(sorted(set(w.wr.written)), ["refs/heads/brain/c/good", "refs/heads/brain/integration",
                                                     "refs/heads/brain/state"])

    def test_no_merge_cuts_and_writes_the_state_only(self):
        w = AW.World()
        w.decided = {"decisions": {"good": {"decision": "reject", "reasons": ["merge_paused"]}}, "merge": None}
        out = w.run()
        self.assertIsNone(out["merge"])
        self.assertEqual(w.gh.refs["brain/integration"], w.main)
        self.assertEqual(sorted(set(w.wr.written)), ["refs/heads/brain/integration", "refs/heads/brain/state"])
        rows = rows_of(w.gh.read_file("brain/state", ".brain/ledger.jsonl"))
        self.assertEqual([r["kind"] for r in rows], ["genesis", "cycle_start", "integration_cut", "ratchet_base",
                                                     "decision", "status"])
        self.assertEqual(rows[4]["payload"], {"decision": "reject", "candidate": "good", "reasons": ["merge_paused"]})
        self.assertIn('- Last decision: "reject"\n', w.gh.read_file("brain/state", ".brain/status.md").decode())

    def test_the_ratchet_base_is_the_referees_run(self):
        w = AW.World()
        w.files["base.jsonl"] = AW.run_file({"tool": "biome", "violations": [AW.violation(n) for n in (1, 2, 3, 4)]})
        w.base_run_sha256 = sha(w.files["base.jsonl"])
        w.run()
        self.assertEqual(rows_of(w.gh.read_file("brain/state", ".brain/ledger.jsonl"))[3]["payload"],
                         {"base_run_sha256": w.base_run_sha256, "counts": {"biome": 4}})

    def test_d5s_merge_that_cannot_be_written_writes_nothing(self):
        """The merge is applied to the base file in the tree before any write (``loop.write_cycle.merge_change``)."""
        w = AW.World()
        w.cand("good")["diff.patch"] = AW.diff("src/a.js", 2, ["var q = 1;"], ["let q = 1;"])
        with self.assertRaises(activate.Unusable) as ctx:
            w.run()
        self.assertIn("patch_does_not_apply", str(ctx.exception))
        self.assertEqual(w.writes(), [])
        for case in ("absent", "file_link"):  # the base file is read from the tree only, never through a link
            w = AW.World()
            w.tree = w.base_tree()
            os.remove(os.path.join(w.tree, "src", "a.js"))
            if case == "file_link":
                os.symlink(os.path.join(w.base_tree(), "src", "a.js"), os.path.join(w.tree, "src", "a.js"))
            with self.assertRaises(activate.Unusable, msg=case) as ctx:
                w.run()
            self.assertIn("base_file_missing", str(ctx.exception), case)
            self.assertEqual(w.writes(), [], case)

    def test_copy_target_cut_at_base_sha(self):
        w = AW.World(kind="copy")
        later = w.gh.seed_commit("mirror", [w.main], files={"src/a.js": b"changed\n"})
        w.gh.refs["main"] = later
        w.run()
        self.assertEqual(w.gh.commits[w.gh.refs["brain/integration"]]["parents"][0], w.main)
        self.assertEqual(w.gh.refs["main"], later)


class Refusals(unittest.TestCase):
    def assert_nothing_written(self, w: AW.World):
        self.assertEqual(w.writes(), [])

    def test_genesis_refusal_writes_nothing(self):
        w = AW.World()
        fact(w, "/actions/workflows").update(workflows=[{"id": 1}])
        with self.assertRaises(W.Refused) as ctx:
            w.run()
        self.assertEqual(ctx.exception.reasons, ["toy_workflows"])
        self.assert_nothing_written(w)

    def test_the_base_must_be_the_commit_pulled_read(self):
        """The toy's ``main`` moved after D1 read its tree: the cut, the base run and D5 would not be of one tree."""
        w = AW.World()
        moved = w.gh.seed_commit("toy-main-2", [w.main], files={"src/a.js": AW.SOURCE})
        w.gh.overrides[("GET", "/repos/%s/git/ref/heads/main" % AW.REPO)] = (
            200, {"ref": "refs/heads/main", "object": {"sha": moved, "type": "commit"}})
        with self.assertRaises(W.Refused) as ctx:
            w.run()
        self.assertEqual(ctx.exception.reasons, ["base_moved"])
        self.assert_nothing_written(w)
        w = AW.World(kind="copy")  # a copy pulled at another commit than targets[].base_sha
        w.heads["brain/integration"] = w.gh.seed_commit("other", [w.main], files={})
        with self.assertRaises(W.Refused) as ctx:
            w.run()
        self.assertEqual(ctx.exception.reasons, ["base_moved"])
        self.assert_nothing_written(w)

    def test_only_a_genesis_cycles_pulled(self):
        w = AW.World()
        w.heads["brain/state"] = "5" * 40
        with self.assertRaises(activate.Unusable):
            w.run()
        for bad in ("0" * 63, None, 7):
            w = AW.World()
            w.base_run_sha256 = bad
            with self.assertRaises(activate.Unusable):
                w.run()
        w = AW.World()
        del w.files["base.jsonl"]
        with self.assertRaises(activate.Unusable):
            w.run()
        self.assert_nothing_written(w)

    def test_ratchet_base_refusals_write_nothing(self):
        lines = AW.BASE_RUN.split(b"\n")
        for reason in ("base_run_hash_mismatch", "tool_nondeterministic"):
            w = AW.World()
            if reason == "base_run_hash_mismatch":
                w.base_run_sha256 = "0" * 64
            else:
                w.files["base.jsonl"] = b"\n".join(lines[:2] + [lines[2].replace(b'"line": 3', b'"line": 4')]) + b"\n"
                w.base_run_sha256 = sha(w.files["base.jsonl"])
            with self.assertRaises(W.Refused) as ctx:
                w.run()
            self.assertEqual(ctx.exception.reasons, [reason])
            self.assert_nothing_written(w)

    def test_already_activated_and_integration_exists(self):
        w = AW.World()
        w.gh.refs["brain/state"] = w.main
        w.gh.refs["brain/integration"] = w.main
        with self.assertRaises(W.Refused) as ctx:
            w.run()
        self.assertEqual(ctx.exception.reasons, ["already_activated", "integration_exists"])
        self.assert_nothing_written(w)
        w = AW.World()
        w.run()
        before = len(w.writes())
        with self.assertRaises(W.Refused) as ctx:
            w.run()  # a second activation over the first
        self.assertEqual(ctx.exception.reasons, ["already_activated", "integration_exists"])
        self.assertEqual(len(w.writes()), before)

    def test_wrong_repo_and_missing_base_commit(self):
        w = AW.World()
        summary = json.loads(w.files["summary.json"])
        summary["targets"][0]["repo"] = "acme/other"
        w.files["summary.json"] = json.dumps(summary).encode()
        fact(w, "/installation/repositories").update(repositories=[{"full_name": "acme/other"}])
        for path in [p for m, p in w.gh.overrides if p.startswith("/repos/")]:
            w.gh.overrides[("GET", path.replace(AW.REPO, "acme/other"))] = w.gh.overrides[("GET", path)]
        w.gh.overrides[("GET", "/repos/acme/other/git/ref/heads/main")] = (
            200, {"ref": "refs/heads/main", "object": {"sha": w.main, "type": "commit"}})
        with self.assertRaises(W.Refused) as ctx:
            w.run()
        self.assertEqual(ctx.exception.reasons, ["target_repo_mismatch"])
        self.assert_nothing_written(w)
        w = AW.World(kind="copy")
        summary = json.loads(w.files["summary.json"])
        summary["targets"][0]["base_sha"] = "7" * 40
        w.files["summary.json"] = json.dumps(summary).encode()
        w.heads["brain/integration"] = "7" * 40
        with self.assertRaises(W.ApiError):
            w.run()
        self.assert_nothing_written(w)

    def test_rows_the_ledger_refuses_write_nothing(self):
        """The dry plan runs before the cut: a secret in a row, a cost row the schema refuses."""
        w = AW.World()
        w.cost = [YW.cost_row("cagir-41-1", w.main, reason="leak ghp_" + "Q7x" * 12)]  # a token shape, not a token
        with self.assertRaises(W.Refused) as ctx:
            w.run()
        self.assertTrue(ctx.exception.reasons[0].startswith("state_unwritable: "), ctx.exception.reasons)
        self.assert_nothing_written(w)
        w = AW.World()
        row = YW.cost_row("cagir-41-1", w.main)
        del row["payload"]["usd_micros"]
        w.cost = [row]
        with self.assertRaises(W.Refused) as ctx:
            w.run()
        self.assertTrue(ctx.exception.reasons[0].startswith("state_unwritable: "), ctx.exception.reasons)
        self.assert_nothing_written(w)
        w = AW.World()
        w.pulled = lambda: AW.World.pulled(w)._replace(policy_bytes=b"{}")  # no canary_usd: no status facts
        with self.assertRaises(activate.Unusable):
            w.run()
        self.assert_nothing_written(w)

    def test_github_refuses_to_create_the_integration_branch(self):
        w = AW.World(create_denied=("brain/integration",))
        with self.assertRaises(W.ApiError):
            w.run()
        self.assertEqual(w.writes(), [("POST", "/repos/%s/git/refs" % AW.REPO)])
        self.assertEqual(sorted(w.gh.refs), ["main"])

    def test_hard_stop_after_the_cut_names_what_was_written(self):
        w = AW.World()
        w.signer = anchor.FakeSigner(False)
        with self.assertRaises(activate.HardStop) as ctx:
            w.run()
        self.assertIsInstance(ctx.exception, activate.append.HardStop)
        self.assertEqual(ctx.exception.written, ["refs/heads/brain/c/good", "refs/heads/brain/integration"])
        self.assertNotIn("brain/state", w.gh.refs)


class Apply(unittest.TestCase):
    def block(self, text: str) -> dict:
        return diffguard.parse(text)[0]

    def test_applies_at_its_own_line_only(self):
        old = b"a\nb\nc\nb\n"
        d = "diff --git a/f b/f\n--- a/f\n+++ b/f\n@@ -4 +4 @@\n-b\n+B\n"
        self.assertEqual(diffguard.apply(self.block(d), old), b"a\nb\nc\nB\n")
        with self.assertRaises(diffguard.DiffError):  # the same line elsewhere is not searched for
            diffguard.apply(self.block(d), b"a\nb\nc\nx\n")
        ctx = "diff --git a/f b/f\n--- a/f\n+++ b/f\n@@ -1,3 +1,3 @@\n a\n-b\n+B\n c\n"
        self.assertEqual(diffguard.apply(self.block(ctx), old), b"a\nB\nc\nb\n")
        with self.assertRaises(diffguard.DiffError):  # a context line that differs
            diffguard.apply(self.block(ctx), b"z\nb\nc\nb\n")

    def test_insertion_deletion_and_end_of_file(self):
        old = b"a\nb\n"
        ins = "diff --git a/f b/f\n--- a/f\n+++ b/f\n@@ -1,0 +2 @@\n+x\n"
        self.assertEqual(diffguard.apply(self.block(ins), old), b"a\nx\nb\n")
        dele = "diff --git a/f b/f\n--- a/f\n+++ b/f\n@@ -2 +1,0 @@\n-b\n"
        self.assertEqual(diffguard.apply(self.block(dele), old), b"a\n")
        no_eol = "diff --git a/f b/f\n--- a/f\n+++ b/f\n@@ -2 +2 @@\n-b\n+b\n\\ No newline at end of file\n"
        self.assertEqual(diffguard.apply(self.block(no_eol), old), b"a\nb")
        with self.assertRaises(diffguard.DiffError):  # the base has no newline, the diff says it has
            diffguard.apply(self.block("diff --git a/f b/f\n--- a/f\n+++ b/f\n@@ -2 +2 @@\n-b\n+c\n"), b"a\nb")
        with self.assertRaises(diffguard.DiffError):  # beyond the end of the file
            diffguard.apply(self.block("diff --git a/f b/f\n--- a/f\n+++ b/f\n@@ -5 +5 @@\n-b\n+c\n"), old)
        with self.assertRaises(diffguard.DiffError):  # an insertion after a line the file does not have
            diffguard.apply(self.block("diff --git a/f b/f\n--- a/f\n+++ b/f\n@@ -5,0 +6 @@\n+x\n"), old)
        with self.assertRaises(diffguard.DiffError):  # a line without a newline that would not be the last
            diffguard.apply(self.block("diff --git a/f b/f\n--- a/f\n+++ b/f\n@@ -1 +1 @@\n-a\n+a\n"
                                       "\\ No newline at end of file\n"), old)

    def test_only_an_in_place_text_change(self):
        for d in ("diff --git a/f b/g\nsimilarity index 90%\nrename from f\nrename to g\n",
                  "diff --git a/f b/f\nnew file mode 100644\n--- /dev/null\n+++ b/f\n@@ -0,0 +1 @@\n+x\n",
                  "diff --git a/f b/f\nold mode 100644\nnew mode 100755\n"):
            with self.assertRaises(diffguard.DiffError, msg=d):
                diffguard.apply(self.block(d), b"x\n")

    def test_bytes_that_are_not_utf8_are_kept(self):
        old = b"\xff\nb\n"
        d = "diff --git a/f b/f\n--- a/f\n+++ b/f\n@@ -2 +2 @@\n-b\n+c\n"
        self.assertEqual(diffguard.apply(self.block(d), old), b"\xff\nc\n")


class CommandLine(unittest.TestCase):
    def run_cli(self, w: AW.World, target="toy", args=None, api=None):
        with tempfile.TemporaryDirectory() as tmp:
            paths = []
            record = api if api is not None else dict(toy_reads(w))
            for name, data in [("api.json", json.dumps(record).encode())] + [
                    (n, w.files[n]) for n in activate.GENESIS_FILES]:
                paths.append(os.path.join(tmp, name))
                with open(paths[-1], "wb") as fh:
                    fh.write(data)
            proc = subprocess.run([sys.executable, "-m", "activate"] + (args or ["genesis"] + paths),
                                  input=json.dumps({"target": target}).encode(), cwd=REFEREE, capture_output=True,
                                  timeout=60)
        return proc.returncode, json.loads(proc.stdout.decode().splitlines()[-1]), proc.stderr.decode()

    def test_planned_and_hard_stop(self):
        w = AW.World()
        code, out, _ = self.run_cli(w)
        self.assertEqual((code, out), (0, self_gen(w)))
        api = toy_reads(w)
        api["GET /repos/%s/actions/workflows" % AW.REPO] = {"workflows": [{"id": 1}]}
        code, out, _ = self.run_cli(w, api=api)
        self.assertEqual((code, out), (1, {"ok": False, "hard_stop": True, "reasons": ["toy_workflows"],
                                           "payload": None}))

    def test_unusable(self):
        w = AW.World()
        api = toy_reads(w)
        del api["GET /app"]
        for kwargs in ({"api": api}, {"target": "other"}, {"args": ["genesis"]}, {"args": ["genesis"] + ["/x"] * 6},
                       {"api": []}):
            code, out, err = self.run_cli(w, **kwargs)
            self.assertEqual((code, out), (2, {"ok": False, "hard_stop": True, "payload": None}), kwargs)
            self.assertTrue(err.startswith("unusable input"), err)


def self_gen(w: AW.World) -> dict:
    return activate.genesis(AW.World().gh, w.files, "toy")


if __name__ == "__main__":
    unittest.main()
