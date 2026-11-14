"""Test 49 (asama-0/09) and group ``refs`` (tohum/29d): ``target.write``, the one way to write to a target.

- the ref rule: every ref written is a valid branch under ``refs/heads/brain/``; ``main``, ``brain/``'s
  look-alikes and other ref spaces are refused, each git name rule with its own case;
- the route rule: only the listed REST and Git Data routes of the configured repository; the contents API,
  the ``merges`` endpoint, ref deletion, repository settings, GraphQL, another repository, a force update,
  a squash or rebase merge and a merge of a pull request the guard has not seen open on ``brain/`` refuse;
- the writer against an in-process GitHub (``fake_github``) with the target's rulesets: branch, commit,
  pull request, check, merge; every attempt on ``main`` is refused before it is sent and ``main`` never moves;
- the state commit (``commit_files``, MF10's writer): blobs and trees only for plain files at safe paths, one
  commit on the head the caller read, a fast-forward update; a moved head or a branch outside ``brain/`` is
  refused before any object is created;
- revert: the revert commit's tree is the merge's first parent's tree (not its own, not the second parent's),
  its parent is the head of the branch it is made onto, it lands on a ``brain/`` branch, and after the pull
  request and merge the branch holds that tree; a merge that is not the head, a commit that is not a merge,
  or a revert branch outside ``brain/`` is refused;
- responses that do not say what was asked are errors; the HTTPS transport sends the token only to the API
  and follows no redirect;
- one way: no other module under ``referee/`` reaches the network or pushes with git;
- the command line (tohum/29i ``refs``): ``replay`` over a recorded API, each 29i case (revert first parent
  tree, refuse main, update never forces, prefix look-alike, ``..``, merge into main read then refused, pull
  request into main); outputs from the requests sent; exit 0 / 1 / 2, one JSON line.
"""

from __future__ import annotations

import ast
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
import urllib.request
import urllib.response
from email.message import Message

REFEREE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REFEREE)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from target import branches  # noqa: E402
from target import write as W  # noqa: E402
from fake_github import FakeGitHub  # noqa: E402

REPO = "acme/toy"
P = "/repos/acme/toy/"
A = "a" * 40
B = "b" * 40
GATE = branches.CHECK


def check(method, rest, body=None, pulls=None, prefix=P):
    return W.Guard(REPO, pulls).check(method, prefix + rest, body)


OPEN = {"base": "brain/integration", "head": "brain/c/1", "head_sha": A, "state": "open"}


class RefRule(unittest.TestCase):
    def test_brain_branches_are_writable(self):
        for ref in ("refs/heads/brain/integration", "refs/heads/brain/state", "refs/heads/brain/c/k0-17",
                    "refs/heads/brain/c/a.b_c-D9", "refs/heads/brain/c/x/y"):
            self.assertEqual(W.ref_reasons(ref), [], ref)

    def test_outside_brain(self):
        for ref in ("refs/heads/main", "refs/heads/master", "refs/heads/brain", "refs/heads/brainx/a",
                    "refs/heads/Brain/a", "refs/heads/BRAIN/a", "refs/tags/brain/a", "refs/brain/a",
                    "refs/pull/1/head", "brain/c/1", "heads/brain/c/1", " refs/heads/brain/c/1",
                    "refs/heads//brain/c/1", "refs/heads/x/brain/c/1", "", None, 7, ["refs/heads/brain/a"]):
            self.assertEqual(W.ref_reasons(ref), ["ref_outside_brain"], repr(ref))

    def test_git_name_rules(self):
        cases = {
            "empty component": "brain/", "double slash": "brain//a", "trailing slash": "brain/a/",
            "dot dot": "brain/a..b", "dot dot component": "brain/../main", "leading dot": "brain/.a",
            "lock": "brain/a.lock", "lock inner": "brain/a.lock/b", "trailing dot": "brain/a.",
            "colon": "brain/a:b", "tilde": "brain/a~1", "caret": "brain/a^", "space": "brain/a b",
            "backslash": "brain/a\\b", "at brace": "brain/a@{1}", "star": "brain/a*", "question": "brain/a?",
            "bracket": "brain/a[", "control": "brain/a\x01", "newline": "brain/a\n", "del": "brain/a\x7f",
            "non ascii": "brain/ç", "percent": "brain/a%2f", "plus": "brain/a+b",
        }
        for why, name in cases.items():
            self.assertEqual(W.ref_reasons("refs/heads/" + name), ["ref_invalid"], why)

    def test_cross_repository_head_is_refused(self):
        self.assertEqual(W.branch_reasons("evil:brain/c/1"), ["ref_outside_brain"])
        self.assertEqual(W.branch_reasons("brain:brain/c/1"), ["ref_outside_brain"])
        self.assertEqual(W.branch_reasons("brain/c:x"), ["ref_invalid"])


