"""The loop's inputs from the referee repository's own files, as the tests place them (tohum/29s, ``loop.inputs``):
the checkout's ``bootstrap.json`` and the program the ``sigstore`` step leaves. The fake ``claude`` the ``claude``
step would leave is ``fake_claude.install_for_loop``."""

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
