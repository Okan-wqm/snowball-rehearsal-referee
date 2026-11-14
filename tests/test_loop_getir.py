"""Test 46 (asama-0/09), MF17, D2 -> D3: the ``getir`` job over the ``pulled`` artifact (``loop.job run getir``) and
the hand-over of its ``deps`` artifact to ``kos`` (``runner.deps_npm.artifact_in``), tarballs served by a mirror
directory (the sandbox has no network; the HTTPS fetch is asama-0/10a #getir), ``kos`` with the fake runner.

- the job, per served target ``<id>`` (``in/pulled/<id>``): the recipe's lock in the pulled tree is fetched by MF5
  into ``$RUNNER_TEMP/out/deps/<id>/<address>/``, which MF5's ``verify`` takes; the line's ``targets`` entry
  ``{target: <id>, ...}`` carries the address, the counts and the license report; exit 0 and ``ok`` true; with two
  served targets each is fetched into its own ``out/deps/<id>/``, in the served order;
- the hand-over: ``out/deps``, downloaded whole as ``in/deps``, is installed by ``kos`` from ``in/deps/<id>`` (the
  unit's test reads the unpacked package): a change to one target's ``in/deps/<id>`` is that target's alone, and
  ``out/deps`` laid out without the ``<id>/`` level is not read; a changed tarball byte after the hand-over is
  MF5's ``tarball_mismatch``; an ``in/deps/<id>`` that is not exactly one ``<address>/`` directory runs nothing
  (``deps_invalid``);
- refusals before and during the fetch: a refused artifact, two units, an unsafe tree and a recipe the static check
  refuses fetch nothing; a git dependency, a changed tarball byte and the recipe's ``limits.deps_bytes`` are MF5's
  refusals (``deps_refused``), nothing written; a failed fetch and an existing ``out/deps/<id>`` are no verdict.
"""

from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
import unittest

REFEREE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REFEREE)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from loop import job as J  # noqa: E402
from loop import pulled as P  # noqa: E402
from runner import deps_npm as N  # noqa: E402
from profile_tree import write_tree  # noqa: E402
from test_deps_npm import Fixture  # noqa: E402
from test_kos import operating, recipe  # noqa: E402
from test_loop_kos import TREE, Base, RedAs, tar_of  # noqa: E402

# The unit's test passes only when the dependency was installed next to the lock, as kos's staging puts it.
USES_DEP = r'''import json, sys
try:
    ok = json.load(open("pkg/node_modules/left-pad/package.json"))["version"] == "1.3.0"
except OSError:
    ok = False
print("TAP version 13")
print(("ok" if ok else "not ok") + " 1 - left-pad installed")
print("1..1")
sys.exit(0 if ok else 1)
'''


class Getir(Base):
    def setUp(self) -> None:
        super().setUp()
        self.fx = Fixture(os.path.join(self.base, "npm"))
        self.fx.lock["name"] = "pkg"
        self.fx.lock["packages"][""] = {"name": "pkg", "version": "1.0.0"}
        self.fx.add("left-pad", "1.3.0")
        self.write_lock()
        self.fetched: list[str] = []
        self.deps = os.path.join(self.temp, "out", "deps")  # getir's artifact: one <id>/ per served target
        self.out = os.path.join(self.deps, "t1")

    def write_lock(self) -> None:
        write_tree(self.src, {"pkg/package-lock.json": self.fx.lock, "pkg/run_tests.py": USES_DEP})

    def fetcher(self, url, cap):
        self.fetched.append(url)
        return N.mirror_fetcher(self.fx.mirror)(url, cap)

    def run_getir(self, env=None) -> dict:
        return J.run("getir", dict({"RUNNER_TEMP": self.temp}, **(env or {})), fetcher=self.fetcher)

    def hand_over(self) -> str:
        """The upload of ``out/deps`` and its download as ``in/deps``: the directory copied whole; t1's part,
        ``in/deps/t1``, is returned."""
        dest = os.path.join(self.temp, "in", "deps")
        shutil.copytree(self.deps, dest, symlinks=True)
        return os.path.join(dest, "t1")

    def one(self, out: dict) -> dict:
        """The line's one target, ``t1``: its entry of ``targets``."""
        self.assertEqual([t["target"] for t in out["targets"]], ["t1"])
        return out["targets"][0]

    def run_kos(self, runner=None, env=None) -> dict:
        return J.run("kos", dict({"RUNNER_TEMP": self.temp}, **(env or {})), runner=runner or RedAs())


