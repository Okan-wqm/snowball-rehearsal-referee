"""A repository's branch heads, and one commit fetched by its id into a new bare git directory (``çek``, D1; stage 0).

Rules: tohum/08 item 1 (``çek`` is credential-less: it fetches the brain's and the target's requested SHAs and
makes their trees an artifact by content identity; it runs no code), asama-0/01 D1. A private target's reader App
(tohum/08) is not stage 0's: both stage 0 targets are public.

``fetch(git_dir, url, sha)`` checks its inputs first and starts no process when one fails (``PulledError``, every
reason that holds listed):

- ``fetch_sha_unsafe``: ``sha`` is not 40 lowercase hex (``loop.gitobj.SHA``);
- ``fetch_url_unsafe``: ``url`` is not ``https://<host>[:<port>]/<segment>[/<segment>...]`` with a host of
  letters, digits, ``-`` and ``.`` labels and segments of letters, digits, ``_``, ``.`` and ``-`` other than
  ``.`` and ``..``: so no other transport (``file://``, ``ssh``, ``ext::``), no user name or password in the URL,
  no query, nothing git could read as an option;
- ``fetch_dir_unsafe``: ``git_dir`` is not an absolute path, already exists, or its parent is not a directory.

Then two git processes, each with ``loop.gitobj.git_env`` plus ``GIT_TERMINAL_PROMPT=0``, stdin and stdout
``/dev/null``. The configuration git reads is then only the new repository's own (``git init``'s) and the ``-c``
values below, so no credential helper is configured; with no ``GIT_ASKPASS``, ``SSH_ASKPASS`` or ``core.askPass``
and no terminal prompt, nothing is asked for a password:

1. ``git init --bare --quiet <git_dir>``;
2. ``git -c protocol.allow=never -c protocol.https.allow=always -c gc.auto=0 -c maintenance.auto=false
   --git-dir=<git_dir> fetch --quiet --no-tags --no-recurse-submodules --depth=1 --no-write-fetch-head --
   <url> <sha>:refs/pulled``: only https, no tags, no submodule, the one commit with its whole tree and no
   history, kept by the ref ``refs/pulled``; no garbage collection after it.

A process that cannot start is ``git_unavailable``; a non-zero exit is ``fetch_failed:init:<code>`` or
``fetch_failed:fetch:<code>`` (git's own message goes to stderr). Last, the commit is read back through
``loop.gitobj.GitBatch`` with ``loop.gitobj.read`` (its id recomputed); its reasons (``object_missing:<sha>``,
``object_mismatch:<sha>``, ``git_batch_unreadable``) are this step's. On any failure after the inputs are
accepted, ``git_dir`` is removed. The tree under the commit is not read here: ``loop.gitobj.tree_tar`` and
``lookup`` read it and refuse what is missing.

``heads(git_dir, url, refs)`` reads the commit ids of the branch refs ``refs`` (e.g. the target's
``refs/heads/brain/state``) without fetching anything. Its inputs are checked first, as ``fetch``'s
(``fetch_url_unsafe``, ``fetch_dir_unsafe``, and ``heads_ref_unsafe``: ``refs`` is not a non-empty list of distinct
``refs/heads/<name>`` with ``<name>`` slash-separated components of letters, digits, ``_``, ``.`` and ``-``, none
``.``, ``..`` or starting with ``.``). Then ``git init --bare --quiet <git_dir>`` and ``git -c protocol.allow=never
-c protocol.https.allow=always --git-dir=<git_dir> ls-remote --heads -- <url> <ref>...``, environment and stdin
as above, stdout read. The ``--git-dir`` matters: without it git reads the configuration of a repository it finds
around the working directory (a ``url.<base>.insteadOf`` there sends the read to another repository; real git
2.47.3 does, ``tests/fixtures/git-heads.json``). ``git_dir`` is removed afterwards whatever happened. git matches
a pattern against the end of a ref name, so ``refs/heads/x/refs/heads/brain/state`` is listed too; only the exact
names count. Every line of the answer must be 40 lowercase hex, a tab and a name without spaces or control
characters; a requested ref listed twice, or any other line, is ``heads_unreadable``; a non-zero exit is
``heads_failed:init:<code>`` or ``heads_failed:ls-remote:<code>``, a git that cannot start ``git_unavailable``. The answer maps each requested ref to its id, ``None`` for a ref the
repository does not have.

Out of scope, stated: which commit and which URL (the caller's: the bootstrap result's accepted SHA, the target's
heads), a time limit (the job's ``timeout-minutes`` bounds a stalled fetch), what the server or a redirect does
beyond these options (git's), and SHA-256 repositories.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from typing import Any

from loop import gitobj as G
from loop.pulled import PulledError

_LABEL = r"[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?"
URL = re.compile(r"https://%s(?:\.%s)*(?::[0-9]{1,5})?(?:/(?!\.{1,2}(?:/|$))[A-Za-z0-9_.-]+)+" % (_LABEL, _LABEL))
REF = "refs/pulled"
HEAD_REF = re.compile(r"refs/heads/(?!\.)[A-Za-z0-9_.-]+(?:/(?!\.)[A-Za-z0-9_.-]+)*")
_LISTED = re.compile(rb"([0-9a-f]{40})\t([^\x00-\x20\x7f]+)")
CONFIG = ("protocol.allow=never", "protocol.https.allow=always", "gc.auto=0", "maintenance.auto=false")


def _checks(git_dir: str, url: str) -> list[str]:
    reasons = []
    if not (isinstance(url, str) and URL.fullmatch(url)):
        reasons.append("fetch_url_unsafe")
    if not (isinstance(git_dir, str) and os.path.isabs(git_dir) and not os.path.lexists(git_dir)
            and os.path.isdir(os.path.dirname(git_dir.rstrip("/")) or "/")):
        reasons.append("fetch_dir_unsafe")
    return reasons


def argv(git: str, git_dir: str, url: str, sha: str) -> list[list[str]]:
    """The two commands ``fetch`` runs, in order."""
    config = [a for c in CONFIG for a in ("-c", c)]
    return [
        [git, "init", "--bare", "--quiet", git_dir],
        [git, *config, "--git-dir=%s" % git_dir, "fetch", "--quiet", "--no-tags", "--no-recurse-submodules",
         "--depth=1", "--no-write-fetch-head", "--", url, "%s:%s" % (sha, REF)],
    ]


def _run(cmd: list[str], env: dict[str, str], stdout: Any = subprocess.DEVNULL) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(cmd, stdin=subprocess.DEVNULL, stdout=stdout, env=env)
    except OSError:
        raise PulledError(["git_unavailable"]) from None


def heads_argv(git: str, git_dir: str, url: str, refs: list[str]) -> list[list[str]]:
    """The two commands ``heads`` runs, in order."""
    config = [a for c in CONFIG[:2] for a in ("-c", c)]
    return [
        [git, "init", "--bare", "--quiet", git_dir],
        [git, *config, "--git-dir=%s" % git_dir, "ls-remote", "--heads", "--", url, *refs],
    ]


def parse_heads(out: bytes, refs: list[str]) -> dict[str, str | None]:
    """``git ls-remote``'s answer -> each of ``refs`` to its id or ``None``, by the rules above."""
    found: dict[str, str | None] = dict.fromkeys(refs)
    lines = out.split(b"\n")
    if lines[-1] == b"":
        lines.pop()
    for line in lines:
        m = _LISTED.fullmatch(line)
        if not m:
            raise PulledError(["heads_unreadable"])
        ref = m.group(2).decode("utf-8", "replace")
        if ref in found:
            if found[ref] is not None:
                raise PulledError(["heads_unreadable"])
            found[ref] = m.group(1).decode()
    return found


