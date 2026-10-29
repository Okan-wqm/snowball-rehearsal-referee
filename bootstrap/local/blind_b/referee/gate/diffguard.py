"""gate.diffguard -- diff-guard (MF7, asama-0/08 item 1).

    python -m gate.diffguard check <diff.patch> <profile.json> <recipe.json>

Prints {"ok": bool, "reasons": ["<reason>:<path>", ...]} (exit 0 ok, 1 reasons found), or
{"ok": false, "error": ...} with exit 2 on unusable input (unparseable diff, unreadable profile or recipe).
"""
import fnmatch
import json
import re
import sys

from gate.pathrules import covers, is_agent_config

CONFIG_BASENAMES = {
    ".eslintrc", ".eslintrc.json", ".eslintrc.js", ".eslintrc.cjs", ".eslintrc.yml", ".eslintrc.yaml",
    "eslint.config.js", "eslint.config.mjs", "eslint.config.cjs",
    "tsconfig.json",
    "jest.config.js", "jest.config.ts", "vitest.config.js", "vitest.config.ts",
    ".prettierrc", ".prettierrc.json", "biome.json",
}
LOCKFILES = {"package-lock.json", "npm-shrinkwrap.json", "yarn.lock", "pnpm-lock.yaml"}
SYMLINK, SUBMODULE = "120000", "160000"

HUNK = re.compile(r"@@ -\d+(?:,(\d+))? \+\d+(?:,(\d+))? @@.*")
INDEX = re.compile(r"index [0-9a-fA-F]+\.\.[0-9a-fA-F]+(?: ([0-7]{6}))?")
MODE = re.compile(r"[0-7]{6}")
BASE85_LINE = re.compile(r"[A-Za-z][0-9A-Za-z!#$%&()*+\-;<=>?@^_`{|}~]*")
_ESC = {"a": 7, "b": 8, "t": 9, "n": 10, "v": 11, "f": 12, "r": 13, '"': 34, "\\": 92}


class Unparseable(Exception):
    pass


class Unusable(Exception):
    pass


def split_lines(text: str) -> list:
    segs = text.split("\n")
    if segs[-1] == "":
        segs.pop()
    return segs


def _unquote(s: str):
    """Parse one git C-quoted name at the start of s; return (name, rest)."""
    if not s.startswith('"'):
        raise Unparseable("expected a quoted name")
    out = bytearray()
    i = 1
    while i < len(s):
        ch = s[i]
        if ch == '"':
            try:
                return out.decode("utf-8"), s[i + 1:]
            except UnicodeDecodeError as e:
                raise Unparseable("quoted name is not UTF-8") from e
        if ch == "\\":
            nxt = s[i + 1:i + 2]
            if nxt in _ESC:
                out.append(_ESC[nxt])
                i += 2
            elif re.fullmatch(r"[0-7]", nxt or "x") and re.fullmatch(r"[0-7]{3}", s[i + 1:i + 4]):
                out.append(int(s[i + 1:i + 4], 8))
                i += 4
            else:
                raise Unparseable("bad escape in quoted name")
        else:
            out += ch.encode("utf-8")
            i += 1
    raise Unparseable("unterminated quoted name")


def _name(s: str) -> str:
    """A name on a ---/+++/rename/copy line: quoted, or verbatim minus git's trailing TAB."""
    if s.startswith('"'):
        name, rest = _unquote(s)
        if rest not in ("", "\t"):
            raise Unparseable("junk after quoted name")
        return name
    return s[:-1] if s.endswith("\t") else s


def _header_candidates(rest: str) -> list:
    """All (A, B) splits of 'a/A b/B' (either side possibly quoted)."""
    if rest.startswith('"'):
        a, tail = _unquote(rest)
        if not tail.startswith(" "):
            raise Unparseable("bad diff --git header")
        b = _name(tail[1:])
        return [(a, b)] if a.startswith("a/") and b.startswith("b/") else []
    cands = []
    for k, ch in enumerate(rest):
        if ch != " ":
            continue
        a, right = rest[:k], rest[k + 1:]
        if not a.startswith("a/"):
            continue
        b = right
        if right.startswith('"'):
            try:
                b, tail = _unquote(right)
            except Unparseable:
                continue
            if tail != "":
                continue
        if b.startswith("b/"):
            cands.append((a, b))
    return cands


