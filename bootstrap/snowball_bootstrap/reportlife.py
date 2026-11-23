"""The life of the brain's reports as the bootstrap referee counts it (`tohum/26l`, seed epoch AD, E694).

A report is the Founder's file (`reports/<id>.json`, `26c`), known by its file name; its `state` is one of a closed
set, and the reading is closed: any other value, a missing state, an `id` that is not the file's name, or a terminal
state without what it needs counts as `open`. The operator's answers are seed data, `reports/answers.json` beside this
package (one source; the epoch's CHANGELOG row is its human form): `{id, changelog: CHANGELOG-<n>, kind:
answered|partial|declined}`. The same file carries the `(id, sha256)` of the reports confirmed at the brain commit it
names, which stay closed while their bytes are unchanged (loosening L-AD2).

`split` is the one rule both readers apply, the referee (`decide`) and the operator's launcher (`seed/founder/launch.py`):
the open reports no answer names are the operator's debt (`reports_open`), the open reports an answer names, or that
were carried, are the Founder's (`reports_unconfirmed`; L-AD3). Both are warnings, never reasons.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPORT_FIELDS = ("id", "kind", "ref", "state")  # of each `reports/*.json` the signed result names (`26c`, E93)
STATES = ("open", "confirmed", "declined", "superseded", "withdrawn")
ANSWER_KINDS = ("answered", "partial", "declined")
CHECK_KINDS = ("test", "read")  # `read`: the answer is read, not yet built (loosening L-AD1)
MAX_FIELD = 500  # the longest string field of a report that is read; a longer one reads as null
MAX_REFS = 50
ANSWERS_FILE = Path(__file__).resolve().parents[1] / "reports" / "answers.json"
ANSWERS_SCHEMA = "snowball-report-answers/1"
COMMIT_RE = re.compile(r"[0-9a-f]{40}\Z")
SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
CHANGELOG_RE = re.compile(r"CHANGELOG-[1-9][0-9]*\Z")
PAGE_REF_RE = re.compile(r"[A-Za-z0-9._/-]+(:[0-9]+(-[0-9]+)?)?\Z")  # `26k`, `26k:12`, `asama-1/13d:12-36`


class AnswersError(ValueError):
    """The seed's answers file is not the shape this module reads: the operator's mistake, caught by CI."""


@dataclass(frozen=True)
class Answers:
    kinds: dict[str, frozenset[str]]  # report id -> the kinds of the operator's answers that name it
    carried: frozenset[tuple[str, str]]  # (id, sha256) of the reports confirmed at the carried brain commit


def _text(value: Any) -> str | None:
    return value if isinstance(value, str) and value.strip() and len(value) <= MAX_FIELD else None


def epoch_commits(summary: Any) -> frozenset[str]:
    """The `seed_epochs[].commit` values of a `setup/summary.json` document (`26c`): the brain's delivery commits
    (`25` 10b, `26l`). A row that is not an object with a full commit adds nothing; a summary without the list has
    none, so no confirmation's ``epoch`` is one of them."""
    rows = summary.get("seed_epochs") if isinstance(summary, dict) else None
    return frozenset(row["commit"] for row in rows if isinstance(row, dict) and isinstance(row.get("commit"), str)
                     and COMMIT_RE.match(row["commit"])) if isinstance(rows, list) else frozenset()


def evidence(data: Any, epochs: frozenset[str] | None = None) -> bool:
    """A closing write's typed evidence (`26l` "Teyidin kanıtı"): ``epoch`` the full commit of a `seed_epochs[]` row,
    ``answered_by`` a non-empty list of page references, ``check`` a command, ``check_kind`` `test` or `read`. The form
    is read; the command is the Founder's, re-runnable by anyone, never run here. With ``epochs`` (`epoch_commits`)
    the ``epoch`` must also be one of the summary's delivery commits (seed-096, epoch AF): forty digits of a commit
    that delivered no seed prove nothing, and the report counts open (a warning, never a reason)."""
    if not isinstance(data, dict):
        return False
    refs = data.get("answered_by")
    return (isinstance(data.get("epoch"), str) and bool(COMMIT_RE.match(data["epoch"]))
            and (epochs is None or data["epoch"] in epochs)
            and isinstance(refs, list) and 0 < len(refs) <= MAX_REFS
            and all(isinstance(r, str) and len(r) <= MAX_FIELD and PAGE_REF_RE.match(r) for r in refs)
            and _text(data.get("check")) is not None
            and data.get("check_kind") in CHECK_KINDS)


def read_row(name: str, content: bytes | None, epochs: frozenset[str] | None = None) -> dict[str, Any]:
    """One `reports/<name>` as both readers count it: ``{stem, id, kind, ref, state, sha256, evidence, superseded_by,
    derived_from}``. ``stem`` is the file name without `.json`, the report's key. A field that is missing, not a string
    or longer than ``MAX_FIELD``, or any field of a file that is not one JSON object, is null; ``content`` None (bytes
    that could not be read) leaves every field null, so the report counts open. ``epochs`` is what the evidence's
    ``epoch`` must be one of (`evidence`); both readers pass the setup summary's, the referee from its checkout and the
    launcher from the referee repository's main."""
    data: Any = None
    if content is not None:
        try:
            data = json.loads(content.decode("utf-8"))
        except (UnicodeDecodeError, ValueError, RecursionError):
            data = None
    doc = data if isinstance(data, dict) else {}
    row: dict[str, Any] = {"stem": name[:-len(".json")] if name.endswith(".json") else name}
    for key in REPORT_FIELDS:
        value = doc.get(key)
        row[key] = value if isinstance(value, str) and len(value) <= MAX_FIELD else None
    row["sha256"] = hashlib.sha256(content).hexdigest() if content is not None else None
    row["evidence"] = evidence(doc, epochs)
    row["superseded_by"] = _text(doc.get("superseded_by"))
    row["derived_from"] = _text(doc.get("derived_from"))
    return row


