"""Canonical JSON (the RFC 8785 subset the seed allows) and hashing helpers.

Hashed artefacts carry no floating-point numbers (`tohum/26`): values are integers, strings,
booleans, null, arrays and objects. Object keys are sorted by UTF-16 code units, as RFC 8785
requires; for keys inside the Basic Multilingual Plane this equals code-point order.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

MAX_SAFE_INTEGER = 2**53 - 1


class CanonicalError(ValueError):
    """Raised when a value cannot be written in the canonical subset."""


def _check(value: Any, path: str) -> None:
    if value is None or isinstance(value, (bool, str)):
        if isinstance(value, str):
            for ch in value:
                if 0xD800 <= ord(ch) <= 0xDFFF:
                    raise CanonicalError(f"{path}: lone surrogate in string")
        return
    if isinstance(value, int):
        if abs(value) > MAX_SAFE_INTEGER:
            raise CanonicalError(f"{path}: integer outside the safe range")
        return
    if isinstance(value, float):
        raise CanonicalError(f"{path}: floating-point numbers are not allowed")
    if isinstance(value, list):
        for i, item in enumerate(value):
            _check(item, f"{path}[{i}]")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise CanonicalError(f"{path}: object key is not a string")
            _check(key, f"{path}.<key>")
            _check(item, f"{path}.{key}")
        return
    raise CanonicalError(f"{path}: unsupported type {type(value).__name__}")


def _utf16_key(key: str) -> list[int]:
    return list(key.encode("utf-16-be"))


def _sorted(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _sorted(value[k]) for k in sorted(value, key=_utf16_key)}
    if isinstance(value, list):
        return [_sorted(v) for v in value]
    return value


def canonical(value: Any) -> bytes:
    """Return the canonical UTF-8 encoding of ``value``."""
    _check(value, "$")
    text = json.dumps(_sorted(value), ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    return text.encode("utf-8")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def row_hash(row: dict[str, Any]) -> str:
    """Chain hash of a ledger row: sha256(canonical(row - row_hash) || prev_hash)."""
    body = {k: v for k, v in row.items() if k != "row_hash"}
    prev = row["prev_hash"]
    if not isinstance(prev, str) or len(prev) != 64:
        raise CanonicalError("prev_hash must be 64 hex characters")
    return sha256_hex(canonical(body) + prev.encode("ascii"))


def dump(value: Any) -> str:
    """Pretty, deterministic JSON for files people read. Not used for hashing."""
    _check(value, "$")
    return json.dumps(_sorted(value), ensure_ascii=False, indent=2, allow_nan=False) + "\n"
