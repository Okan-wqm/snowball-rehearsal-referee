"""The Founder's read-only ledger index (`seed/founder/ledger_index.py`, register E506; the owner's decision on gap D,
2026-11-02: exact lookups and folds built by code over the whole ledger, nothing summarised, nothing stored).

The law: what the index finds is what a full scan of the ledger finds. The oracle below writes every field path out
by hand with string operations (the tool uses regular expressions) and imports nothing from the tool; it is held on
300 seeded random ledgers and on a frozen copy of the real one (`fixtures/founder-ledger-4423ff3.jsonl.gz`, the brain
at `4423ff3`, the git blob's bytes). The folds are held to naive quadratic scans. The trailing comment on a test names
the mutants it kills (`local/mutate.py`)."""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import random
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from snowball_bootstrap import ledgercheck

from helpers import FOUNDER_DIR, load_ledger_index

LI = load_ledger_index()
TOOL = FOUNDER_DIR / "ledger_index.py"
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "founder-ledger-4423ff3.jsonl.gz"
KEYS = ("kind", "part", "derivation", "trust", "row", "hash", "supersedes", "commit", "day", "path", "report", "tag")
KINDS = ("session_start", "decision", "build", "blocked", "seed_issue", "cost", "session_end", "learning")


# ---- the oracle: the rules of `ledger_index --help`, written out by hand ----------------------------------------
LOWER = frozenset("abcdefghijklmnopqrstuvwxyz_")
DIGITS = frozenset("0123456789")
HEX = frozenset("0123456789abcdef")
FIELD = {"kind": "kind", "part": "part", "derivation": "derivation", "trust": "trust", "row": "row_id",
         "hash": "row_hash", "supersedes": "supersedes", "commit": "snapshot_id"}


def o_word(ref: str):
    """(word, rest) when the ref is `<a-z_ letters>:` and the character after the colon is no digit."""
    colon = ref.find(":")
    if colon < 1 or any(c not in LOWER for c in ref[:colon]):
        return None
    rest = ref[colon + 1:]
    if rest and rest[0] in DIGITS:
        return None
    return ref[:colon], rest


def o_cut(ref: str) -> str:
    """The ref without a final `:n` or `:n-m`."""
    head, colon, tail = ref.rpartition(":")
    first, dash, second = tail.partition("-")

    def number(text):
        return text != "" and all(c in DIGITS for c in text)
    return head if colon and number(first) and (not dash or number(second)) else ref


def o_refs(row: dict) -> list:
    payload = row.get("payload")
    if type(payload) is dict and type(payload.get("refs")) is list:
        return [ref for ref in payload["refs"] if type(ref) is str]
    return []


def o_tags(row: dict) -> list:
    return [(found[0], found[1]) for found in map(o_word, o_refs(row)) if found and found[1] != ""]


def o_values(row: dict, key: str) -> list:
    if key in FIELD:
        value = row.get(FIELD[key])
        return [value] if type(value) is str else []
    if key == "day":
        return [row["ts"][:10]] if type(row.get("ts")) is str else []
    if key == "path":
        out = [o_cut(ref) for ref in o_refs(row) if o_word(ref) is None]
        evidence = row.get("evidence_refs")
        if type(evidence) is list:
            out += [item["path"] for item in evidence if type(item) is dict and type(item.get("path")) is str]
        return [path for path in out if path != ""]
    if key == "report":
        out = []
        for path in o_values(row, "path"):
            stem = path[len("reports/"):-len(".json")]
            if path.startswith("reports/") and path.endswith(".json") and len(path) > len("reports/.json") \
                    and "/" not in stem:
                out.append(stem)
        return out
    if key == "tag":
        return [f"{word}:{value}" for word, value in o_tags(row)]
    raise AssertionError(key)


def o_match(key: str, value: str, query: str) -> bool:
    if key == "commit" and len(query) >= 7 and all(c in HEX for c in query):
        return value.startswith(query)
    if key == "under":
        return value.startswith(query)
    if key == "report":
        return value == query or value.startswith(query + "-")
    return value == query


def o_table(rows: list) -> list:
    """Each row's values of every key, read once: (line, {key: values})."""
    return [(line, {key: o_values(r, key) for key in KEYS}) for line, r in rows]


def o_find(rows: list, conds: list, table: list | None = None) -> list:
    """Lines of the rows meeting every (key, query): every row scanned for every query, nothing indexed."""
    out = []
    for line, held in o_table(rows) if table is None else table:
        for key, query in conds:
            for value in held["path" if key == "under" else key]:
                if o_match(key, value, query):
                    break
            else:
                break  # no value of this row meets this condition
        else:
            out.append(line)
    return out


def o_rows(data: bytes) -> list:
    """(line, row) of a ledger whose every line is a JSON object (the generated ones)."""
    return [(n, json.loads(raw)) for n, raw in enumerate(data.split(b"\n")[:-1], start=1)]


# ---- ledgers ------------------------------------------------------------------------------------------------------
def dump(rows: list, ascii_only: bool = False) -> bytes:
    return b"".join((json.dumps(row, ensure_ascii=ascii_only) + "\n").encode("utf-8") for row in rows)


def row(n: int, kind: str = "decision", refs=(), **extra) -> dict:
    out = {"row_id": f"f{n}", "ts": "2026-11-02T00:00:00Z", "part": "founder", "kind": kind,
           "payload": {"summary": f"row {n}", "refs": list(refs)}, "derivation": "llm_inference", "trust": "inferred",
           "snapshot_id": "a" * 40, "evidence_refs": [], "prev_hash": "0" * 64, "row_hash": f"{n:064x}"}
    out.update(extra)
    return out


