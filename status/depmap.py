"""``status.depmap``: the dependency drawings, what depends on what, generated from code and never written by hand.

Owner's rule (2026-10-30): a drawing a human can read, of the target and of the brain, generated from the verified
map, kept in the brain repository and regenerated in the push that changes the code it maps; a stale drawing is a
stale document. The brain's drawing is ``docs/map/brain.md`` and test 42 regenerates it from ``referee/`` and fails
on any byte of difference; the target's is ``docs/map/target.md``, made from a read-only checkout of the target
and carrying the target commit it was made from (the referee's sandbox holds no target, so it is regenerated in
the session that reads the target, not by a test).

**The brain** (``brain_map``), over the Python files under a root (``referee/``), ``tests/``, hidden directories and
``__pycache__`` not read:

- a module is a ``.py`` file, named by its path (``gate/secrets.py`` is ``gate.secrets``, ``gate/__init__.py`` is
  ``gate``, ``activate.py`` is ``activate``);
- an arrow A -> B means A's source holds an ``import`` statement, anywhere in it (inside a function too), that names
  B: ``import x.y.z`` and ``from x.y import z`` name the deepest known module among ``x.y.z``, ``x.y``, ``x``
  (``from x.y import z`` names ``x.y.z`` when that is a module); a relative ``from .`` is resolved against A's
  package; an import naming no module under the root (the standard library, a third party), or A itself, draws
  nothing;
- a live root is a module that a workflow file under ``ROOT/.github/workflows/`` starts with ``python -m`` or
  ``python3 -m``; a module started there that is not under the root is listed as external, not drawn;
- live means reachable from a live root by arrows, and a package (``__init__.py``) holding a live module is live,
  since Python runs it first; no arrow is drawn for that. An import is not a call: a live module may still be one that
  nothing calls (a mechanism imported but not wired). Off the live path means not reachable at all.
- the register of the off-live (``REGISTER``, ``ROOT/status/off_live.json``; a missing file is an empty register):
  a JSON object naming each module off the live path with ``{"kind": ..., "why": ...}``. ``kind`` is ``unwired``
  (a mechanism the cycle needs that no job reaches yet) or ``session_tool`` (run by a person or a session, never
  by the loop); ``why`` is a non-empty string. An empty package (an ``__init__.py`` with no statement but a
  docstring, listed in ``empty_packages``) is off the live path exactly when none of its modules is live, so it is
  not named; one with code is a module like any other. ``register_problems``, sorted and unique:
  ``register_unreadable`` (not UTF-8 JSON whose top is an object; nothing else is checked), ``entry_invalid:<m>``
  (not an object of exactly those two keys, a kind outside the two, a ``why`` that is not a string or is only
  blanks), ``named_unknown:<m>`` (no such module, or an empty package), ``named_but_live:<m>`` (named but live: the
  push that wires a module removes its entry) and ``off_live_unnamed:<m>`` (off the live path, not an empty
  package, not named). So a module nobody wires is named with its reason, and a wired one leaves the list. Not
  checked, stated: whether a ``why`` is true (a person reads it) and whether an ``unwired`` module is ever wired.
- Not read, stated: modules imported by a name built at run time (``importlib``), modules started as a
  subprocess (``python -m`` inside Python code), a file that does not parse (listed, no arrows).

**The target** (``target_map``), over a checkout's files (``profile.jsimports.walk``):

- a project is a directory named by one of three manifests read at the root only: the npm ``workspaces`` of the
  root ``package.json`` (an array, or ``{packages: [...]}``; each pattern matched segment by segment with ``*`` and
  ``?`` inside a segment, ``**`` any number of segments, a leading ``!`` excluding; a match is a directory holding
  a ``package.json``; its name the manifest's ``name``, else the directory); every Nx ``project.json`` (its
  ``name``, else the directory's last segment); every ``Cargo.toml`` below the root whose ``[package]`` is a table
  (a workspace member, an excluded package, a nested workspace's root and a test fixture alike; its
  ``[package].name``, else the directory's last segment; a manifest with only ``[workspace]`` is no project);
  every ``pyproject.toml`` below the root (its
  ``[project].name``, else the directory's last segment). The root directory itself is never a project. A
  directory named by several manifests is one project with every kind. A directory below the root holding a
  TypeScript configuration (a file named by ``jsimports.TSCONFIG``: ``tsconfig.json``, ``tsconfig.lib.json``, ...;
  ``tsc -p`` builds the files it includes as one program) that no project of those manifests holds is a project
  of kind ``tsconfig``, named by its directory: a library a root tsconfig alias reaches, or a test suite, with no
  ``package.json`` or ``project.json``; decided against the manifests' projects only, so nested ones are both
  projects, one inside a ``path`` project below is one too (a TypeScript program inside a directory Python puts
  on ``sys.path``) and one inside a manifest's project is none (whether its ``include`` covers the files is not read: the
  deepest project owns a file, as for every kind). A directory a Python file puts on
  ``sys.path`` (``profile.pypath``: only what it resolves, present in the checkout, not the root) that no project
  of those manifests holds is a project of kind ``path``, named by its directory; this is decided against the
  manifests' projects only, so two nested inserted directories are both projects. Then a directory an absolute
  import of a ``.py`` file reaches through a directory the same file inserts (``sys_path_target``: a package or a
  namespace package, not a module file) that no project holds is a project of kind ``path`` too, named by its
  directory: only the root's can be, as every other inserted directory present is a box or inside a project by
  then, so this is the top-level package ``t`` of ``import t`` after ``sys.path.insert(0, <the root>)``; a
  module file ``t.py`` at the root reached so makes no box. Last, a directory below the root holding a Dockerfile
  (``profile.docker.DOCKERFILE_NAMES``) that no box of any kind above holds is a project of kind ``docker``, named
  by its directory: an image built from it (several Dockerfiles in one directory are one box). After it, a directory
  below the root holding a kustomization file (``profile.kustomize.KUSTOMIZATION_NAMES``) that no box holds is a
  project of kind ``kustomize``, named by its directory;
- a file belongs to the project with the deepest directory holding it;
- an arrow A -> B, labelled with how it was found: ``npm`` (a key of ``dependencies``, ``devDependencies``,
  ``peerDependencies`` or ``optionalDependencies`` of A's ``package.json`` is B's npm name), ``cargo`` (a dependency
  of A's ``Cargo.toml``, in ``[dependencies]``, ``[dev-dependencies]``, ``[build-dependencies]`` or a
  ``[target.*]`` one, that Cargo resolves to B's directory: by its ``path``, through A's workspace root's
  ``[workspace.dependencies]`` when it is ``workspace = true``, or by that root's ``[patch.crates-io]`` for a
  crates.io dependency; the root as Cargo finds it, ``cargo_workspace``, and the rules in ``cargo_dep_paths``), ``import`` (a JS/TS file of A, one of ``jsimports.SOURCE_EXTENSIONS``,
  holds an import specifier resolving into B: a relative one by its path, a bare one equal to B's npm name or starting
  with it and ``/``, or one matching an alias of the root tsconfig (``jsimports.aliases``)),
  ``python`` (a ``.py`` file of A, read by ``import_statements``, imports by an absolute name whose first part is
  a top-level package of B: a directory ``B/<name>/`` or ``B/src/<name>/`` holding ``__init__.py``; the first
  project in path order wins a name two projects hold; a relative import is counted, never drawn), ``sys.path``
  (a ``.py`` file of A imports by an absolute name whose first part ``t`` reaches, by ``sys_path_target``, a
  package ``D/t/``, a module ``D/t.py`` or a directory ``D/t`` for a directory ``D`` the same file puts on
  ``sys.path``, and B holds that path; tried before the ``python`` rule, so that import draws no ``python``
  arrow), ``docker`` (a Dockerfile of A that a compose file or a GitHub Actions step builds copies a path B
  holds, or a directory holding B, from its build context: ``docker_edges``, ``profile.docker`` and
  ``profile.ghactions``), ``kustomize`` (a kustomization file of A names a path, resolved from its directory, that B
  holds: ``kustomize_edges`` and ``profile.kustomize``);
- an import specifier is one ``jsimports.specifiers`` reads (as written: a commented-out import counts, an
  import whose specifier is not a string literal does not);
- not read, stated: a ``sys.path`` insertion reaching other files (a ``conftest.py``'s reaching its tests, a
  module's reaching its importers), the directory of a script run directly (Python's ``sys.path[0]``), ``PYTHONPATH``
  and pytest's ``pythonpath``, Python's order between an inserted directory and the others (the inserted ones are
  taken in source order, ``insert`` and ``append`` alike), a module of another kind (``.pyc``, an extension
  module); nested npm workspaces (a ``package.json`` workspace below the root), Rust ``use`` lines (the
  manifest is Cargo's own list), a Cargo target file outside its package's directory (``[[test]] path =
  "../x.rs"``: the file belongs to the project holding it), a Python package that is a single module file, Go's and every other
  language's references (imports, Terraform module sources, SQL table names, a Dockerfile no build names;
  counted by extension or name in ``coverage.unread_code_files``), a Dockerfile's build context named anywhere but
  a compose file or a ``docker/build-push-action`` step (a ``docker build`` line, a Makefile, a script), what
  ``profile.docker``, ``profile.ghactions``, ``profile.kustomize`` and ``profile.yamlblock`` state they do not
  read, Helm charts, a Kubernetes manifest's references (images, config maps, services) and a manifest no
  kustomization names, whether a resolved
  path exists,
  project references in ``tsconfig``;
- ``coverage`` says how much of the checkout this map holds: files, JS/TS and Python files read, each also in no
  project, specifiers by outcome (an import in a file of no project, or into no project, is ``outside_projects``),
  manifests that could not be parsed, code files of languages not read (``file_kind``'s ``code``: by name,
  ``CODE_FILE_NAMES``, or by extension, ``OTHER_CODE_EXTENSIONS``), in all and in no project; ``unclassified_files``:
  the files whose extension no list states (not read, not code, not ``NOT_CODE_EXTENSIONS``) per extension, and
  ``files_without_extension``, each a count and the first three paths, so a language or format the map does not
  know shows as a number (whether such a file is code is not decided; a file in a skipped directory is not
  seen); and ``unread_manifests``: the dependency manifests found whose dependencies draw no
  arrow, by the first pattern of ``MANIFESTS_NOT_READ`` a file's name matches, plus every ``package.json`` below
  the root outside the npm workspace projects (an Nx project's own ``package.json`` too); a count and the first
  three paths each, and ``sys_path``: insertion calls, directories resolved (``missing``: not in the checkout,
  no box and no import through them), values leaving the root, calls or values not resolved and the files holding
  them (count and first three in path order), imports resolved through an inserted directory; ``docker``: the
  counts of ``docker_edges``; ``kustomize``: those of ``kustomize_edges`` (references by outcome, the manifests
  they deploy by document ``kind``, YAML files no kustomization names). ``unread_manifests``
  names a missing ecosystem adapter; a manifest kind outside that list (and a build file
  under another name) is not counted, and a counted file is not opened.

**The delta** (``map_delta``): what changed between two target maps (``map``'s output), so a session that changes a
reader measures its effect on the target with one comparison instead of diffing drawings by hand. The maps are
read as given; how they were made (two brains on one target, one brain on two target commits) is the caller's: a
session maps the target with the base brain from a worktree of the base commit and with its own tree, then runs
``delta``. Rules:

- ``projects`` by ``dir``: ``added`` (a dir only in the head map) and ``removed`` (only in the base), each the node
  as written; ``changed``: a dir in both whose ``name`` or ``kinds`` differ, ``{dir, base, head}`` with both nodes;
- ``edges`` by ``(from, to)``: ``added``, ``removed`` and ``changed`` (``kinds`` differ, ``{from, to, base,
  head}`` with both edges), the same way;
- ``coverage`` by key path (a list of keys, not a dotted string: a key such as ``.utf8`` holds a dot): where both
  sides hold an object the keys of both are descended; anything else (a number, a string, a list, an object facing
  a non-object) is a leaf, and a leaf that differs is ``{path, base, head}``; a key on one side only is one entry
  with that side's whole value and no key for the other side;
- two values are equal when their canonical JSON is (``1`` and ``true``, ``1`` and ``1.0`` differ); every list is in
  sorted order (nodes by dir, edges by ``(from, to)``, coverage by path); ``same`` is true when all are empty.
- A map file is usable when it is UTF-8 JSON: an object holding ``projects`` (a list of objects with a string
  ``dir``, a string ``name`` and a list of strings ``kinds``, no dir twice), ``edges`` (a list of objects with string
  ``from`` and ``to`` and a list of strings ``kinds``, no pair twice) and ``coverage`` (an object), and nests at
  most ``MAP_DEPTH`` (64) objects and lists deep, the map itself the first (``map`` wrote 6 on the target of
  2026-11-05: map, coverage, ``docker``, ``workflows``, ``unreadable``, ``examples``; and map, coverage,
  ``kustomize``, ``manifests``, ``unreadable``, ``examples``); so the delta's walks and its output stay far inside the interpreter's
  recursion limit, and a deeper file is unusable, never a fault. Other keys are not read but are counted in the
  depth. Not compared, stated: anything the map does not hold (a file's specifiers, a file's reader view: f769).

Command line, run from ``referee/``::

    python -m status.depmap brain ROOT                    the brain's drawing (markdown) on stdout
    python -m status.depmap check ROOT                    the register's problems, one JSON line {ok, problems}
    python -m status.depmap target ROOT --source LABEL    the target's drawing (markdown) on stdout
    python -m status.depmap coverage ROOT                 the target map's coverage, one JSON line
    python -m status.depmap map ROOT                      the target map (projects, edges, coverage), one JSON line
    python -m status.depmap delta BASE HEAD               the delta of two ``map`` files, one JSON line

exit 0, 1 when ``check`` finds a problem or ``delta`` a difference, or 2 on a bad command line, a root that is not
a directory or a map file that is not usable (``{"ok": false, "error": ...}``).
"""

