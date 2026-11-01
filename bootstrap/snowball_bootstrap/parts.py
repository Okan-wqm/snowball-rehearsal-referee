"""`kos` in parts (E440): one push's run shared out among N parallel jobs and joined into the single job's `run.json`.

The single job is the one-part case of this same code (`run-tests`). A part runs the red controls in its own sandbox,
then its share of the work, each piece exactly as the single job runs it: the manifest's Stage 0 tests whose place is
its own (place mod N), the vector inputs whose place among the push's inputs is its own (first-asked order, each input
asked once, E273), and, when nothing it saw is red, its share of module-less red. It writes what it ran: the test and
module-less records, and for every vector call the answer (a tape). It judges nothing.

The join does. It checks that every part is the part it says it is (place, part count, head and the push's plan, all
computed again here from the same snapshot) and that each part reported exactly its own share in order; then it
replays every vector judge over the merged tape in the single job's call order (`vectors.replay`), puts the tests and
the module-less records back in the single job's order and writes what the single job writes. A part missing, failed,
short, long, reordered or foreign stops the join: the push is an outage (`kos:failure`), never an accept.

A part's sandbox answers the red controls for that part. If any part's controls fail, the run is the single job's run
on that sandbox: the failing controls (the first such part's) and nothing else (`tohum/08` 3).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Callable

from . import canon, vectors
from .container import Runner, RunResult
from .controls import run_controls

SCHEMA = "snowball-bootstrap-part/1"
MAX_PARTS = 64


class PartError(ValueError):
    """The parts do not add up to one run of the push (E440): the join writes nothing."""


def nothing_red(controls: list[dict], tests: list[dict], vectors_: list[dict], lic: list[dict],
                module_less: list[dict] | None = None) -> bool:
    """No control misbehaved, no test, vector or wheel failed and no test stayed green without its module (nor did
    docker fail under one): what a part can say of its own share."""
    return (all(c["ok"] for c in controls) and all(t["ok"] for t in tests) and all(v["ok"] for v in vectors_)
            and all(x["allowed"] for x in lic)
            and not any(m["stayed_green"] or m["runner_fault"] for m in module_less or []))


def is_green(controls: list[dict], tests: list[dict], vectors_: list[dict], lic: list[dict],
             module_less: list[dict] | None = None) -> bool:
    """Green means: controls behaved, at least one test ran, every test, vector and wheel passed, and no test
    stayed green without its micro-feature's module (nor did docker fail under one)."""
    return bool(tests) and nothing_red(controls, tests, vectors_, lic, module_less)


def test_record(test: dict[str, Any], res: RunResult) -> dict[str, Any]:
    """One declared test's run as `run.json` and the signed result hold it."""
    tail = (res.stdout + b"\n" + res.stderr).decode("utf-8", "replace")[-4000:]
    return {"id": test["id"], "cmd_sha256": hashlib.sha256(test["cmd"].encode()).hexdigest(),
            "exit": res.exit_code, "timed_out": res.timed_out, "duration_ms": res.duration_ms,
            "stdout_sha256": hashlib.sha256(res.stdout).hexdigest(),
            "stderr_sha256": hashlib.sha256(res.stderr).hexdigest(),
            "ok": res.ok, "output_tail": tail}


@dataclass(frozen=True)
class Push:
    """What every part and the join compute alike from the same snapshot, before anything runs."""

    head: str
    tests: list[dict[str, Any]]  # the manifest's Stage 0 tests, in order
    groups: vectors.Applied  # the vector groups this push runs, each with its judge
    asked: list[str]  # the input of every vector call, in the judges' order
    units: list[tuple[int, str]]  # every module-less run, (micro-feature, test id), in order
    lic: list[dict[str, Any]]
    missing: list[str]  # `vector_groups_missing`

    @property
    def inputs(self) -> list[str]:
        """Each input once, in the order it is first asked: the places the parts share out."""
        return list(dict.fromkeys(self.asked))

    def plan_sha256(self) -> str:
        return canon.sha256_hex(canon.canonical({
            "head": self.head, "tests": [[t["id"], hashlib.sha256(t["cmd"].encode()).hexdigest()] for t in self.tests],
            "asked": self.asked, "units": [[mf, test_id] for mf, test_id in self.units]}))


def part_of(text: str) -> tuple[int, int]:
    """``K/N`` as (K, N): part K of N, counted from 0."""
    try:
        k, n = (int(x) for x in text.split("/"))
    except ValueError:
        raise PartError(f"a part is K/N, not {text!r}") from None
    if not (1 <= n <= MAX_PARTS and 0 <= k < n):
        raise PartError(f"no part {text!r}: K/N with 0 <= K < N <= {MAX_PARTS}")
    return k, n


