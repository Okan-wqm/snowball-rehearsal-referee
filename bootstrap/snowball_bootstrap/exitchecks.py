"""The (A) conditions of `asama-0/10` that `pull` checks on the brain archive it already holds (`29b`; the draft `29e`
"Tohum denetimleri": in `çek`, read from the archive, never run in a container): #kurucu-defteri, #is-akisi, #agac
and #genellik (E162's follow-up, E280-E285, E288-E292).

Each anchor's result is ``{status: ok | failed | undecided, reasons, why}`` in ``meta["exit_checks"]``; `decide` turns
it into the exit's conditions, and an absent or undecided result keeps the exit closed as ``not_checked``, never
passes. A check that cannot decide says why; it never becomes the Founder's ``pull_error``.

No result says a target's name in clear (E290): wherever a reason's subject or a ``why`` holds a name from
``targets[].identifiers``, it is replaced by ``sha256:`` and the first 16 hex characters of its sha256 (`withheld`), in
every anchor's result and in the exit's other reasons (`cli`).
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from typing import Any, Callable

from . import ledgercheck, wiring
from .classify import is_agent_config
from .config import Target, names_the_copy
from .treehash import CaseCollision, TreeError, iter_files, tree_hash

ANCHORS = ("kurucu-defteri", "is-akisi", "agac", "genellik")
REFEREE = "referee"
TOY_DIR = "tests/fixtures/toy-repo"  # the toy target's content (`13`, `24a`), which the import copies (`25a`)
MAX_REASONS = 20
WITHHELD_RE = re.compile(r"sha256:[0-9a-f]{16}\Z")


def outcome(reasons: list[str], why: str = "") -> dict[str, Any]:
    return {"status": "failed" if reasons else "ok", "reasons": list(reasons), "why": why}


def undecided(why: str) -> dict[str, Any]:
    return {"status": "undecided", "reasons": [], "why": why}


def referee_files(tar_bytes: bytes) -> dict[str, bytes]:
    """Every regular file under `referee/`, by its path in the brain."""
    return {path.as_posix(): content for path, content, _x in iter_files(tar_bytes) if path.parts[:1] == (REFEREE,)}


def referee_tree(files: dict[str, bytes], tar_bytes: bytes) -> tuple[dict[str, Any], str | None]:
    """#agac besides the operator names (the referee tree hash refuses those itself, `treehash.RESERVED_TOP`, as the
    pre-reason ``referee_tree:``, and two names one on the operator's Windows, E289): no agent configuration anywhere in
    `referee/` (`29f`; no exception for fixtures, E285), and the toy subtree's hash for the signed result, which the
    import's #oyuncak compares (`10a`, E131); the toy too is copied onto that file system."""
    reasons = [f"agent_config_in_referee:{path}" for path in sorted(files) if is_agent_config(path)][:MAX_REASONS]
    toy: str | None = None
    try:
        toy = tree_hash(tar_bytes, TOY_DIR, forbid_operator_names=False, fold_case=True)
    except CaseCollision as exc:
        reasons.append(f"toy_tree:{exc}")
    except TreeError:
        reasons.append("toy_tree_missing")
    return outcome(reasons), toy


def fold(text: str) -> str:
    """The form a name is compared in (E291): compatibility-decomposed and case-folded, without combining marks, the
    dotless ı as i. So ``güneş`` in NFC or NFD, ``GÜNEŞ``, ``gunes``, ``ｇｕｎｅｓ`` are one name, and so are ``İskele``,
    ``ıskele`` and ``iskele``; every pair Python's ``re.IGNORECASE`` takes for one letter folds alike."""
    text = unicodedata.normalize("NFKD", unicodedata.normalize("NFKD", text).casefold())
    return "".join(ch for ch in text if not unicodedata.combining(ch)).replace("\u0131", "i")


def target_names(targets: tuple[Target, ...] | None) -> list[tuple[int, int, str]]:
    """``(target index, identifier index, folded name)`` for every identifier with something left to look for."""
    return [(i, j, fold(name)) for i, t in enumerate(targets or ()) for j, name in enumerate(t.identifiers)
            if fold(name)]


def _first(names: list[tuple[int, int, str]], text: str) -> tuple[int, int] | None:
    folded = fold(text)
    return next(((i, j) for i, j, name in names if name in folded), None)