class RouteRule(unittest.TestCase):
    def test_allowed_routes(self):
        allowed = [
            ("GET", "git/ref/heads/main", None, []), ("GET", "git/ref/heads/brain/integration", None, []),
            ("GET", "git/commits/" + A, None, []), ("GET", "pulls/12", None, []),
            ("POST", "git/refs", {"ref": "refs/heads/brain/c/1", "sha": A}, ["refs/heads/brain/c/1"]),
            ("PATCH", "git/refs/heads/brain/state", {"sha": A}, ["refs/heads/brain/state"]),
            ("PATCH", "git/refs/heads/brain/state", {"sha": A, "force": False}, ["refs/heads/brain/state"]),
            ("POST", "git/commits", {"message": "m", "tree": A, "parents": [B]}, []),
            ("POST", "git/commits", {"message": "m", "tree": A, "parents": [A, B]}, []),
            ("POST", "pulls", {"title": "t", "head": "brain/c/1", "base": "brain/integration"}, []),
            ("POST", "pulls", {"title": "t", "head": "brain/c/1", "base": "brain/integration", "body": ""}, []),
            ("POST", "check-runs", {"name": GATE, "head_sha": A, "status": "completed", "conclusion": "success"}, []),
            ("POST", "check-runs", {"name": GATE, "head_sha": A, "status": "completed", "conclusion": "failure",
                                    "output": {"title": "t", "summary": ""}}, []),
        ]
        for method, rest, body, refs in allowed:
            self.assertEqual(check(method, rest, body), ([], refs), (method, rest, body))
        self.assertEqual(check("PUT", "pulls/3/merge", {"sha": A, "merge_method": "merge"}, {3: OPEN}),
                         ([], ["refs/heads/brain/integration"]))

    def test_main_and_outside_brain_refused_on_every_writing_route(self):
        for ref in ("refs/heads/main", "refs/heads/release/1", "refs/tags/v1"):
            self.assertEqual(check("POST", "git/refs", {"ref": ref, "sha": A}), (["ref_outside_brain"], []))
        for name in ("main", "dev", "brainx"):
            self.assertEqual(check("PATCH", "git/refs/heads/" + name, {"sha": A}), (["ref_outside_brain"], []))
        for head, base in (("brain/c/1", "main"), ("main", "brain/integration"), ("feature", "dev")):
            reasons, _ = check("POST", "pulls", {"title": "t", "head": head, "base": base})
            self.assertEqual(reasons, ["ref_outside_brain"], (head, base))
        onto_main = dict(OPEN, base="main")
        self.assertEqual(check("PUT", "pulls/3/merge", {"sha": A, "merge_method": "merge"}, {3: onto_main}),
                         (["ref_outside_brain"], []))
        from_main = dict(OPEN, head="main")
        self.assertEqual(check("PUT", "pulls/3/merge", {"sha": A, "merge_method": "merge"}, {3: from_main}),
                         (["ref_outside_brain"], []))

    def test_routes_outside_the_list(self):
        refused = [
            ("PUT", "contents/src/a.js", {"message": "m", "content": "", "branch": "brain/c/1"}),
            ("POST", "merges", {"base": "brain/integration", "head": "brain/c/1"}),
            ("DELETE", "git/refs/heads/brain/c/1", None), ("DELETE", "git/refs/heads/brain/integration", None),
            ("PATCH", "pulls/3", {"base": "main"}), ("POST", "pulls/3/update-branch", {}),
            ("POST", "git/tags", {}), ("PUT", "branches/main/protection", {}), ("POST", "rulesets", {}),
            ("POST", "forks", {}), ("POST", "dispatches", {}), ("POST", "actions/workflows/x/dispatches", {}),
            ("GET", "contents/a", None), ("GET", "git/refs", None), ("HEAD", "pulls/3", None),
            ("POST", "git/ref/heads/brain/c/1", {"sha": A}), ("PATCH", "git/refs/brain/c/1", {"sha": A}),
            ("PUT", "pulls/0/merge", {"sha": A, "merge_method": "merge"}),
            ("PUT", "pulls/03/merge", {"sha": A, "merge_method": "merge"}),
        ]
        for method, rest, body in refused:
            self.assertEqual(check(method, rest, body, {3: OPEN}), (["route_not_allowed"], []), (method, rest))
        self.assertEqual(W.Guard(REPO).check("PATCH", "/repos/acme/toy", {"default_branch": "brain/x"}),
                         (["route_not_allowed"], []))
        self.assertEqual(W.Guard(REPO).check("POST", "/graphql", {"query": "mutation"}), (["route_not_allowed"], []))
        for other in ("/repos/acme/other/", "/repos/acme/toy2/", "/repos/acmex/toy/", "/repos/ACME/toy/",
                      "https://api.github.com/repos/acme/toy/", "/repos/acme/toy/../other/"):
            reasons, _ = W.Guard(REPO).check("POST", other + "git/refs", {"ref": "refs/heads/brain/c/1", "sha": A})
            self.assertEqual(reasons, ["route_not_allowed"], other)

    def test_path_shapes(self):
        body = {"ref": "refs/heads/brain/c/1", "sha": A}
        for rest in ("git/refs?x=1", "git/refs#x", "git/refs/", "git//refs", "git/%72efs", "git/refs ",
                     "git\\refs", "", "git/refs\n"):
            self.assertEqual(check("POST", rest, body), (["route_not_allowed"], []), repr(rest))
        self.assertEqual(check("PATCH", "git/refs/heads/brain/c/../../main", {"sha": A}), (["route_not_allowed"], []))
        self.assertEqual(check("GET", "git/ref/heads/brain/a..b"), (["route_not_allowed"], []))
        for name in ("brain/c/1?force=true", "brain/c/1#x", "brain/c/1/", "brain//c/1", "brain/c/%31", "brain/c/1 ",
                     "brain/c\\1"):
            self.assertEqual(check("PATCH", "git/refs/heads/" + name, {"sha": A}), (["route_not_allowed"], []), name)
        self.assertEqual(check("GET", "git/ref/heads/brain/a~1"), (["ref_invalid"], []))
        self.assertEqual(check("GET", "git/ref/heads/main", {"x": 1}), (["body_invalid"], []))
        for sha in (A.upper(), A[:7], A + "0" * 24):
            self.assertEqual(check("GET", "git/commits/" + sha), (["route_not_allowed"], []), sha)

    def test_bodies(self):
        bad = [
            ("POST", "git/refs", {"ref": "refs/heads/brain/c/1"}), ("POST", "git/refs", {"ref": "refs/heads/brain/c/1",
                                                                                         "sha": A, "force": True}),
            ("POST", "git/refs", {"ref": "refs/heads/brain/c/1", "sha": A[:39]}), ("POST", "git/refs", None),
            ("POST", "git/refs", {"ref": "refs/heads/brain/c/1", "sha": A + "0"}),
            ("POST", "git/refs", {"ref": "refs/heads/brain/c/1", "sha": A + "0" * 24}),
            ("POST", "git/refs", [["ref", "refs/heads/brain/c/1"]]),
            ("PATCH", "git/refs/heads/brain/state", {"sha": A.upper()}),
            ("PATCH", "git/refs/heads/brain/state", {"sha": A, "ref": "refs/heads/main"}),
            ("POST", "git/commits", {"message": "m", "tree": A, "parents": [A, B, A]}),
            ("POST", "git/commits", {"message": "", "tree": A, "parents": [A]}),
            ("POST", "git/commits", {"message": "m", "tree": A, "parents": [A], "author": {}}),
            ("POST", "git/commits", {"message": "m", "tree": A, "parents": A}),
            ("POST", "git/commits", {"message": "m", "tree": A, "parents": [A.upper()]}),
            ("POST", "git/commits", {"message": "m", "tree": A, "parents": [B, A[:39]]}),
            ("POST", "pulls", {"title": "", "head": "brain/c/1", "base": "brain/integration"}),
            ("POST", "pulls", {"title": "t", "head": "brain/c/1", "base": "brain/integration", "draft": True}),
            ("POST", "pulls", {"title": "t", "head": "brain/c/1", "base": "brain/integration", "body": None}),
            ("POST", "pulls", {"title": "t", "head": "brain/c/1", "base": "brain/integration",
                               "maintainer_can_modify": True}),
            ("POST", "check-runs", {"name": GATE, "head_sha": A, "status": "in_progress", "conclusion": "success"}),
            ("POST", "check-runs", {"name": GATE, "head_sha": A, "status": "completed", "conclusion": "neutral"}),
            ("POST", "check-runs", {"name": "", "head_sha": A, "status": "completed", "conclusion": "success"}),
            ("POST", "check-runs", {"name": GATE, "head_sha": A[:39], "status": "completed", "conclusion": "success"}),
            ("POST", "check-runs", {"name": GATE, "head_sha": "main", "status": "completed", "conclusion": "success"}),
            ("POST", "check-runs", {"name": GATE, "head_sha": A, "status": "completed", "conclusion": "success",
                                    "output": {"title": "", "summary": ""}}),
            ("POST", "check-runs", {"name": GATE, "head_sha": A, "status": "completed", "conclusion": "success",
                                    "actions": []}),
            ("POST", "check-runs", {"name": GATE, "head_sha": A, "status": "completed", "conclusion": "success",
                                    "output": {"title": "t", "summary": "", "annotations": []}}),
            ("PUT", "pulls/3/merge", {"merge_method": "merge"}),
            ("PUT", "pulls/3/merge", {"sha": A.upper(), "merge_method": "merge"}),
            ("PUT", "pulls/3/merge", {"sha": A, "merge_method": "merge", "commit_message": "x"}),
        ]
        for method, rest, body in bad:
            self.assertEqual(check(method, rest, body, {3: OPEN}), (["body_invalid"], []), (method, rest, body))

    def test_force_update_refused(self):
        for force in (True, 1, "false", None):
            self.assertEqual(check("PATCH", "git/refs/heads/brain/state", {"sha": A, "force": force}),
                             (["force_update"], []), force)

    def test_merge_rules(self):
        body = {"sha": A, "merge_method": "merge"}
        for method in ("squash", "rebase", None):
            self.assertEqual(check("PUT", "pulls/3/merge", dict(body, merge_method=method), {3: OPEN}),
                             (["merge_method"], []))
        self.assertEqual(check("PUT", "pulls/3/merge", body), (["merge_unknown_pull"], []))
        self.assertEqual(check("PUT", "pulls/3/merge", body, {4: OPEN}), (["merge_unknown_pull"], []))
        self.assertEqual(check("PUT", "pulls/3/merge", body, {3: dict(OPEN, state="closed")}),
                         (["merge_not_open"], []))
        self.assertEqual(check("PUT", "pulls/3/merge", dict(body, sha=B), {3: OPEN}), (["merge_head_moved"], []))
        self.assertEqual(check("PUT", "pulls/3/merge", dict(body, commit_title=""), {3: OPEN}), (["body_invalid"], []))

    def test_observe_records_pulls_only_from_pull_responses(self):
        g = W.Guard(REPO)
        resp = {"number": 3, "state": "open", "base": {"ref": "brain/integration"},
                "head": {"ref": "brain/c/1", "sha": A}}
        g.observe("GET", P + "git/commits/" + A, resp)
        g.observe("GET", "/repos/acme/other/pulls/3", resp)
        self.assertEqual(g.pulls, {})
        with self.assertRaises(W.ApiError):
            g.observe("GET", P + "pulls/4", resp)
        g.observe("POST", P + "pulls", resp)  # a created pull is not a record: a merge reads it again
        g.observe("PATCH", P + "pulls/3", resp)  # only a read is
        self.assertEqual(g.pulls, {})
        for broken in ({}, dict(resp, number="3"), dict(resp, number=True), dict(resp, head={"ref": "brain/c/1"}),
                       dict(resp, head={"ref": "brain/c/1", "sha": A.upper()}),
                       dict(resp, head={"ref": "brain/c/1", "sha": None})):
            with self.assertRaises(W.ApiError):
                g.observe("GET", P + "pulls/3", broken)
        with self.assertRaises(W.ApiError):  # True == 1 in Python: a bool is not a number even where it would equal one
            g.observe("GET", P + "pulls/1", dict(resp, number=True))
        g.observe("GET", P + "pulls/3", resp)
        self.assertEqual(g.pulls[3]["base"], "brain/integration")
        g.observe("GET", P + "pulls/3", dict(resp, base={"ref": "main"}))
        self.assertEqual(g.check("PUT", P + "pulls/3/merge", {"sha": A, "merge_method": "merge"}),
                         (["ref_outside_brain"], []))

    def test_repo_must_be_one_name(self):
        for repo in ("acme", "acme/toy/x", "../toy", "acme/..", "", None, "acme/to y"):
            with self.assertRaises(W.Unusable):
                W.Guard(repo)


