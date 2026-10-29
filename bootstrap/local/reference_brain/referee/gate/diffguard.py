"""MF7 gate.diffguard (asama-0/08 item 1): python -m gate.diffguard check <diff.patch> <profile.json> <recipe.json>.

Prints one JSON line {"ok": bool, "reasons": ["<reason>:<path>", ...]}; exit 0 ok, 1 reasons found,
2 unusable input (then {"ok": false, "error": ...}). Every applicable reason of every changed path is
reported, the path as written in the diff (no normalisation).
"""
from __future__ import annotations

import fnmatch
import json
import re
import sys
from typing import Any

AGENT_DIRS = {".claude", ".vscode", ".devcontainer"}
AGENT_FILES = {"claude.md", "agents.md", ".mcp.json", ".envrc"}
CONFIG_NAMES = {".eslintrc", ".eslintrc.json", ".eslintrc.js", ".eslintrc.cjs", ".eslintrc.yml", ".eslintrc.yaml",
                "eslint.config.js", "eslint.config.mjs", "eslint.config.cjs", "tsconfig.json",
                "jest.config.js", "jest.config.ts", "vitest.config.js", "vitest.config.ts",
                ".prettierrc", ".prettierrc.json", "biome.json"}
LOCKFILES = {"package-lock.json", "npm-shrinkwrap.json", "yarn.lock", "pnpm-lock.yaml"}
EXT_HEADERS = ("old mode ", "new mode ", "deleted file mode ", "new file mode ", "copy from ", "copy to ",
               "rename from ", "rename to ", "similarity index ", "dissimilarity index ", "index ")
