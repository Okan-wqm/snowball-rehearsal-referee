"""MF15 llm.call, the plan verb (asama-0/14:42, 09:61, tohum/08:22,71-72).

python -m dispatcher.llm_call plan <template.json>; stdin {model, input{}, budget{stage_cap_usd_micros,
spent_usd_micros, call_cap_usd_micros}}. Builds the prompt from typed input, scans it with MF2's prompt
rule, applies the stage brake and plans the argv of the pinned tool-less `claude -p`. Nothing is executed.

MF15 calls this brain's MF2 (`gate.secrets.scan_text`, the prompt rule of 29f) in place of A's own `gate/secrets.py`,
which held that rule only; A's ledger helpers are `ledger/_common.py`, beside this brain's MF1.
"""
import hashlib
import json
import re
import sys

from gate import secrets
from ledger._common import NotCanonical, canonical

_PLACEHOLDER = re.compile(r"\{\{([A-Za-z_][A-Za-z0-9_]*)\}\}")
_TYPES = ("string", "integer")
_BUDGET = ("stage_cap_usd_micros", "spent_usd_micros", "call_cap_usd_micros")


class Unusable(Exception):
    pass


def _emit(obj, code):
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()
    return code


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _typed(value, kind):
    return isinstance(value, str) if kind == "string" else _is_int(value)


def usd(micros):
    """Integer micros -> '<units>.<6 digits>' with no float arithmetic (26:31-33)."""
    return "%d.%06d" % divmod(micros, 1_000_000)


def _load_template(path):
    try:
        with open(path, "rb") as fh:
            tpl = json.loads(fh.read().decode("utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise Unusable("template") from exc
    if not isinstance(tpl, dict) or not isinstance(tpl.get("fields"), dict) or not isinstance(tpl.get("text"), str):
        raise Unusable("template shape")
    if not all(kind in _TYPES for kind in tpl["fields"].values()):
        raise Unusable("field type")
    return tpl["fields"], tpl["text"]


def _load_request():
    try:
        req = json.loads(sys.stdin.buffer.read().decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise Unusable("request") from exc
    if not isinstance(req, dict) or not isinstance(req.get("model"), str) or not isinstance(req.get("input"), dict):
        raise Unusable("request shape")
    budget = req.get("budget")
    if not isinstance(budget, dict) or not all(_is_int(budget.get(k)) and budget[k] >= 0 for k in _BUDGET):
        raise Unusable("budget")
    return req["model"], req["input"], budget


def render(fields, text, values):
    """One left-to-right pass; each {{name}} becomes the RFC 8785 JSON of the typed value; never rescanned."""
    def substitute(match):
        name = match.group(1)
        if name not in fields:
            raise Unusable("placeholder names an undeclared field")
        return canonical(values[name])
    return _PLACEHOLDER.sub(substitute, text)


def argv_for(model, max_budget_usd):
    """The pinned tool-less CLI call; the prompt goes on stdin."""
    return ["claude", "-p", "--model", model, "--tools", "", "--setting-sources", "",
            "--disable-slash-commands", "--no-session-persistence", "--max-budget-usd", max_budget_usd]


def plan(template_path):
    fields, text = _load_template(template_path)
    model, given, budget = _load_request()
    for name, kind in fields.items():
        if name not in given or not _typed(given[name], kind):
            raise Unusable("declared field missing or wrongly typed")
    values = {name: given[name] for name in fields}
    dropped = sorted(name for name in given if name not in fields)
    try:
        prompt = render(fields, text, values)
        prompt_bytes = prompt.encode("utf-8")
    except (NotCanonical, UnicodeEncodeError) as exc:
        raise Unusable("prompt not encodable") from exc
    reasons = []
    if secrets.scan_text(prompt):
        reasons.append("secret_in_prompt")
    remaining = budget["stage_cap_usd_micros"] - budget["spent_usd_micros"]
    if remaining <= 0:
        reasons.append("stage_brake")
    reasons.sort()
    send = not reasons
    max_budget = usd(min(budget["call_cap_usd_micros"], remaining)) if send else None
    out = {
        "send": send,
        "reasons": reasons,
        "prompt_sha256": hashlib.sha256(prompt_bytes).hexdigest(),
        "dropped": dropped,
        "max_budget_usd": max_budget,
        "argv": argv_for(model, max_budget) if send else [],
    }
    return out, 0 if send else 1


def main(argv):
    if len(argv) != 3 or argv[1] != "plan":
        return _emit({"send": False}, 2)
    try:
        out, code = plan(argv[2])
    except Unusable:
        return _emit({"send": False}, 2)
    return _emit(out, code)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
