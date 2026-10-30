"""MF1 helpers: RFC 8785 canonical form and the chain rule of tohum/29a:18-20 and 26:29-31.

Implementation A's shared helpers of MF14-MF18 (`revert_drill`, `prompt`, `genesis`), as A wrote them in its
`ledger/chain.py`: this brain's MF1 is `ledger/chain.py`, which they do not replace (MF8-MF13's A keeps its own in
`_strict.py`).

row_hash = sha256(canonical(row - row_hash) || prev_hash); the first row's prev_hash is 64 zeros.
Hashed artefacts carry no floats (26:31): a float is refused, as is an integer outside the
IEEE-754 safe range (RFC 8785 numbers are doubles; such an integer has no exact form).
"""
import hashlib
import json

ZERO = "0" * 64
_SAFE = 2 ** 53 - 1
_SHORT = {'"': '\\"', "\\": "\\\\", "\b": "\\b", "\f": "\\f", "\n": "\\n", "\r": "\\r", "\t": "\\t"}


class NotCanonical(ValueError):
    pass


def _string(s):
    out = ['"']
    for ch in s:
        o = ord(ch)
        if ch in _SHORT:
            out.append(_SHORT[ch])
        elif o < 0x20:
            out.append("\\u%04x" % o)
        elif 0xD800 <= o <= 0xDFFF:
            raise NotCanonical("lone surrogate")
        else:
            out.append(ch)
    out.append('"')
    return "".join(out)


def _utf16_key(k):
    try:
        return k.encode("utf-16-be")
    except UnicodeEncodeError as exc:
        raise NotCanonical("lone surrogate in key") from exc


def canonical(value):
    """RFC 8785 text of a JSON value (str)."""
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, int):
        if abs(value) > _SAFE:
            raise NotCanonical("integer outside the safe range")
        return str(value)
    if isinstance(value, float):
        raise NotCanonical("float in a hashed artefact")
    if isinstance(value, str):
        return _string(value)
    if isinstance(value, list):
        return "[" + ",".join(canonical(v) for v in value) + "]"
    if isinstance(value, dict):
        keys = sorted(value, key=_utf16_key)
        return "{" + ",".join(_string(k) + ":" + canonical(value[k]) for k in keys) + "}"
    raise NotCanonical("not a JSON value")


def canonical_bytes(value):
    return canonical(value).encode("utf-8")


def sha256_hex(data):
    return hashlib.sha256(data).hexdigest()


def split_lines(data):
    """LF-separated lines; the empty piece after the last LF is not a line (29f:20-21)."""
    pieces = data.split(b"\n")
    if pieces and pieces[-1] == b"":
        pieces.pop()
    return pieces


def row_hash(row):
    body = {k: v for k, v in row.items() if k != "row_hash"}
    prev = row.get("prev_hash")
    if not isinstance(prev, str):
        raise NotCanonical("prev_hash not a string")
    return sha256_hex(canonical_bytes(body) + prev.encode("utf-8"))


def verify(data):
    """(valid, rows). A line that is not a JSON object breaks the chain (29i:46-47 choice)."""
    rows = []
    prev = ZERO
    for line in split_lines(data):
        try:
            row = json.loads(line.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            return False, None
        if not isinstance(row, dict):
            return False, None
        stored = row.get("row_hash")
        if not isinstance(stored, str) or row.get("prev_hash") != prev:
            return False, None
        try:
            if row_hash(row) != stored:
                return False, None
        except (NotCanonical, UnicodeEncodeError):
            return False, None
        prev = stored
        rows.append(row)
    return True, rows
