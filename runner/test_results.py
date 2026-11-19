"""``test_results``: one test run's stdout and exit code as the ``tests`` list the gate and the sentinel read
(stage 0; called by ``runner.kos`` for a candidate's ``checks.json`` and for each sentinel run).

Rules: asama-0/08 criteria 6 and 7 (the affected tests are green; zero tests is red), tohum/04 (zero tests is
red), ``gate.check`` (``checks.json``'s ``tests``: ``[{id, status: pass|fail}]``; empty is ``zero_tests``, a
``fail`` is ``tests_red``), ``gate.sentinel`` (a run's ``results``, the same list; an id twice is unusable).

The recipe's schema (tohum/26c) has no field that names the test runner, so the output says what it is
(``read``): stdout that holds jest's document is read as jest's, any other stdout as TAP. Two formats are read;
nothing else is.

**jest's document** (``jest``; the ``--json`` option of the jest CLI, which ``profile.nx`` puts on the command it
composes; read from ``@jest/core`` and ``@jest/test-result`` 30.5.2's code: with ``--json`` the reporters write
to stderr and the document is written to stdout once, as one line with a final ``\\n``, after the run). The
document is found by ``lint_record``'s rules 1 and 2 (``last_document``: the whole stdout when it is JSON, else
the last line; the bytes before it are the test code's own writes to stdout and are not read) and has jest's
shape (``shaped``): an object whose ``numTotalTests`` is an integer and whose ``testResults`` is a list of
objects, each with ``name`` and ``status`` strings and ``assertionResults``, a list of objects with ``title``
and ``status`` strings and ``ancestorTitles``, a list of strings. Its tests, files in document order:

- one entry per assertion in the file's order: ``id`` is the file, the ancestor titles and the title joined
  by `` > ``, the file being ``name`` relative to the container's root (``lint_record.relative``; a ``name``
  not under it as written); status ``passed`` is ``pass``; ``pending``, ``skipped``, ``todo`` and ``disabled``
  are left out (the test did not run; TAP's ``SKIP`` and ``TODO`` rule); any other status is ``fail``;
- a file whose status is not ``passed``, ``focused`` (jest's word for a file whose run tests passed with others
  pending) or ``skipped`` and none of whose assertions is ``fail`` gives one entry, ``id`` the file, ``fail``:
  a test file that did not run (jest reports a file it could not compile or load as ``failed`` with no
  assertion) is red by its own name;
- an earlier line of stdout that itself has the shape (``lint_record``'s rule 4) gives the one entry
  ``{id: SEVERAL, status: fail}`` and nothing else: a command that runs jest twice would otherwise lose the
  first run's results without a trace.

Stdout whose last line is not such a document is not jest's and is read as TAP: text on the document's own line
(a write to stdout without a newline before jest's), lines after it, and ``--outputFile`` (the document goes to
a file) leave no TAP line either, so the list is empty or the exit entry below.

**TAP** (``tap``; ``node --test``'s default reporter when stdout is not a terminal). A test is a top-level line
``ok N`` or ``not ok N``, optionally `` - description``, at column 0; indented lines are subtests and are not
counted, as ``node --test`` indents them. Its ``id`` is the description with TAP's ``\\#`` and ``\\\\`` escapes
undone (the number when there is none); a line whose directive (after the first unescaped `` # ``) starts with
``SKIP`` or ``TODO`` (any case) is left out: a skipped test did not run and a failing TODO test does not fail
the run.

**The exit code** (``read``, both formats): when the command exits non-zero and no listed test failed, one entry
``{id: "test_cmd exit <code>", status: fail}`` is added, so a crash, a ``Bail out!``, or a jest run that failed
for a reason no test carries (a coverage threshold, no test found) is red, not zero tests.

Out of scope, stated: other runners and reporters (mocha, vitest, pytest, jest's default reporter: no line of
theirs is read, so ``tests`` is empty and the gate's ``zero_tests`` rejects: closed, not open); a jest command
this brain did not compose with ``--json`` (an owner's ``npm test`` script: ``profile.fit``'s npm form adds no
option); ids that repeat (two TAP lines with one description, two jest tests of one file with the same titles:
each is its own entry, and the sentinel reads such a run as unusable); whether the test code wrote a second
document or TAP lines of its own on stdout beyond the rules above (the run's stdout is the tested tree's own
output in both formats; the exit code is the command's).
"""

