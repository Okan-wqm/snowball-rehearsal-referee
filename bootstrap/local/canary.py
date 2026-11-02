"""The rival canary (register E126, E311): does the seed rival catch a defect nobody told it about? Stdlib only.

An operator-side measurement, never a verdict: it changes neither the rival nor the referee, signs nothing and pushes
nothing anywhere. Each entry of ``canary_catalog.json`` is one push, judged the way the live referee judges a code push:

- a plant is one known defect (one edit, with a hidden oracle); a control is a behaviour-preserving refactor of the
  kind the Founder pushes (no oracle);
- a whole-diff entry edits the live last accepted commit, so the diff is the edit alone; a buried entry edits a real
  push the referee accepted (its ``host``, a multi-module push), inside a file that push changed, and is judged against
  the push's own parent: the rival reviews the whole real diff with the edit somewhere in it (E311).

The referee is the live one. A fresh read-only clone of the referee repository (never a cached one) gives
``bootstrap.json``, ``policy.json``, ``seats/``, ``setup/summary.json`` and ``vectors/``, and its ``bootstrap/`` is
the code every step runs: when the canary was started on other code it runs itself again on the clone's. Every record
names the referee commit and the seat prompt's hash. Per entry:

1. the clean head: the host push (whole-diff: the last accepted commit) on a history that holds every seed epoch
   commit the live summary names. When it does not hold them, the last epoch's ``spec/tohum/`` and ``seed/`` are put
   on it in a commit whose second parent is that epoch's commit: what the referee's ``pull`` asks of a head (`25` 10b:
   the last epoch's commit on the branch, the head's seed equal to its);
2. the push: one commit on the clean head with the entry's edits, in the canary's own ``plants.git``;
3. ``pull`` (the referee's own command) reads it from ``plants.git`` with the live signed state, whose
   ``last_accepted_sha`` is the push's base (the host's parent; whole-diff: unchanged). A pull with a pre-reason is not
   reviewed, whatever else it says;
4. a plant's oracle passes on the clean head and fails, on its own, on the push; the rival never sees it;
5. the survival screen is ``run-tests`` (the referee's own command: its runner controls, every stage-0 test, every
   finished micro-feature's vector group, module-less red), one container at a time, with the referee's timeouts. It
   runs on the clean head first, which must be green or the batch stops before any review (a red clean head is this
   machine or a host the referee would not accept today, never a score), then on the push: a push it rejects never
   reaches the rival in the live loop, so it is not sent here either. Only the vector calls' total budget
   (``vectors.BUDGET_S``, sized for the referee's runner) is widened, by ``VECTOR_BUDGET_FACTOR``: this machine starts
   a container in about 8 s, and a budget it cannot meet would turn a clean head red. A screen whose every failure ran
   out of time is not counted either way. Screens are kept per referee commit and tree (``screens/``), so a dry run's
   screens serve the live run after it;
6. ``rival`` (the referee's own command: model, effort, turns, cap and seat prompt from the clone) reviews the pulled
   request alone; the canary keeps the request and the CLI's stream, which ``rival.py`` keeps nowhere;
7. every reproducer runs (``reproduce.run_reproducers``) on the push, on the clean head and, for a buried entry, on the
   push's base, and the referee's ``decide`` says which attempts prove a defect on the push. A proof whose symptom the
   clean head does not show is the edit's: a plant ``caught``, a control's ``false_refutation``. One the clean head
   shows but the base does not is the host push's own (``proven_in_host``); one the base shows too was there before
   (``proven_on_base``, on a control ``preexisting_defect``). A docker failure under any of these runs judges nothing
   (``runner_fault``), like an outage of the CLI.

Rates (recall overall, per kind and per mode; plants found, an attempt pointing at the planted lines; false
refutations over the controls) carry both one-sided Clopper-Pearson bounds at the seed's alpha (``cp_lower`` of `29a`,
1 - ``confidence_level`` 0.90 of `18a`; `19`).

    cd seed/bootstrap && python local/canary.py --work F:/snowball-work/canary --mode buried
    cd seed/bootstrap && python local/canary.py --work F:/snowball-work/canary --mode buried --live --max-usd 8

Without ``--live`` the rival is a fake that knows each plant's oracle and always uses it: a positive control of the
whole chain (containers included) that spends nothing. With ``--live`` the real rival runs through the operator's own
``claude`` login. Everything goes under ``--work`` (a private folder, never a repository): ``brain.git`` (a read-only
mirror of the brain), ``plants.git`` (the pushes), ``referee/<stamp>/`` (the clone), ``screens/`` and
``runs/<stamp>/`` with a folder per entry (``record.json``, the pulled request, ``rival/rival.json``,
``rival/transcript/``) plus ``results.json`` and ``report.md``. The canary's containers are named
``snowball_canary_<hex>``.
"""

from __future__ import annotations

import argparse
import contextlib
import copy
import datetime
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Protocol

HERE = Path(__file__).resolve().parent
BOOT = HERE.parent
CODE_ENV = "SNOWBALL_CANARY_REFEREE_CODE"  # the referee clone's bootstrap/, when the canary runs itself again on it
CODE = Path(os.environ[CODE_ENV]) if os.environ.get(CODE_ENV) else BOOT
sys.path.insert(0, str(BOOT / "tests"))
sys.path.insert(0, str(CODE))

from snowball_bootstrap import cli, config, gitio, reproduce, rival, state as st, vectors  # noqa: E402
from snowball_bootstrap.classify import LEDGER_FILE, SEED_DIRS, is_seed_path  # noqa: E402
from snowball_bootstrap.container import DockerRunner, RunResult  # noqa: E402
from snowball_bootstrap.decide import decide, utc_now  # noqa: E402  (the referee's own rule of what proves a defect)
from snowball_bootstrap.treehash import extract  # noqa: E402
from helpers import cp_lower  # noqa: E402  (the seed's one-sided Clopper-Pearson lower bound, held to `29a`)

CATALOG = HERE / "canary_catalog.json"
CATALOG_SCHEMA = "snowball-rival-canary-catalog/2"
RESULTS_SCHEMA = "snowball-rival-canary-results/2"
CONTROL = "control"
MODES = ("whole", "buried")
SPLITS = ("tune", "held")  # fixed per entry before any rival change: a change is tuned on tune entries, held ones judge it
ALPHA = float(json.loads((BOOT / "vectors" / "vectors.json").read_text(encoding="utf-8"))["cp_lower"]["alpha"])
FIRST_BATCH = (6, 3)  # plants and controls of one run unless the operator names more
MAX_USD = 12.0  # the run stops before a review once the rival's booked spend reaches this (a runaway brake)
NOT_JUDGED = ("outage", "runner_fault")  # nothing was judged: left out of every rate, their cost kept
VECTOR_BUDGET_FACTOR = 6  # the vector calls' total budget on this machine, in units of the referee's (step 5)
DEFAULT_REFEREE = "Okan-wqm/snowball-rehearsal-referee"
CONTAINER_PREFIX = "snowball_canary_"
SEATS = "seats/29-tohum-koltuklari.md"
CODE_PARTS = ("snowball_bootstrap", "stages", "requirements/claude-cli")  # what runs, and the CLI it pins
RIVAL_PARTS = ("seats", "bootstrap.json", "policy.json", "bootstrap/snowball_bootstrap/rival.py",
               "bootstrap/snowball_bootstrap/rival_mcp.py", "bootstrap/snowball_bootstrap/reproduce.py",
               "bootstrap/snowball_bootstrap/secretscan.py", "bootstrap/requirements/claude-cli")
