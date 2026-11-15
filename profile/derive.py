"""Static profile derivation and the check of a proposal against it (stage 0, MF4).

Rules: tohum/14 (the referee derives the profile itself; a proposal that differs from the derivation is
refused; security paths by keyword and ownership file; excluded directories; agent configuration excluded
everywhere and case-insensitively; the operator's ``excluded_paths``, which a proposal may only widen),
tohum/26a (``profile.derive``: target tree and ``targets[]`` in; profile, unit candidates, excluded paths
out; no side effect), tohum/26b and 26c (field names, the unit recipe), asama-0/08 (unit selection
criteria), asama-0/09 tests 19 and 47, tohum/29d (group ``profile``).

What ``derive`` returns, and the exact rule for each field (all paths are relative to the tree root,
``/``-separated; names are compared after ``str.casefold``):

- Walk. Every entry below the root is visited in name order without following symlinks; a directory
  the walk cannot list stops the derivation (``DeriveError``), it is never skipped. An entry is not
  descended into, and adds nothing to the fields below the excluded ones, when it is excluded: its name
  is one of ``AGENT_CONFIG`` or ``EXCLUDED_DIR_NAMES``, or it matches an operator pattern.
- ``agent_config``: the seven names of tohum/14 (``.claude``, ``CLAUDE.md``, ``AGENTS.md``,
  ``.mcp.json``, ``.vscode``, ``.envrc``, ``.devcontainer``). A path is agent configuration when any of
  its components equals one of them after casefold, at any depth, file or directory. In the tree, a
  symlink whose target text has such a component (``/`` or ``\\`` separated) is agent configuration too;
  the target is not resolved further. Names are compared as stored: a name that differs by a trailing
  space or dot, a Windows short name or a stream suffix is not one of the seven.
- ``excluded_paths``: the operator's ``targets[].excluded_paths`` as written, plus every topmost agent
  configuration path found in the tree (topmost after casefold: ``.claude`` is covered by ``.Claude``).
  An operator entry is a pattern in the ownership-file syntax below, matched case-insensitively.
- ``excluded_dir_names`` and ``excluded_dirs``: a closed list of dependency, cache, build-output and
  other agents' workspace names (``EXCLUDED_DIR_NAMES``); an entry with such a name is excluded, and
  ``excluded_dirs`` lists the topmost ones found. ``.git`` is skipped and not listed. Other names are
  not excluded here; the operator's ``excluded_paths`` is the channel for them.
- ``languages``: ``{name: {files: n}}`` over regular files that are not excluded, by file extension
  (``EXTENSIONS``, casefolded). A file with another extension, or none, counts for no language.
- ``security_paths``: topmost paths (file or directory, symlinks included, excluded ones not) one of
  whose components contains a security keyword as a substring after casefold, plus the regular files
  and their directories matched by an ownership-file line that names an owner (any of them) containing a
  keyword (``CODEOWNERS``, ``.github/CODEOWNERS``, ``docs/CODEOWNERS``, ``.gitlab/CODEOWNERS``, each read
  only when it is a regular file with no symlink on its way). Those lines' patterns are also kept as written in
  ``security_owner_patterns`` so that paths added later are covered. Keywords are the policy's
  ``security_keywords`` when given, otherwise the fourteen of tohum/14. A substring rule over-includes
  (``author`` holds ``auth``); that is its cost, a narrower rule would let a security path through.
  File contents are not read for keywords.
- ``safety_paths`` (tohum/05 "Fiziksel güvenlik": code that drives, stops, alarms for or protects a physical
  process, its thresholds and escalation included): topmost paths found by the same component rule with
  ``SAFETY_KEYWORDS`` (a closed list of this module, the page's six kinds of process in English and Turkish
  plus control-system words: pump, aeration, oxygen, feeding, alarm and alert, emergency stop, shutdown,
  interlock, safety, SCADA, PLC, Modbus, actuator, valve, dosing, heater, chiller, VFD, automation, threshold,
  setpoint, escalation; the policy's keywords do not replace it), plus the paths matched by an ownership-file
  line naming an owner that holds such a word, plus the paths matched by the owner's optional
  ``targets[].safety_paths`` (patterns in the syntax below; an entry that matches nothing in the tree adds
  nothing). Every safety path is also in ``security_paths``, the one list the path gates read
  (``gate.diffguard``, ``loop.decide``, ``unit_verify``'s criterion 5), so nothing derived here is touched
  until K6 is live, formatters included. The owner's list and the keywords only widen the derivation. Out of
  scope: names in no list (a pump driver in ``motor.ts`` under ``devices/``: the owner's ``safety_paths`` is
  the channel) and file contents.
- ``test_path_rules``: the rules of ``TEST_RULES`` that match at least one non-excluded regular file,
  plus, as literal paths, every non-excluded ``.rs`` file with a ``#[test]`` attribute or a ``#[cfg(...)]``
  that names ``test`` (``INLINE_RUST_TEST``; inline tests). A test file outside these rules (say
  ``FooTest.java``, a Python doctest) is not recognised.
- ``unit_candidates``: the operator's ``unit_candidates`` in their order; when there are none, every
  non-excluded directory that holds a project manifest as a regular file (``PROJECT_MANIFESTS``: ``package.json``,
  or ``project.json``, which alone makes a directory an Nx project), in path order. Each is ``{path, eligible,
  reasons}``; eligible means none of: ``path_invalid`` (absolute, ``..``, empty), ``path_symlink``,
  ``not_a_directory``, ``excluded``, ``safety_path`` or ``security_path`` (the candidate is such a path or lies
  under one, ``guarded_by``; tohum/05: until K6 is live, which is never in this brain, unit selection leaves
  them out, stage 1's first unit included; a candidate that only holds one below it stays a candidate and the
  gates refuse touching that path), ``no_package_json`` (neither manifest is there as a regular file with no
  symlink on its way), ``package_json_unparsable`` (it is there and is not a JSON object),
  ``project_json_unparsable`` (the same of ``project.json`` when there is no ``package.json``; with both,
  ``package.json`` is the one judged here and ``profile.nx`` reads the other: whether the manifest gives
  commands is MF6's question, not this one's),
  ``no_version_file`` (no non-blank regular ``.nvmrc`` or ``.node-version``, nor a ``.tool-versions``
  with a ``node``/``nodejs`` line, in the unit directory or an ancestor up to the root), ``no_lockfile``
  (no ``npm-shrinkwrap.json`` or ``package-lock.json`` there; the nearest wins, shrinkwrap first),
  ``lock_not_regular`` (it is a symlink or not a file), ``lock_unparsable``, ``lock_v1_unsupported`` (no
  ``packages`` object),
  ``lock_without_integrity`` (an entry under ``node_modules/`` that is neither a link nor bundled has no
  ``integrity`` string; its value is judged by MF5). These are the static parts of asama-0/08 criteria 1 and 3; "small, well tested",
  the service-free tests, the lint tool, the fixable violation and 3/3 green are not judged here (MF6).

Pattern syntax (operator ``excluded_paths`` and ownership-file lines, GitHub's): a leading ``/`` or a
``/`` inside anchors the pattern at the root, otherwise it matches at any depth; ``*`` and ``?`` do not
cross ``/``, ``**`` does, ``[...]`` is a class; a trailing ``/`` is dropped, so the pattern also matches a
file of that name (wider, never narrower); a match on a directory covers everything below it. Out of
scope: ``!`` negation, escaped spaces, GitLab sections (a line starting with ``[`` or ``^[`` is skipped).

``check(derived, proposal)`` refuses (``ok`` false, every reason listed):

- a field ``derive`` does not produce (``field_not_derived:<name>``), so nothing unjudged gets through;
- ``agent_config``, ``security_keywords``, ``security_owner_patterns``, ``excluded_dir_names``,
  ``test_path_rules`` or the language names that are not equal to the derivation as casefolded sets, or
  ``security_paths`` and ``excluded_dirs`` that, reduced to their topmost paths, are not equal to it
  (``differs:<field>``): narrowing and widening are both refused;
- ``excluded_paths`` that leave out a derived entry (``narrowed:excluded_paths:<entry>``): the brain may
  only widen this list (tohum/14). An entry is kept only by the same pattern (casefolded, trailing ``/``
  dropped) or, when the entry is a glob-free anchored path, by a glob-free pattern that matches it; so
  ``/vendor`` does not keep ``vendor`` (any depth) and ``/legacy/*`` does not keep ``/legacy/*.js``;
- a unit recipe (``units``) whose ``path`` is not an eligible candidate, with a field outside the recipe
  of tohum/26c, with an input that is invalid or excluded, or (given the tree) missing or reached through
  a symlink, or with no input that covers its ``path``. An input that holds an excluded path below it is
  accepted: the exclusion still applies to that path; symlinks below an input are not judged here.

A field the proposal does not carry is not proposed, so it is not compared; only the derivation enters
the profile (tohum/14). Out of scope here: every other ``profile.json`` field (toolchains, commands,
graph, banned constructs, ...) and the recipe's own values (image, commands, limits: MF6).

The functions above are the Python API (``unit_verify`` uses them on a checked-out tree). The command
line is the seed's vector interface for group ``profile`` (tohum/29f, 29d), a separate, smaller rule set
over a tar archive (``derive_vector``, ``check_vector``); it does not run the rules above.

    python -m profile.derive derive TREE.tar.gz OPERATOR.json
    python -m profile.derive check TREE.tar.gz OPERATOR.json PROPOSAL.json

Run from ``referee/``, no stdin; the last (only) stdout line is one JSON object.

- Tree: a gzip tar read in memory; only member names are used, never contents. Directory members are
  ignored; a leading ``./`` is dropped. Any other member type (symlink, link, device, ...), an absolute
  name, or a name with an empty, ``.`` or ``..`` component makes the input unusable.
- ``OPERATOR.json``: an object with ``security_keywords``, ``excluded_paths`` and ``unit_candidates``,
  each a list of strings (other keys are ignored).
- Agent configuration: case-insensitively (``casefold``), a component ``.claude``, ``.vscode`` or
  ``.devcontainer``, or a last component ``CLAUDE.md``, ``AGENTS.md``, ``.mcp.json`` or ``.envrc``.
- Coverage: ``e`` covers ``p`` when ``p == e.rstrip('/')`` or ``p`` starts with ``e.rstrip('/') + '/'``;
  case-sensitive, as written (``src`` does not cover ``srcx/a.py``).
- A file is excluded when it is agent configuration or covered by an operator ``excluded_paths`` entry.
- ``languages``: from non-excluded files by extension, ``.py`` python, ``.js .mjs .cjs`` javascript,
  ``.ts .tsx .mts .cts`` typescript (extension compared as written), nothing else.
- ``security_paths``: non-excluded files whose lower-cased path holds a lower-cased keyword as a substring.
- ``excluded_paths``: the excluded files of the tree.
- ``unit_candidates``: the operator's entries in their order (as written), each kept when it is not
  itself excluded by the file rule above and covers at least one file of the tree, excluded or not.

``languages``, ``security_paths`` and ``excluded_paths`` are sorted in code point order. ``check`` reads a
proposal object carrying the same four lists (missing or of the wrong type: unusable) and prints
``accepted`` (true when ``reasons`` is empty) and the sorted ``reasons``, each at most once:
``differs:languages`` (sets differ), ``differs:unit_candidates`` (lists differ), ``narrows:security_paths``
and ``narrows:excluded_paths`` (a derived path is not in the proposal's list, compared as strings). A
proposal that only widens ``security_paths`` or ``excluded_paths`` is accepted: tohum/14's specific rule
allows widening (29f notes that its general sentence would refuse it; no vector judges this case).

Exit: ``derive`` 0, or 2 when an input is unusable; ``check`` 0 accepted, 1 refused, 2 unusable input.
On exit 2 the line is ``{"error": ...}`` (``check`` adds ``"accepted": false``), never a traceback; any
other exception is exit 2 at ``cli.run``'s boundary (``FAULT_LINE``, the type alone on stderr). Out of scope: signals and the interpreter being
killed.
"""

