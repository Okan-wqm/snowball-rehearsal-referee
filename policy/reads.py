"""The one reader of ``policy.json``'s values for the loop, and the command that names what it reads (tohum/29v).

Why one place: before this module five modules each walked the parsed policy with their own ``get`` calls
(``runner.deps_npm``, ``profile.derive``, ``profile.unit_verify`` in three places, ``dispatcher.llm_call``,
``loop.cagir``'s path), so "which values does the loop read, and from which path" had no single answer and the
command of tohum/29v would have been a second, hand-kept list beside them. Now the paths are constants here, the
modules read through ``at`` and ``operating``, and the command prints ``at`` over the same constants.

Rules (each bound by a test in ``tests/test_policy_reads.py``):

1. ``PATHS``: the full path, section first (tohum/29v "Yol"), of every value read through this module: the four
   ``constitutional`` paths below and ``("operating", name)`` for each of ``OPERATING_NAMES``. No path key holds a
   ``.``, so the dotted names of the command are distinct.
2. ``at(policy, path)``: the value at ``path`` walked from the root, one key at a time; ``ABSENT`` when a key on the
   way is not there. Nothing else is looked at: a key of the same name at the root or in another section is not
   read (tohum/29v: it is not that key). ``Malformed`` when ``policy``, or a value on the way before the last
   key, is not an object. A JSON ``null`` at the path is returned as ``None``, which is not ``ABSENT``.
3. ``operating(policy)``: what a reader of limits is given: ``None`` when ``policy`` is not an object or has no
   ``operating`` key; otherwise a new object holding, for each of ``OPERATING_NAMES`` present, ``at``'s value of its
   path (``Malformed`` when ``operating`` is not an object). A key of ``operating`` outside ``OPERATING_NAMES`` is
   not in it, so no reader downstream can read one.
4. The readers: ``runner.deps_npm`` (``LICENSE_ALLOWLIST``, ``LICENSE_EXCEPTIONS``, ``("operating",
   "deps_bytes")``), ``profile.derive`` (``SECURITY_KEYWORDS``), ``profile.unit_verify`` (``operating``; from it
   ``runner.contained`` and ``runner.kos`` get their limits), ``dispatcher.llm_call.policy_usd`` (the path its
   caller names; ``loop.cagir`` and ``loop.write_cycle`` name ``CANARY_USD``). ``tests/test_policy_reads.py``'s
   ``Readers`` runs each of these functions on a policy that records every key looked up in it and finds no
   lookup off ``PATHS``; and its register finds the section names as string constants in no other source file.

Outside, stated: what a reader does with the value (its type checks, its default when ``ABSENT``, the band rule of
``runner.contained.limits``) is the reader's; the bytes of ``policy.json`` hashed whole (``activate``'s
``policy_sha256``) are no value read; ``Readers`` shows the functions it runs on the inputs it gives them, not
every path through the loop (a new reader that walks the policy itself without the section names, on a call
``Readers`` does not make, is not seen).

Command line (tohum/29v), run from ``referee/``::

    python -m policy.reads FILE

One JSON line: an object whose names are ``PATHS`` dotted and whose values are ``at``'s over ``FILE`` (``null``
for ``ABSENT``; a ``null`` in the file prints the same, the interface has one word for both). Exit 0. Exit 2 with
``{"ok": false, "error": ...}``: wrong arguments, a file that cannot be read or is not one JSON object without a
repeated key and without ``NaN`` or an infinity (``ledger.chain``'s two hooks; ``cli.loads``' depth bound
included), or ``Malformed``.
"""

from __future__ import annotations

import json
import sys
from typing import Any

import cli
from ledger import chain

CONSTITUTIONAL = "constitutional"
LICENSE_ALLOWLIST = (CONSTITUTIONAL, "license_allowlist")
LICENSE_EXCEPTIONS = (CONSTITUTIONAL, "license_exceptions")
SECURITY_KEYWORDS = (CONSTITUTIONAL, "security_keywords")
CANARY_USD = (CONSTITUTIONAL, "stage_budgets", "asama_0", "canary_usd")
OPERATING = "operating"
OPERATING_NAMES = ("unit_inputs_bytes", "deps_bytes", "worktree_bytes", "container_mem_bytes", "kos_wall_s",
                   "test_total_s", "output_bytes")
PATHS = (LICENSE_ALLOWLIST, LICENSE_EXCEPTIONS, SECURITY_KEYWORDS, CANARY_USD) + tuple(
    (OPERATING, name) for name in OPERATING_NAMES)


class _Absent:
    def __repr__(self) -> str:
        return "ABSENT"


ABSENT: Any = _Absent()


class Malformed(ValueError):
    """``policy``, or a value on the way to a path, is not an object."""


def dotted(path: tuple[str, ...]) -> str:
    return ".".join(path)


def at(policy: Any, path: tuple[str, ...]) -> Any:
    """The value at ``path`` from the root, ``ABSENT`` or ``Malformed`` (rule 2)."""
    node = policy
    for depth, key in enumerate(path):
        if not isinstance(node, dict):
            raise Malformed("policy%s is not an object" % "".join(".%s" % k for k in path[:depth]))
        if key not in node:
            return ABSENT
        node = node[key]
    return node


def operating(policy: Any) -> dict | None:
    """The ``operating`` entries a reader of limits is given (rule 3)."""
    if not isinstance(policy, dict) or OPERATING not in policy:
        return None
    found = {name: at(policy, (OPERATING, name)) for name in OPERATING_NAMES}
    return {name: value for name, value in found.items() if value is not ABSENT}


def named(policy: Any) -> dict:
    """The command's object: every path of ``PATHS`` dotted, with ``at``'s value (``None`` for ``ABSENT``)."""
    values = {dotted(path): at(policy, path) for path in PATHS}
    return {name: None if value is ABSENT else value for name, value in values.items()}


def _refuse(message: str) -> int:
    sys.stdout.write(json.dumps({"ok": False, "error": message}) + "\n")
    return 2


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        return _refuse("usage: python -m policy.reads FILE")
    try:
        with open(argv[0], "rb") as fh:
            policy = cli.loads(fh.read().decode("utf-8"), object_pairs_hook=chain._no_duplicates,
                               parse_constant=chain._no_constant)
        out = named(policy)
    except (OSError, UnicodeDecodeError, ValueError, RecursionError) as exc:
        return _refuse("unusable input: %s" % cli.cause(exc))
    sys.stdout.write(json.dumps(out, sort_keys=True) + "\n")
    return 0


FAULT_LINE = {"ok": False, "error": "internal error"}


if __name__ == "__main__":
    sys.exit(cli.run(main, sys.argv[1:], FAULT_LINE))
