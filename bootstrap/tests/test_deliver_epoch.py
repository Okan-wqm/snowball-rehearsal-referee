"""The one-command seed epoch delivery (`seed/founder/deliver_epoch.py`, E526): README "Tohum teslimi" in one tool.

Git runs for real on local repositories (the source with S, the referee's and the brain's remotes as bare
repositories); GitHub (CI, the referee's results, its runs and the dispatch) is a fake. The checkout's own
`snowball_bootstrap seed-epoch` prints the row, as S's would.
"""

from __future__ import annotations

import builtins
import contextlib
import importlib.util
import io
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

BOOT = Path(__file__).resolve().parents[1]
FOUNDER = BOOT.parent / "founder"
FOUNDER_ID = ("Snowball Founder", "founder@snowball.invalid")
LAUNCHER_ID = ("Snowball launcher", "launcher@snowball.invalid")
OPERATOR = {"GIT_AUTHOR_NAME": "op", "GIT_AUTHOR_EMAIL": "op@example.invalid", "GIT_COMMITTER_NAME": "op",
            "GIT_COMMITTER_EMAIL": "op@example.invalid"}


def load_deliver():
    spec = importlib.util.spec_from_file_location("founder_deliver_epoch", FOUNDER / "deliver_epoch.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


deliver = load_deliver()


def g(cwd: Path, *args: str, stdin: bytes | None = None, who: tuple[str, str] = ("t", "t@example.invalid")) -> str:
    env = {**os.environ, "GIT_AUTHOR_NAME": who[0], "GIT_AUTHOR_EMAIL": who[1], "GIT_COMMITTER_NAME": who[0],
           "GIT_COMMITTER_EMAIL": who[1]}
    return subprocess.run(["git", "-c", "core.autocrlf=false", "-C", str(cwd), *args], input=stdin, env=env,
                          capture_output=True, check=True).stdout.decode().strip()


def history(path: Path, commits: list[tuple[dict[str, bytes | None], tuple[str, str]]]) -> list[str]:
    """A repository whose commits hold exactly these bytes (written through the index: no line-end filter), each by
    its committer; None removes a path."""
    path.mkdir(parents=True, exist_ok=True)
    g(path, "init", "-q", "-b", "main")
    shas = []
    for files, who in commits:
        for rel, data in files.items():
            if data is None:
                g(path, "update-index", "--force-remove", "--", rel)
                continue
            sha = g(path, "hash-object", "-w", "--no-filters", "--stdin", stdin=data)
            g(path, "update-index", "--add", "--cacheinfo", f"100644,{sha},{rel}")
        g(path, "commit", "-q", "--allow-empty", "-m", f"commit {len(shas)}", who=who)
        shas.append(g(path, "rev-parse", "HEAD"))
    return shas


def bare(src: Path, dest: Path) -> Path:
    subprocess.run(["git", "clone", "-q", "--bare", str(src), str(dest)], check=True, capture_output=True)
    return dest


def show(repo: Path, rev: str, path: str) -> bytes:
    return subprocess.run(["git", "-C", str(repo), "show", f"{rev}:{path}"], capture_output=True, check=True).stdout


def dumps(doc) -> bytes:
    return (json.dumps(doc, indent=2, ensure_ascii=False) + "\n").encode()


SOURCE_FILES = {
    "seed/bootstrap/snowball_x.py": b"print('referee')\n",
    "seed/bootstrap/vectors/cases.json": b'{"cases": []}\n',
    "seed/bootstrap/workflow/bootstrap.yml": b"name: bootstrap\n",
    "spec/tohum/29-tohum-koltuklari.md": b"# Koltuklar\n",
    "spec/tohum/CHANGELOG.md": b"# Tohum\n- 2.2: `seed-046-x` -> `29b:1`\n",
    "spec/tohum/00-giris.md": b"# Giris\n",
    "seed/founder/launch.py": b"# not delivered\n",
    "seed/security-ledger.jsonl": b'{"row_id": "s1"}\n',
}


class World:
    """S in a source repository, the referee and the brain as bare remotes, a work folder, a fake GitHub."""

    def __init__(self, source_files: dict[str, bytes] | None = None, referee_extra: dict[str, bytes] | None = None):
        self.tmp = Path(tempfile.mkdtemp(prefix="opa-epoch-"))
        self.source = self.tmp / "source"
        self.s = history(self.source, [(source_files or SOURCE_FILES, ("m", "m@example.invalid"))])[-1]
        self.summary = {"seed_commit": "a" * 40, "seed_tree_sha256": "b" * 64,
                        "seed_epochs": [{"bootstrap_sha256": "c" * 64, "commit": "d" * 40, "seed_sha256": None,
                                         "spec_tohum_sha256": "e" * 64}],
                        "honesty_exception": None,
                        "targets": [{"id": "copy", "kind": "copy", "unit_candidates": ["apps/alert-engine"]}]}
        referee = {"control.json": dumps({"kill_switch": False, "budget_state": "ok", "waived_refutations": []}),
                   "setup/summary.json": dumps(self.summary), "bootstrap/old_module.py": b"old\n",
                   "bootstrap/snowball_x.py": b"print('old referee')\n", "vectors/old.json": b"{}\n",
                   "seats/29-tohum-koltuklari.md": b"# eski\n", ".github/workflows/bootstrap.yml": b"name: old\n",
                   "policy.json": b"{}\n", **(referee_extra or {})}
        history(self.tmp / "referee-work", [(referee, ("op", "op@example.invalid"))])
        self.referee = bare(self.tmp / "referee-work", self.tmp / "referee.git")
        f0, self.f, self.c = history(self.tmp / "brain-work", [
            ({"spec/tohum/00-giris.md": b"# eski\n", "spec/tohum/gone.md": b"gone\n", "spec/INDEX.md": b"# index\n",
              "founder-ledger.jsonl": b""}, FOUNDER_ID),
            ({"harness/x.py": b"x = 1\n"}, FOUNDER_ID),
            ({"founder-ledger.jsonl": b'{"kind": "cost"}\n'}, LAUNCHER_ID)])
        self.brain = bare(self.tmp / "brain-work", self.tmp / "brain.git")
        self.work = self.tmp / "work"
        self.work.mkdir()
        (self.work / "snowball-founder.env").write_text("GITHUB_TOKEN=never-read\n", encoding="utf-8")
        (self.work / "pilot-log.md").write_text("# Snowball pilot günlüğü\n", encoding="utf-8")
        self.gh = FakeGitHub(self)

    def delivery(self, **kw):
        kw.setdefault("epoch_code", BOOT)
        return deliver.Delivery(self.s[:7], self.work, self.source, self.gh, Path(tempfile.mkdtemp(dir=self.tmp)),
                                wait_s=0, **kw)

    def run(self, dry_run: bool = False, **kw):
        out = io.StringIO()
        with mock.patch.dict(os.environ, OPERATOR), mock.patch.object(deliver, "WAIT_POLL_S", 0), \
                mock.patch.object(deliver, "say"), contextlib.redirect_stdout(out):
            code = self.delivery(**kw).run(dry_run=dry_run)
        return code, out.getvalue()

    def head(self, repo: Path) -> str:
        return g(repo, "rev-parse", "main")


class FakeGitHub:
    def __init__(self, world: World) -> None:
        self.world = world
        self.referee_repo, self.brain_repo = "o/referee", "o/brain"
        self.ci = [{"databaseId": 1, "headSha": world.s, "headBranch": "main", "event": "push",
                    "status": "completed", "conclusion": "success", "createdAt": "2026-11-03T08:00:00Z"}]
        self.verdicts = [{"head": world.c, "kind": "none", "verdict": "noop", "state": {"last_evaluated_sha": world.c}},
                         {"head": world.f, "kind": "code", "verdict": "accepted",
                          "state": {"last_evaluated_sha": world.f}}]
        self.dispatched, self.seen_at_wait, self.answer = [], [], None

    def remote(self, repo: str) -> str:
        return str({"o/referee": self.world.referee, "o/brain": self.world.brain}[repo])

    def ci_runs(self, sha):
        return self.ci

    def on_main(self, sha):
        return True

    def results(self):
        return self.verdicts

    def active_runs(self):
        control = json.loads(show(self.world.referee, "main", "control.json"))
        self.seen_at_wait.append((control["kill_switch"], self.world.head(self.world.brain)))
        return 0

    def dispatch(self, timeout_s):
        """The referee's own check (`cli._check_epoch`): the last row names the brain's head, the kill switch is off."""
        summary = json.loads(show(self.world.referee, "main", "setup/summary.json"))
        control = json.loads(show(self.world.referee, "main", "control.json"))
        head = self.world.head(self.world.brain)
        self.dispatched.append((control["kill_switch"], summary["seed_epochs"][-1]["commit"], head))
        result = self.answer or {"kind": "seed_update", "verdict": "noop", "head": head}
        return {"id": 77, "conclusion": "success"}, result


class DeliveryTest(unittest.TestCase):
    """The eight steps, and the copy's checks: CI, strays, S's blobs, CR bytes."""

    def test_one_command_does_the_eight_steps(self):  # epoch_security_ledger_not_delivered
        world = World()
        before = world.head(world.referee)
        real_open, io_open = builtins.open, io.open

        def guarded(opener):
            def open_(file, *a, **kw):
                if "snowball-founder.env" in str(file):
                    raise AssertionError("the delivery read the Founder's secrets")
                return opener(file, *a, **kw)
            return open_
        edit = {"targets": {"copy": {"unit_candidates": {"from": ["apps/alert-engine"], "to": ["web/modules/hr"]}}}}
        with mock.patch.object(builtins, "open", guarded(real_open)), mock.patch.object(io, "open", guarded(io_open)):
            code, _ = world.run(summary_edit=edit, note="İçerik: E526.")
        self.assertEqual(code, 0)
        # 5: D is one commit over the brain's head, spec/tohum is S's (a deleted page too), nothing else changed
        d = world.head(world.brain)
        self.assertEqual(g(world.brain, "rev-parse", f"{d}^"), world.c)
        self.assertEqual(g(world.brain, "rev-parse", f"{d}:spec/tohum"),
                         g(world.source, "rev-parse", f"{world.s}:spec/tohum"))
        self.assertEqual(g(world.brain, "diff", "--name-only", f"{d}^", d).split(),
                         ["spec/tohum/00-giris.md", "spec/tohum/29-tohum-koltuklari.md", "spec/tohum/CHANGELOG.md",
                          "spec/tohum/gone.md"])
        self.assertEqual(g(world.brain, "log", "-1", "--format=%s", d), f"Tohum dönemi: snowball-mcp {world.s[:7]}")
        # 3, 6, 7: kill switch on, the synced copy with the row, kill switch off: three commits on the referee
        commits = g(world.referee, "rev-list", "--reverse", f"{before}..main").split()
        self.assertEqual(len(commits), 3)
        self.assertIs(json.loads(show(world.referee, commits[0], "control.json"))["kill_switch"], True)
        self.assertIs(json.loads(show(world.referee, commits[2], "control.json"))["kill_switch"], False)
        self.assertEqual(world.gh.seen_at_wait, [(True, world.c)])  # the switch was on before D reached the brain
        # E541 (the Founder's report seed-047 (b)): genesis reads the seed's security ledger in the referee
        # repository's setup/, where the import keeps it; the epoch delivers it there byte for byte
        self.assertEqual(show(world.referee, commits[1], "setup/security-ledger.jsonl"),
                         SOURCE_FILES["seed/security-ledger.jsonl"])
        for src, dest in deliver.REFEREE_MAP:  # every byte of the copy is S's, the old files are gone
            self.assertEqual(g(world.referee, "ls-tree", "-r", "--name-only", commits[1], "--", dest).split(),
                             [dest + p[len(src):] for p in sorted(SOURCE_FILES) if p == src or p.startswith(src + "/")])
            self.assertEqual(g(world.referee, "rev-parse", f"{commits[1]}:{dest}"),
                             g(world.source, "rev-parse", f"{world.s}:{src}"))
        raw = show(world.referee, "main", "setup/summary.json").decode()
        summary = json.loads(raw)
        self.assertEqual(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", raw)  # the format is kept
        row = summary["seed_epochs"][-1]
        self.assertEqual((row["commit"], row["seed_sha256"], len(summary["seed_epochs"])), (d, None, 2))
        self.assertEqual(summary["seed_epochs"][0], world.summary["seed_epochs"][0])
        self.assertEqual(summary["targets"][0]["unit_candidates"], ["web/modules/hr"])
        self.assertEqual({k: v for k, v in summary.items() if k not in ("seed_epochs", "targets")},
                         {k: v for k, v in world.summary.items() if k not in ("seed_epochs", "targets")})
        self.assertEqual(world.gh.dispatched, [(False, d, d)])  # 7: verified with the switch off and D at the head
        # 8: the touch row, STOP gone (this run set it), no journal, the lock free again
        log = (world.work / "pilot-log.md").read_text(encoding="utf-8")
        self.assertIn(f"tohum dönemi teslim edildi (insan dokunuşu, `27`; `deliver_epoch.py`). Kaynak snowball-mcp "
                      f"`{world.s[:7]}`", log)
        self.assertIn(f"doğrulama 77: seed_update/noop/`{d[:7]}`. İçerik: E526.", log)
        self.assertFalse((world.work / "STOP").exists())
        self.assertFalse((world.work / deliver.JOURNAL).exists())
        lock = deliver.launch.LauncherLock(world.work / deliver.launch.LOCK_FILE)
        self.assertTrue(lock.acquire())
        lock.release()

    def test_a_red_or_missing_ci_writes_nothing(self):  # epoch_ci_not_checked
        sha = "f" * 40
        run = {"databaseId": 5, "headSha": sha, "headBranch": "main", "event": "push", "status": "completed",
               "conclusion": "success", "createdAt": "2026-11-03T08:00:00Z"}
        self.assertTrue(deliver.ci_green([run], sha)[0])
        for runs in ([], [dict(run, conclusion="failure")], [dict(run, status="in_progress", conclusion="")],
                     [dict(run, headBranch="ops/x")], [dict(run, event="workflow_dispatch")],
                     [run, dict(run, databaseId=6, conclusion="cancelled", createdAt="2026-11-03T09:00:00Z")]):
            self.assertFalse(deliver.ci_green(runs, sha)[0], runs)
        world = World()
        world.gh.ci = [dict(world.gh.ci[0], conclusion="failure")]
        heads = (world.head(world.referee), world.head(world.brain))
        with self.assertRaisesRegex(deliver.Refused, "step 1: ci.yml run 1 is completed/failure"):
            world.run()
        self.assertEqual((world.head(world.referee), world.head(world.brain)), heads)
        self.assertEqual(sorted(p.name for p in world.work.iterdir()), ["pilot-log.md", "snowball-founder.env"])

    def test_the_dry_run_prints_the_plan_and_writes_nothing(self):
        world = World()
        heads = (world.head(world.referee), world.head(world.brain))
        code, out = world.run(dry_run=True)
        self.assertEqual(code, 0)
        self.assertIn(f"Seed epoch of snowball-mcp {world.s[:7]} (ci.yml run 1 green)", out)
        for step in range(2, 9):
            self.assertIn(f"  {step}. ", out)
        self.assertEqual((world.head(world.referee), world.head(world.brain)), heads)
        self.assertEqual(sorted(p.name for p in world.work.iterdir()), ["pilot-log.md", "snowball-founder.env"])
        self.assertEqual(world.gh.dispatched, [])

    def test_a_stray_file_stops_it_and_a_second_run_continues(self):  # epoch_strays_unseen
        """2026-11-02: a `__pycache__` in the referee clone was staged. A stray file anywhere in a clone refuses; the
        kill switch is on by then, so STOP and the journal stay, and the next run continues from there."""
        world = World()
        real_clone = deliver.Delivery.clone

        def dirty_clone(self, repo, name):
            dest = real_clone(self, repo, name)
            if name == "referee":
                (dest / "__pycache__").mkdir()
                (dest / "__pycache__" / "x.cpython-312.pyc").write_bytes(b"\0")
            return dest
        with mock.patch.object(deliver.Delivery, "clone", dirty_clone):
            with self.assertRaisesRegex(deliver.Refused, r"stray files: \?\? __pycache__/x.cpython-312.pyc"):
                world.run()
        journal = json.loads((world.work / deliver.JOURNAL).read_text(encoding="utf-8"))
        self.assertEqual((journal["stop_created"], sorted(journal)),
                         (True, ["kill_on", "source_commit", "stop_created"]))
        self.assertTrue((world.work / "STOP").exists())
        self.assertEqual(world.head(world.brain), world.c)  # nothing reached the brain
        code, _ = world.run()
        self.assertEqual(code, 0)
        self.assertFalse((world.work / "STOP").exists())  # the first run set it
        self.assertEqual(len(g(world.referee, "rev-list", "main").split()), 4)  # one kill-on commit, not two
        with self.assertRaisesRegex(deliver.Refused, "stray files"):
            clone = Path(tempfile.mkdtemp(dir=world.tmp)) / "c"
            subprocess.run(["git", "clone", "-q", str(world.referee), str(clone)], check=True, capture_output=True)
            (clone / "notes.tmp").write_text("x", encoding="utf-8")
            deliver.stage(clone, deliver.expected_files(world.source, world.s, deliver.REFEREE_MAP))

    def staged_clone(self, world: World) -> tuple[Path, dict]:
        clone = Path(tempfile.mkdtemp(dir=world.tmp)) / "c"
        subprocess.run(["git", "-c", "core.autocrlf=false", "clone", "-q", "-c", "core.autocrlf=false",
                        str(world.referee), str(clone)], check=True, capture_output=True)
        expected = deliver.expected_files(world.source, world.s, deliver.REFEREE_MAP)
        deliver.stage(clone, expected)
        return clone, expected

    def test_a_staged_blob_that_is_not_s_refuses(self):  # epoch_blob_unchecked
        world = World()
        clone, expected = self.staged_clone(world)
        deliver.check_index(clone, expected)  # what stage left is S's
        for change in (lambda: (clone / "bootstrap/snowball_x.py").write_bytes(b"print('edited')\n"),
                       lambda: (clone / "bootstrap/extra.py").write_bytes(b"\n"),
                       lambda: g(clone, "update-index", "--chmod=+x", "--", "vectors/cases.json")):
            fresh, expected = self.staged_clone(world)
            clone = fresh
            change()
            g(clone, "add", "-A", "--", "bootstrap")
            with self.assertRaisesRegex(deliver.Refused, "staged blobs are not S's"):
                deliver.check_index(clone, expected)
        # a line-end attribute in the referee normalises S's CRLF bytes on `git add`: the blob is not S's
        files = dict(SOURCE_FILES, **{"seed/bootstrap/win.txt": b"a\r\nb\r\n"})
        world = World(files, {".gitattributes": b"* text=auto\n"})
        with self.assertRaisesRegex(deliver.Refused, r"staged blobs are not S's \(1\): bootstrap/win.txt"):
            world.run()

    def test_cr_bytes_in_the_staged_diff_refuse(self):  # epoch_cr_bytes_pass
        world = World(dict(SOURCE_FILES, **{"seed/bootstrap/win.txt": b"a\r\nb\r\n"}))
        clone, expected = self.staged_clone(world)  # S's own bytes, so the blobs are S's
        deliver.check_index(clone, expected)
        with self.assertRaisesRegex(deliver.Refused, "the staged diff has 2 CR bytes"):
            deliver.check_no_cr(clone)
        with self.assertRaisesRegex(deliver.Refused, "CR bytes"):
            world.run()
        self.assertEqual(world.head(world.brain), world.c)



class DeliveryGuardTest(unittest.TestCase):
    """What the delivery waits for and what it leaves: the referee's verdicts, the launcher, the operator's STOP."""

    def test_the_verification_must_be_the_delivery_itself(self):  # epoch_wrong_verdict_accepted
        d = "d" * 40
        self.assertIsNone(deliver.delivered({"kind": "seed_update", "verdict": "noop", "head": d}, d))
        for wrong in ({"kind": "seed_update", "verdict": "rejected", "head": d},
                      {"kind": "code", "verdict": "noop", "head": d},
                      {"kind": "seed_update", "verdict": "noop", "head": "e" * 40}, None):
            self.assertIsNotNone(deliver.delivered(wrong, d), wrong)
        world = World()
        world.gh.answer = {"kind": "seed_update", "verdict": "rejected", "head": None}
        with mock.patch.object(FakeGitHub, "dispatch", lambda self, t: ({"id": 9, "conclusion": "success"}, dict(
                self.answer, head=self.world.head(self.world.brain)))):
            with self.assertRaisesRegex(deliver.Refused, "step 7: referee run 9 .*seed_update/rejected"):
                world.run()
        self.assertTrue((world.work / "STOP").exists())  # the launcher does not start on an unverified epoch
        self.assertNotIn("teslim edildi", (world.work / "pilot-log.md").read_text(encoding="utf-8"))

    def test_the_last_push_is_judged(self):  # epoch_unjudged_push_delivered, epoch_unread_rejection_delivered
        """E385: no delivery over an unjudged push, nor over a rejection no session has read (the seed_update result
        carries no rejection block). A noop on the launcher's cost commit above the push does not hide its verdict."""
        f, c = "f" * 40, "c" * 40
        log = [(c, *LAUNCHER_ID), ("e" * 40, "op", "op@x"), (f, *FOUNDER_ID), ("0" * 40, *FOUNDER_ID)]
        chain = deliver.founder_chain(log, {"e" * 40})
        self.assertEqual(chain, [c, "e" * 40, f])
        self.assertEqual(deliver.founder_chain([(c, *LAUNCHER_ID)], set()), [])
        none_c = {"head": c, "kind": "none", "verdict": "noop", "state": {"last_evaluated_sha": c}}
        rejected = {"head": f, "kind": "code", "verdict": "rejected", "state": {"last_evaluated_sha": f}}
        old = {"head": "0" * 40, "kind": "code", "verdict": "accepted", "state": {"last_evaluated_sha": "0" * 40}}
        cases = [([old], [], "unjudged"), ([], [], "unjudged"),
                 ([none_c, dict(rejected, verdict="accepted")], [], "ok"),
                 ([none_c, rejected], [], "unread"),
                 ([none_c, rejected], [{"kind": "intervention", "brain_before": f}], "unread"),
                 ([none_c, rejected], [{"brain_before": "0" * 40}], "unread"),
                 ([none_c, rejected], [{"brain_before": c}], "ok"),
                 ([none_c], [], "unread"),  # its verdict is no longer among the results: only a session proves it
                 ([dict(rejected, kind="none", verdict="noop")], [], "ok")]  # a memory push is a noop itself
        for results, cycles, state in cases:
            self.assertEqual(deliver.judgement(chain, results, cycles)[0], state, (results, cycles))
        self.assertEqual(deliver.judgement([], [none_c], [])[0], "unjudged")
        world = World()
        world.gh.verdicts = [dict(rejected, head=world.f, state={"last_evaluated_sha": world.f})]
        heads = (world.head(world.referee), world.head(world.brain))
        with self.assertRaisesRegex(deliver.Refused, "no session has read it"):
            world.run()
        (world.work / "pilot-metrics.jsonl").write_text(json.dumps({"brain_before": world.c}) + "\n", encoding="utf-8")
        world.gh.verdicts = [{"head": "9" * 40, "state": {"last_evaluated_sha": "9" * 40}}]
        with self.assertRaisesRegex(deliver.Refused, "start the launcher for one cycle"):
            world.run()
        self.assertEqual((world.head(world.referee), world.head(world.brain)), heads)  # nothing written
        self.assertEqual(sorted(p.name for p in world.work.iterdir()),
                         ["launcher.lock", "pilot-log.md", "pilot-metrics.jsonl", "snowball-founder.env"])

    def test_the_operators_stop_stays(self):  # epoch_removes_the_operators_stop
        world = World()
        (world.work / "STOP").write_text("mine\n", encoding="utf-8")
        code, _ = world.run()
        self.assertEqual(code, 0)
        self.assertEqual((world.work / "STOP").read_text(encoding="utf-8"), "mine\n")

    def test_a_running_launcher_is_waited_for(self):
        world = World()
        held = deliver.launch.LauncherLock(world.work / deliver.launch.LOCK_FILE)
        self.assertTrue(held.acquire())
        try:
            with self.assertRaisesRegex(deliver.Refused, "step 2: the launcher still runs"):
                world.run()
        finally:
            held.release()
        self.assertFalse((world.work / "STOP").exists())  # nothing was written: the folder as it was found
        self.assertFalse((world.work / deliver.JOURNAL).exists())

    def test_another_unfinished_delivery_refuses(self):
        world = World()
        (world.work / deliver.JOURNAL).write_text(json.dumps({"source_commit": "1" * 40}), encoding="utf-8")
        with self.assertRaisesRegex(deliver.Refused, "unfinished delivery of 1111111"):
            world.run()

    def test_the_summary_and_control_rewrites(self):
        raw = dumps({"seed_commit": "a", "targets": [{"id": "copy", "unit_candidates": ["x"]}]}).decode()
        row = {"commit": "d" * 40}
        out = json.loads(deliver.with_epoch(raw, row, None))
        self.assertEqual(out["seed_epochs"], [row])  # the first delivery opens the list
        with self.assertRaisesRegex(deliver.Refused, "already ends with the row"):
            deliver.with_epoch(deliver.dumps(out), row, None)
        with self.assertRaisesRegex(deliver.Refused, "not in the format"):
            deliver.with_epoch(raw.replace("\n", "\r\n"), row, None)
        for edit, why in (({"seed_commit": {}}, "and/or"), ({"fields": []}, "and/or"),
                          ({"targets": {"toy": {}}}, "no target 'toy'"),
                          ({"targets": {"copy": {"kind": {"from": 1, "to": 2}}}}, "no field 'kind'"),
                          ({"targets": {"copy": {"unit_candidates": {"from": ["y"], "to": []}}}}, "is \\['x'\\]"),
                          ({"targets": {"copy": {"unit_candidates": {"to": []}}}}, "exactly from and to")):
            with self.assertRaisesRegex(deliver.Refused, why):
                deliver.with_epoch(raw, row, edit)

    def test_the_summary_edit_sets_a_top_level_field_naming_what_it_replaces(self):
        """E564: an owner's exception and its commitment come with the seed epoch whose seed reads them (`26c`): the
        edit names each key's present value (null: not there yet), so a stale edit refuses instead of overwriting."""
        # epoch_field_from_unchecked epoch_field_edits_the_tools_rows
        raw = dumps({"seed_commit": "a", "honesty_commitment": "c" * 64,
                     "targets": [{"id": "copy", "unit_candidates": ["x"]}]}).decode()
        row = {"commit": "d" * 40}
        exception = {"stage": 0, "carry_to": 1, "reason": "E286, E561"}
        edit = {"fields": {"spec_exception": {"from": None, "to": exception},
                           "spec_commitment": {"from": None, "to": "e" * 64},
                           "honesty_commitment": {"from": "c" * 64, "to": "f" * 64}},
                "targets": {"copy": {"unit_candidates": {"from": ["x"], "to": ["y"]}}}}
        out = json.loads(deliver.with_epoch(raw, row, edit))
        self.assertEqual(out, {"seed_commit": "a", "honesty_commitment": "f" * 64, "seed_epochs": [row],
                               "targets": [{"id": "copy", "unit_candidates": ["y"]}],
                               "spec_exception": exception, "spec_commitment": "e" * 64})
        for fields, why in (({"spec_commitment": {"from": "e" * 64, "to": "1" * 64}}, "is None, not"),
                            ({"honesty_commitment": {"from": None, "to": "1" * 64}}, "is 'c+', not None"),
                            ({"spec_commitment": {"from": None, "to": None}}, "to is not null"),
                            ({"spec_commitment": {"to": "1" * 64}}, "exactly from and to"),
                            ({"seed_epochs": {"from": None, "to": []}}, "this tool's row"),
                            ({"targets": {"from": None, "to": []}}, "its own edits")):
            with self.subTest(fields=fields), self.assertRaisesRegex(deliver.Refused, why):
                deliver.with_epoch(raw, row, {"fields": fields})
        control = dumps({"kill_switch": False, "budget_state": "ok"}).decode()
        self.assertEqual(deliver.with_kill_switch(control, True), control.replace("false", "true"))
        with self.assertRaisesRegex(deliver.Refused, "no boolean kill_switch"):
            deliver.with_kill_switch(dumps({"budget_state": "ok"}).decode(), True)

    def test_the_github_side_is_the_launchers(self):
        """The reads go through the launcher's retried `gh_json`; the dispatch and the results are the launcher's own,
        and its wait is not cut by the STOP this tool set; the result is the dispatched run's, not the newest."""
        work = Path(tempfile.mkdtemp(prefix="opa-gh-"))
        gh = deliver.GitHub(work, "o/brain", "o/referee", "o/source")
        calls = []

        def gh_json(*args):
            calls.append(args)
            if args[0] == "api":
                return {"status": "ahead"}
            if args[args.index("-R") + 1] == "o/referee":
                return [{"status": "in_progress"}, {"status": "completed"}, {"status": "queued"}]
            return [{"headSha": "s"}]
        with mock.patch.object(deliver.launch, "gh_json", side_effect=gh_json):
            self.assertEqual((gh.ci_runs("s"), gh.on_main("s"), gh.active_runs()), ([{"headSha": "s"}], True, 2))
        self.assertEqual(calls[0][:7], ("run", "list", "-R", "o/source", "--workflow", "ci.yml", "--commit"))
        self.assertEqual(calls[1], ("api", "repos/o/source/compare/s...main"))
        self.assertEqual(calls[2][:6], ("run", "list", "-R", "o/referee", "--workflow", "bootstrap.yml"))
        (work / "STOP").write_text("x", encoding="utf-8")
        self.assertFalse(gh.pilot.stopped())
        arts = [{"id": 1, "workflow_run": {"id": 41}}, {"id": 2, "workflow_run": {"id": 42}}]
        files = {1: {"result.json": b'{"head": "newest"}'}, 2: {"result.json": b'{"head": "dispatched"}'}}
        reader = type(gh.pilot)
        with mock.patch.object(reader, "state_artifacts", return_value=arts), \
                mock.patch.object(reader, "artifact_files", side_effect=lambda art: files[art["id"]]):
            with mock.patch.object(reader, "dispatch_referee", return_value={"id": "42", "conclusion": "success"}):
                self.assertEqual(gh.dispatch(60)[1]["head"], "dispatched")
            with mock.patch.object(reader, "dispatch_referee", return_value={"id": "43", "conclusion": "failure"}):
                self.assertIsNone(gh.dispatch(60)[1])

    def test_the_command_line(self):
        world = World()
        argv = [world.s[:7], "--work", str(world.work), "--source", str(world.source)]
        err = io.StringIO()
        out = io.StringIO()
        with mock.patch.object(deliver, "GitHub", lambda *a: world.gh), contextlib.redirect_stdout(out):
            self.assertEqual(deliver.main([*argv, "--dry-run"]), 0)
            world.gh.ci = []
            with contextlib.redirect_stderr(err):
                self.assertEqual(deliver.main(argv), 2)
        self.assertIn(f"Seed epoch of snowball-mcp {world.s[:7]}", out.getvalue())
        self.assertIn("refused: step 1: no ci.yml push run on main", err.getvalue())
        self.assertIn("nothing was written", err.getvalue())

    def test_the_readme_says_the_tool_does_the_eight_steps(self):
        readme = (FOUNDER / "README.md").read_text(encoding="utf-8")
        section = readme.split("## Tohum teslimi", 1)[1].split("\n## ", 1)[0]
        self.assertIn("python seed/founder/deliver_epoch.py", section)
        for refusal in ("CI", "STOP", "E385", "kill_switch", "CR", "blob", "seed_update", "--dry-run",
                        "snowball-founder.env"):
            self.assertIn(refusal, section)


if __name__ == "__main__":
    unittest.main()
