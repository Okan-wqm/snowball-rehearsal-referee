"""Apply the seed vectors (`tohum/29a`, `29d`) to the founder's code through the fixed interface.

A vector group applies once a micro-feature of the stage table that owns it is declared done; a group the
table does not name has no owner in this stage and does not run (`cp_lower`, `mcnemar`, `match` are P1's,
`drill` the Stage 2 batch's). Every vector is checked twice: the right input must give the expected answer,
and a changed input must not.

`chain` and the P1 and drill groups have judges of their own, written before `29d`. Every other group is data
(`"runner": "data"`) and one judge applies it, so a seed epoch adds a group without adding code (`29d`).
"""

from __future__ import annotations

import json
import math
import shlex
import shutil
import time
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Callable

from . import stages
from .container import Runner

CWD = "referee"
SEED_FILE = "vectors.json"  # every case's command and expected answer; the fixtures sit beside it
# `docker run` exits with this when docker itself failed. Since E01 the container turns a command's own 125 into 1,
# so 125 here never comes from the Founder's code: such a vector is the sandbox failing, not a wrong answer (E141).
DOCKER_ERROR = 125
# Every vector call of one push together, retries included. The spec names no limit; this one keeps a command that
# hangs on every input from outliving the `kos` job (60 min), which would book the push as an outage that never
# reaches the Founder. What the budget leaves unrun is red as `not_run:time_budget` and the Founder's (E18's plan).
BUDGET_S = 1200
_now = time.monotonic


def fixtures(vectors_dir: Path, dest: Path) -> Path:
    """What the sandbox mounts at `/vec`: the seed's vectors without ``vectors.json``. The commands read their fixtures
    there; the expected values stay with the referee, or Founder code could print the answer it finds for its argv."""
    if dest.exists():  # a work directory used twice gets a fresh copy, never an old one
        shutil.rmtree(dest)
    shutil.copytree(vectors_dir, dest)
    (dest / SEED_FILE).unlink()
    return dest


def _last_json(stdout: bytes) -> dict[str, Any] | None:
    for line in reversed(stdout.decode("utf-8", "replace").splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            value = json.loads(line)
        except (json.JSONDecodeError, RecursionError):  # nested deeper than the parser goes is no answer, not a crash
            return None
        return value if isinstance(value, dict) else None
    return None


def _rounded(value: Any, like: str) -> str | None:
    if not isinstance(value, str):
        return None
    places = len(like.split(".", 1)[1]) if "." in like else 0
    try:
        return str(Decimal(value).quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP))
    except InvalidOperation:
        return None


class VectorRun:
    def __init__(self, runner: Runner, timeout_s: int, budget_s: int = BUDGET_S):
        self.runner = runner
        self.timeout_s = timeout_s
        self.deadline = _now() + budget_s
        self.results: list[dict[str, Any]] = []
        self.fault = ""
        self.exit: int | None = None  # the exit code of the last try of the last call

    def call(self, cmd: str, stdin: bytes = b"") -> dict[str, Any] | None:
        res = None
        for _ in range(2):  # a container the host killed under load answers nothing: ask again before blaming the judge
            left = self.deadline - _now()
            if left <= 0:
                break
            res = self.runner.run(cmd, cwd=CWD, stdin=stdin, timeout_s=min(self.timeout_s, math.ceil(left)))
            self.exit = res.exit_code
            if not res.timed_out and res.stdout.strip():
                self.fault = ""
                return _last_json(res.stdout)
        if res is None:  # the budget was spent before this call: it never ran
            self.exit = None
            self.fault = "not_run:time_budget"
            return None
        tail = res.stderr[-100:].decode("utf-8", "replace") if isinstance(res.stderr, bytes) else ""
        self.fault = f"no answer: exit {res.exit_code}{', timed out' if res.timed_out else ''} {tail}".strip()
        return None

    def record(self, vid: str, ok: bool, detail: str = "") -> None:
        if not ok and self.fault:
            detail = f"{detail} | {self.fault}"
            self.fault = ""
        self.results.append({"id": vid, "ok": ok, "detail": detail[:200], "exit": self.exit,
                             "runner_fault": not ok and self.exit == DOCKER_ERROR})


