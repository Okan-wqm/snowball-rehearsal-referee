"""Operator-written inputs, validated strictly. Anything missing or malformed stops the run.

Files, all in the referee repository and written only by the operator (`tohum/25`):
- ``bootstrap.json``: what this bootstrap watches and how it runs.
- ``control.json``: the kill switch, the budget brake and the loop's schedule (`26c`), for this workflow and, through
  the `control` command, for every job of the loop (`29p`).
- ``policy.json``: the constitutional policy (only the keys this bootstrap reads are checked).
- ``setup/summary.json``: the setup summary (seed commit and seed tree hash), the seed epochs delivered since, the
  Stage 0 targets, the honesty commitment and the owner's exception to #durustluk beside it (`26c`, every key
  checked).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SHA_RE = re.compile(r"^[0-9a-f]{40}\Z")
HEX64_RE = re.compile(r"^[0-9a-f]{64}\Z")
REPO_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9._-]{1,100}\Z")
IMAGE_RE = re.compile(r"^[a-z0-9./_-]+(?::[A-Za-z0-9._-]+)?@sha256:[0-9a-f]{64}\Z")
BRANCH_RE = re.compile(r"^[A-Za-z0-9._/-]{1,200}\Z")


class ConfigError(ValueError):
    """An operator file is missing, malformed, or says stop."""


def _load(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigError(f"missing {path}") from exc
    except json.JSONDecodeError as exc:
        raise ConfigError(f"{path} is not valid JSON: {exc}") from exc


def _req(obj: Any, key: str, kind: type, where: str) -> Any:
    if not isinstance(obj, dict) or key not in obj:
        raise ConfigError(f"{where}: missing key {key!r}")
    value = obj[key]
    if kind is int and isinstance(value, bool):
        raise ConfigError(f"{where}.{key} must be an integer")
    if not isinstance(value, kind):
        raise ConfigError(f"{where}.{key} must be {kind.__name__}")
    return value


def _pos_int(obj: Any, key: str, where: str) -> int:
    value = _req(obj, key, int, where)
    if value <= 0:
        raise ConfigError(f"{where}.{key} must be positive")
    return value


@dataclass(frozen=True)
class RivalConfig:
    model: str
    effort: str
    max_turns: int
    per_run_cap_usd_micros: int


@dataclass(frozen=True)
class Limits:
    test_timeout_s: int
    reproducer_timeout_s: int
    max_prompt_chars: int
    max_tree_bytes: int


@dataclass(frozen=True)
class Bootstrap:
    brain_repo: str
    brain_branch: str
    image: str
    rival: RivalConfig
    limits: Limits


MODEL_RE = re.compile(r"^claude-[a-z0-9][a-z0-9.-]*\Z")
REMOVED_KEYS = {"max_tokens": "the rival runs through the claude CLI, which takes no per-request token limit flag",
                "price_micros_per_mtok": "cost is the CLI's own list-price estimate"}


def _only_known(obj: dict[str, Any], known: set[str], where: str) -> None:
    unknown = sorted(set(obj) - known)
    if unknown:
        hints = "; ".join(f"{k} was removed: {REMOVED_KEYS[k]}" for k in unknown if k in REMOVED_KEYS)
        raise ConfigError(f"{where}: unknown key(s) {', '.join(unknown)}" + (f" ({hints})" if hints else ""))


def load_bootstrap(root: Path) -> Bootstrap:
    data = _load(root / "bootstrap.json")
    where = "bootstrap.json"
    if isinstance(data, dict):
        _only_known(data, {"brain_repo", "brain_branch", "image", "rival", "limits"}, where)
    repo = _req(data, "brain_repo", str, where)
    if not REPO_RE.match(repo):
        raise ConfigError(f"{where}.brain_repo must be owner/name")
    branch = _req(data, "brain_branch", str, where)
    if not BRANCH_RE.match(branch) or ".." in branch:
        raise ConfigError(f"{where}.brain_branch is not a plain branch name")
    image = _req(data, "image", str, where)
    if not IMAGE_RE.match(image):
        raise ConfigError(f"{where}.image must be pinned by digest (name@sha256:<64 hex>)")
    rival = _req(data, "rival", dict, where)
    rw = f"{where}.rival"
    _only_known(rival, {"model", "effort", "max_turns", "per_run_cap_usd_micros"}, rw)
    model = _req(rival, "model", str, rw)
    if not MODEL_RE.match(model):
        raise ConfigError(f"{rw}.model must be a full model id such as claude-sonnet-5-5 (the served model is "
                          "compared with it)")
    effort = _req(rival, "effort", str, rw)
    if effort not in {"low", "medium", "high", "xhigh", "max"}:
        raise ConfigError(f"{rw}.effort is not a known effort level")
    limits = _req(data, "limits", dict, where)
    lw = f"{where}.limits"
    _only_known(limits, {"test_timeout_s", "reproducer_timeout_s", "max_prompt_chars", "max_tree_bytes"}, lw)
    return Bootstrap(
        brain_repo=repo,
        brain_branch=branch,
        image=image,
        rival=RivalConfig(
            model=model,
            effort=effort,
            max_turns=_pos_int(rival, "max_turns", rw),
            per_run_cap_usd_micros=_pos_int(rival, "per_run_cap_usd_micros", rw),
        ),
        limits=Limits(
            test_timeout_s=_pos_int(limits, "test_timeout_s", lw),
            reproducer_timeout_s=_pos_int(limits, "reproducer_timeout_s", lw),
            max_prompt_chars=_pos_int(limits, "max_prompt_chars", lw),
            max_tree_bytes=_pos_int(limits, "max_tree_bytes", lw),
        ),
    )


def control_state(path: Path) -> dict[str, Any]:
    """``control.json``, failing closed (`26c`): it stops unless the kill switch is explicitly off and the budget state
    is ok."""
    data = _load(path)
    if not isinstance(data, dict) or data.get("kill_switch") is not False:
        raise ConfigError("control.json: kill switch is on or not explicitly false")
    if data.get("budget_state") != "ok":
        raise ConfigError("control.json: budget_state is not 'ok'")
    return data


def check_control(root: Path) -> None:
    """Fail closed unless the kill switch is explicitly off and the budget state is ok."""
    control_state(root / "control.json")


LOOP_EVENTS = ("schedule", "workflow_dispatch")  # the loop's triggers (`asama-0/01` D0, `25a`)


def loop_goes(path: Path, event: str) -> bool:
    """D0 of a loop job (`asama-0/01`, `29p`): whether it goes on. Stops (ConfigError) on the kill switch or the budget
    brake, and on a trigger the loop never runs on; a scheduled run is paused (False) unless ``loop_schedule`` is
    exactly true (`26c`: missing is false); the operator's dispatch goes."""
    data = control_state(path)
    if event not in LOOP_EVENTS:
        raise ConfigError(f"the loop runs on {' or '.join(LOOP_EVENTS)}, not on {event!r}")
    return event == "workflow_dispatch" or data.get("loop_schedule") is True


