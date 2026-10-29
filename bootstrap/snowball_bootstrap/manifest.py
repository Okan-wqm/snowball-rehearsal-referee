"""The founder's test manifest (`snowball-tests.json`, `tohum/26b`) and its lock files.

The bootstrap runs only the commands listed here, and refuses a manifest that leaves a finished
micro-feature without its self-test (`asama-0/14`) or that lists no test at all.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import PurePosixPath

# Stage 0 micro-feature -> self-test numbers, copied from asama-0/14 (seed 2.2).
STAGE0_MF_TESTS: dict[int, tuple[int, ...]] = {
    1: (13,), 2: (30,), 3: (26,), 4: (31,), 5: (19,), 6: (8,), 7: (2, 4), 8: (27,),
    9: (1, 6, 7, 12, 14, 28), 10: (32,), 11: (9, 11), 12: (33,), 13: (20, 21), 14: (34,),
    15: (23,), 16: (35,), 17: (36,), 18: (25,), 19: (24,), 20: (37,), 21: (38,), 22: (22,),
    23: (39,), 24: (40,), 25: (41,), 26: (42,), 27: (43,), 28: (29,), 29: (44,), 30: (45,),
}
STAGE0_MF_COUNT = len(STAGE0_MF_TESTS)
TEST_ID_RE = re.compile(r"^T([1-9][0-9]{0,2})\Z")
MAX_CMD = 2000
MAX_TESTS = 200
MAX_LOCKFILES = 10
REQ_LINE_RE = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)==([A-Za-z0-9._+!-]+)\Z")
HASH_TOKEN_RE = re.compile(r"^--hash=sha256:[0-9a-f]{64}\Z")


MAX_STAGE = 1000  # stages and micro-features are small numbers; anything larger is a mistake or a probe


def _text(value: str) -> bool:
    """True when the string can be written as UTF-8 (a lone surrogate cannot, nor be signed)."""
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


class ManifestError(ValueError):
    """The manifest or a lock file is unusable; the message is the rejection detail."""


@dataclass(frozen=True)
class TestEntry:
    id: str
    cmd: str
    stage: int


@dataclass(frozen=True)
class Manifest:
    tests: tuple[TestEntry, ...]
    done_mf: tuple[int, ...]
    lockfiles: tuple[str, ...]

    def stage_tests(self, stage: int) -> list[TestEntry]:
        return [t for t in self.tests if t.stage == stage]


def _safe_relpath(value: object) -> str:
    if not isinstance(value, str) or not value or not _text(value):
        raise ManifestError("lock file path must be a non-empty string")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or "\\" in value:
        raise ManifestError(f"lock file path {value!r} must be relative and inside the repository")
    return str(path)


def parse_manifest(text: str) -> Manifest:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ManifestError(f"snowball-tests.json is not valid JSON: {exc}") from exc
    except RecursionError as exc:
        raise ManifestError("snowball-tests.json is nested too deeply") from exc
    if not isinstance(data, dict) or set(data) != {"tests", "done_mf", "lockfiles"}:
        raise ManifestError("snowball-tests.json must have exactly: tests, done_mf, lockfiles")
    raw_tests, raw_done, raw_locks = data["tests"], data["done_mf"], data["lockfiles"]
    if not isinstance(raw_tests, list) or not isinstance(raw_done, list) or not isinstance(raw_locks, list):
        raise ManifestError("tests, done_mf and lockfiles must be arrays")
    if len(raw_tests) > MAX_TESTS:
        raise ManifestError(f"more than {MAX_TESTS} tests")
    tests: list[TestEntry] = []
    seen: set[str] = set()
    for item in raw_tests:
        if not isinstance(item, dict) or set(item) != {"id", "cmd", "stage"}:
            raise ManifestError("each test must have exactly: id, cmd, stage")
        tid, cmd, stage = item["id"], item["cmd"], item["stage"]
        if not isinstance(tid, str) or not TEST_ID_RE.match(tid):
            raise ManifestError(f"test id {tid!r} must look like T13")
        if tid in seen:
            raise ManifestError(f"duplicate test id {tid}")
        seen.add(tid)
        if not isinstance(cmd, str) or not cmd.strip() or len(cmd) > MAX_CMD or "\x00" in cmd or not _text(cmd):
            raise ManifestError(f"{tid}: cmd must be a non-empty string up to {MAX_CMD} characters")
        if not isinstance(stage, int) or isinstance(stage, bool) or not 0 <= stage <= MAX_STAGE:
            raise ManifestError(f"{tid}: stage must be an integer from 0 to {MAX_STAGE}")
        tests.append(TestEntry(tid, cmd, stage))
    done: list[int] = []
    for mf in raw_done:
        if not isinstance(mf, int) or isinstance(mf, bool) or not 0 < mf <= MAX_STAGE:
            raise ManifestError(f"done_mf entries must be integers from 1 to {MAX_STAGE}")
        done.append(mf)
    if len(raw_locks) > MAX_LOCKFILES:
        raise ManifestError(f"more than {MAX_LOCKFILES} lock files")
    locks = tuple(_safe_relpath(p) for p in raw_locks)
    return Manifest(tuple(tests), tuple(done), locks)


def check_stage0(manifest: Manifest) -> list[str]:
    """Reasons the manifest cannot be accepted for Stage 0; empty when it can."""
    reasons: list[str] = []
    stage0 = manifest.stage_tests(0)
    if not stage0:
        reasons.append("zero_tests")
    done = list(manifest.done_mf)
    if done != list(range(1, len(done) + 1)) or len(done) > STAGE0_MF_COUNT:
        reasons.append("done_mf_not_in_order")
        return reasons
    present = {int(TEST_ID_RE.match(t.id).group(1)) for t in stage0}  # type: ignore[union-attr]
    for mf in done:
        for number in STAGE0_MF_TESTS[mf]:
            if number not in present:
                reasons.append(f"missing_test:MF{mf}:T{number}")
    return reasons


@dataclass(frozen=True)
class Requirement:
    name: str
    version: str
    hashes: tuple[str, ...]


def parse_lockfile(text: str) -> list[Requirement]:
    """Accept only ``name==version --hash=sha256:...`` requirements; no options, URLs or markers."""
    logical: list[str] = []
    pending = ""
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].rstrip() if not raw.lstrip().startswith("--hash") else raw.rstrip()
        if line.endswith("\\"):
            pending += line[:-1] + " "
            continue
        pending += line
        if pending.strip():
            logical.append(pending.strip())
        pending = ""
    if pending.strip():
        logical.append(pending.strip())
    reqs: list[Requirement] = []
    for line in logical:
        tokens = line.split()
        match = REQ_LINE_RE.match(tokens[0])
        if not match:
            raise ManifestError(f"lock file entry is not 'name==version': {line[:80]}")
        hashes = []
        for token in tokens[1:]:
            if not HASH_TOKEN_RE.match(token):
                raise ManifestError(f"only --hash=sha256:<hex> may follow a requirement: {token[:80]}")
            hashes.append(token.split(":", 1)[1])
        if not hashes:
            raise ManifestError(f"{tokens[0]} has no --hash")
        reqs.append(Requirement(match.group(1), match.group(2), tuple(hashes)))
    return reqs
