"""``profile.nx``: an Nx project's ``lint`` and ``test`` targets as the direct commands their executors run, for
``profile.fit`` when the candidate's ``package.json`` has no such script.

Read from Nx 22.7.12's own code (``nx``, ``@nx/eslint`` and ``@nx/jest`` from the npm registry: target merging,
``resolveNxTokensInOptions``, ``interpolate``, the ``@nx/eslint:lint`` and ``@nx/jest:jest`` executors). The rules
below are the part of that code this module reproduces; anything else is refused with a reason, never guessed.

**The workspace and the target** (``target``): ``nx.json`` at the tree's root is a JSON object (else
``no_workspace``; the workspace root is the tree's root, a nested Nx workspace is not read); the candidate's nearest
lock (``derive.nearest_lock``) is the root's ``package-lock.json`` or ``npm-shrinkwrap.json``, where the commands'
``node_modules/.bin`` lies (``lock_not_at_workspace_root``); ``<path>/project.json`` is a JSON object whose
``targets`` holds the target name (``no_target``). The target's keys are within ``executor``, ``options``,
``inputs``, ``outputs``, ``cache`` and ``configurations`` (``target_key:<key>``: ``dependsOn`` runs other tasks
first, ``defaultConfiguration`` changes the options, a ``command`` is ``nx:run-commands``); its ``executor`` is the
one the name maps to, ``@nx/eslint:lint`` for ``lint`` and ``@nx/jest:jest`` for ``test`` (``executor:<value>``);
its ``options`` keys are within that executor's supported set (``option:<key>``). The ``targetDefaults`` entry Nx
merges in (``readTargetDefaultsForTarget``: the executor's key, else the target name, else the longest glob key
matching the name, ``fnmatch`` standing for ``minimatch``) has only ``inputs``, ``outputs`` and ``cache``
(``target_defaults_key:<key>``), which change caching, not what runs. Option strings are resolved as
``resolveNxTokensInOptions`` does: a leading ``{workspaceRoot}`` with its ``/`` dropped, any other
``{workspaceRoot}`` refused (``token:workspaceRoot``), every ``{projectRoot}`` the candidate's path, every
``{projectName}`` the ``name`` of ``project.json`` (``token:projectName`` when it has none).

**lint** (``@nx/eslint:lint``, options ``lintFilePatterns`` only): the patterns (default ``["{projectRoot}"]``)
pass through the executor's ``interpolate`` (``nx_interpolate``); the flat config is the first of
``FLAT_CONFIGS`` in the candidate's directory, then each directory above it to the root (``findFlatConfigFile``;
none: ``no_flat_config``, the eslintrc path is not read); the lock's ``node_modules/eslint`` has a ``version`` of
major 9 or more (``eslint_version``: the ESLint CLI reads ``--config`` as a flat config from 9 on). The command,
run from the workspace root as the executor ``chdir``s there::

    node_modules/.bin/eslint --config <flat config> --no-error-on-unmatched-pattern --format json <patterns...>

which is the executor's ``ESLint`` call (``overrideConfigFile``, ``errorOnUnmatchedPattern: false``,
``lintFiles(patterns)``, no fix and no cache) with the ``json`` formatter on stdout. A pattern starting with ``-``
is refused (``pattern_option``). The flat config file joins the recipe's inputs.

**test** (``@nx/jest:jest``, options ``jestConfig`` only, required: ``option_missing:jestConfig``): the command is::

    env TS_NODE_COMPILER_OPTIONS=<the executor's value> node_modules/.bin/jest --config <jestConfig>

the executor's ``runCLI`` with the one config (``NODE_ENV`` is ``test`` in both, the jest binary setting it when
unset). ``jestConfig`` starting with ``-`` is refused (``pattern_option``); it joins the inputs when it is a
relative path inside the tree.

**lint inferred** (``inferred_lint``, ``@nx/eslint/plugin``'s ``createNodes``, when ``project.json`` has no ``lint``
key; an explicit target with an executor replaces the inferred one, ``isCompatibleTarget``, so the rules above
stay): ``nx.json``'s ``plugins`` is a list (``plugins``) whose every entry is ``@nx/eslint/plugin``, as a string or
an object (``plugin:<name>``: another plugin may infer or change a ``lint`` target and its code is not read), an
object with keys within ``plugin`` and ``options`` (``plugin_key:<key>``: ``include``/``exclude`` filter the files the
plugin sees) and options within ``targetName`` (a string, default ``lint``) and ``extensions`` (a list of strings,
leading dots dropped, default ``EXTENSIONS``) (``plugin_option:<key>``); exactly one entry names ``lint`` (none:
``no_target``; more: ``plugin_entries``). The candidate's directory holds ``project.json`` or ``package.json``
(``no_target``) and ``package.json``'s ``nx.targets`` has no ``lint`` (``package_nx_target``: its merge is not
reproduced). The plugin's ESLint root is the nearest directory, from the candidate's up to the tree's root, holding a
file of ``ESLINTRC`` or ``FLAT_CONFIGS`` (none: ``no_target``); it is the tree's root (``config_below_root``: ESLint
would read a config whose ``files`` patterns are relative to its own directory) and the root holds no ``ESLINTRC``
file (``eslintrc``: the plugin then sets ``ESLINT_USE_FLAT_CONFIG=false``); ESLint's major is 9 or more
(``eslint_version``). The project has a lintable file: a file (a symlink to one counts, a symlinked directory is not
entered) whose name ends in ``.<extension>``, in the candidate's directory or below it, not in ``node_modules`` or ``.git`` and not below another directory holding
``project.json`` or ``package.json`` (Nx gives such a file to that project) (``no_lintable_files``). The root
candidate ``.`` has ``package.json`` and ``src`` (else ``lib``) (``no_standalone_src``). The ``targetDefaults``
entry, read for executor ``nx:run-commands`` (the ``command`` sugar is resolved first), passes the rule above. The
plugin's target is ``eslint .`` (``eslint ./src`` for the root) run by ``nx:run-commands`` with ``cwd`` the
candidate's directory and the workspace's ``node_modules/.bin`` on ``PATH``, the caller's arguments appended::

    /bin/sh -c 'cd -- "$0" && exec "$@"' <path> /work/node_modules/.bin/eslint <. or ./src or ./lib> --format json

The POSIX shell (``CD_EXEC``; the path is its ``$0``, an argument, never part of the script text) gives ESLint the
candidate's directory as its working directory, where it looks up the flat config from (the root's, as no
configuration lies between) and where the config's own code resolves relative paths; the program is the root lock's
(``/work`` is the tree's root in every run, ``runner.contained.WORKDIR``). Every flat config at the root joins the
inputs. Not reproduced: ESLint's ignores and ``.gitignore``/``.nxignore`` in the lintable-file rule (Nx asks
``isPathIgnored``, which evaluates the config: a project whose every file ESLint ignores has no inferred target, and
the command composed here fails in the run, ESLint 9 refusing a pattern whose files are all ignored), the plugin's
targets cache.

Not reproduced (a run shows any difference): Nx's ``.env`` files loaded into a task's environment, a target a plugin
infers other than the ``lint`` above, a project declared only in ``package.json``'s ``nx`` field, ``nx:run-commands``
and other executors, the eslintrc configuration, the files a configuration reaches (its imports, a jest ``preset``
such as a root ``jest.preset.js``, a tsconfig's ``extends``: ``profile.fit.reached`` adds them), whether the
programs exist in the installed packages (``unit_verify.check_recipe`` judges the ``.bin`` paths against the lock).
"""

