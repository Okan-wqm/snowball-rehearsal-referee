"""The ``pulled`` artifact: what ``çek`` (D1) hands to the jobs after it, one layout written and read here (stage 0).

Rules: asama-0/01 D1 (``çek`` reads, at the SHA the bootstrap referee last accepted, ``candidates/<target>/`` and
``targets/<target>/units.json``, and the target's tree; it writes ``pulled``) and D3 (``koş`` reads ``pulled``),
tohum/26c (a ready candidate is ``candidates/<target>/<cid>/`` holding ``finding.json``, ``diff.patch`` and
``expect.json``; a ``targets[]`` entry of ``setup/summary.json``), tohum/08 item 1 and tohum/01b (a job takes
another job's output only by artifact and hash; the workflow's download checks the artifact's digest,
``digest-mismatch: error``, and this module checks each file against the manifest inside it).

**Layout** (a directory; ``pulled.json`` is written last)::

    pulled.json                 {schema: "snowball-pulled/1", target, files: {path: sha256}}
    tree.tar                    the target's tree as a tar archive (``git archive``'s format)
    units.json                  targets/<target>/units.json as read
    policy.json                 the referee repository's policy.json as read
    state/heads.json            {"brain/state": commit | null, "brain/integration": commit}: the heads D1 read
    state/ledger.jsonl          brain/state's files at that head, the bytes D1 verified (``target.branches``'
    state/chain/root.jsonl        ``STATE_CHAINS``, each by its name under the state directory, ``state_name``:
                                  the commit's ``.brain/`` is not repeated; MF1's verify --previous, MF11's root)
    state/status.md             brain/state's ``status.md`` at that head, as read; absent when the head has none
    candidates/<cid>/finding.json, diff.patch, expect.json

**Served** (tohum/29s "Hedefler": a run serves every ``targets[]`` entry, in the array's order). The uploaded
artifact is a directory holding ``served.json`` ``{schema: "snowball-served/1", targets: [id, ...]}``, the ids of the
targets ``cek`` serves this run in that order, and for each id a directory ``<id>/`` laid out as above; nothing
else. ``cek`` alone decides which targets are served (``write_served``); every later job serves exactly that list,
in that order (``served``: ``served_unreadable`` unless the file is a regular file holding exactly those two keys,
the schema, and distinct ids each a target id, ``runner.kos.CANDIDATE_ID``; ``served_missing:<id>`` for an id
without its directory, a link included; ``unlisted:<name>`` for any other entry). Each job's own artifact holds
one ``<id>/`` per served target the same way (``out/deps/<id>/``, ``out/results/<id>/``, ``out/response/<id>/``).

``target`` is the ``targets[]`` entry of ``setup/summary.json`` for this target, as read (an object with a string
``id``; its lists are checked by ``profile.derive`` where they are used). ``<cid>`` is ``runner.kos``'s candidate id.
``state/`` is what the jobs after D1 know of the cycle's state: the ledger the stage brake sums (D4) and that D6
extends, the ``status.md`` whose block D6 regenerates, the heads D6 writes on and D7 watches; a job reads it here,
never from the target.

**The genesis cycle** (``genesis``): ``brain/state`` ``null`` in ``state/heads.json`` is a target that has neither
``brain/state`` nor ``brain/integration`` yet, whose cycle is its activation (tohum/26a ``activate``: the operator's
first cycle; ``yaz`` runs ``activate``). Then ``brain/integration`` is the commit the tree was read from, the one the
activation cuts ``brain/integration`` at, both chained files are empty and there is no ``status.md``; any other
combination is ``heads_invalid`` (``write`` refuses it the same way). Every other cycle has both heads.

**Reading** (``read``; every reason that holds is listed, prefixed ``pulled:`` by the job): the manifest is a
regular file holding a JSON object with exactly those three keys (``manifest_unreadable``), the schema
(``schema_unknown``), the target (``target_invalid``); ``files`` maps each path to 64 lowercase hex
(``files_invalid``); every path is one of the layout's (``path_not_in_layout:<path>``); ``tree.tar``,
``units.json``, ``policy.json`` and the ``state/`` files but ``state/status.md`` are listed (``missing:<path>``) and every listed candidate has its three files
(``candidate_incomplete:<cid>``); every listed file is a regular file, no symlink on its way, with the listed
sha256 (``file_missing:<path>``, ``hash_mismatch:<path>``); no other file or directory is in the artifact
(``unlisted:<path>``). ``units.json``, ``policy.json`` and ``state/heads.json`` must be JSON
(``json_unreadable:<path>``), and ``state/heads.json`` an object of exactly ``brain/state`` and ``brain/integration``, each 40 lowercase hex,
``brain/state`` ``null`` only in the genesis cycle's form above (``heads_invalid``). The chained files are not judged here: their reader verifies what it uses (the stage brake's
``llm_call.CostBook`` verifies the ledger as a chain).

**The tree** (``extract_tree``): Python's ``tarfile`` with its ``data`` filter, into a directory that must not
exist: directories, regular files and links that stay inside it; a member whose path leaves the directory
(``..``), a link leaving it (relative or absolute target), a device or FIFO refuses the tree (``tree_unsafe``), as
does an unreadable archive (``tree_unreadable``). A leading ``/`` of a member name is dropped (the filter's rule),
so an absolute name lands inside the directory. Modes are the filter's (no setuid, setgid or sticky bit; the
execute bits kept). A refused tree may be partly written; the caller drops the directory.

Who writes ``pulled``: ``loop.cek.assemble``, called by the ``cek`` job once D1's checks before it hold
(``loop.job``). Out of scope, stated: whether ``state/`` holds what D1 verified (the ``cek`` job's tests: this
module only carries bytes), and a size bound on the archive (the artifact's own size and the job's disk and wall
clock bound it).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tarfile
from typing import Any, NamedTuple

import cli
from profile import derive as D
from runner import kos as K
from target import branches as B

SCHEMA = "snowball-pulled/1"
MANIFEST = "pulled.json"
TREE = "tree.tar"
UNITS = "units.json"
POLICY = "policy.json"
STATE_DIR = "state"
HEADS = STATE_DIR + "/heads.json"
def _carried(path: str) -> str:
    """Where the artifact carries ``brain/state``'s file ``path``: under ``state/``, by its name under the state
    directory (``target.branches.state_name``)."""
    return "%s/%s" % (STATE_DIR, B.state_name(path))


STATE_FILES = (HEADS,) + tuple(_carried(p) for p in B.STATE_CHAINS)
STATUS = _carried(B.STATE_STATUS)
HEAD_BRANCHES = (B.STATE, B.INTEGRATION)
TOP = (TREE, UNITS, POLICY) + STATE_FILES   # always listed
LAYOUT = TOP + (STATUS,)                     # STATUS listed when the head has a status.md
SHA40 = re.compile(r"[0-9a-f]{40}\Z")
CANDIDATES = "candidates"
CANDIDATE_FILES = ("diff.patch", "expect.json", "finding.json")
HEX64 = re.compile(r"[0-9a-f]{64}\Z")
SERVED = "served.json"
SERVED_SCHEMA = "snowball-served/1"


class PulledError(ValueError):
    """The artifact is not a ``pulled`` artifact; ``reasons`` lists why."""

    def __init__(self, reasons: list[str]) -> None:
        super().__init__(", ".join(reasons))
        self.reasons = reasons


class Pulled(NamedTuple):
    target: dict
    units: Any
    policy: Any
    tree_tar: str                           # the path of tree.tar inside the artifact
    candidates: dict[str, dict[str, bytes]]  # cid -> {file name: bytes}
    heads: dict[str, str]                   # brain/state and brain/integration -> commit
    state: dict[str, bytes]                 # target.branches.STATE_CHAINS path -> bytes
    policy_bytes: bytes                     # policy.json as carried (``policy`` is it parsed)
    status: bytes | None                    # brain/state's status.md, None when the head has none


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _dump(obj: Any) -> bytes:
    return (json.dumps(obj, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _candidate_of(path: str) -> str | None:
    """The cid of a candidate file's path in the layout, else None."""
    parts = path.split("/")
    if len(parts) == 3 and parts[0] == CANDIDATES and K.CANDIDATE_ID.fullmatch(parts[1]) \
            and parts[2] in CANDIDATE_FILES:
        return parts[1]
    return None


