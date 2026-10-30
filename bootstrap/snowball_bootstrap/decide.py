"""The acceptance decision (`tohum/29b`, "Kabul" and "Aşama 0 çıkışının (A) parçası").

Pure function of the jobs' verified outputs and of the time it is handed. Nothing here runs code or calls a
network. Besides the verdict it keeps the referee's memory of the rival (`tohum/29`, "Rakibin kuralları"):
proven defects that must stop reproducing (E08), claims no reproducer proved on the head they were made for, with
what their reproducers showed since (E07, E260), the rival result a retry reuses (E20), and what counts against the
Founder and what only warns the operator (E11, E12).
"""

from __future__ import annotations

import copy
import datetime
import hashlib
from typing import Any

from . import secretscan, stages
from .reproduce import reproducer_key
from .rival import REPRODUCER_FIELDS
from .state import MAX_OPEN_CLAIMS, MAX_OPEN_REFUTATIONS

RESULT_SCHEMA = "snowball-bootstrap-result/1"
VALID_RIVAL = ("refuted", "not_refuted")


def utc_now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


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


REFUTATION_KINDS = ("refutation_reproduced", "refutation_still_reproduces")


def signature(reason: dict[str, Any]) -> str:
    """What makes two rejections "the same": the kind and the test, check or condition it names.

    A proven defect is named by its reproducer (the command and what it expects), neither by its position among
    the rival's attempts nor by how the claim is worded: found again in other words, or still reproducing from
    the state, it is one streak, and three different defects in a row are three (E08).
    """
    if reason["kind"] in REFUTATION_KINDS:
        return "refutation:" + reason["ref"].removeprefix("repro:")
    return f"{reason['kind']}:{reason.get('test_id') or reason['ref']}"


OUTAGE_RETRY_LIMIT = 3  # consecutive infrastructure failures of one commit before `poll` parks it
OUTAGE_GIVE_UP_DAYS = 7  # a parked commit is retried once a day for this long, then stops visibly (E12)
RIVAL_SIDE_WARN = 3  # the rival's own failures in a row that warn the operator (E11)
# A rival-side failure another run may not repeat leaves the commit unevaluated, so the next run reviews it again,
# until RIVAL_SIDE_WARN failures in a row; the Founder is never left to push something it cannot fix (E166).
# These two would only fail again: no budget left, or a request the API refuses as such (E12).
RIVAL_SIDE_FINAL = ("budget", "request_rejected")
# Rejections that say nothing about the Founder's work: they leave its streaks exactly as they were (E11).
NOT_THE_FOUNDERS = ("budget", "pull_error", "infra", "rival_missing")
# What an unresolved rival run can say that the Founder can fix: a push too large to send or to review in the
# turns given, or a secret-shaped string in it. Every other unresolved run is the rival's own failure.
FOUNDERS_RIVAL_REASONS = ("prompt_too_large", "max_turns", "secret_in_prompt")
DOCKER_ERROR = 125  # `docker run` exit code for a failure of docker itself
# Heads with nothing of the Founder's to judge: an unchanged tree or ledger rows alone (`none`), and the operator's
# seed delivery itself (`seed_update`, `25` 10b, E88). Noop: no streak, no rival artifact, no acceptance.
NOTHING_TO_JUDGE = ("none", "seed_update")
# The (A) conditions of `asama-0/10` the seed has no check for yet (E162; their rows E107, E100/E132, E130/E131, E102,
# E79). Until a check exists each keeps the exit closed as `exit_condition` `not_checked:<anchor>`, never passes
# silently. The Founder cannot fix them, so they are not its rejections (`29b` "Ret hafızası").
EXIT_NOT_CHECKED = ("kurucu-defteri", "is-akisi", "agac", "genellik", "spec", "durustluk")
NOT_CHECKED = "not_checked:"


def counts_against_founder(reason: dict[str, Any]) -> bool:
    if reason["kind"] in NOT_THE_FOUNDERS:
        return False
    if reason["kind"] == "rival_unresolved":
        return str(reason["ref"]).split(":", 1)[0] in FOUNDERS_RIVAL_REASONS
    if reason["kind"] == "exit_condition":
        return not str(reason["ref"]).startswith(NOT_CHECKED)
    return True


