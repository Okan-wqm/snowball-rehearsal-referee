"""MF5 deps.fetch (npm): python -m runner.deps_npm fetch <package-lock.json> <mirror_dir>.

stdin: {"registry_egress": [...], "install_scripts_required": ["name@version", ...]}.
The tarball of resolved https://<host>/<path> is the file <mirror_dir>/<host>/<path> (offline mirror).
Prints one JSON line {ok, rejected, artefact, licenses}; exit 0 ok, 1 a package rejected, 2 unusable
input. Tarballs are read in memory; nothing is written.
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import sys
import tarfile
import zlib
from typing import Any

INSTALL_HOOKS = ("preinstall", "install", "postinstall")


class Unusable(Exception):
    pass


# --- RFC 8785 canonical JSON (strings, integers, booleans, null, arrays, objects) -------------------

def _canon_str(s: str) -> str:
    out = ['"']
    for ch in s:
        o = ord(ch)
        if ch == '"':
            out.append('\\"')
        elif ch == "\\":
            out.append("\\\\")
        elif ch == "\b":
            out.append("\\b")
        elif ch == "\f":
            out.append("\\f")
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\r":
            out.append("\\r")
        elif ch == "\t":
            out.append("\\t")
        elif o < 0x20 or 0xD800 <= o <= 0xDFFF:
            out.append("\\u%04x" % o)
        else:
            out.append(ch)
    out.append('"')
    return "".join(out)


def canonical(value: Any) -> str:
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        return _canon_str(value)
    if isinstance(value, list):
        return "[" + ",".join(canonical(v) for v in value) + "]"
    if isinstance(value, dict):
        keys = sorted(value, key=lambda k: k.encode("utf-16-be"))
        return "{" + ",".join(_canon_str(k) + ":" + canonical(value[k]) for k in keys) + "}"
    raise TypeError(f"not canonicalisable: {type(value).__name__}")


# --- checks -----------------------------------------------------------------------------------------

def _has_dotdot(target: str) -> bool:
    return ".." in target.replace("\\", "/").split("/")


def _is_absolute(target: str) -> bool:
    return target.startswith(("/", "\\")) or (len(target) > 1 and target[1] == ":")


def _mirror_file(mirror: str, resolved: str) -> str | None:
    scheme_sep = resolved.find("://")
    if scheme_sep < 0:
        return None
    host, sep, rest = resolved[scheme_sep + 3:].partition("/")
    parts = [host, *rest.split("/")]
    if not sep or any(p in ("", ".", "..") for p in parts):
        return None  # such a URL path names no file inside the mirror
    path = os.path.join(mirror, *parts)
    return path if os.path.isfile(path) else None


def _sha512_values(integrity: Any) -> set[str]:
    if not isinstance(integrity, str):
        return set()
    return {tok[len("sha512-"):].split("?", 1)[0] for tok in integrity.split() if tok.startswith("sha512-")}


def _read_package(tgz: bytes) -> tuple[dict[str, Any], bool]:
    """(package/package.json as an object, whether package/binding.gyp exists)."""
    try:
        with tarfile.open(fileobj=io.BytesIO(tgz), mode="r:gz") as tar:
            names = {m.name for m in tar.getmembers()}
            member = tar.getmember("package/package.json")
            fh = tar.extractfile(member)
            if fh is None:
                raise Unusable("package/package.json is not a regular file")
            manifest = json.loads(fh.read().decode("utf-8"))
    except (KeyError, OSError, EOFError, tarfile.TarError, zlib.error, ValueError) as exc:
        raise Unusable(f"tarball: {exc}") from exc
    if not isinstance(manifest, dict):
        raise Unusable("tarball: package/package.json is not an object")
    return manifest, "package/binding.gyp" in names


def check_package(path: str, entry: dict[str, Any], mirror: str, egress: list[str],
                  marked: set[str]) -> tuple[str | None, dict[str, Any] | None]:
    """(reason or None, license row or None) for one lock entry; the first failing check wins."""
    resolved = entry.get("resolved")
    resolved = resolved if isinstance(resolved, str) else ""
    if resolved.startswith(("git+", "git:", "github:", "git@")):
        return "git_dependency", None
    if resolved.startswith("file:") or (entry.get("link") is True and (_is_absolute(resolved) or _has_dotdot(resolved))):
        return "file_dependency", None
    if not any(resolved.startswith(prefix) for prefix in egress):
        return "registry_not_allowed", None
    tarball_path = _mirror_file(mirror, resolved)
    if tarball_path is None:
        return "tarball_missing", None
    try:
        with open(tarball_path, "rb") as fh:
            tgz = fh.read()
    except OSError:
        return "tarball_missing", None
    digest = base64.b64encode(hashlib.sha512(tgz).digest()).decode("ascii")
    if digest not in _sha512_values(entry.get("integrity")):
        return "integrity_mismatch", None
    manifest, has_gyp = _read_package(tgz)
    scripts = manifest.get("scripts")
    has_script = (isinstance(scripts, dict) and any(h in scripts for h in INSTALL_HOOKS)) \
        or has_gyp or entry.get("hasInstallScript") is True
    name, version, license_ = manifest.get("name"), manifest.get("version"), manifest.get("license")
    if has_script and f"{name}@{version}" not in marked:
        return "install_script_unmarked", None
    return None, {"path": path, "name": name if isinstance(name, str) else None,
                  "version": version if isinstance(version, str) else None,
                  "license": license_ if isinstance(license_, str) else None}


def fetch(lock: Any, mirror: str, request: Any) -> dict[str, Any]:
    if not isinstance(request, dict):
        raise Unusable("stdin is not a JSON object")
    egress, marked = request.get("registry_egress"), request.get("install_scripts_required")
    for name, value in (("registry_egress", egress), ("install_scripts_required", marked)):
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            raise Unusable(f"stdin: {name} is not a list of strings")
    if not all(e.endswith("/") for e in egress):
        raise Unusable("stdin: a registry_egress entry does not end with '/'")
    if not isinstance(lock, dict) or not isinstance(lock.get("packages"), dict):
        raise Unusable("lock: no 'packages' object")
    rejected, fetched, licenses = [], [], []
    for path, entry in lock["packages"].items():
        if path == "":
            continue
        if not isinstance(entry, dict):
            raise Unusable(f"lock: packages[{path!r}] is not an object")
        resolved = entry.get("resolved")
        if entry.get("link") is True and isinstance(resolved, str) and resolved and ":" not in resolved \
                and not _is_absolute(resolved) and not _has_dotdot(resolved):
            continue  # workspace link to an in-repo target: nothing to fetch
        reason, row = check_package(path, entry, mirror, egress, set(marked))
        if reason is not None:
            rejected.append(f"{reason}:{path}")
        else:
            fetched.append({"integrity": entry.get("integrity"), "path": path})
            licenses.append(row)
    if rejected:
        return {"ok": False, "rejected": sorted(rejected), "artefact": None, "licenses": None}
    fetched.sort(key=lambda r: r["path"])
    licenses.sort(key=lambda r: r["path"])
    address = "sha256:" + hashlib.sha256(canonical(fetched).encode("utf-8")).hexdigest()
    return {"ok": True, "rejected": [], "artefact": address, "licenses": licenses}


def _emit(obj: dict[str, Any], code: int) -> int:
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()
    return code


def main(args: list[str]) -> int:
    unusable = {"ok": False, "artefact": None, "licenses": None}
    if len(args) != 3 or args[0] != "fetch":
        return _emit(unusable, 2)
    try:
        request = json.loads(sys.stdin.buffer.read().decode("utf-8"))
        with open(args[1], "rb") as fh:
            lock = json.loads(fh.read().decode("utf-8"))
        if not os.path.isdir(args[2]):
            raise Unusable("mirror dir is not a directory")
        os.listdir(args[2])
        result = fetch(lock, args[2], request)
    except (Unusable, OSError, ValueError) as exc:
        return _emit({**unusable, "error": str(exc)}, 2)
    return _emit(result, 0 if result["ok"] else 1)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
