"""The self-improvement scorecard (`seed/founder/scorecard.py`, E310): built from signed and hashed records, refused
on a broken chain or a changed cache, ordered by the referee's artifacts, publishing counts only, and never writing
outside its folder. The world here is synthetic: no target, no live repository."""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import io
import json
import os
import random
import re
import stat
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from snowball_bootstrap import exitchecks
from snowball_bootstrap.canon import row_hash

ROOT = Path(__file__).resolve().parents[3]
FOUNDER = ROOT / "seed" / "founder"
BRAIN, REFEREE = "owner/brain", "owner/referee"
TARGET = "Güneş-İskele"  # a planted target name: it must never reach the public card
CLAIM = "CLAIM-TEXT-7f3a"  # a planted claim, ledger summary and idea text
ZERO = "0" * 64


def load(name: str):
    spec = importlib.util.spec_from_file_location(f"founder_{name}", FOUNDER / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sha(n: int) -> str:
    return f"{n:040x}"


def chain(rows: list[dict]) -> str:
    prev, out = ZERO, []
    for i, row in enumerate(rows, start=1):
        row = dict(row, row_id=f"f{i}", prev_hash=prev)
        row["row_hash"] = row_hash(row)
        prev = row["row_hash"]
        out.append(json.dumps(row, ensure_ascii=False, sort_keys=True))
    return "\n".join(out) + "\n"


LEDGER = chain([
    {"ts": "2027-01-01T00:00:00Z", "part": "founder", "kind": "session_start", "payload": {"summary": "start"}},
    {"ts": "2020-01-01T00:00:00Z", "part": "founder", "kind": "decision",
     "payload": {"summary": f"{CLAIM} about {TARGET}"}},
    {"ts": "2026-10-30T00:00:00Z", "part": "founder", "kind": f"learning about {TARGET}", "payload": {}},
])


def result(head: str, base: str, kind: str, verdict: str, reasons=(), evaluated: bool = True, state=None,
           **extra) -> dict:
    state = {"last_evaluated_sha": head if evaluated else "f" * 40, "rival_artifacts": [], "open_refutations": [],
             "open_claims": [], "stage_spend_usd_micros": 1_500_000, **(state or {})}
    out = {"schema": "snowball-bootstrap-result/1", "head": head, "base": base, "kind": kind, "verdict": verdict,
           "reasons": [{"kind": k, "ref": r, "detail": f"{CLAIM} {TARGET}"} for k, r in reasons],
           "warnings": [], "waived": [], "learning": {"repeat_events": 0, "repeated": [], "not_learning": []},
           "module_less": [], "state_reproducers": [], "state": state,
           "rival": {"attempts": [{"claim": f"{CLAIM} in {TARGET}"}]}}
    out.update(extra)
    return out


SEED = sha(100)
C1, C2, C3, C4, C5, C6 = (sha(n) for n in range(1, 7))
MANIFESTS = {C1: [1], C2: [1, 2], C3: [1, 2], C4: [1, 2], C5: [1, 2], C6: [1, 2, 3]}  # the seed commit has none
def rerun(key: str, reproduced: bool, source: str = "refutation") -> dict:
    """A reproducer the signed state kept, run again on a later head (`state_reproducers`)."""
    return {"key": key, "source": source, "reproduced": reproduced}


RESULTS = [  # in the order the referee signed them
    result(sha(99), SEED, "spec", "frozen"),
    result(C1, SEED, "code", "accepted", module_less=[{"mf": 1, "test_id": "T1", "stayed_green": False}]),
    # Proven defect j (proven before this record) still shows here, beside a failing test: one push, one rejection.
    result(C2, C1, "code", "rejected", [("test_failed", "x"), ("refutation_still_reproduces", "repro:j")],
           state_reproducers=[rerun("j", True)]),
    result(C3, C1, "code", "rejected", [("rival_missing", "")],  # the rival's failure, not the Founder's
           state_reproducers=[rerun("j", False)]),
    result(C4, C1, "code", "accepted", module_less=[{"mf": 2, "test_id": "T2", "stayed_green": False},
                                                    {"mf": 2, "test_id": "T3", "stayed_green": False}],
           state_reproducers=[rerun("j", False)]),  # accepted where j no longer shows: j is closed, never run again
    result(sha(98), C4, "seed_update", "noop"),
    # A work push, flagged below: proven defect k still shows; an open claim's reproducer proves nothing (E260).
    result(C5, C4, "code", "rejected", [("refutation_still_reproduces", "repro:k")],
           state_reproducers=[rerun("k", True), rerun("c1", True, source="claim")],
           learning={"repeat_events": 1, "repeated": ["refutation:k"], "not_learning": []}),
    result(C6, C4, "code", "rejected", [("infra", "kos:docker")], evaluated=False,  # an outage: not judged
           state_reproducers=[rerun("k", True)]),
    result(C6, C4, "code", "accepted", module_less=[{"mf": 3, "test_id": "T4", "stayed_green": True}],
           state_reproducers=[rerun("k", False)],
           learning={"repeat_events": 1, "repeated": [], "not_learning": []},
           state={"stage_spend_usd_micros": 2_750_000, "open_claims": [{"id": "c1"}],  # the latest state
                  "rival_artifacts": [{"sha": C1, "outcome": "survived"}, {"sha": C2, "outcome": "refuted"},
                                      {"sha": C6, "outcome": "survived"}]}),
]
EXCLUSIONS = {"entries": [{"id": "E901", "head": C5}, {"id": "E902", "unit": "MF1"}]}
METRICS = [{"stamp": "20261030T000000Z", "cost_usd": 2.5, "minutes": 10.0, "reports_new": [f"{CLAIM} {TARGET}"]},
           {"stamp": "20261030T010000Z", "cost_usd": None, "minutes": 3.0}]
IDEAS = ("# Fikir ölçütü\n\n| # | Fikir | Kimin | Not | Sistem önerdi mi |\n|---|---|---|---|---|\n"
         f"| 1 | {CLAIM} {TARGET} | sahip | 2026 | — |\n| 2 | başka | sahip | 2026 | **evet**, döngü 3 |\n\n"
         "| Boşluk | Sistem buldu mu | Kanıt |\n|---|---|---|\n| E1 | **evet**, 2026 | f1 |\n| E2 | henüz | — |\n")


def zipped(res: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("result.json", json.dumps(res))
        zf.writestr("result.json.sigstore.json", "{}")
    return buf.getvalue()


MAIN = sha(77)  # the brain's main has moved past every judged head: one more row in its ledger
LATER_LEDGER = chain([json.loads(line) for line in LEDGER.splitlines()]
                     + [{"ts": "2026-10-31T00:00:00Z", "part": "founder", "kind": "decision", "payload": {}}])


class FakeGitHub:
    """The referee's artifacts and the brain's files, served the way `gh api` serves them; every path is recorded.
    The ledger is served at the last result's head and, one row longer, at the brain's main."""

    def __init__(self, sc, results=RESULTS, ledger=LEDGER):
        self.sc, self.calls = sc, []
        self.ledger, self.last_head = ledger, results[-1]["head"]
        self.zips = {1000 + i: zipped(r) for i, r in enumerate(results)}
        self.arts = [{"id": 1000 + i, "digest": "sha256:" + hashlib.sha256(self.zips[1000 + i]).hexdigest(),
                      "created_at": f"2026-10-30T{i:02d}:00:00Z", "expired": False,
                      "workflow_run": {"id": 500 + i, "head_sha": r["head"], "head_branch": "main"}}
                     for i, r in enumerate(results)]

    def __call__(self, path: str, raw: bool = False) -> bytes:
        self.calls.append(path)
        if path.startswith(f"repos/{REFEREE}/actions/artifacts?"):
            return json.dumps({"artifacts": self.arts}).encode()
        m = re.fullmatch(rf"repos/{REFEREE}/actions/artifacts/(\d+)/zip", path)
        if m:
            return self.zips[int(m.group(1))]
        if path == f"repos/{BRAIN}/commits/main":
            return json.dumps({"sha": MAIN}).encode()
        if path == f"repos/{BRAIN}/contents/founder-ledger.jsonl?ref={self.last_head}":
            return self.ledger.encode()
        if path == f"repos/{BRAIN}/contents/founder-ledger.jsonl?ref={MAIN}":
            return LATER_LEDGER.encode()
        m = re.fullmatch(rf"repos/{BRAIN}/contents/snowball-tests.json\?ref=([0-9a-f]{{40}})", path)
        if m and m.group(1) in MANIFESTS:
            return json.dumps({"tests": [], "done_mf": MANIFESTS[m.group(1)], "lockfiles": []}).encode()
        raise self.sc.NotFound(path)


def signed(results: list[dict]) -> list[dict]:
    """Results as the cache hands them to `build`, in the order given."""
    return [{"artifact": {"artifact_id": 1000 + i, "digest": f"sha256:{i:064x}", "created_at": f"2026-10-30T{i:02d}:00Z",
                          "run_id": 500 + i, "files": {"result.json": f"{i:064x}"}}, "result": r}
            for i, r in enumerate(results)]


def inputs(**changes) -> dict:
    base = {"results": signed(RESULTS), "ledger_at": C6, "ledger": LEDGER, "manifests": dict(MANIFESTS, **{SEED: []}),
            "metrics": METRICS, "ideas": IDEAS, "exclusions": EXCLUSIONS, "gaps": []}
    base.update(changes)
    return base


class BuildTest(unittest.TestCase):
    def setUp(self):
        self.sc = load("scorecard")
        self.model = self.sc.build(inputs())
        self.units = {u["mf"]: u for u in self.model["public"]["units"]}

    def test_a_broken_chain_refuses_the_card(self):
        lines = LEDGER.splitlines()
        edited = json.loads(lines[1])
        edited["payload"]["summary"] = "rewritten"
        for ledger, why in ((LEDGER.replace('"start"', '"restart"'), "row_hash"),
                            ("\n".join([lines[0], lines[2]]), "prev_hash"),
                            ("\n".join([lines[0], json.dumps(edited), lines[2]]), "row_hash"),
                            (lines[0] + "\nnot json\n", "unreadable")):
            with self.assertRaises(self.sc.ScorecardError) as caught:
                self.sc.build(inputs(ledger=ledger))
            self.assertIn(why, str(caught.exception))

    def test_units_come_from_the_manifests_at_head_and_base(self):
        self.assertEqual(sorted(self.units), [1, 2, 3])
        mf2 = self.units[2]
        self.assertEqual((mf2["attempts"], mf2["founder_rejections"], mf2["other_rejections"], mf2["first"]),
                         (3, 1, 1, False))  # a Founder's rejection, the rival's failure, then accepted
        self.assertEqual((self.units[3]["attempts"], self.units[3]["first"]), (1, True))  # the outage is not judged
        self.assertEqual([u["segment"] for u in self.model["public"]["units"]], [0, 0, 1])  # a seed epoch between
        pushes = self.model["public"]["pushes"]
        self.assertEqual((pushes["judged"], pushes["by_kind"], pushes["work_pushes"]), (7, {"code": 6, "spec": 1}, 1))
        self.assertEqual(self.model["public"]["autonomy"],
                         {"seed_epochs": 1, "waived_refutations": 0, "unevaluated_runs": 1, "rival_side_retries": 0})

    def test_owners_come_from_the_referees_rule(self):
        with mock.patch.object(self.sc, "counts_against_founder", wraps=self.sc.counts_against_founder) as rule:
            model = self.sc.build(inputs())
        self.assertIn(mock.call({"kind": "rival_missing", "ref": ""}), rule.call_args_list)
        self.assertEqual(model["public"]["pushes"]["founder_rejected"]["referee"]["x"], 2)
        with mock.patch.object(self.sc, "counts_against_founder", return_value=False):
            self.assertEqual(self.sc.build(inputs())["public"]["pushes"]["founder_rejected"]["referee"]["x"], 0)

    def test_exclusions_adjust_beside_the_referee_column(self):
        public = self.model["public"]
        self.assertEqual((self.units[1]["first"], self.units[1]["first_adjusted"], self.units[1]["flags"]),
                         (True, None, ["E902"]))
        fr = public["pushes"]["founder_rejected"]
        self.assertEqual((fr["referee"]["x"], fr["referee"]["n"], fr["adjusted"]["x"], fr["adjusted"]["n"]),
                         (2, 6, 1, 5))
        self.assertEqual(public["repeat"], {"events": 1, "events_adjusted": 0, "not_learning_runs": 0})
        self.assertEqual(public["inputs"]["exclusions"], [{"id": "E901", "on": C5}, {"id": "E902", "on": "MF1"}])

    def test_proven_defects_are_counted_as_defects_until_they_close(self):
        # j still shows on C2, k only on the flagged C5; the claim's reproducer and the outage's run are not counted.
        self.assertEqual(self.model["public"]["proven_defects"],
                         {"defects": 2, "reruns": 5, "reproduced_again": 2, "reproduced_again_adjusted": 1,
                          "retention": "UNMEASURABLE"})
        self.assertEqual(self.model["public"]["module_less"], {"runs": 4, "mfs": 3, "green": 1})  # MF2 has two tests
        text = self.sc.render_public(self.model["public"])
        self.assertIn("| Kalıcılık: kabul edilmiş işte kapanmış kusurun geri dönmesi | ölçülemez", text)
        self.assertNotIn("kalıcılık, tekrar", text)  # nothing on the card is called retention but the gap itself
        verbs = {line.split(" | ")[0]: line for line in text.splitlines() if line.startswith("| ")}
        self.assertTrue(verbs["| yanlışı yanlış bilir"].endswith("| ölçülemez |"), verbs["| yanlışı yanlış bilir"])

    def test_the_latest_state_gives_the_rival_counts_and_spend(self):
        self.assertEqual(self.model["public"]["rival"], {"survived": 2, "refuted": 1, "open_refutations": 0,
                                                         "open_claims": 1, "recall": "UNMEASURABLE"})
        self.assertEqual(self.model["private"]["cost"]["rival_usd"], "2.75")

    def test_the_ledger_must_be_read_at_the_last_results_head(self):
        for at in (MAIN, C5):
            with self.assertRaises(self.sc.ScorecardError) as caught:
                self.sc.build(inputs(ledger_at=at))
            self.assertIn("two record points", str(caught.exception))
        self.assertEqual(self.model["public"]["as_of"]["last_run"]["head"], C6)

    def test_missing_data_is_a_gap_never_zero(self):
        private = self.sc.build(inputs(metrics=None, ideas=None))["private"]
        self.assertEqual(private["cost"]["founder"], "GAP: pilot-metrics.jsonl not read")
        self.assertIsNone(private["discovery"])
        founder = self.model["private"]["cost"]["founder"]
        self.assertEqual((founder["sessions"], founder["sessions_without_cost"], founder["usd_total"]), (2, 1, "2.50"))
        self.assertEqual(self.model["private"]["discovery"],
                         {"ideas_proposed": 1, "ideas_held": 2, "gaps_found": 1, "gaps_held": 2})

    def test_clopper_pearson_matches_tohum_19(self):
        lo, hi = self.sc.clopper_pearson(3, 5)
        self.assertEqual((f"{lo:.2f}", f"{hi:.2f}"), ("0.15", "0.95"))
        self.assertEqual(self.sc.clopper_pearson(0, 10)[0], 0.0)
        self.assertEqual(self.sc.clopper_pearson(10, 10)[1], 1.0)
        self.assertEqual(f"{self.sc.clopper_pearson(0, 10)[1]:.4f}", "0.3085")  # 1 - 0.025 ** (1 / 10)
        self.assertEqual(self.sc.share(3, 4), {"x": 3, "n": 4, "verdict": "UNMEASURABLE"})
        self.assertEqual(self.sc.share(3, 5), {"x": 3, "n": 5, "ci95": ["0.15", "0.95"]})
        with self.assertRaises(ValueError):
            self.sc.clopper_pearson(3, 0)

    def test_order_comes_from_the_artifacts_not_from_the_input_or_the_ledger(self):
        shuffled = inputs()
        random.Random(4).shuffle(shuffled["results"])
        self.assertEqual(self.sc.build(shuffled), self.model)
        late = inputs(ledger_at=C3)  # the same results signed in another order: MF2's rival failure after its
        late["results"][3]["artifact"]["created_at"] = "2026-10-30T23:00Z"  # acceptance, and last
        self.assertEqual(self.sc.build(late)["public"]["units"][1]["attempts"], 2)

    def test_the_same_inputs_give_the_same_bytes(self):
        again = self.sc.build(copy.deepcopy(inputs()))
        self.assertEqual(self.sc.render_public(again["public"]), self.sc.render_public(self.model["public"]))
        self.assertEqual(self.sc.render_private(again), self.sc.render_private(self.model))

    def test_the_public_card_says_unproved_first_and_publishes_counts_only(self):
        public = self.model["public"]
        text = self.sc.render_public(public) + json.dumps(public, ensure_ascii=False)
        self.assertIn("**Kendini geliştirdiği kanıtlandı mı: hayır.**", text.splitlines()[4])
        self.assertNotIn(exitchecks.fold(TARGET), exitchecks.fold(text))  # in no spelling the seed folds alike
        for planted in (CLAIM, "learning about"):  # claims, ledger text, a free-text kind
            self.assertNotIn(planted, text)
        self.assertEqual(public["ledger_kinds"], {"decision": 1, "diğer": 1, "session_start": 1})
        self.assertNotIn("cost", json.dumps(public))
        self.assertEqual(public["exam"], {"status": "not_run", "register": "E317"})


class FlaggedFirstAttemptTest(unittest.TestCase):
    """A flagged push that is a unit's first attempt: the referee column counts it, the adjusted column reads the
    unit at its first unflagged attempt, and the unit stays in the segment of its first attempt (the live card's MF16:
    first attempt the blind push d0dc433, E248)."""

    D1, D2, D3, D4 = (sha(n) for n in range(11, 15))

    def setUp(self):
        self.sc = load("scorecard")
        d1, d2, d3, d4 = self.D1, self.D2, self.D3, self.D4
        results = [result(d1, SEED, "code", "accepted"),
                   result(d2, d1, "code", "rejected", [("test_failed", "x")]),  # flagged: MF2's first attempt
                   result(sha(97), d1, "seed_update", "noop"),
                   result(d3, d1, "code", "accepted"),  # MF2 accepted, in the next segment
                   result(d4, d3, "code", "rejected", [("test_failed", "y")])]  # flagged: MF3's only attempt
        model = self.sc.build(inputs(results=signed(results), ledger_at=d4,
                                     manifests={SEED: [], d1: [1], d2: [1, 2], d3: [1, 2], d4: [1, 2, 3]},
                                     exclusions={"entries": [{"id": "E903", "head": d2}, {"id": "E904", "head": d4}]}))
        self.public = model["public"]
        self.units = {u["mf"]: u for u in self.public["units"]}

    def test_the_adjusted_column_reads_the_first_unflagged_attempt(self):
        mf2 = self.units[2]
        self.assertEqual((mf2["first"], mf2["first_adjusted"], mf2["flags"], mf2["attempts"]),
                         (False, True, ["E903"], 2))
        self.assertEqual((self.units[3]["first"], self.units[3]["first_adjusted"]), (False, None))  # no unflagged try
        fa = self.public["first_attempt"]["all"]
        self.assertEqual((fa["referee"]["x"], fa["referee"]["n"], fa["adjusted"]["x"], fa["adjusted"]["n"]),
                         (1, 3, 2, 2))

    def test_a_unit_belongs_to_the_segment_of_its_first_attempt(self):
        self.assertEqual({mf: u["segment"] for mf, u in self.units.items()}, {1: 0, 2: 0, 3: 1})
        segments = {s["segment"]: (s["referee"]["x"], s["referee"]["n"], s["adjusted"]["x"], s["adjusted"]["n"])
                    for s in self.public["first_attempt"]["segments"]}
        self.assertEqual(segments, {0: (1, 2, 2, 2), 1: (0, 1, 0, 0)})


class FetchTest(unittest.TestCase):
    def setUp(self):
        self.sc = load("scorecard")
        self.work = Path(tempfile.mkdtemp())
        (self.work / "pilot-metrics.jsonl").write_text("".join(json.dumps(m) + "\n" for m in METRICS), encoding="utf-8")
        (self.work / "fikir-olcutu.md").write_text(IDEAS, encoding="utf-8")
        self.github = FakeGitHub(self.sc)

    def tearDown(self):
        for path in self.work.rglob("*"):
            if path.is_file():
                os.chmod(path, stat.S_IWRITE | stat.S_IREAD)

    def snapshot(self) -> dict[str, bytes]:
        return {p.relative_to(self.work).as_posix(): p.read_bytes() for p in self.work.rglob("*") if p.is_file()}

    def test_writes_only_its_own_folder_and_the_public_card(self):
        for name in ("pilot-metrics.jsonl", "fikir-olcutu.md"):
            os.chmod(self.work / name, stat.S_IREAD)  # opened for writing, either would fail here
        before = self.snapshot()
        self.sc.update(self.work, BRAIN, REFEREE, public=self.work / "pub" / "karne", get=self.github)
        after = self.snapshot()
        changed = {p for p in after if before.get(p) != after[p]}
        self.assertTrue(changed)
        self.assertEqual({p for p in changed if not p.startswith(("scorecard/", "pub/karne."))}, set())
        self.assertEqual({p for p in changed if p.startswith("pub/")}, {"pub/karne.json", "pub/karne.md"})
        self.assertEqual({p: after[p] for p in before}, before)

    def test_the_cache_is_append_only_and_checked(self):
        self.sc.update(self.work, BRAIN, REFEREE, get=self.github)
        zips = [c for c in self.github.calls if c.endswith("/zip")]
        self.assertEqual(len(zips), len(RESULTS))
        index = (self.work / "scorecard" / "results" / "index.jsonl").read_text(encoding="utf-8")
        again = FakeGitHub(self.sc)
        self.sc.update(self.work, BRAIN, REFEREE, get=again)
        self.assertEqual([c for c in again.calls if c.endswith("/zip")], [])  # nothing downloaded twice
        self.assertEqual((self.work / "scorecard" / "results" / "index.jsonl").read_text(encoding="utf-8"), index)
        self.assertEqual([c for c in again.calls if "snowball-tests.json" in c], [])  # manifests are cached too
        cached = self.work / "scorecard" / "results" / "1001" / "result.json"
        cached.write_text(cached.read_text(encoding="utf-8").replace("accepted", "rejected"), encoding="utf-8")
        with self.assertRaises(self.sc.ScorecardError):
            self.sc.update(self.work, BRAIN, REFEREE, get=FakeGitHub(self.sc))

    def test_a_zip_that_does_not_match_its_digest_is_refused(self):
        self.github.zips[1002] = zipped(result(C2, C1, "code", "accepted"))
        with self.assertRaises(self.sc.ScorecardError) as caught:
            self.sc.update(self.work, BRAIN, REFEREE, get=self.github)
        self.assertIn("digest", str(caught.exception))

    def test_an_artifact_without_a_digest_is_refused_not_cached_unchecked(self):
        self.github.arts[2]["digest"] = None
        with self.assertRaises(self.sc.ScorecardError) as caught:
            self.sc.update(self.work, BRAIN, REFEREE, get=self.github)
        self.assertIn("none given", str(caught.exception))
        self.assertFalse((self.work / "scorecard" / "results" / "1002").exists())

    def test_only_main_artifacts_are_read_and_an_expired_one_is_a_gap(self):
        other = {"id": 2000, "digest": "sha256:" + hashlib.sha256(self.github.zips[1001]).hexdigest(),
                 "created_at": "2026-10-30T23:00:00Z", "expired": False,
                 "workflow_run": {"id": 900, "head_sha": C1, "head_branch": "feature"}}  # a branch run's state
        self.github.zips[2000] = self.github.zips[1001]
        expired = {"id": 2001, "digest": None, "created_at": "2026-10-30T23:30:00Z", "expired": True,
                   "workflow_run": {"id": 901, "head_sha": C6, "head_branch": "main"}}
        self.github.arts += [other, expired]
        model = self.sc.update(self.work, BRAIN, REFEREE, public=self.work / "pub" / "karne", get=self.github)
        self.assertEqual([c for c in self.github.calls if c.endswith(("/2000/zip", "/2001/zip"))], [])
        self.assertEqual(model["public"]["as_of"]["results"], len(RESULTS))
        self.assertEqual(model["public"]["gaps"][0], "artefakt 2001 önbelleğe alınmadan süresi doldu")
        self.assertIn("artefakt 2001 önbelleğe alınmadan", (self.work / "pub" / "karne.md").read_text(encoding="utf-8"))

    def test_the_ledger_is_read_at_the_head_of_the_last_result(self):
        model = self.sc.update(self.work, BRAIN, REFEREE, get=self.github)
        self.assertIn(f"repos/{BRAIN}/contents/founder-ledger.jsonl?ref={C6}", self.github.calls)
        self.assertNotIn(f"repos/{BRAIN}/commits/main", self.github.calls)  # main has one more row (LATER_LEDGER)
        as_of = model["public"]["as_of"]
        self.assertEqual((as_of["ledger_rows"], as_of["last_run"]["head"]), (3, C6))

    def test_the_live_shape_round_trips(self):
        model = self.sc.update(self.work, BRAIN, REFEREE, public=self.work / "pub" / "karne", get=self.github)
        self.assertEqual(model["public"]["units"], units_from_inputs())
        written = json.loads((self.work / "pub" / "karne.json").read_text(encoding="utf-8"))
        self.assertEqual((self.work / "pub" / "karne.md").read_text(encoding="utf-8"), self.sc.render_public(written))

    def test_gh_is_read_with_get_only(self):
        with mock.patch.object(self.sc.subprocess, "run",
                               return_value=subprocess.CompletedProcess([], 0, b"{}", b"")) as run:
            self.sc.gh_get("repos/x/y")
            self.sc.gh_get("repos/x/y/contents/z", True)
        for call in run.call_args_list:
            argv = call.args[0]
            self.assertEqual(argv[:4], ["gh", "api", "--method", "GET"])
            self.assertFalse({"-f", "-F", "--field", "--raw-field", "--input"} & set(argv))
        with mock.patch.object(self.sc.subprocess, "run",
                               return_value=subprocess.CompletedProcess([], 1, b"", b"gh: Not Found (HTTP 404)")):
            with self.assertRaises(self.sc.NotFound):
                self.sc.gh_get("repos/x/y")


def units_from_inputs() -> list[dict]:
    sc = load("scorecard")
    built = sc.build(dict(inputs(), exclusions=json.loads((FOUNDER / "scorecard_exclusions.json").read_text("utf-8"))))
    return built["public"]["units"]


class CommittedCardTest(unittest.TestCase):
    """docs/karne.md is generated: it is what the code renders from docs/karne.json, with the code's definitions."""

    def setUp(self):
        self.sc = load("scorecard")
        self.card = json.loads((ROOT / "docs" / "karne.json").read_text(encoding="utf-8"))

    def test_the_page_is_rendered_from_its_json_with_the_current_definitions(self):
        self.assertEqual(self.card["definitions_sha256"], self.sc.DEFINITIONS_SHA256,
                         "the definitions changed: regenerate docs/karne with seed/founder/scorecard.py")
        page = (ROOT / "docs" / "karne.md").read_bytes().replace(b"\r\n", b"\n").decode("utf-8")
        self.assertTrue(page == self.sc.render_public(self.card), "docs/karne.md differs from its json: regenerate it")

    def test_its_exclusions_are_the_files_and_each_names_a_register_row(self):
        entries = json.loads((FOUNDER / "scorecard_exclusions.json").read_text(encoding="utf-8"))["entries"]
        self.assertEqual(self.card["inputs"]["exclusions"], [{"id": e["id"], "on": e.get("head", e.get("unit"))}
                                                             for e in entries])
        register = (ROOT / "docs" / "eksik-kaydi.md").read_text(encoding="utf-8")
        for e in entries:
            self.assertRegex(register, rf"(?m)^\| {e['id']} \|", e["id"])


class OutsideTheLoopTest(unittest.TestCase):
    """The debate's decision (E310): the card is an operator command, never part of the launcher's loop, and the
    Founder's capsule never sees it."""

    def test_the_launcher_does_not_run_the_scorecard(self):
        self.assertNotIn("scorecard", (FOUNDER / "launch.py").read_text(encoding="utf-8"))

    def test_the_capsule_mounts_nothing_of_the_scorecards_folder(self):
        launch = load("launch")
        work = Path(tempfile.mkdtemp())
        pilot = launch.Pilot(work, BRAIN, REFEREE, "target")
        pilot.seed = "a" * 40
        argv = pilot.capsule_argv("20261030T000000Z", "claude-opus-5-5", 200, 50)
        sources = [Path(part.split("=", 1)[1]) for arg in argv if arg.startswith("type=bind")
                   for part in arg.split(",") if part.startswith("src=")]
        self.assertTrue(sources)
        for src in sources:
            self.assertNotEqual(src, work)
            self.assertNotIn(src, (work / "scorecard").parents)
            self.assertFalse(str(src).startswith(str(work / "scorecard")))


if __name__ == "__main__":
    unittest.main()
