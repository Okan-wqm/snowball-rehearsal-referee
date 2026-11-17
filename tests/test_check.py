"""Test 35 (asama-0/09) and group ``k0map`` (tohum/29d, 29h): ``gate.check``, the pure merge decision.

- the mapped line (asama-0/08) on two real git diffs of one change (``-U0`` and ``-U2``), each line checked
  against the post-image file built by an applier written here, not only against expected numbers; the
  29h cases (shift, inside a hunk, insertion point, deleted line, after pure hunks); renames, deletions,
  untouched paths, a copy (its source does not move), two blocks of one path (unusable); the parser refuses a
  hunk whose ``+`` start is not the one git writes;
- criteria 3-8 over the seed's run records (``base.jsonl``, ``cand.jsonl``, ``checks.json``, ``hashes.json``,
  stdin), each reason from its own case and alone where it can be alone: target not found, not
  distinguished (inside a hunk, behind an insertion), nondeterministic base and candidate, scope (removed
  line, inserted line at ``e+1`` and past it, ``b = 0`` hunks, other path, rename, mode, ``fix`` null,
  context ignored), ratchet per tool, zero tests, red tests, red control green, ``merge_paused`` for every
  value but ``false``, a pending sentinel, a secret in the diff, every hash, a forged run and forged checks
  are not read; a deleted target line is distinguished; the target's rule, path and mapped range each bound
  ``not_distinguished``; each reason once; each shape rule of the inputs refused on its own case; the good
  candidate merges;
- the command line: one JSON line, exit 0 / 1 / 2, ``{"decision": "reject"}`` on unusable input, never a
  traceback; a diff's bytes that are not UTF-8 are decided on; each exit 2 is the module's own refusal
  (``refusal.assert_refused`` with the stderr cause, since decide's refusal line is its fault line by design), and
  a crash in ``decide`` still prints a reject.

Kept mutants: ``tests/mutants/check.json``. Shown equivalent, so not kept: ``_plain``'s ``startswith("/")`` and
``not path`` (a leading ``/`` and the empty path both give an empty part), ``scope_violation``'s ``old != path``
(``gate.diffguard`` gives ``old != new`` only with rename or copy headers, which the headers rule refuses).
"""

from __future__ import annotations

import difflib
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO

REFEREE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REFEREE)

from gate import check as C  # noqa: E402
from gate import diffguard as G  # noqa: E402
import cli  # noqa: E402
import refusal  # noqa: E402

CAUSE = r"(?m)^unusable input: "  # gate.check's own refusal on stderr; its decide line equals its fault line

# One change made with git 2.x and printed by ``git diff -U0`` and ``git diff -U2``: line 3 modified, two
# lines inserted after line 6, lines 12-13 deleted, the last line modified and left without a newline.
OLD_M = "".join("line %d\n" % i for i in range(1, 26))
NEW_M = ("line 1\nline 2\nline 3 changed\nline 4\nline 5\nline 6\ninserted A\ninserted B\n"
         + "".join("line %d\n" % i for i in range(7, 12)) + "".join("line %d\n" % i for i in range(14, 25))
         + "line 25 last")
DIFF_U0 = """diff --git a/m.js b/m.js
index 086df9f..40db0c4 100644
--- a/m.js
+++ b/m.js
@@ -3 +3 @@ line 2
-line 3
+line 3 changed
@@ -6,0 +7,2 @@ line 6
+inserted A
+inserted B
@@ -12,2 +13,0 @@ line 11
-line 12
-line 13
@@ -25 +25 @@ line 24
-line 25
+line 25 last
\\ No newline at end of file
"""
DIFF_U2 = """diff --git a/m.js b/m.js
index 086df9f..40db0c4 100644
--- a/m.js
+++ b/m.js
@@ -1,8 +1,10 @@
 line 1
 line 2
-line 3
+line 3 changed
 line 4
 line 5
 line 6
+inserted A
+inserted B
 line 7
 line 8
@@ -10,6 +12,4 @@ line 9
 line 10
 line 11
-line 12
-line 13
 line 14
 line 15
@@ -23,3 +23,3 @@ line 22
 line 23
 line 24
-line 25
+line 25 last
\\ No newline at end of file
"""



def _split(text):
    parts = text.split("\n")
    lines = [(p, True) for p in parts[:-1]]
    if parts[-1]:
        lines.append((parts[-1], False))
    return lines


def apply_block(block, source):
    """The post-image of ``source`` under ``block``'s hunks: a second computation of where lines land,
    independent of ``map_line``; None when a context or removed line differs from ``source``."""
    base = _split(source)
    out, cursor = [], 0
    for h in block["hunks"]:
        start = h["old_start"] - 1 if h["old_count"] else h["old_start"]
        if start < cursor or start > len(base):
            return None
        out.extend(base[cursor:start])
        cursor = start
        for tag, text, eol in h["lines"]:
            if tag == "+":
                out.append((text, eol))
                continue
            if cursor >= len(base) or base[cursor] != (text, eol):
                return None
            if tag == " ":
                out.append((text, eol))
            cursor += 1
    out.extend(base[cursor:])
    return "".join(t + ("\n" if eol else "") for t, eol in out)


