import io
import json
import re
import tarfile
import tempfile
import time
import unittest
import zipfile
from pathlib import Path

from snowball_bootstrap import canon, licenses, secretscan
from snowball_bootstrap.classify import classify, spec_stage_dirs
from snowball_bootstrap.config import ConfigError, load_bootstrap
from snowball_bootstrap.controls import run_controls
from snowball_bootstrap.manifest import ManifestError, check_stage0, parse_lockfile, parse_manifest
from snowball_bootstrap.treehash import TreeError, extract
from snowball_bootstrap.vectors import run_vectors

from helpers import FakeRunner

BOOTSTRAP = Path(__file__).resolve().parents[1]
VECTORS = BOOTSTRAP / "vectors"
POLICY_DEFAULTS = BOOTSTRAP.parents[1] / "spec" / "tohum" / "18a-politika-baslangic-degerleri.md"
Z = "0" * 64


class CanonTest(unittest.TestCase):
    def test_seed_vectors_v1_v2(self):
        v1 = {"row_id": "r1", "ts": "2026-10-28T00:00:00Z", "part": "events", "kind": "genesis", "payload": {},
              "derivation": "tool", "trust": "verified", "snapshot_id": "s0", "evidence_refs": [], "prev_hash": Z}
        h1 = canon.row_hash(v1)
        self.assertEqual(h1, "3bae91580aca99362572e9f5f41b3e46c2bc0c29236f72e867faa5cd46ca603a")
        v2 = {"row_id": "r2", "ts": "2026-10-28T00:00:01Z", "part": "cost", "kind": "run",
              "payload": {"usd_micros": 0}, "derivation": "tool", "trust": "observed", "snapshot_id": "s0",
              "evidence_refs": [], "prev_hash": h1}
        self.assertEqual(canon.row_hash(v2), "3b10a5bb06351b0933c0e30f7dd55d3a57245743b97fb1faba348351a554a45c")

    def test_row_hash_ignores_own_hash_field(self):
        row = {"a": 1, "prev_hash": Z}
        self.assertEqual(canon.row_hash(row), canon.row_hash(dict(row, row_hash="x" * 64)))

    def test_floats_and_surrogates_rejected(self):
        with self.assertRaises(canon.CanonicalError):
            canon.canonical({"x": 0.5})
        with self.assertRaises(canon.CanonicalError):
            canon.canonical({"x": "\ud800"})
        with self.assertRaises(canon.CanonicalError):
            canon.canonical({"x": 2**60})

    def test_keys_sorted_by_utf16(self):
        self.assertEqual(canon.canonical({"b": 1, "a": 2, "é": 3}), '{"a":2,"b":1,"é":3}'.encode())


class ClassifyTest(unittest.TestCase):
    def test_kinds(self):
        self.assertEqual(classify([]), ("none", []))
        self.assertEqual(classify(["spec/asama-0/01-amac.md", "spec/INDEX.md"]), ("spec", []))
        self.assertEqual(classify(["referee/ledger/chain.py", "snowball-tests.json"]), ("code", []))
        self.assertEqual(classify(["spec/asama-0/x.md", "referee/a.py"]), ("rejected", ["mixed_spec_and_code"]))
        self.assertEqual(classify(["spec/tohum/00-cekirdek.md"]), ("rejected", ["seed_modified"]))
        self.assertEqual(classify(["seed/bootstrap/x.py"]), ("rejected", ["seed_modified"]))
        self.assertEqual(classify([".github/workflows/x.yml"]), ("rejected", ["root_workflow_modified"]))
        self.assertEqual(classify(["referee/.github/workflows/x.yml"]), ("code", []))

    def test_spec_dirs(self):
        self.assertEqual(spec_stage_dirs(["spec/asama-0/a.md", "spec/asama-1/b.md", "spec/INDEX.md"]),
                         ["spec/asama-0", "spec/asama-1"])


