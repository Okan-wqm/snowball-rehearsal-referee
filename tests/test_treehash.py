"""D1 (asama-0/01), MF17's cek: ``loop.treehash``, ``referee_tree_sha256`` by tohum/26c's rule.

- the known answer of 26c (``/vec/treehash/three-files.tar``'s three files, rebuilt here byte for byte, so the test
  needs no ``/vec``): ``d255bfaa...``; and the rule computed independently (the lines, byte-sorted) on other trees;
- what does not enter: directories, the executable bit, entry order, files outside ``referee/``;
- every refusal of 26c, each alone, anywhere in the archive or under ``referee/`` as the rule says, and the places
  where the same name is not refused (an operator name below the top, ``.git`` as part of a name);
- the git reader: a commit built from the same files has the tar's hash; a link in it is refused; a gitlink is
  ``loop.gitobj``'s ``tree_submodule``; the brain's own HEAD agrees with ``git ls-tree`` (``RealGit``, skipped
  where git is absent);
- the command line: exit 0 with the hash, 1 with the reasons, 2 for an archive that cannot be read.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest

REFEREE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REFEREE)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from loop import gitobj as G  # noqa: E402
from loop import pulled as P  # noqa: E402
from loop import treehash as T  # noqa: E402
import git_store as S  # noqa: E402

KNOWN = "d255bfaa4f3afb55f037a81d40ba8e44896babc20fbd5883ca291f003cd25037"  # tohum/26c
THREE = [("referee/", "dir", b"", 0o775), ("referee/a.py", "file", b'print("a")\n', 0o664),
         ("referee/loop/", "dir", b"", 0o775), ("referee/loop/job.py", "file", b"x = 1\n", 0o664),
         ("referee/run.sh", "file", b"#!/bin/sh\necho ok\n", 0o775)]


def tar_of(entries, fmt=tarfile.PAX_FORMAT) -> bytes:
    """A tar from ``(name, kind, data, mode)``; kinds file, dir, link, fifo, hard (a hard link to ``data``)."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w", format=fmt, encoding="utf-8", errors="surrogateescape") as tar:
        for name, kind, data, mode in entries:
            info = tarfile.TarInfo(name)
            info.mode = mode
            if kind == "file":
                info.size = len(data)
                tar.addfile(info, io.BytesIO(data))
                continue
            info.type = {"dir": tarfile.DIRTYPE, "link": tarfile.SYMTYPE, "fifo": tarfile.FIFOTYPE,
                         "hard": tarfile.LNKTYPE}[kind]
            if kind in ("link", "hard"):
                info.linkname = data.decode()
            tar.addfile(info)
    return buf.getvalue()


def independent(files: dict[str, bytes]) -> str:
    """26c's rule written again, separately: files maps a path under referee/ to its bytes."""
    lines = sorted(("%s  %s\n" % (hashlib.sha256(d).hexdigest(), p)).encode() for p, d in files.items())
    return hashlib.sha256(b"".join(lines)).hexdigest()


def triples(files: dict[str, bytes]) -> list[tuple[str, str, bytes]]:
    return [(p, "file", d) for p, d in files.items()]


class KnownAnswer(unittest.TestCase):
    def test_the_pages_known_answer(self):
        self.assertEqual(T.of_tar(tar_of(THREE)), KNOWN)
        self.assertEqual(T.of_tar(tar_of(THREE, tarfile.GNU_FORMAT)), KNOWN)
        self.assertEqual(T.of_tar(tar_of(THREE, tarfile.USTAR_FORMAT)), KNOWN)

    def test_the_rule_on_other_trees(self):
        # byte order: "B" < "a" < "a b" < "a/"; the separator is two spaces; the path is relative to referee/
        files = {"a": b"1", "B": b"2", "a b": b"3", "a0/x": b"", "é/y": b"4" * 10000}
        self.assertEqual(T.digest(triples({"referee/" + p: d for p, d in files.items()})), independent(files))
        self.assertNotEqual(independent({"a": b"1"}), independent({"a": b"2"}))
        self.assertNotEqual(T.digest(triples({"referee/a": b"1"})), T.digest(triples({"referee/b": b"1"})))


