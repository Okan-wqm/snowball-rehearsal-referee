"""The bootstrap's memory between runs: the last signed result's ``state`` block.

There is no writable store in the referee repository (only the operator writes it), so state
travels in the signed ``bootstrap-state`` artifact of the previous run and is verified with
Sigstore before use. If none exists, the run starts from the setup summary and says so.

``reject_streaks`` counts, per rejection signature, how many evaluated rejections in a row carried
it; ``repeat_events`` counts the times a signature came back on the very next rejection. They
measure whether the founder uses what a rejection told it (`tohum/29b`, "Ret hafızası").
``rival_side_streak`` counts the rival's own failures in a row (E11), which warn the operator instead.
``outage_sha``, ``outage_count`` and ``outage_since`` count the consecutive infrastructure failures of one
commit, so that a dead token parks that commit instead of re-running the whole pipeline every hour
(`decide.OUTAGE_RETRY_LIMIT`) and is given up after a week; ``outage_stop`` names a failure that stops
for the operator at once (an isolation fault, E12).
``rival_artifacts`` lists every head the rival judged with its outcome (E20); ``pending_rival`` keeps a
valid rival result whose reproducers could not run, so the retry reuses it (one attempt per artifact).
``open_refutations`` are proven defects, re-run on every later code head until an accepted head no longer
shows them (E08); ``open_claims`` are refutations that were not reproduced (E07).

A state written by an older bootstrap is carried forward by ``migrate``, never thrown away (`tohum/25`).
"""

from __future__ import annotations

import re
from typing import Any

from .config import ConfigError, Summary

SCHEMA = "snowball-bootstrap-state/2"
SCHEMA_V1 = "snowball-bootstrap-state/1"
SHA_RE = re.compile(r"^[0-9a-f]{40}\Z")
HEX64_RE = re.compile(r"^[0-9a-f]{64}\Z")
KEY_RE = re.compile(r"^[0-9a-f]{16}\Z")
CLAIM_ID_RE = re.compile(r"^[0-9a-f]{12}\Z")
MONTH_RE = re.compile(r"^\d{4}-\d{2}\Z")
TIME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z\Z")
OUTCOMES = ("survived", "refuted", "unknown")
MAX_OPEN_REFUTATIONS = 20
MAX_OPEN_CLAIMS = 10
KEYS_V1 = {"schema", "origin", "last_accepted_sha", "last_evaluated_sha", "frozen_specs", "rival_artifacts",
           "month", "month_spend_usd_micros", "stage_spend_usd_micros", "runs", "reject_streaks", "repeat_events",
           "outage_sha", "outage_count"}
KEYS = KEYS_V1 | {"outage_since", "outage_stop", "rival_side_streak", "open_refutations", "open_claims",
                  "pending_rival"}
REFUTATION_KEYS = {"key", "claim", "evidence_refs", "reproducer", "first_head", "last_head"}
CLAIM_KEYS = {"id", "claim", "evidence_refs", "reproducer", "observed", "first_head", "rewritten"}


def initial(summary: Summary, month: str) -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "origin": "initial",
        "last_accepted_sha": summary.seed_commit,
        "last_evaluated_sha": None,
        "frozen_specs": {},
        "rival_artifacts": [],
        "month": month,
        "month_spend_usd_micros": 0,
        "stage_spend_usd_micros": 0,
        "runs": 0,
        "reject_streaks": {},
        "repeat_events": 0,
        "outage_sha": None,
        "outage_count": 0,
        "outage_since": None,
        "outage_stop": None,
        "rival_side_streak": 0,
        "open_refutations": [],
        "open_claims": [],
        "pending_rival": None,
    }


def migrate(state: Any, now: str) -> Any:
    """Carry a state of an earlier schema forward; anything else is returned as it is for ``validate`` to judge.

    v1 -> v2: books, streaks, frozen specs and the accepted SHA stay. A v1 artifact list cannot say which
    heads survived the rival, so only the last accepted head (accepted means it survived) counts as one; the
    others become ``unknown``, which the exit never counts. A running outage restarts its week now.
    """
    if not isinstance(state, dict) or state.get("schema") != SCHEMA_V1 or set(state) != KEYS_V1:
        return state
    new = dict(state, schema=SCHEMA)
    arts = state["rival_artifacts"] if isinstance(state["rival_artifacts"], list) else []
    new["rival_artifacts"] = [{"sha": sha, "outcome": "survived" if sha == state["last_accepted_sha"] else "unknown"}
                              for sha in arts]
    new.update(outage_since=now if state["outage_sha"] else None, outage_stop=None, rival_side_streak=0,
               open_refutations=[], open_claims=[], pending_rival=None)
    return new


def _text(value: Any, limit: int) -> bool:
    return isinstance(value, str) and len(value) <= limit


