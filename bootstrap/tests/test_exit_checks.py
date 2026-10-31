"""The Stage 0 exit conditions E162 kept closed because the seed had no check for them (`asama-0/10`, (A)).

Four are checked now, on the brain archive `pull` already holds, never by running the Founder's code
(`29b`; the draft `29e` "Tohum denetimleri"): #kurucu-defteri (E107, E280), #is-akisi (test 46's `wiring` rules,
E100, E281-E283; its control sub-rule since E282, `test_exit_decisions`), #agac (E130, E131, E285) and #genellik
(E284). #spec (E286) and #durustluk (E79, E287) stay unchecked: each keeps the exit closed by name and is never
counted against the Founder. The trailing comment on a test names the mutants it kills (`local/mutate.py`).
"""

import hashlib
import io
import json
import tarfile
import tempfile
import unicodedata
import unittest
from pathlib import Path
from unittest import mock

from snowball_bootstrap import classify, config, decide as decide_module, exitchecks, importer, ledgercheck, wiring
from snowball_bootstrap.config import ConfigError, load_summary
from snowball_bootstrap.decide import decide
from snowball_bootstrap.treehash import TreeError, tree_hash

import test_flow
from helpers import LOOP_YML, commit, ledger_bytes, ledger_rows, make_repo

A, B = "a" * 40, "b" * 40
CODE_JOBS = {"getir": "success", "kos": "success", "cagir": "success", "yeniden": "skipped"}
EXIT_JOBS = {"getir": "success", "kos": "success"}
LOOP = "referee/.github/workflows/loop.yml"
TOY = "tests/fixtures/toy-repo/app.py"
INVALID, ACCEPTED = "founder_ledger_invalid", "founder_ledger_accepted_invalid"


