"""Test 40 (asama-0/09: "sonraki D1 doğrular") and 46 (D1 of ``cek``): ``loop.rekor``, the next cycle's read and
verification of a root's Rekor entry, and ``ledger.anchor.judge`` with it.

- a real entry (``fixtures/rekor-entry.json``, ``capture_rekor_entry.py``): the answer is the uuid's (its key and its
  body's leaf hash); the bundle made from it is, field for field, the one its signer published, except the proof and
  the signed entry timestamp, which are the answer's (Rekor re-proves against its newer tree); the bundle is
  the one real ``sigstore`` judged: valid with the workflow's identity, invalid with another identity, another
  digest or a changed proof hash;
- ``RekorHttp``: one GET of ``REKOR + uuid``, no header, no body; 404 is no entry; a value that is no uuid is no
  entry and sends nothing; another status, an answer too large, not JSON, of two entries, of another uuid or
  another body is ``RekorError``;
- ``entry_reasons``: no entry; a body of another digest or another kind (``entry_root_mismatch``, nothing run); a
  bundle piece missing (``entry_unverified``, nothing run); the verifier's argv (``identity_argv`` with the pin and
  ``sha256:`` of the payload) and the bundle it reads; its non-zero exit (``entry_unverified``);
- ``ledger.anchor.judge`` over it: the root and the entry judged together, in ``ledger.anchor``'s order.
"""

from __future__ import annotations

import base64
import copy
import hashlib
import io
import json
import os
import sys
import unittest
import urllib.request
import urllib.response
from email.message import Message

REFEREE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REFEREE)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ledger import anchor as AN  # noqa: E402
from loop import accepted as A  # noqa: E402
from loop import rekor as R  # noqa: E402
from test_anchor import LEDGER, WORKFLOW  # noqa: E402

with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "rekor-entry.json")) as _fh:
    REAL = json.load(_fh)
REAL_ANSWER = json.loads(REAL["answer"])
REAL_ENTRY = next(iter(REAL_ANSWER.values()))


def b64(hex_text: str) -> str:
    return base64.b64encode(bytes.fromhex(hex_text)).decode()


def entry_for(digest: str, kind: str = "hashedrekord", drop: str | None = None) -> tuple[str, dict]:
    """A Rekor answer's ``(uuid, entry)`` whose body records ``digest`` with the real entry's certificate and
    signature (no signature here is valid: the verifier is a fake)."""
    body = json.loads(base64.b64decode(REAL_ENTRY["body"]))
    body["kind"] = kind
    body["spec"]["data"]["hash"]["value"] = digest
    raw = json.dumps(body).encode()
    entry = dict(copy.deepcopy(REAL_ENTRY), body=base64.b64encode(raw).decode())
    if drop:
        del entry["verification"][drop]
    return "0" * 16 + hashlib.sha256(b"\x00" + raw).hexdigest(), entry


class _Https(urllib.request.BaseHandler):
    handler_order = 100

    def __init__(self, status: int, body: bytes):
        self.status, self.body, self.seen = status, body, []

    def https_open(self, req):
        self.seen.append(req)
        resp = urllib.response.addinfourl(io.BytesIO(self.body), Message(), req.full_url, self.status)
        resp.msg = "x"
        return resp


