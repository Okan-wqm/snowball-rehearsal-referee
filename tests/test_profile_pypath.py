"""``profile.pypath`` (run with test 47): the directories a Python file puts on ``sys.path``, read statically.

Each rule of the module's docstring on a source made for it: every resolving form (``Path``/``pathlib.Path`` with
segments, ``str``, ``os.fspath``, ``parent``, ``parents[n]``, ``/``, ``os.path.join``, ``dirname``, ``resolve``,
``absolute``, ``abspath``, ``realpath``, ``normpath``, a multi-segment literal, a name); ``parent`` lexical and
``resolve`` folding; a name bound once (assignment, annotated assignment, ``for`` over a literal) and a name bound
twice or by an argument; leaving the root (``parents``, a fold above the root, an absolute segment); the
unresolved forms (working directory, environment, ``or``, a relative string, a wrong argument count, a call outside
the list, a negative or non-literal index, a rebound ``__file__``); the calls not counted (an alias of ``sys``,
slice assignment); a function's body counted; source order; a source that does not parse; ``tree_insertions``
(a parsed source, the reader ``status.depmap`` calls) gives ``insertions``'s result and reads a file's bindings only
when it holds an insertion call.
"""

from __future__ import annotations

import os
import sys
import unittest

REFEREE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REFEREE)

from profile import pypath as P  # noqa: E402

HEAD = "import os\nimport sys\nimport pathlib\nfrom pathlib import Path\n"
FILE = "a/b/c.py"


def dirs(body: str, rel: str = FILE) -> dict:
    return P.insertions(HEAD + body, rel)


class Resolved(unittest.TestCase):
    def one(self, expr: str) -> str:
        r = dirs("sys.path.insert(0, %s)\n" % expr)
        self.assertEqual((r["calls"], r["unresolved"], r["leaves_root"]), (1, 0, 0), expr)
        self.assertEqual(len(r["dirs"]), 1, expr)
        return r["dirs"][0]

    def test_each_form(self):
        cases = {
            "str(Path(__file__).resolve().parents[1] / 'tools' / 'poc')": "a/tools/poc",
            "str(Path(__file__).parents[0])": "a/b",
            "Path(__file__).parent.parent": "a",
            "str(pathlib.Path(__file__, '..', 'lib').resolve())": "a/b/lib",
            "os.fspath(Path(__file__).parent / 'x/y')": "a/b/x/y",      # a literal of two segments
            "os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'lib')": "a/lib",
            "os.path.dirname(os.path.realpath(__file__))": "a/b",
            "os.path.normpath(os.path.join(os.path.dirname(__file__), '..'))": "a",
            "str(Path(__file__).absolute().parent)": "a/b",
            "Path(__file__).parents[2]": "",                              # the root itself
        }
        for expr, want in cases.items():
            self.assertEqual(self.one(expr), want, expr)

    def test_parent_is_lexical_and_resolve_folds(self):
        self.assertEqual(self.one("(Path(__file__).parent / '..').parent"), "a/b")
        self.assertEqual(self.one("(Path(__file__).parent / '..').resolve().parent"), "")
        self.assertEqual(self.one("os.path.dirname(os.path.join(os.path.dirname(__file__), '..'))"), "a/b")

    def test_names_bound_once(self):
        r = dirs("ROOT = Path(__file__).resolve().parents[1]\nPOC: Path = ROOT / 'tools'\nSEG = 'poc'\n"
                 "def f():\n    if str(POC / SEG) not in sys.path:\n        sys.path.insert(0, str(POC / SEG))\n")
        self.assertEqual(r, {"calls": 1, "dirs": ["a/tools/poc"], "unresolved": 0, "leaves_root": 0})

    def test_a_for_over_a_literal_inserts_each(self):
        r = dirs("R = Path(__file__).parent\nfor p in (R / 'x', str(R / 'y')):\n    sys.path.insert(0, str(p))\n")
        self.assertEqual(r["dirs"], ["a/b/x", "a/b/y"])
        self.assertEqual(r["calls"], 1)

    def test_source_order(self):
        r = dirs("sys.path.append(os.path.dirname(__file__))\nsys.path.insert(0, str(Path(__file__).parents[1]))\n")
        self.assertEqual(r["dirs"], ["a/b", "a"])


