"""The operator's `drill-fixtures` command: the live revert-drill fixtures of one import (`tohum/26f` "Canlı prova
fikstürleri", `25a` 7, `asama-0/01` D8; E499, E544).

Run on the operator's machine after the import and before the activation (`25a` 7). It reads, from git objects alone
and never a working tree: the referee checkout's committed ``setup/imports.jsonl``, whose last transfer line binds the
set (``import_line_sha256``, the sha256 of the line without its LF, `26d`) and names the toy tree
(``toy_tree_sha256``) and the brain commit (``brain_sha``); the toy clone's ``main`` tree, which must hash to
``toy_tree_sha256`` by `26c`'s rule (`importer.part_hash`, the import's own); the brain at ``brain_sha``, whose toy
fixture must hash to it too and whose ``candidates/<toy id>/`` say which files a merge-expected candidate changes; the
checkout's ``policy.json`` (``constitutional.security_keywords``) and ``setup/summary.json`` (the toy target).
The operator's catalog is a private file outside any repository: a JSON list of ``{cause, patch}`` drafts.

It writes one line of base64 (no LF) of the RFC 8785 JSON ``{import_line_sha256, instances: [{id, cause, patch}]}``,
the instances in the order of their ids, only to the path the operator gives, which must not exist yet; each ``id`` is
32 fresh random lowercase hex characters (`secrets`). It prints the cause counts, the value's sha256 and its size, and
never a patch, an id or a patched path. The operator writes the value as the referee secret `loop.yml` names.

Refused, each before anything is written: a binding that does not hold (the checkout's commit does not hold the referee
tree the last transfer line names, that line names no toy tree, the toy or the brain's fixture is another tree); a toy
tree holding an ownership file (``CODEOWNERS``: `14` makes the paths it gives the security team security paths, and
the seed does not read which); a cause outside `29j`'s three (``build_break``, ``lint_regression``,
``test_regression``); causes of unequal counts or one missing (`26f`: equal, at least one); a patch that is not exactly
one in-place modification of one existing regular file in `26c`'s ``diff.patch`` form (git's header, no add, delete,
rename, copy, mode change or binary, no CR, no NUL), or whose ``index`` line does not name the file's blobs and mode, or
that changes nothing; two entries that plant the same bytes in the same file (a plant once made is in the toy's public
history); a file on a security path; a patch that does not apply at its exact lines (`apply`: no fuzz, no offset, hunks
in order, context byte for byte); a file a merge-expected candidate changes (per file, `26f`); a value over 48 KB
(GitHub's secret limit, E544); a measured cause that is not the declared one, or that the measurement cannot name.

The causes are measured with the toy's own tools in a sandbox, never with referee code, and no container has a
network: the seed fetches each of the lockfile's tarballs from the npm registry itself (no redirect followed, HTTP 200,
at most ``MAX_DEPS_BYTES`` together) and holds it to the lockfile's sha512 integrity before any byte reaches docker;
`DockerSandbox` installs them in a pinned Node image whose ``node --version`` must be the project's ``.nvmrc``
(``npm ci --offline --ignore-scripts`` from npm's cache of those bytes). Each tree is then measured in fresh containers
of its bytes: one parses every JavaScript file (``node --check``), imports every module that is not a test file and
runs the toy's ``lint`` script for its ESLint total; each of four more runs the toy's ``test`` script once (MF12's
first run and three reruns, each in a fresh container, `29j` ``flaky``), its tests read one by one through a reporter
of the seed's. MF12's rule is applied test by test: green when no run has a red test; red when a test fails in all four
runs; else flaky or unfinished, and no cause, since the sentinel would not revert it. The clean tree is measured once as
the base, and must load with its tests green; a plant whose patch changes what the measurement installs from or runs on
(``package.json``, ``package-lock.json``, ``.nvmrc``) is refused, so a plant and the base are measured with the same
tools. `29j`'s rule order names the cause: ``build_break`` when the code no longer loads (its red tests and lint are
its result); else ``lint_regression`` when the total rose and every test is green; ``test_regression`` when a test is
red, one of them a test of the plant's unit (Stage 0's impact set, else MF13 says ``impact_miss``), and the total did
not rise. Both, or neither, is no single cause and is refused; so is a plant whose ESLint errors and warnings move
apart, as a total of one of them would name another cause, and one after which a test file no longer parses or fails
as a whole (a throw before any test, an import that fails), as the seed does not name ``build_ok``'s producer (`29j`)
and either cause could be read. Without docker the command stops: the measurement is never skipped.

Spec sessiz, the narrowest choice each time (E499): the security paths are the seed's mechanical rule (`14`, `29k`
``security_keyword_substring``: a file whose lower-case path holds a lower-case keyword of ``policy.json``'s
``security_keywords``, each keyword without its padding) and the owner's ``safety_paths`` of the toy target (`05`
"Fiziksel güvenlik", `29f`'s cover rule, case-blind), with no exclusion applied (a superset of the profile's, so a
refusal is never too lenient); the physical safety paths the system derives from the target (`05`, `14`) are not the
seed's to compute (E544 (5)); the ``test`` script must be exactly ``node --test``, whose default file patterns (Node
22) say which files are tests; the plant's unit is every one of the toy's ``unit_candidates`` that covers its file, and
a red test is the unit's when each of them covers the test's file; a tree whose lockfile names a package outside the
npm registry, or one without its single sha512 integrity, or no single ``package-lock.json`` with its ``package.json``
and ``.nvmrc``, is refused; the value carries no LF.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import io
import json
import os
import re
import secrets
import subprocess
import tarfile
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Protocol

from . import canon, config, gitio, importer, stagelock
from .config import ConfigError
from .ghapi import _NoRedirect
from .treehash import iter_files, path_problem

CAUSES = ("build_break", "lint_regression", "test_regression")  # `29j`'s rule order, `26f`'s closed set
ID_RE = re.compile(r"^[0-9a-f]{32}\Z")
MAX_VALUE_BYTES = 48 * 1024  # GitHub's limit on one secret (E544 (4))
MAX_DEPS_BYTES = 128 * 1024 * 1024  # the lockfile's tarballs together, as the seed fetches them
REGISTRY = "https://registry.npmjs.org/"
SRI_RE = re.compile(r"^sha512-[A-Za-z0-9+/]{86}==\Z")  # one sha512 Subresource Integrity, as npm writes it
OWNERSHIP_FILE = "codeowners"  # `14`: the paths an ownership file gives the security team are security paths
TEST_SCRIPT = "node --test"
TEST_RUNS = 4  # MF12 (`29j` `flaky`): the first run and three reruns; a test is red when it fails in all four
JS_SUFFIXES = (".js", ".mjs", ".cjs")
NVMRC_RE = re.compile(r"^v?([0-9]+\.[0-9]+\.[0-9]+)\n?\Z")
HUNK_RE = re.compile(r"^@@ -([0-9]+)(?:,([0-9]+))? \+([0-9]+)(?:,([0-9]+))? @@(?: .*)?\Z")
INDEX_RE = re.compile(r"^index ([0-9a-f]{7,40})\.\.([0-9a-f]{7,40}) (100644|100755)\Z")
NO_NEWLINE = "\\ No newline at end of file"
# What a git header says about a change that is not an in-place modification (`26f`: one existing file, in place).
NOT_IN_PLACE = (("new file mode", "adds a file"), ("deleted file mode", "deletes a file"),
                ("old mode", "changes a mode"), ("new mode", "changes a mode"), ("rename from", "renames a file"),
                ("rename to", "renames a file"), ("copy from", "copies a file"), ("copy to", "copies a file"),
                ("similarity index", "renames or copies a file"), ("dissimilarity index", "rewrites a file"),
                ("Binary files", "is binary"), ("GIT binary patch", "is binary"))


class FixtureStop(ConfigError):
    """The fixtures cannot be produced; nothing was written. The message names no patch content and no id."""


# ---------------------------------------------------------------- the strict unified diff

@dataclass(frozen=True)
class Hunk:
    old_start: int
    old_count: int
    new_start: int
    new_count: int
    lines: tuple[tuple[str, str, bool], ...]  # (kind ' ' '-' '+', text, ends with a newline)


@dataclass(frozen=True)
class Section:
    """One file's part of a unified diff: its header lines (before ``---``), the two paths and the hunks."""
    header: tuple[str, ...]
    old_path: str | None
    new_path: str | None
    hunks: tuple[Hunk, ...]


