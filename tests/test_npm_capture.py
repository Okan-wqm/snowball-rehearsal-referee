"""``runner.deps_npm``'s reading of a lock entry's platform fields against npm's own answers (asama-0/09, test 34).

``fixtures/npm-platform.json`` is made by ``capture_npm_platform.py``: npm 10.9.9's npm-install-checks 7.1.2,
``checkPlatform`` asked for every entry and environment of that file's tables, and node's ``!!value`` for its flag
values. Here, without node or npm:

- ``platform_admits`` admits an entry exactly when npm's check returned; where npm's check threw
  (``EBADPLATFORM``, or a ``TypeError`` on a shape it cannot read) the entry is not admitted;
- ``js_true`` holds a value true exactly when JavaScript does (the reading of an entry's ``optional``);
- the fixture is the capture's own tables, whole: every environment and entry of ``capture_npm_platform`` in its
  order, every flag value, and each of the three outcomes is there (a table cut short or of one outcome would
  pass the two comparisons above and prove less than it says).

``fixtures/npm-version.json`` is made by ``capture_npm_version.py``: ``@npmcli/package-json`` 6.2.0's version
step (node-semver 7.7.4, loose) asked for every value of that file's two lists. ``manifest_version`` gives npm's
reading for each value of ``READ``; for a value of ``LEFT`` it gives the string with the prefix and the trim
taken off and nothing else (None for a value that is no string), which is never the version npm reads there.

``fixtures/npm-bundled.json`` is made by ``capture_npm_bundled.py``: arborist 8.0.5's ``loadActual`` and ``npm
rebuild`` asked, for each layout of that file, which directories below a package's own ``node_modules`` are
packages and in which a postinstall ran. Every such directory is a chain of ``bundled_path`` (the directories
``inspect_tarball`` judges; ``test_deps_npm.TestBundled`` runs them through a tarball), and no directory the
capture wrote outside every chain was loaded or ran.

What this does not show: that another npm version answers the same (the fixture names its versions), and the
libc npm finds itself on a linux machine (every linux environment of the table states its libc).
"""

import collections
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REFEREE = os.path.dirname(HERE)
sys.path.insert(0, REFEREE)
sys.path.insert(0, HERE)

import capture_npm_bundled as capture_bundled  # noqa: E402
import capture_npm_platform as capture  # noqa: E402
import capture_npm_version as capture_version  # noqa: E402
from runner import deps_npm  # noqa: E402

FIXTURE = os.path.join(HERE, "fixtures", "npm-platform.json")


def table() -> dict:
    with open(FIXTURE, encoding="utf-8") as fh:
        return json.load(fh)


def versions() -> dict:
    with open(os.path.join(HERE, "fixtures", "npm-version.json"), encoding="utf-8") as fh:
        return json.load(fh)


def platform_of(env: dict) -> dict:
    return {field: env.get(field) for field in ("os", "cpu", "libc")}


