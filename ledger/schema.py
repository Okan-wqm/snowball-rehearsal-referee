"""The shapes of the artifacts the stage 0 loop writes on ``brain/state``: ledger rows, root rows, the
``status.md`` block (stage 0, test 14 of asama-0/09, written with MF18).

Rules: tohum/26 (the ledger row; ``derivation``, ``trust``, ``cause`` and ``miss_reason`` closed sets; no float
in a hashed artifact; ``drill`` payload; part -> file), tohum/27a (``chain/root.jsonl`` rows), asama-0/14 row 16
(the block), and the payloads this repository's writers produce, one table (``ROW_TYPES``) for all of them.

**A ledger row** (``row_reasons``) has exactly the keys of tohum/26: ``row_id``, ``ts``, ``part``, ``kind``,
``payload``, ``derivation``, ``trust``, ``snapshot_id``, ``evidence_refs``, ``prev_hash``, ``row_hash``, and
optionally ``cause``, ``miss_reason``, ``derived_from``, ``proposed_by``. ``row_id``, ``kind``, ``snapshot_id``,
``derived_from`` and ``proposed_by`` are non-empty strings; ``ts`` is ``YYYY-MM-DDTHH:MM:SSZ``; ``part`` one of
``PARTS`` (tohum/26's table); ``derivation``, ``trust``, ``cause``, ``miss_reason`` in their closed sets;
``evidence_refs`` a list of ``{path, line_start, line_end}`` with ``1 <= line_start <= line_end``;
``prev_hash`` and ``row_hash`` 64 lowercase hex. No value anywhere in the row is a float.

**Row types.** ``(part, kind)`` must be one of ``ROW_TYPES``; anything else is ``unknown_row_type``: the loop
writes no row whose shape is not written here. Each type gives its payload's keys (required and optional, no
other key), each key's shape, and whether ``cause`` is required (a failed or reverted event, tohum/26; for a
``decision`` only when it is a reject). The words are the seed's vector pages' choices, which tohum/26 does not
list yet (tohum/29m, 29n, 29o: "26'ya girmelidir"): the ``drill`` ``commit`` and ``plant`` payloads and the
``events`` ``revert`` row are ``harness.revert_drill``'s (MF14, 29m; the loop's D7 writes the same revert row,
``ledger.events.revert``); the ``cost`` payload is ``llm.call``'s (MF15,
its ``usd_micros`` the field 29n's brake sums); ``status`` and ``status_edited`` are ``status.block``'s (MF16, 29n);
``genesis`` is 29o's twelve keys; ``sentinel`` is tohum/26f's ``{merge_sha, verdict: green|flaky, red: [], flaky}``
(``red`` always empty: a red ends at its ``revert`` row, 26f), D7's (``ledger.events.sentinel``); ``merge`` (tohum/26d:
``kind: merge``, its payload free; here ``{candidate, path, pull, head_sha, merge_sha, hunk_covered}``,
``target.land``'s answer and asama-0/08's coverage record, ``HUNK_COVERED``: a list, possibly empty, of ``{path,
old_start, old_count, new_start, new_count, covered: "unmeasured", reason: "no_coverage_tool"}``, stage 0's only
values, ``ledger.events.UNMEASURED``; each entry's ``path`` the row's) is
written after the candidate's ``decision`` merge row (``{decision: merge, candidate}``) by ``activate`` and D6
(``ledger.events.decided``); ``pass`` (the PASS row of asama-0/10a, tohum/26d: its ``kind`` free, here ``pass``;
``payload`` 26d's ``stage`` (the integer 0), ``verdict`` ``PASS``, ``import_line_sha256``,
``copy_genesis_row_hash``, ``copy_merge_row_hashes`` (at least one, each once) and optional ``owner_exception``
(``OWNER_EXCEPTION``: (A)'s list of the owner's exceptions), and
this brain's ``conditions`` and ``not_checked``, which 26d allows) is ``harness.pass_row``'s, as is ``copy_gate``
(``{conditions}``, the conditions of the copy's genesis gate judged open on the toy, D6's; this brain's shape,
seed-048); and ``cycle_start``,
``integration_cut``, ``ratchet_base`` and ``decision``
(``payload.decision`` is the field 29n reads) are ``activate``'s (MF18; D6 writes ``cycle_start``, ``ratchet_base``
and ``decision`` with the same builders, ``ledger.events``). Kinds no writer here produces (``rival``,
``accept``, ``freeze``, ``security``, ``looks``, ``founder``) are not in the table, so they are refused until a
writer and its shape are added. The founder row is a session's, not the loop's: its shape and writer are
``ledger.founder``'s, built on ``ROW_FIELDS`` below.

**A root row** (``root_reasons``): exactly ``{row_id, ts, root, rekor_uuid, prev_hash, row_hash}``
(``ledger.anchor.root_row``), ``root`` 64 lowercase hex, ``rekor_uuid`` a non-empty string.

**Files.** ``ledger_reasons`` and ``roots_reasons`` first verify the file as a chain (``ledger.chain``, the one
verifier), then each row. ``status_reasons`` reads ``status.md`` and the ledger: the file has a block
(``status.block.split``, the one reading of the markers) and its sha256 equals ``block_sha256`` of the ledger's last
``status`` row.

Each reason is a string ``<where>: <what>``; an empty list means the artifact conforms. Not checked here: the
meaning of a value (that a hash is the hash of what it names; ``activate`` and the tests check those), and the
JSON Schema files tohum/26 places in the referee repository's ``schemas/`` (not in this repository).
"""

