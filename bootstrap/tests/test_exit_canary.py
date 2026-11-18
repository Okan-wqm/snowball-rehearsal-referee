"""The exit request's container canary (seed-058, E600-E602, `tohum/29z`) and the toy's summary base (seed-059, E603).

Before (B) nothing started a real container from the brain's `referee/`; three (B) attempts ended on host facts the
brain's stand-in did not carry. On an exit request the `kanarya` job runs the brain's own `runner.contained run` once on
the host, outside any container, with no secret and no permission; a red answer keeps the exit closed as
`canary:<status>`. Here: what the referee hands the brain, how it reads the answer, how `decide` reads the job's
untrusted output, the workflow's wiring and the pages that say it.

The trailing comment on a test names the mutants it kills (`local/mutate.py`).
"""

import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from snowball_bootstrap import cli, config, exitcanary
from snowball_bootstrap.decide import decide

from helpers import workflow_job

BOOT = Path(__file__).resolve().parents[1]
ROOT = BOOT.parents[1]
A, B = "a" * 40, "b" * 40
IMAGE = "node:22.23.4-bookworm-slim@sha256:" + "4" * 64
SUMMARY = {"seed_commit": "c" * 40, "seed_tree_sha256": "d" * 64,
           "targets": [{"id": "toy", "repo": "o/toy", "kind": "toy", "base_sha": None, "identifiers": [],
                        "excluded_paths": [], "unit_candidates": []},
                       {"id": "copy", "repo": "o/copy", "kind": "copy", "base_sha": "e" * 40, "identifiers": ["acme"],
                        "excluded_paths": [], "unit_candidates": ["src"]}]}
OPERATING = {"container_mem_bytes": {"value": 1 << 30, "band": [1 << 28, 1 << 32]}}


def page(prefix):
    found = sorted((ROOT / "spec" / "tohum").glob(f"{prefix}-*.md"))
    assert len(found) == 1, prefix
    return found[0].read_text(encoding="utf-8")


def flat(text):
    return " ".join(text.split())


def tar_of(files):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:", format=tarfile.PAX_FORMAT) as tar:
        for name, data in files.items():
            raw = data if isinstance(data, bytes) else data.encode("utf-8")
            info = tarfile.TarInfo(name)
            info.size, info.mode = len(raw), 0o755 if name.endswith(".py") else 0o644
            tar.addfile(info, io.BytesIO(raw))
    return buf.getvalue()


def units(image=IMAGE, *more):
    return json.dumps({"units": [{"unit_id": "u", "env_image": image}] + [{"unit_id": f"u{i}", "env_image": m}
                                                                           for i, m in enumerate(more)]})


class Snapshot:
    """A referee snapshot (`snap/`) with the summary and policy the canary reads."""

    def __init__(self, test, summary=SUMMARY, policy=None):
        self.dir = Path(tempfile.mkdtemp())
        test.addCleanup(shutil.rmtree, self.dir, True)
        (self.dir / "setup").mkdir()
        (self.dir / "setup" / "summary.json").write_text(json.dumps(summary), encoding="utf-8")
        policy = {"constitutional": {}, "operating": OPERATING} if policy is None else policy
        (self.dir / "policy.json").write_text(json.dumps(policy), encoding="utf-8")


# A brain whose `runner.contained run FILE` reports what it was handed: its argv, cwd, environment and the request.
REPORTER = r'''
import json, os, sys
req = json.load(open(sys.argv[2], encoding="utf-8"))
seen = {"argv": sys.argv[1:], "cwd": os.getcwd(), "env": sorted(os.environ), "req": req,
        "secret": os.environ.get("SNOWBALL_CANARY_SECRET"), "home": os.environ.get("HOME")}
open(os.path.join(os.path.dirname(sys.argv[2]), "seen.json"), "w", encoding="utf-8").write(json.dumps(seen))
print("noise before the answer")
print(json.dumps(ANSWER))
'''


def brain(answer, extra=None, script=REPORTER):
    files = {"referee/runner/__init__.py": "", "referee/runner/contained.py": script.replace("ANSWER", repr(answer)),
             "targets/toy/units.json": units()}
    files.update(extra or {})
    return tar_of({k: v for k, v in files.items() if v is not None})


