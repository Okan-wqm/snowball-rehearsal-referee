"""Test 49 (with test_write.py): genesis' reads are sent with the credential GitHub answers them to.

``target.app_jwt`` (the App's JWT), ``target.write.HttpTransport``'s choice of credential per request,
``loop.job.writer_transport`` and the token ``loop.job.APP_INPUTS`` asks for, against ``github_auth.GitHub``: a
GitHub that answers by the ``Authorization`` header (its docstring says which of its rows are the operator's
observations and which are read from documentation). The job-level tests run ``yaz`` with its own transport
(``transport=None``) in ``test_loop_write.Genesis``' world.
"""

from __future__ import annotations

import datetime
import json
import re
import unittest
from unittest import mock

import activate as AC
import activation_world as AW
import github_auth as GA
import test_loop_write as TLW
import yaz_world as YW
from loop import job as J
from target import app_jwt as AJ
from target import branches as B
from target.land import HardStop
from target import write as W

NOW = 1_794_000_000
CLOCK = lambda: datetime.datetime.fromtimestamp(NOW, datetime.timezone.utc)  # noqa: E731
KEY = GA.rsa()
PEM = GA.pem(GA.pkcs1(KEY))
SECRETS = {J.APP_ID_ENV: str(AW.APP_ID), J.APP_KEY_ENV: PEM}


def refusal(pem, app_id="4242", now=NOW) -> str:
    try:
        AJ.token(app_id, pem, now)
    except AJ.Unusable as exc:
        return str(exc)
    raise AssertionError("a token was made")


