"""``profile.yamlblock``: a reader of the YAML that repositories' CI and container files are written in (GitHub
workflows and actions, compose files), read statically, no YAML library (the sandbox has none). It is a reader,
not a judge: ``tests/workflow_yaml.py`` is the seed's strict subset for the referee's own ``loop.yml`` (tohum/29r),
which refuses forms that this module reads.

``load_all(text)`` gives the value of every document of the text, in order; a value is a ``dict`` (keys ``str``,
in file order), ``list``, ``str``, ``int``, ``float``, ``bool`` or ``None``. ``load(text)`` gives the one document's
value, ``None`` for a text with no document; a second document is ``documents`` at its line. A text either does
not read raises ``Unreadable`` (a ``ValueError``) with ``line`` (1-based, 0 for the whole text) and ``reason`` (one
of ``REASONS``); nothing is returned for the documents before it. Exactly these forms are read:

- lines: LF or CRLF; blank lines and lines whose first non-blank character is ``#`` are skipped outside block and
  quoted scalars; indentation is spaces, a tab before content is ``tab``;
- documents: a marker is ``---`` or ``...`` at column 0 followed by the end of the line, a blank or a comment
  (other text after it, ``--- !x`` or ``--- |``, is ``marker_content``); ``---`` starts a document, ``...`` ends
  one; lines starting with ``%`` (directives) are skipped between documents; a document without ``---`` starts at
  the first other line (at the start of the text or after a ``...``), so it holds content; a document after ``---``
  may be empty (its value is ``None``); a quoted scalar is not continued across a
  marker (``unterminated_quote``); anchors are the document's own (an alias to an earlier document's is ``alias``);
- the root is a block mapping or a block sequence (a root scalar is ``scalar_document``);
- block mapping: ``key: value`` or ``key:`` (value the block below, indented more, or a block sequence at the key's
  own column; nothing below is ``None``); a key is plain (up to the first ``:`` followed by a blank or the end of
  the line, before any `` #``) or wholly single- or double-quoted; keys stay strings (``on`` and ``true`` too); a
  key twice in one mapping is ``duplicate_key``; a ``? `` key and a key with an anchor, an alias or a tag (``&a k:``)
  are ``complex_key``;
- block sequence: ``- value`` or ``-`` (value below); ``- key: value`` opens a mapping at the key's column, ``- -``
  a sequence;
- scalars: plain (a trailing `` #`` comment removed; continuation lines indented more than the key or dash are
  joined with a space, a blank line between them a line break; a continuation holding ``: `` is
  ``mapping_in_scalar``), typed by the core schema: ``null``/``Null``/``NULL``/``~``/empty, ``true``/``false`` (and
  ``True``, ``TRUE``, ``False``, ``FALSE``), decimal integers, decimal floats; everything else ``str``; a plain
  scalar starting with ``%``, ``@`` or a backtick is ``indicator``;
  single-quoted (``''`` a quote) and double-quoted (escapes ``\\0 \\a \\b \\t \\n \\v \\f \\r \\e \\  \\" \\/ \\\\
  \\N \\_ \\L \\P \\xHH \\uHHHH \\UHHHHHHHH`` and an escaped line break; another is ``escape``), over several lines
  folded as YAML does, unclosed ``unterminated_quote``, followed by more than a comment ``text_after_quote``;
  literal ``|`` and folded ``>`` block scalars with a chomping (``-``, ``+``) and an indentation indicator (another
  header is ``block_header``);
- flow collections ``[...]`` and ``{...}`` (over several lines, nested, quoted and plain scalars, aliases; a
  ``key: value`` pair inside ``[...]`` or a bracket left open is ``flow``);
- anchors ``&name`` on a scalar, a flow collection or a block below, aliases ``*name`` (an unknown one is
  ``alias``), merge keys ``<<: *a`` and ``<<: [*a, *b]`` (keys written in the mapping win, then the earlier
  alias);
- more than ``MAX_DEPTH`` block collections open at once, or more than ``MAX_DEPTH`` flow collections open at once
  in one flow value, is ``too_deep`` (no function here calls itself).

Not read, stated: tags (``!x`` is ``tag``), content on a marker's line, a mapping or sequence as a key, the YAML 1.1 types
(``yes``/``on`` stay strings, octal and sexagesimal numbers). A line break inside a plain or quoted scalar is
folded by the rules above; a block scalar's indentation is taken from its first non-blank line unless given.
"""

