"""Test 13 (asama-0/09): the chain.

The seed vectors V1-V3 of tohum/29a, an edited row of any kind, a deleted, swapped or repeated row, a rewrite
that recomputes every hash and a file that lost its tail are all caught, and an honest append is not refused.
Run from referee/:  python -m unittest discover -s tests
"""

import json
import os
import random
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from ledger import chain

REFEREE = Path(__file__).resolve().parents[1]
ZERO = "0" * 64
V1_HASH = "3bae91580aca99362572e9f5f41b3e46c2bc0c29236f72e867faa5cd46ca603a"
V2_HASH = "3b10a5bb06351b0933c0e30f7dd55d3a57245743b97fb1faba348351a554a45c"

# RFC 8785 appendix B: IEEE 754 bits -> the text a conforming serializer prints.
RFC_NUMBERS = [
    ("0000000000000000", "0"), ("8000000000000000", "0"), ("0000000000000001", "5e-324"),
    ("8000000000000001", "-5e-324"), ("7fefffffffffffff", "1.7976931348623157e+308"),
    ("ffefffffffffffff", "-1.7976931348623157e+308"), ("4340000000000000", "9007199254740992"),
    ("c340000000000000", "-9007199254740992"), ("4430000000000000", "295147905179352830000"),
    ("44b52d02c7e14af5", "9.999999999999997e+22"), ("44b52d02c7e14af6", "1e+23"),
    ("44b52d02c7e14af7", "1.0000000000000001e+23"), ("444b1ae4d6e2ef4e", "999999999999999700000"),
    ("444b1ae4d6e2ef4f", "999999999999999900000"), ("444b1ae4d6e2ef50", "1e+21"),
    ("3eb0c6f7a0b5ed8c", "9.999999999999997e-7"), ("3eb0c6f7a0b5ed8d", "0.000001"),
    ("41b3de4355555553", "333333333.3333332"), ("41b3de4355555554", "333333333.33333325"),
    ("41b3de4355555555", "333333333.3333333"), ("41b3de4355555556", "333333333.3333334"),
    ("41b3de4355555557", "333333333.33333343"), ("becbf647612f3696", "-0.0000033333333333333333"),
    ("43143ff3c1cb0959", "1424953923781206.2"),
]


def v1_fields():
    return {"row_id": "r1", "ts": "2026-10-28T00:00:00Z", "part": "events", "kind": "genesis", "payload": {},
            "derivation": "tool", "trust": "verified", "snapshot_id": "s0", "evidence_refs": []}


def v2_fields():
    return {"row_id": "r2", "ts": "2026-10-28T00:00:01Z", "part": "cost", "kind": "run",
            "payload": {"usd_micros": 0}, "derivation": "tool", "trust": "observed", "snapshot_id": "s0",
            "evidence_refs": []}


def run_cli(*args, stdin=b""):
    proc = subprocess.run([sys.executable, "-m", "ledger.chain", *args], cwd=REFEREE, input=stdin,
                          capture_output=True, check=False)
    return proc.returncode, proc.stdout.decode("utf-8"), proc.stderr.decode("utf-8")


class Files(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def path(self, name):
        return str(self.dir / name)

    def chain_file(self, name, count):
        """A chain written by the writer itself."""
        path = self.path(name)
        for number in range(1, count + 1):
            chain.append_row(path, {"row_id": f"r{number}", "ts": f"2026-10-28T00:00:{number:02d}Z",
                                    "part": "events", "kind": "run", "payload": {"n": number, "usd_micros": number * 10},
                                    "derivation": "tool", "trust": "observed", "snapshot_id": "s0",
                                    "evidence_refs": []})
        return path

    def rows(self, path):
        return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines()]

    def write(self, path, rows):
        Path(path).write_bytes(b"".join(chain.canonical(row) + b"\n" for row in rows))
        return path

    def forged(self, rows, start):
        """What a forger does after editing row `start`: recompute every hash from there on."""
        out = [dict(row) for row in rows]
        for index in range(start, len(out)):
            out[index]["prev_hash"] = out[index - 1]["row_hash"] if index else ZERO
            out[index]["row_hash"] = chain.row_hash(out[index])
        return out

    def assertBroken(self, result, row_id):
        self.assertIs(result["valid"], False, result)
        self.assertEqual(result["broken_row"], row_id, result)