def tar_of(files):
    """A git-archive-like tarball of ``{path: bytes or str}``."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:", format=tarfile.PAX_FORMAT) as tar:
        for name, content in files.items():
            data = content if isinstance(content, bytes) else content.encode("utf-8")
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


# ---------------------------------------------------------------- #kurucu-defteri


class FounderLedgerRules(unittest.TestCase):
    """`asama-0/10` #kurucu-defteri, `asama-0/09` test 30, `tohum/26`: chained with the seed's canonical code, only
    appended relative to the last accepted commit, the founder `kind` set. At the exit the whole file is checked; a
    row the referee accepted before it checked rows is reported apart, as nothing the Founder can append fixes it."""

    def check(self, head, base=None, whole=True):
        return ledgercheck.check(head, base, whole=whole)

    def test_a_chained_ledger_that_only_grew_passes(self):
        rows = ledger_rows(5)
        for whole in (True, False):
            self.assertEqual(self.check(ledger_bytes(rows), ledger_bytes(rows[:3]), whole), [], whole)
            self.assertEqual(self.check(ledger_bytes(rows), ledger_bytes(rows), whole), [], whole)
        self.assertEqual(self.check(ledger_bytes(rows), None), [])

    def test_a_payload_edited_without_rehashing_is_refused(self):  # ledger_row_hash_unchecked
        rows = ledger_rows(3)
        rows[2] = dict(rows[2], payload={"summary": "edited afterwards", "refs": []})  # V3 of `29a`
        self.assertEqual(self.check(ledger_bytes(rows)), [f"{INVALID}:row_hash:L3"])

    def test_a_spliced_row_with_a_valid_hash_of_its_own_is_refused(self):  # ledger_prev_hash_unchecked
        rows = ledger_rows(2) + ledger_rows(1, start=3, prev="1" * 64)
        self.assertEqual(self.check(ledger_bytes(rows)), [f"{INVALID}:prev_hash:L3"])

    def test_the_first_row_links_to_sixty_four_zeros(self):  # ledger_first_link_unchecked
        self.assertEqual(self.check(ledger_bytes(ledger_rows(2, prev="1" * 64))), [f"{INVALID}:prev_hash:L1"])

    def test_a_ledger_rechained_after_an_accepted_row_changed_is_refused(self):  # ledger_prefix_unchecked
        accepted = ledger_rows(3)
        rechained = ledger_rows(4, edits={1: {"payload": {"summary": "rewritten", "refs": []}}})
        self.assertEqual(self.check(ledger_bytes(rechained), None), [])  # the chain alone cannot see it
        for whole in (True, False):
            self.assertEqual(self.check(ledger_bytes(rechained), ledger_bytes(accepted), whole),
                             [f"{INVALID}:rewritten:L2"], whole)

    def test_accepted_rows_are_compared_as_bytes_not_as_canonical_json(self):  # ledger_canonical_compare
        rows = ledger_rows(3)
        reordered = json.dumps(dict(reversed(list(rows[0].items()))), separators=(",", ":")).encode() + b"\n"
        head = reordered + ledger_bytes(rows[1:])
        self.assertEqual(self.check(head, None), [])  # the same row, its keys in another order
        self.assertEqual(self.check(head, ledger_bytes(rows[:2]), whole=False), [f"{INVALID}:rewritten:L1"])

    def test_a_deleted_or_truncated_ledger_is_refused(self):  # ledger_deletion_passes
        rows = ledger_rows(3)
        self.assertEqual(self.check(None, ledger_bytes(rows), whole=False), [f"{INVALID}:deleted"])
        self.assertEqual(self.check(None, ledger_bytes(rows)), [f"{INVALID}:deleted"])
        self.assertEqual(self.check(ledger_bytes(rows[:2]), ledger_bytes(rows), whole=False),
                         [f"{INVALID}:truncated:L3"])
        self.assertEqual(self.check(ledger_bytes(rows)[:-5], ledger_bytes(rows), whole=False),
                         [f"{INVALID}:truncated:L3"])

    def test_every_row_ends_with_a_newline(self):  # ledger_unterminated_passes
        rows = ledger_rows(2)
        self.assertEqual(self.check(ledger_bytes(rows)[:-1]), [f"{INVALID}:unterminated:L2"])
        self.assertEqual(self.check(ledger_bytes(rows)[:-1], ledger_bytes(rows[:1]), whole=False),
                         [f"{INVALID}:unterminated:L2"])
        # A partial last line the referee accepted may be closed by its newline and nothing else.
        partial = ledger_bytes(rows)[:-1]
        self.assertEqual(self.check(partial + b"\n", partial, whole=False), [])
        tail = ledger_bytes(ledger_rows(1, start=3, prev=rows[1]["row_hash"]))
        self.assertEqual(self.check(partial + b" " + b"\n" + tail, partial, whole=False), [f"{INVALID}:rewritten:L2"])

    def test_an_accepted_partial_line_is_an_accepted_row(self):  # ledger_accepted_partial_line_counted_new
        """A bad row the referee accepted without its newline is still the referee's acceptance: a push closing it
        with its newline is not charged for it, and the exit reports it apart."""
        rows = ledger_rows(3, edits={1: {"kind": "learning"}})
        partial = ledger_bytes(rows[:2])[:-1]
        head = partial + b"\n" + ledger_bytes(rows[2:])
        self.assertEqual(self.check(head, partial, whole=False), [])
        self.assertEqual(self.check(head, partial), [f"{ACCEPTED}:kind:L2"])

    def test_values_canonical_json_cannot_hold_are_refused(self):  # ledger_noncanonical_passes
        good = ledger_rows(1)[0]
        for value in ("1.5", "NaN", "Infinity", str(2 ** 60)):
            text = canonical_text(dict(good, payload={"summary": "x", "refs": []})).replace('"refs":[]', f'"refs":[{value}]')
            self.assertEqual(self.check(text.encode() + b"\n"), [f"{INVALID}:noncanonical:L1"], value)
        lone = canonical_text(good).replace('"row 1"', '"\\ud800"')
        self.assertEqual(self.check(lone.encode() + b"\n"), [f"{INVALID}:noncanonical:L1"])

    def test_a_duplicate_key_cannot_hide_a_kind_outside_the_set(self):  # ledger_duplicate_keys_last_wins
        row = ledger_rows(1)[0]
        text = canonical_text(row).replace('"kind":"decision"', '"kind":"learning","kind":"decision"')
        self.assertEqual(self.check(text.encode() + b"\n"), [f"{INVALID}:duplicate_key:L1"])

    def test_deep_nesting_is_the_rows_failure_not_a_crash(self):  # ledger_depth_unbounded
        deep = '{"payload":' + "[" * 2000 + "]" * 2000 + "}"
        self.assertEqual(self.check(deep.encode() + b"\n"), [f"{INVALID}:too_deep:L1"])
        shallow_but_over = '{"payload":' + "[" * 100 + "]" * 100 + "}"
        self.assertEqual(self.check(shallow_but_over.encode() + b"\n"), [f"{INVALID}:too_deep:L1"])

    def test_nesting_is_capped_at_exactly_max_depth(self):  # ledger_depth_bound_65
        def nested(levels):  # the row is level 1, its payload level 2, `refs` level 3, each list inside one more
            inner: list = []
            for _ in range(levels - 3):
                inner = [inner]
            return ledger_bytes(ledger_rows(1, edits={0: {"payload": {"refs": inner}}}))
        self.assertEqual(ledgercheck.MAX_DEPTH, 64)
        self.assertEqual(self.check(nested(ledgercheck.MAX_DEPTH)), [])
        self.assertEqual(self.check(nested(ledgercheck.MAX_DEPTH + 1)), [f"{INVALID}:too_deep:L1"])

    def test_the_kind_set_and_the_part_are_test_30s(self):  # ledger_kind_unchecked ledger_part_unchecked
        for kind in ledgercheck.FOUNDER_KINDS:
            self.assertEqual(self.check(ledger_bytes(ledger_rows(2, edits={1: {"kind": kind}}))), [], kind)
        self.assertEqual(self.check(ledger_bytes(ledger_rows(2, edits={1: {"kind": "learning"}}))),
                         [f"{INVALID}:kind:L2"])
        self.assertEqual(self.check(ledger_bytes(ledger_rows(2, edits={1: {"part": "events"}}))),
                         [f"{INVALID}:part:L2"])
        self.assertEqual(set(ledgercheck.FOUNDER_KINDS),
                         {"session_start", "decision", "build", "blocked", "seed_issue", "cost", "session_end"})

    def test_bytes_that_are_not_rows_are_refused(self):
        for raw, rule in ((b"\xff\xfe\n", "not_utf8"), (b"not json\n", "not_json"), (b"[1, 2]\n", "not_json"),
                          (b"\n", "not_json")):
            self.assertEqual(self.check(raw), [f"{INVALID}:{rule}:L1"], raw)
        row = ledger_rows(1)[0]
        for gone in ("prev_hash", "row_hash"):
            text = json.dumps({k: v for k, v in row.items() if k != gone})
            self.assertEqual(self.check(text.encode() + b"\n"), [f"{INVALID}:{gone}:L1"], gone)

    def test_an_exit_needs_a_ledger_and_a_push_without_one_is_fine(self):  # ledger_missing_at_exit_passes
        self.assertEqual(self.check(None, None), [f"{INVALID}:missing"])
        self.assertEqual(self.check(b"", None), [f"{INVALID}:missing"])
        self.assertEqual(self.check(None, None, whole=False), [])

    def test_a_row_the_referee_already_accepted_is_reported_apart(self):  # ledger_accepted_rows_skipped_at_exit
        rows = ledger_rows(4, edits={2: {"kind": "learning"}})
        base = ledger_bytes(rows[:3])
        self.assertEqual(self.check(ledger_bytes(rows), base), [f"{ACCEPTED}:kind:L3"])
        self.assertEqual(self.check(ledger_bytes(rows), base, whole=False), [])  # a push checks what it adds
        worse = ledger_rows(5, edits={2: {"kind": "learning"}, 4: {"kind": "lesson"}})
        self.assertEqual(self.check(ledger_bytes(worse), base), [f"{ACCEPTED}:kind:L3", f"{INVALID}:kind:L5"])
        self.assertEqual(self.check(ledger_bytes(worse), base, whole=False), [f"{INVALID}:kind:L5"])

    def test_a_push_checks_the_rows_after_the_accepted_ones(self):  # ledger_new_rows_unchecked_on_push
        rows = ledger_rows(3)
        bad = rows + ledger_rows(1, start=4, prev="2" * 64)
        self.assertEqual(self.check(ledger_bytes(bad), ledger_bytes(rows), whole=False), [f"{INVALID}:prev_hash:L4"])


def canonical_text(row):
    return json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


class ExitFlow(unittest.TestCase):
    """Through `pull`: the checks run on every judged push or at the exit, from the archive in hand."""

    setUp = test_flow.Flow.setUp
    tearDown = test_flow.Flow.tearDown
    pull = test_flow.Flow.pull
    finish = test_flow.Flow.finish
    rival_ok = test_flow.Flow.rival_ok
    green_run = test_flow.Flow.green_run
    freeze_stage0 = test_flow.Flow.freeze_stage0

    def accept(self, files, done=(1,)):
        files = dict(files, **{"snowball-tests.json": test_flow.all_tests_manifest(done)})
        commit(self.brain, files, "code")
        meta = self.pull()
        result = self.finish(meta, run=self.green_run(meta), rival=self.rival_ok(), jobs=CODE_JOBS)
        self.assertEqual(result["verdict"], "accepted", result["reasons"])
        return meta["head"]

    def ask_exit(self, extra=None):
        frozen = self.state["frozen_specs"]["spec/asama-0"]
        request = json.dumps({"stage": 0, "sha": self.state["last_accepted_sha"], "spec_sha256": frozen})
        commit(self.brain, dict({"exit-request.json": request}, **(extra or {})), "exit request")
        meta = self.pull()
        self.assertEqual(meta["kind"], "exit", meta["pre_reasons"])
        return meta

    def write_summary(self, **extra):
        path = self.referee / "setup" / "summary.json"
        path.write_text(json.dumps(dict(json.loads(path.read_text()), **extra)))


class FounderLedgerOnEveryPush(ExitFlow):
    def test_a_code_push_with_a_bad_new_row_is_refused_before_the_tests_and_the_rival(self):  # ledger_checked_only_at_exit
        self.freeze_stage0()
        rows = ledger_rows(2)
        self.accept({"referee/ledger/chain.py": "x = 1\n", "founder-ledger.jsonl": ledger_bytes(rows)})
        grown = rows + ledger_rows(1, start=3, prev=rows[-1]["row_hash"], edits={0: {"kind": "learning"}})
        commit(self.brain, {"referee/ledger/chain.py": "x = 2\n", "founder-ledger.jsonl": ledger_bytes(grown)}, "bad")
        meta = self.pull()
        self.assertEqual((meta["kind"], meta["pre_reasons"]), ("code", [f"{INVALID}:kind:L3"]))
        self.assertEqual((meta["run_tests"], meta["run_rival"]), (False, False))
        result = self.finish(meta)
        self.assertEqual(result["state"]["reject_streaks"], {f"{INVALID}:kind:L3:": 1})  # the Founder's to fix
        good = rows + ledger_rows(1, start=3, prev=rows[-1]["row_hash"])
        commit(self.brain, {"founder-ledger.jsonl": ledger_bytes(good)}, "fixed")
        self.assertEqual(self.pull()["pre_reasons"], [])

    def test_a_spec_push_checks_every_row_since_the_last_accepted_commit(self):
        rows = ledger_rows(2)
        commit(self.brain, {"founder-ledger.jsonl": ledger_bytes(rows)}, "rows alone: nothing to judge")
        self.assertEqual(self.pull()["kind"], "none")
        commit(self.brain, {"spec/asama-0/00-ozet.md": "# stage 0 v2\n",
                            "founder-ledger.jsonl": ledger_bytes(ledger_rows(2, edits={0: {"kind": "lesson"}}))},
               "spec")
        meta = self.pull()  # the rows were never accepted: the push may rewrite them, and they are all checked
        self.assertEqual((meta["kind"], meta["pre_reasons"], meta["run_rival"]), ("spec", [f"{INVALID}:kind:L1"], False))

    def test_a_ledger_nested_past_the_parser_is_a_rejection_not_a_pull_error(self):
        deep = ('{"payload":' + "[" * 100000 + "]" * 100000 + "}\n").encode()
        commit(self.brain, {"spec/asama-0/00-ozet.md": "# stage 0 v2\n", "founder-ledger.jsonl": deep}, "deep")
        self.assertEqual(self.pull()["pre_reasons"], [f"{INVALID}:too_deep:L1"])

    def test_an_exit_without_a_ledger_is_refused_and_counted(self):  # exit_ledger_check_not_wired
        self.freeze_stage0()
        self.accept({"referee/ledger/chain.py": "x = 1\n"})
        meta = self.ask_exit()
        self.assertEqual(meta["exit_checks"]["kurucu-defteri"]["status"], "failed")
        self.assertEqual(meta["pre_reasons"], [])  # the tests still run: one request hears all that is missing
        result = self.finish(meta, run=self.green_run(meta), jobs=EXIT_JOBS)
        self.assertIn(("exit_condition", f"{INVALID}:missing"), [(r["kind"], r["ref"]) for r in result["reasons"]])
        self.assertEqual(result["state"]["reject_streaks"].get(f"exit_condition:{INVALID}:missing"), 1)

    def test_at_the_exit_an_accepted_row_with_broken_bytes_closes_the_exit_but_is_never_the_founders(self):
        """A row the referee accepted before it checked rows: its broken hash is tamper evidence for the operator
        (`13`), which nothing the Founder may append closes (E280; a broken meaning rule is closable, below in
        `test_exit_decisions`)."""
        self.freeze_stage0()
        self.accept({"referee/ledger/chain.py": "x = 1\n"})
        good = ledger_rows(3)
        tampered = ledger_bytes([good[0], dict(good[1], payload={"summary": "edited", "refs": []}), good[2]])
        self.state["last_accepted_sha"] = commit(self.brain, {"founder-ledger.jsonl": tampered},
                                                 "accepted under the seed that did not check rows")
        meta = self.ask_exit({"founder-ledger.jsonl": tampered + ledger_bytes(ledger_rows(1, start=4,
                                                                                          prev=good[-1]["row_hash"]))})
        self.assertEqual(meta["exit_checks"]["kurucu-defteri"]["reasons"], [f"{ACCEPTED}:row_hash:L2"])
        result = self.finish(meta, run=self.green_run(meta), jobs=EXIT_JOBS)
        self.assertIn(f"{ACCEPTED}:row_hash:L2", result["exit"]["missing"])
        self.assertNotIn(f"exit_condition:{ACCEPTED}:row_hash:L2", result["state"]["reject_streaks"])


class ExitDecision(unittest.TestCase):
    """`decide` maps pull's results: absent or undecided is `not_checked` (never a pass), failed is the Founder's,
    and what the seed cannot check stays named with its open register row."""

    def state(self, **kw):
        s = {"schema": "snowball-bootstrap-state/3", "origin": "artifact", "last_accepted_sha": A,
             "last_evaluated_sha": None, "frozen_specs": {}, "month": "2026-10", "month_spend_usd_micros": 0,
             "stage_spend_usd_micros": 0, "runs": 1, "reject_streaks": {}, "repeat_events": 0, "outage_sha": None,
             "outage_count": 0, "outage_since": None, "outage_stop": None, "rival_side_streak": 0,
             "open_refutations": [], "open_claims": [], "pending_rival": None, "rejected_exit_request": None,
             "rival_artifacts": [{"sha": s_, "outcome": "survived"} for s_ in (A, "1" * 40, "2" * 40)]}
        s.update(kw)
        return s

    def meta(self, state, checks=None, **kw):
        m = {"head": B, "base": A, "kind": "exit", "state": state, "changed": ["exit-request.json"], "pre_reasons": [],
             "evaluate": True, "run_tests": True, "run_rival": False,
             "manifest": {"tests": [], "done_mf": list(range(1, 19)), "lockfiles": []},
             "exit_request": {"stage": 0, "sha": A, "spec_sha256": "e" * 64}, "referee_tree_sha256": "f" * 64,
             "toy_tree_sha256": "d" * 64, "spec_dir_hashes": {}}
        if checks is not None:
            m["exit_checks"] = checks
        m.update(kw)
        return m

    def run_(self, meta):
        return decide(meta, {"controls": [], "tests": [{"id": "T13", "cmd_sha256": "c", "ok": True}], "vectors": [],
                             "licenses": [], "green": True}, None, None, EXIT_JOBS, 2, 3)

    @staticmethod
    def ok():
        return {anchor: {"status": "ok", "reasons": [], "why": ""} for anchor in decide_module.EXIT_CHECKS}

    def test_the_anchors_are_split_between_the_checks_and_what_stays_unchecked(self):
        self.assertEqual(decide_module.EXIT_CHECKS, ("kurucu-defteri", "is-akisi", "agac", "genellik"))
        self.assertEqual(set(decide_module.EXIT_NOT_CHECKED), {"spec", "durustluk"})  # #is-akisi whole since E282

    def test_no_result_from_pull_is_never_a_pass(self):  # exit_check_absent_passes
        res = self.run_(self.meta(self.state()))
        named = ["kurucu-defteri", "is-akisi", "agac", "genellik", "spec", "durustluk"]
        self.assertEqual(res["exit"]["missing"], ["not_checked:" + a for a in named])
        for anchor in decide_module.EXIT_CHECKS:
            checks = self.ok()
            del checks[anchor]
            res = self.run_(self.meta(self.state(), checks))
            self.assertIn("not_checked:" + anchor, res["exit"]["missing"], anchor)
            for broken in ({"status": "passed"}, {"status": "failed", "reasons": []}, "ok", None,
                           {"status": "ok", "reasons": ["x"], "why": ""}):
                checks[anchor] = broken
                res = self.run_(self.meta(self.state(), checks))
                self.assertIn("not_checked:" + anchor, res["exit"]["missing"], (anchor, broken))
        # #agac passed but pull gave no toy subtree hash for the signed result: no result, not a pass.
        res = self.run_(self.meta(self.state(), self.ok(), toy_tree_sha256=None))  # agac_ok_without_the_toy_hash
        self.assertIn("not_checked:agac", res["exit"]["missing"])

    def test_with_every_check_passing_only_what_the_seed_cannot_check_is_left(self):  # unchecked_exit_conditions_pass
        res = self.run_(self.meta(self.state(), self.ok()))
        self.assertEqual(res["exit"]["missing"], ["not_checked:spec", "not_checked:durustluk"])
        details = {r["ref"]: r.get("detail", "") for r in res["reasons"]}
        self.assertIn("E286", details["not_checked:spec"])
        self.assertIn("E287", details["not_checked:durustluk"])
        self.assertFalse(res["exit"]["transferable"])
        with mock.patch.object(decide_module, "EXIT_NOT_CHECKED", {}):
            res = self.run_(self.meta(self.state(), self.ok()))
        self.assertEqual((res["verdict"], res["exit"]["transferable"]), ("accepted", True))
        self.assertEqual(res["exit"]["toy_tree_sha256"], "d" * 64)  # exit_toy_hash_not_signed
        self.assertEqual(res["exit"]["checks"], self.ok())

    def test_an_undecided_check_says_why_and_is_not_the_founders(self):
        checks = dict(self.ok(), genellik={"status": "undecided", "reasons": [], "why": "no targets[] (E284)"})
        state = self.state()
        for _ in range(3):
            res = self.run_(self.meta(state, checks))
            state = res["state"]
        reason = next(r for r in res["reasons"] if r["ref"] == "not_checked:genellik")
        self.assertIn("E284", reason["detail"])
        self.assertEqual((res["state"]["reject_streaks"], res["learning"]["not_learning"]), ({}, []))

    def test_a_failed_check_is_the_founders_but_an_accepted_rows_broken_bytes_are_not(self):
        # integrity_break_counted meaning_break_not_the_founders
        """E280: an accepted row whose bytes or chain are broken is tamper evidence nothing appended closes; one that
        breaks a meaning rule (`kind`) is closed by a superseding row, so it is the Founder's."""
        accepted = {"status": "failed", "reasons": [f"{ACCEPTED}:row_hash:L7"], "why": ""}
        state = self.state()
        for _ in range(3):
            res = self.run_(self.meta(state, dict(self.ok(), **{"kurucu-defteri": accepted})))
            state = res["state"]
        self.assertIn(f"{ACCEPTED}:row_hash:L7", res["exit"]["missing"])
        self.assertEqual((res["verdict"], res["state"]["reject_streaks"], res["learning"]["not_learning"]),
                         ("rejected", {}, []))
        for found in (f"{INVALID}:kind:L9", f"{ACCEPTED}:kind:L7"):
            new = {"status": "failed", "reasons": [found], "why": ""}
            state = self.state()
            for _ in range(3):
                res = self.run_(self.meta(state, dict(self.ok(), **{"kurucu-defteri": new})))
                state = res["state"]
            self.assertEqual(res["learning"]["not_learning"], [f"exit_condition:{found}"], found)


