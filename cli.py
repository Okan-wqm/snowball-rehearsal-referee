"""The one process boundary of every referee command line: each module ends with
``sys.exit(cli.run(main, sys.argv[1:], FAULT_LINE))``.

Why: every command here answers with its exit code, and 0 and 1 are verdicts in each of them (clean or match,
merge or reject, valid or broken; each module's docstring gives its own meaning), while 2 is "unusable, no
verdict". Python itself ends a process with exit 1 when an exception escapes, and with 120 when stdout cannot
be flushed at shutdown. So a fault (a bug, an exception a module's own handlers did not expect, an exception in
such a handler, or a stdout that is closed or a broken pipe) would read as a verdict. Measured before this module:
with stdout closed, 20 of the 22 commands exited 1 (``gate.secrets scan`` on a clean file said "match").

Rules ``run`` keeps (each bound by a test in ``tests/test_cli.py``):

1. ``main``'s stdout is held in memory and written to the real stdout only after ``main`` returned; so a run that
   faults never leaves a verdict line, even one ``main`` wrote before the fault.
2. ``main`` must return an ``int`` that is 0, 1 or 2 (a ``bool`` or ``None`` is a fault: ``sys.exit(None)``
   would be exit 0).
3. Any ``Exception`` escaping ``main``, and ``SystemExit`` raised inside it (a command returns its code, it does
   not exit), is a fault.
4. Writing or flushing the held output to the real stdout is part of the run; if it fails, that is a fault.
5. On a fault: exit 2; stderr gets ``internal error: <exception type>`` (the type only, never the message or a
   traceback: a message can carry the scanned or sent text, tohum/30c); stdout gets the module's ``fault_line``
   (a dict, or a function of argv for commands whose exit-2 line depends on the command; if that function fails,
   ``GENERIC_LINE``) as one JSON line. If stdout cannot take that line either, its descriptor is pointed at
   ``/dev/null`` so the interpreter's own flush at shutdown cannot turn the exit into 120. When the real stdout
   breaks part way through (rule 4), the bytes it took before breaking stay where they went; the exit is 2.

6. Outside this module, a handler that catches every exception (bare, ``Exception`` or ``BaseException``) either
   ends with a bare ``raise`` (cleanup) or reports through ``internal_error(<its exception>)``, and uses the
   exception nowhere else; so the last-resort text is this module's, type only. Every command but ``target.write``
   leaves the fault to ``run``; ``target.write`` keeps one handler, because its line says what was already sent. Bound by a register over every source file in ``tests/test_cli.py``. Not this rule's: the narrower
   handlers, which are rule 7's.
7. Outside this module, every handler that names its exception (``except ... as exc``) uses that name only as
   ``cause(exc)``, ``internal_error(exc)``, ``raise ... from exc`` (a chained cause is never printed: rule 5 prints
   the type), or one of the attributes in ``KEPT_ATTRIBUTES``; and no source reads ``traceback``, ``exc_info``,
   ``__context__``, ``__cause__`` or ``__traceback__``. So the only text of a caught exception that can reach an
   output is ``cause``'s, and ``cause`` writes the message only of an exception whose class is defined in a
   source file under ``referee/`` (its text is built at a referee raise site); of any other exception it writes
   no character of the message: only the type's name, a JSON or Unicode position with the encoding's name, or an
   ``OSError``'s ``strerror`` (the text set with its errno; for a system call, the OS's), never its file name.
   Bound in ``tests/test_cli.py`` by a register over every source file, by ``CauseOf`` and by ``Injected`` (every
   command run with its reads raising a builtin exception that carries a mark). Measured before this rule: the
   register finds 78 uses of a caught exception in 22 modules, among them ``"unusable input: %s" % exc`` over
   ``ValueError``, ``KeyError`` and ``OSError``, whose messages quote their input (``int('...')`` quotes its
   argument, a ``KeyError`` its key, an ``OSError`` its path, a ``UnicodeDecodeError`` the byte).
   Out of scope, stated: what a referee raise site itself puts in its own exception's text (a field name, a path
   from argv, a value of the request; rule 7 makes such a site the only author, it does not review what it
   quotes); a child process's own stderr.

8. Outside this module, no source parses JSON with ``json.load`` or ``json.loads``: it calls ``loads`` or ``load``
   here, which take the same arguments and raise ``TooDeep``, a ``ValueError`` and a ``RecursionError`` at once, for
   JSON nested deeper than ``DEPTH`` (128) arrays and objects, and for the parser's own ``RecursionError``; any
   other result or exception of the parser is unchanged.
   Why: a handler written for unusable JSON names ``ValueError``; the decoder's depth failure is not one, so it
   escaped such handlers as a fault (exit 2 with the fault line instead of the command's own unusable line; measured
   before this rule: 22 of 51 parse sites in 19 modules had no handler naming it in their function, among them
   ``status.depmap delta`` on a file of 200000 ``[``). Being both, ``TooDeep`` is caught by every handler that caught
   the parser's failure before (one naming ``RecursionError`` keeps its own text), and by every ``ValueError``
   handler. And on python 3.12 the C decoder parses about 10000 levels, while a recursive walk in Python stops at
   the interpreter's recursion limit (1000 frames): measured before the bound, ``profile.fit`` on a tree whose
   ``project.json`` nests a lint option 3000 lists deep faulted (``profile.nx``'s ``resolved``), where the same tree
   with that file unparsable gives the command's own answer. The bound makes every parsed value shallow enough for
   any walk of up to 7 frames a level; the deepest JSON measured in the vector inputs is 6 levels, in the first
   target's 1190 JSON files 10. Depth is counted on the text after a successful parse: each ``[`` or ``{`` outside
   a string opens a level, so a hook (``object_pairs_hook`` and the others) does not change it. Bound by a register
   over every source file, by ``LoadsDepth`` and ``Walks`` (every function in a referee source that calls itself
   by name, run over a value ``DEPTH`` deep) in ``tests/test_cli.py``, and by ``Deep`` (``profile.fit``) in
   ``tests/test_profile_nx.py``.
   Out of scope, stated: values not parsed here (built in memory, read by another parser such as ``tomllib``);
   recursion through two or more functions (``Walks`` finds a function calling itself by its own name only).

9. Outside this module, a handler that turns unreadable archive bytes (a tar, a gzip stream, a zip) into the
   command's own answer names ``ARCHIVE_ERRORS``: ``tarfile.TarError``, ``gzip.BadGzipFile``, ``zlib.error``,
   ``EOFError`` and ``zipfile.BadZipFile``, what those libraries raise for malformed bytes, each seen in
   ``tests/test_archives.py``'s corpus (every byte of a small archive flipped, every third truncation,
   300 seeded scrambles) or one of its fixtures. A handler may add the errors of its own context after them (a file
   it opens: ``OSError``). zipfile also raises ``RuntimeError`` (an encrypted member; its ``NotImplementedError``,
   an unknown method or version, is one) and ``ValueError`` (an offset before the archive) for malformed bytes; being
   types any code raises, they are not in the tuple: the one zip reader (``loop.accepted.unpack``) names them for a
   ``try`` that holds only zipfile calls. Why: each reader had written its own list, and three missed one (measured
   before this rule over that corpus: ``loop.accepted.unpack`` let ``zlib.error`` and ``RuntimeError`` through,
   ``loop.treehash``'s command ``EOFError`` and ``zlib.error``, ``profile.derive.read_tree`` and
   ``profile.unit_verify``'s unpack ``gzip.BadGzipFile``, a CRC failure); each escape was a fault (rule 3) where
   the command had its own refusal. Bound by ``tests/test_archives.py``: every reader that names the tuple runs
   over the corpus, and each variant is read, or refused by the reader's own answer, or (a reader whose handler is
   its caller's: ``loop.treehash.of_tar``, ``profile.unit_verify.unpack``) raises only what that handler catches;
   and a register over every source file: outside this module, no handler names one of those library errors itself.
   Out of scope, stated: the readers' own checks of what a readable archive holds; errors of writing what an
   archive holds (``profile.unit_verify`` writes files: an ``OSError`` there is a fault, not a refusal).

Out of scope, stated: a fault while the module is imported (``python -m`` runs the module's top level before this
boundary exists; ``tests/test_cli.py`` imports every command module, so a broken import is red before a push); signals and
``KeyboardInterrupt`` (they end the process with their own codes, never 1); the interpreter being killed;
a child process writing to descriptor 1 directly (no command here lets a child inherit it: ``gate.secrets send``
gives its sender stderr, the others capture or discard the child's stdout).
"""