from __future__ import annotations

import hashlib
import re
from typing import Any, Callable

import cli
from dispatcher import llm_call
from ledger import chain
from target import branches

PARTS = ("founder", "events", "cost", "drill", "freeze", "rival", "accept", "security", "looks")
DERIVATIONS = ("tool", "static_analysis", "test_verified", "llm_inference", "name_similarity", "imported")
TRUSTS = ("verified", "observed", "inferred")
CAUSES = ("test_regression", "contract_counterpart", "build_break", "lint_regression", "flaky_dependency",
          "conflict_with_main", "scope_violation", "imported_assumption", "impact_miss", "unknown")
MISS_REASONS = ("map_edge_missing", "unseen_file", "wrong_property", "ref_mismatch", "not_reported", "unknown")
ROOT_KEYS = ("row_id", "ts", "root", "rekor_uuid", "prev_hash", "row_hash")
INTEGRATION = branches.INTEGRATION

TS = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z\Z")
HEX64 = re.compile(r"[0-9a-f]{64}\Z")
HEX40 = re.compile(r"[0-9a-f]{40}\Z")

Check = Callable[[Any, str], "list[str]"]


# ---------------------------------------------------------------- value shapes

def _bad(where: str, what: str) -> list[str]:
    return ["%s: %s" % (where, what)]


def text(value: Any, where: str) -> list[str]:
    return [] if isinstance(value, str) and value else _bad(where, "not a non-empty string")


def hex64(value: Any, where: str) -> list[str]:
    return [] if isinstance(value, str) and HEX64.match(value) else _bad(where, "not 64 lowercase hex")


def hex40(value: Any, where: str) -> list[str]:
    return [] if isinstance(value, str) and HEX40.match(value) else _bad(where, "not 40 lowercase hex")


def timestamp(value: Any, where: str) -> list[str]:
    return [] if isinstance(value, str) and TS.match(value) else _bad(where, "not YYYY-MM-DDTHH:MM:SSZ")


def count(value: Any, where: str) -> list[str]:
    return [] if type(value) is int and value >= 0 else _bad(where, "not an integer >= 0")


def positive(value: Any, where: str) -> list[str]:
    return [] if type(value) is int and value >= 1 else _bad(where, "not an integer >= 1")


def one_of(*allowed: Any) -> Check:
    def check(value: Any, where: str) -> list[str]:
        return [] if isinstance(value, str) and value in allowed else _bad(where, "not one of %s" % "|".join(allowed))
    return check


def nullable(inner: Check) -> Check:
    def check(value: Any, where: str) -> list[str]:
        return [] if value is None else inner(value, where)
    return check


def list_of(inner: Check, non_empty: bool = False, unique_sorted: bool = False, unique: bool = False) -> Check:
    def check(value: Any, where: str) -> list[str]:
        if not isinstance(value, list):
            return _bad(where, "not a list")
        if non_empty and not value:
            return _bad(where, "empty")
        out = [r for i, v in enumerate(value) for r in inner(v, "%s[%d]" % (where, i))]
        if unique_sorted and not out and value != sorted(set(value)):
            out += _bad(where, "not sorted and unique")
        if unique and not out and len(value) != len(set(value)):
            out += _bad(where, "an element repeated")
        return out
    return check


