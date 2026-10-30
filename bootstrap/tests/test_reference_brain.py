"""The reference brain (`local/reference_brain/`) that the end-to-end run and the GitHub rehearsal push is real.

It is held to what the referee holds a Founder push to, minus Docker: its manifest passes the Stage 0 checks,
its own tests pass, the seed vectors of the micro-features it declares done pass through the real vector
runner, and its tests fail when its code is wrong (one mutant here; `local/mutate_brain.py` runs them all).
A stub here once claimed eighteen micro-features with import-only tests, and the real rival refuted it.

It also carries reference implementations of MF2-MF13 (`gate/`, `runner/`, `profile/`, `ledger/append.py`,
`ledger/anchor.py`, `target/`): implementation A, one of the two blind implementations every expected value of those
groups was checked with (E161). They are the evidence that the seed vectors pass on a correct implementation and fail
on broken ones; the brain does not declare them done. MF8-MF13's A calls this brain's MF2 (`gate.secrets`) and keeps its
own ledger helpers in `ledger/_strict.py`, beside this brain's MF1, which they do not replace. For MF2-MF7 the other, B,
is `local/blind_b/referee/` as it was written (from the cases without their expected values): the second computation
`29a` and `29d` ask for, run here again on every change of the seed.
"""

import json
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from snowball_bootstrap import manifest, stages, vectors
from snowball_bootstrap.container import RunResult

BOOT = Path(__file__).resolve().parents[1]
BRAIN = BOOT / "local" / "reference_brain"
BLIND_B = BOOT / "local" / "blind_b"
VECTORS = BOOT / "vectors"
sys.path.insert(0, str(BOOT / "local"))
import mutate_brain  # noqa: E402

DATA_MFS = tuple(range(2, 14))
DATA_GROUPS = ("secrets", "contained", "profile", "npmlock", "recipe", "diffguard", "k0map", "refs", "append", "root",
               "flaky", "cause")
B_MFS, B_GROUPS = DATA_MFS[:6], DATA_GROUPS[:6]  # B is in the repo for MF2-MF7 only


class LocalRunner:
    """The vector commands run on this machine instead of in a container: same cwd, stdin and /vec/ files."""

    def __init__(self, brain=BRAIN):
        self.brain = brain

    def run(self, cmd, *, cwd=".", stdin=b"", timeout_s):
        argv = [sys.executable if part == "python" else
                VECTORS.as_posix() + part[len("/vec"):] if part.startswith("/vec/") else part
                for part in shlex.split(cmd)]
        started = time.monotonic()
        proc = subprocess.run(argv, cwd=self.brain / cwd, input=stdin, capture_output=True, timeout=timeout_s,
                              check=False)
        return RunResult(proc.returncode, proc.stdout, proc.stderr, int((time.monotonic() - started) * 1000))


def seed_vectors():
    return json.loads((VECTORS / "vectors.json").read_text(encoding="utf-8"))


def run_cases(brain, ids):
    """The data runner on ``brain`` for the cases ``ids`` name (a ``.changed_input`` id names its case)."""
    wanted = {i.removesuffix(".changed_input") for i in ids}
    seed = seed_vectors()
    only = {g: dict(seed[g], cases=[c for c in seed[g]["cases"] if c["id"] in wanted]) for g in DATA_GROUPS}
    with tempfile.TemporaryDirectory() as tmp:
        Path(tmp, "vectors.json").write_text(json.dumps({g: v for g, v in only.items() if v["cases"]}),
                                             encoding="utf-8")
        return vectors.run_vectors(LocalRunner(brain), Path(tmp), DATA_MFS)


