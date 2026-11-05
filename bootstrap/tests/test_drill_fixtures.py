"""The operator's `drill-fixtures` command (E499; `tohum/26f` "Canlı prova fikstürleri", `25a` 7, E544): the live
revert-drill fixtures of one import, checked against every rule of `26f`, each cause measured with the toy's own tools,
written to the operator's path alone.

Every git repository is a local one made here; the sandbox is a fake that answers from the plant's bytes, except in
`DockerIntegrationTest`, which runs the real `DockerSandbox` only when docker is there and ``SNOWBALL_DRILL_DOCKER=1``
asks for it (the suite runs under every mutant, and the seed's fetch of the lockfile's tarballs needs the network).
The trailing comment on a test names the mutants it kills (`local/mutate.py`).
"""

import base64
import hashlib
import http.server
import io
import json
import os
import shutil
import subprocess
import tarfile
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from snowball_bootstrap import canon, cli, drillfixtures as df, importer
from snowball_bootstrap.config import ConfigError
from snowball_bootstrap.drillfixtures import FixtureStop, Measurement

ZERO = "0" * 64
TOY = {
    "README.md": b"# textkit\n",
    "textkit/.nvmrc": b"22.23.4\n",
    "textkit/package.json": json.dumps({"name": "textkit", "version": "1.0.0", "private": True, "type": "module",
                                        "scripts": {"lint": "node lint.mjs", "test": "node --test"}}).encode() + b"\n",
    "textkit/package-lock.json": json.dumps({"name": "textkit", "version": "1.0.0", "lockfileVersion": 3,
                                             "requires": True,
                                             "packages": {"": {"name": "textkit", "version": "1.0.0"}}}).encode()
    + b"\n",
    # The toy's own lint tool here: ESLint's JSON report, one error for each `var `, exit 0.
    "textkit/lint.mjs": (b'import { readdirSync, readFileSync } from "node:fs";\n'
                         b'const report = readdirSync("src").filter((f) => f.endsWith(".js")).map((f) => ({\n'
                         b'  filePath: f, warningCount: 0,\n'
                         b'  errorCount: (readFileSync(`src/${f}`, "utf8").match(/\\bvar /g) || []).length }));\n'
                         b"process.stdout.write(JSON.stringify(report));\n"),
    "textkit/src/greet.js": b'export function greet(name) {\n  return "Hello, " + name + "!";\n}\n',
    "textkit/src/slug.js": (b"export function slugify(text) {\n  const lower = text.toLowerCase();\n"
                            b'  return lower.trim().replace(/[^a-z0-9]+/g, "-");\n}\n'),
    "textkit/src/stats.js": (b"export function total(values) {\n  var sum = 0;\n  for (const v of values) {\n"
                             b"    sum = sum + v;\n  }\n  return sum;\n}\n"),
    "textkit/src/permissions.js": b"export function canEdit(user) {\n  return user.editor === true;\n}\n",
    "textkit/test/greet.test.js": (b'import { test } from "node:test";\nimport assert from "node:assert/strict";\n'
                                   b'import { greet } from "../src/greet.js";\n\n'
                                   b'test("greet", () => {\n  assert.equal(greet("Ada"), "Hello, Ada!");\n});\n'),
    "textkit/test/slug.test.js": (b'import { test } from "node:test";\nimport assert from "node:assert/strict";\n'
                                  b'import { slugify } from "../src/slug.js";\n\n'
                                  b'test("slug", () => {\n  assert.equal(slugify("A b"), "a-b");\n});\n'),
}
GREET, SLUG, STATS, PERM = "textkit/src/greet.js", "textkit/src/slug.js", "textkit/src/stats.js", \
    "textkit/src/permissions.js"
KEYWORDS = ["auth", "guard", "security", "session", "token", "secret", "crypto", "tenant", "permission", "role",
            "policy", "payment", "billing", "pii"]
BASE = Measurement("v22.23.4", True, 1, True)
UNITS = ("textkit",)  # the unit candidates covering a plant's file in the toy target (`Fixture.summary`)
RED = ("textkit/test/greet.test.js",)  # the file of the test a test plant makes red


def git(repo, *args, data=None):
    return subprocess.run(["git", "-c", "core.autocrlf=false", *args], cwd=repo, input=data, capture_output=True,
                          check=True).stdout


def repo_of(path: Path, files: dict[str, bytes]) -> Path:
    """A repository whose ``main`` holds ``files`` exactly (bytes, LF as given)."""
    path.mkdir(parents=True)
    git(path, "init", "-q", "-b", "main")
    for key, value in (("core.autocrlf", "false"), ("user.email", "t@example.invalid"), ("user.name", "t")):
        git(path, "config", key, value)
    commit_files(path, files)
    return path


def commit_files(path: Path, files: dict[str, bytes | None], message: str = "c") -> str:
    for rel, content in files.items():
        target = path / rel
        if content is None:
            target.unlink()
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    git(path, "add", "-A")
    git(path, "commit", "-q", "--allow-empty", "-m", message)
    return git(path, "rev-parse", "HEAD").decode().strip()


def chained(rows):
    out, prev = [], ZERO
    for row in rows:
        row = dict(row, prev_hash=prev)
        row["row_hash"] = canon.row_hash(row)
        prev = row["row_hash"]
        out.append(json.dumps(row, separators=(",", ":")).encode("utf-8"))
    return out


def patch_of(repo: Path, rel: str, new: bytes) -> str:
    """The operator's draft as git writes it: ``rel`` changed to ``new`` in ``repo``'s tree, then put back."""
    old = (repo / rel).read_bytes()
    (repo / rel).write_bytes(new)
    try:
        return git(repo, "diff", "--no-color", "--no-ext-diff", "--", rel).decode("utf-8")
    finally:
        (repo / rel).write_bytes(old)


class FakeSandbox:
    """Answers from the bytes of the one file a plant changed (``answers``: new bytes -> measurement); the clean tree
    gets ``base``. ``during`` runs inside each plant's measurement."""

    def __init__(self, answers=None, base=BASE, during=None):
        self.answers, self.base, self.during = answers or {}, base, during
        self.trees, self.closed, self.readied = [], False, False

    def ready(self):
        self.readied = True

    def measure(self, tree, plan):
        self.trees.append(tree)
        changed = [content for rel, (content, _x) in tree.items() if TOY.get(rel) != content]
        if not changed:
            return self.base
        if self.during:
            self.during()
        return self.answers[changed[0]]

    def close(self):
        self.closed = True


