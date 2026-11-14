"""``referee_tree_sha256``: the hash of a brain commit's ``referee/`` tree (D1, stage 0).

Rules: tohum/26c ``setup/imports.jsonl`` (the algorithm, its refusals and its known answer), tohum/25a item 1 (the
operator files at the referee repository's root, which ``referee/`` may not carry in any case), asama-0/01 D1 (green:
the accepted SHA's ``referee/`` hash is the last ``setup/imports.jsonl`` row's).

**The hash.** Over an archive's entries (a path, a kind, the bytes of a file), one line per regular file under
``referee/``: the content's sha256 (lowercase hex), two spaces, the path relative to ``referee/``, LF. The lines are
sorted by their bytes (UTF-8) and joined; the result's sha256, lowercase hex, is the hash. Directories and the
executable bit do not enter. A file's bytes are the blob's as committed (``loop.gitobj`` reads objects, so no
attribute, filter or end-of-line conversion applies).

**No hash** (``TreeHashError``; every reason found is listed, sorted, unique), anywhere in the archive:

- ``link:<path>``: a symbolic link; ``special:<path>``: an entry that is neither a regular file, a directory nor a
  link (a device, a fifo, a hard link of a tar; a gitlink of a commit, which ``loop.gitobj`` refuses already as
  ``tree_submodule:<path>``);
- ``path_not_utf8:<path>``, ``path_control:<path>`` (a character of Unicode category Cc: U+0000-U+001F, U+007F-U+009F),
  ``path_backslash:<path>``, ``path_colon:<path>``, ``path_absolute:<path>`` (begins with ``/``),
  ``path_dotdot:<path>`` (a component ``..``), ``path_dotgit:<path>`` (a component ``.git`` in any case, by
  ``str.casefold``);

and under ``referee/``:

- ``casefold_collision:<path>``: two paths, or two directories on the way, that are one name under ``casefold``
  (``referee/A/x`` and ``referee/a/y`` collide at ``A``/``a``); each spelling is listed;
- ``operator_name:<name>``: a top entry of ``referee/`` whose casefold is one of ``OPERATOR_NAMES`` (25a's operator
  files, ``bootstrap`` among them);
- ``no_files``: no regular file under ``referee/``.

A path is shown in a reason with bytes that are not UTF-8 and characters of category Cc escaped (``\\xNN``).

Out of scope, stated: 25a's other ban, agent configuration in ``referee/`` (26c's refusals do not name it; the
seed's ``#agac`` judges it), and paths that 26c does not name: an empty or ``.`` component is not refused, and a path
spelled ``./referee/...`` is not under ``referee/``. The tar reader takes names as ``tarfile`` decodes them (UTF-8,
surrogate escapes kept, so a name that is not UTF-8 is seen as such).

Command line, from ``referee/``::

    python -m loop.treehash tar FILE     # {"ok": true, "referee_tree_sha256": "<hex>"}, exit 0
                                         # {"ok": false, "reasons": [...]}, exit 1; 2 unreadable archive
"""

from __future__ import annotations

import hashlib
import io
import json
import sys
import tarfile
import unicodedata
from typing import Iterable

from loop import gitobj as G
import cli

PREFIX = "referee/"
# tohum/25a item 1: the operator files at the referee repository's root, which the import keeps (``bootstrap`` too).
OPERATOR_NAMES = ("bootstrap", "bootstrap.json", "control.json", "policy.json", "seats", "setup", "vectors")
KINDS = ("file", "dir", "link", "special")


class TreeHashError(Exception):
    def __init__(self, reasons: list[str]):
        super().__init__(", ".join(reasons))
        self.reasons = reasons


def _show(text: str) -> str:
    raw = text.encode("utf-8", "surrogateescape").decode("utf-8", "backslashreplace")
    return "".join("\\x%02x" % ord(ch) if unicodedata.category(ch) == "Cc" else ch for ch in raw)


