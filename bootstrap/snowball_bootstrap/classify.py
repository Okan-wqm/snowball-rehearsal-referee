"""What kind of push is this (`tohum/29b`, "İki tür push")?"""

from __future__ import annotations

import re

SPEC_STAGE_RE = re.compile(r"^spec/asama-\d+/")
SPEC_INDEX = "spec/INDEX.md"

# Reasons are stable identifiers; they appear in rejection artefacts the founder reads.
SEED_MODIFIED = "seed_modified"
ROOT_WORKFLOW_MODIFIED = "root_workflow_modified"
MIXED = "mixed_spec_and_code"


def is_spec_path(path: str) -> bool:
    return bool(SPEC_STAGE_RE.match(path)) or path == SPEC_INDEX


def classify(changed: list[str]) -> tuple[str, list[str]]:
    """Return (kind, reasons). kind is one of none, spec, code, rejected."""
    if not changed:
        return "none", []
    reasons: set[str] = set()
    spec = code = False
    for path in changed:
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
    return ("spec" if spec else "code"), []


def spec_stage_dirs(changed: list[str]) -> list[str]:
    """Stage directories a spec request touches, e.g. ``spec/asama-0``."""
    dirs = {"/".join(p.split("/")[:2]) for p in changed if SPEC_STAGE_RE.match(p)}
    return sorted(dirs)
