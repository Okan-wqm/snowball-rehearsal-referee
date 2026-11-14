"""Run kept mutants: each in its own copy of the brain, each against the tests named for it.

A mutant is data (``tests/mutants/<topic>.json``): ``{"root"?, "mutants": [{"id", "file", "old", "new",
"tests"}]}``. ``root`` is the brain directory the file's mutants live in, one of ``ROOTS``: ``referee`` (the
default, when the field is absent) or ``.`` (the brain's root, whose ``tests/`` holds the session tools
``run_like_referee``, ``vec_compare`` and ``generality`` and test 14's ``test_founder_ledger``, which tests
``referee/ledger/founder.py``: a file is named from the root, so a root mutant may change a file under
``referee/``); any other value is malformed. ``file`` is relative to ``<root>/``,
``tests`` a list whose entries are each either a ``<root>/tests`` file pattern (an entry ending in ``.py``) or a
unittest id (``<module>.<Class>`` or ``<module>.<Class>.<method>``, dotted identifiers, ``<module>`` the file
``<root>/tests/<module>.py``); any other entry is malformed. For each mutant:

- ``old`` must occur in ``file`` exactly once in the brain as it is: ``stale`` (zero; a refactor removed the code
  the mutant was written for) or ``ambiguous`` (more), and nothing is run;
- the brain is copied (``.git`` included: some tests read the brain's commits), ``old`` is replaced by ``new`` in
  the copy, and each entry runs in order in the copy's ``<root>/`` (as ``snowball-tests.json`` runs them): a
  pattern as ``python -m unittest discover -s tests -p <pattern>``, an id as unittest's ``main`` over that one name
  with ``<root>/tests`` first on ``sys.path`` (what discover puts there), so an id runs in the same directory and
  imports the same modules as its file's discover run, only fewer tests. ``killed`` when one exits non-zero (a
  run of no test is non-zero: Python 3.12's exit 5), ``survived`` when all exit 0, ``timeout`` when one runs
  longer than its limit (reported, neither killed nor survived; the entries after it are not run);
- each distinct ``root`` and ``tests`` list is run once on an unchanged copy, each entry under ``--timeout``,
  when the first of its mutants is reached (not all lists before the first mutant: a large selection would be
  silent for as long as every list takes): if it is not green there (an entry over ``--timeout`` included), its
  mutants are ``baseline_red`` and not run (a red test kills every mutant and proves nothing).

Limits. A mutant's entry may run ``min(--timeout, max(--floor, --factor * s))`` seconds, ``s`` the seconds that
same entry took in its list's baseline (wall clock, measured in this run, under the same ``--jobs``): a mutant
that loops ends near ``--factor`` times the baseline instead of at the ceiling, and ``--floor`` keeps a quick
entry from timing out on load. The limit says nothing about why a mutant was slow: a ``timeout`` may be a mutant
that loops or one that is only slower than the limit (a person reads which).

The first line printed is the plan, ``{"plan": {changed, selected, reused, to_run, tiers, lists}}``, before
anything is copied or run: ``changed`` the number of changed paths (``null`` without ``--touched``), ``selected``
the mutants of this run, ``reused`` those whose row comes from ``--record`` (below), ``to_run`` the rest,
``tiers`` the ``to_run`` count of each tier (below), ``lists`` the distinct ``root`` and ``tests`` lists among
``to_run``. ``--plan`` adds ``by_file`` (each mutant file's ``[selected, to_run]``), prints that one line and
stops, exit 0: nothing is copied, run or written.

Each row ``{file, id, outcome, fp}`` is printed and flushed as its mutant finishes, so the rows come in the order
the mutants finish, and a run that is cut keeps the rows it printed. After the last row, one summary line
``{ok, files, mutants, outcomes, reused}`` (``summary``): ``files`` the mutant files read, ``mutants`` the rows
printed, ``outcomes`` each outcome's count, ``reused`` the rows not run in this run; it is printed only when every
mutant has its row, so a run cut before its end (a session's tool limit, a kill) lacks it, and output without it
is not a whole run. Exit 0 only when every mutant is ``killed`` (no mutant run is exit 1: nothing was shown),
``ok`` the same. The brain itself is only read (``--record``'s file is the one thing written, where it is named).

**Fingerprint** (``fp``, ``fingerprint``): the sha256 of the mutant's ``root``, ``file``, ``old``, ``new`` and
``tests`` and of the path and bytes of every file in the mutant's reach, ``reach`` being the one rule
``--touched`` selects by (below): its ``file``, the ``<root>/tests`` files its ``tests`` entries name, and the
import closure of those, over the working tree as it is. Two runs give a mutant the same ``fp`` exactly when
those fields and those files' bytes are the same. Not in it, the same width as ``--touched``'s: a file that is
not Python or that a test reaches without an import statement, the machine (its python, its programs), and this
tool's own code unless the mutant reaches it (a row says what the tool that printed it judged). A ``stale`` or
``ambiguous`` mutant has none (its row's ``fp`` is ``""``): it cannot be applied, and no record row stands for
it. The tree must stand still while a run reads it: a mutant's ``fp`` is taken at the run's start and again when
the mutant has run, and when the two differ (a file it reaches was changed or removed meanwhile, so its copy was
not of the tree its row would name) that mutant has no row, no later mutant starts (those running end, each
under the same check) and the run ends with an error. What this does not see: a file changed and changed back in
between, and a change to a file outside the reach.

**Order.** The mutants to run start in tier order, inside a tier in file and mutant order: tier 0, a changed path
is the mutant's own file under ``tests/mutants/`` or its ``file``; tier 1, a changed path is a test file one of
its ``tests`` entries names; tier 2, every other (reached through an import only; without ``--touched`` every
mutant is tier 2). So a run that is cut has spent its time on the mutants nearest the change.

**Kept outcomes** (``--record FILE``; with ``--plan`` the file is read, not written). A record row is a row this
tool printed: a line that is one JSON object with string ``file``, ``id``, ``outcome`` and ``fp``; any other line
(a plan, a summary, a line cut in the middle) is not a row and is passed over. A selected mutant is not run and
its row is printed with ``"reused": true`` when the record's rows for its ``file`` and ``id`` with today's ``fp``
all have one outcome and that outcome is ``killed`` or ``survived`` (a ``timeout`` or ``baseline_red`` row is
never reused; rows that disagree are not reused, the mutant runs again). Each row of a mutant run in this run
whose outcome is ``killed`` or ``survived`` is appended to FILE and flushed as it finishes, so a cut run's
outcomes are there for the next. When a run is whole (the summary is printed) FILE is written again: for each
mutant file read, in file and mutant order, the one row of each mutant that has a reusable row at today's ``fp``;
the rows of mutant files this run did not read stay as they were, after them. What a record row is evidence of:
that this tool printed it; nothing proves a row a person wrote into the file was a run.

``--touched REV`` runs only the mutants a change since ``REV`` can concern. The changed paths are git's: every path
``git diff --name-only --no-renames REV`` names (``REV`` against the working tree, staged or not, committed or not;
a rename names both its paths) and every untracked path ``git ls-files --others --exclude-standard`` names. A
mutant is selected when a changed path is

- the mutant's own file under ``tests/mutants/`` (a new or edited mutant), or
- a ``.py`` file in the mutant's reach (``reach``): the import closure of its ``file`` or of a ``.py`` file under
  ``<root>/tests`` whose name one of its ``tests`` entries names (a pattern by ``fnmatch``, discover runs these or
  fewer; an id by its ``<module>``), its ``file`` included. The closure
  is ``status.depmap``'s reading of import statements (one reader of imports) and every package holding a module
  reached (Python runs it first), over the working tree's modules as the test run sees them, a name taken from the
  first of the root's import spaces (``ROOTS``) that has it: for ``referee``, ``referee/tests``'s files by their
  names inside ``tests``, then ``referee/``'s outside it; for ``.``, the root ``tests/`` first (discover's start
  directory), then those two, which the root tests put on ``sys.path`` themselves. A changed ``.py`` path the
  working tree no longer has (removed, renamed away) is a module still, reached by a file that imports its name.

Not seen by ``--touched``, stated: a change to a file that is not Python (a fixture, a JSON, a workflow) or that
a test reaches without an import statement (opened by path, run as a subprocess, imported by a built name); the
imports of a file that does not parse (it is selected by its own path, it reaches nothing further). Before a push
that changes such a file, run the full set.

``--discover --out KEPT`` (one candidates file, not with ``--touched``) finds which tests kill each candidate,
so a mutant job writes only candidates. A candidates file is a mutant file (same fields and rules); each
candidate's ``tests`` is the search space. Each entry runs (as above, in the same directory and with the same
imports) under a collector that records every test that fails or errs (a subtest's failure is its test's; an
unexpected success is a failure) and each test's seconds. An entry kills as a whole when its run fails other than
by a test of its own (a module that does not import, a class or module fixture, no test run, a non-zero exit with
no record, a test id that is not a ``tests`` entry), and is then its own killer. Every entry runs, so the killers
are all the search space has; an entry over its limit is listed in ``timeouts`` and gives no killer. A candidate
is ``killed`` when it has a killer, else ``timeout`` when an entry timed out, else ``survived``; ``stale``,
``ambiguous`` and ``baseline_red`` as above, the baseline being the same collector on an unchanged copy (green:
no test failed, no other failure, a test ran). Each row is ``{file, id, outcome, killers, timeouts, tests}``;
``tests`` the ``--keep`` (default 1) killers that took the fewest seconds in the baseline (an entry killer its
entry's seconds), ties by name. A candidate's limits come from its entries' seconds in the baseline, also for an
entry that is named as a test is (a test's seconds are the test's alone, an entry's its whole run's). KEPT, refused when it exists, is written once every row is in: the candidates
file's ``root`` and its killed candidates with ``tests`` replaced by their chosen killers, in candidate order; it is
not written when none is killed. Then the summary line and exit as above. A survivor is not in KEPT: a person says
whether it is equivalent or writes the test that kills it. The killers are one run's evidence; run KEPT in the
normal mode to keep it.

Out of scope, stated: tests outside the ``tests/`` of a root in ``ROOTS``, mutants that are not one
textual replacement, and equivalent mutants (a ``survived`` mutant may be one: the runner says it survived,
a person says why).
"""

