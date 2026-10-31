"""Snowball's system map (owner rule E301): what connects to what, drawn from the code and never by hand. Stdlib only.

    python3 local/system_map.py            # from seed/bootstrap: writes docs/harita.md
    python3 local/system_map.py --check    # exit 1 when docs/harita.md is not what the code draws

Nothing is run; three sources are read. `workflow/bootstrap.yml`: the referee's jobs, their `needs:`, the
`-m snowball_bootstrap <command>` lines each job runs, its permissions and secrets (a line reader for the few keys it
needs; the seed's own YAML subset reader, `wiring.parse`, refuses this file's folded blocks on purpose). The modules of
`snowball_bootstrap/`: their imports inside the package and the sibling scripts they start, read with `ast`; `cli.py`'s
subcommands and the modules each command's handler reaches. `seed/founder/launch.py`: the referee modules it imports.

The hand-written part is the block below: the actors outside the code (operator, brain repository, rival model, Rekor),
the links that meet them, and which area of the package a module belongs to. Each link names the file and the text
that prove it; when the text is gone the map is not drawn (ValueError), so a link cannot outlive the code it describes.
`tests/test_wiring.py` (`SystemMapTest`) regenerates the page in memory and fails when the committed one differs.
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

BOOT = Path(__file__).resolve().parents[1]
ROOT = BOOT.parents[1]
OUT = "docs/harita.md"
WORKFLOW = "seed/bootstrap/workflow/bootstrap.yml"
PACKAGE = "seed/bootstrap/snowball_bootstrap"
LAUNCHER = "seed/founder/launch.py"
SCORECARD = "seed/founder/scorecard.py"  # the operator's self-improvement card (E310), outside the launcher's loop
CAPSULE = ("seed/founder/Dockerfile", "seed/founder/entrypoint.sh", "seed/founder/prompt.md")

# ---- The hand-written part: actors outside the code, the links that meet them, the package's areas. ----------------
# Endpoints: an actor below, "launcher", "capsule", "referee" (the workflow as a whole) or "job:<regex>" (every job
# whose text matches; at least one must). Evidence: (file, regex) that must be found, or the map is not drawn.
ACTORS = {
    "operator": ("stadium", "Operator"),
    "brain": ("cylinder", "Brain repository (GitHub)"),
    "rival": ("hexagon", "Rival model (Claude, operator's login)"),
    "rekor": ("cylinder", "Rekor (Sigstore transparency log)"),
}
LINKS = (
    ("operator", "launcher", "starts the pilot", (LAUNCHER, r"on the operator's machine")),
    ("launcher", "capsule", "docker run: one Founder session", (LAUNCHER, r'"docker", "run"')),
    ("capsule", "brain", "git push", (CAPSULE[1], r"push")),
    ("launcher", "referee", "dispatch: gh workflow run", (LAUNCHER, r'"gh", "workflow", "run"')),
    ("brain", r"job:-m snowball_bootstrap pull\b", "read anonymously", (WORKFLOW, r"the brain is read anonymously")),
    (r"job:secrets\.CLAUDE_CODE_OAUTH_TOKEN", "rival", "claude CLI: claims and reproducers",
     (PACKAGE + "/rival.py", r"resolve_claude")),
    (r"job:-m sigstore sign", "rekor", "signs result.json, keyless", (WORKFLOW, r"Sign the result into Rekor")),
    (r"job:-m sigstore sign", "launcher", "signed verdict: bootstrap-state artifact",
     (LAUNCHER, r'STATE_ARTIFACT = "bootstrap-state"')),
    ("launcher", "capsule", "last verdict, read-only: /work/referee", (CAPSULE[2], r"/work/referee/result\.json")),
    ("operator", "brain", "seed epoch: delivers spec/tohum and seed/", ("seed/founder/README.md", r"Tohum teslimi")),
    ("operator", "referee", "installs bootstrap/, vectors/, kill switch, seed_epochs row",
     (WORKFLOW, r"all written by the operator")),
    ("operator", "scorecard", "after each cycle: docs/karne.md", (SCORECARD, r"--public docs/karne")),
    (r"job:-m sigstore sign", "scorecard", "signed results, digest-checked, cached",
     (SCORECARD, r'STATE_ARTIFACT = "bootstrap-state"')),
    ("brain", "scorecard", "ledger, chain verified, and test manifests", (SCORECARD, r"def verify_chain")),
)
# Which area of the referee package a module belongs to (a role, which the code cannot say). A module missing here is
# drawn under UNPLACED, so a new module shows up on the map before anyone files it.
AREAS = (
    ("Entry", ("__init__", "__main__", "cli")),
    ("Intake", ("canon", "classify", "config", "ghapi", "gitio", "importer", "licenses", "treehash")),
    ("Sandbox", ("container", "controls", "manifest", "moduleless", "vectors")),
    ("Rival", ("reproduce", "rival", "rival_mcp", "secretscan")),
    ("Judgement", ("decide", "exitchecks", "ledgercheck", "stages", "state", "wiring")),
)
UNPLACED = "Unplaced"
# ---------------------------------------------------------------------------------------------------------------------

EDGE_LABEL_RE = re.compile(r"[A-Za-z0-9 ,.:/_=+-]+\Z")
SHAPES = {"stadium": '(["{}"])', "cylinder": '[("{}")]', "hexagon": '{{{{"{}"}}}}', "box": '["{}"]'}
COMMAND_RE = re.compile(r"-m\s+snowball_bootstrap\s+([a-z][a-z0-9-]*)")
KEY_RE = re.compile(r"([A-Za-z_][A-Za-z0-9_-]*):(?:\s+(.*))?\Z")


class Sources:
    """Reads the repository's files as text (universal newlines, so a CRLF checkout draws the same map). ``overrides``
    replaces a file's text by its repository path, for tests."""

    def __init__(self, root: Path = ROOT, overrides: dict[str, str] | None = None):
        self.root, self.overrides = root, dict(overrides or {})

    def read(self, rel: str) -> str:
        if rel in self.overrides:
            return self.overrides[rel]
        return (self.root / rel).read_text(encoding="utf-8")

    def modules(self) -> list[str]:
        return sorted(p.stem for p in (self.root / PACKAGE).glob("*.py"))


