"""The operator's activation tools (`tohum/25a` 1, 2 and 9; `asama-0/10a` #aktarim, #oyuncak, "Kilidin açılışı"; `26c`):
the import (K1 of `seed/founder/ETKINLESTIRME.md`: E100, E275, E370; on git objects alone since E470), `stage-open`,
the stage lock the bootstrap reads on every pull, and Stage 1's batch tables, batch exit and batch transfer (K3: E331,
E371-E373, E375-E379, E388).

Nothing here signs or verifies with Sigstore: the seed's one call into it (`importer.verify_signature`) is replaced by a
recorder, as `test_flow` and `test_exit_checks` do. Every git repository is a local one. The trailing comment on a test
names the mutants it kills (`local/mutate.py`).
"""

import base64
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from snowball_bootstrap import canon, cli, config, gitio, importer, manifest as manifest_module, stagelock, stages, wiring
from snowball_bootstrap.canon import canonical, row_hash
from snowball_bootstrap.config import ConfigError
from snowball_bootstrap.container import RunResult
from snowball_bootstrap.decide import decide
from snowball_bootstrap.importer import ImportErrorStop, run_import
from snowball_bootstrap.manifest import check_stage, parse_manifest
from snowball_bootstrap.treehash import tree_hash

import test_exit_checks
from helpers import (GIT_IDENTITY, LOOP_YML, FakeRunner, bare_repo, commit, git_in, install_fake_claude, main_of,
                     make_repo, ok_result, plumbed, posix_only, sh, submit, tree_files)
from test_exit_checks import tar_of

BOOT = Path(__file__).resolve().parents[1]
ROOT = BOOT.parents[1]
ZERO = "0" * 64
TOY_DIR = "tests/fixtures/toy-repo"
BRAIN_FILES = {
    "referee/ledger/chain.py": "x = 1\n",
    "referee/gate/check.py": "y = 2\n",
    "referee/.github/workflows/loop.yml": LOOP_YML,
    f"{TOY_DIR}/app.py": "import os\n",
    f"{TOY_DIR}/README.md": "toy\n",
    "spec/tohum/00-cekirdek.md": "# core\n",
}
# What `import` must keep exactly as it found it (`25a` 1): the operator's files, the bootstrap referee and its workflow.
OPERATOR_FILES = {
    "policy.json": "{}\n",
    "bootstrap.json": "{}\n",
    "setup/summary.json": "{}\n",
    "seats/29-tohum-koltuklari.md": "seat\n",
    "vectors/vectors.json": "{}\n",
    "bootstrap/snowball_bootstrap/__init__.py": "seed\n",
    "bootstrap/workflow/bootstrap.yml": "name: copy\n",
    ".github/workflows/bootstrap.yml": "name: snowball-bootstrap\n",
}
IMPORT_KEYS = ["ts", "stage", "brain_sha", "referee_tree_sha256", "result_sha256", "toy_tree_sha256", "prev_hash",
               "row_hash"]
BATCH_KEYS = ["ts", "stage", "batch", "brain_sha", "referee_tree_sha256", "result_sha256", "prev_hash", "row_hash"]
DROP = object()  # a field a fixture leaves out


def write(root, files):
    for rel, content in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content if isinstance(content, bytes) else content.encode("utf-8"))


def read_all(root, skip=(".git",)):
    """Every file under ``root`` as {posix path: bytes}, ``skip`` top names left out."""
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*"))
            if p.is_file() and p.relative_to(root).parts[0] not in skip}


def chained(rows):
    """``rows`` (dicts without the chain fields) chained with the seed's canonical code, as JSONL bytes (`26`)."""
    out, prev = [], ZERO
    for row in rows:
        row = dict(row, prev_hash=prev)
        row["row_hash"] = row_hash(row)
        prev = row["row_hash"]
        out.append(row)
    return out, b"".join(json.dumps(r, separators=(",", ":")).encode("utf-8") + b"\n" for r in out)


def edited(base, over):
    """``base`` with ``over`` applied; a value ``DROP`` removes its key."""
    out = dict(base)
    for key, value in (over or {}).items():
        if value is DROP:
            out.pop(key, None)
        else:
            out[key] = value
    return out


def raw_tree(repo, entries):
    """A tree object of ``entries`` [(mode, name, sha)] in the order given, unchecked (`hash-object --literally`): what
    a brain's git can hold and git's own object check refuses."""
    out = b"".join(mode.encode() + b" " + name.encode("utf-8") + b"\0" + bytes.fromhex(sha) for mode, name, sha in entries)
    return git_in(repo, "hash-object", "-t", "tree", "-w", "--literally", "--stdin", data=out).decode().strip()


def lock_of(line, **over):
    """A well-formed lock naming the counter line ``line``."""
    return dict({"stage": 1, "pass_row_sha256": "1" * 64, "toy_state_head": "2" * 40, "copy_state_head": "3" * 40,
                 "import_line_sha256": hashlib.sha256(line).hexdigest()}, **over)


# The operator's policy once Stage 1 opens: Stage 0's rival brake and Stage 1's (`asama-1/10`, `26e`; E492).
STAGE1_POLICY = {"constitutional": {
    "monthly_cap_usd": 300, "stage_params": {"rival_min_attempts": 2, "repeat_reject_limit": 3},
    "stage_budgets": {"asama_0": {"rival_usd": 30}, "asama_1": {"rival_usd": 15}},
    "license_allowlist": ["MIT", "Apache-2.0"], "license_exceptions": {}}}


def without_stage1_brake(policy=STAGE1_POLICY):
    """``policy`` as Stage 0 wrote it: Stage 1's block gone."""
    out = json.loads(json.dumps(policy))
    del out["constitutional"]["stage_budgets"]["asama_1"]
    return out


def locked(root, brain_sha="4" * 40, batches=()):
    """Stage 0's transfer, the lock naming it and a transfer row for each of ``batches`` after it, under ``root``;
    the counter's rows."""
    rows, data = chained([{"ts": "2026-10-31T08:00:00Z", "stage": 0, "brain_sha": brain_sha,
                           "referee_tree_sha256": "d" * 64, "result_sha256": "e" * 64, "toy_tree_sha256": "f" * 64}] +
                         [{"ts": "2026-11-02T08:00:00Z", "stage": 1, "batch": b, "brain_sha": "5" * 40,
                           "referee_tree_sha256": "6" * 64, "result_sha256": "7" * 64} for b in batches])
    write(root, {"setup/imports.jsonl": data, "setup/stage.json": json.dumps(lock_of(data.split(b"\n")[0]))})
    return rows


class ImportCase(unittest.TestCase):
    """A brain with a referee tree and a toy, the signed result of its (A), and the operator's two repositories as their
    remotes: the referee repository, whose main holds the operator's files and the bootstrap referee, and the toy's.
    The import clones them bare, builds on their main and pushes; no working tree is involved (E470)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.work = Path(self.tmp.name)
        identity = mock.patch.dict(os.environ, GIT_IDENTITY)
        identity.start()
        self.addCleanup(identity.stop)
        self.brain = self.work / "brain"
        make_repo(self.brain, {"README.md": "brain\n"})
        write(self.brain, BRAIN_FILES)
        self.sha = commit(self.brain, {}, "referee and toy")
        self.hashes()
        self.result = self.work / "result.json"
        self.write_result()
        self.bundle = self.work / "result.json.sigstore.json"
        self.bundle.write_text("{}")
        self.referee = bare_repo(self.work / "referee.git", dict(OPERATOR_FILES, **{"control.json": CONTROL_ON}))
        self.toy = bare_repo(self.work / "toy.git", {"README.md": "toy main\n"})
        self.verified = []
        patcher = mock.patch.object(importer, "verify_signature",
                                    side_effect=lambda *a: self.verified.append(a))
        patcher.start()
        self.addCleanup(patcher.stop)

    def hashes(self):
        """The signed hashes of the brain commit's two parts (a placeholder where the spec gives a part none)."""
        def of(prefix, **rule):
            try:
                return tree_hash(gitio.archive(self.brain, self.sha, (prefix,)), prefix, **rule)
            except Exception:  # noqa: BLE001 - a tree the spec refuses: the import must refuse it before any hash
                return "0" * 64
        self.referee_hash = of("referee")
        self.toy_hash = of(TOY_DIR, forbid_operator_names=False, fold_case=True)

    def write_result(self, **exit_fields):
        exit_block = {"transferable": True, "brain_sha": self.sha, "referee_tree_sha256": self.referee_hash,
                      "toy_tree_sha256": self.toy_hash, "repeat_events": 0}
        exit_block.update(exit_fields)
        self.result.write_bytes(json.dumps({"kind": "exit", "verdict": "accepted", "head": self.sha,
                                            "exit": exit_block}, indent=2).encode("utf-8") + b"\n")

    def use_tree(self, files):
        """The brain commit becomes one holding exactly ``files`` (made from objects, any names), the signed result
        naming its hashes."""
        self.sha = plumbed(self.brain, files)
        self.hashes()
        self.write_result()

    def set_main(self, changes, repo=None):
        """A new main for ``repo`` (the referee's by default): its files with ``changes`` (None removes a path)."""
        repo = repo or self.referee
        files = tree_files(repo)
        for path, content in changes.items():
            if content is None:
                files.pop(path, None)
            else:
                files[path] = content
        git_in(repo, "update-ref", "refs/heads/main", plumbed(repo, files, parent=main_of(repo)))

    def run_import(self, toy=True):
        return run_import(self.result, self.bundle, "id", "py", str(self.brain), str(self.referee),
                          str(self.toy) if toy else None)

    def imports(self):
        return tree_files(self.referee).get("setup/imports.jsonl", b"")

    def heads(self):
        return main_of(self.referee), main_of(self.toy)

    def refused(self, says, toy=True):
        """The import stops naming ``says``, and neither repository's main moved."""
        before = self.heads()
        with self.assertRaises(ImportErrorStop) as caught:
            self.run_import(toy=toy)
        self.assertIn(says, str(caught.exception))
        self.assertEqual(self.heads(), before)
        return str(caught.exception)


CONTROL_ON = '{"kill_switch": true, "budget_state": "ok"}\n'


class ImportBuildsOnMainTest(ImportCase):
    """E470: the import builds the referee's next main from git objects: the brain's `referee/` tree at the top and what
    it keeps taken from main by exact name (`25a` 1; E100: the push judge stays)."""

    def test_the_bootstrap_its_workflow_and_the_operator_files_stay_as_they_were(self):  # import_keeps_no_bootstrap import_deletes_bootstrap_yml
        before, old_main = tree_files(self.referee), main_of(self.referee)
        self.run_import()
        after = tree_files(self.referee)
        for rel, content in before.items():
            self.assertEqual(after.get(rel), content, rel)
        self.assertEqual(after[".github/workflows/loop.yml"], LOOP_YML.encode("utf-8"))
        self.assertEqual(sorted(set(after) - set(before)),
                         [".github/workflows/loop.yml", "gate/check.py", "ledger/chain.py", "setup/imports.jsonl"])
        self.assertEqual(git_in(self.referee, "rev-parse", "refs/heads/main^").decode().strip(), old_main)
        self.assertEqual(tree_files(self.toy), {"README.md": b"toy\n", "app.py": b"import os\n"})

    def test_a_second_import_leaves_no_file_of_the_first_referee_tree(self):
        self.run_import()
        self.sha = commit(self.brain, {"referee/gate/check.py": None, "referee/gate/other.py": "z = 3\n"}, "next batch")
        self.hashes()
        self.write_result()
        self.run_import()
        after = tree_files(self.referee)
        self.assertNotIn("gate/check.py", after)
        self.assertEqual(after["gate/other.py"], b"z = 3\n")
        self.assertEqual(after[".github/workflows/bootstrap.yml"], b"name: snowball-bootstrap\n")
        self.assertEqual(after["bootstrap/snowball_bootstrap/__init__.py"], b"seed\n")
        self.assertEqual(len(self.imports().splitlines()), 2)

    def test_github_is_cleared_around_the_bootstraps_workflow(self):  # import_github_kept_whole
        self.set_main({".github/workflows/old.yml": "name: stale\n", ".github/CODEOWNERS": "* @x\n", "old/x.py": "x\n"})
        self.run_import()
        after = tree_files(self.referee)
        self.assertEqual([p for p in ("old/x.py", ".github/workflows/old.yml", ".github/CODEOWNERS") if p in after], [])
        self.assertEqual(after[".github/workflows/bootstrap.yml"], b"name: snowball-bootstrap\n")

    def test_the_commit_changes_only_the_counter_after_the_checked_tree(self):  # import_counter_only_change_unchecked
        """`26c:39-40`: the counter's row is in the same commit, appended to main's file; nothing else in `setup/`. A
        commit whose index took one more entry with the counter's (the eighth skeptic's A4) is refused."""
        self.set_main({"setup/notes.txt": "operator's\n"})
        self.run_import()
        main = main_of(self.referee)
        changed = git_in(self.referee, "diff-tree", "-r", "--name-only", "--no-commit-id", main).decode().split()
        self.assertIn("setup/imports.jsonl", changed)
        self.assertEqual([c for c in changed if c.startswith(("setup/", "bootstrap/", "policy", "seats/"))],
                         ["setup/imports.jsonl"])
        self.assertEqual(tree_files(self.referee)["setup/notes.txt"], b"operator's\n")
        real = importer._git

        def one_more(cwd, *args, **kw):
            out = real(cwd, *args, **kw)
            if args[:3] == ("update-index", "--add", "--cacheinfo"):
                blob = git_in(cwd, "hash-object", "-w", "--stdin", data=b"EVIL\n").decode().strip()
                real(cwd, "update-index", "--add", "--cacheinfo", f"100644,{blob},setup/notes.txt", index=kw["index"])
            return out
        with mock.patch.object(importer, "_git", side_effect=one_more):
            self.refused("more than the counter")

    def test_the_composed_tree_is_checked_before_anything_is_written(self):  # import_composed_unchecked import_composed_kept_unchecked import_composed_workflow_unchecked
        """A stray file, a kept file and the push judge changed in the composition (the eighth skeptic's A1: the
        workflow is kept by its own name, not by a top name) are each refused before anything is written."""
        real = importer._compose
        for label, extra in (("a stray file", "stray.py"), ("a kept file changed", "policy.json"),
                             ("the push judge changed", ".github/workflows/bootstrap.yml")):
            def compose(bare, work, referee_tree, kept, extra=extra):
                index, _tree = real(bare, work, referee_tree, kept)
                blob = git_in(bare, "hash-object", "-w", "--stdin", data=b"EVIL\n").decode().strip()
                git_in(bare, "update-index", "--add", "--cacheinfo", f"100644,{blob},{extra}", index=index)
                return index, git_in(bare, "write-tree", index=index).decode().strip()
            with self.subTest(label), mock.patch.object(importer, "_compose", side_effect=compose):
                self.refused("the composed tree")

    def test_the_import_reads_and_writes_no_working_tree(self):  # import_temp_left_behind
        """E470: it clones bare into a temporary directory of its own and removes it; a checkout of the referee
        repository, wherever one is, is never read or written (here the operator's checkout stands beside it)."""
        checkout = self.work / "checkout"
        sh(self.work, "git", "clone", "-q", str(self.referee), str(checkout))
        before = read_all(checkout, skip=())
        temps = self.work / "temps"
        temps.mkdir()
        with mock.patch.object(importer.tempfile, "tempdir", str(temps)):
            self.run_import()
        self.assertEqual(list(temps.iterdir()), [])
        self.assertEqual(read_all(checkout, skip=()), before)

    def test_main_that_moved_meanwhile_refuses_the_push(self):  # import_push_forced
        """The push is never forced: a commit that reached main after the clone (here while Sigstore is asked) stays,
        the import's is refused, no counter row lands, and the message names main as the remote has it now (E482)."""
        read = main_of(self.referee)

        def another_push(*_args):
            self.set_main({"policy.json": '{"x": 1}\n'})
        importer.verify_signature.side_effect = another_push
        with self.assertRaises(ImportErrorStop) as caught:
            self.run_import()
        moved = main_of(self.referee)
        self.assertNotEqual(moved, read)
        self.assertIn(f"the referee's main is now {moved} (the import read {read})", str(caught.exception))
        self.assertEqual(tree_files(self.referee)["policy.json"], b'{"x": 1}\n')
        self.assertNotIn("setup/imports.jsonl", tree_files(self.referee))

    def test_a_main_rewound_meanwhile_refuses_the_push(self):  # import_push_unleased
        """E482 (the eighth skeptic's S16): a main rewound after the clone (its last commit taken back) would take the
        import's commit as a fast-forward and bring the taken-back commit back with it; the lease on the main the import
        read refuses it, and the message names the main the remote has."""
        first = main_of(self.referee)
        self.set_main({"policy.json": '{"v": 2}\n'})
        second = main_of(self.referee)
        importer.verify_signature.side_effect = lambda *_a: git_in(self.referee, "update-ref", "refs/heads/main", first)
        with self.assertRaises(ImportErrorStop) as caught:
            self.run_import()
        self.assertEqual(main_of(self.referee), first)
        self.assertEqual(tree_files(self.referee)["policy.json"], b"{}\n")
        self.assertIn(f"the referee's main is now {first} (the import read {second})", str(caught.exception))

    def test_a_toy_main_that_moved_meanwhile_refuses_the_push(self):  # import_toy_push_forced
        """E482 (the eighth skeptic's A11): the toy's push carries a lease on the toy main the import read too; a commit
        that reached it after the fetch stays, and the referee is not pushed."""
        real = importer._check_pushed
        referee = main_of(self.referee)

        def moved(bare, work, name, commit, held):
            if name == "toy":
                self.set_main({"later.py": "x\n"}, repo=self.toy)
            return real(bare, work, name, commit, held)
        with mock.patch.object(importer, "_check_pushed", side_effect=moved), self.assertRaises(ImportErrorStop) as caught:
            self.run_import()
        self.assertIn("later.py", tree_files(self.toy))
        self.assertIn(f"the toy's main is now {main_of(self.toy)}; the referee was not pushed", str(caught.exception))
        self.assertEqual(main_of(self.referee), referee)

    def test_the_callers_git_variables_do_not_reach_the_import(self):  # import_git_env_inherited
        """The eighth skeptic's A19: of the caller's GIT_* variables only the identity reaches the import's git; a
        GIT_DIR, GIT_INDEX_FILE or GIT_WORK_TREE of a shell inside a checkout redirects nothing."""
        decoy = bare_repo(self.work / "decoy.git", {"x.txt": "decoy\n"})
        before = (main_of(decoy), sorted(str(p) for p in decoy.rglob("*")))
        with mock.patch.dict(os.environ, {"GIT_DIR": str(decoy), "GIT_INDEX_FILE": str(self.work / "decoy-index"),
                                          "GIT_WORK_TREE": str(self.work), "GIT_OBJECT_DIRECTORY": str(decoy / "objects")}):
            self.run_import()
        self.assertEqual((main_of(decoy), sorted(str(p) for p in decoy.rglob("*"))), before)
        self.assertIn("setup/imports.jsonl", tree_files(self.referee))

    def test_no_hook_of_the_operators_runs_in_the_import(self):  # import_hooks_run
        """The eighth skeptic's A20: the operator's own configuration is read (identity, credentials), but a hook it
        names (`core.hooksPath`: here `pre-push` and `reference-transaction`) never runs in the import's repository."""
        home = self.work / "home"
        hooks = home / "hooks"
        hooks.mkdir(parents=True)
        ran = self.work / "ran.log"
        for name in ("pre-push", "reference-transaction"):
            hook = hooks / name
            hook.write_text(f'#!/bin/sh\necho "{name} $PWD" >> "{ran.as_posix()}"\ncat >/dev/null\nexit 0\n',
                            newline="\n")
            hook.chmod(0o755)
        (home / ".gitconfig").write_text(f"[core]\n\thooksPath = {hooks.as_posix()}\n", newline="\n")
        with mock.patch.dict(os.environ, {"HOME": str(home), "XDG_CONFIG_HOME": str(home / "xdg")}):
            self.run_import()
        lines = ran.read_text().splitlines() if ran.exists() else []
        self.assertTrue(lines, "the hooks run where git runs them (the remotes' side here)")
        self.assertEqual([line for line in lines if "snowball-import-" in line], [])

    def test_a_repository_given_as_a_relative_path_is_the_callers(self):
        """E485 (the eighth skeptic's p8_relpath): `--brain brain`, `--referee referee.git`, `--toy toy.git` name
        repositories in the caller's working directory, though git runs in the import's temporary directory."""
        cwd = os.getcwd()
        self.addCleanup(os.chdir, cwd)
        os.chdir(self.work)
        run_import(self.result, self.bundle, "id", "py", "brain", "referee.git", "toy.git")
        self.assertIn("setup/imports.jsonl", tree_files(self.referee))
        self.assertEqual(importer.located("https://example.invalid/r.git"), "https://example.invalid/r.git")
        self.assertEqual(importer.located("git@example.invalid:o/r.git"), "git@example.invalid:o/r.git")
        self.assertTrue(Path(importer.located("referee.git")).samefile(self.referee))
        self.assertTrue(importer.located("./a:b").endswith("a:b") and importer.located("./a:b") != "./a:b")

    @unittest.skipUnless(os.name == "nt", "a drive-relative path is Windows'")
    def test_a_drive_relative_path_is_the_drives(self):
        """E498 (the act10 skeptic): `C:rel` with the working directory on another drive is relative to C:'s own
        directory; kept as it was, git read it from the import's temporary directory. Windows' alone, so no mutant of
        the Linux mutation run measures it; red before the fix on Windows (register E498)."""
        here = os.path.splitdrive(os.getcwd())[0].upper()
        other = "D:" if here == "C:" else "C:"
        found = importer.located(other + "rel.git")
        self.assertTrue(os.path.isabs(found), found)
        self.assertEqual((found[:2].upper(), Path(found).name), (other, "rel.git"))
        self.assertEqual(importer.located(here + "rel.git"), os.path.join(os.getcwd(), "rel.git"))

    def test_an_empty_repository_name_stops(self):  # import_empty_name_is_the_cwd import_empty_toy_is_no_toy
        """E498: `--toy ""` (or an empty --brain or --referee) names nothing; read as a path it was the caller's working
        directory, and the command line made it no toy at all. It stops before anything is read."""
        for args in (("", str(self.referee), str(self.toy)), (str(self.brain), "", str(self.toy)),
                     (str(self.brain), str(self.referee), "")):
            with self.subTest(args=args), self.assertRaisesRegex(ImportErrorStop, "an empty repository name"):
                run_import(self.result, self.bundle, "id", "py", *args)
        argv = ["import", "--result", str(self.result), "--bundle", str(self.bundle), "--identity", "id",
                "--sigstore-python", "py", "--brain", str(self.brain), "--referee", str(self.referee), "--toy", ""]
        before = self.heads()
        self.assertEqual(cli.main(argv), 2)
        self.assertEqual((self.heads(), self.verified), (before, []))