# One break per way of getting a group wrong that a case is there to catch (its `purpose` in `vectors.json`, its line
# in `29f`/`29g`): (name, module under referee/, text found once, replacement, the result ids that must turn red).
BS = chr(92)
BREAKS = [
    ("github_format_missing", "gate/secrets.py", "_FORMATS = (_GITHUB, _AWS)", "_FORMATS = (_AWS,)",
     ["secrets.diff_added_line", "secrets.prompt"]),
    ("diff_added_lines_only", "gate/secrets.py",
     'lines = scan_rows(text) if kind == "row" else scan_text(text)',
     'lines = scan_rows(text) if kind == "row" else scan_text(text if kind == "prompt" else "' + BS + 'n".join('
     'l if l.startswith("+") else "" for l in text.split("' + BS + 'n")))',
     ["secrets.diff_context_line"]),
    ("row_scanned_raw", "gate/secrets.py",
     "if any(next(_match_starts(s), None) is not None for s in _strings(row)):",
     "if next(_match_starts(line), None) is not None:", ["secrets.row_json_escape"]),
    ("prompt_not_scanned", "gate/secrets.py",
     'lines = scan_rows(text) if kind == "row" else scan_text(text)',
     'lines = scan_rows(text) if kind == "row" else (set() if kind == "prompt" else scan_text(text))',
     ["secrets.prompt", "secrets.glued_token", "secrets.prompt_clean.changed_input"]),
    ("prompt_never_clean", "gate/secrets.py", "    if lines:", '    if lines or kind == "prompt":',
     ["secrets.prompt_clean"]),
    ("github_word_boundary", "gate/secrets.py", '_GITHUB = re.compile(r"gh[pousr]_[A-Za-z0-9]{36}")',
     '_GITHUB = re.compile(r"' + BS + 'bgh[pousr]_[A-Za-z0-9]{36}' + BS + 'b")', ["secrets.glued_token"]),
    ("aws_fifteen_characters", "gate/secrets.py", "[A-Z0-9]{16}(?![A-Za-z0-9])", "[A-Z0-9]{15}(?![A-Za-z0-9])",
     ["secrets.clean_near_miss"]),
    ("bad_row_skipped", "gate/secrets.py", 'raise Unusable(f"line {number}: not JSON") from exc', "continue",
     ["secrets.row_unusable_fails_closed"]),

    ("network_left_default", "runner/contained.py", '"--network", "none",', "",
     ["contained.argv_baseline", "contained.argv_second_request"]),
    ("artefacts_writable", "runner/contained.py", 'f"type=bind,src={path},dst={path},readonly"',
     'f"type=bind,src={path},dst={path}"', ["contained.argv_baseline"]),
    ("memory_limit_constant", "runner/contained.py", '"--memory", str(mem["value"]),', '"--memory", "536870912",',
     ["contained.argv_baseline.changed_input", "contained.argv_second_request"]),
    ("uid_constant", "runner/contained.py", '"--user", str(uid),', '"--user", "1001",',
     ["contained.argv_second_request"]),
    ("unpinned_image_accepted", "runner/contained.py", "if not _PINNED.fullmatch(image):", "if False:",
     ["contained.refuse_unpinned_image"]),
    ("actions_env_stripped", "runner/contained.py", 'raise Refused("actions_env")',
     'env = {k: v for k, v in env.items() if not k.startswith("ACTIONS_")}', ["contained.refuse_actions_env"]),
    ("docker_socket_mounted", "runner/contained.py",
     "if any(_exposes_docker_socket(p) for p in [worktree, outdir, *artefacts]):", "if False:",
     ["contained.refuse_docker_socket"]),
    ("services_accepted", "runner/contained.py", "    if services:", "    if False:", ["contained.refuse_services"]),
    ("memory_limit_defaulted", "runner/contained.py", 'raise Refused("container_mem_bytes_missing")',
     'mem = {"value": 536870912}', ["contained.refuse_missing_mem_limit"]),

    ("agent_config_case_sensitive", "profile/derive.py",
     "return any(p.lower() in AGENT_DIRS for p in parts) or parts[-1].lower() in AGENT_FILES",
     "return any(p in AGENT_DIRS for p in parts) or parts[-1] in AGENT_FILES",
     ["profile.agent_config_case_insensitive"]),
    ("operator_exclusions_ignored", "profile/derive.py",
     "return is_agent_config(path) or any(covers(e, path) for e in excluded_paths)", "return is_agent_config(path)",
     ["profile.operator_excluded_paths"]),
    ("security_keyword_in_the_file_name_only", "profile/derive.py",
     "any(k in f.lower() for k in keywords)", "any(k in posixpath.basename(f).lower() for k in keywords)",
     ["profile.security_keyword_substring"]),
    ("unit_candidates_sorted", "profile/derive.py", '"unit_candidates": units,', '"unit_candidates": sorted(units),',
     ["profile.unit_candidates_order_and_filter"]),
    ("narrowing_accepted", "profile/derive.py", "if not set(derived[key]) <= set(prop[key]):", "if False:",
     ["profile.reject_narrowed_excluded"]),
    ("languages_unchecked", "profile/derive.py", 'if set(prop["languages"]) != set(derived["languages"]):',
     "if False:", ["profile.reject_different_languages"]),

    ("integrity_unchecked", "runner/deps_npm.py", 'if digest not in _sha512_values(entry.get("integrity")):',
     "if False:", ["npmlock.integrity_good_and_one_byte.changed_input"]),
    ("integrity_of_the_unpacked_tar", "runner/deps_npm.py", "hashlib.sha512(tgz)",
     "hashlib.sha512(zlib.decompress(tgz, 47))", ["npmlock.integrity_good_and_one_byte"]),
    ("install_script_from_the_lock_only", "runner/deps_npm.py",
     "(isinstance(scripts, dict) and any(h in scripts for h in INSTALL_HOOKS))", "False",
     ["npmlock.install_script_unmarked"]),
    ("registry_prefix_without_its_slash", "runner/deps_npm.py",
     "if not any(resolved.startswith(prefix) for prefix in egress):",
     'if not any(resolved.startswith(prefix.rstrip("/")) for prefix in egress):', ["npmlock.registry_not_allowed"]),
    ("git_dependency_fetched", "runner/deps_npm.py", 'if resolved.startswith(("git+", "git:", "github:", "git@")):',
     "if False:", ["npmlock.git_dependency"]),
    ("file_dependency_fetched", "runner/deps_npm.py", 'resolved.startswith("file:") or ', "",
     ["npmlock.file_dependency"]),
    ("license_from_the_lock", "runner/deps_npm.py", '"license": license_ if isinstance(license_, str) else None}',
     '"license": entry.get("license")}', ["npmlock.license_from_tarball"]),
    ("address_in_lock_order", "runner/deps_npm.py", 'fetched.sort(key=lambda r: r["path"])', "pass",
     ["npmlock.same_lock_same_address"]),

    ("services_unchecked", "profile/unit_verify.py", 'if recipe.get("services") != []:', "if False:",
     ["recipe.good.changed_input"]),
    ("image_unchecked", "profile/unit_verify.py", "if not (isinstance(image, str) and PINNED.fullmatch(image)):",
     "if False:", ["recipe.image_tag_only", "recipe.image_digest_malformed"]),
    ("digest_length_loose", "profile/unit_verify.py", "[0-9a-f]{64}", "[0-9a-f]{63,64}",
     ["recipe.image_digest_malformed"]),
    ("unit_dir_unchecked", "profile/unit_verify.py",
     "if not (isinstance(path, str) and any(covers(e, path) for e in inputs)):", "if False:",
     ["recipe.inputs_missing_unit_dir"]),
    ("input_agent_config_case_sensitive", "profile/unit_verify.py",
     "return any(p.lower() in AGENT_DIRS for p in parts) or parts[-1].lower() in AGENT_FILES",
     "return any(p in AGENT_DIRS for p in parts) or parts[-1] in AGENT_FILES", ["recipe.inputs_agent_config"]),
    ("absolute_input_accepted", "profile/unit_verify.py", 'return entry.startswith("/") or ', "return ",
     ["recipe.inputs_not_plain"]),
    ("limit_keys_unchecked", "profile/unit_verify.py", "if key not in operating:", "if False:",
     ["recipe.limit_key_unknown"]),
    ("empty_command_accepted", "profile/unit_verify.py", "isinstance(cmd, list) and cmd and all(",
     "isinstance(cmd, list) and all(", ["recipe.test_cmd_empty"]),
    ("test_cmd_only", "profile/unit_verify.py", 'CMD_FIELDS = ("lint_cmd", "test_cmd", "affected_test_cmd")',
     'CMD_FIELDS = ("test_cmd",)', ["recipe.cmd_entries"]),

    ("coverage_without_the_slash_rule", "gate/diffguard.py", 'base = entry.rstrip("/")', "base = entry",
     ["diffguard.inside_inputs"]),
    ("symlink_unchecked", "gate/diffguard.py", 'if "120000" in modes:', "if False:", ["diffguard.symlink"]),
    ("submodule_unchecked", "gate/diffguard.py", 'if "160000" in modes:', "if False:", ["diffguard.submodule"]),
    ("dotdot_unchecked", "gate/diffguard.py", 'if path.startswith("/") or ".." in path.split("/"):',
     'if path.startswith("/"):', ["diffguard.dotdot_path"]),
    ("diff_agent_config_case_sensitive", "gate/diffguard.py",
     "return any(p.lower() in AGENT_DIRS for p in parts) or parts[-1].lower() in AGENT_FILES",
     "return any(p in AGENT_DIRS for p in parts) or parts[-1] in AGENT_FILES",
     ["diffguard.agent_config_case_insensitive"]),
    ("security_paths_unchecked", "gate/diffguard.py",
     'if any(covers(e, path) for e in profile["security_paths"]):', "if False:", ["diffguard.security_path"]),
    ("gitattributes_unchecked", "gate/diffguard.py", 'if base == ".gitattributes":', "if False:",
     ["diffguard.config_manifest_lock_gitattributes"]),
    ("excluded_dirs_unchecked", "gate/diffguard.py",
     'if any(covers(e, path) for e in profile["excluded_dirs"]):', "if False:", ["diffguard.excluded_path"]),
    ("first_reason_only", "gate/diffguard.py", 'return {f"{reason}:{path}" for reason in found}',
     'return {f"{reason}:{path}" for reason in sorted(found)[:1]}', ["diffguard.every_reason"]),

    ("shift_counts_every_hunk", "gate/check.py",
     'ends_before = (h["a"] + h["b"] - 1 < line) if h["b"] > 0 else (h["a"] < line)', "ends_before = True",
     ["k0map.map_shift"]),
    ("inside_a_hunk_like_any_line", "gate/check.py", 'if h["b"] > 0 and h["a"] <= line <= h["a"] + h["b"] - 1:',
     "if False:", ["k0map.map_inside_hunk", "k0map.not_distinguished"]),
    ("inside_a_hunk_shifted_by_its_net", "gate/check.py", 'return [h["c"], h["c"] + h["d"] - 1] if h["d"] > 0 else []',
     'return [line + h["d"] - h["b"]] * 2', ["k0map.map_inside_hunk", "k0map.not_distinguished"]),
    ("inside_a_hunk_its_position_there", "gate/check.py", 'return [h["c"], h["c"] + h["d"] - 1] if h["d"] > 0 else []',
     'return [line - h["a"] + h["c"]] * 2', ["k0map.map_inside_hunk", "k0map.not_distinguished"]),
    ("other_paths_hunks_shift", "gate/check.py", "hunks = hunks_of(parse_diff(_diff_text(argv[0])), argv[1])",
     'hunks = [h for blk in parse_diff(_diff_text(argv[0])) for h in blk["hunks"]]', ["k0map.map_shift"]),
    ("hash_manifest_unchecked", "gate/check.py",
     "if data[name] is None or manifest.get(name) != hashlib.sha256(data[name]).hexdigest():", "if data[name] is None:",
     ["k0map.artefact_hash_mismatch", "k0map.merge.changed_input"]),
    ("ratchet_per_rule", "gate/check.py", 'return {run["tool"]: len(run["violations"])}',
     'return {(run["tool"], r): [v["rule_id"] for v in run["violations"]].count(r) '
     'for r in {v["rule_id"] for v in run["violations"]}}', ["k0map.merge"]),
    ("distinguished_off_the_mapped_range", "gate/check.py", 'span[0] <= v["line"] <= span[1]', "True",
     ["k0map.merge"]),
    ("target_matched_without_its_line", "gate/check.py", ' and v["line"] == finding["line"]), None)', "), None)",
     ["k0map.target_not_found"]),
    ("runs_compared_as_json", "gate/check.py", "if runs is not None and len(set(runs[0])) != 1:",
     "if runs is not None and len({repr(loads(line)) for line in runs[0]}) != 1:", ["k0map.tool_nondeterministic"]),
    ("fix_range_from_the_finding", "gate/check.py", 'if _out_of_scope(blocks, target["path"], target["fix"]):',
     'if _out_of_scope(blocks, target["path"], finding["fix_range"]):', ["k0map.scope_violation"]),
    ("decide_first_reason_only", "gate/check.py", "return sorted(reasons)", "return sorted(reasons)[:1]",
     ["k0map.ratchet_and_broken_test", "k0map.fail_closed_controls"]),
    ("ratchet_unchecked", "gate/check.py",
     "if any(count > before.get(tool, 0) for tool, count in after.items()):", "if False:",
     ["k0map.ratchet_and_broken_test"]),
    ("red_control_unchecked", "gate/check.py", 'if checks["red_control"] == "pass":', "if False:",
     ["k0map.red_control_green"]),
    ("missing_merge_paused_reads_false", "gate/check.py", 'if request["control"].get("merge_paused") is not False:',
     'if request["control"].get("merge_paused", False) is not False:', ["k0map.fail_closed_controls"]),
    ("zero_tests_green", "gate/check.py", 'if not checks["tests"]:', "if False:", ["k0map.fail_closed_controls"]),
    ("open_sentinel_ignored", "gate/check.py", 'if request["unfinished_sentinels"]:', "if False:",
     ["k0map.fail_closed_controls"]),
    # E236: pure insertions (b = 0) and pure deletions (d = 0), and the added line's edges of the fix range
    ("insertion_ends_at_its_line", "gate/check.py", 'else (h["a"] < line)', 'else (h["a"] <= line)',
     ["k0map.map_insertion_point", "k0map.insertion_not_distinguished"]),
    ("insertions_never_shift", "gate/check.py", 'else (h["a"] < line)', "else False", ["k0map.map_after_pure_hunks"]),
    ("deleted_line_on_the_line_before_the_gap", "gate/check.py",
     'return [h["c"], h["c"] + h["d"] - 1] if h["d"] > 0 else []',
     'return [h["c"], h["c"] + h["d"] - 1] if h["d"] > 0 else [h["c"], h["c"]]', ["k0map.map_deleted_line"]),
    ("deleted_line_an_inverted_range", "gate/check.py", 'return [h["c"], h["c"] + h["d"] - 1] if h["d"] > 0 else []',
     'return [h["c"], h["c"] + h["d"] - 1]', ["k0map.map_deleted_line"]),
    ("insertion_based_at_its_line_a", "gate/check.py", 'base = h["a"] if h["b"] > 0 else h["a"] + 1',
     'base = h["a"]', ["k0map.insertion_past_fix"]),
    ("added_line_two_past_the_fix", "gate/check.py", 'elif tag == "+" and not start <= base <= end + 1:',
     'elif tag == "+" and not start <= base <= end + 2:', ["k0map.insertion_past_fix"]),
    # E237: every koş file's hash, both run files' bytes
    ("only_the_base_runs_hash_checked", "gate/check.py", "if data[name] is None or manifest.get(name) != hashlib",
     'if data[name] is None or name == "base.jsonl" and manifest.get(name) != hashlib',
     ["k0map.forged_candidate_run", "k0map.forged_checks"]),
    ("candidate_runs_hash_unchecked", "gate/check.py", "if data[name] is None or manifest.get(name) != hashlib",
     'if data[name] is None or name != "cand.jsonl" and manifest.get(name) != hashlib', ["k0map.forged_candidate_run"]),
    ("checks_hash_unchecked", "gate/check.py", "if data[name] is None or manifest.get(name) != hashlib",
     'if data[name] is None or name != "checks.json" and manifest.get(name) != hashlib', ["k0map.forged_checks"]),
    ("base_runs_never_compared", "gate/check.py", "for runs in (base, cand):", "for runs in (cand,):",
     ["k0map.base_nondeterministic"]),

    ("second_parent_tree", "target/write.py", 'first = _field(parents[0], "sha")', 'first = _field(parents[-1], "sha")',
     ["refs.revert_first_parent_tree", "refs.revert_first_parent_tree.changed_input"]),
    ("merge_commits_own_tree", "target/write.py",
     'tree = _field(api.call("GET", f"{base}/git/commits/{first}"), "tree", "sha")', 'tree = _field(merge, "tree", "sha")',
     ["refs.revert_first_parent_tree"]),
    ("refs_from_the_recorded_response", "target/write.py",
     'api.call("POST", f"{base}/git/refs", {"ref": ref, "sha": created})' + chr(10) + "        api.refs.append(ref)",
     'api.refs.append(_field(api.call("POST", f"{base}/git/refs", {"ref": ref, "sha": created}), "ref"))',
     ["refs.revert_first_parent_tree"]),
    ("brain_prefix_unchecked", "target/write.py", "if not isinstance(ref, str) or not ref.startswith(BRAIN):",
     "if not isinstance(ref, str):", ["refs.refuse_main", "refs.refuse_prefix_lookalike", "refs.refuse_merge_into_main",
                                      "refs.refuse_pr_into_main"]),
    ("brain_prefix_without_its_slash", "target/write.py", 'BRAIN = "refs/heads/brain/"', 'BRAIN = "refs/heads/brain"',
     ["refs.refuse_prefix_lookalike"]),
    ("dotdot_component_allowed", "target/write.py",
     'return all(part not in ("", ".", "..") for part in ref[len("refs/heads/"):].split("/"))', "return True",
     ["refs.refuse_dotdot"]),
    ("merge_base_unchecked", "target/write.py",
     'if not (ref_allowed("refs/heads/" + head) and ref_allowed("refs/heads/" + base_ref)):',
     'if not ref_allowed("refs/heads/" + head):', ["refs.refuse_merge_into_main"]),
    ("pr_base_unchecked", "target/write.py", "if not (ref_allowed(head) and ref_allowed(base_ref)):",
     "if not ref_allowed(head):", ["refs.refuse_pr_into_main"]),
    ("update_forces", "target/write.py", '{"sha": sha, "force": False}', '{"sha": sha, "force": True}',
     ["refs.update_never_forces"]),  # E240

    ("commit_per_row", "ledger/append.py", "writer.commit(body + tail)",
     "for _row in stored:" + chr(10) + "            writer.commit(body + tail)", ["append.cycle_one_commit"]),
    ("new_rows_not_chained_to_each_other", "ledger/append.py", 'prev = new["row_hash"]', "pass",
     ["append.cycle_one_commit"]),
    ("chained_onto_the_previous_version", "ledger/append.py",
     'prev = cur_rows[-1]["row_hash"] if cur_rows else chain.ZERO',
     'prev = chain.loads(chain.split_lines(previous_bytes)[-1])["row_hash"] if previous_bytes else chain.ZERO',
     ["append.chains_onto_current_tip"]),
    ("chain_unverified", "ledger/append.py", "broken = chain.first_broken(cur_rows)", "broken = None",
     ["append.refuse_broken_tip"]),
    ("append_only_unchecked", "ledger/append.py",
     "moved = chain.first_not_in_place(chain.split_lines(previous_bytes), chain.split_lines(ledger_bytes))",
     "moved = None", ["append.refuse_rewritten_history", "append.refuse_reserialized_row"]),
    # E238: a ledger that is not JSON Lines is a broken chain, and step (1) comes before the request is read
    ("unparsable_ledger_unusable_input", "ledger/append.py", '_refused(True, f"ledger is not JSON Lines: {exc}")',
     "raise", ["append.refuse_unparsable_ledger"]),
    ("request_read_before_the_chain", "ledger/append.py",
     "cur_rows = _verified(ledger_bytes, previous_bytes)  # (1) first: tamper evidence stops hard whatever is asked"
     + chr(10) + "    rows = _request(stdin, cur_rows)",
     "rows = _request(stdin, [])" + chr(10) + "    cur_rows = _verified(ledger_bytes, previous_bytes)",
     ["append.refuse_broken_chain_first"]),
    ("append_only_canonical", "ledger/_strict.py", "if index >= len(current) or current[index] != line:",
     "if index >= len(current) or canonical(loads(current[index])) != canonical(loads(line)):",
     ["append.refuse_reserialized_row"]),
    ("new_rows_scanned_raw", "ledger/append.py", "if any(secrets.scan_rows(json.dumps(row)) for row in rows):",
     'if secrets.scan_text(stdin.decode("utf-8")):', ["append.refuse_secret_row"]),
    ("proposed_by_trust_kept", "ledger/append.py", 'new["trust"] = "inferred"', "pass",
     ["append.proposed_by_stored_inferred"]),
    ("previous_version_ignored", "ledger/chain.py", "problem = _not_append_only(rows, earlier)", "problem = None",
     ["append.chain_previous_rewrite", "append.chain_previous_truncated"]),
    ("truncation_allowed", "ledger/chain.py", 'return before["row_id"], "the file lost this row"', "return None",
     ["append.chain_previous_truncated"]),

    ("first_row_of_each_part", "ledger/anchor.py", "tips[part] = row_hash", "tips.setdefault(part, row_hash)",
     ["root.part_tips", "root.verify_good"]),
    ("root_not_canonical", "ledger/anchor.py", "hashlib.sha256(chain.canonical(tips)).hexdigest()",
     "hashlib.sha256(json.dumps(tips).encode()).hexdigest()", ["root.part_tips", "root.verify_good"]),
    ("entry_hash_is_the_uuid", "ledger/anchor.py", '"hash": request["root"]', '"hash": signer["uuid"]',
     ["root.anchor_signs_root"]),
    ("signs_a_fixed_root", "ledger/anchor.py", '"hash": request["root"]',
     '"hash": "7381e3007f21fc75b1968fb12c20c35760b5368274d3eeae15275d735ae93a73"',
     ["root.anchor_signs_root.changed_input"]),
    ("unsignable_passes", "ledger/anchor.py", 'if not signer["available"]:', "if False:", ["root.unsignable_hard_stop"]),
    ("ledger_root_unchecked", "ledger/anchor.py", 'if root != last["root"]:', "if False:", ["root.verify_tip_moved"]),
    ("identity_unpinned", "ledger/anchor.py", 'if entry["identity"] != pin["identity"]:', "if False:",
     ["root.verify_identity_pin"]),
    ("entry_hash_unchecked", "ledger/anchor.py", 'if entry["hash"] != last["root"]:', "if False:",
     ["root.verify_entry_other_root"]),
    ("missing_entry_passes", "ledger/anchor.py", 'reasons.append("entry_missing")', "pass",
     ["root.verify_entry_missing"]),

    ("zero_tests_first_run_green", "gate/sentinel.py", 'if first["results"] and not _failed(first):',
     "if not _failed(first):", ["flaky.green_first_run.changed_input"]),
    ("red_on_the_first_run", "gate/sentinel.py", "if len(runs) < CONSIDERED:", "if False:",
     ["flaky.one_red_run_never_reverts"]),
    ("red_on_any_failure", "gate/sentinel.py", "red = sorted(t for t in ever if all(t in f for f in failed))",
     "red = sorted(ever)", ["flaky.red_three_reruns.changed_input", "flaky.per_test_rule"]),
    ("never_red", "gate/sentinel.py", 'verdict = "red" if red or no_results else "flaky"', 'verdict = "flaky"',
     ["flaky.red_three_reruns", "flaky.per_test_rule"]),
    ("decided_after_two_reruns", "gate/sentinel.py", "CONSIDERED = 4", "CONSIDERED = 3",
     ["flaky.two_reruns_rerun"]),  # E239: 3/3 is the first run plus three reruns (29j's choice)

    ("impact_ignored", "gate/revert.py", 'if any(test in impact for test in signals["red_tests"]):', "if False:",
     ["cause.test_regression"]),
    ("outside_impact_called_regression", "gate/revert.py", 'return "impact_miss"', 'return "test_regression"',
     ["cause.impact_miss"]),
    ("tests_before_build", "gate/revert.py", 'if signals["build_ok"] is False:',
     'if signals["build_ok"] is False and not signals["red_tests"]:', ["cause.build_break_first"]),
    ("lint_unchecked", "gate/revert.py", 'if any(t["after"] > t["before"] for t in signals["lint"].values()):',
     "if False:", ["cause.lint_regression", "cause.lint_per_tool"]),
    ("lint_summed_over_tools", "gate/revert.py", 'if any(t["after"] > t["before"] for t in signals["lint"].values()):',
     'if sum(t["after"] for t in signals["lint"].values()) > sum(t["before"] for t in signals["lint"].values()):',
     ["cause.lint_per_tool"]),
    ("no_unknown", "gate/revert.py", 'return "unknown"', 'return "impact_miss"', ["cause.unknown"]),
]


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
        self.assertEqual(stages.load(0).groups_of(done), ("chain",))
        self.assertEqual(vectors.missing_groups(VECTORS, done, stages.load(0)), [])
        results = vectors.run_vectors(LocalRunner(), VECTORS, done)
        self.assertEqual(len(results), 6, results)
        self.assertEqual([r for r in results if not r["ok"]], [])

    def test_its_tests_fail_without_its_module(self):
        """Module-less red (`asama-0/14`): MF1's tests, run on its tree without `referee/ledger/chain.py`, fail."""
        module = stages.load(0).feature(1).module
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp) / "referee"
            shutil.copytree(BRAIN / "referee", work, ignore=shutil.ignore_patterns("__pycache__"))
            (work / module).unlink()
            code, _failed = mutate_brain.run_tests(work)
        self.assertNotEqual(code, 0)

    def test_every_brain_mutant_still_applies(self):
        text = (BRAIN / "referee" / mutate_brain.TARGET).read_text(encoding="utf-8")
        for name, old, _new, _why in mutate_brain.MUTANTS:
            self.assertEqual(text.count(old), 1, f"{name}: its anchor must occur exactly once in the brain")

    def test_its_tests_catch_the_bug_the_first_rehearsal_found(self):
        mutant = next(m for m in mutate_brain.MUTANTS if m[0] == "earlier_file_ignored")
        killed, detail, _ = mutate_brain.run_mutant(mutant)
        self.assertTrue(killed, detail)


