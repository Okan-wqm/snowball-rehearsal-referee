"""``yaz``'s D6: the cycle's writes on the target, from D5's decision, D7's end and D8's step (stage 0).

Rules: asama-0/01 D6 (``yaz`` writes ``brain/c/<id>``, the pull request, the check and the merge, and one
``brain/state`` commit per cycle with the signed root and ``status.md``; every ref under ``refs/heads/brain/``;
the chain verified before the write; judges MF9, 10, 11, 16), tohum/07 and tohum/01b (merges are serial, by pull
request; ``brain/state`` takes one direct commit per cycle on the head D1 verified), tohum/13 and tohum/28 (a chain
break or a root that cannot be signed is a hard stop), asama-0/10a ``#model`` (the canary's ``cost`` row is written).

**Inputs** (``write``): ``art``, the ``pulled`` artifact (``loop.pulled.read``): its ``brain/state`` ledger, roots
file and ``status.md`` as D1 read them, its heads, its candidates, its policy; ``tree``, the directory its tree was
extracted to (the tree D3 ran on and D5 judged); ``decided``, ``loop.decide``'s ``{decisions, merge}``; ``cost``,
the cost rows of this cycle's ``response`` (``loop.cagir.read_response``); ``writer``, a ``target.write.Writer`` on
the target's repository; ``signer``, the root's signer (``loop.sign.SigstoreSigner`` in the job); ``imports``,
``setup/imports.jsonl``'s bytes (``status.block``'s human-touch count); ``cycle_id`` and ``ts``; ``base_lint``,
the lint totals of the base this cycle's ``kos`` ran (``loop.watch.base_lint``: ``{base_run_sha256, counts}``,
required when D5 chose a merge, else ``Unusable``); ``end``, D7's sentinel to end, ``{merge_sha, verdict, runs,
flaky, sha256, facts?}`` (``loop.watch.read``'s verified answer at ``brain/integration``'s head, with
``loop.watch.facts`` on a red), or ``None``; ``drill``, ``loop.drill.step``'s answer or ``None``: only ``commit``
(``{payload}``) and ``plant`` (``{instance_id, path, content}``) write; an action ``loop.drill`` does not give is
``Unusable``; ``gate``, the payload of the toy's ``copy_gate`` row (``harness.pass_row.gate_payload``) when the copy's
genesis gate opened on this cycle's state, or ``None``; ``passed``, the payload of the toy's PASS row
(``harness.pass_row.judge``'s ``payload``) when the toy's and the copy's states were judged ``PASS``, or ``None``.

**Order.** Nothing is written on the target before every check holds, and nothing is signed before the rows are
planned:

1. the merge, when D5 chose one: its diff applied to the tree (``target.land.applied``, the one application
   ``activate`` makes); a reason here means D5 chose a candidate that cannot be written, ``Unusable``. An ``end``
   must be of ``brain/integration``'s head in a cycle with no merge (D5 merges nothing while a sentinel is
   unfinished), and MF12's ``gate.sentinel.decide`` of its runs must give its ``verdict`` (and ``flaky``): a red's
   ``gate.revert.assess`` of its runs and facts must be a revert, so its cause is known before any write; a green
   or flaky one is ended by a row (``ledger.serial``); anything else (a ``rerun``, a verdict its runs do not give)
   is ``Unusable``. A ``plant`` is the cycle's one merge: with D5's merge or an ``end`` it is ``Unusable``, and like a
   merge it needs ``base_lint``;
2. both heads read from the target equal ``pulled``'s (``head_moved:<branch>``, ``Refused``): the state this cycle
   decided on is still the state it writes on, so a second run of the same cycle (a rerun of ``yaz`` after its
   first run wrote) writes nothing;
3. a dry plan: ``ledger.cycle.plan`` of the cycle's rows with the merge's answer left as placeholders and a signer
   that signs nothing (``DRY``): the roots file and the ledger as chains extending themselves (D1's versions are the
   previous ones: nothing was added since), the rows' secret scan, the whole new ledger against ``ledger.schema``,
   the root row's id. A failure is ``Refused`` with ``state_unwritable`` (a ``ledger.append.HardStop`` stays a hard
   stop, ``target.land.HardStop`` with nothing written);
4. the merge landed (``target.land.land``) on ``brain/integration``'s head with the check ``target.branches.CHECK``,
   or a red ``end`` reverted (``target.land.revert``: the revert commit on ``brain/revert/<merge_sha>``, its pull
   request, the same check and the merge), or D8's plant landed (``target.land.plant``: ``brain/drill/<cycle_id>``,
   its pull request, the same check, saying it is no gate decision, and the merge); a green or flaky ``end`` and a
   ``commit`` write nothing on ``brain/integration``;
5. ``ledger.cycle.commit`` on ``brain/state`` at ``pulled``'s head (``ledger.append.TargetState``: the writer
   refuses a moved head before creating anything): the rows, ``status.md``'s block and the signed root, one commit.

A failure after the first write of step 4 or 5 is ``target.land.HardStop`` naming the refs written
(``writer.written``).

**The rows**, in this order, each ``ledger.events``': ``cycle_start {cycle_id}``; ``ratchet_base {base_run_sha256,
counts}`` when the cycle merges or plants (``base_lint``: the merge's lint before, which a later revert reads with
``ledger.serial.lint_before``); per candidate in code-point order of its id, ``ledger.events.decided``'s rows (a
reject's ``decision`` with D5's reasons and ``ledger.events.cause``; the merge's ``decision`` and then its ``merge``
row with ``path``, ``target.land.land``'s ``{pull, head_sha, merge_sha}`` and ``hunk_covered``, the record of
the hunks step 1 applied, ``ledger.events.hunk_covered``); ``revert {merge_sha}`` with
``gate.revert``'s cause for a red ``end``, or ``sentinel {merge_sha, verdict, red: [], flaky}`` for a green or flaky
one (the row that finishes the merge's sentinel, ``ledger.serial``; tohum/26f); D8's ``drill`` row (``commit`` with its payload, or ``plant`` with ``harness.revert_drill``'s
``{drill, family, instance_id, merge_sha}``, the planted merge's SHA; ``ledger.events.drill``); the ``copy_gate`` row
with ``gate`` (``harness.pass_row``'s gate); the ``pass`` row with ``passed`` (tohum/26d); the response's cost rows as
they are; then
``status.block``'s rows (``ledger.cycle``). ``ts`` is the given time; ``snapshot_id`` is ``brain/integration``'s
head in ``pulled`` (the snapshot D3 ran on and D5 judged; the cost row carries the same, ``loop.cagir``). Row ids are
``<cycle_id>:start``, ``<cycle_id>:ratchet``, ``<cycle_id>:c:<cid>``, ``<cycle_id>:m:<cid>``, ``<cycle_id>:revert`` or
``<cycle_id>:sentinel``, ``<cycle_id>:drill``, ``<cycle_id>:gate``, ``<cycle_id>:pass``, ``<cycle_id>:status``
and the root row's ``<cycle_id>:root``. The
status facts' ``canary_cap_usd_micros`` is ``canary_usd`` of ``pulled``'s policy (``loop.cagir.CANARY_USD``, the
cap D4 called with).

Returns ``{merge: {candidate, path, pull, head_sha, merge_sha} | None, revert: {reverted, cause, pull, commit,
merge_sha} | None, plant: {instance_id, pull, head_sha, merge_sha} | None, state_sha, root, rekor_uuid, rows,
edited}``.

Out of scope, stated: which drill step is due (``loop.drill``); whether GitHub's ruleset accepts the writes (``target.write``'s known limits); the signer's program (``loop.sign``).
"""

