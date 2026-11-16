"""What merging one accepted candidate, or reverting a red merge, writes on the target, in one place (stage 0; called
by ``activate`` and D6 and D7 of ``yaz``).

Rules: asama-0/08 (an accepted candidate is applied to ``brain/integration``'s head), asama-0/01 D6 (``yaz``
writes ``brain/c/<id>``, the pull request, the check and the merge; every ref under ``refs/heads/brain/``),
tohum/01b (``brain/integration`` takes changes only by pull request, merges are serial), tohum/07 (a verified red
merge is reverted; the revert passes the gate like a merge), ``target.write`` (MF9, the
one writer; its guard checks every request).

``applied(tree, diff_text)``: the candidate's one changed file after its diff, ``{reasons, path, content, hunks}``. The
diff must parse (``gate.diffguard.parse``) and change exactly one file (``diff_not_one_file`` otherwise: the gate's
criterion 4 lets a candidate change only its finding's file, and nothing here writes more than one); the base file is
read from ``tree`` at the block's path (a regular file, no symbolic link on its way, else ``base_file_missing``) and
the hunks applied (``gate.diffguard.apply``, which takes only an in-place text change: a creation, deletion, rename,
copy, mode change or binary patch is ``patch_does_not_apply`` too). ``hunks`` are the block's text hunks in diff
order, each ``{old_start, old_count, new_start, new_count}`` as its ``@@`` header gives them (``gate.diffguard.HUNK_RANGE``; empty for
a block with no hunk), the ranges ``ledger.events.hunk_covered`` records. ``content`` and ``hunks`` are ``None`` with
a reason.

``land(writer, cid, path, content, base, check)``: branch ``brain/c/<cid>`` at ``base``, one commit setting ``path``
to ``content``, a pull request into ``brain/integration``, a ``success`` check run named ``check`` on the commit, and
the merge pinned to that commit; returns ``{pull, head_sha, merge_sha}``. Each step is one ``target.write`` call;
an error leaves the earlier steps written (the caller's ``HardStop`` names them, ``writer.written``).

``plant(writer, cycle_id, path, content, base, check)``: D8's planted merge (the revert drill's, ``loop.drill``), the
same five steps on branch ``brain/drill/<cycle_id>``, its title and check summary saying it is planted by the drill
and is not a gate decision; returns ``{pull, head_sha, merge_sha}``. ``harness.revert_drill.run_drill`` makes the same
writes through the same function (``pull_merge``).

``revert(writer, merge_sha, runs, facts, check)``: D7's revert of ``merge_sha``, ``brain/integration``'s head, when
``runs`` are a verified red: ``gate.revert.revert_red`` (the revert commit, whose tree is the merge's first
parent's, on ``brain/revert/<merge_sha>``, and its pull request into ``brain/integration``), then the same check and
pinned merge as a candidate's. Returns ``{cause, pull, commit, merge_sha}`` (``merge_sha`` the revert's merge
commit). Runs that are not red are ``Unusable``, before anything is written (the caller reverts only a red).

Out of scope, stated: whether ``base`` is still ``brain/integration``'s head (the caller reads it before landing;
GitHub refuses a merge that is not a fast-forward of a moved base only by the ruleset's strict check); that the
file is the finding's (the gate's criterion 4, judged before).
"""

from __future__ import annotations

from typing import Any

from gate import diffguard
from gate import revert as gate_revert
from ledger import append
from profile import derive
from target import branches, write

CANDIDATE_PREFIX = "brain/c/"
DRILL_PREFIX = "brain/drill/"
REVERT_PREFIX = "brain/revert/"


class Unusable(ValueError):
    pass


class HardStop(append.HardStop):
    """A cycle's write failed after its first write; ``written`` names the refs already written (tohum/28)."""

    def __init__(self, message: str, written: list[str]):
        super().__init__("%s (written: %s)" % (message, ", ".join(written) or "nothing"))
        self.written = written