from __future__ import annotations

import ast
import collections
import fnmatch
import itertools
import json
import os
import posixpath
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import cli
from profile import docker
from profile import ghactions
from profile import jsimports as J
from profile import kustomize
from profile import pypath
from profile import yamlblock

USAGE = ("usage: python -m status.depmap brain ROOT | check ROOT | target ROOT --source LABEL | coverage ROOT"
         " | map ROOT | delta BASE HEAD")
GENERATED = "Generated by `python -m status.depmap %s` from %s; do not edit by hand."

BRAIN_SKIP = {"tests", "__pycache__"}
REGISTER = "status/off_live.json"
OFF_LIVE_KINDS = ("session_tool", "unwired")
WORKFLOW_MODULE = re.compile(r"\bpython3?\s+-m\s+([A-Za-z_][A-Za-z0-9_.]*)")

# Every file of a checkout is of one kind (``file_kind``), decided in this order: ``read`` (a ``.py`` file or a JS/TS
# file, jsimports.SOURCE_EXTENSIONS: its imports draw arrows); ``code`` (its references are not read), by name
# first (``CODE_FILE_NAMES``, fnmatchcase on the name, the first pattern that matches is the key) and then by
# extension (``OTHER_CODE_EXTENSIONS``; an extension is the name's last suffix, case as written, a name's leading
# dot not one); ``not_code`` (``NOT_CODE_EXTENSIONS``); ``unclassified`` (any other extension: a kind no list
# states, counted so a new language or format shows as a number); ``no_extension`` (no name pattern, no suffix).
# Code: programming languages, shell scripts, infrastructure code (Terraform: a module calls another by path; a
# Dockerfile copies paths and names images; a Makefile runs targets and files) and query or schema languages (SQL,
# GraphQL, protobuf, jq: a file names tables, types, messages or fields another defines).
OTHER_CODE_EXTENSIONS = {".rs", ".go", ".java", ".kt", ".rb", ".php", ".cs", ".c", ".cc", ".cpp", ".h",
                         ".swift", ".scala", ".vue", ".svelte",
                         ".sh", ".bash", ".ps1",
                         ".tf", ".hcl",
                         ".sql", ".graphql", ".gql", ".proto", ".jq"}
CODE_FILE_NAMES = docker.DOCKERFILE_NAMES + (
                   "Makefile", "GNUmakefile", "makefile", "Jenkinsfile", "Justfile", "justfile", "Vagrantfile",
                   "Rakefile", "Tiltfile")
# Not code: what no map draws an arrow from, by group: documents and markup; data and configuration; styles;
# images, fonts and media; archives and binaries; keys, certificates and digests; build and tool outputs.
NOT_CODE_EXTENSIONS = {".md", ".mdx", ".markdown", ".rst", ".adoc", ".txt", ".html", ".htm", ".xml", ".svg", ".pdf",
                       ".json", ".jsonc", ".json5", ".jsonl", ".ndjson", ".yaml", ".yml", ".toml", ".ini", ".cfg",
                       ".conf", ".properties", ".csv", ".tsv", ".lock",
                       ".css", ".scss", ".sass", ".less",
                       ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".bmp", ".avif",
                       ".woff", ".woff2", ".ttf", ".otf", ".eot", ".mp3", ".mp4", ".webm", ".wav",
                       ".zip", ".gz", ".tgz", ".tar", ".bz2", ".xz", ".7z", ".jar", ".wasm", ".so", ".dll", ".exe",
                       ".bin",
                       ".pem", ".crt", ".cer", ".key", ".pub", ".asc", ".sig", ".sha256",
                       ".map", ".tsbuildinfo", ".snap", ".log"}
FILE_KINDS = ("read", "code", "not_code", "unclassified", "no_extension")
NPM_DEP_FIELDS = ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies")
CARGO_DEP_TABLES = ("dependencies", "dev-dependencies", "build-dependencies")
# Dependency manifests of ecosystems target_map does not read, each a pattern matched (fnmatchcase) against a
# file's name: the one list coverage.unread_manifests counts by.
MANIFESTS_NOT_READ = (
    "go.mod",                                                               # Go
    "pom.xml", "build.gradle", "build.gradle.kts", "settings.gradle", "settings.gradle.kts", "build.sbt",  # JVM
    "Gemfile", "*.gemspec",                                                 # Ruby
    "composer.json",                                                        # PHP
    "*.csproj", "*.fsproj", "*.vbproj",                                     # .NET
    "Package.swift", "Podfile",                                             # Swift
    "pubspec.yaml",                                                         # Dart
    "mix.exs", "rebar.config",                                              # Elixir, Erlang
    "setup.py", "setup.cfg", "Pipfile", "requirements*.txt",                # Python beside pyproject.toml
    "CMakeLists.txt", "meson.build", "conanfile.txt", "conanfile.py", "vcpkg.json",  # C and C++
    "*.cabal", "stack.yaml",                                                # Haskell
    "deno.json", "deno.jsonc",                                              # Deno
    "MODULE.bazel", "WORKSPACE", "WORKSPACE.bazel",                         # Bazel
    "build.zig", "dune-project", "Project.toml",                            # Zig, OCaml, Julia
)
UNREAD_EXAMPLES = 3
PROJECT_KINDS = ("npm", "nx", "cargo", "python", "tsconfig", "path", "docker", "kustomize")
# target_map reads its Python and JS/TS files READERS at a time, at most READ_AHEAD files ahead of the one it
# parses: a checkout on a network or virtual file system answers each open slowly, and threads wait in parallel
READERS = 16
READ_AHEAD = 256


# ---------------------------------------------------------------------------------------------------- the brain