def run_part(push: Push, part: int, parts: int, runner: Runner, test_timeout_s: int,
             module_less: Callable[[Callable[[int], bool]], list[dict[str, Any]]]) -> dict[str, Any]:
    """Part ``part`` of ``parts``: its controls, then, on a sandbox that behaved, its tests, its vector calls and, when
    nothing it saw is red, its module-less runs. ``module_less`` runs the places a predicate names."""
    def own(place: int) -> bool:
        return place % parts == part
    record: dict[str, Any] = {"schema": SCHEMA, "part": part, "parts": parts, "head": push.head,
                              "plan_sha256": push.plan_sha256(), "controls": run_controls(runner), "tests": [],
                              "tape": [], "module_less": None}
    if not all(c["ok"] for c in record["controls"]):
        return record  # the single job runs nothing on a sandbox whose controls fail; neither does a part
    record["tests"] = [test_record(t, runner.run(t["cmd"], timeout_s=test_timeout_s))
                       for place, t in enumerate(push.tests) if own(place)]
    mine = {key for place, key in enumerate(push.inputs) if own(place)}
    record["tape"], known = vectors.run_part(runner, push.groups, mine)
    if nothing_red(record["controls"], record["tests"], known, push.lic):  # a red push is rejected anyway
        record["module_less"] = module_less(own)
    return record


def _merge(what: str, keys: list[Any], owners: list[int], shares: list[list[dict]], key: Callable[[dict], Any]) -> list:
    """The single job's list: the record at each place taken, in order, from the share of the part that owns it."""
    taken = [0] * len(shares)
    merged = []
    for place, (wanted, owner) in enumerate(zip(keys, owners)):
        share = shares[owner]
        if taken[owner] >= len(share) or key(share[taken[owner]]) != wanted:
            raise PartError(f"part {owner} of {len(shares)} does not hold {what} {place} where its share has it")
        merged.append(share[taken[owner]])
        taken[owner] += 1
    for owner, share in enumerate(shares):
        if taken[owner] != len(share):
            raise PartError(f"part {owner} of {len(shares)} reported {len(share) - taken[owner]} {what} not its own")
    return merged


def _well_formed(record: Any, part: int, parts: int, push: Push) -> None:
    if not isinstance(record, dict) or record.get("schema") != SCHEMA:
        raise PartError(f"part {part}: not a {SCHEMA} record")
    if (record.get("part"), record.get("parts")) != (part, parts):
        raise PartError(f"part {part} of {parts} holds the record of part {record.get('part')} of {record.get('parts')}")
    if record.get("head") != push.head or record.get("plan_sha256") != push.plan_sha256():
        raise PartError(f"part {part} ran another push or another plan of it")
    lists = ("controls", "tests", "tape")
    if not all(isinstance(record.get(name), list) and all(isinstance(x, dict) for x in record[name]) for name in lists):
        raise PartError(f"part {part}: controls, tests and tape must be lists of objects")
    if not (record["module_less"] is None or isinstance(record["module_less"], list)
            and all(isinstance(x, dict) for x in record["module_less"])):
        raise PartError(f"part {part}: module_less must be null or a list of objects")
    for entry in record["tape"]:
        if (sorted(entry) != sorted(vectors.TAPE_FIELDS) or not isinstance(entry["input"], str)
                or not (entry["line"] is None or isinstance(entry["line"], str))
                or not (entry["exit"] is None or type(entry["exit"]) is int) or not isinstance(entry["fault"], str)):
            raise PartError(f"part {part}: a tape entry is not {{input, line, exit, fault}}")


def join(push: Push, records: list[Any]) -> dict[str, Any]:
    """`run.json` of the push from its parts' records, in part order: what the single job writes on the same answers."""
    parts = len(records)
    if not 1 <= parts <= MAX_PARTS:
        raise PartError(f"{parts} parts: a run has 1 to {MAX_PARTS}")
    for part, record in enumerate(records):
        _well_formed(record, part, parts, push)
    failed = [r for r in records if not all(c.get("ok") is True for c in r["controls"])]
    if failed:
        return _run(push, failed[0]["controls"], [], [], [])
    controls = records[0]["controls"]
    if any(r["controls"] != controls for r in records):
        raise PartError("the parts' sandboxes answered the red controls differently")
    tests = _merge("test", [t["id"] for t in push.tests], [p % parts for p in range(len(push.tests))],
                   [r["tests"] for r in records], lambda rec: rec.get("id"))
    owner = {key: place % parts for place, key in enumerate(push.inputs)}
    tape = _merge("vector call", push.asked, [owner[key] for key in push.asked], [r["tape"] for r in records],
                  lambda entry: entry["input"])
    try:
        vector_records = vectors.replay(tape, push.groups)
    except vectors.TapeError as exc:
        raise PartError(str(exc)) from None
    module_less: list[dict[str, Any]] = []
    if is_green(controls, tests, vector_records, push.lic):  # the single job runs module-less red then, and only then
        if any(r["module_less"] is None for r in records):
            raise PartError("a part left out its module-less runs, yet the push is green")
        module_less = _merge("module-less run", list(push.units), [p % parts for p in range(len(push.units))],
                             [r["module_less"] for r in records], lambda rec: (rec.get("mf"), rec.get("test_id")))
    return _run(push, controls, tests, vector_records, module_less)


def _run(push: Push, controls: list[dict], tests: list[dict], vector_records: list[dict],
         module_less: list[dict]) -> dict[str, Any]:
    return {"controls": controls, "tests": tests, "vectors": vector_records, "licenses": push.lic,
            "module_less": module_less, "vector_groups_missing": push.missing,
            "green": is_green(controls, tests, vector_records, push.lic, module_less)}
