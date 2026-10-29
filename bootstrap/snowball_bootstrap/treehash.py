"""Tree hashes over git-archive tarballs, and safe extraction of regular files only.

The referee code tree hash is what the operator import compares (`tohum/25a` 1). It covers the
regular files under ``referee/`` at a pinned commit, by relative path and content:
``sha256( "".join(sorted(f"{sha256(content)}  {relpath}\\n")) )``.
"""

from __future__ import annotations

import hashlib
import io
import tarfile
from pathlib import Path, PurePosixPath

# Operator-only names: the import never overwrites them, so the referee code may not carry them.
OPERATOR_NAMES = frozenset({"policy.json", "control.json", "setup", "seats", "vectors", "bootstrap.json"})


class TreeError(ValueError):
    """The archive contains something other than regular files and directories."""


def is_utf8_name(name: str) -> bool:
    """False for a name that is not UTF-8: git and tar keep its bytes as lone surrogates."""
    return not any("\ud800" <= char <= "\udfff" for char in name)


def shown(name: str) -> str:
    """The name as text that canonical JSON and a message can hold (a lone surrogate can be neither)."""
    return name.encode("utf-8", "surrogateescape").decode("utf-8", "replace")


def path_problem(name: str) -> str | None:
    """Why a (UTF-8) path must not reach a file system, a prompt or a log line; None when it is fine.

    Control characters forge lines in the rival's request and in logs (E03); a `.git` component writes
    into a repository's own metadata, hooks included, when the operator imports an accepted tree (E04);
    `:` and backslashes mean something else on Windows, where the operator imports.
    """
    if any(ord(c) < 0x20 or ord(c) == 0x7F for c in name):
        return "control character"
    if "\\" in name or ":" in name:
        return "backslash or colon"
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts:
        return "absolute or parent path"
    if any(part.lower() == ".git" for part in path.parts):
        return ".git component"
    return None


def _clean(name: str) -> PurePosixPath:
    if not is_utf8_name(name):
        raise TreeError(f"path in archive is not valid UTF-8: {shown(name)}")
    problem = path_problem(name)
    if problem:
        raise TreeError(f"unsafe path in archive ({problem}): {name!r}")
    return PurePosixPath(name)


def iter_files(tar_bytes: bytes):
    """Yield (path, content, executable) for regular files; refuse links and special files."""
    try:
        with tarfile.open(fileobj=io.BytesIO(tar_bytes), mode="r:") as tar:
            for member in tar.getmembers():
                if member.name == "pax_global_header" or member.type == tarfile.XGLTYPE:
                    continue
                path = _clean(member.name)
                if member.isdir():
                    continue
                if not member.isfile():
                    raise TreeError(f"not a regular file: {member.name}")
                handle = tar.extractfile(member)
                assert handle is not None
                yield path, handle.read(), bool(member.mode & 0o111)
    except tarfile.TarError as exc:  # a corrupt or truncated archive is the same kind of refusal
        raise TreeError(f"not a readable archive: {type(exc).__name__}") from exc


def tree_hash(tar_bytes: bytes, prefix: str, forbid_operator_names: bool = True) -> str:
    """Hash of the regular files under ``prefix`` in a git-archive tarball."""
    pre = PurePosixPath(prefix)
    lines = []
    for path, content, _exec in iter_files(tar_bytes):
        try:
            rel = path.relative_to(pre)
        except ValueError:
            continue
        if forbid_operator_names and rel.parts and rel.parts[0] in OPERATOR_NAMES:
            raise TreeError(f"{prefix}/{rel.parts[0]} is an operator-only name")
        lines.append(f"{hashlib.sha256(content).hexdigest()}  {rel.as_posix()}\n")
    if not lines:
        raise TreeError(f"no files under {prefix}/")
    return hashlib.sha256("".join(sorted(lines)).encode("utf-8")).hexdigest()


def extract(tar_bytes: bytes, dest: Path, max_bytes: int, prefix: str = "") -> int:
    """Extract regular files (optionally only under ``prefix``) into ``dest``; return total bytes."""
    total = 0
    pre = PurePosixPath(prefix) if prefix else None
    dest.mkdir(parents=True, exist_ok=True)
    for path, content, executable in iter_files(tar_bytes):
        if pre is not None:
            try:
                path = path.relative_to(pre)
            except ValueError:
                continue
        total += len(content)
        if total > max_bytes:
            raise TreeError(f"tree larger than {max_bytes} bytes")
        target = dest.joinpath(*path.parts)
        if not target.resolve().is_relative_to(dest.resolve()):
            raise TreeError(f"path leaves the destination: {path}")
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
            target.chmod(0o755 if executable else 0o644)
        except OSError as exc:  # e.g. a name longer than the file system allows
            raise TreeError(f"cannot write {path}: {exc.strerror or type(exc).__name__}") from exc
    return total
