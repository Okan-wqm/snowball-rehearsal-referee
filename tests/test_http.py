"""``httpbody``'s rule: one read of an HTTPS answer's body and one list of a failed exchange's errors, for every reader.

- ``HttpBody``: ``httpbody.read`` over answers parsed by ``http.client.HTTPResponse`` itself (``http_wire``): a body
  that ended at or under the cap short of its ``Content-Length`` raises ``IncompleteRead`` with a cap as without
  one; every body of at most ``cap`` bytes gets the same result (bytes or the error's type) either way, over
  generated lengths and over a chunked answer cut at every byte; a body over the cap is its first ``cap + 1``
  bytes; a body with no length, and a stand-in without ``length``, are read and not judged.
- ``HttpSites``: each reader that names ``httpbody.ERRORS`` (``runner.deps_npm.https_once``, ``loop.accepted``'s
  ``json``, ``blob`` and ``redirect``, ``loop.rekor``'s ``entry``) gives its own answer for each failed exchange:
  a body short of its length, a chunked body cut inside a chunk, a status line that cannot be read, a connection
  closed before any answer, a refused connection, a timeout; ``target.write.HttpTransport``, which has no
  handler, raises the error as it is (the module's stated scope).
- ``Register``: over every source file, each response opened through an opener made by
  ``urllib.request.build_opener`` is found (six, in four modules); none is read by its own ``read``; each but
  ``target.write``'s is opened in a ``try`` with a handler naming ``httpbody.ERRORS``; no source's code
  names ``urlopen`` or an ``HTTPSConnection``, and ``build_opener`` is named only in full. The register is shown red on each way to leave the rule and green on the allowed shapes.
"""

from __future__ import annotations

import ast
import http.client
import io
import os
import random
import socket
import sys
import unittest
import urllib.error

REFEREE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REFEREE)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import httpbody  # noqa: E402
from loop import accepted as A  # noqa: E402
from loop import rekor as R  # noqa: E402
from runner import deps_npm as N  # noqa: E402
from target import write as W  # noqa: E402
from http_wire import Wire, _Sock, answer, chunked  # noqa: E402
from test_cli import sources  # noqa: E402

URL = "https://registry.example/x.tgz"


def response(raw: bytes) -> http.client.HTTPResponse:
    resp = http.client.HTTPResponse(_Sock(raw))
    resp.begin()
    return resp


def body(raw: bytes, cap: int | None):
    """``httpbody.read``'s bytes, or the type of what it raised."""
    try:
        return httpbody.read(response(raw), cap)
    except Exception as exc:  # noqa: BLE001 - the type is the result compared
        return type(exc)


class HttpBody(unittest.TestCase):
    def test_a_whole_body_is_read_with_and_without_a_cap(self):
        raw = answer(200, b"tarball")
        self.assertEqual([body(raw, cap) for cap in (None, 100, 8, 7)], [b"tarball"] * 4)
        self.assertEqual([body(answer(200), cap) for cap in (None, 0, 5)], [b""] * 3)

    def test_a_body_over_the_cap_is_its_first_cap_plus_one_bytes(self):
        self.assertEqual([body(answer(200, b"tarball"), cap) for cap in (6, 2, 0)], [b"tarball", b"tar", b"t"])
        # cut short too, but over the cap: the caller refuses it by its size, whether it was complete is not judged
        self.assertEqual(body(answer(200, b"tar", length=7), 2), b"tar")

    def test_a_body_short_of_its_length_raises_with_a_cap_as_without(self):
        short = answer(200, b"tar", length=7)
        for cap in (None, 100, 7, 6, 3):
            with self.subTest(cap=cap):
                with self.assertRaises(http.client.IncompleteRead) as caught:
                    httpbody.read(response(short), cap)
                self.assertEqual((caught.exception.partial, caught.exception.expected), (b"tar", 4))
        for cap in (None, 0, 9):  # no byte of the body arrived
            self.assertIs(body(answer(200, b"", length=7), cap), http.client.IncompleteRead, cap)

    def test_any_body_within_the_cap_is_judged_as_the_uncapped_read_judges_it(self):
        rng = random.Random(10)
        seen = set()
        for _ in range(300):
            sent, said = rng.randrange(0, 40), rng.randrange(0, 40)
            raw = answer(200, rng.randbytes(sent), length=said)
            free = body(raw, None)
            seen.add(free is http.client.IncompleteRead)
            # http.client reads no further than the length said: the body is min(sent, said) bytes, within each cap
            for cap in (min(sent, said), sent, said, max(sent, said) + rng.randrange(0, 5)):
                self.assertEqual(body(raw, cap), free, (sent, said, cap))
        self.assertEqual(seen, {True, False})

    def test_a_chunked_body_cut_at_any_byte_is_judged_the_same_either_way(self):
        whole = chunked(200, b"tar", b"ball")
        results = []
        for cut in range(len(whole) - whole.index(b"\r\n\r\n") - 4 + 1):
            free = body(chunked(200, b"tar", b"ball", cut=cut), None)
            results.append(free)
            for cap in (7, 8, 100):
                self.assertEqual(body(chunked(200, b"tar", b"ball", cut=cut), cap), free, (cut, cap))
        # the last-chunk's size read: whole; before it: the error (what follows that size is not looked at)
        self.assertEqual(results[:5], [b"tarball"] * 5)
        self.assertEqual(set(results[5:]), {http.client.IncompleteRead})
        self.assertEqual(body(chunked(200, b"tar", b"ball", cut=9), 2), b"tar")  # over the cap

    def test_a_body_with_no_length_and_a_stand_in_without_one_are_not_judged(self):
        self.assertEqual([body(b"HTTP/1.1 200 X\r\n\r\ntar", cap) for cap in (None, 100, 3)], [b"tar"] * 3)
        unread = b"HTTP/1.1 200 X\r\nContent-Length: seven\r\n\r\ntar"  # a length http.client does not take
        self.assertEqual([body(unread, cap) for cap in (None, 100)], [b"tar"] * 2)
        self.assertEqual(httpbody.read(io.BytesIO(b"tarball"), 100), b"tarball")
        self.assertEqual(httpbody.read(io.BytesIO(b"tarball"), 2), b"tar")
        self.assertEqual(httpbody.read(io.BytesIO(b"tarball")), b"tarball")

    def test_the_errors_are_oserror_and_http_clients_which_is_not_one(self):
        self.assertEqual(httpbody.ERRORS, (OSError, http.client.HTTPException))
        self.assertFalse(issubclass(http.client.HTTPException, OSError))
        for kind in (urllib.error.URLError, urllib.error.HTTPError, socket.gaierror, TimeoutError,
                     ConnectionResetError, http.client.IncompleteRead, http.client.BadStatusLine,
                     http.client.RemoteDisconnected, http.client.LineTooLong):
            self.assertTrue(issubclass(kind, httpbody.ERRORS), kind)