class ImportTheToyTest(ImportCase):
    """`25a` 2, `asama-0/10a` #oyuncak: the toy's main gets a commit whose tree is the signed toy tree (E389, E470)."""

    def test_the_toys_main_becomes_the_signed_toy_tree(self):  # import_toy_tree_not_used
        self.set_main({"stale.py": "from an earlier toy\n", "old/x.txt": "x\n"}, repo=self.toy)
        old = main_of(self.toy)
        self.run_import()
        self.assertEqual(tree_files(self.toy), {"README.md": b"toy\n", "app.py": b"import os\n"})
        self.assertEqual(git_in(self.toy, "rev-parse", "refs/heads/main^").decode().strip(), old)

    def test_an_empty_toy_repository_gets_its_first_commit(self):
        shutil.rmtree(self.toy, onerror=lambda f, p, _e: (os.chmod(p, 0o700), f(p)))
        self.toy = bare_repo(self.work / "toy.git")
        self.run_import()
        self.assertEqual(tree_files(self.toy), {"README.md": b"toy\n", "app.py": b"import os\n"})

    def test_a_toy_that_holds_the_tree_already_is_left_as_it_is(self):  # import_toy_pushed_again
        self.run_import()
        toy = main_of(self.toy)
        self.sha = commit(self.brain, {"referee/gate/other.py": "z = 3\n"}, "the referee only")
        self.hashes()
        self.write_result()
        self.run_import()
        self.assertEqual(main_of(self.toy), toy)


