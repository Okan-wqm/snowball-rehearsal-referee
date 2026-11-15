"""``activate``: the operator's first cycle on a target: the genesis row, the ``brain/integration`` cut, the ratchet
base and the ready candidates, written as one orphan ``brain/state`` commit (stage 0, MF18).

Rules: tohum/29o (``genesis``: the reads, the reasons, the twelve-key payload, the exits), asama-0/14 row 18,
asama-0/09 tests 45 and 14, asama-0/10a #genesis (genesis reads and hashes the facts from the API) and #taban (the
ratchet base is the referee's own tool run at genesis), asama-0/08 (the acceptance rule), tohum/25a rows 3-7 (the
rulesets, the writer App's scope, no workflow on the toy, Actions off on the copy; ``brain/state`` opened with the
genesis row; ``brain/integration`` cut from the toy's ``main`` or at the copy's ``targets[].base_sha``),
tohum/01b:59-60 (``rules/branches`` and ``current_user_can_bypass``), tohum/28:37 (each reason is a hard stop),
tohum/30e (the seed security ledger), tohum/26a (``activate``: in ``koş`` and ``yaz``, the operator's first cycle).
Calls: 9 (every write), 10, 11 and 16 (the state commit), through their modules; 2, 7 and 8 (the decision) through
D5's ``loop.decide``, whose answer it takes.

**Genesis** (``genesis``), a dry run: it reads through a transport (``target.write``'s; the vector's is
``target.write.Replay`` over a recorded API) and writes nothing. Inputs: ``setup/summary.json``, the
``setup/imports.jsonl`` rows, the referee policy, ``setup/security-ledger.jsonl`` (tohum/26c) and the verified recipe, as bytes,
and the target id.

The reads, exactly these, each once (``reads``): ``GET /app``, ``GET /installation/repositories``, ``GET
/repos/{repo}/rules/branches/{brain/state, brain/integration, main}``, then ``GET /repos/{repo}/rulesets/{id}`` for
each ``ruleset_id`` of those three answers (in first-seen order); for a ``toy`` ``GET
/repos/{repo}/git/ref/heads/main`` and ``GET /repos/{repo}/actions/workflows``; for a ``copy`` ``GET
/repos/{repo}/actions/permissions``. A read answered other than 200, or a body not of the form read, is unusable:
the list is a ceiling, nothing else is read.

Reasons, sorted; any reason is a hard stop and no payload:

- ``app_scope``: the set of ``repositories[].full_name`` is not the set of ``targets[].repo``;
- ``state_rules_missing``: ``brain/state`` has no ``deletion`` or no ``non_fast_forward`` rule;
- ``integration_rules_missing``: ``brain/integration`` lacks one of ``deletion``, ``non_fast_forward``,
  ``pull_request``, ``required_status_checks``;
- ``integration_check_not_writer``: a ``required_status_checks`` rule of ``brain/integration`` whose
  ``strict_required_status_checks_policy`` is not ``true``, that lists no check, or one of whose checks has an
  ``integration_id`` other than ``/app``'s ``id`` (no such rule: only the reason above);
- ``rules_bypassable``: a ruleset a rule of ``brain/state`` or ``brain/integration`` comes from has
  ``current_user_can_bypass`` other than ``never`` (``exempt`` and ``pull_requests_only`` included);
- ``main_writable``: a ruleset a rule of ``main`` comes from is bypassable so, or ``main`` has neither an
  ``update`` rule nor a ``pull_request`` rule whose ``required_approving_review_count`` is an integer >= 1;
- ``toy_workflows``: the toy's ``workflows`` list is not empty;
- ``copy_actions_enabled``: the copy's ``enabled`` is not ``false``;
- ``security_ledger_broken``: the seed security ledger is empty or not a valid chain (``ledger.chain``).

The payload, twelve keys: ``target`` (the id); ``base_sha`` (``toy``: ``object.sha`` of the API's ``main``, the
summary's not read; ``copy``: ``targets[].base_sha``); of the last ``imports.jsonl`` row carrying
``referee_tree_sha256`` (a counter row that is no transfer is skipped; read by ``loop.accepted.last_import``, the
one reader D1 shares): ``referee_tree_sha256``, ``result_sha256``
and ``import_line_sha256`` (that line's bytes without its LF); ``seed_epoch`` (the last ``seed_epochs[]`` entry as
written); ``policy_sha256``, ``summary_sha256``, ``seed_security_ledger_sha256`` (sha256 of each file's bytes as
given); ``seed_security_last_row_hash``; ``recipe_sha256`` (of the recipe's RFC 8785 form); ``facts_sha256`` (of
the RFC 8785 form of ``{"GET <path>": body}`` over the reads). Unusable (``Unusable``): the target not exactly once
in ``targets[]`` or of another kind, a file that is not the JSON it names (``imports.jsonl`` a valid chain of
objects), no transfer row or one whose ``referee_tree_sha256`` is not 64 lowercase hex, a read not answered or malformed (a rule without an integer ``ruleset_id`` included).

**Activation** (``activate``): the write half of the genesis cycle (``loop.pulled.genesis``: a target with neither
``brain/state`` nor ``brain/integration``), run by ``yaz`` (``loop.job``) after D5 judged the cycle's candidates. Its
inputs are the cycle's own: ``art``, the ``pulled`` artifact (its target, the commit its tree was read from, its
candidates' diffs and its policy); ``tree``, that tree extracted (D1's checkout of the pulled tree, the tree D3 ran
on and D5 judged); ``decided``, D5's ``loop.decide`` answer ``{decisions, merge}`` (the acceptance rule of
asama-0/08, criteria 1-8 with ``profile.unit_verify.guard_profile``: one decider for every cycle, so the activation
judges no candidate itself); ``files``, the genesis files above and ``base.jsonl``, D3's base run, with its
``base_run_sha256`` from D3's index; ``cost``, the cost rows of the cycle's ``response`` (D4's canary); the signer,
the cycle id and the time. In this order; nothing is written before step 5:

1. ``genesis`` through the writer's transport; a reason is ``Refused`` (a hard stop: nothing is written); the
   writer's repository must be the target's (``target_repo_mismatch``); the genesis ``base_sha`` must be the commit
   ``pulled``'s tree was read from (``base_moved``: the toy's ``main`` moved after D1 read it, or a copy pulled at
   another commit than ``targets[].base_sha``), so the cut, the ratchet base and D5's decisions are of one tree.
2. The ratchet base (asama-0/10a #taban): ``base.jsonl`` (the referee's lint tool run three times on the base tree
   in ``koş``) must hash to ``base_run_sha256`` (``base_run_hash_mismatch``) and its three records be one
   (``tool_nondeterministic``); ``counts`` is violations per tool in its first record (``gate.check``'s count).
3. Reads: ``brain/state`` must not exist (``already_activated``), ``brain/integration`` must not exist
   (``integration_exists``), the ``base_sha`` commit must read. Any reason: ``Refused``. D5's merge, if any, is
   applied to its base file in ``tree`` (``loop.write_cycle.merge_change``, the application D6 makes too; a reason
   is ``Unusable``: D5 chose a candidate that cannot be written).
4. A dry plan of the state (``ledger.cycle.plan`` with the merge's answer as placeholders and a signer that signs
   nothing, ``loop.write_cycle``'s): the rows' secret scan, the whole ledger against ``ledger.schema``; a failure
   is ``Refused`` with ``state_unwritable: ...``.
5. Cut: ``brain/integration`` created at ``base_sha``. If GitHub refuses the creation, nothing else is written.
6. D5's merge (``target.land.land``): branch ``brain/c/<cid>`` at the cut, one commit, a pull request into
   ``brain/integration``, a ``success`` check named ``target.branches.CHECK``, the merge. A reject writes nothing on
   the target.
7. The state, ``events`` rows in this order: ``genesis`` (the payload), ``cycle_start {cycle_id}``,
   ``integration_cut {branch, base_sha}``, ``ratchet_base {base_run_sha256, counts}``, D5's decisions in code-point
   order of the candidate id (``loop.write_cycle.candidate_rows``: a merge's ``decision {decision: merge,
   candidate}`` and its ``merge {candidate, path, pull, head_sha, merge_sha, hunk_covered}`` row, tohum/26d; a reject's
   ``decision {decision: reject, candidate, reasons}`` with ``ledger.events.cause``), the response's cost rows as
   they are, then ``status.block.plan``'s rows (MF16; ``loop.write_cycle.status_facts``); ``ledger.cycle.plan``
   over an empty ledger and roots file chains them, signs the root and writes its row; its files (``ledger.jsonl``,
   ``chain/root.jsonl``, ``status.md`` and the root's Sigstore bundle, all under ``.brain/``, tohum/26d "Yer") go in
   one orphan commit that opens ``brain/state``. Row ids are
   ``<cycle_id>:genesis``, ``:start``, ``:cut``, ``:ratchet``, ``:c:<cid>``, ``:m:<cid>``, ``:status`` and the root
   row's ``:root``; every ``events`` row's ``snapshot_id`` is the cut.

A failure after step 5 raises ``HardStop`` carrying the refs already written (tohum/25a's failure rule leaves them
to the operator; step 3 refuses a retry). Returns ``{merge, state_sha, integration_sha, root, rekor_uuid, rows,
row_hashes, entry, edited, files}``.

Out of scope, stated: running the tools and tests (``koş``: their outputs are inputs here); (A)'s Rekor ids, the App
declaration of tohum/25a row 5 and ``bypass_actors`` (genesis does not read them, tohum/29o); writing
``profile.json`` into ``brain/state``; D8's drill in the genesis cycle (``yaz`` does not run it there: the drill
starts in the next cycle); the copy's genesis gate (tohum/25a row 7: the toy's cycles 1-5 green; judged by
``harness.pass_row.gate`` in the toy's ``yaz`` and read by ``cek``, which serves the copy's genesis only after it
opened, ``loop.job``); a second genesis after a re-import (tohum/26d) on a
target whose ``brain/state`` exists (``already_activated``: tohum/07 neither re-cuts nor syncs ``brain/integration``,
reported as seed-047). Whether GitHub lets
the writer App create ``brain/integration`` under tohum/25a row 3's ``pull_request`` rule is not known here
(seed-037); the fake GitHub is tested both ways.

Command line (group ``genesis``), run from ``referee/``, one JSON line on stdout, the cause on stderr::

    python -m activate genesis API SUMMARY IMPORTS POLICY SECURITY RECIPE   stdin {"target": id}
        -> {ok, hard_stop, reasons, payload}
        exit 0 planned; 1 hard stop; 2 unusable ({"ok": false, "hard_stop": true, "payload": null})
"""

