"""``profile.kustomize``: the paths a Kustomize kustomization file names, read statically from its parsed document
(``profile.yamlblock``); no ``kustomize`` binary is run.

``is_kustomization(name)``: a file name Kustomize takes as a kustomization root's file, ``KUSTOMIZATION_NAMES``.

``references(doc)`` gives ``(field, value, kind)`` for each value a path field of the document holds, in the order
of ``FIELDS`` and then of the list:

- path fields, each a list: ``resources``, ``bases`` (deprecated, read as ``resources``), ``components``, ``crds``,
  ``patchesStrategicMerge``, ``transformers``, ``generators``, ``validators``, ``configurations``; the ``path`` of
  each entry of ``patches`` and ``patchesJson6902``; ``openapi.path``; and for each entry of
  ``configMapGenerator`` and ``secretGenerator`` each of its ``files`` (``key=path`` gives ``path``) and ``envs``
  and its ``env``;
- ``kind`` is ``path`` (a string naming a file or a directory relative to the kustomization's directory),
  ``remote`` (a string holding ``://`` or starting ``git@``: Kustomize fetches it) or
  ``inline`` (a string holding a line break or ``: ``, YAML text, or a mapping or list: a patch or a plugin
  configuration written in place; Kustomize itself tries a ``patchesStrategicMerge`` entry as a file first, so a
  file path holding ``: `` is taken as inline here); any other value (a number, ``None``) is ``not_a_path``;
- a ``path`` may still be a repository written as a host's path without a scheme: ``host_like``;
- a field that is not a list (an entry of ``patches`` that is not a mapping) gives nothing for that field or
  entry.

Not read, stated: ``helmCharts`` and ``helmChartInflationGenerator`` (a chart is not a path of the checkout),
``replacements``' ``path``, ``sortOptions``, every field that names an object rather than a file (``images``,
``replicas``, ``namespace``, labels); whether a ``path`` exists or what kind of file it is is the caller's.
"""

from __future__ import annotations

from typing import Any

KUSTOMIZATION_NAMES = ("kustomization.yaml", "kustomization.yml", "Kustomization")
LISTS = ("resources", "bases", "components", "crds", "patchesStrategicMerge", "transformers", "generators",
         "validators", "configurations")
ENTRY_PATHS = ("patches", "patchesJson6902")
GENERATORS = ("configMapGenerator", "secretGenerator")
FIELDS = LISTS + ENTRY_PATHS + ("openapi",) + GENERATORS
KINDS = ("path", "remote", "inline", "not_a_path")


def is_kustomization(name: str) -> bool:
    return name in KUSTOMIZATION_NAMES


def kind(value: Any) -> str:
    if isinstance(value, (dict, list)):
        return "inline"
    if not isinstance(value, str):
        return "not_a_path"
    if "\n" in value or ": " in value:
        return "inline"
    if "://" in value or value.startswith("git@"):
        return "remote"
    return "path"


def host_like(value: str) -> bool:
    """Whether a ``path`` value starts with a host name (its first segment holds a dot and is not ``.``/``..``-led,
    ``example.com/org/repo``): Kustomize reads a path from the checkout first and fetches it as a repository only
    when nothing is there, so this is the caller's question for a path the checkout does not hold."""
    first = value.split("/", 1)[0]
    return "/" in value and "." in first and not first.startswith(".")


def references(doc: Any) -> list[tuple[str, Any, str]]:
    if not isinstance(doc, dict):
        return []
    out: list[tuple[str, Any, str]] = []

    def add(field: str, value: Any) -> None:
        out.append((field, value, kind(value)))

    for field in LISTS:
        if isinstance(doc.get(field), list):
            for value in doc[field]:
                add(field, value)
    for field in ENTRY_PATHS:
        if isinstance(doc.get(field), list):
            for entry in doc[field]:
                if isinstance(entry, dict) and "path" in entry:
                    add(field, entry["path"])
    if isinstance(doc.get("openapi"), dict) and "path" in doc["openapi"]:
        add("openapi", doc["openapi"]["path"])
    for field in GENERATORS:
        if not isinstance(doc.get(field), list):
            continue
        for entry in doc[field]:
            if not isinstance(entry, dict):
                continue
            for key in ("files", "envs"):
                if isinstance(entry.get(key), list):
                    for value in entry[key]:
                        if key == "files" and isinstance(value, str) and "=" in value and kind(value) == "path":
                            value = value.split("=", 1)[1]
                        add(field, value)
            if "env" in entry:
                add(field, entry["env"])
    return out