from __future__ import annotations

import fnmatch
import json
import os
import posixpath
import re
from typing import Any

from profile import derive as D
from runner import contained as C

FLAT_CONFIGS = ("eslint.config.cjs", "eslint.config.js", "eslint.config.mjs", "eslint.config.cts",
                "eslint.config.ts", "eslint.config.mts")
# ESLint's own lookup order in one directory (eslint 9.39.4, lib/config/config-loader.js FLAT_CONFIG_FILENAMES,
# given to find-up from the working directory): the same six names as Nx's, another order.
ESLINT_FLAT_CONFIGS = ("eslint.config.js", "eslint.config.mjs", "eslint.config.cjs", "eslint.config.ts",
                       "eslint.config.mts", "eslint.config.cts")
ESLINTRC = (".eslintrc", ".eslintrc.js", ".eslintrc.cjs", ".eslintrc.yaml", ".eslintrc.yml", ".eslintrc.json")
EXTENSIONS = ("ts", "cts", "mts", "tsx", "js", "cjs", "mjs", "jsx", "html", "vue")
PLUGIN = "@nx/eslint/plugin"
CD_EXEC = 'cd -- "$0" && exec "$@"'
PLUGIN_KEYS = ("plugin", "options")
PLUGIN_OPTIONS = ("targetName", "extensions")
SKIPPED_DIRS = ("node_modules", ".git")
EXECUTORS = {"lint": "@nx/eslint:lint", "test": "@nx/jest:jest"}
OPTIONS = {"lint": ("lintFilePatterns",), "test": ("jestConfig",)}
TARGET_KEYS = ("executor", "options", "inputs", "outputs", "cache", "configurations")
DEFAULTS_KEYS = ("inputs", "outputs", "cache")
TS_NODE = json.dumps({"moduleResolution": "Node10", "module": "commonjs", "customConditions": None},
                     separators=(",", ":"))
