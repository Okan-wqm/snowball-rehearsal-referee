"""MF4 profile.derive (static).

  python -m profile.derive derive <tree.tar.gz> <operator.json>
      -> {"languages", "unit_candidates", "security_paths", "excluded_paths"}; exit 0, 2 unusable input
  python -m profile.derive check <tree.tar.gz> <operator.json> <proposal.json>
      -> {"accepted", "reasons"}; exit 0 accepted, 1 rejected, 2 unusable input

The tree is read in memory from the gzip tar; nothing is written to disk.
"""
from __future__ import annotations

import io
import json
import posixpath
import sys
import tarfile
import zlib
from typing import Any

AGENT_DIRS = {".claude", ".vscode", ".devcontainer"}
AGENT_FILES = {"claude.md", "agents.md", ".mcp.json", ".envrc"}
LANGUAGES = {".py": "python", ".js": "javascript", ".mjs": "javascript", ".cjs": "javascript",
             ".ts": "typescript", ".tsx": "typescript", ".mts": "typescript", ".cts": "typescript"}
PROFILE_LISTS = ("languages", "unit_candidates", "security_paths", "excluded_paths")


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


def is_excluded(path: str, excluded_paths: list[str]) -> bool:
    return is_agent_config(path) or any(covers(e, path) for e in excluded_paths)


def read_tree(path: str) -> list[str]:
    try:
        with open(path, "rb") as fh:
            data = fh.read()
        files: set[str] = set()
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
            for member in tar:
                if member.isdir():
                    continue  # a directory exists iff some file lies under it
                name = member.name
                parts = name.split("/")
                if name.startswith("/") or any(p in ("", ".", "..") for p in parts):
                    raise Unusable(f"tree member {name!r} is not a relative POSIX path")
                files.add(name)
    except (OSError, tarfile.TarError, EOFError, zlib.error) as exc:
        raise Unusable(f"tree: {exc}") from exc
    return sorted(files)


def _str_list(obj: dict[str, Any], key: str, where: str) -> list[str]:
    value = obj.get(key)
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise Unusable(f"{where}: {key} is not a list of strings")
    return value


def read_json_object(path: str, where: str) -> dict[str, Any]:
    try:
        with open(path, "rb") as fh:
            value = json.loads(fh.read().decode("utf-8"))
    except (OSError, ValueError) as exc:
        raise Unusable(f"{where}: {exc}") from exc
    if not isinstance(value, dict):
        raise Unusable(f"{where}: not a JSON object")
    return value


def derive(files: list[str], operator: dict[str, Any]) -> dict[str, list[str]]:
    keywords = [k.lower() for k in _str_list(operator, "security_keywords", "operator")]
    excluded_entries = _str_list(operator, "excluded_paths", "operator")
    candidates = _str_list(operator, "unit_candidates", "operator")

    excluded = [f for f in files if is_excluded(f, excluded_entries)]
    kept = [f for f in files if not is_excluded(f, excluded_entries)]
    languages = {LANGUAGES[ext] for ext in (posixpath.splitext(posixpath.basename(f))[1] for f in kept)
                 if ext in LANGUAGES}
    security = [f for f in kept if any(k in f.lower() for k in keywords)]
    units = [c for c in candidates
             if not is_excluded(c, excluded_entries) and any(covers(c, f) for f in files)]
    return {"languages": sorted(languages), "unit_candidates": units,
            "security_paths": sorted(security), "excluded_paths": sorted(excluded)}


def check(derived: dict[str, list[str]], proposal: dict[str, Any]) -> list[str]:
    prop = {key: _str_list(proposal, key, "proposal") for key in PROFILE_LISTS}
    reasons = []
    if set(prop["languages"]) != set(derived["languages"]):
        reasons.append("differs:languages")
    if prop["unit_candidates"] != derived["unit_candidates"]:
        reasons.append("differs:unit_candidates")
    for key in ("security_paths", "excluded_paths"):
        if not set(derived[key]) <= set(prop[key]):
            reasons.append(f"narrows:{key}")
    return sorted(reasons)


def _emit(obj: dict[str, Any], code: int) -> int:
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()
    return code


def main(args: list[str]) -> int:
    try:
        if len(args) == 3 and args[0] == "derive":
            derived = derive(read_tree(args[1]), read_json_object(args[2], "operator"))
            return _emit(derived, 0)
        if len(args) == 4 and args[0] == "check":
            derived = derive(read_tree(args[1]), read_json_object(args[2], "operator"))
            reasons = check(derived, read_json_object(args[3], "proposal"))
            return _emit({"accepted": not reasons, "reasons": reasons}, 1 if reasons else 0)
        raise Unusable("usage: derive <tree.tar.gz> <operator.json> | check <tree> <operator> <proposal>")
    except Unusable as exc:
        if args[:1] == ["check"]:
            return _emit({"accepted": False, "error": str(exc)}, 2)
        return _emit({"error": str(exc)}, 2)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
