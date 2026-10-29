"""Hash-chained ledger rows: canonical form, row hash, appender and verifier.

Stage 0, micro-feature 1 (asama-0/14). The rules are tohum/13, tohum/26 and tohum/29a:

- Canonical form is RFC 8785 (JCS): object keys sorted by UTF-16 code units, minimal string escapes,
  numbers printed the way ECMAScript prints them. What JCS cannot express (NaN, Infinity, an integer a
  double cannot hold, a lone surrogate, a key that is not a string, a type JSON does not have) is refused,
  never guessed.
- ``row_hash = sha256(canonical(row without row_hash) || prev_hash)``, lowercase hex. ``prev_hash`` is the
  ASCII hex text, and the first row's ``prev_hash`` is 64 zeros.
- ``verify`` demands that every row names the hash of the row before it and carries the hash of its own
  content. With ``--previous`` the file must also extend the earlier version of itself without touching it:
  a rewrite that recomputes every hash after the edited row is a valid chain and is still refused.

Command line (stdout is one JSON line; exit 0 = fine, 1 = broken chain, 2 = input the tool cannot use):

    python -m ledger.chain hash                        one row, as JSON, on stdin
    python -m ledger.chain verify FILE [--previous FILE]
    python -m ledger.chain append FILE                 one row without prev_hash and row_hash on stdin

A broken chain names the first row that fails (its ``row_id``, or ``line:N`` when the line has none).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sys
from decimal import Decimal
from typing import Any

ZERO_HASH = "0" * 64
HEX64 = re.compile(r"[0-9a-f]{64}\Z")
ESCAPES = {0x08: "\\b", 0x09: "\\t", 0x0A: "\\n", 0x0C: "\\f", 0x0D: "\\r", 0x22: '\\"', 0x5C: "\\\\"}


class ChainError(ValueError):
    """The input cannot be hashed or written the way the spec says."""


# ------------------------------------------------------------------ RFC 8785

def _string(text: str) -> str:
    out = ['"']
    for char in text:
        code = ord(char)
        if code in ESCAPES:
            out.append(ESCAPES[code])
        elif code < 0x20:
            out.append(f"\\u{code:04x}")
        else:
            out.append(char)
    out.append('"')
    return "".join(out)


def _number(value: int | float) -> str:
    """ECMAScript Number::toString (RFC 8785 section 3.2.2.3) for a finite double."""
    if isinstance(value, int):
        try:
            number = float(value)
        except OverflowError as exc:
            raise ChainError(f"integer {str(value)[:20]}... is not a double") from exc
        if int(number) != value:
            raise ChainError(f"integer {value} is not exactly a double")
    else:
        number = value
    if not math.isfinite(number):
        raise ChainError("NaN and Infinity have no JSON form")
    if number == 0:
        return "0"
    parts = Decimal(repr(abs(number))).normalize().as_tuple()
    digits = "".join(str(d) for d in parts.digits)
    k, n = len(digits), parts.exponent + len(digits)
    if k <= n <= 21:
        text = digits + "0" * (n - k)
    elif 0 < n <= 21:
        text = digits[:n] + "." + digits[n:]
    elif -6 < n <= 0:
        text = "0." + "0" * (-n) + digits
    else:
        exponent = n - 1
        mantissa = digits[0] + ("." + digits[1:] if k > 1 else "")
        text = f"{mantissa}e{'+' if exponent > 0 else '-'}{abs(exponent)}"
    return ("-" if number < 0 else "") + text


def _utf16(key: str) -> bytes:
    return key.encode("utf-16-be")  # big endian bytes compare exactly like UTF-16 code units


def _encode(value: Any, out: list[str]) -> None:
    if value is None:
        out.append("null")
    elif value is True:
        out.append("true")
    elif value is False:
        out.append("false")
    elif isinstance(value, str):
        out.append(_string(value))
    elif isinstance(value, (int, float)):
        out.append(_number(value))
    elif isinstance(value, list):
        out.append("[")
        for index, item in enumerate(value):
            if index:
                out.append(",")
            _encode(item, out)
        out.append("]")
    elif isinstance(value, dict):
        for key in value:
            if not isinstance(key, str):
                raise ChainError(f"object key {key!r} is not a string")
        out.append("{")
        for index, key in enumerate(sorted(value, key=_utf16)):
            if index:
                out.append(",")
            out.append(_string(key))
            out.append(":")
            _encode(value[key], out)
        out.append("}")
    else:
        raise ChainError(f"{type(value).__name__} has no JSON form")


def canonical(value: Any) -> bytes:
    """The RFC 8785 bytes of a JSON value."""
    out: list[str] = []
    try:
        _encode(value, out)
        return "".join(out).encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ChainError("a string holds a lone surrogate") from exc
    except RecursionError as exc:
        raise ChainError("nested too deeply") from exc


# ------------------------------------------------------------------ rows

def row_hash(row: Any) -> str:
    if not isinstance(row, dict):
        raise ChainError("a row is a JSON object")
    prev = row.get("prev_hash")
    if not isinstance(prev, str) or not HEX64.match(prev):
        raise ChainError("prev_hash must be 64 lowercase hex characters")
    body = {key: value for key, value in row.items() if key != "row_hash"}
    return hashlib.sha256(canonical(body) + prev.encode("ascii")).hexdigest()


def _no_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    keys = [key for key, _ in pairs]
    if len(keys) != len(set(keys)):
        raise ValueError("an object repeats a key")
    return dict(pairs)


def _no_constants(name: str) -> Any:
    raise ValueError(f"{name} is not JSON")


def _loads(text: str) -> Any:
    return json.loads(text, object_pairs_hook=_no_duplicate_keys, parse_constant=_no_constants)


Problem = tuple[str, str]  # (row, what is wrong)


def _load(path: str) -> tuple[list[Any], Problem | None]:
    """Every line of a JSON Lines file; the first line that is not JSON ends the list and is the problem."""
    with open(path, "rb") as handle:
        data = handle.read()
    lines = data.split(b"\n")
    if lines[-1] == b"":
        lines.pop()
    rows: list[Any] = []
    for number, raw in enumerate(lines, start=1):
        try:
            rows.append(_loads(raw.decode("utf-8")))
        except ValueError:  # UnicodeDecodeError and JSONDecodeError are ValueErrors
            return rows, (f"line:{number}", "the line is not one JSON value")
    return rows, None


def _chain_break(rows: list[Any]) -> Problem | None:
    expected_prev, seen = ZERO_HASH, set()
    for number, row in enumerate(rows, start=1):
        row_id = row.get("row_id") if isinstance(row, dict) else None
        if not isinstance(row, dict):
            return f"line:{number}", "a row is a JSON object"
        if not isinstance(row_id, str) or not row_id:
            return f"line:{number}", "row_id is missing"
        if row_id in seen:
            return row_id, "row_id repeats"
        seen.add(row_id)
        if row.get("prev_hash") != expected_prev:
            return row_id, "prev_hash is not the hash of the row before"
        try:
            computed = row_hash(row)
        except ChainError as exc:
            return row_id, str(exc)
        if row.get("row_hash") != computed:
            return row_id, "row_hash does not match the row"
        expected_prev = computed
    return None


def _not_append_only(rows: list[Any], earlier: list[Any]) -> Problem | None:
    for index, before in enumerate(earlier):
        if index >= len(rows):
            return before["row_id"], "the file lost this row"
        if canonical(rows[index]) != canonical(before):
            return before["row_id"], "this row was rewritten"
    return None


def check_file(path: str, previous: str | None = None) -> dict[str, Any]:
    rows, unreadable = _load(path)
    problem = _chain_break(rows) or unreadable
    if problem is None and previous is not None:
        earlier, unreadable_before = _load(previous)
        before = _chain_break(earlier) or unreadable_before
        if before is not None:
            problem = (before[0], f"the previous file is broken: {before[1]}")
        else:
            problem = _not_append_only(rows, earlier)
    if problem is not None:
        return {"valid": False, "broken_row": problem[0], "reason": problem[1]}
    return {"valid": True, "broken_row": None, "rows": len(rows)}


def append_row(path: str, row: Any) -> str:
    """Add one row to the end of the file and return its hash. A broken chain is never extended."""
    if not isinstance(row, dict):
        raise ChainError("a row is a JSON object")
    if "prev_hash" in row or "row_hash" in row:
        raise ChainError("the writer sets prev_hash and row_hash itself")
    if not isinstance(row.get("row_id"), str) or not row["row_id"]:
        raise ChainError("row_id is missing")
    rows: list[Any] = []
    if os.path.exists(path):
        rows, unreadable = _load(path)
        problem = _chain_break(rows) or unreadable
        if problem is not None:
            raise ChainError(f"refusing to extend a broken chain: {problem[0]}: {problem[1]}")
        with open(path, "rb") as handle:
            content = handle.read()
        if content and not content.endswith(b"\n"):
            raise ChainError("the last line has no newline, so the file may be cut short")
    if any(existing["row_id"] == row["row_id"] for existing in rows):
        raise ChainError(f"row_id {row['row_id']} is already in the file")
    full = dict(row, prev_hash=rows[-1]["row_hash"] if rows else ZERO_HASH)
    full["row_hash"] = row_hash(full)
    line = canonical(full) + b"\n"
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, "O_BINARY", 0), 0o644)
    try:
        view = memoryview(line)
        while view:
            view = view[os.write(fd, view):]
        os.fsync(fd)
    finally:
        os.close(fd)
    return full["row_hash"]


# ------------------------------------------------------------------ command line

def _stdin_row() -> Any:
    try:
        return _loads(sys.stdin.buffer.read().decode("utf-8"))
    except ValueError as exc:
        raise ChainError(f"stdin is not one JSON value: {exc}") from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m ledger.chain")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("hash")
    verify = sub.add_parser("verify")
    verify.add_argument("file")
    verify.add_argument("--previous")
    sub.add_parser("append").add_argument("file")
    args = parser.parse_args(argv)
    code = 0
    try:
        if args.command == "hash":
            result: dict[str, Any] = {"row_hash": row_hash(_stdin_row())}
        elif args.command == "verify":
            result = check_file(args.file, args.previous)
            code = 0 if result["valid"] else 1
        else:
            result = {"row_hash": append_row(args.file, _stdin_row())}
    except (ChainError, OSError) as exc:
        result, code = {"error": str(exc)}, 2
    print(json.dumps(result, separators=(",", ":")))
    return code


if __name__ == "__main__":
    sys.exit(main())
