"""The stage tables (`asama-0/14`, `tohum/26c` "Aşama tablosu"): the machine copy of a stage's micro-features.

`stages/stage0.json` is `{stage, mfs: [{mf, tests[], groups[], module, calls[]}]}`. The referee reads from it what
`done_mf` means, the tests a finished micro-feature must declare (`asama-0/09`), when a vector group runs (`29d`),
the module path module-less red deletes and the micro-feature count of the exit (`asama-0/10`). A called
micro-feature comes before its callers (`asama-0/14` "Sıra"). A table that breaks that, or any rule here, is not
loaded: the run stops (a seed defect is the operator's to fix, never the Founder's rejection).

Past Stage 0 the seed carries batch tables, not stage tables (`26c`: "Partilerin tabloları aynı dizindedir";
`asama-1/13` 1: "Partinin tablosu tohumdadır ... setup/stage.json açtıktan sonra geçerlidir"): Stage 1's own
micro-features (`asama-1/06`, `lint.discover` first) are the Founder's, and its batches are numbered apart from them
(`06`: "Partiler numarasızdır"). `stages/stage1-P1.json` is `{stage: 1, batch: "P1", mfs}`, `asama-1/13`'s P1 rows.
Once the operator's lock opened Stage 1 (`setup/stage.json`, `asama-0/10a`), the table that holds is the open batch's:
the first of `BATCHES[1]` the counter has no transfer of (`stagelock.batches_done`). Each batch has its own numbering,
so P2's table (`stages/stage1-P2.json`) joined without renumbering P1's (E491). With every batch the seed carries
transferred, the open table is empty: no micro-feature of the seed is open, `done_mf` is `[]` (Stage 1's own
micro-features are judged live by the transferred referee, `06`). The exit batch of `asama-1/13` is no table here: it
comes with Stage 1's own exit, whose (A) this seed does not judge (E378, E495). Stage 1 is the ladder's fixed root
(`03`), so none of this is a default to deviate from. `tohum/26e` is the tables' page: every row, the batch names, the
module paths and P2 MF1's test number (53, `30d` "Profil testi": `asama-1/13`'s "`30d`'nin profil testleri").

The open table carries what is finished as ``before``: Stage 0 and every transferred batch. All their micro-features
are done, so their vector groups run on every push (`asama-0/14`: a finished micro-feature's group runs on every later
push) and their tests stay declared. Spec sessiz (E372, E378): the batch table's name and its ``batch`` field; the
module paths, from `26a`'s tool names as `asama-0/14`'s are (``snapshot.make`` is ``snapshot/make.py``) and, for the
three mechanisms `26a` names no tool for, from the mechanism; a micro-feature of two tools takes the first one's path
(`asama-0/14` MF1 ``ledger.chain``, MF13 ``gate.revert``): P2 MF1 is ``security/derive.py``; ``calls`` empty, as the
page names none.

The pages a table copies are the stage pages the seed rival reads beside a code push (`STAGE_PAGES`, `26e`, E493): the
rows and their tests, so the rival measures the push against the micro-features the referee judges it by. Stage 0's
table copies `asama-0/14` and `09`; past the lock the batch tables copy `asama-1/13` and `asama-0/09`, and Stage 1's own
micro-features, judged by the same pushes, are `asama-1/06`'s.
"""

from __future__ import annotations

import json
import re
import sys
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
# The batches whose tables this seed carries, per stage, in `asama-1/13`'s order (P1 before P2 before the exit batch).
BATCHES: dict[int, tuple[str, ...]] = {1: ("P1", "P2")}
# The stage pages the rival reads beside a code push, per open stage (`26e`, E493): the pages its table copies.
STAGE_PAGES: dict[int, tuple[str, ...]] = {0: ("asama-0/09-", "asama-0/14-"),
                                           1: ("asama-0/09-", "asama-1/06-", "asama-1/13-")}
