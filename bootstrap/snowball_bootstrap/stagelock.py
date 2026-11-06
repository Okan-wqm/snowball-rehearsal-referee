"""The stage lock and the counter it is bound to (`tohum/02` 5, `asama-0/10a` "Kilidin açılışı", `tohum/25a` 9, `26c`).

``setup/imports.jsonl`` is the operator's human-touch counter: one chained row per touch (`26c:39-40`, `26`), a
transfer's row the one that carries ``referee_tree_sha256`` (`29n`, `29o`). ``setup/stage.json`` is the lock:
``{stage, pass_row_sha256, toy_state_head, copy_state_head, import_line_sha256}`` (`26c:40-41`). After it the counter
holds the open stage's batch transfers (`asama-1/13`, `26c` ``batch``), and `batches_done` reads them.

`stage-open` (`open_stage`; the operator's, after the PASS row, `25a` 9) reads the PASS row in the toy target's
`brain/state`, verifies both targets' chains with the seed's code and each one's last root with Sigstore, and writes the
lock. Nothing is pushed: the operator reviews the file and pushes it. The bootstrap reads the lock on every `pull` and
in `control` (`load`): the Stage 1 tables and the ``stage: 1`` tests hold only once it is there, and a lock that is not
exactly `26c`'s, or whose import line is not a Stage 0 transfer of a sound counter, stops the run (`asama-0/09` test 29:
a transition that does not match is refused).

What `stage-open` binds, before it writes anything (`02` 5: only the PASS row opens the lock):
- the referee that ran (B): the import line is the counter's last transfer, Stage 0's, and it is the line each
  target's last genesis row names (`29o` ``import_line_sha256``). `25a` 7: the loop opens `brain/state` with the
  genesis row, so it is the ledger's first row; `25a` 3: no one deletes or rewrites `brain/state`, so after a red (B)
  the operator reverts the transfer and imports the fixed SHA (`asama-0/10a` "Başarısızlık") and (B) runs again from a
  new genesis row that names the new line, the first one staying where it is. What (B) ran on is the last genesis
  row, and only the rows after it count: a transfer after the one (B) ran on opens nothing (E377), and a re-transfer
  does not lock the targets for good (E411).
- the two targets: each ledger opens with its target's genesis, and the last genesis names its `setup/summary.json`
  ``targets[]`` row, the toy's and the copy's, the copy's on its ``base_sha``, which a copy has (`29o`, E473), and the
  line's referee tree and signed result (E471); the PASS row carries the copy's last genesis and merge rows' hashes
  (`10a` #pass), and they are rows of the copy clone it is given (E376).
- the referee checkout: its commit holds the referee tree the last transfer line names (`26c`'s hash from git, what the
  import keeps left out, E471), so the lock opens on what the import pushed and the operator pulled; the counter and
  `setup/summary.json` are that commit's too, read from git and never from the working tree, whose bytes a checkout's
  settings change (E478).
- the stage's rival brake: that commit's `policy.json` names ``stage_budgets.asama_1.rival_usd``, which the bootstrap
  reads from the first run past the lock and stops without (`29b`, `26e`, `asama-1/10`; E492).
- the PASS row itself: the referee's own row, not a player's proposal (`26`, `13`: those carry ``proposed_by`` and
  ``trust: inferred``) (E388), written after the toy's merge and naming the transfer the counter's last line is (the
  trust root `10a` #pass writes includes the operator transfer) (E405), and the owner's exception exactly as the signed
  (A) result the last transfer imported names it (`02` "Sahip istisnası": the PASS row carries it by name) (E379): the
  import wrote that result's bytes beside its row as ``setup/results/<result_sha256>.json``, read from the commit and
  bound by its name (`26c`, E543), so no second copy of it is given on the command line.
- each root: the bundle the loop keeps beside it in the same `brain/state` commit (E414), its transparency log entry
  the root row's, whose entry hash is the root (`29j` ``entry_root_mismatch``, `vectors/root/rekor.json`), and Sigstore
  verifies the bundle against the digest ``sha256:<root>`` (`13`: Rekor carries only the hash) (E375).

The PASS row's fields and the rule applied here are `tohum/26d`'s, the page the Founder reads (E404, E414). Spec
sessiz, the narrowest choice each time (register E371, E375-E379, E388, E411, E414, E416):
- ``<state_root>`` is the directory `01a` names, ``.brain/`` at the root of the target's `brain/state` (the operator's
  decision under the owner's authority, E417: the Founder reads `01a` as written; E58's one folder): `ledger.jsonl`,
  `chain/root.jsonl` and the root's bundle ``chain/<root>.sigstore.json`` under it, read at the commit ``--ref`` names
  in the operator's local clone (default ``refs/remotes/origin/brain/state``); that commit is the state head the lock
  records. A profile (`26b` ``state_root``) anywhere in that commit naming another directory stops: reading it needs a
  seed epoch.
- A row is a player's proposal when ``proposed_by`` names its proposer (a string that is not empty); a proposal is left
  out first, so a proposed copy cannot block the lock. A row that carries ``proposed_by`` with any other value (null)
  is counted, and is not the referee's own. The referee's own (`26`): no ``proposed_by``, ``trust`` one of ``verified``
  and ``observed`` (``inferred`` is a proposal's), a ``derivation`` merge evidence may have (the first three). A genesis
  row is an ``events`` row of ``kind: genesis`` that is the referee's own, a merge row one of ``kind: merge``.
- The PASS row is the one ``events`` row after the toy's last genesis (`27a`: `stage-open` reads `events`) whose
  ``payload`` has ``stage: 0`` and ``verdict: "PASS"`` (`02` 4, `19`), counted among the rows that are no proposal;
  none or two stop. Its ``pass_row_sha256``, like ``import_line_sha256`` (`29o`), is the sha256 of its line without
  the LF. A merge row is between that genesis and the PASS row (`asama-0/08`: the toy's merge is round 2, the PASS row
  round 9). The copy's rows it carries: ``payload.copy_genesis_row_hash`` and ``payload.copy_merge_row_hashes`` (one or
  more), each a ``row_hash`` (`26`) of the copy's last genesis and of merge rows after it. The transfer:
  ``payload.import_line_sha256`` is the counter's last transfer line's, as the last genesis rows'. The owner's
  exceptions: ``payload.owner_exception`` is the signed result's ``exit.owner_exception`` (an array by anchor, E563),
  canonically the same, and is absent when that is.
- Every `profile.json` of a target's commit is one plain JSON object (no byte order mark, no key twice); one that is not
  stops, as skipped it could hide one naming another ``state_root`` (E472).
- A chained file (`26`): every line ends with LF and has no CR, is one JSON object with no key twice, and its
  ``row_hash`` is `canon.row_hash`'s with ``prev_hash`` the previous row's, 64 zeros first.
- A root (`13`, `29j`): the last ``chain/root.jsonl`` row's ``root`` is sha256 of the RFC 8785 bytes of the ledger's
  tips (each part's last ``row_hash``) at the head. Its bundle, signed by ``--identity`` (the loop workflow's), is a
  regular file of the same commit (E414); its one log entry is the one the row names: its leaf hash, sha256(0x00 ‖
  canonicalized body, strict base64), is ``rekor_uuid`` (the last 64 characters when a 16-character tree id leads), and
  the body is a Rekor v1 ``hashedrekord`` (``apiVersion`` 0.0.1) whose ``spec.data.hash`` is ``{algorithm: sha256,
  value: <root>}``: the root itself (E474; pinned sigstore 4.5.0 picks the highest version the TUF signing config lists
  unless ``--rekor-version`` says otherwise, E415).
- Stage 0 → 1 is the only lock this seed opens (`03`: Stages 0 and 1 are the ladder's fixed root); a lock already in
  place is never written over. Past the lock's line, every transfer is a batch transfer of the lock's stage.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import canon, config, gitio, stages
from .config import ConfigError, Target
from .stages import BATCH_RE

SETUP = "setup"
LOCK_FILE = "stage.json"
COUNTER_FILE = "imports.jsonl"
RESULTS_DIR = "results"  # the signed result each transfer imported, by its result_sha256 (`26c`, E543)
LOCK_KEYS = ("stage", "pass_row_sha256", "toy_state_head", "copy_state_head", "import_line_sha256")
OPENS = 1  # the stage the seed's lock opens: Stage 0 -> 1 (`03`)
STATE_ROOT = ".brain/"  # `<state_root>` in `brain/state`, `01a`'s default; no other is read before a seed epoch (E417)
LEDGER = STATE_ROOT + "ledger.jsonl"
ROOTS = STATE_ROOT + "chain/root.jsonl"
ROOT_BUNDLE = STATE_ROOT + "chain/{root}.sigstore.json"  # the root's Sigstore bundle, beside its root row (E414)
DEFAULT_REF = "refs/remotes/origin/brain/state"
# The derivations merge evidence may have (`26`: "yalnız ilk üç derivation"): the PASS row is the referee's measurement.
REFEREE_DERIVATIONS = ("tool", "static_analysis", "test_verified")
# `26`'s trust values but ``inferred``, which a player's proposal is stored with: the referee's own rows (E404).
REFEREE_TRUST = ("verified", "observed")
ZERO = "0" * 64
HEX64 = re.compile(r"^[0-9a-f]{64}\Z")
SHA = re.compile(r"^[0-9a-f]{40}\Z")
UUID = re.compile(r"^(?:[0-9a-f]{16})?([0-9a-f]{64})\Z")


class LockStop(ConfigError):
    """The lock cannot be read, or `stage-open` must not write it; the message says why."""


def result_file(result_sha256: str) -> str:
    """Where a transfer's signed result lies in the referee repository (`26c`, E543): the import writes its bytes there
    in the commit of its counter row; the loop's ``yaz`` and `stage-open` read it by the row's ``result_sha256``."""
    return f"{SETUP}/{RESULTS_DIR}/{result_sha256}.json"


def _unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    found: dict[str, Any] = {}
    for key, value in pairs:
        if key in found:
            raise ValueError(f"key {key!r} twice")
        found[key] = value
    return found


def _constant(name: str) -> Any:
    raise ValueError(f"{name} is not JSON a hash can hold")


def chained_lines(data: bytes, where: str) -> list[tuple[bytes, dict[str, Any]]]:
    """Each line of a chained JSONL file (without its LF) with its row; an empty file has none. Stops on the first line
    that is not a sound link of the chain (`26`), naming ``where`` and the line."""
    if not data:
        return []
    if not data.endswith(b"\n"):
        raise LockStop(f"{where}: the last line has no newline")
    found: list[tuple[bytes, dict[str, Any]]] = []
    prev = ZERO
    for number, line in enumerate(data[:-1].split(b"\n"), start=1):
        try:
            if b"\r" in line:
                raise ValueError("a carriage return")
            row = json.loads(line.decode("utf-8"), object_pairs_hook=_unique, parse_constant=_constant)
            if not isinstance(row, dict):
                raise ValueError("not an object")
            if row.get("prev_hash") != prev:
                raise ValueError("prev_hash is not the previous row's row_hash")
            if row.get("row_hash") != canon.row_hash(row):
                raise ValueError("row_hash is not the row's")
        except (UnicodeDecodeError, ValueError, RecursionError) as exc:
            raise LockStop(f"{where} line {number} breaks the chain: {exc}") from exc
        prev = row["row_hash"]
        found.append((line, row))
    return found


def line_sha256(line: bytes) -> str:
    """A row's line hash: its bytes without the LF (`29o` ``import_line_sha256``)."""
    return hashlib.sha256(line).hexdigest()