from __future__ import annotations

import functools
import json
import os
import posixpath
import re
import stat
import sys
import tarfile
from typing import Any

import cli

# What makes a directory a project, in the order a candidate's manifest is judged: npm's, then Nx's. The one list
# for unit candidates here, the project an input belongs to (``profile.fit``) and Nx's project bounds (``profile.nx``).
PROJECT_MANIFESTS = ("package.json", "project.json")
AGENT_CONFIG = (".claude", "CLAUDE.md", "AGENTS.md", ".mcp.json", ".vscode", ".envrc", ".devcontainer")
EXCLUDED_DIR_NAMES = (
    "node_modules", "bower_components", "jspm_packages", "dist", "coverage", ".nyc_output", ".next", ".nuxt",
    ".turbo", ".parcel-cache", ".cache", "__pycache__", ".venv", ".tox", ".mypy_cache", ".pytest_cache",
    ".cursor", ".codex", ".gemini", ".windsurf", ".continue", ".roo", ".aider.tags.cache.v3",
)
SECURITY_KEYWORDS = ("auth", "guard", "security", "session", "token", "secret", "crypto", "tenant",
                     "permission", "role", "policy", "payment", "billing", "pii")
SAFETY_KEYWORDS = ("pump", "pompa", "aerat", "havalandir", "oxygen", "oksijen", "feeding", "feeder", "besleme",
                   "yemleme", "alarm", "alert", "uyari", "emergency", "estop", "e-stop", "e_stop", "acil-dur",
                   "acil_dur", "acildur", "shutdown", "interlock", "failsafe", "fail-safe", "fail_safe", "safety",
                   "scada", "plc", "modbus", "actuator", "valve", "dosing", "heater", "chiller", "automation",
                   "threshold", "setpoint", "escalat", "vfd")
