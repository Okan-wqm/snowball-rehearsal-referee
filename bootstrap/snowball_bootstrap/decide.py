"""The acceptance decision (`tohum/29b`, "Kabul" and "Aşama 0 çıkışının (A) parçası").

Pure function of the jobs' verified outputs. Nothing here runs code or calls a network.
"""

from __future__ import annotations

import copy
import hashlib
from typing import Any

from . import secretscan
from .manifest import STAGE0_MF_COUNT

RESULT_SCHEMA = "snowball-bootstrap-result/1"
VALID_RIVAL = ("refuted", "not_refuted")


def _excerpt(text: str) -> str | None:
    tail = text[-2000:]
    return None if secretscan.scan(tail) else tail


WITHHELD = "(withheld: the text matches a secret pattern)"


def _redacted(text: Any) -> Any:
    """A published copy of a free-text field: dropped when it carries a secret, like a reason's detail."""
    return WITHHELD if isinstance(text, str) and secretscan.scan(text) else text


def _reason(kind: str, ref: str = "", detail: str = "", test_id: str | None = None) -> dict[str, Any]:
    item: dict[str, Any] = {"kind": kind, "ref": ref,
                            "detail_sha256": hashlib.sha256(detail.encode("utf-8", "replace")).hexdigest()}
    if test_id is not None:
        item["test_id"] = test_id
    excerpt = _excerpt(detail) if detail else None
    if excerpt:
        item["detail"] = excerpt
    return item


def signature(reason: dict[str, Any]) -> str:
    """What makes two rejections "the same": the kind and the test, check or condition it names.

    A reproduced refutation is named by its claim, not by its position among the rival's attempts: every
    refutation is "attempt 0", and three different defects in a row must not stop the Founder as not learning.
    """
    if reason["kind"] == "refutation_reproduced":
        return f"{reason['kind']}:{reason['detail_sha256'][:12]}"
    return f"{reason['kind']}:{reason.get('test_id') or reason['ref']}"


OUTAGE_RETRY_LIMIT = 3  # consecutive infrastructure failures of one commit before `poll` parks it
NOT_THE_FOUNDERS = ("budget", "pull_error")  # stops the run for the operator; never counts as the Founder not learning
DOCKER_ERROR = 125  # `docker run` exit code for a failure of docker itself


def _learning(state: dict[str, Any], reasons: list[dict[str, Any]], limit: int) -> dict[str, Any]:
    """Update the rejection streaks of an evaluated commit and say which ones repeat.

    A signature's streak grows while every evaluated commit is rejected for it and ends at the first
    commit that is not; an accepted commit has no reasons, so it ends them all.
    """
    old = state["reject_streaks"]
    now = sorted({signature(r) for r in reasons if r["kind"] not in NOT_THE_FOUNDERS})
    state["reject_streaks"] = {sig: old.get(sig, 0) + 1 for sig in now}
    state["repeat_events"] += sum(1 for sig in now if sig in old)
    streaks = state["reject_streaks"]
    return {"repeated": sorted(s for s, n in streaks.items() if n >= 2),
            "not_learning": sorted(s for s, n in streaks.items() if n >= limit),
            "repeat_events": state["repeat_events"]}