def run_cli_err(*args, stdin=""):
    """``(exit, the one JSON line, stderr)``."""
    proc = subprocess.run([sys.executable, "-m", "gate.check", *args], cwd=REFEREE, capture_output=True,
                          text=True, input=stdin, timeout=60)
    lines = proc.stdout.split("\n")
    assert "Traceback" not in proc.stderr, proc.stderr
    assert proc.stdout.count("\n") == 1, proc.stdout
    return proc.returncode, json.loads(lines[0]), proc.stderr


def run_cli(*args, stdin=""):
    return run_cli_err(*args, stdin=stdin)[:2]


def file_diff(path, old, new, n=0, a=None, b=None):
    body = list(difflib.unified_diff(old.splitlines(True), new.splitlines(True), "a/" + (a or path),
                                     "b/" + (b or path), n=n))
    assert body, "no change"
    return "diff --git a/%s b/%s\nindex 1111111..2222222 100644\n" % (a or path, b or path) + "".join(body)


def mapped(diff, path, line):
    return C.map_line(G.parse(diff), path, line)


class MappedLine(unittest.TestCase):

    def test_real_diffs_expected_numbers(self):
        u0 = {1: [1, 1], 2: [2, 2], 3: [3, 3], 6: [6, 6], 7: [9, 9], 11: [13, 13], 12: [], 13: [],
              14: [14, 14], 24: [24, 24], 25: [25, 25]}
        u2 = {1: [1, 10], 8: [1, 10], 9: [11, 11], 10: [12, 15], 15: [12, 15], 16: [16, 16], 22: [22, 22],
              23: [23, 25], 25: [23, 25]}
        for diff, table in ((DIFF_U0, u0), (DIFF_U2, u2)):
            for line, want in table.items():
                self.assertEqual(mapped(diff, "m.js", line), want, (diff[:60], line))

    def test_real_diffs_against_the_files(self):
        old, new = OLD_M.split("\n"), NEW_M.split("\n")
        for diff in (DIFF_U0, DIFF_U2):
            blocks = G.parse(diff)
            self.assertEqual(apply_block(blocks[0], OLD_M), NEW_M)
            hunks = blocks[0]["hunks"]
            for line in range(1, 26):
                m = C.map_line(blocks, "m.js", line)
                inside = [h for h in hunks if h["old_count"] and h["old_start"] <= line < h["old_start"] + h["old_count"]]
                if inside:
                    want = [t for tag, t, _ in inside[0]["lines"] if tag != "-"]
                    self.assertEqual(new[m[0] - 1:m[1]] if m else [], want, line)
                else:
                    self.assertEqual(m[0], m[1])
                    self.assertEqual(new[m[0] - 1], old[line - 1], line)

    def test_seed_cases(self):
        old = "".join("l%d\n" % i for i in range(1, 11))
        # map_shift: a line after a hunk moves by that hunk's net count; one before it does not
        d = file_diff("f", old, old.replace("l3\n", "l3a\nl3b\nl3c\n"))
        self.assertEqual((mapped(d, "f", 2), mapped(d, "f", 7)), ([2, 2], [9, 9]))
        # map_inside_hunk: the whole candidate range, not the shifted line nor the position inside the hunk
        self.assertEqual(mapped(d, "f", 3), [3, 5])
        # map_insertion_point: '-a,0' inserts after a; a itself does not move, a+1 does
        d = file_diff("f", old, old.replace("l4\n", "l4\nnew\n"))
        self.assertIn("@@ -4,0 +5 @@", d)
        self.assertEqual((mapped(d, "f", 4), mapped(d, "f", 5)), ([4, 4], [6, 6]))
        # map_deleted_line: a pure deletion maps to nothing, not to the line before the gap
        d = file_diff("f", old, old.replace("l6\n", ""))
        self.assertIn("@@ -6 +5,0 @@", d)
        self.assertEqual((mapped(d, "f", 6), mapped(d, "f", 7)), ([], [6, 6]))
        # map_after_pure_hunks: an insertion and a deletion before the line both count
        d = file_diff("f", old, old.replace("l2\n", "l2\nx\ny\n").replace("l5\n", ""))
        self.assertEqual(mapped(d, "f", 9), [10, 10])
        self.assertEqual(apply_block(G.parse(d)[0], old).split("\n")[9], "l9")

    def test_insertion_at_the_top(self):
        top = "diff --git a/t.js b/t.js\nindex 1..2 100644\n--- a/t.js\n+++ b/t.js\n@@ -0,0 +1,3 @@\n+a\n+b\n+c\n"
        self.assertEqual(mapped(top, "t.js", 1), [4, 4])

    def test_paths(self):
        diff = ("diff --git a/x.js b/y.js\nsimilarity index 90%\nrename from x.js\nrename to y.js\n"
                "index 1..2 100644\n--- a/x.js\n+++ b/y.js\n@@ -2 +2 @@\n-b\n+B\n"
                "diff --git a/gone.js b/gone.js\ndeleted file mode 100644\nindex 1..0\n--- a/gone.js\n"
                "+++ /dev/null\n@@ -1 +0,0 @@\n-x\n"
                "diff --git a/new.js b/new.js\nnew file mode 100644\nindex 0..1\n--- /dev/null\n"
                "+++ b/new.js\n@@ -0,0 +1 @@\n+x\n")
        self.assertEqual(mapped(diff, "x.js", 1), [1, 1])
        self.assertEqual(mapped(diff, "x.js", 2), [2, 2])
        self.assertEqual(mapped(diff, "gone.js", 1), [])
        binary_gone = "diff --git a/g.png b/g.png\ndeleted file mode 100644\nindex 1..0\nBinary files a/g.png and /dev/null differ\n"
        self.assertEqual(G.parse(binary_gone)[0]["hunks"], [])
        self.assertEqual(mapped(binary_gone, "g.png", 3), [])  # a deleted path has no line, hunks or not
        self.assertEqual(mapped(diff, "other.js", 7), [7, 7])
        for path, line in (("new.js", 1), ("x.js", 0), ("x.js", True)):
            with self.assertRaises(G.DiffError):
                mapped(diff, path, line)

    def test_copies_and_two_blocks_of_one_path(self):
        # a copy leaves its source as it is: the copy's hunks move lines of the new path only
        copy = ("diff --git a/x.js b/y.js\nsimilarity index 90%\ncopy from x.js\ncopy to y.js\nindex 1..2 100644\n"
                "--- a/x.js\n+++ b/y.js\n@@ -1,0 +2,2 @@\n+p\n+q\n")
        self.assertEqual(G.parse(copy)[0]["kind"], "copy")
        self.assertEqual(mapped(copy, "x.js", 5), [5, 5])
        # the parser takes two blocks of one path; which hunks move the line is then not known
        one = "diff --git a/z.js b/z.js\nindex 1..2 100644\n--- a/z.js\n+++ b/z.js\n@@ -1 +1 @@\n-a\n+b\n"
        self.assertEqual(len(G.parse(one + one)), 2)
        with self.assertRaises(G.DiffError):
            mapped(one + one, "z.js", 3)
        self.assertEqual(mapped(one + one, "w.js", 3), [3, 3])

    def test_hunk_starts_are_checked(self):
        for bad in (DIFF_U0.replace("@@ -6,0 +7,2 @@", "@@ -6,0 +500,2 @@"),
                    DIFF_U0.replace("@@ -12,2 +13,0 @@", "@@ -12,2 +14,0 @@"),
                    DIFF_U0.replace("@@ -3 +3 @@", "@@ -7 +7 @@")):  # out of order with '-6,0'
            with self.assertRaises(G.DiffError):
                G.parse(bad)

    def test_cli_map(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "c.patch")
            with open(p, "w") as fh:
                fh.write(DIFF_U2)
            self.assertEqual(run_cli("map", p, "m.js", "10"), (0, {"mapped": [12, 15]}))
            self.assertEqual(run_cli("map", p, "m.js", "16"), (0, {"mapped": [16, 16]}))
            with open(p, "w") as fh:
                fh.write(DIFF_U0)
            self.assertEqual(run_cli("map", p, "m.js", "12"), (0, {"mapped": []}))
            for line in ("0", "-1", "x", "01"):
                argv = ["map", p, "m.js", line]
                refusal.assert_refused(self, C, argv, *run_cli_err(*argv), cause=CAUSE)
            with open(p, "w") as fh:
                fh.write(DIFF_U2.replace("+12,4", "+13,4"))
            argv = ["map", p, "m.js", "16"]
            code, out, err = run_cli_err(*argv)
            refusal.assert_refused(self, C, argv, code, out, err, cause=CAUSE)
            self.assertIn("unusable", out["error"])
            argv = ["map", os.path.join(d, "none.patch"), "m.js", "1"]  # OSError is the module's refusal
            refusal.assert_refused(self, C, argv, *run_cli_err(*argv), cause=CAUSE)