def python_modules(root: str) -> dict[str, str]:
    """Dotted module name -> path relative to ``root``, for every ``.py`` file outside ``BRAIN_SKIP`` and hidden
    directories."""
    modules: dict[str, str] = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in BRAIN_SKIP and not d.startswith("."))
        rel_dir = os.path.relpath(dirpath, root)
        parts = [] if rel_dir == "." else rel_dir.split(os.sep)
        for name in sorted(filenames):
            if not name.endswith(".py"):
                continue
            rel = "/".join(parts + [name])
            dotted = module_name(rel)
            if dotted:
                modules[dotted] = rel
    return modules


def module_name(rel: str) -> str:
    """The dotted name of a ``.py`` path relative to its root (``a/b.py`` is ``a.b``, ``a/__init__.py`` is ``a``;
    the root's own ``__init__.py`` is ``""``)."""
    parts = rel[:-3].split("/")
    return ".".join(parts[:-1] if parts[-1] == "__init__" else parts)


def with_packages(names: set[str], modules: dict[str, str]) -> set[str]:
    """``names`` and every package among ``modules`` holding one of them: importing ``a.b.c`` runs ``a`` and ``a.b``
    first."""
    return set(names) | {".".join(n.split(".")[:i]) for n in names for i in range(1, n.count(".") + 1)} & set(modules)


def _deepest(name: str, modules: dict[str, str]) -> str | None:
    parts = name.split(".")
    for n in range(len(parts), 0, -1):
        candidate = ".".join(parts[:n])
        if candidate in modules:
            return candidate
    return None


def import_statements(source: str) -> list[tuple[int, str, list[str]]]:
    """Every import statement of a Python source, anywhere in it: ``(level, module, names)``; ``import a.b`` is
    ``(0, "a.b", [])``, ``from ..x import y, z`` is ``(2, "x", ["y", "z"])``, ``from . import y`` is
    ``(1, "", ["y"])``. ``SyntaxError`` when the source does not parse. The one reader of both maps."""
    return tree_import_statements(ast.parse(source))


