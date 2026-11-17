"""``rekor.anchor``: the cycle's root, its signature, and the next D1's check of it (stage 0, MF11).

Rules: asama-0/14 row 11, asama-0/09 test 40, tohum/29j (group ``root``), tohum/13 (root and external log; a
chain break or a root that cannot be written to Rekor is a hard stop), tohum/26 (part -> file; roots in
``chain/root.jsonl``), tohum/27a (``chain/root.jsonl`` rows), tohum/28 (hard stop).

- **Root** (``tips``, ``root_of``): the ledger must be a valid chain (``ledger.chain.verify_bytes``, the one
  verifier) and every row must carry a non-empty string ``part``; otherwise ``Unusable``. ``tips`` maps each part
  that has a row to the stored ``row_hash`` of that part's last row in file order; ``root`` is the lowercase hex
  sha256 of the RFC 8785 bytes of ``tips`` (``ledger.chain.canonical``). An empty ledger has no tip and is
  ``Unusable``: there is nothing to anchor.
- **Anchor** (``anchor``): the signer signs the tips' RFC 8785 bytes (``preimage``), the bytes whose sha256 the
  root is, so the hash of the signed data is the root itself and not a digest of it (tohum/26d "Kök": the Rekor
  record's ``spec.data.hash`` is the root). It answers ``{uuid, identity, bundle}``, ``bundle`` the bytes of the
  Sigstore bundle it made (non-empty); ``anchor`` returns the entry ``{uuid, hash: root, identity}`` and the bundle,
  which the cycle keeps beside the root row (``ledger.cycle``, tohum/26d "Yer"). A signer that cannot sign raises
  ``Unsignable``, which is a ``HardStop``: no entry, nothing written; an answer without one of the three is
  ``Unsignable`` too. ``FakeSigner`` here stands in for a verified Sigstore bundle (asama-0/14 "Kum", tohum/29j)
  and does no cryptography: its bundle is a JSON line naming what it was asked to sign, no Sigstore bundle. The
  real signer is ``loop.sign.SigstoreSigner`` (``sigstore sign`` in ``yaz``); the seed's pins are not part of this
  module (asama-0/10a #kok). The command ``anchor`` below has a root and no tips: its stand-in signer is asked
  for its answer alone (``FakeSigner.answer``, ``entry_of``), nothing is signed and no bundle is made.
- **Verify** (``verify``, the next cycle's D1): reads the ledger's root, only the last line of
  ``chain/root.jsonl`` (``root`` 64 lowercase hex, ``rekor_uuid`` a non-empty string) and the recorded Rekor
  entries ``{entries: {uuid: {hash, identity}}}``. Reasons, in this order: ``root_mismatch`` (the ledger's root
  is not the recorded root); ``entry_missing`` (no entry under ``rekor_uuid``; then the other two are not
  judged); ``entry_root_mismatch`` (the entry's ``hash`` is not the recorded root); ``identity_mismatch`` (the
  entry's ``identity`` is not the pin). Valid only with no reason. Not judged here: the chain of
  ``chain/root.jsonl`` itself (``ledger.chain verify`` reads it, tohum/27a) and how the entries were fetched
  from Rekor. The order and the root rule are ``judge``'s, which the next cycle's D1 calls with the entry it reads
  from Rekor itself (``loop.rekor``: there the entry's hash and identity are judged by ``sigstore``).
- **The root row** (``root_row``): one chained row ``{row_id, ts, root, rekor_uuid, prev_hash, row_hash}`` appended
  to ``chain/root.jsonl``; ``root_row_reasons`` refuses a repeated or empty ``row_id`` and an empty ``ts``. The
  cycle that signs the new ledger's root and commits both files with ``status.md`` in the cycle's one
  ``brain/state`` commit is ``ledger.cycle`` (calls 10 -> 11, 16). Writing the hard-stop row itself (tohum/28) is
  the caller's.

Command line (tohum/29j), run from ``referee/``, one JSON line on stdout, the cause on stderr::

    python -m ledger.anchor root LEDGER                  -> {tips, root}                       exit 0
    python -m ledger.anchor anchor SIGNER  stdin {"root"} -> {ok, hard_stop, entry}             exit 0, 1 unsignable
    python -m ledger.anchor verify LEDGER ROOTS REKOR  stdin {"identity"} -> {valid, reasons}   exit 0 valid, 1 not
    exit 2 in all three: unusable input (the line then carries null or empty fields).

The stdin requests take exactly the named key. ``SIGNER`` ``{available, identity, uuid}``: ``available`` a
boolean; when true, ``identity`` and ``uuid`` non-empty strings. Other keys of the signer file, of the Rekor
record and of its entries are records of an outside system and are ignored.
"""