class SeedVectorsOnReferenceImplementationsTest(unittest.TestCase):
    """MF2-MF13's seed vectors (E161) through the real data runner, on correct and on broken implementations."""

    def test_every_new_group_is_green_on_the_reference_implementations(self):
        seed = seed_vectors()
        # MF10 also owns `chain` (MF1's own judge); the brain's MF1 answers it, so it runs here too.
        self.assertEqual(stages.load(0).groups_of(DATA_MFS), DATA_GROUPS[:8] + ("chain",) + DATA_GROUPS[8:])
        self.assertEqual(vectors.missing_groups(VECTORS, DATA_MFS, stages.load(0)), [])
        results = vectors.run_vectors(LocalRunner(), VECTORS, DATA_MFS)
        cases = [c["id"] for g in DATA_GROUPS for c in seed[g]["cases"]]
        data = [r for r in results if not r["id"].startswith("chain.")]
        self.assertEqual([r["id"] for r in data], [i + s for i in cases for s in ("", ".changed_input")])
        self.assertEqual((len(data), len(results)), (204, 210))  # MF2-MF7 92, MF8-MF13 112; `chain` 6
        self.assertEqual([(r["id"], r["detail"]) for r in results if not r["ok"]], [])
        self.assertEqual(brain_manifest().done_mf, (1,))  # reference implementations, not declared done

    def test_every_new_group_is_green_on_the_second_blind_implementation_too(self):
        """`29a`, `29d`: every expected value is computed twice, independently. B is kept so the second computation can
        be run again (a changed fixture or case is checked on both), not only claimed (E161). MF8-MF13's B is not in
        the repo (E233): their second computation is the workflow's record, not run here."""
        self.assertEqual(stages.load(0).groups_of(B_MFS), B_GROUPS)
        modules = sorted(p.relative_to(BLIND_B / "referee").as_posix() for p in (BLIND_B / "referee").rglob("*.py"))
        for feature in B_MFS:
            self.assertIn(stages.load(0).feature(feature).module, modules)
        for rel in modules:  # its own code, not a copy of A's
            a = BRAIN / "referee" / rel
            self.assertFalse(a.exists() and a.read_bytes() == (BLIND_B / "referee" / rel).read_bytes(), rel)
        results = vectors.run_vectors(LocalRunner(BLIND_B), VECTORS, B_MFS)
        self.assertEqual(len(results), 92)
        self.assertEqual([(r["id"], r["detail"]) for r in results if not r["ok"]], [])

    def test_no_profile_case_decides_what_the_operator_has_not(self):
        """E194: `tohum/14:15-17`, `01b` and test 19 (`asama-0/09`) reject every proposal that differs from the derivation;
        `14:52` and `30d` let a proposal widen. Until the operator aligns them, an implementation of either reading passes
        the seed: A turned into the general reading (any difference in a path list rejected) stays green."""
        ids = [c["id"] + s for c in seed_vectors()["profile"]["cases"] for s in ("", ".changed_input")]
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            shutil.copytree(BRAIN / "referee", work / "referee", ignore=shutil.ignore_patterns("__pycache__"))
            target = work / "referee" / "profile" / "derive.py"
            text = target.read_text(encoding="utf-8")
            only_narrowing = "if not set(derived[key]) <= set(prop[key]):"
            self.assertEqual(text.count(only_narrowing), 1)
            target.write_text(text.replace(only_narrowing, "if set(derived[key]) != set(prop[key]):"),
                              encoding="utf-8", newline="")
            results = run_cases(work, ids)
        self.assertEqual(len(results), len(ids))
        self.assertEqual([(r["id"], r["detail"]) for r in results if not r["ok"]], [])

    def test_its_profile_package_does_not_shadow_the_standard_library_here(self):
        """E191: a test module that put the brain's `referee/` first on `sys.path` made `import cProfile` fail for
        every later test in the process (the brain's `profile/` package won over the standard library's)."""
        import importlib.machinery
        import test_security_ledger  # noqa: F401  (it adds the brain's referee/ to sys.path)
        found = importlib.machinery.PathFinder.find_spec("profile", sys.path)  # what an import would load now
        self.assertNotIn("reference_brain", (found.origin or "") if found else "")

    def test_every_case_turns_red_on_an_implementation_broken_the_way_it_targets(self):
        seed = seed_vectors()
        every = {c["id"] for g in DATA_GROUPS for c in seed[g]["cases"]}
        self.assertEqual({i.removesuffix(".changed_input") for b in BREAKS for i in b[4]}, every)
        self.assertEqual(len({b[0] for b in BREAKS}), len(BREAKS))
        for name, rel, old, new, ids in BREAKS:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as tmp:
                work = Path(tmp)
                shutil.copytree(BRAIN / "referee", work / "referee", ignore=shutil.ignore_patterns("__pycache__"))
                target = work / "referee" / rel
                text = target.read_text(encoding="utf-8")
                self.assertEqual(text.count(old), 1, f"{name}: its anchor must occur exactly once in {rel}")
                broken = text.replace(old, new)
                compile(broken, rel, "exec")  # a wrong implementation, not one that cannot start
                target.write_text(broken, encoding="utf-8", newline="")
                results = {r["id"]: r for r in run_cases(work, ids)}
                stayed = sorted(i for i in ids if results[i]["ok"])
                self.assertEqual(stayed, [], f"{name}: these stayed green")
                silent = sorted(i for i in ids if not results[i]["detail"].startswith("got "))
                self.assertEqual(silent, [], f"{name}: red because it gave no answer, not a wrong one")


if __name__ == "__main__":
    unittest.main()
