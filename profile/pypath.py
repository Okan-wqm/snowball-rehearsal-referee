"""``profile.pypath``: the directories a Python file puts on ``sys.path`` itself, read statically (nothing is run),
used by ``status.depmap`` (the target's drawing): a dependency declared by code, not by a manifest.

``insertions(source, rel)`` reads a file at ``rel`` (relative to the checkout's root, ``/``-separated) and gives
``{"dirs", "unresolved", "leaves_root", "calls"}``: ``calls`` the number of insertion calls, ``dirs`` every
directory they insert, relative to the root (``""`` the root itself), in source order, ``unresolved`` the calls or
values no rule below resolves, ``leaves_root`` the values that leave the root. Raises ``SyntaxError`` (or
``ValueError``) when the source does not parse.

- an insertion call is ``sys.path.insert(<index>, X)`` or ``sys.path.append(X)``, written with the name ``sys``,
  anywhere in the file (a function's body too, whether or not it runs); any other argument count is unresolved;
- ``X`` is resolved when it is anchored at the file: built from ``__file__`` (the file's own path) by these, and
  only these, forms: ``Path(v)``/``pathlib.Path(v, "seg", ...)``, ``str(v)``, ``os.fspath(v)``, ``v.parent``,
  ``v.parents[n]`` (``n`` a non-negative integer literal: ``-1`` is an operator on one, unresolved), ``v / "seg"``, ``os.path.join(v, "seg", ...)``,
  ``os.path.dirname(v)``, ``v.resolve()``, ``v.absolute()``, ``os.path.abspath(v)``, ``os.path.realpath(v)``,
  ``os.path.normpath(v)``, a string literal as a segment (``"a/b"`` is two segments), and a name;
- a name resolves when the file binds it exactly once (all scopes counted together; an assignment, an annotated
  assignment, a ``for`` or ``with`` target, an argument, an import, a ``def`` or ``class`` each bind): an
  assignment of a single name or an annotated assignment gives its value's values, a ``for`` over a tuple or list
  literal gives each element's values (one call inserting such a name inserts each); a name bound twice or more,
  or by anything else, is unresolved;
- ``parent``, ``parents`` and ``dirname`` drop the last segment as written, as ``pathlib`` does
  (``Path("a/b/..").parent`` is ``a/b``); ``resolve``, ``abspath``, ``realpath`` and ``normpath`` fold ``..``
  lexically; a value whose segments go above the root, at any step, leaves the root; an absolute segment
  (``"/x"``) leaves it too; the inserted directory is the final value's segments folded;
- unresolved, stated: a value from the environment, the command line, the working directory (a relative string not
  built from ``__file__``, ``Path.cwd()``), a conditional or ``or``, a call outside the list (``with_name``,
  ``joinpath``, a helper function), ``import sys as s`` or ``from sys import path``, and ``sys.path[0:0] = ...``
  or ``site.addsitedir`` (not counted at all). Not followed, stated: symbolic links (``resolve`` and ``realpath``
  fold ``..`` without them).
"""

from __future__ import annotations

import ast
import posixpath
from typing import Any

PATH_CALLS = {"Path", "pathlib.Path"}
IDENTITY_CALLS = {"str", "os.fspath"}
FOLD_CALLS = {"os.path.abspath", "os.path.realpath", "os.path.normpath"}
FOLD_METHODS = {"resolve"}
KEEP_METHODS = {"absolute"}
LEAVES = "leaves_root"


def _dotted(node: ast.AST) -> str | None:
    """``a.b.c`` for a chain of attributes on a name, else None."""
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if not isinstance(node, ast.Name):
        return None
    parts.append(node.id)
    return ".".join(reversed(parts))


