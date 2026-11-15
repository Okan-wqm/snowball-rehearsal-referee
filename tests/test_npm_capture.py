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

import capture_npm_platform as capture  # noqa: E402
from runner import deps_npm  # noqa: E402

FIXTURE = os.path.join(HERE, "fixtures", "npm-platform.json")


def table() -> dict:
    with open(FIXTURE, encoding="utf-8") as fh:
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
