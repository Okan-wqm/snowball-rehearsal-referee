"""MF9 target.write: the only write path to the target, GitHub REST and Git Data API, refs/heads/brain/** only
(asama-0/14:36, tohum/26a:27,70-71).

    python -m target.write replay <api.json>   (stdin: one write request)
        -> {"ok", "refs", "writes", "commit", "forced"}

<api.json> is a recorded API {"METHOD /path": body} answered in process: a recorded call gets its body, any other
call gets 404. Outputs come from the requests sent, never from the recorded responses; `forced` says whether a
PATCH of a ref asked for force: true (no force push, tohum/07:16; E240).
"""

from __future__ import annotations

import json
import re
import sys
from typing import Any, NoReturn

BRAIN = "refs/heads/brain/"
SHA = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")
REPO = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")


class Unusable(ValueError):
    pass


class Refused(Exception):
    pass


class NotFound(Exception):
    pass


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in pairs:
        if key in out:
            raise Unusable(f"duplicate key {key!r}")
        out[key] = value
    return out


def _constant(name: str) -> Any:
    raise Unusable(f"non-finite number {name}")


def loads(data: bytes) -> Any:
    try:
        return json.loads(data.decode("utf-8"), object_pairs_hook=_pairs, parse_constant=_constant)
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise Unusable("not JSON") from exc


def ref_allowed(ref: Any) -> bool:
    """Starts with refs/heads/brain/; every component after refs/heads/ non-empty and neither '.' nor '..';
    case-sensitive."""
    if not isinstance(ref, str) or not ref.startswith(BRAIN):
        return False
    return all(part not in ("", ".", "..") for part in ref[len("refs/heads/"):].split("/"))


def _plain_ref(ref: Any) -> bool:
    """A ref that is only read (revert's onto): under refs/, no empty, '.' or '..' component."""
    return (isinstance(ref, str) and ref.startswith("refs/")
            and all(part not in ("", ".", "..") for part in ref[len("refs/"):].split("/")))


class FakeAPI:
    def __init__(self, record: dict[str, Any]):
        self.record = record
        self.writes: list[str] = []
        self.refs: list[str] = []
        self.forced = False

    def call(self, method: str, path: str, body: dict[str, Any] | None = None) -> Any:
        key = f"{method} {path}"
        if method != "GET":
            self.writes.append(key)
        if method == "PATCH" and "/git/refs/" in path and isinstance(body, dict) and body.get("force") is True:
            self.forced = True
        if key not in self.record:
            raise NotFound(key)
        return self.record[key]


def _need(cond: bool, what: str) -> None:
    if not cond:
        raise Unusable(what)


def _field(obj: Any, *keys: str) -> Any:
    for key in keys:
        if not isinstance(obj, dict) or key not in obj:
            raise Unusable(f"recorded response lacks {'.'.join(keys)}")
        obj = obj[key]
    return obj