from __future__ import annotations

import re
from typing import Any

from runner import lint_record as R

TAP_LINE = re.compile(r"(not ok|ok) ([0-9]+)(?: - (.*))?\Z")
SKIPPED = ("skip", "todo")
JEST_PASSED = "passed"
JEST_NOT_RUN = ("pending", "skipped", "todo", "disabled")
JEST_FILE_OK = ("passed", "focused", "skipped")
JOIN = " > "
SEVERAL = "test_cmd output: several documents"


# ---------------------------------------------------------------- TAP

def _split_directive(text: str) -> tuple[str, str | None]:
    """``(description, directive)``: the directive follows the first `` #`` not escaped by a backslash."""
    i = 0
    while i < len(text):
        if text[i] == "\\":
            i += 2
            continue
        if text[i] == "#" and i > 0 and text[i - 1] == " ":
            return text[:i - 1], text[i + 1:].strip()
        i += 1
    return text, None


def _unescape(text: str) -> str:
    return re.sub(r"\\([\\#])", r"\1", text)


def tap(stdout: bytes) -> list[dict]:
    """The top-level TAP lines of ``stdout`` as tests (module docstring, "TAP")."""
    tests = []
    for raw in stdout.decode("utf-8", "replace").split("\n"):
        m = TAP_LINE.fullmatch(raw.rstrip("\r"))
        if not m:
            continue
        desc, directive = _split_directive(m.group(3) or "")
        if directive is not None and directive.lower().startswith(SKIPPED):
            continue
        tests.append({"id": _unescape(desc) or m.group(2), "status": "pass" if m.group(1) == "ok" else "fail"})
    return tests


# ---------------------------------------------------------------- jest

def _strings(value: Any, keys: tuple) -> bool:
    return isinstance(value, dict) and all(isinstance(value.get(k), str) for k in keys)


def shaped(doc: Any) -> bool:
    """Whether a JSON value is jest's ``--json`` document (the module docstring's shape)."""
    return (isinstance(doc, dict) and type(doc.get("numTotalTests")) is int
            and isinstance(doc.get("testResults"), list)
            and all(_strings(f, ("name", "status")) and isinstance(f.get("assertionResults"), list)
                    and all(_strings(a, ("title", "status")) and isinstance(a.get("ancestorTitles"), list)
                            and all(isinstance(t, str) for t in a["ancestorTitles"])
                            for a in f["assertionResults"])
                    for f in doc["testResults"]))


def jest(stdout: bytes, root: str = R.CONTAINER_ROOT) -> list[dict] | None:
    """The tests of jest's document on ``stdout`` (module docstring, "jest's document"); ``None`` when stdout
    does not end with one."""
    extra, doc = R.last_document(stdout)
    if not shaped(doc):
        return None
    if R.earlier_document(extra, shaped):
        return [{"id": SEVERAL, "status": "fail"}]
    tests = []
    for result in doc["testResults"]:
        name = R.relative(result["name"], root) or result["name"]
        own = [{"id": JOIN.join([name] + a["ancestorTitles"] + [a["title"]]),
                "status": "pass" if a["status"] == JEST_PASSED else "fail"}
               for a in result["assertionResults"] if a["status"] not in JEST_NOT_RUN]
        if result["status"] not in JEST_FILE_OK and not any(t["status"] == "fail" for t in own):
            own.append({"id": name, "status": "fail"})
        tests += own
    return tests


# ---------------------------------------------------------------- one run

def read(stdout: bytes, exit_code: int | None, root: str = R.CONTAINER_ROOT) -> list[dict]:
    """The ``tests`` list of one test run: jest's document when stdout ends with one, else TAP; the exit entry
    (module docstring)."""
    tests = jest(stdout, root)
    if tests is None:
        tests = tap(stdout)
    if exit_code != 0 and not any(t["status"] == "fail" for t in tests):
        tests.append({"id": "test_cmd exit %s" % exit_code, "status": "fail"})
    return tests
