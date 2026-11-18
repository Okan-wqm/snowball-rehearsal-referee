"""``yaz``'s D8: the revert drill in the loop, one step per cycle (stage 0, MF14 in the cycle).

Rules: asama-0/01 D8 (the previous cycle's ``yaz`` commits, this cycle applies; inputs the seed's drill fixtures and
the drill seed, a referee secret; output ``drill`` rows; judge: the reveal equals the commitment, the planted merge
was reverted, ``cause`` equals the key's), tohum/22a ``#geri-alma`` (the planted bad merge is seen red by the
sentinel and reverted by ``gate.revert``), tohum/29m (``harness.revert_drill``: the key, the commitment, the rows and
the judge, used here as they are), tohum/08 item 1 (the seed is a secret, so only a job that runs no code holds it:
``yaz``), tohum/07 (merges are serial: a planted merge is a merge, ``ledger.serial``).

**Inputs** (tohum/26f "D8'in canli girdileri", "Canli prova fikstürleri"; seed-045, answered by seed epoch e884cbb):
two secrets of ``yaz``'s step, named here and in ``loop.yml`` (``loop.job``): the drill seed ``DRILL_SEED`` and the
live drill fixtures ``DRILL_FIXTURES``. ``inputs(environ, imports)`` with ``imports`` the checkout's
``setup/imports.jsonl`` bytes:

1. ``DRILL_SEED`` unset or empty: ``None`` (the drill is off for the run: the operator has not given the secret);
2. ``DRILL_FIXTURES`` unset or empty: ``{off: fixtures_absent}`` (the seed alone turns nothing on and stops nothing);
3. the fixtures' value is one line of base64 (RFC 4648 alphabet, padded; ``base64.b64decode(validate=True)``: an
   LF, a blank or any other byte is refused) whose
   bytes are UTF-8 RFC 8785 JSON (the bytes equal ``ledger.chain.canonical`` of what they parse to) of exactly
   ``{import_line_sha256, instances}``: ``import_line_sha256`` 64 lowercase hex; ``instances`` a non-empty list of
   exactly ``{id, cause, patch}``, ``id`` 32 lowercase hex and unique, ``cause`` one of ``CAUSES``, ``patch`` a
   non-empty string; every cause of ``CAUSES`` has the same number of instances, at least one. Any other value is
   ``Unusable`` (exit 2 before any write); its message names the rule broken and never a value of the secret;
4. ``import_line_sha256`` is not the sha256 of the counter's last transfer line without its LF
   (``loop.accepted.last_import``, the one reader; a counter it refuses is ``Unusable``): ``{off:
   fixtures_import_mismatch}`` (26f: the drill is off and the reason named; each import gets a new set);
5. else ``{seed: {seed}, catalog: {instances: [{id, cause}]}, patches: {id: patch}}``, the catalog in
   ``harness.revert_drill``'s form (it reads ``id`` and ``cause`` only) and each patch a unified diff of one file
   (``target.land.applied``'s, the one application a candidate's diff gets).

Not checked here, stated: the rules 26f gives the producer (``drill-fixtures``: each patch gives exactly its cause
on the toy's tree, touches no file a candidate expected to merge touches, no security path, the 48 KB cap); a patch
that does not apply to ``brain/integration``'s head is the step's ``patch_does_not_apply`` below.

**Stated assumptions** (26f leaves MF17's composition to the Founder): the commitment's ``cycle_id`` is the
Actions run id of the cycle that writes it (29m: decimal digits), recovered by a later cycle from the
``events``/``cycle_start`` row of the commitment's cycle (its ``<run id>-<attempt>``); the drill is committed in cycle
N's ``yaz``, planted in a later cycle's ``yaz`` (with that cycle's ``ratchet_base``, so the revert has a lint before),
watched by the next cycle's ``kos`` and reverted by its ``yaz`` (D7, like any merge), and the key revealed and judged
by the first ``yaz`` after the planted merge is finished.

**The step** (``step``), from ``brain/state``'s ledger as D1 verified it, its unfinished merges
(``ledger.serial.unfinished``), whether D5 merges a candidate this cycle, the tree of ``brain/integration``'s head and
this run's id. Let D be the ledger's revert-drill ``commit`` and ``plant`` rows (``harness.revert_drill``'s reading):

1. no inputs: ``{action: off}``; inputs ``{off: why}``: ``{action: off, why}`` (``yaz``'s line shows it);
2. D's last row is a commitment C. Its cycle's run id is read (``commitment_unplaced`` when no ``cycle_start`` with a
   ``<digits>-<digits>`` id precedes it) and its key derived; a key whose commitment is not C's (the seed or the
   catalog changed since) abandons C: this cycle commits again (rule 4, ``replaces: commitment_mismatch``). Else, with
   an unfinished merge or a candidate D5 merges, ``{action: wait, why: merge_unfinished|candidate_merges}`` (one merge
   at a time, the candidate first). Else the key's instance's patch is applied to the tree: a patch that no longer
   applies abandons C (rule 4, ``replaces: patch_does_not_apply``); one that applies is ``{action: plant,
   instance_id, path, content}``, which D6 lands (``target.land.plant``) with the ``ratchet_base`` and ``plant`` rows;
3. D's last row is a plant P whose merge is unfinished: ``{action: wait, why: drill_unfinished}`` (D7 watches it);
4. otherwise (no drill yet, or P finished, or C abandoned): when P exists and C is kept, ``judged`` is P's drill
   revealed: ``{key, verdict, reasons}`` of ``harness.revert_drill.judge`` over the ledger with the key of the
   commitment before P (a red the loop reverted with the key's cause is ``PASS``; a merge ended green, or reverted
   with another cause, is ``FAIL``). Then a new commitment is written for this run's id when every instance's patch
   applies to the tree (``{action: commit, payload}``), else ``{action: none, why: patch_does_not_apply, instances}``
   (the catalog does not fit this target's head: nothing is committed that could not be planted).

The key and the instance are never in the step's answer before the plant (``commit`` carries the hash only); the
plant names its instance (29m's plant row does), and the key is in the answer only once judged.

Out of scope, stated: how often a drill runs (one after another, as the ledger allows: this brain's choice); a
row for the verdict (29m gives commit and plant rows only; the verdict is in ``yaz``'s line); a candidate that keeps
merging every other cycle delays the plant (the candidate goes first).
"""