def _side(line: str, mark: str, prefix: str) -> str | None:
    """The path of a ``---``/``+++`` line as git writes it (``a/x``, ``b/x``, ``/dev/null``); None for ``/dev/null``."""
    rest = line[len(mark):]
    if rest == "/dev/null":
        return None
    if not rest.startswith(prefix):
        raise ValueError(f"a {mark.strip()} line without {prefix}")
    return rest[len(prefix):]


def sections(text: str) -> list[Section]:
    """The file sections of a git unified diff, hunk counts read exactly, so a removed line that begins ``--`` is never
    taken for a header. ValueError on a diff this parser cannot read."""
    if "\r" in text:
        raise ValueError("a carriage return")
    if "\0" in text:
        raise ValueError("a NUL")
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        raise ValueError("a lone surrogate: not UTF-8 text") from None
    if not text.endswith("\n"):
        raise ValueError("the last line has no newline")
    lines = text[:-1].split("\n")
    found: list[Section] = []
    i = 0
    while i < len(lines):
        if not lines[i].startswith("diff --git "):
            raise ValueError(f"line {i + 1} begins no file section")
        header = [lines[i]]
        i += 1
        while i < len(lines) and not lines[i].startswith(("--- ", "diff --git ")):
            header.append(lines[i])
            i += 1
        if i >= len(lines) or lines[i].startswith("diff --git "):
            found.append(Section(tuple(header), None, None, ()))  # a header-only section: mode, rename, binary
            continue
        if i + 1 >= len(lines) or not lines[i + 1].startswith("+++ "):
            raise ValueError(f"line {i + 2} is not the +++ line")
        old, new = _side(lines[i], "--- ", "a/"), _side(lines[i + 1], "+++ ", "b/")
        i += 2
        hunks = []
        while i < len(lines) and lines[i].startswith("@@"):
            match = HUNK_RE.match(lines[i])
            if not match:
                raise ValueError(f"line {i + 1} is not a hunk header")
            a, b, c, d = (int(g) if g is not None else 1 for g in match.groups())
            i += 1
            body: list[tuple[str, str, bool]] = []
            olds = news = 0
            while olds < b or news < d or (i < len(lines) and lines[i] == NO_NEWLINE):
                if i >= len(lines):
                    raise ValueError("a hunk ends before its counts")
                line = lines[i]
                if line == NO_NEWLINE:
                    if not body or not body[-1][2]:
                        raise ValueError(f"line {i + 1}: a no-newline marker after no line")
                    body[-1] = (body[-1][0], body[-1][1], False)
                elif line[:1] in (" ", "-", "+"):
                    body.append((line[0], line[1:], True))
                    olds += line[0] != "+"
                    news += line[0] != "-"
                    if olds > b or news > d:
                        raise ValueError(f"line {i + 1}: more lines than the hunk header counts")
                else:
                    raise ValueError(f"line {i + 1} is no hunk line")
                i += 1
            hunks.append(Hunk(a, b, c, d, tuple(body)))
        if not hunks:
            raise ValueError("a file section without a hunk")
        found.append(Section(tuple(header), old, new, tuple(hunks)))
    if not found:
        raise ValueError("no file section")
    return found


def _git_path(header: str) -> str | None:
    """The one path of ``diff --git a/<p> b/<p>``; None when the two differ, are quoted or cannot be split."""
    rest = header[len("diff --git "):]
    size, odd = divmod(len(rest) - len("a/ b/"), 2)
    path = rest[2:2 + size]
    return path if not odd and size > 0 and not rest.startswith('"') and rest == f"a/{path} b/{path}" else None


def changed_files(text: str) -> set[str]:
    """Every path a (multi-file) unified diff changes: both sides of each section, a rename's two names, the paths of a
    header-only section. ValueError when one cannot be read."""
    out: set[str] = set()
    for section in sections(text):
        renamed = [h.split(" ", 2)[2] for h in section.header if h.startswith(("rename from ", "rename to ",
                                                                                 "copy from ", "copy to "))]
        sides = [p for p in (section.old_path, section.new_path) if p is not None]
        if not sides and not renamed:
            path = _git_path(section.header[0])
            if path is None:
                raise ValueError("a section whose path cannot be read")
            sides = [path]
        out.update(sides + renamed)
    return out


@dataclass(frozen=True)
class Edit:
    """A plant's patch, checked to be one in-place modification of one file."""
    path: str
    old_blob: str
    new_blob: str
    mode: str
    hunks: tuple[Hunk, ...]


def in_place_edit(text: str) -> Edit:
    """`26f`'s patch, read strictly: `26c`'s ``diff.patch`` form (git's header lines, exactly ``diff --git``,
    ``index <old>..<new> <mode>``, ``--- a/<p>``, ``+++ b/<p>``) for one file changed in place. ValueError says why."""
    found = sections(text)
    if len(found) != 1:
        raise ValueError(f"changes {len(found)} files, not one")
    section = found[0]
    for line in section.header[1:]:
        for start, what in NOT_IN_PLACE:
            if line.startswith(start):
                raise ValueError(f"{what}, not one in-place modification")
    path = _git_path(section.header[0])
    if path is None:
        raise ValueError("its diff --git line does not name one unquoted path twice")
    if len(section.header) != 2 or not INDEX_RE.match(section.header[1]):
        raise ValueError("its header is not exactly diff --git and one index line with the file's mode")
    if not section.hunks or section.old_path != path or section.new_path != path:
        raise ValueError("its --- and +++ lines do not name the diff --git path on both sides")
    old_blob, new_blob, mode = INDEX_RE.match(section.header[1]).groups()
    if any(not any(kind != " " for kind, _t, _n in hunk.lines) for hunk in section.hunks):
        raise ValueError("a hunk changes nothing")
    return Edit(path, old_blob, new_blob, mode, section.hunks)


