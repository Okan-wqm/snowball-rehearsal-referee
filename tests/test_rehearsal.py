"""(B)'s flow rehearsal (asama-0/08's order of cycles, 10a): ``loop.job``'s five jobs run after run, from no heads, on
one in-process world, until the flow stalls; the test states where it stalls today.

**The world.** A toy (``t1``) and a copy (``c1``) in ``setup/summary.json``'s ``targets[]`` (toy first), each an
in-process GitHub (``fake_github``, with git's object ids) holding only ``main``; the brain's commit (``referee/``,
each target's ``units.json``, the toy's candidates ``good`` and ``breaks`` with their ``expect.json`` and the copy's
``good``) in ``git_store``'s fake ``git``, which also answers every object and ``ls-remote`` of both GitHubs as they
are at the run's start; one fake Rekor that the root signer of ``yaz`` writes each signed root's entry into, so the
next run's D1 reads it back; the checkout with ``policy.json``, ``bootstrap.json``, ``setup/imports.jsonl``,
``setup/security-ledger.jsonl`` and ``DRILL_SEED`` set in ``yaz``; either no ``DRILL_FIXTURES`` (the operator has not
written the live drill fixtures secret, tohum/26f) or fixtures of this test's (``DRILL_PATCHES``, bound to the
checkout's counter, with the sentinel those patches turn red, ``test_loop_write.SENTINEL_UNITS``). The fake runner runs the
tree's Python (``test_loop_kos.RedAs``), the fake ``claude`` answers the canary.

**A run** (``Flow.run``) is the workflow's order with each job on its own runner: ``cek``; its ``out/pulled`` copied
whole as the ``in/pulled`` of ``getir``, ``kos``, ``cagir`` and ``yaz``; ``getir``'s ``out/deps`` as ``kos``'s
``in/deps``; ``kos``'s ``out/results`` and ``cagir``'s ``out/response`` as ``yaz``'s. A job that is not ``ok`` ends
the run there. The run's record (``Flow.record``) keeps per target what decides the next run: genesis, the merge
and each candidate's reasons, the sentinel's verdict, the drill's action, the gate; and the copy's waiting.

**The stall** is the first run whose record equals the one before it (the flow repeats itself: nothing the next run
reads has moved but the cycle's own rows), or a job that is not ``ok``; **the end** is a run with no job stopped whose
``yaz`` judged a target's PASS row ``PASS`` (``ended``; that run writes the row). Neither within ``MAX_RUNS`` runs
fails the test (a drill that keeps passing never repeats a record: its phases alternate). ``Rehearsal`` asserts every
run's record up to it, so a change that moves (B) one step, or breaks an earlier one, changes this test in the same
push. Today (B) stalls without the fixtures, with the gate closed on ``#geri-alma`` alone, and with patches on the
file a merged candidate changed (a set 26f's producer refuses), on every cause; with the fixtures of the three causes
it ends: the toy's gate opens, the copy's genesis runs and the toy's PASS row is written. Each run after the genesis
also checks that D1 verified the state the run before wrote. The checkout holds (A)'s result where the counter's
import names it (``setup/results/<result_sha256>.json``, tohum/26c, 29s), which the PASS judgement reads.

Out of scope, stated: the real runner, git, GitHub, Rekor, Sigstore and model (the jobs' own tests and 10a's live
run); the toy fixture of ``tests/fixtures/toy-repo`` (node; the fake runner runs Python only, so the world's tree is
``test_loop_kos.TREE``); the copy's cycles beyond its genesis and first sentinel, which the end comes after.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import os
import re
import shutil
import sys
import unittest

REFEREE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REFEREE)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import activation_world as AW  # noqa: E402
import fake_claude  # noqa: E402
import git_store as S  # noqa: E402
import test_accepted as TA  # noqa: E402
import test_loop_cagir  # noqa: E402
import yaz_world as YW  # noqa: E402
from fake_github import FakeGitHub  # noqa: E402
from ledger import chain as CH  # noqa: E402
from loop import accepted as A  # noqa: E402
from loop import job as J  # noqa: E402
from loop import treehash as T  # noqa: E402
from loop_inputs_world import BOOTSTRAP, install_sigstore, write_bootstrap  # noqa: E402
from profile_tree import writable_base, write_tree  # noqa: E402
from target import branches as B  # noqa: E402
from test_kos import BREAKS_TEST, GOOD, diff, recipe  # noqa: E402
from test_loop_cek import POLICY, install_listing_git  # noqa: E402
from test_loop_kos import FINDING, TREE, RedAs  # noqa: E402
from test_loop_write import DRILL_PATCHES as D8_PATCHES, SENTINEL_PY, SENTINEL_UNITS, drill_catalog, fixtures_value  # noqa: E402,E501
from test_pass_row import RD_BUILD, RD_LINT, RD_TEST  # noqa: E402
from test_rekor import entry_for  # noqa: E402
from harness import pass_row as PR  # noqa: E402
from harness import revert_drill as RD  # noqa: E402
from loop import drill as DR  # noqa: E402
from status import exit_b as EB  # noqa: E402

REFEREE_REPO = "o/referee"
TARGETS = (("t1", "toy", "o/toy"), ("c1", "copy", "o/copy"))
MERGE = {"decision": "merge"}
CANDIDATES = {"t1": {"good": (GOOD, MERGE), "breaks": (BREAKS_TEST, {"decision": "reject", "reason": "tests_red"})},
              "c1": {"good": (GOOD, MERGE)}}
# The drill's patches (``test_loop_write.D8``'s, moved to line 2): each turns the sentinel red, RD_LINT also adds a
# ``var`` line. They change ``const b``, a line ``good`` leaves as it was, so they apply after its merge.
# RD_BUILD is the set's build break: the same red on a line that does not parse (PARSE_ERROR, a fatal lint message).
DRILL_PATCHES = {RD_TEST: diff("pkg/a.js", ["const b = 2;"], ["const b = 2; // SENTINEL_RED"], start=2),
                 RD_LINT: diff("pkg/a.js", ["const b = 2;"], ["const b = 2; // SENTINEL_RED", "var z = 2;"], start=2),
                 RD_BUILD: diff("pkg/a.js", ["const b = 2;"], ["const b = 2; // SENTINEL_RED PARSE_ERROR"], start=2)}
DRILL_CAUSES = {RD_TEST: "test_regression", RD_LINT: "lint_regression", RD_BUILD: "build_break"}
SHA40 = re.compile(r"\b[0-9a-f]{40}\b")
LISTED = {"brain/state": B.STATE, "brain/integration": B.INTEGRATION, "main": "main"}


class RekorSigner:
    """``yaz``'s root signer: each payload (a root's preimage, ``ledger.anchor``) gets a Rekor entry recording its
    sha256, the root (``test_rekor.entry_for``), put into ``rekor`` where the next run's D1 reads it; the bundle it
    answers names the entry and is no Sigstore bundle."""

    def __init__(self, rekor: dict, identity: str) -> None:
        self.rekor, self.identity = rekor, identity

    def sign(self, payload: bytes) -> dict:
        uuid, entry = entry_for(hashlib.sha256(payload).hexdigest())
        self.rekor[uuid] = entry
        return {"uuid": uuid, "identity": self.identity, "bundle": json.dumps({"rehearsal_entry": uuid}).encode()}


class Rekor:
    def __init__(self) -> None:
        self.entries: dict = {}

    def entry(self, uuid):
        return self.entries.get(uuid)


class Router:
    """The writer's transport over both GitHubs: a repository's path to its own, and the App's two routes (one App
    installed on both targets, tohum/25a row 3) answered here."""

    def __init__(self, hubs: dict[str, FakeGitHub]) -> None:
        self.hubs = hubs

    def __call__(self, method, path, body):
        if (method, path) == ("GET", "/app"):
            return 200, {"id": AW.APP_ID, "slug": "snowball-writer"}
        if (method, path) == ("GET", "/installation/repositories"):
            return 200, {"total_count": len(self.hubs), "repositories": [{"full_name": r} for r in self.hubs]}
        for repo, hub in self.hubs.items():
            if path.startswith("/repos/%s/" % repo):
                return hub(method, path, body)
        return 404, {"message": "Not Found"}


def _candidate(diff: bytes, expect: dict) -> dict[str, bytes]:
    return {"diff.patch": diff, "finding.json": json.dumps(FINDING).encode(),
            "expect.json": json.dumps(expect).encode() + b"\n"}


class Flow:
    """The world above and its runs, under ``base``."""

    def __init__(self, base: str, drill: dict | None = None, seed: str = "7" * 64,
                 patches: dict[str, bytes] = DRILL_PATCHES) -> None:
        """``drill``: ``DRILL_FIXTURES``' instances ``{instance id: cause}`` (each instance's patch from ``patches``,
        the units' sentinel ``SENTINEL_UNITS``, which those patches turn red), or none; ``seed``: ``DRILL_SEED``."""
        self.base, self.runs, self.seed = base, 0, seed
        self.state_heads: list = []  # the toy's brain/state head after each run
        self.work = os.path.join(base, "checkout")
        self.brain = {"referee/loop/job.py": b"x = 1\n", "referee/a.py": b"a\n"}
        units = SENTINEL_UNITS if drill else {"units": [recipe()]}
        for tid, cands in CANDIDATES.items():
            self.brain["targets/%s/units.json" % tid] = json.dumps(units).encode()
            for cid, (diff, expect) in cands.items():
                self.brain.update({"candidates/%s/%s/%s" % (tid, cid, f): d
                                   for f, d in _candidate(diff, expect).items()})
        self.brain_objects, self.brain_sha = S.store(self.brain)
        tree_files = dict(TREE, **({"pkg/sentinel.py": SENTINEL_PY} if drill else {}))
        files = {p: (json.dumps(v) if isinstance(v, dict) else v).encode() for p, v in tree_files.items()}
        self.hubs: dict[str, FakeGitHub] = {}
        targets = []
        for tid, kind, repo in TARGETS:
            hub = FakeGitHub(repo, required_check=B.CHECK)
            hub.refs["main"] = hub.seed_files(files, msg="main")
            hub.overrides.update({k: v for k, v in AW.facts(kind, repo).items()
                                  if not k[1].startswith(("/app", "/installation"))})
            self.hubs[repo] = hub
            targets.append({"id": tid, "kind": kind, "repo": repo, "excluded_paths": [], "unit_candidates": [],
                            "base_sha": hub.refs["main"], "identifiers": []})
        summary = {"seed_epochs": [{"commit": "1" * 40, "spec_tohum_sha256": "2" * 64, "seed_sha256": "3" * 64,
                                    "bootstrap_sha256": "4" * 64}], "targets": targets}
        tree = T.digest([(p, "file", d) for p, d in self.brain.items()])
        # (A)'s result, which the import names and copies (tohum/26c, 29s), with the owner's two exceptions of
        # stage 0 (tohum/02 "Sahip istisnası": the form (A) writes them in, 26d:45-47)
        self.result = result = YW.transfer({"requested": True, "transferable": True,
                                            "owner_exception": YW.OWNER_EXCEPTIONS})["result"]
        imported = dict(TA.import_row(tree, self.brain_sha), result_sha256=hashlib.sha256(result).hexdigest())
        write_tree(self.work, {"setup/summary.json": json.dumps(summary),
                               "setup/imports.jsonl": TA.chained([imported]).decode(),
                               PR.result_path(TA.chained([imported])): result.decode(),
                               J.SECURITY_LEDGER: YW.chained([{"row_id": "s1", "part": "security", "kind": "note",
                                                               "payload": {}}]).decode()})
        with open(os.path.join(self.work, "policy.json"), "wb") as fh:
            fh.write(POLICY)
        write_bootstrap(self.work)
        self.fixtures = ""
        if drill:
            self.catalog = drill_catalog(drill, patches)
            with open(os.path.join(self.work, "setup", "imports.jsonl"), "rb") as fh:
                self.fixtures = fixtures_value(self.catalog, fh.read())
        self.rekor = Rekor()
        self.signer = RekorSigner(self.rekor.entries, A.workflow_identity(REFEREE_REPO, A.LOOP_WORKFLOW))
        zipped = TA.zip_of({"result.json": TA.result(self.brain_sha), "result.json.sigstore.json": b"{}"})
        self.api = TA.FakeApi([TA.artifact(11, "2026-11-01T00:00:00Z")], zipped)

    def _git(self, root: str) -> str:
        """The fake ``git`` of this run: every object of the brain and of both GitHubs' refs, each repository's
        ``ls-remote`` answer as its refs are now."""
        objects = dict(self.brain_objects)
        listings = {}
        for repo, hub in self.hubs.items():
            objects.update(hub.git_objects(list(hub.refs.values())))
            listings[A.repo_url(repo)] = b"".join(b"%s\trefs/heads/%s\n" % (hub.refs[b].encode(), b.encode())
                                                  for b in LISTED.values() if b in hub.refs)
        answers = {sha: S.batch_record(sha, kind, data) for sha, (kind, data) in objects.items()}
        bin_dir = os.path.join(root, "bin")
        os.makedirs(bin_dir)
        S.install_git(bin_dir, answers, listing=b"")
        return install_listing_git(bin_dir, listings)

    def run(self) -> dict:
        """One run of the workflow: ``{job: its line}`` for each job run, in order, up to the first not ``ok``."""
        self.runs += 1
        root = os.path.join(self.base, "run%d" % self.runs)
        temps = {job: os.path.join(root, job) for job in ("cek", "getir", "kos", "cagir", "yaz")}
        os.makedirs(temps["cek"])
        install_sigstore(temps["cek"])
        env = {"RUNNER_TEMP": temps["cek"], "GITHUB_REPOSITORY": REFEREE_REPO, "GITHUB_TOKEN": "t",
               "GITHUB_WORKSPACE": self.work, "PATH": os.environ.get("PATH", "")}
        lines = {"cek": J.run("cek", env, http=self.api, verifier=lambda argv: 0, git=self._git(root),
                              rekor=self.rekor)}
        if not lines["cek"]["ok"]:
            return lines
        for job in ("getir", "kos", "cagir", "yaz"):
            shutil.copytree(os.path.join(temps["cek"], "out", "pulled"), os.path.join(temps[job], "in", "pulled"),
                            symlinks=True)
        lines["getir"] = J.run("getir", {"RUNNER_TEMP": temps["getir"]})
        if not lines["getir"]["ok"]:
            return lines
        shutil.copytree(os.path.join(temps["getir"], "out", "deps"), os.path.join(temps["kos"], "in", "deps"))
        lines["kos"] = J.run("kos", {"RUNNER_TEMP": temps["kos"]}, runner=RedAs())
        if not lines["kos"]["ok"]:
            return lines
        claude = os.path.dirname(fake_claude.install_for_loop(temps["cagir"]))
        fake_claude.behave(claude, test_loop_cagir.result(modelUsage={BOOTSTRAP["rival"]["model"]: {"costUSD": 0.01}}))
        run_id = {"GITHUB_RUN_ID": str(self.runs), "GITHUB_RUN_ATTEMPT": "1"}
        lines["cagir"] = J.run("cagir", dict({"RUNNER_TEMP": temps["cagir"], "CLAUDE_CODE_OAUTH_TOKEN": "t",
                                              "GITHUB_WORKSPACE": self.work}, **run_id))
        if not lines["cagir"]["ok"]:
            return lines
        for job, art in (("kos", "results"), ("cagir", "response")):
            shutil.copytree(os.path.join(temps[job], "out", art), os.path.join(temps["yaz"], "in", art))
        write_tree(os.path.join(temps["yaz"], "control"), {"control.json": {"merge_paused": False}})
        now = YW.NOW + datetime.timedelta(hours=self.runs)
        lines["yaz"] = J.run("yaz", YW.env(temps["yaz"], self.work, GITHUB_REPOSITORY=REFEREE_REPO,
                                           DRILL_SEED=self.seed, DRILL_FIXTURES=self.fixtures, **run_id),
                             transport=Router(self.hubs), signer=self.signer, now=lambda: now)
        self.state_heads.append(self.hubs[TARGETS[0][2]].refs.get(B.STATE))
        return lines

    @staticmethod
    def record(lines: dict) -> dict:
        """What the next run depends on, from a run's lines (see the module docstring)."""
        cek = lines["cek"]
        out: dict = {"waiting": [t["target"] for t in cek.get("targets", []) if "waiting" in t]}
        last = list(lines)[-1]
        if not lines[last]["ok"]:
            out["stopped"] = {"job": last, "target": lines[last].get("target"), "reason": lines[last].get("reason"),
                              "reasons": lines[last].get("reasons", [])}
        for t in lines.get("yaz", {}).get("targets", []):
            sentinel = t.get("sentinel")
            out[t["target"]] = {
                "genesis": t.get("written", {}).get("genesis", False), "merge": t.get("merge"),
                "decisions": {cid: d["reasons"] for cid, d in t.get("decisions", {}).items()},
                "sentinel": None if sentinel is None else sentinel["verdict"], "drill": t.get("drill"),
                "gate": t.get("gate"), "pass": t.get("pass"), "done": t.get("done")}
        return out