def applied(tree: str, diff_text: str) -> dict:
    """``{reasons, path, content}``: see the module docstring."""
    try:
        blocks = diffguard.parse(diff_text)
    except diffguard.DiffError:
        return {"reasons": ["diff_unusable"], "path": None, "content": None, "hunks": None}
    if len(blocks) != 1:
        return {"reasons": ["diff_not_one_file"], "path": None, "content": None, "hunks": None}
    path = blocks[0]["new"] or blocks[0]["old"]
    old = derive._read_regular(tree, path)
    if old is None:
        return {"reasons": ["base_file_missing"], "path": path, "content": None, "hunks": None}
    try:
        content = diffguard.apply(blocks[0], old)
    except diffguard.DiffError:
        return {"reasons": ["patch_does_not_apply"], "path": path, "content": None, "hunks": None}
    return {"reasons": [], "path": path, "content": content,
            "hunks": [{k: h[k] for k in diffguard.HUNK_RANGE} for h in blocks[0]["hunks"]]}


def pull_merge(writer: Any, branch: str, base: str, files: dict[str, bytes], onto: str, title: str, body: str,
               check: str, summary: str) -> dict:
    """``branch`` at ``base``, one commit of ``files``, a pull request into ``onto``, a ``success`` check named
    ``check`` on the commit and the merge pinned to it: ``{pull, head_sha, merge_sha}``. One sequence for a candidate,
    a planted drill merge and ``harness.revert_drill``'s."""
    writer.create_branch(branch, base)
    head = writer.commit_files(branch, base, files, title)
    pull = writer.open_pull(branch, onto, title, body)
    return {"pull": pull, "head_sha": head, "merge_sha": _checked_merge(writer, pull, head, check, summary)}


def land(writer: Any, cid: str, path: str, content: bytes, base: str, check: str) -> dict:
    """Branch, commit, pull request, check and merge of one accepted candidate onto ``brain/integration``."""
    return pull_merge(writer, CANDIDATE_PREFIX + cid, base, {path: content}, branches.INTEGRATION, "candidate %s" % cid,
                      "accepted by the gate (asama-0/08)", check, "gate: merge")


def plant(writer: Any, cycle_id: str, path: str, content: bytes, base: str, check: str) -> dict:
    """D8's planted merge onto ``brain/integration`` (see the module docstring)."""
    return pull_merge(writer, DRILL_PREFIX + cycle_id, base, {path: content}, branches.INTEGRATION,
                      planted_title(cycle_id), PLANTED_BODY, check, planted_summary(cycle_id))


PLANTED_BODY = "planted by exit.drill (revert)"


def planted_title(cycle_id: str) -> str:
    return "drill %s: planted merge" % cycle_id


def planted_summary(cycle_id: str) -> str:
    return "planted by exit.drill (revert) for cycle %s; not a gate decision" % cycle_id


def revert(writer: Any, merge_sha: str, runs: Any, facts: Any, check: str) -> dict:
    """D7's revert of ``merge_sha`` onto ``brain/integration`` (see the module docstring)."""
    done = gate_revert.revert_red(writer, runs, facts, merge_sha, branches.INTEGRATION, REVERT_PREFIX + merge_sha)
    if not done["reverted"]:  # revert_red sent nothing
        raise Unusable("the sentinel's runs are not a verified red (%s): nothing to revert" % done["verdict"])
    summary = "gate: revert of %s, cause %s" % (merge_sha, done["cause"])
    return {"cause": done["cause"], "pull": done["pull"], "commit": done["commit"],
            "merge_sha": _checked_merge(writer, done["pull"], done["commit"], check, summary)}


def _checked_merge(writer: Any, pull: Any, head: str, check: str, summary: str) -> str:
    """The gate's ``success`` check on ``head``, then the pull request's merge pinned to it: one step for a
    candidate and a revert."""
    if pull is None:
        raise write.ApiError(None, "pull request created without a number")
    writer.check(head, check, "success", summary)
    return writer.merge(pull, head)