class CanonicalFormTest(unittest.TestCase):
    def test_rfc8785_number_table(self):
        for bits, text in RFC_NUMBERS:
            value = struct.unpack(">d", bytes.fromhex(bits))[0]
            self.assertEqual(chain.canonical(value).decode(), text, bits)

    def test_integers_are_printed_as_the_double_they_are(self):
        for value, text in [(0, "0"), (1, "1"), (-7, "-7"), (2 ** 53, "9007199254740992"), (10 ** 21, "1e+21"),
                            (10 ** 20, "100000000000000000000"), (1.0, "1"), (-0.0, "0"), (1.5, "1.5")]:
            self.assertEqual(chain.canonical(value).decode(), text, value)

    def test_what_a_double_cannot_hold_is_refused(self):
        for value in (2 ** 53 + 1, -(2 ** 53 + 1), 10 ** 400, float("nan"), float("inf"), float("-inf")):
            with self.assertRaises(chain.ChainError, msg=str(value)[:30]):
                chain.canonical(value)

    def test_true_is_not_one(self):
        self.assertEqual(chain.canonical({"a": True, "b": 1, "c": False, "d": 0, "e": None}),
                         b'{"a":true,"b":1,"c":false,"d":0,"e":null}')

    def test_keys_sort_by_utf16_code_unit_not_by_code_point(self):
        keys = ["€", "\r", "דּ", "1", "\U0001F600", "\u0080", "ö"]
        expected = ["\r", "1", "\u0080", "ö", "€", "\U0001F600", "דּ"]
        self.assertNotEqual(sorted(keys), expected, "the example must tell the two orders apart")
        text = chain.canonical({key: 0 for key in keys}).decode("utf-8")
        self.assertEqual(json.loads(text, object_pairs_hook=lambda pairs: [k for k, _ in pairs]), expected)

    def test_output_has_no_whitespace_and_keeps_array_order(self):
        value = {"c": [3, 1, 2], "a": {"z": 1, "y": [None, {"b": "x"}]}}
        self.assertEqual(chain.canonical(value), b'{"a":{"y":[null,{"b":"x"}],"z":1},"c":[3,1,2]}')

    def test_strings_use_the_shortest_escapes_and_nothing_else(self):
        self.assertEqual(chain.canonical("\b\t\n\f\r").decode(), '"\\b\\t\\n\\f\\r"')
        self.assertEqual(chain.canonical('"\\/').decode(), '"\\"\\\\/"')
        self.assertEqual(chain.canonical("\x00\x0b\x1f").decode(), '"\\u0000\\u000b\\u001f"')
        self.assertEqual(chain.canonical("\x7fé€\U0001F600").decode("utf-8"), '"\x7fé€\U0001F600"')

    def test_every_character_survives_a_round_trip_without_raw_control_characters(self):
        for code in list(range(0x300)) + [0x20ac, 0xd7ff, 0xe000, 0xfb33, 0xffff, 0x1f600, 0x10ffff]:
            char = chr(code)
            out = chain.canonical(char)
            self.assertEqual(json.loads(out.decode("utf-8")), char, hex(code))
            self.assertFalse(any(byte < 0x20 for byte in out), hex(code))

    def test_a_lone_surrogate_is_refused_as_value_and_as_key(self):
        with self.assertRaises(chain.ChainError):
            chain.canonical("\ud800")
        with self.assertRaises(chain.ChainError):
            chain.canonical({"\udc00": 1})

    def test_values_json_does_not_have_are_refused(self):
        for value in ({1: "a"}, b"bytes", {1, 2}, (1, 2), object()):
            with self.assertRaises(chain.ChainError, msg=repr(value)):
                chain.canonical(value)

    def test_absurd_nesting_is_refused_not_a_crash(self):
        deep = []
        for _ in range(5000):
            deep = [deep]
        with self.assertRaises(chain.ChainError):
            chain.canonical(deep)


