"""The target's ``brain/state`` at its head, its chained files verified against its previous version (``çek``, D1;
stage 0).

Rules: asama-0/01 D1 (``çek`` reads the target's ``brain/state`` head; among its checks MF1's ``verify
--previous``), tohum/01b (``brain/state``: one direct commit per cycle, written only by ``yaz``; ``chain/*`` and
``ledger.jsonl`` append only, the earlier lines byte for byte the same, the new lines chained), tohum/29i (the
ledger at ``brain/state``'s head is the previous, last verified version a cycle extends), ``target.branches``
(``STATE_CHAINS``, the files: ``ledger.jsonl`` and ``chain/root.jsonl`` under the commit's ``.brain/``; a reason
names the path in the commit), ``ledger.chain`` (MF1, the one verifier).

**Previous** (``parent``): a cycle writes one commit on ``brain/state`` on top of the head it verified, so the
previous version of the head's files is its parent's. A head with no parent (``activate``'s orphan genesis commit)
has no previous version: its files are verified as chains only. A head with more than one parent is
``state_merge``: no cycle writes one, and which parent is the previous would be a guess.

**Verify** (``verify``), for each file of ``STATE_CHAINS`` in that order; every reason that holds is listed
(``PulledError``):

- ``file_missing:<path>``: the head's tree has no file entry at the path (``loop.gitobj.lookup``: absent, a link,
  a tree, a gitlink; a link is never followed);
- ``chain_empty:<path>``: the file holds no row (``activate`` opens both with a row);
- ``chain_broken:<path>:<line>``: the file is not a valid chain (``ledger.chain.verify_bytes``), ``line`` the
  first broken line;
- with a parent: ``previous_missing:<path>`` (the parent's tree has no file entry there) and
  ``not_append_only:<path>:<line>`` (a line of the parent's file is not, byte for byte, the same line of the
  head's: changed, moved or gone), judged only on a file that is a valid chain;
- a git object reason of either commit (``loop.gitobj``: ``object_missing:<sha>``, ``commit_unreadable``, ...)
  as ``state:<reason>``.

On success: ``{"head", "previous" (the parent or ``None``), "rows" (path -> its number of rows)}``.

Out of scope, stated: whether the head is the commit the last cycle wrote and not one more pushed on top of it,
which is the root's question (MF11's ``ledger.anchor.judge`` of the ledger's root against the last row of
``chain/root.jsonl`` and its Rekor entry, run by the job on ``chains``' bytes after ``verify``); the other files
of ``brain/state`` (``profile.json``; the roots' Sigstore bundles under ``chain/``, which ``ledger.cycle`` writes
and the operator's ``stage-open`` reads: D1 reads the entry from Rekor, not the bundle in the commit, so a head
whose last root has no bundle file is not refused here; ``status.md`` is read by ``status`` as bytes, not verified:
D6's ``status.block.plan`` regenerates a block edited by hand and records it); the row payloads (``ledger.schema``'s); the reads themselves (the job's ``loop.fetch``). Both versions are held in memory.
"""

from __future__ import annotations

from typing import Any

from ledger import chain
from loop import gitobj as G
from loop.pulled import PulledError
from target import branches


def parent(source: G.Source, head: str) -> str | None:
    """The head's previous version (see the module): its one parent or ``None``; ``PulledError``."""
    try:
        found = G.parents(source, head)
    except PulledError as exc:
        raise PulledError(["state:%s" % r for r in exc.reasons]) from None
    if len(found) > 1:
        raise PulledError(["state_merge"])
    return found[0] if found else None


def _file(source: G.Source, commit: str, path: str) -> bytes | None:
    found = G.lookup(source, commit, path)
    return G.read(source, found[1], "blob") if found is not None and found[0] == "file" else None


def chains(source: G.Source, commit: str) -> dict[str, bytes | None]:
    """``commit``'s chained files (``STATE_CHAINS``), each its bytes or ``None`` where no file entry is; ``PulledError``
    for a git object reason, unmarked. Read by ``verify`` and by D1's root check (``loop.job``)."""
    return {path: _file(source, commit, path) for path in branches.STATE_CHAINS}


def status(source: G.Source, commit: str) -> bytes | None:
    """``commit``'s ``status.md`` (``target.branches.STATE_STATUS``): its bytes, or ``None`` where no file entry is
    (absent, a link, a tree, a gitlink); ``PulledError`` for a git object reason, unmarked. Read by D1 for D6."""
    return _file(source, commit, branches.STATE_STATUS)


def verify(source: G.Source, head: str, previous: G.Source | None = None, prev: str | None = None) -> dict[str, Any]:
    """``head``'s chained files from ``source``, each against ``prev``'s from ``previous`` when ``prev`` is given."""
    reasons: list[str] = []
    rows: dict[str, int] = {}
    for path in branches.STATE_CHAINS:
        try:
            data = _file(source, head, path)
            old = _file(previous, prev, path) if prev is not None else None
        except PulledError as exc:
            reasons += ["state:%s" % r for r in exc.reasons]
            continue
        if data is None:
            reasons.append("file_missing:%s" % path)
        if prev is not None and old is None:
            reasons.append("previous_missing:%s" % path)
        if data is None:
            continue
        verdict = chain.verify_bytes(data)
        if not verdict["valid"]:
            reasons.append("chain_broken:%s:%d" % (path, verdict["line"]))
            continue
        rows[path] = len(chain._lines(data))
        if not rows[path]:
            reasons.append("chain_empty:%s" % path)
        if old is not None:
            verdict = chain.verify_bytes(data, old)
            if not verdict["valid"]:
                reasons.append("not_append_only:%s:%d" % (path, verdict["line"]))
    if reasons:
        raise PulledError(list(dict.fromkeys(reasons)))
    return {"head": head, "previous": prev, "rows": rows}
