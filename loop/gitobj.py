"""A commit's tree from its git objects, by content identity (``çek``, D1; stage 0).

Rules: asama-0/06 and tohum/24 (``çek`` builds the target's tree from the file list, blob by blob;
``export-ignore`` and ``.gitattributes`` filters have no effect, no file can be hidden; there is no ``.git``),
tohum/08 item 1 (``çek`` makes its trees an artifact by content identity), ``loop.pulled`` (``tree.tar``).

**Source.** An object source is a callable ``sha -> (type, content)`` that raises ``KeyError`` for an object it
does not have. ``GitBatch`` is one over ``git cat-file --batch`` of a local git directory (``loop.fetch`` fills
one with a commit); tests give a dict's ``__getitem__``. Nothing the source says is trusted:
``read`` recomputes every object's id, ``sha1(b"<type> <size>\\0" + content)`` (git's SHA-1 object format; a
SHA-256 repository is out of scope, ids are 40 lowercase hex), and refuses an object whose id or type differs.

**Modes** (``canonical``): a tree entry's mode is read as git reads it (``tree-walk.c``: ``get_mode`` then
``canon_mode``): octal digits, nothing else and at least one; then by its type bits (``mode & 0o170000``):
``0o100000`` a regular file, ``0o755`` when ``mode & 0o100`` else ``0o644`` (so the legacy ``100664`` is
``100644``); ``0o120000`` a symbolic link (its blob is the target); ``0o040000`` a tree (``40000`` and ``040000``
alike); anything else a gitlink (git reads ``644`` or ``140000`` as ``160000``). Only these low bits are read, so
git's accumulation in a 32-bit ``unsigned int`` (higher digits fall off) reads the same. ``fixtures/git-modes.json``
is real git's reading of 35 such modes.

**Walk** (``entries`` from a commit, ``walk`` from a tree): each tree object, depth first, every entry read and
verified. Reasons (``PulledError``; every one found is listed, sorted, the walk goes on past a bad entry):

- ``object_missing:<sha>`` (the source has no such object), ``object_mismatch:<sha>`` (its id or type is not
  the one asked for, e.g. a tree entry naming a blob), ``commit_unreadable`` (no ``tree <sha>`` first line),
  ``tree_unreadable:<sha>`` (not a sequence of ``<mode> <name>\\0<20 bytes>`` with a non-empty mode);
- ``tree_name:<path>``: an entry name git's own ``fsck`` refuses: empty, ``.``, ``..``, ``.git`` in any case,
  or holding ``/``; also a name that is not UTF-8 (``tarfile`` writes UTF-8 names; such a path is reported
  with replacement characters); ``tree_duplicate:<path>``: a name twice in one tree;
- ``tree_mode:<path>:<mode>``: a mode that is not octal digits (git: ``malformed mode in tree entry``);
- ``tree_link:<path>``: a symbolic link whose target is not UTF-8;
- ``tree_submodule:<path>``: a gitlink (a submodule's commit; its content is not in this repository, so a tree
  with one is refused rather than handed on without it).

**Lookup** (``lookup``): the entry at a ``/``-separated path, reading only the trees on the way: its kind
(``canonical``'s, or ``malformed`` for a mode that is not octal digits, so a malformed entry is not taken for an
absent one) and object id; ``None`` when a component is absent or one before the last is not a tree (a symbolic link
on the way is not followed). The trees on the way give ``tree_unreadable``, ``object_missing`` and
``object_mismatch``, and ``tree_duplicate`` for a component named twice; their other entries are not judged.

``tree_tar`` writes the walked tree as ``pulled``'s ``tree.tar`` (PAX): a directory per tree (``0o755``), a
regular file per file entry (``0o644`` or ``0o755``, the blob's bytes as they are: no end-of-line, ``export-subst``
or filter conversion), a symbolic link per link entry (its target as written, not checked here), ordered
by path, with mtime 0, uid and gid 0 and no owner names, so the same commit gives the same bytes. What a
link may point at, and what the tree may hold beyond the names above, stays ``loop.pulled.extract_tree``'s
rule in ``kos``. The whole tree is held in memory.

Not checked here, stated: git ``fsck``'s other name rules (NTFS and HFS spellings of ``.git``, ``.gitmodules``
as a link), tree entry order, and the commit's signature and author; its parents are read only by ``parents``.
"""

from __future__ import annotations

import hashlib
import io
import re
import subprocess
import tarfile
from typing import Callable, NamedTuple

from loop.pulled import PulledError

SHA = re.compile(r"[0-9a-f]{40}")
Source = Callable[[str], "tuple[str, bytes]"]

OCTAL = re.compile(rb"[0-7]+")


