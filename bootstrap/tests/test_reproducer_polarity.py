"""E260: a reproducer's polarity (`docs/eksik-kaydi.md`, `tohum/29` "Rakibin kuralları").

The referee sees bytes: whether the text a reproducer names shows on a head, and on an empty tree. Whether that text
is the defect's symptom or what correct code prints is the rival's meaning, never in the bytes. The live pilot's claim
87c088321252 (`fixtures/rival/polarity_87c088321252.json`, copied from the signed results) expected what correct code
prints, as a test does: it did not show on the defective head, and it showed on the fix. Two paths turned such a
reproducer into a proof, both through the real `reproduce` and `decide` code below:

- an open claim, re-run on a later head (E07), proved the fix a defect and then rejected every correct head (E08);
- the same confusion on correct code proves at once.

The rule that closes them: a reproducer proves only on the head it is judged on, where its symptom shows because of
the code and the head does not show what the reproducer itself calls correct; both sides are named, by one rule of
when a side shows (`rival.side_holds`); a proven defect keeps blocking while its symptom shows, as before (E08).
"""

from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from snowball_bootstrap import reproduce, rival, secretscan, state as st
from snowball_bootstrap.container import RunResult

import test_rival_memory
from test_founder_capsule import load_launch
from test_rival_memory import CODE_JOBS, green, meta2, not_refuted, refuted_by, run_decide, state2

LIVE = json.loads((Path(__file__).resolve().parent / "fixtures" / "rival" / "polarity_87c088321252.json")
                  .read_text(encoding="utf-8"))
ATTEMPT = LIVE["attempt"]
CMD = ATTEMPT["reproducer"]["cmd"]
DEFECTIVE, FIXED, LATER = LIVE["defective_head"]["sha"], LIVE["fixed_head"]["sha"], "9" * 40


class Head:
    """A container that answers every command as one head of the brain did (the signed result's tails)."""

    def __init__(self, seen: dict):
        self.result = RunResult(seen["exit"], seen["stdout"].encode(), seen["stderr"].encode(), 1)

    def run(self, cmd, **kw):
        return self.result


# The empty control tree: `cd referee` fails before anything prints (E09).
EMPTY = Head({"exit": 2, "stdout": "", "stderr": "sh: 1: cd: can't cd to referee\n"})
ON_DEFECT, ON_FIX = Head(LIVE["defective_head"]), Head(LIVE["fixed_head"])
# A later head on which the defect is still there (the row is still reported clean) while a new per-key report prints
# the right answer beside it: a partial fix, or a richer output.
ON_PARTIAL = Head({"exit": 0, "stdout": '{"clean": true, "lines": [], "keys": [{"line": 1, "clean": false}]}\n',
                   "stderr": ""})


def two_sided(symptom: str, correct: str) -> dict:
    """The live command with both sides named (E260): the symptom on stdout and what correct code prints."""
    return {"cmd": CMD, "expect_exit": None, "expect_stdout_contains": symptom, "expect_stderr_contains": None,
            "correct_exit": None, "correct_stdout_contains": correct, "correct_stderr_contains": None}


def state_entries(state: dict) -> list[dict]:
    """What `pull` asks `reproduce` to run from the signed state (`cli.py` pull and `cmd_reproduce`)."""
    return ([{"key": e["key"], "source": "refutation", "reproducer": e["reproducer"]} for e in state["open_refutations"]]
            + [{"key": c["id"], "source": "claim", "reproducer": c["reproducer"]} for c in state["open_claims"]
               if c["reproducer"] is not None])


def judge_state(state: dict, head: str, on: Head) -> dict:
    """One code head on which the rival finds nothing: `pull` asks for the state's reproducers, `reproduce` runs them
    on the head and the empty tree, `decide` judges (`cli.py` pull, `cmd_reproduce`, `cmd_decide`)."""
    entries = state_entries(state)
    results = reproduce.run_state_reproducers(on, entries, 5, control=EMPTY)
    return run_decide(meta2("code", state, head=head, state_repro=[e["key"] for e in entries]), green(), not_refuted(),
                      [], CODE_JOBS, state_repro=results)