FAILED = {  # each a failed exchange; the first four are bytes http.client itself judges
    "short of its length": answer(200, b'{"a', length=9),
    "cut inside a chunk": chunked(200, b'{"a": 1}', cut=9),
    "no status line": b"garbage\r\n\r\n",
    "closed before an answer": b"",
    "refused": urllib.error.URLError(ConnectionRefusedError(111, "Connection refused")),
    "timeout": TimeoutError("timed out"),
}
BODIES = ("short of its length", "cut inside a chunk")
UUID = "0" * 64


def state_reasons(call) -> list[str]:
    try:
        call()
    except A.StateError as exc:
        return exc.reasons
    raise AssertionError("no StateError")


class HttpSites(unittest.TestCase):
    def test_the_stand_in_raises_what_http_client_raises(self):
        raised = {}
        for name, step in FAILED.items():
            try:
                httpbody.read(response(step)) if isinstance(step, bytes) else None
            except httpbody.ERRORS as exc:
                raised[name] = type(exc)
        self.assertEqual(raised, {
            "short of its length": http.client.IncompleteRead, "cut inside a chunk": http.client.IncompleteRead,
            "no status line": http.client.BadStatusLine, "closed before an answer": http.client.RemoteDisconnected})

    def test_deps_npm_reads_each_again(self):
        for name, step in FAILED.items():
            for cap in (None, 100):
                with self.subTest(name, cap=cap):
                    with self.assertRaises(N.FetchAgain):
                        N.https_once(URL, cap, (Wire(step),))

    def test_accepted_json_is_actions_unreadable(self):
        for name, step in FAILED.items():
            with self.subTest(name):
                http = A.ActionsHttp("tok", handlers=(Wire(step),))
                self.assertEqual(state_reasons(lambda: http.json("/x")), ["actions_unreadable"])
        self.assertEqual(A.ActionsHttp("tok", handlers=(Wire(chunked(200, b'{"a": 1}')),)).json("/x"), {"a": 1})

    def test_accepted_blob_is_actions_unreadable(self):
        for name, step in FAILED.items():
            with self.subTest(name):
                http = A.ActionsHttp("tok", handlers=(Wire(step),))
                self.assertEqual(state_reasons(lambda: http.blob("https://b.example/z", 100)), ["actions_unreadable"])
        http = A.ActionsHttp("tok", handlers=(Wire(answer(200, b"zip")),))
        self.assertEqual(http.blob("https://b.example/z", 100), b"zip")

    def test_accepted_redirect_is_actions_unreadable(self):
        for name in sorted(set(FAILED) - set(BODIES)):  # it reads no body
            with self.subTest(name):
                http = A.ActionsHttp("tok", handlers=(Wire(FAILED[name]),))
                self.assertEqual(state_reasons(lambda: http.redirect("/zip")), ["actions_unreadable"])

    def test_rekor_entry_is_a_rekor_error(self):
        texts = {}
        for name, step in FAILED.items():
            with self.assertRaises(R.RekorError) as caught:
                R.RekorHttp(handlers=(Wire(step),)).entry(UUID)
            texts[name] = str(caught.exception)
        self.assertEqual(texts, {
            "short of its length": "rekor unreadable: IncompleteRead",
            "cut inside a chunk": "rekor unreadable: IncompleteRead",
            "no status line": "rekor unreadable: BadStatusLine",
            "closed before an answer": "rekor unreadable: RemoteDisconnected",
            "refused": "rekor unreadable: URLError", "timeout": "rekor unreadable: TimeoutError"})

    def test_the_write_transport_has_no_handler_and_raises_each_as_it_is(self):
        raised = {}
        for name, step in FAILED.items():
            try:
                W.HttpTransport("tok", handlers=(Wire(step),))("GET", "/repos/o/r", None)
            except httpbody.ERRORS as exc:
                raised[name] = type(exc)
        self.assertEqual(raised, {
            "short of its length": http.client.IncompleteRead, "cut inside a chunk": http.client.IncompleteRead,
            "no status line": http.client.BadStatusLine, "closed before an answer": http.client.RemoteDisconnected,
            "refused": urllib.error.URLError, "timeout": TimeoutError})
        whole = W.HttpTransport("tok", handlers=(Wire(chunked(200, b'{"a": 1}')),))("GET", "/repos/o/r", None)
        self.assertEqual(whole, (200, {"a": 1}))