class Fetch(Getir):
    def test_the_lock_is_fetched_into_one_artifact_that_verifies(self):
        self.write_pulled()
        line = self.run_getir()
        out = self.one(line)
        self.assertEqual((line["ok"], line["job"], "reason" in line), (True, "getir", False))
        self.assertEqual((out["ok"], out["done"], "reason" in out), (True, ["D2"], False))
        address = out["deps"]["address"]
        self.assertEqual(os.listdir(self.deps), ["t1"])
        self.assertEqual(os.listdir(self.out), [address])
        self.assertEqual(N.verify(os.path.join(self.out, address)), {"ok": True, "reasons": [], "address": address})
        self.assertEqual(N.artifact_in(self.out), os.path.join(self.out, address))
        self.assertEqual((out["deps"]["packages"], out["deps"]["bytes"]),
                         (1, len(self.fx.blobs[self.fx.lock["packages"]["node_modules/left-pad"]["resolved"]])))
        self.assertEqual(out["licenses"], [{"key": "node_modules/left-pad", "name": "left-pad", "version": "1.3.0",
                                            "license": ["MIT"], "allowed": True}])
        self.assertEqual(self.fetched, [self.fx.lock["packages"]["node_modules/left-pad"]["resolved"]])
        # the lock copy in the artifact is the tree's lock, byte for byte
        with open(os.path.join(self.out, address, "package-lock.json"), "rb") as fh:
            with open(os.path.join(self.src, "pkg/package-lock.json"), "rb") as src:
                self.assertEqual(fh.read(), src.read())

    def test_a_lock_without_packages_gives_an_artifact_with_none(self):
        write_tree(self.src, {"pkg/package-lock.json": TREE["pkg/package-lock.json"]})
        self.write_pulled()
        line = self.run_getir()
        out = self.one(line)
        self.assertEqual((line["ok"], out["ok"], out["deps"]["packages"], out["licenses"], self.fetched),
                         (True, True, 0, [], []))
        self.assertTrue(N.verify(N.artifact_in(self.out))["ok"])

    def test_the_cli_exits_0_when_the_job_is_done(self):
        write_tree(self.src, {"pkg/package-lock.json": TREE["pkg/package-lock.json"]})
        self.write_pulled()
        env = {k: v for k, v in os.environ.items() if k not in J.SECRET_ENV + J.OIDC_ENV}
        proc = subprocess.run([sys.executable, "-m", "loop.job", "run", "getir"], cwd=REFEREE, capture_output=True,
                              env=dict(env, RUNNER_TEMP=self.temp))
        out = json.loads(proc.stdout)
        self.assertEqual((proc.returncode, out["ok"], self.one(out)["done"]), (0, True, ["D2"]), proc.stderr)


class HandOver(Getir):
    def test_kos_installs_what_getir_fetched(self):
        self.write_pulled()
        self.assertTrue(self.run_getir()["ok"])
        self.hand_over()
        line = self.run_kos()
        out = self.one(line)
        self.assertEqual(out["index"]["base"], {"verdict": "verified", "reasons": []})
        self.assertEqual((line["ok"], out["ok"], out["done"]), (True, True, ["D3"]))

    def test_without_the_artifact_kos_has_no_verdict(self):
        # the same tree with no in/deps: a lock with packages and no artifact is unusable input for kos
        self.write_pulled()
        self.assertTrue(self.run_getir()["ok"])
        with self.assertRaises(J.Unusable):
            self.run_kos()

    def test_a_changed_tarball_byte_after_the_hand_over(self):
        self.write_pulled()
        self.run_getir()
        dest = N.artifact_in(self.hand_over())
        tarballs = os.path.join(dest, "tarballs")
        path = os.path.join(tarballs, os.listdir(tarballs)[0])
        with open(path, "r+b") as fh:
            first = fh.read(1)
            fh.seek(0)
            fh.write(bytes([first[0] ^ 1]))
        out = self.one(self.run_kos())
        self.assertEqual(out["index"]["base"]["verdict"], "no_verdict")
        self.assertEqual(out["index"]["base"]["reasons"], ["deps:tarball_mismatch:node_modules/left-pad"])

    def test_a_root_that_is_not_one_address_directory_runs_nothing(self):
        self.write_pulled()
        self.run_getir()
        address = os.listdir(self.out)[0]

        def extra(root):
            write_tree(root, {"licenses.json": "[]"})

        def renamed(root):
            os.rename(os.path.join(root, address), os.path.join(root, address.upper()))

        def flattened(root):
            inner = os.path.join(root, address)
            for name in os.listdir(inner):
                shutil.move(os.path.join(inner, name), os.path.join(root, name))
            os.rmdir(inner)

        def linked(root):
            shutil.move(os.path.join(root, address), os.path.join(self.base, address))
            os.symlink(os.path.join(self.base, address), os.path.join(root, address))

        def a_file(root):
            shutil.rmtree(os.path.join(root, address))
            write_tree(root, {address: "x"})

        for change in (extra, renamed, flattened, linked, a_file):
            with self.subTest(change=change.__name__):
                shutil.rmtree(os.path.join(self.temp, "in", "deps"), ignore_errors=True)
                shutil.rmtree(os.path.join(self.base, address), ignore_errors=True)
                change(self.hand_over())
                runner = RedAs()
                out = self.run_kos(runner)
                self.assertEqual((out["ok"], out["reason"], out["target"]), (False, "deps_invalid", "t1"))
                self.assertEqual(self.one(out)["reason"], "deps_invalid")
                self.assertEqual(runner.calls, [])
                self.assertFalse(os.path.exists(os.path.join(self.temp, "out", "results")))


