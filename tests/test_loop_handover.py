"""Test 46 (asama-0/09), MF17: every artifact hand-over of ``loop.yml``, each edge proven or stated.

The edges are not listed by hand: ``edges(JOBS)`` derives them from ``loop.job.JOBS`` (a job that uploads an
artifact and a job that downloads it), the one source the workflow is rendered from. ``HANDOVER`` gives each edge
exactly one status, and ``problems`` checks it against what the code does:

- ``handover`` (a test id): the named test passes, and while it runs ``loop.job.run`` is called for the producer,
  which leaves ``$RUNNER_TEMP/out/<artifact>``, and later for the consumer, which finds ``$RUNNER_TEMP/in/<artifact>``
  with the same content (``digest``: every path, its kind and its bytes or link target) and returns ``done`` steps.
  So the test runs both jobs on the artifact as the upload and download hand it over, not each on its own fixture;
- ``unread`` (a test id): the named test passes and the consumer returns ``done`` steps while
  ``in/<artifact>`` is absent, so the consumer's wired steps do not read the download (a stated gap, with its why);
- ``unwired`` (a why): the producer, run on an empty ``$RUNNER_TEMP``, stops at once with ``cycle_not_wired``, no
  ``done`` step and no ``out/<artifact>``: nothing reaches the consumer in a real run;
- ``unwired_consumer`` (a why): the consumer, run on an empty ``$RUNNER_TEMP``, stops at once the same way (no
  ``done`` step, nothing uploaded): whatever the producer hands over, no wired step of the consumer reads it;
- ``unwritten`` (a test id): the producer's first steps are wired but it does not write the artifact yet: the named
  test passes, calls the producer at least once with a result ``cycle_not_wired`` (its wired steps ran to their
  end), and no call of the producer leaves ``out/<artifact>``: nothing reaches the consumer in a real run.

A register missing a derived edge, or naming one that is not derived, is a problem; so wiring a producer turns its
``unwired`` edges red until each names a hand-over test, and a new download needs a status in the same push.

Out of scope, stated: what the pinned upload and download actions do to the bytes (the copy here is
``shutil.copytree`` or a move; the actions' real transfer is asama-0/10a's live run), the digests the workflow
passes between jobs (``LOOP_<ARTIFACT>_DIGEST``, test_loop_workflow), and whether a consumer judges the artifact
correctly (each job's own tests).
"""

from __future__ import annotations

import functools
import importlib
import hashlib
import os
import shutil
import sys
import tempfile
import unittest
from typing import Any

REFEREE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REFEREE)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from loop import job as J  # noqa: E402
from profile_tree import write_tree  # noqa: E402

GETIR_TO_KOS = "test_loop_getir.HandOver.test_kos_installs_what_getir_fetched"
CEK_TO_ALL = "test_loop_cek.CekJob.test_getir_kos_cagir_and_yaz_run_on_the_pulled_cek_hands_over"
CEK_D1 = "test_loop_cek.CekJob.test_the_job_runs_d1_and_hands_pulled_to_the_upload"
KOS_TO_YAZ = "test_loop_yaz.YazJob.test_the_job_runs_d5_with_criterion_8_from_the_state"

# (artifact, consumer) -> (status, test id | why)
HANDOVER: dict[tuple[str, str], tuple[str, str]] = {
    ("pulled", "getir"): ("handover", CEK_TO_ALL),
    ("pulled", "kos"): ("handover", CEK_TO_ALL),
    ("pulled", "cagir"): ("handover", CEK_TO_ALL),
    ("pulled", "yaz"): ("handover", CEK_TO_ALL),
    ("deps", "kos"): ("handover", GETIR_TO_KOS),
    ("deps", "yaz"): ("unread", KOS_TO_YAZ),  # D5 reads D3's and D4's artifacts (asama-0/01); no wired step reads deps
    ("results", "yaz"): ("handover", KOS_TO_YAZ),
    ("response", "yaz"): ("handover", CEK_TO_ALL),  # D6 appends the response's cost row
}
STATUSES = ("handover", "unread", "unwired", "unwired_consumer", "unwritten")


def edges(jobs: dict[str, J.Job]) -> dict[tuple[str, str], str]:
    """``{(artifact, consumer): producer}`` for every download of every job."""
    producers = {job.upload: name for name, job in jobs.items() if job.upload}
    return {(artifact, name): producers[artifact] for name, job in jobs.items() for artifact in job.downloads}


