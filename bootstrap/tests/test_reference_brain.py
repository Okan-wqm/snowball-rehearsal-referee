"""The reference brain (`local/reference_brain/`) that the end-to-end run and the GitHub rehearsal push is real.

It is held to what the referee holds a Founder push to, minus Docker: its manifest passes the Stage 0 checks,
its own tests pass, the seed vectors of the micro-features it declares done pass through the real vector
runner, and its tests fail when its code is wrong (one mutant here; `local/mutate_brain.py` runs them all).
A stub here once claimed eighteen micro-features with import-only tests, and the real rival refuted it.
"""

import json
import shlex
import subprocess
import sys
import time
import unittest
from pathlib import Path

from snowball_bootstrap import manifest, vectors
from snowball_bootstrap.container import RunResult

BOOT = Path(__file__).resolve().parents[1]
BRAIN = BOOT / "local" / "reference_brain"
VECTORS = BOOT / "vectors"
sys.path.insert(0, str(BOOT / "local"))
import mutate_brain  # noqa: E402


class LocalRunner:
    """The vector commands run on this machine instead of in a container: same cwd, stdin and /vec/ files."""

    def run(self, cmd, *, cwd=".", stdin=b"", timeout_s):
        argv = [sys.executable if part == "python" else
                VECTORS.as_posix() + part[len("/vec"):] if part.startswith("/vec/") else part
                for part in shlex.split(cmd)]
        started = time.monotonic()
        proc = subprocess.run(argv, cwd=BRAIN / cwd, input=stdin, capture_output=True, timeout=timeout_s, check=False)
        return RunResult(proc.returncode, proc.stdout, proc.stderr, int((time.monotonic() - started) * 1000))


def brain_manifest():
    return manifest.parse_manifest((BRAIN / "snowball-tests.json").read_text(encoding="utf-8"))


class ReferenceBrainTest(unittest.TestCase):
    def test_its_manifest_passes_the_stage0_checks_and_claims_only_what_it_has(self):
        found = brain_manifest()
        self.assertEqual(manifest.check_stage0(found), [])
        self.assertEqual(found.done_mf, (1,))
        self.assertEqual(found.lockfiles, ())  # standard library only: nothing to fetch, nothing unused pinned

    def test_its_own_tests_pass(self):
        code, failed = mutate_brain.run_tests(BRAIN / "referee")
        self.assertEqual(code, 0, failed)

    def test_the_seed_vectors_of_what_it_declares_done_pass_through_the_real_vector_runner(self):
        done = brain_manifest().done_mf
        spec = json.loads((VECTORS / "vectors.json").read_text(encoding="utf-8"))
        self.assertEqual([name for name, _fn in vectors.GROUPS if spec[name]["mf"] in done], ["chain"])
        results = vectors.run_vectors(LocalRunner(), VECTORS, done)
        self.assertEqual(len(results), 6, results)
        self.assertEqual([r for r in results if not r["ok"]], [])

    def test_every_brain_mutant_still_applies(self):
        text = (BRAIN / "referee" / mutate_brain.TARGET).read_text(encoding="utf-8")
        for name, old, _new, _why in mutate_brain.MUTANTS:
            self.assertEqual(text.count(old), 1, f"{name}: its anchor must occur exactly once in the brain")

    def test_its_tests_catch_the_bug_the_first_rehearsal_found(self):
        mutant = next(m for m in mutate_brain.MUTANTS if m[0] == "earlier_file_ignored")
        killed, detail, _ = mutate_brain.run_mutant(mutant)
        self.assertTrue(killed, detail)


if __name__ == "__main__":
    unittest.main()