def heads(git_dir: str, url: str, refs: list[str], git: str = "git",
          environ: dict[str, str] | None = None) -> dict[str, str | None]:
    """The ids of the branch refs ``refs`` of ``url``, read through the new bare git directory ``git_dir``."""
    reasons = _checks(git_dir, url)
    if not (isinstance(refs, list) and refs and len(set(refs)) == len(refs)
            and all(isinstance(r, str) and HEAD_REF.fullmatch(r) for r in refs)):
        reasons.append("heads_ref_unsafe")
    if reasons:
        raise PulledError(reasons)
    env = dict(G.git_env(environ), GIT_TERMINAL_PROMPT="0")
    try:
        init, listing = heads_argv(git, git_dir, url, refs)
        code = _run(init, env).returncode
        if code != 0:
            raise PulledError(["heads_failed:init:%d" % code])
        done = _run(listing, env, subprocess.PIPE)
        if done.returncode != 0:
            raise PulledError(["heads_failed:ls-remote:%d" % done.returncode])
        return parse_heads(done.stdout, refs)
    finally:
        shutil.rmtree(git_dir, ignore_errors=True)


def fetch(git_dir: str, url: str, sha: str, git: str = "git", environ: dict[str, str] | None = None) -> None:
    """Fill the new bare git directory ``git_dir`` with commit ``sha`` of ``url`` by the rules above."""
    reasons = [] if isinstance(sha, str) and G.SHA.fullmatch(sha) else ["fetch_sha_unsafe"]
    reasons += _checks(git_dir, url)
    if reasons:
        raise PulledError(reasons)
    env = dict(G.git_env(environ), GIT_TERMINAL_PROMPT="0")
    try:
        for step, cmd in zip(("init", "fetch"), argv(git, git_dir, url, sha)):
            code = _run(cmd, env).returncode
            if code != 0:
                raise PulledError(["fetch_failed:%s:%d" % (step, code)])
        with G.GitBatch(git_dir, git, environ) as source:
            G.read(source, sha, "commit")
    except BaseException:
        shutil.rmtree(git_dir, ignore_errors=True)
        raise