def digest(path: str) -> str | None:
    """The content of a directory tree (relative paths, kinds, bytes, link targets), or ``None`` when absent."""
    if not os.path.isdir(path):
        return None
    h = hashlib.sha256()
    for root, dirs, files in os.walk(path):
        dirs.sort()
        for name in sorted(dirs + files):
            full = os.path.join(root, name)
            rel = os.path.relpath(full, path).encode()
            if os.path.islink(full):
                h.update(b"L%d:%s%s" % (len(rel), rel, os.readlink(full).encode()))
            elif os.path.isdir(full):
                h.update(b"D%d:%s" % (len(rel), rel))
            else:
                with open(full, "rb") as fh:
                    data = fh.read()
                h.update(b"F%d:%s%d:%s" % (len(rel), rel, len(data), data))
    return h.hexdigest()


class Call(dict):
    pass


def _artifacts(jobs: dict[str, J.Job]) -> tuple[tuple[str, tuple[str, ...], str | None], ...]:
    """What ``recorded`` reads of ``jobs``: each job's downloads and upload (the key of its cache)."""
    return tuple(sorted((name, tuple(job.downloads), job.upload) for name, job in jobs.items()))


def recorded(test_id: str, jobs: dict[str, J.Job]) -> tuple[bool, tuple[Call, ...]]:
    """Run one test with ``loop.job.run`` wrapped: whether it passed, and every call that returned, in order, with
    its job, its downloads' digests before the call, its result and its upload's digest after the call.

    A test runs once per process for one ``_artifacts(jobs)``: what it records does not depend on the register
    being checked, so every register (``Register``, each ``Proofs`` case) reads the same run. A test whose result
    changes between two runs in one process is judged by its first run."""
    return _recorded(test_id, _artifacts(jobs))


@functools.cache
def _recorded(test_id: str, artifacts: tuple[tuple[str, tuple[str, ...], str | None], ...]
              ) -> tuple[bool, tuple[Call, ...]]:
    io = {name: (downloads, upload) for name, downloads, upload in artifacts}
    calls: list[Call] = []
    real = J.run

    def run(name: str, environ: dict[str, str], *args: Any, **kwargs: Any) -> dict[str, Any]:
        temp = environ.get("RUNNER_TEMP") or ""
        downloads, upload = io.get(name, ((), None))
        seen = {a: digest(os.path.join(temp, "in", a)) for a in downloads}
        out = real(name, environ, *args, **kwargs)
        made = digest(os.path.join(temp, "out", upload)) if upload else None
        calls.append(Call(job=name, seen=seen, out=out, upload=made))
        return out

    try:
        suite = unittest.defaultTestLoader.loadTestsFromName(test_id)
    except (ImportError, AttributeError):
        return False, ()
    result = unittest.TestResult()
    J.run = run
    try:
        suite.run(result)
    finally:
        J.run = real
    return result.testsRun == 1 and result.wasSuccessful() and not result.skipped, tuple(calls)


def _done(out: dict) -> bool:
    """The call did a step: ``cek``'s ``done``, or a later job's for some served target (``loop.job.run``)."""
    return bool(out.get("done")) or any(t.get("done") for t in out.get("targets") or [])


def _handed_over(calls: tuple[Call, ...], artifact: str, producer: str, consumer: str) -> bool:
    for i, made in enumerate(calls):
        if made["job"] != producer or made["upload"] is None:
            continue
        for took in calls[i + 1:]:
            if took["job"] == consumer and took["seen"].get(artifact) == made["upload"] and _done(took["out"]):
                return True
    return False


def _unread(calls: tuple[Call, ...], artifact: str, consumer: str) -> bool:
    return any(c["job"] == consumer and c["seen"].get(artifact, "") is None and _done(c["out"]) for c in calls)


def _unwritten(calls: tuple[Call, ...], producer: str) -> bool:
    made = [c for c in calls if c["job"] == producer]
    return (any(c["out"].get("reason") == "cycle_not_wired" for c in made)
            and all(c["upload"] is None for c in made))