SYMPTOM, CORRECT = "canary-symptom", "canary-correct"
PLANTER = {"GIT_AUTHOR_NAME": "canary", "GIT_AUTHOR_EMAIL": "canary@example.invalid",
           "GIT_AUTHOR_DATE": "2026-01-01T00:00:00Z", "GIT_COMMITTER_NAME": "canary",
           "GIT_COMMITTER_EMAIL": "canary@example.invalid", "GIT_COMMITTER_DATE": "2026-01-01T00:00:00Z"}
SHA40 = re.compile(r"^[0-9a-f]{40}$")


class CanaryError(RuntimeError):
    """The measurement cannot be made as asked (a stale anchor, a bad catalog, a red clean head, a stopped command)."""


class Runner(Protocol):
    def run(self, cmd: str, *, cwd: str = ".", stdin: bytes = b"", timeout_s: int) -> RunResult: ...


MakeRunner = Callable[[Path, Path, Path, list[str]], Runner]  # (tree, deps, vec, lockfiles), like ``cli._runner``


# ---- the catalog -----------------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Edit:
    """``old`` occurs exactly once in ``path`` at the clean head and becomes ``new``."""
    path: str
    old: str
    new: str


@dataclass(frozen=True)
class Host:
    """A real push the referee accepted (a survived rival artifact of the signed state, on the accepted history),
    replayed against its own parent with a buried entry's edit inside it."""
    name: str
    push: str
    why: str


@dataclass(frozen=True)
class Entry:
    """One push to judge. A plant has one edit and its oracle; a control (``kind`` "control") one edit per file it
    refactors and no oracle. ``host`` names a buried entry's host push; None edits the last accepted commit.
    ``split`` is fixed in the catalog: a change of the rival (model, effort, turns, seat prompt, reproducer sandbox)
    may be tuned on ``tune`` entries only, and only the ``held`` ones measure it."""
    id: str
    kind: str
    host: str | None
    edits: tuple[Edit, ...]
    oracle: str | None
    why: str
    split: str = "tune"
    stratum: str = ""  # the module the entry edits (``gate.check``): where in the code the rival is measured

    @property
    def control(self) -> bool:
        return self.kind == CONTROL

    @property
    def mode(self) -> str:
        return "buried" if self.host else "whole"


def oracle_reproducer(entry: Entry) -> dict[str, Any]:
    """The fake rival's reproducer for a plant: the oracle, run where the planted file exists (on the referee's empty
    tree it prints nothing, so it is not tautological), its symptom what a failing oracle prints."""
    cmd = (f"if [ -f {shlex.quote(entry.edits[0].path)} ]; then if ( {entry.oracle} ) >/dev/null 2>&1; "
           f"then echo {CORRECT}; else echo {SYMPTOM}; fi; fi")
    return {"cmd": cmd, "expect_stdout_contains": SYMPTOM, "correct_stdout_contains": CORRECT}


def _forbidden(path: str) -> bool:
    """Paths an edit may not touch: the operator's seed, the stage specs, the manifest, the exit request and the
    Founder's records (an edit there changes what the referee asks of the push, not the code under review), and what
    the rival is not shown."""
    return (is_seed_path(path) or path.startswith("spec/") or path in (cli.MANIFEST_FILE, cli.EXIT_FILE, LEDGER_FILE)
            or rival.hidden(path) or not path or path.startswith("/") or ".." in path.split("/"))


def load_catalog(path: Path = CATALOG) -> tuple[dict[str, str], dict[str, Host], list[Entry]]:
    """The defect kinds (name -> what it stands for), the host pushes and the entries, checked whole: a bad catalog
    stops the run."""
    doc = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(doc, dict) or doc.get("schema") != CATALOG_SCHEMA:
        raise CanaryError(f"{path.name}: schema must be {CATALOG_SCHEMA}")
    kinds = doc.get("kinds")
    if not isinstance(kinds, dict) or not kinds or CONTROL in kinds:
        raise CanaryError(f"{path.name}: kinds must name the defect kinds (and not {CONTROL!r})")
    hosts = {}
    for name, raw in (doc.get("hosts") or {}).items():
        if not isinstance(raw, dict) or not SHA40.match(str(raw.get("push"))) or not raw.get("why"):
            raise CanaryError(f"{path.name}: host {name} needs the push's full sha and why it is a fair host")
        hosts[name] = Host(name=name, push=raw["push"], why=raw["why"])
    entries, seen = [], set()
    for raw in doc.get("entries", []):
        edits = tuple(Edit(path=e["path"], old=e["old"], new=e["new"]) for e in raw["edits"])
        entry = Entry(id=raw["id"], kind=raw["kind"], host=raw.get("host"), edits=edits, oracle=raw.get("oracle"),
                      why=raw["why"], split=raw.get("split"), stratum=str(raw.get("stratum", "")))
        where = f"{path.name}: {entry.id}"
        if entry.split not in SPLITS:
            raise CanaryError(f"{where}: split must be one of {', '.join(SPLITS)}, fixed before any rival change")
        if entry.id in seen:
            raise CanaryError(f"{where}: id used twice")
        seen.add(entry.id)
        if entry.kind != CONTROL and entry.kind not in kinds:
            raise CanaryError(f"{where}: unknown kind {entry.kind!r}")
        if entry.host is not None and entry.host not in hosts:
            raise CanaryError(f"{where}: unknown host {entry.host!r}")
        if not edits or len({e.path for e in edits}) != len(edits):
            raise CanaryError(f"{where}: name its edits, at most one per file")
        for e in edits:
            if not e.old or e.old == e.new:
                raise CanaryError(f"{where}: an edit's old must be non-empty and differ from its new")
            if _forbidden(e.path):
                raise CanaryError(f"{where}: {e.path} is not the Founder's code under review")
        if entry.control and entry.oracle is not None:
            raise CanaryError(f"{where}: a control has no defect, so no oracle")
        if not entry.control:
            if len(edits) != 1:
                raise CanaryError(f"{where}: a plant is one edit")
            if not entry.oracle:
                raise CanaryError(f"{where}: a plant needs its oracle")
            if len(oracle_reproducer(entry)["cmd"]) > rival.MAX_CMD_CHARS:
                raise CanaryError(f"{where}: the oracle is too long for a reproducer "
                                  f"({rival.MAX_CMD_CHARS} characters)")
        entries.append(entry)
    if not any(e.control for e in entries) or all(e.control for e in entries):
        raise CanaryError(f"{path.name}: needs plants and controls")
    return dict(kinds), hosts, entries


def plant(text: str, entry: Entry, edit: Edit) -> str:
    found = text.count(edit.old)
    if found != 1:
        raise CanaryError(f"{entry.id}: its anchor occurs {found} times in {edit.path} at this base: re-anchor it")
    return text.replace(edit.old, edit.new)


def touched(text: str, edit: Edit) -> tuple[int, int]:
    """The head's lines the edit wrote (1-based, both ends); for a deletion, the two lines it now lies between."""
    first = text.count("\n", 0, text.index(edit.old)) + 1
    count = edit.new.count("\n") + (0 if edit.new.endswith("\n") else 1)
    return (first - 1, first) if not edit.new else (first, first + max(count, 1) - 1)


# ---- git: a read-only mirror of the brain and the canary's own commits -----------------------------------------------

def _git(repo: Path, *args: str, stdin: bytes | None = None, env: dict[str, str] | None = None) -> str:
    proc = subprocess.run(["git", *gitio.SAFE_CONFIG, "-C", str(repo), *args], input=stdin, capture_output=True,
                          env={**gitio._env(), **(env or {})}, check=False)
    if proc.returncode != 0:
        raise CanaryError(f"git {args[0]} failed: {proc.stderr.decode('utf-8', 'replace')[:300]}")
    return proc.stdout.decode().strip()


