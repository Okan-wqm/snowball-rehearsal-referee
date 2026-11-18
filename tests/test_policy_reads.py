"""``policy.reads`` (tohum/29v): the one reader of ``policy.json``'s values and the command that names them.

What these tests show, on the inputs they build (no file of ``/vec`` is read here):

- ``Walk``: rules 1-3 of the module (``PATHS``, ``at``, ``operating``, ``named``);
- ``Command``: the command line on files written here: a sectioned policy, the same with every read value moved
  to the root beside other values (nothing of the root is printed), a missing section, and the unusable inputs;
- ``Readers``: each function that reads the policy, run on a policy whose objects record every key looked up:
  no lookup is off ``PATHS`` (a root key, another section, an unnamed ``operating`` key, a walk over a whole
  section), and each function refuses or defaults (as its own rule says) on the hoisted policy instead of
  reading the root;
- ``Register``: the section name ``constitutional`` and ``performance`` as string constants in no source file
  of ``referee/`` but ``policy/reads.py``, and no ``get``/index/``in`` with the string ``operating`` on a name
  ``policy`` anywhere else.

Not shown: a reader these tests do not run (see the module's "Outside").
"""

from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
import tempfile
import unittest

REFEREE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REFEREE)

from dispatcher import llm_call as L  # noqa: E402
from policy import reads as P  # noqa: E402
from profile import derive as D  # noqa: E402
from profile import unit_verify as U  # noqa: E402
from runner import deps_npm as N  # noqa: E402

MiB = 1 << 20


def entry(value: int) -> dict:
    return {"value": value, "band": [1, value * 4]}


def sectioned() -> dict:
    """A policy with every path of ``PATHS`` in its section, each value distinct, and values beside them."""
    return {
        "constitutional": {
            "license_allowlist": ["MIT", "ISC"],
            "license_exceptions": {"a==1.0.0": {"expression": "MIT", "evidence": "e"}},
            "security_keywords": ["auth", "secret"],
            "stage_budgets": {"asama_0": {"canary_usd": 7, "other_usd": 70}, "asama_1": {"canary_usd": 700}},
            "unread": 1,
        },
        "operating": dict({name: entry(100 + i) for i, name in enumerate(P.OPERATING_NAMES)},
                          unnamed_bytes=entry(999)),
        "performance": {"kos_wall_s": entry(555), "license_allowlist": ["PERF"]},
        "schema": 1,
    }


def hoisted() -> dict:
    """``sectioned`` with every ``PATHS`` value taken out of its section and put at the root under its last key
    (and, for the nested one, under its whole tail), other values left where they were."""
    policy = sectioned()
    for path in P.PATHS:
        node = policy
        for key in path[:-1]:
            node = node[key]
        value = node.pop(path[-1])
        policy[path[-1]] = value
    policy["stage_budgets"] = {"asama_0": {"canary_usd": 7}}
    return policy


