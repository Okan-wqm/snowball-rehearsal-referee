"""E88, the seed epoch (`tohum/25` 10b, `tohum/26c` `seed_epochs[]`).

The operator delivers a new seed into the live brain as one commit on top of its head and appends that commit's row
to `setup/summary.json` (`seed/founder/README.md`, "Tohum teslimi"). From then on the referee judges nothing in the
delivery itself, never holds the delivered seed against a later Founder push whose diff still carries it, rejects
every change the Founder makes to the seed, and carries its signed state across the epoch.
"""

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from snowball_bootstrap import cli, gitio, state as st
from snowball_bootstrap.config import ConfigError, SeedEpoch, Summary, load_summary
from snowball_bootstrap.treehash import tree_hash

import test_flow
from helpers import commit, make_repo, sh

CODE_JOBS = {"getir": "success", "kos": "success", "cagir": "success", "yeniden": "skipped"}
RED_JOBS = {"getir": "success", "kos": "success", "cagir": "skipped"}
NEW_SEED = {"spec/tohum/00-cekirdek.md": "# core, second epoch\n", "spec/tohum/29d-yeni.md": "# a page the epoch adds\n",
            "seed/bootstrap/snowball_bootstrap/__init__.py": "VERSION = 2\n", "seed/bootstrap/vectors/new.json": "{}\n"}
FIRST_TEST = f"test_failed:T{test_flow.STAGE0.feature(1).tests[0]}"


