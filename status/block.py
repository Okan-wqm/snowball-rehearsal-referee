"""``status.block``, the smallest one: the block of ``status.md`` produced from the ledger; a hand edit of it is
regenerated in the next cycle and written to ``events`` (stage 0, MF16).

Rules: tohum/29n (``status``: the fields, the block's markers and bytes, the edit rule, the rows, the exits),
asama-0/14 row 16, asama-0/09 test 42, tohum/26a (``status.block``: reads the ledger, writes the block of
``status.md`` on ``brain/state``), tohum/15 and tohum/01b (the block is written only by ``status.block``), tohum/26c
and tohum/27 (``setup/imports.jsonl`` is the human touch counter). Calls 10 -> 16: the rows and the file go into the
cycle's one ``brain/state`` commit through ``ledger.cycle`` (which chains them with ``ledger.append``).

**Fields** (``fields``), from the ledger's rows and ``imports.jsonl``'s alone; an ``events`` row is one with
``part: events``:

- ``cycle_id``: ``payload.cycle_id`` of the last ``events`` row of kind ``cycle_start`` (null when none);
- ``last_decision``: ``payload.decision`` of the last ``events`` row of kind ``decision`` (null when none); a later
  ``events`` row of another kind does not replace it;
- ``base_age_s``: ts(the last ``cycle_start``) - ts(the first ``events`` row of kind ``genesis``) in seconds, ts
  ``YYYY-MM-DDTHH:MM:SSZ`` (UTC); null when either row is missing; a negative difference is written as it is;
- ``brake``: ``{spent_usd_micros, cap_usd_micros, engaged}``: spent is ``dispatcher.llm_call.spent_micros`` (the sum
  of ``payload.usd_micros`` over every ``part: cost`` row, the one rule ``llm.call``'s brake uses), cap the stage's
  canary cap given on stdin, ``engaged`` iff spent >= cap;
- ``human_touches``: the number of ``imports.jsonl`` rows; every row is one touch, a transfer or not.

**The block** is the bytes from the one after the LF of the line that is exactly ``OPEN`` up to the first byte of
the next line that is exactly ``CLOSE``: no marker byte, its last line with its LF. ``status.md`` without an ``OPEN``
line has no block (``found_sha256`` null); two ``OPEN`` lines, or an ``OPEN`` with no ``CLOSE`` after it, are
unusable. The rest of the file is ``docs.render``'s and is never read here.

**Edits.** Every cycle records the block it writes as an ``events`` row of kind ``status``, ``payload
{block_sha256}``. ``recorded_sha256`` is the last such row's, or null; ``edited`` iff ``found_sha256 !=
recorded_sha256`` (both null, the first cycle, is no edit; a deleted block with a recorded one is). An edit is
the event ``{kind: status_edited, payload: {found_sha256, recorded_sha256}}``.

**The view** (``render_block``) is the Founder's (test 42; the seed compares neither its bytes nor their hash): one
line per field, every value written as JSON with every non-ASCII character and ``<``, ``>``, ``&``, `````, ``|``,
``[``, ``]``, ``@`` as ``\\uXXXX``, so a value cannot add a line (so not a marker line), HTML, a link, a mention or
a code span.

**Render** (``render``) reads and writes nothing else: it does not verify the ledger or ``imports.jsonl`` as chains
(``ledger.append`` does, tohum/29i). **The cycle** (``plan``): the ledger must be a valid chain
extending ``previous`` (``ledger.append.HardStop`` otherwise, before anything else is read); the cycle's own rows
count as the ledger's last rows; the new ``status.md`` is the old one with the block replaced (``regenerate``), or
the markers and the block followed by the old file when it had no block; the rows appended after the cycle's are a
``status_edited`` row (when edited) and the ``status`` row. ``plan`` writes nothing: ``ledger.cycle`` chains its rows
(``ledger.append``) and commits ``status.md`` with the ledger and the signed root in the cycle's one commit.

Out of scope here, stated: the other lines of tohum/20's top section, tohum/07's ``main`` commits since the cut (no
stage 0 producer, asama-0/01:37), who writes ``cycle_start`` and ``decision`` rows (the cycle and the gate; this
module only reads them), human touches outside ``imports.jsonl`` that no one writes there, and what lies outside
the block (``docs.render``, stage 1). A hand edit is regenerated, not refused (tohum/15:16 and 01b:37 call it a
broken chain and a rejection; the owner decides, tohum/29n).

Command line, run from ``referee/``, one JSON line on stdout, the cause of an error on stderr::

    python -m status.block render LEDGER IMPORTS STATUS   stdin {"canary_cap_usd_micros": integer}
        -> {cycle_id, last_decision, base_age_s, brake, human_touches, edited, event, block, block_sha256}
        exit 0 not edited; 1 edited; 2 an unreadable file, a line that is not a JSON object, a malformed ts in a
        row used, a cost row without an integer usd_micros, a cap that is not an integer, a marker error
        ({"edited": null}).
"""

from __future__ import annotations

import calendar
import hashlib
import json
import re
import sys
import time
from typing import Any

