"""MF8 gate.check: the pure decision of asama-0/08 items 3-8 and the mapped-line rule (asama-0/08:26-31).

    python -m gate.check map <diff.patch> <path> <line>                                -> {"mapped": [first, last] | []}
    python -m gate.check decide <candidate_dir> <base_runs.jsonl> <candidate_runs_dir> <hashes.json>
                                                (stdin: {control, unfinished_sentinels}) -> {"decision", "reasons"}
"""

from __future__ import annotations

import hashlib
import os
import re
import sys
from typing import Any

from . import secrets
from ._strict import Unusable, emit, is_int, is_str_list, loads, read, split_lines

HUNK = re.compile(r"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(?: .*)?")
# extended header lines git writes between `diff --git` and the first hunk
HEADER_PREFIXES = ("index ", "old mode ", "new mode ", "deleted file mode ", "new file mode ", "similarity index ",
                   "dissimilarity index ", "rename from ", "rename to ", "copy from ", "copy to ", "--- ", "+++ ",
                   "Binary files ")


# --- diff ----------------------------------------------------------------------------------------------------

def _block_paths(line: str) -> tuple[str, str]:
    rest = line[len("diff --git "):]
    if not rest.startswith("a/"):
        raise Unusable("diff --git header without a/ path")
    cuts = [m.start() for m in re.finditer(" b/", rest)]
    pairs = [(rest[2:cut], rest[cut + 3:]) for cut in cuts]
    pairs = [(a, b) for a, b in pairs if a and b]
    if len(pairs) > 1:
        pairs = [(a, b) for a, b in pairs if a == b]
    if len(pairs) != 1:
        raise Unusable("diff --git header paths not readable")
    return pairs[0]


def parse_diff(text: str) -> list[dict[str, Any]]:
    """Blocks of a unified git diff: {"a", "b", "hunks": [{"a", "b", "c", "d", "lines": [(tag, text)]}]}.
    A `diff --git a/A b/B` block changes B (tohum/29k:42-43)."""
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    blocks: list[dict[str, Any]] = []
    i, n = 0, len(lines)
    while i < n:
        if not lines[i].startswith("diff --git "):
            raise Unusable(f"diff line {i + 1}: expected a diff --git header")
        old, new = _block_paths(lines[i])
        block: dict[str, Any] = {"a": old, "b": new, "hunks": []}
        blocks.append(block)
        i += 1
        while i < n and not lines[i].startswith(("@@", "diff --git ")):
            if not lines[i].startswith(HEADER_PREFIXES):
                raise Unusable(f"diff line {i + 1}: not a header line")
            i += 1
        while i < n and lines[i].startswith("@@"):
            m = HUNK.fullmatch(lines[i])
            if not m:
                raise Unusable(f"diff line {i + 1}: bad hunk header")
            a, c = int(m.group(1)), int(m.group(3))
            b = int(m.group(2)) if m.group(2) is not None else 1
            d = int(m.group(4)) if m.group(4) is not None else 1
            if (b > 0 and a < 1) or (d > 0 and c < 1):
                raise Unusable(f"diff line {i + 1}: hunk starts at line 0")
            i += 1
            left_b, left_d, body = b, d, []
            while left_b > 0 or left_d > 0:
                if i >= n:
                    raise Unusable("diff ends inside a hunk")
                line = lines[i]
                tag = line[:1]
                if tag == " ":
                    left_b, left_d = left_b - 1, left_d - 1
                elif tag == "-":
                    left_b -= 1
                elif tag == "+":
                    left_d -= 1
                elif tag != "\\":
                    raise Unusable(f"diff line {i + 1}: not a hunk line")
                if left_b < 0 or left_d < 0:
                    raise Unusable(f"diff line {i + 1}: hunk longer than its header")
                if tag != "\\":
                    body.append((tag, line[1:]))
                i += 1
            while i < n and lines[i].startswith("\\"):  # "\ No newline at end of file"
                i += 1
            block["hunks"].append({"a": a, "b": b, "c": c, "d": d, "lines": body})
        if i < n and not lines[i].startswith("diff --git "):
            raise Unusable(f"diff line {i + 1}: text after the hunks")
    for path in {blk["b"] for blk in blocks}:
        hunks_of(blocks, path)  # each path's hunks in order, not overlapping
    return blocks


def _base_span(h: dict[str, Any]) -> tuple[int, int]:
    """The hunk's base range in half-lines; a b = 0 hunk sits between base lines a and a + 1."""
    if h["b"] > 0:
        return 2 * h["a"], 2 * (h["a"] + h["b"] - 1)
    return 2 * h["a"] + 1, 2 * h["a"] + 1


