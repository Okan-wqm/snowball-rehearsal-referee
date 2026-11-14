"""``unit.verify``: a unit recipe is checked statically, then its lint and service-free tests run 3/3 at
HEAD with only the recipe's ``inputs`` and the fetched dependencies, contained and without network
(stage 0, MF6).

Rules: tohum/14 and 26c (the recipe ``{unit_id, path, inputs[], toolchain, env_image (@sha256),
lockfiles[], install_scripts_required[], lint_cmd[], test_cmd[], affected_test_cmd[], services: [],
limits{}}``; ``inputs`` are proven sufficient only by a 3/3 green run with those inputs alone; the image
is the official toolchain image of the version in the repository's version file; ``services`` empty in
stage 0), tohum/26a (``unit.verify``: recipe, tree and ``deps`` in; verified recipe or refusal and the
3/3 results out; ``limit_hit:<key>``), asama-0/06 (only the unit's ``inputs`` enter the worktree; the
container installs the dependencies without network and without scripts; a marked package's script runs
in ``koş`` without network), asama-0/08 criterion 6 and unit criteria 4 and 5, asama-0/09 test 48, tohum/18a
(``operating{}``), tohum/29d and 29g (group ``recipe``: ``vector_check`` below). It calls
``runner.lint_record`` (step 6), MF3 (``runner.contained``), MF5 (``runner.deps_npm``) and MF4
(``profile.derive``: the recipe's path and inputs against the derivation, the exclusions while the inputs are
copied, and criterion 5's coverage).

``verify``'s static check (``check_recipe``; every reason listed):

- Fields: every recipe field is required (``missing:<field>``), no other field is allowed
  (``field_not_in_recipe:<field>``).
- ``unit_id`` ``[A-Za-z0-9][A-Za-z0-9._-]{0,127}``; ``path`` and every input a relative path inside the
  tree (``invalid:<field>``); some input covers ``path`` (``inputs_miss_unit_path``); no input is or holds
  ``.snowball``, the verifier's own directory in the worktree (``reserved_path``).
- ``toolchain`` is exactly ``node@X.Y.Z`` (stage 0 has one ecosystem, npm; ``invalid:toolchain``).
- ``env_image`` is pinned by digest as ``run.contained`` requires (``image_not_pinned``), its repository is
  the official one, ``node`` or ``docker.io/library/node`` (``image_not_official``), and its tag is
  ``X.Y.Z`` or ``X.Y.Z-<variant>`` with the toolchain's version (``image_version_mismatch``).
- ``lockfiles`` is exactly one path named ``package-lock.json`` or ``npm-shrinkwrap.json``
  (``invalid:lockfiles``), covered by an input (``lockfile_not_in_inputs``), in the unit's directory or
  one of its ancestors (``lockfile_not_for_unit``).
- ``install_scripts_required`` a list of strings (their form is MF5's ``runner.deps_npm.Marks``, read against
  the lock below: a key of the lock or ``name@version``; any other element is ``lock:mark_not_usable:<element>``).
- ``lint_cmd``, ``test_cmd`` and ``affected_test_cmd`` non-empty lists of non-empty strings without NUL
  (``invalid:<field>``; an empty ``affected_test_cmd`` is refused as group ``recipe`` refuses it,
  tohum/29g). ``affected_test_cmd`` is not run here (stage 0's affected set is the unit's whole
  service-free test set, asama-0/08 item 6).
- ``services`` is ``[]`` (``services_not_empty``).
- ``limits`` an object whose keys are ``operating{}`` keys (``limit_key_unknown:<key>``) and whose values are
  positive integers (``invalid:limits.<key>``); given the policy's ``operating``, a value may tighten the
  operator's value but not loosen it (``limit_above_operating:<key>``) and stays inside the band
  (``limit_below_band:<key>``). The run uses the smaller of the two.
- With the tree: ``profile.derive check`` of ``{units: [recipe]}`` (reasons prefixed ``profile:``: the path
  is an eligible candidate, inputs not excluded, present, not behind a symlink); the version file
  nearest to the unit's directory (walking up to the root; in one directory ``.nvmrc``, then
  ``.node-version``, then a ``node``/``nodejs`` line of ``.tool-versions``) must exist
  (``version_file_missing``), name an exact ``X.Y.Z`` with an optional leading ``v``
  (``version_file_not_exact``) and equal the toolchain's (``toolchain_version_mismatch``); the lock must be
  a regular file with no symlink on its way (``lockfile_missing``) and pass MF5's static check with the
  recipe's marks (``lock:<reason>``).
- With the tree, the commands against the lock (``cmd_not_installed:<field>:<element>``, the element as
  written). Only ``node_modules`` paths are judged, because the worktree has no other source for them: the
  copy leaves every ``node_modules`` name out (casefolded) and the install writes only
  ``<lock dir>/<lock key>/`` and ``.bin`` links (step 2). An element of ``lint_cmd``, ``test_cmd`` or
  ``affected_test_cmd`` that is a relative path (``derive.norm_path``; ``/work/<path>`` is read as ``<path>``;
  any other absolute path, and an element starting with ``-``, an option, is not judged) with a component
  equal to ``node_modules`` after casefold is installed only when it is below the lock's directory (paths are
  read from ``/work``, the tree's root) and, below it, it lies in a package of the lock (a key MF5's lock
  reading takes, ``runner.deps_npm.entries``: not ``""``, a chain of ``node_modules/<name>`` at the top or below
  a workspace folder; or a workspace link MF5 takes, ``runner.deps_npm.live_workspaces``, which step 2 makes a
  symlink to its folder), followed by nothing or by a rest with no ``node_modules`` component; or it is a
  directory on the way to such a key; or
  it is exactly ``<P>/.bin/<name>`` where a key ``<P>/<package>`` (``<package>`` one name or ``@scope/name``)
  has a lock ``bin`` naming ``<name>`` (an object with that key, or a string and ``<name>`` the bare part of
  the package's name as MF5 reads it, as step 2 reads a package's ``bin``). The lock's ``bin`` stands for the
  tarball's here, as npm writes it from the package's ``package.json``; a lock without it refuses that
  ``.bin`` path. Not judged: whether the file exists inside the package, a path inside an option
  (``--config=x/node_modules/y``) or another element (``sh -c`` text), a bare program name (``vitest``,
  ``npx``), and imports or configuration that reach outside the inputs: those show in the run as a red or
  failing command, as before.
- With the tree, a command of exactly the form ``npm --prefix <dir> run --silent <script>``, optionally followed
  by ``--`` and arguments (``npm_run``; ``<dir>`` read as a path like the elements above, ``<script>`` not
  starting with ``-``; any other ``npm`` form is not judged): ``<dir>/package.json`` is a JSON object whose
  ``scripts`` maps ``<script>`` to a string (``script_missing:<field>:<script>``), and each program of that
  script (``script_programs``: the first word of every simple command, ``shlex`` POSIX with
  ``punctuation_chars``, ``NAME=value`` words and redirection targets skipped) that is known as an npm program
  (``npm_programs``: a dependency declared by the ``package.json`` of ``<dir>`` or of a directory above it, or a
  ``bin`` name of a package of a lock there) and is a plain name (``[A-Za-z0-9._-]``) is
  installed: the lock's directory is ``<dir>`` or above it (npm puts ``<dir>/node_modules/.bin`` and every
  directory's above it on ``PATH``, and only the lock's ``node_modules`` exists in the worktree) and
  ``<d>/node_modules/.bin/<program>`` is installed by the rule above for ``<d>`` the ``<dir>`` itself or a
  directory above it up to the lock's directory (a workspace member's own nested ``.bin`` included)
  (``script_not_installed:<field>:<program>``, once per field and program). Not judged: a program known as
  neither (``rm``, a global tool), a program written as a path or with ``$``, the scripts a script runs through
  ``npm run`` (only the first level), a script ``shlex`` cannot read, and whether the program accepts the
  arguments.
- The tree checks run when no reason above is about a field they read: a reason about ``unit_id``,
  ``env_image``, ``services`` or ``limits`` alone does not stop them (``TREE_FREE_FIELDS``), so every reason of
  both kinds is listed; any other reason (a field the tree checks read, ``field_not_in_recipe``) stops them.

The run (``verify``), only when the static check passes (steps 1-3 are ``stage``, which ``runner.kos`` shares, so
``koş``'s results come from the same worktree):

1. Worktree. The inputs are copied from the tree into a fresh staging directory, topmost input first,
   without following symlinks (a symlink is copied as a symlink; its target is not; a FIFO, socket or
   device is not copied); an entry the
   derivation excludes (agent configuration, excluded directory names such as ``node_modules``, the
   operator's ``excluded_paths``) and ``.git`` are left out even under an input such as ``.``. Their
   regular files' bytes above ``unit_inputs_bytes`` stop the run (``limit_hit:unit_inputs_bytes``).
2. Dependencies. The ``deps`` artifact is taken by its address (MF5 ``verify``); its lock must be the
   tree's lock byte for byte (``deps_lock_mismatch``). The rows are sorted by the container's platform
   (``runner.deps_npm.platform_plan`` with ``container_platform``: Linux, this machine's cpu, the image's
   libc): a row whose ``os``, ``cpu`` or ``libc`` exclude the platform is not installed, nor is a row below its
   directory (``not_installed`` in the result). npm does the same with an optional row and ends its install on
   any other (``unsupported`` in the result names those); here neither is a reason (tohum/26c "Birim tarifi": a
   package that is not unpacked refuses nothing, the runs are the measure). Each installed row's tarball is
   unpacked, by the
   referee and without running anything, into ``<lock dir>/<lock key>/`` with its first path component
   dropped: directories and regular files only (files 0644, or 0755 when the member has an execute
   bit); symbolic and hard links and other member types are skipped, as npm does; a member name that is
   absolute or holds ``..``, or a destination with a symlink or a non-directory on its way, refuses the
   artifact (``deps_unpack_unsafe:<key>``); unpacked bytes are bounded by ``worktree_bytes``. Then for
   each package whose ``package.json`` has ``bin`` (a string, named after the package's bare name, or an
   object), a relative symlink ``<parent node_modules>/.bin/<name>`` to the target inside the package is
   made, the first in lock-key order winning; a bin name outside ``[A-Za-z0-9._-]`` or a target leaving
   the package is skipped. Then each workspace link MF5 takes (``runner.deps_npm.live_workspaces``) becomes a
   relative symlink ``<lock dir>/<key>`` to ``<lock dir>/<folder>``, as ``npm ci`` makes it; a symlink or
   non-directory on its way, or an entry already there, refuses the artifact (``deps_unpack_unsafe:<key>``). A
   folder outside the inputs leaves the link dangling, which shows in the run. Out of scope: the ``bin`` links
   of a workspace package (none is made, and the static rule above refuses such a ``.bin`` path unless a
   package of the lock provides it), ``directories.bin``, man pages, npm's own install logic, and a
   bound on the number of members (only their bytes are bounded; time is bounded by the job's clock). A lock
   with no package needs no artifact; one with packages and no artifact is unusable input.
3. Install scripts, of installed rows only (tohum/26c "Birim tarifi": a mark is leave to fetch a package that
   has a script; no page says which script runs, and a script that does not run or ends nonzero refuses
   nothing: the runs are the measure). When a row is flagged ``install_script`` (marked in the recipe, checked
   by MF5), one contained run of ``npm --prefix /work/<lock dir> rebuild --offline --foreground-scripts
   <names>`` with every flagged name precedes the runs (``install`` in the result). When it exits 0 its
   worktree is the start of every run. When it exits nonzero that worktree is discarded (which scripts ran
   before the failure is npm's queue's to say) and each name runs alone with the same command, in name order,
   each from the worktree the one before left (``install_each`` in the result: the run, ``name``,
   ``dropped``). A name that exits 0 leaves its worktree to the next. A name that exits nonzero leaves the
   worktree as it was before its run, with one change when every flagged row of the name still installed is
   optional: those rows are removed, with every row below them and the ``.bin`` links into them (``dropped``:
   every row removed), as npm drops an optional package that fails to build and goes on. Any other name's rows
   stay as unpacked (``dropped`` is ``[]``). A name is run alone only while one of its flagged rows is still
   installed. An install run that is no valid run (its red control, a limit) gives no verdict. ``npm rebuild``
   names packages, not rows, and its exit does not say which row's script failed; so, wider than npm's drop,
   when a name has several flagged optional rows all of them go, where npm drops only the failing one (the
   runs can lack a package npm would have kept), and a name with one row that is not optional keeps all its
   rows. The names run alone in name order, not in npm's dependency order: a script that needs another
   package's script to have run first can fail here where the joint run's order would have built it. Left out
   of npm's rule, each stated in ``platform_plan``: an optional row's ``engines``, and the rest of npm's
   optional set. Whether npm and node-gyp succeed in the real image is not proven here (no node in the
   referee's sandbox); its proof is asama-0/10a #birim.
4. 3/3. Three attempts, each running ``lint_cmd`` and then ``test_cmd``, every command in its own fresh
   contained run (MF3: no network, read-only root, the image, limits) of the same worktree, working
   directory ``/work`` (the tree's root), with ``HOME`` and ``TMPDIR`` under ``/work/.snowball``,
   ``CI=true``, ``npm_config_offline=true``, and the caller's red control in the same image. Tests are
   green when the exit code is 0 (``test_red:<attempt>``). Lint is green when the exit code is 0 or 1
   (ESLint's: 1 means findings, which asama-0/08 criterion 5 requires; 2 and others are failures,
   ``lint_failed:<attempt>``) and the three runs give the same exit code and the same stdout bytes
   (``lint_not_deterministic``). An insufficient ``inputs`` closure shows here, as a red or failing
   run; the verifier does not tell it apart from a failing test.
5. Limits. ``test_total_s`` caps the wall clock of each attempt's ``test_cmd``: the runner's timeout is the
   smaller of it and ``kos_wall_s``, and a test command stopped by that cap is ``limit_hit:test_total_s``.
   ``run.contained``'s own limits apply to every run (``limit_hit:kos_wall_s``, ``worktree_bytes``,
   ``output_bytes``; container memory).
6. The lint output, only when 1-5 left no reason (asama-0/08's unit selection, bold criteria 4 and 5). Each
   lint run's stdout, with the worktree it read, becomes a run record (``runner.lint_record``: ESLint's
   ``--format json`` only; its refusals are ``lint_output:<reason>``, e.g. a parse error ``fatal:<path>``).
   Criterion 5: some violation of the first record has a ``fix`` and a path that a ``security_paths``,
   ``excluded_dirs`` or ``excluded_paths`` entry of the derivation does not cover and an ``inputs`` entry
   does (29f coverage, as written); else ``no_fixable_violation``. Configuration, manifest and lock files
   count here although the gate refuses a candidate that changes them (MF7's rule, not called here).

Verdicts: ``verified`` (the recipe, its sha256 over canonical JSON, the deps address, every run's
results, and ``lint_records``: the three runs' records, the ratchet base's run file once written by
``lint_record.run_file``); ``refused`` (a reason about the recipe or the unit: static reasons, ``lock:``,
``test_red``, ``lint_failed``, ``lint_not_deterministic``, ``lint_output:``,
``no_fixable_violation``); ``no_verdict``
(nothing is learned about the recipe: ``limit_hit:<key>`` -- a limit is the operator's, not counted to the
Founder, tohum/18a --, an invalid contained run such as ``red_control_green``, ``red_control_fault``,
``runner_fault``, ``breach:in_changed``, ``unreadable_output``, or a ``deps`` artifact that does not verify,
``deps:<reason>``, or does not belong to the tree's lock, or cannot be unpacked safely). Out of scope:
asama-0/08 unit criterion 7 (churn) and whether the tests are "well tested".

Group ``recipe``'s check (``vector_check``, tohum/29g; no tree, nothing run) is a separate, narrower
check than ``check_recipe``: it emits only these reasons, every applicable one, sorted in code point
order, ``<input>`` and ``<key>`` as written in the recipe:

- ``image_not_pinned``: ``env_image`` (any value, missing included) is not ``<ref>@sha256:<64 lowercase
  hex>`` (``run.contained``'s image rule);
- ``inputs_missing_unit``: no input covers ``path`` (tohum/29f coverage: ``p == e.rstrip('/')`` or ``p``
  starts with ``e.rstrip('/') + '/'``, case-sensitive, as written);
- ``input_not_plain:<input>``: the input is absolute, holds ``\\`` or has a ``.`` or ``..`` component
  (``.`` itself included);
- ``input_excluded:<input>``: the input itself is agent configuration (tohum/29f, case-insensitive: a
  component ``.claude``, ``.vscode`` or ``.devcontainer``, or the last component, trailing ``/`` ignored,
  ``CLAUDE.md``, ``AGENTS.md``, ``.mcp.json`` or ``.envrc``);
- ``cmd_empty:<field>``: ``lint_cmd``, ``test_cmd`` or ``affected_test_cmd`` is missing, not a list, empty,
  or holds a non-string or an empty string;
- ``limit_key_unknown:<key>``: a ``limits`` key is not a key of ``policy.operating`` (values not looked at);
- ``services_not_empty``: ``services`` is not ``[]`` (missing included).

Unusable input there (exit 2): a file missing or not JSON, ``recipe`` not an object, ``policy`` not
``{operating: {...}}``, ``path`` not a string, ``inputs`` not a list of strings, ``limits`` not an
object. Other recipe fields are not looked at.

Command line, run from ``referee/``, no stdin; the last stdout line is one JSON line. ``check``: ``{ok,
reasons}``, exit 0 when ``reasons`` is empty, else 1. ``verify``: the report, exit 0 verified, 1 refused, 2
no verdict. Unusable input (missing or non-JSON files, JSON nested too deeply, wrong shapes, a policy
without the needed ``operating`` keys) are exit 2 with ``{ok: false, error}``; any other exception is exit 2 at
``cli.run``'s boundary (``FAULT_LINE``, the type alone on stderr). Out of scope: signals and the interpreter being killed.

    python -m profile.unit_verify check RECIPE POLICY
    python -m profile.unit_verify verify FILE

``FILE`` is ``{recipe, tree, policy, red_control: {cmd}, deps?, target?, base?}``: ``recipe`` and
``policy`` objects, ``tree`` the HEAD tree, ``deps`` an MF5 artifact directory (its name is its address),
``target`` the ``targets[]`` entry, ``base`` where fresh run directories go. It runs docker.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import posixpath
import re
import shlex
import shutil
import stat
import sys
import tarfile
import tempfile
import time
from typing import Any

from profile import derive as D
from runner import contained as C
from runner import deps_npm as N
from runner import lint_record as R
import cli

RECIPE_FIELDS = D.RECIPE_FIELDS
OPERATING_NAMES = ("unit_inputs_bytes", "deps_bytes", "worktree_bytes", "container_mem_bytes", "kos_wall_s",
                  "test_total_s", "output_bytes")
RUN_LIMIT_NAMES = ("unit_inputs_bytes", "worktree_bytes", "container_mem_bytes", "kos_wall_s", "test_total_s",
            "output_bytes")
UNIT_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
TOOLCHAIN = re.compile(r"node@([0-9]+\.[0-9]+\.[0-9]+)")
VERSION_TEXT = re.compile(r"v?([0-9]+\.[0-9]+\.[0-9]+)")
OFFICIAL_REPOS = ("node", "docker.io/library/node")
IMAGE_SHAPE = re.compile(r"(?P<repo>[^@]+?)(?::(?P<tag>[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}))?@sha256:[0-9a-f]{64}")
CMD_FIELDS = ("lint_cmd", "test_cmd", "affected_test_cmd")
BIN_NAME = re.compile(r"[A-Za-z0-9._-]+")
# Reasons about fields the tree checks never read: they do not stop the tree checks (every reason is listed).
TREE_FREE_FIELDS = ("unit_id", "env_image", "services", "limits")
SHELL_OPERATOR = re.compile(r"[();<>|&]+")
ASSIGNMENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=")
DEP_FIELDS = ("dependencies", "devDependencies", "optionalDependencies", "peerDependencies")
RESERVED = ".snowball"
ATTEMPTS = 3
# node's process.arch for the machine names a docker host reports (os.uname().machine); the official image is built for these.
NODE_CPU = {"x86_64": "x64", "amd64": "x64", "aarch64": "arm64", "arm64": "arm64", "armv7l": "arm",
            "ppc64le": "ppc64", "s390x": "s390x"}
LINT_OK_EXITS = (0, 1)
ENV = {"HOME": "/work/.snowball/home", "TMPDIR": "/work/.snowball/tmp", "CI": "true",
       "npm_config_offline": "true"}
NO_VERDICT_PREFIXES = ("limit_hit:", "deps:", "deps_lock_mismatch", "deps_unpack_unsafe", "red_control_",
                       "runner_fault", "breach:", "unreadable_output")


class VerifyError(ValueError):
    """Unusable input: no verdict (exit 2)."""


def canonical(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")


# ---------------------------------------------------------------- static check

def _argv_ok(value: Any) -> bool:
    return (isinstance(value, list) and bool(value)
            and all(isinstance(v, str) and v and "\x00" not in v for v in value))


def _operating(policy: Any, keys) -> dict:
    """``{key: (value, band)}`` for ``keys`` from ``policy.operating``; each must be valid (MF3's rule)."""
    operating = policy.get("operating") if isinstance(policy, dict) else None
    try:
        values = C.limits(operating, tuple(keys))
    except C.ContainmentError as exc:
        raise VerifyError("policy: %s" % cli.cause(exc)) from None
    return {k: (values[k], operating[k]["band"]) for k in keys}


def vector_check(recipe: Any, policy: Any) -> list[str]:
    """Group ``recipe``'s static check (tohum/29g): the sorted reasons; see ``check`` in the module docstring.

    Raises ``VerifyError`` (unusable input) when ``recipe`` or ``policy.operating`` is not an object, or
    ``path``, ``inputs`` (a list of strings) or ``limits`` (an object) is missing or of another type."""
    if not isinstance(recipe, dict):
        raise VerifyError("recipe is not an object")
    operating = policy.get("operating") if isinstance(policy, dict) else None
    if not isinstance(operating, dict):
        raise VerifyError("policy must be {operating: {key: {value, band}}}")
    path, inputs, limits = recipe.get("path"), recipe.get("inputs"), recipe.get("limits")
    if not isinstance(path, str):
        raise VerifyError("recipe.path must be a string")
    if not (isinstance(inputs, list) and all(isinstance(e, str) for e in inputs)):
        raise VerifyError("recipe.inputs must be a list of strings")
    if not isinstance(limits, dict):
        raise VerifyError("recipe.limits must be an object")
    reasons = set()
    image = recipe.get("env_image")
    if not (isinstance(image, str) and C.IMAGE.match(image)):
        reasons.add("image_not_pinned")
    if not any(D.covers_as_written(e, path) for e in inputs):
        reasons.add("inputs_missing_unit")
    for e in inputs:
        if e.startswith("/") or "\\" in e or any(p in (".", "..") for p in e.split("/")):
            reasons.add("input_not_plain:%s" % e)
        if D.agent_config_as_written(e):
            reasons.add("input_excluded:%s" % e)
    for field in CMD_FIELDS:
        value = recipe.get(field)
        if not (isinstance(value, list) and value and all(isinstance(v, str) and v for v in value)):
            reasons.add("cmd_empty:%s" % field)
    reasons.update("limit_key_unknown:%s" % k for k in limits if k not in operating)
    if recipe.get("services") != []:
        reasons.add("services_not_empty")
    return sorted(reasons)


def check_recipe(recipe: Any, policy: Any = None, tree: str | None = None, target: Any = None,
                 derived: dict | None = None) -> list[str]:
    """Every static reason against ``recipe`` (empty when it passes); see the module docstring. ``derived`` is
    ``derived_profile(tree, target, policy)`` when the caller has it already (one derivation for many recipes)."""
    if not isinstance(recipe, dict):
        return ["malformed:recipe"]
    reasons = ["missing:%s" % f for f in RECIPE_FIELDS if f not in recipe]
    reasons += ["field_not_in_recipe:%s" % f for f in sorted(recipe) if f not in RECIPE_FIELDS]
    get = recipe.get
    if "unit_id" in recipe and not (isinstance(get("unit_id"), str) and UNIT_ID.fullmatch(get("unit_id"))):
        reasons.append("invalid:unit_id")
    path = D.norm_path(get("path"))
    if "path" in recipe and path is None:
        reasons.append("invalid:path")
    inputs = []
    if "inputs" in recipe:
        raw = get("inputs")
        inputs = [D.norm_path(p) for p in raw] if D._str_list(raw) and raw else [None]
        if None in inputs:
            reasons.append("invalid:inputs")
            inputs = [p for p in inputs if p is not None]
        if path is not None and not any(D.covers(p, path) for p in inputs):
            reasons.append("inputs_miss_unit_path")
        if any(D.covers(p, RESERVED) or D.covers(RESERVED, p) for p in inputs if p != "."):
            reasons.append("reserved_path")
    version = None
    if "toolchain" in recipe:
        m = TOOLCHAIN.fullmatch(get("toolchain")) if isinstance(get("toolchain"), str) else None
        if m is None:
            reasons.append("invalid:toolchain")
        else:
            version = m.group(1)
    if "env_image" in recipe:
        reasons += _image_reasons(get("env_image"), version)
    lock = None
    if "lockfiles" in recipe:
        locks = get("lockfiles")
        lock = D.norm_path(locks[0]) if D._str_list(locks) and len(locks) == 1 else None
        if lock is None or posixpath.basename(lock) not in N.LOCK_NAMES:
            reasons.append("invalid:lockfiles")
            lock = None
        else:
            if not any(D.covers(p, lock) for p in inputs):
                reasons.append("lockfile_not_in_inputs")
            if path is not None and not D.covers(posixpath.dirname(lock) or ".", path):
                reasons.append("lockfile_not_for_unit")
    if "install_scripts_required" in recipe and not D._str_list(get("install_scripts_required")):
        reasons.append("invalid:install_scripts_required")
    for field in CMD_FIELDS:
        if field in recipe and not _argv_ok(get(field)):
            reasons.append("invalid:%s" % field)
    if "services" in recipe and get("services") != []:
        reasons.append("services_not_empty")
    if "limits" in recipe:
        reasons += _limit_reasons(get("limits"), policy)
    if tree is not None and not [r for r in reasons if _field_of(r) not in TREE_FREE_FIELDS]:
        reasons += _tree_reasons(recipe, path, lock, version, tree,
                                 derived if derived is not None else derived_profile(tree, target, policy))
    return reasons


def _field_of(reason: str) -> str | None:
    """The recipe field a static reason is about (``None`` for reasons about several fields)."""
    if reason.startswith(("missing:", "invalid:")):
        return reason.split(":", 1)[1].split(".", 1)[0]
    if reason.startswith("image_"):
        return "env_image"
    if reason.startswith("limit_"):
        return "limits"
    return "services" if reason == "services_not_empty" else None


def _image_reasons(image: Any, version: str | None) -> list[str]:
    if not (isinstance(image, str) and C.IMAGE.match(image)):
        return ["image_not_pinned"]
    m = IMAGE_SHAPE.fullmatch(image)
    if m is None or m.group("repo") not in OFFICIAL_REPOS:
        return ["image_not_official"]
    tag = m.group("tag") or ""
    if version is None or not (tag == version or tag.startswith(version + "-")):
        return ["image_version_mismatch"]
    return []


def _limit_reasons(limits: Any, policy: Any) -> list[str]:
    if not isinstance(limits, dict):
        return ["invalid:limits"]
    reasons = []
    operating = policy.get("operating") if isinstance(policy, dict) else None
    for key in sorted(limits):
        value = limits[key]
        if key not in OPERATING_NAMES:
            reasons.append("limit_key_unknown:%s" % key)
        elif not C._posint(value):
            reasons.append("invalid:limits.%s" % key)
        elif operating is not None:
            (op_value, band), = _operating(policy, (key,)).values()
            if value > op_value:
                reasons.append("limit_above_operating:%s" % key)
            elif value < band[0]:
                reasons.append("limit_below_band:%s" % key)
    return reasons


def nearest_version(tree: str, path: str) -> tuple[str | None, str | None]:
    """``(file, text)`` of the version file nearest to ``path`` (``file`` a normalised tree path, no ``./``);
    ``(None, None)`` when there is none."""
    for d in D._ancestors(path):
        for name in (".nvmrc", ".node-version"):
            data = D._read_regular(tree, posixpath.join(d, name))
            if data is not None and data.strip():
                return D.norm_path(posixpath.join(d, name)), data.decode("utf-8", "replace").strip()
        data = D._read_regular(tree, posixpath.join(d, ".tool-versions"))
        if data is not None:
            for line in data.decode("utf-8", "replace").splitlines():
                words = line.split()
                if len(words) > 1 and words[0] in ("node", "nodejs"):
                    return D.norm_path(posixpath.join(d, ".tool-versions")), words[1]
    return None, None


def _tree_reasons(recipe: dict, path: str, lock: str, version: str, tree: str, derived: dict) -> list[str]:
    reasons = []
    reasons += ["profile:%s" % r for r in D.check(derived, {"units": [recipe]}, tree)["reasons"]]
    _, text = nearest_version(tree, path)
    if text is None:
        reasons.append("version_file_missing")
    else:
        m = VERSION_TEXT.fullmatch(text)
        if m is None:
            reasons.append("version_file_not_exact")
        elif m.group(1) != version:
            reasons.append("toolchain_version_mismatch")
    data = D._read_regular(tree, lock)
    if data is None:
        reasons.append("lockfile_missing")
    else:
        try:
            parsed = cli.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, ValueError, RecursionError):
            parsed = None
        report = N.check(parsed, N.DEFAULT_REGISTRIES, recipe["install_scripts_required"])
        reasons += ["lock:%s" % r for r in report["reasons"]]
        if isinstance(parsed, dict) and isinstance(parsed.get("packages"), dict):
            lock_dir = posixpath.dirname(lock) or "."
            reasons += ["cmd_not_installed:%s:%s" % (field, element) for field in CMD_FIELDS
                        for element in recipe[field] if not installed(element, lock_dir, parsed)]
            for field in CMD_FIELDS:
                reasons += _script_reasons(field, recipe[field], lock_dir, parsed, tree)
    return reasons