def seed_choosing(catalog: dict, chosen: dict[str, str]) -> str:
    """A ``DRILL_SEED`` whose key selects ``chosen[run id]`` for each run id (searched, so no selection is written
    here)."""
    for n in range(100000):
        seed = "rehearsal-seed-%d" % n
        if all(RD.key({"seed": seed}, run, catalog)["instance_id"] == i for run, i in chosen.items()):
            return seed
    raise AssertionError("no seed selects %s" % chosen)


def step(record: dict) -> dict:
    """A run's record with commit ids written ``<sha>`` and the drill's line cut to what the flow turns on (its
    action, the planted instance, the judged verdict and reasons): the commitments and keys are the drill's own
    tests' (test_loop_write ``D8``, test_revert_drill)."""
    out = json.loads(SHA40.sub("<sha>", json.dumps(record)))
    for tid in (t for t, _, _ in TARGETS):
        drill = (out.get(tid) or {}).get("drill")
        if drill:
            cut = {k: drill[k] for k in ("action", "why", "instance_id") if k in drill}
            if "judged" in drill:
                cut["judged"] = [drill["judged"]["key"]["instance_id"], drill["judged"]["verdict"],
                                 drill["judged"]["reasons"]]
            out[tid]["drill"] = cut
    return out


def toy(merge=None, decisions=None, sentinel=None, drill=None, gate=None, done=("D5", "D6"), genesis=False,
        judged=None) -> dict:
    """The toy's part of an expected record; ``decisions`` default: both candidates' diffs no longer apply (``good``
    merged at the genesis)."""
    stale = ["artefact_hash_mismatch", "kos:patch_does_not_apply"]
    return {"genesis": genesis, "merge": merge, "decisions": decisions or {"breaks": stale, "good": stale},
            "sentinel": sentinel, "drill": drill, "gate": gate, "pass": judged, "done": list(done)}