GREEN = {"valid": True, "reasons": [], "result": {"exit": 0, "status": "ok"}}


class ToyImageTest(unittest.TestCase):
    def test_the_image_is_the_first_unit_of_the_toys_recipe_pinned_by_digest(self):  # canary_image_of_the_last_unit
        snap = Snapshot(self)
        other = "node:20.0.0@sha256:" + "5" * 64
        self.assertEqual(exitcanary.toy_image(snap.dir, tar_of({"targets/toy/units.json": units(IMAGE, other)})),
                         IMAGE)

    def test_no_single_toy_or_no_pinned_image_is_no_recipe(self):  # canary_image_unpinned_accepted
        snap = Snapshot(self)
        for files in ({}, {"targets/toy/units.json": "not json"}, {"targets/toy/units.json": '{"units": []}'},
                      {"targets/toy/units.json": units("node:22")},
                      {"targets/toy/units.json": units(IMAGE + " --privileged")},
                      {"targets/copy/units.json": units()}):
            with self.subTest(files=files):
                self.assertIsNone(exitcanary.toy_image(snap.dir, tar_of(files)))
        two = dict(SUMMARY, targets=[SUMMARY["targets"][0], dict(SUMMARY["targets"][0], id="toy2")])
        self.assertIsNone(exitcanary.toy_image(Snapshot(self, two).dir,
                                               tar_of({"targets/toy/units.json": units()})))  # canary_any_toy

    def test_the_operating_section_is_the_policys_own_or_empty(self):
        self.assertEqual(exitcanary.operating(Snapshot(self).dir), OPERATING)
        self.assertEqual(exitcanary.operating(Snapshot(self, policy={"constitutional": {}}).dir), {})


class StatusTest(unittest.TestCase):
    """How the brain's answer is read (`29z` "Okunan")."""

    def status(self, answer, timed_out=False):
        line = answer if isinstance(answer, str) else json.dumps(answer)
        return exitcanary.status_of(("log line\n" + line + "\n\n").encode(), timed_out)

    def test_only_a_valid_run_whose_canary_ended_0_is_ok(self):  # canary_exit_unread canary_breach_is_ok
        self.assertEqual(self.status(GREEN), ["ok"])
        self.assertEqual(self.status(dict(GREEN, result={"exit": 3})), ["breach"])
        self.assertEqual(self.status(dict(GREEN, result={"exit": 127})), ["exit_127"])
        for result in ({"exit": "0"}, {"exit": True}, {"exit": -1}, {"exit": 256}, {}, None):
            with self.subTest(result=result):
                self.assertEqual(self.status(dict(GREEN, result=result)), ["malformed"])

    def test_an_invalid_run_names_its_reasons_as_tokens(self):  # canary_reasons_unfiltered canary_invalid_is_ok
        answer = {"valid": False, "reasons": ["runner_fault", "red_control_fault", "runner_fault",
                                              "limit_hit:kos_wall_s", "Bad Token", "x" * 33, "ok", 7]}
        self.assertEqual(self.status(answer), ["limit_hit:kos_wall_s", "red_control_fault", "runner_fault"])
        self.assertEqual(self.status({"valid": False, "reasons": []}), ["invalid"])
        self.assertEqual(self.status({"valid": False, "reasons": "runner_fault"}), ["invalid"])
        many = {"valid": False, "reasons": [f"r{i:02d}" for i in range(12)]}
        self.assertEqual(self.status(many), [f"r{i:02d}" for i in range(8)])  # canary_statuses_unbounded

    def test_no_object_with_a_boolean_valid_is_no_answer_and_a_timeout_is_named(self):  # canary_valid_truthy
        for line in ("", "not json", "[1]", json.dumps({"valid": 1, "result": {"exit": 0}}),
                     json.dumps({"reasons": []}), "{" * 100000):
            with self.subTest(line=line[:20]):
                self.assertEqual(self.status(line), ["no_answer"])
        self.assertEqual(self.status(GREEN, timed_out=True), ["timeout"])

    def test_the_last_line_is_read_not_the_first(self):  # canary_first_line_read
        out = (json.dumps({"valid": False, "reasons": ["runner_fault"]}) + "\n" + json.dumps(GREEN) + "\n").encode()
        self.assertEqual(exitcanary.status_of(out, False), ["ok"])


