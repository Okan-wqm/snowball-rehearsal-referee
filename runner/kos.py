"""``koş``'s results: the files the gate reads, made from contained runs of the base tree and of each candidate's
tree (stage 0; the D3 part of the ``kos`` job that ``gate.check`` and ``activate`` read).

Rules: asama-0/01 D3 (``koş`` reads the pulled tree, the ``deps`` artifact, the recipe and the candidates and
writes result files whose hashes are taken outside the containers), asama-0/08 criteria 3, 5, 6 and 7 (the tool
three times, byte for byte; the ratchet; the affected tests, in stage 0 the unit's whole service-free test set;
the red control), tohum/08 items 2-3, tohum/01b (the gate reads results by artifact and hash), tohum/04 (zero
tests is red). It calls MF6's staging (``profile.unit_verify.stage``: the static check, the inputs' closure, the
dependencies, the install scripts; so the worktree is the one ``unit.verify`` proves), MF3 through
``unit_verify``'s contained runs (fresh directory per run, no network, red control in every run),
``runner.lint_record`` (the run record) and MF7's diff parser and ``apply``. It writes what ``gate.check
decide`` (MF8) and ``activate`` (MF18) read; it decides nothing.

**OUT** (a directory that must not exist; ``index.json`` is written last)::

    base.jsonl                          three lint runs of the base worktree, one run record per line
    c/<cid>/cand.jsonl                  three lint runs of the candidate's worktree
    c/<cid>/checks.json                 {red_control: pass|fail, tests: [{id, status: pass|fail}]}
    c/<cid>/hashes.json                 {"base.jsonl", "cand.jsonl", "checks.json"}: sha256 of the bytes written
    sentinel.json                       {merge_sha, runs, verdict, red, flaky}: only when a merge is watched
    index.json                          {base: {verdict, reasons}, base_run_sha256,
                                         candidates: {cid: {verdict, reasons}},
                                         sentinel: null | {merge_sha, verdict, reasons, sha256}}

Verdicts are ``unit_verify``'s classes: ``verified`` (the files are written and no reason holds), ``refused`` (a
reason about the tree: the candidate's or the base's), ``no_verdict`` (a run that tells nothing: a limit, an
invalid contained run, a green red control, a base that gave no run file).

**The base.** ``stage`` on the pulled tree, then ``lint_cmd`` three times, each in its own contained run. Each run
must end ``ok`` with exit 0 or 1 (``lint_failed:<n>``) and convert (``lint_output:<reason>``); any reason of a
contained run, ``red_control_green`` included, stops the base: no ratchet base comes from a sandbox that a known
bad command passed. ``base.jsonl`` holds the three records in run order even when they differ: the gate and
genesis judge that (``tool_nondeterministic``), this module records it. Without ``base.jsonl`` no candidate runs
(``base_unavailable``).

**A candidate** ``cid`` (a directory holding ``diff.patch``; only that file is read). ``cid`` is
``[A-Za-z0-9][A-Za-z0-9._-]{0,127}`` (else ``candidate_id_invalid``, nothing written for it). Its worktree is a
fresh copy of the base worktree (symlinks copied as symlinks), so no candidate sees another's change. The diff is
parsed by ``gate.diffguard.parse`` (``patch_unusable``); every block must change one file in place
(``patch_not_in_place``), whose path is relative and normal (``patch_path_invalid``), not under ``.snowball``, the
runs' own directory (``reserved_path``), and a regular file of the worktree with no symlink on its way
(``base_file_missing``: a file outside the recipe's ``inputs`` is not in the worktree); ``gate.diffguard.apply``
must apply it there (``patch_does_not_apply``). Then ``lint_cmd`` three times and ``test_cmd`` once (its wall
clock capped by ``test_total_s``), each in its own contained run. When every run ended ``ok``, every lint run
exited 0 or 1 and converts, the three files are written; ``red_control`` is ``pass`` when a run's red control
passed (the gate's criterion 7 rejects it; the index says ``red_control_green``). Any other reason of a contained
run (a limit, ``red_control_fault``, ``runner_fault``, ``breach:``, ``unreadable_output``) writes no file.

**The tests** (``tap_tests``): the TAP the test command prints on stdout (``node --test``'s default reporter when
stdout is not a terminal; the recipe's ``test_cmd``). A test is a top-level line ``ok N`` or ``not ok N``,
optionally `` - description``, at column 0; indented lines are subtests and are not counted, as ``node --test``
indents them. Its ``id`` is the description with TAP's ``\\#`` and ``\\\\`` escapes undone (the number when there
is none); a line whose directive (after the first unescaped `` # ``) starts with ``SKIP`` or ``TODO`` (any case)
is left out: a skipped test did not run and a failing TODO test does not fail the run. When the command exits
non-zero and no listed test failed, one entry ``{id: "test_cmd exit <code>", status: fail}`` is added, so a
crash or a ``Bail out!`` is red, not zero tests. Out of scope: other reporters and test runners (they give no
TAP line, so ``tests`` is empty and the gate's ``zero_tests`` rejects: closed, not open), and duplicate
descriptions (each line is its own entry).

**The sentinel** (D7, MF12; ``watch``, a merge SHA, given by the caller: the merge whose sentinel has not finished,
which must be the tree's own commit). With no ``watch`` the index's ``sentinel`` is ``null`` and nothing more runs.
With one, after the base's lint runs and whatever they gave, the recipe's ``affected_test_cmd`` (stage 0's affected
set is the unit's whole service-free test set, asama-0/08 item 6) runs at the staged base worktree, each run its
own contained run with the red control, its wall clock capped by ``test_total_s``; each run's ``results`` is
``tap_tests`` of its stdout and exit (the TAP rules above). ``gate.sentinel.watch`` asks for the runs: one when the
first is green, four (run 1 and three reruns) otherwise. ``sentinel.json`` holds the merge SHA, every run used and
``gate.sentinel``'s verdict (``green``, ``flaky`` or ``red``) with its ``red`` and ``flaky`` ids; the index carries
the verdict, ``reasons`` ``[]`` and the file's sha256. No verdict (``verdict`` and ``sha256`` null, no file) when the
base did not stage (the staging's reasons), when a run tells nothing (any reason of the contained run,
``red_control_green`` included: a sandbox a known bad command passed judges no test), or when the runs are not
``gate.sentinel``'s shape (``sentinel_unusable``: two top-level TAP lines with one description); the runs stop at
the first run that tells nothing. Who reads the verdict is ``yaz``'s half of D7 (``loop.watch``: the revert on red,
the ``events``/``sentinel`` end row on green or flaky, ``loop.write_cycle``), not this module.

Caller: ``loop.job``'s ``kos`` (D3, D7), which reads the ``pulled`` artifact (``loop.pulled``) and passes the one
``deps`` artifact directory under the download (``runner.deps_npm.artifact_in``), and ``watch`` from
``brain/state``'s ledger. Not done here, stated: the drill of the ``kos`` job (D8), and how ``yaz`` treats a
candidate without files (the gate reads a missing file as ``artefact_hash_mismatch``). The hashes are taken by this
process after every container ended, from the bytes it wrote, not from anything a container wrote.

Command line, from ``referee/``; it runs docker::

    python -m runner.kos run FILE    FILE {recipe, tree, policy, red_control: {cmd}, candidates: {cid: dir},
                                     out, deps?, target?, base?, watch?}; stdout the index, one JSON line; exit 0 base
                                     verified, 1 base refused, 2 no verdict or unusable input
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import sys
import tempfile
from typing import Any

from gate import diffguard
from gate import sentinel as S
from profile import derive as D
from profile import unit_verify as U
from runner import contained as C
from runner import lint_record as R
import cli

LINT_RUNS = 3
CANDIDATE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
TAP_LINE = re.compile(r"(not ok|ok) ([0-9]+)(?: - (.*))?\Z")
SKIPPED = ("skip", "todo")
INDEX = "index.json"
SENTINEL = "sentinel.json"
BASE = "base.jsonl"
MERGE_SHA = re.compile(r"[0-9a-f]{40}\Z")


class KosError(ValueError):
    """Unusable input (exit 2)."""


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _verdict(reasons: list[str]) -> dict:
    """``unit_verify``'s classes; ``base_unavailable`` tells nothing about the candidate, so it is no verdict."""
    if not reasons:
        return {"verdict": "verified", "reasons": []}
    if any(not r.startswith(U.NO_VERDICT_PREFIXES + ("base_unavailable",)) for r in reasons):
        return {"verdict": "refused", "reasons": reasons}
    return {"verdict": "no_verdict", "reasons": reasons}


