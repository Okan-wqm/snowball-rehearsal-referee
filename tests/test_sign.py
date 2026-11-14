"""Test 40 (asama-0/09, MF11's signature): ``loop.sign.SigstoreSigner``, the cycle root's real signer.

- a real bundle of ``sigstore sign`` (``fixtures/rekor-entry.json`` ``published``) over the file it signed
  (``fixtures/sigstore-signed-payload``): the answer is ``{uuid: the body's leaf hash, identity: pin}`` and the uuid
  is the one Rekor serves the entry under; the two runs are ``sign --rekor-version 1 --bundle`` of the payload file
  (holding exactly the payload) and ``verify identity`` of that bundle with the pin;
- each refusal alone, each ``Unsignable`` (a hard stop): sign exits non-zero, no bundle, a bundle too large, not
  JSON, with no or two tlog entries, recording another digest, of another kind or of ``0.0.2`` (Rekor v2's), the
  verifier refusing the pin; a refusal before the verifier runs nothing more;
- round trip: ``ledger.anchor.anchor`` with this signer gives the entry that ``loop.rekor.entry_reasons`` (the next
  D1) finds and accepts for the same root, and a root of another ledger is refused there;
- the default runner on a real process: a fake ``sigstore`` program on disk; one that cannot start is unsignable.

Real ``sigstore`` 4.5.1 on the two fixtures (session of 2026-11-01): ``verify identity`` exits 0 with the fixture's
identity and 1 with another (``tests/fixtures/rekor-entry.json`` ``verdicts`` records the same on the bundle
``loop.rekor`` makes); ``sigstore sign --help`` names ``--rekor-version`` (1 or 2, default the highest available).
"""

from __future__ import annotations

import base64
import copy
import hashlib
import json
import os
import stat
import sys
import tempfile
import unittest

REFEREE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, REFEREE)
sys.path.insert(0, HERE)

from ledger import anchor as AN  # noqa: E402
from loop import accepted as A  # noqa: E402
from loop import rekor as R  # noqa: E402
from loop import sign as S  # noqa: E402
from test_anchor import LEDGER  # noqa: E402
from test_rekor import REAL, REAL_ENTRY  # noqa: E402

PIN = "https://github.com/acme/referee/.github/workflows/loop.yml@refs/heads/main"
with open(os.path.join(HERE, "fixtures", "sigstore-signed-payload"), "rb") as _fh:
    SIGNED = _fh.read()


def bundle_for(digest: str | None = None, kind: str = "hashedrekord", version: str = "0.0.1",
               entries: int = 1) -> dict:
    """The real published bundle; with ``digest``, ``kind`` or ``version`` its body rewritten (no signature here is
    valid then: the verifier is a fake)."""
    made = copy.deepcopy(REAL["published"])
    tlog = made["verificationMaterial"]["tlogEntries"]
    if digest is not None or kind != "hashedrekord" or version != "0.0.1":
        body = json.loads(base64.b64decode(tlog[0]["canonicalizedBody"]))
        body["kind"], body["apiVersion"] = kind, version
        if digest is not None:
            body["spec"]["data"]["hash"]["value"] = digest
        tlog[0]["canonicalizedBody"] = base64.b64encode(json.dumps(body).encode()).decode()
    made["verificationMaterial"]["tlogEntries"] = (tlog * entries)[:entries]
    return made


def leaf(body_b64: str) -> str:
    return hashlib.sha256(b"\x00" + base64.b64decode(body_b64)).hexdigest()


class Program:
    """A fake ``run``: ``sign`` writes ``bundle`` (bytes, or None for nothing) and exits ``sign_exit``; ``verify``
    exits ``verify_exit``. Keeps every argv and the payload file's bytes at sign time."""

    def __init__(self, bundle, sign_exit=0, verify_exit=0):
        self.bundle, self.sign_exit, self.verify_exit = bundle, sign_exit, verify_exit
        self.argvs, self.signed = [], None

    def __call__(self, argv):
        self.argvs.append(list(argv))
        if next(a for a in argv if a in ("sign", "verify")) == "sign":
            with open(argv[-1], "rb") as fh:
                self.signed = fh.read()
            if self.bundle is not None:
                with open(argv[argv.index("--bundle") + 1], "wb") as fh:
                    fh.write(self.bundle if isinstance(self.bundle, bytes) else json.dumps(self.bundle).encode())
            return self.sign_exit
        return self.verify_exit


class RealBundle(unittest.TestCase):
    def test_answers_the_leaf_hash_and_the_pin(self):
        written = json.dumps(REAL["published"], indent=1).encode() + b"\n"
        run = Program(written)
        answer = S.SigstoreSigner(PIN, ("/opt/python", "-m", "sigstore"), run).sign(SIGNED)
        # the bundle is the file's bytes as the program wrote them, not a rewriting of them
        self.assertEqual(answer, {"uuid": REAL["uuid"][-64:], "identity": PIN, "bundle": written})
        self.assertEqual(R.checked_answer(answer["uuid"], json.loads(REAL["answer"])), REAL_ENTRY)  # Rekor's entry
        sign, verify = run.argvs
        bundle, payload = sign[7], sign[8]
        # the program is an argv prefix: the sigstore step's venv as ``python -m sigstore`` (tohum/29s)
        self.assertEqual(sign, ["/opt/python", "-m", "sigstore", "sign", "--rekor-version", "1", "--bundle", bundle,
                                payload])
        self.assertEqual(verify, A.identity_argv(("/opt/python", "-m", "sigstore"), bundle, PIN, payload))
        self.assertEqual(run.signed, SIGNED)
        self.assertNotEqual(bundle, payload)
        self.assertFalse(os.path.exists(bundle))  # the fresh directory is gone

    def test_empty_pin_is_refused(self):
        for bad in ("", None):
            with self.assertRaises(ValueError):
                S.SigstoreSigner(bad, ("sigstore",))