class ImportRowTest(ImportCase):
    def test_the_row_is_26cs_chained_and_its_line_is_what_genesis_binds(self):
        """E275: `{ts, stage, brain_sha, referee_tree_sha256, result_sha256, toy_tree_sha256}` chained (`26`), one line
        of compact JSON in that order, LF only (`29o` hashes the line without its LF); a second import chains on."""
        first = self.run_import()
        lines = self.imports().split(b"\n")
        self.assertEqual(lines[-1], b"")
        row = json.loads(lines[0])
        self.assertEqual(list(row), IMPORT_KEYS)
        self.assertEqual(lines[0], json.dumps(row, separators=(",", ":")).encode("ascii"))
        self.assertNotIn(b"\r", self.imports())
        self.assertEqual((row["stage"], row["brain_sha"], row["referee_tree_sha256"], row["toy_tree_sha256"]),
                         (0, self.sha, self.referee_hash, self.toy_hash))
        self.assertEqual(row["result_sha256"], hashlib.sha256(self.result.read_bytes()).hexdigest())
        self.assertRegex(row["ts"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z\Z")
        self.assertEqual((row["prev_hash"], row["row_hash"]), (ZERO, row_hash(row)))
        self.assertEqual(first, row)
        second = self.run_import()
        rows = [json.loads(line) for line in self.imports().splitlines()]
        self.assertEqual(rows, [row, second])
        self.assertEqual((second["prev_hash"], second["row_hash"]), (row["row_hash"], row_hash(second)))

    def test_a_counter_whose_chain_is_broken_is_not_appended_to(self):  # import_counter_unread
        _rows, data = chained([{"ts": "2026-10-30T12:00:00Z", "stage": 0}])
        _rows, other = chained([{"ts": "2026-10-30T13:00:00Z", "stage": 0}])
        for broken in (data.replace(b'"stage":0', b'"stage":1'), data[:-1], b"not json\n", data + b"\n",
                       data.replace(b"\n", b"\r\n"), data + other,
                       data.replace(b'"stage":0', b'"stage":0,"stage":0')):
            with self.subTest(broken=broken[:40]):
                self.set_main({"setup/imports.jsonl": broken})
                before = self.heads()
                with self.assertRaises(ConfigError):
                    self.run_import()
                self.assertEqual(self.heads(), before)

    def test_a_counter_that_is_no_plain_file_is_not_appended_to(self):  # import_counter_mode_unchecked
        """The eighth skeptic's A5: main's counter as an executable or a link is not appended to (and turned into a
        plain file by the import's commit)."""
        _rows, data = chained([{"ts": "2026-10-30T12:00:00Z", "stage": 0}])
        for spec in (("100755", data), ("120000", b"../policy.json")):
            with self.subTest(mode=spec[0]):
                self.set_main({"setup/imports.jsonl": spec})
                self.refused("is not a plain file (mode 100644)")

    def test_a_non_transfer_touch_row_of_the_counter_is_chained_on(self):
        """`29n`, E277: the counter holds touches that are no transfer; the next row chains on its hash."""
        rows, data = chained([{"ts": "2026-10-30T12:00:00Z", "stage": 0}])
        self.set_main({"setup/imports.jsonl": data})
        row = self.run_import()
        self.assertEqual(row["prev_hash"], rows[0]["row_hash"])
        self.assertEqual(self.imports().split(b"\n")[0], data.split(b"\n")[0])


class ImportRefusesTest(ImportCase):
    def test_the_kill_switch_must_be_on(self):  # import_without_kill_switch
        """`25a` 1, `asama-0/10a` #aktarim: "Kill switch açık değilse çalışmaz", read from the main the import builds on;
        on means exactly true (E370)."""
        for control in ('{"kill_switch": false, "budget_state": "ok"}\n', '{"budget_state": "ok"}\n',
                        '{"kill_switch": "true"}\n', '{"kill_switch": 1}\n', "[true]\n", "not json\n", None):
            with self.subTest(control=control):
                self.set_main({"control.json": control})
                self.refused("kill switch")
                self.assertEqual(self.verified, [])  # checked first, before anything else

    def test_the_cli_stops_with_exit_2_when_the_kill_switch_is_off(self):
        self.set_main({"control.json": '{"kill_switch": false}\n'})
        argv = ["import", "--result", str(self.result), "--bundle", str(self.bundle), "--identity", "id",
                "--sigstore-python", "py", "--brain", str(self.brain), "--referee", str(self.referee),
                "--toy", str(self.toy)]
        before = self.heads()
        self.assertEqual(cli.main(argv), 2)
        self.assertEqual(self.heads(), before)

    def test_the_toy_tree_must_be_the_signed_toy_tree(self):  # import_toy_hash_unchecked
        self.write_result(toy_tree_sha256="1" * 64)
        self.refused("toy tree hash")

    def test_a_result_with_a_toy_hash_needs_the_toy_repository(self):  # import_without_toy
        self.refused("give --toy", toy=False)

    def test_the_referee_tree_must_be_the_signed_referee_tree(self):
        self.write_result(referee_tree_sha256="2" * 64)
        self.refused("referee tree hash")

    def test_a_result_that_is_not_accepted_and_transferable_is_refused(self):
        for exit_fields, verdict in (({"transferable": False}, "accepted"), ({}, "rejected"),  # I3_transferable_truthy
                                     ({"transferable": 1}, "accepted"), ({"transferable": "true"}, "accepted")):
            with self.subTest(verdict=verdict, exit=exit_fields):
                self.write_result(**exit_fields)
                if verdict != "accepted":
                    data = json.loads(self.result.read_text())
                    data["verdict"] = verdict
                    self.result.write_text(json.dumps(data))
                self.refused("transferable")

    def test_an_open_stage_lock_refuses_a_stage_0_import(self):  # import_after_the_lock_opened
        self.set_main({"setup/stage.json": "{}\n"})
        self.refused("the lock this Stage 0 result opened")

    def test_the_brain_commit_must_be_there(self):
        self.write_result(brain_sha="9" * 40)
        self.refused("git fetch failed")

    def test_a_link_or_a_submodule_in_a_part_stops(self):  # import_part_links_allowed
        """`26c`: no hash where a link or a special entry is; a link is never written into the referee's main."""
        for files, says in (({"referee/a.py": "x\n", "referee/l": ("120000", "../bootstrap"), f"{TOY_DIR}/app.py": "y\n"},
                             "referee/l is a link or a submodule"),
                            ({"referee/a.py": "x\n", "referee/m": ("160000", self.sha), f"{TOY_DIR}/app.py": "y\n"},
                             "referee/m is a link or a submodule"),
                            ({"referee/a.py": "x\n", f"{TOY_DIR}/app.py": "y\n", f"{TOY_DIR}/l": ("120000", "/etc")},
                             f"{TOY_DIR}/l is a link or a submodule")):
            with self.subTest(says=says):
                self.use_tree(files)
                self.refused(says)

    def test_the_referee_repository_needs_a_main(self):
        git_in(self.referee, "update-ref", "-d", "refs/heads/main")
        with self.assertRaises(ImportErrorStop) as caught:
            self.run_import()
        self.assertIn("no main", str(caught.exception))


class ImportRefusesNamesTest(ImportCase):
    """E470 (the third skeptic's case variants, short names, devices and trailing dots, four rounds of them on a file
    system): every name of a new part is refused at tree level, before any object is written, when the spec refuses it,
    when a file system reads it as another, when it is, holds or leads to what the import keeps in some case, or when
    two of them are one name case-folded. Each is refused because it is dangerous wherever the repository is checked out
    later; the import itself touches no disk."""

    def refuse_tree(self, paths, says, prefix="referee/"):
        files = {"referee/ledger/chain.py": "x = 1\n", f"{TOY_DIR}/app.py": "y\n"}
        files.update({prefix + p: "EVIL\n" for p in paths})
        self.use_tree(files)
        return self.refused(says)

    def test_a_name_that_is_holds_or_leads_to_a_kept_entry_in_some_case_is_refused(self):  # import_kept_case_sensitive import_overwrites_bootstrap_yml
        for path in (".github/workflows/bootstrap.yml", ".GitHub/Workflows/BOOTSTRAP.yml",
                     ".github/workflows/bootstrap.yml/x", ".github/workflows", ".github", "Bootstrap/x.py",
                     "BOOTSTRAP/snowball_bootstrap/__init__.py", "Control.json", "Setup/summary.json", "SEATS/x.md",
                     "Policy.json"):
            with self.subTest(path=path):
                self.refuse_tree([path], "what the import keeps, in some case")

    def test_names_a_windows_file_system_reads_as_others_are_refused(self):  # import_windows_names_allowed
        for path, says in (("x/a.", "a dot or a space"), ("x/a ", "a dot or a space"), ("x./a", "a dot or a space"),
                           ("x /a", "a dot or a space"), ("x/nul", "device"), ("x/NUL.txt", "device"),
                           ("x/con.py", "device"), ("x/aux", "device"), ("x/CONIN$", "device"),
                           ("x/COM¹", "device"), ("x/PRN.log", "device"), ("x/lpt9.c", "device"),
                           ("x/nul .txt", "device"), ("BOOTST~1/x.py", "8.3"), ("x/foo~2.txt", "8.3"),
                           ("a|b.py", "cannot hold"), ("q?.py", "cannot hold"), ("s*.py", "cannot hold"),
                           ('d".py', "cannot hold"), ("l<.py", "cannot hold"), ("g>.py", "cannot hold"),
                           ("x" * 200 + "/" + "y" * 60, "longer than Windows' 260")):
            with self.subTest(path=path):
                self.refuse_tree([path], says)

    def test_windows_names_are_refused_on_every_system(self):  # import_windows_chars_allowed import_long_paths_allowed
        """E484 (the eighth skeptic's S9: on Linux the import pushed them, on Windows git stopped half way): names a
        Windows checkout cannot hold are refused by the rule, before any object, wherever the import runs."""
        emoji = "\U0001f600" * 60  # 120 UTF-16 units, 60 code points, 240 bytes: a name within every limit
        for path in ("a|b.py", "x/q?.py", "s*.py", 'd".py', "l<.py", "g>.py", "x" * 250 + "/" + "y" * 250 + ".py",
                     f"{emoji}/{emoji}/" + "\U0001f600" * 11):  # 264 units, 133 code points: Windows counts units
            with self.subTest(path=path[:20]), self.assertRaises(ImportErrorStop):
                importer.refuse_names("referee", [path], importer.KEPT_PATHS)
        importer.refuse_names("referee", ["y" * 4 + "/" + "x" * 255, f"{emoji}/{emoji}/" + "\U0001f600" * 9,
                                          "a-b_c.d/e f(1)+[2]{3}'4'.py"])  # 260 units each: the longest path

    def test_a_name_longer_than_255_bytes_is_refused(self):  # import_long_names_allowed import_long_names_by_code_points import_long_names_by_utf16
        """E496 (the act10 skeptic's Q5: a 256-unit name was pushed): NTFS holds 255 UTF-16 units in one name, ext4 (the
        operator's WSL) 255 bytes; a name's UTF-8 bytes are never fewer than its units, so the byte count is the rule."""
        for name in ("x" * 256, "d/" + "x" * 256, "ş" * 128, "\U0001f600" * 64):  # 256 bytes each
            with self.subTest(name=name[:12]), self.assertRaisesRegex(ImportErrorStop, "a name longer than 255 bytes"):
                importer.refuse_names("referee", [name], importer.KEPT_PATHS)
        importer.refuse_names("referee", ["x" * 255, "d/" + "x" * 255, "ş" * 127, "\U0001f600" * 63])
        self.use_tree({"referee/ledger/chain.py": "x = 1\n", "referee/" + "n" * 256: "y\n", f"{TOY_DIR}/app.py": "y\n"})
        self.refused("a name longer than 255 bytes")

    def test_names_git_reads_for_itself_are_refused_in_any_form(self):  # import_gitattributes_allowed import_gitmodules_allowed import_git_names_unchecked import_hfs_names_allowed
        """E478, E479 (the eighth skeptic's S1, S2, F): `.gitattributes` (it changes a checkout's bytes: eol,
        working-tree-encoding over the kept files) and `.gitmodules` (it fetches from elsewhere) are no new part's, at
        any depth, in any case, and in HFS+'s form, the code points it ignores (git's `is_hfs_dotgit`); `.git`'s HFS+
        form too. NTFS's forms (`GIT~1`, `.git.`, `.git `, `.git::$DATA`) are names the Windows rules refuse."""
        attrs = "setup/** text eol=crlf\ncontrol.json text working-tree-encoding=UTF-16LE\n"
        for path, says in ((".gitattributes", "git's attributes"), ("ledger/.gitattributes", "git's attributes"),
                           (".GitAttributes", "git's attributes"), (".gitattributes\u200c", "git's attributes"),
                           ("\ufeff.gitattributes", "git's attributes"), (".gitmodules", "git's submodules"),
                           ("x/.GITMODULES", "git's submodules"), (".git\u200dmodules", "git's submodules")):
            with self.subTest(path=path):
                self.refuse_tree([path], says)
        self.use_tree({"referee/ledger/chain.py": "x = 1\n", "referee/.gitattributes": attrs, f"{TOY_DIR}/app.py": "y\n"})
        self.refused("git's attributes, which change a checkout's bytes")
        for path in ("x/.git\u200c/config", "x/.g\u200eit/hooks/post-checkout", "\u206a.GIT/config",
                     "x/.gitattributes\u202e", "x/.gitmodules\ufeff"):
            with self.subTest(path=path), self.assertRaises(ImportErrorStop) as caught:
                importer.refuse_names("referee", [path], importer.KEPT_PATHS)
            self.assertIn("in some case or form", str(caught.exception))
        for path, says in (("x/GIT~1/config", "8.3"), ("x/git~1", "8.3"), ("x/.git./config", "a dot or a space"),
                           ("x/.git /config", "a dot or a space"), ("x/.git::$INDEX_ALLOCATION/config", "colon"),
                           ("x/GITMOD~1", "8.3"), ("x/gi7eba~1", "8.3"), ("x/.gitmodules.", "a dot or a space")):
            with self.subTest(path=path), self.assertRaises(ImportErrorStop) as caught:
                importer.refuse_names("referee", [path], importer.KEPT_PATHS)
            self.assertIn(says, str(caught.exception))
        for path in ("bootstrap\u200c/snowball_bootstrap/__init__.py", "\u200dsetup/x.json"):  # kept names, folded
            with self.subTest(path=path), self.assertRaises(ImportErrorStop) as caught:
                importer.refuse_names("referee", [path], importer.KEPT_PATHS)
            self.assertIn("what the import keeps", str(caught.exception))

    def test_names_one_name_case_folded_are_refused(self):  # import_case_collision_allowed
        for paths in (["ledger/A.py", "ledger/a.py"], ["Ledger/x.py", "ledger/y.py"], [".GitHub/x.yml"],
                      [".github/Workflows/x.yml"]):
            with self.subTest(paths=paths):
                self.refuse_tree(paths, "one name case-folded")

    def test_names_the_spec_refuses_are_refused(self):
        for path in ("x/a\tb", "x\\y", "x/c:d"):
            with self.subTest(path=path):
                self.refuse_tree([path], "(`26c`, E470, E484)")
        for path in (".Git/config", "x/.git/hooks/h", "../x", "/x"):  # git builds no tree with these: the rule alone
            with self.subTest(path=path), self.assertRaises(ImportErrorStop):
                importer.refuse_names("referee", [path], importer.KEPT_PATHS)

    def test_the_toys_names_are_held_to_the_same_rules(self):  # import_toy_names_unchecked
        for paths, says in ((["a."], "a dot or a space"), (["Nul"], "device"), (["A.py", "a.py"], "case-folded"),
                            (["x/.gitattributes"], "git's attributes"), ([".gitmodules"], "git's submodules"),
                            (["a|b"], "cannot hold")):
            with self.subTest(paths=paths):
                self.refuse_tree(paths, says, prefix=f"{TOY_DIR}/")
        self.refuse_tree(["GIT~1/hooks/post-checkout"], "hasDotgit", prefix=f"{TOY_DIR}/")  # git's own fetch check

    def test_the_toy_holds_no_workflow(self):  # import_toy_github_allowed
        """E480 (the eighth skeptic's S17: a toy tree carrying `.github/workflows/run.yml` reached the toy's main): `25a`
        6, "oyuncakta iş akışı yoktur": no `.github`, at any depth, folded."""
        for path in (".github/workflows/run.yml", ".GitHub/dependabot.yml", "sub/.github/x.yml", ".git\u200chub/x.yml"):
            with self.subTest(path=path):
                self.refuse_tree([path], "the toy holds none (`25a` 6", prefix=f"{TOY_DIR}/")
        importer.refuse_names("referee", [".github/workflows/loop.yml"], importer.KEPT_PATHS)  # the referee's own


    def test_a_main_with_a_case_variant_of_a_kept_name_stops(self):  # import_main_case_variant
        """The third skeptic's `cv_detail.py` in git: a main whose `bootstrap/`, `.github/`, `setup/` or the push judge
        is under another case is refused, not dropped; a missing push judge or kill switch stops too."""
        files = tree_files(self.referee)
        for old, new in (("bootstrap/snowball_bootstrap/__init__.py", "Bootstrap/snowball_bootstrap/__init__.py"),
                         (".github/workflows/bootstrap.yml", ".GitHub/workflows/bootstrap.yml"),
                         ("setup/summary.json", "Setup/summary.json"),
                         (".github/workflows/bootstrap.yml", ".github/workflows/Bootstrap.yml")):
            with self.subTest(new=new):
                changed = dict(files)
                changed[new] = changed.pop(old)
                git_in(self.referee, "update-ref", "refs/heads/main", plumbed(self.referee, changed))
                self.refused("case variant")
        for gone, says in (("bootstrap/", "main has no bootstrap"),
                           (".github/workflows/bootstrap.yml", "main has no .github/workflows/bootstrap.yml")):
            with self.subTest(gone=gone):
                changed = {p: c for p, c in files.items() if not (p == gone or p.startswith(gone))}
                git_in(self.referee, "update-ref", "refs/heads/main", plumbed(self.referee, changed))
                self.refused(says)


class ImportChecksObjectsTest(ImportCase):
    """E479 (the eighth skeptic's B2, `p8_fsck.py`: a referee remote that checks what it receives, as GitHub does,
    refused the referee's push after the toy's had gone, for good): git's own object checks run before anything is
    pushed, on the brain's objects as they are fetched, and strictly on the bare repository holding both new commits."""

    def brain_with_a_bad_tree(self, kind):
        """The brain commit whose `referee/gate/` tree git's object check refuses: its entries out of git's order
        (an error), or a subtree's mode written with a leading zero (a warning, an error when strict)."""
        blob = lambda text: git_in(self.brain, "hash-object", "-w", "--stdin", data=text.encode()).decode().strip()
        if kind == "treeNotSorted":
            gate = raw_tree(self.brain, [("100644", "b.py", blob("b = 2\n")), ("100644", "a.py", blob("a = 1\n"))])
        else:
            sub = raw_tree(self.brain, [("100644", "a.py", blob("a = 1\n"))])
            gate = raw_tree(self.brain, [("040000", "sub", sub)])
        normal = plumbed(self.brain, {"referee/ledger/chain.py": "x = 1\n", "referee/.github/workflows/loop.yml": LOOP_YML,
                                      f"{TOY_DIR}/app.py": "import os\n"})

        def entries(treeish):
            rows = [line.split("\t", 1) for line in git_in(self.brain, "ls-tree", treeish).decode().splitlines()]
            return [(head.split()[0].lstrip("0"), name, head.split()[2]) for head, name in rows]
        referee = sorted(entries(normal + ":referee") + [("40000", "gate", gate)],
                         key=lambda e: e[1] + ("/" if e[0] == "40000" else ""))
        top = [(m, name, raw_tree(self.brain, referee) if name == "referee" else sha)
               for m, name, sha in entries(normal + "^{tree}")]
        self.sha = git_in(self.brain, "commit-tree", raw_tree(self.brain, top), data=b"brain").decode().strip()
        self.hashes()
        self.write_result()

    def test_the_brains_objects_are_checked_as_they_are_fetched(self):  # import_brain_fetched_unchecked
        for kind in ("treeNotSorted", "zeroPaddedFilemode"):
            with self.subTest(kind=kind):
                self.brain_with_a_bad_tree(kind)
                said = self.refused("git fetch failed")
                self.assertIn(kind, said)

    def test_what_would_be_pushed_is_checked_before_the_first_push(self):  # import_unchecked_before_push import_push_check_off import_push_check_by_option
        """The second gate, for an object no fetch checked (here the brain's fetch is made to check nothing): what the
        push would send is checked as a remote that checks what it receives does, and refused before anything is
        pushed: no object git refuses is pushed, whichever way it came (E479, E494)."""
        for kind, other in (("treeNotSorted", "zeroPaddedFilemode"), ("zeroPaddedFilemode", "treeNotSorted")):
            with self.subTest(kind=kind):  # each its own referee repository: one bad object at a time
                self.referee = bare_repo(self.work / f"referee-{kind}.git",
                                         dict(OPERATOR_FILES, **{"control.json": CONTROL_ON}))
                self.brain_with_a_bad_tree(kind)
                with mock.patch.object(importer, "FETCH_CHECKED", ()):
                    said = self.refused("git's object check refuses an object the push to the referee's main would "
                                        "send, one its main does not hold (E479, E494): nothing was pushed")
                self.assertIn(kind, said)
                self.assertNotIn(other, said)

    def bad_side_branch(self, repo, branch):
        """A commit whose tree git's object check refuses (a mode with a leading zero), on ``branch`` of ``repo``."""
        blob = git_in(repo, "hash-object", "-w", "--stdin", data=b"x\n").decode().strip()
        side = git_in(repo, "commit-tree", raw_tree(repo, [("0100644", "z", blob)]), data=b"side").decode().strip()
        git_in(repo, "update-ref", f"refs/heads/{branch}", side)
        return side

    def test_a_bad_object_on_another_referee_branch_stops_nothing(self):
        """The act10 skeptic's Q3 (E494): a legacy branch of the referee repository holds a tree git's strict check
        refuses; no push sends it, so the import goes through (it stopped every import for good). Two layers hold it:
        only main is cloned, and only what the push sends is checked; a mutant of either alone passes here and is
        killed by the tests below."""
        self.bad_side_branch(self.referee, "legacy")
        row = self.run_import()
        self.assertEqual(row["brain_sha"], self.sha)
        self.assertIn("ledger/chain.py", tree_files(self.referee))

    def test_a_bad_object_on_another_toy_branch_stops_nothing(self):
        """Q4 (E494): the toy repository's other branch (the Founder can push branches there) holds the same."""
        self.bad_side_branch(self.toy, "founder-side")
        self.run_import()
        self.assertEqual(tree_files(self.toy), {"README.md": b"toy\n", "app.py": b"import os\n"})

    def test_an_object_main_already_holds_is_not_checked_again(self):  # import_push_check_unseeded import_checks_the_whole_repository
        """E494: the remote holds its main's history, so a bad object there is never what the push sends: an old main
        commit with a tree git now refuses stops nothing, while the new commit reaches it as a parent."""
        old = self.bad_side_branch(self.referee, "old")
        files = tree_files(self.referee)
        git_in(self.referee, "update-ref", "refs/heads/main", plumbed(self.referee, files, parent=old))
        git_in(self.referee, "update-ref", "-d", "refs/heads/old")
        self.run_import()
        self.assertEqual(git_in(self.referee, "rev-parse", "refs/heads/main^^").decode().strip(), old)

    def test_the_import_reads_each_repository_s_main_alone(self):  # import_clone_every_branch import_toy_every_branch
        """E494: the referee repository is cloned with its main alone and the toy's main alone is fetched; the import's
        repository holds no other branch of either."""
        self.bad_side_branch(self.referee, "legacy")
        self.bad_side_branch(self.toy, "founder-side")
        seen = []
        real = importer._check_pushed

        def record(bare, work, name, commit, held):
            seen.append(sorted(gitio.git(bare, "for-each-ref", "--format=%(refname)").decode().split()))
            return real(bare, work, name, commit, held)
        with mock.patch.object(importer, "_check_pushed", side_effect=record):
            self.run_import()
        self.assertEqual(seen[0], ["refs/heads/main", "refs/toy/main"])

    def test_a_toy_branch_whose_name_ends_in_main_is_not_main(self):  # import_toy_main_by_name_tail
        """git's `ls-remote` matches a pattern against the end of a ref's name: a toy without main but with
        `x/refs/heads/main` has no main to build on, so the toy's commit is its first (it was fetched and stopped)."""
        git_in(self.toy, "update-ref", "refs/heads/x/refs/heads/main", main_of(self.toy))
        git_in(self.toy, "update-ref", "-d", "refs/heads/main")
        self.run_import()
        self.assertEqual(git_in(self.toy, "rev-list", "--count", "refs/heads/main").decode().strip(), "1")

    def test_an_empty_toy_is_fetched_as_none(self):
        """The toy is empty until the first import (`25` 10): no main to fetch, the toy's first commit has no parent."""
        self.toy = bare_repo(self.work / "empty-toy.git")  # no main, no commit
        self.run_import()
        self.assertEqual(tree_files(self.toy), {"app.py": b"import os\n", "README.md": b"toy\n"})
        self.assertEqual(git_in(self.toy, "rev-list", "--count", "refs/heads/main").decode().strip(), "1")


# ---------------------------------------------------------------- the batch transfer (`asama-1/13` 3, E378)

class BatchImportTest(ImportCase):
    """Once `setup/stage.json` opened Stage 1, the same command transfers the open batch's signed (A) (`25a` 1:
    "her parti çıkışında aynı komut"; `asama-1/06`: P1's (A), transfer and (B) come first). The toy is left as it is."""

    def setUp(self):
        super().setUp()
        self.stage0_rows, data = chained([{"ts": "2026-10-31T08:00:00Z", "stage": 0, "brain_sha": "c" * 40,
                                           "referee_tree_sha256": "d" * 64, "result_sha256": "e" * 64,
                                           "toy_tree_sha256": "f" * 64}])
        self.set_main({"setup/imports.jsonl": data, "setup/stage.json": json.dumps(lock_of(data.split(b"\n")[0]))})
        self.write_result(stage=1, batch="P1")

    def snapshot(self):
        """Main's lock and counter in a directory, as stagelock reads them."""
        snap = self.work / f"snap{len(list(self.work.glob('snap*')))}"
        files = tree_files(self.referee)
        write(snap, {p: files[p] for p in ("setup/imports.jsonl", "setup/stage.json") if p in files})
        return snap

    def test_the_open_batchs_result_is_transferred_and_its_row_names_the_batch(self):  # import_batch_refused import_batch_row_unnamed
        """`26c:39`: `{ts, stage, batch, brain_sha, referee_tree_sha256, result_sha256}` chained on, no toy hash."""
        toy = main_of(self.toy)
        row = self.run_import(toy=False)
        self.assertEqual(list(row), BATCH_KEYS)
        self.assertEqual((row["stage"], row["batch"], row["brain_sha"], row["referee_tree_sha256"]),
                         (1, "P1", self.sha, self.referee_hash))
        self.assertEqual(row["result_sha256"], hashlib.sha256(self.result.read_bytes()).hexdigest())
        self.assertEqual(row["prev_hash"], self.stage0_rows[-1]["row_hash"])
        self.assertEqual(main_of(self.toy), toy)
        self.assertEqual(tree_files(self.referee)["ledger/chain.py"], b"x = 1\n")
        snap = self.snapshot()
        self.assertEqual(stagelock.batches_done(snap, stagelock.load(snap)), ("P1",))

    def test_a_batch_is_transferred_once_and_only_the_open_one(self):  # import_batch_any
        self.run_import(toy=False)
        self.refused("open batch is 'P2'", toy=False)  # P1 is done; P2's table holds next (E491)
        self.write_result(stage=1, batch="P2")
        self.assertEqual(self.run_import(toy=False)["batch"], "P2")
        self.write_result(stage=1, batch="P2")
        self.refused("open batch is None", toy=False)  # P1 and P2 done; the seed carries no later batch table

    def test_a_batch_result_of_another_batch_or_stage_or_without_the_lock_is_refused(self):  # import_batch_stage_unchecked
        for fields, says in (({"stage": 1, "batch": "P2"}, "open batch is 'P1'"), ({"stage": 2, "batch": "P1"}, "Stage 2"),
                             ({"stage": True, "batch": "P1"}, "Stage True"), ({"batch": "P1"}, "Stage None")):
            with self.subTest(fields=fields):
                self.write_result(**fields)
                self.refused(says, toy=False)
        self.set_main({"setup/stage.json": None})
        self.write_result(stage=1, batch="P1")
        self.refused("only once setup/stage.json opened", toy=False)

    def test_a_batch_transfer_leaves_the_toy_alone(self):  # import_batch_touches_the_toy
        self.refused("without --toy", toy=True)


# ---------------------------------------------------------------- stage-open

TOY_TARGET = {"id": "toy-t", "repo": "owner/toy", "kind": "toy", "base_sha": None, "identifiers": [],
              "excluded_paths": [], "unit_candidates": []}
COPY_BASE = "ab" * 20
COPY_TARGET = {"id": "copy-t", "repo": "owner/copy", "kind": "copy", "base_sha": COPY_BASE, "identifiers": ["acme"],
               "excluded_paths": [], "unit_candidates": ["app"]}
OWNER_EXCEPTION = {"anchor": "durustluk", "stage": 0, "carry_to": 1, "reason": "E287", "carry_commitment": "c" * 64,
                   "measured": False}


class Target:
    """A target repository whose `brain/state` holds, under `<state_root>` (`.brain/`, `01a`, E417), a ledger and a root
    chain, as the loop referee writes them, and the last root's Sigstore bundle beside them, `chain/<root>.sigstore.json`
    (`26d`, E414): one `hashedrekord` log entry that records the root as its hash (`29j`). ``bundle`` stands another
    bundle there (False: none), ``uuid_suffix`` follows the root row's `rekor_uuid`, ``state_root`` puts the files
    elsewhere ("" the commit's top), ``extra`` adds files to the commit."""

    def __init__(self, path, rows, root_override=None, entry_hash=None, body=None, bundle=None, uuid_suffix="",
                 state_root=".brain/", extra=None):
        self.path = path
        make_repo(path, {"README.md": "main\n"})
        sh(path, "git", "checkout", "-q", "--orphan", "brain/state")
        sh(path, "git", "rm", "-q", "-rf", ".")
        self.rows, self.ledger = chained(rows)
        tips = {}
        for row in self.rows:
            if isinstance(row.get("part"), str):
                tips[row["part"]] = row["row_hash"]
        self.root = root_override or hashlib.sha256(canonical(tips)).hexdigest()
        recorded = entry_hash if entry_hash is not None else {"algorithm": "sha256", "value": self.root}
        signature = {"content": base64.b64encode(str(path).encode()).decode(), "publicKey": {"content": "x"}}
        entry = body(self.root, signature) if body else {"apiVersion": "0.0.1", "kind": "hashedrekord", "spec": {
            "data": {"hash": recorded}, "signature": signature}}
        self.body = json.dumps(entry, separators=(",", ":")).encode()
        self.uuid = "24296fb24b8ad77a" + hashlib.sha256(b"\x00" + self.body).hexdigest()
        self.roots, root_bytes = chained([{"row_id": "r1", "ts": "2026-10-31T10:00:00Z", "root": self.root,
                                           "rekor_uuid": self.uuid + uuid_suffix}])
        self.bundle = bundle if bundle is not None else json.dumps({
            "mediaType": "application/vnd.dev.sigstore.bundle.v0.3+json",
            "verificationMaterial": {"tlogEntries": [{"canonicalizedBody": base64.b64encode(self.body).decode()}]}
        }).encode()
        files = {"ledger.jsonl": self.ledger, "chain/root.jsonl": root_bytes, "status.md": "# status\n"}
        if self.bundle is not False:
            files[f"chain/{self.root}.sigstore.json"] = self.bundle
        write(path, dict({state_root + rel: content for rel, content in files.items()}, **(extra or {})))
        sh(path, "git", "add", "-A")
        sh(path, "git", "commit", "-q", "-m", "state")
        self.head = sh(path, "git", "rev-parse", "HEAD")
        sh(path, "git", "checkout", "-q", "main")

    def line_of(self, index):
        return self.ledger.split(b"\n")[index]


def event(kind, payload, part="events"):
    return {"row_id": f"{part}-{kind}", "ts": "2026-10-31T09:00:00Z", "part": part, "kind": kind, "payload": payload,
            "derivation": "tool", "trust": "verified", "snapshot_id": "0" * 40, "evidence_refs": []}


REFEREE_CODE = {"ledger/chain.py": "x = 1\n", "gate/check.py": "y = 2\n", ".github/workflows/loop.yml": LOOP_YML}


class StageOpenCase(unittest.TestCase):
    """The referee checkout after Stage 0's transfer (its commit holds the transferred referee tree beside what the
    import keeps), the signed (A) result it imported, and the two targets' state clones after (B): genesis rows naming
    the transfer, a copy merge, the PASS row on the toy carrying the copy's rows."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.work = Path(self.tmp.name)
        self.referee = self.work / "referee"
        make_repo(self.referee, dict(OPERATOR_FILES, **REFEREE_CODE))
        sh(self.referee, "git", "config", "core.autocrlf", "false")  # the bytes committed are the bytes written
        self.tree_sha = importer.committed_referee_hash(self.referee)  # what the transfer line names (E471)
        self.commit_referee({"policy.json": json.dumps(STAGE1_POLICY)})  # Stage 1's rival brake written (E492)
        self.write_summary()
        self.result = self.work / "result.json"
        self.write_signed()
        self.write_counter()
        self.made = 0
        self.copy = self.make_copy()
        self.toy = self.make_toy()
        self.verified = []

        def verify(subject, bundle, identity, sigstore_python):  # the bundle as Sigstore is given it, a file
            self.verified.append((subject, Path(bundle).read_bytes(), identity, sigstore_python))
        patcher = mock.patch.object(importer, "verify_signature", side_effect=verify)
        patcher.start()
        self.addCleanup(patcher.stop)

    def write_summary(self, targets=(TOY_TARGET, COPY_TARGET), **over):
        summary = {"seed_commit": "a" * 40, "seed_tree_sha256": "b" * 64, "targets": list(targets)}
        summary.update(over)
        self.commit_referee({"setup/summary.json": json.dumps(summary)})

    def commit_referee(self, files):
        """The operator's files, written and committed (None removes one): `stage-open` reads the checkout's commit,
        never its working tree (E478)."""
        for rel, content in files.items():
            if content is None:
                (self.referee / rel).unlink()
            else:
                write(self.referee, {rel: content})
        sh(self.referee, "git", "add", "-A", "--", *files)
        sh(self.referee, "git", "commit", "-q", "--allow-empty", "-m", "operator")

    def write_signed(self, **exit_fields):
        """The (A) result the import verified; its bytes' hash is the transfer row's `result_sha256`."""
        exit_block = edited({"requested": True, "transferable": True, "brain_sha": "c" * 40,
                             "referee_tree_sha256": self.tree_sha, "toy_tree_sha256": "f" * 64}, exit_fields)
        self.result.write_bytes(json.dumps({"kind": "exit", "verdict": "accepted", "exit": exit_block},
                                           indent=2).encode("utf-8") + b"\n")

    def write_counter(self, later=()):
        """Stage 0's transfer of the signed result, a touch that is no transfer (`29n`), then ``later`` rows."""
        self.import_rows, data = chained([
            {"ts": "2026-10-31T08:00:00Z", "stage": 0, "brain_sha": "c" * 40, "referee_tree_sha256": self.tree_sha,
             "result_sha256": hashlib.sha256(self.result.read_bytes()).hexdigest(), "toy_tree_sha256": "f" * 64},
            {"ts": "2026-10-31T08:30:00Z", "stage": 0}, *later])
        self.commit_referee({"setup/imports.jsonl": data})
        self.import_line = data.split(b"\n")[0]
        self.line_sha = hashlib.sha256(self.import_line).hexdigest()
        self.result_sha = self.import_rows[0]["result_sha256"]

    def bound(self, **over):
        """What a genesis row's payload binds of the transfer line (`29o`): its hash, its referee tree, its result."""
        return dict({"import_line_sha256": self.line_sha, "referee_tree_sha256": self.tree_sha,
                     "result_sha256": self.result_sha}, **over)

    def fresh(self, name):
        """A new directory for a target (a git repository's objects are read-only on Windows: none is removed)."""
        self.made += 1
        return self.work / f"{name}{self.made}"

    def copy_rows(self, genesis=None):
        return [event("genesis", edited(dict(self.bound(), target="copy-t", base_sha=COPY_BASE), genesis)),
                event("merge", {"c": 2}), event("status", {"b": 3})]

    def make_copy(self, rows=None, **kw):
        return Target(self.fresh("copy"), rows if rows is not None else self.copy_rows(), **kw)

    def toy_rows(self, genesis=None, payload=None, row=None):
        passed = event("pass", edited({"stage": 0, "verdict": "PASS", "import_line_sha256": self.line_sha,
                                       "copy_genesis_row_hash": self.copy.rows[0]["row_hash"],
                                       "copy_merge_row_hashes": [self.copy.rows[1]["row_hash"]]}, payload))
        return [event("genesis", edited(dict(self.bound(), target="toy-t"), genesis)),
                event("merge", {"c": 1}), event("cost", {"usd": 1}, part="cost"), edited(passed, row),
                event("status", {"b": 2})]

    def make_toy(self, rows=None, **kw):
        return Target(self.fresh("toy"), rows if rows is not None else self.toy_rows(), **kw)

    def argv(self, **over):
        args = {"--referee": self.referee, "--toy": self.toy.path, "--copy": self.copy.path,
                "--ref": "refs/heads/brain/state", "--identity": "loop-id", "--sigstore-python": "py",
                "--result": self.result}
        args.update(over)
        return ["stage-open"] + [str(x) for pair in args.items() for x in pair]

    def open(self):
        return stagelock.open_stage(self.referee, self.toy.path, self.copy.path, "refs/heads/brain/state", "loop-id",
                                    "py", self.result)

    def stage_file(self):
        return self.referee / "setup" / "stage.json"

    def refused(self, says):
        with self.assertRaises((ConfigError, ImportErrorStop, gitio.GitError)) as caught:
            self.open()
        self.assertIn(says, str(caught.exception))
        self.assertFalse(self.stage_file().exists())


class StageOpenWritesTest(StageOpenCase):
    def test_the_lock_is_26cs_five_fields_and_nothing_else(self):
        """`asama-0/10a`, `26c:40-41`, `25a` 9: `{stage: 1, pass_row_sha256, toy_state_head, copy_state_head,
        import_line_sha256}`, the hashes of the PASS line and the last transfer line without their LF (`29o`)."""
        self.assertEqual(cli.main(self.argv()), 0)
        lock = json.loads(self.stage_file().read_text(encoding="utf-8"))
        self.assertEqual(lock, {"stage": 1, "pass_row_sha256": hashlib.sha256(self.toy.line_of(3)).hexdigest(),
                                "toy_state_head": self.toy.head, "copy_state_head": self.copy.head,
                                "import_line_sha256": self.line_sha})
        self.assertEqual(self.stage_file().read_bytes(), canon.dump(lock).encode("utf-8"))  # LF, sorted, readable
        self.assertEqual(stagelock.load(self.referee), stagelock.Lock(**lock))  # what the bootstrap then reads

    def test_each_targets_last_root_is_verified_with_sigstore_as_the_root_digest(self):  # stage_open_root_not_signed stage_open_root_signs_another_artifact
        """E375, `29j`, `13`: the Rekor entry's hash is the root, so Sigstore verifies the bundle against the digest
        `sha256:<root>`, not against a file of the root's hex text (whose sha256 is not the root). The bundle is the one
        each target's `brain/state` keeps beside its root row (E414)."""
        self.open()
        self.assertEqual(self.verified, [(f"sha256:{self.toy.root}", self.toy.bundle, "loop-id", "py"),
                                         (f"sha256:{self.copy.root}", self.copy.bundle, "loop-id", "py")])

    def test_stage_open_is_a_command_the_operator_can_ask_for_help(self):
        with self.assertRaises(SystemExit) as caught:
            cli.build_parser().parse_args(["stage-open", "--help"])
        self.assertEqual(caught.exception.code, 0)


class SigstoreCallTest(unittest.TestCase):
    def test_the_seeds_sigstore_call_takes_a_digest_as_its_input(self):  # verify_subject_not_passed
        """sigstore 4.5.0 (`requirements/sign.txt`) reads an input `sha256:<hex>` as a digest, not as a file name."""
        calls = []
        with mock.patch.object(importer.subprocess, "run",
                               side_effect=lambda argv, **k: calls.append(argv) or mock.Mock(returncode=0)):
            importer.verify_signature("sha256:" + "a" * 64, Path("b.json"), "id", "py")
        self.assertEqual(calls[0][-1], "sha256:" + "a" * 64)
        self.assertEqual(calls[0][:5], ["py", "-m", "sigstore", "verify", "identity"])
        self.assertIn("sigstore==4.5.0", (BOOT / "requirements" / "sign.txt").read_text(encoding="utf-8"))


class StageOpenRefusesTest(StageOpenCase):
    def test_without_an_accepted_transferable_import(self):  # stage_open_without_a_transfer
        """Only a transfer (a row with `referee_tree_sha256`, `29o`) of Stage 0 opens Stage 1: a Stage 1 transfer of
        the very result in hand stops at the stage, before anything else is read."""
        signed = hashlib.sha256(self.result.read_bytes()).hexdigest()
        for rows in ([{"ts": "2026-10-31T08:30:00Z", "stage": 0}],
                     [{"ts": "2026-10-31T08:00:00Z", "stage": 1, "brain_sha": "c" * 40, "referee_tree_sha256": "d" * 64,
                       "result_sha256": signed}],
                     [{"ts": "2026-10-31T08:00:00Z", "stage": False, "brain_sha": "c" * 40,
                       "referee_tree_sha256": "d" * 64, "result_sha256": signed}]):
            with self.subTest(rows=rows):
                self.commit_referee({"setup/imports.jsonl": chained(rows)[1]})
                self.refused("the last transfer is not Stage 0's")
        self.commit_referee({"setup/imports.jsonl": None})
        self.refused("has no setup/imports.jsonl")

    def test_with_a_broken_counter(self):  # stage_open_counter_unchained
        data = (self.referee / "setup" / "imports.jsonl").read_bytes()
        self.commit_referee({"setup/imports.jsonl": data.replace(b'"stage":0', b'"stage":3', 1)})
        self.refused("setup/imports.jsonl line 1 breaks the chain")

    def test_without_the_pass_row(self):  # stage_open_without_pass stage_open_two_pass_rows stage_open_pass_any_part stage_open_pass_any_verdict stage_open_pass_any_stage
        first = self.toy_rows()[:3]
        for extra, says in (([], "no PASS row"),
                            ([event("pass", {"stage": 0, "verdict": "FAIL"})], "no PASS row"),
                            ([event("pass", {"stage": 1, "verdict": "PASS"})], "no PASS row"),
                            ([event("pass", {"stage": False, "verdict": "PASS"})], "no PASS row"),
                            ([event("pass", {"stage": 0, "verdict": "PASS"}, part="drill")], "no PASS row"),
                            ([self.toy_rows()[3], event("pass2", self.toy_rows()[3]["payload"])], "2 PASS rows")):
            with self.subTest(rows=[r["payload"] for r in extra]):
                self.toy = self.make_toy(first + extra)
                self.refused(says)

    def test_with_a_broken_toy_or_copy_chain(self):  # stage_open_chain_unchecked
        for name in ("toy", "copy"):
            with self.subTest(target=name):
                target = getattr(self, name)
                sh(target.path, "git", "checkout", "-q", "brain/state")
                data = target.ledger.replace(b'"c":', b'"C":', 1)
                write(target.path, {".brain/ledger.jsonl": data})
                sh(target.path, "git", "commit", "-q", "-am", "edit a row")
                sh(target.path, "git", "checkout", "-q", "main")
                self.refused(f"{name} brain/state .brain/ledger.jsonl")
                sh(target.path, "git", "branch", "-q", "-f", "brain/state", target.head)

    def test_when_the_ledger_moved_past_its_last_anchored_root(self):  # stage_open_root_not_the_tips
        """`13`, `29j` `verify_tip_moved`: the root anchors the head's tips; a tip past it is not anchored."""
        self.copy = self.make_copy(root_override="9" * 64)
        self.toy = self.make_toy()
        self.refused("copy")

    def test_when_the_root_bundle_is_not_the_root_rows_log_entry(self):  # stage_open_bundle_any_entry
        self.toy = self.make_toy(bundle=self.copy.bundle)
        self.refused("rekor_uuid")

    def test_when_the_log_entry_does_not_record_the_root(self):  # stage_open_entry_hash_unchecked
        """E375, `29j` `entry_root_mismatch`: the entry the root row names must record the root itself as its hash."""
        for recorded in ({"algorithm": "sha256", "value": hashlib.sha256(b"x").hexdigest()},
                         {"algorithm": "sha512", "value": None}, "not a hash"):
            with self.subTest(recorded=recorded):
                self.toy = self.make_toy(entry_hash=recorded)
                self.refused("entry_root_mismatch")
        self.assertEqual(self.verified, [])  # refused before Sigstore is asked

    def test_a_log_entry_of_another_kind_or_body_does_not_open_the_lock(self):  # stage_open_entry_kind_any
        """E406 (the skeptic's S2): only a `hashedrekord` body whose `spec.data.hash` is the root records it. Another
        kind carrying the same `spec.data.hash` (here `intoto`, and `rekord`) does not; nor does a Rekor v2 body
        (`hashedrekord` 0.0.2, the digest under `spec.hashedRekordV002`): the seed reads v0.0.1 bodies alone and is
        closed to any other until a seed epoch reads it (`26d` 8)."""
        bodies = {
            "intoto": lambda root, sig: {"apiVersion": "0.0.2", "kind": "intoto", "spec": {
                "data": {"hash": {"algorithm": "sha256", "value": root}}, "signature": sig}},
            "rekord": lambda root, sig: {"apiVersion": "0.0.1", "kind": "rekord", "spec": {
                "data": {"hash": {"algorithm": "sha256", "value": root}}, "signature": sig}},
            "hashedrekord v0.0.2": lambda root, sig: {"apiVersion": "0.0.2", "kind": "hashedrekord", "spec": {
                "hashedRekordV002": {"data": {"algorithm": "SHA2_256",
                                              "digest": base64.b64encode(bytes.fromhex(root)).decode()},
                                     "signature": sig}}},
        }
        for label, body in bodies.items():
            with self.subTest(body=label):
                self.toy = self.make_toy(body=body)
                self.refused("entry_root_mismatch")
        self.assertEqual(self.verified, [])
        self.toy = self.make_toy()  # the v0.0.1 hashedrekord body, as the vectors' `root` group has it, opens
        self.open()
        self.assertTrue(self.stage_file().exists())

    def test_when_sigstore_refuses_the_root(self):
        importer.verify_signature.side_effect = ImportErrorStop("signature verification failed: no")
        self.refused("signature verification failed")

    def test_without_the_targets_state_branch(self):
        self.copy = self.make_copy()
        sh(self.copy.path, "git", "branch", "-q", "-D", "brain/state")
        self.refused("brain/state")

    def test_when_the_lock_is_already_open(self):  # stage_open_overwrites stage_open_lock_in_the_commit_unread
        write(self.referee, {"setup/stage.json": '{"stage": 1}\n'})
        with self.assertRaises(ConfigError):
            self.open()
        self.assertEqual(self.stage_file().read_text(), '{"stage": 1}\n')
        self.commit_referee({"setup/stage.json": '{"stage": 1}\n'})  # committed, then gone from the disk (E478)
        self.stage_file().unlink()
        with self.assertRaises(ConfigError) as caught:
            self.open()
        self.assertIn("is already there", str(caught.exception))
        self.assertFalse(self.stage_file().exists())

    def test_a_referee_inside_its_checkout_is_refused(self):  # stage_open_from_a_subdirectory
        """E497 (the act10 skeptic): git reads a path argument from the directory it runs in, so `--referee` naming a
        directory inside the checkout found no lock in the commit and wrote one beneath itself; it is refused, with the
        lock committed or not, and nothing is written."""
        sub = self.referee / "bootstrap"
        for committed in (False, True):
            if committed:
                self.commit_referee({"setup/stage.json": '{"stage": 1}\n'})
            with self.subTest(committed=committed), self.assertRaises(stagelock.LockStop) as caught:
                stagelock.open_stage(sub, self.toy.path, self.copy.path, "refs/heads/brain/state", "loop-id", "py",
                                     self.result)
            self.assertIn("inside its checkout: give the checkout's top (E497)", str(caught.exception))
            self.assertFalse((sub / "setup").exists())


class StageOpenReadsTheCommitTest(StageOpenCase):
    """E478 (the eighth skeptic's S1 and E471's partial gap): the counter and `setup/summary.json` are the checkout's
    commit's, read from git: a checkout whose settings change the bytes on disk (`core.autocrlf`, which the Windows
    operator has) opens the lock, and what is only on the disk, edited or never committed, is not read."""

    def test_a_checkout_with_crlf_on_disk_opens_the_lock(self):  # stage_open_counter_from_disk
        clone = self.work / "crlf"
        sh(self.work, "git", "-c", "core.autocrlf=true", "clone", "-q", str(self.referee), str(clone))
        self.assertIn(b"\r\n", (clone / "setup" / "imports.jsonl").read_bytes())
        self.referee = clone
        self.open()
        self.assertTrue(self.stage_file().exists())

    def test_the_working_tree_is_not_read(self):  # stage_open_summary_from_disk
        counter = self.referee / "setup" / "imports.jsonl"
        summary = self.referee / "setup" / "summary.json"
        counter.write_bytes(counter.read_bytes() + b"not a row\n")
        summary.write_text(json.dumps({"seed_commit": "a" * 40, "seed_tree_sha256": "b" * 64, "targets": []}))
        self.open()
        self.stage_file().unlink()
        sh(self.referee, "git", "rm", "-q", "--cached", "setup/imports.jsonl")
        sh(self.referee, "git", "commit", "-q", "-m", "the counter only on the disk")
        self.refused("has no setup/imports.jsonl")


class StageOpenBindsTheCopyTest(StageOpenCase):
    """E376, `10a` #pass: the PASS row carries the copy's genesis and merge rows' hashes; `--copy` must be the clone of
    `setup/summary.json`'s copy target that holds them, and `--toy` the toy target's."""

    def test_the_toy_clone_given_as_the_copy_is_refused(self):  # SK_copy_target_any stage_open_copy_target_unchecked
        self.copy = self.toy
        self.refused("copy target 'copy-t'")

    def test_each_clone_is_its_targets(self):  # stage_open_first_row_unchecked
        for rows, name, says in ((self.toy_rows(genesis={"target": "copy-t"}), "toy", "toy target 'toy-t'"),
                                 (self.copy_rows(genesis={"target": "toy-t"}), "copy", "copy target 'copy-t'"),
                                 (self.copy_rows(genesis={"base_sha": "cd" * 20}), "copy", "base_sha"),
                                 (self.toy_rows()[1:], "toy", "toy target")):  # its first row is no genesis
            with self.subTest(name=name, says=says):
                if name == "copy":
                    self.copy = self.make_copy(rows)
                    self.toy = self.make_toy()
                else:
                    self.toy = self.make_toy(rows)
                self.refused(says)
                self.copy, self.toy = self.make_copy(), None
                self.toy = self.make_toy()

    def test_the_summary_names_one_toy_and_one_copy(self):  # stage_open_targets_unchecked
        for targets in ((TOY_TARGET,), (TOY_TARGET, COPY_TARGET, dict(COPY_TARGET, id="copy-2")), ()):
            with self.subTest(targets=[t["id"] for t in targets]):
                self.write_summary(targets)
                self.refused("one toy and one copy target")

    def test_the_pass_row_names_the_copys_genesis_and_merge_rows(self):  # stage_open_copy_rows_unchecked
        copy_rows = self.copy.rows
        for payload in ({"copy_genesis_row_hash": DROP}, {"copy_genesis_row_hash": "1" * 64},
                        {"copy_genesis_row_hash": copy_rows[1]["row_hash"]}):
            with self.subTest(payload=payload):
                self.toy = self.make_toy(self.toy_rows(payload=payload))
                self.refused("copy_genesis_row_hash")
        for merges in (DROP, [], ["2" * 64], [copy_rows[0]["row_hash"]], [copy_rows[1]["row_hash"]] * 2,
                       copy_rows[1]["row_hash"], [{"h": 1}]):
            with self.subTest(merges=merges):
                self.toy = self.make_toy(self.toy_rows(payload={"copy_merge_row_hashes": merges}))
                self.refused("copy_merge_row_hashes")
        # Two merges on the copy, both named (the status row is no merge, `26d` 6).
        self.copy = self.make_copy(self.copy_rows()[:2] + [event("merge", {"c": 3})] + self.copy_rows()[2:])
        merges = [r["row_hash"] for r in self.copy.rows if r["kind"] == "merge"]
        self.assertEqual(len(merges), 2)
        self.toy = self.make_toy(self.toy_rows(payload={"copy_merge_row_hashes": merges}))
        self.open()
        self.assertTrue(self.stage_file().exists())


class StageOpenBindsTheTransferTest(StageOpenCase):
    """E377, `29o`, `02` 5: the lock binds the referee (B) ran on. Both genesis rows name the counter's last transfer
    line; a transfer imported after it (no lock yet, so the import lets it in, `25a` "Başarısızlık") opens nothing."""

    def test_a_genesis_naming_another_import_line_is_refused(self):  # stage_open_genesis_line_unchecked
        for name in ("toy", "copy"):
            with self.subTest(name=name):
                if name == "toy":
                    self.toy = self.make_toy(self.toy_rows(genesis={"import_line_sha256": "9" * 64}))
                else:
                    self.copy = self.make_copy(self.copy_rows(genesis={"import_line_sha256": "9" * 64}))
                    self.toy = self.make_toy()
                self.refused(f"{name} brain/state: the last genesis row names another transfer")
                self.copy = self.make_copy()
                self.toy = self.make_toy()

    def test_a_second_stage_0_transfer_after_the_pass_opens_nothing(self):  # stage_open_import_line_of_the_last_row
        """(B) ran on the first transfer (both genesis rows name it); a second Stage 0 transfer imported after the PASS
        row is the counter's last, and its own signed result in hand does not open the lock either."""
        first = [{k: v for k, v in row.items() if k not in ("prev_hash", "row_hash")} for row in self.import_rows]
        self.write_signed(brain_sha="7" * 40)
        second = {"ts": "2026-10-31T12:00:00Z", "stage": 0, "brain_sha": "7" * 40, "referee_tree_sha256": self.tree_sha,
                  "result_sha256": hashlib.sha256(self.result.read_bytes()).hexdigest(), "toy_tree_sha256": "5" * 64}
        self.commit_referee({"setup/imports.jsonl": chained(first + [second])[1]})
        self.refused("toy brain/state: the last genesis row names another transfer than the counter's last one")


class StageOpenAfterARetransferTest(StageOpenCase):
    """E411 (the third skeptic's deadlock): `25a` 3 keeps `brain/state` (no deletion, no rewrite), so the first genesis
    row stays for good. After a red (B) the operator reverts the transfer, its counter line with it, and imports the
    fixed SHA (`asama-0/10a` "Başarısızlık"); (B) runs again from a new genesis row that names the new line. The lock
    binds each ledger's last genesis and counts only the rows after it."""

    def retransfer(self):
        """The fixed SHA's transfer is now the counter's only one; the first transfer's line hash is returned."""
        old = self.line_sha
        self.write_signed(brain_sha="9" * 40)
        rows, data = chained([{"ts": "2026-11-01T08:00:00Z", "stage": 0, "brain_sha": "9" * 40,
                               "referee_tree_sha256": self.tree_sha,
                               "result_sha256": hashlib.sha256(self.result.read_bytes()).hexdigest(),
                               "toy_tree_sha256": "f" * 64}])
        self.commit_referee({"setup/imports.jsonl": data})
        self.import_line = data.split(b"\n")[0]
        self.line_sha = hashlib.sha256(self.import_line).hexdigest()
        self.result_sha = rows[0]["result_sha256"]
        return old

    @staticmethod
    def again(row):
        return edited(row, {"row_id": row["row_id"] + "-2"})

    def two_runs(self, old):
        """Both ledgers after (B) on the first transfer (genesis, merge; no PASS) and the start of (B) on the second;
        the toy's rows so far (the copy is made)."""
        self.copy = self.make_copy([
            event("genesis", {"target": "copy-t", "base_sha": COPY_BASE, "import_line_sha256": old}),
            event("merge", {"c": 1}),
            self.again(event("genesis", dict(self.bound(), target="copy-t", base_sha=COPY_BASE))),
            self.again(event("merge", {"c": 2}))])
        return [event("genesis", {"target": "toy-t", "import_line_sha256": old}), event("merge", {"c": 3}),
                self.again(event("genesis", dict(self.bound(), target="toy-t"))),
                self.again(event("merge", {"c": 4}))]

    def passed(self, **over):
        """The second run's PASS row, naming the copy's second genesis and merge unless ``over`` names others."""
        payload = {"stage": 0, "verdict": "PASS", "import_line_sha256": self.line_sha}
        if "copy_genesis_row_hash" not in over:
            payload["copy_genesis_row_hash"] = self.copy.rows[2]["row_hash"]
        if "copy_merge_row_hashes" not in over:
            payload["copy_merge_row_hashes"] = [self.copy.rows[3]["row_hash"]]
        return event("pass", edited(payload, over))

    def test_b_run_again_from_a_new_genesis_opens_the_lock(self):  # stage_open_first_genesis_binds
        toy = self.two_runs(self.retransfer())
        self.toy = self.make_toy(toy + [self.passed()])
        lock = self.open()
        self.assertEqual((lock["import_line_sha256"], lock["pass_row_sha256"]),
                         (self.line_sha, hashlib.sha256(self.toy.line_of(4)).hexdigest()))

    def test_only_the_rows_after_the_last_genesis_count(self):  # stage_open_rows_before_genesis_count
        old = self.retransfer()
        toy = self.two_runs(old)
        for over, says in (({"copy_genesis_row_hash": self.copy.rows[0]["row_hash"]}, "copy's last genesis row"),
                           ({"copy_merge_row_hashes": [self.copy.rows[1]["row_hash"]]}, "after its last genesis")):
            with self.subTest(over=over):
                self.toy = self.make_toy(toy + [self.passed(**over)])
                self.refused(says)
        self.toy = self.make_toy(toy[:3] + [self.passed()])  # the toy's only merge is the first run's
        self.refused("comes before the toy's merge")
        first = event("pass", {"stage": 0, "verdict": "PASS", "import_line_sha256": old,
                               "copy_genesis_row_hash": self.copy.rows[0]["row_hash"],
                               "copy_merge_row_hashes": [self.copy.rows[1]["row_hash"]]})
        self.toy = self.make_toy(toy[:2] + [first] + toy[2:] + [self.passed()])  # the first run's PASS is not counted
        self.open()
        self.stage_file().unlink()
        self.toy = self.make_toy(toy[:2] + [first] + toy[2:])  # nor opens anything on its own
        self.refused("no PASS row after the last genesis")

    def test_each_ledger_is_its_targets_from_its_first_genesis_to_its_last(self):  # stage_open_copy_target_unchecked stage_open_first_row_unchecked
        """The ledger opens with its own target's genesis, and the genesis (B) ran from names that target too: a
        ledger whose later genesis is another target's, or that another target's genesis opened, opens nothing."""
        toy = self.two_runs(self.retransfer())
        other = edited(toy[2], {"payload": dict(toy[2]["payload"], target="copy-t")})
        self.toy = self.make_toy(toy[:2] + [other] + toy[3:] + [self.passed()])
        self.refused("toy brain/state: the last genesis row is not the genesis of setup/summary.json's toy target")
        first = edited(toy[0], {"payload": dict(toy[0]["payload"], target="copy-t")})
        self.toy = self.make_toy([first] + toy[1:] + [self.passed()])
        self.refused("toy brain/state: the first ledger row is not the genesis")

    def test_each_ledgers_last_genesis_names_the_last_transfer(self):  # stage_open_genesis_line_unchecked
        old = self.retransfer()
        toy = self.two_runs(old)
        stale = self.copy  # the copy's (B) never ran again: its last genesis names the first transfer
        self.copy = self.make_copy(self.copy_rows(genesis={"import_line_sha256": old}))
        self.toy = self.make_toy(toy + [self.passed(copy_genesis_row_hash=self.copy.rows[0]["row_hash"],
                                                    copy_merge_row_hashes=[self.copy.rows[1]["row_hash"]])])
        self.refused("copy brain/state: the last genesis row names another transfer")
        self.copy = stale
        later = self.again(self.again(event("genesis", {"target": "toy-t", "import_line_sha256": "9" * 64})))
        self.toy = self.make_toy(toy + [self.passed(), later])  # a later transfer's (B) began after the PASS row
        self.refused("toy brain/state: the last genesis row names another transfer")


class StageOpenReadsTheGenesisTest(StageOpenCase):
    """E416 (the third skeptic): the genesis row is read as one: an `events` row of `kind: genesis`, the referee's own
    (`25a` 7, `29o`, `26d`). A first row of another kind or part, or a player's, is no genesis, so the toy's merge can
    never be its genesis; and a PASS row whose `proposed_by` is null is named, not dropped."""

    def test_a_first_row_that_is_no_genesis_opens_nothing(self):  # stage_open_genesis_any_kind stage_open_genesis_any_part stage_open_genesis_proposed_ok
        for over in ({"kind": "status"}, {"part": "cost"}, {"kind": "merge"}, {"proposed_by": "founder"},
                     {"proposed_by": None}, {"trust": "inferred"}, {"derivation": "llm_inference"}):
            for name in ("toy", "copy"):
                with self.subTest(name=name, over=over):
                    if name == "toy":
                        rows = self.toy_rows()
                        self.toy = self.make_toy([edited(rows[0], over)] + rows[1:])
                    else:
                        rows = self.copy_rows()
                        self.copy = self.make_copy([edited(rows[0], over)] + rows[1:])
                        self.toy = self.make_toy()
                    self.refused(f"{name} brain/state: the first ledger row is not the genesis")
                    self.copy = self.make_copy()
                    self.toy = self.make_toy()

    def test_a_genesis_of_kind_merge_is_not_the_toys_merge(self):
        """The skeptic's `test_open_genesis_may_be_the_toys_merge`: the genesis payload as the toy's only merge row."""
        rows = self.toy_rows()
        self.toy = self.make_toy([edited(rows[0], {"kind": "merge"}), rows[2], rows[3], rows[4]])
        self.refused("the first ledger row is not the genesis")
        self.toy = self.make_toy([rows[0], rows[2], rows[3], rows[4]])
        self.refused("comes before the toy's merge")

    def test_a_pass_row_with_proposed_by_null_is_named_not_dropped(self):  # stage_open_proposal_null_dropped
        for value in (None, ""):
            with self.subTest(value=value):
                self.toy = self.make_toy(self.toy_rows(row={"proposed_by": value}))
                self.refused(f"not the referee's own row (`26`, `26d`; it has proposed_by {json.dumps(value)})")

    def test_a_ledger_row_without_a_part_stops(self):  # stage_open_part_unchecked
        rows = self.toy_rows()
        self.toy = self.make_toy(rows[:4] + [edited(rows[4], {"part": DROP})])
        self.refused("toy brain/state .brain/ledger.jsonl: a row has no part")


class StageOpenReadsTheRootTest(StageOpenCase):
    """E414: the root's bundle is the loop's, kept beside its root row in the same `brain/state` commit
    (`chain/<root>.sigstore.json`, `26d`); `rekor_uuid` is the tree id and the leaf hash and nothing more."""

    def test_without_the_bundle_in_brain_state(self):  # stage_open_bundle_missing_unnamed
        self.toy = self.make_toy(bundle=False)
        self.refused(f"no .brain/chain/{self.toy.root}.sigstore.json")
        self.assertEqual(self.verified, [])

    def test_a_rekor_uuid_with_more_after_it_is_refused(self):  # stage_open_uuid_unanchored
        for suffix in ("00", "\n", "g"):
            with self.subTest(suffix=suffix):
                self.toy = self.make_toy(uuid_suffix=suffix)
                self.refused("the last root row has no rekor_uuid")
        self.assertEqual(self.verified, [])


class StageOpenReadsTheStateRootTest(StageOpenCase):
    """E417 (the operator's decision under the owner's authority, 2026-11-01): `<state_root>` is the directory `01a:27-28`
    names, `.brain/` at the root of `brain/state`, as the Founder reads it (E58: the system's one folder). A ledger at
    the commit's top is not read; a profile naming another `state_root` stops, named: that needs a seed epoch."""

    def test_the_state_root_is_brain_not_the_commits_top(self):  # stage_open_state_root_top
        self.assertIsNotNone(gitio.file_at(self.toy.path, self.toy.head, ".brain/ledger.jsonl"))  # where it opens
        self.toy = self.make_toy(state_root="")
        self.refused("toy brain/state")
        self.refused("no .brain/ledger.jsonl (`<state_root>` is .brain/ at the root of brain/state")
        self.copy = self.make_copy(state_root="")
        self.toy = self.make_toy()
        self.refused("copy brain/state")
        self.refused("no .brain/ledger.jsonl")

    def test_a_profile_naming_another_state_root_stops(self):  # stage_open_state_root_any
        """`26b`'s profile carries `state_root`: one naming another directory than `.brain/` (here the loop wrote its
        state under `state/`; and a profile in `.brain/` naming `x/`) is named, not read as a missing ledger."""
        for state_root, profile_at, named in (("state/", "state/profile.json", "state/"),
                                              (".brain/", ".brain/profile.json", "x/")):
            with self.subTest(profile_at=profile_at):
                self.toy = self.make_toy(state_root=state_root,
                                         extra={profile_at: json.dumps({"state_root": named, "units": []})})
                self.refused(f"toy brain/state {self.toy.head}: {profile_at} names state_root {named!r}: a state_root "
                             "other than .brain/ needs a seed epoch")
        for value in (".brain/", ".brain"):  # `01a`'s own; and a security profile that names none (`30d`)
            with self.subTest(value=value):
                self.toy = self.make_toy(extra={".brain/profile.json": json.dumps({"state_root": value}),
                                                ".brain/security/profile.json": json.dumps({"classes": []})})
                self.open()
                self.stage_file().unlink()


class StageOpenBindsTheCommittedTreeTest(StageOpenCase):
    """E471 (the fourth skeptic's so06, so07): the lock opens on the referee the counter's last transfer wrote. The
    checkout's commit holds that referee tree (`26c`'s hash of its tree, what the import keeps left out, from git), and
    the last genesis rows bind the line's referee tree and signed result too (`29o`)."""

    def test_the_checkouts_commit_holds_the_transferred_referee_tree(self):  # stage_open_committed_tree_unread
        commit(self.referee, {"ledger/chain.py": "x = 2\n"}, "another referee tree")
        self.refused("the referee tree the checkout's commit holds is not the one the counter's last transfer line names")
        sh(self.referee, "git", "reset", "-q", "--hard", "HEAD~1")
        self.write_summary()
        self.write_counter()
        write(self.referee, {"ledger/chain.py": "edited, not committed\n"})  # the commit is read, not the disk
        self.open()
        self.stage_file().unlink()
        shutil.rmtree(self.referee / ".git", onerror=lambda f, p, _e: (os.chmod(p, 0o700), f(p)))
        self.refused("holds no commit")

    def test_the_last_genesis_binds_the_lines_tree_and_result(self):  # stage_open_genesis_tree_unbound stage_open_genesis_result_unbound
        for key in ("referee_tree_sha256", "result_sha256"):
            for value in ("0" * 64, DROP):
                for name in ("toy", "copy"):
                    with self.subTest(key=key, value=value, name=name):
                        if name == "toy":
                            self.toy = self.make_toy(self.toy_rows(genesis={key: value}))
                        else:
                            self.copy = self.make_copy(self.copy_rows(genesis={key: value}))
                            self.toy = self.make_toy()
                        self.refused(f"{name} brain/state: the last genesis row's {key} is not the counter's last")
                        self.copy = self.make_copy()
                        self.toy = self.make_toy()

    def test_a_copy_without_a_base_opens_nothing(self):  # stage_open_copy_base_any
        """so08: a copy target without `base_sha`, and its genesis without one, are no copy (`26c`, `29o`)."""
        for base, says in ((None, "copy target has no base_sha"), ("", "base_sha must be"), ("ab" * 19, "base_sha must be")):
            with self.subTest(base=base):
                self.write_summary(targets=(TOY_TARGET, dict(COPY_TARGET, base_sha=base)))
                self.copy = self.make_copy(self.copy_rows(genesis={"base_sha": base if base else DROP}))
                self.toy = self.make_toy()
                self.refused(says)


class StageOpenReadsTheProfilesTest(StageOpenCase):
    """E472 (so01, so02, so04; X1, X2): every `profile.json` of each target's commit is read as one plain JSON object,
    the copy's too; one that cannot be (a byte order mark, a key twice, not JSON) stops instead of being skipped, as
    skipped it could hide one naming another `state_root`."""

    def test_an_unreadable_profile_stops_on_either_target(self):  # stage_open_profile_unreadable_skipped
        for content, says in ((b"\xef\xbb\xbf" + json.dumps({"state_root": "state/"}).encode(), "BOM"),
                              (b'{"state_root":"state/","state_root":".brain/"}', "key 'state_root' twice"),
                              (b"not json", "is not a profile this seed can read"),
                              (b"\xff\xfe", "is not a profile this seed can read")):
            for name in ("toy", "copy"):
                with self.subTest(says=says, name=name):
                    target = (self.make_toy if name == "toy" else self.make_copy)(
                        extra={".brain/a/profile.json": content, "state/profile.json": json.dumps({"state_root": "x/"})})
                    setattr(self, name, target)
                    if name == "copy":
                        self.toy = self.make_toy()
                    self.refused(says)
                    self.copy = self.make_copy()
                    self.toy = self.make_toy()

    def test_a_profile_that_is_no_json_object_stops(self):  # stage_open_profile_not_object_skipped
        """E481 (the eighth skeptic's p8_stageopen): `26d` "Yer": every profile.json is one plain JSON object; an array,
        a string, a number or null naming nothing is not read past."""
        for content in (json.dumps([{"state_root": "elsewhere/"}]), '"elsewhere/"', "null", "1"):
            with self.subTest(content=content):
                self.toy = self.make_toy(extra={".brain/profile.json": content})
                self.refused("not a JSON object")
        self.toy = self.make_toy()

    def test_a_profile_that_is_a_link_or_a_submodule_stops(self):  # stage_open_profile_link_skipped
        """E481 (the eighth skeptic's B7): a profile.json that is a symbolic link or a submodule (entries a brain/state
        commit can hold, made here from objects) is not skipped."""
        for name in ("toy", "copy"):
            for entry in (("120000", "../elsewhere/profile.json"), ("160000", self.toy.head)):
                with self.subTest(name=name, mode=entry[0]):
                    target = getattr(self, name)
                    files = tree_files(target.path, "refs/heads/brain/state")
                    files[".brain/sub/profile.json"] = entry
                    target.head = plumbed(target.path, files, parent=target.head)
                    git_in(target.path, "update-ref", "refs/heads/brain/state", target.head)
                    self.refused(f"{name} brain/state {target.head}: .brain/sub/profile.json is not a profile this "
                                 "seed can read (not a regular file")
                    self.copy = self.make_copy()
                    self.toy = self.make_toy()

    def test_the_copys_profile_is_read_too(self):  # stage_open_copy_profile_unread
        self.copy = self.make_copy(state_root="state/", extra={"state/profile.json": json.dumps({"state_root": "state/"})})
        self.toy = self.make_toy()
        self.refused("copy brain/state")
        self.refused("names state_root 'state/': a state_root other than .brain/ needs a seed epoch")


class StageOpenReadsTheLogEntryTest(StageOpenCase):
    """E474 (so09, so10; X4, X5, X6): the bundle has one log entry, its body is strict base64 of a Rekor v1
    `hashedrekord` (`apiVersion` 0.0.1) whose `spec.data.hash` is `{algorithm: sha256, value: <root>}`: the root itself
    (`26d`). A player's genesis after the PASS row is no genesis (so05, Z1)."""

    def test_a_bundle_with_more_than_one_entry_stops(self):  # stage_open_log_entries_many
        one = json.loads(self.make_toy().bundle)["verificationMaterial"]["tlogEntries"][0]
        self.toy = self.make_toy(bundle=json.dumps({"verificationMaterial": {"tlogEntries": [one, one]}}).encode())
        self.refused("not one log entry")
        self.assertEqual(self.verified, [])

    def test_a_body_that_is_not_strict_base64_stops(self):  # stage_open_log_body_lenient
        made = self.make_toy()
        good = json.loads(made.bundle)["verificationMaterial"]["tlogEntries"][0]["canonicalizedBody"]
        for bad in (good[:4] + "*" + good[4:], good[:8] + "\n" + good[8:]):
            with self.subTest(bad=bad[:12]):
                self.toy = self.make_toy(bundle=json.dumps({"verificationMaterial": {"tlogEntries": [
                    {"canonicalizedBody": bad}]}}).encode())
                self.refused("is not a Sigstore bundle with one log entry")
        self.assertEqual(self.verified, [])

    def test_the_entry_records_the_root_with_sha256_in_a_v1_body(self):  # stage_open_entry_algorithm_any stage_open_api_version_any
        bodies = {
            "sha512 with the root's value": lambda root, sig: {"apiVersion": "0.0.1", "kind": "hashedrekord", "spec": {
                "data": {"hash": {"algorithm": "sha512", "value": root}}, "signature": sig}},
            "apiVersion 0.0.2 in the v1 shape": lambda root, sig: {"apiVersion": "0.0.2", "kind": "hashedrekord",
                                                                    "spec": {"data": {"hash": {"algorithm": "sha256",
                                                                                               "value": root}},
                                                                             "signature": sig}},
            "no apiVersion": lambda root, sig: {"kind": "hashedrekord", "spec": {
                "data": {"hash": {"algorithm": "sha256", "value": root}}, "signature": sig}},
        }
        for label, body in bodies.items():
            with self.subTest(label):
                self.toy = self.make_toy(body=body)
                self.refused("entry_root_mismatch")
        self.assertEqual(self.verified, [])

    def test_a_players_genesis_after_the_pass_row_is_no_genesis(self):  # stage_open_last_genesis_any_row
        rows = self.toy_rows()
        for over in ({"proposed_by": "founder", "trust": "inferred", "row_id": "p"}, {"trust": "inferred", "row_id": "i"}):
            with self.subTest(over=over):
                self.toy = self.make_toy(rows + [edited(rows[0], dict(over, payload={"target": "toy-t"}))])
                self.open()
                self.stage_file().unlink()


class StageOpenCarriesTheExceptionTest(StageOpenCase):
    """E379, `02` "Sahip istisnası": the PASS row carries the owner's exception by name, exactly as the signed (A)
    result names it, so the condition carried to Stage 1's (A) is not lost; `--result` is that result (its hash is the
    transfer row's `result_sha256`)."""

    def with_exception(self):
        self.write_signed(owner_exception=OWNER_EXCEPTION)
        self.write_counter()
        self.copy = self.make_copy()

    def test_the_pass_row_carries_the_signed_exception_exactly(self):  # stage_open_owner_exception_unchecked SK_exception_anchor_only
        self.with_exception()
        self.toy = self.make_toy()
        self.refused("owner_exception")
        for change in ({"anchor": "kok"}, {"carry_to": None}, {"carry_commitment": None}, {"measured": True},
                       {"measured": 0}, {"reason": "other"}, {"stage": DROP}, {"extra": 1}):
            with self.subTest(change=change):
                self.toy = self.make_toy(self.toy_rows(payload={"owner_exception": edited(OWNER_EXCEPTION, change)}))
                self.refused("owner_exception")
        self.toy = self.make_toy(self.toy_rows(payload={"owner_exception": dict(OWNER_EXCEPTION)}))
        self.open()
        self.assertTrue(self.stage_file().exists())

    def test_no_exception_is_carried_that_the_signed_result_does_not_name(self):  # stage_open_exception_one_sided
        self.toy = self.make_toy(self.toy_rows(payload={"owner_exception": dict(OWNER_EXCEPTION)}))
        self.refused("owner_exception")

    def test_the_result_must_be_the_one_the_transfer_imported(self):  # stage_open_result_unbound
        self.result.write_bytes(self.result.read_bytes() + b" ")
        self.refused("result_sha256")
        self.result.unlink()
        self.refused("cannot be read")


class StageOpenNeedsTheRefereesRowTest(StageOpenCase):
    """E388, E404, `26`, `13`, `26d`: rows the player proposes carry `proposed_by` and `trust: inferred`; only the
    referee's own PASS row opens the lock: no `proposed_by`, `trust` one of `26`'s other two, a merge-evidence
    derivation."""

    def test_a_player_proposed_or_inferred_pass_row_is_refused(self):  # stage_open_pass_inferred_allowed stage_open_pass_proposed_allowed stage_open_pass_derivation_any
        for row in ({"trust": "inferred"}, {"trust": DROP}, {"trust": "VERIFIED"}, {"derivation": "player"},
                    {"derivation": "llm_inference"}, {"derivation": DROP}):
            with self.subTest(row=row):
                self.toy = self.make_toy(self.toy_rows(row=row))
                self.refused("not the referee's own row")
        for row in ({"proposed_by": "founder"}, {"proposed_by": "founder", "trust": "inferred", "derivation": "player"}):
            with self.subTest(row=row):  # a proposal is no PASS row at all: it is left out before the count
                self.toy = self.make_toy(self.toy_rows(row=row))
                self.refused("no PASS row")
        self.toy = self.make_toy(self.toy_rows(row={"derivation": "test_verified"}))
        self.open()
        self.assertTrue(self.stage_file().exists())

    def test_26s_observed_trust_is_the_referees_too(self):  # stage_open_observed_refused
        """E404: `26` has three trust values and only `inferred` marks a player's proposal; an `observed` PASS row (the
        second skeptic's N3) is the referee's own and opens the lock."""
        self.toy = self.make_toy(self.toy_rows(row={"trust": "observed", "derivation": "tool"}))
        self.open()
        self.assertTrue(self.stage_file().exists())

    def test_a_proposed_copy_of_the_pass_row_is_left_out(self):  # stage_open_proposals_counted
        """E405 (the second skeptic): a player's proposed copy of the PASS row beside the referee's own made "2 PASS
        rows" and blocked the lock for good; rows with `proposed_by` are left out before the count (`26d` 3)."""
        rows = self.toy_rows()
        proposed = edited(rows[3], {"row_id": "events-proposed", "proposed_by": "founder", "trust": "inferred",
                                    "derivation": "llm_inference"})
        for at in (len(rows), 2):  # after the PASS row, and before it
            with self.subTest(at=at):
                self.toy = self.make_toy(rows[:at] + [proposed] + rows[at:])
                lock = self.open()
                self.assertEqual(lock["pass_row_sha256"], hashlib.sha256(self.toy.line_of(3 + (at == 2))).hexdigest())
                self.stage_file().unlink()


class StageOpenNeedsTheMergesTest(StageOpenCase):
    """E405, `26d` 4 and 6, `asama-0/08` rounds 2 and 9: the PASS row comes after the toy's merge, and every copy row it
    names as a merge is one: an `events` row of `kind: merge`, the referee's own."""

    def test_the_pass_row_may_not_come_before_the_toys_merge(self):  # stage_open_pass_before_merge
        rows = self.toy_rows()
        for order, label in (([rows[0], rows[3], rows[1], rows[2], rows[4]], "PASS right after genesis"),
                             ([rows[0], rows[2], rows[3], rows[4]], "no merge at all"),
                             ([rows[0], edited(rows[1], {"proposed_by": "founder", "trust": "inferred",
                                                         "derivation": "llm_inference"}), rows[3]], "a proposed merge"),
                             ([rows[0], edited(rows[1], {"part": "cost"}), rows[3]], "a merge outside events"),
                             ([rows[0], edited(rows[1], {"kind": "decision"}), rows[3]], "another kind")):
            with self.subTest(label):
                self.toy = self.make_toy(order)
                self.refused("comes before the toy's merge")
        self.toy = self.make_toy([rows[0], rows[1], rows[3]])
        self.open()

    def test_a_merge_row_is_the_referees_own(self):  # stage_open_merge_derivation_any stage_open_merge_trust_any
        """`26d`: a merge row's trust is `verified` or `observed` and its derivation one of the first three, as any row
        of the referee's own; an inferred merge, or one from an LLM's inference, is no merge on either ledger."""
        for over in ({"trust": "inferred"}, {"trust": DROP}, {"derivation": "llm_inference"},
                     {"derivation": "name_similarity"}, {"derivation": DROP}, {"proposed_by": None}):
            with self.subTest(over=over):
                rows = self.toy_rows()
                self.toy = self.make_toy([rows[0], edited(rows[1], over), rows[3]])
                self.refused("comes before the toy's merge")
                rows = self.copy_rows()
                self.copy = self.make_copy([rows[0], edited(rows[1], over)] + rows[2:])
                self.toy = self.make_toy()
                self.refused("each a merge row of the copy's ledger")
                self.copy = self.make_copy()

    def test_the_toys_merge_is_not_the_copys(self):  # stage_open_copy_merges_from_toy
        toy_merge = chained(self.toy_rows()[:2])[0][1]["row_hash"]
        self.toy = self.make_toy(self.toy_rows(payload={"copy_merge_row_hashes": [toy_merge]}))
        self.assertEqual(self.toy.rows[1]["row_hash"], toy_merge)
        self.refused("each a merge row of the copy's ledger")

    def test_each_named_copy_merge_is_a_merge_row(self):  # stage_open_copy_merge_any_row
        """The second skeptic: the copy's status row named as a merge passed (any later copy row did)."""
        status = self.copy.rows[2]
        self.assertEqual(status["kind"], "status")
        self.toy = self.make_toy(self.toy_rows(payload={"copy_merge_row_hashes": [status["row_hash"]]}))
        self.refused("each a merge row of the copy's ledger")
        self.toy = self.make_toy(self.toy_rows(payload={"copy_merge_row_hashes": [self.copy.rows[1]["row_hash"],
                                                                                status["row_hash"]]}))
        self.refused("each a merge row of the copy's ledger")
        proposed = edited(self.copy.rows[1], {"row_id": "events-merge-2", "proposed_by": "founder",
                                              "trust": "inferred", "derivation": "llm_inference"})
        proposed.pop("prev_hash"), proposed.pop("row_hash")
        self.copy = self.make_copy(self.copy_rows() + [proposed])
        self.toy = self.make_toy(self.toy_rows(payload={"copy_merge_row_hashes": [self.copy.rows[3]["row_hash"]]}))
        self.refused("each a merge row of the copy's ledger")
        # A proposal stays one with trust and derivation a referee row would have; and the copy's genesis is no merge
        # after it (S6, the first skeptic's): a genesis of kind merge is no genesis at all (E416).
        merge = edited(self.copy_rows()[1], {"proposed_by": "founder"})
        self.copy = self.make_copy(self.copy_rows()[:1] + [merge])
        self.toy = self.make_toy(self.toy_rows(payload={"copy_merge_row_hashes": [self.copy.rows[1]["row_hash"]]}))
        self.refused("each a merge row of the copy's ledger")
        self.copy = self.make_copy()
        self.toy = self.make_toy(self.toy_rows(payload={"copy_merge_row_hashes": [self.copy.rows[0]["row_hash"]]}))
        self.refused("each a merge row of the copy's ledger")
        genesis = edited(self.copy_rows()[0], {"kind": "merge"})
        self.copy = self.make_copy([genesis] + self.copy_rows()[1:])
        self.toy = self.make_toy(self.toy_rows(payload={"copy_merge_row_hashes": [self.copy.rows[0]["row_hash"]]}))
        self.refused("copy brain/state: the first ledger row is not the genesis")
        self.copy = self.make_copy()
        self.toy = self.make_toy(self.toy_rows(payload={"copy_merge_row_hashes": [self.copy.rows[1]["row_hash"]]}))
        self.open()


class StageOpenNamesTheTransferTest(StageOpenCase):
    """E405, `26d` 5, `10a` #pass (the trust root includes the operator transfer): the PASS row names the counter's
    last transfer line, as the genesis rows do."""

    def test_a_pass_row_naming_another_transfer_or_none_is_refused(self):  # stage_open_pass_line_unchecked
        for value in ("9" * 64, DROP, self.line_sha.upper(), None):
            with self.subTest(value=value):
                self.toy = self.make_toy(self.toy_rows(payload={"import_line_sha256": value}))
                self.refused("the PASS row names another transfer")

    def test_a_reverted_later_transfer_that_wrote_the_pass_row_opens_nothing(self):
        """The second skeptic's residual: transfer 1 is in place and the genesis rows name it; a later transfer 2's
        referee wrote the PASS row, then transfer 2 was reverted, so the counter's last line is transfer 1's again.
        Its PASS row names transfer 2's line: the lock does not open on transfer 1."""
        second = self.import_rows[0] | {"ts": "2026-10-31T12:00:00Z", "brain_sha": "7" * 40}
        second.pop("prev_hash"), second.pop("row_hash")
        _rows, data = chained([edited(r, {"prev_hash": DROP, "row_hash": DROP}) for r in self.import_rows] + [second])
        reverted_line = hashlib.sha256(data.split(b"\n")[2]).hexdigest()  # transfer 2's line, now gone
        self.toy = self.make_toy(self.toy_rows(payload={"import_line_sha256": reverted_line}))
        self.refused("the PASS row names another transfer")


class PassRowPageTest(unittest.TestCase):
    """E404 (the second skeptic's N3): the PASS row is written by the Founder's code and read by `stage-open`, so its
    format is an interface fact the seed owes on a page the Founder reads (it never sees seed code). `tohum/26d` names
    every field, value and rule `stagelock` applies, and the pages that point at the PASS row point there."""

    @staticmethod
    def flat(name):
        return " ".join((ROOT / "spec" / name).read_text(encoding="utf-8").split())

    def test_26d_names_what_stage_open_reads(self):  # stage_open_observed_refused stage_open_merge_any_kind
        from snowball_bootstrap import decide as decide_module
        page = self.flat("tohum/26d-semalar-pass-satiri.md")
        source = Path(stagelock.__file__).read_text(encoding="utf-8")
        for field in ("import_line_sha256", "copy_genesis_row_hash", "copy_merge_row_hashes", "owner_exception"):
            self.assertIn(f"`{field}`", page)
            self.assertIn(f'"{field}"', source)
        for value in stagelock.REFEREE_TRUST + stagelock.REFEREE_DERIVATIONS:
            self.assertIn(f"`{value}`", page)
        self.assertEqual(stagelock.REFEREE_TRUST, ("verified", "observed"))  # `26`'s three but a proposal's `inferred`
        for words in ("`part: events`", "`stage`: tamsayı `0`", '`verdict`: dizgi `"PASS"`', "`proposed_by` taşımaz",
                      "`kind: merge`", "Öneriler ayrıldıktan sonra", "son genesis ile onun arasında en az bir merge "
                      "satırı", "PASS satırı başka bir aktarımı adlandırıyorsa kilit açılmaz", "`hashedrekord`",
                      "`{algorithm: sha256, value: <kök>}`", "`sha256:<kök>`", "`pass_row_sha256`",
                      "`{anchor, stage, carry_to, reason, carry_commitment, measured}`",
                      f"`{decide_module.OWNER_EXCEPTABLE}`",
                      # E411-E416: the facts the third skeptic found missing
                      "`kind: genesis`", "Defterin ilk satırı o hedefin genesis'idir", "defterin son genesis satırıdır",
                      "yalnız ondan sonrakileri sayar", "`<state_root>` `01a`'nın adlandırdığı dizindir: hedefin `brain/state` "
                      "commit'inin kökündeki `.brain/`", "başka bir dizin adlandıran profil", "tohum dönemi ister",
                      "`.brain/chain/<kök>.sigstore.json`", "Paketi döngü yazar ve kök satırının yanında tutar",
                      "sonuncusu da, LF ile biter", "CR yoktur", "hiçbir anahtar iki kez geçmez",
                      "`proposed_by`'ı boş olmayan bir dizgi olan satır oyuncunun önerisidir", "`proposed_by: null`",
                      "Rekor v1 `hashedrekord`", "verinin hash'i kökün kendisidir", "en yüksek sürümü seçer",
                      "`--referee` klonunun commit'indeki hakem ağacı", "`payload.referee_tree_sha256`",
                      "kopyanın bir tabanı vardır", "okunamayan profil de durdurur", "katı base64",
                      "ardında hiçbir şey olamaz", "`--referee` klonunun commit'inden okunur, çalışma ağacından değil",
                      "tek düz JSON nesnesi olan düzenli dosyadır"):
            self.assertIn(words, page)
        self.assertEqual(stagelock.ROOT_BUNDLE, ".brain/chain/{root}.sigstore.json")  # `.brain/chain/<kök>.sigstore.json`
        self.assertIn("`stage-open` son genesis'i okur (`26d`)", self.flat("tohum/25a-kurulum-etkinlestirme.md"))
        self.assertIn("| `chain/<kök>.sigstore.json` (son kökün Sigstore paketi, `26d`) | `yaz` | `stage-open` |",
                      self.flat("tohum/27a-okuyucular-hedef-durumu.md"))
        tasks = {line.split("|")[1].strip(): line.split("|")[2] for line in
                 (ROOT / "spec" / "tohum" / "00b-gorev-haritasi.md").read_text(encoding="utf-8").splitlines()
                 if line.startswith("| ") and not line.startswith("| Görev")}
        for task in ("Şema ve araç imzası", "Aşama açma ve kapama", "Hakem bileşeni yazma (Aşama 0 ve partiler)"):
            self.assertIn("`26c`, `26d`", tasks[task], task)  # E414: the pages the Founder reads for the PASS row
        lines = (ROOT / "spec" / "tohum" / "26d-semalar-pass-satiri.md").read_text(encoding="utf-8").splitlines()
        self.assertRegex(lines[2], r"^Tarih: \d{4}-\d\d-\d\d · Sürüm: [\d.]+ · Durum: \w+ · Sahibi: operatör$")
        index = (ROOT / "spec" / "INDEX.md").read_text(encoding="utf-8")
        self.assertIn(f"| `tohum/26d-semalar-pass-satiri.md` | {lines[0].removeprefix('# ')} | "
                      f"{lines[3].removeprefix('Okunma: ')} |", index)
        self.assertIn("PASS satırı ve kilidin açılışı `26d`'de", self.flat("tohum/26-semalar.md"))
        self.assertIn("`26b`, `26c`, `26d`", self.flat("tohum/26-semalar.md"))  # the sources of field names
        self.assertIn("PASS satırının alanları ve komutun kuralı `26d`", self.flat("tohum/25a-kurulum-etkinlestirme.md"))


class ImportPageTest(unittest.TestCase):
    """E470: the operator reads `25a` 1-2, so they say what the import does, on git objects alone; and the copy into a
    checkout, its clearing, kept-state reading and junction handling are gone from the code with nothing using them."""

    def test_25a_says_the_git_object_procedure(self):
        page = PassRowPageTest.flat("tohum/25a-kurulum-etkinlestirme.md")
        for words in ("hiçbir çalışma ağacını okumaz ve yazmaz", "kendi geçici dizinine çıplak klonlar",
                      "`main`'den tam adıyla alınan korunanlardır", "sonda nokta ya da boşluk, aygıt adı, `~` ve rakam",
                      "harf duyarsız tek ad olan iki ad", "aynı commit'te `setup/imports.jsonl`'a bir satır ekler",
                      "zorlamadan itilir", "oyuncak önce, hakem sonra itilir", "`main`'in `control.json`'ıdır",
                      # E478-E485: the sixth round's facts
                      "`.gitattributes`", "`.gitmodules`", "HFS+'ın yok saydığı kod noktaları olmadan", '`\\|?*"<>`',
                      "260 karakterden uzun yol", "(`fetch.fsckObjects`)",
                      # E494-E498: the act10 skeptic's
                      "(`receive.fsckObjects`) her itmenin göndereceğini denetler", "yalnız `main`'i",
                      "`main`'in zaten tuttuğu nesne durdurmaz", "255 bayttan uzun tek ad", "boş repo adı durdurur",
                      "sürücüye göreli yol o sürücünün dizininden",
                      "(`--force-with-lease=refs/heads/main:<sha>`)", "ret uzak `main`'in o anki başını adlandırır",
                      "hiçbir derinlikte `.github` yok", "çağıranın dizininden okunur"):
            self.assertIn(words, page)
        source = Path(importer.__file__).read_text(encoding="utf-8")
        for gone in ("def _clear", "def kept_state", "O_EXCL", "samestat", "is_junction", "def disk_hash", "copytree"):
            self.assertNotIn(gone, source)
        self.assertLessEqual({"CON", "PRN", "AUX", "NUL", "COM1", "LPT9", "CONIN$", "CONOUT$"}, importer.DEVICES)


# ---------------------------------------------------------------- the lock the bootstrap reads on every pull

class LockReadTest(StageOpenCase):
    def lock(self, **over):
        return lock_of(self.import_line, **over)

    def test_no_file_is_stage_0(self):
        self.assertIsNone(stagelock.load(self.referee))

    def test_the_file_is_read_strictly(self):  # lock_keys_unchecked lock_stage_unchecked lock_hex_unchecked
        """`26c`: a missing or unknown field fails closed; test 29: a transition that does not match is refused."""
        good = self.lock()
        cases = [dict(good, extra=1), {k: v for k, v in good.items() if k != "copy_state_head"},
                 dict(good, stage=2), dict(good, stage=True), dict(good, stage="1"), dict(good, stage=0),
                 dict(good, pass_row_sha256="X" * 64), dict(good, toy_state_head="2" * 39),
                 dict(good, import_line_sha256="4" * 64)]
        for case in cases:
            with self.subTest(case=case):
                write(self.referee, {"setup/stage.json": json.dumps(case)})
                with self.assertRaises(ConfigError):
                    stagelock.load(self.referee)
        write(self.referee, {"setup/stage.json": json.dumps(good)})
        self.assertEqual(stagelock.load(self.referee).stage, 1)

    def test_the_import_line_must_be_a_stage_0_transfer_of_a_sound_counter(self):  # lock_line_any_row lock_transfer_of_any_stage
        rows, data = chained([{"ts": "2026-10-31T08:30:00Z", "stage": 0}])
        write(self.referee, {"setup/imports.jsonl": data,
                             "setup/stage.json": json.dumps(lock_of(data.split(b"\n")[0]))})
        with self.assertRaises(ConfigError):  # names the touch row, not a transfer
            stagelock.load(self.referee)
        write(self.referee, {"setup/imports.jsonl": data.replace(b"08:30", b"08:31")})
        with self.assertRaises(ConfigError):  # the chain no longer holds
            stagelock.load(self.referee)
        _rows, false = chained([{"ts": "2026-10-31T08:00:00Z", "stage": False, "brain_sha": "c" * 40,
                                 "referee_tree_sha256": "d" * 64, "result_sha256": "e" * 64}])
        write(self.referee, {"setup/imports.jsonl": false,  # G4_lock_transfer_stage_bool: false is no stage 0
                             "setup/stage.json": json.dumps(lock_of(false.split(b"\n")[0]))})
        with self.assertRaises(ConfigError) as caught:
            stagelock.load(self.referee)
        self.assertIn("not Stage 0's", str(caught.exception))
        _rows, batch = chained([{"ts": "2026-11-02T08:00:00Z", "stage": 1, "batch": "P1", "brain_sha": "5" * 40,
                                 "referee_tree_sha256": "6" * 64, "result_sha256": "7" * 64}])
        write(self.referee, {"setup/imports.jsonl": batch,  # Stage 1's own transfer
                             "setup/stage.json": json.dumps(lock_of(batch.split(b"\n")[0]))})
        with self.assertRaises(ConfigError):
            stagelock.load(self.referee)

    def test_a_later_batch_transfer_keeps_the_lock_and_is_read_as_done(self):  # lock_batches_unread
        """`asama-1/13`: the batches' transfers come after the lock; it still names its own line."""
        self.write_counter(later=[{"ts": "2026-11-02T08:00:00Z", "stage": 1, "batch": "P1", "brain_sha": "5" * 40,
                                   "referee_tree_sha256": "6" * 64, "result_sha256": "7" * 64}])
        write(self.referee, {"setup/stage.json": json.dumps(self.lock())})
        lock = stagelock.load(self.referee)
        self.assertEqual(lock.stage, 1)
        self.assertEqual(stagelock.batches_done(self.referee, lock), ("P1",))
        self.write_counter()
        self.assertEqual(stagelock.batches_done(self.referee, stagelock.load(self.referee)), ())

    def test_past_the_lock_only_the_stages_batch_transfers(self):  # lock_later_transfers_unchecked
        """A Stage 0 transfer after the lock's line, or a row of another stage or without its batch, stops the run."""
        for later in ({"stage": 0}, {"stage": 2, "batch": "P1"}, {"stage": 1}, {"stage": 1, "batch": "P 1"},
                      {"stage": True, "batch": "P1"}):
            with self.subTest(later=later):
                self.write_counter(later=[dict({"ts": "2026-11-02T08:00:00Z", "brain_sha": "5" * 40,
                                                "referee_tree_sha256": "6" * 64, "result_sha256": "7" * 64}, **later)])
                write(self.referee, {"setup/stage.json": json.dumps(self.lock())})
                with self.assertRaises(ConfigError) as caught:
                    stagelock.load(self.referee)
                self.assertIn("batch", str(caught.exception))

    def test_control_checks_the_lock_with_the_other_operator_files(self):  # lock_not_read_by_control
        referee = self.work / "ctl"
        shutil.copytree(self.referee, referee)
        write(referee, {
            "control.json": '{"kill_switch": false, "budget_state": "ok"}',
            "bootstrap.json": json.dumps({
                "brain_repo": "owner/brain", "brain_branch": "main",
                "image": "docker.io/library/python:3.12-slim@sha256:" + "a" * 64,
                "rival": {"model": "claude-sonnet-5-5", "effort": "medium", "max_turns": 30,
                          "per_run_cap_usd_micros": 3_000_000},
                "limits": {"test_timeout_s": 600, "reproducer_timeout_s": 120, "max_prompt_chars": 600_000,
                           "max_tree_bytes": 50_000_000}}),
            "policy.json": json.dumps({"constitutional": {
                "monthly_cap_usd": 300, "stage_params": {"rival_min_attempts": 2, "repeat_reject_limit": 3},
                "stage_budgets": {"asama_0": {"rival_usd": 30}},
                "license_allowlist": ["MIT"], "license_exceptions": {}}}),
            "setup/stage.json": json.dumps(self.lock(stage=2))})
        self.assertEqual(cli.main(["control", "--root", str(referee)]), 2)
        write(referee, {"setup/stage.json": json.dumps(self.lock())})
        self.assertEqual(cli.main(["control", "--root", str(referee)]), 0)


# ---------------------------------------------------------------- Stage 1's batch tables (E372, E378)

def batch_rows(name):
    """`asama-1/13`'s rows of batch ``name``: {MF: (tests, groups)}."""
    page = next((ROOT / "spec" / "asama-1").glob("13-*.md")).read_text(encoding="utf-8")
    rows = {}
    for line in page.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) == 5 and cells[0] == name and cells[1].isdigit():
            tests = [int(n) for n in cells[3].split(", ")] if re.fullmatch(r"[\d, ]+", cells[3]) else None
            groups = re.findall(r"`([a-z_]+)`", cells[4])
            rows[int(cells[1])] = (tests, groups)
    return rows


def page_batches():
    """The batches of `asama-1/13`'s micro-feature table, in the page's order."""
    page = next((ROOT / "spec" / "asama-1").glob("13-*.md")).read_text(encoding="utf-8")
    found = []
    for line in page.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) == 5 and cells[1].isdigit() and cells[0] not in found:
            found.append(cells[0])
    return found


