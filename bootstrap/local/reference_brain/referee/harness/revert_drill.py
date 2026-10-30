"""MF14 revert drill (asama-0/14:41, 09:74, 22a:44-53): commit, reveal, judge.

commit/reveal <catalog.json> <seed.json>, stdin {"cycle_id": "<decimal digits>"}.
judge <ledger.jsonl> <key.json>, no stdin.
"""
import hashlib
import hmac
import json
import re
import sys

from ledger._common import NotCanonical, canonical_bytes, sha256_hex, verify  # A's helpers, beside MF1

_DIGITS = re.compile(r"[0-9]+")
_KEY_FIELDS = ("cycle_id", "selection", "instance_id", "cause")


class Unusable(Exception):
    pass


def _emit(obj, code):
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()
    return code


def _read(path):
    try:
        with open(path, "rb") as fh:
            return fh.read()
    except OSError as exc:
        raise Unusable(str(exc)) from exc


def _json_file(path):
    try:
        return json.loads(_read(path).decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise Unusable(str(exc)) from exc


def _stdin_json():
    try:
        return json.loads(sys.stdin.buffer.read().decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise Unusable(str(exc)) from exc


def answer_key(catalog_path, seed_path, request):
    catalog = _json_file(catalog_path)
    if not isinstance(catalog, dict):
        raise Unusable("catalog not an object")
    instances = catalog.get("instances")
    if not isinstance(instances, list) or not instances:
        raise Unusable("empty or missing instances")
    seen = set()
    pairs = []
    for inst in instances:
        if not isinstance(inst, dict):
            raise Unusable("instance not an object")
        iid, cause = inst.get("id"), inst.get("cause")
        if not isinstance(iid, str) or not iid or not isinstance(cause, str):
            raise Unusable("instance without id or cause")
        if iid in seen:
            raise Unusable("duplicate id")
        seen.add(iid)
        pairs.append((iid, cause))
    seed_doc = _json_file(seed_path)
    if not isinstance(seed_doc, dict) or not isinstance(seed_doc.get("seed"), str):
        raise Unusable("seed")
    if not isinstance(request, dict):
        raise Unusable("stdin not an object")
    cycle_id = request.get("cycle_id")
    if not isinstance(cycle_id, str) or not _DIGITS.fullmatch(cycle_id):
        raise Unusable("cycle_id")
    try:
        seed_bytes = seed_doc["seed"].encode("utf-8")
    except UnicodeEncodeError as exc:
        raise Unusable("seed not UTF-8 encodable") from exc
    selection = hmac.new(seed_bytes, cycle_id.encode("utf-8"), hashlib.sha256).hexdigest()
    pairs.sort(key=lambda p: p[0])  # code-point order of id; file order never matters
    iid, cause = pairs[int(selection, 16) % len(pairs)]
    return {"cycle_id": cycle_id, "selection": selection, "instance_id": iid, "cause": cause}


def key_sha256(key):
    return sha256_hex(canonical_bytes({f: key[f] for f in _KEY_FIELDS}))


def _payload(row):
    p = row.get("payload")
    return p if isinstance(p, dict) else {}


def _is(row, part, kind):
    return row.get("part") == part and row.get("kind") == kind


def judge_rows(rows, key):
    plants = [i for i, r in enumerate(rows) if _is(r, "drill", "plant") and _payload(r).get("drill") == "revert"]
    if not plants:
        return ["not_planted"]
    p_idx = plants[-1]
    plant = _payload(rows[p_idx])
    reasons = set()
    commits = [i for i in range(p_idx) if _is(rows[i], "drill", "commit") and _payload(rows[i]).get("drill") == "revert"]
    if not commits:
        reasons.add("commitment_not_before_run")
    elif _payload(rows[commits[-1]]).get("commitment_sha256") != key_sha256(key):
        reasons.add("commitment_mismatch")
    if plant.get("instance_id") != key["instance_id"]:
        reasons.add("instance_mismatch")
    merge_sha = plant.get("merge_sha")
    revert = None
    if isinstance(merge_sha, str):
        for r in rows[p_idx + 1:]:
            if _is(r, "events", "revert") and _payload(r).get("merge_sha") == merge_sha:
                revert = r
                break
    if revert is None:
        reasons.add("not_reverted")
    elif revert.get("cause") != key["cause"]:
        reasons.add("cause_mismatch")
    return sorted(reasons)


def _judge(ledger_path, key_path):
    data = _read(ledger_path)
    key = _json_file(key_path)
    if not isinstance(key, dict) or not all(isinstance(key.get(f), str) for f in _KEY_FIELDS):
        raise Unusable("key")
    try:
        key_sha256(key)
    except (NotCanonical, UnicodeEncodeError) as exc:
        raise Unusable("key not canonicalizable") from exc
    valid, rows = verify(data)
    reasons = ["chain_broken"] if not valid else judge_rows(rows, key)
    return _emit({"verdict": "FAIL" if reasons else "PASS", "reasons": reasons}, 1 if reasons else 0)


def main(argv):
    verb = argv[1] if len(argv) > 1 else None
    if verb in ("commit", "reveal"):
        null_line = {"commitment_sha256": None} if verb == "commit" else {"key": None, "revealed_sha256": None}
        try:
            if len(argv) != 4:
                raise Unusable("usage")
            key = answer_key(argv[2], argv[3], _stdin_json())
            digest = key_sha256(key)
        except (Unusable, NotCanonical, UnicodeEncodeError):
            return _emit(null_line, 2)
        if verb == "commit":
            return _emit({"commitment_sha256": digest}, 0)  # the key itself is never printed
        return _emit({"key": key, "revealed_sha256": digest}, 0)
    if verb == "judge":
        try:
            if len(argv) != 4:
                raise Unusable("usage")
            return _judge(argv[2], argv[3])
        except Unusable:
            return _emit({"verdict": "FAIL"}, 2)
    return _emit({"error": "usage: commit|reveal|judge"}, 2)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