# ---------------------------------------------------------------- #is-akisi


class WorkflowSubset(unittest.TestCase):
    """The seed's restricted YAML subset (E281): what it reads, it reads as GitHub does; anything else is
    `workflow_unparseable`, never a guess."""

    def test_the_seeds_own_fixture_reads_as_written(self):
        doc = wiring.parse(LOOP_YML.encode())
        self.assertEqual(doc["permissions"], {})
        self.assertEqual(doc["on"], {"schedule": [{"cron": "7 * * * *"}], "workflow_dispatch": {}})
        self.assertEqual(list(doc["jobs"]), ["cek", "getir", "kos", "cagir", "yaz"])
        self.assertEqual(doc["jobs"]["cek"]["steps"][2]["run"],
                         'set -eu\npython3 -m loop pull --out "$RUNNER_TEMP/pulled"\n')
        self.assertEqual(doc["jobs"]["yaz"]["steps"][1]["env"]["WRITER_KEY"], "${{ secrets.WRITER_APP_PRIVATE_KEY }}")
        self.assertEqual(doc["jobs"]["kos"]["needs"], ["getir"])
        self.assertEqual(doc["jobs"]["cek"]["steps"][1]["with"], {"persist-credentials": "false"})
        self.assertEqual(wiring.parse(b"a: 'it''s'\nb: \"q\\\"\\\\\"\nc:\n"), {"a": "it's", "b": 'q"\\', "c": None})

    def test_forms_outside_the_subset_are_refused(self):  # subset_accepts_aliases subset_duplicate_keys_last_wins
        cases = {
            "anchor": "name: &a loop\n", "alias": "name: *a\n", "tag": "name: !!str loop\n",
            "merge key": "a:\n  <<: *b\n", "duplicate key": "name: loop\nname: again\n", "tab": "name:\tloop\n",
            "carriage return": "name: loop\r\n", "folded": "run: >\n  echo\n", "literal strip": "run: |-\n  echo\n",
            "document marker": "---\nname: loop\n", "document end": "name: loop\n...\n", "directive": "%YAML 1.2\nname: x\n",
            "comment after a plain scalar": "name: loop # the loop\n", "flow sequence": "needs: [cek]\n",
            "flow mapping": "with: {a: b}\n", "multi-line plain": "name: loop\n  continued\n",
            "byte order mark": "\ufeffname: loop\n", "next line": "name: lo\u0085op\n", "line separator": "name: lo\u2028op\n",
            "escape": 'name: "a\\nb"\n', "unterminated quote": "name: 'loop\n", "text after a quote": "name: 'a' b\n",
            "indentless sequence": "steps:\n- run: x\n", "key without a space": "name:loop\n", "question key": "? a\n",
            "nesting that does not nest": "a:\n    b: 1\n  c: 2\n", "quoted key": "'on': push\n",
            "empty literal": "run: |\nname: x\n", "plain mapping indicator": "name: a: b\n", "empty": "",
            "control character": "name: lo\x07op\n", "delete": "name: lo\x7fop\n",
        }
        for name, text in cases.items():
            with self.subTest(name):
                with self.assertRaises(wiring.Unparseable):
                    wiring.parse(text.encode("utf-8"))
        with self.assertRaises(wiring.Unparseable):
            wiring.parse(b"name: \xff\n")
        with self.assertRaises(wiring.Unparseable):  # subset_depth_unbounded
            wiring.parse("".join(f"{'  ' * i}k{i}:\n" for i in range(40)).encode() + b"  " * 40 + b"v: 1\n")
        with self.assertRaises(wiring.Unparseable):
            wiring.parse(b"a: " + b"x" * wiring.MAX_BYTES + b"\n")

    def test_what_yaml_reads_otherwise_is_refused_by_name(self):
        # wiring_paragraph_separator_passes wiring_noncharacters_pass wiring_double_quote_text_after_passes
        # wiring_literal_blank_with_spaces_passes
        cases = {"name: lo\u2029op\n": "control_character",  # a line break to YAML 1.1, text to 1.2
                 "name: lo\ufffeop\n": "control_character", "name: lo\uffffop\n": "control_character",  # not printable
                 'name: "a" b\n': "text_after_quote",  # GitHub refuses it; read as "a" it would pass
                 "run: |\n  echo 1\n   \n  echo 2\n": "blank_line_with_spaces"}  # content or a blank: two readings
        for text, why in cases.items():
            with self.subTest(text=text), self.assertRaises(wiring.Unparseable) as caught:
                wiring.parse(text.encode("utf-8"))
            self.assertEqual(caught.exception.why, why, text)
        self.assertEqual(wiring.parse("name: lo\ufffdop\nrun: |\n  echo 1\n\n  echo 2\n".encode()),
                         {"name": "lo\ufffdop", "run": "echo 1\n\necho 2\n"})

    def test_nesting_is_capped_at_exactly_max_depth(self):  # wiring_depth_bound_33
        def nested(levels):
            return ("".join(f"{'  ' * i}k{i}:\n" for i in range(levels - 1)) + "  " * (levels - 1) + "v: 1\n").encode()
        self.assertEqual(wiring.MAX_DEPTH, 32)
        self.assertIsInstance(wiring.parse(nested(wiring.MAX_DEPTH)), dict)
        with self.assertRaises(wiring.Unparseable) as caught:
            wiring.parse(nested(wiring.MAX_DEPTH + 1))
        self.assertEqual(caught.exception.why, "too_deep")


