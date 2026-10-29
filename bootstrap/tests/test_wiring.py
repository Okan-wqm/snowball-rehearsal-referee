"""The parts of the bootstrap that only meet in production must agree: workflow, CLI, files, secrets, spec.

Nothing here runs a workflow. It reads `workflow/bootstrap.yml` the way a reviewer would and holds
every claim in it against the code and the spec, so that a renamed flag, a deleted file, a new secret
nobody documented or a stale instruction fails a test instead of the first real run.
"""

import re
import shlex
import unittest
from pathlib import Path

from snowball_bootstrap import cli, rival

BOOT = Path(__file__).resolve().parents[1]
ROOT = BOOT.parents[1]
WORKFLOW = (BOOT / "workflow" / "bootstrap.yml").read_text(encoding="utf-8")
SETUP_DAY = (ROOT / "spec" / "tohum" / "25-kurulum-gunu.md").read_text(encoding="utf-8")
BS = chr(92)


def run_blocks(text):
    """The shell text of every `run:` step, as a list of single commands (continuations joined)."""
    lines = text.splitlines()
    commands = []
    for i, line in enumerate(lines):
        m = re.match(r"^(\s*)(?:- )?run:\s*(.*)$", line)
        if not m:
            continue
        indent, rest = len(m.group(1)), m.group(2).strip()
        if rest not in ("|", ">"):
            commands.append(rest)
            continue
        body = []
        for follow in lines[i + 1:]:
            if follow.strip() and len(follow) - len(follow.lstrip()) <= indent + 1:
                break
            body.append(follow.strip())
        if rest == ">":
            commands.append(" ".join(b for b in body if b))
            continue
        joined, current = [], ""
        for b in body:
            if b.endswith(BS):
                current += b[:-1] + " "
            else:
                joined.append(current + b)
                current = ""
        commands.extend(c for c in joined if c)
    return commands


def bootstrap_invocations():
    found = []
    for command in run_blocks(WORKFLOW):
        m = re.search(r"python3 -m snowball_bootstrap ([^|]*?)(?: \| | >> |$)", command)
        if m:
            text = re.sub(r"\$\{\{.*?\}\}", "X", m.group(1))
            found.append(shlex.split(text))
    return found


