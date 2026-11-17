"""Capture of ``fixtures/npm-platform.json``: what npm's own code answers for a lock entry's ``os``, ``cpu`` and
``libc`` and which JSON values JavaScript holds true (tests only; needs ``node`` and an installed ``npm``).

Two tables, asked of the real code and written as it answers:

- ``platform``: for each environment of ``ENVS`` and each entry of ``entries()``, npm-install-checks'
  ``checkPlatform(entry, false, env)`` (the call arborist's reify makes): ``admits`` when it returns, else the
  thrown error's ``code`` (``EBADPLATFORM``) or, without one, its class name (``TypeError``). An environment
  without ``libc`` is one whose ``os`` is not ``linux``: npm then finds no libc itself, where for ``linux`` it
  would probe this machine's.
- ``truth``: ``!!value`` for each value of ``FLAGS``, the reading arborist's load-virtual gives a lock entry's
  ``optional`` (``node.optional = !!sw.optional``; that line is read from the source, it is not run here).

``test_npm_capture`` compares ``runner.deps_npm.platform_admits`` and ``js_true`` with these tables. Run from
``referee/``: ``python tests/capture_npm_platform.py > tests/fixtures/npm-platform.json``.
"""

import json
import os
import subprocess
import sys

ENVS = [{"os": "linux", "cpu": "x64", "libc": "glibc"}, {"os": "linux", "cpu": "arm64", "libc": "musl"},
        {"os": "darwin", "cpu": "arm64"}]

# one field's values: what npm writes, what a hand can write, and shapes that are not a list of strings
VALUES = ["linux", "darwin", "x64", "arm64", "glibc", "musl", "any", "!linux", "!win32", "!", "",
          ["linux"], ["darwin"], ["darwin", "linux"], ["x64"], ["arm64"], ["x64", "arm64"], ["glibc"], ["musl"],
          ["any"], ["any", "darwin"], ["darwin", "any"], [], [""], ["!"],
          ["!win32"], ["!linux"], ["!win32", "darwin"], ["!win32", "linux"], ["linux", "!linux"],
          ["!linux", "linux"], ["!x64"], ["!musl"], ["!glibc"], ["!win32", "!darwin"],
          None, False, 0, True, 1, 7, -1,
          {}, {"linux": 1}, {"length": 1, "0": "any"}, {"length": 1, "0": "any", "1": "darwin"},
          {"length": 1, "0": "linux"}, {"length": 2, "0": "any"}, {"length": True, "0": "any"},
          {"length": "1", "0": "any"}, {"length": 0}, {"0": "any"},
          ["linux", 7], [7, "linux"], [["linux"]], [7], ["!linux", 7], [7, "!linux"], [None], [None, "linux"],
          [True], [{}], ["any", 7], [["any"]]]

FLAGS = [True, False, None, 0, 1, -1, "", "true", "false", "0", [], [0], {}, {"a": 0}]

# entries with more than one field: every field must admit
COMBINED = [{"os": ["linux"], "cpu": ["x64"], "libc": ["glibc"]}, {"os": ["linux"], "cpu": ["x64"], "libc": ["musl"]},
            {"os": ["linux"], "cpu": ["arm64"], "libc": ["glibc"]}, {"os": ["darwin"], "cpu": ["x64"]},
            {"os": ["linux"], "cpu": None}, {"os": None, "cpu": ["arm64"]}, {"os": "", "cpu": "", "libc": ""},
            {"os": ["darwin"], "cpu": ["arm64"], "libc": None}, {"os": ["darwin"], "cpu": ["arm64"], "libc": ["glibc"]},
            {}, {"optional": True, "engines": {"node": ">=99"}}]

SCRIPT = r"""
const fs = require('fs')
const {checkPlatform} = require(process.argv[1])
const input = JSON.parse(fs.readFileSync(0, 'utf8'))
const platform = []
for (const env of input.envs) {
  for (const entry of input.entries) {
    let outcome
    try { checkPlatform(entry, false, env); outcome = 'admits' } catch (e) { outcome = e.code || e.constructor.name }
    platform.push({env, entry, outcome})
  }
}
const truth = input.flags.map(value => ({value, true: !!value}))
process.stdout.write(JSON.stringify({node: process.version, platform, truth}))
"""


def entries() -> list:
    return [{field: value} for field in ("os", "cpu", "libc") for value in VALUES] + COMBINED


def main() -> int:
    root = subprocess.run(["npm", "root", "-g"], capture_output=True, text=True, check=True).stdout.strip()
    checks = os.path.join(root, "npm", "node_modules", "npm-install-checks")
    with open(os.path.join(checks, "package.json"), encoding="utf-8") as fh:
        checks_version = json.load(fh)["version"]
    npm = subprocess.run(["npm", "--version"], capture_output=True, text=True, check=True).stdout.strip()
    proc = subprocess.run(["node", "-e", SCRIPT, checks], capture_output=True, text=True, check=True,
                          input=json.dumps({"envs": ENVS, "entries": entries(), "flags": FLAGS}))
    got = json.loads(proc.stdout)
    out = {"npm": npm, "npm_install_checks": checks_version, "node": got["node"], "platform": got["platform"],
           "truth": got["truth"]}
    json.dump(out, sys.stdout, indent=None, separators=(",", ":"), sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