def _work_path(element: str) -> str | None:
    """A command element read as a path of the tree: ``/work/<p>`` is ``<p>``; ``None`` when not a plain path."""
    return D.norm_path(element[len(C.WORKDIR) + 1:] if element.startswith(C.WORKDIR + "/") else element)


def npm_run(argv: list) -> tuple[str, str] | None:
    """``(directory, script)`` when ``argv`` is ``npm --prefix <dir> run --silent <script>``, optionally followed
    by ``--`` and arguments, ``<dir>`` a plain path of the tree and ``<script>`` not an option; else ``None``."""
    if not (len(argv) >= 6 and argv[:2] == ["npm", "--prefix"] and argv[3:5] == ["run", "--silent"]
            and not argv[5].startswith("-") and (len(argv) == 6 or argv[6] == "--")):
        return None
    directory = _work_path(argv[2])
    return (directory, argv[5]) if directory is not None else None


def script_programs(text: str) -> list[str] | None:
    """The program word of every simple command of a ``package.json`` script, read with ``shlex`` (POSIX,
    ``punctuation_chars``): a command starts the script and follows a token made only of ``();|&``; leading
    ``NAME=value`` words are skipped; a token holding ``<`` or ``>`` is a redirection whose next token is its
    target, not a program. ``None`` when ``shlex`` cannot read the text (an open quote)."""
    lexer = shlex.shlex(text, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    try:
        tokens = list(lexer)
    except ValueError:
        return None
    programs, start, skip = [], True, False
    for token in tokens:
        if skip:
            skip = False
        elif SHELL_OPERATOR.fullmatch(token) and ("<" in token or ">" in token):
            skip = True
        elif SHELL_OPERATOR.fullmatch(token):
            start = True
        elif start and not ASSIGNMENT.match(token):
            programs.append(token)
            start = False
    return programs


def npm_programs(tree: str, directory: str) -> set:
    """The names npm's ``run`` could find on its ``PATH`` in the developer's layout: dependencies declared by the
    ``package.json`` of ``directory`` and of each directory above it, and the ``bin`` names of the packages of
    the locks there (MF5's lock reading)."""
    names: set = set()
    for d in D._ancestors(directory):
        _, manifest = D._json(tree, posixpath.join(d, "package.json"))
        if isinstance(manifest, dict):
            for field in DEP_FIELDS:
                if isinstance(manifest.get(field), dict):
                    names.update(manifest[field])
        for lock_name in N.LOCK_NAMES:
            _, lock = D._json(tree, posixpath.join(d, lock_name))
            for row in N.entries(lock)[1]:
                names |= _bin_names(row["entry"], row["name"])
    return names


def _script_reasons(field: str, argv: list, lock_dir: str, lock: Any, tree: str) -> list[str]:
    """``npm --prefix <dir> run --silent <script>``: the script exists and its programs are installed."""
    found = npm_run(argv)
    if found is None:
        return []
    directory, script = found
    _, manifest = D._json(tree, posixpath.join(directory, "package.json"))
    scripts = manifest.get("scripts") if isinstance(manifest, dict) else None
    text = scripts.get(script) if isinstance(scripts, dict) else None
    if not isinstance(text, str):
        return ["script_missing:%s:%s" % (field, script)]
    known = npm_programs(tree, directory)
    on_path = lock_dir == "." or directory == lock_dir or directory.startswith(lock_dir + "/")
    dirs = [directory]  # <dir> and each directory above it up to the lock's: their node_modules/.bin are on PATH
    while on_path and dirs[-1] != lock_dir:
        dirs.append(posixpath.dirname(dirs[-1]) or ".")
    reasons = []
    for program in script_programs(text) or []:
        judged = program in known and BIN_NAME.fullmatch(program)
        bins = [posixpath.join(d, "node_modules", ".bin", program) for d in dirs]  # norm_path drops a leading ./
        if judged and not (on_path and any(installed(b, lock_dir, lock) for b in bins)):
            reason = "script_not_installed:%s:%s" % (field, program)
            if reason not in reasons:
                reasons.append(reason)
    return reasons


def _bin_names(entry: Any, name: str) -> set:
    value = entry.get("bin")
    if isinstance(value, str):
        return {name.split("/")[-1]}
    return set(value) if isinstance(value, dict) else set()


def installed(element: str, lock_dir: str, lock: Any) -> bool:
    """False when ``element`` is a ``node_modules`` path the lock does not install (module docstring); the lock's
    packages, their keys and names, are read as MF5 reads them (``runner.deps_npm.entries``)."""
    path = _work_path(element)
    if path is None or element.startswith("-") or "node_modules" not in [c.casefold() for c in path.split("/")]:
        return True
    if lock_dir != ".":
        if not path.startswith(lock_dir + "/"):
            return False
        path = path[len(lock_dir) + 1:]
    rows = {row["key"]: row for row in N.entries(lock)[1]}
    links = N.live_workspaces(lock.get("packages") if isinstance(lock, dict) else None)[0]
    parts = path.split("/")
    for i in range(len(parts), 0, -1):
        head = "/".join(parts[:i])
        if (head in rows or head in links) and "node_modules" not in [c.casefold() for c in parts[i:]]:
            return True
    if any(key.startswith(path + "/") for key in list(rows) + list(links)):
        return True
    if len(parts) < 3 or parts[-2] != ".bin":
        return False
    parent, name = "/".join(parts[:-2]), parts[-1]
    for key, row in rows.items():
        package = key[len(parent) + 1:] if key.startswith(parent + "/") else ""
        one_name = package and package.count("/") == package.startswith("@")
        if one_name and name in _bin_names(row["entry"], row["name"]):
            return True
    return False


# ---------------------------------------------------------------- worktree

def _effective(policy: Any, limits: dict) -> tuple[dict, dict]:
    """``(values, operating)``: per run key the smaller of the operator's value and the recipe's."""
    found = _operating(policy, RUN_LIMIT_NAMES)
    values, operating = {}, {}
    for key, (value, band) in found.items():
        values[key] = min(value, limits.get(key, value))
        operating[key] = {"value": values[key], "band": band}
    return values, operating


def copy_inputs(tree: str, inputs: list[str], derived: dict, staging: str, limit: int) -> int:
    """Copy the inputs' closure into ``staging``; returns its regular-file bytes (stops above ``limit``)."""
    total = 0
    tops = D.minimal(D.norm_path(p) for p in inputs)
    for top in tops:
        if top != "." and D.excluded(derived, top):
            continue
        stack = [top]
        while stack:
            rel = stack.pop()
            src = tree if rel == "." else os.path.join(tree, rel)
            dst = staging if rel == "." else os.path.join(staging, rel)
            st = os.lstat(src)
            if rel != ".":
                os.makedirs(os.path.dirname(dst), exist_ok=True)
            if stat.S_ISLNK(st.st_mode):
                os.symlink(os.readlink(src), dst)
            elif stat.S_ISDIR(st.st_mode):
                os.makedirs(dst, exist_ok=True)
                for name in sorted(os.listdir(src), reverse=True):
                    child = name if rel == "." else rel + "/" + name
                    if name != ".git" and not D.excluded(derived, child):
                        stack.append(child)
            elif stat.S_ISREG(st.st_mode):
                shutil.copy2(src, dst, follow_symlinks=False)
                total += st.st_size
                if total > limit:
                    return total
    return total


def _safe_dir(root: str, rel: str) -> str | None:
    """Create ``root/rel`` component by component; None when a symlink or a non-directory is on the way."""
    cur = root
    for part in [p for p in rel.split("/") if p]:
        cur = os.path.join(cur, part)
        try:
            st = os.lstat(cur)
        except FileNotFoundError:
            os.mkdir(cur)
            continue
        if not stat.S_ISDIR(st.st_mode):
            return None
    return cur


class _Unsafe(Exception):
    pass


class _TooBig(Exception):
    pass


def unpack(data: bytes, root: str, dest: str, budget: int) -> tuple[int, int]:
    """Unpack an npm tarball under ``root/dest``; returns ``(bytes, skipped members)``; see the docstring."""
    written = skipped = 0
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
        for member in tar:
            if member.name.startswith("/") or ".." in member.name.split("/"):
                raise _Unsafe(member.name)
            parts = [p for p in member.name.split("/") if p not in ("", ".")]
            if len(parts) < 2:
                continue
            rel = "/".join(parts[1:])
            if member.isdir():
                if _safe_dir(root, dest + "/" + rel) is None:
                    raise _Unsafe(member.name)
                continue
            if not member.isfile():
                skipped += 1
                continue
            parent = _safe_dir(root, dest + "/" + posixpath.dirname(rel))
            if parent is None:
                raise _Unsafe(member.name)
            target = os.path.join(parent, parts[-1])
            if os.path.lexists(target):
                if not stat.S_ISREG(os.lstat(target).st_mode):
                    raise _Unsafe(member.name)
                os.unlink(target)
            written += member.size
            if written > budget:
                raise _TooBig()
            fh = tar.extractfile(member)
            fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                         0o755 if member.mode & 0o111 else 0o644)
            with os.fdopen(fd, "wb") as out:
                shutil.copyfileobj(fh, out)
            os.chmod(target, 0o755 if member.mode & 0o111 else 0o644)
    return written, skipped


