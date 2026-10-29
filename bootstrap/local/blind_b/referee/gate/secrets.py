"""gate.secrets -- secrets.scan (MF2): diff, ledger row, prompt.

    python -m gate.secrets scan diff|row|prompt <file>

Prints exactly one JSON line: {"clean": bool, "lines": [int]} (exit 0 clean, 1 match), or
{"clean": false} on unusable input (exit 2, fail closed). The matched text is never printed.
"""
import json
import re
import sys

# GitHub classic token: gh[pousr]_ + 36 [A-Za-z0-9], no boundary on either side.
GITHUB_CLASSIC = re.compile(r"gh[pousr]_[A-Za-z0-9]{36}")
# AWS access key id: AKIA|ASIA + 16 [A-Z0-9], not adjacent to [A-Za-z0-9] on either side.
AWS_KEY_ID = re.compile(r"(?<![A-Za-z0-9])(?:AKIA|ASIA)[A-Z0-9]{16}(?![A-Za-z0-9])")
PATTERNS = (GITHUB_CLASSIC, AWS_KEY_ID)
KINDS = ("diff", "row", "prompt")


class Unusable(Exception):
    pass


def has_secret(s: str) -> bool:
    return any(p.search(s) for p in PATTERNS)


def split_lines(text: str) -> list:
    """LF-separated segments; a final empty segment after the last LF is not a line."""
    segs = text.split("\n")
    if segs[-1] == "":
        segs.pop()
    return segs


def _text_match_lines(text: str) -> list:
    """Scan the whole text; report the 1-based line on which each match starts."""
    lines = set()
    for pat in PATTERNS:
        for m in pat.finditer(text):
            lines.add(text.count("\n", 0, m.start()) + 1)
    return sorted(lines)


class _Obj(list):
    """A decoded JSON object kept as its (key, value) pairs, duplicates included."""


def _reject_constant(name):
    raise ValueError(f"not JSON: {name}")


def _strings(value):
    out, stack = [], [value]
    while stack:
        v = stack.pop()
        if isinstance(v, str):
            out.append(v)
        elif isinstance(v, _Obj):
            for k, x in v:
                out.append(k)
                stack.append(x)
        elif isinstance(v, list):
            stack.extend(v)
    return out


def _row_match_lines(text: str) -> list:
    hits = []
    for n, line in enumerate(split_lines(text), start=1):
        try:
            row = json.loads(line, object_pairs_hook=_Obj, parse_constant=_reject_constant)
        except (ValueError, RecursionError) as e:
            raise Unusable(f"row line {n} does not decode") from e
        if not isinstance(row, _Obj):
            raise Unusable(f"row line {n} is not a JSON object")
        if any(has_secret(s) for s in _strings(row)):
            hits.append(n)
    return hits


def scan(kind: str, data: bytes) -> list:
    """Return the sorted distinct match lines; raise Unusable when the input cannot be judged."""
    if kind not in KINDS:
        raise Unusable(f"unknown kind {kind!r}")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as e:
        raise Unusable("not UTF-8") from e
    if kind == "row":
        return _row_match_lines(text)
    return _text_match_lines(text)


def _emit(obj) -> None:
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    try:
        if len(argv) != 3 or argv[0] != "scan":
            raise Unusable("usage: scan diff|row|prompt <file>")
        kind, path = argv[1], argv[2]
        if kind not in KINDS:
            raise Unusable(f"unknown kind {kind!r}")
        try:
            with open(path, "rb") as f:
                data = f.read()
        except OSError as e:
            raise Unusable("unreadable file") from e
        lines = scan(kind, data)
    except Exception:  # fail closed: nothing that cannot be judged is declared clean
        _emit({"clean": False})
        return 2
    clean = not lines
    _emit({"clean": clean, "lines": lines})
    return 0 if clean else 1


if __name__ == "__main__":
    sys.exit(main())