class Jwt(unittest.TestCase):
    def test_the_token_verifies_under_the_public_key_and_carries_the_three_claims(self):
        token = AJ.token("4242", PEM, NOW)
        self.assertRegex(token, r"\A[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\Z")
        self.assertEqual(GA.jwt_claims(token, KEY["n"], KEY["e"]), {"exp": NOW + 300, "iat": NOW - 60, "iss": "4242"})
        head, claims, _ = token.split(".")
        self.assertEqual(GA._unb64url(head), b'{"alg":"RS256","typ":"JWT"}')
        self.assertEqual(GA._unb64url(claims), b'{"exp":%d,"iat":%d,"iss":"4242"}' % (NOW + 300, NOW - 60))
        self.assertEqual(token, AJ.token("4242", PEM, NOW))  # deterministic
        self.assertNotEqual(token, AJ.token("4242", PEM, NOW + 1))
        # a client id is an issuer too
        self.assertEqual(GA.jwt_claims(AJ.token("Iv23liABCdef", PEM, NOW), KEY["n"], KEY["e"])["iss"], "Iv23liABCdef")

    def test_the_signature_is_this_key_s_over_these_bytes(self):
        token = AJ.token("4242", PEM, NOW)
        other = GA.rsa(seed=7)
        with self.assertRaises(ValueError):
            GA.jwt_claims(token, other["n"], other["e"])
        head, claims, sig = token.split(".")
        forged = AJ.b64url(b'{"exp":%d,"iat":%d,"iss":"1"}' % (NOW + 300, NOW - 60))
        with self.assertRaises(ValueError):
            GA.jwt_claims("%s.%s.%s" % (head, forged, sig), KEY["n"], KEY["e"])
        self.assertEqual(AJ.token("4242", GA.pem(GA.pkcs1(other)), NOW).split(".")[:2], [head, claims])
        self.assertNotEqual(AJ.token("4242", GA.pem(GA.pkcs1(other)), NOW), token)

    def test_both_pem_forms_give_the_same_token(self):
        token = AJ.token("4242", PEM, NOW)
        self.assertEqual(AJ.token("4242", GA.pem(GA.pkcs8(GA.pkcs1(KEY)), "PRIVATE KEY"), NOW), token)
        # line ends and outer blank lines are the file's, not the key's
        self.assertEqual(AJ.token("4242", "\n" + PEM.replace("\n", "\r\n") + "\n", NOW), token)

    def test_a_pem_that_is_not_one_plain_rsa_block_is_refused(self):
        der = GA.pkcs1(KEY)
        body = PEM.splitlines()
        for pem in (GA.pem(der, "EC PRIVATE KEY"), GA.pem(der, "ENCRYPTED PRIVATE KEY"), GA.pem(der, "PUBLIC KEY"),
                    "Bag Attributes\n" + PEM, PEM + "x\n", "", "\n".join(body[:-1]), "\n".join(body[1:]),
                    "\n".join([body[0], body[-1]]), "\n".join([body[0]] + body[1:-1] + [body[-1].replace("RSA ", "")])):
            self.assertRegex(refusal(pem), r"\Aprivate key: not one PEM block", pem[:40])
        for pem in (PEM + PEM,  # two blocks: the inner END and BEGIN lines are not base64
                    "\n".join([body[0], "Proc-Type: 4,ENCRYPTED", "DEK-Info: AES-256-CBC,00", ""] + body[1:]),
                    "\n".join([body[0], body[1][:-1] + "!"] + body[2:]),
                    "\n".join([body[0], body[1] + "="] + body[2:]),
                    "\n".join([body[0], body[1][:-1]] + body[2:])):
            self.assertEqual(refusal(pem), "private key: the PEM body is not base64")
        for value in (None, PEM.encode(), 7):
            self.assertEqual(refusal(value), "private key: not text")
        # the label decides the structure read: PKCS#1 bytes under the PKCS#8 label and the reverse are refused
        self.assertRegex(refusal(GA.pem(der, "PRIVATE KEY")), r"\Aprivate key: ")
        self.assertRegex(refusal(GA.pem(GA.pkcs8(der))), r"\Aprivate key: ")

    def test_der_is_read_strictly(self):
        der = GA.pkcs1(KEY)
        ints = b"".join(GA.der_int(n) for n in (0, KEY["n"], KEY["e"], KEY["d"], KEY["p"], KEY["q"], KEY["d"] % (
            KEY["p"] - 1), KEY["d"] % (KEY["q"] - 1), pow(KEY["q"], -1, KEY["p"])))
        self.assertEqual(GA.der(0x30, ints), der)
        size = len(ints).to_bytes(2, "big")
        cases = {
            "bytes after the DER structure": der + b"\x00",
            "a DER length that is not in its shortest form": b"\x30\x83\x00" + size + ints,
            "a DER value longer than its data": der[:-1],
            "not the DER structure of an RSA key": b"\x31" + der[1:],
            "bytes after the nine integers of an RSA key": GA.der(0x30, ints + GA.der_int(1)),
            "a DER integer that is negative or not in its shortest form": GA.der(0x30, b"\x02\x02\x00\x00" + ints[3:]),
        }
        for want, data in cases.items():
            self.assertEqual(refusal(GA.pem(data)), "private key: " + want)
        # a length below 128 written in the long form, an indefinite length, a negative and an empty integer
        for head in (b"\x02\x81\x01\x00", b"\x02\x80\x00", b"\x02\x01\x80", b"\x02\x00"):
            self.assertRegex(refusal(GA.pem(GA.der(0x30, head + ints[3:]))), r"\Aprivate key: a DER ")
        # eight integers
        self.assertEqual(refusal(GA.pem(GA.der(0x30, ints[:-len(GA.der_int(pow(KEY["q"], -1, KEY["p"])))]))),
                         "private key: not the DER structure of an RSA key")
        # PKCS#8: another algorithm, absent parameters, a trailing element
        inner = GA.pkcs1(KEY)
        ec = GA.der(0x30, GA.der(0x06, bytes([0x2A, 0x86, 0x48, 0xCE, 0x3D, 2, 1])) + GA.der(0x05, b""))
        bare = GA.der(0x30, GA.der(0x06, bytes([0x2A, 0x86, 0x48, 0x86, 0xF7, 0x0D, 1, 1, 1])))
        for algorithm in (ec, bare):
            self.assertEqual(refusal(GA.pem(GA.pkcs8(inner, algorithm), "PRIVATE KEY")),
                             "private key: PKCS#8 of another algorithm than rsaEncryption")
        extra = GA.der(0x30, GA.der_int(0) + GA.RSA_ALGORITHM + GA.der(0x04, inner) + GA.der(0xA0, b""))
        self.assertEqual(refusal(GA.pem(extra, "PRIVATE KEY")),
                         "private key: PKCS#8 with attributes or a public key is not read")
        v1 = GA.der(0x30, GA.der_int(1) + GA.RSA_ALGORITHM + GA.der(0x04, inner))
        self.assertEqual(refusal(GA.pem(v1, "PRIVATE KEY")), "private key: PKCS#8 of another algorithm than rsaEncryption")

    def test_numbers_that_are_not_one_key_are_refused(self):
        self.assertEqual(refusal(GA.pem(GA.pkcs1(KEY, version=1))), "private key: not a two-prime RSA key (version 0)")
        for change in ({"n": KEY["n"] + 2}, {"d": KEY["d"] + 2}, {"e": KEY["e"] + 2}, {"e": 1, "d": 1},
                       {"p": KEY["p"] + 2}, {"p": 1, "q": KEY["n"]}, {"p": KEY["n"], "q": 1}):
            self.assertEqual(refusal(GA.pem(GA.pkcs1(dict(KEY, **change)))), "private key: its numbers are not one RSA key",
                             sorted(change))
        # an even exponent with its own inverse does not exist (p - 1 is even); e = 2 with any d is refused
        self.assertEqual(refusal(GA.pem(GA.pkcs1(dict(KEY, e=2)))), "private key: its numbers are not one RSA key")
        # d need only invert e modulo lcm(p - 1, q - 1): openssl's d (the smallest) and the textbook's both sign
        import math
        small = pow(KEY["e"], -1, math.lcm(KEY["p"] - 1, KEY["q"] - 1))
        self.assertNotEqual(small, KEY["d"])
        self.assertEqual(AJ.token("4242", GA.pem(GA.pkcs1(dict(KEY, d=small))), NOW), AJ.token("4242", PEM, NOW))

    def test_sign_answers_only_a_signature_that_verifies(self):
        key = (KEY["n"], KEY["e"], KEY["d"])
        sig = AJ.sign(key, b"m")
        self.assertEqual(len(sig), 256)
        self.assertEqual(pow(int.from_bytes(sig, "big"), KEY["e"], KEY["n"]).to_bytes(256, "big"), AJ.encoded(b"m", 256))
        for bad in ((KEY["n"], KEY["e"], KEY["d"] + 2), (KEY["n"], KEY["e"] + 2, KEY["d"])):
            with self.assertRaises(AJ.Unusable) as ctx:
                AJ.sign(bad, b"m")
            self.assertEqual(str(ctx.exception), "private key: the signature does not verify under its own public numbers")

    def test_a_modulus_under_2048_bits_is_refused(self):
        self.assertEqual(KEY["n"].bit_length(), 2048)
        near = GA.rsa(2047, seed=7)
        self.assertIn(near["n"].bit_length(), (2046, 2047))
        for key in (near, GA.rsa(1024, seed=7)):
            self.assertEqual(refusal(GA.pem(GA.pkcs1(key))), "private key: a modulus under 2048 bits")

    def test_app_id_and_clock(self):
        for app_id in ("", "a b", "x" * 65, 4242, None, "42\n", "a/b"):
            self.assertEqual(refusal(PEM, app_id=app_id), "App id: not an App id or a client id")
        for at in (1.5, float(NOW), True, None, "1", 59, -1):
            self.assertEqual(refusal(PEM, now=at), "now: not whole seconds since the epoch")
        self.assertEqual(GA.jwt_claims(AJ.token("4242", PEM, 60), KEY["n"], KEY["e"])["iat"], 0)

    def test_no_refusal_holds_key_bytes(self):
        der = GA.pkcs1(KEY)
        messages = [refusal(GA.pem(der, "EC PRIVATE KEY")), refusal(GA.pem(der + b"\x00")), refusal(PEM + "x"),
                    refusal(GA.pem(GA.pkcs1(dict(KEY, n=KEY["n"] + 2)))), refusal(PEM, app_id="a b"),
                    refusal(GA.pem(GA.pkcs1(GA.rsa(1024, seed=7))))]
        for message in messages:
            self.assertIsNone(re.search(r"[A-Za-z0-9+/=]{16,}|\d{5,}", message), message)
            self.assertLess(len(message), 100)