REF_SHAPES = ("seed/x.py", "seed/x.py:12", "seed/x.py:3-9", "seed/y.py:3-", "docs/", "docs/a/b.md:7", "foo:12",
              "Seed/X.py", "spec/ü.md:1", "reports/seed-043-x.json", "reports/seed-043-x.json:4",
              "reports/seed-04.json",
              "reports/sub/x.json", "reports/.json", "closes:f999", "see:f3", "https://example.invalid/a:1", "a:b:c",
              "x:", "kind:1-2", "", "a:1:2", "docs/a-b.md:1-2-3")


def random_ledger(rng: random.Random) -> bytes:
    commits = ["".join(rng.choice("0123456789abcdef") for _ in range(40)) for _ in range(3)]
    commits.append(commits[0][:7])
    rows, hashes = [], []
    count = rng.randint(0, 80)
    for i in range(1, count + 1):
        refs = []
        for _ in range(rng.randint(0, 4)):
            shape = rng.random()
            refs.append(f"closes:f{rng.randint(1, i)}" if shape < 0.15 else f"closes:f{rng.randint(i + 1, count + 3)}"
                        if shape < 0.25 else rng.choice(REF_SHAPES))
        if refs and rng.random() < 0.2:
            refs.append(refs[0])  # a duplicate ref
        if rng.random() < 0.03:
            refs.append(7)  # not a string: no key
        evidence = [{"path": rng.choice(("seed/x.py", "spec/ü.md", "reports/seed-050.json", "docs/")),
                     "line_start": 1, "line_end": 2} for _ in range(rng.randint(0, 2))]
        evidence += [{"path": 7}, "x"] if rng.random() < 0.05 else []
        new = {"row_id": f"f{i}" if rng.random() > 0.05 or not rows else rng.choice(rows)["row_id"],
               "ts": f"2026-11-0{rng.randint(1, 3)}T0{rng.randint(0, 9)}:00:00Z", "part": "founder",
               "kind": rng.choice(KINDS), "payload": {"summary": f"row {i} ünï {rng.random()}", "refs": refs},
               "derivation": rng.choice(("llm_inference", "tool", "test_verified")),
               "trust": rng.choice(("inferred", "observed", "verified")), "snapshot_id": rng.choice(commits),
               "evidence_refs": evidence, "prev_hash": hashes[-1] if hashes else "0" * 64,
               "row_hash": f"{rng.getrandbits(256):064x}"}
        odd = rng.random()
        if odd < 0.02:
            new["kind"] = ["decision"]
        elif odd < 0.04:
            new["payload"] = "not an object"
        elif odd < 0.06:
            new["payload"]["refs"] = "not a list"
        elif odd < 0.08:
            new["snapshot_id"] = 12
        elif odd < 0.10:
            new["ts"] = None
        elif odd < 0.12:
            new["row_id"] = 3
        elif odd < 0.14:
            new["part"] = "other"
        if rng.random() < 0.1:
            new["supersedes"] = rng.choice(hashes) if hashes and rng.random() < 0.6 else rng.choice(("f" * 64, 5))
        rows.append(new)
        hashes.append(new["row_hash"])
    return dump(rows, ascii_only=rng.random() < 0.5)


def queries(rows: list, rng: random.Random) -> list:
    """(key, query) pairs: every present value of every key, five absent ones, every 7-character commit prefix,
    every --under prefix and the report prefixes on both sides of a dash."""
    out = []
    for key in KEYS:
        present = list(dict.fromkeys(v for _line, r in rows for v in o_values(r, key)))
        out += [(key, v) for v in present]
        out += [(key, v) for v in ("zz-absent", "f0", "seed", "SEED/X.PY", "reports/seed-043-x")]
        if key == "commit":
            out += [(key, v[:7]) for v in present if len(v) >= 7] + [(key, v[:6]) for v in present]
        if key == "path":
            for path in present:
                out += [("under", path[:i + 1]) for i, c in enumerate(path) if c == "/"]
                out += [("under", path), ("under", path[:1])]
        if key == "report":
            for stem in present:
                parts = stem.split("-")
                out += [(key, "-".join(parts[:i])) for i in range(1, len(parts))] + [(key, stem[:-1])]
    return list(dict.fromkeys(out))


class LedgerFiles(unittest.TestCase):
    def ledger(self, data: bytes) -> str:
        fd, path = tempfile.mkstemp(suffix=".jsonl", prefix="ledger-index-")
        os.write(fd, data)
        os.close(fd)
        self.addCleanup(os.unlink, path)
        return path


def ask(path: str, *argv: str) -> tuple[int, dict, list]:
    code, text = LI.answer([*argv, "--ledger", path])
    lines = text.splitlines()
    return code, json.loads(lines[0]), [json.loads(line) for line in lines[1:]]


def every_page(path: str, *argv: str) -> tuple[dict, list]:
    """Follow `next` to the end; the count stays the same on every page."""
    _code, head, items = ask(path, *argv)
    first = head
    while head["next"]:
        _code, head, more = ask(path, *argv, *head["next"].split())
        assert head["count"] == first["count"], (head, first)
        items += more
    return first, items


