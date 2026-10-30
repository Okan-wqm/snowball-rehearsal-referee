"""MF10 ledger.append: one brain/state commit per cycle; verify --previous before writing; rows pass MF2
(asama-0/14:37, tohum/26a:28, tohum/13:43-46, tohum/01b:26-32).

    python -m ledger.append cycle <ledger.jsonl> <previous.jsonl>   (stdin: {"rows": [row, ...]})
        -> {"ok", "row_hashes", "commits", "hard_stop"}

Steps: (1) before the request is read, the ledger is a valid chain and extends the previous version byte for
byte, else hard stop; a ledger that is not JSON Lines is not a valid chain (tohum/29i, E238); (2) every new row
is scanned with secrets.scan's row semantics, a match invalidates the run (no hard stop); (3) a row with
proposed_by is stored with trust inferred; (4) rows chain in stdin order onto the last row; (5) one brain/state
commit through the writer (a fake that counts commits here).
"""

from __future__ import annotations

import json
import sys
from typing import Any, NoReturn

from gate import secrets
from ledger import _strict as chain  # A's helpers; this brain's MF1 `ledger.chain` has another interface
from ledger._strict import Unusable


class CountingWriter:
    """The brain/state writer of the cycle; this fake keeps the new file in memory and counts commits."""

    def __init__(self) -> None:
        self.commits = 0
        self.content = b""

    def commit(self, content: bytes) -> None:
        self.content = content
        self.commits += 1


def _emit(obj: dict[str, Any], code: int) -> NoReturn:
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()
    sys.exit(code)


def _refused(hard_stop: bool, why: str) -> NoReturn:
    _emit({"ok": False, "row_hashes": [], "commits": 0, "hard_stop": hard_stop, "reason": why}, 1)


def _verified(ledger_bytes: bytes, previous_bytes: bytes) -> list[dict[str, Any]]:
    """(1) The ledger is a valid chain and an append-only extension of the previous version, every previous line
    byte-identical in place; otherwise hard stop. A line that is not a JSON object is a broken chain, not unusable
    input; the previous version is compared as bytes only."""
    try:
        _, cur_rows = chain.read_jsonl(ledger_bytes)
    except Unusable as exc:
        _refused(True, f"ledger is not JSON Lines: {exc}")
    broken = chain.first_broken(cur_rows)
    if broken is not None:
        _refused(True, f"chain broken at line {broken + 1}")
    moved = chain.first_not_in_place(chain.split_lines(previous_bytes), chain.split_lines(ledger_bytes))
    if moved is not None:
        _refused(True, f"previous line {moved + 1} not in place")
    return cur_rows


def _request(stdin: bytes, cur_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    request = chain.loads(stdin)
    if not (isinstance(request, dict) and isinstance(request.get("rows"), list)
            and all(isinstance(row, dict) for row in request["rows"])):
        raise Unusable("stdin is not {rows: [row, ...]}")
    rows: list[dict[str, Any]] = request["rows"]
    ids = []
    for row in rows:
        if "prev_hash" in row or "row_hash" in row:
            raise Unusable("a new row carries prev_hash or row_hash")
        if not isinstance(row.get("row_id"), str):
            raise Unusable("a new row has no string row_id")
        chain.canonical(row)  # hashable: no float, no lone surrogate
        ids.append(row["row_id"])
    if len(set(ids)) != len(ids):
        raise Unusable("duplicate row_id among the new rows")
    if set(ids) & {r.get("row_id") for r in cur_rows}:
        raise Unusable("a new row_id is already in the ledger")
    return rows


def cycle(ledger_bytes: bytes, previous_bytes: bytes, stdin: bytes, writer: CountingWriter) -> list[str]:
    cur_rows = _verified(ledger_bytes, previous_bytes)  # (1) first: tamper evidence stops hard whatever is asked
    rows = _request(stdin, cur_rows)

    # (2) secrets
    if any(secrets.scan_rows(json.dumps(row)) for row in rows):  # this brain's MF2, row semantics (29f)
        _refused(False, "secret in a new row: run invalid")

    # (3) + (4)
    prev = cur_rows[-1]["row_hash"] if cur_rows else chain.ZERO
    stored, hashes = [], []
    for row in rows:
        new = dict(row)
        if "proposed_by" in new:
            new["trust"] = "inferred"
        new["prev_hash"] = prev
        new["row_hash"] = chain.row_hash(new)
        prev = new["row_hash"]
        stored.append(new)
        hashes.append(new["row_hash"])

    # (5) one commit for the whole cycle
    if stored:
        tail = b"".join(json.dumps(row, separators=(",", ":"), ensure_ascii=False).encode("utf-8") + b"\n"
                        for row in stored)
        body = ledger_bytes if ledger_bytes.endswith(b"\n") or not ledger_bytes else ledger_bytes + b"\n"
        writer.commit(body + tail)
    return hashes


def main(argv: list[str]) -> None:
    if len(argv) != 3 or argv[0] != "cycle":
        _emit({"ok": False, "row_hashes": [], "commits": 0, "hard_stop": False,
               "error": "usage: cycle <ledger.jsonl> <previous.jsonl>"}, 2)
    writer = CountingWriter()
    try:
        with open(argv[1], "rb") as fh:
            ledger_bytes = fh.read()
        with open(argv[2], "rb") as fh:
            previous_bytes = fh.read()
        hashes = cycle(ledger_bytes, previous_bytes, sys.stdin.buffer.read(), writer)
    except (OSError, Unusable) as exc:
        _emit({"ok": False, "row_hashes": [], "commits": 0, "hard_stop": False, "error": str(exc)}, 2)
    _emit({"ok": True, "row_hashes": hashes, "commits": writer.commits, "hard_stop": False}, 0)


if __name__ == "__main__":
    main(sys.argv[1:])
