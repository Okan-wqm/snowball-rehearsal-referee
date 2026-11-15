"""Test 20 (asama-0/09): a known bad candidate runs in every contained run and must come out red; green
makes every result of that run invalid (tohum/08 item 3).

The known bad candidate here is a tree whose check exits 1. The control is red only when it ran to the
end (status ``ok``) with an exit code other than 0, 125, 126 and 127; a runner that loses exit codes, a
control that passes, or a control that never ran each make the run invalid, while the job's own result
is still reported.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import unittest

REFEREE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REFEREE)

from runner import contained  # noqa: E402
from fake_docker import FakeDocker, FixedRunner  # noqa: E402
from test_contained import IMAGE, PROBE, operating, writable_base  # noqa: E402


class RedControlTest(unittest.TestCase):
    def setUp(self) -> None:
        self.base = writable_base()
        self.addCleanup(shutil.rmtree, self.base, True)
        self.tree = os.path.join(self.base, "tree")
        os.mkdir(self.tree)
        shutil.copy(PROBE, os.path.join(self.tree, "probe.py"))

    def job(self, *steps: str) -> dict:
        return {"image": IMAGE, "cmd": ["python3", "/work/probe.py", *steps], "tree": self.tree}

    def bad(self) -> dict:
        return self.job("write", "/out/verdict.txt", "fail", "exit", "1")

    def test_red_control_red_keeps_the_run_valid(self):
        fake = FakeDocker()
        r = contained.run_with_red_control(self.job("write", "/out/verdict.txt", "pass"), self.bad(), operating(),
                                           runner=fake, base=self.base)
        self.assertEqual((r["valid"], r["reasons"]), (True, []))
        self.assertEqual(r["red_control"]["exit"], 1)
        self.assertEqual(r["result"]["exit"], 0)
        roots = [c["mounts"][0]["src"] for c in fake.calls]
        self.assertEqual(len(fake.calls), 2)
        self.assertNotEqual(roots[0], roots[1])
        for call in fake.calls:  # the control runs under the same containment as the job
            self.assertTrue(contained.check_argv(call["argv"])["ok"])
            self.assertEqual(call["argv"][call["argv"].index("--network") + 1], "none")

    def test_red_control_green_invalidates(self):
        r = contained.run_with_red_control(self.job(), self.job("exit", "0"), operating(), runner=FakeDocker(),
                                           base=self.base)
        self.assertEqual((r["valid"], r["reasons"]), (False, ["red_control_green"]))
        self.assertEqual(r["result"]["status"], "ok")  # the job's own result is kept, marked by the run

    def test_runner_that_loses_exit_codes_is_caught(self):
        r = contained.run_with_red_control(self.job(), self.bad(), operating(), runner=FakeDocker(exit_override=0),
                                           base=self.base)
        self.assertFalse(r["valid"])
        self.assertEqual(r["reasons"], ["red_control_green"])

    def test_control_that_did_not_run_is_a_fault(self):
        for runner in (FixedRunner(125), FixedRunner(126), FixedRunner(127), FixedRunner(None, timed_out=True)):
            r = contained.run_with_red_control(self.job(), self.bad(), operating(), runner=runner, base=self.base)
            self.assertFalse(r["valid"])
            self.assertIn("red_control_fault", r["reasons"])
        r = contained.run_with_red_control(self.job("write", "/out/big", "x" * 20), self.bad(),
                                           operating(output_bytes=10), runner=FakeDocker(), base=self.base)
        self.assertEqual((r["valid"], r["reasons"]), (False, ["limit_hit:output_bytes"]))
        r = contained.run_with_red_control(self.job(), self.job("write", "/out/big", "x" * 20, "exit", "1"),
                                           operating(output_bytes=10), runner=FakeDocker(), base=self.base)
        self.assertEqual((r["valid"], r["reasons"]), (False, ["red_control_fault"]))

    def test_every_run_carries_a_control(self):
        other = dict(self.bad(), image="python:3.11-slim@sha256:" + "cd" * 32)
        for missing in (None, {}, {"image": IMAGE}, other, dict(self.bad(), image=None)):
            with self.assertRaises(contained.ContainmentError):
                contained.run_with_red_control(self.job(), missing, operating(), runner=FakeDocker(), base=self.base)
        job_file = os.path.join(self.base, "req.json")
        with open(job_file, "w") as fh:
            json.dump({"job": self.job(), "operating": operating(), "base": self.base}, fh)
        p = subprocess.run([sys.executable, "-m", "runner.contained", "run", job_file], cwd=REFEREE,
                           capture_output=True, text=True)
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertIn("red control", json.loads(p.stdout)["error"])


if __name__ == "__main__":
    unittest.main()