class Refusals(Getir):
    def assert_nothing_fetched(self, out, reason, reasons=None):
        self.assertEqual((out["ok"], out["reason"], out["target"]), (False, reason, "t1"))
        self.assertEqual((self.one(out)["ok"], self.one(out)["reason"]), (False, reason))
        if reasons is not None:
            self.assertEqual(out["reasons"], reasons)
        self.assertEqual(self.fetched, [])
        self.assertFalse(os.path.exists(self.deps) and os.listdir(self.deps))

    def test_a_refused_artifact_two_units_or_an_unsafe_tree_fetch_nothing(self):
        self.write_pulled()
        with open(os.path.join(self.pulled, "units.json"), "ab") as fh:
            fh.write(b" ")
        self.assert_nothing_fetched(self.run_getir(), "pulled_invalid", ["hash_mismatch:units.json"])
        shutil.rmtree(self.temp)
        self.write_pulled(units={"units": [recipe(), recipe(unit_id="b")]})
        self.assert_nothing_fetched(self.run_getir(), "units_not_one")
        shutil.rmtree(self.temp)
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w") as tar:
            info = tarfile.TarInfo("pkg/link")
            info.type, info.linkname = tarfile.SYMTYPE, "../../../etc"
            tar.addfile(info)
        self.write_pulled(tree_tar=buf.getvalue())
        self.assert_nothing_fetched(self.run_getir(), "pulled_invalid", ["tree_unsafe"])

    def test_a_recipe_the_static_check_refuses_fetches_nothing(self):
        for units, reason in (({"units": [recipe(lockfiles=["pkg/npm-shrinkwrap.json"])]}, "lockfile_missing"),
                              ({"units": [recipe(services=["db"])]}, "services_not_empty"),
                              ({"units": [recipe(install_scripts_required=["left-pad"])]},
                               "lock:mark_not_usable:left-pad")):
            with self.subTest(reason=reason):
                shutil.rmtree(self.temp, ignore_errors=True)
                self.fetched = []
                self.write_pulled(units=units)
                out = self.run_getir()
                self.assert_nothing_fetched(out, "recipe_refused")
                self.assertIn(reason, out["reasons"])

    def test_a_git_dependency_is_refused_before_any_fetch(self):
        self.fx.lock["packages"]["node_modules/gitdep"] = {"version": "1.0.0", "resolved": "git+https://x/y.git"}
        self.write_lock()
        self.write_pulled()
        out = self.run_getir()
        # the static check reads the same lock with MF5's check, so the recipe is refused first
        self.assert_nothing_fetched(out, "recipe_refused")
        self.assertIn("lock:git_dependency:node_modules/gitdep", out["reasons"])

    def test_a_changed_tarball_byte_at_the_registry(self):
        self.fx.put(self.fx.lock["packages"]["node_modules/left-pad"]["resolved"], b"not the tarball")
        self.write_pulled()
        out = self.run_getir()
        self.assertEqual((out["ok"], out["reason"], out["reasons"], out["target"]),
                         (False, "deps_refused", ["integrity_mismatch:node_modules/left-pad"], "t1"))
        self.assertEqual(self.one(out)["reason"], "deps_refused")
        self.assertEqual((os.listdir(self.deps), os.listdir(self.out)), (["t1"], []))

    def test_the_recipes_deps_bytes_tightens_the_operators(self):
        size = len(self.fx.blobs[self.fx.lock["packages"]["node_modules/left-pad"]["resolved"]])
        for limit, ok in ((size - 1, False), (size, True)):
            with self.subTest(limit=limit):
                shutil.rmtree(self.temp, ignore_errors=True)
                self.write_pulled(units={"units": [recipe(limits={"deps_bytes": limit})]})
                out = self.run_getir()
                self.assertEqual((out["ok"], self.one(out)["ok"]), (ok, ok), out)
                if not ok:
                    self.assertEqual((out["reason"], out["reasons"]), ("deps_refused", ["limit_hit:deps_bytes"]))
        # the operator's value binds when the recipe sets none
        ops = operating()
        ops["deps_bytes"]["value"] = size - 1
        shutil.rmtree(self.temp, ignore_errors=True)
        self.write_pulled(policy={"operating": ops})
        self.assertEqual(self.run_getir()["reasons"], ["limit_hit:deps_bytes"])

    def test_a_failed_fetch_and_an_existing_output_are_no_verdict(self):
        self.write_pulled()
        os.remove(os.path.join(self.fx.mirror, "registry.npmjs.org", "left-pad", "-", "left-pad-1.3.0.tgz"))
        with self.assertRaises(J.Unusable):
            self.run_getir()
        shutil.rmtree(self.temp)
        self.fetched = []
        self.write_pulled()
        os.makedirs(self.out)
        with self.assertRaises(J.Unusable):
            self.run_getir()
        self.assertEqual(self.fetched, [])