def world():
    """A target: ``main`` and ``brain/integration`` at the same commit, as activation cuts it."""
    gh = FakeGitHub(REPO)
    root = gh.seed_commit("t0")
    gh.refs["main"] = root
    gh.refs["brain/integration"] = root
    return gh, W.Writer(REPO, gh), root


def writes(gh):
    return [r for r in gh.requests if r[0] != "GET"]


def written_refs(gh):
    refs = []
    for method, path, body in writes(gh):
        if method == "POST" and path.endswith("/git/refs"):
            refs.append(body["ref"])
        elif method == "PATCH":
            refs.append("refs/heads/" + path.split("/git/refs/heads/", 1)[1])
        elif method == "PUT" and path.endswith("/merge"):
            refs.append("refs/heads/" + gh.pulls[int(path.split("/")[-2])]["base"])
    return refs


def candidate(gh, wr, cid="brain/c/1", tree="t1"):
    """A candidate commit on its own branch, the way the gate publishes one; returns (pull, head sha)."""
    base = wr.head("brain/integration")
    tree_sha = gh.commits[gh.seed_commit(tree)]["tree"]
    sha = wr.commit("candidate " + cid, tree_sha, [base])
    wr.create_branch(cid, sha)
    return wr.open_pull(cid, "brain/integration", "candidate " + cid), sha


class WriterLoop(unittest.TestCase):
    def test_branch_pull_check_merge(self):
        gh, wr, root = world()
        n, sha = candidate(gh, wr)
        wr.check(sha, GATE, "success", "criteria 1-8 hold")
        merged = wr.merge(n, sha)
        self.assertEqual(gh.refs["brain/integration"], merged)
        self.assertEqual(gh.commits[merged]["parents"], [root, sha])
        self.assertEqual(gh.commits[merged]["tree"], gh.commits[sha]["tree"])
        self.assertEqual(gh.refs["main"], root)
        self.assertEqual(written_refs(gh), ["refs/heads/brain/c/1", "refs/heads/brain/integration"])
        self.assertTrue(all(r.startswith("refs/heads/brain/") for r in written_refs(gh)))
        self.assertTrue(all(path.startswith(P) for _, path, _ in gh.requests))

    def test_the_ruleset_still_holds_without_the_check(self):
        gh, wr, _ = world()
        n, sha = candidate(gh, wr)
        with self.assertRaises(W.ApiError) as ctx:
            wr.merge(n, sha)
        self.assertEqual(ctx.exception.status, 405)

    def test_brain_state_update_is_a_fast_forward(self):
        gh, wr, root = world()
        state = gh.seed_commit("s0")
        wr.create_branch("brain/state", state)
        nxt = wr.commit("cycle 1", gh.commits[state]["tree"], [state])
        wr.update_branch("brain/state", nxt)
        self.assertEqual(gh.refs["brain/state"], nxt)
        self.assertEqual(writes(gh)[-1], ("PATCH", P + "git/refs/heads/brain/state", {"sha": nxt, "force": False}))
        with self.assertRaises(W.ApiError):  # a rewind is not a fast-forward and force is never sent
            wr.update_branch("brain/state", state)
        self.assertEqual(gh.refs["brain/state"], nxt)
        with self.assertRaises(W.ApiError):  # the integration branch takes no direct push
            wr.update_branch("brain/integration", nxt)

    def test_every_attempt_on_main_is_refused_before_it_is_sent(self):
        gh, wr, root = world()
        n, sha = candidate(gh, wr)
        gh.pulls[9] = {"base": "main", "head": "brain/c/1", "state": "open", "merged": False, "sha": sha}
        sent = len(gh.requests)
        attempts = [
            lambda: wr.create_branch("main", sha), lambda: wr.update_branch("main", sha),
            lambda: wr.create_branch("feature/x", sha), lambda: wr.open_pull("brain/c/1", "main", "t"),
            lambda: wr.open_pull("main", "brain/integration", "t"), lambda: wr.create_branch("brain/../main", sha),
        ]
        for attempt in attempts:
            with self.assertRaises(W.Refused):
                attempt()
        self.assertEqual(len(gh.requests), sent)
        wr.check(sha, GATE, "success")
        with self.assertRaises(W.Refused) as ctx:  # a pull onto main made by someone else: read, then refused
            wr.merge(9, sha)
        self.assertEqual(ctx.exception.reasons, ["ref_outside_brain"])
        self.assertEqual(gh.requests[-1][0], "GET")
        self.assertEqual(gh.refs["main"], root)
        self.assertNotIn(("PUT", P + "pulls/9/merge"), [(m, p) for m, p, _ in gh.requests])

    def test_a_pull_whose_base_changed_to_main_is_refused(self):
        gh, wr, root = world()
        n, sha = candidate(gh, wr)
        wr.check(sha, GATE, "success")
        gh.pulls[n]["base"] = "main"  # retargeted after it was opened
        with self.assertRaises(W.Refused):
            wr.merge(n, sha)
        self.assertEqual(gh.refs["main"], root)

    def test_a_head_that_moved_is_refused(self):
        gh, wr, _ = world()
        n, sha = candidate(gh, wr)
        wr.check(sha, GATE, "success")
        newer = gh.seed_commit("t9", [sha])
        gh.refs["brain/c/1"] = newer
        with self.assertRaises(W.Refused) as ctx:
            wr.merge(n, sha)
        self.assertEqual(ctx.exception.reasons, ["merge_head_moved"])

    def test_responses_that_do_not_answer_the_question(self):
        gh, wr, root = world()
        gh.overrides[("GET", P + "git/ref/heads/brain/integration")] = (
            200, {"ref": "refs/heads/brain/integration-old", "object": {"sha": root}})
        with self.assertRaises(W.ApiError):
            wr.head("brain/integration")
        gh.overrides[("GET", P + "git/commits/" + root)] = (200, {"sha": A, "tree": {"sha": B}, "parents": []})
        with self.assertRaises(W.ApiError):
            wr.read_commit(root)
        gh.overrides[("GET", P + "git/ref/heads/main")] = (404, {"message": "Not Found"})
        with self.assertRaises(W.ApiError):
            wr.head("main")
        for sha in ("x", A.upper(), None):
            gh.overrides[("GET", P + "git/ref/heads/brain/state")] = (
                200, {"ref": "refs/heads/brain/state", "object": {"sha": sha}})
            with self.assertRaises(W.ApiError):
                wr.head("brain/state")
        for status in (199, 300, 302, 304, "200", None):  # only a 2xx answer is a success
            gh.overrides[("GET", P + "git/ref/heads/brain/integration")] = (
                status, {"ref": "refs/heads/brain/integration", "object": {"sha": root}})
            with self.assertRaises(W.ApiError) as ctx:
                wr.head("brain/integration")
            self.assertEqual(ctx.exception.status, status)
        gh.overrides[("POST", P + "git/commits")] = (201, {"sha": "x"})
        with self.assertRaises(W.ApiError):
            wr.commit("m", gh.commits[root]["tree"], [root])

    def test_a_merge_response_that_did_not_land(self):
        gh, wr, root = world()
        n, sha = candidate(gh, wr)
        wr.check(sha, GATE, "success")
        for answer in ({"merged": True}, {"merged": True, "sha": "x"}, {"merged": "true", "sha": B}, None):
            gh.overrides[("PUT", P + "pulls/%d/merge" % n)] = (200, answer)
            with self.assertRaises(W.ApiError):
                wr.merge(n, sha)
        del gh.overrides[("PUT", P + "pulls/%d/merge" % n)]

        def unmerged(method, path, body):  # the merge lands but the response says it did not
            status, data = gh(method, path, body)
            return (status, dict(data, merged=False)) if method == "PUT" else (status, data)
        with self.assertRaises(W.ApiError):
            W.Writer(REPO, unmerged).merge(n, sha)

    def test_a_pull_number_is_an_int_not_a_bool(self):
        gh, wr, root = world()
        gh.refs["brain/c/1"] = root
        for number, want in ((5, 5), (True, None), ("5", None), (None, None)):
            gh.overrides[("POST", P + "pulls")] = (201, {"number": number})
            self.assertIs(wr.open_pull("brain/c/1", "brain/integration", "t"), want, number)

    def test_a_pull_created_elsewhere(self):
        gh, wr, root = world()
        gh.refs["brain/c/1"] = root
        gh.overrides[("POST", P + "pulls")] = (201, {"number": 5, "state": "open", "base": {"ref": "brain/other"},
                                                     "head": {"ref": "brain/c/1", "sha": root}})
        with self.assertRaises(W.ApiError):
            wr.open_pull("brain/c/1", "brain/integration", "t")