HUNK = re.compile(r"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
_ESCAPES = {"a": 7, "b": 8, "t": 9, "n": 10, "v": 11, "f": 12, "r": 13, '"': 34, "\\": 92}


class Unusable(Exception):
    pass


# --- path rules -------------------------------------------------------------------------------------

def is_agent_config(path: str) -> bool:
    parts = [p for p in path.split("/") if p]
    if not parts:
        return False
    return any(p.lower() in AGENT_DIRS for p in parts) or parts[-1].lower() in AGENT_FILES


def covers(entry: str, path: str) -> bool:
    base = entry.rstrip("/")
    return path == base or path.startswith(base + "/")


def path_reasons(path: str, modes: set[str], profile: dict[str, list[str]], inputs: list[str]) -> set[str]:
    base = path.rsplit("/", 1)[-1]
    found = set()
    if "120000" in modes:
        found.add("symlink")
    if "160000" in modes:
        found.add("submodule")
    if path.startswith("/") or ".." in path.split("/"):
        found.add("path_escape")
    if any(covers(e, path) for e in profile["security_paths"]):
        found.add("security_path")
    if any(covers(e, path) for e in profile["excluded_dirs"]):
        found.add("excluded_path")
    if is_agent_config(path):
        found.add("agent_config")
    if base in CONFIG_NAMES or fnmatch.fnmatchcase(base, "tsconfig.*.json") or path.startswith(".github/"):
        found.add("config")
    if base == "package.json":
        found.add("manifest")
    if base in LOCKFILES:
        found.add("lockfile")
    if base == ".gitattributes":
        found.add("gitattributes")
    if not any(covers(e, path) for e in inputs):
        found.add("outside_inputs")
    return {f"{reason}:{path}" for reason in found}


# --- git diff parsing -------------------------------------------------------------------------------

def _unquote(text: str) -> tuple[str, str]:
    """Parse a C-quoted git path at the start of text; return (path, rest)."""
    assert text.startswith('"')
    out = bytearray()
    i = 1
    while i < len(text):
        ch = text[i]
        if ch == '"':
            return out.decode("utf-8", "surrogateescape"), text[i + 1:]
        if ch == "\\":
            nxt = text[i + 1:i + 2]
            if nxt in _ESCAPES:
                out.append(_ESCAPES[nxt])
                i += 2
                continue
            if re.fullmatch(r"[0-3][0-7]{2}", text[i + 1:i + 4]):
                out.append(int(text[i + 1:i + 4], 8))
                i += 4
                continue
            raise Unusable(f"bad escape in quoted path {text!r}")
        out += ch.encode("utf-8", "surrogateescape")
        i += 1
    raise Unusable(f"unterminated quoted path {text!r}")


def _path_token(text: str, prefix: str) -> str:
    """'a/X' or '"a/X"' (whole token) -> X."""
    if text.startswith('"'):
        path, rest = _unquote(text)
        if rest:
            raise Unusable(f"trailing text after quoted path {text!r}")
    else:
        path = text
    if not path.startswith(prefix):
        raise Unusable(f"path {path!r} lacks the {prefix!r} prefix")
    return path[len(prefix):]


def _header_paths(rest: str) -> tuple[str, str] | None:
    """Paths of 'diff --git a/A b/B'; None when the unquoted header is ambiguous."""
    if rest.startswith('"'):
        a, tail = _unquote(rest)
        if not tail.startswith(" ") or not a.startswith("a/"):
            raise Unusable(f"bad diff header {rest!r}")
        return a[2:], _path_token(tail[1:], "b/")
    if ' "' in rest:
        a, b = rest.split(' "', 1)
        return _path_token(a, "a/"), _path_token('"' + b, "b/")
    n = (len(rest) - 5) // 2
    if len(rest) % 2 == 1 and rest.startswith("a/") and rest[2 + n:5 + n] == " b/" and rest[2:2 + n] == rest[5 + n:]:
        return rest[2:2 + n], rest[5 + n:]
    if rest.count(" b/") == 1:
        a, b = rest.split(" b/", 1)
        return _path_token(a, "a/"), b
    return None


def _file_line_path(text: str, prefix: str) -> str | None:
    if text.endswith("\t"):
        text = text[:-1]
    if text == "/dev/null":
        return None
    return _path_token(text, prefix)


def parse_diff(text: str) -> list[tuple[list[str], set[str]]]:
    """[(changed paths, modes)] per 'diff --git' block; Unusable on anything that is not a git diff."""
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    starts = [i for i, line in enumerate(lines) if line.startswith("diff --git ")]
    for i, line in enumerate(lines):
        if line.startswith("diff ") and not line.startswith("diff --git "):
            raise Unusable(f"line {i + 1}: not a git diff header")
    if any(line.strip() for line in lines[:starts[0] if starts else len(lines)]):
        raise Unusable("text before the first 'diff --git' header")
    blocks = []
    for k, start in enumerate(starts):
        end = starts[k + 1] if k + 1 < len(starts) else len(lines)
        blocks.append(_parse_block(lines[start:end], start + 1))
    return blocks


def _parse_block(block: list[str], lineno: int) -> tuple[list[str], set[str]]:
    header = _header_paths(block[0][len("diff --git "):])
    modes: set[str] = set()
    rename_from = rename_to = None
    deleted = False
    minus = plus = None
    i = 1
    while i < len(block) and block[i].startswith(EXT_HEADERS):
        line = block[i]
        if line.startswith(("new file mode ", "new mode ")):
            modes.add(line.rsplit(" ", 1)[1])
        elif line.startswith("deleted file mode "):
            deleted = True
        elif line.startswith("index "):
            tokens = line.split(" ")
            if len(tokens) == 3:
                modes.add(tokens[2])
        elif line.startswith("rename from "):
            rename_from = _path_token(line[len("rename from "):], "")
        elif line.startswith("rename to "):
            rename_to = _path_token(line[len("rename to "):], "")
        i += 1
    if i < len(block) and (block[i].startswith("Binary files ") or block[i] == "GIT binary patch"):
        if any(l.startswith(("--- ", "+++ ", "@@ ")) for l in block[i + 1:]):
            raise Unusable(f"block at line {lineno}: text patch after a binary patch")
        i = len(block)
    if i < len(block) and block[i].startswith("--- "):
        if i + 1 >= len(block) or not block[i + 1].startswith("+++ "):
            raise Unusable(f"block at line {lineno}: '---' without '+++'")
        minus = _file_line_path(block[i][4:], "a/")
        plus = _file_line_path(block[i + 1][4:], "b/")
        i += 2
    while i < len(block):
        m = HUNK.match(block[i])
        if m is None:
            if block[i] == "" or block[i].startswith("\\"):
                i += 1
                continue
            raise Unusable(f"line {lineno + i}: unexpected line in a git diff block")
        old = int(m.group(2)) if m.group(2) is not None else 1
        new = int(m.group(4)) if m.group(4) is not None else 1
        i += 1
        while (old > 0 or new > 0) and i < len(block):
            line = block[i]
            tag = line[:1]
            if tag in (" ", ""):
                old, new = old - 1, new - 1
            elif tag == "-":
                old -= 1
            elif tag == "+":
                new -= 1
            elif tag != "\\":
                raise Unusable(f"line {lineno + i}: bad hunk line")
            i += 1
        if old != 0 or new != 0:
            raise Unusable(f"hunk ending at line {lineno + i}: line counts do not match")

    if header is None:
        a = minus if minus is not None else rename_from
        b = plus if plus is not None else rename_to
        if a is None and b is None:
            raise Unusable(f"block at line {lineno}: ambiguous paths")
        header = (a if a is not None else b, b if b is not None else a)
    if rename_from is not None or rename_to is not None:
        paths = [p for p in (rename_from, rename_to) if p is not None]
    elif deleted:
        paths = [header[0]]
    else:
        paths = [header[1]]
    return paths, modes


# --- command ----------------------------------------------------------------------------------------

def _read_object(path: str, where: str, keys: tuple[str, ...]) -> dict[str, Any]:
    try:
        with open(path, "rb") as fh:
            value = json.loads(fh.read().decode("utf-8"))
    except (OSError, ValueError) as exc:
        raise Unusable(f"{where}: {exc}") from exc
    if not isinstance(value, dict):
        raise Unusable(f"{where}: not a JSON object")
    for key in keys:
        if not isinstance(value.get(key), list) or not all(isinstance(v, str) for v in value[key]):
            raise Unusable(f"{where}: {key} is not a list of strings")
    return value


def _emit(obj: dict[str, Any], code: int) -> int:
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()
    return code


def main(args: list[str]) -> int:
    try:
        if len(args) != 4 or args[0] != "check":
            raise Unusable("usage: check <diff.patch> <profile.json> <recipe.json>")
        try:
            with open(args[1], "rb") as fh:
                text = fh.read().decode("utf-8", "surrogateescape")
        except OSError as exc:
            raise Unusable(f"diff: {exc}") from exc
        profile = _read_object(args[2], "profile", ("security_paths", "excluded_dirs"))
        inputs = _read_object(args[3], "recipe", ("inputs",))["inputs"]
        reasons: set[str] = set()
        for paths, modes in parse_diff(text):
            for path in paths:
                reasons |= path_reasons(path, modes, profile, inputs)
    except Unusable as exc:
        return _emit({"ok": False, "error": str(exc)}, 2)
    ordered = sorted(reasons)
    return _emit({"ok": not ordered, "reasons": ordered}, 1 if ordered else 0)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