# ---- The workflow ----------------------------------------------------------------------------------------------------

class Job:
    def __init__(self, name: str, lines: list[str]):
        self.name, self.lines = name, lines
        self.text = "\n".join(lines)
        self.needs: list[str] = []
        self.permissions = ""
        self.commands = list(dict.fromkeys(COMMAND_RE.findall(self.text)))
        self.secrets = sorted(set(re.findall(r"secrets\.([A-Za-z0-9_]+)", self.text)))
        indent = min(_indent(line) for line in lines) if lines else 0
        for i, line in enumerate(lines):
            m = KEY_RE.fullmatch(line.strip()) if _indent(line) == indent else None
            if not m or m.group(1) not in ("needs", "permissions"):
                continue
            value, block = (m.group(2) or "").strip(), _block(lines, i, indent)
            if m.group(1) == "needs":
                self.needs = _sequence(value, block)
            else:
                self.permissions = value or ", ".join(b.strip() for b in block)


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _block(lines: list[str], at: int, indent: int) -> list[str]:
    """The lines nested under the key on line ``at``."""
    out = []
    for line in lines[at + 1:]:
        if _indent(line) <= indent:
            break
        out.append(line)
    return out


def _sequence(value: str, block: list[str]) -> list[str]:
    if value.startswith("[") and value.endswith("]"):
        items = value[1:-1].split(",")
    elif value:
        items = [value]
    else:
        items = [b.strip()[1:] for b in block if b.strip().startswith("-")]
    return [i.strip().strip("'\"") for i in items if i.strip()]


def workflow_jobs(text: str) -> dict[str, Job]:
    """The jobs of a workflow, in file order. Whole-line comments are dropped (a shell comment in a script is not run)."""
    lines = [line for line in text.splitlines() if line.strip() and not line.lstrip().startswith("#")]
    if "jobs:" not in lines:
        raise ValueError("the workflow has no top-level `jobs:`")
    body = []
    for line in lines[lines.index("jobs:") + 1:]:
        if _indent(line) == 0:
            break
        body.append(line)
    if not body:
        raise ValueError("the workflow's `jobs:` is empty")
    indent = min(_indent(line) for line in body)
    jobs: dict[str, list[str]] = {}
    for line in body:
        if _indent(line) == indent:
            m = KEY_RE.fullmatch(line.strip())
            if not m or m.group(2):
                raise ValueError(f"not a job key: {line.strip()!r}")
            jobs[m.group(1)] = []
        else:
            jobs[next(reversed(jobs))].append(line)
    found = {name: Job(name, lines) for name, lines in jobs.items()}
    for job in found.values():
        for need in job.needs:
            if need not in found:
                raise ValueError(f"job {job.name} needs {need}, which is not a job")
    return found