REPLACEMENT = re.compile(r"{([\s\S]+?)}")


class NotComposed(Exception):
    """The target is outside the rules above; ``reasons`` is ``[<the reason code>]`` (``cli.KEPT_ATTRIBUTES``)."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reasons = [reason]


def resolve_tokens(value: str, root: str, name: Any) -> str:
    """Nx's ``resolveNxTokensInOptions`` on one string."""
    value = re.sub(r"^\{workspaceRoot\}/?", "", value, count=1)
    if "{workspaceRoot}" in value:
        raise NotComposed("token:workspaceRoot")
    value = value.replace("{projectRoot}", root)
    if "{projectName}" in value:
        if not isinstance(name, str) or not name:
            raise NotComposed("token:projectName")
        value = value.replace("{projectName}", name)
    return value


def _node_join(parts: list[str]) -> str:
    """Node's ``path.posix.join`` for relative parts: the non-empty parts joined and normalised, a trailing ``/``
    kept, ``.`` when nothing is left."""
    joined = "/".join(p for p in parts if p)
    if not joined:
        return "."
    norm = posixpath.normpath(joined)
    return norm + "/" if joined.endswith("/") and norm != "/" else norm


def nx_interpolate(template: str, root: str, name: Any) -> str:
    """The executor's ``interpolate`` with ``{workspaceRoot: '', projectRoot, projectName}``."""
    if template.startswith("/") or not REPLACEMENT.search(template):
        return template
    if template.find("{workspaceRoot}", 1) != -1:
        raise NotComposed("token:workspaceRoot")
    if root == "." and template.find("{projectRoot}", 1) != -1:
        raise NotComposed("token:projectRoot")
    data = {"workspaceRoot": "", "projectRoot": root, "projectName": name}

    def one(part: str) -> str:
        if root == ".":
            part = part.replace("{projectRoot}", "", 1)

        def sub(match: re.Match) -> str:
            value: Any = data
            for key in match.group(0)[1:-1].strip().split("."):
                if not isinstance(value, dict) or not value.get(key):
                    return match.group(0)
                value = value[key]
            return value if isinstance(value, str) else match.group(0)
        return REPLACEMENT.sub(sub, part)
    return _node_join([one(p) for p in template.split("/")]).replace("{workspaceRoot}/", "", 1)


def _target_defaults(nx: dict, name: str, executor: str) -> Any:
    defaults = nx.get("targetDefaults")
    if not isinstance(defaults, dict):
        return None
    if executor in defaults:
        return defaults[executor]
    if name in defaults:
        return defaults[name]
    globbed = [k for k in defaults if any(c in k for c in "*?[{") and fnmatch.fnmatchcase(name, k)]
    return defaults[max(globbed, key=len)] if globbed else None


def _rel(path: str, name: str) -> str:
    return name if path == "." else posixpath.join(path, name)


def workspace(tree: str, path: str) -> dict:
    """``nx.json`` of the workspace candidate ``path`` lies in, its lock at the root (module docstring)."""
    _, nx = D._json(tree, "nx.json")
    if not isinstance(nx, dict):
        raise NotComposed("no_workspace")
    if D.nearest_lock(tree, path) not in ("package-lock.json", "npm-shrinkwrap.json"):
        raise NotComposed("lock_not_at_workspace_root")
    return nx


def _project(tree: str, path: str) -> tuple[Any, Any]:
    """``(project.json, its targets)`` of candidate ``path``, each None when not a JSON object."""
    _, project = D._json(tree, _rel(path, "project.json"))
    project = project if isinstance(project, dict) else None
    targets = project.get("targets") if project else None
    return project, targets if isinstance(targets, dict) else None


