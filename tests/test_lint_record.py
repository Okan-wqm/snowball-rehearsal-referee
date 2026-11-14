"""``runner.lint_record`` (called by MF6, run by test 48's command): ESLint's JSON output as ``gate.check``'s run
record.

The fixture ``fixtures/eslint_edge/`` is real output: ESLint 10.13.0 (``--format json``, node 22.23.4) run on
``tree/`` with ``tree/eslint.config.js``, and on two candidate trees (``tree/`` without ``fatal.js``, with
``multi.js`` replaced by ``cand_fix.multi.js`` or ``cand_sup.multi.js``); only the absolute root of each
``filePath`` was rewritten to ``/work``. ``cand_*.patch`` are ``git diff`` of those two changes.

- the record on the edge files (CRLF, lone CR, U+2028, BOM, astral characters, a file without a final newline,
  multi-line fixes, a suggestion that is no fix, a suppressed violation, an unused directive), exact;
- an independent oracle: each fix applied to the text, the changed base lines found with difflib, inside
  ``[first, last]``; and the gate's own scope rule on the real candidate diff;
- end to end through ``gate.check.decide``: the real fix merges; the real suppression comment is
  ``not_distinguished`` because a suppressed violation is counted;
- every refusal on its own input, all reasons together; the run file ``gate.check`` reads; the command line.
"""

from __future__ import annotations

import difflib
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import unittest.mock

REFEREE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REFEREE)

from gate import check, diffguard  # noqa: E402
from runner import lint_record as L  # noqa: E402

FIX = os.path.join(REFEREE, "tests", "fixtures", "eslint_edge")
TREE = os.path.join(FIX, "tree")


def read(name: str) -> str:
    with open(os.path.join(FIX, name), encoding="utf-8", newline="") as fh:
        return fh.read()


def load(name: str) -> list:
    return json.loads(read(name))


def out(doc) -> bytes:
    return json.dumps(doc).encode("utf-8")


def base_output() -> list:
    return [r for r in load("eslint.json") if not r["filePath"].endswith("/fatal.js")]


def cand_tree(base: str, variant: str) -> str:
    """The tree ESLint read for ``<variant>.json``: ``tree/`` without ``fatal.js``, ``multi.js`` replaced."""
    tree = os.path.join(base, variant)
    shutil.copytree(TREE, tree)
    os.remove(os.path.join(tree, "fatal.js"))
    shutil.copyfile(os.path.join(FIX, variant + ".multi.js"), os.path.join(tree, "multi.js"))
    return tree


EXPECTED = [
    ("astral.js", "no-var", 1, [1, 1]),
    ("astral.js", "dot-notation", 1, [1, 1]),
    ("bom.js", "no-var", 1, [1, 1]),
    ("crlf.js", "no-var", 1, [1, 1]),
    ("crlf.js", "no-var", 2, [2, 2]),
    ("lonecr.js", "no-var", 1, [1, 1]),      # ESLint: line 2 (a lone CR is its line break); git: line 1
    ("ls.js", "no-var", 2, [2, 2]),          # ESLint: line 3 (U+2028 in a string); git: line 2
    ("multi.js", "prefer-template", 2, [2, 4]),
    ("multi.js", "no-useless-return", 9, [7, 10]),
    ("noeol.js", "no-var", 1, [1, 1]),
    ("suppressed.js", L.NO_RULE, 3, [3, 3]),  # unused disable directive: no ruleId
    ("suppressed.js", "no-var", 2, [2, 2]),   # suppressed, still counted
    ("unused.js", "no-unused-vars", 1, None),  # a suggestion is not a fix
]