class WorkflowWiringTest(unittest.TestCase):
    def test_every_invocation_is_accepted_by_the_real_argument_parser(self):
        invocations = bootstrap_invocations()
        self.assertGreater(len(invocations), 10)
        commands = {argv[0] for argv in invocations}
        self.assertIn("rival", commands)
        for argv in invocations:
            try:
                cli.build_parser().parse_args(argv)
            except SystemExit:
                self.fail(f"bootstrap.yml calls `{' '.join(argv)}`, which the CLI refuses")

    def test_every_file_the_workflow_reads_exists(self):
        paths = set(re.findall(r"snap/bootstrap/([A-Za-z0-9_./-]+)", WORKFLOW))
        self.assertIn("requirements/claude-cli/package.json", paths)
        for rel in sorted(paths):
            if "node_modules" in rel:  # created by npm ci in the job
                continue
            self.assertTrue((BOOT / rel).exists(), f"bootstrap.yml names snap/bootstrap/{rel}, which does not exist")

    def test_every_secret_and_variable_is_documented_for_the_operator(self):
        names = set(re.findall(r"(?:secrets|vars)@BS@.([A-Z0-9_]+)".replace("@BS@", BS), WORKFLOW))
        self.assertEqual(names, {"CLAUDE_CODE_OAUTH_TOKEN"})  # the brain is public: nothing else is held
        for name in names:
            self.assertIn(name, SETUP_DAY, f"tohum/25 never tells the operator about {name}")

    def test_the_model_credential_reaches_only_the_rival_step(self):
        self.assertEqual(WORKFLOW.count("${{ secrets.CLAUDE_CODE_OAUTH_TOKEN }}"), 1)
        used = re.findall(r"\$\{\{\s*secrets\.([A-Za-z0-9_]+)\s*\}\}", WORKFLOW)
        self.assertEqual(used, ["CLAUDE_CODE_OAUTH_TOKEN"])  # no other way to read a secret
        self.assertNotIn("toJSON(secrets", WORKFLOW)
        self.assertNotIn("secrets[", WORKFLOW)
        self.assertNotIn("secrets: inherit", WORKFLOW)
        rival_step = WORKFLOW[WORKFLOW.index("name: Seed rival"):]
        rival_step = rival_step[:rival_step.index("- id: pack")]
        self.assertIn("${{ secrets.CLAUDE_CODE_OAUTH_TOKEN }}", rival_step)
        self.assertNotIn("ANTHROPIC_API_KEY", WORKFLOW.replace("No API key", ""))

    def test_the_rival_is_run_with_the_cli_that_was_installed_and_pinned(self):
        install = re.search(r"npm ci --prefix (snap/bootstrap/requirements/claude-cli)", WORKFLOW)
        self.assertIsNotNone(install)
        self.assertIn(f"--claude {install.group(1)}/node_modules/.bin/claude", WORKFLOW)
        self.assertNotIn("--ignore-scripts", WORKFLOW)  # the CLI's own install step links its binary

    def test_the_brain_is_read_without_any_identity(self):
        """Public brain: no App token step, no token handed to the pull or the poll, no auth header in the code."""
        self.assertNotIn("app-id", WORKFLOW)
        self.assertEqual(re.findall(r"BRAIN_[A-Z_]+", WORKFLOW), [])
        self.assertNotIn("steps.app.", WORKFLOW)
        gitio_source = (BOOT / "snowball_bootstrap" / "gitio.py").read_text(encoding="utf-8")
        for needle in ("extraheader", "AUTHORIZATION", "x-access-token"):
            self.assertNotIn(needle, gitio_source, f"gitio still knows how to send {needle}")

    def test_no_github_context_is_expanded_inside_a_shell_script(self):
        """E17: `${{ github.ref }}` pasted into bash runs a branch name chosen by whoever can dispatch."""
        for command in run_blocks(WORKFLOW):
            self.assertNotRegex(command, r"\$\{\{\s*(github|inputs)\.", command[:160])

    def test_only_runs_on_main_judge_and_sign_and_the_identity_is_mains(self):
        """E17: a dispatch from another branch must neither judge nor sign, and the state is verified as main's."""
        cek = WORKFLOW[WORKFLOW.index("  cek:"):WORKFLOW.index("  getir:")]
        yaz = WORKFLOW[WORKFLOW.index("  yaz:"):]
        for job in (cek, yaz):
            self.assertIn("github.ref == 'refs/heads/main'", job.split("steps:", 1)[0])
        identity = re.search(r'--identity "([^"]+)"', WORKFLOW).group(1)
        self.assertTrue(identity.endswith("/.github/workflows/bootstrap.yml@refs/heads/main"), identity)

    def test_the_job_outlives_the_cli_it_waits_for(self):
        job = WORKFLOW[WORKFLOW.index("  cagir:"):]
        minutes = int(re.search(r"timeout-minutes: ([0-9]+)", job).group(1))
        self.assertGreater(minutes * 60, rival.CLI_TIMEOUT_S + 300, "install and bookkeeping need room too")


class NothingStaleTest(unittest.TestCase):
    STALE = ("call.txt", "secrets.ANTHROPIC", "import anthropic", "anthropic==", "/tmp/call", "Anthropic SDK",
             "model SDK", "price_micros_per_mtok", "READER_APP", "BRAIN_TOKEN", "create-github-app-token")

    def test_the_old_api_design_has_left_no_trace(self):
        here = Path(__file__).resolve()
        files = [p for base in (BOOT, ROOT / "spec" / "tohum", ROOT / "README.md") for p in
                 ([base] if base.is_file() else base.rglob("*"))
                 if p.is_file() and p != here and "node_modules" not in p.parts and "__pycache__" not in p.parts
                 and p.suffix in (".py", ".md", ".yml", ".json", ".txt")]
        self.assertGreater(len(files), 50)
        for path in files:
            if path.name == "package-lock.json" or path.name == "CHANGELOG.md":
                continue  # the changelog is history
            text = path.read_text(encoding="utf-8", errors="replace")
            for term in self.STALE:
                if path.name == "config.py" and term == "price_micros_per_mtok":
                    continue  # named on purpose, to tell an operator the key was removed
                if path.name == "test_units.py" and term == "price_micros_per_mtok":
                    continue
                self.assertNotIn(term, text, f"{path.relative_to(ROOT)} still says {term!r}")


if __name__ == "__main__":
    unittest.main()
