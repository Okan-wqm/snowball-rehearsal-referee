"""Capture of ``fixtures/git-fetch.json``: real git running ``loop.fetch``'s commands (tests only; needs ``git``
and the network to github.com).

Each case runs ``loop.fetch.argv``'s two commands with ``loop.fetch``'s environment (``loop.gitobj.git_env`` of
``PATH`` and ``HOME`` plus ``SSH_ASKPASS``, then ``GIT_TERMINAL_PROMPT=0``) and records the exit codes and what
git left; ``SSH_ASKPASS`` names a script that, if run, writes a marker file and answers ``x``:

- ``public``: a public commit of github.com (this brain's ``e4dc54a``): the commit and its tree are read back
  with ``loop.gitobj``, ``refs/pulled`` is the commit, ``shallow`` lists it (no history);
- ``unknown_commit``: a commit id the repository does not have;
- ``no_repository``: a repository that does not exist, where GitHub asks for credentials: whether the askpass
  script ran; ``no_repository_prompt_kept``: the same with ``SSH_ASKPASS`` put back after ``git_env`` (why
  ``git_env`` drops it);
- ``file_transport``: a ``file://`` URL of a local repository (``loop.fetch`` refuses it before git; this shows
  the ``-c protocol`` values refuse it too).

The argv is recorded with ``<git_dir>``, ``<url>`` and ``<sha>`` in place; ``test_fetch.RealGit`` checks it is
``loop.fetch.argv``'s, so a change to the commands needs a new capture. Run from ``referee/``:
``python tests/capture_git_fetch.py > tests/fixtures/git-fetch.json``.
"""

import json
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from loop import fetch as F  # noqa: E402
from loop import gitobj as G  # noqa: E402

BRAIN = "https://github.com/Okan-wqm/snowball-rehearsal-brain"
PUBLIC = "e4dc54a40cc668935e6e732976875d8913174b63"
UNKNOWN = "0123456789abcdef0123456789abcdef01234567"
MISSING = "https://github.com/Okan-wqm/no-such-repository-snowball"


def case(tmp: str, name: str, url: str, sha: str, keep_askpass: bool = False) -> dict:
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
    for cmd in F.argv("git", git_dir, url, sha):
        code = subprocess.run(cmd, env=env, stdin=subprocess.DEVNULL, capture_output=True).returncode
        out["exits"].append(code)
        if code:
            break
    out["prompt_script_ran"] = os.path.exists(marker)
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
        doc = {
            "git": subprocess.run(["git", "--version"], capture_output=True, text=True).stdout.strip(),
            "argv": F.argv("git", "<git_dir>", "<url>", "<sha>"),
            "cases": {
                "public": dict(case(tmp, "public", BRAIN, PUBLIC), url=BRAIN, sha=PUBLIC),
                "unknown_commit": dict(case(tmp, "unknown_commit", BRAIN, UNKNOWN), url=BRAIN, sha=UNKNOWN),
                "no_repository": dict(case(tmp, "no_repository", MISSING, PUBLIC), url=MISSING, sha=PUBLIC),
                "no_repository_prompt_kept": dict(case(tmp, "kept", MISSING, PUBLIC, True), url=MISSING, sha=PUBLIC),
                "file_transport": case(tmp, "file_transport", "file://" + local, head),
            },
        }
    json.dump(doc, sys.stdout, indent=1, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
