"""An in-process model of the GitHub REST routes ``target.write`` uses (tests only, asama-0/14 row 9 "Kum").

State: refs (name -> sha), commits (sha -> {tree, parents}), pulls, check runs, and every request received.
It models what the writer depends on and the target's rulesets (tohum/25a row 3), nothing more:

- a ref update that is not a fast-forward is refused (422) unless ``force`` is true;
- a branch in ``direct_push_denied`` (``brain/integration``) refuses ``PATCH`` of its ref (422); it changes only
  by a merge, and a merge into it needs a ``success`` check run on the head sha. Creating a branch (``POST
  git/refs``) is refused only for a name in ``create_denied`` (empty by default): tohum/25a row 3 lists no
  creation rule for ``brain/integration``, so activation cuts it with ``POST``; whether GitHub's ``pull_request``
  rule also refuses that creation is not modelled as known, both answers are tested (asama-0/10a #genesis);
- a merge needs the base head to be an ancestor of the pull's head (no three-way merge is modelled; else 405);
  the merge commit has parents ``[base head, head sha]`` and the head's tree; ``sha`` must equal the head;
- a commit's tree must already be known (from a seeded commit or ``POST git/trees``), its parents must exist;
- blobs hold bytes and trees map paths to blobs (``base_tree`` entries kept, the new ones set on top), so
  ``read_file`` gives a branch's file content back.

**Object ids.** A blob, a tree and a commit the API creates (``POST git/blobs``, ``git/trees``, ``git/commits``, a
merge) has the id git gives the same object (``git_store``'s format: every file ``100644``, a fixed author), as
GitHub's ids are git's, so the same commit can be read by ``loop.gitobj`` (``git_objects``: every such object in git's
format, for ``git_store``'s fake ``git``). ``seed_files`` seeds a commit the same way; ``seed_commit`` and a test that
fills ``commits`` or ``trees`` by hand give made-up ids, which ``git_objects`` refuses (``NotGit``).

It also answers routes the writer must never call (``PUT contents``, ``POST merges``, ``DELETE`` of a ref), so
a test can see that the guard, not the fake, stopped them: ``requests`` records every request received.
"""

from __future__ import annotations

import base64
import copy
import hashlib
import re

import git_store
from ledger.chain import canonical
from target import branches

SHA = re.compile(r"[0-9a-f]{40}")


def sha_of(obj) -> str:
    return hashlib.sha1(canonical(obj)).hexdigest()


class NotGit(Exception):
    """An object ``git_objects`` cannot give in git's format: a made-up id, or one it does not hold."""


