"""MF16 status.block, smallest form (asama-0/14:43, 09:66).

python -m status.block render <ledger.jsonl> <imports.jsonl> <status.md>; stdin {"canary_cap_usd_micros": int}.
Fields come from the ledger and imports.jsonl alone; the block found in status.md is compared by sha256 with
the last events status row's block_sha256. render writes nothing.
"""
import calendar
import datetime
import hashlib
import json
import re
import sys

OPEN = b"<!-- status.block -->"
CLOSE = b"<!-- /status.block -->"
_TS = re.compile(r"([0-9]{4})-([0-9]{2})-([0-9]{2})T([0-9]{2}):([0-9]{2}):([0-9]{2})Z")


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


def _jsonl(path):
    pieces = _read(path).split(b"\n")
    if pieces and pieces[-1] == b"":
        pieces.pop()
    rows = []
    for piece in pieces:
        try:
            row = json.loads(piece.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise Unusable("line not JSON") from exc
        if not isinstance(row, dict):
            raise Unusable("line not a JSON object")
        rows.append(row)
    return rows


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _epoch(ts):
    m = _TS.fullmatch(ts) if isinstance(ts, str) else None
    if not m:
        raise Unusable("ts format")
    parts = tuple(int(g) for g in m.groups())
    try:
        datetime.datetime(*parts)
    except ValueError as exc:
        raise Unusable("ts not a date") from exc
    return calendar.timegm(parts + (0, 0, 0))


def _payload(row):
    p = row.get("payload")
    return p if isinstance(p, dict) else {}


def _str_or_none(v):
    return v if isinstance(v, str) else None


def find_block(data):
    """Bytes after the LF ending the opening marker line up to the first byte of the next closing line."""
    lines = []
    pos = 0
    while pos < len(data):
        nl = data.find(b"\n", pos)
        end = len(data) if nl == -1 else nl
        lines.append((pos, end, len(data) if nl == -1 else nl + 1))
        pos = lines[-1][2]
    opens = [i for i, (s, e, _) in enumerate(lines) if data[s:e] == OPEN]
    if not opens:
        return None
    if len(opens) > 1:
        raise Unusable("two opening markers")
    first = opens[0]
    for s, e, _ in lines[first + 1:]:
        if data[s:e] == CLOSE:
            return data[lines[first][2]:s]
    raise Unusable("opening marker without its closing line")


def fields(rows, imports, cap):
    events = [r for r in rows if r.get("part") == "events"]
    starts = [r for r in events if r.get("kind") == "cycle_start"]
    decisions = [r for r in events if r.get("kind") == "decision"]
    geneses = [r for r in events if r.get("kind") == "genesis"]
    statuses = [r for r in events if r.get("kind") == "status"]
    base_age = None
    if starts and geneses:
        base_age = _epoch(starts[-1].get("ts")) - _epoch(geneses[0].get("ts"))
    spent = 0
    for r in rows:
        if r.get("part") == "cost":
            micros = _payload(r).get("usd_micros")
            if not _is_int(micros):
                raise Unusable("cost row without integer usd_micros")
            spent += micros
    return {
        "cycle_id": _str_or_none(_payload(starts[-1]).get("cycle_id")) if starts else None,
        "last_decision": _str_or_none(_payload(decisions[-1]).get("decision")) if decisions else None,
        "base_age_s": base_age,
        "brake": {"spent_usd_micros": spent, "cap_usd_micros": cap, "engaged": spent >= cap},
        "human_touches": len(imports),
    }, (_str_or_none(_payload(statuses[-1]).get("block_sha256")) if statuses else None)


def render_block(f):
    def show(v):
        return "none" if v is None else str(v)
    brake = f["brake"]
    return (
        "Cycle: %s\n" % show(f["cycle_id"])
        + "Last decision: %s\n" % show(f["last_decision"])
        + "Base age: %s s\n" % show(f["base_age_s"])
        + "Brake: %d of %d USD micros spent%s\n" % (brake["spent_usd_micros"], brake["cap_usd_micros"],
                                                    " (engaged)" if brake["engaged"] else "")
        + "Human touches: %d\n" % f["human_touches"]
    )


def render(ledger_path, imports_path, status_path):
    try:
        req = json.loads(sys.stdin.buffer.read().decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise Unusable("stdin") from exc
    cap = req.get("canary_cap_usd_micros") if isinstance(req, dict) else None
    if not _is_int(cap) or cap < 0:
        raise Unusable("cap")
    rows = _jsonl(ledger_path)
    imports = _jsonl(imports_path)
    block = find_block(_read(status_path))
    out, recorded = fields(rows, imports, cap)
    found = hashlib.sha256(block).hexdigest() if block is not None else None
    edited = found != recorded
    out["edited"] = edited
    out["event"] = ({"kind": "status_edited", "payload": {"found_sha256": found, "recorded_sha256": recorded}}
                    if edited else None)
    text = render_block(out)
    out["block"] = text
    out["block_sha256"] = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return out, 1 if edited else 0


def main(argv):
    if len(argv) != 5 or argv[1] != "render":
        return _emit({"edited": None}, 2)
    try:
        out, code = render(argv[2], argv[3], argv[4])
    except Unusable:
        return _emit({"edited": None}, 2)
    return _emit(out, code)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
