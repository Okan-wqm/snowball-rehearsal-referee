"""``profile.ghactions`` (run with test 47): each rule of its docstring on a value made for it.

- ``evaluate``: literals, ``matrix`` lookups (nested, missing ``null``, the context's name in any case), ``!``,
  ``==``/``!=`` (strings ignoring case, other types as numbers), ``&&``/``||`` returning operands, precedence and
  parentheses, an unknown context (decided by the left operand of ``&&``/``||`` or ``context``), and the reasons
  ``function``, ``operator``, ``syntax``;
- ``interpolate``: text around expressions, each result's text;
- ``matrices``: no matrix, axes, ``exclude``, ``include`` (extending matching combinations, overwriting added keys,
  appended when it matches none, an appended one never matched again, include only), the dynamic forms and the
  bound;
- ``builds``: the action's name case-insensitive with any ref, other actions not builds, defaults (``.`` and
  ``<context>/Dockerfile``), ``./`` removed, pairs per combination (distinct, sorted), a reason empties the pairs,
  a composite action's ``runs.steps``, ``where``;
- ``is_actions_file``: the root's ``.github/workflows`` directly, ``action.yml``/``action.yaml`` anywhere.
"""

from __future__ import annotations

import os
import sys
import unittest

REFEREE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REFEREE)

from profile import ghactions as G  # noqa: E402
from profile import yamlblock as Y  # noqa: E402


class Evaluate(unittest.TestCase):
    M = {"svc": "Api", "n": 2, "flag": False, "o": {"name": "deep"}, "empty": ""}

    def test_values(self):
        cases = {"'it''s'": "it's", "12": 12, "1.5": 1.5, "0x10": 16, "true": True, "false": False, "null": None,
                 "matrix.svc": "Api", "MATRIX.svc": "Api", "matrix.o.name": "deep", "matrix.missing": None,
                 "matrix.svc.x": None, "!matrix.flag": True, "!!matrix.svc": True, "!matrix.empty": True}
        for text, want in cases.items():
            with self.subTest(text=text):
                self.assertEqual(G.evaluate(text, self.M), want)

    def test_equality(self):
        cases = {"matrix.svc == 'API'": True, "matrix.svc != 'api'": False, "matrix.n == '2'": True,
                 "matrix.n == 2.0": True, "matrix.flag == 0": True, "null == 0": True, "'x' == 0": False,
                 "true == 1": True, "matrix.missing == null": True, "'a' == 'b'": False}
        for text, want in cases.items():
            with self.subTest(text=text):
                self.assertEqual(G.evaluate(text, self.M), want)

    def test_and_or_return_operands(self):
        cases = {"matrix.svc == 'api' && 'A' || 'B'": "A", "matrix.svc == 'web' && 'A' || 'B'": "B",
                 "'' || 'x'": "x", "0 && 'x'": 0, "'a' && 'b'": "b", "'a' || 'b'": "a",
                 "false || true && 'y'": "y", "(false || true) && 'y'": "y", "!(true && false)": True,
                 "'' && 'x' || 'z'": "z", "true || false && false": True, "!matrix.flag && 'x'": "x",
                 "!(false) && 'x'": "x"}
        for text, want in cases.items():
            with self.subTest(text=text):
                self.assertEqual(G.evaluate(text, self.M), want)

    def test_unknown_context(self):
        self.assertEqual(G.evaluate("matrix.flag && inputs.x", self.M), False)    # decided by the left operand
        self.assertEqual(G.evaluate("matrix.svc || steps.a.outputs.b", self.M), "Api")
        for text in ("inputs.ctx", "needs.p.outputs.m == 'x'", "!env.X", "github.ref && 'a'",
                     "true && secrets.T", "matrix.svc == vars.V"):
            with self.subTest(text=text), self.assertRaises(G.Unresolved) as cm:
                G.evaluate(text, self.M)
            self.assertEqual(cm.exception.reason, "context")

    def test_reasons(self):
        cases = {"fromJson(needs.a.outputs.m)": "function", "format('{0}', matrix.svc)": "function",
                 "matrix.n < 3": "operator", "matrix.n >= 3": "operator", "matrix['svc']": "operator",
                 "matrix.*.x": "operator", "": "syntax", "matrix.svc ==": "syntax", "(true": "syntax",
                 "true)": "syntax", "'a' 'b'": "syntax", "== 'a'": "syntax", "'open": "syntax", "a ! b": "syntax"}
        for text, reason in cases.items():
            with self.subTest(text=text), self.assertRaises(G.Unresolved) as cm:
                G.evaluate(text, self.M)
            self.assertEqual(cm.exception.reason, reason)
            self.assertIsInstance(cm.exception, ValueError)


class Interpolate(unittest.TestCase):
    def test_text(self):
        m = {"d": "apps/x", "n": 3, "f": 1.0, "b": True, "z": None}
        self.assertEqual(G.interpolate("${{ matrix.d }}/Dockerfile", m), "apps/x/Dockerfile")
        self.assertEqual(G.interpolate("a-${{matrix.n}}-${{ matrix.f }}-${{ matrix.b }}-${{ matrix.z }}", m),
                         "a-3-1-true-")
        self.assertEqual(G.interpolate("plain", m), "plain")
        self.assertEqual(G.interpolate(None, m), "")
        self.assertEqual(G.interpolate(7, m), "7")
        self.assertEqual(G.interpolate(False, m), "false")
        with self.assertRaises(G.Unresolved):
            G.interpolate("${{ matrix.d }}/${{ inputs.f }}", m)