EXTENSIONS = {
    ".js": "javascript", ".mjs": "javascript", ".cjs": "javascript", ".jsx": "javascript",
    ".ts": "typescript", ".mts": "typescript", ".cts": "typescript", ".tsx": "typescript",
    ".py": "python", ".go": "go", ".rs": "rust", ".java": "java", ".kt": "kotlin", ".rb": "ruby",
    ".php": "php", ".cs": "csharp", ".c": "c", ".h": "c", ".cc": "cpp", ".cpp": "cpp", ".hpp": "cpp",
    ".swift": "swift", ".scala": "scala", ".sh": "shell", ".sql": "sql",
}
TEST_RULES = ("**/test/**", "**/tests/**", "**/__tests__/**", "**/spec/**", "**/*.test.*", "**/*.spec.*",
              "**/test_*.py", "**/*_test.py", "**/*_test.go")
INLINE_RUST_TEST = re.compile(rb"#\s*\[\s*(?:test\s*\]|cfg\s*\([^\]]*\btest\b)")
OWNER_FILES = ("CODEOWNERS", ".github/CODEOWNERS", "docs/CODEOWNERS", ".gitlab/CODEOWNERS")
RECIPE_FIELDS = ("unit_id", "path", "inputs", "toolchain", "env_image", "lockfiles", "install_scripts_required",
                 "lint_cmd", "test_cmd", "affected_test_cmd", "services", "limits")
SET_FIELDS = ("agent_config", "security_keywords", "security_paths", "security_owner_patterns",
              "safety_keywords", "safety_paths", "excluded_dir_names", "excluded_dirs", "test_path_rules")