# ---- the bytes read ---------------------------------------------------------------------------------------------
class BytesTest(LedgerFiles):
    def test_each_line_is_one_row(self):  # lindex_first_row_dropped lindex_last_row_dropped
        """Every line is read once, and the header says which bytes: size, sha256, rows."""
        data = dump([row(1), row(2), row(3)])
        path = self.ledger(data)
        code, head, items = ask(path, "find", "--order", "oldest")
        self.assertEqual(code, 0)
        self.assertEqual([item["line"] for item in items], [1, 2, 3])
        self.assertEqual((head["rows"], head["bytes"], head["sha256"]),
                         (3, len(data), hashlib.sha256(data).hexdigest()))
        self.assertEqual((head["tool"], head["verified"], head["complete"], head["unreadable"]),
                         ("ledger_index/1", False, True, []))
        self.assertEqual(ask(self.ledger(b""), "find")[1]["tip"], None)

    def test_unreadable_lines_are_listed_and_the_rest_answers(self):  # lindex_unreadable_line_skipped
        """Exit 1 and `complete: false` name the lines not read; every answer still covers the readable lines, as a
        scan of those lines finds."""
        rows = [row(1, refs=["seed/x.py"]), row(2, refs=["seed/x.py"]), row(4, refs=["seed/x.py"])]
        data = dump(rows[:2]) + b'{"row_id": "f3", "kind": "decision", "kind": "build"}\n' + dump(rows[2:]) + b"{"
        code, head, items = ask(self.ledger(data), "history", "seed/x.py")
        self.assertEqual(code, 1)
        self.assertFalse(head["complete"])
        self.assertEqual(head["unreadable"],
                         [{"line": 3, "rule": "duplicate_key"}, {"line": 5, "rule": "unterminated"}])
        self.assertEqual(head["unreadable_count"], 2)
        self.assertEqual([item["line"] for item in items], [1, 2, 4])
        self.assertEqual(head["rows"], 3)

    def test_the_read_rules_are_a_subset_of_the_referees(self):  # lindex_duplicate_key_accepted
        """Reuse by test, not by copy (the referee's code never enters the capsule: `prompt.md` forbids reading it and
        MF1's chain is the Founder's own task). A line the tool does not read is one `ledgercheck` rejects, under the
        same rule's name; what the referee rejects and the tool reads is only what the chain judges: a float, an
        integer past 2^53, a lone surrogate, nesting past 64."""
        corpus = {b'\xff{"a": 1}': "not_utf8", b'{"a": 1, "a": 2}': "duplicate_key", b'{"a": NaN}': "noncanonical",
                  b'{"a": -Infinity}': "noncanonical", b"[1, 2]": "not_json", b'"text"': "not_json", b"": "not_json",
                  b"{": "not_json", b'{"a": 1} x': "not_json", "﻿{}".encode(): "not_json",
                  b'{"a": ' + b"9" * 5000 + b"}": "noncanonical", b"[" * 100000: "too_deep",
                  b'{"a": 1.5}': None, b'{"a": 9007199254740993}': None, b'{"a": "\\ud800"}': None,
                  b'{"a": ' * 65 + b"1" + b"}" * 65: None, b'{"a": 1}\r': None, b'{"kind": "decision"}': None}
        for raw, rule in corpus.items():
            with self.subTest(line=raw[:40]):
                try:
                    LI.read_line(raw)
                    mine = None
                except LI.Unreadable as exc:
                    mine = str(exc)
                try:
                    ledgercheck._row(raw)
                    referee = None
                except ledgercheck._NotARow as exc:
                    referee = str(exc)
                self.assertEqual(mine, rule)
                if mine is not None:
                    self.assertEqual(referee, mine)
                elif referee is not None:
                    self.assertIn(referee, ("noncanonical", "too_deep"))
        data = b'{"a": 1}\n{"b": 2}'
        self.assertIn(f"{ledgercheck.INVALID}:unterminated:L2", ledgercheck.check(data, None, True))
        self.assertEqual(LI.Ledger("x", data).unreadable, [{"line": 2, "rule": "unterminated"}])

    def test_the_tip_is_the_last_readable_row_and_moves_with_an_append(self):  # lindex_tip_from_first_row
        path = self.ledger(dump([row(1), row(2)]) + b"not json\n")
        head = ask(path, "tail")[1]
        self.assertEqual(head["tip"], {"line": 2, "row_id": "f2", "row_hash": f"{2:064x}"})
        before = ask(self.ledger(dump([row(1), row(2)])), "tail")[1]
        after = ask(self.ledger(dump([row(1), row(2), row(3)])), "tail")[1]
        self.assertEqual(before["tip"]["line"], 2)
        self.assertEqual(after["tip"], {"line": 3, "row_id": "f3", "row_hash": f"{3:064x}"})
        self.assertNotEqual(before["sha256"], after["sha256"])
        self.assertEqual((before["rows"], after["rows"]), (2, 3))
        odd = ask(self.ledger(dump([row(1), row(2, row_id=5, row_hash=None)])), "tail")[1]
        self.assertEqual(odd["tip"], {"line": 2, "row_id": None, "row_hash": None})  # a field of the wrong type: null

    def test_no_ledger_and_a_bad_query_exit_2(self):
        code, text = LI.answer(["find", "--ledger", str(Path(tempfile.gettempdir()) / "no-such-ledger.jsonl")])
        self.assertEqual((code, json.loads(text)["error"]), (2, "no ledger: FileNotFoundError"))
        path = self.ledger(dump([row(1), row(2)]))
        for argv in (["show", "nope"], ["named", "x1"], ["unclosed", "--tag", "Bad"], ["text", ""], ["history"],
                     ["show", "1", "2", "--from", "3"]):
            with self.subTest(argv=argv):
                self.assertEqual(LI.answer([*argv, "--ledger", path])[0], 2)
        with open(os.devnull, "w") as quiet, mock.patch("sys.stderr", quiet):
            for argv in (["find", "--limit", "0"], ["find", "--limit", "201"], ["keys", "nokey"], ["nocommand"]):
                with self.subTest(argv=argv), self.assertRaises(SystemExit) as stop:
                    LI.answer([*argv, "--ledger", path])
                self.assertEqual(stop.exception.code, 2)