from __future__ import annotations

import argparse
import concurrent.futures
import glob
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from fnmatch import fnmatch
from typing import Any, Callable

BRAIN = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(BRAIN, "referee"))

from status import depmap  # noqa: E402
FIELDS = ("id", "file", "old", "new", "tests")
# A mutant file's root (module docstring) -> its import spaces, brain-relative, in the order a name is found.
ROOTS = {"referee": ("referee/tests/", "referee/"), ".": ("tests/", "referee/tests/", "referee/")}
TEST_ID = re.compile(r"[A-Za-z_]\w*(\.[A-Za-z_]\w*){1,2}", re.ASCII)
# One name run as discover would: referee/tests first on sys.path, the cwd (referee/) after it.
RUN_ID = ("import os, sys, unittest; sys.path.insert(0, os.path.abspath('tests')); "
          "unittest.main(module=None, argv=['unittest', sys.argv[1]])")


def test_file(entry: str) -> str:
    """The ``referee/tests`` file pattern of a ``tests`` entry: a pattern itself, an id its ``<module>.py``."""
    return entry if entry.endswith(".py") else entry.split(".", 1)[0] + ".py"


def _entry(entry: Any) -> bool:
    return isinstance(entry, str) and (entry.endswith(".py") or bool(TEST_ID.fullmatch(entry)))