def is_transfer(row: dict[str, Any]) -> bool:
    """A transfer's counter row, as against another touch (`29n`, `29o`)."""
    return "referee_tree_sha256" in row


def read_counter(referee: Path) -> list[tuple[bytes, dict[str, Any]]]:
    """The operator's counter, verified; none when the file is not there yet."""
    path = referee / SETUP / COUNTER_FILE
    try:
        data = path.read_bytes()
    except FileNotFoundError:
        return []
    except OSError as exc:
        raise LockStop(f"{SETUP}/{COUNTER_FILE} cannot be read: {type(exc).__name__}") from exc
    return chained_lines(data, f"{SETUP}/{COUNTER_FILE}")


@dataclass(frozen=True)
class Lock:
    stage: int
    pass_row_sha256: str
    toy_state_head: str
    copy_state_head: str
    import_line_sha256: str


def _after_the_lock(counter: list[tuple[bytes, dict[str, Any]]], lock: Lock) -> list[dict[str, Any]] | None:
    """The transfer rows after the lock's import line; None when no transfer row has that line."""
    for index, (line, row) in enumerate(counter):
        if is_transfer(row) and line_sha256(line) == lock.import_line_sha256:
            return [r for _l, r in counter[index + 1:] if is_transfer(r)]
    return None


