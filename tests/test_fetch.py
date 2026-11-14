"""Test 46 (asama-0/09), MF17, D1: ``loop.fetch``, one commit fetched by id into a new bare git directory.

Over the fake ``git`` of ``git_store`` on PATH (the referee's sandbox has no git), which records each process's
argv and environment and answers ``cat-file --batch`` with real git's records (``test_gitobj.real_objects``):

- the two commands and the read-back, exactly, with the environment of ``loop.gitobj.git_env`` plus
  ``GIT_TERMINAL_PROMPT=0`` (no inherited ``GIT_*`` or ``SSH_ASKPASS``), stdin and stdout ``/dev/null``;
- every unsafe input refused together before any process starts; the URLs that are accepted;
- a failing ``init`` or ``fetch``, a git that cannot start, a commit missing or not a commit after the fetch:
  each its reason, and the directory removed.

Real git: ``fixtures/git-fetch.json`` is git 2.47.3 running these commands against github.com and a local
``file://`` repository (``capture_git_fetch.py``); ``RealGit`` checks its argv is today's ``loop.fetch.argv`` and
what git did: a public commit fetched with no history, an unknown commit, a missing repository and a ``file://``
URL refused, and the ``SSH_ASKPASS`` program run only when it is put back after ``git_env``.

``loop.fetch.heads`` over the same fake ``git`` (its ``ls-remote`` writes a given answer): the two commands exactly,
with ``--git-dir`` of the fresh directory, removed afterwards; unsafe inputs refused before any process; the answer's
rules (exact names only, absent refs ``None``, a ref twice or a line of another form refused); failures. Real git:
``fixtures/git-heads.json`` (``capture_git_heads.py``): ``RealHeads`` checks its argv is today's
``loop.fetch.heads_argv``, the parse of a real answer, and that the ``--git-dir`` keeps a repository's
``url.<base>.insteadOf`` around the working directory from sending the read elsewhere (without it, it did).
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import unittest

REFEREE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REFEREE)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from loop import fetch as F  # noqa: E402
from loop import gitobj as G  # noqa: E402
from loop import pulled as P  # noqa: E402
from profile_tree import writable_base  # noqa: E402
import git_store as S  # noqa: E402
from test_gitobj import REAL_COMMIT, real_objects  # noqa: E402

URL = "https://github.com/Acme-org/some_repo"
CAPTURE = os.path.join(REFEREE, "tests", "fixtures", "git-fetch.json")
CONFIG = ["-c", "protocol.allow=never", "-c", "protocol.https.allow=always", "-c", "gc.auto=0",
          "-c", "maintenance.auto=false"]


class Fetch(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = writable_base("t-fetch-")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.bin = os.path.join(self.dir, "bin")
        os.mkdir(self.bin)
        self.git_dir = os.path.join(self.dir, "repo.git")
        self.answers = {sha: S.batch_record(sha, kind, data) for sha, (kind, data) in real_objects().items()}

    def fetch(self, answers=None, exits=None, url=URL, sha=REAL_COMMIT, git_dir=None, environ=None):
        git = S.install_git(self.bin, self.answers if answers is None else answers, exits=exits)
        F.fetch(self.git_dir if git_dir is None else git_dir, url, sha, git=git, environ=environ)

    def calls(self) -> list[dict]:
        path = os.path.join(self.bin, "calls.jsonl")
        return S.calls(self.bin) if os.path.exists(path) else []

    def refused(self, reasons, **kw) -> None:
        with self.assertRaises(P.PulledError) as ctx:
            self.fetch(**kw)
        self.assertEqual(ctx.exception.reasons, reasons)

    def test_init_fetch_then_the_commit_read_back(self):
        # askpass programs are dropped (values kept short: they are paths, not secrets)
        env = {"PATH": "/usr/bin", "HOME": "/h", "GIT_DIR": "/elsewhere", "GIT_ASKPASS": "/a", "SSH_ASKPASS": "/s",
               "GIT_CONFIG_PARAMETERS": "'core.x=1'"}
        read_end, write_end = os.pipe()  # this process's stdin is a pipe, so a git that inherited it would show it
        saved = os.dup(0)
        os.dup2(read_end, 0)
        try:
            self.fetch(environ=env)
        finally:
            os.dup2(saved, 0)
            for fd in (saved, read_end, write_end):
                os.close(fd)
        self.assertTrue(os.path.isdir(self.git_dir))
        calls = self.calls()
        self.assertEqual([c["argv"] for c in calls], [
            ["init", "--bare", "--quiet", self.git_dir],
            CONFIG + ["--git-dir=%s" % self.git_dir, "fetch", "--quiet", "--no-tags", "--no-recurse-submodules",
                      "--depth=1", "--no-write-fetch-head", "--", URL, "%s:refs/pulled" % REAL_COMMIT],
            ["--git-dir=%s" % self.git_dir, "cat-file", "--batch"],
        ])
        for call, prompt in zip(calls, (True, True, False)):
            git_vars = {k: v for k, v in call["env"].items() if k.startswith("GIT_")}
            want = dict({"GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull},
                        **({"GIT_TERMINAL_PROMPT": "0"} if prompt else {}))
            self.assertEqual(git_vars, want)
            self.assertEqual((call["env"]["PATH"], call["env"]["HOME"]), ("/usr/bin", "/h"))
            self.assertNotIn("SSH_ASKPASS", call["env"])
        self.assertEqual([c["fds"] for c in calls[:2]], [[os.devnull, os.devnull]] * 2)  # nothing can be asked

    def test_unsafe_inputs_start_no_process(self):
        os.mkdir(self.git_dir)
        self.refused(["fetch_sha_unsafe", "fetch_url_unsafe", "fetch_dir_unsafe"],
                     sha=REAL_COMMIT.upper(), url="file:///repo")
        for sha in ("", REAL_COMMIT[:39], REAL_COMMIT + "0", REAL_COMMIT.upper(), "g" * 40, "HEAD", None):
            with self.subTest(sha=sha):
                self.refused(["fetch_sha_unsafe"], sha=sha, git_dir=os.path.join(self.dir, "new.git"))
        for url in ("http://github.com/o/r", "file:///repo", "ssh://github.com/o/r", "git@github.com:o/r",
                    "git://github.com/o/r", "ext::sh -c touch% /tmp/x", "https://u:@github.com/o/r",
                    "https://u@github.com/o/r", "https://github.com", "https://github.com/",
                    "https://github.com/o/r?x=1", "https://github.com/o/r#x", "https://github.com/o/r/",
                    "https://github.com/../r", "https://github.com/o/..", "https://github.com/./r",
                    "https://-oProxyCommand/o/r", "https://github..com/o/r", "https://github.com:x/o/r",
                    "https://github.com/o r/x", "https://github.com/o/r\n", "HTTPS://github.com/o/r",
                    "--upload-pack=x", "https://github.com/o/%2e%2e", None):
            with self.subTest(url=url):
                self.refused(["fetch_url_unsafe"], url=url, git_dir=os.path.join(self.dir, "new.git"))
        for git_dir in ("repo.git", self.git_dir, os.path.join(self.dir, "missing", "repo.git"),
                        os.path.join(self.dir, "afile", "repo.git"), "/", None):
            with self.subTest(git_dir=git_dir):
                with open(os.path.join(self.dir, "afile"), "w"):
                    pass
                self.refused(["fetch_dir_unsafe"], git_dir=git_dir)
        self.assertEqual(self.calls(), [])
        self.assertTrue(os.path.isdir(self.git_dir))  # an existing directory is left as it was

    def test_accepted_urls(self):
        for url in (URL, URL + ".git", "https://github.com/o/.github", "https://ghe.example.org:8443/o/r.git",
                    "https://example.org/a/b/c", "https://localhost/r"):
            with self.subTest(url=url):
                shutil.rmtree(self.git_dir, ignore_errors=True)
                self.fetch(url=url)
                self.assertEqual(self.calls()[-2]["argv"][-2], url)

    def test_a_failing_step_removes_the_directory(self):
        for exits, reason, ran in (({"init": 3}, "fetch_failed:init:3", 1), ({"init": 1}, "fetch_failed:init:1", 1),
                                   ({"fetch": 1}, "fetch_failed:fetch:1", 2),
                                   ({"fetch": 128}, "fetch_failed:fetch:128", 2)):
            with self.subTest(reason):
                if self.calls():
                    os.remove(os.path.join(self.bin, "calls.jsonl"))
                self.refused([reason], exits=exits)
                self.assertFalse(os.path.lexists(self.git_dir))
                self.assertEqual(len(self.calls()), ran)  # nothing runs after the failing step

    def test_git_that_cannot_start(self):
        not_executable = os.path.join(self.dir, "plain-file")
        with open(not_executable, "w") as fh:
            fh.write("#!/bin/sh\n")
        for git in (os.path.join(self.dir, "no-git"), not_executable, self.dir):
            with self.subTest(git=git):
                with self.assertRaises(P.PulledError) as ctx:
                    F.fetch(self.git_dir, URL, REAL_COMMIT, git=git)
                self.assertEqual(ctx.exception.reasons, ["git_unavailable"])
                self.assertFalse(os.path.lexists(self.git_dir))

    def test_the_commit_is_checked_after_the_fetch(self):
        missing = dict(self.answers)
        del missing[REAL_COMMIT]
        self.refused(["object_missing:%s" % REAL_COMMIT], answers=missing)
        self.assertFalse(os.path.lexists(self.git_dir))
        tree = G._tree_sha(real_objects()[REAL_COMMIT][1])
        # the server's object under the commit's id is the tree: an id that is not a commit is refused
        self.refused(["object_mismatch:%s" % REAL_COMMIT],
                     answers=dict(self.answers, **{REAL_COMMIT: self.answers[tree].replace(
                         tree.encode(), REAL_COMMIT.encode(), 1)}))
        self.assertFalse(os.path.lexists(self.git_dir))
        self.refused(["git_batch_unreadable"], answers=dict(self.answers, **{REAL_COMMIT: b"garbage\n"}))
        self.assertFalse(os.path.lexists(self.git_dir))


class RealGit(unittest.TestCase):
    def setUp(self) -> None:
        with open(CAPTURE) as fh:
            self.doc = json.load(fh)

    def test_the_captured_commands_are_fetchs(self):
        self.assertEqual(self.doc["argv"], F.argv("git", "<git_dir>", "<url>", "<sha>"))

    def test_what_real_git_did(self):
        cases = self.doc["cases"]
        public = cases["public"]
        self.assertEqual((public["exits"], public["ref"], public["shallow"]), ([0, 0], public["sha"], [public["sha"]]))
        self.assertGreater(public["entries"], 0)
        for name in ("unknown_commit", "no_repository", "no_repository_prompt_kept", "file_transport"):
            with self.subTest(name):
                self.assertEqual(cases[name]["exits"], [0, 128])  # init, then a refused fetch
        self.assertEqual({n: c["prompt_script_ran"] for n, c in cases.items()},
                         {"public": False, "unknown_commit": False, "no_repository": False,
                          "no_repository_prompt_kept": True, "file_transport": False})
        for name in ("public", "unknown_commit", "no_repository"):
            self.assertTrue(F.URL.fullmatch(cases[name]["url"]) and G.SHA.fullmatch(cases[name]["sha"]))


HEADS = os.path.join(REFEREE, "tests", "fixtures", "git-heads.json")
STATE, INTEGRATION = "refs/heads/brain/state", "refs/heads/brain/integration"
A40, B40 = "a" * 40, "b" * 40


class Heads(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = writable_base("t-heads-")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.bin = os.path.join(self.dir, "bin")
        os.mkdir(self.bin)
        self.git_dir = os.path.join(self.dir, "heads.git")

    def heads(self, listing=b"", exits=None, url=URL, refs=(STATE, INTEGRATION), git_dir=None, environ=None):
        git = S.install_git(self.bin, {}, exits=exits, listing=listing)
        return F.heads(self.git_dir if git_dir is None else git_dir, url, list(refs) if isinstance(refs, tuple)
                       else refs, git=git, environ=environ)

    def calls(self) -> list[dict]:
        return S.calls(self.bin) if os.path.exists(os.path.join(self.bin, "calls.jsonl")) else []

    def refused(self, reasons, **kw) -> None:
        with self.assertRaises(P.PulledError) as ctx:
            self.heads(**kw)
        self.assertEqual(ctx.exception.reasons, reasons)
        self.assertFalse(os.path.lexists(self.git_dir))

    def test_the_two_commands_and_the_directory_removed(self):
        env = {"PATH": "/usr/bin", "HOME": "/h", "GIT_DIR": "/elsewhere", "SSH_ASKPASS": "/s"}
        got = self.heads(b"%s\t%s\n" % (A40.encode(), INTEGRATION.encode()), environ=env)
        self.assertEqual(got, {STATE: None, INTEGRATION: A40})
        calls = self.calls()
        self.assertEqual([c["argv"] for c in calls], [
            ["init", "--bare", "--quiet", self.git_dir],
            CONFIG[:4] + ["--git-dir=%s" % self.git_dir, "ls-remote", "--heads", "--", URL, STATE, INTEGRATION],
        ])
        for call in calls:
            self.assertEqual({k: v for k, v in call["env"].items() if k.startswith("GIT_")},
                             {"GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull, "GIT_TERMINAL_PROMPT": "0"})
            self.assertNotIn("SSH_ASKPASS", call["env"])
            self.assertEqual(call["fds"][0], os.devnull)
        self.assertFalse(os.path.lexists(self.git_dir))

    def test_unsafe_inputs_start_no_process(self):
        os.mkdir(self.git_dir)
        with self.assertRaises(P.PulledError) as ctx:
            self.heads(url="file:///r", refs=["main"])
        self.assertEqual(ctx.exception.reasons, ["fetch_url_unsafe", "fetch_dir_unsafe", "heads_ref_unsafe"])
        self.assertTrue(os.path.isdir(self.git_dir))  # an existing directory is left as it was
        os.rmdir(self.git_dir)
        for refs in ([], ["main"], ["refs/heads/"], ["refs/heads/a/"], ["refs/heads//a"], ["refs/heads/.a"],
                     ["refs/heads/a/.."], ["refs/heads/a/./b"], ["refs/tags/v1"], ["refs/heads/a b"],
                     ["refs/heads/a*"], ["--upload-pack=x"], ["refs/heads/a\n"], [STATE, STATE], [None], "refs/heads/a",
                     None):
            with self.subTest(refs=refs):
                self.refused(["heads_ref_unsafe"], refs=refs)
        self.assertEqual(self.calls(), [])

    def test_accepted_refs(self):
        for ref in ("refs/heads/main", STATE, "refs/heads/a.b/c_d-e", "refs/heads/a..b"):
            with self.subTest(ref=ref):
                self.assertEqual(self.heads(refs=[ref]), {ref: None})

    def test_the_answer(self):
        line = b"%s\t%s\n"
        both = line % (A40.encode(), STATE.encode()) + line % (B40.encode(), INTEGRATION.encode())
        self.assertEqual(self.heads(both), {STATE: A40, INTEGRATION: B40})
        self.assertEqual(self.heads(both.rstrip(b"\n")), {STATE: A40, INTEGRATION: B40})  # no final newline
        self.assertEqual(self.heads(b""), {STATE: None, INTEGRATION: None})
        # git matches a pattern against the end of a name: only the exact name counts
        tail = line % (B40.encode(), b"refs/heads/x/" + STATE.encode()) + line % (A40.encode(), STATE.encode())
        self.assertEqual(self.heads(tail), {STATE: A40, INTEGRATION: None})
        for bad in (line % (A40.encode(), STATE.encode()) * 2,
                    line % (A40.encode(), STATE.encode()) + line % (B40.encode(), STATE.encode()),
                    b"%s %s\n" % (A40.encode(), STATE.encode()), line % (A40.upper().encode(), STATE.encode()),
                    line % (A40[:39].encode(), STATE.encode()), b"\n", b"x\n", both + b"\n",
                    line % (A40.encode(), STATE.encode() + b"\tx"), b"%s\t\n" % A40.encode(),
                    (line % (A40.encode(), STATE.encode())).replace(b"\n", b"\r\n")):
            with self.subTest(bad=bad):
                self.refused(["heads_unreadable"], listing=bad)

    def test_failures(self):
        for exits, reason, ran in (({"init": 2}, "heads_failed:init:2", 1),
                                   ({"ls-remote": 128}, "heads_failed:ls-remote:128", 2)):
            with self.subTest(reason):
                if self.calls():
                    os.remove(os.path.join(self.bin, "calls.jsonl"))
                self.refused([reason], exits=exits, listing=b"%s\t%s\n" % (A40.encode(), STATE.encode()))
                self.assertEqual(len(self.calls()), ran)
        with self.assertRaises(P.PulledError) as ctx:
            F.heads(self.git_dir, URL, [STATE], git=os.path.join(self.dir, "no-git"))
        self.assertEqual(ctx.exception.reasons, ["git_unavailable"])
        self.assertFalse(os.path.lexists(self.git_dir))


class RealHeads(unittest.TestCase):
    def setUp(self) -> None:
        with open(HEADS) as fh:
            self.doc = json.load(fh)

    def test_the_captured_commands_are_heads(self):
        self.assertEqual(self.doc["argv"], F.heads_argv("git", "<git_dir>", "<url>", ["<ref>"]))

    def test_what_real_git_did(self):
        cases, refs = self.doc["cases"], self.doc["refs"]
        public = cases["public"]
        self.assertEqual(public["exits"], [0, 0])
        found = F.parse_heads(public["stdout"].encode(), refs)
        self.assertTrue(G.SHA.fullmatch(found["refs/heads/main"]))
        self.assertIsNone(found["refs/heads/brain/state"])
        # a url.<base>.insteadOf around the working directory: kept out by --git-dir, followed without it
        self.assertEqual(cases["redirect"]["stdout"], public["stdout"])
        self.assertEqual(cases["redirect_without_git_dir"]["stdout"], self.doc["brain_main"])
        self.assertNotEqual(self.doc["brain_main"], public["stdout"])
        self.assertEqual(cases["no_repository"]["exits"], [0, 128])
        self.assertFalse(any(c["prompt_script_ran"] for c in cases.values()))


if __name__ == "__main__":
    unittest.main()
