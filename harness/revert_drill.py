"""``exit.drill``, revert family only: a bad merge from the seed's catalog is planted, reverted, and judged
against the answer key committed before the run (stage 0, MF14).

Rules: tohum/29m (``revert_drill``: commands, selection, key, rows, the judge's order and its reasons), asama-0/14
row 14, asama-0/09 test 50, asama-0/01 step D8 (the previous cycle's ``yaz`` commits, this cycle runs), tohum/22a
``#geri-alma``, tohum/29c (commitment = ``sha256(canonical(key))``).

**Inputs.** The catalog is ``{instances: [{id, cause, ...}]}``: a non-empty list, ``id`` a non-empty string unique
in the list, ``cause`` a string; no other field is read (``Unusable`` otherwise). The seed file is ``{seed:
string}``, non-empty (an empty HMAC key is no secret; this module's choice), other keys not read; in production it
is the referee's secret. ``cycle_id`` is the Actions run id of the cycle that writes the commitment: a string of
ASCII decimal digits.

**The key** (``key``): ``selection = HMAC-SHA256(key = the seed's UTF-8 bytes, message = cycle_id's UTF-8
bytes)``, 64 lowercase hex; the instance is the ``int(selection, 16) mod N``-th of the catalog sorted by ``id`` in
code point order (the file's order does not matter). The key is exactly ``{cycle_id, selection, instance_id,
cause}``; the commitment (``commitment``) is the sha256 of its RFC 8785 bytes (``ledger.chain.canonical``). The
secret ``selection`` is inside the key, so the public commitment cannot be found by trying each instance.

**Rows** (tohum/29m; the words are its choice): the commitment ``part: drill, kind: commit, payload {drill:
revert, family: revert, commitment_sha256}`` (``commit_payload``, written by cycle N's ``yaz``; the key itself is
never written or printed before the run); the plant ``part: drill, kind: plant, payload {drill: revert, family:
revert, instance_id, merge_sha}``; the revert ``part: events, kind: revert``, the row's top-level ``cause``,
``payload {merge_sha}``. No row carries a cycle id: "the previous cycle" is chain order only.

**The judge** (``judge``) reads a ledger file and a key; it takes no seed and does not derive the selection again:

1. the file is not a valid chain (``ledger.chain.verify_bytes``; a line that is not a JSON object breaks it):
   ``chain_broken`` alone;
2. P = the last row ``part: drill, kind: plant`` with ``payload.drill == "revert"``; none: ``not_planted`` alone;
3. C = the last row ``part: drill, kind: commit`` with ``payload.drill == "revert"`` before P in file order; none:
   ``commitment_not_before_run`` (no key comparison); else ``commitment_mismatch`` when
   ``commitment(key) != C.payload.commitment_sha256``;
4. ``instance_mismatch`` when ``P.payload.instance_id`` is not the key's ``instance_id``;
5. R = the first row after P with ``part: events, kind: revert`` and ``payload.merge_sha`` equal to P's; none:
   ``not_reverted``, else ``cause_mismatch`` when R's ``cause`` is not the key's.

Every reason of (3)-(5) is written, sorted, each once; ``PASS`` iff there is none. Earlier drills in the file are
history (only P, the C before it and the R after it are read). The judge trusts the file it is given to be the
verified ledger: it takes no seed, so a ledger chained anew around an edited key passes it; such a file is not an
append-only extension of the previous verified version (``ledger.chain.verify_bytes(new, previous)``, which
``ledger.append`` and ``run_drill`` require), and that check, not the judge, is what refuses it.

**The run** (``run_drill``), the cycle after the commitment: the ledger read must be a valid chain extending
``previous`` (else ``HardStop``, ``ledger.append``'s); its last revert-drill row must be a ``commit`` equal to
``commitment(key)`` for the given ``cycle_id`` (else ``NoCommitment``: nothing is planted, nothing written). Then
the instance's ``files`` are committed on ``brain/drill/<cycle_id>`` from ``onto``'s head, a pull request opened,
a check posted saying the merge is planted and is not a gate decision, the pull request merged (``target.land.pull_merge``,
the sequence the loop's D8 plants with);
``observe(merge)`` gives ``(runs, facts)`` and ``gate.revert.revert_red`` decides and reverts onto
``brain/drill/<cycle_id>-revert`` (calls 12 -> 13 -> 14). It returns the key and the plant and revert payloads (the
revert's ``cause`` beside it) for that cycle's ``ledger.append``; the verdict is ``judge`` over the appended ledger.

Out of scope, stated: where the planted files come from (the catalog's other fields, e.g. a patch name, are the
seed's fixtures and are not read here; ``run_drill`` takes ``files`` per instance id), merging the revert's pull
request (the gate's), writing the rows (``ledger.append``), the other drill families (tohum/22a, stage 2).

Command line, run from ``referee/``, one JSON line on stdout, the cause of an error on stderr::

    python -m harness.revert_drill commit CATALOG SEED   stdin {"cycle_id"}  -> {commitment_sha256}
    python -m harness.revert_drill reveal CATALOG SEED   stdin {"cycle_id"}  -> {key, revealed_sha256}
    python -m harness.revert_drill judge LEDGER KEY                          -> {verdict, reasons}

    commit, reveal: exit 0; 2 an unreadable or malformed catalog, seed or stdin ({"commitment_sha256": null},
    {"key": null, "revealed_sha256": null}). judge: exit 0 PASS, 1 FAIL, 2 an unreadable file or a key that is
    not exactly four string fields ({"verdict": "FAIL"}).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import sys
from typing import Any, Callable

from gate import revert
from ledger import append, chain
from target import land, write
import cli

DRILL = "revert"
KEY = ("cycle_id", "selection", "instance_id", "cause")
REASONS = ("cause_mismatch", "commitment_mismatch", "commitment_not_before_run", "instance_mismatch",
           "not_reverted")
CYCLE = re.compile(r"[0-9]+\Z")
HardStop = append.HardStop  # one hard stop for a ledger that is not a valid chain extending the previous one


class Unusable(ValueError):
    pass


class NoCommitment(Exception):
    """The ledger's last revert-drill row is not this key's commitment: the drill does not run."""


# ---------------------------------------------------------------- inputs

def instances(catalog: Any) -> list[dict]:
    """The catalog's instances sorted by id (code point order); ``Unusable`` unless the shape above."""
    items = catalog.get("instances") if isinstance(catalog, dict) else None
    if not isinstance(items, list) or not items:
        raise Unusable("the catalog must be {instances: [...]} with at least one instance")
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str) or item["id"] == "":
            raise Unusable("an instance's id must be a non-empty string")
        if not isinstance(item.get("cause"), str):
            raise Unusable("instance %r: cause must be a string" % item["id"])
        if item["id"] in seen:
            raise Unusable("instance id %r is repeated" % item["id"])
        seen.add(item["id"])
    return sorted(items, key=lambda item: item["id"])