# ---- the folds against naive scans ------------------------------------------------------------------------------
def o_unclosed(rows: list, tag: str, kinds: tuple) -> list:
    out = []
    for line, r in rows:
        rid = r.get("row_id")
        if r.get("kind") not in kinds or type(rid) is not str:
            continue
        namers = [(n, s) for n, s in rows if (tag, rid) in o_tags(s)]
        out.append({"line": line, "closed_by": [{"line": n, "row_id": s.get("row_id") if type(s.get("row_id")) is str
                                                 else None, "kind": s.get("kind") if type(s.get("kind")) is str
                                                 else None} for n, s in namers if n > line],
                    "early": [n for n, _s in namers if n <= line],
                    "ambiguous": sum(1 for _n, s in rows if s.get("row_id") == rid) > 1})
    return out


def o_sessions(rows: list) -> list:
    starts = [n for n, r in rows if r.get("kind") == "session_start"]
    ends = [n for n, r in rows if r.get("kind") == "session_end"]
    out, used = [], set()
    for i, start in enumerate(starts):
        stop = starts[i + 1] if i + 1 < len(starts) else float("inf")
        mine = [e for e in ends if start < e < stop]
        out.append((start, "finished" if mine else "unfinished", mine[0] if mine else None))
        used |= set(mine[:1])
    out += [(e, "orphan_end", e) for e in ends if e not in used]
    return sorted(out)


def o_named(rows: list, target: str) -> list:
    ids, is_id = {target}, target[:1] == "f" and len(target) > 1 and all(c in DIGITS for c in target[1:])
    for _n, r in rows:
        if is_id and r.get("row_id") == target and type(r.get("row_hash")) is str:
            ids.add(r["row_hash"])
        if not is_id and r.get("row_hash") == target and type(r.get("row_id")) is str:
            ids.add(r["row_id"])
    return [n for n, r in rows if any(v in ids for _t, v in o_tags(r)) or r.get("supersedes") in ids]


class FoldTest(LedgerFiles):
    def crafted(self) -> str:
        rows = [row(1, "seed_issue"), row(2, "decision", ["closes:f1"]),  # closed forward
                row(3, "decision", ["closes:f4"]), row(4, "seed_issue"),  # named only before: open
                row(5, "blocked", ["closes:f999"]),  # dangling ref, open item
                row(6, "seed_issue"), row(7, "build", ["closes:f6", "closes:f6"]), row(8, "decision", ["closes:f6"]),
                row(9, "seed_issue"), row(10, "seed_issue", row_id="f9"), row(11, "cost", ["closes:f9"]),
                row(12, "learning", ["see:f1"])]
        return self.ledger(dump(rows))

    def test_only_a_later_namer_closes_a_row(self):  # lindex_early_closer_counts lindex_row_listed_twice
        """Each closer is shown once, an earlier namer never closes, a duplicated row_id is ambiguous."""
        path = self.crafted()
        head, items = every_page(path, "unclosed", "--tag", "closes", "--order", "oldest")
        self.assertEqual(head["rule"], "structural: the closer's own validity is not judged")
        self.assertEqual([i["line"] for i in items], [4, 5])
        self.assertEqual(items[0]["early"], [{"line": 3, "row_id": "f3", "kind": "decision"}])
        _head, every = every_page(path, "unclosed", "--tag", "closes", "--all", "--order", "oldest")
        by_line = {i["line"]: i for i in every}
        self.assertEqual(list(by_line), [1, 4, 5, 6, 9, 10])
        self.assertEqual(by_line[6]["closed_by"], [{"line": 7, "row_id": "f7", "kind": "build"},
                                                   {"line": 8, "row_id": "f8", "kind": "decision"}])
        self.assertEqual([by_line[n]["ambiguous"] for n in (9, 10, 1)], [True, True, False])
        self.assertEqual([c["line"] for c in by_line[9]["closed_by"]], [11])
        self.assertEqual([i["line"] for i in every_page(path, "unclosed", "--tag", "see", "--kinds", "seed_issue")[1]],
                         [10, 9, 6, 4])  # any tag the caller names; f1 is named by see:f1

    def test_unclosed_is_a_scan_of_every_later_row(self):  # lindex_early_closer_counts lindex_row_listed_twice
        rng = random.Random(506)
        for case in range(60):
            data = random_ledger(rng)
            rows, path = o_rows(data), self.ledger(data)
            for kinds in (("seed_issue", "blocked"), ("decision",)):
                expected = o_unclosed(rows, "closes", kinds)
                _head, every = every_page(path, "unclosed", "--tag", "closes", "--kinds", ",".join(kinds), "--all",
                                          "--order", "oldest")
                got = [{"line": i["line"], "closed_by": i["closed_by"], "early": [e["line"] for e in i["early"]],
                        "ambiguous": i["ambiguous"]} for i in every]
                self.assertEqual(got, expected, case)
                _head, open_ = every_page(path, "unclosed", "--tag", "closes", "--kinds", ",".join(kinds))
                self.assertEqual([i["line"] for i in open_],
                                 [e["line"] for e in reversed(expected) if not e["closed_by"]])

    def test_sessions_pair_in_line_order_and_an_unfinished_one_is_named(self):  # lindex_unfinished_session_missed
        rows = [row(1, "session_end"), row(2, "session_start"), row(3, "decision"), row(4, "session_start"),
                row(5, "session_end"), row(6, "session_end"), row(7, "session_start"), row(8, "cost")]
        path = self.ledger(dump(rows))
        head, items = every_page(path, "sessions", "--order", "oldest")
        self.assertEqual((head["sessions"], head["finished"], head["unfinished"], head["orphan_end"]),
                         (3, 1, [2, 7], [1, 6]))
        self.assertEqual([(i["line"], i["state"]) for i in items],
                         [(1, "orphan_end"), (2, "unfinished"), (4, "finished"), (6, "orphan_end"), (7, "unfinished")])
        self.assertEqual(items[2]["end"]["line"], 5)
        _head, last = every_page(path, "sessions", "--last", "2")
        self.assertEqual([i["line"] for i in last], [4, 5, 6, 7, 8])  # from the 2nd last start to the end
        rng = random.Random(5060)
        for case in range(60):
            data = random_ledger(rng)
            _head, items = every_page(self.ledger(data), "sessions", "--order", "oldest")
            got = [(i["line"], i["state"], (i["end"] or {}).get("line")) for i in items]
            self.assertEqual(got, o_sessions(o_rows(data)), case)

    def test_named_finds_tag_refs_and_supersedes_both_ways(self):  # lindex_supersedes_not_named
        first = "a" * 64  # a hash starting with a digit is no tag value (`see:0...` is a path)
        rows = [row(1, "learning", row_hash=first), row(2, "decision", supersedes=first),
                row(3, "decision", ["closes:f1"]), row(4, "decision", ["see:" + first]),
                row(5, "decision", ["closes:f2"]),
                row(6, "decision", ["see:" + f"{1:064x}"])]
        path = self.ledger(dump(rows))
        self.assertEqual([i["line"] for i in every_page(path, "named", "f1", "--order", "oldest")[1]], [2, 3, 4])
        _head, items = every_page(path, "named", first, "--order", "oldest")
        self.assertEqual([(i["line"], i["via"]) for i in items], [(2, ["supersedes"]), (3, ["refs:closes"]),
                                                                  (4, ["refs:see"])])
        rng = random.Random(50600)
        for case in range(40):
            data = random_ledger(rng)
            rows, path = o_rows(data), self.ledger(data)
            for target in [r.get("row_id") for _n, r in rows[:5] if type(r.get("row_id")) is str] + \
                          [r["row_hash"] for _n, r in rows if "supersedes" in r][:3] + ["f999"]:
                got = [i["line"] for i in every_page(path, "named", target, "--order", "oldest")[1]]
                self.assertEqual(got, o_named(rows, target), (case, target))