def _stops_at_once(producer: str, jobs: dict[str, J.Job]) -> bool:
    temp = tempfile.mkdtemp(prefix="t-handover-")
    try:
        try:
            out = J.run(producer, {"RUNNER_TEMP": temp})
        except J.Unusable:
            return False
        upload = jobs[producer].upload
        return (out.get("reason") == "cycle_not_wired" and not _done(out) and not out.get("ok")
                and not os.path.lexists(os.path.join(temp, "out", upload)))
    finally:
        shutil.rmtree(temp, ignore_errors=True)


def problems(register: dict[tuple[str, str], tuple[str, str]], jobs: dict[str, J.Job]) -> list[str]:
    derived = edges(jobs)
    found = ["unregistered:%s->%s" % e for e in sorted(set(derived) - set(register))]
    found += ["not_an_edge:%s->%s" % e for e in sorted(set(register) - set(derived))]
    for (artifact, consumer), (status, ref) in sorted(register.items()):
        if (artifact, consumer) not in derived:
            continue
        producer = derived[(artifact, consumer)]
        edge = "%s:%s->%s" % (artifact, producer, consumer)
        if status not in STATUSES or not (isinstance(ref, str) and ref):
            found.append("bad_status:%s" % edge)
        elif status == "unwired":
            if not _stops_at_once(producer, jobs):
                found.append("producer_wired:%s" % edge)
        elif status == "unwired_consumer":
            if not _stops_at_once(consumer, jobs):
                found.append("consumer_wired:%s" % edge)
        else:
            passed, calls = recorded(ref, jobs)
            if not passed:
                found.append("test_failed:%s:%s" % (edge, ref))
            elif status == "handover" and not _handed_over(calls, artifact, producer, consumer):
                found.append("not_handed_over:%s:%s" % (edge, ref))
            elif status == "unread" and not _unread(calls, artifact, consumer):
                found.append("not_unread:%s:%s" % (edge, ref))
            elif status == "unwritten" and not _unwritten(calls, producer):
                found.append("not_unwritten:%s:%s" % (edge, ref))
    return found


class Register(unittest.TestCase):
    def test_every_edge_of_the_workflow_holds_its_status(self):
        self.assertEqual(problems(HANDOVER, J.JOBS), [])

    def test_the_edges_are_the_workflows_downloads(self):
        self.assertEqual(edges(J.JOBS), {
            ("pulled", "getir"): "cek", ("pulled", "kos"): "cek", ("pulled", "cagir"): "cek",
            ("pulled", "yaz"): "cek", ("deps", "kos"): "getir", ("deps", "yaz"): "getir",
            ("results", "yaz"): "kos", ("response", "yaz"): "cagir"})

    def test_a_missing_or_extra_edge(self):
        register = dict(HANDOVER)
        del register[("response", "yaz")]
        register[("results", "cagir")] = ("unwired", "x")
        self.assertEqual(problems(register, J.JOBS)[:2], ["unregistered:response->yaz", "not_an_edge:results->cagir"])

    def test_a_new_download_needs_a_status(self):
        jobs = dict(J.JOBS)
        jobs["cagir"] = jobs["cagir"]._replace(needs=("cek", "getir"), downloads=("pulled", "deps"))
        self.assertIn("unregistered:deps->cagir", problems(HANDOVER, jobs))

    def test_a_bad_status(self):
        for entry in (("done", KOS_TO_YAZ), ("handover", ""), ("unwired", None)):
            with self.subTest(entry=entry):
                register = dict(HANDOVER)
                register[("response", "yaz")] = entry
                self.assertEqual(problems(register, J.JOBS), ["bad_status:response:cagir->yaz"])


