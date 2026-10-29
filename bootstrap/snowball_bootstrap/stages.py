"""The stage tables (`asama-0/14`, `tohum/26c` "Aşama tablosu"): the machine copy of a stage's micro-features.

`stages/stage0.json` is `{stage, mfs: [{mf, tests[], groups[], module, calls[]}]}`. The referee reads from it what
`done_mf` means, the tests a finished micro-feature must declare (`asama-0/09`), when a vector group runs (`29d`),
the module path module-less red deletes and the micro-feature count of the exit (`asama-0/10`). A called
micro-feature comes before its callers (`asama-0/14` "Sıra"). A table that breaks that, or any rule here, is not
loaded: the run stops (a seed defect is the operator's to fix, never the Founder's rejection).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

from .config import ConfigError
from .treehash import path_problem

STAGES_DIR = Path(__file__).resolve().parents[1] / "stages"
MODULE_ROOT = "referee"  # module paths are under the brain's `referee/` (`asama-0/14` "Modül")
FIELDS = {"mf", "tests", "groups", "module", "calls"}
GROUP_RE = re.compile(r"^[a-z][a-z0-9_]{0,40}\Z")
MAX_TEST = 999  # the manifest's test ids are T1..T999 (`manifest.TEST_ID_RE`)
MAX_MFS = 100


@dataclass(frozen=True)
class MicroFeature:
    mf: int
    tests: tuple[int, ...]
    groups: tuple[str, ...]
    module: str  # relative to `referee/`
    calls: tuple[int, ...]  # the micro-features it calls, each numbered below it

    @property
    def module_path(self) -> str:
        return f"{MODULE_ROOT}/{self.module}"


@dataclass(frozen=True)
class StageTable:
    stage: int
    mfs: tuple[MicroFeature, ...]

    @property
    def count(self) -> int:
        return len(self.mfs)

    def feature(self, mf: int) -> MicroFeature:
        if not 1 <= mf <= self.count:
            raise KeyError(f"MF{mf} is not in the stage {self.stage} table")
        return self.mfs[mf - 1]

    def groups_of(self, done: Iterable[int]) -> tuple[str, ...]:
        """The vector groups the finished micro-features own, each once, in table order (`29a`: a group runs once
        a micro-feature that owns it is done; a group no micro-feature of the table names does not run)."""
        finished = set(done)
        found: list[str] = []
        for feature in self.mfs:
            if feature.mf in finished:
                found += [g for g in feature.groups if g not in found]
        return tuple(found)


def _number(value: Any, high: int) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= high


def _module(value: Any, where: str) -> str:
    if not isinstance(value, str) or not value or path_problem(value) or value.startswith("/"):
        raise ConfigError(f"{where}: module must be a safe relative path under {MODULE_ROOT}/")
    if PurePosixPath(value).as_posix() != value or value.endswith("/"):
        raise ConfigError(f"{where}: module path {value!r} is not in normal form")
    return value


def parse_table(text: str, stage: int) -> StageTable:
    """Validate a stage table; a ConfigError names the first rule it breaks."""
    name = f"stage{stage}.json"
    try:
        data = json.loads(text)
    except (ValueError, RecursionError) as exc:
        raise ConfigError(f"{name} is not valid JSON: {exc}") from exc
    if not isinstance(data, dict) or set(data) != {"stage", "mfs"}:
        raise ConfigError(f"{name} must have exactly: stage, mfs")
    if data["stage"] != stage or isinstance(data["stage"], bool):
        raise ConfigError(f"{name} says stage {data['stage']!r}")
    raw = data["mfs"]
    if not isinstance(raw, list) or not 1 <= len(raw) <= MAX_MFS:
        raise ConfigError(f"{name}: mfs must be a list of 1 to {MAX_MFS} micro-features")
    owner: dict[int, int] = {}
    modules: set[str] = set()
    features = []
    for number, item in enumerate(raw, start=1):
        where = f"{name} MF{number}"
        if not isinstance(item, dict) or set(item) != FIELDS:
            raise ConfigError(f"{where} must have exactly: {', '.join(sorted(FIELDS))}")
        if item["mf"] != number or isinstance(item["mf"], bool):
            raise ConfigError(f"{where}: micro-features are numbered 1..N in order, found {item['mf']!r}")
        tests, groups, calls = item["tests"], item["groups"], item["calls"]
        if not isinstance(tests, list) or not tests or not all(_number(t, MAX_TEST) for t in tests):
            raise ConfigError(f"{where}: tests must be a non-empty list of test numbers (asama-0/09)")
        for t in tests:
            if t in owner:  # a test belongs to one micro-feature (§0.9 "Ne zaman")
                raise ConfigError(f"{where}: test {t} is already MF{owner[t]}'s")
            owner[t] = number
        if not isinstance(groups, list) or not all(isinstance(g, str) and GROUP_RE.match(g) for g in groups) \
                or len(set(groups)) != len(groups):
            raise ConfigError(f"{where}: groups must be distinct vector group names")
        module = _module(item["module"], where)
        if module in modules:
            raise ConfigError(f"{where}: module {module} is another micro-feature's")
        modules.add(module)
        if not isinstance(calls, list) or not all(_number(c, MAX_MFS) for c in calls) or calls != sorted(set(calls)):
            raise ConfigError(f"{where}: calls must be increasing micro-feature numbers")
        late = [c for c in calls if c >= number]
        if late:  # `asama-0/14` "Sıra": a called micro-feature comes before its caller
            raise ConfigError(f"{where} calls MF{late[0]}: a called micro-feature must come before its caller")
        features.append(MicroFeature(number, tuple(tests), tuple(groups), module, tuple(calls)))
    return StageTable(stage, tuple(features))


def load(stage: int = 0, directory: Path | None = None) -> StageTable:
    """The seed's table of ``stage``, read and validated on every call (it is small; nothing stale is kept)."""
    path = (directory or STAGES_DIR) / f"stage{stage}.json"
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise ConfigError(f"stage table {path.name} cannot be read: {type(exc).__name__}") from exc
    return parse_table(text, stage)
