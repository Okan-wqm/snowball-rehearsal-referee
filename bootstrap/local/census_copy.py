"""The copy target's `census` vector (`29za`, E671, E744): the enabled ESLint rule set at the copy's pinned `base_sha`,
produced by the operator with ESLint's own `--print-config` on each unit and committed as the seed's `census_copy`
group (interface `29zc`).

The units are the referee's `setup/summary.json` `targets[kind=copy].unit_candidates`. `collect` asks the copy's own
ESLint, installed from the copy's own lockfile, about every tracked file of each unit, with no extension list of its
own: a file is linted when ESLint does not ignore it and a config applies to it (`isPathIgnored`,
`calculateConfigForFile`, what `eslint --print-config <file>` prints; it prints `undefined` for a file no config
applies to). It writes each linted file's raw output, the JSON the CLI prints (in one process the `settings` key may
come at another place: the `rules` object is the same), and `run.json` with the Node, npm,
ESLint and plugin versions read from the run itself. `record` reduces them to `census_copy.json`: per unit the enabled
rules, the copy's set as their union with each rule carrying the units it is enabled in, every file's verdict and
hashes, and each distinct canonical `rules` object (options included) once, keyed by its sha256. A rule is enabled
when its severity is "warn", "error", 1 or 2 (alone or first in its array); "off" and 0 are not; any other severity
stops the run.

Reproduce (Node 20.11.0, the copy's `.nvmrc`, with its npm; no Docker):
    git clone https://github.com/Okan-wqm/snowball-rehearsal-copy copy && git -C copy checkout <base_sha>
    cd copy && npm ci --ignore-scripts --no-audit --no-fund
    python seed/bootstrap/local/census_copy.py collect copy raw <unit>...
    python seed/bootstrap/local/census_copy.py record copy raw census_copy.json <unit>...
The raw outputs carry the checkout's absolute path (`tsconfigRootDir`, parser paths), so their sha256 is the
derivation's at the recorded `checkout`; each output's `rules` object, canonical, is path-free and is what re-derives.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

ON = {1, 2, "warn", "error"}
OFF = {0, "off"}
PLUGINS = ("@eslint/js", "@typescript-eslint/eslint-plugin", "@typescript-eslint/parser", "@nx/eslint-plugin",
           "eslint-plugin-import", "eslint-plugin-jsx-a11y", "eslint-plugin-react", "eslint-plugin-react-hooks",
           "jsonc-eslint-parser", "typescript")

# Run by the copy's own node in the copy's root: one JSON line per file on stdout, then one line of versions.
ASK = r"""
const { createRequire } = require("node:module");
const path = require("node:path");
const fs = require("node:fs");
const local = createRequire(path.join(process.cwd(), "package.json"));
const { ESLint } = local("eslint");
const npmDirs = [path.join(path.dirname(process.execPath), "node_modules", "npm"),
                 path.join(path.dirname(process.execPath), "..", "lib", "node_modules", "npm")];
const npmDir = npmDirs.find((d) => fs.existsSync(path.join(d, "package.json")));
(async () => {
  const eslint = new ESLint({ cwd: process.cwd() });
  const files = JSON.parse(fs.readFileSync(0, "utf8"));
  for (const file of files) {
    const ignored = await eslint.isPathIgnored(file);
    const config = ignored ? undefined : await eslint.calculateConfigForFile(file);
    const text = config === undefined ? null : JSON.stringify(config, null, "  ") + "\n";
    process.stdout.write(JSON.stringify({ file, ignored, text }) + "\n");
  }
  process.stdout.write(JSON.stringify({ node: process.version.replace(/^v/, ""), eslint: ESLint.version,
    npm: npmDir ? JSON.parse(fs.readFileSync(path.join(npmDir, "package.json"), "utf8")).version : null }) + "\n");
})().catch((error) => { console.error(error); process.exit(1); });
"""


def severity_on(value) -> bool:
    """Whether one rule's configured value enables it; a severity that is none of 0-2 or off/warn/error is an error."""
    level = value[0] if isinstance(value, list) and value else value
    if isinstance(level, bool) or not isinstance(level, (int, str)) or (level not in ON and level not in OFF):
        raise ValueError(f"not a severity: {value!r}")
    return level in ON


