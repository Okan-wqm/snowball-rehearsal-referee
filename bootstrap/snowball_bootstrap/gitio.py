"""Git operations on the untrusted brain repository.

Hooks, filters and attributes in the brain repository must not change what the referee sees, so
the archive is built from the tree's blobs directly: ``export-ignore`` and ``export-subst`` have
no effect (`asama-0/06`).
"""

from __future__ import annotations

import io
import os
import subprocess
import tarfile
from pathlib import Path

from .treehash import shown

SAFE_CONFIG = (
    "-c", "core.hooksPath=/dev/null",
    "-c", "core.fsmonitor=false",
    "-c", "protocol.file.allow=user",
    "-c", "advice.detachedHead=false",
)
SPECIAL_MODES = {"120000": "symlink", "160000": "submodule"}


class GitError(RuntimeError):
    pass


def git(repo: Path, *args: str, stdin: bytes | None = None) -> bytes:
    full_env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    full_env.update({"GIT_TERMINAL_PROMPT": "0", "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null"})
    proc = subprocess.run(["git", *SAFE_CONFIG, "-C", str(repo), *args], input=stdin,
                          capture_output=True, env=full_env, check=False)
    if proc.returncode != 0:
        raise GitError(f"git {args[0]} failed: {proc.stderr.decode('utf-8', 'replace')[:500]}")
    return proc.stdout


def fetch(dest: Path, remote: str, branch: str, base_sha: str) -> str:
    """Fetch ``branch`` and make sure ``base_sha`` is present. Return the branch head SHA."""
    dest.mkdir(parents=True, exist_ok=True)
    if not (dest / "HEAD").exists():
        git(dest, "init", "--bare", "--quiet")
    git(dest, "fetch", "--quiet", "--no-tags", remote, f"+refs/heads/{branch}:refs/remotes/brain/{branch}")
    head = git(dest, "rev-parse", f"refs/remotes/brain/{branch}^{{commit}}").decode().strip()
    if not has_commit(dest, base_sha):
        try:
            git(dest, "fetch", "--quiet", "--no-tags", remote, base_sha)
        except GitError:
            pass
    return head


def remote_head(remote: str, branch: str) -> str:
    """The branch head on the remote, read with ``ls-remote`` (no objects are fetched)."""
    out = git(Path("."), "ls-remote", "--heads", remote, f"refs/heads/{branch}").decode()
    lines = [line.split("\t") for line in out.splitlines() if line.strip()]
    if len(lines) != 1 or lines[0][1] != f"refs/heads/{branch}":
        raise GitError(f"branch {branch!r} not found on the brain remote")
    return lines[0][0]


def has_commit(repo: Path, sha: str) -> bool:
    try:
        git(repo, "cat-file", "-e", f"{sha}^{{commit}}")
        return True
    except GitError:
        return False


def is_ancestor(repo: Path, base: str, head: str) -> bool:
    proc = subprocess.run(["git", *SAFE_CONFIG, "-C", str(repo), "merge-base", "--is-ancestor", base, head],
                          capture_output=True, check=False)
    return proc.returncode == 0


def changed_paths(repo: Path, base: str, head: str) -> list[str]:
    out = git(repo, "diff", "--name-only", "-z", "--no-renames", base, head)
    return sorted(p for p in out.decode("utf-8", "surrogateescape").split("\0") if p)


def diff_text(repo: Path, base: str, head: str, exclude: tuple[str, ...] = ()) -> str:
    """The full diff, without any file whose name is in ``exclude``, in any directory."""
    pathspec = ["--", *(f":(exclude,glob)**/{name}" for name in exclude)] if exclude else []
    out = git(repo, "diff", "--no-color", "--no-ext-diff", "--no-textconv", "--no-renames", "--binary", base, head,
              *pathspec)
    return out.decode("utf-8", "replace")


def _entries(repo: Path, head: str) -> list[tuple[str, str, str]]:
    out = git(repo, "ls-tree", "-r", "-z", "--full-tree", head)
    entries = []
    for record in out.split(b"\0"):
        if not record:
            continue
        meta, path = record.split(b"\t", 1)
        mode, _kind, sha = meta.decode().split()
        entries.append((mode, sha, path.decode("utf-8", "surrogateescape")))
    return entries


def special_entries(repo: Path, head: str) -> list[str]:
    """Paths that are not regular files (symlinks, submodules)."""
    return sorted(f"{SPECIAL_MODES[m]}:{shown(p)}" for m, _s, p in _entries(repo, head) if m in SPECIAL_MODES)


def tree_paths(repo: Path, head: str) -> list[str]:
    """Every path in the tree at ``head``, as git stores it (a name that is not UTF-8 keeps lone surrogates)."""
    return [p for _m, _s, p in _entries(repo, head)]


def archive(repo: Path, head: str) -> bytes:
    """Deterministic tar of the regular files at ``head``, read blob by blob."""
    entries = [(m, s, p) for m, s, p in _entries(repo, head) if m in ("100644", "100755")]
    batch = "".join(f"{s}\n" for _m, s, _p in entries).encode()
    out = git(repo, "cat-file", "--batch", stdin=batch)
    buf = io.BytesIO()
    pos = 0
    with tarfile.open(fileobj=buf, mode="w:", format=tarfile.PAX_FORMAT) as tar:
        for mode, sha, path in entries:
            header_end = out.index(b"\n", pos)
            obj_sha, _type, size = out[pos:header_end].decode().split()
            if obj_sha != sha:
                raise GitError("cat-file returned objects out of order")
            start = header_end + 1
            content = out[start:start + int(size)]
            pos = start + int(size) + 1
            info = tarfile.TarInfo(path)
            info.size = len(content)
            info.mode = 0o755 if mode == "100755" else 0o644
            info.mtime = 0
            tar.addfile(info, io.BytesIO(content))
    return buf.getvalue()