# ---- each key's rule ----------------------------------------------------------------------------------------------
class KeysTest(LedgerFiles):
    def lines(self, path: str, *argv: str) -> list:
        return [i["line"] for i in every_page(path, "find", *argv, "--order", "oldest")[1]]

    def test_a_path_is_a_ref_with_its_line_span_cut_off(self):  # lindex_line_span_kept
        path = self.ledger(dump([row(1, refs=["seed/x.py"]), row(2, refs=["seed/x.py:12"]),
                                 row(3, refs=["seed/x.py:3-9"]), row(4, refs=["seed/x.py:3-"]),
                                 row(5, refs=["closes:f1", "docs/a.md:1-2-3"])]))
        self.assertEqual(self.lines(path, "--path", "seed/x.py"), [1, 2, 3])
        self.assertEqual(self.lines(path, "--path", "seed/x.py:3-"), [4])
        self.assertEqual(self.lines(path, "--path", "docs/a.md:1-2-3"), [5])
        self.assertEqual(self.lines(path, "--path", "closes:f1"), [])

    def test_a_ref_like_foo_12_is_a_path_and_never_a_tag(self):  # lindex_tag_digit_guard_lost
        path = self.ledger(dump([row(1, refs=["foo:12", "closes:f9", "kind:1-2"])]))
        self.assertEqual(self.lines(path, "--path", "foo"), [1])
        self.assertEqual(self.lines(path, "--path", "kind"), [1])
        self.assertEqual(self.lines(path, "--tag", "foo:12"), [])
        self.assertEqual(self.lines(path, "--tag", "closes:f9"), [1])
        values = [i["value"] for i in ask(path, "keys", "tag")[2]]
        self.assertEqual(values, ["closes:f9"])

    def test_a_path_in_evidence_refs_is_a_path(self):  # lindex_evidence_paths_ignored
        path = self.ledger(dump([row(1, evidence_refs=[{"path": "spec/tohum/26.md", "line_start": 1, "line_end": 2}]),
                                 row(2, evidence_refs=[{"path": 7}, "spec/tohum/26.md"])]))
        _head, items = every_page(path, "find", "--path", "spec/tohum/26.md")
        self.assertEqual([(i["line"], i["via"]) for i in items], [(1, ["evidence_refs"])])

    def test_paths_are_compared_byte_for_byte(self):  # lindex_paths_casefolded
        path = self.ledger(dump([row(1, refs=["Seed/X.py"]), row(2, refs=["seed/x.py"])]))
        self.assertEqual(self.lines(path, "--path", "Seed/X.py"), [1])
        self.assertEqual(self.lines(path, "--path", "seed/x.py"), [2])
        self.assertEqual(self.lines(path, "--under", "seed/"), [2])

    def test_a_commit_query_of_seven_hex_characters_is_a_prefix(self):  # lindex_commit_exact_only
        full = "0123456789abcdef0123456789abcdef01234567"
        path = self.ledger(dump([row(1, snapshot_id=full), row(2, snapshot_id=full[:7]), row(3, snapshot_id="xyz")]))
        self.assertEqual(self.lines(path, "--commit", full[:7]), [1, 2])
        self.assertEqual(self.lines(path, "--commit", full), [1])
        self.assertEqual(self.lines(path, "--commit", full[:6]), [])  # shorter: exact only
        self.assertEqual(self.lines(path, "--commit", "xyz"), [3])
        head = ask(path, "find", "--commit", full[:7])[1]
        self.assertEqual(head["text_also"], {"tier": "text", "guarantee": "none", "terms": [full[:7]], "count": 0})

    def test_a_report_query_ends_at_a_dash(self):  # lindex_report_prefix_without_dash
        """A report query matches its own stem and the stems it starts before a dash."""
        path = self.ledger(dump([row(1, refs=["reports/seed-043-sentinel.json:3"]),
                                 row(2, refs=["reports/seed-04.json"]),
                                 row(3, refs=["reports/sub/seed-043.json"]),
                                 row(4, evidence_refs=[{"path": "reports/seed-043.json"}])]))
        self.assertEqual(self.lines(path, "--report", "seed-043"), [1, 4])
        self.assertEqual(self.lines(path, "--report", "seed-04"), [2])
        self.assertEqual(self.lines(path, "--report", "seed"), [1, 2, 4])
        self.assertEqual(self.lines(path, "--report", "seed-043-sentinel"), [1])

    def test_keys_are_anded_across_and_ored_within(self):
        path = self.ledger(dump([row(1, "decision", ["a/b"]), row(2, "build", ["a/b"]), row(3, "decision", ["c"]),
                                 row(4, "cost", ts="x")]))
        self.assertEqual(self.lines(path, "--kind", "decision", "--path", "a/b"), [1])
        self.assertEqual(self.lines(path, "--kind", "decision", "--kind", "build"), [1, 2, 3])
        self.assertEqual(self.lines(path, "--line", "3", "--line", "4"), [3, 4])
        self.assertEqual(self.lines(path, "--day", "2026-11-02", "--row", "f2", "--hash", f"{2:064x}"), [2])
        self.assertEqual(self.lines(path), [1, 2, 3, 4])


