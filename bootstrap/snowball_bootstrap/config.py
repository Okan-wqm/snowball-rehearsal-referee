"""Operator-written inputs, validated strictly. Anything missing or malformed stops the run.

Files, all in the referee repository and written only by the operator (`tohum/25`):
- ``bootstrap.json``: what this bootstrap watches and how it runs.
- ``control.json``: the kill switch.
- ``policy.json``: the constitutional policy (only the keys this bootstrap reads are checked).
- ``setup/summary.json``: the setup summary (seed commit and seed tree hash) and the seed epochs delivered since.
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


def check_control(root: Path) -> None:
    """Fail closed unless the kill switch is explicitly off and the budget state is ok."""
    data = _load(root / "control.json")
    if data.get("kill_switch") is not False:
        raise ConfigError("control.json: kill switch is on or not explicitly false")
    if data.get("budget_state") != "ok":
        raise ConfigError("control.json: budget_state is not 'ok'")


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
class Summary:
    seed_commit: str
    seed_tree_sha256: str
    epochs: tuple[SeedEpoch, ...] = ()

    @property
    def epoch(self) -> SeedEpoch | None:
        """The last seed epoch, the one the brain's seed must equal; None while only the setup seed exists."""
        return self.epochs[-1] if self.epochs else None


EPOCH_KEYS = frozenset({"commit", "spec_tohum_sha256", "seed_sha256", "bootstrap_sha256"})


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
    return Summary(seed_commit=seed_commit, seed_tree_sha256=seed_tree, epochs=epochs)
