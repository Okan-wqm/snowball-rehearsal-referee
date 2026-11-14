"""``llm.call``: one tool-less model call through the pinned ``claude`` CLI, from typed input, with its ``cost``
row (stage 0, MF15).

Rules: tohum/29m (``prompt``: the template, the typed input, dropping, placeholders, the scan, the brake, the plan's
output), asama-0/14 row 15, asama-0/09 test 37, asama-0/12 (the stage brake), tohum/24 ("Araçsız çağrı", "Kaçış":
429 and other outages are not rejections, no silent retry inside a run; the call cap is ``min(call cap, what the
stage leaves)``), tohum/26a (``llm.call``), tohum/06 (the cost is the CLI's list-price estimate; on a timeout the
cap is written), tohum/08 item 11 (a prompt is scanned, a match is not sent).

**Template** (``check_template``): ``{fields: {name: "string" | "integer"}, text: string}`` and optionally
``output`` (the structured output's type, read only by ``call``: ``{name: kind}``, at least one field, kinds
``string``, ``integer``, ``boolean``, ``strings``); no other key. Names match ``[A-Za-z_][A-Za-z0-9_]*``. In
``text`` every ``{{`` starts a placeholder that must be ``{{name}}`` with a declared name; any other ``{{`` (a
space, a bad or undeclared name, no closing ``}}``) makes the request unusable. Single braces and a ``}}`` that
closes no placeholder are text.

**Typed input** (``build``): every declared field is in ``input`` with its type (a JSON string; a JSON integer
within +-(2^53-1), never ``true``); an input field the template does not declare is dropped, named in
``dropped`` (sorted), and never reaches the prompt. The prompt is ``text`` with each placeholder replaced, left to
right in one pass, by the field's RFC 8785 JSON (``ledger.chain.canonical``: a string quoted and escaped, an integer
in digits); the inserted text is not scanned again, so a value cannot expand a placeholder, close its quotes or
add a line. ``prompt_sha256`` is the sha256 of the prompt's UTF-8 bytes alone.

**Plan** (``plan``), nothing run: the request is ``{model: non-empty string, input, budget:
{stage_cap_usd_micros, spent_usd_micros, call_cap_usd_micros}}`` (integers >= 0; the caller turns the spend and
``canary_usd`` into micro-USD). Reasons, sorted: ``secret_in_prompt`` when ``gate.secrets.scan`` (kind ``prompt``,
MF2) matches in the built prompt; ``stage_brake`` when ``stage_cap - spent <= 0``. With no reason the call is sent
with cap ``min(call_cap, stage_cap - spent)`` and ``max_budget_usd`` is that cap as ``"<units>.<6 digits>"`` USD;
otherwise ``max_budget_usd`` is null. The argv is the pinned CLI's (``command``).

**A call** (``call``): the plan, with the provider token as a known value for the scan; nothing is started and no
row is written when it is not sent (outcome ``secret`` or ``brake``). Otherwise:

1. The CLI file's sha512 must equal the pin (``Unusable`` otherwise). The file is hashed, then executed by
   path: a file swapped between the two is out of reach of this check.
2. One process, no retry: ``claude -p`` with ``ARGS`` (no built-in tool, no setting source, no MCP server,
   no slash command, no session persistence), ``--model``, ``--max-budget-usd`` the cap, and ``--json-schema``
   from ``output`` when the template has one; JSON output; the prompt on stdin, never in argv; the working
   directory a fresh empty directory; the environment exactly ``PATH`` (inherited), ``HOME`` and
   ``CLAUDE_CONFIG_DIR`` (fresh empty directories), ``CLAUDE_CODE_DISABLE_AUTO_MEMORY=1`` and
   ``CLAUDE_CODE_OAUTH_TOKEN`` when given. Nothing else of the caller's environment reaches it.
3. The result is classified (``classify``, the first rule that holds):

   - the process ran past ``timeout_s``: ``outage`` / ``timeout``, cost = cap;
   - stdout is not one JSON object with ``type: result``, a ``total_cost_usd`` number >= 0 (at most 2^53-1
     micro-USD once rounded up) and a ``modelUsage`` object: ``unresolved`` / ``malformed_result``, cost = cap;
   - otherwise the cost is ``total_cost_usd`` rounded up to a micro-USD, computed exactly from the number's
     JSON text (``to_micros``: never a float, no decimal context, any exponent), and the served models are
     ``modelUsage``'s keys;
   - ``subtype: error_max_budget_usd``: ``unresolved`` / ``over_budget``;
   - ``is_error`` anything but ``false``, or another ``subtype``: by the status in ``API Error: NNN`` of ``result``: 429
     ``outage`` / ``quota``; 401 and 403 ``outage`` / ``identity``; 5xx ``outage`` / ``server``; 400, 404, 413,
     422 ``request_rejected`` / ``http_NNN``; any other status, or none, ``unresolved`` / ``cli_error``;
   - the cost is above the cap: ``unresolved`` / ``over_budget``;
   - ``stop_reason: refusal``: ``unresolved`` / ``refusal``;
   - the served models are not exactly the requested one: ``unresolved`` / ``model_mismatch``;
   - the template has an ``output`` type and ``structured_output`` is not a value of it: ``unresolved`` /
     ``malformed_output``;
   - else ``ok``, the run is valid, and ``output`` is ``structured_output`` (null without an ``output`` type).

4. Every started process gives one ``cost`` row (part ``cost``, kind ``cost``), recorded in the ``CostBook``
   before ``call`` returns, whatever the outcome; the book's ``request()`` is the cycle's ``ledger.append``
   input (calls 10 -> 15: one ``brain/state`` commit per cycle). The payload's ``usd_micros`` is the cost, the
   field ``status.block``'s brake sums (tohum/29n). The row holds no float and no free text from the CLI but the
   served model names.

**The book** (``CostBook``) reads the ledger only once it is a valid chain extending ``previous``
(``ledger.chain.verify_bytes``) or raises ``ledger.append.HardStop``. ``spent()`` is ``spent_micros`` over the
ledger's rows and those recorded since: the sum of ``payload.usd_micros`` over every ``part: cost`` row, one
rule for this module's brake and ``status.block``'s; a ``cost`` row without an integer ``usd_micros`` >= 0 is
``Unusable`` (the brake cannot be computed, so no call).

Out of scope, stated: whether the real CLI's JSON matches the shapes above (the fake here follows them; the real
call is asama-0/10a ``#model``); a network error without a status (``cli_error``, not ``outage``); the API-key
path for sale (tohum/24); where the template, model, caps and the stage's spend come from (``policy.json``, the
caller); a system prompt (none is passed: the template's text is the whole prompt).

Command line, run from ``referee/``, one JSON line on stdout, the cause of an error on stderr::

    python -m dispatcher.llm_call plan TEMPLATE   stdin {model, input, budget}
        -> {send, reasons, prompt_sha256, dropped, max_budget_usd, argv}
    exit 0 sent; 1 not sent (a stop, not a rejection); 2 unusable request ({"send": false}).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from typing import Any

from gate import secrets
from ledger import append, chain
import cli

INPUT_TYPES = ("string", "integer")
OUTPUT_TYPES = ("string", "integer", "boolean", "strings")
NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
PLACEHOLDER = re.compile(r"\{\{([A-Za-z_][A-Za-z0-9_]*)\}\}")
TEMPLATE = {"fields", "text"}
TEMPLATE_OPTIONAL = {"output"}
BUDGET = ("stage_cap_usd_micros", "spent_usd_micros", "call_cap_usd_micros")
REQUEST = {"model", "input", "budget"}
REASONS = ("secret_in_prompt", "stage_brake")
TOKEN_ENV = "CLAUDE_CODE_OAUTH_TOKEN"
ARGS = ("-p", "--output-format", "json", "--tools", "", "--setting-sources", "", "--strict-mcp-config",
        "--disable-slash-commands", "--no-session-persistence")
PART = KIND = "cost"
OUTCOMES = ("ok", "outage", "request_rejected", "unresolved", "secret", "brake")
OUTAGE_STATUS = {429: "quota", 401: "identity", 403: "identity"}
REJECTED_STATUS = (400, 404, 413, 422)
API_STATUS = re.compile(r"API Error: (\d{3})\b")
HEX = set("0123456789abcdef")


class Unusable(ValueError):
    pass


# ---------------------------------------------------------------- types, the template, the prompt

def check_type(spec: Any, kinds: tuple[str, ...], what: str, non_empty: bool) -> dict:
    if not isinstance(spec, dict) or (non_empty and not spec):
        raise Unusable("%s must be an object {name: kind}%s" % (what, " with a field" if non_empty else ""))
    for name, kind in spec.items():
        if not NAME.match(name):
            raise Unusable("%s: field name %r must match [A-Za-z_][A-Za-z0-9_]*" % (what, name))
        if kind not in kinds:
            raise Unusable("%s: field %s has kind %r, not one of %s" % (what, name, kind, ", ".join(kinds)))
    return spec


def _of_kind(value: Any, kind: str) -> bool:
    if kind == "string":
        return isinstance(value, str)
    if kind == "integer":
        return type(value) is int and abs(value) <= chain.MAX_SAFE_INT
    if kind == "boolean":
        return type(value) is bool
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def check_value(spec: dict, value: Any, what: str) -> dict:
    """``value`` has exactly ``spec``'s fields, each of its kind (the structured output); otherwise ``Unusable``."""
    if not isinstance(value, dict) or set(value) != set(spec):
        raise Unusable("%s must have exactly the fields %s" % (what, sorted(spec)))
    for name, kind in spec.items():
        if not _of_kind(value[name], kind):
            raise Unusable("%s: field %s is not a %s" % (what, name, kind))
    return value


