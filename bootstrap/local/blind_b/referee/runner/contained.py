"""runner.contained -- run.contained (MF3): the `docker run` argv of one contained run.

    python -m runner.contained argv      (stdin: one JSON run request)

Builds the argv it would execute (it does not run docker, checks no host path for existence and
creates nothing on disk) and prints one JSON line: the projection parsed back from that argv plus the
argv itself (exit 0), or {"ok": false, "reason": ...} when the request is refused (exit 1) or unusable
(exit 2).
"""
import json
import re
import sys

FIELDS = ("image", "cmd", "uid", "worktree", "outdir", "artefacts", "env", "services", "operating")
PINNED_IMAGE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/:-]*@sha256:[0-9a-f]{64}")
DOCKER_SOCKETS = ("/var/run/docker.sock", "/run/docker.sock")
WORK_DST, OUT_DST, ARTEFACT_DST = "/work", "/out", "/artefacts"


class Refused(Exception):
    exit_code = 1


class Unusable(Exception):
    exit_code = 2


def _is_int(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _normalise(path: str) -> str:
    parts = []
    for c in path.split("/"):
        if c in ("", "."):
            continue
        if c == "..":
            if parts:
                parts.pop()
            continue
        parts.append(c)
    return "/" + "/".join(parts)


def _exposes_docker_socket(path: str) -> bool:
    p = _normalise(path)
    if p.rsplit("/", 1)[-1] == "docker.sock":
        return True
    prefix = p.rstrip("/") + "/"
    return any(sock == p or sock.startswith(prefix) for sock in DOCKER_SOCKETS)


def _check_host_path(path, what: str) -> None:
    if not isinstance(path, str):
        raise Unusable(f"{what} must be a string")
    if not path.startswith("/") or any(ch in path for ch in ',"\n\r\x00'):
        raise Unusable(f"{what} is not an absolute host path usable in a bind mount")


def validate(req) -> None:
    """Raise Unusable for a malformed request, Refused for a forbidden one."""
    if not isinstance(req, dict):
        raise Unusable("request is not a JSON object")
    missing = [f for f in FIELDS if f not in req]
    if missing:
        raise Unusable("missing request field(s): " + ", ".join(missing))
    if not isinstance(req["image"], str):
        raise Unusable("image must be a string")
    cmd = req["cmd"]
    if not isinstance(cmd, list) or not cmd or not all(isinstance(x, str) and "\x00" not in x for x in cmd):
        raise Unusable("cmd must be a non-empty list of strings")
    if not _is_int(req["uid"]) or req["uid"] < 0:
        raise Unusable("uid must be a non-negative integer")
    _check_host_path(req["worktree"], "worktree")
    _check_host_path(req["outdir"], "outdir")
    if not isinstance(req["artefacts"], list):
        raise Unusable("artefacts must be a list")
    for a in req["artefacts"]:
        _check_host_path(a, "artefact")
    env = req["env"]
    if not isinstance(env, dict):
        raise Unusable("env must be an object")
    for name, value in env.items():
        if name == "" or "=" in name or "\x00" in name or not isinstance(value, str) or "\x00" in value:
            raise Unusable("env must map variable names to string values")
    if not isinstance(req["services"], list):
        raise Unusable("services must be a list")
    if not isinstance(req["operating"], dict):
        raise Unusable("operating must be an object")

    if not PINNED_IMAGE.fullmatch(req["image"]):
        raise Refused("image is not pinned by @sha256 digest")
    for name in env:
        if name.startswith("ACTIONS_"):
            raise Refused("ACTIONS_* variables are not passed into the container")
    for path in [req["worktree"], req["outdir"], *req["artefacts"]]:
        if _exposes_docker_socket(path):
            raise Refused("the docker socket is not mounted")
    if req["services"]:
        raise Refused("Stage 0 units are service-less")
    mem = req["operating"].get("container_mem_bytes")
    if not isinstance(mem, dict) or not _is_int(mem.get("value")) or mem["value"] <= 0:
        raise Refused("operating has no usable container_mem_bytes value")


def build_argv(req) -> list:
    mem = str(req["operating"]["container_mem_bytes"]["value"])
    argv = ["docker", "run", "--rm",
            "--network", "none",
            "--cap-drop", "ALL",
            "--read-only",
            "--user", str(req["uid"]),
            "--memory", mem, "--memory-swap", mem,
            "--mount", f"type=bind,src={req['worktree']},dst={WORK_DST}",
            "--mount", f"type=bind,src={req['outdir']},dst={OUT_DST}"]
    for i, a in enumerate(req["artefacts"]):
        argv += ["--mount", f"type=bind,src={a},dst={ARTEFACT_DST}/{i},readonly"]
    for name in sorted(req["env"]):
        argv += ["--env", f"{name}={req['env'][name]}"]
    argv += ["--workdir", WORK_DST, req["image"], *req["cmd"]]
    return argv


# ---- projection: parsed from an argv, never copied from the request ----

VALUE_OPTS = {
    "--network": "network", "--net": "network",
    "--cap-drop": "cap_drop", "--cap-add": "cap_add",
    "--user": "user", "-u": "user",
    "--memory": "memory", "-m": "memory",
    "--memory-swap": "memory_swap",
    "--mount": "mount", "--volume": "volume", "-v": "volume", "--tmpfs": "tmpfs",
    "--env": "env", "-e": "env", "--env-file": "env_file",
    "--workdir": "workdir", "-w": "workdir", "--name": "name",
}
FLAG_OPTS = {"--rm": "rm", "--read-only": "read_only", "--privileged": "privileged",
             "--init": "init", "-i": "interactive", "--interactive": "interactive",
             "-t": "tty", "--tty": "tty", "-d": "detach", "--detach": "detach"}
UNITS = {"": 1, "b": 1, "k": 1024, "m": 1024 ** 2, "g": 1024 ** 3}


def _bytes(value: str) -> int:
    m = re.fullmatch(r"(\d+)([bkmgBKMG]?)", value)
    if not m:
        raise ValueError(f"bad memory value {value!r}")
    return int(m.group(1)) * UNITS[m.group(2).lower()]


def _mount_pair(spec: str) -> list:
    kv = {}
    flags = set()
    for field in spec.split(","):
        k, sep, v = field.partition("=")
        if sep:
            kv[k.strip().lower()] = v
        else:
            flags.add(field.strip().lower())
    kind = kv.get("type", "volume")
    dst = kv.get("dst", kv.get("destination", kv.get("target", "")))
    if kind == "tmpfs":
        return ["tmpfs:" + dst, "rw"]
    if kind != "bind":
        raise ValueError(f"unsupported mount type {kind!r}")
    src = kv.get("src", kv.get("source"))
    ro = bool(flags & {"readonly", "ro"})
    for key in ("readonly", "ro"):
        if key in kv:
            ro = kv[key].lower() in ("1", "true")
    return [src, "ro" if ro else "rw"]


def _volume_pair(spec: str) -> list:
    parts = spec.split(":")
    if len(parts) < 2 or not parts[0].startswith("/"):
        raise ValueError(f"unsupported volume {spec!r}")
    opts = parts[2].split(",") if len(parts) > 2 else []
    return [parts[0], "ro" if "ro" in opts else "rw"]


def project(argv: list) -> dict:
    if argv[:2] != ["docker", "run"]:
        raise ValueError("not a docker run argv")
    values = {}
    flags = set()
    i, image = 2, None
    while i < len(argv):
        tok = argv[i]
        if not tok.startswith("-"):
            image = tok
            break
        name, sep, attached = tok.partition("=")
        if name in FLAG_OPTS and not sep:
            flags.add(FLAG_OPTS[name])
            i += 1
            continue
        if name not in VALUE_OPTS:
            raise ValueError(f"unknown option {tok!r}")
        if sep:
            value = attached
            i += 1
        else:
            value = argv[i + 1]
            i += 2
        values.setdefault(VALUE_OPTS[name], []).append((name, value))
    if image is None:
        raise ValueError("no image in argv")
    if "env_file" in values:
        raise ValueError("--env-file is not supported by this projection")

    def all_of(key):
        return [v for _, v in values.get(key, [])]

    def last_of(key):
        got = all_of(key)
        return got[-1] if got else None

    mounts = [_mount_pair(v) for v in all_of("mount")]
    mounts += [_volume_pair(v) for v in all_of("volume")]
    mounts += [["tmpfs:" + v.split(":", 1)[0], "rw"] for v in all_of("tmpfs")]
    user = last_of("user")
    memory = last_of("memory")
    return {
        "ok": True,
        "network": last_of("network") or "default",
        "cap_drop": sorted(all_of("cap_drop")),
        "cap_add": sorted(all_of("cap_add")),
        "privileged": "privileged" in flags,
        "read_only": "read_only" in flags,
        "uid": int(user.split(":", 1)[0]) if user is not None else None,
        "memory_bytes": _bytes(memory) if memory is not None else None,
        "mounts": sorted(mounts),
        "env_names": sorted({v.split("=", 1)[0] for v in all_of("env")}),
        "image": image,
        "argv": list(argv),
    }


def evaluate(req) -> tuple:
    try:
        validate(req)
    except (Refused, Unusable) as e:
        return e.exit_code, {"ok": False, "reason": str(e)}
    return 0, project(build_argv(req))


def handle(req) -> dict:
    return evaluate(req)[1]


def _emit(obj) -> None:
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def main(argv=None, stdin_text=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    try:
        if argv != ["argv"]:
            raise Unusable("usage: argv  (request on stdin)")
        if stdin_text is None:
            stdin_text = sys.stdin.buffer.read().decode("utf-8")
        try:
            req = json.loads(stdin_text)
        except ValueError as e:
            raise Unusable("stdin is not JSON") from e
        code, out = evaluate(req)
    except Exception as e:  # unusable: one line, exit 2
        _emit({"ok": False, "reason": str(e) or type(e).__name__})
        return 2
    _emit(out)
    return code


if __name__ == "__main__":
    sys.exit(main())