from __future__ import annotations

import base64
import hashlib
import re
from typing import Any

from harness import revert_drill as RD
from ledger import chain
from loop import accepted as AC
from target import land
import cli

SEED_ENV = "DRILL_SEED"
FIXTURES_ENV = "DRILL_FIXTURES"
CAUSES = ("test_regression", "build_break", "lint_regression")  # tohum/26f: a fixture's cause, each shown equally
FIXTURE_KEYS = ("import_line_sha256", "instances")
INSTANCE_KEYS = ("cause", "id", "patch")
HEX32 = re.compile(r"[0-9a-f]{32}\Z")
CYCLE_ID = re.compile(r"([0-9]+)-[0-9]+\Z")


class Unusable(ValueError):
    pass


def inputs(environ: dict[str, str], imports: bytes) -> dict | None:
    """``None``, ``{off}`` or ``{seed, catalog, patches}`` (see the module docstring)."""
    seed = environ.get(SEED_ENV)
    if not seed:
        return None
    value = environ.get(FIXTURES_ENV)
    if not value:
        return {"off": "fixtures_absent"}
    doc = fixtures(value)
    try:
        _, line = AC.last_import(imports)
    except AC.StateError as exc:
        raise Unusable("drill: imports: %s" % exc.reasons[0]) from None
    if doc["import_line_sha256"] != hashlib.sha256(line).hexdigest():
        return {"off": "fixtures_import_mismatch"}
    return {"seed": {"seed": seed},
            "catalog": {"instances": [{"id": i["id"], "cause": i["cause"]} for i in doc["instances"]]},
            "patches": {i["id"]: i["patch"] for i in doc["instances"]}}