def _pieces(text: str, fields: dict) -> list[tuple[str, str]]:
    """``text`` as ``("text", s)`` and ``("field", name)`` pieces; every ``{{`` must open ``{{name}}`` with a
    declared name."""
    pieces, i = [], 0
    while True:
        at = text.find("{{", i)
        if at < 0:
            return pieces + [("text", text[i:])]
        match = PLACEHOLDER.match(text, at)
        if not match:
            raise Unusable("template text: the {{ at %d is not {{name}}" % at)
        if match.group(1) not in fields:
            raise Unusable("template text: placeholder {{%s}} names no declared field" % match.group(1))
        pieces += [("text", text[i:at]), ("field", match.group(1))]
        i = match.end()


def check_template(tmpl: Any) -> dict:
    if not isinstance(tmpl, dict) or not TEMPLATE <= set(tmpl) <= TEMPLATE | TEMPLATE_OPTIONAL:
        raise Unusable("template must be {fields, text} and optionally output")
    check_type(tmpl["fields"], INPUT_TYPES, "template fields", non_empty=False)
    if not isinstance(tmpl["text"], str):
        raise Unusable("template text must be a string")
    if "output" in tmpl:
        check_type(tmpl["output"], OUTPUT_TYPES, "template output", non_empty=True)
    _pieces(tmpl["text"], tmpl["fields"])
    return tmpl


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def build(tmpl: Any, value: Any) -> dict:
    """``{prompt, prompt_sha256, dropped}`` from a template and a typed input (see the module docstring)."""
    fields = check_template(tmpl)["fields"]
    if not isinstance(value, dict):
        raise Unusable("input must be an object")
    for name, kind in fields.items():
        if name not in value:
            raise Unusable("input: declared field %s is missing" % name)
        if not _of_kind(value[name], kind):
            raise Unusable("input: field %s is not a JSON %s" % (name, kind))
    out = []
    for kind, piece in _pieces(tmpl["text"], fields):
        try:
            out.append(piece if kind == "text" else chain.canonical(value[piece]).decode("utf-8"))
        except chain.ChainError as exc:
            raise Unusable("input field %s: %s" % (piece, cli.cause(exc))) from None
    try:
        prompt = "".join(out)
        return {"prompt": prompt, "prompt_sha256": _sha256(prompt), "dropped": sorted(set(value) - set(fields))}
    except UnicodeEncodeError:
        raise Unusable("the prompt is not encodable as UTF-8") from None