def _bins(manifest: Any, name: str) -> dict:
    if not isinstance(manifest, dict):
        return {}
    value = manifest.get("bin")
    if isinstance(value, str):
        return {name.split("/")[-1]: value}
    if isinstance(value, dict):
        return {k: v for k, v in value.items() if isinstance(v, str)}
    return {}


def link_bins(staging: str, lock_dir: str, rows: list[dict]) -> list[str]:
    """Make ``.bin`` symlinks for every package with ``bin``; returns the links made (relative paths)."""
    made: list[str] = []
    for row in sorted(rows, key=lambda r: r["key"]):
        pkg = posixpath.join(lock_dir, row["key"]) if lock_dir != "." else row["key"]
        pkg_json = D._read_regular(staging, pkg + "/package.json")
        try:
            manifest = cli.loads(pkg_json.decode("utf-8")) if pkg_json is not None else None
        except (UnicodeDecodeError, ValueError, RecursionError):
            manifest = None
        parent = pkg[: pkg.rindex("node_modules/") + len("node_modules")]
        for bin_name, target in sorted(_bins(manifest, row["name"]).items()):
            inner = D.norm_path(target)
            if not BIN_NAME.fullmatch(bin_name) or bin_name in (".", "..") or inner is None:
                continue
            bin_dir = _safe_dir(staging, parent + "/.bin")
            link = parent + "/.bin/" + bin_name
            if bin_dir is None or os.path.lexists(os.path.join(staging, link)):
                continue
            os.symlink(posixpath.relpath(pkg + "/" + inner, parent + "/.bin"), os.path.join(staging, link))
            full = os.path.join(staging, pkg, inner)
            if os.path.isfile(full) and not os.path.islink(full):
                os.chmod(full, 0o755)
            made.append(link)
    return made