def _chain(run: VectorRun, spec: dict[str, Any]) -> None:
    for i, item in enumerate(spec["rows"], start=1):
        row, expected = item["row"], item["row_hash"]
        out = run.call("python -m ledger.chain hash", json.dumps(row).encode())
        got = out.get("row_hash") if out else None
        run.record(f"chain.V{i}.hash", got == expected, f"got {got}")
        changed = dict(row, row_id=row["row_id"] + "x")
        out = run.call("python -m ledger.chain hash", json.dumps(changed).encode())
        got = out.get("row_hash") if out else None
        run.record(f"chain.V{i}.hash_changed_input", isinstance(got, str) and got != expected, f"got {got}")
    out = run.call(f"python -m ledger.chain verify {shlex.quote('/vec/' + spec['verify_good'])}")
    run.record("chain.verify_good", bool(out) and out.get("valid") is True, json.dumps(out)[:120])
    out = run.call(f"python -m ledger.chain verify {shlex.quote('/vec/' + spec['verify_v3'])}")
    run.record("chain.V3", bool(out) and out.get("valid") is False
               and out.get("broken_row") == spec["v3_broken_row"], json.dumps(out)[:120])


def _cp(run: VectorRun, spec: dict[str, Any]) -> None:
    alpha = spec["alpha"]
    for x, n, expected in spec["cases"]:
        out = run.call(f"python -m harness.stats cp_lower {x} {n} {alpha}")
        got = _rounded(out.get("lb") if out else None, expected)
        run.record(f"cp_lower.{x}/{n}", got == expected, f"got {got}")
        lower_x = str(Decimal(x) - 1)
        out = run.call(f"python -m harness.stats cp_lower {lower_x} {n} {alpha}")
        got = _rounded(out.get("lb") if out else None, expected)
        run.record(f"cp_lower.{x}/{n}.changed_input", got is not None and got != expected, f"got {got}")


def _mcnemar(run: VectorRun, spec: dict[str, Any]) -> None:
    for b, c, expected in spec["cases"]:
        out = run.call(f"python -m harness.stats mcnemar {b} {c}")
        got = _rounded(out.get("p") if out else None, expected)
        run.record(f"mcnemar.{b},{c}", got == expected, f"got {got}")
        out = run.call(f"python -m harness.stats mcnemar {b + 1} {c}")
        got = _rounded(out.get("p") if out else None, expected)
        run.record(f"mcnemar.{b},{c}.changed_input", got is not None and got != expected, f"got {got}")


def _match(run: VectorRun, spec: dict[str, Any]) -> None:
    for i, item in enumerate(spec["cases"], start=1):
        cmd = ("python -m harness.score "
               f"{shlex.quote('/vec/' + item['findings'])} {shlex.quote('/vec/' + item['cases'])}")
        out = run.call(cmd)
        got = out.get("hits") if out else None
        run.record(f"match.{i}", isinstance(got, int) and not isinstance(got, bool) and got == item["hits"],
                   f"got {got}")


def _drill(run: VectorRun, spec: dict[str, Any]) -> None:
    """Lesson drill judge (`tohum/29c`): every simulated brain gets the reference verdicts. The edited
    cases are the changed inputs: a brain's run with its answer key (``tampered_key``) or its transcript
    edited after it."""
    for item in spec["cases"]:
        out = run.call(f"python -m harness.drill judge {shlex.quote('/vec/' + item['file'])}")
        got = (out.get("drill"), out.get("verdicts")) if out else (None, None)
        run.record(f"drill.{item['name']}", got == (item["drill"], item["verdicts"]), json.dumps(got)[:200])