def load(root: Path) -> Lock | None:
    """The lock as the bootstrap reads it on every pull; None before `stage-open` wrote it (Stage 0)."""
    path = root / SETUP / LOCK_FILE
    if not path.exists():
        return None
    where = f"{SETUP}/{LOCK_FILE}"
    try:
        data = json.loads(path.read_bytes().decode("utf-8"), object_pairs_hook=_unique, parse_constant=_constant)
    except (OSError, UnicodeDecodeError, ValueError, RecursionError) as exc:
        raise LockStop(f"{where} is not readable JSON: {exc}") from exc
    if not isinstance(data, dict) or set(data) != set(LOCK_KEYS):
        raise LockStop(f"{where} must have exactly the keys {', '.join(LOCK_KEYS)} (`26c`)")
    if type(data["stage"]) is not int or data["stage"] != OPENS:
        raise LockStop(f"{where}.stage must be {OPENS}: the seed's lock opens Stage {OPENS} after Stage 0's PASS")
    for key in ("pass_row_sha256", "import_line_sha256"):
        if not isinstance(data[key], str) or not HEX64.match(data[key]):
            raise LockStop(f"{where}.{key} must be 64 lowercase hex characters")
    for key in ("toy_state_head", "copy_state_head"):
        if not isinstance(data[key], str) or not SHA.match(data[key]):
            raise LockStop(f"{where}.{key} must be a 40-character commit SHA")
    lock = Lock(**data)
    counter = read_counter(root)
    named = [row for line, row in counter if is_transfer(row) and line_sha256(line) == lock.import_line_sha256]
    if not named:
        raise LockStop(f"{where}.import_line_sha256 names no transfer row of {SETUP}/{COUNTER_FILE}")
    if named[0].get("stage") != lock.stage - 1 or type(named[0].get("stage")) is not int:
        raise LockStop(f"{where}.import_line_sha256 names a transfer that is not Stage {lock.stage - 1}'s")
    for row in _after_the_lock(counter, lock) or []:  # `asama-1/13`: past the lock, only the open stage's batches
        if type(row.get("stage")) is not int or row["stage"] != lock.stage or not isinstance(row.get("batch"), str) \
                or not BATCH_RE.match(row["batch"]):
            raise LockStop(f"{SETUP}/{COUNTER_FILE}: a transfer after the lock's line is not a Stage {lock.stage} "
                           "batch's (`asama-1/13`, `26c` batch)")
    return lock