def load(path: str) -> list[dict[str, Any]]:
    """The mutants of one file, each with its file's ``root`` (``referee`` when absent) under ``"root"``; a
    malformed file or mutant raises ``ValueError``."""
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    mutants = data.get("mutants") if isinstance(data, dict) else None
    if not isinstance(mutants, list) or not mutants:
        raise ValueError("%s: no mutants list" % path)
    root = data.get("root", "referee")
    if not (isinstance(root, str) and root in ROOTS) or set(data) - {"root", "mutants"}:
        raise ValueError("%s: root %r is not one of %s, or a field is unknown" % (path, root, sorted(ROOTS)))
    for m in mutants:
        if not (isinstance(m, dict) and sorted(m) == sorted(FIELDS)
                and all(isinstance(m[k], str) and m[k] for k in ("id", "file", "old"))
                and isinstance(m["new"], str) and m["new"] != m["old"]
                and isinstance(m["tests"], list) and m["tests"] and all(_entry(t) for t in m["tests"])):
            raise ValueError("%s: malformed mutant %r" % (path, m.get("id") if isinstance(m, dict) else m))
    ids = [m["id"] for m in mutants]
    if len(set(ids)) != len(ids):
        raise ValueError("%s: duplicate mutant id" % path)
    return [dict(m, root=root) for m in mutants]


def applicable(brain: str, mutant: dict[str, Any]) -> str | None:
    """``None`` when ``old`` occurs once in the brain's ``file``, else ``stale`` or ``ambiguous``."""
    path = os.path.join(brain, mutant["root"], mutant["file"])
    try:
        with open(path, encoding="utf-8") as fh:
            count = fh.read().count(mutant["old"])
    except FileNotFoundError:
        count = 0
    return None if count == 1 else ("stale" if count == 0 else "ambiguous")


def _copy(brain: str, mutant: dict[str, Any] | None = None) -> str:
    """A copy of the brain in a new temporary directory, with ``mutant`` applied when given."""
    work = tempfile.mkdtemp(prefix="mutate-")
    copy = os.path.join(work, "brain")
    shutil.copytree(brain, copy, symlinks=True, ignore=shutil.ignore_patterns("__pycache__"))
    if mutant:
        path = os.path.join(copy, mutant["root"], mutant["file"])
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text.replace(mutant["old"], mutant["new"]))
    return copy


def _emitter(emit: Callable[[Any], None] | None) -> Callable[[Any], None]:
    """``emit`` called one thread at a time; nothing when ``emit`` is ``None``."""
    lock = threading.Lock()

    def send(row: Any) -> None:
        if emit:
            with lock:
                emit(row)
    return send