def fixtures(value: str) -> dict:
    """The fixtures secret's value decoded and checked (rule 3 of the module docstring), else ``Unusable``."""
    try:
        data = base64.b64decode(value, validate=True)  # any byte outside the alphabet or its padding is an error
    except ValueError:  # binascii.Error, and a str that is not ASCII
        raise Unusable("drill: %s is not one line of padded base64" % FIXTURES_ENV) from None
    try:
        doc = chain.parse_row(data.decode("utf-8"))
        canonical = chain.canonical(doc) == data
    except (UnicodeDecodeError, chain.ChainError):
        raise Unusable("drill: %s is not a JSON object in base64" % FIXTURES_ENV) from None
    if not canonical:
        raise Unusable("drill: %s is not RFC 8785 JSON" % FIXTURES_ENV)
    if sorted(doc) != sorted(FIXTURE_KEYS) or not isinstance(doc["import_line_sha256"], str) \
            or not chain.HEX64.match(doc["import_line_sha256"]):
        raise Unusable("drill: %s is not {import_line_sha256, instances}" % FIXTURES_ENV)
    items = doc["instances"]
    if not isinstance(items, list) or not items:
        raise Unusable("drill: %s's instances is not a non-empty list" % FIXTURES_ENV)
    for n, item in enumerate(items):
        if not (isinstance(item, dict) and sorted(item) == list(INSTANCE_KEYS) and isinstance(item["id"], str)
                and HEX32.match(item["id"]) and item["cause"] in CAUSES and isinstance(item["patch"], str)
                and item["patch"]):
            raise Unusable("drill: %s's instance %d is not {id: 32 hex, cause, patch}" % (FIXTURES_ENV, n))
    if len({item["id"] for item in items}) != len(items):
        raise Unusable("drill: %s repeats an instance id" % FIXTURES_ENV)
    counts = {c: sum(item["cause"] == c for item in items) for c in CAUSES}
    if len(set(counts.values())) != 1 or not counts[CAUSES[0]]:
        raise Unusable("drill: %s's causes are not each given the same number of instances" % FIXTURES_ENV)
    return doc


def run_id(cycle_id: str) -> str:
    """The Actions run id of the loop's cycle id ``<run id>-<attempt>``."""
    found = CYCLE_ID.match(cycle_id) if isinstance(cycle_id, str) else None
    if found is None:
        raise Unusable("cycle id %r is not <run id>-<attempt>" % (cycle_id,))
    return found.group(1)


def _rows(ledger: bytes) -> list[dict]:
    rows = RD.chain_rows(ledger)
    if rows is None:
        raise Unusable("drill: brain/state's ledger is not a chain")
    return rows


def committed_by(rows: list[dict], at: int) -> str:
    """The run id of the cycle whose rows hold ``rows[at]``: its last ``cycle_start`` before it."""
    starts = [r for r in rows[:at] if r.get("part") == "events" and r.get("kind") == "cycle_start"]
    if not starts:
        raise Unusable("drill: commitment_unplaced")
    return run_id(starts[-1]["payload"].get("cycle_id"))


def step(inp: dict | None, ledger: bytes, unfinished: list[str], merging: bool, tree: str, this_run: str) -> dict:
    """D8's action this cycle (see the module docstring); ``Unusable`` for a run id that is not decimal digits."""
    try:
        return _step(inp, ledger, unfinished, merging, tree, this_run)
    except RD.Unusable as exc:
        raise Unusable("drill: %s" % cli.cause(exc)) from None


def _step(inp: dict | None, ledger: bytes, unfinished: list[str], merging: bool, tree: str, this_run: str) -> dict:
    if inp is None:
        return {"action": "off"}
    if "off" in inp:
        return {"action": "off", "why": inp["off"]}
    rows = _rows(ledger)
    drills = [i for i, r in enumerate(rows) if RD.is_drill(r, "commit") or RD.is_drill(r, "plant")]
    last = rows[drills[-1]] if drills else None
    out: dict[str, Any] = {}
    if last is not None and last["kind"] == "commit":
        answer = RD.key(inp["seed"], committed_by(rows, drills[-1]), inp["catalog"])
        if RD.commit_payload(answer) != last["payload"]:
            out["replaces"] = "commitment_mismatch"
        elif unfinished or merging:
            return {"action": "wait", "why": "merge_unfinished" if unfinished else "candidate_merges"}
        else:
            change = land.applied(tree, inp["patches"][answer["instance_id"]])
            if not change["reasons"]:
                return {"action": "plant", "instance_id": answer["instance_id"], "path": change["path"],
                        "content": change["content"]}
            out["replaces"] = "patch_does_not_apply"
    elif last is not None:
        if last["payload"].get("merge_sha") in unfinished:
            return {"action": "wait", "why": "drill_unfinished"}
        commits = [i for i in drills if rows[i]["kind"] == "commit"]
        if commits:
            answer = RD.key(inp["seed"], committed_by(rows, commits[-1]), inp["catalog"])
            out["judged"] = dict(RD.judge(ledger, answer), key=answer)
    misfits = sorted(i for i, patch in inp["patches"].items() if land.applied(tree, patch)["reasons"])
    if misfits:
        return dict(out, action="none", why="patch_does_not_apply", instances=misfits)
    answer = RD.key(inp["seed"], RD.cycle(this_run), inp["catalog"])
    return dict(out, action="commit", payload=RD.commit_payload(answer))


def line(done: dict) -> dict:
    """The step as ``yaz``'s line shows it: the planted file's content left out."""
    return {k: v for k, v in done.items() if k != "content"}
