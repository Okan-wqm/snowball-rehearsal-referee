"""A reader for the YAML subset ``loop.job`` writes, used by test 46 to read ``loop.yml`` without a YAML library
(the referee's sandbox has the standard library only). It is written apart from ``loop.job``'s emitter, so a
mistake in one shows as a difference against the other.

The subset, exactly: block mappings (``key: value`` or ``key:`` and a more indented block), block sequences
(``- item``; an item may open a mapping on its own line), plain scalars, single-quoted scalars (``''`` is a
quote), ``|`` literal blocks (clip: one final newline), ``{}`` and ``[]``, and whole-line ``#`` comments outside a
literal block. Every scalar is returned as ``str`` (no booleans, numbers or nulls). Anything else is refused with
``Unparseable``: tabs in indentation, documents markers, anchors, aliases, tags, flow collections other than ``{}``
and ``[]``, double-quoted and folded scalars, ``?`` keys, a plain scalar holding ``: `` or `` #`` or ending in
``:``, duplicate keys, a key that is not ``[A-Za-z_][A-Za-z0-9_-]*``, and indentation that does not nest.
"""

from __future__ import annotations

import re
from typing import Any


class Unparseable(Exception):
    pass


_KEY = re.compile(r"([A-Za-z_][A-Za-z0-9_-]*):(?: (.*))?")
_INDICATORS = set("[]{}&*!|>'\"%@`,?#-:")


def _lines(text: str) -> list[tuple[int, int, str]]:
    out = []
    for number, raw in enumerate(text.split("\n"), 1):
        if "\t" in raw[:len(raw) - len(raw.lstrip(" \t"))]:
            raise Unparseable("line %d: tab in indentation" % number)
        out.append((number, len(raw) - len(raw.lstrip(" ")), raw))
    return out


def _scalar(text: str, number: int) -> Any:
    if text == "{}":
        return {}
    if text == "[]":
        return []
    if text.startswith("'"):
        if len(text) < 2 or not text.endswith("'") or "'" in text[1:-1].replace("''", ""):
            raise Unparseable("line %d: bad single-quoted scalar" % number)
        return text[1:-1].replace("''", "'")
    if not text or text[0] in _INDICATORS or text != text.strip():
        raise Unparseable("line %d: scalar outside the subset: %r" % (number, text))
    if ": " in text or " #" in text or text.endswith(":"):
        raise Unparseable("line %d: ambiguous plain scalar: %r" % (number, text))
    return text


class _Reader:
    def __init__(self, text: str):
        self.lines = _lines(text)
        self.i = 0

    def _skip(self) -> None:
        while self.i < len(self.lines):
            _, _, raw = self.lines[self.i]
            if raw.strip() and not raw.lstrip(" ").startswith("#"):
                return
            self.i += 1

    def _peek(self) -> tuple[int, int, str] | None:
        self._skip()
        return self.lines[self.i] if self.i < len(self.lines) else None

    def block(self, indent: int) -> Any:
        line = self._peek()
        if line is None or line[1] != indent:
            raise Unparseable("line %d: expected a block at column %d" % (line[0] if line else 0, indent))
        body = line[2][indent:]
        if body == "-" or body.startswith("- "):
            return self._sequence(indent)
        return self._mapping(indent)

    def _value(self, rest: str | None, indent: int, number: int) -> Any:
        if rest is None or rest == "":
            nxt = self._peek()
            if nxt is None or nxt[1] <= indent:
                raise Unparseable("line %d: key without a value" % number)
            return self.block(nxt[1])
        if rest == "|":
            return self._literal(indent, number)
        return _scalar(rest, number)

    def _literal(self, indent: int, number: int) -> str:
        body: list[str] = []
        column = None
        while self.i < len(self.lines):
            _, col, raw = self.lines[self.i]
            if raw.strip() and col <= indent:
                break
            if raw.strip():
                if column is None:
                    column = col
                elif col < column:
                    raise Unparseable("line %d: literal block line left of its column" % self.lines[self.i][0])
                body.append(raw[column:])
            else:
                body.append("")
            self.i += 1
        while body and body[-1] == "":
            body.pop()
        if not body:
            raise Unparseable("line %d: empty literal block" % number)
        return "\n".join(body) + "\n"

    def _mapping(self, indent: int) -> dict[str, Any]:
        out: dict[str, Any] = {}
        while True:
            line = self._peek()
            if line is None or line[1] < indent:
                return out
            number, _, raw = line
            match = _KEY.fullmatch(raw[indent:])
            if not match:
                raise Unparseable("line %d: not a key of the subset: %r" % (number, raw.strip()))
            key = match.group(1)
            if key in out:
                raise Unparseable("line %d: duplicate key %r" % (number, key))
            self.i += 1
            out[key] = self._value(match.group(2), indent, number)

    def _sequence(self, indent: int) -> list[Any]:
        out: list[Any] = []
        while True:
            line = self._peek()
            if line is None or line[1] < indent:
                return out
            number, col, raw = line
            body = raw[indent:]
            if col > indent or not (body == "-" or body.startswith("- ")):
                if col == indent:
                    return out
                raise Unparseable("line %d: unexpected indentation" % number)
            rest = body[2:] if body.startswith("- ") else ""
            if rest.startswith(" "):
                raise Unparseable("line %d: item indentation outside the subset" % number)
            if rest == "":
                self.i += 1
                out.append(self._value(None, indent, number))
            elif _KEY.fullmatch(rest):
                self.lines[self.i] = (number, indent + 2, " " * (indent + 2) + rest)
                out.append(self._mapping(indent + 2))
            else:
                self.i += 1
                out.append(_scalar(rest, number))


def parse(text: str) -> Any:
    if text.startswith("﻿"):
        raise Unparseable("byte order mark")
    for number, _, raw in _lines(text):
        if raw.rstrip() in ("---", "...") or raw.startswith("%"):
            raise Unparseable("line %d: document marker or directive" % number)
    reader = _Reader(text)
    if reader._peek() is None:
        raise Unparseable("empty document")
    doc = reader.block(0)
    if reader._peek() is not None:
        raise Unparseable("line %d: text after the document" % reader._peek()[0])
    if not isinstance(doc, dict):
        raise Unparseable("the document is not a mapping")
    return doc