class RowHashTest(unittest.TestCase):
    def test_seed_vectors_v1_and_v2(self):
        first = dict(v1_fields(), prev_hash=ZERO)
        self.assertEqual(chain.row_hash(first), V1_HASH)
        second = dict(v2_fields(), prev_hash=V1_HASH)
        self.assertEqual(chain.row_hash(second), V2_HASH)

    def test_the_stored_row_hash_is_not_part_of_the_hash(self):
        row = dict(v1_fields(), prev_hash=ZERO)
        self.assertEqual(chain.row_hash(dict(row, row_hash="garbage")), V1_HASH)

    def test_key_order_does_not_matter(self):
        row = dict(v2_fields(), prev_hash=V1_HASH)
        reordered = dict(reversed(list(row.items())))
        self.assertEqual(chain.row_hash(reordered), V2_HASH)

    def test_every_field_and_the_previous_hash_change_the_hash(self):
        row = dict(v2_fields(), prev_hash=V1_HASH)
        for key in row:
            other = dict(row)
            other[key] = "1" * 64 if key == "prev_hash" else {"x": 1}
            self.assertNotEqual(chain.row_hash(other), V2_HASH, key)
        self.assertNotEqual(chain.row_hash(dict(row, extra=1)), V2_HASH)
        smaller = {k: v for k, v in row.items() if k != "snapshot_id"}
        self.assertNotEqual(chain.row_hash(smaller), V2_HASH)

    def test_prev_hash_is_hashed_a_second_time_as_ascii_text(self):
        """sha256(canonical(row) || prev_hash): the same row under two previous hashes must differ even if the
        canonical body would be equal, so the suffix is real and not only the copy inside the body."""
        import hashlib
        row = dict(v1_fields(), prev_hash=ZERO)
        body = chain.canonical(row)
        self.assertEqual(chain.row_hash(row), hashlib.sha256(body + ZERO.encode("ascii")).hexdigest())
        self.assertNotEqual(chain.row_hash(row), hashlib.sha256(body).hexdigest())

    def test_a_bad_previous_hash_is_refused(self):
        row = v1_fields()
        for bad in (None, "", "0" * 63, "0" * 65, "A" * 64, "g" * 64, 0):
            with self.assertRaises(chain.ChainError, msg=repr(bad)):
                chain.row_hash(dict(row, prev_hash=bad))
        with self.assertRaises(chain.ChainError):
            chain.row_hash(row)
        with self.assertRaises(chain.ChainError):
            chain.row_hash([1])


