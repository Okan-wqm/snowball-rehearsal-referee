"""One rule for every command-line refusal test: an exit-2 line is the module's own refusal, not ``cli.run``'s fault.

A module refuses unusable input in its own handler: exit 2 and its own line. An exception the module did not expect
reaches ``cli.run`` (rule 5), which also exits 2, but writes ``internal error: <type>`` on stderr and the module's
``FAULT_LINE`` (or ``cli.GENERIC_LINE`` when a fault-line function fails) on stdout. A test that takes any exit-2
line with an ``error`` key as the refusal therefore passes when the module crashes (ledger f951, f952): the crash
looks like a refusal. ``assert_refused`` tells them apart by both marks of a fault, so a caller asserts only what
its own refusal says (its ``error`` text, its ``ok``).

A module whose refusal line equals its fault line by design (``gate.check decide``: both are ``{"decision":
"reject"}``, so a crash still rejects) cannot be told apart by the line. Its caller passes ``cause``, a regex
the module's own refusal writes on stderr (``gate.check``: ``unusable input: ``); then the stderr must match it,
and the line check is waived only for a fault line equal to ``line``.

Out of scope: a run whose stderr was not captured (the stderr mark is then not seen; the line check still holds,
and with ``cause`` the run fails).
"""

from __future__ import annotations

import re
from typing import Any

import cli

FAULT_MARK = re.compile(r"(?m)^internal error: ")


def assert_refused(test: Any, module: Any, argv: list[str], code: int, line: Any, stderr: str | bytes,
                   cause: str | None = None) -> None:
    """``code`` is exit 2 and (``line``, ``stderr``) carry no mark of ``cli.run``'s fault path for ``module``
    run with ``argv``: no ``internal error: `` stderr line, no traceback, and ``line`` is neither the module's
    fault line for ``argv`` nor ``cli.GENERIC_LINE``; with ``cause``, the stderr matches it (``re.search``) and a
    fault line equal to ``line`` is the module's refusal line by design (see the module docstring)."""
    if isinstance(stderr, bytes):
        stderr = stderr.decode("utf-8", "replace")
    test.assertEqual(code, cli.FAULT_EXIT, (argv, line, stderr))
    test.assertNotIn("Traceback", stderr, argv)
    test.assertIsNone(FAULT_MARK.search(stderr), "cli.run's fault, not a refusal: %r %r" % (argv, stderr))
    if cause is not None:
        test.assertRegex(stderr, cause, argv)
    for fault in (cli._line(module.FAULT_LINE, argv), cli.GENERIC_LINE):  # the one rule cli.run picks it by
        if cause is not None and line == fault:
            continue  # the refusal line by design; the stderr cause above told them apart
        test.assertNotEqual(line, fault, "cli.run's fault line, not a refusal: %r" % (argv,))