def batches_done(root: Path, lock: Lock) -> tuple[str, ...]:
    """The batches transferred since the lock opened, in the counter's order (`26c` ``batch``, `asama-1/13`); `load`
    has checked that each later transfer is one."""
    return tuple(row["batch"] for row in _after_the_lock(read_counter(root), lock) or [])


def open_table(root: Path) -> stages.StageTable:
    """The table that holds, from the operator's files under ``root`` alone (`asama-0/10a`: the Stage 1 table holds
    only once the lock is there): Stage 0's while there is no lock, past it the open batch's after the batches the
    counter transferred. Every job and the import read it here, so what a batch is and which form an exit request has
    are this table's, never what a request or a job's input says (E402)."""
    lock = load(root)
    return stages.load(lock.stage, done=batches_done(root, lock)) if lock else stages.load(0)


# ---------------------------------------------------------------- stage-open

def _state(repo: Path, ref: str, name: str) -> tuple[str, list[tuple[bytes, dict[str, Any]]], dict[str, Any], bytes]:
    """A target's state head, its ledger rows (chain verified), its last root row (chain verified, the tips' root) and
    that root's Sigstore bundle, all read at the head."""
    try:
        head = gitio.git(repo, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}").decode().strip()
    except gitio.GitError as exc:
        raise LockStop(f"{name}: {ref} is not a commit in {repo} (fetch the target's brain/state first)") from exc
    _one_state_root(repo, head, name)
    ledger = gitio.file_at(repo, head, LEDGER)
    roots = gitio.file_at(repo, head, ROOTS)
    if ledger is None or roots is None:
        raise LockStop(f"{name} brain/state {head}: no {LEDGER if ledger is None else ROOTS} (`<state_root>` is "
                       f"{STATE_ROOT} at the root of brain/state, `01a`, `26d`)")
    rows = chained_lines(ledger, f"{name} brain/state {LEDGER}")
    anchors = chained_lines(roots, f"{name} brain/state {ROOTS}")
    if not rows or not anchors:
        raise LockStop(f"{name} brain/state {head}: {LEDGER if not rows else ROOTS} has no row")
    tips: dict[str, str] = {}
    for _line, row in rows:
        if not isinstance(row.get("part"), str):
            raise LockStop(f"{name} brain/state {LEDGER}: a row has no part")
        tips[row["part"]] = row["row_hash"]
    last = anchors[-1][1]
    root = hashlib.sha256(canon.canonical(tips)).hexdigest()
    if last.get("root") != root:
        raise LockStop(f"{name} brain/state {head}: the ledger's tips are not the last anchored root (`13`, `29j`)")
    if not isinstance(last.get("rekor_uuid"), str) or not UUID.match(last["rekor_uuid"]):
        raise LockStop(f"{name} brain/state {ROOTS}: the last root row has no rekor_uuid")
    where = ROOT_BUNDLE.format(root=last["root"])  # the root row's own bundle (`26d`: named by its root)
    bundle = gitio.file_at(repo, head, where)
    if bundle is None:
        raise LockStop(f"{name} brain/state {head}: no {where}, the last root's Sigstore bundle the loop keeps beside "
                       "its root row (`26d`)")
    return head, rows, last, bundle