def seed_bytes(seed: Any) -> bytes:
    if not isinstance(seed, dict) or not isinstance(seed.get("seed"), str) or seed["seed"] == "":
        raise Unusable("the seed file must be {seed: non-empty string}")
    return seed["seed"].encode("utf-8")


def cycle(value: Any) -> str:
    if not isinstance(value, str) or not CYCLE.match(value):
        raise Unusable("cycle_id must be a string of decimal digits")
    return value


# ---------------------------------------------------------------- key and commitment

def selection(seed: bytes, cycle_id: str) -> str:
    return hmac.new(seed, cycle(cycle_id).encode("utf-8"), hashlib.sha256).hexdigest()


def key(seed: Any, cycle_id: str, catalog: Any) -> dict:
    """The answer key for ``cycle_id`` from the seed file's and the catalog's objects."""
    items = instances(catalog)
    chosen = selection(seed_bytes(seed), cycle_id)
    item = items[int(chosen, 16) % len(items)]
    return {"cycle_id": cycle_id, "selection": chosen, "instance_id": item["id"], "cause": item["cause"]}


def commitment(answer: dict) -> str:
    return hashlib.sha256(chain.canonical(answer)).hexdigest()


def key_shape(answer: Any) -> dict:
    if not isinstance(answer, dict) or set(answer) != set(KEY) or not all(isinstance(answer[k], str) for k in KEY):
        raise Unusable("the key must be exactly {%s}, each a string" % ", ".join(KEY))
    return answer