PROPOSABLE = SET_FIELDS + ("languages", "excluded_paths", "units")

_AGENT = frozenset(n.casefold() for n in AGENT_CONFIG)
AGENT_CONFIG_DIRS = frozenset(n.casefold() for n in (".claude", ".vscode", ".devcontainer"))
AGENT_CONFIG_FILES = frozenset(n.casefold() for n in AGENT_CONFIG) - AGENT_CONFIG_DIRS
_EXCL_DIR = frozenset(n.casefold() for n in EXCLUDED_DIR_NAMES)


class DeriveError(ValueError):
    """The tree or the target cannot be derived; no profile is returned."""


# ---------------------------------------------------------------- patterns and paths

@functools.lru_cache(maxsize=None)
def pattern_regex(pattern: str) -> re.Pattern:
    """Compile an ownership-file / excluded-path pattern; it matches a path or anything below one."""
    p = pattern.casefold()
    anchored = p.startswith("/")
    p = p.strip("/")
    if not p:
        raise DeriveError("empty pattern %r" % pattern)
    anchored = anchored or "/" in p
    out, i = [], 0
    while i < len(p):
        if p.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif p.startswith("**", i):
            out.append(".*")
            i += 2
        elif p[i] == "*":
            out.append("[^/]*")
            i += 1
        elif p[i] == "?":
            out.append("[^/]")
            i += 1
        elif p[i] == "[" and "]" in p[i + 2:]:
            end = p.index("]", i + 2)
            body = p[i + 1:end]
            if body.startswith("!"):
                body = "^" + body[1:]
            out.append("[" + body.replace("\\", "\\\\").replace("/", "") + "]")
            i = end + 1
        else:
            out.append(re.escape(p[i]))
            i += 1
    try:
        return re.compile(("" if anchored else "(?:.*/)?") + "".join(out) + "(?:/.*)?\\Z", re.DOTALL)
    except re.error as exc:
        raise DeriveError("invalid pattern %r: %s" % (pattern, cli.cause(exc))) from None


def pattern_matches(pattern: str, path: str) -> bool:
    return pattern_regex(pattern).match(path.casefold()) is not None


def norm_path(path: Any) -> str | None:
    """A relative ``/`` path inside the tree, normalised; None when absolute, empty, or leaving the tree."""
    if not isinstance(path, str) or not path or path.startswith("/") or "\\" in path or "\x00" in path:
        return None
    norm = posixpath.normpath(path)
    if norm == ".." or norm.startswith("../"):
        return None
    return norm


def covers(entry: str, path: str) -> bool:
    entry, path = entry.casefold(), path.casefold()
    return entry == "." or path == entry or path.startswith(entry + "/")


def covers_as_written(entry: str, path: str) -> bool:
    """tohum/29f coverage, on paths as written: ``path == entry.rstrip('/')`` or ``path`` starts with it
    plus ``/``; case-sensitive, no normalisation (``covers`` above is the derivation's folded form)."""
    e = entry.rstrip("/")
    return path == e or path.startswith(e + "/")


def agent_config_as_written(path: str) -> bool:
    """tohum/29f agent configuration on a path as written (trailing ``/`` ignored): case-insensitively, some
    component is ``.claude``, ``.vscode`` or ``.devcontainer``, or the last one is ``CLAUDE.md``,
    ``AGENTS.md``, ``.mcp.json`` or ``.envrc``."""
    parts = path.rstrip("/").split("/")
    return (any(p.casefold() in AGENT_CONFIG_DIRS for p in parts)
            or parts[-1].casefold() in AGENT_CONFIG_FILES)


def minimal(paths) -> list[str]:
    """Drop every path that an other path of the list covers."""
    out: list[str] = []
    for p in sorted(set(paths), key=lambda s: (s.casefold().count("/"), s)):
        if not any(covers(q, p) for q in out):
            out.append(p)
    return sorted(out)


def is_agent_config(path: str) -> bool:
    return any(part.casefold() in _AGENT for part in path.split("/"))


def excluded(derived: dict, path: str) -> str | None:
    """Why ``path`` is excluded under ``derived`` (agent_config, excluded_dir, excluded_path), or None."""
    parts = [part.casefold() for part in path.split("/")]
    if any(part in _AGENT for part in parts):
        return "agent_config"
    if any(part in _EXCL_DIR for part in parts):
        return "excluded_dir"
    if any(pattern_matches(p, path) for p in derived.get("excluded_paths", [])):
        return "excluded_path"
    return None


# ---------------------------------------------------------------- derive

def _keywords(policy: dict | None) -> list[str]:
    if policy is None:
        return list(SECURITY_KEYWORDS)
    constitutional = policy.get("constitutional") if isinstance(policy, dict) else None
    words = constitutional.get("security_keywords") if isinstance(constitutional, dict) else None
    if not (isinstance(words, list) and words and all(isinstance(w, str) and w for w in words)):
        raise DeriveError("policy.constitutional.security_keywords is not a list of words")
    return [w.casefold() for w in words]