def withheld(text: str, names: list[tuple[int, int, str]]) -> str:
    """``text``, or ``sha256:<16 hex>`` of it when it holds a target's name (E290): the one rule for showing a text
    that may carry a name. Already withheld text is left as it is."""
    if WITHHELD_RE.match(text) or _first(names, text) is None:
        return text
    return f"sha256:{hashlib.sha256(text.encode('utf-8', 'surrogatepass')).hexdigest()[:16]}"


def withheld_reason(reason: str, names: list[tuple[int, int, str]]) -> str:
    """A reason with its subject (what follows the rule's name) withheld when it holds a target's name."""
    rule, colon, subject = reason.partition(":")
    return f"{rule}:{withheld(subject, names)}" if colon else reason


def _text(content: bytes) -> str | None:
    """A file's text: strict UTF-8 without a NUL (git's own test for a binary file); None when it is not text."""
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        return None
    return None if "\0" in text else text


def generality(files: dict[str, bytes], targets: tuple[Target, ...] | None) -> dict[str, Any]:
    """#genellik (E284, E291): no name from `setup/summary.json` ``targets[].identifiers`` in `referee/`, looked for
    in every path and in every file's text, each compared `fold`-ed.

    The copy target is the one with an outside name to keep out: without ``targets[]``, without a copy target, or with
    a copy target that names no identifier, nothing can be decided (the operator's step, `25` 10a). The toy's content
    is the Founder's own fixture, so a toy target without identifiers has nothing to look for and is fine.
    A file that is not UTF-8 text (or holds a NUL) cannot be read for a name, so it does not pass:
    ``referee_file_not_text:<path>``, the Founder's to fix. The names are never published (`withheld`); ``why`` says
    which target and identifier by their index.
    """
    if not names_the_copy(targets):
        return undecided("setup/summary.json does not name the copy target's identifiers in targets[] (`26c`, `25` "
                         "10a): the operator's step, so nothing can be looked for yet (E99, E284)")
    names = target_names(targets)
    if len(names) != sum(len(t.identifiers) for t in targets or ()):
        return undecided("an identifier in setup/summary.json targets[] has no letter left once folded (E291): the "
                         "operator's step to name it so it can be looked for")
    reasons: list[str] = []
    found: list[str] = []
    for path in sorted(files):
        shown = withheld(path, names)
        hit = _first(names, path[len(REFEREE) + 1:])
        text = _text(files[path]) if hit is None else ""
        if text is None:
            reasons.append(f"referee_file_not_text:{shown}")
            continue
        if hit is None:
            hit = _first(names, text)
        if hit is not None:
            reasons.append(f"target_name_in_referee:{shown}")
            found.append(f"{shown}: targets[{hit[0]}].identifiers[{hit[1]}]")
    return outcome(reasons[:MAX_REASONS], "; ".join(found[:MAX_REASONS]))


def founder_ledger(head: bytes | None, base: bytes | None) -> dict[str, Any]:
    """#kurucu-defteri at the exit: the whole file (`ledgercheck`); ``why`` names each accepted row a later row closed
    beside the row that closed it (`13`, E280), so the signed result keeps both."""
    reasons, closures = ledgercheck.judge(head, base, whole=True)
    return outcome(reasons, "; ".join(f"L{old} superseded by L{new}" for old, new in closures))


def _guarded(check: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    try:
        return check()
    except Exception as exc:  # noqa: BLE001  a check that breaks decides nothing: the exit stays closed and says why
        return undecided(f"the check could not run ({type(exc).__name__}); the exit stays closed until it can")


def run(tar_bytes: bytes, ledger_head: bytes | None, ledger_base: bytes | None,
        targets: tuple[Target, ...] | None) -> tuple[dict[str, dict[str, Any]], str | None]:
    """Every anchor's result, with any target name withheld (E290), and the toy subtree's hash (None when it has
    none)."""
    toy: list[str | None] = [None]
    names = target_names(targets)

    def tree() -> dict[str, Any]:
        result, toy[0] = referee_tree(referee_files(tar_bytes), tar_bytes)
        return result

    checks: dict[str, Callable[[], dict[str, Any]]] = {
        "kurucu-defteri": lambda: founder_ledger(ledger_head, ledger_base),
        "is-akisi": lambda: outcome(wiring.check(wiring.files_in(referee_files(tar_bytes)))),
        "agac": tree,
        "genellik": lambda: generality(referee_files(tar_bytes), targets),
    }
    results = {anchor: _guarded(checks[anchor]) for anchor in ANCHORS}
    for result in results.values():
        result["reasons"] = [withheld_reason(r, names) for r in result["reasons"]]
        result["why"] = withheld(result["why"], names)
    return results, toy[0]
