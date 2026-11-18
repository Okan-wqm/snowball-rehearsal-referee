"""The loop's one way to run the Sigstore program: its exit code, and the signs of why it failed (stage 0).

Rules: tohum/29s (the program is the ``sigstore`` step's, an argv prefix: ``loop.inputs.sigstore``), tohum/13 and
tohum/28 (a root that cannot be signed is a hard stop: ``loop.sign`` decides that, with what ``run`` answers),
``cli`` rule 7 (no text of a program's output reaches an output of the loop). Every run of ``sigstore`` in the loop
goes through ``run`` unless a caller of those modules gives its own runner (tests do): the bootstrap state's and
the Rekor entry's ``verify identity`` (``loop.accepted``, ``loop.rekor``; ``cek``) and the root's ``sign`` and
``verify identity`` (``loop.sign``; ``yaz``).

``run(argv)`` starts ``argv`` with no standard input and with its standard output and standard error in one pipe,
writes every byte it reads from the pipe to this process's standard error (file descriptor 2) as it arrives, and
answers an ``Exit``: an ``int``, the program's exit code (``127`` when it cannot start), with ``signs``, a tuple
of names. ``signs`` is empty for exit 0 and for a program that could not start; otherwise it is ``signs_of`` the
last ``TAIL`` bytes the program wrote.

``signs_of(output)`` names, in this order, by two rules:

1. each ``PHRASES`` entry ``(name, phrase)`` whose phrase occurs in the output once every run of white space is
   one space (``sigstore`` wraps its messages at word boundaries): ``name``. The phrases are literal texts of
   ``sigstore`` 4.5.0's own source (``errors.py``, ``oidc.py``, ``_internal/tuf.py``, ``_cli.py``);
2. when the output holds Python's ``Traceback (most recent call last):``: ``raised:<type>``, ``<type>`` taken
   from the last line of the output that begins with a dotted identifier (ASCII letters, digits, ``_`` and ``.``)
   whose last part ends in ``Error``, ``Exception``, ``Exit`` or ``Interrupt``, at most ``MAX_TYPE`` characters,
   followed by ``:`` or the line's end: the type an uncaught exception's last line names
   (``sigstore._internal.fulcio.client.FulcioClientError``, ``requests.exceptions.ConnectionError``), none of its
   message; ``traceback`` alone when no line is one.

A name is one of this module's own words or a name of that form; no other text of the output is answered.
``tests/fixtures/sigstore-sign-failures.json`` holds four real outputs of ``sigstore`` 4.5.0's ``sign``
(``tests/capture_sign_failures.py``); ``tests/test_program.py`` binds the rules to them.

Out of scope, stated: output that says none of this (``signs`` is then empty; the exit code is still the answer);
a phrase or a traceback cut by the ``TAIL`` bound or wrapped inside a word; colour codes (the pipe is no terminal);
another version's wording (a phrase that changed is no longer found, the traceback rule does not depend on
wording); a failure at Rekor (no captured output); how long the program runs (no time limit here: the job's own
limit ends it); whether a sign is true (any line of that form after a traceback is taken for its last line; an
exception type named otherwise is ``traceback``).
"""

from __future__ import annotations

import os
import re
import subprocess

TAIL = 1 << 16
MAX_TYPE = 120
TRACEBACK = "Traceback (most recent call last):"
RAISED = re.compile(r"((?:[A-Za-z_][A-Za-z0-9_]*\.)*[A-Za-z_][A-Za-z0-9_]*(?:Error|Exception|Exit|Interrupt))(?::|$)")
PHRASES = (
    ("network", "A network issue occurred."),
    ("tuf_refresh", "Failed to refresh TUF metadata"),
    ("root_of_trust", "Unable to establish root of trust."),
    ("ambient_credential", "An issue occurred with ambient credential detection."),
    ("no_identity", "No identity token supplied or detected!"),
    ("identity_expired", "identity token has expired"),
    ("certificate_expired", "signing certificate has expired"),
)


class Exit(int):
    """A program's exit code with ``signs`` (see the module docstring)."""

    signs: tuple[str, ...]

    def __new__(cls, code: int, signs: tuple[str, ...] = ()) -> "Exit":
        made = super().__new__(cls, code)
        made.signs = signs
        return made


def signs_of(output: bytes) -> tuple[str, ...]:
    text = output.decode("utf-8", "replace")
    joined = " ".join(text.split())
    found = [name for name, phrase in PHRASES if phrase in joined]
    if TRACEBACK in text:
        names = [m.group(1) for m in map(RAISED.match, text.splitlines()) if m and len(m.group(1)) <= MAX_TYPE]
        found.append("raised:" + names[-1] if names else "traceback")
    return tuple(found)


def _to_stderr(data: bytes) -> None:
    while data:
        data = data[os.write(2, data):]


def run(argv: list[str]) -> Exit:
    try:
        proc = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    except OSError:
        return Exit(127)
    tail = b""
    with proc.stdout as out:
        while chunk := out.read1(TAIL):
            _to_stderr(chunk)
            tail = (tail + chunk)[-TAIL:]
    code = proc.wait()
    return Exit(code, signs_of(tail) if code != 0 else ())
