"""A toy target for activation tests (tests 45 and 14): the in-process GitHub with ``main`` and the facts genesis
reads (tohum/29o: the writer App, its installation, the three branches' rules and their rulesets, the toy's
workflows or the copy's Actions permission, answered as ``overrides``), the operator files, the referee's base run,
the genesis cycle's ``pulled`` (``loop.pulled.Pulled``: no ``brain/state`` head, ``brain/integration`` the base
commit) with five ready candidates, the good one and asama-0/08's four bad ones (outside the fix range, a ratchet
increase, a broken test, a forbidden path), and D5's answer on them (``loop.decide``'s shape, written here by hand:
deciding is D5's, tested in test_loop_yaz; the activation writes the answer). Every input is written here by hand;
hashes the tests expect are computed from these bytes, not by ``activate``.
"""

from __future__ import annotations

import hashlib
import atexit
import json
import os
import shutil
import tempfile

from fake_github import FakeGitHub
from ledger import anchor, chain
from loop import pulled
from target import branches

REPO = "acme/toy"
GATE = branches.CHECK  # tohum/25a row 3
CYCLE = "41000000001"
TS = "2026-10-30T12:00:00Z"
SNAP = "s-activation"

SOURCE = b"// toy\nvar x = 1;\nvar y = 2;\nmodule.exports = { x, y };\n"
TEST = b"const t = require('node:test');\n"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def chained(rows: list[dict]) -> bytes:
    out, prev = [], chain.ZERO_HASH
    for row in rows:
        row = dict(row, prev_hash=prev)
        row["row_hash"] = prev = chain.row_hash(row)
        out.append(chain.canonical(row) + b"\n")
    return b"".join(out)


def run_file(record: dict, lines: int = 3) -> bytes:
    line = json.dumps(record, sort_keys=True).encode("utf-8") + b"\n"
    return line * lines


def violation(line: int, rule: str = "no-var", path: str = "src/a.js", fix=None) -> dict:
    return {"rule_id": rule, "path": path, "line": line, "fix": [line, line] if fix is None else fix}


BASE_RUN = run_file({"tool": "eslint", "violations": [violation(2), violation(3)]})
CHECKS_GREEN = json.dumps({"tests": [{"id": "test/a.test.js", "status": "pass"}], "red_control": "fail"}).encode()
CHECKS_RED = json.dumps({"tests": [{"id": "test/a.test.js", "status": "fail"}], "red_control": "fail"}).encode()


def diff(path: str, old_start: int, removed: list[str], added: list[str]) -> bytes:
    head = "diff --git a/%s b/%s\nindex 1111111..2222222 100644\n--- a/%s\n+++ b/%s\n" % (path, path, path, path)
    hunk = "@@ -%d,%d +%d,%d @@\n" % (old_start, len(removed), old_start, len(added))
    body = "".join("-%s\n" % r for r in removed) + "".join("+%s\n" % a for a in added)
    return (head + hunk + body).encode("utf-8")


def candidate(cid: str, patch: bytes, line: int = 2, path: str = "src/a.js") -> dict:
    """A ready candidate as ``pulled`` carries it (``loop.pulled.CANDIDATE_FILES``)."""
    return {"id": cid, "diff.patch": patch, "expect.json": b"{}\n",
            "finding.json": json.dumps({"rule_id": "no-var", "path": path, "line": line, "fix_range": [line, line],
                                        "tool_output_sha256": sha(BASE_RUN)}).encode()}


def candidates() -> list[dict]:
    return [
        # good: line 2 fixed inside its fix range, nothing else changes
        candidate("good", diff("src/a.js", 2, ["var x = 1;"], ["let x = 1;"])),
        # outside the fix range: changes line 3 as well (scope_violation)
        candidate("bad-scope", diff("src/a.js", 2, ["var x = 1;", "var y = 2;"], ["let x = 1;", "let y = 2;"])),
        # ratchet: fixes line 2 but its tree has one more violation of the tool
        candidate("bad-ratchet", diff("src/a.js", 2, ["var x = 1;"], ["let x = 1;"])),
        # a broken test
        candidate("bad-test", diff("src/a.js", 2, ["var x = 1;"], ["let x = 1;"])),
        # a forbidden path: the lint configuration
        candidate("bad-path", diff("eslint.config.js", 1, ["module.exports = [];"], ["module.exports = [{}];"])),
    ]


EXPECTED_REJECTS = {
    "bad-scope": ("scope_violation", "scope_violation"),
    "bad-ratchet": ("ratchet_increase", "lint_regression"),
    "bad-test": ("tests_red", "test_regression"),
    "bad-path": ("config:eslint.config.js", "scope_violation"),
}


APP_ID = 4242
POLICY = json.dumps({"stage_budgets": {"asama_0": {"canary_usd": 0.22}}}).encode() + b"\n"


def decided() -> dict:
    """D5's answer on ``candidates()``: the good one merges, each bad one has its reason (``EXPECTED_REJECTS``)."""
    out = {"good": {"decision": "merge", "reasons": []}}
    out.update({cid: {"decision": "reject", "reasons": [reason]} for cid, (reason, _) in EXPECTED_REJECTS.items()})
    return {"decisions": out, "merge": "good"}