from __future__ import annotations

import gzip
import io
import json
import os
import re
import sys
import tarfile
import zipfile
import zlib
from typing import Any, Callable

FAULT_EXIT = 2
EXITS = (0, 1, 2)
GENERIC_LINE = {"error": "internal error"}


class Fault(Exception):
    """``main`` broke the boundary's contract (rule 2, 3 or 4)."""


class TooDeep(ValueError, RecursionError):
    """JSON nested deeper than ``DEPTH`` or than the parser can go (rule 8)."""


DEPTH = 128  # the deepest JSON loads returns, in arrays and objects (rule 8)
ARCHIVE_ERRORS = (tarfile.TarError, gzip.BadGzipFile, zlib.error, EOFError, zipfile.BadZipFile)  # rule 9
_LEVEL = re.compile(r"[\[\]{}]")


def outside_strings(text: str) -> str:
    """The valid JSON ``text`` without its strings (their quotes included).

    In valid JSON a backslash occurs only in a string, where it starts a two-character escape (``\\uXXXX`` is ``\\u``
    and four plain characters). So each run of backslashes pairs from its left end, as ``str.replace`` pairs it; after
    the pairs go, a backslash left over escapes the character after it, and removing every ``\\"`` leaves only the
    quotes that open and close strings, which alternate: the even pieces between them are the text outside strings.
    Only ``str`` methods, no regular expression: on string-heavy text (one long string, long runs of escaped quotes or
    of backslashes) measured at most 2.5 times ``json.loads`` and bound below 8 times by ``LoadsDepth``, where the
    former pattern ``"(?:[^"\\]|\\.)*"`` took 16 to 100 times. Text that is not valid JSON is out of scope."""
    return "".join(text.replace("\\\\", "").replace('\\"', "").split('"')[::2])