BUILD = "urllib.request.build_opener"
NAMED = "httpbody.ERRORS"
CALLERS_HANDLE = ("target/write.py",)  # httpbody's stated scope: the transport that sends writes has no handler


def opened(source: str) -> list[tuple[int, list[str]]]:
    """``(line, faults)`` of every ``with`` in ``source`` that opens a response through an opener made by
    ``urllib.request.build_opener`` (a name or attribute assigned that call anywhere in the source, or the call
    itself, then ``.open(...)``). Faults: ``read`` (the block names a read method of the response: ``read``,
    ``read1``, ``readinto``, ``readline``, ``readlines``), ``handler`` (the ``with`` is in no ``try`` body of its
    function with a handler naming ``httpbody.ERRORS``). Out of scope, stated: an opener that
    reaches ``open`` another way (an argument, a function's return value, an alias of the module)."""
    tree = ast.parse(source)
    openers = {ast.unparse(target) for node in ast.walk(tree) if isinstance(node, ast.Assign)
               and isinstance(node.value, ast.Call) and ast.unparse(node.value.func) == BUILD
               for target in node.targets}
    found = []

    def is_open(expr: ast.expr) -> bool:
        if not (isinstance(expr, ast.Call) and isinstance(expr.func, ast.Attribute) and expr.func.attr == "open"):
            return False
        holder = expr.func.value
        return ast.unparse(holder) in openers or (isinstance(holder, ast.Call) and ast.unparse(holder.func) == BUILD)

    def visit(node: ast.AST, handled: bool) -> None:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            handled = False
        if isinstance(node, ast.With):
            for item in node.items:
                if not is_open(item.context_expr):
                    continue
                faults = [] if handled else ["handler"]
                name = item.optional_vars.id if isinstance(item.optional_vars, ast.Name) else None
                reads = [n for stmt in node.body for n in ast.walk(stmt) if isinstance(n, ast.Attribute)
                         and n.attr in ("read", "read1", "readinto", "readline", "readlines")
                         and isinstance(n.value, ast.Name) and n.value.id == name]
                if reads:
                    faults.append("read")
                found.append((node.lineno, faults))
        if isinstance(node, ast.Try):
            names = any(NAMED in ast.unparse(h.type) for h in node.handlers if h.type is not None)
            for child in node.body:
                visit(child, handled or names)
            for child in [*node.handlers, *node.orelse, *node.finalbody]:
                visit(child, handled)
            return
        for child in ast.iter_child_nodes(node):
            visit(child, handled)

    visit(tree, False)
    return found


def identifiers(source: str) -> tuple[set[str], set[str]]:
    """Every name the code of ``source`` uses (names, attribute names, imported names; not its strings), and each
    name and attribute chain as written (``urllib.request.build_opener``; an imported name alone)."""
    names, dotted = set(), set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Name):
            names.add(node.id)
            dotted.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
            dotted.add(ast.unparse(node))
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                names.update(alias.name.split("."))
                dotted.add(alias.name)
    return names, dotted