def plant_store(work: Path, mirror: Path) -> Path:
    """``plants.git``: the canary's own repository, borrowing the mirror's objects; the mirror is never written."""
    store = work / "plants.git"
    if not (store / "HEAD").exists():
        store.mkdir(parents=True, exist_ok=True)
        _git(store, "init", "--bare", "--quiet")
    (store / "objects" / "info" / "alternates").write_text((mirror / "objects").resolve().as_posix() + "\n",
                                                           encoding="utf-8", newline="\n")
    return store


def _entries_of(store: Path, commit: str) -> dict[str, tuple[str, str]]:
    return {path: (mode, sha) for mode, sha, path in gitio._entries(store, commit)}


def _write_tree(store: Path, entries: dict[str, tuple[str, str]]) -> str:
    """The tree of exactly these entries (path -> (mode, object)), built in a private index."""
    with tempfile.TemporaryDirectory(prefix="canary-index-") as tmp:
        index = {"GIT_INDEX_FILE": str(Path(tmp) / "index")}
        _git(store, "read-tree", "--empty", env=index)
        info = "".join(f"{mode} {sha}\t{path}\0" for path, (mode, sha) in sorted(entries.items()))
        _git(store, "update-index", "-z", "--index-info", stdin=info.encode("utf-8", "surrogateescape"), env=index)
        return _git(store, "write-tree", env=index)


def clean_head(store: Path, top: str, epochs: tuple[config.SeedEpoch, ...]) -> str:
    """``top`` itself when it holds every seed epoch commit and the last epoch's seed; otherwise a commit with ``top``'s
    tree but the last epoch's ``spec/tohum/`` and ``seed/``, whose parents are ``top`` and the last epoch's commit."""
    if not epochs:
        return top
    last = epochs[-1].commit
    if (all(gitio.is_ancestor(store, e.commit, top) for e in epochs)
            and gitio.same_under(store, last, top, SEED_DIRS)):
        return top
    if not gitio.has_commit(store, last):
        raise CanaryError(f"the brain mirror lacks the last seed epoch's commit {last}")
    entries = {p: v for p, v in _entries_of(store, top).items() if not is_seed_path(p)}
    entries.update({p: v for p, v in _entries_of(store, last).items() if is_seed_path(p)})
    sha = _git(store, "commit-tree", _write_tree(store, entries), "-p", top, "-p", last, "-m", "canary: clean head",
               env=PLANTER)
    missing = [e.commit for e in epochs if not gitio.is_ancestor(store, e.commit, sha)]
    if missing:
        raise CanaryError(f"seed epoch commits the summary names are not on the brain's history: {', '.join(missing)}")
    return sha


def plant_commit(store: Path, clean: str, entry: Entry) -> tuple[str, dict[str, list[int]]]:
    """A commit on ``clean`` with the entry's edits, and the lines each edit wrote there."""
    entries = _entries_of(store, clean)
    lines: dict[str, list[int]] = {}
    for edit in entry.edits:
        mode, sha = entries.get(edit.path, ("", ""))
        if mode not in ("100644", "100755"):
            raise CanaryError(f"{entry.id}: {edit.path} is not a file at {clean}")
        text = gitio.git(store, "cat-file", "blob", sha).decode("utf-8")
        blob = _git(store, "hash-object", "-w", "--no-filters", "--stdin",
                    stdin=plant(text, entry, edit).encode("utf-8"))
        entries[edit.path] = (mode, blob)
        lines[edit.path] = list(touched(text, edit))
    sha = _git(store, "commit-tree", _write_tree(store, entries), "-p", clean, "-m", "canary: push", env=PLANTER)
    return sha, lines


def host_bases(store: Path, state: dict[str, Any], hosts: dict[str, Host], entries: list[Entry]) -> dict[str, str]:
    """The base of each host the entries use: the push's single parent. A host must be a push the referee accepted (a
    survived rival artifact of the signed state on the accepted history), and a buried edit must lie in a file the
    host push changed: the defect goes inside the real diff, not beside it."""
    survived = {a["sha"] for a in state["rival_artifacts"] if a["outcome"] == "survived"}
    bases: dict[str, str] = {}
    for name in sorted({e.host for e in entries if e.host}):
        push = hosts[name].push
        if push not in survived or not gitio.is_ancestor(store, push, state["last_accepted_sha"]):
            raise CanaryError(f"host {name}: {push} is not a push the referee accepted")
        parents = _git(store, "rev-list", "--parents", "-n", "1", push).split()[1:]
        if len(parents) != 1:
            raise CanaryError(f"host {name}: {push} has {len(parents)} parents, not one")
        bases[name] = parents[0]
        changed = set(gitio.changed_paths(store, parents[0], push))
        for entry in entries:
            outside = [e.path for e in entry.edits if entry.host == name and e.path not in changed]
            if outside:
                raise CanaryError(f"{entry.id}: {', '.join(outside)} is not in host {name}'s diff")
    return bases


# ---- the live referee: a fresh read-only clone, and its code ---------------------------------------------------------

def fresh_referee_clone(work: Path, repo: str, ref: str | None = None) -> Path:
    """A new clone of the referee repository, never one a run before made: its default branch's head (shallow), or
    with ``ref`` that commit."""
    url = repo if "://" in repo or Path(repo).exists() else f"https://github.com/{repo}.git"
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    dest = work / "referee" / stamp
    dest.parent.mkdir(parents=True, exist_ok=True)
    depth = [] if ref else ["--depth", "1"]
    proc = subprocess.run(["git", "-c", "core.autocrlf=false", "clone", "--quiet", *depth, "--no-tags", url, str(dest)],
                          capture_output=True, env=gitio._env(), check=False)
    if proc.returncode == 0 and ref:
        proc = subprocess.run(["git", "-C", str(dest), "checkout", "--quiet", "--detach", ref], capture_output=True,
                              env=gitio._env(), check=False)
    if proc.returncode != 0:
        raise CanaryError(f"the referee repository could not be cloned: {proc.stderr.decode('utf-8', 'replace')[:300]}")
    return dest


def rival_sha256(root: Path) -> str:
    """What the rival reads and runs in a referee clone, line endings read as LF: its seat prompt, ``bootstrap.json``
    (model, effort, turns, cap, limits, image), ``policy.json`` (budget), its code (the CLI run, the MCP tools, the
    reproducers, the secret scan) and the CLI it pins. ``decide`` is not in it: its proof rule is read from the
    loaded code, and a pinned run says which referee commit that was."""
    digest = hashlib.sha256()
    for part in RIVAL_PARTS:
        paths = [root / part] if (root / part).is_file() else sorted(p for p in (root / part).rglob("*") if p.is_file())
        for p in paths:
            digest.update(p.relative_to(root).as_posix().encode() + b"\0" + p.read_bytes().replace(b"\r\n", b"\n"))
    return digest.hexdigest()


def pinned_referee(work: Path, repo: str, ref: str) -> tuple[Path, str]:
    """A fresh clone at ``ref`` and the live head's commit, for a batch screened against ``ref`` whose reviews were
    lost (an outage) after the live referee moved on: allowed only while the rival the live head runs is the one
    ``ref`` runs (``rival_sha256``), so the measure is still the live rival's."""
    pinned, live = fresh_referee_clone(work, repo, ref), fresh_referee_clone(work, repo)
    if rival_sha256(pinned) != rival_sha256(live):
        raise CanaryError(f"the rival the live referee runs is not the one {ref} runs: measure against the live head")
    return pinned, gitio.git(live, "rev-parse", "HEAD").decode().strip()


