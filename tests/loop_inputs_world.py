"""The loop's inputs from the referee repository's own files, as the tests place them (tohum/29s, ``loop.inputs``):
the checkout's ``bootstrap.json`` and the program the ``sigstore`` step leaves. The fake ``claude`` the ``claude``
step would leave is ``fake_claude.install_for_loop``. ``own_path`` is the ``PATH`` a test gives a job: the test's
own empty directory, not the machine's ``PATH`` (founder ledger f1203: with the machine's, a job that took a
program from ``PATH`` would start one of the machine's, and a test's outcome would depend on what is installed)."""

from __future__ import annotations

import json
import os

ABSENT = object()
BOOTSTRAP = {"brain_repo": "o/brain", "rival": {"model": "claude-test-model"}, "other": [1]}


def write_bootstrap(work: str, bootstrap=None) -> None:
    """The checkout's ``bootstrap.json`` (tohum/29s): ``BOOTSTRAP`` when ``None``, else a dict, raw bytes, or
    ``ABSENT`` (no file)."""
    path = os.path.join(work, "bootstrap.json")
    if os.path.lexists(path):
        os.remove(path)
    if bootstrap is ABSENT:
        return
    body = BOOTSTRAP if bootstrap is None else bootstrap
    with open(path, "wb") as fh:
        fh.write(body if isinstance(body, bytes) else json.dumps(body).encode())


def install_sigstore(temp: str) -> str:
    """The file the sigstore step leaves at ``$RUNNER_TEMP/sig/bin/python`` (never run here: the tests' verifier
    and signer are fakes)."""
    path = os.path.join(temp, "sig", "bin", "python")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(b"")
    return path


def own_path(base: str) -> str:
    """A job environment's ``PATH`` for a test: ``<base>/path``, a directory of the test's own, made empty (the
    job's programs are the ones a step leaves under ``$RUNNER_TEMP``, tohum/29s, or a fake the test passes)."""
    path = os.path.join(base, "path")
    os.makedirs(path, exist_ok=True)
    return path
