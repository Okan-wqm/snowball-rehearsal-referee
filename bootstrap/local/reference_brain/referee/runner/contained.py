"""MF3 run.contained: python -m runner.contained argv  (stdin: one JSON run request).

Builds the `docker run` argv the run would execute (it does not run docker, checks no host path and
creates nothing) and prints one JSON line: the argv's projection plus the argv itself.
Exit 0 argv built; 1 request refused ({"ok": false, "reason": ...}); 2 unusable input ({"ok": false}).
"""
from __future__ import annotations

import json
import posixpath
import re
import sys
from typing import Any

_PINNED = re.compile(r"[^@\s]+@sha256:[0-9a-f]{64}")
_ENV_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_DOCKER_SOCKETS = ("/var/run/docker.sock", "/run/docker.sock")
_FIELDS = ("image", "cmd", "uid", "worktree", "outdir", "artefacts", "env", "services", "operating")
WORKDIR = "/work"
OUTDIR = "/out"


class Refused(Exception):
    pass


class Unusable(Exception):
    pass


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _host_path(value: Any, field: str) -> str:
    # A bind source must be an absolute host path; ',' and '"' would split or quote --mount's CSV fields.
    if not isinstance(value, str) or not value.startswith("/") or any(c in value for c in ',"\n\r\0'):
        raise Unusable(f"{field}: not a plain absolute host path")
    return value


def _exposes_docker_socket(path: str) -> bool:
    norm = posixpath.normpath(path)
    if posixpath.basename(norm) == "docker.sock":
        return True
    # Mounting a directory that holds the socket mounts the socket too.
    return any(sock == norm or sock.startswith(norm.rstrip("/") + "/") for sock in _DOCKER_SOCKETS)


def build(request: Any) -> list[str]:
    if not isinstance(request, dict):
        raise Unusable("request is not a JSON object")
    missing = [f for f in _FIELDS if f not in request]
    if missing:
        raise Unusable("missing field(s): " + ", ".join(missing))
    image, cmd, uid = request["image"], request["cmd"], request["uid"]
    env, services, operating = request["env"], request["services"], request["operating"]
    if not isinstance(image, str):
        raise Unusable("image is not a string")
    if not isinstance(cmd, list) or not cmd or not all(isinstance(c, str) for c in cmd):
        raise Unusable("cmd is not a non-empty list of strings")
    if not _is_int(uid) or uid < 0:
        raise Unusable("uid is not a non-negative integer")
    if not isinstance(env, dict) or not all(isinstance(v, str) for v in env.values()):
        raise Unusable("env is not an object of strings")
    if not isinstance(services, list):
        raise Unusable("services is not a list")
    if not isinstance(operating, dict):
        raise Unusable("operating is not an object")
    if not isinstance(request["artefacts"], list):
        raise Unusable("artefacts is not a list")
    worktree = _host_path(request["worktree"], "worktree")
    outdir = _host_path(request["outdir"], "outdir")
    artefacts = [_host_path(a, "artefacts[]") for a in request["artefacts"]]
    for name in env:
        if not _ENV_NAME.fullmatch(name):
            raise Unusable(f"env name {name!r} is not a variable name")

    if not _PINNED.fullmatch(image):
        raise Refused("image_not_pinned")
    if any(name.startswith("ACTIONS_") for name in env):
        raise Refused("actions_env")
    if any(_exposes_docker_socket(p) for p in [worktree, outdir, *artefacts]):
        raise Refused("docker_socket")
    if services:
        raise Refused("services")
    mem = operating.get("container_mem_bytes")
    if mem is None:
        raise Refused("container_mem_bytes_missing")
    if not isinstance(mem, dict) or not _is_int(mem.get("value")) or mem["value"] <= 0:
        raise Unusable("operating.container_mem_bytes.value is not a positive integer")

    argv = ["docker", "run", "--rm",
            "--network", "none",
            "--cap-drop", "ALL",
            "--read-only",
            "--user", str(uid),
            "--memory", str(mem["value"]),
            "--mount", f"type=bind,src={worktree},dst={WORKDIR}",
            "--mount", f"type=bind,src={outdir},dst={OUTDIR}"]
    for path in artefacts:
        argv += ["--mount", f"type=bind,src={path},dst={path},readonly"]
    for name, value in env.items():
        argv += ["--env", f"{name}={value}"]
    argv += ["--workdir", WORKDIR, image, *cmd]
    return argv


