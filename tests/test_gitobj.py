"""Test 46 (asama-0/09), MF17, D1: ``loop.gitobj``, a commit's tree read from its git objects by content id.

- real git: ``fixtures/git-objects.batch.b64`` is ``git cat-file --batch-all-objects --batch | base64`` of a
  repository made with git 2.47.3 (recipe in ``REAL``; base64 because every file under ``referee/`` is text,
  asama-0/10 #genellik; the decoded stream is git's, ``REAL_BATCH_SHA256``): a nested file, an empty-free nested directory, a symlink, an executable,
  a CRLF file, ``hidden.txt`` marked ``export-ignore`` and ``subst.txt`` marked ``export-subst``. ``git archive``
  of that commit leaves ``hidden.txt`` out; ``tree_tar`` keeps it and keeps ``subst.txt`` unexpanded, the CRLF
  bytes, the link and the modes (asama-0/06: ``.gitattributes`` has no effect). The same files built by
  ``git_store`` give real git's tree id, so the in-Python objects below are git's format;
- ``GitBatch`` over a fake ``git`` on PATH that answers with real git's records: its argv, its environment
  (no inherited ``GIT_*``), a missing object, an answer that is not the protocol;
- every refusal of the walk, listed together; a lying source (content or type changed) is refused;
- modes: ``canonical`` reads each mode of ``fixtures/git-modes.json`` (real git 2.47.3's ``ls-tree`` of a tree
  holding it, made by ``capture_git_modes.py``) as git does, and the walk takes legacy modes as git's files,
  links and trees;
- ``lookup``: only the trees on a path are read; absent, through a non-tree, malformed, duplicate;
- ``tree_tar`` is deterministic and unpacks with ``loop.pulled.extract_tree``, empty directories included;
- ``parents``: real git 2.47.3's commits (``fixtures/git-parents.json``, made by ``capture_git_parents.py``: a root,
  a child, a merge, a message holding ``parent`` lines) read as git's ``rev-list --parents`` reads them, and
  ``git_store``'s commits on parents; a ``parent`` line that is no id and a commit with no ``tree`` line refused.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import shutil
import sys
import tarfile
import unittest

REFEREE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REFEREE)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from loop import gitobj as G  # noqa: E402
from loop import pulled as P  # noqa: E402
from profile_tree import writable_base  # noqa: E402
import git_store as S  # noqa: E402

FIXTURE = os.path.join(REFEREE, "tests", "fixtures", "git-objects.batch.b64")
MODES = os.path.join(REFEREE, "tests", "fixtures", "git-modes.json")
PARENTS = os.path.join(REFEREE, "tests", "fixtures", "git-parents.json")
PRINTED = {("file", 0o644): "100644", ("file", 0o755): "100755", ("link", 0o777): "120000",
           ("dir", 0o755): "040000", ("submodule", 0): "160000"}  # how git ls-tree prints each kind
# git init -b main; files as below; chmod +x x.sh; ln -s d/a.txt link; git add -A;
# GIT_AUTHOR_DATE=GIT_COMMITTER_DATE='1700000000 +0000' git -c user.name=A -c user.email=a@example.org commit -m fixture
REAL = {
    ".gitattributes": b"hidden.txt export-ignore\nsubst.txt export-subst\n",
    "d/a.txt": b"hi\n",
    "e/f/win.txt": b"crlf\r\n",
    "hidden.txt": b"hidden\n",
    "link": ("120000", b"d/a.txt"),
    "subst.txt": b"id: $Format:%H$\n",
    "x.sh": ("100755", b"#!/bin/sh\necho x\n"),
}
REAL_COMMIT = "265111f095bfacdaa9ab28c23b217d432eb3d60f"
REAL_TREE = "8eaf6ffd50d03ba51d2b619e8af7f244e86901cd"
REAL_BATCH_SHA256 = "e005a2c2412d5e2bef5d7b3dc7fab377e0dacc4d87e1833112d7372f5e378c70"  # of the stream git wrote


def real_batch() -> bytes:
    """git's stream: the fixture's lines (``base64``'s, 76 columns) joined and decoded, nothing else accepted."""
    with open(FIXTURE, "rb") as fh:
        return base64.b64decode(b"".join(fh.read().split(b"\n")), validate=True)


def real_objects() -> dict:
    return S.parse_batch(real_batch())


def members(tar_bytes: bytes) -> list[tuple]:
    with tarfile.open(fileobj=io.BytesIO(tar_bytes), mode="r:") as tar:
        return [(m.name, m.type, m.linkname, m.mode, tar.extractfile(m).read() if m.isreg() else None)
                for m in tar.getmembers()]


class RealGit(unittest.TestCase):
    def test_the_fixture_decodes_to_the_stream_git_wrote(self):
        self.assertEqual(hashlib.sha256(real_batch()).hexdigest(), REAL_BATCH_SHA256)

    def test_the_tree_of_a_real_commit(self):
        out = G.tree_tar(real_objects().__getitem__, REAL_COMMIT)
        self.assertEqual(members(out), [
            (".gitattributes", tarfile.REGTYPE, "", 0o644, REAL[".gitattributes"]),
            ("d", tarfile.DIRTYPE, "", 0o755, None),
            ("d/a.txt", tarfile.REGTYPE, "", 0o644, b"hi\n"),
            ("e", tarfile.DIRTYPE, "", 0o755, None),
            ("e/f", tarfile.DIRTYPE, "", 0o755, None),
            ("e/f/win.txt", tarfile.REGTYPE, "", 0o644, b"crlf\r\n"),
            ("hidden.txt", tarfile.REGTYPE, "", 0o644, b"hidden\n"),       # export-ignore has no effect
            ("link", tarfile.SYMTYPE, "d/a.txt", 0o777, None),
            ("subst.txt", tarfile.REGTYPE, "", 0o644, b"id: $Format:%H$\n"),  # export-subst has no effect
            ("x.sh", tarfile.REGTYPE, "", 0o755, b"#!/bin/sh\necho x\n"),
        ])

    def test_git_store_writes_gits_format(self):
        objects, commit = S.store(REAL)
        self.assertEqual(G._tree_sha(objects[commit][1]), REAL_TREE)
        self.assertEqual({sha for sha, (kind, _) in objects.items() if kind != "commit"},
                         {sha for sha, (kind, _) in real_objects().items() if kind != "commit"})


class Parents(unittest.TestCase):
    def test_as_real_git_reads_them(self):
        with open(PARENTS) as fh:
            commits = json.load(fh)["commits"]
        self.assertEqual([len(c["parents"]) for c in commits.values()], [1, 2, 1, 0])  # child, merge, message, root
        for name, c in commits.items():
            with self.subTest(commit=name):
                source = {c["sha"]: ("commit", bytes.fromhex(c["object"]))}.__getitem__
                self.assertEqual(G.parents(source, c["sha"]), c["parents"])

    def test_git_stores_commits_and_what_is_refused(self):
        objects, first = S.store({"a": b"1\n"})
        S.store({"a": b"2\n"}, (first,), objects)
        two = S.store({"a": b"3\n"}, (first, "b" * 40), objects)[1]
        self.assertEqual(G.parents(objects.__getitem__, first), [])
        self.assertEqual(G.parents(objects.__getitem__, two), [first, "b" * 40])
        tree = G.tree_of(objects.__getitem__, first)
        for raw in (b"tree %s\nparent %s\n\nm\n" % (tree.encode(), b"B" * 40),
                    b"tree %s\nparent %s\n\nm\n" % (tree.encode(), b"b" * 39),
                    b"parent %s\ntree %s\n\nm\n" % (first.encode(), tree.encode())):
            with self.subTest(raw=raw):
                sha = S.put(objects, "commit", raw)
                with self.assertRaises(P.PulledError) as cm:
                    G.parents(objects.__getitem__, sha)
                self.assertEqual(cm.exception.reasons, ["commit_unreadable"])
        with self.assertRaises(P.PulledError) as cm:
            G.parents(objects.__getitem__, "c" * 40)
        self.assertEqual(cm.exception.reasons, ["object_missing:%s" % ("c" * 40)])


class Batch(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = writable_base("t-gitobj-")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.answers = {sha: S.batch_record(sha, kind, data) for sha, (kind, data) in real_objects().items()}

    def source(self, answers=None, environ=None, exit_after=()) -> G.GitBatch:
        git = S.install_git(self.dir, self.answers if answers is None else answers, exit_after)
        return G.GitBatch("/repo.git", git=git, environ=environ)

    def test_reads_through_cat_file_batch(self):
        env = {"PATH": "/usr/bin", "GIT_DIR": "/elsewhere", "GIT_CONFIG_PARAMETERS": "'core.x=1'", "HOME": "/h"}
        with self.source(environ=env) as src:
            out = G.tree_tar(src, REAL_COMMIT)
        self.assertEqual(out, G.tree_tar(real_objects().__getitem__, REAL_COMMIT))
        (call,) = S.calls(self.dir)
        self.assertEqual(call["argv"], ["--git-dir=/repo.git", "cat-file", "--batch"])
        self.assertEqual(sorted(k for k in call["env"] if k.startswith("GIT_")),
                         ["GIT_CONFIG_GLOBAL", "GIT_CONFIG_NOSYSTEM"])
        self.assertEqual((call["env"]["GIT_CONFIG_GLOBAL"], call["env"]["GIT_CONFIG_NOSYSTEM"], call["env"]["HOME"]),
                         ("/dev/null", "1", "/h"))

    def test_a_missing_object(self):
        blob = G.object_id("blob", b"hi\n")
        del self.answers[blob]
        with self.source() as src:
            with self.assertRaises(KeyError):
                src(blob)
            with self.assertRaises(P.PulledError) as ctx:
                G.tree_tar(src, REAL_COMMIT)
        self.assertEqual(ctx.exception.reasons, ["object_missing:%s" % blob])

    def test_an_answer_outside_the_protocol(self):
        blob = G.object_id("blob", b"hi\n")
        record = self.answers[blob]
        # each answer is followed by git ending: a git that stalls with its pipe open is the job's timeout's
        for name, answer in (("short", record[:-3]), ("no newline", record[:-1] + b"X"), ("nothing", b""),
                             ("other sha", record.replace(blob.encode(), b"0" * 40, 1)),
                             ("other sha missing", b"%s missing\n" % (b"0" * 40)),
                             ("no size", b"%s blob\n" % blob.encode()),
                             ("size not a number", b"%s blob x\n" % blob.encode())):
            with self.subTest(name):
                with self.source(dict(self.answers, **{blob: answer}), exit_after=(blob,)) as src:
                    with self.assertRaises(P.PulledError) as ctx:
                        src(blob)
                self.assertEqual(ctx.exception.reasons, ["git_batch_unreadable"])
        with self.source() as src:
            with self.assertRaises(KeyError):
                src("not-a-sha")


class Walk(unittest.TestCase):
    def refused(self, objects: dict, commit: str) -> list[str]:
        with self.assertRaises(P.PulledError) as ctx:
            G.entries(objects.__getitem__, commit)
        return ctx.exception.reasons

    def test_a_lying_source_is_refused(self):
        objects, commit = S.store({"a": b"x"})
        blob = G.object_id("blob", b"x")
        self.assertEqual(self.refused(dict(objects, **{blob: ("blob", b"y")}), commit), ["object_mismatch:%s" % blob])
        self.assertEqual(self.refused(dict(objects, **{blob: ("tree", b"x")}), commit), ["object_mismatch:%s" % blob])
        self.assertEqual(self.refused(dict(objects, **{commit: ("blob", objects[commit][1])}), commit),
                         ["object_mismatch:%s" % commit])
        tree_sha = G._tree_sha(objects[commit][1])
        self.assertEqual(self.refused({commit: objects[commit]}, commit), ["object_missing:%s" % tree_sha])

    def test_the_commit(self):
        objects: dict = {}
        bad = S.put(objects, "commit", b"author x\n")
        self.assertEqual(self.refused(objects, bad), ["commit_unreadable"])
        for commit in ("A" * 40, "a" * 39, None):
            self.assertEqual(self.refused(objects, commit), ["commit_unreadable"])
        self.assertEqual(self.refused(objects, "a" * 40), ["object_missing:%s" % ("a" * 40)])

    def test_every_bad_entry_listed_together(self):
        objects: dict = {}
        blob = S.put(objects, "blob", b"x")
        odd_link = S.put(objects, "blob", b"\xff")
        sub = S.tree(objects, [(b"100644", b"..", blob), (b"100644", b"ok", blob)])
        broken = S.put(objects, "tree", b"100644 cut\0" + bytes(5))
        root = S.tree(objects, [
            (b"100644", b"", blob), (b"100644", b".", blob), (b"100644", b".GIT", blob), (b"100644", b"a/b", blob),
            (b"100644", b"\xfe", blob), (b"100644", b"dup", blob), (b"100755", b"dup", blob),
            (b"1006x4", b"malformed", blob), (b"160000", b"mod", blob), (b"120000", b"odd", odd_link),
            (b"40000", b"sub", sub), (b"40000", b"broken", broken), (b"100644", b"gone", "c" * 40),
        ])
        commit = S.commit(objects, root)
        self.assertEqual(self.refused(objects, commit), sorted([
            "tree_name:", "tree_name:.", "tree_name:.GIT", "tree_name:a/b", "tree_name:�",
            "tree_duplicate:dup", "tree_mode:malformed:1006x4", "tree_submodule:mod", "tree_link:odd",
            "tree_name:sub/..", "tree_unreadable:%s" % broken, "object_missing:%s" % ("c" * 40)]))

    def test_entries_need_their_own_type(self):
        objects: dict = {}
        blob = S.put(objects, "blob", b"x")
        tree_sha = S.tree(objects, [(b"100644", b"a", blob)])
        root = S.tree(objects, [(b"40000", b"d", blob), (b"100644", b"f", tree_sha)])
        self.assertEqual(self.refused(objects, S.commit(objects, root)),
                         sorted(["object_mismatch:%s" % blob, "object_mismatch:%s" % tree_sha]))


class Modes(unittest.TestCase):
    def setUp(self) -> None:
        with open(MODES) as fh:
            self.git = json.load(fh)

    def test_canonical_is_how_real_git_reads_a_mode(self):
        self.assertEqual(len(self.git["modes"]), 35)
        for mode, printed in self.git["modes"].items():
            with self.subTest(mode=mode):
                got = G.canonical(mode.encode())
                self.assertEqual(None if got is None else PRINTED[got], printed)

    def test_the_walk_reads_legacy_modes_as_git_does(self):
        objects: dict = {}
        blob = S.put(objects, "blob", b"hi\n")
        inner = S.tree(objects, [(b"100644", b"in", blob)])
        files = [(m, "f%d" % i) for i, (m, p) in enumerate(self.git["modes"].items()) if p in ("100644", "100755")]
        links = [(m, "l%d" % i) for i, (m, p) in enumerate(self.git["modes"].items()) if p == "120000"]
        dirs = [(m, "d%d" % i) for i, (m, p) in enumerate(self.git["modes"].items()) if p == "040000"]
        root = S.tree(objects, [(m.encode(), n.encode(), blob) for m, n in files + links]
                      + [(m.encode(), n.encode(), inner) for m, n in dirs])
        got = {e.path: (e.kind, e.mode, e.data) for e in G.entries(objects.__getitem__, S.commit(objects, root))}
        want = {n: ("file", int(self.git["modes"][m][-3:], 8), b"hi\n") for m, n in files}
        want.update({n: ("link", 0o777, b"hi\n") for _, n in links})
        want.update({n: ("dir", 0o755, b"") for _, n in dirs})
        want.update({n + "/in": ("file", 0o644, b"hi\n") for _, n in dirs})
        self.assertEqual(got, want)
        self.assertEqual(want["f5"], ("file", 0o644, b"hi\n"))  # 100664, the rival's case

    def test_every_gitlink_reading_is_a_submodule(self):
        objects: dict = {}
        blob = S.put(objects, "blob", b"hi\n")
        subs = [m for m, p in self.git["modes"].items() if p == "160000"]
        root = S.tree(objects, [(m.encode(), b"s%d" % i, blob) for i, m in enumerate(subs)])
        with self.assertRaises(P.PulledError) as ctx:
            G.entries(objects.__getitem__, S.commit(objects, root))
        self.assertEqual(ctx.exception.reasons, sorted("tree_submodule:s%d" % i for i in range(len(subs))))


class Lookup(unittest.TestCase):
    def setUp(self) -> None:
        self.objects: dict = {}
        o = self.objects
        self.blob = S.put(o, "blob", b"x")
        self.d = S.tree(o, [(b"100644", b"f", self.blob)])
        self.broken = S.put(o, "tree", b"100644 cut\0" + bytes(5))
        root = S.tree(o, [(b"100644", b"..", self.blob), (b"040000", b"a", self.d), (b"40000", b"b", self.broken),
                          (b"100664", b"file", self.blob), (b"120000", b"link", S.put(o, "blob", b"a")),
                          (b"1x", b"odd", self.blob), (b"160000", b"sub", self.blob),
                          (b"40000", b"two", self.d), (b"40000", b"two", self.d),
                          (b"40000", b"gone", "c" * 40)])
        self.commit = S.commit(o, root)

    def look(self, path, objects=None):
        return G.lookup((objects or self.objects).__getitem__, self.commit, path)

    def test_found_and_absent(self):
        # the root holds a bad name, a broken tree and a gitlink; looking up other paths does not judge them
        self.assertEqual(self.look("a"), ("dir", self.d))
        self.assertEqual(self.look("a/f"), ("file", self.blob))
        self.assertEqual(self.look("file"), ("file", self.blob))
        self.assertEqual(self.look("sub"), ("submodule", self.blob))
        self.assertEqual(self.look("odd"), ("malformed", self.blob))
        for path in ("none", "a/none", "a/f/x", "link/f", "file/x", "sub/x", "odd/x", "", "a/", "a//f", "A/f", "FILE"):
            with self.subTest(path=path):
                self.assertIsNone(self.look(path))

    def test_what_the_way_refuses(self):
        with self.assertRaises(P.PulledError) as ctx:
            self.look("two/f")
        self.assertEqual(ctx.exception.reasons, ["tree_duplicate:two"])
        with self.assertRaises(P.PulledError) as ctx:
            self.look("b/x")
        self.assertEqual(ctx.exception.reasons, ["tree_unreadable:%s" % self.broken])
        with self.assertRaises(P.PulledError) as ctx:
            self.look("gone/x")
        self.assertEqual(ctx.exception.reasons, ["object_missing:%s" % ("c" * 40)])
        with self.assertRaises(P.PulledError) as ctx:
            self.look("a/f", dict(self.objects, **{self.d: ("blob", self.objects[self.d][1])}))
        self.assertEqual(ctx.exception.reasons, ["object_mismatch:%s" % self.d])
        with self.assertRaises(P.PulledError) as ctx:
            G.lookup(self.objects.__getitem__, "a" * 39, "a")
        self.assertEqual(ctx.exception.reasons, ["commit_unreadable"])


class TreeTar(unittest.TestCase):
    def setUp(self) -> None:
        self.base = writable_base("t-gitobj-tar-")
        self.addCleanup(shutil.rmtree, self.base, ignore_errors=True)

    def test_deterministic_and_unpacked_by_extract_tree(self):
        objects, commit = S.store(REAL)
        empty = S.tree(objects, [])
        root = G.parse_tree(objects[G._tree_sha(objects[commit][1])][1], "")
        commit = S.commit(objects, S.tree(objects, root + [(b"40000", b"z-empty", empty)]))
        out = G.tree_tar(objects.__getitem__, commit)
        self.assertEqual(out, G.tree_tar(dict(reversed(list(objects.items()))).__getitem__, commit))
        with tarfile.open(fileobj=io.BytesIO(out), mode="r:") as tar:
            self.assertEqual({(m.mtime, m.uid, m.gid, m.uname, m.gname) for m in tar.getmembers()},
                             {(0, 0, 0, "", "")})
        path = os.path.join(self.base, "tree.tar")
        with open(path, "wb") as fh:
            fh.write(out)
        dest = os.path.join(self.base, "tree")
        P.extract_tree(path, dest)
        self.assertEqual(os.listdir(os.path.join(dest, "z-empty")), [])
        self.assertEqual(os.readlink(os.path.join(dest, "link")), "d/a.txt")
        self.assertTrue(os.access(os.path.join(dest, "x.sh"), os.X_OK))
        with open(os.path.join(dest, "hidden.txt"), "rb") as fh:
            self.assertEqual(fh.read(), b"hidden\n")

    def test_what_the_tree_holds_is_left_to_extract_tree(self):
        # gitobj reads; an escaping symlink passes here and kos's extract_tree refuses it (one rule, one place)
        objects, commit = S.store({"l": ("120000", b"../../etc")})
        path = os.path.join(self.base, "tree.tar")
        with open(path, "wb") as fh:
            fh.write(G.tree_tar(objects.__getitem__, commit))
        with self.assertRaises(P.PulledError) as ctx:
            P.extract_tree(path, os.path.join(self.base, "tree"))
        self.assertEqual(ctx.exception.reasons, ["tree_unsafe"])


if __name__ == "__main__":
    unittest.main()
