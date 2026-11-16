"""``cli.run``, the one process boundary of every referee command (run with test 38: a fault must never read as
a verdict, and ``gate.secrets``' exit 1 is "match").

- Boundary: each rule of ``cli``'s docstring in-process, with fake ``main`` functions: a verdict line written
  before a fault is dropped (rule 1); a return that is not 0, 1 or 2 (``True``, ``None``, 3, "1") is a fault
  (rule 2); an exception and ``SystemExit`` are faults, ``KeyboardInterrupt`` is not caught (rule 3); stderr names
  the type and never the message (rule 5); the fault line is a dict or a function of argv, and a failing
  function gives ``GENERIC_LINE``.
- Register: the commands are found by scanning ``referee/`` for a ``__main__`` block (not a hand-kept list); each
  block is exactly ``sys.exit(cli.run(main, sys.argv[1:], FAULT_LINE))``, and each module's ``FAULT_LINE`` gives a
  JSON object for every first argument its usage names and for none.
- Handlers (rule 6): every catch-all handler in every source file re-raises or reports through
  ``cli.internal_error`` (only ``target.write`` reports); the register is shown red on eleven ways a handler can
  leak a message or swallow a fault, and green on the allowed shapes.
- Causes (rule 7): every use of a caught exception in every source file is ``cli.cause``, ``cli.internal_error``,
  ``raise ... from`` or a kept attribute (the register is shown red on fifteen ways a message can leak and green on
  the allowed shapes); ``CauseOf`` gives ``cli.cause``'s text for referee and other exceptions, the mark never in
  the latter; ``Injected`` runs every command in-process with ``json.loads`` or ``open`` raising a builtin exception
  that carries the mark (228 runs reach a patched read, measured) and finds no mark in any output, while the same
  runs with ``cli.cause`` replaced by ``str`` leak it in 139 runs of 19 commands.
- Names (tohum/26e, spec-011): no module or package of ``referee/`` or ``tests/`` is named like a standard module
  but the frozen table's ``profile``; the scan is shown to find a shadowing module and package; no source imports
  ``cProfile``.
- Process: every command, started the way the referee starts it, exits 2 when stdout is closed or a broken pipe
  (before this boundary: 20 of 22 exited 1 with stdout closed, and most 120 on a broken pipe); and ``gate.secrets
  scan`` on a clean file and on a file with a fake token exits 0 and 1 with a working stdout and 2 with either
  broken stdout, so the exit carries the verdict only when the verdict line reached its reader.
"""

from __future__ import annotations

import ast
import contextlib
import importlib
import io
import json
import os
import random
import subprocess
import sys
import tempfile
import time
import unittest

REFEREE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REFEREE)

import cli  # noqa: E402

ENTRY = "sys.exit(cli.run(main, sys.argv[1:], FAULT_LINE))"
MARK = "MESSAGE-" + "TEXT-OF-THE-INPUT"  # an exception message that must reach no output (used by module tests too)


def commands() -> dict[str, str]:
    """Module name -> path of every file under referee/ (tests excluded) with a ``__main__`` block."""
    found = {}
    for top, dirs, files in os.walk(REFEREE):
        dirs[:] = sorted(d for d in dirs if d not in ("tests", "__pycache__"))
        for name in sorted(files):
            if not name.endswith(".py"):
                continue
            path = os.path.join(top, name)
            with open(path, encoding="utf-8") as fh:
                tree = ast.parse(fh.read())
            if any(_is_main_block(node) for node in tree.body):
                rel = os.path.relpath(path, REFEREE)[:-3]
                found[rel.replace(os.sep, ".")] = path
    return found


def _is_main_block(node: ast.stmt) -> bool:
    return (isinstance(node, ast.If) and isinstance(node.test, ast.Compare)
            and isinstance(node.test.left, ast.Name) and node.test.left.id == "__name__")