def _run_tests(copy: str, root: str, tests: list[str], limits: list[float]) -> tuple[str, list[float]]:
    """``(verdict, seconds)`` for the entries run in order in the copy's ``<root>/``, entry ``i`` under
    ``limits[i]`` seconds: ``green``, ``red`` or ``timeout``, and the wall-clock seconds of each entry run."""
    seconds: list[float] = []
    for entry, limit in zip(tests, limits, strict=True):
        argv = ([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", entry] if entry.endswith(".py")
                else [sys.executable, "-c", RUN_ID, entry])
        start = time.monotonic()
        try:
            done = subprocess.run(argv,
                                  cwd=os.path.join(copy, root), stdout=subprocess.DEVNULL,
                                  stderr=subprocess.DEVNULL, timeout=limit)
        except subprocess.TimeoutExpired:
            return "timeout", seconds + [time.monotonic() - start]
        seconds.append(time.monotonic() - start)
        if done.returncode != 0:
            return "red", seconds
    return "green", seconds


def limits(seconds: list[float], timeout: float, factor: float, floor: float) -> list[float]:
    """A mutant's limit for each entry from the seconds the entry took in the baseline (module docstring)."""
    return [min(timeout, max(floor, factor * s)) for s in seconds]


def baseline(brain: str, root: str, tests: list[str], timeout: float) -> tuple[str, list[float]]:
    """``(verdict, seconds)`` of ``tests`` run in ``root`` on an unchanged copy, each entry under ``timeout``."""
    copy = _copy(brain)
    try:
        return _run_tests(copy, root, tests, [timeout] * len(tests))
    finally:
        shutil.rmtree(os.path.dirname(copy), ignore_errors=True)


def run_one(brain: str, mutant: dict[str, Any], limit: list[float]) -> str:
    """``killed``, ``survived``, ``timeout``, ``stale`` or ``ambiguous``."""
    reason = applicable(brain, mutant)
    if reason:
        return reason
    copy = _copy(brain, mutant)
    try:
        verdict, _ = _run_tests(copy, mutant["root"], mutant["tests"], limit)
    finally:
        shutil.rmtree(os.path.dirname(copy), ignore_errors=True)
    return {"red": "killed", "green": "survived"}.get(verdict, verdict)


def touched(brain: str, rev: str) -> set[str]:
    """The paths changed since ``rev``, relative to the brain (rules in the module docstring); a ``rev`` git
    cannot read raises ``ValueError``."""
    def git(*args: str) -> list[str]:
        done = subprocess.run(["git", "-C", brain, *args], capture_output=True, text=True)
        if done.returncode != 0:
            raise ValueError("git %s: %s" % (" ".join(args), done.stderr.strip()))
        return [line for line in done.stdout.splitlines() if line]
    git("rev-parse", "--verify", "--quiet", rev + "^{commit}")
    return set(git("diff", "--name-only", "--no-renames", rev, "--")) | set(git("ls-files", "--others",
                                                                                 "--exclude-standard"))


def closure_of(brain: str, changed: set[str], spaces: tuple[str, ...]) -> Callable[[list[str]], set[str]]:
    """``paths -> closure``: brain-relative ``.py`` paths to the brain-relative paths of every module their import
    statements reach and every package holding one (Python runs it first), themselves included; a name is the
    module of the first of ``spaces`` (a root's, ``ROOTS``) that has it. A changed ``.py`` path the working tree no
    longer has is a module with no imports, so a file still importing it reaches it."""
    removed = sorted(p for p in changed if p.endswith(".py") and not os.path.exists(os.path.join(brain, p)))
    modules: dict[str, str] = {}
    for prefix in spaces:
        found = {n: prefix + rel for n, rel in depmap.python_modules(os.path.join(brain, prefix)).items()}
        found.update({depmap.module_name(p[len(prefix):]): p for p in removed
                      if next((s for s in spaces if p.startswith(s)), None) == prefix})
        for name, path in sorted(found.items()):
            if name:
                modules.setdefault(name, path)
    names = {rel: n for n, rel in modules.items()}
    edges: dict[str, set[str]] = {}
    for name, rel in modules.items():
        try:
            with open(os.path.join(brain, rel), encoding="utf-8") as fh:
                edges[name] = depmap.module_imports(fh.read(), name, rel.endswith("__init__.py"), modules)
        except (FileNotFoundError, SyntaxError):  # removed, or its imports cannot be read: it reaches nothing
            edges[name] = set()

    def closure(paths: list[str]) -> set[str]:
        reached = depmap.with_packages(depmap.reachable(edges, [names[p] for p in paths if p in names]), modules)
        return set(paths) | {modules[n] for n in reached}
    return closure


def reach(brain: str, roots: set[str], changed: set[str]) -> Callable[[dict[str, Any]], tuple[list[str], set[str]]]:
    """``mutant -> (starts, reached)`` for mutants of ``roots`` (module docstring, ``--touched``): ``starts`` the
    mutant's ``file`` and the test files its ``tests`` entries name, ``reached`` the import closure of ``starts``;
    brain-relative paths. ``changed`` only names the removed modules ``closure_of`` still reaches."""
    closures = {root: closure_of(brain, changed, ROOTS[root]) for root in roots}
    # A root's first import space is its own tests/ (discover's start directory).
    tests = {root: sorted(ROOTS[root][0] + rel for rel in depmap.python_modules(os.path.join(brain, ROOTS[root][0]))
                          .values()) for root in roots}

    def of(m: dict[str, Any]) -> tuple[list[str], set[str]]:
        starts = [os.path.normpath(os.path.join(m["root"], m["file"]))] + [
            t for t in tests[m["root"]] if any(fnmatch(os.path.basename(t), test_file(e)) for e in m["tests"])]
        return starts, closures[m["root"]](starts)
    return of


def tier(path: str, starts: list[str], reached: set[str], changed: set[str]) -> int | None:
    """How near a change to ``changed`` is to the mutant of the mutant file ``path`` (brain-relative), ``starts``
    and ``reached`` its ``reach``: 0 its own mutant file or its ``file``, 1 a test file it names, 2 a file it only
    reaches; ``None`` when no changed path concerns it."""
    if path in changed or starts[0] in changed:
        return 0
    if set(starts[1:]) & changed:
        return 1
    return 2 if reached & changed else None


def select(brain: str, items: list[tuple[str, dict[str, Any]]], changed: set[str]) -> list[tuple[str, dict]]:
    """The ``(mutant file, mutant)`` items a change to ``changed`` (brain-relative paths) can concern."""
    of = reach(brain, {m["root"] for _, m in items}, changed)
    return [(path, m) for path, m in items if tier(os.path.relpath(path, brain), *of(m), changed) is not None]


def fingerprint(brain: str, mutant: dict[str, Any], reached: set[str]) -> str:
    """The mutant's ``fp`` (module docstring): ``reached`` its reach over the tree as it is."""
    files = []
    for rel in sorted(reached):
        with open(os.path.join(brain, rel), "rb") as fh:
            files.append([rel, hashlib.sha256(fh.read()).hexdigest()])
    data = {"mutant": {k: mutant[k] for k in ("root", *FIELDS) if k != "id"}, "files": files}
    return hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


REUSED = ("killed", "survived")  # the outcomes a record row may stand for (module docstring)


def record_rows(path: str) -> list[dict[str, str]]:
    """The rows of the record at ``path`` in line order (module docstring: any other line is passed over); a
    record that does not exist has none."""
    rows = []
    try:
        with open(path, encoding="utf-8") as fh:
            lines = fh.read().splitlines()
    except FileNotFoundError:
        return rows
    for line in lines:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict) and all(isinstance(row.get(k), str) for k in ("file", "id", "outcome", "fp")):
            rows.append({k: row[k] for k in ("file", "id", "outcome", "fp")})
    return rows