def _target(target: dict | None) -> tuple[list[str], list[str], list[str]]:
    """The operator's ``excluded_paths``, ``unit_candidates`` and the owner's optional ``safety_paths``."""
    if target is None:
        return [], [], []
    if not isinstance(target, dict):
        raise DeriveError("target must be an object")
    lists = []
    for key in ("excluded_paths", "unit_candidates", "safety_paths"):
        value = target.get(key, [])
        if not (isinstance(value, list) and all(isinstance(v, str) and v.strip("/") for v in value)):
            raise DeriveError("target.%s must be a list of non-empty strings" % key)
        lists.append(value)
    for p in lists[0]:
        pattern_regex(p)
    return lists[0], lists[1], lists[2]


def _walk(root: str):
    """Yield (relative path, lstat) for every entry, depth first in name order; never follows symlinks.

    The caller sends False into the generator to keep it out of a directory it has just been given.
    The walk keeps its own stack, so tree depth is bounded by the file system, not by Python recursion.
    """
    def listing(rel: str):
        full = os.path.join(root, rel) if rel else root
        try:
            names = sorted(os.listdir(full))
        except OSError as exc:
            raise DeriveError("cannot list %s: %s" % (rel or ".", cli.cause(exc))) from None
        return iter([posixpath.join(rel, n) if rel else n for n in names if n != ".git"])

    stack = [listing("")]
    while stack:
        child = next(stack[-1], None)
        if child is None:
            stack.pop()
            continue
        try:
            st = os.lstat(os.path.join(root, child))
        except OSError as exc:
            raise DeriveError("cannot stat %s: %s" % (child, cli.cause(exc))) from None
        descend = yield child, st
        if descend is not False and stat.S_ISDIR(st.st_mode):
            stack.append(listing(child))


def derive(tree: str, target: dict | None = None, policy: dict | None = None) -> dict:
    if not os.path.isdir(tree) or os.path.islink(tree):
        raise DeriveError("tree is not a directory")
    op_excluded, op_candidates, op_safety = _target(target)
    keywords = _keywords(policy)
    agent_found, excl_dirs, security, safety, files, project_dirs = [], [], [], [], [], set()
    languages: dict[str, int] = {}

    walker = _walk(tree)
    send = None
    while True:
        try:
            rel, st = walker.send(send)
        except StopIteration:
            break
        name = rel.rsplit("/", 1)[-1].casefold()
        send = None
        if name in _AGENT or (stat.S_ISLNK(st.st_mode) and _link_to_agent_config(tree, rel)):
            agent_found.append(rel)
            send = False
            continue
        if name in _EXCL_DIR:
            excl_dirs.append(rel)
            send = False
            continue
        if any(pattern_matches(p, rel) for p in op_excluded):
            send = False
            continue
        if any(k in name for k in keywords):
            security.append(rel)
        if any(k in name for k in SAFETY_KEYWORDS):
            safety.append(rel)
        if stat.S_ISREG(st.st_mode):
            files.append(rel)
            lang = EXTENSIONS.get(posixpath.splitext(name)[1])
            if lang:
                languages[lang] = languages.get(lang, 0) + 1
            if name in PROJECT_MANIFESTS:
                project_dirs.add(posixpath.dirname(rel) or ".")

    owner_patterns = _owner_patterns(tree, keywords)
    safety_patterns = _owner_patterns(tree, SAFETY_KEYWORDS) + op_safety
    all_paths = _all_paths(files)
    for patterns, found in ((owner_patterns, security), (safety_patterns, safety)):
        for pattern in patterns:
            rx = pattern_regex(pattern)
            found.extend(p for p in all_paths if rx.match(p.casefold()))

    derived = {
        "agent_config": list(AGENT_CONFIG),
        "excluded_dir_names": list(EXCLUDED_DIR_NAMES),
        "excluded_dirs": minimal(excl_dirs),
        "excluded_paths": sorted(set(op_excluded) | set(minimal(agent_found))),
        "languages": {k: {"files": v} for k, v in sorted(languages.items())},
        "safety_keywords": list(SAFETY_KEYWORDS),
        "safety_paths": minimal(safety),
        "security_keywords": keywords,
        "security_owner_patterns": owner_patterns,
        "security_paths": minimal(security + safety),
        "test_path_rules": _test_rules(tree, files),
    }
    candidates = op_candidates or sorted(project_dirs)
    derived["unit_candidates"] = [_candidate(tree, derived, c) for c in candidates]
    return derived


def _link_to_agent_config(tree: str, rel: str) -> bool:
    """A symlink whose target text names agent configuration in any component (not resolved further)."""
    try:
        target = os.readlink(os.path.join(tree, rel))
    except OSError:
        return False
    return any(part.casefold() in _AGENT for part in re.split(r"[/\\]", target))


def _all_paths(files: list[str]) -> list[str]:
    """The files and every directory above them."""
    out = set(files)
    for f in files:
        d = posixpath.dirname(f)
        while d:
            out.add(d)
            d = posixpath.dirname(d)
    return sorted(out)


def _owner_patterns(tree: str, keywords: list[str]) -> list[str]:
    patterns: list[str] = []
    for owner_file in OWNER_FILES:
        text = _read_regular(tree, owner_file)
        if text is None:
            continue
        for line in text.decode("utf-8", "replace").splitlines():
            line = line.split("#", 1)[0].strip()
            if not line or line.startswith(("[", "^[")):
                continue
            pattern, *owners = line.split()
            if any(k in owner.casefold() for owner in owners for k in keywords):
                pattern_regex(pattern)
                patterns.append(pattern)
    return sorted(set(patterns))