def tree_import_statements(tree: ast.AST) -> list[tuple[int, str, list[str]]]:
    """``import_statements`` of a parsed source."""
    out: list[tuple[int, str, list[str]]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out.extend((0, alias.name, []) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            out.append((node.level, node.module or "", [a.name for a in node.names if a.name != "*"]))
    return out


def module_imports(source: str, module: str, is_package: bool, modules: dict[str, str]) -> set[str]:
    """The modules under the root that ``module``'s import statements name (rules in the module docstring)."""
    found: set[str] = set()
    for level, name, names in import_statements(source):
        if level:
            package = module.split(".") if is_package else module.split(".")[:-1]
            up = level - 1
            if up > len(package):
                continue
            base = ".".join(package[:len(package) - up] + (name.split(".") if name else []))
        else:
            base = name
        if not names:
            target = _deepest(base, modules) if base else None
            if target:
                found.add(target)
        for alias in names:
            full = base + "." + alias if base else alias
            target = full if full in modules else _deepest(base, modules) if base else None
            if target:
                found.add(target)
    found.discard(module)
    return found


def workflow_modules(root: str) -> list[str]:
    """Every module name a workflow file under ``ROOT/.github/workflows`` starts with ``python -m``, sorted."""
    names: set[str] = set()
    wf_dir = os.path.join(root, ".github", "workflows")
    if os.path.isdir(wf_dir):
        for name in sorted(os.listdir(wf_dir)):
            if name.endswith((".yml", ".yaml")):
                with open(os.path.join(wf_dir, name), encoding="utf-8") as f:
                    names.update(WORKFLOW_MODULE.findall(f.read()))
    return sorted(names)


def reachable(edges: dict[str, set[str]], roots: list[str]) -> set[str]:
    seen: set[str] = set()
    stack = list(roots)
    while stack:
        node = stack.pop()
        if node in seen:
            continue
        seen.add(node)
        stack.extend(edges.get(node, ()))
    return seen


def brain_map(root: str) -> dict[str, Any]:
    modules = python_modules(root)
    edges: dict[str, set[str]] = {}
    unparsed: list[str] = []
    entry: set[str] = set()
    empty: set[str] = set()
    for name, rel in modules.items():
        with open(os.path.join(root, rel), encoding="utf-8") as f:
            source = f.read()
        try:
            edges[name] = module_imports(source, name, rel.endswith("__init__.py"), modules)
        except SyntaxError:
            unparsed.append(rel)
            edges[name] = set()
            continue
        if rel.endswith("__init__.py") and _only_docstring(source):
            empty.add(name)
        if re.search(r"^if __name__ == [\"']__main__[\"']:", source, re.M):
            entry.add(name)
    started = workflow_modules(root)
    roots = [m for m in started if m in modules]
    live = reachable(edges, roots)
    live = with_packages(live, modules)
    return {
        "modules": modules,
        "edges": {k: sorted(v) for k, v in sorted(edges.items())},
        "roots": roots,
        "external_roots": [m for m in started if m not in modules],
        "live": sorted(live),
        "off_live": sorted(set(modules) - live),
        "entry_points": sorted(entry),
        "unparsed": sorted(unparsed),
        "empty_packages": sorted(empty),
        "register": read_register(root),
    }


def _only_docstring(source: str) -> bool:
    body = ast.parse(source).body
    return not body or (len(body) == 1 and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant)
                        and isinstance(body[0].value.value, str))


def read_register(root: str) -> Any:
    """``REGISTER`` under ``root`` as JSON; ``{}`` when the file is absent, ``None`` when it cannot be read as JSON."""
    path = os.path.join(root, REGISTER)
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            return cli.load(f)
    except (UnicodeDecodeError, ValueError, RecursionError):
        return None


def register_problems(m: dict[str, Any]) -> list[str]:
    """The register's problems against ``brain_map``'s ``m`` (the rules in the module docstring)."""
    register = m["register"]
    if not isinstance(register, dict):
        return ["register_unreadable"]
    problems: set[str] = set()
    for name, entry in register.items():
        if not (isinstance(entry, dict) and set(entry) == {"kind", "why"} and entry["kind"] in OFF_LIVE_KINDS
                and isinstance(entry["why"], str) and entry["why"].strip()):
            problems.add("entry_invalid:%s" % name)
        if name not in m["modules"] or name in m["empty_packages"]:
            problems.add("named_unknown:%s" % name)
        elif name in m["live"]:
            problems.add("named_but_live:%s" % name)
    problems.update("off_live_unnamed:%s" % n for n in m["off_live"]
                    if n not in register and n not in m["empty_packages"])
    return sorted(problems)


# --------------------------------------------------------------------------------------------------- the target


def _segment(seg: str) -> str:
    return "".join("[^/]*" if c == "*" else "[^/]" if c == "?" else re.escape(c) for c in seg)


def _glob_regex(pattern: str) -> re.Pattern:
    """One workspace pattern as a regex over ``/`` and a relative directory: ``*`` and ``?`` stay inside one
    segment, ``**`` is any number of whole segments (none included)."""
    segments = [s for s in pattern.strip("/").split("/") if s not in ("", ".")]
    return re.compile("^" + "".join(r"(?:/[^/]+)*" if s == "**" else "/" + _segment(s) for s in segments) + "$")


def glob_dirs(patterns: list[str], dirs: list[str]) -> list[str]:
    """The directories (relative, ``/``-separated) matched by the include patterns and by no ``!`` pattern."""
    include = [_glob_regex(p) for p in patterns if not p.startswith("!")]
    exclude = [_glob_regex(p[1:]) for p in patterns if p.startswith("!")]
    return sorted(d for d in dirs if d and any(r.match("/" + d) for r in include)
                  and not any(r.match("/" + d) for r in exclude))


def _read(root: str, rel: str) -> str | None:
    try:
        with open(os.path.join(root, rel), encoding="utf-8") as f:
            return f.read()
    except (OSError, UnicodeDecodeError):
        return None


def _reads(root: str, rels: list[str]):
    """``(rel, _read(root, rel))`` for each of ``rels``, in their order, read by ``READERS`` threads at most
    ``READ_AHEAD`` files ahead of the one taken."""
    with ThreadPoolExecutor(READERS) as pool:
        rest = iter(rels)
        pending = collections.deque((rel, pool.submit(_read, root, rel)) for rel in itertools.islice(rest, READ_AHEAD))
        while pending:
            rel, text = pending.popleft()
            for more in itertools.islice(rest, 1):
                pending.append((more, pool.submit(_read, root, more)))
            yield rel, text.result()


class _Projects:
    def __init__(self) -> None:
        self.by_dir: dict[str, dict[str, Any]] = {}

    def add(self, d: str, kind: str, name: str) -> None:
        p = self.by_dir.setdefault(d, {"dir": d, "kinds": set(), "names": {}})
        p["kinds"].add(kind)
        p["names"].setdefault(kind, name)

    def owner(self, path: str) -> str | None:
        """The deepest project directory holding ``path`` (a file or a directory), or None."""
        probe = path
        while probe:
            if probe in self.by_dir:
                return probe
            probe = posixpath.dirname(probe)
        return None


def _norm(path: str) -> str | None:
    """``path`` normalised relative to the root, or None when it leaves the root."""
    p = posixpath.normpath(path)
    if p == ".":
        return ""
    if p.startswith("../") or p == ".." or p.startswith("/"):
        return None
    return p


def _tsconfig_aliases(root: str, files: set[str], coverage: dict) -> list[tuple[str, str]]:
    name = J.alias_file(files)
    if name is None:
        return []
    try:
        return J.aliases(_read(root, name) or "")
    except ValueError:
        coverage["unparsed_manifests"].append(name)
        return []


def _cargo_deps(manifest: dict) -> list[tuple[str, Any]]:
    deps: list[tuple[str, Any]] = []
    tables = [manifest] + [t for t in (manifest.get("target") or {}).values() if isinstance(t, dict)]
    for table in tables:
        for key in CARGO_DEP_TABLES:
            for name, spec in sorted((table.get(key) or {}).items()):
                deps.append((name, spec))
    return deps


def _under(path: str, base: str) -> bool:
    """``path`` is ``base`` or inside it, segment by segment (``""`` is the root)."""
    return base == "" or path == base or path.startswith(base + "/")


def cargo_workspace(d: str, manifest: dict, roots: dict[str, dict]) -> str | None:
    """The directory of the workspace root package ``d`` belongs to, as Cargo finds it, or None (its own root).

    ``package.workspace``, when a string, names it (a path from ``d``); else ``d`` itself when its manifest has a
    ``[workspace]``; else the nearest directory above ``d`` whose manifest has one, unless that one's ``exclude``
    holds ``d`` (an exclude entry is a path from the workspace root, ``d`` excluded when at or below it), which
    leaves ``d`` its own root. Cargo also refuses a package under a workspace that neither lists nor excludes it;
    membership is not checked here."""
    package = manifest.get("package") or {}
    if isinstance(package.get("workspace"), str):
        named = _norm(posixpath.join(d, package["workspace"]))
        return named if named in roots else None
    if d in roots:
        return d
    probe = d
    while probe:
        probe = posixpath.dirname(probe)
        if probe in roots:
            excludes = (roots[probe].get("workspace") or {}).get("exclude") or []
            for ex in excludes:
                path = _norm(posixpath.join(probe, ex)) if isinstance(ex, str) else None
                if path is not None and _under(d, path):
                    return None
            return probe
    return None


def _crate(key: str, spec: dict) -> str:
    """The crate a dependency (or a patch) entry names: its ``package`` when it renames, else its key."""
    return spec["package"] if isinstance(spec.get("package"), str) else key


def cargo_dep_paths(d: str, manifest: dict, top_dir: str, top: dict) -> list[str]:
    """The directories (normalised, inside the root) Cargo resolves package ``d``'s dependencies to, sorted.

    ``top`` is the manifest of ``d``'s workspace root at ``top_dir`` (``d``'s own when it has none). A dependency is
    each entry of ``_cargo_deps``; its directory is its ``path`` from ``d``; for ``workspace = true``, the ``path``
    of ``top``'s ``[workspace.dependencies]`` entry of that name, from ``top_dir``; else, for a crates.io one (no
    ``path``, ``git`` or ``registry``, here or in that entry), the ``path`` of ``top``'s ``[patch.crates-io]`` entry
    for the same crate (an entry's crate is its ``package`` when it renames, else its key; a ``workspace = true`` entry
    absent from the table resolves to nothing), from ``top_dir``. Not read, stated: ``[replace]``,
    ``[patch]`` of another source, a ``git`` dependency's repository."""
    ws_deps = (top.get("workspace") or {}).get("dependencies") or {}
    patches = (top.get("patch") or {}).get("crates-io") or {}
    found: set[str] = set()
    for name, spec in _cargo_deps(manifest):
        spec = spec if isinstance(spec, dict) else {}
        path = None
        base = d
        if spec.get("workspace") is True:
            inherited = ws_deps.get(name)
            if not isinstance(inherited, (dict, str)):
                continue
            spec = inherited if isinstance(inherited, dict) else {}
            base = top_dir
        if isinstance(spec.get("path"), str):
            path = _norm(posixpath.join(base, spec["path"]))
        elif not any(k in spec for k in ("git", "registry")):
            crate = _crate(name, spec)
            patch = next((p for key, p in sorted(patches.items()) if isinstance(p, dict) and _crate(key, p) == crate
                          and isinstance(p.get("path"), str)), None)
            if patch is not None:
                path = _norm(posixpath.join(top_dir, patch["path"]))
        if path is not None and path != d:
            found.add(path)
    return sorted(found)


def sys_path_target(top: str, inserted: list[str], file_set: set[str], dir_set: set[str]) -> str | None:
    """What an absolute import whose first name is ``top`` reaches through ``inserted`` (directories in their
    source order), as Python's path finder takes it: in the first directory ``D`` holding a package ``D/top/``
    with ``__init__.py`` or a module ``D/top.py``, that package (before the module in the same ``D``) or module;
    else the first ``D/top`` that is a directory (a namespace package); else None. The module is the path
    ``D/top.py``, the packages the directory."""
    for d in inserted:
        path = posixpath.join(d, top)
        if path + "/__init__.py" in file_set:
            return path
        if path + ".py" in file_set:
            return path + ".py"
    return next((posixpath.join(d, top) for d in inserted if posixpath.join(d, top) in dir_set), None)


def file_kind(rel: str) -> tuple[str, str]:
    """A file's kind (``FILE_KINDS``) and its key: the extension, the ``CODE_FILE_NAMES`` pattern that matched, or
    ``""`` for ``no_extension``; the rule is the comment above ``OTHER_CODE_EXTENSIONS``."""
    name = posixpath.basename(rel)
    ext = posixpath.splitext(name)[1]
    if ext == ".py" or ext in J.SOURCE_EXTENSIONS:
        return "read", ext
    pattern = next((p for p in CODE_FILE_NAMES if fnmatch.fnmatchcase(name, p)), None)
    if pattern is not None:
        return "code", pattern
    if ext in OTHER_CODE_EXTENSIONS:
        return "code", ext
    if ext in NOT_CODE_EXTENSIONS:
        return "not_code", ext
    return ("unclassified", ext) if ext else ("no_extension", "")


def _examples(found: dict[str, list[str]]) -> dict[str, dict[str, Any]]:
    """``{key: {"count", "examples"}}``, the first ``UNREAD_EXAMPLES`` paths in path order, keys sorted."""
    return {k: {"count": len(v), "examples": sorted(v)[:UNREAD_EXAMPLES]} for k, v in sorted(found.items())}


def unread_manifests(files: list[str], npm_dirs: set[str]) -> dict[str, dict[str, Any]]:
    """Per pattern of ``MANIFESTS_NOT_READ`` that a file's name matches (the first pattern in the list), and under
    ``package.json`` every one outside the root whose directory is not an npm workspace project (its dependencies
    draw nothing): ``{"count", "examples"}``, the first ``UNREAD_EXAMPLES`` paths in path order; patterns with no
    file are left out."""
    found: dict[str, list[str]] = {}
    for rel in files:
        name = posixpath.basename(rel)
        d = posixpath.dirname(rel)
        if name == "package.json":
            if d and d not in npm_dirs:
                found.setdefault(name, []).append(rel)
            continue
        pattern = next((p for p in MANIFESTS_NOT_READ if fnmatch.fnmatchcase(name, p)), None)
        if pattern is not None:
            found.setdefault(pattern, []).append(rel)
    return _examples(found)


def _yaml(root: str, rel: str) -> list[Any] | None:
    """The documents of the YAML file ``rel`` (``profile.yamlblock.load_all``), or ``None`` when it is not UTF-8
    or not read (counted as unreadable by each caller; an undecodable file is not an empty one)."""
    text = _read(root, rel)
    if text is None:
        return None
    try:
        return yamlblock.load_all(text)
    except yamlblock.Unreadable:
        return None


def _context_matches(context: str, source: str, files: set[str], dirs: set[str]) -> list[str] | None:
    """The paths a ``context`` source names, relative to the root: the path itself when it is a file or a
    directory, or for a source holding ``*``, ``?`` or ``[`` every file and directory under the context whose path
    matches it segment by segment (``fnmatchcase``, ``*`` inside one segment, as Docker's ``filepath.Match``);
    ``None`` when the source leaves the context."""
    path = _norm(posixpath.join(context, source.lstrip("/")))
    if path is None or not _under(path, context):
        return None
    if not any(c in source for c in "*?["):
        return [path] if path in files or path in dirs else []
    want = path.split("/")
    return sorted(p for p in itertools.chain(files, dirs) if p and len(p.split("/")) == len(want)
                  and all(fnmatch.fnmatchcase(a, b) for a, b in zip(p.split("/"), want)))


def docker_edges(root: str, files: list[str], dockerfiles: list[str], dirs: set[str], projects: _Projects,
                 coverage: dict, edge) -> set[str]:
    """The ``docker`` arrows and ``coverage["docker"]``; returns the Dockerfiles read (those a build names).

    A build is a context and a Dockerfile, from two sources, each file read by ``profile.yamlblock`` (one not read
    counts in ``compose_unreadable`` or ``workflows.unreadable``): a ``profile.docker.compose_builds`` entry of a
    compose file (``profile.docker.COMPOSE_NAMES``), its context, ``.`` when not given, relative to the compose file's
    directory, and its Dockerfile, ``Dockerfile`` when not given, relative to the context; and a pair of a
    ``profile.ghactions.builds`` step of a GitHub Actions file (``profile.ghactions.is_actions_file``), both paths
    from the root (a step not resolved counts by its reason). A build is ``unresolved`` when a value is not a
    string or holds ``$`` (Compose substitutes variables; an expression left in a workflow's value) or ``://`` (a remote context), starts with ``/`` or
    leaves the root, and ``missing`` when the context is not a directory of the checkout or the Dockerfile not a
    file of it. Each Dockerfile with a build is read once; for each distinct context it is built with, each
    ``context`` source (``_context_matches``) reaches the project holding each path it names and, for a
    directory, every project inside it; an arrow goes from the project holding the Dockerfile to each project
    reached (none from a Dockerfile in no project, the root's)."""
    cov = {"dockerfiles": len(dockerfiles), "compose_files": 0, "compose_unreadable": {}, "builds": 0,
           "builds_unresolved": 0,
           "builds_missing": 0, "dockerfiles_built": 0, "dockerfiles_not_built": {},
           "sources": {k: 0 for k in docker.COPY_KINDS}, "malformed": 0,
           "context_sources": {"matched": 0, "no_match": 0, "leaves_context": 0},
           "workflows": {"files": 0, "unreadable": {}, "steps": 0, "steps_unresolved": {k: 0 for k in
                                                                                         ghactions.REASONS},
                         "builds": 0, "builds_unresolved": 0, "builds_missing": 0}}
    coverage["docker"] = cov
    wf = cov["workflows"]
    file_set = set(files)
    contexts: dict[str, set[str]] = {}

    def place(base: str, context: str, dockerfile: str, in_context: bool, counts: dict) -> None:
        counts["builds"] += 1
        if any(not isinstance(v, str) or "$" in v or "://" in v for v in (context, dockerfile)):
            counts["builds_unresolved"] += 1
            return
        ctx = _norm(posixpath.join(base, context))
        path = None if ctx is None else _norm(posixpath.join(ctx if in_context else "", dockerfile))
        if ctx is None or path is None:
            counts["builds_unresolved"] += 1
        elif ctx not in dirs or path not in file_set:
            counts["builds_missing"] += 1
        else:
            contexts.setdefault(path, set()).add(ctx)

    unreadable: dict[str, list[str]] = {"compose": [], "actions": []}
    for rel in files:
        compose = docker.is_compose(posixpath.basename(rel))
        if not compose and not ghactions.is_actions_file(rel):
            continue
        (cov if compose else wf)["compose_files" if compose else "files"] += 1
        docs = _yaml(root, rel)
        if docs is None or len(docs) > 1:
            unreadable["compose" if compose else "actions"].append(rel)
            continue
        doc = docs[0] if docs else None
        if compose:
            for _service, context, dockerfile in docker.compose_builds(doc):
                place(posixpath.dirname(rel), "." if context is None else context,
                      "Dockerfile" if dockerfile is None else dockerfile, True, cov)
            continue
        for build in ghactions.builds(doc):
            wf["steps"] += 1
            if build.reason is not None:
                wf["steps_unresolved"][build.reason] += 1
            for context, dockerfile in build.pairs:
                place("", context, dockerfile, False, wf)
    cov["compose_unreadable"] = _examples({"": unreadable["compose"]})[""]
    wf["unreadable"] = _examples({"": unreadable["actions"]})[""]
    cov["dockerfiles_built"] = len(contexts)
    cov["dockerfiles_not_built"] = _examples({"": [r for r in dockerfiles if r not in contexts]})[""]
    project_dirs = sorted(projects.by_dir)
    for rel in sorted(contexts):
        sources, malformed = docker.copies(_read(root, rel) or "")
        cov["malformed"] += malformed
        here = projects.owner(rel)
        for _line, _keyword, source, kind in sources:
            cov["sources"][kind] += 1
            if kind != "context":
                continue
            for ctx in sorted(contexts[rel]):
                matched = _context_matches(ctx, source, file_set, dirs)
                if matched is None:
                    cov["context_sources"]["leaves_context"] += 1
                    continue
                cov["context_sources"]["matched" if matched else "no_match"] += 1
                for p in matched:
                    edge(here, projects.owner(p), "docker")
                    if p in dirs:
                        for d in project_dirs:
                            if _under(d, p):
                                edge(here, d, "docker")
    return set(contexts)


def kustomize_edges(root: str, files: list[str], dirs: set[str], projects: _Projects, coverage: dict,
                    edge) -> None:
    """The ``kustomize`` arrows and ``coverage["kustomize"]``.

    Each kustomization file (``profile.kustomize.is_kustomization``) is read as one YAML document (a file not
    UTF-8, not read by ``profile.yamlblock`` or holding several documents counts in ``unreadable``); each of its
    ``profile.kustomize.references`` is counted by kind, and a ``path`` one, joined to the file's directory, is
    ``leaves_root`` (it starts with ``/`` or leaves the root), ``remote`` (no file or directory of the checkout
    and ``profile.kustomize.host_like``: Kustomize fetches it), ``missing`` (no file or directory of the checkout
    otherwise: ``kustomize build`` stops there), ``no_kustomization`` (a directory holding no kustomization file, which
    Kustomize requires of a directory) or ``resolved``; a resolved one draws an arrow from the project holding the
    kustomization file to the project holding the path (none from a file in no project). ``missing_files`` and
    ``no_kustomization_files`` are the kustomization files with such a reference. ``manifests``: each resolved
    file of ``resources``, ``bases`` or ``crds`` is read once with every document (``profile.yamlblock``;
    ``unreadable`` as above), its documents counted, empty ones apart, and the non-empty ones by their ``kind``
    (``no_kind`` when it is not a string). ``unreferenced``: the ``.yaml`` and ``.yml`` files in a directory holding
    a kustomization file (that directory only, not below it), other than kustomization files, that no resolved
    reference of any kustomization file names and that hold a Kubernetes object (``_k8s_object``; a file not read
    holds none): not built by Kustomize, whether applied another way is not read."""
    cov: dict[str, Any] = {"files": 0, "unreadable": {}, "references": {k: 0 for k in kustomize.KINDS},
                           "paths": {"resolved": 0, "missing": 0, "remote": 0, "no_kustomization": 0, "leaves_root": 0},
                           "missing_files": {}, "no_kustomization_files": {},
                           "manifests": {"files": 0, "unreadable": {}, "documents": 0, "empty_documents": 0,
                                         "kinds": {}}, "unreferenced": {}}
    coverage["kustomize"] = cov
    file_set = set(files)
    roots = {posixpath.dirname(rel) for rel in files if kustomize.is_kustomization(posixpath.basename(rel))}
    found: dict[str, list[str]] = {"unreadable": [], "missing_files": [], "no_kustomization_files": []}
    named: set[str] = set()
    manifests: set[str] = set()
    for rel in files:
        if not kustomize.is_kustomization(posixpath.basename(rel)):
            continue
        cov["files"] += 1
        docs = _yaml(root, rel)
        if docs is None or len(docs) > 1:
            found["unreadable"].append(rel)
            continue
        here = projects.owner(rel)
        flags = set()
        for field, value, kind in kustomize.references(docs[0] if docs else None):
            cov["references"][kind] += 1
            if kind != "path":
                continue
            path = _norm(posixpath.join(posixpath.dirname(rel), value))
            if path is None:
                outcome = "leaves_root"
            elif path not in file_set and path not in dirs:
                outcome = "remote" if kustomize.host_like(value) else "missing"
            elif path in dirs and path not in roots:
                outcome = "no_kustomization"
            else:
                outcome = "resolved"
            cov["paths"][outcome] += 1
            if outcome in ("missing", "no_kustomization"):
                flags.add(outcome + "_files")
            if outcome != "resolved":
                continue
            named.add(path)
            if here is not None:
                edge(here, projects.owner(path), "kustomize")
            if path in file_set and field in ("resources", "bases", "crds"):
                manifests.add(path)
        for flag in sorted(flags):
            found[flag].append(rel)
    man = cov["manifests"]
    for rel in sorted(manifests):
        man["files"] += 1
        docs = _yaml(root, rel)
        if docs is None:
            man["unreadable"].setdefault("", []).append(rel)
            continue
        for doc in docs:
            if doc is None:
                man["empty_documents"] += 1
                continue
            man["documents"] += 1
            key = doc.get("kind") if isinstance(doc, dict) and isinstance(doc.get("kind"), str) else "no_kind"
            man["kinds"][key] = man["kinds"].get(key, 0) + 1
    man["unreadable"] = _examples({"": man["unreadable"].get("", [])})[""]
    man["kinds"] = dict(sorted(man["kinds"].items()))
    for key, rels in found.items():
        cov[key] = _examples({"": rels})[""]
    cov["unreferenced"] = _examples({"": [rel for rel in files if posixpath.dirname(rel) in roots
                                          and posixpath.splitext(rel)[1] in (".yaml", ".yml")
                                          and not kustomize.is_kustomization(posixpath.basename(rel))
                                          and rel not in named and _k8s_object(_yaml(root, rel))]})[""]


def _k8s_object(docs: list[Any] | None) -> bool:
    """Whether some document is a Kubernetes object's shape: a mapping with a string ``apiVersion`` and ``kind``."""
    return any(isinstance(d, dict) and isinstance(d.get("apiVersion"), str) and isinstance(d.get("kind"), str)
               for d in docs or ())


def target_map(root: str) -> dict[str, Any]:
    import tomllib

    files, dirs = J.walk(root)
    file_set = set(files)
    coverage: dict[str, Any] = {"files": len(files), "unparsed_manifests": [], "unread_code_files": {},
                                "unread_code_files_outside_projects": {},
                                "source_files": 0, "source_files_outside_projects": 0,
                                "python_files": 0, "python_files_outside_projects": 0, "python_files_unparsed": 0,
                                "unread_manifests": {},
                                "sys_path": {"calls": 0, "dirs": 0, "missing": 0, "unresolved": 0, "leaves_root": 0,
                                             "imports": 0, "unresolved_files": []},
                                "specifiers": {"cross_project": 0, "same_project": 0, "external_package": 0,
                                               "outside_projects": 0, "leaves_root": 0, "python_external": 0,
                                               "python_relative": 0}}
    projects = _Projects()
    manifests: dict[str, dict] = {}

    def load_json(rel: str) -> dict | None:
        try:
            value = cli.loads(_read(root, rel) or "")
        except ValueError:
            coverage["unparsed_manifests"].append(rel)
            return None
        return value if isinstance(value, dict) else None

    # npm workspaces
    npm_names: dict[str, str] = {}
    root_pkg = load_json("package.json") if "package.json" in file_set else None
    workspaces = (root_pkg or {}).get("workspaces")
    if isinstance(workspaces, dict):
        workspaces = workspaces.get("packages")
    if isinstance(workspaces, list):
        pkg_dirs = [d for d in dirs if d + "/package.json" in file_set]
        for d in glob_dirs([w for w in workspaces if isinstance(w, str)], pkg_dirs):
            pkg = load_json(d + "/package.json")
            if pkg is None:
                continue
            manifests[d] = pkg
            name = pkg.get("name") if isinstance(pkg.get("name"), str) else d
            projects.add(d, "npm", name)
            npm_names.setdefault(name, d)
    # Nx projects
    for rel in files:
        if posixpath.basename(rel) == "project.json" and posixpath.dirname(rel):
            pj = load_json(rel)
            if pj is None:
                continue
            d = posixpath.dirname(rel)
            projects.add(d, "nx", pj.get("name") if isinstance(pj.get("name"), str) else posixpath.basename(d))
    # Cargo packages: every manifest below the root with a [package] table
    cargo: dict[str, dict] = {}
    cargo_roots: dict[str, dict] = {}
    for rel in files:
        if posixpath.basename(rel) != "Cargo.toml":
            continue
        d = posixpath.dirname(rel)
        try:
            manifest = tomllib.loads(_read(root, rel) or "")
        except tomllib.TOMLDecodeError:
            coverage["unparsed_manifests"].append(rel)
            continue
        if isinstance(manifest.get("workspace"), dict):
            cargo_roots[d] = manifest
        package = manifest.get("package")
        if d and isinstance(package, dict):
            cargo[d] = manifest
            name = package.get("name")
            projects.add(d, "cargo", name if isinstance(name, str) else posixpath.basename(d))

    # Python projects: a pyproject.toml below the root; their top-level packages
    py_packages: dict[str, str] = {}
    for rel in files:
        if posixpath.basename(rel) == "pyproject.toml" and posixpath.dirname(rel):
            d = posixpath.dirname(rel)
            try:
                pyproject = tomllib.loads(_read(root, rel) or "")
            except tomllib.TOMLDecodeError:
                coverage["unparsed_manifests"].append(rel)
                continue
            projects.add(d, "python", (pyproject.get("project") or {}).get("name") or posixpath.basename(d))
    for rel in files:
        parts = rel.split("/")
        if parts[-1] != "__init__.py" or len(parts) < 3:
            continue
        holder = "/".join(parts[:-2])
        holder = posixpath.dirname(holder) if posixpath.basename(holder) == "src" else holder
        if holder in projects.by_dir and "python" in projects.by_dir[holder]["kinds"]:
            py_packages.setdefault(parts[-2], holder)

    # TypeScript configurations no manifest's project holds, decided now (against the manifests' projects only),
    # boxed after the Python boxes, which are decided against the manifests' projects only too
    ts_boxes = sorted({posixpath.dirname(rel) for rel in files if posixpath.dirname(rel)
                       and J.TSCONFIG.fullmatch(posixpath.basename(rel)) and projects.owner(rel) is None})

    # Python files: read once; the directories each puts on sys.path (profile.pypath) become boxes when no
    # manifest's project holds them, decided against the manifest projects only (so the order does not matter)
    dir_set = set(dirs)
    python: dict[str, tuple[list | None, list[str]]] = {}
    sys_path = coverage["sys_path"]
    for rel, text in _reads(root, [rel for rel in files if rel.endswith(".py")]):
        try:
            tree = ast.parse(text) if text is not None else None
            statements = tree_import_statements(tree) if tree is not None else None
            inserted = pypath.tree_insertions(tree, rel) if tree is not None else None
        except (SyntaxError, ValueError):
            statements = inserted = None
        if inserted is None:
            python[rel] = (None, [])
            continue
        for key in ("calls", "unresolved", "leaves_root"):
            sys_path[key] += inserted[key]
        if inserted["unresolved"]:
            sys_path["unresolved_files"].append(rel)
        present = [d for d in inserted["dirs"] if d in dir_set]
        sys_path["dirs"] += len(inserted["dirs"])
        sys_path["missing"] += len(inserted["dirs"]) - len(present)
        python[rel] = (statements, present)
    new_boxes = sorted({d for _s, ds in python.values() for d in ds if d and projects.owner(d) is None})
    for d in new_boxes:
        projects.add(d, "path", d)
    # a package directory an import reaches through an inserted directory, when no project holds it (only the
    # root's can be: every other inserted directory present is a box or inside a project by now)
    package_boxes = sorted({through for statements, ds in python.values() for level, name, _n in statements or ()
                            if not level and (through := sys_path_target(name.split(".")[0], ds, file_set, dir_set))
                            in dir_set and projects.owner(through) is None})
    for d in package_boxes:
        projects.add(d, "path", d)
    for d in ts_boxes:
        projects.add(d, "tsconfig", d)
    # Dockerfiles no project holds: their directory is a box, decided last (against every other box)
    dockerfiles = [rel for rel in files if docker.is_dockerfile(posixpath.basename(rel))]
    for d in sorted({posixpath.dirname(rel) for rel in dockerfiles if posixpath.dirname(rel)
                     and projects.owner(rel) is None}):
        projects.add(d, "docker", d)
    # kustomization roots no project holds: their directory is a box, decided after the Dockerfiles' boxes
    for d in sorted({posixpath.dirname(rel) for rel in files if posixpath.dirname(rel)
                     and kustomize.is_kustomization(posixpath.basename(rel)) and projects.owner(rel) is None}):
        projects.add(d, "kustomize", d)

    edges: dict[tuple[str, str], set[str]] = {}

    def edge(a: str | None, b: str | None, kind: str) -> None:
        if a is not None and b is not None and a != b:
            edges.setdefault((a, b), set()).add(kind)

    for d, pkg in manifests.items():
        for field in NPM_DEP_FIELDS:
            for name in sorted(pkg.get(field) or {}):
                if name in npm_names:
                    edge(d, npm_names[name], "npm")
    for d, manifest in cargo.items():
        top = cargo_workspace(d, manifest, cargo_roots)
        top_dir = d if top is None else top
        top_manifest = manifest if top is None else cargo_roots[top]
        for path in cargo_dep_paths(d, manifest, top_dir, top_manifest):
            if path in projects.by_dir:
                edge(d, path, "cargo")

    built = docker_edges(root, files, dockerfiles, dir_set, projects, coverage, edge)
    kustomize_edges(root, files, dir_set, projects, coverage, edge)

    aliases = _tsconfig_aliases(root, file_set, coverage)
    counts = coverage["specifiers"]
    unknown: dict[str, list[str]] = {}
    sources = _reads(root, [rel for rel in files if posixpath.splitext(rel)[1] in J.SOURCE_EXTENSIONS])
    for rel in files:
        ext = posixpath.splitext(rel)[1]
        if ext == ".py":
            statements, inserted = python[rel]
            if statements is None:
                coverage["python_files_unparsed"] += 1
                continue
            coverage["python_files"] += 1
            here = projects.owner(rel)
            if here is None:
                coverage["python_files_outside_projects"] += 1
            for level, name, _names in statements:
                if level:
                    counts["python_relative"] += 1
                    continue
                top = name.split(".")[0]
                through = sys_path_target(top, inserted, file_set, dir_set)
                if through is not None:
                    sys_path["imports"] += 1
                    there = projects.owner(through)
                    if here is None or there is None:
                        counts["outside_projects"] += 1
                    elif here == there:
                        counts["same_project"] += 1
                    else:
                        counts["cross_project"] += 1
                        edge(here, there, "sys.path")
                    continue
                if top not in py_packages:
                    counts["python_external"] += 1
                    continue
                there = py_packages[top]
                if here is None:
                    counts["outside_projects"] += 1
                elif here == there:
                    counts["same_project"] += 1
                else:
                    counts["cross_project"] += 1
                    edge(here, there, "python")
            continue
        if ext not in J.SOURCE_EXTENSIONS:
            kind, key = file_kind(rel)
            if kind == "code" and rel not in built:
                coverage["unread_code_files"][key] = coverage["unread_code_files"].get(key, 0) + 1
                if projects.owner(rel) is None:
                    outside = coverage["unread_code_files_outside_projects"]
                    outside[key] = outside.get(key, 0) + 1
            elif kind in ("unclassified", "no_extension"):
                unknown.setdefault(key, []).append(rel)
            continue
        _rel, text = next(sources)
        if text is None:
            continue
        coverage["source_files"] += 1
        here = projects.owner(rel)
        if here is None:
            coverage["source_files_outside_projects"] += 1
        for spec in J.specifiers(text):
            if spec.startswith("./") or spec.startswith("../") or spec in (".", ".."):
                path = _norm(posixpath.join(posixpath.dirname(rel), spec))
            else:
                path = J.alias_path(spec, aliases)
                if path is not None:
                    path = _norm(path)
                else:
                    pkg_name = next((n for n in sorted(npm_names, key=len, reverse=True)
                                     if spec == n or spec.startswith(n + "/")), None)
                    if pkg_name is None:
                        counts["external_package"] += 1
                        continue
                    path = npm_names[pkg_name]
            if path is None:
                counts["leaves_root"] += 1
                continue
            there = projects.owner(path)
            if here is None or there is None:
                counts["outside_projects"] += 1
            elif here == there:
                counts["same_project"] += 1
            else:
                counts["cross_project"] += 1
                edge(here, there, "import")

    coverage["unread_manifests"] = unread_manifests(files, set(manifests))
    unknown_counted = _examples(unknown)  # key "": the files with no extension
    coverage["files_without_extension"] = unknown_counted.pop("", {"count": 0, "examples": []})
    coverage["unclassified_files"] = unknown_counted
    coverage["unparsed_manifests"] = sorted(set(coverage["unparsed_manifests"]))
    for key in ("unread_code_files", "unread_code_files_outside_projects"):
        coverage[key] = dict(sorted(coverage[key].items()))
    files_unresolved = sys_path.pop("unresolved_files")
    sys_path["unresolved_files"] = {"count": len(files_unresolved), "examples": files_unresolved[:UNREAD_EXAMPLES]}
    coverage["projects"] = len(projects.by_dir)
    coverage["projects_by_kind"] = {k: sum(1 for p in projects.by_dir.values() if k in p["kinds"])
                                    for k in PROJECT_KINDS}
    nodes = []
    for d, p in sorted(projects.by_dir.items()):
        name = next(p["names"][k] for k in PROJECT_KINDS if k in p["names"])
        nodes.append({"dir": d, "name": name, "kinds": sorted(p["kinds"])})
    return {"projects": nodes,
            "edges": [{"from": a, "to": b, "kinds": sorted(k)} for (a, b), k in sorted(edges.items())],
            "coverage": coverage}


# ------------------------------------------------------------------------------------------------------ drawing


def _ids(names: list[str]) -> dict[str, str]:
    return {n: "n%d" % i for i, n in enumerate(sorted(names))}


def _label(text: str) -> str:
    return '"' + text.replace('"', "#quot;") + '"'


def render_brain(m: dict[str, Any], source: str = "`referee/`") -> str:
    names = sorted(m["modules"])
    ids = _ids(names)
    importers: dict[str, list[str]] = {n: [] for n in names}
    for a, targets in m["edges"].items():
        for b in targets:
            importers[b].append(a)
    groups: dict[str, list[str]] = {}
    for n in names:
        groups.setdefault(n.split(".")[0] if "." in n else "", []).append(n)
    lines = ["# The brain's dependency map", "", GENERATED % ("brain .", source + ", run there"), "",
             "An arrow A --> B: A holds an import statement naming B. Live roots (double border) are the modules "
             "the workflows under `referee/.github/workflows/` start with `python -m`; a live module (green) is "
             "reachable from one by imports, which is not proof that it is called; the others (grey) are off "
             "the live path: run by tests and vector commands only. Rules and what is not read: "
             "`referee/status/depmap.py`.", "",
             "Modules %d, arrows %d, live roots %s, live %d, off the live path %d." % (
                 len(names), sum(len(v) for v in m["edges"].values()), ", ".join(m["roots"]) or "none",
                 len(m["live"]), len(m["off_live"])), ""]
    if m["external_roots"]:
        lines += ["Started by a workflow but not under the root (not drawn): %s." % ", ".join(m["external_roots"]), ""]
    if m["unparsed"]:
        lines += ["Not parsed (no arrows): %s." % ", ".join(m["unparsed"]), ""]
    problems = register_problems(m)
    lines += ["Every module off the live path is named, with its reason, in `referee/%s` (the last column); a "
              "wired module leaves it in the same push. Register problems: %s." % (
                  REGISTER, ", ".join(problems) or "none"), ""]
    register = m["register"] if isinstance(m["register"], dict) else {}
    lines += ["```mermaid", "flowchart LR"]
    for group, members in sorted(groups.items()):
        if group:
            lines.append("  subgraph g_%s[%s]" % (group, _label(group)))
        for n in members:
            shape = "[[%s]]" if n in m["roots"] else "[%s]"
            lines.append("    %s%s" % (ids[n], shape % _label(n)))
        if group:
            lines.append("  end")
    for a, targets in m["edges"].items():
        for b in targets:
            lines.append("  %s --> %s" % (ids[a], ids[b]))
    lines.append("  classDef live fill:#d8f0d8,stroke:#2e7d32")
    lines.append("  classDef off fill:#eeeeee,stroke:#9e9e9e,color:#616161")
    if m["live"]:
        lines.append("  class %s live" % ",".join(ids[n] for n in m["live"]))
    if m["off_live"]:
        lines.append("  class %s off" % ",".join(ids[n] for n in m["off_live"]))
    lines += ["```", "", "| module | file | live | `__main__` | imports | imported by | off the live path because |",
              "|---|---|---|---|---|---|---|"]
    for n in names:
        entry = register.get(n)
        why = ("%s: %s" % (entry.get("kind"), entry.get("why")) if isinstance(entry, dict)
               else "empty package" if n in m["empty_packages"] and n not in m["live"] else "")
        lines.append("| %s | %s | %s | %s | %s | %s | %s |" % (
            n, m["modules"][n], "root" if n in m["roots"] else "yes" if n in m["live"] else "no",
            "yes" if n in m["entry_points"] else "", ", ".join(m["edges"][n]), ", ".join(sorted(importers[n])),
            " ".join(why.replace("|", "\\|").split())))
    return "\n".join(lines) + "\n"


def _some(counted: dict[str, Any]) -> str:
    """``example, example, example, ...`` for one ``{"count", "examples"}``, ``...`` when there are more."""
    return ", ".join(counted["examples"]) + (", ..." if counted["count"] > len(counted["examples"]) else "")


def _listed(counted: dict[str, dict[str, Any]]) -> str:
    """``key count (example, example, example, ...)`` per entry of ``_examples``'s form, ``; ``-joined; an entry of
    count 0 left out."""
    return "; ".join("%s %d (%s)" % (k, v["count"], _some(v)) for k, v in counted.items() if v["count"])


def render_target(m: dict[str, Any], source: str) -> str:
    dirs = [p["dir"] for p in m["projects"]]
    ids = _ids(dirs)
    cov = m["coverage"]
    sp = cov["specifiers"]
    sp_ins = cov["sys_path"]
    dk = cov["docker"]
    wf = dk["workflows"]
    kz = cov["kustomize"]
    groups: dict[str, list[dict]] = {}
    for p in m["projects"]:
        groups.setdefault(p["dir"].split("/")[0], []).append(p)
    lines = ["# The target's dependency map", "", GENERATED % ("target ROOT --source ...", source), "",
             "A box is a project (a directory named by the root's npm workspaces, an Nx `project.json`, a Cargo "
             "package's `Cargo.toml` or a `pyproject.toml`; of kind `tsconfig`: a directory holding a TypeScript "
             "configuration that no such project holds; or of kind `path`: a directory a Python file puts on "
             "`sys.path` that no such project holds, or a package directory a Python file imports through one it puts there, "
             "found only at the root; or of kind `docker`: a directory holding a Dockerfile that no other box holds; or of kind "
             "`kustomize`: a directory holding a kustomization file that no other box holds); an arrow A --> B is labelled with how it was found: "
             "`npm` or `cargo` (A's manifest names B, for Cargo also through its workspace or a `[patch]`), "
             "`import` (a JS/TS file of A imports into B), `python` (a Python file of A imports a package of B), "
             "`sys.path` (a Python file of A imports a name found in a directory the same file puts on `sys.path`, "
             "and B holds it), `docker` (a Dockerfile of A, built with a context a compose file or a GitHub Actions step "
             "names, copies a path B holds or a directory holding B), `kustomize` (a kustomization file of A names a "
             "path B holds). Rules and what is not read: "
             "`referee/status/depmap.py`, `referee/profile/pypath.py`, `referee/profile/docker.py`, "
             "`referee/profile/ghactions.py`, `referee/profile/kustomize.py` and `referee/profile/yamlblock.py`.", "",
             "Projects %d (%s), arrows %d. Files %d; JS/TS files read %d (%d outside "
             "any project), Python files read %d (%d outside any project, %d not parsed). Imports: %d across "
             "projects, %d inside one, %d "
             "of external JS packages, %d of Python modules no project holds, %d relative Python (not drawn), %d "
             "from or into no project, %d leaving the root." % (
                 cov["projects"], ", ".join("%s %d" % (k, cov["projects_by_kind"][k]) for k in PROJECT_KINDS),
                 len(m["edges"]), cov["files"],
                 cov["source_files"], cov["source_files_outside_projects"], cov["python_files"],
                 cov["python_files_outside_projects"], cov["python_files_unparsed"], sp["cross_project"],
                 sp["same_project"], sp["external_package"],
                 sp["python_external"], sp["python_relative"], sp["outside_projects"], sp["leaves_root"]), "",
             "`sys.path` insertions in Python files: %d calls; %d directories resolved (%d not in the checkout), "
             "%d leaving the root, %d calls or values not resolved (%d files: %s); %d imports resolved through "
             "them." % (
                 sp_ins["calls"], sp_ins["dirs"], sp_ins["missing"], sp_ins["leaves_root"], sp_ins["unresolved"],
                 sp_ins["unresolved_files"]["count"],
                 _some(sp_ins["unresolved_files"]) or "none",
                 sp_ins["imports"]), "",
             "Dockerfiles %d: %d built (by %d `build:` entries of %d compose files, %d not resolved, %d naming no "
             "context or Dockerfile of the checkout; compose files not read: %s; by %d builds of %d `docker/build-push-action` steps in %d "
             "GitHub Actions files, %d not resolved, %d naming no context or Dockerfile of the checkout; steps not "
             "resolved: %s; Actions files not read: %s), %d not built by any (%s); their `COPY`/`ADD` sources: %d "
             "from the context (%d matched, %d matching nothing, %d leaving it), %d from a stage or image, "
             "%d heredocs, %d remote, %d holding a variable (not resolved); %d instructions malformed." % (
                 dk["dockerfiles"], dk["dockerfiles_built"], dk["builds"], dk["compose_files"],
                 dk["builds_unresolved"], dk["builds_missing"],
                 "%d (%s)" % (dk["compose_unreadable"]["count"], _some(dk["compose_unreadable"]))
                 if dk["compose_unreadable"]["count"] else "none", wf["builds"], wf["steps"], wf["files"],
                 wf["builds_unresolved"], wf["builds_missing"],
                 ", ".join("%s %d" % (k, n) for k, n in wf["steps_unresolved"].items() if n) or "none",
                 "%d (%s)" % (wf["unreadable"]["count"], _some(wf["unreadable"])) if wf["unreadable"]["count"]
                 else "none", dk["dockerfiles_not_built"]["count"],
                 _some(dk["dockerfiles_not_built"]) or "none", dk["sources"]["context"],
                 dk["context_sources"]["matched"], dk["context_sources"]["no_match"],
                 dk["context_sources"]["leaves_context"], dk["sources"]["stage"], dk["sources"]["heredoc"],
                 dk["sources"]["remote"], dk["sources"]["variable"], dk["malformed"]), "",
             "Kustomization files %d (not read: %s): path references %d (%d resolved, %d naming nothing of the "
             "checkout (files: %s), %d naming a directory with no kustomization file (files: %s), %d leaving the root, "
             "%d a repository's path), %d "
             "remote, %d inline, %d not a path; manifests they deploy (`resources`, `bases`, `crds`): %d files "
             "(not read: %s), %d documents (%s), %d empty; Kubernetes manifests beside a kustomization file "
             "that none names: %s." % (
                 kz["files"], "%d (%s)" % (kz["unreadable"]["count"], _some(kz["unreadable"]))
                 if kz["unreadable"]["count"] else "none", kz["references"]["path"], kz["paths"]["resolved"],
                 kz["paths"]["missing"], _some(kz["missing_files"]) or "none", kz["paths"]["no_kustomization"],
                 _some(kz["no_kustomization_files"]) or "none", kz["paths"]["leaves_root"], kz["paths"]["remote"],
                 kz["references"]["remote"], kz["references"]["inline"], kz["references"]["not_a_path"],
                 kz["manifests"]["files"], "%d (%s)" % (kz["manifests"]["unreadable"]["count"],
                                                        _some(kz["manifests"]["unreadable"]))
                 if kz["manifests"]["unreadable"]["count"] else "none", kz["manifests"]["documents"],
                 ", ".join("%s %d" % kv for kv in kz["manifests"]["kinds"].items()) or "none",
                 kz["manifests"]["empty_documents"],
                 "%d (%s)" % (kz["unreferenced"]["count"], _some(kz["unreferenced"]))
                 if kz["unreferenced"]["count"] else "none"), "",
             "Code files whose references are not read (`OTHER_CODE_EXTENSIONS` by extension, `CODE_FILE_NAMES` "
             "by name: other languages, shell, Terraform, Dockerfiles no build names, Makefiles, SQL, GraphQL, "
             "protobuf, jq): %s." % (
                 ", ".join("%s %d (%d in no project)" % (ext, n, cov["unread_code_files_outside_projects"].get(ext, 0))
                           for ext, n in cov["unread_code_files"].items()) or "none"), "",
             "Dependency manifests found and not read (`MANIFESTS_NOT_READ`; `package.json` outside the npm "
             "workspaces): %s." % (_listed(cov["unread_manifests"]) or "none"), "",
             "Files of no stated kind (an extension in none of the lists, nor in `NOT_CODE_EXTENSIONS`): %s; "
             "files with no extension and no `CODE_FILE_NAMES` name: %s." % (
                 _listed(cov["unclassified_files"]) or "none",
                 _listed({"": cov["files_without_extension"]}).lstrip() or "none"), ""]
    if cov["unparsed_manifests"]:
        lines += ["Manifests not parsed: %s." % ", ".join(cov["unparsed_manifests"]), ""]
    lines += ["```mermaid", "flowchart LR"]
    for group, members in sorted(groups.items()):
        lines.append("  subgraph g%d[%s]" % (sorted(groups).index(group), _label(group)))
        for p in members:
            lines.append("    %s[%s]" % (ids[p["dir"]], _label(p["name"])))
        lines.append("  end")
    for e in m["edges"]:
        lines.append("  %s -->|%s| %s" % (ids[e["from"]], " ".join(e["kinds"]), ids[e["to"]]))
    lines += ["```", "", "| project | directory | manifests | depends on |", "|---|---|---|---|"]
    names = {p["dir"]: p["name"] for p in m["projects"]}
    out: dict[str, list[str]] = {d: [] for d in dirs}
    for e in m["edges"]:
        out[e["from"]].append("%s (%s)" % (names[e["to"]], " ".join(e["kinds"])))
    for p in m["projects"]:
        lines.append("| %s | %s | %s | %s |" % (p["name"], p["dir"], " ".join(p["kinds"]), ", ".join(out[p["dir"]])))
    return "\n".join(lines) + "\n"


# ------------------------------------------------------------------------------------------------------ delta


# Each list of a map: its entries' string fields (each also has ``kinds``, a list of strings) and the fields that
# identify an entry; the other fields are what ``map_delta`` compares. The one source of check_map and map_delta.
MAP_PARTS = {"projects": (("dir", "name"), ("dir",)), "edges": (("from", "to"), ("from", "to"))}


MAP_DEPTH = 64  # the deepest usable map file (module docstring)


def _depth(value: Any) -> int:
    """How many objects and lists deep ``value`` nests (a scalar 0); by a stack, so any depth is measured."""
    deepest, stack = 0, [(value, 1)]
    while stack:
        item, level = stack.pop()
        if isinstance(item, (dict, list)):
            deepest = max(deepest, level)
            stack.extend((child, level + 1) for child in (item.values() if isinstance(item, dict) else item))
    return deepest


class MapUnusable(ValueError):
    """A map file ``delta`` cannot read; the text is built here and names the field."""


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _strings(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(v, str) for v in value)


def check_map(m: Any) -> None:
    """Raise ``MapUnusable`` unless ``m`` has the shape the module docstring's delta rules read."""
    if not isinstance(m, dict):
        raise MapUnusable("map is not an object")
    if _depth(m) > MAP_DEPTH:
        raise MapUnusable("map nests deeper than %d" % MAP_DEPTH)
    for key, (names, ident) in MAP_PARTS.items():
        items = m.get(key)
        if not isinstance(items, list):
            raise MapUnusable("%s is not a list" % key)
        seen = set()
        for item in items:
            if not (isinstance(item, dict) and all(isinstance(item.get(n), str) for n in names)
                    and _strings(item.get("kinds"))):
                raise MapUnusable("%s holds an entry without string %s and a list of string kinds"
                                  % (key, " and ".join(names)))
            k = tuple(item[n] for n in ident)
            if k in seen:
                raise MapUnusable("%s holds one %s twice" % (key, " and ".join(ident)))
            seen.add(k)
    if not isinstance(m.get("coverage"), dict):
        raise MapUnusable("coverage is not an object")


def _keyed(part: str, base: list, head: list) -> dict[str, list]:
    names, ident = MAP_PARTS[part]
    compared = [n for n in names + ("kinds",) if n not in ident]
    b = {tuple(x[n] for n in ident): x for x in base}
    h = {tuple(x[n] for n in ident): x for x in head}
    changed = []
    for k in sorted(b.keys() & h.keys()):
        if any(b[k][c] != h[k][c] for c in compared):  # strings and lists of strings (check_map)
            changed.append(dict(zip(ident, k), base=b[k], head=h[k]))
    return {"added": [h[k] for k in sorted(h.keys() - b.keys())],
            "removed": [b[k] for k in sorted(b.keys() - h.keys())],
            "changed": changed}


def _leaves(base: dict, head: dict, path: list[str], out: list[dict]) -> None:
    for key in sorted(base.keys() | head.keys()):
        here = path + [key]
        if key not in head:
            out.append({"path": here, "base": base[key]})
        elif key not in base:
            out.append({"path": here, "head": head[key]})
        elif isinstance(base[key], dict) and isinstance(head[key], dict):
            _leaves(base[key], head[key], here, out)
        elif _canonical(base[key]) != _canonical(head[key]):
            out.append({"path": here, "base": base[key], "head": head[key]})


def map_delta(base: dict[str, Any], head: dict[str, Any]) -> dict[str, Any]:
    """The delta of two usable maps (``check_map``), by the module docstring's rules."""
    delta: dict[str, Any] = {part: _keyed(part, base[part], head[part]) for part in MAP_PARTS}
    coverage: list[dict] = []
    _leaves(base["coverage"], head["coverage"], [], coverage)
    delta["coverage"] = coverage
    delta["same"] = not coverage and not any(v for part in MAP_PARTS for v in delta[part].values())
    return delta


def read_map(path: str) -> dict[str, Any]:
    try:
        with open(path, "rb") as fh:
            m = cli.loads(fh.read().decode("utf-8"))
        check_map(m)
    except (OSError, ValueError) as exc:  # MapUnusable is a ValueError
        raise MapUnusable("%s: %s" % (path, cli.cause(exc))) from None
    return m


def main(argv: list[str]) -> int:
    if len(argv) == 3 and argv[0] == "delta":
        try:
            delta = map_delta(read_map(argv[1]), read_map(argv[2]))
        except MapUnusable as exc:
            print(json.dumps({"ok": False, "error": cli.cause(exc)}, sort_keys=True))
            return 2
        print(json.dumps(delta, sort_keys=True))
        return 0 if delta["same"] else 1
    if len(argv) < 2 or argv[0] not in ("brain", "check", "target", "coverage", "map") or not os.path.isdir(argv[1]):
        print(USAGE, file=sys.stderr)
        return 2
    command, root, rest = argv[0], argv[1], argv[2:]
    if command == "brain" and not rest:
        sys.stdout.write(render_brain(brain_map(root)))
        return 0
    if command == "check" and not rest:
        problems = register_problems(brain_map(root))
        print(json.dumps({"ok": not problems, "problems": problems}, sort_keys=True))
        return 1 if problems else 0
    if command == "target" and len(rest) == 2 and rest[0] == "--source":
        sys.stdout.write(render_target(target_map(root), rest[1]))
        return 0
    if command == "map" and not rest:
        print(json.dumps(target_map(root), sort_keys=True))
        return 0
    if command == "coverage" and not rest:
        print(json.dumps(target_map(root)["coverage"], sort_keys=True))
        return 0
    print(USAGE, file=sys.stderr)
    return 2


FAULT_LINE = cli.GENERIC_LINE


if __name__ == "__main__":
    sys.exit(cli.run(main, sys.argv[1:], FAULT_LINE))