def reusable(rows: list[dict[str, str]]) -> dict[tuple[str, str, str], str]:
    """``(file, id, fp) -> outcome`` for the keys whose rows all have one outcome, that outcome in ``REUSED``."""
    seen: dict[tuple[str, str, str], set[str]] = {}
    for r in rows:
        seen.setdefault((r["file"], r["id"], r["fp"]), set()).add(r["outcome"])
    return {key: next(iter(outcomes)) for key, outcomes in seen.items()
            if len(outcomes) == 1 and outcomes <= set(REUSED)}


def _write_record(path: str, files: list[str], current: dict[tuple[str, str], str]) -> None:
    """A whole run's rewrite of the record (module docstring): ``files`` the brain-relative mutant files read,
    ``current`` each of their mutants' ``(file, id) -> fp`` in file and mutant order."""
    rows = record_rows(path)
    keep = reusable(rows)
    out = [{"file": f, "id": i, "outcome": keep[(f, i, fp)], "fp": fp} for (f, i), fp in current.items()
           if (f, i, fp) in keep]
    out += [r for r in rows if r["file"] not in files]
    with open(path + ".tmp", "w", encoding="utf-8") as fh:
        for r in out:
            fh.write(json.dumps(r, sort_keys=True) + "\n")
    os.replace(path + ".tmp", path)


