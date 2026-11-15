"""``ledger.founder``: the Founder's ledger (``founder-ledger.jsonl`` at the brain's root) against the founder row of
tohum/26 and the closing rule of tohum/13 ("Kurucu defterinde kapatma"), and the one command a session appends a
row with. A session tool (``status/off_live.json``): the loop never writes founder rows, a session does; test 14
runs the same ``problems`` on every push (``tests/test_founder_ledger.py``).

Rules checked by ``problems``:
- the file is one chain (``ledger.chain.verify_bytes``, the one verifier); a broken chain is the only problem
  reported, since rows are not read from a file that is not a chain;
- every row has tohum/26's row fields (``ledger.schema.ROW_FIELDS`` and ``ROW_OPTIONAL_FIELDS``, the one source),
  plus the founder row's optional ``supersedes`` (64 lowercase hex) and no other field (a float is refused by the
  chain itself); ``payload`` is exactly ``{summary, refs[]}``, summary a non-empty string and refs a list of
  non-empty strings;
- the meaning rules tohum/13 names (``part``, ``kind``, ``supersedes``): ``part`` is ``founder``; ``kind`` is in the
  set tohum/26 lists after "**`founder` satırı:** `kind` ∈", read from the page (``spec_kinds``), not copied;
  ``supersedes`` names the ``row_hash`` of an earlier row of this file that breaks a meaning rule;
- a row that breaks a meaning rule is a problem unless a later row that breaks none and has the row shape names its
  ``row_hash`` in ``supersedes`` (the row is closed);
- a ref ``closes:<row_id>`` (this brain's rule, not tohum's: an item is not a broken row, so ``supersedes`` cannot
  close it) names an earlier row of kind ``seed_issue`` or ``blocked`` (an item) that no earlier valid closer has
  closed, once per row; anything else is a problem, and it is not closable. A row closes the items it names only when
  it breaks no meaning rule and has the row shape.

**Open items** (``open``): what this brain has reported and not closed, generated instead of copied into a session's
summary. The items are (1) every ``seed_issue`` or ``blocked`` row no valid ``closes:`` ref names, with its
``row_id``, kind, ``ts`` and the first 200 characters of its summary, in ledger order; then (2) every
``reports/<id>.json`` (tohum/26c; the report's ``state`` is its one source, a ledger row does not close it) whose
``state`` is not ``confirmed``, by id, with kind, state and ref. A report that is not a JSON object with ``id`` equal
to its file's stem and a non-empty string ``state`` makes the list unusable (exit 2); a ledger with any problem gives
no list (exit 1). Whether an item is still true is not checked: a session closes it with the evidence in the
closer's summary.

**Ref since filing** (``ref_checks``; each report item's ``ref_check``): whether the page text a report's ``ref``
names has changed since the report was filed, so that after a seed epoch a session knows which reports to re-test
first. It reads text, not meaning: a re-wrapped paragraph is ``line_changed`` and a changed meaning on an untouched
line is not seen. Read from the git repository holding the reports directory (``git`` with ``loop.gitobj.git_env``,
the one rule for a referee git process; git's ownership check is passed for the named directory and its
ancestors only, ``safe.directory`` on the command line, since that is the repository the caller asks about; paths
are literal, ``--literal-pathspecs``); the commands run are ``rev-parse``, ``log -1 --format=%H``, ``ls-tree`` and
``cat-file blob``; nothing is written. A file "at" a commit is a regular file there (its mode read as
``loop.gitobj.canonical`` reads it): a directory, symbolic link or submodule at the path is none. Rules, in this
order:
- ``unknown`` with ``why``: ``git_unavailable`` (git cannot be started), ``not_in_git`` (the directory is in no
  work tree), ``ref_unreadable`` (``ref`` is not ``<path>:<n>`` or ``<path>:<n>-<m>`` with 1 <= n <= m and a
  relative path with no ``..`` component);
- ``uncommitted``: no commit holds the report, or the report's file differs from its file at its last commit (its
  ref was written against today's page or is being rewritten; there is nothing to compare);
- otherwise ``filed`` is the last commit that changed the report's file, and ``bounded`` is true when that commit is
  a boundary of a shallow clone (the report may have been filed earlier; a change before it is not seen); then
  ``unknown`` ``page_absent_at_filing`` (no file at the path at that commit) or ``line_out_of_range`` (the
  lines are not in it), ``page_gone`` (no regular file at the path in the work tree today; a symbolic link is followed), ``page_unchanged`` (the work tree's
  file has the filed bytes), ``line_same`` (the file changed, the named lines did not: same bytes at the same
  numbers), ``line_moved`` with ``lines`` (those lines, as one block, are elsewhere; every start line), or
  ``line_changed`` (that block is nowhere in today's file: re-test this report first).
Lines are split on ``\n`` and compared as bytes. A block that moved to another page is ``line_changed``: only the
named page is read. A page that is a file but cannot be read is a fault (exit 2, ``cli.run``), not a status. Ledger
items carry no ref this can read and get no ``ref_check``.

Not checked: ``snapshot_id`` being the brain's SHA at that moment (one accepted row, f58, carries a short SHA;
tohum/13 does not count it among the meaning rules a row can be closed for); whether a closed row was accepted
before it was closed (tohum/13: a row a push adds broken is refused even if closed; that needs the last accepted
SHA, which the bootstrap referee holds); append-only against an earlier version (the bootstrap referee checks it
against the last accepted SHA; ``append`` itself only ever adds a line).

**Append** (``append``): builds one row (``row_id`` ``f<n+1>`` after a last row ``f<n>``, ``f1`` on an empty file;
``prev_hash`` the last row's ``row_hash``, or the zero hash; ``row_hash`` by ``ledger.chain.row_hash``), and writes
the file with that line added only if both hold:
- the line is clean under ``gate.secrets.scan(line, "row")``, MF2's row scan (refusal ``row_scan:<rule>`` with its
  sha256, never the value);
- ``problems`` of the new file holds no problem that ``problems`` of the old file did not (refusal
  ``problem:<text>``). So a row that closes an open row is written and the closed row's problem goes; a row that
  breaks a rule is not written, and neither is any row while the file is not a chain (``ledger_unusable``).
The new file is written whole to a temporary file beside it and renamed over it. Not guarded: a second writer
between the read and the rename (a session is one writer).

Command line, run from ``referee/`` (stdout one JSON line; exit 0 ok, 1 problem or refusal, 2 unusable input):

    python -m ledger.founder check [--ledger FILE] [--page FILE]
    python -m ledger.founder open [--ledger FILE] [--page FILE] [--reports DIR]
    python -m ledger.founder append --kind KIND --summary TEXT|- --snapshot SHA [--ref PATH ...]
        [--derivation D] [--trust T] [--supersedes HASH] [--ts TS] [--ledger FILE] [--page FILE]

``--summary -`` reads the summary from stdin (UTF-8, one trailing newline dropped). Defaults: derivation
``llm_inference``, trust ``inferred``, ts the current UTC second, ledger and page the brain's.
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import subprocess
import sys
import tempfile

from gate import secrets
from ledger import chain, schema
from loop.gitobj import SHA, canonical, git_env
import cli

BRAIN = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LEDGER = os.path.join(BRAIN, "founder-ledger.jsonl")
PAGE = os.path.join(BRAIN, "spec", "tohum", "26-semalar.md")
REPORTS = os.path.join(BRAIN, "reports")
FOUNDER = "founder"
ROW_ID = re.compile(r"f(\d+)\Z")
ITEM_KINDS = frozenset({"seed_issue", "blocked"})  # the founder kinds that report something to be closed
CLOSES = "closes:"
CLOSED_REPORT_STATES = frozenset({"confirmed"})  # tohum/26c: the Founder confirms what a seed epoch fixed
HEAD = 200
REF = re.compile(r"([^:\s]+):([1-9][0-9]*)(?:-([1-9][0-9]*))?\Z")

PAYLOAD = schema.shape({"summary": schema.text, "refs": schema.list_of(schema.text)})
# part and kind are meaning rules (closable), so the shape takes any non-empty string there
FOUNDER_ROW = schema.shape({**schema.ROW_FIELDS, "part": schema.text, "kind": schema.text, "payload": PAYLOAD},
                           {**schema.ROW_OPTIONAL_FIELDS, "supersedes": schema.hex64})


class Unusable(Exception):
    """The ledger, the page or the arguments cannot be used; nothing is written."""


def spec_kinds(page: str = PAGE) -> frozenset:
    """The founder kinds tohum/26 lists; exactly one such list, or AssertionError rather than a guess."""
    with open(page, encoding="utf-8") as fh:
        found = re.findall(r"\*\*`founder` satırı:\*\*\s+`kind`\s+∈\s+\{([^}]*)\}", fh.read())
    if len(found) != 1:
        raise AssertionError("26 has %d founder kind lists, expected 1" % len(found))
    kinds = re.findall(r"`([^`]+)`", found[0])
    if not kinds or len(set(kinds)) != len(kinds):
        raise AssertionError("26's founder kind list is empty or repeats a kind: %r" % found[0])
    return frozenset(kinds)


def _judge(data: bytes, kinds: frozenset) -> tuple[list[dict], list[str], list[list[str]], dict[str, str]]:
    """The rows of ``data`` (a chain), the problems found, each row's meaning-rule breaks, and the open items each
    valid closer closed (item row_id -> closer row_id). A broken chain is the only problem then, with no rows."""
    verdict = chain.verify_bytes(data)
    if not verdict["valid"]:
        return [], ["chain: %s (line %s)" % (verdict["reason"], verdict["line"])], [], {}
    rows = [chain.parse_row(line.decode("utf-8")) for line in chain._lines(data)]
    out: list[str] = []
    breaks: list[list[str]] = []
    earlier: dict[str, int] = {}  # row_hash -> index of an earlier row
    for i, row in enumerate(rows):
        where = "line %d (%s)" % (i + 1, row.get("row_id"))
        out += FOUNDER_ROW(row, where)
        broken = []
        if row.get("part") != FOUNDER:
            broken.append("part %r is not founder" % row.get("part"))
        if row.get("kind") not in kinds:
            broken.append("kind %r is not one of 26's founder kinds" % row.get("kind"))
        if "supersedes" in row:
            j = earlier.get(row["supersedes"])
            if j is None:
                broken.append("supersedes names no earlier row")
            elif not breaks[j]:
                broken.append("supersedes names line %d, which breaks no meaning rule" % (j + 1))
        breaks.append(broken)
        earlier[row.get("row_hash")] = i
    items: dict[str, int] = {}  # row_id of an earlier seed_issue or blocked row -> its index
    closed: dict[str, str] = {}
    for i, row in enumerate(rows):
        where = "line %d (%s)" % (i + 1, row.get("row_id"))
        refs = row.get("payload", {}).get("refs") if isinstance(row.get("payload"), dict) else None
        names = [r[len(CLOSES):] for r in refs if isinstance(r, str) and r.startswith(CLOSES)] \
            if isinstance(refs, list) else []
        counts = not breaks[i] and not FOUNDER_ROW(row, "")
        for n, name in enumerate(names):
            if name not in items:
                out.append("%s: %s%s names no earlier seed_issue or blocked row" % (where, CLOSES, name))
            elif name in names[:n]:
                out.append("%s: %s%s is named twice" % (where, CLOSES, name))
            elif name in closed:
                out.append("%s: %s%s, already closed by %s" % (where, CLOSES, name, closed[name]))
            elif counts:
                closed[name] = row.get("row_id")
        if row.get("kind") in ITEM_KINDS and isinstance(row.get("row_id"), str):
            items.setdefault(row["row_id"], i)
    return rows, out, breaks, closed


def problems(data: bytes, kinds: frozenset) -> list[str]:
    rows, out, breaks, _ = _judge(data, kinds)
    closed = {row["supersedes"] for row, broken in zip(rows, breaks)
              if not broken and "supersedes" in row and not FOUNDER_ROW(row, "")}
    for i, (row, broken) in enumerate(zip(rows, breaks)):
        if broken and row.get("row_hash") not in closed:
            out += ["line %d (%s): %s, not closed" % (i + 1, row.get("row_id"), b) for b in broken]
    return out


def read_reports(directory: str = REPORTS) -> list[dict]:
    """Every ``<id>.json`` of the reports directory (tohum/26c), sorted by id; Unusable when one is not a JSON object
    with a string ``id`` equal to its file name's stem and a non-empty string ``state``. A missing directory has none."""
    if not os.path.isdir(directory):
        return []
    out = []
    for name in sorted(os.listdir(directory)):
        if not name.endswith(".json"):
            continue
        try:
            with open(os.path.join(directory, name), encoding="utf-8") as fh:
                report = cli.load(fh)
        except (OSError, ValueError) as exc:
            raise Unusable("report %s: %s" % (name, cli.cause(exc))) from None
        if not isinstance(report, dict) or report.get("id") != name[:-len(".json")] \
                or not isinstance(report.get("state"), str) or not report["state"]:
            raise Unusable("report %s: not an object with id %r and a state" % (name, name[:-len(".json")]))
        out.append(report)
    return out