def _one_state_root(repo: Path, head: str, name: str) -> None:
    """E417: this seed reads `<state_root>` at ``.brain/`` alone (`01a`'s default). A profile in the commit (`26b`: its
    ``state_root``) that names another directory stops, named: reading it needs a seed epoch. A profile this check cannot
    read as one plain JSON object (a link or a submodule, a byte order mark, a key twice, not UTF-8, not JSON, or JSON
    that is no object) stops too: skipped, it could hide the one that names another directory (E472, E481)."""
    for path in gitio.tree_paths(repo, head):
        if path.rsplit("/", 1)[-1] != "profile.json":
            continue
        data = gitio.file_at(repo, head, path)
        try:
            if data is None:
                raise ValueError("not a regular file")
            profile = json.loads(data.decode("utf-8"), object_pairs_hook=_unique, parse_constant=_constant)
            if not isinstance(profile, dict):
                raise ValueError("not a JSON object")
        except (UnicodeDecodeError, ValueError, RecursionError) as exc:
            raise LockStop(f"{name} brain/state {head}: {path} is not a profile this seed can read ({exc}; `26b`, "
                           "E472)") from exc
        if "state_root" in profile and profile["state_root"] not in (STATE_ROOT, STATE_ROOT.rstrip("/")):
            raise LockStop(f"{name} brain/state {head}: {path} names state_root {profile['state_root']!r}: a state_root "
                           f"other than {STATE_ROOT} needs a seed epoch (`01a`, `26d`, E417)")


def _log_body(bundle: bytes, name: str) -> bytes:
    """The canonicalized body of the bundle's one transparency log entry."""
    try:
        data = json.loads(bundle.decode("utf-8"))
        entries = data["verificationMaterial"]["tlogEntries"]
        if not isinstance(entries, list) or len(entries) != 1:
            raise ValueError("not one log entry")
        return base64.b64decode(entries[0]["canonicalizedBody"], validate=True)
    except (UnicodeDecodeError, ValueError, RecursionError, KeyError, TypeError, binascii.Error) as exc:
        raise LockStop(f"{name} root bundle (brain/state {STATE_ROOT}chain/<root>.sigstore.json) is not a Sigstore bundle "
                       f"with one log entry: {exc}") from exc


def _entry_hash(body: bytes) -> Any:
    """The hash a `hashedrekord` log entry records (`spec.data.hash`), or None when the body is not one."""
    try:
        data = json.loads(body.decode("utf-8"))
        v1 = data.get("kind") == "hashedrekord" and data.get("apiVersion") == "0.0.1"  # Rekor v1's body (E474)
        return data["spec"]["data"]["hash"] if v1 else None
    except (UnicodeDecodeError, ValueError, RecursionError, KeyError, TypeError, AttributeError):
        return None


def _verify_root(root_row: dict[str, Any], bundle: bytes, identity: str, sigstore_python: str, name: str) -> None:
    named = UUID.match(root_row["rekor_uuid"]).group(1)  # type: ignore[union-attr]
    body = _log_body(bundle, name)
    if hashlib.sha256(b"\x00" + body).hexdigest() != named:
        raise LockStop(f"{name}: the root bundle's log entry is not the last root row's rekor_uuid")
    if _entry_hash(body) != {"algorithm": "sha256", "value": root_row["root"]}:
        raise LockStop(f"{name}: the root bundle's log entry does not record the root as its hash (`29j` "
                       "entry_root_mismatch; a Rekor v1 hashedrekord, `26d`)")
    from . import importer  # the seed's one call into Sigstore, the import's (imported here: it reads this module)
    with tempfile.TemporaryDirectory(prefix="snowball-root-") as tmp:  # Sigstore reads a bundle file
        bundle_file = Path(tmp) / f"{name}-root.sigstore.json"
        bundle_file.write_bytes(bundle)
        importer.verify_signature(f"sha256:{root_row['root']}", bundle_file, identity, sigstore_python)


def _proposal(row: dict[str, Any]) -> bool:
    """`26`: a row the player proposed, marked with the proposer's name; left out before anything is counted."""
    return isinstance(row.get("proposed_by"), str) and row["proposed_by"] != ""


def _referees_own(row: dict[str, Any]) -> bool:
    """`26`: the referee wrote it as its own: not a player's proposal, from evidence a merge may rest on."""
    return ("proposed_by" not in row and row.get("trust") in REFEREE_TRUST
            and row.get("derivation") in REFEREE_DERIVATIONS)


def _is_merge(row: dict[str, Any]) -> bool:
    """A merge row (`26d`): an ``events`` row of ``kind: merge``, the referee's own."""
    return row.get("part") == "events" and row.get("kind") == "merge" and _referees_own(row)


def _is_genesis(row: dict[str, Any]) -> bool:
    """A genesis row (`25a` 7, `29o`, `26d`): an ``events`` row of ``kind: genesis``, the referee's own."""
    return row.get("part") == "events" and row.get("kind") == "genesis" and _referees_own(row)


def _payload(row: dict[str, Any]) -> dict[str, Any]:
    return row["payload"] if isinstance(row.get("payload"), dict) else {}