class RunTest(unittest.TestCase):
    """What the referee hands the brain's command (`29z` "Komut")."""

    def run_canary(self, answer, files=None, timeout_s=60, script=REPORTER):
        snap = Snapshot(self)
        work = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, work, True)
        tar = brain(answer, files, script)
        tree = work / "src"
        from snowball_bootstrap.treehash import extract
        extract(tar, tree, 10_000_000)
        with mock.patch.dict(os.environ, {"GITHUB_OUTPUT": str(work / "out"), "GITHUB_TOKEN": "x",
                                          "ACTIONS_RUNTIME_TOKEN": "y", "PYTHONPATH": "/nowhere"}):
            found = exitcanary.run(snap.dir, tar, tree, work / "canary", timeout_s=timeout_s)
        seen = work / "canary" / "seen.json"
        return found, (json.loads(seen.read_text(encoding="utf-8")) if seen.exists() else None), tree

    def test_the_brain_gets_the_request_from_its_referee_tree_and_nothing_of_githubs(self):
        # canary_env_inherited canary_secret_not_planted canary_cwd_not_referee canary_red_control_missing
        found, seen, tree = self.run_canary(GREEN)
        self.assertEqual(found, ["ok"])
        self.assertEqual(Path(seen["cwd"]).resolve(), (tree / "referee").resolve())
        self.assertEqual(seen["argv"][0], "run")
        self.assertTrue(Path(seen["argv"][1]).is_absolute())
        self.assertNotIn(str(tree.resolve()), str(Path(seen["argv"][1]).resolve().parent))
        self.assertTrue(set(seen["env"]) <= {"PATH", "HOME", "SNOWBALL_CANARY_SECRET", "PYTHONDONTWRITEBYTECODE",
                                             "LC_CTYPE", "SYSTEMROOT"}, seen["env"])
        self.assertRegex(seen["secret"], r"^[0-9a-f]{32}$")
        self.assertEqual(seen["req"], {"job": {"image": IMAGE, "cmd": ["node", "-e", exitcanary.SCRIPT]},
                                       "red_control": {"image": IMAGE, "cmd": ["node", "-e", "process.exit(1)"]},
                                       "operating": OPERATING})

    def test_each_run_plants_a_new_secret(self):  # canary_secret_fixed
        first = self.run_canary(GREEN)[1]["secret"]
        self.assertNotEqual(first, self.run_canary(GREEN)[1]["secret"])

    def test_the_answer_is_read_and_a_missing_recipe_runs_nothing(self):
        self.assertEqual(self.run_canary({"valid": False, "reasons": ["runner_fault"]})[0], ["runner_fault"])
        found, seen, _tree = self.run_canary(GREEN, {"targets/toy/units.json": None})
        self.assertEqual((found, seen), (["no_recipe"], None))

    def test_a_hanging_brain_is_a_timeout_and_a_tree_without_referee_no_answer(self):  # canary_no_timeout
        hang = "import time\ntime.sleep(30)\n"
        self.assertEqual(self.run_canary(GREEN, timeout_s=1, script=hang)[0], ["timeout"])
        snap, work = Snapshot(self), Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, work, True)
        tar = tar_of({"targets/toy/units.json": units()})
        self.assertEqual(exitcanary.run(snap.dir, tar, work / "empty", work / "c"), ["no_answer"])

    def test_the_cli_writes_one_output_and_stays_green(self):  # canary_output_unwritten
        snap = Snapshot(self)
        (snap.dir / "bootstrap.json").write_text("{}", encoding="utf-8")
        work = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, work, True)
        (work / "pulled").mkdir()
        (work / "pulled" / "brain.tar").write_bytes(brain({"valid": False, "reasons": ["unreadable_output"]}))
        out = work / "gh-output"
        boot = mock.Mock()
        boot.limits.max_tree_bytes = 10_000_000
        with mock.patch.dict(os.environ, {"GITHUB_OUTPUT": str(out)}), \
                mock.patch.object(cli.config, "load_bootstrap", return_value=boot), \
                mock.patch("sys.stdout", io.StringIO()):
            code = cli.main(["canary", "--root", str(snap.dir), "--pulled", str(work / "pulled"),
                             "--work", str(work / "w")])
        self.assertEqual(code, 0)
        self.assertEqual(out.read_text(encoding="utf-8"), "canary=unreadable_output\n")