from __future__ import annotations

import re
from typing import Any

MAX_DEPTH = 64
REASONS = ("tab", "indentation", "not_a_key", "not_an_entry", "duplicate_key", "complex_key", "too_deep", "tag",
           "alias", "unterminated_quote", "text_after_quote", "escape", "flow", "indicator", "mapping_in_scalar",
           "documents", "scalar_document", "block_header", "marker_content")

_NULL = ("", "~", "null", "Null", "NULL")
_BOOL = {"true": True, "True": True, "TRUE": True, "false": False, "False": False, "FALSE": False}
_INT = re.compile(r"[-+]?[0-9]+")
_FLOAT = re.compile(r"[-+]?(?:\.[0-9]+|[0-9]+(?:\.[0-9]*)?)(?:[eE][-+]?[0-9]+)?")
_HEADER = re.compile(r"([|>])(?:([1-9])([-+]?)|([-+])([1-9])?)?(?:\s+#.*)?")
_ANCHOR = re.compile(r"&([^\s,\[\]{}]+)(?:\s+(.*))?")
_ESCAPES = {"0": "\0", "a": "\a", "b": "\b", "t": "\t", "\t": "\t", "n": "\n", "v": "\v", "f": "\f", "r": "\r",
            "e": "\x1b", " ": " ", '"': '"', "/": "/", "\\": "\\", "N": "\x85", "_": "\xa0", "L": " ",
            "P": " "}
_HEX = {"x": 2, "u": 4, "U": 8}
_BLOCK = object()


class Unreadable(ValueError):
    def __init__(self, line: int, reason: str) -> None:
        super().__init__("L%d:%s" % (line, reason))
        self.line = line
        self.reason = reason


def _plain(text: str) -> Any:
    if text in _NULL:
        return None
    if text in _BOOL:
        return _BOOL[text]
    if _INT.fullmatch(text):
        return int(text)
    if _FLOAT.fullmatch(text):
        return float(text)
    return text


def _uncomment(text: str) -> str:
    """``text`` without a trailing comment (`` #`` or a ``#`` that starts it), blanks stripped."""
    if text.startswith("#"):
        return ""
    m = re.search(r"[ \t]#", text)
    return (text[:m.start()] if m else text).strip()


def _marker(line: str, i: int) -> str | None:
    """``---`` or ``...`` when line ``i`` (0-based) is a document marker: the three characters at column 0, then
    the end, a blank or a comment; a marker followed by other text is ``marker_content``."""
    if line[:3] not in ("---", "...") or line[3:4] not in ("", " ", "\t", "\r"):
        return None
    if _uncomment(line[3:]) != "":
        raise Unreadable(i + 1, "marker_content")
    return line[:3]


def _quoted_end(text: str, start: int) -> int | None:
    """The index of the quote closing the scalar opened at ``text[start]``, or ``None``."""
    quote = text[start]
    j = start + 1
    while j < len(text):
        if quote == '"' and text[j] == "\\":
            j += 2
            continue
        if text[j] == quote:
            if quote == "'" and text[j + 1:j + 2] == "'":
                j += 2
                continue
            return j
        j += 1
    return None


def _key(content: str) -> tuple[str, str] | None:
    """``(key, rest)`` when ``content`` is a ``key: value`` or ``key:`` line, else ``None``."""
    if content[:1] in ("'", '"'):
        end = _quoted_end(content, 0)
        if end is None:
            return None
        after = content[end + 1:].lstrip(" ")
        if not (after == ":" or after.startswith(": ")):
            return None
        return _unquote(content[:end + 1], 0), after[1:].strip()
    if content[:1] in "[{":
        return None
    for m in re.finditer(r":(?: |$)", content):
        if re.search(r"[ \t]#", content[:m.start()]):
            return None
        key = content[:m.start()].rstrip()
        return (key, content[m.end():].strip()) if key else None
    return None