from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import dataclass, field
from typing import Any, Callable

from ledger import append, chain
from target import branches
import cli

LEDGER_PATH = branches.STATE_LEDGER
ROOTS_PATH = branches.STATE_ROOTS
bundle_path = branches.state_bundle
REASONS = ("root_mismatch", "entry_missing", "entry_root_mismatch", "identity_mismatch")


class Unusable(ValueError):
    pass


class Unsignable(append.HardStop):
    """The root cannot be signed: a hard stop (tohum/13, tohum/28), nothing is written."""


# ---------------------------------------------------------------- root

def tips(ledger: bytes) -> dict[str, str]:
    verdict = chain.verify_bytes(ledger)
    if not verdict["valid"]:
        raise Unusable("ledger is not a valid chain: %s (%s)" % (verdict["reason"], verdict["broken_row"]))
    out: dict[str, str] = {}
    for lineno, line in enumerate(chain._lines(ledger), 1):
        row = chain.parse_row(line.decode("utf-8"))
        part = row.get("part")
        if not isinstance(part, str) or not part:
            raise Unusable("line %d has no part" % lineno)
        out[part] = row["row_hash"]
    if not out:
        raise Unusable("empty ledger: no tip to anchor")
    return out


def preimage(tip_map: dict[str, str]) -> bytes:
    """The bytes the root is the sha256 of, and the payload the signer signs: the tips' RFC 8785 form."""
    return chain.canonical(tip_map)


def root_of(tip_map: dict[str, str]) -> str:
    return hashlib.sha256(preimage(tip_map)).hexdigest()


# ---------------------------------------------------------------- signing

@dataclass
class FakeSigner:
    """``{available, identity, uuid}``: answers with its uuid and identity, or cannot sign. Keeps the payloads; its
    ``bundle`` names the payload's sha256 and is no Sigstore bundle."""

    available: bool
    identity: str | None = None
    uuid: str | None = None
    payloads: list[bytes] = field(default_factory=list)

    @classmethod
    def from_json(cls, obj: Any) -> "FakeSigner":
        if not isinstance(obj, dict) or type(obj.get("available")) is not bool:
            raise Unusable("signer: available must be a boolean")
        if obj["available"]:
            for key in ("identity", "uuid"):
                if not isinstance(obj.get(key), str) or not obj[key]:
                    raise Unusable("signer: %s must be a non-empty string" % key)
        return cls(obj["available"], obj.get("identity"), obj.get("uuid"))

    def answer(self) -> dict:
        if not self.available:
            raise Unsignable("signer unavailable")
        return {"uuid": self.uuid, "identity": self.identity}

    def sign(self, payload: bytes) -> dict:
        answer = self.answer()
        self.payloads.append(payload)
        named = dict(answer, fake_signed_sha256=hashlib.sha256(payload).hexdigest())
        return dict(answer, bundle=chain.canonical(named) + b"\n")


def _root_text(value: Any) -> str:
    if not isinstance(value, str) or not chain.HEX64.match(value):
        raise Unusable("root must be 64 lowercase hex characters")
    return value


