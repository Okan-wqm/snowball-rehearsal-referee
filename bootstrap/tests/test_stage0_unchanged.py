"""Stage 0 is judged as before while no lock exists (E402): every exit request shape, through the real `pull` and
`decide` commands, gives the base's meta and signed result, field for field once the run's own commit SHAs and
content hashes are named.

The expected outputs are recorded from the seed this branch was built on, without the activation tooling: main
`6dcf8e8` (first `merge/train2` `d7706b8`; main's E390-E399 changed one `not_checked:spec` detail since, so the record
moved with it, E477; main's E426 added `exam_faults` to the meta and the signed result, E488), not computed here: run
this file as a script on that tree's `seed/bootstrap` to record them again
(``python tests/test_stage0_unchanged.py --record <file>``). Two histories are
judged: after an accepted MF1 push (each shape, every exit rejected), and after all of Stage 0 was accepted, where
the plain request is accepted and transferable once what the seed cannot check yet is set aside (as `test_flow`'s
import test does). A difference in any field of either document, for any shape, fails: the Stage 1 tooling may
change nothing the bootstrap referee signs before `stage-open` wrote `setup/stage.json` (`asama-0/10a`: the Stage 1
table holds only after the lock).
"""

import hashlib
import json
import os
import re
import sys
import unittest
from pathlib import Path
from unittest import mock

from snowball_bootstrap import cli, gitio
from snowball_bootstrap.treehash import tree_hash

from helpers import LOOP_YML, commit, ledger_bytes, ledger_rows, sh
from test_flow import ALL_MFS, Flow, all_tests_manifest

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "stage0" / "exit-requests-6dcf8e8.json"
TOY = "tests/fixtures/toy-repo"
# Each shape is what `exit-request.json` holds, over `{stage: 0, sha: <last accepted>, spec_sha256: <frozen>}`;
# a value DROP leaves the key out, RAW replaces the whole document with the given text.
DROP = "<drop>"
SHAPES = {
    "plain": {},
    "batch_str": {"batch": "P1"},
    "batch_other_str": {"batch": "P2"},
    "batch_int": {"batch": 5},
    "batch_null": {"batch": None},
    "batch_empty": {"batch": ""},
    "batch_malformed": {"batch": "no good!"},
    "batch_list": {"batch": ["P1"]},
    "stage1": {"stage": 1},
    "stage1_batch": {"stage": 1, "batch": "P1"},
    "stage_bool": {"stage": True},
    "wrong_sha": {"sha": "a" * 40},
    "wrong_sha_batch": {"sha": "a" * 40, "batch": "P1"},
    "wrong_spec": {"spec_sha256": "b" * 64},
    "wrong_spec_batch": {"spec_sha256": "b" * 64, "batch": "P1"},
    "stage1_wrong_spec_batch": {"stage": 1, "spec_sha256": "b" * 64, "batch": "P1"},
    "extra_key": {"note": "x"},
    "missing_spec": {"spec_sha256": DROP},
    "missing_spec_batch": {"spec_sha256": DROP, "batch": "P1"},
    "not_an_object": {"RAW": "[0]"},
}
COMPLETE = ("plain", "batch_str", "batch_null", "stage1", "stage1_batch", "wrong_sha_batch")
HEX = re.compile(r"\b[0-9a-f]{40}(?:[0-9a-f]{24})?\b")


def request_bytes(base: dict, shape: dict) -> bytes:
    if "RAW" in shape:
        return shape["RAW"].encode("utf-8")
    req = dict(base)
    for key, value in shape.items():
        if value == DROP:
            req.pop(key, None)
        else:
            req[key] = value
    return json.dumps(req).encode("utf-8")


def named(value, names: dict[str, str]):
    """``value`` with every commit SHA or hash this run made (not one a fixture fixes) replaced by its role's name."""
    if isinstance(value, dict):
        return {named(k, names): named(v, names) for k, v in value.items()}
    if isinstance(value, list):
        return [named(v, names) for v in value]
    if isinstance(value, str):
        return HEX.sub(lambda m: names.get(m.group(0), m.group(0)), value)
    return value