WAIVER_RE = re.compile(r"^[0-9a-f]{16}\Z")


def load_waivers(root: Path) -> list[str]:
    """Proven defects the operator closed by hand: ``control.json`` ``waived_refutations``, a list of the
    16-character reproducer keys a rejection names as ``repro:<key>`` (`tohum/29`, E08). Optional."""
    data = _load(root / "control.json")
    waived = data.get("waived_refutations", []) if isinstance(data, dict) else []
    if not isinstance(waived, list) or not all(isinstance(w, str) and WAIVER_RE.match(w) for w in waived):
        raise ConfigError("control.json.waived_refutations must be a list of 16-character reproducer keys")
    return sorted(set(waived))


SPDX_ID_RE = re.compile(r"^[A-Za-z0-9.+-]{1,64}\Z")
PIN_RE = re.compile(r"^[a-z0-9][a-z0-9-]*==[A-Za-z0-9.+!-]+\Z")


@dataclass(frozen=True)
class Policy:
    monthly_cap_usd_micros: int
    stage0_rival_usd_micros: int
    rival_min_attempts: int
    repeat_reject_limit: int
    license_allowlist: frozenset[str]
    license_exceptions: dict[str, str]


def load_policy(root: Path) -> Policy:
    data = _load(root / "policy.json")
    const = _req(data, "constitutional", dict, "policy.json")
    cw = "policy.json.constitutional"
    params = _req(const, "stage_params", dict, cw)
    budgets = _req(const, "stage_budgets", dict, cw)
    stage0 = _req(budgets, "asama_0", dict, f"{cw}.stage_budgets")
    allow = _req(const, "license_allowlist", list, cw)
    if not allow or not all(isinstance(a, str) and SPDX_ID_RE.match(a) for a in allow):
        raise ConfigError(f"{cw}.license_allowlist must be a non-empty list of SPDX identifiers")
    exceptions = _req(const, "license_exceptions", dict, cw)
    for pin, entry in exceptions.items():
        if not PIN_RE.match(pin) or not isinstance(entry, dict) or set(entry) != {"expression", "evidence"} \
                or not all(isinstance(v, str) and v.strip() for v in entry.values()):
            raise ConfigError(f"{cw}.license_exceptions[{pin!r}] must be "
                              "{{expression, evidence}} keyed by normalised name==version")
    return Policy(
        monthly_cap_usd_micros=_pos_int(const, "monthly_cap_usd", cw) * 1_000_000,
        stage0_rival_usd_micros=_pos_int(stage0, "rival_usd", f"{cw}.stage_budgets.asama_0") * 1_000_000,
        rival_min_attempts=_pos_int(params, "rival_min_attempts", f"{cw}.stage_params"),
        repeat_reject_limit=_pos_int(params, "repeat_reject_limit", f"{cw}.stage_params"),
        license_allowlist=frozenset(allow),
        license_exceptions={pin: entry["expression"] for pin, entry in exceptions.items()},
    )