def _same(a: Any, b: Any) -> bool:
    """Equal as JSON values. Python's ``==`` would take ``1`` for ``true`` and ``1.0`` for ``1``; JSON does not."""
    return json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def _gives(out: dict[str, Any] | None, fields: dict[str, Any]) -> bool:
    return out is not None and all(name in out and _same(out[name], value) for name, value in fields.items())


def _shown(out: dict[str, Any] | None, fields: dict[str, Any]) -> str:
    return "no JSON object" if out is None else "got " + json.dumps({k: out[k] for k in fields if k in out})


def _data(run: VectorRun, spec: dict[str, Any]) -> None:
    """The generic data runner (`29d`). A case's command, run from ``referee/`` with its stdin, must print every
    field ``expect`` names with that value; other fields of the line (an argv, a reason) are not compared. Its
    changed input must answer the same fields, and not with ``expect_not``: an answer that ignores the input
    fails there, and so does no answer at all."""
    for case in spec["cases"]:
        out = run.call(case["cmd"], case.get("stdin", "").encode("utf-8"))
        run.record(case["id"], _gives(out, case["expect"]), _shown(out, case["expect"]))
        changed = case["changed"]
        avoid = changed["expect_not"]
        out = run.call(changed["cmd"], changed.get("stdin", "").encode("utf-8"))
        run.record(f"{case['id']}.changed_input",
                   out is not None and all(name in out for name in avoid) and not _gives(out, avoid),
                   _shown(out, avoid))


GROUPS = (("chain", _chain), ("cp_lower", _cp), ("mcnemar", _mcnemar), ("match", _match), ("drill", _drill))
DATA_RUNNER = "data"  # a group of `{cmd, stdin?, fixture, expect, changed: {..., expect_not}}` cases (`29d`)


def _seed(vectors_dir: Path) -> dict[str, Any]:
    return json.loads((vectors_dir / SEED_FILE).read_text(encoding="utf-8"))


def _delivered(group: dict[str, Any], tree: Path | None) -> bool:
    """A data group's interface page (`29f`, `29g`) is all the Founder reads of it. The group applies to a tree whose
    seed carries that page; vectors the referee got before the Founder's seed did are the seed's gap, not a red push.
    Without a tree (a check of the seed alone) nothing is asked of it."""
    page = group.get("interface")
    return tree is None or (isinstance(page, str) and (tree / page).is_file())


def _judges(spec: dict[str, Any], tree: Path | None = None) -> dict[str, Callable[[VectorRun, dict[str, Any]], None]]:
    """Every group the seed has a judge for, in the seed's order: its own judge, or the data runner for a group
    marked as data whose page the tree has. A group with neither cannot run."""
    own = dict(GROUPS)
    judges: dict[str, Callable[[VectorRun, dict[str, Any]], None]] = {}
    for name, group in spec.items():
        if name in own:
            judges[name] = own[name]
        elif isinstance(group, dict) and group.get("runner") == DATA_RUNNER and _delivered(group, tree):
            judges[name] = _data
    return judges


def missing_groups(vectors_dir: Path, done_mf: tuple[int, ...], table: stages.StageTable, *,
                   tree: Path | None = None) -> list[str]:
    """Groups a finished micro-feature owns that the seed has no vectors (or no runner) for yet, or whose interface
    page is not yet in the Founder's seed (``tree``).

    Their expected values come with the seed, computed twice independently (`29a`); the referee never makes them
    up. `decide` warns on a code push and refuses the exit while any is missing.
    """
    judges = _judges(_seed(vectors_dir), tree)
    return [g for g in table.groups_of(done_mf) if g not in judges]


def run_vectors(runner: Runner, vectors_dir: Path, done_mf: tuple[int, ...], timeout_s: int = 120, *,
                table: stages.StageTable | None = None, tree: Path | None = None) -> list[dict]:
    owned = set((table or stages.load(0)).groups_of(done_mf))
    spec = _seed(vectors_dir)
    run = VectorRun(runner, timeout_s)
    for name, judge in _judges(spec, tree).items():
        if name in owned:
            judge(run, spec[name])
    return run.results