def _test_rules(tree: str, files: list[str]) -> list[str]:
    rules = [r for r in TEST_RULES if any(pattern_matches(r, f) for f in files)]
    for f in files:
        if f.casefold().endswith(".rs"):
            data = _read_regular(tree, f)
            if data is not None and INLINE_RUST_TEST.search(data):
                rules.append(f)
    return sorted(rules)


def _read_regular(tree: str, rel: str) -> bytes | None:
    """The bytes of ``rel`` when it and every directory above it are real (no symlink); else None."""
    cur = tree
    for part in rel.split("/"):
        cur = os.path.join(cur, part)
        try:
            st = os.lstat(cur)
        except OSError:
            return None
        if stat.S_ISLNK(st.st_mode):
            return None
    if not stat.S_ISREG(st.st_mode):
        return None
    with open(cur, "rb") as fh:
        return fh.read()


def _real_dir(tree: str, rel: str) -> str | None:
    """'' when ``rel`` is a real directory, else the reason (path_symlink, not_a_directory)."""
    if rel == ".":
        return ""
    cur = tree
    for part in rel.split("/"):
        cur = os.path.join(cur, part)
        try:
            st = os.lstat(cur)
        except OSError:
            return "not_a_directory"
        if stat.S_ISLNK(st.st_mode):
            return "path_symlink"
    return "" if stat.S_ISDIR(st.st_mode) else "not_a_directory"


def _ancestors(rel: str) -> list[str]:
    out = [rel]
    while rel != ".":
        rel = posixpath.dirname(rel) or "."
        out.append(rel)
    return out


def _json(tree: str, rel: str) -> tuple[bool, Any]:
    data = _read_regular(tree, rel)
    if data is None:
        return False, None
    try:
        return True, cli.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, RecursionError):
        return True, None


def _candidate(tree: str, derived: dict, raw: str) -> dict:
    path = norm_path(raw)
    if path is None:
        return {"path": raw, "eligible": False, "reasons": ["path_invalid"]}
    reasons = []
    where = _real_dir(tree, path)
    if where:
        reasons.append(where)
    if path != "." and excluded(derived, path):
        reasons.append("excluded")
    guarded = guarded_by(derived, path)
    if guarded:
        reasons.append(guarded)
    if not reasons:
        for name in PROJECT_MANIFESTS:
            present, manifest = _json(tree, posixpath.join(path, name))
            if present:
                if not isinstance(manifest, dict):
                    reasons.append(name.replace(".", "_") + "_unparsable")
                break
        else:
            reasons.append("no_package_json")
        if not any(_has_version_file(tree, d) for d in _ancestors(path)):
            reasons.append("no_version_file")
        reasons.extend(_lock_reasons(tree, path))
    return {"path": path, "eligible": not reasons, "reasons": reasons}


def guarded_by(derived: dict, path: str) -> str | None:
    """``safety_path`` when a ``safety_paths`` entry covers ``path`` (equal to it or above it), else
    ``security_path`` when a ``security_paths`` entry does, else None. A path that only holds such a path below
    it is not covered (tohum/05: the unit that is one, or lies under one)."""
    for field in ("safety_paths", "security_paths"):
        if any(covers(entry, path) for entry in derived.get(field, [])):
            return field[:-1]
    return None


def _has_version_file(tree: str, d: str) -> bool:
    for name in (".nvmrc", ".node-version"):
        data = _read_regular(tree, posixpath.join(d, name))
        if data is not None and data.strip():
            return True
    data = _read_regular(tree, posixpath.join(d, ".tool-versions"))
    if data is None:
        return False
    return any(line.split()[:1] in (["node"], ["nodejs"]) and len(line.split()) > 1
               for line in data.decode("utf-8", "replace").splitlines())


def nearest_lock(tree: str, path: str) -> str | None:
    """The lock nearest to ``path``: walking up to the root, in one directory ``npm-shrinkwrap.json`` before
    ``package-lock.json``, the first name that exists (of any kind); ``None`` when there is none."""
    for d in _ancestors(path):
        for name in ("npm-shrinkwrap.json", "package-lock.json"):
            rel = name if d == "." else posixpath.join(d, name)
            if os.path.lexists(os.path.join(tree, rel)):
                return rel
    return None


def _lock_reasons(tree: str, path: str) -> list[str]:
    rel = nearest_lock(tree, path)
    if rel is None:
        return ["no_lockfile"]
    present, lock = _json(tree, rel)
    if not present:
        return ["lock_not_regular"]
    if not isinstance(lock, dict):
        return ["lock_unparsable"]
    packages = lock.get("packages")
    if not isinstance(packages, dict):
        return ["lock_v1_unsupported"]
    for key, entry in packages.items():
        if "node_modules/" not in key:
            continue
        if not isinstance(entry, dict):
            return ["lock_unparsable"]
        if entry.get("link") is True or entry.get("inBundle") is True:
            continue
        integrity = entry.get("integrity")
        if not (isinstance(integrity, str) and integrity):
            return ["lock_without_integrity"]
    return []


# ---------------------------------------------------------------- check