def json_schema(spec: dict) -> dict:
    """The JSON Schema the CLI is asked to answer in: exactly ``spec``'s fields, each of its kind."""
    kinds = {"string": {"type": "string"}, "integer": {"type": "integer"}, "boolean": {"type": "boolean"},
             "strings": {"type": "array", "items": {"type": "string"}}}
    return {"type": "object", "properties": {name: kinds[kind] for name, kind in spec.items()},
            "required": sorted(spec), "additionalProperties": False}


# ---------------------------------------------------------------- money

def usd(micros: int) -> str:
    """Micro-USD as the decimal string ``--max-budget-usd`` takes: 500000 -> ``0.500000``."""
    return "%d.%06d" % divmod(micros, 1_000_000)


NUMBER = re.compile(r"(-?)(0|[1-9][0-9]*)(?:\.([0-9]+))?(?:[eE]([+-]?)([0-9]+))?\Z")


class JsonNumber:
    """A JSON number kept as its text (``_strict_json``): a fraction or exponent, or an integer of more than
    ``INT_DIGITS`` digits. It is no ``int`` and no ``str``, so no type check takes it for either."""

    __slots__ = ("text",)

    def __init__(self, text: str):
        self.text = text


INT_DIGITS = 18  # 2^53-1 has 16 digits: a longer integer is outside every range read here


