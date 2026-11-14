"""Capture of ``fixtures/git-parents.json``: real git's commit objects and their parents (tests only; needs ``git``).

In a new repository: ``root`` (no parent), ``child`` (one), ``merge`` (two, ``git merge --no-ff`` of a side
branch) and ``message`` (one parent, its message holding ``parent <40 hex>`` lines after the header, which are no
parents). For each: the raw object (``git cat-file commit``, hex) and git's own answer of its parents (``git
rev-list --parents -n 1``). ``test_gitobj.Parents`` checks ``loop.gitobj.parents`` against git's answer. Run from
``referee/``: ``python tests/capture_git_parents.py > tests/fixtures/git-parents.json``.
"""

import json
import os
import subprocess
import tempfile

ENV = {"PATH": os.environ.get("PATH", ""), "HOME": "/nonexistent", "GIT_CONFIG_NOSYSTEM": "1",
       "GIT_AUTHOR_NAME": "A", "GIT_AUTHOR_EMAIL": "a@example.org", "GIT_AUTHOR_DATE": "1700000000 +0000",
       "GIT_COMMITTER_NAME": "A", "GIT_COMMITTER_EMAIL": "a@example.org", "GIT_COMMITTER_DATE": "1700000000 +0000"}


def git(cwd: str, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, env=ENV, check=True, capture_output=True).stdout.decode().strip()


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        git(tmp, "init", "--quiet", "-b", "main")
        names = {}

        def commit(name: str, message: str) -> None:
            with open(os.path.join(tmp, "%s.txt" % name), "w") as fh:
                fh.write(name + "\n")
            git(tmp, "add", "-A")
            git(tmp, "commit", "--quiet", "-m", message)
            names[name] = git(tmp, "rev-parse", "HEAD")

        commit("root", "root")
        commit("child", "child")
        git(tmp, "checkout", "--quiet", "-b", "side", names["root"])
        commit("side", "side")
        git(tmp, "checkout", "--quiet", "main")
        git(tmp, "merge", "--quiet", "--no-ff", "-m", "merge", "side")
        names["merge"] = git(tmp, "rev-parse", "HEAD")
        commit("message", "message\n\nparent %s\nparent %s" % ("a" * 40, names["root"]))
        out = {"git": git(tmp, "--version"), "commits": {}}
        for name in ("root", "child", "merge", "message"):
            sha = names[name]
            raw = subprocess.run(["git", "cat-file", "commit", sha], cwd=tmp, env=ENV, check=True,
                                 capture_output=True).stdout
            out["commits"][name] = {"sha": sha, "object": raw.hex(),
                                    "parents": git(tmp, "rev-list", "--parents", "-n", "1", sha).split()[1:]}
    print(json.dumps(out, indent=1, sort_keys=True))


if __name__ == "__main__":
    main()