def _pass_line(rows: list[tuple[bytes, dict[str, Any]]], start: int,
               import_line: str) -> tuple[bytes, dict[str, Any]]:
    """The toy ledger's PASS row (`26d`) after its last genesis at ``start``, counted among the rows that are no
    proposal: one, the referee's own, after a merge that is after that genesis, and naming the transfer the lock binds."""
    found = [(index, line, row) for index, (line, row) in enumerate(rows) if index > start and not _proposal(row)
             and row.get("part") == "events" and isinstance(row.get("payload"), dict)
             and type(row["payload"].get("stage")) is int and row["payload"]["stage"] == OPENS - 1
             and row["payload"].get("verdict") == "PASS"]
    if len(found) != 1:
        raise LockStop(f"toy brain/state {LEDGER}: " + ("no PASS row" if not found else f"{len(found)} PASS rows")
                       + f" after the last genesis (an events row, no player's proposal, whose payload is stage "
                       f"{OPENS - 1}, verdict PASS)")
    index, line, row = found[0]
    if not _referees_own(row):
        carried = f"proposed_by {json.dumps(row['proposed_by'])}" if "proposed_by" in row else "no proposed_by"
        raise LockStop(f"the PASS row is not the referee's own row (`26`, `26d`; it has {carried}): no proposed_by, "
                       f"trust one of {', '.join(REFEREE_TRUST)} (inferred is a player's proposal), derivation one of "
                       f"{', '.join(REFEREE_DERIVATIONS)}")
    if not any(_is_merge(earlier) for _line, earlier in rows[start + 1:index]):
        raise LockStop("the PASS row comes before the toy's merge: no merge row (an events row of kind merge, the "
                       "referee's own) is between the toy's last genesis and it (`asama-0/08` rounds 2 and 9, `26d`)")
    if row["payload"].get("import_line_sha256") != import_line:
        raise LockStop("the PASS row names another transfer than the counter's last one (payload.import_line_sha256, "
                       "`26d`; `10a` #pass: the trust root includes the operator transfer)")
    return line, row


def _targets(summary: config.Summary) -> tuple[Target, Target]:
    """`setup/summary.json`'s toy and copy target, one of each (`26c` ``targets[]``)."""
    kinds = {kind: [t for t in summary.targets or () if t.kind == kind] for kind in ("toy", "copy")}
    if any(len(found) != 1 for found in kinds.values()):
        raise LockStop("setup/summary.json targets[] must name one toy and one copy target (`26c`, `25` 10a)")
    copy = kinds["copy"][0]
    if not isinstance(copy.base_sha, str) or not SHA.match(copy.base_sha):
        raise LockStop("setup/summary.json's copy target has no base_sha: a copy is made from a base (`26c`, `29o`, "
                       "E473)")
    return kinds["toy"][0], copy


def _genesis(rows: list[tuple[bytes, dict[str, Any]]], name: str, target: Target, import_line: str,
             transfer: dict[str, Any]) -> int:
    """Where the target's last genesis row is. The ledger opens with the target's genesis (`25a` 7); (B) ran from its
    last genesis, which is bound to the target's ``targets[]`` row and to the transfer the lock records (`29o`: the
    line's hash, and the referee tree and signed result it names, E471): a re-transfer after a red (B) runs (B) again
    from a new one (`asama-0/10a` "Başarısızlık", `25a` 3, E411)."""
    first = rows[0][1]
    if not _is_genesis(first) or _payload(first).get("target") != target.id:
        raise LockStop(f"{name} brain/state: the first ledger row is not the genesis of setup/summary.json's {name} "
                       f"target {target.id!r} (an events row of kind genesis, the referee's own, payload.target; "
                       f"`25a` 7, `29o`, `26d`; is --{name} that target's clone?)")
    start = max(index for index, (_line, row) in enumerate(rows) if _is_genesis(row))
    payload = _payload(rows[start][1])
    if payload.get("target") != target.id:
        raise LockStop(f"{name} brain/state: the last genesis row is not the genesis of setup/summary.json's {name} "
                       f"target {target.id!r} (payload.target, `29o`, `26d`)")
    if name == "copy" and payload.get("base_sha") != target.base_sha:
        raise LockStop("copy brain/state: the last genesis row's base_sha is not targets[]'s for the copy (`29o`)")
    if payload.get("import_line_sha256") != import_line:
        raise LockStop(f"{name} brain/state: the last genesis row names another transfer than the counter's last one "
                       "(payload.import_line_sha256, `29o`): the lock binds the referee (B) ran on; after a "
                       "re-transfer (B) runs again from a new genesis row in both targets (`26d`)")
    for key in ("referee_tree_sha256", "result_sha256"):
        if payload.get(key) != transfer.get(key):
            raise LockStop(f"{name} brain/state: the last genesis row's {key} is not the counter's last transfer "
                           f"line's (payload.{key}, `29o`, E471)")
    return start


