"""Test 46 (asama-0/09), MF17, D3 -> D5: ``yaz``'s decision (``loop.decide``, ``loop.job run yaz``) on what the
``kos`` job wrote with the fake runner, and on the pulled candidates (asama-0/08 criteria 1-8). One target is served
here (``in/pulled/served.json`` listing t1): its ``pulled`` is ``in/pulled/t1``, ``kos``'s ``out/results/t1`` is
handed over as ``in/results/t1``, and the job's line holds its one target line ``targets[0]`` (``target`` t1, the
job's ``ok``; a refused target's ``reason``, ``reasons`` and id are the job's).

- one cycle: a good candidate merges; a test-breaking and a ratchet-raising one are rejected for their own reasons;
  merges are serial (a second good candidate carries ``sentinel_pending``); the order is the ids' code-point order;
- criterion 1 through ``gate.diffguard`` with the profile ``kos`` staged with: a manifest change, a security
  keyword of the policy, and an operator excluded path, which 29g says ``excluded_dirs`` carries (and ``kos`` refused too: ``kos:base_file_missing``);
- criterion 2: a diff that adds a key id is ``secret_in_diff`` (MF2 reached through MF8);
- criteria 7 and 8 from the inputs: ``merge_paused`` missing or true, an unfinished sentinel;
- the artifacts by hash: a changed byte of a run file, a missing ``hashes.json``, an unusable diff or finding;
- the job: ``loop.job run yaz`` reads ``control.json`` and the two artifacts, takes criterion 8 from ``pulled``'s
  ``brain/state`` ledger (``ledger.serial``: no merge, a merge, a planted merge, a reverted one) and ends ``ok``
  after D5 and D6 (D7 when it ends a sentinel; D8 off without its seed); its root signer is the ``sigstore`` step's
  program (tohum/29s), and without it the job is no verdict before anything is written; a ledger ``ledger.serial`` refuses is ``state_refused``, nothing decided; a refused
  artifact (among them a ``pulled`` whose ``target.id`` is not its directory's name, ``target_mismatch``, nothing
  decided), a ``served.json`` beside an unlisted directory (``pulled_invalid``, no target served), a missing
  ``control.json`` and an unusable recipe;
- criterion 1's profile (``GuardProfile``, the two calls ``loop.decide`` makes): paths named in the tree (a
  security and a physical safety word), a CODEOWNERS safety owner, the owner's ``safety_paths``, the operator's
  excluded paths, the policy's security keywords; a tree or target the derivation refuses.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import unittest

REFEREE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REFEREE)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import activation_world as AW  # noqa: E402
from gate import diffguard as G  # noqa: E402
from loop import decide as E  # noqa: E402
from profile import derive as D  # noqa: E402
from loop import job as J  # noqa: E402
from loop import pulled as P  # noqa: E402
from profile import unit_verify as V  # noqa: E402
from profile_tree import write_tree  # noqa: E402
from test_kos import BREAKS_TEST, GOOD, RAISES, diff, recipe  # noqa: E402
from test_loop_kos import HEADS, TARGET, Base, RedAs, candidate, state_files  # noqa: E402
from test_revert_drill import plant, reverted  # noqa: E402
from test_serial import M1, START, merge  # noqa: E402
from test_loop_cagir import policy  # noqa: E402
import yaz_world as YW  # noqa: E402
from loop import sign as S  # noqa: E402
from loop_inputs_world import install_sigstore  # noqa: E402

KEY_ID = "AK" + "IA" + "Q7" * 8  # a key id shape (MF2's floor), spelled so this file holds none
LEAK = diff("pkg/a.js", ["var a = 1;"], ["let a = 1; // " + KEY_ID])
MANIFEST = diff("pkg/package.json", ['{"name": "pkg", "version": "1.0.0"}'], ['{"name": "pkg", "version": "1.0.1"}'])
C_JS = diff("pkg/c.js", ["const d = 5;"], ["const d = 6;"])
OPEN = {"merge_paused": False}


class Cycle(Base):
    """``kos`` then ``yaz`` in one ``$RUNNER_TEMP``, as the workflow hands the artifacts over."""

    def kos(self, cands: dict, target: dict | None = None, units=None, **kw) -> dict:
        """The ``kos`` job on the pulled artifact; it ends ``ok`` (so the upload runs) and its ``out/results`` is
        handed over to ``in/results`` as the download does (``out/results/t1`` to ``in/results/t1``). Returns the
        target's line of ``kos``'s line (``line``)."""
        self.write_pulled(cands, target=target, units=units, **kw)
        out = J.run("kos", {"RUNNER_TEMP": self.temp}, runner=RedAs())
        self.assertTrue(out["ok"], out)
        self.assertNotIn("reason", out)
        # the download of kos's out/results: its one directory per served target
        os.makedirs(os.path.dirname(self.results()), exist_ok=True)
        shutil.move(os.path.join(self.temp, "out", "results", TARGET["id"]), self.results())
        os.rmdir(os.path.join(self.temp, "out", "results"))
        return self.line(out)

    def results(self, *parts) -> str:
        return os.path.join(self.temp, "in", "results", TARGET["id"], *parts)

    def line(self, out: dict, tid: str = "t1") -> dict:
        """The job line's one target line, after checking it is ``tid``'s, that the job's ``ok`` is its, and that a
        refused target's ``reason``/``reasons`` and id are the job's (``loop.job.run``)."""
        [line] = out["targets"]
        self.assertEqual(line["target"], tid)
        self.assertEqual(out["ok"], line["ok"])
        stop = {k: out[k] for k in ("reason", "reasons", "target") if k in out}
        if line["ok"]:
            self.assertEqual(stop, {})
        else:
            self.assertEqual(stop, {k: line[k] for k in ("reason", "reasons", "target") if k in line})
        return line

    def refused(self, out: dict, tid: str = "t1") -> dict:
        """A job stopped at its one target (see ``line``)."""
        line = self.line(out, tid)
        self.assertFalse(line["ok"])
        return line

    def tree(self) -> str:
        tree = os.path.join(self.base, "tree-%d" % len(os.listdir(self.base)))
        P.extract_tree(os.path.join(self.pulled, P.TREE), tree)
        return tree

    def decide(self, control=None, unfinished=(), unit=None) -> dict:
        art = P.read(self.pulled)
        return E.decide(art, unit or recipe(), self.tree(), self.results(), OPEN if control is None else control,
                        list(unfinished))

    def reasons(self, got: dict) -> dict:
        return {cid: d["reasons"] for cid, d in got["decisions"].items()}


class OneCycle(Cycle):
    def test_good_merges_bad_rejected_for_their_reasons(self):
        self.kos({"good": candidate(GOOD), "breaks": candidate(BREAKS_TEST), "raises": candidate(RAISES)})
        got = self.decide()
        self.assertEqual(got["merge"], "good")
        self.assertEqual(got["decisions"]["good"], {"decision": "merge", "reasons": []})
        self.assertEqual(got["decisions"]["breaks"], {"decision": "reject", "reasons": ["tests_red"]})
        # judged after good, which is this cycle's merge: its sentinel is unfinished (tohum/07)
        self.assertEqual(got["decisions"]["raises"]["decision"], "reject")
        self.assertIn("ratchet_increase", got["decisions"]["raises"]["reasons"])
        self.assertIn("sentinel_pending", got["decisions"]["raises"]["reasons"])

    def test_merges_are_serial_in_code_point_order(self):
        self.kos({"b2": candidate(GOOD), "B1": candidate(GOOD), "a3": candidate(GOOD)})
        got = self.decide()
        self.assertEqual(got["merge"], "B1")  # "B" < "a" < "b" by code point
        self.assertEqual(self.reasons(got), {"B1": [], "a3": ["sentinel_pending"], "b2": ["sentinel_pending"]})

    def test_a_rejected_candidate_does_not_take_the_merge(self):
        self.kos({"a": candidate(BREAKS_TEST), "b": candidate(GOOD)})
        got = self.decide()
        self.assertEqual((got["merge"], self.reasons(got)), ("b", {"a": ["tests_red"], "b": []}))

    def test_no_candidates(self):
        self.kos({})
        self.assertEqual(self.decide(), {"decisions": {}, "merge": None})


class Criteria(Cycle):
    def test_criterion_1_a_manifest(self):
        self.kos({"good": candidate(MANIFEST)})
        reasons = self.reasons(self.decide())["good"]
        self.assertIn("manifest:pkg/package.json", reasons)

    def test_criterion_1_the_operators_excluded_path_reaches_diffguard(self):
        # pkg/c.js: a file the fixture's lint does not read, so the base still runs without it
        write_tree(self.src, {"pkg/c.js": "const d = 5;\n"})
        self.kos({"edit": candidate(C_JS)}, target=dict(TARGET, excluded_paths=["pkg/c.js"]))
        art = P.read(self.pulled)
        self.assertIn("pkg/c.js", V.guard_profile(self.tree(), art.target, art.policy)["excluded_dirs"])
        reasons = self.reasons(self.decide())["edit"]
        self.assertIn("excluded_path:pkg/c.js", reasons)
        self.assertIn("kos:base_file_missing", reasons)  # the staging left it out of the worktree too

    def test_criterion_1_without_operator_exclusion_the_path_is_not_excluded(self):
        write_tree(self.src, {"pkg/c.js": "const d = 5;\n"})
        self.kos({"edit": candidate(C_JS)})
        reasons = self.reasons(self.decide())["edit"]
        self.assertFalse([r for r in reasons if r.startswith(("excluded_path", "kos:"))], reasons)

    def test_criterion_1_a_security_path(self):
        write_tree(self.src, {"pkg/auth.js": "var s = 1;\n"})
        self.kos({"sec": candidate(diff("pkg/auth.js", ["var s = 1;"], ["let s = 1;"]))})
        art = P.read(self.pulled)
        self.assertIn("pkg/auth.js", V.guard_profile(self.tree(), art.target, art.policy)["security_paths"])
        self.assertIn("security_path:pkg/auth.js", self.reasons(self.decide())["sec"])

    def test_criterion_1_the_policys_security_keywords(self):
        """``pulled``'s policy reaches the guard profile: a keyword it names guards the file."""
        doc = json.loads(policy())
        doc["constitutional"] = {"security_keywords": ["a.js"]}
        self.kos({"good": candidate(GOOD)}, policy=json.dumps(doc).encode())
        self.assertIn("security_path:pkg/a.js", self.reasons(self.decide())["good"])

    def test_criterion_2_a_secret_in_the_diff(self):
        self.kos({"leak": candidate(LEAK)})
        self.assertIn("secret_in_diff", self.reasons(self.decide())["leak"])

    def test_criterion_7_merge_paused(self):
        self.kos({"good": candidate(GOOD)})
        for control in ({}, {"merge_paused": True}, {"merge_paused": "false"}, None, []):
            with self.subTest(control=control):
                got = self.decide(control={} if control is None else control)
                self.assertEqual((got["merge"], self.reasons(got)), (None, {"good": ["merge_paused"]}))

    def test_criterion_8_an_unfinished_sentinel(self):
        self.kos({"good": candidate(GOOD)})
        got = self.decide(unfinished=["a" * 40])
        self.assertEqual((got["merge"], self.reasons(got)), (None, {"good": ["sentinel_pending"]}))


