"""``profile.fit``: for each unit candidate of a tree, the stage-0 recipe its own npm scripts (or Nx targets) give,
judged by ``unit_verify.check_recipe``; the first candidate that passes is the brain's ``units.json`` proposal (stage 0).

Rules: asama-0/08 "Birim seçimi" (the operator names the candidate units in order in ``targets[]``; MF4 and MF6
check the bold criteria mechanically; when a candidate fails, the next one is tried), tohum/26c (the recipe; the
brain proposes ``targets/<target>/units.json``, which ``çek`` reads: ``loop.cek``), MF4 (``profile.derive``: the
candidates, in the operator's order when ``targets[]`` names them, else every ``package.json`` directory, sorted)
and MF6 (``unit_verify.check_recipe`` with the tree is the one judge; this module adds no reason of its own).

**The composed recipe** (``compose``) for candidate ``path``:

- ``unit_id``: ``path`` with every character outside ``[A-Za-z0-9._-]`` written ``-`` and a leading ``.``,
  ``_`` or ``-`` dropped; ``root`` for ``.``; at most 128 characters.
- ``lockfiles``: ``[derive.nearest_lock]`` (the lock MF4 reads for the candidate), ``[]`` when there is none.
- ``toolchain``: ``node@<text>`` of ``unit_verify.nearest_version`` with a leading ``v`` dropped (``node@`` when
  there is no version file); ``env_image``: ``images[<that text>]`` when given, else ``""``.
- ``inputs``: ``path``, the lock, the version file, the files the commands name (below) and what they reach
  (``reached``), the ones another covers left out (``derive.minimal``). What an input reaches, transitively from
  ``path`` and those files (``path`` ``.`` covers the tree and reaches nothing more):

  - a directory input's ``package.json`` names in ``unit_verify.DEP_FIELDS``, each looked up as Node does,
    ``<dir>/node_modules/<name>`` for ``<dir>`` the input's directory and then each directory above it up to the
    lock's, the first key of the lock found winning: when that key is a workspace link MF5 takes
    (``runner.deps_npm.live_workspaces``, an in-repo ``file:`` dependency included, since npm writes it in the
    same form), its folder, an input as the lock names it (a folder missing from the tree is ``check_recipe``'s
    ``input_missing``);
  - every import specifier (``jsimports.specifiers``) of a JS/TS file (``jsimports.SOURCE_EXTENSIONS``) of an
    input, a directory being walked by ``jsimports.walk``, the ``preset`` of a jest configuration there
    (``jsimports.jest_preset``) and every ``extends`` of a ``tsconfig*.json`` there: a
    relative one is the path it names from the file's directory (none when it leaves the tree); a bare one is
    both the path a root tsconfig alias gives (``jsimports.alias_path``) and the workspace folder its package
    (``jsimports.package_name``) links to by the lookup above, started at the file's directory;
  - a reached path an input already covers brings nothing. Another, but a linked folder, brings the deepest
    directory at or above it, below the root, holding a ``package.json`` or ``project.json``, else the path
    itself; the path is the one that exists as written (a directory too) or with one of ``EXTENSIONS`` (no
    symbolic link on its way); a path that does not exist brings the project of a directory above it only, so a
    path into no project brings nothing.

  So a workspace package reached by an alias or by an undeclared import, and the root tsconfig a project's
  extends, are inputs. Not reached, stated (their need shows only in ``verify``'s 3/3 run): an Nx implicit
  dependency, a path written in a configuration value other than an import, a tsconfig ``extends`` and a jest
  ``preset`` (jest's ``moduleNameMapper`` or ``setupFiles``, ESLint's ``parserOptions.project``), a bare jest
  preset's own ``jest-preset`` file (its package is the lock's, or the link's folder), an import whose specifier is
  not a string literal, a ``paths`` alias of a tsconfig other than the root's, tsconfig ``references``, a file
  read at run time, and a file type other than JS/TS and tsconfig (``.vue``, ``.svelte``, CSS). An import inside
  a comment or a string is not one (``jsimports.code_view``, whose lexing limits are stated there); a whole
  project directory is an input when one of its files is reached, so an input may be more than the run needs.
- ``install_scripts_required``: the lock keys whose entry says ``hasInstallScript: true`` (MF5's lock reading),
  sorted. A script only a tarball declares is not known before the fetch (MF5 refuses it then).
- ``lint_cmd``: ``npm --prefix <path> run --silent lint -- --format json``; ``test_cmd`` and
  ``affected_test_cmd``: ``npm --prefix <path> run --silent test`` (stage 0's affected set is the unit's whole
  test set, asama-0/08 item 6). npm runs the owner's own script in ``<path>`` with ``<path>/node_modules/.bin``
  and every directory above it on ``PATH``, writes nothing of its own to stdout with ``--silent`` and exits with
  the script's code (npm 10.9.9, measured). ``check_recipe`` judges such a command's script and programs
  (``script_missing``, ``script_not_installed``). Not judged here: whether the lint tool is ESLint and takes
  ``--format json`` (``verify``'s ``lint_output:`` shows it), whether the tests need services, and anything
  else only a run shows.
- When the ``lint`` script of ``path/package.json`` has the program ``eslint`` (one of
  ``unit_verify.script_programs``: the word itself, so not ``npx eslint``, a path to its binary or a wrapper that
  starts it), the flat config ESLint's own lookup finds joins ``inputs`` and is followed like the Nx files:
  npm runs the script in ``path``, and ESLint takes the first of ``nx.ESLINT_FLAT_CONFIGS`` that is a file (a
  symbolic link to one counts) in that directory, else in each directory above it (eslint 9.39.4,
  ``lib/config/config-loader.js``; here up to the tree's root, the worktree's top in the container). No such file:
  nothing joins. Not read, stated: the script's own options (with ``--config`` or ``-c`` ESLint reads the file
  named there and the looked-up one is an input the run does not need; ``--flag v10_config_lookup_from_file``
  starts the lookup at each linted file), ``ESLINT_USE_FLAT_CONFIG=false``, an ESLint before 9 (it reads an
  eslintrc file unless ``eslint.config.js`` is there), an eslintrc file of any version, and the ``test`` script's
  tool configuration (a jest or vitest config outside ``path``).
- When ``path/package.json`` has no ``lint`` (or no ``test``) script, that command (``test`` giving
  ``affected_test_cmd`` too) is the candidate's Nx target as ``profile.nx`` composes it (an ``@nx/eslint:lint`` or
  ``@nx/jest:jest`` target of ``path/project.json`` in a workspace whose ``nx.json`` and lock are at the tree's
  root, or, with no ``lint`` key in ``project.json``, the ``lint`` target ``@nx/eslint/plugin`` infers; its rules
  and refusals are there), and the files it names (the flat ESLint config, the jest config) join ``inputs``;
  when ``profile.nx`` refuses, the npm form above stays and ``check_recipe`` refuses it
  (``script_missing``). The npm script, when there is one, always wins.
- ``services``: ``[]``; ``limits``: ``{}`` (the operator's values apply).

**Result** (``fit``): ``{candidates, fit, rows}``: one row ``{path, reasons, recipe, sources}`` per candidate of the
derivation, in its order, ``reasons`` being ``check_recipe``'s (an ineligible candidate shows as
``profile:units[0]:unit_not_eligible:<path>``; ``sources`` from ``commands``, ``{lint, test}`` each ``npm_script``,
``nx_target`` or ``none:<profile.nx's reason>``); ``fit`` lists the paths with no reason. Passing this static
check is not verification: ``verify`` (3/3 at HEAD, contained) is.

Command line, no stdin; one JSON line on stdout::

    python -m profile.fit TREE [--target TARGET.json] [--policy POLICY.json] [--images IMAGES.json] [--units OUT]

``TREE`` a directory, read only; ``TARGET`` the ``targets[]`` entry; ``POLICY`` the referee's ``policy.json``;
``IMAGES`` a JSON object from a version (``X.Y.Z``) to an image reference. With ``--units``, ``OUT`` is written
as ``{"units": [<the first passing recipe>]}`` when one passes (stage 0 runs exactly one unit) and is not
touched otherwise. Exit 0 when a candidate passes, 1 when none does, 2 on unusable input (``{ok: false,
error}``).
"""