class StageOneTableTest(unittest.TestCase):
    TABLE = stages.load(1)

    def test_the_table_is_the_p1_batchs_rows_of_asama_1_13(self):  # stage1_table_drifts
        """`asama-1/13` 1: the batch's table is in the seed and holds once `setup/stage.json` opened it. P1's comes
        first (`asama-1/06`: P1 ends before Stage 1's MF1 runs live). Tests and groups are the page's; module and calls
        are spec sessiz (E372)."""
        rows = batch_rows("P1")
        self.assertEqual(sorted(rows), list(range(1, 9)))
        self.assertEqual((self.TABLE.stage, self.TABLE.batch, self.TABLE.label), (1, "P1", "stage1-P1"))
        self.assertEqual({f.mf: (list(f.tests), list(f.groups)) for f in self.TABLE.mfs}, rows)

    def test_each_batch_is_a_table_of_its_own_in_the_pages_order(self):  # stage1_table_is_the_stages
        """E378, `26c:23` "Partilerin tabloları aynı dizindedir", `asama-1/06` "Partiler numarasızdır": a batch's table
        is named for its batch and numbers its own micro-features, so a later batch joins without renumbering; the
        batches the seed carries are the page's first ones, in its order, and no other table lies beside them."""
        order = page_batches()
        self.assertEqual(order[:2], ["P1", "P2"])
        self.assertEqual(list(stages.BATCHES[1]), order[:len(stages.BATCHES[1])])
        files = sorted(p.name for p in stages.STAGES_DIR.glob("*.json"))
        self.assertEqual(files, ["stage0.json"] + [stages.table_name(1, b) for b in stages.BATCHES[1]])
        data = json.loads((stages.STAGES_DIR / "stage1-P1.json").read_text(encoding="utf-8"))
        self.assertEqual((data["stage"], data["batch"]), (1, "P1"))
        with self.assertRaises(ConfigError):  # a batch table read as another batch's
            stages.parse_table(json.dumps(data), 1, "P2")
        with self.assertRaises(ConfigError):  # or as a stage table
            stages.parse_table(json.dumps(data), 1)

    def test_its_tests_are_section_09s_p1_tests_and_its_groups_the_seeds_p1_vectors(self):
        page = (ROOT / "spec" / "asama-0" / "09-harness-in-kendi-testleri.md").read_text(encoding="utf-8")
        p1 = {int(m.group(1)) for m in re.finditer(r"^\| (\d+) \| .* \| P1 \|$", page, re.M)}
        self.assertEqual({n for f in self.TABLE.mfs for n in f.tests}, p1)
        seed = json.loads((BOOT / "vectors" / "vectors.json").read_text(encoding="utf-8"))
        owned = {name for name, group in seed.items() if isinstance(group, dict) and group.get("owner") == "P1"}
        self.assertEqual({g for f in self.TABLE.mfs for g in f.groups}, owned)

    def test_stage_1_carries_stage_0_as_finished(self):  # stage0_groups_dropped_in_stage1 stage1_wiring_not_due
        """`asama-0/14`: a finished micro-feature's group runs on every later push; Stage 0's 18 are all finished once
        the lock opens, so every Stage 0 group runs with Stage 1's own, and the wiring check on every code push."""
        stage0 = stages.load(0)
        every0 = stage0.groups_of(range(1, stage0.count + 1))
        self.assertEqual(self.TABLE.groups_of(()), every0)
        self.assertEqual(self.TABLE.groups_of([4]), every0 + ("match", "cp_lower", "mcnemar"))
        self.assertEqual(stage0.groups_of(()), ())
        self.assertEqual([t.stage for t in self.TABLE.before], [0])
        self.assertTrue(wiring.due(self.TABLE, set()))
        self.assertFalse(wiring.due(stage0, set()))

    def test_a_transferred_batch_is_finished_and_the_next_one_holds(self):  # stage1_batches_done_ignored stage1_p2_not_carried
        """E378, E491: once the counter has P1's transfer, P1's micro-features are finished (its groups run, its tests
        stay declared) and P2's table holds; after P2's too, the seed carries no later table, so none is open: `done_mf`
        is empty and Stage 1's own micro-features are the transferred referee's to judge (`asama-1/06`)."""
        after = stages.load(1, done=("P1",))
        self.assertEqual((after.stage, after.batch, after.label, after.count), (1, "P2", "stage1-P2", 2))
        self.assertEqual([t.label for t in after.before], ["stage0", "stage1-P1"])
        self.assertEqual(after.groups_of(()), self.TABLE.groups_of(range(1, 9)))
        last = stages.load(1, done=("P1", "P2"))
        self.assertEqual((last.stage, last.batch, last.count), (1, None, 0))
        self.assertEqual([t.label for t in last.before], ["stage0", "stage1-P1", "stage1-P2"])
        for done in (("P2",), ("P1", "P1"), ("P2", "P1"), ("P1", "P2", "P2")):
            with self.subTest(done=done), self.assertRaises(ConfigError):
                stages.load(1, done=done)
        with self.assertRaises(ConfigError):
            stages.load(0, done=("P1",))

    def test_there_is_no_table_past_the_root(self):
        """`03`: Stage 1 is the ladder's fixed root; what follows is the Founder's stage spec, not a seed table."""
        with self.assertRaises(ConfigError):
            stages.load(2)