class RealEntry(unittest.TestCase):
    def test_the_answer_is_the_uuids(self):
        self.assertEqual(R.checked_answer(REAL["uuid"], REAL_ANSWER), REAL_ENTRY)
        self.assertEqual(R.checked_answer(REAL["uuid"][-64:], REAL_ANSWER), REAL_ENTRY)  # the leaf hash alone

    def test_the_bundle_is_the_published_one_with_rekors_proof(self):
        made = R.bundle(REAL_ENTRY, R.body_of(REAL_ENTRY))
        published = REAL["published"]
        self.assertEqual(made["mediaType"], published["mediaType"])
        self.assertEqual(made["messageSignature"], published["messageSignature"])
        self.assertEqual(made["verificationMaterial"]["certificate"], published["verificationMaterial"]["certificate"])
        [ours], [theirs] = made["verificationMaterial"]["tlogEntries"], published["verificationMaterial"]["tlogEntries"]
        self.assertEqual(set(ours), set(theirs))
        for key in set(theirs) - {"inclusionProof", "inclusionPromise"}:
            self.assertEqual(ours[key], theirs[key], key)
        self.assertEqual(set(ours["inclusionProof"]), set(theirs["inclusionProof"]))
        proof = REAL_ENTRY["verification"]["inclusionProof"]
        self.assertEqual(ours["inclusionProof"], {
            "logIndex": str(proof["logIndex"]), "rootHash": b64(proof["rootHash"]), "treeSize": str(proof["treeSize"]),
            "hashes": [b64(h) for h in proof["hashes"]], "checkpoint": {"envelope": proof["checkpoint"]}})
        self.assertEqual(ours["inclusionPromise"],
                         {"signedEntryTimestamp": REAL_ENTRY["verification"]["signedEntryTimestamp"]})

    def test_real_sigstore_judged_this_bundle(self):
        self.assertEqual(R.bundle(REAL_ENTRY, R.body_of(REAL_ENTRY)), REAL["made"])
        self.assertEqual(REAL["verdicts"], {"good": 0, "other_identity": 1, "other_digest": 1, "other_proof": 1})
        self.assertTrue(REAL["identity"].startswith("https://github.com/"))  # a GitHub Actions identity
        self.assertEqual(R.body_of(REAL_ENTRY)["spec"]["data"]["hash"]["value"], REAL["digest"])


class Reading(unittest.TestCase):
    def read(self, status: int, body: bytes, uuid: str = REAL["uuid"]):
        fake = _Https(status, body)
        return R.RekorHttp(handlers=(fake,)).entry(uuid), fake.seen

    def test_one_plain_get(self):
        entry, seen = self.read(200, REAL["answer"].encode())
        self.assertEqual(entry, REAL_ENTRY)
        [req] = seen
        self.assertEqual((req.full_url, req.get_method(), req.data, req.headers),
                         (R.REKOR + REAL["uuid"], "GET", None, {}))  # urllib's Host and User-agent only

    def test_no_entry(self):
        self.assertEqual(self.read(404, b"")[0], None)
        for uuid in ("", "uuid-1", "A" * 64, "0" * 63, "0" * 65, "0" * 64 + "/x", None):
            with self.subTest(uuid=uuid):
                self.assertEqual(self.read(200, REAL["answer"].encode(), uuid), (None, []))

    def test_what_is_not_the_entry_is_no_verdict(self):
        other_uuid, other = entry_for("a" * 64)
        changed = dict(REAL_ENTRY, body=other["body"])
        for name, status, body in (
                ("status", 500, b""), ("too large", 200, b" " * (R.MAX_ANSWER + 1)), ("not json", 200, b"{"),
                ("two", 200, json.dumps(dict(REAL_ANSWER, **{other_uuid: other})).encode()),
                ("none", 200, b"{}"), ("list", 200, b"[]"),
                ("another uuid", 200, json.dumps({other_uuid: other}).encode()),
                ("another body", 200, json.dumps({REAL["uuid"]: changed}).encode()),
                ("no body", 200, json.dumps({REAL["uuid"]: {}}).encode())):
            with self.subTest(name):
                with self.assertRaises(R.RekorError):
                    self.read(status, body)