# ---------------------------------------------------------------- the decision

SRC = "const x = 1;\nvar y = 2;\nlet z = 3;\nvar w = 4;\nconst v = 5;\n"
GOOD = SRC.replace("var y", "let y")
PATH = "src/a.js"


def v(line, rule="no-var", fix="same", path=PATH):
    return {"rule_id": rule, "path": path, "line": line, "fix": [line, line] if fix == "same" else fix}


def run(violations, tool="eslint"):
    return json.dumps({"tool": tool, "violations": violations}, separators=(",", ":")).encode()


def three(line):
    return line + b"\n" + line + b"\n" + line + b"\n"


class Case:
    """One decision input; ``write`` lays it out as the ``koş`` job and the candidate directory do."""

    def __init__(self):
        self.finding = {"rule_id": "no-var", "path": PATH, "line": 2, "fix_range": [2, 2],
                        "tool_output_sha256": "0" * 64}
        self.diff = file_diff(PATH, SRC, GOOD)
        self.files = {"base.jsonl": three(run([v(2), v(4)])), "cand.jsonl": three(run([v(4)])),
                      "checks.json": json.dumps({"tests": [{"id": "t1", "status": "pass"}],
                                                 "red_control": "fail"}).encode()}
        self.hashes = None  # None: the hashes of ``files``; a dict overrides
        self.missing = set()
        self.stdin = {"control": {"kill_switch": False, "merge_paused": False}, "unfinished_sentinels": []}

    def hash_doc(self):
        return self.hashes or {k: hashlib.sha256(b).hexdigest() for k, b in self.files.items()}

    def forge(self, name, raw):
        """Replace a file after its hash was taken, as a forger inside ``koş`` would."""
        self.hashes = self.hash_doc()
        self.files[name] = raw

    def decide(self):
        files = {k: (None if k in self.missing else b) for k, b in self.files.items()}
        return C.decide(C.finding(self.finding), self.diff, files, C.hashes_file(self.hash_doc()),
                        C.request(self.stdin))

    def write(self, d):
        cand, runs = os.path.join(d, "cand"), os.path.join(d, "koş")
        os.makedirs(cand)
        os.makedirs(runs)
        out = {"cand": cand, "runs": runs, "base": os.path.join(runs, "base.jsonl"),
               "hashes": os.path.join(d, "hashes.json")}
        with open(os.path.join(cand, "finding.json"), "w") as fh:
            fh.write(self.finding if isinstance(self.finding, str) else json.dumps(self.finding))
        with open(os.path.join(cand, "diff.patch"), "w", encoding="utf-8", errors="surrogateescape") as fh:
            fh.write(self.diff)
        for name, raw in self.files.items():
            if name not in self.missing:
                with open(os.path.join(runs, name), "wb") as fh:
                    fh.write(raw)
        with open(out["hashes"], "w") as fh:
            json.dump(self.hash_doc(), fh)
        return out