# ---- the law on random ledgers ----------------------------------------------------------------------------------
class LawTest(LedgerFiles):
    def test_what_the_index_finds_is_what_a_full_scan_finds(self):
        """300 seeded ledgers of 0-80 rows: every key's every present value, five absent ones, every commit prefix,
        every --under prefix, report prefixes, 200 AND pairs and OR groups; then the command line itself, page by
        page, and `keys` against the oracle's distinct values."""
        rng = random.Random(2026_11_02)
        for case in range(300):
            data = random_ledger(rng)
            rows, ledger = o_rows(data), LI.Ledger("mem", data)
            table = o_table(rows)
            scan = {cond: o_find(rows, [cond], table) for cond in queries(rows, rng)}  # a full scan for each query
            for cond, expected in scan.items():
                got = [line for line, _row, _via in LI.find(ledger, [[cond]])]
                self.assertEqual(got, expected, (case, cond))
            present = [cond for cond, lines in scan.items() if lines]
            for _ in range(200 if present else 0):
                pair = [rng.choice(present), rng.choice(present)]
                got = [line for line, _row, _via in LI.find(ledger, [[c] for c in pair])]
                self.assertEqual(got, sorted(set(scan[pair[0]]) & set(scan[pair[1]])), (case, pair))  # AND
            for key in ("kind", "path", "tag"):
                some = [q for k, q in present if k == key][:3]
                got = [line for line, _row, _via in LI.find(ledger, [[(key, q) for q in some]])] if some else []
                self.assertEqual(got, sorted({n for q in some for n in scan[(key, q)]}), (case, key))  # OR
            if case % 10:
                continue
            path = self.ledger(data)
            for key in KEYS:
                first = next((q for k, q in present if k == key), None)
                if first is not None:
                    head, items = every_page(path, "find", f"--{key}", first, "--order", "oldest", "--limit", "7")
                    self.assertEqual([i["line"] for i in items], scan[(key, first)], (case, key))
                counts = {}
                for line, r in rows:
                    for value in dict.fromkeys(o_values(r, key)):
                        counts.setdefault(value, []).append(line)
                _code, head, items = ask(path, "keys", key, "--top", "200")
                while head["next"]:
                    head, more = ask(path, "keys", key, "--top", "200", *head["next"].split())[1:]
                    items += more
                self.assertEqual({i["value"]: (i["rows"], i["first"], i["last"]) for i in items},
                                 {v: (len(ls), ls[0], ls[-1]) for v, ls in counts.items()}, (case, key))
            for under in [q for k, q in present if k == "under"][:2]:
                got = [i["line"] for i in every_page(path, "history", "--under", under)[1]]
                self.assertEqual(got, scan[("under", under)], (case, under))