def _learning(state: dict[str, Any], reasons: list[dict[str, Any]], limit: int) -> dict[str, Any]:
    """Update the rejection streaks of an evaluated commit and say which ones repeat.

    A signature's streak grows while every evaluated commit is rejected for it and ends at the first commit
    that is not; an accepted commit has no reasons, so it ends them all. A rejection only for reasons the
    Founder cannot act on (the rival's own failure, the budget, a referee step) leaves every streak as it was.
    """
    counted = [r for r in reasons if counts_against_founder(r)]
    if counted or not reasons:
        old = state["reject_streaks"]
        now = sorted({signature(r) for r in counted})
        state["reject_streaks"] = {sig: old.get(sig, 0) + 1 for sig in now}
        state["repeat_events"] += sum(1 for sig in now if sig in old)
    streaks = state["reject_streaks"]
    return {"repeated": sorted(s for s, n in streaks.items() if n >= 2),
            "not_learning": sorted(s for s, n in streaks.items() if n >= limit),
            "repeat_events": state["repeat_events"]}


def _reproducer(rep: dict[str, Any] | None) -> dict[str, Any] | None:
    return None if rep is None else {k: rep.get(k) for k in REPRODUCER_FIELDS}


def _observed(result: dict[str, Any] | None, head: str) -> dict[str, Any] | None:
    """What a claim's reproducer showed and on which head, for the next rival (E07, E260)."""
    if result is None:
        return None
    seen = {k: result.get(k) for k in ("exit", "timed_out", "shown", "contradicted", "tautological", "stdout_tail",
                                       "stderr_tail")}
    return dict(seen, head=head)


def _remember(refutations: dict[str, dict[str, Any]], key: str, source: dict[str, Any], head: str) -> None:
    """Keep a proven defect so every later code head is checked for it (E08)."""
    if key in refutations:
        refutations[key]["last_head"] = head
        return
    refutations[key] = {"key": key, "claim": source["claim"][:2000], "evidence_refs": list(source["evidence_refs"])[:20],
                        "reproducer": _reproducer(source["reproducer"]), "first_head": head, "last_head": head}