from __future__ import annotations

import json
import os
import posixpath
import re
import sys
from typing import Any

from profile import derive as D
from profile import jsimports as J
from profile import nx as X
from profile import unit_verify as U
from runner import deps_npm as N
import cli

LINT_CMD = ("run", "--silent", "lint", "--", "--format", "json")
TEST_CMD = ("run", "--silent", "test")
ESLINT = "eslint"  # the program word of a lint script whose flat config is looked up (module docstring)
UNSAFE_ID = re.compile(r"[^A-Za-z0-9._-]")
EXTENSIONS = (".ts", ".tsx", ".d.ts", ".mts", ".cts", ".js", ".jsx", ".mjs", ".cjs", ".json")
PROJECT_MARKERS = ("package.json", "project.json")


def unit_id(path: str) -> str:
    if path == ".":
        return "root"
    return UNSAFE_ID.sub("-", path).lstrip("._-")[:128] or "root"


def install_marks(tree: str, lock: str | None) -> list[str]:
    _, parsed = D._json(tree, lock) if lock else (False, None)
    return sorted(row["key"] for row in N.entries(parsed)[1] if row["entry"].get("hasInstallScript") is True)


def _declared(tree: str, directory: str) -> list[str]:
    """The names ``<directory>/package.json`` declares in ``unit_verify.DEP_FIELDS``, sorted; none when unreadable."""
    _, manifest = D._json(tree, posixpath.join(directory, "package.json"))
    names = set()
    for field in U.DEP_FIELDS if isinstance(manifest, dict) else ():
        if isinstance(manifest.get(field), dict):
            names.update(n for n in manifest[field] if isinstance(n, str))
    return sorted(names)