class StateCommit(unittest.TestCase):
    """``POST git/blobs`` and ``git/trees`` (plain files only) and ``commit_files``, the state commit."""

    def test_object_routes(self):
        tree = {"base_tree": A, "tree": [{"path": "state/ledger.jsonl", "mode": "100644", "type": "blob", "sha": B}]}
        self.assertEqual(check("POST", "git/blobs", {"content": "eyJhIjoxfQo=", "encoding": "base64"}), ([], []))
        self.assertEqual(check("POST", "git/blobs", {"content": "", "encoding": "base64"}), ([], []))
        self.assertEqual(check("POST", "git/trees", tree), ([], []))
        entry = tree["tree"][0]
        bad = [
            {"content": "x", "encoding": "utf-8"}, {"content": "eyJhIjoxfQo=", "encoding": "utf-8"},
            {"content": "eyJhIjoxfQo", "encoding": "base64"},
            {"content": "ey JhIjoxfQo=", "encoding": "base64"}, {"content": "eyJhIjoxfQp=", "encoding": "base64"},
            {"content": "eyJhIjoxfQo="}, {"content": 1, "encoding": "base64"},
            {"content": "", "encoding": "base64", "sha": A},
        ]
        for body in bad:
            self.assertEqual(check("POST", "git/blobs", body), (["body_invalid"], []), body)
        bad_entries = [dict(entry, mode=m) for m in ("100755", "120000", "160000", "040000")]
        bad_entries += [dict(entry, type=t) for t in ("tree", "commit")]
        bad_entries += [dict(entry, path=x) for x in (
            "", "/abs", "a//b", "a/", "./a", "a/./b", "../a", "a/../b", ".git/config", "x/.GIT/hooks/a", ".Git",
            "a b", "a\\b", "a\nb", "ü", "a+b", 7)]
        bad_entries += [dict(entry, sha=A.upper()), dict(entry, content="x"), {k: v for k, v in entry.items() if k != "sha"}]
        for e in bad_entries:
            self.assertEqual(check("POST", "git/trees", {"base_tree": A, "tree": [e]}), (["body_invalid"], []), e)
        for body in ({"base_tree": A, "tree": []}, {"tree": []}, {"base_tree": None, "tree": [entry]},
                     {"base_tree": A[:39], "tree": [entry]}, {"tree": [dict(entry, mode="120000")]},
                     {"base_tree": A, "tree": [entry, dict(entry, sha=A)]}, {"base_tree": A, "tree": entry},
                     dict(tree, extra=1)):
            self.assertEqual(check("POST", "git/trees", body), (["body_invalid"], []), body)
        self.assertEqual(check("POST", "git/trees", {"base_tree": A, "tree": [entry, dict(entry, path="b/.gitkeep")]}),
                         ([], []))
        # no base_tree: a tree of only these entries, the orphan brain/state's root (tohum/01a); writes no ref
        self.assertEqual(check("POST", "git/trees", {"tree": [entry]}), ([], []))
        self.assertEqual(check("POST", "git/commits", {"message": "m", "tree": A, "parents": []}), ([], []))

    def state(self):
        gh, wr, root = world()
        state = gh.seed_commit("s0", files={"keep.txt": b"k\n", "ledger.jsonl": b"old\n"})
        gh.refs["brain/state"] = state
        return gh, wr, state

    def test_one_commit_on_the_read_head(self):
        gh, wr, state = self.state()
        before = len(gh.requests)
        sha = wr.commit_files("brain/state", state, {"ledger.jsonl": b"old\nnew\n"}, "cycle 1")
        self.assertEqual(gh.refs["brain/state"], sha)
        self.assertEqual(gh.commits[sha]["parents"], [state])
        self.assertEqual(gh.read_file("brain/state", "ledger.jsonl"), b"old\nnew\n")
        self.assertEqual(gh.read_file("brain/state", "keep.txt"), b"k\n")  # the head's tree is the base
        sent = [(m, path[len(P):]) for m, path, _ in gh.requests[before:]]
        self.assertEqual(sent, [("GET", "git/ref/heads/brain/state"), ("GET", "git/commits/" + state),
                                ("POST", "git/blobs"), ("POST", "git/trees"), ("POST", "git/commits"),
                                ("PATCH", "git/refs/heads/brain/state")])
        self.assertEqual(gh.requests[-1][2], {"sha": sha, "force": False})
        self.assertEqual(wr.written, ["refs/heads/brain/state"])
        self.assertEqual(gh.refs["main"], gh.refs["brain/integration"])

    def test_a_moved_head_is_refused_before_any_object(self):
        gh, wr, state = self.state()
        moved = gh.seed_commit("s1", [state])
        gh.refs["brain/state"] = moved
        before = len(gh.requests)
        with self.assertRaises(W.Refused) as ctx:
            wr.commit_files("brain/state", state, {"ledger.jsonl": b"x\n"}, "cycle 1")
        self.assertEqual(ctx.exception.reasons, ["state_head_moved"])
        self.assertEqual([r[0] for r in gh.requests[before:]], ["GET"])
        self.assertEqual(gh.refs["brain/state"], moved)

    def test_outside_brain_and_bad_paths_are_refused_before_sending(self):
        gh, wr, state = self.state()
        gh.refs["main"] = state
        before = len(gh.requests)
        for branch in ("main", "brainx/state", "brain/../main"):
            with self.assertRaises(W.Refused):
                wr.commit_files(branch, state, {"ledger.jsonl": b"x\n"}, "m")
        self.assertEqual(gh.requests[before:], [])
        with self.assertRaises(W.Refused) as ctx:
            wr.commit_files("brain/state", state, {".git/hooks/post-checkout": b"x"}, "m")
        self.assertEqual(ctx.exception.reasons, ["body_invalid"])
        self.assertNotIn("POST", [r[0] for r in gh.requests[before:] if r[1].endswith("git/trees")])
        self.assertEqual(gh.refs["brain/state"], state)

    def test_responses_without_a_sha(self):
        for route in ("git/blobs", "git/trees"):
            gh, wr, state = self.state()
            gh.overrides[("POST", P + route)] = (201, {"sha": None})
            with self.assertRaises(W.ApiError):
                wr.commit_files("brain/state", state, {"ledger.jsonl": b"x\n"}, "m")
            self.assertEqual(gh.refs["brain/state"], state)

    def test_orphan_holds_only_its_files_and_has_no_parent(self):
        gh, wr, root = world()
        before = len(gh.requests)
        sha = wr.open_orphan("brain/state", {"ledger.jsonl": b"g\n", "chain/root.jsonl": b"r\n"}, "genesis")
        self.assertEqual(gh.refs["brain/state"], sha)
        self.assertEqual(gh.commits[sha]["parents"], [])
        self.assertEqual(gh.trees[gh.commits[sha]["tree"]].keys(), {"ledger.jsonl", "chain/root.jsonl"})
        self.assertEqual(gh.read_file("brain/state", "chain/root.jsonl"), b"r\n")
        sent = [(m, path[len(P):]) for m, path, _ in gh.requests[before:]]
        self.assertEqual(sent, [("GET", "git/ref/heads/brain/state"), ("POST", "git/blobs"), ("POST", "git/blobs"),
                                ("POST", "git/trees"), ("POST", "git/commits"), ("POST", "git/refs")])
        self.assertNotIn("base_tree", gh.requests[before + 3][2])
        self.assertEqual(wr.written, ["refs/heads/brain/state"])

    def test_orphan_over_an_existing_branch_is_refused_before_any_object(self):
        gh, wr, state = self.state()
        before = len(gh.requests)
        with self.assertRaises(W.Refused) as ctx:
            wr.open_orphan("brain/state", {"ledger.jsonl": b"x\n"}, "genesis")
        self.assertEqual(ctx.exception.reasons, ["branch_exists"])
        self.assertEqual([r[0] for r in gh.requests[before:]], ["GET"])
        self.assertEqual(gh.refs["brain/state"], state)
        for branch in ("main", "brain/../main", "Brain/state"):
            with self.assertRaises(W.Refused):
                wr.open_orphan(branch, {"ledger.jsonl": b"x\n"}, "genesis")
        with self.assertRaises(W.Unusable):
            wr.open_orphan("brain/other", {}, "genesis")
        self.assertEqual([r[0] for r in gh.requests[before:]], ["GET"])

    def test_exists_reads_404_as_absent_and_raises_other_errors(self):
        gh, wr, state = self.state()
        self.assertTrue(wr.exists("brain/state"))
        self.assertFalse(wr.exists("brain/none"))
        gh.overrides[("GET", P + "git/ref/heads/brain/x")] = (500, {})
        with self.assertRaises(W.ApiError):
            wr.exists("brain/x")