def _parse_hunks(lines, i):
    n = len(lines)
    if i >= n or not lines[i].startswith("@@"):
        raise Unparseable(f"line {i + 1}: expected a hunk after ---/+++")
    while i < n and lines[i].startswith("@@"):
        m = HUNK.fullmatch(lines[i])
        if not m:
            raise Unparseable(f"line {i + 1}: bad hunk header")
        old = int(m.group(1)) if m.group(1) is not None else 1
        new = int(m.group(2)) if m.group(2) is not None else 1
        i += 1
        while old > 0 or new > 0:
            if i >= n:
                raise Unparseable("truncated hunk")
            ln = lines[i]
            if ln.startswith("\\"):
                i += 1
                continue
            tag = ln[:1]
            if tag == " " or ln == "":
                old, new = old - 1, new - 1
            elif tag == "-":
                old -= 1
            elif tag == "+":
                new -= 1
            else:
                raise Unparseable(f"line {i + 1}: unexpected line inside a hunk")
            if old < 0 or new < 0:
                raise Unparseable(f"line {i + 1}: hunk longer than its header")
            i += 1
        while i < n and lines[i].startswith("\\"):
            i += 1
    return i


def _parse_binary(lines, i):
    n = len(lines)
    while i < n and not lines[i].startswith("diff --git "):
        ln = lines[i]
        if not (ln == "" or re.fullmatch(r"(literal|delta) \d+", ln) or BASE85_LINE.fullmatch(ln)):
            raise Unparseable(f"line {i + 1}: bad binary patch line")
        i += 1
    return i


def parse(text: str) -> list:
    """Blocks of a unified git diff: [{"paths": [...], "modes": {...}}]. Raises Unparseable."""
    lines = split_lines(text)
    blocks = []
    i, n = 0, len(lines)
    while i < n:
        line = lines[i]
        if not line.startswith("diff --git "):
            raise Unparseable(f"line {i + 1}: expected 'diff --git'")
        cands = _header_candidates(line[len("diff --git "):])
        if not cands:
            raise Unparseable(f"line {i + 1}: bad diff --git header")
        i += 1
        modes, ext = set(), {}
        while i < n:
            ln = lines[i]
            if ln.startswith(("new file mode ", "new mode ", "old mode ", "deleted file mode ")):
                mode = ln.rsplit(" ", 1)[1]
                if not MODE.fullmatch(mode):
                    raise Unparseable(f"line {i + 1}: bad mode")
                if ln.startswith(("new file mode ", "new mode ")):
                    modes.add(mode)
            elif ln.startswith("index "):
                m = INDEX.fullmatch(ln)
                if not m:
                    raise Unparseable(f"line {i + 1}: bad index line")
                if m.group(1):
                    modes.add(m.group(1))
            elif ln.startswith(("rename from ", "rename to ", "copy from ", "copy to ")):
                word, direction, value = ln.split(" ", 2)
                ext[f"{word} {direction}"] = _name(value)
            elif re.fullmatch(r"(similarity|dissimilarity) index \d+%", ln):
                pass
            elif ln.startswith("Binary files ") and ln.endswith(" differ"):
                pass
            else:
                break
            i += 1
        old_name = new_name = None
        if i < n and lines[i].startswith("--- "):
            if i + 1 >= n or not lines[i + 1].startswith("+++ "):
                raise Unparseable(f"line {i + 1}: '---' without '+++'")
            old_name, new_name = _name(lines[i][4:]), _name(lines[i + 1][4:])
            i = _parse_hunks(lines, i + 2)
        elif i < n and lines[i] == "GIT binary patch":
            i = _parse_binary(lines, i + 1)
        if i < n and not lines[i].startswith("diff --git "):
            raise Unparseable(f"line {i + 1}: unexpected line after a block")

        def consistent(ab):
            a, b = ab[0][2:], ab[1][2:]
            if old_name not in (None, "/dev/null") and old_name != "a/" + a:
                return False
            if new_name not in (None, "/dev/null") and new_name != "b/" + b:
                return False
            for key, want in (("rename from", a), ("copy from", a), ("rename to", b), ("copy to", b)):
                if key in ext and ext[key] != want:
                    return False
            return True

        good = [c for c in cands if consistent(c)]
        if len(good) > 1:
            good = [c for c in good if c[0][2:] == c[1][2:]]
        if len(good) != 1:
            raise Unparseable("cannot tell the block's paths apart")
        a, b = good[0][0][2:], good[0][1][2:]
        # A block changes B; a deletion changes A (== B in git's header); a rename changes both.
        # A copy leaves its source untouched. A != B without rename lines is checked on both (fail closed).
        paths = [b] if ("copy to" in ext or "copy from" in ext) else sorted({a, b})
        blocks.append({"paths": paths, "modes": modes})
    return blocks