_VALUE_FLAGS = {"--network", "--net", "--cap-drop", "--cap-add", "--user", "-u", "--memory", "-m",
                "--mount", "--volume", "-v", "--tmpfs", "--env", "-e", "--env-file", "--workdir", "-w",
                "--name", "--memory-swap"}
_UNITS = {"": 1, "b": 1, "k": 1024, "m": 1024 ** 2, "g": 1024 ** 3}


def _bytes(text: str) -> int:
    m = re.fullmatch(r"(\d+)([bkmg]?)", text.lower())
    if m is None:
        raise ValueError(f"memory value {text!r}")
    return int(m.group(1)) * _UNITS[m.group(2)]


def project(argv: list[str]) -> dict[str, Any]:
    """Read the compared projection back out of the argv (not out of the request)."""
    if argv[:2] != ["docker", "run"]:
        raise ValueError("not a docker run argv")
    out: dict[str, Any] = {"ok": True, "network": "default", "cap_drop": [], "cap_add": [],
                           "privileged": False, "read_only": False, "uid": None, "memory_bytes": None,
                           "mounts": [], "env_names": [], "image": None}
    i = 2
    while i < len(argv):
        token = argv[i]
        if not token.startswith("-"):
            out["image"] = token
            break
        if "=" in token and token.split("=", 1)[0] in _VALUE_FLAGS:
            flag, value = token.split("=", 1)
            i += 1
        elif token in _VALUE_FLAGS:
            flag, value = token, argv[i + 1]
            i += 2
        else:
            flag, value = token, None
            i += 1
        if flag in ("--network", "--net"):
            out["network"] = value
        elif flag == "--cap-drop":
            out["cap_drop"].append(value)
        elif flag == "--cap-add":
            out["cap_add"].append(value)
        elif flag == "--privileged":
            out["privileged"] = True
        elif flag == "--read-only":
            out["read_only"] = True
        elif flag in ("--user", "-u"):
            out["uid"] = int(value.split(":", 1)[0])
        elif flag in ("--memory", "-m"):
            out["memory_bytes"] = _bytes(value)
        elif flag == "--mount":
            opts = {}
            for part in value.split(","):
                key, _, val = part.partition("=")
                opts[key] = val if _ else "true"
            dst = opts.get("dst", opts.get("destination", opts.get("target", "")))
            if opts.get("type") == "tmpfs":
                out["mounts"].append(["tmpfs:" + dst, "rw"])
            else:
                src = opts.get("src", opts.get("source", ""))
                ro = opts.get("readonly", opts.get("ro", "false")) in ("true", "1", "")
                out["mounts"].append([src, "ro" if ro else "rw"])
        elif flag in ("--volume", "-v"):
            parts = value.split(":")
            mode = "ro" if len(parts) > 2 and "ro" in parts[2].split(",") else "rw"
            out["mounts"].append([parts[0], mode])
        elif flag == "--tmpfs":
            out["mounts"].append(["tmpfs:" + value.split(":", 1)[0], "rw"])
        elif flag in ("--env", "-e"):
            out["env_names"].append(value.split("=", 1)[0])
        elif flag == "--env-file":
            raise ValueError("--env-file entries are not readable here")
    out["cap_drop"].sort()
    out["cap_add"].sort()
    out["mounts"].sort()
    out["env_names"].sort()
    out["argv"] = argv
    return out


def _emit(obj: dict[str, Any], code: int) -> int:
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()
    return code


def main(args: list[str]) -> int:
    if args != ["argv"]:
        return _emit({"ok": False, "reason": "usage: python -m runner.contained argv"}, 2)
    try:
        request = json.loads(sys.stdin.buffer.read().decode("utf-8"))
        argv = build(request)
    except Refused as exc:
        return _emit({"ok": False, "reason": str(exc)}, 1)
    except (Unusable, ValueError, UnicodeDecodeError) as exc:
        return _emit({"ok": False, "reason": f"unusable: {exc}"}, 2)
    return _emit(project(argv), 0)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