def ordered_by(key: str, inner: Check) -> Check:
    """A list of ``inner`` objects whose ``key`` values do not decrease, compared by code point; ``inner`` is a
    shape that makes ``key`` a string (the order is read only when every element conforms)."""
    def check(value: Any, where: str) -> list[str]:
        out = list_of(inner)(value, where)
        keys = [] if out else [v[key] for v in value]
        return out or (_bad(where, "not in the order of %s" % key) if keys != sorted(keys) else [])
    return check


def exactly(allowed: Any) -> Check:
    """``allowed`` of its own type (``0`` is not ``False``)."""
    def check(value: Any, where: str) -> list[str]:
        return [] if type(value) is type(allowed) and value == allowed else _bad(where, "not %r" % (allowed,))
    return check


def any_value(value: Any, where: str) -> list[str]:
    return []


def empty_list(value: Any, where: str) -> list[str]:
    return [] if value == [] and isinstance(value, list) else _bad(where, "not an empty list")


def map_of(inner: Check) -> Check:
    def check(value: Any, where: str) -> list[str]:
        if not isinstance(value, dict):
            return _bad(where, "not an object")
        return [r for k, v in value.items() for r in text(k, where + " key") + inner(v, "%s.%s" % (where, k))]
    return check


def any_object(value: Any, where: str) -> list[str]:
    return [] if isinstance(value, dict) else _bad(where, "not an object")


def tagged(key: str, shapes: dict[str, Check]) -> Check:
    """An object whose ``key`` names which of ``shapes`` it has."""
    def check(value: Any, where: str) -> list[str]:
        if not isinstance(value, dict):
            return _bad(where, "not an object")
        if value.get(key) not in shapes:
            return _bad("%s.%s" % (where, key), "not one of %s" % "|".join(shapes))
        return shapes[value[key]](value, where)
    return check


def shape(required: dict[str, Check], optional: dict[str, Check] | None = None) -> Check:
    """An object with exactly the ``required`` keys and any of the ``optional`` ones, each of its shape."""
    optional = optional or {}

    def check(value: Any, where: str) -> list[str]:
        if not isinstance(value, dict):
            return _bad(where, "not an object")
        out = []
        for key in sorted(set(required) - set(value)):
            out += _bad("%s.%s" % (where, key), "missing")
        for key in sorted(set(value) - set(required) - set(optional)):
            out += _bad("%s.%s" % (where, key), "not a field of this shape")
        for key, inner in list(required.items()) + list(optional.items()):
            if key in value:
                out += inner(value[key], "%s.%s" % (where, key))
        return out
    return check


def no_float(value: Any, where: str) -> list[str]:
    """tohum/26: no float in a hashed artifact (integers, or fixed decimal strings)."""
    if isinstance(value, float):
        return _bad(where, "a float")
    if isinstance(value, dict):
        return [r for k, v in value.items() for r in no_float(v, "%s.%s" % (where, k))]
    if isinstance(value, list):
        return [r for i, v in enumerate(value) for r in no_float(v, "%s[%d]" % (where, i))]
    return []


# ---------------------------------------------------------------- row types

_EVIDENCE = shape({"path": text, "line_start": positive, "line_end": positive})


def evidence(value: Any, where: str) -> list[str]:
    out = _EVIDENCE(value, where)
    if not out and value["line_start"] > value["line_end"]:
        out = _bad(where, "line_start after line_end")
    return out


GENESIS = shape({  # tohum/29o's twelve keys (activate.genesis)
    "target": text, "base_sha": hex40, "referee_tree_sha256": hex64, "result_sha256": hex64,
    "import_line_sha256": hex64, "seed_epoch": shape({"commit": hex40, "spec_tohum_sha256": hex64,
                                                      "seed_sha256": hex64, "bootstrap_sha256": hex64}),
    "policy_sha256": hex64, "summary_sha256": hex64, "seed_security_ledger_sha256": hex64,
    "seed_security_last_row_hash": hex64, "recipe_sha256": hex64, "facts_sha256": hex64,
})