# ---------------------------------------------------------------- rows

def commit_payload(answer: dict) -> dict:
    """The commitment row's payload (``part: drill, kind: commit``): the hash only, never the key."""
    return {"drill": DRILL, "family": DRILL, "commitment_sha256": commitment(answer)}


def plant_payload(instance_id: str, merge_sha: str) -> dict:
    return {"drill": DRILL, "family": DRILL, "instance_id": instance_id, "merge_sha": merge_sha}


def revert_payload(merge_sha: str) -> dict:
    """``part: events, kind: revert``; the row's top-level ``cause`` is the revert's."""
    return {"merge_sha": merge_sha}


def _is(row: dict, part: str, kind: str) -> bool:
    return row.get("part") == part and row.get("kind") == kind and isinstance(row.get("payload"), dict)


def is_drill(row: dict, kind: str) -> bool:
    return _is(row, "drill", kind) and row["payload"].get("drill") == DRILL


def chain_rows(ledger: bytes) -> list[dict] | None:
    """The rows of a valid chain, or None (``ledger.chain``, the one verifier)."""
    if not chain.verify_bytes(ledger)["valid"]:
        return None
    return [chain.parse_row(line.decode("utf-8")) for line in chain._lines(ledger)]


# ---------------------------------------------------------------- judge

def judge(ledger: bytes, answer: Any) -> dict:
    """``{verdict: PASS|FAIL, reasons}`` (see the module docstring)."""
    answer = key_shape(answer)
    rows = chain_rows(ledger)
    if rows is None:
        return {"verdict": "FAIL", "reasons": ["chain_broken"]}
    plants = [i for i, row in enumerate(rows) if is_drill(row, "plant")]
    if not plants:
        return {"verdict": "FAIL", "reasons": ["not_planted"]}
    p = plants[-1]
    plant = rows[p]["payload"]
    found = set()
    commits = [row for row in rows[:p] if is_drill(row, "commit")]
    if not commits:
        found.add("commitment_not_before_run")
    elif commits[-1]["payload"].get("commitment_sha256") != commitment(answer):
        found.add("commitment_mismatch")
    if plant.get("instance_id") != answer["instance_id"]:
        found.add("instance_mismatch")
    reverts = [row for row in rows[p + 1:]
               if _is(row, "events", "revert") and row["payload"].get("merge_sha") == plant.get("merge_sha")]
    if not reverts:
        found.add("not_reverted")
    elif reverts[0].get("cause") != answer["cause"]:
        found.add("cause_mismatch")
    reasons = [r for r in REASONS if r in found]
    return {"verdict": "FAIL" if reasons else "PASS", "reasons": reasons}


# ---------------------------------------------------------------- the run

