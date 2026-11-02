"""Operator import at the Stage 0 exit and at each batch exit after it (`tohum/25a` 1-2, `asama-0/10a` #aktarim and
#oyuncak, `asama-1/13` 3: "aynı komut"). Run on the operator's machine, with the kill switch on.

It works on git objects alone, in a bare repository of its own in a fresh temporary directory, and never reads or writes
a working tree (E470: four rounds of a file system's names, cases, short names, links and junctions refuted every copy
into a checkout). In order: the referee repository is cloned bare, and its ``main`` is what the import builds on; the
kill switch is that commit's ``control.json`` (exactly true); the signed result is verified with Sigstore and must be
accepted and transferable; it is Stage 0's exit while that ``main`` holds no lock, or the open batch's once its
``setup/stage.json`` opened Stage 1; the pinned brain commit is fetched into the bare repository with git's own object
checks on (``fetch.fsckObjects``, E479). Then, before any object is written, every name of the new parts (``referee/``
and, at Stage 0's exit, ``tests/fixtures/toy-repo/``) is one the spec allows (`26c`) and one no file system reads as
another: no control character, backslash, colon, ``..`` or ``.git`` (case-folded); no name ending in a dot or a space,
no reserved device name, no ``~`` and a digit (an 8.3 short name's shape), none of ``|?*"<>``, no path longer than
260 characters (Windows holds none of them, on whatever system the import runs, E484) and no name longer than 255 bytes
(ext4's limit on one name; NTFS's is 255 UTF-16 units, never more bytes, E496); no ``.git``, ``.gitattributes``
or ``.gitmodules``, folded (any case, and without the code points HFS+ ignores, as git reads its own names), so nothing
of the brain changes what a checkout's bytes are or fetches from elsewhere (E478, E479), and in the toy no ``.github``
(`25a` 6: the toy holds no workflow, E480); no two names one name folded; and none that is, holds or leads to, folded,
what the import keeps. A link or a submodule there stops too. Each part's hash by `26c`'s rule, read from its blobs, is
the signed one.

The new referee tree is composed in a private index: the brain's ``referee/`` tree at the top, then what the import
keeps taken from ``main`` by exact name (the operator's files and directories, ``setup/`` with them, the bootstrap
referee's ``bootstrap/`` and ``.github/workflows/bootstrap.yml``: the push judge stays, E100), so
``referee/.github/workflows/loop.yml`` lands at ``.github/workflows/loop.yml`` and nothing else of ``main`` stays. The
composed tree is checked again: each kept entry's object is ``main``'s, and the rest hashes to the signed tree. Only
then does the counter get its row (`26c:39-40`), ``{ts, stage, batch?, brain_sha, referee_tree_sha256, result_sha256,
toy_tree_sha256?}`` in that order, chained (`26`), one line of compact JSON ended by LF, appended to ``main``'s
``setup/imports.jsonl`` (a plain file, mode 100644) in the same commit, the only entry that differs from the checked
tree. At Stage 0's exit the toy repository's ``main`` gets a commit whose tree is the signed toy tree (`25a` 2); a batch
transfer leaves the toy as it is (`asama-1/13`). Only ``main`` of the referee repository is cloned and only ``main``
of the toy's fetched (E494). Before anything is pushed, git's object check runs on exactly what each push sends: the
objects the new commit reaches and the main the import read does not (``receive.fsckObjects`` in a repository of the
import's own that holds that main, `_check_pushed`): what a remote that checks what it receives refuses stops here
(E479), while an object of another branch, or one main already holds, stops nothing (E494). So a toy is never pushed
beside a referee commit its remote refuses. The toy is pushed first, the referee
commit last, each with a lease on the ``main`` the import read (``--force-with-lease=refs/heads/main:<sha>``, a
fast-forward a ``main`` that moved or was rewound since refuses, E482); a refused push names that remote's ``main`` as
``ls-remote`` reads it then (a rerun leaves a toy that already holds the tree as it is). The operator then pulls
``main`` into a checkout, where git's own ``core.protectNTFS`` and the refusals above keep the names and bytes what
they were.

Spec sessiz, the narrowest choice each time (register E370, E378, E470, E478-E485): the kill switch is on only when
``kill_switch`` is exactly true; a result without ``exit.batch`` is Stage 0's exit (``stage`` 0), imported only before
the lock; one with it is a batch's, imported only while that batch is the lock's stage's open one
(`stagelock.open_table`), with ``stage`` and ``batch`` from the signed result and no toy; ``result_sha256`` is sha256
of the signed result file's bytes; ``ts`` is UTC to the second (`26c` vectors); the commit's author is the operator's git
identity; a ``main`` without ``bootstrap/``, ``.github/workflows/bootstrap.yml`` or ``control.json``, or with a case
variant of a kept name, stops; a repository given as a local path is read from the caller's working directory (E485),
a drive-relative one as the system resolves it, and an empty name stops (E498).
"""

