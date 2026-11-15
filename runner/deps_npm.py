"""``deps.fetch`` for npm: the lock is checked, every tarball is fetched and verified against the lock's
``integrity``, and the result is one content-addressed artifact with a license report (stage 0, MF5).

Rules: asama-0/06 (each tarball verified by ``integrity``; ``resolved`` on an allowed registry; git and
file dependencies refused; content-addressed output that every run takes by its hash; a package that
needs an install script is marked in the recipe), asama-0/09 test 34, tohum/24 and 26a (license report
written; the gate applies only to dependencies that enter the product), tohum/08 4 (scripts off: this
module never installs or runs anything), tohum/18a (``operating.deps_bytes``, ``license_allowlist``,
``license_exceptions``), tohum/29d (group ``npmlock``).

The lock (``check``, before anything is fetched; every reason listed as ``<reason>:<key>``):

- It must be a JSON object with ``lockfileVersion`` the integer 2 or 3 (not ``3.0``, not ``true``) and a
  ``packages`` object
  (``lock_unparsable``, ``lock_version_unsupported``). The ``dependencies`` section of a version 2 lock is
  not read; an installer that reads it (npm 6) is out of scope.
- The root entry ``""`` is skipped: the target's own package and its scripts are the target's code, run
  in ``koş``, not judged here. npm workspaces (tohum/29g, ``workspaces``): a workspace link and the workspace
  folder it names are skipped too, for the same reason (the folder is the target's own code, its scripts
  included); the live path takes only a link whose key is a package key below and whose ``resolved`` is a
  folder written plainly (``live_workspaces``); any other link is an entry and is refused below. Every other
  key must be a chain of ``node_modules/<name>`` segments with npm name characters, at the top or below a
  taken workspace folder (``<folder>/node_modules/...``, ``key_name``), else ``key_not_allowed``; so a key
  outside ``node_modules`` that no link names (``packages/a``) is refused.
- ``link: true``, a ``resolved`` or ``version`` that starts with ``file:``, or a non-empty ``resolved`` with
  no ``://`` is a file
  dependency (``file_dependency``); one that starts with ``git+``, ``git:``, ``git@``, ``github:``,
  ``gitlab:``, ``bitbucket:`` or ``gist:`` (casefolded) is a git dependency (``git_dependency``); a bundled
  entry (``inBundle: true``) is refused (``bundled_dependency``): its bytes come inside another tarball
  and are not judged on their own here.
- Otherwise ``resolved`` must be exactly ``https://<host><prefix><name>/-/<bare>-<version>.tgz`` for an
  allowed registry (scheme ``https``; a host of ``[A-Za-z0-9.-]`` as written, so no user, port or a character
  that only lowercases into ASCII such as the Kelvin sign, equal to the registry's after lowercasing; no query
  or fragment; path characters ``[A-Za-z0-9._~@/-]`` only, so no ``%``-escapes and no version ``+build``);
  ``<name>`` is the entry's
  ``name`` (an alias) or the last name of its key, ``<bare>`` its part after ``/``, ``<version>`` the
  entry's semver ``version``. A missing one is ``resolved_missing``, any other ``resolved_not_allowed``,
  a bad version ``version_invalid``. Allowed registries: ``--registry`` (repeatable; the profile's
  ``registry_egress``), default ``https://registry.npmjs.org/``.
- ``integrity`` is a space-separated SRI list: each token ``sha256-``, ``sha384-`` or ``sha512-`` plus
  strict base64 of the digest's length, or ``sha1-`` which is ignored as weak; any other token is
  ``integrity_malformed``. No strong token is ``integrity_weak``; none at all ``integrity_missing``.
- ``hasInstallScript: true`` needs the package marked in the recipe's ``install_scripts_required``
  (``install_script_not_marked``). A mark is a key of this lock's ``packages`` other than ``""`` or exactly
  ``name@version`` (an npm name, a semver version; one the lock does not hold marks nothing); any other
  element (a bare name, a path the lock does not hold, ``""``, a range or tag) is ``mark_not_usable:<element>``
  here and unusable input (exit 2) for ``store`` and ``fetch`` (tohum/26c; class ``Marks``).

The artifact fetch (``store``), only when the lock passes: each distinct ``resolved`` is fetched once and every
strong ``integrity`` token must equal the bytes' digest (``integrity_mismatch``; one changed byte is
caught). A tarball that matches is read in memory, never extracted: it must be gzip tar
(``tarball_unreadable``) with exactly one regular member ``<top>/package.json`` (``tarball_no_package_json``,
``tarball_ambiguous_package_json``; at most 1 MiB, a JSON object, else ``tarball_package_json_unreadable``)
whose ``name`` and ``version`` equal the lock's (``tarball_manifest_mismatch``), and no member under
``<top>/node_modules/`` (``bundled_dependency``, as for a bundled lock entry). A ``preinstall``,
``install`` or ``postinstall`` key in its ``scripts``, or a ``<top>/binding.gyp`` member (npm's implicit
``node-gyp rebuild``), needs the same recipe mark as ``hasInstallScript``. The tarball's decompression
time is bounded only by the job's wall clock. ``operating.deps_bytes`` (from ``--policy``) bounds the
total bytes of distinct tarballs, or ``cap`` when it is smaller (a recipe's ``limits.deps_bytes``, which may only
tighten the operator's value); going over it stops the fetch with ``limit_hit:deps_bytes``.

Licenses: every place in the tarball's ``package.json`` that states one (``license`` as a string or an
object's ``type``; each entry of ``licenses``) is listed in the report; license files are not read, and a
value of another type is listed as ``<unreadable>``. ``license_exceptions["name==version"].expression``
replaces the listed values. Without ``--product`` the report is written and nothing is gated (the
target's dependencies do not enter the product). With ``--product`` a package with no value is
``license_not_found`` and one with a value that is not allowed is ``license_not_allowed``. A value is
allowed when it is an SPDX expression of identifiers joined by ``AND``/``OR`` with parentheses and every
identifier is ASCII ``[A-Za-z0-9.+-]`` and in ``license_allowlist`` after lowercasing (operators are
case-sensitive; ``--policy`` replaces the 18a list), in at most 512 words and 64 ``(``: ``OR`` does not
let a listed identifier carry an unlisted one, ``+`` is allowed only as part of a listed identifier
(``GPL-2.0+``), and ``WITH`` never is (not as an operator, not as a listed word), so ``X WITH Y`` is not
allowed even through ``license_exceptions``, whose expression is judged by the same rule.

The artifact, written by ``store`` only when nothing is refused: ``OUT/<address>/`` holding the lock under
its own name (``package-lock.json`` or ``npm-shrinkwrap.json``), ``tarballs/<sha512 hex>.tgz`` and
``manifest.json``, the canonical JSON (sorted keys, no spaces, ASCII) of the lock's sha256 and, per key,
name, version, resolved, integrity, sha512, bytes, the listed licenses and the install-script flag.
``address`` is the sha256 of ``manifest.json``'s bytes, so the same lock and tarballs give the same
address and a changed lock byte gives another. ``verify`` takes it by that hash: the manifest bytes must
hash to the address, each tarball must be a regular file with its sha512 and must match its
``integrity``, the lock copy must hash to ``lock_sha256``, and no other file may be there
(``unexpected_file``). ``store`` also prints the ``npmlock`` ``artefact`` of the same packages (below).
A job that hands the artifact on uploads ``OUT`` and the next job downloads it whole: ``artifact_in`` takes the
one ``<address>/`` directory under the downloaded root (exactly one entry, a directory named 64 lowercase hex),
so the downloader passes ``verify`` the directory whose name is the address (``loop.job``'s ``getir`` and ``kos``).

Fetching: ``--mirror DIR`` reads ``DIR/<host>/<path>`` (the referee's fixtures and tests); without it
the tarball is fetched over HTTPS with redirects refused and the read capped. The HTTPS path is not
exercised by the tests here (no network in the sandbox); its proof is asama-0/10a #getir. A tarball that
cannot be fetched is no verdict (exit 2), not a refusal: an outage says nothing about the lock.

Group ``npmlock`` (tohum/29g, the vector interface; ``fetch``, a report, nothing written): stdin
``{registry_egress[], install_scripts_required[]}``, each registry ``https://<host>/...`` ending with ``/``,
each element a mark as above (a lock key of this lock or ``name@version``; any other element is exit 2). The lock must be ``lockfileVersion`` 3 with a ``packages`` object of objects.
The entries other than ``""``, a workspace link and the workspace folder it names (``workspaces``, compared as
written) are packages, a nested ``<folder>/node_modules/<name>``, any other link, a key outside ``node_modules``
that no link names and an entry without ``resolved`` included; each gets the first of these reasons that holds,
in this order:

- ``git_dependency``: ``resolved`` starts with ``git+``, ``git:``, ``github:`` or ``git@`` (as written);
- ``file_dependency``: ``resolved`` starts with ``file:``, or ``link`` is true and the target (``resolved``)
  is absolute (``/``, ``\\`` or a drive letter) or contains ``..``;
- ``registry_not_allowed``: ``resolved`` is missing or does not start with a ``registry_egress`` entry
  (a plain string prefix over the whole URL, ``/`` included); so an in-tree link and a bundled entry are
  refused here, nothing of theirs being fetched;
- ``tarball_missing``: no regular file ``MIRROR/<host>/<path>`` for ``https://<host>/<path>`` (taken
  literally; an empty, ``.`` or ``..`` segment cannot be in the mirror);
- ``integrity_mismatch``: the lock's ``integrity`` has no ``sha512-`` token, or one differs from
  ``sha512-`` + base64 of the sha512 of the raw ``.tgz`` bytes (other tokens are not read);
- ``install_script_unmarked``: ``package/package.json`` has ``preinstall``, ``install`` or ``postinstall``
  in ``scripts``, or ``package/binding.gyp`` exists, or the lock entry has ``hasInstallScript: true``; and
  neither the lock path nor the tarball's ``name@version`` is in ``install_scripts_required``.

The tarball is read in memory. Out: ``{ok, rejected, artefact, licenses}``; ``rejected`` the sorted
``<reason>:<lock path>``; ``artefact`` ``sha256:`` + the hex sha256 of the canonical JSON (RFC 8785 for
strings: sorted keys, no spaces, UTF-8) of ``[{integrity, path}]`` sorted by path, ``integrity`` as the
lock writes it, so a lock written another way gives the same address; ``licenses`` sorted by path
``{path, name, version, license}`` from ``package/package.json`` (each ``null`` unless a string; a report,
no gate). With a refusal ``artefact`` and ``licenses`` are ``null``. Exit 2 (nothing fetched): a lock or
stdin that is not as above (an element of ``install_scripts_required`` that is not a mark included), a
mirror that is not a readable directory, a mirror file that cannot be read, and a tarball that passes
``integrity`` but is not gzip tar with exactly one ``package/package.json`` JSON object.

Command line, run from ``referee/`` (one JSON line on stdout; exit 0 fine, 1 refused, 2 no verdict). Exit
1 comes only from a report with ``ok`` false; every other failure is exit 2 with an ``{ok: false, error}`` line:
unusable input (a missing or non-JSON lock, recipe or policy, JSON nested too deeply, a value of the
wrong shape, a lock file not named as above, a fetch that failed, an existing artifact directory that
does not verify); any other exception is exit 2 at ``cli.run``'s boundary (``FAULT_LINE``, the type alone on
stderr). Out of scope:
signals and the interpreter being killed.

    python -m runner.deps_npm fetch LOCK MIRROR < {"registry_egress": [...], "install_scripts_required": [...]}
    python -m runner.deps_npm check LOCK [--registry URL]... [--recipe FILE]
    python -m runner.deps_npm store LOCK OUT [--mirror DIR] [--registry URL]... [--recipe FILE]
                                             [--policy FILE] [--product]
    python -m runner.deps_npm verify ARTIFACT_DIR [--address HEX]
    python -m runner.deps_npm platform LOCK --os OS --cpu CPU [--libc LIBC]

``--recipe`` is a unit recipe (tohum/26c) whose ``install_scripts_required`` is read; ``--policy`` a
``policy.json``.

``platform`` (``platform_report``; nothing fetched, no tarball read) says what the verifier's install does
with each package of the lock on a platform named with node's words (``linux``, ``x64``, ``glibc``): which
rows are not unpacked, on which of those npm's own install would have failed, and what becomes of the rows with
``hasInstallScript``. The rule is ``platform_plan``'s; what it leaves out of npm's rule is written there. Exit 0
unless the lock has a structure reason (1) or the input is unusable (2). A fetch still fetches and checks every
package (tohum/29g): the artifact is the lock's, not a platform's.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import io
import json
import os
import re
import shutil
import stat
import sys
import tarfile
import tempfile
import urllib.parse
import urllib.request
from typing import Any, Callable

import cli

DEFAULT_REGISTRIES = ("https://registry.npmjs.org/",)
LICENSE_ALLOWLIST = ("MIT", "MIT-0", "BSD-2-Clause", "BSD-3-Clause", "0BSD", "Apache-2.0", "ISC", "PSF-2.0",
                     "Python-2.0", "Unlicense", "CC0-1.0", "Zlib", "MPL-2.0")
LOCK_NAMES = ("package-lock.json", "npm-shrinkwrap.json")
GIT_PREFIXES = ("git+", "git:", "git@", "github:", "gitlab:", "bitbucket:", "gist:")
INSTALL_SCRIPTS = ("preinstall", "install", "postinstall")
STRONG = {"sha256": 32, "sha384": 48, "sha512": 64}
PACKAGE_JSON_MAX = 1 << 20
SCHEMA = "snowball-deps-npm/1"

_SEG = r"[A-Za-z0-9~-][A-Za-z0-9._~-]*"
_NAME = r"(?:@%s/)?%s" % (_SEG, _SEG)
NAME_RE = re.compile(_NAME)
LOCK_PATH_RE = re.compile(r"(?:node_modules/%s/)*node_modules/(%s)" % (_NAME, _NAME))
VERSION_RE = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?")
PATH_CHARS = re.compile(r"[A-Za-z0-9._~@/-]*")
HOST_RE = re.compile(r"[A-Za-z0-9.-]+")
LICENSE_ID = re.compile(r"[A-Za-z0-9.+-]+")
B64_RE = re.compile(r"[A-Za-z0-9+/]+={0,2}")


class DepsError(ValueError):
    """Unusable input or a failed fetch: no verdict (exit 2)."""


def canonical(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")


# ---------------------------------------------------------------- lock

def _registries(urls) -> list[tuple[str, str]]:
    out = []
    for url in urls:
        if not isinstance(url, str):
            raise DepsError("registry is not a string")
        parts = urllib.parse.urlsplit(url)
        if (parts.scheme != "https" or not HOST_RE.fullmatch(parts.netloc) or parts.query or parts.fragment
                or not PATH_CHARS.fullmatch(parts.path) or ".." in parts.path.split("/")):
            raise DepsError("registry not usable: %r" % url)
        prefix = parts.path if parts.path.endswith("/") else parts.path + "/"
        out.append((parts.netloc.lower(), prefix))
    return out


def parse_integrity(value: Any) -> tuple[str | None, list[tuple[str, bytes]]]:
    """``(reason or None, strong (algorithm, digest) pairs)``."""
    if not isinstance(value, str) or not value.strip():
        return "integrity_missing", []
    strong = []
    for word in value.split():
        alg, sep, b64 = word.partition("-")
        if not B64_RE.fullmatch(b64):
            return "integrity_malformed", []
        if alg == "sha1":
            continue
        if alg not in STRONG:
            return "integrity_malformed", []
        try:
            digest = base64.b64decode(b64, validate=True)
        except (binascii.Error, ValueError):
            return "integrity_malformed", []
        if len(digest) != STRONG[alg]:
            return "integrity_malformed", []
        strong.append((alg, digest))
    if not strong:
        return "integrity_weak", []
    return None, strong


class Marks:
    """``install_scripts_required`` read against one lock (tohum/26c, 29g).

    An element is a mark when it is a key of the lock's ``packages`` other than the root ``""`` (it marks that
    entry) or ``name@version`` with an npm name (scoped or not, as in a lock key) and a semver version (it marks
    the package of that name and version; one the lock does not hold marks nothing). Every other element (a
    bare name, scoped or not; a path the lock does not hold; ``""``; a range or tag after ``@``) is not a mark
    and lands in ``bad``, in the request's order: it would otherwise be ignored or mark every version.
    """

    def __init__(self, marks: list[str], keys) -> None:
        keys = {k for k in keys if k != ""}
        self.keys, self.versions, self.bad = set(), set(), []
        for mark in marks:
            name, at, version = mark.rpartition("@")
            if mark in keys:
                self.keys.add(mark)
            elif at and NAME_RE.fullmatch(name) and VERSION_RE.fullmatch(version):
                self.versions.add(mark)
            else:
                self.bad.append(mark)

    def require(self) -> None:
        if self.bad:
            raise DepsError("install_scripts_required: not a lock key or name@version: %s"
                            % ", ".join(json.dumps(m) for m in self.bad))

    def marked(self, key: str, name: Any, version: Any) -> bool:
        return key in self.keys or (isinstance(name, str) and isinstance(version, str)
                                    and "%s@%s" % (name, version) in self.versions)


def read_marks(marks: list[str], keys) -> Marks:
    """``Marks`` of a request that must be usable: an element that is not a mark is unusable input (exit 2)."""
    found = Marks(marks, keys)
    found.require()
    return found


def _in_repo(resolved: Any) -> bool:
    """A link target inside the repository (tohum/29g): a non-empty string, not absolute (``/``, ``\\``), with no
    ``..`` component (split on ``/`` and ``\\``) and no ``:`` (so no drive letter, no ``file:``, no URL)."""
    return (isinstance(resolved, str) and resolved != "" and not resolved.startswith(("/", "\\"))
            and ":" not in resolved and ".." not in re.split(r"[/\\]", resolved))


def workspaces(packages: Any) -> tuple[dict[str, str], set[str]]:
    """npm workspaces in a lock's ``packages`` (tohum/29g), the one reading of which entries are no packages:
    ``(links, folders)``. A workspace link is an entry other than ``""`` with ``link: true`` whose ``resolved`` is
    in the repository (``_in_repo``); ``links`` maps its key to that ``resolved``. A workspace folder is a key
    equal to some link's ``resolved``, compared as written, with no ``node_modules`` component; ``folders`` holds
    the ``resolved`` values of that shape whether or not the lock has them as keys. Every other entry is a
    package: a key outside ``node_modules`` that no link names is not a folder."""
    links = {}
    for key, entry in packages.items() if isinstance(packages, dict) else ():
        if key != "" and isinstance(entry, dict) and entry.get("link") is True and _in_repo(entry.get("resolved")):
            links[key] = entry["resolved"]
    folders = {f for f in links.values() if "node_modules" not in f.split("/")}
    return links, folders


def key_name(key: str, folders: set[str]) -> str | None:
    """The package name a lock key installs, or None when the live path does not take the key: a chain of
    ``node_modules/<name>`` segments (``LOCK_PATH_RE``), at the top or below a workspace folder (``<folder>/``
    before the first ``node_modules`` component; the folder's components non-empty and not ``.``)."""
    parts = key.split("/")
    if "node_modules" not in parts:
        return None
    cut = parts.index("node_modules")
    prefix = parts[:cut]
    if prefix and ("/".join(prefix) not in folders or any(p in ("", ".") for p in prefix)):
        return None
    m = LOCK_PATH_RE.fullmatch("/".join(parts[cut:]))
    return m.group(1) if m else None


def _source_reason(entry: dict) -> str | None:
    if entry.get("link") is True:
        return "file_dependency"
    if entry.get("inBundle") is True:
        return "bundled_dependency"
    for field in ("resolved", "version"):
        value = entry.get(field)
        if not isinstance(value, str):
            continue
        low = value.casefold()
        if low.startswith(GIT_PREFIXES):
            return "git_dependency"
        if low.startswith("file:") or (field == "resolved" and value and "://" not in value):
            return "file_dependency"
    return None


def _resolved_reason(entry: dict, name: str, registries: list[tuple[str, str]]) -> str | None:
    resolved = entry.get("resolved")
    if not isinstance(resolved, str) or not resolved:
        return "resolved_missing"
    version = entry["version"]
    parts = urllib.parse.urlsplit(resolved)
    if (parts.scheme != "https" or "?" in resolved or "#" in resolved or not HOST_RE.fullmatch(parts.netloc)
            or not PATH_CHARS.fullmatch(parts.path)):
        return "resolved_not_allowed"
    bare = name.split("/")[-1]
    for host, prefix in registries:
        if parts.netloc.lower() == host and parts.path == "%s%s/-/%s-%s.tgz" % (prefix, name, bare, version):
            return None
    return "resolved_not_allowed"


def entries(lock: Any) -> tuple[list[str], list[dict]]:
    """Lock structure: ``(reasons, [{key, name, version, resolved, integrity, strong, entry}])``."""
    if not isinstance(lock, dict):
        return ["lock_unparsable"], []
    if type(lock.get("lockfileVersion")) is not int or lock["lockfileVersion"] not in (2, 3):
        return ["lock_version_unsupported"], []
    packages = lock.get("packages")
    if not isinstance(packages, dict):
        return ["lock_version_unsupported"], []
    reasons, out = [], []
    links, folders = live_workspaces(packages)
    for key in sorted(packages):
        entry = packages[key]
        if key == "" or key in links or key in folders:
            continue
        found = key_name(key, folders)
        if found is None or not isinstance(entry, dict):
            reasons.append("key_not_allowed:%s" % key)
            continue
        name = entry.get("name", found)
        if not isinstance(name, str) or not NAME_RE.fullmatch(name):
            reasons.append("key_not_allowed:%s" % key)
            continue
        out.append({"key": key, "name": name, "entry": entry})
    return reasons, out


def live_workspaces(packages: Any) -> tuple[dict[str, str], set[str]]:
    """The workspaces the live path takes: ``workspaces``' links whose key is a package key (``key_name``, so the
    staged symlink lands in a ``node_modules`` directory) and whose ``resolved`` is a workspace folder (so it names
    a directory of the repository, not a package path) written plainly (no empty or ``.`` component, so never the
    lock's own directory); the folders those links name. Any other link stays an
    entry and is refused as before (``file_dependency``, ``key_not_allowed``)."""
    links, folders = workspaces(packages)
    taken = {k: f for k, f in links.items() if f in folders and key_name(k, folders) is not None
             and not any(p in ("", ".") for p in f.split("/"))}
    return taken, set(taken.values())


PLATFORM_FIELDS = ("os", "cpu", "libc")


def js_true(value: Any) -> bool:
    """Whether JavaScript holds a JSON value true (``!!value``): everything but ``null``, ``false``, the number
    zero and the empty string; an empty list or object is true there. npm reads a lock entry's ``optional``
    and tests the presence of its ``os``, ``cpu`` and ``libc`` this way."""
    return not (value is None or value == "" or (isinstance(value, (int, float)) and value == 0))


def _platform_list(value: Any, wanted: Any) -> bool:
    """npm's ``checkList`` (npm-install-checks) over a ``wanted`` JavaScript holds true: a string is a list of
    one; ``["any"]`` alone admits everything; an entry ``!x`` excludes ``x``; otherwise some entry without ``!``
    equals ``value``, or every entry is a negation. Any other shape (a number, ``true``, an object, a list
    holding something that is not a string) admits nothing: npm's check throws on it or says no before it
    throws, which drops an optional package and fails the install for any other, the same outcome as an
    exclusion. One object is admitted, because npm's test for ``["any"]`` reads ``length`` and ``0`` and holds
    for it: one whose ``length`` is the number 1 and whose ``"0"`` is ``"any"``."""
    if isinstance(wanted, str):
        wanted = [wanted]
    if isinstance(wanted, dict):
        length = wanted.get("length")
        return not isinstance(length, bool) and length == 1 and wanted.get("0") == "any"
    if not isinstance(wanted, list) or not all(isinstance(w, str) for w in wanted):
        return False
    if wanted == ["any"]:
        return True
    if any(w.startswith("!") and w[1:] == value for w in wanted):
        return False
    return any(w == value for w in wanted if not w.startswith("!")) or all(w.startswith("!") for w in wanted)


def platform_admits(entry: Any, platform: dict) -> bool:
    """Whether npm installs a lock entry on ``platform`` (``{os, cpu, libc}``, node's names: ``linux``, ``x64``,
    ``glibc``; ``libc`` None when not known): npm-install-checks' ``checkPlatform`` over the entry's ``os``,
    ``cpu`` and ``libc``. A field the entry lacks, or holds with a value JavaScript holds false (``js_true``),
    admits; an entry with a ``libc`` that is read on a platform whose libc is not known is excluded, as npm
    excludes it. ``engines`` is not read (see ``platform_plan``)."""
    if not isinstance(entry, dict):
        return True
    for field in PLATFORM_FIELDS:
        if js_true(entry.get(field)) and (platform.get(field) is None
                                          or not _platform_list(platform[field], entry[field])):
            return False
    return True


def platform_plan(packages: Any, keys, platform: dict) -> dict:
    """Which of the lock rows ``keys`` are unpacked on ``platform``, each list sorted: ``installed``;
    ``not_installed`` (a row whose ``os``, ``cpu`` or ``libc`` exclude the platform, ``platform_admits``, and
    every row below such a row's directory, which goes with it); ``unsupported`` (the excluded rows among
    ``not_installed`` that are not optional and not below a row already left out: npm skips an excluded
    optional row without an error, and its install ends with EBADPLATFORM on any other; ``devOptional`` is
    not ``optional``, npm installs such a row when development dependencies are installed); ``optional`` (the installed optional rows: npm drops one
    whose install script fails and goes on). The one reading of these lock fields; the verifier
    (``profile.unit_verify``) installs by it. No list is a refusal (tohum/26c "Birim tarifi": a package that is
    not unpacked is no reason on any page; the recipe's measure is the runs): ``unsupported`` says where npm's
    own install would have stopped. A row is optional when its ``optional`` is a value JavaScript holds true
    (``js_true``; npm's ``!!optional``, arborist's load-virtual), which a lock npm wrote spells ``true``.

    Narrower than npm, each a row npm would not install and this plan installs: an optional row whose
    ``engines`` exclude the node or npm version (npm checks engines for optional rows as well); the rest of
    npm's "optional set" (a package that needs a missing row through a dependency that is not optional is
    removed by npm too, up to the first optional dependency). Both show as a package present here that npm
    would have left out, never the reverse."""
    packages = packages if isinstance(packages, dict) else {}
    plan: dict[str, list[str]] = {"installed": [], "not_installed": [], "unsupported": [], "optional": []}
    for key in sorted(keys):
        entry = packages.get(key)
        entry = entry if isinstance(entry, dict) else {}
        if any(key.startswith(gone + "/") for gone in plan["not_installed"]):
            plan["not_installed"].append(key)
        elif platform_admits(entry, platform):
            plan["installed"].append(key)
            if js_true(entry.get("optional")):
                plan["optional"].append(key)
        else:
            plan["not_installed"].append(key)
            if not js_true(entry.get("optional")):
                plan["unsupported"].append(key)
    return plan


def platform_report(lock: Any, platform: dict) -> dict:
    """The command line's report of ``platform_plan`` over every package of a lock (``entries``), with the rows
    whose lock entry says ``hasInstallScript: true`` sorted by what the verifier does with their script:
    ``required`` (run; the row stays as unpacked when its script fails), ``optional`` (run; the row can be
    dropped when its script fails: ``profile.unit_verify`` step 3 has the rule), ``not_installed`` (not run).
    ``ok`` is false when the lock has a structure reason, and only then. A tarball's own scripts are not read
    here (no tarball is); ``store`` reads them."""
    reasons, items = entries(lock)
    packages = lock.get("packages") if isinstance(lock, dict) else None
    plan = platform_plan(packages, [i["key"] for i in items], platform)
    scripted = {i["key"] for i in items if i["entry"].get("hasInstallScript") is True}
    optional = set(plan["optional"])
    report = {"ok": not reasons,
              "platform": {f: platform.get(f) for f in PLATFORM_FIELDS}, "packages": len(items),
              "installed": len(plan["installed"]), "not_installed": plan["not_installed"],
              "unsupported": plan["unsupported"],
              "scripts": {"required": [k for k in plan["installed"] if k in scripted and k not in optional],
                          "optional": [k for k in plan["installed"] if k in scripted and k in optional],
                          "not_installed": [k for k in plan["not_installed"] if k in scripted]}}
    if reasons:
        report["reasons"] = reasons
    return report


def check(lock: Any, registries=DEFAULT_REGISTRIES, marks: list[str] | None = None) -> dict:
    """The static check of the lock; nothing is fetched."""
    regs = _registries(registries)
    reasons, items = entries(lock)
    packages = lock.get("packages") if isinstance(lock, dict) else None
    found = Marks(list(marks or []), packages if isinstance(packages, dict) else ())
    if not isinstance(packages, dict):  # no lock to read the marks against: the lock's reason only
        return {"ok": False, "reasons": reasons, "items": items, "marks": found}
    reasons += ["mark_not_usable:%s" % m for m in found.bad]
    for item in items:
        key, entry = item["key"], item["entry"]
        source = _source_reason(entry)
        if source:
            reasons.append("%s:%s" % (source, key))
            continue
        version = entry.get("version")
        if not isinstance(version, str) or not VERSION_RE.fullmatch(version):
            reasons.append("version_invalid:%s" % key)
            continue
        resolved = _resolved_reason(entry, item["name"], regs)
        if resolved:
            reasons.append("%s:%s" % (resolved, key))
        bad, item["strong"] = parse_integrity(entry.get("integrity"))
        if bad:
            reasons.append("%s:%s" % (bad, key))
        if entry.get("hasInstallScript") is True and not found.marked(key, item["name"], version):
            reasons.append("install_script_not_marked:%s" % key)
    return {"ok": not reasons, "reasons": reasons, "items": items, "marks": found}


# ---------------------------------------------------------------- tarball

def integrity_matches(data: bytes, strong: list[tuple[str, bytes]]) -> bool:
    return bool(strong) and all(hashlib.new(alg, data).digest() == digest for alg, digest in strong)


def inspect_tarball(data: bytes) -> tuple[str | None, dict]:
    """``(reason or None, {manifest, binding_gyp})``, read in memory, nothing extracted."""
    found, gyp = [], False
    try:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
            for member in tar:
                parts = [p for p in member.name.split("/") if p not in ("", ".")]
                if len(parts) >= 2 and parts[1] == "node_modules":
                    return "bundled_dependency", {}
                if len(parts) != 2:
                    continue
                if parts[1] == "binding.gyp":
                    gyp = True
                if parts[1] == "package.json":
                    if not member.isfile():
                        return "tarball_no_package_json", {}
                    if member.size > PACKAGE_JSON_MAX:
                        return "tarball_package_json_unreadable", {}
                    fh = tar.extractfile(member)
                    found.append(fh.read(PACKAGE_JSON_MAX + 1) if fh else b"")
    except cli.ARCHIVE_ERRORS:  # read in memory: no OSError but gzip's, in the tuple (cli rule 9)
        return "tarball_unreadable", {}
    if not found:
        return "tarball_no_package_json", {}
    if len(found) > 1:
        return "tarball_ambiguous_package_json", {}
    try:
        manifest = cli.loads(found[0].decode("utf-8"))
    except ValueError:  # cli.TooDeep included
        return "tarball_package_json_unreadable", {}
    if not isinstance(manifest, dict):
        return "tarball_package_json_unreadable", {}
    return None, {"manifest": manifest, "binding_gyp": gyp}


def licenses_of(manifest: dict) -> list[str]:
    out = []
    lic = manifest.get("license")
    if lic is not None:
        if isinstance(lic, str):
            out.append(lic)
        elif isinstance(lic, dict) and isinstance(lic.get("type"), str):
            out.append(lic["type"])
        else:
            out.append("<unreadable>")
    lics = manifest.get("licenses")
    if lics is not None:
        if not isinstance(lics, list):
            out.append("<unreadable>")
        for one in lics if isinstance(lics, list) else []:
            if isinstance(one, str):
                out.append(one)
            elif isinstance(one, dict) and isinstance(one.get("type"), str):
                out.append(one["type"])
            else:
                out.append("<unreadable>")
    return out


def expression_allowed(expr: str, allowlist) -> bool:
    allowed = {a.lower() for a in allowlist}
    words = re.findall(r"\(|\)|[^\s()]+", expr)
    pos = 0

    def term() -> bool:
        nonlocal pos
        if pos >= len(words):
            return False
        word = words[pos]
        pos += 1
        if word == "(":
            if not expression() or pos >= len(words) or words[pos] != ")":
                return False
            pos += 1
            return True
        return (word not in ("AND", "OR", "WITH") and LICENSE_ID.fullmatch(word) is not None
                and word.lower() in allowed)

    def expression() -> bool:
        nonlocal pos
        if not term():
            return False
        while pos < len(words) and words[pos] in ("AND", "OR"):
            pos += 1
            if not term():
                return False
        return True

    if len(words) > 512 or words.count("(") > 64:
        return False
    return expression() and pos == len(words)


def licenses_allowed(values: list[str], allowlist) -> bool:
    return bool(values) and all(expression_allowed(v, allowlist) for v in values)


# ---------------------------------------------------------------- fetch

def mirror_fetcher(root: str) -> Callable[[str, int | None], bytes]:
    def fetch(url: str, cap: int | None) -> bytes:
        parts = urllib.parse.urlsplit(url)
        path = os.path.join(root, parts.netloc.lower(), *[p for p in parts.path.split("/") if p])
        try:
            with open(path, "rb") as fh:
                return fh.read() if cap is None else fh.read(cap + 1)
        except OSError as exc:
            raise DepsError("fetch failed: %s: %s" % (url, cli.cause(exc))) from None
    return fetch


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise DepsError("fetch failed: %s: redirect refused" % req.full_url)


def https_fetcher(url: str, cap: int | None) -> bytes:  # pragma: no cover - needs the network (10a #getir)
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        with opener.open(url, timeout=60) as resp:
            if resp.status != 200:
                raise DepsError("fetch failed: %s: HTTP %s" % (url, resp.status))
            return resp.read() if cap is None else resp.read(cap + 1)
    except OSError as exc:
        raise DepsError("fetch failed: %s: %s" % (url, cli.cause(exc))) from None


def _policy_values(policy: Any) -> tuple[list[str], dict, int | None]:
    if policy is None:
        return list(LICENSE_ALLOWLIST), {}, None
    if not isinstance(policy, dict):
        raise DepsError("policy is not an object")
    const = policy.get("constitutional", {})
    operating = policy.get("operating", {})
    if not isinstance(const, dict) or not isinstance(operating, dict):
        raise DepsError("policy constitutional or operating is not an object")
    allow = const.get("license_allowlist", list(LICENSE_ALLOWLIST))
    if not isinstance(allow, list) or not all(isinstance(a, str) for a in allow):
        raise DepsError("license_allowlist is not a list of strings")
    exceptions = const.get("license_exceptions", {})
    if not isinstance(exceptions, dict) or not all(
            isinstance(v, dict) and isinstance(v.get("expression"), str) for v in exceptions.values()):
        raise DepsError("license_exceptions is not {name==version: {expression, evidence}}")
    limit = None
    if "deps_bytes" in operating:
        value = operating["deps_bytes"].get("value") if isinstance(operating["deps_bytes"], dict) else None
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise DepsError("operating.deps_bytes.value is not a non-negative integer")
        limit = value
    return allow, exceptions, limit


def fetch(lock_path: str, out: str, fetcher: Callable[[str, int | None], bytes], registries=DEFAULT_REGISTRIES,
          marks: list[str] | None = None, policy: Any = None, product: bool = False, cap: int | None = None) -> dict:
    name = os.path.basename(lock_path)
    if name not in LOCK_NAMES:
        raise DepsError("lock file must be named %s" % " or ".join(LOCK_NAMES))
    allow, exceptions, limit = _policy_values(policy)
    if cap is not None:
        if not isinstance(cap, int) or isinstance(cap, bool) or cap < 0:
            raise DepsError("cap is not a non-negative integer")
        limit = cap if limit is None else min(limit, cap)
    lock_bytes = _read(lock_path)
    lock = _parse(lock_bytes, lock_path)
    report = check(lock, registries, marks)
    report["marks"].require()
    if not report["ok"]:
        return {"ok": False, "reasons": report["reasons"]}
    reasons, blobs, total = [], {}, 0
    for item in report["items"]:
        url = item["entry"]["resolved"]
        if url not in blobs:
            data = fetcher(url, None if limit is None else limit - total)
            total += len(data)
            if limit is not None and total > limit:
                return {"ok": False, "reasons": ["limit_hit:deps_bytes"]}
            blobs[url] = data
        if not integrity_matches(blobs[url], item["strong"]):
            reasons.append("integrity_mismatch:%s" % item["key"])
    if reasons:
        return {"ok": False, "reasons": reasons}
    rows, licenses = [], []
    for item in report["items"]:
        key, entry, data = item["key"], item["entry"], blobs[item["entry"]["resolved"]]
        bad, info = inspect_tarball(data)
        if bad:
            reasons.append("%s:%s" % (bad, key))
            continue
        manifest = info["manifest"]
        if manifest.get("name") != item["name"] or manifest.get("version") != entry["version"]:
            reasons.append("tarball_manifest_mismatch:%s" % key)
            continue
        scripts = manifest.get("scripts")
        script = info["binding_gyp"] or entry.get("hasInstallScript") is True or (
            isinstance(scripts, dict) and any(s in scripts for s in INSTALL_SCRIPTS))
        if script and not report["marks"].marked(key, item["name"], entry["version"]):
            reasons.append("install_script_not_marked:%s" % key)
        found = licenses_of(manifest)
        pinned = "%s==%s" % (item["name"], entry["version"])
        values = [exceptions[pinned]["expression"]] if pinned in exceptions else found
        ok = licenses_allowed(values, allow)
        licenses.append({"key": key, "name": item["name"], "version": entry["version"], "license": values,
                         "allowed": ok})
        if product and not ok:
            reasons.append("%s:%s" % ("license_not_allowed" if values else "license_not_found", key))
        rows.append({"key": key, "name": item["name"], "version": entry["version"], "resolved": entry["resolved"],
                     "integrity": entry["integrity"], "sha512": hashlib.sha512(data).hexdigest(),
                     "bytes": len(data), "license": found, "install_script": bool(script)})
    if reasons:
        return {"ok": False, "reasons": reasons}
    manifest_obj = {"schema": SCHEMA, "lock": name, "lock_sha256": hashlib.sha256(lock_bytes).hexdigest(),
                    "packages": rows}
    manifest_bytes = canonical(manifest_obj)
    address = hashlib.sha256(manifest_bytes).hexdigest()
    _write_artifact(out, address, name, lock_bytes, manifest_bytes, blobs)
    return {"ok": True, "reasons": [], "address": address, "packages": len(rows),
            "bytes": sum(len(b) for b in blobs.values()), "licenses": licenses,
            "artefact": vector_address([{"integrity": r["integrity"], "path": r["key"]} for r in rows])}


def _write_artifact(out: str, address: str, lock_name: str, lock_bytes: bytes, manifest_bytes: bytes,
                    blobs: dict) -> None:
    final = os.path.join(out, address)
    if os.path.lexists(final):
        if not verify(final, address)["ok"]:
            raise DepsError("existing artifact %s does not verify" % address)
        return
    tmp = tempfile.mkdtemp(prefix=".tmp-", dir=out)
    try:
        os.mkdir(os.path.join(tmp, "tarballs"))
        for data in blobs.values():
            with open(os.path.join(tmp, "tarballs", hashlib.sha512(data).hexdigest() + ".tgz"), "wb") as fh:
                fh.write(data)
        with open(os.path.join(tmp, lock_name), "wb") as fh:
            fh.write(lock_bytes)
        with open(os.path.join(tmp, "manifest.json"), "wb") as fh:
            fh.write(manifest_bytes)
        os.rename(tmp, final)
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise


# ---------------------------------------------------------------- verify

def artifact_in(root: str) -> str:
    """The one artifact ``fetch`` wrote under ``root``: ``root/<address>``, the path ``verify`` takes. ``root`` must
    be a directory (no symlink) holding exactly one entry, a directory (no symlink) named 64 lowercase hex; else
    ``DepsError``. Whether that directory is the artifact its name says is ``verify``'s question, not this one's."""
    if os.path.islink(root) or not os.path.isdir(root):
        raise DepsError("deps root is not a directory")
    names = sorted(os.listdir(root))
    if len(names) != 1:
        raise DepsError("deps root holds %d entries, not one artifact" % len(names))
    path = os.path.join(root, names[0])
    if not re.fullmatch(r"[0-9a-f]{64}", names[0]) or os.path.islink(path) or not os.path.isdir(path):
        raise DepsError("deps root's entry is not an artifact directory named by its address")
    return path


def _regular(path: str) -> bytes | None:
    try:
        st = os.lstat(path)
    except OSError:
        return None
    if not stat.S_ISREG(st.st_mode):
        return None
    with open(path, "rb") as fh:
        return fh.read()


def verify(directory: str, address: str | None = None) -> dict:
    """Take an artifact by its hash: ``{ok, reasons, address}``."""
    address = address if address is not None else os.path.basename(os.path.normpath(directory))
    data = _regular(os.path.join(directory, "manifest.json"))
    if data is None:
        return {"ok": False, "reasons": ["manifest_missing"], "address": address}
    if hashlib.sha256(data).hexdigest() != address:
        return {"ok": False, "reasons": ["address_mismatch"], "address": address}
    try:
        manifest = cli.loads(data.decode("ascii"))
        lock_name, packages = manifest["lock"], manifest["packages"]
        expected = {"manifest.json", lock_name, "tarballs"}
        if lock_name not in LOCK_NAMES or manifest.get("schema") != SCHEMA:
            raise ValueError
    except (ValueError, KeyError, TypeError, RecursionError):
        return {"ok": False, "reasons": ["manifest_unreadable"], "address": address}
    reasons = []
    lock = _regular(os.path.join(directory, lock_name))
    if lock is None or hashlib.sha256(lock).hexdigest() != manifest.get("lock_sha256"):
        reasons.append("lock_mismatch")
    tarballs = set()
    for row in packages if isinstance(packages, list) else [None]:
        try:
            fname = row["sha512"] + ".tgz"
            if not re.fullmatch(r"[0-9a-f]{128}\.tgz", fname):
                raise ValueError
            _, strong = parse_integrity(row["integrity"])
        except (TypeError, KeyError, ValueError):
            reasons.append("manifest_unreadable")
            continue
        tarballs.add(fname)
        blob = _regular(os.path.join(directory, "tarballs", fname))
        if blob is None or hashlib.sha512(blob).hexdigest() != row["sha512"]:
            reasons.append("tarball_mismatch:%s" % row.get("key"))
        elif not integrity_matches(blob, strong):
            reasons.append("integrity_mismatch:%s" % row.get("key"))
    try:
        present = set(os.listdir(directory))
        extra = sorted(present - expected)
        tdir = os.path.join(directory, "tarballs")
        if os.path.islink(tdir) or not os.path.isdir(tdir):
            reasons.append("unexpected_file:tarballs")
        else:
            extra += sorted("tarballs/" + n for n in set(os.listdir(tdir)) - tarballs)
    except OSError:
        extra = ["<unlistable>"]
    reasons += ["unexpected_file:%s" % n for n in extra]
    return {"ok": not reasons, "reasons": reasons, "address": address}


# ---------------------------------------------------------------- npmlock (the vector interface)

VECTOR_GIT = ("git+", "git:", "github:", "git@")
VECTOR_REASONS = ("git_dependency", "file_dependency", "registry_not_allowed", "tarball_missing",
                  "integrity_mismatch", "install_script_unmarked")
_REGISTRY_RE = re.compile(r"https://[^/\s]+/\S*")
_ABSOLUTE_RE = re.compile(r"[/\\]|[A-Za-z]:")


def vector_canonical(obj: Any) -> bytes:
    """RFC 8785 for values made of objects, arrays and strings: sorted keys, no spaces, UTF-8."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def vector_address(rows: list[dict]) -> str:
    """``sha256:`` + hex of the canonical JSON of ``[{integrity, path}]`` sorted by path."""
    listed = sorted(({"integrity": r["integrity"], "path": r["path"]} for r in rows), key=lambda r: r["path"])
    return "sha256:" + hashlib.sha256(vector_canonical(listed)).hexdigest()


def _vector_request(raw: bytes) -> tuple[list[str], list[str]]:
    req = _parse(raw, "<stdin>")
    if not isinstance(req, dict):
        raise DepsError("stdin is not an object")
    regs, marks = req.get("registry_egress"), req.get("install_scripts_required")
    for field, value in (("registry_egress", regs), ("install_scripts_required", marks)):
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            raise DepsError("stdin %s is not a list of strings" % field)
    for reg in regs:
        if not _REGISTRY_RE.fullmatch(reg) or not reg.endswith("/"):
            raise DepsError("registry not usable (https://<host>/... ending with /): %r" % reg)
    return regs, marks


def _vector_lock(path: str) -> dict:
    lock = _parse(_read(path), path)
    version = lock.get("lockfileVersion") if isinstance(lock, dict) else None
    if type(version) is not int or version != 3:
        raise DepsError("%s: not a lockfileVersion 3 lock" % path)
    packages = lock.get("packages")
    if not isinstance(packages, dict) or not all(isinstance(v, dict) for v in packages.values()):
        raise DepsError("%s: packages is not an object of objects" % path)
    return packages


def _mirror_file(mirror: str, resolved: str) -> str | None:
    """``https://<host>/<path>`` -> ``<mirror>/<host>/<path>``, taken literally; None if it cannot be there."""
    if not resolved.startswith("https://"):
        return None
    parts = resolved[len("https://"):].split("/")
    if any(p in ("", ".", "..") or "\\" in p or "\0" in p for p in parts):
        return None
    return os.path.join(mirror, *parts)


def _sha512_tokens(integrity: Any) -> list[str]:
    return [t for t in integrity.split() if t.startswith("sha512-")] if isinstance(integrity, str) else []


def _vector_tarball(data: bytes, where: str) -> dict:
    """``package/package.json`` (an object) and whether ``package/binding.gyp`` exists; else no verdict."""
    found, gyp = [], False
    try:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
            for member in tar:
                name = "/".join(p for p in member.name.split("/") if p not in ("", "."))
                if name == "package/binding.gyp":
                    gyp = True
                elif name == "package/package.json":
                    if not member.isfile() or member.size > PACKAGE_JSON_MAX:
                        raise DepsError("%s: package/package.json not a readable file" % where)
                    fh = tar.extractfile(member)
                    found.append(fh.read() if fh else b"")
    except cli.ARCHIVE_ERRORS as exc:
        raise DepsError("%s: tarball unreadable: %s" % (where, cli.cause(exc))) from None
    if len(found) != 1:
        raise DepsError("%s: %d package/package.json members" % (where, len(found)))
    manifest = _parse(found[0], where + ":package/package.json")
    if not isinstance(manifest, dict):
        raise DepsError("%s: package/package.json is not an object" % where)
    return {"manifest": manifest, "binding_gyp": gyp}


def npmlock(lock_path: str, mirror: str, registries: list[str], marks: list[str]) -> dict:
    """The ``npmlock`` report ``{ok, rejected, artefact, licenses}``; DepsError is unusable input."""
    packages = _vector_lock(lock_path)
    found = read_marks(marks, packages)
    try:
        os.listdir(mirror)
    except OSError as exc:
        raise DepsError("mirror unreadable: %s" % (cli.cause(exc))) from None
    rejected, rows, licenses, cache = [], [], [], {}
    links, folders = workspaces(packages)
    for path in sorted(packages):
        if path == "" or path in links or path in folders:
            continue
        entry = packages[path]
        resolved = entry.get("resolved")
        resolved = resolved if isinstance(resolved, str) else None
        reason = None
        if resolved is not None and resolved.startswith(VECTOR_GIT):
            reason = "git_dependency"
        elif (resolved is not None and resolved.startswith("file:")) or (
                entry.get("link") is True and resolved is not None
                and (_ABSOLUTE_RE.match(resolved) or ".." in resolved)):
            reason = "file_dependency"
        elif resolved is None or not any(resolved.startswith(r) for r in registries):
            reason = "registry_not_allowed"
        else:
            fpath = _mirror_file(mirror, resolved)
            if fpath is None or not os.path.isfile(fpath):
                reason = "tarball_missing"
            else:
                if fpath not in cache:
                    try:
                        cache[fpath] = _read(fpath)
                    except OSError as exc:
                        raise DepsError("mirror unreadable: %s: %s" % (fpath, cli.cause(exc))) from None
                data = cache[fpath]
                want = "sha512-" + base64.b64encode(hashlib.sha512(data).digest()).decode("ascii")
                hashes = _sha512_tokens(entry.get("integrity"))
                if not hashes or any(t != want for t in hashes):
                    reason = "integrity_mismatch"
                else:
                    info = _vector_tarball(data, path)
                    manifest = info["manifest"]
                    name, version = manifest.get("name"), manifest.get("version")
                    scripts = manifest.get("scripts")
                    script = (info["binding_gyp"] or entry.get("hasInstallScript") is True
                              or (isinstance(scripts, dict) and any(s in scripts for s in INSTALL_SCRIPTS)))
                    if script and not found.marked(path, name, version):
                        reason = "install_script_unmarked"
                    else:
                        rows.append({"integrity": entry["integrity"], "path": path})
                        lic = manifest.get("license")
                        licenses.append({"path": path, "name": name if isinstance(name, str) else None,
                                         "version": version if isinstance(version, str) else None,
                                         "license": lic if isinstance(lic, str) else None})
        if reason:
            rejected.append("%s:%s" % (reason, path))
    rejected.sort()
    if rejected:
        return {"ok": False, "rejected": rejected, "artefact": None, "licenses": None}
    return {"ok": True, "rejected": [], "artefact": vector_address(rows),
            "licenses": sorted(licenses, key=lambda r: r["path"])}


# ---------------------------------------------------------------- command line

def _read(path: str) -> bytes:
    with open(path, "rb") as fh:
        return fh.read()


def _parse(data: bytes, path: str) -> Any:
    try:
        return cli.loads(data.decode("utf-8"))
    except RecursionError:
        raise DepsError("%s: JSON nested too deeply" % path) from None
    except (UnicodeDecodeError, ValueError) as exc:
        raise DepsError("%s: not JSON: %s" % (path, cli.cause(exc))) from None


def _marks(recipe: Any) -> list[str]:
    if recipe is None:
        return []
    marks = recipe.get("install_scripts_required", []) if isinstance(recipe, dict) else None
    if not isinstance(marks, list) or not all(isinstance(m, str) for m in marks):
        raise DepsError("recipe install_scripts_required is not a list of strings")
    return marks


def _emit(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj, sort_keys=True) + "\n")