class Matrices(unittest.TestCase):
    def job(self, matrix):
        return {"strategy": {"matrix": matrix}}

    def test_none(self):
        self.assertEqual(G.matrices({}), [{}])
        self.assertEqual(G.matrices({"strategy": {"fail-fast": False}}), [{}])

    def test_axes_exclude_include(self):
        got = G.matrices(self.job({
            "os": ["linux", "mac"], "v": [1, 2],
            "exclude": [{"os": "mac", "v": 2}],
            "include": [{"v": 1, "extra": "a"}, {"v": 1, "extra": "b", "os": "linux"}, {"os": "win", "v": 9},
                        {"os": "win", "extra": "never"}]}))
        self.assertEqual(got, [
            {"os": "linux", "v": 1, "extra": "b"},         # extended by both; the second overwrites "extra"
            {"os": "linux", "v": 2},
            {"os": "mac", "v": 1, "extra": "a"},           # the second entry changes os: not added here
            {"os": "win", "v": 9},                         # matches none: its own combination
            {"os": "win", "extra": "never"}])              # an appended combination is never matched again

    def test_include_only(self):
        self.assertEqual(G.matrices(self.job({"include": [{"f": "a"}, {"f": "b"}]})), [{"f": "a"}, {"f": "b"}])

    def test_dynamic(self):
        for matrix in ("${{ fromJson(x) }}", {"include": "${{ fromJson(x) }}"}, {"os": "${{ fromJson(x) }}"},
                       {"os": ["a", "${{ inputs.o }}"]}, {"exclude": "${{ x }}"}, {"include": ["notamapping"]},
                       {"a": list(range(17)), "b": list(range(17))},
                       {"include": [{"k": n} for n in range(G.MAX_COMBINATIONS + 1)]}):
            with self.subTest(matrix=str(matrix)[:40]), self.assertRaises(G.Unresolved) as cm:
                G.matrices(self.job(matrix))
            self.assertEqual(cm.exception.reason, "matrix_dynamic")
        self.assertEqual(len(G.matrices(self.job({"a": list(range(16)), "b": list(range(16))}))), 256)


class Builds(unittest.TestCase):
    TEXT = ("jobs:\n"
            "  a:\n    steps:\n"
            "      - uses: actions/checkout@v4\n"
            "      - uses: DOCKER/build-push-action@v6\n"
            "      - uses: docker/build-push-action\n        with:\n          context: ./svc\n"
            "      - uses: docker/build-push-action@abc\n        with:\n          file: ./img/Dockerfile.x\n"
            "      - uses: docker/build-push-actions@v1\n"
            "      - uses: other/docker/build-push-action@v1\n"
            "  m:\n    strategy:\n      matrix:\n        s: [api, web, api2]\n        include:\n"
            "          - s: api2\n            s_dir: api\n    steps:\n"
            "      - run: echo\n"
            "      - uses: docker/build-push-action@v6\n        with:\n"
            "          context: ${{ matrix.s_dir || matrix.s }}\n"
            "          file: ${{ matrix.s == 'web' && 'web/Dockerfile' || '' }}\n"
            "      - uses: docker/build-push-action@v6\n        with:\n          context: ${{ inputs.c }}\n")

    def test_builds(self):
        self.assertEqual(G.builds(Y.load(self.TEXT)), [
            G.Build("jobs.a.steps[1]", [(".", "Dockerfile")], None),
            G.Build("jobs.a.steps[2]", [("svc", "svc/Dockerfile")], None),
            G.Build("jobs.a.steps[3]", [(".", "img/Dockerfile.x")], None),
            G.Build("jobs.m.steps[1]", [("api", "api/Dockerfile"), ("web", "web/Dockerfile")], None),
            G.Build("jobs.m.steps[2]", [], "context")])

    def test_composite_action(self):
        doc = Y.load("runs:\n  using: composite\n  steps:\n    - uses: docker/build-push-action@v5\n"
                     "      with:\n        context: ${{ inputs.context }}\n"
                     "    - uses: docker/build-push-action@v5\n      with:\n        context: d\n        file: d/F\n")
        self.assertEqual(G.builds(doc), [G.Build("runs.steps[0]", [], "context"),
                                         G.Build("runs.steps[1]", [("d", "d/F")], None)])

    def test_not_a_workflow(self):
        for doc in (None, [], "x", {"jobs": "x"}, {"jobs": {"a": {"steps": "x"}}}, {"runs": {"using": "node20"}}):
            with self.subTest(doc=doc):
                self.assertEqual(G.builds(doc), [])

    def test_is_actions_file(self):
        yes = (".github/workflows/a.yml", ".github/workflows/b.yaml", "action.yml", ".github/actions/x/action.yaml",
               "deep/dir/action.yml")
        no = (".github/workflows/sub/a.yml", "x/.github/workflows/a.yml", ".github/workflows/a.json",
              ".github/dependabot.yml", "myaction.yml", "action.yml.bak")
        self.assertEqual([p for p in yes if G.is_actions_file(p)], list(yes))
        self.assertEqual([p for p in no if G.is_actions_file(p)], [])


if __name__ == "__main__":
    unittest.main()
