"""The brain SHA a loop cycle runs and its proof: the bootstrap referee's last signed state (``çek``, D1; stage 0).

Rules: tohum/29b "Durum" (the state is the newest unexpired artifact named exactly ``bootstrap-state`` made by runs of
the referee repository's ``main``, two files ``result.json`` and ``result.json.sigstore.json``; it is opened with
``sigstore verify identity`` against the referee repository's ``bootstrap.yml`` on ``main``; a reader that cannot
verify it, or finds none, stops with exit 2; the last accepted SHA is ``state.last_accepted_sha``), tohum/26c
``setup/imports.jsonl`` (one chained row per import, with ``referee_tree_sha256``; ``loop.treehash`` is the rule),
asama-0/01 D1 (green: the accepted SHA's ``referee/`` hash is the last ``imports.jsonl`` row's).

Every refusal is ``StateError`` with one reason (``reasons[0]``); the ``cek`` job turns it into exit 2 (no verdict), as 29b says.

**Choosing the artifact** (``choose``), over the artifacts listed by ``GET /repos/<repo>/actions/artifacts`` (every
page, ``list_artifacts``): ``name`` exactly ``bootstrap-state``, ``expired`` false, ``workflow_run.head_branch``
``main`` and ``workflow_run.head_repository_id`` equal to ``workflow_run.repository_id`` (a run of the repository
itself, not of a fork's branch called ``main``). Of those, the newest by ``created_at`` (``YYYY-MM-DDTHH:MM:SSZ``,
compared as text), a tie broken by the larger ``id``. None: ``state_absent``. An entry that is not of that form
(missing fields, a ``created_at`` of another form) is ``actions_unreadable``, never skipped, since a skipped entry
could be the newest. The listing's order is not relied on.

**Opening it** (``unpack``): the artifact's zip holds exactly the two files, by those names, each at most
``MAX_FILE`` (16 MiB) bytes, nothing else (no directory, no third file): otherwise ``state_unreadable``. At most
``MAX_FILE + 1`` bytes of a file are read, whatever its header declares; the zip itself is downloaded only up to
``4 * MAX_FILE`` bytes (``state_unreadable`` beyond).

**Verifying it** (``verify_argv``, ``open_state``): both files are written to a fresh directory and ``sigstore verify
identity --bundle <dir>/result.json.sigstore.json --cert-identity
https://github.com/<repo>/.github/workflows/bootstrap.yml@refs/heads/main --cert-oidc-issuer
https://token.actions.githubusercontent.com <dir>/result.json`` runs (``<repo>`` ``owner/name``, checked against
``REPO``; else ``repo_unsafe``); a non-zero exit, or a program that cannot start, is ``state_unverified``. Then
``result.json`` must be a JSON object whose ``state.last_accepted_sha`` is 40 lowercase hex: else ``state_invalid``.
Only bytes that passed the verifier are parsed.

**The import** (``last_import``, the one reader of the file's transfer rows: D1 here and genesis in ``activate``):
``setup/imports.jsonl`` verified with ``ledger.chain.verify_bytes`` as a chain of JSON objects (else
``imports_broken``). The file is also the human-touch counter (tohum/29n: every row is a touch, a touch that is no
transfer has a row of its own form), so the import is the last row that carries ``referee_tree_sha256`` (tohum/29o:
"the last imports row carrying ``referee_tree_sha256``; the counter's other touches are skipped"); no such row is
``imports_no_transfer``; its value must be 64 lowercase hex (``imports_invalid``). It returns that row and its line's
bytes without the LF (``activate``'s ``import_line_sha256``). ``check_tree``: the accepted commit's ``referee/`` hash (``loop.treehash.of_commit``) equals it;
a tree the hash refuses is ``referee_tree_refused`` (the hash's reasons after it in ``reasons``), a different hash
``referee_tree_mismatch``.

Which ``sigstore`` program runs is the caller's argument (``sigstore``, an argv prefix): in a run, the one the
``sigstore`` step installs from ``bootstrap/requirements/sign.txt`` (tohum/29s, ``loop.inputs.sigstore``).

Out of scope, stated: the bundle's transparency-log checks beyond what ``sigstore verify identity`` does; the
other fields of ``result.json`` (its previous result's hash, the frozen specs); which repository the accepted brain
commit is fetched from (``repo_url`` makes the URL of the name its caller gives: ``loop.inputs.brain_repo``); the artifact's retention.

Network: this module and ``target.write`` are the two that name GitHub's hosts; it only reads (every request is a GET
without a body, ``tests/test_write.py`` ``OneWay``), and the token goes only to the API host.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import subprocess
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from typing import Any, Callable, Sequence

import cli
from ledger import chain as C
from loop import treehash as T
from loop.pulled import PulledError

ARTIFACT = "bootstrap-state"
RESULT = "result.json"
BUNDLE = "result.json.sigstore.json"
MAX_FILE = 16 * 1024 * 1024
ISSUER = "https://token.actions.githubusercontent.com"
IDENTITY = "https://github.com/%s/.github/workflows/%s@refs/heads/main"
BOOTSTRAP_WORKFLOW = "bootstrap.yml"  # signs the bootstrap referee's state (tohum/29b)
LOOP_WORKFLOW = "loop.yml"  # its ``yaz`` signs each cycle's root (tohum/01a: yaz holds the Sigstore OIDC identity)
REPO = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})/[A-Za-z0-9._-]{1,100}")
SHA40 = re.compile(r"[0-9a-f]{40}")
HEX64 = re.compile(r"[0-9a-f]{64}")
STAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")
PER_PAGE = 100
MAX_PAGES = 100
API = "https://api.github.com"


class StateError(Exception):
    """``reasons``: the reason code first, then its details (``referee_tree_refused``'s hash reasons); codes only,
    so a handler may read them (``cli.KEPT_ATTRIBUTES``)."""

    def __init__(self, reason: str, details: list[str] | None = None):
        self.reasons = [reason] + list(details or [])
        super().__init__(", ".join(self.reasons))


def repo_url(repo: Any) -> str:
    """The HTTPS URL ``loop.fetch`` reads the GitHub repository ``owner/name`` from (``repo_unsafe`` otherwise): the
    brain's and a target's (``targets[].repo``)."""
    return "https://github.com/%s" % repo_name(repo)


def repo_name(repo: Any) -> str:
    if not (isinstance(repo, str) and REPO.fullmatch(repo) and repo.split("/")[1] not in (".", "..")):
        raise StateError("repo_unsafe")
    return repo


# ---- choosing and opening the artifact -------------------------------------------------------------------------

def _usable(entry: Any) -> bool:
    if not isinstance(entry, dict):
        return False
    run = entry.get("workflow_run")
    return (isinstance(entry.get("name"), str) and isinstance(entry.get("expired"), bool)
            and type(entry.get("id")) is int and isinstance(entry.get("created_at"), str)
            and bool(STAMP.fullmatch(entry["created_at"])) and isinstance(run, dict)
            and isinstance(run.get("head_branch"), (str, type(None)))
            and type(run.get("repository_id")) is int and type(run.get("head_repository_id")) is int)


def choose(artifacts: list[Any]) -> dict:
    """The state artifact among a listing's entries, by the rules above."""
    if not isinstance(artifacts, list) or not all(_usable(a) for a in artifacts):
        raise StateError("actions_unreadable")
    found = [a for a in artifacts if a["name"] == ARTIFACT and not a["expired"]
             and a["workflow_run"]["head_branch"] == "main"
             and a["workflow_run"]["head_repository_id"] == a["workflow_run"]["repository_id"]]
    if not found:
        raise StateError("state_absent")
    return max(found, key=lambda a: (a["created_at"], a["id"]))


def unpack(data: bytes) -> tuple[bytes, bytes]:
    """``(result.json, result.json.sigstore.json)`` from the artifact's zip, by the rules above."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            infos = zf.infolist()
            if sorted(i.filename for i in infos) != sorted([RESULT, BUNDLE]):
                raise StateError("state_unreadable")
            files = {}
            for info in infos:  # the names admit no directory; the read, not the declared size, is the bound
                with zf.open(info) as fh:
                    body = fh.read(MAX_FILE + 1)
                if len(body) > MAX_FILE:
                    raise StateError("state_unreadable")
                files[info.filename] = body
    except (*cli.ARCHIVE_ERRORS, RuntimeError, ValueError):  # cli rule 9
        raise StateError("state_unreadable") from None
    return files[RESULT], files[BUNDLE]


def workflow_identity(repo: str, workflow: str) -> str:
    """The certificate identity of ``workflow`` run on the repository ``repo``'s ``main`` (``repo_unsafe``)."""
    return IDENTITY % (repo_name(repo), workflow)


def identity_argv(sigstore: Sequence[str], bundle: str, identity: str, artifact: str) -> list[str]:
    """``sigstore verify identity`` of ``artifact`` (a path, or ``sha256:<hex>``) with ``bundle`` against
    ``identity`` and GitHub Actions' issuer: the one form both of the loop's Sigstore checks run. ``sigstore`` is
    the program's argv prefix (``loop.inputs.sigstore``: ``(<python>, -m, sigstore)`` in a run)."""
    return [*sigstore, "verify", "identity", "--bundle", bundle, "--cert-identity", identity,
            "--cert-oidc-issuer", ISSUER, artifact]


def verify_argv(sigstore: Sequence[str], repo: str, directory: str) -> list[str]:
    return identity_argv(sigstore, os.path.join(directory, BUNDLE), workflow_identity(repo, BOOTSTRAP_WORKFLOW),
                         os.path.join(directory, RESULT))


def run_verifier(argv: list[str]) -> int:
    """The default verifier: the program's exit code; its output goes to stderr; one that cannot start is 127."""
    try:
        return subprocess.run(argv, stdin=subprocess.DEVNULL, stdout=2, check=False).returncode
    except OSError:
        return 127


def open_state(result: bytes, bundle: bytes, repo: str, sigstore: Sequence[str],
               verifier: Callable[[list[str]], int] = run_verifier) -> dict:
    """The verified result: ``{last_accepted_sha, result_sha256}``, by the rules above (``repo_unsafe`` from
    ``verify_argv``, before the verifier runs)."""
    with tempfile.TemporaryDirectory(prefix="bootstrap-state-") as tmp:
        for name, body in ((RESULT, result), (BUNDLE, bundle)):
            with open(os.path.join(tmp, name), "wb") as fh:
                fh.write(body)
        if verifier(verify_argv(sigstore, repo, tmp)) != 0:
            raise StateError("state_unverified")
    try:
        doc = cli.loads(result.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, RecursionError):
        doc = None
    state = doc.get("state") if isinstance(doc, dict) else None
    sha = state.get("last_accepted_sha") if isinstance(state, dict) else None
    if not (isinstance(sha, str) and SHA40.fullmatch(sha)):
        raise StateError("state_invalid")
    return {"last_accepted_sha": sha, "result_sha256": hashlib.sha256(result).hexdigest()}


# ---- reading the Actions API -------------------------------------------------------------------------------------

class _Capture(urllib.request.HTTPRedirectHandler):
    """Follows no redirect; keeps the location a 302 names, so the caller fetches it without the token."""

    def __init__(self) -> None:
        self.location: str | None = None

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D401 - urllib's signature
        if code == 302:
            self.location = newurl
        return None


class ActionsHttp:
    """GET over HTTPS: ``json(path)`` from the REST API with the token; ``redirect(path)`` the ``Location`` of a
    302 the API answers (an artifact's zip); ``blob(url)`` that location's bytes, without the token (the token is
    never sent to another host), at most ``limit`` bytes. No redirect is followed by urllib."""

    def __init__(self, token: str, timeout: float = 60.0, handlers: tuple = ()):
        if not isinstance(token, str) or not token or any(c in token for c in "\r\n"):
            raise StateError("token_unusable")
        self.token, self.timeout, self.handlers = token, timeout, handlers
        self.opener = urllib.request.build_opener(_Capture(), *handlers)

    def _req(self, path: str) -> urllib.request.Request:
        req = urllib.request.Request(API + path)
        req.add_header("Authorization", "Bearer " + self.token)
        req.add_header("Accept", "application/vnd.github+json")
        req.add_header("X-GitHub-Api-Version", "2022-11-28")
        return req

    def json(self, path: str) -> Any:
        try:
            with self.opener.open(self._req(path), timeout=self.timeout) as resp:
                return cli.loads(resp.read(MAX_FILE))
        except (urllib.error.URLError, OSError, ValueError):
            raise StateError("actions_unreadable") from None

    def redirect(self, path: str) -> str:
        capture = _Capture()
        try:
            with urllib.request.build_opener(capture, *self.handlers).open(self._req(path), timeout=self.timeout):
                pass
        except (urllib.error.URLError, OSError):
            pass
        if capture.location is None or not capture.location.startswith("https://"):
            raise StateError("actions_unreadable")
        return capture.location

    def blob(self, url: str, limit: int) -> bytes:
        if not url.startswith("https://"):
            raise StateError("actions_unreadable")
        try:
            with self.opener.open(urllib.request.Request(url), timeout=self.timeout) as resp:
                body = resp.read(limit + 1)
        except (urllib.error.URLError, OSError):
            raise StateError("actions_unreadable") from None
        if len(body) > limit:
            raise StateError("state_unreadable")
        return body


def list_artifacts(http: Any, repo: str) -> list[Any]:
    """Every page of the repository's artifacts named ``bootstrap-state`` (``total_count`` read from the first
    page; more than ``MAX_PAGES`` (100) pages, a page that is not ``{total_count, artifacts}``, or a short page before
    the count is reached is ``actions_unreadable``; an empty page ends the read without asking for another)."""
    query = urllib.parse.urlencode({"name": ARTIFACT, "per_page": PER_PAGE})
    out: list[Any] = []
    total = None
    for page in range(1, MAX_PAGES + 1):
        doc = http.json("/repos/%s/actions/artifacts?%s&page=%d" % (repo_name(repo), query, page))
        if not (isinstance(doc, dict) and type(doc.get("total_count")) is int and isinstance(doc.get("artifacts"), list)):
            raise StateError("actions_unreadable")
        total = doc["total_count"] if total is None else total
        out += doc["artifacts"]
        if len(out) >= total:
            return out
        if not doc["artifacts"]:
            break
    raise StateError("actions_unreadable")


def read_state(http: Any, repo: str, sigstore: Sequence[str],
               verifier: Callable[[list[str]], int] = run_verifier) -> dict:
    """D1's read of the bootstrap state: listed, chosen, downloaded, unpacked, verified (the rules above)."""
    entry = choose(list_artifacts(http, repo))
    url = http.redirect("/repos/%s/actions/artifacts/%d/zip" % (repo_name(repo), entry["id"]))
    result, bundle = unpack(http.blob(url, 4 * MAX_FILE))
    return dict(open_state(result, bundle, repo, sigstore, verifier), artifact_id=entry["id"])


# ---- the import -------------------------------------------------------------------------------------------------

def last_import(data: bytes) -> tuple[dict, bytes]:
    """The last transfer row of ``setup/imports.jsonl`` and its line's bytes (without the LF), by the rules above."""
    if not C.verify_bytes(data)["valid"]:
        raise StateError("imports_broken")
    rows = [(C.parse_row(line.decode("utf-8")), line) for line in C._lines(data)]  # objects: verify_bytes's rule
    transfers = [(row, line) for row, line in rows if "referee_tree_sha256" in row]
    if not transfers:
        raise StateError("imports_no_transfer")
    row, line = transfers[-1]
    if not (isinstance(row["referee_tree_sha256"], str) and HEX64.fullmatch(row["referee_tree_sha256"])):
        raise StateError("imports_invalid")
    return row, line


def check_tree(source: Any, commit: str, imported: dict) -> str:
    """The accepted commit's ``referee/`` hash, which must equal the last import's (the rules above)."""
    try:
        got = T.of_commit(source, commit)
    except T.TreeHashError as exc:
        raise StateError("referee_tree_refused", exc.reasons) from None
    except PulledError as exc:
        raise StateError("referee_tree_refused", ["brain:%s" % r for r in exc.reasons]) from None
    if got != imported["referee_tree_sha256"]:
        raise StateError("referee_tree_mismatch")
    return got
