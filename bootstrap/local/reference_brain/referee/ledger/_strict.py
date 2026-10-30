"""Shared input helpers of the ledger modules (MF10 `append`, MF11 `anchor`): strict JSON, JSON Lines, RFC 8785,
the row hash, the chain check and the byte-level append-only check (tohum/29a, tohum/13:35-38, tohum/01b:32).

Implementation A's own helpers, as A wrote them in its `ledger/chain.py`, without that file's command line: this
brain's MF1 is `ledger/chain.py`, which they do not replace. row_hash = sha256(canonical(row - row_hash) ||
prev_hash); the first row's prev_hash is 64 zeros. Hashed artefacts carry no floats (26:31-32).
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

ZERO = "0" * 64
HEX64 = re.compile(r"[0-9a-f]{64}")
MAX_SAFE = 2**53 - 1  # RFC 8785 numbers are IEEE 754 doubles; a larger integer is not exact


class Unusable(ValueError):
    """Input that cannot be read as the interface describes (exit 2)."""


# --- strict JSON ---------------------------------------------------------------------------------------------

def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in pairs:
        if key in out:
            raise Unusable(f"duplicate key {key!r}")
        out[key] = value
    return out


def _constant(name: str) -> Any:
    raise Unusable(f"non-finite number {name}")


def loads(data: bytes | str) -> Any:
    """JSON with no duplicate keys and no NaN/Infinity; bytes must be UTF-8."""
    if isinstance(data, bytes):
        try:
            data = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise Unusable("not UTF-8") from exc
    try:
        return json.loads(data, object_pairs_hook=_pairs, parse_constant=_constant)
    except json.JSONDecodeError as exc:
        raise Unusable(f"not JSON: {exc.msg}") from exc
    except RecursionError as exc:
        raise Unusable("nested too deep") from exc


def split_lines(data: bytes) -> list[bytes]:
    """Lines split on LF; the empty piece after the last LF is not a line (tohum/29f:20-21)."""
    if not data:
        return []
    lines = data.split(b"\n")
    if lines[-1] == b"":
        lines.pop()
    return lines


def read_jsonl(data: bytes) -> tuple[list[bytes], list[dict[str, Any]]]:
    """Every line must be one JSON object; otherwise the file is not JSON Lines (unusable)."""
    lines = split_lines(data)
    rows = []
    for number, line in enumerate(lines, start=1):
        value = loads(line)
        if not isinstance(value, dict):
            raise Unusable(f"line {number} is not a JSON object")
        rows.append(value)
    return lines, rows


# --- RFC 8785 ------------------------------------------------------------------------------------------------

_ESCAPES = {'"': '\\"', "\\": "\\\\", "\b": "\\b", "\f": "\\f", "\n": "\\n", "\r": "\\r", "\t": "\\t"}


def _string(text: str) -> str:
    out = ['"']
    for ch in text:
        if ch in _ESCAPES:
            out.append(_ESCAPES[ch])
        elif ord(ch) < 0x20:
            out.append("\\u%04x" % ord(ch))
        else:
            out.append(ch)
    out.append('"')
    return "".join(out)


def _key(name: str) -> bytes:
    return name.encode("utf-16-be", "surrogatepass")  # RFC 8785 sorts by UTF-16 code units


def _canon(value: Any) -> str:
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, int):
        if abs(value) > MAX_SAFE:
            raise Unusable("integer outside the exact double range")
        return str(value)
    if isinstance(value, float):
        raise Unusable("float in a hashed artefact")
    if isinstance(value, str):
        return _string(value)
    if isinstance(value, list):
        return "[" + ",".join(_canon(item) for item in value) + "]"
    if isinstance(value, dict):
        return "{" + ",".join(_string(k) + ":" + _canon(value[k]) for k in sorted(value, key=_key)) + "}"
    raise Unusable(f"not a JSON value: {type(value).__name__}")


def canonical(value: Any) -> bytes:
    try:
        return _canon(value).encode("utf-8")
    except UnicodeEncodeError as exc:  # a lone surrogate has no UTF-8 form
        raise Unusable("lone surrogate in a string") from exc


# --- chain ---------------------------------------------------------------------------------------------------

def row_hash(row: dict[str, Any]) -> str:
    prev = row.get("prev_hash")
    if not isinstance(prev, str) or not HEX64.fullmatch(prev):
        raise Unusable("prev_hash is not 64 lowercase hex")
    body = {k: v for k, v in row.items() if k != "row_hash"}
    return hashlib.sha256(canonical(body) + prev.encode("ascii")).hexdigest()


def first_broken(rows: list[dict[str, Any]]) -> int | None:
    """Index of the first row whose prev_hash or row_hash does not hold, or None for a valid chain."""
    expected_prev = ZERO
    for index, row in enumerate(rows):
        stored = row.get("row_hash")
        if row.get("prev_hash") != expected_prev or not isinstance(stored, str):
            return index
        try:
            if row_hash(row) != stored:
                return index
        except Unusable:
            return index
        expected_prev = stored
    return None


def first_not_in_place(previous: list[bytes], current: list[bytes]) -> int | None:
    """Append-only: every previous line byte-identical at its place (tohum/01b:32). Index of the first line
    that is not, or None when current extends previous."""
    for index, line in enumerate(previous):
        if index >= len(current) or current[index] != line:
            return index
    return None