class Walk(unittest.TestCase):
    def test_paths_are_sectioned_and_their_keys_hold_no_dot(self):
        self.assertEqual(len(set(P.PATHS)), len(P.PATHS))
        self.assertEqual(len({P.dotted(p) for p in P.PATHS}), len(P.PATHS))
        for path in P.PATHS:
            self.assertIn(path[0], ("constitutional", "operating", "performance"), path)
            self.assertGreaterEqual(len(path), 2)
            for key in path:
                self.assertTrue(key and "." not in key, path)
        self.assertEqual({p[1] for p in P.PATHS if p[0] == "operating"}, set(P.OPERATING_NAMES))
        self.assertEqual(P.dotted(P.CANARY_USD), "constitutional.stage_budgets.asama_0.canary_usd")

    def test_at_returns_the_value_at_the_path(self):
        policy = sectioned()
        self.assertEqual(P.at(policy, P.LICENSE_ALLOWLIST), ["MIT", "ISC"])
        self.assertEqual(P.at(policy, P.CANARY_USD), 7)
        self.assertIs(P.at(policy, ("operating", "kos_wall_s")), policy["operating"]["kos_wall_s"])
        self.assertEqual(P.at(policy, ("constitutional", "stage_budgets")), policy["constitutional"]["stage_budgets"])

    def test_at_reads_no_key_of_the_same_name_elsewhere(self):
        policy = hoisted()
        for path in P.PATHS:
            self.assertIs(P.at(policy, path), P.ABSENT, path)
        self.assertIs(P.at({"license_allowlist": ["X"]}, P.LICENSE_ALLOWLIST), P.ABSENT)
        self.assertIs(P.at({"performance": {"kos_wall_s": entry(5)}}, ("operating", "kos_wall_s")), P.ABSENT)
        self.assertIs(P.at({"constitutional": {"asama_0": {"canary_usd": 1}, "canary_usd": 2}}, P.CANARY_USD),
                      P.ABSENT)
        self.assertIs(P.at({}, P.CANARY_USD), P.ABSENT)

    def test_a_null_at_the_path_is_not_absent(self):
        self.assertIsNone(P.at({"constitutional": {"security_keywords": None}}, P.SECURITY_KEYWORDS))
        self.assertIsNot(P.ABSENT, None)

    def test_a_non_object_on_the_way_is_malformed(self):
        for policy in ([], "x", None, 3, {"constitutional": []}, {"constitutional": "x"}, {"constitutional": None},
                       {"constitutional": {"stage_budgets": 1}},
                       {"constitutional": {"stage_budgets": {"asama_0": [7]}}}):
            with self.subTest(policy=policy), self.assertRaises(P.Malformed):
                P.at(policy, P.CANARY_USD)
        # the last key's value is the value, whatever its type
        self.assertEqual(P.at({"constitutional": {"stage_budgets": {"asama_0": {"canary_usd": [1]}}}}, P.CANARY_USD),
                         [1])

    def test_operating_holds_the_named_entries_only(self):
        policy = sectioned()
        got = P.operating(policy)
        self.assertEqual(set(got), set(P.OPERATING_NAMES))
        for name in P.OPERATING_NAMES:
            self.assertIs(got[name], policy["operating"][name])
        self.assertIsNot(got, policy["operating"])
        del policy["operating"]["kos_wall_s"]
        self.assertEqual(set(P.operating(policy)), set(P.OPERATING_NAMES) - {"kos_wall_s"})
        self.assertEqual(P.operating({"operating": {"unnamed_bytes": entry(1)}}), {})

    def test_operating_without_a_policy_or_the_section(self):
        for policy in (None, [], "x", {}, {"constitutional": {}}, dict(sectioned()["operating"])):
            with self.subTest(policy=policy):
                self.assertIsNone(P.operating(policy))
        self.assertIsNone(P.operating({"performance": sectioned()["operating"]}))
        for section in ([], "x", None, 5):
            with self.subTest(section=section), self.assertRaises(P.Malformed):
                P.operating({"operating": section})

    def test_named_is_every_path_with_its_value_or_none(self):
        policy = sectioned()
        got = P.named(policy)
        self.assertEqual(set(got), {P.dotted(p) for p in P.PATHS})
        self.assertEqual(got["constitutional.license_allowlist"], ["MIT", "ISC"])
        self.assertEqual(got["constitutional.stage_budgets.asama_0.canary_usd"], 7)
        self.assertEqual(got["operating.kos_wall_s"], policy["operating"]["kos_wall_s"])
        self.assertEqual(P.named(hoisted()), {P.dotted(p): None for p in P.PATHS})
        self.assertEqual(P.named({}), {P.dotted(p): None for p in P.PATHS})