def _check_defaults(nx: dict, name: str, executor: str) -> None:
    defaults = _target_defaults(nx, name, executor)
    if defaults is not None:
        if not isinstance(defaults, dict):
            raise NotComposed("target_defaults_key:" + name)
        for key in sorted(defaults):
            if key not in DEFAULTS_KEYS:
                raise NotComposed("target_defaults_key:" + key)


def target(tree: str, path: str, name: str) -> tuple[dict, dict]:
    """``(project, options)`` of target ``name`` of candidate ``path``, token-resolved (module docstring)."""
    nx = workspace(tree, path)
    project, targets = _project(tree, path)
    spec = targets.get(name) if targets is not None else None
    if not isinstance(spec, dict):
        raise NotComposed("no_target")
    for key in sorted(spec):
        if key not in TARGET_KEYS:
            raise NotComposed("target_key:" + key)
    if spec.get("executor") != EXECUTORS[name]:
        raise NotComposed("executor:%s" % spec.get("executor"))
    options = spec.get("options", {})
    if not isinstance(options, dict):
        raise NotComposed("option:options")
    for key in sorted(options):
        if key not in OPTIONS[name]:
            raise NotComposed("option:" + key)
    _check_defaults(nx, name, EXECUTORS[name])

    def resolved(value: Any) -> Any:
        if isinstance(value, str):
            return resolve_tokens(value, path, project.get("name"))
        if isinstance(value, list):
            return [resolved(v) for v in value]
        return value
    return project, {k: resolved(v) for k, v in options.items()}


def flat_config(tree: str, path: str, names: tuple = FLAT_CONFIGS, exists=os.path.exists) -> str | None:
    """The nearest flat config from the candidate's directory up to the root, as a tree path, or None: in each
    directory the first of ``names`` for which ``exists`` holds. The defaults are Nx's ``findFlatConfigFile``;
    ``ESLINT_FLAT_CONFIGS`` with ``os.path.isfile`` is ESLint's own lookup from that directory."""
    directory = path
    while True:
        for file in names:
            rel = file if directory == "." else posixpath.join(directory, file)
            if exists(os.path.join(tree, rel)):
                return rel
        if directory == ".":
            return None
        directory = posixpath.dirname(directory) or "."


def _major(version: Any) -> int | None:
    match = re.match(r"(\d+)\.", version) if isinstance(version, str) else None
    return int(match.group(1)) if match else None


def _check_eslint(tree: str, path: str) -> None:
    _, parsed = D._json(tree, D.nearest_lock(tree, path))
    packages = parsed.get("packages") if isinstance(parsed, dict) else None
    eslint = packages.get("node_modules/eslint") if isinstance(packages, dict) else None
    major = _major(eslint.get("version")) if isinstance(eslint, dict) else None
    if major is None or major < 9:
        raise NotComposed("eslint_version")


def _plugin_extensions(nx: dict) -> list[str]:
    """The ``extensions`` of the one ``@nx/eslint/plugin`` entry naming ``lint`` (module docstring)."""
    plugins = nx.get("plugins", [])
    if not isinstance(plugins, list):
        raise NotComposed("plugins")
    found = []
    for entry in plugins:
        plugin = entry if isinstance(entry, str) else entry.get("plugin") if isinstance(entry, dict) else None
        if plugin != PLUGIN:
            raise NotComposed("plugin:%s" % plugin)
        if isinstance(entry, str):
            entry = {}
        for key in sorted(entry):
            if key not in PLUGIN_KEYS:
                raise NotComposed("plugin_key:" + key)
        options = entry.get("options", {})
        if not isinstance(options, dict):
            raise NotComposed("plugin_option:options")
        for key in sorted(options):
            if key not in PLUGIN_OPTIONS:
                raise NotComposed("plugin_option:" + key)
        name = options.get("targetName", "lint")
        extensions = options.get("extensions", list(EXTENSIONS))
        if not isinstance(name, str):
            raise NotComposed("plugin_option:targetName")
        if not isinstance(extensions, list) or not all(isinstance(e, str) for e in extensions):
            raise NotComposed("plugin_option:extensions")
        if name == "lint":
            found.append([re.sub(r"^\.+", "", e) for e in extensions])
    if not found:
        raise NotComposed("no_target")
    if len(found) > 1:
        raise NotComposed("plugin_entries")
    return found[0]