def _lines(data: bytes) -> list[tuple[bytes, bool]]:
    parts = data.split(b"\n")
    out = [(part, True) for part in parts[:-1]]
    if parts[-1]:
        out.append((parts[-1], False))
    return out


def apply(data: bytes, hunks: tuple[Hunk, ...]) -> bytes:
    """The seed's strict applier: each hunk at exactly its header's lines, its context and removed lines equal to the
    file's byte for byte (a line's newline too), no fuzz, no offset, hunks in order and apart, and its new start the old
    one moved by the hunks before it. ValueError naming the first hunk that does not apply."""
    lines = _lines(data)
    out: list[tuple[bytes, bool]] = []
    pos = delta = 0
    for number, hunk in enumerate(hunks, start=1):
        old_at = hunk.old_start - 1 if hunk.old_count else hunk.old_start
        new_at = hunk.new_start - 1 if hunk.new_count else hunk.new_start
        if old_at < pos or old_at + hunk.old_count > len(lines):
            raise ValueError(f"hunk {number} lies outside the file or before the hunk ahead of it")
        if new_at != old_at + delta:
            raise ValueError(f"hunk {number}'s new start is not its old start moved by the hunks before it")
        old = [(t.encode("utf-8"), nl) for kind, t, nl in hunk.lines if kind != "+"]
        if lines[old_at:old_at + hunk.old_count] != old:
            raise ValueError(f"hunk {number} does not apply at its lines")
        out.extend(lines[pos:old_at])
        out.extend((t.encode("utf-8"), nl) for kind, t, nl in hunk.lines if kind != "-")
        pos = old_at + hunk.old_count
        delta += hunk.new_count - hunk.old_count
    out.extend(lines[pos:])
    if any(not nl for _t, nl in out[:-1]):
        raise ValueError("a line without a newline is not the last line")
    return b"".join(t + (b"\n" if nl else b"") for t, nl in out)


def blob_id(data: bytes) -> str:
    """Git's object name of a blob of ``data``."""
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()  # noqa: S324 (git's name, not a security hash)


# ---------------------------------------------------------------- the measurement

@dataclass(frozen=True)
class Plan:
    """What the sandbox runs on a tree: the Node project's directory ("" at the top), the files ``node --check`` reads
    and the modules it imports, the Node version ``.nvmrc`` names, the bytes the dependencies come from."""
    project: str
    parse: tuple[str, ...]
    load: tuple[str, ...]
    node: str
    manifest: bytes
    lockfile: bytes


@dataclass(frozen=True)
class Measurement:
    """One tree, measured. ``loads``: every file that is not a test file parses and every such module imports (None:
    a step could not finish); ``lint_total``: the ESLint total, errors and warnings (None: no usable report);
    ``tests_green``: MF12's decision on the ``TEST_RUNS`` runs, test by test (`tests_green`); ``lint_split``: the
    total's errors and warnings, when the report gave them apart; ``test_files_load``: every test file parses and no
    run failed one as a whole (None: a step could not finish); ``red_files``: the files of MF12's red tests, as paths
    of the tree."""
    node: str
    loads: bool | None
    lint_total: int | None
    tests_green: bool | None
    lint_split: tuple[int, int] | None = None
    test_files_load: bool | None = True
    red_files: tuple[str, ...] = ()


Tree = dict[str, tuple[bytes, bool]]  # path -> (content, executable)


class Sandbox(Protocol):
    def ready(self) -> None: ...  # FixtureStop when it cannot measure
    def measure(self, tree: Tree, plan: Plan) -> Measurement: ...
    def close(self) -> None: ...


def is_node_test_file(rel: str) -> bool:
    """Whether ``node --test`` (Node 22) runs the file by default, ``rel`` relative to the directory it runs in:
    ``**/*.test.*``, ``**/*-test.*``, ``**/*_test.*``, ``**/test-*.*``, ``**/test.*`` and ``**/test/**/*``, each of
    ``.js``, ``.mjs``, ``.cjs``."""
    path = PurePosixPath(rel)
    if path.suffix not in JS_SUFFIXES:
        return False
    stem = path.name[:-len(path.suffix)]
    return ("test" in path.parts[:-1] or stem == "test" or stem.startswith("test-")
            or stem.endswith((".test", "-test", "_test")))


def tarballs_of(lock: bytes, where: str = "the lockfile") -> list[tuple[str, str]]:
    """Each distinct ``(resolved, integrity)`` of the lockfile's packages, sorted: every one a tarball of the npm
    registry with one sha512 integrity, which the seed checks on the bytes it fetches and npm checks again."""
    try:
        data = json.loads(lock.decode("utf-8"), object_pairs_hook=stagelock._unique)
    except (UnicodeDecodeError, ValueError, RecursionError) as exc:
        raise FixtureStop(f"{where} is not JSON: {exc}") from exc
    packages = data.get("packages") if isinstance(data, dict) else None
    if not isinstance(packages, dict) or "" not in packages:
        raise FixtureStop(f"{where} has no packages map (lockfileVersion 2 or 3): npm ci cannot read it from the "
                          "lockfile alone")
    found: set[tuple[str, str]] = set()
    for name, entry in packages.items():
        if name == "":
            continue
        if not isinstance(entry, dict) or not isinstance(entry.get("resolved"), str) \
                or not entry["resolved"].startswith(REGISTRY) or not isinstance(entry.get("integrity"), str):
            raise FixtureStop(f"{where}: a package is not one of the npm registry with its integrity: the "
                              "dependencies come from the registry only")
        if not SRI_RE.match(entry["integrity"]):
            raise FixtureStop(f"{where}: a package's integrity is not one sha512 (sha512-<base64>): the seed checks "
                              "each tarball it fetches against it")
        found.add((entry["resolved"], entry["integrity"]))
    if len({url for url, _i in found}) != len(found):
        raise FixtureStop(f"{where}: one tarball is named with two integrities")
    return sorted(found)


def download(url: str, limit: int) -> bytes:
    """The bytes at ``url``: HTTP 200, no redirect followed, at most ``limit`` bytes; FixtureStop otherwise."""
    try:
        with urllib.request.build_opener(_NoRedirect()).open(url, timeout=120) as response:
            status, data = response.status, response.read(limit + 1)
    except (urllib.error.URLError, OSError, ValueError) as exc:  # a refused redirect is an HTTPError, a URLError
        raise FixtureStop(f"a tarball could not be fetched from the npm registry: {type(exc).__name__}; nothing "
                          "was written") from None
    if status != 200:
        raise FixtureStop(f"the npm registry answered {status}, not 200; nothing was written")
    if len(data) > limit:
        raise FixtureStop(f"the lockfile's tarballs are over {MAX_DEPS_BYTES} bytes; nothing was written")
    return data