def reduced_needs(jobs: dict[str, Job]) -> list[tuple[str, str]]:
    """``needs`` edges without those another path already implies (the drawing; the table keeps every one)."""
    def reach(start: str) -> set[str]:
        seen, todo = set(), list(jobs[start].needs)
        while todo:
            n = todo.pop()
            if n not in seen:
                seen.add(n)
                todo.extend(jobs[n].needs)
        return seen
    edges = []
    for job in jobs.values():
        for need in job.needs:
            if not any(need in reach(other) for other in job.needs if other != need):
                edges.append((need, job.name))
    return edges


# ---- The package -----------------------------------------------------------------------------------------------------

class Module:
    def __init__(self, name: str, source: str, package: set[str]):
        self.name, self.tree = name, ast.parse(source)
        self.doc = _first_sentence(ast.get_docstring(self.tree) or "")
        self.imports: dict[str, list[str]] = {}  # module -> names taken from it
        self.bound: dict[str, str] = {}  # local name -> the package module it comes from
        self.starts = sorted({n.value[:-3] for n in ast.walk(self.tree) if isinstance(n, ast.Constant)
                              and isinstance(n.value, str) and n.value.endswith(".py") and n.value[:-3] in package
                              and n.value[:-3] != name})
        for node in ast.walk(self.tree):
            if isinstance(node, ast.ImportFrom):
                base = _package_module(node, package)
                if base is None:
                    continue
                for alias in node.names:
                    if base == "" and alias.name in package:  # from . import x
                        self._take(alias.name, "", alias.asname or alias.name)
                    elif base:
                        self._take(base, alias.name, alias.asname or alias.name)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    parts = alias.name.split(".")
                    if parts[0] == "snowball_bootstrap" and len(parts) > 1 and parts[1] in package:
                        self._take(parts[1], "", alias.asname or alias.name)

    def _take(self, module: str, name: str, local: str) -> None:
        names = self.imports.setdefault(module, [])
        if name and name not in names:
            names.append(name)
        self.bound[local] = module


def _package_module(node: ast.ImportFrom, package: set[str]) -> str | None:
    """'' for ``from . import x`` or ``from snowball_bootstrap import x``; the module for ``from .m`` or
    ``from snowball_bootstrap.m``; None for anything outside the package."""
    if node.level == 1:
        return node.module or ""
    if node.level == 0 and node.module and node.module.split(".")[0] == "snowball_bootstrap":
        rest = node.module.split(".")[1:]
        return rest[0] if rest and rest[0] in package else ("" if not rest else None)
    return None


def _first_sentence(doc: str) -> str:
    para = " ".join(doc.strip().split("\n\n")[0].split())
    m = re.search(r"[.!?](?=\s|$)", para)
    text = para[:m.end()] if m else para
    return text if len(text) <= 180 else text[:177].rsplit(" ", 1)[0] + " ..."


def module_graph(src: Sources) -> dict[str, Module]:
    names = src.modules()
    package = set(names)
    return {name: Module(name, src.read(f"{PACKAGE}/{name}.py"), package) for name in names}


def cli_commands(cli: Module) -> dict[str, str]:
    """``cli.py``'s subcommands: every ``add("<command>", <handler>, ...)`` call in ``build_parser``."""
    handlers = {n.name for n in cli.tree.body if isinstance(n, ast.FunctionDef)}
    build = next((n for n in cli.tree.body if isinstance(n, ast.FunctionDef) and n.name == "build_parser"), None)
    if build is None:
        raise ValueError("cli.py has no build_parser")
    found = {}
    for node in ast.walk(build):
        if (isinstance(node, ast.Call) and len(node.args) >= 2 and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str) and isinstance(node.args[1], ast.Name)
                and node.args[1].id in handlers):
            found[node.args[0].value] = node.args[1].id
    return found


