"""A change to the seed's behaviour lands with its document (owner, 2026-10-30; `spec/tohum/15`).

The owner's rule: once a change is done with evidence and tests, the relevant section of the relevant document is updated
in the same batch. A machine cannot tell which section is relevant; it can tell that a push changed the referee, the
launcher, the vectors or the drill and touched no document at all. That floor is this check, run by CI on every push to
`main` over the pushed range.

    git diff --name-only <before> <after> | python3 local/doc_with_change.py

Exit 0 when no guarded path changed or a document changed with it, 1 otherwise (the guarded paths are listed).
"""

from __future__ import annotations

import sys

GUARDED = ("seed/bootstrap/snowball_bootstrap/", "seed/bootstrap/workflow/", "seed/bootstrap/vectors/",
           "seed/bootstrap/stages/", "seed/founder/", "seed/drill/")
DOCS = ("docs/", "spec/", "README.md", "seed/founder/README.md")


def is_doc(path: str) -> bool:
    return path in DOCS or any(path.startswith(d) for d in DOCS if d.endswith("/"))


def undocumented(paths: list[str]) -> list[str]:
    """The guarded paths of a change that carries no document; empty when the change is documented or guards nothing."""
    changed = [p.strip() for p in paths if p.strip()]
    guarded = [p for p in changed if p.startswith(GUARDED) and not is_doc(p)]
    if not guarded or any(is_doc(p) for p in changed):
        return []
    return guarded


def main() -> int:
    missing = undocumented(sys.stdin.read().splitlines())
    if missing:
        print("This change alters the seed's behaviour and updates no document (docs/, spec/, README.md, "
              "seed/founder/README.md). Update the section that describes it in the same push:")
        for p in missing:
            print("  " + p)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