class Artifacts(Cycle):
    def test_a_changed_byte_of_a_run_file(self):
        self.kos({"good": candidate(GOOD)})
        with open(self.results("c", "good", "cand.jsonl"), "ab") as fh:
            fh.write(b"\n")
        self.assertIn("artefact_hash_mismatch", self.reasons(self.decide())["good"])

    def test_no_hashes_file(self):
        self.kos({"good": candidate(GOOD)})
        os.remove(self.results("c", "good", "hashes.json"))
        self.assertEqual(self.reasons(self.decide())["good"], ["artefact_hash_mismatch"])

    def test_kos_refusal_is_the_candidates_reason(self):
        stale = diff("pkg/a.js", ["var zzz = 9;"], ["let zzz = 9;"])
        self.kos({"stale": candidate(stale)})
        reasons = self.reasons(self.decide())["stale"]
        self.assertIn("kos:patch_does_not_apply", reasons)
        self.assertIn("artefact_hash_mismatch", reasons)

    def test_missing_index_entry(self):
        self.kos({"good": candidate(GOOD)})
        with open(self.results("index.json"), "w") as fh:
            json.dump({"candidates": {}}, fh)
        self.assertIn("kos:missing", self.reasons(self.decide())["good"])

    def test_unusable_diff_and_finding(self):
        bad_finding = dict(candidate(GOOD), **{"finding.json": b'{"rule_id": 1}'})
        self.kos({"nodiff": candidate(b"not a diff\n"), "nofinding": bad_finding})
        reasons = self.reasons(self.decide())
        self.assertEqual(reasons["nodiff"], ["diff_unusable"])
        self.assertIn("candidate_unusable", reasons["nofinding"])

    def test_an_unusable_recipe_judges_nothing(self):
        self.kos({"good": candidate(GOOD)})
        with self.assertRaises(E.Unusable):
            self.decide(unit=recipe(inputs="pkg"))


