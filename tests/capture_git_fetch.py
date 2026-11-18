"""Capture of ``fixtures/git-fetch.json``: real git running ``loop.fetch``'s commands (tests only; needs ``git``
and the network to github.com).

Each case runs ``loop.fetch.argv``'s two commands with ``loop.fetch``'s environment (``loop.gitobj.git_env`` of
``PATH`` and ``HOME`` plus ``SSH_ASKPASS``, then ``GIT_TERMINAL_PROMPT=0``) and records the exit codes and what
git left; ``SSH_ASKPASS`` names a script that, if run, writes a marker file and answers ``x``:

- ``public``: a public commit of github.com (this brain's ``e4dc54a``): the commit and its tree are read back
  with ``loop.gitobj``, ``refs/pulled`` is the commit, ``shallow`` lists it (no history);
- ``history``: ``loop.fetch.argv(..., history=True)`` on a later public commit (``c801314``, whose ancestor
  ``6cd1be7`` is two commits back): the exits, that no ``shallow`` file is left, the ``promisor`` value git wrote
  for the URL in the directory's config, and ``loop.accepted.check_ancestor``'s answers on what was fetched:
  ``ancestor`` (``6cd1be7`` from ``c801314``: reasons, empty when it holds) and ``not_ancestor`` (``c801314``
  from ``6cd1be7``, a walk to the history's roots: its reasons and ``walked``, the commits it read); and
  on ``public``'s depth-1 directory, ``shallow_parent`` (its commit's own parent, found on the commit's
  ``parent`` line without another read) and ``shallow_walk`` (a commit further back: the parent is not there);
- ``unknown_commit``: a commit id the repository does not have;
- ``no_repository``: a repository that does not exist, where GitHub asks for credentials: whether the askpass
  script ran; ``no_repository_prompt_kept``: the same with ``SSH_ASKPASS`` put back after ``git_env`` (why
  ``git_env`` drops it);
- ``file_transport``: a ``file://`` URL of a local repository (``loop.fetch`` refuses it before git; this shows
  the ``-c protocol`` values refuse it too).

The argv is recorded with ``<git_dir>``, ``<url>`` and ``<sha>`` in place (``history_argv``: the history form);
``test_fetch.RealGit`` checks they are ``loop.fetch.argv``'s, so a change to the commands needs a new capture. Run from ``referee/``:
``python tests/capture_git_fetch.py > tests/fixtures/git-fetch.json``.
"""

import json
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from loop import accepted as A  # noqa: E402
from loop import fetch as F  # noqa: E402
from loop import gitobj as G  # noqa: E402

BRAIN = "https://github.com/Okan-wqm/snowball-rehearsal-brain"
PUBLIC = "e4dc54a40cc668935e6e732976875d8913174b63"
UNKNOWN = "0123456789abcdef0123456789abcdef01234567"
MISSING = "https://github.com/Okan-wqm/no-such-repository-snowball"
LATER = "c801314b371a2f50f9e6efd638342c2eb4d29801"
ANCESTOR = "6cd1be72e04b41e0ed5033f2412d91eec87ab0d6"  # LATER's parent's parent


def asked(source, accepted: str, transfer: str) -> dict:
    """``check_ancestor``'s reasons (none when it holds) and the commits it read."""
    read: list[str] = []

    def counting(sha):
        read.append(sha)
        return source(sha)
    try:
        A.check_ancestor(counting, accepted, transfer)
    except A.StateError as exc:
        return {"reasons": exc.reasons, "walked": len(read)}
    return {"reasons": [], "walked": len(read)}


def walks(history_dir: str, shallow_dir: str, env: dict) -> dict:
    """``history``'s own fields, read from its directory and from ``public``'s depth-1 one."""
    out: dict = {"shallow_file": os.path.exists(os.path.join(history_dir, "shallow"))}
    out["promisor"] = subprocess.run(["git", "--git-dir=%s" % history_dir, "config", "--get",
                                      "remote.%s.promisor" % BRAIN], env=env, capture_output=True,
                                     text=True).stdout.strip()
    with G.GitBatch(history_dir, environ=env) as src:
        out["ancestor"] = asked(src, LATER, ANCESTOR)
        out["not_ancestor"] = asked(src, ANCESTOR, LATER)
    with G.GitBatch(shallow_dir, environ=env) as src:
        parent = G.parents(src, PUBLIC)[0]
        out["shallow_parent"] = asked(src, PUBLIC, parent)  # named by the one commit that is there
        out["shallow_walk"] = asked(src, PUBLIC, UNKNOWN)
        out["shallow_walk"]["reasons"] = [r.replace(parent, "<parent>") for r in out["shallow_walk"]["reasons"]]
    return out


