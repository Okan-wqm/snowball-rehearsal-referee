"""The Founder's ledger (`asama-0/10` #kurucu-defteri, `asama-0/09` test 30, `tohum/26`, `00a`; E107, E280).

`founder-ledger.jsonl` is chained with the seed's canonical code (`canon.row_hash`: ``sha256(canonical(row -
row_hash) || prev_hash)``, the first ``prev_hash`` 64 zeros) and only appended relative to the last accepted commit.
The referee checks it on every push it judges (`00a`): a spec or code push has the rows it adds checked, the exit the
whole file. Only bytes are read; nothing of the Founder's runs.

What the spec leaves open is chosen here (E280):
- "only appended" is a byte prefix: the last accepted commit's ledger bytes start the head's. A row whose keys were
  merely reordered is a changed row (E232 asks the same of MF1's ``verify --previous``; the referee reads the rule
  literally). A partial last line may only be closed by its newline.
- every row ends with a newline, so the next append never touches it; a row is one UTF-8 JSON object with no
  duplicate key (a later ``kind`` cannot hide an earlier one), no NaN or Infinity, at most ``MAX_DEPTH`` levels of
  objects and arrays, and nothing canonical JSON cannot hold (`tohum/26`: no floats).
- ``part`` is ``founder`` and ``kind`` is one of `tohum/26`'s founder kinds (test 30); ``supersedes``, when present,
  names an earlier row of the file that breaks one of these meaning rules (`26`, `13`). These are the ledger's
  structure; its content, the other fields of `26`, is not gated: it is the Founder's memory (`13`).
- a row the referee accepted is never rewritten. One that breaks a meaning rule (``MEANING_RULES``; a row accepted
  before the seed checked rows can) is closed by a later valid row that names its ``row_hash`` in
  ``supersedes`` (`13` "Kurucu defterinde kapatma", E280); the closing row may ride along with the exit request, and
  the exit names each closed row beside the row that closed it. Left unclosed it is ``founder_ledger_accepted_invalid``
  and the Founder's to fix (`29b` "Ret hafızası"). Broken bytes or a broken chain in an accepted row are tamper
  evidence (`13`): nothing appended closes them, so they are reported apart and never counted (`beyond_appending`).
  A row a push adds is judged as it is; no later row closes it. A missing final newline is the Founder's however old
  the line, as appending it is the fix.
"""

from __future__ import annotations

import json
import re
from typing import Any

from . import canon

FOUNDER_KINDS = ("session_start", "decision", "build", "blocked", "seed_issue", "cost", "session_end")
INVALID = "founder_ledger_invalid"
ACCEPTED_INVALID = "founder_ledger_accepted_invalid"
SUPERSEDES = "supersedes"
# The rules a row's meaning breaks, as against its bytes or its chain: an accepted row that breaks one of them is closed
# by a superseding row (`13`, E280). Every other rule is an integrity rule.
MEANING_RULES = ("part", "kind", SUPERSEDES)
ZERO = "0" * 64
HEX64_RE = re.compile(r"^[0-9a-f]{64}\Z")
MAX_DEPTH = 64
MAX_REASONS = 20


class _NotARow(ValueError):
    """Why one line is not a row; the message is the rule's name."""


def _unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    found: dict[str, Any] = {}
    for key, value in pairs:
        if key in found:
            raise _NotARow("duplicate_key")
        found[key] = value
    return found


def _no_constant(_name: str) -> Any:
    raise _NotARow("noncanonical")  # NaN, Infinity and -Infinity: no canonical form holds them


def _too_deep(value: Any) -> bool:
    stack = [(value, 1)]
    while stack:
        item, level = stack.pop()
        if level > MAX_DEPTH:
            return True
        children = item.values() if isinstance(item, dict) else item if isinstance(item, list) else ()
        stack += [(child, level + 1) for child in children if isinstance(child, (dict, list))]
    return False


def _row(line: bytes) -> dict[str, Any]:
    try:
        text = line.decode("utf-8")
    except UnicodeDecodeError:
        raise _NotARow("not_utf8") from None
    try:
        row = json.loads(text, object_pairs_hook=_unique, parse_constant=_no_constant)
    except _NotARow:
        raise
    except RecursionError:
        raise _NotARow("too_deep") from None
    except json.JSONDecodeError:
        raise _NotARow("not_json") from None
    except ValueError:  # an integer longer than Python reads
        raise _NotARow("noncanonical") from None
    if not isinstance(row, dict):
        raise _NotARow("not_json")
    if _too_deep(row):
        raise _NotARow("too_deep")
    try:
        canon.canonical(row)
    except canon.CanonicalError:
        raise _NotARow("noncanonical") from None
    return row


