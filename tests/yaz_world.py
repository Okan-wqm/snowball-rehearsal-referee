"""What D6 of ``yaz`` writes on, for tests: the in-process GitHub holding ``pulled``'s heads, the cycle's ``response``
and the checkout's ``setup/imports.jsonl`` (tests 46, MF17's ``yaz``; shared by test_loop_yaz and test_loop_cek's
hand-over). Every value is written here by hand.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import os

from fake_github import FakeGitHub, sha_of
from ledger import anchor, chain
from loop import cagir as CG
from target import branches as B

REPO = "acme/t1"
NOW = datetime.datetime(2026, 11, 1, 17, 0, 0, tzinfo=datetime.timezone.utc)
TS = "2026-11-01T17:00:00Z"
IDENTITY = "https://github.com/acme/referee/.github/workflows/loop.yml@refs/heads/main"
IMPORTS_ROWS = [{"ts": "2026-10-30T09:00:00Z", "stage": 0}]


def signer(available: bool = True) -> anchor.FakeSigner:
    return anchor.FakeSigner(available, IDENTITY if available else None, "rekor-yaz" if available else None)


def chained(rows: list[dict]) -> bytes:
    prev, out = chain.ZERO_HASH, b""
    for row in rows:
        row = dict(row, prev_hash=prev)
        row["row_hash"] = prev = chain.row_hash(row)
        out += (json.dumps(row) + "\n").encode()
    return out


# (A)'s ``exit.owner_exception`` as tohum/02 "Sahip istisnası" and 26d:45-47 give it: the owner's two exceptions
# of stage 0, a list in the order of ``anchor`` (the values other than ``anchor`` and ``measured`` are the tests')
OWNER_EXCEPTIONS = [
    {"anchor": "durustluk", "stage": 0, "carry_to": 1, "reason": "no plant before the stage",
     "carry_commitment": "c" * 64, "measured": False},
    {"anchor": "spec", "stage": 0, "carry_to": 1, "reason": "no machine definition of the mechanical items",
     "carry_commitment": "d" * 64, "measured": False}]


def transfer(exit_: dict | None = None, tree: str = "2" * 64) -> dict:
    """A counter whose last row is an import naming an (A) result (``harness.pass_row.imported``'s inputs):
    ``{imports, result, line_sha256}``; ``exit_`` is the result's ``exit`` object."""
    result = json.dumps({"verdict": "accepted", "exit": exit_ or {"requested": True, "transferable": True}}).encode()
    rows = IMPORTS_ROWS + [{"ts": "2026-10-30T10:00:00Z", "stage": 0, "referee_tree_sha256": tree,
                            "result_sha256": hashlib.sha256(result).hexdigest()}]
    imports = chained(rows)
    return {"imports": imports, "result": result,
            "line_sha256": hashlib.sha256(imports.rstrip(b"\n").split(b"\n")[-1]).hexdigest()}


def cost_row(row_id: str = "cagir-9-1", snapshot: str = "b" * 40, usd: int = 1234, **payload) -> dict:
    """A ``cost`` row of ``ledger.schema``'s shape, as ``loop.cagir`` records one."""
    body = dict({"tool": "llm.call", "template_sha256": "1" * 64, "model_requested": "m", "models_served": ["m"],
                 "outcome": "ok", "reason": None, "usd_micros": usd, "cost_source": "total_cost_usd",
                 "cap_usd_micros": 1_000_000, "prompt_sha256": "2" * 64, "duration_ms": 10}, **payload)
    return {"row_id": row_id, "ts": TS, "part": "cost", "kind": "cost", "payload": body, "derivation": "tool",
            "trust": "observed", "snapshot_id": snapshot, "evidence_refs": []}


def github_at(heads: dict[str, str], integration_files: dict[str, bytes], state_files: dict[str, bytes] | None = None,
              repo: str = REPO) -> FakeGitHub:
    """The fake GitHub with ``brain/state`` and ``brain/integration`` at ``heads`` (commits made up under those ids,
    each without parent), the integration commit holding ``integration_files``."""
    gh = FakeGitHub(repo, required_check=B.CHECK)
    for branch, files in ((B.STATE, state_files or {}), (B.INTEGRATION, integration_files)):
        tree = sha_of(["tree", branch])
        gh.trees[tree] = {path: gh._blob(data) for path, data in files.items()}
        gh.commits[heads[branch]] = {"tree": tree, "parents": [], "message": branch}
        gh.refs[branch] = heads[branch]
    return gh


def files_of(root: str) -> dict[str, bytes]:
    out = {}
    for dirpath, _, names in os.walk(root):
        for name in names:
            full = os.path.join(dirpath, name)
            with open(full, "rb") as fh:
                out[os.path.relpath(full, root).replace(os.sep, "/")] = fh.read()
    return out


def write_response(temp: str, target_id: str, heads: dict[str, str], rows: list[dict], at: str = "t1",
                   **over) -> str:
    """``$RUNNER_TEMP/in/response/<at>/response.json`` (``at`` the served target's directory) as ``loop.cagir.d4``
    writes it."""
    doc = dict({"schema": CG.SCHEMA, "target": target_id, "heads": heads, "rows": rows, "outcome": "ok",
                "reason": None, "sent": True, "run_valid": True, "output": {"echo": target_id},
                "models_served": ["m"], "cost_usd_micros": 1234, "prompt_sha256": "2" * 64, "dropped": []}, **over)
    root = os.path.join(temp, "in", "response", at)
    os.makedirs(root, exist_ok=True)
    with open(os.path.join(root, CG.RESPONSE), "w") as fh:
        json.dump(doc, fh)
    return root


def write_workspace(base: str) -> str:
    """The checkout (``$GITHUB_WORKSPACE``) with ``setup/imports.jsonl``."""
    root = os.path.join(base, "workspace")
    os.makedirs(os.path.join(root, "setup"), exist_ok=True)
    with open(os.path.join(root, "setup", "imports.jsonl"), "wb") as fh:
        fh.write(chained(IMPORTS_ROWS))
    return root


def env(temp: str, workspace: str, **over) -> dict[str, str]:
    return dict({"RUNNER_TEMP": temp, "WRITER_TOKEN": "x", "GITHUB_REPOSITORY": "acme/referee",
                 "GITHUB_WORKSPACE": workspace, "GITHUB_RUN_ID": "9", "GITHUB_RUN_ATTEMPT": "1"}, **over)