@dataclass(frozen=True)
class SeedEpoch:
    """A seed the operator delivered into the brain (`25` 10b, `26c` ``seed_epochs[]``): the brain commit that carries
    it and the tree hashes of its ``spec/tohum/`` and ``seed/`` there (``seed_sha256`` is None when the brain has no
    ``seed/``). ``bootstrap_sha256`` is the referee's ``bootstrap/`` copy of the same seed."""
    commit: str
    spec_tohum_sha256: str
    seed_sha256: str | None
    bootstrap_sha256: str


@dataclass(frozen=True)
class Target:
    """A Stage 0 target (`25` 10a, `26c` ``targets[]``). ``identifiers`` are the names the generality check looks for
    in `referee/` (`asama-0/10` #genellik); ``base_sha`` is None for a target with no commit yet (the toy is empty
    until the exit's import, `25` 10)."""
    id: str
    repo: str
    kind: str
    base_sha: str | None
    identifiers: tuple[str, ...]
    excluded_paths: tuple[str, ...]
    unit_candidates: tuple[str, ...]


@dataclass(frozen=True)
class HonestyException:
    """The owner's named exception to Stage 0's #durustluk (`02` "Sahip istisnası", `26c`; E287, E294): the plant the
    honesty rehearsal measures was not made before the Founder started (`25` 10c), so the condition can be neither
    measured nor passed there. One anchor, one stage, one carry target: Stage 0's exit names it, and Stage 1's (A) must
    measure #durustluk, with no second exception. The ``honesty_commitment`` beside it is the plant Stage 1 measures;
    without one the exception takes nothing off the exit (`decide`, E297): Stage 1 could not measure it either."""
    stage: int
    carry_to: int
    reason: str


@dataclass(frozen=True)
class Summary:
    seed_commit: str
    seed_tree_sha256: str
    epochs: tuple[SeedEpoch, ...] = ()
    targets: tuple[Target, ...] | None = None  # None: the summary has no targets[] yet (E99, E284)
    honesty_commitment: str | None = None  # sha256(canonical(key)) of the plant (`25` 10c)
    honesty_exception: HonestyException | None = None  # with a commitment beside it, the plant is the carried stage's

    @property
    def epoch(self) -> SeedEpoch | None:
        """The last seed epoch, the one the brain's seed must equal; None while only the setup seed exists."""
        return self.epochs[-1] if self.epochs else None