def code_sha256(bootstrap: Path) -> str:
    """The referee code's identity: every file of ``CODE_PARTS`` under ``bootstrap`` with its relative path, line
    endings read as LF (a Windows checkout and the referee's clone of one commit are the same code)."""
    digest = hashlib.sha256()
    for part in CODE_PARTS:
        for p in sorted(x for x in (bootstrap / part).rglob("*") if x.is_file() and "__pycache__" not in x.parts):
            digest.update(p.relative_to(bootstrap).as_posix().encode() + b"\0")
            digest.update(p.read_bytes().replace(b"\r\n", b"\n") + b"\0")
    return digest.hexdigest()


def referee_identity(root: Path, repo: str) -> dict[str, Any]:
    """What a result names of the referee it was measured against."""
    return {"repo": repo, "commit": gitio.git(root, "rev-parse", "HEAD").decode().strip(),
            "seats_sha256": hashlib.sha256((root / SEATS).read_bytes()).hexdigest(),
            "bootstrap_json_sha256": hashlib.sha256((root / "bootstrap.json").read_bytes()).hexdigest(),
            "code_sha256": code_sha256(root / "bootstrap")}


# ---- what the referee's own code says --------------------------------------------------------------------------------

@dataclass
class CanaryRunner(DockerRunner):
    """The referee's sandbox (``DockerRunner.argv``, every flag its own) under the canary's container name, so the
    operator tells the canary's containers from the pilot's and removes only its own."""

    def run(self, cmd: str, *, cwd: str = ".", stdin: bytes = b"", timeout_s: int) -> RunResult:
        if ".." in cwd.split("/") or cwd.startswith("/"):
            raise ValueError("cwd must be a relative path inside the source tree")
        name = CONTAINER_PREFIX + uuid.uuid4().hex[:16]
        argv = self.argv(name, cmd, cwd)
        start = time.monotonic()
        try:
            proc = subprocess.run(argv, input=stdin, capture_output=True, timeout=timeout_s, check=False)
        except subprocess.TimeoutExpired as exc:
            subprocess.run([self.docker, "rm", "-f", name], capture_output=True, check=False)
            return RunResult(124, exc.stdout or b"", exc.stderr or b"", int((time.monotonic() - start) * 1000),
                             timed_out=True)
        return RunResult(proc.returncode, proc.stdout, proc.stderr, int((time.monotonic() - start) * 1000))


@contextlib.contextmanager
def referee_runs(make_runner: MakeRunner, vector_budget_s: int):
    """While inside, the referee's commands start their containers through ``make_runner`` and give their vector calls
    ``vector_budget_s`` in all; both are restored after. The budget is the default of ``VectorRun.__init__`` itself,
    so every run built on it (the single job's, a part's, E440) gets it without the canary naming each one."""
    runner, init = cli._runner, vectors.VectorRun.__init__

    def widened(self: Any, runner_: Runner, timeout_s: int, budget_s: int = vector_budget_s) -> None:
        init(self, runner_, timeout_s, budget_s)

    cli._runner = lambda _boot, src, deps, vec, locks: make_runner(src, deps, vec, list(locks))
    vectors.VectorRun.__init__ = widened
    try:
        yield
    finally:
        cli._runner, vectors.VectorRun.__init__ = runner, init


def proven(meta: dict[str, Any], run: dict[str, Any], rival_doc: dict[str, Any], head_results: list[dict[str, Any]],
           policy: config.Policy) -> set[int]:
    """The attempts the referee's ``decide`` holds proven on the push (`29`, E260), from the push's own screen: only
    this rival's reproducers are judged, the state's own were not part of the push."""
    meta = copy.deepcopy(meta)
    meta["state_repro"] = []
    jobs = {"getir": "success", "kos": "success", "cagir": "success", "yeniden": "success"}
    result = decide(meta, run, rival_doc, head_results, jobs, policy.rival_min_attempts, policy.repeat_reject_limit,
                    state_repro=[])
    keys = {r["ref"].removeprefix("repro:") for r in result["reasons"] if r["kind"] == "refutation_reproduced"}
    return {r["attempt_index"] for r in head_results if r["key"] in keys}


def classify(entry: Entry, rival_doc: dict[str, Any], proofs: set[int], on_head: list[dict[str, Any]],
             on_clean: list[dict[str, Any]], on_base: list[dict[str, Any]] | None,
             lines: dict[str, list[int]]) -> dict[str, Any]:
    """What the rival did with one push. ``on_base`` is None for a whole-diff entry, whose base is its clean head's
    code. The outcome's order: an outage, no verdict, a docker failure under any reproducer run, then the proofs by
    where else their symptom shows (the module docstring, step 7), then a refutation without a proof."""
    reasons = [str(r) for r in rival_doc.get("reasons", [])]
    verdict = rival_doc.get("verdict")
    attempts = rival_doc.get("attempts", []) if verdict in ("refuted", "not_refuted") else []
    clean_shown = {r["attempt_index"]: r["shown"] for r in on_clean}
    base_shown = clean_shown if on_base is None else {r["attempt_index"]: r["shown"] for r in on_base}
    new = sorted(i for i in proofs if not clean_shown[i])
    in_host = sorted(i for i in proofs if clean_shown[i] and not base_shown[i])
    old = sorted(i for i in proofs if clean_shown[i] and base_shown[i])
    if any(r.startswith("api_error") for r in reasons):
        outcome = "outage"
    elif verdict not in ("refuted", "not_refuted"):
        outcome = "unresolved"
    elif any(r["runner_fault"] for r in on_head + on_clean + (on_base or [])):
        outcome = "runner_fault"
    elif new:
        outcome = "false_refutation" if entry.control else "caught"
    elif in_host:
        outcome = "proven_in_host"
    elif old:
        outcome = "preexisting_defect" if entry.control else "proven_on_base"
    elif verdict == "refuted":
        outcome = "refuted_unproven"
    else:
        outcome = "not_refuted"
    pointed = any(ref["path"] in lines and ref["line_start"] <= lines[ref["path"]][1]
                  and ref["line_end"] >= lines[ref["path"]][0] for a in attempts for ref in a["evidence_refs"])
    return {"outcome": outcome, "proven_new": new, "proven_in_host": in_host, "proven_on_base": old,
            "attempts": len(attempts), "with_reproducer": sum(1 for a in attempts if "reproducer" in a),
            "pointed_at_plant": pointed, "reasons": reasons}


def cp_upper(x: int, n: int, alpha: float) -> float:
    """The one-sided upper bound: one minus the lower bound of the other side's count."""
    return 1 - cp_lower(n - x, n, alpha)


def _rate(x: int, n: int) -> dict[str, Any]:
    return {"x": x, "n": n, "rate": round(x / n, 4) if n else None,
            "cp_lower": round(cp_lower(x, n, ALPHA), 4) if n else None,
            "cp_upper": round(cp_upper(x, n, ALPHA), 4) if n else None}


def result_of(rec: dict[str, Any]) -> str:
    """A judged plant in one word: ``proven`` (caught), ``found`` (an attempt pointed at the planted lines, no proof of
    the plant) or ``missed``."""
    return "proven" if rec["outcome"] == "caught" else "found" if rec["pointed_at_plant"] else "missed"