def run(brain: str, files: list[str], jobs: int, timeout: float, changed: set[str] | None = None,
        emit: Callable[[dict[str, Any]], None] | None = None, factor: float = 5.0,
        floor: float = 60.0, record: str | None = None, plan_only: bool = False) -> list[dict[str, Any]]:
    """One row per mutant, in file and mutant order: ``{file, id, outcome, fp}`` (and ``reused`` when it was not
    run); with ``changed``, only the mutants ``select`` keeps; ``emit`` is called with the plan first, then with
    each row as its mutant finishes (one thread at a time); ``timeout``, ``factor`` and ``floor`` are the limits';
    ``record`` and ``plan_only`` are ``--record`` and ``--plan`` (module docstring; ``plan_only`` returns no
    row)."""
    loaded = [(path, m) for path in files for m in load(path)]
    roots = {m["root"] for _, m in loaded}
    as_is = reach(brain, roots, set())
    rel = {path: os.path.relpath(path, brain) for path in files}

    def now(m: dict[str, Any]) -> str | None:
        """The mutant's ``fp`` over the tree at this moment, the files those the run's start reached; ``None``
        when it cannot be applied or one of them is gone."""
        try:
            return None if applicable(brain, m) else fingerprint(brain, m, as_is(m)[1])
        except OSError:
            return None

    fps = {(rel[path], m["id"]): now(m) for path, m in loaded}
    if changed is None:
        mutants = [(path, m, 2) for path, m in loaded]
    else:
        of = reach(brain, roots, changed)
        mutants = [(path, m, t) for path, m in loaded
                   for t in [tier(rel[path], *of(m), changed)] if t is not None]
    kept = reusable(record_rows(record)) if record else {}
    rows: dict[int, dict[str, Any]] = {}
    todo: list[tuple[int, str, dict[str, Any], int]] = []
    for n, (path, m, t) in enumerate(mutants):
        fp = fps[(rel[path], m["id"])]
        if fp is not None and (rel[path], m["id"], fp) in kept:
            rows[n] = {"file": rel[path], "id": m["id"], "outcome": kept[(rel[path], m["id"], fp)], "fp": fp,
                       "reused": True}
        else:
            todo.append((n, path, m, t))
    todo.sort(key=lambda item: item[3])  # stable: file and mutant order inside a tier
    suites = {(m["root"], tuple(m["tests"])) for _, _, m, _ in todo if not applicable(brain, m)}
    plan: dict[str, Any] = {"changed": None if changed is None else len(changed), "selected": len(mutants),
                            "reused": len(rows), "to_run": len(todo),
                            "tiers": [sum(1 for item in todo if item[3] == t) for t in (0, 1, 2)],
                            "lists": len(suites)}
    send = _emitter(emit)
    if plan_only:
        by_file: dict[str, list[int]] = {}
        for path, _, _ in mutants:
            by_file.setdefault(rel[path], [0, 0])[0] += 1
        for _, path, _, _ in todo:
            by_file[rel[path]][1] += 1
        send({"plan": plan | {"by_file": by_file}})
        return []
    send({"plan": plan})
    for n in sorted(rows):
        send(rows[n])
    base: dict[tuple[str, tuple[str, ...]], tuple[str, list[float]]] = {}
    locks = {suite: threading.Lock() for suite in suites}
    keep_lock, moved = threading.Lock(), threading.Event()

    def base_of(suite: tuple[str, tuple[str, ...]]) -> tuple[str, list[float]]:
        with locks[suite]:  # the list's first mutant runs its baseline, the others wait for it
            if suite not in base:
                base[suite] = baseline(brain, suite[0], list(suite[1]), timeout)
            return base[suite]

    def one(item: tuple[int, str, dict[str, Any], int]) -> None:
        n, path, m, _ = item
        if moved.is_set():  # the tree moved under an earlier mutant: no later one starts
            return
        outcome = applicable(brain, m)
        if not outcome:
            verdict, seconds = base_of((m["root"], tuple(m["tests"])))
            outcome = ("baseline_red" if verdict != "green"
                       else run_one(brain, m, limits(seconds, timeout, factor, floor)))
            if now(m) != fps[(rel[path], m["id"])]:  # the copy was not, or may not have been, of the tree named
                moved.set()
                raise RuntimeError("%s %s: its fp changed while it ran: the tree must stand still during a run"
                                   % (rel[path], m["id"]))
        row = {"file": rel[path], "id": m["id"], "outcome": outcome, "fp": fps[(rel[path], m["id"])] or ""}
        if record and outcome in REUSED:
            with keep_lock, open(record, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(row, sort_keys=True) + "\n")
        rows[n] = row
        send(row)

    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, jobs)) as pool:
        list(pool.map(one, todo))
    if record:
        _write_record(record, list(rel.values()), {key: fp for key, fp in fps.items() if fp is not None})
    return [rows[n] for n in sorted(rows)]