class ManifestTest(unittest.TestCase):
    def manifest(self, tests, done, locks=()):
        return json.dumps({"tests": tests, "done_mf": list(done), "lockfiles": list(locks)})

    def test_valid_and_complete(self):
        m = parse_manifest(self.manifest([{"id": "T13", "cmd": "python -m unittest", "stage": 0},
                                          {"id": "T30", "cmd": "python -m unittest t30", "stage": 0}], [1, 2]))
        self.assertEqual(check_stage0(m), [])

    def test_missing_test_and_zero_tests_and_order(self):
        m = parse_manifest(self.manifest([{"id": "T13", "cmd": "x", "stage": 0}], [1, 2]))
        self.assertEqual(check_stage0(m), ["missing_test:MF2:T30"])
        m = parse_manifest(self.manifest([], []))
        self.assertEqual(check_stage0(m), ["zero_tests"])
        m = parse_manifest(self.manifest([{"id": "T13", "cmd": "x", "stage": 0}], [2]))
        self.assertEqual(check_stage0(m), ["done_mf_not_in_order"])

    def test_malformed(self):
        for bad in ['{"tests": []}', self.manifest([{"id": "13", "cmd": "x", "stage": 0}], []),
                    self.manifest([{"id": "T1", "cmd": "", "stage": 0}], []),
                    self.manifest([], [], ["../x.txt"]),
                    self.manifest([{"id": "T1", "cmd": "x", "stage": 0, "extra": 1}], [])]:
            with self.assertRaises(ManifestError):
                parse_manifest(bad)

    def test_lockfile(self):
        h = "a" * 64
        self.assertEqual(len(parse_lockfile(f"x==1 \\\n    --hash=sha256:{h}\ny==2 --hash=sha256:{h}\n")), 2)
        for bad in [f"x>=1 --hash=sha256:{h}", "x==1", f"--index-url https://evil\nx==1 --hash=sha256:{h}",
                    f"x==1 --hash=sha256:{h} --trusted-host evil", "git+https://x/y"]:
            with self.assertRaises(ManifestError):
                parse_lockfile(bad)


class VectorsTest(unittest.TestCase):
    def test_correct_implementation_passes_every_vector(self):
        results = run_vectors(FakeRunner(VECTORS), VECTORS, (1, 9))
        self.assertTrue(results)
        self.assertEqual([r for r in results if not r["ok"]], [])

    def test_groups_wait_for_their_micro_feature(self):
        self.assertEqual(run_vectors(FakeRunner(VECTORS), VECTORS, (2,)), [])
        ids = {r["id"].split(".")[0] for r in run_vectors(FakeRunner(VECTORS), VECTORS, (1,))}
        self.assertEqual(ids, {"chain"})

    def test_wrong_implementations_fail(self):
        for wrong, prefix in [("chain_ignores_input", "chain.V1.hash_changed_input"),
                              ("verify_always_valid", "chain.V3"), ("cp_wilson", "cp_lower.60/60"),
                              ("score_counts_twice", "match.3")]:
            failed = {r["id"] for r in run_vectors(FakeRunner(VECTORS, wrong={wrong}), VECTORS, (1, 9))
                      if not r["ok"]}
            self.assertIn(prefix, failed, wrong)

    def test_drill_vectors_need_a_judge_that_fails_non_learners(self):
        honest = run_vectors(FakeRunner(VECTORS), VECTORS, (18,))
        self.assertEqual(len(honest), 19)
        self.assertEqual([r for r in honest if not r["ok"]], [])
        lenient = {r["id"] for r in run_vectors(FakeRunner(VECTORS, wrong={"drill_lenient"}), VECTORS, (18,))
                   if not r["ok"]}
        self.assertEqual(lenient, {r["id"] for r in honest} - {"drill.learner"})
        blind = {r["id"] for r in run_vectors(FakeRunner(VECTORS, wrong={"drill_ignores_commitment"}), VECTORS,
                                             (18,)) if not r["ok"]}
        self.assertEqual(blind, {"drill.tampered_key"})