def link_workspace(staging: str, lock_dir: str, key: str, folder: str) -> bool:
    """npm's workspace link: a relative symlink ``<lock dir>/<key>`` to ``<lock dir>/<folder>`` (both from
    ``runner.deps_npm.live_workspaces``, so the folder has no ``..`` and the key ends in ``node_modules/<name>``).
    False, nothing made, when a symlink or a non-directory is on the key's way or the key already exists (a
    package unpacked there). The folder need not be in the inputs: then the link dangles, as a missing input shows
    in the run."""
    path = key if lock_dir == "." else lock_dir + "/" + key
    target = folder if lock_dir == "." else lock_dir + "/" + folder
    parent = _safe_dir(staging, posixpath.dirname(path))
    if parent is None or os.path.lexists(os.path.join(staging, path)):
        return False
    os.symlink(posixpath.relpath(target, posixpath.dirname(path)), os.path.join(staging, path))
    return True


def container_platform(image: str, machine: str | None = None) -> dict:
    """The platform npm sees in a container of ``image``, in node's words ``{os, cpu, libc}``: ``os`` is
    ``linux`` (the runner starts Linux containers); ``cpu`` is this machine's (``os.uname().machine`` through
    ``NODE_CPU``: the runner names no ``--platform``, so docker takes the host's variant of the image; a machine
    not in the table is unusable input, not a guess); ``libc`` is ``musl`` when a ``-`` separated part of the
    tag starts with ``alpine`` and ``glibc`` otherwise (the official image's variants are Debian's or
    Alpine's). Read from the recipe and the host, not asked of the container: a wrong reading shows as a
    binding package missing in the runs, a red run and not a silent pass."""
    machine = os.uname().machine if machine is None else machine
    if machine not in NODE_CPU:
        raise VerifyError("this machine's architecture is not one the verifier knows a node cpu for")
    m = IMAGE_SHAPE.fullmatch(image) if isinstance(image, str) else None
    parts = (m.group("tag") or "").split("-") if m else []
    return {"os": "linux", "cpu": NODE_CPU[machine],
            "libc": "musl" if any(part.startswith("alpine") for part in parts) else "glibc"}