def write(out: str, target: dict, tree_tar: bytes, units: bytes, policy: bytes,
          candidates: dict[str, dict[str, bytes]], heads: dict[str, str], state: dict[str, bytes],
          status: bytes | None) -> dict:
    """Write the layout into ``out`` (which must not exist); returns the manifest. ``state`` maps each path of
    ``STATE_CHAINS`` to its bytes; ``status`` is ``status.md``'s bytes or ``None`` (not written)."""
    if sorted(state) != sorted(B.STATE_CHAINS) or not all(isinstance(d, bytes) for d in state.values()) \
            or not (status is None or isinstance(status, bytes)):
        raise PulledError(["state_incomplete"])
    if not _heads_valid(heads, state, status):
        raise PulledError(["heads_invalid"])
    files = {TREE: tree_tar, UNITS: units, POLICY: policy, HEADS: _dump(heads)}
    files.update({_carried(p): d for p, d in state.items()})
    if status is not None:
        files[STATUS] = status
    for cid, content in candidates.items():
        if sorted(content) != sorted(CANDIDATE_FILES):
            raise PulledError(["candidate_incomplete:%s" % cid])
        for name, data in content.items():
            files["%s/%s/%s" % (CANDIDATES, cid, name)] = data
    bad = [p for p in files if p not in LAYOUT and _candidate_of(p) is None]
    if bad:
        raise PulledError(["path_not_in_layout:%s" % p for p in sorted(bad)])
    os.makedirs(out)
    for path, data in sorted(files.items()):
        full = os.path.join(out, *path.split("/"))
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "xb") as fh:
            fh.write(data)
    manifest = {"schema": SCHEMA, "target": target, "files": {p: _sha(d) for p, d in sorted(files.items())}}
    with open(os.path.join(out, MANIFEST), "xb") as fh:
        fh.write(_dump(manifest))
    return manifest