class Refusals(unittest.TestCase):
    def refused(self, run, payload=SIGNED, runs=2):
        with self.assertRaises(AN.Unsignable):
            S.SigstoreSigner(PIN, ("sigstore",), run).sign(payload)
        self.assertEqual(len(run.argvs), runs)
        self.assertTrue(issubclass(AN.Unsignable, AN.append.HardStop))

    def test_sign_fails(self):
        self.refused(Program(REAL["published"], sign_exit=1), runs=1)

    def test_no_bundle(self):
        self.refused(Program(None), runs=1)

    def test_bundle_too_large(self):
        self.refused(Program(json.dumps(REAL["published"]).encode().ljust(R.MAX_ANSWER + 1)), runs=1)  # valid JSON
        S.SigstoreSigner(PIN, ("s",), Program(json.dumps(REAL["published"]).encode().ljust(R.MAX_ANSWER))).sign(SIGNED)

    def test_bundle_not_json(self):
        self.refused(Program(b"{"), runs=1)

    def test_tlog_entries_not_one(self):
        for n in (0, 2):
            self.refused(Program(bundle_for(entries=n)), runs=1)
        self.refused(Program({"verificationMaterial": {"tlogEntries": {"0": {}}}}), runs=1)

    def test_another_digest(self):
        self.refused(Program(REAL["published"]), payload=SIGNED + b"\n", runs=1)
        self.refused(Program(bundle_for(digest="0" * 64)), runs=1)

    def test_another_kind_or_rekor_v2(self):
        self.refused(Program(bundle_for(kind="dsse")), runs=1)
        self.refused(Program(bundle_for(version="0.0.2")), runs=1)

    def test_verifier_refuses_the_pin(self):
        self.refused(Program(REAL["published"], verify_exit=1), runs=2)


class RoundTrip(unittest.TestCase):
    """What the signer answers is what the next D1 reads and accepts."""

    def test_anchor_then_next_d1(self):
        tip_map = AN.tips(LEDGER)
        root = AN.root_of(tip_map)
        made = bundle_for(digest=root)  # tohum/26d "Kök": the record's spec.data.hash is the root itself
        body = made["verificationMaterial"]["tlogEntries"][0]["canonicalizedBody"]
        program = Program(made)
        entry, bundle = AN.anchor(tip_map, S.SigstoreSigner(PIN, ("sigstore",), program))
        self.assertEqual(entry, {"uuid": leaf(body), "hash": root, "identity": PIN})
        self.assertEqual(hashlib.sha256(program.signed).hexdigest(), root)  # the file sigstore hashed
        self.assertEqual(json.loads(bundle), made)
        rekor = {entry["uuid"]: dict(copy.deepcopy(REAL_ENTRY), body=body)}
        seen = []
        judge = R.entry_reasons(rekor.get, PIN, ("sigstore",), lambda argv: seen.append(argv) or 0)
        self.assertEqual(judge(entry["uuid"], root), [])
        self.assertEqual(seen[0][seen[0].index("--cert-identity") + 1], PIN)
        self.assertEqual(seen[0][-1], "sha256:" + root)  # the digest stage-open verifies the bundle for
        self.assertEqual(judge(entry["uuid"], "cd" * 32), ["entry_root_mismatch"])

    def test_a_record_of_a_digest_of_the_root_is_not_signed(self):
        tip_map = AN.tips(LEDGER)
        of_the_text = hashlib.sha256(AN.root_of(tip_map).encode("ascii")).hexdigest()
        program = Program(bundle_for(digest=of_the_text))
        with self.assertRaises(AN.Unsignable):
            AN.anchor(tip_map, S.SigstoreSigner(PIN, ("sigstore",), program))
        self.assertEqual(len(program.argvs), 1)  # refused on the bundle's body, before the verifier


class RealProcess(unittest.TestCase):
    def test_default_runner_runs_the_program(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = os.path.join(tmp, "bundle.json")
            with open(source, "w") as fh:
                json.dump(REAL["published"], fh)
            program = os.path.join(tmp, "sigstore")
            with open(program, "w") as fh:
                fh.write("#!%s\nimport shutil, sys\nargv = sys.argv[1:]\n"
                         "if argv[0] == 'sign':\n    shutil.copy(%r, argv[argv.index('--bundle') + 1])\n"
                         "sys.exit(0 if argv[0] == 'sign' or %r in argv else 1)\n" % (sys.executable, source, PIN))
            os.chmod(program, os.stat(program).st_mode | stat.S_IXUSR)
            self.assertEqual(S.SigstoreSigner(PIN, (program,)).sign(SIGNED)["uuid"], REAL["uuid"][-64:])
            with self.assertRaises(AN.Unsignable):
                S.SigstoreSigner(PIN + "x", (program,)).sign(SIGNED)
            with self.assertRaises(AN.Unsignable):
                S.SigstoreSigner(PIN, (os.path.join(tmp, "absent"),)).sign(SIGNED)


if __name__ == "__main__":
    unittest.main()