def _lookup(packages: dict, start: str, name: str) -> str | None:
    """Node's lookup of ``name`` from directory ``start`` (relative to the lock's directory): the first lock key
    ``<dir>/node_modules/<name>`` for ``<dir>`` ``start`` and then each directory above it, up to the lock's."""
    directory = start
    while True:
        key = "node_modules/" + name if directory == "." else directory + "/node_modules/" + name
        if key in packages:
            return key
        if directory == ".":
            return None
        directory = posixpath.dirname(directory) or "."


def _existing(tree: str, path: str) -> str | None:
    """``path``, or the first of it with an extension Node or TypeScript adds (``.json`` too, for a tsconfig's
    ``extends``), that exists with no symbolic link on its way; None when none does (a directory exists as
    written, so its ``index`` file needs no try of its own)."""
    tries = [path] + [path + e for e in EXTENSIONS]
    return next((t for t in tries if os.path.lexists(os.path.join(tree, t)) and D._input_where(tree, t) == ""), None)


def _is_file(tree: str, path: str) -> bool:
    return os.path.isfile(os.path.join(tree, path)) and D._input_where(tree, path) == ""


def _unit(tree: str, path: str) -> str | None:
    """The input a reached tree path brings (module docstring): its deepest project directory, else the existing
    path itself, else nothing."""
    found = _existing(tree, path)
    is_dir = found is not None and os.path.isdir(os.path.join(tree, found))
    probe = found if is_dir else posixpath.dirname(found or path)
    while probe:
        if any(_is_file(tree, posixpath.join(probe, m)) for m in PROJECT_MARKERS):
            return probe
        probe = posixpath.dirname(probe)
    return found


def _references(tree: str, entry: str) -> list[tuple[str, str]]:
    """``(file, reference)`` for every JS/TS file and tsconfig of input ``entry`` (a file, or a directory walked by
    ``jsimports.walk``): the file's import specifiers, the tsconfig's ``extends``."""
    if os.path.isdir(os.path.join(tree, entry)):
        if D._real_dir(tree, entry):
            return []
        names = [posixpath.join(entry, f) for f in J.walk(os.path.join(tree, entry))[0]]
    else:
        names = [entry]
    out = []
    for name in names:
        is_tsconfig = J.TSCONFIG.fullmatch(posixpath.basename(name)) is not None
        if not is_tsconfig and posixpath.splitext(name)[1] not in J.SOURCE_EXTENSIONS:
            continue
        data = D._read_regular(tree, name)
        text = data.decode("utf-8", "replace") if data is not None else ""
        refs = J.extends(text) if is_tsconfig else J.specifiers(text)
        if J.JEST_CONFIG.fullmatch(posixpath.basename(name)):
            refs += [p for p in [J.jest_preset(text)] if p]
        out += [(name, r) for r in refs]
    return out