def judge_exit(state: dict, head: str, on: Head) -> dict:
    """An exit request on ``head``: no rival runs there (`cli.py` `needs_rival`), the state's reproducers do."""
    entries = state_entries(state)
    meta = test_rival_memory.E20OneAttemptPerArtifact.exit_meta(None, state)  # the module's: not run twice here
    meta.update(head=head, state_repro=[e["key"] for e in entries])
    return run_decide(meta, green(), None, None, {"getir": "success", "kos": "success", "yeniden": "success"},
                      state_repro=reproduce.run_state_reproducers(on, entries, 5, control=EMPTY))


def validate(rep: dict) -> dict:
    """The rival's reproducer as the MCP server checks it before it is accepted (`rival.validate_verdict`)."""
    with tempfile.TemporaryDirectory() as tmp:
        box = rival.ToolBox(Path(tmp))
        return rival.validate_verdict({"verdict": "refuted", "attempts": [dict(ATTEMPT, reproducer=rep)]},
                                      box)["attempts"][0]["reproducer"]


class E260ReproducerPolarity(unittest.TestCase):
    def claim_left_open(self) -> dict:
        """86cc8b4: the rival's attempt runs on the head it was written for, does not show, and stays open (E07)."""
        res = run_decide(meta2("code", state2(), head=DEFECTIVE), green(), refuted_by(copy.deepcopy(ATTEMPT)),
                         reproduce.run_reproducers(ON_DEFECT, [ATTEMPT], 5, control=EMPTY), CODE_JOBS)
        self.assertEqual((res["verdict"], res["reasons"]), ("accepted", []))
        claim = res["state"]["open_claims"][0]
        self.assertEqual((claim["id"], reproduce.reproducer_key(claim["reproducer"])), (LIVE["claim_id"], LIVE["key"]))
        return res["state"]

    # ------------------------------------------------------------ path 1: an open claim shows after the fix

    def test_the_fix_of_an_open_claim_whose_reproducer_expects_the_correct_output_is_accepted(self):
        """f668776 fixed the defect; the open claim's expectation (`"clean": false`) now holds, and E07 made the fix a
        proven defect; E08 then rejected every correct head after it (`refutation_still_reproduces`)."""
        state = self.claim_left_open()
        seen = []
        for head in (FIXED, LATER):
            res = judge_state(state, head, ON_FIX)
            seen.append((res["verdict"], [r["kind"] for r in res["reasons"]], len(res["state"]["open_refutations"])))
            state = res["state"]
        self.assertEqual(seen, [("accepted", [], 0), ("accepted", [], 0)])

    def test_what_a_later_head_showed_is_kept_for_the_next_rival_with_that_head(self):
        state = judge_state(self.claim_left_open(), FIXED, ON_FIX)["state"]
        claim = next(c for c in state["open_claims"] if c["id"] == LIVE["claim_id"])
        self.assertEqual((claim["first_head"], claim["rewritten"]), (DEFECTIVE, False))
        observed = claim["observed"]
        self.assertEqual((observed["head"], observed["shown"], observed["exit"], observed["stdout_tail"]),
                         (FIXED, True, 1, LIVE["fixed_head"]["stdout"]))
        ctx = rival.build_context("code", FIXED, LATER, [], "", {}, fence="f" * 16, open_claims=state["open_claims"])
        section = ctx.split("=== " + "f" * 16 + " open claims", 1)[1].split("=== " + "f" * 16, 1)[0]
        self.assertIn('"head": "' + FIXED + '"', section)
        self.assertIn('"shown": true', section)

    def test_the_rival_proves_a_regression_by_sending_the_claim_on_the_head_under_review(self):
        """What the re-run used to catch alone: a claim with the symptom's polarity that did not show where it was made
        (the code was right) shows on a later head that broke it. The re-run records it; the rival, sending it again
        with `open_claim`, has it judged on the head under review, where it proves the defect."""
        rep = two_sided('"clean": true', '"clean": false')
        claim = {"id": "0123456789ab", "claim": "a row with a secret-named key is reported clean",
                 "evidence_refs": ATTEMPT["evidence_refs"], "reproducer": rep, "observed": None,
                 "first_head": FIXED, "rewritten": False}
        quiet = judge_state(state2(open_claims=[claim]), LATER, ON_DEFECT)
        self.assertEqual((quiet["verdict"], quiet["state"]["open_claims"][0]["observed"]["shown"]), ("accepted", True))
        again = dict(copy.deepcopy(ATTEMPT), reproducer=rep, open_claim=claim["id"])
        res = run_decide(meta2("code", state2(open_claims=[claim]), head=LATER), green(), refuted_by(again),
                         reproduce.run_reproducers(ON_DEFECT, [again], 5, control=EMPTY), CODE_JOBS)
        self.assertEqual([(r["kind"], r["ref"]) for r in res["reasons"]],
                         [("refutation_reproduced", "repro:" + reproduce.reproducer_key(rep))])
        self.assertEqual((res["state"]["open_claims"], res["state"]["open_refutations"][0]["first_head"]), ([], LATER))

    # ------------------------------------------------------------ path 2: the same confusion on correct code

    def test_every_reproducer_names_what_correct_code_prints_apart_from_its_symptom(self):
        for rep, why in ((ATTEMPT["reproducer"], "needs correct_exit"),  # the live reproducer as sent: one side only
                         # a test's habit: the correct output on both sides, or inside the symptom
                         (two_sided('"clean": false', '"clean": false'), "correct side shows wherever the symptom"),
                         (two_sided('"clean": false, "lines": [1]', '"clean": false'),
                          "correct side shows wherever the symptom"),
                         (dict(two_sided('"clean": true', '"clean": false'), expect_exit=1, correct_exit=1,
                               correct_stdout_contains=None), "correct side shows wherever the symptom"),
                         # a symptom inside what correct code prints shows on correct code, and E08 would keep
                         # rejecting the fix while it does
                         (two_sided("clean", '"clean": false'), "symptom shows wherever the correct side"),
                         (dict(two_sided("clean", '"clean": false'), expect_exit=1, correct_exit=1),
                          "symptom shows wherever the correct side"),
                         # true of correct code but not instead of the symptom: it shows on the defective head too
                         (dict(two_sided('"clean": true', None), correct_exit=0), "names none of the symptom's")):
            with self.assertRaisesRegex(ValueError, why, msg=rep):
                validate(rep)
        for side in ("correct_stdout_contains", "correct_stderr_contains"):
            with self.assertRaisesRegex(ValueError, side + " must be 1-"):
                validate(dict(two_sided('"clean": true', '"clean": false'), **{side: ""}))
        with self.assertRaisesRegex(ValueError, "correct_exit must be an integer"):
            validate(dict(two_sided('"clean": true', '"clean": false'), correct_exit=True))
        self.assertEqual(validate(two_sided('"clean": true', '"clean": false')), two_sided('"clean": true', '"clean": false'))

    def test_the_validator_and_the_runner_tell_the_sides_apart_by_one_rule(self):
        """A reproducer is refused only when one side follows from the other as a whole, the way the runner reads a
        side: the same exit code on both sides is no reason when the texts tell them apart."""
        rep = dict(two_sided("value=10;", "value=1;"), expect_exit=0, correct_exit=0)
        self.assertEqual(validate(rep), rep)
        on_defect = reproduce.run_one(Head({"exit": 0, "stdout": "value=10;\n", "stderr": ""}), EMPTY, rep, 5)
        on_fix = reproduce.run_one(Head({"exit": 0, "stdout": "value=1;\n", "stderr": ""}), EMPTY, rep, 5)
        self.assertEqual([{k: r[k] for k in ("shown", "contradicted", "reproduced")} for r in (on_defect, on_fix)],
                         [{"shown": True, "contradicted": False, "reproduced": True},
                          {"shown": False, "contradicted": True, "reproduced": False}])

    def test_a_head_that_prints_what_the_reproducer_calls_correct_proves_nothing(self):
        """A wrong claim against the fixed code, both of its texts taken from what correct code prints (the symptom
        `"clean": false`, the correct side `"lines": [1]`): no rule on the two texts alone refuses it, and its symptom
        shows on f668776 and not on the empty tree. The head shows its correct side too: nothing is proven."""
        confused = dict(copy.deepcopy(ATTEMPT), reproducer=validate(two_sided('"clean": false', '"lines": [1]')))
        ran = reproduce.run_reproducers(ON_FIX, [confused], 5, control=EMPTY)
        res = run_decide(meta2("code", state2(), head=FIXED), green(), refuted_by(confused), ran, CODE_JOBS)
        self.assertEqual((res["verdict"], [r["kind"] for r in res["reasons"]], res["state"]["open_refutations"]),
                         ("accepted", [], []))
        self.assertEqual({k: ran[0].get(k) for k in ("shown", "contradicted", "tautological", "reproduced")},
                         {"shown": True, "contradicted": True, "tautological": False, "reproduced": True})
        self.assertTrue(res["state"]["open_claims"][0]["observed"]["contradicted"])
        honest = dict(copy.deepcopy(ATTEMPT), reproducer=two_sided('"clean": true', '"clean": false'))
        self.assertTrue(reproduce.run_reproducers(ON_DEFECT, [honest], 5, control=EMPTY)[0]["reproduced"])
        self.assertFalse(reproduce.run_reproducers(ON_FIX, [honest], 5, control=EMPTY)[0]["shown"])

    def test_a_proven_two_sided_defect_closes_on_the_accepted_fix(self):  # E08 with the correct side
        honest = dict(copy.deepcopy(ATTEMPT), reproducer=two_sided('"clean": true', '"clean": false'))
        proven = run_decide(meta2("code", state2(), head=DEFECTIVE), green(), refuted_by(honest),
                            reproduce.run_reproducers(ON_DEFECT, [honest], 5, control=EMPTY), CODE_JOBS)
        self.assertEqual(proven["verdict"], "rejected")
        still = judge_state(proven["state"], LATER, ON_DEFECT)
        self.assertEqual([r["kind"] for r in still["reasons"]], ["refutation_still_reproduces"])
        fixed = judge_state(still["state"], FIXED, ON_FIX)
        self.assertEqual((fixed["verdict"], fixed["state"]["open_refutations"]), ("accepted", []))

    def test_a_proven_defect_blocks_while_its_symptom_shows_whatever_else_the_head_prints(self):
        """E08 as it was before E260: a later head that still prints the symptom next to what the reproducer calls
        correct (a partial fix, a richer output) is not correct code by the reproducer's own contract, so it is
        rejected and the defect stays open, exactly as for a reproducer without a correct side. Printing the correct
        text somewhere never closes a proven defect; a head without the symptom does."""
        seen = {}
        for name, rep in (("two-sided", two_sided('"clean": true', '"clean": false')),
                          ("symptom only", {k: v for k, v in two_sided('"clean": true', None).items()
                                            if not k.startswith("correct_")})):
            attempt = dict(copy.deepcopy(ATTEMPT), reproducer=rep)
            state = run_decide(meta2("code", state2(), head=DEFECTIVE), green(), refuted_by(attempt),
                               reproduce.run_reproducers(ON_DEFECT, [attempt], 5, control=EMPTY), CODE_JOBS)["state"]
            partial = judge_state(state, LATER, ON_PARTIAL)
            fixed = judge_state(partial["state"], FIXED, ON_FIX)
            seen[name] = [(partial["verdict"], [r["kind"] for r in partial["reasons"]],
                           len(partial["state"]["open_refutations"])),
                          (fixed["verdict"], len(fixed["state"]["open_refutations"]))]
            rerun = partial["state_reproducers"][0]
            self.assertEqual((rerun["shown"], rerun["reproduced"]), (True, True), name)
        self.assertEqual(seen["two-sided"], [("rejected", ["refutation_still_reproduces"], 1), ("accepted", 0)])
        self.assertEqual(seen["two-sided"], seen["symptom only"])

    # ------------------------------------------------------------ the exit, and sending an open claim again

    def test_at_the_exit_an_open_claim_is_listed_with_what_it_showed_there_never_proven(self):
        """No rival runs on an exit head, so nothing there tells a regression from a fix: an honest claim that shows
        on the exit head and the live claim, whose reproducer expects what correct code prints, show alike. Both are
        listed with what their reproducers showed on that head, for the operator who owns the exit; neither is
        proven (`asama-0/10` #rakip: open claims are listed)."""
        exit_head = "e" * 40
        honest = {"id": "0123456789ab", "claim": "a row with a secret-named key is reported clean",
                  "evidence_refs": ATTEMPT["evidence_refs"], "reproducer": two_sided('"clean": true', '"clean": false'),
                  "observed": None, "first_head": FIXED, "rewritten": False}
        survived = [{"sha": s, "outcome": "survived"} for s in ("a" * 40, "1" * 40, "2" * 40)]
        for claim, on in ((honest, ON_DEFECT), (copy.deepcopy(LIVE["open_claim"]), ON_FIX)):
            res = judge_exit(state2(open_claims=[claim], rival_artifacts=survived), exit_head, on)
            self.assertTrue(all(r["kind"] == "exit_condition" and r["ref"].startswith("not_checked:")
                                for r in res["reasons"]), res["reasons"])  # E162 only
            self.assertEqual(res["state"]["open_refutations"], [])
            listed = res["exit"]["open_claims"]
            self.assertEqual([c["id"] for c in listed], [claim["id"]])
            self.assertEqual({k: listed[0]["observed"][k] for k in ("head", "shown", "contradicted", "tautological")},
                             {"head": exit_head, "shown": True, "contradicted": False, "tautological": False})

    def test_any_open_claim_may_be_sent_again_and_an_unchanged_one_keeps_its_rewrite(self):
        """An open claim is judged on the head under review only when the rival sends it again. A claim whose one
        rewrite is spent (`rewrite_allowed: false`) is still proven when sent again on a head that shows it; a claim
        sent again unchanged where it proves nothing keeps its rewrite, and what it showed there is recorded."""
        rep = two_sided('"clean": true', '"clean": false')
        spent = {"id": "0123456789ab", "claim": "a row with a secret-named key is reported clean",
                 "evidence_refs": ATTEMPT["evidence_refs"], "reproducer": rep, "observed": None, "first_head": FIXED,
                 "rewritten": True}
        ctx = rival.build_context("code", FIXED, LATER, [], "", {}, fence="f" * 16, open_claims=[spent])
        self.assertIn('"rewrite_allowed": false', ctx)
        again = dict(copy.deepcopy(ATTEMPT), reproducer=rep, open_claim=spent["id"])
        res = run_decide(meta2("code", state2(open_claims=[spent]), head=LATER), green(), refuted_by(again),
                         reproduce.run_reproducers(ON_DEFECT, [again], 5, control=EMPTY), CODE_JOBS)
        self.assertEqual(([r["kind"] for r in res["reasons"]], res["state"]["open_claims"]),
                         (["refutation_reproduced"], []))
        fresh = dict(spent, rewritten=False)
        res = run_decide(meta2("code", state2(open_claims=[fresh]), head=LATER), green(), refuted_by(again),
                         reproduce.run_reproducers(ON_FIX, [again], 5, control=EMPTY), CODE_JOBS)
        kept = res["state"]["open_claims"]
        self.assertEqual((res["verdict"], len(kept), kept[0]["rewritten"], kept[0]["reproducer"]),
                         ("accepted", 1, False, rep))
        self.assertEqual((kept[0]["observed"]["head"], kept[0]["observed"]["shown"]), (LATER, False))
        corrected = dict(again, reproducer=two_sided('"clean": true, "lines": []', '"clean": false'))
        res = run_decide(meta2("code", res["state"], head="8" * 40), green(), refuted_by(corrected),
                         reproduce.run_reproducers(ON_FIX, [corrected], 5, control=EMPTY), CODE_JOBS)
        self.assertEqual((res["state"]["open_claims"][0]["rewritten"], res["state"]["open_claims"][0]["reproducer"]),
                         (True, corrected["reproducer"]))

    # ------------------------------------------------------------ the live state and the rival's instructions

    def test_reproducers_kept_before_the_correct_side_load_keep_their_key_and_mean_the_same(self):
        """The live state's open claim and a proven defect written before E260 have no correct side: they load, keep
        the key the referee signed (027465767d2d46dc) and are read with their symptom alone, as before."""
        live = copy.deepcopy(LIVE["open_claim"])
        legacy = {"key": LIVE["key"], "claim": live["claim"], "evidence_refs": live["evidence_refs"],
                  "reproducer": dict(live["reproducer"]), "first_head": DEFECTIVE, "last_head": DEFECTIVE}
        st.validate(state2(open_claims=[live], open_refutations=[legacy]))
        self.assertEqual(reproduce.reproducer_key(live["reproducer"]), LIVE["key"])
        self.assertEqual(reproduce.reproducer_key(two_sided('"clean": false', '"clean": true')), LIVE["key"])
        ran = reproduce.run_one(ON_FIX, EMPTY, live["reproducer"], 5)
        self.assertEqual((ran["shown"], ran["contradicted"], ran["reproduced"]), (True, False, True))
        new = dict(live, reproducer=two_sided('"clean": true', '"clean": false'))
        st.validate(state2(open_claims=[new]))
        with self.assertRaises(st.ConfigError):
            st.validate(state2(open_claims=[dict(live, reproducer=dict(live["reproducer"], expect_stdout="x"))]))

    def test_the_rival_is_told_both_sides_and_that_proof_is_only_on_the_head_under_review(self):
        text = " ".join(rival.PROTOCOL.split())
        for phrase in ("the symptom, what THIS head prints", "what the same command prints once the code is correct",
                       "Never write the output you expect from correct code as the symptom",
                       "it names at least one exit code or stream the symptom names",
                       "neither side may follow from the other",
                       "proven only on the head under review", "the correct side does not",
                       "blocks every later head on which its symptom still shows, whatever else that head prints",
                       "proves nothing on a later one",
                       "An open claim is judged on the head under review only when you send it again",
                       "Any open claim may be sent again; rewrite_allowed says only whether a corrected reproducer "
                       "is kept"):
            self.assertIn(phrase, text)
        self.assertEqual(secretscan.scan(text), [])
        tool = next(t for t in rival.TOOLS if t["name"] == "submit_verdict")
        rep = tool["input_schema"]["properties"]["attempts"]["items"]["properties"]["reproducer"]
        self.assertEqual(set(rep["properties"]), {"cmd", "expect_exit", "expect_stdout_contains", "expect_stderr_contains",
                                                  "correct_exit", "correct_stdout_contains", "correct_stderr_contains"})
        self.assertEqual(rep["properties"]["correct_stdout_contains"]["maxLength"], rival.MAX_EXPECT_CHARS)
        self.assertIn("once the code is correct", rep["description"])