def run_drill(writer: Any, seed: Any, catalog: Any, cycle_id: str, files: Any, ledger: bytes, previous: bytes,
              observe: Callable[[str], tuple], onto: str, check_name: str) -> dict:
    """One revert drill for the commitment cycle ``cycle_id`` wrote (see the module docstring). Returns ``{key,
    plant, revert, cause, reverted}``: ``plant`` and ``revert`` are payloads (``revert`` null when the watch did not
    revert), ``cause`` the revert row's. ``HardStop``, ``NoCommitment`` and ``Unusable`` are raised before anything
    is written."""
    answer = key(seed, cycle_id, catalog)
    planted = files.get(answer["instance_id"]) if isinstance(files, dict) else None
    if not isinstance(planted, dict) or not planted or not all(
            write.file_path(p) and isinstance(t, str) for p, t in planted.items()):
        raise Unusable("instance %r: files must be a non-empty {path: text}" % answer["instance_id"])
    verdict = chain.verify_bytes(ledger, previous)
    if not verdict["valid"]:
        raise HardStop("ledger: %s (%s)" % (verdict["reason"], verdict["broken_row"]))
    drills = [row for row in chain_rows(ledger) if is_drill(row, "commit") or is_drill(row, "plant")]
    if not drills or drills[-1]["kind"] != "commit" or drills[-1]["payload"] != commit_payload(answer):
        raise NoCommitment("the ledger's last revert-drill row is not cycle %s's commitment" % cycle_id)
    branch = land.DRILL_PREFIX + cycle_id
    merge = land.pull_merge(writer, branch, writer.head(onto), {p: t.encode("utf-8") for p, t in planted.items()},
                            onto, land.planted_title(cycle_id), land.PLANTED_BODY, check_name,
                            land.planted_summary(cycle_id))["merge_sha"]
    runs, facts = observe(merge)
    done = revert.revert_red(writer, runs, facts, merge, onto, branch + "-revert")
    return {"key": answer, "plant": plant_payload(answer["instance_id"], merge), "reverted": done["reverted"],
            "revert": revert_payload(merge) if done["reverted"] else None, "cause": done["cause"]}


# ---------------------------------------------------------------- command line

USAGE = ("usage: python -m harness.revert_drill commit|reveal CATALOG SEED < {\"cycle_id\"} | "
         "python -m harness.revert_drill judge LEDGER KEY")
EMPTY = {"commit": {"commitment_sha256": None}, "reveal": {"key": None, "revealed_sha256": None},
         "judge": {"verdict": "FAIL"}}


def _read(path: str) -> bytes:
    try:
        with open(path, "rb") as handle:
            return handle.read()
    except OSError as exc:
        raise Unusable("%s: %s" % (path, cli.cause(exc))) from None


def _json(data: bytes) -> dict:
    return chain.parse_row(data.decode("utf-8"))


def _emit(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj, sort_keys=True) + "\n")


def main(argv: list[str]) -> int:
    command = argv[0] if len(argv) == 3 and argv[0] in EMPTY else None
    try:
        if command is None:
            raise Unusable(USAGE)
        if command == "judge":
            ledger = _read(argv[1])
            result = judge(ledger, _json(_read(argv[2])))
            _emit(result)
            return 0 if result["verdict"] == "PASS" else 1
        catalog, seed = _json(_read(argv[1])), _json(_read(argv[2]))
        request = _json(sys.stdin.buffer.read())
        if set(request) != {"cycle_id"}:
            raise Unusable('stdin must be {"cycle_id"} and nothing else')
        answer = key(seed, cycle(request["cycle_id"]), catalog)
        _emit({"commitment_sha256": commitment(answer)} if command == "commit"
              else {"key": answer, "revealed_sha256": commitment(answer)})
        return 0
    except (Unusable, UnicodeDecodeError, chain.ChainError) as exc:
        sys.stderr.write("unusable input: %s\n" % cli.cause(exc))
    _emit(EMPTY.get(command, {"verdict": "FAIL"}))
    return 2


def FAULT_LINE(argv: list[str]) -> dict:  # noqa: N802 - cli.run's fault line, by command
    return EMPTY.get(argv[0] if len(argv) == 3 else None, {"verdict": "FAIL"})


if __name__ == "__main__":
    sys.exit(cli.run(main, sys.argv[1:], FAULT_LINE))