def _anchor(value: Any, where: str) -> list[str]:
    return text(value, where) or (_bad(where, "starts with #") if value.startswith("#") else [])


# (A)'s ``exit.owner_exception`` (tohum/02 "Sahip istisnası", 26d:45-47): a list in the order of ``anchor``, each
# element the six keys, ``anchor`` without ``#``, ``measured`` false. What no seed page states is not judged: the
# other values' types (the (A) result's as written), which anchors there are, how many elements (an empty list
# conforms), and whether an anchor comes once (equal anchors side by side are in order). The single object of the
# seed before E563 is not a list and does not conform.
OWNER_EXCEPTION = ordered_by("anchor", shape({
    "anchor": _anchor, "stage": any_value, "carry_to": any_value, "reason": any_value, "carry_commitment": any_value,
    "measured": exactly(False)}))

DECISION = tagged("decision", {
    "merge": shape({"decision": one_of("merge"), "candidate": text}),
    "reject": shape({"decision": one_of("reject"), "candidate": text,
                     "reasons": list_of(text, non_empty=True, unique_sorted=True)}),
})


# asama-0/08's coverage record on a merge row (``ledger.events.hunk_covered``): stage 0 writes only unmeasured
HUNK_COVERED = list_of(shape({"path": text, "old_start": count, "old_count": count, "new_start": count,
                              "new_count": count, "covered": one_of("unmeasured"), "reason": one_of("no_coverage_tool")}))
MERGE = shape({"candidate": text, "path": text, "pull": positive, "head_sha": hex40, "merge_sha": hex40,
               "hunk_covered": HUNK_COVERED})


def _hunk_paths(payload: dict, where: str) -> list[str]:
    """Each coverage entry names the merge row's own file (a record of another file is not this merge's)."""
    return [r for i, h in enumerate(payload["hunk_covered"]) if h["path"] != payload["path"]
            for r in _bad("%s.hunk_covered[%d].path" % (where, i), "not the merge's path")]


def _rejected(payload: Any) -> bool:
    return isinstance(payload, dict) and payload.get("decision") == "reject"


# the sentinel verdicts that end a merge's sentinel without a revert (``events``/``sentinel``, tohum/26f)
SENTINEL_ENDS = ("green", "flaky")

# (part, kind) -> (payload shape, cause required: a bool or a test on the payload)
ROW_TYPES: dict[tuple[str, str], tuple[Check, Any]] = {
    ("events", "genesis"): (GENESIS, False),
    ("events", "cycle_start"): (shape({"cycle_id": text}), False),
    ("events", "integration_cut"): (shape({"branch": one_of(INTEGRATION), "base_sha": hex40}), False),
    ("events", "ratchet_base"): (shape({"base_run_sha256": hex64, "counts": map_of(count)}), False),
    ("events", "decision"): (DECISION, _rejected),
    ("events", "revert"): (shape({"merge_sha": hex40}), True),
    ("events", "merge"): (lambda p, where: MERGE(p, where) or _hunk_paths(p, where), False),
    ("events", "sentinel"): (shape({"merge_sha": hex40, "verdict": one_of(*SENTINEL_ENDS), "red": empty_list,
                                    "flaky": list_of(text, unique_sorted=True)}), False),
    ("events", "status"): (shape({"block_sha256": hex64}), False),
    ("events", "status_edited"): (shape({"found_sha256": nullable(hex64), "recorded_sha256": nullable(hex64)}),
                                  False),
    ("cost", "cost"): (shape({"tool": one_of("llm.call"), "template_sha256": hex64, "model_requested": text,
                              "models_served": list_of(text), "outcome": one_of(*llm_call.OUTCOMES),
                              "reason": nullable(text), "usd_micros": count, "cost_source": text,
                              "cap_usd_micros": count, "prompt_sha256": hex64, "duration_ms": count}), False),
    ("events", "pass"): (shape({"stage": exactly(0), "verdict": one_of("PASS"), "import_line_sha256": hex64,
                                "copy_genesis_row_hash": hex64,
                                "copy_merge_row_hashes": list_of(hex64, non_empty=True, unique=True),
                                "conditions": list_of(text, unique_sorted=True),
                                "not_checked": list_of(text, unique_sorted=True)},
                               {"owner_exception": OWNER_EXCEPTION}), False),
    ("events", "copy_gate"): (shape({"conditions": list_of(text, non_empty=True, unique_sorted=True)}), False),
    ("drill", "commit"): (shape({"drill": one_of("revert"), "family": one_of("revert"), "commitment_sha256": hex64}),
                          False),
    ("drill", "plant"): (shape({"drill": one_of("revert"), "family": one_of("revert"), "instance_id": text,
                                "merge_sha": hex40}), False),
}