class Record(unittest.TestCase):
    def test_edge_files_exact(self):
        rec = L.record(out(base_output()), TREE)
        self.assertEqual(rec["tool"], "eslint")
        got = [(v["path"], v["rule_id"], v["line"], v["fix"]) for v in rec["violations"]]
        self.assertEqual(got, EXPECTED)
        self.assertEqual(sorted(rec), ["tool", "violations"])
        self.assertTrue(all(sorted(v) == ["fix", "line", "path", "rule_id"] for v in rec["violations"]))

    def test_eslint_lines_are_converted_not_copied(self):
        lines = {r["filePath"].rsplit("/", 1)[1]: [m["line"] for m in r["messages"]] for r in base_output()}
        self.assertEqual(lines["lonecr.js"], [2])
        self.assertEqual(lines["ls.js"], [3])

    def test_fix_ranges_hold_every_changed_line(self):
        """Oracle independent of ``_Text.fix``: apply the fix to the text, diff the git lines, compare."""
        base = tempfile.mkdtemp(prefix="t-lint-")
        self.addCleanup(shutil.rmtree, base, ignore_errors=True)
        runs = [(base_output(), TREE)] + [(load(v + ".json"), cand_tree(base, v)) for v in ("cand_fix", "cand_sup")]
        checked = 0
        for results, tree in runs:
            for result in results:
                rel = result["filePath"][len("/work/"):]
                for m in result["messages"] + result["suppressedMessages"]:
                    if not m.get("fix"):
                        continue
                    with open(os.path.join(tree, rel), encoding="utf-8", newline="") as fh:
                        text = fh.read()
                    first, last = L._Text(text).fix(m["fix"])
                    changed = self._changed(text, m["fix"])
                    self.assertTrue(changed, (rel, m))
                    for kind, line in changed:
                        self.assertTrue(first <= line <= last + (kind == "insert"), (rel, m["ruleId"], changed))
                    checked += 1
        self.assertEqual(checked, 35)  # 12 fixes in the base run, 11 and 12 in the candidate runs

    @staticmethod
    def _changed(text: str, fix: dict) -> list:
        """Base lines a fix changes: ``("base", n)`` for a removed or replaced line, ``("insert", n)`` for an
        insertion before base line n. Offsets are UTF-16 units of the text without its BOM, as ESLint's."""
        body = text[1:] if text.startswith("\ufeff") else text
        u16 = body.encode("utf-16-le")
        s, e = fix["range"]
        new = (u16[:2 * s] + fix["text"].encode("utf-16-le") + u16[2 * e:]).decode("utf-16-le")
        old_lines, new_lines = body.split("\n"), new.split("\n")
        found = []
        for tag, i1, i2, _, _ in difflib.SequenceMatcher(None, old_lines, new_lines, autojunk=False).get_opcodes():
            if tag in ("replace", "delete"):
                found += [("base", n + 1) for n in range(i1, i2)]
            elif tag == "insert":
                found.append(("insert", i1 + 1))
        return found

    def test_join_rule_when_the_range_ends_on_a_newline(self):
        text = "a\nb\nc\n"
        cases = [((0, 2), "x", [1, 2]), ((0, 2), "x\n", [1, 1]), ((4, 6), "", [3, 3]), ((2, 2), "y\n", [2, 2]),
                 ((1, 1), "z", [1, 1]), ((0, 6), "", [1, 3])]
        for rng, new, want in cases:
            fix = {"range": list(rng), "text": new}
            self.assertEqual(L._Text(text).fix(fix), want, (rng, new))
            for kind, line in self._changed(text, fix):
                self.assertTrue(want[0] <= line <= want[1] + (kind == "insert"), (rng, new, line))

    def test_offsets_exclude_the_byte_order_mark(self):
        """ESLint's ranges skip a leading BOM (bom.js: ``var`` at range 0); a range starting on line 2 stays there."""
        text = "\ufeffa\nb\n"
        self.assertEqual(L._Text(text).fix({"range": [2, 4], "text": ""}), [2, 2])
        self.assertEqual(L._Text(text).offset(2, 1), 2)
        self.assertEqual(L._Text(text).git_line(2), 2)

    def test_scope_rule_of_the_gate_on_the_real_candidate_diffs(self):
        rec = L.record(out(base_output()), TREE)
        target = next(v for v in rec["violations"] if v["rule_id"] == "prefer-template")
        for name in ("cand_fix.patch", "cand_sup.patch"):
            blocks = diffguard.parse(read(name))
            self.assertFalse(check.scope_violation(blocks, "multi.js", target["fix"]), name)
        # the range is not wider than needed: the real fix touches its last line
        blocks = diffguard.parse(read("cand_fix.patch"))
        self.assertTrue(check.scope_violation(blocks, "multi.js", [target["fix"][0], target["fix"][1] - 1]))

    def test_fatal_refuses_the_whole_run(self):
        with self.assertRaises(L.RecordError) as ctx:
            L.record(out(load("eslint.json")), TREE)
        self.assertEqual(ctx.exception.reasons, ["fatal:fatal.js"])