class Entry(NamedTuple):
    path: str
    kind: str        # "dir", "file" or "link"
    mode: int
    data: bytes      # file content or link target; b"" for a directory


def object_id(kind: str, data: bytes) -> str:
    return hashlib.sha1(b"%s %d\0" % (kind.encode(), len(data)) + data).hexdigest()


def read(source: Source, sha: str, kind: str) -> bytes:
    """The content of object ``sha``, which must be a ``kind``; ``PulledError`` otherwise."""
    try:
        got_kind, data = source(sha)
    except KeyError:
        raise PulledError(["object_missing:%s" % sha]) from None
    if got_kind != kind or not isinstance(data, bytes) or object_id(kind, data) != sha:
        raise PulledError(["object_mismatch:%s" % sha])
    return data


def _tree_sha(commit: bytes) -> str:
    first = commit.split(b"\n", 1)[0]
    if first.startswith(b"tree ") and SHA.fullmatch(first[5:].decode("ascii", "replace")):
        return first[5:].decode()
    raise PulledError(["commit_unreadable"])


def parents(source: Source, commit: str) -> list[str]:
    """The ids on ``commit``'s ``parent`` lines, in order (git writes them right after the ``tree`` line);
    ``PulledError`` (``commit_unreadable``: no ``tree`` first line, or a ``parent`` line whose id is not 40
    lowercase hex; ``object_*``)."""
    header = read(source, commit, "commit").split(b"\n\n", 1)[0].split(b"\n")
    _tree_sha(header[0])
    out = []
    for line in header[1:]:
        if not line.startswith(b"parent "):
            break
        sha = line[7:].decode("ascii", "replace")
        if not SHA.fullmatch(sha):
            raise PulledError(["commit_unreadable"])
        out.append(sha)
    return out


def parse_tree(data: bytes, sha: str) -> list[tuple[bytes, bytes, str]]:
    """``(mode, name, sha)`` of each entry of a tree object, in its order."""
    out, i = [], 0
    while i < len(data):
        space = data.find(b" ", i)
        nul = data.find(b"\0", space + 1) if space > i else -1
        if nul < 0 or nul + 21 > len(data):
            raise PulledError(["tree_unreadable:%s" % sha])
        out.append((data[i:space], data[space + 1:nul], data[nul + 1:nul + 21].hex()))
        i = nul + 21
    return out


def canonical(mode: bytes) -> tuple[str, int] | None:
    """``(kind, permission)`` git reads ``mode`` as: ``file``, ``link``, ``dir`` or ``submodule``; ``None`` when
    it is not octal digits (see the module)."""
    if not OCTAL.fullmatch(mode):
        return None
    value = int(mode, 8)
    kind = value & 0o170000
    if kind == 0o100000:
        return "file", 0o755 if value & 0o100 else 0o644
    if kind == 0o120000:
        return "link", 0o777
    if kind == 0o040000:
        return "dir", 0o755
    return "submodule", 0


def _name(raw: bytes) -> tuple[str, bool]:
    try:
        name = raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("utf-8", "replace"), False
    return name, name not in ("", ".", "..") and name.lower() != ".git" and "/" not in name


def tree_of(source: Source, commit: str) -> str:
    """The id of ``commit``'s tree; ``PulledError`` (``commit_unreadable``, ``object_*``)."""
    if not (isinstance(commit, str) and SHA.fullmatch(commit)):
        raise PulledError(["commit_unreadable"])
    return _tree_sha(read(source, commit, "commit"))


def walk(source: Source, tree: str) -> list[Entry]:
    """Every directory, file and link under tree ``tree``, paths relative to it, sorted; ``PulledError``."""
    out: list[Entry] = []
    reasons: list[str] = []
    stack = [("", tree)]
    while stack:
        prefix, tree = stack.pop()
        try:
            listed = parse_tree(read(source, tree, "tree"), tree)
        except PulledError as exc:
            reasons += exc.reasons
            continue
        seen: set[bytes] = set()
        for mode, raw, sha in listed:
            name, ok = _name(raw)
            path = prefix + name
            if not ok:
                reasons.append("tree_name:%s" % path)
                continue
            if raw in seen:
                reasons.append("tree_duplicate:%s" % path)
                continue
            seen.add(raw)
            kind, perm = canonical(mode) or (None, 0)
            try:
                if kind == "dir":
                    out.append(Entry(path, "dir", perm, b""))
                    stack.append((path + "/", sha))
                elif kind == "file":
                    out.append(Entry(path, "file", perm, read(source, sha, "blob")))
                elif kind == "link":
                    target = read(source, sha, "blob")
                    try:
                        target.decode("utf-8")
                    except UnicodeDecodeError:
                        reasons.append("tree_link:%s" % path)
                        continue
                    out.append(Entry(path, "link", perm, target))
                elif kind == "submodule":
                    reasons.append("tree_submodule:%s" % path)
                else:
                    reasons.append("tree_mode:%s:%s" % (path, mode.decode("ascii", "replace")))
            except PulledError as exc:
                reasons += exc.reasons
    if reasons:
        raise PulledError(sorted(set(reasons)))
    return sorted(out, key=lambda e: e.path)


