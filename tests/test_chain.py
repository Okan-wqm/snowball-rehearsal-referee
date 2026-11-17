"""Test 13 (asama-0/09): chain vectors V1-V3; a broken row and an append-only violation are caught.

Every case drives the command the referee runs, ``python -m ledger.chain`` from ``referee/``, in a
subprocess. Files reach ``verify`` through pipes (``/dev/fd/N``), so the suite writes nothing to disk and
runs in a read-only container. Expected hashes are built here independently of ``ledger.chain``: for rows
with ASCII keys, integers and strings, RFC 8785 is ``json.dumps(sort_keys=True, separators=(",", ":"),
ensure_ascii=False)``; for the cases where that shortcut differs from RFC 8785, the canonical bytes are
written out by hand.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import threading
import unittest

REFEREE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BRAIN = os.path.dirname(REFEREE)
sys.path.insert(0, REFEREE)

from ledger import chain  # noqa: E402
import refusal  # noqa: E402
Z = "0" * 64

V1 = {"row_id": "r1", "ts": "2026-10-28T00:00:00Z", "part": "events", "kind": "genesis", "payload": {},
      "derivation": "tool", "trust": "verified", "snapshot_id": "s0", "evidence_refs": [], "prev_hash": Z}
V1_HASH = "3bae91580aca99362572e9f5f41b3e46c2bc0c29236f72e867faa5cd46ca603a"
V2 = {"row_id": "r2", "ts": "2026-10-28T00:00:01Z", "part": "cost", "kind": "run",
      "payload": {"usd_micros": 0}, "derivation": "tool", "trust": "observed", "snapshot_id": "s0",
      "evidence_refs": [], "prev_hash": V1_HASH}
V2_HASH = "3b10a5bb06351b0933c0e30f7dd55d3a57245743b97fb1faba348351a554a45c"


def ref_hash(row: dict) -> str:
    """Independent row hash for simple rows (ASCII keys, ints, strings, no floats)."""
    body = {k: v for k, v in row.items() if k != "row_hash"}
    canon = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(canon + row["prev_hash"].encode("ascii")).hexdigest()


def build_chain(payloads: list[dict]) -> list[dict]:
    rows, prev = [], Z
    for i, payload in enumerate(payloads, start=1):
        row = {"row_id": "r%d" % i, "ts": "2026-10-29T00:00:%02dZ" % i, "part": "founder", "kind": "decision",
               "payload": payload, "derivation": "tool", "trust": "observed", "snapshot_id": "s0",
               "evidence_refs": [], "prev_hash": prev}
        row["row_hash"] = prev = ref_hash(row)
        rows.append(row)
    return rows


def jsonl(rows: list) -> bytes:
    return b"".join(json.dumps(r, separators=(",", ":")).encode() + b"\n" for r in rows)


def run_chain(args: list, stdin: bytes = b"", files: dict | None = None):
    """Run ``python -m ledger.chain`` from referee/; each bytes value in ``args`` is served as a pipe file."""
    fds, writers, argv = [], [], []
    for arg in args:
        if isinstance(arg, bytes):
            r, w = os.pipe()
            fds.append(r)
            writers.append((w, arg))
            argv.append("/dev/fd/%d" % r)
        else:
            argv.append(arg)

    def feed(fd: int, data: bytes) -> None:
        with os.fdopen(fd, "wb") as fh:
            try:
                fh.write(data)
            except BrokenPipeError:
                pass

    threads = [threading.Thread(target=feed, args=wd) for wd in writers]
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    proc = subprocess.Popen([sys.executable, "-m", "ledger.chain", *argv], cwd=REFEREE, env=env,
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            pass_fds=fds)
    for fd in fds:
        os.close(fd)
    for t in threads:
        t.start()
    out, err = proc.communicate(stdin, timeout=60)
    for t in threads:
        t.join()
    lines = out.decode().splitlines()
    assert len(lines) == 1, "stdout must be one JSON line, got %r (stderr %r)" % (out, err)
    return proc.returncode, json.loads(lines[0]), err


class HashCommand(unittest.TestCase):
    def hash_of(self, text: bytes) -> str:
        code, out, err = run_chain(["hash"], stdin=text)
        self.assertEqual(code, 0, (out, err))
        return out["row_hash"]

    def refused(self, text: bytes) -> None:
        code, out, err = run_chain(["hash"], stdin=text)
        refusal.assert_refused(self, chain, ["hash"], code, out, err)
        self.assertIn("error", out)

    def test_v1_v2(self):
        self.assertEqual(self.hash_of(json.dumps(V1).encode() + b"\n"), V1_HASH)
        self.assertEqual(self.hash_of(json.dumps(V2).encode()), V2_HASH)

    def test_one_byte_changed_gives_another_hash(self):
        text = json.dumps(V1, separators=(",", ":")).encode()
        changed = text.replace(b"00:00:00Z", b"00:00:01Z")
        self.assertNotEqual(changed, text)
        self.assertNotEqual(self.hash_of(changed), V1_HASH)
        self.assertNotEqual(self.hash_of(json.dumps(dict(V2, payload={"usd_micros": 1})).encode()), V2_HASH)

    def test_prev_hash_is_part_of_the_hash(self):
        self.assertNotEqual(self.hash_of(json.dumps(dict(V2, prev_hash=Z)).encode()), V2_HASH)

    def test_key_order_whitespace_and_row_hash_do_not_matter(self):
        shuffled = dict(reversed(list(V2.items())))
        shuffled["row_hash"] = "anything"
        self.assertEqual(self.hash_of(json.dumps(shuffled, indent=None, separators=(" , ", " : ")).encode()), V2_HASH)

    def test_keys_sort_by_utf16_code_units(self):
        # U+1F600 is D83D DE00 in UTF-16, below U+FB01; by code point it would sort after.
        row = {"prev_hash": Z, "ﬁ": 1, "\U0001f600": 2}
        canon = '{"prev_hash":"%s","\U0001f600":2,"ﬁ":1}' % Z
        expected = hashlib.sha256(canon.encode("utf-8") + Z.encode()).hexdigest()
        self.assertEqual(self.hash_of(json.dumps(row).encode()), expected)

    def test_string_escapes(self):
        row = {"prev_hash": Z, "s": "a\"b\\c\n\t\b\f\r\x01\x1f/é \x7f"}
        canon = '{"prev_hash":"%s","s":"a\\"b\\\\c\\n\\t\\b\\f\\r\\u0001\\u001f/é \x7f"}' % Z
        expected = hashlib.sha256(canon.encode("utf-8") + Z.encode()).hexdigest()
        self.assertEqual(self.hash_of(json.dumps(row).encode()), expected)

    def test_literals_and_integers(self):
        row = {"prev_hash": Z, "a": [True, False, None, -7, 9007199254740991, 0]}
        canon = '{"a":[true,false,null,-7,9007199254740991,0],"prev_hash":"%s"}' % Z
        expected = hashlib.sha256(canon.encode() + Z.encode()).hexdigest()
        self.assertEqual(self.hash_of(json.dumps(row).encode()), expected)
        row = {"prev_hash": Z, "a": -9007199254740991}
        canon = '{"a":-9007199254740991,"prev_hash":"%s"}' % Z
        self.assertEqual(self.hash_of(json.dumps(row).encode()), hashlib.sha256(canon.encode() + Z.encode()).hexdigest())

    def test_refuses_what_has_no_canonical_form(self):
        base = json.dumps(V1)[:-1]
        for extra in (', "x": 1.5', ', "x": 1.0', ', "x": 1e2', ', "x": NaN', ', "x": Infinity',
                      ', "x": 9007199254740992', ', "x": -9007199254740992', ', "x": "\\ud800"',
                      ', "x": "\\udc00"', ', "\\ud800": 1', ', "\\udfff": 1', ', "row_id": "dup"'):
            with self.subTest(extra=extra):
                self.refused((base + extra + "}").encode())

    def test_refuses_bad_prev_hash_and_bad_input(self):
        for prev in (Z.upper().replace("0", "A"), Z[:-1], Z + "0", Z + "\n", "\n" + Z, 5, None):
            with self.subTest(prev=prev):
                self.refused(json.dumps(dict(V1, prev_hash=prev)).encode())
        no_prev = {k: v for k, v in V1.items() if k != "prev_hash"}
        self.refused(json.dumps(no_prev).encode())
        self.refused(b"")
        self.refused(b"[1,2]")
        self.refused(b"not json")
        self.refused(json.dumps(V1).encode() + b"\n" + json.dumps(V2).encode())
        self.refused(b"\xff\xfe")

    def test_deep_nesting_is_refused_not_a_traceback(self):
        self.refused(b'{"prev_hash":"%s","x":%s1%s}' % (Z.encode(), b"[" * 100000, b"]" * 100000))


class VerifyCommand(unittest.TestCase):
    def verify(self, data: bytes, previous: bytes | None = None):
        args = ["verify", data] + (["--previous", previous] if previous is not None else [])
        code, out, err = run_chain(args)
        self.assertNotIn(b"Traceback", err)
        self.assertEqual(code, 0 if out["valid"] else 1, out)
        return out

    def assert_broken(self, out: dict, row: str) -> None:
        self.assertFalse(out["valid"], out)
        self.assertEqual(out["broken_row"], row, out)

    def test_v1_v2_chain_is_valid(self):
        out = self.verify(jsonl([dict(V1, row_hash=V1_HASH), dict(V2, row_hash=V2_HASH)]))
        self.assertEqual(out, {"valid": True, "broken_row": None, "line": None, "reason": None})

    def test_v3_edited_payload_breaks_r2_only(self):
        v3 = dict(V2, payload={"usd_micros": 1}, row_hash=V2_HASH)
        out = self.verify(jsonl([dict(V1, row_hash=V1_HASH), v3]))
        self.assert_broken(out, "r2")
        self.assertEqual(out["line"], 2)
        self.assertTrue(self.verify(jsonl([dict(V1, row_hash=V1_HASH)]))["valid"])

    def test_every_single_field_edit_is_caught(self):
        rows = build_chain([{"summary": "a", "refs": []}, {"summary": "b", "refs": ["x"]}, {"summary": "c", "refs": []}])
        self.assertTrue(self.verify(jsonl(rows))["valid"])
        for i, row in enumerate(rows):
            for key in row:
                edited = [dict(r) for r in rows]
                value = edited[i][key]
                edited[i][key] = value + "0" if isinstance(value, str) else ["changed"]
                if key == "row_hash":
                    edited[i][key] = Z
                with self.subTest(row=i, key=key):
                    out = self.verify(jsonl(edited))
                    self.assertFalse(out["valid"])
                    self.assertEqual(out["line"], i + 1)

    def test_broken_link_reorder_delete_and_first_prev(self):
        rows = build_chain([{"n": 1}, {"n": 2}, {"n": 3}])
        self.assert_broken(self.verify(jsonl([rows[0], rows[2]])), "r3")
        self.assert_broken(self.verify(jsonl([rows[1], rows[0], rows[2]])), "r2")
        self.assert_broken(self.verify(jsonl(rows[1:])), "r2")
        missing = dict(rows[0])
        del missing["row_hash"]
        self.assert_broken(self.verify(jsonl([missing])), "r1")

    def test_unusable_lines_are_broken_rows(self):
        rows = build_chain([{"n": 1}, {"n": 2}])
        good = jsonl(rows)
        cases = {
            b"not json\n": "line:1",
            jsonl(rows[:1]) + b"\n" + jsonl(rows[1:]): "line:2",
            jsonl(rows[:1]) + b"[1]\n": "line:2",
            jsonl(rows[:1]) + b"\xff\n": "line:2",
            jsonl(rows[:1]) + b"[" * 100000 + b"]" * 100000 + b"\n": "line:2",
            good.replace(b'"n":2', b'"n":2.0'): "r2",
            good.replace(b'"n":2', b'"n":2,"n":2'): "line:2",
            good + b"\n": "line:3",
        }
        for data, name in cases.items():
            with self.subTest(name=name, data=data[-40:]):
                self.assert_broken(self.verify(data), name)

    def test_empty_file_and_missing_final_newline(self):
        self.assertTrue(self.verify(b"")["valid"])
        self.assertTrue(self.verify(jsonl(build_chain([{"n": 1}]))[:-1])["valid"])

    def test_append_only(self):
        rows = build_chain([{"n": 1}, {"n": 2}, {"n": 3}])
        old = jsonl(rows[:2])
        self.assertTrue(self.verify(jsonl(rows), old)["valid"])
        self.assertTrue(self.verify(old, old)["valid"])
        self.assertTrue(self.verify(jsonl(rows), b"")["valid"])
        self.assert_broken(self.verify(jsonl(rows[:1]), old), "r2")

    def test_rewrite_with_recomputed_hashes_is_refused(self):
        original = build_chain([{"n": 1}, {"n": 2}, {"n": 3}])
        rewritten = build_chain([{"n": 1}, {"n": 20}, {"n": 3}, {"n": 4}])
        self.assertTrue(self.verify(jsonl(rewritten))["valid"])  # a well-formed chain on its own
        out = self.verify(jsonl(rewritten), jsonl(original))
        self.assert_broken(out, "r2")
        self.assertEqual(out["line"], 2)

    def test_same_rows_reserialised_is_not_append_only(self):
        rows = build_chain([{"n": 1}])
        spaced = json.dumps(rows[0], indent=None, separators=(", ", ": ")).encode() + b"\n"
        self.assertTrue(self.verify(spaced)["valid"])
        self.assert_broken(self.verify(spaced, jsonl(rows)), "r1")

    def test_unreadable_file(self):
        for args in (["/nonexistent/ledger.jsonl"], [jsonl(build_chain([{"n": 1}])), "--previous", "/nonexistent/old.jsonl"]):
            with self.subTest(args=args[-1]):
                code, out, _ = run_chain(["verify", *args])
                self.assertEqual(code, 2)
                self.assertEqual(list(out), ["error"])
                self.assertTrue(out["error"].startswith("cannot read: "), out)

    def test_founder_ledger_is_a_valid_chain(self):
        with open(os.path.join(BRAIN, "founder-ledger.jsonl"), "rb") as fh:
            self.assertTrue(self.verify(fh.read())["valid"])


class Library(unittest.TestCase):
    """``canonical`` and ``row_hash`` called from Python (``activate``, ``status.block``, ``ledger.append``):
    a value a JSON line cannot carry is refused with ``ChainError`` too, never another exception."""

    def test_canonical_refuses_values_json_has_no_form_for(self):
        deep: list = []
        for _ in range(100000):
            deep = [deep]
        for value in ({1: "a"}, {None: 1}, {"\ud800": 1}, {"\udc00": 1}, (1, 2), b"x", {"a": {1.5}}, deep):
            with self.subTest(value=type(value).__name__):
                with self.assertRaises(chain.ChainError):
                    chain.canonical(value)

    def test_row_id_that_is_not_a_string_names_the_line(self):
        row = build_chain([{"n": 1}])[0]
        row["row_id"] = 7
        out = chain.verify_bytes(jsonl([row]))
        self.assertEqual((out["valid"], out["broken_row"], out["line"]), (False, "line:1", 1))


class Usage(unittest.TestCase):
    def test_bad_arguments(self):
        for args in ([], ["hash", "extra"], ["verify"], ["verify", "a", "--prev", "b"], ["sign"]):
            with self.subTest(args=args):
                code, out, _ = run_chain(args)
                self.assertEqual(code, 2)
                self.assertEqual(out, {"error": "usage"})


if __name__ == "__main__":
    unittest.main()
