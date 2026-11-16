"""Git objects in git's own format, built in Python (tests only): the object source ``loop.gitobj`` reads.

``store(files, parents)`` -> ``(objects, commit)``: ``objects`` maps sha -> (type, content) for a commit (on
``parents``, none by default) whose tree holds
``files`` (path -> bytes for a ``100644`` file, or ``(mode, bytes)``; ``"120000"`` is a link, its bytes the
target); entries are sorted as git sorts them (a tree's name compared with a trailing ``/``). ``RealGit`` checks
that a tree built here has the id real git gave the same files.

``install_git(directory, answers)`` writes an executable ``git`` that speaks ``cat-file --batch``: for each
requested line it writes ``answers[line]`` (raw bytes, given hex-encoded in ``answers.json`` beside it) or
``<line> missing``, and exits after answering a line in ``exit_after``; it appends its argv, environment and
what its stdin and stdout are (``fds``) to ``calls.jsonl`` beside itself. Its ``init`` (the first argument after the options, ``-c`` and ``-C`` taking a value)
creates the directory named last, its ``fetch`` does nothing, its ``ls-remote`` writes ``listing`` and any command named
in ``outputs`` writes its bytes; each exits with ``exits[<command>]`` (0 when absent): the objects it then answers
stand for what a fetch brought.

``HistoryGit(directory)`` writes a ``git`` that answers ``ledger.founder``'s ref check from a linear history (see
the class); real git's answers to the same tests are its check.
"""

from __future__ import annotations

import hashlib
import json
import marshal
import os
import stat
import sys

REFEREE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REFEREE)

from loop.gitobj import object_id  # noqa: E402

AUTHOR = b"A <a@example.org> 1700000000 +0000"


def put(objects: dict, kind: str, data: bytes) -> str:
    sha = object_id(kind, data)
    objects[sha] = (kind, data)
    return sha


def tree(objects: dict, entries: list[tuple[bytes, bytes, str]]) -> str:
    """A tree object from ``(mode, name, sha)`` entries, written in the order given."""
    return put(objects, "tree", b"".join(m + b" " + n + b"\0" + bytes.fromhex(s) for m, n, s in entries))


def commit(objects: dict, tree_sha: str, message: bytes = b"m\n", parents: tuple = ()) -> str:
    return put(objects, "commit", b"tree %s\n%sauthor %s\ncommitter %s\n\n%s" % (
        tree_sha.encode(), b"".join(b"parent %s\n" % p.encode() for p in parents), AUTHOR, AUTHOR, message))


def _build(objects: dict, files: dict) -> str:
    here: dict[str, tuple[bytes, str]] = {}
    subs: dict[str, dict] = {}
    for path, value in files.items():
        head, _, rest = path.partition("/")
        if rest:
            subs.setdefault(head, {})[rest] = value
        else:
            mode, data = value if isinstance(value, tuple) else ("100644", value)
            here[head] = (mode.encode(), put(objects, "blob", data))
    for name, sub in subs.items():
        here[name] = (b"40000", _build(objects, sub))
    order = sorted(here, key=lambda n: n.encode() + (b"/" if here[n][0] == b"40000" else b""))
    return tree(objects, [(here[n][0], n.encode(), here[n][1]) for n in order])


def store_tree(files: dict, objects: dict) -> str:
    """The id of the tree holding ``files`` (``store``'s input), its objects added to ``objects``."""
    return _build(objects, files)


def store(files: dict, parents: tuple = (), objects: dict | None = None) -> tuple[dict, str]:
    """``objects`` (a new dict when ``None``) with a commit of ``files`` on ``parents`` added; the commit's id."""
    objects = {} if objects is None else objects
    return objects, commit(objects, _build(objects, files), parents=parents)


def from_dir(root: str) -> dict:
    """A directory's regular files as ``store`` input (executable bit kept)."""
    out: dict = {}
    for dirpath, _, names in os.walk(root):
        for n in names:
            p = os.path.join(dirpath, n)
            with open(p, "rb") as fh:
                data = fh.read()
            out[os.path.relpath(p, root).replace(os.sep, "/")] = (
                "100755" if os.access(p, os.X_OK) else "100644", data)
    return out


def parse_batch(stream: bytes) -> dict:
    """``git cat-file --batch`` output -> sha -> (type, content); its own parser, independent of ``GitBatch``."""
    out, i = {}, 0
    while i < len(stream):
        nl = stream.index(b"\n", i)
        sha, kind, size = stream[i:nl].decode().split()
        start = nl + 1
        out[sha] = (kind, stream[start:start + int(size)])
        assert stream[start + int(size):start + int(size) + 1] == b"\n"
        i = start + int(size) + 1
    return out


def batch_record(sha: str, kind: str, data: bytes) -> bytes:
    return b"%s %s %d\n" % (sha.encode(), kind.encode(), len(data)) + data + b"\n"


