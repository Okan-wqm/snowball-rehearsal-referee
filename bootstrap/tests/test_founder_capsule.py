"""The Founder's capsule and launcher (`seed/founder`, register E90, E91, E112): the isolation the pilot relies on
is pinned here, so a later edit that loosens it fails a test instead of passing unnoticed."""

from __future__ import annotations

import importlib.util
import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from snowball_bootstrap import rival

FOUNDER = Path(__file__).resolve().parents[2] / "founder"


def load_launch():
    spec = importlib.util.spec_from_file_location("founder_launch", FOUNDER / "launch.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class CapsuleArgvTest(unittest.TestCase):
    def setUp(self):
        self.launch = load_launch()
        self.work = Path(tempfile.mkdtemp())
        pilot = self.launch.Pilot(self.work, "owner/brain", "owner/referee", "target")
        pilot.seed = "a" * 40
        self.argv = pilot.capsule_argv("20261029T000000Z", "claude-opus-5-5", 200, 50)
        self.joined = " ".join(self.argv)

    def mounts(self) -> dict[str, str]:
        out = {}
        for i, arg in enumerate(self.argv):
            if arg == "--mount":
                spec = dict(part.split("=", 1) if "=" in part else (part, "") for part in self.argv[i + 1].split(","))
                out[spec["dst"]] = "readonly" if "readonly" in spec else "rw"
        return out

    def test_the_capsule_is_locked_down(self):
        for flag in ("--read-only", "--rm"):
            self.assertIn(flag, self.argv)
        self.assertEqual(self.argv[self.argv.index("--cap-drop") + 1], "ALL")
        self.assertEqual(self.argv[self.argv.index("--security-opt") + 1], "no-new-privileges")
        for flag in ("--privileged", "--cap-add", "--pid", "--userns", "--ipc", "--device", "-v", "--volume",
                     "--network", "--net"):  # the default bridge only: never the host's network or namespaces
            self.assertFalse(any(a == flag or a.startswith(flag + "=") for a in self.argv), flag)
        self.assertNotIn("docker.sock", self.joined)
        self.assertEqual(self.argv[-1], self.launch.IMAGE)

    def test_secrets_referee_result_and_target_are_read_only_and_the_brain_lives_in_memory(self):
        self.assertEqual(self.mounts(), {"/run/secrets/founder.env": "readonly", "/work/referee": "readonly",
                                         "/work/target": "readonly", "/work/logs": "rw"})
        self.assertIn("/work/brain:rw,exec,size=2g,mode=1777", self.argv)  # a fresh clone every session, never on disk
        for i, arg in enumerate(self.argv):
            if arg == "-e":
                self.assertNotRegex(self.argv[i + 1], r"TOKEN|KEY|SECRET", "a secret passed as an environment flag")

    def test_a_session_sees_only_its_own_transcript_folder_and_gets_the_seed(self):  # E155, E154
        logs = [self.argv[i + 1] for i, a in enumerate(self.argv) if a == "--mount" and "dst=/work/logs" in self.argv[i + 1]]
        self.assertEqual(len(logs), 1)
        src = Path(re.search(r"src=([^,]+)", logs[0]).group(1))
        self.assertEqual(src, self.work / "logs" / "20261029T000000Z")
        self.assertIn("BRAIN_SEED=" + "a" * 40, self.argv)

    def test_every_mount_stays_inside_the_one_work_folder(self):
        for i, arg in enumerate(self.argv):
            if arg == "--mount":
                src = re.search(r"src=([^,]+)", self.argv[i + 1]).group(1)
                self.assertTrue(Path(src).is_relative_to(self.work), src)


class BuildContextTest(unittest.TestCase):
    def test_a_windows_checkout_reaches_the_image_with_lf_and_nothing_else(self):  # E152
        launch = load_launch()
        seed = Path(tempfile.mkdtemp())
        for rel in launch.BUILD_FILES:
            (seed / rel).parent.mkdir(parents=True, exist_ok=True)
            (seed / rel).write_bytes(b"#!/bin/sh\r\nset -eu\r\n" if rel.endswith(".sh") else b"line\r\nline\r\n")
        (seed / "founder" / "secret-notes.txt").write_bytes(b"not for the image\n")
        launch.SEED = seed
        ctx = Path(tempfile.mkdtemp())
        launch.write_build_context(ctx)
        files = sorted(p.relative_to(ctx).as_posix() for p in ctx.rglob("*") if p.is_file())
        self.assertEqual(files, sorted(launch.BUILD_FILES))
        for rel in files:
            self.assertNotIn(b"\r", (ctx / rel).read_bytes(), rel)
        self.assertEqual((ctx / "founder/entrypoint.sh").read_bytes(), b"#!/bin/sh\nset -eu\n")


class RefereeRetryTest(unittest.TestCase):  # E166: the loop never waits on the Founder for the rival's own failure
    def run_cycle(self, evaluated_on):
        launch = load_launch()
        before, after = "a" * 40, "b" * 40
        report = []

        class Fake(launch.Pilot):
            dispatches = 0
            heads = [before, after]

            def fetch_result(self):
                if not self.dispatches:
                    return None
                done = self.dispatches >= evaluated_on
                return {"head": after, "verdict": "accepted" if done else "rejected",
                        "warnings": [] if done else [f"rival_side_retry:{self.dispatches}"],
                        "state": {"last_evaluated_sha": after if done else None}}

            def dispatch_referee(self, timeout_s):
                self.dispatches += 1
                return {"id": str(self.dispatches), "conclusion": "success", "url": "u"}

            def brain_head(self):
                return self.heads.pop(0)

            def ledger_rows(self, sha):
                return []

            def session(self, *a):
                return {"exit": 0, "minutes": 1}

            def write(self, text):
                report.append(text)

        pilot = Fake(Path(tempfile.mkdtemp()), "o/brain", "o/referee", "target")
        pilot.idle = 0
        pilot.seed = before  # a fresh pilot: nothing to judge before the first session
        args = type("Args", (), dict(model="m", max_turns=1, budget_usd=1, session_timeout=1, referee_timeout=1))
        with mock.patch.object(launch, "say"):
            pilot.cycle(1, args)
        self.metrics = [json.loads(line) for line in pilot.metrics.read_text(encoding="utf-8").splitlines()]
        return pilot.dispatches, "".join(report), launch.MAX_REFEREE_RETRIES

    def test_every_cycle_leaves_one_measurable_line(self):  # what docs/pilot-gunlugu.md counts
        self.run_cycle(evaluated_on=2)
        self.assertEqual(len(self.metrics), 1)
        m = self.metrics[0]
        self.assertEqual((m["pushed"], m["verdict"], m["referee_retries"], m["brain_after"]), (True, "accepted", 1, "b" * 40))
        for key in ("reasons", "warnings", "rival_attempts", "reproduced", "old_refutations_still_reproducing",
                    "ledger_new", "reports_new", "minutes", "cost_usd"):
            self.assertIn(key, m)

    def catch_up(self, prior_head):
        launch = load_launch()
        head, calls = "b" * 40, []

        class Fake(launch.Pilot):
            dispatches = 0

            def fetch_result(self):
                judged = head if self.dispatches else prior_head
                return {"head": judged, "verdict": "rejected", "state": {"last_evaluated_sha": judged},
                        "warnings": [], "reasons": []}

            def dispatch_referee(self, timeout_s):
                self.dispatches += 1
                calls.append("referee")
                return {"id": "1", "conclusion": "success", "url": "u"}

            def brain_head(self):
                return head  # the session pushes nothing

            def ledger_rows(self, sha):
                return []

            def session(self, *a):
                calls.append("session")
                return {"exit": 0, "minutes": 1}

            def write(self, text):
                pass

        pilot = Fake(Path(tempfile.mkdtemp()), "o/brain", "o/referee", "target")
        pilot.idle, pilot.seed = 0, "s" * 40
        args = type("Args", (), dict(model="m", max_turns=1, budget_usd=1, session_timeout=1, referee_timeout=1))
        with mock.patch.object(launch, "say"):
            pilot.cycle(1, args)
        return calls

    def test_a_push_the_referee_never_judged_is_judged_before_the_next_session(self):  # E168
        self.assertEqual(self.catch_up(prior_head="a" * 40), ["referee", "session"])
        self.assertEqual(self.catch_up(prior_head="b" * 40), ["session"])  # already judged: straight to work

    def test_a_reasons_owner_is_the_referees_own_rule(self):
        owner = load_launch().reason_owner
        self.assertEqual(owner({"kind": "refutation_reproduced", "ref": "repro:x"}), "founder")
        self.assertEqual(owner({"kind": "rival_unresolved", "ref": "secret_in_prompt:generic_assignment"}), "founder")
        self.assertEqual(owner({"kind": "rival_unresolved", "ref": "secret_in_verdict:generic_assignment_bare"}), "rival")
        self.assertEqual(owner({"kind": "rival_missing", "ref": ""}), "rival")
        self.assertEqual(owner({"kind": "infra", "ref": "kos"}), "referee")
        self.assertEqual(owner({"kind": "budget", "ref": ""}), "referee")

    def test_an_unevaluated_commit_goes_back_to_the_referee_before_the_next_session(self):
        dispatches, report, _ = self.run_cycle(evaluated_on=2)
        self.assertEqual(dispatches, 2)
        self.assertIn("1 kez yeniden incelendi", report)
        self.assertIn("**accepted**", report)

    def test_an_evaluated_commit_is_not_sent_again_and_retries_are_capped(self):
        self.assertEqual(self.run_cycle(evaluated_on=1)[0], 1)
        dispatches, report, cap = self.run_cycle(evaluated_on=99)
        self.assertEqual(dispatches, 1 + cap)
        self.assertIn(f"{cap} kez yeniden incelendi", report)


class TranscriptTest(unittest.TestCase):
    def test_the_closing_result_event_is_what_the_report_reads(self):
        launch = load_launch()
        path = Path(tempfile.mkdtemp()) / "s.jsonl"
        events = [{"type": "system", "subtype": "init"}, {"type": "result", "num_turns": 1, "total_cost_usd": 0.1},
                  "not json", {"type": "result", "subtype": "success", "num_turns": 7, "total_cost_usd": 1.5,
                               "result": "pushed MF1"}]
        path.write_text("\n".join(e if isinstance(e, str) else json.dumps(e) for e in events), encoding="utf-8")
        self.assertEqual(launch.Pilot.transcript_summary(path),
                         {"turns": 7, "cost_usd": 1.5, "subtype": "success", "final": "pushed MF1"})
        self.assertEqual(launch.Pilot.transcript_summary(path.with_name("missing.jsonl")), {"transcript": "missing"})


class ImageAndEntrypointTest(unittest.TestCase):
    def setUp(self):
        self.dockerfile = (FOUNDER / "Dockerfile").read_text(encoding="utf-8")
        self.entry = (FOUNDER / "entrypoint.sh").read_text(encoding="utf-8")

    def test_base_images_are_pinned_by_digest_and_the_founder_is_not_root(self):
        froms = re.findall(r"(?m)^FROM (\S+)", self.dockerfile)
        self.assertEqual(len(froms), 2)
        for image in froms:
            self.assertRegex(image, r"@sha256:[0-9a-f]{64}$")
        self.assertRegex(self.dockerfile, r"(?m)^USER founder$")
        self.assertIn("COPY bootstrap/requirements/claude-cli/", self.dockerfile)  # the referee's own CLI pin
        self.assertIn("npm ci", self.dockerfile)

    def test_the_capsule_pins_the_cli_like_the_referee_does(self):
        env_block = self.dockerfile[self.dockerfile.index("ENV "):self.dockerfile.index("USER ")]
        for key, value in rival.PINNED_ENV.items():
            self.assertRegex(env_block, rf"\b{key}={value}\b", f"{key} differs from the referee's rival pin")

    def test_the_founder_fixes_root_causes_and_never_hides_them(self):  # E204, owner 2026-10-29
        prompt = " ".join((FOUNDER / "prompt.md").read_text(encoding="utf-8").split())
        for phrase in ("kök nedeninden ve mimari olarak onar", "`except: pass`", "susturmak",
                       "özel durum olarak kodlamak", "düzeltilmiş gibi yapma"):
            self.assertIn(phrase, prompt)

    def test_the_founder_measures_its_own_coverage_on_the_real_target(self):  # E203: the muscle, not a per-repo patch
        prompt = " ".join((FOUNDER / "prompt.md").read_text(encoding="utf-8").split())
        for phrase in ("`/work/target` üzerinde salt okunur çalıştır", "kapsamını ölç", "`missing_capability:`",
                       "tek bir repoya özel yama değil", "hedefte yeniden ölçüp farkı yaz", "herkese açıktır"):
            self.assertIn(phrase, prompt)
        self.assertNotIn("project.json", prompt)  # the duty is general; what is missing is the Founder's to find
        self.assertNotIn("Nx", prompt)

    def test_the_session_has_no_inherited_configuration_and_no_mcp(self):
        self.assertIn('--setting-sources ""', self.entry)
        self.assertIn("--strict-mcp-config", self.entry)
        self.assertIn("--no-session-persistence", self.entry)
        self.assertIn('CLAUDE_CONFIG_DIR="$(mktemp -d)"', self.entry)
        self.assertNotIn("ANTHROPIC_API_KEY", self.entry + self.dockerfile)

    def test_git_trusts_the_brain_clone_on_its_root_owned_tmpfs(self):  # E152: without it no commit, no push
        self.assertIn("safe.directory /work/brain", self.entry)

    def test_the_clone_holds_no_history_before_the_seed(self):  # E154: earlier rehearsal code is not the Founder's
        cut = self.entry[self.entry.index('if [ -n "${BRAIN_SEED:-}" ]'):]
        self.assertIn('merge-base --is-ancestor "$BRAIN_SEED" HEAD', cut)
        self.assertIn("> /work/brain/.git/shallow", cut)
        self.assertIn("reflog expire --expire=now --all", cut)
        self.assertIn("gc --quiet --prune=now", cut)
        self.assertLess(self.entry.index("git clone"), self.entry.index('if [ -n "${BRAIN_SEED:-}" ]'))
        self.assertLess(self.entry.index("gc --quiet --prune=now"), self.entry.index("claude -p"))

    def test_the_github_token_never_reaches_a_url_a_command_line_or_the_log(self):
        self.assertIn("http.https://github.com/.extraheader", self.entry)
        self.assertIn("unset GITHUB_TOKEN basic", self.entry)
        self.assertNotRegex(self.entry, r"https://[^\"\s]*\$\{?GITHUB_TOKEN")
        self.assertNotRegex(self.entry, r"echo[^\n]*\$\{?(GITHUB_TOKEN|CLAUDE_CODE_OAUTH_TOKEN|basic)")
        self.assertNotIn("set -x", self.entry)


if __name__ == "__main__":
    unittest.main()
