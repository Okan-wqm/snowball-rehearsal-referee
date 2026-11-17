"""``profile.docker``: what a Dockerfile copies from its build context and which build context a compose file gives
a Dockerfile, read statically (nothing is built or run), used by ``status.depmap`` (the target's drawing): an image
depends on the projects it copies.

**Dockerfiles.** A file is a Dockerfile when its name matches one of ``DOCKERFILE_NAMES`` (``fnmatchcase``).
``instructions(text)`` gives ``[(line, KEYWORD, arguments)]``, ``line`` the 1-based line the instruction starts on,
``KEYWORD`` upper-cased, ``arguments`` the rest with its continuations joined; by BuildKit's rules, exactly these:

- parser directives: the leading lines of the form ``# name=value`` (blanks around allowed) before any other line;
  ``escape`` (``\\`` or a backtick) is the continuation character, ``\\`` by default; the first other line ends
  them (a blank line too);
- a line whose first non-blank character is ``#`` is a comment, also inside a continuation; a blank line inside a
  continuation is skipped;
- a line ending (trailing blanks aside) in the escape character continues on the next line, the character
  removed; continuation lines are joined as written;
- a heredoc: in a ``RUN``, ``COPY`` or ``ADD``, each blank-separated word of the arguments that is wholly
  ``<<WORD``, ``<<-WORD``, ``<<"WORD"`` or ``<<'WORD'`` (``WORD`` a letter or ``_`` and then letters, digits and
  ``_``; a file descriptor's digits may come first, ``2<<EOF``), in order, takes the following lines up to a line
  equal to ``WORD`` (for ``<<-`` after leading tabs are removed) as its body, not as instructions; a heredoc never
  closed takes the rest of the file. So ``$((1<<2))`` or ``a<<EOF`` is no heredoc.

``copies(text)`` gives ``(sources, malformed)``. ``sources`` is ``[(line, KEYWORD, source, kind)]`` for each source
of each ``COPY`` and ``ADD``: leading ``--flag`` and ``--flag=value`` options removed, then the JSON array form
(arguments starting with ``[`` that ``cli.loads`` reads as a list of strings) or else, as Docker falls back,
the arguments split on blanks; the last one is
the destination, the rest are sources. ``kind`` is, in this order: ``stage`` (the instruction has ``--from``: it
copies from a stage or an image), ``heredoc`` (a source starting with ``<<``: an inline file), ``remote`` (a source
holding ``://`` or starting with ``git@``), ``variable`` (a source holding ``$``: Docker substitutes ``ARG`` and
``ENV`` values, not resolved here) and ``context`` (a path in the build context; a leading ``/`` is the context's
root, as Docker reads it). ``malformed`` counts ``COPY``/``ADD`` instructions with fewer than two arguments.

**Compose files.** A file is a compose file when its name matches one of ``COMPOSE_NAMES``.
``compose_builds(doc)`` takes the file read by ``profile.yamlblock.load`` (so anchors, merge keys and flow
mappings are followed) and gives ``[(service, context, dockerfile)]`` for each service of its ``services`` mapping
whose ``build`` is not ``null``, in file order: a mapping gives its ``context`` and ``dockerfile`` (``None`` when
missing: Compose's defaults, ``.`` and ``Dockerfile``), any other value is the context with ``dockerfile``
``None``; the values are as read (a value that is not a string is the caller's to refuse).

Not read, stated: a ``build`` key outside ``services`` (an ``x-`` extension's is read only where a service
merges it), ``dockerfile_inline``, ``additional_contexts``, ``include`` and ``extends`` (another file's
services), a ``.dockerignore`` (a source may copy less than its path holds), ``ARG``/``ENV`` substitution, and
build contexts named elsewhere (``profile.ghactions`` reads ``docker/build-push-action`` steps; a ``docker build``
line, a Makefile, a script are not read).
"""

from __future__ import annotations

import fnmatch
import re
from typing import Any

import cli

DOCKERFILE_NAMES = ("Dockerfile", "Dockerfile.*", "*.Dockerfile", "*.dockerfile", "Containerfile")
COMPOSE_NAMES = ("compose.yaml", "compose.yml", "compose.*.yaml", "compose.*.yml",
                 "docker-compose.yaml", "docker-compose.yml", "docker-compose.*.yaml", "docker-compose.*.yml")