class VerifyTest(Files):
    def test_a_written_chain_is_valid(self):
        result = chain.check_file(self.chain_file("a.jsonl", 6))
        self.assertEqual(result, {"valid": True, "broken_row": None, "rows": 6})

    def test_an_empty_file_is_a_valid_empty_chain(self):
        Path(self.path("e.jsonl")).write_bytes(b"")
        self.assertEqual(chain.check_file(self.path("e.jsonl"))["valid"], True)

    def test_vector_v3_an_edited_payload_without_a_new_hash_breaks_r2_and_leaves_r1(self):
        first = dict(v1_fields(), prev_hash=ZERO, row_hash=V1_HASH)
        second = dict(v2_fields(), prev_hash=V1_HASH, row_hash=V2_HASH)
        self.assertEqual(chain.check_file(self.write(self.path("ok.jsonl"), [first, second]))["valid"], True)
        self.assertEqual(chain.check_file(self.write(self.path("r1.jsonl"), [first]))["valid"], True)
        second["payload"] = {"usd_micros": 1}
        self.assertBroken(chain.check_file(self.write(self.path("v3.jsonl"), [first, second])), "r2")

    def test_any_edit_of_any_field_of_any_row_is_caught_at_that_row(self):
        rows = self.rows(self.chain_file("good.jsonl", 5))
        edits = {"payload": {"n": -1}, "ts": "2030-01-01T00:00:00Z", "kind": "x", "part": "x", "trust": "verified",
                 "snapshot_id": "s9", "derivation": "agent", "evidence_refs": ["e"], "row_hash": "f" * 64,
                 "prev_hash": "f" * 64}
        for index in range(len(rows)):
            for key, value in edits.items():
                edited = [dict(row) for row in rows]
                edited[index][key] = value
                result = chain.check_file(self.write(self.path("edit.jsonl"), edited))
                self.assertBroken(result, rows[index]["row_id"])
            added = [dict(row) for row in rows]
            added[index]["extra"] = 1
            self.assertBroken(chain.check_file(self.write(self.path("add.jsonl"), added)), rows[index]["row_id"])
            removed = [dict(row) for row in rows]
            del removed[index]["trust"]
            self.assertBroken(chain.check_file(self.write(self.path("del.jsonl"), removed)), rows[index]["row_id"])

    def test_a_changed_row_id_is_caught_under_the_new_name(self):
        rows = self.rows(self.chain_file("good.jsonl", 3))
        rows[1]["row_id"] = "renamed"
        self.assertBroken(chain.check_file(self.write(self.path("x.jsonl"), rows)), "renamed")

    def test_a_deleted_swapped_or_repeated_row_is_caught(self):
        rows = self.rows(self.chain_file("good.jsonl", 5))
        self.assertBroken(chain.check_file(self.write(self.path("a.jsonl"), rows[:2] + rows[3:])), "r4")
        self.assertBroken(chain.check_file(self.write(self.path("b.jsonl"), rows[1:])), "r2")
        self.assertBroken(chain.check_file(self.write(self.path("c.jsonl"), rows[:1] + [rows[2], rows[1]] + rows[3:])), "r3")
        self.assertBroken(chain.check_file(self.write(self.path("d.jsonl"), rows[:3] + [rows[2]] + rows[3:])), "r3")

    def test_a_row_id_used_twice_is_caught_even_when_the_hashes_agree(self):
        rows = self.rows(self.chain_file("good.jsonl", 3))
        rows[2]["row_id"] = "r1"
        rows = self.forged(rows, 2)
        self.assertBroken(chain.check_file(self.write(self.path("x.jsonl"), rows)), "r1")

    def test_a_forged_tail_that_names_the_wrong_previous_row_is_caught(self):
        rows = self.rows(self.chain_file("good.jsonl", 3))
        rows[2]["prev_hash"] = ZERO
        rows[2]["row_hash"] = chain.row_hash(rows[2])
        self.assertBroken(chain.check_file(self.write(self.path("x.jsonl"), rows)), "r3")

    def test_a_second_row_that_claims_to_be_first_is_caught(self):
        rows = self.rows(self.chain_file("good.jsonl", 2))
        rows[0]["prev_hash"] = V1_HASH
        self.assertBroken(chain.check_file(self.write(self.path("x.jsonl"), rows)), "r1")

    def test_lines_that_are_not_rows_are_named_by_line(self):
        good = self.chain_file("good.jsonl", 3)
        text = Path(good).read_text(encoding="utf-8").splitlines()
        cases = {
            "garbage": text[:2] + ["{not json"] + text[2:],
            "blank": text[:2] + [""] + text[2:],
            "array": text[:2] + ["[1,2]"] + text[2:],
            "duplicate key": text[:2] + ['{"row_id":"a","row_id":"b"}'] + text[2:],
            "nan": text[:2] + ['{"row_id":"a","x":NaN}'] + text[2:],
        }
        for name, lines in cases.items():
            Path(self.path("x.jsonl")).write_text("\n".join(lines) + "\n", encoding="utf-8")
            self.assertBroken(chain.check_file(self.path("x.jsonl")), "line:3")
        Path(self.path("u.jsonl")).write_bytes(b"\xff\xfe\n")
        self.assertBroken(chain.check_file(self.path("u.jsonl")), "line:1")

    def test_a_line_nested_too_deeply_for_the_parser_is_a_broken_line_not_a_crash(self):
        """Found by the rival in the second rehearsal: json.loads raises RecursionError, not ValueError."""
        good = self.chain_file("good.jsonl", 2)
        text = Path(good).read_text(encoding="utf-8") + "[" * 200000 + "\n"
        Path(self.path("deep.jsonl")).write_text(text, encoding="utf-8")
        self.assertBroken(chain.check_file(self.path("deep.jsonl")), "line:3")
        self.assertBroken(chain.check_file(good, self.path("deep.jsonl")), "line:3")

    def test_a_row_without_a_usable_id_is_named_by_line(self):
        rows = self.rows(self.chain_file("good.jsonl", 3))
        for bad in (None, "", 7):
            edited = [dict(row) for row in rows]
            edited[1]["row_id"] = bad
            self.assertBroken(chain.check_file(self.write(self.path("x.jsonl"), edited)), "line:2")

    def test_the_first_problem_in_the_file_wins_over_a_later_unreadable_line(self):
        rows = self.rows(self.chain_file("good.jsonl", 4))
        rows[1]["payload"] = {"n": 99}
        text = Path(self.write(self.path("x.jsonl"), rows)).read_text(encoding="utf-8") + "{broken\n"
        Path(self.path("x.jsonl")).write_text(text, encoding="utf-8")
        self.assertBroken(chain.check_file(self.path("x.jsonl")), "r2")

    def test_cutting_the_tail_is_invisible_without_the_earlier_file(self):
        rows = self.rows(self.chain_file("good.jsonl", 4))
        self.assertEqual(chain.check_file(self.write(self.path("cut.jsonl"), rows[:2]))["valid"], True)

    def test_a_missing_file_is_an_error_not_a_verdict(self):
        with self.assertRaises(OSError):
            chain.check_file(self.path("absent.jsonl"))