class YazBase(Cycle):
    """``yaz`` on a target whose heads are ``pulled``'s (``yaz_world.github_at``), with this cycle's ``response``
    (no tests here: test_loop_write's D6 tests share it)."""

    def write_pulled(self, cands=None, target=None, policy=None, **kw) -> dict:
        return super().write_pulled(cands, target=target or dict(TARGET, repo=YW.REPO),
                                    policy=policy or globals()["policy"](), **kw)

    def setUp(self) -> None:
        super().setUp()
        self.workspace = YW.write_workspace(self.base)
        self.signer = YW.signer()

    def github(self) -> None:
        """The target at ``pulled``'s heads, ``brain/integration`` holding the tree, and the response of the cycle."""
        art = P.read(self.pulled)
        self.gh = YW.github_at(art.heads, YW.files_of(self.src))
        shutil.rmtree(os.path.join(self.temp, "in", "response"), ignore_errors=True)
        YW.write_response(self.temp, art.target["id"], art.heads, [YW.cost_row(snapshot=art.heads["brain/integration"])])

    def run_yaz(self, **env) -> dict:
        return J.run("yaz", YW.env(self.temp, self.workspace, **env), transport=self.gh, signer=self.signer,
                     now=lambda: YW.NOW)

    def control(self, doc) -> None:
        write_tree(os.path.join(self.temp, "control"), {"control.json": doc})

    def with_ledger(self, rows: list[dict] | None) -> None:
        """``pulled`` rewritten with ``rows`` as ``brain/state``'s ledger (the default state when ``None``)."""
        shutil.rmtree(self.pulled)
        self.write_pulled({"good": candidate(GOOD), "breaks": candidate(BREAKS_TEST)},
                          state=None if rows is None else state_files(rows))
        self.github()


