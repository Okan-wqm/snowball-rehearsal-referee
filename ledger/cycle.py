"""The cycle's one ``brain/state`` commit: its rows, the ``status.md`` block and the signed root, planned in one place
(stage 0; calls 10 -> 11, 10 -> 16: D6 and the activation).

Rules: asama-0/01 D6 (``yaz`` writes one ``brain/state`` commit per cycle, the signed root and ``status.md``; the
chain is verified before the write), asama-0/14 rows 10, 11 and 16, tohum/13 (rows only appended; the root signed
in Rekor; a chain break or a root that cannot be signed is a hard stop), tohum/28 (hard stop), ``ledger.schema``
(the row types the loop writes, one table).

**Inputs** (``plan``): the ledger and the roots file at ``brain/state``'s head and their previous versions (the
versions the caller last verified: equal to the current ones when nothing was added since; ``b""`` for a target with
no ``brain/state`` yet, the activation's orphan commit), the head's ``status.md`` (``None`` when it has none), the
cycle's rows (JSON objects without ``prev_hash`` and ``row_hash``), ``setup/imports.jsonl``'s bytes, the status facts
``{ts, snapshot_id, row_id, canary_cap_usd_micros}`` (``status.block``'s), the signer and the root row's id.

**Order**, nothing signed or returned before every check holds:

1. the roots file is a valid chain and an append-only extension of its previous version, else ``HardStop`` before
   anything else is read (``ledger.chain``, the one verifier);
2. ``status.block.plan`` (the ledger an append-only extension of its previous version, else ``HardStop``; the facts;
   the block; the ``status`` row and, when the block was edited by hand, the ``status_edited`` row after the cycle's);
3. ``ledger.append.plan_cycle`` chains those rows (unique row ids, the secret scan: ``SecretRow``);
4. the whole new ledger conforms to ``ledger.schema`` (``ledger_reasons``: every row of a known type with its
   payload's shape, the old rows included: a loop ledger holds only rows the loop writes), else ``Unusable``;
5. the root row's id is new in the roots file and ``ts`` is a timestamp (``ledger.anchor.root_row_reasons``), else
   ``Unusable``, before the signer is asked;
6. the root of the new ledger (``ledger.anchor.root_of``) is signed (``ledger.anchor.anchor``: the tips' bytes, whose
   sha256 the root is; ``Unsignable``, a ``HardStop``, when it cannot be) and one chained root row is appended.

``plan`` returns ``{files, row_hashes, root, entry, block_sha256, edited}``. ``files`` maps paths of ``brain/state``'s
commit to bytes, all under the state directory (``target.branches.STATE_ROOT``, tohum/26d "Yer"): exactly
``.brain/ledger.jsonl``, ``.brain/chain/root.jsonl``, ``.brain/status.md`` and the new root's Sigstore bundle as the
signer gave it, ``.brain/chain/<root>.sigstore.json`` (``ledger.anchor.bundle_path``), beside the root row that names
that root. The bundles of earlier roots stay where their cycles wrote them. ``plan`` writes nothing. ``commit`` plans
and hands ``files`` to the state writer in one ``commit_files`` call (``ledger.append.CountingState`` or
``TargetState``): the cycle's one commit. The activation opens ``brain/state`` with ``plan``'s files as an orphan
commit (``target.write.Writer.open_orphan``).

Out of scope, stated: which rows a cycle writes (the caller's: ``activate`` and D6 of ``yaz``,
``loop.write_cycle``, both through ``ledger.events``); where ``status.md`` and the previous versions come from (the
caller's read of ``brain/state``: D6 takes them from ``pulled``, which D1 filled); the meaning of a row's values
(``ledger.schema`` checks shapes); what the bundle's bytes are (the signer's: ``loop.sign`` checks the real one
before it answers); a ``profile.json`` in the state directory (no module writes one).
"""

from __future__ import annotations

import json
from typing import Any

from ledger import anchor, append, chain, schema
from status import block


class Unusable(ValueError):
    pass


# Every exception ``plan`` raises for its inputs (``commit`` adds the state writer's): a caller that has written
# before planning names what it wrote when one of these is raised (``target.land.HardStop``).
FAILURES = (append.HardStop, append.SecretRow, append.Unusable, Unusable, block.Unusable, anchor.Unusable)


def plan(ledger: bytes, previous: bytes, roots: bytes, previous_roots: bytes, status: bytes | None, rows: Any,
         imports: bytes, facts: Any, signer: Any, root_row_id: str) -> dict[str, Any]:
    """The cycle's files and what they record; see the module docstring. Writes nothing."""
    verdict = chain.verify_bytes(roots, previous_roots)
    if not verdict["valid"]:
        raise append.HardStop("roots: %s (%s)" % (verdict["reason"], verdict["broken_row"]))
    planned = block.plan(ledger, previous, rows, status, imports, facts)
    request = json.dumps({"rows": planned["rows"]}, sort_keys=True).encode("utf-8")
    cycle = append.plan_cycle(ledger, previous, lambda: request)
    reasons = schema.ledger_reasons(cycle.content)
    if reasons:
        raise Unusable("ledger: %s" % "; ".join(reasons))
    ts = facts["ts"]  # status.block.plan checked the facts
    reasons = anchor.root_row_reasons(roots, root_row_id, ts)
    if reasons:
        raise Unusable("root row: %s" % "; ".join(reasons))
    tip_map = anchor.tips(cycle.content)
    root = anchor.root_of(tip_map)
    entry, bundle = anchor.anchor(tip_map, signer)
    files = {anchor.LEDGER_PATH: cycle.content, anchor.ROOTS_PATH: anchor.root_row(roots, root_row_id, ts, root,
                                                                                   entry["uuid"]),
             anchor.bundle_path(root): bundle, block.STATUS_PATH: planned["status"]}
    return {"files": files, "row_hashes": cycle.row_hashes, "root": root, "entry": entry,
            "block_sha256": planned["block_sha256"], "edited": planned["edited"]}


def commit(state: Any, message: str, ledger: bytes, previous: bytes, roots: bytes, previous_roots: bytes,
           status: bytes | None, rows: Any, imports: bytes, facts: Any, signer: Any, root_row_id: str) -> dict[str, Any]:
    """``plan`` and its files in one ``state.commit_files`` call; returns ``plan``'s result."""
    planned = plan(ledger, previous, roots, previous_roots, status, rows, imports, facts, signer, root_row_id)
    state.commit_files(planned["files"], message)
    return planned