def reached(cli: Module, handler: str) -> list[str]:
    """The package modules a handler uses, through the helpers of ``cli.py`` it calls."""
    funcs = {n.name: n for n in cli.tree.body if isinstance(n, ast.FunctionDef)}
    seen, todo, modules = set(), [handler], set()
    while todo:
        name = todo.pop()
        if name in seen:
            continue
        seen.add(name)
        for node in ast.walk(funcs[name]):
            if isinstance(node, ast.Name):
                if node.id in cli.bound:
                    modules.add(cli.bound[node.id])
                elif node.id in funcs:
                    todo.append(node.id)
    return sorted(modules)


def area_of(name: str) -> str:
    return next((area for area, members in AREAS if name in members), UNPLACED)


# ---- Drawing ---------------------------------------------------------------------------------------------------------

def _id(prefix: str, name: str) -> str:
    return prefix + re.sub(r"[^A-Za-z0-9_]", "_", name)


def _node(node_id: str, label: str, shape: str = "box") -> str:
    return node_id + SHAPES[shape].format(label.replace('"', "#quot;"))


def _edge(a: str, b: str, label: str = "", dotted: bool = False) -> str:
    if label and not EDGE_LABEL_RE.match(label):
        raise ValueError(f"edge label {label!r} has a character Mermaid may misread")
    arrow = "-.->" if dotted else "-->"
    return f"{a} {arrow}|{label}| {b}" if label else f"{a} {arrow} {b}"


def _cell(text: str) -> str:
    return text.replace("|", "\\|")


def _ticks(items: list[str]) -> str:
    return ", ".join(f"`{i}`" for i in items) if items else "-"


def _fence(lines: list[str]) -> list[str]:
    return ["```mermaid", *lines, "```", ""]


def _jobs_of(endpoint: str, jobs: dict[str, Job]) -> list[str]:
    pattern = re.compile(endpoint[len("job:"):])
    hits = [j.name for j in jobs.values() if pattern.search(j.text)]
    if not hits:
        raise ValueError(f"no job of {WORKFLOW} matches the map's endpoint {endpoint!r}")
    return hits


def _ends(endpoint: str, jobs: dict[str, Job]) -> list[str]:
    if endpoint.startswith("job:"):
        return [_id("job_", j) for j in _jobs_of(endpoint, jobs)]
    if endpoint in ACTORS or endpoint in ("launcher", "capsule", "referee", "scorecard"):
        return [endpoint]
    raise ValueError(f"unknown endpoint {endpoint!r}")


def system_flow(src: Sources, jobs: dict[str, Job]) -> tuple[list[str], int, int]:
    for rel in (LAUNCHER, SCORECARD, *CAPSULE):
        src.read(rel)  # a missing file stops the drawing
    lines = ["flowchart LR"]
    lines += ["  " + _node(a, label, shape) for a, (shape, label) in ACTORS.items()]
    lines.append("  subgraph machine[\"Operator's machine\"]")
    lines.append("    " + _node("launcher", "launcher<br/>seed/founder/launch.py"))
    lines.append("    " + _node("capsule", "Founder capsule, Docker<br/>" + " · ".join(Path(p).name for p in CAPSULE)))
    lines.append("    " + _node("scorecard", "scorecard<br/>" + SCORECARD))
    lines.append("  end")
    lines.append('  subgraph referee["Referee repository: workflow/bootstrap.yml on GitHub Actions"]')
    for job in jobs.values():
        lines.append("    " + _node(_id("job_", job.name), f"job {job.name}<br/>" + (" · ".join(job.commands) or "-")))
    lines.append("  end")
    needs = reduced_needs(jobs)
    lines += ["  " + _edge(_id("job_", a), _id("job_", b)) for a, b in needs]
    count = 0
    for a, b, label, (rel, pattern) in LINKS:
        if not re.search(pattern, src.read(rel)):
            raise ValueError(f"the map's link {a} -> {b} ({label}) has lost its evidence: {pattern!r} in {rel}")
        for x in _ends(a, jobs):
            for y in _ends(b, jobs):
                lines.append("  " + _edge(x, y, label, dotted=True))
                count += 1
    nodes = len(ACTORS) + 3 + len(jobs)
    return lines, nodes, len(needs) + count