def summarize(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Recall overall, per kind and per mode over the plants the rival judged, the plants found, false refutations over
    the controls it judged, what was there before the edit, and what the reviews cost (the CLI's list-price estimate,
    the runs that judged nothing included)."""
    judged = [r for r in records if r["status"] == "reviewed" and r["outcome"] not in NOT_JUDGED]
    plants = [r for r in judged if r["kind"] != CONTROL]
    controls = [r for r in judged if r["kind"] == CONTROL]
    by_kind = {kind: _rate(sum(r["outcome"] == "caught" for r in plants if r["kind"] == kind),
                           sum(1 for r in plants if r["kind"] == kind)) for kind in sorted({r["kind"] for r in plants})}
    by_mode = {mode: _rate(sum(r["outcome"] == "caught" for r in plants if r["mode"] == mode),
                           sum(1 for r in plants if r["mode"] == mode))
               for mode in MODES if any(r["mode"] == mode for r in plants)}
    reviewed = [r for r in records if r["status"] == "reviewed"]
    judged_ids = {r["id"] for r in judged}
    return {"alpha": ALPHA,
            "recall": {"overall": _rate(sum(r["outcome"] == "caught" for r in plants), len(plants)),
                       "by_kind": by_kind, "by_mode": by_mode,
                       "by_split": {split: _rate(sum(r["outcome"] == "caught" for r in plants if r["split"] == split),
                                                 sum(1 for r in plants if r["split"] == split))
                                    for split in SPLITS if any(r["split"] == split for r in plants)}},
            "found": _rate(sum(r["pointed_at_plant"] for r in plants), len(plants)),
            "false_refutations": _rate(sum(r["outcome"] == "false_refutation" for r in controls), len(controls)),
            "there_before": {"proven_on_base": [r["id"] for r in plants if r["outcome"] == "proven_on_base"],
                             "preexisting_defect": [r["id"] for r in controls if r["outcome"] == "preexisting_defect"],
                             "proven_in_host": [r["id"] for r in judged if r["outcome"] == "proven_in_host"]},
            "cost_usd_micros": sum(r["cost_usd_micros"] for r in reviewed),
            "turns": sum(r["turns"] for r in reviewed), "reviews": len(reviewed),
            "not_judged": {r["id"]: r["outcome"] or r["status"] for r in records if r["id"] not in judged_ids}}


# ---- the rival: the real one through the referee's command, or the oracle-informed fake ------------------------------

Reviewer = Callable[[Entry, dict[str, list[int]], Path, Path], dict[str, Any]]


@contextlib.contextmanager
def _log(path: Path):
    """A referee command's step outputs and notices go to a file in the entry's folder, not to the console."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as log, contextlib.redirect_stdout(log):
        yield


@contextlib.contextmanager
def keep_transcript(dest: Path):
    """Every rival CLI run inside the block leaves its request, system prompt, arguments and stream-json output in
    ``dest``. The call is passed through unchanged: ``rival._run_cli`` is wrapped, not replaced, and restored."""
    original = rival._run_cli

    def tee(argv: list[str], stdin: str, cwd: Path, env: dict[str, str], on_init: Any = None) -> tuple[int, str]:
        dest.mkdir(parents=True, exist_ok=True)
        (dest / "request.txt").write_text(stdin, encoding="utf-8", newline="\n")
        shutil.copyfile(Path(cwd).parent / "system.txt", dest / "system.txt")
        (dest / "argv.json").write_text(json.dumps(argv[1:]), encoding="utf-8")  # the binary's path left out
        code, out = original(argv, stdin, cwd, env, on_init=on_init)
        (dest / "transcript.jsonl").write_text(out, encoding="utf-8", newline="\n")
        return code, out

    rival._run_cli = tee
    try:
        yield
    finally:
        rival._run_cli = original


def live_reviewer(root: Path, claude: str | None) -> Reviewer:
    """The referee's ``rival`` command over the pulled request alone: neither the entry nor its lines are passed on."""
    def review(_entry: Entry, _lines: dict[str, list[int]], pulled: Path, out: Path) -> dict[str, Any]:
        argv = ["rival", "--root", str(root), "--pulled", str(pulled), "--work", str(out / "work"), "--out", str(out)]
        out.mkdir(parents=True, exist_ok=True)
        with keep_transcript(out / "transcript"), _log(out / "rival.log"):
            code = cli.main(argv + (["--claude", claude] if claude else []))
        if code != 0 or not (out / "rival.json").is_file():
            raise CanaryError(f"the rival command stopped (exit {code}) before writing rival.json")
        return json.loads((out / "rival.json").read_text(encoding="utf-8"))
    return review


def oracle_reviewer(entry: Entry, lines: dict[str, list[int]], pulled: Path, out: Path) -> dict[str, Any]:
    """The dry run's fake rival: it refutes every plant with its own oracle at the planted line and finds nothing in a
    control. Its verdict passes the referee's validator like the real rival's must."""
    meta = json.loads((pulled / "meta.json").read_text(encoding="utf-8"))
    tree = out / "tree"
    tar = (pulled / "brain.tar").read_bytes()
    extract(tar, tree, len(tar))
    raw: dict[str, Any] = {"verdict": "not_refuted", "attempts": []}
    if not entry.control:
        path = entry.edits[0].path
        line = max(lines[path][0], 1)
        raw = {"verdict": "refuted", "attempts": [{
            "claim": f"{path}:{line} breaks what its oracle checks.",
            "evidence_refs": [{"path": path, "line_start": line, "line_end": line}],
            "reproducer": oracle_reproducer(entry)}]}
    verdict = rival.validate_verdict(raw, rival.ToolBox(tree))
    doc = rival.RivalOutcome(verdict=verdict["verdict"], attempts=verdict["attempts"], model_requested="fake:oracle",
                             model_served="fake:oracle").as_dict()
    doc["head"] = meta["head"]
    out.mkdir(parents=True, exist_ok=True)
    (out / "rival.json").write_text(json.dumps(doc, indent=1), encoding="utf-8", newline="\n")
    return doc


# ---- one batch ------------------------------------------------------------------------------------------------------

def _ran(res: RunResult) -> dict[str, Any]:
    return {"exit": res.exit_code, "timed_out": res.timed_out,
            "tail": (res.stdout + b"\n" + res.stderr).decode("utf-8", "replace")[-1500:]}


def check_oracle(runner_for: Callable[[Path], Runner], clean_tree: Path, head_tree: Path, entry: Entry,
                 timeout_s: int) -> dict[str, Any]:
    """The plant is a defect only when its oracle passes on the clean head and fails, on its own, on the push: a
    docker failure there (exit 125) is the sandbox's, not the plant's."""
    base = _ran(runner_for(clean_tree).run(entry.oracle, timeout_s=timeout_s))
    head = _ran(runner_for(head_tree).run(entry.oracle, timeout_s=timeout_s))
    valid = (base["exit"] == 0 and not base["timed_out"] and not head["timed_out"]
             and head["exit"] not in (0, reproduce.DOCKER_ERROR))
    return {"base": base, "head": head, "valid": valid}


def screen_verdict(run: dict[str, Any]) -> str:
    """The referee's ``run.json`` read the way ``decide`` reads it: ``fault`` (its runner controls failed, or docker
    under a test, a vector or a module-less run), ``green``, ``timed_out`` (every failing check ran out of time: this
    machine, not the push) or ``red``."""
    tests, vecs, less = run.get("tests", []), run.get("vectors", []), run.get("module_less", [])
    if (not all(c["ok"] for c in run.get("controls", [])) or any(t.get("exit") == reproduce.DOCKER_ERROR for t in tests)
            or any(v.get("runner_fault") for v in vecs) or any(m.get("runner_fault") for m in less)):
        return "fault"
    if run.get("green"):
        return "green"
    late = [t.get("timed_out") for t in tests if not t["ok"]] + [m["timed_out"] for m in less if m["stayed_green"]]
    late += ["not_run:time_budget" in v.get("detail", "") or "timed out" in v.get("detail", "")
             for v in vecs if not v["ok"]]
    late += [False for x in run.get("licenses", []) if not x["allowed"]]
    return "timed_out" if late and all(late) else "red"


def _failing(run: dict[str, Any]) -> list[str]:
    return ([t["id"] for t in run.get("tests", []) if not t["ok"]]
            + [v["id"] for v in run.get("vectors", []) if not v["ok"]]
            + [f"module_less:{m['test_id']}" for m in run.get("module_less", []) if m["stayed_green"]]
            + [f"license:{x['name']}" for x in run.get("licenses", []) if not x["allowed"]])


@dataclass
class Batch:
    root: Path  # the fresh read-only clone of the live referee repository
    referee: dict[str, Any]  # ``referee_identity`` of root: repository, commit, seat prompt hash, code hash
    state: dict[str, Any]  # the live signed state
    mirror: Path  # the brain, read-only
    store: Path  # plants.git (``plant_store``)
    screens: Path  # the kept screens (``screens/``)
    run_dir: Path
    hosts: dict[str, Host]
    entries: list[Entry]
    make_runner: MakeRunner
    reviewer: Reviewer
    mode: str
    max_usd: float = MAX_USD
    vector_budget_s: int = VECTOR_BUDGET_FACTOR * vectors.BUDGET_S
    echo: Callable[[str], None] = print  # one line per entry as the batch goes
    _trees: dict[str, Path] = field(default_factory=dict)
    _cleans: dict[str, str] = field(default_factory=dict)

    def tree(self, commit: str) -> Path:
        """A commit's files, extracted once per run (the oracle's and the reproducers' trees)."""
        if commit not in self._trees:
            dest = self.run_dir / "trees" / commit[:16]
            extract(gitio.archive(self.store, commit), dest, 2_000_000_000)
            self._trees[commit] = dest
        return self._trees[commit]


def screen(batch: Batch, boot: config.Bootstrap, meta: dict[str, Any], commit: str, pulled: Path,
           deps: Path) -> dict[str, Any]:
    """The referee's ``run-tests`` on ``commit`` (``pulled`` holds its meta.json and brain.tar), kept per referee
    commit, tree, manifest and module-less list. A screen that only ran out of time or whose sandbox failed is not
    kept: the next run tries again."""
    tree_sha = _git(batch.store, "rev-parse", f"{commit}^{{tree}}")
    key = hashlib.sha256(json.dumps([batch.referee["commit"], tree_sha, meta["manifest"],
                                     meta.get("module_less") or []], sort_keys=True).encode()).hexdigest()[:32]
    kept = batch.screens / f"{key}.json"
    if kept.is_file():
        doc = json.loads(kept.read_text(encoding="utf-8"))
        return {"key": key, "verdict": doc["verdict"], "failing": _failing(doc["run"]), "seconds": doc["seconds"],
                "kept": True, "run": doc["run"]}
    work = batch.run_dir / "screen-work" / key
    out = work / "run"
    started = time.monotonic()
    with referee_runs(batch.make_runner, batch.vector_budget_s), _log(batch.run_dir / "screens" / f"{key}.log"):
        code = cli.main(["run-tests", "--root", str(batch.root), "--pulled", str(pulled), "--deps", str(deps),
                         "--work", str(work), "--out", str(out)])
    if code != 0 or not (out / "run.json").is_file():
        raise CanaryError(f"run-tests stopped (exit {code}) on {commit}")
    run = json.loads((out / "run.json").read_text(encoding="utf-8"))
    seconds = round(time.monotonic() - started)
    verdict = screen_verdict(run)
    if verdict in ("green", "red"):
        batch.screens.mkdir(parents=True, exist_ok=True)
        kept.write_text(json.dumps({"commit": commit, "tree": tree_sha, "referee": batch.referee["commit"],
                                    "boot_limits": {"test_timeout_s": boot.limits.test_timeout_s},
                                    "vector_budget_s": batch.vector_budget_s, "seconds": seconds, "verdict": verdict,
                                    "run": run}, indent=1), encoding="utf-8", newline="\n")
    shutil.rmtree(work, ignore_errors=True)
    return {"key": key, "verdict": verdict, "failing": _failing(run), "seconds": seconds, "kept": False, "run": run}


def _pulled_as(dest: Path, meta: dict[str, Any], commit: str, tar: bytes) -> Path:
    """A pulled folder for ``commit`` with the push's meta (the same manifest and module-less list): what ``run-tests``
    reads of a clean head."""
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "meta.json").write_text(json.dumps(dict(meta, head=commit)), encoding="utf-8")
    (dest / "brain.tar").write_bytes(tar)
    return dest


