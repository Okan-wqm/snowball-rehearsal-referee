"""Mutation check of the bootstrap's own tests: break the code on purpose, expect a test to notice.

Every mutant is one textual change to the referee's code that a careless edit could plausibly make.
The check copies the repository layout to a temporary directory, applies the change, runs the unit
tests there and demands a failure. A mutant that survives names behaviour no test measures. An
anchor that no longer matches fails loudly, so the list cannot rot while the code moves on.

    cd seed/bootstrap && python3 local/mutate.py [--only NAME] [--list] [--shard K/N]

Run it on Linux (several tests need a POSIX shell). Exit 0 means every mutant was killed.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

BOOT = Path(__file__).resolve().parents[1]
ROOT = BOOT.parents[1]
PKG = "seed/bootstrap/snowball_bootstrap"

# (name, file, old text found exactly once, new text, what the mutant stands for)
MUTANTS = [
    ("outage_judged_by_served_model", f"{PKG}/rival.py",
     'if result.get("is_error") or subtype.startswith("error"):',
     'if served and (result.get("is_error") or subtype.startswith("error")):',
     "the bug found in review: a signed-out CLI (no model) became model_mismatch and counted against the push"),
    ("outage_check_removed", f"{PKG}/rival.py",
     'if result.get("is_error") or subtype.startswith("error"):', "if False:",
     "failed calls read as verdicts"),
    ("model_check_removed", f"{PKG}/rival.py", "if served != [cfg.model]:", "if False:",
     "any served model is accepted"),
    ("model_from_modelusage_only", f"{PKG}/rival.py", "served = sorted(api_models | set(usage))",
     "served = sorted(set(usage))", "the CLI names the requested model; the API's reply is ignored"),
    ("refusal_read_as_outage", f"{PKG}/rival.py", 'if result.get("stop_reason") == "refusal":', "if False:",
     "a refusal is retried forever"),
    ("isolation_not_attested", f"{PKG}/rival.py", "fault = _isolation_fault(init, usage)", "fault = None",
     "a run with extra tools or an API key is accepted"),
    ("verdict_not_validated", f"{PKG}/rival.py", "verdict = validate_verdict(raw, ToolBox(tree_root))",
     'verdict = {"verdict": raw.get("verdict"), "attempts": raw.get("attempts", [])}',
     "whatever the model wrote becomes the verdict"),
    ("negative_cost_accepted", f"{PKG}/rival.py", "if not math.isfinite(cost) or cost < 0:", "if False:",
     "a bad cost lowers the month's spend"),
    ("prompt_secret_scan_off", f"{PKG}/rival.py", "leaked = secretscan.scan(system_text",
     "leaked = [] and secretscan.scan(system_text", "a secret in the request is sent to the model"),
    ("verdict_secret_scan_off", f"{PKG}/rival.py", 'leaked = secretscan.scan(chr(10).join(_texts(verdict["attempts"])))',
     "leaked = []", "a secret in the verdict text reaches the signed artifacts"),
    ("api_key_reaches_the_cli", f"{PKG}/rival.py",
     'DROPPED_ENV_PREFIXES = ("ANTHROPIC_", "CLAUDE_CODE_USE_", "CLAUDE_CODE_GATEWAY_")',
     "DROPPED_ENV_PREFIXES = ()", "the credential decision leaks: a key overrides the login"),
    ("model_fallback_allowed", f"{PKG}/rival.py", '"CLAUDE_CODE_NO_MODEL_FALLBACK": "1"', '"X_UNUSED": "1"',
     "a refused request is silently re-sent on another model"),
    ("timeout_is_free", f"{PKG}/rival.py", "out.cost_usd_micros = budget  # the spend is unknown",
     "pass  # the spend is unknown", "a hanging run costs nothing, so retrying it is free"),
    ("timeout_leaves_children", f"{PKG}/rival.py", "os.killpg(proc.pid, signal.SIGKILL)", "proc.kill()",
     "the MCP server outlives a timed-out CLI"),
    ("toolbox_escapes_the_tree", f"{PKG}/rival.py", "if not target.is_relative_to(self.root):", "if False:",
     "the model reads files outside the extracted tree"),
    ("mcp_result_secret_scan_off", f"{PKG}/rival_mcp.py",
     "if secretscan.scan(text):  # file contents were checked whole", "if False:  # file contents were checked whole",
     "a tool result with a secret reaches the model"),
    ("mcp_accepts_invalid_verdicts", f"{PKG}/rival_mcp.py", "validate_verdict(args, self.box)", "None",
     "the model is never told its verdict is malformed (the real e2e failure)"),
    ("mcp_second_verdict_wins", f"{PKG}/rival_mcp.py", "if self.submitted:", "if False:",
     "a later submission replaces the first valid one"),
    ("outage_counted_against_the_push", f"{PKG}/decide.py", '.startswith("api_error")', '.startswith("api_errorX")',
     "an outage is recorded as a rejection and feeds not_learning"),
    ("missing_rival_ignored", f"{PKG}/decide.py", 'reasons.append(_reason("rival_missing"))', "pass",
     "a push is accepted without any rival result"),
    ("unsafe_archive_names_pass", f"{PKG}/treehash.py", '":" in name', "False",
     "a Windows-shaped member name reaches the filesystem"),
    ("unknown_config_keys_pass", f"{PKG}/config.py", "unknown = sorted(set(obj) - known)", "unknown = []",
     "removed or misspelled operator settings are silently ignored"),
    ("outage_never_parked", f"{PKG}/cli.py", 'int(prev.get("outage_count", 0)) >= OUTAGE_RETRY_LIMIT',
     'int(prev.get("outage_count", 0)) >= 10**9', "a dead token re-runs the whole pipeline every hour"),
    ("parked_forever", f"{PKG}/cli.py", "age < datetime.timedelta(days=1)", "True",
     "a parked commit is never tried again"),
    ("outage_count_never_grows", f"{PKG}/decide.py", 'state["outage_count"] += 1', 'state["outage_count"] += 0',
     "the outage memory never reaches its limit"),
    ("verdict_keeps_outage_count", f"{PKG}/decide.py", 'state["outage_sha"], state["outage_count"] = None, 0', "pass",
     "an old outage streak parks a commit that has since been judged"),
    ("outage_not_announced", f"{PKG}/cli.py", "if outage:  # the job stays green", "if False:  # the job stays green",
     "an outage leaves no trace in the job: the operator sees a green run and nothing else"),
    ("utf16_secret_passes", f"{PKG}/rival.py", 'or secretscan.scan(text.replace(chr(0), ""))', "",
     "a UTF-16 file carries a token past the scan"),
    ("api_key_source_unchecked", f"{PKG}/rival.py", 'if init.get("apiKeySource") != "none":', "if False:",
     "a run using an API key is accepted"),
    ("grep_hides_skipped_files", f"{PKG}/rival.py", 'if skipped else ""', 'if False else ""',
     "the model reads (no matches) for a file grep never opened"),
    ("interrupt_leaves_children", f"{PKG}/rival.py", "except BaseException:  # a timeout, Ctrl-C, SIGTERM",
     "except subprocess.TimeoutExpired:  # a timeout, Ctrl-C, SIGTERM",
     "Ctrl-C or SIGTERM leaves the CLI and its MCP server running and spending"),
    ("stream_split_on_unicode_lines", f"{PKG}/rival.py", "stdout.split(", "stdout.splitlines(",
     "a result text with U+2028 cuts the result event in two and the whole run is lost"),
    ("deadline_can_be_swallowed", f"{PKG}/rival_mcp.py", "class _Deadline(BaseException):", "class _Deadline(OSError):",
     "pathlib's directory walk swallows the signal's exception and the call runs without any limit"),
    ("secret_file_read_by_lines", f"{PKG}/rival.py", 'raise SecretWithheld("withheld: the file matches a secret pattern")',
     "pass", "a PEM body is returned by asking for line 2 onwards"),
    ("verdict_not_checked_for_canonical_json", f"{PKG}/rival.py", 'canon.canonical({"verdict": raw["verdict"], "attempts": clean})',
     "None", "a verdict the signed artifacts cannot hold crashes the job and loses the run's cost"),
    ("deep_json_kills_the_server", f"{PKG}/rival_mcp.py", "except (ValueError, RecursionError):", "except ValueError:",
     "one 10 000-level JSON line ends the session"),
    ("links_followed", f"{PKG}/rival.py", 'base.rglob("*") if p.is_file() and not p.is_symlink()',
     'base.rglob("*") if p.is_file()', "grep reads through a link out of the tree"),
    ("refutations_signed_by_position", f"{PKG}/decide.py", "reason['detail_sha256'][:12]", "reason['ref']",
     "three different defects in a row read as one rejection and stop the Founder"),
    ("test_output_republished", f"{PKG}/decide.py", 'output_tail=_redacted(t.get("output_tail"))', 'output_tail=t.get("output_tail")',
     "a secret printed by a failing test is published in the signed result"),
    ("unchanged_tree_polled_forever", f"{PKG}/decide.py", "elif evaluate:  # an unchanged tree", "elif False:  # an unchanged tree",
     "an empty commit is picked up again every hour"),
    ("vector_flake_blamed_on_founder", f"{PKG}/vectors.py", "for _ in range(2):", "for _ in range(1):",
     "a container the host killed under load is recorded as the Founder's failed vector"),
    ("not_learning_one_early", f"{PKG}/decide.py", "if n >= limit)", "if n >= limit - 1)",
     "the Founder is stopped after two identical rejections instead of three"),
    ("api_key_descriptor_reaches_the_cli", f"{PKG}/rival.py", '"CLAUDE_API_KEY",' + chr(10) + '                     "CLAUDE_CODE_API_KEY_FILE_DESCRIPTOR")',
     '"X_UNUSED")', "a key passed through a file descriptor overrides the login"),
    ("sigterm_not_ignored_during_the_kill", f"{PKG}/rival.py", "signal.signal(signal.SIGTERM, signal.SIG_IGN)  # a second", "pass  # a second",
     "a second SIGTERM interrupts the kill and leaves the CLI running"),
    ("second_communicate_unbounded", f"{PKG}/rival.py", "proc.communicate(timeout=CLI_KILL_WAIT_S)", "proc.communicate()",
     "a descendant in another session that holds the pipe keeps the run open after the kill"),
    ("verdict_check_without_deadline", f"{PKG}/rival_mcp.py", "                with _deadline(self.tool_timeout_s):" + chr(10) + "                    validate_verdict(args, self.box)",
     "                if True:" + chr(10) + "                    validate_verdict(args, self.box)",
     "a verdict the checker takes minutes over hangs the whole session"),
    ('secret_name_tail_unbounded', f"{PKG}/secretscan.py", '[A-Za-z0-9_]{0,80}', '[A-Za-z0-9_]*', 'a long run of keywords makes every scan quadratic and a line of a diff can stop the whole run'),
    ('jwt_boundary_is_the_alphabet', f"{PKG}/secretscan.py", '"jwt": re.compile(r"(?<![A-Za-z0-9_\\-])eyJ', '"jwt": re.compile(_L + r"eyJ', 'an eyJ-eyJ-... run starts a scan of the whole run at every eyJ'),
    ('json_key_quote_not_allowed', f"{PKG}/secretscan.py", '[\'\\"]?\\s*[:=]', '\\s*[:=]', 'a credential under a quoted JSON key is not found'),
    ('verdict_scanned_as_json', f"{PKG}/rival.py", 'secretscan.scan(chr(10).join(_texts(verdict["attempts"])))', 'secretscan.scan(json.dumps(verdict["attempts"]))', 'a key after a newline or an accented letter is written to rival.json'),
    ('non_utf8_name_reaches_json', f"{PKG}/cli.py", '    changed = [shown(p) for p in changed]\n', '', 'a file name that is not UTF-8 stops `pull` on every poll'),
    ('tar_error_escapes', f"{PKG}/treehash.py", '    except tarfile.TarError as exc:', '    except ZeroDivisionError as exc:', 'a corrupt archive raises tarfile.ReadError instead of TreeError'),
    ('sha_accepts_a_newline', f"{PKG}/state.py", 'SHA_RE = re.compile(r"^[0-9a-f]{40}\\Z")', 'SHA_RE = re.compile(r"^[0-9a-f]{40}$")', 'a state sha with a trailing newline is accepted'),
    ("failed_controls_blamed_on_the_founder", f"{PKG}/decide.py", 'broken = [c["id"] for c in controls if not c["ok"]]',
     "broken = []", "a runner whose own controls fail has its test output counted as the Founder's rejections"),
    ("docker_fault_clears_a_refutation", f"{PKG}/decide.py", 'any(r.get("runner_fault") for r in repro or [])', "False",
     "docker failing in the reproduction container means 'not reproduced' and the commit is accepted"),
    ("docker_fault_not_marked", f"{PKG}/reproduce.py", "res.exit_code == DOCKER_ERROR", "False",
     "the reproducer runner does not tell docker's failure from an absent defect"),
    ("budget_counts_against_the_founder", f"{PKG}/decide.py", 'if r["kind"] not in NOT_THE_FOUNDERS}', "}",
     "an exhausted budget stops the Founder as not learning"),
    ("unrun_reproducers_clear_a_refutation", f"{PKG}/decide.py", 'if rival.get("reproducer_count") and job_results.get("yeniden") != "success":',
     'if rival.get("reproducer_count") and job_results.get("yeniden") not in (None, "success", "skipped"):',
     "a refutation whose reproduction job was skipped is accepted"),
    ("bare_hex_threshold_dropped", f"{PKG}/secretscan.py", "[0-9a-f]{32,}", "[0-9a-f]{3,}",
     "short hex or plain numbers assigned to a token-named variable refuse innocent pushes"),
    ("brain_read_gets_an_identity_again", "seed/bootstrap/workflow/bootstrap.yml",
     "          GH_TOKEN: ${{ github.token }}\n        run: python3 -m snowball_bootstrap poll",
     "          GH_TOKEN: ${{ github.token }}\n          BRAIN" + "_TOKEN: ${{ github.token }}\n        run: python3 -m snowball_bootstrap poll",
     "an identity is handed to the brain read although the brain is public"),
    ("config_value_prints_what_nobody_reads", f"{PKG}/cli.py", "    output(image=boot.image)\n",
     "    output(image=boot.image, brain_branch=boot.brain_branch)\n",
     "a step output nobody reads stays behind and the workflow and the command drift apart"),
    ("setup_day_names_an_app_the_workflow_dropped", "spec/tohum/25-kurulum-gunu.md",
     "sır `CLAUDE_CODE_OAUTH_TOKEN` (operatörün",
     "değişken `READER" + "_APP_ID`, sırlar `READER" + "_APP_KEY` ve `CLAUDE_CODE_OAUTH_TOKEN` (operatörün",
     "the operator is told to configure an App that nothing uses"),
]


def run_mutant(index: int, mutant: tuple[str, str, str, str, str] | None) -> tuple[bool, str, float]:
    """Apply one mutant (or none: the baseline) to a fresh copy and run the unit tests there."""
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix=f"mutant-{index}-") as tmp:
        work = Path(tmp)
        ignore = shutil.ignore_patterns("__pycache__", "node_modules", ".git")
        shutil.copytree(ROOT / "seed", work / "seed", ignore=ignore)
        shutil.copytree(ROOT / "spec" / "tohum", work / "spec" / "tohum", ignore=ignore)
        if mutant is not None:
            _name, rel, old, new, _why = mutant
            target = work / rel
            text = target.read_text(encoding="utf-8")
            if text.count(old) != 1:
                return False, f"ANCHOR MISSING in {rel} (found {text.count(old)}x): update the mutant", 0.0
            target.write_text(text.replace(old, new), encoding="utf-8", newline="")
        boot = work / "seed" / "bootstrap"
        env = {"PATH": "/usr/local/bin:/usr/bin:/bin", "PYTHONDONTWRITEBYTECODE": "1", "PYTHONPATH": ".:tests",
               "HOME": str(work)}
        proc = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-f"], cwd=boot, env=env,
                              capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=900)
    output = proc.stdout + proc.stderr
    killers = [line.split(" ")[1] for line in output.splitlines() if line.startswith(("FAIL: ", "ERROR: "))]
    return proc.returncode != 0, (killers[0] if killers else "(no test named)"), time.monotonic() - started


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", help="run only the mutant with this name")
    parser.add_argument("--list", action="store_true", help="list the mutants and what each stands for")
    parser.add_argument("--shard", help="K/N: run every N-th mutant starting at K, so N containers can share the list")
    args = parser.parse_args()
    chosen = [(i, m) for i, m in enumerate(MUTANTS) if not args.only or m[0] == args.only]
    if args.shard:
        k, n = (int(part) for part in args.shard.split("/"))
        chosen = [(i, m) for i, m in chosen if i % n == k]
    if not chosen:
        print("no such mutant", file=sys.stderr)
        return 2
    if args.list:
        for _i, m in chosen:
            print(f"{m[0]:34} {m[4]}")
        return 0
    killed, detail, _ = run_mutant(-1, None)  # without this a failing environment makes every mutant "killed"
    if killed:
        print(f"the unmutated code already fails its tests ({detail}); fix that first", file=sys.stderr)
        return 2
    survivors = []
    for i, m in chosen:
        killed, detail, seconds = run_mutant(i, m)
        print(f"{'killed  ' if killed else 'SURVIVED'} {m[0]:34} {seconds:5.1f}s  {detail}", flush=True)
        if not killed:
            survivors.append(m[0])
    print(f"\n{len(chosen) - len(survivors)}/{len(chosen)} mutants killed")
    if survivors:
        print("not measured by any test:", ", ".join(survivors))
    return 1 if survivors else 0


if __name__ == "__main__":
    sys.exit(main())