def registry_tarball(url: str, integrity: str, limit: int, get: Callable[[str, int], bytes] = download) -> bytes:
    """One of the lockfile's tarballs, fetched by the seed itself from the npm registry and held to its integrity
    before any byte reaches a container: no container, the install's included, has a network."""
    if not url.startswith(REGISTRY) or not SRI_RE.match(integrity):
        raise FixtureStop("a tarball is not one of the npm registry with one sha512 integrity")
    data = get(url, limit)
    if base64.b64encode(hashlib.sha512(data).digest()).decode("ascii") != integrity[len("sha512-"):]:
        raise FixtureStop("a tarball fetched from the npm registry is not the lockfile's integrity; nothing was "
                          "written")
    return data


def plan_of(tree: Tree, where: str = "the toy tree") -> Plan:
    """The measurement of a tree's single Node project: its ``package-lock.json`` (one, outside ``node_modules``),
    ``package.json`` (``scripts.test`` exactly ``node --test``, a ``scripts.lint``) and ``.nvmrc`` beside it."""
    locks = [p for p in tree if PurePosixPath(p).name == "package-lock.json" and "node_modules" not in p.split("/")]
    if len(locks) != 1:
        raise FixtureStop(f"{where} holds {len(locks)} package-lock.json, not one: the toy is one Node project")
    parent = PurePosixPath(locks[0]).parent.as_posix()
    project = "" if parent == "." else parent
    at = f"{project}/" if project else ""
    for name in ("package.json", ".nvmrc"):
        if f"{at}{name}" not in tree:
            raise FixtureStop(f"{where} has no {at}{name} beside its lockfile")
    try:
        manifest = json.loads(tree[f"{at}package.json"][0].decode("utf-8"), object_pairs_hook=stagelock._unique)
    except (UnicodeDecodeError, ValueError, RecursionError) as exc:
        raise FixtureStop(f"{where}: {at}package.json is not JSON: {exc}") from exc
    scripts = manifest.get("scripts") if isinstance(manifest, dict) else None
    if not isinstance(scripts, dict) or scripts.get("test") != TEST_SCRIPT or not isinstance(scripts.get("lint"), str):
        raise FixtureStop(f"{where}: {at}package.json's scripts must run the tests with exactly {TEST_SCRIPT!r} and "
                          "name a lint script: the measurement uses the toy's own tools as the seed reads them")
    nvmrc = NVMRC_RE.match(tree[f"{at}.nvmrc"][0].decode("utf-8", "replace"))
    if not nvmrc:
        raise FixtureStop(f"{where}: {at}.nvmrc does not name one Node version (major.minor.patch)")
    tarballs_of(tree[locks[0]][0], f"{where}: {locks[0]}")
    js = sorted(p for p in tree if p.startswith(at) and p.endswith(JS_SUFFIXES)
                and "node_modules" not in p[len(at):].split("/"))
    return Plan(project, tuple(js), tuple(p for p in js if not is_node_test_file(p[len(at):])), f"v{nvmrc.group(1)}",
                tree[f"{at}package.json"][0], tree[locks[0]][0])


def covers(unit: str, path: str) -> bool:
    """`29k`'s cover rule: ``path`` is the unit's path or under it."""
    top = unit.rstrip("/")
    return path == top or path.startswith(top + "/")


def units_of(path: str, candidates: tuple[str, ...]) -> tuple[str, ...]:
    """The toy's unit candidates that cover a plant's file: the unit whose merge declares the impact set is one of
    them, and which one is not the seed's to say."""
    return tuple(u for u in candidates if covers(u, path))


def measured_cause(base: Measurement, measured: Measurement, units: tuple[str, ...]) -> tuple[str | None, str]:
    """`29j`'s rule order on a plant's tree against the clean base: the cause, or None and why none can be named.
    ``units``: the unit candidates covering the plant's file (`units_of`)."""
    if measured.node != base.node:
        return None, "it was measured on another Node"
    if measured.loads is False:
        return "build_break", "the code no longer loads"
    if measured.loads is None or measured.lint_total is None or measured.test_files_load is None:
        return None, "a step of its measurement could not finish"
    if measured.test_files_load is False:
        return None, ("a test file no longer parses or fails as a whole: build_break or test_regression, as the seed "
                      "does not name build_ok's producer (`29j`)")
    if measured.tests_green is None:
        return None, (f"its tests did not finish, or a test failed without failing in all {TEST_RUNS} runs (flaky, "
                      "MF12)")
    if base.lint_split and measured.lint_split:
        moves = {(after > before) - (after < before) for before, after in zip(base.lint_split, measured.lint_split)}
        if {1, -1} <= moves:
            return None, "its ESLint errors and warnings moved apart: a total of one of them names another cause"
    rose, red = measured.lint_total > base.lint_total, not measured.tests_green
    if rose and red:
        return None, "the lint total rose and a test is red: two causes, not one"
    if rose:
        return "lint_regression", "the lint total rose"
    if red and not (units and any(all(covers(u, f) for u in units) for f in measured.red_files)):
        return None, ("no red test is a test of the plant's unit (Stage 0's impact set): MF13 would name "
                      "impact_miss")
    if red:
        return "test_regression", "a test is red"
    return None, "it loads, its lint total did not rise and its tests are green: no cause"


# ---------------------------------------------------------------- the docker sandbox

