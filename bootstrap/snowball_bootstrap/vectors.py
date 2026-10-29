"""Apply the seed vectors (`tohum/29a`) to the founder's code through the fixed interface.

A vector group applies once the micro-feature that owns it is declared done. Every vector is
checked twice: the right input must give the expected answer, and a changed input must not.
"""

from __future__ import annotations

import json
import shlex
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from .container import Runner

CWD = "referee"


def _last_json(stdout: bytes) -> dict[str, Any] | None:
    for line in reversed(stdout.decode("utf-8", "replace").splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
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
    def __init__(self, runner: Runner, timeout_s: int):
        self.runner = runner
        self.timeout_s = timeout_s
        self.results: list[dict[str, Any]] = []
        self.fault = ""

    def call(self, cmd: str, stdin: bytes = b"") -> dict[str, Any] | None:
        for _ in range(2):  # a container the host killed under load answers nothing: ask again before blaming the judge
            res = self.runner.run(cmd, cwd=CWD, stdin=stdin, timeout_s=self.timeout_s)
            if not res.timed_out and res.stdout.strip():
                self.fault = ""
                return _last_json(res.stdout)
        tail = res.stderr[-100:].decode("utf-8", "replace") if isinstance(res.stderr, bytes) else ""
        self.fault = f"no answer: exit {res.exit_code}{', timed out' if res.timed_out else ''} {tail}".strip()
        return None

    def record(self, vid: str, ok: bool, detail: str = "") -> None:
        if not ok and self.fault:
            detail = f"{detail} | {self.fault}"
            self.fault = ""
        self.results.append({"id": vid, "ok": ok, "detail": detail[:200]})


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
    """Lesson drill judge (`tohum/29c`): every simulated brain gets the reference verdicts. The
    ``tampered_key`` case is the changed input of ``learner``: same run, answer key edited after it."""
    for item in spec["cases"]:
        out = run.call(f"python -m harness.drill judge {shlex.quote('/vec/' + item['file'])}")
        got = (out.get("drill"), out.get("verdicts")) if out else (None, None)
        run.record(f"drill.{item['name']}", got == (item["drill"], item["verdicts"]), json.dumps(got)[:200])


GROUPS = (("chain", _chain), ("cp_lower", _cp), ("mcnemar", _mcnemar), ("match", _match), ("drill", _drill))


def run_vectors(runner: Runner, vectors_dir: Path, done_mf: tuple[int, ...], timeout_s: int = 120) -> list[dict]:
    spec = json.loads((vectors_dir / "vectors.json").read_text(encoding="utf-8"))
    run = VectorRun(runner, timeout_s)
    for name, fn in GROUPS:
        group = spec[name]
        if group["mf"] in done_mf:
            fn(run, group)
    return run.results