class AppendOnlyTest(Files):
    def test_a_file_that_only_grew_is_fine(self):
        before = self.chain_file("a.jsonl", 3)
        copy = self.write(self.path("before.jsonl"), self.rows(before))
        chain.append_row(before, {"row_id": "r4", "ts": "t", "part": "events", "kind": "run", "payload": {},
                                  "derivation": "tool", "trust": "observed", "snapshot_id": "s0", "evidence_refs": []})
        self.assertEqual(chain.check_file(before, copy), {"valid": True, "broken_row": None, "rows": 4})
        self.assertEqual(chain.check_file(copy, copy)["valid"], True)

    def test_anything_may_follow_an_empty_earlier_file(self):
        Path(self.path("empty.jsonl")).write_bytes(b"")
        self.assertEqual(chain.check_file(self.chain_file("a.jsonl", 2), self.path("empty.jsonl"))["valid"], True)

    def test_a_rewrite_that_recomputes_every_hash_is_a_valid_chain_and_still_refused(self):
        earlier = self.chain_file("earlier.jsonl", 5)
        rows = self.rows(earlier)
        rows[1]["payload"] = {"n": 2, "usd_micros": 1}
        forged = self.write(self.path("forged.jsonl"), self.forged(rows, 1))
        self.assertEqual(chain.check_file(forged)["valid"], True, "the forgery is internally consistent")
        self.assertBroken(chain.check_file(forged, earlier), "r2")

    def test_rewriting_the_last_row_or_the_first_is_refused(self):
        earlier = self.chain_file("earlier.jsonl", 4)
        for index in (0, 3):
            rows = self.rows(earlier)
            rows[index]["kind"] = "other"
            forged = self.write(self.path(f"forged{index}.jsonl"), self.forged(rows, index))
            self.assertBroken(chain.check_file(forged, earlier), f"r{index + 1}")

    def test_losing_rows_is_refused_and_names_the_first_lost_row(self):
        earlier = self.chain_file("earlier.jsonl", 5)
        rows = self.rows(earlier)
        self.assertBroken(chain.check_file(self.write(self.path("a.jsonl"), rows[:3]), earlier), "r4")
        self.assertBroken(chain.check_file(self.write(self.path("b.jsonl"), []), earlier), "r1")

    def test_a_row_inserted_in_the_middle_is_refused(self):
        earlier = self.chain_file("earlier.jsonl", 3)
        rows = self.rows(earlier)
        extra = {"row_id": "rx", "ts": "t", "part": "events", "kind": "run", "payload": {}, "derivation": "tool",
                 "trust": "observed", "snapshot_id": "s0", "evidence_refs": []}
        forged = self.forged(rows[:1] + [extra] + rows[1:], 1)
        self.assertBroken(chain.check_file(self.write(self.path("f.jsonl"), forged), earlier), "r2")

    def test_true_and_one_are_different_rows(self):
        rows = self.rows(self.chain_file("a.jsonl", 2))
        rows[0]["payload"] = {"flag": 1}
        rows = self.forged(rows, 0)
        earlier = self.write(self.path("earlier.jsonl"), rows)
        rows[0]["payload"] = {"flag": True}
        rows = self.forged(rows, 0)
        self.assertBroken(chain.check_file(self.write(self.path("later.jsonl"), rows), earlier), "r1")

    def test_a_broken_earlier_file_is_reported_as_such(self):
        earlier = self.chain_file("earlier.jsonl", 3)
        rows = self.rows(earlier)
        rows[1]["payload"] = {"n": 0}
        broken = self.write(self.path("broken.jsonl"), rows)
        result = chain.check_file(self.chain_file("now.jsonl", 3), broken)
        self.assertBroken(result, "r2")
        self.assertIn("previous", result["reason"])

    def test_a_broken_new_file_is_reported_before_the_comparison(self):
        earlier = self.chain_file("earlier.jsonl", 3)
        rows = self.rows(earlier)
        rows[2]["payload"] = {"n": 0}
        self.assertBroken(chain.check_file(self.write(self.path("n.jsonl"), rows), earlier), "r3")