class _NoGit(Exception):
    """git cannot be started."""


def _git(trust: list[str], top: str, *args: str) -> bytes | None:
    """git's stdout for ``git <trust> -C top args``, or None when git exits non-zero; _NoGit when git cannot
    start."""
    try:
        proc = subprocess.run(["git", *trust, "--literal-pathspecs", "-C", top, *args], stdin=subprocess.DEVNULL,
                              capture_output=True, env=git_env(dict(os.environ)))
    except OSError:
        raise _NoGit() from None
    return proc.stdout if proc.returncode == 0 else None


def _trust(directory: str) -> list[str]:
    """``-c safe.directory=<d>`` for the directory and each of its ancestors: git's ownership check passes for the
    repository holding the named directory and for no other."""
    out, d = [], os.path.realpath(directory)
    while True:
        out += ["-c", "safe.directory=%s" % d]
        if os.path.dirname(d) == d:
            return out
        d = os.path.dirname(d)


def _lines(data: bytes) -> list[bytes]:
    lines = data.split(b"\n")
    return lines[:-1] if lines[-1] == b"" else lines


def _read(path: str) -> bytes | None:
    """The file's bytes, or None when ``path`` is not a regular file (absent, a directory)."""
    if not os.path.isfile(path):
        return None
    with open(path, "rb") as fh:
        return fh.read()