class Judging(unittest.TestCase):
    ROOT = "1" * 64

    def judge(self, entry, code=0, pin=WORKFLOW):
        self.calls = []

        def verifier(argv):
            with open(argv[4]) as fh:
                self.calls.append((argv, json.load(fh)))
            return code
        return R.entry_reasons(lambda uuid: entry, pin, ("sigstore",), verifier)("u", self.ROOT)

    def test_no_entry(self):
        self.assertIsNone(self.judge(None))
        self.assertEqual(self.calls, [])

    def test_a_body_that_does_not_record_the_root(self):
        # another root; sha256 of the root's text (a digest of the root is not the root, tohum/26d "Kök"); another kind
        for entry in (entry_for("2" * 64)[1], entry_for(hashlib.sha256(self.ROOT.encode()).hexdigest())[1],
                      entry_for(self.ROOT, kind="rekord")[1],
                      dict(REAL_ENTRY, body="not base64!"), dict(REAL_ENTRY, body=base64.b64encode(b"[]").decode())):
            with self.subTest():
                self.assertEqual(self.judge(entry), ["entry_root_mismatch"])
                self.assertEqual(self.calls, [])

    def test_the_verifier_judges_the_bundle_against_the_pin_and_the_payload(self):
        _, entry = entry_for(self.ROOT)
        self.assertEqual(self.judge(entry), [])
        [(argv, made)] = self.calls
        self.assertEqual(argv, ["sigstore", "verify", "identity", "--bundle", argv[4], "--cert-identity", WORKFLOW,
                                "--cert-oidc-issuer", "https://token.actions.githubusercontent.com",
                                "sha256:" + self.ROOT])  # stage-open's form: the digest verified is the root
        self.assertEqual(made, R.bundle(entry, R.body_of(entry)))
        self.assertFalse(os.path.exists(argv[4]))  # a temporary file
        self.assertEqual(self.judge(entry, code=1), ["entry_unverified"])
        other = "https://github.com/o/r/.github/workflows/x.yml@refs/heads/main"
        self.assertEqual(self.judge(entry, pin=other), [])
        self.assertEqual(self.calls[0][0][6], other)  # the pin the caller gives

    def test_an_entry_without_a_bundle_piece_is_unverified_without_running(self):
        digest = self.ROOT
        for drop in ("inclusionProof", "signedEntryTimestamp"):
            with self.subTest(drop=drop):
                self.assertEqual(self.judge(entry_for(digest, drop=drop)[1]), ["entry_unverified"])
                self.assertEqual(self.calls, [])
        _, entry = entry_for(digest)
        body = json.loads(base64.b64decode(entry["body"]))
        for name, change in (("two certificates", lambda b: b["spec"]["signature"]["publicKey"].update(
                content=base64.b64encode(base64.b64decode(b["spec"]["signature"]["publicKey"]["content"]) * 2).decode())),
                             ("no certificate", lambda b: b["spec"]["signature"]["publicKey"].update(content="")),
                             ("text around it", lambda b: b["spec"]["signature"]["publicKey"].update(
                                 content=base64.b64encode(b"x\n" + base64.b64decode(
                                     b["spec"]["signature"]["publicKey"]["content"])).decode())),
                             ("no signature", lambda b: b["spec"]["signature"].pop("content"))):
            with self.subTest(name):
                b = copy.deepcopy(body)
                change(b)
                odd = dict(entry, body=base64.b64encode(json.dumps(b).encode()).decode())
                self.assertEqual(self.judge(odd), ["entry_unverified"])
                self.assertEqual(self.calls, [])
        for key, value in (("logIndex", "7"), ("logID", "xyz"), ("integratedTime", -1)):
            with self.subTest(key=key):
                self.assertEqual(self.judge(dict(entry, **{key: value})), ["entry_unverified"])

    def test_judge_over_rekor(self):
        root = AN.root_of(AN.tips(LEDGER))
        uuid, entry = entry_for(root)
        roots = AN.root_row(b"", "r1", "2026-11-01T00:00:00Z", root, uuid)
        rekor = R.entry_reasons({uuid: entry}.get, WORKFLOW, ("sigstore",), lambda argv: 0)
        self.assertEqual(AN.judge(LEDGER, roots, rekor), {"valid": True, "reasons": [], "root": root, "rekor_uuid": uuid})
        other = AN.root_row(b"", "r1", "2026-11-01T00:00:00Z", "2" * 64, uuid)
        self.assertEqual(AN.judge(LEDGER, other, rekor)["reasons"], ["root_mismatch", "entry_root_mismatch"])
        gone = AN.root_row(b"", "r1", "2026-11-01T00:00:00Z", root, "f" * 64)
        self.assertEqual(AN.judge(LEDGER, gone, rekor)["reasons"], ["entry_missing"])
        refused = R.entry_reasons({uuid: entry}.get, WORKFLOW, ("sigstore",), lambda argv: 1)
        self.assertEqual(AN.judge(LEDGER, other, refused)["reasons"], ["root_mismatch", "entry_root_mismatch"])
        self.assertEqual(AN.judge(LEDGER, roots, refused)["reasons"], ["entry_unverified"])


if __name__ == "__main__":
    unittest.main()
