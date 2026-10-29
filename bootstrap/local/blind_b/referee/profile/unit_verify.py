"""profile.unit_verify -- static unit recipe check (MF6; the run-based 3/3 check is not here).

    python -m profile.unit_verify check <recipe.json> <policy.json>

Prints {"ok": bool, "reasons": [str]} (exit 0 ok, 1 reasons found); exit 2 on unusable input.
"""
import json
import re
import sys

from profile.pathrules import covers, is_agent_config

PINNED_IMAGE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/:-]*@sha256:[0-9a-f]{64}")
CMD_FIELDS = ("lint_cmd", "test_cmd", "affected_test_cmd")


class Unusable(Exception):
    pass


def _not_plain(entry: str) -> bool:
    return entry.startswith("/") or "\\" in entry or any(c in (".", "..") for c in entry.split("/"))


def _cmd_bad(value) -> bool:
    return (not isinstance(value, list) or not value
            or any(not isinstance(x, str) or x == "" for x in value))


def reasons(recipe: dict, operating: dict) -> list:
    out = set()
    image = recipe.get("env_image")
    if not (isinstance(image, str) and PINNED_IMAGE.fullmatch(image)):
        out.add("image_not_pinned")

    path = recipe.get("path")
    inputs = recipe.get("inputs", [])
    if not isinstance(path, str):
        raise Unusable("recipe.path must be a string")
    if not isinstance(inputs, list) or not all(isinstance(x, str) for x in inputs):
        raise Unusable("recipe.inputs must be a list of strings")
    if not any(covers(e, path) for e in inputs):
        out.add("inputs_missing_unit")
    for e in inputs:
        if _not_plain(e):
            out.add("input_not_plain:" + e)
        if is_agent_config(e):
            out.add("input_excluded:" + e)

    for field in CMD_FIELDS:
        if _cmd_bad(recipe.get(field)):
            out.add("cmd_empty:" + field)

    limits = recipe.get("limits", {})
    if not isinstance(limits, dict):
        raise Unusable("recipe.limits must be an object")
    for key in limits:
        if key not in operating:
            out.add("limit_key_unknown:" + key)

    if recipe.get("services", None) != []:
        out.add("services_not_empty")
    return sorted(out)


def _load(path: str, what: str):
    try:
        with open(path, "rb") as f:
            return json.loads(f.read().decode("utf-8"))
    except (OSError, ValueError, UnicodeDecodeError) as e:
        raise Unusable(f"{what} is unreadable or not JSON") from e


def _emit(obj) -> None:
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    try:
        if len(argv) != 3 or argv[0] != "check":
            raise Unusable("usage: check <recipe.json> <policy.json>")
        recipe = _load(argv[1], "recipe")
        policy = _load(argv[2], "policy")
        if not isinstance(recipe, dict):
            raise Unusable("recipe is not an object")
        if not isinstance(policy, dict) or not isinstance(policy.get("operating"), dict):
            raise Unusable("policy has no operating object")
        found = reasons(recipe, policy["operating"])
    except Exception as e:
        _emit({"ok": False, "error": str(e) or type(e).__name__})
        return 2
    _emit({"ok": not found, "reasons": found})
    return 0 if not found else 1


if __name__ == "__main__":
    sys.exit(main())
