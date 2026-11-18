"""``ledger.append``: a cycle's rows onto the chained ledger, one ``brain/state`` commit (stage 0, MF10).

Rules: asama-0/14 row 10, asama-0/09 test 39, tohum/29i (group ``append``), tohum/13 (chained ledgers, rows only
appended, the referee writes every row, one commit per cycle), tohum/26 (ledger row; a row carrying
``proposed_by`` is stored with ``trust: inferred``), tohum/01b (``brain/state``: checked before the commit,
a failed check writes nothing and stops hard), tohum/08 item 11 (every ledger row is scanned for secrets; a match
invalidates the run).

A cycle, in this order (``append_cycle``):

1. Before the rows are read: the ledger (the file at ``brain/state``'s head) is a valid chain and an
   append-only extension of ``previous`` (the last verified version), every earlier line byte for byte the
   same (``ledger.chain.verify_bytes``, the one verifier). Otherwise ``HardStop``: nothing is read or written,
   however unusable the request is. A line that is not a JSON object (a line cut while being written
   included) breaks the chain.
2. The request is ``{"rows": [row, ...]}`` and nothing else, at least one row; each row a JSON object
   without ``prev_hash`` or ``row_hash``, no duplicate key, no ``row_id`` that another new row or a ledger
   row already has (``Unusable`` otherwise). No other row schema is checked here (tohum/26's fields and
   closed sets are not enforced by this module).
3. Every new row, as given (escapes decoded), passes ``gate.secrets.match_lines`` in its ``row`` meaning;
   a match is ``SecretRow``: nothing is written, the run is invalid, not a hard stop.
4. A row with a top-level ``proposed_by`` key (any value, ``null`` included) is stored with ``trust: "inferred"``, whatever ``trust`` it had.
5. Rows are chained in request order onto the ledger's last row, whatever their ``part``; each stored line
   is the RFC 8785 form of the row with ``prev_hash`` and ``row_hash`` (``ledger.chain``). A row the
   canonical form cannot hold (a float, an integer outside I-JSON) is ``Unusable``.
6. The new file is the ledger's bytes, a newline if its last line had none, and the new lines. It is
   verified again as an append-only extension of the ledger (``HardStop`` if not), then handed to the
   state writer in one ``commit`` call: one commit per cycle.

State writers: ``CountingState`` counts commits and keeps the last commit's files, touching neither disk nor network
(the vector's writer, asama-0/14 "Kum"); ``TargetState`` commits the file through ``target.write``'s
``Writer.commit_files`` on ``brain/state`` at the head the ledger was read from. Both also take
``commit_files(files, message)``: one commit of several files (``ledger.cycle`` adds the root
file). Reading ``brain/state`` is the caller's job (the ``yaz`` job's checkout); this module never reads the target.

Command line (tohum/29i), run from ``referee/``, one JSON line on stdout, the cause on stderr::

    python -m ledger.append cycle LEDGER PREVIOUS      stdin {"rows": [...]}
        -> {ok, row_hashes: [stored rows' row_hash, request order], commits, hard_stop}
        refused: row_hashes [], commits 0
        exit 0 written; 1 refused (hard stop or secret); 2 unusable: a file that cannot be read, or, once
        step 1 holds, a request that step 2 or 5 refuses.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from typing import Any, Callable

from gate import secrets
from ledger import chain
from target import branches
import cli

STATE_BRANCH = branches.STATE


class HardStop(Exception):
    """The ledger is not a valid chain extending the previous version: nothing is written."""


class Unusable(ValueError):
    pass


class SecretRow(Exception):
    """A new row holds a secret: nothing is written and the run is invalid."""

    def __init__(self, rows: list[int]):
        super().__init__("secret in new row(s) %s" % rows)
        self.rows = rows


# ---------------------------------------------------------------- the cycle

def _ledger_rows(data: bytes) -> list[dict]:
    return [chain.parse_row(line.decode("utf-8")) for line in chain._lines(data)]


def _request_rows(raw: bytes, taken: set) -> list[dict]:
    try:
        request = chain.parse_row(raw.decode("utf-8"))
    except (UnicodeDecodeError, chain.ChainError) as exc:
        raise Unusable("request: %s" % cli.cause(exc)) from None
    if set(request) != {"rows"} or not isinstance(request["rows"], list) or not request["rows"]:
        raise Unusable('request must be {"rows": [row, ...]} with at least one row')
    ids = set(taken)
    for i, row in enumerate(request["rows"], 1):
        if not isinstance(row, dict):
            raise Unusable("row %d is not a JSON object" % i)
        if "prev_hash" in row or "row_hash" in row:
            raise Unusable("row %d carries prev_hash or row_hash; the chain is written here" % i)
        if "row_id" in row:
            key = json.dumps(row["row_id"], sort_keys=True)
            if key in ids:
                raise Unusable("row %d repeats row_id %s" % (i, key))
            ids.add(key)
    return request["rows"]


def _scan(rows: list[dict]) -> None:
    text = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows).encode("utf-8")
    try:
        found = secrets.match_lines(text, "row")
    except secrets.ScanError as exc:
        raise Unusable("rows cannot be scanned: %s" % cli.cause(exc)) from None
    if found:
        raise SecretRow(found)


def _chained(rows: list[dict], tip: str) -> tuple[list[bytes], list[str]]:
    lines, hashes = [], []
    for row in rows:
        stored = dict(row)
        if "proposed_by" in stored:
            stored["trust"] = "inferred"
        stored["prev_hash"] = tip
        try:
            stored["row_hash"] = tip = chain.row_hash(stored)
            lines.append(chain.canonical(stored))
        except chain.ChainError as exc:
            raise Unusable("row %s: %s" % (len(lines) + 1, cli.cause(exc))) from None
        hashes.append(tip)
    return lines, hashes


@dataclass
class Cycle:
    content: bytes
    row_hashes: list[str]


def plan_cycle(ledger: bytes, previous: bytes, read_request: Callable[[], bytes]) -> Cycle:
    """Steps 1-6 up to the commit: the new ledger file and the stored rows' hashes. ``read_request`` is
    called only after step 1 holds."""
    verdict = chain.verify_bytes(ledger, previous)
    if not verdict["valid"]:
        raise HardStop("ledger: %s (%s)" % (verdict["reason"], verdict["broken_row"]))
    old = _ledger_rows(ledger)
    taken = {json.dumps(r["row_id"], sort_keys=True) for r in old if "row_id" in r}
    rows = _request_rows(read_request(), taken)
    _scan(rows)
    lines, hashes = _chained(rows, old[-1]["row_hash"] if old else chain.ZERO_HASH)
    joint = b"\n" if ledger and not ledger.endswith(b"\n") else b""
    content = ledger + joint + b"".join(line + b"\n" for line in lines)
    after = chain.verify_bytes(content, ledger)
    if not after["valid"]:
        raise HardStop("new ledger: %s (%s)" % (after["reason"], after["broken_row"]))
    return Cycle(content, hashes)


def append_cycle(ledger: bytes, previous: bytes, read_request: Callable[[], bytes], state: Any,
                 message: str = "ledger: one cycle") -> list[str]:
    """Plan the cycle and commit it with ``state.commit(content, message)``, once; return the row hashes."""
    cycle = plan_cycle(ledger, previous, read_request)
    state.commit(cycle.content, message)
    return cycle.row_hashes


# ---------------------------------------------------------------- state writers

@dataclass
class CountingState:
    """The vector's writer: counts commits, keeps the last commit's files, touches no disk and no network."""

    commits: int = 0
    files: dict | None = None
    path: str = branches.STATE_LEDGER

    @property
    def content(self) -> bytes | None:
        return None if self.files is None else self.files.get(self.path)

    def commit(self, content: bytes, message: str) -> None:
        self.commit_files({self.path: content}, message)

    def commit_files(self, files: dict[str, bytes], message: str) -> None:
        self.commits += 1
        self.files = dict(files)


@dataclass
class TargetState:
    """``brain/state`` on the target through ``target.write``: one commit setting the files on ``head``."""

    writer: Any
    head: str
    path: str = branches.STATE_LEDGER
    branch: str = STATE_BRANCH
    commits_made: list[str] = field(default_factory=list)

    def commit(self, content: bytes, message: str) -> None:
        self.commit_files({self.path: content}, message)

    def commit_files(self, files: dict[str, bytes], message: str) -> None:
        self.commits_made.append(self.writer.commit_files(self.branch, self.head, files, message))


# ---------------------------------------------------------------- command line

USAGE = "usage: python -m ledger.append cycle LEDGER PREVIOUS < request"


def _emit(ok: bool, hashes: list[str], commits: int, hard_stop: bool) -> None:
    sys.stdout.write(json.dumps({"ok": ok, "row_hashes": hashes, "commits": commits, "hard_stop": hard_stop},
                                sort_keys=True) + "\n")


def main(argv: list[str]) -> int:
    try:
        if len(argv) != 3 or argv[0] != "cycle":
            raise Unusable(USAGE)
        files = []
        for path in argv[1:]:
            with open(path, "rb") as fh:
                files.append(fh.read())
        state = CountingState()
        hashes = append_cycle(files[0], files[1], sys.stdin.buffer.read, state)
        _emit(True, hashes, state.commits, False)
        return 0
    except HardStop as exc:
        sys.stderr.write("hard stop: %s\n" % cli.cause(exc))
        _emit(False, [], 0, True)
        return 1
    except SecretRow as exc:
        sys.stderr.write("run invalid: %s\n" % cli.cause(exc))
        _emit(False, [], 0, False)
        return 1
    except (Unusable, OSError) as exc:
        sys.stderr.write("unusable input: %s\n" % cli.cause(exc))
    _emit(False, [], 0, False)
    return 2


FAULT_LINE = {"ok": False, "error": "internal error"}  # not row_hashes [] and commits 0: a fault cannot say what was committed


if __name__ == "__main__":
    sys.exit(cli.run(main, sys.argv[1:], FAULT_LINE))