EPOCH_KEYS = frozenset({"commit", "spec_tohum_sha256", "seed_sha256", "bootstrap_sha256"})
TARGET_KEYS = frozenset({"id", "repo", "kind", "base_sha", "identifiers", "excluded_paths", "unit_candidates"})
TARGET_KINDS = ("toy", "copy")
HONESTY_EXCEPTION_KEYS = frozenset({"stage", "carry_to", "reason"})


def names_the_copy(targets: tuple[Target, ...] | None) -> bool:
    """Whether ``targets[]`` names a copy target and every copy target's identifiers (`25` 10a): the names #genellik
    looks for (`asama-0/10`, E284), so what Stage 0 needs before it starts (E293). The toy's content is the Founder's
    own fixture, so a toy target needs none."""
    copies = [t for t in targets or () if t.kind == "copy"]
    return bool(copies) and all(t.identifiers for t in copies)


def _texts(row: dict[str, Any], key: str, where: str) -> tuple[str, ...]:
    value = row[key]
    if not isinstance(value, list) or not all(isinstance(v, str) and v.strip() for v in value):
        raise ConfigError(f"{where}.{key} must be a list of non-empty strings")
    return tuple(value)


def target(row: Any, where: str) -> Target:
    """One ``targets[]`` row, read strictly: exactly `26c`'s keys, so a misspelt key stops the run instead of leaving a
    list unread (`26c`: a missing or unknown field fails closed)."""
    if not isinstance(row, dict) or set(row) != TARGET_KEYS:
        raise ConfigError(f"{where} must have exactly the keys {', '.join(sorted(TARGET_KEYS))} (`26c`)")
    if not isinstance(row["id"], str) or not row["id"].strip():
        raise ConfigError(f"{where}.id must be a non-empty string")
    if not isinstance(row["repo"], str) or not REPO_RE.match(row["repo"]):
        raise ConfigError(f"{where}.repo must be owner/name")
    if row["kind"] not in TARGET_KINDS:
        raise ConfigError(f"{where}.kind must be one of {', '.join(TARGET_KINDS)}")
    if row["base_sha"] is not None and not (isinstance(row["base_sha"], str) and SHA_RE.match(row["base_sha"])):
        raise ConfigError(f"{where}.base_sha must be a 40-character commit SHA, or null for a target with no commit")
    return Target(row["id"], row["repo"], row["kind"], row["base_sha"], _texts(row, "identifiers", where),
                  _texts(row, "excluded_paths", where), _texts(row, "unit_candidates", where))


def _epoch(row: Any, where: str) -> SeedEpoch:
    if not isinstance(row, dict) or set(row) != EPOCH_KEYS:
        raise ConfigError(f"{where} must have exactly the keys {', '.join(sorted(EPOCH_KEYS))} (`26c`)")
    if not isinstance(row["commit"], str) or not SHA_RE.match(row["commit"]):
        raise ConfigError(f"{where}.commit must be a 40-character commit SHA")
    for key in ("spec_tohum_sha256", "bootstrap_sha256"):
        if not isinstance(row[key], str) or not HEX64_RE.match(row[key]):
            raise ConfigError(f"{where}.{key} must be 64 hex characters")
    if row["seed_sha256"] is not None and not (isinstance(row["seed_sha256"], str) and HEX64_RE.match(row["seed_sha256"])):
        raise ConfigError(f"{where}.seed_sha256 must be 64 hex characters, or null when the brain has no seed/")
    return SeedEpoch(row["commit"], row["spec_tohum_sha256"], row["seed_sha256"], row["bootstrap_sha256"])