def _file_at(trust: list[str], top: str, commit: str, path: str) -> bytes | None:
    """The bytes of the regular file at ``path`` in ``commit``'s tree, or None when there is none there (absent, a
    directory, a symbolic link, a submodule): the entry's mode from ``ls-tree``, read as ``loop.gitobj.canonical``
    reads it, then its blob."""
    listed = _git(trust, top, "ls-tree", "-z", "--full-tree", commit, "--", path) or b""
    entry = listed.split(b"\0")[0]
    meta, tab, name = entry.partition(b"\t")
    fields = meta.split(b" ")
    sha = fields[-1].decode("ascii", "replace")
    if not tab or name != path.encode("utf-8") or len(fields) != 3 or not SHA.fullmatch(sha) \
            or (canonical(fields[0]) or ("",))[0] != "file":
        return None
    return _git(trust, top, "cat-file", "blob", sha)


def _ref_check(trust: list[str], top: str, shallow: set[str], report_path: str, ref) -> dict:
    m = REF.match(ref) if isinstance(ref, str) else None
    path = m.group(1) if m else ""
    first = int(m.group(2)) if m else 0
    last = int(m.group(3) or first) if m else 0
    if not m or last < first or path.startswith("/") or ".." in path.split("/"):
        return {"status": "unknown", "why": "ref_unreadable"}
    report = os.path.relpath(report_path, top)
    filed = (_git(trust, top, "log", "-1", "--format=%H", "--", report) or b"").decode("ascii").strip()
    if not filed or _file_at(trust, top, filed, report) != _read(report_path):
        return {"status": "uncommitted"}
    out = {"filed": filed, "bounded": filed in shallow}
    then = _file_at(trust, top, filed, path)
    if then is None:
        return {"status": "unknown", "why": "page_absent_at_filing", **out}
    block = _lines(then)[first - 1:last]
    if len(block) != last - first + 1:
        return {"status": "unknown", "why": "line_out_of_range", **out}
    now = _read(os.path.join(top, path))
    if now is None:
        return {"status": "page_gone", **out}
    if now == then:
        return {"status": "page_unchanged", **out}
    lines = _lines(now)
    if lines[first - 1:last] == block:
        return {"status": "line_same", **out}
    starts = [i + 1 for i in range(len(lines) - len(block) + 1) if lines[i:i + len(block)] == block]
    if starts:
        return {"status": "line_moved", "lines": starts, **out}
    return {"status": "line_changed", **out}


