"""runner.deps_npm -- deps.fetch for npm (MF5), against an offline registry mirror.

    python -m runner.deps_npm fetch <package-lock.json> <mirror_dir>
    stdin: {"registry_egress": [...], "install_scripts_required": [...]}

The tarball of resolved https://<host>/<path> is the file <mirror_dir>/<host>/<path>. Tarballs are read in
memory; nothing is written to disk. Prints one JSON line {ok, rejected, artefact, licenses}: exit 0 ok,
1 a package rejected, 2 unusable input ({"ok": false, "error": ...}).

Founder report E200: an install_scripts_required element is an exact lock key or name@version; anything else
(a bare name) is refused as unusable input.
"""
import base64
import hashlib
import io
import json
import os
import re
import sys
import tarfile

GIT_PREFIXES = ("git+", "git:", "github:", "git@")
INSTALL_SCRIPTS = ("preinstall", "install", "postinstall")
NAME_AT_VERSION = re.compile(r"(?:@[^@/\s]+/)?[^@/\s]+@[^@/\s]+")
SKIP = object()


class Unusable(Exception):
    pass


# ---- RFC 8785 canonical JSON (strings, integers, booleans, null, arrays, objects; no floats) ----

_SHORT = {'"': '\\"', "\\": "\\\\", "\b": "\\b", "\f": "\\f", "\n": "\\n", "\r": "\\r", "\t": "\\t"}


def _quote(s: str) -> str:
    out = ['"']
    for ch in s:
        if ch in _SHORT:
            out.append(_SHORT[ch])
        elif ord(ch) < 0x20:
            out.append("\\u%04x" % ord(ch))
        else:
            out.append(ch)
    out.append('"')
    return "".join(out)


def _canon(v) -> str:
    if v is None:
        return "null"
    if v is True:
        return "true"
    if v is False:
        return "false"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, str):
        return _quote(v)
    if isinstance(v, list):
        return "[" + ",".join(_canon(x) for x in v) + "]"
    if isinstance(v, dict):
        keys = sorted(v, key=lambda k: k.encode("utf-16-be"))
        return "{" + ",".join(_quote(k) + ":" + _canon(v[k]) for k in keys) + "}"
    raise TypeError(f"not canonicalisable: {type(v).__name__}")


def canonical(v) -> bytes:
    return _canon(v).encode("utf-8")


# ---- per-package checks ----

def _has_dotdot(target: str) -> bool:
    return any(c == ".." for c in re.split(r"[/\\]", target))


def _is_absolute(target: str) -> bool:
    return target.startswith(("/", "\\")) or re.match(r"[A-Za-z]:", target) is not None


def _mirror_file(mirror: str, resolved: str):
    if not resolved.startswith("https://"):
        return None
    rest = resolved[len("https://"):]
    parts = rest.split("/")
    if len(parts) < 2 or any(c in ("", ".", "..") for c in parts):
        return None
    if any(ch in rest for ch in "\\?#\x00"):
        return None
    return os.path.join(mirror, *parts)


def _sri_ok(integrity, data: bytes) -> bool:
    if not isinstance(integrity, str):
        return False
    digest = base64.b64encode(hashlib.sha512(data).digest()).decode("ascii")
    values = [tok[len("sha512-"):].split("?", 1)[0] for tok in integrity.split() if tok.startswith("sha512-")]
    return bool(values) and all(v == digest for v in values)


def _read_tarball(data: bytes) -> dict:
    """package/package.json and install-script evidence of an npm tarball, read in memory."""
    manifest = None
    scripted = False
    try:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tf:
            for m in tf.getmembers():
                comps = [c for c in m.name.split("/") if c not in ("", ".")]
                if len(comps) != 2:
                    continue
                # npm strips the top directory whatever its name; install evidence is taken under any of
                # them (fail closed), the manifest under package/ as the contract names it.
                if comps[1] == "binding.gyp":
                    scripted = True
                if comps[1] == "package.json" and m.isreg():
                    pj = json.loads(tf.extractfile(m).read().decode("utf-8"))
                    scripts = pj.get("scripts") if isinstance(pj, dict) else None
                    if isinstance(scripts, dict) and any(k in scripts for k in INSTALL_SCRIPTS):
                        scripted = True
                    if comps[0] == "package":
                        manifest = pj
    except (tarfile.TarError, OSError, EOFError, ValueError, UnicodeDecodeError) as e:
        raise Unusable("tarball is not a readable npm package") from e
    if not isinstance(manifest, dict):
        raise Unusable("tarball has no package/package.json object")
    return {"manifest": manifest, "scripted": scripted}