def workflow(old=None, new=None, *more):
    """LOOP_YML with each ``old`` (found exactly once) replaced by ``new``."""
    text = LOOP_YML
    pairs = [(old, new)] + list(zip(more[::2], more[1::2])) if old is not None else []
    for o, n in pairs:
        assert text.count(o) == 1, o
        text = text.replace(o, n)
    return text.encode()


def job_block(name):
    start = LOOP_YML.index(f"  {name}:\n")
    following = [LOOP_YML.index(f"  {j}:\n") for j in wiring.JOBS if LOOP_YML.index(f"  {j}:\n") > start]
    return LOOP_YML[start:min(following) if following else len(LOOP_YML)]


def in_job(name, old, new):
    block = job_block(name)
    assert block.count(old) == 1, (name, old)
    return block, block.replace(old, new)


class WorkflowRules(unittest.TestCase):
    """Test 46's rules (`asama-0/09`; `tohum/08`, `01a`), one case each."""

    def check(self, text, extra=None):
        return wiring.check(dict({"loop.yml": text}, **(extra or {})))

    def test_the_seeds_fixture_keeps_every_rule(self):
        self.assertEqual(self.check(workflow()), [])

    def test_the_directory_holds_loop_yml_and_nothing_else(self):  # workflow_extra_files_pass
        self.assertEqual(self.check(workflow(), {"loop.yaml": b"x: 1\n"}), ["workflow_extra_file:loop.yaml"])
        self.assertEqual(self.check(workflow(), {"bootstrap.yml": workflow()}), ["workflow_extra_file:bootstrap.yml"])
        self.assertEqual(wiring.check({"ci.yml": workflow()}), ["workflow_extra_file:ci.yml", "workflow_missing:loop.yml"])
        self.assertEqual(wiring.check({}), ["workflow_missing:loop.yml"])
        self.assertEqual(self.check(b"name: loop\nname: again\n")[0][:30], "workflow_unparseable:loop.yml:")

    def test_top_level_permissions_are_empty(self):  # workflow_top_permissions_unchecked
        self.assertEqual(self.check(workflow("permissions: {}\njobs:", "permissions: read-all\njobs:")),
                         ["workflow_top_permissions"])
        self.assertEqual(self.check(workflow("permissions: {}\njobs:", "jobs:")), ["workflow_top_permissions"])

    def test_no_forbidden_trigger_in_any_form(self):  # workflow_trigger_mapping_form_ignored workflow_trigger_case_sensitive
        on_block = "on:\n  schedule:\n    - cron: '7 * * * *'\n  workflow_dispatch: {}\n"
        for event in wiring.FORBIDDEN_EVENTS:
            for form in (f"on: {event}\n", f"on:\n  - schedule\n  - {event}\n",
                         on_block + f"  {event}: {{}}\n", on_block + f"  {event}:\n    types:\n      - created\n"):
                with self.subTest(form=form):
                    self.assertEqual(self.check(workflow(on_block, form)), [f"workflow_trigger:{event}"])
        self.assertEqual(self.check(workflow(on_block, "on: Issue_Comment\n")), ["workflow_trigger:Issue_Comment"])
        self.assertEqual(self.check(workflow(on_block, "")), ["workflow_trigger:none"])

    def test_the_five_jobs_and_no_other(self):  # workflow_job_set_unchecked
        extra = LOOP_YML + "  lint:\n    if: github.ref == 'refs/heads/main'\n    permissions: {}\n    steps:\n      - run: x\n"
        self.assertEqual(self.check(extra.encode()), ["workflow_unknown_job:lint", "workflow_control_step:lint"])
        block = job_block("getir")
        self.assertEqual(self.check(workflow(block, "")), ["workflow_missing_job:getir"])

    def test_every_job_runs_on_main_only(self):  # workflow_main_only_by_substring
        for job, new in (("getir", "if: github.ref == 'refs/heads/main' || true"),
                         ("cek", "if: always()"), ("yaz", "if: github.ref != 'refs/heads/main'")):
            self.assertEqual(self.check(workflow(*in_job(job, "if: github.ref == 'refs/heads/main'", new))),
                             [f"workflow_job_not_main_only:{job}"], job)
        self.assertEqual(self.check(workflow(*in_job("kos", "    if: github.ref == 'refs/heads/main'\n", ""))),
                         ["workflow_job_not_main_only:kos"])

    def test_no_github_context_in_a_run_script(self):  # workflow_github_in_run_naive workflow_contexts_case_sensitive
        for script in ("echo ${{github.ref}}", "echo ${{ GITHUB.event.head_commit.message }}",
                       'echo "${{ toJSON(github) }}"', "echo ${{ format('{0}', github.ref) }}"):
            self.assertEqual(self.check(workflow("run: python3 -m loop fetch", f"run: {script}")),
                             ["workflow_github_in_run:getir:2"], script)
        literal = workflow('python3 -m loop pull --out "$RUNNER_TEMP/pulled"', 'echo "${{ github.head_ref }}"')
        self.assertEqual(self.check(literal), ["workflow_github_in_run:cek:3"])
        # Through the environment it is data, not script (E17): the fixture's `yaz` does that and passes.
        self.assertEqual(self.check(workflow("run: python3 -m loop fetch", "run: echo $GITHUB_REF $STEPS_GITHUB")), [])

    def test_actions_are_pinned_by_sha(self):  # workflow_pin_by_tag workflow_reusable_unpinned_passes
        pinned = "actions/checkout@0123456789abcdef0123456789abcdef01234567"
        for ref in ("actions/checkout@v4", "actions/checkout@0123456", "actions/checkout@" + "A" * 40,
                    "./.github/actions/x", "docker://alpine:3", "actions/checkout"):
            self.assertEqual(self.check(workflow(pinned, ref)), ["workflow_action_not_pinned:cek:2"], ref)
        reusable = "  other:\n    if: github.ref == 'refs/heads/main'\n    uses: o/r/.github/workflows/w.yml@main\n"
        self.assertEqual(self.check((LOOP_YML + reusable).encode()),
                         ["workflow_unknown_job:other", "workflow_action_not_pinned:other:job",
                          "workflow_control_step:other"])

    def test_checkout_never_keeps_its_credentials(self):  # workflow_persist_credentials_unchecked
        keep = "        with:\n          persist-credentials: false\n"
        for new in ("", "        with:\n          persist-credentials: true\n",
                    "        with:\n          persist-credentials: False\n", "        with:\n          fetch-depth: 1\n"):
            self.assertEqual(self.check(workflow(keep, new)), ["workflow_persist_credentials:cek:2"], new)
        self.assertEqual(self.check(workflow(keep, "        with:\n          persist-credentials: 'false'\n")), [])

    def test_the_jobs_that_run_code_hold_no_rights_and_no_secret(self):  # workflow_code_job_rights_unchecked
        self.assertEqual(self.check(workflow(*in_job("kos", "permissions: {}", "permissions:\n      contents: read"))),
                         ["workflow_code_job_permissions:kos"])
        self.assertEqual(self.check(workflow(*in_job("getir", "    permissions: {}\n", ""))),
                         ["workflow_code_job_permissions:getir"])
        secret = "      - name: run\n        env:\n          T: ${{ secrets.CLAUDE_CODE_OAUTH_TOKEN }}\n        run: python3 -m loop run\n"
        self.assertEqual(self.check(workflow("      - name: run\n        run: python3 -m loop run\n", secret)),
                         ["workflow_secret_in_code_job:kos"])
        lower = "        with:\n          name: deps\n"
        self.assertEqual(self.check(workflow(lower, "        with:\n          name: ${{ SECRETS.x }}\n")),
                         ["workflow_secret_in_code_job:kos"])

    def test_secrets_ids_and_write_scopes_only_where_the_table_puts_them(self):  # workflow_write_scope_outside_the_secret_jobs
        cek_perms = "    permissions:\n      contents: read\n      actions: read\n"
        for perms in ("    permissions:\n      contents: write\n", "    permissions:\n      id-token: write\n",
                      "    permissions: write-all\n"):
            self.assertEqual(self.check(workflow(cek_perms, perms)), ["workflow_secret_job:cek"], perms)
        env = "      - name: pull\n        env:\n          K: ${{ secrets.X }}\n"
        self.assertEqual(self.check(workflow("      - name: pull\n", env)), ["workflow_secret_job:cek"])
        top = workflow("permissions: {}\njobs:", "permissions: {}\nenv:\n  K: ${{ secrets.X }}\njobs:")
        self.assertEqual(self.check(top), ["workflow_secret_job:workflow", "workflow_control_context:workflow"])

    def test_secrets_are_never_enumerated_or_inherited(self):  # workflow_secrets_enumeration_unchecked
        for value in ("${{ toJSON(secrets) }}", "${{ secrets['CLAUDE_CODE_OAUTH_TOKEN'] }}", "${{ secrets }}"):
            text = workflow("CLAUDE_CODE_OAUTH_TOKEN: ${{ secrets.CLAUDE_CODE_OAUTH_TOKEN }}",
                            f"CLAUDE_CODE_OAUTH_TOKEN: {value}")
            self.assertEqual(self.check(text), ["workflow_secrets_enumerated:cagir"], value)
        inherit = workflow(*in_job("cagir", "    needs:\n", "    secrets: inherit\n    needs:\n"))
        self.assertEqual(self.check(inherit), ["workflow_secrets_enumerated:cagir"])
        top = workflow("permissions: {}\njobs:", "permissions: {}\nenv:\n  ALL: ${{ toJSON(secrets) }}\njobs:")
        self.assertEqual(self.check(top), ["workflow_secret_job:workflow", "workflow_secrets_enumerated:workflow",
                                           "workflow_control_context:workflow"])
        # wiring_top_level_enumeration_unchecked

    def test_an_expression_ends_where_githubs_template_reader_ends_it(self):
        """E288: GitHub ends ``${{`` at the first ``}}`` outside a single-quoted literal; ending it at any ``}}`` let
        ``'}}' && secrets.X`` hand a secret to the job that runs the Founder's code."""
        # expression_ends_at_any_braces expression_left_open_ignored
        self.assertEqual(wiring._expressions("${{ '}}' && secrets.X }}"), [" '}}' && secrets.X "])
        self.assertEqual(wiring._expressions("a ${{ 'it''s }}' }} b ${{x}}}"), [" 'it''s }}' ", "x"])
        self.assertEqual(wiring._expressions("${{ github.ref"), [" github.ref"])  # left open: all of it is read
        self.assertEqual(wiring._expressions("${{ '}}' && github.ref"), [" '}}' && github.ref"])
        self.assertEqual(wiring._expressions("no ${ { expression } }"), [])
        kos = workflow("      - name: run\n        run: python3 -m loop run\n",
                       "      - name: run\n        env:\n          T: ${{ '}}' && secrets.CLAUDE_CODE_OAUTH_TOKEN }}\n"
                       "        run: python3 -m loop run\n")
        self.assertEqual(self.check(kos), ["workflow_secret_in_code_job:kos"])
        run = workflow("run: python3 -m loop fetch", "run: echo ${{ '}}' && github.event.head_commit.message }}")
        self.assertEqual(self.check(run), ["workflow_github_in_run:getir:2"])
        every = workflow("CLAUDE_CODE_OAUTH_TOKEN: ${{ secrets.CLAUDE_CODE_OAUTH_TOKEN }}",
                         "CLAUDE_CODE_OAUTH_TOKEN: ${{ '}}' && toJSON(secrets) }}")
        self.assertEqual(self.check(every), ["workflow_secrets_enumerated:cagir"])

    def test_no_github_context_in_any_script_the_runner_executes(self):
        """Test 46's ``run:`` read for what it guards (E288): the shell line, ``defaults.run`` and github-script's
        ``script`` are code too. ``working-directory`` is a path the runner starts the process in, not code."""
        # script_shell_unchecked github_script_unchecked job_defaults_unchecked workflow_defaults_unchecked
        fetch = "      - name: fetch\n        run: python3 -m loop fetch\n"
        shell = fetch + "        shell: bash -c \"${{ github.event.head_commit.message }} {0}\"\n"
        self.assertEqual(self.check(workflow(fetch, shell)), ["workflow_github_in_run:getir:2"])
        script = ("      - uses: actions/github-script@0123456789abcdef0123456789abcdef01234567\n        with:\n"
                  "          script: console.log('${{ github.event.issue.title }}')\n")
        self.assertEqual(self.check(workflow(fetch, script)), ["workflow_github_in_run:getir:2"])
        defaults = "    defaults:\n      run:\n        shell: bash ${{ github.head_ref }} {0}\n    steps:\n"
        self.assertEqual(self.check(workflow(*in_job("getir", "    steps:\n", defaults))),
                         ["workflow_github_in_run:getir:defaults", "workflow_control_context:getir"])
        top = workflow("permissions: {}\njobs:", "permissions: {}\ndefaults:\n  run:\n    shell: ${{ github.ref }}\njobs:")
        self.assertEqual(self.check(top), ["workflow_github_in_run:workflow:defaults", "workflow_control_context:workflow"])
        self.assertEqual(self.check(workflow("permissions: {}\njobs:", "permissions: {}\ndefaults: x\njobs:")),
                         ["workflow_github_in_run:workflow:defaults",  # not a mapping: no script the seed can read
                          "workflow_control_context:workflow"])
        where = fetch + "        working-directory: ${{ github.workspace }}/referee\n"
        self.assertEqual(self.check(workflow(fetch, where)), [])
        quiet = fetch + "        shell: bash\n"
        self.assertEqual(self.check(workflow(fetch, quiet)), [])

    def test_a_workflow_directory_spelt_in_other_letters_is_the_same_directory(self):
        """E289: the operator imports on a case-insensitive file system, where `.GITHUB/workflows/` is
        `.github/workflows/`; a file there is an extra file, and a `loop.yml` only there is no `loop.yml`."""
        # workflow_directory_case_sensitive case_variant_directory_read_as_loop
        found = wiring.files_in({LOOP: b"a", "referee/.GITHUB/workflows/evil.yml": b"b", "referee/x.py": b"c",
                                 "referee/.github/workflows.py": b"d", "referee/.github/WorkFlows/sub/c.yml": b"e"})
        self.assertEqual(found, {"loop.yml": b"a", ".GITHUB/workflows/evil.yml": b"b", ".github/WorkFlows/sub/c.yml": b"e"})
        self.assertEqual(wiring.check(dict(found, **{"loop.yml": workflow()})),
                         ["workflow_extra_file:.GITHUB/workflows/evil.yml", "workflow_extra_file:.github/WorkFlows/sub/c.yml"])
        only = wiring.files_in({"referee/.GITHUB/Workflows/loop.yml": workflow()})
        self.assertEqual(wiring.check(only), ["workflow_extra_file:.GITHUB/Workflows/loop.yml", "workflow_missing:loop.yml"])
        self.assertEqual(wiring.check({"LOOP.yml": workflow()}), ["workflow_extra_file:LOOP.yml", "workflow_missing:loop.yml"])


