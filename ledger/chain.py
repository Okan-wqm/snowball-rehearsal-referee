"""Hash-chained ledger rows: canonical form, row hash and verifier (stage 0, MF1).

Rules: tohum/13 (chained ledgers), tohum/26 (ledger row, numbers), tohum/29a (vectors V1-V3, interface).

- Canonical form is RFC 8785 (JCS). Hashed artifacts carry no floating point (tohum/26), so the only
  numbers accepted are integers inside the I-JSON range (|n| <= 2**53 - 1), where the JCS form is the
  plain decimal. Anything JCS or tohum/26 cannot express -- a float, NaN, an integer outside that range,
  a lone surrogate, a duplicate key -- is refused, never guessed.
- ``row_hash = sha256(canonical(row without row_hash) || prev_hash)``: ``||`` is byte concatenation and
  ``prev_hash`` is its ASCII hex text. Hashes are lowercase hex; the first row's ``prev_hash`` is 64 zeros.
- ``verify`` requires every row to name the hash of the row before it and to carry the hash of its own
  content. With ``--previous`` the file must also be the earlier version with lines only appended: an
  edited row whose hashes were all recomputed is a valid chain and is still refused.

Command line, run from ``referee/`` (stdout is one JSON line; exit 0 fine, 1 broken, 2 unusable input):

    python -m ledger.chain hash                               one row as JSON on stdin
    python -m ledger.chain verify FILE [--previous FILE]

A broken chain names the first failing row: its ``row_id``, or ``line:N`` when the line has none.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from typing import Any

import cli

ZERO_HASH = "0" * 64
HEX64 = re.compile(r"[0-9a-f]{64}\Z")
MAX_SAFE_INT = 2**53 - 1
SHORT_ESCAPES = {'"': '\\"', "\\": "\\\\", "\b": "\\b", "\t": "\\t", "\n": "\\n", "\f": "\\f", "\r": "\\r"}


class ChainError(ValueError):
    """The input cannot be canonicalised or hashed the way the spec says."""


# ---------------------------------------------------------------- RFC 8785

def _canon_string(text: str) -> str:
    parts = ['"']
    for ch in text:
        if ch in SHORT_ESCAPES:
            parts.append(SHORT_ESCAPES[ch])
        elif ord(ch) < 0x20:
            parts.append("\\u%04x" % ord(ch))
        elif 0xD800 <= ord(ch) <= 0xDFFF:
            raise ChainError("lone surrogate in string")
        else:
            parts.append(ch)
    parts.append('"')
    return "".join(parts)


def _utf16_key(key: str) -> bytes:
    return key.encode("utf-16-be")


def _canon(value: Any, out: list[str]) -> None:
    if value is None:
        out.append("null")
    elif value is True:
        out.append("true")
    elif value is False:
        out.append("false")
    elif isinstance(value, int):
        if abs(value) > MAX_SAFE_INT:
            raise ChainError("integer outside the I-JSON range")
        out.append(str(value))
    elif isinstance(value, float):
        raise ChainError("floating point number in a hashed row (tohum/26)")
    elif isinstance(value, str):
        out.append(_canon_string(value))
    elif isinstance(value, list):
        out.append("[")
        for i, item in enumerate(value):
            if i:
                out.append(",")
            _canon(item, out)
        out.append("]")
    elif isinstance(value, dict):
        for key in value:
            if not isinstance(key, str):
                raise ChainError("object key is not a string")
            _canon_string(key)  # refuses lone surrogates in keys before sorting
        out.append("{")
        for i, key in enumerate(sorted(value, key=_utf16_key)):
            if i:
                out.append(",")
            out.append(_canon_string(key))
            out.append(":")
            _canon(value[key], out)
        out.append("}")
    else:
        raise ChainError("type %s has no JSON form" % type(value).__name__)


def canonical(value: Any) -> bytes:
    """RFC 8785 bytes of ``value``; raises ChainError for what the canonical form cannot hold."""
    out: list[str] = []
    try:
        _canon(value, out)
    except RecursionError:
        raise ChainError("value nested too deeply") from None
    return "".join(out).encode("utf-8")


# ---------------------------------------------------------------- parsing

def _no_duplicates(pairs: list[tuple[str, Any]]) -> dict:
    obj: dict = {}
    for key, val in pairs:
        if key in obj:
            raise ChainError("duplicate key %r" % key)
        obj[key] = val
    return obj


def _no_constant(name: str) -> Any:
    raise ChainError("%s is not JSON" % name)


def parse_row(text: str) -> dict:
    """One ledger line as a JSON object; ChainError for anything else."""
    try:
        row = cli.loads(text, object_pairs_hook=_no_duplicates, parse_constant=_no_constant)
    except ChainError:
        raise
    except RecursionError:
        raise ChainError("line nested too deeply") from None
    except ValueError as exc:
        raise ChainError("not JSON: %s" % cli.cause(exc)) from None
    if not isinstance(row, dict):
        raise ChainError("row is not a JSON object")
    return row


# ---------------------------------------------------------------- hash

def row_hash(row: dict) -> str:
    """``sha256(canonical(row - row_hash) || prev_hash)`` as lowercase hex."""
    prev = row.get("prev_hash")
    if not isinstance(prev, str) or not HEX64.match(prev):
        raise ChainError("prev_hash is not 64 lowercase hex characters")
    body = {k: v for k, v in row.items() if k != "row_hash"}
    return hashlib.sha256(canonical(body) + prev.encode("ascii")).hexdigest()


# ---------------------------------------------------------------- verify

def _row_name(row: Any, lineno: int) -> str:
    if isinstance(row, dict) and isinstance(row.get("row_id"), str):
        return row["row_id"]
    return "line:%d" % lineno


def _lines(data: bytes) -> list[bytes]:
    """Lines of a JSONL file; the final newline is a terminator, not an empty last line."""
    if not data:
        return []
    lines = data.split(b"\n")
    if lines[-1] == b"":
        lines.pop()
    return lines


def _result(valid: bool, broken: str | None = None, lineno: int | None = None, reason: str | None = None) -> dict:
    return {"valid": valid, "broken_row": broken, "line": lineno, "reason": reason}


def verify_bytes(data: bytes, previous: bytes | None = None) -> dict:
    """Verify a chained JSONL file; with ``previous``, also that it only appended to that version."""
    lines = _lines(data)
    expected_prev = ZERO_HASH
    for lineno, raw in enumerate(lines, start=1):
        row: Any = None
        try:
            text = raw.decode("utf-8")
            row = parse_row(text)
            if row.get("prev_hash") != expected_prev:
                return _result(False, _row_name(row, lineno), lineno, "prev_hash does not name the row before")
            stored = row.get("row_hash")
            if not isinstance(stored, str) or row_hash(row) != stored:
                return _result(False, _row_name(row, lineno), lineno, "row_hash does not match the row")
        except UnicodeDecodeError:
            return _result(False, "line:%d" % lineno, lineno, "line is not UTF-8")
        except ChainError as exc:
            return _result(False, _row_name(row, lineno), lineno, cli.cause(exc))
        expected_prev = stored

    if previous is not None:
        old = _lines(previous)
        for lineno, old_raw in enumerate(old, start=1):
            if lineno > len(lines) or lines[lineno - 1] != old_raw:
                try:
                    name = _row_name(parse_row(old_raw.decode("utf-8")), lineno)
                except (UnicodeDecodeError, ChainError):
                    name = "line:%d" % lineno
                return _result(False, name, lineno, "not append-only: a row of the previous version is changed or gone")
    return _result(True)


def verify_file(path: str, previous_path: str | None = None) -> dict:
    with open(path, "rb") as fh:
        data = fh.read()
    previous = None
    if previous_path is not None:
        with open(previous_path, "rb") as fh:
            previous = fh.read()
    return verify_bytes(data, previous)


# ---------------------------------------------------------------- command line

USAGE = "usage: python -m ledger.chain hash < row.json | python -m ledger.chain verify FILE [--previous FILE]"


def _emit(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj, sort_keys=True, separators=(",", ":")) + "\n")


def main(argv: list[str]) -> int:
    if argv[:1] == ["hash"] and len(argv) == 1:
        data = sys.stdin.buffer.read()
        try:
            lines = _lines(data)
            if len(lines) != 1:
                raise ChainError("hash takes exactly one line on stdin")
            _emit({"row_hash": row_hash(parse_row(lines[0].decode("utf-8")))})
            return 0
        except (ChainError, UnicodeDecodeError) as exc:
            _emit({"error": cli.cause(exc)})
            return 2
    if argv[:1] == ["verify"] and (len(argv) == 2 or (len(argv) == 4 and argv[2] == "--previous")):
        try:
            result = verify_file(argv[1], argv[3] if len(argv) == 4 else None)
        except OSError as exc:
            _emit({"error": "cannot read: %s" % cli.cause(exc)})
            return 2
        _emit(result)
        return 0 if result["valid"] else 1
    sys.stderr.write(USAGE + "\n")
    _emit({"error": "usage"})
    return 2


FAULT_LINE = cli.GENERIC_LINE


if __name__ == "__main__":
    sys.exit(cli.run(main, sys.argv[1:], FAULT_LINE))