def _fold(pieces: list[str]) -> str:
    """Lines of a multi-line flow scalar joined as YAML folds them: a break between two lines is a space, a run of
    ``n`` blank lines ``n`` line breaks; each line stripped (the first only on the right, the last on the left)."""
    out = ""
    blanks = 0
    for k, piece in enumerate(pieces):
        piece = piece if k == 0 else piece.lstrip(" \t")
        piece = piece if k == len(pieces) - 1 else piece.rstrip(" \t")
        if k == 0:
            out = piece
        elif piece == "" and k != len(pieces) - 1:
            blanks += 1
        else:
            out += ("\n" * blanks if blanks else " ") + piece
            blanks = 0
    return out


def _unquote(text: str, line: int) -> str:
    """The value of a whole quoted scalar ``text`` (quotes included, line breaks already folded)."""
    body = text[1:-1]
    if text[0] == "'":
        return body.replace("''", "'")
    out: list[str] = []
    j = 0
    while j < len(body):
        c = body[j]
        if c != "\\":
            out.append(c)
            j += 1
            continue
        e = body[j + 1:j + 2]
        if e in _ESCAPES:
            out.append(_ESCAPES[e])
            j += 2
        elif e in _HEX and re.fullmatch(r"[0-9A-Fa-f]{%d}" % _HEX[e], body[j + 2:j + 2 + _HEX[e]]):
            out.append(chr(int(body[j + 2:j + 2 + _HEX[e]], 16)))
            j += 2 + _HEX[e]
        else:
            raise Unreadable(line, "escape")
    return "".join(out)


def _closed(text: str) -> bool:
    """Whether the brackets ``text`` opens outside quotes are all closed again (or more closed); a bracket in a
    comment counts (lines are gathered only while indented more, and ``_flow`` skips the comment)."""
    depth = 0
    j = 0
    while j < len(text):
        c = text[j]
        if c in "'\"" and (j == 0 or text[j - 1] in " \t\n[{,:"):
            end = _quoted_end(text, j)
            if end is None:
                return False
            j = end
        elif c in "[{":
            depth += 1
        elif c in "]}":
            depth -= 1
        j += 1
    return depth <= 0


def _flow(text: str, line: int, anchors: dict[str, Any]) -> Any:
    """A whole flow collection ``text`` (comments already allowed after blanks)."""
    stack: list[list[Any]] = []        # [container, key, have_key]
    result: Any = None
    done = False
    j = 0

    def put(value: Any) -> None:
        nonlocal result, done
        if not stack:
            result, done = value, True
            return
        top = stack[-1]
        if isinstance(top[0], list):
            top[0].append(value)
        elif not top[2]:
            top[1], top[2] = value, True
        else:
            top[0][str(top[1])] = value
            top[1], top[2] = None, False

    while j < len(text):
        c = text[j]
        if c in " \t\n":
            j += 1
        elif c == "#" and (j == 0 or text[j - 1] in " \t\n"):
            nl = text.find("\n", j)
            j = len(text) if nl < 0 else nl
        elif done:
            raise Unreadable(line, "text_after_quote")
        elif c in "[{":
            if len(stack) >= MAX_DEPTH:
                raise Unreadable(line, "too_deep")
            stack.append([[] if c == "[" else {}, None, False])
            j += 1
        elif c in "]}":
            if not stack or isinstance(stack[-1][0], list) != (c == "]"):
                raise Unreadable(line, "flow")
            top = stack.pop()
            if top[2]:
                top[0][str(top[1])] = None
            put(top[0])
            j += 1
        elif c == ",":
            if not stack:
                raise Unreadable(line, "flow")
            top = stack[-1]
            if isinstance(top[0], dict) and top[2]:
                top[0][str(top[1])] = None
                top[1], top[2] = None, False
            j += 1
        elif c == ":":
            if not stack or isinstance(stack[-1][0], list) or not stack[-1][2]:
                raise Unreadable(line, "flow")
            stack[-1][2] = "value"
            j += 1
        else:
            if c in "'\"":
                end = _quoted_end(text, j)
                if end is None:
                    raise Unreadable(line, "unterminated_quote")
                value = _unquote(c + _fold(text[j + 1:end].split("\n")) + c, line)
                j = end + 1
            else:
                k = j
                while k < len(text) and text[k] not in ",[]{}\n" and not (
                        text[k] == ":" and text[k + 1:k + 2] in ("", " ", "\t", "\n", ",", "]", "}")) and not (
                        text[k] == "#" and text[k - 1] in " \t"):
                    k += 1
                word = text[j:k].strip()
                j = k
                if word == "":
                    raise Unreadable(line, "flow")
                if word.startswith("*"):
                    if word[1:] not in anchors:
                        raise Unreadable(line, "alias")
                    value = anchors[word[1:]]
                elif word.startswith("!"):
                    raise Unreadable(line, "tag")
                else:
                    value = _plain(word)
            if stack and isinstance(stack[-1][0], dict) and stack[-1][2] is True:
                raise Unreadable(line, "flow")
            put(value)
    if stack or not done:
        raise Unreadable(line, "flow")
    return result