def tohum_page(prefix):
    return next((ROOT / "spec" / "tohum").glob(f"{prefix}-*.md")).read_text(encoding="utf-8")


def flat_text(text):
    return " ".join(text.split())


def page_26e_rows():
    """`26e`'s table: {(batch, MF): (tests, groups, module, calls)}, as the page writes it."""
    rows = {}
    for line in tohum_page("26e").splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) == 6 and re.fullmatch(r"`P\d+`", cells[0]):
            listed = lambda cell: [] if cell == "—" else cell
            tests = [int(n) for n in cells[2].split(", ")]
            groups = re.findall(r"`([a-z_]+)`", listed(cells[3]) or "")
            calls = [int(n) for n in re.findall(r"\d+", listed(cells[5]) or "")]
            rows[(cells[0].strip("`"), int(cells[1]))] = (tests, groups, cells[4].strip("`"), calls)
    return rows


class StageOneTablesPageTest(unittest.TestCase):
    """E491 (E373's first item): the batch tables the Founder works to are on a page (`26e`), every field of them, the
    ones `asama-1/13` leaves silent too (module paths, batch names, P2 MF1's test number); page, tables and code hold
    one another, so none can drift. P2's rows are `asama-1/13`'s, its MF1's test is `30d`'s numbered profile test."""

    def test_26e_is_every_row_of_every_table_the_seed_carries(self):  # stage1_p2_test_renumbered stage1_p2_module_moved
        tables = {b: stages.load(1, done=stages.BATCHES[1][:i]) for i, b in enumerate(stages.BATCHES[1])}
        from_tables = {(b, f.mf): (list(f.tests), list(f.groups), f.module, list(f.calls))
                       for b, t in tables.items() for f in t.mfs}
        self.assertEqual(page_26e_rows(), from_tables)
        self.assertEqual(list(dict.fromkeys(b for b, _mf in page_26e_rows())), list(stages.BATCHES[1]))
        self.assertEqual(stages.BATCHES[1], ("P1", "P2"))

    def test_p2s_rows_are_asama_1_13s_and_mf1s_test_is_30ds_profile_test(self):  # stage1_p2_test_renumbered
        rows = batch_rows("P2")
        self.assertEqual(sorted(rows), [1, 2])
        p2 = stages.load(1, done=("P1",))
        self.assertEqual((list(p2.feature(2).tests), list(p2.feature(2).groups)), rows[2])
        self.assertEqual(rows[1], (None, []))  # the page names the tests, `30d`'nin profil testleri, by no number
        page13 = next((ROOT / "spec" / "asama-1").glob("13-*.md")).read_text(encoding="utf-8")
        self.assertIn("| P2 | 1 | `security.derive` ve `security.run` (`tohum/30d`) | `30d`'nin profil testleri | — |", page13)
        profile = next(b for b in re.split(r"\n\s*\n", tohum_page("30d")) if b.startswith("**Profil testi.**"))
        number = int(re.search(r"devamı olarak (\d+) \(`26e`\)", flat_text(profile)).group(1))
        self.assertEqual(list(p2.feature(1).tests), [number])
        self.assertIn("\"`30d`'nin profil testleri\" tek testtir", flat_text(profile))
        tests_page = (ROOT / "spec" / "asama-0" / "09-harness-in-kendi-testleri.md").read_text(encoding="utf-8")
        numbered = [int(n) for n in re.findall(r"^\| (\d+) \|", tests_page, re.M)]
        self.assertEqual(number, max(numbered) + 1)  # §0.9's numbers go on; none is reused (`asama-0/09`: kalıcıdır)
        others = [n for t in [stages.load(0), stages.load(1)] for f in t.mfs for n in f.tests]
        self.assertNotIn(number, others)
        self.assertEqual(rows[2], ([22], []))
        self.assertIn("| 22 | Dispatch kanaryası", tests_page)
        self.assertTrue(re.search(r"^\| 22 \| .* \| P2 \|$", tests_page, re.M))

    def test_module_paths_are_26as_first_tool_of_each_mechanism(self):  # stage1_p2_module_moved
        """Spec sessiz (E372, E491): a module is its mechanism's first tool in `26a`, dots made slashes (`asama-0/14`
        MF1 and MF13 take their first tool's); a mechanism with no tool there keeps E372's name."""
        tools = set(re.findall(r"^\| `([a-z_]+\.[a-z_]+)` \|", tohum_page("26a"), re.M))
        page13 = next((ROOT / "spec" / "asama-1").glob("13-*.md")).read_text(encoding="utf-8")
        checked = 0
        for line in page13.splitlines():
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if len(cells) == 5 and cells[0] in stages.BATCHES[1] and cells[1].isdigit():
                named = [t for t in re.findall(r"`([a-z_]+\.[a-z_]+)`", cells[2]) if t in tools]
                module = page_26e_rows()[(cells[0], int(cells[1]))][2]
                if named:
                    checked += 1
                    self.assertEqual(module, named[0].replace(".", "/") + ".py", line)
        self.assertEqual(checked, 7)  # P1's 2, 3, 4, 6, 7 and P2's 1, 2 name a tool of 26a's

    def test_the_exit_batch_is_no_table_of_this_seed_and_the_page_says_why(self):  # stage1_exit_judged_as_stage0
        """E495: `asama-1/13`'s third batch comes with Stage 1's own exit, whose (A) this seed does not judge."""
        self.assertEqual(page_batches()[2], "Aşama 1 çıkışı")
        self.assertNotIn(page_batches()[2], stages.BATCHES[1])
        exit_part = next(b for b in re.split(r"\n\s*\n", tohum_page("26e")) if b.startswith("**Çıkış partisi.**"))
        for words in ("bu tohumda tablo değildir", "Aşama 1'in kendi çıkışının (A)'sıyla gelir",
                      "(`batch`'siz istek `exit_request_wrong_stage`'dir)", "P1 ve P2 aktarılınca açık tablo boştur"):
            self.assertIn(words, flat_text(exit_part))
        self.assertIn("(`26e`)", flat_text(tohum_page("26c")))  # 26c's stage table paragraph points here
        self.assertIn("`26e`", tohum_page("00b"))