# Discovery's run of one entry (module docstring): argv entry, record path. The record: the ids of the tests that
# failed or erred, whether a failure was not a test's own, the tests run, each test's seconds.
COLLECT = r"""
import io, json, os, sys, time, unittest
entry, record = sys.argv[1], sys.argv[2]
loader = unittest.TestLoader()
if entry.endswith(".py"):
    suite = loader.discover("tests", pattern=entry)
else:
    sys.path.insert(0, os.path.join(os.getcwd(), "tests"))
    suite = loader.loadTestsFromName(entry)


class Result(unittest.TextTestResult):
    seconds = {}

    def startTest(self, test):
        self.started = time.monotonic()
        super().startTest(test)

    def stopTest(self, test):
        super().stopTest(test)
        self.seconds[test.id()] = time.monotonic() - self.started


result = unittest.TextTestRunner(stream=io.StringIO(), resultclass=Result).run(suite)
failed, other = set(), False
for test in [t for t, _ in result.failures + result.errors] + list(result.unexpectedSuccesses):
    test = test.test_case if isinstance(test, unittest.case._SubTest) else test
    if isinstance(test, unittest.TestCase):
        failed.add(test.id())
    else:
        other = True
with open(record, "w") as fh:
    json.dump({"failed": sorted(failed), "other": other, "ran": result.testsRun, "seconds": result.seconds}, fh)
"""


def _collect(copy: str, root: str, entry: str, limit: float) -> tuple[dict[str, Any] | None, float]:
    """``(record, seconds)`` of one entry run under ``COLLECT`` in the copy's ``<root>/``: the record ``None`` when
    the entry timed out, ``{killers, seconds}`` otherwise; ``killers`` the entry itself when it failed other than
    by a test of its own (module docstring), else the ids of its failed tests. A module that does not import fails
    as a test ``unittest.loader._FailedTest.<name>``, an id of four names, so its entry is its killer; an id
    that ``TEST_ID`` matches never ends in ``.py`` (a test method's name starts with ``test``)."""
    fd, path = tempfile.mkstemp(prefix="mutate-record-", suffix=".json")
    os.close(fd)
    start = time.monotonic()
    try:
        try:
            done = subprocess.run([sys.executable, "-c", COLLECT, entry, path], cwd=os.path.join(copy, root),
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=limit)
        except subprocess.TimeoutExpired:
            return None, time.monotonic() - start
        took = time.monotonic() - start
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
    finally:
        os.unlink(path)
    rec = json.loads(text) if text else None
    if (done.returncode != 0 or rec is None or rec["other"] or not rec["ran"]
            or not all(TEST_ID.fullmatch(t) for t in rec["failed"])):
        return {"killers": [entry], "seconds": rec["seconds"] if rec else {}}, took
    return {"killers": rec["failed"], "seconds": rec["seconds"]}, took


def _search(brain: str, root: str, tests: list[str], limit: list[float],
            mutant: dict[str, Any] | None = None) -> tuple[list[str], list[str], list[float], dict[str, float]]:
    """``(killers, timeouts, took, seconds)`` of every entry run in a copy of the brain, with ``mutant`` applied
    when given: ``took`` each entry's seconds in the entries' order, ``seconds`` each test's by its id (an entry
    can be named as a test is, so the two are kept apart)."""
    copy = _copy(brain, mutant)
    killers: list[str] = []
    timeouts: list[str] = []
    took: list[float] = []
    seconds: dict[str, float] = {}
    try:
        for entry, cap in zip(tests, limit, strict=True):
            rec, entry_seconds = _collect(copy, root, entry, cap)
            took.append(entry_seconds)
            if rec is None:
                timeouts.append(entry)
                continue
            seconds.update(rec["seconds"])
            killers += [k for k in rec["killers"] if k not in killers]
    finally:
        shutil.rmtree(os.path.dirname(copy), ignore_errors=True)
    return killers, timeouts, took, seconds


def choose(killers: list[str], seconds: dict[str, float], keep: int) -> list[str]:
    """The ``keep`` killers that took the fewest baseline seconds, ties by name (a killer with no baseline time
    last)."""
    return sorted(killers, key=lambda k: (seconds.get(k, float("inf")), k))[:keep]


