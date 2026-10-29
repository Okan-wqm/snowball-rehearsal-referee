"""MF2 secrets.scan: python -m gate.secrets scan <diff|row|prompt> <file>.

Prints exactly one JSON line on every exit: {"clean": bool, "lines": [int]}; {"clean": false} when the
input is unusable. Exit 0 clean, 1 match (run invalid, prompt withheld), 2 unusable input.
The matched text is never printed; only 1-based line numbers of the input file.
"""
from __future__ import annotations

import json
import re
import sys
from typing import Any, Iterator

# GitHub classic token: gh[pousr]_ + 36 [A-Za-z0-9], no boundary on either side.
_GITHUB = re.compile(r"gh[pousr]_[A-Za-z0-9]{36}")
# AWS access key id: AKIA|ASIA + 16 [A-Z0-9], not adjacent to another [A-Za-z0-9] on either side.
_AWS = re.compile(r"(?<![A-Za-z0-9])(?:AKIA|ASIA)[A-Z0-9]{16}(?![A-Za-z0-9])")
_FORMATS = (_GITHUB, _AWS)


class Unusable(Exception):
    pass


def _match_starts(text: str) -> Iterator[int]:
    """Offsets where some secret format match starts (every start, overlapping ones included)."""
    for pattern in _FORMATS:
        pos = 0
        while True:
            m = pattern.search(text, pos)
            if m is None:
                break
            yield m.start()
            pos = m.start() + 1


def _lines_of(text: str) -> list[str]:
    parts = text.split("\n")
    if parts and parts[-1] == "":
        parts.pop()  # the empty segment after a final LF is not a line
    return parts


def scan_text(text: str) -> set[int]:
    return {text.count("\n", 0, start) + 1 for start in _match_starts(text)}


class _Pairs(list):
    """A decoded JSON object kept as its (key, value) pairs, so a duplicate key cannot hide a value."""


def _reject_constant(name: str) -> Any:
    raise ValueError(f"not JSON: {name}")


def _strings(value: Any) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, _Pairs):
        for key, item in value:
            yield key
            yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)


def scan_rows(text: str) -> set[int]:
    found: set[int] = set()
    for number, line in enumerate(_lines_of(text), start=1):
        try:
            row = json.loads(line, object_pairs_hook=_Pairs, parse_constant=_reject_constant)
        except ValueError as exc:
            raise Unusable(f"line {number}: not JSON") from exc
        if not isinstance(row, _Pairs):
            raise Unusable(f"line {number}: not a JSON object")
        if any(next(_match_starts(s), None) is not None for s in _strings(row)):
            found.add(number)
    return found


def _emit(obj: dict[str, Any], code: int) -> int:
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()
    return code


def main(argv: list[str]) -> int:
    if len(argv) != 3 or argv[0] != "scan" or argv[1] not in ("diff", "row", "prompt"):
        return _emit({"clean": False}, 2)
    kind, path = argv[1], argv[2]
    try:
        with open(path, "rb") as fh:
            text = fh.read().decode("utf-8")
        lines = scan_rows(text) if kind == "row" else scan_text(text)
    except (OSError, UnicodeDecodeError, Unusable):
        return _emit({"clean": False}, 2)
    if lines:
        return _emit({"clean": False, "lines": sorted(lines)}, 1)
    return _emit({"clean": True, "lines": []}, 0)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