def to_micros(text: str) -> int | None:
    """The JSON number ``text`` (USD) rounded up to a micro-USD, exactly, by integer arithmetic on its digits;
    None when it is negative and not zero, or above 2^53-1 micro-USD. No decimal context: no precision, no
    exponent limit, no rounding before the ceiling; work is bounded by the text's length, whatever the exponent."""
    match = NUMBER.match(text)
    if not match:
        raise Unusable("not a JSON number: %r" % text[:40])
    minus, whole, frac, exp_sign, exp = match.groups()
    frac = frac or ""
    digits = (whole + frac).lstrip("0")
    if not digits:
        return 0
    if minus:
        return None
    exp = (exp or "0").lstrip("0") or "0"
    if len(exp) > INT_DIGITS:  # |exponent| >= 10^18: astronomically large, or below any micro and above zero
        return 1 if exp_sign == "-" else None
    # value = int(digits) * 10^scale micro-USD; its leading digit sits at 10^(len(digits) - 1 + scale)
    scale = (-int(exp) if exp_sign == "-" else int(exp)) - len(frac) + 6
    if len(digits) - 1 + scale >= 16:  # >= 10^16 > 2^53-1
        return None
    if scale >= 0:
        micros = int(digits) * 10 ** scale
    else:
        cut = len(digits) + scale  # digits at or above one micro
        micros = 1 if cut <= 0 else int(digits[:cut]) + (1 if digits[cut:].strip("0") else 0)
    return micros if micros <= chain.MAX_SAFE_INT else None


def _micros(value: Any, what: str, positive: bool = False) -> int:
    if type(value) is not int or value < (1 if positive else 0) or value > chain.MAX_SAFE_INT:
        raise Unusable("%s must be an integer %s" % (what, "> 0" if positive else ">= 0"))
    return value


# ---------------------------------------------------------------- the book and the brake

def spent_micros(rows: list[dict]) -> int:
    """The stage's spend: the sum of ``payload.usd_micros`` over every ``part: cost`` row (``Unusable`` when one
    has no integer ``usd_micros`` >= 0). One rule for this module's brake and ``status.block``'s."""
    total = 0
    for row in rows:
        if row.get("part") == PART:
            payload = row.get("payload")
            total += _micros(payload.get("usd_micros") if isinstance(payload, dict) else None,
                             "cost row %r usd_micros" % row.get("row_id"))
    return total