def run(api: FakeAPI, req: dict[str, Any]) -> dict[str, Any] | None:
    """Performs the request; returns the commit body for a revert, else None."""
    op = req.get("op")
    repo = req.get("repo")
    _need(isinstance(repo, str) and bool(REPO.fullmatch(repo)) and ".." not in repo.split("/")
          and "." not in repo.split("/"), "repo is not owner/name")
    base = f"/repos/{repo}"
    if op in ("branch", "update"):
        ref, sha = req.get("ref"), req.get("sha")
        _need(isinstance(ref, str) and isinstance(sha, str) and bool(SHA.fullmatch(sha)), "ref or sha missing")
        if not ref_allowed(ref):
            raise Refused(ref)
        if op == "branch":
            api.call("POST", f"{base}/git/refs", {"ref": ref, "sha": sha})
            api.refs.append(ref)
        else:
            tail = ref[len("refs/"):]
            api.call("PATCH", f"{base}/git/refs/{tail}", {"sha": sha, "force": False})
            api.refs.append("refs/" + tail)
        return None
    if op == "pr":
        head, base_ref, title = req.get("head"), req.get("base"), req.get("title")
        _need(isinstance(head, str) and isinstance(base_ref, str) and isinstance(title, str), "head, base or title")
        if not (ref_allowed(head) and ref_allowed(base_ref)):
            raise Refused(f"{head} -> {base_ref}")
        api.call("POST", f"{base}/pulls", {"title": title, "head": head[len("refs/heads/"):],
                                           "base": base_ref[len("refs/heads/"):]})
        return None
    if op == "check":
        sha, name, conclusion = req.get("sha"), req.get("name"), req.get("conclusion")
        _need(isinstance(sha, str) and bool(SHA.fullmatch(sha)) and isinstance(name, str)
              and isinstance(conclusion, str), "sha, name or conclusion")
        api.call("POST", f"{base}/check-runs", {"name": name, "head_sha": sha, "status": "completed",
                                                "conclusion": conclusion})
        return None
    if op == "merge":
        number = req.get("pr")
        _need(isinstance(number, int) and not isinstance(number, bool) and number >= 1, "pr is not a number")
        pull = api.call("GET", f"{base}/pulls/{number}")
        head, base_ref = _field(pull, "head", "ref"), _field(pull, "base", "ref")
        _need(isinstance(head, str) and isinstance(base_ref, str), "recorded head/base ref is not a string")
        if not (ref_allowed("refs/heads/" + head) and ref_allowed("refs/heads/" + base_ref)):
            raise Refused(f"{head} -> {base_ref}")
        body: dict[str, Any] = {"merge_method": "merge"}
        head_sha = pull["head"].get("sha")
        if isinstance(head_sha, str):
            body["sha"] = head_sha
        api.call("PUT", f"{base}/pulls/{number}/merge", body)
        api.refs.append("refs/heads/" + base_ref)
        return None
    if op == "revert":
        merge_sha, onto, ref = req.get("merge_sha"), req.get("onto"), req.get("ref")
        _need(isinstance(merge_sha, str) and bool(SHA.fullmatch(merge_sha)) and _plain_ref(onto)
              and isinstance(ref, str), "merge_sha, onto or ref")
        if not ref_allowed(ref):
            raise Refused(ref)
        merge = api.call("GET", f"{base}/git/commits/{merge_sha}")
        parents = _field(merge, "parents")
        _need(isinstance(parents, list) and len(parents) >= 1, "merge commit has no parents")
        first = _field(parents[0], "sha")
        _need(isinstance(first, str) and bool(SHA.fullmatch(first)), "first parent sha")
        tree = _field(api.call("GET", f"{base}/git/commits/{first}"), "tree", "sha")
        head = _field(api.call("GET", f"{base}/git/ref/{onto[len('refs/'):]}"), "object", "sha")
        _need(isinstance(tree, str) and isinstance(head, str), "tree or head sha")
        commit = {"message": f"Revert {merge_sha}", "tree": tree, "parents": [head]}
        created = _field(api.call("POST", f"{base}/git/commits", commit), "sha")
        _need(isinstance(created, str), "new commit sha")
        api.call("POST", f"{base}/git/refs", {"ref": ref, "sha": created})
        api.refs.append(ref)
        return {"tree": tree, "parents": [head]}
    raise Unusable(f"unknown op {op!r}")


def _emit(obj: dict[str, Any], code: int) -> NoReturn:
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()
    sys.exit(code)


def main(argv: list[str]) -> None:
    if len(argv) != 2 or argv[0] != "replay":
        _emit({"ok": False, "refs": [], "writes": [], "commit": None, "forced": False,
               "error": "usage: replay <api.json>"}, 2)
    api = None
    try:
        with open(argv[1], "rb") as fh:
            record = loads(fh.read())
        _need(isinstance(record, dict), "api.json is not an object")
        req = loads(sys.stdin.buffer.read())
        _need(isinstance(req, dict), "stdin is not one request object")
        api = FakeAPI(record)
        commit = run(api, req)
    except Refused as exc:
        _emit({"ok": False, "refs": [], "writes": [], "commit": None, "forced": False, "refused": str(exc)}, 1)
    except (OSError, Unusable, NotFound) as exc:
        done = api if api is not None else FakeAPI({})
        _emit({"ok": False, "refs": sorted(done.refs), "writes": done.writes, "commit": None, "forced": done.forced,
               "error": f"{type(exc).__name__}: {exc}"}, 2)
    _emit({"ok": True, "refs": sorted(api.refs), "writes": api.writes, "commit": commit, "forced": api.forced}, 0)


if __name__ == "__main__":
    main(sys.argv[1:])