class Revert(unittest.TestCase):
    def merged(self):
        gh, wr, root = world()
        n, sha = candidate(gh, wr)
        wr.check(sha, GATE, "success")
        return gh, wr, root, wr.merge(n, sha)

    def test_revert_tree_is_the_first_parents_tree(self):
        gh, wr, root, merge = self.merged()
        sent = len(wr.sent)
        out = wr.revert(merge, "brain/integration", "brain/c/revert-1", "revert: test_regression")
        first, second = gh.commits[merge]["parents"]
        self.assertNotEqual(gh.commits[first]["tree"], gh.commits[merge]["tree"])
        self.assertEqual(out["tree"], gh.commits[first]["tree"])
        self.assertNotIn(out["tree"], (gh.commits[merge]["tree"], gh.commits[second]["tree"]))
        self.assertEqual(gh.commits[out["commit"]], {"tree": gh.commits[first]["tree"], "parents": [merge],
                                                     "message": "revert: test_regression"})
        self.assertEqual([(m, p) for m, p, _ in wr.sent[sent:]], [
            ("GET", P + "git/commits/" + merge), ("GET", P + "git/commits/" + first),
            ("GET", P + "git/ref/heads/brain/integration"), ("POST", P + "git/commits"), ("POST", P + "git/refs")])
        self.assertEqual(gh.refs["brain/c/revert-1"], out["commit"])
        self.assertEqual(gh.refs["brain/integration"], merge)  # the revert is a branch, not a push
        n = wr.open_pull("brain/c/revert-1", "brain/integration", "revert: test_regression")
        wr.check(out["commit"], GATE, "success")
        reverted = wr.merge(n, out["commit"])
        self.assertEqual(gh.commits[reverted]["tree"], gh.commits[root]["tree"])
        self.assertEqual(gh.commits[reverted]["parents"], [merge, out["commit"]])
        self.assertEqual(gh.refs["main"], root)
        self.assertTrue(all(r.startswith("refs/heads/brain/") for r in written_refs(gh)))
        self.assertEqual(wr.written, written_refs(gh))

    def test_only_the_head_is_reverted(self):
        gh, wr, root, merge = self.merged()
        n, sha = candidate(gh, wr, "brain/c/2", "t2")
        wr.check(sha, GATE, "success")
        wr.merge(n, sha)
        sent = len(writes(gh))
        with self.assertRaises(W.Refused) as ctx:
            wr.revert(merge, "brain/integration", "brain/c/revert-1", "revert")
        self.assertEqual(ctx.exception.reasons, ["revert_not_head"])
        self.assertEqual(len(writes(gh)), sent)

    def test_only_a_merge_is_reverted(self):
        gh, wr, root = world()
        gh.direct_push_denied = set()
        child = wr.commit("plain", gh.commits[root]["tree"], [root])
        wr.update_branch("brain/integration", child)
        sent = len(writes(gh))
        with self.assertRaises(W.Refused) as ctx:
            wr.revert(child, "brain/integration", "brain/c/revert-1", "revert")
        self.assertEqual(ctx.exception.reasons, ["revert_not_merge"])
        self.assertEqual(len(writes(gh)), sent)

    def test_revert_branch_outside_brain_is_refused_before_any_call(self):
        gh, wr, root, merge = self.merged()
        sent = len(gh.requests)
        for branch in ("main", "brain", "brain/../main"):
            with self.assertRaises(W.Refused):
                wr.revert(merge, "brain/integration", branch, "revert")
        self.assertEqual(len(gh.requests), sent)

    def test_pure_rule(self):
        commits = {A: {"tree": "1" * 40, "parents": []}, B: {"tree": "2" * 40, "parents": [A, "c" * 40]},
                   "c" * 40: {"tree": "3" * 40, "parents": [A]}, "d" * 40: {"tree": "4" * 40, "parents": [A]}}
        self.assertEqual(W.revert_commit(commits, B, B), ([], {"tree": "1" * 40, "parents": [B]}))
        self.assertEqual(W.revert_commit(commits, "d" * 40, B), (["revert_not_head"], None))
        self.assertEqual(W.revert_commit(commits, "d" * 40, "d" * 40), (["revert_not_merge"], None))
        self.assertEqual(W.revert_commit(commits, "e" * 40, "e" * 40), (["commit_unknown"], None))
        self.assertEqual(W.revert_commit({B: commits[B]}, B, B), (["commit_unknown"], None))
        for tree in (None, "x", "1" * 39):
            self.assertEqual(W.revert_commit({B: commits[B], A: {"tree": tree, "parents": []}}, B, B),
                             (["commit_unknown"], None), tree)
        three = {B: {"tree": "2" * 40, "parents": [A, A, A]}, A: commits[A]}
        self.assertEqual(W.revert_commit(three, B, B), (["revert_not_merge"], None))