def _str_list(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(v, str) for v in value)


def check(derived: dict, proposal: Any, tree: str | None = None) -> dict:
    """Judge a proposal (profile fields and/or ``units``) against ``derived``; see the module docstring.

    With ``tree`` (the tree ``derived`` came from), recipe inputs must also exist there with no symlink
    on their way; the command line always passes it.
    """
    if isinstance(proposal, list):
        proposal = {"units": proposal}
    if not isinstance(proposal, dict):
        return {"ok": False, "reasons": ["malformed:proposal"]}
    reasons: list[str] = []
    for field in sorted(proposal):
        if field not in PROPOSABLE:
            reasons.append("field_not_derived:%s" % field)
    for field in SET_FIELDS:
        if field not in proposal:
            continue
        value = proposal[field]
        if not _str_list(value):
            reasons.append("malformed:%s" % field)
            continue
        if field in ("security_paths", "excluded_dirs"):
            same = minimal(value) == derived[field]
        else:
            same = {v.casefold() for v in value} == {v.casefold() for v in derived[field]}
        if not same:
            reasons.append("differs:%s" % field)
    if "languages" in proposal:
        value = proposal["languages"]
        names = list(value) if isinstance(value, (dict, list)) else None
        if names is None or not all(isinstance(n, str) for n in names):
            reasons.append("malformed:languages")
        elif set(names) != set(derived["languages"]):
            reasons.append("differs:languages")
    if "excluded_paths" in proposal:
        value = proposal["excluded_paths"]
        if not _str_list(value):
            reasons.append("malformed:excluded_paths")
        else:
            for entry in derived["excluded_paths"]:
                if not any(_pattern_covers(v, entry) for v in value):
                    reasons.append("narrowed:excluded_paths:%s" % entry)
    if "units" in proposal:
        reasons.extend(_check_units(derived, proposal["units"], tree))
    return {"ok": not reasons, "reasons": reasons}


def _pattern_covers(wide: str, entry: str) -> bool:
    """True when pattern ``wide`` matches at least every path pattern ``entry`` matches.

    Exact for the same pattern (casefolded, trailing ``/`` dropped). Otherwise only for glob-free
    patterns where ``entry`` is anchored (it names one root path): ``wide`` then covers it when it
    matches that path. Any other pair is judged not covered, so the check refuses rather than guesses.
    """
    w, e = wide.rstrip("/").casefold(), entry.rstrip("/").casefold()
    if w == e:
        return True
    if any(c in w + e for c in "*?[") or not ("/" in e.lstrip("/") or e.startswith("/")):
        return False
    path = norm_path(e.lstrip("/"))
    return bool(w.strip("/")) and path is not None and pattern_regex(wide).match(path) is not None


def _input_where(tree: str, rel: str) -> str:
    """'' when ``rel`` exists in ``tree`` with no symlink on its way, else input_missing or input_symlink."""
    if rel == ".":
        return ""
    cur = tree
    for part in rel.split("/"):
        cur = os.path.join(cur, part)
        try:
            st = os.lstat(cur)
        except OSError:
            return "input_missing"
        if stat.S_ISLNK(st.st_mode):
            return "input_symlink"
    return ""


def _check_units(derived: dict, units: Any, tree: str | None) -> list[str]:
    if not isinstance(units, list) or not units:
        return ["malformed:units"]
    eligible = {c["path"]: c["eligible"] for c in derived["unit_candidates"]}
    reasons = []
    for i, unit in enumerate(units):
        if not isinstance(unit, dict):
            reasons.append("malformed:units[%d]" % i)
            continue
        for field in sorted(unit):
            if field not in RECIPE_FIELDS:
                reasons.append("units[%d]:field_not_in_recipe:%s" % (i, field))
        path = norm_path(unit.get("path"))
        if path is None:
            reasons.append("units[%d]:path_invalid" % i)
        elif path not in eligible:
            reasons.append("units[%d]:unit_not_candidate:%s" % (i, path))
        elif not eligible[path]:
            reasons.append("units[%d]:unit_not_eligible:%s" % (i, path))
        inputs = unit.get("inputs")
        if not (_str_list(inputs) and inputs):
            reasons.append("units[%d]:malformed:inputs" % i)
            continue
        normed = []
        for raw in inputs:
            p = norm_path(raw)
            if p is None:
                reasons.append("units[%d]:input_invalid:%s" % (i, raw))
            elif p != "." and excluded(derived, p):
                reasons.append("units[%d]:input_excluded:%s" % (i, p))
            elif tree is not None and _input_where(tree, p):
                reasons.append("units[%d]:%s:%s" % (i, _input_where(tree, p), p))
            else:
                normed.append(p)
        if path is not None and not any(covers(p, path) for p in normed):
            reasons.append("units[%d]:inputs_miss_unit_path" % i)
    return reasons


# ---------------------------------------------------------------- vector interface (tohum/29f, ``profile``)

VECTOR_EXTENSIONS = {".py": "python", ".js": "javascript", ".mjs": "javascript", ".cjs": "javascript",
                     ".ts": "typescript", ".tsx": "typescript", ".mts": "typescript", ".cts": "typescript"}