# Runs as `node -e` in a measurement container, after the tree is unpacked under /tmp/work and with no network. A
# container runs one step of one tree (DFX_STEP): `build` parses every JavaScript file, imports every module that is
# not a test file and runs the toy's lint script; `test` runs the toy's tests once. Each of MF12's four runs is a
# container of its own, so no run sees what the build or another run left (`29j` `flaky`, "taze kapsayıcıda yeniden
# koşuları"). Each command is its own process with a deadline, its output captured, never this script's own stdout.
HARNESS = r"""'use strict';
const cp = require('node:child_process'), fs = require('node:fs'), path = require('node:path');
const url = require('node:url');
const root = '/tmp/work', proj = path.join(root, process.env.DFX_PROJECT), ms = Number(process.env.DFX_STEP_MS);
fs.cpSync('/deps/node_modules', path.join(proj, 'node_modules'), {recursive: true, verbatimSymlinks: true});
function step(cmd, args, cwd, keep) {
  const r = cp.spawnSync(cmd, args, {cwd, timeout: ms, killSignal: 'SIGKILL', maxBuffer: 1 << 26,
                                     stdio: ['ignore', keep ? 'pipe' : 'ignore', 'ignore']});
  const timedOut = !!r.error && r.error.code === 'ETIMEDOUT';
  return {status: r.error ? null : r.status, timed_out: timedOut,
          stdout: keep && r.stdout ? r.stdout.toString('utf8') : ''};
}
const out = {node: process.version, step: process.env.DFX_STEP};
if (out.step === 'build') {
  out.parse = [];
  for (const f of JSON.parse(process.env.DFX_PARSE)) {
    const r = step(process.execPath, ['--check', path.join(root, f)], root, false);
    out.parse.push({status: r.status, timed_out: r.timed_out});
  }
  out.load = [];
  for (const f of JSON.parse(process.env.DFX_LOAD)) {
    const file = path.join(root, f);
    const r = step(process.execPath, ['--input-type=module', '-e', 'await import(process.argv[1])',
                                      url.pathToFileURL(file).href], path.dirname(file), false);
    out.load.push({status: r.status, timed_out: r.timed_out});
  }
  out.lint = step('npm', ['run', '--silent', 'lint'], proj, true);
} else if (out.step === 'test') {
  // the toy's `test` script is exactly `node --test` (plan_of): run it with a reporter of ours, per test; what the
  // tests print arrives at the reporter as events and is never read as the report
  fs.writeFileSync('/tmp/dfx-reporter.mjs', process.env.DFX_REPORTER);
  const t = step(process.execPath, ['--test', '--test-reporter=/tmp/dfx-reporter.mjs',
                                    '--test-reporter-destination=stdout'], proj, true);
  let rec = null;
  try { rec = JSON.parse(t.stdout); } catch (e) { rec = null; }
  out.test = {status: t.status, timed_out: t.timed_out, tests: rec && rec.tests, red: rec && rec.red};
}
process.stdout.write(JSON.stringify(out));
"""
# The reporter: one line, the number of tests that passed or failed and each red one: its file as a path of the tree,
# line, column and name (a test is one test in every run), and `whole` when the file failed as a whole (Node names
# that failure after the file's path from where it runs: a throw before any test, an import that fails, a parse
# error). A skipped or todo test is no result (a todo test's failure fails no run).
REPORTER = r"""import path from 'node:path';
export default async function* (source) {
  const red = new Map();
  let tests = 0;
  for await (const e of source) {
    if (e.type !== 'test:pass' && e.type !== 'test:fail') continue;
    const d = e.data;
    if (d.skip || d.todo) continue;
    tests += 1;
    if (e.type === 'test:fail') {
      const named = typeof d.file === 'string';
      const r = {file: named ? path.relative('/tmp/work', d.file) : null, line: d.line ?? null,
                 column: d.column ?? null, name: d.name,
                 whole: named && d.nesting === 0 && d.name === path.relative(process.cwd(), d.file)};
      red.set(JSON.stringify(r), r);
    }
  }
  yield JSON.stringify({tests, red: [...red.values()]});
}
"""
MEASURE_SH = 'set -eu\nmkdir /tmp/work\ntar -x -C /tmp/work --no-same-owner -f -\nexec node -e "$DFX_HARNESS"\n'
# No network here either: npm reads every tarball from its cache, filled from the bytes the seed fetched and checked.
INSTALL_SH = ("set -eu\nmkdir /tmp/p\ntar -x -C /tmp/p --no-same-owner -f -\ncd /tmp/p\n"
              "if [ -d tarballs ]; then npm cache add /tmp/p/tarballs/*.tgz >/dev/null 2>&1; fi\n"
              f"npm ci --offline --ignore-scripts --no-audit --no-fund --registry={REGISTRY} >/dev/null 2>&1\n"
              "mkdir -p node_modules\ncp -R node_modules /deps/\n")  # a lockfile of no package makes no node_modules
LABEL = "snowball.drill-fixtures=1"
HARDENED = ("--network", "none", "--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--read-only",
            "--tmpfs", "/tmp:rw,exec,nosuid,size=1g", "--pids-limit", "256", "--memory", "1g", "--cpus", "2",
            "--env", "HOME=/tmp", "--env", "npm_config_update_notifier=false", "--env", "npm_config_cache=/tmp/.npm")