def facts(kind: str, repo: str = REPO) -> dict:
    """The GitHub answers genesis reads when every precondition holds (``{(method, path): (status, body)}``)."""
    p = "/repos/%s" % repo
    rule = lambda kind_, ruleset, **params: dict({"type": kind_, "ruleset_id": ruleset},  # noqa: E731
                                                 **({"parameters": params} if params else {}))
    out = {
        "/app": {"id": APP_ID, "slug": "snowball-writer"},
        "/installation/repositories": {"total_count": 1, "repositories": [{"full_name": repo}]},
        p + "/rules/branches/brain/state": [rule("deletion", 1), rule("non_fast_forward", 1)],
        p + "/rules/branches/brain/integration": [
            rule("deletion", 2), rule("non_fast_forward", 2), rule("pull_request", 2, required_approving_review_count=0),
            rule("required_status_checks", 2, strict_required_status_checks_policy=True,
                 required_status_checks=[{"context": GATE, "integration_id": APP_ID}])],
        p + "/rules/branches/main": [rule("deletion", 3), rule("pull_request", 3, required_approving_review_count=1)],
    }
    for n in (1, 2, 3):
        out[p + "/rulesets/%d" % n] = {"id": n, "current_user_can_bypass": "never"}
    if kind == "toy":
        out[p + "/actions/workflows"] = {"total_count": 0, "workflows": []}
    else:
        out[p + "/actions/permissions"] = {"enabled": False}
    return {("GET", path): (200, body) for path, body in out.items()}


_TREES: list[str] = []


def _trees() -> str:
    """One directory for every base tree of the process, removed at exit."""
    if not _TREES:
        _TREES.append(tempfile.mkdtemp(prefix="activation-trees-"))
        atexit.register(shutil.rmtree, _TREES[0], True)
    return _TREES[0]


class World:
    """The target and the inputs; each test may change any of them before calling ``run``."""

    def __init__(self, kind: str = "toy", create_denied=()):
        self.gh = FakeGitHub(REPO, required_check=GATE, create_denied=create_denied)
        self.main = self.gh.seed_commit("toy-main", files={
            "src/a.js": SOURCE, "test/a.test.js": TEST, "eslint.config.js": b"module.exports = [];\n",
            "package.json": b"{}\n", "src/auth/session.js": b"module.exports = {};\n",
            "src/feeder/valve.js": b"module.exports = {};\n"})
        self.gh.refs["main"] = self.main
        self.gh.overrides.update(facts(kind))
        self.imports = chained([{"ts": "2026-10-30T09:00:00Z", "stage": 0, "brain_sha": "b" * 40,
                                 "referee_tree_sha256": "e" * 64, "result_sha256": "d" * 64,
                                 "toy_tree_sha256": "f" * 64},
                                {"ts": "2026-10-30T10:00:00Z", "stage": 0}])  # a touch that is no transfer
        self.summary = json.dumps({
            "seed_epochs": [{"commit": "1" * 40, "spec_tohum_sha256": "2" * 64, "seed_sha256": "3" * 64,
                             "bootstrap_sha256": "4" * 64}],
            "targets": [{"id": "toy", "repo": REPO, "kind": kind, "base_sha": self.main, "identifiers": [],
                         "excluded_paths": [], "unit_candidates": []}]}).encode()
        self.recipe = json.dumps({"unit_id": "toy", "inputs": ["src/", "test/", "eslint.config.js",
                                                               "package.json"]}).encode()
        self.security = chained([{"row_id": "sec-1", "part": "security", "kind": "note", "payload": {}}])
        self.files = {"summary.json": self.summary, "imports.jsonl": self.imports, "policy.json": POLICY,
                      "security-ledger.jsonl": self.security,
                      "recipe.json": self.recipe, "base.jsonl": BASE_RUN}
        self.base_run_sha256 = sha(BASE_RUN)  # D3's index's
        self.candidates = candidates()
        self.decided = decided()
        self.cost: list[dict] = []
        self.signer = anchor.FakeSigner(True, "referee@example", "rekor-1")
        self.tree = None  # the base tree's directory; None: base_tree() at run
        self.heads = {branches.STATE: None, branches.INTEGRATION: self.main}  # pulled's: a genesis cycle

    def pulled(self) -> pulled.Pulled:
        """The genesis cycle's ``pulled`` as ``loop.pulled.read`` gives it."""
        summary = json.loads(self.files["summary.json"])
        return pulled.Pulled(summary["targets"][0], {"units": [json.loads(self.recipe)]}, json.loads(POLICY), "",
                             {c["id"]: {k: v for k, v in c.items() if k != "id"} for c in self.candidates},
                             dict(self.heads), {p: b"" for p in branches.STATE_CHAINS}, POLICY, None)

    def base_tree(self) -> str:
        """A new directory holding the base commit's tree (D1's checkout), not ``main``'s head; removed when the
        test process exits. Each call writes a fresh one."""
        root = tempfile.mkdtemp(dir=_trees())
        for path, blob in self.gh.trees[self.gh.commits[self.main]["tree"]].items():
            full = os.path.join(root, *path.split("/"))
            os.makedirs(os.path.dirname(full), exist_ok=True)
            with open(full, "wb") as fh:
                fh.write(self.gh.blobs[blob])
        return root

    def cand(self, cid: str) -> dict:
        return next(c for c in self.candidates if c["id"] == cid)

    def writer(self):
        from target import write
        return write.Writer(REPO, self.gh)

    def run(self, art: pulled.Pulled | None = None):
        import activate
        self.wr = self.writer()
        return activate.activate(self.wr, self.files, art or self.pulled(), self.tree or self.base_tree(),
                                 self.decided, self.base_run_sha256, self.cost, self.signer, CYCLE, TS)

    def writes(self) -> list[tuple]:
        return [(m, p) for m, p, _ in self.gh.requests if m != "GET"]