class ControlsTest(unittest.TestCase):
    def test_honest_runner_passes(self):
        runner = FakeRunner(VECTORS, commands={"exit 1": (1, b"")})
        self.assertTrue(all(c["ok"] for c in run_controls(runner)))

    def test_always_green_runner_fails(self):
        class Green(FakeRunner):
            def run(self, cmd, **kw):
                from snowball_bootstrap.container import RunResult
                return RunResult(0, b"", b"", 1)
        results = {c["id"]: c["ok"] for c in run_controls(Green(VECTORS))}
        self.assertFalse(results["exit_one"])
        self.assertFalse(results["network_blocked"])
        self.assertFalse(results["source_read_only"])


class SecretScanTest(unittest.TestCase):
    def test_patterns(self):
        fake = "gh" + "p_" + "A" * 36
        self.assertEqual(secretscan.scan(f"token: {fake}"), ["github_token"])
        self.assertEqual(secretscan.scan("-----BEGIN " + "RSA PRIVATE KEY-----"), ["private_key"])
        self.assertEqual(secretscan.scan("nothing here"), [])


if __name__ == "__main__":
    unittest.main()


def spec_allowlist() -> frozenset[str]:
    """The recommended allowlist as `tohum/18a` writes it: the backticked ids before the first ';'."""
    row = next(line for line in POLICY_DEFAULTS.read_text(encoding="utf-8").splitlines()
               if line.startswith("| `license_allowlist` |"))
    return frozenset(re.findall(r"`([^`]+)`", row.split("|")[2].split(";")[0]))


def make_wheel(directory: Path, name: str, headers: list[str], files: dict[str, str] | None = None) -> Path:
    path = directory / f"{name}-1.0-py3-none-any.whl"
    with zipfile.ZipFile(path, "w") as zf:
        meta = "Metadata-Version: 2.4\nName: " + name + "\nVersion: 1.0\n" + "".join(h + "\n" for h in headers)
        zf.writestr(f"{name}-1.0.dist-info/METADATA", meta)
        for rel, text in (files or {}).items():
            zf.writestr(f"{name}-1.0.dist-info/{rel}", text)
    return path


GPL3 = "GNU GENERAL PUBLIC LICENSE\n   Version 3, 29 June 2007\n Everyone is permitted to copy..."
MIT_TEXT = ("Permission is hereby granted, free of charge, to any person obtaining a copy of this software... "
            "The above copyright notice and this permission notice shall be included in all copies.")
PSF_TEXT = ("PYTHON SOFTWARE FOUNDATION LICENSE VERSION 2\n... material that was previously distributed under "
            "the GNU General Public License (GPL), the law of the Commonwealth of Virginia shall govern ...")


