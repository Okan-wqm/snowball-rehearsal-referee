"""Contained run: one docker container per command, fresh host directory, hashes taken outside (stage 0, MF3).

Rules: tohum/08 items 2-3 (container flags, fresh host worktree, results hashed outside after the
container ends, red control in every run), tohum/26a (run.contained: command, trees, artifacts, unit
image and limits in; results and their hashes out), tohum/18a and 26c (``operating{key: {value, band}}``
limits, ``limit_hit:<key>``), asama-0/14 (group ``contained``: the generated ``docker run`` argv carries
the mandatory flags and none of the forbidden ones), tohum/29f section ``contained`` (the ``argv`` command).

The argv. One writer (``_compose``) writes every flag; two layouts differ only in the mounts. ``build_argv``
(the run layout, used by ``run``) writes exactly this shape, and ``check_argv`` accepts nothing else:

    docker run --rm --pull never --network none --cap-drop ALL --read-only
      --security-opt no-new-privileges --user UID:GID --memory N --memory-swap N
      --name snowball-<32 hex> --workdir /work [--env NAME=VALUE ...]
      --mount type=bind,src=ROOT/work,dst=/work --mount type=bind,src=ROOT/out,dst=/out
      [--mount type=bind,src=ROOT/in,dst=/in,readonly]
      IMAGE CMD [ARG ...]

- ``check_argv`` is an allowlist, not a list of bad flags: before the image, every token must be one of
  the flags above, written as its own token with its value in the next token (the ``--flag=value`` form,
  short forms and any other docker flag are refused, so ``--privileged``, ``--network host``, ``--cap-add``,
  ``-v``, ``--device``, ``--pid host``, ``--env-file`` cannot appear). Each flag but ``--env`` and
  ``--mount`` appears exactly once; ``argv[0:2]`` is exactly ``docker run`` (no global option such as
  ``-H``). Values: user is two decimal ids, neither 0; memory and swap are the same integer of at least
  6 MiB; env is ``NAME=VALUE`` with NAME an identifier not starting, in any case, with ``ACTIONS_``, ``GITHUB_`` or
  ``RUNNER_`` (the ``--env NAME`` form, which copies the host's value, is refused); mounts are exactly
  ``/work`` and ``/out`` writable and optionally ``/in`` read-only, all three from one absolute, normalised
  ROOT spelled with ``[A-Za-z0-9._/-]`` only. The image is pinned: ``name[:tag]@sha256:<64 hex>``.
- The request layout (``request_argv``, the ``argv`` command; ``check_argv(argv, layout="request")``):
  the same flags, ``--user UID:65534``, and the mounts ``--mount type=bind,src=WORKTREE,dst=/work``,
  ``src=OUTDIR,dst=/out`` and, for each ``artefacts[k]``, ``src=PATH,dst=/in/<k>,readonly``. Each source is an
  absolute, normalised path of ``[A-Za-z0-9._/-]`` (so no ``,`` can add a mount option), not ``/``, not a
  docker socket (below); sources do not repeat, and no artefact covers or is covered by the worktree or the
  output directory. ``run`` does not use this layout: it keeps its fresh ROOT and mounts the artefacts as one
  ``/in``.
- Docker socket rule (request layout), on the path text only: a source is refused when a component is
  ``docker.sock`` (any case), when it covers ``/var/run/docker.sock`` or ``/run/docker.sock`` (tohum/29f
  coverage: equal, or a prefix ending at ``/``; so ``/var``, ``/var/run``, ``/run`` too), or when it is
  ``/run/user`` or ``/run/user/<one component>`` (rootless docker's socket directory). A symlink or bind
  mount that reaches a socket under another name is not seen: the command does not look at the disk.
- Out of scope of ``check_argv``: what CMD does inside the container, and env values (the ``koş`` job
  carries no secret, tohum/08 item 1, so a value can only come from the caller). Whether a mount source
  is a real directory and not a symlink is checked by ``run`` on the host, not by ``check_argv``.

The run (``run``):

- A fresh directory per run (``tempfile.mkdtemp``) holds ``work`` (a copy of the tree), ``out`` (empty) and
  ``in`` (a copy of the artifacts, mounted read-only). Docker's own process gets ``PATH`` and ``HOME`` (the
  fresh directory) only, so no other host variable reaches it, and the argv is checked before docker
  starts.
- After docker returns (on timeout: ``docker kill`` by name, then wait), ``work``, ``out`` and ``in`` are
  hashed from the host without following symlinks: a symlink is recorded with its target, a FIFO or
  device as its type and is never opened; an entry the host cannot read or list makes the run
  ``unreadable_output``.
- ``status`` is ``ok``; or ``runner_fault`` (docker exit 125); ``limit_hit:kos_wall_s`` (timeout),
  ``limit_hit:worktree_bytes`` (tree too big before the run, or ``work`` too big after),
  ``limit_hit:output_bytes`` (``out`` too big after); ``breach:in_changed`` (the read-only artifacts differ
  after the run); ``unreadable_output``. Only ``ok`` is a valid result; the command's own exit code is the
  result, not the status.
- Limits are measured, not enforced while the command runs: a command can fill the disk before the
  size check after it sees that. ``files_read`` and ``network_attempts`` are not measured here and are
  reported as ``null``; ``paths_written`` is the hash difference of ``work`` and ``out``.

Red control (``run_with_red_control``): every call runs a known bad candidate in its own fresh directory
with the same image (required), flags and limits. It is red when its status is ``ok`` and its exit code is not
0, 125, 126 or 127 (docker, not-executable and not-found failures). A green control makes the whole run
invalid (``red_control_green``); a control that could not run is ``red_control_fault``.

Command line, run from ``referee/`` (stdout is one JSON line; exit 0 fine, 1 refused or invalid, 2
unusable input). Exit 1 comes only from a refusal (``ContainmentError``, ``check`` not ok, ``run`` not
valid); input that is not JSON, nested too deeply to parse, or of the wrong shape is exit 2, and so is any
other exception, at ``cli.run``'s boundary (``FAULT_LINE``, the type alone on stderr), never a traceback. Out of scope:
signals and the interpreter being killed.

    python -m runner.contained argv      stdin {image, cmd, uid, worktree, outdir, artefacts, env, services,
                                         operating} (tohum/29f); see below
    python -m runner.contained check     stdin: an argv as a JSON array
    python -m runner.contained run FILE  FILE {job, red_control, operating, base?}; job and red_control are
                                         {image, cmd, tree?, artifacts?, env?, uid?, gid?}

``argv`` (tohum/29f group ``contained``): builds the request layout's argv; it does not run docker, reads
no host path and makes nothing on disk. All nine fields are required, of their JSON types (``cmd`` a
non-empty list of strings, ``artefacts`` strings, ``env`` string values; other keys are ignored); otherwise
exit 2. Refused, exit 1, never fixed: non-empty ``services``; an image that is not
``<ref>@sha256:<64 lowercase hex>``; an env name starting, in any case, with ``ACTIONS_``, ``GITHUB_`` or
``RUNNER_``, or not an identifier; no ``operating.container_mem_bytes``, or its value not an integer inside
its band or below 6 MiB; a mount source the rules above refuse; ``uid`` not a positive integer (never root).
On exit 0 the line is the projection of the built argv, computed by parsing that argv (``project_argv``),
not copied from the request: ``ok``, ``network`` (last ``--network``/``--net``, else ``default``),
``cap_drop``, ``cap_add`` (sorted), ``privileged``, ``read_only``, ``uid`` (``--user`` before ``:``, an
integer), ``memory_bytes`` (integer), ``mounts`` (``[source, "ro"|"rw"]`` sorted; tmpfs as
``["tmpfs:" + target, "rw"]``), ``env_names`` (sorted), ``image``, ``argv``. On exit 1 and 2 the line is
``{"ok": false, "reason": ...}``.
"""