# ---- pages --------------------------------------------------------------------------------------------------------
class PagingTest(LedgerFiles):
    def test_count_is_every_match_and_next_rebuilds_the_whole_list(self):  # lindex_count_is_page_size
        rows = [row(n, "seed_issue" if n % 3 else "decision", ["seed/x.py", f"closes:f{n - 4}"]) for n in range(1, 31)]
        path = self.ledger(dump(rows))
        for argv in (["find", "--path", "seed/x.py"], ["history", "seed/x.py"], ["named", "f2"],
                     ["unclosed", "--tag", "closes", "--all"], ["text", "row"], ["sessions", "--last", "1"]):
            whole = ask(path, *argv, "--limit", "200")
            for order in ("newest", "oldest"):
                with self.subTest(argv=argv, order=order):
                    _code, head, first = ask(path, *argv, "--limit", "3", "--order", order)
                    self.assertEqual(head["count"], whole[1]["count"])
                    self.assertEqual(head["shown"], len(first))
                    _head, paged = every_page(path, *argv, "--limit", "3", "--order", order)
                    expected = sorted(whole[2], key=lambda i: i["line"], reverse=order == "newest")
                    self.assertEqual(paged, expected)
        head = ask(path, "find", "--limit", "5")[1]
        self.assertEqual((head["count"], head["shown"], head["next"]), (30, 5, "--before 26"))
        keys_head = ask(path, "keys", "row", "--top", "4")[1]
        self.assertEqual((keys_head["count"], keys_head["shown"], keys_head["next"]), (30, 4, "--skip 4"))
        _code, head, items = ask(path, "tail", "5")
        self.assertEqual(([i["line"] for i in items], head["next"]), ([26, 27, 28, 29, 30], "--before 26"))
        _code, head, items = ask(path, "tail", "5", *head["next"].split())
        self.assertEqual([i["line"] for i in items], [21, 22, 23, 24, 25])
        self.assertIsNone(ask(path, "tail", "5", "--before", "6")[1]["next"])  # rows 1-5: nothing older

    def test_an_answer_stays_inside_the_budget_on_the_real_ledger(self):
        """The CLI keeps only a 2 KB preview of a tool output over 30 KB (22 session logs, E506): every default answer
        stays under it, and a page ends at 24,000 bytes whatever --limit asks."""
        path = self.ledger(gzip.decompress(FIXTURE.read_bytes()))
        others = [["text", "-i", "exit"], ["sessions"], ["tail", "200"], ["keys", "path"], ["find", "--limit", "200"]]
        for argv in [["find", "--kind", kind] for kind in KINDS] + others:
            with self.subTest(argv=argv):
                code, text = LI.answer([*argv, "--ledger", path])
                self.assertEqual(code, 0)
                self.assertLessEqual(len(text), 30_000)
                self.assertLessEqual(len(text.encode("utf-8")), LI.BUDGET + 1)
        code, text = LI.answer(["show", *map(str, range(1, 593)), "--ledger", path])
        head = json.loads(text.splitlines()[0])
        self.assertLess(len(text.encode("utf-8")), 24_000)
        self.assertEqual(head["next"].split()[0], str(head["shown"] + 1))  # the selectors left
        long_line = "x" * 60_000
        path = self.ledger(dump([row(1), row(2, payload={"summary": long_line, "refs": []})]))
        texts, start = [], 0
        while True:
            _code, head, items = ask(path, "show", "2", "--from", str(start))
            texts.append(items[0]["text"])
            if head["next"] is None:
                break
            start = int(head["next"].split()[-1])
        self.assertEqual("".join(texts), Path(path).read_bytes().split(b"\n")[1].decode())


# ---- read-only ----------------------------------------------------------------------------------------------------
class ReadOnlyTest(unittest.TestCase):
    def test_a_run_writes_nothing(self):
        """Every command, run as the capsule runs it (`python3 -I`), in a git repository: nothing changes there."""
        repo = Path(tempfile.mkdtemp(prefix="ledger-index-ro-"))
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        (repo / "founder-ledger.jsonl").write_bytes(dump([row(1, "session_start"), row(2, "seed_issue", ["a/b:1"]),
                                                         row(3, "session_end", ["closes:f2"])]))
        before = sorted(p.relative_to(repo).as_posix() for p in repo.rglob("*") if ".git" not in p.parts)
        ledger = str(repo / "founder-ledger.jsonl")
        for argv in (["find", "--kind", "seed_issue"], ["history", "a/b"], ["named", "f2"], ["show", "1", "f3"],
                     ["unclosed", "--tag", "closes"], ["sessions"], ["tail"], ["keys", "tag"], ["text", "row"],
                     ["--help"]):
            proc = subprocess.run([sys.executable, "-I", str(TOOL), *argv, *(["--ledger", ledger] if argv != ["--help"]
                                                                            else [])],
                                  cwd=repo, capture_output=True, timeout=60)
            self.assertEqual(proc.returncode, 0, (argv, proc.stderr))
        status = subprocess.run(["git", "-C", str(repo), "status", "--porcelain", "--ignored"], capture_output=True,
                                text=True, check=True).stdout
        self.assertEqual(status.strip(), "?? founder-ledger.jsonl")
        self.assertEqual(sorted(p.relative_to(repo).as_posix() for p in repo.rglob("*") if ".git" not in p.parts),
                         before)