class WorkflowOnEveryPush(ExitFlow):
    """`asama-0/14` MF17: the `wiring` check runs on every push once the loop workflow's micro-feature is finished,
    and at the exit; before that the file is the Founder's work in progress."""

    def test_the_check_starts_with_the_micro_feature_that_owns_the_workflow(self):  # wiring_before_its_micro_feature
        self.assertEqual([f.mf for f in test_flow.STAGE0.mfs if f.module == wiring.MODULE], [17])
        self.freeze_stage0()
        broken = workflow("permissions: {}\njobs:", "jobs:")
        commit(self.brain, {LOOP: broken, "referee/ledger/chain.py": "x = 1\n",
                            "snowball-tests.json": test_flow.all_tests_manifest(range(1, 17))}, "up to MF16")
        self.assertEqual(self.pull()["pre_reasons"], [])
        commit(self.brain, {"snowball-tests.json": test_flow.all_tests_manifest(range(1, 18))}, "MF17")
        meta = self.pull()
        self.assertEqual((meta["pre_reasons"], meta["run_rival"]), (["workflow_top_permissions"], False))
        commit(self.brain, {LOOP: workflow()}, "MF17 fixed")
        self.assertEqual(self.pull()["pre_reasons"], [])

    def test_a_finished_micro_feature_cannot_be_undeclared(self):  # done_mf_withdrawal_passes wiring_due_on_the_head_alone
        """E292: a group, and MF17's wiring check, run on every push after the one the MF entered done_mf in
        (`asama-0/14`, `29a`). Declaring fewer would switch them off, so the push is refused and still checked."""
        self.freeze_stage0()
        self.accept({"referee/ledger/chain.py": "x = 1\n", LOOP: workflow()}, done=range(1, 18))
        commit(self.brain, {LOOP: workflow("permissions: {}\njobs:", "jobs:"), "referee/ledger/chain.py": "x = 2\n",
                            "snowball-tests.json": test_flow.all_tests_manifest(range(1, 17))}, "MF17 undeclared")
        meta = self.pull()
        self.assertEqual(meta["pre_reasons"], ["done_mf_withdrawn:MF17", "workflow_top_permissions"])
        self.assertEqual((meta["run_tests"], meta["run_rival"]), (False, False))
        result = self.finish(meta, jobs=CODE_JOBS)
        self.assertEqual(result["verdict"], "rejected")
        self.assertIn("done_mf_withdrawn:MF17:", result["state"]["reject_streaks"])  # the Founder's to fix
        commit(self.brain, {LOOP: workflow(), "snowball-tests.json": test_flow.all_tests_manifest(range(1, 15))},
               "three undeclared, the workflow fixed")
        self.assertEqual(self.pull()["pre_reasons"], ["done_mf_withdrawn:MF15", "done_mf_withdrawn:MF16",
                                                      "done_mf_withdrawn:MF17"])
        commit(self.brain, {"snowball-tests.json": test_flow.all_tests_manifest(range(1, 18))}, "declared again")
        self.assertEqual(self.pull()["pre_reasons"], [])

    def test_at_the_exit_every_rule_is_checked_the_control_rule_too(self):  # exit_wiring_check_not_wired
        self.freeze_stage0()
        self.accept({"referee/ledger/chain.py": "x = 1\n", LOOP: workflow("permissions: {}\njobs:", "jobs:")})
        meta = self.ask_exit()
        self.assertEqual(meta["exit_checks"]["is-akisi"], {"status": "failed", "reasons": ["workflow_top_permissions"],
                                                           "why": ""})
        result = self.finish(meta, run=self.green_run(meta), jobs=EXIT_JOBS)
        refs = [r["ref"] for r in result["reasons"]]
        self.assertIn("workflow_top_permissions", refs)
        self.assertNotIn("not_checked:is-akisi", refs)  # E282: the control sub-rule is decided by reading the file