def area_overview(mods: dict[str, Module]) -> tuple[list[str], int, int]:
    counts: dict[tuple[str, str], int] = {}
    for m in mods.values():
        for target in m.imports:
            a, b = area_of(m.name), area_of(target)
            if a != b:
                counts[(a, b)] = counts.get((a, b), 0) + 1
    areas = [a for a, _ in AREAS] + ([UNPLACED] if any(area_of(n) == UNPLACED for n in mods) else [])
    lines = ["flowchart LR"]
    for area in areas:
        size = sum(1 for n in mods if area_of(n) == area)
        lines.append("  " + _node(_id("a_", area), f"{area}<br/>{size} modules"))
    lines += ["  " + _edge(_id("a_", a), _id("a_", b), str(n)) for (a, b), n in sorted(counts.items())]
    return lines, len(areas), len(counts)


def area_diagram(area: str, mods: dict[str, Module]) -> tuple[list[str], int]:
    own = [n for n in mods if area_of(n) == area]
    edges = [(n, t, False) for n in own for t in sorted(mods[n].imports)] + [(n, t, True) for n in own for t in mods[n].starts]
    outside = sorted({t for _, t, _ in edges if area_of(t) != area}, key=lambda t: (area_of(t), t))
    lines = ["flowchart LR", f'  subgraph {_id("a_", area)}["{area}"]']
    lines += ["    " + _node(_id("m_", n), n) for n in own]
    lines.append("  end")
    for other in dict.fromkeys(area_of(t) for t in outside):
        lines.append(f'  subgraph {_id("a_", other)}["{other}"]')
        lines += ["    " + _node(_id("m_", t), t) + ":::outside" for t in outside if area_of(t) == other]
        lines.append("  end")
    lines += ["  " + _edge(_id("m_", a), _id("m_", b), "starts as a process" if dotted else "", dotted)
              for a, b, dotted in edges]
    lines.append("  classDef outside stroke-dasharray: 4 3")
    return lines, len(edges)


def launcher_diagram(src: Sources, mods: dict[str, Module]) -> tuple[list[str], list[str], list[str]]:
    launcher = Module("launch", src.read(LAUNCHER), set(mods))
    lines = ["flowchart LR", "  " + _node("launcher", "seed/founder/launch.py")]
    lines.append('  subgraph pkg["snowball_bootstrap"]')
    lines += ["    " + _node(_id("m_", t), t) for t in launcher.imports]
    lines.append("  end")
    lines += ["  " + _edge("launcher", _id("m_", t), ", ".join(names) or "module") for t, names in
              launcher.imports.items()]
    closure, todo = set(), list(launcher.imports)
    while todo:
        n = todo.pop()
        if n not in closure:
            closure.add(n)
            todo.extend(mods[n].imports)
    return lines, list(launcher.imports), sorted(closure)


