"""What kind of push is this (`tohum/29b`, "İki tür push")?"""

from __future__ import annotations

import re

SPEC_STAGE_RE = re.compile(r"^spec/asama-\d+/")
SPEC_INDEX = "spec/INDEX.md"
LEDGER_FILE = "founder-ledger.jsonl"
REPORTS_DIR = "reports/"

# Reasons are stable identifiers; they appear in rejection artefacts the founder reads.
SEED_MODIFIED = "seed_modified"
ROOT_WORKFLOW_MODIFIED = "root_workflow_modified"
MIXED = "mixed_spec_and_code"


def is_spec_path(path: str) -> bool:
    return bool(SPEC_STAGE_RE.match(path)) or path == SPEC_INDEX


SEED_DIRS = ("spec/tohum", "seed")  # what a seed epoch delivers into the brain (`25` 10b)


def is_seed_path(path: str) -> bool:
    return any(path.startswith(d + "/") for d in SEED_DIRS)


def is_founder_record(path: str) -> bool:
    """The Founder's memory and reports: neither spec nor code. They never turn a spec request into a mixed one,
    and a push of nothing else is not judged (`29b`, "Push türleri"; the `ledger` push of the narrowed Stage 0)."""
    return path == LEDGER_FILE or path.startswith(REPORTS_DIR)


# Agent configuration (`29f`, `14`, `24a`): a component `.claude`, `.vscode` or `.devcontainer`, or a last component
# `CLAUDE.md`, `AGENTS.md`, `.mcp.json` or `.envrc`, in any case and at any depth.
AGENT_DIRS = frozenset({".claude", ".vscode", ".devcontainer"})
AGENT_FILES = frozenset({"claude.md", "agents.md", ".mcp.json", ".envrc"})


def is_agent_config(path: str) -> bool:
    parts = [part.casefold() for part in path.split("/") if part]
    return any(part in AGENT_DIRS for part in parts) or (bool(parts) and parts[-1] in AGENT_FILES)


def classify(changed: list[str]) -> tuple[str, list[str]]:
    """Return (kind, reasons). kind is one of none, spec, code, rejected."""
    reasons: set[str] = set()
    spec = code = False
    for path in changed:
        if is_founder_record(path):
            continue
        if path.startswith("seed/") or (path.startswith("spec/") and not is_spec_path(path)):
            reasons.add(SEED_MODIFIED)  # spec/tohum/**, any other non-stage spec path, the bootstrap
        elif path.startswith(".github/"):
            reasons.add(ROOT_WORKFLOW_MODIFIED)
        elif is_spec_path(path):
            spec = True
        else:
            code = True
    if spec and code:
        reasons.add(MIXED)
    if reasons:
        return "rejected", sorted(reasons)
    if not (spec or code):
        return "none", []
    return ("spec" if spec else "code"), []


def spec_stage_dirs(changed: list[str]) -> list[str]:
    """Stage directories a spec request touches, e.g. ``spec/asama-0``."""
    dirs = {"/".join(p.split("/")[:2]) for p in changed if SPEC_STAGE_RE.match(p)}
    return sorted(dirs)