def entry_of(root: str, answer: Any) -> dict:
    """The entry ``{uuid, hash, identity}`` of ``root`` from a signer's answer; ``Unsignable`` without both names."""
    root = _root_text(root)
    if not isinstance(answer, dict) or not all(isinstance(answer.get(k), str) and answer[k] for k in ("uuid", "identity")):
        raise Unsignable("signer gave no entry")
    return {"uuid": answer["uuid"], "hash": root, "identity": answer["identity"]}


def anchor(tip_map: dict[str, str], signer: Any) -> tuple[dict, bytes]:
    """Have ``signer`` sign the tips' ``preimage`` and return the root's entry ``{uuid, hash, identity}`` and the
    bundle's bytes; ``Unsignable`` if it cannot be signed or the answer lacks one of them."""
    answer = signer.sign(preimage(tip_map))
    entry = entry_of(root_of(tip_map), answer)
    if not isinstance(answer.get("bundle"), bytes) or not answer["bundle"]:
        raise Unsignable("signer gave no bundle")
    return entry, answer["bundle"]


# ---------------------------------------------------------------- verify (next D1)

def _last_root_row(roots: bytes) -> dict:
    lines = chain._lines(roots)
    if not lines:
        raise Unusable("root file has no row")
    try:
        row = chain.parse_row(lines[-1].decode("utf-8"))
    except (UnicodeDecodeError, chain.ChainError) as exc:
        raise Unusable("last root row: %s" % cli.cause(exc)) from None
    _root_text(row.get("root"))
    if not isinstance(row.get("rekor_uuid"), str) or not row["rekor_uuid"]:
        raise Unusable("last root row: rekor_uuid must be a non-empty string")
    return row


def _entries(rekor: Any) -> dict:
    entries = rekor.get("entries") if isinstance(rekor, dict) else None
    if not isinstance(entries, dict):
        raise Unusable("rekor record: entries must be an object")
    for uuid, entry in entries.items():
        if not isinstance(entry, dict) or not all(isinstance(entry.get(k), str) for k in ("hash", "identity")):
            raise Unusable("rekor entry %r: hash and identity must be strings" % uuid)
    return entries


def judge(ledger: bytes, roots: bytes, entry_reasons: Callable[[str, str], list[str] | None]) -> dict:
    """The root check with the Rekor entry judged by ``entry_reasons(rekor_uuid, recorded_root)``: ``None`` when
    there is no entry under the uuid, else the entry's reasons in order. ``verify`` gives it the recorded entries;
    the next cycle's D1 (``loop.rekor``) gives it the entry read from Rekor. Returns ``{valid, reasons, root,
    rekor_uuid}`` (the last root row's)."""
    current = root_of(tips(ledger))
    last = _last_root_row(roots)
    reasons = ["root_mismatch"] if current != last["root"] else []
    found = entry_reasons(last["rekor_uuid"], last["root"])
    reasons += ["entry_missing"] if found is None else found
    return {"valid": not reasons, "reasons": reasons, "root": last["root"], "rekor_uuid": last["rekor_uuid"]}


def verify(ledger: bytes, roots: bytes, rekor: Any, pin: str) -> dict:
    if not isinstance(pin, str) or not pin:
        raise Unusable("identity pin must be a non-empty string")

    def recorded(uuid: str, root: str) -> list[str] | None:
        entry = _entries(rekor).get(uuid)
        if entry is None:
            return None
        return [reason for reason, wrong in (("entry_root_mismatch", entry["hash"] != root),
                                             ("identity_mismatch", entry["identity"] != pin)) if wrong]
    found = judge(ledger, roots, recorded)
    return {"valid": found["valid"], "reasons": found["reasons"]}


# ---------------------------------------------------------------- the root row (the cycle's: ledger.cycle)