class TheGitHub(unittest.TestCase):
    """The tests' GitHub refuses what the real one is known to refuse (else the tests above it prove nothing)."""

    def setUp(self) -> None:
        self.calls = []
        self.gh = GA.github(lambda *a: (self.calls.append(a), (200, {"id": 4242}))[1], NOW)

    def get(self, credential: str, path: str = "/app", method: str = "GET"):
        try:
            return W.HttpTransport(credential, handlers=(self.gh,), app=lambda: credential)(method, path, None)[0]
        except W.ApiError as exc:
            return exc.status

    def test_app_is_answered_only_to_a_jwt_github_accepts(self):
        pem = self.gh.app.pem
        self.assertEqual(self.get(AJ.token("4242", pem, NOW)), 200)
        token = self.gh.mint(J.APP_INPUTS, SECRETS, ["acme/toy"])
        other = GA.pem(GA.pkcs1(GA.rsa(seed=7)))
        for bad in (token, "x", AJ.token("4243", pem, NOW), AJ.token("4242", other, NOW),
                    AJ.token("4242", pem, NOW - 300), AJ.token("4242", pem, NOW + 61)):
            self.assertEqual(self.get(bad), 401)
        self.assertEqual(self.get(AJ.token("4242", pem, NOW - 299)), 200)
        self.assertEqual(self.get(AJ.token("4242", pem, NOW + 60)), 200)
        self.assertEqual(len(self.calls), 3)
        self.assertEqual(self.gh.seen[1], ("GET", "/app", "token", 401))

    def test_a_token_holds_what_was_asked_within_the_app_s(self):
        token = self.gh.mint(J.APP_INPUTS, SECRETS, ["acme/toy"])
        self.assertEqual(self.gh.tokens[token]["permissions"], {
            "contents": "write", "pull_requests": "write", "checks": "write", "administration": "read",
            "metadata": "read"})
        few = {k: v for k, v in J.APP_INPUTS.items() if k != "permission-administration"}
        self.assertNotIn("administration", self.gh.tokens[self.gh.mint(few, SECRETS, ["acme/toy"])]["permissions"])
        for more in ({"permission-administration": "write"}, {"permission-actions": "read"},
                     {"permission-workflows": "write"}):
            with self.assertRaises(GA.MintRefused):
                self.gh.mint(dict(J.APP_INPUTS, **more), SECRETS, ["acme/toy"])
        for wrong in ({J.APP_ID_ENV: "1"}, {J.APP_KEY_ENV: GA.pem(GA.pkcs1(GA.rsa(seed=7)))}):
            with self.assertRaises(GA.MintRefused):
                self.gh.mint(J.APP_INPUTS, dict(SECRETS, **wrong), ["acme/toy"])

    def test_repository_routes_ask_the_token_its_repository_and_its_permission(self):
        token = self.gh.mint(J.APP_INPUTS, SECRETS, ["acme/toy"])
        p = "/repos/acme/toy/"
        self.assertEqual(self.get(token, p + "actions/permissions"), 200)
        self.assertEqual(self.get(token, p + "git/ref/heads/main"), 200)
        self.assertEqual(self.get(token, "/repos/acme/other/git/ref/heads/main"), 404)
        self.assertEqual(self.get(token, p + "actions/secrets"), 403)        # in no row: closed
        self.assertEqual(self.get(token, p + "git/refs/heads/main", "DELETE"), 403)
        self.assertEqual(self.get("ghs_unknown", p + "git/ref/heads/main"), 401)
        self.assertEqual(self.get(AJ.token("4242", self.gh.app.pem, NOW), p + "git/ref/heads/main"), 401)
        few = self.gh.mint({k: v for k, v in J.APP_INPUTS.items() if k != "permission-administration"}, SECRETS,
                           ["acme/toy"])
        self.assertEqual(self.get(few, p + "actions/permissions"), 403)
        self.assertEqual(self.get(few, p + "rules/branches/main"), 200)
        # workflows: free on a public repository, ``actions: read`` (which the App does not hold) on a private one
        self.assertEqual(self.get(token, p + "actions/workflows"), 200)
        self.gh.public = False
        self.assertEqual(self.get(token, p + "actions/workflows"), 403)