# ---------------------------------------------------------------- #agac


class RefereeTree(unittest.TestCase):
    """`asama-0/10` #agac: no operator name in any case, no agent configuration, the toy subtree's hash signed."""

    def test_operator_names_and_the_bootstraps_own_are_refused_in_any_case(self):  # operator_names_case_sensitive bootstrap_not_reserved
        for name in ("referee/Policy.json", "referee/CONTROL.JSON", "referee/SETUP/summary.json", "referee/Seats/x.md",
                     "referee/bootstrap/snowball_bootstrap/cli.py", "referee/BootStrap.json", "referee/\u017fetup/x"):
            with self.assertRaises(TreeError, msg=name):
                tree_hash(tar_of({"referee/a.py": "x", name: "y"}), "referee")
        self.assertEqual(len(tree_hash(tar_of({"referee/a.py": "x", "referee/tests/setup/x.py": "y",
                                              "referee/policy_check.py": "z"}), "referee")), 64)

    def test_two_names_one_on_a_case_insensitive_file_system_are_refused(self):  # case_collisions_pass
        """E289, E130: the operator imports on Windows, where the second of two such names is written over the first
        (the probe: `.GITHUB/workflows/evil.yml` beside `.github/workflows/loop.yml` committed as `.GITHUB/`, so GitHub
        ran no workflow and an unchecked one sat in the referee repo)."""
        for files in ({"referee/.github/workflows/loop.yml": "a", "referee/.GITHUB/workflows/evil.yml": "b"},
                      {"referee/a.py": "x", "referee/A.py": "y"}, {"referee/gate/x.py": "x", "referee/GATE/y.py": "y"},
                      {"referee/gate": "x", "referee/Gate/y.py": "y"}):
            with self.subTest(files=sorted(files)), self.assertRaises(TreeError) as caught:
                tree_hash(tar_of(files), "referee")
            self.assertIn("case-insensitive", str(caught.exception))
        self.assertEqual(len(tree_hash(tar_of({"referee/a.py": "x", "referee/ab.py": "y", "referee/b/a.py": "z"}),
                                       "referee")), 64)
        loose = tar_of({"spec/asama-0/a.md": "x", "spec/asama-0/A.md": "y"})  # not imported: hashed as it is
        self.assertEqual(len(tree_hash(loose, "spec/asama-0", forbid_operator_names=False)), 64)

    def test_the_import_refuses_names_its_file_system_would_fold(self):
        """The brain's git keeps both names; the import stops before it wipes anything of the operator's."""
        brain_tar = tar_of({"referee/.github/workflows/loop.yml": LOOP_YML, "referee/.GITHUB/workflows/evil.yml": "x"})
        with tempfile.TemporaryDirectory() as tmp:
            result = Path(tmp) / "result.json"
            result.write_text(json.dumps({"verdict": "accepted", "head": A, "exit": {
                "transferable": True, "brain_sha": A, "referee_tree_sha256": "0" * 64}}))
            referee = Path(tmp) / "referee"
            (referee / ".github" / "workflows").mkdir(parents=True)
            (referee / ".github" / "workflows" / "bootstrap.yml").write_text("name: bootstrap\n")
            with mock.patch.object(importer, "verify_signature"), \
                    mock.patch.object(importer.gitio, "has_commit", return_value=True), \
                    mock.patch.object(importer.gitio, "archive", return_value=brain_tar), \
                    self.assertRaises(TreeError):
                importer.run_import(result, result, "id", "py", Path(tmp), referee, None)
            self.assertEqual((referee / ".github" / "workflows" / "bootstrap.yml").read_text(), "name: bootstrap\n")

    def test_the_import_refuses_a_mixed_case_operator_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            brain = Path(tmp) / "brain"
            sha = make_repo(brain, {"referee/a.py": "x\n", "referee/Control.json": "{}\n"})
            result = Path(tmp) / "result.json"
            result.write_text(json.dumps({"verdict": "accepted", "head": sha, "exit": {
                "transferable": True, "brain_sha": sha, "referee_tree_sha256": "0" * 64}}))
            referee = Path(tmp) / "referee"
            referee.mkdir()
            (referee / "control.json").write_text('{"kill_switch": true}')
            with mock.patch.object(importer, "verify_signature"), self.assertRaises(TreeError):
                importer.run_import(result, result, "id", "py", brain, referee, None)
            self.assertEqual((referee / "control.json").read_text(), '{"kill_switch": true}')

    def test_agent_configuration_is_refused_at_any_depth_and_in_any_case(self):  # agent_config_case_sensitive
        for path in ("referee/.claude/settings.json", "referee/tests/x/.claude/hooks.py", "referee/tests/x/CLAUDE.md",
                     "referee/.VSCode/settings.json", "referee/gate/.mcp.json", "referee/.envrc", "referee/AGENTS.md",
                     "referee/.devcontainer/devcontainer.json", "referee/a/Claude.MD"):
            self.assertTrue(classify.is_agent_config(path), path)
            res, _toy = exitchecks.referee_tree({"referee/a.py": b"x", path: b"y"}, tar_of({TOY: "x"}))
            self.assertEqual(res["reasons"], [f"agent_config_in_referee:{path}"], path)
        for path in ("referee/claude.md.txt", "referee/notclaude/x.py", "referee/claude/x.py", "referee/.envrc.d/x",
                     "referee/vscode/x"):
            self.assertFalse(classify.is_agent_config(path), path)

    def test_the_toy_subtree_is_hashed_into_the_result_or_missing(self):  # toy_hash_from_the_wrong_prefix toy_missing_passes
        tar = tar_of({TOY: "import os\n", "tests/fixtures/toy-repo/README.md": "toy\n", "tests/other.py": "x"})
        res, toy = exitchecks.referee_tree({"referee/a.py": b"x"}, tar)
        self.assertEqual((res["status"], toy), ("ok", tree_hash(tar, "tests/fixtures/toy-repo", forbid_operator_names=False)))
        res, toy = exitchecks.referee_tree({"referee/a.py": b"x"}, tar_of({"tests/other.py": "x"}))
        self.assertEqual((res["reasons"], toy), (["toy_tree_missing"], None))

    def test_the_toy_is_imported_onto_the_same_file_system(self):  # toy_case_collision_passes
        tar = tar_of({TOY: "x", "tests/fixtures/toy-repo/App.py": "y"})
        res, toy = exitchecks.referee_tree({"referee/a.py": b"x"}, tar)
        self.assertEqual((res["status"], toy), ("failed", None))
        self.assertEqual(res["reasons"], ["toy_tree:tests/fixtures/toy-repo/App.py and tests/fixtures/toy-repo/app.py "
                                          "are one name on a case-insensitive file system"])