def drop_rows(staging: str, lock_dir: str, keys: list[str], installed: list[str],
              links: list[str]) -> tuple[list[str], list[str]]:
    """Remove the installed packages ``keys`` with what is below them; ``(removed, links kept)``: ``removed``
    the rows of ``installed`` that are gone, sorted (each of ``keys`` and every row below one of them, as
    ``platform_plan`` counts a row below a row that is not installed), and the ``.bin`` links among ``links``
    that pointed into one of them are removed too. ``keys`` and ``installed`` are rows ``install_deps`` unpacked
    into ``staging``, so no symlink is on their way; a row whose tarball unpacked no file has no directory and
    nothing of it is removed."""
    removed = sorted(k for k in installed if any(k == key or k.startswith(key + "/") for key in keys))
    gone = []
    for key in sorted(keys):
        dest = key if lock_dir == "." else lock_dir + "/" + key
        path = os.path.join(staging, *dest.split("/"))
        if os.path.lexists(path):       # not there: below a key removed before it, or never unpacked
            shutil.rmtree(path)
        gone.append(dest + "/")
    kept = []
    for link in links:
        path = os.path.join(staging, *link.split("/"))
        target = posixpath.normpath(posixpath.join(posixpath.dirname(link), os.readlink(path)))
        if (target + "/").startswith(tuple(gone)):
            os.unlink(path)
        else:
            kept.append(link)
    return removed, kept


