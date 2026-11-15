"""The loop's reads of `policy.json`, asked of the loop itself (`tohum/29v`; the Founder's report seed-053, E588).

A key of `policy.json` stands under its section (`26b`: `constitutional`, `operating`, `performance`); `18a` and `18b`
write each key with its section. The Founder's canary read `stage_budgets` at the file's top level and its own tests
agreed with its code, not with the page (seed-053): nothing the referee ran read a policy file for a key's path. This
check does, for every key at once: on every push whose tests run, `kos` runs ``python -m policy.reads <file>`` in
`referee/`, in the tests' sandbox, over two of the seed's fixtures at `/vec/policy/`: `policy.json`, every `18a` and
`18b` key under its section, and `policy_hoisted.json`, the same file with the stage's required paths (`required.json`)
taken out of their sections and put at the top level with other values. The command's last stdout line is one JSON
object whose field names are the full paths of the values the loop reads, each with the value it read there.

The judge holds the answer to the fixture: every named path starts with a section and is the fixture's, its value is
the fixture's value there, and every required path is named (itself or a dotted ancestor). On the hoisted file a
required path read with the top-level value is a read from the wrong place. `decide` reads the findings as the self map
check's (`29t`): warnings in Stage 0, reasons the Founder can fix once the lock opened Stage 1. A pass says the values
the command names come from their paths, not that every read of the loop is named (E589).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .container import Runner, RunResult
from . import secretscan
from .moduleless import DOCKER_ERROR, output_record

FIXTURE_DIR = "policy"  # under the seed's `vectors/`, mounted at `/vec/policy/`
FULL = "policy.json"
HOISTED = "policy_hoisted.json"
REQUIRED = "required.json"
SECTIONS = ("constitutional", "operating", "performance")
RUN_DIR = "referee"
MODULE_FILE = "referee/policy/reads.py"  # the ref of a finding that names no path
LINE_MAX = 65536  # the last stdout line is read up to this many bytes; a longer one is no answer
PATH_SHOWN_MAX = 120  # a path the command names and the fixture lacks is shown up to this long
FAILED = "policy_reads_failed"
UNSECTIONED = "policy_reads_unsectioned"
UNKNOWN = "policy_reads_unknown"
WRONG_VALUE = "policy_reads_wrong_value"
REQUIRED_ABSENT = "policy_reads_required_absent"
ROOT_FALLBACK = "policy_reads_root_fallback"
NAMES = (FAILED, UNSECTIONED, UNKNOWN, WRONG_VALUE, REQUIRED_ABSENT, ROOT_FALLBACK)
RUN_FIELDS = ("exit", "timed_out", "duration_ms", "runner_fault", "line", "output_sha256", "output_tail")


def command(fixture: str) -> str:
    """The one command the referee runs over one of its fixtures."""
    if fixture not in (FULL, HOISTED):
        raise ValueError(f"not a policy fixture: {fixture!r}")
    return f"python -m policy.reads /vec/{FIXTURE_DIR}/{fixture}"


def required_paths(rows: Any, stage: int) -> list[str]:
    """The required paths of ``stage``: every row of `required.json` for that stage or an earlier one (a later stage
    keeps reading what an earlier one read), each a dotted path under a section."""
    if not (isinstance(rows, dict) and all(isinstance(k, str) and k.isdigit() for k in rows)):
        raise ValueError(f"{REQUIRED} must be an object keyed by stage numbers")
    paths = set()
    for key, listed in rows.items():
        if not (isinstance(listed, list) and all(isinstance(p, str) and p.split(".")[0] in SECTIONS for p in listed)):
            raise ValueError(f"{REQUIRED}[{key}] must be a list of paths under a section")
        if int(key) <= stage:
            paths.update(listed)
    return sorted(paths)


def plan(vectors_dir: Path, stage: int) -> dict[str, Any] | None:
    """What `kos` runs and judges for ``stage``: the required paths and both fixtures, read from the seed's own files;
    None when the seed holds no `vectors/policy/` (nothing to ask). A broken seed file stops the run (ValueError)."""
    base = vectors_dir / FIXTURE_DIR
    if not (base / REQUIRED).is_file():
        return None
    docs = {}
    for name in (REQUIRED, FULL, HOISTED):
        docs[name] = json.loads((base / name).read_text(encoding="utf-8"))
    if not all(isinstance(docs[n], dict) for n in (FULL, HOISTED)):
        raise ValueError("the policy fixtures must be JSON objects")
    return {"required": required_paths(docs[REQUIRED], stage), "full": docs[FULL], "hoisted": docs[HOISTED]}


def digest(plan_: dict[str, Any] | None) -> str | None:
    """The plan's sha256 (sorted-key JSON; the fixtures hold numbers canonical JSON refuses): what a part's plan hash
    binds, so a part run on other fixtures or another stage's paths never joins."""
    if plan_ is None:
        return None
    return hashlib.sha256(json.dumps(plan_, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def _record(res: RunResult) -> dict[str, Any]:
    lines = [line for line in res.stdout.split(b"\n") if line.strip()]
    last = lines[-1] if lines else b""
    return {"exit": res.exit_code, "timed_out": res.timed_out, "duration_ms": res.duration_ms,
            "runner_fault": res.exit_code == DOCKER_ERROR,
            "line": last.decode("utf-8", "replace") if len(last) <= LINE_MAX else None, **output_record(res)}


def run(runner: Runner, timeout_s: int) -> dict[str, Any]:
    """The command over the full fixture, then over the hoisted one, both in `referee/`: always both runs."""
    return {"runs": [_record(runner.run(command(name), cwd=RUN_DIR, timeout_s=timeout_s)) for name in (FULL, HOISTED)]}


def complete(record: Any) -> bool:
    """Whether ``record`` is a run of this check: both runs, each with exactly its fields."""
    runs = record.get("runs") if isinstance(record, dict) and set(record) == {"runs"} else None
    return (isinstance(runs, list) and len(runs) == 2
            and all(isinstance(r, dict) and set(r) == set(RUN_FIELDS) for r in runs))


def runner_fault(record: Any) -> bool:
    """Docker itself failed under one of the runs: nothing the run printed is evidence about the push."""
    return isinstance(record, dict) and any(r.get("runner_fault") for r in record.get("runs") or [])


def _same(a: Any, b: Any) -> bool:
    """JSON equality with the type: 1, 1.0 and true are three values."""
    if type(a) is not type(b):
        return False
    if isinstance(a, dict):
        return a.keys() == b.keys() and all(_same(a[k], b[k]) for k in a)
    if isinstance(a, list):
        return len(a) == len(b) and all(_same(x, y) for x, y in zip(a, b))
    return a == b


_ABSENT = object()


def at(doc: Any, keys: list[str]) -> Any:
    """The value at ``keys`` in ``doc``, or the absent marker."""
    for key in keys:
        if not (isinstance(doc, dict) and key in doc):
            return _ABSENT
        doc = doc[key]
    return doc


def _reads(line: Any) -> dict[str, Any] | None:
    """The command's answer: one JSON object of string paths, or None."""
    if not isinstance(line, str):
        return None
    try:
        found = json.loads(line)
    except (ValueError, RecursionError):
        return None
    return found if isinstance(found, dict) else None


def _covering(reads: dict[str, Any], path: str) -> Any:
    """What ``reads`` says of ``path``: its own value, or the value inside an ancestor named on a dot boundary; the
    absent marker when neither is named."""
    keys = path.split(".")
    for n in range(len(keys), 0, -1):
        name = ".".join(keys[:n])
        if name in reads:
            return at(reads[name], keys[n:])
    return _ABSENT


def shown(path: str) -> str:
    """A path the command named, as the signed result may show it: the Founder's own text, so one that is long or
    matches a secret pattern is named by its hash only (E290's rule for `output_tail`)."""
    if len(path) <= PATH_SHOWN_MAX and not secretscan.scan(path):
        return path
    return "sha256:" + hashlib.sha256(path.encode("utf-8", "replace")).hexdigest()[:16]


def _tail(run_: dict[str, Any]) -> str:
    how = "timed out" if run_["timed_out"] else f"exited {run_['exit']}"
    return f"{how}; output tail: {run_['output_tail']}"


def findings(plan_: dict[str, Any], record: dict[str, Any]) -> list[tuple[str, str, str]]:
    """``(name, path, detail)`` of every finding, in path order; [] when the answer is the fixture's."""
    first, second = record["runs"]
    if first["exit"] != 0 or first["timed_out"]:
        return [(FAILED, MODULE_FILE, f"{command(FULL)} {_tail(first)}")]
    reads = _reads(first["line"])
    if reads is None:
        return [(FAILED, MODULE_FILE, f"the last stdout line of {command(FULL)} is not one JSON object")]
    out = []
    for path in sorted(reads):
        keys = path.split(".")
        if keys[0] not in SECTIONS:
            out.append((UNSECTIONED, shown(path), f"{shown(path)} does not start with {', '.join(SECTIONS)} (`26b`)"))
            continue
        want = at(plan_["full"], keys)
        if want is _ABSENT:
            out.append((UNKNOWN, shown(path), f"{shown(path)} is not a key of {FULL} (`18a`, `18b`)"))
        elif not _same(reads[path], want):
            out.append((WRONG_VALUE, path, f"{path} was read as another value than {FULL} holds there"))
    for path in plan_["required"]:
        if _covering(reads, path) is _ABSENT:
            out.append((REQUIRED_ABSENT, path, f"{path} is read by the loop (`18a`) and the command does not name it"))
    hoisted = _reads(second["line"]) if second["exit"] == 0 and not second["timed_out"] else None
    for path in plan_["required"] if hoisted is not None else []:
        got, decoy = _covering(hoisted, path), at(plan_["hoisted"], path.split(".")[1:])
        if got is not _ABSENT and decoy is not _ABSENT and _same(got, decoy):
            out.append((ROOT_FALLBACK, path, f"{path} was read from the top level of {HOISTED}, where it is not"))
    return sorted(out, key=lambda f: (f[1], f[0]))