class Credential(unittest.TestCase):
    """``HttpTransport``: which credential goes with which request."""

    def setUp(self) -> None:
        self.seen = []
        outer = self

        class Record(GA.urllib.request.BaseHandler):
            handler_order = 100

            def https_open(self, req):
                outer.seen.append((req.get_method(), req.full_url, req.get_header("Authorization")))
                resp = GA.urllib.response.addinfourl(GA.io.BytesIO(b"{}"), GA.Message(), req.full_url, 200)
                resp.msg = "x"
                return resp

        self.record = Record()

    def test_get_app_goes_with_the_jwt_and_everything_else_with_the_token(self):
        made = []
        t = W.HttpTransport("tok", handlers=(self.record,), app=lambda: (made.append(1), "j.w.t")[1])
        t("GET", "/installation/repositories", None)
        t("GET", "/repos/acme/toy/rules/branches/main", None)
        t("POST", "/repos/acme/toy/git/refs", {"ref": "refs/heads/brain/c/1", "sha": "a" * 40})
        self.assertEqual(made, [])  # no JWT is made for a request that is not the App's
        t("GET", "/app", None)
        t("GET", "/app", None)
        self.assertEqual(len(made), 2)  # one per read: none is kept
        self.assertEqual([auth for _, _, auth in self.seen], ["Bearer tok"] * 3 + ["Bearer j.w.t"] * 2)
        self.assertEqual(self.seen[3][:2], ("GET", "https://api.github.com/app"))

    def test_no_other_request_is_sent_as_the_app(self):
        t = W.HttpTransport("tok", handlers=(self.record,), app=lambda: "j.w.t")
        for method, path in (("GET", "/app/installations"), ("POST", "/app/installations/1/access_tokens"),
                             ("DELETE", "/app/installations/1"), ("POST", "/app"), ("PATCH", "/app"),
                             ("GET", "/app/hook/config"), ("get", "/app")):
            with self.assertRaises(W.Unusable) as ctx:
                t(method, path, None)
            self.assertEqual(str(ctx.exception), "%s %s: only GET /app is sent as the App" % (method, path))
        self.assertEqual(self.seen, [])
        # a path that only starts with the letters is an ordinary one (the token's)
        t("GET", "/apps/snowball-writer", None)
        self.assertEqual(self.seen[0][2], "Bearer tok")

    def test_without_the_app_s_credential_get_app_is_not_sent(self):
        t = W.HttpTransport("tok", handlers=(self.record,))
        with self.assertRaises(W.Unusable) as ctx:
            t("GET", "/app", None)
        self.assertEqual(str(ctx.exception), "GET /app is answered only to the App's JWT and none was given")
        for bad in ("", "a\nb", "a\rb", None, b"x"):
            with self.assertRaises(W.Unusable) as ctx:
                W.HttpTransport("tok", handlers=(self.record,), app=lambda: bad)("GET", "/app", None)
            self.assertEqual(str(ctx.exception), "the App's JWT must be one non-empty line")
        self.assertEqual(self.seen, [])