def _carries_the_copy(payload: dict[str, Any], copy_rows: list[tuple[bytes, dict[str, Any]]], start: int) -> None:
    """`10a` #pass: the PASS row carries the copy's genesis and merge rows' hashes, rows of the copy clone given: its
    last genesis at ``start`` and merge rows after it."""
    if payload.get("copy_genesis_row_hash") != copy_rows[start][1]["row_hash"]:
        raise LockStop("the PASS row does not name the copy's last genesis row (payload.copy_genesis_row_hash, `10a` "
                       "#pass, `26d`)")
    merges = payload.get("copy_merge_row_hashes")
    later = {row["row_hash"]: row for _line, row in copy_rows[start + 1:]}
    if not isinstance(merges, list) or not merges or not all(isinstance(h, str) and h in later and _is_merge(later[h])
                                                            for h in merges) \
            or len(set(merges)) != len(merges):
        raise LockStop("the PASS row does not name the copy's merge rows, each once and each a merge row of the "
                       "copy's ledger after its last genesis (an events row of kind merge, the referee's own; "
                       "payload.copy_merge_row_hashes, `10a` #pass, `26d`)")


def _committed_is_transferred(referee: Path, head: str, transfer: dict[str, Any]) -> None:
    """E471: the referee tree the checkout's commit holds, what the import keeps left out, read from git (`26c`'s rule),
    is the one the counter's last transfer line names: the lock opens on the referee that transfer wrote."""
    from . import importer  # it reads this module
    try:
        committed = importer.committed_referee_hash(referee, head)
    except (gitio.GitError, importer.ImportErrorStop) as exc:
        raise LockStop(f"--referee {referee} holds no commit whose referee tree this seed can read: {exc}") from exc
    if committed != transfer.get("referee_tree_sha256"):
        raise LockStop("the referee tree the checkout's commit holds is not the one the counter's last transfer line "
                       "names (its referee_tree_sha256; pull main after the import, E471)")


def _signed_exit(referee: Path, head: str, transfer: dict[str, Any]) -> dict[str, Any]:
    """The ``exit`` block of the signed (A) result the transfer imported, from the checkout's commit (E543): the import
    wrote its bytes as ``setup/results/<result_sha256>.json`` in the commit of its row (`26c`), and they must hash to
    that name, so a file edited or put there by hand opens nothing."""
    name = transfer.get("result_sha256")
    if not isinstance(name, str) or not HEX64.match(name):
        raise LockStop(f"{SETUP}/{COUNTER_FILE}: the last transfer's result_sha256 is not a sha256 (`26c`)")
    rel = result_file(name)
    data = _committed(referee, head, rel)
    if hashlib.sha256(data).hexdigest() != name:
        raise LockStop(f"{rel} is not the signed result the counter's last transfer imported: its bytes do not hash to "
                       "its result_sha256 (`26c`)")
    try:
        exit_block = json.loads(data.decode("utf-8")).get("exit")
    except (UnicodeDecodeError, ValueError, RecursionError, AttributeError) as exc:
        raise LockStop(f"{rel} is not a result: {exc}") from exc
    if not isinstance(exit_block, dict):
        raise LockStop(f"{rel} has no exit block")
    return exit_block


def _carries_the_exception(payload: dict[str, Any], exit_block: dict[str, Any]) -> None:
    """`02` "Sahip istisnası": the PASS row carries the owner's exceptions by name, as the signed (A) result names them
    (an array by anchor of ``{anchor, stage, carry_to, reason, carry_commitment, measured: false}``, E563), so no
    carried condition is lost. Canonical equality holds the whole array: each element, their order and their count."""
    if ("owner_exception" in payload) != ("owner_exception" in exit_block):
        raise LockStop("the PASS row's owner_exception is not the signed result's: one names an owner's exception, the "
                       "other none (`02` 'Sahip istisnası')")
    if "owner_exception" in payload:
        try:
            same = canon.canonical(payload["owner_exception"]) == canon.canonical(exit_block["owner_exception"])
        except ValueError:
            same = False
        if not same:
            raise LockStop("the PASS row does not carry the owner's exceptions as the signed result names them "
                           "(payload.owner_exception, exit.owner_exception: an array by anchor of {anchor, stage, "
                           "carry_to, reason, carry_commitment, measured}; `02`)")