def _path_reasons(path: str) -> list[str]:
    reasons = []
    try:
        path.encode("utf-8")
    except UnicodeEncodeError:
        reasons.append("path_not_utf8")
    else:
        if any(unicodedata.category(ch) == "Cc" for ch in path):
            reasons.append("path_control")
    if "\\" in path:
        reasons.append("path_backslash")
    if ":" in path:
        reasons.append("path_colon")
    if path.startswith("/"):
        reasons.append("path_absolute")
    parts = path.split("/")
    if ".." in parts:
        reasons.append("path_dotdot")
    if any(p.casefold() == ".git" for p in parts):
        reasons.append("path_dotgit")
    return ["%s:%s" % (r, _show(path)) for r in reasons]


def digest(items: Iterable[tuple[str, str, bytes]]) -> str:
    """The hash of an archive given as ``(path, kind, data)`` triples (``kind`` one of ``KINDS``; ``data`` a file's
    bytes, ignored for other kinds), or ``TreeHashError`` with the reasons above."""
    reasons: list[str] = []
    lines: list[bytes] = []
    spellings: dict[str, set[str]] = {}
    for path, kind, data in items:
        if kind not in KINDS:
            raise ValueError("unknown entry kind %r" % kind)
        reasons += _path_reasons(path)
        if kind in ("link", "special"):
            reasons.append("%s:%s" % (kind, _show(path)))
        if not path.startswith(PREFIX) or path == PREFIX:
            continue
        rel = path[len(PREFIX):].rstrip("/") if kind == "dir" else path[len(PREFIX):]
        parts = rel.split("/")
        if parts[0].casefold() in OPERATOR_NAMES:
            reasons.append("operator_name:%s" % _show(parts[0]))
        for i in range(1, len(parts) + 1):
            prefix = "/".join(parts[:i])
            spellings.setdefault(prefix.casefold(), set()).add(prefix)
        if kind == "file" and not reasons:
            lines.append(b"%s  %s\n" % (hashlib.sha256(data).hexdigest().encode(), rel.encode("utf-8")))
    for names in spellings.values():
        if len(names) > 1:
            reasons += ["casefold_collision:%s" % _show(n) for n in names]
    if not reasons and not lines:
        reasons.append("no_files")
    if reasons:
        raise TreeHashError(sorted(set(reasons)))
    return hashlib.sha256(b"".join(sorted(lines))).hexdigest()


def of_tar(data: bytes) -> str:
    """The hash of a tar archive's bytes (``tarfile.ReadError`` for bytes that are not one)."""
    items = []
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:*", encoding="utf-8", errors="surrogateescape") as tar:
        for member in tar.getmembers():
            if member.isreg():
                fh = tar.extractfile(member)
                items.append((member.name, "file", fh.read() if fh else b""))
            elif member.isdir():
                items.append((member.name, "dir", b""))
            elif member.issym():
                items.append((member.name, "link", b""))
            else:
                items.append((member.name, "special", b""))
    return digest(items)


def of_commit(source, commit: str) -> str:
    """The hash of a commit's tree read from git objects (``loop.gitobj.entries``, which walks the whole tree and
    raises ``loop.pulled.PulledError`` with its own reasons for a tree it refuses)."""
    return digest((e.path, e.kind, e.data) for e in G.entries(source, commit))


def main(argv: list[str]) -> int:
    if len(argv) != 2 or argv[0] != "tar":
        sys.stderr.write("usage: python -m loop.treehash tar FILE\n")
        sys.stdout.write(json.dumps({"ok": False, "reasons": None}) + "\n")
        return 2
    try:
        with open(argv[1], "rb") as fh:
            data = fh.read()
        out = {"ok": True, "referee_tree_sha256": of_tar(data)}
    except TreeHashError as exc:
        out = {"ok": False, "reasons": exc.reasons}
    except (OSError, *cli.ARCHIVE_ERRORS) as exc:
        sys.stderr.write("unusable input: %s\n" % cli.cause(exc))
        sys.stdout.write(json.dumps({"ok": False, "reasons": None}) + "\n")
        return 2
    sys.stdout.write(json.dumps(out, sort_keys=True) + "\n")
    return 0 if out["ok"] else 1


FAULT_LINE = {"ok": False, "reasons": None}


if __name__ == "__main__":
    sys.exit(cli.run(main, sys.argv[1:], FAULT_LINE))
