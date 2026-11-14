"""Capture of ``fixtures/git-heads.json``: real git running ``loop.fetch.heads``'s commands (tests only; needs ``git``
and the network to github.com).

Each case runs ``loop.fetch.heads_argv``'s two commands with ``loop.fetch``'s environment (``loop.gitobj.git_env``
of ``PATH`` and ``HOME`` plus ``SSH_ASKPASS``, then ``GIT_TERMINAL_PROMPT=0``) and records the exit codes, the
answer's bytes and whether the ``SSH_ASKPASS`` script (it writes a marker file and answers ``x``) ran:

- ``public``: a public repository (``PUBLIC``), asking for its ``main`` and a ``brain/state`` it does not have;
- ``redirect``: the same commands with the working directory inside a repository whose configuration says
  ``url.<BRAIN>.insteadOf <PUBLIC>``; and ``redirect_without_git_dir``, the listing without ``--git-dir`` in the
  same place: which repository answered (why ``heads`` passes ``--git-dir``);
- ``no_repository``: a repository that does not exist.

The argv is recorded with ``<git_dir>``, ``<url>`` and the refs in place; ``test_fetch.RealHeads`` checks it is
``loop.fetch.heads_argv``'s, so a change to the commands needs a new capture. Run from ``referee/``:
``python tests/capture_git_heads.py > tests/fixtures/git-heads.json``.
"""

import json
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from loop import fetch as F  # noqa: E402
from loop import gitobj as G  # noqa: E402

PUBLIC = "https://github.com/sigstore/gh-action-sigstore-python"  # a repository that is no target of this brain
BRAIN = "https://github.com/Okan-wqm/snowball-rehearsal-brain"
MISSING = "https://github.com/Okan-wqm/no-such-repository-snowball"
REFS = ["refs/heads/main", "refs/heads/brain/state"]


def case(tmp: str, name: str, url: str, cwd: str | None = None, git_dir: bool = True) -> dict:
    marker = os.path.join(tmp, "%s.prompted" % name)
    ask = os.path.join(tmp, "prompt.sh")
    with open(ask, "w") as fh:
        fh.write('#!/bin/sh\necho "$1" >> "%s"\necho x\n' % marker)
    os.chmod(ask, 0o755)
    env = dict(G.git_env({"PATH": "/usr/bin:/bin", "HOME": tmp, "SSH_ASKPASS": ask}), GIT_TERMINAL_PROMPT="0")
    path = os.path.join(tmp, "%s.git" % name)
    init, listing = F.heads_argv("git", path, url, REFS)
    if not git_dir:
        listing = [a for a in listing if not a.startswith("--git-dir=")]
    out: dict = {"exits": [], "url": url}
    for cmd in (init, listing):
        done = subprocess.run(cmd, env=env, stdin=subprocess.DEVNULL, capture_output=True, cwd=cwd or tmp)
        out["exits"].append(done.returncode)
        if done.returncode:
            break
        out["stdout"] = done.stdout.decode()
    out["prompt_script_ran"] = os.path.exists(marker)
    return out


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        local = os.path.join(tmp, "around")
        env = G.git_env({"PATH": "/usr/bin:/bin", "HOME": tmp})
        subprocess.run(["git", "init", "-q", local], check=True, env=env)
        subprocess.run(["git", "-C", local, "config", "url.%s.insteadOf" % BRAIN, PUBLIC], check=True, env=env)
        doc = {
            "git": subprocess.run(["git", "--version"], capture_output=True, text=True).stdout.strip(),
            "argv": F.heads_argv("git", "<git_dir>", "<url>", ["<ref>"]),
            "refs": REFS,
            "brain_main": case(tmp, "brain", BRAIN)["stdout"],
            "cases": {
                "public": case(tmp, "public", PUBLIC),
                "redirect": case(tmp, "redirect", PUBLIC, cwd=local),
                "redirect_without_git_dir": case(tmp, "redirect_bare", PUBLIC, cwd=local, git_dir=False),
                "no_repository": case(tmp, "no_repository", MISSING),
            },
        }
    json.dump(doc, sys.stdout, indent=1, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
