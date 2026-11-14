"""``çağır``'s D4: stage 0's one runtime model call, the canary, from the ``pulled`` artifact to ``response``
(stage 0).

Rules: asama-0/01 D4 (``çağır``: the provider identity, runs no code; a typed request in, the response, the served
model and the cost out; MF15; its green column: only (B)'s canary call), asama-0/12 (the canary's brake is
``policy.json`` ``stage_budgets.asama_0.canary_usd``, and ``--max-budget-usd`` per call; at the brake no call is made
and the cycle falls closed), asama-0/10a ``#model`` (the served model is the requested one, ``--max-budget-usd``
applied, the ``cost`` row written, a prompt with a secret pattern not sent), tohum/24 ("Araçsız çağrı": the
referee's ``llm.call`` builds the prompt from typed input), tohum/29m (``llm.call``'s rules, MF15's own).

**The call** (``d4``): ``dispatcher.llm_call.call`` with

- the template ``CANARY`` (the referee's own constant: nothing the Founder writes into ``pulled`` chooses its text)
  and the typed input ``{target: <the targets[] entry's id>}``;
- the stage cap and the call cap both ``canary_usd`` of the artifact's ``policy.json`` in micro-USD
  (``llm_call.policy_usd``): asama-0/12 gives the canary one budget, so a call may spend what the stage leaves of
  it and no more;
- the spend: a ``llm_call.CostBook`` on ``state/ledger.jsonl`` of ``pulled`` (``brain/state``'s ledger at the head D1
  verified, ``verify --previous`` and the root included), verified again here as a chain; the append-only check
  against its previous version is D1's, so the book gets no previous version;
- the cost row's ``row_id`` ``cagir-<run id>-<run attempt>`` (one per run of the job: a rerun is another attempt),
  its ``ts`` the clock's time as the job starts the call (taken before it), its ``snapshot_id`` ``brain/integration``'s head from ``state/heads.json``.

**The response** (``response.json`` in the output directory, which must not exist): ``{schema:
"snowball-response/1", target, heads, outcome, reason, sent, run_valid, output, models_served, cost_usd_micros,
prompt_sha256, dropped, rows}``, ``rows`` the book's rows of this call (one ``cost`` row when a process was started,
none for ``secret`` and ``brake``): D6's ``ledger.append`` input. The response is written for every outcome, so
the cost of a started process reaches the ledger whatever it was; whether the canary held is its ``outcome`` (``ok``
only when the served model is the requested one and the answer has the output's type, ``llm_call.classify``), not
whether the job ended green. The answer itself is recorded, not judged: the canary checks the call's path (model,
cap, cost, scan), not the model's reply.

**Reading it back** (``read_response``, D6 of ``yaz``; every reason that holds is listed, ``ResponseError``): the
directory holds exactly ``response.json`` (``unlisted:<name>`` for anything else), a regular file with no symbolic
link on its way (``response_missing``) holding one JSON object with exactly the keys above
(``response_unreadable``); ``schema`` is ``SCHEMA`` (``schema_unknown``); ``target`` is the id of ``pulled``'s
``targets[]`` entry (``target_mismatch``) and ``heads`` ``pulled``'s heads (``heads_mismatch``): the response is this
cycle's; ``rows`` is a list of objects (``rows_invalid``). Their shape is ``ledger.schema``'s, checked with the
whole new ledger by ``ledger.cycle`` before anything is signed.

The ``claude`` CLI, its sha512 pin and the model are the caller's arguments: in a run, ``loop.job``'s ``cagir`` gives
the CLI the ``claude`` step installs, the sha512 of that file when the job read it and ``bootstrap.json``'s
``rival.model`` (``loop.inputs``, tohum/29s).

Out of scope, stated: the CLI's real output shapes (asama-0/10a ``#model``).
"""

from __future__ import annotations

import json
import os
from typing import Any

import cli
from dispatcher import llm_call as L
from loop import pulled as P
from profile import derive as D
from target import branches as B

SCHEMA = "snowball-response/1"
RESPONSE = "response.json"
CANARY_USD = ("stage_budgets", "asama_0", "canary_usd")
CANARY = {
    "fields": {"target": "string"},
    "text": "This is the canary call of the Snowball loop for the target {{target}}. Reply only with the structured "
            "output: echo is the target's name as given, without quotes.",
    "output": {"echo": "string"},
}
TIMEOUT_S = 300.0
CALL_KEYS = ("outcome", "reason", "sent", "run_valid", "output", "models_served", "cost_usd_micros", "prompt_sha256",
             "dropped")  # the call's answer, as llm_call.call gives it
KEYS = ("schema", "target", "heads", "rows") + CALL_KEYS


class ResponseError(ValueError):
    """The directory is not this cycle's ``response``; ``reasons`` lists why."""

    def __init__(self, reasons: list[str]) -> None:
        super().__init__(", ".join(reasons))
        self.reasons = reasons


def d4(art: P.Pulled, out: str, *, claude: str, claude_sha512: str, model: str, token: str, row_id: str,
       ts: str) -> dict[str, Any]:
    """One canary call (see the module docstring); writes ``out/response.json`` and returns its summary
    ``{outcome, reason, sent, models_served, cost_usd_micros}``. ``llm_call.Unusable`` (the policy's
    ``canary_usd``, the pin, the request) and ``ledger.append.HardStop`` (a ledger that is not a chain) leave
    nothing written."""
    if os.path.lexists(out):
        raise L.Unusable("%s exists" % out)
    cap = L.policy_usd(art.policy_bytes, *CANARY_USD)
    book = L.CostBook(art.state[B.STATE_LEDGER], None)
    got = L.call(CANARY, {"target": art.target["id"]}, claude=claude, claude_sha512=claude_sha512, model=model,
                 stage_cap_micros=cap, call_cap_micros=cap, book=book, token=token, timeout_s=TIMEOUT_S,
                 row_id=row_id, ts=ts, snapshot_id=art.heads[B.INTEGRATION])
    response = {"schema": SCHEMA, "target": art.target["id"], "heads": art.heads, "rows": book.rows,
                **{k: got[k] for k in CALL_KEYS}}
    os.makedirs(out)
    with open(os.path.join(out, RESPONSE), "x", encoding="utf-8") as fh:
        fh.write(json.dumps(response, sort_keys=True) + "\n")
    return {k: got[k] for k in ("outcome", "reason", "sent", "models_served", "cost_usd_micros")}


def read_response(root: str, art: P.Pulled) -> list[dict]:
    """``response``'s cost rows, the directory checked against ``art`` (see the module docstring)."""
    names = sorted(os.listdir(root)) if os.path.isdir(root) and not os.path.islink(root) else []
    reasons = ["unlisted:%s" % n for n in names if n != RESPONSE]
    raw = D._read_regular(root, RESPONSE) if names else None
    if raw is None:
        raise ResponseError(reasons + ["response_missing"])
    try:
        doc = cli.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, RecursionError):
        doc = None
    if not (isinstance(doc, dict) and sorted(doc) == sorted(KEYS)):
        raise ResponseError(reasons + ["response_unreadable"])
    if doc["schema"] != SCHEMA:
        reasons.append("schema_unknown")
    if doc["target"] != art.target["id"]:
        reasons.append("target_mismatch")
    if doc["heads"] != art.heads:
        reasons.append("heads_mismatch")
    if not (isinstance(doc["rows"], list) and all(isinstance(r, dict) for r in doc["rows"])):
        reasons.append("rows_invalid")
    if reasons:
        raise ResponseError(reasons)
    return doc["rows"]
