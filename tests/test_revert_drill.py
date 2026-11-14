"""Test 50 (asama-0/09) and group ``revert_drill`` (tohum/29m): the revert drill, ``exit.drill`` revert only.

- the key: ``selection = HMAC-SHA256(seed's UTF-8 bytes, cycle_id)`` checked against RFC 4231 test case 6 and a
  hand-built HMAC; the instance index over the catalog sorted by id in code point order (file order irrelevant,
  every instance reachable, the whole 256-bit selection used); the key's exact fields; every malformed catalog,
  seed and cycle_id unusable; fields the group does not read are ignored;
- the commitment: ``sha256`` of the RFC 8785 form, key order irrelevant; the commit payload holds no key field;
- the judge over chained ledgers written by ``ledger.append``: PASS; each reason of steps (3)-(5) alone and all
  at once; a broken chain alone (an edited row, a line that is not an object); not planted; only the last plant,
  the last commitment before it and the first revert of its merge after it are read; a malformed key unusable;
- the run on the in-process GitHub: the committed instance is planted, merged and reverted to the first parent's
  tree, the judge then passes on the appended rows for each cause; a wrong observed cause, a green watch, no or a
  spent or another cycle's commitment, an edited ledger and unusable inputs write nothing or fail as stated;
- the command line on the seed's vector inputs' shapes: outputs and exits 0/1/2.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest

REFEREE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REFEREE)

from harness import revert_drill as D  # noqa: E402
from ledger import append, chain  # noqa: E402
from target import write as W  # noqa: E402
from test_write import GATE, world  # noqa: E402

SEED = {"seed": "test-drill-seed-ç"}
SEED_BYTES = "test-drill-seed-ç".encode("utf-8")
CATALOG = {"instances": [
    {"id": "lint-rise", "cause": "lint_regression", "patch": "lint.patch"},
    {"id": "broken-build", "cause": "build_break"},
    {"id": "failing-test", "cause": "test_regression"},
]}
IDS = sorted(i["id"] for i in CATALOG["instances"])
CAUSE = {i["id"]: i["cause"] for i in CATALOG["instances"]}
FILES = {"lint-rise": {"src/a.js": "var x = 1\n"}, "broken-build": {"src/a.js": "export const = ;\n"},
         "failing-test": {"src/a.js": "export const a = 2;\n"}}
TS = "2026-10-30T00:00:00Z"
M1, M2 = "1" * 40, "2" * 40


def hand_hmac(seed: bytes, message: bytes) -> str:
    """RFC 2104 written out, a second computation beside ``hmac``."""
    block = 64
    k = hashlib.sha256(seed).digest() if len(seed) > block else seed
    k = k.ljust(block, b"\0")
    inner = hashlib.sha256(bytes(b ^ 0x36 for b in k) + message).digest()
    return hashlib.sha256(bytes(b ^ 0x5C for b in k) + inner).hexdigest()


def hand_key(cycle_id: str, seed: bytes = SEED_BYTES, ids=IDS) -> dict:
    chosen = hand_hmac(seed, cycle_id.encode())
    instance = ids[int(chosen, 16) % len(ids)]
    return {"cycle_id": cycle_id, "selection": chosen, "instance_id": instance, "cause": CAUSE[instance]}


def cycle_choosing(instance_id: str) -> str:
    for n in range(41000000000, 41000001000):
        if hand_key(str(n))["instance_id"] == instance_id:
            return str(n)
    raise AssertionError("no cycle chooses " + instance_id)


def row(row_id: str, part: str, kind: str, payload: dict, cause: str | None = None) -> dict:
    out = {"row_id": row_id, "ts": TS, "part": part, "kind": kind, "payload": payload, "derivation": "tool",
           "trust": "verified", "snapshot_id": "s0", "evidence_refs": []}
    if cause is not None:
        out["cause"] = cause
    return out


def commit(row_id: str, key: dict) -> dict:
    return row(row_id, "drill", "commit", D.commit_payload(key))


def plant(row_id: str, instance_id: str, merge: str) -> dict:
    return row(row_id, "drill", "plant", D.plant_payload(instance_id, merge))


def reverted(row_id: str, merge: str, cause: str) -> dict:
    return row(row_id, "events", "revert", D.revert_payload(merge), cause)


def ledger_with(rows: list[dict], ledger: bytes = b"") -> bytes:
    """Rows chained onto ``ledger`` by ``ledger.append``, the way the cycle writes them."""
    request = json.dumps({"rows": rows}).encode()
    return append.plan_cycle(ledger, ledger, lambda: request).content


def cli(stdin: bytes, *argv: str):
    proc = subprocess.run([sys.executable, "-m", "harness.revert_drill", *argv], cwd=REFEREE, input=stdin,
                          capture_output=True, timeout=60)
    lines = proc.stdout.decode().splitlines()
    return proc.returncode, (json.loads(lines[0]) if len(lines) == 1 else lines), proc.stderr.decode()


class Key(unittest.TestCase):
    def test_rfc4231_case_6(self):
        seed = b"\xaa" * 131
        message = "Test Using Larger Than Block-Size Key - Hash Key First"
        want = "60e431591ee0b67f0d8a26aacbf5b77f8e0bc6213728c5140546040f0ee37f54"
        self.assertEqual(hand_hmac(seed, message.encode()), want)
        # selection takes a decimal cycle id; the same HMAC over digits
        self.assertEqual(D.selection(seed, "41"), hand_hmac(seed, b"41"))

    def test_key(self):
        for n in ("0", "7", "41000000018", "1" * 30):
            self.assertEqual(D.key(SEED, n, CATALOG), hand_key(n))

    def test_seed_is_its_utf8_bytes_and_cycle_the_message(self):
        n = "41000000018"
        self.assertEqual(D.key(SEED, n, CATALOG)["selection"], hand_hmac(SEED_BYTES, n.encode()))
        self.assertNotEqual(D.key(SEED, n, CATALOG)["selection"], hand_hmac(n.encode(), SEED_BYTES))
        self.assertNotEqual(D.key(SEED, n, CATALOG)["selection"], hand_hmac("test-drill-seed-ç".encode(
            "latin-1"), n.encode()))

    def test_file_order_does_not_matter(self):
        rotated = {"instances": CATALOG["instances"][1:] + CATALOG["instances"][:1]}
        for n in map(str, range(30)):
            self.assertEqual(D.key(SEED, n, CATALOG), D.key(SEED, n, rotated))
            self.assertEqual(D.key(SEED, n, CATALOG), D.key(SEED, n, {"instances": CATALOG["instances"][::-1]}))

    def test_sorted_by_code_point(self):
        catalog = {"instances": [{"id": "b", "cause": "x"}, {"id": "B", "cause": "y"}, {"id": "ä", "cause": "z"},
                                 {"id": "a", "cause": "w"}]}
        for n in map(str, range(40)):
            want = ["B", "a", "b", "ä"][int(hand_hmac(SEED_BYTES, n.encode()), 16) % 4]
            self.assertEqual(D.key(SEED, n, catalog)["instance_id"], want)

    def test_whole_selection_is_the_number(self):
        # a cycle where the low byte, the high byte, the low or high 32 or 64 bits each pick another instance
        for n in map(str, range(41000000000, 41000002000)):
            s = hand_hmac(SEED_BYTES, n.encode())
            whole = int(s, 16) % 3
            parts = [int(s[-2:], 16), int(s[:2], 16), int(s[-8:], 16), int(s[:8], 16), int(s[:16], 16),
                     int(s[-16:], 16)]
            if all(p % 3 != whole for p in parts):
                self.assertEqual(D.key(SEED, n, CATALOG)["instance_id"], IDS[whole])
                return
        self.fail("no discriminating cycle in range")

    def test_every_instance_reachable_and_the_seed_matters(self):
        self.assertEqual({D.key(SEED, str(n), CATALOG)["instance_id"] for n in range(60)}, set(IDS))
        other = {"seed": "test-drill-seed-d"}
        self.assertNotEqual([D.key(SEED, str(n), CATALOG)["instance_id"] for n in range(30)],
                            [D.key(other, str(n), CATALOG)["instance_id"] for n in range(30)])

    def test_unread_fields_and_any_cause_string(self):
        catalog = {"instances": [{"id": "x", "cause": "", "patch": 1, "files": None}], "note": [1]}
        self.assertEqual(D.key(dict(SEED, extra=1), "1", catalog)["cause"], "")
        self.assertEqual(D.key(SEED, "1", {"instances": [{"id": "x", "cause": "not_a_tohum_cause"}]})["cause"],
                         "not_a_tohum_cause")

    def test_unusable_catalog_seed_cycle(self):
        good = {"id": "x", "cause": "build_break"}
        catalogs = [None, [], {}, {"instances": []}, {"instances": {}}, {"instances": [good, dict(good)]},
                    {"instances": [dict(good, id="")]}, {"instances": [dict(good, id=1)]},
                    {"instances": [{"cause": "c"}]}, {"instances": [{"id": "x"}]},
                    {"instances": [dict(good, cause=None)]}, {"instances": [dict(good, cause=["c"])]},
                    {"instances": ["x"]}]
        for catalog in catalogs:
            with self.assertRaises(D.Unusable, msg=catalog):
                D.key(SEED, "1", catalog)
        for seed in (None, {}, {"seed": ""}, {"seed": 7}, {"seed": None}, ["s"], "s"):
            with self.assertRaises(D.Unusable, msg=seed):
                D.key(seed, "1", CATALOG)
        for n in ("", None, 1, "1a", " 1", "1\n", "-1", "١٢", "1.0", "１"):
            with self.assertRaises(D.Unusable, msg=n):
                D.key(SEED, n, CATALOG)


class Commitment(unittest.TestCase):
    def test_sha256_of_the_canonical_form(self):
        k = D.key(SEED, "7", CATALOG)
        text = '{"cause":"%s","cycle_id":"7","instance_id":"%s","selection":"%s"}' % (
            k["cause"], k["instance_id"], k["selection"])
        self.assertEqual(D.commitment(k), hashlib.sha256(text.encode()).hexdigest())
        self.assertEqual(D.commitment(dict(reversed(list(k.items())))), D.commitment(k))

    def test_commit_payload_holds_only_the_hash(self):
        k = D.key(SEED, "7", CATALOG)
        self.assertEqual(D.commit_payload(k), {"drill": "revert", "family": "revert",
                                               "commitment_sha256": D.commitment(k)})
        text = json.dumps(commit("d1", k))
        for leaked in (k["instance_id"], k["selection"], k["cause"], '"7"'):
            self.assertNotIn(leaked, text)

    def test_rows(self):
        self.assertEqual(D.plant_payload("i", M1), {"drill": "revert", "family": "revert", "instance_id": "i",
                                                    "merge_sha": M1})
        self.assertEqual(D.revert_payload(M1), {"merge_sha": M1})


class Judge(unittest.TestCase):
    def setUp(self):
        self.cycle = cycle_choosing("broken-build")
        self.answer = D.key(SEED, self.cycle, CATALOG)

    def judge(self, rows, key=None):
        return D.judge(ledger_with(rows), key or self.answer)

    def good(self):
        return [commit("c", self.answer), plant("p", "broken-build", M1), reverted("r", M1, "build_break")]

    def test_pass(self):
        self.assertEqual(self.judge(self.good()), {"verdict": "PASS", "reasons": []})

    def test_each_reason_alone(self):
        c, p, r = self.good()
        other = D.key(SEED, cycle_choosing("lint-rise"), CATALOG)
        cases = [
            ([commit("c", other), p, r], ["commitment_mismatch"]),
            ([p, r], ["commitment_not_before_run"]),
            ([p, commit("c", self.answer), r], ["commitment_not_before_run"]),
            ([c, plant("p", "lint-rise", M1), r], ["instance_mismatch"]),
            ([c, p], ["not_reverted"]),
            ([c, p, reverted("r", M2, "build_break")], ["not_reverted"]),
            ([c, reverted("r0", M1, "build_break"), p], ["not_reverted"]),
            ([c, p, reverted("r", M1, "lint_regression")], ["cause_mismatch"]),
            ([c, p, row("r", "events", "revert", {"merge_sha": M1})], ["cause_mismatch"]),
            ([c, p, row("r", "events", "reverted", {"merge_sha": M1}, "build_break")], ["not_reverted"]),
            ([c, p, row("r", "drill", "revert", {"merge_sha": M1}, "build_break")], ["not_reverted"]),
        ]
        for rows, reasons in cases:
            self.assertEqual(self.judge(rows), {"verdict": "FAIL", "reasons": reasons}, rows)

    def test_tampered_key(self):
        # the cause was wrong and the key was edited after the run to match it
        rows = [commit("c", self.answer), plant("p", "broken-build", M1), reverted("r", M1, "lint_regression")]
        self.assertEqual(self.judge(rows, dict(self.answer, cause="lint_regression")),
                         {"verdict": "FAIL", "reasons": ["commitment_mismatch"]})
        for field in ("cycle_id", "selection", "instance_id"):
            got = self.judge(self.good(), dict(self.answer, **{field: self.answer[field] + "0"}))
            self.assertIn("commitment_mismatch", got["reasons"])

    def test_three_reasons_and_a_late_commitment_is_not_compared(self):
        rows = [plant("p", "lint-rise", M1), commit("c", D.key(SEED, "1", CATALOG)), reverted("r", M1, "x")]
        self.assertEqual(self.judge(rows), {"verdict": "FAIL", "reasons": [
            "cause_mismatch", "commitment_not_before_run", "instance_mismatch"]})

    def test_chain_broken_alone(self):
        good = ledger_with(self.good())
        lines = good.splitlines(keepends=True)
        first = json.loads(lines[0])
        first["payload"]["commitment_sha256"] = "0" * 64
        edited = json.dumps(first).encode() + b"\n" + b"".join(lines[1:])
        cut = b"".join(lines[:2]) + b"[]\n" + lines[2]
        for data in (edited, cut, good + b"{\n", good[:-5] + b"\n"):
            self.assertEqual(D.judge(data, self.answer), {"verdict": "FAIL", "reasons": ["chain_broken"]})
        # the stated boundary: the judge takes no seed, so a ledger chained anew around a tampered key passes it;
        # that ledger is not an append-only extension of the verified previous one (ledger.append's check)
        tampered = dict(self.answer, cause="lint_regression")
        rewritten = ledger_with([commit("c", tampered), plant("p", "broken-build", M1),
                                 reverted("r", M1, "lint_regression")])
        self.assertEqual(D.judge(rewritten, tampered), {"verdict": "PASS", "reasons": []})
        self.assertFalse(chain.verify_bytes(rewritten, ledger_with(self.good()[:1]))["valid"])

    def test_not_planted(self):
        lesson = plant("p", "broken-build", M1)
        lesson["payload"] = dict(lesson["payload"], drill="lesson")
        for rows in ([], [commit("c", self.answer)], [commit("c", self.answer), lesson, reverted("r", M1, "build_break")],
                     [row("p", "events", "plant", D.plant_payload("broken-build", M1))],
                     [row("p", "drill", "plant", "not an object")]):
            data = ledger_with(rows) if rows else b""
            self.assertEqual(D.judge(data, self.answer), {"verdict": "FAIL", "reasons": ["not_planted"]}, rows)

    def test_last_of_several_drills(self):
        earlier = D.key(SEED, cycle_choosing("lint-rise"), CATALOG)
        history = [commit("c0", earlier), plant("p0", "lint-rise", M2), reverted("r0", M2, "lint_regression")]
        self.assertEqual(self.judge(history + self.good()), {"verdict": "PASS", "reasons": []})
        # the earlier drill's key is history: judged against the last plant, it fails
        self.assertEqual(self.judge(history + self.good(), earlier)["verdict"], "FAIL")
        # the last commitment before P is read, not the first
        c, p, r = self.good()
        self.assertEqual(self.judge([c, commit("c2", earlier), p, r]),
                         {"verdict": "FAIL", "reasons": ["commitment_mismatch"]})
        # the first revert of P's merge after P is read, not a later one
        self.assertEqual(self.judge([c, p, reverted("r1", M1, "unknown"), reverted("r2", M1, "build_break")]),
                         {"verdict": "FAIL", "reasons": ["cause_mismatch"]})
        # a commit of another drill family is not C
        lesson = commit("c3", earlier)
        lesson["payload"] = dict(lesson["payload"], drill="lesson")
        self.assertEqual(self.judge([c, lesson, p, r]), {"verdict": "PASS", "reasons": []})

    def test_unusable_key(self):
        for key in (None, [], {}, dict(self.answer, extra="x"), {k: v for k, v in self.answer.items() if k != "cause"},
                    dict(self.answer, cause=None), dict(self.answer, cycle_id=7)):
            with self.assertRaises(D.Unusable, msg=key):
                D.judge(ledger_with(self.good()), key)


# ---------------------------------------------------------------- the run

RED_RUN = {"results": [{"id": "t1", "status": "fail"}, {"id": "t2", "status": "pass"}]}
GREEN_RUN = {"results": [{"id": "t1", "status": "pass"}, {"id": "t2", "status": "pass"}]}
CALM = {"impact": ["t1"], "build_ok": True, "lint": {"eslint": {"before": 3, "after": 3}}}
OBSERVED = {  # what the contained runs at a planted head would report, per planted cause
    "test_regression": ([RED_RUN] * 4, CALM),
    "build_break": ([{"results": []}] * 4, dict(CALM, build_ok=False)),
    "lint_regression": ([RED_RUN] * 4, dict(CALM, lint={"eslint": {"before": 3, "after": 5}})),
}


class Run(unittest.TestCase):
    def world(self):
        gh, wr, root = world()
        base = gh.seed_commit("t-base", files={"src/a.js": b"export const a = 1;\n", "test/a.test.js": b"ok\n"})
        gh.refs["main"] = gh.refs["brain/integration"] = base
        return gh, wr, base

    def committed(self, instance_id):
        cycle = cycle_choosing(instance_id)
        start = ledger_with([row("g1", "events", "genesis", {})])
        return cycle, ledger_with([commit("d-" + cycle, D.key(SEED, cycle, CATALOG))], start)

    def drill(self, wr, cycle, ledger, observe, files=FILES, previous=None, catalog=CATALOG):
        calls = []

        def watch(merge):
            calls.append(merge)
            return observe(merge)

        out = D.run_drill(wr, SEED, catalog, cycle, files, ledger, ledger if previous is None else previous, watch,
                          "brain/integration", GATE)
        return out, calls

    def appended(self, ledger, out, cycle):
        rows = [row("p-" + cycle, "drill", "plant", out["plant"])]
        if out["revert"] is not None:
            rows.append(row("r-" + cycle, "events", "revert", out["revert"], out["cause"]))
        return ledger_with(rows, ledger)

    def test_each_planted_cause_is_reverted_and_judged_pass(self):
        for instance in IDS:
            with self.subTest(instance):
                gh, wr, base = self.world()
                cycle, ledger = self.committed(instance)
                out, calls = self.drill(wr, cycle, ledger, lambda m, c=CAUSE[instance]: OBSERVED[c])
                self.assertEqual(out["key"], hand_key(cycle))
                merge = out["plant"]["merge_sha"]
                self.assertEqual(out["plant"], D.plant_payload(instance, merge))
                self.assertEqual((out["reverted"], out["cause"], out["revert"]), (True, CAUSE[instance],
                                                                                 {"merge_sha": merge}))
                self.assertEqual(calls, [merge])
                self.assertEqual(gh.commits[merge]["parents"][0], base)
                branch = "brain/drill/" + cycle
                self.assertEqual(gh.read_file(branch, "src/a.js"), FILES[instance]["src/a.js"].encode())
                revert_head = gh.refs[branch + "-revert"]
                self.assertEqual(gh.commits[revert_head]["tree"], gh.commits[base]["tree"])
                planted_check = [c for c in gh.checks if c["head_sha"] == gh.commits[merge]["parents"][1]]
                self.assertIn("not a gate decision", json.dumps(planted_check))
                self.assertEqual(gh.refs["main"], base)
                self.assertEqual(D.judge(self.appended(ledger, out, cycle), out["key"]),
                                 {"verdict": "PASS", "reasons": []})

    def test_another_cause_fails(self):
        gh, wr, base = self.world()
        cycle, ledger = self.committed("failing-test")
        out, _ = self.drill(wr, cycle, ledger, lambda m: OBSERVED["lint_regression"])
        self.assertEqual(out["cause"], "lint_regression")
        self.assertEqual(D.judge(self.appended(ledger, out, cycle), out["key"]),
                         {"verdict": "FAIL", "reasons": ["cause_mismatch"]})

    def test_green_watch_is_not_reverted(self):
        gh, wr, base = self.world()
        cycle, ledger = self.committed("failing-test")
        out, _ = self.drill(wr, cycle, ledger, lambda m: ([GREEN_RUN], CALM))
        self.assertEqual((out["reverted"], out["revert"], out["cause"]), (False, None, None))
        self.assertNotIn("brain/drill/%s-revert" % cycle, gh.refs)
        self.assertEqual(D.judge(self.appended(ledger, out, cycle), out["key"]),
                         {"verdict": "FAIL", "reasons": ["not_reverted"]})

    def assertNothingWritten(self, error, cycle, ledger, previous=None, files=FILES, catalog=CATALOG):
        gh, wr, base = self.world()
        before = len(gh.requests)
        calls = []
        with self.assertRaises(error):
            D.run_drill(wr, SEED, catalog, cycle, files, ledger, ledger if previous is None else previous,
                        lambda m: calls.append(m), "brain/integration", GATE)
        self.assertEqual((len(gh.requests), calls), (before, []))

    def test_no_matching_commitment_plants_nothing(self):
        cycle, ledger = self.committed("failing-test")
        self.assertNothingWritten(D.NoCommitment, cycle, b"")
        self.assertNothingWritten(D.NoCommitment, str(int(cycle) + 1), ledger)  # another cycle's commitment
        self.assertNothingWritten(D.NoCommitment, cycle, ledger, catalog={"instances": CATALOG["instances"][:2]})
        spent = ledger_with([plant("p", "failing-test", M1)], ledger)
        self.assertNothingWritten(D.NoCommitment, cycle, spent)
        forged = dict(commit("f", D.key({"seed": "other"}, cycle, CATALOG)))
        self.assertNothingWritten(D.NoCommitment, cycle, ledger_with([forged]))
        # a plant row carrying the commitment's payload is no commitment
        as_plant = row("x", "drill", "plant", D.commit_payload(D.key(SEED, cycle, CATALOG)))
        self.assertNothingWritten(D.NoCommitment, cycle, ledger_with([as_plant], ledger))

    def test_edited_ledger_stops(self):
        cycle, ledger = self.committed("failing-test")
        lines = ledger.splitlines(keepends=True)
        last = json.loads(lines[-1])
        last["payload"]["commitment_sha256"] = "0" * 64
        edited = b"".join(lines[:-1]) + json.dumps(last).encode() + b"\n"
        self.assertNothingWritten(D.HardStop, cycle, edited)
        self.assertNothingWritten(D.HardStop, cycle, ledger, previous=ledger + b'{"row_id": "gone"}\n')

    def test_unusable_inputs_write_nothing(self):
        cycle, ledger = self.committed("failing-test")
        for files in (None, {}, {"failing-test": {}}, {"failing-test": {"../a": "x"}},
                      {"failing-test": {"a": b"x"}}, {"failing-test": {".git/config": "x"}},
                      {k: v for k, v in FILES.items() if k != "failing-test"}):
            self.assertNothingWritten(D.Unusable, cycle, ledger, files=files)
        self.assertNothingWritten(D.Unusable, "x", ledger)


# ---------------------------------------------------------------- command line

class CommandLine(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)

    def file(self, name: str, data) -> str:
        path = os.path.join(self.dir.name, name)
        with open(path, "wb") as handle:
            handle.write(data if isinstance(data, bytes) else json.dumps(data).encode())
        return path

    def test_commit_and_reveal(self):
        cat, seed = self.file("c.json", CATALOG), self.file("s.json", SEED)
        k = hand_key("41000000018")
        self.assertEqual(cli(b'{"cycle_id":"41000000018"}', "commit", cat, seed),
                         (0, {"commitment_sha256": D.commitment(k)}, ""))
        code, out, _ = cli(b'{"cycle_id":"41000000018"}', "commit", cat, seed)
        self.assertNotIn(k["selection"], json.dumps(out))
        self.assertEqual(cli(b'{"cycle_id":"41000000018"}', "reveal", cat, seed),
                         (0, {"key": k, "revealed_sha256": D.commitment(k)}, ""))

    def test_judge(self):
        cycle = cycle_choosing("broken-build")
        k = D.key(SEED, cycle, CATALOG)
        good = ledger_with([commit("c", k), plant("p", "broken-build", M1), reverted("r", M1, "build_break")])
        wrong = ledger_with([commit("c", k), plant("p", "broken-build", M1), reverted("r", M1, "unknown")])
        key = self.file("k.json", k)
        self.assertEqual(cli(b"", "judge", self.file("g.jsonl", good), key), (0, {"verdict": "PASS", "reasons": []},
                                                                            ""))
        self.assertEqual(cli(b"", "judge", self.file("w.jsonl", wrong), key)[:2],
                         (1, {"verdict": "FAIL", "reasons": ["cause_mismatch"]}))
        self.assertEqual(cli(b"", "judge", self.file("b.jsonl", b"[]\n"), key)[:2],
                         (1, {"verdict": "FAIL", "reasons": ["chain_broken"]}))

    def test_unusable(self):
        cat, seed = self.file("c.json", CATALOG), self.file("s.json", SEED)
        missing = os.path.join(self.dir.name, "none.json")
        good = b'{"cycle_id":"7"}'
        led = self.file("l.jsonl", b"")
        key = self.file("k.json", hand_key("7"))
        empty = {"commit": {"commitment_sha256": None}, "reveal": {"key": None, "revealed_sha256": None},
                 "judge": {"verdict": "FAIL"}}
        cases = [
            (good, ["commit", cat]), (good, ["drill", cat, seed]), (good, ["commit", cat, seed, "x"]), (good, []),
            (b"{", ["commit", cat, seed]), (b"\xff", ["reveal", cat, seed]), (b'{"cycle_id":7}', ["commit", cat, seed]),
            (b'{"cycle_id":"7","x":1}', ["commit", cat, seed]), (b'{"cycle_id":"7a"}', ["reveal", cat, seed]),
            (good, ["commit", missing, seed]), (good, ["reveal", cat, missing]), (good, ["commit", self.dir.name, seed]),
            (good, ["commit", self.file("e.json", {"instances": []}), seed]),
            (good, ["commit", self.file("d.json", b'{"instances":[{"id":"a","cause":"c"},{"id":"a","cause":"d"}]}'),
                    seed]),
            (good, ["commit", cat, self.file("bad-seed.json", {"seed": 1})]),
            (good, ["reveal", cat, self.file("dup.json", b'{"seed":"a","seed":"b"}')]),
            (b"", ["judge", missing, key]), (b"", ["judge", led, missing]),
            (b"", ["judge", led, self.file("k3.json", {"cycle_id": "7", "selection": "s", "instance_id": "i"})]),
            (b"", ["judge", led, self.file("k5.json", dict(hand_key("7"), extra="x"))]),
            (b"", ["judge", led, self.file("kn.json", b"[]")]),
        ]
        for stdin, argv in cases:
            code, out, err = cli(stdin, *argv)
            want = empty.get(argv[0] if len(argv) == 3 else None, {"verdict": "FAIL"})
            self.assertEqual((code, out), (2, want), (stdin, argv))
            self.assertTrue(err.startswith("unusable input: "), err)


if __name__ == "__main__":
    unittest.main()