class Command(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = tmp.name
        self.n = 0

    def write(self, content) -> str:
        self.n += 1
        path = os.path.join(self.dir, "p%d.json" % self.n)
        with open(path, "wb") as fh:
            fh.write(content if isinstance(content, bytes) else json.dumps(content).encode())
        return path

    def run_cmd(self, *argv: str) -> tuple[int, dict, str]:
        proc = subprocess.run([sys.executable, "-m", "policy.reads", *argv], cwd=REFEREE, stdin=subprocess.DEVNULL,
                              capture_output=True, text=True, timeout=120)
        self.assertNotIn("Traceback", proc.stderr)
        lines = proc.stdout.splitlines()
        self.assertEqual(len(lines), 1, proc.stdout)
        return proc.returncode, json.loads(lines[0]), proc.stdout

    def test_a_sectioned_policy_prints_each_path_with_the_value_read(self):
        policy = sectioned()
        code, out, _ = self.run_cmd(self.write(policy))
        self.assertEqual(code, 0)
        self.assertEqual(set(out), {P.dotted(p) for p in P.PATHS})
        for path in P.PATHS:
            node = policy
            for key in path:
                node = node[key]
            self.assertEqual(out[P.dotted(path)], node, path)
        for name in out:  # tohum/29v: every name starts with a section
            self.assertIn(name.split(".")[0], ("constitutional", "operating", "performance"))

    def test_a_hoisted_policy_prints_null_for_every_path(self):
        code, out, text = self.run_cmd(self.write(hoisted()))
        self.assertEqual(code, 0)
        self.assertEqual(out, {P.dotted(p): None for p in P.PATHS})
        self.assertNotIn("MIT", text)

    def test_one_absent_path_is_null_and_the_rest_are_read(self):
        policy = sectioned()
        del policy["constitutional"]["stage_budgets"]["asama_0"]["canary_usd"]
        del policy["operating"]["output_bytes"]
        policy["canary_usd"] = 9
        policy["output_bytes"] = entry(9)
        code, out, _ = self.run_cmd(self.write(policy))
        self.assertEqual(code, 0)
        self.assertEqual([n for n, v in sorted(out.items()) if v is None],
                         ["constitutional.stage_budgets.asama_0.canary_usd", "operating.output_bytes"])
        self.assertEqual(out["operating.kos_wall_s"], policy["operating"]["kos_wall_s"])

    def test_unusable_input_is_exit_2_with_one_json_error(self):
        good = json.dumps(sectioned())
        cases = {
            "not_json": b"{",
            "list": b"[]",
            "string": b'"x"',
            "section_not_object": b'{"constitutional": []}',
            "operating_not_object": b'{"operating": 5}',
            "way_not_object": b'{"constitutional": {"stage_budgets": {"asama_0": 3}}}',
            "repeated_key": b'{"operating": {}, "operating": {}}',
            "repeated_key_nested": b'{"constitutional": {"security_keywords": ["a"], "security_keywords": ["b"]}}',
            "nan": b'{"operating": {"kos_wall_s": NaN}}',
            "infinity": b'{"x": -Infinity}',
            "not_utf8": b'{"x": "\xff"}',
            "two_values": (good + good).encode(),
            "deep": b'{"x": ' + b"[" * 100000 + b"]" * 100000 + b"}",
        }
        for name, content in cases.items():
            with self.subTest(case=name):
                code, out, _ = self.run_cmd(self.write(content))
                self.assertEqual((code, out["ok"]), (2, False))
                self.assertTrue(out["error"].startswith("unusable input: "), out)
        for argv in ((), (self.write(sectioned()), "x"), (os.path.join(self.dir, "missing.json"),), (self.dir,)):
            with self.subTest(argv=argv):
                code, out, _ = self.run_cmd(*argv)
                self.assertEqual((code, out["ok"]), (2, False))


class Recorded(dict):
    """An object of the policy that records the path of every key looked up in it, and every walk over it."""

    def __init__(self, value: dict, path: tuple, log: list):
        super().__init__((k, wrap(v, path + (k,), log)) for k, v in value.items())
        self.path, self.log = path, log

    def _see(self, key):
        self.log.append(self.path + (key,))

    def __getitem__(self, key):
        self._see(key)
        return super().__getitem__(key)

    def get(self, key, default=None):
        self._see(key)
        return super().get(key, default)

    def __contains__(self, key):
        self._see(key)
        return super().__contains__(key)

    def pop(self, key, *default):
        self._see(key)
        return super().pop(key, *default)

    def setdefault(self, key, default=None):
        self._see(key)
        return super().setdefault(key, default)

    def _walk(self):
        self.log.append(self.path + (WALK,))

    def __iter__(self):
        self._walk()
        return super().__iter__()

    def keys(self):
        self._walk()
        return super().keys()

    def values(self):
        self._walk()
        return super().values()

    def items(self):
        self._walk()
        return super().items()

    def __eq__(self, other):
        self._walk()
        return super().__eq__(other)

    __hash__ = None

    def copy(self):
        self._walk()
        return super().copy()


WALK = object()


def wrap(value, path: tuple, log: list):
    if isinstance(value, dict):
        return Recorded(value, path, log)
    if isinstance(value, list):
        return [wrap(v, path + (i,), log) for i, v in enumerate(value)]
    return value


def off_paths(log: list) -> list:
    """The recorded lookups that are neither on the way to a path of ``PATHS`` nor at or under one."""
    def on(seen: tuple) -> bool:
        return any(seen == path[:len(seen)] or seen[:len(path)] == path for path in P.PATHS)
    return [seen for seen in log if not on(seen)]


class Readers(unittest.TestCase):
    """Rule 4. ``recorded`` is ``sectioned`` (every path present, values beside them in every section and at the
    root) with its objects recording; a reader's lookups must all be on ``PATHS``."""

    def recorded(self, policy=None) -> tuple[dict, list]:
        log: list = []
        return wrap(sectioned() if policy is None else policy, (), log), log

    def check(self, log: list, *reached: tuple) -> None:
        self.assertEqual(off_paths(log), [])
        for path in reached:  # the reader did read: an empty log proves nothing
            self.assertIn(path, log)

    def test_the_recorder_sees_an_off_path_lookup(self):
        for read in (lambda p: p["schema"], lambda p: p.get("license_allowlist"), lambda p: "kos_wall_s" in p,
                     lambda p: p["operating"]["unnamed_bytes"], lambda p: p["performance"].get("kos_wall_s"),
                     lambda p: p["constitutional"]["stage_budgets"]["asama_1"], lambda p: list(p),
                     lambda p: dict(p["operating"]), lambda p: p["operating"].items(),
                     lambda p: p["constitutional"]["stage_budgets"]["asama_0"].values(),
                     lambda p: json.dumps(p["operating"]), lambda p: {**p["operating"]},
                     lambda p: p["operating"] == {}, lambda p: p["constitutional"].copy()):
            policy, log = self.recorded()
            read(policy)
            self.assertNotEqual(off_paths(log), [], log)
        policy, log = self.recorded()
        policy["operating"]["kos_wall_s"]["band"][0]
        policy["constitutional"]["license_exceptions"].items()
        self.assertEqual(off_paths(log), [])

    def test_deps_npm_reads_its_three_paths(self):
        policy, log = self.recorded()
        allow, exceptions, limit = N._policy_values(policy)
        self.assertEqual((allow, limit), (["MIT", "ISC"], 101))
        self.assertEqual(dict.items(exceptions), dict.items(sectioned()["constitutional"]["license_exceptions"]))
        self.check(log, P.LICENSE_ALLOWLIST, P.LICENSE_EXCEPTIONS, N.DEPS_BYTES)
        self.assertIn(N.DEPS_BYTES, P.PATHS)
        policy, log = self.recorded(hoisted())
        self.assertEqual(N._policy_values(policy), (list(N.LICENSE_ALLOWLIST), {}, None))  # the seed's defaults
        self.check(log)

    def test_derive_reads_the_security_keywords(self):
        policy, log = self.recorded()
        self.assertEqual(D._keywords(policy), ["auth", "secret"])
        self.check(log, P.SECURITY_KEYWORDS)
        policy, log = self.recorded(hoisted())
        with self.assertRaises(D.DeriveError):
            D._keywords(policy)
        self.check(log)

    def test_unit_verify_reads_the_named_operating_entries(self):
        policy, log = self.recorded()
        got = U._operating(policy, P.OPERATING_NAMES)
        self.assertEqual({k: v[0] for k, v in got.items()}, {n: 100 + i for i, n in enumerate(P.OPERATING_NAMES)})
        self.check(log, ("operating", "kos_wall_s"), ("operating", "output_bytes"))

        policy, log = self.recorded()
        recipe = {"path": "pkg", "inputs": ["pkg"], "limits": {"kos_wall_s": 5, "unnamed_bytes": 5, "cpu_s": 1},
                  "env_image": "x", "services": []}
        reasons = U.vector_check(recipe, policy)
        # a key of operating{} the loop does not name is no limit key: it is not looked up, so it is unknown
        self.assertEqual([r for r in reasons if r.startswith("limit_")],
                         ["limit_key_unknown:cpu_s", "limit_key_unknown:unnamed_bytes"])
        self.check(log, ("operating", "kos_wall_s"))

        policy, log = self.recorded()
        self.assertEqual(U._limit_reasons({"kos_wall_s": 10 ** 9, "output_bytes": 5, "unnamed_bytes": 5}, policy),
                         ["limit_above_operating:kos_wall_s", "limit_key_unknown:unnamed_bytes"])
        self.check(log, ("operating", "kos_wall_s"))

        with tempfile.TemporaryDirectory() as tree:
            policy, log = self.recorded()
            derived = U.derived_profile(tree, None, policy)
            self.assertEqual(derived, D.derive(tree, None, {"constitutional": {"security_keywords": ["auth", "secret"]}}))
            self.check(log, P.SECURITY_KEYWORDS)

    def test_unit_verify_on_a_hoisted_policy_reads_no_root_value(self):
        policy, log = self.recorded(hoisted())
        with self.assertRaises(U.VerifyError):
            U._operating(policy, ("kos_wall_s",))
        self.assertEqual(U.vector_check({"path": "pkg", "inputs": ["pkg"], "limits": {"kos_wall_s": 5},
                                         "env_image": "x", "services": []}, policy).count("limit_key_unknown:kos_wall_s"),
                         1)
        self.check(log)

    def test_policy_usd_reads_the_path_from_the_root_only(self):
        self.assertEqual(L.policy_usd(json.dumps(sectioned()).encode(), *P.CANARY_USD), 7_000_000)
        for policy in (hoisted(), {"stage_budgets": {"asama_0": {"canary_usd": 7}}}, {"constitutional": []},
                       {"constitutional": {"stage_budgets": {"asama_0": 7}}},
                       {"operating": {"stage_budgets": {"asama_0": {"canary_usd": 7}}}}):
            with self.subTest(policy=policy), self.assertRaises(L.Unusable):
                L.policy_usd(json.dumps(policy).encode(), *P.CANARY_USD)

    def test_the_loop_names_the_canary_path_of_this_module(self):
        from loop import cagir
        self.assertIs(cagir.CANARY_USD, P.CANARY_USD)
        self.assertIs(U.OPERATING_NAMES, P.OPERATING_NAMES)


def sources() -> list[str]:
    found = []
    for base, dirs, files in os.walk(REFEREE):
        dirs[:] = sorted(d for d in dirs if d != "__pycache__" and not (base == REFEREE and d == "tests"))
        found += [os.path.join(base, f) for f in sorted(files) if f.endswith(".py")]
    return found


SECTIONS_ONLY_HERE = ("constitutional", "performance")
POLICY_NAMES = ("policy", "pol", "policy_json")


def section_constants(tree: ast.AST) -> list[tuple[int, str]]:
    """String constants that are a section name of ``SECTIONS_ONLY_HERE`` (docstrings are not: an expression
    statement that is only a string), and lookups of the string ``operating`` on a name of ``POLICY_NAMES``."""
    docs = {id(n.value) for n in ast.walk(tree) if isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant)}
    found = [(n.lineno, n.value) for n in ast.walk(tree)
             if isinstance(n, ast.Constant) and n.value in SECTIONS_ONLY_HERE and id(n) not in docs]

    def is_policy(node) -> bool:
        return isinstance(node, ast.Name) and node.id in POLICY_NAMES

    def is_operating(node) -> bool:
        return isinstance(node, ast.Constant) and node.value == "operating"

    for n in ast.walk(tree):
        if isinstance(n, ast.Subscript) and is_policy(n.value) and is_operating(n.slice):
            found.append((n.lineno, "operating"))
        elif (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and is_policy(n.func.value) and n.args
              and is_operating(n.args[0])):
            found.append((n.lineno, "operating"))
        elif isinstance(n, ast.Compare) and is_operating(n.left) and any(is_policy(c) for c in n.comparators):
            found.append((n.lineno, "operating"))
    return sorted(found)