def case(tmp: str, name: str, url: str, sha: str, keep_askpass: bool = False, history: bool = False) -> dict:
    marker = os.path.join(tmp, "%s.prompted" % name)
    ask = os.path.join(tmp, "prompt.sh")  # the SSH_ASKPASS program
    with open(ask, "w") as fh:
        fh.write('#!/bin/sh\necho "$1" >> "%s"\necho x\n' % marker)
    os.chmod(ask, 0o755)
    env = dict(G.git_env({"PATH": "/usr/bin:/bin", "HOME": tmp, "SSH_ASKPASS": ask}), GIT_TERMINAL_PROMPT="0")
    if keep_askpass:
        env["SSH_ASKPASS"] = ask
    git_dir = os.path.join(tmp, "%s.git" % name)
    out: dict = {"exits": []}
    for cmd in F.argv("git", git_dir, url, sha, history):
        code = subprocess.run(cmd, env=env, stdin=subprocess.DEVNULL, capture_output=True).returncode
        out["exits"].append(code)
        if code:
            break
    out["prompt_script_ran"] = os.path.exists(marker)
    out["git_dir"], out["env"] = git_dir, env
    if history:
        return out
    if out["exits"] == [0, 0]:
        with G.GitBatch(git_dir, environ=env) as src:
            out["entries"] = len(G.entries(src, sha))
        out["ref"] = subprocess.run(["git", "--git-dir=%s" % git_dir, "rev-parse", F.REF], env=env,
                                    capture_output=True, text=True).stdout.strip()
        with open(os.path.join(git_dir, "shallow")) as fh:
            out["shallow"] = fh.read().split()
    return out


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        local = os.path.join(tmp, "local")
        env = G.git_env({"PATH": "/usr/bin:/bin", "HOME": tmp})
        subprocess.run(["git", "init", "-q", local], check=True, env=env)
        subprocess.run(["git", "-C", local, "-c", "user.name=A", "-c", "user.email=a@example.org", "commit", "-q",
                        "--allow-empty", "-m", "m"], check=True, env=env)
        head = subprocess.run(["git", "-C", local, "rev-parse", "HEAD"], env=env, capture_output=True,
                              text=True).stdout.strip()
        public = case(tmp, "public", BRAIN, PUBLIC)
        history = case(tmp, "history", BRAIN, LATER, history=True)
        history.update(walks(history["git_dir"], public["git_dir"], history["env"]))
        doc = {
            "git": subprocess.run(["git", "--version"], capture_output=True, text=True).stdout.strip(),
            "argv": F.argv("git", "<git_dir>", "<url>", "<sha>"),
            "history_argv": F.argv("git", "<git_dir>", "<url>", "<sha>", history=True),
            "cases": {
                "public": dict(public, url=BRAIN, sha=PUBLIC),
                "history": dict(history, url=BRAIN, sha=LATER, ancestor_sha=ANCESTOR),
                "unknown_commit": dict(case(tmp, "unknown_commit", BRAIN, UNKNOWN), url=BRAIN, sha=UNKNOWN),
                "no_repository": dict(case(tmp, "no_repository", MISSING, PUBLIC), url=MISSING, sha=PUBLIC),
                "no_repository_prompt_kept": dict(case(tmp, "kept", MISSING, PUBLIC, True), url=MISSING, sha=PUBLIC),
                "file_transport": case(tmp, "file_transport", "file://" + local, head),
            },
        }
    for one in doc["cases"].values():
        one.pop("git_dir", None)  # a temporary path
        one.pop("env", None)
    json.dump(doc, sys.stdout, indent=1, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