class YazJob(YazBase):
    def test_the_job_runs_d5_with_criterion_8_from_the_state(self):
        self.kos({"good": candidate(GOOD), "breaks": candidate(BREAKS_TEST)})
        self.control(OPEN)
        self.github()
        out = self.line(self.run_yaz())
        # the default state's ledger holds no merge: nothing unfinished, good merges
        self.assertEqual((out["ok"], "reason" in out, out["done"], out["merge"]), (True, False, ["D5", "D6"], "good"))
        self.assertEqual(self.reasons(out), {"good": [], "breaks": ["tests_red"]})
        # kos and yaz read the same state: an unfinished merge is the head's, whose sentinel kos ran (green here)
        head = HEADS["brain/integration"]
        reverted_merge = [START, merge("c1", head), reverted("r1", head, "test_regression")]
        for rows, want in (([START, merge("c1", head)], "sentinel_pending"),       # the activation's merge
                           ([START, plant("p1", "i1", head)], "sentinel_pending"),  # the drill's planted merge
                           (reverted_merge, None)):
            with self.subTest(rows=[r["row_id"] for r in rows]):
                shutil.rmtree(self.pulled)
                shutil.rmtree(self.results())
                self.kos({"good": candidate(GOOD), "breaks": candidate(BREAKS_TEST)}, state=state_files(rows))
                self.github()
                out = self.line(self.run_yaz())
                self.assertEqual(out["done"], ["D5", "D6", "D7"] if want else ["D5", "D6"])
                self.assertEqual(out["sentinel"] and (out["sentinel"]["merge_sha"], out["sentinel"]["verdict"]),
                                 want and (head, "green"))
                if want:
                    self.assertEqual((out["merge"], self.reasons(out)),
                                     (None, {"good": [want], "breaks": [want, "tests_red"]}))
                else:
                    self.assertEqual((out["merge"], self.reasons(out)), ("good", {"good": [], "breaks": ["tests_red"]}))

    def test_the_root_signer_is_the_sigstore_step_s(self):
        # tohum/29s: yaz signs with the program the sigstore step installs, pinned to loop.yml on the referee's main
        environ = YW.env(self.temp, self.workspace)
        with self.assertRaisesRegex(J.Unusable, "sigstore_missing"):
            J._signer(environ)
        python = install_sigstore(self.temp)
        got = J._signer(environ)
        self.assertEqual((type(got), got.sigstore, got.pin),
                         (S.SigstoreSigner, (python, "-m", "sigstore"),
                          "https://github.com/acme/referee/.github/workflows/loop.yml@refs/heads/main"))
        # the job without an injected signer and without the step's program: no verdict, nothing written
        os.remove(python)
        self.kos({"good": candidate(GOOD)})
        self.control(OPEN)
        self.github()
        with self.assertRaisesRegex(J.Unusable, "sigstore_missing"):
            J.run("yaz", environ, transport=self.gh, now=lambda: YW.NOW)
        self.assertEqual([m for m, _, _ in self.gh.requests if m != "GET"], [])

    def test_a_state_ledger_serial_refuses_decides_nothing(self):
        self.kos({"good": candidate(GOOD)})
        self.control(OPEN)
        for rows, want in (([START, reverted("r1", M1, "unknown")], ["finish_without_merge:%s" % M1]),
                           ([{"row_id": "g1", "part": "genesis"}], None)):
            with self.subTest(want=want):
                self.with_ledger(rows)
                out = self.refused(J.run("yaz", {"RUNNER_TEMP": self.temp}))
                self.assertEqual((out["ok"], out["reason"]), (False, "state_refused"))
                self.assertNotIn("decisions", out)
                if want:
                    self.assertEqual(out["reasons"], want)
                else:
                    self.assertTrue(out["reasons"], out)

    def test_the_control_file_is_read(self):
        self.kos({"good": candidate(GOOD)})
        self.control({"merge_paused": True})
        self.github()
        out = self.line(self.run_yaz())
        self.assertIn("merge_paused", out["decisions"]["good"]["reasons"])
        os.remove(os.path.join(self.temp, "control", "control.json"))
        with self.assertRaises(J.Unusable):
            J.run("yaz", {"RUNNER_TEMP": self.temp})

    def test_a_refused_artifact(self):
        self.kos({"good": candidate(GOOD)})
        self.control(OPEN)
        with open(os.path.join(self.pulled, "candidates/good/diff.patch"), "ab") as fh:
            fh.write(b" ")
        out = self.refused(J.run("yaz", {"RUNNER_TEMP": self.temp}))
        self.assertEqual((out["reason"], out["reasons"]), ("pulled_invalid", ["hash_mismatch:candidates/good/diff.patch"]))

    def test_a_pulled_of_another_target(self):
        # in/pulled/t1 holding target t2's artifact, every hash in it right: the directory names the target
        self.kos({"good": candidate(GOOD)})
        self.control(OPEN)
        shutil.rmtree(self.pulled)
        self.write_pulled({"good": candidate(GOOD)}, target=dict(TARGET, id="t2", repo=YW.REPO))
        out = self.refused(J.run("yaz", {"RUNNER_TEMP": self.temp}))
        self.assertEqual((out["reason"], out["reasons"]), ("pulled_invalid", ["target_mismatch"]))
        self.assertNotIn("decisions", out)

    def test_an_unreadable_served_list(self):
        self.kos({"good": candidate(GOOD)})
        self.control(OPEN)
        os.makedirs(os.path.join(self.temp, "in", "pulled", "t9"))  # a directory served.json does not list
        out = J.run("yaz", {"RUNNER_TEMP": self.temp})
        self.assertEqual((out["ok"], out["reason"], out["reasons"]), (False, "pulled_invalid", ["unlisted:t9"]))
        self.assertNotIn("targets", out)

    def test_two_units(self):
        self.kos({})
        self.control(OPEN)
        shutil.rmtree(self.pulled)
        self.write_pulled(units={"units": [recipe(), recipe(unit_id="b")]})
        self.assertEqual(self.refused(J.run("yaz", {"RUNNER_TEMP": self.temp}))["reason"], "units_not_one")

    def test_an_unusable_recipe(self):
        self.kos({"good": candidate(GOOD)})
        self.control(OPEN)
        shutil.rmtree(self.pulled)
        self.write_pulled({"good": candidate(GOOD)}, units={"units": [recipe(inputs="pkg")]})
        with self.assertRaises(J.Unusable):
            J.run("yaz", {"RUNNER_TEMP": self.temp})

    def test_command_line(self):
        env = {k: v for k, v in os.environ.items() if k in ("PATH", "HOME", "LANG", "SYSTEMROOT")}

        def run():
            proc = subprocess.run([sys.executable, "-m", "loop.job", "run", "yaz"], cwd=REFEREE,
                                  env=dict(env, RUNNER_TEMP=self.temp), capture_output=True)
            return proc.returncode, json.loads(proc.stdout)
        # no pulled downloaded: refused (exit 1) before any target is served
        code, out = run()
        self.assertEqual((code, out["ok"], out["reason"], "targets" in out), (1, False, "pulled_invalid", False))
        # a served pulled and no control.json: no verdict (exit 2)
        self.write_pulled({"good": candidate(GOOD)})
        self.assertEqual(run(), (2, {"ok": False, "reason": None}))


