"""The Rekor entry of a cycle's root, read and verified by the next cycle's D1 (``çek``; stage 0, MF11's verify).

Rules: asama-0/14 row 11 (``rekor.anchor``: the root signed with Sigstore, the next D1 verifies it), tohum/13 ("Kök ve
dış günlük": the root is written to Sigstore Rekor; a branch tip that does not match the root in Rekor is tamper
evidence), tohum/01a (``yaz`` holds the Sigstore OIDC identity), tohum/26d "Kök" (the record's ``spec.data.hash`` is
the root itself, not a digest of it), ``ledger.anchor`` (the root, the root row, the payload: the root's preimage,
whose sha256 the root is; ``judge``: the order of the reasons).

**Reading** (``RekorHttp.entry``): ``GET https://rekor.sigstore.dev/api/v1/log/entries/<uuid>``, no header, no body,
no token; 404 is ``None`` (no entry). The uuid must be 64 lowercase hex characters (the entry's leaf hash) or 80
(a tree id of 16 and the leaf hash); any other value names no entry and is ``None`` without a request. Any other
failure, an answer over ``MAX_ANSWER`` bytes, or an answer that is not one JSON object with exactly one key, that
key a uuid whose last 64 characters are the requested one's and the RFC 6962 leaf hash of its ``body`` (``sha256(0x00
|| body)``), is ``RekorError`` (no verdict): an answer is never taken for an entry it is not.

**Judging** (``entry_reasons``, the ``entry_reasons`` of ``ledger.anchor.judge``), for the recorded root ``r``:

- ``entry_root_mismatch``: the entry's body is not a ``hashedrekord`` ``0.0.1`` whose ``spec.data.hash`` is
  ``sha256`` with the value ``r`` (a body that does not decode is one too: it records no root; so is a body that
  records ``sha256`` of ``r``'s text: a digest of the root is not the root);
- ``entry_unverified``: the bundle (``bundle``) cannot be made from the entry, or ``sigstore verify identity
  --bundle <it> --cert-identity <pin> --cert-oidc-issuer https://token.actions.githubusercontent.com
  sha256:<r>`` (``loop.accepted.identity_argv``, the form the bootstrap state's check runs) exits non-zero.
  ``sigstore`` judges the signature, the certificate's chain and validity, its identity and issuer, the signed entry
  timestamp and the inclusion proof; it reports one verdict, so the recorded entries' ``identity_mismatch``
  (``ledger.anchor.verify``) is not told apart from the others here.

**The bundle** (``bundle``) is a Sigstore bundle v0.3 made only of the entry: the certificate (the body's
``publicKey``, one PEM certificate, as DER), the tlog entry (``logIndex``, ``logID``, the body's kind and version,
``integratedTime``, ``verification.signedEntryTimestamp``, ``verification.inclusionProof`` with its checkpoint, the
body itself) and the message signature (the body's digest and signature). ``tests/fixtures/rekor-entry.json`` holds
a real entry, the bundle its signer published and real ``sigstore`` 4.5.1's exit codes on the bundle made here.

The ``sigstore`` program is the caller's argv prefix (``loop.inputs.sigstore`` in ``cek``, tohum/29s).

Out of scope, stated: the trust root the program fetches; whether a newer root than the recorded one is in Rekor (a ``brain/state`` reset to an earlier, valid
cycle: the ruleset's ``non_fast_forward`` on an open target, tohum/13); the identity pin's source (the referee
repository's ``loop.yml`` on ``main``, the job's own ``GITHUB_REPOSITORY``: no seed page this clone has names the
pin, an assumption); the Rekor instance (the public one).
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
import re
import tempfile
import urllib.error
import urllib.request
from typing import Any, Callable, Sequence

import cli
from loop import accepted as A

REKOR = "https://rekor.sigstore.dev/api/v1/log/entries/"
UUID = re.compile(r"(?:[0-9a-f]{16})?[0-9a-f]{64}")
MAX_ANSWER = 1024 * 1024
MEDIA_TYPE = "application/vnd.dev.sigstore.bundle.v0.3+json"
PEM = re.compile(r"-----BEGIN CERTIFICATE-----\n([A-Za-z0-9+/=\n]+?)\n?-----END CERTIFICATE-----\n?")


class RekorError(Exception):
    """Rekor could not be read, or answered with something that is not the requested entry: no verdict."""


def _leaf(body: str) -> str:
    try:
        return hashlib.sha256(b"\x00" + base64.b64decode(body, validate=True)).hexdigest()
    except (binascii.Error, ValueError):
        return ""


def checked_answer(uuid: str, answer: Any) -> dict:
    """The entry of a Rekor answer to ``GET .../entries/<uuid>``, by the reading rules above; ``RekorError``."""
    if not (isinstance(answer, dict) and len(answer) == 1):
        raise RekorError("rekor answer is not one entry")
    (key, entry), = answer.items()
    if not (isinstance(key, str) and UUID.fullmatch(key) and key[-64:] == uuid[-64:] and isinstance(entry, dict)
            and isinstance(entry.get("body"), str) and _leaf(entry["body"]) == uuid[-64:]):
        raise RekorError("rekor answer is not the entry %s" % uuid)
    return entry


class RekorHttp:
    """``entry(uuid)``: the public Rekor's entry, ``None`` when it has none (the rules above)."""

    def __init__(self, timeout: float = 60.0, handlers: tuple = ()):
        self.timeout = timeout
        self.opener = urllib.request.build_opener(*handlers)

    def entry(self, uuid: str) -> dict | None:
        if not (isinstance(uuid, str) and UUID.fullmatch(uuid)):
            return None
        try:
            with self.opener.open(urllib.request.Request(REKOR + uuid), timeout=self.timeout) as resp:
                data = resp.read(MAX_ANSWER + 1)
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None
            raise RekorError("rekor: HTTP %d" % exc.code) from None
        except (urllib.error.URLError, OSError) as exc:
            raise RekorError("rekor unreadable: %s" % type(exc).__name__) from None
        if len(data) > MAX_ANSWER:
            raise RekorError("rekor answer too large")
        try:
            answer = cli.loads(data)
        except (ValueError, RecursionError):
            raise RekorError("rekor answer is not JSON") from None
        return checked_answer(uuid, answer)


