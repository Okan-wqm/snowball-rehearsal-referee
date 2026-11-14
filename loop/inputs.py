"""The loop's inputs that come from the referee repository's own files, not from operator variables (stage 0,
MF17): the brain repository, the Sigstore program and the canary's ``claude`` CLI and model.

Rules: tohum/29s (no input of a ``loop.yml`` run is an operator variable, a trigger input or a program already on the
runner's PATH). One reader per input, used by every job that needs it:

- **The brain repository** (``brain_repo``): ``bootstrap.json``'s ``brain_repo``, ``owner/name``
  (``loop.accepted.repo_name``'s rule). ``cek`` reads it for D1's fetch of the accepted brain commit.
- **The canary's model** (``rival_model``): ``bootstrap.json``'s ``rival.model``, a non-empty string. ``cagir``
  sends it as the canary's requested model (D4).
- **The Sigstore program** (``sigstore``): ``$RUNNER_TEMP/sig/bin/python -m sigstore``, the virtual environment the
  ``sigstore`` step (``STEPS["sigstore"]``, 29s's text) installs from the control step's clone of
  ``bootstrap/requirements/sign.txt``. ``cek`` verifies with it (the bootstrap state, the root's Rekor entry), ``yaz``
  signs with it (``loop.sign``).
- **The canary's CLI** (``claude``): ``$RUNNER_TEMP/control/bootstrap/requirements/claude-cli/node_modules/.bin/claude``,
  the program the ``claude`` step (``STEPS["claude"]``, 29s's text) installs with ``npm ci`` from the pinned lock and
  checks against the pinned version. That lock and version check is the pin (29s: there is no separate pin of the
  executable's bytes); ``cagir`` hashes the file when the job reads it and gives that sha512 to MF15
  (``dispatcher.llm_call``), which hashes it again before it starts the process: the bytes run are the bytes the
  job found after the step, not a pin from elsewhere.

``bootstrap.json`` is read from the job's checkout (``$GITHUB_WORKSPACE/bootstrap.json``), the run's own commit of the
referee repository, the commit ``cek`` also reads ``setup/`` and ``policy.json`` from: every operator file of one
run comes from one commit. 29s also names the control step's clone (``$RUNNER_TEMP/control/bootstrap.json``, ``main``
as it is now); it is not read here. The file must be a regular file holding one JSON object with no duplicate key
and no ``NaN`` or ``Infinity``; each reader checks only its own field, so a job is not stopped by a field it does
not use. Every refusal is ``InputError`` with one reason: ``bootstrap_unreadable`` (absent, not a regular file, not
UTF-8, not that JSON), ``brain_repo_invalid``, ``rival_model_invalid``, ``sigstore_missing`` and ``claude_missing``
(the step's program is not a file: the step did not run or failed). A job turns each into no verdict (exit 2):
these are the operator's files and the run's own steps, not the brain's work.

Out of scope, stated: what the two steps do (29s's text, run by Actions; test 46 checks the workflow carries them
exactly and ``tests/test_install_steps_spec.py`` binds the copies to 29s); the other fields of ``bootstrap.json``
(the bootstrap referee's); which targets a run serves (29s "Hedefler": ``loop.cek.targets`` and ``loop.job``).
"""

from __future__ import annotations

import os
import stat
from typing import Any

import cli
from ledger import chain
from loop import accepted as A

BOOTSTRAP = "bootstrap.json"
MAX_BOOTSTRAP = 1 << 20

SIGSTORE_PYTHON = ("sig", "bin", "python")  # under $RUNNER_TEMP
CLAUDE_CLI = ("control", "bootstrap", "requirements", "claude-cli", "node_modules", ".bin", "claude")