def enabled(config: dict) -> list[str]:
    """The enabled rules of one `--print-config` output, sorted."""
    return sorted(rule for rule, value in config["rules"].items() if severity_on(value))


def union(units: dict[str, list[str]]) -> dict[str, list[str]]:
    """The copy's set: every rule enabled in some unit, with the units it is enabled in, both sorted."""
    found: dict[str, list[str]] = {}
    for unit in sorted(units):
        for rule in units[unit]:
            found.setdefault(rule, []).append(unit)
    return {rule: found[rule] for rule in sorted(found)}


def case_name(rule: str) -> str:
    """A rule's case name (`29za`: `dot-notation` is `dot_notation`): `@` dropped, `/` and `-` become `_`."""
    return rule.lstrip("@").replace("/", "_").replace("-", "_")


def canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def files_of(checkout: Path, unit: str) -> list[str]:
    """Every tracked file of a unit, whatever its kind: ESLint, not this list, decides which it lints."""
    out = subprocess.run(["git", "-C", str(checkout), "ls-files", "-z", "--", unit], check=True,
                         capture_output=True).stdout.decode("utf-8")
    return sorted(f for f in out.split("\0") if f)


def raw_name(path: str) -> str:
    return path.replace("/", "__") + ".json"


def collect(checkout: Path, raw: Path, units: list[str]) -> None:
    files = [f for unit in units for f in files_of(checkout, unit)]
    proc = subprocess.run(["node", "-e", ASK], cwd=checkout, input=json.dumps(files).encode("utf-8"), check=True,
                          capture_output=True)
    lines = [json.loads(line) for line in proc.stdout.decode("utf-8").splitlines()]
    raw.mkdir(parents=True, exist_ok=True)
    verdicts = {}
    for row in lines[:-1]:
        verdicts[row["file"]] = {"ignored": row["ignored"], "linted": row["text"] is not None}
        if row["text"] is not None:
            (raw / raw_name(row["file"])).write_bytes(row["text"].encode("utf-8"))
    if sorted(verdicts) != sorted(files):
        raise RuntimeError("ESLint did not answer for every file")
    modules = checkout / "node_modules"
    versions = dict(lines[-1], **{name: json.loads((modules / name / "package.json").read_text(encoding="utf-8"))
                                  ["version"] for name in PLUGINS})
    (raw / "run.json").write_text(json.dumps({"versions": versions, "files": verdicts}, indent=1) + "\n",
                                  encoding="utf-8", newline="\n")


def record(checkout: Path, raw: Path, units: list[str]) -> dict:
    head = subprocess.run(["git", "-C", str(checkout), "rev-parse", "HEAD"], check=True, capture_output=True,
                          text=True).stdout.strip()
    run = json.loads((raw / "run.json").read_text(encoding="utf-8"))
    per_unit, files, rules_by_sha = {}, {}, {}
    for unit in units:
        found: set[str] = set()
        for path in files_of(checkout, unit):
            verdict = run["files"][path]
            if not verdict["linted"]:
                files[path] = {"linted": False, "ignored": verdict["ignored"]}
                continue
            data = (raw / raw_name(path)).read_bytes()
            config = json.loads(data)
            key = sha256(canonical(config["rules"]))
            rules_by_sha[key] = config["rules"]
            files[path] = {"linted": True, "raw_sha256": sha256(data), "rules_sha256": key,
                           "enabled": len(enabled(config))}
            found.update(enabled(config))
        per_unit[unit] = sorted(found)
    return {"schema": "snowball-census-copy/2", "repo": "Okan-wqm/snowball-rehearsal-copy", "base_sha": head,
            "checkout": checkout.resolve().as_posix(), "tool": "eslint", "versions": run["versions"],
            "units": {unit: {"enabled": per_unit[unit]} for unit in units}, "files": files,
            "union": union(per_unit), "rules": {key: rules_by_sha[key] for key in sorted(rules_by_sha)}}


def main(argv: list[str]) -> int:
    if len(argv) >= 4 and argv[0] == "collect":
        collect(Path(argv[1]), Path(argv[2]), argv[3:])
        return 0
    if len(argv) >= 5 and argv[0] == "record":
        out = record(Path(argv[1]), Path(argv[2]), argv[4:])
        Path(argv[3]).write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n", encoding="utf-8",
                                 newline="\n")
        return 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
