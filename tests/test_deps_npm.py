"""Test 34 (asama-0/09) and group ``npmlock`` (tohum/29d): ``deps.fetch`` for npm, on local fixture
tarballs served by a mirror directory (the sandbox has no network; the HTTPS path is asama-0/10a #getir).

- every tarball equals the lock's ``integrity``; one changed byte is refused and no artifact is written;
- ``resolved`` off the allowed registry (host, scheme, user, port, query, path, name), git and file
  dependencies, bundled entries and keys outside ``node_modules`` that no workspace link names are refused
  before anything is fetched; npm workspaces (tohum/29g): a workspace link and the folder it names are skipped,
  nested ``<folder>/node_modules/*`` packages are judged and fetched under their keys (``TestWorkspaces`` and
  the ``workspace`` cases of ``TestNpmlock``);
- a package that needs an install script (lock flag, ``scripts``, ``binding.gyp``) is refused unless the
  recipe marks it by a key of this lock or ``name@version`` (tohum/26c); every other element of
  ``install_scripts_required`` (bare name, scoped bare name, a path this lock does not hold, ``""``, a range
  or tag) is ``mark_not_usable`` for ``check`` and unusable input for ``store`` and ``fetch``, before any
  tarball is fetched; a ``name@version`` the lock does not hold marks nothing;
- the same lock gives the same content address, one changed lock byte another; ``verify`` takes the
  artifact by its hash and refuses a changed tarball, lock or manifest and an extra file;
- the license report is written; with ``--product`` an unlisted or missing license is refused;
- ``operating.deps_bytes`` stops the fetch; unusable input is exit 2 with one JSON line, never a traceback;
- the ``npmlock`` vector interface (tohum/29g), ``fetch LOCK MIRROR`` with stdin, is ``TestNpmlock``: the
  named cases, the order of reasons per package, the address recomputed here, exit 2; the artifact is
  written by ``store`` and prints the same ``artefact``.

Kept mutants of the module's guard rules are in ``tests/mutants/deps_npm.json``, each named with the test here that
kills it; the HTTPS fetcher (no network here) and the artifact's write-then-rename have none.
"""

from __future__ import annotations

import base64
import copy
import gzip
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
import unittest
from unittest import mock

REFEREE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REFEREE)

from runner import deps_npm as N  # noqa: E402
from profile_tree import writable_base  # noqa: E402

REG = "https://registry.npmjs.org/"


