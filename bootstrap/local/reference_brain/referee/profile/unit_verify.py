"""MF6 unit.verify, static recipe check: python -m profile.unit_verify check <recipe.json> <policy.json>.

Prints one JSON line {"ok": bool, "reasons": [...]}; exit 0 ok, 1 reasons found, 2 unusable input
(then {"ok": false, "error": ...}). The reasons below are the only ones.
"""
from __future__ import annotations

import json
import re
import sys
from typing import Any

PINNED = re.compile(r"[^@\s]+@sha256:[0-9a-f]{64}")
AGENT_DIRS = {".claude", ".vscode", ".devcontainer"}
AGENT_FILES = {"claude.md", "agents.md", ".mcp.json", ".envrc"}
CMD_FIELDS = ("lint_cmd", "test_cmd", "affected_test_cmd")


class Unusable(Exception):
    pass


def is_agent_config(path: str) -> bool:
    parts = [p for p in path.split("/") if p]
    if not parts:
        return False
    return any(p.lower() in AGENT_DIRS for p in parts) or parts[-1].lower() in AGENT_FILES


def covers(entry: str, path: str) -> bool:
    base = entry.rstrip("/")
    return path == base or path.startswith(base + "/")


def not_plain(entry: str) -> bool:
    return entry.startswith("/") or "\\" in entry or any(p in (".", "..") for p in entry.split("/"))


def verify(recipe: dict[str, Any], operating: dict[str, Any]) -> list[str]:
    inputs = recipe.get("inputs", [])
    if not isinstance(inputs, list) or not all(isinstance(e, str) for e in inputs):
        raise Unusable("recipe: inputs is not a list of strings")
    limits = recipe.get("limits", {})
    if not isinstance(limits, dict):
        raise Unusable("recipe: limits is not an object")

    reasons: set[str] = set()
    image = recipe.get("env_image")
    if not (isinstance(image, str) and PINNED.fullmatch(image)):
        reasons.add("image_not_pinned")
    path = recipe.get("path")
    if not (isinstance(path, str) and any(covers(e, path) for e in inputs)):
        reasons.add("inputs_missing_unit")
    for entry in inputs:
        if not_plain(entry):
            reasons.add(f"input_not_plain:{entry}")
        if is_agent_config(entry):
            reasons.add(f"input_excluded:{entry}")
    for field in CMD_FIELDS:
        cmd = recipe.get(field)
        if not (isinstance(cmd, list) and cmd and all(isinstance(a, str) and a for a in cmd)):
            reasons.add(f"cmd_empty:{field}")
    for key in limits:
        if key not in operating:
            reasons.add(f"limit_key_unknown:{key}")
    if recipe.get("services") != []:
        reasons.add("services_not_empty")
    return sorted(reasons)


def _read_object(path: str, where: str) -> dict[str, Any]:
    try:
        with open(path, "rb") as fh:
            value = json.loads(fh.read().decode("utf-8"))
    except (OSError, ValueError) as exc:
        raise Unusable(f"{where}: {exc}") from exc
    if not isinstance(value, dict):
        raise Unusable(f"{where}: not a JSON object")
    return value


def _emit(obj: dict[str, Any], code: int) -> int:
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()
    return code


def main(args: list[str]) -> int:
    try:
        if len(args) != 3 or args[0] != "check":
            raise Unusable("usage: check <recipe.json> <policy.json>")
        recipe = _read_object(args[1], "recipe")
        operating = _read_object(args[2], "policy").get("operating")
        if not isinstance(operating, dict):
            raise Unusable("policy: operating is not an object")
        reasons = verify(recipe, operating)
    except Unusable as exc:
        return _emit({"ok": False, "error": str(exc)}, 2)
    return _emit({"ok": not reasons, "reasons": reasons}, 1 if reasons else 0)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