def entries(source: Source, commit: str) -> list[Entry]:
    """Every directory, file and link of ``commit``'s tree, sorted by path; ``PulledError`` (see the module)."""
    return walk(source, tree_of(source, commit))


def lookup(source: Source, commit: str, path: str) -> tuple[str, str] | None:
    """``(kind, sha)`` of the entry at ``path`` in ``commit``'s tree, or ``None`` (see the module)."""
    kind, sha = "dir", tree_of(source, commit)
    for i, part in enumerate(path.split("/")):
        if kind != "dir":
            return None
        found = [(mode, s) for mode, raw, s in parse_tree(read(source, sha, "tree"), sha) if raw == part.encode()]
        if len(found) > 1:
            raise PulledError(["tree_duplicate:%s" % "/".join(path.split("/")[:i + 1])])
        if not found:
            return None
        kind, sha = (canonical(found[0][0]) or ("malformed", 0))[0], found[0][1]
    return kind, sha


def tree_tar(source: Source, commit: str) -> bytes:
    """``commit``'s tree as ``pulled``'s ``tree.tar`` (see the module); ``PulledError``."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w", format=tarfile.PAX_FORMAT) as tar:
        for e in entries(source, commit):
            info = tarfile.TarInfo(e.path)
            info.mode = e.mode  # TarInfo's mtime, uid and gid are 0
            if e.kind == "dir":
                info.type = tarfile.DIRTYPE
                tar.addfile(info)
            elif e.kind == "link":
                info.type, info.linkname = tarfile.SYMTYPE, e.data.decode("utf-8")
                tar.addfile(info)
            else:
                info.size = len(e.data)
                tar.addfile(info, io.BytesIO(e.data))
    return buf.getvalue()


def git_env(environ: dict[str, str] | None) -> dict[str, str]:
    """The environment of every git process the referee starts: ``environ`` without any ``GIT_*`` variable and
    without ``SSH_ASKPASS`` (real git 2.47.3 runs it for a user name and password even under
    ``GIT_TERMINAL_PROMPT=0``), then ``GIT_CONFIG_NOSYSTEM=1`` and ``GIT_CONFIG_GLOBAL=/dev/null`` (no system or
    user configuration is read)."""
    env = {k: v for k, v in (environ or {}).items() if not k.startswith("GIT_") and k != "SSH_ASKPASS"}
    env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL="/dev/null")
    return env


class GitBatch:
    """An object source over ``git --git-dir=<dir> cat-file --batch`` (one process, one object per request).

    Use as a context manager. The git directory is the caller's (a bare repository holding the commit); the
    process's environment is ``git_env``'s.
    A ``<sha> missing`` answer is ``KeyError``; any other answer that is not ``<sha> <type> <size>`` followed
    by exactly that many bytes and a newline, or git ending before that, is
    ``PulledError(["git_batch_unreadable"])``. A git that stops answering but keeps its output open blocks the
    read; no timeout is kept here (the job's ``timeout-minutes`` bounds it).
    """

    def __init__(self, git_dir: str, git: str = "git", environ: dict[str, str] | None = None):
        self.argv = [git, "--git-dir=%s" % git_dir, "cat-file", "--batch"]
        self.env = git_env(environ)
        self.proc: subprocess.Popen | None = None

    def __enter__(self) -> "GitBatch":
        self.proc = subprocess.Popen(self.argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, env=self.env)
        return self

    def __exit__(self, *exc) -> None:
        assert self.proc is not None
        self.proc.stdin.close()
        self.proc.stdout.close()
        self.proc.wait()

    def __call__(self, sha: str) -> tuple[str, bytes]:
        if not SHA.fullmatch(sha):
            raise KeyError(sha)
        assert self.proc is not None, "GitBatch is used inside a with block"
        self.proc.stdin.write(sha.encode() + b"\n")
        self.proc.stdin.flush()
        header = self.proc.stdout.readline().split()
        if header == [sha.encode(), b"missing"]:
            raise KeyError(sha)
        if len(header) != 3 or header[0] != sha.encode() or not header[2].isdigit():
            raise PulledError(["git_batch_unreadable"])
        size = int(header[2])
        data = self.proc.stdout.read(size)
        if len(data) != size or self.proc.stdout.read(1) != b"\n":
            raise PulledError(["git_batch_unreadable"])
        return header[1].decode("ascii", "replace"), data
