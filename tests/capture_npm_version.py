"""Capture of ``fixtures/npm-version.json``: how npm's own code reads a ``package.json``'s ``version`` (tests only;
needs ``node`` and an installed ``npm``).

One table, asked of the real code and written as it answers: for each value of ``READ`` and ``LEFT``,
``@npmcli/package-json``'s ``lib/normalize.js`` run on ``{name: "x", version: value}`` with the one step
``fixVersionField`` (the step that validates and cleans the version with node-semver's loose reading; pacote's
manifest reading goes through this module, which is read from pacote's source and not run here). ``read`` is the
version the content holds afterwards, None when the call threw (``Invalid version``, or a ``TypeError`` on a
value node-semver cannot take).

``READ`` are the values ``runner.deps_npm.manifest_version`` promises to read as npm does; ``LEFT`` the ones it
leaves as written or reads as nothing, where npm reads something else. ``test_npm_capture`` holds the function to
both. Run from ``referee/``: ``python tests/capture_npm_version.py > tests/fixtures/npm-version.json``.
"""

import json
import os
import subprocess
import sys

READ = ["1.8.8", "v1.8.8", "=1.8.8", "==1.8.8", "vv1.8.8", "v=1.8.8", "=v1.8.8", " 1.8.8", "1.8.8 ", " v1.8.8 ",
        "\t1.8.8\n", "\r\n1.8.8\r\n", "\x0b1.8.8\x0c", "v 1.8.8", "= 1.8.8", " = v 1.8.8", "v\t1.8.8",
        "1.0.0-beta.1", "v1.0.0-beta.1", "1.0.0-rc.1", "=0.0.0", "10.20.30", "v1.2.3-0"]

LEFT = ["1.2.3beta", "v1.2.3beta", "01.2.3", "1.02.3", "1.2.3+build", "v1.2.3+build.5", "1.2.3-beta+b",
        "\xa01.8.8", "\ufeff1.8.8", "1.8.8\u2028", "", "v", "1.8", "1", "1.8.8.1", "V1.8.8", "x1.8.8", "1 .8.8",
        "1.8.8 v", "latest", None, False, True, 0, 1, 1.8, [], ["1.8.8"], {}, {"version": "1.8.8"}]

SCRIPT = r"""
const fs = require('fs')
const normalize = require(process.argv[1])
const input = JSON.parse(fs.readFileSync(0, 'utf8'))
const main = async () => {
  const versions = []
  for (const value of input.values) {
    const content = {name: 'x', version: value}
    let read
    try { await normalize({content}, {steps: ['fixVersionField']}); read = content.version } catch (e) { read = null }
    versions.push({value, read})
  }
  process.stdout.write(JSON.stringify({node: process.version, versions}))
}
main()
"""


def main() -> int:
    root = subprocess.run(["npm", "root", "-g"], capture_output=True, text=True, check=True).stdout.strip()
    modules = os.path.join(root, "npm", "node_modules")
    versions = {}
    for field, package in (("npmcli_package_json", "@npmcli/package-json"), ("semver", "semver")):
        with open(os.path.join(modules, package, "package.json"), encoding="utf-8") as fh:
            versions[field] = json.load(fh)["version"]
    npm = subprocess.run(["npm", "--version"], capture_output=True, text=True, check=True).stdout.strip()
    proc = subprocess.run(["node", "-e", SCRIPT, os.path.join(modules, "@npmcli", "package-json", "lib", "normalize.js")],
                          capture_output=True, text=True, check=True, input=json.dumps({"values": READ + LEFT}))
    got = json.loads(proc.stdout)
    out = {"npm": npm, "node": got["node"], "versions": got["versions"], **versions}
    json.dump(out, sys.stdout, indent=None, separators=(",", ":"), sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