def depth(text: str) -> int:
    """How many arrays and objects deep the valid JSON ``text`` nests (a scalar is 0); brackets in strings do not
    count."""
    level = deepest = 0
    for bracket in _LEVEL.findall(outside_strings(text)):
        if bracket in "[{":
            level += 1
            deepest = max(deepest, level)
        else:
            level -= 1
    return deepest


def loads(text: str | bytes, **options: Any) -> Any:
    """``json.loads(text, **options)``; ``TooDeep`` for JSON deeper than ``DEPTH`` or for the parser's
    ``RecursionError`` (rule 8)."""
    try:
        value = json.loads(text, **options)
    except RecursionError:
        raise TooDeep("JSON nested too deeply") from None
    if isinstance(text, (bytes, bytearray)):
        text = text.decode(json.detect_encoding(text), "surrogatepass")  # as json.loads decoded it
    if depth(text) > DEPTH:
        raise TooDeep("JSON nested too deeply")
    return value


def load(stream: Any, **options: Any) -> Any:
    """``json.load(stream, **options)`` by ``loads`` (rule 8)."""
    return loads(stream.read(), **options)


def internal_error(exc: BaseException) -> str:
    """The one text of an unexpected exception (rule 5): ``internal error: <type>``, never the message.

    A ``Fault``'s text is written here, by this module, so it is kept (``exit 3``, ``stdout``). Used by ``run`` and
    by the one module handler that reports a fault itself (``target.write``: it knows what it already wrote).
    """
    return "internal error: %s" % (str(exc) if isinstance(exc, Fault) else type(exc).__name__)


KEPT_ATTRIBUTES = ("reasons", "status", "code")
"""Attributes of a caught exception a handler may read (rule 7). Each is set by its raiser as a code, not a message:
``reasons``, a referee exception's list of reason codes (``loop.pulled``, ``runner.lint_record``, ``target.write``);
``status``, ``target.write.ApiError``'s HTTP status; ``code``, ``urllib.error.HTTPError``'s HTTP status."""

