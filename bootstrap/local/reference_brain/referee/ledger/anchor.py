"""MF11 rekor.anchor: root = canonical hash of the part tips; signing through a fake signer; the next cycle's D1
verifies (asama-0/14:38, tohum/13:47-55, tohum/26a:29).

    python -m ledger.anchor root <ledger.jsonl>                                   -> {"root", "tips"}
    python -m ledger.anchor anchor <signer.json>   (stdin: {"root": hex})         -> {"ok", "hard_stop", "entry"}
    python -m ledger.anchor verify <ledger.jsonl> <root.jsonl> <rekor.json>
                                                   (stdin: {"identity": pin})     -> {"valid", "reasons"}
"""

from __future__ import annotations

import hashlib
import json
import sys
from typing import Any, NoReturn

from ledger import _strict as chain  # A's helpers; this brain's MF1 `ledger.chain` has another interface
from ledger._strict import HEX64, Unusable


def _emit(obj: dict[str, Any], code: int) -> NoReturn:
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()
    sys.exit(code)


def _read(path: str) -> bytes:
    try:
        with open(path, "rb") as fh:
            return fh.read()
    except OSError as exc:
        raise Unusable(f"cannot read {path}") from exc


def tips_and_root(ledger_bytes: bytes) -> tuple[dict[str, str], str]:
    """tips = {part: stored row_hash of that part's last row}; root = sha256(RFC 8785 bytes of tips)."""
    _, rows = chain.read_jsonl(ledger_bytes)
    if not rows:
        raise Unusable("empty ledger: no part to anchor")
    tips: dict[str, str] = {}
    for number, row in enumerate(rows, start=1):
        part, row_hash = row.get("part"), row.get("row_hash")
        if not isinstance(part, str) or not isinstance(row_hash, str) or not HEX64.fullmatch(row_hash):
            raise Unusable(f"ledger line {number} has no part or row_hash")
        tips[part] = row_hash
    return tips, hashlib.sha256(chain.canonical(tips)).hexdigest()


def cmd_root(argv: list[str]) -> None:
    if len(argv) != 1:
        _emit({"root": None, "tips": None, "error": "usage: root <ledger.jsonl>"}, 2)
    try:
        tips, root = tips_and_root(_read(argv[0]))
    except Unusable as exc:
        _emit({"root": None, "tips": None, "error": str(exc)}, 2)
    _emit({"root": root, "tips": tips}, 0)


def cmd_anchor(argv: list[str]) -> None:
    unusable = {"ok": False, "hard_stop": True, "entry": None}
    if len(argv) != 1:
        _emit(dict(unusable, error="usage: anchor <signer.json>"), 2)
    try:
        signer = chain.loads(_read(argv[0]))
        request = chain.loads(sys.stdin.buffer.read())
        if not (isinstance(signer, dict) and isinstance(signer.get("available"), bool)
                and isinstance(signer.get("identity"), str) and isinstance(signer.get("uuid"), str)):
            raise Unusable("signer.json is not {available, identity, uuid}")
        if not (isinstance(request, dict) and isinstance(request.get("root"), str) and HEX64.fullmatch(request["root"])):
            raise Unusable("stdin is not {root: 64 lowercase hex}")
    except Unusable as exc:
        _emit(dict(unusable, error=str(exc)), 2)
    if not signer["available"]:
        _emit({"ok": False, "hard_stop": True, "entry": None}, 1)
    _emit({"ok": True, "hard_stop": False,
           "entry": {"uuid": signer["uuid"], "hash": request["root"], "identity": signer["identity"]}}, 0)


def cmd_verify(argv: list[str]) -> None:
    if len(argv) != 3:
        _emit({"valid": False, "reasons": [], "error": "usage: verify <ledger.jsonl> <root.jsonl> <rekor.json>"}, 2)
    try:
        _, root = tips_and_root(_read(argv[0]))
        _, records = chain.read_jsonl(_read(argv[1]))
        if not records:
            raise Unusable("root.jsonl has no record")
        last = records[-1]
        if not (isinstance(last.get("root"), str) and isinstance(last.get("rekor_uuid"), str)):
            raise Unusable("last root record has no root or rekor_uuid")
        log = chain.loads(_read(argv[2]))
        if not (isinstance(log, dict) and isinstance(log.get("entries"), dict)
                and all(isinstance(e, dict) and isinstance(e.get("hash"), str) and isinstance(e.get("identity"), str)
                        for e in log["entries"].values())):
            raise Unusable("rekor.json is not {entries: {uuid: {hash, identity}}}")
        pin = chain.loads(sys.stdin.buffer.read())
        if not (isinstance(pin, dict) and isinstance(pin.get("identity"), str)):
            raise Unusable("stdin is not {identity}")
    except Unusable as exc:
        _emit({"valid": False, "reasons": [], "error": str(exc)}, 2)
    reasons = []
    if root != last["root"]:
        reasons.append("root_mismatch")
    entry = log["entries"].get(last["rekor_uuid"])
    if entry is None:
        reasons.append("entry_missing")
    else:
        if entry["hash"] != last["root"]:
            reasons.append("entry_root_mismatch")
        if entry["identity"] != pin["identity"]:
            reasons.append("identity_mismatch")
    _emit({"valid": not reasons, "reasons": sorted(reasons)}, 0 if not reasons else 1)


def main(argv: list[str]) -> None:
    commands = {"root": cmd_root, "anchor": cmd_anchor, "verify": cmd_verify}
    if argv[:1] and argv[0] in commands:
        commands[argv[0]](argv[1:])
    _emit({"error": "usage: root | anchor | verify"}, 2)


if __name__ == "__main__":
    main(sys.argv[1:])