from __future__ import annotations

import hashlib
import json
import sys
from typing import Any

from gate import check
from ledger import append, chain, cycle, events, schema
from loop import accepted, pulled, write_cycle
from target import branches, land, write
import cli

STATE = branches.STATE
INTEGRATION = branches.INTEGRATION
MAIN = "main"
FILES = ("summary.json", "imports.jsonl", "policy.json", "security-ledger.jsonl", "recipe.json", "base.jsonl")
GENESIS_FILES = FILES[:5]
KINDS = ("toy", "copy")
BRANCHES = (STATE, INTEGRATION, MAIN)
INTEGRATION_RULES = ("deletion", "non_fast_forward", "pull_request", "required_status_checks")
Refused = write.Refused


class Unusable(ValueError):
    pass


HardStop = land.HardStop  # activation failed after its first write; ``written`` names the refs already written


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json(data: bytes, name: str) -> Any:
    """JSON with no duplicate key and no NaN or Infinity (``ledger.chain``'s reading)."""
    try:
        return cli.loads(data.decode("utf-8"), object_pairs_hook=chain._no_duplicates,
                          parse_constant=chain._no_constant)
    except (UnicodeDecodeError, ValueError, RecursionError) as exc:
        raise Unusable("%s is not JSON: %s" % (name, cli.cause(exc))) from None