class LicenseTest(unittest.TestCase):
    ALLOW = frozenset({"MIT", "Apache-2.0", "BSD-3-Clause", "PSF-2.0"})

    def judge(self, headers, files=None, exceptions=None):
        with tempfile.TemporaryDirectory() as tmp:
            make_wheel(Path(tmp), "pkg", headers, files)
            report = licenses.check_dir(Path(tmp), self.ALLOW, exceptions or {})
        self.assertEqual(len(report), 1)
        return report[0]

    def test_expressions(self):
        for expr, ok in (("MIT", True), ("mit", True), ("MIT OR GPL-3.0-only", True),
                         ("MIT AND GPL-3.0-only", False), ("(MIT OR GPL-3.0-only) AND Apache-2.0", True),
                         ("GPL-3.0-only OR (MIT AND AGPL-3.0-only)", False),
                         ("Apache-2.0 WITH LLVM-exception", True), ("Apache-2.0+", True)):
            self.assertEqual(licenses.allowed(expr, self.ALLOW), ok, expr)
        for bad in ("", "MIT OR", "(MIT", "MIT)", "AND MIT", "MIT GPL-3.0-only"):
            with self.assertRaises(licenses.ExpressionError, msg=bad):
                licenses.allowed(bad, self.ALLOW)

    def test_every_place_that_names_a_license_must_allow(self):
        r = self.judge(["License-Expression: MIT"], {"licenses/LICENSE": MIT_TEXT})
        self.assertEqual((r["expression"], r["allowed"]), ("MIT", True))
        r = self.judge(["License-Expression: MIT",
                        "Classifier: License :: OSI Approved :: GNU General Public License v3 (GPLv3)"])
        self.assertFalse(r["allowed"])
        r = self.judge(["License: MIT"], {"licenses/COPYING": GPL3})
        self.assertFalse(r["allowed"])
        r = self.judge(["Classifier: License :: Other/Proprietary License"])
        self.assertFalse(r["allowed"])

    def test_license_found_only_in_a_file_and_unknown_is_refused(self):
        r = self.judge([], {"licenses/LICENSE": MIT_TEXT})
        self.assertEqual((r["expression"], r["allowed"]), ("MIT", True))
        r = self.judge(["Classifier: License :: OSI Approved :: BSD License"], {"licenses/AUTHORS": "someone"})
        self.assertEqual((r["expression"], r["allowed"]), ("unknown", False))
        r = self.judge(["License: see the website"])
        self.assertEqual((r["expression"], r["allowed"]), ("unknown", False))

    def test_a_mention_is_not_a_license(self):
        r = self.judge(["License-Expression: PSF-2.0"], {"licenses/LICENSE": PSF_TEXT})
        self.assertEqual((r["expression"], r["allowed"]), ("PSF-2.0", True))
        self.assertEqual([s["expression"] for s in r["sources"]], ["PSF-2.0", "PSF-2.0"])

    def test_operator_exception_must_itself_be_allowed(self):
        r = self.judge([], exceptions={"pkg==1.0": "MIT"})
        self.assertEqual((r["basis"], r["allowed"]), ("exception", True))
        r = self.judge([], exceptions={"pkg==1.0": "GPL-3.0-only"})
        self.assertFalse(r["allowed"])
        r = self.judge([], exceptions={"pkg==2.0": "MIT"})
        self.assertEqual((r["expression"], r["allowed"]), ("unknown", False))

    def test_oversized_license_file_is_not_read(self):
        r = self.judge([], {"licenses/LICENSE": MIT_TEXT + " " * licenses.MAX_READ})
        self.assertEqual(r["expression"], "unknown")

    def test_cli_stops_on_a_violation(self):
        from snowball_bootstrap import cli
        with tempfile.TemporaryDirectory() as tmp:
            root, wheels = Path(tmp), Path(tmp) / "w"
            wheels.mkdir()
            (root / "policy.json").write_text(json.dumps({"constitutional": {
                "monthly_cap_usd": 1, "stage_params": {"rival_min_attempts": 1, "repeat_reject_limit": 3},
                "stage_budgets": {"asama_0": {"rival_usd": 1}}, "license_allowlist": ["MIT"],
                "license_exceptions": {}}}))
            argv = ["licenses", "--root", str(root), "--wheels", str(wheels), "--out", str(root / "r.json")]
            self.assertEqual(cli.main(argv), 2)  # no wheels at all is not a pass
            make_wheel(wheels, "good", ["License-Expression: MIT"])
            self.assertEqual(cli.main(argv), 0)
            make_wheel(wheels, "bad", [], {"licenses/LICENSE": GPL3})
            self.assertEqual(cli.main(argv), 2)
            report = json.loads((root / "r.json").read_text())
            self.assertEqual([(r["name"], r["allowed"]) for r in report], [("bad", False), ("good", True)])


class LicensePolicyTest(unittest.TestCase):
    def policy(self, **const):
        from snowball_bootstrap.config import load_policy
        base = {"monthly_cap_usd": 1, "stage_params": {"rival_min_attempts": 1, "repeat_reject_limit": 3},
                "stage_budgets": {"asama_0": {"rival_usd": 1}}, "license_allowlist": ["MIT"],
                "license_exceptions": {}}
        base.update(const)
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "policy.json").write_text(json.dumps({"constitutional": base}))
            return load_policy(Path(tmp))

    def test_allowlist_and_exceptions_are_strict(self):
        from snowball_bootstrap.config import ConfigError
        good = self.policy(license_exceptions={"pkg==1.0": {"expression": "MIT", "evidence": "LICENSE in sdist"}})
        self.assertEqual((good.license_allowlist, good.license_exceptions), (frozenset({"MIT"}), {"pkg==1.0": "MIT"}))
        for bad in ({"license_allowlist": []}, {"license_allowlist": ["MIT OR GPL-3.0-only"]},
                    {"license_exceptions": {"pkg==1.0": {"expression": "MIT"}}},
                    {"license_exceptions": {"Pkg_X==1.0": {"expression": "MIT", "evidence": "x"}}}):
            with self.assertRaises(ConfigError, msg=bad):
                self.policy(**bad)

    def test_a_wheel_that_is_not_allowed_makes_the_run_red(self):
        from snowball_bootstrap.cli import is_green
        ok = [{"ok": True}]
        self.assertTrue(is_green(ok, ok, ok, [{"allowed": True}]))
        self.assertFalse(is_green(ok, ok, ok, [{"allowed": True}, {"allowed": False}]))
        self.assertFalse(is_green(ok, [], ok, []))