# tohum/26's row fields, one source for ROW and for a part with extra optional fields (the founder row's supersedes)
ROW_FIELDS: dict[str, Check] = {
    "row_id": text, "ts": timestamp, "part": one_of(*PARTS), "kind": text, "payload": any_object,
    "derivation": one_of(*DERIVATIONS), "trust": one_of(*TRUSTS), "snapshot_id": text,
    "evidence_refs": list_of(evidence), "prev_hash": hex64, "row_hash": hex64}
ROW_OPTIONAL_FIELDS: dict[str, Check] = {
    "cause": one_of(*CAUSES), "miss_reason": one_of(*MISS_REASONS), "derived_from": text, "proposed_by": text}
ROW = shape(ROW_FIELDS, ROW_OPTIONAL_FIELDS)

ROOT = shape({"row_id": text, "ts": timestamp, "root": hex64, "rekor_uuid": text, "prev_hash": hex64, "row_hash": hex64})


def row_reasons(row: Any, where: str = "row") -> list[str]:
    """Why ``row`` (a stored ledger row) does not conform; see the module docstring."""
    out = ROW(row, where)
    if not isinstance(row, dict):
        return out
    out += no_float(row, where)
    typ = ROW_TYPES.get((row.get("part"), row.get("kind")))
    if typ is None:
        return out + _bad(where, "unknown_row_type %s/%s" % (row.get("part"), row.get("kind")))
    payload_shape, cause_required = typ
    out += payload_shape(row.get("payload"), where + ".payload")
    if callable(cause_required):
        cause_required = cause_required(row.get("payload"))
    if cause_required and "cause" not in row:
        out += _bad(where + ".cause", "missing (a failed or reverted event)")
    return out


def payload_reasons(part: str, kind: str, payload: Any) -> list[str]:
    """The payload check alone, for a writer that checks before it chains its row."""
    typ = ROW_TYPES.get((part, kind))
    if typ is None:
        return _bad("row", "unknown_row_type %s/%s" % (part, kind))
    return typ[0](payload, "payload") + no_float(payload, "payload")


def root_reasons(row: Any, where: str = "root") -> list[str]:
    return ROOT(row, where) + (no_float(row, where) if isinstance(row, dict) else [])


def _rows(data: bytes, where: str) -> tuple[list[dict], list[str]]:
    verdict = chain.verify_bytes(data)
    if not verdict["valid"]:
        return [], _bad(where, "not a valid chain: %s (line %s)" % (verdict["reason"], verdict["line"]))
    return [chain.parse_row(line.decode("utf-8")) for line in chain._lines(data)], []


def ledger_reasons(data: bytes) -> list[str]:
    rows, out = _rows(data, "ledger")
    for i, row in enumerate(rows, 1):
        out += row_reasons(row, "ledger line %d" % i)
    return out


def roots_reasons(data: bytes) -> list[str]:
    rows, out = _rows(data, "roots")
    for i, row in enumerate(rows, 1):
        out += root_reasons(row, "roots line %d" % i)
    return out


def status_reasons(status: bytes, ledger: bytes) -> list[str]:
    from status import block  # the block's markers and its bytes, one source

    rows, out = _rows(ledger, "ledger")
    try:
        parts = block.split(status)
    except block.Unusable as exc:
        return out + _bad("status.md", cli.cause(exc))
    if parts is None:
        return out + _bad("status.md", "has no block")
    recorded = [r["payload"].get("block_sha256") for r in rows
                if r.get("part") == block.PART and r.get("kind") == block.KIND and isinstance(r.get("payload"), dict)]
    if not recorded:
        out += _bad("status.md", "the ledger has no status row")
    elif hashlib.sha256(parts[1]).hexdigest() != recorded[-1]:
        out += _bad("status.md", "block sha256 is not the last status row's block_sha256")
    return out