class CostBook:
    """The cost rows of a verified ledger plus the ones recorded in this cycle; the stage brake reads it."""

    def __init__(self, ledger: bytes, previous: bytes):
        verdict = chain.verify_bytes(ledger, previous)
        if not verdict["valid"]:
            raise append.HardStop("ledger: %s (%s)" % (verdict["reason"], verdict["broken_row"]))
        self.ledger = [chain.parse_row(line.decode("utf-8")) for line in chain._lines(ledger)]
        self.rows: list[dict] = []

    def spent(self) -> int:
        return spent_micros(self.ledger + self.rows)

    def record(self, row: dict) -> None:
        self.rows.append(row)

    def request(self) -> bytes:
        """The rows recorded in this cycle as ``ledger.append``'s request."""
        return json.dumps({"rows": self.rows}, sort_keys=True).encode("utf-8")


def policy_usd(policy: bytes, *path: str) -> int:
    """The USD value at ``path`` of ``policy.json``'s bytes (e.g. ``stage_budgets``, ``asama_0``, ``canary_usd``)
    in micro-USD, rounded up exactly as a cost is (``to_micros`` on the number's JSON text, never a float);
    ``Unusable`` when the file is not one JSON object without duplicate keys, the path is absent, or the value is
    not a JSON number >= 0 (``true`` and strings included) within 2^53-1 micro-USD."""
    try:
        node = _strict_json(policy.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, RecursionError, chain.ChainError) as exc:
        raise Unusable("policy.json: %s" % cli.cause(exc)) from None
    for key in path:
        if not isinstance(node, dict) or key not in node:
            raise Unusable("policy.json has no %s" % ".".join(path))
        node = node[key]
    micros = _cost(node)
    if micros is None:
        raise Unusable("policy.json %s must be a JSON number >= 0 USD" % ".".join(path))
    return micros


# ---------------------------------------------------------------- the result

def _json_int(text: str) -> int | JsonNumber:
    return int(text) if len(text.lstrip("-")) <= INT_DIGITS else JsonNumber(text)


def _strict_json(text: str) -> Any:
    return cli.loads(text, parse_float=JsonNumber, parse_int=_json_int, object_pairs_hook=chain._no_duplicates,
                      parse_constant=chain._no_constant)


def _cost(value: Any) -> int | None:
    """A JSON number >= 0 (an integer, not ``true``, or a ``JsonNumber``) as micro-USD rounded up; else None."""
    if type(value) is int:
        return to_micros(str(value))
    if isinstance(value, JsonNumber):
        return to_micros(value.text)
    return None


def classify(stdout: bytes | None, model: str, cap: int, output: dict | None) -> dict:
    """Step 3 of a call (the module docstring): ``{outcome, reason, cost_usd_micros, cost_source, models_served,
    output}``; ``output`` None when the template has no output type, ``stdout`` None when the process ran past its
    timeout."""
    def done(outcome, reason, cost=cap, source="cap", served=(), out=None):
        return {"outcome": outcome, "reason": reason, "cost_usd_micros": cost, "cost_source": source,
                "models_served": sorted(served), "output": out}

    if stdout is None:
        return done("outage", "timeout")
    try:
        result = _strict_json(stdout.decode("utf-8").strip())
    except (UnicodeDecodeError, ValueError, chain.ChainError, RecursionError):
        result = None
    measured = _cost(result.get("total_cost_usd")) if isinstance(result, dict) else None
    if (measured is None or result.get("type") != "result" or not isinstance(result.get("modelUsage"), dict)):
        return done("unresolved", "malformed_result")
    usage = result["modelUsage"]
    seen = dict(cost=measured, source="cli_estimate", served=list(usage))
    if result.get("subtype") == "error_max_budget_usd":
        return done("unresolved", "over_budget", **seen)
    if result.get("is_error") is not False or result.get("subtype") != "success":
        text = result.get("result")
        status = API_STATUS.search(text) if isinstance(text, str) else None
        code = int(status.group(1)) if status else None
        if code in OUTAGE_STATUS:
            return done("outage", OUTAGE_STATUS[code], **seen)
        if code is not None and 500 <= code <= 599:
            return done("outage", "server", **seen)
        if code in REJECTED_STATUS:
            return done("request_rejected", "http_%d" % code, **seen)
        return done("unresolved", "cli_error", **seen)
    if measured > cap:
        return done("unresolved", "over_budget", **seen)
    if result.get("stop_reason") == "refusal":
        return done("unresolved", "refusal", **seen)
    if list(usage) != [model]:
        return done("unresolved", "model_mismatch", **seen)
    if output is None:
        return done("ok", None, **seen)
    try:
        out = check_value(output, result.get("structured_output"), "structured_output")
    except Unusable:
        return done("unresolved", "malformed_output", **seen)
    return done("ok", None, out=out, **seen)