_AGENT_ANY = frozenset(n.casefold() for n in (".claude", ".vscode", ".devcontainer"))
_AGENT_LAST = frozenset(n.casefold() for n in ("CLAUDE.md", "AGENTS.md", ".mcp.json", ".envrc"))
VECTOR_FIELDS = ("languages", "security_paths", "excluded_paths", "unit_candidates")


def vector_agent_config(path: str) -> bool:
    """tohum/29f: a component .claude/.vscode/.devcontainer, or a last component CLAUDE.md, ..., any case."""
    parts = [p.casefold() for p in path.split("/")]
    return any(p in _AGENT_ANY for p in parts) or parts[-1] in _AGENT_LAST


def vector_covers(entry: str, path: str) -> bool:
    """tohum/29f coverage: case-sensitive, as written."""
    e = entry.rstrip("/")
    return path == e or path.startswith(e + "/")


def read_tree(path: str) -> list[str]:
    """The file names of a gzip tar (sorted, unique); directory members are ignored."""
    names = set()
    try:
        with tarfile.open(path, "r:gz") as tar:
            for member in tar:
                name = member.name
                while name.startswith("./"):
                    name = name[2:]
                if member.isdir():
                    continue
                if not member.isfile():
                    raise DeriveError("tree member %r is not a file or directory" % member.name)
                parts = name.split("/")
                if name.startswith("/") or any(p in ("", ".", "..") for p in parts):
                    raise DeriveError("tree member %r is not a relative POSIX path" % member.name)
                names.add(name)
    except cli.ARCHIVE_ERRORS as exc:
        raise DeriveError("tree is not a readable gzip tar: %s" % cli.cause(exc)) from None
    return sorted(names)


def read_operator(path: str) -> dict:
    op = _load(path)
    if not isinstance(op, dict):
        raise DeriveError("operator.json must be an object")
    for key in ("security_keywords", "excluded_paths", "unit_candidates"):
        if not _str_list(op.get(key)):
            raise DeriveError("operator.%s must be a list of strings" % key)
    return op


def derive_vector(files: list[str], operator: dict) -> dict:
    def is_excluded(p: str) -> bool:
        return vector_agent_config(p) or any(vector_covers(e, p) for e in operator["excluded_paths"])

    keywords = [k.lower() for k in operator["security_keywords"]]
    excluded_files = sorted(f for f in files if is_excluded(f))
    kept = sorted(f for f in files if not is_excluded(f))
    languages = {VECTOR_EXTENSIONS[posixpath.splitext(f)[1]] for f in kept
                 if posixpath.splitext(f)[1] in VECTOR_EXTENSIONS}
    return {
        "languages": sorted(languages),
        "security_paths": [f for f in kept if any(k in f.lower() for k in keywords)],
        "excluded_paths": excluded_files,
        "unit_candidates": [c for c in operator["unit_candidates"]
                            if not is_excluded(c.rstrip("/")) and any(vector_covers(c, f) for f in files)],
    }


def check_vector(derived: dict, proposal: Any) -> dict:
    if not isinstance(proposal, dict):
        raise DeriveError("proposal must be an object")
    for key in VECTOR_FIELDS:
        if not _str_list(proposal.get(key)):
            raise DeriveError("proposal.%s must be a list of strings" % key)
    reasons = []
    if set(proposal["languages"]) != set(derived["languages"]):
        reasons.append("differs:languages")
    if proposal["unit_candidates"] != derived["unit_candidates"]:
        reasons.append("differs:unit_candidates")
    for key in ("security_paths", "excluded_paths"):
        if not set(derived[key]) <= set(proposal[key]):
            reasons.append("narrows:%s" % key)
    return {"accepted": not reasons, "reasons": sorted(reasons)}


# ---------------------------------------------------------------- command line

def _emit(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj, sort_keys=True, separators=(",", ":")) + "\n")


def _load(path: str) -> Any:
    try:
        with open(path, encoding="utf-8") as fh:
            return cli.load(fh)
    except RecursionError:
        raise DeriveError("%s: JSON nested too deeply" % path) from None


USAGE = ("usage: python -m profile.derive derive TREE.tar.gz OPERATOR.json"
         " | check TREE.tar.gz OPERATOR.json PROPOSAL.json")


def main(argv: list[str]) -> int:
    fail = {"accepted": False} if argv[:1] == ["check"] else {}
    try:
        if len(argv) == 3 and argv[0] == "derive":
            _emit(derive_vector(read_tree(argv[1]), read_operator(argv[2])))
            return 0
        if len(argv) == 4 and argv[0] == "check":
            derived = derive_vector(read_tree(argv[1]), read_operator(argv[2]))
            report = check_vector(derived, _load(argv[3]))
            _emit(report)
            return 0 if report["accepted"] else 1
        _emit(dict(fail, error=USAGE))
        return 2
    except (DeriveError, ValueError, OSError) as exc:
        _emit(dict(fail, error="unusable input: %s" % cli.cause(exc)))
        return 2


def FAULT_LINE(argv: list[str]) -> dict:  # noqa: N802 - cli.run's fault line, by command
    return dict({"accepted": False} if argv[:1] == ["check"] else {}, error="internal error")


if __name__ == "__main__":
    sys.exit(cli.run(main, sys.argv[1:], FAULT_LINE))