class _FakeHttps(urllib.request.BaseHandler):
    handler_order = 100

    def __init__(self, answers):
        self.answers = list(answers)
        self.seen = []

    def https_open(self, req):
        self.seen.append(req)
        status, body, extra = self.answers.pop(0)
        headers = Message()
        for k, v in extra.items():
            headers[k] = v
        resp = urllib.response.addinfourl(io.BytesIO(body), headers, req.full_url, status)
        resp.msg = "x"
        return resp


class Transport(unittest.TestCase):
    def test_request_shape(self):
        fake = _FakeHttps([(201, b'{"sha": "%s"}' % A.encode(), {})])
        t = W.HttpTransport("tok", handlers=(fake,))
        status, data = t("POST", P + "git/commits", {"message": "m", "tree": A, "parents": [B]})
        self.assertEqual((status, data), (201, {"sha": A}))
        req = fake.seen[0]
        self.assertEqual(req.full_url, "https://api.github.com" + P + "git/commits")
        self.assertEqual(req.get_method(), "POST")
        self.assertEqual(req.get_header("Authorization"), "Bearer tok")
        self.assertEqual(json.loads(req.data), {"message": "m", "tree": A, "parents": [B]})

    def test_no_redirect_is_followed(self):
        for code in (301, 302, 303, 307, 308):
            fake = _FakeHttps([(code, b"", {"Location": "https://evil.example/x"}), (200, b"{}", {})])
            t = W.HttpTransport("tok", handlers=(fake,))
            with self.assertRaises(W.ApiError) as ctx:
                t("POST", P + "git/refs", {"ref": "refs/heads/brain/c/1", "sha": A})
            self.assertEqual(ctx.exception.status, code)
            self.assertEqual([r.full_url for r in fake.seen], ["https://api.github.com" + P + "git/refs"])

    def test_errors(self):
        fake = _FakeHttps([(422, b'{"message": "no"}', {}), (200, b"<html>", {})])
        t = W.HttpTransport("tok", handlers=(fake,))
        with self.assertRaises(W.ApiError) as ctx:
            t("GET", P + "pulls/1", None)
        self.assertEqual(ctx.exception.status, 422)
        with self.assertRaises(W.ApiError):
            t("GET", P + "pulls/1", None)
        for token in ("", "a\nb", None):
            with self.assertRaises(W.Unusable):
                W.HttpTransport(token)

    def test_writer_over_http_refuses_before_the_socket(self):
        fake = _FakeHttps([])
        wr = W.Writer(REPO, W.HttpTransport("tok", handlers=(fake,)))
        with self.assertRaises(W.Refused):
            wr.create_branch("main", A)
        self.assertEqual(fake.seen, [])


NET_MODULES = {"urllib.request", "http.client", "socket", "ssl", "requests", "httpx", "urllib3", "aiohttp",
               "http"}
# The modules that may open a connection, each for one job (tohum/01a): ``yaz`` writes the target through
# ``target.write``; ``getir`` reads registry tarballs through ``deps.fetch`` and sends nothing (no request body,
# no method, no header: ``ReadOnlyFetch`` below); ``cek`` reads the bootstrap referee's state through the Actions API
# with ``loop.accepted`` (GET only, no body: ``test_actions_read_is_get_only``) and the root's Rekor entry with
# ``loop.rekor`` (GET only, no token: ``test_actions_read_is_get_only`` too).
NET_ALLOWED = {os.path.join("target", "write.py"), os.path.join("runner", "deps_npm.py"),
               os.path.join("loop", "accepted.py"), os.path.join("loop", "rekor.py")}
# The modules that may name GitHub's hosts: the writer, and cek's reader (the API, the brain's URL, the bootstrap
# workflow's certificate identity).
GITHUB_NAMED = {os.path.join("target", "write.py"), os.path.join("loop", "accepted.py")}


def scan(rel, src):
    found = []
    for node in ast.walk(ast.parse(src)):
        mods = []
        if isinstance(node, ast.Import):
            mods = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            mods = [node.module] + [node.module + "." + a.name for a in node.names]
        if rel not in NET_ALLOWED:
            found += ["%s: import %s" % (rel, m) for m in mods if m in NET_MODULES]
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and rel != os.path.join("target", "write.py"):
            if ("github.com" in node.value.lower() and rel not in GITHUB_NAMED) \
                    or node.value in ("push", "send-pack", "receive-pack"):
                found.append("%s: %r" % (rel, node.value))
    return found


def referee_modules():
    for top, dirs, files in os.walk(REFEREE):
        dirs[:] = [d for d in dirs if d not in ("tests", "__pycache__")]
        for name in files:
            if name.endswith(".py"):
                path = os.path.join(top, name)
                with open(path, encoding="utf-8") as fh:
                    yield os.path.relpath(path, REFEREE), fh.read()