class PinnedRequirementLicenseTest(unittest.TestCase):
    """The bootstrap's own pinned wheels: every one has a recorded, allowed license."""

    def test_record_matches_the_lock_file_and_the_spec_allowlist(self):
        allow = spec_allowlist()
        self.assertIn("MIT", allow)
        self.assertNotIn("GPL-3.0-only", allow)
        record = json.loads((BOOTSTRAP / "requirements" / "licenses.json").read_text())["packages"]
        pins = set()
        for req in parse_lockfile((BOOTSTRAP / "requirements" / "sign.txt").read_text()):
            pins.add(f"{re.sub(r'[-_.]+', '-', req.name).lower()}=={req.version}")
        self.assertEqual(pins, set(record))
        for pin, expr in record.items():
            self.assertTrue(licenses.allowed(expr, allow), f"{pin}: {expr}")


class ClaudeCliPinTest(unittest.TestCase):
    """The claude CLI is the one npm package the workflow installs: an exact version, every package by sha512."""

    def test_the_lock_file_pins_one_exact_version_with_integrity(self):
        folder = BOOTSTRAP / "requirements" / "claude-cli"
        pin = json.loads((folder / "package.json").read_text())["dependencies"]
        lock = json.loads((folder / "package-lock.json").read_text())
        main, platform = "@anthropic-ai/claude-code", "@anthropic-ai/claude-code-linux-x64"
        self.assertEqual(sorted(pin), [main, platform])
        version = pin[main]
        self.assertEqual(pin[platform], version)
        self.assertRegex(version, r"^[0-9]+\.[0-9]+\.[0-9]+$")
        self.assertEqual(lock["packages"][""]["dependencies"], pin)
        # npm 12 blocks install scripts unless allowed; without them the binary stays a 500-byte stub
        package = json.loads((folder / "package.json").read_text())
        self.assertEqual(package["allowScripts"], {f"{main}@{version}": True})
        binary = lock["packages"]["node_modules/" + platform]
        # The package holding the real binary is a hard dependency: npm skips an optional package whose digest
        # is wrong (and re-resolves it without the lock), a required one fails the install with EINTEGRITY.
        self.assertFalse(binary.get("optional"))
        self.assertEqual((binary["os"], binary["libc"]), (["linux"], ["glibc"]))
        for path, entry in lock["packages"].items():
            if path:
                self.assertTrue(entry["integrity"].startswith("sha512-"), path)
                self.assertTrue(entry["resolved"].startswith("https://registry.npmjs.org/"), path)
                self.assertEqual(entry["version"], version, path)


class TreeHardeningTest(unittest.TestCase):
    def test_unsafe_member_names_never_reach_the_filesystem(self):
        names = ("..\\..\\x", "C:\\x", "a:b", "/abs", "a/../b", "x\\y")  # a NUL cannot be written into a tar name
        with tempfile.TemporaryDirectory() as tmp:
            for name in names:
                buf = io.BytesIO()
                with tarfile.open(fileobj=buf, mode="w") as tar:
                    info = tarfile.TarInfo(name)
                    info.size = 1
                    tar.addfile(info, io.BytesIO(b"x"))
                with self.assertRaises(TreeError, msg=name):
                    extract(buf.getvalue(), Path(tmp) / "dest" / "tree", 1000)
            self.assertEqual(list(Path(tmp).rglob("x")), [])
            buf = io.BytesIO()  # a legal git member name longer than the file system allows: a TreeError, not a traceback
            with tarfile.open(fileobj=buf, mode="w") as tar:
                info = tarfile.TarInfo("a/" + "b" * 1000)
                info.size = 1
                tar.addfile(info, io.BytesIO(b"x"))
            with self.assertRaises(TreeError):
                extract(buf.getvalue(), Path(tmp) / "long", 1000)


