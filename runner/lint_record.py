"""``lint_record``: the lint tool's own output, read with the tree it ran on, as the run record the gate reads
(stage 0; called by MF6 ``unit.verify``, which checks asama-0/08's unit criteria 4 and 5 with it).

Rules: asama-0/08 (unit selection, bold criteria 4 and 5, which MF4 and MF6 check mechanically: the lint tool
gives a rule id, a line and a machine-applicable ``fix``; the unit has a fixable violation outside the security
path; criterion 5 of the acceptance rule counts violations per tool), ``gate.check`` (MF8: the run record
``{tool, violations: [{rule_id, path, line, fix: [first, last] | null}]}``, ``fix`` in base lines, both ends
included, and its note that suppressed violations must count), tohum/26c (``finding.json`` ``fix_range``),
asama-0/01 (``koş`` runs the tool in the container whose worktree is ``/work``).

**The input.** Stage 0 has one ecosystem (npm) and one lint output: ESLint's ``json`` formatter, i.e. the
recipe's ``lint_cmd`` carries ``--format json``. ``output`` is the command's stdout bytes: a JSON array of
results, each ``{filePath, messages: [...], suppressedMessages: [...], source?, ...}``; a message ``{ruleId:
string | null, fatal?, severity: 1 | 2, line, column, fix?: {range: [start, end], text}}``. ``tree`` is the
worktree the tool read, on the host; ``root`` its path inside the container (``/work``). Any other output is
refused (``not_eslint_json``); other formatters and tools are out of scope.

**The record** (``record``), ``{tool: "eslint", violations}``, one violation per message of
``messages`` and of ``suppressedMessages`` (a suppressed violation is still a violation: otherwise a
suppression comment would lower the ratchet's count and hide the target), files in output order, each file's
messages before its suppressed ones, each list in output order:

- ``path``: ``filePath`` relative to ``root``, ``/``-separated as written.
- ``rule_id``: ``ruleId``; a non-fatal message without one (an unused disable directive, an unused inline
  configuration) gets ``NO_RULE``. A rule really named ``NO_RULE`` would share its id; no ESLint core rule is.
- ``line``: the git line (lines end at ``\\n`` only) of the message's position. ESLint numbers lines with
  every ``\\r\\n``, ``\\r``, ``\\n``, U+2028 and U+2029 as a break and columns in UTF-16 code units of the text
  without its leading byte order mark; the position is that offset, and its git line is one plus the number of
  ``\\n`` before it. So a file with a lone ``\\r`` or a U+2028 gets the git line the diff and the gate use.
- ``fix``: ``null`` without ``fix`` (suggestions are not fixes). Else, for the range ``[s, e)`` in the same
  offsets: ``first`` is the git line of ``s``; ``last`` is the git line of ``e - 1``, or ``first`` when
  ``s == e``; when the last replaced unit is a ``\\n`` and ``text`` does not end with ``\\n`` the next line is
  joined to the edited one, so ``last`` is the git line of ``e``, at most the file's last line.

Every reason (refusal; no record): ``not_eslint_json`` (not UTF-8 JSON of the shape above, a missing
``suppressedMessages`` included: such a tool does not report suppressions); ``path_outside_root:<filePath>``
(not under ``root``, or a ``.``, ``..`` or empty component, or a ``\\``); ``file_unreadable:<path>`` (a
reported file that is not a regular file of ``tree`` with no symlink on its way); ``source_not_utf8:<path>``;
``source_mismatch:<path>`` (``source``, when ESLint gives it, differs from the file's text: the tool read
another tree); ``fatal:<path>`` (a parse error: the file was not judged, so its violations would vanish from
the count; the caller treats the run as failed); ``message_unusable:<path>`` (a message's rule id, severity,
line, column or fix range is not a valid value for that file). Files without messages are not read.

Out of scope, stated: whether a minimal diff of the fixed file stays in ``[first, last]`` when lines repeat
(git may place an identical line's removal elsewhere; the candidate's author writes ``diff.patch``), tools
other than ESLint, and checking that ``fix.text`` is what the candidate applies (``gate.check`` judges the diff
against the range, not the text).

``run_file`` writes the records of the three runs as the run file ``gate.check`` reads (``base.jsonl``,
``cand.jsonl``): one canonical JSON line each.

Command line, from ``referee/``; stdin the tool's stdout; one JSON line on stdout::

    python -m runner.lint_record TREE [ROOT]     {ok, reasons, record}; exit 0 record, 1 refused, 2 usage
"""

from __future__ import annotations

import array
import bisect
import json
import os
import sys
from typing import Any

from profile import derive as D
import cli

TOOL = "eslint"
NO_RULE = "eslint:no-rule-id"
CONTAINER_ROOT = "/work"
BOM = "\ufeff"
NL, CR, LS, PS = 0x0A, 0x0D, 0x2028, 0x2029
USAGE = "usage: python -m runner.lint_record TREE [ROOT]   (stdin: ESLint --format json output)"


class RecordError(ValueError):
    def __init__(self, reasons: list[str]):
        super().__init__(", ".join(reasons))
        self.reasons = reasons