from __future__ import annotations

import datetime
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
from pathlib import Path, PurePosixPath

from . import canon, gitio, stagelock
from .treehash import OPERATOR_NAMES, TreeError, is_utf8_name, path_problem, shown, tree_hash

OIDC_ISSUER = "https://token.actions.githubusercontent.com"
TOY_DIR = "tests/fixtures/toy-repo"
BRANCH = "main"
# What the import keeps of the referee repository's main, by exact name: the operator's files and directories and the
# bootstrap referee with its workflow (`25a` 1).
KEEP_TOP = OPERATOR_NAMES | {"bootstrap"}
BOOTSTRAP_WORKFLOW = ".github/workflows/bootstrap.yml"
KEPT_PATHS = tuple(sorted(KEEP_TOP)) + (BOOTSTRAP_WORKFLOW,)
KEEP_FOLDS = frozenset(name.casefold() for name in KEEP_TOP)
MUST_KEEP = ("bootstrap", BOOTSTRAP_WORKFLOW, "control.json")  # without them there is no push judge or kill switch
COUNTER = "setup/imports.jsonl"
STAGE = 0  # the stage exit this seed's bootstrap signs as transferable (`02` "Önyükleme hakemi bugün yalnız Aşama 0 ...")
MAX_PART_BYTES = 200_000_000
# Names a file system the repository is checked out on reads as another (E470): Windows' devices, in any case, with or
# without an extension; and the 8.3 short name's `~` and a digit. Windows holds none of `|?*"<>` in a name, nor a path
# longer than MAX_PATH (E484).
DEVICES = frozenset({"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"}
                    | {f"{port}{n}" for port in ("COM", "LPT") for n in "0123456789¹²³"})
SHORT_NAME = re.compile(r"~[0-9]")
WINDOWS_CHARS = frozenset('|?*"<>')
MAX_PATH = 260
# One name's limit where the repository is checked out (E496): NTFS holds 255 UTF-16 units, ext4 (the operator's WSL)
# 255 bytes. A name's UTF-8 bytes are never fewer than its UTF-16 units, so the byte count holds both: a longer name
# stops here, not in a checkout half way.
MAX_NAME = 255
# The code points HFS+ leaves out of a name when it compares two, as git's `is_hfs_dotgit` reads its own names (E479).
HFS_IGNORED = dict.fromkeys((0x200C, 0x200D, 0x200E, 0x200F, 0x202A, 0x202B, 0x202C, 0x202D, 0x202E, 0x206A, 0x206B,
                             0x206C, 0x206D, 0x206E, 0x206F, 0xFEFF))
# Names git reads from a tree for itself, never a new part's (E478, E479): NTFS's forms of them (`GIT~1`, `.git.`,
# `.git::$DATA`) are names the Windows rules above refuse already.
GIT_NAMES = {".git": "git's own directory",
             ".gitattributes": "git's attributes, which change a checkout's bytes (eol, working-tree-encoding)",
             ".gitmodules": "git's submodules, fetched from elsewhere"}