USAGE = ("usage: python -m runner.deps_npm fetch LOCK MIRROR (stdin {registry_egress, install_scripts_required}) | "
         "check LOCK [--registry URL]... [--recipe FILE] | store LOCK OUT [--mirror DIR] [--registry URL]... "
         "[--recipe FILE] [--policy FILE] [--product] | verify DIR [--address HEX] | "
         "platform LOCK --os OS --cpu CPU [--libc LIBC]")


def main(argv: list[str]) -> int:
    try:
        if argv[:1] == ["fetch"]:
            if len(argv) != 3 or any(a.startswith("--") for a in argv[1:]):
                raise DepsError(USAGE)
            registries, marks = _vector_request(sys.stdin.buffer.read())
            report = npmlock(argv[1], argv[2], registries, marks)
            _emit(report)
            return 0 if report["ok"] else 1
        args, opts, regs = [], {}, []
        it = iter(argv)
        for a in it:
            if a in ("--registry", "--recipe", "--policy", "--mirror", "--address", "--os", "--cpu", "--libc"):
                value = next(it, None)
                if value is None:
                    raise DepsError("%s needs a value" % a)
                if a == "--registry":
                    regs.append(value)
                elif a in opts:
                    raise DepsError("%s given twice" % a)
                else:
                    opts[a] = value
            elif a == "--product":
                opts[a] = True
            else:
                args.append(a)
        if len(args) == 2 and args[0] == "platform" and {"--os", "--cpu"} <= set(opts) <= {"--os", "--cpu", "--libc"} \
                and not regs:
            report = platform_report(_parse(_read(args[1]), args[1]),
                                     {"os": opts["--os"], "cpu": opts["--cpu"], "libc": opts.get("--libc")})
            _emit(report)
            return 0 if report["ok"] else 1
        if {"--os", "--cpu", "--libc"} & set(opts):
            raise DepsError(USAGE)
        registries = regs or list(DEFAULT_REGISTRIES)
        recipe = _parse(_read(opts["--recipe"]), opts["--recipe"]) if "--recipe" in opts else None
        policy = _parse(_read(opts["--policy"]), opts["--policy"]) if "--policy" in opts else None
        if len(args) == 2 and args[0] == "check" and not ({"--policy", "--mirror", "--address", "--product"} & set(opts)):
            report = check(_parse(_read(args[1]), args[1]), registries, _marks(recipe))
            _emit({"ok": report["ok"], "reasons": report["reasons"]})
            return 0 if report["ok"] else 1
        if len(args) == 3 and args[0] == "store" and "--address" not in opts:
            fetcher = mirror_fetcher(opts["--mirror"]) if "--mirror" in opts else https_fetcher
            report = fetch(args[1], args[2], fetcher, registries, _marks(recipe), policy, "--product" in opts)
            _emit(report)
            return 0 if report["ok"] else 1
        if len(args) == 2 and args[0] == "verify" and set(opts) <= {"--address"} and not regs:
            report = verify(args[1], opts.get("--address"))
            _emit(report)
            return 0 if report["ok"] else 1
        _emit({"ok": False, "error": USAGE})
        return 2
    except (DepsError, ValueError, OSError) as exc:
        _emit({"ok": False, "error": "unusable input: %s" % cli.cause(exc)})
        return 2


FAULT_LINE = {"ok": False, "error": "internal error"}


if __name__ == "__main__":
    sys.exit(cli.run(main, sys.argv[1:], FAULT_LINE))