def ref_checks(directory: str, reports: list[dict]) -> dict[str, dict]:
    """Each report's ``ref_check`` by id (see the module docstring, "Ref since filing")."""
    try:
        trust = _trust(directory)
        top = _git(trust, directory, "rev-parse", "--show-toplevel") if os.path.isdir(directory) else None
        if top is None:
            return {r["id"]: {"status": "unknown", "why": "not_in_git"} for r in reports}
        top = top.decode("utf-8").rstrip("\n")
        marks = _git(trust, top, "rev-parse", "--git-path", "shallow")
        shallow = set((_read(os.path.join(top, marks.decode("utf-8").rstrip("\n"))) or b"").decode("ascii").split()
                      ) if marks else set()
        base = os.path.realpath(directory)
        return {r["id"]: _ref_check(trust, top, shallow, os.path.join(base, r["id"] + ".json"), r.get("ref"))
                for r in reports}
    except _NoGit:
        return {r["id"]: {"status": "unknown", "why": "git_unavailable"} for r in reports}


def open_items(data: bytes, kinds: frozenset, reports: list[dict],
               checks: dict[str, dict] | None = None) -> tuple[list[dict], list[str]]:
    """The open items (see the module docstring) and the ledger's problems; no item is listed when there is one.
    ``checks`` (``ref_checks``'s) adds each report item's ``ref_check``."""
    rows, _, _, closed = _judge(data, kinds)
    found = problems(data, kinds)
    if found:
        return [], found
    items = [{"id": row["row_id"], "source": "ledger", "kind": row["kind"], "ts": row["ts"],
              "head": row["payload"]["summary"][:HEAD]}
             for row in rows if row["kind"] in ITEM_KINDS and row["row_id"] not in closed]
    items += [{"id": r["id"], "source": "report", "kind": r.get("kind"), "state": r["state"], "ref": r.get("ref"),
               **({"ref_check": checks[r["id"]]} if checks is not None else {})}
              for r in reports if r["state"] not in CLOSED_REPORT_STATES]
    return items, []