class Proofs(unittest.TestCase):
    def check(self, key: tuple[str, str], entry: tuple[str, str]) -> list[str]:
        return problems(dict(HANDOVER) | {key: entry}, J.JOBS)

    def test_a_wired_producer_is_not_unwired(self):
        # getir runs D2 (on an empty RUNNER_TEMP it refuses the missing pulled, it does not stop as unwired)
        self.assertEqual(self.check(("deps", "kos"), ("unwired", "x")), ["producer_wired:deps:getir->kos"])

    def test_a_producer_that_writes_is_not_unwritten(self):
        # getir uploads deps in the hand-over test: not "unwritten"
        self.assertEqual(self.check(("deps", "kos"), ("unwritten", GETIR_TO_KOS)),
                         ["not_unwritten:deps:getir->kos:%s" % GETIR_TO_KOS])

    def test_a_test_that_never_runs_the_producer_is_not_unwritten(self):
        # cek's assembly test calls loop.cek.assemble, never the cek job
        name = "test_loop_cek.Brain.test_the_summary"
        self.assertEqual(self.check(("pulled", "kos"), ("unwritten", name)),
                         ["not_unwritten:pulled:cek->kos:%s" % name])

    def test_cek_is_not_unwired_any_more(self):
        # on an empty RUNNER_TEMP cek has no verdict (its variables are unset), it does not stop at once
        self.assertEqual(self.check(("pulled", "kos"), ("unwired", "x")), ["producer_wired:pulled:cek->kos"])

    def test_a_wired_consumer_is_not_unwired(self):
        # kos reads pulled (on an empty RUNNER_TEMP it refuses the missing download), and yaz reads results
        self.assertEqual(self.check(("pulled", "kos"), ("unwired_consumer", "x")), ["consumer_wired:pulled:cek->kos"])
        self.assertEqual(self.check(("results", "yaz"), ("unwired_consumer", "x")),
                         ["consumer_wired:results:kos->yaz"])

    def test_cek_writes_pulled_now(self):
        # the D1 test leaves out/pulled: not "unwritten" any more
        self.assertEqual(self.check(("pulled", "getir"), ("unwritten", CEK_D1)),
                         ["not_unwritten:pulled:cek->getir:%s" % CEK_D1])

    def test_a_producer_alone_is_not_a_hand_over(self):
        # the D1 test uploads pulled but runs no consumer on it
        self.assertEqual(self.check(("pulled", "kos"), ("handover", CEK_D1)),
                         ["not_handed_over:pulled:cek->kos:%s" % CEK_D1])

    def test_cagir_is_wired_as_producer_and_as_consumer(self):
        # on an empty RUNNER_TEMP cagir has no verdict (its variables are unset): it stops neither way at once
        self.assertEqual(self.check(("response", "yaz"), ("unwired", "x")), ["producer_wired:response:cagir->yaz"])
        self.assertEqual(self.check(("pulled", "cagir"), ("unwired_consumer", "x")),
                         ["consumer_wired:pulled:cek->cagir"])

    def test_kos_is_not_unwired_either(self):
        # kos is wired (D3, D7): on an empty RUNNER_TEMP its first refusal is the missing pulled, not cycle_not_wired
        self.assertEqual(self.check(("results", "yaz"), ("unwired", "x")), ["producer_wired:results:kos->yaz"])

    def test_the_consumer_without_the_artifact_is_not_a_hand_over(self):
        # getir then kos with no copy of out/deps: kos raises Unusable, so no consumer call returned
        name = "test_loop_getir.HandOver.test_without_the_artifact_kos_has_no_verdict"
        self.assertEqual(self.check(("deps", "kos"), ("handover", name)),
                         ["not_handed_over:deps:getir->kos:%s" % name])

    def test_a_changed_copy_is_not_a_hand_over(self):
        # kos runs (done D3) on a copy whose tarball byte was flipped: not the content getir wrote
        name = "test_loop_getir.HandOver.test_a_changed_tarball_byte_after_the_hand_over"
        self.assertEqual(self.check(("deps", "kos"), ("handover", name)),
                         ["not_handed_over:deps:getir->kos:%s" % name])

    def test_a_consumer_on_its_own_fixture_is_not_a_hand_over(self):
        # yaz's own tests write in/results through kos; a test of decide alone never calls the yaz job
        name = "test_loop_yaz.OneCycle.test_good_merges_bad_rejected_for_their_reasons"
        self.assertEqual(self.check(("results", "yaz"), ("handover", name)),
                         ["not_handed_over:results:kos->yaz:%s" % name])

    def test_an_artifact_the_consumer_had_is_not_unread(self):
        self.assertEqual(self.check(("deps", "kos"), ("unread", GETIR_TO_KOS)),
                         ["not_unread:deps:getir->kos:%s" % GETIR_TO_KOS])

    def test_an_unknown_or_failing_test(self):
        unknown = "test_loop_getir.HandOver.test_no_such_test"
        self.assertEqual(self.check(("deps", "kos"), ("handover", unknown)),
                         ["test_failed:deps:getir->kos:%s" % unknown])
        failing = "test_loop_handover.Failing.deliberately_fails"
        self.assertEqual(self.check(("deps", "kos"), ("handover", failing)),
                         ["test_failed:deps:getir->kos:%s" % failing])

    def test_a_class_name_is_not_one_test(self):
        name = "test_loop_getir.HandOver"
        self.assertEqual(self.check(("deps", "kos"), ("handover", name)), ["test_failed:deps:getir->kos:%s" % name])

    def test_digest_sees_bytes_names_kinds_and_links(self):
        base = tempfile.mkdtemp(prefix="t-handover-")
        self.addCleanup(shutil.rmtree, base, ignore_errors=True)
        root = os.path.join(base, "a")
        os.makedirs(os.path.join(root, "d"))
        with open(os.path.join(root, "d", "f"), "wb") as fh:
            fh.write(b"x")
        os.symlink("d/f", os.path.join(root, "l"))
        first = digest(root)
        self.assertEqual(digest(os.path.join(base, "none")), None)
        copy = os.path.join(base, "b")
        shutil.copytree(root, copy, symlinks=True)
        self.assertEqual(digest(copy), first)
        changes = {
            "byte": lambda r: write_tree(r, {"d/f": "y"}),
            "name": lambda r: os.rename(os.path.join(r, "d", "f"), os.path.join(r, "d", "g")),
            "link": lambda r: (os.remove(os.path.join(r, "l")), os.symlink("d", os.path.join(r, "l"))),
            "empty dir": lambda r: os.makedirs(os.path.join(r, "e")),
            "link to file": lambda r: (os.remove(os.path.join(r, "l")), shutil.copy(os.path.join(r, "d", "f"),
                                                                                  os.path.join(r, "l"))),
        }
        for label, change in changes.items():
            with self.subTest(change=label):
                other = os.path.join(base, label.replace(" ", "-"))
                shutil.copytree(root, other, symlinks=True)
                change(other)
                self.assertNotEqual(digest(other), first)