def render(src: Sources | None = None) -> str:
    src = src or Sources()
    jobs = workflow_jobs(src.read(WORKFLOW))
    mods = module_graph(src)
    commands = cli_commands(mods["cli"])
    for area, members in AREAS:
        for name in members:
            if name not in mods:
                raise ValueError(f"AREAS places {name} in {area}, but {PACKAGE}/{name}.py does not exist")
    for job in jobs.values():
        for command in job.commands:
            if command not in commands:
                raise ValueError(f"job {job.name} runs `{command}`, which is not a subcommand of cli.py")
    flow, flow_nodes, flow_edges = system_flow(src, jobs)
    overview, area_nodes, area_edges = area_overview(mods)
    import_edges = sum(len(m.imports) for m in mods.values())
    start_edges = sum(len(m.starts) for m in mods.values())
    launch, direct, closure = launcher_diagram(src, mods)

    out = ["# System map", "",
           "Generated by `seed/bootstrap/local/system_map.py` — do not edit by hand; regenerate with "
           "`python3 local/system_map.py` from `seed/bootstrap`. `tests/test_wiring.py` (`SystemMapTest`) fails when "
           "this page no longer matches the code (owner rule E301, `docs/eksik-kaydi.md`).", "",
           "Read from the code: the jobs, `needs:` and commands of `seed/bootstrap/workflow/bootstrap.yml`; the "
           "imports of every module of `seed/bootstrap/snowball_bootstrap/` (with `ast`); the subcommands of "
           "`cli.py`; the imports of `seed/founder/launch.py`. Written by hand, in one block at the top of the script: "
           "the four actors outside the code, the links that meet them (each must still be found in the file it "
           "names, or the map is not drawn) and the area each module belongs to.", "",
           "## Legend", "",
           "| Mark | Meaning |", "|---|---|",
           "| Rectangle | Code in this repository: a file, a workflow job or a module |",
           "| Rounded, cylinder, hexagon | Outside the code: the operator; a repository or log; the rival model |",
           "| Solid arrow | Diagram 1: the job runs after the other (`needs:`). Diagrams 2-3: imports |",
           "| Dotted arrow, labelled | Something crosses a boundary: a push, a dispatch, an artifact, a call, "
           "a process |",
           "| Dashed border | A module of another area, drawn where this area imports it |", "",
           "## 1. System flow", "",
           f"{flow_nodes} nodes, {flow_edges} edges. A job box lists the `snowball_bootstrap` commands it runs, in "
           "order. Job arrows leave out dependencies another path already implies; the table lists every `needs:`. "
           "A seed epoch is the operator's delivery of `spec/tohum/` and `seed/` to the brain, with the "
           "`seed_epochs` row the referee checks on its next pull (`seed/founder/README.md`).", ""]
    out += _fence(flow)
    out += ["| Job | needs | Runs | Permissions | Secrets |", "|---|---|---|---|---|"]
    out += [f"| `{j.name}` | {_ticks(j.needs)} | {_ticks(j.commands)} | {_cell(j.permissions) or '-'} | "
            f"{_ticks(j.secrets)} |" for j in jobs.values()]
    out += ["", "## 2. Referee package: `seed/bootstrap/snowball_bootstrap`", "",
            f"{len(mods)} modules, {import_edges} imports inside the package, {start_edges} started as a separate "
            f"process. Areas are roles. The overview has {area_nodes} areas and {area_edges} edges; an arrow's "
            "number is how many imports cross from one area to the other.", ""]
    out += _fence(overview)
    imported_by: dict[str, list[str]] = {n: [] for n in mods}
    for m in mods.values():
        for t in m.imports:
            imported_by[t].append(m.name)
    for area in [a for a, _ in AREAS] + [UNPLACED]:
        own = [n for n in mods if area_of(n) == area]
        if not own:
            continue
        diagram, edges = area_diagram(area, mods)
        out += [f"### {area}", "", f"{len(own)} modules, {edges} edges out of them.", ""]
        out += _fence(diagram) if edges else []
        out += ["| Module | What it is (first sentence of its docstring) | Imported by |", "|---|---|---|"]
        out += [f"| `{n}` | {_cell(mods[n].doc) or '-'} | {_ticks(imported_by[n])} |" for n in own]
        out.append("")
    out += ["### Commands", "",
            "Every subcommand of `cli.py`, the jobs that run it, and the package modules its handler reaches through "
            "`cli.py`'s own helpers. A command no job runs is run by the operator or a local tool.", "",
            "| Command | Run by | Handler | Modules it reaches |", "|---|---|---|---|"]
    for command, handler in commands.items():
        by = [j.name for j in jobs.values() if command in j.commands]
        out.append(f"| `{command}` | {_ticks(by) if by else 'operator / local'} | `{handler}` | "
                   f"{_ticks(reached(mods['cli'], handler))} |")
    out += ["", "## 3. Launcher links", "",
            f"`seed/founder/launch.py` runs on the operator's machine and imports {len(direct)} referee modules, so "
            "the launcher applies the referee's own rules instead of a copy (E244). Through them it loads "
            f"{len(closure)}: {_ticks(closure)}.", ""]
    out += _fence(launch)
    return "\n".join(out).rstrip("\n") + "\n"


def main(argv: list[str]) -> int:
    page = render()
    path = ROOT / OUT
    if "--check" in argv:
        current = path.read_bytes() if path.exists() else b""
        if current != page.encode("utf-8"):
            print(f"{OUT} is stale: run `python3 local/system_map.py` from seed/bootstrap", file=sys.stderr)
            return 1
        return 0
    path.write_bytes(page.encode("utf-8"))
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