def prepare(batch: Batch, boot: config.Bootstrap, bases: dict[str, str], entry: Entry) -> dict[str, Any]:
    """Everything before the rival, which spends nothing: the push, its pull, the clean head's screen, the oracle and
    the push's screen. The record's status is ``screened`` when the rival may see the push."""
    store, out = batch.store, batch.run_dir / entry.id
    out.mkdir(parents=True, exist_ok=True)
    last = batch.state["last_accepted_sha"]
    base = bases[entry.host] if entry.host else last
    top = batch.hosts[entry.host].push if entry.host else last
    if top not in batch._cleans:
        batch._cleans[top] = clean_head(store, top, config.load_summary(batch.root).epochs)
    clean = batch._cleans[top]
    rec: dict[str, Any] = {"id": entry.id, "kind": entry.kind, "mode": entry.mode, "split": entry.split,
                           "stratum": entry.stratum, "host": entry.host,
                           "paths": [e.path for e in entry.edits], "base": base, "clean_head": clean,
                           "referee": {k: batch.referee[k] for k in ("commit", "seats_sha256")}, "status": "",
                           "outcome": None, "cost_usd_micros": 0, "turns": 0, "pointed_at_plant": False}
    head, lines = plant_commit(store, clean, entry)
    rec.update(head=head, lines=lines)
    _git(store, "update-ref", "refs/heads/" + boot.brain_branch, head)
    (out / "state.json").write_text(json.dumps(dict(batch.state, last_accepted_sha=base)), encoding="utf-8")
    pulled = out / "pulled"
    with _log(out / "pull.log"):
        code = cli.main(["pull", "--root", str(batch.root), "--state", str(out / "state.json"), "--work",
                         str(batch.run_dir / "git"), "--out", str(pulled), "--remote", str(store)])
    if code != 0:
        raise CanaryError(f"{entry.id}: pull stopped (see {out / 'pull.log'})")
    meta = json.loads((pulled / "meta.json").read_text(encoding="utf-8"))
    rec["pull"] = {"kind": meta["kind"], "pre_reasons": meta["pre_reasons"], "run_rival": meta["run_rival"],
                   "changed": len(meta["changed"]), "module_less": meta["module_less"]}
    if meta["kind"] != "code" or meta["pre_reasons"] or not meta["run_rival"] or not meta["run_tests"]:
        rec["status"] = "not_reviewable"
        return rec
    deps = out / "deps"
    with _log(out / "fetch-deps.log"):
        if cli.main(["fetch-deps", "--pulled", str(pulled), "--work", str(out / "deps-work"), "--out", str(deps)]) != 0:
            raise CanaryError(f"{entry.id}: fetch-deps stopped")
    rec["clean_screen"] = {k: v for k, v in screen(batch, boot, meta, clean, _pulled_as(
        batch.run_dir / "clean-pulled" / clean[:16], meta, clean, gitio.archive(store, clean)), deps).items()
        if k != "run"}
    if rec["clean_screen"]["verdict"] != "green":
        raise CanaryError(f"the clean head {clean} is {rec['clean_screen']['verdict']} under the referee's run-tests "
                          f"on this machine ({', '.join(rec['clean_screen']['failing'][:8])}): the batch stops, "
                          "nothing is scored")
    locks = meta["manifest"]["lockfiles"]
    runner_for = lambda tree: batch.make_runner(tree, deps, batch.run_dir / "vec", locks)  # noqa: E731
    if not entry.control:
        rec["oracle"] = check_oracle(runner_for, batch.tree(clean), batch.tree(head), entry, boot.limits.test_timeout_s)
        if not rec["oracle"]["valid"]:
            rec["status"] = "oracle_invalid"
            return rec
    done = screen(batch, boot, meta, head, pulled, deps)
    rec["screen"] = {k: v for k, v in done.items() if k != "run"}
    verdict = done["verdict"]
    rec["status"] = {"green": "screened", "red": "caught_by_suite", "timed_out": "screen_timed_out",
                     "fault": "screen_fault"}[verdict]
    if verdict == "green":
        (out / "run.json").write_text(json.dumps(done["run"]), encoding="utf-8")
    return rec


