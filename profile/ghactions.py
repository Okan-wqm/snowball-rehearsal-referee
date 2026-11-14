"""``profile.ghactions``: the image builds a GitHub Actions file declares, read statically (nothing is run), used by
``status.depmap`` to give a Dockerfile the build context that no compose file gives it.

A file is read when ``is_actions_file`` says so. ``builds(doc)`` takes a file read by ``profile.yamlblock.load`` and gives ``[Build]``, one per step whose ``uses``
names ``docker/build-push-action`` (owner and name compared case-insensitively, any ref after ``@``), in file
order: ``where`` (``jobs.<id>.steps[<n>]``, or ``runs.steps[<n>]`` for a composite action), ``pairs`` (the
distinct ``(context, file)`` the step builds, sorted) and ``reason`` (``None`` when every combination resolved,
else one of ``REASONS``; ``pairs`` is then empty). The step's ``with.context`` and ``with.file`` are evaluated once
per combination of its job's matrix (``matrices``):

- a value without ``${{`` is taken as written; each ``${{ expression }}`` in it is evaluated (``evaluate``) and
  its result written into the text (``null`` as empty, ``true``/``false``, a number as Python writes an ``int`` or
  ``float``); a value that is not a string is written the same way;
- an empty or missing ``context`` is ``.`` (the action's Git context: the repository's root); an empty or missing
  ``file`` is ``<context>/Dockerfile``; both are paths from the repository's root (the action passes ``file`` to
  Buildx as given, relative to the workspace, not to the context); a leading ``./`` is removed.

``matrices(job)`` gives the job's combinations as dicts, by GitHub's rules: no ``strategy.matrix``, one empty
combination; else the product of its axes (every key but ``include`` and ``exclude``, each a list), less every
combination that an ``exclude`` entry matches (each of its keys equal), then each ``include`` entry added to every
combination of the axes whose original values it does not change (overwriting keys added by an earlier entry) or,
when it matches none, appended as a combination of its own (never matched by a later entry). A matrix, an axis,
``include`` or ``exclude`` written as an expression (``${{ fromJson(...) }}``), or an axis value holding one, is
``matrix_dynamic``; the combinations are computed only when the axes give at most ``MAX_COMBINATIONS`` and
``include`` has at most that many entries (more is ``matrix_dynamic`` too).

``evaluate(expression, matrix)`` reads GitHub's expression language over the ``matrix`` context only: string
literals (``'...'``, ``''`` a quote), numbers, ``true``, ``false``, ``null``, ``matrix.a.b`` (a key missing is
``null``), ``!``, ``==``, ``!=``, ``&&``, ``||`` (operands returned as GitHub does: ``a && b`` is ``a`` when ``a``
is falsy, else ``b``; ``a || b`` is ``a`` when truthy, else ``b``) and parentheses. ``==`` compares two strings
ignoring case and values of different types as numbers (``null`` 0, ``true`` 1, a string its number or NaN).
Another context (``inputs``, ``steps``, ``needs``, ``env``, ``github``, ``vars``, ``secrets``, ...) is unknown: an
operator over an unknown operand is unknown, except that ``&&`` and ``||`` return their left operand when it
decides them; an unknown result is ``context``. A function call is ``function``; ``<``, ``<=``, ``>``, ``>=``,
an index ``[...]`` or ``*`` is ``operator``; any other text is ``syntax``.

Not read, stated: ``docker build`` and ``docker buildx build`` command lines in ``run`` (none in the target
measured on 2026-11-05), ``docker/bake-action``, a composite action's inputs as given by its callers (its builds are
``context``), a reusable workflow's inputs (``context``), ``if:`` conditions (a step is counted whether it runs or
not), the Git context's subdirectory form (``{{defaultContext}}:dir``, kept as text), ``build-contexts``.
"""

from __future__ import annotations

import itertools
import re
from typing import Any, NamedTuple

import cli

ACTION = "docker/build-push-action"
REASONS = ("matrix_dynamic", "context", "function", "operator", "syntax")
MAX_COMBINATIONS = 256

_TOKEN = re.compile(r"\s*(?:(?P<str>'(?:[^']|'')*')|(?P<num>[-+]?(?:0x[0-9A-Fa-f]+|[0-9]+(?:\.[0-9]*)?"
                    r"(?:[eE][-+]?[0-9]+)?))|(?P<name>[A-Za-z_][A-Za-z0-9_-]*(?:\.[A-Za-z_*][A-Za-z0-9_-]*)*)"
                    r"|(?P<op>==|!=|&&|\|\||<=|>=|[!()<>\[\]*,]))")