def reached(tree: str, path: str, lock: str | None, seeds=(), memo: dict | None = None) -> list[str]:
    """The inputs candidate ``path`` reaches beyond itself and ``seeds`` (module docstring), as tree paths, sorted;
    ``memo`` (one per tree, unchanged while it is used) keeps each input's references for the next call."""
    memo = {} if memo is None else memo
    if path == ".":
        return []
    packages, links = {}, {}
    if lock is not None:
        _, parsed = D._json(tree, lock)
        packages = parsed.get("packages") if isinstance(parsed, dict) else None
        packages = packages if isinstance(packages, dict) else {}
        links, _ = N.live_workspaces(packages) if packages else ({}, None)
    lock_dir = posixpath.dirname(lock) if lock else ""
    alias_name = J.alias_file({n for n in J.ALIAS_FILES if D._read_regular(tree, n) is not None})
    try:
        table = J.aliases(D._read_regular(tree, alias_name).decode("utf-8")) if alias_name else []
    except (ValueError, UnicodeDecodeError, RecursionError, AttributeError):
        table = []

    def in_lock(tree_path: str) -> str | None:  # tree path -> relative to the lock's directory, None outside it
        if not lock_dir:
            return tree_path or "."
        if tree_path == lock_dir:
            return "."
        return tree_path[len(lock_dir) + 1:] if tree_path.startswith(lock_dir + "/") else None

    def linked(start: str, name: str) -> str | None:  # a workspace folder, as a tree path, by Node's lookup
        here = in_lock(start)
        key = _lookup(packages, here, name) if here is not None and packages else None
        folder = links.get(key) if key else None
        return (posixpath.join(lock_dir, folder) if lock_dir else folder) if folder else None

    have = [path] + list(seeds)
    found: set[str] = set()
    todo = list(have)
    while todo:
        entry = todo.pop()
        targets = []  # (tree path, whether it is an input as it is: a workspace folder the lock links)
        if os.path.isdir(os.path.join(tree, entry)):
            targets += [(linked(entry, name), True) for name in _declared(tree, entry)]
        if entry not in memo:
            memo[entry] = _references(tree, entry)
        for name, ref in memo[entry]:
            if J.is_relative(ref):
                targets.append((posixpath.join(posixpath.dirname(name), ref), False))
                continue
            targets.append((J.alias_path(ref, table), False))
            package = J.package_name(ref)
            if package is not None:
                targets.append((linked(posixpath.dirname(name) or ".", package), True))
        for target, direct in targets:
            target = D.norm_path(target)
            if target in (None, ".") or any(D.covers(q, target) for q in have + sorted(found)):
                continue
            unit = target if direct else _unit(tree, target)
            if unit is not None and not any(D.covers(q, unit) for q in have + sorted(found)):
                found.add(unit)
                todo.append(unit)
    return sorted(found)


def commands(tree: str, path: str) -> dict:
    """``{lint_cmd, test_cmd, inputs, sources}`` of candidate ``path``: for ``lint`` and ``test`` each, the npm form
    when ``<path>/package.json`` has the script, else the Nx target's command when ``profile.nx`` composes it, else
    the npm form (which ``check_recipe`` refuses as ``script_missing``); ``sources[name]`` is ``npm_script``,
    ``nx_target`` or ``none:<profile.nx's reason>``; ``inputs`` the files the Nx commands add and the flat config
    of an npm lint script that runs ``eslint`` (module docstring)."""
    _, manifest = D._json(tree, "package.json" if path == "." else posixpath.join(path, "package.json"))
    scripts = manifest.get("scripts") if isinstance(manifest, dict) else None
    npm = {"lint": ["npm", "--prefix", path] + list(LINT_CMD), "test": ["npm", "--prefix", path] + list(TEST_CMD)}
    out: dict = {"inputs": [], "sources": {}}
    for name, nx in (("lint", X.lint), ("test", X.test)):
        out[name + "_cmd"] = npm[name]
        if isinstance(scripts, dict) and isinstance(scripts.get(name), str):
            out["sources"][name] = "npm_script"
            if name == "lint" and ESLINT in (U.script_programs(scripts[name]) or []):
                config = X.flat_config(tree, path, X.ESLINT_FLAT_CONFIGS, os.path.isfile)
                out["inputs"] += [config] if config else []
            continue
        try:
            out[name + "_cmd"], extra = nx(tree, path)
        except X.NotComposed as exc:
            out["sources"][name] = "none:" + exc.reasons[0]
            continue
        out["sources"][name] = "nx_target"
        out["inputs"] += extra
    return out


