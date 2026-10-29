"""Operator import at the Stage 0 exit (`tohum/25a` 1-2). Run on the operator's machine.

It never pushes. It verifies the signed result, rebuilds the referee code tree from the pinned
brain commit, compares hashes, and copies files into local checkouts of the referee repository
and the toy target. The operator reviews ``git status`` and pushes.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from . import gitio
from .treehash import OPERATOR_NAMES, extract, tree_hash

OIDC_ISSUER = "https://token.actions.githubusercontent.com"
# Operator files and directories in the referee repository that the import never touches.
KEEP_TOP = OPERATOR_NAMES | {".git"}


class ImportErrorStop(RuntimeError):
    """The import must not proceed; the message says why."""


def verify_signature(result: Path, bundle: Path, identity: str, sigstore_python: str) -> None:
    proc = subprocess.run([sigstore_python, "-m", "sigstore", "verify", "identity", "--bundle", str(bundle),
                           "--cert-identity", identity, "--cert-oidc-issuer", OIDC_ISSUER, str(result)],
                          capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise ImportErrorStop(f"signature verification failed: {proc.stderr.strip()[:500]}")


def run_import(result_path: Path, bundle_path: Path, identity: str, sigstore_python: str,
               brain_repo: Path, referee_dir: Path, toy_dir: Path | None) -> dict:
    verify_signature(result_path, bundle_path, identity, sigstore_python)
    result = json.loads(result_path.read_text(encoding="utf-8"))
    exit_block = result.get("exit") or {}
    if result.get("verdict") != "accepted" or not exit_block.get("transferable"):
        raise ImportErrorStop("the signed result does not mark this commit transferable")
    sha = exit_block["brain_sha"]
    expected = exit_block["referee_tree_sha256"]
    if not gitio.has_commit(brain_repo, sha):
        raise ImportErrorStop(f"brain commit {sha} is not in {brain_repo}; fetch it first")
    tar_bytes = gitio.archive(brain_repo, sha)
    actual = tree_hash(tar_bytes, "referee")
    if actual != expected:
        raise ImportErrorStop(f"referee tree hash {actual} differs from the signed {expected}")

    for child in referee_dir.iterdir():
        if child.name not in KEEP_TOP:
            if child.is_dir() and not child.is_symlink():
                shutil.rmtree(child)
            else:
                child.unlink()
    # The wipe above also retires the bootstrap (its workflow and package): only the imported
    # referee code and the operator files remain.
    copied = extract(tar_bytes, referee_dir, max_bytes=200_000_000, prefix="referee")

    toy_bytes = 0
    if toy_dir is not None:
        for child in toy_dir.iterdir():
            if child.name == ".git":
                continue
            if child.is_dir() and not child.is_symlink():
                shutil.rmtree(child)
            else:
                child.unlink()
        toy_bytes = extract(tar_bytes, toy_dir, max_bytes=50_000_000, prefix="tests/fixtures/toy-repo")
    log = {"brain_sha": sha, "referee_tree_sha256": actual, "referee_bytes": copied, "toy_bytes": toy_bytes,
           "result_head": result.get("head")}
    setup = referee_dir / "setup"
    setup.mkdir(exist_ok=True)
    with (setup / "imports.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(log, sort_keys=True) + "\n")
    return log
