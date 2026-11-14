"""Test 46 (asama-0/09), MF17, D4: the ``cagir`` job (``loop.job run cagir``, ``loop.cagir``), MF15's call on the
``pulled`` artifact, with the fake ``claude`` CLI (``fake_claude.py``, test 37's). The job serves every target
``in/pulled/served.json`` lists, in order (tohum/29s "Hedefler"): target ``<id>``'s ``pulled`` is ``in/pulled/<id>``,
its response ``out/response/<id>``, its line ``targets[i]`` of the job's line (``{target: <id>, ok, done, call,
claude_sha512}``).

- the call: one process, the CLI the ``claude`` step installs (``loop.inputs.claude``, tohum/29s; the fake placed
  there), the referee's own template with the target's id as typed input (the prompt on stdin, the id in its RFC
  8785 form), the model ``bootstrap.json``'s ``rival.model`` in the checkout (no variable is read), the pin the
  CLI file's sha512 when the job read it (in the line), ``--max-budget-usd`` the canary's
  ``canary_usd`` less what ``state/ledger.jsonl``'s cost rows spent (an integer and a fraction of USD, exact);
- the response: written whatever the outcome (``ok``, a served model that is not the requested one), its one
  ``cost`` row with the run's ``row_id``, the clock's ``ts`` and ``brain/integration``'s head, appended by
  ``ledger.append`` onto the ledger ``pulled`` carries (D6's input); the target's line is ``ok`` with ``done``
  ``["D4"]``, and so is the job;
- two served targets: one call each, in ``served.json``'s order, each response in its own ``out/response/<id>``
  naming that target;
- not sent, response written without a row: the stage brake (the ledger's spend at the cap), a secret pattern in the
  prompt (a target id shaped like a token);
- nothing started and nothing written: a refused ``pulled`` (``pulled_invalid``, exit 1), among them one whose
  ``target.id`` is not its directory's name (``target_mismatch``) and an unreadable ``served.json``; a
  ``canary_usd`` that is absent, ``true``, a string or negative, a ledger in ``pulled`` that is not a chain, no CLI
  where the step installs it (one on ``PATH`` is not used), an unusable ``bootstrap.json`` or ``rival.model``, an
  unset variable and an existing ``out/response/<id>`` (no verdict, exit 2).
"""

from __future__ import annotations

import datetime
import json
import os
import shutil
import sys
import unittest

REFEREE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REFEREE)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import fake_claude  # noqa: E402
from dispatcher import llm_call as L  # noqa: E402
from ledger import append  # noqa: E402
from loop import cagir as CG  # noqa: E402
from loop import inputs  # noqa: E402
from loop import job as J  # noqa: E402
from test_kos import operating  # noqa: E402
from loop import pulled as P  # noqa: E402
from test_loop_kos import HEADS, TARGET, Base, state_files  # noqa: E402
from loop_inputs_world import ABSENT, BOOTSTRAP, write_bootstrap  # noqa: E402

from test_llm_call import MODEL, TOKEN  # noqa: E402  (test 37's model and token-shaped value, one source)

NOW = datetime.datetime(2026, 11, 1, 13, 30, 5, tzinfo=datetime.timezone.utc)
OUTPUT = {"echo": "t1"}


def result(**over) -> str:
    base = {"type": "result", "subtype": "success", "is_error": False, "result": "", "stop_reason": "end_turn",
            "total_cost_usd": 0.0123451, "modelUsage": {MODEL: {"costUSD": 0.0123451}}, "structured_output": OUTPUT}
    base.update(over)
    return json.dumps(base)


def policy(canary: str = "1") -> bytes:
    """``policy.json`` with ``canary_usd`` written as the JSON text ``canary`` (so ``0.5`` is a JSON fraction)."""
    return ('{"operating": %s, "stage_budgets": {"asama_0": {"canary_usd": %s}}}'
            % (json.dumps(operating()), canary)).encode()


def ledger_with_costs(*costs: int) -> list[dict]:
    rows = [{"row_id": "g1", "part": "genesis", "kind": "genesis", "payload": {}}]
    return rows + [{"row_id": "c%d" % i, "part": "cost", "kind": "cost", "payload": {"usd_micros": c}}
                   for i, c in enumerate(costs)]