class SeedEpochFlow(unittest.TestCase):
    setUp = test_flow.Flow.setUp
    tearDown = test_flow.Flow.tearDown
    pull = test_flow.Flow.pull
    finish = test_flow.Flow.finish
    rival_ok = test_flow.Flow.rival_ok
    green_run = test_flow.Flow.green_run
    freeze_stage0 = test_flow.Flow.freeze_stage0
    commit_with_raw_name = test_flow.Flow.commit_with_raw_name

    def summary_path(self) -> Path:
        return self.referee / "setup" / "summary.json"

    def epoch_row(self, sha, *extra):
        printed = io.StringIO()
        with contextlib.redirect_stdout(printed):
            self.assertEqual(cli.main(["seed-epoch", "--brain", str(self.brain), "--commit", sha, *extra]), 0)
        return json.loads(printed.getvalue())

    def deliver(self, files=None, *extra):
        """The README's procedure: one commit of seed paths on top of the brain's head, then the row `seed-epoch`
        prints appended to the summary's `seed_epochs[]`."""
        sha = commit(self.brain, NEW_SEED if files is None else files, "seed epoch")
        summary = json.loads(self.summary_path().read_text())
        summary.setdefault("seed_epochs", []).append(self.epoch_row(sha, *extra))
        self.summary_path().write_text(json.dumps(summary))
        return sha

    def accept_mf1(self):
        self.freeze_stage0()
        commit(self.brain, {"referee/ledger/chain.py": "x = 1\n",
                            "snowball-tests.json": test_flow.all_tests_manifest([1])}, "mf1")
        meta = self.pull()
        result = self.finish(meta, run=self.green_run(meta), rival=self.rival_ok(), jobs=CODE_JOBS)
        self.assertEqual(result["verdict"], "accepted", result["reasons"])
        return meta["head"]

    def red_push(self, n):
        commit(self.brain, {"referee/ledger/chain.py": f"x = {n}\n"}, f"red {n}")
        meta = self.pull()
        run = self.green_run(meta)
        run["tests"][0]["ok"], run["green"] = False, False
        return self.finish(meta, run=run, jobs=RED_JOBS)

    def test_the_delivery_itself_is_nothing_to_judge(self):
        """(d) The operator's commit lands on a Founder head the referee rejected; that head's code is not judged
        again under the operator's name, and nothing of the delivery counts for or against the Founder."""
        accepted = self.accept_mf1()
        self.assertEqual(self.red_push(2)["verdict"], "rejected")
        streaks = dict(self.state["reject_streaks"])
        self.assertEqual(streaks, {FIRST_TEST: 1})
        delivery = self.deliver()
        meta = self.pull()
        self.assertEqual((meta["head"], meta["kind"], meta["pre_reasons"]), (delivery, "seed_update", []))
        self.assertEqual((meta["run_tests"], meta["run_rival"]), (False, False))
        self.assertIn("spec/tohum/29d-yeni.md", meta["changed"])  # what was delivered, on the record
        result = self.finish(meta)
        self.assertEqual((result["kind"], result["verdict"], result["reasons"], result["rejection"]),
                         ("seed_update", "noop", [], None))
        self.assertEqual((result["state"]["last_accepted_sha"], result["state"]["last_evaluated_sha"]),
                         (accepted, delivery))
        self.assertEqual(result["state"]["reject_streaks"], streaks)
        self.assertEqual(self.pull()["kind"], "none")  # judged once: the next poll skips it

    def test_a_later_founder_push_is_judged_without_the_delivered_seed(self):
        """(a) The last accepted commit is older than the delivery, so the seed change stays in the diff of the
        Founder's next push; it is the operator's, and neither the classification nor the rival sees it."""
        accepted = self.accept_mf1()
        self.red_push(2)
        self.deliver()
        self.finish(self.pull())
        commit(self.brain, {"referee/ledger/chain.py": "x = 3\n"}, "the Founder's fix, on top of the delivery")
        meta = self.pull()
        self.assertEqual((meta["base"], meta["kind"], meta["pre_reasons"]), (accepted, "code", []))
        self.assertEqual(meta["changed"], ["referee/ledger/chain.py"])
        self.assertEqual((meta["run_tests"], meta["run_rival"]), (True, True))
        diff = (Path(self.tmp.name) / f"pulled{self.n}" / "diff.patch").read_text(encoding="utf-8")
        self.assertIn("referee/ledger/chain.py", diff)
        self.assertNotIn("spec/tohum/", diff)
        self.assertNotIn("seed/bootstrap/", diff)
        result = self.finish(meta, run=self.green_run(meta), rival=self.rival_ok(), jobs=CODE_JOBS)
        self.assertEqual(result["verdict"], "accepted", result["reasons"])
        self.assertEqual(result["state"]["reject_streaks"], {})

    def test_an_exit_request_a_spec_request_or_ledger_rows_over_the_delivery_keep_their_kind(self):
        """(a) The referee never saw the delivery as a head: the Founder pushed on top of it first."""
        accepted = self.accept_mf1()
        delivery = self.deliver()
        frozen = self.state["frozen_specs"]["spec/asama-0"]
        commit(self.brain, {"exit-request.json": json.dumps({"stage": 0, "sha": accepted, "spec_sha256": frozen}),
                            "founder-ledger.jsonl": '{"kind":"exit"}\n'}, "exit request")
        meta = self.pull()
        self.assertEqual((meta["kind"], meta["pre_reasons"], meta["changed"]),
                         ("exit", [], ["exit-request.json", "founder-ledger.jsonl"]))
        sh(self.brain, "git", "reset", "-q", "--hard", delivery)
        commit(self.brain, {"spec/asama-1/00-ozet.md": "# stage 1\n"}, "the next stage's spec")
        meta = self.pull()
        self.assertEqual((meta["kind"], meta["pre_reasons"], meta["run_rival"]), ("spec", [], True))
        self.assertEqual((meta["changed"], list(meta["spec_dir_hashes"])), (["spec/asama-1/00-ozet.md"], ["spec/asama-1"]))
        sh(self.brain, "git", "reset", "-q", "--hard", delivery)
        commit(self.brain, {"founder-ledger.jsonl": '{"kind":"session"}\n'}, "ledger rows alone")
        meta = self.pull()
        self.assertEqual((meta["kind"], meta["pre_reasons"]), ("none", []))

    def test_every_founder_change_to_the_seed_is_still_rejected(self):
        """(b) After the epoch the head's seed trees must be the summary's: a change, an addition or a removal under
        spec/tohum/ or seed/ is the Founder's, even with code beside it."""
        self.accept_mf1()
        delivery = self.deliver()
        self.finish(self.pull())
        cases = {"spec/tohum edited": {"spec/tohum/00-cekirdek.md": "# the Founder's core\n"},
                 "spec/tohum page added": {"spec/tohum/99-x.md": "x\n"},
                 "delivered page removed": {"spec/tohum/29d-yeni.md": None},
                 "seed/ edited": {"seed/bootstrap/vectors/new.json": "[]\n"},
                 "seed/ file added": {"seed/bootstrap/vectors/more.json": "{}\n"},
                 "seed/ file removed": {"seed/bootstrap/snowball_bootstrap/__init__.py": None}}
        for name, files in cases.items():
            commit(self.brain, dict(files, **{"referee/ledger/chain.py": "x = 9\n"}), name)
            meta = self.pull()
            self.assertEqual(meta["kind"], "rejected", name)
            self.assertIn("seed_modified", meta["pre_reasons"], name)
            self.assertIn("seed_tree_mismatch", meta["pre_reasons"], name)
            result = self.finish(meta)
            self.assertEqual(result["verdict"], "rejected", name)
            sh(self.brain, "git", "reset", "-q", "--hard", delivery)

    def chmod_commit(self, path, files=None):
        """A commit that sets the executable bit of ``path`` (beside ``files``): git records a mode change only."""
        for rel, content in (files or {}).items():
            (self.brain / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.brain / rel).write_text(content)
        sh(self.brain, "git", "add", "-A")
        sh(self.brain, "git", "update-index", "--chmod=+x", path)
        sh(self.brain, "git", "commit", "-q", "-m", f"chmod +x {path}")
        return sh(self.brain, "git", "rev-parse", "HEAD")

    def test_a_mode_change_to_the_seed_is_a_founder_change_too(self):
        """(b), E184: the seed's tree hashes leave the executable bit out, git does not. A mode change under spec/tohum/
        or seed/ is rejected after the epoch as it is without one: beside code, and alone after an accepted push."""
        self.accept_mf1()
        delivery = self.deliver()
        self.finish(self.pull())
        for path in ("spec/tohum/00-cekirdek.md", "seed/bootstrap/vectors/new.json"):
            self.chmod_commit(path, {"referee/ledger/chain.py": "x = 9\n"})
            meta = self.pull()
            self.assertEqual(meta["kind"], "rejected", path)
            self.assertIn("seed_modified", meta["pre_reasons"], path)
            self.assertIn("seed_tree_mismatch", meta["pre_reasons"], path)
            self.assertEqual(self.finish(meta)["verdict"], "rejected", path)
            sh(self.brain, "git", "reset", "-q", "--hard", delivery)
        commit(self.brain, {"referee/ledger/chain.py": "x = 3\n"}, "accepted on top of the delivery")
        meta = self.pull()
        result = self.finish(meta, run=self.green_run(meta), rival=self.rival_ok(), jobs=CODE_JOBS)
        self.assertEqual(result["verdict"], "accepted", result["reasons"])
        self.chmod_commit("spec/tohum/29d-yeni.md")
        meta = self.pull()
        self.assertEqual(meta["changed"], ["spec/tohum/29d-yeni.md"])
        self.assertIn("seed_modified", meta["pre_reasons"])
        self.assertEqual(self.finish(meta)["verdict"], "rejected")

    def test_a_push_the_referee_cannot_read_is_not_charged_with_the_delivery(self):
        """E184: an unsafe or non-UTF-8 name leaves the tree unread, but the delivered seed in the diff is still the
        operator's: the rejection names the name alone, and no `seed_modified` streak points at the operator's seed."""
        self.accept_mf1()
        delivery = self.deliver()
        self.finish(self.pull())
        for raw, reason in ((b"x" + bytes([92]) + b"y.md", "unsafe_path"), (b"bad" + bytes([0xFF]) + b".md", "non_utf8_path")):
            self.commit_with_raw_name(raw)
            meta = self.pull()
            self.assertEqual((meta["kind"], meta["pre_reasons"]), ("rejected", [reason]), raw)
            result = self.finish(meta)
            self.assertEqual([r["kind"] for r in result["reasons"]], [reason], raw)
            self.assertNotIn("seed_modified:", result["state"]["reject_streaks"], raw)
            sh(self.brain, "git", "update-ref", "refs/heads/main", delivery)

    def test_a_brain_without_seed_gets_a_null_row_and_may_not_grow_one(self):
        """(b) `seed/` only when the brain has one: the row's seed_sha256 is null and the referee's bootstrap/ is
        read from the source repository the operator copied it from."""
        source = Path(self.tmp.name) / "snowball-mcp"
        source_sha = make_repo(source, {"seed/bootstrap/snowball_bootstrap/__init__.py": "VERSION = 2\n"})
        delivery = self.deliver({"spec/tohum/00-cekirdek.md": "# core, second epoch\n"},
                                "--source", str(source), "--source-commit", source_sha)
        row = json.loads(self.summary_path().read_text())["seed_epochs"][-1]
        self.assertEqual((row["commit"], row["seed_sha256"]), (delivery, None))
        self.assertEqual(row["bootstrap_sha256"], tree_hash(gitio.archive(source, source_sha), "seed/bootstrap",
                                                            forbid_operator_names=False))
        self.assertEqual(self.pull()["kind"], "seed_update")
        commit(self.brain, {"seed/x.py": "x = 1\n"}, "the Founder grows a seed/")
        meta = self.pull()
        self.assertEqual(meta["kind"], "rejected")
        self.assertIn("seed_tree_mismatch", meta["pre_reasons"])

    def test_the_signed_state_crosses_the_epoch(self):
        """(c) Frozen specs, streaks, proven defects and open claims are the referee's memory of the Founder; the
        epoch neither resets nor rewrites them, and the next push is judged against them."""
        accepted = self.accept_mf1()
        self.red_push(2)
        refutation = {"key": "0123456789abcdef", "claim": "the chain accepts a forged row", "evidence_refs": [],
                      "reproducer": {"cmd": "python -m ledger.chain verify /vec/x", "expect_exit": 1},
                      "first_head": accepted, "last_head": accepted}
        claim = {"id": "abcdef012345", "claim": "verify ignores prev_hash", "evidence_refs": [],
                 "reproducer": {"cmd": "python -m ledger.chain verify /vec/y", "expect_exit": 1}, "observed": None,
                 "first_head": accepted, "rewritten": False}
        self.state.update(open_refutations=[refutation], open_claims=[claim])
        before = json.loads(json.dumps(self.state))
        self.deliver()
        after = self.finish(self.pull())["state"]
        st.validate(after)  # still a state the next run can verify and read
        for key in ("frozen_specs", "reject_streaks", "repeat_events", "open_refutations", "open_claims",
                    "rival_artifacts", "last_accepted_sha", "month_spend_usd_micros", "stage_spend_usd_micros"):
            self.assertEqual(after[key], before[key], key)
        commit(self.brain, {"referee/ledger/chain.py": "x = 3\n"}, "still red, on top of the delivery")
        meta = self.pull()
        self.assertEqual(meta["state_repro"], [refutation["key"], claim["id"]])
        run = self.green_run(meta)
        run["tests"][0]["ok"], run["green"] = False, False
        result = self.finish(meta, run=run, jobs=RED_JOBS)
        self.assertEqual(result["learning"]["repeated"], [FIRST_TEST])  # the streak from before the epoch goes on
        self.assertEqual(result["state"]["reject_streaks"], {FIRST_TEST: 2})

    def test_a_summary_row_that_is_not_its_commits_stops_the_run(self):
        """An operator's mistake in the row stops the run before any push is judged against a seed nobody
        delivered; it never becomes the Founder's rejection."""
        self.deliver()
        good = json.loads(self.summary_path().read_text())
        row = good["seed_epochs"][-1]
        state_path = Path(self.tmp.name) / "state_bad_row.json"
        state_path.write_text(json.dumps(self.state))
        for name, bad in (("spec/tohum hash", dict(row, spec_tohum_sha256="0" * 64)),
                          ("seed/ hash", dict(row, seed_sha256=None)),
                          ("commit not pushed", dict(row, commit="1" * 40))):
            self.summary_path().write_text(json.dumps(dict(good, seed_epochs=[bad])))
            out = Path(self.tmp.name) / "pulled_bad_row"
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                rc = cli.main(["pull", "--root", str(self.referee), "--state", str(state_path), "--work",
                               str(Path(self.tmp.name) / "work"), "--out", str(out), "--remote", str(self.brain)])
            self.assertEqual(rc, 2, name)
            self.assertIn("stop: setup/summary.json: the last seed epoch", err.getvalue(), name)
            self.assertFalse((out / "meta.json").exists(), name)