def install_deps(staging: str, lock: str, deps: str | None, tree_lock: bytes, budget: int,
                 platform: dict | None = None) -> tuple[list[str], dict]:
    """Take the artifact by its hash and unpack the rows ``platform`` admits (``runner.deps_npm.
    platform_plan``; every row when ``platform`` is None); ``(reasons, {address, rows, links, bytes, skipped,
    not_installed, unsupported, optional})``: ``rows`` the manifest rows unpacked, ``not_installed``,
    ``unsupported`` and ``optional`` the plan's keys."""
    lock_obj = cli.loads(tree_lock.decode("utf-8"))
    has_packages = any(k for k in lock_obj.get("packages", {}))
    if deps is None:
        if has_packages:
            raise VerifyError("the lock has packages and no deps artifact was given")
        return [], {"address": None, "rows": [], "links": [], "bytes": 0, "skipped": 0, "not_installed": [],
                    "unsupported": [], "optional": []}
    report = N.verify(deps)
    if not report["ok"]:
        return ["deps:%s" % r for r in report["reasons"]], {}
    with open(os.path.join(deps, "manifest.json"), "rb") as fh:
        manifest = cli.loads(fh.read().decode("ascii"))
    if manifest["lock_sha256"] != hashlib.sha256(tree_lock).hexdigest():
        return ["deps_lock_mismatch"], {}
    lock_dir = posixpath.dirname(lock) or "."
    links, folders = N.live_workspaces(lock_obj.get("packages"))
    for row in manifest["packages"]:
        if not isinstance(row.get("key"), str) or N.key_name(row["key"], folders) is None:
            return ["deps_unpack_unsafe:%s" % row.get("key")], {}
    keys = [row["key"] for row in manifest["packages"]]
    plan = (N.platform_plan(lock_obj.get("packages"), keys, platform) if platform is not None
            else {"installed": keys, "not_installed": [], "unsupported": [], "optional": []})
    installed = set(plan["installed"])
    rows = [row for row in manifest["packages"] if row["key"] in installed]
    total = skipped = 0
    for row in rows:
        dest = row["key"] if lock_dir == "." else lock_dir + "/" + row["key"]
        with open(os.path.join(deps, "tarballs", row["sha512"] + ".tgz"), "rb") as fh:
            data = fh.read()
        try:
            n, s = unpack(data, staging, dest, budget - total)
        except _Unsafe:
            return ["deps_unpack_unsafe:%s" % row["key"]], {}
        except _TooBig:
            return ["limit_hit:worktree_bytes"], {}
        except cli.ARCHIVE_ERRORS:
            return ["deps_unpack_unsafe:%s" % row["key"]], {}
        total += n
        skipped += s
    made = link_bins(staging, lock_dir, rows)
    for key, folder in sorted(links.items()):
        if not link_workspace(staging, lock_dir, key, folder):
            return ["deps_unpack_unsafe:%s" % key], {}
    return [], {"address": report["address"], "rows": rows, "links": made, "bytes": total,
                "skipped": skipped, "workspaces": sorted(links), "not_installed": plan["not_installed"],
                "unsupported": plan["unsupported"], "optional": plan["optional"]}