class CanaryScriptInDockerTest(unittest.TestCase):
    """The canary command itself, in the real image with the flags `29f` asks of a contained run: all three attempts
    fail there (0), and each one succeeds without its flag (3). Runs where docker holds the image (no pull)."""

    IMAGE = os.environ.get("SNOWBALL_CANARY_IMAGE", "node:22.23.4-bookworm-slim")

    def setUp(self):
        docker = shutil.which("docker")
        if docker is None or subprocess.run([docker, "image", "inspect", self.IMAGE], capture_output=True).returncode:
            self.skipTest(f"docker with {self.IMAGE} on this host")
        self.out = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.out, True)
        os.chmod(self.out, 0o777)

    def run_script(self, *flags):
        user = ["--user", f"{os.getuid()}:{os.getgid()}"] if hasattr(os, "getuid") else []  # the host reads /out
        argv = ["docker", "run", "--rm", *user, *flags, "--mount", f"type=bind,src={self.out},dst=/out", self.IMAGE,
                "node", "-e", exitcanary.SCRIPT]
        return subprocess.run(argv, capture_output=True, timeout=120, env=dict(os.environ, SNOWBALL_CANARY_SECRET="z"))

    def test_contained_it_ends_0_and_writes_a_private_report(self):
        proc = self.run_script("--network", "none", "--read-only", "--cap-drop", "ALL")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(json.loads((self.out / "canary.json").read_text()), {"breach": []})

    def test_each_open_door_is_a_breach(self):
        for flags, door in ((["--read-only", "-e", "SNOWBALL_CANARY_SECRET"], "env"),
                            (["--network", "none"], "write")):
            with self.subTest(door=door):
                proc = self.run_script(*flags)
                self.assertEqual(proc.returncode, exitcanary.BREACH_EXIT, proc.stderr)
                self.assertIn(door, json.loads((self.out / "canary.json").read_text())["breach"])


def exit_meta(state):
    return {"head": B, "base": A, "kind": "exit", "state": state, "changed": [], "pre_reasons": [], "evaluate": True,
            "run_tests": True, "run_rival": False, "manifest": {"tests": [], "done_mf": list(range(1, 19)),
                                                                "lockfiles": []},
            "exit_request": {"stage": 0, "sha": A, "spec_sha256": "e" * 64}, "referee_tree_sha256": "f" * 64,
            "spec_dir_hashes": {}}


def state0():
    return {"schema": "snowball-bootstrap-state/4", "origin": "artifact", "last_accepted_sha": A,
            "last_evaluated_sha": None, "frozen_specs": {}, "month": "2026-10", "month_spend_usd_micros": 0,
            "stage_spend_usd_micros": 0, "runs": 4, "reject_streaks": {}, "repeat_events": 0, "outage_sha": None,
            "outage_count": 0, "outage_since": None, "outage_stop": None, "rival_side_streak": 0,
            "open_refutations": [], "open_claims": [], "pending_rival": None, "rejected_exit_request": None,
            "exit_accepted_sha": None,
            "rival_artifacts": [{"sha": s, "outcome": "survived"} for s in (A, "1" * 40, "2" * 40)]}


GREEN_RUN = {"controls": [{"id": "c", "ok": True}], "tests": [], "vectors": [], "licenses": [], "green": True}
JOBS = {"getir": "success", "kos": "success"}