def _no_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    keys = [k for k, _ in pairs]
    if len(keys) != len(set(keys)):
        raise AnswersError(f"report answers: a repeated key in one object: {sorted(keys)}")
    return dict(pairs)


def load_answers(path: Path | None = None) -> Answers:
    """The seed's answers file, read strictly: a malformed one is an error, never an empty list."""
    try:
        doc = json.loads((path or ANSWERS_FILE).read_text(encoding="utf-8"), object_pairs_hook=_no_duplicate_keys)
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise AnswersError(f"report answers: {exc}") from exc
    if not isinstance(doc, dict) or set(doc) != {"schema", "answers", "carried"} or doc["schema"] != ANSWERS_SCHEMA:
        raise AnswersError("report answers: expected {schema, answers, carried} of " + ANSWERS_SCHEMA)
    kinds: dict[str, set[str]] = {}
    seen: set[tuple[str, str]] = set()
    if not isinstance(doc["answers"], list):
        raise AnswersError("report answers: answers must be a list")
    for i, row in enumerate(doc["answers"]):
        if (not isinstance(row, dict) or set(row) != {"id", "changelog", "kind"} or _text(row["id"]) is None
                or not isinstance(row["changelog"], str) or not CHANGELOG_RE.match(row["changelog"])
                or row["kind"] not in ANSWER_KINDS):
            raise AnswersError(f"report answers: answers[{i}] must be {{id, changelog: CHANGELOG-<n>, kind}}")
        if (row["id"], row["changelog"]) in seen:
            raise AnswersError(f"report answers: answers[{i}] repeats {row['id']} in {row['changelog']}")
        seen.add((row["id"], row["changelog"]))
        kinds.setdefault(row["id"], set()).add(row["kind"])
    carried = doc["carried"]
    if (not isinstance(carried, dict) or set(carried) != {"brain", "confirmed"}
            or not isinstance(carried["brain"], str) or not COMMIT_RE.match(carried["brain"])
            or not isinstance(carried["confirmed"], list)):
        raise AnswersError("report answers: carried must be {brain: <commit>, confirmed: [...]}")
    pairs: set[tuple[str, str]] = set()
    for i, row in enumerate(carried["confirmed"]):
        if (not isinstance(row, dict) or set(row) != {"id", "sha256"} or _text(row["id"]) is None
                or not isinstance(row["sha256"], str) or not SHA256_RE.match(row["sha256"])):
            raise AnswersError(f"report answers: carried.confirmed[{i}] must be {{id, sha256}}")
        if any(rid == row["id"] for rid, _ in pairs):
            raise AnswersError(f"report answers: carried.confirmed[{i}] repeats {row['id']}")
        pairs.add((row["id"], row["sha256"]))
    return Answers(kinds={k: frozenset(v) for k, v in kinds.items()}, carried=frozenset(pairs))


def _superseded_closed(report: dict[str, Any], by_stem: dict[str, dict[str, Any]]) -> bool:
    """A supersession closes only toward a real successor: one in the brain whose ``derived_from`` names this report,
    which is not withdrawn, on a ``superseded_by`` chain that ends without a cycle."""
    stem = report["stem"]
    successor = by_stem.get(report.get("superseded_by") or "")
    if successor is None or successor.get("derived_from") != stem:
        return False
    if successor.get("state") == "withdrawn":
        return False
    seen = {stem}
    step: dict[str, Any] | None = successor
    while step is not None and step.get("state") == "superseded":
        if step["stem"] in seen:
            return False  # the chain comes back: nothing new carries what is missing
        seen.add(step["stem"])
        step = by_stem.get(step.get("superseded_by") or "")
    return True


def closed(report: dict[str, Any], by_stem: dict[str, dict[str, Any]], answers: Answers) -> bool:
    """Whether a report counts as closed (`26l` "Okuma kapalıdır"); everything not shown closed counts as open."""
    stem, state = report.get("stem"), report.get("state")
    if not isinstance(stem, str) or report.get("id") != stem:
        return False  # a report is known by its file name; a missing or other id proves nothing
    if (stem, report.get("sha256")) in answers.carried:
        return True  # confirmed at the carried brain commit, bytes unchanged (L-AD2)
    named = answers.kinds.get(stem, frozenset())
    if state == "confirmed":
        return report.get("evidence") is True
    if state == "declined":
        return report.get("evidence") is True and "declined" in named
    if state == "superseded":
        return _superseded_closed(report, by_stem)
    if state == "withdrawn":
        return not named  # only before any epoch names it
    return False


def split(reports: list[dict[str, Any]], answers: Answers) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """(owed by the operator, owed by the Founder): the open reports no answer names, and the open reports an answer
    names or the carried set holds (a carried report touched without the typed fields is the Founder's to finish)."""
    by_stem = {r["stem"]: r for r in reports if isinstance(r.get("stem"), str)}
    carried_ids = {rid for rid, _ in answers.carried}
    owed: list[dict[str, Any]] = []
    unconfirmed: list[dict[str, Any]] = []
    for r in reports:
        if closed(r, by_stem, answers):
            continue
        stem = r.get("stem")
        (unconfirmed if stem in answers.kinds or stem in carried_ids else owed).append(r)
    return owed, unconfirmed


def counts(reports: list[dict[str, Any]], answers: Answers, unread: int = 0) -> tuple[int, int]:
    """`split`'s sizes; ``unread`` reports past the reader's cap count as the operator's, never as closed."""
    owed, unconfirmed = split(reports, answers)
    return len(owed) + unread, len(unconfirmed)
