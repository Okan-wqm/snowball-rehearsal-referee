"""Path rules shared by profile.derive, profile.unit_verify and gate.diffguard.

Agent configuration (tohum/14:49-51): a path any of whose components equals, ignoring case, .claude,
.vscode or .devcontainer, or whose last component equals, ignoring case, CLAUDE.md, AGENTS.md, .mcp.json
or .envrc. Coverage: an entry e covers path p iff p == e.rstrip('/') or p starts with e.rstrip('/') + '/'
(case-sensitive, on the path as written).
"""

AGENT_DIRS = (".claude", ".vscode", ".devcontainer")
AGENT_FILES = ("CLAUDE.md", "AGENTS.md", ".mcp.json", ".envrc")


def same_ignoring_case(a: str, b: str) -> bool:
    # Fail closed: equal under Unicode case folding or under upper-casing (the two common
    # case-insensitive comparisons; for ASCII names they agree).
    return a.casefold() == b.casefold() or a.upper() == b.upper()


def components(path: str) -> list:
    return [c for c in path.split("/") if c != ""]


def is_agent_config(path: str) -> bool:
    comps = components(path)
    if any(same_ignoring_case(c, d) for c in comps for d in AGENT_DIRS):
        return True
    return bool(comps) and any(same_ignoring_case(comps[-1], f) for f in AGENT_FILES)


def covers(entry: str, path: str) -> bool:
    e = entry.rstrip("/")
    return path == e or path.startswith(e + "/")