SCRIPT = '''#!%s
import json, os, sys
here = os.path.dirname(os.path.abspath(__file__))
with open("/proc/self/environ", "rb") as fh:
    env = dict(item.decode().split("=", 1) for item in fh.read().split(b"\\0") if item)
with open(os.path.join(here, "calls.jsonl"), "a") as fh:
    fh.write(json.dumps({"argv": sys.argv[1:], "env": env,
                         "fds": [os.path.realpath("/proc/self/fd/" + str(fd)) for fd in (0, 1)]}) + "\\n")
with open(os.path.join(here, "answers.json")) as fh:
    doc = json.load(fh)
args, i = sys.argv[1:], 0
while i < len(args) and args[i].startswith("-"):
    i += 2 if args[i] in ("-c", "-C") else 1
if i < len(args) and (args[i] in ("init", "fetch") or args[i] in doc["outputs"]):
    if args[i] == "init":
        os.makedirs(args[-1])
    sys.stdout.buffer.write(bytes.fromhex(doc["outputs"].get(args[i], "")))
    sys.exit(doc["exits"].get(args[i], 0))
answers = {k: bytes.fromhex(v) for k, v in doc["answers"].items()}
out = sys.stdout.buffer
for line in sys.stdin.buffer:
    key = line.rstrip(b"\\n").decode()
    out.write(answers.get(key, key.encode() + b" missing\\n"))
    out.flush()
    if key in doc["exit_after"]:
        sys.exit(0)
'''


def install_git(directory: str, answers: dict[str, bytes], exit_after: tuple = (), exits: dict | None = None,
                listing: bytes = b"", outputs: dict[str, bytes] | None = None) -> str:
    path = os.path.join(directory, "git")
    with open(path, "w") as fh:
        fh.write(SCRIPT % sys.executable)
    os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR)
    with open(os.path.join(directory, "answers.json"), "w") as fh:
        json.dump({"answers": {k: v.hex() for k, v in answers.items()}, "exit_after": list(exit_after),
                   "exits": exits or {},
                   "outputs": {k: v.hex() for k, v in ({"ls-remote": listing} | (outputs or {})).items()}}, fh)
    return path


def calls(directory: str) -> list[dict]:
    with open(os.path.join(directory, "calls.jsonl")) as fh:
        return [json.loads(line) for line in fh]


# ---------------------------------------------------------------- a history git (``ledger.founder``'s ref check)

HISTORY_SCRIPT = '''#!%s -IS
import hashlib, marshal, os, sys
here = os.path.dirname(os.path.abspath(__file__))
with open("/proc/self/environ", "rb") as fh:
    env = dict(item.decode().split("=", 1) for item in fh.read().split(b"\\0") if item)
with open(os.path.join(here, "calls"), "ab") as fh:  # marshal, json and re are slow to import
    fh.write(marshal.dumps({"argv": sys.argv[1:], "env": env}))
args, i, cwd, literal = sys.argv[1:], 0, os.getcwd(), False
while i < len(args) and args[i].startswith("-"):
    if args[i] == "-C":
        cwd = os.path.join(cwd, args[i + 1])
    literal = literal or args[i] == "--literal-pathspecs"
    i += 2 if args[i] in ("-c", "-C") else 1
args = args[i:]
if "GIT_DIR" in env:  # real git follows it; here it names no repository
    sys.exit(128)
top = os.path.realpath(cwd)
while not os.path.isfile(os.path.join(top, ".git", "history")):
    if os.path.dirname(top) == top:
        sys.exit(128)
    top = os.path.dirname(top)
with open(os.path.join(top, ".git", "history"), "rb") as fh:
    commits = marshal.load(fh)["commits"]
out = sys.stdout.buffer
def blob_id(data):
    return hashlib.sha1(b"blob %%d\\0" %% len(data) + data).hexdigest()
def at(commit, path):
    entry = commit["files"].get(path)
    return None if entry is None else (entry[0], bytes.fromhex(entry[1]))
def glob(pattern, path):  # "*" any run of characters, "/" too; "?" one character
    if not pattern:
        return not path
    if pattern[0] == "*":
        return any(glob(pattern[1:], path[k:]) for k in range(len(path) + 1))
    return bool(path) and pattern[0] in ("?", path[0]) and glob(pattern[1:], path[1:])
if args == ["rev-parse", "--show-toplevel"]:
    out.write(top.encode() + b"\\n")
elif args == ["rev-parse", "--git-path", "shallow"]:
    out.write(b".git/shallow\\n")
elif args[:4] == ["log", "-1", "--format=%%H", "--"] and len(args) == 5:
    if not commits:
        sys.exit(128)
    match = (lambda p: p == args[4]) if literal else (lambda p: glob(args[4], p))
    for n in range(len(commits) - 1, -1, -1):
        def seen(c):
            return sorted((p, at(c, p)) for p in c["files"] if match(p))
        if seen(commits[n]) != (seen(commits[n - 1]) if n else []):
            out.write(commits[n]["id"].encode() + b"\\n")
            break
elif args[:3] == ["ls-tree", "-z", "--full-tree"] and len(args) == 6 and args[4] == "--":
    found = [c for c in commits if c["id"] == args[3]]
    if not found:
        sys.exit(128)
    path, files = args[5], found[0]["files"]
    # the entry at the path; for a path ending in "/", the entries under it, sorted
    names = sorted({path + p[len(path):].split("/")[0] for p in files if p.startswith(path)}) \\
        if path.endswith("/") else [path]
    for name in names:
        if name in files:
            mode, data = at(found[0], name)
            out.write(b"%%s blob %%s\\t%%s\\0" %% (mode.encode(), blob_id(data).encode(), name.encode()))
        elif any(p.startswith(name + "/") for p in files):
            out.write(b"040000 tree %%s\\t%%s\\0" %% (hashlib.sha1(name.encode()).hexdigest().encode(),
                                                       name.encode()))
elif args[:2] == ["cat-file", "blob"] and len(args) == 3:
    blobs = {blob_id(e[1]): e[1] for c in commits for e in (at(c, p) for p in c["files"])}
    if args[2] not in blobs:
        sys.exit(128)
    out.write(blobs[args[2]])
else:
    sys.exit(129)
'''