def environ(token: str, **over) -> dict:
    return dict({"WRITER_TOKEN": token}, **dict(SECRETS, **over))


class WriterTransport(unittest.TestCase):
    """``loop.job.writer_transport`` against the credentialed GitHub, the token made from ``APP_INPUTS``."""

    def world(self, kind: str = "toy", inputs=None, public: bool = True):
        world = AW.World(kind)
        gh = GA.github(world.gh, NOW, public=public)
        self.assertEqual(gh.app.pem, PEM)
        token = gh.mint(J.APP_INPUTS if inputs is None else inputs, SECRETS, [AW.REPO])
        return world, gh, token

    def test_genesis_reads_are_answered_for_a_toy_and_a_copy(self):
        for kind, own in (("toy", "actions/workflows"), ("copy", "actions/permissions")):
            world, gh, token = self.world(kind)
            got = AC.genesis(J.writer_transport(environ(token), CLOCK, True, (gh,)), world.files, "toy")
            self.assertEqual(got, AC.genesis(world.gh, world.files, "toy"))
            self.assertEqual((got["ok"], got["reasons"]), (True, []), got)
            self.assertEqual(gh.seen[0], ("GET", "/app", "jwt", 200))
            self.assertEqual({(kind_, status) for _, _, kind_, status in gh.seen[1:]}, {("token", 200)})
            self.assertIn(("GET", "/repos/%s/%s" % (AW.REPO, own), "token", 200), gh.seen)

    def test_the_activation_is_written_with_the_token_asked_for(self):
        world, gh, token = self.world()
        world.writer = lambda: W.Writer(AW.REPO, J.writer_transport(environ(token), CLOCK, True, (gh,)))
        out = world.run()
        self.assertNotIn("reason", out)
        self.assertEqual({B.STATE, B.INTEGRATION} - set(world.gh.refs), set())
        self.assertEqual({s[3] for s in gh.seen if s[3] >= 400}, {404})  # the branches it finds absent, no refusal
        self.assertEqual({m for m, _, _, _ in gh.seen}, {"GET", "POST", "PATCH", "PUT"})
        self.assertEqual([s for s in gh.seen if s[2] == "jwt"], [("GET", "/app", "jwt", 200)])

    def test_each_permission_asked_for_is_needed(self):
        def without(name):
            return {k: v for k, v in J.APP_INPUTS.items() if k != name}

        for name in ("permission-contents", "permission-pull-requests", "permission-checks"):
            world, gh, token = self.world(inputs=without(name))
            world.writer = lambda: W.Writer(AW.REPO, J.writer_transport(environ(token), CLOCK, True, (gh,)))
            with self.assertRaises((W.ApiError, HardStop), msg=name) as ctx:
                world.run()
            self.assertIn("403: ", str(ctx.exception))
            self.assertEqual(gh.seen[-1][2:], ("token", 403))
        # administration: the copy's read (the toy's genesis does not ask it)
        world, gh, token = self.world("copy", without("permission-administration"))
        with self.assertRaises(W.ApiError) as ctx:
            AC.genesis(J.writer_transport(environ(token), CLOCK, True, (gh,)), world.files, "toy")
        self.assertEqual(ctx.exception.status, 403)
        self.assertEqual(gh.seen[-1], ("GET", "/repos/%s/actions/permissions" % AW.REPO, "token", 403))

    def test_a_private_toy_s_workflows_are_not_readable_with_the_app_s_permissions(self):
        # a known limit, stated: tohum/25 item 6 gives the App no ``actions`` permission (github_auth: from the
        # documentation, not observed); genesis on a private toy stops at this read
        world, gh, token = self.world(public=False)
        with self.assertRaises(W.ApiError) as ctx:
            AC.genesis(J.writer_transport(environ(token), CLOCK, True, (gh,)), world.files, "toy")
        self.assertEqual((ctx.exception.status, gh.seen[-1][1]), (403, "/repos/%s/actions/workflows" % AW.REPO))

    def test_without_app_the_transport_holds_no_app_credential(self):
        world, gh, token = self.world()
        transport = J.writer_transport(environ(token), CLOCK, handlers=(gh,))
        self.assertIsNone(transport.app)
        with self.assertRaises(W.Unusable):
            AC.genesis(transport, world.files, "toy")
        self.assertEqual(gh.seen, [])
        self.assertEqual(transport("GET", "/repos/%s/git/ref/heads/main" % AW.REPO, None)[0], 200)
        # and it asks for neither secret
        self.assertIsNone(J.writer_transport({"WRITER_TOKEN": token}, CLOCK).app)

    def test_an_unset_secret_is_unusable_before_any_request(self):
        world, gh, token = self.world()
        for name in (J.APP_ID_ENV, J.APP_KEY_ENV):
            for env in (environ(token, **{name: ""}), {k: v for k, v in environ(token).items() if k != name}):
                with self.assertRaises(J.Unusable) as ctx:
                    J.writer_transport(env, CLOCK, True, (gh,))
                self.assertEqual(str(ctx.exception), "yaz: %s is not set" % name)
        self.assertEqual(gh.seen, [])

    def test_a_key_that_is_refused_is_unusable_at_the_read_without_its_bytes(self):
        world, gh, token = self.world()
        bad = GA.pem(GA.pkcs1(KEY), "EC PRIVATE KEY")
        transport = J.writer_transport(environ(token, **{J.APP_KEY_ENV: bad}), CLOCK, True, (gh,))
        self.assertEqual(transport("GET", "/repos/%s/git/ref/heads/main" % AW.REPO, None)[0], 200)
        with self.assertRaises(W.Unusable) as ctx:
            AC.genesis(transport, world.files, "toy")
        self.assertEqual(str(ctx.exception), "private key: not one PEM block of RSA PRIVATE KEY or PRIVATE KEY")
        self.assertEqual(len(gh.seen), 1)
        with self.assertRaises(W.Unusable) as ctx:
            J.writer_transport(environ(token, **{J.APP_ID_ENV: "a b"}), CLOCK, True, (gh,))("GET", "/app", None)
        self.assertEqual(str(ctx.exception), "App id: not an App id or a client id")

    def test_the_jwt_is_made_at_the_clock_s_time_of_the_read(self):
        world, gh, token = self.world()
        at = [NOW - 3600]
        transport = J.writer_transport(environ(token), lambda: datetime.datetime.fromtimestamp(
            at[0], datetime.timezone.utc), True, (gh,))
        with self.assertRaises(W.ApiError) as ctx:  # an hour-old clock: GitHub's refuses the expired JWT
            transport("GET", "/app", None)
        self.assertEqual(ctx.exception.status, 401)
        at[0] = NOW
        self.assertEqual(transport("GET", "/app", None), (200, {"id": AW.APP_ID, "slug": "snowball-writer"}))
        # another App's id on the same key: not this App's JWT
        other = J.writer_transport(environ(token, **{J.APP_ID_ENV: "4243"}), CLOCK, True, (gh,))
        with self.assertRaises(W.ApiError):
            other("GET", "/app", None)