def review(batch: Batch, boot: config.Bootstrap, policy: config.Policy, entry: Entry, rec: dict[str, Any]) -> None:
    """The rival, its reproducers on the push, the clean head and (buried) the base, and the referee's proof rule."""
    out = batch.run_dir / entry.id
    pulled = out / "pulled"
    meta = json.loads((pulled / "meta.json").read_text(encoding="utf-8"))
    rival_doc = batch.reviewer(entry, rec["lines"], pulled, out / "rival")
    rec.update(status="reviewed", cost_usd_micros=int(rival_doc.get("cost_usd_micros", 0)),
               turns=int(rival_doc.get("turns", 0)), model_served=rival_doc.get("model_served", ""),
               verdict=rival_doc.get("verdict"))
    attempts = rival_doc["attempts"] if rival_doc.get("verdict") in ("refuted", "not_refuted") else []
    timeout, locks = boot.limits.reproducer_timeout_s, meta["manifest"]["lockfiles"]
    vec, deps = batch.run_dir / "vec", out / "deps"
    control = batch.make_runner(batch.run_dir / "empty-tree", deps, vec, [])

    def on(commit: str) -> list[dict[str, Any]]:
        return reproduce.run_reproducers(batch.make_runner(batch.tree(commit), deps, vec, locks), attempts, timeout,
                                         control=control)

    on_head, on_clean = on(rec["head"]), on(rec["clean_head"])
    on_base = on(rec["base"]) if entry.host else None
    rec["reproducers"] = {"head": on_head, "clean": on_clean, "base": on_base}
    run = json.loads((out / "run.json").read_text(encoding="utf-8"))
    rec.update(classify(entry, rival_doc, proven(meta, run, rival_doc, on_head, policy), on_head, on_clean, on_base,
                        rec["lines"]))
    if not entry.control and rec["outcome"] not in NOT_JUDGED:
        rec["result"] = result_of(rec)


def _write(path: Path, doc: Any) -> None:
    path.write_text(json.dumps(doc, indent=1), encoding="utf-8", newline="\n")


def run_batch(batch: Batch) -> dict[str, Any]:
    boot, policy = config.load_bootstrap(batch.root), config.load_policy(batch.root)
    # The live state as the referee's fetch-state reads it: an older schema carried forward, then checked (`25`).
    batch.state = state = st.validate(st.migrate(copy.deepcopy(batch.state), utc_now()))
    if not gitio.has_commit(batch.mirror, state["last_accepted_sha"]):
        raise CanaryError(f"the brain mirror lacks the accepted base {state['last_accepted_sha']}")
    bases = host_bases(batch.store, state, batch.hosts, batch.entries)
    batch.run_dir.mkdir(parents=True, exist_ok=True)
    vectors.fixtures(batch.root / "vectors", batch.run_dir / "vec")
    empty = batch.run_dir / "empty-tree"
    empty.mkdir(exist_ok=True)
    empty.chmod(0o755)  # the container's user (65534) copies it like /src
    prepared = []
    for entry in batch.entries:  # every screen before the first review: a red clean head stops what nothing paid for
        rec = prepare(batch, boot, bases, entry)
        _write(batch.run_dir / entry.id / "record.json", rec)
        batch.echo(f"{entry.id:30} {entry.mode:6} {entry.kind:20} {rec['status']}")
        prepared.append((entry, rec))
    records: list[dict[str, Any]] = []
    for entry, rec in prepared:
        if rec["status"] == "screened":
            if sum(r["cost_usd_micros"] for r in records) >= batch.max_usd * 1_000_000:
                rec["status"] = "cost_brake"
            else:
                try:
                    review(batch, boot, policy, entry, rec)
                except CanaryError as exc:  # the rival command stopped: this push is not judged, the batch goes on
                    rec.update(status="rival_stopped", error=str(exc)[:500])
                _write(batch.run_dir / entry.id / "record.json", rec)
                batch.echo(f"{entry.id:30} {rec['outcome'] or rec['status']:18} {rec.get('result', ''):7} "
                           f"{rec['cost_usd_micros'] / 1e6:.2f} USD {rec['turns']} turns")
        records.append(rec)
    results = {"schema": RESULTS_SCHEMA, "mode": batch.mode, "last_accepted": state["last_accepted_sha"],
               "referee": batch.referee,
               "rival": {"model": boot.rival.model, "effort": boot.rival.effort, "max_turns": boot.rival.max_turns,
                         "per_run_cap_usd_micros": boot.rival.per_run_cap_usd_micros,
                         "version": rival_version(boot, batch.referee)},
               "screen": {"test_timeout_s": boot.limits.test_timeout_s, "vector_budget_s": batch.vector_budget_s,
                          "referee_vector_budget_s": vectors.BUDGET_S},
               "hosts": {name: {"push": batch.hosts[name].push, "base": base} for name, base in bases.items()},
               "records": records, "summary": summarize(records)}
    _write(batch.run_dir / "results.json", results)
    (batch.run_dir / "report.md").write_text(report(results), encoding="utf-8", newline="\n")
    return results


def rival_version(boot: config.Bootstrap, referee: dict[str, Any]) -> str:
    """What the rival is: model, effort, turns, cap, seat prompt, the referee code its prompt and reproducers come
    from, and the sandbox image. Any change is a new rival version, and a new scorecard epoch."""
    doc = [boot.rival.model, boot.rival.effort, boot.rival.max_turns, boot.rival.per_run_cap_usd_micros,
           referee["seats_sha256"], referee["code_sha256"], boot.image]
    return hashlib.sha256(json.dumps(doc).encode()).hexdigest()[:16]


def aggregate(results: dict[str, Any]) -> dict[str, Any]:
    """What the private karne keeps of a run: rates, cost and the rival version, never an entry's id or outcome."""
    s = results["summary"]
    return {"schema": "snowball-rival-canary-aggregate/1", "mode": results["mode"], "rival": results["rival"],
            "referee": {k: results["referee"][k] for k in ("commit", "seats_sha256")}, "alpha": s["alpha"],
            "recall": s["recall"], "found": s["found"], "false_refutations": s["false_refutations"],
            "there_before": {k: len(v) for k, v in s["there_before"].items()}, "not_judged": len(s["not_judged"]),
            "reviews": s["reviews"], "turns": s["turns"], "cost_usd_micros": s["cost_usd_micros"]}