def _judge(line: bytes, prev: str | None, closable: dict[str, int]) -> tuple[str | None, str | None, int | None]:
    """(the first rule the line breaks or None, the ``row_hash`` the next row must name or None when unknown, the line
    a valid row closes or None). ``closable`` maps the ``row_hash`` of each earlier row that breaks a meaning rule to its
    line."""
    try:
        row = _row(line)
    except _NotARow as exc:
        return str(exc), None, None
    declared = row.get("row_hash")
    link = declared if isinstance(declared, str) and HEX64_RE.match(declared) else None
    given = row.get("prev_hash")
    if not isinstance(given, str) or not HEX64_RE.match(given) or (prev is not None and given != prev):
        return "prev_hash", link, None
    if canon.row_hash(row) != declared:
        return "row_hash", link, None
    if row.get("part") != "founder":
        return "part", link, None
    if row.get("kind") not in FOUNDER_KINDS:
        return "kind", link, None
    if SUPERSEDES not in row:
        return None, link, None
    target = row[SUPERSEDES]
    closes = closable.get(target) if isinstance(target, str) else None
    return (SUPERSEDES if closes is None else None), link, closes


def _line_of(data: bytes, offset: int) -> int:
    return data.count(b"\n", 0, offset) + 1


def judge(head: bytes | None, base: bytes | None, whole: bool) -> tuple[list[str], list[tuple[int, int]]]:
    """Why the head's ledger breaks the rule ([] when it keeps it), and at the exit each accepted row a later valid row
    closed, as (its line, the closing row's line).

    ``base`` is the ledger of the last accepted commit (None when it had none). ``whole`` is the exit's reading, every
    row; otherwise only the rows after the accepted ones are judged, the chain anchored on the last accepted row.
    """
    if head is None:
        if base is not None:
            return [f"{INVALID}:deleted"], []
        return ([f"{INVALID}:missing"] if whole else []), []
    accepted = base or b""
    if not head.startswith(accepted):
        cut = next((i for i, (a, b) in enumerate(zip(head, accepted)) if a != b), min(len(head), len(accepted)))
        rule = "truncated" if accepted.startswith(head) else "rewritten"
        return [f"{INVALID}:{rule}:L{_line_of(accepted, cut)}"], []
    if accepted and not accepted.endswith(b"\n") and head[len(accepted):len(accepted) + 1] not in (b"", b"\n"):
        return [f"{INVALID}:rewritten:L{_line_of(accepted, len(accepted))}"], []  # a partial line closed by more than \n
    lines = head.split(b"\n")
    terminated = lines[-1] == b""
    if terminated:
        lines.pop()
    if not lines:
        return ([f"{INVALID}:missing"] if whole else []), []
    kept = accepted.count(b"\n") + (1 if accepted and not accepted.endswith(b"\n") else 0)
    judged: list[tuple[int, str | None]] = []
    closable: dict[str, int] = {}
    closed_by: dict[int, int] = {}
    prev: str | None = ZERO
    for number, line in enumerate(lines, start=1):
        rule, prev, closes = _judge(line, prev, closable)
        if rule in MEANING_RULES and prev is not None:
            closable.setdefault(prev, number)
        if closes is not None:
            closed_by.setdefault(closes, number)
        judged.append((number, rule))
    reasons: list[str] = []
    closures: list[tuple[int, int]] = []
    for number, rule in judged:
        if rule is not None:
            if number > kept:
                reasons.append(f"{INVALID}:{rule}:L{number}")
            elif whole and rule in MEANING_RULES and number in closed_by:
                closures.append((number, closed_by[number]))
            elif whole:
                reasons.append(f"{ACCEPTED_INVALID}:{rule}:L{number}")
        if number == len(lines) and not terminated:
            reasons.append(f"{INVALID}:unterminated:L{number}")
    return reasons[:MAX_REASONS], closures[:MAX_REASONS]


def check(head: bytes | None, base: bytes | None, whole: bool) -> list[str]:
    """Why the head's ledger breaks the rule; [] when it keeps it (`judge`)."""
    return judge(head, base, whole)[0]


def beyond_appending(reason: str) -> bool:
    """Whether an exit reason names what nothing the Founder may append changes: an accepted row whose bytes or chain
    are broken (`13`: tamper evidence, the operator's). Every other reason of this check is the Founder's to fix."""
    head, _colon, rest = reason.partition(":")
    return head == ACCEPTED_INVALID and rest.split(":", 1)[0] not in MEANING_RULES
