"""MF18 activation, the genesis verb (asama-0/14:45, 09:69, 10a:16-17, tohum/25a:17-21, 01b:59-60).

python -m activate genesis <api.json> <summary.json> <imports.jsonl> <policy.json> <security-ledger.jsonl>
<recipe.json>; stdin {"target": "<targets[].id>"}. A dry run against a recorded GitHub REST file
({"METHOD /path": body}; a recorded call gets its body, any other a 404): the preconditions are read, the
genesis row's payload is planned, nothing is written.
"""
import hashlib
import json
import sys

from ledger._common import NotCanonical, canonical_bytes, split_lines, verify  # A's helpers, beside MF1

STATE_RULES = {"deletion", "non_fast_forward"}
INTEGRATION_RULES = {"deletion", "non_fast_forward", "pull_request", "required_status_checks"}


class Unusable(Exception):
    pass


def _emit(obj, code):
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()
    return code


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _read(path):
    try:
        with open(path, "rb") as fh:
            return fh.read()
    except OSError as exc:
        raise Unusable(str(exc)) from exc


def _parse(data):
    try:
        return json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise Unusable("malformed JSON") from exc


def _object(data):
    value = _parse(data)
    if not isinstance(value, dict):
        raise Unusable("not an object")
    return value


class RecordedApi:
    """In-process replay; every answered request line is kept for the facts hash."""

    def __init__(self, recorded):
        self.recorded = recorded
        self.read = {}

    def get(self, path):
        line = "GET " + path
        if line not in self.recorded:
            raise Unusable("404 " + line)
        self.read[line] = self.recorded[line]
        return self.recorded[line]


def _rule_types(body):
    if not isinstance(body, list) or not all(isinstance(r, dict) and isinstance(r.get("type"), str)
                                             and _is_int(r.get("ruleset_id")) for r in body):
        raise Unusable("rules body")
    return {r["type"] for r in body}


def _restricts_main(rule):
    """25a:18: main asks an approving review, or only bypass may update it (the `update` rule)."""
    if rule["type"] == "update":
        return True
    params = rule.get("parameters")
    count = params.get("required_approving_review_count") if isinstance(params, dict) else None
    return rule["type"] == "pull_request" and _is_int(count) and count >= 1


def _check_not_writer(rule, app_id):
    params = rule.get("parameters")
    if not isinstance(params, dict) or params.get("strict_required_status_checks_policy") is not True:
        return True
    checks = params.get("required_status_checks")
    if not isinstance(checks, list) or not checks:
        return True
    return any(not isinstance(c, dict) or not _is_int(c.get("integration_id")) or c["integration_id"] != app_id
               for c in checks)