def decide(meta: dict[str, Any], run: dict[str, Any] | None, rival: dict[str, Any] | None,
           repro: list[dict[str, Any]] | None, job_results: dict[str, str],
           rival_min_attempts: int, repeat_reject_limit: int) -> dict[str, Any]:
    """Return the signed result (including the next state)."""
    state = copy.deepcopy(meta["state"])
    head, base, kind = meta["head"], meta["base"], meta["kind"]
    reasons: list[dict[str, Any]] = [_reason(r) for r in meta.get("pre_reasons", [])]
    evaluate = bool(meta.get("evaluate", True))
    outage = False  # an infrastructure failure: the commit is retried, never counted as a rejection

    # The rival is skipped on purpose when the tests are red (it would spend budget on a commit
    # that is rejected anyway), so it is expected only for spec requests or green test runs.
    rival_expected = bool(meta.get("run_rival")) and (
        kind == "spec" or (run is not None and bool(run.get("green"))))
    for job, expected in (("getir", meta.get("run_tests")), ("kos", meta.get("run_tests")),
                          ("cagir", rival_expected)):
        if expected and job_results.get(job) != "success":
            reasons.append(_reason("infra", ref=f"{job}:{job_results.get(job)}"))
            evaluate = False
            outage = True

    tests = (run or {}).get("tests", [])
    vectors = (run or {}).get("vectors", [])
    controls = (run or {}).get("controls", [])
    if meta.get("run_tests") and run is not None:
        broken = [c["id"] for c in controls if not c["ok"]]
        if not broken and any(t.get("exit") == DOCKER_ERROR for t in tests):
            broken = ["docker"]
        if broken:  # the sandbox itself failed: nothing it printed is evidence about the push
            reasons.append(_reason("infra", ref="kos:" + ",".join(broken)))
            evaluate = False
            outage = True
        else:
            for t in tests:
                if not t["ok"]:
                    reasons.append(_reason("test_failed", ref=t["cmd_sha256"], detail=t.get("output_tail", ""),
                                           test_id=t["id"]))
            for v in vectors:
                if not v["ok"]:
                    reasons.append(_reason("vector_failed", ref=v["id"], detail=v.get("detail", "")))
            for lic in (run or {}).get("licenses", []):
                if not lic["allowed"]:
                    reasons.append(_reason("license_not_allowed",
                                           ref=f"{lic['name']}=={lic['version']}:{lic['expression']}"))
            if not tests:
                reasons.append(_reason("zero_tests"))

    rival_valid = False
    if rival_expected:
        if rival is None:
            if job_results.get("cagir") == "success":  # a failed job is already reported as infra
                reasons.append(_reason("rival_missing"))
        else:
            state["month_spend_usd_micros"] += int(rival.get("cost_usd_micros", 0))
            state["stage_spend_usd_micros"] += int(rival.get("cost_usd_micros", 0))
            if rival.get("verdict") in VALID_RIVAL:
                rival_valid = True
                if rival.get("reproducer_count") and job_results.get("yeniden") != "success":
                    reasons.append(_reason("infra", ref=f"yeniden:{job_results.get('yeniden')}"))
                    evaluate = False
                    outage = True
                elif any(r.get("runner_fault") for r in repro or []):  # docker failed: "not reproduced" proves nothing
                    reasons.append(_reason("infra", ref="yeniden:docker"))
                    evaluate = False
                    outage = True
                elif ({r["attempt_index"] for r in repro or []}
                      != {i for i, a in enumerate(rival.get("attempts", [])) if "reproducer" in a}):
                    reasons.append(_reason("infra", ref="yeniden:incomplete"))  # a reproducer that never ran (E05)
                    evaluate = False
                    outage = True
                for r in repro or []:
                    if r["reproduced"]:
                        attempt = rival["attempts"][r["attempt_index"]]
                        reasons.append(_reason("refutation_reproduced", ref=f"attempt:{r['attempt_index']}",
                                               detail=attempt["claim"]))
            else:
                for why in rival.get("reasons", []) or ["unresolved"]:
                    reasons.append(_reason("rival_unresolved", ref=why))
                if any(str(w).startswith("api_error") for w in rival.get("reasons", [])):
                    evaluate = False  # identity, quota, network or timeout: retry this commit later
                    outage = True

    exit_block: dict[str, Any] = {"requested": kind == "exit", "transferable": False, "missing": []}
    if kind == "exit":
        exit_block["pinned_sha"] = (meta.get("exit_request") or {}).get("sha")  # None when malformed (E41)
        missing = exit_block["missing"]
        manifest = meta.get("manifest") or {}
        if list(manifest.get("done_mf", [])) != list(range(1, STAGE0_MF_COUNT + 1)):
            missing.append("not_all_micro_features_done")
        others = set(state["rival_artifacts"]) - {base}
        if base not in state["rival_artifacts"]:
            missing.append("no_rival_attempt_on_exit_sha")
        if len(others) < rival_min_attempts:
            missing.append(f"rival_attempts:{len(others)}<{rival_min_attempts}")
        if not meta.get("referee_tree_sha256"):
            missing.append("referee_tree_hash")
        for m in missing:
            reasons.append(_reason("exit_condition", ref=m))

    accepted = not reasons and kind in ("spec", "code", "exit")
    if kind == "spec":
        verdict = "frozen" if accepted else "rejected"
    elif kind == "none":
        verdict = "noop"
    else:
        verdict = "accepted" if accepted else "rejected"

    learning = {"repeated": [], "not_learning": [], "repeat_events": state["repeat_events"]}
    if evaluate and kind != "none":
        state["last_evaluated_sha"] = head
        learning = _learning(state, reasons, repeat_reject_limit)
    elif evaluate:  # an unchanged tree (an empty commit, a revert): nothing to judge and nothing to learn from
        state["last_evaluated_sha"] = head
    if outage:
        if state["outage_sha"] == head:
            state["outage_count"] += 1
        else:
            state["outage_sha"], state["outage_count"] = head, 1
    elif evaluate and kind != "none":
        state["outage_sha"], state["outage_count"] = None, 0
    if accepted:
        state["last_accepted_sha"] = head
        if kind == "spec":
            state["frozen_specs"].update(meta.get("spec_dir_hashes", {}))
    if rival_valid and head not in state["rival_artifacts"]:
        state["rival_artifacts"].append(head)
    if kind == "exit" and accepted:
        exit_block["transferable"] = True
        exit_block["referee_tree_sha256"] = meta["referee_tree_sha256"]
        exit_block["brain_sha"] = head
    if kind == "exit":
        exit_block["repeat_events"] = state["repeat_events"]
    state["runs"] += 1
    state["origin"] = "artifact"

    rejection = None
    if verdict == "rejected":
        rejection = {"sha": head, "kind": kind, "reasons": reasons}
    return {
        "schema": RESULT_SCHEMA,
        "head": head,
        "base": base,
        "kind": kind,
        "verdict": verdict,
        "reasons": reasons,
        "tests": [dict(t, output_tail=_redacted(t.get("output_tail"))) if "output_tail" in t else t for t in tests],
        "vectors": [dict(v, detail=_redacted(v.get("detail"))) if "detail" in v else v for v in vectors],
        "controls": controls,
        "rival": rival,
        "reproducers": repro or [],
        "exit": exit_block,
        "learning": learning,
        "licenses": (run or {}).get("licenses", []),
        "state": state,
        "rejection": rejection,
    }