def _eslint_root(tree: str, path: str) -> str | None:
    """The nearest directory from ``path`` up to the root holding a file of ``ESLINTRC`` or ``FLAT_CONFIGS``."""
    directory = path
    while True:
        if any(os.path.isfile(os.path.join(tree, _rel(directory, f))) for f in ESLINTRC + FLAT_CONFIGS):
            return directory
        if directory == ".":
            return None
        directory = posixpath.dirname(directory) or "."


def has_lintable(tree: str, path: str, extensions: list[str]) -> bool:
    """A lintable file of the project at ``path`` (module docstring)."""
    suffixes = tuple("." + e for e in extensions)
    top = os.path.join(tree, path)
    for here, dirs, files in os.walk(top):
        dirs[:] = sorted(d for d in dirs if d not in SKIPPED_DIRS and not any(
            os.path.isfile(os.path.join(here, d, f)) for f in D.PROJECT_MANIFESTS))
        if any(f.endswith(suffixes) and os.path.isfile(os.path.join(here, f)) for f in files):
            return True
    return False


def inferred_lint(tree: str, path: str, nx: dict) -> tuple[list[str], list[str]]:
    """``(lint_cmd, extra inputs)`` of the ``lint`` target ``@nx/eslint/plugin`` infers (module docstring)."""
    extensions = _plugin_extensions(nx)
    if not any(os.path.isfile(os.path.join(tree, _rel(path, f))) for f in D.PROJECT_MANIFESTS):
        raise NotComposed("no_target")
    _, manifest = D._json(tree, _rel(path, "package.json"))
    declared = manifest.get("nx") if isinstance(manifest, dict) else None
    declared = declared.get("targets") if isinstance(declared, dict) else None
    if isinstance(declared, dict) and "lint" in declared:
        raise NotComposed("package_nx_target")
    root = _eslint_root(tree, path)
    if root is None:
        raise NotComposed("no_target")
    if root != ".":
        raise NotComposed("config_below_root")
    if any(os.path.isfile(os.path.join(tree, f)) for f in ESLINTRC):
        raise NotComposed("eslintrc")
    _check_eslint(tree, path)
    if not has_lintable(tree, path, extensions):
        raise NotComposed("no_lintable_files")
    pattern = "."
    if path == ".":
        src = [d for d in ("src", "lib") if os.path.exists(os.path.join(tree, d))]
        if not os.path.isfile(os.path.join(tree, "package.json")) or not src:
            raise NotComposed("no_standalone_src")
        pattern = "./" + src[0]
    _check_defaults(nx, "lint", "nx:run-commands")
    return (["/bin/sh", "-c", CD_EXEC, path, C.WORKDIR + "/node_modules/.bin/eslint", pattern, "--format", "json"],
            [f for f in FLAT_CONFIGS if os.path.isfile(os.path.join(tree, f))])


def lint(tree: str, path: str) -> tuple[list[str], list[str]]:
    """``(lint_cmd, extra inputs)`` of the ``lint`` target, explicit or else inferred; ``NotComposed`` with the
    reason otherwise."""
    nx = workspace(tree, path)
    _, targets = _project(tree, path)
    if targets is None or "lint" not in targets:
        return inferred_lint(tree, path, nx)
    project, options = target(tree, path, "lint")
    patterns = options.get("lintFilePatterns", ["{projectRoot}"])
    if not isinstance(patterns, list) or not patterns or not all(isinstance(p, str) and p for p in patterns):
        raise NotComposed("option:lintFilePatterns")
    patterns = [nx_interpolate(p, path, project.get("name")) for p in patterns]
    if any(p.startswith("-") for p in patterns):
        raise NotComposed("pattern_option")
    config = flat_config(tree, path)
    if config is None:
        raise NotComposed("no_flat_config")
    _check_eslint(tree, path)
    return (["node_modules/.bin/eslint", "--config", config, "--no-error-on-unmatched-pattern", "--format", "json"]
            + patterns, [config])


def test(tree: str, path: str) -> tuple[list[str], list[str]]:
    """``(test_cmd, extra inputs)`` of the ``test`` target; ``NotComposed`` with the reason otherwise."""
    _, options = target(tree, path, "test")
    config = options.get("jestConfig")
    if config is None:
        raise NotComposed("option_missing:jestConfig")
    if not isinstance(config, str) or not config:
        raise NotComposed("option:jestConfig")
    if config.startswith("-"):
        raise NotComposed("pattern_option")
    norm = D.norm_path(config)
    return (["env", "TS_NODE_COMPILER_OPTIONS=" + TS_NODE, "node_modules/.bin/jest", "--config", config],
            [norm] if norm else [])