def _path_reasons(path: str, modes: set, profile: dict, recipe: dict) -> list:
    out = []
    base = path.rsplit("/", 1)[-1]
    if SYMLINK in modes:
        out.append("symlink")
    if SUBMODULE in modes:
        out.append("submodule")
    if path.startswith("/") or ".." in path.split("/"):
        out.append("path_escape")
    if any(covers(e, path) for e in profile["security_paths"]):
        out.append("security_path")
    if any(covers(e, path) for e in profile["excluded_dirs"]):
        out.append("excluded_path")
    if is_agent_config(path):
        out.append("agent_config")
    if base in CONFIG_BASENAMES or fnmatch.fnmatchcase(base, "tsconfig.*.json") or covers(".github/", path):
        out.append("config")
    if base == "package.json":
        out.append("manifest")
    if base in LOCKFILES:
        out.append("lockfile")
    if base == ".gitattributes":
        out.append("gitattributes")
    if not any(covers(e, path) for e in recipe["inputs"]):
        out.append("outside_inputs")
    return [f"{r}:{path}" for r in out]


def reasons(blocks: list, profile: dict, recipe: dict) -> list:
    found = set()
    for blk in blocks:
        for path in blk["paths"]:
            found.update(_path_reasons(path, blk["modes"], profile, recipe))
    return sorted(found)


def _load_json(path: str, what: str):
    try:
        with open(path, "rb") as f:
            return json.loads(f.read().decode("utf-8"))
    except (OSError, ValueError, UnicodeDecodeError) as e:
        raise Unusable(f"{what} is unreadable or not JSON") from e


def _str_list(obj, key, what):
    v = obj.get(key) if isinstance(obj, dict) else None
    if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
        raise Unusable(f"{what}.{key} must be a list of strings")
    return v


def _emit(obj) -> None:
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    try:
        if len(argv) != 4 or argv[0] != "check":
            raise Unusable("usage: check <diff.patch> <profile.json> <recipe.json>")
        try:
            with open(argv[1], "rb") as f:
                text = f.read().decode("utf-8")
        except (OSError, UnicodeDecodeError) as e:
            raise Unusable("diff is unreadable") from e
        blocks = parse(text)
        prof = _load_json(argv[2], "profile")
        rec = _load_json(argv[3], "recipe")
        profile = {"security_paths": _str_list(prof, "security_paths", "profile"),
                   "excluded_dirs": _str_list(prof, "excluded_dirs", "profile")}
        recipe = {"inputs": _str_list(rec, "inputs", "recipe")}
        found = reasons(blocks, profile, recipe)
    except Exception as e:  # unusable input: one line, exit 2
        _emit({"ok": False, "error": str(e) or type(e).__name__})
        return 2
    _emit({"ok": not found, "reasons": found})
    return 0 if not found else 1


if __name__ == "__main__":
    sys.exit(main())