class Decide(unittest.TestCase):
    """The record is what the gate decides on: real fix merges, real suppression does not."""

    def setUp(self):
        self.base = tempfile.mkdtemp(prefix="t-lint-")
        self.addCleanup(shutil.rmtree, self.base, ignore_errors=True)

    def decide(self, variant: str) -> dict:
        base_rec = L.record(out(base_output()), TREE)
        cand_rec = L.record(out(load(variant + ".json")), cand_tree(self.base, variant))
        files = {"base.jsonl": L.run_file([base_rec] * 3), "cand.jsonl": L.run_file([cand_rec] * 3),
                 "checks.json": json.dumps({"tests": [{"id": "t", "status": "pass"}], "red_control": "fail"}).encode()}
        hashes = {k: hashlib.sha256(v).hexdigest() for k, v in files.items()}
        target = next(v for v in base_rec["violations"] if v["rule_id"] == "prefer-template")
        found = check.finding({"rule_id": target["rule_id"], "path": target["path"], "line": target["line"]})
        diff = read(variant + ".patch")
        return check.decide(found, diff, files, check.hashes_file(hashes),
                            check.request({"control": {"merge_paused": False}, "unfinished_sentinels": []}))

    def test_real_fix_merges(self):
        self.assertEqual(self.decide("cand_fix"), {"decision": "merge", "reasons": []})

    def test_real_suppression_is_not_distinguished(self):
        self.assertEqual(self.decide("cand_sup"), {"decision": "reject", "reasons": ["not_distinguished"]})

    def test_without_counting_suppressed_the_suppression_would_merge(self):
        """The mutant the rule exists for: dropping ``suppressedMessages`` makes the bad candidate merge."""
        real = L._results
        with unittest.mock.patch.object(L, "_results", lambda o: [dict(r, suppressedMessages=[]) for r in real(o)]):
            self.assertEqual(self.decide("cand_sup"), {"decision": "merge", "reasons": []})

    def test_run_file_is_what_the_gate_reads(self):
        rec = L.record(out(base_output()), TREE)
        raw = L.run_file([rec] * 3)
        self.assertEqual(check.run_file(raw, "base.jsonl"), (rec, True))
        self.assertEqual(raw.count(b"\n"), 3)
        self.assertEqual(raw.split(b"\n")[0], json.dumps(rec, sort_keys=True, separators=(",", ":")).encode())


