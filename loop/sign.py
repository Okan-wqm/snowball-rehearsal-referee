"""The cycle root's real signer: ``sigstore sign`` in ``yaz`` (D6; stage 0, MF11's signature, the counterpart of
``ledger.anchor.FakeSigner``).

Rules: asama-0/14 row 11 (the root is signed with Sigstore, the next D1 verifies it), tohum/01a (``yaz`` holds the
Sigstore OIDC identity), tohum/13 (a root that cannot be written to Rekor is a hard stop), ``ledger.anchor`` (the
signer's contract: ``sign(payload) -> {uuid, identity, bundle}``, or ``Unsignable``; the payload is the root's
preimage, so ``sha256(payload)`` is the root), ``loop.rekor`` (how the next D1 reads and judges the entry: through
Rekor's v1 API, a ``hashedrekord`` ``0.0.1`` body, the uuid as its leaf hash), tohum/26d "Kök" (the record's
``spec.data.hash`` is the root itself; ``sign`` takes files only, so the file signed is the preimage) and "Yer" (the
bundle is kept in ``brain/state``'s commit beside the root row: ``ledger.cycle`` puts the bytes answered here there).

``SigstoreSigner(pin).sign(payload)``, in a fresh directory:

1. writes ``payload`` to a file and runs ``sigstore sign --rekor-version 1 --bundle <bundle> <file>``
   (``sign_argv``). ``sigstore`` 4.5.1 otherwise logs to the highest Rekor version its trust root offers, whose
   entries the v1 API does not serve, so the next D1 would find no entry. The OIDC token is the ambient one of
   the job (GitHub Actions' ``id-token``); this module passes none;
2. reads the bundle (at most ``loop.rekor.MAX_ANSWER`` bytes, one JSON object) and its one ``tlogEntries`` entry;
   its ``canonicalizedBody`` must be what ``loop.rekor.body_of`` accepts and record ``sha256(payload)``;
3. runs ``sigstore verify identity`` of that bundle against the payload file with ``pin`` and GitHub Actions'
   issuer (``loop.accepted.identity_argv``, the form both of the loop's Sigstore checks run): the entry was signed
   by the identity the next D1 will pin, not merely by whichever token the job had;
4. answers ``{uuid: the leaf hash of the body (64 hex, loop.rekor), identity: pin, bundle: the bundle file's bytes
   as ``sigstore`` wrote them}``: the bytes step 2 read and step 3 verified, read once.

A non-zero exit or a program that cannot start at 1 or 3, a missing, oversized or unreadable bundle, a bundle
without exactly one tlog entry, or a body of another kind, version or digest is ``ledger.anchor.Unsignable`` (a hard
stop: nothing is written). ``tests/fixtures/rekor-entry.json`` ``published`` is a real bundle of ``sigstore sign``
and ``tests/fixtures/sigstore-signed-payload`` the file it signed; real ``sigstore`` 4.5.1's exits on them are
recorded in ``tests/test_sign.py``.

The program is the caller's ``sigstore`` argv prefix: in ``yaz``, the one the ``sigstore`` step installs
(``loop.inputs.sigstore``, tohum/29s: ``sigstore==4.5.0``). The recorded exits above are 4.5.1's, the version the
fixtures were captured with; no exit of 4.5.0 on them is recorded here.

Out of scope, stated: whether the entry is
in Rekor's log beyond what ``sigstore verify identity`` checks of the bundle (the next D1 reads it from Rekor);
the pin's source (``loop.accepted.workflow_identity`` of the referee repository's ``loop.yml``, the caller's).
"""

from __future__ import annotations

import hashlib
import os
import tempfile
from typing import Callable, Sequence

import cli
from ledger.anchor import Unsignable
from loop import accepted as A
from loop import rekor as R

PAYLOAD = "root"
BUNDLE = "root.sigstore.json"


def sign_argv(sigstore: Sequence[str], bundle: str, payload: str) -> list[str]:
    return [*sigstore, "sign", "--rekor-version", "1", "--bundle", bundle, payload]


def _bundle_body(path: str, digest: str) -> tuple[bytes, str]:
    """The bundle's bytes and its one ``canonicalizedBody``, checked by the rules above; ``Unsignable``."""
    try:
        with open(path, "rb") as fh:
            data = fh.read(R.MAX_ANSWER + 1)
    except OSError:
        raise Unsignable("sigstore wrote no bundle") from None
    if len(data) > R.MAX_ANSWER:
        raise Unsignable("bundle too large")
    try:
        made = cli.loads(data)
        entries = made["verificationMaterial"]["tlogEntries"]
        body = entries[0]["canonicalizedBody"] if isinstance(entries, list) and len(entries) == 1 else None
    except (ValueError, RecursionError, KeyError, TypeError, IndexError):
        raise Unsignable("bundle unreadable") from None
    record = R.body_of({"body": body}) if isinstance(body, str) else None
    if record is None or record["spec"]["data"]["hash"]["value"] != digest:
        raise Unsignable("bundle records no hashedrekord 0.0.1 of the payload")
    return data, body


class SigstoreSigner:
    """``sign(payload) -> {uuid, identity, bundle}`` by the rules above; ``run(argv) -> exit code``."""

    def __init__(self, pin: str, sigstore: Sequence[str], run: Callable[[list[str]], int] = A.run_verifier):
        if not isinstance(pin, str) or not pin:
            raise ValueError("identity pin must be a non-empty string")
        self.pin, self.sigstore, self.run = pin, sigstore, run

    def sign(self, payload: bytes) -> dict:
        digest = hashlib.sha256(payload).hexdigest()
        with tempfile.TemporaryDirectory(prefix="root-sign-") as tmp:
            path, bundle = os.path.join(tmp, PAYLOAD), os.path.join(tmp, BUNDLE)
            with open(path, "wb") as fh:
                fh.write(payload)
            if self.run(sign_argv(self.sigstore, bundle, path)) != 0:
                raise Unsignable("sigstore sign failed")
            data, body = _bundle_body(bundle, digest)
            if self.run(A.identity_argv(self.sigstore, bundle, self.pin, path)) != 0:
                raise Unsignable("the bundle is not verified for the pinned identity")
        return {"uuid": R._leaf(body), "identity": self.pin, "bundle": data}