class AppendTest(Files):
    def test_the_first_two_rows_get_the_seed_vector_hashes(self):
        path = self.path("a.jsonl")
        self.assertEqual(chain.append_row(path, v1_fields()), V1_HASH)
        self.assertEqual(chain.append_row(path, v2_fields()), V2_HASH)
        rows = self.rows(path)
        self.assertEqual([r["prev_hash"] for r in rows], [ZERO, V1_HASH])
        self.assertEqual(chain.check_file(path)["valid"], True)

    def test_lines_are_stored_in_canonical_form_one_per_line(self):
        path = self.chain_file("a.jsonl", 3)
        data = Path(path).read_bytes()
        self.assertTrue(data.endswith(b"\n"))
        self.assertEqual(data, b"".join(chain.canonical(row) + b"\n" for row in self.rows(path)))

    def test_the_writer_sets_the_hashes_and_refuses_rows_that_bring_their_own(self):
        path = self.path("a.jsonl")
        for extra in ({"prev_hash": ZERO}, {"row_hash": V1_HASH}):
            with self.assertRaises(chain.ChainError):
                chain.append_row(path, dict(v1_fields(), **extra))
        self.assertFalse(os.path.exists(path))

    def test_rows_without_an_id_or_with_a_used_id_or_not_objects_are_refused(self):
        path = self.chain_file("a.jsonl", 2)
        before = Path(path).read_bytes()
        for bad in ({"ts": "t"}, {"row_id": ""}, {"row_id": 5}, dict(v1_fields(), row_id="r2"), [1], "x", None):
            with self.assertRaises(chain.ChainError, msg=repr(bad)[:40]):
                chain.append_row(path, bad)
        self.assertEqual(Path(path).read_bytes(), before)

    def test_a_row_that_cannot_be_hashed_leaves_the_file_alone(self):
        path = self.chain_file("a.jsonl", 2)
        before = Path(path).read_bytes()
        with self.assertRaises(chain.ChainError):
            chain.append_row(path, dict(v1_fields(), row_id="rz", payload={"n": float("nan")}))
        self.assertEqual(Path(path).read_bytes(), before)

    def test_a_broken_chain_is_never_extended(self):
        rows = self.rows(self.chain_file("a.jsonl", 3))
        rows[1]["payload"] = {"n": 0}
        broken = self.write(self.path("broken.jsonl"), rows)
        before = Path(broken).read_bytes()
        with self.assertRaises(chain.ChainError):
            chain.append_row(broken, dict(v1_fields(), row_id="r9"))
        self.assertEqual(Path(broken).read_bytes(), before)

    def test_a_file_cut_in_the_middle_of_a_line_is_never_extended(self):
        path = self.chain_file("a.jsonl", 2)
        data = Path(path).read_bytes()
        Path(path).write_bytes(data.rstrip(b"\n"))
        with self.assertRaises(chain.ChainError):
            chain.append_row(path, dict(v1_fields(), row_id="r9"))
        self.assertEqual(Path(path).read_bytes(), data.rstrip(b"\n"))

    def test_appending_keeps_every_earlier_byte(self):
        path = self.chain_file("a.jsonl", 3)
        before = Path(path).read_bytes()
        chain.append_row(path, dict(v1_fields(), row_id="r4"))
        self.assertTrue(Path(path).read_bytes().startswith(before))