from dispatcher import llm_call
from ledger import append, chain
from target import branches
import cli

STATUS_PATH = branches.STATE_STATUS
OPEN = b"<!-- status.block -->"
CLOSE = b"<!-- /status.block -->"
PART = "events"
KIND = "status"
EDITED = "status_edited"
START = "cycle_start"
DECISION = "decision"
GENESIS = "genesis"
FACTS = {"ts", "snapshot_id", "row_id", "canary_cap_usd_micros"}
TS = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z\Z")
ESCAPED = {c: "\\u%04x" % ord(c) for c in "<>&`|[]@"}


class Unusable(ValueError):
    pass


# ---------------------------------------------------------------- inputs

def _count(value: Any, what: str) -> int:
    if type(value) is not int or not 0 <= value <= chain.MAX_SAFE_INT:
        raise Unusable("%s must be an integer >= 0" % what)
    return value


def seconds(ts: Any, what: str) -> int:
    """``YYYY-MM-DDTHH:MM:SSZ`` as seconds since the epoch; ``Unusable`` for any other form or an invalid date."""
    if not isinstance(ts, str) or not TS.match(ts):
        raise Unusable("%s must be YYYY-MM-DDTHH:MM:SSZ" % what)
    try:
        return calendar.timegm(time.strptime(ts, "%Y-%m-%dT%H:%M:%SZ"))
    except ValueError:
        raise Unusable("%s is not a valid time" % what) from None


def rows_of(data: bytes, what: str) -> list[dict]:
    """The JSON object lines of a JSONL file (no chain check); ``Unusable`` for any other line."""
    try:
        return [chain.parse_row(line.decode("utf-8")) for line in chain._lines(data)]
    except (chain.ChainError, UnicodeDecodeError) as exc:
        raise Unusable("%s: %s" % (what, cli.cause(exc))) from None


def _events(rows: list[dict], kind: str) -> list[dict]:
    return [row for row in rows if row.get("part") == PART and row.get("kind") == kind]


def _payload(row: dict | None, key: str) -> Any:
    payload = row.get("payload") if row is not None else None
    return payload.get(key) if isinstance(payload, dict) else None


# ---------------------------------------------------------------- fields and edits

def fields(rows: list[dict], imports: list[dict], cap: Any) -> dict:
    """The five fields (see the module docstring) over ``rows``, the ledger's rows in file order."""
    cap = _count(cap, "canary_cap_usd_micros")
    starts, decisions, origins = _events(rows, START), _events(rows, DECISION), _events(rows, GENESIS)
    start = starts[-1] if starts else None
    age = None
    if start is not None and origins:
        age = seconds(start.get("ts"), "the last cycle_start row's ts") - seconds(
            origins[0].get("ts"), "the first genesis row's ts")
    try:
        spent = llm_call.spent_micros(rows)
    except llm_call.Unusable as exc:
        raise Unusable(cli.cause(exc)) from None
    return {"cycle_id": _payload(start, "cycle_id"),
            "last_decision": _payload(decisions[-1], "decision") if decisions else None,
            "base_age_s": age,
            "brake": {"spent_usd_micros": spent, "cap_usd_micros": cap, "engaged": spent >= cap},
            "human_touches": len(imports)}


def split(status: bytes) -> tuple[bytes, bytes, bytes] | None:
    """``status.md`` as (through the ``OPEN`` line, the block, from the ``CLOSE`` line on), or None without an
    ``OPEN`` line; ``Unusable`` for two ``OPEN`` lines or an ``OPEN`` with no ``CLOSE`` after it."""
    lines = status.split(b"\n")
    starts, at = [], 0
    for line in lines:
        starts.append(at)
        at += len(line) + 1
    opens = [i for i, line in enumerate(lines) if line == OPEN and starts[i] + len(line) < len(status)]
    if [i for i, line in enumerate(lines) if line == OPEN] != opens:
        raise Unusable("status.md: an OPEN line without its LF")
    if not opens:
        return None
    if len(opens) > 1:
        raise Unusable("status.md: two OPEN lines")
    first = opens[0]
    close = next((i for i in range(first + 1, len(lines)) if lines[i] == CLOSE), None)
    if close is None:
        raise Unusable("status.md: OPEN with no CLOSE after it")
    body_start, body_end = starts[first + 1], starts[close]
    return status[:body_start], status[body_start:body_end], status[body_end:]


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def edit(rows: list[dict], status: bytes) -> dict:
    """``{found_sha256, recorded_sha256, edited, event}`` (see the module docstring)."""
    parts = split(status)
    found = None if parts is None else _sha(parts[1])
    recorded = _events(rows, KIND)
    recorded_sha = _payload(recorded[-1], "block_sha256") if recorded else None
    edited = found != recorded_sha
    event = {"kind": EDITED, "payload": {"found_sha256": found, "recorded_sha256": recorded_sha}} if edited else None
    return {"found_sha256": found, "recorded_sha256": recorded_sha, "edited": edited, "event": event}


# ---------------------------------------------------------------- the block