GENESIS = toy(merge="good", decisions={"breaks": ["tests_red"], "good": []}, drill={"action": "off", "why": "genesis"},
              genesis=True)


def closed(**conditions) -> dict:
    names = {"geri_alma": "#geri-alma", "nobetci": "#nobetci #hayatta"}
    return {"verdict": "closed", "conditions": {names[k]: ["toy:" + r for r in v] for k, v in conditions.items()}}


MAX_RUNS = 20


def rehearse(flow: Flow) -> list[dict]:
    """Each run's ``step`` up to and including the stall (see the module docstring). After the genesis every run's
    D1 verified the toy's ``brain/state`` that the run before wrote, as an extension of the one before that, and its
    root's entry read from Rekor; else ``AssertionError``, as with no stall in ``MAX_RUNS`` runs."""
    records: list[dict] = []
    for _ in range(MAX_RUNS):
        lines = flow.run()
        records.append(step(Flow.record(lines)))
        line = lines["cek"]["targets"][0]
        if len(flow.state_heads) > 1:
            previous = flow.state_heads[-3] if len(flow.state_heads) > 2 else None
            got = (line["state"]["head"], line["state"]["previous"])
            if got != (flow.state_heads[-2], previous) or line["root"]["rekor_uuid"] not in flow.rekor.entries:
                raise AssertionError("run %d: D1 did not verify the state the run before wrote: %s" % (flow.runs, got))
        if "stopped" in records[-1] or records[-1:] == records[-2:-1] or ended(records[-1]):
            return records
    raise AssertionError("no stall and no end in %d runs: %s" % (MAX_RUNS, records))