def _chain_rows(data: bytes) -> list[dict] | None:
    """The rows of a valid, non-empty chain, else None."""
    if not chain.verify_bytes(data)["valid"]:
        return None
    rows = [chain.parse_row(line.decode("utf-8")) for line in chain._lines(data)]
    return rows or None


def _canonical_sha(value: Any, name: str) -> str:
    try:
        return _sha(chain.canonical(value))
    except (chain.ChainError, ValueError, TypeError) as exc:
        raise Unusable("%s has no canonical form: %s" % (name, cli.cause(exc))) from None


# ---------------------------------------------------------------- genesis

class Reads:
    """The genesis reads through a transport: each a 200 answer, recorded as ``{"GET <path>": body}``."""

    def __init__(self, transport: Any):
        self.transport = transport
        self.facts: dict[str, Any] = {}

    def get(self, path: str, kind: type) -> Any:
        key = "GET " + path
        if key not in self.facts:
            status, body = self.transport("GET", path, None)
            if status != 200:
                raise Unusable("%s answered %s" % (key, status))
            self.facts[key] = body
        body = self.facts[key]
        if not isinstance(body, kind):
            raise Unusable("%s: the body is not a JSON %s" % (key, "object" if kind is dict else "array"))
        return body


def _rules(body: list, where: str) -> list[dict]:
    for rule in body:
        if not isinstance(rule, dict) or not isinstance(rule.get("type"), str) or \
                type(rule.get("ruleset_id")) is not int:
            raise Unusable("%s: a rule without a type and an integer ruleset_id" % where)
    return body