def show(value: Any) -> str:
    """A value as inert JSON text: no line break, no non-ASCII, none of ``ESCAPED``'s characters."""
    text = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(", ", ": "))
    return "".join(ESCAPED.get(c, c) for c in text)


def render_block(f: dict) -> bytes:
    brake = f["brake"]
    lines = ["## Status", "",
             "Written by the referee's status.block from the ledger. A hand edit of this block is replaced in the",
             "next cycle and recorded as a status_edited event.", "",
             "- Cycle: %s" % show(f["cycle_id"]),
             "- Last decision: %s" % show(f["last_decision"]),
             "- Base age: %s s since genesis" % show(f["base_age_s"]),
             "- Brake: %s, %d of %d micro-USD spent" % ("engaged" if brake["engaged"] else "released",
                                                      brake["spent_usd_micros"], brake["cap_usd_micros"]),
             "- Human touches: %d" % f["human_touches"]]
    return ("\n".join(lines) + "\n").encode("ascii")


def regenerate(status: bytes | None, block: bytes) -> bytes:
    """The new ``status.md``: the block replaced between the markers, or the markers and the block before the old
    file when it has none."""
    parts = split(status) if status is not None else None
    if parts is None:
        return OPEN + b"\n" + block + CLOSE + b"\n" + (status or b"")
    return parts[0] + block + parts[2]


def render(ledger: bytes, imports: bytes, status: bytes, cap: Any) -> dict:
    """The command's output (see the module docstring); writes nothing."""
    rows = rows_of(ledger, "ledger")
    f = fields(rows, rows_of(imports, "imports.jsonl"), cap)
    e = edit(rows, status)
    block = render_block(f)
    return dict(f, edited=e["edited"], event=e["event"], block=block.decode("ascii"), block_sha256=_sha(block))


# ---------------------------------------------------------------- the cycle

def _facts(facts: Any) -> dict:
    if not isinstance(facts, dict) or set(facts) != FACTS:
        raise Unusable("facts must be exactly {%s}" % ", ".join(sorted(FACTS)))
    for name in ("snapshot_id", "row_id"):
        if not isinstance(facts[name], str) or not facts[name]:
            raise Unusable("%s must be a non-empty string" % name)
    seconds(facts["ts"], "facts.ts")
    _count(facts["canary_cap_usd_micros"], "canary_cap_usd_micros")
    return facts


def plan(ledger: bytes, previous: bytes, rows: Any, status: bytes | None, imports: bytes, facts: Any) -> dict:
    """The cycle's status: ``render``'s fields plus ``{status, rows}``, where ``rows`` are the given rows followed by
    this module's rows and ``status`` the new ``status.md``. Writes nothing."""
    verdict = chain.verify_bytes(ledger, previous)
    if not verdict["valid"]:
        raise append.HardStop("ledger: %s (%s)" % (verdict["reason"], verdict["broken_row"]))
    facts = _facts(facts)
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        raise Unusable("rows must be a list of JSON objects")
    every = rows_of(ledger, "ledger") + rows
    f = fields(every, rows_of(imports, "imports.jsonl"), facts["canary_cap_usd_micros"])
    e = edit(every, status if status is not None else b"")
    block = render_block(f)
    common = {"part": PART, "ts": facts["ts"], "derivation": "tool", "trust": "verified",
              "snapshot_id": facts["snapshot_id"], "evidence_refs": []}
    new = []
    if e["edited"]:
        new.append(dict(common, row_id=facts["row_id"] + ":edited", kind=EDITED, payload=e["event"]["payload"]))
    new.append(dict(common, row_id=facts["row_id"], kind=KIND, payload={"block_sha256": _sha(block)}))
    return dict(f, edited=e["edited"], event=e["event"], block=block, block_sha256=_sha(block),
                status=regenerate(status, block), rows=rows + new)


# ---------------------------------------------------------------- command line

USAGE = "usage: python -m status.block render LEDGER IMPORTS STATUS < {\"canary_cap_usd_micros\": integer}"


def _read(path: str) -> bytes:
    try:
        with open(path, "rb") as fh:
            return fh.read()
    except OSError as exc:
        raise Unusable("%s: %s" % (path, cli.cause(exc))) from None


def _emit(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj, sort_keys=True) + "\n")


def main(argv: list[str]) -> int:
    try:
        if len(argv) != 4 or argv[0] != "render":
            raise Unusable(USAGE)
        ledger, imports, status = (_read(path) for path in argv[1:])
        request = chain.parse_row(sys.stdin.buffer.read().decode("utf-8"))
        if set(request) != {"canary_cap_usd_micros"}:
            raise Unusable('stdin must be {"canary_cap_usd_micros"} and nothing else')
        out = render(ledger, imports, status, request["canary_cap_usd_micros"])
        _emit(out)
        return 1 if out["edited"] else 0
    except (Unusable, chain.ChainError, UnicodeDecodeError) as exc:
        sys.stderr.write("unusable input: %s\n" % cli.cause(exc))
    _emit({"edited": None})
    return 2


FAULT_LINE = {"edited": None}


if __name__ == "__main__":
    sys.exit(cli.run(main, sys.argv[1:], FAULT_LINE))