def ended(record: dict) -> bool:
    """Whether ``record`` is (B)'s end: no job stopped and a target's ``yaz`` judged its PASS row ``PASS``."""
    return "stopped" not in record and any(((record.get(t) or {}).get("pass") or {}).get("verdict") == "PASS"
                                           for t, _, _ in TARGETS)


def without_fixtures(base: str) -> Flow:
    return Flow(base)


def with_fixtures(base: str) -> Flow:
    return Flow(base, drill=DRILL_CAUSES,
                seed=seed_choosing(drill_catalog(DRILL_CAUSES), {"2": RD_TEST, "5": RD_LINT, "8": RD_BUILD}))


def stale_patches(base: str) -> Flow:
    return Flow(base, drill=DRILL_CAUSES, patches=D8_PATCHES)


# ``docs/exit-b.md``'s cases (``status.exit_b.render_case``), in its order: name, title, the world, the open reports
# the stop waits for (a seed epoch answering one of them closes it, and this test's expected stall then moves).
CASES = (
    ("without-fixtures", "No drill fixtures secret (the operator writes it at the activation, tohum/26f)",
     without_fixtures, []),
    ("with-fixtures", "Drill fixtures of the three causes", with_fixtures, []),
    ("stale-patches", "Drill patches on the file the toy's merge changed (a set 26f's producer refuses)",
     stale_patches, []),
)