def _bypassable(reads: Reads, repo: str, rules: list[dict]) -> bool:
    out = False
    for ruleset_id in dict.fromkeys(rule["ruleset_id"] for rule in rules):
        ruleset = reads.get("/repos/%s/rulesets/%d" % (repo, ruleset_id), dict)
        out = out or ruleset.get("current_user_can_bypass") != "never"
    return out


def _target(summary: Any, target_id: Any) -> dict:
    if not isinstance(summary, dict) or not isinstance(summary.get("targets"), list) \
            or not isinstance(summary.get("seed_epochs"), list) or not summary["seed_epochs"]:
        raise Unusable("summary.json must carry targets[] and a non-empty seed_epochs[]")
    found = [t for t in summary["targets"] if isinstance(t, dict) and t.get("id") == target_id]
    if not isinstance(target_id, str) or len(found) != 1:
        raise Unusable("target %r is not exactly once in targets[]" % (target_id,))
    target = found[0]
    if target.get("kind") not in KINDS or not isinstance(target.get("repo"), str) or schema.hex40(
            target.get("base_sha"), "base_sha"):
        raise Unusable("target %r: kind toy or copy, a repo and a 40-hex base_sha" % target_id)
    return target


def genesis(transport: Any, files: dict[str, bytes], target_id: Any) -> dict:
    """``{ok, hard_stop, reasons, payload}`` (see the module docstring); reads only, writes nothing."""
    missing = [name for name in GENESIS_FILES if not isinstance(files.get(name), bytes)]
    if missing:
        raise Unusable("missing file(s): %s" % ", ".join(missing))
    summary = _json(files["summary.json"], "summary.json")
    target = _target(summary, target_id)
    _json(files["policy.json"], "policy.json")
    recipe = _json(files["recipe.json"], "recipe.json")
    try:
        transfer, transfer_line = accepted.last_import(files["imports.jsonl"])
    except accepted.StateError as exc:
        raise Unusable("imports.jsonl: %s" % cli.cause(exc)) from None

    repo, reads, reasons = target["repo"], Reads(transport), set()
    app = reads.get("/app", dict)
    installed = reads.get("/installation/repositories", dict).get("repositories")
    if not isinstance(installed, list) or not all(isinstance(r, dict) and isinstance(r.get("full_name"), str)
                                                  for r in installed):
        raise Unusable("GET /installation/repositories: repositories[] of {full_name}")
    rules = {b: _rules(reads.get("/repos/%s/rules/branches/%s" % (repo, b), list), b) for b in BRANCHES}
    if {r["full_name"] for r in installed} != {t.get("repo") for t in summary["targets"] if isinstance(t, dict)}:
        reasons.add("app_scope")
    types = {b: {rule["type"] for rule in rules[b]} for b in BRANCHES}
    if not {"deletion", "non_fast_forward"} <= types[STATE]:
        reasons.add("state_rules_missing")
    if not set(INTEGRATION_RULES) <= types[INTEGRATION]:
        reasons.add("integration_rules_missing")
    for rule in rules[INTEGRATION]:
        if rule["type"] == "required_status_checks":
            params = rule.get("parameters") if isinstance(rule.get("parameters"), dict) else {}
            checks = params.get("required_status_checks")
            if params.get("strict_required_status_checks_policy") is not True or not isinstance(checks, list) \
                    or not checks or any(not isinstance(c, dict) or c.get("integration_id") != app.get("id")
                                         for c in checks):
                reasons.add("integration_check_not_writer")
    if _bypassable(reads, repo, rules[STATE] + rules[INTEGRATION]):
        reasons.add("rules_bypassable")
    reviewed = any(rule["type"] == "pull_request" and isinstance(rule.get("parameters"), dict)
                   and type(rule["parameters"].get("required_approving_review_count")) is int
                   and rule["parameters"]["required_approving_review_count"] >= 1 for rule in rules[MAIN])
    if _bypassable(reads, repo, rules[MAIN]) or not ("update" in types[MAIN] or reviewed):
        reasons.add("main_writable")
    if target["kind"] == "toy":
        ref = reads.get("/repos/%s/git/ref/heads/main" % repo, dict).get("object")
        base_sha = ref.get("sha") if isinstance(ref, dict) else None
        if schema.hex40(base_sha, "main"):
            raise Unusable("GET main: object.sha is not 40 lowercase hex")
        workflows = reads.get("/repos/%s/actions/workflows" % repo, dict).get("workflows")
        if not isinstance(workflows, list):
            raise Unusable("GET actions/workflows: workflows[] missing")
        if workflows:
            reasons.add("toy_workflows")
    else:
        base_sha = target["base_sha"]
        if reads.get("/repos/%s/actions/permissions" % repo, dict).get("enabled") is not False:
            reasons.add("copy_actions_enabled")
    security = _chain_rows(files["security-ledger.jsonl"])
    if security is None:
        reasons.add("security_ledger_broken")
    if reasons:
        return {"ok": False, "hard_stop": True, "reasons": sorted(reasons), "payload": None}
    payload = {
        "target": target_id,
        "base_sha": base_sha,
        "referee_tree_sha256": transfer.get("referee_tree_sha256"),
        "result_sha256": transfer.get("result_sha256"),
        "import_line_sha256": _sha(transfer_line),
        "seed_epoch": summary["seed_epochs"][-1],
        "policy_sha256": _sha(files["policy.json"]),
        "summary_sha256": _sha(files["summary.json"]),
        "seed_security_ledger_sha256": _sha(files["security-ledger.jsonl"]),
        "seed_security_last_row_hash": security[-1]["row_hash"],
        "recipe_sha256": _canonical_sha(recipe, "recipe.json"),
        "facts_sha256": _canonical_sha(reads.facts, "the facts"),
    }
    bad = schema.payload_reasons("events", "genesis", payload)
    if bad:
        raise Unusable("genesis payload: %s" % "; ".join(bad))
    return {"ok": True, "hard_stop": False, "reasons": [], "payload": payload}


