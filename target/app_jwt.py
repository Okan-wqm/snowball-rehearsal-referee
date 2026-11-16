"""The writer App's JWT: the one credential GitHub answers ``GET /app`` to (stage 0, MF18's first genesis read).

Why it exists (spec/tohum/CHANGELOG.md, 2026-11-15, the operator's two API facts): ``GET /app`` is read only with
the App's JWT, an installation token is answered 401; tohum/29o lists ``GET /app`` among genesis' reads, and
``yaz``'s installation token (``loop.job``'s ``writer token`` step) is the only credential the transport had.

``token(app_id, pem, now)`` gives the compact JWS GitHub's App authentication asks for: header ``{"alg": "RS256",
"typ": "JWT"}``, claims ``{"exp": now + LIFE, "iat": now - SKEW, "iss": app_id}``, each the base64url (no padding)
of its JSON with sorted keys and no spaces, signed with RSASSA-PKCS1-v1_5 over SHA-256 (RFC 8017 section 8.2, RFC
7518 section 3.3). The signature is deterministic: equal inputs give equal bytes.

The key (``private_key``) is the PEM GitHub hands out for an App, read with the standard library alone:

- its line ends may be written as the two characters ``\\n`` (a key kept on one line): each is read as a line
  end first, as the JWT library of the token action reads the same secret (``privateKey.replace(/\\\\n/g, "\\n")``
  in universal-github-app-jwt, read in actions/create-github-app-token 64ab729a's ``dist/main.cjs``);
- one block, ``RSA PRIVATE KEY`` (PKCS#1 ``RSAPrivateKey``, the form GitHub downloads) or ``PRIVATE KEY`` (PKCS#8
  ``PrivateKeyInfo`` whose algorithm is ``rsaEncryption`` with NULL parameters, holding the same structure); text
  before or after the block, a header line inside it (an encrypted PEM has ``Proc-Type``), any other label
  (``ENCRYPTED PRIVATE KEY``, ``EC PRIVATE KEY``) and base64 outside the alphabet are refused;
- DER read strictly: definite lengths in their shortest form, each value consumed to its last byte, integers
  positive and without a needless leading zero byte, version 0 (two primes);
- the numbers must be one key: ``n == p * q``, ``p`` and ``q`` greater than 1, ``e`` odd and greater than 1,
  ``d * e == 1`` modulo ``lcm(p - 1, q - 1)``, and ``n`` of at least ``MIN_BITS`` bits (RFC 7518 section 3.3).

``sign`` computes ``em ** d mod n`` and checks ``sig ** e mod n == em`` before answering; a mismatch raises.

Refused here, though the token action's side may read it (it gives a PKCS#1 key to Node's ``createPrivateKey``,
whose PEM reader was not compared with this one), stated: a PKCS#1 block with text before or after it.

Not done here, stated: whether ``p`` and ``q`` are prime (a key of composite factors that passes the checks above
signs, and GitHub refuses what does not verify under the App's public key); constant-time arithmetic (Python's
``pow`` is not; the key signs one token per genesis cycle on a runner that is discarded, and nothing here answers
a caller who chooses the message); verifying a JWT (the tests' GitHub does, ``tests/github_auth.py``); every
algorithm but RS256. No message of ``Unusable`` holds a byte of the key or a character of the App id; the App id's
refusal names the rule it breaks (``_why_not``), so a job's line says why without showing the secret.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import math
import re

LIFE = 300      # seconds from ``now`` to ``exp``; GitHub refuses an ``exp`` more than 600 s ahead
SKEW = 60       # seconds ``iat`` is put before ``now`` (GitHub's advice for clock drift)
MIN_BITS = 2048

# the DER of DigestInfo{sha256, NULL} up to the digest (RFC 8017 section 9.2, note 1)
SHA256_PREFIX = bytes.fromhex("3031300d060960864801650304020105000420")
RSA_OID = bytes.fromhex("2a864886f70d010101")  # 1.2.840.113549.1.1.1 rsaEncryption
LABELS = ("RSA PRIVATE KEY", "PRIVATE KEY")
APP_ID = re.compile(r"[A-Za-z0-9._-]{1,64}")   # an App id (digits) or a client id (``Iv1.`` or ``Iv23`` forms)
_B64 = re.compile(r"[A-Za-z0-9+/]+={0,2}")


class Unusable(Exception):
    pass


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


# ---------------------------------------------------------------- DER

def _tlv(data: bytes, at: int, tag: int) -> tuple[bytes, int]:
    """The value of the ``tag`` element at ``at`` and the offset after it."""
    if at + 2 > len(data) or data[at] != tag:
        raise Unusable("private key: not the DER structure of an RSA key")
    size, at = data[at + 1], at + 2
    if size & 0x80:
        count = size & 0x7F
        if not 1 <= count <= 4 or at + count > len(data) or data[at] == 0:
            raise Unusable("private key: a DER length that is not in its shortest form")
        size, at = int.from_bytes(data[at:at + count], "big"), at + count
        if size < 0x80:
            raise Unusable("private key: a DER length that is not in its shortest form")
    if at + size > len(data):
        raise Unusable("private key: a DER value longer than its data")
    return data[at:at + size], at + size


def _whole(data: bytes, tag: int) -> bytes:
    value, end = _tlv(data, 0, tag)
    if end != len(data):
        raise Unusable("private key: bytes after the DER structure")
    return value


def _integer(data: bytes, at: int) -> tuple[int, int]:
    value, at = _tlv(data, at, 0x02)
    if not value or value[0] & 0x80 or (len(value) > 1 and value[0] == 0 and not value[1] & 0x80):
        raise Unusable("private key: a DER integer that is negative or not in its shortest form")
    return int.from_bytes(value, "big"), at


def _rsa_private_key(der: bytes) -> tuple[int, int, int]:
    """``(n, e, d)`` of a PKCS#1 ``RSAPrivateKey``."""
    body, at, numbers = _whole(der, 0x30), 0, []
    for _ in range(9):  # version, n, e, d, p, q, d mod (p-1), d mod (q-1), q^-1 mod p
        number, at = _integer(body, at)
        numbers.append(number)
    if at != len(body):
        raise Unusable("private key: bytes after the nine integers of an RSA key")
    version, n, e, d, p, q = numbers[:6]
    if version != 0:
        raise Unusable("private key: not a two-prime RSA key (version 0)")
    if p <= 1 or q <= 1 or n != p * q or e <= 1 or e % 2 == 0 or (d * e) % math.lcm(p - 1, q - 1) != 1:
        raise Unusable("private key: its numbers are not one RSA key")
    if n.bit_length() < MIN_BITS:
        raise Unusable("private key: a modulus under %d bits" % MIN_BITS)
    return n, e, d


