"""Fixture trees for tests 19 and 47: written into a fresh temporary directory per test."""

from __future__ import annotations

import json
import os
import tempfile

LOCK_OK = {"lockfileVersion": 3, "packages": {
    "": {"name": "toy"},
    "node_modules/left-pad": {"version": "1.3.0", "resolved": "https://registry.npmjs.org/left-pad/-/left-pad-1.3.0.tgz",
                              "integrity": "sha512-" + "A" * 86 + "=="},
    "node_modules/local": {"resolved": "packages/local", "link": True},
    "node_modules/left-pad/node_modules/inner": {"version": "1.0.0", "inBundle": True},
}}


def writable_base(prefix: str) -> str:
    for cand in (os.environ.get("TMPDIR"), "/tmp", "/dev/shm"):
        if cand and os.path.isdir(cand):
            try:
                return tempfile.mkdtemp(prefix=prefix, dir=cand)
            except OSError:
                continue
    raise AssertionError("no writable temporary directory: the profile tests cannot run, so they fail")


def write_tree(root: str, files: dict) -> str:
    """``files``: relative path -> str | bytes | dict/list (JSON) | ("symlink", target)."""
    for rel, content in files.items():
        full = os.path.join(root, rel)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        if isinstance(content, tuple) and content[0] == "symlink":
            os.symlink(content[1], full)
        elif isinstance(content, (dict, list)):
            with open(full, "w", encoding="utf-8") as fh:
                json.dump(content, fh)
        else:
            with open(full, "wb") as fh:
                fh.write(content.encode() if isinstance(content, str) else content)
    return root


def write_tar(path: str, files, dirs=(), extra=()) -> str:
    """A gzip tar at ``path``: ``files`` (names, or name -> bytes) as regular members, ``dirs`` as
    directory members, ``extra`` as ready ``TarInfo`` members (symlinks and such)."""
    import io
    import tarfile
    items = files.items() if isinstance(files, dict) else ((f, b"x") for f in files)
    with tarfile.open(path, "w:gz") as tar:
        for name in dirs:
            info = tarfile.TarInfo(name)
            info.type = tarfile.DIRTYPE
            tar.addfile(info)
        for name, data in items:
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
        for info in extra:
            tar.addfile(info)
    return path
