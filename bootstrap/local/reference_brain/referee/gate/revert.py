"""MF13 gate.revert's mechanical cause (tohum/07:34-37, tohum/26:41-44, asama-0/08:20).

    python -m gate.revert cause   (stdin: {"red_tests": [...], "impact": [...], "build_ok": bool,
                                           "lint": {tool: {"before": int, "after": int}}})  -> {"cause": ...}

First rule that holds: build_break (build_ok false); lint_regression (some tool's after > before, per tool);
test_regression (some red test in impact); impact_miss (red tests, none in impact); otherwise unknown.
The revert itself is target.write's revert op.
"""

from __future__ import annotations

import sys
from typing import Any

from ._strict import Unusable, emit, is_int, is_str_list, loads


def cause(signals: dict[str, Any]) -> str:
    if signals["build_ok"] is False:
        return "build_break"
    if any(t["after"] > t["before"] for t in signals["lint"].values()):
        return "lint_regression"
    impact = set(signals["impact"])
    if any(test in impact for test in signals["red_tests"]):
        return "test_regression"
    if signals["red_tests"]:
        return "impact_miss"
    return "unknown"


def _parse(stdin: bytes) -> dict[str, Any]:
    s = loads(stdin)
    ok = (isinstance(s, dict) and is_str_list(s.get("red_tests")) and is_str_list(s.get("impact"))
          and isinstance(s.get("build_ok"), bool) and isinstance(s.get("lint"), dict)
          and all(isinstance(t, dict) and is_int(t.get("before")) and is_int(t.get("after"))
                  for t in s["lint"].values()))
    if not ok:
        raise Unusable("stdin is not {red_tests[], impact[], build_ok, lint{tool: {before, after}}}")
    return s


def main(argv: list[str]) -> None:
    if argv != ["cause"]:
        emit({"cause": None, "error": "usage: cause"}, 2)
    try:
        signals = _parse(sys.stdin.buffer.read())
    except Unusable as exc:
        emit({"cause": None, "error": str(exc)}, 2)
    emit({"cause": cause(signals)}, 0)


if __name__ == "__main__":
    main(sys.argv[1:])