def _checkout_head(referee: Path) -> str:
    """The commit the referee checkout is on: what `stage-open` reads (E471, E478). ``--referee`` is the top of its
    checkout (E497): every path here, the lock it looks for in the commit and the file it writes, is read from the top,
    and git reads a path argument from the directory it runs in, so a subdirectory would find no lock and write one
    beneath itself."""
    try:
        head = gitio.git(referee, "rev-parse", "--verify", "--quiet", "HEAD^{commit}").decode().strip()
        prefix = gitio.git(referee, "rev-parse", "--show-prefix").decode().strip()
    except gitio.GitError as exc:
        raise LockStop(f"--referee {referee} holds no commit: clone the referee repository and pull main after the "
                       "import (E471)") from exc
    if prefix:
        raise LockStop(f"--referee {referee} is {prefix!r} inside its checkout: give the checkout's top (E497)")
    return head


def _committed(referee: Path, head: str, rel: str) -> bytes:
    """A file of the checkout's commit, read from its blob: never the working tree, whose bytes a checkout's settings
    change (``core.autocrlf``) and where an edit is not what the import pushed (E478)."""
    data = gitio.file_at(referee, head, rel)
    if data is None:
        raise LockStop(f"the referee checkout's commit {head} has no {rel}: import, then pull main into the checkout "
                       "(E478)")
    return data


def _committed_summary(referee: Path, head: str) -> config.Summary:
    try:
        return config.summary_of(json.loads(_committed(referee, head, f"{SETUP}/summary.json").decode("utf-8")))
    except (UnicodeDecodeError, ValueError, RecursionError) as exc:
        raise LockStop(f"setup/summary.json of the referee checkout's commit {head} is not JSON: {exc}") from exc


def _committed_stage_brake(referee: Path, head: str, stage: int) -> None:
    """The stage the lock opens has its rival brake in the commit's `policy.json` (`29b`, `26e`, `asama-1/10`; E492):
    the bootstrap reads it on the first run past the lock and stops without it, so no lock opens on a policy that lacks
    it."""
    try:
        config.policy_of(json.loads(_committed(referee, head, "policy.json").decode("utf-8"))).rival_usd_micros(stage)
    except (UnicodeDecodeError, ValueError, RecursionError) as exc:  # ConfigError is a ValueError
        raise LockStop(f"policy.json of the referee checkout's commit {head}: {exc} (write "
                       f"stage_budgets.asama_{stage}.rival_usd before the lock, `26e`)") from exc


def open_stage(referee: Path, toy: Path, copy: Path, ref: str, identity: str, sigstore_python: str) -> dict[str, Any]:
    """Write ``setup/stage.json`` after Stage 0's PASS row; return what was written. Nothing is pushed. The counter, the
    summary, the policy, the signed (A) result and the referee tree are the checkout's commit's, read from git (E471,
    E478, E492, E543)."""
    path = referee / SETUP / LOCK_FILE
    head = _checkout_head(referee)
    if path.exists() or gitio.git(referee, "ls-tree", "--name-only", head, "--", f"{SETUP}/{LOCK_FILE}").strip():
        raise LockStop(f"{SETUP}/{LOCK_FILE} is already there: the lock is open (revert its commit to close it)")
    counter = chained_lines(_committed(referee, head, f"{SETUP}/{COUNTER_FILE}"), f"{SETUP}/{COUNTER_FILE}")
    transfers = [(line, row) for line, row in counter if is_transfer(row)]
    if not transfers or transfers[-1][1].get("stage") != OPENS - 1 or type(transfers[-1][1].get("stage")) is not int:
        raise LockStop(f"{SETUP}/{COUNTER_FILE}: the last transfer is not Stage {OPENS - 1}'s accepted, transferable "
                       "exit (import it first)")
    import_line, transfer = line_sha256(transfers[-1][0]), transfers[-1][1]
    exit_block = _signed_exit(referee, head, transfer)
    _committed_is_transferred(referee, head, transfer)
    toy_target, copy_target = _targets(_committed_summary(referee, head))
    _committed_stage_brake(referee, head, OPENS)
    toy_head, toy_rows, toy_root, toy_bundle = _state(toy, ref, "toy")
    copy_head, copy_rows, copy_root, copy_bundle = _state(copy, ref, "copy")
    toy_start = _genesis(toy_rows, "toy", toy_target, import_line, transfer)
    copy_start = _genesis(copy_rows, "copy", copy_target, import_line, transfer)
    pass_line, pass_row = _pass_line(toy_rows, toy_start, import_line)
    _carries_the_copy(pass_row["payload"], copy_rows, copy_start)
    _carries_the_exception(pass_row["payload"], exit_block)
    _verify_root(toy_root, toy_bundle, identity, sigstore_python, "toy")
    _verify_root(copy_root, copy_bundle, identity, sigstore_python, "copy")
    lock = {"stage": OPENS, "pass_row_sha256": line_sha256(pass_line), "toy_state_head": toy_head,
            "copy_state_head": copy_head, "import_line_sha256": import_line}
    path.write_bytes(canon.dump(lock).encode("utf-8"))
    return lock