class StageOneManifestTest(unittest.TestCase):
    def manifest(self, stage0_mfs=range(1, 19), stage1_done=(), stage1_tests=None, drop=(), done=None):
        t0 = stages.load(0)
        tests = [{"id": f"T{n}", "cmd": f"t{n}", "stage": 0} for mf in stage0_mfs for n in t0.feature(mf).tests
                 if n not in drop]
        t1 = stages.load(1)
        numbers = stage1_tests if stage1_tests is not None else [n for mf in stage1_done for n in t1.feature(mf).tests]
        tests += [{"id": f"T{n}", "cmd": f"t{n}", "stage": 1} for n in numbers]
        return parse_manifest(json.dumps({"tests": tests, "done_mf": list(stage1_done if done is None else done),
                                          "lockfiles": []}))

    def test_done_mf_is_the_open_batchs_and_its_tests_are_stage_1_tests(self):  # stage1_tests_at_stage0
        table = stages.load(1)
        self.assertEqual(check_stage(self.manifest(), table), [])
        self.assertEqual(check_stage(self.manifest(stage1_done=[1, 2]), table), [])
        self.assertEqual(check_stage(self.manifest(stage1_done=[1, 2], stage1_tests=[51]), table),
                         ["missing_test:MF2:T8"])
        self.assertEqual(check_stage(self.manifest(stage1_done=range(1, 19), stage1_tests=[]), table),
                         ["done_mf_not_in_order"])  # Stage 0's done_mf kept: P1 has 8
        stage0_numbered = parse_manifest(json.dumps({"tests": [{"id": "T51", "cmd": "x", "stage": 0}] + [
            {"id": f"T{n}", "cmd": "x", "stage": 0} for f in stages.load(0).mfs for n in f.tests],
            "done_mf": [1], "lockfiles": []}))
        self.assertEqual(check_stage(stage0_numbered, table), ["missing_test:MF1:T51"])

    def test_a_base_declares_the_open_tables_own_micro_features(self):  # declares_counts_earlier_tables
        """`declares` says whether a manifest's `done_mf` is the open table's: its own micro-features with their tests.
        A missing test of a finished table is that table's own reason (`missing_test:stage0:...`) and leaves P1's MF1
        declared, so a base missing it still counts MF1 as done (no module-less red for it, its withdrawal seen)."""
        table = stages.load(1)
        lacking = self.manifest(stage1_done=[1], drop=(13,))
        self.assertEqual(check_stage(lacking, table), ["missing_test:stage0:MF1:T13"])
        self.assertTrue(manifest_module.declares(lacking, table))
        self.assertFalse(manifest_module.declares(self.manifest(stage1_done=[1, 2], stage1_tests=[51]), table))
        self.assertFalse(manifest_module.declares(self.manifest(stage1_done=range(1, 19), stage1_tests=[]), table))

    def test_stage_0s_tests_stay_declared(self):  # stage0_tests_dropped_in_stage1
        """E292's rule across the lock: Stage 0's micro-features stay finished, so their tests stay in the manifest."""
        self.assertEqual(check_stage(self.manifest(drop=(13,)), stages.load(1)), ["missing_test:stage0:MF1:T13"])

    def test_a_transferred_batchs_tests_stay_declared_and_done_mf_starts_again(self):  # stage1_batches_done_ignored
        """E378: under the table after P1's transfer, P1's tests stay declared at stage 1 (named by their table) and
        `done_mf` is the next table's, empty here."""
        after = stages.load(1, done=("P1",))
        self.assertEqual(check_stage(self.manifest(stage1_done=range(1, 9), done=[]), after), [])
        self.assertEqual(check_stage(self.manifest(stage1_done=range(1, 9)), after), ["done_mf_not_in_order"])
        self.assertEqual(check_stage(self.manifest(stage1_done=range(1, 9), stage1_tests=[51, 8], done=[]), after),
                         ["missing_test:stage1-P1:MF3:T2", "missing_test:stage1-P1:MF3:T4",
                          "missing_test:stage1-P1:MF4:T1", "missing_test:stage1-P1:MF4:T6",
                          "missing_test:stage1-P1:MF4:T7", "missing_test:stage1-P1:MF4:T12",
                          "missing_test:stage1-P1:MF4:T28", "missing_test:stage1-P1:MF5:T9",
                          "missing_test:stage1-P1:MF5:T11", "missing_test:stage1-P1:MF6:T24",
                          "missing_test:stage1-P1:MF7:T41", "missing_test:stage1-P1:MF8:T52"])

    def test_stage_0_is_judged_as_before(self):
        table = stages.load(0)
        m = parse_manifest(json.dumps({"tests": [{"id": "T13", "cmd": "x", "stage": 0}, {"id": "T51", "cmd": "y",
                                                                                         "stage": 1}],
                                       "done_mf": [1], "lockfiles": []}))
        self.assertEqual(check_stage(m, table), manifest_module.check_stage0(m))
        self.assertEqual(check_stage(m, table), [])
        only_later = parse_manifest(json.dumps({"tests": [{"id": "T51", "cmd": "y", "stage": 1}], "done_mf": [],
                                                "lockfiles": []}))
        self.assertEqual(check_stage(only_later, table), ["zero_tests"])  # a stage 1 test is not one yet


