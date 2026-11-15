"""Capture of ``fixtures/rekor-entry.json``: a real Rekor entry signed by a GitHub Actions workflow, the bundle its
signer published, and real ``sigstore``'s verdicts on the bundle ``loop.rekor`` makes from the entry (tests only;
needs the network and a ``sigstore`` program, given as the first argument).

The entry: the release of ``sigstore/gh-action-sigstore-python`` v3.5.0 published ``action.yml.sigstore.json``, a
``hashedrekord`` signed by its release workflow. Its ``logIndex`` gives the entry's uuid (Rekor's
``?logIndex=`` query); one answer is kept, and ``loop.rekor.RekorHttp().entry(uuid)`` reads the same entry the way
D1 does. ``IDENTITY`` is the release workflow's certificate identity for that tag. Verdicts, each the exit code of
``loop.accepted.identity_argv`` with the bundle ``loop.rekor.bundle`` makes: ``good`` (the identity, the entry's
digest), ``other_identity``, ``other_digest``, ``other_proof`` (one inclusion-proof hash changed). The bundle made
is kept (``made``), so a change of ``loop.rekor.bundle`` shows against the bytes ``sigstore`` judged. Run from
``referee/``: ``python tests/capture_rekor_entry.py /path/to/sigstore > tests/fixtures/rekor-entry.json``.
"""

import json
import os
import subprocess
import sys
import tempfile
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from loop import accepted as A  # noqa: E402
from loop import rekor as R  # noqa: E402

TAG = "v3.5.0"
PUBLISHED = "https://github.com/sigstore/gh-action-sigstore-python/releases/download/%s/action.yml.sigstore.json" % TAG
IDENTITY = "https://github.com/sigstore/gh-action-sigstore-python/.github/workflows/release.yml@refs/tags/%s" % TAG


def get(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=60) as resp:
        return resp.read()


def verdict(sigstore: str, made: dict, identity: str, digest: str) -> int:
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "b.json")
        with open(path, "w") as fh:
            json.dump(made, fh)
        return subprocess.run(A.identity_argv((sigstore,), path, identity, "sha256:" + digest),
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode


def main(sigstore: str) -> None:
    published = json.loads(get(PUBLISHED))
    index = published["verificationMaterial"]["tlogEntries"][0]["logIndex"]
    (uuid, _), = json.loads(get(R.REKOR[:-1] + "?logIndex=%s" % index)).items()
    answer = get(R.REKOR + uuid).decode()
    entry = R.checked_answer(uuid, json.loads(answer))  # Rekor proves anew on each read: one answer for all below
    assert R.RekorHttp().entry(uuid)["body"] == entry["body"]
    body = R.body_of(entry)
    made = R.bundle(entry, body)
    digest = body["spec"]["data"]["hash"]["value"]
    bad = json.loads(json.dumps(made))
    hashes = bad["verificationMaterial"]["tlogEntries"][0]["inclusionProof"]["hashes"]
    hashes[0] = ("B" if hashes[0][0] != "B" else "C") + hashes[0][1:]
    verdicts = {"good": verdict(sigstore, made, IDENTITY, digest),
                "other_identity": verdict(sigstore, made, IDENTITY.replace(TAG, "v0.0.0"), digest),
                "other_digest": verdict(sigstore, made, IDENTITY, "0" * 64),
                "other_proof": verdict(sigstore, bad, IDENTITY, digest)}
    version = subprocess.run([sigstore, "--version"], capture_output=True, text=True).stdout.strip()
    json.dump({"published_url": PUBLISHED, "published": published, "uuid": uuid, "answer": answer,
               "made": made, "identity": IDENTITY, "digest": digest, "sigstore": version, "verdicts": verdicts},
              sys.stdout, indent=1, sort_keys=True)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main(sys.argv[1])