class WhatDoesNotEnter(unittest.TestCase):
    def test_directories_mode_and_order(self):
        plain = [(n, k, d, 0o644) for n, k, d, _ in THREE if k == "file"]
        self.assertEqual(T.of_tar(tar_of(plain)), KNOWN)                 # no directory entries
        self.assertEqual(T.of_tar(tar_of(list(reversed(THREE)))), KNOWN)  # another order
        extra = THREE + [("referee/empty/", "dir", b"", 0o755)]
        self.assertEqual(T.of_tar(tar_of(extra)), KNOWN)                 # an empty directory

    def test_files_outside_referee(self):
        outside = THREE + [("candidates/t/c/finding.json", "file", b"{}", 0o644), ("referee.txt", "file", b"x", 0o644),
                           ("refereeX/a", "file", b"y", 0o644), ("README", "file", b"z", 0o644)]
        self.assertEqual(T.of_tar(tar_of(outside)), KNOWN)


class Refusals(unittest.TestCase):
    def refused(self, entries) -> list[str]:
        with self.assertRaises(T.TreeHashError) as ctx:
            T.of_tar(tar_of(THREE + entries))
        return ctx.exception.reasons

    def test_links_and_special_files_anywhere(self):
        self.assertEqual(self.refused([("referee/l", "link", b"a.py", 0o777)]), ["link:referee/l"])
        self.assertEqual(self.refused([("docs/l", "link", b"../x", 0o777)]), ["link:docs/l"])
        self.assertEqual(self.refused([("referee/f", "fifo", b"", 0o644)]), ["special:referee/f"])
        self.assertEqual(self.refused([("other/h", "hard", b"referee/a.py", 0o644)]), ["special:other/h"])

    def test_path_rules_anywhere(self):
        cases = {
            "x/\udcffname": "path_not_utf8:x/\\xffname",
            "referee/a\x01b": "path_control:referee/a\\x01b",
            "docs/a\x7fb": "path_control:docs/a\\x7fb",
            "docs/a\x85b": "path_control:docs/a\\x85b",
            "referee/a\\b": "path_backslash:referee/a\\b",
            "docs/c:d": "path_colon:docs/c:d",
            "/abs/x": "path_absolute:/abs/x",
            "docs/../x": "path_dotdot:docs/../x",
            "referee/.GIT/config": "path_dotgit:referee/.GIT/config",
            "x/.git": "path_dotgit:x/.git",
        }
        for name, reason in cases.items():
            with self.subTest(name=name):
                self.assertEqual(self.refused([(name, "file", b"q", 0o644)]), [reason])

    def test_near_names_that_are_not_refused(self):
        for name in ("referee/.gitignore", "referee/x.git", "referee/a..b", "referee/sub/setup",
                     "referee/sub/bootstrap/x", "referee/setup.py", "docs/policy.json"):
            with self.subTest(name=name):
                files = {n[len("referee/"):]: d for n, k, d, _ in THREE if k == "file"}
                if name.startswith("referee/"):
                    files[name[len("referee/"):]] = b"q"
                self.assertEqual(T.of_tar(tar_of(THREE + [(name, "file", b"q", 0o644)])), independent(files))

    def test_casefold_collisions_under_referee(self):
        self.assertEqual(self.refused([("referee/A.py", "file", b"", 0o644)]),
                         ["casefold_collision:A.py", "casefold_collision:a.py"])
        # two directories on the way
        self.assertEqual(self.refused([("referee/LOOP/other.py", "file", b"", 0o644)]),
                         ["casefold_collision:LOOP", "casefold_collision:loop"])
        # a file and a directory of one name
        self.assertEqual(self.refused([("referee/Run.sh/x", "file", b"", 0o644)]),
                         ["casefold_collision:Run.sh", "casefold_collision:run.sh"])
        # casefold, not lower: German sharp s
        self.assertEqual(self.refused([("referee/straße", "file", b"", 0o644),
                                       ("referee/STRASSE", "file", b"", 0o644)]),
                         ["casefold_collision:STRASSE", "casefold_collision:straße"])
        # outside referee/ the same pair is not judged
        self.assertEqual(T.of_tar(tar_of(THREE + [("docs/A", "file", b"", 0o644), ("docs/a", "file", b"", 0o644)])),
                         KNOWN)

    def test_operator_names_at_the_top(self):
        for name in T.OPERATOR_NAMES + ("Setup", "POLICY.JSON", "BootStrap"):
            with self.subTest(name=name):
                self.assertEqual(self.refused([("referee/%s" % name, "file", b"", 0o644)]),
                                 ["operator_name:%s" % name])
        self.assertEqual(self.refused([("referee/seats/", "dir", b"", 0o755)]), ["operator_name:seats"])
        self.assertEqual(set(T.OPERATOR_NAMES), {"policy.json", "control.json", "bootstrap.json", "setup", "seats",
                                                 "vectors", "bootstrap"})  # tohum/25a item 1

    def test_no_files_under_referee(self):
        for entries in ([], [("referee/", "dir", b"", 0o755)], [("referee/d/", "dir", b"", 0o755)],
                        [("referee", "file", b"x", 0o644)], [("other/a", "file", b"x", 0o644)]):
            with self.subTest(entries=entries):
                with self.assertRaises(T.TreeHashError) as ctx:
                    T.of_tar(tar_of(entries))
                self.assertEqual(ctx.exception.reasons, ["no_files"])

    def test_every_reason_is_listed(self):
        self.assertEqual(self.refused([("referee/l", "link", b"x", 0o777), ("docs/c:d", "file", b"", 0o644),
                                       ("referee/setup", "file", b"", 0o644)]),
                         ["link:referee/l", "operator_name:setup", "path_colon:docs/c:d"])

    def test_an_unknown_kind_is_a_programming_error(self):
        with self.assertRaises(ValueError):
            T.digest([("referee/a", "socket", b"")])


