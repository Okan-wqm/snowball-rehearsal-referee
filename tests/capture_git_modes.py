"""Capture of ``fixtures/git-modes.json``: how real git reads a tree entry's mode (tests only; needs ``git``).

For each mode string below, a one-entry tree ``<mode> f`` pointing at a blob is written with ``git hash-object -t
tree --literally`` into a fresh repository, and ``git ls-tree`` prints the mode git reads it as (``null`` when
git refuses the tree: ``malformed mode in tree entry``). ``test_gitobj.Modes`` compares ``loop.gitobj.canonical``
with this table. Run from ``referee/``: ``python tests/capture_git_modes.py > tests/fixtures/git-modes.json``.
"""

import json
import subprocess
import sys
import tempfile

MODES = ["100644", "100755", "120000", "40000", "160000",            # what git writes
         "100664", "100600", "100700", "100744", "100777", "100000",  # regular files, other permission bits
         "100611", "100654", "1100644", "7100755", "300644",          # exec bits of others only; bits above
         "040000", "040755", "120777", "120644",                       # zero-padded tree, link with bits
         "140000", "60000", "20000", "10000", "170000", "0", "644", "1006440",  # neither: git reads a gitlink
         "40000000000100644", "77777777777",                          # past 32 bits (git's unsigned int)
         "", "100644x", "100648", "-100644", "1o0644"]                 # not octal digits: malformed


def main() -> int:
    env = {"GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null", "PATH": "/usr/bin:/bin"}
    with tempfile.TemporaryDirectory() as repo:
        run = lambda argv, data=None: subprocess.run(["git", "-C", repo] + argv, input=data, capture_output=True,
                                                     env=env)
        subprocess.run(["git", "init", "-q", repo], check=True, env=env)
        blob = run(["hash-object", "-w", "--stdin"], b"hi\n").stdout.decode().strip()
        out = {"git": run(["--version"]).stdout.decode().strip(), "blob": blob, "modes": {}}
        for mode in MODES:
            tree = run(["hash-object", "-t", "tree", "--literally", "-w", "--stdin"],
                       mode.encode() + b" f\0" + bytes.fromhex(blob)).stdout.decode().strip()
            ls = run(["ls-tree", tree])
            if ls.returncode != 0:
                assert b"malformed mode" in ls.stderr, ls.stderr
                out["modes"][mode] = None
            else:
                got, _, rest = ls.stdout.decode().partition(" ")
                assert rest.endswith(" %s\tf\n" % blob), ls.stdout
                out["modes"][mode] = got
    json.dump(out, sys.stdout, indent=1)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