class GuardProfile(unittest.TestCase):
    """Criterion 1's profile is derived from the tree by ``profile.unit_verify.guard_profile``, the one function
    ``loop.decide`` judges every cycle with (the genesis cycle's too: ``activate`` takes D5's answer): no input file
    lists the guarded paths, the tree, the target entry and the policy do. Each case is the two calls
    ``loop.decide`` makes, ``guard_profile`` then ``gate.diffguard.check``, on activation_world's toy tree."""

    def reasons(self, change=None, patch=None) -> list[str]:
        w = AW.World()
        w.tree = w.base_tree()
        if change:
            change(w)
        target = json.loads(w.files["summary.json"])["targets"][0]
        profile = V.guard_profile(w.tree, target, json.loads(w.files["policy.json"]))
        return G.check((patch or w.cand("good")["diff.patch"]).decode(), profile, json.loads(w.recipe))

    def summary_target(self, w: AW.World, **fields):
        summary = json.loads(w.files["summary.json"])
        summary["targets"][0].update(fields)
        w.files["summary.json"] = json.dumps(summary).encode()

    def test_unguarded_control(self):
        self.assertEqual(self.reasons(), [])

    def test_paths_named_in_the_tree_are_guarded(self):
        """A security word (``auth``) and a physical safety word (``feeder``, tohum/05) in the base tree's names."""
        for path in ("src/auth/session.js", "src/feeder/valve.js"):
            patch = AW.diff(path, 1, ["module.exports = {};"], ["module.exports = { a: 1 };"])
            self.assertEqual(self.reasons(patch=patch), ["security_path:" + path])

    def test_codeowners_safety_owner_in_the_tree(self):
        def owners(w):
            with open(os.path.join(w.tree, "CODEOWNERS"), "w") as fh:
                fh.write("src/ @acme/scada-team\n")
        self.assertIn("security_path:src/a.js", self.reasons(owners))

    def test_owners_safety_paths_widen(self):
        self.assertIn("security_path:src/a.js", self.reasons(lambda w: self.summary_target(w, safety_paths=["src/a.js"])))

    def test_operators_excluded_paths(self):
        self.assertIn("excluded_path:src/a.js", self.reasons(lambda w: self.summary_target(w, excluded_paths=["src/"])))

    def test_policy_security_keywords(self):
        policy = {"constitutional": {"security_keywords": ["a.js"]}}
        self.assertIn("security_path:src/a.js",
                      self.reasons(lambda w: w.files.update({"policy.json": json.dumps(policy).encode()})))

    def test_a_tree_or_target_the_derivation_refuses(self):
        cases = {"not_a_directory": lambda w: setattr(w, "tree", os.path.join(w.base_tree(), "package.json")),
                 "tree_is_a_link": lambda w: (os.symlink(w.base_tree(), w.tree + "-link"),
                                              setattr(w, "tree", w.tree + "-link")),
                 "safety_paths_malformed": lambda w: self.summary_target(w, safety_paths=[""]),
                 "policy_keywords_malformed": lambda w: w.files.update(
                     {"policy.json": b'{"constitutional": {"security_keywords": []}}'})}
        for name, change in cases.items():
            with self.assertRaises(D.DeriveError, msg=name):
                self.reasons(change)


if __name__ == "__main__":
    unittest.main()