class Register(unittest.TestCase):
    def test_the_section_names_are_string_constants_in_policy_reads_only(self):
        files = sources()
        self.assertGreater(len(files), 30)
        self.assertIn(os.path.join(REFEREE, "policy", "reads.py"), files)
        found = {}
        for path in files:
            with open(path, encoding="utf-8") as fh:
                hits = section_constants(ast.parse(fh.read()))
            if hits:
                found[os.path.relpath(path, REFEREE)] = hits
        self.assertEqual(sorted(found), [os.path.join("policy", "reads.py")], found)

    def test_the_register_sees_each_form(self):
        for source, expected in (
                ('x = policy.get("constitutional", {})', ["constitutional"]),
                ('PATH = ("constitutional", "a")', ["constitutional"]),
                ('if "performance" in policy: pass', ["performance"]),
                ('x = policy["operating"]', ["operating"]),
                ('x = policy.get("operating")', ["operating"]),
                ('x = pol.pop("operating", None)', ["operating"]),
                ('x = "operating" in policy', ["operating"]),
                ('def f():\n    """the constitutional part"""\n    return req["operating"]', []),
                ('"""constitutional"""', []),
                ('x = ctx["operating"]', [])):
            with self.subTest(source=source):
                self.assertEqual([v for _, v in section_constants(ast.parse(source))], expected)


if __name__ == "__main__":
    unittest.main()