# ---------------------------------------------------------------- runs

class _Timed:
    """Wraps a runner: caps its timeout and records the wall clock of each call by container name."""

    def __init__(self, inner: C.Runner, cap: float | None) -> None:
        self.inner, self.cap, self.calls = inner, cap, {}

    def __call__(self, argv: list, env: dict, timeout: float) -> C.RunnerResult:
        capped = self.cap is not None and self.cap < timeout
        start = time.monotonic()
        res = self.inner(argv, env, self.cap if capped else timeout)
        self.calls[C._flag_value(argv, "--name")] = {"duration_s": round(time.monotonic() - start, 3),
                                                     "capped": capped and res.timed_out, "stdout": res.stdout}
        return res


def _one(job_cmd: list, red_cmd: list, image: str, staging: str, operating: dict, runner: C.Runner,
         base: str | None, cap: float | None = None) -> dict:
    timed = _Timed(runner, cap)
    job = {"image": image, "cmd": job_cmd, "tree": staging, "env": dict(ENV)}
    red = {"image": image, "cmd": red_cmd, "tree": staging, "env": dict(ENV)}
    report = C.run_with_red_control(job, red, operating, timed, base)
    shutil.rmtree(report["red_control"]["run_root"], ignore_errors=True)    # nothing reads the control's copy
    main = report["result"]
    timing = timed.calls.get(C._flag_value(main["argv"], "--name"), {})
    reasons = list(report["reasons"])
    if timing.get("capped"):
        reasons = ["limit_hit:test_total_s" if r == "limit_hit:kos_wall_s" else r for r in reasons]
    return {"valid": report["valid"], "reasons": reasons, "exit": main["exit"], "status": main["status"],
            "stdout_sha256": main.get("stdout_sha256"), "outputs_sha256": main["outputs_sha256"],
            "duration_s": timing.get("duration_s"), "red_control_exit": report["red_control"]["exit"],
            "run_root": main["run_root"], "stdout": timing.get("stdout")}


def _public(run: dict) -> dict:
    return {k: v for k, v in run.items() if k not in ("run_root", "stdout")}


def _discard(run: dict) -> None:
    """Remove a finished run's directory (its copy of the worktree): its results are in ``run`` already."""
    shutil.rmtree(run["run_root"], ignore_errors=True)


def lint_records(stdouts: list, staging: str, recipe: dict, derived: dict) -> tuple[list[str], list[dict]]:
    """asama-0/08 unit criteria 4 and 5 on the lint runs' stdout: ``(reasons, one run record per run)``."""
    records, reasons = [], []
    for out in stdouts:
        try:
            records.append(R.record(out if isinstance(out, bytes) else b"", staging))
        except R.RecordError as exc:
            reasons += ["lint_output:" + r for r in exc.reasons if "lint_output:" + r not in reasons]
    if reasons:
        return reasons, []
    closed = derived["security_paths"] + derived["excluded_dirs"] + derived["excluded_paths"]
    if not any(v["fix"] is not None and not any(D.covers_as_written(e, v["path"]) for e in closed)
               and any(D.covers_as_written(e, v["path"]) for e in recipe["inputs"])
               for v in records[0]["violations"]):
        return ["no_fixable_violation"], []
    return [], records


def derived_profile(tree: str, target: Any, policy: Any) -> dict:
    """The derivation the staging copies inputs under (``profile.derive`` with the policy's security keywords when
    the policy has a ``constitutional`` part, the seed's default list otherwise). One call for every reader of the
    staged tree: ``stage`` here and the gate's path rules in ``yaz`` (``loop.decide``) judge the same profile."""
    return D.derive(tree, target, policy if isinstance(policy, dict) and "constitutional" in policy else None)


def guard_profile(tree: str, target: Any, policy: Any) -> dict:
    """``gate.diffguard``'s profile ``{security_paths, excluded_dirs}`` for ``tree``, from ``derived_profile``:
    ``security_paths`` as derived (the physical safety paths among them, tohum/05), ``excluded_dirs`` the derived
    ``excluded_dirs`` and ``excluded_paths`` (the operator's and the agent configuration found), so tohum/29g's rule
    that ``excluded_dirs`` carries the operator's excluded paths holds. The one guard profile of every acceptance
    decision: ``yaz``'s (``loop.decide``) and the activation's (``activate``). Raises ``DeriveError`` as ``derive``."""
    derived = derived_profile(tree, target, policy)
    return {"security_paths": list(derived["security_paths"]),
            "excluded_dirs": D.minimal(derived["excluded_dirs"] + derived["excluded_paths"])}


def _install_each(flagged: dict, deps_info: dict, rebuild: list, lock_dir: str, recipe: dict, red_control: dict,
                  operating: dict, runner: C.Runner, staging_root: str, staging: str,
                  result: dict) -> tuple[list[str], str]:
    """Step 3 after a joint install run that exited nonzero: each flagged name alone, in name order, each from the
    worktree the one before left; ``(reasons, the worktree the runs start from)``. ``result["install_each"]`` gets
    a row per run and ``result["bin_links"]`` loses the links of dropped rows. A reason is an invalid run's."""
    optional = set(deps_info["optional"])
    present = [row["key"] for row in deps_info["rows"]]
    for name in sorted(flagged):
        keys = [key for key in flagged[name] if key in present]
        if not keys:
            continue
        run = _one(rebuild + [name], red_control["cmd"], recipe["env_image"], staging, operating, runner,
                   staging_root)
        each = dict(_public(run), name=name, dropped=[])
        result["install_each"].append(each)
        if not run["valid"]:
            return run["reasons"], staging
        if run["exit"] == 0:
            previous, staging = staging, os.path.join(run["run_root"], "work")
            if os.path.dirname(previous) != staging_root:       # an earlier name's run; the first copy stays
                shutil.rmtree(os.path.dirname(previous), ignore_errors=True)
            continue
        _discard(run)
        if all(key in optional for key in keys):
            each["dropped"], result["bin_links"] = drop_rows(staging, lock_dir, keys, present, result["bin_links"])
            present = [key for key in present if key not in each["dropped"]]
    return [], staging


