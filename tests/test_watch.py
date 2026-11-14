"""Test 46 (asama-0/09), MF17, D7's half in ``yaz``: ``loop.watch`` reads the sentinel ``kos`` wrote and builds the
facts of a red (asama-0/01 D7, tohum/07, tohum/29j).

- ``read``: nothing watched and no entry is ``None``; an entry while nothing is watched, an entry for another merge
  or none (an index that is not a JSON object, a results path that is not a directory), a file that is missing, a
  directory, changed or not the index's hash, a document that does not parse or is of another shape or merge, and a
  verdict MF12's ``decide`` does not give on its runs (or the index does not) are each refused with their reason;
  an entry without a verdict is passed on with its reasons; a verified red, green and flaky are read with the
  verified file's hash;
- ``base_lint``: the base run's counts when its hash is the index's and its three records one; ``None`` for a
  missing file (``base_run`` too, with the index's hash), another hash, three records that differ, a record
  ``gate.check`` refuses, no hash in the index;
- ``base_build``: ``false`` for a base refused with a ``lint_output:fatal:`` reason (ESLint could not parse a file),
  unless a red control passed or the base run is verified anyway; ``true`` for no reason and a verified base run;
  ``None`` for any other reason (``lint_output:fatal:`` not at its start included), a missing or malformed ``base``, no reason without a verified run (bound to what
  ``runner.kos`` really writes in ``test_kos.Sentinel``);
- ``facts``: the impact set is every id the runs report; ``build_ok`` is the one given; lint per tool in either side,
  an absent tool counting 0 (an empty ratchet base too), tools in sorted order; ``None`` lint when the merge's cycle has no ratchet base or the base lint is unreadable;
  ``gate.revert.assess`` then gives ``build_break``, ``test_regression``, ``lint_regression`` or ``unknown``
  (``unknown`` whenever ``build_ok`` is ``None``).
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import tempfile
import unittest

REFEREE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REFEREE)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from gate import revert as R  # noqa: E402
from gate import sentinel as S  # noqa: E402
from loop import watch as WT  # noqa: E402
from runner import kos as K  # noqa: E402
from test_revert_drill import ledger_with, plant, row  # noqa: E402
from test_serial import merge  # noqa: E402

M = "1" * 40
FAIL = {"results": [{"id": "a", "status": "fail"}, {"id": "b", "status": "pass"}]}
PASS = {"results": [{"id": "a", "status": "pass"}, {"id": "b", "status": "pass"}]}
EXTRA = {"results": [{"id": "a", "status": "fail"}, {"id": "c", "status": "pass"}]}


def record(tool: str, n: int) -> bytes:
    return json.dumps({"tool": tool, "violations": [{"rule_id": "r", "path": "a.js", "line": i + 1, "fix": None}
                                                    for i in range(n)]}).encode()


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class Results(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = tempfile.mkdtemp(prefix="t-watch-")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)

    def put(self, name: str, data: bytes) -> None:
        with open(os.path.join(self.dir, name), "wb") as fh:
            fh.write(data)

    def results(self, runs=None, entry=None, doc=None, base=None, base_sha=None, verdict=None) -> str:
        """An index, and a sentinel file for ``runs`` (its verdict MF12's) unless ``doc`` is given; ``verdict`` the
        index's ``base``."""
        index = {"base_run_sha256": base_sha if base_sha is not None else (sha(base) if base else None),
                 "candidates": {}, "sentinel": None}
        if verdict is not None:
            index["base"] = verdict
        if runs is not None or doc is not None:
            if doc is None:
                got = S.decide(runs)
                doc = {"merge_sha": M, "runs": runs, "verdict": got["verdict"], "red": got["red"], "flaky": got["flaky"]}
            data = json.dumps(doc).encode()
            self.put(K.SENTINEL, data)
            index["sentinel"] = {"merge_sha": M, "verdict": doc.get("verdict"), "reasons": [], "sha256": sha(data)}
        if entry is not None:
            index["sentinel"] = entry
        if base is not None:
            self.put(K.BASE, base)
        self.put(K.INDEX, json.dumps(index).encode())
        return self.dir


class Read(Results):
    def refused(self, results: str, watch=M) -> list[str]:
        with self.assertRaises(WT.Refused) as ctx:
            WT.read(results, watch)
        return ctx.exception.reasons

    def test_verified_verdicts(self):
        for runs, verdict, red, flaky in (([FAIL] * 4, "red", ["a"], []), ([PASS], "green", [], []),
                                          ([FAIL, PASS, PASS, PASS], "flaky", [], ["a"])):
            with self.subTest(verdict=verdict):
                got = WT.read(self.results(runs), M)
                with open(os.path.join(self.dir, K.SENTINEL), "rb") as fh:
                    file_sha = sha(fh.read())
                self.assertEqual(got, {"merge_sha": M, "verdict": verdict, "runs": runs, "red": red, "flaky": flaky,
                                       "sha256": file_sha})

    def test_nothing_watched(self):
        self.assertIsNone(WT.read(self.results(), None))
        self.assertEqual(self.refused(self.results([PASS]), None), ["sentinel_unexpected"])

    def test_no_verdict_is_passed_on(self):
        entry = {"merge_sha": M, "verdict": None, "reasons": ["red_control_green"], "sha256": None}
        self.assertEqual(WT.read(self.results(entry=entry), M),
                         {"merge_sha": M, "verdict": None, "reasons": ["red_control_green"]})

    def test_the_entry_must_name_the_watched_merge(self):
        self.assertEqual(self.refused(self.results()), ["sentinel_missing"])
        self.assertEqual(self.refused(self.results([PASS]), "2" * 40), ["sentinel_missing"])
        self.put(K.INDEX, b"not json")
        self.assertEqual(self.refused(self.dir), ["sentinel_missing"])
        self.put(K.INDEX, b"[]")  # JSON, but not an object
        self.assertEqual(self.refused(self.dir), ["sentinel_missing"])
        as_file = os.path.join(self.dir, "results-a-file")  # the results path is not a directory
        self.put("results-a-file", b"")
        self.assertEqual(self.refused(as_file), ["sentinel_missing"])
        self.assertIsNone(WT.base_lint(as_file))
        self.assertIsNone(WT.base_build(as_file))

    def test_the_file_by_its_hash(self):
        results = self.results([FAIL] * 4)
        with open(os.path.join(results, K.SENTINEL), "ab") as fh:
            fh.write(b" ")
        self.assertEqual(self.refused(results), ["sentinel_hash_mismatch"])
        os.remove(os.path.join(results, K.SENTINEL))
        self.assertEqual(self.refused(results), ["sentinel_hash_mismatch"])
        os.mkdir(os.path.join(results, K.SENTINEL))  # a directory where the file should be
        self.assertEqual(self.refused(results), ["sentinel_hash_mismatch"])

    def test_the_document_shape_and_merge(self):
        good = {"merge_sha": M, "runs": [PASS], "verdict": "green", "red": [], "flaky": []}
        for doc in (dict(good, merge_sha="2" * 40), dict(good, extra=1), {k: v for k, v in good.items() if k != "red"},
                    dict(good, runs=[{"results": 1}]), [good]):
            with self.subTest(doc=doc):
                if isinstance(doc, list):
                    data = json.dumps(doc).encode()
                    self.put(K.SENTINEL, data)
                    results = self.results(entry={"merge_sha": M, "verdict": "green", "reasons": [], "sha256": sha(data)})
                else:
                    results = self.results(doc=doc)
                self.assertEqual(self.refused(results), ["sentinel_unreadable"])
        data = b"not json"  # bytes of the index's hash that do not parse
        self.put(K.SENTINEL, data)
        results = self.results(entry={"merge_sha": M, "verdict": "green", "reasons": [], "sha256": sha(data)})
        self.assertEqual(self.refused(results), ["sentinel_unreadable"])

    def test_the_verdict_is_mf12s_on_the_runs(self):
        base = {"merge_sha": M, "runs": [FAIL] * 4, "verdict": "red", "red": ["a"], "flaky": []}
        for doc in (dict(base, verdict="green"), dict(base, red=[]), dict(base, flaky=["b"]),
                    dict(base, runs=[PASS], verdict="red")):
            with self.subTest(doc=doc):
                self.assertEqual(self.refused(self.results(doc=doc)), ["sentinel_verdict_mismatch"])
        results = self.results([FAIL] * 4)
        with open(os.path.join(results, K.INDEX)) as fh:
            index = json.load(fh)
        index["sentinel"]["verdict"] = "green"  # the index says another verdict than its file
        self.put(K.INDEX, json.dumps(index).encode())
        self.assertEqual(self.refused(results), ["sentinel_verdict_mismatch"])


class BaseLint(Results):
    def test_the_counts_of_a_verified_base(self):
        base = (record("eslint", 2) + b"\n") * 3
        self.assertEqual(WT.base_lint(self.results(base=base)), {"base_run_sha256": sha(base), "counts": {"eslint": 2}})

    def test_none_when_it_cannot_be_read(self):
        same = (record("eslint", 2) + b"\n") * 3
        for base, base_sha in ((None, None), (same, "f" * 64), (record("eslint", 2) + b"\n" + record("eslint", 3)
                                                                 + b"\n" + record("eslint", 2) + b"\n", None),
                               (b"{}\n{}\n{}\n", None), (same[:-1] + b"\n\n", None)):
            with self.subTest(base=base, base_sha=base_sha):
                shutil.rmtree(self.dir)
                os.makedirs(self.dir)
                self.assertIsNone(WT.base_lint(self.results(base=base, base_sha=base_sha)))
        shutil.rmtree(self.dir)
        os.makedirs(self.dir)
        self.put(K.BASE, same)
        self.put(K.INDEX, b"{}")  # no base_run_sha256
        self.assertIsNone(WT.base_lint(self.dir))
        os.remove(os.path.join(self.dir, K.BASE))  # the index's hash, no file
        self.put(K.INDEX, json.dumps({"base_run_sha256": sha(same)}).encode())
        self.assertIsNone(WT.base_run(self.dir))
        self.assertIsNone(WT.base_lint(self.dir))
        self.put(K.BASE, same)
        self.assertEqual(WT.base_run(self.dir), (same, sha(same)))


FATAL_A = "lint_output:fatal:pkg/a.js"


class BaseBuild(Results):
    BASE = (record("eslint", 2) + b"\n") * 3

    def build(self, reasons, base=None) -> bool | None:
        verdict = {"verdict": "refused" if reasons else "verified", "reasons": reasons}
        return WT.base_build(self.results(base=base, verdict=verdict))

    def test_a_file_the_lint_could_not_parse_is_a_build_break(self):
        self.assertIs(self.build([FATAL_A]), False)
        self.assertIs(self.build(["lint_output:fatal:pkg/b.js", FATAL_A, "lint_output:message_unusable:pkg/c.js"]),
                      False)

    def test_a_verified_base_run_is_a_build(self):
        self.assertIs(self.build([], self.BASE), True)

    def test_none_when_the_lint_told_nothing_about_parsing(self):
        for reasons, base in (([], None),  # no reason, but no verified base run
                              (["lint_failed:1"], None), (["limit_hit:kos_wall_s"], None),
                              (["lint_output:not_eslint_json"], None), (["services_not_empty"], None),
                              (["red_control_green", FATAL_A], None),  # a sandbox a bad command passed
                              ([FATAL_A], self.BASE),  # the index contradicts its own base run
                              (["red_control_green"], self.BASE),
                              (["lint_failed:" + FATAL_A], None)):  # the prefix only: no reason of another kind
            with self.subTest(reasons=reasons, base=base is not None):
                shutil.rmtree(self.dir)
                os.makedirs(self.dir)
                self.assertIsNone(self.build(reasons, base))

    def test_none_without_a_readable_base(self):
        for verdict in ({}, {"verdict": "refused"}, {"reasons": FATAL_A}, {"reasons": [FATAL_A, 1]}, [FATAL_A]):
            with self.subTest(verdict=verdict):
                self.assertIsNone(WT.base_build(self.results(verdict=verdict)))
        self.assertIsNone(WT.base_build(self.results()))  # no base in the index
        self.put(K.INDEX, b"not json")
        self.assertIsNone(WT.base_build(self.dir))


def cycle(sha_: str, counts: dict | None) -> list[dict]:
    rows = [row("s", "events", "cycle_start", {"cycle_id": "8"})]
    if counts is not None:
        rows.append(row("b", "events", "ratchet_base", {"base_run_sha256": "e" * 64, "counts": counts}))
    return rows + [merge("c", sha_)]


class Facts(unittest.TestCase):
    def red(self, runs=None) -> dict:
        return {"merge_sha": M, "verdict": "red", "runs": runs or [FAIL] * 4, "red": ["a"], "flaky": []}

    def test_impact_build_and_lint(self):
        got = WT.facts(self.red([FAIL, EXTRA, FAIL, FAIL]), ledger_with(cycle(M, {"eslint": 3, "old": 1})),
                       {"base_run_sha256": "e" * 64, "counts": {"eslint": 3, "new": 2}}, True)
        self.assertEqual(got, {"impact": ["a", "b", "c"], "build_ok": True,
                               "lint": {"eslint": {"before": 3, "after": 3}, "new": {"before": 0, "after": 2},
                                        "old": {"before": 1, "after": 0}}})
        self.assertEqual(list(got["lint"]), ["eslint", "new", "old"])  # tools in sorted order
        self.assertEqual(R.assess([FAIL] * 4, got)["cause"], "lint_regression")  # "new" rose
        same = dict(got, lint={"eslint": {"before": 3, "after": 3}})
        self.assertEqual(R.assess([FAIL] * 4, same)["cause"], "test_regression")

    def test_build_ok_is_the_one_given(self):
        ledger = ledger_with(cycle(M, {"eslint": 3}))
        after = {"base_run_sha256": "e" * 64, "counts": {"eslint": 3}}
        for build_ok, cause in ((False, "build_break"), (True, "test_regression"), (None, "unknown")):
            with self.subTest(build_ok=build_ok):
                got = WT.facts(self.red(), ledger, after, build_ok)
                self.assertIs(got["build_ok"], build_ok)
                self.assertEqual(R.assess([FAIL] * 4, got)["cause"], cause)
        # a head that does not parse has no base run (kos writes none), so no lint after: still a build break
        self.assertEqual(R.assess([FAIL] * 4, WT.facts(self.red(), ledger, None, False))["cause"], "build_break")

    def test_an_empty_ratchet_base_counts_every_tool_from_zero(self):
        got = WT.facts(self.red(), ledger_with(cycle(M, {})), {"base_run_sha256": "e" * 64, "counts": {"eslint": 3}},
                       True)
        self.assertEqual(got["lint"], {"eslint": {"before": 0, "after": 3}})
        self.assertEqual(R.assess([FAIL] * 4, got)["cause"], "lint_regression")

    def test_lint_none_without_before_or_after(self):
        after = {"base_run_sha256": "e" * 64, "counts": {"eslint": 3}}
        for ledger, after_ in ((ledger_with(cycle(M, None)), after), (ledger_with(cycle(M, {"eslint": 3})), None),
                               (ledger_with([row("s", "events", "cycle_start", {"cycle_id": "8"}),
                                             plant("p", "i1", M)]), after)):
            with self.subTest(after=after_):
                got = WT.facts(self.red(), ledger, after_, True)
                self.assertIsNone(got["lint"])
                self.assertEqual(R.assess([FAIL] * 4, got)["cause"], "unknown")


if __name__ == "__main__":
    unittest.main()