def write_served(root: str, ids: list[str]) -> None:
    """``served.json`` in ``root``, the ``cek`` job's ``out/pulled`` (see "Served" above)."""
    with open(os.path.join(root, SERVED), "xb") as fh:
        fh.write(_dump({"schema": SERVED_SCHEMA, "targets": list(ids)}))


def served(root: str) -> list[str]:
    """The targets ``root`` (a downloaded ``pulled``) serves, in order (see "Served" above); ``PulledError`` with
    every reason."""
    raw = D._read_regular(root, SERVED) if os.path.isdir(root) and not os.path.islink(root) else None
    try:
        doc = cli.loads(raw.decode("utf-8")) if raw is not None else None
    except (UnicodeDecodeError, ValueError, RecursionError):
        doc = None
    if not (isinstance(doc, dict) and set(doc) == {"schema", "targets"} and doc["schema"] == SERVED_SCHEMA
            and isinstance(doc["targets"], list)
            and all(isinstance(t, str) and K.CANDIDATE_ID.fullmatch(t) for t in doc["targets"])
            and len(set(doc["targets"])) == len(doc["targets"])):
        raise PulledError(["served_unreadable"])
    ids = doc["targets"]
    entries = set(os.listdir(root)) - {SERVED}
    reasons = ["served_missing:%s" % t for t in ids
               if t not in entries or os.path.islink(os.path.join(root, t)) or not os.path.isdir(os.path.join(root, t))]
    reasons += ["unlisted:%s" % n for n in sorted(entries - set(ids))]
    if reasons:
        raise PulledError(reasons)
    return ids


def _heads_valid(heads: Any, state: dict[str, bytes], status: bytes | None) -> bool:
    """``heads`` names both heads, each 40 lowercase hex, except the genesis cycle's ``brain/state`` ``null`` with
    empty chains and no ``status.md`` (see "The genesis cycle")."""
    if not (isinstance(heads, dict) and sorted(heads) == sorted(HEAD_BRANCHES)):
        return False
    shas = [heads[B.INTEGRATION]] + ([] if heads[B.STATE] is None else [heads[B.STATE]])
    if not all(isinstance(v, str) and SHA40.fullmatch(v) for v in shas):
        return False
    return heads[B.STATE] is not None or (status is None and not any(state.values()))


def genesis(art: Pulled) -> bool:
    """Whether ``art`` is a genesis cycle's (see "The genesis cycle"): ``read`` checked its form."""
    return art.heads[B.STATE] is None