COPY_KINDS = ("context", "stage", "heredoc", "remote", "variable")

_DIRECTIVE = re.compile(r"#\s*([A-Za-z_]+)\s*=\s*(.*?)\s*")
_HEREDOC = re.compile(r"\d*<<(-?)([\"']?)([A-Za-z_][A-Za-z0-9_]*)\2")
HEREDOC_KEYWORDS = ("RUN", "COPY", "ADD")
_FLAG = re.compile(r"--[A-Za-z-]+(?:=\S*)?")


def is_dockerfile(name: str) -> bool:
    return any(fnmatch.fnmatchcase(name, p) for p in DOCKERFILE_NAMES)


def is_compose(name: str) -> bool:
    return any(fnmatch.fnmatchcase(name, p) for p in COMPOSE_NAMES)


def instructions(text: str) -> list[tuple[int, str, str]]:
    lines = text.split("\n")
    escape = "\\"
    i = 0
    while i < len(lines):
        m = _DIRECTIVE.fullmatch(lines[i].strip())
        if m is None:
            break
        if m.group(1).lower() == "escape" and m.group(2) in ("\\", "`"):
            escape = m.group(2)
        i += 1
    out: list[tuple[int, str, str]] = []
    while i < len(lines):
        stripped = lines[i].strip()
        if not stripped or stripped.startswith("#"):
            i += 1
            continue
        start = i + 1
        parts: list[str] = []
        line = lines[i].rstrip()
        while line.endswith(escape):
            parts.append(line[:-1])
            i += 1
            while i < len(lines) and (not lines[i].strip() or lines[i].strip().startswith("#")):
                i += 1
            if i >= len(lines):
                line = ""
                break
            line = lines[i].rstrip()
        parts.append(line)
        i += 1
        joined = "".join(parts).strip()
        keyword, _sep, arguments = joined.partition(" ")
        arguments = arguments.strip()
        out.append((start, keyword.upper(), arguments))
        words = arguments.split() if keyword.upper() in HEREDOC_KEYWORDS else []
        for strip_tabs, _q, word in (m.groups() for w in words if (m := _HEREDOC.fullmatch(w)) is not None):
            while i < len(lines):
                body = lines[i].lstrip("\t") if strip_tabs else lines[i]
                i += 1
                if body == word:
                    break
    return out


def _kind(source: str, staged: bool) -> str:
    if staged:
        return "stage"
    if source.startswith("<<"):
        return "heredoc"
    if "://" in source or source.startswith("git@"):
        return "remote"
    if "$" in source:
        return "variable"
    return "context"


def copies(text: str) -> tuple[list[tuple[int, str, str, str]], int]:
    sources: list[tuple[int, str, str, str]] = []
    malformed = 0
    for line, keyword, arguments in instructions(text):
        if keyword not in ("COPY", "ADD"):
            continue
        rest = arguments
        staged = False
        args = None
        while (m := _FLAG.match(rest)) is not None and (m.end() == len(rest) or rest[m.end()].isspace()):
            staged = staged or m.group(0).startswith("--from=")
            rest = rest[m.end():].lstrip()
        if rest.startswith("["):
            try:
                args = cli.loads(rest)
            except ValueError:
                args = None
        if not (isinstance(args, list) and all(isinstance(a, str) for a in args)):
            args = rest.split()
        if len(args) < 2:
            malformed += 1
            continue
        sources.extend((line, keyword, s, _kind(s, staged)) for s in args[:-1])
    return sources, malformed


def compose_builds(doc: Any) -> list[tuple[str, Any, Any]]:
    builds: list[tuple[str, Any, Any]] = []
    services = doc.get("services") if isinstance(doc, dict) else None
    for name, service in (services.items() if isinstance(services, dict) else ()):
        build = service.get("build") if isinstance(service, dict) else None
        if isinstance(build, dict):
            builds.append((name, build.get("context"), build.get("dockerfile")))
        elif build is not None:
            builds.append((name, build, None))
    return builds