def _count(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _reproducer(rep: Any) -> bool:
    return (isinstance(rep, dict) and _text(rep.get("cmd"), 1000) and bool(rep["cmd"])
            and set(rep) <= {"cmd", "expect_exit", "expect_stdout_contains", "expect_stderr_contains"})


def _refs(refs: Any) -> bool:
    return isinstance(refs, list) and len(refs) <= 20 and all(isinstance(r, dict) for r in refs)


def _sha_or_none(value: Any) -> bool:
    return value is None or bool(SHA_RE.match(str(value)))


def validate(state: Any) -> dict[str, Any]:
    if not isinstance(state, dict) or state.get("schema") != SCHEMA:
        raise ConfigError("previous state has an unexpected shape (schema "
                          f"{state.get('schema') if isinstance(state, dict) else type(state).__name__!r}); "
                          "see tohum/25 'Durum kaybolursa'")
    if set(state) != KEYS:
        missing, extra = sorted(KEYS - set(state)), sorted(set(state) - KEYS)
        raise ConfigError("previous state has an unexpected shape (missing: " + (", ".join(missing) or "none")
                          + "; unexpected: " + (", ".join(extra) or "none") + "): another version of the bootstrap "
                          "wrote it and no migration knows it; see tohum/25 'Durum kaybolursa'")
    if not SHA_RE.match(str(state["last_accepted_sha"])):
        raise ConfigError("previous state: bad last_accepted_sha")
    for key in ("last_evaluated_sha", "outage_sha"):
        if not _sha_or_none(state[key]):
            raise ConfigError(f"previous state: bad {key}")
    if not isinstance(state["frozen_specs"], dict) or not all(
            isinstance(k, str) and isinstance(v, str) and HEX64_RE.match(v) for k, v in state["frozen_specs"].items()):
        raise ConfigError("previous state: bad frozen_specs")
    if not isinstance(state["rival_artifacts"], list) or not all(
            isinstance(a, dict) and set(a) == {"sha", "outcome"} and SHA_RE.match(str(a["sha"]))
            and a["outcome"] in OUTCOMES for a in state["rival_artifacts"]):
        raise ConfigError("previous state: bad rival_artifacts")
    if not MONTH_RE.match(str(state["month"])):
        raise ConfigError("previous state: bad month")
    if not isinstance(state["reject_streaks"], dict) or not all(
            isinstance(k, str) and isinstance(v, int) and not isinstance(v, bool) and v > 0
            for k, v in state["reject_streaks"].items()):
        raise ConfigError("previous state: bad reject_streaks")
    for key in ("month_spend_usd_micros", "stage_spend_usd_micros", "runs", "repeat_events", "outage_count",
                "rival_side_streak"):
        if not _count(state[key]):
            raise ConfigError(f"previous state: bad {key}")
    if state["outage_since"] is not None and not TIME_RE.match(str(state["outage_since"])):
        raise ConfigError("previous state: bad outage_since")
    if state["outage_stop"] is not None and not _text(state["outage_stop"], 200):
        raise ConfigError("previous state: bad outage_stop")
    refutations = state["open_refutations"]
    if not isinstance(refutations, list) or len(refutations) > MAX_OPEN_REFUTATIONS or not all(
            isinstance(e, dict) and set(e) == REFUTATION_KEYS and KEY_RE.match(str(e["key"]))
            and _text(e["claim"], 2000) and _refs(e["evidence_refs"]) and _reproducer(e["reproducer"])
            and SHA_RE.match(str(e["first_head"])) and SHA_RE.match(str(e["last_head"])) for e in refutations):
        raise ConfigError("previous state: bad open_refutations")
    claims = state["open_claims"]
    if not isinstance(claims, list) or len(claims) > MAX_OPEN_CLAIMS or not all(
            isinstance(c, dict) and set(c) == CLAIM_KEYS and CLAIM_ID_RE.match(str(c["id"]))
            and _text(c["claim"], 2000) and _refs(c["evidence_refs"])
            and (c["reproducer"] is None or _reproducer(c["reproducer"]))
            and (c["observed"] is None or isinstance(c["observed"], dict))
            and SHA_RE.match(str(c["first_head"])) and isinstance(c["rewritten"], bool) for c in claims):
        raise ConfigError("previous state: bad open_claims")
    pending = state["pending_rival"]
    if pending is not None and not (
            isinstance(pending, dict) and set(pending) == {"sha", "rival"} and SHA_RE.match(str(pending["sha"]))
            and isinstance(pending["rival"], dict) and pending["rival"].get("verdict") in ("refuted", "not_refuted")
            and isinstance(pending["rival"].get("attempts"), list)):
        raise ConfigError("previous state: bad pending_rival")
    return state


def rollover(state: dict[str, Any], month: str) -> dict[str, Any]:
    new = dict(state)
    if new["month"] != month:
        new["month"] = month
        new["month_spend_usd_micros"] = 0
    new["origin"] = state["origin"]
    return new