class BootstrapConfigTest(unittest.TestCase):
    BASE = {"brain_repo": "owner/brain", "brain_branch": "main",
            "image": "docker.io/library/python:3.12-slim@sha256:" + "a" * 64,
            "rival": {"model": "claude-sonnet-5-5", "effort": "medium", "max_turns": 30,
                      "per_run_cap_usd_micros": 3_000_000},
            "limits": {"test_timeout_s": 600, "reproducer_timeout_s": 120, "max_prompt_chars": 600_000,
                       "max_tree_bytes": 50_000_000}}

    def load(self, mutate):
        doc = json.loads(json.dumps(self.BASE))
        mutate(doc)
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "bootstrap.json").write_text(json.dumps(doc))
            return load_bootstrap(Path(tmp))

    def test_the_shipped_shape_loads(self):
        boot = self.load(lambda d: None)
        self.assertEqual((boot.rival.model, boot.rival.max_turns, boot.rival.per_run_cap_usd_micros),
                         ("claude-sonnet-5-5", 30, 3_000_000))

    def test_keys_of_the_old_api_design_are_refused_by_name(self):
        for key in ("max_tokens", "price_micros_per_mtok"):
            with self.assertRaisesRegex(ConfigError, f"{key} was removed"):
                self.load(lambda d: d["rival"].update({key: 1}))

    def test_unknown_keys_are_refused_everywhere(self):
        for where, mutate in (("top", lambda d: d.update(api_key="x")),
                              ("rival", lambda d: d["rival"].update(fallback_model="claude-opus-5-5")),
                              ("limits", lambda d: d["limits"].update(extra=1))):
            with self.assertRaisesRegex(ConfigError, "unknown key", msg=where):
                self.load(mutate)

    def test_the_model_must_be_a_full_id(self):
        for model in ("sonnet", "", "  ", "claude-sonnet-5-5[1m]", "gpt-5"):
            with self.assertRaisesRegex(ConfigError, "full model id", msg=model):
                self.load(lambda d: d["rival"].update(model=model))