from __future__ import annotations

from typing import Any

from dispatcher import llm_call
from gate import revert as gate_revert
from gate import sentinel
from harness import pass_row as PR
from harness import revert_drill
from ledger import append, cycle, events, schema
from loop import cagir
from loop import pulled as P
from target import branches as B
from target import land
from target import write as W
import cli

DRILL_ACTIONS = (None, "off", "wait", "none", "commit", "plant")  # loop.drill.step's actions; only the last two write
PLACEHOLDER = {"pull": 1, "head_sha": "0" * 40, "merge_sha": "0" * 40}  # the dry plan's merge answer


class Refused(Exception):
    def __init__(self, reasons: list[str]) -> None:
        super().__init__(", ".join(reasons))
        self.reasons = reasons


class Unusable(ValueError):
    pass


class _Dry:
    """Signs nothing: the dry plan's signer (step 3)."""

    def sign(self, payload: bytes) -> dict:
        return {"uuid": "dry", "identity": "dry", "bundle": b"dry"}


DRY = _Dry()


def merge_change(art: P.Pulled, tree: str, merge: str | None) -> dict | None:
    """D5's merge applied to the tree (``target.land.applied``): ``{reasons: [], path, content}``, ``None`` with no
    merge; a reason means D5 chose a candidate that cannot be written (``Unusable``). Shared with ``activate``."""
    if merge is None:
        return None
    change = land.applied(tree, art.candidates[merge]["diff.patch"].decode("utf-8", "surrogateescape"))
    if change["reasons"]:
        raise Unusable("merge %s cannot be written: %s" % (merge, ", ".join(change["reasons"])))
    return change


