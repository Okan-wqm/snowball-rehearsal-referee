"""The reference brain (`local/reference_brain/`) that the end-to-end run and the GitHub rehearsal push is real.

It is held to what the referee holds a Founder push to, minus Docker: its manifest passes the Stage 0 checks,
its own tests pass, the seed vectors of the micro-features it declares done pass through the real vector
runner, and its tests fail when its code is wrong (one mutant here; `local/mutate_brain.py` runs them all).
A stub here once claimed eighteen micro-features with import-only tests, and the real rival refuted it.

It also carries reference implementations of MF2-MF7 (`gate/`, `runner/`, `profile/`): implementation A, one of the
two blind implementations every expected value of those groups was checked with (E161). They are the evidence that the
seed vectors pass on a correct implementation and fail on broken ones; the brain does not declare them done. The other,
B, is `local/blind_b/referee/` as it was written (from the cases without their expected values): the second
computation `29a` and `29d` ask for, run here again on every change of the seed.
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

DATA_MFS = (2, 3, 4, 5, 6, 7)
DATA_GROUPS = ("secrets", "contained", "profile", "npmlock", "recipe", "diffguard")


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
    """MF2-MF7's seed vectors (E161) through the real data runner, on correct and on broken implementations."""

    def test_every_new_group_is_green_on_the_reference_implementations(self):
        seed = seed_vectors()
        self.assertEqual(stages.load(0).groups_of(DATA_MFS), DATA_GROUPS)
        self.assertEqual(vectors.missing_groups(VECTORS, DATA_MFS, stages.load(0)), [])
        results = vectors.run_vectors(LocalRunner(), VECTORS, DATA_MFS)
        cases = [c["id"] for g in DATA_GROUPS for c in seed[g]["cases"]]
        self.assertEqual([r["id"] for r in results], [i + s for i in cases for s in ("", ".changed_input")])
        self.assertEqual(len(results), 92)
        self.assertEqual([r for r in results if not r["ok"]], [])
        self.assertEqual(brain_manifest().done_mf, (1,))  # reference implementations, not declared done

    def test_every_new_group_is_green_on_the_second_blind_implementation_too(self):
        """`29a`, `29d`: every expected value is computed twice, independently. B is kept so the second computation can
        be run again (a changed fixture or case is checked on both), not only claimed (E161)."""
        modules = sorted(p.relative_to(BLIND_B / "referee").as_posix() for p in (BLIND_B / "referee").rglob("*.py"))
        for feature in DATA_MFS:
            self.assertIn(stages.load(0).feature(feature).module, modules)
        for rel in modules:  # its own code, not a copy of A's
            a = BRAIN / "referee" / rel
            self.assertFalse(a.exists() and a.read_bytes() == (BLIND_B / "referee" / rel).read_bytes(), rel)
        results = vectors.run_vectors(LocalRunner(BLIND_B), VECTORS, DATA_MFS)
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