def _claim_id(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def _keep_claim(claims: list[dict[str, Any]], attempt: dict[str, Any], result: dict[str, Any] | None,
                head: str) -> None:
    """A refutation no reproducer proved on the head it was made for stays open (E07). Naming an open claim sends it
    again, to be judged on the head under review: its reproducer as kept says what it showed there, a different one
    replaces it, once (E260: sending a claim again unchanged is no rewrite)."""
    target = attempt.get("open_claim")
    existing = next((c for c in claims if c["id"] == target), None) if target else None
    if existing is not None:
        if "reproducer" in attempt:
            rep = _reproducer(attempt["reproducer"])
            if rep == _reproducer(existing["reproducer"]):
                existing["observed"] = _observed(result, head)
            elif not existing["rewritten"]:
                existing.update(reproducer=rep, observed=_observed(result, head), rewritten=True)
        return
    claim_id = _claim_id(attempt["claim"])
    if any(c["id"] == claim_id for c in claims):
        return
    claims.append({"id": claim_id, "claim": attempt["claim"][:2000], "evidence_refs": list(attempt["evidence_refs"])[:20],
                   "reproducer": _reproducer(attempt.get("reproducer")), "observed": _observed(result, head),
                   "first_head": head, "rewritten": False})


def _module_less_green(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """`module_less_green:MFk` for each micro-feature with a test that stayed green without its module
    (`asama-0/14`; `tohum/04` 1: a test that stays green when the change is taken away is not a test)."""
    green: dict[int, list[dict[str, Any]]] = {}
    for m in results:
        if m["stayed_green"]:
            green.setdefault(m["mf"], []).append(m)
    return [_reason("module_less_green", ref=f"MF{mf}",
                    detail=f"{', '.join(m['test_id'] for m in found)} stayed green without {found[0]['module']}"
                           + ("" if found[0]["module_present"] else " (the path was not in the tree)"))
            for mf, found in sorted(green.items())]


def decide(meta: dict[str, Any], run: dict[str, Any] | None, rival: dict[str, Any] | None,
           repro: list[dict[str, Any]] | None, job_results: dict[str, str],
           rival_min_attempts: int, repeat_reject_limit: int, *,
           state_repro: list[dict[str, Any]] | None = None, now: str | None = None,
           table: stages.StageTable | None = None) -> dict[str, Any]:
    """Return the signed result (including the next state).

    ``repro`` holds the results of this rival's reproducers, ``state_repro`` those of the reproducers the state
    keeps (proven defects and open claims) that `pull` asked for in ``meta["state_repro"]``. ``table`` is the
    Stage 0 table (`stages/stage0.json` when not given): the exit needs every one of its micro-features.
    """
    table = table or stages.load(0)
    state = copy.deepcopy(meta["state"])
    now = now or utc_now()
    head, base, kind = meta["head"], meta["base"], meta["kind"]
    reasons: list[dict[str, Any]] = [_reason(r) for r in meta.get("pre_reasons", [])]
    evaluate = bool(meta.get("evaluate", True))
    outage = False  # an infrastructure failure: the commit is retried, never counted as a rejection
    stop = None  # an outage only the operator can end (an isolation fault, E12)
    warnings: list[str] = []
    green = run is not None and bool(run.get("green"))

    # A valid rival result whose reproducers could not run is reused by the retry of the same head: one rival
    # attempt per artifact (E20, `29`). It was booked when it was made.
    pending = state.get("pending_rival")
    reuse = bool(meta.get("reuse_rival")) and isinstance(pending, dict) and pending.get("sha") == head
    if reuse:
        rival = pending["rival"]

    # The rival is skipped on purpose when the tests are red (it would spend budget on a commit
    # that is rejected anyway), so it is expected only for spec requests or green test runs.
    rival_expected = (bool(meta.get("run_rival")) or reuse) and (kind == "spec" or green)
    for job, expected in (("getir", meta.get("run_tests")), ("kos", meta.get("run_tests")),
                          ("cagir", rival_expected and not reuse)):
        if expected and job_results.get(job) != "success":
            reasons.append(_reason("infra", ref=f"{job}:{job_results.get(job)}"))
            evaluate = False
            outage = True

    tests = (run or {}).get("tests", [])
    vectors = (run or {}).get("vectors", [])
    controls = (run or {}).get("controls", [])
    module_less = (run or {}).get("module_less", [])
    # A group a finished micro-feature owns and the seed has no vectors for is the seed's gap, not the Founder's:
    # a code push is told (the vectors run from the push after a seed epoch adds them), the exit waits (`29d`).
    groups_missing = list((run or {}).get("vector_groups_missing", [])) if meta.get("run_tests") else []
    if meta.get("run_tests") and run is not None:
        broken = [c["id"] for c in controls if not c["ok"]]
        if not broken and (any(t.get("exit") == DOCKER_ERROR for t in tests)
                           or any(v.get("runner_fault") for v in vectors)  # E141: docker failed under a vector
                           or any(m.get("runner_fault") for m in module_less)):
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
            licensed = True
            for lic in (run or {}).get("licenses", []):
                if not lic["allowed"]:
                    licensed = False
                    reasons.append(_reason("license_not_allowed",
                                           ref=f"{lic['name']}=={lic['version']}:{lic['expression']}"))
            if not tests:
                reasons.append(_reason("zero_tests"))
            reasons += _module_less_green(module_less)
            clean = bool(tests) and licensed and all(t["ok"] for t in tests) and all(v["ok"] for v in vectors)
            unrun = set(meta.get("module_less") or []) - {m["mf"] for m in module_less}
            if clean and unrun:  # a green run must carry module-less red for every micro-feature pull named (E05)
                reasons.append(_reason("infra", ref="kos:module_less_incomplete"))
                evaluate = False
                outage = True
        if kind != "exit":
            warnings += [f"vector_group_missing:{g}" for g in groups_missing]

    # Whatever a rival run spent is booked as soon as its record is here, whether or not this run can judge it
    # (E13, K7: with run.json missing the rival is not "expected", and its spend used to vanish). A reused
    # result was booked when it was made.
    if rival is not None and not reuse:
        state["month_spend_usd_micros"] += int(rival.get("cost_usd_micros", 0))
        state["stage_spend_usd_micros"] += int(rival.get("cost_usd_micros", 0))

    rival_valid = False
    rival_side = False  # an evaluated run in which the rival itself failed (E11)
    if rival_expected:
        if rival is None:
            if job_results.get("cagir") == "success":  # a failed job is already reported as infra
                reasons.append(_reason("rival_missing"))
                rival_side = True
                if state["rival_side_streak"] + 1 < RIVAL_SIDE_WARN:
                    evaluate = False  # review this commit again (E166)
                    warnings.append(f"rival_side_retry:{state['rival_side_streak'] + 1}")
        else:
            if rival.get("verdict") in VALID_RIVAL:
                rival_valid = True
            else:
                said = [str(w) for w in rival.get("reasons", [])] or ["unresolved"]
                for why in said:
                    reasons.append(_reason("rival_unresolved", ref=why))
                if any(w.startswith("api_error") for w in said):
                    evaluate = False  # identity, quota, network, timeout or isolation: retry this commit later
                    outage = True
                    stop = next((w.split(":", 1)[1] for w in said if w.startswith("api_error:isolation_")), None)
                else:
                    rival_side = not any(counts_against_founder(_reason("rival_unresolved", ref=w)) for w in said)
                    if (rival_side and not any(w.startswith(RIVAL_SIDE_FINAL) for w in said)
                            and state["rival_side_streak"] + 1 < RIVAL_SIDE_WARN):
                        evaluate = False  # review this commit again (E166)
                        warnings.append(f"rival_side_retry:{state['rival_side_streak'] + 1}")
                warnings += [w for w in said if w.startswith("request_rejected")]

    # Reproducers: the rival's own (or the reused rival's) and the state's on code and exit heads (E07, E08).
    attempts = rival.get("attempts", []) if rival_valid else []
    with_repro = {i for i, a in enumerate(attempts) if "reproducer" in a}
    state_expected = list(meta.get("state_repro") or []) if kind in ("code", "exit") and green else []
    state_results = list(state_repro or [])
    complete = True
    if with_repro or state_expected:
        if job_results.get("yeniden") != "success":
            reasons.append(_reason("infra", ref=f"yeniden:{job_results.get('yeniden')}"))
            complete = False
        elif any(r.get("runner_fault") for r in (repro or []) + state_results):  # docker failed: proves nothing
            reasons.append(_reason("infra", ref="yeniden:docker"))
            complete = False
        elif ({r["attempt_index"] for r in repro or []} != with_repro
              or {s["key"] for s in state_results} != set(state_expected)):
            reasons.append(_reason("infra", ref="yeniden:incomplete"))  # a reproducer that never ran (E05)
            complete = False
        if not complete:
            evaluate = False
            outage = True

    refutations = {e["key"]: e for e in state["open_refutations"]}
    claims = state["open_claims"]
    waived = sorted(set(meta.get("waived") or []) & set(refutations))
    for key in waived:  # the operator closed it by hand (`control.json`, `29`)
        refutations.pop(key)
    if complete and not outage:
        reported: set[str] = set()
        # The state's reproducers first: they ran as the state was when `pull` read it.
        for s in state_results:
            if s["source"] == "refutation":
                entry = refutations.get(s["key"])
                # A proven defect still reproduces while its symptom shows because of the code, whatever else the head
                # prints: by the contract the symptom never shows on correct code, and what the reproducer calls
                # correct is no proof the code is (E08; E260 left this rule as it was).
                if entry is not None and s["reproduced"]:
                    entry["last_head"] = head
                    reasons.append(_reason("refutation_still_reproduces", ref=f"repro:{s['key']}", detail=entry["claim"]))
                    reported.add(s["key"])
                continue
            claim = next((c for c in claims if c["id"] == s["key"]), None)
            if claim is not None:
                # A reproducer proves only on the head it was written for (E260). An open claim's did not prove there,
                # so its showing here says only that this head behaves the way it expects: the defect if it expects
                # the symptom, the fix if it expects what correct code prints, which the bytes cannot tell apart. It
                # is recorded for the next rival, which can send it again to be judged on the head it reviews.
                claim["observed"] = _observed(s, head)
        by_index = {r["attempt_index"]: r for r in repro or []}
        for i, attempt in enumerate(attempts):
            result = by_index.get(i)
            # Proof on the head it is judged on: the symptom shows because of the code, and the head does not show what
            # the reproducer itself calls correct (E260); a head that shows both leaves the claim open.
            if result is not None and result["reproduced"] and not result["contradicted"]:
                key = reproducer_key(attempt["reproducer"])
                if key not in reported:
                    reasons.append(_reason("refutation_reproduced", ref=f"repro:{key}", detail=attempt["claim"]))
                    reported.add(key)
                _remember(refutations, key, attempt, head)
                proven = (attempt.get("open_claim"), _claim_id(attempt["claim"]))  # a claim proven is no longer open
                claims[:] = [c for c in claims if c["id"] not in proven]
            elif rival["verdict"] == "refuted":
                _keep_claim(claims, attempt, result, head)

    exit_block: dict[str, Any] = {"requested": kind == "exit", "transferable": False, "missing": []}
    if kind == "exit":
        exit_block["pinned_sha"] = (meta.get("exit_request") or {}).get("sha")  # None when malformed (E41)
        missing = exit_block["missing"]
        manifest = meta.get("manifest") or {}
        if list(manifest.get("done_mf", [])) != list(range(1, table.count + 1)):
            missing.append("not_all_micro_features_done")
        missing += [f"vector_group_missing:{g}" for g in groups_missing]  # `asama-0/10` #testler: every group passes
        survived = {a["sha"] for a in state["rival_artifacts"] if a["outcome"] == "survived"}  # E20
        others = survived - {base}
        if base not in survived:
            missing.append("no_rival_attempt_on_exit_sha")
        if len(others) < rival_min_attempts:
            missing.append(f"rival_attempts:{len(others)}<{rival_min_attempts}")
        if not meta.get("referee_tree_sha256"):
            missing.append("referee_tree_hash")
        missing += [NOT_CHECKED + anchor for anchor in EXIT_NOT_CHECKED]  # E162: closed until the seed checks it
        for m in missing:
            reasons.append(_reason("exit_condition", ref=m))

    accepted = not reasons and kind in ("spec", "code", "exit")
    if kind == "spec":
        verdict = "frozen" if accepted else "rejected"
    elif kind in NOTHING_TO_JUDGE:
        verdict = "noop"
    else:
        verdict = "accepted" if accepted else "rejected"

    if accepted:
        state["last_accepted_sha"] = head
        if kind == "spec":
            state["frozen_specs"].update(meta.get("spec_dir_hashes", {}))
        # A proven defect closes only on an accepted head where it ran and no longer reproduces (E08).
        for s in state_results:
            if s["source"] == "refutation" and not s["reproduced"]:
                refutations.pop(s["key"], None)
    state["open_refutations"] = list(refutations.values())[-MAX_OPEN_REFUTATIONS:]
    state["open_claims"] = claims[-MAX_OPEN_CLAIMS:]

    learning = {"repeated": [], "not_learning": [], "repeat_events": state["repeat_events"]}
    if evaluate and kind not in NOTHING_TO_JUDGE:
        state["last_evaluated_sha"] = head
        learning = _learning(state, reasons, repeat_reject_limit)
    elif evaluate:  # an unchanged tree (an empty commit, a revert): nothing to judge and nothing to learn from
        state["last_evaluated_sha"] = head
    if outage:
        if state["outage_sha"] == head:
            state["outage_count"] += 1
        else:
            state["outage_sha"], state["outage_count"], state["outage_since"] = head, 1, now
        state["outage_stop"] = stop
    elif evaluate and kind not in NOTHING_TO_JUDGE:
        state.update(outage_sha=None, outage_count=0, outage_since=None, outage_stop=None)

    if rival_valid:
        state["rival_side_streak"] = 0
    elif rival_side:  # counted on a retried run too, so the retries end (E166)
        state["rival_side_streak"] += 1
        if state["rival_side_streak"] >= RIVAL_SIDE_WARN:
            warnings.append(f"rival_side_streak:{state['rival_side_streak']}")

    if rival_valid and not complete:  # its reproducers could not run: the retry reuses this verdict (E20)
        state["pending_rival"] = {"sha": head, "rival": copy.deepcopy(rival)}  # with what it cost, booked once
    elif evaluate or (isinstance(pending, dict) and pending.get("sha") != head):
        state["pending_rival"] = None
    if rival_valid and complete and not outage and all(a["sha"] != head for a in state["rival_artifacts"]):
        refuted_here = any(r["kind"] in REFUTATION_KINDS for r in reasons)
        state["rival_artifacts"].append({"sha": head, "outcome": "refuted" if refuted_here else "survived"})

    if kind == "exit" and accepted:
        exit_block["transferable"] = True
        exit_block["referee_tree_sha256"] = meta["referee_tree_sha256"]
        exit_block["brain_sha"] = head
    if kind == "exit":
        exit_block["repeat_events"] = state["repeat_events"]
        # Listed, never proven here (E260): no rival runs on an exit head, so the operator, who owns the exit's (B) part,
        # reads what each claim's reproducer showed and on which head (`asama-0/10` #rakip).
        exit_block["open_claims"] = [{"id": c["id"], "claim": c["claim"], "first_head": c["first_head"],
                                      "observed": c["observed"]} for c in state["open_claims"]]
        if verdict == "rejected" and evaluate and meta.get("exit_request_sha256"):
            # `asama-0/10`, `26c`: the same bytes left in place are ignored in later code pushes (E97), so a request the
            # seed cannot accept yet (E162) never turns every later code push into `exit_request_not_alone`.
            state["rejected_exit_request"] = meta["exit_request_sha256"]
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
        # Module-less red, signed with the verdict: each finished MF's tests went red without its module (E169).
        "module_less": module_less,
        "rival": rival,
        "rival_reused": reuse,  # the rival result of an earlier run of this head; its cost was booked then
        "reproducers": repro or [],
        "state_reproducers": state_results,
        "exit": exit_block,
        "learning": learning,
        "warnings": warnings,
        "waived": waived,
        "licenses": (run or {}).get("licenses", []),
        "state": state,
        "rejection": rejection,
    }