_EXPR = re.compile(r"\$\{\{(.*?)\}\}", re.S)
_UNKNOWN = object()
_PREC = {"||": 1, "&&": 2, "==": 3, "!=": 3}


class Unresolved(ValueError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class Build(NamedTuple):
    where: str
    pairs: list[tuple[str, str]]
    reason: str | None


def _truthy(v: Any) -> bool:
    if v is None or v is False or v == "":
        return False
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return v == v and v != 0
    return True


def _number(v: Any) -> float:
    if v is None:
        return 0.0
    if isinstance(v, bool):
        return 1.0 if v else 0.0
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        s = v.strip()
        if s == "":
            return 0.0
        try:
            return float(int(s, 16)) if s.lower().startswith(("0x", "-0x", "+0x")) else float(s)
        except ValueError:
            return float("nan")
    return float("nan")


def _equal(a: Any, b: Any) -> bool:
    if isinstance(a, str) and isinstance(b, str):
        return a.casefold() == b.casefold()
    if type(a) is type(b) and not isinstance(a, (str, int, float)):
        return a == b
    return _number(a) == _number(b)


def _apply(op: str, stack: list[Any]) -> None:
    if op == "!":
        v = stack.pop()
        stack.append(_UNKNOWN if v is _UNKNOWN else not _truthy(v))
        return
    b, a = stack.pop(), stack.pop()
    if op in ("&&", "||"):
        if a is _UNKNOWN:
            stack.append(_UNKNOWN)
        elif _truthy(a) == (op == "||"):
            stack.append(a)
        else:
            stack.append(b)
        return
    if a is _UNKNOWN or b is _UNKNOWN:
        stack.append(_UNKNOWN)
    else:
        stack.append(_equal(a, b) == (op == "=="))


def _lookup(name: str, matrix: dict[str, Any]) -> Any:
    parts = name.split(".")
    if parts[0].lower() != "matrix":
        return _UNKNOWN
    value: Any = matrix
    for part in parts[1:]:
        if part == "*":
            raise Unresolved("operator")
        value = value.get(part) if isinstance(value, dict) else None
    return value


def evaluate(expression: str, matrix: dict[str, Any]) -> Any:
    """The value of ``expression``; raises ``Unresolved`` (see the module's docstring)."""
    values: list[Any] = []
    ops: list[str] = []
    j = 0
    expect_value = True
    text = expression.strip()
    while j < len(text):
        m = _TOKEN.match(text, j)
        if m is None or m.end() == j:
            if text[j:].strip() == "":
                break
            raise Unresolved("syntax")
        j = m.end()
        if m.group("str") is not None:
            token: Any = m.group("str")[1:-1].replace("''", "'")
            kind = "value"
        elif m.group("num") is not None:
            token = _number(m.group("num"))
            token = int(token) if token == int(token) and "." not in m.group("num") else token
            kind = "value"
        elif m.group("name") is not None:
            name = m.group("name")
            if text[j:].lstrip().startswith("("):
                raise Unresolved("function")
            token = {"true": True, "false": False, "null": None}.get(name, _UNKNOWN) \
                if "." not in name and name in ("true", "false", "null") else _lookup(name, matrix)
            kind = "value"
        else:
            token = m.group("op")
            kind = "op"
        if kind == "value":
            if not expect_value:
                raise Unresolved("syntax")
            values.append(token)
            expect_value = False
            while ops and ops[-1] == "!":
                _apply(ops.pop(), values)
            continue
        if token in ("<", "<=", ">", ">=", "[", "]", "*", ","):
            raise Unresolved("operator")
        if token == "!" or token == "(":
            if not expect_value:
                raise Unresolved("syntax")
            ops.append(token)
            continue
        if token == ")":
            if expect_value:
                raise Unresolved("syntax")
            while ops and ops[-1] != "(":
                _apply(ops.pop(), values)
            if not ops:
                raise Unresolved("syntax")
            ops.pop()
            while ops and ops[-1] == "!":
                _apply(ops.pop(), values)
            continue
        if expect_value:
            raise Unresolved("syntax")
        while ops and ops[-1] in _PREC and _PREC[ops[-1]] >= _PREC[token]:
            _apply(ops.pop(), values)
        ops.append(token)
        expect_value = True
    if expect_value:
        raise Unresolved("syntax")
    while ops:
        op = ops.pop()
        if op == "(":
            raise Unresolved("syntax")
        _apply(op, values)
    if len(values) != 1:
        raise Unresolved("syntax")
    if values[0] is _UNKNOWN:
        raise Unresolved("context")
    return values[0]


def _text(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return str(int(v)) if isinstance(v, float) and v == int(v) else str(v)
    if isinstance(v, str):
        return v
    raise Unresolved("syntax")


def interpolate(value: Any, matrix: dict[str, Any]) -> str:
    """``value`` with each ``${{ expression }}`` replaced by its result's text."""
    if not isinstance(value, str):
        return _text(value)
    return _EXPR.sub(lambda m: _text(evaluate(m.group(1), matrix)), value)


def _dynamic(value: Any) -> bool:
    return isinstance(value, str) and "${{" in value


def matrices(job: Any) -> list[dict[str, Any]]:
    strategy = job.get("strategy") if isinstance(job, dict) else None
    matrix = strategy.get("matrix") if isinstance(strategy, dict) else None
    if matrix is None:
        return [{}]
    if not isinstance(matrix, dict):
        raise Unresolved("matrix_dynamic")
    axes = {k: v for k, v in matrix.items() if k not in ("include", "exclude")}
    include = matrix.get("include") or []
    exclude = matrix.get("exclude") or []
    if any(not isinstance(v, list) for v in axes.values()) or not isinstance(include, list) \
            or not isinstance(exclude, list) or any(not isinstance(e, dict) for e in include + exclude) \
            or any(_dynamic(x) for v in axes.values() for x in v):
        raise Unresolved("matrix_dynamic")
    size = 1
    for v in axes.values():
        size *= len(v)
    if size > MAX_COMBINATIONS or len(include) > MAX_COMBINATIONS:
        raise Unresolved("matrix_dynamic")
    names = list(axes)
    combos = [dict(zip(names, values)) for values in itertools.product(*axes.values())] if axes else []
    combos = [c for c in combos
              if not any(all(k in c and _equal(c[k], v) for k, v in e.items()) for e in exclude)]
    originals = [dict(c) for c in combos]
    added: list[dict[str, Any]] = []
    for entry in include:
        matched = False
        for combo, original in zip(combos, originals):
            if all(_equal(original[k], v) for k, v in entry.items() if k in original):
                combo.update(entry)
                matched = True
        if not matched:
            added.append(dict(entry))
    return combos + added


def _norm(path: str) -> str:
    while path.startswith("./"):
        path = path[2:]
    return path or "."


def _steps(doc: Any) -> list[tuple[str, Any, list]]:
    """``(prefix, job, steps)`` of a workflow's jobs or a composite action's ``runs``."""
    out: list[tuple[str, Any, list]] = []
    if not isinstance(doc, dict):
        return out
    jobs = doc.get("jobs")
    if isinstance(jobs, dict):
        for name, job in jobs.items():
            if isinstance(job, dict) and isinstance(job.get("steps"), list):
                out.append(("jobs.%s.steps" % name, job, job["steps"]))
    runs = doc.get("runs")
    if isinstance(runs, dict) and isinstance(runs.get("steps"), list):
        out.append(("runs.steps", {}, runs["steps"]))
    return out


def is_actions_file(rel: str) -> bool:
    """A workflow (a ``.yml``/``.yaml`` file directly in the root's ``.github/workflows``, the only place GitHub
    reads them) or an action's metadata (``action.yml``/``action.yaml`` anywhere)."""
    head, _sep, name = rel.rpartition("/")
    return (head == ".github/workflows" and name.endswith((".yml", ".yaml"))) or name in ("action.yml", "action.yaml")


def is_build(step: Any) -> bool:
    uses = step.get("uses") if isinstance(step, dict) else None
    return isinstance(uses, str) and uses.partition("@")[0].lower() == ACTION


def builds(doc: Any) -> list[Build]:
    out: list[Build] = []
    for prefix, job, steps in _steps(doc):
        for n, step in enumerate(steps):
            if not is_build(step):
                continue
            where = "%s[%d]" % (prefix, n)
            given = step.get("with") if isinstance(step.get("with"), dict) else {}
            try:
                pairs = set()
                for combo in matrices(job):
                    context = _norm(interpolate(given.get("context"), combo))
                    file = interpolate(given.get("file"), combo)
                    pairs.add((context, _norm(file) if file else _norm(context + "/Dockerfile")))
            except Unresolved as e:
                out.append(Build(where, [], cli.cause(e)))
                continue
            out.append(Build(where, sorted(pairs), None))
    return out