class Registry(unittest.TestCase):
    def test_the_two_secrets_are_yaz_s_and_refused_in_a_code_job(self):
        self.assertEqual(J.APP_SECRETS, {"WRITER_APP_ID": "${{ secrets.WRITER_APP_ID }}",
                                         "WRITER_APP_PRIVATE_KEY": "${{ secrets.WRITER_APP_PRIVATE_KEY }}"})
        doc = J.workflow()
        holders = {name for name, job in doc["jobs"].items() if "WRITER_APP_" in json.dumps(job)}
        self.assertEqual(holders, {"yaz"})
        run = [s for s in doc["jobs"]["yaz"]["steps"] if s.get("name") == "yaz"]
        self.assertEqual(len(run), 1)
        self.assertEqual({k: v for k, v in run[0]["env"].items() if k.startswith("WRITER_")},
                         dict(J.APP_SECRETS, WRITER_TOKEN="${{ steps.app.outputs.token }}"))
        for job in ("getir", "kos"):
            for name in J.APP_SECRETS:
                out = J.run(job, {"RUNNER_TEMP": "/nonexistent", name: "x"})
                self.assertEqual((out["ok"], out["reason"]), (False, "secret_in_code_job:" + name))


class Job(TLW.Genesis):
    """``yaz`` with its own transport (``transport=None``: ``writer_transport``, given the tests' GitHub as its
    urllib handler and nothing else), the token made from ``APP_INPUTS``."""

    def own(self, **env) -> dict:
        """The job's line's target line, and the ``app`` arguments ``writer_transport`` was called with."""
        if getattr(self, "auth", None) is None or self.auth.fake is not self.gh:
            self.auth = GA.github(self.gh, int(YW.NOW.timestamp()))
            self.token = self.auth.mint(J.APP_INPUTS, SECRETS, [YW.REPO])
        real, self.apps = J.writer_transport, []

        def spy(environ, now, app=False):
            self.apps.append(app)
            return real(environ, now, app, (self.auth,))

        env = dict({"WRITER_TOKEN": self.token}, **dict(SECRETS, **env))
        with mock.patch.object(J, "writer_transport", spy):
            return self.line(J.run("yaz", YW.env(self.temp, self.workspace, **env), signer=self.signer,
                                   now=lambda: YW.NOW))

    def test_the_genesis_cycle_reads_as_the_app_and_the_next_cycle_holds_no_app_credential(self):
        TLW.write_tree(self.src, {"pkg/b.js": "var b = 1;\n"})
        self.main_at()
        self.kos({"good": TLW.candidate(TLW.GOOD)})
        self.control(TLW.OPEN)
        self.github()
        # the key missing: unusable, nothing sent
        with self.assertRaises(J.Unusable):
            self.own(**{J.APP_KEY_ENV: ""})
        self.assertEqual(self.auth.seen, [])
        out = self.own()
        self.assertEqual((out["ok"], out["done"], out["merge"]), (True, ["D5", "D6"], "good"), out)
        self.assertEqual(self.apps, [True])
        self.assertEqual(self.auth.seen[0], ("GET", "/app", "jwt", 200))
        self.assertEqual([s for s in self.auth.seen if s[3] in (401, 403) or (s[2] == "jwt") != (s[1] == "/app")], [])
        self.assertIn(B.STATE, self.gh.refs)
        # the next cycle: ordinary, with the secrets still in the environment
        sent = len(self.auth.seen)
        other = dict(TLW.candidate(TLW.diff("pkg/b.js", ["var b = 1;"], ["let b = 1;"])),
                     **{"finding.json": json.dumps(dict(TLW.FINDING, path="pkg/b.js")).encode()})
        self.next_cycle({"good": other}, "10")
        out = self.own(GITHUB_RUN_ID="10")
        self.assertEqual((out["ok"], out["done"]), (True, ["D5", "D6", "D7"]), out)
        self.assertEqual(self.apps, [False])
        later = self.auth.seen[sent:]
        self.assertTrue(later)
        self.assertEqual([s for s in later if s[2] != "token" or s[3] in (401, 403)], [])


def load_tests(loader, standard, pattern):
    """This module's own tests: ``Job`` inherits ``test_loop_write.Genesis``' world, not its tests (test 46's)."""
    suite = unittest.TestSuite()
    for case in (Jwt, TheGitHub, Credential, WriterTransport, Registry, Job):
        names = [n for n in loader.getTestCaseNames(case) if n in vars(case)]
        suite.addTests(case(n) for n in names)
    return suite