# ---------------------------------------------------------------- #genellik


TARGET = {"id": "copy", "repo": "owner/copy", "kind": "copy", "base_sha": "c" * 40, "identifiers": ["Zorbalix"],
          "excluded_paths": [], "unit_candidates": ["packages/api"]}


class Generality(unittest.TestCase):
    """`asama-0/10` #genellik: no name from `targets[].identifiers` in `referee/`'s text or paths (E284)."""

    BASE = {"seed_commit": "a" * 40, "seed_tree_sha256": "b" * 64}

    def load(self, doc):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "setup").mkdir()
            (Path(tmp) / "setup" / "summary.json").write_text(json.dumps(doc))
            return load_summary(Path(tmp))

    def test_targets_are_read_strictly(self):  # targets_typo_accepted
        self.assertIsNone(self.load(self.BASE).targets)
        summary = self.load(dict(self.BASE, targets=[TARGET, dict(TARGET, id="toy", kind="toy", base_sha=None,
                                                                   identifiers=[])]))
        self.assertEqual([(t.id, t.identifiers) for t in summary.targets], [("copy", ("Zorbalix",)), ("toy", ())])
        without = {k: v for k, v in TARGET.items() if k != "identifiers"}
        for bad in ({}, [dict(without, identifers=["Zorbalix"])], [without], [dict(TARGET, note="x")],
                    [dict(TARGET, kind="real")], [dict(TARGET, identifiers="Zorbalix")], [dict(TARGET, identifiers=[" "])],
                    [dict(TARGET, identifiers=[1])], [TARGET, dict(TARGET)], [dict(TARGET, base_sha="c" * 39)],
                    [dict(TARGET, repo="copy")], ["copy"]):
            with self.assertRaises(ConfigError, msg=repr(bad)):
                self.load(dict(self.BASE, targets=bad))

    def summary(self, *targets):
        return config.Summary("a" * 40, "b" * 64, (), tuple(config.target(t, "t") for t in targets))

    def test_a_name_in_any_case_in_a_file_or_a_path_is_refused(self):  # generality_case_sensitive generality_paths_skipped
        targets = self.summary(TARGET).targets
        files = {"referee/a.py": b"x = 1\n", "referee/gate/b.py": b"# talks to ZORBALIX's api\n"}
        res = exitchecks.generality(files, targets)
        self.assertEqual((res["status"], res["reasons"]), ("failed", ["target_name_in_referee:referee/gate/b.py"]))
        self.assertIn("targets[0].identifiers[0]", res["why"])
        for path in ("referee/zorbalix_client.py", "referee/ZorbaLix_client.py"):  # generality_path_case_sensitive
            res = exitchecks.generality({"referee/a.py": b"x\n", path: b"x\n"}, targets)
            digest = hashlib.sha256(path.encode()).hexdigest()[:16]
            self.assertEqual(res["reasons"], [f"target_name_in_referee:sha256:{digest}"], path)
            self.assertNotIn("orbalix", json.dumps(res).casefold())  # generality_identifier_published
        self.assertEqual(exitchecks.generality({"referee/a.py": b"x\n"}, targets)["status"], "ok")

    def test_a_name_is_the_same_name_in_any_unicode_spelling(self):
        """E291: the name is compared `fold`-ed: one normal form, any case, without combining marks, ı as i; so every
        letter Python's own ``re.IGNORECASE`` takes for another (`ıskele` matches `iskele`) is that letter here."""
        # generality_unnormalized generality_marks_kept generality_dotless_i_apart generality_case_sensitive
        nfc = "g\u00fcne\u015f"
        nfd = unicodedata.normalize("NFD", nfc)
        for name, text in ((nfc, f"T = '{nfd}'"), (nfd, f"T = '{nfc}'"), (nfc, "G\u00dcNE\u015e"), (nfc, "gunes_client"),
                           (nfc, "\uff27\uff35\uff2e\uff25\uff33"), ("iskele", "re.compile('\u0131skele', re.I)"),
                           ("\u0130skele", "iskele"), ("Iskele", "\u0131SKELE"), ("strasse", "Stra\u00dfe"),
                           ("Zorbalix", "ZORBALIX")):
            targets = self.summary(dict(TARGET, identifiers=[name])).targets
            with self.subTest(name=name, text=text):
                self.assertEqual(exitchecks.generality({"referee/t.py": text.encode()}, targets)["status"], "failed")
                self.assertEqual(exitchecks.generality({f"referee/{text}.py": b"x\n"}, targets)["status"], "failed")
        self.assertEqual(exitchecks.fold("\u0130\u0131I\u017f\u212a"), "iiisk")
        targets = self.summary(dict(TARGET, identifiers=[nfc])).targets
        self.assertEqual(exitchecks.generality({"referee/t.py": b"gune = 1\n"}, targets)["status"], "ok")

    def test_a_file_that_is_not_text_does_not_pass_unread(self):  # generality_binary_read_with_replacement generality_nul_text_read
        """A name in UTF-16 or ISO-8859-9 is not seen in the UTF-8 reading; such a file is not vouched for."""
        targets = self.summary(dict(TARGET, identifiers=["suderra", "g\u00fcne\u015f"])).targets
        for data in ("suderra\n".encode("utf-16"), "g\u00fcne\u015f\n".encode("iso8859_9"),
                     "suderra\n".encode("utf-16-le"), b"x = 1\n\x00\n"):
            res = exitchecks.generality({"referee/a.py": b"x\n", "referee/names.dat": data}, targets)
            self.assertEqual((res["status"], res["reasons"]), ("failed", ["referee_file_not_text:referee/names.dat"]), data)
        named = exitchecks.generality({"referee/suderra.bin": b"\xff\n"}, targets)
        digest = hashlib.sha256(b"referee/suderra.bin").hexdigest()[:16]
        self.assertEqual(named["reasons"], [f"target_name_in_referee:sha256:{digest}"])  # the name in the path first

    def test_without_names_to_look_for_it_stays_unchecked(self):  # generality_without_targets_passes
        toy = dict(TARGET, id="toy", kind="toy", base_sha=None, identifiers=[])
        for targets in (None, (), self.summary(dict(TARGET, identifiers=[]), toy).targets,
                        self.summary(dict(toy, identifiers=["Zorbalix"])).targets,  # generality_without_a_copy_decides
                        self.summary(dict(TARGET, identifiers=["\u0301"]), toy).targets):  # generality_empty_fold_matches_everything
            res = exitchecks.generality({"referee/a.py": b"x\n"}, targets)
            self.assertEqual(res["status"], "undecided", targets)
            self.assertIn("E2", res["why"])
        # The toy's content is the Founder's own fixture: without identifiers it has nothing to look for (E291).
        res = exitchecks.generality({"referee/a.py": b"x\n"}, self.summary(TARGET, toy).targets)  # generality_toy_needs_identifiers
        self.assertEqual(res["status"], "ok")

    def test_no_check_publishes_a_name_in_clear(self):  # names_published_by_other_anchors why_published
        """E290: #genellik withholds a path that carries a name; the other anchors quote the same paths, and the
        skeptic read the name back from #agac's and #is-akisi's reasons."""
        targets = self.summary(TARGET).targets
        files = {LOOP: LOOP_YML, "referee/loop/__init__.py": "", TOY: "x\n",
                 "referee/.claude/zorbalix-notes.md": "x\n", "referee/.github/workflows/Zorbalix.yml": LOOP_YML}
        results, _toy = exitchecks.run(tar_of(files), None, None, targets)
        self.assertNotIn("zorbalix", json.dumps(results).casefold())
        self.assertEqual(results["agac"]["reasons"], ["agent_config_in_referee:sha256:" + hashlib.sha256(
            b"referee/.claude/zorbalix-notes.md").hexdigest()[:16]])
        self.assertEqual(results["is-akisi"]["reasons"], ["workflow_extra_file:sha256:" + hashlib.sha256(
            b"Zorbalix.yml").hexdigest()[:16]])
        loud = {"status": "failed", "reasons": ["x:zorbalix"], "why": "found in Zorbalix's client"}
        with mock.patch.object(exitchecks, "generality", return_value=loud):
            results, _toy = exitchecks.run(tar_of(files), None, None, targets)
        self.assertNotIn("zorbalix", json.dumps(results["genellik"]).casefold())
        self.assertEqual(exitchecks.withheld("sha256:0123456789abcdef", exitchecks.target_names(targets)),
                         "sha256:0123456789abcdef")