def next_row(data: bytes, kind: str, summary: str, refs: list[str], snapshot: str, ts: str,
             derivation: str = "llm_inference", trust: str = "inferred", supersedes: str | None = None) -> dict:
    """The row that follows the last row of ``data`` (a chain), hashed; its fields are not checked here."""
    lines = chain._lines(data)
    if lines:
        last = chain.parse_row(lines[-1].decode("utf-8"))
        m = ROW_ID.match(str(last.get("row_id")))
        if not m:
            raise Unusable("last row_id %r is not f<n>" % last.get("row_id"))
        row_id, prev = "f%d" % (int(m.group(1)) + 1), last.get("row_hash")
    else:
        row_id, prev = "f1", chain.ZERO_HASH
    row = {"row_id": row_id, "ts": ts, "part": FOUNDER, "kind": kind, "payload": {"summary": summary, "refs": refs},
           "derivation": derivation, "trust": trust, "snapshot_id": snapshot, "evidence_refs": [], "prev_hash": prev}
    if supersedes is not None:
        row["supersedes"] = supersedes
    row["row_hash"] = chain.row_hash(row)
    return row


def line_of(row: dict) -> bytes:
    return (json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")


def refusals(old: bytes, line: bytes, kinds: frozenset) -> list[str]:
    """Why ``line`` may not be added to ``old``: MF2's row scan, then any problem the new file has and ``old`` had
    not. Unusable when ``old`` is not a chain."""
    before = problems(old, kinds)
    if before and before[0].startswith("chain: "):
        raise Unusable("ledger_unusable: %s" % before[0])
    found = ["row_scan:%s:%s" % (m["rule"], m["sha256"]) for m in secrets.scan(line.decode("utf-8"), "row")]
    seen = set(before)
    return found + ["problem:%s" % p for p in problems(old + line, kinds) if p not in seen]


def append(path: str, row: dict, kinds: frozenset) -> list[str]:
    """Add ``row`` to the ledger at ``path`` unless ``refusals`` names a reason; return the reasons."""
    with open(path, "rb") as fh:
        old = fh.read()
    line = line_of(row)
    reasons = refusals(old, line, kinds)
    if reasons:
        return reasons
    fd, tmp = tempfile.mkstemp(prefix=".founder-", dir=os.path.dirname(os.path.abspath(path)))
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(old + line)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
    return []


# ---------------------------------------------------------------- command line

class _Parser(argparse.ArgumentParser):
    def error(self, message: str):
        raise Unusable("usage: %s" % message)


def _parser() -> argparse.ArgumentParser:
    p = _Parser(prog="python -m ledger.founder", add_help=False)
    sub = p.add_subparsers(dest="command", required=True, parser_class=_Parser)
    for name in ("check", "append", "open"):
        s = sub.add_parser(name, add_help=False)
        s.add_argument("--ledger", default=LEDGER)
        s.add_argument("--page", default=PAGE)
    sub.choices["open"].add_argument("--reports", default=REPORTS)
    a = sub.choices["append"]
    a.add_argument("--kind", required=True)
    a.add_argument("--summary", required=True)
    a.add_argument("--snapshot", required=True)
    a.add_argument("--ref", action="append", default=[])
    a.add_argument("--derivation", default="llm_inference")
    a.add_argument("--trust", default="inferred")
    a.add_argument("--supersedes")
    a.add_argument("--ts")
    return p


def _emit(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj, ensure_ascii=False, sort_keys=True) + "\n")


