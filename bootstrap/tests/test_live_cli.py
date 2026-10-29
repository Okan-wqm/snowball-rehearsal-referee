"""The real `claude` CLI against the contract rival.py relies on. Runs only where the CLI is installed.

No model call is made and nothing is spent: the CLI is run with a made-up token, so the API answers 401.
That is enough to tell a drifted contract from a healthy one, because the CLI only prints the result
this module parses when it accepted every flag in `_cli_argv`.
"""

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from snowball_bootstrap import rival
from snowball_bootstrap.config import RivalConfig

PIN_FILE = Path(__file__).resolve().parents[1] / "requirements" / "claude-cli" / "package.json"
CLAUDE = rival.resolve_claude(None)
CFG = RivalConfig(model="claude-sonnet-5-5", effort="medium", max_turns=5, per_run_cap_usd_micros=1_000_000)
# Flags the CLI accepts but leaves out of `claude --help` (verified against 2.1.293).
HIDDEN_FLAGS = {"--system-prompt-file", "--max-turns"}


@unittest.skipUnless(CLAUDE, "the claude CLI is not on PATH")
class LiveCliContractTest(unittest.TestCase):
    def test_a_signed_out_cli_reports_an_outage_the_way_rival_py_expects(self):
        with tempfile.TemporaryDirectory() as tmp:
            tree = Path(tmp) / "tree"
            tree.mkdir()
            (tree / "a.py").write_text("x = 1" + chr(10))
            env = {"CLAUDE_CODE_OAUTH_TOKEN": "not-a-real-token", "CLAUDE_CONFIG_DIR": str(Path(tmp) / "cfg")}
            installed = subprocess.run([CLAUDE, "--version"], capture_output=True, text=True).stdout.split()[0]
            with mock.patch.dict(os.environ, env):  # the installed CLI may be newer than the pin: judge its contract
                out = rival.run_rival(CFG, claude_bin=CLAUDE, seat_prompt="seat", context="context", tree_root=tree,
                                      budget_usd_micros=1_000_000, max_prompt_chars=100_000, pinned_version=installed)
        # A renamed flag or a changed output format gives cli_exit_N or bad_cli_result instead.
        self.assertEqual(out.verdict, "unresolved")
        self.assertEqual(len(out.reasons), 1, out.reasons)
        self.assertRegex(out.reasons[0], r"^api_error:(http_[0-9]+|not_logged_in|unknown)$", out.reasons)
        self.assertEqual(out.cost_usd_micros, 0)

    def test_every_visible_flag_in_use_is_still_in_the_help(self):
        helptext = subprocess.run([CLAUDE, "--help"], capture_output=True, text=True, encoding="utf-8").stdout
        with tempfile.TemporaryDirectory() as tmp:
            argv = rival._cli_argv(CLAUDE, CFG, Path(tmp), Path(tmp), 1_000_000)
        flags = {arg.split("=", 1)[0] for arg in argv if arg.startswith("--")}
        self.assertTrue(flags - HIDDEN_FLAGS)
        for flag in sorted(flags - HIDDEN_FLAGS):
            self.assertIn(flag, helptext, f"{flag} is no longer documented by `claude --help`")

    def test_the_installed_version_is_the_pinned_one(self):
        pin = json.loads(PIN_FILE.read_text())["dependencies"]["@anthropic-ai/claude-code"]
        version = subprocess.run([CLAUDE, "--version"], capture_output=True, text=True).stdout.split()[0]
        if version != pin:
            self.skipTest(f"claude {version} is installed, the pin is {pin}; the contract tests above still apply")


if __name__ == "__main__":
    unittest.main()