class Decision(unittest.TestCase):

    def assertReasons(self, case, reasons):
        result = case.decide()
        self.assertEqual(result, {"decision": "merge" if not reasons else "reject", "reasons": reasons})

    def test_good_candidate_merges(self):
        self.assertReasons(Case(), [])

    def test_merge_with_shifted_violation_and_changed_rule(self):
        # the fix splits line 2 in two: the old no-var at 4 now sits at 5, outside the mapped [2, 3];
        # a new violation of another rule replaces the fixed one, so the tool's total stays
        c = Case()
        c.diff = file_diff(PATH, SRC, SRC.replace("var y = 2;\n", "let y =\n  2;\n"))
        c.files["cand.jsonl"] = three(run([v(3, "indent", None), v(5)]))
        self.assertReasons(c, [])

    def test_target_not_found(self):
        c = Case()
        c.finding["line"] = 3
        c.files["cand.jsonl"] = three(run([v(3), v(4)]))  # would be not_distinguished with a target
        c.diff = file_diff(PATH, SRC, SRC.replace("const v", "let v"))  # would be scope_violation
        self.assertReasons(c, ["target_not_found"])
        for change in ({"rule_id": "no-console"}, {"path": "src/b.js"}):
            c = Case()
            c.finding.update(change)
            self.assertReasons(c, ["target_not_found"])

    def test_not_distinguished(self):
        c = Case()
        c.diff = file_diff(PATH, SRC, SRC.replace("var y = 2;", "var y = 20;"))
        c.files["cand.jsonl"] = three(run([v(2), v(4)]))
        self.assertReasons(c, ["not_distinguished"])
        c.files["cand.jsonl"] = three(run([v(2, "other"), v(4)]))  # another rule there does not count
        self.assertReasons(c, [])

    def test_not_distinguished_needs_rule_path_and_range(self):
        # a violation of the target's rule on another path, or before the mapped range, does not count
        for other in (v(2, path="src/b.js"), v(1)):
            c = Case()
            c.files["cand.jsonl"] = three(run([other, v(4)]))
            self.assertReasons(c, [])

    def test_deleting_the_target_line_distinguishes_it(self):
        # the target line is deleted: it maps to nothing, so no candidate violation is on it
        c = Case()
        c.diff = file_diff(PATH, SRC, SRC.replace("var y = 2;\n", ""))
        self.assertIn("@@ -2 +1,0 @@", c.diff)
        c.files["cand.jsonl"] = three(run([v(3)]))
        self.assertReasons(c, [])

    def test_not_distinguished_inside_the_hunk(self):
        # the violation left on the second line of the split: the target line (2) and the shifted line
        # miss it, the mapped range [2, 3] does not
        c = Case()
        c.diff = file_diff(PATH, SRC, SRC.replace("var y = 2;\n", "let y = 2;\nvar q = 2;\n"))
        c.files["cand.jsonl"] = three(run([v(3), v(5)]))
        self.assertReasons(c, ["not_distinguished"])

    def test_insertion_not_distinguished(self):
        # nothing fixed, a comment added after the target line: the '-2,0' hunk does not end before line 2
        c = Case()
        c.diff = file_diff(PATH, SRC, SRC.replace("var y = 2;\n", "var y = 2;\n// fixed\n"))
        self.assertIn("@@ -2,0 +3 @@", c.diff)
        c.files["cand.jsonl"] = three(run([v(2), v(5)]))
        self.assertReasons(c, ["not_distinguished"])

    def test_tool_nondeterministic(self):
        line = run([v(4)])
        spaced = line.replace(b'"tool":', b'"tool": ')
        self.assertEqual(json.loads(spaced), json.loads(line))
        for name, base_or_cand in (("cand.jsonl", line), ("base.jsonl", run([v(2), v(4)]))):
            for pos in range(3):
                c = Case()
                rows = [base_or_cand] * 3
                rows[pos] = base_or_cand.replace(b'"tool":', b'"tool": ')
                c.files[name] = b"\n".join(rows) + b"\n"
                self.assertReasons(c, ["tool_nondeterministic"])
                rows[pos] = base_or_cand + b" "  # a trailing byte is a byte too
                c.files[name] = b"\n".join(rows) + b"\n"
                self.assertReasons(c, ["tool_nondeterministic"])
        c = Case()
        c.files["cand.jsonl"] = three(line).rstrip(b"\n")  # no final newline: still three equal lines
        self.assertReasons(c, [])

    def test_scope_removed_line(self):
        c = Case()
        c.diff = file_diff(PATH, SRC, SRC.replace("let z = 3;\n", ""))  # line e+1 removed, nothing added after
        self.assertIn("@@ -3 +2,0 @@", c.diff)
        c.files["cand.jsonl"] = three(run([v(2), v(3)]))
        self.assertReasons(c, ["not_distinguished", "scope_violation"])
        c = Case()
        c.diff = file_diff(PATH, SRC, GOOD.replace("let z = 3;\n", ""))
        self.assertReasons(c, ["scope_violation"])
        c.files["base.jsonl"] = three(run([v(2, fix=[2, 3]), v(4)]))
        self.assertReasons(c, [])
        c = Case()
        c.diff = file_diff(PATH, SRC, GOOD.replace("const x = 1;\n", ""))  # line s-1 removed
        self.assertIn("@@ -1,2 +1 @@", c.diff)
        self.assertReasons(c, ["scope_violation"])

    def test_scope_inserted_line(self):
        # p is the base line that comes next: after the fix's last line (e+1) is inside, past it is not
        c = Case()
        c.diff = file_diff(PATH, SRC, GOOD.replace("let y = 2;\n", "let y = 2;\nlet y2 = 2;\n"))
        self.assertReasons(c, [])
        c.diff = file_diff(PATH, SRC, GOOD.replace("let z = 3;\n", "let z = 3;\n// past\n"))
        self.assertReasons(c, ["scope_violation"])  # insertion_past_fix: '-3,0' puts p at 4 = e+2
        c.diff = file_diff(PATH, SRC, SRC.replace("const x = 1;\n", "const x = 1;\n// a\n"))
        self.assertIn("@@ -1,0 +2 @@", c.diff)
        c.files["cand.jsonl"] = three(run([v(3), v(5)]))
        self.assertReasons(c, ["not_distinguished"])  # '-1,0' puts p at 2 = s: in scope, but nothing fixed
        c.diff = file_diff(PATH, SRC, "// top\n" + GOOD)
        c.files["cand.jsonl"] = three(run([v(5)]))
        self.assertReasons(c, ["scope_violation"])  # '-0,0' puts p at 1 < s

    def test_scope_ignores_context(self):
        c = Case()
        c.diff = file_diff(PATH, SRC, GOOD, n=3)
        self.assertIn(" const v = 5;", c.diff)
        c.files["base.jsonl"], c.files["cand.jsonl"] = three(run([v(2)])), three(run([]))
        self.assertReasons(c, [])
        # the mapped range follows the diff as written: with context, the untouched no-var at 4 is inside it
        c = Case()
        c.diff = file_diff(PATH, SRC, GOOD, n=3)
        self.assertReasons(c, ["not_distinguished"])

    def test_scope_other_path_rename_mode_and_null_fix(self):
        other = file_diff("src/b.js", "a\n", "b\n")
        renamed = file_diff(PATH, SRC, GOOD, a=PATH, b="src/c.js").replace(
            "index 1111111..2222222 100644\n", "similarity index 90%\nrename from src/a.js\nrename to src/c.js\n"
            "index 1111111..2222222 100644\n", 1)
        mode = file_diff(PATH, SRC, GOOD).replace("index 1111111..2222222 100644\n",
                                                  "old mode 100644\nnew mode 100755\nindex 1111111..2222222\n", 1)
        for diff in (file_diff(PATH, SRC, GOOD) + other, mode):
            c = Case()
            c.diff = diff
            self.assertReasons(c, ["scope_violation"])
        c = Case()
        c.diff = renamed
        self.assertEqual(G.parse(renamed)[0]["kind"], "rename")
        self.assertIn("scope_violation", c.decide()["reasons"])
        c = Case()
        c.files["base.jsonl"] = three(run([v(2, fix=None), v(4)]))
        self.assertReasons(c, ["scope_violation"])
        c = Case()
        c.diff = "diff --git a/%s b/%s\nindex 1111111..2222222 100644\nBinary files a/%s and b/%s differ\n" % ((PATH,) * 4)
        self.assertEqual(G.parse(c.diff)[0]["kind"], "modify")
        self.assertReasons(c, ["scope_violation"])

    def test_first_target_in_the_file(self):
        c = Case()
        c.files["base.jsonl"] = three(run([v(2), v(2, fix=None), v(4)]))
        c.files["cand.jsonl"] = three(run([v(4), v(1, "x")]))
        self.assertReasons(c, [])
        c.files["base.jsonl"] = three(run([v(2, fix=None), v(2), v(4)]))
        self.assertReasons(c, ["scope_violation"])

    def test_ratchet_per_tool(self):
        c = Case()
        c.files["cand.jsonl"] = three(run([v(4), v(5, "eqeqeq"), v(1, "eqeqeq")]))
        self.assertReasons(c, ["ratchet_increase"])
        c.files["cand.jsonl"] = three(run([v(5, "eqeqeq")], tool="tsc"))  # a tool absent from base counts 0
        self.assertReasons(c, ["ratchet_increase"])
        c.files["cand.jsonl"] = three(run([v(4), v(1, "eqeqeq")]))  # equal to base's two: no increase
        c.files["base.jsonl"] = three(run([v(2), v(4), v(5, "eqeqeq")]))
        self.assertReasons(c, [])

    def test_tests_and_red_control(self):
        for checks, reasons in (({"tests": [], "red_control": "fail"}, ["zero_tests"]),
                                ({"tests": [{"id": "a", "status": "pass"}, {"id": "b", "status": "fail"}],
                                  "red_control": "fail"}, ["tests_red"]),
                                ({"tests": [{"id": "a", "status": "pass"}], "red_control": "pass"},
                                 ["red_control_green"])):
            c = Case()
            c.files["checks.json"] = json.dumps(checks).encode()
            self.assertReasons(c, reasons)

    def test_ratchet_and_broken_test(self):
        c = Case()
        c.files["cand.jsonl"] = three(run([v(4), v(5, "eqeqeq"), v(1, "eqeqeq")]))
        c.files["checks.json"] = json.dumps({"tests": [{"id": "a", "status": "fail"}], "red_control": "fail"}).encode()
        self.assertReasons(c, ["ratchet_increase", "tests_red"])

    def test_merge_paused_unless_false(self):
        for control in ({"merge_paused": True}, {}, {"merge_paused": "false"}, {"merge_paused": 0},
                        {"merge_paused": None}):
            c = Case()
            c.stdin["control"] = control
            self.assertReasons(c, ["merge_paused"])

    def test_sentinel_pending(self):
        c = Case()
        c.stdin["unfinished_sentinels"] = ["c" * 40]
        self.assertReasons(c, ["sentinel_pending"])

    def test_fail_closed_controls(self):
        c = Case()
        c.stdin = {"control": {"kill_switch": False}, "unfinished_sentinels": ["c" * 40]}
        c.files["checks.json"] = json.dumps({"tests": [], "red_control": "fail"}).encode()
        self.assertReasons(c, ["merge_paused", "sentinel_pending", "zero_tests"])

    def test_secret_in_diff(self):
        token = "".join(["gh", "p_"]) + "".join(chr(65 + (i * 7) % 26) for i in range(36))
        c = Case()
        c.diff = file_diff(PATH, SRC, SRC.replace("var y = 2;", "let y = '%s';" % token))
        self.assertReasons(c, ["secret_in_diff"])

    def test_every_hash_is_checked(self):
        for name in C.RUN_FILES:
            c = Case()
            c.files[name] += b" "
            c.hashes = {k: hashlib.sha256(b).hexdigest() for k, b in Case().files.items()}
            self.assertReasons(c, ["artefact_hash_mismatch"])
            c = Case()
            c.missing.add(name)
            self.assertReasons(c, ["artefact_hash_mismatch"])
            c.hashes = dict(c.hash_doc(), **{name: hashlib.sha256(b"").hexdigest()})
            self.assertReasons(c, ["artefact_hash_mismatch"])  # missing is not empty
        c = Case()
        c.missing.update(C.RUN_FILES)
        self.assertReasons(c, ["artefact_hash_mismatch"])  # each reason once, however many files fail

    def test_a_file_failing_its_hash_is_not_read(self):
        # forged_candidate_run: the half fix's real run is hashed, a clean run is put in its place
        c = Case()
        c.files["cand.jsonl"] = three(run([v(2), v(4)]))
        c.forge("cand.jsonl", three(run([v(4)])))
        self.assertReasons(c, ["artefact_hash_mismatch"])
        # forged_checks: a red run rewritten as all passing
        c = Case()
        c.files["checks.json"] = json.dumps({"tests": [{"id": "a", "status": "fail"}], "red_control": "fail"}).encode()
        c.forge("checks.json", json.dumps({"tests": [{"id": "a", "status": "pass"}], "red_control": "fail"}).encode())
        self.assertReasons(c, ["artefact_hash_mismatch"])
        # bytes that are not even a run file are not parsed when their hash fails
        c = Case()
        c.forge("base.jsonl", b"garbage")
        self.assertReasons(c, ["artefact_hash_mismatch"])
        # the rules over the verified files are still judged
        c = Case()
        c.forge("cand.jsonl", b"x")
        c.stdin["control"] = {}
        c.diff = file_diff(PATH, SRC, GOOD.replace("const v", "let v"))
        self.assertReasons(c, ["artefact_hash_mismatch", "merge_paused", "scope_violation"])

    def test_unusable_inputs(self):
        good = run([v(2), v(4)])
        breaks = [
            ("base.jsonl", good + b"\n" + good + b"\n"),
            ("base.jsonl", three(good) + good + b"\n"),
            ("base.jsonl", three(b"{")),
            ("base.jsonl", three(b"[]")),
            ("base.jsonl", three(run([dict(v(2), line=0)]))),
            ("base.jsonl", three(run([dict(v(2), line=True)]))),
            ("base.jsonl", three(run([v(2, fix=[3, 2])]))),
            ("base.jsonl", three(run([v(2, fix=[0, 2])]))),
            ("base.jsonl", three(run([v(2, fix=[2])]))),
            ("base.jsonl", three(run([v(2, fix=[2, 2, 3])]))),
            ("base.jsonl", three(run([v(2, fix=[True, 2])]))),
            ("base.jsonl", three(run(["src/a.js:2"]))),
            ("base.jsonl", three(run([dict(v(2), rule_id=5)]))),
            ("base.jsonl", three(run([dict(v(2), rule_id="")]))),
            ("base.jsonl", three(run([dict(v(2), path="../a.js")]))),
            ("base.jsonl", three(run([dict(v(2), path="src\\a.js")]))),
            ("base.jsonl", three(run([dict(v(2), path="src/./a.js")]))),
            ("base.jsonl", three(run([dict(v(2), path="src//a.js")]))),
            ("base.jsonl", three(run([dict(v(2), path="src/")]))),
            ("base.jsonl", three(run([dict(v(2), path="")]))),
            ("base.jsonl", three(run([dict(v(2), path=7)]))),
            ("base.jsonl", three(json.dumps({"violations": []}).encode())),
            ("cand.jsonl", three(b'{"tool": "eslint"}')),
            ("checks.json", b'{"tests": []}'),
            ("checks.json", b'{"tests": [{"id": "a", "status": "ok"}], "red_control": "fail"}'),
            ("checks.json", b"[1, 2]"),
            ("checks.json", b'{"tests": {}, "red_control": "fail"}'),
            ("checks.json", b'{"tests": ["a"], "red_control": "fail"}'),
            ("checks.json", b'{"tests": [{"id": 1, "status": "pass"}], "red_control": "fail"}'),
            ("checks.json", b'{"tests": [{"status": "pass"}], "red_control": "fail"}'),
        ]
        for i, (name, raw) in enumerate(breaks):
            c = Case()
            c.files[name] = raw
            with self.assertRaises(C.Unusable, msg=str(i)):
                c.decide()
        for i, change in enumerate((lambda c: c.finding.update(path="/etc/x"), lambda c: c.finding.update(line="2"),
                                    lambda c: c.finding.pop("rule_id"),
                                    lambda c: setattr(c, "finding", [c.finding]),
                                    lambda c: c.finding.update(rule_id=["no-var"]),
                                    lambda c: setattr(c, "stdin", [c.stdin]),
                                    lambda c: setattr(c, "hashes", [c.hash_doc()]),
                                    lambda c: setattr(c, "hashes", dict(c.hash_doc(), **{"checks.json": c.hash_doc()["checks.json"] + "\n"})),
                                    lambda c: setattr(c, "hashes", dict(c.hash_doc(), **{"checks.json": c.hash_doc()["checks.json"] + "0"})),
                                    lambda c: setattr(c, "stdin", {"control": {"merge_paused": False}}),
                                    lambda c: setattr(c, "stdin", {"control": False, "unfinished_sentinels": []}),
                                    lambda c: c.stdin.update(unfinished_sentinels=[1]),
                                    lambda c: setattr(c, "hashes", {"base.jsonl": "A" * 64}),
                                    lambda c: setattr(c, "hashes", dict(c.hash_doc(), **{"cand.jsonl": c.hash_doc()["cand.jsonl"].upper()})),
                                    lambda c: setattr(c, "diff", "not a diff\n"))):
            c = Case()
            change(c)
            with self.assertRaises((C.Unusable, G.DiffError), msg=str(i)):
                c.decide()