class OneWay(unittest.TestCase):
    def test_no_other_module_reaches_the_network_or_pushes(self):
        offenders = []
        for rel, src in referee_modules():
            offenders += scan(rel, src)
        self.assertEqual(offenders, [])

    def test_the_scan_sees_an_offender(self):
        src = "import urllib.request\nfrom http import client\nimport subprocess\n" \
              "subprocess.run(['git', 'push'])\nURL = 'https://API.GitHub.com/repos'\n"
        self.assertEqual(sorted(scan(os.path.join("gate", "x.py"), src)), [
            "gate/x.py: 'https://API.GitHub.com/repos'", "gate/x.py: 'push'", "gate/x.py: import http",
            "gate/x.py: import http.client", "gate/x.py: import urllib.request"])
        self.assertEqual(scan(os.path.join("runner", "deps_npm.py"), "import urllib.request\n"), [])

    def test_actions_read_is_get_only(self):
        """``loop.accepted`` builds every request as ``urllib.request.Request(<url>)``: one argument, no ``data``,
        ``method`` or ``headers``, so it only reads; and it names no git push."""
        src = dict(referee_modules())[os.path.join("loop", "accepted.py")]
        calls = [n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.Call)
                 and isinstance(n.func, ast.Attribute) and n.func.attr == "Request"]
        self.assertEqual(len(calls), 2)
        for call in calls:
            self.assertEqual((len(call.args), call.keywords), (1, []))
        self.assertNotIn("add_data", src)
        self.assertEqual(scan(os.path.join("loop", "accepted.py"), src), [])
        self.assertEqual(scan(os.path.join("loop", "accepted.py"), src + "\nX = 'push'\n"),
                         ["loop/accepted.py: 'push'"])
        self.assertEqual(scan(os.path.join("loop", "job.py"), "U = 'https://github.com/%s'\n"),
                         ["loop/job.py: 'https://github.com/%s'"])
        # loop.rekor: one Request of one argument, and no token, header or body anywhere in it
        src = dict(referee_modules())[os.path.join("loop", "rekor.py")]
        calls = [n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.Call)
                 and isinstance(n.func, ast.Attribute) and n.func.attr == "Request"]
        self.assertEqual([(len(c.args), c.keywords) for c in calls], [(1, [])])
        for word in ("add_data", "add_header", "add_unredirected_header", "Authorization", "headers="):
            self.assertNotIn(word, src)
        self.assertEqual(scan(os.path.join("loop", "rekor.py"), src), [])

    def test_read_only_fetch(self):
        """``deps.fetch`` opens a bare URL: no ``Request``, no ``data``/``method``/``headers`` anywhere."""
        src = dict(referee_modules())[os.path.join("runner", "deps_npm.py")]
        bad = []
        for node in ast.walk(ast.parse(src)):
            if isinstance(node, ast.Attribute) and node.attr in ("Request", "urlopen", "add_header"):
                bad.append(node.attr)
            if isinstance(node, ast.Call):
                bad += [k.arg for k in node.keywords if k.arg in ("data", "method", "headers")]
        self.assertEqual(bad, [])


def cli(*args, api=None, request=None):
    """``python -m target.write`` with ``api`` written to a file (appended to ``args``) and ``request`` on stdin."""
    with tempfile.TemporaryDirectory() as tmp:
        argv = list(args)
        if api is not None:
            path = os.path.join(tmp, "api.json")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(api if isinstance(api, str) else json.dumps(api))
            argv.append(path)
        stdin = request if isinstance(request, str) else json.dumps(request)
        proc = subprocess.run([sys.executable, "-m", "target.write", *argv], cwd=REFEREE, capture_output=True,
                              text=True, input=stdin, timeout=60)
    assert "Traceback" not in proc.stderr, proc.stderr
    assert proc.stdout.count("\n") == 1, proc.stdout
    return proc.returncode, json.loads(proc.stdout)


M, F1, F2, T1, T2, TM, R, H = ("1" * 40, "2" * 40, "3" * 40, "4" * 40, "5" * 40, "6" * 40, "7" * 40, "8" * 40)
REVERT_API = {
    "GET %sgit/commits/%s" % (P, M): {"sha": M, "tree": {"sha": TM}, "parents": [{"sha": F1}, {"sha": F2}]},
    "GET %sgit/commits/%s" % (P, F1): {"sha": F1, "tree": {"sha": T1}, "parents": []},
    "GET %sgit/commits/%s" % (P, F2): {"sha": F2, "tree": {"sha": T2}, "parents": [{"sha": F1}]},
    "GET %sgit/ref/heads/brain/integration" % P: {"ref": "refs/heads/brain/integration", "object": {"sha": M}},
    "POST %sgit/commits" % P: {"sha": R, "tree": {"sha": T1}},
    "POST %sgit/refs" % P: {"ref": "refs/heads/brain/c/revert-1", "object": {"sha": R}},
}
PULL = {"number": 7, "state": "open", "base": {"ref": "brain/integration"}, "head": {"ref": "brain/c/1", "sha": H}}
MERGE_API = {"GET %spulls/7" % P: PULL, "PUT %spulls/7/merge" % P: {"merged": True, "sha": M}}
REFUSED = {"ok": False, "refs": [], "writes": [], "commit": None, "forced": False}