def status_facts(art: P.Pulled, cyc: dict) -> dict:
    """``status.block``'s facts of the cycle ``cyc`` (``{cycle_id, ts, snapshot_id}``): its canary cap is
    ``canary_usd`` of ``pulled``'s policy (``loop.cagir.CANARY_USD``). Shared with ``activate``."""
    try:
        cap = llm_call.policy_usd(art.policy_bytes, *cagir.CANARY_USD)
    except llm_call.Unusable as exc:
        raise Unusable(cli.cause(exc)) from None
    return {"ts": cyc["ts"], "snapshot_id": cyc["snapshot_id"], "row_id": "%s:status" % cyc["cycle_id"],
            "canary_cap_usd_micros": cap}


def candidate_rows(cyc: dict, decided: dict, merged: dict | None, change: dict | None) -> list[dict]:
    """D5's decisions as rows, in code-point order of the candidate id (``ledger.events.decided``); ``merged`` is
    the merge's ``{path, pull, head_sha, merge_sha}`` and ``change`` its ``merge_change``, whose ``hunks`` the merge
    row's ``hunk_covered`` records. Shared with ``activate``."""
    out: list[dict] = []
    for cid in sorted(decided["decisions"]):
        out += events.decided(cyc, cid, decided["decisions"][cid]["reasons"],
                              dict(merged, hunks=change["hunks"]) if cid == decided["merge"] else None)
    return out