def stage(recipe: Any, tree: str, policy: Any, red_control: Any, deps: str | None, target: Any, runner: C.Runner,
          staging_root: str) -> tuple[list[str], dict, dict]:
    """Steps 1-3 under ``staging_root``, after the static check: ``(reasons, result, context)``. ``context`` is
    ``{staging, derived, values, operating}`` (empty when there is a reason): ``staging`` the worktree every run
    starts from. Shared by ``verify`` and ``runner.kos`` so both run the same worktree."""
    if not (isinstance(red_control, dict) and _argv_ok(red_control.get("cmd"))):
        raise VerifyError("red_control must be {cmd: [argv]}")
    if not os.path.isdir(tree) or os.path.islink(tree):
        raise VerifyError("tree is not a directory")
    reasons = check_recipe(recipe, policy, tree, target)
    if reasons:
        return reasons, {}, {}
    values, operating = _effective(policy, recipe["limits"])
    derived = derived_profile(tree, target, policy)
    lock = D.norm_path(recipe["lockfiles"][0])
    staging = os.path.join(staging_root, "tree")
    os.mkdir(staging)
    size = copy_inputs(tree, recipe["inputs"], derived, staging, values["unit_inputs_bytes"])
    if size > values["unit_inputs_bytes"]:
        return ["limit_hit:unit_inputs_bytes"], {"inputs_bytes": size}, {}
    if os.path.lexists(os.path.join(staging, RESERVED)):
        return ["reserved_path"], {}, {}
    platform = container_platform(recipe["env_image"])
    bad, deps_info = install_deps(staging, lock, deps, D._read_regular(tree, lock), values["worktree_bytes"] - size,
                                  platform)
    if bad:
        return bad, {"inputs_bytes": size, "platform": platform}, {}
    for sub in ("home", "tmp"):
        os.makedirs(os.path.join(staging, RESERVED, sub))
    result: dict[str, Any] = {"inputs_bytes": size, "deps_address": deps_info["address"],
                              "deps_bytes_unpacked": deps_info["bytes"], "bin_links": deps_info["links"],
                              "skipped_members": deps_info["skipped"], "platform": platform,
                              "not_installed": deps_info["not_installed"],
                              "unsupported": deps_info["unsupported"], "install": None, "install_each": [],
                              "runs": {"lint": [], "test": []}}
    lock_dir = posixpath.dirname(lock) or "."
    prefix = "/work" if lock_dir == "." else "/work/" + lock_dir
    rebuild = ["npm", "--prefix", prefix, "rebuild", "--offline", "--foreground-scripts"]
    flagged: dict[str, list[str]] = {}
    for row in deps_info["rows"]:
        if row.get("install_script"):
            flagged.setdefault(row["name"], []).append(row["key"])
    if flagged:
        run = _one(rebuild + sorted(flagged), red_control["cmd"], recipe["env_image"], staging, operating, runner,
                   staging_root)
        result["install"] = _public(run)
        if not run["valid"]:
            return run["reasons"], result, {}
        if run["exit"] == 0:
            staging = os.path.join(run["run_root"], "work")
        else:
            _discard(run)
            bad, staging = _install_each(flagged, deps_info, rebuild, lock_dir, recipe, red_control, operating,
                                         runner, staging_root, staging, result)
            if bad:
                return bad, result, {}
    return [], result, {"staging": staging, "derived": derived, "values": values, "operating": operating}


def verify(recipe: Any, tree: str, policy: Any, red_control: Any, deps: str | None = None, target: Any = None,
           runner: C.Runner | None = None, base: str | None = None) -> dict:
    """The static check, then the 3/3 run; ``{verdict, ok, reasons, ...}`` (see the module docstring)."""
    runner = runner or C.docker_runner
    staging_root = tempfile.mkdtemp(prefix="snowball-unit-", dir=base)
    try:
        bad, result, ctx = stage(recipe, tree, policy, red_control, deps, target, runner, staging_root)
        if bad:
            return _verdict(bad, **result)
        staging, derived, operating = ctx["staging"], ctx["derived"], ctx["operating"]
        reasons, stdouts = [], []
        cap = ctx["values"]["test_total_s"]
        for attempt in range(1, ATTEMPTS + 1):
            lint = _one(recipe["lint_cmd"], red_control["cmd"], recipe["env_image"], staging, operating,
                        runner, staging_root)
            _discard(lint)
            test = _one(recipe["test_cmd"], red_control["cmd"], recipe["env_image"], staging, operating,
                        runner, staging_root, cap)
            _discard(test)
            result["runs"]["lint"].append(_public(lint))
            stdouts.append(lint["stdout"])
            result["runs"]["test"].append(_public(test))
            for run in (lint, test):
                reasons += [r for r in run["reasons"] if r not in reasons]
            if lint["valid"] and lint["exit"] not in LINT_OK_EXITS:
                reasons.append("lint_failed:%d" % attempt)
            if test["valid"] and test["exit"] != 0:
                reasons.append("test_red:%d" % attempt)
        lints = result["runs"]["lint"]
        if all(r["valid"] for r in lints) and len({(r["exit"], r["stdout_sha256"]) for r in lints}) > 1:
            reasons.append("lint_not_deterministic")
        if not reasons:
            reasons, records = lint_records(stdouts, staging, recipe, derived)
            if not reasons:
                result["lint_records"] = records
        if reasons:
            return _verdict(reasons, **result)
        return dict(_verdict([], **result), recipe=recipe, recipe_sha256=hashlib.sha256(canonical(recipe)).hexdigest())
    finally:
        shutil.rmtree(staging_root, ignore_errors=True)


def _verdict(reasons: list[str], **extra) -> dict:
    if not reasons:
        verdict = "verified"
    elif any(not r.startswith(NO_VERDICT_PREFIXES) for r in reasons):
        verdict = "refused"
    else:
        verdict = "no_verdict"
    return dict(extra, verdict=verdict, ok=not reasons, reasons=reasons)


# ---------------------------------------------------------------- command line

def _emit(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj, sort_keys=True) + "\n")


def _load(path: str) -> Any:
    try:
        with open(path, encoding="utf-8") as fh:
            return cli.load(fh)
    except RecursionError:
        raise VerifyError("%s: JSON nested too deeply" % path) from None


USAGE = "usage: python -m profile.unit_verify check RECIPE POLICY | verify FILE"
EXIT = {"verified": 0, "refused": 1, "no_verdict": 2}


def main(argv: list[str]) -> int:
    try:
        if len(argv) == 3 and argv[0] == "check":
            reasons = vector_check(_load(argv[1]), _load(argv[2]))
            _emit({"ok": not reasons, "reasons": reasons})
            return 0 if not reasons else 1
        if len(argv) == 2 and argv[0] == "verify":
            req = _load(argv[1])
            if not isinstance(req, dict) or not isinstance(req.get("tree"), str):
                raise VerifyError("verify FILE must be {recipe, tree, policy, red_control, deps?, target?, base?}")
            report = verify(req.get("recipe"), req["tree"], req.get("policy"), req.get("red_control"),
                            req.get("deps"), req.get("target"), base=req.get("base"))
            _emit(report)
            return EXIT[report["verdict"]]
        _emit({"ok": False, "error": USAGE})
        return 2
    except (VerifyError, D.DeriveError, C.ContainmentError, ValueError, KeyError, TypeError, OSError,
            RecursionError) as exc:
        _emit({"ok": False, "error": "unusable input: %s" % cli.cause(exc)})
        return 2


FAULT_LINE = {"ok": False, "error": "internal error"}


if __name__ == "__main__":
    sys.exit(cli.run(main, sys.argv[1:], FAULT_LINE))
