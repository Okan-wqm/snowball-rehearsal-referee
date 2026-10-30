"""Shared input helpers of the gate modules: strict JSON, LF lines, one-line JSON output."""

from __future__ import annotations

import json
import sys
from typing import Any, NoReturn


class Unusable(ValueError):
    """Input that cannot be read as the interface describes (exit 2)."""


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
    if not data:
        return []
    lines = data.split(b"\n")
    if lines[-1] == b"":
        lines.pop()
    return lines


def read(path: str) -> bytes:
    try:
        with open(path, "rb") as fh:
            return fh.read()
    except OSError as exc:
        raise Unusable(f"cannot read {path}") from exc


def is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def is_str_list(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def emit(obj: dict[str, Any], code: int) -> NoReturn:
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()
    sys.exit(code)