from __future__ import annotations

import hashlib
import json
import os
import posixpath
import re
import secrets as _random
import shutil
import stat
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from typing import Any, Callable

import cli

DEFAULT_UID = 65534
DEFAULT_GID = 65534
MIN_MEMORY = 6 * 1024 * 1024
RUN_LIMITS = ("container_mem_bytes", "kos_wall_s", "worktree_bytes", "output_bytes")
FORBIDDEN_ENV_PREFIXES = ("ACTIONS_", "GITHUB_", "RUNNER_")
NOT_RED_EXITS = (0, 125, 126, 127)
KILL_WAIT_S = 30

# Flag -> value rule, in the order build_argv writes them. None: no value. Each appears exactly once.
SINGLE_FLAGS: dict[str, Any] = {
    "--rm": None,
    "--pull": "never",
    "--network": "none",
    "--cap-drop": "ALL",
    "--read-only": None,
    "--security-opt": "no-new-privileges",
    "--user": re.compile(r"([1-9][0-9]{0,9}):([1-9][0-9]{0,9})\Z"),
    "--memory": re.compile(r"[1-9][0-9]{0,18}\Z"),
    "--memory-swap": re.compile(r"[1-9][0-9]{0,18}\Z"),
    "--name": re.compile(r"snowball-[0-9a-f]{32}\Z"),
    "--workdir": "/work",
}
MANDATORY = ("--network", "--cap-drop", "--read-only", "--user")
ENV_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
ROOT_PATH = re.compile(r"/[A-Za-z0-9._/-]*\Z")
MOUNT = re.compile(r"type=bind,src=(/[A-Za-z0-9._/-]*),dst=(/work|/out|/in)(,readonly)?\Z")
REQUEST_MOUNT = re.compile(r"type=bind,src=([^,]*),dst=(/work|/out|/in/(?:0|[1-9][0-9]{0,5}))(,readonly)?\Z")
SOURCE_PATH = re.compile(r"/[A-Za-z0-9._/-]*\Z")
DOCKER_SOCKET_NAME = "docker.sock"
DOCKER_SOCKETS = ("/var/run/docker.sock", "/run/docker.sock")
DOCKER_SOCKET_DIR = re.compile(r"/run/user/[^/]+/?\Z")  # rootless docker: /run/user/<uid>/docker.sock
WORKDIR = "/work"  # the container work directory of every run; gate.check reads lint paths under it
MOUNT_SUBDIR = {"/work": "work", "/out": "out", "/in": "in"}
_COMPONENT = r"[a-z0-9]+(?:(?:\.|_|__|-+)[a-z0-9]+)*"
IMAGE = re.compile(
    r"(?:[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?)*(?::[0-9]+)?/)?"
    + _COMPONENT + r"(?:/" + _COMPONENT + r")*"
    + r"(?::[A-Za-z0-9_][A-Za-z0-9_.-]{0,127})?"
    + r"@sha256:[0-9a-f]{64}\Z")