class LeavesRoot(unittest.TestCase):
    def test_each_way_out(self):
        for expr in ("Path(__file__).parents[3]", "Path(__file__).parent.parent.parent.parent",
                     "(Path(__file__).parent / '../../..').resolve()", "Path('/opt/x')",
                     "os.path.join(os.path.dirname(__file__), '/etc')"):
            r = dirs("sys.path.insert(0, str(%s))\n" % expr)
            self.assertEqual((r["calls"], r["dirs"], r["unresolved"], r["leaves_root"]), (1, [], 0, 1), expr)

    def test_a_fold_above_the_root_at_insertion(self):
        r = dirs("sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..', 'x'))\n")
        self.assertEqual((r["dirs"], r["leaves_root"]), ([], 1))


class Unresolved(unittest.TestCase):
    def test_each_unresolved_form(self):
        for body in ("sys.path.insert(0, os.getcwd())\n",
                     "sys.path.insert(0, str(Path.cwd()))\n",
                     "sys.path.insert(0, 'lib')\n",
                     "sys.path.insert(0, str(Path('lib') / 'x'))\n",
                     "sys.path.insert(0, os.environ['X'])\n",
                     "sys.path.insert(0, os.environ.get('X') or os.path.dirname(__file__))\n",
                     "sys.path.insert(0, str(Path(__file__).parent if True else Path(__file__)))\n",
                     "sys.path.insert(0, str(Path(__file__).with_name('x')))\n",
                     "sys.path.insert(0, str(Path(__file__).parents[-1]))\n",
                     "sys.path.insert(0, str(Path(__file__).parents[True]))\n",
                     "i = 1\nsys.path.insert(0, str(Path(__file__).parents[i]))\n",
                     "sys.path.insert(str(Path(__file__).parent))\n",
                     "sys.path.append(path=str(Path(__file__).parent))\n",
                     "sys.path.append(os.path.dirname(__file__), 'x')\n",
                     "sys.path.insert(0, str(Path(__file__).parent / Path(__file__).parent))\n",
                     "R = Path(__file__).parent\nR = R / 'x'\nsys.path.insert(0, str(R))\n",
                     "def f(R):\n    pass\nR = Path(__file__).parent\nsys.path.insert(0, str(R))\n",
                     "for p in paths():\n    sys.path.insert(0, p)\n",
                     "for p in (Path(__file__).parent, os.getcwd()):\n    sys.path.insert(0, str(p))\n",
                     "__file__ = 'x.py'\nsys.path.insert(0, os.path.dirname(__file__))\n",
                     "R = R\nsys.path.insert(0, str(R))\n"):
            r = dirs(body)
            self.assertEqual((r["calls"], r["dirs"], r["unresolved"], r["leaves_root"]), (1, [], 1, 0), body)

    def test_not_counted(self):
        for body in ("import sys as s\ns.path.insert(0, os.path.dirname(__file__))\n",
                     "sys.path[0:0] = [os.path.dirname(__file__)]\n",
                     "code = 'sys.path.insert(0, x)'\n"):
            self.assertEqual(dirs(body)["calls"], 0, body)

    def test_a_parsed_source_reads_its_bindings_only_with_an_insertion_call(self):
        import ast
        with_call = HEAD + "R = Path(__file__).parent\nsys.path.insert(0, str(R / 'x'))\n"
        without = HEAD + "R = Path(__file__).parent\nprint(sys.path, R)\n"
        self.assertEqual(P.tree_insertions(ast.parse(with_call), FILE), P.insertions(with_call, FILE))
        self.assertEqual(P.tree_insertions(ast.parse(with_call), FILE)["dirs"], ["a/b/x"])
        built = []
        real = P._Reader

        class Counted(real):
            def __init__(self, tree, rel):
                built.append(rel)
                super().__init__(tree, rel)
        P._Reader = Counted
        try:
            self.assertEqual(P.tree_insertions(ast.parse(without), FILE),
                             {"calls": 0, "dirs": [], "unresolved": 0, "leaves_root": 0})
            self.assertEqual(built, [])
            P.tree_insertions(ast.parse(with_call), FILE)
            self.assertEqual(built, [FILE])
        finally:
            P._Reader = real

    def test_a_source_that_does_not_parse(self):
        with self.assertRaises(SyntaxError):
            P.insertions("def (:\n", FILE)


if __name__ == "__main__":
    unittest.main()