class Targets(Getir):
    """Two served targets, t2 before t1 (served.json's order), the same lock in each pulled tree."""

    def setUp(self) -> None:
        super().setUp()
        root = os.path.dirname(self.pulled)
        os.makedirs(root)
        P.write_served(root, ["t2", "t1"])
        self.write_pulled_as("t1")
        self.write_pulled_as("t2")

    def test_each_served_target_gets_its_own_deps(self):
        line = self.run_getir()
        self.assertEqual((line["ok"], line.get("reason")), (True, None))
        self.assertEqual([(t["target"], t["ok"], t["done"]) for t in line["targets"]],
                         [("t2", True, ["D2"]), ("t1", True, ["D2"])])
        self.assertEqual(sorted(os.listdir(self.deps)), ["t1", "t2"])
        for entry in line["targets"]:
            address = entry["deps"]["address"]
            here = os.path.join(self.deps, entry["target"])
            self.assertEqual(os.listdir(here), [address])
            self.assertEqual(N.verify(os.path.join(here, address))["ok"], True)
            self.assertEqual(N.artifact_in(here), os.path.join(here, address))
        resolved = self.fx.lock["packages"]["node_modules/left-pad"]["resolved"]
        self.assertEqual(self.fetched, [resolved, resolved])

    def test_kos_reads_each_targets_own_deps(self):
        self.assertTrue(self.run_getir()["ok"])
        dest = N.artifact_in(os.path.join(os.path.dirname(self.hand_over()), "t2"))
        tarballs = os.path.join(dest, "tarballs")
        path = os.path.join(tarballs, os.listdir(tarballs)[0])
        with open(path, "r+b") as fh:
            first = fh.read(1)
            fh.seek(0)
            fh.write(bytes([first[0] ^ 1]))
        line = self.run_kos()
        self.assertEqual([t["target"] for t in line["targets"]], ["t2", "t1"])
        t2, t1 = line["targets"]
        self.assertEqual((t2["index"]["base"]["verdict"], t2["index"]["base"]["reasons"]),
                         ("no_verdict", ["deps:tarball_mismatch:node_modules/left-pad"]))
        self.assertEqual(t1["index"]["base"], {"verdict": "verified", "reasons": []})

    def test_deps_without_the_id_level_are_not_read(self):
        # t1's <address>/ handed over as in/deps itself: kos finds no in/deps/<id>, and the lock has packages
        self.assertTrue(self.run_getir()["ok"])
        shutil.copytree(self.out, os.path.join(self.temp, "in", "deps"), symlinks=True)
        with self.assertRaises(J.Unusable):
            self.run_kos()


if __name__ == "__main__":
    unittest.main()