def hunks_of(blocks: list[dict[str, Any]], path: str) -> list[dict[str, Any]]:
    hunks = [h for blk in blocks if blk["b"] == path for h in blk["hunks"]]
    for prev, cur in zip(hunks, hunks[1:]):
        if _base_span(cur)[0] <= _base_span(prev)[1]:
            raise Unusable(f"hunks of {path} overlap or are out of order")
    return hunks


def mapped(hunks: list[dict[str, Any]], line: int) -> list[int]:
    """asama-0/08:26-29: inside a hunk's base range -> that hunk's whole candidate range ([] when d = 0);
    otherwise line + sum(d - b) over the hunks whose base range ends before it."""
    for h in hunks:
        if h["b"] > 0 and h["a"] <= line <= h["a"] + h["b"] - 1:
            return [h["c"], h["c"] + h["d"] - 1] if h["d"] > 0 else []
    shift = 0
    for h in hunks:
        ends_before = (h["a"] + h["b"] - 1 < line) if h["b"] > 0 else (h["a"] < line)
        if ends_before:
            shift += h["d"] - h["b"]
    return [line + shift, line + shift]


def _positive_line(text: str) -> int:
    if not (text.isascii() and text.isdigit()) or int(text) < 1:
        raise Unusable("line is not a positive integer")
    return int(text)


def _diff_text(path: str) -> str:
    try:
        return read(path).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise Unusable("diff is not UTF-8") from exc


def cmd_map(argv: list[str]) -> None:
    if len(argv) != 3:
        emit({"mapped": None, "error": "usage: map <diff.patch> <path> <line>"}, 2)
    try:
        line = _positive_line(argv[2])
        hunks = hunks_of(parse_diff(_diff_text(argv[0])), argv[1])
    except Unusable as exc:
        emit({"mapped": None, "error": str(exc)}, 2)
    emit({"mapped": mapped(hunks, line)}, 0)


# --- decide --------------------------------------------------------------------------------------------------

KOS_FILES = ("base.jsonl", "cand.jsonl", "checks.json")


def _violation(v: Any) -> bool:
    if not isinstance(v, dict):
        return False
    fix = v.get("fix", "absent")
    fix_ok = fix is None or (isinstance(fix, list) and len(fix) == 2 and all(is_int(x) for x in fix))
    return (isinstance(v.get("rule_id"), str) and isinstance(v.get("path"), str) and is_int(v.get("line"))
            and v["line"] >= 1 and fix_ok)


def _runs(data: bytes, name: str) -> tuple[list[bytes], dict[str, Any]]:
    """Exactly three run lines {tool, violations[]}; returns the raw lines and the first run."""
    lines = split_lines(data)
    if len(lines) != 3:
        raise Unusable(f"{name} has {len(lines)} lines, not 3")
    runs = []
    for number, line in enumerate(lines, start=1):
        run = loads(line)
        if not (isinstance(run, dict) and isinstance(run.get("tool"), str) and isinstance(run.get("violations"), list)
                and all(_violation(v) for v in run["violations"])):
            raise Unusable(f"{name} line {number} is not a lint run")
        runs.append(run)
    return lines, runs[0]


def _checks(data: bytes) -> dict[str, Any]:
    checks = loads(data)
    ok = (isinstance(checks, dict) and isinstance(checks.get("tests"), list)
          and all(isinstance(t, dict) and isinstance(t.get("id"), str) and t.get("status") in ("pass", "fail")
                  for t in checks["tests"])
          and checks.get("red_control") in ("pass", "fail"))
    if not ok:
        raise Unusable("checks.json is not {tests: [{id, status}], red_control}")
    return checks


def _finding(path: str) -> dict[str, Any]:
    finding = loads(read(path))
    if not (isinstance(finding, dict) and isinstance(finding.get("rule_id"), str)
            and isinstance(finding.get("path"), str) and is_int(finding.get("line")) and finding["line"] >= 1):
        raise Unusable("finding.json has no rule_id, path and positive line")
    return finding


def _out_of_scope(blocks: list[dict[str, Any]], path: str, fix: Any) -> bool:
    if fix is None:
        return True
    if any(blk["a"] != path or blk["b"] != path for blk in blocks):
        return True  # the diff touches another path
    start, end = fix
    for blk in blocks:
        for h in blk["hunks"]:
            base = h["a"] if h["b"] > 0 else h["a"] + 1  # the next base line of the hunk
            for tag, _ in h["lines"]:
                if tag == " ":
                    base += 1
                elif tag == "-":
                    if not start <= base <= end:
                        return True
                    base += 1
                elif tag == "+" and not start <= base <= end + 1:
                    return True
    return False