def tar_of(files: dict[str, tuple[bytes, bool]]) -> bytes:
    """A tar of regular files only, by sorted path, with no owner and no time."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:", format=tarfile.PAX_FORMAT) as tar:
        for rel in sorted(files):
            content, executable = files[rel]
            info = tarfile.TarInfo(rel)
            info.size, info.mode, info.mtime = len(content), 0o755 if executable else 0o644, 0
            tar.addfile(info, io.BytesIO(content))
    return buf.getvalue()


def _steps(value: Any, count: int) -> bool | None:
    if not isinstance(value, list) or len(value) != count or not all(isinstance(s, dict) for s in value):
        raise ValueError("a step list is not the plan's")
    if any(type(s.get("status")) is int and s["status"] != 0 for s in value):
        return False
    return None if any(s.get("status") != 0 for s in value) else True


RedTest = tuple[str, Any, Any, str, bool]  # its file as a path of the tree, line, column, name; failed as a whole


def red_of(run: Any) -> frozenset[RedTest] | None:
    """The red tests of one run of the toy's tests; None when the run did not finish, ran no test (`04`), names a red
    test the reporter does not write, or its exit status and its red tests disagree (a run that died naming no test,
    or a red test in a run that passed)."""
    if not isinstance(run, dict):
        raise ValueError("a test run is not an object")
    red, tests = run.get("red"), run.get("tests")
    if run.get("timed_out") or type(run.get("status")) is not int or type(tests) is not int or tests < 1 \
            or not isinstance(red, list) or len(red) > tests:
        return None
    found: set[RedTest] = set()
    for r in red:
        if not isinstance(r, dict) or not isinstance(r.get("file"), str) or not r["file"] \
                or path_problem(r["file"]) or not isinstance(r.get("name"), str) or type(r.get("whole")) is not bool \
                or not all(r.get(k) is None or type(r.get(k)) is int for k in ("line", "column")):
            return None
        found.add((r["file"], r.get("line"), r.get("column"), r["name"], r["whole"]))
    if (run["status"] != 0) != bool(found):
        return None
    return frozenset(found)


def tests_green(reds: Any) -> tuple[bool | None, frozenset[RedTest]]:
    """MF12's decision (`29j` `flaky`) on the red tests of the ``TEST_RUNS`` runs (`red_of`), test by test, and its
    red tests: True when no run has a red test; False when a test is red in every run (`red`, the sentinel reverts);
    None when a run could not finish or a test failed in some runs only (flaky: no red test, the sentinel does not
    revert)."""
    if not isinstance(reds, list) or len(reds) != TEST_RUNS:
        raise ValueError("the test runs are not the plan's")
    if None in reds:
        return None, frozenset()
    red = frozenset.intersection(*reds)
    if red:
        return False, red
    return (None if frozenset.union(*reds) else True), frozenset()


def lint_split(stdout: str) -> tuple[int, int] | None:
    """ESLint's JSON report's errors and warnings, each summed over every file; None for anything else."""
    try:
        report = json.loads(stdout)
    except (ValueError, RecursionError):
        return None
    if not isinstance(report, list) or not all(isinstance(r, dict) for r in report):
        return None
    counts = [[r.get(k) for r in report] for k in ("errorCount", "warningCount")]
    if not all(type(c) is int and c >= 0 for kind in counts for c in kind):
        return None
    return sum(counts[0]), sum(counts[1])


def measurement_of(build: bytes, runs: tuple[bytes, ...], plan: Plan) -> Measurement:
    """The build container's JSON line and the ``TEST_RUNS`` test containers' (each a fresh container's), read into
    a measurement; FixtureStop when one is not the harness's, or they ran on different Nodes."""
    try:
        out = json.loads(build.decode("utf-8"))
        tests = [json.loads(raw.decode("utf-8")) for raw in runs]
        if not isinstance(out, dict) or out.get("step") != "build" or len(tests) != TEST_RUNS \
                or not all(isinstance(t, dict) and t.get("step") == "test" for t in tests):
            raise ValueError("not the steps' outputs")
        node, lint = out["node"], out["lint"]
        if not isinstance(node, str) or any(t["node"] != node for t in tests) or not isinstance(lint, dict):
            raise ValueError("not the harness's fields")
        parse = out["parse"]
        _steps(parse, len(plan.parse))
        modules = set(plan.load)
        loads = _steps([s for f, s in zip(plan.parse, parse) if f in modules], len(modules))
        tests_parse = _steps([s for f, s in zip(plan.parse, parse) if f not in modules], len(plan.parse) - len(modules))
        imported = _steps(out["load"], len(plan.load))
        reds = [red_of(t["test"]) for t in tests]
    except (UnicodeDecodeError, ValueError, KeyError, TypeError, RecursionError) as exc:
        raise FixtureStop(f"the measurement container's output is not the harness's: {type(exc).__name__}") from exc
    green, red = tests_green(reds)
    whole = any(test[4] for run in reds if run for test in run)
    tests_load = False if tests_parse is False or whole else tests_parse
    loads = False if False in (loads, imported) else (None if None in (loads, imported) else True)
    split = lint_split(lint.get("stdout", "")) if lint.get("status") in (0, 1) and not lint.get("timed_out") else None
    return Measurement(node, loads, None if split is None else sum(split), green, split, tests_load,
                       tuple(sorted({test[0] for test in red})))


@dataclass
class DockerSandbox:
    """Each step one fresh container of ``image`` (pinned by digest), none with a network; the dependencies of each
    distinct lockfile go into a docker volume of this run, installed from tarballs the seed fetched and held to the
    lockfile's integrity (``fetch``), mounted read-only where trees are measured, and removed at the end."""
    image: str
    docker: str = "docker"
    step_s: int = 120
    run: Callable[..., subprocess.CompletedProcess] = subprocess.run
    fetch: Callable[[str, int], bytes] = download
    volumes: dict[str, str] = field(default_factory=dict)

    def ready(self) -> None:
        if not config.IMAGE_RE.match(self.image):
            raise FixtureStop("--node-image must name its digest (name:tag@sha256:<64 hex>), so the toy's tools are "
                              "the image's that was chosen")
        try:
            proc = self.run([self.docker, "version", "--format", "{{.Server.Version}}"], capture_output=True,
                            timeout=60, check=False)
            ok = proc.returncode == 0 and proc.stdout.strip()
        except (OSError, subprocess.TimeoutExpired):
            ok = False
        if not ok:
            raise FixtureStop("docker is not available: the causes are measured with the toy's own tools in a "
                              "sandbox (`26f`) and that is never skipped; nothing was written")

    def _container(self, args: list[str], stdin: bytes, timeout: int) -> subprocess.CompletedProcess:
        name = f"snowball-dfx-{uuid.uuid4().hex[:16]}"
        argv = [self.docker, "run", "--rm", "-i", "--name", name, "--label", LABEL, *args]
        try:
            return self.run(argv, input=stdin, capture_output=True, timeout=timeout, check=False)
        except subprocess.TimeoutExpired:
            self.run([self.docker, "rm", "-f", name], capture_output=True, check=False)
            raise FixtureStop(f"a sandbox step ran past {timeout} s; nothing was written") from None

    def _deps(self, plan: Plan) -> str:
        key = canon.sha256_hex(hashlib.sha256(plan.manifest).digest() + hashlib.sha256(plan.lockfile).digest())
        if key in self.volumes:
            return self.volumes[key]
        files = {"package.json": (plan.manifest, False), "package-lock.json": (plan.lockfile, False)}
        left = MAX_DEPS_BYTES
        for k, (url, integrity) in enumerate(tarballs_of(plan.lockfile)):
            data = registry_tarball(url, integrity, left, self.fetch)
            left -= len(data)
            files[f"tarballs/{k:05d}.tgz"] = (data, False)
        volume = f"snowball-dfx-{uuid.uuid4().hex[:16]}"
        made = self.run([self.docker, "volume", "create", "--label", LABEL, volume], capture_output=True, check=False)
        if made.returncode != 0:
            raise FixtureStop("docker could not create the dependency volume; nothing was written")
        self.volumes[key] = volume
        proc = self._container([*HARDENED, "--user", "0:0", "--mount", f"type=volume,src={volume},dst=/deps",
                                "--entrypoint", "sh", self.image, "-c", INSTALL_SH], tar_of(files), 900)
        if proc.returncode != 0:
            raise FixtureStop("npm ci --offline --ignore-scripts did not install the dependencies from the lockfile; "
                              "nothing was written")
        return volume

    def _step(self, step: str, tree: bytes, plan: Plan, volume: str) -> bytes:
        """One fresh container on the tree's bytes: the build step, or one run of the tests."""
        env = {"DFX_STEP": step, "DFX_PROJECT": plan.project, "DFX_STEP_MS": str(self.step_s * 1000),
               "DFX_HARNESS": HARNESS, "DFX_REPORTER": REPORTER,
               "DFX_PARSE": json.dumps(list(plan.parse)), "DFX_LOAD": json.dumps(list(plan.load))}
        args = [*HARDENED, "--user", "65534:65534", "--mount", f"type=volume,src={volume},dst=/deps,readonly"]
        for key, value in env.items():
            args += ["--env", f"{key}={value}"]
        count = len(plan.parse) + len(plan.load) + 1 if step == "build" else 1
        proc = self._container([*args, "--entrypoint", "sh", self.image, "-c", MEASURE_SH], tree,
                               count * self.step_s + 300)
        if proc.returncode != 0:
            raise FixtureStop("the measurement container failed; nothing was written")
        return proc.stdout

    def measure(self, tree: Tree, plan: Plan) -> Measurement:
        volume, data = self._deps(plan), tar_of(tree)
        build = self._step("build", data, plan, volume)
        runs = tuple(self._step("test", data, plan, volume) for _k in range(TEST_RUNS))
        return measurement_of(build, runs, plan)

    def close(self) -> None:
        for volume in self.volumes.values():
            self.run([self.docker, "volume", "rm", "-f", volume], capture_output=True, check=False)
        self.volumes.clear()


# ---------------------------------------------------------------- the inputs

def _outside_repositories(path: Path, what: str) -> None:
    """A private file is outside every git repository: no ancestor of it holds a ``.git``."""
    for parent in path.resolve().parents:
        if (parent / ".git").exists():
            raise FixtureStop(f"{what} is inside the git repository {parent}: the fixtures and their drafts are "
                              "private and never a repository's file (`26f`)")


def read_catalog(path: Path) -> list[tuple[str, str]]:
    """The operator's drafts: a JSON list of objects with exactly ``cause`` and ``patch``, both strings."""
    try:
        data = json.loads(path.read_bytes().decode("utf-8"), object_pairs_hook=stagelock._unique,
                          parse_constant=stagelock._constant)
    except OSError as exc:
        raise FixtureStop(f"the catalog cannot be read: {type(exc).__name__}") from exc
    except (UnicodeDecodeError, ValueError, RecursionError) as exc:
        raise FixtureStop(f"the catalog is not JSON: {type(exc).__name__}") from exc
    if not isinstance(data, list) or not data:
        raise FixtureStop("the catalog must be a non-empty JSON list of {cause, patch}")
    for k, entry in enumerate(data):
        if not isinstance(entry, dict) or set(entry) != {"cause", "patch"} \
                or not all(isinstance(entry[key], str) for key in entry):
            raise FixtureStop(f"catalog entry {k} must have exactly the string fields cause and patch")
    return [(entry["cause"], entry["patch"]) for entry in data]


@dataclass(frozen=True)
class Binding:
    import_line_sha256: str
    toy_tree_sha256: str
    brain_sha: str
    keywords: tuple[str, ...]
    toy: config.Target


def binding(referee: Path) -> Binding:
    """The counter's last transfer line in the referee checkout's commit, held to that commit's referee tree (E471),
    with the commit's security keywords and toy target."""
    head = stagelock._checkout_head(referee)
    counter = stagelock.chained_lines(stagelock._committed(referee, head, importer.COUNTER), importer.COUNTER)
    transfers = [(line, row) for line, row in counter if stagelock.is_transfer(row)]
    if not transfers:
        raise FixtureStop(f"{importer.COUNTER} holds no transfer: import first (`25a` 1)")
    line, row = transfers[-1]
    toy_tree, brain_sha = row.get("toy_tree_sha256"), row.get("brain_sha")
    if not isinstance(toy_tree, str) or not stagelock.HEX64.match(toy_tree):
        raise FixtureStop(f"the last transfer of {importer.COUNTER} names no toy tree (a batch transfer leaves the toy "
                          "as it is): the fixtures are bound to a transfer that wrote the toy")
    if not isinstance(brain_sha, str) or not stagelock.SHA.match(brain_sha):
        raise FixtureStop(f"the last transfer of {importer.COUNTER} names no brain commit")
    stagelock._committed_is_transferred(referee, head, row)
    try:
        policy = json.loads(stagelock._committed(referee, head, "policy.json").decode("utf-8"),
                            object_pairs_hook=stagelock._unique)
        words = policy["constitutional"]["security_keywords"]
    except (UnicodeDecodeError, ValueError, RecursionError, KeyError, TypeError) as exc:
        raise FixtureStop(f"policy.json of the checkout's commit names no constitutional.security_keywords: "
                          f"{type(exc).__name__}") from exc
    if not isinstance(words, list) or not words or not all(isinstance(w, str) and w.strip() for w in words):
        raise FixtureStop("policy.json's constitutional.security_keywords must be a non-empty list of non-empty texts "
                          "(`14`, `18a`)")
    toys = [t for t in stagelock._committed_summary(referee, head).targets or () if t.kind == "toy"]
    if len(toys) != 1:
        raise FixtureStop("setup/summary.json's targets[] must name one toy target (`26c`, `25` 10a)")
    keywords = tuple(w.strip().lower() for w in words)
    return Binding(stagelock.line_sha256(line), toy_tree, brain_sha, keywords, toys[0])


def _tree_hash(repo: Path, treeish: str, what: str) -> str:
    try:
        return importer.part_hash(repo, treeish, importer.TOY_DIR, forbid_operator_names=False, fold_case=True)
    except (gitio.GitError, importer.ImportErrorStop) as exc:
        raise FixtureStop(f"{what} cannot be read: {exc}") from exc


def toy_tree(toy: Path, ref: str, expected: str) -> tuple[Tree, dict[str, str]]:
    """The toy clone's tree at ``ref``, held to the line's ``toy_tree_sha256``; its files and each path's mode. The ref
    is resolved once, so the hash, the modes and the files are of one tree even if the ref moves meanwhile."""
    try:
        tree = gitio.git(toy, "rev-parse", "--verify", "--quiet", f"{ref}^{{tree}}").decode().strip()
    except gitio.GitError as exc:
        raise FixtureStop(f"--toy {toy} has no tree at {ref}: fetch the toy's main") from exc
    if _tree_hash(toy, tree, f"--toy {toy} at {ref}") != expected:
        raise FixtureStop(f"the toy at {ref} is not the tree the last transfer line names (toy_tree_sha256)")
    modes = {p: m for m, _s, p in gitio._entries(toy, tree)}
    files = {p.as_posix(): (content, executable) for p, content, executable in iter_files(gitio.archive(toy, tree))}
    return files, modes


def merge_expected_files(brain: Path, bind: Binding) -> dict[str, set[str]]:
    """``candidates/<toy id>/<cid>/`` at the line's brain commit: each merge-expected candidate's changed files. The
    brain's toy fixture there must be the line's toy tree, so the candidates are the ones beside it."""
    if not gitio.has_commit(brain, bind.brain_sha):
        raise FixtureStop(f"--brain {brain} does not hold the transfer's brain commit {bind.brain_sha}: fetch it")
    if _tree_hash(brain, f"{bind.brain_sha}:{importer.TOY_DIR}", "the brain's toy fixture") != bind.toy_tree_sha256:
        raise FixtureStop(f"the brain's {importer.TOY_DIR}/ at {bind.brain_sha} is not the toy tree the line names")
    top = f"candidates/{bind.toy.id}/"
    files = {p.as_posix(): c for p, c, _x in iter_files(gitio.archive(brain, bind.brain_sha, (top.rstrip("/"),)))}
    ids = sorted({p[len(top):].split("/", 1)[0] for p in files if "/" in p[len(top):]})
    if not ids:
        raise FixtureStop(f"{top} holds no candidate at {bind.brain_sha}: the per-file rule has nothing to read")
    out: dict[str, set[str]] = {}
    for cid in ids:
        try:
            expect = json.loads(files[f"{top}{cid}/expect.json"].decode("utf-8"))
            if not isinstance(expect, dict) or expect.get("decision") not in ("merge", "reject"):
                raise ValueError("no decision merge or reject")
            if expect["decision"] == "merge":
                out[cid] = changed_files(files[f"{top}{cid}/diff.patch"].decode("utf-8"))
        except (KeyError, UnicodeDecodeError, ValueError, RecursionError) as exc:
            raise FixtureStop(f"candidate {cid}: its expect.json or diff.patch cannot be read ({exc}), so the "
                              "per-file rule cannot be checked") from exc
    return out


def _on_security_path(path: str, bind: Binding) -> bool:
    """`14`'s keyword rule and the owner's safety paths, both read case-blind (the keywords lower-cased and stripped
    by `binding`): wider than the profile's reading, never narrower."""
    low = path.lower()
    return any(word in low for word in bind.keywords) or any(covers(e.lower(), low) for e in bind.toy.safety_paths)


def planted(k: int, cause: str, patch: str, tree: Tree, modes: dict[str, str], bind: Binding,
            merged: dict[str, set[str]]) -> tuple[str, bytes]:
    """Catalog entry ``k`` checked against every rule but the measurement; its file and that file's new bytes."""
    where = f"catalog entry {k}"
    if cause not in CAUSES:
        raise FixtureStop(f"{where}: its cause is not one of {', '.join(CAUSES)} (`26f`, `29j`)")
    try:
        edit = in_place_edit(patch)
    except ValueError as exc:
        raise FixtureStop(f"{where}: its patch {exc}") from exc
    if path_problem(edit.path) or modes.get(edit.path) not in ("100644", "100755") or edit.path not in tree:
        raise FixtureStop(f"{where}: its patch changes no existing regular file of the toy tree")
    if _on_security_path(edit.path, bind):
        raise FixtureStop(f"{where}: its file is on a security path (`26f`, `14`, `05`)")
    for cid, paths in sorted(merged.items()):
        if edit.path in paths:
            raise FixtureStop(f"{where}: its file is one the merge-expected candidate {cid} changes (`26f`: per file)")
    if edit.mode != modes[edit.path]:
        raise FixtureStop(f"{where}: its index line names another mode than the file's (no mode change)")
    old = tree[edit.path][0]
    if not blob_id(old).startswith(edit.old_blob):
        raise FixtureStop(f"{where}: its index line names another blob than the file's in this toy tree")
    try:
        new = apply(old, edit.hunks)
    except (ValueError, UnicodeEncodeError) as exc:
        raise FixtureStop(f"{where}: its patch does not apply exactly: {exc}") from exc
    if not blob_id(new).startswith(edit.new_blob):
        raise FixtureStop(f"{where}: its index line names another result blob than the patch makes")
    if new == old:
        raise FixtureStop(f"{where}: its patch changes nothing")
    if b"\0" in old or b"\0" in new:
        raise FixtureStop(f"{where}: its file is binary")
    return edit.path, new


# ---------------------------------------------------------------- the command

def _checked_and_measured(referee: Path, toy: Path, toy_ref: str, brain: Path, catalog: Path,
                          sandbox: Sandbox) -> tuple[bytes, dict[str, int]]:
    """Every rule of `26f` on the drafts, then each plant's cause measured against the clean base; the value."""
    drafts = read_catalog(catalog)
    bind = binding(referee)
    tree, modes = toy_tree(toy, toy_ref, bind.toy_tree_sha256)
    if any(PurePosixPath(p).name.lower() == OWNERSHIP_FILE for p in tree):
        raise FixtureStop("the toy tree holds an ownership file (CODEOWNERS): the paths it gives the security team are "
                          "security paths (`14`), and the seed does not read which those are")
    merged = merge_expected_files(brain, bind)
    plants = [planted(k, cause, patch, tree, modes, bind, merged) for k, (cause, patch) in enumerate(drafts)]
    if len(set(plants)) != len(plants):
        raise FixtureStop("two catalog entries plant the same bytes in the same file: one plant, not two instances (a "
                          "plant once made is in the toy's public history)")
    counts = {cause: sum(c == cause for c, _p in drafts) for cause in CAUSES}
    if len(set(counts.values())) != 1 or not counts[CAUSES[0]]:
        raise FixtureStop("each cause needs the same number of instances, at least one (`26f`): "
                          + ", ".join(f"{c} {n}" for c, n in counts.items()))
    ids = [secrets.token_hex(16) for _d in drafts]
    if len(set(ids)) != len(ids) or not all(ID_RE.match(i) for i in ids):
        raise FixtureStop("the fresh ids are not 32 distinct lowercase hex characters")
    instances = sorted(({"id": i, "cause": c, "patch": p} for i, (c, p) in zip(ids, drafts)), key=lambda x: x["id"])
    value = base64.b64encode(canon.canonical({"import_line_sha256": bind.import_line_sha256, "instances": instances}))
    if len(value) > MAX_VALUE_BYTES:
        raise FixtureStop(f"the value is {len(value)} bytes, over GitHub's 48 KB for one secret (E544)")
    base_plan = plan_of(tree)
    trees = []
    for k, (path, new) in enumerate(plants):
        patched = dict(tree, **{path: (new, tree[path][1])})
        if plan_of(patched, f"catalog entry {k}'s tree") != base_plan:
            raise FixtureStop(f"catalog entry {k}: its patch changes what the measurement installs from or runs on "
                              "(package.json, package-lock.json, .nvmrc): a plant is measured with the base's tools")
        trees.append(patched)
    base = sandbox.measure(tree, base_plan)
    if base.node != base_plan.node:
        raise FixtureStop(f"the image's Node is {base.node}, the toy's .nvmrc names {base_plan.node}")
    if not (base.loads and base.test_files_load and base.lint_total is not None and base.tests_green):
        raise FixtureStop("the clean toy tree does not load with a lint report and green tests: no plant can be "
                          "measured against it")
    for k, ((cause, _patch), (path, _new), patched) in enumerate(zip(drafts, plants, trees)):
        units = units_of(path, bind.toy.unit_candidates)
        found, why = measured_cause(base, sandbox.measure(patched, base_plan), units)
        if found != cause:
            raise FixtureStop(f"catalog entry {k}: declared {cause}, measured {found or 'no single cause'} ({why})")
    return value, counts


def produce(referee: Path, toy: Path, toy_ref: str, brain: Path, catalog: Path, out: Path,
            sandbox: Sandbox) -> dict[str, Any]:
    """Check, measure, write; what may be printed: the counts, the value's sha256 and its size."""
    _outside_repositories(catalog, "the catalog")
    _outside_repositories(out, "--out")
    if out.exists() or out.is_symlink():
        raise FixtureStop("--out is there already: the fixtures are never written over (a burnt set is never reused, "
                          "`26f`); give a new path")
    if not out.parent.is_dir():
        raise FixtureStop("--out's directory is not there: the value is written into an existing private directory")
    sandbox.ready()
    try:
        value, counts = _checked_and_measured(referee, toy, toy_ref, brain, catalog, sandbox)
    finally:
        sandbox.close()
    try:
        handle = os.open(out, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o600)
    except FileExistsError:
        raise FixtureStop("--out appeared while the plants were measured: nothing was written over") from None
    except OSError as exc:
        raise FixtureStop(f"--out cannot be created: {type(exc).__name__}; nothing was written") from None
    with os.fdopen(handle, "wb") as stream:
        stream.write(value)
    return {"causes": counts, "instances": sum(counts.values()), "value_sha256": hashlib.sha256(value).hexdigest(),
            "value_bytes": len(value)}