_HOME = os.path.dirname(os.path.abspath(__file__)) + os.sep


def _own(exc: BaseException) -> bool:
    """True when ``exc``'s class is defined in a source file under ``referee/`` (``__main__`` included when the
    command was started with ``python -m``)."""
    module = sys.modules.get(type(exc).__module__)
    path = getattr(module, "__file__", None)
    return isinstance(path, str) and os.path.abspath(path).startswith(_HOME)


def cause(exc: BaseException) -> str:
    """The one text of a caught exception that may reach an output (rule 7).

    - A referee exception (its class is defined under ``referee/``): its message, written at a referee raise site.
    - ``json.JSONDecodeError``: ``JSONDecodeError at line L column C``, the type and the position (the decoder's
      message can quote a character of the input).
    - ``UnicodeError`` with a position: ``<type> at position N (<encoding>)`` (the default text quotes the byte).
    - ``OSError`` with an error text (``strerror``, set with an errno; for a system call the OS's text,
      ``No such file or directory``): that text, never the file name.
    - Anything else: the type's name alone (``KeyError``, ``ValueError``, ``TarError``).
    """
    if _own(exc):
        return str(exc)
    if isinstance(exc, json.JSONDecodeError):
        return "JSONDecodeError at line %d column %d" % (exc.lineno, exc.colno)
    if isinstance(exc, UnicodeError) and isinstance(getattr(exc, "start", None), int):
        encoding = getattr(exc, "encoding", None)
        return "%s at position %d (%s)" % (type(exc).__name__, exc.start,
                                           encoding if isinstance(encoding, str) else "unknown encoding")
    if isinstance(exc, OSError) and isinstance(exc.strerror, str):
        return exc.strerror
    return type(exc).__name__


def _call(main: Callable[[list[str]], Any], argv: list[str]) -> tuple[int, str]:
    held = io.StringIO()
    real = sys.stdout
    sys.stdout = held
    try:
        try:
            code = main(argv)
        except SystemExit as exc:
            raise Fault("SystemExit") from exc
    finally:
        sys.stdout = real
    if type(code) is not int or code not in EXITS:
        raise Fault("exit %r" % (code,))
    return code, held.getvalue()


def _say(stream: Any, text: str) -> bool:
    """Write and flush ``text``; False when the stream is closed (None) or broken."""
    try:
        stream.write(text)
        stream.flush()
        return True
    except (AttributeError, OSError, ValueError):
        return False


def _quiet_stdout() -> bool:
    """Point descriptor 1 at /dev/null (rule 5); False when there is no descriptor to point (a closed stdout)."""
    try:
        fd = sys.stdout.fileno()
        devnull = os.open(os.devnull, os.O_WRONLY)
    except (AttributeError, OSError, ValueError):
        return False
    try:
        os.dup2(devnull, fd)
    finally:
        os.close(devnull)
    return True


def _line(fault_line: Any, argv: list[str]) -> dict[str, Any]:
    """The module's exit-2 line; a ``fault_line`` function that itself fails gives ``GENERIC_LINE``."""
    if not callable(fault_line):
        return fault_line
    try:
        return fault_line(argv)
    except Exception:  # noqa: BLE001 - the line is chosen during a fault; the exit code already says no verdict
        return GENERIC_LINE


def run(main: Callable[[list[str]], Any], argv: list[str], fault_line: Any) -> int:
    """Run ``main(argv)`` under rules 1-5 of the module docstring and return the process's exit code."""
    try:
        code, out = _call(main, argv)
        if not _say(sys.stdout, out):
            raise Fault("stdout")
        return code
    except Exception as exc:  # noqa: BLE001 - rule 5: a fault is exit 2 with a reason, never exit 1
        # The exit code is the answer; the two lines below are best effort, a closed stream cannot change it.
        _say(sys.stderr, internal_error(exc) + "\n")
        if not _say(sys.stdout, json.dumps(_line(fault_line, argv), sort_keys=True) + "\n"):
            _quiet_stdout()
        return FAULT_EXIT