class _Text:
    """One file's text in ESLint's offsets (UTF-16 units, BOM removed) with both line systems."""

    def __init__(self, text: str):
        if text.startswith(BOM):
            text = text[1:]
        units = array.array("H")
        units.frombytes(text.encode("utf-16-le"))
        if sys.byteorder == "big":
            units.byteswap()
        self.units = units
        self.newlines = [i for i, u in enumerate(units) if u == NL]
        starts = [0]
        n = len(units)
        for i, u in enumerate(units):
            if u == NL or u in (LS, PS) or (u == CR and not (i + 1 < n and units[i + 1] == NL)):
                starts.append(i + 1)
        self.eslint_starts = starts
        self.last_line = len(self.newlines) + (1 if n > (self.newlines[-1] + 1 if self.newlines else 0) else 0)

    def git_line(self, offset: int) -> int:
        return 1 + bisect.bisect_left(self.newlines, offset)

    def offset(self, line: Any, column: Any) -> int | None:
        if not (_int(line) and _int(column) and line <= len(self.eslint_starts)):
            return None
        off = self.eslint_starts[line - 1] + column - 1
        return off if off <= len(self.units) else None

    def fix(self, fix: Any) -> list[int] | None:
        """``[first, last]`` git lines of a fix, or None when the fix is not a valid range of this text."""
        if not isinstance(fix, dict) or not isinstance(fix.get("text"), str):
            return None
        rng = fix.get("range")
        if not (isinstance(rng, list) and len(rng) == 2 and all(type(x) is int for x in rng)
                and 0 <= rng[0] <= rng[1] <= len(self.units)):
            return None
        s, e = rng
        first = self.git_line(s)
        if s == e:
            return [first, first]
        if self.units[e - 1] == NL and not fix["text"].endswith("\n"):
            return [first, max(first, min(self.git_line(e), self.last_line))]
        return [first, self.git_line(e - 1)]


def _int(v: Any) -> bool:
    return type(v) is int and v >= 1


def _relative(file_path: Any, root: str) -> str | None:
    prefix = root.rstrip("/") + "/"
    if not isinstance(file_path, str) or not file_path.startswith(prefix) or "\\" in file_path:
        return None
    rel = file_path[len(prefix):]
    if any(part in ("", ".", "..") for part in rel.split("/")):
        return None
    return rel


def _results(output: bytes) -> list[dict]:
    try:
        doc = cli.loads(output.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, RecursionError) as exc:
        raise RecordError(["not_eslint_json"]) from exc
    ok = isinstance(doc, list) and all(
        isinstance(r, dict) and isinstance(r.get("filePath"), str)
        and all(isinstance(r.get(k), list) and all(isinstance(m, dict) for m in r[k])
                for k in ("messages", "suppressedMessages"))
        and ("source" not in r or isinstance(r["source"], str))
        for r in doc)
    if not ok:
        raise RecordError(["not_eslint_json"])
    return doc


def _violation(msg: dict, text: _Text) -> dict | None:
    rule = msg.get("ruleId")
    if not ((isinstance(rule, str) and rule) or rule is None) or msg.get("severity") not in (1, 2):
        return None
    off = text.offset(msg.get("line"), msg.get("column"))
    if off is None:
        return None
    fix = None
    if "fix" in msg and msg["fix"] is not None:
        fix = text.fix(msg["fix"])
        if fix is None:
            return None
    return {"rule_id": rule if rule is not None else NO_RULE, "path": None, "line": text.git_line(off), "fix": fix}


def record(output: bytes, tree: str, root: str = CONTAINER_ROOT) -> dict:
    """The run record of one lint run; raises ``RecordError`` with every reason (see the module docstring)."""
    reasons: list[str] = []
    violations: list[dict] = []
    for result in _results(output):
        rel = _relative(result["filePath"], root)
        if rel is None:
            reasons.append("path_outside_root:%s" % result["filePath"])
            continue
        messages = result["messages"] + result["suppressedMessages"]
        if not messages:
            continue
        if any(m.get("fatal") is True for m in messages):
            reasons.append("fatal:%s" % rel)
            continue
        raw = D._read_regular(tree, rel)
        if raw is None:
            reasons.append("file_unreadable:%s" % rel)
            continue
        try:
            source = raw.decode("utf-8")
        except UnicodeDecodeError:
            reasons.append("source_not_utf8:%s" % rel)
            continue
        if "source" in result and result["source"] != source:
            reasons.append("source_mismatch:%s" % rel)
            continue
        text = _Text(source)
        found = [_violation(m, text) for m in messages]
        if any(v is None for v in found):
            reasons.append("message_unusable:%s" % rel)
            continue
        violations.extend(dict(v, path=rel) for v in found)
    if reasons:
        raise RecordError(sorted(set(reasons)))
    return {"tool": TOOL, "violations": violations}


def line(rec: dict) -> bytes:
    return json.dumps(rec, sort_keys=True, separators=(",", ":")).encode("ascii")


def run_file(records: list[dict]) -> bytes:
    """The run file of ``gate.check`` (``base.jsonl``/``cand.jsonl``): one line per run, in run order."""
    return b"".join(line(r) + b"\n" for r in records)


def main(argv: list[str]) -> int:
    if len(argv) not in (1, 2) or not os.path.isdir(argv[0]):
        sys.stderr.write(USAGE + "\n")
        return 2
    try:
        rec = record(sys.stdin.buffer.read(), argv[0], argv[1] if len(argv) == 2 else CONTAINER_ROOT)
    except RecordError as exc:
        sys.stdout.write(json.dumps({"ok": False, "reasons": exc.reasons, "record": None}, sort_keys=True) + "\n")
        return 1
    sys.stdout.write(json.dumps({"ok": True, "reasons": [], "record": rec}, sort_keys=True) + "\n")
    return 0


FAULT_LINE = cli.GENERIC_LINE


if __name__ == "__main__":
    sys.exit(cli.run(main, sys.argv[1:], FAULT_LINE))