def ratchet_base(base_run: bytes, base_run_sha256: str) -> dict:
    """``{reasons, counts}``: step 2 of the activation (``gate.check.base_counts``)."""
    try:
        return check.base_counts(base_run, base_run_sha256)
    except check.Unusable as exc:
        raise Unusable(cli.cause(exc)) from None


# ---------------------------------------------------------------- activation

def activate(writer: write.Writer, files: dict[str, bytes], art: pulled.Pulled, tree: str, decided: dict,
             base_run_sha256: Any, cost: list[dict], signer: Any, cycle_id: str, ts: str) -> dict:
    """The activation in ``art``'s genesis cycle; see the module docstring."""
    if not pulled.genesis(art):
        raise Unusable("pulled is not a genesis cycle's: brain/state has a head")
    missing = [name for name in FILES if not isinstance(files.get(name), bytes)]
    if missing:
        raise Unusable("missing file(s): %s" % ", ".join(missing))
    if schema.hex64(base_run_sha256, "base_run_sha256"):
        raise Unusable("base_run_sha256 must be 64 lowercase hex")
    gen = genesis(writer.transport, files, art.target["id"])
    if gen["hard_stop"]:
        raise Refused(gen["reasons"])
    target = _target(_json(files["summary.json"], "summary.json"), art.target["id"])
    if writer.repo != target["repo"]:
        raise Refused(["target_repo_mismatch"])
    cut = gen["payload"]["base_sha"]
    if cut != art.heads[INTEGRATION]:
        raise Refused(["base_moved"])
    base = ratchet_base(files["base.jsonl"], base_run_sha256)
    if base["reasons"]:
        raise Refused(base["reasons"])
    reasons = []
    if writer.exists(STATE):
        reasons.append("already_activated")
    if writer.exists(INTEGRATION):
        reasons.append("integration_exists")
    if reasons:
        raise Refused(reasons)
    writer.read_commit(cut)
    cyc = {"cycle_id": cycle_id, "ts": ts, "snapshot_id": cut}
    try:
        change = write_cycle.merge_change(art, tree, decided["merge"])
        facts = write_cycle.status_facts(art, cyc)
    except write_cycle.Unusable as exc:
        raise Unusable(cli.cause(exc)) from None

    def rows(merged: dict | None) -> list[dict]:
        return [events.row(cyc, "genesis", "genesis", gen["payload"]), events.start(cyc),
                events.row(cyc, "cut", "integration_cut", {"branch": INTEGRATION, "base_sha": cut}),
                events.ratchet_base(cyc, base_run_sha256, base["counts"])] \
            + write_cycle.candidate_rows(cyc, decided, merged, change) + list(cost)

    root_row_id = "%s:root" % cycle_id
    try:  # the dry plan: every row and the whole ledger checked before the first write
        cycle.plan(b"", b"", b"", b"", None, rows(dict(write_cycle.PLACEHOLDER, path=change["path"]) if change else None),
                   files["imports.jsonl"], facts, write_cycle.DRY, root_row_id)
    except append.HardStop as exc:
        raise HardStop("state: %s" % cli.cause(exc), []) from None
    except cycle.FAILURES as exc:
        raise Refused(["state_unwritable: %s" % cli.cause(exc)]) from None
    writer.create_branch(INTEGRATION, cut)
    merged = None
    try:
        if change is not None:
            merged = dict(land.land(writer, decided["merge"], change["path"], change["content"], cut, branches.CHECK),
                          path=change["path"])
        state = cycle.plan(b"", b"", b"", b"", None, rows(merged), files["imports.jsonl"], facts, signer, root_row_id)
        sha = writer.open_orphan(STATE, state["files"], "genesis: cycle %s" % cycle_id)
    except (write.ApiError, write.Refused, Unusable) + cycle.FAILURES as exc:
        raise HardStop("%s: %s" % (type(exc).__name__, cli.cause(exc)), sorted(set(writer.written))) from None
    return {"merge": dict(merged, candidate=decided["merge"]) if merged else None, "state_sha": sha,
            "integration_sha": cut, "root": state["root"], "rekor_uuid": state["entry"]["uuid"],
            "rows": len(state["row_hashes"]), "row_hashes": state["row_hashes"], "entry": state["entry"],
            "edited": state["edited"], "files": state["files"]}


