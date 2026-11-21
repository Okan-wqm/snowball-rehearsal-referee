"""The operator's restart row (`seed/founder/restart_row.py`; `26i`, `28a` (h), seed-085 h, E687): chained to the
counter by the referee's own rules, so the bootstrap reads it as a sound non-transfer touch. The trailing comment on a
test names the mutants it kills (`local/mutate.py`)."""

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

from snowball_bootstrap import canon, stagelock

ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location("restart_row", ROOT / "seed" / "founder" / "restart_row.py")
restart_row = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(restart_row)

STOP = "a" * 64


def transfer_counter() -> bytes:
    row = {"ts": "2026-11-20T00:00:00Z", "stage": 0, "brain_sha": "b" * 40, "referee_tree_sha256": "c" * 64,
           "result_sha256": "d" * 64, "prev_hash": stagelock.ZERO}
    row["row_hash"] = canon.row_hash(row)
    return json.dumps(row, separators=(",", ":")).encode() + b"\n"


class RestartRowTest(unittest.TestCase):
    def line(self, counter, **kw):
        args = dict(target="copy", hard_stop=STOP, stage=1, note="restart after the drift was repaired",
                    ts="2026-11-21T12:00:00Z")
        args.update(kw)
        return restart_row.restart_line(counter, **args)

    def test_the_row_chains_onto_the_counter(self):  # restart_row_unchained restart_row_hash_not_the_referees
        counter = transfer_counter()
        line = self.line(counter)
        rows = stagelock.chained_lines(counter + line, "setup/imports.jsonl")  # the bootstrap's own reading
        self.assertEqual(len(rows), 2)
        row = rows[-1][1]
        self.assertEqual({k: row[k] for k in ("touch", "target", "hard_stop", "stage")},
                         {"touch": "restart", "target": "copy", "hard_stop": STOP, "stage": 1})
        self.assertEqual(row["prev_hash"], rows[0][1]["row_hash"])
        self.assertFalse(stagelock.is_transfer(row))  # no batch count moves
        self.assertTrue(line.endswith(b"}\n") and b"\r" not in line)
        first = stagelock.chained_lines(self.line(b""), "setup/imports.jsonl")[0][1]
        self.assertEqual(first["prev_hash"], stagelock.ZERO)

    def test_a_bad_input_or_a_broken_counter_refuses(self):
        for kw in ({"target": ""}, {"hard_stop": "A" * 64}, {"hard_stop": "abc"}, {"stage": -1}, {"stage": "1"},
                   {"ts": "2026-11-21 12:00"}):
            with self.subTest(kw=kw), self.assertRaises(restart_row.Refused):
                self.line(b"", **kw)
        broken = transfer_counter().replace(b'"stage":0', b'"stage":5')
        with self.assertRaisesRegex(restart_row.Refused, "the counter is broken"):
            self.line(broken)

    def test_the_command_appends_and_refuses_without_writing(self):
        with tempfile.TemporaryDirectory() as tmp:
            counter = Path(tmp) / "setup" / "imports.jsonl"
            counter.parent.mkdir()
            counter.write_bytes(transfer_counter())
            self.assertEqual(restart_row.main([tmp, "--target", "copy", "--hard-stop", STOP, "--stage", "1"]), 0)
            self.assertEqual(len(stagelock.read_counter(Path(tmp))), 2)
            before = counter.read_bytes()
            self.assertEqual(restart_row.main([tmp, "--target", "copy", "--hard-stop", "x", "--stage", "1"]), 2)
            self.assertEqual(counter.read_bytes(), before)
        readme = (ROOT / "seed" / "founder" / "README.md").read_text(encoding="utf-8")
        self.assertIn("python seed/founder/restart_row.py <hakem checkout'u> --target <id> --hard-stop <row_hash>", readme)


if __name__ == "__main__":
    unittest.main()