# ---------------------------------------------------------------- the plan and the call

def sha512_file(path: str) -> str:
    digest = hashlib.sha512()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def command(claude: str, model: str, cap: int, tmpl: dict) -> list[str]:
    """The argv of one call; the prompt is not in it."""
    argv = [claude, *ARGS, "--model", model, "--max-budget-usd", usd(cap)]
    if "output" in tmpl:
        argv += ["--json-schema", chain.canonical(json_schema(tmpl["output"])).decode("utf-8")]
    return argv


def plan(tmpl: Any, request: Any, known: list[tuple[str, str]] = (), claude: str = "claude") -> dict:
    """``{send, reasons, prompt, prompt_sha256, dropped, cap_micros, max_budget_usd, argv}`` (see the module
    docstring); ``Unusable`` for an unusable request. Nothing is run."""
    if not isinstance(request, dict) or set(request) != REQUEST:
        raise Unusable("the request must be {model, input, budget} and nothing else")
    model, budget = request["model"], request["budget"]
    if not isinstance(model, str) or not model:
        raise Unusable("model must be a non-empty string")
    if not isinstance(budget, dict) or set(budget) != set(BUDGET):
        raise Unusable("budget must be {%s}" % ", ".join(BUDGET))
    stage_cap, spent, call_cap = (_micros(budget[k], "budget " + k) for k in BUDGET)
    built = build(tmpl, request["input"])
    reasons = []
    if secrets.scan(built["prompt"], "prompt", known):
        reasons.append("secret_in_prompt")
    left = stage_cap - spent
    if left <= 0:
        reasons.append("stage_brake")
    cap = min(call_cap, left) if not reasons else None
    return dict(built, send=not reasons, reasons=reasons, cap_micros=cap,
                max_budget_usd=None if cap is None else usd(cap),
                argv=None if cap is None else command(claude, model, cap, tmpl))


def _environment(root: str, token: str | None) -> dict:
    env = {"PATH": os.environ.get("PATH", os.defpath), "HOME": os.path.join(root, "home"),
           "CLAUDE_CONFIG_DIR": os.path.join(root, "config"), "CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1"}
    for name in ("home", "config", "work"):
        os.mkdir(os.path.join(root, name))
    if token is not None:
        env[TOKEN_ENV] = token
    return env


def template_sha256(tmpl: dict) -> str:
    return hashlib.sha256(chain.canonical(tmpl)).hexdigest()


def cost_row(tmpl: dict, planned: dict, model: str, verdict: dict, duration_ms: int, row_id: str, ts: str,
             snapshot_id: str) -> dict:
    payload = {"tool": "llm.call", "template_sha256": template_sha256(tmpl), "model_requested": model,
               "models_served": verdict["models_served"], "outcome": verdict["outcome"], "reason": verdict["reason"],
               "usd_micros": verdict["cost_usd_micros"], "cost_source": verdict["cost_source"],
               "cap_usd_micros": planned["cap_micros"], "prompt_sha256": planned["prompt_sha256"],
               "duration_ms": duration_ms}
    return {"row_id": row_id, "ts": ts, "part": PART, "kind": KIND, "payload": payload, "derivation": "tool",
            "trust": "observed", "snapshot_id": snapshot_id, "evidence_refs": []}