class Register(unittest.TestCase):
    def test_every_opened_response_is_read_through_cli_and_handled(self):
        found = {path: opened(src) for path, src in sources().items()}
        sites = {path: len(got) for path, got in found.items() if got}
        self.assertEqual(sites, {"loop/accepted.py": 3, "loop/rekor.py": 1, "runner/deps_npm.py": 1,
                                 "target/write.py": 1})
        faults = {path: [f for _, f in got if f] for path, got in found.items()}
        self.assertEqual({p: f for p, f in faults.items() if f}, {p: [["handler"]] for p in CALLERS_HANDLE})

    def test_every_source_that_builds_an_opener_is_in_the_register(self):
        named = {path: identifiers(src) for path, src in sources().items()}
        builders = sorted(p for p, (names, _) in named.items() if "build_opener" in names)
        self.assertEqual(builders, ["loop/accepted.py", "loop/rekor.py", "runner/deps_npm.py", "target/write.py"])
        for path, (names, dotted) in named.items():
            self.assertEqual({d for d in dotted if d.endswith("build_opener")} - {BUILD}, set(), path)
            self.assertEqual(names & {"urlopen", "HTTPSConnection", "HTTPConnection"}, set(), path)
        names, dotted = identifiers("from urllib.request import build_opener as b, urlopen\nimport http.client\n"
                                    "c = http.client.HTTPSConnection(h)\no = urllib.request.build_opener()\n")
        self.assertEqual(names & {"build_opener", "urlopen", "HTTPSConnection"},
                         {"build_opener", "urlopen", "HTTPSConnection"})
        self.assertEqual({d for d in dotted if d.endswith("build_opener")}, {"build_opener", BUILD})

    def test_the_register_sees_each_way_to_leave_the_rule(self):
        head = "import urllib.request\nimport httpbody\nopener = urllib.request.build_opener()\n"
        bad = {
            "its own read": (head + "try:\n    with opener.open(u) as resp:\n        x = resp.read(9)\n"
                             "except httpbody.ERRORS:\n    pass\n", [["read"]]),
            "its own uncapped read": (head + "try:\n    with opener.open(u) as resp:\n        x = resp.read()\n"
                                      "except httpbody.ERRORS:\n    pass\n", [["read"]]),
            "read handed on": (head + "try:\n    with opener.open(u) as resp:\n        x = f(resp.read)\n"
                               "except httpbody.ERRORS:\n    pass\n", [["read"]]),
            "its own list": (head + "try:\n    with opener.open(u) as resp:\n        x = httpbody.read(resp, 9)\n"
                             "except (urllib.error.URLError, OSError):\n    pass\n", [["handler"]]),
            "no try": (head + "with opener.open(u) as resp:\n    x = httpbody.read(resp, 9)\n", [["handler"]]),
            "opened in the handler": (head + "try:\n    pass\nexcept httpbody.ERRORS:\n"
                                      "    with opener.open(u) as resp:\n        x = httpbody.read(resp)\n",
                                      [["handler"]]),
            "the try is another function's": (head + "try:\n    def f():\n        with opener.open(u) as resp:\n"
                                              "            return httpbody.read(resp)\n"
                                              "except httpbody.ERRORS:\n    pass\n", [["handler"]]),
            "an attribute, both": ("import urllib.request\nclass C:\n    def __init__(self):\n"
                                   "        self.opener = urllib.request.build_opener()\n    def get(self, u):\n"
                                   "        with self.opener.open(u) as resp:\n            return resp.read(5)\n",
                                   [["handler", "read"]]),
            "built in place": ("import urllib.request\nwith urllib.request.build_opener().open(u) as r:\n"
                               "    x = r.read()\n", [["handler", "read"]]),
        }
        for why, (src, faults) in bad.items():
            self.assertEqual([f for _, f in opened(src)], faults, why)
        good = {
            "the rule": head + "try:\n    with opener.open(u, timeout=3) as resp:\n        x = httpbody.read(resp, 9)\n"
                               "except urllib.error.HTTPError:\n    pass\nexcept httpbody.ERRORS as exc:\n    pass\n",
            "in a tuple": head + "try:\n    with opener.open(u) as resp:\n        x = httpbody.read(resp)\n"
                                 "except (*httpbody.ERRORS, ValueError):\n    pass\n",
            "an outer try": head + "try:\n    try:\n        with opener.open(u) as resp:\n            pass\n"
                                   "    finally:\n        pass\nexcept httpbody.ERRORS:\n    pass\n",
        }
        for why, src in good.items():
            self.assertEqual([f for _, f in opened(src)], [[]], why)
        other = "import tarfile\nwith tarfile.open(p) as tar:\n    x = tar.read()\nwith open(p) as fh:\n    fh.read()\n"
        self.assertEqual(opened(other), [])  # not an opener's response: not this register's


if __name__ == "__main__":
    unittest.main()
