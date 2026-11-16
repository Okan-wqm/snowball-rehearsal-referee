"""The exit request's container canary (seed-058, `29z`): one real contained run before (B).

Nothing before the live loop started a real container from the brain's `referee/`: the brain's own tests run inside
the `kos` sandbox, where `runner.contained` can start none, so its MF3 met the host only in (B), and three (B) attempts
ended on host facts no stand-in carried (an image the host did not hold, the container's uid against the job's). When
the push is an exit request, the `kanarya` job runs the brain's own MF3 once, on the GitHub runner, outside any
container and with no secret and no permission: `python -m runner.contained run <request>` from the pulled tree's
`referee/`, in the image of the toy's unit recipe, with a canary command and a red control. What it answers is the
brain's own report; a red one keeps the exit closed as `canary:<status>` in `exit.missing`, never as a crash of the
run. A false green buys nothing: (B) runs the real loop.

The job's output is written on a host where brain code ran, so `decide` reads it as untrusted text: only short tokens
of `TOKEN`, at most `MAX_STATUSES` of them; anything else is `malformed`.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from . import config
from .treehash import TreeError, iter_files

TOY = "toy"
UNITS_FILE = "targets/{id}/units.json"  # the brain's recipe proposal (`26c` "Birim tarifi")
IMAGE = re.compile(r"[a-z0-9][a-z0-9._/-]*(?::[A-Za-z0-9._-]+)?@sha256:[0-9a-f]{64}\Z")
COMMAND = ("python3", "-m", "runner.contained", "run")  # run from the pulled tree's `referee/` (`29z`)
TIMEOUT_S = 900  # the whole brain command: it may pull the image first; the job's limit is 30 minutes
SECRET_NAME = "SNOWBALL_CANARY_SECRET"  # set for the brain's process only; the container must not see it
BREACH_EXIT = 3  # the canary command's exit when one of its three attempts succeeded
# What the canary command does inside the container (Node: Stage 0's unit image is the official Node image, `26c`):
# reads the host's planted variable, writes outside its two writable directories, connects out; writes its finding to
# /out as a private file (0600, as mkstemp makes one) and ends 0 when all three attempts failed, 3 when one succeeded.
SCRIPT = (
    'const fs=require("fs"),net=require("net");const found=[];'
    'if(Object.prototype.hasOwnProperty.call(process.env,"' + SECRET_NAME + '"))found.push("env");'
    'try{fs.writeFileSync("/snowball-canary","x");found.push("write")}catch(e){}'
    'let done=false;const s=net.connect({host:"1.1.1.1",port:443});'
    'function end(open){if(done)return;done=true;if(open)found.push("network");s.destroy();'
    'fs.writeFileSync("/out/canary.json",JSON.stringify({breach:found})+"\\n",{mode:0o600});'
    'process.exit(found.length?' + str(BREACH_EXIT) + ':0)}'
    's.on("connect",()=>end(true));s.on("error",()=>end(false));setTimeout(()=>end(false),5000);'
)
CANARY_CMD = ["node", "-e", SCRIPT]
RED_CMD = ["node", "-e", "process.exit(1)"]  # the red control: a run whose command must end red

TOKEN = re.compile(r"[a-z0-9_]+(?::[a-z0-9_]+)?\Z")
MAX_TOKEN = 32  # a token is a status, never a value: too short to hold a secret's shape (`gh?_` + 36 is 40)
MAX_STATUSES = 8
OK = "ok"
MALFORMED = "malformed"
JOB_RESULTS = ("success", "failure", "cancelled", "skipped")
DETAIL = ("the brain's `python -m runner.contained run`, outside any container, in the toy's unit image, with the "
          "canary command and a red control (tohum/29z)")


def toy_image(root: Path, tar_bytes: bytes) -> str | None:
    """The image of the toy's unit recipe in the pulled tree: `targets/<toy id>/units.json`'s first unit's
    ``env_image``, pinned by digest; None when the summary names no single toy or the recipe gives no such image."""
    try:
        toys = [t for t in config.load_summary(root).targets or () if t.kind == TOY]
        wanted = UNITS_FILE.format(id=toys[0].id) if len(toys) == 1 else None
        raw = next((content for path, content, _exec in iter_files(tar_bytes) if path.as_posix() == wanted), None)
    except (config.ConfigError, TreeError):
        return None
    try:
        units = json.loads(raw.decode("utf-8"))["units"] if raw is not None else None
        image = units[0]["env_image"]
    except (ValueError, UnicodeDecodeError, KeyError, IndexError, TypeError):
        return None
    return image if isinstance(image, str) and IMAGE.match(image) else None


def operating(root: Path) -> dict[str, Any]:
    """The referee policy's `operating` section as it is, `{}` when it has none (E579): the brain's run reads it."""
    try:
        section = json.loads((root / "policy.json").read_text(encoding="utf-8")).get("operating")
    except (OSError, ValueError, AttributeError):
        return {}
    return section if isinstance(section, dict) else {}


def request(image: str, policy_operating: dict[str, Any]) -> dict[str, Any]:
    """The request file `run` reads (`29z`): the canary job and its red control in the same image, and the limits."""
    return {"job": {"image": image, "cmd": list(CANARY_CMD)},
            "red_control": {"image": image, "cmd": list(RED_CMD)},
            "operating": policy_operating}


def _token(value: Any) -> bool:
    return isinstance(value, str) and len(value) <= MAX_TOKEN and TOKEN.match(value) is not None


def status_of(stdout: bytes, timed_out: bool) -> list[str]:
    """What the brain's answer says, as tokens: its last non-blank stdout line, a JSON object with ``valid``,
    ``reasons`` and ``result.exit`` (`29z`). ``ok`` only when the run is valid and the canary ended 0."""
    if timed_out:
        return ["timeout"]
    lines = [line for line in stdout.decode("utf-8", "replace").splitlines() if line.strip()]
    try:
        answer = json.loads(lines[-1]) if lines else None
    except (ValueError, RecursionError):
        answer = None
    if not isinstance(answer, dict) or not isinstance(answer.get("valid"), bool):
        return ["no_answer"]
    if not answer["valid"]:
        reasons = answer.get("reasons")
        found = sorted({r for r in reasons if _token(r) and r != OK}) if isinstance(reasons, list) else []
        return found[:MAX_STATUSES] or ["invalid"]
    result = answer.get("result")
    code = result.get("exit") if isinstance(result, dict) else None
    if type(code) is not int or not 0 <= code <= 255:
        return [MALFORMED]
    if code == 0:
        return [OK]
    return ["breach"] if code == BREACH_EXIT else [f"exit_{code}"]


def run(root: Path, tar_bytes: bytes, tree: Path, work: Path, timeout_s: int = TIMEOUT_S) -> list[str]:
    """The canary in this job: the brain's command from ``tree``/referee, its environment only ``PATH``, a fresh
    ``HOME`` and the planted variable (nothing of GitHub's), the request in ``work``."""
    image = toy_image(root, tar_bytes)
    if image is None:
        return ["no_recipe"]
    work.mkdir(parents=True, exist_ok=True)
    req = work / "canary-request.json"
    req.write_text(json.dumps(request(image, operating(root))), encoding="utf-8")
    home = Path(tempfile.mkdtemp(prefix="canary-home-", dir=work))
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(home), SECRET_NAME: secrets.token_hex(16),
           "PYTHONDONTWRITEBYTECODE": "1"}
    if os.name == "nt":  # a Windows interpreter does not start without it; the job itself runs on Linux
        env["SYSTEMROOT"] = os.environ.get("SYSTEMROOT", r"C:\Windows")
    argv = [sys.executable if COMMAND[0] == "python3" else COMMAND[0], *COMMAND[1:], str(req.resolve())]
    try:
        proc = subprocess.run(argv, cwd=tree / "referee", env=env, stdin=subprocess.DEVNULL, capture_output=True,
                              timeout=timeout_s, check=False)
    except subprocess.TimeoutExpired:
        return status_of(b"", True)
    except OSError:  # no referee/ in the tree, or no interpreter: no answer
        return ["no_answer"]
    return status_of(proc.stdout, False)


def record(job: Any, line: Any) -> dict[str, Any]:
    """What the signed result keeps of the canary: the job's result and the statuses its output names, read as
    untrusted text. A job that did not succeed has no statuses."""
    job = job if job in JOB_RESULTS else "none"
    if job != "success":
        return {"job": job, "status": []}
    tokens = line.split(",") if isinstance(line, str) else []
    if (not tokens or len(tokens) > MAX_STATUSES or not all(_token(t) for t in tokens)
            or len(set(tokens)) != len(tokens) or (OK in tokens and len(tokens) > 1)):
        return {"job": job, "status": [MALFORMED]}
    return {"job": job, "status": tokens}


def missing(rec: dict[str, Any]) -> list[str]:
    """The exit's missing entries for the canary: none when it ran and said ``ok``."""
    if rec["job"] != "success":
        return [f"canary:job_{rec['job']}"]
    return [f"canary:{s}" for s in rec["status"] if s != OK]