def write(art: P.Pulled, tree: str, decided: dict, cost: list[dict], writer: W.Writer, signer: Any,
          imports: bytes, cycle_id: str, ts: str, base_lint: dict | None = None,
          end: dict | None = None, drill: dict | None = None, gate: dict | None = None,
          passed: dict | None = None) -> dict[str, Any]:
    """D6, D7's end of a sentinel, D8's step, the gate's and the PASS row (see the module docstring)."""
    cyc = {"cycle_id": cycle_id, "ts": ts, "snapshot_id": art.heads[B.INTEGRATION]}
    merge = decided["merge"]
    change = None
    action = (drill or {}).get("action")
    planted = action == "plant"
    if action not in DRILL_ACTIONS:
        raise Unusable("drill: %r is no action of loop.drill" % (action,))
    if planted and (merge is not None or end is not None):
        raise Unusable("drill: a plant is the cycle's one merge, in a cycle that ends no sentinel")
    if merge is not None or planted:
        if base_lint is None:
            raise Unusable("merge %s: the base's lint totals are unreadable" % (merge or "planted"))
    change = merge_change(art, tree, merge)
    cause = red = None
    if end is not None:
        if merge is not None or end["merge_sha"] != art.heads[B.INTEGRATION]:
            raise Unusable("a sentinel's end is of brain/integration's head, in a cycle that merges nothing")
        try:
            judged = sentinel.decide(end["runs"])
            if (judged["verdict"], judged["flaky"]) != (end["verdict"], end["flaky"]):
                raise Unusable("sentinel: its runs give %s, not %s" % (judged["verdict"], end["verdict"]))
            if judged["verdict"] == "red":
                red, assessed = end, gate_revert.assess(end["runs"], end["facts"])
                if not assessed["revert"]:
                    raise Unusable("revert: the sentinel's runs are not a verified red")
                cause = assessed["cause"]
            elif judged["verdict"] not in schema.SENTINEL_ENDS:
                raise Unusable("sentinel: %s ends nothing" % judged["verdict"])
        except (gate_revert.Unusable, sentinel.Unusable) as exc:
            raise Unusable("sentinel: %s" % cli.cause(exc)) from None
    moved = ["head_moved:%s" % b for b in P.HEAD_BRANCHES if writer.head(b) != art.heads[b]]
    if moved:
        raise Refused(moved)
    facts = status_facts(art, cyc)

    def rows(merged: dict | None, plant_sha: str) -> list[dict]:
        out = [events.start(cyc)]
        if merge is not None or planted:
            out.append(events.ratchet_base(cyc, base_lint["base_run_sha256"], base_lint["counts"]))
        out += candidate_rows(cyc, decided, merged, change)
        if red is not None:
            out.append(events.revert(cyc, red["merge_sha"], cause))
        elif end is not None:
            out.append(events.sentinel(cyc, end["merge_sha"], end["verdict"], end["flaky"]))
        if planted:
            out.append(events.drill(cyc, "plant", revert_drill.plant_payload(drill["instance_id"], plant_sha)))
        elif action == "commit":
            out.append(events.drill(cyc, "commit", drill["payload"]))
        if gate is not None:
            out.append(events.row(cyc, "gate", PR.GATE_ROW[1], gate))
        if passed is not None:
            out.append(events.row(cyc, "pass", PR.PASS_ROW[1], passed))
        return out + list(cost)

    ledger, roots = art.state[B.STATE_LEDGER], art.state[B.STATE_ROOTS]
    args = (ledger, ledger, roots, roots, art.status)
    root_row_id = "%s:root" % cycle_id
    try:
        cycle.plan(*args, rows(dict(PLACEHOLDER, path=change["path"]) if change else None, PLACEHOLDER["merge_sha"]),
                   imports, facts, DRY, root_row_id)
    except append.HardStop as exc:
        raise land.HardStop("state: %s" % cli.cause(exc), []) from None
    except cycle.FAILURES as exc:
        raise Refused(["state_unwritable: %s" % cli.cause(exc)]) from None
    state = append.TargetState(writer, art.heads[B.STATE])
    merged = reverted = plant = None
    try:
        if change is not None:
            merged = dict(land.land(writer, merge, change["path"], change["content"], art.heads[B.INTEGRATION],
                                    B.CHECK), path=change["path"])
        if red is not None:
            reverted = dict(land.revert(writer, red["merge_sha"], red["runs"], red["facts"], B.CHECK),
                            reverted=red["merge_sha"])
        if planted:
            plant = dict(land.plant(writer, cycle_id, drill["path"], drill["content"], art.heads[B.INTEGRATION],
                                    B.CHECK), instance_id=drill["instance_id"])
        planned = cycle.commit(state, "cycle %s" % cycle_id, *args, rows(merged, plant and plant["merge_sha"]),
                               imports, facts, signer, root_row_id)
    except (W.ApiError, W.Refused) + cycle.FAILURES as exc:
        raise land.HardStop("%s: %s" % (type(exc).__name__, cli.cause(exc)), sorted(set(writer.written))) from None
    return {"merge": dict(merged, candidate=merge) if merged else None, "revert": reverted, "plant": plant,
            "state_sha": state.commits_made[-1],
            "root": planned["root"], "rekor_uuid": planned["entry"]["uuid"], "rows": len(planned["row_hashes"]),
            "edited": planned["edited"]}