class CommandLine(unittest.TestCase):

    def cli(self, case, stdin=None):
        with tempfile.TemporaryDirectory() as d:
            p = case.write(d)
            return run_cli("decide", p["cand"], p["base"], p["runs"], p["hashes"],
                           stdin=json.dumps(case.stdin) if stdin is None else stdin)

    def test_merge_reject_unusable(self):
        self.assertEqual(self.cli(Case()), (0, {"decision": "merge", "reasons": []}))
        c = Case()
        c.stdin["control"]["merge_paused"] = True
        self.assertEqual(self.cli(c), (1, {"decision": "reject", "reasons": ["merge_paused"]}))
        c = Case()
        c.missing.add("cand.jsonl")
        self.assertEqual(self.cli(c), (1, {"decision": "reject", "reasons": ["artefact_hash_mismatch"]}))
        c.hashes = dict(c.hash_doc(), **{"cand.jsonl": hashlib.sha256(b"").hexdigest()})
        self.assertEqual(self.cli(c), (1, {"decision": "reject", "reasons": ["artefact_hash_mismatch"]}))
        self.assertRefused(Case(), stdin="{")
        c = Case()
        c.files["checks.json"] = b"{}"
        self.assertRefused(c)
        c = Case()
        c.diff = "not a diff\n"
        self.assertRefused(c)
        c = Case()
        c.finding = "{"  # finding.json is not JSON: cli.load's ValueError
        self.assertRefused(c)
        for argv in (["decide", "/nonexistent", "x", "y", "z"], ["decide", "x"], ["push"]):
            code, out, err = run_cli_err(*argv, stdin="{}")
            refusal.assert_refused(self, C, argv, code, out, err, cause=CAUSE)
            self.assertEqual(out, {"decision": "reject"} if argv[0] == "decide" else out)

    def test_diff_bytes_that_are_not_utf8(self):
        # a base file in Latin-1: the diff carries its bytes as they are, and the gate still decides
        src = SRC.replace("const x = 1;", "const x = 1; // caf\udce9")
        c = Case()
        c.diff = file_diff(PATH, src, src.replace("var y", "let y"), n=1)
        self.assertIn("caf\udce9", c.diff)
        self.assertEqual(self.cli(c), (0, {"decision": "merge", "reasons": []}))

    def test_a_crash_in_decide_still_rejects(self):
        # an exception the module did not expect reaches cli.run, whose line for decide is a reject
        for argv, line in ((["decide", "a", "b", "c", "d"], {"decision": "reject"}), (["map"], cli.GENERIC_LINE)):
            out, err = StringIO(), StringIO()
            with redirect_stdout(out), redirect_stderr(err):
                code = cli.run(lambda _argv: 1 // 0, argv, C.FAULT_LINE)
            self.assertEqual((code, json.loads(out.getvalue())), (2, line))
            with self.assertRaises(AssertionError):  # and the refusal check tells it from a refusal
                refusal.assert_refused(self, C, argv, code, json.loads(out.getvalue()), err.getvalue(), cause=CAUSE)

    def assertRefused(self, case, stdin=None):
        with tempfile.TemporaryDirectory() as d:
            p = case.write(d)
            argv = ["decide", p["cand"], p["base"], p["runs"], p["hashes"]]
            code, out, err = run_cli_err(*argv, stdin=json.dumps(case.stdin) if stdin is None else stdin)
        refusal.assert_refused(self, C, argv, code, out, err, cause=CAUSE)
        self.assertEqual(out, {"decision": "reject"})


if __name__ == "__main__":
    unittest.main()