COUNTED = "test_loop_handover.Counted.counted"


def _runs() -> int:
    # the class the loader runs by name (under ``python tests/test_loop_handover.py`` this module is __main__)
    return importlib.import_module("test_loop_handover").Counted.runs


class Cache(unittest.TestCase):
    def test_a_test_runs_once_for_every_register(self):
        recorded(COUNTED, J.JOBS)
        before = _runs()
        for _ in range(3):
            self.assertEqual(recorded(COUNTED, J.JOBS), (True, ()))
        self.assertEqual(_runs(), before)

    def test_another_shape_of_the_jobs_runs_the_test_again(self):
        shapes = []
        for name in ("getir", "kos"):
            jobs = dict(J.JOBS)
            jobs[name] = jobs[name]._replace(upload=None)
            shapes.append(jobs)
        before = _runs()
        for jobs in shapes + shapes:
            recorded(COUNTED, jobs)
        self.assertEqual(_runs(), before + 2)

    def test_the_recording_follows_the_jobs_it_is_given(self):
        # kos downloads only pulled here: its calls record no deps, though J.JOBS's kos downloads deps too
        jobs = dict(J.JOBS)
        jobs["kos"] = jobs["kos"]._replace(downloads=("pulled",))
        full = [c["seen"] for c in recorded(CEK_TO_ALL, J.JOBS)[1] if c["job"] == "kos"]
        part = [c["seen"] for c in recorded(CEK_TO_ALL, jobs)[1] if c["job"] == "kos"]
        self.assertTrue(full and part)
        self.assertEqual([sorted(seen) for seen in full], [["deps", "pulled"]] * len(full))
        self.assertEqual(part, [{"pulled": seen["pulled"]} for seen in full])


class Counted(unittest.TestCase):
    """Run by name only, from ``Cache``: counts its runs across the process."""

    runs = 0

    def counted(self):
        type(self).runs += 1


class Failing(unittest.TestCase):
    """Run by name only, from ``Proofs.test_an_unknown_or_failing_test``: its method is not ``test_*``, so
    discovery does not collect it."""

    def deliberately_fails(self):
        self.fail("deliberately")


if __name__ == "__main__":
    unittest.main()