class FakeGitHub:
    def __init__(self, repo: str = "acme/toy", direct_push_denied=("brain/integration",),
                 required_check: str = branches.CHECK, create_denied=()):
        self.prefix = "/repos/%s/" % repo
        self.refs: dict[str, str] = {}
        self.commits: dict[str, dict] = {}
        self.blobs: dict[str, bytes] = {}
        self.trees: dict[str, dict[str, str]] = {}
        self.pulls: dict[int, dict] = {}
        self.checks: list[dict] = []
        self.requests: list[tuple] = []
        self.direct_push_denied = set(direct_push_denied)
        self.create_denied = set(create_denied)
        self.required_check = required_check
        self.overrides: dict[tuple, tuple] = {}

    # ---- seeding
    def seed_commit(self, tree_name: str, parents=(), msg="seed", files=None) -> str:
        tree = sha_of(["tree", tree_name])
        self.trees[tree] = {path: self._blob(data) for path, data in (files or {}).items()}
        rec = {"tree": tree, "parents": list(parents), "message": msg}
        sha = sha_of(rec)
        self.commits[sha] = rec
        return sha

    def seed_files(self, files: dict[str, bytes], parents=(), msg="seed") -> str:
        """A commit of ``files`` on ``parents`` with git's ids (see "Object ids"), as the API would create it."""
        tree = self._tree({path: self._blob(data) for path, data in files.items()})
        return self._new_commit({"tree": tree, "parents": list(parents), "message": msg})

    def _tree(self, files: dict[str, str]) -> str:
        sha = git_store.store_tree({path: self.blobs[blob] for path, blob in files.items()}, {})
        self.trees[sha] = files
        return sha

    def _new_commit(self, rec: dict) -> str:
        sha = git_store.commit({}, rec["tree"], rec["message"].encode("utf-8"), tuple(rec["parents"]))
        self.commits[sha] = rec
        return sha

    def git_objects(self, commits) -> dict[str, tuple[str, bytes]]:
        """Every object reachable from ``commits`` (their parents, trees and blobs), sha -> (type, content) in git's
        format; ``NotGit`` when one of them does not have git's id."""
        objects: dict = {}
        todo, seen = list(commits), set()
        while todo:
            sha = todo.pop()
            if sha in seen:
                continue
            seen.add(sha)
            rec = self.commits.get(sha)
            if rec is None or rec["tree"] not in self.trees:
                raise NotGit("commit %s is not held" % sha)
            got = git_store.store_tree({p: self.blobs[b] for p, b in self.trees[rec["tree"]].items()}, objects)
            made = git_store.commit(objects, got, rec["message"].encode("utf-8"), tuple(rec["parents"]))
            if (got, made) != (rec["tree"], sha):
                raise NotGit("commit %s has a made-up id" % sha)
            todo.extend(rec["parents"])
        return objects

    def _blob(self, data: bytes) -> str:
        sha = hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()
        self.blobs[sha] = data
        return sha

    def read_file(self, branch: str, path: str) -> bytes | None:
        blob = self.trees[self.commits[self.refs[branch]]["tree"]].get(path)
        return None if blob is None else self.blobs[blob]

    def ancestors(self, sha: str) -> set[str]:
        seen, todo = set(), [sha]
        while todo:
            s = todo.pop()
            if s not in seen:
                seen.add(s)
                todo.extend(self.commits[s]["parents"])
        return seen

    # ---- transport
    def __call__(self, method: str, path: str, body):
        self.requests.append((method, path, copy.deepcopy(body)))
        if (method, path) in self.overrides:
            return self.overrides[(method, path)]
        if not path.startswith(self.prefix):
            return 404, {"message": "Not Found"}
        rest = path[len(self.prefix):]
        handler = getattr(self, "_" + method.lower(), None)
        return handler(rest, body) if handler else (405, {"message": "method"})

    def _ref(self, name):
        return {"ref": "refs/heads/" + name, "object": {"sha": self.refs[name], "type": "commit"}}

    def _commit(self, sha):
        rec = self.commits[sha]
        return {"sha": sha, "tree": {"sha": rec["tree"]}, "parents": [{"sha": p} for p in rec["parents"]],
                "message": rec["message"]}

    def _pull(self, n):
        p = self.pulls[n]
        return {"number": n, "state": p["state"], "merged": p["merged"],
                "base": {"ref": p["base"]}, "head": {"ref": p["head"], "sha": self.refs.get(p["head"], p["sha"])}}

    def _get(self, rest, body):
        m = re.fullmatch(r"git/ref/heads/(.+)", rest)
        if m:
            return (200, self._ref(m.group(1))) if m.group(1) in self.refs else (404, {"message": "Not Found"})
        m = re.fullmatch(r"git/commits/(.+)", rest)
        if m:
            return (200, self._commit(m.group(1))) if m.group(1) in self.commits else (404, {})
        m = re.fullmatch(r"pulls/(\d+)", rest)
        if m:
            return (200, self._pull(int(m.group(1)))) if int(m.group(1)) in self.pulls else (404, {})
        return 404, {"message": "Not Found"}

    def _set_ref(self, name, sha, force, create=False):
        if name in (self.create_denied if create else self.direct_push_denied):
            return 422, {"message": "Repository rule violations: changes must be made through a pull request"}
        if sha not in self.commits:
            return 422, {"message": "Object does not exist"}
        if name in self.refs and not force and self.refs[name] not in self.ancestors(sha):
            return 422, {"message": "Update is not a fast forward"}
        self.refs[name] = sha
        return 200, self._ref(name)

    def _post(self, rest, body):
        if rest == "git/refs":
            name = body["ref"][len("refs/heads/"):]
            if name in self.refs:
                return 422, {"message": "Reference already exists"}
            status, data = self._set_ref(name, body["sha"], False, create=True)
            return (201 if status == 200 else status), data
        if rest == "git/commits":
            if body["tree"] not in self.trees or \
                    any(p not in self.commits for p in body["parents"]):
                return 422, {"message": "tree or parent does not exist"}
            rec = {"tree": body["tree"], "parents": list(body["parents"]), "message": body["message"]}
            return 201, self._commit(self._new_commit(rec))
        if rest == "git/blobs":
            return 201, {"sha": self._blob(base64.b64decode(body["content"]))}
        if rest == "git/trees":
            if "base_tree" in body and body["base_tree"] not in self.trees:
                return 422, {"message": "base_tree does not exist"}
            files = dict(self.trees[body["base_tree"]]) if "base_tree" in body else {}
            for entry in body["tree"]:
                if entry["sha"] not in self.blobs:
                    return 422, {"message": "blob does not exist"}
                files[entry["path"]] = entry["sha"]
            return 201, {"sha": self._tree(files)}
        if rest == "pulls":
            if body["head"] not in self.refs or body["base"] not in self.refs:
                return 422, {"message": "head or base does not exist"}
            n = len(self.pulls) + 1
            self.pulls[n] = {"base": body["base"], "head": body["head"], "state": "open", "merged": False,
                             "sha": self.refs[body["head"]]}
            return 201, self._pull(n)
        if rest == "check-runs":
            self.checks.append(copy.deepcopy(body))
            return 201, {"id": len(self.checks), "head_sha": body["head_sha"]}
        if rest == "merges":  # never allowed by the guard; modelled so a test sees it was not reached
            self.refs[body["base"]] = self.refs[body["head"]]
            return 201, {"sha": self.refs[body["base"]]}
        return 404, {"message": "Not Found"}

    def _patch(self, rest, body):
        m = re.fullmatch(r"git/refs/heads/(.+)", rest)
        if not m or m.group(1) not in self.refs:
            return 422, {"message": "Reference does not exist"}
        return self._set_ref(m.group(1), body["sha"], bool(body.get("force")))

    def _put(self, rest, body):
        m = re.fullmatch(r"pulls/(\d+)/merge", rest)
        if m and int(m.group(1)) in self.pulls:
            p = self.pulls[int(m.group(1))]
            head = self.refs[p["head"]]
            if p["state"] != "open":
                return 405, {"message": "Pull Request is not mergeable"}
            if body.get("sha") != head:
                return 409, {"message": "Head branch was modified"}
            if p["base"] in self.direct_push_denied and not any(
                    c["head_sha"] == head and c["name"] == self.required_check and c["conclusion"] == "success"
                    for c in self.checks):
                return 405, {"message": "Required status check is expected"}
            base_head = self.refs[p["base"]]
            if base_head not in self.ancestors(head):
                return 405, {"message": "merge conflict (not modelled)"}
            rec = {"tree": self.commits[head]["tree"], "parents": [base_head, head],
                   "message": "Merge pull request #%s" % m.group(1)}
            sha = self._new_commit(rec)
            self.refs[p["base"]] = sha
            p["state"], p["merged"] = "closed", True
            return 200, {"sha": sha, "merged": True, "message": "Pull Request successfully merged"}
        if rest.startswith("contents/"):  # never allowed by the guard
            return 201, {"commit": {"sha": "0" * 40}}
        return 404, {"message": "Not Found"}

    def _delete(self, rest, body):  # never allowed by the guard
        m = re.fullmatch(r"git/refs/heads/(.+)", rest)
        if m and m.group(1) in self.refs:
            del self.refs[m.group(1)]
            return 204, None
        return 422, {}