class Fixture(unittest.TestCase):
    """A referee checkout after a Stage 0 import, the toy clone, the brain, a catalog of three drafts (one a cause)."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="dfx-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.toy = repo_of(self.tmp / "toy", TOY)
        brain_files = {f"{importer.TOY_DIR}/{rel}": content for rel, content in TOY.items()}
        brain_files.update({
            "candidates/toy/good/expect.json": b'{"decision": "merge"}\n',
            "candidates/toy/good/diff.patch": patch_of(self.toy, STATS, TOY[STATS].replace(b"var sum", b"let sum"))
            .encode(),
            "candidates/toy/bad-test/expect.json": b'{"decision": "reject", "reason": "tests_red"}\n',
            "candidates/toy/bad-test/diff.patch": patch_of(self.toy, GREET, TOY[GREET].replace(b"Hello", b"Bye"))
            .encode(),
            "referee/ledger/chain.py": b"x = 1\n"})
        self.brain = repo_of(self.tmp / "brain", brain_files)
        self.brain_sha = git(self.brain, "rev-parse", "HEAD").decode().strip()
        self.toy_hash = importer.part_hash(self.toy, "refs/heads/main", importer.TOY_DIR, forbid_operator_names=False,
                                           fold_case=True)
        self.referee = repo_of(self.tmp / "referee", {
            "ledger/chain.py": b"x = 1\n",
            "policy.json": json.dumps({"constitutional": {"security_keywords": KEYWORDS}}).encode(),
            "setup/summary.json": json.dumps(self.summary()).encode()})
        self.import_rows()
        self.private = self.tmp / "private"
        self.private.mkdir()
        self.out = self.private / "fixtures.b64"
        self.drafts = {"build_break": patch_of(self.toy, GREET, TOY[GREET] + b"export function broken( {\n"),
                       "lint_regression": patch_of(self.toy, SLUG, TOY[SLUG].replace(b"const lower", b"var lower")),
                       "test_regression": patch_of(self.toy, GREET, TOY[GREET].replace(b"Hello", b"Hi"))}
        self.answers = {TOY[GREET] + b"export function broken( {\n": Measurement("v22.23.4", False, 2, False),
                        TOY[SLUG].replace(b"const lower", b"var lower"): Measurement("v22.23.4", True, 2, True),
                        TOY[GREET].replace(b"Hello", b"Hi"): Measurement("v22.23.4", True, 1, False,
                                                                         red_files=RED)}

    @staticmethod
    def summary(**toy):
        return {"seed_commit": "a" * 40, "seed_tree_sha256": "b" * 64, "targets": [
            dict({"id": "toy", "repo": "o/toy", "kind": "toy", "base_sha": None, "identifiers": [],
                  "excluded_paths": [], "unit_candidates": ["textkit"]}, **toy),
            {"id": "copy", "repo": "o/copy", "kind": "copy", "base_sha": "c" * 40, "identifiers": ["X"],
             "excluded_paths": [], "unit_candidates": ["a"]}]}

    def import_rows(self, **over):
        """The counter: a touch row, then the transfer (its referee tree the checkout's), ``over`` set on it."""
        referee_tree = importer.committed_referee_hash(self.referee, "HEAD")
        transfer = dict({"ts": "2026-11-04T08:00:00Z", "stage": 0, "brain_sha": self.brain_sha,
                         "referee_tree_sha256": referee_tree, "result_sha256": "e" * 64,
                         "toy_tree_sha256": self.toy_hash}, **over)
        lines = chained([{"ts": "2026-11-03T08:00:00Z", "touch": "kill_switch"}, transfer])
        commit_files(self.referee, {"setup/imports.jsonl": b"".join(line + b"\n" for line in lines)})
        self.line = lines[-1]

    def catalog(self, entries=None):
        entries = entries if entries is not None else [{"cause": c, "patch": p} for c, p in self.drafts.items()]
        path = self.private / f"catalog-{len(list(self.private.iterdir()))}.json"
        path.write_text(json.dumps(entries), encoding="utf-8")
        return path

    def produce(self, catalog=None, sandbox=None, out=None, toy_ref="refs/heads/main"):
        self.sandbox = sandbox or FakeSandbox(self.answers)
        return df.produce(self.referee, self.toy, toy_ref, self.brain, catalog or self.catalog(), out or self.out,
                          self.sandbox)

    def refused(self, says, **kw):
        with self.assertRaises(FixtureStop) as caught:
            self.produce(**kw)
        self.assertIn(says, str(caught.exception))
        self.assertFalse(self.out.exists(), "a refusal wrote the value")
        return str(caught.exception)


class ProduceTest(Fixture):
    def test_one_base64_line_of_the_canonical_set_of_the_last_transfer(self):  # drill_fixtures_ids_from_cause
        """E499 (`26f`): one line of base64 (no LF) of the RFC 8785 JSON; the import line's sha256 is its bytes
        without the LF; the ids are 32 fresh lowercase hex characters, distinct, in the order the instances are."""
        done = self.produce()
        value = self.out.read_bytes()
        self.assertNotIn(b"\n", value)
        data = json.loads(base64.b64decode(value, validate=True))
        self.assertEqual(canon.canonical(data), base64.b64decode(value))
        self.assertEqual(set(data), {"import_line_sha256", "instances"})
        self.assertEqual(data["import_line_sha256"], hashlib.sha256(self.line).hexdigest())
        ids = [i["id"] for i in data["instances"]]
        self.assertTrue(all(len(i) == 32 and set(i) <= set("0123456789abcdef") for i in ids))
        self.assertEqual(ids, sorted(set(ids)))
        self.assertEqual(sorted((i["cause"], i["patch"]) for i in data["instances"]), sorted(self.drafts.items()))
        self.assertTrue(all(set(i) == {"id", "cause", "patch"} for i in data["instances"]))
        self.assertEqual(done, {"causes": {c: 1 for c in df.CAUSES}, "instances": 3,
                                "value_sha256": hashlib.sha256(value).hexdigest(), "value_bytes": len(value)})
        self.assertTrue(self.sandbox.readied and self.sandbox.closed)
        self.assertEqual(len(self.sandbox.trees), 4)  # the base once, then each plant
        again = self.tmp / "private" / "again.b64"
        self.produce(out=again)
        other = [i["id"] for i in json.loads(base64.b64decode(again.read_bytes()))["instances"]]
        self.assertFalse(set(ids) & set(other), "the ids are not fresh")

    def test_the_cli_prints_counts_the_sha256_and_the_size_and_nothing_else(self):
        # drill_fixtures_value_printed drill_fixtures_value_to_stderr
        """E499: the terminal gets exactly the counts, the value's sha256, its size and the next step's sentence, and
        nothing on stderr; checked at Python's streams and at the file descriptors 1 and 2 beneath them, so no
        encoding of the value or of an id or patch, and no write that bypasses ``sys.stdout``, can reach it."""
        fake = FakeSandbox(self.answers)
        fds = {fd: tempfile.TemporaryFile() for fd in (1, 2)}
        saved = {fd: os.dup(fd) for fd in fds}
        try:
            for fd, handle in fds.items():
                os.dup2(handle.fileno(), fd)
            with mock.patch.object(df, "DockerSandbox", lambda image: fake), \
                    mock.patch("sys.stderr", new_callable=io.StringIO) as err, \
                    mock.patch("sys.stdout", new_callable=io.StringIO) as printed:
                code = cli.main(["drill-fixtures", "--referee", str(self.referee), "--toy", str(self.toy),
                                 "--toy-ref", "refs/heads/main", "--brain", str(self.brain), "--catalog",
                                 str(self.catalog()), "--out", str(self.out), "--node-image",
                                 "node:22@sha256:" + "a" * 64])
        finally:
            for fd in fds:
                os.dup2(saved[fd], fd)
                os.close(saved[fd])
        beneath = {}
        for fd, handle in fds.items():
            handle.seek(0)
            beneath[fd] = handle.read()
            handle.close()
        self.assertEqual(code, 0)
        value = self.out.read_bytes()
        done = {"causes": {c: 1 for c in df.CAUSES}, "instances": 3, "value_sha256": hashlib.sha256(value).hexdigest(),
                "value_bytes": len(value)}
        self.assertEqual(printed.getvalue(), json.dumps(done, indent=2, sort_keys=True) + "\n"
                         "Write the file's content as the referee secret loop.yml names for the fixtures; record only "
                         "value_sha256.\n")
        self.assertEqual(err.getvalue(), "")
        self.assertEqual(beneath, {1: b"", 2: b""})

    def test_an_existing_out_is_never_written_over(self):  # drill_fixtures_out_overwritten
        """E499: a set is written once; a path already there, or one that appears while the plants are measured, is
        left exactly as it was."""
        self.out.write_bytes(b"old")
        with self.assertRaises(FixtureStop) as caught:
            self.produce()
        self.assertIn("there already", str(caught.exception))
        self.assertEqual(self.out.read_bytes(), b"old")
        self.out.unlink()
        with self.assertRaises(FixtureStop) as caught:
            self.produce(sandbox=FakeSandbox(self.answers, during=lambda: self.out.write_bytes(b"meanwhile")))
        self.assertIn("appeared", str(caught.exception))
        self.assertEqual(self.out.read_bytes(), b"meanwhile")

    def test_the_value_and_the_drafts_stay_outside_every_repository(self):
        """E499 (`26f`: never a file of a repository): an out path or a catalog inside a git work tree is refused."""
        self.refused("inside the git repository", out=self.referee / "fixtures.b64")
        inside = self.toy / "drafts.json"
        inside.write_text(json.dumps([]), encoding="utf-8")
        self.refused("inside the git repository", catalog=inside)

    def test_an_out_without_its_directory_is_refused_before_anything_is_measured(self):  # drill_fixtures_out_dir_late
        """E499: the value has a private directory to go to before the toy's tools run."""
        missing = self.private / "no-such-dir" / "fixtures.b64"
        with self.assertRaises(FixtureStop) as caught:
            self.produce(out=missing)
        self.assertIn("directory is not there", str(caught.exception))
        self.assertFalse(self.sandbox.readied or self.sandbox.trees)

    def test_without_docker_the_command_stops_and_writes_nothing(self):  # drill_fixtures_docker_skipped
        """E499: the measurement is never skipped: no docker, no value."""
        self.refused("docker is not available",
                     sandbox=df.DockerSandbox("node:22@sha256:" + "a" * 64, docker="no-such-docker-e499"))
        failing = df.DockerSandbox("node:22@sha256:" + "a" * 64,
                                   run=lambda *a, **k: subprocess.CompletedProcess(a, 1, b"", b""))
        self.refused("docker is not available", sandbox=failing)
        self.refused("must name its digest", sandbox=df.DockerSandbox("node:22.23.4-bookworm-slim"))


class BindingRefusedTest(Fixture):
    def test_a_toy_that_is_not_the_lines_toy_tree_is_refused(self):  # drill_fixtures_toy_tree_unchecked
        """E499 (`26f`: the patch applies to that import's toy tree, `toy_tree_sha256`)."""
        commit_files(self.toy, {"README.md": b"# moved\n"})
        self.refused("not the tree the last transfer line names")

    def test_a_checkout_that_is_not_the_lines_referee_is_refused(self):  # drill_fixtures_line_unbound
        """E499: the line binds the set only when the checkout's commit holds the referee tree it names (E471)."""
        commit_files(self.referee, {"ledger/chain.py": b"x = 2\n"})
        with self.assertRaises(ConfigError) as caught:  # stage-open's own refusal (E471), the same rule
            self.produce()
        self.assertIn("referee_tree_sha256", str(caught.exception))
        self.assertFalse(self.out.exists())

    def test_a_last_transfer_without_a_toy_tree_is_refused(self):
        """E499: a batch transfer writes no toy; the set is bound to a transfer that did."""
        self.import_rows(toy_tree_sha256=None)
        self.refused("names no toy tree")

    def test_a_brain_whose_toy_fixture_is_another_tree_is_refused(self):
        """E499: the candidates read are the ones beside the line's toy tree."""
        moved = commit_files(self.brain, {f"{importer.TOY_DIR}/README.md": b"# other\n"})
        self.import_rows(brain_sha=moved)
        self.refused("is not the toy tree the line names")


class DraftRefusedTest(Fixture):
    def test_a_cause_outside_29js_three_is_refused(self):
        """E499 (`26f`): test_regression, build_break or lint_regression."""
        self.refused("its cause is not one of", catalog=self.catalog([{"cause": "impact_miss",
                                                                       "patch": self.drafts["build_break"]}]))

    def test_unequal_cause_counts_or_a_missing_cause_are_refused(self):  # drill_fixtures_counts_unchecked
        """E499 (`26f`: each cause the same count, at least one)."""
        extra = patch_of(self.toy, SLUG, TOY[SLUG].replace(b'"-"', b'"_"'))
        entries = [{"cause": c, "patch": p} for c, p in self.drafts.items()]
        self.refused("the same number of instances", catalog=self.catalog(entries + [
            {"cause": "test_regression", "patch": extra}]))
        self.refused("the same number of instances", catalog=self.catalog(entries[1:]))

    def test_a_file_on_a_security_path_is_refused(self):  # drill_fixtures_security_path_unchecked safety_paths_dropped
        """E499 (`26f`, `14`, `29k`): a lower-case keyword of policy.json in the lower-case path; the toy target's
        safety_paths too (`05`)."""
        perm = patch_of(self.toy, PERM, TOY[PERM].replace(b"=== true", b"!== true"))
        self.refused("on a security path", catalog=self.catalog([{"cause": "test_regression", "patch": perm}]))
        commit_files(self.referee, {"setup/summary.json": json.dumps(self.summary(safety_paths=["textkit/src/slug.js"]))
                                    .encode()})
        self.import_rows()
        self.refused("on a security path", catalog=self.catalog([{"cause": "lint_regression",
                                                                  "patch": self.drafts["lint_regression"]}]))

    def test_the_security_rule_folds_the_case_of_the_keyword_and_of_the_path(self):
        # drill_fixtures_keyword_case_folded drill_fixtures_path_case_folded
        """E499 (`14`, `29k` `security_keyword_substring`): the keyword and the path compared in lower case, so a
        mixed-case keyword of policy.json (`SLUG`) holds a lower-case path and a lower-case keyword a mixed-case one."""
        from types import SimpleNamespace
        bind = df.Binding("a" * 64, "b" * 64, "c" * 40, ("slug",), SimpleNamespace(safety_paths=()))
        self.assertTrue(df._on_security_path("textkit/src/Slug.js", bind))
        self.assertFalse(df._on_security_path("textkit/src/greet.js", bind))
        commit_files(self.referee, {"policy.json": json.dumps(
            {"constitutional": {"security_keywords": ["SLUG", "Perm"]}}).encode()})
        self.import_rows()
        self.assertEqual(df.binding(self.referee).keywords, ("slug", "perm"))
        self.refused("on a security path", catalog=self.catalog([{"cause": "lint_regression",
                                                                  "patch": self.drafts["lint_regression"]}]))

    def test_a_padded_keyword_and_a_safety_path_in_another_case_still_hold_the_path(self):
        # drill_fixtures_keyword_padded drill_fixtures_safety_path_case_folded
        """E499 (`14`, `05`): a keyword is read without its padding (`  slug `), and an owner's safety path holds the
        toy's file whatever the case either spells it in; both wider than the profile's reading, never narrower."""
        commit_files(self.referee, {"policy.json": json.dumps(
            {"constitutional": {"security_keywords": ["  slug ", "auth"]}}).encode()})
        self.import_rows()
        self.assertEqual(df.binding(self.referee).keywords, ("slug", "auth"))
        self.refused("on a security path", catalog=self.catalog([{"cause": "lint_regression",
                                                                  "patch": self.drafts["lint_regression"]}]))
        commit_files(self.referee, {
            "policy.json": json.dumps({"constitutional": {"security_keywords": ["auth"]}}).encode(),
            "setup/summary.json": json.dumps(self.summary(safety_paths=["TextKit/Src/Greet.js"])).encode()})
        self.import_rows()
        self.refused("on a security path", catalog=self.catalog([{"cause": "test_regression",
                                                                  "patch": self.drafts["test_regression"]}]))

    def test_two_entries_that_plant_the_same_bytes_are_refused(self):  # drill_fixtures_duplicate_accepted
        """E499 (`26f`: each instance a plant of its own; one once planted is in the toy's public history): the same
        patch twice, and two patches that differ only in their hunk's section heading (git's ``@@ … @@ <function>``),
        make one plant and are refused before anything is measured."""
        lint = self.drafts["lint_regression"]
        headed = lint.replace("@@ -1,4 +1,4 @@\n", "@@ -1,4 +1,4 @@ export function slugify(text) {\n", 1)
        self.assertNotEqual(headed, lint)
        for twin in (lint, headed):
            entries = [{"cause": "build_break", "patch": self.drafts["build_break"]},
                       {"cause": "lint_regression", "patch": lint}, {"cause": "lint_regression", "patch": twin},
                       {"cause": "test_regression", "patch": self.drafts["test_regression"]}]
            said = self.refused("the same bytes in the same file", catalog=self.catalog(entries))
            self.assertNotIn("slug", said)
            self.assertEqual(self.sandbox.trees, [])

    def test_a_toy_tree_with_an_ownership_file_is_refused(self):  # drill_fixtures_ownership_unchecked
        """E499 (`14`: the paths an ownership file gives the security team are security paths): the seed does not
        read CODEOWNERS, so a toy tree that holds one, in any case and directory, is refused."""
        for rel in (".github/CODEOWNERS", "docs/codeowners"):
            with self.subTest(rel=rel):
                commit_files(self.toy, {rel: b"* @owner\n"})
                hashed = importer.part_hash(self.toy, "refs/heads/main", importer.TOY_DIR,
                                            forbid_operator_names=False, fold_case=True)
                self.import_rows(toy_tree_sha256=hashed)
                self.refused("ownership file")
                commit_files(self.toy, {rel: None})

    def test_a_patch_whose_result_is_the_file_it_started_from_is_refused(self):  # drill_fixtures_noop_accepted
        """E499 (`26f`): a plant changes its file; lines replaced by themselves, with an index line naming one blob,
        apply exactly and are still no plant (the measurement would find no cause only after the sandbox's minutes)."""
        blob = df.blob_id(TOY[GREET])[:12]
        noop = (f"diff --git a/{GREET} b/{GREET}\nindex {blob}..{blob} 100644\n--- a/{GREET}\n+++ b/{GREET}\n"
                '@@ -2,1 +2,1 @@\n-  return "Hello, " + name + "!";\n+  return "Hello, " + name + "!";\n')
        self.refused("changes nothing", catalog=self.catalog([{"cause": "test_regression", "patch": noop}]))

    def test_a_file_a_merge_expected_candidate_changes_is_refused(self):  # drill_fixtures_candidate_files_unchecked
        """E499 (`26f`: per file, not per line); a rejected candidate's file is free."""
        stats = patch_of(self.toy, STATS, TOY[STATS].replace(b"return sum", b"return sum + 1"))
        said = self.refused("merge-expected candidate good", catalog=self.catalog([{"cause": "test_regression",
                                                                                     "patch": stats}]))
        self.assertNotIn("stats.js", said)

    def test_a_patch_that_is_no_single_in_place_modification_is_refused(self):  # drill_fixtures_add_accepted
        """E499 (`26f`: one existing regular file changed in place): an added, deleted, renamed or binary file, a
        mode change, two files, a CR and a missing file are each refused."""
        add = "diff --git a/textkit/x.js b/textkit/x.js\nnew file mode 100644\nindex 0000000..e69de29\n"
        delete = "diff --git a/textkit/src/slug.js b/textkit/src/slug.js\ndeleted file mode 100644\n" \
                 "index 1111111..0000000\n--- a/textkit/src/slug.js\n+++ /dev/null\n@@ -1 +0,0 @@\n-x\n"
        rename = "diff --git a/a.js b/b.js\nsimilarity index 100%\nrename from a.js\nrename to b.js\n"
        mode = "diff --git a/textkit/src/slug.js b/textkit/src/slug.js\nold mode 100644\nnew mode 100755\n"
        binary = "diff --git a/textkit/a.bin b/textkit/a.bin\nindex 1111111..2222222 100644\n" \
                 "Binary files a/textkit/a.bin and b/textkit/a.bin differ\n"
        two = self.drafts["lint_regression"] + self.drafts["test_regression"]
        crlf = self.drafts["lint_regression"].replace("\n", "\r\n")
        missing = self.drafts["lint_regression"].replace("textkit/src/slug.js", "textkit/src/gone.js")
        for patch, says in ((add, "adds a file"), (delete, "deletes a file"), (rename, "renames"),
                            (mode, "changes a mode"), (binary, "is binary"), (two, "changes 2 files"),
                            (crlf, "carriage return"), (missing, "no existing regular file")):
            self.refused(says, catalog=self.catalog([{"cause": "lint_regression", "patch": patch}]))

    def test_no_exact_fit_is_refused(self):  # drill_fixtures_context_unchecked drill_fixtures_new_start_unchecked
        """E499 (`26f`: kaydırmadan): a hunk moved by a line, a context line one byte off, and a new start that is not
        the old one moved by the hunks before it are refused, though each would apply with an offset or fuzz."""
        good = self.drafts["lint_regression"]
        moved = good.replace("@@ -1,4 +1,4 @@", "@@ -2,4 +2,4 @@")
        fuzzed = good.replace(" export function slugify(text) {", " export function slugify(text)  {")
        shifted = good.replace("@@ -1,4 +1,4 @@", "@@ -1,4 +2,4 @@")
        self.assertNotEqual(moved, good)
        self.assertNotEqual(fuzzed, good)
        for patch, says in ((moved, "outside the file"), (fuzzed, "does not apply at its lines"),
                            (shifted, "new start")):
            self.refused(says, catalog=self.catalog([{"cause": "lint_regression", "patch": patch}]))

    def test_an_index_line_that_is_not_the_files_blobs_is_refused(self):  # drill_fixtures_index_unchecked
        """E499 (`26c`'s diff.patch form): the index line names the file's blob in this toy tree and the result's, and
        the file's own mode (no mode change)."""
        good = self.drafts["lint_regression"]
        self.assertIn(" 100644\n", good)
        self.refused("another mode", catalog=self.catalog([{"cause": "lint_regression",
                                                            "patch": good.replace(" 100644\n", " 100755\n", 1)}]))
        old, new = good.split("\n")[1].split(" ")[1].split("..")
        self.refused("another blob", catalog=self.catalog([{"cause": "lint_regression",
                                                            "patch": good.replace(old, "1234567", 1)}]))
        self.refused("another result blob", catalog=self.catalog([{"cause": "lint_regression",
                                                                   "patch": good.replace(new, "1234567", 1)}]))

    def test_a_patch_that_is_not_utf8_text_is_refused(self):  # drill_fixtures_surrogate_accepted
        """E499: a lone surrogate (JSON can carry one) is no text git wrote; it is refused as the patch's fault."""
        good = self.drafts["lint_regression"]
        odd = good.replace("@@ -1,4 +1,4 @@", "@@ -1,4 +1,4 @@ \ud800", 1)
        self.assertNotEqual(odd, good)
        self.refused("lone surrogate", catalog=self.catalog([{"cause": "lint_regression", "patch": odd}]))

    def test_a_value_over_48_kb_is_refused(self):  # drill_fixtures_size_unchecked
        """E499, E544 (4): GitHub holds at most 48 KB in one secret."""
        big = b"// " + b"x" * 50_000 + b"\n"
        entries = [{"cause": "build_break", "patch": patch_of(self.toy, GREET, TOY[GREET] + big)},
                   {"cause": "lint_regression", "patch": self.drafts["lint_regression"]},
                   {"cause": "test_regression", "patch": self.drafts["test_regression"]}]
        self.refused("over GitHub's 48 KB", catalog=self.catalog(entries))

    def test_a_catalog_that_is_not_a_list_of_cause_and_patch_is_refused(self):
        """E499: the operator's drafts, read strictly."""
        for entries in ([], {"cause": "x"}, [{"cause": "build_break"}], [{"cause": "build_break", "patch": 1}],
                        [{"cause": "build_break", "patch": "p", "id": "x"}]):
            self.refused("catalog", catalog=self.catalog(entries))


class MeasuredCauseTest(Fixture):
    def test_a_measured_cause_that_is_not_the_declared_one_is_refused(self):  # drill_fixtures_label_unmeasured
        """E499 (`26f`: the patch gives exactly this cause by `29j`'s order)."""
        entries = [{"cause": "lint_regression", "patch": self.drafts["build_break"]},
                   {"cause": "build_break", "patch": self.drafts["lint_regression"]},
                   {"cause": "test_regression", "patch": self.drafts["test_regression"]}]
        self.refused("declared lint_regression, measured build_break", catalog=self.catalog(entries))

    def test_two_causes_or_none_are_refused(self):  # drill_fixtures_ambiguous_accepted
        """E499 (`26f`: each instance has one cause): a red test beside a risen lint total is two; nothing is none."""
        both = dict(self.answers)
        both[TOY[SLUG].replace(b"const lower", b"var lower")] = Measurement("v22.23.4", True, 2, False)
        self.refused("two causes", sandbox=FakeSandbox(both))
        none = dict(self.answers)
        none[TOY[GREET].replace(b"Hello", b"Hi")] = Measurement("v22.23.4", True, 1, True)
        self.refused("no cause", sandbox=FakeSandbox(none))

    def test_a_red_test_outside_the_plants_unit_is_refused(self):
        # drill_fixtures_impact_miss_accepted drill_fixtures_unit_any_candidate drill_fixtures_units_unread
        """E499 (`29j` `cause`: MF13's impact set at Stage 0 is the unit's tests; a red test outside it is
        ``impact_miss``, not ``test_regression``): a plant whose tests red in all four runs are none of its unit's is
        refused. The unit is each unit candidate that covers the plant's file, and a red test is the unit's when every
        one of them covers it; a plant's file under no candidate has no unit."""
        elsewhere = dict(self.answers)
        elsewhere[TOY[GREET].replace(b"Hello", b"Hi")] = Measurement("v22.23.4", True, 1, False,
                                                                     red_files=("other/test/a.test.js",))
        self.refused("impact_miss", sandbox=FakeSandbox(elsewhere))
        commit_files(self.referee, {"setup/summary.json": json.dumps(self.summary(
            unit_candidates=["textkit/src", "other"])).encode()})
        self.import_rows()
        self.refused("impact_miss")  # the red test is textkit/test's; the plant's unit is textkit/src
        commit_files(self.referee, {"setup/summary.json": json.dumps(self.summary(
            unit_candidates=["textkit", "other"])).encode()})
        self.import_rows()
        self.produce()  # two units: the test plant's unit is textkit, which covers its red test
        cause, red = df.measured_cause, Measurement("v22.23.4", True, 1, False, red_files=RED)
        self.assertEqual(cause(BASE, red, UNITS)[0], "test_regression")
        self.assertEqual(cause(BASE, Measurement("v22.23.4", True, 1, False, red_files=("x", *RED)), UNITS)[0],
                         "test_regression")
        for units in ((), ("textkit", "textkit/src"), ("textkit/src",), ("text",)):
            self.assertIsNone(cause(BASE, red, units)[0], units)
        self.assertEqual(df.units_of(GREET, ("textkit", "textkit/src/", "other", "textkit/test", "text")),
                         ("textkit", "textkit/src/"))

    def test_a_test_file_that_no_longer_loads_names_no_cause(self):  # drill_fixtures_test_files_ignored
        """E499 (`29j` names no producer of ``build_ok``): when a test file stops parsing or fails as a whole while
        the code still loads, either build_break or test_regression could be read, so the plant is refused."""
        found = df.measured_cause(BASE, Measurement("v22.23.4", True, 1, False, test_files_load=False,
                                                    red_files=RED), UNITS)
        self.assertIsNone(found[0])
        self.assertIn("a test file no longer parses or fails as a whole", found[1])
        self.assertIsNone(df.measured_cause(BASE, Measurement("v22.23.4", True, 1, False, test_files_load=None,
                                                              red_files=RED), UNITS)[0])
        self.assertEqual(df.measured_cause(BASE, Measurement("v22.23.4", False, 1, False, test_files_load=False),
                                           UNITS)[0], "build_break")

    def test_a_plant_measured_with_other_tools_than_the_bases_is_refused(self):  # drill_fixtures_plan_unchecked
        """E499 (`26f`: measured with the toy's own tools): a patch to .nvmrc, package.json or package-lock.json would
        measure the plant on another Node or other dependencies than the clean base it is compared with."""
        nvmrc = patch_of(self.toy, "textkit/.nvmrc", b"22.23.5\n")
        manifest = patch_of(self.toy, "textkit/package.json",
                            TOY["textkit/package.json"].replace(b'"1.0.0"', b'"1.0.1"'))
        for patch in (nvmrc, manifest):
            entries = [{"cause": "build_break", "patch": patch},
                       {"cause": "lint_regression", "patch": self.drafts["lint_regression"]},
                       {"cause": "test_regression", "patch": self.drafts["test_regression"]}]
            self.refused("with the base's tools", catalog=self.catalog(entries))
            self.assertEqual(self.sandbox.trees, [], "a tree was measured before every plan was checked")

    def test_the_clean_tree_must_load_green_on_the_toys_node(self):  # drill_fixtures_base_unchecked
        """E499: the base is measured once and must be clean, on the Node `.nvmrc` names."""
        self.refused("does not load", sandbox=FakeSandbox(self.answers, base=Measurement("v22.23.4", True, 1, False)))
        self.refused("does not load", sandbox=FakeSandbox(self.answers, base=Measurement(
            "v22.23.4", True, 1, True, test_files_load=False)))
        self.refused(".nvmrc names", sandbox=FakeSandbox(self.answers, base=Measurement("v20.0.0", True, 1, True)))

    def test_29js_rule_order_names_the_cause(self):
        """E499 (`29j`): build_break first, its red tests and lint its result; then lint; then a red test."""
        cause = lambda base, measured: df.measured_cause(base, measured, UNITS)  # noqa: E731
        self.assertEqual(cause(BASE, Measurement("v22.23.4", False, 9, False))[0], "build_break")
        self.assertEqual(cause(BASE, Measurement("v22.23.4", True, 2, True))[0], "lint_regression")
        self.assertEqual(cause(BASE, Measurement("v22.23.4", True, 0, False, red_files=RED))[0], "test_regression")
        for unnamed in (Measurement("v22.23.4", True, 2, False, red_files=RED), Measurement("v22.23.4", True, 1, True),
                        Measurement("v22.23.4", None, 1, False), Measurement("v22.23.4", True, None, False),
                        Measurement("v22.23.4", True, 2, None), Measurement("v20.0.0", False, 1, False)):
            self.assertIsNone(cause(BASE, unnamed)[0], unnamed)
        self.assertIn("flaky", cause(BASE, Measurement("v22.23.4", True, 1, None))[1])

    def test_errors_and_warnings_that_move_apart_name_no_cause(self):  # drill_fixtures_lint_split_ignored
        """E499 (`29j` leaves the lint total's producer unnamed): when ESLint's errors and warnings move apart, a total
        of errors alone, or of warnings alone, would say another thing than their sum, so the plant is refused."""
        cause = lambda base, measured: df.measured_cause(base, measured, UNITS)  # noqa: E731
        base = Measurement("v22.23.4", True, 3, True, (2, 1))
        for split, red in (((3, 0), False), ((3, 0), True), ((1, 2), True), ((1, 3), False)):
            found = cause(base, Measurement("v22.23.4", True, sum(split), not red, split,
                                            red_files=RED if red else ()))
            self.assertIsNone(found[0], split)
            self.assertIn("moved apart", found[1])
        self.assertEqual(cause(base, Measurement("v22.23.4", True, 4, True, (2, 2)))[0], "lint_regression")
        self.assertEqual(cause(base, Measurement("v22.23.4", True, 3, False, (2, 1), red_files=RED))[0],
                         "test_regression")
        self.assertEqual(cause(base, Measurement("v22.23.4", False, 0, False, (0, 5)))[0], "build_break")


class DiffTest(unittest.TestCase):
    """E499: the seed's own strict unified-diff reader and applier."""

    OLD = b"a\nb\nc\nd\ne\nf\ng\nh\n"

    def edit(self, text):
        return df.in_place_edit(text)

    def test_hunks_apply_at_their_lines_moved_by_the_hunks_before(self):
        """E499: each hunk at its own lines, the later one's new start moved by the hunks before it."""
        text = ("diff --git a/f b/f\nindex 1111111..2222222 100644\n--- a/f\n+++ b/f\n"
                "@@ -1,2 +1,3 @@\n a\n+x\n b\n@@ -7,2 +8,1 @@\n g\n-h\n")
        self.assertEqual(df.apply(self.OLD, self.edit(text).hunks), b"a\nx\nb\nc\nd\ne\nf\ng\n")

    def test_a_missing_last_newline_is_kept_or_changed_exactly(self):
        """E499: git's no-newline marker is a byte of the context: a file whose last line ends otherwise is refused."""
        text = ("diff --git a/f b/f\nindex 1111111..2222222 100644\n--- a/f\n+++ b/f\n"
                "@@ -1,2 +1,2 @@\n a\n-b\n\\ No newline at end of file\n+c\n")
        self.assertEqual(df.apply(b"a\nb", self.edit(text).hunks), b"a\nc\n")
        with self.assertRaises(ValueError):
            df.apply(b"a\nb\n", self.edit(text).hunks)  # the file's b has its newline: the context is not byte for byte

    def test_counts_must_be_the_hunks_lines(self):
        """E499: a hunk's lines are exactly its header's counts, neither fewer nor more, and no stray line."""
        for body in ("@@ -1,2 +1,2 @@\n a\n-b\n", "@@ -1,1 +1,1 @@\n a\n-b\n+c\n", "@@ -1 +1 @@\n-a\n+b\nzz\n"):
            with self.assertRaises(ValueError, msg=body):
                self.edit("diff --git a/f b/f\nindex 1111111..2222222 100644\n--- a/f\n+++ b/f\n" + body)

    def test_hunks_out_of_order_or_overlapping_are_refused(self):  # drill_fixtures_hunks_unordered
        """E499: a hunk that starts before the end of the one ahead of it does not apply, however its lines fit."""
        head = "diff --git a/f b/f\nindex 1111111..2222222 100644\n--- a/f\n+++ b/f\n"
        for body in ("@@ -7,2 +7,1 @@\n g\n-h\n@@ -2,1 +1,1 @@\n-b\n+x\n",  # reordered, its new start consistent
                     "@@ -1,2 +1,2 @@\n a\n-b\n+x\n@@ -2,2 +2,2 @@\n-x\n+b\n c\n"):  # overlapping
            with self.assertRaisesRegex(ValueError, "before the hunk ahead"):
                df.apply(self.OLD, self.edit(head + body).hunks)

    def test_a_hunk_that_changes_nothing_is_refused(self):
        """E499: a hunk of context alone is no plant."""
        with self.assertRaisesRegex(ValueError, "changes nothing"):
            self.edit("diff --git a/f b/f\nindex 1111111..2222222 100644\n--- a/f\n+++ b/f\n@@ -1 +1 @@\n a\n")

    def test_the_files_a_candidate_changes_are_read_by_hunk_counts(self):
        """A removed line that begins with ``--`` is not a header; a rename names both paths."""
        text = ("diff --git a/x.js b/x.js\nindex 1111111..2222222 100644\n--- a/x.js\n+++ b/x.js\n"
                "@@ -1,2 +1,1 @@\n--- a/y.js\n a\n"
                "diff --git a/p.js b/q.js\nsimilarity index 100%\nrename from p.js\nrename to q.js\n")
        self.assertEqual(df.changed_files(text), {"x.js", "p.js", "q.js"})

    def test_git_writes_the_blobs_the_index_line_names(self):
        """E499: `blob_id` is git's own object name, which the index line abbreviates."""
        repo = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, repo, ignore_errors=True)
        (repo / "f").write_bytes(self.OLD)
        named = subprocess.run(["git", "-c", "core.autocrlf=false", "hash-object", "f"], cwd=repo, capture_output=True,
                               check=True).stdout.decode().strip()
        self.assertEqual(df.blob_id(self.OLD), named)