def _counts(run: dict[str, Any]) -> dict[str, int]:
    return {run["tool"]: len(run["violations"])}


def decide(cand_dir: str, base_path: str, runs_dir: str, hashes_path: str, stdin: bytes) -> list[str]:
    finding = _finding(os.path.join(cand_dir, "finding.json"))
    diff_text = _diff_text(os.path.join(cand_dir, "diff.patch"))
    blocks = parse_diff(diff_text)
    request = loads(stdin)
    if not (isinstance(request, dict) and isinstance(request.get("control"), dict)
            and is_str_list(request.get("unfinished_sentinels"))):
        raise Unusable("stdin is not {control: {...}, unfinished_sentinels: [...]}")
    manifest = loads(read(hashes_path))
    if not isinstance(manifest, dict):
        raise Unusable("hashes.json is not an object")

    reasons: set[str] = set()
    paths = {"base.jsonl": base_path, "cand.jsonl": os.path.join(runs_dir, "cand.jsonl"),
             "checks.json": os.path.join(runs_dir, "checks.json")}
    data: dict[str, bytes | None] = {}
    for name in KOS_FILES:
        try:
            data[name] = read(paths[name])
        except Unusable:
            data[name] = None
        if data[name] is None or manifest.get(name) != hashlib.sha256(data[name]).hexdigest():
            reasons.add("artefact_hash_mismatch")

    base = _runs(data["base.jsonl"], "base.jsonl") if data["base.jsonl"] is not None else None
    cand = _runs(data["cand.jsonl"], "cand.jsonl") if data["cand.jsonl"] is not None else None
    checks = _checks(data["checks.json"]) if data["checks.json"] is not None else None

    for runs in (base, cand):
        if runs is not None and len(set(runs[0])) != 1:
            reasons.add("tool_nondeterministic")

    if base is not None:
        target = next((v for v in base[1]["violations"] if v["rule_id"] == finding["rule_id"]
                       and v["path"] == finding["path"] and v["line"] == finding["line"]), None)
        if target is None:
            reasons.add("target_not_found")
        else:
            hunks = hunks_of(blocks, target["path"])
            span = mapped(hunks, target["line"])
            if cand is not None and span and any(
                    v["rule_id"] == target["rule_id"] and v["path"] == target["path"] and span[0] <= v["line"] <= span[1]
                    for v in cand[1]["violations"]):
                reasons.add("not_distinguished")
            if _out_of_scope(blocks, target["path"], target["fix"]):
                reasons.add("scope_violation")

    if base is not None and cand is not None:
        before, after = _counts(base[1]), _counts(cand[1])
        if any(count > before.get(tool, 0) for tool, count in after.items()):
            reasons.add("ratchet_increase")

    if checks is not None:
        if not checks["tests"]:
            reasons.add("zero_tests")
        if any(t["status"] == "fail" for t in checks["tests"]):
            reasons.add("tests_red")
        if checks["red_control"] == "pass":
            reasons.add("red_control_green")

    if request["control"].get("merge_paused") is not False:
        reasons.add("merge_paused")
    if request["unfinished_sentinels"]:
        reasons.add("sentinel_pending")
    if secrets.scan_text(diff_text):  # this brain's MF2 (29f: the diff's whole text)
        reasons.add("secret_in_diff")
    return sorted(reasons)


def cmd_decide(argv: list[str]) -> None:
    if len(argv) != 4:
        emit({"decision": "reject", "error": "usage: decide <candidate_dir> <base_runs.jsonl> <candidate_runs_dir> "
                                            "<hashes.json>"}, 2)
    try:
        reasons = decide(*argv, sys.stdin.buffer.read())
    except Unusable as exc:
        emit({"decision": "reject", "error": str(exc)}, 2)
    emit({"decision": "reject" if reasons else "merge", "reasons": reasons}, 1 if reasons else 0)


def main(argv: list[str]) -> None:
    if argv[:1] == ["map"]:
        cmd_map(argv[1:])
    if argv[:1] == ["decide"]:
        cmd_decide(argv[1:])
    emit({"error": "usage: map ... | decide ..."}, 2)


if __name__ == "__main__":
    main(sys.argv[1:])
