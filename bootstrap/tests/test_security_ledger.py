"""The referee's own security ledger (`seed/security-ledger.jsonl`, register E56) stays true and bound to the code.

Every row keeps the hash chain intact, names a CWE class, a catalogue class and a state that the seed pages
define, and points to regression tests, CI jobs and mutants that still exist: renaming a test or dropping a
mutant fails here, so a closed security gap cannot quietly lose the guard that keeps it closed.
"""

import json
import re
import sys
import unittest
from pathlib import Path

from snowball_bootstrap import secretscan

BOOT = Path(__file__).resolve().parents[1]
SEED = BOOT.parent
ROOT = SEED.parent
LEDGER = SEED / "security-ledger.jsonl"
# Last, not first: the brain's `profile/` package (MF4, MF6) would shadow the standard library's `profile` (and so
# `cProfile`) for every test that runs after this one (E191).
sys.path.append(str(BOOT / "local" / "reference_brain" / "referee"))
sys.path.insert(0, str(BOOT / "local"))
from ledger import chain  # noqa: E402
import mutate  # noqa: E402


def rows():
    return [json.loads(line) for line in LEDGER.read_text(encoding="utf-8").splitlines()]


def page(pattern):
    return "".join(p.read_text(encoding="utf-8") for p in sorted((ROOT / "spec" / "tohum").glob(pattern)))


class SecurityLedgerTest(unittest.TestCase):
    def test_the_chain_is_intact(self):
        self.assertGreaterEqual(len(rows()), 8)
        self.assertEqual(chain.check_file(str(LEDGER)), {"valid": True, "broken_row": None, "rows": len(rows())})

    def test_every_row_names_a_cwe_class_a_catalogue_class_and_a_defined_state(self):
        catalogue, ledger_page = page("30[abc]-*.md"), page("30e-*.md")
        states = set(re.search(r"state: ([a-z]+(?:\|[a-z]+)+)", ledger_page).group(1).split("|"))
        kinds = set(re.findall(r"(?m)^\| `([a-z_]+)` \|", ledger_page))
        self.assertIn("closed", states)
        self.assertIn("fix", kinds)
        for row in rows():
            payload = row["payload"]
            self.assertEqual(row["part"], "security", row["row_id"])
            self.assertRegex(payload["class"], r"^CWE-[0-9]+$", row["row_id"])
            self.assertTrue(f"`{payload['catalogue_id']}`" in catalogue, f"{row['row_id']}: unknown catalogue class")
            self.assertIn(payload["state"], states, f"{row['row_id']}: state not defined in 30e")
            self.assertIn(row["kind"], kinds, f"{row['row_id']}: kind not defined in 30e")

    def test_every_test_ci_job_and_mutant_a_row_names_still_exists(self):
        mutants = {m[0] for m in mutate.MUTANTS}
        for row in rows():
            for name in row["payload"].get("mutants", []):
                self.assertIn(name, mutants, f"{row['row_id']}: mutant {name} is gone from local/mutate.py")
            for ref in row["payload"].get("tests", []):
                path, *rest = ref.split("::")
                text = (ROOT / path).read_text(encoding="utf-8")
                if path.endswith(".py"):
                    cls, method = rest
                    self.assertRegex(text, rf"(?m)^class {re.escape(cls)}\(", f"{row['row_id']}: {ref}")
                    self.assertRegex(text, rf"(?m)^    def {re.escape(method)}\(", f"{row['row_id']}: {ref}")
                else:
                    self.assertRegex(text, rf"(?m)^  {re.escape(rest[0])}:", f"{row['row_id']}: {ref}")

    def test_nothing_secret_is_written_into_the_ledger(self):
        self.assertEqual(secretscan.scan(LEDGER.read_text(encoding="utf-8")), [])


if __name__ == "__main__":
    unittest.main()