def load_summary(root: Path) -> Summary:
    data = _load(root / "setup" / "summary.json")
    where = "setup/summary.json"
    seed_commit = _req(data, "seed_commit", str, where)
    if not SHA_RE.match(seed_commit):
        raise ConfigError(f"{where}.seed_commit must be a 40-character commit SHA")
    seed_tree = _req(data, "seed_tree_sha256", str, where)
    if not HEX64_RE.match(seed_tree):
        raise ConfigError(f"{where}.seed_tree_sha256 must be 64 hex characters")
    epochs: tuple[SeedEpoch, ...] = ()
    if "seed_epochs" in data:  # absent: no seed was delivered after setup
        rows = data["seed_epochs"]
        if not isinstance(rows, list) or not rows:
            raise ConfigError(f"{where}.seed_epochs must be a non-empty list of seed epochs")
        epochs = tuple(_epoch(row, f"{where}.seed_epochs[{i}]") for i, row in enumerate(rows))
    targets: tuple[Target, ...] | None = None
    if "targets" in data:  # absent: the operator has not named the targets yet (`25` 10a)
        if not isinstance(data["targets"], list):
            raise ConfigError(f"{where}.targets must be a list of targets")
        targets = tuple(target(row, f"{where}.targets[{i}]") for i, row in enumerate(data["targets"]))
        if len({t.id for t in targets}) != len(targets):
            raise ConfigError(f"{where}.targets: two targets have the same id")
    commitment = None
    if "honesty_commitment" in data:  # `25` 10c: sha256(canonical(key)), the key itself never in open text
        commitment = data["honesty_commitment"]
        if not isinstance(commitment, str) or not HEX64_RE.match(commitment):
            raise ConfigError(f"{where}.honesty_commitment must be 64 lower-case hex characters")
    # Beside the exception, a commitment is the carried stage's plant, measured there (`02` "Sahip istisnası").
    exception = _honesty_exception(data["honesty_exception"], f"{where}.honesty_exception") \
        if "honesty_exception" in data else None
    return Summary(seed_commit=seed_commit, seed_tree_sha256=seed_tree, epochs=epochs, targets=targets,
                   honesty_commitment=commitment, honesty_exception=exception)


def _honesty_exception(row: Any, where: str) -> HonestyException:
    """The owner's exception, read strictly: exactly `26c`'s keys; the rehearsal is Stage 0's (`asama-0/10`), so the
    exception is Stage 0's and carries to Stage 1; the reason names why (the register row) in a non-empty text."""
    if not isinstance(row, dict) or set(row) != HONESTY_EXCEPTION_KEYS:
        raise ConfigError(f"{where} must have exactly the keys {', '.join(sorted(HONESTY_EXCEPTION_KEYS))} (`26c`)")
    if type(row["stage"]) is not int or row["stage"] != 0:
        raise ConfigError(f"{where}.stage must be 0: the honesty rehearsal is Stage 0's (`asama-0/10`)")
    if type(row["carry_to"]) is not int or row["carry_to"] != row["stage"] + 1:
        raise ConfigError(f"{where}.carry_to must be {row['stage'] + 1}: the next stage measures it (`02`)")
    if not isinstance(row["reason"], str) or not row["reason"].strip():
        raise ConfigError(f"{where}.reason must name why the plant was not made (a non-empty text)")
    return HonestyException(row["stage"], row["carry_to"], row["reason"])


def start_missing(summary: Summary) -> list[str]:
    """What the setup summary lacks for Stage 0 to start (`25` 10a, 10c and "Aşama 0 bu özet olmadan başlamaz"; E293):
    the referee builds no first state without it, so a setup item cannot be skipped unseen again. The honesty
    commitment is needed with or without the owner's exception (E297): beside the exception it is the plant of the
    stage the exception carries to, so no pilot starts, or restarts from a lost state, with the rehearsal unplanted."""
    missing = []
    if not names_the_copy(summary.targets):
        missing.append("targets[] naming the copy target's identifiers (`25` 10a)")
    if summary.honesty_commitment is None:
        missing.append("honesty_commitment (`25` 10c; beside the owner's honesty_exception, the carried stage's plant, "
                       "`02`)")
    return missing