def _pkcs8(der: bytes) -> bytes:
    """The ``RSAPrivateKey`` bytes inside a PKCS#8 ``PrivateKeyInfo`` of ``rsaEncryption``."""
    body = _whole(der, 0x30)
    version, at = _integer(body, 0)
    algorithm, at = _tlv(body, at, 0x30)
    oid, end = _tlv(algorithm, 0, 0x06)
    if version != 0 or oid != RSA_OID or algorithm[end:] != b"\x05\x00":
        raise Unusable("private key: PKCS#8 of another algorithm than rsaEncryption")
    inner, at = _tlv(body, at, 0x04)
    if at != len(body):
        raise Unusable("private key: PKCS#8 with attributes or a public key is not read")
    return inner


def private_key(pem: str) -> tuple[int, int, int]:
    """``(n, e, d)`` of the PEM (see the module docstring); ``Unusable`` otherwise."""
    if not isinstance(pem, str):
        raise Unusable("private key: not text")
    lines = [line.strip() for line in pem.replace("\\n", "\n").strip().splitlines()]
    for label in LABELS:
        if len(lines) >= 3 and lines[0] == "-----BEGIN %s-----" % label and lines[-1] == "-----END %s-----" % label:
            break
    else:
        raise Unusable("private key: not one PEM block of %s" % " or ".join(LABELS))
    body = "".join(lines[1:-1])
    if not _B64.fullmatch(body):
        raise Unusable("private key: the PEM body is not base64")
    try:
        der = base64.b64decode(body, validate=True)
    except (binascii.Error, ValueError):
        raise Unusable("private key: the PEM body is not base64") from None
    return _rsa_private_key(der if label == LABELS[0] else _pkcs8(der))


# ---------------------------------------------------------------- RS256

def encoded(message: bytes, size: int) -> bytes:
    """EMSA-PKCS1-v1_5 of ``message``'s SHA-256 for a modulus of ``size`` bytes (RFC 8017 section 9.2)."""
    tail = SHA256_PREFIX + hashlib.sha256(message).digest()
    return b"\x00\x01" + b"\xff" * (size - len(tail) - 3) + b"\x00" + tail


def sign(key: tuple[int, int, int], message: bytes) -> bytes:
    n, e, d = key
    size = (n.bit_length() + 7) // 8
    em = int.from_bytes(encoded(message, size), "big")
    sig = pow(em, d, n)
    if pow(sig, e, n) != em:
        raise Unusable("private key: the signature does not verify under its own public numbers")
    return sig.to_bytes(size, "big")


def _why_not(app_id: object) -> str:
    """Which rule of ``APP_ID`` the value breaks, the first of these that holds, with no character of the value."""
    if not isinstance(app_id, str):
        return "not text"
    if not app_id:
        return "empty"
    if len(app_id) > 64:
        return "longer than 64 characters"
    if any(ch.isspace() for ch in app_id):
        return "space or a line end in it"
    return "a character that is not an ASCII letter, a digit, '.', '_' or '-'"


def token(app_id: str, pem: str, now: int) -> str:
    """The App's JWT at ``now`` (seconds since the epoch); see the module docstring."""
    if not isinstance(app_id, str) or not APP_ID.fullmatch(app_id):
        raise Unusable("App id: not an App id or a client id (%s)" % _why_not(app_id))
    if type(now) is not int or now < SKEW:
        raise Unusable("now: not whole seconds since the epoch")
    key = private_key(pem)

    def part(value: dict) -> str:
        return b64url(json.dumps(value, sort_keys=True, separators=(",", ":")).encode("ascii"))

    signed = "%s.%s" % (part({"alg": "RS256", "typ": "JWT"}),
                        part({"exp": now + LIFE, "iat": now - SKEW, "iss": app_id}))
    return "%s.%s" % (signed, b64url(sign(key, signed.encode("ascii"))))