class PlanTest(unittest.TestCase):
    """E499: what the sandbox runs, read from the toy tree."""

    def tree(self, **over):
        files = {rel: (content, False) for rel, content in TOY.items()}
        files.update({rel: (content, False) for rel, content in over.items()})
        return files

    def test_the_project_its_files_its_tests_and_its_node(self):
        """E499: the toy's one Node project, the files node --check reads, the modules it imports (no test file, by
        Node 22's default patterns) and the Node .nvmrc names."""
        plan = df.plan_of(self.tree())
        self.assertEqual(plan.project, "textkit")
        self.assertEqual(plan.node, "v22.23.4")
        self.assertIn("textkit/test/greet.test.js", plan.parse)
        self.assertNotIn("textkit/test/greet.test.js", plan.load)
        self.assertIn("textkit/src/greet.js", plan.load)
        for rel in ("test/a.js", "a/test/b/c.mjs", "a.test.js", "a-test.cjs", "a_test.js", "test-a.js", "test.js"):
            self.assertTrue(df.is_node_test_file(rel), rel)
        for rel in ("src/a.js", "tests/a.js", "atest.js", "test.ts", "contest.js"):
            self.assertFalse(df.is_node_test_file(rel), rel)

    def test_a_tree_the_seed_cannot_measure_as_the_toys_own_is_refused(self):
        # drill_fixtures_integrity_form_unchecked drill_fixtures_one_tarball_two_integrities
        """E499: a package outside the npm registry or without one sha512 integrity (the seed checks each tarball it
        fetches against it), one tarball named with two integrities, a test script that is not exactly node --test, an
        .nvmrc naming no version and two lockfiles are each refused before anything runs."""
        lock = json.loads(TOY["textkit/package-lock.json"])
        lock["packages"]["node_modules/x"] = {"version": "1.0.0", "resolved": "https://evil.example/x.tgz",
                                              "integrity": "sha512-x"}
        good, other = ("sha512-" + base64.b64encode(hashlib.sha512(b).digest()).decode() for b in (b"x", b"y"))
        integrities = [
            json.dumps(dict(lock, packages={"": lock["packages"][""], "node_modules/x": {
                "version": "1.0.0", "resolved": df.REGISTRY + "x/-/x-1.0.0.tgz", "integrity": integrity}}))
            for integrity in ("sha1-" + base64.b64encode(b"x" * 20).decode(), good + " " + good, good[:-3] + "==")]
        twice = json.loads(TOY["textkit/package-lock.json"])
        for name, integrity in (("node_modules/x", good), ("node_modules/a/node_modules/x", other)):
            twice["packages"][name] = {"version": "1.0.0", "resolved": df.REGISTRY + "x/-/x-1.0.0.tgz",
                                       "integrity": integrity}
        manifest = json.loads(TOY["textkit/package.json"])
        manifest["scripts"]["test"] = "node --test test/"
        for over, says in (({"textkit/package-lock.json": json.dumps(lock).encode()}, "npm registry"),
                           *(({"textkit/package-lock.json": text.encode()}, "not one sha512") for text in integrities),
                           ({"textkit/package-lock.json": json.dumps(twice).encode()}, "two integrities"),
                           ({"textkit/package.json": json.dumps(manifest).encode()}, "exactly 'node --test'"),
                           ({"textkit/.nvmrc": b"lts/*\n"}, ".nvmrc"),
                           ({"other/package-lock.json": b"{}"}, "2 package-lock.json")):
            with self.assertRaisesRegex(FixtureStop, says.replace(".", r"\.").replace("*", r"\*")):
                df.plan_of(self.tree(**over))