# tohum/29s "Sigstore" and "Kanaryanın claude CLI'si": each step's ``run``, byte for byte (``loop.job`` adds the
# name and the control gate).
SIGSTORE_RUN = (
    "set -eu\n"
    "cd \"$RUNNER_TEMP/control/bootstrap\"\n"
    "python3 -m venv \"$RUNNER_TEMP/sig\"\n"
    "\"$RUNNER_TEMP/sig/bin/pip\" download --quiet --require-hashes --only-binary=:all: --no-deps -d"
    " \"$RUNNER_TEMP/sigw\" -r requirements/sign.txt\n"
    "python3 -m snowball_bootstrap licenses --root .. --wheels \"$RUNNER_TEMP/sigw\"\n"
    "\"$RUNNER_TEMP/sig/bin/pip\" install --quiet --no-index --find-links \"$RUNNER_TEMP/sigw\" --require-hashes"
    " --only-binary=:all: --no-deps -r requirements/sign.txt\n")
CLAUDE_RUN = (
    "set -eu\n"
    "C=\"$RUNNER_TEMP/control/bootstrap/requirements/claude-cli\"\n"
    "node -e 'process.exit(Number(process.versions.node.split(\".\")[0]) >= 22 ? 0 : 1)'\n"
    "npm ci --prefix \"$C\" --no-audit --no-fund\n"
    "pinned=$(node -p \"require('$C/package.json').dependencies['@anthropic-ai/claude-code']\")\n"
    "test \"$(\"$C/node_modules/.bin/claude\" --version | cut -d' ' -f1)\" = \"$pinned\"\n")
STEPS = {"sigstore": SIGSTORE_RUN, "claude": CLAUDE_RUN}  # step name -> run


class InputError(Exception):
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


def _temp(environ: dict[str, str]) -> str:
    temp = environ.get("RUNNER_TEMP")
    if not temp or not os.path.isabs(temp):
        raise InputError("runner_temp_unset")
    return temp


def _bootstrap(workspace: str) -> dict[str, Any]:
    path = os.path.join(workspace, BOOTSTRAP)
    try:
        if not stat.S_ISREG(os.lstat(path).st_mode):
            raise InputError("bootstrap_unreadable")
        with open(path, "rb") as fh:
            data = fh.read(MAX_BOOTSTRAP + 1)
        if len(data) > MAX_BOOTSTRAP:
            raise InputError("bootstrap_unreadable")
        doc = cli.loads(data.decode("utf-8"), object_pairs_hook=chain._no_duplicates,
                         parse_constant=chain._no_constant)
    except (OSError, UnicodeDecodeError, ValueError, RecursionError):
        raise InputError("bootstrap_unreadable") from None
    if not isinstance(doc, dict):
        raise InputError("bootstrap_unreadable")
    return doc


def brain_repo(workspace: str) -> str:
    """``bootstrap.json``'s ``brain_repo`` (``owner/name``)."""
    try:
        return A.repo_name(_bootstrap(workspace).get("brain_repo"))
    except A.StateError:
        raise InputError("brain_repo_invalid") from None


def rival_model(workspace: str) -> str:
    """``bootstrap.json``'s ``rival.model``, a non-empty string."""
    rival = _bootstrap(workspace).get("rival")
    model = rival.get("model") if isinstance(rival, dict) else None
    if not (isinstance(model, str) and model.strip()):
        raise InputError("rival_model_invalid")
    return model


def sigstore(environ: dict[str, str]) -> tuple[str, ...]:
    """The Sigstore program's argv prefix, ``(<RUNNER_TEMP>/sig/bin/python, -m, sigstore)``."""
    python = os.path.join(_temp(environ), *SIGSTORE_PYTHON)
    if not os.path.isfile(python):
        raise InputError("sigstore_missing")
    return (python, "-m", "sigstore")


def claude(environ: dict[str, str]) -> str:
    """The canary's ``claude`` CLI, as the ``claude`` step installed it."""
    path = os.path.join(_temp(environ), *CLAUDE_CLI)
    if not os.path.isfile(path):
        raise InputError("claude_missing")
    return path