class CommandLineTest(Files):
    def one_json_line(self, text):
        self.assertTrue(text.endswith("\n") and text.count("\n") == 1, repr(text))
        return json.loads(text)

    def test_hash_reads_one_row_from_stdin_and_answers_one_json_line(self):
        row = dict(v1_fields(), prev_hash=ZERO)
        code, out, _ = run_cli("hash", stdin=json.dumps(row).encode())
        self.assertEqual((code, self.one_json_line(out)), (0, {"row_hash": V1_HASH}))
        code, out, _ = run_cli("hash", stdin=json.dumps(dict(row, row_id="r1x")).encode())
        self.assertEqual(code, 0)
        self.assertNotEqual(self.one_json_line(out)["row_hash"], V1_HASH)

    def test_hash_of_input_it_cannot_use_is_exit_2_with_an_error_and_no_traceback(self):
        for stdin in (b"", b"not json", b'{"a":1}\n{"b":2}', b"[1]", b'{"prev_hash":"x"}', b"\xff", b"[" * 200000):
            code, out, err = run_cli("hash", stdin=stdin)
            self.assertEqual(code, 2, stdin[:20])
            self.assertIn("error", self.one_json_line(out))
            self.assertNotIn("Traceback", err)

    def test_a_deeply_nested_file_or_row_keeps_the_one_json_line_contract(self):
        deep = self.path("deep.jsonl")
        Path(deep).write_text("[" * 200000 + "\n", encoding="utf-8")
        code, out, err = run_cli("verify", deep)
        self.assertEqual((code, self.one_json_line(out)["broken_row"]), (1, "line:1"))
        self.assertNotIn("Traceback", err)
        code, out, err = run_cli("append", self.path("a.jsonl"), stdin=b'{"row_id":"r1","x":' + b"[" * 200000)
        self.assertEqual(code, 2)
        self.assertIn("error", self.one_json_line(out))
        self.assertNotIn("Traceback", err)
        self.assertFalse(os.path.exists(self.path("a.jsonl")))

    def test_verify_answers_by_exit_code_and_by_json(self):
        good = self.chain_file("good.jsonl", 3)
        code, out, _ = run_cli("verify", good)
        self.assertEqual((code, self.one_json_line(out)["valid"]), (0, True))
        rows = self.rows(good)
        rows[1]["payload"] = {"n": 0}
        bad = self.write(self.path("bad.jsonl"), rows)
        code, out, _ = run_cli("verify", bad)
        answer = self.one_json_line(out)
        self.assertEqual((code, answer["valid"], answer["broken_row"]), (1, False, "r2"))

    def test_verify_with_the_earlier_file_catches_the_rewrite(self):
        earlier = self.chain_file("earlier.jsonl", 4)
        rows = self.rows(earlier)
        rows[2]["kind"] = "edited"
        forged = self.write(self.path("forged.jsonl"), self.forged(rows, 2))
        self.assertEqual(run_cli("verify", forged)[0], 0)
        code, out, _ = run_cli("verify", forged, "--previous", earlier)
        self.assertEqual((code, self.one_json_line(out)["broken_row"]), (1, "r3"))
        code, out, _ = run_cli("verify", earlier, "--previous", earlier)
        self.assertEqual((code, self.one_json_line(out)["valid"]), (0, True))

    def test_a_missing_file_is_exit_2(self):
        code, out, _ = run_cli("verify", self.path("absent.jsonl"))
        self.assertEqual(code, 2)
        self.assertIn("error", self.one_json_line(out))
        good = self.chain_file("good.jsonl", 1)
        self.assertEqual(run_cli("verify", good, "--previous", self.path("absent.jsonl"))[0], 2)

    def test_append_through_the_command_line(self):
        path = self.path("a.jsonl")
        code, out, _ = run_cli("append", path, stdin=json.dumps(v1_fields()).encode())
        self.assertEqual((code, self.one_json_line(out)), (0, {"row_hash": V1_HASH}))
        code, out, _ = run_cli("append", path, stdin=json.dumps(dict(v1_fields(), prev_hash=ZERO)).encode())
        self.assertEqual(code, 2)
        self.assertEqual(run_cli("verify", path)[0], 0)

    def test_an_unknown_command_is_refused(self):
        self.assertEqual(run_cli("rewrite")[0], 2)
        self.assertEqual(run_cli()[0], 2)