class SummaryEpochsTest(unittest.TestCase):
    ROW = {"commit": "c" * 40, "spec_tohum_sha256": "d" * 64, "seed_sha256": None, "bootstrap_sha256": "e" * 64}
    BASE = {"seed_commit": "a" * 40, "seed_tree_sha256": "b" * 64, "targets": []}  # other summary fields stay unread

    def load(self, doc):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "setup").mkdir()
            (Path(tmp) / "setup" / "summary.json").write_text(json.dumps(doc))
            return load_summary(Path(tmp))

    def test_rows_are_read_strictly_and_the_last_one_rules(self):
        self.assertIsNone(self.load(self.BASE).epoch)
        later = dict(self.ROW, commit="f" * 40, seed_sha256="1" * 64)
        summary = self.load(dict(self.BASE, seed_epochs=[self.ROW, later]))
        self.assertEqual(len(summary.epochs), 2)
        self.assertEqual(summary.epoch, SeedEpoch("f" * 40, "d" * 64, "1" * 64, "e" * 64))
        without = {k: v for k, v in self.ROW.items() if k != "bootstrap_sha256"}
        for bad in ([], {}, ["row"], [dict(self.ROW, note="x")], [without], [dict(self.ROW, commit="C" * 40)],
                    [dict(self.ROW, commit="c" * 40 + "\n")], [dict(self.ROW, spec_tohum_sha256="d" * 63)],
                    [dict(self.ROW, seed_sha256="")], [dict(self.ROW, seed_sha256=1)],
                    [dict(self.ROW, bootstrap_sha256=None)], [self.ROW, dict(self.ROW, commit=None)]):
            with self.assertRaises(ConfigError, msg=repr(bad)):
                self.load(dict(self.BASE, seed_epochs=bad))

    def test_a_lost_state_starts_again_at_the_last_epochs_commit(self):
        """`25` "Durum kaybolursa": the referee starts from the last seed epoch's commit."""
        epochs = (SeedEpoch("c" * 40, "d" * 64, None, "e" * 64), SeedEpoch("f" * 40, "d" * 64, None, "e" * 64))
        self.assertEqual(st.initial(Summary("a" * 40, "b" * 64, epochs), "2026-10")["last_accepted_sha"], "f" * 40)
        self.assertEqual(st.initial(Summary("a" * 40, "b" * 64), "2026-10")["last_accepted_sha"], "a" * 40)


if __name__ == "__main__":
    unittest.main()