class DecideTest(unittest.TestCase):
    """`decide` reads the job's result and its output as untrusted text (`29z` "Kayıt ve karar")."""

    def canary_of(self, job, line, kind="exit"):
        meta = dict(exit_meta(state0()), kind=kind)
        jobs = dict(JOBS, kanarya=job) if job is not None else dict(JOBS)
        res = decide(meta, GREEN_RUN, None, None, jobs, 2, 3, canary=line)
        return res, [m for m in res["exit"]["missing"] if m.startswith("canary:")]

    def test_a_green_canary_adds_nothing_and_is_recorded(self):  # canary_not_recorded
        res, missing = self.canary_of("success", "ok")
        self.assertEqual(missing, [])
        self.assertEqual(res["exit"]["canary"], {"job": "success", "status": ["ok"]})

    def test_a_red_canary_keeps_the_exit_closed_and_counts(self):  # canary_red_ignored canary_not_the_founders
        res, missing = self.canary_of("success", "red_control_fault,runner_fault")
        self.assertEqual(missing, ["canary:red_control_fault", "canary:runner_fault"])
        self.assertEqual(res["verdict"], "rejected")
        self.assertFalse(res["exit"]["transferable"])
        reasons = [r for r in res["reasons"] if r["ref"].startswith("canary:")]
        self.assertEqual([(r["kind"], r["detail"]) for r in reasons], [("exit_condition", exitcanary.DETAIL)] * 2)
        self.assertIn("exit_condition:canary:runner_fault", res["state"]["reject_streaks"])
        self.assertIsNone(res["state"]["outage_sha"])  # never an outage

    def test_a_job_that_did_not_succeed_or_did_not_run_is_missing(self):  # canary_job_unchecked canary_absent_passes
        for job, name in (("failure", "job_failure"), ("cancelled", "job_cancelled"), ("skipped", "job_skipped"),
                          (None, "job_none"), ("weird", "job_none")):
            with self.subTest(job=job):
                res, missing = self.canary_of(job, "ok")
                self.assertEqual(missing, [f"canary:{name}"])
                self.assertEqual(res["exit"]["canary"]["status"], [])

    def test_output_that_is_not_status_tokens_is_malformed(self):  # canary_output_trusted canary_ok_beside_red
        # canary_repeats_accepted canary_token_holds_a_secret canary_output_unbounded
        for line in (None, "", "ok,ok", "runner_fault,runner_fault", "ok,runner_fault", "Runner Fault", "ghp_" + "a" * 36, ",".join("abcdefghi"),
                     "a;b", "runner_fault\nok"):
            with self.subTest(line=line):
                res, missing = self.canary_of("success", line)
                self.assertEqual(missing, ["canary:malformed"])
                self.assertEqual(res["exit"]["canary"]["status"], ["malformed"])

    def test_only_an_exit_reads_the_canary(self):
        res = decide(dict(exit_meta(state0()), kind="code", run_rival=False), GREEN_RUN, None, None, JOBS, 2, 3)
        self.assertNotIn("canary", res["exit"])
        self.assertEqual(res["exit"]["missing"], [])


class WorkflowTest(unittest.TestCase):
    """`workflow/bootstrap.yml`'s `kanarya` job and how `yaz` reads it."""

    def test_the_job_holds_no_secret_no_permission_runs_only_on_an_exit_and_uploads_nothing(self):
        # canary_job_holds_a_permission canary_job_on_every_push
        job = workflow_job("kanarya")
        self.assertIn("    permissions: {}\n", job)
        self.assertIn("    needs: cek\n", job)
        self.assertIn("if: needs.cek.result == 'success' && needs.cek.outputs.exit_request == 'true'", job)
        # An own-head request is a code push (E630): pull's exit_request output, not its kind, says one is there.
        self.assertIn("      exit_request: ${{ steps.pull.outputs.exit_request }}\n", workflow_job("cek"))
        for word in ("secrets.", "upload-artifact", "docker pull", "id-token", "contents:", "cache"):
            self.assertNotIn(word, job.split("steps:", 1)[1], word)
        self.assertIn("python3 -m snowball_bootstrap canary --root snap --pulled pulled --work work", job)
        self.assertIn("canary: ${{ steps.canary.outputs.canary }}", job)
        self.assertIn('echo "${{ needs.cek.outputs.pulled_sha }}  pulled.tar" | sha256sum -c -', job)

    def test_yaz_waits_for_it_and_never_pastes_its_output_into_a_script(self):  # canary_output_pasted
        yaz = workflow_job("yaz")
        self.assertIn("needs: [cek, getir, kos, cagir, yeniden, kanarya]", yaz)
        decide_step = yaz[yaz.index("- name: Decide"):yaz.index("- name: Sign")]
        self.assertIn("CANARY: ${{ needs.kanarya.outputs.canary }}", decide_step)
        self.assertIn('--job kanarya=${{ needs.kanarya.result }} --canary "$CANARY"', decide_step)
        script = decide_step[decide_step.index("run: >"):]
        self.assertNotIn("outputs.canary", script)
        others = "".join(workflow_job(j) for j in ("cek", "getir", "kos_parca", "kos", "cagir", "yeniden"))
        self.assertNotIn("kanarya", others)