def root_row_reasons(roots: bytes, row_id: Any, ts: Any) -> list[str]:
    """Why a root row ``row_id``/``ts`` cannot be appended to ``roots``: a repeated or empty id, an empty ts."""
    old = [chain.parse_row(line.decode("utf-8")) for line in chain._lines(roots)]
    out = []
    if not isinstance(row_id, str) or not row_id or any(r.get("row_id") == row_id for r in old):
        out.append("root row_id must be a new non-empty string")
    if not isinstance(ts, str) or not ts:
        out.append("root ts must be a non-empty string")
    return out


def root_row(roots: bytes, row_id: str, ts: str, root: str, rekor_uuid: str) -> bytes:
    """``roots`` with one chained root row appended (RFC 8785 line, ``ledger.chain``)."""
    reasons = root_row_reasons(roots, row_id, ts)
    if reasons:
        raise Unusable("; ".join(reasons))
    old = [chain.parse_row(line.decode("utf-8")) for line in chain._lines(roots)]
    row = {"row_id": row_id, "ts": ts, "root": _root_text(root), "rekor_uuid": rekor_uuid,
           "prev_hash": old[-1]["row_hash"] if old else chain.ZERO_HASH}
    row["row_hash"] = chain.row_hash(row)
    joint = b"\n" if roots and not roots.endswith(b"\n") else b""
    return roots + joint + chain.canonical(row) + b"\n"


# ---------------------------------------------------------------- command line

USAGE = ("usage: python -m ledger.anchor root LEDGER | anchor SIGNER < {\"root\"} | "
         "verify LEDGER ROOTS REKOR < {\"identity\"}")
EMPTY = {"root": {"tips": None, "root": None},
         "anchor": {"ok": False, "hard_stop": False, "entry": None},
         "verify": {"valid": False, "reasons": []}}


def _read(path: str) -> bytes:
    with open(path, "rb") as fh:
        return fh.read()


def _json(data: bytes, what: str) -> Any:
    try:
        return chain.parse_row(data.decode("utf-8"))
    except (UnicodeDecodeError, chain.ChainError) as exc:
        raise Unusable("%s: %s" % (what, cli.cause(exc))) from None


def _stdin_value(key: str) -> Any:
    request = _json(sys.stdin.buffer.read(), "stdin")
    if set(request) != {key}:
        raise Unusable('stdin must be {"%s": ...} and nothing else' % key)
    return request[key]


def _emit(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj, sort_keys=True) + "\n")


def main(argv: list[str]) -> int:
    command = argv[0] if argv else ""
    try:
        if command == "root" and len(argv) == 2:
            tip_map = tips(_read(argv[1]))
            _emit({"tips": tip_map, "root": root_of(tip_map)})
            return 0
        if command == "anchor" and len(argv) == 2:
            signer = FakeSigner.from_json(_json(_read(argv[1]), "signer"))
            root = _root_text(_stdin_value("root"))
            try:
                entry = entry_of(root, signer.answer())
            except Unsignable as exc:
                sys.stderr.write("hard stop: %s\n" % cli.cause(exc))
                _emit({"ok": False, "hard_stop": True, "entry": None})
                return 1
            _emit({"ok": True, "hard_stop": False, "entry": entry})
            return 0
        if command == "verify" and len(argv) == 4:
            ledger, roots, rekor = _read(argv[1]), _read(argv[2]), _json(_read(argv[3]), "rekor record")
            result = verify(ledger, roots, rekor, _stdin_value("identity"))
            _emit(result)
            return 0 if result["valid"] else 1
        command = ""
        raise Unusable(USAGE)
    except (Unusable, OSError, UnicodeDecodeError, chain.ChainError) as exc:
        sys.stderr.write("unusable input: %s\n" % cli.cause(exc))
    _emit(EMPTY.get(command, {"error": "usage"}))
    return 2


def FAULT_LINE(argv: list[str]) -> dict:  # noqa: N802 - cli.run's fault line, by command
    return EMPTY.get(argv[0] if argv else "", {"error": "usage"})


if __name__ == "__main__":
    sys.exit(cli.run(main, sys.argv[1:], FAULT_LINE))
