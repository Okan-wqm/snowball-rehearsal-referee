"""``yaz``'s half of D7: the sentinel's verdict read from ``kos``'s results, and the facts ``gate.revert`` needs for a
red (stage 0).

Rules: asama-0/01 D7 (the sentinel runs in the next cycle's ``koş`` and ``yaz``; green, or a revert with its
``cause``), tohum/07 (on red, the 3/3 rule, then ``gate.revert``; a revert is written with a ``cause``), tohum/01b
(the gate reads results by artifact and hash), tohum/29j (``cause``'s request: the verified red tests, the impact
set declared at the merge, "in stage 0 the unit's service-free tests", ``build_ok``, and each tool's lint total at
the merge's first parent and at the head; their producers are the Founder's code, the seed's answer to seed-044).

**The verdict** (``read(results, watch)``). ``watch`` is the merge whose sentinel ``kos`` ran, chosen from the state
by the rule ``kos`` uses (``loop.job._watched``: the one unfinished merge, at ``brain/integration``'s head), or
``None``. The results' ``index.json`` ``sentinel`` must agree:

- ``watch`` ``None``: the entry must be ``null`` (else ``sentinel_unexpected``); the answer is ``None``;
- else the entry must be an object naming ``watch`` (else ``sentinel_missing``). Its ``verdict`` ``null`` (``kos``
  ran no run that tells something) is ``{merge_sha, verdict: null, reasons}``: nothing to act on this cycle;
- else ``sentinel.json``'s bytes must hash to the entry's ``sha256`` (``sentinel_hash_mismatch``, a missing file
  included), be ``{merge_sha, runs, verdict, red, flaky}`` naming ``watch`` (``sentinel_unreadable``), and MF12's
  own ``gate.sentinel.decide`` on its ``runs`` must give its ``verdict``, ``red`` and ``flaky`` and the index's
  verdict (``sentinel_verdict_mismatch``; runs ``decide`` refuses are ``sentinel_unreadable``). The answer is
  ``{merge_sha, verdict, runs, red, flaky, sha256}`` (``sha256`` the verified ``sentinel.json``'s, which D7's end
  row of a green or flaky verdict carries, ``ledger.events.sentinel``).

Any reason is ``Refused`` with it; nothing is decided from a sentinel this reader did not verify.

**The base's lint** (``base_lint(results)``): ``base.jsonl`` of the results with ``index.json``'s
``base_run_sha256``, read by ``gate.check.base_counts`` (the hash, the three records one): ``{base_run_sha256,
counts}`` or ``None`` when there is no such file, its hash or records do not hold, or ``run_file`` refuses it.
It is the lint at ``brain/integration``'s head: D6 records it as the ``ratchet_base`` of a cycle that merges (the
merge's lint before) and D7 reads it as a red's lint after.

**The head's build** (``base_build(results)``). ``build_ok`` is whether the code at the red head built and loaded
(tohum/29j); the seed leaves its producer to this code (its answer to seed-044). A stage 0 unit has no build command
(an npm unit runs its sources as they are), so the one compile step it has is its lint tool parsing every file it
lints with the unit's own parser configuration (ESLint, ``runner.lint_record``): a file the tool cannot parse is
reported as a fatal message, which ``runner.lint_record`` refuses as ``fatal:<path>`` and ``kos`` lists as the base's
``lint_output:fatal:<path>``. ``kos`` lints the head (``brain/integration``'s, the watched merge) in the cycle that
runs its sentinel. From ``index.json``'s ``base`` (``{verdict, reasons}``):

- ``false``: some reason is ``lint_output:fatal:<path>`` and none is ``red_control_green`` (a sandbox a known bad
  command passed judges nothing), and the base run is not verified;
- ``true``: the base's ``reasons`` are ``[]`` and ``base_lint`` verifies its base run: each of the three lint runs
  parsed every file it read;
- ``None`` otherwise: the lint told nothing about parsing (a run over a limit, a failing or crashing tool, output that
  does not convert for another reason, a base that did not stage, an index without ``base``).

What it does not judge, stated: a file the lint tool does not read (outside its configuration or ignored), a module
that parses but does not load (a missing import, a throw at load time: that shows as failing tests of the run, so
``test_regression``), and whether the merge's first parent parsed: at a merge of the gate it did (its cycle merged
only with a base run, which exists only when every file parsed), at a planted merge (D8) it is not checked. What it takes on trust, stated: the unit's lint parser configuration
parses what the unit's runtime loads; a file that configuration cannot parse but the runtime would load (a syntax
the runtime has and the configured parser lacks) is judged ``false``, a build break the runtime would not show.

**The facts of a red** (``facts(sentinel, ledger, after, build_ok)``), each rule exact and stated, since no page names
them:

- ``impact``: every test id the sentinel's runs report, sorted. Stage 0's impact set is the unit's whole
  service-free test set (asama-0/08 item 6), which is what ``affected_test_cmd`` runs; so a red test is always in
  it and ``impact_miss`` is not reachable from the live path at stage 0;
- ``build_ok``: ``base_build``'s answer (above), given by the caller; ``None`` makes ``gate.revert.assess``'s cause
  ``unknown`` (no rule after ``build_break`` can be stated when the build is not known);
- ``lint``: per tool in either, in sorted order, ``{before, after}`` (a tool absent from one side counts 0, ``gate.check``'s rule):
  ``before`` the ratchet base of the merge's cycle (``ledger.serial.lint_before`` of ``brain/state``'s ledger),
  ``after`` ``base_lint``'s counts; ``None`` when either is missing (``gate.revert.assess``'s rule then).

Caller: ``loop.job``'s ``yaz`` (D7, before D6's writes); the revert itself and its row are ``loop.write_cycle``'s.
Out of scope, stated: the drill's merges (D8).
"""