def body_of(entry: dict) -> dict | None:
    """The entry's body as a ``hashedrekord`` ``0.0.1`` object with a ``sha256`` digest, else ``None``."""
    try:
        body = cli.loads(base64.b64decode(entry["body"], validate=True))
    except (binascii.Error, ValueError, RecursionError, KeyError, TypeError):
        return None
    if not isinstance(body, dict):
        return None
    spec = body.get("spec")
    data = spec.get("data") if isinstance(spec, dict) else None
    digest = data.get("hash") if isinstance(data, dict) else None
    if not (body.get("kind") == "hashedrekord" and body.get("apiVersion") == "0.0.1" and isinstance(digest, dict)
            and digest.get("algorithm") == "sha256" and isinstance(digest.get("value"), str)):
        return None
    return body


def _b64_of_hex(value: Any) -> str:
    if not (isinstance(value, str) and re.fullmatch(r"(?:[0-9a-f]{2})+", value)):
        raise ValueError("not hex")
    return base64.b64encode(bytes.fromhex(value)).decode("ascii")


def _int_text(value: Any) -> str:
    if type(value) is not int or value < 0:
        raise ValueError("not a count")
    return str(value)


def bundle(entry: dict, body: dict) -> dict:
    """The Sigstore bundle v0.3 of a ``hashedrekord`` entry (the rules above); ``ValueError`` when a piece is
    missing or of another form."""
    try:
        signature = body["spec"]["signature"]
        pem = base64.b64decode(signature["publicKey"]["content"], validate=True).decode("ascii")
        cert = PEM.fullmatch(pem)
        if cert is None:
            raise ValueError("not one certificate")
        der = base64.b64decode(cert.group(1).replace("\n", ""), validate=True)
        proof = entry["verification"]["inclusionProof"]
        set_ = entry["verification"]["signedEntryTimestamp"]
        sig = signature["content"]
        if not all(isinstance(v, str) and v for v in (set_, sig, proof["checkpoint"])) \
                or not isinstance(proof["hashes"], list):
            raise ValueError("not text")
        return {
            "mediaType": MEDIA_TYPE,
            "verificationMaterial": {
                "certificate": {"rawBytes": base64.b64encode(der).decode("ascii")},
                "tlogEntries": [{
                    "logIndex": _int_text(entry["logIndex"]),
                    "logId": {"keyId": _b64_of_hex(entry["logID"])},
                    "kindVersion": {"kind": body["kind"], "version": body["apiVersion"]},
                    "integratedTime": _int_text(entry["integratedTime"]),
                    "inclusionPromise": {"signedEntryTimestamp": set_},
                    "inclusionProof": {
                        "logIndex": _int_text(proof["logIndex"]),
                        "rootHash": _b64_of_hex(proof["rootHash"]),
                        "treeSize": _int_text(proof["treeSize"]),
                        "hashes": [_b64_of_hex(h) for h in proof["hashes"]],
                        "checkpoint": {"envelope": proof["checkpoint"]},
                    },
                    "canonicalizedBody": entry["body"],
                }],
            },
            "messageSignature": {
                "messageDigest": {"algorithm": "SHA2_256", "digest": _b64_of_hex(body["spec"]["data"]["hash"]["value"])},
                "signature": sig,
            },
        }
    except (KeyError, TypeError, AttributeError, binascii.Error, UnicodeDecodeError) as exc:
        raise ValueError("entry lacks a bundle piece: %s" % type(exc).__name__) from None


def entry_reasons(read: Callable[[str], dict | None], pin: str, sigstore: Sequence[str],
                  verifier: Callable[[list[str]], int] = A.run_verifier) -> Callable[[str, str], list[str] | None]:
    """``ledger.anchor.judge``'s entry judgement over Rekor (``read``: ``RekorHttp().entry`` or a fake), by the
    judging rules above."""

    def judge(uuid: str, root: str) -> list[str] | None:
        entry = read(uuid)
        if entry is None:
            return None
        body = body_of(entry)
        if body is None or body["spec"]["data"]["hash"]["value"] != root:
            return ["entry_root_mismatch"]
        try:
            made = bundle(entry, body)
        except ValueError:
            return ["entry_unverified"]
        with tempfile.TemporaryDirectory(prefix="rekor-entry-") as tmp:
            path = os.path.join(tmp, "entry.sigstore.json")
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(made, fh)
            code = verifier(A.identity_argv(sigstore, path, pin, "sha256:" + root))
        return [] if code == 0 else ["entry_unverified"]
    return judge