class RandomisedTest(Files):
    """Seeded, so a failure repeats. Random rows, one random edit, and the edit is always found."""

    LEAVES = [0, 1, -3, 2.5, 1e-7, 1e21, True, False, None, "", "x", "é€", "\U0001F600", "\n", []]

    def row(self, rng, number):
        keys = ["a", "é", "\U0001F600", "דּ", "z", "1", "\r"]
        payload = {rng.choice(keys): rng.choice(self.LEAVES) for _ in range(rng.randint(0, 5))}
        payload["nested"] = {"k": [rng.choice(self.LEAVES) for _ in range(rng.randint(0, 3))]}
        return {"row_id": f"r{number}", "ts": "2026-10-28T00:00:00Z", "part": rng.choice(["events", "cost"]),
                "kind": "run", "payload": payload, "derivation": "tool", "trust": "observed",
                "snapshot_id": "s0", "evidence_refs": []}

    def changed(self, rng, value):
        if value is True or value is False:
            return not value
        if isinstance(value, int):
            return value + 1
        if isinstance(value, float):
            return value + 1.5
        if isinstance(value, str):
            return value + "x"
        if isinstance(value, list):
            return value + [0]
        if isinstance(value, dict):
            return dict(value, zz=1)
        return 0

    def test_a_random_edit_of_a_random_row_is_found_and_so_is_its_consistent_rewrite(self):
        rng = random.Random(8785)
        for round_number in range(80):
            fresh = [self.row(rng, number) for number in range(1, rng.randint(1, 10) + 1)]
            rows = self.forged(fresh, 0)
            path = self.write(self.path("c.jsonl"), rows)
            self.assertEqual(chain.check_file(path)["valid"], True, round_number)
            if round_number < 5:  # the writer builds the same bytes (it fsyncs every row, so only a few rounds)
                written = self.path("w.jsonl")
                if os.path.exists(written):
                    os.unlink(written)
                for row in fresh:
                    chain.append_row(written, row)
                self.assertEqual(Path(written).read_bytes(), Path(path).read_bytes())
            index = rng.randrange(len(rows))
            key = rng.choice([k for k in rows[index] if k not in ("row_id", "prev_hash", "row_hash")])
            edited = [dict(row) for row in rows]
            edited[index][key] = self.changed(rng, edited[index][key])
            self.assertBroken(chain.check_file(self.write(self.path("e.jsonl"), edited)), rows[index]["row_id"])
            forged = self.write(self.path("f.jsonl"), self.forged(edited, index))
            self.assertEqual(chain.check_file(forged)["valid"], True)
            self.assertBroken(chain.check_file(forged, path), rows[index]["row_id"])


if __name__ == "__main__":
    unittest.main()
