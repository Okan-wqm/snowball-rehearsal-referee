"""``gate.check``: the gate's pure merge decision over recorded ``koş`` results (stage 0, MF8).

Rules: asama-0/08 criteria 3-8 and the mapped line, asama-0/09 test 35, tohum/29h (group ``k0map``: the
command line, the run record, the reasons), tohum/04 (zero tests is red), tohum/07 (merges are serial, the
sentinel), tohum/08 item 3 (red control), tohum/01b (the gate reads results by artifact and hash), tohum/26a
(``gate.check`` calls ``secrets.scan`` on the diff, asama-0/14 ``calls`` 2 -> 8), 26c (``finding.json``;
``control.json``: a missing ``merge_paused`` is true).

Nothing here runs a tool or a test: the ``koş`` job ran them contained (MF3) and wrote three files, whose
sha256 the gate took outside the container. The gate checks the bytes against those hashes and decides.

The mapped line (asama-0/08), ``map_line``: the hunks of the block whose pre-image is ``PATH`` move a base
line ``L``. A hunk ``@@ -a,b +c,d @@`` (a missing count is 1) has the base range ``[a, a+b-1]`` and the
candidate range ``[c, c+d-1]``, context lines included. ``L`` in a base range maps to that hunk's whole
candidate range (``[]`` when ``d = 0``); any other ``L`` maps to ``[m, m]`` with ``m = L`` plus ``d - b`` of
every hunk that ends before ``L``. A hunk with ``b = 0`` (git writes ``-a,0`` for an insertion after line
``a``) has no base range; it lies between ``a`` and ``a+1`` and ends before ``L`` when ``a < L``. A path no
block changes maps to itself; a deleted path maps to ``[]``; a path the diff creates has no base line (unusable).
The diff parser (``gate.diffguard``, shared with MF7) checks every ``+`` start against the one git writes, so a
diff that lies about where its hunks land is unusable, not mapped.

The decision, ``decide``. Inputs: the candidate directory (``finding.json``, of which only ``rule_id``,
``path`` and ``line`` are read, and ``diff.patch``); ``base.jsonl``, three lint runs on the base tree;
the candidate run directory with ``cand.jsonl`` (three lint runs on the candidate tree) and ``checks.json``
``{tests: [{id, status: pass|fail}], red_control: pass|fail}``; ``hashes.json`` ``{"base.jsonl",
"cand.jsonl", "checks.json"}``, 64 lowercase hex each; stdin ``{control, unfinished_sentinels: [merge sha]}``.
A run file holds exactly three lines, one run record each, ``{tool, violations: [{rule_id, path, line,
fix: [first, last] | null}]}`` (``fix`` names base lines, both ends included); a rule that reads a run reads
the file's first line. Each reason, all of them written:

- ``artefact_hash_mismatch``: one of the three files is missing or its sha256 is not the one in
  ``hashes.json`` (each is checked). A file that fails its hash is not read: no rule that reads it is
  judged, every other rule is.
- ``target_not_found``: the first line of ``base.jsonl`` has no violation with the finding's ``rule_id``,
  ``path`` and ``line``. Without a target ``not_distinguished`` and ``scope_violation`` are not judged.
  With several, the first in the file is the target.
- ``not_distinguished``: the first line of ``cand.jsonl`` has a violation with the target's ``rule_id``
  and ``path`` whose line is in the target line's mapped range.
- ``tool_nondeterministic``: the three lines of ``base.jsonl`` or of ``cand.jsonl`` (both are checked) are
  not byte for byte the same.
- ``scope_violation``: the target's ``fix`` is ``null``; or the diff does anything but modify the
  finding's path in place (another path, a rename, copy, creation, deletion, mode change, binary patch); or
  a removed line's base number is outside ``[s, e]``; or an added line's base position ``p`` is outside
  ``s <= p <= e+1``. ``p`` is the base line that comes next in its hunk: ``a+b`` after the hunk's last base
  line, ``a+1`` in a ``b = 0`` hunk. Context lines are not judged.
- ``ratchet_increase``: a tool counts more violations in the first line of ``cand.jsonl`` than in that of
  ``base.jsonl`` (per tool, not per rule; a tool absent from a file counts 0).
- ``zero_tests``: ``tests`` is empty. ``tests_red``: a test has status ``fail``.
- ``red_control_green``: ``red_control`` is ``pass`` (the known-bad candidate passed).
- ``merge_paused``: ``control.merge_paused`` is not exactly ``false`` (``true``, missing or any other value).
- ``sentinel_pending``: ``unfinished_sentinels`` is not empty.
- ``secret_in_diff``: ``secrets.scan`` in its ``diff`` meaning finds a match in ``diff.patch`` (MF2).

The decision is ``merge`` only when there is no reason. Unusable input (exit 2, stdout ``{"decision":
"reject"}``, the cause on stderr): an unreadable ``finding.json``, ``diff.patch`` or ``hashes.json``, a diff
the parser refuses, a finding, run file (once its hash holds), ``checks.json`` or stdin not of the shapes
above. Fields beyond the ones read are ignored.

Not judged here: criterion 1's path rules (``gate.diffguard``); its check that the diff applies to
``brain/integration``'s head, which 29h gives this module, has no input in the decision yet (29h: no case
until it has one); criterion 2 for ledger rows and prompts; how a tool's
own output becomes a run record (the spec does not give it; whoever writes it must count suppressed
violations as violations, or a suppression comment passes the ratchet and the mapped-line rule); hunk
coverage (asama-0/08's ``hunk_covered`` is the loop's record, ``ledger.events.hunk_covered``, not part of this decision).

Command line, from ``referee/``; stdout is one JSON line::

    python -m gate.check map DIFF PATH LINE      {"mapped": [first, last] | []}; exit 0, 2 unusable
    python -m gate.check decide CAND_DIR BASE_JSONL CAND_RUN_DIR HASHES   (stdin as above)
        {"decision": "merge" | "reject", "reasons": [...]}; exit 0 merge, 1 reject, 2 unusable
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from typing import Any

from gate import diffguard
from gate import secrets
import cli

DiffError = diffguard.DiffError
RUN_LINES = 3
RUN_FILES = ("base.jsonl", "cand.jsonl", "checks.json")
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
STATUSES = ("pass", "fail")


class Unusable(ValueError):
    """Input the gate cannot decide on (exit 2)."""


# ---------------------------------------------------------------- the mapped line

def _block_of(blocks: list[dict], path: str) -> dict | None:
    hits = [b for b in blocks if b["old"] == path and b["kind"] != "copy"]
    if len(hits) > 1:
        raise DiffError("more than one block changes %r" % path)
    if any(b["kind"] == "create" and b["new"] == path for b in blocks):
        raise DiffError("%r is created by the diff, so it has no base line" % path)
    return hits[0] if hits else None


def map_line(blocks: list[dict], path: str, line: int) -> list[int]:
    """The candidate lines of base line ``line`` of ``path``: ``[first, last]`` or ``[]``; see the docstring."""
    if type(line) is not int or line < 1:
        raise DiffError("a base line is an integer from 1")
    block = _block_of(blocks, path)
    if block is None:
        return [line, line]
    if block["kind"] == "delete":
        return []
    shift = 0
    for h in block["hunks"]:
        a, b, c, d = h["old_start"], h["old_count"], h["new_start"], h["new_count"]
        if b and a <= line <= a + b - 1:
            return [c, c + d - 1] if d else []
        if (a + b - 1 if b else a) < line:
            shift += d - b
    return [line + shift, line + shift]


# ---------------------------------------------------------------- scope

def scope_violation(blocks: list[dict], path: str, fix: list[int] | None) -> bool:
    """True when the diff is not an in-place change of ``path`` confined to base lines ``fix``."""
    if fix is None or len(blocks) != 1:
        return True
    block = blocks[0]
    if block["old"] != path or block["new"] != path or block["binary"] or set(block["headers"]) - {"index"}:
        return True
    s, e = fix
    for h in block["hunks"]:
        pos = h["old_start"] if h["old_count"] else h["old_start"] + 1
        for tag, _, _ in h["lines"]:
            if tag == "+":
                if not s <= pos <= e + 1:
                    return True
                continue
            if tag == "-" and not s <= pos <= e:
                return True
            pos += 1
    return False


# ---------------------------------------------------------------- reading the inputs

def _plain(path: Any, what: str) -> str:
    if not isinstance(path, str) or not path or path.startswith("/") or "\\" in path \
            or any(p in ("", ".", "..") for p in path.split("/")):
        raise Unusable("%s must be a plain relative path" % what)
    return path


def _line_no(value: Any, what: str) -> int:
    if type(value) is not int or value < 1:
        raise Unusable("%s must be an integer >= 1" % what)
    return value


def _rule(value: Any, what: str) -> str:
    if not isinstance(value, str) or not value:
        raise Unusable("%s must be a non-empty string" % what)
    return value


def finding(doc: Any) -> dict:
    if not isinstance(doc, dict):
        raise Unusable("finding.json must be an object")
    return {"rule_id": _rule(doc.get("rule_id"), "finding.rule_id"), "path": _plain(doc.get("path"), "finding.path"),
            "line": _line_no(doc.get("line"), "finding.line")}


def _violation(v: Any, what: str) -> dict:
    if not isinstance(v, dict):
        raise Unusable("%s must be an object" % what)
    fix = v.get("fix")
    if fix is not None and not (isinstance(fix, list) and len(fix) == 2 and all(type(x) is int for x in fix)
                                and 1 <= fix[0] <= fix[1]):
        raise Unusable("%s.fix must be [first, last] base lines or null" % what)
    return {"rule_id": _rule(v.get("rule_id"), what + ".rule_id"), "path": _plain(v.get("path"), what + ".path"),
            "line": _line_no(v.get("line"), what + ".line"), "fix": fix}


def run_file(raw: bytes, name: str) -> tuple[dict, bool]:
    """``(the first line's run record, whether the three lines are byte-identical)``."""
    lines = raw.split(b"\n")
    if lines[-1] == b"":
        lines.pop()
    if len(lines) != RUN_LINES:
        raise Unusable("%s must hold exactly %d lines" % (name, RUN_LINES))
    try:
        rec = cli.loads(lines[0].decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise Unusable("%s line 1 is not JSON: %s" % (name, cli.cause(exc))) from exc
    if not isinstance(rec, dict) or not isinstance(rec.get("violations"), list):
        raise Unusable("%s line 1 must be {tool, violations: []}" % name)
    run = {"tool": _rule(rec.get("tool"), name + ".tool"),
           "violations": [_violation(v, "%s.violations[%d]" % (name, i)) for i, v in enumerate(rec["violations"])]}
    return run, all(line == lines[0] for line in lines)


def base_counts(base_run: bytes, base_run_sha256: str) -> dict:
    """``{reasons, counts}``: the lint totals of a base run file (``base.jsonl``) whose sha256 must be
    ``base_run_sha256`` (``base_run_hash_mismatch``) and whose three records must be one (``tool_nondeterministic``);
    ``counts`` is ``{tool: violations}`` of its first record (``_counts``, criterion 5's count), ``None`` with a
    reason. A file ``run_file`` refuses raises ``Unusable``. One reading for ``activate``'s ratchet base and the
    loop's (``loop.watch``: a merge's lint before, a sentinel's lint after)."""
    if hashlib.sha256(base_run).hexdigest() != base_run_sha256:
        return {"reasons": ["base_run_hash_mismatch"], "counts": None}
    run, same = run_file(base_run, "base.jsonl")
    if not same:
        return {"reasons": ["tool_nondeterministic"], "counts": None}
    return {"reasons": [], "counts": _counts(run)}


def checks_file(raw: bytes) -> dict:
    try:
        doc = cli.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise Unusable("checks.json is not JSON: %s" % cli.cause(exc)) from exc
    if not isinstance(doc, dict) or not isinstance(doc.get("tests"), list) or doc.get("red_control") not in STATUSES:
        raise Unusable("checks.json must be {tests: [], red_control: pass|fail}")
    for i, t in enumerate(doc["tests"]):
        if not isinstance(t, dict) or not isinstance(t.get("id"), str) or t.get("status") not in STATUSES:
            raise Unusable("checks.json tests[%d] must be {id, status: pass|fail}" % i)
    return doc


def hashes_file(doc: Any) -> dict:
    if not isinstance(doc, dict) or not all(isinstance(doc.get(k), str) and SHA256.match(doc[k]) for k in RUN_FILES):
        raise Unusable("hashes.json must give 64 lowercase hex for %s" % ", ".join(RUN_FILES))
    return doc


def request(doc: Any) -> dict:
    if not isinstance(doc, dict) or not isinstance(doc.get("control"), dict) \
            or not isinstance(doc.get("unfinished_sentinels"), list) \
            or not all(isinstance(s, str) for s in doc["unfinished_sentinels"]):
        raise Unusable("stdin must be {control: {}, unfinished_sentinels: [merge sha]}")
    return doc


# ---------------------------------------------------------------- the decision

def _counts(run: dict) -> dict[str, int]:
    return {run["tool"]: len(run["violations"])}


def decide(found: dict, diff_text: str, files: dict[str, bytes | None], hashes: dict, stdin: dict) -> dict:
    """The decision; see the module docstring. ``files`` maps each of ``RUN_FILES`` to its bytes or None
    (missing). Raises ``Unusable`` or ``DiffError`` on unusable input."""
    blocks = diffguard.parse(diff_text)
    reasons: list[str] = []
    verified = {}
    for name in RUN_FILES:
        raw = files.get(name)
        if raw is None or hashlib.sha256(raw).hexdigest() != hashes[name]:
            reasons.append("artefact_hash_mismatch")
        else:
            verified[name] = raw  # only a file whose hash holds is read
    runs = {}
    for name in ("base.jsonl", "cand.jsonl"):
        if name in verified:
            runs[name], same = run_file(verified[name], name)
            if not same:
                reasons.append("tool_nondeterministic")
    base, cand = runs.get("base.jsonl"), runs.get("cand.jsonl")
    if base is not None:
        targets = [v for v in base["violations"] if (v["rule_id"], v["path"], v["line"])
                   == (found["rule_id"], found["path"], found["line"])]
        if not targets:
            reasons.append("target_not_found")
        else:
            target = targets[0]
            if scope_violation(blocks, found["path"], target["fix"]):
                reasons.append("scope_violation")
            mapped = map_line(blocks, found["path"], found["line"])
            if cand is not None and mapped and any(
                    v["rule_id"] == target["rule_id"] and v["path"] == target["path"]
                    and mapped[0] <= v["line"] <= mapped[1] for v in cand["violations"]):
                reasons.append("not_distinguished")
    if base is not None and cand is not None:
        before = _counts(base)
        if any(n > before.get(tool, 0) for tool, n in _counts(cand).items()):
            reasons.append("ratchet_increase")
    if "checks.json" in verified:
        checks = checks_file(verified["checks.json"])
        if not checks["tests"]:
            reasons.append("zero_tests")
        if any(t["status"] == "fail" for t in checks["tests"]):
            reasons.append("tests_red")
        if checks["red_control"] == "pass":
            reasons.append("red_control_green")
    if stdin["control"].get("merge_paused") is not False:
        reasons.append("merge_paused")
    if stdin["unfinished_sentinels"]:
        reasons.append("sentinel_pending")
    if secrets.scan(diff_text, "diff"):
        reasons.append("secret_in_diff")
    reasons = sorted(set(reasons))
    return {"decision": "reject" if reasons else "merge", "reasons": reasons}


# ---------------------------------------------------------------- command line

def _emit(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj, sort_keys=True) + "\n")


def _text(path: str) -> str:
    with open(path, "rb") as fh:
        return fh.read().decode("utf-8", "surrogateescape")


def _json(path: str) -> Any:
    with open(path, encoding="utf-8") as fh:
        return cli.load(fh)


def _bytes_or_none(path: str) -> bytes | None:
    try:
        with open(path, "rb") as fh:
            return fh.read()
    except FileNotFoundError:
        return None


USAGE = "usage: python -m gate.check map DIFF PATH LINE | decide CAND_DIR BASE_JSONL CAND_RUN_DIR HASHES"


def _decide_cli(cand_dir: str, base_jsonl: str, cand_run_dir: str, hashes_path: str) -> dict:
    try:
        stdin = cli.loads(sys.stdin.read())
    except ValueError as exc:
        raise Unusable("stdin is not JSON: %s" % cli.cause(exc)) from exc
    files = {"base.jsonl": _bytes_or_none(base_jsonl),
             "cand.jsonl": _bytes_or_none(os.path.join(cand_run_dir, "cand.jsonl")),
             "checks.json": _bytes_or_none(os.path.join(cand_run_dir, "checks.json"))}
    return decide(finding(_json(os.path.join(cand_dir, "finding.json"))),
                  _text(os.path.join(cand_dir, "diff.patch")), files, hashes_file(_json(hashes_path)), request(stdin))


def main(argv: list[str]) -> int:
    mode = argv[0] if argv else None
    try:
        if len(argv) == 4 and mode == "map":
            if not re.fullmatch(r"[1-9][0-9]*", argv[3]):
                raise Unusable("LINE must be a positive integer")
            _emit({"mapped": map_line(diffguard.parse(_text(argv[1])), argv[2], int(argv[3]))})
            return 0
        if len(argv) == 5 and mode == "decide":
            result = _decide_cli(*argv[1:])
            _emit(result)
            return 0 if result["decision"] == "merge" else 1
        raise Unusable(USAGE)
    except (Unusable, DiffError, ValueError, OSError, RecursionError) as exc:
        cause = "unusable input: %s" % cli.cause(exc)
    _emit({"decision": "reject"} if mode == "decide" else {"error": cause})
    sys.stderr.write(cause + "\n")
    return 2


def FAULT_LINE(argv: list[str]) -> dict:  # noqa: N802 - cli.run's fault line, by command
    return {"decision": "reject"} if argv[:1] == ["decide"] else cli.GENERIC_LINE


if __name__ == "__main__":
    sys.exit(cli.run(main, sys.argv[1:], FAULT_LINE))