class PagesTest(unittest.TestCase):
    """The pages say what the code does (seed-058, seed-059, seed-060)."""

    def test_29b_says_it_after_the_exit_request_and_29z_holds_the_codes_constants(self):
        # canary_page_drops_the_command canary_page_wrong_timeout canary_page_drops_a_status
        line73 = page("29b").splitlines()[72]
        for words in ("**Kanarya** (seed-058)", "`python -m runner.contained run`'ı konteynerin dışında",
                      "sırsız ve izinsiz `kanarya` işinde", "`canary:<durum>`", "(`29z`)"):
            self.assertIn(words, line73)
        z = flat(page("29z"))
        for words in (f"süre {exitcanary.TIMEOUT_S} sn", f"`{exitcanary.SECRET_NAME}`", "`python3 -m runner.contained run <istek>`",
                      '`["node", "-e", "process.exit(1)"]`', f"biri başardıysa {exitcanary.BREACH_EXIT} ile biter",
                      f"en çok {exitcanary.MAX_TOKEN} karakterlik", f"en çok {exitcanary.MAX_STATUSES}'i",
                      "`[a-z0-9_]+(:[a-z0-9_]+)?`", "`permissions: {}`", "imaj çekmez", "`exit_<kod>`",
                      "`canary:job_<job>`", "kipi 0600"):
            self.assertIn(words, z, words)
        for status in ("no_recipe", "timeout", "no_answer", "invalid", "malformed", "ok", "breach"):
            self.assertIn(f"`{status}`", z)
        self.assertIn(", ".join(f"`{r}`" for r in exitcanary.JOB_RESULTS) + " ya da `none`", z)
        self.assertEqual(exitcanary.RED_CMD, ["node", "-e", "process.exit(1)"])
        self.assertEqual(exitcanary.COMMAND, ("python3", "-m", "runner.contained", "run"))

    def test_29o_says_the_toys_summary_base_is_null_as_the_referee_reads_it(self):
        # toy_base_page_not_null toy_base_fact_dropped seed_sha_null_fact_dropped
        lines = page("29o").splitlines()
        self.assertIn("oyuncak kurulumda boştur (`null`)", flat(" ".join(lines[44:46])))
        fact = flat(page("29o").split("**Kurulumun özetteki biçimi** (seed-059).", 1)[1])
        for words in ("oyuncak kurulumda boştur, yazılan `null`'dır; boş dize ya da eksik anahtar okunmaz",
                      "`seed_epochs[].seed_sha256` (beyinde `seed/` yoksa", "Zorunlu: `seed_commit`",
                      "`seed_epoch` son satırı olduğu gibi taşır"):
            self.assertIn(words, fact, words)
        optional = re.search(r"Yazılmayabilen: (.*?)\. ", fact).group(1)
        self.assertEqual(set(re.findall(r"`([a-z_\[\].]+)`", optional)),
                         {"seed_epochs", "targets", "targets[].safety_paths"} | {
                             f for fields in config.OWNER_EXCEPTIONS.values() for f in (fields.exception, fields.commitment)})
        self.assertEqual(config.TARGET_OPTIONAL_KEYS, {"safety_paths"})
        epoch = {"commit": "c" * 40, "spec_tohum_sha256": "d" * 64, "seed_sha256": None, "bootstrap_sha256": "e" * 64}
        self.assertIsNone(config._epoch(epoch, "e").seed_sha256)
        row = dict(SUMMARY["targets"][0])
        self.assertIsNone(config.target(row, "t").base_sha)
        for broken in (dict(row, base_sha=""), {k: v for k, v in row.items() if k != "base_sha"},
                       dict(row, base_sha="A" * 40)):
            with self.subTest(row=broken), self.assertRaises(config.ConfigError):
                config.target(broken, "t")

    def test_the_new_genesis_summaries_are_the_form_the_referee_reads_at_setup(self):
        """The sixth (B) attempt: fixtures that carry a form setup does not write let a reading pass that the real summary
        stops. The summary the toy cases read is one the referee itself reads; the others differ by the row they name."""
        genesis = BOOT / "vectors" / "genesis"
        real = config.summary_of(json.loads((genesis / "summary_toy_null.json").read_text(encoding="utf-8")))
        self.assertEqual([e.seed_sha256 for e in real.epochs], [None] * len(real.epochs))
        self.assertEqual([(t.kind, t.base_sha is None) for t in real.targets], [("toy", True), ("copy", False)])
        config.summary_of(json.loads((genesis / "summary_bases_null.json").read_text(encoding="utf-8")))
        for name in ("summary_toy_absent.json", "summary_bases_absent.json"):
            with self.subTest(name=name), self.assertRaises(config.ConfigError):
                config.summary_of(json.loads((genesis / name).read_text(encoding="utf-8")))

    def test_29s_names_the_writer_apps_two_secrets_and_what_is_not_known(self):  # app_secret_names_dropped
        text = flat(page("29s").split("**GitHub kimlikleri** (seed-057).", 1)[1])
        for words in ("`WRITER_APP_ID` (App ID)", "`WRITER_APP_PRIVATE_KEY` (GitHub'ın indirdiği `.pem` dosyasının tamamı)",
                      "2026-10-31'de GitHub web arayüzünden girdi", "Operatör bir sırrın değerini okuyamaz",
                      "satır sonu olup olmadığı bilinmiyor", "tohum bundan öte bir biçim güvencesi vermez"):
            self.assertIn(words, text, words)
        for word in ("trim", "kırp", "temizle"):  # facts, never how the Founder must read them
            self.assertNotIn(word, text.lower())

    def test_the_changelog_names_the_three_reports_by_lines_that_say_them(self):  # changelog_drops_seed_058
        log = flat((ROOT / "spec" / "tohum" / "CHANGELOG.md").read_text(encoding="utf-8"))
        says = {"seed-058-no-real-container-before-b": ("29b", 73, 73, "**Kanarya** (seed-058)"),
                "seed-059-genesis-vector-toy-base-not-setups-form": ("29o", 45, 46, "boştur (`null`)"),
                "seed-060-app-secret-form-not-stated": ("29s", 78, 80, "`WRITER_APP_PRIVATE_KEY`")}
        for report, (prefix, first, last, words) in says.items():
            ref = f"`{prefix}:{first}`" if first == last else f"`{prefix}:{first}-{last}`"
            self.assertIn(f"`{report}` → {ref}", log, report)
            self.assertIn(words, flat(" ".join(page(prefix).splitlines()[first - 1:last])), report)
        self.assertIn("`seed-058-no-real-container-before-b` → `29b:73`, `29z`", log)
        self.assertIn("`seed-059-genesis-vector-toy-base-not-setups-form` → `29o:45-46`, `29o:69-76`", log)
        z = page("29o").splitlines()
        self.assertTrue(z[68].startswith("**Kurulumun özetteki biçimi** (seed-059)."), z[68])
        self.assertIn("`seed_epoch_seed_null`", " ".join(z[62:67]))
        self.assertEqual(len(z), 76)


if __name__ == "__main__":
    unittest.main()