# ---------------------------------------------------------------- pull with the lock open

class StageOnePullTest(unittest.TestCase):
    """The bootstrap with `setup/stage.json` in place (`asama-0/10a` "Kilidin açılışı"): the Stage 1 tables and the
    `stage: 1` tests hold from then on."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        self.brain = base / "brain"
        self.seed_files = {"spec/tohum/00-cekirdek.md": "# core\n", "spec/asama-0/00-ozet.md": "# stage 0\n",
                           "spec/asama-1/00-ozet.md": "# stage 1\n",
                           # the stage pages the rival reads beside a code push, Stage 0's and Stage 1's (E493)
                           **{f"spec/{name}.md": f"# {name}\n" for name in (
                               "asama-0/09-harness-in-kendi-testleri", "asama-0/14-sirali-mikro-ozellikler",
                               "asama-1/06-sirali-mikro-ozellikler", "asama-1/13-aktarim-partileri")},
                           "referee/.github/workflows/loop.yml": LOOP_YML,
                           "snowball-tests.json": self.manifest_text(stage1_done=())}
        make_repo(self.brain, {"README.md": "brain\n"})
        write(self.brain, self.seed_files)
        self.seed_sha = commit(self.brain, {}, "stage 0 exit")
        tar = gitio.archive(self.brain, self.seed_sha)
        self.referee = base / "referee"
        seed_hash = tree_hash(tar, "spec/tohum", forbid_operator_names=False)
        write(self.referee, {"setup/summary.json": json.dumps({"seed_commit": self.seed_sha,
                                                              "seed_tree_sha256": seed_hash})})
        write(self.referee, {
            "control.json": '{"kill_switch": false, "budget_state": "ok"}',
            "bootstrap.json": json.dumps({
                "brain_repo": "owner/brain", "brain_branch": "main",
                "image": "docker.io/library/python:3.12-slim@sha256:" + "a" * 64,
                "rival": {"model": "claude-sonnet-5-5", "effort": "medium", "max_turns": 30,
                          "per_run_cap_usd_micros": 3_000_000},
                "limits": {"test_timeout_s": 600, "reproducer_timeout_s": 120, "max_prompt_chars": 600_000,
                           "max_tree_bytes": 50_000_000}}),
            "policy.json": json.dumps(STAGE1_POLICY)})
        self.write_counter()
        frozen = {d: tree_hash(tar, d, forbid_operator_names=False) for d in ("spec/asama-0", "spec/asama-1")}
        self.state = {"schema": "snowball-bootstrap-state/3", "origin": "artifact",
                      "last_accepted_sha": self.seed_sha, "last_evaluated_sha": None, "frozen_specs": frozen,
                      "rival_artifacts": [], "month": "2026-10", "month_spend_usd_micros": 0,
                      "stage_spend_usd_micros": 0, "runs": 9, "reject_streaks": {}, "repeat_events": 0,
                      "outage_sha": None, "outage_count": 0, "outage_since": None, "outage_stop": None,
                      "rival_side_streak": 0, "open_refutations": [], "open_claims": [], "pending_rival": None,
                      "rejected_exit_request": None}
        self.n = 0

    def write_counter(self, batches=()):
        """Stage 0's transfer, the lock naming it, and a transfer row for each of ``batches`` after it."""
        self.imports = locked(self.referee, self.seed_sha, batches)

    @staticmethod
    def manifest_text(stage1_done=(), p1_finished=False):
        """Every Stage 0 test at stage 0, and ``stage1_done``'s tests at stage 1 with it as `done_mf`; None: the
        manifest of Stage 0's exit, its 18 micro-features done. ``p1_finished``: every P1 test, `done_mf` empty."""
        t0, t1 = stages.load(0), stages.load(1)
        tests = [{"id": f"T{n}", "cmd": f"t{n}", "stage": 0} for f in t0.mfs for n in f.tests]
        if stage1_done is None:
            return json.dumps({"tests": tests, "done_mf": list(range(1, t0.count + 1)), "lockfiles": []})
        if p1_finished:
            tests += [{"id": f"T{n}", "cmd": f"t{n}", "stage": 1} for f in t1.mfs for n in f.tests]
            return json.dumps({"tests": tests, "done_mf": [], "lockfiles": []})
        tests += [{"id": f"T{n}", "cmd": f"t{n}", "stage": 1} for mf in stage1_done for n in t1.feature(mf).tests]
        return json.dumps({"tests": tests, "done_mf": list(stage1_done), "lockfiles": []})

    def pull(self, rc=0):
        self.n += 1
        state_path = Path(self.tmp.name) / f"state{self.n}.json"
        state_path.write_text(json.dumps(self.state))
        out = Path(self.tmp.name) / f"pulled{self.n}"
        got = cli.main(["pull", "--root", str(self.referee), "--state", str(state_path),
                        "--work", str(Path(self.tmp.name) / "work"), "--out", str(out), "--remote", str(self.brain)])
        self.assertEqual(got, rc)
        return json.loads((out / "meta.json").read_text(encoding="utf-8")) if rc == 0 else None

    def stage0_base(self):
        """The last accepted commit is still Stage 0's: its manifest declares Stage 0's 18 micro-features."""
        self.state["last_accepted_sha"] = commit(self.brain, {"snowball-tests.json": self.manifest_text(None)},
                                                 "stage 0's manifest")

    def ask(self, **request):
        """An exit request alone, naming the last accepted commit and the frozen spec ``request`` says."""
        req = dict({"stage": 1, "sha": self.state["last_accepted_sha"],
                    "spec_sha256": self.state["frozen_specs"]["spec/asama-1"], "batch": "P1"}, **request)
        commit(self.brain, {"exit-request.json": json.dumps({k: v for k, v in req.items() if v is not DROP})}, "exit")
        meta = self.pull()
        self.assertEqual(meta["kind"], "exit")
        return meta

    def test_the_first_stage_1_push_after_a_stage_0_base(self):  # stage_lock_never_read stage0_base_read_as_stage1
        """The base's `done_mf` is Stage 0's: nothing of Stage 1 is withdrawn, MF1's module-less red runs, and the
        stage reaches run-tests."""
        self.stage0_base()
        commit(self.brain, {"referee/runner/organs.py": "x = 1\n", "snowball-tests.json": self.manifest_text([1])},
               "P1 MF1")
        meta = self.pull()
        self.assertEqual((meta["kind"], meta["pre_reasons"], stagelock.open_table(self.referee).label),
                         ("code", [], "stage1-P1"))
        self.assertEqual((meta["module_less"], meta["run_tests"]), ([1], True))
        self.assertEqual({"stage", "batch", "batches_done"} & set(meta), set())  # the jobs read the lock themselves

    def test_a_stage_1_micro_feature_cannot_be_undeclared(self):
        self.state["last_accepted_sha"] = commit(self.brain, {"snowball-tests.json": self.manifest_text([1])}, "MF1")
        commit(self.brain, {"snowball-tests.json": self.manifest_text([])}, "undeclare")
        self.assertIn("done_mf_withdrawn:MF1", self.pull()["pre_reasons"])

    def test_stage_1s_tests_and_stage_0s_are_both_required(self):
        commit(self.brain, {"snowball-tests.json": json.dumps({"tests": [{"id": "T13", "cmd": "t", "stage": 0}],
                                                               "done_mf": [1], "lockfiles": []})}, "no T51")
        reasons = self.pull()["pre_reasons"]
        self.assertIn("missing_test:MF1:T51", reasons)
        self.assertIn("missing_test:stage0:MF2:T38", reasons)

    def test_stage_1s_spec_must_be_frozen(self):  # stage1_spec_not_required
        """`29b`, `02` 2-3: code is accepted under a frozen spec; in Stage 1 that is `spec/asama-1`'s, Stage 0's too."""
        for missing in ("spec/asama-1", "spec/asama-0"):
            with self.subTest(missing=missing):
                frozen = dict(self.state["frozen_specs"])
                del self.state["frozen_specs"][missing]
                commit(self.brain, {"referee/x.py": f"x = '{missing}'\n"}, "code")
                self.assertIn("spec_not_frozen", self.pull()["pre_reasons"])
                self.state["frozen_specs"] = frozen

    def test_a_stage_exit_request_is_the_wrong_stage(self):  # stage1_exit_judged_as_stage0
        """`02`: this seed judges only the Stage 0 exit; with the lock open that exit is behind, Stage 1's not yet
        judged here (E373)."""
        self.stage0_base()
        frozen = self.state["frozen_specs"]
        for stage, spec, reasons in ((0, "spec/asama-0", ["exit_request_wrong_stage"]),  # C2_batch_spec_any_stage
                                     (1, "spec/asama-0", ["exit_request_wrong_stage"]),
                                     (1, "spec/asama-1", ["exit_request_spec_hash_mismatch", "exit_request_wrong_stage"])):
            with self.subTest(stage=stage, spec=spec):  # a stage's own exit, judged in Stage 0's form (`spec/asama-0`)
                meta = self.ask(stage=stage, spec_sha256=frozen[spec], batch=DROP)
                self.assertEqual([r for r in meta["pre_reasons"] if r.startswith("exit_request")], reasons)
                self.state["last_evaluated_sha"] = None

    def test_the_open_batchs_exit_request_is_judged(self):  # batch_exit_request_malformed batch_exit_wrong_stage_always
        """E378, `02` 6, `asama-1/13` 2, `26c:17`: the batch's request is the exit request's form with `batch`; for the
        open batch, on the last accepted commit and the frozen `spec/asama-1`, nothing in the request is refused."""
        meta = self.ask()
        self.assertEqual([r for r in meta["pre_reasons"] if r.startswith("exit_request")], [])
        self.assertEqual(meta["exit_request"]["batch"], "P1")
        self.assertIsNotNone(meta["referee_tree_sha256"])

    def test_a_batch_request_for_another_batch_stage_or_spec_is_refused(self):  # batch_exit_batch_unchecked batch_exit_spec_of_stage0
        for request, reason in (({"batch": "P2"}, "exit_request_wrong_batch"),
                                ({"stage": 0}, "exit_request_wrong_stage"),
                                ({"stage": 2}, "exit_request_wrong_stage"),
                                ({"spec_sha256": self.state["frozen_specs"]["spec/asama-0"]},
                                 "exit_request_spec_hash_mismatch"),
                                ({"batch": "P 1"}, "exit_request_malformed"), ({"batch": 1}, "exit_request_malformed"),
                                ({"batches": "P1"}, "exit_request_malformed")):
            with self.subTest(request=request):
                self.assertIn(reason, self.ask(**request)["pre_reasons"])
                self.state["last_evaluated_sha"] = None

    def test_without_the_lock_a_batch_request_is_malformed_as_it_always_was(self):  # stage0_batch_key_allowed
        """E402: before the lock the form is Stage 0's table's, which has no batch: a `batch` key is malformed, the
        request is not read (no pinned SHA), exactly as before the Stage 1 tooling (`test_stage0_unchanged`)."""
        (self.referee / "setup" / "stage.json").unlink()
        stage0 = self.state["frozen_specs"]["spec/asama-0"]  # batch_exit_stage0_batch: Stage 0 has no batches
        for request in ({}, {"stage": 0, "spec_sha256": stage0}):
            with self.subTest(request=request):
                meta = self.ask(**request)
                self.assertEqual((meta["pre_reasons"][:1], meta["exit_request"]), (["exit_request_malformed"], None))
                self.state["last_evaluated_sha"] = None

    def test_after_p1s_transfer_its_micro_features_are_finished(self):  # stage1_batches_done_ignored
        """E378: the counter's P1 transfer finishes P1: its tests stay declared, `done_mf` is the next table's (P2's,
        E491), and a P1 request is the wrong batch."""
        self.write_counter(batches=("P1",))
        self.state["last_accepted_sha"] = commit(self.brain, {"snowball-tests.json": self.manifest_text(range(1, 9))},
                                                 "P1 done")
        commit(self.brain, {"referee/y.py": "y = 1\n", "snowball-tests.json": self.manifest_text(p1_finished=True)},
               "after P1")
        meta = self.pull()
        table = stagelock.open_table(self.referee)
        self.assertEqual((table.stage, table.batch, [b.label for b in table.before]), (1, "P2", ["stage0", "stage1-P1"]))
        self.assertEqual(meta["pre_reasons"], [])
        commit(self.brain, {"snowball-tests.json": self.manifest_text([])}, "P1's tests dropped")
        self.assertIn("missing_test:stage1-P1:MF1:T51", self.pull()["pre_reasons"])
        self.state["last_accepted_sha"] = sh(self.brain, "git", "rev-parse", "HEAD")
        self.assertIn("exit_request_wrong_batch", self.ask()["pre_reasons"])

    def test_the_wiring_is_checked_on_every_stage_1_code_push(self):
        commit(self.brain, {"referee/.github/workflows/loop.yml": "name: loop\n"}, "break the loop workflow")
        reasons = self.pull()["pre_reasons"]
        self.assertTrue(any(r.startswith("workflow_") for r in reasons), reasons)

    def test_a_lock_that_does_not_match_stops_the_run(self):  # stage_lock_never_read
        """Test 29 (`asama-0/09`): the transition is refused, the run stops for the operator (exit 2)."""
        lock = json.loads((self.referee / "setup" / "stage.json").read_text())
        write(self.referee, {"setup/stage.json": json.dumps(dict(lock, import_line_sha256="0" * 64))})
        commit(self.brain, {"referee/x.py": "x = 1\n"}, "code")
        self.pull(rc=2)

    def test_without_the_lock_the_stage_is_0(self):
        (self.referee / "setup" / "stage.json").unlink()
        self.stage0_base()
        commit(self.brain, {"referee/x.py": "x = 1\n"}, "code")
        meta = self.pull()
        self.assertEqual((stagelock.open_table(self.referee).label, "stage" in meta), ("stage0", False))
        self.assertNotIn("spec_not_frozen", meta["pre_reasons"])