class CagirJob(Base):
    def setUp(self) -> None:
        super().setUp()
        self.claude = fake_claude.install_for_loop(self.temp)
        self.bin = os.path.dirname(self.claude)
        fake_claude.behave(self.bin, result())
        self.work = os.path.join(self.base, "checkout")
        os.makedirs(self.work)
        write_bootstrap(self.work, dict(BOOTSTRAP, rival={"model": MODEL}))
        self.env = {"RUNNER_TEMP": self.temp, "CLAUDE_CODE_OAUTH_TOKEN": TOKEN, "GITHUB_WORKSPACE": self.work,
                    "GITHUB_RUN_ID": "77", "GITHUB_RUN_ATTEMPT": "2", "PATH": os.environ.get("PATH", "")}

    def write(self, canary: str = "1", ledger: list[dict] | None = None, **kw) -> None:
        state = state_files(ledger) if ledger is not None else None
        self.write_pulled(policy=policy(canary), state=state, **kw)

    def serve(self, *targets: dict, **kw) -> None:
        """``in/pulled`` serving ``targets`` in that order: ``served.json`` and each one's ``pulled`` in its directory."""
        served = os.path.dirname(self.pulled)
        os.makedirs(served)
        P.write_served(served, [t["id"] for t in targets])
        for t in targets:
            self.pulled = os.path.join(served, t["id"])
            self.write(target=t, **kw)

    def run_cagir(self, **env) -> dict:
        environ = {k: v for k, v in dict(self.env, **env).items() if v is not None}
        return J.run("cagir", environ, now=lambda: NOW)

    def line(self, out: dict, tid: str = "t1") -> dict:
        """The one target's line of the job's line, after checking it is the one served and the job's ``ok`` is it."""
        [line] = out["targets"]
        self.assertEqual(line["target"], tid)
        self.assertEqual(out["ok"], line["ok"])
        return line

    @property
    def root(self) -> str:
        return os.path.join(self.temp, "out", "response")

    @property
    def out(self) -> str:
        return os.path.join(self.root, "t1")

    def response(self, tid: str = "t1") -> dict:
        with open(os.path.join(self.root, tid, CG.RESPONSE)) as fh:
            return json.load(fh)

    def calls(self) -> list[dict]:
        return fake_claude.calls(self.bin)

    def assert_nothing(self) -> None:
        self.assertEqual(self.calls(), [])
        self.assertFalse(os.path.lexists(self.root))

    def no_verdict(self, **env) -> None:
        with self.assertRaises(J.Unusable):
            self.run_cagir(**env)
        self.assert_nothing()

    def test_the_canary_call_and_its_response(self):
        ledger = ledger_with_costs(200_000, 50_000)
        self.write(ledger=ledger)
        job = self.run_cagir()
        out = self.line(job)
        self.assertEqual((job["ok"], out["ok"], out["done"], job["job"]), (True, True, ["D4"], "cagir"))
        self.assertNotIn("reason", job)
        self.assertEqual(out["call"], {"outcome": "ok", "reason": None, "sent": True, "models_served": [MODEL],
                                       "cost_usd_micros": 12346})
        self.assertEqual(out["claude_sha512"], L.sha512_file(self.claude))
        [call] = self.calls()
        # the prompt, written out by hand: the template's text with the id in its JSON form, on stdin only
        prompt = ('This is the canary call of the Snowball loop for the target "t1". Reply only with the '
                  'structured output: echo is the target\'s name as given, without quotes.')
        self.assertEqual(call["stdin"], prompt)
        self.assertNotIn(prompt, " ".join(call["argv"]))
        argv = call["argv"]
        self.assertEqual(argv[argv.index("--model") + 1], MODEL)
        # canary_usd 1 USD, the ledger's cost rows spent 0.25 of it: the call may spend the rest
        self.assertEqual(argv[argv.index("--max-budget-usd") + 1], "0.750000")
        self.assertEqual(call["env"]["CLAUDE_CODE_OAUTH_TOKEN"], TOKEN)
        got = self.response()
        [row] = got["rows"]
        self.assertEqual({k: got[k] for k in ("schema", "target", "heads", "outcome", "reason", "sent", "run_valid",
                                              "output", "models_served", "cost_usd_micros", "dropped")},
                         {"schema": "snowball-response/1", "target": "t1", "heads": HEADS, "outcome": "ok",
                          "reason": None, "sent": True, "run_valid": True, "output": OUTPUT,
                          "models_served": [MODEL], "cost_usd_micros": 12346, "dropped": []})
        self.assertEqual((row["row_id"], row["ts"], row["snapshot_id"], row["part"], row["kind"]),
                         ("cagir-77-2", "2026-11-01T13:30:05Z", HEADS["brain/integration"], "cost", "cost"))
        self.assertEqual((row["payload"]["usd_micros"], row["payload"]["cap_usd_micros"],
                          row["payload"]["model_requested"], row["payload"]["prompt_sha256"]),
                         (12346, 750_000, MODEL, got["prompt_sha256"]))
        # D6's input: the rows go onto the ledger pulled carries, through ledger.append's own rules
        led = state_files(ledger)[".brain/ledger.jsonl"]
        cycle = append.plan_cycle(led, led, lambda: json.dumps({"rows": got["rows"]}).encode())
        self.assertEqual(len(cycle.row_hashes), 1)
        self.assertEqual(L.spent_micros([json.loads(x) for x in cycle.content.splitlines()]), 262_346)

    def test_a_fraction_of_a_dollar_is_exact(self):
        # the JSON text's exact value rounded up to a micro-USD (llm_call.to_micros), never through a float
        for canary, cap in (("0.5", "0.500000"), ("0.0000005", "0.000001"), ("5e-1", "0.500000")):
            with self.subTest(canary=canary):
                for d in ("in", "out"):  # not the claude step's CLI, which is under the same RUNNER_TEMP
                    shutil.rmtree(os.path.join(self.temp, d), ignore_errors=True)
                if self.calls():
                    os.remove(os.path.join(self.bin, "calls.jsonl"))
                self.write(canary=canary)
                self.run_cagir()
                argv = self.calls()[0]["argv"]
                self.assertEqual(argv[argv.index("--max-budget-usd") + 1], cap)

    def test_another_served_model_is_written_and_not_ok(self):
        fake_claude.behave(self.bin, result(modelUsage={"claude-haiku-5-5": {"costUSD": 0.001}}))
        self.write()
        out = self.line(self.run_cagir())
        self.assertEqual((out["ok"], out["done"]), (True, ["D4"]))
        got = self.response()
        self.assertEqual((got["outcome"], got["reason"], got["run_valid"]), ("unresolved", "model_mismatch", False))
        self.assertEqual([r["payload"]["models_served"] for r in got["rows"]], [["claude-haiku-5-5"]])

    def test_the_brake_sends_nothing_and_writes_no_row(self):
        self.write(ledger=ledger_with_costs(600_000, 400_000))
        out = self.line(self.run_cagir())
        self.assertEqual((out["ok"], out["call"]["outcome"], out["call"]["sent"]), (True, "brake", False))
        self.assertEqual(self.calls(), [])
        self.assertEqual((self.response()["rows"], self.response()["reason"]), ([], "stage_brake"))

    def test_a_secret_in_the_prompt_is_not_sent(self):
        secret = "ghp_" + "A1b2C3d4" * 4 + "Zz9Y"
        self.serve(dict(TARGET, id=secret))
        out = self.line(self.run_cagir(), secret)
        self.assertEqual((out["call"]["outcome"], out["call"]["sent"]), ("secret", False))
        self.assertEqual((self.calls(), self.response(secret)["rows"]), ([], []))

    def test_a_refused_pulled_starts_nothing(self):
        self.write()
        with open(os.path.join(self.pulled, "state", "ledger.jsonl"), "ab") as fh:
            fh.write(b"\n")
        job = self.run_cagir()
        out = self.line(job)
        for line in (job, out):
            self.assertEqual((line["ok"], line["reason"], line["reasons"]), (False, "pulled_invalid",
                                                                             ["hash_mismatch:state/ledger.jsonl"]))
        self.assertEqual(job["target"], "t1")
        self.assert_nothing()

    def test_a_pulled_of_another_target_starts_nothing(self):
        # in/pulled/t1 holding target t2's artifact (every hash in it right): the directory names the target
        self.write(target=dict(TARGET, id="t2"))
        job = self.run_cagir()
        out = self.line(job)
        for line in (job, out):
            self.assertEqual((line["ok"], line["reason"], line["reasons"]),
                             (False, "pulled_invalid", ["target_mismatch"]))
        self.assertNotIn("call", out)
        self.assert_nothing()

    def test_an_unreadable_served_list_starts_nothing(self):
        self.write()
        with open(os.path.join(os.path.dirname(self.pulled), P.SERVED), "w") as fh:
            json.dump({"schema": P.SERVED_SCHEMA, "targets": ["t1", "t1"]}, fh)
        job = self.run_cagir()
        self.assertEqual((job["ok"], job["reason"], job["reasons"]), (False, "pulled_invalid", ["served_unreadable"]))
        self.assertNotIn("targets", job)
        self.assert_nothing()

    def test_two_targets_are_called_in_the_served_order(self):
        # t2 listed first: the order is served.json's, not the names'
        self.serve(dict(TARGET, id="t2"), TARGET)
        fake_claude.behave(self.bin, result(structured_output={"echo": "t2"}))
        job = self.run_cagir()
        self.assertEqual((job["ok"], [t["target"] for t in job["targets"]]), (True, ["t2", "t1"]))
        for line in job["targets"]:
            self.assertEqual((line["ok"], line["done"], line["call"]["sent"]), (True, ["D4"], True))
        self.assertEqual(sorted(os.listdir(self.root)), ["t1", "t2"])
        self.assertEqual([self.response(t)["target"] for t in ("t2", "t1")], ["t2", "t1"])
        calls = self.calls()
        self.assertEqual(len(calls), 2)
        self.assertEqual(['"t2"' in calls[0]["stdin"], '"t1"' in calls[1]["stdin"]], [True, True])
        # each response's row is its own call's, with the run's row id
        self.assertEqual([self.response(t)["rows"][0]["row_id"] for t in ("t2", "t1")], ["cagir-77-2"] * 2)

    def test_a_canary_budget_that_is_no_amount_is_no_verdict(self):
        for canary in ("true", '"1"', "-1", "null"):
            with self.subTest(canary=canary):
                shutil.rmtree(self.pulled, ignore_errors=True)
                self.write(canary=canary)
                self.no_verdict()
        shutil.rmtree(self.pulled)
        self.write_pulled(policy={"operating": operating()})
        self.no_verdict()

    def test_a_ledger_that_is_not_a_chain_is_no_verdict(self):
        state = state_files(ledger_with_costs(1))
        state[".brain/ledger.jsonl"] = state[".brain/ledger.jsonl"].replace(b'"usd_micros": 1', b'"usd_micros": 0')
        self.write_pulled(policy=policy(), state=state)
        self.no_verdict()

    def test_the_model_is_bootstrap_json_s_and_no_variable_is_read(self):
        write_bootstrap(self.work, {"rival": {"model": "claude-other-model"}})  # cagir needs no brain_repo
        fake_claude.behave(self.bin, result(modelUsage={"claude-other-model": {"costUSD": 0.01}}))
        self.write()
        out = self.line(self.run_cagir(LOOP_CANARY_MODEL=MODEL, CANARY_MODEL=MODEL, LOOP_CLAUDE_SHA512="0" * 128))
        self.assertEqual(out["call"]["outcome"], "ok")
        argv = self.calls()[0]["argv"]
        self.assertEqual(argv[argv.index("--model") + 1], "claude-other-model")

    def test_an_unusable_bootstrap_starts_nothing(self):
        self.write()
        for boot in (ABSENT, b"{", b'{"rival": {"model": "a"}, "rival": {"model": "b"}}', b"[]", {"rival": "m"},
                     {"rival": {}}, {"rival": {"model": ""}}, {"rival": {"model": " "}}, {"rival": {"model": 5}},
                     {"model": MODEL}, b'{"rival": {"model": "m"}}'.ljust(inputs.MAX_BOOTSTRAP + 1)):
            with self.subTest(bootstrap=boot):
                write_bootstrap(self.work, boot)
                with self.assertRaisesRegex(J.Unusable, "bootstrap_unreadable|rival_model_invalid"):
                    self.run_cagir()
                self.assert_nothing()

    def test_a_bootstrap_at_the_size_bound_is_read(self):
        self.write()
        write_bootstrap(self.work, ('{"rival": {"model": "%s"}}' % MODEL).encode().ljust(inputs.MAX_BOOTSTRAP))
        self.assertEqual(self.line(self.run_cagir())["call"]["outcome"], "ok")

    def test_the_cli_is_the_step_s_not_one_on_path(self):
        self.write()
        on_path = os.path.join(self.base, "path-bin")
        os.makedirs(on_path)
        fake_claude.install(on_path)
        fake_claude.behave(on_path, result())
        os.remove(self.claude)
        with self.assertRaisesRegex(J.Unusable, "claude_missing"):
            self.run_cagir(PATH=on_path + os.pathsep + os.environ.get("PATH", ""))
        self.assertEqual(fake_claude.calls(on_path), [])
        self.assert_nothing()

    def test_the_environment(self):
        self.write()
        for name in J.CAGIR_ENV:
            with self.subTest(unset=name):
                self.no_verdict(**{name: None})
        os.makedirs(self.out)
        with self.assertRaises(J.Unusable):
            self.run_cagir()
        self.assertEqual((self.calls(), os.listdir(self.out)), ([], []))


if __name__ == "__main__":
    unittest.main()
