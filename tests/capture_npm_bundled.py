"""Capture of ``fixtures/npm-bundled.json``: which directories below a package's own ``node_modules`` npm reads as
packages, and which of their install scripts ``npm rebuild`` runs (tests only; needs ``node`` and an installed
``npm``; it runs npm on directories this script writes in a temporary place, nothing of a target).

One table, asked of the real code and written as it answers. For each layout of ``LAYOUTS`` a project is written:
``package.json`` depending on ``host``, and ``node_modules/host/`` with a ``package.json`` whose
``bundleDependencies`` is the layout's ``bundle`` and, for each directory of ``DIRS``, a ``package.json`` at
``node_modules/host/<directory>/`` with a ``postinstall`` that writes a file ``ran`` beside it. Then:

- ``loaded``: the directories below ``node_modules/host/`` that ``@npmcli/arborist``'s ``loadActual`` holds as
  nodes (its inventory's locations);
- ``ran``: the directories that hold ``ran`` after ``npm --prefix <project> rebuild --offline
  --foreground-scripts host``, the command ``profile.unit_verify`` runs for a marked package.

``test_npm_capture`` holds ``runner.deps_npm.bundled_path`` to it: every directory of ``loaded`` and of ``ran``
is a chain. Run from ``referee/``: ``python tests/capture_npm_bundled.py > tests/fixtures/npm-bundled.json``.
"""

import json
import os
import subprocess
import sys
import tempfile

DIRS = ["node_modules/a", "node_modules/_x", "node_modules/.h", "node_modules/x y", "node_modules/UP",
        "node_modules/~t", "node_modules/n!", "node_modules/-d", "node_modules/ü", "node_modules/@s/y",
        "node_modules/@s/.z", "node_modules/@s/_w", "node_modules/@/q", "node_modules/@/.r",
        "node_modules/a/node_modules/b", "node_modules/a/node_modules/.c", "node_modules/a/node_modules/@t/u",
        "node_modules/a/lib/node_modules/d", "node_modules/a/lib", "node_modules/.h/node_modules/e",
        "node_modules/@s/y/node_modules/f", "lib/node_modules/g", "lib"]

TOP = ["a", "_x", ".h", "x y", "UP", "~t", "n!", "-d", "ü", "@s/y", "@s/.z", "@s/_w", "@/q", "@/.r"]

LAYOUTS = [{"id": "all_listed", "bundle": TOP}, {"id": "some_listed", "bundle": ["_x", "@s/y"]},
           {"id": "none_listed", "bundle": []}, {"id": "no_field", "bundle": None}]

SCRIPT = r"""
const Arborist = require(process.argv[1])
const main = async () => {
  const tree = await new Arborist({path: process.argv[2]}).loadActual()
  const prefix = 'node_modules/host/'
  const loaded = [...tree.inventory.values()].map(n => n.location.replace(/\\/g, '/'))
    .filter(l => l.startsWith(prefix)).map(l => l.slice(prefix.length)).sort()
  process.stdout.write(JSON.stringify({node: process.version, loaded}))
}
main()
"""


def write(path: str, obj: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh)


def one(layout: dict, modules: str) -> dict:
    with tempfile.TemporaryDirectory() as project:
        project = os.path.realpath(project)
        write(os.path.join(project, "package.json"), {"name": "root", "version": "1.0.0",
                                                     "dependencies": {"host": "1.0.0"}})
        host = os.path.join(project, "node_modules", "host")
        manifest = {"name": "host", "version": "1.0.0"}
        if layout["bundle"] is not None:
            manifest["bundleDependencies"] = layout["bundle"]
        write(os.path.join(host, "package.json"), manifest)
        for number, directory in enumerate(DIRS):
            write(os.path.join(host, directory, "package.json"),
                  {"name": "p%d" % number, "version": "1.0.0", "scripts": {"postinstall": "touch ran"}})
        proc = subprocess.run(["node", "-e", SCRIPT, os.path.join(modules, "@npmcli", "arborist"), project],
                              capture_output=True, text=True, check=True)
        got = json.loads(proc.stdout)
        env = dict(os.environ, npm_config_cache=os.path.join(project, ".cache"), npm_config_update_notifier="false")
        subprocess.run(["npm", "--prefix", project, "rebuild", "--offline", "--foreground-scripts", "host"],
                       capture_output=True, text=True, check=True, cwd=project, env=env)
        ran = sorted(d for d in DIRS if os.path.exists(os.path.join(host, d, "ran")))
        return {"id": layout["id"], "bundle": layout["bundle"], "loaded": got["loaded"], "ran": ran,
                "node": got["node"]}


def main() -> int:
    root = subprocess.run(["npm", "root", "-g"], capture_output=True, text=True, check=True).stdout.strip()
    modules = os.path.join(root, "npm", "node_modules")
    with open(os.path.join(modules, "@npmcli", "arborist", "package.json"), encoding="utf-8") as fh:
        arborist = json.load(fh)["version"]
    npm = subprocess.run(["npm", "--version"], capture_output=True, text=True, check=True).stdout.strip()
    layouts = [one(layout, modules) for layout in LAYOUTS]
    node = layouts[0]["node"]
    for layout in layouts:
        del layout["node"]
    out = {"npm": npm, "node": node, "npmcli_arborist": arborist, "dirs": DIRS, "layouts": layouts}
    json.dump(out, sys.stdout, indent=None, separators=(",", ":"), sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