class SecretScanCoverageTest(unittest.TestCase):
    """Found by a real run: the model read GITHUB_TOKEN-style lines through grep, quoted them in its claims, and
    they went to the provider and into rival.json, because the scan only knew a few shapes."""

    TOK = "A" * 10 + "b" * 10 + "7" * 8

    def test_the_commonest_credential_shapes_are_found(self):
        cases = {
            "generic_assignment": ['GITHUB_TOKEN = "' + self.TOK + '"', "db_password: '" + self.TOK + "'",
                                   '{"password": "' + self.TOK + '"}', "{'api_key': '" + self.TOK + "'}",
                                   "a_very_long_name_" * 4 + "token = '" + self.TOK + "'",
                                   'AWS_SECRET_ACCESS_KEY = "' + "wJalrXUtnFEMI/K7MDENG" + "bPxRfiCY" + '"'],
            "generic_assignment_bare": ["AWS_SECRET_ACCESS_KEY=" + "wJalrXUtnFEMI/K7MDENG" + "bPxRfiCY",
                                        "api_key: " + self.TOK, "TOKEN=" + "0123456789abcdef" * 2],
            "openai_key": ["OPENAI = " + "sk-" + "proj-" + "A" * 40],
            "stripe_key": ["sk_" + "live_" + "A" * 24, "rk_" + "live_" + "A" * 24, "sk_" + "test_" + "A" * 24],
            "google_api_key": ["AI" + "za" + "A" * 35],
            "npm_token": ["npm" + "_" + "A" * 36],
            "jwt": ["ey" + "J" + "A" * 12 + ".ey" + "J" + "A" * 12 + "." + "A" * 12],
            "url_credentials": ["DATABASE_URL=postgres://app:" + "Pa55w0rd" + "Xyz9@db.internal:5432/app",
                                "git+https://builder:" + "ci9Token8Value" + "@example.com/org/repo.git"],
        }
        for name, samples in cases.items():
            for sample in samples:
                self.assertIn(name, secretscan.scan(sample), sample)

    def test_identifiers_numbers_and_lookups_are_not_secrets(self):
        for line in ("token = tokenizer_pretrained_model_name_v2", "secret = get_secret_value_from_vault_1",
                     "token_count = 12345678901234567890", 'api_key = os.environ["API_KEY"]', "max_tokens = 100000",
                     "postgres://user:password@localhost:5432/db", "https://example.com:8080/a/b?c=d",
                     "git@github.com:owner/repo.git", "http://user:pass@localhost/",
                     'password = "changeme"', "password_field = hash_password_with_salt_and_pepper",
                     "SECRET_KEY = config.get('secret_key_name')", "token: Bearer",
                     "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"):
            self.assertEqual(secretscan.scan(line), [], line)

    def test_the_repository_itself_has_no_false_positive(self):
        root = Path(__file__).resolve().parents[3]
        checked = 0
        for base in (root / "seed", root / "spec", root / "README.md"):
            for path in ([base] if base.is_file() else base.rglob("*")):
                parts = path.parts
                if (not path.is_file() or "node_modules" in parts or "__pycache__" in parts or path.stat().st_size > 2_000_000
                        or path.suffix not in (".py", ".md", ".json", ".yml", ".txt", ".cjs")):
                    continue
                checked += 1
                self.assertEqual(secretscan.scan(path.read_text(encoding="utf-8", errors="replace")), [],
                                 str(path.relative_to(root)))
        self.assertGreater(checked, 100)


class SecretScanSpeedTest(unittest.TestCase):
    """V3: a pattern with two open-ended repeats around a keyword took 24 s on 2000 characters of `token` and
    minutes on one long hex line; the diff, whole files and verdicts reach the scan unbounded."""

    def test_hostile_lines_are_scanned_in_linear_time(self):
        hostile = {"keyword run": "token" * 10_000, "name tail": "api_key" * 7_000, "hex line": "0123456789abcdef" * 3_125,
                   "jwt alphabet": "eyJ-" * 50_000, "url prefix": "a://b:c1" * 6_250, "long value": "token=" + "Aa1" * 16_000}
        for label, text in hostile.items():
            started = time.perf_counter()
            secretscan.scan(text)
            self.assertLess(time.perf_counter() - started, 1.0, label)


class SecretScanBoundaryTest(unittest.TestCase):
    def test_a_token_glued_to_other_characters_is_still_a_token(self):
        for text in ("x" + "gh" + "p_" + "A" * 36, "_" + "gh" + "p_" + "A" * 36, "a-" + "AKIA" + "ABCDEFGHIJKLMNOP",
                     "-----BEGIN PGP PRIV" + "ATE KEY BLOCK-----"):
            self.assertNotEqual(secretscan.scan(text), [], text)

    def test_every_whole_string_pattern_rejects_a_trailing_newline(self):
        """V3: `$` matches before a final newline, so `<sha>\n` passed for a sha; `\Z` does not."""
        import re
        from snowball_bootstrap import config, manifest, state as st
        for module in (config, st, manifest):
            for name, value in vars(module).items():
                if isinstance(value, re.Pattern) and value.pattern.startswith("^"):
                    self.assertTrue(value.pattern.endswith("\Z"), f"{module.__name__}.{name}: {value.pattern}")
        self.assertIsNone(st.SHA_RE.match("a" * 40 + chr(10)))
        self.assertIsNotNone(st.SHA_RE.match("a" * 40))

    def test_a_jwt_shape_inside_a_longer_word_is_not_one(self):
        jwt = "ey" + "J" + "A" * 12 + ".ey" + "J" + "A" * 12 + "." + "A" * 12
        self.assertIn("jwt", secretscan.scan(" " + jwt))
        self.assertNotIn("jwt", secretscan.scan("x" + jwt))