class HistoryGit:
    """A ``git`` that answers the five commands ``ledger.founder``'s ref check runs (``rev-parse
    --show-toplevel``, ``rev-parse --git-path shallow``, ``log -1 --format=%H -- <path>``, ``ls-tree -z
    --full-tree <commit> -- <path>``, ``cat-file blob <sha>``) from a linear history kept in
    ``<top>/.git/history`` (``marshal``: the script imports nothing slow to start); any other command exits 129. The work tree is real files; ``commit`` records it.

    Its rules, as git's for a linear history: ``log`` names the newest commit whose files matching the path (a
    glob of ``*`` and ``?`` only, ``*`` crossing ``/``, unless ``--literal-pathspecs``) differ from its parent's, the oldest commit kept
    comparing against nothing (so a shallow boundary is where everything was added); ``ls-tree`` gives the path's
    entry (a file's mode and blob id, a link's ``120000``, ``040000`` for a path with files under it), or for a
    path ending in ``/`` the entries under it; ``-C`` sets the directory; a ``GIT_DIR`` in the environment names no repository (exit 128).
    That these rules give what real git gives is checked by ``tests/capture_ref_since.py``, which runs the same tests
    on real git and keeps each check's answer (``tests/fixtures/ref-since-real-git.json``).
    Each call's argv and environment are appended to ``calls`` beside the script (``calls()`` reads them)."""

    def __init__(self, directory: str):
        self.directory = directory
        self.path = os.path.join(directory, "git")
        with open(self.path, "w") as fh:
            fh.write(HISTORY_SCRIPT % sys.executable)
        os.chmod(self.path, os.stat(self.path).st_mode | stat.S_IXUSR)

    def calls(self) -> list[dict]:
        out: list[dict] = []
        if os.path.exists(os.path.join(self.directory, "calls")):
            with open(os.path.join(self.directory, "calls"), "rb") as fh:
                while fh.peek(1):
                    out.append(marshal.load(fh))
        return out

    @staticmethod
    def _history(top: str) -> dict:
        with open(os.path.join(top, ".git", "history"), "rb") as fh:
            return marshal.load(fh)

    @staticmethod
    def _save(top: str, history: dict) -> None:
        with open(os.path.join(top, ".git", "history"), "wb") as fh:
            marshal.dump(history, fh)

    def init(self, top: str) -> None:
        os.makedirs(os.path.join(top, ".git"))
        self._save(top, {"commits": []})

    def commit(self, top: str) -> str:
        """Record the work tree's files and links (not ``.git``) as a new commit; its id."""
        files: dict = {}
        for dirpath, dirs, names in os.walk(top):
            dirs[:] = [d for d in dirs if not (dirpath == top and d == ".git")]
            for n in names + [d for d in dirs if os.path.islink(os.path.join(dirpath, d))]:
                p = os.path.join(dirpath, n)
                rel = os.path.relpath(p, top).replace(os.sep, "/")
                if os.path.islink(p):
                    files[rel] = ["120000", os.readlink(p).encode().hex()]
                elif os.path.isfile(p):
                    with open(p, "rb") as fh:
                        files[rel] = ["100755" if os.access(p, os.X_OK) else "100644", fh.read().hex()]
        history = self._history(top)
        parent = history["commits"][-1]["id"] if history["commits"] else ""
        sha = hashlib.sha1(json.dumps([parent, files], sort_keys=True).encode()).hexdigest()
        history["commits"].append({"id": sha, "files": files})
        self._save(top, history)
        return sha

    def clone(self, top: str, depth: int, dest: str) -> None:
        """A clone of ``top``'s last ``depth`` commits into ``dest``, its tip checked out; ``.git/shallow`` names
        the oldest kept commit when an older one was left out."""
        commits = self._history(top)["commits"]
        kept = commits[-depth:]
        self.init(dest)
        self._save(dest, {"commits": kept})
        if len(kept) < len(commits):
            with open(os.path.join(dest, ".git", "shallow"), "w") as fh:
                fh.write(kept[0]["id"] + "\n")
        for path, (mode, data) in kept[-1]["files"].items():
            p = os.path.join(dest, path)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            if mode == "120000":
                os.symlink(bytes.fromhex(data).decode(), p)
            else:
                with open(p, "wb") as fh:
                    fh.write(bytes.fromhex(data))