class _Reader:
    def __init__(self, text: str) -> None:
        self.lines = [ln[:-1] if ln.endswith("\r") else ln for ln in text.split("\n")]
        self.anchors: dict[str, Any] = {}

    def _indent(self, k: int) -> int:
        raw = self.lines[k]
        return len(raw) - len(raw.lstrip(" "))

    def _blank(self, k: int) -> bool:
        s = self.lines[k].strip()
        return s == "" or s.startswith("#")

    def value(self, text: str, i: int, limit: int) -> tuple[Any, int]:
        """The value written as ``text`` on line ``i`` (0-based) and the next line to read; continuation lines
        are those indented more than ``limit``. ``_BLOCK`` (and ``i + 1``) when the value is the block below."""
        lines = self.lines
        anchor = None
        m = _ANCHOR.fullmatch(text)
        if m is not None:
            anchor, text = m.group(1), _uncomment(m.group(2) or "")
            if text == "":
                return (_BLOCK, anchor), i + 1
        if text.startswith("!"):
            raise Unreadable(i + 1, "tag")
        nxt = i + 1
        if text.startswith("*"):
            name = _uncomment(text)[1:]
            if name not in self.anchors:
                raise Unreadable(i + 1, "alias")
            value = self.anchors[name]
        elif text[:1] in "|>":
            value, nxt = self._block_scalar(text, i, limit)
        elif text[:1] in ("'", '"'):
            pieces = [text]
            k = i
            while _quoted_end("\n".join(pieces), 0) is None:
                k += 1
                if k >= len(lines) or _marker(lines[k], k) is not None:
                    raise Unreadable(i + 1, "unterminated_quote")
                pieces.append(lines[k])
            joined = "\n".join(pieces)
            end = _quoted_end(joined, 0)
            if _uncomment(joined[end + 1:]) != "":
                raise Unreadable(k + 1, "text_after_quote")
            body = joined[1:end]
            if text[0] == '"':
                body = re.sub(r"\\\n[ \t]*", "", body)
            value = _unquote(text[0] + _fold(body.split("\n")) + text[0], i + 1)
            nxt = k + 1
        elif text[:1] in "[{":
            pieces = [text]
            k = i
            while not _closed("\n".join(pieces)) and k + 1 < len(lines) \
                    and (self._indent(k + 1) > limit or self._blank(k + 1)):
                k += 1
                pieces.append(lines[k])
            value = _flow("\n".join(pieces), i + 1, self.anchors)
            nxt = k + 1
        else:
            plain = _uncomment(text)
            if plain[:1] in ("%", "@", "`"):
                raise Unreadable(i + 1, "indicator")
            pieces = [plain]
            k = i + 1
            while k < len(lines):
                s = lines[k].strip()
                if s == "":
                    k += 1
                    continue
                if s.startswith("#") or self._indent(k) <= limit:
                    break
                cont = _uncomment(s)
                if re.search(r":(?: |$)", cont):
                    raise Unreadable(k + 1, "mapping_in_scalar")
                pieces.extend([""] * (k - nxt))
                pieces.append(cont)
                k += 1
                nxt = k
            value = _plain(plain) if len(pieces) == 1 else _fold(pieces)
        if anchor is not None:
            self.anchors[anchor] = value
        return value, nxt

    def _block_scalar(self, text: str, i: int, limit: int) -> tuple[str, int]:
        m = _HEADER.fullmatch(text)
        if m is None:
            raise Unreadable(i + 1, "block_header")
        style = m.group(1)
        chomp = m.group(3) or m.group(4) or ""
        given = m.group(2) or m.group(5)
        lines = self.lines
        k = i + 1
        ci = limit + int(given) if given else None
        body: list[str] = []
        while k < len(lines):
            raw = lines[k]
            if raw.strip() == "":
                body.append(raw[ci:] if ci is not None and len(raw) > ci else "")
                k += 1
                continue
            ind = self._indent(k)
            if ind <= limit:
                break
            if ci is None:
                ci = ind
            if ind < ci:
                raise Unreadable(k + 1, "indentation")
            body.append(raw[ci:])
            k += 1
        trailing = 0
        while body and body[-1].strip() == "":
            body.pop()
            trailing += 1
        if style == "|":
            core = "\n".join(body)
        else:
            core = body[0] if body else ""
            for j in range(1, len(body)):
                cur, prev = body[j], body[j - 1]
                if cur == "":
                    core += "\n"
                elif prev == "":
                    q = next((body[x] for x in range(j - 2, -1, -1) if body[x] != ""), None)
                    if q is None or cur[0] in " \t" or q[0] in " \t":
                        core += "\n"
                    core += cur
                elif cur[0] in " \t" or prev[0] in " \t":
                    core += "\n" + cur
                else:
                    core += " " + cur
        if not body:
            return ("\n" * trailing if chomp == "+" else ""), k
        if chomp == "-":
            return core, k
        return core + "\n" + ("\n" * trailing if chomp == "+" else ""), k

    def documents(self) -> list[tuple[int, Any]]:
        """Every document, ``(line, value)``: ``line`` (1-based) is its ``---`` marker's, else its first line's.
        Each pass consumes a line: ``document`` reads at least one or stops at a marker, which is consumed here."""
        lines = self.lines
        docs: list[tuple[int, Any]] = []
        i = 0
        while True:
            while i < len(lines) and (self._blank(i) or lines[i].startswith("%")):
                i += 1
            if i >= len(lines):
                return docs
            end = _marker(lines[i], i)
            if end == "...":
                i += 1
                continue
            while True:
                start = i + 1
                if end == "---":
                    i += 1
                self.anchors = {}
                root, i, end = self.document(i)
                docs.append((start, root))
                if end != "---":
                    break

    def document(self, i: int) -> tuple[Any, int, str | None]:
        """The document starting at line ``i`` (0-based), the line where it ends and the marker there (``None`` at
        the end of the text)."""
        lines = self.lines
        root: Any = None
        frames: list[list[Any]] = []        # [indent, container, explicit keys or None]
        pending: list[Any] | None = None     # [container, key, indent, from_key, anchor]
        while i < len(lines):
            raw = lines[i].rstrip(" \t")
            content = raw.lstrip(" ")
            if content == "" or content.startswith("#"):
                i += 1
                continue
            if content.startswith("\t"):
                raise Unreadable(i + 1, "tab")
            indent = len(raw) - len(content)
            if indent == 0 and _marker(content, i) is not None:
                if pending is not None and pending[4] is not None:
                    self.anchors[pending[4]] = None
                return root, i, _marker(content, i)
            entry = content == "-" or content.startswith("- ")
            if pending is not None:
                if indent > pending[2] and not entry and _key(content) is None and not content.startswith("? "):
                    value, nxt = self.value(content, i, pending[2])
                    if isinstance(value, tuple) and value[0] is _BLOCK:
                        raise Unreadable(i + 1, "indentation")
                    pending[0][pending[1]] = value
                    if pending[4] is not None:
                        self.anchors[pending[4]] = value
                    pending = None
                    i = nxt
                    continue
                if indent > pending[2] or (entry and pending[3] and indent == pending[2]):
                    obj: Any = [] if entry else {}
                    pending[0][pending[1]] = obj
                    if pending[4] is not None:
                        self.anchors[pending[4]] = obj
                    frames.append([indent, obj, None if entry else set()])
                elif pending[4] is not None:
                    self.anchors[pending[4]] = None
                pending = None
            while frames and (frames[-1][0] > indent or (frames[-1][0] == indent and frames[-1][2] is None
                              and not entry and len(frames) > 1 and frames[-2][0] == indent)):
                frames.pop()
            if root is None:
                if not entry and _key(content) is None:
                    raise Unreadable(i + 1, "complex_key" if content.startswith("? ") else "scalar_document")
                root = [] if entry else {}
                frames.append([indent, root, None if entry else set()])
            if not frames or frames[-1][0] != indent:
                raise Unreadable(i + 1, "indentation")
            col, text = indent, content
            while True:
                if len(frames) > MAX_DEPTH:
                    raise Unreadable(i + 1, "too_deep")
                at, obj, explicit = frames[-1]
                if explicit is None:
                    if not (text == "-" or text.startswith("- ")):
                        raise Unreadable(i + 1, "not_an_entry")
                    rest = text[1:]
                    newcol = col + 1 + len(rest) - len(rest.lstrip(" "))
                    rest = rest.strip(" ")
                    if rest == "-" or rest.startswith("- ") or _key(rest) is not None:
                        child: Any = [] if rest.startswith("-") else {}
                        obj.append(child)
                        frames.append([newcol, child, None if rest.startswith("-") else set()])
                        col, text = newcol, rest
                        continue
                    if rest.startswith("? "):
                        raise Unreadable(i + 1, "complex_key")
                    if _uncomment(rest) == "":
                        obj.append(None)
                        pending = [obj, len(obj) - 1, col, False, None]
                        i += 1
                        break
                    value, nxt = self.value(rest, i, col)
                    obj.append(None)
                    if isinstance(value, tuple) and value[0] is _BLOCK:
                        pending = [obj, len(obj) - 1, col, False, value[1]]
                    else:
                        obj[-1] = value
                    i = nxt
                    break
                kv = _key(text)
                if kv is None:
                    raise Unreadable(i + 1, "complex_key" if text.startswith("? ") else "not_a_key")
                key, rest = kv
                if text[:1] in "&*!":
                    raise Unreadable(i + 1, "complex_key")
                if key in explicit:
                    raise Unreadable(i + 1, "duplicate_key")
                explicit.add(key)
                if _uncomment(rest) == "":
                    obj[key] = None
                    pending = [obj, key, col, True, None]
                    i += 1
                    break
                value, nxt = self.value(rest, i, col)
                if isinstance(value, tuple) and value[0] is _BLOCK:
                    obj[key] = None
                    pending = [obj, key, col, True, value[1]]
                elif key == "<<":
                    for source in (value if isinstance(value, list) else [value]):
                        if not isinstance(source, dict):
                            raise Unreadable(i + 1, "alias")
                        for k, v in source.items():
                            if k not in obj:
                                obj[k] = v
                else:
                    obj[key] = value
                i = nxt
                break
        if pending is not None and pending[4] is not None:
            self.anchors[pending[4]] = None
        return root, i, None


def load(text: str) -> Any:
    """The text's one document (``None`` when it holds none); a second one is ``documents`` at its line."""
    docs = _Reader(text).documents()
    if len(docs) > 1:
        raise Unreadable(docs[1][0], "documents")
    return docs[0][1] if docs else None


def load_all(text: str) -> list[Any]:
    """Every document of the text, in order (``load_all`` in the module docstring)."""
    return [value for _line, value in _Reader(text).documents()]