class ContainmentError(ValueError):
    """The request cannot be run inside the container the spec requires; nothing was started."""


class UnusableInput(ValueError):
    """The request is not of the shape the command reads (exit 2, not a refusal)."""


# ---------------------------------------------------------------- limits

def limits(operating: dict, keys: tuple[str, ...]) -> dict[str, int]:
    """Read ``operating{key: {value, band: [min, max]}}``; every key is required, value inside its band."""
    out = {}
    for key in keys:
        entry = operating.get(key) if isinstance(operating, dict) else None
        if not isinstance(entry, dict):
            raise ContainmentError("operating.%s missing" % key)
        value, band = entry.get("value"), entry.get("band")
        if not _posint(value):
            raise ContainmentError("operating.%s.value is not a positive integer" % key)
        if not (isinstance(band, list) and len(band) == 2
                and all(isinstance(b, int) and not isinstance(b, bool) and b >= 0 for b in band)):
            raise ContainmentError("operating.%s.band is not [min, max]" % key)
        if not band[0] <= value <= band[1]:
            raise ContainmentError("operating.%s.value outside its band" % key)
        out[key] = value
    return out


def _posint(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


# ---------------------------------------------------------------- argv

def _compose(image: Any, cmd: Any, operating: Any, env: Any, uid: Any, gid: Any, mounts: list[str],
             name: str | None) -> list[str]:
    """The one ``docker run`` argv writer: every flag but the mounts is the same for every layout."""
    memory = limits(operating, ("container_mem_bytes",))["container_mem_bytes"]
    if not (isinstance(cmd, list) and cmd and all(isinstance(c, str) for c in cmd)):
        raise ContainmentError("cmd must be a non-empty list of strings")
    if not all(_posint(i) for i in (uid, gid)):
        raise ContainmentError("uid and gid must be positive integers (never root)")
    argv = ["docker", "run", "--rm", "--pull", "never", "--network", "none", "--cap-drop", "ALL",
            "--read-only", "--security-opt", "no-new-privileges", "--user", "%d:%d" % (uid, gid),
            "--memory", str(memory), "--memory-swap", str(memory),
            "--name", name or "snowball-" + _random.token_hex(16), "--workdir", "/work"]
    for key in sorted(env or {}):
        if not isinstance(env[key], str):
            raise ContainmentError("env values must be strings")
        argv += ["--env", "%s=%s" % (key, env[key])]
    for mount in mounts:
        argv += ["--mount", mount]
    return argv + [image] + cmd


def build_argv(image: str, cmd: list[str], run_root: str, operating: dict, env: dict | None = None,
               uid: int = DEFAULT_UID, gid: int = DEFAULT_GID, artifacts: bool = False,
               name: str | None = None) -> list[str]:
    """The run layout (fresh ROOT); refused (ContainmentError) unless ``check_argv`` accepts it."""
    mounts = ["type=bind,src=%s/work,dst=/work" % run_root, "type=bind,src=%s/out,dst=/out" % run_root]
    if artifacts:
        mounts.append("type=bind,src=%s/in,dst=/in,readonly" % run_root)
    argv = _compose(image, cmd, operating, env, uid, gid, mounts, name)
    report = check_argv(argv)
    if not report["ok"]:
        raise ContainmentError("argv refused: %s" % json.dumps(report, sort_keys=True))
    return argv


REQUEST_FIELDS = (("image", str), ("cmd", list), ("uid", int), ("worktree", str), ("outdir", str),
                  ("artefacts", list), ("env", dict), ("services", list), ("operating", dict))


def request_shape(req: Any) -> dict:
    """Types only (exit 2): every field of tohum/29f's request present and of its type; other keys ignored."""
    if not isinstance(req, dict):
        raise UnusableInput("request must be a JSON object")
    for key, kind in REQUEST_FIELDS:
        if key not in req:
            raise UnusableInput("request.%s missing" % key)
        if not isinstance(req[key], kind) or isinstance(req[key], bool):
            raise UnusableInput("request.%s is not a %s" % (key, kind.__name__))
    if not req["cmd"] or not all(isinstance(c, str) for c in req["cmd"]):
        raise UnusableInput("request.cmd must be a non-empty list of strings")
    if not all(isinstance(a, str) for a in req["artefacts"]):
        raise UnusableInput("request.artefacts must be a list of strings")
    if not all(isinstance(v, str) for v in req["env"].values()):
        raise UnusableInput("request.env values must be strings")
    return req


def request_argv(req: Any) -> list[str]:
    """The argv for one tohum/29f run request; UnusableInput for its shape, ContainmentError for a refusal.

    Mounts: ``worktree`` at ``/work`` and ``outdir`` at ``/out`` writable, ``artefacts[k]`` at ``/in/<k>``
    read-only; the user is ``UID:65534``. Nothing on disk is read or made.
    """
    req = request_shape(req)
    if req["services"]:
        raise ContainmentError("services: stage 0 units have none")
    if not IMAGE.match(req["image"]):
        raise ContainmentError("image is not pinned as <ref>@sha256:<64 lowercase hex>: %s" % req["image"])
    for key in sorted(req["env"]):
        reason = _env_problem("%s=" % key)
        if reason:
            raise ContainmentError("env %s: %s" % (key, reason))
    if "container_mem_bytes" not in req["operating"]:
        raise ContainmentError("operating.container_mem_bytes missing")
    sources = [("worktree", req["worktree"]), ("outdir", req["outdir"])] + \
        [("artefacts[%d]" % k, a) for k, a in enumerate(req["artefacts"])]
    for label, path in sources:
        reason = source_problem(path)
        if reason:
            raise ContainmentError("%s: %s" % (label, reason))
    mounts = ["type=bind,src=%s,dst=/work" % req["worktree"], "type=bind,src=%s,dst=/out" % req["outdir"]]
    mounts += ["type=bind,src=%s,dst=/in/%d,readonly" % (a, k) for k, a in enumerate(req["artefacts"])]
    argv = _compose(req["image"], req["cmd"], req["operating"], req["env"], req["uid"], DEFAULT_GID, mounts, None)
    report = check_argv(argv, layout="request")
    if not report["ok"]:
        raise ContainmentError("argv refused: %s" % json.dumps(report, sort_keys=True))
    return argv


# docker run flags that take no value (anything else starting with '-' takes the next token, or '=value')
BOOL_FLAGS = {"--rm", "--read-only", "--privileged", "--init", "--interactive", "-i", "--tty", "-t",
              "--detach", "-d", "--no-healthcheck", "--oom-kill-disable", "--publish-all", "-P", "--quiet", "-q",
              "--disable-content-trust", "--sig-proxy"}
SHORT = {"-e": "--env", "-u": "--user", "-m": "--memory", "-v": "--volume", "-w": "--workdir", "-p": "--publish"}
MEMORY_VALUE = re.compile(r"([0-9]+) ?([kmgtp]?)i?b?\Z", re.IGNORECASE)


def project_argv(argv: list[str]) -> dict:
    """tohum/29f's projection of a ``docker run`` argv, read from the argv itself (not from any request)."""
    opts: list[tuple[str, str | None]] = []
    i = 2
    while i < len(argv) and argv[i].startswith("-"):
        tok = argv[i]
        if tok.startswith("--") and "=" in tok:
            flag, value = tok.split("=", 1)
            i += 1
        elif tok in BOOL_FLAGS:
            flag, value = tok, None
            i += 1
        else:
            flag, value = tok, argv[i + 1] if i + 1 < len(argv) else None
            i += 2
        opts.append((SHORT.get(flag, flag), value))
    image = argv[i] if i < len(argv) else None
    network, user, memory = "default", None, None
    cap_drop: list[str] = []
    cap_add: list[str] = []
    flags = {"--privileged": False, "--read-only": False}
    mounts: list[list[str]] = []
    env_names: set[str] = set()
    for flag, value in opts:
        if flag in ("--network", "--net"):
            network = value
        elif flag == "--cap-drop":
            cap_drop.append(value)
        elif flag == "--cap-add":
            cap_add.append(value)
        elif flag in flags:
            flags[flag] = value is None or value.lower() in ("true", "1")
        elif flag == "--user":
            user = value
        elif flag == "--memory":
            memory = value
        elif flag == "--env":
            env_names.add((value or "").partition("=")[0])
        elif flag == "--mount":
            mounts.append(_project_mount(value or ""))
        elif flag == "--volume":
            parts = (value or "").split(":")
            ro = len(parts) > 2 and "ro" in parts[2].split(",")
            mounts.append([parts[0] if len(parts) > 1 else "volume:" + parts[0], "ro" if ro else "rw"])
        elif flag == "--tmpfs":
            mounts.append(["tmpfs:" + (value or "").split(":")[0], "rw"])
    uid_text = user.split(":")[0] if user is not None else None
    return {"ok": True, "network": network, "cap_drop": sorted(cap_drop), "cap_add": sorted(cap_add),
            "privileged": flags["--privileged"], "read_only": flags["--read-only"],
            "uid": int(uid_text) if uid_text is not None and uid_text.isdigit() else None,
            "memory_bytes": _memory_bytes(memory), "mounts": sorted(mounts), "env_names": sorted(env_names),
            "image": image, "argv": argv}


def _project_mount(value: str) -> list[str]:
    fields = dict(f.split("=", 1) if "=" in f else (f, "true") for f in value.split(","))
    kind = fields.get("type", "volume")
    target = fields.get("dst") or fields.get("destination") or fields.get("target") or ""
    if kind == "tmpfs":
        return ["tmpfs:" + target, "rw"]
    source = fields.get("src") or fields.get("source") or "volume:" + target
    ro = fields.get("readonly", fields.get("ro", "false")).lower() not in ("false", "0")
    return [source, "ro" if ro else "rw"]


def _memory_bytes(value: str | None) -> int | None:
    m = MEMORY_VALUE.match(value or "")
    if not m:
        return None
    unit = m.group(2).lower()
    return int(m.group(1)) * 1024 ** ("kmgtp".index(unit) + 1 if unit else 0)


def check_argv(argv: Any, layout: str = "run") -> dict:
    """``{ok, missing, forbidden}`` for an argv; ``ok`` only for the exact shape in the module docstring.

    ``layout`` is the mount rule: ``run`` (one fresh ROOT, what ``build_argv`` writes) or ``request`` (what
    ``request_argv`` writes for the ``argv`` command); every other flag rule is the same for both.
    """
    if layout not in ("run", "request"):
        raise ValueError("layout is run or request")
    missing: list[str] = []
    forbidden: list[str] = []
    if not (isinstance(argv, list) and all(isinstance(a, str) for a in argv)):
        return {"ok": False, "missing": [], "forbidden": ["argv is not a list of strings"]}
    if argv[:2] != ["docker", "run"]:
        return {"ok": False, "missing": [], "forbidden": ["argv must start with exactly: docker run"]}
    seen: dict[str, int] = {}
    mounts: list[str] = []
    i = 2
    image_at = None
    while i < len(argv):
        tok = argv[i]
        if not tok.startswith("-"):
            image_at = i
            break
        if tok in SINGLE_FLAGS:
            rule = SINGLE_FLAGS[tok]
            seen[tok] = seen.get(tok, 0) + 1
            if rule is None:
                i += 1
                continue
            value = argv[i + 1] if i + 1 < len(argv) else None
            if value is None or not _value_ok(rule, value):
                forbidden.append("%s %s" % (tok, value))
            i += 2
            continue
        if tok == "--env":
            value = argv[i + 1] if i + 1 < len(argv) else None
            reason = _env_problem(value)
            if reason:
                forbidden.append("--env %s (%s)" % (value, reason))
            i += 2
            continue
        if tok == "--mount":
            value = argv[i + 1] if i + 1 < len(argv) else None
            if value is None:
                forbidden.append("--mount without a value")
            else:
                mounts.append(value)
            i += 2
            continue
        forbidden.append("flag not allowed: %s" % tok)
        i += 1
    for flag in SINGLE_FLAGS:
        if seen.get(flag, 0) == 0:
            missing.append(flag)
        elif seen[flag] > 1:
            forbidden.append("%s given %d times" % (flag, seen[flag]))
    mem = _flag_value(argv, "--memory")
    swap = _flag_value(argv, "--memory-swap")
    if mem is not None and mem.isdigit() and int(mem) < MIN_MEMORY:
        forbidden.append("--memory below %d" % MIN_MEMORY)
    if mem is not None and swap is not None and mem != swap:
        forbidden.append("--memory-swap differs from --memory")
    forbidden += (_mount_problems if layout == "run" else _request_mount_problems)(mounts, missing)
    if image_at is None:
        missing.append("image")
    elif not IMAGE.match(argv[image_at]):
        forbidden.append("image not pinned by @sha256: %s" % argv[image_at])
    elif image_at + 1 >= len(argv):
        missing.append("command")
    ok = not missing and not forbidden
    return {"ok": ok, "missing": missing, "forbidden": forbidden}


def _value_ok(rule: Any, value: str) -> bool:
    if isinstance(rule, str):
        return value == rule
    return bool(rule.match(value))


def _flag_value(argv: list[str], flag: str) -> str | None:
    for i in range(2, len(argv) - 1):
        if argv[i] == flag:
            return argv[i + 1]
    return None


def _env_problem(value: str | None) -> str | None:
    if value is None:
        return "no value"
    name, sep, _ = value.partition("=")
    if not sep:
        return "NAME without =VALUE copies the host's value"
    if not ENV_NAME.match(name):
        return "not an identifier"
    if name.upper().startswith(FORBIDDEN_ENV_PREFIXES):
        return "runner variable"
    return None


def _mount_problems(mounts: list[str], missing: list[str]) -> list[str]:
    problems: list[str] = []
    roots: set[str] = set()
    dsts: list[str] = []
    for value in mounts:
        m = MOUNT.match(value)
        if not m:
            problems.append("--mount not allowed: %s" % value)
            continue
        src, dst, readonly = m.group(1), m.group(2), bool(m.group(3))
        if (dst == "/in") != readonly:
            problems.append("--mount %s: only /in is read-only, and it must be" % value)
        suffix = "/" + MOUNT_SUBDIR[dst]
        root = src[: -len(suffix)] if src.endswith(suffix) else None
        if not root or not _root_ok(root):
            problems.append("--mount %s: source must be ROOT%s under one fresh ROOT" % (value, suffix))
            continue
        roots.add(root)
        dsts.append(dst)
    for dst in set(dsts):
        if dsts.count(dst) > 1:
            problems.append("--mount for %s given %d times" % (dst, dsts.count(dst)))
    for dst in ("/work", "/out"):
        if dst not in dsts:
            missing.append("--mount %s" % dst)
    if len(roots) > 1:
        problems.append("--mount sources under more than one ROOT")
    return problems


def _request_mount_problems(mounts: list[str], missing: list[str]) -> list[str]:
    problems: list[str] = []
    pairs: list[tuple[str, str]] = []
    for value in mounts:
        m = REQUEST_MOUNT.match(value)
        if not m:
            problems.append("--mount not allowed: %s" % value)
            continue
        src, dst, readonly = m.group(1), m.group(2), bool(m.group(3))
        if dst.startswith("/in/") != readonly:
            problems.append("--mount %s: only /in/<k> is read-only, and it must be" % value)
        reason = source_problem(src)
        if reason:
            problems.append("--mount %s: %s" % (value, reason))
        pairs.append((src, dst))
    srcs, dsts = [p[0] for p in pairs], [p[1] for p in pairs]
    if len(set(srcs)) != len(srcs) or len(set(dsts)) != len(dsts):
        problems.append("--mount source or target given more than once")
    for dst in ("/work", "/out"):
        if dst not in dsts:
            missing.append("--mount %s" % dst)
    ins = sorted(int(d[4:]) for d in dsts if d.startswith("/in/"))
    if ins != list(range(len(ins))):
        problems.append("--mount /in/<k> are not /in/0 to /in/<n-1>")
    writable = [s for s, d in pairs if not d.startswith("/in/")]
    for src, dst in pairs:
        if dst.startswith("/in/") and any(_covers(src, w) or _covers(w, src) for w in writable):
            problems.append("--mount %s: an artefact overlaps a writable directory" % src)
    return problems


def _covers(e: str, p: str) -> bool:
    """tohum/29f: ``e`` covers ``p`` iff ``p == e`` or ``p`` starts with ``e + '/'`` (paths are normalised)."""
    e = e.rstrip("/")
    return p == e or p.startswith(e + "/")


def source_problem(path: Any) -> str | None:
    """Why a request path cannot be a mount source (None: it can). Read as text; the disk is never looked at."""
    if not isinstance(path, str):
        return "path is not a string"
    parts = path.split("/")
    if any(part.lower() == DOCKER_SOCKET_NAME for part in parts) \
            or any(_covers(path, sock) for sock in DOCKER_SOCKETS) \
            or path in ("/run/user", "/run/user/") or DOCKER_SOCKET_DIR.match(path):
        return "docker socket: %s is or contains a docker socket" % path
    if not SOURCE_PATH.match(path) or path.startswith("//") or posixpath.normpath(path) != path:
        return "not an absolute, normalised path of [A-Za-z0-9._/-]: %s" % path
    if path == "/":
        return "the host root"
    return None


def _root_ok(root: str) -> bool:
    return bool(ROOT_PATH.match(root)) and root != "/" and os.path.normpath(root) == root \
        and "/../" not in root + "/" and "/./" not in root + "/"


# ---------------------------------------------------------------- hashing outside

def hash_tree(top: str) -> dict[str, dict]:
    """Every entry under ``top`` by relative path, read from the host; symlinks are never followed."""
    entries: dict[str, dict] = {}
    if not os.path.isdir(top):
        return entries

    pending = [(top, "")]
    while pending:
        path, rel = pending.pop()
        try:
            with os.scandir(path) as it:
                children = sorted(it, key=lambda e: e.name)
        except OSError:
            entries[rel] = {"type": "dir", "unreadable": True}
            continue
        for child in children:
            crel = child.name if not rel else rel + "/" + child.name
            try:
                st = os.lstat(child.path)
            except OSError:
                entries[crel] = {"type": "unknown", "unreadable": True}
                continue
            if stat.S_ISLNK(st.st_mode):
                entries[crel] = {"type": "symlink", "target": os.readlink(child.path)}
            elif stat.S_ISDIR(st.st_mode):
                entries[crel] = {"type": "dir"}
                pending.append((child.path, crel))
            elif stat.S_ISREG(st.st_mode):
                entries[crel] = _hash_file(child.path)
            else:
                entries[crel] = {"type": "other", "mode": stat.S_IFMT(st.st_mode)}
    return entries


def _hash_file(path: str) -> dict:
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError:
        return {"type": "file", "unreadable": True}
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            return {"type": "other", "mode": stat.S_IFMT(st.st_mode)}
        digest = hashlib.sha256()
        size = 0
        while True:
            chunk = os.read(fd, 1 << 20)
            if not chunk:
                break
            digest.update(chunk)
            size += len(chunk)
        return {"type": "file", "sha256": digest.hexdigest(), "size": size}
    finally:
        os.close(fd)


def tree_bytes(entries: dict[str, dict]) -> int:
    return sum(e.get("size", 0) for e in entries.values())


def tree_sha256(entries: dict[str, dict]) -> str:
    return hashlib.sha256(json.dumps(entries, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


# ---------------------------------------------------------------- run

@dataclass
class RunnerResult:
    exit: int | None
    stdout: bytes
    stderr: bytes
    timed_out: bool


Runner = Callable[[list, dict, float], RunnerResult]


def docker_runner(argv: list[str], env: dict, timeout: float) -> RunnerResult:
    """Run the docker CLI; on timeout kill the container by its ``--name`` and wait for the CLI."""
    proc = subprocess.Popen(argv, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE)
    try:
        out, err = proc.communicate(timeout=timeout)
        return RunnerResult(proc.returncode, out, err, False)
    except subprocess.TimeoutExpired:
        name = _flag_value(argv, "--name")
        subprocess.run(["docker", "kill", name], env=env, stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, timeout=KILL_WAIT_S, check=False)
        try:
            out, err = proc.communicate(timeout=KILL_WAIT_S)
        except subprocess.TimeoutExpired:
            proc.kill()
            out, err = proc.communicate()
        return RunnerResult(None, out, err, True)


def fresh_run_root(base: str | None = None) -> str:
    """A new private directory with empty ``work``, ``out`` and ``in``; never an existing one."""
    root = os.path.realpath(tempfile.mkdtemp(prefix="snowball-run-", dir=base))
    if not _root_ok(root):
        shutil.rmtree(root, ignore_errors=True)
        raise ContainmentError("run root has characters the mount rule refuses: %s" % root)
    for sub in ("work", "out", "in"):
        os.mkdir(os.path.join(root, sub))
    os.chmod(os.path.join(root, "out"), 0o777)
    return root


def _open_tree(top: str) -> None:
    """Let the container user write the copied worktree (the run root itself stays private, 0700)."""
    os.chmod(top, 0o777)
    for dirpath, dirnames, filenames in os.walk(top):
        for d in dirnames:
            p = os.path.join(dirpath, d)
            if not os.path.islink(p):
                os.chmod(p, 0o777)
        for f in filenames:
            p = os.path.join(dirpath, f)
            if not os.path.islink(p):
                os.chmod(p, os.lstat(p).st_mode | 0o666)


def _sources_real(root: str, artifacts: bool) -> None:
    for sub in ("work", "out") + (("in",) if artifacts else ()):
        path = os.path.join(root, sub)
        if os.path.realpath(path) != path or not stat.S_ISDIR(os.lstat(path).st_mode):
            raise ContainmentError("mount source is not a real directory: %s" % path)


def run(job: dict, operating: dict, runner: Runner | None = None, base: str | None = None) -> dict:
    """One contained run of ``job`` = {image, cmd, tree?, artifacts?, env?, uid?, gid?}; see the docstring."""
    runner = runner or docker_runner
    lim = limits(operating, RUN_LIMITS)
    root = fresh_run_root(base)
    work, out, inp = (os.path.join(root, s) for s in ("work", "out", "in"))
    has_artifacts = bool(job.get("artifacts"))
    if job.get("tree"):
        shutil.copytree(job["tree"], work, symlinks=True, dirs_exist_ok=True)
    _open_tree(work)
    if has_artifacts:
        shutil.copytree(job["artifacts"], inp, symlinks=True, dirs_exist_ok=True)
    argv = build_argv(job["image"], job["cmd"], root, operating, env=job.get("env"),
                      uid=job.get("uid", DEFAULT_UID), gid=job.get("gid", DEFAULT_GID), artifacts=has_artifacts)
    _sources_real(root, has_artifacts)
    work_before = hash_tree(work)
    in_before = hash_tree(inp)
    result: dict[str, Any] = {"run_root": root, "argv": argv, "exit": None, "timed_out": False,
                              "files_read": None, "network_attempts": None}
    if tree_bytes(work_before) > lim["worktree_bytes"]:
        return _finish(result, "limit_hit:worktree_bytes", work_before, work_before, {}, None)
    docker_env = {"PATH": os.environ.get("PATH", os.defpath), "HOME": root}
    res = runner(argv, docker_env, lim["kos_wall_s"])
    result.update(exit=res.exit, timed_out=res.timed_out,
                  stdout_sha256=hashlib.sha256(res.stdout).hexdigest(),
                  stderr_sha256=hashlib.sha256(res.stderr).hexdigest())
    work_after, out_after, in_after = hash_tree(work), hash_tree(out), hash_tree(inp)
    status = "ok"
    if res.timed_out:
        status = "limit_hit:kos_wall_s"
    elif res.exit == 125:
        status = "runner_fault"
    if in_after != in_before:
        status = "breach:in_changed"
    elif any(e.get("unreadable") for e in list(out_after.values()) + list(work_after.values())):
        status = "unreadable_output" if status == "ok" else status
    elif status == "ok" and tree_bytes(out_after) > lim["output_bytes"]:
        status = "limit_hit:output_bytes"
    elif status == "ok" and tree_bytes(work_after) > lim["worktree_bytes"]:
        status = "limit_hit:worktree_bytes"
    return _finish(result, status, work_before, work_after, out_after, in_after)


def _finish(result: dict, status: str, work_before: dict, work_after: dict, out_after: dict,
            in_after: dict | None) -> dict:
    written = sorted(["work/" + p for p in set(work_before) | set(work_after)
                      if work_before.get(p) != work_after.get(p)] + ["out/" + p for p in out_after])
    result.update(status=status, valid=status == "ok", outputs=out_after,
                  outputs_sha256=tree_sha256(out_after), worktree_sha256=tree_sha256(work_after),
                  paths_written=written)
    return result


def red_control_reasons(red: dict) -> list[str]:
    """The red control rule, one source for the run here and for ``gate.check`` (MF8), which reads the
    recorded result: ``[]`` when the control ran (status ``ok``) and was red (an integer exit other than 0,
    125, 126, 127), ``["red_control_green"]`` on exit 0, ``["red_control_fault"]`` otherwise."""
    status, code = red.get("status"), red.get("exit")
    if status != "ok" or type(code) is not int or code in (125, 126, 127):
        return ["red_control_fault"]
    if code == 0:
        return ["red_control_green"]
    return []


def run_with_red_control(job: dict, red_control: dict, operating: dict, runner: Runner | None = None,
                         base: str | None = None) -> dict:
    """``job`` and the known bad ``red_control``, each contained; the run is valid only if the control is red."""
    if not isinstance(red_control, dict) or not red_control.get("cmd"):
        raise ContainmentError("every run carries a red control")
    if red_control.get("image") != job.get("image"):
        raise ContainmentError("the red control runs in the job's image")
    red = run(red_control, operating, runner, base)
    main = run(job, operating, runner, base)
    reasons = red_control_reasons(red)
    if not main["valid"]:
        reasons.append(main["status"])
    return {"valid": not reasons, "reasons": reasons, "result": main, "red_control": red}


# ---------------------------------------------------------------- command line

def _emit(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj, sort_keys=True) + "\n")


def main(argv: list[str]) -> int:
    if argv == ["argv"]:
        return _main_argv()
    try:
        if argv == ["check"]:
            report = check_argv(cli.loads(sys.stdin.read()))
            _emit(report)
            return 0 if report["ok"] else 1
        if len(argv) == 2 and argv[0] == "run":
            with open(argv[1], encoding="utf-8") as fh:
                req = cli.load(fh)
            report = run_with_red_control(req["job"], req.get("red_control"), req["operating"], base=req.get("base"))
            _emit(report)
            return 0 if report["valid"] else 1
        _emit({"error": "usage: python -m runner.contained argv|check|run FILE"})
        return 2
    except ContainmentError as exc:
        _emit({"error": cli.cause(exc)})
        return 1
    except (ValueError, KeyError, TypeError, OSError, RecursionError) as exc:
        _emit({"error": "unusable input: %s" % cli.cause(exc)})
        return 2


def _main_argv() -> int:
    """tohum/29f group ``contained``: stdin one run request, stdout the projection of the built argv."""
    try:
        argv = request_argv(cli.loads(sys.stdin.read()))
        _emit(project_argv(argv))
        return 0
    except ContainmentError as exc:
        _emit({"ok": False, "reason": cli.cause(exc)})
        return 1
    except (ValueError, RecursionError) as exc:  # UnusableInput, JSON errors
        _emit({"ok": False, "reason": "unusable input: %s" % cli.cause(exc)})
        return 2


def FAULT_LINE(argv: list[str]) -> dict:  # noqa: N802 - cli.run's fault line, by command
    return {"ok": False, "reason": "internal error"} if argv == ["argv"] else cli.GENERIC_LINE


if __name__ == "__main__":
    sys.exit(cli.run(main, sys.argv[1:], FAULT_LINE))