from __future__ import annotations

import hashlib
import os
from typing import Any

import cli
from gate import check
from gate import sentinel as S
from ledger import serial
from runner import kos

DOC_KEYS = {"merge_sha", "runs", "verdict", "red", "flaky"}
FATAL = "lint_output:fatal:"  # kos's prefix of runner.lint_record's fatal:<path>


class Refused(Exception):
    def __init__(self, reasons: list[str]) -> None:
        super().__init__(", ".join(reasons))
        self.reasons = reasons


def _bytes(path: str) -> bytes | None:
    try:
        with open(path, "rb") as fh:
            return fh.read()
    except (FileNotFoundError, NotADirectoryError, IsADirectoryError):
        return None


def _index(results: str) -> dict:
    raw = _bytes(os.path.join(results, kos.INDEX))
    try:
        doc = cli.loads(raw) if raw is not None else None
    except ValueError:
        doc = None
    return doc if isinstance(doc, dict) else {}


def read(results: str, watch: str | None) -> dict | None:
    """The sentinel's verdict for ``watch``; see the module docstring."""
    entry = _index(results).get("sentinel")
    if watch is None:
        if entry is not None:
            raise Refused(["sentinel_unexpected"])
        return None
    if not isinstance(entry, dict) or entry.get("merge_sha") != watch:
        raise Refused(["sentinel_missing"])
    if entry.get("verdict") is None:
        return {"merge_sha": watch, "verdict": None, "reasons": entry.get("reasons")}
    raw = _bytes(os.path.join(results, kos.SENTINEL))
    if raw is None or hashlib.sha256(raw).hexdigest() != entry.get("sha256"):
        raise Refused(["sentinel_hash_mismatch"])
    try:
        doc = cli.loads(raw)
        if not (isinstance(doc, dict) and set(doc) == DOC_KEYS and doc["merge_sha"] == watch):
            raise Refused(["sentinel_unreadable"])
        judged = S.decide(doc["runs"])
    except ValueError:  # S.Unusable is one
        raise Refused(["sentinel_unreadable"]) from None
    if (judged["verdict"], judged["red"], judged["flaky"]) != (doc["verdict"], doc["red"], doc["flaky"]) \
            or doc["verdict"] != entry["verdict"]:
        raise Refused(["sentinel_verdict_mismatch"])
    return {"merge_sha": watch, "verdict": doc["verdict"], "runs": doc["runs"], "red": doc["red"],
            "flaky": doc["flaky"], "sha256": entry["sha256"]}


def base_run(results: str) -> tuple[bytes, str] | None:
    """The results' base run as given: ``(base.jsonl's bytes, index.json's base_run_sha256)``, or ``None`` when
    either is missing; nothing judged (``base_lint`` and ``activate``'s ratchet base judge it)."""
    sha = _index(results).get("base_run_sha256")
    raw = _bytes(os.path.join(results, kos.BASE))
    return None if raw is None or not isinstance(sha, str) else (raw, sha)


def base_lint(results: str) -> dict | None:
    """``{base_run_sha256, counts}`` of the results' base run, or ``None``; see the module docstring."""
    given = base_run(results)
    if given is None:
        return None
    raw, sha = given
    try:
        got = check.base_counts(raw, sha)
    except check.Unusable:
        return None
    return None if got["reasons"] else {"base_run_sha256": sha, "counts": got["counts"]}


def base_build(results: str) -> bool | None:
    """Whether the head's code built (``build_ok``), from the results' base lint; see the module docstring."""
    base = _index(results).get("base")
    reasons = base.get("reasons") if isinstance(base, dict) else None
    if not (isinstance(reasons, list) and all(isinstance(r, str) for r in reasons)):
        return None
    verified = base_lint(results) is not None
    if any(r.startswith(FATAL) for r in reasons) and "red_control_green" not in reasons and not verified:
        return False
    if not reasons and verified:
        return True
    return None


def facts(sentinel: dict, ledger: bytes, after: dict | None, build_ok: bool | None) -> dict[str, Any]:
    """``{impact, build_ok, lint}`` of a red ``sentinel`` (``read``'s answer); see the module docstring.
    ``ledger.serial.Unusable`` for a ledger it cannot read."""
    impact = sorted({r["id"] for run in sentinel["runs"] for r in run["results"]})
    before = serial.lint_before(ledger, sentinel["merge_sha"])
    lint = None
    if before is not None and after is not None:
        lint = {tool: {"before": before.get(tool, 0), "after": after["counts"].get(tool, 0)}
                for tool in sorted(set(before) | set(after["counts"]))}
    return {"impact": impact, "build_ok": build_ok, "lint": lint}