class NpmCapture(unittest.TestCase):
    def test_an_entry_is_admitted_exactly_when_npm_s_check_returns(self):
        for case in table()["platform"]:
            with self.subTest(env=case["env"], entry=case["entry"]):
                self.assertIs(deps_npm.platform_admits(case["entry"], platform_of(case["env"])),
                              case["outcome"] == "admits")

    def test_a_value_is_held_true_exactly_when_javascript_holds_it_true(self):
        for case in table()["truth"]:
            with self.subTest(value=case["value"]):
                self.assertIs(deps_npm.js_true(case["value"]), case["true"])

    def test_a_manifest_version_is_read_as_npm_reads_it_or_left_as_written(self):
        got = versions()
        cases = got["versions"]
        self.assertEqual([case["value"] for case in cases], capture_version.READ + capture_version.LEFT)
        self.assertEqual((got["npm"], got["npmcli_package_json"], got["semver"]), ("10.9.9", "6.2.0", "7.7.4"))
        read, left = cases[:len(capture_version.READ)], cases[len(capture_version.READ):]
        for case in read:
            with self.subTest(value=case["value"]):
                self.assertTrue(case["read"])                    # npm reads a version here, and it is this one
                self.assertEqual(deps_npm.manifest_version(case["value"]), case["read"])
        for case in left:
            with self.subTest(value=case["value"]):
                mine = deps_npm.manifest_version(case["value"])
                if case["read"]:                                 # npm reads a version: this function does not
                    self.assertNotEqual(mine, case["read"])
                if isinstance(case["value"], str):               # nothing but the prefix and the trim is taken
                    self.assertEqual(mine, case["value"].strip(" \t\n\x0b\x0c\r").lstrip("v= \t\n\x0b\x0c\r"))
                else:
                    self.assertIsNone(mine)
        # each kind of answer is in the table: a cleaned version, an unreadable one, and an absent one read as ""
        self.assertTrue(any(c["read"] and c["read"] != c["value"] for c in read))
        self.assertEqual(sorted({repr(c["read"]) for c in left if not c["read"]}), ["''", "None"])
        self.assertTrue(any(c["read"] for c in left))

    def test_every_directory_npm_reads_as_a_bundled_package_is_a_chain(self):
        with open(os.path.join(HERE, "fixtures", "npm-bundled.json"), encoding="utf-8") as fh:
            got = json.load(fh)
        self.assertEqual((got["npm"], got["npmcli_arborist"]), ("10.9.9", "8.0.5"))
        self.assertEqual(got["dirs"], capture_bundled.DIRS)
        self.assertEqual([(lay["id"], lay["bundle"]) for lay in got["layouts"]],
                         [(lay["id"], lay["bundle"]) for lay in capture_bundled.LAYOUTS])

        def chain(directory: str) -> bool:
            return deps_npm.bundled_path(directory.split("/") + ["package.json"]) == (directory, ["package.json"])

        for layout in got["layouts"]:
            for directory in layout["loaded"] + layout["ran"]:
                with self.subTest(layout=layout["id"], directory=directory):
                    self.assertIn(directory, got["dirs"])
                    self.assertTrue(chain(directory))
            self.assertLessEqual(set(layout["ran"]), set(layout["loaded"]))
        # the other way does not hold and is not claimed: a chain npm does not read (a name that starts with a dot),
        # and a chain npm reads and runs nothing in (a package its bundler does not list)
        everything = got["layouts"][0]
        self.assertEqual(everything["id"], "all_listed")
        unread = [d for d in got["dirs"] if chain(d) and d not in everything["loaded"]]
        self.assertEqual(unread, ["node_modules/.h", "node_modules/@s/.z", "node_modules/a/node_modules/.c",
                                  "node_modules/.h/node_modules/e"])
        self.assertEqual([d for d in got["dirs"] if not chain(d)],
                         ["node_modules/a/lib/node_modules/d", "node_modules/a/lib", "lib/node_modules/g", "lib"])
        self.assertEqual(everything["ran"], everything["loaded"])
        for name in ("node_modules/_x", "node_modules/x y", "node_modules/@/.r", "node_modules/a/node_modules/b"):
            self.assertIn(name, everything["ran"])              # names no npm package has, and a nested one
        self.assertEqual([lay["ran"] for lay in got["layouts"][2:]], [[], []])
        self.assertLess(len(got["layouts"][1]["ran"]), len(got["layouts"][1]["loaded"]))

    def test_the_fixture_is_the_capture_s_tables_whole(self):
        got = table()
        self.assertEqual([(case["env"], case["entry"]) for case in got["platform"]],
                         [(env, entry) for env in capture.ENVS for entry in capture.entries()])
        self.assertEqual([case["value"] for case in got["truth"]], capture.FLAGS)
        outcomes = collections.Counter(case["outcome"] for case in got["platform"])
        self.assertEqual(sorted(outcomes), ["EBADPLATFORM", "TypeError", "admits"])
        self.assertEqual(sorted({case["true"] for case in got["truth"]}), [False, True])
        self.assertEqual((got["npm"], got["npm_install_checks"]), ("10.9.9", "7.1.2"))


if __name__ == "__main__":
    unittest.main()