def genesis(paths, request):
    api_path, summary_path, imports_path, policy_path, security_path, recipe_path = paths
    if not isinstance(request, dict) or not isinstance(request.get("target"), str):
        raise Unusable("stdin")
    target_id = request["target"]

    recorded = _object(_read(api_path))
    summary_bytes = _read(summary_path)
    summary = _object(summary_bytes)
    targets = summary.get("targets")
    if not isinstance(targets, list) or not all(isinstance(t, dict) and isinstance(t.get("repo"), str) for t in targets):
        raise Unusable("targets")
    matching = [t for t in targets if t.get("id") == target_id]
    if len(matching) != 1:
        raise Unusable("target not in summary.targets")
    target = matching[0]
    kind, repo = target.get("kind"), target["repo"]
    if kind not in ("toy", "copy"):
        raise Unusable("kind")
    if kind == "copy" and not isinstance(target.get("base_sha"), str):
        raise Unusable("copy base_sha")
    epochs = summary.get("seed_epochs")
    if not isinstance(epochs, list) or not epochs:
        raise Unusable("seed_epochs")

    import_lines = split_lines(_read(imports_path))
    import_rows = [_object(line) for line in import_lines]
    # The counter holds every human touch (27:19); a transfer's row is the one with the referee tree (26c:37).
    transfers = [i for i, row in enumerate(import_rows) if "referee_tree_sha256" in row]
    if not transfers:
        raise Unusable("no transfer row")
    last_transfer = transfers[-1]
    last_import = import_rows[last_transfer]
    if not isinstance(last_import.get("referee_tree_sha256"), str) or not isinstance(last_import.get("result_sha256"), str):
        raise Unusable("imports row")

    policy_bytes = _read(policy_path)
    _object(policy_bytes)
    security_bytes = _read(security_path)
    try:
        recipe_sha = _sha(canonical_bytes(_object(_read(recipe_path))))
    except (NotCanonical, UnicodeEncodeError) as exc:
        raise Unusable("recipe not canonicalizable") from exc

    api = RecordedApi(recorded)
    app = api.get("/app")
    if not isinstance(app, dict) or not _is_int(app.get("id")):
        raise Unusable("/app body")
    installed = api.get("/installation/repositories")
    repos = installed.get("repositories") if isinstance(installed, dict) else None
    if not isinstance(repos, list) or not all(isinstance(r, dict) and isinstance(r.get("full_name"), str) for r in repos):
        raise Unusable("installation body")
    state_body = api.get("/repos/%s/rules/branches/brain/state" % repo)
    integration_body = api.get("/repos/%s/rules/branches/brain/integration" % repo)
    main_body = api.get("/repos/%s/rules/branches/main" % repo)  # 01b:59: brain/* and main
    state_types = _rule_types(state_body)
    integration_types = _rule_types(integration_body)
    _rule_types(main_body)
    bypass = {}  # 01b:60: the writer App's current_user_can_bypass, per ruleset a rule comes from
    for ruleset_id in sorted({r["ruleset_id"] for r in state_body + integration_body + main_body}):
        ruleset = api.get("/repos/%s/rulesets/%d" % (repo, ruleset_id))
        if not isinstance(ruleset, dict) or not isinstance(ruleset.get("current_user_can_bypass"), str):
            raise Unusable("ruleset body")
        bypass[ruleset_id] = ruleset["current_user_can_bypass"] != "never"
    workflows = None
    if kind == "toy":
        main = api.get("/repos/%s/git/ref/heads/main" % repo)
        obj = main.get("object") if isinstance(main, dict) else None
        if not isinstance(obj, dict) or not isinstance(obj.get("sha"), str):
            raise Unusable("main ref body")
        base_sha = obj["sha"]  # the toy is cut from main (25a:21)
        actions = None
        listed = api.get("/repos/%s/actions/workflows" % repo)  # 25a:20: the toy has no workflow
        workflows = listed.get("workflows") if isinstance(listed, dict) else None
        if not isinstance(workflows, list):
            raise Unusable("workflows body")
    else:
        actions = api.get("/repos/%s/actions/permissions" % repo)
        if not isinstance(actions, dict):
            raise Unusable("actions body")
        base_sha = target["base_sha"]  # the copy is cut from targets[].base_sha (25a:21)

    reasons = set()
    if {r["full_name"] for r in repos} != {t["repo"] for t in targets}:
        reasons.add("app_scope")
    if not STATE_RULES <= state_types:
        reasons.add("state_rules_missing")
    if not INTEGRATION_RULES <= integration_types:
        reasons.add("integration_rules_missing")
    if any(r["type"] == "required_status_checks" and _check_not_writer(r, app["id"]) for r in integration_body):
        reasons.add("integration_check_not_writer")
    if kind == "copy" and actions.get("enabled") is not False:
        reasons.add("copy_actions_enabled")
    if any(bypass[r["ruleset_id"]] for r in state_body + integration_body):
        reasons.add("rules_bypassable")
    if any(bypass[r["ruleset_id"]] for r in main_body) or not any(_restricts_main(r) for r in main_body):
        reasons.add("main_writable")
    if kind == "toy" and workflows:
        reasons.add("toy_workflows")
    valid, security_rows = verify(security_bytes)
    if not valid or not security_rows:
        reasons.add("security_ledger_broken")

    if reasons:
        return {"ok": False, "hard_stop": True, "reasons": sorted(reasons), "payload": None}, 1
    try:
        facts_sha = _sha(canonical_bytes(api.read))
    except (NotCanonical, UnicodeEncodeError) as exc:
        raise Unusable("recorded body not canonicalizable") from exc
    payload = {
        "target": target_id,
        "base_sha": base_sha,
        "referee_tree_sha256": last_import["referee_tree_sha256"],
        "result_sha256": last_import["result_sha256"],
        "import_line_sha256": _sha(import_lines[last_transfer]),
        "seed_epoch": epochs[-1],
        "policy_sha256": _sha(policy_bytes),
        "summary_sha256": _sha(summary_bytes),
        "seed_security_ledger_sha256": _sha(security_bytes),
        "seed_security_last_row_hash": security_rows[-1]["row_hash"],
        "recipe_sha256": recipe_sha,
        "facts_sha256": facts_sha,
    }
    return {"ok": True, "hard_stop": False, "reasons": [], "payload": payload}, 0


def main(argv):
    unusable = {"ok": False, "hard_stop": True, "payload": None}
    if len(argv) != 8 or argv[1] != "genesis":
        return _emit(unusable, 2)
    try:
        request = _parse(sys.stdin.buffer.read())
        out, code = genesis(argv[2:8], request)
    except Unusable:
        return _emit(unusable, 2)
    return _emit(out, code)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