TOY_NAMES = dict(GIT_NAMES, **{".github": "GitHub's workflows: the toy holds none (`25a` 6, E480)"})
KEEP_ENV = ("GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "GIT_COMMITTER_NAME", "GIT_COMMITTER_EMAIL")
FETCH_CHECKED = ("-c", "fetch.fsckObjects=true")
DOS_DRIVE = re.compile(r"^[A-Za-z]:")


class ImportErrorStop(RuntimeError):
    """The import must not proceed; the message says why."""


def verify_signature(subject: Path | str, bundle: Path, identity: str, sigstore_python: str) -> None:
    """Sigstore verifies ``bundle`` for ``subject``: a file, or a digest ``sha256:<hex>`` (a root, `stagelock`)."""
    proc = subprocess.run([sigstore_python, "-m", "sigstore", "verify", "identity", "--bundle", str(bundle),
                           "--cert-identity", identity, "--cert-oidc-issuer", OIDC_ISSUER, str(subject)],
                          capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise ImportErrorStop(f"signature verification failed: {proc.stderr.strip()[:500]}")


def kept(rel: str | PurePosixPath) -> bool:
    """What the import keeps of the referee repository's main (a path in its tree), by exact name."""
    rel = PurePosixPath(rel).as_posix()
    return rel.split("/")[0] in KEEP_TOP or rel == BOOTSTRAP_WORKFLOW


def fold(name: str) -> str:
    """A name as some file system the repository is checked out on reads it: case-folded, and without the code points
    HFS+ ignores (E479)."""
    return name.translate(HFS_IGNORED).casefold()


def windows_problem(path: str) -> str | None:
    """Why a path is not itself on a Windows file system, where the operator checks the repository out; None if it is."""
    if len(path.encode("utf-16-le", "surrogatepass")) // 2 > MAX_PATH:
        return f"a path longer than Windows' {MAX_PATH} characters"
    for part in path.split("/"):
        if len(part.encode("utf-8", "surrogatepass")) > MAX_NAME:
            return f"a name longer than {MAX_NAME} bytes (ext4's limit; NTFS's {MAX_NAME} UTF-16 units are never more)"
        if WINDOWS_CHARS.intersection(part):
            return 'a character a Windows name cannot hold (|?*"<>)'
        if part.endswith((".", " ")):
            return "a name ending in a dot or a space"
        if part.split(".")[0].rstrip(" ").upper() in DEVICES:
            return "a reserved device name"
        if SHORT_NAME.search(part):
            return "an 8.3 short name's shape (~ and a digit)"
    return None


def refuse_names(label: str, paths: list[str], kept_paths: tuple[str, ...] = (), own: dict = GIT_NAMES) -> None:
    """Every name of a new part, before any object is written (E470): one the spec allows (`26c`), one no file system
    reads as another, none of the names git (or GitHub, ``own``) reads for itself, and none that is, holds or leads to,
    folded, a kept path; no two one name folded."""
    folds = {fold(k): k for k in kept_paths}
    seen: dict[str, str] = {}
    for k in kept_paths:
        parts = k.split("/")
        for n in range(1, len(parts) + 1):
            seen.setdefault(fold("/".join(parts[:n])), "/".join(parts[:n]))
    for path in paths:
        if not is_utf8_name(path):
            raise ImportErrorStop(f"{label}/{shown(path)}: a name that is not UTF-8 (`26c`): nothing was written")
        problem = path_problem(path) or windows_problem(path)
        if problem:
            raise ImportErrorStop(f"{label}/{path!r}: {problem} (`26c`, E470, E484): nothing was written")
        for part in path.split("/"):
            if fold(part) in own:
                raise ImportErrorStop(f"{label}/{path!r}: {part!r} is {own[fold(part)]}, in some case or form "
                                      "(E478-E480): nothing was written")
        folded = fold(path)
        for kept_fold, kept_path in folds.items():
            if folded == kept_fold or folded.startswith(kept_fold + "/") or kept_fold.startswith(folded + "/"):
                raise ImportErrorStop(f"{label}/{path} is, holds or leads to {kept_path}, what the import keeps, in some "
                                      "case (`25a` 1, E130, E470): nothing was written")
        parts = path.split("/")
        for n in range(1, len(parts) + 1):
            name = "/".join(parts[:n])
            other = seen.setdefault(fold(name), name)
            if other != name:
                raise ImportErrorStop(f"{label}/{name} and {other} are one name case-folded (E130, E470): nothing was "
                                      "written")


def _git(cwd: Path, *args: str, stdin: bytes | None = None, index: Path | None = None, config: tuple[str, ...] = ()
         ) -> bytes:
    """Git as the operator runs it, with their own configuration (identity, credentials) but never a hook or a file
    system monitor, nor a ``GIT_*`` variable of the caller's but their identity; ``config`` goes before the command;
    ``cwd`` is the import's own bare repository or its temporary directory, never a checkout."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_") or k in KEEP_ENV}
    env["GIT_TERMINAL_PROMPT"] = "0"
    if index is not None:
        env["GIT_INDEX_FILE"] = str(index)
    proc = subprocess.run(["git", *gitio.SAFE_CONFIG, *config, *args], cwd=cwd, input=stdin, capture_output=True,
                          env=env, check=False)
    if proc.returncode != 0:
        raise ImportErrorStop(f"git {args[0]} failed: {proc.stderr.decode('utf-8', 'replace').strip()[:400]}")
    return proc.stdout


def located(repo: str) -> str:
    """A repository the operator names: a URL as it is, a local path made absolute from the caller's working directory
    (git runs in the import's temporary directory, E485). A URL is git's: ``scheme://``, or ``host:path`` with no slash
    before the colon (a Windows drive letter is a path there). A Windows drive-relative ``C:rel`` is made absolute as the
    system reads it (``os.path.abspath``: that drive's own directory), not kept relative for git to read from the
    temporary directory (E498). An empty name names nothing: it stops, it is no default."""
    if not repo:
        raise ImportErrorStop("an empty repository name (--brain, --referee or --toy \"\"): give the repository or "
                              "leave the option out (E498)")
    colon, slash = repo.find(":"), repo.find("/")
    drive = os.name == "nt" and DOS_DRIVE.match(repo)
    if "://" in repo or (colon >= 0 and (slash < 0 or colon < slash) and not drive):
        return repo
    if os.path.splitdrive(repo)[0] and not os.path.isabs(repo):  # Windows' `C:rel`: that drive's own directory
        return os.path.abspath(repo)
    return os.path.normpath(os.path.join(os.getcwd(), repo))  # `./a:b` stays a name (abspath's normpath makes `a:` a drive)


def _rev(bare: Path, rev: str) -> str | None:
    try:
        return gitio.git(bare, "rev-parse", "--verify", "--quiet", rev).decode().strip() or None
    except gitio.GitError:
        return None


def _subtree(bare: Path, commit: str, path: str) -> str | None:
    """The tree at ``path`` in ``commit``, or None when there is none (or something else is there)."""
    found = _rev(bare, f"{commit}:{path}")
    if found is None or gitio.git(bare, "cat-file", "-t", found).strip() != b"tree":
        return None
    return found


def kill_switch_on(bare: Path, main: str) -> None:
    """`25a` 1: the import runs only with the kill switch on, read from the main it builds on."""
    try:
        data = json.loads((gitio.file_at(bare, main, "control.json") or b"").decode("utf-8"))
    except (UnicodeDecodeError, ValueError, RecursionError) as exc:
        raise ImportErrorStop(f"the kill switch is not on: main's control.json cannot be read ({type(exc).__name__})"
                              ) from exc
    if not isinstance(data, dict) or data.get("kill_switch") is not True:
        raise ImportErrorStop("the kill switch is not on: main's control.json kill_switch must be true while importing "
                              "(`25a` 1)")


def _entries(bare: Path, treeish: str) -> list[tuple[str, str, str]]:
    """(mode, sha, path) of every leaf under ``treeish``, as git stores the path."""
    return gitio._entries(bare, treeish)


def part_hash(bare: Path, treeish: str, label: str, skip=lambda path: False, **rule) -> str:
    """`26c`'s hash of the regular files under ``treeish`` but what ``skip`` leaves out, read from their blobs; a link or
    a submodule there, or more than ``MAX_PART_BYTES``, stops."""
    entries = [(m, s, p) for m, s, p in _entries(bare, treeish) if not skip(p)]
    special = [p for m, _s, p in entries if m not in ("100644", "100755")]
    if special:
        raise ImportErrorStop(f"{label}/{shown(special[0])} is a link or a submodule (`26c`): nothing was written")
    sizes = gitio.git(bare, "cat-file", "--batch-check=%(objectsize)", stdin="".join(f"{s}\n" for _m, s, _p in entries)
                      .encode()).split()
    if sum(int(n) for n in sizes) > MAX_PART_BYTES:
        raise ImportErrorStop(f"{label}/ is larger than {MAX_PART_BYTES} bytes: nothing was written")
    try:
        return tree_hash(gitio.archive(bare, treeish, skip=skip, under=label + "/"), label, **rule)
    except TreeError as exc:
        raise ImportErrorStop(f"{label}/: {exc} (`26c`): nothing was written") from exc


def committed_referee_hash(repo: Path, rev: str = "HEAD") -> str:
    """The hash `26c` gives the referee tree a commit of the referee repository holds, what it keeps left out: the
    tree the last transfer wrote, as `stage-open` reads it from git (E471)."""
    return part_hash(repo, rev, "referee", skip=kept)


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _transfer_of(exit_block: dict, snapshot: Path, toy_repo: str | None) -> tuple[int, str | None]:
    """The stage and batch this signed result transfers: Stage 0's exit before the lock, the open batch after it. The
    lock and the counter are main's, read from ``snapshot`` (their two blobs, nothing else)."""
    if "batch" not in exit_block:
        if (snapshot / stagelock.SETUP / stagelock.LOCK_FILE).exists():
            raise ImportErrorStop("setup/stage.json is there: the lock this Stage 0 result opened is not imported again")
        return STAGE, None
    lock = stagelock.load(snapshot)  # the lock and the counter it names; a broken one stops here
    if lock is None:
        raise ImportErrorStop("a batch's result is imported only once setup/stage.json opened its stage (`asama-1/13`)")
    stage, batch = exit_block.get("stage"), exit_block["batch"]
    if type(stage) is not int or stage != lock.stage:
        raise ImportErrorStop(f"the signed batch result is Stage {stage!r}'s, the lock opened Stage {lock.stage}")
    open_batch = stagelock.open_table(snapshot).batch
    if batch != open_batch:
        raise ImportErrorStop(f"the signed result is batch {batch!r}'s; the open batch is {open_batch!r} (`asama-1/13`: "
                              "each batch's transfer once, in order)")
    if toy_repo is not None:
        raise ImportErrorStop("a batch transfer leaves the toy as it is (`asama-1/13`; `25a` 2 is Stage 0's exit): "
                              "run it without --toy")
    return stage, batch


def _kept_from(bare: Path, main: str) -> list[tuple[str, str, str]]:
    """Main's entries the import keeps, by exact name; a case variant of a kept name, or a main without the push judge or
    the kill switch, stops."""
    leaves = _entries(bare, main)
    for _m, _s, path in leaves:
        top = path.split("/")[0]
        if (top.casefold() in KEEP_FOLDS and top not in KEEP_TOP) or (top.casefold() == ".github" and top != ".github") \
                or (path.casefold() == BOOTSTRAP_WORKFLOW and path != BOOTSTRAP_WORKFLOW):
            raise ImportErrorStop(f"main holds {shown(path)}, under a case variant of what the import keeps (`25a` 1, "
                                  "E470): nothing was written")
    entries = [(m, s, p) for m, s, p in leaves if kept(p)]
    for must in MUST_KEEP:
        if not any(p == must or p.startswith(must + "/") for _m, _s, p in entries):
            raise ImportErrorStop(f"main has no {must}: the import keeps it and builds on nothing without it (`25a` 1)")
    return entries


def _remove(path: Path) -> None:
    def writable(func, target, _exc):  # git's objects are read-only on Windows
        os.chmod(target, stat.S_IWRITE)
        func(target)
    shutil.rmtree(path, onerror=writable)


def _compose(bare: Path, work: Path, referee_tree: str, kept_entries: list[tuple[str, str, str]]) -> tuple[Path, str]:
    """The new tree in a private index: the referee tree at the top, then main's kept entries by exact name."""
    index = work / "index"
    _git(bare, "read-tree", referee_tree, index=index)
    lines = b"".join(f"{mode} {'commit' if mode == '160000' else 'blob'} {sha}\t".encode() +
                     path.encode("utf-8", "surrogateescape") + b"\0" for mode, sha, path in kept_entries)
    _git(bare, "update-index", "-z", "--index-info", stdin=lines, index=index)
    return index, _git(bare, "write-tree", index=index).decode().strip()


def _check_composed(bare: Path, tree: str, main: str, expected: str) -> None:
    """E470: each kept entry's object in the composed tree is main's; the rest hashes to the signed referee tree."""
    tops = {p.split("/")[0] for _m, _s, p in _entries(bare, main)} & KEEP_TOP
    for name in sorted(tops) + [BOOTSTRAP_WORKFLOW]:
        if _rev(bare, f"{tree}:{name}") != _rev(bare, f"{main}:{name}"):
            raise ImportErrorStop(f"the composed tree's {name} is not main's (`25a` 1): nothing was written")
    if part_hash(bare, tree, "referee", skip=kept) != expected:
        raise ImportErrorStop("the composed tree, what the import keeps left out, is not the signed referee tree "
                              "(`25a` 1): nothing was written")


def _check_pushed(bare: Path, work: Path, name: str, commit: str, held: str | None) -> None:
    """E479, E494: git's object check of exactly what the push to ``name`` would send, before the first push: the
    objects reachable from ``commit`` that the main the import read (``held``, None for an empty repository) does not
    reach. A fresh bare repository of the import's own holds that main, copied unchecked (its remote holds it already),
    and receives ``commit`` with ``receive.fsckObjects`` in its own configuration, as a remote that checks what it
    receives does (a ``-c`` on the push does not reach a local receive-pack); no hook runs there. An object of another
    branch, or one main already holds, is never what this push sends, so it stops nothing (E479 checked the whole
    repository: a bad object on any branch stopped every import for good)."""
    check = work / f"check-{name}.git"
    _git(work, "init", "--bare", "--quiet", "--template=", str(check))
    for key, value in (("core.hooksPath", "/dev/null"), ("receive.fsckObjects", "false")):
        _git(check, "config", key, value)
    if held is not None:
        _git(bare, "push", "--quiet", str(check), f"{held}:refs/heads/held")
    _git(check, "config", "receive.fsckObjects", "true")
    try:
        _git(bare, "push", "--quiet", str(check), f"{commit}:refs/heads/new")
    except ImportErrorStop as exc:
        raise ImportErrorStop(f"{exc}: git's object check refuses an object the push to the {name}'s main would send, "
                              f"one its main does not hold (E479, E494): nothing was pushed") from exc


def _has_main(cwd: Path, repo: str) -> bool:
    """Whether the remote has a branch named exactly main (`ls-remote` matches a pattern against a name's end, so a
    ``x/refs/heads/main`` answers too: the name is compared whole)."""
    listed = _git(cwd, "ls-remote", "--heads", repo, f"refs/heads/{BRANCH}").splitlines()
    return any(line.split(b"\t")[-1] == f"refs/heads/{BRANCH}".encode() for line in listed)


def _fetch_main(bare: Path, repo: str, ref: str) -> str | None:
    """The remote's main alone into ``ref`` (E494: no other branch of it is read); None for a repository without one
    (the toy is empty until the first import, `25` 10). A main that appears after `ls-remote` meets the push's lease."""
    if not _has_main(bare, repo):
        return None
    _git(bare, "fetch", "--quiet", "--no-tags", repo, f"+refs/heads/{BRANCH}:{ref}")
    return _rev(bare, f"{ref}^{{commit}}")


def _remote_main(bare: Path, repo: str) -> str:
    """The remote's main as `ls-remote` reads it now (E482), for a refused push's message."""
    try:
        found = _git(bare, "ls-remote", "--heads", repo, f"refs/heads/{BRANCH}").split()
    except ImportErrorStop as exc:
        return f"unknown ({exc})"
    return found[0].decode() if found else "absent"


def _push(bare: Path, repo: str, commit: str, read: str | None) -> None:
    """``commit`` to the remote's main with a lease on the main the import read (``read``; None: there was none): a
    fast-forward that a main moved or rewound since refuses, never a force (E482)."""
    _git(bare, "push", "--quiet", f"--force-with-lease=refs/heads/{BRANCH}:{read or ''}", repo,
         f"{commit}:refs/heads/{BRANCH}")


def run_import(result_path: Path, bundle_path: Path, identity: str, sigstore_python: str, brain_repo: str,
               referee_repo: str, toy_repo: str | None) -> dict:
    brain_repo, referee_repo = located(brain_repo), located(referee_repo)
    toy_repo = located(toy_repo) if toy_repo is not None else None
    work = Path(tempfile.mkdtemp(prefix="snowball-import-"))
    try:
        return _run(result_path, bundle_path, identity, sigstore_python, brain_repo, referee_repo, toy_repo, work)
    finally:
        _remove(work)


def _run(result_path: Path, bundle_path: Path, identity: str, sigstore_python: str, brain_repo: str,
         referee_repo: str, toy_repo: str | None, work: Path) -> dict:
    bare = work / "work.git"
    try:  # main alone (E494): another branch's objects are no push's, and none of them can stop an import
        _git(work, "clone", "--bare", "--quiet", "--no-tags", "--single-branch", "--branch", BRANCH, referee_repo,
             str(bare))
    except ImportErrorStop as exc:
        if not _has_main(work, referee_repo):
            raise ImportErrorStop(f"the referee repository has no {BRANCH} to build on") from exc
        raise
    main = _rev(bare, f"refs/heads/{BRANCH}^{{commit}}")
    if main is None:
        raise ImportErrorStop(f"the referee repository has no {BRANCH} to build on")
    kill_switch_on(bare, main)
    verify_signature(result_path, bundle_path, identity, sigstore_python)
    result_bytes = result_path.read_bytes()
    result = json.loads(result_bytes.decode("utf-8"))
    exit_block = result.get("exit") or {}
    if result.get("verdict") != "accepted" or exit_block.get("transferable") is not True:
        raise ImportErrorStop("the signed result does not mark this commit transferable")
    snapshot = work / "main"  # main's lock and counter, the two blobs stagelock reads
    for name in (stagelock.LOCK_FILE, stagelock.COUNTER_FILE):
        data = gitio.file_at(bare, main, f"{stagelock.SETUP}/{name}")
        if data is not None:
            (snapshot / stagelock.SETUP).mkdir(parents=True, exist_ok=True)
            (snapshot / stagelock.SETUP / name).write_bytes(data)
    stage, batch = _transfer_of(exit_block, snapshot, toy_repo)
    sha = exit_block["brain_sha"]
    expected = exit_block["referee_tree_sha256"]
    toy_expected = exit_block.get("toy_tree_sha256") if batch is None else None
    if toy_expected is not None and toy_repo is None:
        raise ImportErrorStop("the signed result carries the toy's tree: give --toy, its repository (`25a` 2)")
    counter = stagelock.read_counter(snapshot)  # a broken chain stops here, before anything is written
    prev = counter[-1][1]["row_hash"] if counter else stagelock.ZERO

    _git(bare, "fetch", "--quiet", "--no-tags", brain_repo, sha, config=FETCH_CHECKED)
    if _rev(bare, f"{sha}^{{commit}}") != sha:
        raise ImportErrorStop(f"brain commit {sha} is not in {brain_repo}")
    referee_tree = _subtree(bare, sha, "referee")
    if referee_tree is None:
        raise ImportErrorStop(f"brain commit {sha} has no referee/ tree")
    refuse_names("referee", [p for _m, _s, p in _entries(bare, referee_tree)], KEPT_PATHS)
    actual = part_hash(bare, referee_tree, "referee")
    if actual != expected:
        raise ImportErrorStop(f"referee tree hash {actual} differs from the signed {expected}")
    toy_tree = None
    if toy_expected is not None:
        toy_tree = _subtree(bare, sha, TOY_DIR)
        if toy_tree is None:
            raise ImportErrorStop(f"brain commit {sha} has no {TOY_DIR}/ tree (`25a` 2)")
        refuse_names(TOY_DIR, [p for _m, _s, p in _entries(bare, toy_tree)], own=TOY_NAMES)
        toy_actual = part_hash(bare, toy_tree, TOY_DIR, forbid_operator_names=False, fold_case=True)
        if toy_actual != toy_expected:
            raise ImportErrorStop(f"toy tree hash {toy_actual} differs from the signed {toy_expected} (`25a` 2)")

    kept_entries = _kept_from(bare, main)
    counter_entry = [(m, s) for m, s, p in kept_entries if p == COUNTER]
    if counter_entry and counter_entry[0][0] != "100644":
        raise ImportErrorStop(f"main's {COUNTER} is not a plain file (mode 100644): nothing was written")
    index, composed = _compose(bare, work, referee_tree, kept_entries)
    _check_composed(bare, composed, main, expected)

    row: dict = {"ts": _now(), "stage": stage}
    if batch is not None:
        row["batch"] = batch
    row.update(brain_sha=sha, referee_tree_sha256=actual, result_sha256=hashlib.sha256(result_bytes).hexdigest())
    if toy_expected is not None:
        row["toy_tree_sha256"] = toy_expected
    row["prev_hash"] = prev
    row["row_hash"] = canon.row_hash(row)
    line = json.dumps(row, separators=(",", ":")).encode("utf-8") + b"\n"  # bytes: LF on every platform
    old = gitio.file_at(bare, main, COUNTER) or b""
    blob = _git(bare, "hash-object", "-w", "--stdin", stdin=old + line).decode().strip()
    _git(bare, "update-index", "--add", "--cacheinfo", f"100644,{blob},{COUNTER}", index=index)
    tree = _git(bare, "write-tree", index=index).decode().strip()
    changed = gitio.git(bare, "diff-tree", "-r", "-z", "--name-only", composed, tree).split(b"\0")
    if [c for c in changed if c] != [COUNTER.encode()]:
        raise ImportErrorStop("the commit would change more than the counter after the checked tree: nothing was pushed")
    what = f"Aşama {stage}" + (f", parti {batch}" if batch else "")
    message = (f"Aktarım: {what}, beyin {sha} (`25a` 1, `26c`)\n\nsetup/imports.jsonl row_hash {row['row_hash']}\n")
    commit = _git(bare, "commit-tree", tree, "-p", main, stdin=message.encode("utf-8")).decode().strip()

    toy_commit = toy_main = None
    if toy_tree is not None:
        toy_main = _fetch_main(bare, toy_repo, f"refs/toy/{BRANCH}")
        if toy_main is None or _rev(bare, f"{toy_main}^{{tree}}") != toy_tree:
            parents = ["-p", toy_main] if toy_main else []
            toy_commit = _git(bare, "commit-tree", toy_tree, *parents,
                              stdin=f"Oyuncak: imzalı oyuncak ağacı, beyin {sha} (`25a` 2)\n".encode("utf-8")
                              ).decode().strip()
    _check_pushed(bare, work, "referee", commit, main)  # both before either push: no toy beside a refused referee
    if toy_commit:
        _check_pushed(bare, work, "toy", toy_commit, toy_main)
    if toy_commit:
        try:
            _push(bare, toy_repo, toy_commit, toy_main)
        except ImportErrorStop as exc:
            raise ImportErrorStop(f"{exc}; the toy's main is now {_remote_main(bare, toy_repo)}; the referee was not "
                                  "pushed") from exc
    try:
        _push(bare, referee_repo, commit, main)
    except ImportErrorStop as exc:
        raise ImportErrorStop(f"{exc}; the referee's main is now {_remote_main(bare, referee_repo)} (the import read "
                              f"{main})" + (f"; the toy's main is {toy_commit} (a rerun leaves it as it is)"
                                            if toy_commit else "")) from exc
    print(f"referee: main is {commit}; toy: {toy_commit or 'as it was'}. Pull main into your checkout "
          "(git pull --ff-only).")
    return row