def _dump(obj: Any) -> bytes:
    return (json.dumps(obj, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


# ---------------------------------------------------------------- tests

def _split_directive(text: str) -> tuple[str, str | None]:
    """``(description, directive)``: the directive follows the first `` #`` not escaped by a backslash."""
    i = 0
    while i < len(text):
        if text[i] == "\\":
            i += 2
            continue
        if text[i] == "#" and i > 0 and text[i - 1] == " ":
            return text[:i - 1], text[i + 1:].strip()
        i += 1
    return text, None


def _unescape(text: str) -> str:
    return re.sub(r"\\([\\#])", r"\1", text)


def tap_tests(stdout: bytes, exit_code: int | None) -> list[dict]:
    """The ``tests`` list of ``checks.json`` from one test run; see the module docstring."""
    tests = []
    for raw in stdout.decode("utf-8", "replace").split("\n"):
        m = TAP_LINE.fullmatch(raw.rstrip("\r"))
        if not m:
            continue
        desc, directive = _split_directive(m.group(3) or "")
        if directive is not None and directive.lower().startswith(SKIPPED):
            continue
        tests.append({"id": _unescape(desc) or m.group(2), "status": "pass" if m.group(1) == "ok" else "fail"})
    if exit_code != 0 and not any(t["status"] == "fail" for t in tests):
        tests.append({"id": "test_cmd exit %s" % exit_code, "status": "fail"})
    return tests


def checks(stdout: bytes, exit_code: int | None, red_control_green: bool) -> bytes:
    """``checks.json``'s bytes (``gate.check``'s shape)."""
    return _dump({"red_control": "pass" if red_control_green else "fail", "tests": tap_tests(stdout, exit_code)})


# ---------------------------------------------------------------- runs

def _lint(recipe: dict, red: list, worktree: str, operating: dict, runner: C.Runner, root: str) -> tuple[list, list]:
    """Three lint runs: ``(reasons, records)``; ``records`` only when no reason but ``red_control_green``."""
    reasons, stdouts = [], []
    for n in range(1, LINT_RUNS + 1):
        run = U._one(recipe["lint_cmd"], red, recipe["env_image"], worktree, operating, runner, root)
        reasons += [r for r in run["reasons"] if r not in reasons]
        if run["status"] != "ok":
            continue
        if run["exit"] not in U.LINT_OK_EXITS:
            reasons.append("lint_failed:%d" % n)
        stdouts.append(run["stdout"] if isinstance(run["stdout"], bytes) else b"")
    if [r for r in reasons if r != "red_control_green"] or len(stdouts) != LINT_RUNS:
        return reasons, []
    records = []
    for out in stdouts:
        try:
            records.append(R.record(out, worktree))
        except R.RecordError as exc:
            reasons += ["lint_output:" + r for r in exc.reasons if "lint_output:" + r not in reasons]
    return reasons, ([] if len(records) != LINT_RUNS else records)


class _NoRun(Exception):
    """A sentinel run that tells nothing; ``reasons`` are its contained run's."""

    def __init__(self, reasons: list[str]) -> None:
        super().__init__(", ".join(reasons))
        self.reasons = reasons


def _sentinel(watch: str, recipe: dict, red: list, staging: str, ctx: dict, runner: C.Runner, root: str,
              out: str) -> dict:
    """The sentinel's runs of the staged base worktree and ``sentinel.json``; its index entry (see the module
    docstring)."""
    def one() -> dict:
        test = U._one(recipe["affected_test_cmd"], red, recipe["env_image"], staging, ctx["operating"], runner, root,
                      ctx["values"]["test_total_s"])
        if test["reasons"]:  # a run whose status is not ok has its status among them (contained)
            raise _NoRun(test["reasons"])
        stdout = test["stdout"] if isinstance(test["stdout"], bytes) else b""
        return {"results": tap_tests(stdout, test["exit"])}

    entry = {"merge_sha": watch, "verdict": None, "reasons": [], "sha256": None}
    try:
        got = S.watch(one(), one)
    except _NoRun as exc:
        return dict(entry, reasons=exc.reasons)
    except S.Unusable:
        return dict(entry, reasons=["sentinel_unusable"])
    data = _dump({"merge_sha": watch, "runs": got["runs"], "verdict": got["verdict"], "red": got["red"],
                  "flaky": got["flaky"]})
    with open(os.path.join(out, SENTINEL), "xb") as fh:
        fh.write(data)
    return dict(entry, verdict=got["verdict"], sha256=sha256(data))


def _patch(worktree: str, diff: bytes) -> list[str]:
    """Apply every block of ``diff`` in ``worktree``; the reasons it could not (nothing is half applied then:
    the caller drops the worktree)."""
    try:
        blocks = diffguard.parse(diff.decode("utf-8", "surrogateescape"))
    except diffguard.DiffError:
        return ["patch_unusable"]
    reasons, done = [], {}
    for block in blocks:
        if block["kind"] != "modify" or block["old"] != block["new"] or block["binary"]:
            reasons.append("patch_not_in_place")
            continue
        path = block["old"]
        if D.norm_path(path) != path or path == ".":
            reasons.append("patch_path_invalid")
            continue
        if path.split("/")[0] == U.RESERVED:
            reasons.append("reserved_path")
            continue
        old = D._read_regular(worktree, path)
        if old is None:
            reasons.append("base_file_missing")
            continue
        try:
            done[path] = diffguard.apply(block, old)
        except diffguard.DiffError:
            reasons.append("patch_does_not_apply")
    if reasons:
        return sorted(set(reasons))
    for path, content in done.items():
        full = os.path.join(worktree, path)
        mode = stat.S_IMODE(os.lstat(full).st_mode)
        fd = os.open(full, os.O_WRONLY | os.O_TRUNC | os.O_NOFOLLOW)
        with os.fdopen(fd, "wb") as fh:
            fh.write(content)
        os.chmod(full, mode)
    return []


def _candidate(cid: str, diff: bytes, recipe: dict, red: list, staging: str, ctx: dict, runner: C.Runner,
               root: str, out: str, base_run: bytes) -> dict:
    work_root = tempfile.mkdtemp(prefix="cand-", dir=root)
    worktree = os.path.join(work_root, "work")
    shutil.copytree(staging, worktree, symlinks=True)
    try:
        bad = _patch(worktree, diff)
        if bad:
            return _verdict(bad)
        reasons, records = _lint(recipe, red, worktree, ctx["operating"], runner, work_root)
        if not records:
            return _verdict(reasons)
        test = U._one(recipe["test_cmd"], red, recipe["env_image"], worktree, ctx["operating"], runner, work_root,
                      ctx["values"]["test_total_s"])
        reasons += [r for r in test["reasons"] if r not in reasons]
        if test["status"] != "ok" or [r for r in reasons if r != "red_control_green"]:
            return _verdict(reasons)
        stdout = test["stdout"] if isinstance(test["stdout"], bytes) else b""
        files = {"cand.jsonl": R.run_file(records),
                 "checks.json": checks(stdout, test["exit"], "red_control_green" in reasons)}
        files["hashes.json"] = _dump({"base.jsonl": sha256(base_run), "cand.jsonl": sha256(files["cand.jsonl"]),
                                      "checks.json": sha256(files["checks.json"])})
        directory = os.path.join(out, "c", cid)
        os.makedirs(directory)
        for name, data in files.items():
            with open(os.path.join(directory, name), "xb") as fh:
                fh.write(data)
        return _verdict(reasons)
    finally:
        shutil.rmtree(work_root, ignore_errors=True)


def results(recipe: Any, tree: str, policy: Any, red_control: Any, candidates: dict[str, bytes], out: str,
            deps: str | None = None, target: Any = None, runner: C.Runner | None = None,
            base: str | None = None, watch: str | None = None) -> dict:
    """Write OUT (see the module docstring) and return the index. ``candidates``: ``{cid: diff.patch bytes}``;
    ``watch``: the merge SHA whose sentinel runs, or ``None``."""
    runner = runner or C.docker_runner
    if watch is not None and not (isinstance(watch, str) and MERGE_SHA.match(watch)):
        raise KosError("watch must be a merge SHA, 40 lowercase hex")
    if not isinstance(candidates, dict) or not all(isinstance(k, str) and isinstance(v, bytes)
                                                   for k, v in candidates.items()):
        raise KosError("candidates must map ids to diff bytes")
    if os.path.lexists(out):
        raise KosError("OUT exists: the results directory is written fresh")
    os.makedirs(out)
    root = tempfile.mkdtemp(prefix="snowball-kos-", dir=base)
    try:
        bad, _, ctx = U.stage(recipe, tree, policy, red_control, deps, target, runner, root)
        reasons, records = (bad, []) if bad else _lint(recipe, red_control["cmd"], ctx["staging"], ctx["operating"],
                                                       runner, root)
        index: dict[str, Any] = {"base_run_sha256": None, "candidates": {}, "sentinel": None}
        if records and not reasons:
            base_run = R.run_file(records)
            with open(os.path.join(out, BASE), "xb") as fh:
                fh.write(base_run)
            index["base_run_sha256"] = sha256(base_run)
        index["base"] = _verdict(reasons)
        if watch is not None:
            index["sentinel"] = ({"merge_sha": watch, "verdict": None, "reasons": bad, "sha256": None} if bad else
                                 _sentinel(watch, recipe, red_control["cmd"], ctx["staging"], ctx, runner, root, out))
        for cid in sorted(candidates):
            if not CANDIDATE_ID.fullmatch(cid):
                got = _verdict(["candidate_id_invalid"])
            elif index["base_run_sha256"] is None:
                got = _verdict(["base_unavailable"])
            else:
                got = _candidate(cid, candidates[cid], recipe, red_control["cmd"], ctx["staging"], ctx, runner,
                                 root, out, base_run)
            index["candidates"][cid] = got
        with open(os.path.join(out, INDEX), "xb") as fh:
            fh.write(_dump(index))
        return index
    finally:
        shutil.rmtree(root, ignore_errors=True)


# ---------------------------------------------------------------- command line

USAGE = "usage: python -m runner.kos run FILE"
# What ``results`` raises on unusable input; read by this command line and by ``loop.job``'s ``kos``.
UNUSABLE = (KosError, U.VerifyError, D.DeriveError, C.ContainmentError, ValueError, KeyError, TypeError, OSError,
            RecursionError)
EXIT = {"verified": 0, "refused": 1, "no_verdict": 2}


def _read(path: str) -> bytes:
    with open(path, "rb") as fh:
        return fh.read()


def main(argv: list[str]) -> int:
    try:
        if len(argv) != 2 or argv[0] != "run":
            raise KosError(USAGE)
        req = cli.loads(_read(argv[1]).decode("utf-8"))
        if not (isinstance(req, dict) and isinstance(req.get("tree"), str) and isinstance(req.get("out"), str)
                and isinstance(req.get("candidates"), dict)
                and all(isinstance(v, str) for v in req["candidates"].values())):
            raise KosError("FILE must be {recipe, tree, policy, red_control, candidates: {cid: dir}, out, ...}")
        cands = {cid: _read(os.path.join(d, "diff.patch")) for cid, d in req["candidates"].items()}
        index = results(req.get("recipe"), req["tree"], req.get("policy"), req.get("red_control"), cands,
                        req["out"], req.get("deps"), req.get("target"), base=req.get("base"),
                        watch=req.get("watch"))
        sys.stdout.write(json.dumps(index, sort_keys=True) + "\n")
        return EXIT[index["base"]["verdict"]]
    except UNUSABLE as exc:
        cause = "unusable input: %s" % cli.cause(exc)
    sys.stdout.write(json.dumps({"ok": False, "error": cause}) + "\n")
    return 2


FAULT_LINE = {"ok": False, "error": "internal error"}


if __name__ == "__main__":
    sys.exit(cli.run(main, sys.argv[1:], FAULT_LINE))