def _present(root: str) -> list[str]:
    """Every non-directory entry under ``root`` (relative, ``/``-separated), and every empty directory."""
    found = []
    for dirpath, dirnames, filenames in os.walk(root):
        rel = os.path.relpath(dirpath, root)
        prefix = "" if rel == "." else rel.replace(os.sep, "/") + "/"
        for name in list(dirnames):
            if os.path.islink(os.path.join(dirpath, name)):
                dirnames.remove(name)
                filenames.append(name)
        found += [prefix + n for n in filenames]
        if not dirnames and not filenames and prefix:
            found.append(prefix.rstrip("/") + "/")
    return found


def read(root: str) -> Pulled:
    """Check the artifact in ``root`` against its manifest; ``PulledError`` with every reason, else the content."""
    raw = D._read_regular(root, MANIFEST) if os.path.isdir(root) else None
    try:
        manifest = cli.loads(raw.decode("utf-8")) if raw is not None else None
    except (UnicodeDecodeError, ValueError, RecursionError):
        manifest = None
    if not (isinstance(manifest, dict) and set(manifest) == {"schema", "target", "files"}):
        raise PulledError(["manifest_unreadable"])
    reasons = []
    if manifest["schema"] != SCHEMA:
        reasons.append("schema_unknown")
    target = manifest["target"]
    if not (isinstance(target, dict) and isinstance(target.get("id"), str) and target["id"]):
        reasons.append("target_invalid")
    files = manifest["files"]
    if not (isinstance(files, dict) and all(isinstance(v, str) and HEX64.fullmatch(v) for v in files.values())):
        raise PulledError(reasons + ["files_invalid"])
    candidates: dict[str, dict[str, bytes]] = {}
    contents: dict[str, bytes] = {}
    for path in sorted(files):
        cid = _candidate_of(path)
        if path not in LAYOUT and cid is None:
            reasons.append("path_not_in_layout:%s" % path)
            continue
        data = D._read_regular(root, path)
        if data is None:
            reasons.append("file_missing:%s" % path)
        elif _sha(data) != files[path]:
            reasons.append("hash_mismatch:%s" % path)
        elif cid is None:
            contents[path] = data
        else:
            candidates.setdefault(cid, {})[path.rsplit("/", 1)[1]] = data
    reasons += ["missing:%s" % p for p in TOP if p not in files]
    listed_cids = sorted({c for c in map(_candidate_of, files) if c is not None})
    reasons += ["candidate_incomplete:%s" % c for c in listed_cids
                if sorted(p.rsplit("/", 1)[1] for p in files if _candidate_of(p) == c) != sorted(CANDIDATE_FILES)]
    reasons += ["unlisted:%s" % p for p in sorted(_present(root)) if p != MANIFEST and p not in files]
    parsed = {}
    for path in (UNITS, POLICY, HEADS):
        if path in contents:
            try:
                parsed[path] = cli.loads(contents[path].decode("utf-8"))
            except (UnicodeDecodeError, ValueError, RecursionError):
                reasons.append("json_unreadable:%s" % path)
    state = {p: contents.get(_carried(p), b"") for p in B.STATE_CHAINS}
    if HEADS in parsed and not _heads_valid(parsed[HEADS], state, contents.get(STATUS)):
        reasons.append("heads_invalid")
    if reasons:
        raise PulledError(reasons)
    return Pulled(target, parsed[UNITS], parsed[POLICY], os.path.join(root, TREE), candidates, parsed[HEADS], state,
                  contents[POLICY], contents.get(STATUS))


def extract_tree(tar_path: str, dest: str) -> None:
    """Unpack ``tree.tar`` into ``dest`` (must not exist) with ``tarfile``'s ``data`` filter; ``PulledError``."""
    if os.path.lexists(dest):
        raise PulledError(["tree_dest_exists"])
    os.makedirs(dest)
    try:
        with tarfile.open(tar_path, "r:") as tar:
            tar.extractall(dest, filter="data")
    except tarfile.FilterError:
        raise PulledError(["tree_unsafe"]) from None
    except (*cli.ARCHIVE_ERRORS, OSError):
        raise PulledError(["tree_unreadable"]) from None