def call(tmpl: Any, value: Any, *, claude: str, claude_sha512: str, model: str, stage_cap_micros: int,
         call_cap_micros: int, book: CostBook, token: str | None, timeout_s: float, row_id: str, ts: str,
         snapshot_id: str) -> dict:
    """One call (see the module docstring); the spend is the book's. Returns ``{outcome, reason, sent, run_valid,
    output, models_served, cost_usd_micros, prompt_sha256, dropped, row}``; ``row`` is None when nothing was sent."""
    if token is not None and not isinstance(token, str):
        raise Unusable("token must be a string or None")
    request = {"model": model, "input": value, "budget": {"stage_cap_usd_micros": stage_cap_micros,
                                                           "spent_usd_micros": book.spent(),
                                                           "call_cap_usd_micros": call_cap_micros}}
    planned = plan(tmpl, request, [(TOKEN_ENV, token)] if token else [], claude)
    if not isinstance(claude_sha512, str) or len(claude_sha512) != 128 or not set(claude_sha512) <= HEX:
        raise Unusable("claude_sha512 must be 128 lowercase hex characters")
    if sha512_file(claude) != claude_sha512:
        raise Unusable("the claude CLI at %s is not the pinned one" % claude)
    unsent = {"sent": False, "run_valid": False, "output": None, "models_served": [], "cost_usd_micros": 0,
              "prompt_sha256": planned["prompt_sha256"], "dropped": planned["dropped"], "row": None}
    if "secret_in_prompt" in planned["reasons"]:
        return dict(unsent, outcome="secret", reason="secret_in_prompt")
    if not planned["send"]:
        return dict(unsent, outcome="brake", reason="stage_brake")
    with tempfile.TemporaryDirectory(prefix="llm-call-") as root:
        env = _environment(root, token)
        started = time.monotonic()
        try:
            done = subprocess.run(planned["argv"], input=planned["prompt"].encode("utf-8"), stdout=subprocess.PIPE,
                                  stderr=subprocess.DEVNULL, cwd=os.path.join(root, "work"), env=env,
                                  timeout=timeout_s)
            stdout = done.stdout
        except subprocess.TimeoutExpired:
            stdout = None
        duration = int((time.monotonic() - started) * 1000)
    verdict = classify(stdout, model, planned["cap_micros"], tmpl.get("output"))
    row = cost_row(tmpl, planned, model, verdict, duration, row_id, ts, snapshot_id)
    book.record(row)
    return {"outcome": verdict["outcome"], "reason": verdict["reason"], "sent": True,
            "run_valid": verdict["outcome"] == "ok", "output": verdict["output"],
            "models_served": verdict["models_served"], "cost_usd_micros": verdict["cost_usd_micros"],
            "prompt_sha256": planned["prompt_sha256"], "dropped": planned["dropped"], "row": row}


# ---------------------------------------------------------------- command line

USAGE = "usage: python -m dispatcher.llm_call plan TEMPLATE < {model, input, budget}"


def _emit(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj, sort_keys=True) + "\n")


def main(argv: list[str]) -> int:
    try:
        if len(argv) != 2 or argv[0] != "plan":
            raise Unusable(USAGE)
        try:
            with open(argv[1], "rb") as fh:
                tmpl = chain.parse_row(fh.read().decode("utf-8"))
        except OSError as exc:
            raise Unusable("%s: %s" % (argv[1], cli.cause(exc))) from None
        planned = plan(tmpl, chain.parse_row(sys.stdin.buffer.read().decode("utf-8")))
        _emit({k: planned[k] for k in ("send", "reasons", "prompt_sha256", "dropped", "max_budget_usd", "argv")})
        return 0 if planned["send"] else 1
    except (Unusable, UnicodeDecodeError, chain.ChainError) as exc:
        sys.stderr.write("unusable input: %s\n" % cli.cause(exc))
    _emit({"send": False})
    return 2


FAULT_LINE = {"send": False}


if __name__ == "__main__":
    sys.exit(cli.run(main, sys.argv[1:], FAULT_LINE))
