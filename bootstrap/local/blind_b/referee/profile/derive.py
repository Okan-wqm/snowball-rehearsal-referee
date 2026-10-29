"""profile.derive -- static profile derivation (MF4).

    python -m profile.derive derive <tree.tar.gz> <operator.json>
    python -m profile.derive check  <tree.tar.gz> <operator.json> <proposal.json>

derive prints {languages, unit_candidates, security_paths, excluded_paths} (exit 0; 2 unusable).
check prints {accepted, reasons} (exit 0 accepted, 1 rejected, 2 unusable). One JSON line on every exit.
Nothing is written to disk; tar members are read in memory.
"""
import io
import json
import posixpath
import sys
import tarfile

from profile.pathrules import covers, is_agent_config

LANGUAGES = {
    ".py": "python",
    ".js": "javascript", ".mjs": "javascript", ".cjs": "javascript",
    ".ts": "typescript", ".tsx": "typescript", ".mts": "typescript", ".cts": "typescript",
}
PROPOSAL_FIELDS = ("languages", "unit_candidates", "security_paths", "excluded_paths")


class Unusable(Exception):
    pass


def _str_list(obj, key, where):
    v = obj.get(key) if isinstance(obj, dict) else None
    if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
        raise Unusable(f"{where}: {key} must be a list of strings")
    return v


def read_tree(data: bytes) -> set:
    """Relative POSIX paths of the regular files of a gzip tar; directory entries are ignored."""
    files = set()
    try:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tf:
            for m in tf.getmembers():
                if m.isdir():
                    continue
                if not m.isreg():
                    raise Unusable(f"member {m.name!r} is not a regular file")
                name = m.name
                comps = name.split("/")
                if (name == "" or name.startswith("/") or "\\" in name
                        or any(c in ("", ".", "..") for c in comps)):
                    raise Unusable(f"member name {name!r} is not a plain relative POSIX path")
                files.add(name)
    except (tarfile.TarError, OSError, EOFError) as e:
        raise Unusable("tree is not a readable gzip tar") from e
    return files


def read_operator(data: bytes) -> dict:
    try:
        op = json.loads(data.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as e:
        raise Unusable("operator.json is not JSON") from e
    if not isinstance(op, dict):
        raise Unusable("operator.json is not an object")
    return {k: _str_list(op, k, "operator.json")
            for k in ("security_keywords", "excluded_paths", "unit_candidates")}


def is_excluded(path: str, excluded_entries) -> bool:
    return is_agent_config(path) or any(covers(e, path) for e in excluded_entries)


def _language(path: str):
    suffix = posixpath.splitext(posixpath.basename(path))[1]
    return LANGUAGES.get(suffix)


def derive(files, operator: dict) -> dict:
    excl_entries = operator["excluded_paths"]
    excluded = sorted(p for p in files if is_excluded(p, excl_entries))
    kept = sorted(p for p in files if not is_excluded(p, excl_entries))
    languages = sorted({lang for lang in map(_language, kept) if lang})
    keywords = [k.lower() for k in operator["security_keywords"]]
    security = sorted(p for p in kept if any(k in p.lower() for k in keywords))
    candidates = [c for c in operator["unit_candidates"]
                  if not is_excluded(c, excl_entries) and any(covers(c, f) for f in files)]
    return {"languages": languages, "unit_candidates": candidates,
            "security_paths": security, "excluded_paths": excluded}


def check(derived: dict, proposal: dict) -> list:
    reasons = []
    if set(proposal["languages"]) != set(derived["languages"]):
        reasons.append("differs:languages")
    if list(proposal["unit_candidates"]) != list(derived["unit_candidates"]):
        reasons.append("differs:unit_candidates")
    for field in ("security_paths", "excluded_paths"):
        if not set(derived[field]) <= set(proposal[field]):
            reasons.append("narrows:" + field)
    return sorted(reasons)


def read_proposal(data: bytes) -> dict:
    try:
        prop = json.loads(data.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as e:
        raise Unusable("proposal is not JSON") from e
    if not isinstance(prop, dict):
        raise Unusable("proposal is not an object")
    return {k: _str_list(prop, k, "proposal") for k in PROPOSAL_FIELDS}


def _read(path: str) -> bytes:
    try:
        with open(path, "rb") as f:
            return f.read()
    except OSError as e:
        raise Unusable(f"unreadable file {path}") from e


def _emit(obj) -> None:
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    verb = argv[0] if argv else None
    try:
        if verb == "derive" and len(argv) == 3:
            _emit(derive(read_tree(_read(argv[1])), read_operator(_read(argv[2]))))
            return 0
        if verb == "check" and len(argv) == 4:
            derived = derive(read_tree(_read(argv[1])), read_operator(_read(argv[2])))
            reasons = check(derived, read_proposal(_read(argv[3])))
            _emit({"accepted": not reasons, "reasons": reasons})
            return 0 if not reasons else 1
        raise Unusable("usage: derive <tree.tar.gz> <operator.json> | check <tree> <operator> <proposal>")
    except Exception as e:  # unusable input: one line, exit 2
        out = {"accepted": False} if verb == "check" else {}
        out["error"] = str(e) or type(e).__name__
        _emit(out)
        return 2


if __name__ == "__main__":
    sys.exit(main())