def main(argv: list[str], stdin=None) -> int:
    try:
        args = _parser().parse_args(argv)
        try:
            kinds = spec_kinds(args.page)
            with open(args.ledger, "rb") as fh:
                data = fh.read()
        except (OSError, AssertionError, UnicodeDecodeError) as exc:
            raise Unusable(cli.cause(exc)) from None
        if args.command == "check":
            found = problems(data, kinds)
            _emit({"ok": not found, "problems": found})
            return 1 if found else 0
        if args.command == "open":
            reports = read_reports(args.reports)
            items, found = open_items(data, kinds, reports, ref_checks(args.reports, reports))
            _emit({"ok": not found, "open": items, "problems": found})
            return 1 if found else 0
        summary = args.summary
        if summary == "-":
            try:
                summary = (stdin if stdin is not None else sys.stdin.buffer).read().decode("utf-8")
            except UnicodeDecodeError:
                raise Unusable("summary on stdin is not UTF-8") from None
            summary = summary[:-1] if summary.endswith("\n") else summary
        ts = args.ts or datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        try:
            row = next_row(data, args.kind, summary, args.ref, args.snapshot, ts, args.derivation, args.trust,
                           args.supersedes)
        except (chain.ChainError, UnicodeDecodeError) as exc:
            raise Unusable("ledger_unusable: %s" % cli.cause(exc)) from None
        reasons = append(args.ledger, row, kinds)
    except Unusable as exc:
        _emit({"ok": False, "error": cli.cause(exc)})
        return 2
    if reasons:
        _emit({"ok": False, "reasons": reasons})
        return 1
    _emit({"ok": True, "row_id": row["row_id"], "row_hash": row["row_hash"]})
    return 0


FAULT_LINE = {"ok": False, "error": "internal error"}


if __name__ == "__main__":
    sys.exit(cli.run(main, sys.argv[1:], FAULT_LINE))