def tgz(files: dict, top: str = "package") -> bytes:
    """``files``: name -> bytes | dict (JSON) | ("symlink", target); placed under ``top/``."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz", format=tarfile.USTAR_FORMAT) as tar:
        for name, content in files.items():
            info = tarfile.TarInfo("%s/%s" % (top, name) if top else name)
            info.mtime = 0
            if isinstance(content, tuple):
                info.type, info.linkname = tarfile.SYMTYPE, content[1]
                tar.addfile(info)
                continue
            data = json.dumps(content).encode() if isinstance(content, dict) else content
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def sri(data: bytes, alg: str = "sha512") -> str:
    return "%s-%s" % (alg, base64.b64encode(hashlib.new(alg, data).digest()).decode())


def url(name: str, version: str) -> str:
    return "%s%s/-/%s-%s.tgz" % (REG, name, name.split("/")[-1], version)


class Fixture:
    """A lock, its tarballs in a mirror directory, and an output directory."""

    def __init__(self, base: str):
        self.base = base
        self.mirror = os.path.join(base, "mirror")
        self.out = os.path.join(base, "out")
        os.makedirs(self.out)
        self.lock = {"lockfileVersion": 3, "name": "toy", "packages": {"": {"name": "toy", "version": "1.0.0"}}}
        self.blobs = {}

    def add(self, name: str, version: str, key: str | None = None, manifest: dict | None = None,
            extra: dict | None = None, **entry) -> bytes:
        files = {"package.json": manifest if manifest is not None else
                 {"name": name, "version": version, "license": "MIT"}}
        files.update(extra or {})
        data = tgz(files)
        u = url(name, version)
        self.put(u, data)
        row = {"version": version, "resolved": u, "integrity": sri(data)}
        row.update(entry)
        self.lock["packages"][key or "node_modules/" + name] = row
        return data

    def put(self, u: str, data: bytes) -> None:
        path = os.path.join(self.mirror, *u.split("://", 1)[1].split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as fh:
            fh.write(data)
        self.blobs[u] = data

    def write_lock(self, name: str = "package-lock.json", lock: dict | None = None) -> str:
        path = os.path.join(self.base, name)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(self.lock if lock is None else lock, fh)
        return path

    def fetch(self, **kw):
        calls = []
        inner = N.mirror_fetcher(self.mirror)

        def fetcher(u, cap):
            calls.append(u)
            return inner(u, cap)
        report = N.fetch(self.write_lock(kw.pop("lock_name", "package-lock.json")), self.out, fetcher, **kw)
        return report, calls

    def artifacts(self) -> list[str]:
        return sorted(n for n in os.listdir(self.out))


class Base(unittest.TestCase):
    def setUp(self):
        self.base = writable_base("deps-npm-")
        self.addCleanup(shutil.rmtree, self.base, True)
        self.fx = Fixture(self.base)
        self.fx.add("left-pad", "1.3.0")
        self.fx.add("@scope/util", "2.0.0")
        self.fx.add("inner", "0.1.0", key="node_modules/left-pad/node_modules/inner",
                    manifest={"name": "inner", "version": "0.1.0", "license": "ISC"})


class TestIntegrity(Base):
    def test_good_lock_fetches_and_writes_artifact(self):
        report, calls = self.fx.fetch()
        self.assertTrue(report["ok"], report)
        self.assertEqual(report["packages"], 3)
        self.assertEqual(len(calls), 3)
        self.assertEqual(self.fx.artifacts(), [report["address"]])
        art = os.path.join(self.fx.out, report["address"])
        with open(os.path.join(art, "manifest.json"), "rb") as fh:
            raw = fh.read()
        self.assertEqual(hashlib.sha256(raw).hexdigest(), report["address"])
        manifest = json.loads(raw)
        self.assertEqual(raw, json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("ascii"))
        self.assertEqual([r["key"] for r in manifest["packages"]],
                         ["node_modules/@scope/util", "node_modules/left-pad",
                          "node_modules/left-pad/node_modules/inner"])
        for data in self.fx.blobs.values():
            with open(os.path.join(art, "tarballs", hashlib.sha512(data).hexdigest() + ".tgz"), "rb") as fh:
                self.assertEqual(fh.read(), data)
        self.assertTrue(N.verify(art)["ok"])

    def test_one_changed_byte_is_refused_and_nothing_written(self):
        u = url("left-pad", "1.3.0")
        for pos in (0, len(self.fx.blobs[u]) // 2, len(self.fx.blobs[u]) - 1):
            data = bytearray(self.fx.blobs[u])
            data[pos] ^= 0x01
            with open(os.path.join(self.fx.mirror, "registry.npmjs.org", "left-pad", "-", "left-pad-1.3.0.tgz"),
                      "wb") as fh:
                fh.write(bytes(data))
            report, _ = self.fx.fetch()
            self.assertEqual(report, {"ok": False, "reasons": ["integrity_mismatch:node_modules/left-pad"]})
            self.assertEqual(self.fx.artifacts(), [])

    def test_every_strong_token_must_match(self):
        data = self.fx.blobs[url("left-pad", "1.3.0")]
        entry = self.fx.lock["packages"]["node_modules/left-pad"]
        entry["integrity"] = "%s %s" % (sri(data), sri(b"other", "sha384"))
        self.assertEqual(self.fx.fetch()[0]["reasons"], ["integrity_mismatch:node_modules/left-pad"])
        entry["integrity"] = "%s %s %s" % (sri(b"x", "sha1"), sri(data, "sha256"), sri(data, "sha384"))
        self.assertTrue(self.fx.fetch()[0]["ok"])

    def test_integrity_shape(self):
        data = self.fx.blobs[url("left-pad", "1.3.0")]
        good = sri(data)
        cases = {
            None: "integrity_missing", "": "integrity_missing", 5: "integrity_missing",
            sri(data, "sha1"): "integrity_weak",
            "md5-" + base64.b64encode(hashlib.md5(data).digest()).decode(): "integrity_malformed",
            good[:-4] + "==": "integrity_malformed",            # wrong digest length
            good + "?opt": "integrity_malformed",
            "sha512" + good[6:].replace("-", ""): "integrity_malformed",
            good.replace("sha512-", "sha512-!"): "integrity_malformed",
            "SHA512-" + good[7:]: "integrity_malformed",
            "sha512-" + base64.b64encode(hashlib.sha256(data).digest()).decode(): "integrity_malformed",
            "sha1-!!!!": "integrity_malformed",                 # a weak token is ignored only when well formed
            "sha1-AAAA=== " + good: "integrity_malformed",
        }
        for value, reason in cases.items():
            lock = copy.deepcopy(self.fx.lock)
            lock["packages"]["node_modules/left-pad"]["integrity"] = value
            self.assertEqual(N.check(lock)["reasons"], ["%s:node_modules/left-pad" % reason], value)

    def test_same_lock_same_address_changed_byte_other(self):
        first = self.fx.fetch()[0]
        again = self.fx.fetch()[0]
        self.assertEqual(first["address"], again["address"])
        self.assertEqual(self.fx.artifacts(), [first["address"]])
        self.fx.lock["name"] = "toz"
        other = self.fx.fetch()[0]
        self.assertNotEqual(first["address"], other["address"])
        self.assertEqual(len(self.fx.artifacts()), 2)

    def test_existing_artifact_that_does_not_verify_is_no_verdict(self):
        first = self.fx.fetch()[0]
        lock = os.path.join(self.fx.out, first["address"], "package-lock.json")
        with open(lock, "ab") as fh:
            fh.write(b" ")
        with self.assertRaises(N.DepsError):
            self.fx.fetch()


class TestSource(Base):
    def setUp(self):
        super().setUp()
        self.fetches = []

    def refused(self, key, row, reason, **kw):
        self.fx.lock["packages"][key] = row
        report, calls = self.fx.fetch(**kw)
        self.assertFalse(report["ok"])
        self.assertIn("%s:%s" % (reason, key), report["reasons"], row)
        self.assertEqual(calls, [], "nothing is fetched before the lock passes")
        self.assertEqual(self.fx.artifacts(), [])

    def test_resolved_off_registry(self):
        data = self.fx.blobs[url("left-pad", "1.3.0")]
        good = url("left-pad", "1.3.0")
        for resolved in (
            good.replace("registry.npmjs.org", "registry.evil.org"),
            good.replace("registry.npmjs.org", "registry.npmjs.org.evil.org"),
            good.replace("https://", "http://"),
            good.replace("https://", "https://user@"),
            good.replace("registry.npmjs.org", "registry.npmjs.org:8443"),
            good.replace("registry.npmjs.org", "registry.npmjs.org:443"),
            good.replace("registry.npmjs.org", "regi\u017ftry.npmjs.org"),   # long s casefolds to s
            good.replace("registry.npmjs.org", "registry.npmjs.org."),
            good + "?x=1", good + "#x",
            good.replace("/left-pad/-/", "/other/-/"),                       # another package's tarball
            good.replace("/left-pad/-/", "/left-pad/../other/-/"),
            good.replace("/left-pad/-/", "/left%2dpad/-/"),
            good.replace("1.3.0.tgz", "1.3.1.tgz"),                         # another version
            good.replace(".tgz", ".tar.gz"),
            good.replace("registry.npmjs.org", "registry.npmjs.org.\u212a"),  # Kelvin sign lowercases to k
            "", None,
        ):
            reason = "resolved_missing" if not resolved else "resolved_not_allowed"
            self.refused("node_modules/left-pad", {"version": "1.3.0", "resolved": resolved,
                                                    "integrity": sri(data)}, reason)

    def test_host_is_checked_as_written(self):
        """A host is ``[A-Za-z0-9.-]`` before it is lowercased: a Kelvin sign is refused where ``k`` passes."""
        reg = "https://pkg.example.com/"
        for host, ok in (("pkg.example.com", True), ("PKG.example.com", True), ("p\u212ag.example.com", False)):
            lock = copy.deepcopy(self.fx.lock)
            for row in lock["packages"].values():
                if "resolved" in row:
                    row["resolved"] = row["resolved"].replace(REG, "https://%s/" % host)
            self.assertEqual(N.check(lock, [reg])["ok"], ok, host)

    def test_build_metadata_is_not_in_a_tarball_path(self):
        data = self.fx.blobs[url("left-pad", "1.3.0")]
        self.refused("node_modules/left-pad", {"version": "1.3.0+build", "resolved": url("left-pad", "1.3.0+build"),
                                                "integrity": sri(data)}, "resolved_not_allowed")

    def test_host_is_casefolded_and_registries_replace_default(self):
        self.fx.lock["packages"]["node_modules/left-pad"]["resolved"] = url("left-pad", "1.3.0").replace(
            "registry.npmjs.org", "Registry.NPMJS.org")
        self.assertTrue(N.check(self.fx.lock)["ok"])
        self.assertEqual(N.check(self.fx.lock, ["https://npm.example.com/r/"])["reasons"],
                         ["resolved_not_allowed:%s" % k for k in sorted(self.fx.lock["packages"]) if k])
        lock = copy.deepcopy(self.fx.lock)
        for row in lock["packages"].values():
            if "resolved" in row:
                row["resolved"] = row["resolved"].replace(REG, "https://npm.example.com/r/").replace(
                    "Registry.NPMJS.org/", "npm.example.com/r/")
        self.assertTrue(N.check(lock, ["https://npm.example.com/r"])["ok"])
        self.assertTrue(N.check(lock, ["https://NPM.Example.com/r/"])["ok"])  # the registry's host is lowercased
        for bad in ("http://npm.example.com/", "https://u@npm.example.com/", "https://npm.example.com:8/",
                    "https://npm.example.com/?q", "https://npm.example.com/#f", "https://npm.example.com/a/../b/",
                    "https://npm.example.com/%2e%2e/", "npm.example.com", "https://npm.ex\u017fample.com/", 5):
            with self.assertRaises(N.DepsError, msg=bad):
                N.check(lock, [bad])

    def test_git_and_file_dependencies(self):
        for key, row, reason in (
            ("node_modules/g1", {"version": "git+ssh://git@github.com/a/b.git#abc", "resolved":
                                 "git+ssh://git@github.com/a/b.git#abc"}, "git_dependency"),
            ("node_modules/g2", {"version": "1.0.0", "resolved": "GIT+https://github.com/a/b.git"}, "git_dependency"),
            ("node_modules/g3", {"version": "github:a/b", "resolved": "github:a/b#abc"}, "git_dependency"),
            ("node_modules/g4", {"version": "1.0.0", "resolved": "git@github.com:a/b.git"}, "git_dependency"),
            ("node_modules/g5", {"version": "1.0.0", "resolved": "gitlab:a/b"}, "git_dependency"),
            ("node_modules/g6", {"version": "1.0.0", "resolved": "bitbucket:a/b"}, "git_dependency"),
            ("node_modules/g7", {"version": "1.0.0", "resolved": "gist:abc"}, "git_dependency"),
            ("node_modules/g8", {"version": "github:a/b"}, "git_dependency"),      # the version field is read too
            ("node_modules/f8", {"version": "file:../x"}, "file_dependency"),
            ("node_modules/f1", {"version": "file:../x", "resolved": "file:../x"}, "file_dependency"),
            ("node_modules/f2", {"version": "1.0.0", "resolved": "../x/f2-1.0.0.tgz",
                                 "integrity": sri(b"x")}, "file_dependency"),
            ("node_modules/f3", {"resolved": "../packages/f3", "link": True}, "file_dependency"),
            ("node_modules/f5", {"resolved": "/abs/f5", "link": True}, "file_dependency"),
            ("node_modules/f6", {"resolved": "node_modules/f6", "link": True}, "file_dependency"),  # no folder
            ("node_modules/f7", {"resolved": "./f7", "link": True}, "file_dependency"),  # not written plainly
            ("node_modules/f4", {"version": "1.0.0", "resolved": url("f4", "1.0.0"), "link": True},
             "file_dependency"),
            ("node_modules/b1", {"version": "1.0.0", "inBundle": True}, "bundled_dependency"),
            ("packages/f3", {"name": "f3", "version": "1.0.0"}, "key_not_allowed"),
            ("node_modules/../evil", {"version": "1.0.0", "resolved": url("evil", "1.0.0"),
                                      "integrity": sri(b"x")}, "key_not_allowed"),
            ("node_modules/.bin", {"version": "1.0.0"}, "key_not_allowed"),
            ("node_modules/a/b", {"version": "1.0.0", "resolved": url("a", "1.0.0"),
                                  "integrity": sri(b"x")}, "key_not_allowed"),
            ("node_modules/ok", "not an object", "key_not_allowed"),
            ("node_modules/n1", {"name": "../evil", "version": "1.0.0", "resolved": REG + "../evil/-/evil-1.0.0.tgz",
                                 "integrity": sri(b"x")}, "key_not_allowed"),
            ("node_modules/v2", {"version": "1.0.0-a!b", "resolved": url("v2", "1.0.0-a!b"), "integrity": sri(b"x")},
             "version_invalid"),
            ("node_modules/v1", {"version": "latest", "resolved": url("v1", "latest"), "integrity": sri(b"x")},
             "version_invalid"),
        ):
            self.setUp()
            self.refused(key, row, reason)

    def test_alias_uses_the_entry_name(self):
        data = tgz({"package.json": {"name": "real", "version": "3.0.0", "license": "MIT"}})
        self.fx.put(url("real", "3.0.0"), data)
        self.fx.lock["packages"]["node_modules/alias"] = {"name": "real", "version": "3.0.0",
                                                          "resolved": url("real", "3.0.0"), "integrity": sri(data)}
        self.assertTrue(self.fx.fetch()[0]["ok"])
        self.fx.lock["packages"]["node_modules/alias"]["resolved"] = url("alias", "3.0.0")
        self.assertEqual(N.check(self.fx.lock)["reasons"], ["resolved_not_allowed:node_modules/alias"])

    def test_lock_shape(self):
        for lock, reason in (([], "lock_unparsable"), ({"lockfileVersion": 1, "dependencies": {}},
                                                       "lock_version_unsupported"),
                             ({"lockfileVersion": True, "packages": {}}, "lock_version_unsupported"),
                             ({"lockfileVersion": 3, "packages": []}, "lock_version_unsupported"),
                             ({"lockfileVersion": "3", "packages": {}}, "lock_version_unsupported"),
                             ({"lockfileVersion": 1, "packages": {}}, "lock_version_unsupported"),
                             ({"lockfileVersion": 3.0, "packages": {}}, "lock_version_unsupported"),
                             ({"lockfileVersion": 2.0, "packages": {}}, "lock_version_unsupported")):
            self.assertEqual(N.check(lock)["reasons"], [reason])
        self.assertTrue(N.check({"lockfileVersion": 2, "packages": {"": {}}})["ok"])


class TestWorkspaces(Base):
    """npm workspaces on the live path (tohum/29g, ``workspaces``, ``live_workspaces``, ``key_name``): the link and
    the folder it names are skipped, nested ``<folder>/node_modules/*`` packages are judged and fetched."""

    def setUp(self):
        super().setUp()
        packages = self.fx.lock["packages"]
        packages[""]["workspaces"] = ["libs/ui"]
        packages["node_modules/@acme/ui"] = {"resolved": "libs/ui", "link": True}
        # the folder is the target's own code: its fields are not judged, an install script flag included
        packages["libs/ui"] = {"name": "@acme/ui", "version": "1.0.0", "hasInstallScript": True,
                               "resolved": "https://evil.example/x.tgz"}
        self.nested = self.fx.add("deep", "4.0.0", key="libs/ui/node_modules/deep")

    def test_link_and_folder_skipped_nested_fetched_under_its_key(self):
        self.assertEqual(N.check(self.fx.lock)["reasons"], [])
        report, calls = self.fx.fetch()
        self.assertTrue(report["ok"], report)
        self.assertEqual(sorted(calls), sorted(self.fx.blobs))  # every tarball, no link or folder
        with open(os.path.join(self.fx.out, report["address"], "manifest.json")) as fh:
            rows = json.load(fh)["packages"]
        self.assertEqual([r["key"] for r in rows], ["libs/ui/node_modules/deep", "node_modules/@scope/util",
                                                    "node_modules/left-pad",
                                                    "node_modules/left-pad/node_modules/inner"])
        self.assertTrue(N.verify(os.path.join(self.fx.out, report["address"]))["ok"])

    def test_without_link_true_the_link_and_the_folder_are_refused(self):
        del self.fx.lock["packages"]["node_modules/@acme/ui"]["link"]
        self.assertEqual(N.check(self.fx.lock)["reasons"], [
            "key_not_allowed:libs/ui", "key_not_allowed:libs/ui/node_modules/deep",
            "file_dependency:node_modules/@acme/ui"])

    def test_nested_package_is_judged_like_any_other(self):
        self.fx.lock["packages"]["libs/ui/node_modules/deep"]["resolved"] = url("deep", "4.0.0").replace(
            "registry.npmjs.org", "mirror.example.invalid")
        self.assertEqual(N.check(self.fx.lock)["reasons"], ["resolved_not_allowed:libs/ui/node_modules/deep"])
        self.fx.lock["packages"]["libs/ui/node_modules/deep"] = {
            "version": "4.0.0", "resolved": url("deep", "4.0.0"), "integrity": sri(self.nested),
            "hasInstallScript": True}
        self.assertEqual(N.check(self.fx.lock)["reasons"], ["install_script_not_marked:libs/ui/node_modules/deep"])
        self.assertEqual(N.check(self.fx.lock, marks=["libs/ui/node_modules/deep"])["reasons"], [])
        self.fx.put(url("deep", "4.0.0"), self.nested[:-1] + bytes([self.nested[-1] ^ 1]))
        report, _ = self.fx.fetch(marks=["deep@4.0.0"])
        self.assertEqual(report["reasons"], ["integrity_mismatch:libs/ui/node_modules/deep"])

    def test_a_link_not_taken_stays_an_entry(self):
        for resolved in ("../ui", "/abs/ui", "C:/ui", "libs\\..\\ui", "node_modules/ui", "./libs/ui", "libs//ui",
                         "", "https://registry.npmjs.org/ui/-/ui-1.0.0.tgz"):
            lock = copy.deepcopy(self.fx.lock)
            lock["packages"]["node_modules/@acme/ui"]["resolved"] = resolved
            self.assertIn("file_dependency:node_modules/@acme/ui", N.check(lock)["reasons"], resolved)
            self.assertIn("key_not_allowed:libs/ui", N.check(lock)["reasons"], resolved)
        lock = copy.deepcopy(self.fx.lock)  # a link whose key is no package key
        lock["packages"]["tools/ui"] = lock["packages"].pop("node_modules/@acme/ui")
        self.assertEqual(N.check(lock)["reasons"], ["key_not_allowed:libs/ui",
                                                    "key_not_allowed:libs/ui/node_modules/deep",
                                                    "key_not_allowed:tools/ui"])

    def test_key_name(self):
        folders = {"libs/ui", "apps/web"}
        for key, name in (("node_modules/a", "a"), ("node_modules/@s/a", "@s/a"),
                          ("node_modules/a/node_modules/b", "b"), ("libs/ui/node_modules/a", "a"),
                          ("apps/web/node_modules/@s/a/node_modules/b", "b"),
                          ("libs/ui", None), ("libs/node_modules/a", None), ("other/node_modules/a", None),
                          ("libs/ui/node_modules/a/b", None), ("libs/ui/node_modules/.bin", None),
                          ("node_modules/a/libs/ui/node_modules/b", None), ("node_modules", None),
                          ("libs/ui/x/node_modules/a", None)):
            self.assertEqual(N.key_name(key, folders), name, key)
        self.assertIsNone(N.key_name("./node_modules/a", {"."}))
        self.assertIsNone(N.key_name("a//node_modules/b", {"a/"}))

    def test_workspaces_reading(self):
        packages = {"": {"link": True, "resolved": "x"},
                    "node_modules/a": {"link": True, "resolved": "libs/a"},
                    "node_modules/b": {"link": True, "resolved": "node_modules/c"},
                    "node_modules/d": {"link": "true", "resolved": "libs/d"},
                    "node_modules/e": {"link": True, "resolved": "libs/a..b"},
                    "node_modules/f": {"link": True, "resolved": "libs/../f"},
                    "node_modules/g": {"link": True, "resolved": "a:b"},
                    "node_modules/h": {"link": True, "resolved": "\\h"},
                    "node_modules/i": "not an object"}
        links, folders = N.workspaces(packages)
        self.assertEqual(links, {"node_modules/a": "libs/a", "node_modules/b": "node_modules/c",
                                 "node_modules/e": "libs/a..b"})
        self.assertEqual(folders, {"libs/a", "libs/a..b"})
        self.assertEqual(N.live_workspaces(packages), ({"node_modules/a": "libs/a", "node_modules/e": "libs/a..b"},
                                                       {"libs/a", "libs/a..b"}))


class TestInstallScripts(Base):
    def test_lock_flag_needs_a_mark(self):
        self.fx.lock["packages"]["node_modules/left-pad"]["hasInstallScript"] = True
        report, calls = self.fx.fetch()
        self.assertEqual(report["reasons"], ["install_script_not_marked:node_modules/left-pad"])
        self.assertEqual(calls, [])
        for marks in (["node_modules/left-pad"], ["left-pad@1.3.0"], ["left-pad@1.3.0", "node_modules/left-pad"]):
            self.assertTrue(self.fx.fetch(marks=marks)[0]["ok"], marks)
        # a mark that marks nothing: another version, another name (case counts), another key of this lock
        for marks in (["left-pad@1.3.1"], ["LEFT-PAD@1.3.0"], ["node_modules/@scope/util"], ["absent@1.0.0"],
                      ["@scope/util@2.0.0"]):
            report, calls = self.fx.fetch(marks=marks)
            self.assertEqual((report["reasons"], calls), (["install_script_not_marked:node_modules/left-pad"], []),
                             marks)

    def test_a_marked_lock_flag_is_recorded_and_only_true_is_the_flag(self):
        self.fx.lock["packages"]["node_modules/left-pad"]["hasInstallScript"] = True
        report = self.fx.fetch(marks=["left-pad@1.3.0"])[0]
        self.assertTrue(report["ok"], report)
        with open(os.path.join(self.fx.out, report["address"], "manifest.json"), encoding="ascii") as fh:
            flags = {r["key"]: r["install_script"] for r in json.load(fh)["packages"]}
        self.assertEqual(flags, {"node_modules/@scope/util": False, "node_modules/left-pad": True,
                                 "node_modules/left-pad/node_modules/inner": False})
        for value in ("true", 1, False, None):  # the tarball's scripts are still read in store (test above)
            self.fx.lock["packages"]["node_modules/left-pad"]["hasInstallScript"] = value
            self.assertEqual(N.check(self.fx.lock)["reasons"], [], value)

    def test_an_element_that_is_not_a_mark_makes_the_request_unusable(self):
        self.fx.lock["packages"]["node_modules/left-pad"]["hasInstallScript"] = True
        lock = copy.deepcopy(self.fx.lock)
        for bad in ("left-pad", "absent", "@scope/util", "node_modules/left-pad/", "node_modules/absent",
                    "", "left-pad@^1.3.0", "left-pad@latest", "left-pad@", "@1.3.0", "left pad@1.3.0",
                    "left-pad@1.3"):
            marks = ["left-pad@1.3.0", bad]
            calls = []
            with self.assertRaises(N.DepsError, msg=bad):
                N.fetch(self.fx.write_lock(), self.fx.out, lambda u, cap: calls.append(u), marks=marks)
            self.assertEqual((calls, self.fx.artifacts()), ([], []), bad)
            self.assertEqual(N.check(lock, marks=marks)["reasons"], ["mark_not_usable:%s" % bad], bad)
            self.assertEqual(N.check(lock, marks=[bad, "node_modules/left-pad"])["reasons"],
                             ["mark_not_usable:%s" % bad], bad)
        # every element that is not a mark, in the request's order; the lock's own reasons still follow
        self.assertEqual(N.check(lock, marks=["x", "node_modules/zz"])["reasons"],
                         ["mark_not_usable:x", "mark_not_usable:node_modules/zz",
                          "install_script_not_marked:node_modules/left-pad"])
        # the root key is no package's path; a lock that cannot be read gives its own reason only
        self.assertEqual(N.check({"lockfileVersion": 3, "packages": {"": {}}}, marks=[""])["reasons"],
                         ["mark_not_usable:"])
        self.assertEqual(N.check([], marks=["x"])["reasons"], ["lock_unparsable"])
        self.assertEqual(N.check({"lockfileVersion": 3}, marks=["x"])["reasons"], ["lock_version_unsupported"])

    def test_tarball_scripts_and_binding_gyp_need_a_mark_even_when_lock_is_silent(self):
        for script in N.INSTALL_SCRIPTS:
            self.setUp()
            self.fx.add("left-pad", "1.3.0", manifest={"name": "left-pad", "version": "1.3.0", "license": "MIT",
                                                       "scripts": {script: "node x.js"}})
            self.assertEqual(self.fx.fetch()[0]["reasons"], ["install_script_not_marked:node_modules/left-pad"])
            self.assertTrue(self.fx.fetch(marks=["left-pad@1.3.0"])[0]["ok"])
        self.setUp()
        self.fx.add("left-pad", "1.3.0", extra={"binding.gyp": b"{}"})
        self.assertEqual(self.fx.fetch()[0]["reasons"], ["install_script_not_marked:node_modules/left-pad"])
        self.setUp()
        self.fx.add("left-pad", "1.3.0", manifest={"name": "left-pad", "version": "1.3.0", "license": "MIT",
                                                   "scripts": {"test": "x", "prepare": "y"}})
        report = self.fx.fetch()[0]
        self.assertTrue(report["ok"])
        art = os.path.join(self.fx.out, report["address"], "manifest.json")
        with open(art, encoding="ascii") as fh:
            self.assertFalse(any(r["install_script"] for r in json.load(fh)["packages"]))


class TestPlatform(unittest.TestCase):
    """npm's rule for a lock entry's ``os``, ``cpu`` and ``libc`` (npm-install-checks ``checkPlatform``) and what
    npm then does with the row: an optional row the platform excludes is not installed, any other one fails the
    install."""

    LINUX = {"os": "linux", "cpu": "x64", "libc": "glibc"}

    def test_a_row_without_the_fields_is_admitted(self):
        self.assertTrue(N.platform_admits({}, self.LINUX))
        self.assertTrue(N.platform_admits({"optional": True, "engines": {"node": ">=99"}}, self.LINUX))

    def test_each_field_is_matched_as_npm_matches_it(self):
        cases = [
            ({"os": ["darwin"]}, False),
            ({"os": ["darwin", "linux"]}, True),
            ({"os": "linux"}, True),                       # a string is a list of one
            ({"os": "darwin"}, False),
            ({"os": ["any"]}, True),
            ({"os": ["any", "darwin"]}, False),             # "any" counts only alone
            ({"os": ["!win32"]}, True),                     # only negations, none of them the value
            ({"os": ["!linux"]}, False),
            ({"os": ["!win32", "darwin"]}, False),          # a positive entry is present and none matches
            ({"os": ["!win32", "linux"]}, True),
            ({"os": ["linux", "!linux"]}, False),           # a negation of the value always excludes
            ({"os": []}, True),                             # npm: no positive entry and every one negated
            ({"cpu": ["arm64"]}, False),
            ({"cpu": ["x64", "arm64"]}, True),
            ({"libc": ["musl"]}, False),
            ({"libc": ["glibc"]}, True),
            ({"os": ["linux"], "cpu": ["x64"], "libc": ["musl"]}, False),
            ({"os": ["linux"], "cpu": ["arm64"], "libc": ["glibc"]}, False),
            ({"os": ["linux"], "cpu": ["x64"], "libc": ["glibc"]}, True),
        ]
        for entry, expected in cases:
            with self.subTest(entry=entry):
                self.assertIs(N.platform_admits(entry, self.LINUX), expected)

    def test_a_libc_row_needs_a_known_libc(self):
        unknown = {"os": "linux", "cpu": "x64", "libc": None}
        self.assertFalse(N.platform_admits({"libc": ["glibc"]}, unknown))
        self.assertFalse(N.platform_admits({"libc": ["!musl"]}, unknown))
        self.assertTrue(N.platform_admits({"os": ["linux"]}, unknown))

    def test_a_field_of_another_shape_is_read_as_npm_reads_it(self):
        # the outcomes are npm's own: checkPlatform of npm-install-checks 7 (npm 10.9), asked value by value
        for value in (None, False, 0, ""):          # ``target.os ? ... : true``: a value JavaScript holds false
            with self.subTest(value=value):
                for field in ("os", "cpu", "libc"):
                    self.assertTrue(N.platform_admits({field: value}, self.LINUX))
                self.assertTrue(N.platform_admits({"libc": value}, dict(self.LINUX, libc=None)))
        for value in (7, True, {}, {"linux": 1}, ["linux", 7], [["linux"]], [7], ["!linux", 7], [None],
                      {"length": 1, "0": "linux"}, {"length": 2, "0": "any"}, {"length": True, "0": "any"},
                      {"length": "1", "0": "any"}):
            with self.subTest(value=value):         # npm's check throws or says no: the row is excluded
                for field in ("os", "cpu", "libc"):
                    self.assertFalse(N.platform_admits({field: value}, self.LINUX))
        # ``list.length === 1 && list[0] === 'any'`` holds for this object as for the list
        self.assertTrue(N.platform_admits({"os": {"length": 1, "0": "any"}}, self.LINUX))
        self.assertTrue(N.platform_admits({"os": {"length": 1, "0": "any", "1": "darwin"}}, self.LINUX))

    def test_a_flag_is_set_by_any_value_javascript_holds_true(self):
        for value, truth in ((True, True), ("true", True), ("false", True), (1, True), ([], True), ({}, True),
                             (False, False), (None, False), (0, False), ("", False)):
            with self.subTest(value=value):
                self.assertIs(N.js_true(value), truth)

    def test_plan_sorts_rows_into_what_npm_does_with_them(self):
        packages = {
            "": {"name": "root"},
            "node_modules/plain": {"version": "1.0.0"},
            "node_modules/mac": {"version": "1.0.0", "optional": True, "os": ["darwin"]},
            "node_modules/mac/node_modules/inner": {"version": "1.0.0", "optional": True},
            "node_modules/mac-tools": {"version": "1.0.0"},     # a sibling whose name starts alike is not below it
            "node_modules/musl-binding": {"version": "1.0.0", "optional": True, "dev": True, "libc": ["musl"]},
            "node_modules/glibc-binding": {"version": "1.0.0", "optional": True, "libc": ["glibc"]},
            "node_modules/needs-mac": {"version": "1.0.0", "os": ["darwin"]},
            "node_modules/needs-mac/node_modules/under": {"version": "1.0.0", "os": ["darwin"]},   # goes with it
            "node_modules/dev-or-optional": {"version": "1.0.0", "devOptional": True, "cpu": ["arm64"]},
            "node_modules/optional-word": {"version": "1.0.0", "optional": "false", "os": ["darwin"]},   # ``!!"false"``
            "node_modules/optional-word-kept": {"version": "1.0.0", "optional": 1},
            "node_modules/optional-zero": {"version": "1.0.0", "optional": 0, "os": ["darwin"]},
            "node_modules/optional-list-kept": {"version": "1.0.0", "optional": []},    # true in JavaScript
            "node_modules/optional-object": {"version": "1.0.0", "optional": {}, "os": ["darwin"]},
        }
        keys = [k for k in packages if k]
        plan = N.platform_plan(packages, keys, self.LINUX)
        self.assertEqual(plan, {
            "installed": ["node_modules/glibc-binding", "node_modules/mac-tools", "node_modules/optional-list-kept",
                          "node_modules/optional-word-kept", "node_modules/plain"],
            "not_installed": ["node_modules/dev-or-optional", "node_modules/mac",
                              "node_modules/mac/node_modules/inner", "node_modules/musl-binding",
                              "node_modules/needs-mac", "node_modules/needs-mac/node_modules/under",
                              "node_modules/optional-object", "node_modules/optional-word",
                              "node_modules/optional-zero"],
            "unsupported": ["node_modules/dev-or-optional", "node_modules/needs-mac",
                            "node_modules/optional-zero"],
            "optional": ["node_modules/glibc-binding", "node_modules/optional-list-kept",
                         "node_modules/optional-word-kept"],
        })
        musl = N.platform_plan(packages, keys, dict(self.LINUX, libc="musl"))
        self.assertIn("node_modules/musl-binding", musl["installed"])
        self.assertIn("node_modules/glibc-binding", musl["not_installed"])
        # only the keys asked about are sorted; a key the lock lacks has no fields and is admitted
        self.assertEqual(N.platform_plan(packages, ["node_modules/absent"], self.LINUX),
                         {"installed": ["node_modules/absent"], "not_installed": [], "unsupported": [],
                          "optional": []})

    def test_command_line_reports_the_plan_and_the_rows_with_a_script(self):
        base = writable_base("deps-plat-")
        self.addCleanup(shutil.rmtree, base, True)
        fx = Fixture(base)
        fx.add("left-pad", "1.3.0")
        fx.add("mac", "1.0.0")
        fx.add("native", "1.0.0")
        fx.lock["packages"]["node_modules/left-pad"]["hasInstallScript"] = True
        fx.lock["packages"]["node_modules/mac"].update(optional=True, os=["darwin"], hasInstallScript=True)
        fx.lock["packages"]["node_modules/native"].update(optional=True, hasInstallScript=True)
        for name, fields in (("plain", {}), ("mac-plain", {"optional": True, "os": ["darwin"]}),
                             ("opt-plain", {"optional": True}), ("script-not-true", {"hasInstallScript": "true"})):
            fx.add(name, "1.0.0")           # rows without a script are in no list of ``scripts``
            fx.lock["packages"]["node_modules/" + name].update(fields)
        lock_path = fx.write_lock()

        def run(*args):
            proc = subprocess.run([sys.executable, "-m", "runner.deps_npm", "platform", lock_path] + list(args),
                                  cwd=REFEREE, capture_output=True, text=True, timeout=60)
            self.assertNotIn("Traceback", proc.stderr)
            return proc.returncode, json.loads(proc.stdout)
        code, out = run("--os", "linux", "--cpu", "x64", "--libc", "glibc")
        self.assertEqual(code, 0)
        self.assertEqual(out, {
            "ok": True, "platform": {"os": "linux", "cpu": "x64", "libc": "glibc"}, "packages": 7, "installed": 5,
            "not_installed": ["node_modules/mac", "node_modules/mac-plain"], "unsupported": [],
            "scripts": {"required": ["node_modules/left-pad"], "optional": ["node_modules/native"],
                        "not_installed": ["node_modules/mac"]}})
        fx.lock["packages"]["node_modules/mac"]["optional"] = False
        fx.write_lock()
        code, out = run("--os", "linux", "--cpu", "x64", "--libc", "glibc")
        self.assertEqual((code, out["ok"], out["unsupported"], out["not_installed"], out["scripts"]["not_installed"]),
                         (0, True, ["node_modules/mac"], ["node_modules/mac", "node_modules/mac-plain"],
                          ["node_modules/mac"]))
        code, out = run("--os", "darwin", "--cpu", "arm64")
        self.assertEqual((code, out["platform"], out["installed"]),
                         (0, {"os": "darwin", "cpu": "arm64", "libc": None}, 7))
        for args in ((), ("--os", "linux"), ("--cpu", "x64"), ("--os", "linux", "--cpu", "x64", "--libc"),
                     ("--os", "linux", "--cpu", "x64", "--registry", "https://r.example/")):
            with self.subTest(args=args):
                code, out = run(*args)
                self.assertEqual((code, out["ok"]), (2, False))
        # the platform options belong to this command alone
        proc = subprocess.run([sys.executable, "-m", "runner.deps_npm", "check", lock_path, "--os", "linux"],
                              cwd=REFEREE, capture_output=True, text=True, timeout=60)
        self.assertEqual((proc.returncode, json.loads(proc.stdout)["ok"]), (2, False))
        # a lock with a structure reason is not ok, whatever the platform admits
        fx.lock["lockfileVersion"] = 1
        fx.write_lock()
        code, out = run("--os", "darwin", "--cpu", "arm64")
        self.assertEqual((code, out["ok"], out["unsupported"]), (1, False, []))
        self.assertTrue(out["reasons"])


class TestTarball(Base):
    def test_tarball_shape(self):
        manifest = {"name": "left-pad", "version": "1.3.0", "license": "MIT"}
        for files, top, reason in (
            ({"index.js": b"x"}, "package", "tarball_no_package_json"),
            ({"package.json": ("symlink", "/etc/passwd")}, "package", "tarball_no_package_json"),
            ({"package.json": b"{not json"}, "package", "tarball_package_json_unreadable"),
            ({"package.json": b"[1]"}, "package", "tarball_package_json_unreadable"),
            ({"package.json": b"[" * 100000}, "package", "tarball_package_json_unreadable"),
            ({"package.json": b" " * (N.PACKAGE_JSON_MAX + 1)}, "package", "tarball_package_json_unreadable"),
            ({"package/package.json": manifest, "other/package.json": manifest}, "", "tarball_ambiguous_package_json"),
            ({"package.json": {"name": "left-pad", "version": "1.3.1"}}, "package", "tarball_manifest_mismatch"),
            ({"package.json": manifest, "node_modules/x/package.json": {"name": "x", "version": "1.0.0",
                                                                        "scripts": {"postinstall": "x"}}},
             "package", "bundled_dependency"),
            ({"package.json": {"name": "right-pad", "version": "1.3.0"}}, "package", "tarball_manifest_mismatch"),
        ):
            self.setUp()
            data = tgz(files, top)
            self.fx.put(url("left-pad", "1.3.0"), data)
            self.fx.lock["packages"]["node_modules/left-pad"]["integrity"] = sri(data)
            report = self.fx.fetch()[0]
            self.assertEqual(report["reasons"], ["%s:node_modules/left-pad" % reason], files)
            self.assertEqual(self.fx.artifacts(), [])
        for data in (b"not gzip", tgz({"package.json": manifest})[:-30]):
            self.setUp()
            self.fx.put(url("left-pad", "1.3.0"), data)
            self.fx.lock["packages"]["node_modules/left-pad"]["integrity"] = sri(data)
            self.assertEqual(self.fx.fetch()[0]["reasons"], ["tarball_unreadable:node_modules/left-pad"])

    def test_dot_component_members_are_read(self):
        data = tgz({"package.json": {"name": "left-pad", "version": "1.3.0", "license": "MIT"},
                    "binding.gyp": b"{}"}, "./package")
        self.fx.put(url("left-pad", "1.3.0"), data)
        self.fx.lock["packages"]["node_modules/left-pad"]["integrity"] = sri(data)
        self.assertEqual(self.fx.fetch()[0]["reasons"], ["install_script_not_marked:node_modules/left-pad"])
        self.assertTrue(self.fx.fetch(marks=["left-pad@1.3.0"])[0]["ok"])

    def test_package_json_is_at_most_one_mebibyte(self):
        body = json.dumps({"name": "left-pad", "version": "1.3.0", "license": "MIT"}).encode()
        for size, reason in ((1 << 20, None), ((1 << 20) + 1, "tarball_package_json_unreadable")):
            self.setUp()
            data = tgz({"package.json": body + b" " * (size - len(body))})
            self.fx.put(url("left-pad", "1.3.0"), data)
            self.fx.lock["packages"]["node_modules/left-pad"]["integrity"] = sri(data)
            report = self.fx.fetch()[0]
            self.assertEqual(report["reasons"], ["%s:node_modules/left-pad" % reason] if reason else [], size)

    def test_top_directory_name_is_free(self):
        data = tgz({"package.json": {"name": "left-pad", "version": "1.3.0", "license": "MIT"}}, "left-pad")
        self.fx.put(url("left-pad", "1.3.0"), data)
        self.fx.lock["packages"]["node_modules/left-pad"]["integrity"] = sri(data)
        self.assertTrue(self.fx.fetch()[0]["ok"])


class TestLicense(Base):
    def lic(self, manifest_license: dict, **kw):
        self.fx.add("left-pad", "1.3.0", manifest=dict({"name": "left-pad", "version": "1.3.0"}, **manifest_license))
        return self.fx.fetch(**kw)[0]

    def test_report_written_not_gated_without_product(self):
        report = self.lic({"license": "GPL-3.0-only"})
        self.assertTrue(report["ok"])
        row = [r for r in report["licenses"] if r["key"] == "node_modules/left-pad"][0]
        self.assertEqual((row["license"], row["allowed"]), (["GPL-3.0-only"], False))
        with open(os.path.join(self.fx.out, report["address"], "manifest.json"), encoding="ascii") as fh:
            rows = {r["key"]: r["license"] for r in json.load(fh)["packages"]}
        self.assertEqual(rows["node_modules/left-pad"], ["GPL-3.0-only"])
        self.assertEqual(rows["node_modules/left-pad/node_modules/inner"], ["ISC"])

    def test_product_gate(self):
        cases = [
            ({"license": "MIT"}, None),
            ({"license": "(MIT OR Apache-2.0)"}, None),
            ({"license": "mit AND isc"}, None),                        # identifiers casefolded
            ({"license": "MIT and ISC"}, "license_not_allowed"),       # operators are not
            ({"license": "MIT AND ISC"}, None),
            ({"license": {"type": "BSD-3-Clause"}}, None),
            ({"licenses": [{"type": "MIT"}, "ISC"]}, None),
            ({"license": "MIT OR GPL-3.0-only"}, "license_not_allowed"),
            ({"license": "Apache-2.0 WITH LLVM-exception"}, "license_not_allowed"),
            ({"license": "MIT+"}, "license_not_allowed"),
            ({"license": "I\u017fC"}, "license_not_allowed"),              # long s casefolds to s
            ({"license": "SEE LICENSE IN LICENSE"}, "license_not_allowed"),
            ({"license": "(MIT"}, "license_not_allowed"),
            ({"license": "MIT)"}, "license_not_allowed"),
            ({"license": "MIT OR"}, "license_not_allowed"),
            ({"license": ""}, "license_not_allowed"),
            ({"license": "MIT", "licenses": [{"type": "GPL-2.0"}]}, "license_not_allowed"),
            ({"license": 5}, "license_not_allowed"),
            ({"licenses": "MIT"}, "license_not_allowed"),
            ({"licenses": [{"name": "MIT"}]}, "license_not_allowed"),
            ({}, "license_not_found"),
            ({"licenses": []}, "license_not_found"),
            ({"license": "(MIT GPL-3.0-only"}, "license_not_allowed"),      # an unclosed group ends nothing
            ({"license": " AND ".join(["MIT"] * 256)}, None),                # 511 words
            ({"license": " AND ".join(["MIT"] * 257)}, "license_not_allowed"),  # 513 words
            ({"license": "(" * 64 + "MIT" + ")" * 64}, None),
            ({"license": "(" * 65 + "MIT" + ")" * 65}, "license_not_allowed"),
            ({"license": "Licen\u00e7a"}, "license_not_allowed"),
        ]
        for value, reason in cases:
            self.setUp()
            report = self.lic(value, product=True)
            if reason is None:
                self.assertTrue(report["ok"], (value, report))
            else:
                self.assertEqual(report["reasons"], ["%s:node_modules/left-pad" % reason], value)
                self.assertEqual(self.fx.artifacts(), [])

    def test_policy_allowlist_and_exception(self):
        policy = {"constitutional": {"license_allowlist": ["ISC"]}}
        self.assertEqual(self.lic({"license": "ISC"}, product=True, policy=policy)["reasons"],
                         ["license_not_allowed:node_modules/@scope/util"])
        self.setUp()
        policy = {"constitutional": {"license_exceptions": {
            "left-pad==1.3.0": {"expression": "MIT", "evidence": "reviewed"}}}}
        report = self.lic({}, product=True, policy=policy)
        self.assertTrue(report["ok"], report)
        self.setUp()
        policy["constitutional"]["license_exceptions"]["left-pad==1.3.0"]["expression"] = "GPL-3.0-only"
        self.assertEqual(self.lic({"license": "MIT"}, product=True, policy=policy)["reasons"],
                         ["license_not_allowed:node_modules/left-pad"])
        self.setUp()
        policy["constitutional"]["license_exceptions"] = {"left-pad==1.3.1": {"expression": "MIT", "evidence": "x"}}
        self.assertEqual(self.lic({}, product=True, policy=policy)["reasons"],
                         ["license_not_found:node_modules/left-pad"])
        # an identifier is [A-Za-z0-9.+-] even when the allowlist lists another; WITH is never one
        for listed, value, ok in ((["MIT", "ISC", "Custom,License"], "Custom,License", False),
                                  (["MIT", "ISC", "GPL-2.0+"], "GPL-2.0+", True),
                                  (["MIT", "ISC", "WITH"], "WITH", False),
                                  (["MIT", "ISC", "Apache-2.0", "LLVM-exception", "WITH"],
                                   "Apache-2.0 WITH LLVM-exception", False)):
            self.setUp()
            report = self.lic({"license": value}, product=True,
                              policy={"constitutional": {"license_allowlist": listed}})
            self.assertEqual(report["ok"], ok, (listed, value, report))

    def test_non_ascii_license_is_reported_in_an_ascii_manifest(self):
        report = self.lic({"license": "Licen\u00e7a"})
        self.assertTrue(report["ok"], report)
        art = os.path.join(self.fx.out, report["address"])
        with open(os.path.join(art, "manifest.json"), "rb") as fh:
            raw = fh.read()
        raw.decode("ascii")
        self.assertIn(["Licen\u00e7a"], [r["license"] for r in json.loads(raw)["packages"]])
        self.assertTrue(N.verify(art)["ok"])

    def test_policy_shape(self):
        for policy in ([], {"constitutional": []}, {"operating": "x"},
                       {"constitutional": {"license_allowlist": ["MIT", 5]}},
                       {"constitutional": {"license_exceptions": {"a==1": {"evidence": "x"}}}},
                       {"operating": {"deps_bytes": {"value": -1}}}, {"operating": {"deps_bytes": {"value": True}}},
                       {"operating": {"deps_bytes": 5}}):
            with self.subTest(policy=policy), self.assertRaises(N.DepsError):
                self.fx.fetch(policy=policy)
        self.assertEqual(self.fx.artifacts(), [])


class TestLimitAndVerify(Base):
    def test_deps_bytes(self):
        total = sum(len(b) for b in self.fx.blobs.values())
        ok = {"operating": {"deps_bytes": {"value": total, "band": [0, total]}}}
        self.assertTrue(self.fx.fetch(policy=ok)[0]["ok"])
        over = {"operating": {"deps_bytes": {"value": total - 1, "band": [0, total]}}}
        self.assertEqual(self.fx.fetch(policy=over)[0], {"ok": False, "reasons": ["limit_hit:deps_bytes"]})

    def test_a_shared_tarball_is_fetched_and_counted_once(self):
        row = dict(self.fx.lock["packages"]["node_modules/left-pad"])
        self.fx.lock["packages"]["node_modules/@scope/util/node_modules/left-pad"] = row
        total = sum(len(b) for b in self.fx.blobs.values())
        report, calls = self.fx.fetch(cap=total)
        self.assertTrue(report["ok"], report)
        self.assertEqual((report["packages"], len(calls), report["bytes"]), (4, 3, total))

    def test_mirror_host_is_lowercased(self):
        entry = self.fx.lock["packages"]["node_modules/left-pad"]
        entry["resolved"] = entry["resolved"].replace("registry.npmjs.org", "Registry.NPMJS.org")
        self.assertTrue(self.fx.fetch()[0]["ok"])

    def test_cap_only_tightens(self):
        total = sum(len(b) for b in self.fx.blobs.values())
        hit = {"ok": False, "reasons": ["limit_hit:deps_bytes"]}
        ok = {"operating": {"deps_bytes": {"value": total, "band": [0, total]}}}
        over = {"operating": {"deps_bytes": {"value": total - 1, "band": [0, total]}}}
        self.assertEqual(self.fx.fetch(cap=total - 1)[0], hit)                     # no policy: the cap binds
        self.assertEqual(self.fx.fetch(policy=ok, cap=total - 1)[0], hit)          # smaller than the policy's
        self.assertEqual(self.fx.fetch(policy=over, cap=total * 2)[0], hit)        # a larger cap loosens nothing
        self.assertTrue(self.fx.fetch(policy=ok, cap=total)[0]["ok"])
        for bad in (-1, True, 1.5, "1"):
            with self.subTest(cap=bad), self.assertRaises(N.DepsError):
                self.fx.fetch(cap=bad)

    def test_artifact_in_takes_the_one_address_directory(self):
        address = self.fx.fetch()[0]["address"]
        self.assertEqual(N.artifact_in(self.fx.out), os.path.join(self.fx.out, address))
        self.assertTrue(N.verify(N.artifact_in(self.fx.out))["ok"])
        cases = {
            "a second entry": lambda: open(os.path.join(self.fx.out, "x"), "w").close(),
            "not hex": lambda: os.rename(os.path.join(self.fx.out, address),
                                         os.path.join(self.fx.out, address[:-1] + "g")),
            "upper case": lambda: os.rename(os.path.join(self.fx.out, address),
                                            os.path.join(self.fx.out, address.upper())),
            "short": lambda: os.rename(os.path.join(self.fx.out, address), os.path.join(self.fx.out, address[:-1])),
            "a symlink": lambda: (os.rename(os.path.join(self.fx.out, address), os.path.join(self.base, "moved")),
                                  os.symlink(os.path.join(self.base, "moved"), os.path.join(self.fx.out, address))),
            "a file": lambda: (shutil.rmtree(os.path.join(self.fx.out, address)),
                               open(os.path.join(self.fx.out, address), "w").close()),
            "empty": lambda: shutil.rmtree(os.path.join(self.fx.out, address)),
        }
        for name, change in cases.items():
            with self.subTest(name):
                shutil.rmtree(self.fx.out)
                shutil.rmtree(os.path.join(self.base, "moved"), ignore_errors=True)
                os.makedirs(self.fx.out)
                self.fx.fetch()
                change()
                with self.assertRaises(N.DepsError):
                    N.artifact_in(self.fx.out)
        for root in (os.path.join(self.base, "absent"), os.path.join(self.fx.mirror, "registry.npmjs.org", "left-pad",
                                                                     "-", "left-pad-1.3.0.tgz")):
            with self.subTest(root=root), self.assertRaises(N.DepsError):
                N.artifact_in(root)
        shutil.rmtree(self.fx.out)
        os.makedirs(self.fx.out)
        self.fx.fetch()
        self.assertEqual(len(self.fx.artifacts()), 1)  # a root that is fine but for the link
        os.symlink(self.fx.out, os.path.join(self.base, "root-link"))
        with self.assertRaises(N.DepsError):
            N.artifact_in(os.path.join(self.base, "root-link"))

    def test_verify_refuses_every_change(self):
        report = self.fx.fetch()[0]
        art = os.path.join(self.fx.out, report["address"])
        self.assertTrue(N.verify(art, report["address"])["ok"])
        self.assertEqual(N.verify(art, "0" * 64)["reasons"], ["address_mismatch"])

        def mutated(change):
            copy_dir = os.path.join(self.base, "copy")
            shutil.rmtree(copy_dir, True)
            shutil.copytree(art, copy_dir, symlinks=True)
            change(copy_dir)
            return N.verify(copy_dir, report["address"])

        tball = sorted(os.listdir(os.path.join(art, "tarballs")))[0]

        def flip(path):
            def change(d):
                with open(os.path.join(d, path), "r+b") as fh:
                    first = fh.read(1)
                    fh.seek(0)
                    fh.write(bytes([first[0] ^ 1]))
            return change

        def extra(path):
            def change(d):
                with open(os.path.join(d, path), "wb") as fh:
                    fh.write(b"x")
            return change

        def link_tarball(d):
            p = os.path.join(d, "tarballs", tball)
            os.rename(p, p + ".real")
            os.symlink(p + ".real", p)

        self.assertTrue(mutated(lambda d: None)["ok"])
        self.assertIn("tarball_mismatch", mutated(flip("tarballs/" + tball))["reasons"][0])
        self.assertEqual(mutated(flip("package-lock.json"))["reasons"], ["lock_mismatch"])
        self.assertEqual(mutated(flip("manifest.json"))["reasons"], ["address_mismatch"])
        self.assertEqual(mutated(extra("node_modules"))["reasons"], ["unexpected_file:node_modules"])
        self.assertEqual(mutated(extra("tarballs/x.tgz"))["reasons"], ["unexpected_file:tarballs/x.tgz"])
        reasons = mutated(link_tarball)["reasons"]
        self.assertIn("tarball_mismatch", reasons[0])
        self.assertIn("unexpected_file:tarballs/%s.real" % tball, reasons)
        self.assertEqual(mutated(lambda d: os.remove(os.path.join(d, "manifest.json")))["reasons"],
                         ["manifest_missing"])

        def link_tarballs(d):
            moved = os.path.join(self.base, "tarballs-elsewhere")
            shutil.rmtree(moved, True)
            os.rename(os.path.join(d, "tarballs"), moved)
            os.symlink(moved, os.path.join(d, "tarballs"))
        self.assertEqual(mutated(link_tarballs)["reasons"], ["unexpected_file:tarballs"])

    def test_verify_reads_a_readdressed_manifest_by_its_rules(self):
        """A manifest rewritten and stored under its new address passes the address check; its rules still hold."""
        report = self.fx.fetch()[0]
        art = os.path.join(self.fx.out, report["address"])
        with open(os.path.join(art, "manifest.json"), "rb") as fh:
            manifest = json.loads(fh.read())

        def readdressed(change, rename=None):
            m = copy.deepcopy(manifest)
            change(m)
            raw = N.canonical(m)
            address = hashlib.sha256(raw).hexdigest()
            d = os.path.join(self.base, address)
            shutil.rmtree(d, True)
            shutil.copytree(art, d)
            with open(os.path.join(d, "manifest.json"), "wb") as fh:
                fh.write(raw)
            if rename:
                os.rename(os.path.join(d, "package-lock.json"), os.path.join(d, rename))
            return N.verify(d)

        self.assertTrue(readdressed(lambda m: None)["ok"])
        self.assertEqual(readdressed(lambda m: m.update(lock="lock.json"), "lock.json")["reasons"],
                         ["manifest_unreadable"])
        self.assertEqual(readdressed(lambda m: m.update(schema="snowball-deps-npm/2"))["reasons"],
                         ["manifest_unreadable"])
        weak = "sha1-" + base64.b64encode(hashlib.sha1(b"x").digest()).decode()
        key = manifest["packages"][0]["key"]
        reasons = readdressed(lambda m: m["packages"][0].update(integrity=weak))["reasons"]
        self.assertEqual(reasons, ["integrity_mismatch:%s" % key])
        reasons = readdressed(lambda m: m["packages"][0].update(integrity=sri(b"other")))["reasons"]
        self.assertEqual(reasons, ["integrity_mismatch:%s" % key])
        upper = manifest["packages"][0]["sha512"].upper()
        reasons = readdressed(lambda m: m["packages"][0].update(sha512=upper))["reasons"]
        self.assertEqual(reasons[0], "manifest_unreadable")


class TestCli(Base):
    def run_cli(self, *args):
        proc = subprocess.run([sys.executable, "-m", "runner.deps_npm", *args], cwd=REFEREE, input="",
                              capture_output=True, text=True, timeout=120)
        lines = proc.stdout.splitlines()
        self.assertEqual(len(lines), 1, proc.stdout + proc.stderr)
        self.assertEqual(proc.stderr, "")
        return proc.returncode, json.loads(lines[0])

    def write(self, name, obj):
        path = os.path.join(self.base, name)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(obj if isinstance(obj, str) else json.dumps(obj))
        return path

    def test_cli(self):
        lock = self.fx.write_lock()
        code, out = self.run_cli("check", lock)
        self.assertEqual((code, out), (0, {"ok": True, "reasons": []}))
        code, out = self.run_cli("store", lock, self.fx.out, "--mirror", self.fx.mirror)
        self.assertEqual(code, 0)
        self.assertTrue(out["ok"])
        self.assertEqual(self.run_cli("verify", os.path.join(self.fx.out, out["address"]))[0], 0)
        code, out2 = self.run_cli("verify", os.path.join(self.fx.out, out["address"]), "--address", "f" * 64)
        self.assertEqual((code, out2["reasons"]), (1, ["address_mismatch"]))
        u = url("left-pad", "1.3.0")
        with open(os.path.join(self.fx.mirror, *u.split("://")[1].split("/")), "r+b") as fh:
            fh.seek(40)
            b = fh.read(1)
            fh.seek(40)
            fh.write(bytes([b[0] ^ 0x80]))
        code, out = self.run_cli("store", lock, self.fx.out, "--mirror", self.fx.mirror)
        self.assertEqual((code, out["reasons"]), (1, ["integrity_mismatch:node_modules/left-pad"]))
        self.fx.lock["packages"]["node_modules/left-pad"]["hasInstallScript"] = True
        lock = self.fx.write_lock()
        recipe = self.write("units.json", {"install_scripts_required": ["left-pad@1.3.0"]})
        self.assertEqual(self.run_cli("check", lock)[0], 1)
        self.assertEqual(self.run_cli("check", lock, "--recipe", recipe), (0, {"ok": True, "reasons": []}))
        code, out = self.run_cli("check", lock, "--registry", "https://other.example/")
        self.assertEqual(code, 1)

    def test_cli_product_and_policy(self):
        self.fx.add("left-pad", "1.3.0", manifest={"name": "left-pad", "version": "1.3.0", "license": "GPL-2.0"})
        lock = self.fx.write_lock()
        args = ("store", lock, self.fx.out, "--mirror", self.fx.mirror)
        self.assertEqual(self.run_cli(*args)[0], 0)
        code, out = self.run_cli(*args, "--product")
        self.assertEqual((code, out["reasons"]), (1, ["license_not_allowed:node_modules/left-pad"]))
        policy = self.write("policy.json", {"constitutional": {"license_allowlist": ["GPL-2.0", "MIT", "ISC"]}})
        self.assertEqual(self.run_cli(*args, "--product", "--policy", policy)[0], 0)

    def test_cli_unusable_input_is_exit_2_with_json_error(self):
        lock = self.fx.write_lock()
        os.mkdir(os.path.join(self.base, "deep"))
        deep = self.write("deep/package-lock.json", "[" * 100000)
        self.fx.write_lock(name="npm-shrinkwrap.json")
        shrink = os.path.join(self.base, "npm-shrinkwrap.json")
        wrong_name = self.write("lock.json", self.fx.lock)
        empty_mirror = os.path.join(self.base, "empty")
        os.mkdir(empty_mirror)
        cases = [
            ("check", os.path.join(self.base, "missing.json")),
            ("check", self.write("bad.json", "{")),
            ("check", deep),
            ("check", shrink, "--recipe", self.write("r1.json", {"install_scripts_required": "x"})),
            ("check", shrink, "--recipe", self.write("r2.json", "[" * 100000)),
            ("check", shrink, "--registry", "http://registry.npmjs.org/"),
            ("check", shrink, "--registry", "https://registry.npmjs.org:99999/"),
            ("check", shrink, "--registry"),
            ("check", shrink, "--recipe"),
            ("check", shrink, "--recipe", self.write("r4.json", {"install_scripts_required": [1]})),
            ("check", shrink, "--policy", self.write("p0.json", {})),
            ("store", wrong_name, self.fx.out, "--mirror", self.fx.mirror),
            ("store", shrink, self.fx.out, "--mirror", empty_mirror),
            ("store", shrink, os.path.join(self.base, "no-out"), "--mirror", self.fx.mirror),
            ("store", shrink, self.fx.out, "--mirror", self.fx.mirror, "--policy", self.write("p1.json", [])),
            ("store", shrink, self.fx.out, "--mirror", self.fx.mirror,
             "--policy", self.write("p2.json", {"operating": {"deps_bytes": {"value": "1"}}})),
            ("store", shrink, self.fx.out, "--mirror", self.fx.mirror,
             "--policy", self.write("p3.json", {"constitutional": {"license_allowlist": "MIT"}})),
            ("store", shrink, self.fx.out, "--mirror", self.fx.mirror,
             "--policy", self.write("p4.json", {"constitutional": {"license_exceptions": {"a==1": "MIT"}}})),
            ("store", shrink, self.fx.out, "--mirror", self.fx.mirror, "--mirror", self.fx.mirror),
            ("fetch", shrink, self.fx.out, "--mirror", self.fx.mirror),
            ("verify", self.fx.out, "--registry", REG),
            ("verify", self.fx.out, "--recipe", self.write("r5.json", {})),
            ("store", shrink, self.fx.out, "--mirror", self.fx.mirror, "--address", "0" * 64),
            ("nonsense",),
            (),
        ]
        for args in cases:
            code, out = self.run_cli(*args)
            self.assertEqual(code, 2, (args, out))
            self.assertEqual(out, {"ok": False, "error": out["error"]}, args)
            self.assertFalse(out["error"].startswith("internal error"), (args, out))
        self.assertEqual(self.run_cli("check", deep)[1]["error"], "unusable input: %s: JSON nested too deeply" % deep)
        self.assertEqual(self.run_cli("check", lock)[0], 0)
        bare = self.write("r3.json", {"install_scripts_required": ["left-pad"]})
        self.assertEqual(self.run_cli("check", lock, "--recipe", bare), (1, {"ok": False,
                                                                           "reasons": ["mark_not_usable:left-pad"]}))
        code, out = self.run_cli("store", lock, self.fx.out, "--mirror", self.fx.mirror, "--recipe", bare)
        self.assertEqual((code, out["ok"], self.fx.artifacts()), (2, False, []), out)

    def test_unexpected_exception_is_exit_2_not_refusal(self):
        lock = self.fx.write_lock()
        from test_cli import MARK, run_boundary
        with mock.patch.object(N, "check", side_effect=KeyError(MARK)):
            got = run_boundary(N.main, ["check", lock], N.FAULT_LINE)
        self.assertEqual(got, (2, '{"error": "internal error", "ok": false}\n', "internal error: KeyError\n"))


def vtgz(files, gz_mtime: int = 0, top: str = "package/") -> bytes:
    """A gzip tar with a fixed gzip header (``mtime``), members under ``top`` (``files`` a dict, or a list of
    pairs for repeated names); a ``("symlink", target)`` content is a symbolic link."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w", format=tarfile.USTAR_FORMAT) as tar:
        for name, content in (files.items() if isinstance(files, dict) else files):
            info = tarfile.TarInfo(top + name)
            info.mtime = 0
            if isinstance(content, tuple):
                info.type, info.linkname = tarfile.SYMTYPE, content[1]
                tar.addfile(info)
                continue
            data = json.dumps(content).encode() if isinstance(content, dict) else content
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return gzip.compress(buf.getvalue(), mtime=gz_mtime)


def expected_address(rows: list[tuple[str, str]]) -> str:
    """Recomputed by hand: ``[{"integrity":..,"path":..}]`` sorted by path, no spaces, UTF-8."""
    def q(v):
        return json.dumps(v, ensure_ascii=False)
    body = ",".join('{"integrity":%s,"path":%s}' % (q(i), q(p)) for p, i in sorted(rows, key=lambda r: r[0]))
    return "sha256:" + hashlib.sha256(("[" + body + "]").encode("utf-8")).hexdigest()


class TestNpmlock(unittest.TestCase):
    """Group ``npmlock`` (tohum/29g): ``fetch LOCK MIRROR``, stdin ``{registry_egress, install_scripts_required}``."""

    def setUp(self):
        self.base = writable_base("npmlock-")
        self.addCleanup(shutil.rmtree, self.base, True)
        self.mirror = os.path.join(self.base, "mirror")
        os.makedirs(self.mirror)
        self.stdin = {"registry_egress": [REG], "install_scripts_required": ["gyp-thing@1.2.0"]}
        # keys deliberately not in sorted order
        self.packages = {"": {"name": "toy", "version": "1.0.0"}}
        self.add("node_modules/zeta", "zeta", "1.0.0", {"license": "MIT"})
        self.add("node_modules/@scope/util", "@scope/util", "2.0.0", {"license": "Apache-2.0"})
        self.add("node_modules/zeta/node_modules/inner", "inner", "0.1.0", {})
        self.add("node_modules/gyp-thing", "gyp-thing", "1.2.0",
                 {"license": {"type": "ISC"}, "scripts": {"postinstall": "node-gyp rebuild"}},
                 extra={"binding.gyp": b"{}"}, hasInstallScript=True)

    def add(self, key, name, version, manifest, extra=None, data=None, resolved=None, **entry):
        files = {"package.json": dict({"name": name, "version": version}, **manifest)}
        files.update(extra or {})
        data = vtgz(files) if data is None else data
        u = resolved or url(name, version)
        self.put(u, data)
        self.packages[key] = dict({"version": version, "resolved": u, "integrity": sri(data)}, **entry)
        return data

    def put(self, u, data):
        path = os.path.join(self.mirror, *u.split("://", 1)[1].split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as fh:
            fh.write(data)
        return path

    def lock_text(self, packages=None, **dump):
        return json.dumps({"name": "toy", "lockfileVersion": 3, "requires": True,
                           "packages": self.packages if packages is None else packages}, **dump)

    def write(self, text, name="package-lock.json"):
        path = os.path.join(self.base, name)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        return path

    def run_fetch(self, lock=None, mirror=None, stdin=None, raw_stdin=None, args=None):
        lock = lock if lock is not None else self.write(self.lock_text())
        argv = args if args is not None else ["fetch", lock, mirror or self.mirror]
        proc = subprocess.run([sys.executable, "-m", "runner.deps_npm", *argv], cwd=REFEREE,
                              input=raw_stdin if raw_stdin is not None else json.dumps(stdin or self.stdin),
                              capture_output=True, text=True, timeout=120)
        lines = proc.stdout.splitlines()
        self.assertEqual(len(lines), 1, proc.stdout + proc.stderr)
        self.assertEqual(proc.stderr, "")
        return proc.returncode, json.loads(lines[-1])

    def good_rows(self):
        return [(k, v["integrity"]) for k, v in self.packages.items() if k]

    def snapshot(self):
        out = {}
        for root, dirs, files in os.walk(self.base):
            for n in dirs + files:
                st = os.lstat(os.path.join(root, n))
                out[os.path.join(root, n)] = (st.st_size, st.st_mtime_ns)
        return out

    def test_integrity_good_and_one_byte(self):
        lock = self.write(self.lock_text())
        before = self.snapshot()
        code, out = self.run_fetch(lock)
        self.assertEqual(self.snapshot(), before)  # nothing written next to the lock or in the mirror
        self.assertEqual(code, 0, out)
        self.assertEqual(out, {
            "ok": True, "rejected": [], "artefact": expected_address(self.good_rows()),
            "licenses": [
                {"path": "node_modules/@scope/util", "name": "@scope/util", "version": "2.0.0",
                 "license": "Apache-2.0"},
                {"path": "node_modules/gyp-thing", "name": "gyp-thing", "version": "1.2.0", "license": None},
                {"path": "node_modules/zeta", "name": "zeta", "version": "1.0.0", "license": "MIT"},
                {"path": "node_modules/zeta/node_modules/inner", "name": "inner", "version": "0.1.0",
                 "license": None}]})
        path = os.path.join(self.mirror, "registry.npmjs.org", "zeta", "-", "zeta-1.0.0.tgz")
        with open(path, "rb") as fh:
            orig = fh.read()
        changed = bytearray(orig)
        changed[4] ^= 0x01  # gzip header MTIME byte
        self.assertEqual(gzip.decompress(bytes(changed)), gzip.decompress(orig))
        with open(path, "wb") as fh:
            fh.write(bytes(changed))
        self.assertEqual(self.run_fetch(lock), (1, {"ok": False, "rejected": ["integrity_mismatch:node_modules/zeta"],
                                                    "artefact": None, "licenses": None}))

    def test_install_script_unmarked(self):
        self.add("node_modules/post", "post", "1.0.0", {"scripts": {"postinstall": "node x.js"}})
        self.add("node_modules/pre", "pre", "1.0.0", {"scripts": {"preinstall": "node x.js"}})
        self.add("node_modules/inst", "inst", "1.0.0", {"scripts": {"install": "node x.js"}})
        self.add("node_modules/gyp", "gyp", "1.0.0", {}, extra={"binding.gyp": b"{}"})
        self.add("node_modules/flag", "flag", "1.0.0", {}, hasInstallScript=True)
        self.add("node_modules/test-only", "test-only", "1.0.0", {"scripts": {"test": "x", "prepare": "y"}})
        # post by its lock path; pre@2.0.0 and inst@2.0.0 mark nothing (another version); gyp by another's path
        stdin = dict(self.stdin, install_scripts_required=["gyp-thing@1.2.0", "node_modules/post", "pre@2.0.0",
                                                           "inst@2.0.0", "node_modules/zeta"])
        code, out = self.run_fetch(stdin=stdin)
        self.assertEqual((code, out["rejected"]), (1, ["install_script_unmarked:node_modules/%s" % n
                                                       for n in ("flag", "gyp", "inst", "pre")]))
        self.assertIsNone(out["artefact"])
        stdin["install_scripts_required"] += ["post@1.0.0", "pre@1.0.0", "inst@1.0.0", "gyp@1.0.0", "flag@1.0.0"]
        self.assertEqual(self.run_fetch(stdin=stdin)[0], 0)
        self.assertEqual(self.run_fetch(stdin=dict(self.stdin, install_scripts_required=[]))[1]["rejected"],
                         ["install_script_unmarked:node_modules/%s" % n
                          for n in ("flag", "gyp", "gyp-thing", "inst", "post", "pre")])

    def test_registry_not_allowed(self):
        for i, host in enumerate(("registry.npmjs.org.evil.com", "registry.npmjs.orgx")):
            self.add("node_modules/look%d" % i, "look%d" % i, "1.0.0", {},
                     resolved="https://%s/look%d/-/look%d-1.0.0.tgz" % (host, i, i))
        self.add("node_modules/plain", "plain", "1.0.0", {},
                 resolved="http://registry.npmjs.org/plain/-/plain-1.0.0.tgz")
        self.add("node_modules/upper", "upper", "1.0.0", {},
                 resolved="https://Registry.npmjs.org/upper/-/upper-1.0.0.tgz")
        code, out = self.run_fetch()
        self.assertEqual((code, out["rejected"]), (1, ["registry_not_allowed:node_modules/%s" % n
                                                       for n in ("look0", "look1", "plain", "upper")]))
        # the same tarballs pass once their registry is allowed: only the prefix stopped them
        stdin = dict(self.stdin, registry_egress=[REG, "https://registry.npmjs.org.evil.com/",
                                                  "https://registry.npmjs.orgx/", "https://Registry.npmjs.org/"])
        code, out = self.run_fetch(stdin=stdin)
        self.assertEqual(out["rejected"], ["registry_not_allowed:node_modules/plain"])
        # a path prefix is a prefix of the whole URL, '/' included
        del self.packages["node_modules/plain"], self.packages["node_modules/upper"]
        del self.packages["node_modules/look0"], self.packages["node_modules/look1"]
        self.add("node_modules/sub", "sub", "1.0.0", {},
                 resolved="https://npm.example/registry-evil/sub/-/sub-1.0.0.tgz")
        self.add("node_modules/ok", "ok", "1.0.0", {}, resolved="https://npm.example/registry/ok/-/ok-1.0.0.tgz")
        stdin = dict(self.stdin, registry_egress=[REG, "https://npm.example/registry/"])
        self.assertEqual(self.run_fetch(stdin=stdin)[1]["rejected"], ["registry_not_allowed:node_modules/sub"])

    def test_git_dependency_and_file_dependency_even_with_integrity(self):
        integrity = self.packages["node_modules/zeta"]["integrity"]
        git = {"g1": "git+ssh://git@github.com/a/b.git#0123", "g2": "git://github.com/a/b.git", "g3": "github:a/b",
               "g4": "git@github.com:a/b.git"}
        files = {"f1": ({"resolved": "file:../local.tgz"}), "f2": {"resolved": "../outside", "link": True},
                 "f3": {"resolved": "/abs/pkg", "link": True}, "f4": {"resolved": "C:\\pkg", "link": True},
                 "f5": {"resolved": "packages/a/../../x", "link": True}}
        for n, u in git.items():
            self.packages["node_modules/" + n] = {"version": "1.0.0", "resolved": u, "integrity": integrity}
        for n, e in files.items():
            self.packages["node_modules/" + n] = dict({"version": "1.0.0", "integrity": integrity}, **e)
        code, out = self.run_fetch()
        self.assertEqual(code, 1)
        self.assertEqual(out["rejected"], sorted(["file_dependency:node_modules/%s" % n for n in files]
                                                 + ["git_dependency:node_modules/%s" % n for n in git]))
        # not a git or file dependency, but nothing of theirs comes from an allowed registry: refused there; an
        # in-tree link is a workspace link (29g), so it and the folder it names are not checked
        self.packages = {"": {}, "node_modules/inside": {"resolved": "packages/a", "link": True},
                         "packages/a": {"name": "a", "version": "1.0.0"},
                         "node_modules/zeta/node_modules/bundled": {"version": "1.0.0", "inBundle": True},
                         "node_modules/upper": {"version": "1.0.0", "resolved": "GIT+https://x/y.git"}}
        self.assertEqual(self.run_fetch()[1]["rejected"], [
            "registry_not_allowed:node_modules/upper", "registry_not_allowed:node_modules/zeta/node_modules/bundled"])

    def test_license_from_tarball(self):
        self.packages["node_modules/zeta"]["license"] = "GPL-3.0"
        self.add("node_modules/copyleft", "copyleft", "3.0.0", {"license": "AGPL-3.0-only"}, license="MIT")
        self.add("node_modules/nolicense", "nolicense", "1.0.0", {}, license="MIT")
        code, out = self.run_fetch()
        self.assertEqual(code, 0, out)  # a report, not a gate
        lic = {r["path"]: r["license"] for r in out["licenses"]}
        self.assertEqual((lic["node_modules/zeta"], lic["node_modules/copyleft"], lic["node_modules/nolicense"]),
                         ("MIT", "AGPL-3.0-only", None))
        self.assertEqual([r["path"] for r in out["licenses"]], sorted(r["path"] for r in out["licenses"]))

    def test_tarball_members_and_mirror_entries(self):
        body = json.dumps({"name": "edge", "version": "1.0.0"}).encode()
        self.add("node_modules/edge", "edge", "1.0.0", {}, data=vtgz({"package.json": body + b" " * ((1 << 20) - len(body))}))
        self.add("node_modules/dotted", "dotted", "1.0.0", {}, data=vtgz(
            {"package.json": {"name": "dotted", "version": "1.0.0"}, "binding.gyp": b"{}"}, top="./package/"))
        self.add("node_modules/named", "named", "1.0.0", {}, data=vtgz({"package.json": {"name": 5, "version": 7}}))
        self.packages["node_modules/loose"] = {"version": "1.0.0", "resolved": "../loose", "link": "true"}
        os.makedirs(os.path.join(self.mirror, "registry.npmjs.org", "dir", "-", "dir-1.0.0.tgz"))
        self.packages["node_modules/dir"] = {"version": "1.0.0", "resolved": url("dir", "1.0.0"),
                                             "integrity": sri(b"x")}
        code, out = self.run_fetch()
        self.assertEqual((code, out["rejected"]), (1, ["install_script_unmarked:node_modules/dotted",
                                                       "registry_not_allowed:node_modules/loose",
                                                       "tarball_missing:node_modules/dir"]))
        del self.packages["node_modules/loose"], self.packages["node_modules/dir"]
        code, out = self.run_fetch(stdin=dict(self.stdin, install_scripts_required=["gyp-thing@1.2.0",
                                                                                    "dotted@1.0.0"]))
        self.assertEqual(code, 0, out)
        lic = {r["path"]: (r["name"], r["version"]) for r in out["licenses"]}
        self.assertEqual((lic["node_modules/named"], lic["node_modules/edge"]), ((None, None), ("edge", "1.0.0")))

    def test_fetch_takes_no_option_even_when_it_names_a_path(self):
        """``fetch`` refuses an argument that starts with ``--`` even where a file of that name exists."""
        shutil.copy(self.write(self.lock_text()), os.path.join(self.base, "--lock"))
        shutil.copytree(self.mirror, os.path.join(self.base, "--mirror"))
        cwd = os.getcwd()
        os.chdir(self.base)
        self.addCleanup(os.chdir, cwd)
        for argv, code in ((["fetch", "package-lock.json", "--mirror"], 2), (["fetch", "--lock", "mirror"], 2),
                           (["fetch", "package-lock.json", "mirror"], 0)):
            out = io.StringIO()
            stdin = io.TextIOWrapper(io.BytesIO(json.dumps(self.stdin).encode()))
            with mock.patch.object(sys, "stdin", stdin), mock.patch.object(sys, "stdout", out):
                self.assertEqual(N.main(argv), code, (argv, out.getvalue()))

    def test_mirror_file_is_taken_literally(self):
        m = self.mirror
        self.assertEqual(N._mirror_file(m, "https://h.example/a/-/a-1.0.0.tgz"),
                         os.path.join(m, "h.example", "a", "-", "a-1.0.0.tgz"))
        for resolved in ("http://h.example/a.tgz", "h.example/a.tgz", "https://h.example//a.tgz",
                         "https://h.example/./a.tgz", "https://h.example/../a.tgz", "https://h.example/a/",
                         "https://h.example/a\\..\\b.tgz", "https://h.example/a\0.tgz"):
            self.assertIsNone(N._mirror_file(m, resolved), resolved)

    def test_address_is_utf8_not_escaped(self):
        self.add("node_modules/\u00fcber", "\u00fcber", "1.0.0", {})
        code, out = self.run_fetch()
        self.assertEqual(code, 0, out)
        self.assertEqual(out["artefact"], expected_address(self.good_rows()))

    def test_same_lock_same_address(self):
        code, out = self.run_fetch(self.write(self.lock_text(indent=2)))
        self.assertEqual(code, 0, out)
        self.assertEqual(out["artefact"], expected_address(self.good_rows()))
        reordered = {k: dict(reversed(list(v.items()))) for k, v in reversed(list(self.packages.items()))}
        compact = json.dumps({"packages": reordered, "requires": True, "lockfileVersion": 3, "name": "toy"},
                             separators=(",", ":"))
        self.assertEqual(self.run_fetch(self.write(compact, "other.json"))[1]["artefact"], out["artefact"])
        # another tarball for one package: another integrity, another address
        self.add("node_modules/zeta", "zeta", "1.0.0", {"license": "MIT", "description": "changed"})
        code, out2 = self.run_fetch()
        self.assertEqual(code, 0, out2)
        self.assertNotEqual(out2["artefact"], out["artefact"])
        self.assertEqual(out2["artefact"], expected_address(self.good_rows()))

    def test_first_failing_check_is_the_reason_in_order(self):
        bad = "sha512-" + base64.b64encode(hashlib.sha512(b"other").digest()).decode()
        script = {"scripts": {"postinstall": "x"}}
        self.packages.update({
            "node_modules/a": {"version": "1.0.0", "resolved": "git+file:../a", "link": True, "integrity": bad},
            "node_modules/b": {"version": "1.0.0", "resolved": "file:../b", "integrity": bad},
            "node_modules/c": {"version": "1.0.0", "resolved": "../c", "link": True, "integrity": bad},
            "node_modules/d": {"version": "1.0.0", "resolved": "https://other.example/d/-/d-1.0.0.tgz",
                               "integrity": bad, "hasInstallScript": True},
            "node_modules/e": {"version": "1.0.0", "resolved": url("e", "1.0.0"), "integrity": bad,
                               "hasInstallScript": True},
        })
        self.put("https://other.example/d/-/d-1.0.0.tgz", vtgz({"package.json": {"name": "d", "version": "1.0.0"}}))
        self.add("node_modules/f", "f", "1.0.0", script)
        self.packages["node_modules/f"]["integrity"] = bad
        self.add("node_modules/g", "g", "1.0.0", script)
        # an on-registry URL that climbs out of the mirror cannot be in it, even where the file exists
        escape = REG + "../../secret.tgz"
        data = vtgz({"package.json": {"name": "h", "version": "1.0.0"}})
        with open(os.path.join(self.base, "secret.tgz"), "wb") as fh:
            fh.write(data)
        self.packages["node_modules/h"] = {"version": "1.0.0", "resolved": escape, "integrity": sri(data)}
        code, out = self.run_fetch()
        self.assertEqual((code, out["rejected"]), (1, [
            "file_dependency:node_modules/b", "file_dependency:node_modules/c", "git_dependency:node_modules/a",
            "install_script_unmarked:node_modules/g", "integrity_mismatch:node_modules/f",
            "registry_not_allowed:node_modules/d", "tarball_missing:node_modules/e",
            "tarball_missing:node_modules/h"]))

    def workspace(self, link=None, folder=None):
        """``node_modules/@acme/ui`` links ``libs/ui``; a nested package under it; the folder has no resolved."""
        self.packages[""]["workspaces"] = ["libs/ui"]
        self.packages["node_modules/@acme/ui"] = dict({"resolved": "libs/ui", "link": True}, **(link or {}))
        self.packages["libs/ui"] = dict({"name": "@acme/ui", "version": "1.0.0"}, **(folder or {}))
        self.add("libs/ui/node_modules/deep", "deep", "4.0.0", {"license": "MIT"})

    def test_workspaces_lock(self):
        self.workspace(folder={"hasInstallScript": True, "resolved": "https://evil.example/x.tgz"})
        code, out = self.run_fetch()
        self.assertEqual(code, 0, out)
        rows = [(k, v["integrity"]) for k, v in self.packages.items() if "integrity" in v]
        self.assertIn("libs/ui/node_modules/deep", [r[0] for r in rows])
        self.assertEqual(out["artefact"], expected_address(rows))
        self.assertEqual([r["path"] for r in out["licenses"]], sorted(r[0] for r in rows))

    def test_workspace_folder_needs_its_link(self):
        self.workspace(link={"link": False})
        code, out = self.run_fetch()
        self.assertEqual((code, out["rejected"]), (1, ["registry_not_allowed:libs/ui",
                                                       "registry_not_allowed:node_modules/@acme/ui"]))

    def test_the_exemption_ends_at_the_link_and_its_folder(self):
        self.workspace()
        deep = self.packages["libs/ui/node_modules/deep"]
        deep["resolved"] = deep["resolved"].replace("registry.npmjs.org", "mirror.example.invalid")
        self.assertEqual(self.run_fetch()[1]["rejected"], ["registry_not_allowed:libs/ui/node_modules/deep"])
        self.packages["libs/ui/node_modules/deep"]["resolved"] = url("deep", "4.0.0")
        self.packages["libs/other"] = {"name": "other", "version": "1.0.0"}  # a folder no link names
        self.assertEqual(self.run_fetch()[1]["rejected"], ["registry_not_allowed:libs/other"])

    def test_which_links_are_workspace_links(self):
        """``resolved`` in the repository: non-empty, not absolute, no ``..`` component, no ``:``; the folder is
        compared as written and has no ``node_modules`` component."""
        for resolved, rejected in (
                ("libs/a..b", ["registry_not_allowed:libs/ui"]),            # a link; the folder it names is not libs/ui
                ("./libs/ui", ["registry_not_allowed:libs/ui"]),            # as written
                ("../libs/ui", ["file_dependency:node_modules/@acme/ui", "registry_not_allowed:libs/ui"]),
                ("libs\\..\\ui", ["file_dependency:node_modules/@acme/ui", "registry_not_allowed:libs/ui"]),
                ("/libs/ui", ["file_dependency:node_modules/@acme/ui", "registry_not_allowed:libs/ui"]),
                ("C:libs", ["file_dependency:node_modules/@acme/ui", "registry_not_allowed:libs/ui"]),
                ("a:b", ["file_dependency:node_modules/@acme/ui", "registry_not_allowed:libs/ui"]),  # a drive
                ("ab:c", ["registry_not_allowed:libs/ui", "registry_not_allowed:node_modules/@acme/ui"]),
                ("", ["registry_not_allowed:libs/ui", "registry_not_allowed:node_modules/@acme/ui"])):
            self.setUp()
            self.workspace(link={"resolved": resolved})
            self.assertEqual(self.run_fetch()[1]["rejected"], rejected, resolved)
        self.setUp()  # a link into node_modules is a link; the entry it names is no folder and is checked
        self.workspace(link={"resolved": "node_modules/zeta"})
        self.packages["node_modules/zeta"]["resolved"] = "https://mirror.example.invalid/zeta.tgz"
        self.assertEqual(self.run_fetch()[1]["rejected"], ["registry_not_allowed:libs/ui",
                                                           "registry_not_allowed:node_modules/zeta"])

    def test_integrity_reads_the_sha512_tokens(self):
        zeta = self.packages["node_modules/zeta"]
        data_sha1 = "sha1-" + base64.b64encode(hashlib.sha1(b"x").digest()).decode()
        for integrity, ok in ((zeta["integrity"] + " " + data_sha1, True),
                              (sri(b"x", "sha256") + " " + zeta["integrity"], True),
                              (zeta["integrity"].replace("sha512", "sha256"), False),
                              (data_sha1, False), ("", False), (None, False),
                              (zeta["integrity"] + " " + sri(b"x"), False)):
            if integrity is None:
                zeta.pop("integrity", None)
            else:
                zeta["integrity"] = integrity
            code, out = self.run_fetch()
            self.assertEqual(code, 0 if ok else 1, (integrity, out))
            if not ok:
                self.assertEqual(out["rejected"], ["integrity_mismatch:node_modules/zeta"])

    def test_store_prints_the_same_artefact(self):
        lock = self.write(self.lock_text())
        out_dir = os.path.join(self.base, "out")
        os.mkdir(out_dir)
        proc = subprocess.run([sys.executable, "-m", "runner.deps_npm", "store", lock, out_dir, "--mirror", self.mirror,
                               "--recipe", self.write(json.dumps(self.stdin), "units.json")],
                              cwd=REFEREE, input="", capture_output=True, text=True, timeout=120)
        stored = json.loads(proc.stdout.splitlines()[-1])
        self.assertEqual(proc.returncode, 0, stored)
        self.assertEqual(stored["artefact"], self.run_fetch(lock)[1]["artefact"])
        self.assertEqual(os.listdir(out_dir), [stored["address"]])

    def test_marks_are_lock_keys_or_name_at_version(self):
        self.add("node_modules/post", "post", "1.0.0", {"scripts": {"postinstall": "node x.js"}})
        self.add("node_modules/zeta/node_modules/post", "post", "2.0.0", {"scripts": {"postinstall": "x"}})
        # a nested lock key marks only its entry; name@version marks every entry of that name and version
        code, out = self.run_fetch(stdin=dict(self.stdin, install_scripts_required=[
            "gyp-thing@1.2.0", "node_modules/zeta/node_modules/post"]))
        self.assertEqual((code, out["rejected"]), (1, ["install_script_unmarked:node_modules/post"]))
        for marks in (["node_modules/gyp-thing", "post@1.0.0", "post@2.0.0"],
                      ["node_modules/gyp-thing", "node_modules/post", "node_modules/zeta/node_modules/post",
                       "left-pad@1.3.0"]):
            self.assertEqual(self.run_fetch(stdin=dict(self.stdin, install_scripts_required=marks))[0], 0, marks)
        # name@version is read from the tarball, as 29g says (the lock's own version field is not the mark)
        self.packages["node_modules/post"]["version"] = "9.9.9"
        code, out = self.run_fetch(stdin=dict(self.stdin, install_scripts_required=[
            "gyp-thing@1.2.0", "post@9.9.9", "post@2.0.0"]))
        self.assertEqual((code, out["rejected"]), (1, ["install_script_unmarked:node_modules/post"]))

    def test_an_element_that_is_not_a_mark_is_exit_2_and_nothing_is_read(self):
        # a corrupt tarball: had anything been read, the answer would be integrity_mismatch (exit 1)
        self.put(url("zeta", "1.0.0"), b"corrupt")
        for bad in ("zeta", "left-pad", "@scope/util", "node_modules/left-pad", "node_modules/zeta/",
                    "", "zeta@^1.0.0", "zeta@latest", "zeta@", "@1.0.0", "zeta@1.0"):
            code, out = self.run_fetch(stdin=dict(self.stdin, install_scripts_required=["gyp-thing@1.2.0", bad]))
            self.assertEqual((code, out), (2, {"ok": False, "error": out["error"]}), bad)
        code, out = self.run_fetch(stdin=dict(self.stdin, install_scripts_required=["gyp-thing@1.2.0",
                                                                                    "node_modules/zeta"]))
        self.assertEqual((code, out["rejected"]), (1, ["integrity_mismatch:node_modules/zeta"]))

    def test_unusable_input_is_exit_2(self):
        good = self.lock_text()
        not_dir = self.write("x", "file")
        cases = [
            dict(lock=os.path.join(self.base, "missing.json")),
            dict(lock=self.base),
            dict(lock=self.write("{", "l1.json")),
            dict(lock=self.write(json.dumps({"lockfileVersion": 2, "packages": self.packages}), "l2.json")),
            dict(lock=self.write(good.replace('"lockfileVersion": 3', '"lockfileVersion": 3.0'), "l3.json")),
            dict(lock=self.write(json.dumps({"lockfileVersion": 3, "packages": []}), "l4.json")),
            dict(lock=self.write(json.dumps({"lockfileVersion": 3, "packages": {"node_modules/a": "x"}}), "l5.json")),
            dict(lock=self.write("[" * 100000, "l6.json")),
            dict(mirror=os.path.join(self.base, "no-mirror")),
            dict(mirror=not_dir),
            dict(raw_stdin=""),
            dict(raw_stdin="{"),
            dict(raw_stdin="[]"),
            dict(stdin={"registry_egress": ["https://registry.npmjs.org/r"], "install_scripts_required": []}),
            dict(stdin={"registry_egress": [REG]}),
            dict(stdin={"registry_egress": ["https://registry.npmjs.org"], "install_scripts_required": []}),
            dict(stdin={"registry_egress": ["http://registry.npmjs.org/"], "install_scripts_required": []}),
            dict(stdin={"registry_egress": [REG], "install_scripts_required": [1]}),
            dict(args=["fetch", self.write(good, "l7.json")]),
            dict(args=["fetch", self.write(good, "l8.json"), self.base, "--mirror", self.mirror]),
            dict(args=["fetch", self.write(good, "l9.json"), self.mirror, "extra"]),
            dict(args=["fetch", "--mirror", self.mirror]),
        ]
        for case in cases:
            code, out = self.run_fetch(**case)
            self.assertEqual(code, 2, (case, out))
            self.assertEqual(out, {"ok": False, "error": out["error"]}, case)
            self.assertFalse(out["error"].startswith("internal error"), (case, out))
        # a tarball that matches its integrity but cannot be read: no verdict, not a pass
        body = json.dumps({"name": "big", "version": "1.0.0"}).encode()
        for name, data in (("raw", b"not gzip"), ("nopkg", vtgz({"index.js": b"x"})),
                           ("badjson", vtgz({"package.json": b"{"})), ("array", vtgz({"package.json": b"[1]"})),
                           ("big", vtgz({"package.json": body + b" " * ((1 << 20) + 1 - len(body))})),
                           ("link", vtgz({"package.json": ("symlink", "/etc/passwd")})),
                           ("two", vtgz([("package.json", {"name": "two", "version": "1.0.0"}),
                                         ("package.json", {"name": "two", "version": "1.0.0"})]))):
            packages = {"": {}}
            self.packages = packages
            self.add("node_modules/" + name, name, "1.0.0", {}, data=data)
            code, out = self.run_fetch()
            self.assertEqual((code, out), (2, {"ok": False, "error": out["error"]}), (name, out))
        if hasattr(os, "geteuid") and os.geteuid() != 0:
            self.packages = {"": {}}
            path = self.put(url("zeta", "1.0.0"), b"x")
            self.add("node_modules/zeta", "zeta", "1.0.0", {})
            os.chmod(path, 0)
            self.assertEqual(self.run_fetch()[0], 2)


if __name__ == "__main__":
    unittest.main()