def discover(brain: str, path: str, out: str, jobs: int, timeout: float, keep: int = 1,
             emit: Callable[[dict[str, Any]], None] | None = None, factor: float = 5.0,
             floor: float = 60.0) -> list[dict[str, Any]]:
    """One row per candidate of the file at ``path``, in candidate order (module docstring, ``--discover``);
    writes ``out`` when a candidate is killed; ``emit`` as ``run``'s."""
    candidates = load(path)
    suites = sorted({(m["root"], tuple(m["tests"])) for m in candidates if not applicable(brain, m)})

    def base_of(suite: tuple[str, tuple[str, ...]]) -> tuple[bool, list[float], dict[str, float]]:
        killers, timeouts, took, seconds = _search(brain, suite[0], list(suite[1]), [timeout] * len(suite[1]))
        # a killer's seconds for ``choose``: a test's own; an entry's, when no test that ran has its name, the entry's
        return not (killers or timeouts), took, dict(zip(suite[1], took, strict=True)) | seconds

    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, jobs)) as pool:
        base = dict(zip(suites, pool.map(base_of, suites)))
        send = _emitter(emit)

        def one(m: dict[str, Any]) -> dict[str, Any]:
            row: dict[str, Any] = {"file": os.path.relpath(path, brain), "id": m["id"], "outcome": applicable(brain, m),
                                   "killers": [], "timeouts": [], "tests": []}
            if not row["outcome"]:
                green, entry_seconds, seconds = base[(m["root"], tuple(m["tests"]))]
                if not green:
                    row["outcome"] = "baseline_red"
                else:
                    killers, timeouts, _, _ = _search(brain, m["root"], m["tests"],
                                                   limits(entry_seconds, timeout, factor, floor), m)
                    row.update(killers=killers, timeouts=timeouts, tests=choose(killers, seconds, keep),
                               outcome="killed" if killers else "timeout" if timeouts else "survived")
            send(row)
            return row

        rows = list(pool.map(one, candidates))
    kept = [{k: m[k] for k in FIELDS} | {"tests": r["tests"]} for m, r in zip(candidates, rows)
            if r["outcome"] == "killed"]
    if kept:
        with open(out, "x", encoding="utf-8") as fh:
            json.dump(({"root": candidates[0]["root"]} if candidates[0]["root"] != "referee" else {})
                      | {"mutants": kept}, fh, indent=1, ensure_ascii=False)
            fh.write("\n")
    return rows


def summary(files: list[str], rows: list[dict[str, Any]]) -> dict[str, Any]:
    """The run's last line (module docstring): ``ok`` when there are rows and every one is ``killed``."""
    outcomes: dict[str, int] = {}
    for r in rows:
        outcomes[r["outcome"]] = outcomes.get(r["outcome"], 0) + 1
    return {"ok": bool(rows) and set(outcomes) == {"killed"}, "files": len(files), "mutants": len(rows),
            "outcomes": outcomes, "reused": sum(1 for r in rows if r.get("reused"))}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("files", nargs="*", help="mutant files (default: every referee/tests/mutants/*.json)")
    parser.add_argument("--brain", default=BRAIN)
    parser.add_argument("-j", "--jobs", type=int, default=os.cpu_count() or 1)
    parser.add_argument("--timeout", type=float, default=900.0,
                        help="seconds per tests entry: the baseline's limit and every mutant's ceiling")
    parser.add_argument("--factor", type=float, default=5.0, help="a mutant's limit in baseline durations")
    parser.add_argument("--floor", type=float, default=60.0, help="a mutant's least limit in seconds")
    parser.add_argument("--touched", metavar="REV", help="only the mutants a change since REV can concern")
    parser.add_argument("--record", metavar="FILE", help="kept outcomes: rows read from FILE and reused at the same "
                        "fp, new rows appended to it (module docstring)")
    parser.add_argument("--plan", action="store_true", help="print the plan line with by_file and run nothing")
    parser.add_argument("--discover", action="store_true", help="find each candidate's killing tests, write --out")
    parser.add_argument("--out", help="with --discover: the kept mutant file to write (refused when it exists)")
    parser.add_argument("--keep", type=int, default=1, help="with --discover: killers kept per mutant")
    args = parser.parse_args(argv)
    if not (args.timeout > 0 and args.factor > 0 and args.floor >= 0):
        parser.error("--timeout and --factor must be positive, --floor not negative")
    brain = os.path.abspath(args.brain)
    if args.discover or args.out:
        if not (args.discover and args.out and len(args.files) == 1 and not args.touched and args.keep >= 1
                and not args.record and not args.plan):
            parser.error("--discover takes one candidates file and --out, --keep at least 1, and no --touched, "
                         "--record or --plan")
        if os.path.lexists(args.out):
            parser.error("--out %s exists" % args.out)
        found = discover(brain, os.path.abspath(args.files[0]), args.out, args.jobs, args.timeout, args.keep,
                         lambda row: print(json.dumps(row, sort_keys=True), flush=True), args.factor,
                         args.floor)
        done = summary(args.files, found)
        print(json.dumps(done, sort_keys=True), flush=True)
        return 0 if done["ok"] else 1
    files = args.files or sorted(glob.glob(os.path.join(brain, "referee", "tests", "mutants", "*.json")))
    changed = touched(brain, args.touched) if args.touched else None
    rows = run(brain, [os.path.abspath(f) for f in files], args.jobs, args.timeout, changed,
               lambda row: print(json.dumps(row, sort_keys=True), flush=True), args.factor, args.floor,
               os.path.abspath(args.record) if args.record else None, args.plan)
    if args.plan:
        return 0
    total = summary(files, rows)
    print(json.dumps(total, sort_keys=True), flush=True)
    return 0 if total["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