def check_package(path: str, entry: dict, mirror: str, egress: list, marks: set):
    """Return (reason or None, info) for one lock entry; info is SKIP for an in-repo workspace link."""
    resolved = entry.get("resolved")
    res = resolved if isinstance(resolved, str) else ""
    if res.startswith(GIT_PREFIXES):
        return "git_dependency", None
    if res.startswith("file:"):
        return "file_dependency", None
    if entry.get("link") is True:
        if not isinstance(resolved, str) or _is_absolute(resolved) or _has_dotdot(resolved):
            return "file_dependency", None
        return None, SKIP
    if not any(res.startswith(e) for e in egress):
        return "registry_not_allowed", None
    fp = _mirror_file(mirror, res)
    if fp is None or not os.path.isfile(fp):
        return "tarball_missing", None
    try:
        with open(fp, "rb") as f:
            data = f.read()
    except OSError:
        return "tarball_missing", None
    if not _sri_ok(entry.get("integrity"), data):
        return "integrity_mismatch", None
    tb = _read_tarball(data)
    man = tb["manifest"]
    name, version = man.get("name"), man.get("version")
    if tb["scripted"] or entry.get("hasInstallScript") is True:
        ident = f"{name}@{version}" if isinstance(name, str) and isinstance(version, str) else None
        if path not in marks and (ident is None or ident not in marks):
            return "install_script_unmarked", None
    lic = man.get("license")
    return None, {"name": name, "version": version, "license": lic if isinstance(lic, str) else None}


def _validate_marks(marks: list, lock_keys) -> set:
    """E200: each element is an exact lock key (not the root "") or name@version; a bare name is refused."""
    for m in marks:
        if not ((m != "" and m in lock_keys) or NAME_AT_VERSION.fullmatch(m)):
            raise Unusable(f"install_scripts_required element {m!r} is neither a lock key nor name@version")
    return set(marks)


def fetch(lock, mirror: str, request) -> tuple:
    if not isinstance(lock, dict) or lock.get("lockfileVersion") != 3 or not isinstance(lock.get("packages"), dict):
        raise Unusable("lock is not an npm lockfileVersion 3 lock with a packages object")
    if not isinstance(request, dict):
        raise Unusable("stdin is not an object")
    egress = request.get("registry_egress")
    marks = request.get("install_scripts_required")
    if (not isinstance(egress, list) or not all(isinstance(e, str) and e.endswith("/") for e in egress)
            or not isinstance(marks, list) or not all(isinstance(m, str) for m in marks)):
        raise Unusable("stdin needs registry_egress[] (entries ending in '/') and install_scripts_required[]")
    marks = _validate_marks(marks, lock["packages"])
    if not os.path.isdir(mirror):
        raise Unusable("mirror dir is unreadable")
    try:
        os.listdir(mirror)
    except OSError as e:
        raise Unusable("mirror dir is unreadable") from e

    rejected, fetched = [], []
    for path, entry in lock["packages"].items():
        if path == "":
            continue
        if not isinstance(entry, dict):
            raise Unusable(f"lock entry {path!r} is not an object")
        reason, info = check_package(path, entry, mirror, egress, marks)
        if reason:
            rejected.append(f"{reason}:{path}")
        elif info is not SKIP:
            fetched.append((path, entry.get("integrity"), info))
    if rejected:
        return 1, {"ok": False, "rejected": sorted(rejected), "artefact": None, "licenses": None}
    fetched.sort(key=lambda t: t[0])
    address = "sha256:" + hashlib.sha256(canonical(
        [{"integrity": integ, "path": path} for path, integ, _ in fetched])).hexdigest()
    licenses = [{"path": path, **info} for path, _, info in fetched]
    return 0, {"ok": True, "rejected": [], "artefact": address, "licenses": licenses}


def _emit(obj) -> None:
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def main(argv=None, stdin_text=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    try:
        if len(argv) != 3 or argv[0] != "fetch":
            raise Unusable("usage: fetch <package-lock.json> <mirror_dir>")
        try:
            with open(argv[1], "rb") as f:
                lock = json.loads(f.read().decode("utf-8"))
        except (OSError, ValueError, UnicodeDecodeError) as e:
            raise Unusable("lock is unreadable or not JSON") from e
        if stdin_text is None:
            stdin_text = sys.stdin.buffer.read().decode("utf-8")
        try:
            request = json.loads(stdin_text)
        except ValueError as e:
            raise Unusable("stdin is not JSON") from e
        code, out = fetch(lock, argv[2], request)
    except Exception as e:  # unusable input: one line, exit 2
        _emit({"ok": False, "error": str(e) or type(e).__name__})
        return 2
    _emit(out)
    return code


if __name__ == "__main__":
    sys.exit(main())