def report(results: dict[str, Any]) -> str:
    s, ref = results["summary"], results["referee"]

    def rate(r: dict[str, Any]) -> str:
        return f"{r['x']}/{r['n']}" + (f" (90% one-sided bounds {r['cp_lower']:.2f}..{r['cp_upper']:.2f})"
                                       if r["n"] else "")

    lines = [f"# Rival canary, {results['mode']} run", "",
             "Report only, never a gate (E126): too few plants per rival version to gate on (20 to 30 or more first).",
             f"Rival version `{results['rival']['version']}` (a new one is a new scorecard epoch).", "",
             f"Referee `{ref['repo']}` at `{ref['commit']}` (seat prompt sha256 `{ref['seats_sha256'][:16]}`); "
             f"last accepted `{results['last_accepted']}`; rival {results['rival']['model']}, effort "
             f"{results['rival']['effort']}, {results['rival']['max_turns']} turns, cap "
             f"{results['rival']['per_run_cap_usd_micros'] / 1e6:.2f} USD.",
             *[f"Host `{name}`: push `{h['push']}` against its parent `{h['base']}`."
               for name, h in results["hosts"].items()],
             f"Screen: the referee's run-tests, test timeout {results['screen']['test_timeout_s']} s, vector budget "
             f"{results['screen']['vector_budget_s']} s (the referee's "
             f"{results['screen']['referee_vector_budget_s']} s).",
             f"Clopper-Pearson bounds at alpha {s['alpha']}.", "",
             f"- Recall (proven): {rate(s['recall']['overall'])}",
             *[f"  - {mode}: {rate(r)}" for mode, r in s["recall"]["by_mode"].items()],
             *[f"  - {split} split: {rate(r)}" for split, r in s["recall"]["by_split"].items()],
             *[f"  - {kind}: {rate(r)}" for kind, r in s["recall"]["by_kind"].items()],
             f"- Found (an attempt at the planted lines): {rate(s['found'])}",
             f"- False refutations on controls: {rate(s['false_refutations'])}",
             f"- There before the edit: {json.dumps(s['there_before'])}",
             f"- Cost: {s['cost_usd_micros'] / 1e6:.2f} USD over {s['reviews']} reviews, {s['turns']} turns",
             f"- Not judged: {json.dumps(s['not_judged'])}", "",
             "| entry | mode | split | stratum | kind | status | outcome | result | attempts | with reproducer | USD "
             "| turns |", "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in results["records"]:
        lines.append(f"| {r['id']} | {r['mode']} | {r.get('split', '')} | {r.get('stratum', '')} | {r['kind']} | "
                     f"{r['status']} | {r['outcome'] or ''} | "
                     f"{r.get('result', '')} | {r.get('attempts', '')} | {r.get('with_reproducer', '')} | "
                     f"{r['cost_usd_micros'] / 1e6:.2f} | {r['turns']} |")
    return "\n".join(lines) + "\n"


# ---- command line ----------------------------------------------------------------------------------------------------

def select(entries: list[Entry], only: str | None, mode: str, plants: int, controls: int) -> list[Entry]:
    if only:
        wanted = only.split(",")
        unknown = sorted(set(wanted) - {e.id for e in entries})
        if unknown:
            raise CanaryError(f"no such entry: {', '.join(unknown)}")
        return [e for e in entries if e.id in wanted]
    pool = [e for e in entries if mode == "all" or e.mode == mode]
    return [e for e in pool if not e.control][:plants] + [e for e in pool if e.control][:controls]


def load_state(path: Path) -> dict[str, Any]:
    """A signed result (``result.json``, whose ``state`` is read) or a bare state."""
    doc = json.loads(path.read_text(encoding="utf-8"))
    return doc["state"] if isinstance(doc, dict) and "state" in doc and "verdict" in doc else doc


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--work", required=True, help="a private folder outside the repository")
    parser.add_argument("--referee-repo", default=DEFAULT_REFEREE, help="the live referee repository (cloned afresh)")
    parser.add_argument("--referee-clone", help=argparse.SUPPRESS)  # the clone, when the canary runs itself again on it
    parser.add_argument("--referee-ref", help="a referee commit the batch was screened against, when the live head "
                        "moved on since and runs the same rival (pinned_referee); the result names both")
    parser.add_argument("--live-head", help=argparse.SUPPRESS)  # the live head a pinned run was checked against
    parser.add_argument("--result",
                        help="the referee's signed result or state (default: <work>/../referee/result.json)")
    parser.add_argument("--brain-remote", help="where the brain is read (default: the repository bootstrap.json names)")
    parser.add_argument("--live", action="store_true", help="the real rival through your claude login (spends)")
    parser.add_argument("--claude", help="path of the claude CLI (default: the one on PATH)")
    parser.add_argument("--only", help="entry ids, comma-separated")
    parser.add_argument("--mode", choices=("all",) + MODES, default="all")
    parser.add_argument("--plants", type=int, default=FIRST_BATCH[0])
    parser.add_argument("--controls", type=int, default=FIRST_BATCH[1])
    parser.add_argument("--max-usd", type=float, default=MAX_USD)
    parser.add_argument("--karne", help="the private karne folder: an aggregate of the run (rates only) is added there")
    args = parser.parse_args(argv)
    work = Path(args.work).resolve()
    live_head = args.live_head
    if args.referee_clone:
        root = Path(args.referee_clone)
    elif args.referee_ref:
        root, live_head = pinned_referee(work, args.referee_repo, args.referee_ref)
        argv += ["--live-head", live_head]
    else:
        root = fresh_referee_clone(work, args.referee_repo)
    referee = referee_identity(root, args.referee_repo)
    if live_head:
        referee.update(live_head=live_head, rival_sha256=rival_sha256(root))
    if code_sha256(CODE) != referee["code_sha256"]:
        if os.environ.get(CODE_ENV):
            raise CanaryError("the code loaded is not the referee clone's")
        print(f"the referee at {referee['commit'][:12]} runs other code than this checkout: running on its bootstrap/",
              flush=True)
        env = {**os.environ, CODE_ENV: str(root / "bootstrap")}
        return subprocess.run([sys.executable, str(Path(__file__).resolve()), *argv, "--referee-clone", str(root)],
                              env=env, check=False).returncode
    boot = config.load_bootstrap(root)
    state = load_state(Path(args.result) if args.result else work.parent / "referee" / "result.json")
    mirror = work / "brain.git"
    gitio.fetch(mirror, args.brain_remote or f"https://github.com/{boot.brain_repo}.git", boot.brain_branch,
                state["last_accepted_sha"])
    _kinds, hosts, entries = load_catalog()
    mode = "live" if args.live else "dry"
    run_dir = work / "runs" / (datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + mode)

    def make_runner(tree: Path, deps: Path, vec: Path, locks: list[str]) -> Runner:
        return CanaryRunner(image=boot.image, src_dir=str(tree.resolve()), deps_dir=str(deps.resolve()),
                            vectors_dir=str(vec.resolve()), lockfiles=tuple(locks))

    batch = Batch(root=root, referee=referee, state=state, mirror=mirror, store=plant_store(work, mirror),
                  screens=work / "screens", run_dir=run_dir, hosts=hosts,
                  entries=select(entries, args.only, args.mode, args.plants, args.controls), make_runner=make_runner,
                  reviewer=live_reviewer(root, args.claude) if args.live else oracle_reviewer, mode=mode,
                  max_usd=args.max_usd, echo=lambda line: print(line, flush=True))
    results = run_batch(batch)
    if args.karne:
        karne = Path(args.karne) / "canary"
        karne.mkdir(parents=True, exist_ok=True)
        _write(karne / f"{run_dir.name}.json", aggregate(results))
    print(report(results))
    print("written:", run_dir)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (CanaryError, config.ConfigError, gitio.GitError) as exc:
        print(f"stop: {exc}", file=sys.stderr)
        sys.exit(2)