def compose(tree: str, path: str, images: dict | None = None, memo: dict | None = None) -> dict:
    """The recipe of candidate ``path`` (module docstring)."""
    found = commands(tree, path)
    lock = D.nearest_lock(tree, path)
    version_file, text = U.nearest_version(tree, path)
    version = text[1:] if text and text.startswith("v") else (text or "")
    image = (images or {}).get(version)
    return {
        "unit_id": unit_id(path),
        "path": path,
        "inputs": D.minimal([p for p in (path, lock, version_file) if p] + found["inputs"]
                            + reached(tree, path, lock, found["inputs"], memo)),
        "toolchain": "node@" + version,
        "env_image": image if isinstance(image, str) else "",
        "lockfiles": [lock] if lock else [],
        "install_scripts_required": install_marks(tree, lock),
        "lint_cmd": found["lint_cmd"],
        "test_cmd": found["test_cmd"],
        "affected_test_cmd": list(found["test_cmd"]),
        "services": [],
        "limits": {},
    }


def fit(tree: str, target: Any = None, policy: Any = None, images: dict | None = None) -> dict:
    """Every candidate's composed recipe and ``check_recipe``'s reasons (module docstring)."""
    derived = U.derived_profile(tree, target, policy)
    rows, memo = [], {}
    for candidate in derived["unit_candidates"]:
        if D.norm_path(candidate["path"]) is None:
            rows.append({"path": candidate["path"], "reasons": ["invalid:path"], "recipe": None})
            continue
        recipe = compose(tree, candidate["path"], images, memo)
        rows.append({"path": candidate["path"], "reasons": U.check_recipe(recipe, policy, tree, target, derived),
                     "recipe": recipe, "sources": commands(tree, candidate["path"])["sources"]})
    return {"candidates": len(rows), "fit": [r["path"] for r in rows if not r["reasons"]], "rows": rows}


def _load(path: str) -> Any:
    try:
        with open(path, encoding="utf-8") as fh:
            return cli.load(fh)
    except RecursionError:
        raise ValueError("%s: JSON nested too deeply" % path) from None


USAGE = ("usage: python -m profile.fit TREE [--target TARGET.json] [--policy POLICY.json] [--images IMAGES.json]"
         " [--units OUT]")
OPTIONS = ("--target", "--policy", "--images", "--units")


def main(argv: list[str]) -> int:
    try:
        if not argv or len(argv) % 2 != 1 or argv[0].startswith("-"):
            raise ValueError(USAGE)
        opts = dict(zip(argv[1::2], argv[2::2]))
        if any(k not in OPTIONS for k in opts) or len(opts) != len(argv) // 2:
            raise ValueError(USAGE)
        target = _load(opts["--target"]) if "--target" in opts else None
        policy = _load(opts["--policy"]) if "--policy" in opts else None
        images = _load(opts["--images"]) if "--images" in opts else None
        if target is not None and not isinstance(target, dict):
            raise ValueError("target is not an object")
        if images is not None and not isinstance(images, dict):
            raise ValueError("images is not an object")
        report = fit(argv[0], target, policy, images)
    except (D.DeriveError, U.VerifyError, ValueError, OSError) as exc:
        _emit({"ok": False, "error": "unusable input: %s" % cli.cause(exc)})
        return 2
    passing = [r["recipe"] for r in report["rows"] if not r["reasons"]]
    if passing and "--units" in opts:
        with open(opts["--units"], "w", encoding="utf-8") as fh:
            json.dump({"units": passing[:1]}, fh, indent=2, sort_keys=True)
            fh.write("\n")
    _emit(dict(report, ok=bool(passing)))
    return 0 if passing else 1


def _emit(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj, sort_keys=True, separators=(",", ":")) + "\n")


def FAULT_LINE(argv: list[str]) -> dict:  # noqa: N802 - cli.run's fault line
    return {"ok": False, "error": "internal error"}


if __name__ == "__main__":
    sys.exit(cli.run(main, sys.argv[1:], FAULT_LINE))