class CommandLine(unittest.TestCase):
    def test_revert_first_parent_tree(self):
        req = {"op": "revert", "repo": REPO, "merge_sha": M, "onto": "refs/heads/brain/integration",
               "ref": "refs/heads/brain/c/revert-1"}
        self.assertEqual(cli("replay", api=REVERT_API, request=req), (0, {
            "ok": True, "refs": ["refs/heads/brain/c/revert-1"],
            "writes": ["POST %sgit/commits" % P, "POST %sgit/refs" % P],
            "commit": {"tree": T1, "parents": [M]}, "forced": False}))
        moved = dict(REVERT_API, **{"GET %sgit/ref/heads/brain/integration" % P: {
            "ref": "refs/heads/brain/integration", "object": {"sha": H}}})
        code, out = cli("replay", api=moved, request=req)
        self.assertEqual((code, out), (1, dict(REFUSED, reasons=["revert_not_head"])))

    def test_refuse_main_and_lookalikes(self):
        api = {"PATCH %sgit/refs/heads/main" % P: {"ref": "refs/heads/main"},
               "POST %sgit/refs" % P: {"ref": "x"}, "PATCH %sgit/refs/heads/brain" % P: {}}
        for op, ref, reason in (("update", "refs/heads/main", "ref_outside_brain"),
                                ("branch", "refs/heads/main", "ref_outside_brain"),
                                ("update", "refs/heads/brain", "ref_outside_brain"),
                                ("branch", "refs/heads/brainx/y", "ref_outside_brain"),
                                ("branch", "refs/heads/Brain/y", "ref_outside_brain"),
                                ("branch", "refs/tags/brain/y", "ref_outside_brain"),
                                ("branch", "brain/c/1", "ref_outside_brain"),
                                ("branch", "refs/heads/brain/../main", "ref_invalid"),
                                ("update", "refs/heads/brain/./x", "ref_invalid"),
                                ("branch", "refs/heads/brain//x", "ref_invalid"),
                                ("update", "refs/tags/xbrain/c/1", "ref_outside_brain"),  # 11 chars, then brain/
                                ("branch", "xxxxxxxxxxxbrain/c/1", "ref_outside_brain")):
            code, out = cli("replay", api=api, request={"op": op, "repo": REPO, "ref": ref, "sha": A})
            self.assertEqual((code, out), (1, dict(REFUSED, reasons=[reason])), (op, ref))

    def test_branch_and_update_never_force(self):
        api = {"POST %sgit/refs" % P: {}, "PATCH %sgit/refs/heads/brain/c/x" % P: {}}
        self.assertEqual(cli("replay", api=api, request={"op": "branch", "repo": REPO, "ref": "refs/heads/brain/c/x",
                                                         "sha": A}),
                         (0, {"ok": True, "refs": ["refs/heads/brain/c/x"], "writes": ["POST %sgit/refs" % P],
                              "commit": None, "forced": False}))
        req = {"op": "update", "repo": REPO, "ref": "refs/heads/brain/c/x", "sha": A}
        self.assertEqual(cli("replay", api=api, request=req),
                         (0, {"ok": True, "refs": ["refs/heads/brain/c/x"],
                              "writes": ["PATCH %sgit/refs/heads/brain/c/x" % P], "commit": None, "forced": False}))
        wr = W.writer_for(req, W.Replay(api))
        W.run_request(dict(req, force=True), wr)  # a request cannot ask for force
        self.assertEqual(wr.sent, [("PATCH", P + "git/refs/heads/brain/c/x", {"sha": A, "force": False})])

    def test_forced_reports_what_was_sent(self):
        wr = W.Writer(REPO, W.Replay({}))
        wr.sent = [("PATCH", P + "git/refs/heads/brain/x", {"sha": A, "force": True})]
        self.assertTrue(W.outcome(wr)["forced"])
        wr.sent = [("PATCH", P + "git/refs/heads/brain/x", {"sha": A, "force": False}),
                   ("POST", P + "git/refs", {"ref": "refs/heads/brain/y", "sha": A, "force": True})]
        self.assertFalse(W.outcome(wr)["forced"])

    def test_commit_is_the_last_commit_sent(self):
        wr = W.Writer(REPO, W.Replay({}))
        wr.sent = [("POST", P + "git/commits", {"message": "a", "tree": A, "parents": []}),
                   ("GET", P + "git/commits/" + A, None),
                   ("POST", P + "git/commits", {"message": "b", "tree": B, "parents": [A]})]
        self.assertEqual(W.outcome(wr)["commit"], {"tree": B, "parents": [A]})

    def test_merge(self):
        self.assertEqual(cli("replay", api=MERGE_API, request={"op": "merge", "repo": REPO, "pr": 7}),
                         (0, {"ok": True, "refs": ["refs/heads/brain/integration"],
                              "writes": ["PUT %spulls/7/merge" % P], "commit": None, "forced": False}))
        wr = W.writer_for({"op": "merge", "repo": REPO, "pr": 7}, W.Replay(MERGE_API))
        W.run_request({"op": "merge", "repo": REPO, "pr": 7}, wr)
        self.assertEqual(wr.sent[-1][2], {"sha": H, "merge_method": "merge"})  # pinned to the head read

    def test_refuse_merge_into_main(self):
        for base, reason in (("main", "ref_outside_brain"), ("brain", "ref_outside_brain")):
            api = dict(MERGE_API, **{"GET %spulls/7" % P: dict(PULL, base={"ref": base})})
            self.assertEqual(cli("replay", api=api, request={"op": "merge", "repo": REPO, "pr": 7}),
                             (1, dict(REFUSED, reasons=[reason])))
        api = dict(MERGE_API, **{"GET %spulls/7" % P: dict(PULL, state="closed")})
        self.assertEqual(cli("replay", api=api, request={"op": "merge", "repo": REPO, "pr": 7}),
                         (1, dict(REFUSED, reasons=["merge_not_open"])))

    def test_pull_requests(self):
        api = {"POST %spulls" % P: {"number": 3}}
        for head, base in (("brain/c/1", "main"), ("main", "brain/integration"), ("brain/c/1", "refs/heads/main"),
                           ("brain/c/1", "brainx/integration")):
            code, out = cli("replay", api=api, request={"op": "pr", "repo": REPO, "head": head, "base": base,
                                                        "title": "t"})
            self.assertEqual((code, out), (1, dict(REFUSED, reasons=["ref_outside_brain"])), (head, base))
        req = {"op": "pr", "repo": REPO, "head": "refs/heads/brain/c/1", "base": "brain/integration", "title": "t"}
        self.assertEqual(cli("replay", api=api, request=req),
                         (0, {"ok": True, "refs": [], "writes": ["POST %spulls" % P], "commit": None, "forced": False}))
        wr = W.writer_for(req, W.Replay(api))
        W.run_request(req, wr)
        self.assertEqual(wr.sent[0][2]["head"], "brain/c/1")

    def test_check(self):
        api = {"POST %scheck-runs" % P: {"id": 1}}
        req = {"op": "check", "repo": REPO, "sha": A, "name": GATE, "conclusion": "success"}
        self.assertEqual(cli("replay", api=api, request=req),
                         (0, {"ok": True, "refs": [], "writes": ["POST %scheck-runs" % P], "commit": None,
                              "forced": False}))

    def test_unrecorded_call_is_unusable(self):
        code, out = cli("replay", api={}, request={"op": "branch", "repo": REPO, "ref": "refs/heads/brain/c/1",
                                                   "sha": A})
        self.assertEqual((code, out["ok"], out["refs"], out["writes"]), (2, False, [], ["POST %sgit/refs" % P]))
        self.assertTrue(out["error"].startswith("api: 404"), out["error"])
        no_ref = {k: v for k, v in REVERT_API.items() if k != "POST %sgit/refs" % P}
        code, out = cli("replay", api=no_ref,
                        request={"op": "revert", "repo": REPO, "merge_sha": M, "onto": "refs/heads/brain/integration",
                     "ref": "refs/heads/brain/c/revert-1"})
        self.assertEqual((code, out["refs"], out["commit"]), (2, [], {"tree": T1, "parents": [M]}))
        self.assertEqual(out["writes"], ["POST %sgit/commits" % P, "POST %sgit/refs" % P])

    def test_a_fault_after_a_write_reports_the_writes_and_the_type_only(self):
        """The one module handler kept (cli's rule 6): it knows what was sent, and writes the type, not the message."""
        from unittest import mock
        from test_cli import MARK, run_boundary
        real = W.run_request

        def faulty(req, wr):
            real(req, wr)
            raise RuntimeError(MARK)
        req = {"op": "revert", "repo": REPO, "merge_sha": M, "onto": "refs/heads/brain/integration",
               "ref": "refs/heads/brain/c/revert-1"}
        with tempfile.TemporaryDirectory() as tmp:
            api = os.path.join(tmp, "api.json")
            with open(api, "w", encoding="utf-8") as fh:
                json.dump(REVERT_API, fh)
            with mock.patch.object(W, "run_request", faulty), mock.patch.object(W.sys, "stdin", io.StringIO(json.dumps(req))):
                code, out, err = run_boundary(W.main, ["replay", api], W.FAULT_LINE)
        self.assertEqual((code, err), (2, ""))
        self.assertNotIn(MARK, out)
        self.assertEqual(json.loads(out), {"ok": False, "error": "internal error: RuntimeError",
                                           "refs": ["refs/heads/brain/c/revert-1"],
                                           "writes": ["POST %sgit/commits" % P, "POST %sgit/refs" % P],
                                           "commit": {"tree": T1, "parents": [M]}, "forced": False})

    def test_unusable(self):
        good = {"op": "branch", "repo": REPO, "ref": "refs/heads/brain/c/1", "sha": A}
        for args, api, req in ((("replay",), {}, "{"), (("replay",), "[", good), (("replay",), [], good),
                               (("replay",), {}, dict(good, op="delete")), (("replay",), {}, {"op": "branch"}),
                               (("replay",), {}, dict(good, sha="x")), (("replay",), {}, dict(good, repo="x")),
                               (("replay",), {}, dict(good, ref=7)),
                               (("replay",), {}, {"op": "merge", "repo": REPO, "pr": True}),
                               (("replay",), {}, {"op": "merge", "repo": REPO, "pr": "7"}),
                               (("replay",), {}, {"op": "merge", "repo": REPO, "pr": 0}),
                               (("replay",), {}, {"op": "merge", "repo": REPO, "pr": 10 ** 10}),
                               (("replay",), {}, {"op": "check", "repo": REPO, "sha": A, "name": "n",
                                                  "conclusion": "neutral"}),
                               (("replay",), {}, {"op": "pr", "repo": REPO, "head": "brain/c/1",
                                                  "base": "brain/integration", "title": ""}),
                               (("replay",), {}, {"op": "revert", "repo": REPO, "merge_sha": M, "onto": "brain/x",
                                                  "ref": "refs/heads/brain/c/r"}),
                               (("replay",), REVERT_API, {"op": "revert", "repo": REPO, "merge_sha": M,
                                                          "onto": "refs/heads/brain/integration",
                                                          "ref": "refs/heads/brain/c/r", "message": ""}),
                               (("guard",), {}, good), ((), None, good)):
            code, out = cli(*args, api=api, request=req)
            self.assertEqual(code, 2, (args, api, req))
            self.assertFalse(out["ok"])
            self.assertIn("unusable", out["error"])


if __name__ == "__main__":
    unittest.main()