# ---- the real ledger ------------------------------------------------------------------------------------------------
class RealLedgerTest(LedgerFiles):
    """The brain's `founder-ledger.jsonl` at `4423ff3` (git blob bytes; a CRLF checkout of it is 812,665 B)."""

    @classmethod
    def setUpClass(cls):
        cls.data = gzip.decompress(FIXTURE.read_bytes())
        cls.rows = o_rows(cls.data)
        cls.table = o_table(cls.rows)
        cls.ledger_ = LI.Ledger("fixture", cls.data)

    def test_the_fixture_is_the_brains_ledger_and_the_law_holds_on_it(self):
        self.assertEqual((len(self.data), len(self.rows), self.ledger_.unreadable), (812_073, 592, []))
        self.assertEqual(hashlib.sha256(self.data).hexdigest(),
                         "78722267ff8b5453140ab641d9f21d396ce3a5bbee773e41d66ad0f124389b61")
        tip = self.ledger_.tip()
        self.assertEqual((tip["line"], tip["row_id"]), (592, "f592"))
        self.assertTrue(tip["row_hash"].startswith("e7c6fac6675392ec"))
        self.assertEqual(ledgercheck.check(self.data, self.data, True), [])  # the referee reads it whole and valid
        for key in KEYS:
            index: dict = {}
            for line, held in self.table:
                for value in dict.fromkeys(held[key]):
                    index.setdefault(value, []).append(line)
            got = {value: list(dict.fromkeys(line for line, _w in holders))
                   for value, holders in self.ledger_.index(key).items()}
            self.assertEqual(got, index, key)  # the same values, each with the same rows
            for value, lines in index.items():  # every present value, as the command finds it
                found = [line for line, _r, _v in LI.find(self.ledger_, [[(key, value)]])]
                prefixed = key in ("commit", "report")  # a query may match more values than its own
                self.assertEqual(found, o_find(self.rows, [(key, value)], self.table) if prefixed else lines,
                                 (key, value))
        counts = {key: len({v for _l, r in self.rows for v in o_values(r, key)}) for key in ("path", "commit", "kind")}
        self.assertEqual(counts, {"path": 245, "commit": 110, "kind": 8})

    def test_the_folds_on_the_real_ledger(self):
        path = self.ledger(self.data)
        head, items = every_page(path, "unclosed", "--tag", "closes", "--order", "oldest")
        # the brain's own `ledger.founder open` at 4423ff3 lists these 19 ledger items, in this order
        self.assertEqual([i["row_id"] for i in items],
                         ["f61", "f81", "f213", "f272", "f352", "f427", "f434", "f435", "f440", "f445", "f468", "f491",
                          "f514", "f551", "f558", "f572", "f580", "f588", "f589"])
        self.assertEqual([i["line"] for i in items], [int(i["row_id"][1:]) for i in items])
        _head, every = every_page(path, "unclosed", "--tag", "closes", "--all")
        self.assertEqual(max(len(i["closed_by"]) for i in every), 1)  # no row has two closers today
        self.assertEqual(sum(1 for i in every if i["early"] or i["ambiguous"]), 0)
        head = ask(path, "sessions")[1]
        self.assertEqual([head[k] for k in ("sessions", "finished", "unfinished", "orphan_end")],
                         [84, 84, [], [104]])
        head = ask(path, "find", "--commit", "e68f29ca3f75")[1]
        self.assertEqual((head["count"], head["text_also"]["count"]), (0, 73))  # named only in prose


# ---- the text tier --------------------------------------------------------------------------------------------------
class TextTierTest(LedgerFiles):
    def setUp(self):
        self.path = self.ledger(dump([row(1, payload={"summary": "exit.request written", "refs": []}),
                                      row(2, payload={"summary": "exit_request and EXIT", "refs": ["docs/Exit.md"]}),
                                      row(3, payload={"summary": "prexit straße", "refs": []}, snapshot_id="b" * 40),
                                      row(4, payload={"summary": "STRASSE", "refs": []})]))

    def lines(self, *argv: str) -> list:
        return [i["line"] for i in every_page(self.path, "text", *argv, "--order", "oldest")[1]]

    def test_the_text_tier_says_it_gives_candidates_only(self):  # lindex_text_claims_exact
        head = ask(self.path, "text", "exit")[1]
        self.assertEqual((head["tier"], head["guarantee"]), ("text", "none"))
        self.assertEqual(ask(self.path, "find", "--kind", "decision")[1]["tier"], "exact")
        self.assertNotIn("text_also", ask(self.path, "find", "--kind", "decision")[1])
        for argv in (["--path", "docs/Exit.md"], ["--report", "x"], ["--commit", "b" * 7], ["--under", "docs/"]):
            self.assertEqual(ask(self.path, "find", *argv)[1]["text_also"]["guarantee"], "none", argv)

    def test_terms_are_literal_strings(self):  # lindex_text_is_regex
        self.assertEqual(self.lines("exit.request"), [1])
        self.assertEqual(self.lines("exit_request"), [2])
        self.assertEqual(self.lines("e.it"), [])
        self.assertEqual(self.lines("(", "["), [])

    def test_casefold_and_token(self):
        self.assertEqual(self.lines("exit"), [1, 2, 3])
        self.assertEqual(self.lines("exit", "-i"), [1, 2, 3])
        self.assertEqual(self.lines("EXIT"), [2])
        self.assertEqual(self.lines("exit", "--token"), [1])  # '.' is a boundary, '_' and a letter are not
        self.assertEqual(self.lines("exit", "-i", "--token"), [1, 2])
        self.assertEqual(self.lines("strasse", "-i"), [3, 4])  # casefold: ß is ss
        self.assertEqual(self.lines("bbbbbbb", "Exit.md"), [2, 3])  # OR over terms, refs and snapshot_id too
        _head, items = every_page(self.path, "text", "docs/Exit.md")
        self.assertEqual(items[0]["via"], ["refs"])

    def test_the_text_tier_is_a_scan_of_the_text_fields(self):
        rng = random.Random(7)
        for case in range(30):
            data = random_ledger(rng)
            rows, path = o_rows(data), self.ledger(data)
            for term in ("row 1", "seed/x.py", "ÜNÏ", "f1", "closes:f"):
                for fold in (False, True):
                    def hit(text):
                        return (term.casefold() in text.casefold()) if fold else term in text
                    expected = []
                    for line, r in rows:
                        payload = r.get("payload")
                        fields = [payload["summary"]] if type(payload) is dict else []
                        fields += o_refs(r) + ([r["snapshot_id"]] if type(r.get("snapshot_id")) is str else [])
                        if any(hit(f) for f in fields):
                            expected.append(line)
                    argv = ["text", term, "--order", "oldest"] + (["-i"] if fold else [])
                    self.assertEqual([i["line"] for i in every_page(path, *argv)[1]], expected, (case, term, fold))


if __name__ == "__main__":
    unittest.main()