class Refusals(unittest.TestCase):
    def setUp(self):
        self.tree = tempfile.mkdtemp(prefix="t-lint-")
        self.addCleanup(shutil.rmtree, self.tree, ignore_errors=True)
        self.write("a.js", "var a = 1;\nmodule.exports = a;\n")

    def write(self, rel: str, text, mode="w"):
        path = os.path.join(self.tree, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, mode, **({} if "b" in mode else {"encoding": "utf-8", "newline": ""})) as fh:
            fh.write(text)

    @staticmethod
    def msg(**over) -> dict:
        m = {"ruleId": "no-var", "severity": 1, "line": 1, "column": 1, "fix": {"range": [0, 10], "text": "let a = 1;"}}
        m.update(over)
        return {k: v for k, v in m.items() if v is not ...}

    @staticmethod
    def result(path="/work/a.js", messages=None, suppressed=(), **over) -> dict:
        r = {"filePath": path, "messages": [Refusals.msg()] if messages is None else messages,
             "suppressedMessages": list(suppressed)}
        r.update(over)
        return r

    def reasons(self, doc) -> list:
        with self.assertRaises(L.RecordError) as ctx:
            L.record(doc if isinstance(doc, bytes) else out(doc), self.tree)
        return ctx.exception.reasons

    def test_valid_minimal(self):
        self.assertEqual(L.record(out([self.result()]), self.tree)["violations"],
                         [{"rule_id": "no-var", "path": "a.js", "line": 1, "fix": [1, 1]}])
        self.assertEqual(L.record(b"[]", self.tree), {"tool": "eslint", "violations": []})

    def test_not_eslint_json(self):
        r = self.result()
        no_supp = {k: v for k, v in r.items() if k != "suppressedMessages"}
        for bad in (b"", b"a.js:1:1 no-var", b"\xff[]", b"{}", b"[1]", out([no_supp]), out([dict(r, filePath=3)]),
                    out([dict(r, messages={})]), out([dict(r, messages=[1])]), out([dict(r, source=1)]),
                    b"[" * 100000):
            self.assertEqual(self.reasons(bad), ["not_eslint_json"], bad[:40])

    def test_path_outside_root(self):
        for p in ("/elsewhere/a.js", "/workx/a.js", "/work/../a.js", "/work/./a.js", "/work//a.js", "/work/",
                  "a.js", "/work/b\\a.js"):
            self.assertEqual(self.reasons([self.result(path=p)]), ["path_outside_root:" + p], p)

    def test_only_files_with_messages_are_read(self):
        self.assertEqual(L.record(out([self.result(path="/work/missing.js", messages=[])]), self.tree)["violations"],
                         [])

    def test_file_unreadable_missing_symlink_directory(self):
        self.assertEqual(self.reasons([self.result(path="/work/missing.js")]), ["file_unreadable:missing.js"])
        os.symlink("a.js", os.path.join(self.tree, "link.js"))
        self.assertEqual(self.reasons([self.result(path="/work/link.js")]), ["file_unreadable:link.js"])
        os.symlink(".", os.path.join(self.tree, "d"))
        self.assertEqual(self.reasons([self.result(path="/work/d/a.js")]), ["file_unreadable:d/a.js"])
        os.mkdir(os.path.join(self.tree, "dir.js"))
        self.assertEqual(self.reasons([self.result(path="/work/dir.js")]), ["file_unreadable:dir.js"])

    def test_source_not_utf8_and_mismatch(self):
        self.write("b.js", b"var a = 1;\xff\n", "wb")
        self.assertEqual(self.reasons([self.result(path="/work/b.js")]), ["source_not_utf8:b.js"])
        text = "var a = 1;\nmodule.exports = a;\n"
        self.assertEqual(L.record(out([self.result(source=text)]), self.tree)["violations"][0]["line"], 1)
        self.assertEqual(self.reasons([self.result(source=text + " ")]), ["source_mismatch:a.js"])

    def test_suppressed_fatal_also_refuses(self):
        self.assertEqual(self.reasons([self.result(messages=[], suppressed=[self.msg(ruleId=None, fatal=True)])]),
                         ["fatal:a.js"])
        self.assertEqual(L.record(out([self.result(messages=[self.msg(fatal=False)])]), self.tree)["violations"][0]
                         ["rule_id"], "no-var")

    def test_message_unusable(self):
        n = len("var a = 1;\nmodule.exports = a;\n")
        bad = [dict(ruleId=""), dict(ruleId=3), dict(severity=0), dict(severity="2"), dict(severity=...),
               dict(line=0), dict(line=4), dict(line=True), dict(line=...), dict(column=0), dict(column=...),
               dict(line=3, column=2), dict(column=1.0),
               dict(fix={"range": [3, 2], "text": ""}), dict(fix={"range": [0, n + 1], "text": ""}),
               dict(fix={"range": [-1, 0], "text": ""}), dict(fix={"range": [0], "text": ""}),
               dict(fix={"range": [0, 1]}), dict(fix={"range": [0, True], "text": ""}), dict(fix=[0, 1])]
        for over in bad:
            self.assertEqual(self.reasons([self.result(messages=[self.msg(**over)])]), ["message_unusable:a.js"], over)
        ok = [dict(line=3, column=1), dict(fix=None), dict(fix=...), dict(ruleId=None),
              dict(fix={"range": [n, n], "text": "x"})]
        for over in ok:
            L.record(out([self.result(messages=[self.msg(**over)])]), self.tree)

    def test_every_reason_together_sorted(self):
        self.write("b.js", b"\xfe", "wb")
        doc = [self.result(path="/x/a.js"), self.result(path="/work/nope.js"), self.result(path="/work/b.js"),
               self.result(messages=[self.msg(line=99)])]
        self.assertEqual(self.reasons(doc), ["file_unreadable:nope.js", "message_unusable:a.js",
                                             "path_outside_root:/x/a.js", "source_not_utf8:b.js"])


class CommandLine(unittest.TestCase):
    def run_cli(self, args, stdin: bytes):
        return subprocess.run([sys.executable, "-m", "runner.lint_record"] + args, cwd=REFEREE, input=stdin,
                              capture_output=True, timeout=60)

    def test_exit_codes(self):
        ok = self.run_cli([TREE], out(base_output()))
        self.assertEqual(ok.returncode, 0, ok.stderr)
        doc = json.loads(ok.stdout)
        self.assertEqual((doc["ok"], doc["reasons"]), (True, []))
        self.assertEqual(len(doc["record"]["violations"]), len(EXPECTED))
        bad = self.run_cli([TREE], out(load("eslint.json")))
        self.assertEqual((bad.returncode, json.loads(bad.stdout)),
                         (1, {"ok": False, "reasons": ["fatal:fatal.js"], "record": None}))
        moved = [dict(r, filePath=r["filePath"].replace("/work", "/src", 1)) for r in base_output()]
        self.assertEqual(self.run_cli([TREE, "/src"], out(moved)).returncode, 0)
        for args in ([], [os.path.join(TREE, "nope")], [TREE, "/work", "x"]):
            res = self.run_cli(args, b"[]")
            self.assertEqual((res.returncode, res.stdout), (2, b""), args)


if __name__ == "__main__":
    unittest.main()