# A module's first name (its package, or its file without `.py`) is never a standard library module's: the
# referee runs a command with `referee/` first on `sys.path`, so `profile/` hides the stdlib `profile` and
# `import cProfile` fails (E191, report spec-011, E507). Stage 0's frozen table names `profile` from before the
# rule; it stays until that table is reopened (`26e`).
STDLIB_KEPT: dict[int, frozenset[str]] = {0: frozenset({"profile"})}
BATCH_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,39}\Z")  # a batch's name as a request and a counter row carry it


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
    before: tuple["StageTable", ...] = ()  # what is finished: Stage 0's table first, then the transferred batches'
    batch: str | None = None  # a batch table's batch; None for Stage 0's table and for an open stage with none open

    @property
    def count(self) -> int:
        return len(self.mfs)

    @property
    def label(self) -> str:
        """The table's name in a reason: ``stage0``, ``stage1-P1``."""
        return f"stage{self.stage}" + (f"-{self.batch}" if self.batch else "")

    def feature(self, mf: int) -> MicroFeature:
        if not 1 <= mf <= self.count:
            raise KeyError(f"MF{mf} is not in the {self.label} table")
        return self.mfs[mf - 1]

    def groups_of(self, done: Iterable[int]) -> tuple[str, ...]:
        """The vector groups the finished micro-features own, each once, in table order (`29a`: a group runs once
        a micro-feature that owns it is done; a group no micro-feature of the table names does not run)."""
        finished = set(done)
        found: list[str] = []
        for table in self.before:  # every micro-feature of a finished table is done
            found += [g for g in table.groups_of(range(1, table.count + 1)) if g not in found]
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


def hidden_stdlib(module: str) -> str | None:
    """The standard library module a module path's first name hides, if any."""
    first = PurePosixPath(module).parts[0]
    name = first[:-3] if first.endswith(".py") else first
    return name if name in sys.stdlib_module_names else None


def table_name(stage: int, batch: str | None = None) -> str:
    return f"stage{stage}" + (f"-{batch}" if batch else "") + ".json"


def parse_table(text: str, stage: int, batch: str | None = None) -> StageTable:
    """Validate a stage table (``batch`` None) or a batch table; a ConfigError names the first rule it breaks."""
    name = table_name(stage, batch)
    try:
        data = json.loads(text)
    except (ValueError, RecursionError) as exc:
        raise ConfigError(f"{name} is not valid JSON: {exc}") from exc
    keys = ("stage", "batch", "mfs") if batch else ("stage", "mfs")
    if not isinstance(data, dict) or set(data) != set(keys):
        raise ConfigError(f"{name} must have exactly: {', '.join(keys)}")
    if data["stage"] != stage or isinstance(data["stage"], bool):
        raise ConfigError(f"{name} says stage {data['stage']!r}")
    if batch and data["batch"] != batch:
        raise ConfigError(f"{name} says batch {data['batch']!r}")
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
        hidden = hidden_stdlib(module)
        if hidden and hidden not in STDLIB_KEPT.get(stage, frozenset()):
            raise ConfigError(f"{where}: module {module} hides the standard library's {hidden} (`26e`, E507)")
        if module in modules:
            raise ConfigError(f"{where}: module {module} is another micro-feature's")
        modules.add(module)
        if not isinstance(calls, list) or not all(_number(c, MAX_MFS) for c in calls) or calls != sorted(set(calls)):
            raise ConfigError(f"{where}: calls must be increasing micro-feature numbers")
        late = [c for c in calls if c >= number]
        if late:  # `asama-0/14` "Sıra": a called micro-feature comes before its caller
            raise ConfigError(f"{where} calls MF{late[0]}: a called micro-feature must come before its caller")
        features.append(MicroFeature(number, tuple(tests), tuple(groups), module, tuple(calls)))
    return StageTable(stage, tuple(features), batch=batch)


def _read(stage: int, directory: Path | None, batch: str | None = None) -> StageTable:
    path = (directory or STAGES_DIR) / table_name(stage, batch)
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise ConfigError(f"stage table {path.name} cannot be read: {type(exc).__name__}") from exc
    return parse_table(text, stage, batch)


def load(stage: int = 0, directory: Path | None = None, done: Iterable[str] = ()) -> StageTable:
    """The table that holds in ``stage``, read and validated on every call (it is small; nothing stale is kept): Stage
    0's own, or past it the open batch's after the transferred batches ``done`` (the counter's, in order), with what is
    finished as ``before``. A stage the seed has no batch tables for is past the root (`03`): a ConfigError."""
    if stage == 0:
        if tuple(done):
            raise ConfigError("Stage 0 has no batches")
        return _read(0, directory)
    if stage not in BATCHES:
        raise ConfigError(f"the seed has no table for Stage {stage}: past the fixed root (`03`) the stage spec is the "
                          "Founder's")
    order, done = BATCHES[stage], tuple(done)
    if done != order[:len(done)]:
        raise ConfigError(f"Stage {stage}'s transferred batches {', '.join(done)} are not the seed's batches in order "
                          f"({', '.join(order)}, `asama-1/13`)")
    before = (_read(0, directory),) + tuple(_read(stage, directory, b) for b in done)
    if len(done) == len(order):
        return StageTable(stage, (), before)
    table = _read(stage, directory, order[len(done)])
    return StageTable(table.stage, table.mfs, before, table.batch)