def _bindings(tree: ast.AST) -> dict[str, list[ast.AST]]:
    """Every name the file binds, with the node binding it each time (any scope)."""
    out: dict[str, list[ast.AST]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
            out.setdefault(node.id, []).append(node)
        elif isinstance(node, ast.arg):
            out.setdefault(node.arg, []).append(node)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            out.setdefault(node.name, []).append(node)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                out.setdefault((alias.asname or alias.name).split(".")[0], []).append(node)
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            for name in node.names:
                out.setdefault(name, []).append(node)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            out.setdefault(node.name, []).append(node)
    return out


class _Reader:
    def __init__(self, tree: ast.AST, rel: str) -> None:
        self.file = [s for s in rel.split("/") if s]
        self.bindings = _bindings(tree)
        self.sources: dict[int, ast.AST] = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                self.sources[id(node.targets[0])] = node.value
            elif isinstance(node, ast.AnnAssign) and node.value is not None and isinstance(node.target, ast.Name):
                self.sources[id(node.target)] = node.value
            elif isinstance(node, ast.For) and isinstance(node.target, ast.Name) and isinstance(
                    node.iter, (ast.Tuple, ast.List)):
                self.sources[id(node.target)] = node.iter
        self.seen: set[str] = set()

    # A value is ("str", text) or ("path", segments) for a path anchored at the root; LEAVES once it left the root.

    def values(self, node: ast.AST) -> list[Any] | None:
        """Every value ``node`` may have, or None when a rule does not resolve it."""
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return [("str", node.value)]
        if isinstance(node, ast.Name):
            if node.id == "__file__" and node.id not in self.bindings:
                return [("path", list(self.file))]
            return self._name(node.id)
        if isinstance(node, ast.Attribute) and node.attr == "parent":
            return self._map(node.value, lambda v: self._up(v, 1))
        if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Attribute) and \
                node.value.attr == "parents":
            index = node.slice
            if not (isinstance(index, ast.Constant) and type(index.value) is int):  # -1 is a unary minus
                return None
            return self._map(node.value.value, lambda v: self._up(v, index.value + 1))
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
            return self._join([node.left, node.right])
        if isinstance(node, ast.Call) and not node.keywords:
            return self._call(node)
        return None

    def _name(self, name: str) -> list[Any] | None:
        binds = self.bindings.get(name, [])
        if len(binds) != 1 or id(binds[0]) not in self.sources or name in self.seen:
            return None
        source = self.sources[id(binds[0])]
        self.seen.add(name)
        try:
            if isinstance(source, (ast.Tuple, ast.List)):
                out: list[Any] = []
                for element in source.elts:
                    vs = self.values(element)
                    if vs is None:
                        return None
                    out.extend(vs)
                return out
            return self.values(source)
        finally:
            self.seen.discard(name)

    def _call(self, node: ast.Call) -> list[Any] | None:
        func = _dotted(node.func)
        args = node.args
        if any(isinstance(a, ast.Starred) for a in args):
            return None
        if func in PATH_CALLS and args:
            return self._join(args)
        if func in IDENTITY_CALLS and len(args) == 1:
            return self.values(args[0])
        if func == "os.path.join" and args:
            return self._join(args)
        if func == "os.path.dirname" and len(args) == 1:
            return self._map(args[0], lambda v: self._up(v, 1))
        if func in FOLD_CALLS and len(args) == 1:
            return self._map(args[0], self._fold)
        if isinstance(node.func, ast.Attribute) and not args and node.func.attr in FOLD_METHODS | KEEP_METHODS:
            fold = node.func.attr in FOLD_METHODS
            return self._map(node.func.value, self._fold if fold else (lambda v: v))
        return None

    def _map(self, node: ast.AST, f) -> list[Any] | None:
        vs = self.values(node)
        if vs is None:
            return None
        out = []
        for v in vs:
            if v == LEAVES:
                out.append(v)
            elif v[0] != "path":
                return None
            else:
                out.append(f(v))
        return out

    def _join(self, nodes: list[ast.AST]) -> list[Any] | None:
        """The first node a path (a string only when absolute: it leaves the root), each next one a string."""
        heads = self.values(nodes[0])
        if heads is None:
            return None
        acc: list[Any] = []
        for head in heads:
            if head != LEAVES and head[0] != "path":
                if not head[1].startswith("/"):
                    return None
                head = LEAVES
            acc.append(head)
        for node in nodes[1:]:
            tails = self.values(node)
            if tails is None or any(t == LEAVES or t[0] != "str" for t in tails):
                return None
            acc = [LEAVES if a == LEAVES or t[1].startswith("/") else ("path", a[1] + [s for s in t[1].split("/") if s])
                   for a in acc for t in tails]
        return acc

    @staticmethod
    def _up(v: Any, n: int) -> Any:
        segs = v[1]
        if n > len(segs):
            return LEAVES
        return ("path", segs[:len(segs) - n])

    @staticmethod
    def _fold(v: Any) -> Any:
        out: list[str] = []
        for s in v[1]:
            if s == ".":
                continue
            if s == "..":
                if not out:
                    return LEAVES
                out.pop()
            else:
                out.append(s)
        return ("path", out)


def _insert_arg(node: ast.Call) -> tuple[bool, ast.AST | None]:
    """(is an insertion call, its path argument or None when the argument count is not the method's)."""
    func = _dotted(node.func)
    if func == "sys.path.insert":
        return True, node.args[1] if len(node.args) == 2 and not node.keywords else None
    if func == "sys.path.append":
        return True, node.args[0] if len(node.args) == 1 and not node.keywords else None
    return False, None


def insertions(source: str, rel: str) -> dict[str, Any]:
    return tree_insertions(ast.parse(source), rel)


def tree_insertions(tree: ast.AST, rel: str) -> dict[str, Any]:
    """``insertions`` of a parsed source; the file's bindings are read only when it holds an insertion call."""
    out: dict[str, Any] = {"calls": 0, "dirs": [], "unresolved": 0, "leaves_root": 0}
    calls = [(n, arg) for n in ast.walk(tree) if isinstance(n, ast.Call) for is_insert, arg in [_insert_arg(n)]
             if is_insert]
    if not calls:
        return out
    reader = _Reader(tree, rel)
    calls.sort(key=lambda c: (c[0].lineno, c[0].col_offset))
    for _node, arg in calls:
        out["calls"] += 1
        values = reader.values(arg) if arg is not None else None
        if values is None or any(v != LEAVES and v[0] != "path" for v in values):
            out["unresolved"] += 1
            continue
        for v in values:
            if v == LEAVES:
                out["leaves_root"] += 1
                continue
            folded = _Reader._fold(v)
            if folded == LEAVES:
                out["leaves_root"] += 1
            else:
                out["dirs"].append(posixpath.join(*folded[1]) if folded[1] else "")
    return out