class E260PilotMetric(unittest.TestCase):
    """The pilot's line counts proven defects from the referee's judgement, not from the raw runs: a run whose head also
    shows what the reproducer calls correct proves nothing, and an open claim's showing is an observation
    (`seed/founder/launch.py`)."""

    def metric(self, result: dict, name: str = "old_refutations_still_reproducing") -> int:
        launch = load_launch()
        before, after = "a" * 40, "b" * 40

        class Fake(launch.Pilot):
            heads = [before, after]
            dispatches = 0

            def fetch_result(self):
                return dict(result, head=after, state={"last_evaluated_sha": after}) if self.dispatches else None

            def dispatch_referee(self, timeout_s):
                self.dispatches += 1
                return {"id": "1", "conclusion": "success", "url": "u"}

            def brain_head(self):
                return self.heads.pop(0)

            def ledger_rows(self, sha):
                return []

            def refresh_inputs(self):  # test_founder_capsule.VectorInputsTest's subject
                pass

            def session(self, *a):
                return {"exit": 0, "minutes": 1}

            def write(self, text):
                pass

        pilot = Fake(Path(tempfile.mkdtemp()), "o/brain", "o/referee", "target")
        pilot.idle, pilot.seed = 0, before
        args = type("Args", (), dict(model="m", max_turns=1, budget_usd=1, session_timeout=1, referee_timeout=1))
        with mock.patch.object(launch, "say"):
            pilot.cycle(1, args)
        return json.loads(pilot.metrics.read_text(encoding="utf-8").splitlines()[-1])[name]

    def test_an_open_claims_observation_is_not_a_defect_still_reproducing(self):
        shown = {"key": LIVE["claim_id"], "source": "claim", "reproduced": True, "shown": True}
        self.assertEqual(self.metric({"verdict": "accepted", "reasons": [], "warnings": [], "state_reproducers": [shown]}), 0)
        still = {"key": LIVE["key"], "source": "refutation", "reproduced": True, "shown": True}
        self.assertEqual(self.metric({"verdict": "rejected", "warnings": [], "state_reproducers": [still, shown],
                                      "reasons": [{"kind": "refutation_still_reproduces", "ref": "repro:" + LIVE["key"]}]}),
                         1)

    def test_a_run_whose_head_shows_the_correct_side_is_not_a_proven_defect(self):
        both = {"attempt_index": 0, "key": LIVE["key"], "reproduced": True, "contradicted": True, "tautological": False}
        self.assertEqual(self.metric({"verdict": "accepted", "reasons": [], "warnings": [], "reproducers": [both]},
                                     "reproduced"), 0)
        alone = dict(both, contradicted=False)
        self.assertEqual(self.metric({"verdict": "rejected", "warnings": [], "reproducers": [alone],
                                      "reasons": [{"kind": "refutation_reproduced", "ref": "repro:" + LIVE["key"]}]},
                                     "reproduced"), 1)


if __name__ == "__main__":
    unittest.main()