class GeneralityFlow(ExitFlow):
    def test_the_names_are_looked_for_at_the_exit_and_never_published(self):
        self.write_summary(targets=[TARGET])
        self.freeze_stage0()
        self.accept({"referee/ledger/chain.py": "# a client for zorbalix\nx = 1\n"})
        meta = self.ask_exit()
        self.assertEqual(meta["exit_checks"]["genellik"]["reasons"], ["target_name_in_referee:referee/ledger/chain.py"])
        result = self.finish(meta, run=self.green_run(meta), jobs=EXIT_JOBS)
        self.assertIn("target_name_in_referee:referee/ledger/chain.py", [r["ref"] for r in result["reasons"]])
        self.assertNotIn("zorbalix", json.dumps(result).casefold())

    def test_the_exits_other_reasons_withhold_a_name_too(self):  # exit_pre_reasons_published
        self.write_summary(targets=[TARGET])
        self.freeze_stage0()
        self.accept({"referee/ledger/chain.py": "x = 1\n"})
        manifest = dict(json.loads(test_flow.all_tests_manifest([1])), lockfiles=["requirements/zorbalix.lock"])
        self.state["last_accepted_sha"] = commit(self.brain, {"snowball-tests.json": json.dumps(manifest)}, "lock gone")
        meta = self.ask_exit()
        digest = hashlib.sha256(b"requirements/zorbalix.lock").hexdigest()[:16]
        self.assertIn(f"lockfile_missing:sha256:{digest}", meta["pre_reasons"])
        result = self.finish(meta, jobs=EXIT_JOBS)
        self.assertNotIn("zorbalix", json.dumps(result).casefold())

    def test_without_targets_the_exit_says_whose_step_is_missing(self):
        self.freeze_stage0()
        self.accept({"referee/ledger/chain.py": "x = 1\n"})
        meta = self.ask_exit()
        self.assertEqual(meta["exit_checks"]["genellik"]["status"], "undecided")
        result = self.finish(meta, run=self.green_run(meta), jobs=EXIT_JOBS)
        self.assertIn("not_checked:genellik", result["exit"]["missing"])
        self.assertNotIn("exit_condition:not_checked:genellik", result["state"]["reject_streaks"])


# ---------------------------------------------------------------- the four together


class AllFourAtTheExit(ExitFlow):
    def test_a_complete_brain_leaves_only_what_the_seed_cannot_check(self):
        self.write_summary(targets=[TARGET])
        self.freeze_stage0()
        rows = ledger_rows(3)
        self.accept({"referee/ledger/chain.py": "x = 1\n", LOOP: workflow(), TOY: "import os\n",
                     "founder-ledger.jsonl": ledger_bytes(rows)}, done=test_flow.ALL_MFS)
        meta = self.ask_exit({"founder-ledger.jsonl": ledger_bytes(rows + ledger_rows(1, start=4,
                                                                                         prev=rows[-1]["row_hash"]))})
        self.assertEqual({a: c["status"] for a, c in meta["exit_checks"].items()},
                         {"kurucu-defteri": "ok", "is-akisi": "ok", "agac": "ok", "genellik": "ok"})
        tar = (Path(self.tmp.name) / f"pulled{self.n}" / "brain.tar").read_bytes()
        self.assertEqual(meta["toy_tree_sha256"], tree_hash(tar, "tests/fixtures/toy-repo", forbid_operator_names=False))
        self.assertEqual(meta["pre_reasons"], [])

    def test_a_check_that_breaks_keeps_the_exit_closed_and_says_why(self):  # exit_check_crash_is_pull_error
        self.freeze_stage0()
        self.accept({"referee/ledger/chain.py": "x = 1\n"})
        with mock.patch.object(exitchecks.wiring, "check", side_effect=RecursionError("deep")):
            meta = self.ask_exit()
        self.assertEqual(meta["exit_checks"]["is-akisi"]["status"], "undecided")
        self.assertIn("RecursionError", meta["exit_checks"]["is-akisi"]["why"])
        self.assertNotIn("pull_error", meta["pre_reasons"])


if __name__ == "__main__":
    unittest.main()