# ---------------------------------------------------------------- command line

USAGE = "usage: python -m activate genesis API SUMMARY IMPORTS POLICY SECURITY RECIPE < {\"target\": id}"


def _emit(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj, sort_keys=True) + "\n")


def _read(path: str) -> bytes:
    try:
        with open(path, "rb") as fh:
            return fh.read()
    except OSError as exc:
        raise Unusable("%s: %s" % (path, cli.cause(exc))) from None


def main(argv: list[str]) -> int:
    try:
        if len(argv) != 7 or argv[0] != "genesis":
            raise Unusable(USAGE)
        api = write.Replay(_json(_read(argv[1]), "the recorded API"))
        files = dict(zip(GENESIS_FILES, (_read(path) for path in argv[2:])))
        request = _json(sys.stdin.buffer.read(), "stdin")
        if not isinstance(request, dict) or set(request) != {"target"}:
            raise Unusable('stdin must be {"target"} and nothing else')
        out = genesis(api, files, request["target"])
        _emit(out)
        return 1 if out["hard_stop"] else 0
    except (Unusable, write.Unusable, chain.ChainError) as exc:
        cause = "unusable input: %s" % cli.cause(exc)
    _emit({"ok": False, "hard_stop": True, "payload": None})
    sys.stderr.write(cause + "\n")
    return 2


FAULT_LINE = {"ok": False, "hard_stop": True, "payload": None}


if __name__ == "__main__":
    sys.exit(cli.run(main, sys.argv[1:], FAULT_LINE))