class DockerSandboxTest(unittest.TestCase):
    """E499: the sandbox's containers, as `DockerSandbox` asks docker for them (docker itself replaced)."""

    TARBALL = b"the bytes of a package"
    LOCK = {"name": "textkit", "version": "1.0.0", "lockfileVersion": 3, "requires": True, "packages": {
        "": {"name": "textkit", "version": "1.0.0"},
        "node_modules/x": {"version": "1.0.0", "resolved": df.REGISTRY + "x/-/x-1.0.0.tgz",
                           "integrity": "sha512-" + base64.b64encode(hashlib.sha512(TARBALL).digest()).decode()}}}
    A = {"file": "textkit/test/a.test.js", "line": 3, "column": 1, "name": "a", "whole": False}

    def setUp(self):
        self.calls, self.inputs, self.fetched = [], [], []
        self.tree = dict({rel: (content, False) for rel, content in TOY.items()},
                         **{"textkit/package-lock.json": (json.dumps(self.LOCK).encode(), False)})
        self.plan = df.plan_of(self.tree)

    def fetch(self, url, limit):
        self.fetched.append((url, limit))
        return self.TARBALL

    def docker(self, argv, **kw):
        self.calls.append(argv)
        self.inputs.append(kw.get("input"))
        out = b""
        if argv[1] == "run" and "DFX_STEP=build" in argv:
            out = json.dumps({"node": "v22.23.4", "step": "build", "parse": [{"status": 0}] * len(self.plan.parse),
                              "load": [{"status": 0}] * len(self.plan.load),
                              "lint": {"status": 0, "timed_out": False,
                                       "stdout": '[{"errorCount": 1, "warningCount": 2}]'}}).encode()
        elif argv[1] == "run" and "DFX_STEP=test" in argv:
            out = json.dumps({"node": "v22.23.4", "step": "test", "test": {"status": 1, "timed_out": False,
                                                                           "tests": 2, "red": [self.A]}}).encode()
        return subprocess.CompletedProcess(argv, 0, out, b"")

    def box(self, **kw):
        return df.DockerSandbox("node:22@sha256:" + "a" * 64, run=self.docker, fetch=self.fetch, **kw)

    def test_no_container_has_a_network(self):
        # drill_fixtures_online drill_fixtures_install_runs_scripts drill_fixtures_install_online_npm
        """E499: no container has a network, the install's neither: the seed fetched each of the lockfile's tarballs
        itself and hands their bytes to ``npm ci --offline --ignore-scripts``; each tree is measured read-only,
        unprivileged, its dependencies mounted read-only; the volume is removed at the end."""
        box = self.box()
        self.assertEqual(box.measure(self.tree, self.plan),
                         Measurement("v22.23.4", True, 3, False, (1, 2), True, ("textkit/test/a.test.js",)))
        box.measure(self.tree, self.plan)
        self.assertEqual(self.fetched, [(df.REGISTRY + "x/-/x-1.0.0.tgz", df.MAX_DEPS_BYTES)])  # once per lockfile
        runs = [argv for argv in self.calls if argv[1] == "run"]
        # one install for the one lockfile, then the build and MF12's four runs of each of two measurements
        self.assertEqual(len(runs), 1 + 2 * (1 + df.TEST_RUNS))
        install, measured = runs[0], runs[1:]
        self.assertIn("npm ci --offline --ignore-scripts --no-audit --no-fund --registry=https://registry.npmjs.org/",
                      install[-1])
        self.assertIn("npm cache add /tmp/p/tarballs/*.tgz", install[-1])
        handed = self.inputs[[a[1] for a in self.calls].index("run")]
        with tarfile.open(fileobj=io.BytesIO(handed)) as tar:
            self.assertEqual(tar.extractfile("tarballs/00000.tgz").read(), self.TARBALL)
        self.assertEqual(df.HARDENED[:2], ("--network", "none"))
        for argv in runs:
            self.assertEqual(argv.count("--network"), 1, argv)
            self.assertEqual(argv[argv.index("--network") + 1], "none")
        for argv in measured:
            self.assertIn("--read-only", argv)
            self.assertTrue(any(a.endswith(",dst=/deps,readonly") for a in argv))
            self.assertEqual(argv[argv.index("--user") + 1], "65534:65534")
        volume = next(a for a in install if a.startswith("type=volume")).split(",")[1].split("=")[1]
        box.close()
        self.assertEqual(self.calls[-1][:4], ["docker", "volume", "rm", "-f"])
        self.assertEqual(self.calls[-1][4], volume)

    def test_a_tarball_is_held_to_the_lockfiles_sha512_and_the_byte_limit(self):
        # drill_fixtures_tarball_unverified drill_fixtures_deps_size_unchecked
        """E499: a tarball whose bytes are not the lockfile's integrity, or that brings the lockfile's tarballs over
        ``MAX_DEPS_BYTES`` together, stops the run before any container starts."""
        integrity = self.LOCK["packages"]["node_modules/x"]["integrity"]
        url = self.LOCK["packages"]["node_modules/x"]["resolved"]
        self.assertEqual(df.registry_tarball(url, integrity, 100, lambda u, n: self.TARBALL), self.TARBALL)
        with self.assertRaisesRegex(FixtureStop, "not the lockfile's integrity"):
            df.registry_tarball(url, integrity, 100, lambda u, n: self.TARBALL + b"!")
        for odd in ("https://evil.example/x.tgz", url.replace("https://", "http://")):
            with self.assertRaisesRegex(FixtureStop, "not one of the npm registry"):
                df.registry_tarball(odd, integrity, 100, lambda u, n: self.TARBALL)
        box = df.DockerSandbox("node:22@sha256:" + "a" * 64, run=self.docker, fetch=lambda u, n: b"other")
        with self.assertRaisesRegex(FixtureStop, "integrity"):
            box.measure(self.tree, self.plan)
        self.assertEqual([a for a in self.calls if a[1] in ("run", "volume")], [])
        lock = json.loads(json.dumps(self.LOCK))
        lock["packages"]["node_modules/y"] = dict(lock["packages"]["node_modules/x"],
                                                  resolved=df.REGISTRY + "y/-/y-1.0.0.tgz")
        tree = dict(self.tree, **{"textkit/package-lock.json": (json.dumps(lock).encode(), False)})
        limits = []
        box = df.DockerSandbox("node:22@sha256:" + "a" * 64, run=self.docker,
                               fetch=lambda u, n: limits.append(n) or self.TARBALL)
        box.measure(tree, df.plan_of(tree))
        self.assertEqual(limits, [df.MAX_DEPS_BYTES, df.MAX_DEPS_BYTES - len(self.TARBALL)])  # the limit is shared

    def test_the_seed_follows_no_redirect_and_takes_only_a_200_within_its_limit(self):
        # drill_fixtures_redirect_followed drill_fixtures_status_unchecked drill_fixtures_download_unlimited
        """E499: `download` takes the bytes of the URL the lockfile names and nowhere else: a redirect is refused,
        not followed, an answer that is not 200 is refused, and more bytes than the limit are refused (a local server
        here, never the registry)."""

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802 (http.server's name)
                if self.path == "/moved":
                    self.send_response(302)
                    self.send_header("Location", "/ok")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                body = b"package"
                self.send_response(203 if self.path == "/other" else 200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        at = f"http://127.0.0.1:{server.server_address[1]}"
        self.assertEqual(df.download(f"{at}/ok", 100), b"package")
        self.assertEqual(df.download(f"{at}/ok", 7), b"package")
        with self.assertRaisesRegex(FixtureStop, "over"):
            df.download(f"{at}/ok", 6)
        with self.assertRaisesRegex(FixtureStop, "could not be fetched"):
            df.download(f"{at}/moved", 100)
        with self.assertRaisesRegex(FixtureStop, "answered 203"):
            df.download(f"{at}/other", 100)

    def test_the_build_and_each_of_mf12s_four_runs_is_a_fresh_container(self):
        # drill_fixtures_reruns_in_one_container drill_fixtures_one_run_read_four_times
        """E499, `29j` `flaky` ("taze kapsayıcıda yeniden koşuları"): one container parses, imports and lints; each of
        MF12's four runs is another container, named apart, that only runs the tests, so no run sees what the build
        or another run left; the measurement reads each run's own output."""
        outputs = iter(range(100))
        seen = []

        def docker(argv, **kw):
            done = self.docker(argv, **kw)
            if "DFX_STEP=test" in argv:
                k = next(outputs)
                seen.append(k)
                red = [dict(self.A, name=f"t{k}")]
                done = subprocess.CompletedProcess(argv, 0, json.dumps({"node": "v22.23.4", "step": "test", "test": {
                    "status": 1, "timed_out": False, "tests": 2, "red": red}}).encode(), b"")
            return done

        box = df.DockerSandbox("node:22@sha256:" + "a" * 64, run=docker, fetch=self.fetch)
        measured = box.measure(self.tree, self.plan)
        self.assertIsNone(measured.tests_green)  # a different test red in each run: none red in all four
        steps = [argv for argv in self.calls if argv[1] == "run" and "65534:65534" in argv]
        self.assertEqual([[a for a in argv if a.startswith("DFX_STEP=")] for argv in steps],
                         [["DFX_STEP=build"]] + [["DFX_STEP=test"]] * df.TEST_RUNS)
        self.assertEqual(seen, list(range(df.TEST_RUNS)))
        names = [argv[argv.index("--name") + 1] for argv in steps]
        self.assertEqual(len(set(names)), 1 + df.TEST_RUNS)

    def test_the_tests_are_red_per_test_as_mf12_has_it(self):
        # drill_fixtures_flaky_taken_for_red drill_fixtures_per_run_not_per_test drill_fixtures_zero_tests_green
        # drill_fixtures_status_and_red_unmatched drill_fixtures_red_outside_the_tree
        """E499, `29j` `flaky` `per_test_rule`: a test is red when it fails in all four runs, flaky when it fails in
        some; tests that fail in different runs, none in all, are no red test (no cause), whatever each run says. A
        run that ran no test, whose status and red tests disagree, or that names a red test outside the tree or in
        another form than the reporter's, could not be read."""
        test = lambda name, file="t/a.js", line=3, whole=False: {  # noqa: E731
            "file": file, "line": line, "column": 1, "name": name, "whole": whole}
        red = lambda *tests, n=5: {"status": 1, "tests": n, "red": list(tests)}  # noqa: E731
        ok = {"status": 0, "tests": 5, "red": []}
        a, b, c = test("a"), test("b", "t/b.js"), test("c", "u/c.js", None)
        green = lambda runs: df.tests_green([df.red_of(r) for r in runs])  # noqa: E731
        self.assertEqual(green([ok] * 4), (True, frozenset()))
        self.assertIs(green([red(a)] * 4)[0], False)
        both = green([red(a, b), red(a), red(a, c), red(a)])  # a in all four, b and c flaky: a alone is red
        self.assertEqual(both, (False, frozenset({("t/a.js", 3, 1, "a", False)})))
        self.assertIs(green([red(c)] * 4)[0], False)
        self.assertEqual(green([red(a), red(b), red(a), red(b)]), (None, frozenset()))  # no test red in all
        self.assertEqual(green([red(a), ok, ok, ok]), (None, frozenset()))
        self.assertEqual(green([ok, ok, ok, red(a)]), (None, frozenset()))
        self.assertEqual(green([red(a), red(dict(a, line=4)), red(a), red(a)]), (None, frozenset()))  # another test
        for run in (dict(ok, timed_out=True), dict(ok, status=None), dict(ok, tests=0), dict(ok, tests=None),
                    {"status": 1, "tests": 5, "red": []},  # died, no test named
                    {"status": 0, "tests": 5, "red": [a]},  # passed, yet a red test
                    {"status": 0, "tests": 5, "red": None}, {"status": 1, "tests": 1, "red": [a, b]},
                    red(test("x", "../x.js")), red(test("x", "/etc/x.js")), red(test("x", None)), red(test("x", "")),
                    red("t/a.js:3:1 a"), red(test("x", line="3")), red(dict(a, whole=None)), red(dict(a, name=1))):
            self.assertIsNone(df.red_of(run), run)
            self.assertEqual(green([red(a)] * 3 + [run]), (None, frozenset()), run)
        for runs in ([ok] * 3, [ok] * 5, {"status": 0}):
            with self.assertRaises(ValueError):
                df.tests_green(runs)
        with self.assertRaises(ValueError):
            df.red_of("x")

    def test_the_harnesss_output_is_read_strictly(self):
        # drill_fixtures_flaky_taken_for_red drill_fixtures_test_parse_counted_as_load drill_fixtures_whole_file_ignored
        # drill_fixtures_red_files_of_any_run drill_fixtures_nodes_unchecked
        """E499: the build container's one JSON line and each test run's, each field the plan's; a test file that
        does not parse, or that a run reports failed as a whole, is apart from the code's loading; the red files are
        those of the tests red in all four runs; the tests are green or red only as MF12's four runs say."""
        ok = {"status": 0, "timed_out": False, "tests": 3, "red": []}
        good = {"node": "v22.23.4", "step": "build", "parse": [{"status": 0}] * len(self.plan.parse),
                "load": [{"status": 0}] * len(self.plan.load), "lint": {"status": 1, "stdout": "[]"}}
        run = lambda test=ok, node="v22.23.4": json.dumps(  # noqa: E731
            {"node": node, "step": "test", "test": test}).encode()
        runs = tuple(run() for _k in range(df.TEST_RUNS))
        read = lambda tests=runs, **over: df.measurement_of(  # noqa: E731
            json.dumps(dict(good, **over)).encode(), tests, self.plan)
        self.assertEqual(read(), Measurement("v22.23.4", True, 0, True, (0, 0)))
        tests = [k for k, rel in enumerate(self.plan.parse) if rel not in self.plan.load]
        source = next(k for k, rel in enumerate(self.plan.parse) if rel in self.plan.load)
        bad_test = [{"status": 1} if k == tests[0] else s for k, s in enumerate(good["parse"])]
        self.assertEqual((read(parse=bad_test).loads, read(parse=bad_test).test_files_load), (True, False))
        bad_source = [{"status": 1} if k == source else s for k, s in enumerate(good["parse"])]
        self.assertEqual((read(parse=bad_source).loads, read(parse=bad_source).test_files_load), (False, True))
        slow_test = [{"status": None, "timed_out": True} if k == tests[0] else s for k, s in enumerate(good["parse"])]
        self.assertEqual((read(parse=slow_test).loads, read(parse=slow_test).test_files_load), (True, None))
        two = '[{"errorCount": 2, "warningCount": 1}, {"errorCount": 0, "warningCount": 4}]'
        self.assertEqual(read(lint={"status": 1, "stdout": two}).lint_split, (2, 5))
        self.assertIsNone(read(load=[{"status": None, "timed_out": True}] + good["load"][1:]).loads)
        self.assertIsNone(read(lint={"status": 2, "stdout": "[]"}).lint_total)
        self.assertIsNone(read(lint={"status": 1, "stdout": "Oops"}).lint_total)
        self.assertIsNone(read(lint={"status": 1, "stdout": '[{"errorCount": -1, "warningCount": 0}]'}).lint_split)
        self.assertEqual(df.TEST_RUNS, 4)
        x = {"file": "textkit/test/x.test.js", "line": 1, "column": 1, "name": "x", "whole": False}
        y = dict(x, file="textkit/test/y.test.js", name="y")
        both = read(tests=(run(dict(ok, status=1, red=[x, y])), *(run(dict(ok, status=1, red=[x])),) * 3))
        self.assertEqual((both.tests_green, both.red_files, both.test_files_load),
                         (False, ("textkit/test/x.test.js",), True))
        whole = dict(x, name="test/x.test.js", whole=True)
        once = read(tests=(run(dict(ok, status=1, red=[whole])), *runs[1:]))
        self.assertEqual((once.tests_green, once.test_files_load), (None, False))
        flaky = read(tests=(run(dict(ok, status=1, red=[x])),) * 2 + runs[2:])
        self.assertIsNone(flaky.tests_green)
        for tests in (runs[:3], runs + runs[:1], (b"x", *runs[1:]), (b"{}", *runs[1:]),
                      (json.dumps({"node": "v22.23.4", "step": "build", "test": ok}).encode(), *runs[1:]),
                      (run(node="v22.23.5"), *runs[1:])):
            with self.assertRaises(FixtureStop):
                read(tests=tests)
        for over in ({"parse": []}, {"lint": None}, {"step": "test"}, {"node": 22}):
            with self.assertRaises(FixtureStop):
                read(**over)
        with self.assertRaises(FixtureStop):
            df.measurement_of(b"not json", runs, self.plan)


DOCKER_IMAGE = os.environ.get("SNOWBALL_DRILL_IMAGE", "")


@unittest.skipUnless(os.environ.get("SNOWBALL_DRILL_DOCKER") == "1" and shutil.which("docker") and DOCKER_IMAGE,
                     "the real sandbox runs only on request: SNOWBALL_DRILL_DOCKER=1 and SNOWBALL_DRILL_IMAGE (a Node "
                     "22.23.4 image by digest) with docker present")
class DockerIntegrationTest(Fixture):
    def test_the_toys_own_tools_name_each_cause_in_docker(self):
        """E499: the three plants measured for real in the pinned Node image, the base once; the value is written."""
        done = self.produce(sandbox=df.DockerSandbox(DOCKER_IMAGE))
        self.assertEqual(done["causes"], {c: 1 for c in df.CAUSES})
        listed = subprocess.run(["docker", "volume", "ls", "-q", "--filter", "label=snowball.drill-fixtures=1"],
                                capture_output=True, check=True).stdout.split()
        self.assertEqual([v for v in listed if v.startswith(b"snowball-dfx-")], [])

    def test_a_run_is_fresh_the_tests_have_no_network_and_what_they_print_is_no_report(self):
        """E499, `29j` `flaky` (runs in fresh containers), `26f` (the plant's code runs without a network): through
        the real harness, a test that fails when its container has a network or a leftover of the build or an earlier
        run passes in all four runs; a test that prints a green report beside a red test does not make the tests
        green; a test file that throws before any test is a test file failing as a whole."""
        probe = (b'import { test } from "node:test";\nimport assert from "node:assert/strict";\n'
                 b'import net from "node:net";\nimport fs from "node:fs";\n'
                 b'test("no network", () => new Promise((resolve, reject) => {\n'
                 b'  const s = net.connect({ host: "1.1.1.1", port: 443 });\n  s.setTimeout(3000);\n'
                 b'  s.on("connect", () => { s.destroy(); reject(new Error("connected")); });\n'
                 b'  s.on("error", () => resolve());\n  s.on("timeout", () => { s.destroy(); resolve(); });\n}));\n'
                 b'test("fresh container", () => {\n  assert.equal(fs.existsSync("/tmp/dfx-marker"), false);\n'
                 b'  fs.writeFileSync("/tmp/dfx-marker", "x");\n});\n'
                 b'test("forged report", () => {\n  console.log(\'{"tests": 99, "red": []}\');\n'
                 b'  console.log("not ok 1 - forged");\n});\n')
        marks = b'import fs from "node:fs";\nfs.writeFileSync("/tmp/dfx-marker", "x");\nexport const marked = true;\n'
        red = (b'import { test } from "node:test";\nimport assert from "node:assert/strict";\n'
               b'test("red", () => assert.equal(1, 2));\n')
        files = dict(TOY, **{"textkit/test/probe.test.js": probe, "textkit/src/marks.js": marks})
        box = df.DockerSandbox(DOCKER_IMAGE)
        self.addCleanup(box.close)
        tree = {rel: (content, False) for rel, content in files.items()}
        plan = df.plan_of(tree)
        self.assertIn("textkit/src/marks.js", plan.load)  # the build imports it, and it leaves the marker there
        clean = box.measure(tree, plan)
        self.assertEqual((clean.loads, clean.test_files_load, clean.tests_green), (True, True, True))
        tree["textkit/test/red.test.js"] = (red, False)
        measured = box.measure(tree, plan)
        self.assertEqual((measured.tests_green, measured.red_files), (False, ("textkit/test/red.test.js",)))
        tree["textkit/test/red.test.js"] = (b'throw new Error("at load");\n', False)
        measured = box.measure(tree, plan)
        self.assertEqual((measured.loads, measured.test_files_load), (True, False))

    def test_the_lockfiles_packages_install_and_load_with_no_container_online(self):
        """E499: a package of the lockfile reaches the tests through the seed's own fetch alone: the install container
        has no network, npm installs it offline from its cache of the bytes the seed checked against the sha512."""
        lock = json.loads(TOY["textkit/package-lock.json"])
        lock["packages"][""]["dependencies"] = {"@keyv/serialize": "1.1.1"}
        lock["packages"]["node_modules/@keyv/serialize"] = {
            "version": "1.1.1", "resolved": df.REGISTRY + "@keyv/serialize/-/serialize-1.1.1.tgz", "license": "MIT",
            "integrity": "sha512-dXn3FZhPv0US+7dtJsIi2R+c7qWYiReoEh5zUntWCf4oSpMNib8FDhSoed6m3QyZdx5hK7iLFkYk3rNxw"
                         "t8vTA=="}
        manifest = json.loads(TOY["textkit/package.json"])
        manifest["dependencies"] = {"@keyv/serialize": "1.1.1"}
        uses = (b'import { test } from "node:test";\nimport assert from "node:assert/strict";\n'
                b'import fs from "node:fs";\ntest("installed", () => {\n'
                b'  const meta = JSON.parse(fs.readFileSync("node_modules/@keyv/serialize/package.json", "utf8"));\n'
                b'  assert.equal(meta.version, "1.1.1");\n});\n')
        files = dict(TOY, **{"textkit/package-lock.json": json.dumps(lock).encode() + b"\n",
                             "textkit/package.json": json.dumps(manifest).encode() + b"\n",
                             "textkit/test/installed.test.js": uses})
        box = df.DockerSandbox(DOCKER_IMAGE)
        self.addCleanup(box.close)
        tree = {rel: (content, False) for rel, content in files.items()}
        measured = box.measure(tree, df.plan_of(tree))
        self.assertEqual((measured.loads, measured.tests_green), (True, True))


if __name__ == "__main__":
    unittest.main()