class Commit(unittest.TestCase):
    def test_a_commit_has_the_tars_hash(self):
        files = {n: d for n, k, d, _ in THREE if k == "file"}
        files["referee/run.sh"] = ("100755", files["referee/run.sh"])
        objects, commit = S.store(files)
        self.assertEqual(T.of_commit(objects.__getitem__, commit), KNOWN)

    def test_a_link_in_the_commit(self):
        objects, commit = S.store({"referee/a.py": b"x", "referee/l": ("120000", b"a.py")})
        with self.assertRaises(T.TreeHashError) as ctx:
            T.of_commit(objects.__getitem__, commit)
        self.assertEqual(ctx.exception.reasons, ["link:referee/l"])

    def test_a_gitlink_is_the_readers_refusal(self):
        objects: dict = {}
        blob = S.put(objects, "blob", b"x")
        sub = S.tree(objects, [(b"100644", b"a.py", blob), (b"160000", b"sub", "1" * 40)])
        top = S.tree(objects, [(b"40000", b"referee", sub)])
        with self.assertRaises(P.PulledError) as ctx:
            T.of_commit(objects.__getitem__, S.commit(objects, top))
        self.assertEqual(ctx.exception.reasons, ["tree_submodule:referee/sub"])

    def test_the_brains_own_head_agrees_with_git(self):
        top = os.path.dirname(REFEREE)
        if shutil.which("git") is None or not os.path.isdir(os.path.join(top, ".git")):
            self.skipTest("git or the brain's .git is absent in this sandbox")
        head = subprocess.run(["git", "-C", top, "rev-parse", "HEAD"], capture_output=True, text=True,
                              check=True).stdout.strip()
        listing = subprocess.run(["git", "-C", top, "ls-tree", "-r", "-z", head, "referee/"], capture_output=True,
                                 check=True).stdout
        files = {}
        for record in listing.split(b"\0")[:-1]:
            meta, path = record.split(b"\t", 1)
            blob = subprocess.run(["git", "-C", top, "cat-file", "blob", meta.split()[2].decode()],
                                  capture_output=True, check=True).stdout
            files[path.decode()[len("referee/"):]] = blob
        with G.GitBatch(os.path.join(top, ".git")) as source:
            self.assertEqual(T.of_commit(source, head), independent(files))


class CommandLine(unittest.TestCase):
    def run_cli(self, data: bytes | None, argv=None) -> tuple[int, dict]:
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "a.tar")
            if data is not None:
                with open(path, "wb") as fh:
                    fh.write(data)
            proc = subprocess.run([sys.executable, "-m", "loop.treehash"] + (argv or ["tar", path]), cwd=REFEREE,
                                  capture_output=True, timeout=120)
        return proc.returncode, json.loads(proc.stdout)

    def test_exits(self):
        self.assertEqual(self.run_cli(tar_of(THREE)), (0, {"ok": True, "referee_tree_sha256": KNOWN}))
        self.assertEqual(self.run_cli(tar_of(THREE + [("referee/l", "link", b"x", 0o777)])),
                         (1, {"ok": False, "reasons": ["link:referee/l"]}))
        self.assertEqual(self.run_cli(b"not a tar" * 100), (2, {"ok": False, "reasons": None}))
        self.assertEqual(self.run_cli(None), (2, {"ok": False, "reasons": None}))
        self.assertEqual(self.run_cli(b"", ["zip", "x"]), (2, {"ok": False, "reasons": None}))


if __name__ == "__main__":
    unittest.main()