def entry(path: str) -> list[list[str]]:
    """The statements of each ``__main__`` block of ``path``, unparsed."""
    with open(path, encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    return [[ast.unparse(stmt) for stmt in node.body] for node in tree.body if _is_main_block(node)]


def run_boundary(main, argv=(), fault_line=None):
    """``cli.run`` in-process with stdout and stderr captured: (exit, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli.run(main, list(argv), {"ok": False} if fault_line is None else fault_line)
    return code, out.getvalue(), err.getvalue()


def sources() -> dict[str, str]:
    """Relative path -> source of every .py file under referee/, tests and ``cli.py`` (the boundary) excluded."""
    found = {}
    for top, dirs, files in os.walk(REFEREE):
        dirs[:] = sorted(d for d in dirs if d not in ("tests", "__pycache__"))
        for name in sorted(files):
            path = os.path.join(top, name)
            rel = os.path.relpath(path, REFEREE)
            if name.endswith(".py") and rel != "cli.py":
                with open(path, encoding="utf-8") as fh:
                    found[rel] = fh.read()
    return found


CATCH_ALL = ("Exception", "BaseException")


def _catches_all(handler: ast.ExceptHandler) -> bool:
    """A bare ``except:``, or one naming ``Exception`` or ``BaseException`` (alone, dotted, or in a tuple)."""
    kinds = handler.type.elts if isinstance(handler.type, ast.Tuple) else [handler.type]
    return any(k is None or (isinstance(k, ast.Name) and k.id in CATCH_ALL)
               or (isinstance(k, ast.Attribute) and k.attr in CATCH_ALL) for k in kinds)


def _is_internal_error(node: ast.AST, name: str) -> bool:
    return (isinstance(node, ast.Call) and ast.unparse(node.func) == "cli.internal_error" and not node.keywords
            and len(node.args) == 1 and isinstance(node.args[0], ast.Name) and node.args[0].id == name)


def catch_all_faults(source: str) -> list[str]:
    """cli's rule 6 over one module: each handler that catches every exception either ends with a bare ``raise``
    or reports through ``cli.internal_error(<its name>)``; its bound name is used nowhere else, and it reaches
    neither ``traceback`` nor ``exc_info``. Returns ``line: reason`` for each handler that breaks it."""
    faults = []
    for handler in ast.walk(ast.parse(source)):
        if not isinstance(handler, ast.ExceptHandler) or not _catches_all(handler):
            continue
        body = ast.Module(body=handler.body, type_ignores=[])
        nodes = list(ast.walk(body))
        reported = [n for n in nodes if handler.name and _is_internal_error(n, handler.name)]
        allowed = {id(n.args[0]) for n in reported}
        if handler.name and any(isinstance(n, ast.Name) and n.id == handler.name and id(n) not in allowed
                                for n in nodes):
            faults.append("%d: the exception is used outside cli.internal_error" % handler.lineno)
        if any((isinstance(n, ast.Name) and n.id == "traceback") or (isinstance(n, ast.Attribute)
               and n.attr in ("exc_info", "format_exc", "print_exc", "exception")) for n in nodes):
            faults.append("%d: the handler reads the traceback or the active exception" % handler.lineno)
        reraises = isinstance(handler.body[-1], ast.Raise) and handler.body[-1].exc is None
        if not reraises and not reported:
            faults.append("%d: neither re-raised nor reported through cli.internal_error" % handler.lineno)
    return faults


ACTIVE_READS = ("exc_info", "format_exc", "print_exc", "print_exception", "format_exception", "__context__",
                "__cause__", "__traceback__")


def _allowed_use(node: ast.Name, parents: dict) -> bool:
    """Rule 7's allowed uses of a caught exception's name: ``cli.cause(exc)``, ``cli.internal_error(exc)``,
    ``raise ... from exc``, ``exc.<a KEPT_ATTRIBUTES name>`` and ``type(exc).__name__``."""
    parent = parents[node]
    if isinstance(parent, ast.Call) and parent.args == [node] and not parent.keywords:
        called = ast.unparse(parent.func)
        if called in ("cli.cause", "cli.internal_error"):
            return True
        return called == "type" and isinstance(parents[parent], ast.Attribute) and parents[parent].attr == "__name__"
    if isinstance(parent, ast.Raise) and parent.cause is node:
        return True
    return isinstance(parent, ast.Attribute) and parent.value is node and parent.attr in cli.KEPT_ATTRIBUTES


def caught_uses(source: str) -> list[str]:
    """cli's rule 7 over one module: every load of a name bound by ``except ... as name`` is an allowed use
    (``_allowed_use``), and nothing reads ``traceback`` or the active exception. Returns ``line: reason``."""
    tree = ast.parse(source)
    parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
    faults = []
    for handler in ast.walk(tree):
        if not isinstance(handler, ast.ExceptHandler) or not handler.name:
            continue
        for node in ast.walk(ast.Module(body=handler.body, type_ignores=[])):
            if (isinstance(node, ast.Name) and node.id == handler.name and isinstance(node.ctx, ast.Load)
                    and not _allowed_use(node, parents)):
                faults.append("%d: %s uses the caught exception" % (node.lineno, ast.unparse(parents[node])))
    for node in ast.walk(tree):
        if ((isinstance(node, ast.Name) and node.id == "traceback")
                or (isinstance(node, ast.alias) and node.name.split(".")[0] == "traceback")
                or (isinstance(node, ast.Attribute) and node.attr in ACTIVE_READS)):
            faults.append("%d: reads the traceback or the active exception" % node.lineno)
    return faults


def json_parses(source: str) -> list[str]:
    """cli's rule 8 over one module: no call ``json.load(...)`` or ``json.loads(...)``, no ``from json import``
    of either, no ``json`` imported under another name. Returns ``line: reason``. Out of scope, stated: a parser
    reached by a name built at run time (``getattr(json, name)``)."""
    faults = []
    for node in ast.walk(ast.parse(source)):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in ("load", "loads")
                and isinstance(node.func.value, ast.Name) and node.func.value.id == "json"):
            faults.append("%d: json.%s, not cli.%s" % (node.lineno, node.func.attr, node.func.attr))
        elif isinstance(node, ast.ImportFrom) and node.module == "json":
            faults.append("%d: from json import" % node.lineno)
        elif isinstance(node, ast.Import) and any(a.name == "json" and a.asname for a in node.names):
            faults.append("%d: json imported under another name" % node.lineno)
    return faults


def recursive_functions(source: str) -> list[str]:
    """Every function in ``source`` that calls itself by its own name (``name(...)``, or ``self.name(...)`` and
    ``cls.name(...)`` in a method): ``<function>`` at module level, ``<outer>.<function>`` nested."""
    found = []

    def visit(node: ast.AST, prefix: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                name = prefix + child.name
                for call in ast.walk(child):
                    if isinstance(call, ast.Call) and (
                            (isinstance(call.func, ast.Name) and call.func.id == child.name)
                            or (isinstance(call.func, ast.Attribute) and call.func.attr == child.name
                                and isinstance(call.func.value, ast.Name) and call.func.value.id in ("self", "cls"))):
                        found.append(name)
                        break
                visit(child, name + ".")
            elif isinstance(child, ast.ClassDef):
                visit(child, prefix + child.name + ".")
            else:
                visit(child, prefix)
    visit(ast.parse(source), "")
    return found


def start(module: str, argv: list[str], stdout: str) -> subprocess.CompletedProcess:
    """Run ``python -m module argv`` from referee/ with stdin empty and stdout 'closed', 'broken' (a pipe whose
    reader is gone) or 'pipe' (read normally)."""
    cmd = [sys.executable, "-m", module, *argv]
    common = dict(cwd=REFEREE, stdin=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=120)
    if stdout == "pipe":
        return subprocess.run(cmd, stdout=subprocess.PIPE, **common)
    if stdout == "closed":
        return subprocess.run(cmd, preexec_fn=lambda: os.close(1), **common)
    read, write = os.pipe()
    os.close(read)
    try:
        return subprocess.run(cmd, stdout=write, **common)
    finally:
        os.close(write)


def shadowing(*roots: str) -> set[str]:
    """The names on ``sys.path`` ahead of the standard library (each root's packages and ``.py`` modules) that are
    names of standard modules (``sys.stdlib_module_names``, tohum/26e)."""
    found = set()
    for root in roots:
        for name in os.listdir(root):
            path = os.path.join(root, name)
            if name.endswith(".py"):
                found.add(name[:-3])
            elif os.path.isdir(path) and os.path.isfile(os.path.join(path, "__init__.py")):
                found.add(name)
    return found & set(sys.stdlib_module_names)


class Names(unittest.TestCase):
    """tohum/26e: a referee command runs with ``referee/`` first on ``sys.path`` (and a test with ``tests/`` too), so
    a module named like a standard one hides it (spec-011: ``profile`` breaks ``import cProfile``). The one such
    name is the frozen stage 0 table's ``profile`` (MF4, MF6), kept until that table is reopened; no other."""

    def test_no_module_but_the_frozen_profile_shadows_a_standard_one(self):
        self.assertEqual(shadowing(REFEREE, os.path.join(REFEREE, "tests")), {"profile"})

    def test_the_scan_finds_a_shadowing_module_and_package(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, "json"))
            for rel in ("json/__init__.py", "random.py", "mine.py", "data.txt"):
                with open(os.path.join(tmp, rel), "w", encoding="utf-8") as fh:
                    fh.write("")
            os.makedirs(os.path.join(tmp, "email"))  # a directory without __init__.py is no package here
            self.assertEqual(shadowing(tmp), {"json", "random"})

    def test_no_referee_source_imports_cprofile(self):
        """26e's answer: no referee command calls ``cProfile``, which the ``profile`` package breaks."""
        users = [path for path, source in sources().items()
                 if any(isinstance(node, (ast.Import, ast.ImportFrom)) and "cProfile" in
                        ([a.name for a in node.names] + [getattr(node, "module", None) or ""])
                        for node in ast.walk(ast.parse(source)))]
        self.assertEqual(users, [])


class Boundary(unittest.TestCase):
    def test_a_good_main_passes_its_code_and_output_through(self):
        for code in (0, 1, 2):
            def main(argv, code=code):
                sys.stdout.write('{"v": %d}\n' % code)
                return code
            self.assertEqual(run_boundary(main), (code, '{"v": %d}\n' % code, ""))

    def test_a_verdict_line_written_before_a_fault_is_dropped(self):
        def main(argv):
            sys.stdout.write('{"clean": true}\n')
            raise ValueError("late")
        code, out, err = run_boundary(main, fault_line={"clean": False})
        self.assertEqual((code, out), (2, '{"clean": false}\n'))
        self.assertEqual(err, "internal error: ValueError\n")

    def test_a_return_that_is_not_0_1_or_2_is_a_fault(self):
        for bad in (True, False, None, 3, -1, "1", 1.0):
            code, out, err = run_boundary(lambda argv, bad=bad: bad)
            self.assertEqual((code, out), (2, '{"ok": false}\n'), bad)
            self.assertEqual(err, "internal error: exit %r\n" % (bad,))

    def test_exceptions_and_system_exit_are_faults(self):
        def recurse(argv):
            return recurse(argv)
        cases = [(recurse, "RecursionError"), (lambda argv: {}["k"], "KeyError"),
                 (lambda argv: sys.exit(1), "SystemExit"), (lambda argv: sys.exit(0), "SystemExit")]
        for main, name in cases:
            code, out, err = run_boundary(main)
            self.assertEqual((code, out, err), (2, '{"ok": false}\n', "internal error: %s\n" % name))

    def test_keyboard_interrupt_is_not_caught(self):
        def main(argv):
            raise KeyboardInterrupt
        with self.assertRaises(KeyboardInterrupt):
            run_boundary(main)

    def test_stderr_names_the_type_never_the_message(self):
        def main(argv):
            raise RuntimeError(MARK)
        code, out, err = run_boundary(main)
        self.assertEqual(code, 2)
        self.assertNotIn(MARK, out + err)
        self.assertEqual(err, "internal error: RuntimeError\n")

    def test_the_fault_line_is_a_function_of_argv_and_a_failing_one_gives_the_generic_line(self):
        def main(argv):
            raise ValueError
        self.assertEqual(run_boundary(main, ["decide", "x"], lambda argv: {"first": argv[0]})[1], '{"first": "decide"}\n')
        self.assertEqual(run_boundary(main, [], lambda argv: {"first": argv[0]})[1],
                         json.dumps(cli.GENERIC_LINE, sort_keys=True) + "\n")

    def test_a_stdout_that_fails_after_main_returned_is_a_fault(self):
        class Broken(io.StringIO):
            def write(self, text):
                raise BrokenPipeError
        err = io.StringIO()
        with contextlib.redirect_stdout(Broken()), contextlib.redirect_stderr(err):
            code = cli.run(lambda argv: 0, [], {"ok": False})
        self.assertEqual((code, err.getvalue()), (2, "internal error: stdout\n"))


class Register(unittest.TestCase):
    def test_every_command_enters_through_the_boundary(self):
        found = commands()
        self.assertGreaterEqual(len(found), 22, sorted(found))
        for module, path in found.items():
            self.assertEqual(entry(path), [[ENTRY]], module)

    def test_the_register_sees_a_command_that_bypasses_the_boundary(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "bypass.py")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write('import sys\n\ndef main(argv):\n    return 0\n\nif __name__ == "__main__":\n'
                         '    sys.exit(main(sys.argv[1:]))\n')
            self.assertEqual(entry(path), [["sys.exit(main(sys.argv[1:]))"]])
            self.assertNotEqual(entry(path), [[ENTRY]])

    def test_no_module_handler_writes_an_exception_message(self):
        found = sources()
        self.assertLessEqual({os.path.relpath(p, REFEREE) for p in commands().values()}, set(found))
        self.assertGreaterEqual(len(found), 37, sorted(found))
        faults = {path: catch_all_faults(src) for path, src in found.items()}
        self.assertEqual({p: f for p, f in faults.items() if f}, {})
        kept = sorted(p for p, src in found.items() if "cli.internal_error(" in src)
        self.assertEqual(kept, [os.path.join("target", "write.py")])

    def test_the_handler_register_sees_each_way_to_leak_or_swallow(self):
        head = "import cli, sys, traceback\ndef f():\n    try:\n        g()\n"
        bad = {
            "message in a format": "    except Exception as exc:\n        print('internal error: %s' % exc)\n",
            "str of it": "    except Exception as exc:\n        e = str(exc)\n        print(cli.internal_error(exc), e)\n",
            "its args": "    except BaseException as exc:\n        print(exc.args)\n        raise\n",
            "in a tuple": "    except (ValueError, Exception) as exc:\n        return repr(exc)\n",
            "dotted": "    except builtins.Exception as exc:\n        return f'{exc}'\n",
            "bare, swallowed": "    except:\n        pass\n",
            "unnamed, swallowed": "    except Exception:\n        return 1\n",
            "traceback": "    except Exception as exc:\n        traceback.print_exc()\n        print(cli.internal_error(exc))\n",
            "exc_info": "    except Exception:\n        print(sys.exc_info())\n        raise\n",
            "a raise with a new exception": "    except Exception as exc:\n        raise RuntimeError(exc)\n",
            "internal_error of another value": "    except Exception as exc:\n        print(cli.internal_error(exc.__cause__))\n",
        }
        for why, handler in bad.items():
            self.assertNotEqual(catch_all_faults(head + handler), [], why)
        good = {
            "cleanup and re-raise": "    except BaseException:\n        cleanup()\n        raise\n",
            "bare re-raise": "    except:\n        raise\n",
            "reported": "    except Exception as exc:\n        cause = cli.internal_error(exc)\n        print(cause)\n",
            "a narrower handler is not this rule's": "    except ValueError as exc:\n        print(exc)\n",
        }
        for why, handler in good.items():
            self.assertEqual(catch_all_faults(head + handler), [], why)

    def test_every_caught_exception_reaches_output_only_through_cause(self):
        found = sources()
        self.assertGreaterEqual(len(found), 37, sorted(found))
        faults = {path: caught_uses(src) for path, src in found.items()}
        self.assertEqual({p: f for p, f in faults.items() if f}, {})
        users = sorted(p for p, src in found.items() if "cli.cause(" in src)
        self.assertGreaterEqual(len(users), 22, users)

    def test_the_cause_register_sees_each_way_a_message_can_leak(self):
        head = "import cli, sys\nimport traceback as tb\ndef f():\n    try:\n        g()\n"
        bad = {
            "in a format": "    except ValueError as exc:\n        print('unusable input: %s' % exc)\n",
            "in a tuple of a format": "    except OSError as exc:\n        raise U('%s: %s' % (p, exc)) from None\n",
            "str of it": "    except KeyError as exc:\n        return str(exc)\n",
            "an f-string": "    except ValueError as exc:\n        return f'{exc}'\n",
            "its args": "    except ValueError as exc:\n        return exc.args[0]\n",
            "its filename": "    except OSError as exc:\n        return exc.filename\n",
            "its object": "    except UnicodeDecodeError as exc:\n        return exc.object\n",
            "a new exception of it": "    except ValueError as exc:\n        raise U(exc)\n",
            "kept for later": "    except ValueError as exc:\n        saved = exc\n",
            "cause of something else": "    except ValueError as exc:\n        return cli.cause(exc.__context__)\n",
            "a keyword to cause": "    except ValueError as exc:\n        return cli.cause(exc=exc)\n",
            "type, not its name": "    except ValueError as exc:\n        return type(exc)\n",
            "nested handler": "    except ValueError as exc:\n        try:\n            h()\n        except OSError as err:\n"
                              "            print(err, cli.cause(exc))\n",
            "a traceback module alias": "    except ValueError:\n        tb.print_exc()\n        raise\n",
            "exc_info": "    except ValueError:\n        print(sys.exc_info()[1])\n        raise\n",
        }
        for why, handler in bad.items():
            self.assertNotEqual(caught_uses(head + handler), [], why)
        good = {
            "cause": "    except ValueError as exc:\n        print('unusable input: %s' % cli.cause(exc))\n",
            "chained": "    except ValueError as exc:\n        raise U(cli.cause(exc)) from exc\n",
            "internal_error": "    except Exception as exc:\n        print(cli.internal_error(exc))\n",
            "reason codes and status": "    except E as exc:\n        return exc.reasons, exc.status, exc.code\n",
            "the type's name": "    except E as exc:\n        return '%s: %s' % (type(exc).__name__, cli.cause(exc))\n",
            "unnamed": "    except ValueError:\n        return 2\n",
        }
        for why, handler in good.items():
            self.assertEqual(caught_uses(head.replace("import traceback as tb\n", "") + handler), [], why)

    def test_no_module_parses_json_but_through_cli(self):
        found = sources()
        self.assertGreaterEqual(len(found), 37, sorted(found))
        self.assertEqual({p: f for p, f in ((p, json_parses(src)) for p, src in found.items()) if f}, {})
        users = sorted(p for p, src in found.items() if "cli.loads(" in src or "cli.load(" in src)
        self.assertGreaterEqual(len(users), 27, users)

    def test_the_parse_register_sees_each_way_to_reach_the_parser(self):
        bad = {"loads": "import json\nx = json.loads(t)\n", "load": "import json\nx = json.load(f)\n",
               "from import": "from json import loads\n", "from import of another": "from json import decoder\n",
               "an alias": "import json as j\n"}
        for why, src in bad.items():
            self.assertNotEqual(json_parses(src), [], why)
        good = {"cli": "import cli\nx = cli.loads(t)\ny = cli.load(f)\n", "dumps": "import json\nx = json.dumps(v)\n",
                "another module's loads": "import pickle\nx = pickle.loads(b)\n"}
        for why, src in good.items():
            self.assertEqual(json_parses(src), [], why)

    def test_every_fault_line_is_a_json_object_for_any_argv(self):
        for module in commands():
            line = importlib.import_module(module).FAULT_LINE
            for argv in ([], ["argv"], ["check"], ["decide"], ["judge", "a", "b"], ["commit", "a", "b"], ["verify"],
                         ["root"], ["scan"], ["run", "x"]):
                got = line(argv) if callable(line) else line
                self.assertIsInstance(got, dict, (module, argv))
                self.assertEqual(json.loads(json.dumps(got)), got, (module, argv))


class LoadsDepth(unittest.TestCase):
    """Rule 8: ``cli.loads`` and ``cli.load`` are ``json``'s, but the parser's depth failure is ``TooDeep``."""

    DEEP = "[" * 200000  # deeper than the decoder goes (it raises RecursionError, measured on python 3.12)

    def test_the_parser_alone_raises_a_recursion_error_no_value_error_names(self):
        # the defect rule 8 closes: a handler naming ValueError does not see it
        with self.assertRaises(RecursionError) as caught:
            json.loads(self.DEEP)
        self.assertNotIsInstance(caught.exception, ValueError)

    def test_too_deep_is_a_value_error_and_a_recursion_error(self):
        for parse in (lambda: cli.loads(self.DEEP), lambda: cli.loads(self.DEEP.encode()),
                      lambda: cli.load(io.StringIO(self.DEEP))):
            with self.assertRaises(cli.TooDeep) as caught:
                parse()
            self.assertIsInstance(caught.exception, ValueError)
            self.assertIsInstance(caught.exception, RecursionError)
            self.assertTrue(caught.exception.__suppress_context__)  # raised from None: no chained parser frames
            self.assertEqual(cli.cause(caught.exception), "JSON nested too deeply")

    def test_a_handler_written_either_way_catches_it(self):
        for kind in (ValueError, RecursionError):
            try:
                cli.loads(self.DEEP)
            except kind:
                pass

    def test_same_value_and_options_as_json(self):
        text = '{"a": [1, 2.5, "x", null, true], "b": {"c": NaN}}'
        self.assertEqual(json.dumps(cli.loads(text)), json.dumps(json.loads(text)))
        self.assertEqual(cli.load(io.StringIO(text), parse_float=str)["a"][1], "2.5")
        pairs = cli.loads('{"k": 1, "k": 2}', object_pairs_hook=list)
        self.assertEqual(pairs, [("k", 1), ("k", 2)])
        at_bound = "[" * cli.DEPTH + "]" * cli.DEPTH
        self.assertEqual(cli.loads(at_bound), json.loads(at_bound))

    def test_parsed_but_deeper_than_the_bound_is_too_deep(self):
        n = cli.DEPTH
        shapes = [lambda k: "[" * k + "]" * k,
                  lambda k: '{"a":' * k + "1" + "}" * k,
                  lambda k: "[" * (k // 2) + '{"a":' * (k - k // 2) + "null" + "}" * (k - k // 2) + "]" * (k // 2)]
        for shape in shapes:
            self.assertEqual(cli.loads(shape(n)), json.loads(shape(n)))
            for text in (shape(n + 1), shape(3000)):  # 3000: the parser alone returns it (python 3.12)
                json.loads(text)
                for parse in (lambda: cli.loads(text), lambda: cli.loads(text.encode()),
                              lambda: cli.load(io.StringIO(text)), lambda: cli.loads(text, object_pairs_hook=list)):
                    with self.assertRaises(cli.TooDeep) as caught:
                        parse()
                    self.assertIsInstance(caught.exception, ValueError)
                    self.assertIsInstance(caught.exception, RecursionError)
                    self.assertEqual(cli.cause(caught.exception), "JSON nested too deeply")

    def test_depth_counts_brackets_outside_strings_only(self):
        for text, want in [("1", 0), ('"x"', 0), ("[]", 1), ("{}", 1), ("[[], [[]]]", 3), ('{"a": [1, {"b": 2}]}', 3),
                           ('"[[[{{{"', 0), ('["\\"[", "]"]', 1), ('{"[": "{", "k": ["\\\\", "["]}', 2),
                           ('["\\u005b"]', 1)]:
            self.assertEqual(cli.depth(text), want, text)
        string = json.dumps("[{" * 200 + '\\"')  # brackets, a backslash and a quote inside one string
        at = "[" * (cli.DEPTH - 1) + string + "]" * (cli.DEPTH - 1)
        self.assertEqual(cli.loads(at), json.loads(at))

    def test_bytes_are_counted_as_the_parser_decoded_them(self):
        n = cli.DEPTH
        for encoding in ("utf-8", "utf-16-le", "utf-16-be", "utf-32-le"):
            ok = ("[" * n + '"\u00e9"' + "]" * n).encode(encoding)
            self.assertEqual(cli.loads(ok), json.loads(ok), encoding)
            with self.assertRaises(cli.TooDeep):
                cli.loads(("[" * (n + 1) + "]" * (n + 1)).encode(encoding))

    def test_a_hook_does_not_change_the_count(self):
        n = cli.DEPTH
        text = '{"a":' * n + "1" + "}" * n
        self.assertEqual(cli.loads(text, object_pairs_hook=list), json.loads(text, object_pairs_hook=list))
        with self.assertRaises(cli.TooDeep):
            cli.loads('{"a":' * (n + 1) + "1" + "}" * (n + 1), object_pairs_hook=lambda pairs: 0)

    def test_other_failures_are_unchanged(self):
        with self.assertRaises(json.JSONDecodeError):
            cli.loads("{")
        with self.assertRaises(UnicodeDecodeError):
            cli.loads(b"\xff")

        class Mine(Exception):
            pass

        def hook(pairs):
            raise Mine()
        with self.assertRaises(Mine):
            cli.loads("{}", object_pairs_hook=hook)

    @staticmethod
    def nesting(value) -> int:
        """The depth of a parsed value, by an explicit stack (the reference ``cli.depth`` is checked against)."""
        deepest, stack = 0, [(value, 0)]
        while stack:
            item, level = stack.pop()
            if isinstance(item, (list, dict)):
                deepest = max(deepest, level + 1)
                stack.extend((child, level + 1) for child in (item.values() if isinstance(item, dict) else item))
        return deepest

    def test_depth_equals_the_parsed_values_depth_for_generated_json(self):
        # strings drawn from the characters that end, escape or look like structure, so every escape shape occurs:
        # runs of backslashes of each parity, an escaped quote after them, brackets and quotes in keys and values
        rng = random.Random(8)
        alphabet = ['"', "\\", "[", "]", "{", "}", "u", "x", "\n", "\u00e9", "/", ":", ","]

        def string():
            return "".join(rng.choice(alphabet) for _ in range(rng.randrange(0, 12)))

        def value(level):
            pick = rng.randrange(6 if level < 12 else 3)
            if pick == 0:
                return string()
            if pick == 1:
                return rng.choice([0, -1.5, True, None])
            if pick == 2:
                return "\\" * rng.randrange(1, 6) + rng.choice(['"', "[", "", "\\"])
            if pick == 3:
                return [value(level + 1) for _ in range(rng.randrange(0, 4))]
            return {string(): value(level + 1) for _ in range(rng.randrange(0, 4))}

        for case in range(3000):
            item = value(0)
            for text in (json.dumps(item), json.dumps(item, ensure_ascii=False, indent=case % 3 or None)):
                self.assertEqual(cli.depth(text), self.nesting(json.loads(text)), text)

    def test_depth_costs_a_few_parses_on_string_heavy_text(self):
        # f873: the former regular expression took 16 to 100 times json.loads on these shapes; the bound is 8 times
        # (best of five each, so both sides see the same machine load)
        def best(run):
            times = []
            for _ in range(5):
                start = time.perf_counter()
                run()
                times.append(time.perf_counter() - start)
            return min(times)

        shapes = {"one long string": json.dumps(["x" * 2_000_000]),
                  "escaped quotes": json.dumps(['"' * 1_000_000]),
                  "backslashes": json.dumps(["\\" * 1_000_001 + '"'])}
        for name, text in shapes.items():
            ratio = best(lambda: cli.depth(text)) / best(lambda: json.loads(text))
            self.assertLess(ratio, 8, name)


class Walks(unittest.TestCase):
    """Rule 8's bound against the walks it is for: every function in a referee source that calls itself by name
    (``recursive_functions``; the register is checked equal to ``WALKS``, so a new one is red until it is run
    here) runs over a value ``cli.loads`` returned at ``DEPTH`` with ``HEADROOM`` frames already on the stack, and
    returns without ``RecursionError``."""

    HEADROOM = 150  # frames held above the walk: a margin for a command's own call depth, not a measurement of it

    @staticmethod
    def deep_object(key: str = "a", leaf: str = '"v"') -> dict:
        return cli.loads(('{"%s":' % key) * cli.DEPTH + leaf + "}" * cli.DEPTH)

    def walk_canon(self):
        from ledger import chain
        chain.canonical(self.deep_object())

    def walk_no_float(self):
        from ledger import schema
        self.assertEqual(schema.no_float(cli.loads("[" * cli.DEPTH + "1" + "]" * cli.DEPTH), "v"), [])

    def walk_leaves(self):
        from status import depmap
        out: list = []
        depmap._leaves(self.deep_object(leaf='"b"'), self.deep_object(leaf='"h"'), [], out)
        self.assertEqual(len(out[0]["path"]), cli.DEPTH)

    def walk_emit(self):
        from loop import job
        out: list = []
        job._emit(self.deep_object(), 0, out)
        self.assertEqual(len(out), cli.DEPTH)

    def walk_secrets(self):
        from gate import secrets
        token = "gh" + "p_" + "A1b2C3d4" * 4 + "E5f6"  # a token's format, built here (no such string in a diff)
        row = '{"a":' * (cli.DEPTH - 1) + json.dumps([token]) + "}" * (cli.DEPTH - 1) + "\n"
        self.assertEqual(secrets.match_lines(row.encode(), "row"), [1])  # _strings reached the deepest string
        clean = '{"a":' * (cli.DEPTH - 1) + "[1]" + "}" * (cli.DEPTH - 1) + "\n"
        self.assertEqual(secrets.match_lines(clean.encode(), "row"), [])  # _secret_members walked it all

    def walk_resolved(self):
        from profile import nx
        from test_profile_nx import LINT, Base as NxBase
        from profile_tree import write_tree
        case = NxBase()
        case.setUp()
        try:
            patterns = "[" * (cli.DEPTH - 4) + '"x"' + "]" * (cli.DEPTH - 4)  # 4: project.json's own levels
            write_tree(case.tree, {"libs/a/project.json": '{"targets": {"lint": {"executor": "%s", "options": '
                                   '{"lintFilePatterns": %s}}}}' % (LINT["executor"], patterns)})
            with self.assertRaises(nx.NotComposed) as caught:
                nx.lint(case.tree, "libs/a")
            self.assertEqual(caught.exception.reasons, ["option:lintFilePatterns"])
        finally:
            case.doCleanups()

    WALKS = {"ledger/chain.py": {"_canon": walk_canon},
             "ledger/schema.py": {"no_float": walk_no_float},
             "status/depmap.py": {"_leaves": walk_leaves},
             "loop/job.py": {"_emit": walk_emit},
             "gate/secrets.py": {"_strings": walk_secrets, "_secret_members": walk_secrets},
             "profile/nx.py": {"target.resolved": walk_resolved}}

    def test_the_register_is_every_self_calling_function(self):
        found = {p: set(f) for p, f in ((p, recursive_functions(src)) for p, src in sources().items()) if f}
        self.assertEqual(found, {p: set(w) for p, w in self.WALKS.items()})

    def test_the_register_finds_a_self_call(self):
        src = ("def f(x):\n    return [f(y) for y in x]\n\ndef g(x):\n    def h(y):\n        return h(y)\n"
               "    return x\n\nclass C:\n    def m(self, x):\n        return self.m(x)\n"
               "    def n(self, x):\n        return other.n(x)\n")
        self.assertEqual(recursive_functions(src), ["f", "g.h", "C.m"])

    def test_every_walk_takes_a_value_at_the_bound(self):
        for path, walks in self.WALKS.items():
            for name, walk in walks.items():
                with self.subTest(walk="%s:%s" % (path, name)):
                    self.under_headroom(lambda: walk(self), self.HEADROOM)

    def under_headroom(self, fn, frames: int):
        if frames:
            return self.under_headroom(fn, frames - 1)
        return fn()


class CauseOf(unittest.TestCase):
    """``cli.cause``: a referee exception keeps its message; of any other, no character of the message."""

    def test_a_referee_exception_keeps_its_message(self):
        from gate import secrets
        from ledger import chain
        for exc in (chain.ChainError(MARK), secrets.ScanError(MARK), cli.Fault(MARK)):
            self.assertEqual(cli.cause(exc), MARK, type(exc))

    def test_an_exception_defined_outside_referee_gives_its_type(self):
        import importlib.util
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "elsewhere.py")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("class Unusable(ValueError):\n    pass\n")
            spec = importlib.util.spec_from_file_location("elsewhere", path)
            module = importlib.util.module_from_spec(spec)
            sys.modules["elsewhere"] = module
            try:
                spec.loader.exec_module(module)
                self.assertEqual(cli.cause(module.Unusable(MARK)), "Unusable")
            finally:
                del sys.modules["elsewhere"]

    def test_builtin_messages_never_reach_the_text(self):
        import errno
        import re
        import tarfile
        data = (MARK + "\xff").encode("latin-1")
        try:
            json.loads('{"' + MARK)
        except json.JSONDecodeError as exc:
            decoded = exc
        cases = [
            (ValueError(MARK), "ValueError"),
            (KeyError(MARK), "KeyError"),
            (TypeError(MARK), "TypeError"),
            (RecursionError(MARK), "RecursionError"),
            (OSError(MARK), "OSError"),
            (OSError(errno.ENOENT, os.strerror(errno.ENOENT), MARK), os.strerror(errno.ENOENT)),
            (FileNotFoundError(errno.ENOENT, os.strerror(errno.ENOENT), MARK, None, MARK), os.strerror(errno.ENOENT)),
            (decoded, "JSONDecodeError at line 1 column 2"),
            (json.JSONDecodeError("Invalid \\escape: %r" % MARK, MARK, 3), "JSONDecodeError at line 1 column 4"),
            (UnicodeDecodeError("utf-8", data, len(MARK), len(MARK) + 1, "invalid start byte"),
             "UnicodeDecodeError at position %d (utf-8)" % len(MARK)),
            (UnicodeEncodeError("ascii", MARK + "\u00e9", len(MARK), len(MARK) + 1, MARK),
             "UnicodeEncodeError at position %d (ascii)" % len(MARK)),
            (UnicodeError(MARK), "UnicodeError"),
            (tarfile.ReadError(MARK), "ReadError"),
            (re.error(MARK), "error"),
        ]
        for exc, text in cases:
            self.assertEqual(cli.cause(exc), text, repr(exc)[:80])
            self.assertNotIn(MARK, cli.cause(exc))

    def test_a_referee_exception_raised_under_python_m_keeps_its_message(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "rows.jsonl")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write('{"a": \n')
            proc = subprocess.run([sys.executable, "-m", "ledger.chain", "verify", path], cwd=REFEREE,
                                  capture_output=True, text=True, timeout=120)
        self.assertEqual(proc.returncode, 1, proc.stderr)
        self.assertEqual(json.loads(proc.stdout)["reason"], "not JSON: JSONDecodeError at line 1 column 7")


def _inject_argv(f: str, d: str) -> dict:
    """Argument lists that reach each command's reads (``f`` a file holding ``{}``, ``d`` a directory)."""
    return {
        "activate": [["genesis", f, f, f, f, f, f]],
        "dispatcher.llm_call": [["plan", f]],
        "gate.check": [["map", f, "a", "1"], ["decide", d, f, d, f]],
        "gate.diffguard": [["check", f, f, f]],
        "gate.revert": [["cause"]],
        "gate.secrets": [["scan", "diff", f], ["scan", "row", f], ["scan", "prompt", f], ["scan", "--kind", "diff", f]],
        "gate.sentinel": [["decide"]],
        "harness.revert_drill": [["commit", f, f], ["reveal", f, f], ["judge", f, f]],
        "harness.pass_row": [["judge", d, d, d, d, f, f], ["judge", d, d, d, d, f, f, f, f]],
        "ledger.anchor": [["root", f], ["anchor", f], ["verify", f, f, f]],
        "ledger.append": [["cycle", f, f]],
        "ledger.chain": [["hash"], ["verify", f], ["verify", f, "--previous", f]],
        "ledger.founder": [["check", "--ledger", f], ["open", "--ledger", f, "--reports", d]],
        "loop.job": [["run", f]],
        "loop.treehash": [["tar", f]],
        "profile.derive": [["derive", f, f], ["check", f, f, f]],
        "profile.fit": [[d, "--target", f], [d, "--policy", f], [d, "--images", f]],
        "profile.unit_verify": [["check", f, f], ["verify", f]],
        "runner.contained": [["argv", f], ["check", f], ["run", f]],
        "runner.deps_npm": [["check", f], ["fetch", f, d], ["verify", d]],
        "runner.kos": [["run", f]],
        "runner.lint_record": [[d]],
        "status.block": [["render", f, f, f]],
        "status.depmap": [["brain", d], ["check", d], ["coverage", d], ["target", d, "--source", "x"]],
        "status.exit_b": [["check"], ["register"]],
        "target.write": [["replay", f]],
    }


class Injected(unittest.TestCase):
    """Every command, in-process through ``cli.run``, with the reads every command uses (``json.loads``, which
    ``json.load`` calls, and ``open``) raising a builtin exception whose message, file name or object is the mark:
    the mark reaches neither stdout nor stderr. The same runs with ``cli.cause`` replaced by ``str`` leak it, so the
    test sees the class it guards."""

    INJECTED = {
        "ValueError": lambda: ValueError(MARK),
        "KeyError": lambda: KeyError(MARK),
        "OSError": lambda: OSError(5, "Input/output error", MARK),
        "UnicodeDecodeError": lambda: UnicodeDecodeError("utf-8", MARK.encode(), 0, 1, MARK),
    }

    def runs(self, cause=None) -> tuple[int, list[str]]:
        from unittest import mock
        reached, leaks = 0, []
        with tempfile.TemporaryDirectory() as tmp:
            f = os.path.join(tmp, "in.json")
            with open(f, "w", encoding="utf-8") as fh:
                fh.write("{}")
            table = _inject_argv(f, tmp)
            self.assertEqual(set(table), set(commands()))
            for module, argvs in sorted(table.items()):
                main = importlib.import_module(module).main
                line = importlib.import_module(module).FAULT_LINE
                for argv in argvs:
                    for kind, make in self.INJECTED.items():
                        for target in ("json.loads", "builtins.open", "io.open"):
                            patches = [mock.patch(target, side_effect=make()),
                                       mock.patch("sys.stdin", io.TextIOWrapper(io.BytesIO(b"{}")))]
                            if cause is not None:
                                patches.append(mock.patch.object(cli, "cause", cause))
                            with contextlib.ExitStack() as stack:
                                fakes = [stack.enter_context(p) for p in patches]
                                code, out, err = run_boundary(main, argv, line)
                            if fakes[0].called:
                                reached += 1
                            if MARK in out + err:
                                leaks.append("%s %s %s %s" % (module, argv[:1], kind, target))
                            self.assertIn(code, cli.EXITS)
        return reached, leaks

    def test_no_command_writes_an_injected_message(self):
        reached, leaks = self.runs()
        self.assertEqual(leaks, [])
        self.assertGreaterEqual(reached, 228)

    def test_the_same_runs_leak_when_cause_writes_the_message(self):
        reached, leaks = self.runs(cause=str)
        self.assertGreaterEqual(len(leaks), 139)
        self.assertGreaterEqual(len({leak.split()[0] for leak in leaks}), 19)


class Process(unittest.TestCase):
    def test_every_command_exits_2_when_stdout_is_closed_or_broken(self):
        for module in commands():
            for stdout in ("closed", "broken"):
                proc = start(module, [], stdout)
                self.assertEqual(proc.returncode, 2, (module, stdout, proc.stderr[-300:]))
                self.assertNotIn(b"Traceback", proc.stderr, (module, stdout))

    def test_secrets_verdicts_reach_the_reader_or_the_exit_is_2(self):
        token = "gh" + "p_" + "Q7" * 18
        with tempfile.TemporaryDirectory() as tmp:
            clean, dirty = os.path.join(tmp, "clean.diff"), os.path.join(tmp, "dirty.diff")
            with open(clean, "w", encoding="utf-8") as fh:
                fh.write("+nothing here\n")
            with open(dirty, "w", encoding="utf-8") as fh:
                fh.write("+x = '%s'\n" % token)
            for path, verdict, line in ((clean, 0, {"clean": True, "lines": []}), (dirty, 1, {"clean": False, "lines": [1]})):
                proc = start("gate.secrets", ["scan", "diff", path], "pipe")
                self.assertEqual((proc.returncode, json.loads(proc.stdout)), (verdict, line))
                for stdout in ("closed", "broken"):
                    proc = start("gate.secrets", ["scan", "diff", path], stdout)
                    self.assertEqual((proc.returncode, proc.stderr), (2, b"internal error: stdout\n"), (path, stdout))


if __name__ == "__main__":
    unittest.main()