def case_section(name: str, records: list[dict]) -> str:
    _, title, _, waits = next(c for c in CASES if c[0] == name)
    return EB.render_case(name, title, records, waits, EB.reports_by_id())


def write_doc() -> None:
    """``docs/exit-b.md`` from each case's rehearsal (``python tests/test_rehearsal.py --doc``)."""
    sections = []
    for name, _, world, _ in CASES:
        base = writable_base("t-rehearsal-doc-")
        try:
            sections.append(case_section(name, rehearse(world(base))))
        finally:
            shutil.rmtree(base, ignore_errors=True)
    with open(EB.DOC, "w", encoding="utf-8") as fh:
        fh.write(EB.render(EB.read_page(), sections))


class Rehearsal(unittest.TestCase):
    def setUp(self) -> None:
        self.base = writable_base("t-rehearsal-")
        self.addCleanup(shutil.rmtree, self.base, ignore_errors=True)

    def rehearse(self, flow: Flow) -> list[dict]:
        return rehearse(flow)

    def assert_documented(self, name: str, records: list[dict]) -> None:
        """``docs/exit-b.md`` holds this case's section as these records give it (a stale document is red)."""
        with open(EB.DOC, encoding="utf-8") as fh:
            doc = fh.read()
        self.assertTrue(case_section(name, records) in doc,
                      "docs/exit-b.md is stale for %s: regenerate it with 'python tests/test_rehearsal.py --doc' "
                      "from referee/" % name)

    def test_without_the_drills_fixtures_b_stalls_at_the_drill(self):
        """DRILL_SEED set, no DRILL_FIXTURES (tohum/26f: the operator writes it before the activation, 25a row 7):
        the toy's genesis merges ``good`` and rejects ``breaks``, the next run watches the merge green and ends it,
        and from then on every run is the same: the gate stays closed on ``#geri-alma`` alone and the copy waits."""
        flow = without_fixtures(self.base)
        off = {"action": "off", "why": "fixtures_absent"}
        gate = closed(geri_alma=["drill_inputs_missing"])
        records = self.rehearse(flow)
        self.assert_documented("without-fixtures", records)
        self.assertEqual(records, [
            {"waiting": ["c1"], "t1": GENESIS},
            {"waiting": ["c1"], "t1": toy(sentinel="green", drill=off, done=("D5", "D6", "D7"),
                                          gate=closed(nobetci=["sentinel_unfinished:<sha>"],
                                                      geri_alma=["drill_inputs_missing"]))},
            {"waiting": ["c1"], "t1": toy(drill=off, gate=gate)},
            {"waiting": ["c1"], "t1": toy(drill=off, gate=gate)}])
        hub = flow.hubs["o/copy"]
        self.assertEqual(sorted(hub.refs), ["main"])  # the copy was never written

    def test_with_the_drills_fixtures_b_reaches_its_pass_row(self):
        """Fixtures of the three causes 10a #geri-alma asks for, with a seed that plants RD_TEST, RD_LINT and
        RD_BUILD in turn: each drill is committed, planted as the cycle's one merge, watched red and reverted by
        D7, then revealed and judged ``PASS``. RD_BUILD's head does not parse (``PARSE_ERROR``: the toy's lint
        reports a fatal message), so ``kos`` has no base run in that cycle (the candidates are ``base_unavailable``)
        and D7 reverts it as ``build_break`` (``loop.watch.base_build``, seed-044's answer). Then the toy's gate
        opens, the next run serves the copy and runs its genesis, the copy's sentinel ends green while the toy's
        next drill is reverted, and the run after that judges the toy's PASS row ``PASS`` and writes it."""
        flow = with_fixtures(self.base)
        unshown = ["cause_unshown:%s" % c for c in ("test_regression", "build_break", "lint_regression")]
        wait = {"action": "wait", "why": "drill_unfinished"}
        commit = {"action": "commit"}
        d8 = ("D5", "D6", "D8")
        d78 = ("D5", "D6", "D7", "D8")
        no_base = ["artefact_hash_mismatch", "kos:base_unavailable"]
        stale = ["artefact_hash_mismatch", "kos:patch_does_not_apply"]
        records = self.rehearse(flow)
        self.assert_documented("with-fixtures", records)
        self.assertEqual(records, [
            {"waiting": ["c1"], "t1": GENESIS},
            {"waiting": ["c1"], "t1": toy(sentinel="green", drill=commit, done=d78,
                                          gate=closed(nobetci=["sentinel_unfinished:<sha>"], geri_alma=unshown))},
            {"waiting": ["c1"], "t1": toy(drill={"action": "plant", "instance_id": RD_TEST}, done=d8,
                                          gate=closed(geri_alma=unshown))},
            {"waiting": ["c1"], "t1": toy(sentinel="red", drill=wait, done=d78,
                                          gate=closed(geri_alma=["drill_fail:%s:not_reverted" % RD_TEST] + unshown))},
            {"waiting": ["c1"], "t1": toy(drill=dict(commit, judged=[RD_TEST, "PASS", []]), done=d8,
                                          gate=closed(geri_alma=unshown[1:]))},
            {"waiting": ["c1"], "t1": toy(drill={"action": "plant", "instance_id": RD_LINT}, done=d8,
                                          gate=closed(geri_alma=unshown[1:]))},
            {"waiting": ["c1"], "t1": toy(sentinel="red", drill=wait, done=d78,
                                          gate=closed(geri_alma=["drill_fail:%s:not_reverted" % RD_LINT] + unshown[1:]))},
            {"waiting": ["c1"], "t1": toy(drill=dict(commit, judged=[RD_LINT, "PASS", []]), done=d8,
                                          gate=closed(geri_alma=unshown[1:2]))},
            {"waiting": ["c1"], "t1": toy(drill={"action": "plant", "instance_id": RD_BUILD}, done=d8,
                                          gate=closed(geri_alma=unshown[1:2]))},
            {"waiting": ["c1"], "t1": toy(sentinel="red", drill=wait, done=d78, decisions={"breaks": no_base,
                                                                                          "good": no_base},
                                          gate=closed(geri_alma=["drill_fail:%s:not_reverted" % RD_BUILD] + unshown[1:2]))},
            {"waiting": ["c1"], "t1": toy(drill=dict(commit, judged=[RD_BUILD, "PASS", []]), done=d8,
                                          gate={"verdict": "open", "conditions": {}})},
            {"waiting": [], "t1": toy(drill={"action": "plant", "instance_id": RD_LINT}, done=d8,
                                      judged={"waiting": "copy_genesis"}),
             "c1": {"genesis": True, "merge": "good", "decisions": {"good": []}, "sentinel": None,
                    "drill": {"action": "off", "why": "genesis"}, "gate": None, "pass": None, "done": ["D5", "D6"]}},
            {"waiting": [], "t1": toy(sentinel="red", drill=wait, done=d78, judged={
                "verdict": "FAIL", "conditions": {"#geri-alma": ["toy:drill_fail:%s:not_reverted" % RD_LINT],
                                                  "#nobetci #hayatta": ["copy:sentinel_unfinished:<sha>"]}}),
             "c1": {"genesis": False, "merge": None, "decisions": {"good": stale}, "sentinel": "green",
                    "drill": {"action": "off"}, "gate": None, "pass": None, "done": ["D5", "D6", "D7"]}},
            {"waiting": [], "t1": toy(drill=dict(commit, judged=[RD_LINT, "PASS", []]), done=d8,
                                      judged={"verdict": "PASS", "conditions": {}}),
             "c1": {"genesis": False, "merge": None, "decisions": {"good": stale}, "sentinel": None,
                    "drill": {"action": "off"}, "gate": None, "pass": None, "done": ["D5", "D6"]}}])
        ledger = flow.hubs["o/toy"].read_file(B.STATE, B.STATE_LEDGER)
        self.assertTrue(PR.passed(ledger))  # the PASS row is written
        # and carries (A)'s owner exceptions with the result's RFC 8785 bytes (tohum/26d, stage-open's check 7)
        [row] = [r for r in map(json.loads, ledger.splitlines()) if r["kind"] == "pass"]
        self.assertEqual(CH.canonical(row["payload"]["owner_exception"]),
                         CH.canonical(json.loads(flow.result)["exit"]["owner_exception"]))
        self.assertEqual([e["anchor"] for e in row["payload"]["owner_exception"]], ["durustluk", "spec"])
        self.assertIn(B.STATE, flow.hubs["o/copy"].refs)

    def test_drill_patches_on_a_line_the_toys_merge_changed_never_apply(self):
        """``test_loop_write.D8``'s patches change ``var a = 1;``, the line ``good`` changes at the genesis: on
        ``brain/integration``'s head after that merge no instance applies, so no drill is ever committed and the flow
        stalls as without fixtures, the gate closed on every cause. tohum/26f:52-55 (seed-045's answer) forbids such
        a set: no candidate expected to merge changes a file a patch changes; the loop still answers it safely."""
        flow = stale_patches(self.base)
        none = {"action": "none", "why": "patch_does_not_apply"}
        unshown = ["cause_unshown:%s" % c for c in ("test_regression", "build_break", "lint_regression")]
        records = self.rehearse(flow)
        self.assert_documented("stale-patches", records)
        self.assertEqual(records, [
            {"waiting": ["c1"], "t1": GENESIS},
            {"waiting": ["c1"], "t1": toy(sentinel="green", drill=none, done=("D5", "D6", "D7", "D8"),
                                          gate=closed(nobetci=["sentinel_unfinished:<sha>"], geri_alma=unshown))},
            {"waiting": ["c1"], "t1": toy(drill=none, done=("D5", "D6", "D8"), gate=closed(geri_alma=unshown))},
            {"waiting": ["c1"], "t1": toy(drill=none, done=("D5", "D6", "D8"), gate=closed(geri_alma=unshown))}])


if __name__ == "__main__":
    if sys.argv[1:] == ["--doc"]:
        write_doc()
    else:
        unittest.main()