class Judge(Flow):
    """The real commands over local repositories (`test_flow.Flow`)."""

    def judge(self, label: str, accepted: str, frozen: str, shape: dict, names: dict[str, str]) -> dict:
        """One exit request on top of ``accepted``: `pull`, then the `decide` command as the workflow runs it."""
        sh(self.brain, "git", "reset", "-q", "--hard", accepted)
        raw = request_bytes({"stage": 0, "sha": accepted, "spec_sha256": frozen}, shape)
        head = commit(self.brain, {"exit-request.json": raw}, label)
        meta = self.pull()
        run = Path(self.tmp.name) / f"run-{self.n}"
        run.mkdir()
        (run / "run.json").write_text(json.dumps(self.green_run(meta)), encoding="utf-8")
        pulled, out = Path(self.tmp.name) / f"pulled{self.n}", Path(self.tmp.name) / f"decided-{self.n}"
        env = {k: v for k, v in os.environ.items() if k not in ("GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT")}
        with mock.patch.dict(os.environ, env, clear=True), \
                mock.patch.object(cli, "utc_now", return_value="2026-11-01T00:00:00Z"):
            rc = cli.main(["decide", "--root", str(self.referee), "--pulled", str(pulled), "--run", str(run),
                           "--job", "getir=success", "--job", "kos=success", "--out", str(out)])
        self.assertEqual(rc, 0, label)
        result = json.loads((out / "result.json").read_text(encoding="utf-8"))
        # Content hashes are named too, each computed here from the commit (the blobs' bytes follow the checkout's
        # line endings): the code's own value is compared, under its name, only when it is this one.
        tar = gitio.archive(self.brain, head)
        names = dict(names, **{accepted: "<accepted>", head: "<head>", frozen: "<frozen_spec>",
                               hashlib.sha256(raw).hexdigest(): "<request_sha256>",
                               tree_hash(tar, "referee"): "<referee_tree>"})
        if any(p.startswith(TOY + "/") for p in sh(self.brain, "git", "ls-files").splitlines()):
            names[tree_hash(tar, TOY, forbid_operator_names=False)] = "<toy_tree>"
        return {"meta": named(meta, names), "result": named(result, names)}

    def judge_all(self) -> dict:
        found = {}
        # After an accepted MF1 push: every shape, every exit rejected (not all micro-features are done).
        self.freeze_stage0()
        names = {self.seed_sha: "<seed>", sh(self.brain, "git", "rev-parse", "HEAD"): "<spec>"}
        jobs = {"getir": "success", "kos": "success", "cagir": "success", "yeniden": "skipped"}
        commit(self.brain, {"referee/ledger/chain.py": "x = 1\n", "snowball-tests.json": all_tests_manifest([1])}, "mf1")
        meta = self.pull()
        self.assertEqual(self.finish(meta, run=self.green_run(meta), rival=self.rival_ok(), jobs=jobs)["verdict"],
                         "accepted")
        accepted, frozen, saved = self.state["last_accepted_sha"], self.state["frozen_specs"]["spec/asama-0"], \
            json.dumps(self.state)
        for name, shape in SHAPES.items():
            self.state = json.loads(saved)
            found[name] = self.judge(name, accepted, frozen, shape, names)
        # After all of Stage 0 was accepted (`test_flow`'s import test): the plain request is transferable once what
        # the seed cannot check yet is set aside; the other shapes are what they are.
        summary = self.referee / "setup" / "summary.json"
        summary.write_text(json.dumps(dict(json.loads(summary.read_text()), targets=[
            {"id": "copy", "repo": "owner/copy", "kind": "copy", "base_sha": "c" * 40, "identifiers": ["Zorbalix"],
             "excluded_paths": [], "unit_candidates": []}])))
        files = {"referee/.github/workflows/loop.yml": LOOP_YML.encode(), f"{TOY}/app.py": "import os\n",
                 "founder-ledger.jsonl": ledger_bytes(ledger_rows(2)), "snowball-tests.json": all_tests_manifest(ALL_MFS)}
        sh(self.brain, "git", "reset", "-q", "--hard", accepted)
        commit(self.brain, files, "all of stage 0")
        self.state = json.loads(saved)
        meta = self.pull()
        self.assertEqual(self.finish(meta, run=self.green_run(meta), rival=self.rival_ok(), jobs=jobs)["verdict"],
                         "accepted")
        self.state["rival_artifacts"].append({"sha": "f" * 40, "outcome": "survived"})  # one more reviewed artefact
        complete, saved = self.state["last_accepted_sha"], json.dumps(self.state)
        names = dict(names, **{accepted: "<mf1>"})
        for name in COMPLETE:
            self.state = json.loads(saved)
            with mock.patch("snowball_bootstrap.decide.EXIT_NOT_CHECKED", {}):
                found[f"complete/{name}"] = self.judge(name, complete, frozen, SHAPES[name], names)
        self.assertEqual(found["complete/plain"]["result"]["exit"]["transferable"], True)
        return found


class StageZeroUnchangedTest(Judge):
    def test_every_exit_request_shape_is_judged_as_the_base_judged_it(self):  # stage0_batch_key_allowed
        expected = json.loads(FIXTURE.read_text(encoding="utf-8"))
        found = self.judge_all()
        self.assertEqual(sorted(found), sorted(expected))
        for name in sorted(found):
            for doc in ("meta", "result"):
                with self.subTest(shape=name, doc=doc):
                    self.assertEqual(found[name][doc], expected[name][doc])

    def test_the_fixture_is_the_recording_of_every_shape(self):
        expected = json.loads(FIXTURE.read_text(encoding="utf-8"))
        self.assertEqual(sorted(expected), sorted(list(SHAPES) + [f"complete/{n}" for n in COMPLETE]))
        verdicts = {name: (doc["meta"]["pre_reasons"], doc["result"]["verdict"]) for name, doc in expected.items()}
        self.assertEqual(verdicts["batch_str"][0][:1], ["exit_request_malformed"])  # main: a batch key is malformed
        self.assertEqual(verdicts["complete/plain"], ([], "accepted"))
        self.assertEqual(verdicts["complete/batch_str"][0][:1], ["exit_request_malformed"])
        self.assertEqual(sum(v == "accepted" for _p, v in verdicts.values()), 1)


def load_tests(loader, tests, pattern):
    """Only this module's own tests: `Judge` is a `test_flow.Flow`, whose tests run in their own module."""
    return unittest.TestSuite(StageZeroUnchangedTest(name) for name in vars(StageZeroUnchangedTest)
                              if name.startswith("test"))


if __name__ == "__main__" and sys.argv[1:2] == ["--record"]:
    target = Path(sys.argv[2])

    class Record(Judge):
        def runTest(self):
            found = self.judge_all()  # one line per shape: a difference names its shape in a diff
            lines = [f"{json.dumps(name)}: {json.dumps(found[name], sort_keys=True)}" for name in sorted(found)]
            target.write_bytes(("{\n" + ",\n".join(lines) + "\n}\n").encode("utf-8"))

    sys.exit(not unittest.TextTestRunner(verbosity=1).run(Record()).wasSuccessful())