# ---------------------------------------------------------------- Stage 1's rival brake and pages (E492, E493)

class StageOneRivalBrakeTest(unittest.TestCase):
    """E492 (E373's second item): past the lock the rival's stage brake is the open stage's, `asama-1/10`'s 15 USD as
    `stage_budgets.asama_1.rival_usd` (`29b`, `26e`, `18a`), and the stage's spend counts from the lock that opened it."""

    def test_the_policy_names_a_brake_per_stage_stage_0s_required(self):  # stage1_brake_is_stage0s
        policy = config.policy_of(STAGE1_POLICY)
        self.assertEqual((policy.rival_usd_micros(0), policy.rival_usd_micros(1)), (30_000_000, 15_000_000))
        bare = config.policy_of(without_stage1_brake())
        self.assertEqual(bare.rival_usd_micros(0), 30_000_000)
        with self.assertRaisesRegex(ConfigError, r"stage_budgets\.asama_1\.rival_usd is missing"):
            bare.rival_usd_micros(1)
        founder_only = json.loads(json.dumps(STAGE1_POLICY))
        founder_only["constitutional"]["stage_budgets"]["asama_1"] = {"founder_usd": 150}  # another stage key only
        with self.assertRaises(ConfigError):
            config.policy_of(founder_only).rival_usd_micros(1)
        for bad in (0, -1, "15", 1.5, True):
            broken = json.loads(json.dumps(STAGE1_POLICY))
            broken["constitutional"]["stage_budgets"]["asama_1"]["rival_usd"] = bad
            with self.subTest(bad=bad), self.assertRaises(ConfigError):
                config.policy_of(broken)
        stage0_gone = json.loads(json.dumps(STAGE1_POLICY))
        del stage0_gone["constitutional"]["stage_budgets"]["asama_0"]
        with self.assertRaisesRegex(ConfigError, "asama_0"):
            config.policy_of(stage0_gone)

    def test_the_stages_spend_counts_from_its_lock(self):  # stage1_spend_not_reset stage1_spend_reset_every_run stage1_spend_stage_unchecked
        from snowball_bootstrap import state as st
        prev = {"stage_spend_usd_micros": 29_000_000, "x": 1}
        self.assertIs(st.for_stage(prev, 0), prev)  # Stage 0: the state it always was, no new key
        first = st.for_stage(prev, 1)
        self.assertEqual((first["stage_spend_usd_micros"], first[st.SPEND_STAGE], first["x"]), (0, 1, 1))
        later = dict(first, stage_spend_usd_micros=4_000_000)
        self.assertIs(st.for_stage(later, 1), later)  # counted on, never reset again
        self.assertIs(st.for_stage(later, 0), later)  # a reverted lock starts no stage's spend again (closed side)
        valid = st.initial(config.summary_of({"seed_commit": "a" * 40, "seed_tree_sha256": "b" * 64}), "2026-11")
        self.assertEqual(st.validate(dict(valid, spend_stage=1))["spend_stage"], 1)
        st.validate(valid)
        for bad in (0, -1, True, "1", None):
            with self.subTest(bad=bad), self.assertRaises(ConfigError):
                st.validate(dict(valid, spend_stage=bad))

    def test_stage_open_opens_no_lock_on_a_policy_without_the_stage_1_brake(self):  # stage_open_brake_unchecked
        case = StageOpenCase("run")
        case.setUp()
        self.addCleanup(case.doCleanups)
        case.commit_referee({"policy.json": json.dumps(without_stage1_brake())})
        with self.assertRaises(stagelock.LockStop) as caught:
            case.open()
        self.assertIn("stage_budgets.asama_1.rival_usd", str(caught.exception))
        self.assertFalse(case.stage_file().exists())
        case.commit_referee({"policy.json": json.dumps(STAGE1_POLICY)})
        self.assertEqual(case.open()["stage"], 1)


class StageOnePullBrakeTest(unittest.TestCase):
    """The brake as `pull` and the rival read it once the lock is open (E492), and the stage pages beside a code push
    (E493). StageOnePullTest's fixture, not its tests."""

    setUp = StageOnePullTest.setUp
    write_counter = StageOnePullTest.write_counter
    manifest_text = staticmethod(StageOnePullTest.manifest_text)
    pull = StageOnePullTest.pull

    def test_stage_0s_spend_does_not_brake_stage_1_and_stage_1s_does(self):  # stage1_brake_is_stage0s stage1_spend_not_reset
        self.state["stage_spend_usd_micros"] = 29_000_000  # Stage 0's, past Stage 1's whole 15 USD
        commit(self.brain, {"referee/runner/organs.py": "x = 1\n"}, "P1 work")
        meta = self.pull()
        self.assertNotIn("budget", meta["pre_reasons"])
        self.assertEqual((meta["state"]["stage_spend_usd_micros"], meta["state"]["spend_stage"]), (0, 1))
        self.state.update(stage_spend_usd_micros=15_000_000, spend_stage=1)  # Stage 1's brake reached
        commit(self.brain, {"referee/runner/organs.py": "x = 2\n"}, "more P1 work")
        meta = self.pull()
        self.assertIn("budget", meta["pre_reasons"])
        self.assertEqual(meta["state"]["stage_spend_usd_micros"], 15_000_000)

    def test_without_stage_1s_brake_the_run_stops(self):  # stage1_brake_is_stage0s
        write(self.referee, {"policy.json": json.dumps(without_stage1_brake())})
        commit(self.brain, {"referee/runner/organs.py": "x = 1\n"}, "P1 work")
        self.pull(rc=2)

    def rival(self, spend):
        """The rival command on the last pull, with Stage 1's spend ``spend``: the CLI's argv and prompt."""
        seats = self.referee / "seats"
        seats.mkdir(exist_ok=True)
        (seats / cli.SEATS_FILE).write_text(tohum_page("29"), encoding="utf-8")
        bin_dir = Path(self.tmp.name) / f"bin{self.n}"
        bin_dir.mkdir()
        claude = install_fake_claude(bin_dir)
        (bin_dir / "scenario.json").write_text(json.dumps({"calls": [submit()], "result": ok_result()}))
        pulled = Path(self.tmp.name) / f"pulled{self.n}"
        meta = json.loads((pulled / "meta.json").read_text(encoding="utf-8"))
        meta["state"]["stage_spend_usd_micros"] = spend
        (pulled / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
        gh_output = Path(self.tmp.name) / f"gh_output{self.n}"
        with mock.patch.dict(os.environ, {"GITHUB_OUTPUT": str(gh_output)}):
            self.assertEqual(cli.main(["rival", "--root", str(self.referee), "--pulled", str(pulled), "--work",
                                       str(Path(self.tmp.name) / f"rwork{self.n}"), "--out",
                                       str(Path(self.tmp.name) / f"rival{self.n}"), "--claude", str(claude)]), 0)
        return json.loads((bin_dir / "seen.json").read_text())

    def test_the_rival_gets_stage_1s_brake_and_stage_1s_pages(self):  # stage1_brake_is_stage0s stage1_rival_sees_stage0_pages
        """E493: beside a Stage 1 code push the rival reads the pages the open table copies, `asama-0/09`, `asama-1/06`
        and `asama-1/13`, not Stage 0's table page; its budget is Stage 1's brake less Stage 1's spend."""
        commit(self.brain, {"referee/runner/organs.py": "x = 1\n"}, "P1 work")
        self.pull()
        seen = self.rival(spend=14_500_000)
        self.assertEqual(seen["argv"][seen["argv"].index("--max-budget-usd") + 1], "0.500000")
        for page in ("spec/asama-0/09-harness-in-kendi-testleri.md", "spec/asama-1/06-sirali-mikro-ozellikler.md",
                     "spec/asama-1/13-aktarim-partileri.md"):
            self.assertIn(f'seed page "{page}"', seen["stdin"])
        self.assertNotIn("spec/asama-0/14-", seen["stdin"])


class StagePagesTest(unittest.TestCase):
    def test_the_rival_reads_the_pages_the_open_table_copies(self):  # stage1_rival_sees_stage0_pages
        """E493, `26e`: Stage 0's table copies `asama-0/14` and `09` (as before the lock, unchanged); Stage 1's batch
        tables copy `asama-1/13` and `09`, and Stage 1's own micro-features are `asama-1/06`'s."""
        names = ["spec/asama-0/09-harness-in-kendi-testleri.md", "spec/asama-0/14-sirali-mikro-ozellikler.md",
                 "spec/asama-1/06-sirali-mikro-ozellikler.md", "spec/asama-1/13-aktarim-partileri.md",
                 "spec/asama-1/07-harness-olcumu.md", "spec/tohum/04-is-boyutu-ve-gercek-test.md"]
        tar = tar_of({n: f"# {n}\n" for n in names})
        stage_pages = lambda stage: sorted(p for p in cli._pages(tar, "code", stage) if not p.startswith("spec/tohum/"))
        self.assertEqual(stage_pages(0), names[:2])
        self.assertEqual(stage_pages(1), [names[0], names[2], names[3]])
        self.assertEqual(sorted(cli._pages(tar, "spec", 1)), [])  # a spec request reads the seed's spec pages alone
        page = flat_text(tohum_page("26e"))
        self.assertIn("Aşama 0'da `asama-0/09` ve `asama-0/14`; Aşama 1'de `asama-0/09`, `asama-1/06` ve `asama-1/13`", page)
        for stage, prefixes in stages.STAGE_PAGES.items():
            for prefix in prefixes:
                self.assertEqual(len(list((ROOT / "spec").glob(prefix + "*.md"))), 1, prefix)


# ---------------------------------------------------------------- the batch's (A) (`02` 6, `asama-1/13` 2, E378)

class BatchExitDecisionTest(unittest.TestCase):
    state = test_exit_checks.ExitDecision.state
    ok = staticmethod(test_exit_checks.ExitDecision.ok)

    def meta(self, done=range(1, 9), **request):
        meta = test_exit_checks.ExitDecision.meta(self, self.state(), self.ok())
        meta.update(manifest={"tests": [], "done_mf": list(done), "lockfiles": []},
                    exit_request=dict({"stage": 1, "sha": meta["base"], "spec_sha256": "e" * 64, "batch": "P1"},
                                      **request),
                    honesty_exception={"stage": 0, "carry_to": 1, "reason": "E287", "carry_commitment": "c" * 64})
        return meta

    def run_(self, meta, table=None):
        return decide(meta, {"controls": [], "tests": [{"id": "T51", "cmd_sha256": "c", "ok": True}], "vectors": [],
                             "licenses": [], "green": True}, None, None, {"getir": "success", "kos": "success"}, 2, 3,
                      table=table or stages.load(1))

    def test_the_open_batchs_request_is_transferable_and_names_its_batch(self):  # batch_exit_takes_the_stage_conditions batch_exit_unnamed
        """The narrow form: the batch's own micro-features, the tests, vectors and rival, the archive's checks of the
        tree; the stage's own conditions (#spec, #durustluk) and the owner's exception are the stage exit's."""
        res = self.run_(self.meta())
        self.assertEqual((res["verdict"], res["exit"]["transferable"], res["exit"]["missing"]), ("accepted", True, []))
        self.assertEqual((res["exit"]["stage"], res["exit"]["batch"]), (1, "P1"))
        self.assertNotIn("owner_exception", res["exit"])

    def test_every_micro_feature_of_the_batch_must_be_done(self):
        res = self.run_(self.meta(done=range(1, 8)))
        self.assertEqual(res["exit"]["missing"], ["not_all_micro_features_done"])
        self.assertNotIn("batch", res["exit"])
        res = self.run_(self.meta(), table=stages.load(0))  # judged under Stage 0's 18: not done
        self.assertIn("not_all_micro_features_done", res["exit"]["missing"])

    def test_the_archives_checks_still_hold(self):
        meta = self.meta()
        meta["exit_checks"]["agac"] = {"status": "failed", "reasons": ["agent_config_in_referee:referee/CLAUDE.md"],
                                       "why": ""}
        res = self.run_(meta)
        self.assertEqual(res["exit"]["missing"], ["agent_config_in_referee:referee/CLAUDE.md"])

    def test_the_exits_form_is_the_open_tables_not_the_requests(self):  # batch_form_from_the_request
        """E402: under Stage 0's table every request is Stage 0's exit, one that carries `batch` too: the stage's own
        conditions and the owner's exception stay, nothing names a batch. Under the lock the open batch's form holds
        whatever the request says (`pull` refuses a request that is not the open batch's)."""
        for request in ({}, {"batch": DROP}, {"stage": 0, "batch": "P1"}):
            with self.subTest(table="stage0", request=request):
                meta = self.meta()
                meta["exit_request"] = edited(meta["exit_request"], request)
                res = self.run_(meta, table=stages.load(0))
                self.assertIn("not_checked:spec", res["exit"]["missing"])
                self.assertEqual(res["exit"]["owner_exception"]["anchor"], "durustluk")
                self.assertEqual({"stage", "batch"} & set(res["exit"]), set())
            with self.subTest(table="stage1-P1", request=request):
                res = self.run_(meta, table=stages.load(1))
                self.assertEqual((res["verdict"], res["exit"]["batch"]), ("accepted", "P1"))
                self.assertNotIn("owner_exception", res["exit"])

    def test_the_decide_command_judges_under_the_table_pull_named(self):  # decide_reads_stage0_table
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        work = Path(tmp.name)
        write(work / "root", {"policy.json": json.dumps({"constitutional": {
            "monthly_cap_usd": 300, "stage_params": {"rival_min_attempts": 2, "repeat_reject_limit": 3},
            "stage_budgets": {"asama_0": {"rival_usd": 30}}, "license_allowlist": ["MIT"], "license_exceptions": {}}})})
        write(work / "pulled", {"meta.json": json.dumps(self.meta())})
        write(work / "run", {"run.json": json.dumps({"controls": [], "tests": [{"id": "T51", "cmd_sha256": "c",
                                                                                "ok": True}],
                                                     "vectors": [], "licenses": [], "green": True})})
        argv = ["decide", "--root", str(work / "root"), "--pulled", str(work / "pulled"), "--run", str(work / "run"),
                "--out", str(work / "out"), "--job", "getir=success", "--job", "kos=success"]
        # No lock in the snapshot: Stage 0's table, whatever the meta says of a stage (E402).
        write(work / "pulled", {"meta.json": json.dumps(dict(self.meta(), stage=1, batch="P1", batches_done=[]))})
        self.assertEqual(cli.main(argv), 0)
        result = json.loads((work / "out" / "result.json").read_text(encoding="utf-8"))
        self.assertEqual(result["exit"]["transferable"], False)
        self.assertIn("not_all_micro_features_done", result["exit"]["missing"])
        locked(work / "root")  # the lock the snapshot carries: P1 is the open batch
        self.assertEqual(cli.main(argv), 0)
        result = json.loads((work / "out" / "result.json").read_text(encoding="utf-8"))
        self.assertEqual((result["exit"]["transferable"], result["exit"]["batch"]), (True, "P1"))
        locked(work / "root", batches=("P1",))  # P1 transferred: none of this seed's batches is open
        self.assertEqual(cli.main(argv), 0)
        result = json.loads((work / "out" / "result.json").read_text(encoding="utf-8"))
        self.assertEqual((result["exit"]["transferable"], "batch" in result["exit"]), (False, False))


class StageOneRunTestsTest(unittest.TestCase):
    def test_stage_0_and_stage_1_tests_run_and_module_less_red_reads_stage_1s(self):  # stage1_tests_not_run run_tests_stage_ignored
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        work = Path(tmp.name)
        referee = work / "referee"
        shutil.copytree(BOOT / "vectors", referee / "vectors")
        write(referee, {"bootstrap.json": json.dumps({
            "brain_repo": "owner/brain", "brain_branch": "main",
            "image": "docker.io/library/python:3.12-slim@sha256:" + "a" * 64,
            "rival": {"model": "claude-sonnet-5-5", "effort": "medium", "max_turns": 30, "per_run_cap_usd_micros": 1},
            "limits": {"test_timeout_s": 60, "reproducer_timeout_s": 60, "max_prompt_chars": 1000,
                       "max_tree_bytes": 50_000_000}}),
            "policy.json": json.dumps({"constitutional": {
                "monthly_cap_usd": 300, "stage_params": {"rival_min_attempts": 2, "repeat_reject_limit": 3},
                "stage_budgets": {"asama_0": {"rival_usd": 30}}, "license_allowlist": ["MIT"],
                "license_exceptions": {}}})})
        src = work / "tree"
        write(src, {"referee/runner/organs.py": "x\n", "referee/other.py": "y\n"})
        pulled = work / "pulled"
        pulled.mkdir()
        cli.pack_dir(src, pulled / "brain.tar")
        manifest = {"tests": [{"id": "T13", "cmd": "t13", "stage": 0}, {"id": "T51", "cmd": "t51", "stage": 1},
                              {"id": "T60", "cmd": "t60", "stage": 2}], "done_mf": [1], "lockfiles": []}
        (pulled / "meta.json").write_text(json.dumps({"manifest": manifest, "module_less": [1]}))
        locked(referee)  # the snapshot's lock opened Stage 1: P1's table, its `stage: 1` tests
        deps = work / "deps"
        deps.mkdir()
        calls, trees = [], []

        class Runner(FakeRunner):
            def run(self, cmd, **kw):
                if cmd in ("t13", "t51", "t60"):
                    calls.append((cmd, self.src))
                    present = (self.src / "referee" / "runner" / "organs.py").exists()
                    return RunResult(0 if present else 1, b"", b"", 1)
                return super().run(cmd, **kw)

        def make(boot, tree, *a, **k):
            runner = Runner(referee / "vectors")
            runner.src = Path(tree)
            trees.append(Path(tree))
            return runner
        with mock.patch.object(cli, "_runner", side_effect=make):
            rc = cli.main(["run-tests", "--root", str(referee), "--pulled", str(pulled), "--deps", str(deps),
                           "--work", str(work / "work"), "--out", str(work / "run")])
        self.assertEqual(rc, 0)
        run = json.loads((work / "run" / "run.json").read_text())
        self.assertEqual([t["id"] for t in run["tests"]], ["T13", "T51"])  # a stage 2 test is not one yet
        self.assertEqual([(m["mf"], m["test_id"], m["module"], m["stayed_green"]) for m in run["module_less"]],
                         [(1, "T51", "referee/runner/organs.py", False)])


class WorkflowReadsTheLockTest(unittest.TestCase):
    def test_the_snapshot_carries_the_lock_and_the_counter_when_they_exist(self):  # workflow_drops_the_lock
        """`asama-0/10a`: the bootstrap reads `setup/stage.json` on every pull, so the snapshot the jobs read holds it
        and the counter it is bound to; before the import neither exists and the snapshot is as before."""
        workflow = (BOOT / "workflow" / "bootstrap.yml").read_text(encoding="utf-8")
        step = workflow[workflow.index("name: Snapshot operator files"):workflow.index("name: Kill switch and operator")]
        for name in ("stage.json", "imports.jsonl"):
            self.assertIn(f"if [ -e referee/setup/{name} ]; then cp referee/setup/{name} snap/setup/; fi", step)

    @posix_only
    def test_the_snapshot_step_run_copies_the_lock_and_the_counter(self):  # workflow_drops_the_lock
        """E389: the step itself, run as the job runs it, over a referee checkout with and without the two files."""
        workflow = (BOOT / "workflow" / "bootstrap.yml").read_text(encoding="utf-8")
        block = workflow[workflow.index("name: Snapshot operator files"):workflow.index("name: Kill switch and operator")]
        lines = block.splitlines()[2:]  # past the name and `run: |`
        script = "\n".join(line[10:] for line in lines if line.startswith(" " * 10)) + "\n"
        operator = {"bootstrap/x.py": "x\n", "vectors/v.json": "{}\n", "seats/s.md": "s\n", "bootstrap.json": "{}\n",
                    "control.json": "{}\n", "policy.json": "{}\n", "setup/summary.json": "{}\n"}
        for present in (False, True):
            with self.subTest(present=present), tempfile.TemporaryDirectory() as tmp:
                work = Path(tmp)
                write(work / "referee", operator)
                if present:
                    write(work / "referee", {"setup/stage.json": "{\"stage\": 1}\n", "setup/imports.jsonl": "{}\n"})
                (work / "step.sh").write_text("set -e\n" + script, encoding="utf-8")
                self.assertEqual(sh(work, "sh", "step.sh"), "")
                snapped = sorted(p.name for p in (work / "snap" / "setup").iterdir())
                self.assertEqual(snapped, ["imports.jsonl", "stage.json", "summary.json"] if present else ["summary.json"])


if __name__ == "__main__":
    unittest.main()
