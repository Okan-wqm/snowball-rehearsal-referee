"""The credentials side of GitHub, for tests: who may ask what (tests only; ``fake_github.FakeGitHub`` models the
routes' state and looks at no credential, this wraps it at urllib's handler level, so ``target.write.HttpTransport``
is the transport under test and the ``Authorization`` header it sends decides the answer).

What it holds as fact (spec/tohum/CHANGELOG.md, 2026-11-15, the operator's two observations on the real API):

- ``GET /app`` answers only the App's JWT; an installation token gets 401;
- ``GET /repos/{repo}/actions/permissions`` asks ``administration: read`` of the token, and a token carries only
  the permissions asked for when it was made.

What it holds from my reading of GitHub's REST documentation, not observed live by anyone here (a wrong row is this
file's error, to be corrected when a real run shows it):

- a JWT is RS256 under the App's public key, ``iss`` the App's id, ``iat`` not in the future, ``exp`` in the future
  and at most 600 s ahead; a JWT is answered on no repository route (401);
- the permission each repository route asks (``NEEDS``); ``metadata: read`` is in every token;
- ``actions/workflows`` asks ``actions: read`` on a private repository and nothing on a public one;
- a token asked for a permission the App does not hold, or a level above the App's, is not made (422);
- a repository outside the token's is 404; a route in no row of ``NEEDS`` is 403 (closed: a route the code starts
  to call must be given its row here, with its source).

Not emulated: the token's expiry, rate limits, ``/installation/repositories`` following the token's repositories
(it answers what the wrapped fake holds for it), every other App route.

``app()`` gives a test App with a real 2048-bit RSA key made here from a fixed seed (no key is a file of the
repository); its PEM text is built at run time in both forms GitHub and openssl hand out.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import random
import re
import urllib.request
import urllib.response
from email.message import Message

API = "https://api.github.com"
LEVELS = {"read": 1, "write": 2}
# tohum/25 item 6: what the writer App is installed with
APP_PERMISSIONS = {"contents": "write", "pull_requests": "write", "checks": "write", "administration": "read",
                   "metadata": "read"}

# (method, route under /repos/{repo}/) -> (permission, level); the first row that matches decides
NEEDS = [
    ("GET", r"rules/branches/.+", ("metadata", "read")),
    ("GET", r"rulesets/\d+", ("metadata", "read")),
    ("GET", r"actions/permissions", ("administration", "read")),
    ("GET", r"actions/workflows", ("actions", "read")),  # nothing on a public repository, see ``https_open``
    ("GET", r"git/ref/heads/.+", ("contents", "read")),
    ("GET", r"git/commits/[0-9a-f]+", ("contents", "read")),
    ("GET", r"pulls/\d+", ("pull_requests", "read")),
    ("POST", r"git/(refs|commits|blobs|trees)", ("contents", "write")),
    ("PATCH", r"git/refs/heads/.+", ("contents", "write")),
    ("POST", r"pulls", ("pull_requests", "write")),
    ("PUT", r"pulls/\d+/merge", ("contents", "write")),
    ("POST", r"check-runs", ("checks", "write")),
]


# ---------------------------------------------------------------- a test key

def _probable_prime(n: int, rng: random.Random) -> bool:
    if n % 2 == 0 or any(n % p == 0 for p in (3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37)):
        return False
    d, r = n - 1, 0
    while d % 2 == 0:
        d, r = d // 2, r + 1
    for _ in range(24):
        x = pow(rng.randrange(2, n - 1), d, n)
        if x in (1, n - 1):
            continue
        for _ in range(r - 1):
            x = x * x % n
            if x == n - 1:
                break
        else:
            return False
    return True


def _prime(bits: int, rng: random.Random) -> int:
    while True:
        n = rng.getrandbits(bits) | (3 << (bits - 2)) | 1  # the two top bits set: a product of 2 * bits bits
        if _probable_prime(n, rng):
            return n


_KEYS: dict[tuple, dict] = {}


def rsa(bits: int = 2048, seed: int = 20261115, e: int = 65537) -> dict:
    """The numbers of an RSA key of ``bits`` bits, the same for the same arguments (cached for the process)."""
    if (bits, seed, e) not in _KEYS:
        rng = random.Random(seed)
        while True:
            p, q = _prime(bits // 2, rng), _prime(bits - bits // 2, rng)
            if p != q and (p - 1) % e and (q - 1) % e:
                break
        d = pow(e, -1, (p - 1) * (q - 1))
        _KEYS[(bits, seed, e)] = {"n": p * q, "e": e, "d": d, "p": p, "q": q}
    return dict(_KEYS[(bits, seed, e)])


def der(tag: int, value: bytes) -> bytes:
    size = len(value)
    head = bytes([size]) if size < 0x80 else bytes([0x80 | (size.bit_length() + 7) // 8]) + \
        size.to_bytes((size.bit_length() + 7) // 8, "big")
    return bytes([tag]) + head + value


def der_int(n: int) -> bytes:
    return der(0x02, n.to_bytes(n.bit_length() // 8 + 1, "big"))


def pkcs1(key: dict, version: int = 0) -> bytes:
    p, q, d = key["p"], key["q"], key["d"]
    crt = [d % (p - 1) if p > 1 else 0, d % (q - 1) if q > 1 else 0, pow(q, -1, p)]  # p or q of 1: a test's bad key
    numbers = [version, key["n"], key["e"], d, p, q] + crt
    return der(0x30, b"".join(der_int(n) for n in numbers))


RSA_ALGORITHM = der(0x30, der(0x06, bytes([0x2A, 0x86, 0x48, 0x86, 0xF7, 0x0D, 1, 1, 1])) + der(0x05, b""))


def pkcs8(inner: bytes, algorithm: bytes = RSA_ALGORITHM) -> bytes:
    return der(0x30, der_int(0) + algorithm + der(0x04, inner))


def pem(data: bytes, label: str = "RSA PRIVATE KEY") -> str:
    body = base64.b64encode(data).decode("ascii")
    dashes = "-" * 5
    lines = ["%sBEGIN %s%s" % (dashes, label, dashes)] + [body[i:i + 64] for i in range(0, len(body), 64)] + \
        ["%sEND %s%s" % (dashes, label, dashes)]
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------- the JWT, as GitHub reads it

def _unb64url(text: str) -> bytes:
    if not re.fullmatch(r"[A-Za-z0-9_-]+", text):
        raise ValueError("not base64url")
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def jwt_claims(token: str, n: int, e: int) -> dict:
    """The claims of an RS256 JWT whose signature verifies under ``(n, e)``; ``ValueError`` otherwise. Written from
    RFC 7515 and RFC 8017 section 8.2.2, apart from ``target.app_jwt``."""
    parts = token.split(".")
    if len(parts) != 3:
        raise ValueError("not three parts")
    header = json.loads(_unb64url(parts[0]))
    if header != {"alg": "RS256", "typ": "JWT"}:
        raise ValueError("header")
    size = (n.bit_length() + 7) // 8
    signature = _unb64url(parts[2])
    if len(signature) != size:
        raise ValueError("signature length")
    digest_info = bytes([0x30, 0x31, 0x30, 0x0D, 0x06, 0x09, 0x60, 0x86, 0x48, 0x01, 0x65, 0x03, 0x04, 0x02, 0x01,
                         0x05, 0x00, 0x04, 0x20]) + hashlib.sha256((parts[0] + "." + parts[1]).encode()).digest()
    want = bytes([0, 1]) + bytes([0xFF]) * (size - len(digest_info) - 3) + bytes([0]) + digest_info
    if pow(int.from_bytes(signature, "big"), e, n).to_bytes(size, "big") != want:
        raise ValueError("signature")
    claims = json.loads(_unb64url(parts[1]))
    if not isinstance(claims, dict):
        raise ValueError("claims")
    return claims


class App:
    """A GitHub App as GitHub holds it: its id, its public key, the permissions it is installed with."""

    def __init__(self, app_id: int, key: dict, permissions: dict | None = None):
        self.id, self.key = app_id, key
        self.permissions = dict(APP_PERMISSIONS if permissions is None else permissions)

    def accepts(self, token: str, now: int) -> bool:
        try:
            claims = jwt_claims(token, self.key["n"], self.key["e"])
        except ValueError:
            return False
        iat, exp = claims.get("iat"), claims.get("exp")
        return str(claims.get("iss")) == str(self.id) and type(iat) is int and type(exp) is int \
            and iat <= now < exp <= now + 600


def app(app_id: int = 4242, permissions: dict | None = None) -> App:
    return App(app_id, rsa(), permissions)


# ---------------------------------------------------------------- the API

class MintRefused(Exception):
    pass


class GitHub(urllib.request.BaseHandler):
    """``fake`` (a ``FakeGitHub``, or any ``(method, path, body) -> (status, body)``) behind credentials: put it in
    ``HttpTransport``'s ``handlers``. ``public`` says whether the repository is public; ``now`` is GitHub's clock
    (seconds). ``seen`` lists ``(method, path, credential kind, status)`` of every request received."""

    handler_order = 100

    def __init__(self, fake, the_app: App, now: int, public: bool = True):
        self.fake, self.app, self.now, self.public = fake, the_app, now, public
        self.tokens: dict[str, dict] = {}
        self.seen: list[tuple] = []

    def mint(self, inputs: dict, secrets: dict, repositories: list[str]) -> str:
        """An installation token as the token action makes it from its ``with`` (``loop.job.APP_INPUTS``):
        ``${{ secrets.X }}`` read from ``secrets``, the App's JWT made by GitHub's side from ``app-id`` and
        ``private-key`` (they must be this App's), ``permission-<name>: <level>`` the token's permissions (with
        none asked, every permission of the App), ``repositories`` what the scope step gave."""
        def secret(value):
            m = re.fullmatch(r"\$\{\{ secrets\.([A-Z0-9_]+) \}\}", value)
            return secrets[m.group(1)] if m else value

        if str(secret(inputs["app-id"])) != str(self.app.id) or secret(inputs["private-key"]) != self.app.pem:
            raise MintRefused("401: not this App's id and key")
        asked = {name[len("permission-"):].replace("-", "_"): level for name, level in inputs.items()
                 if name.startswith("permission-")}
        for name, level in asked.items():
            if LEVELS.get(level, 9) > LEVELS.get(self.app.permissions.get(name), 0):
                raise MintRefused("422: the App does not hold %s: %s" % (name, level))
        permissions = dict(asked or self.app.permissions, metadata="read")
        token = "ghs_test%04d" % len(self.tokens)
        self.tokens[token] = {"permissions": permissions, "repositories": list(repositories)}
        return token

    def _answer(self, method: str, path: str, credential: str, body):
        if path == "/app" or path.startswith("/app/"):
            if credential in self.tokens or not self.app.accepts(credential, self.now):
                return "token" if credential in self.tokens else "other", 401, \
                    {"message": "A JSON web token could not be decoded"}
            if (method, path) != ("GET", "/app"):
                return "jwt", 404, {"message": "Not Found"}
            return ("jwt",) + tuple(self.fake(method, path, body))
        grant = self.tokens.get(credential)
        if grant is None:
            return "other", 401, {"message": "Bad credentials"}
        if path == "/installation/repositories":
            return ("token",) + tuple(self.fake(method, path, body))
        m = re.fullmatch(r"/repos/([^/]+/[^/]+)/(.+)", path)
        if not m or m.group(1) not in grant["repositories"]:
            return "token", 404, {"message": "Not Found"}
        for row_method, route, (name, level) in NEEDS:
            if row_method == method and re.fullmatch(route, m.group(2)):
                free = self.public and (name, level) == ("actions", "read")
                if not free and LEVELS.get(grant["permissions"].get(name), 0) < LEVELS[level]:
                    break
                return ("token",) + tuple(self.fake(method, path, body))
        return "token", 403, {"message": "Resource not accessible by integration"}

    def https_open(self, req):
        if not req.full_url.startswith(API + "/"):
            raise AssertionError("a request to another host: %s" % req.full_url)
        path, method = req.full_url[len(API):], req.get_method()
        scheme, _, credential = (req.get_header("Authorization") or "").partition(" ")
        body = None if req.data is None else json.loads(req.data)
        kind, status, answer = self._answer(method, path, credential if scheme == "Bearer" else "", body)
        self.seen.append((method, path, kind, status))
        raw = b"" if answer is None else json.dumps(answer).encode("utf-8")
        resp = urllib.response.addinfourl(io.BytesIO(raw), Message(), req.full_url, status)
        resp.msg = "x"
        return resp


def github(fake, now: int, public: bool = True, permissions: dict | None = None, app_id: int = 4242) -> GitHub:
    """A ``GitHub`` whose App has the test key; ``.app.pem`` is the key's PEM (PKCS#1), the App secret's value."""
    the_app = app(app_id, permissions)
    the_app.pem = pem(pkcs1(the_app.key))
    return GitHub(fake, the_app, now, public)
