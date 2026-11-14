"""Test 46 (asama-0/09), MF17: the loop workflow ``referee/.github/workflows/loop.yml``.

The rules are read from the spec, not from ``loop.job`` (``violations`` below does not import it), so a mistake
in the registry or the emitter shows as a violation of the committed file:

- ``top_permissions``: the top-level ``permissions`` is ``{}``;
- ``workflow_control_context`` (tohum/29p, by allow-list): the workflow has only the keys of ``WORKFLOW_KEYS``
  (``:workflow``) and each job only those of ``JOB_KEYS`` (``:<job>``), a job without ``steps`` also ``uses``,
  ``with`` and ``secrets`` (such a job fails ``workflow_control_step``). So ``env``, ``defaults``, ``container``,
  ``services`` and every unnamed key are refused;
- ``trigger``: ``on`` is only ``schedule`` and ``workflow_dispatch`` (so never ``pull_request_target``,
  ``workflow_run``, ``issue_comment``, ``push``, ``pull_request``);
- ``job_set``: exactly the five jobs of tohum/08 (``cek``, ``getir``, ``kos``, ``cagir``, ``yaz``);
- ``job_not_main``: every job's ``if`` is exactly ``github.ref == 'refs/heads/main'``;
- ``workflow_control_step`` (tohum/29p): every job's first step is, as parsed, exactly ``control_step(job)``, 29p's
  step with ``LOOP_JOB`` the job's own name and no other key; ``control_elsewhere``: no later step runs the
  seed's ``python3 -m snowball_bootstrap control``;
- ``workflow_control_gate`` (tohum/29p): every later step's ``if`` is exactly ``steps.control.outputs.go == 'true'``,
  and
  ``continue_on_error``: nothing continues on error, so a failing ``control`` (kill switch) stops the job;
- ``github_expr_in_run``: no ``${{`` holding ``github`` in any ``run:`` (``expr_in_run``: no ``${{`` at all);
- ``unpinned_action``: every ``uses`` is ``owner/repo@<40 hex>``; ``persist_credentials``: every checkout has
  ``persist-credentials: false``;
- ``permissions_missing``: every job states its permissions; ``code_job_permissions`` and
  ``secret_in_code_job``: ``getir`` and ``kos`` (the jobs that run code) have ``permissions: {}`` and no
  ``secrets.``/``github.token`` expression; ``secret_outside``: secrets appear only in ``cek`` (``github.token``
  only: D1 reads the bootstrap state through the Actions API, asama-0/01), ``cagir`` (``CLAUDE_CODE_OAUTH_TOKEN``
  only) and ``yaz``;
- ``secret_job_runs_code``: a job holding a secret or a permission uses only checkout of its own commit
  (``foreign_checkout`` otherwise), the artifact actions and (``yaz``) the App token action, and runs only
  ``control``, its ``python3 -m loop.job run <job>`` and the install steps ``INSTALLS`` gives it, each exactly
  ``install_step(name)``; ``unknown_run``: the same for the code jobs, which have none;
- ``install_missing`` (tohum/29s): ``cek`` and ``yaz`` run the ``sigstore`` step (``cek`` verifies, ``yaz`` signs)
  and ``cagir`` the ``claude`` step, each once and before the job's ``python3 -m loop.job run`` (``install_order``
  otherwise); an install step carries no secret, since its step has no ``env``;
- ``operator_variable`` (tohum/29s: no input of a run is an operator variable): no expression of any job holds the
  ``vars`` context (``vars.X``, ``vars['X']``, ``toJSON(vars)``);
- ``writer_scope`` (tohum/25 item 6, 29s "Hedefler"): ``yaz`` runs ``SCOPE_STEP`` (``python3 -m loop.job scope``,
  the only other run a job holding a secret may have, and only in ``yaz``) once, before its one App token step,
  whose ``owner`` and ``repositories`` are that step's outputs: the token is scoped to the repositories of
  ``targets[]`` in the run's own ``setup/summary.json``.

Stricter than 29p, on purpose: a job's ``if`` must be ``job_not_main``'s and no job or step continues on error
(29p allows both keys). ``control_step`` is a copy of 29p's text; ``tests/test_control_step_spec.py`` at the
brain's root compares it with the block in ``spec/tohum/29p-kontrol-komutu.md``, so the copy cannot drift.
``install_step`` holds copies of 29s's two steps, bound to that page by ``tests/test_install_steps_spec.py`` the same
way.

Each rule is shown to fire on a mutated copy of the committed file and not on the file itself. Also: the file
is ``loop.job.render()`` byte for byte (and the CLI's output); the parser's subset refusals; the registry covers
D1-D8 and the step table's MFs; the gating, run under a model of Actions' step and job conditions, stops every
job at a failing ``control`` and ends a paused job green with nothing run; ``python -m loop.job run``'s refusal
of a secret in a code job, and every job's entry without its inputs is no verdict (exit 2); the steps themselves
are each job's test file (``cek`` D1 ``test_loop_cek.py``, ``getir`` D2 ``test_loop_getir.py``, ``kos`` D3 and D7
``test_loop_kos.py``, ``cagir`` D4 ``test_loop_cagir.py``, ``yaz`` D5 and its stop
``test_loop_yaz.py``).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

REFEREE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REFEREE)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from workflow_yaml import Unparseable, parse  # noqa: E402

WORKFLOW = os.path.join(REFEREE, ".github", "workflows", "loop.yml")

JOBS = ("cek", "getir", "kos", "cagir", "yaz")         # tohum/08 item 1
CODE_JOBS = ("getir", "kos")                            # run code: no secret, no permission
# None: any (writer App, OIDC). cek: only the job's own token, for D1's Actions read (asama-0/01, actions: read)
SECRETS_ALLOWED = {"cek": {"github.token"}, "cagir": {"CLAUDE_CODE_OAUTH_TOKEN"}, "yaz": None}
MAIN = "github.ref == 'refs/heads/main'"
GATE = "steps.control.outputs.go == 'true'"
CONTROL = re.compile(r"(?m)^python3 -m snowball_bootstrap control( |$)")
PIN = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(/[A-Za-z0-9_./-]+)?@[0-9a-f]{40}")
SECRET_EXPR = re.compile(r"\$\{\{\s*(secrets\.([A-Za-z0-9_]+)|github\.token)")
SECRET_JOB_ACTIONS = ("actions/checkout@", "actions/download-artifact@", "actions/upload-artifact@")
APP_ACTION = "actions/create-github-app-token@"

# tohum/29p "Adım": every job's first step, byte for byte; ``LOOP_JOB`` is the job's name.
CONTROL_RUN = (
    'set -eu\n'
    'git clone --quiet --depth 1 --branch main --filter=blob:none --sparse "$GITHUB_SERVER_URL/$GITHUB_REPOSITORY"'
    ' "$RUNNER_TEMP/control"\n'
    'git -C "$RUNNER_TEMP/control" sparse-checkout set bootstrap\n'
    'cd "$RUNNER_TEMP/control/bootstrap"\n'
    'python3 -m snowball_bootstrap control --control ../control.json --job "$LOOP_JOB" --event "$GITHUB_EVENT_NAME"'
    ' --github-output "$GITHUB_OUTPUT"\n'
)
# tohum/29s "Sigstore" and "Kanaryanın claude CLI'si": the two install steps, byte for byte, and the jobs that run them.
INSTALL_RUN = {
    "sigstore": (
        'set -eu\n'
        'cd "$RUNNER_TEMP/control/bootstrap"\n'
        'python3 -m venv "$RUNNER_TEMP/sig"\n'
        '"$RUNNER_TEMP/sig/bin/pip" download --quiet --require-hashes --only-binary=:all: --no-deps'
        ' -d "$RUNNER_TEMP/sigw" -r requirements/sign.txt\n'
        'python3 -m snowball_bootstrap licenses --root .. --wheels "$RUNNER_TEMP/sigw"\n'
        '"$RUNNER_TEMP/sig/bin/pip" install --quiet --no-index --find-links "$RUNNER_TEMP/sigw" --require-hashes'
        ' --only-binary=:all: --no-deps -r requirements/sign.txt\n'),
    "claude": (
        'set -eu\n'
        'C="$RUNNER_TEMP/control/bootstrap/requirements/claude-cli"\n'
        'node -e \'process.exit(Number(process.versions.node.split(".")[0]) >= 22 ? 0 : 1)\'\n'
        'npm ci --prefix "$C" --no-audit --no-fund\n'
        'pinned=$(node -p "require(\'$C/package.json\').dependencies[\'@anthropic-ai/claude-code\']")\n'
        'test "$("$C/node_modules/.bin/claude" --version | cut -d\' \' -f1)" = "$pinned"\n'),
}
INSTALLS = {"cek": ("sigstore",), "yaz": ("sigstore",), "cagir": ("claude",)}  # 29s: who verifies, signs, calls
# tohum/29s: no input of a run is an operator variable: any ``vars`` context in an expression (``vars.X``,
# ``vars['X']``, ``toJSON(vars)``).
VARS_EXPR = re.compile(r"\$\{\{[^}]*\bvars\b")
# yaz's writer token scope (tohum/25 item 6, 29s "Hedefler"): the step, and the token's inputs it gives.
SCOPE_STEP = {"name": "writer scope", "id": "scope", "if": GATE, "run": "python3 -m loop.job scope\n"}
SCOPE_INPUTS = {"owner": "${{ steps.scope.outputs.owner }}", "repositories": "${{ steps.scope.outputs.repositories }}"}

# tohum/29p "wiring kuralı": the keys allowed, everything else refused.
WORKFLOW_KEYS = {"name", "run-name", "on", "permissions", "concurrency", "jobs"}
JOB_KEYS = {"name", "if", "needs", "runs-on", "permissions", "environment", "concurrency", "outputs",
            "timeout-minutes", "strategy", "continue-on-error", "steps"}
CALL_KEYS = {"uses", "with", "secrets"}  # a workflow call: allowed keys, refused by the first-step rule


def control_step(job: str) -> dict:
    return {"name": "control", "id": "control", "env": {"LOOP_JOB": job}, "run": CONTROL_RUN}


def install_step(name: str) -> dict:
    return {"name": name, "if": GATE, "run": INSTALL_RUN[name]}


def committed() -> str:
    with open(WORKFLOW, encoding="utf-8") as fh:
        return fh.read()


def _strings(value):
    if isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)
    elif isinstance(value, str):
        yield value


def violations(doc: dict) -> list[str]:
    out: list[str] = []
    if doc.get("permissions") != {}:
        out.append("top_permissions")
    if set(doc) - WORKFLOW_KEYS:
        out.append("workflow_control_context:workflow")
    triggers = doc.get("on")
    if not isinstance(triggers, dict) or not triggers or set(triggers) - {"schedule", "workflow_dispatch"}:
        out.append("trigger")
    jobs = doc.get("jobs")
    if not isinstance(jobs, dict) or tuple(sorted(jobs)) != tuple(sorted(JOBS)):
        out.append("job_set")
    for name, job in (jobs or {}).items():
        where = ":" + name
        if not isinstance(job, dict):
            out.append("job_set" + where)
            continue
        if job.get("if") != MAIN:
            out.append("job_not_main" + where)
        if set(job) - JOB_KEYS - (CALL_KEYS if "steps" not in job else set()):
            out.append("workflow_control_context" + where)
        if "continue-on-error" in job:
            out.append("continue_on_error" + where)
        if "permissions" not in job:
            out.append("permissions_missing" + where)
        perms = job.get("permissions")
        secrets = {m.group(2) or "github.token" for s in _strings(job) for m in SECRET_EXPR.finditer(s)}
        holds_secret = bool(secrets) or perms not in ({}, None)
        if name in CODE_JOBS:
            if perms != {}:
                out.append("code_job_permissions" + where)
            if secrets:
                out.append("secret_in_code_job" + where)
        elif secrets:
            allowed = SECRETS_ALLOWED.get(name, set())
            if allowed is not None and not secrets <= allowed:
                out.append("secret_outside" + where)
        if any(VARS_EXPR.search(s) for s in _strings(job)):
            out.append("operator_variable" + where)
        steps = job.get("steps")
        if not isinstance(steps, list) or not steps:
            out.append("workflow_control_step" + where)
            continue
        names = [step.get("name") if isinstance(step, dict) else None for step in steps]
        entry = names.index(name) if name in names else len(steps)
        for install in INSTALLS.get(name, ()):
            if install_step(install) not in steps:
                out.append("install_missing" + where)
            elif names.count(install) != 1 or steps.index(install_step(install)) > entry:
                out.append("install_order" + where)
        if steps[0] != control_step(name):
            out.append("workflow_control_step" + where)
        if name == "yaz":
            tokens = [i for i, st in enumerate(steps) if isinstance(st, dict)
                      and str(st.get("uses", "")).startswith(APP_ACTION)]
            scoped = [i for i, st in enumerate(steps) if st == SCOPE_STEP]
            if (len(tokens) != 1 or len(scoped) != 1 or scoped[0] > tokens[0]
                    or {k: (steps[tokens[0]].get("with") or {}).get(k) for k in SCOPE_INPUTS} != SCOPE_INPUTS):
                out.append("writer_scope" + where)
        for index, step in enumerate(steps):
            at = "%s:%d" % (where, index)
            if not isinstance(step, dict):
                out.append("step_shape" + at)
                continue
            if "continue-on-error" in step:
                out.append("continue_on_error" + at)
            run, uses = step.get("run"), step.get("uses")
            if isinstance(run, str) and "${{" in run:
                out.append(("github_expr_in_run" if re.search(r"\$\{\{[^}]*github", run) else "expr_in_run") + at)
            if index == 0:
                continue
            if step.get("if") != GATE:
                out.append("workflow_control_gate" + at)
            if isinstance(run, str):
                if CONTROL.search(run):
                    out.append("control_elsewhere" + at)
                installed = any(step == install_step(i) for i in INSTALLS.get(name, ()))
                installed = installed or (name == "yaz" and step == SCOPE_STEP)
                if run != "python3 -m loop.job run %s\n" % name and not installed:
                    out.append(("secret_job_runs_code" if holds_secret else "unknown_run") + at)
            if uses is not None:
                if not isinstance(uses, str) or not PIN.fullmatch(uses):
                    out.append("unpinned_action" + at)
                    continue
                allowed_actions = SECRET_JOB_ACTIONS + ((APP_ACTION,) if name == "yaz" else ())
                if holds_secret and not uses.startswith(allowed_actions):
                    out.append("secret_job_runs_code" + at)
                if uses.startswith("actions/checkout@"):
                    given = step.get("with") or {}
                    if given.get("persist-credentials") != "false":
                        out.append("persist_credentials" + at)
                    if set(given) - {"persist-credentials"}:
                        out.append("foreign_checkout" + at)
    return out


def rules(text: str) -> set[str]:
    return {v.split(":")[0] for v in violations(parse(text))}


class Committed(unittest.TestCase):
    def test_file_is_the_registry_rendered(self):
        from loop import job
        self.assertEqual(committed(), job.render())
        self.assertEqual(parse(committed()), job.workflow())

    def test_cli_render_is_the_file(self):
        proc = subprocess.run([sys.executable, "-m", "loop.job", "render"], cwd=REFEREE, capture_output=True)
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(proc.stdout.decode("utf-8"), committed())

    def test_file_keeps_every_rule(self):
        self.assertEqual(violations(parse(committed())), [])

    def test_file_shape(self):
        doc = parse(committed())
        self.assertEqual(set(doc["on"]), {"schedule", "workflow_dispatch"})
        for name in JOBS:
            steps = doc["jobs"][name]["steps"]
            self.assertEqual(steps[0]["id"], "control")
            self.assertEqual(steps[0]["env"], {"LOOP_JOB": name})
            self.assertIn({"name": name, "if": GATE, "run": "python3 -m loop.job run %s\n" % name},
                          [{k: s[k] for k in ("name", "if", "run") if k in s} for s in steps])
        self.assertEqual(doc["jobs"]["kos"]["permissions"], {})
        self.assertEqual(doc["jobs"]["yaz"]["permissions"], {"id-token": "write", "contents": "read"})


def _sub(text: str, old: str, new: str, count: int = 1) -> str:
    assert old in text, old
    return text.replace(old, new, count)


def _job(text: str, name: str) -> tuple[int, int]:
    start = text.index("\n  %s:\n" % name) + 1
    nxt = re.search(r"\n  [a-z]+:\n", text[start + 1:])
    return start, (start + 1 + nxt.start() + 1) if nxt else len(text)


def _in_job(text: str, name: str, old: str, new: str) -> str:
    start, end = _job(text, name)
    return text[:start] + _sub(text[start:end], old, new) + text[end:]


class EachRuleFires(unittest.TestCase):
    """Each mutation breaks one rule of test 46; the rule must fire and the committed file must not."""

    def fires(self, rule: str, text: str):
        self.assertNotIn(rule, rules(committed()))
        self.assertIn(rule, rules(text), text if len(text) < 400 else rule)

    def test_top_permissions(self):
        self.fires("top_permissions", _sub(committed(), "permissions: {}\nconcurrency",
                                           "permissions:\n  contents: write\nconcurrency"))
        self.fires("top_permissions", _sub(committed(), "permissions: {}\nconcurrency", "concurrency"))

    def test_context_allow_list(self):
        for added in ("env:\n  T: ${{ secrets.T }}\n", "defaults:\n  run:\n    shell: bash\n", "x-extra: y\n"):
            with self.subTest(workflow=added):
                self.fires("workflow_control_context", _sub(committed(), "permissions: {}\n", "permissions: {}\n" + added))
        for added in ("env:\n      A: b\n", "defaults:\n      run:\n        working-directory: x\n",
                      "container: node:22\n", "services:\n      db:\n        image: postgres\n", "steps-x: y\n",
                      "uses: o/r/.github/workflows/w.yml@" + "0" * 40 + "\n"):
            with self.subTest(job=added):
                self.fires("workflow_control_context",
                           _in_job(committed(), "cek", "    runs-on:", "    " + added + "    runs-on:"))
        # The allowed keys pass the rule (``continue-on-error`` is allowed here, refused by continue_on_error).
        for added in ("environment: loop\n", "strategy:\n      fail-fast: 'false'\n", "name: cek\n",
                      "concurrency: x\n", "continue-on-error: 'false'\n"):
            with self.subTest(allowed=added):
                text = _in_job(committed(), "kos", "    runs-on:", "    " + added + "    runs-on:")
                self.assertNotIn("workflow_control_context", rules(text))
        self.assertNotIn("workflow_control_context", rules(_sub(committed(), "on:\n", "run-name: loop\non:\n")))

    def test_workflow_call_job(self):
        # A job that calls a workflow has no steps: its uses/with/secrets are allowed keys, the first step is missing.
        start, end = _job(committed(), "cagir")
        call = "  cagir:\n    if: github.ref == 'refs/heads/main'\n    permissions: {}\n    uses: o/r/.github/workflows/w.yml@%s\n    with:\n      a: b\n    secrets:\n      t: x\n" % ("0" * 40)
        found = violations(parse(committed()[:start] + call + committed()[end:]))
        self.assertIn("workflow_control_step:cagir", found)
        self.assertNotIn("workflow_control_context:cagir", found)

    def test_triggers(self):
        for event in ("pull_request_target", "workflow_run", "issue_comment", "push", "pull_request"):
            with self.subTest(event=event):
                self.fires("trigger", _sub(committed(), "  workflow_dispatch: {}\n",
                                           "  workflow_dispatch: {}\n  %s: {}\n" % event))

    def test_job_set(self):
        self.fires("job_set", committed() + "  extra:\n    if: x\n    steps: []\n")
        start, end = _job(committed(), "cagir")
        self.fires("job_set", committed()[:start] + committed()[end:])

    def test_job_only_on_main(self):
        self.fires("job_not_main", _in_job(committed(), "yaz", "    if: github.ref == 'refs/heads/main'\n",
                                           "    if: always()\n"))
        self.fires("job_not_main", _in_job(committed(), "getir", "    if: github.ref == 'refs/heads/main'\n", ""))

    def test_first_step_is_control(self):
        text = committed()
        start, end = _job(text, "kos")
        block = text[start:end]
        control = block[block.index("      - name: control\n"):block.index("      - name: checkout\n")]
        checkout = block[block.index("      - name: checkout\n"):block.index("      - name: download pulled\n")]
        swapped = block.replace(control + checkout, checkout + control)
        self.fires("workflow_control_step", text[:start] + swapped + text[end:])
        self.fires("workflow_control_step", _in_job(text, "cagir", "python3 -m snowball_bootstrap control",
                                                    "python3 -m snowball_bootstrap status"))
        self.fires("workflow_control_step", _in_job(text, "cek", "        id: control\n",
                                                    "        id: control\n        if: always()\n"))

    def test_control_step_exact(self):
        text = committed()
        mutants = {
            "other job's name": ("cek", "          LOOP_JOB: cek\n", "          LOOP_JOB: kos\n"),
            "extra env": ("getir", "          LOOP_JOB: getir\n", "          LOOP_JOB: getir\n          X: y\n"),
            "shell": ("kos", "        id: control\n", "        id: control\n        shell: bash\n"),
            "other name": ("yaz", "      - name: control\n", "      - name: kontrol\n"),
            "no name": ("yaz", "      - name: control\n        id: control\n", "      - id: control\n"),
            "line before": ("cagir", "          set -eu\n", "          echo '{}' > ../control.json\n          set -eu\n"),
            "no set -eu": ("cek", "          set -eu\n", ""),
            "other branch": ("kos", "--branch main", "--branch dev"),
            "other control file": ("getir", "--control ../control.json", "--control ./control.json"),
            "spacing": ("yaz", "--job \"$LOOP_JOB\"", "--job  \"$LOOP_JOB\""),
            "job by literal": ("cek", "--job \"$LOOP_JOB\"", "--job cek"),
        }
        for label, (job, old, new) in mutants.items():
            with self.subTest(mutant=label):
                found = violations(parse(_in_job(text, job, old, new)))
                self.assertIn("workflow_control_step:" + job, found)
                self.assertEqual([v for v in found if v.startswith("workflow_control_step")],
                                 ["workflow_control_step:" + job])

    def test_control_only_first(self):
        self.fires("control_elsewhere", _in_job(committed(), "kos", "python3 -m loop.job run kos\n",
                                                "python3 -m loop.job run kos\n          python3 -m snowball_bootstrap control\n"))

    def test_later_steps_gated_and_nothing_continues(self):
        self.fires("workflow_control_gate", _in_job(committed(), "yaz", "      - name: checkout\n        if: steps.control.outputs.go == 'true'\n",
                                             "      - name: checkout\n"))
        self.fires("workflow_control_gate", _in_job(committed(), "kos", "      - name: kos\n        if: steps.control.outputs.go == 'true'\n",
                                             "      - name: kos\n        if: always()\n"))
        for form in ("${{ steps.control.outputs.go == 'true' }}", "always() && steps.control.outputs.go == 'true'",
                     "steps.control.outputs.go != 'false'"):
            with self.subTest(form=form):
                self.fires("workflow_control_gate", _in_job(committed(), "getir",
                                                            "      - name: getir\n        if: steps.control.outputs.go == 'true'\n",
                                                            "      - name: getir\n        if: %s\n" % form))
        self.fires("continue_on_error", _in_job(committed(), "cek", "        id: control\n",
                                                "        id: control\n        continue-on-error: true\n"))
        self.fires("continue_on_error", _in_job(committed(), "kos", "    timeout-minutes: 60\n",
                                                "    timeout-minutes: 60\n    continue-on-error: true\n"))

    def test_no_github_expression_in_run(self):
        for expr in ("${{ github.event.inputs.x }}", "${{ github.head_ref }}", "${{github.event.issue.title}}"):
            with self.subTest(expr=expr):
                self.fires("github_expr_in_run", _in_job(committed(), "kos", "python3 -m loop.job run kos\n",
                                                         "python3 -m loop.job run kos\n          echo %s\n" % expr))
        self.fires("expr_in_run", _in_job(committed(), "cek", "cd \"$RUNNER_TEMP/control/bootstrap\"\n",
                                          "cd \"${{ runner.temp }}/control/bootstrap\"\n"))

    def test_actions_pinned(self):
        sha = "3d3c42e5aac5ba805825da76410c181273ba90b1"
        for ref in ("v7.0.1", "main", sha[:12], sha.upper()):
            with self.subTest(ref=ref):
                self.fires("unpinned_action", _sub(committed(), "actions/checkout@" + sha, "actions/checkout@" + ref))
        self.fires("unpinned_action", _sub(committed(), "actions/checkout@" + sha, "./local-action"))
        self.fires("unpinned_action", _sub(committed(), "actions/checkout@" + sha, "docker://alpine:3"))

    def test_persist_credentials(self):
        self.fires("persist_credentials", _sub(committed(), "persist-credentials: false", "persist-credentials: true"))
        self.fires("persist_credentials", _in_job(committed(), "getir", "        with:\n          persist-credentials: false\n", ""))

    def test_permissions_stated(self):
        self.fires("permissions_missing", _in_job(committed(), "cagir", "    permissions: {}\n", ""))

    def test_code_jobs_hold_nothing(self):
        self.fires("code_job_permissions", _in_job(committed(), "kos", "    permissions: {}\n",
                                                   "    permissions:\n      contents: read\n"))
        self.fires("secret_in_code_job", _in_job(committed(), "kos", "          LOOP_DEPS_DIGEST:",
                                                 "          CLAUDE_CODE_OAUTH_TOKEN: ${{ secrets.CLAUDE_CODE_OAUTH_TOKEN }}\n          LOOP_DEPS_DIGEST:"))
        self.fires("secret_in_code_job", _in_job(committed(), "getir", "          LOOP_PULLED_DIGEST:",
                                                 "          GH: ${{ github.token }}\n          LOOP_PULLED_DIGEST:"))

    def test_secrets_only_where_the_table_puts_them(self):
        self.fires("secret_outside", _in_job(committed(), "cek", "          GITHUB_TOKEN: ${{ github.token }}\n",
                                             "          GITHUB_TOKEN: ${{ github.token }}\n          K: ${{ secrets.WRITER_APP_PRIVATE_KEY }}\n"))
        self.fires("secret_outside", _in_job(committed(), "cagir", "          CLAUDE_CODE_OAUTH_TOKEN:",
                                             "          W: ${{ secrets.WRITER_APP_ID }}\n          CLAUDE_CODE_OAUTH_TOKEN:"))

    def test_secret_jobs_run_no_code(self):
        self.fires("secret_job_runs_code", _in_job(committed(), "yaz", "python3 -m loop.job run yaz\n",
                                                   "python3 -m loop.job run yaz\n          npm test\n"))
        self.fires("secret_job_runs_code", _in_job(committed(), "cagir", "python3 -m loop.job run cagir\n",
                                                   "python3 -m loop.job run kos\n"))
        pinned = "actions/setup-node@" + "0" * 40
        self.fires("secret_job_runs_code", _in_job(committed(), "cek", "uses: actions/checkout@",
                                                   "uses: %s\n        with:\n          x: y\n      - name: c2\n        if: steps.control.outputs.go == 'true'\n        uses: actions/checkout@" % pinned))
        self.fires("secret_job_runs_code", _in_job(committed(), "cagir", "uses: actions/download-artifact@9000827ccba6bdab643e8b6fd33ac0654aef8333",
                                                   "uses: actions/create-github-app-token@64ab729a6294000f5aa4a4bc0b73d1f32bc45510"))
        self.fires("foreign_checkout", _in_job(committed(), "cagir", "          persist-credentials: false\n",
                                               "          persist-credentials: false\n          repository: someone/brain\n"))
        self.fires("foreign_checkout", _in_job(committed(), "yaz", "          persist-credentials: false\n",
                                               "          persist-credentials: false\n          ref: brain/c/1\n"))

    def _install_block(self, text: str, job: str, name: str) -> str:
        start, end = _job(text, job)
        block = text[start:end]
        i = block.index("      - name: %s\n" % name)
        return block[i:block.index("      - name: ", i + 1)]

    def test_install_steps(self):
        text = committed()
        sig, cla = self._install_block(text, "cek", "sigstore"), self._install_block(text, "cagir", "claude")
        self.assertEqual(self._install_block(text, "yaz", "sigstore"), sig)
        for job, block in (("cek", sig), ("yaz", sig), ("cagir", cla)):
            with self.subTest(removed=job):
                self.fires("install_missing", _in_job(text, job, block, ""))
        # one changed byte, or a secret given to the step: not 29s's step, so neither installed nor allowed
        for old, new in (("--require-hashes --only-binary", "--only-binary"), ("        run: |\n",
                          "        env:\n          T: ${{ secrets.CLAUDE_CODE_OAUTH_TOKEN }}\n        run: |\n")):
            with self.subTest(changed=new):
                found = rules(_in_job(text, "cek", sig, sig.replace(old, new, 1)))
                self.assertTrue({"install_missing", "secret_job_runs_code"} <= found, found)
        changed = cla.replace("--no-audit", "--ignore-scripts=false --no-audit")
        self.assertTrue({"install_missing", "secret_job_runs_code"} <= rules(_in_job(text, "cagir", cla, changed)))
        # after the job's entry, or twice
        start, end = _job(text, "yaz")
        moved = text[start:end].replace(sig, "")
        i = moved.index("        run: |\n          python3 -m loop.job run yaz\n")
        j = i + len("        run: |\n          python3 -m loop.job run yaz\n")
        self.fires("install_order", text[:start] + moved[:j] + sig + moved[j:] + text[end:])
        self.fires("install_order", _in_job(text, "cek", sig, sig + sig))
        # an install step in a job 29s does not give it
        self.fires("secret_job_runs_code", _in_job(text, "yaz", sig, sig + cla))
        start, end = _job(text, "kos")
        block = text[start:end]
        self.fires("unknown_run", text[:start] + block.replace("      - name: checkout\n", sig + "      - name: checkout\n", 1)
                   + text[end:])

    def test_operator_variables(self):
        # the refutation's reproducer: no vars context anywhere in the file
        self.assertIsNone(re.search(r"vars\.", committed()))
        self.assertIsNone(VARS_EXPR.search(committed()))
        for job, name in (("cek", "BRAIN_REPO"), ("cagir", "CANARY_MODEL"), ("cagir", "CLAUDE_CLI_SHA512"),
                          ("yaz", "LOOP_TARGETS"), ("cek", "LOOP_TARGET"), ("yaz", "TARGET_OWNER"),
                          ("kos", "X"), ("getir", "X")):
            with self.subTest(var=name):
                self.fires("operator_variable", _in_job(committed(), job, "    timeout-minutes: 60\n",
                                                        "    timeout-minutes: 60\n    env-x: ${{ vars.%s }}\n" % name))
                self.fires("operator_variable", _in_job(committed(), job, "        run: |\n          python3 -m loop.job",
                                                        "        run: |\n          echo ${{vars.%s}}\n          python3 -m loop.job" % name))

        for form in ("${{ vars['LOOP_TARGET'] }}", "${{ toJSON(vars) }}"):
            with self.subTest(form=form):
                self.fires("operator_variable", _in_job(committed(), "cek", "    timeout-minutes: 60\n",
                                                        "    timeout-minutes: 60\n    env-x: %s\n" % form))

    def test_writer_scope(self):
        text = committed()
        start, end = _job(text, "yaz")
        block = text[start:end]
        i = block.index("      - name: writer scope\n")
        scope = block[i:block.index("      - name: ", i + 1)]
        j = block.index("      - name: writer token\n")
        token = block[j:block.index("      - name: ", j + 1)]
        self.fires("writer_scope", _in_job(text, "yaz", scope, ""))
        self.fires("writer_scope", text[:start] + block.replace(scope + token, token + scope) + text[end:])
        self.fires("writer_scope", _in_job(text, "yaz", "owner: ${{ steps.scope.outputs.owner }}", "owner: acme"))
        self.fires("writer_scope", _in_job(text, "yaz", "          repositories: ${{ steps.scope.outputs.repositories }}\n", ""))
        # a changed scope command is neither the scope step nor allowed
        self.assertTrue({"writer_scope", "secret_job_runs_code"} <= rules(
            _in_job(text, "yaz", "python3 -m loop.job scope\n", "python3 -m loop.job scope --any\n")))
        # the scope step in another job is no install there
        self.fires("secret_job_runs_code", _in_job(text, "cek", "      - name: checkout\n", scope + "      - name: checkout\n"))

    def test_code_jobs_run_only_their_entry(self):
        self.fires("unknown_run", _in_job(committed(), "kos", "python3 -m loop.job run kos\n",
                                          "python3 -m loop.job run kos\n          bash ./in/pulled/x.sh\n"))


class Subset(unittest.TestCase):
    def test_accepted(self):
        self.assertEqual(parse("# c\na: b\nc:\n  - d\n  - e: 'it''s'\n    f: |\n      x\n\n      y\n  # c\ng: {}\nh: []\n"),
                         {"a": "b", "c": ["d", {"e": "it's", "f": "x\n\ny\n"}], "g": {}, "h": []})
        self.assertEqual(parse("a: true\nb: 60\n"), {"a": "true", "b": "60"})

    def test_refused(self):
        for text in ("a:\tb\n\tc: d\n", "---\na: b\n", "a: &x b\n", "a: *x\n", "a: !!str b\n", "a: [b, c]\n",
                     "a: {b: c}\n", "a: \"b\"\n", "a: >\n  b\n", "? a\n: b\n", "a: b\na: c\n", "a: b: c\n",
                     "a: b #c\n", "a: b:\n", "a:\n    b: c\n  d: e\n", "a: 'b\n", "a: 'b'c'\n", "a.b: c\n",
                     "- a\n", "", "a: b\n...\n", "a:\n", " a: b\n", "a: |\n", "a:\n  - b\n   c: d\n"):
            with self.subTest(text=text):
                with self.assertRaises(Unparseable):
                    parse(text)


class Emitter(unittest.TestCase):
    def test_scalars_the_plain_form_cannot_hold_are_quoted_and_read_back(self):
        from loop import job
        values = ["a: b", "x #y", "'q", "it's", "-x", "- x", "end:", "*a", "&a", "!t", "{}", "[]", "|", ">", "%d",
                  "@u", "`c`", ",", "?", "#c", " lead", "trail ", "\"q\"", "", "plain", "${{ x }}", "a:b", "x#y"]
        out: list[str] = []
        job._emit({"k%d" % i: v for i, v in enumerate(values)}, 0, out)
        self.assertEqual(parse("\n".join(out) + "\n"), {"k%d" % i: v for i, v in enumerate(values)})
        for plain in ("plain", "${{ x }}", "a:b", "x#y"):
            self.assertIn("k%d: %s" % (values.index(plain), plain), out)

    def test_literal_blocks_outside_the_subset_are_refused(self):
        from loop import job
        for text in ("a\n\n", " a\n", "a \n", "a\n\nb\n"):
            with self.subTest(text=text):
                with self.assertRaises(job.Unusable):
                    job._emit({"run": text}, 0, [])
        with self.assertRaises(job.Unusable):
            job._emit({"a.b": "c"}, 0, [])


class Registry(unittest.TestCase):
    def test_steps_and_mfs_covered(self):
        from loop import job
        self.assertEqual(sorted({s for j in job.JOBS.values() for s in j.steps}), ["D%d" % i for i in range(1, 9)])
        # asama-0/01's judge column names MFs 1-16; 17 is this workflow and 18 runs in (B) by hand
        self.assertEqual(sorted({m for j in job.JOBS.values() for m in j.mfs}), list(range(1, 17)))
        self.assertEqual(tuple(job.JOBS), JOBS)
        self.assertEqual({n for n, j in job.JOBS.items() if j.runs_code}, set(CODE_JOBS))

    def test_a_reader_without_its_producer_is_refused(self):
        from loop import job
        saved = job.JOBS["getir"]
        try:
            job.JOBS["getir"] = saved._replace(needs=())
            with self.assertRaises(job.Unusable):
                job.render()
        finally:
            job.JOBS["getir"] = saved


def simulate(doc: dict, control: dict[str, tuple[int, str]]) -> dict[str, tuple[str, list[str]]]:
    """Actions' conditions for the two forms this workflow uses: a job runs when its ``if`` holds and every job it
    needs succeeded; a step runs when the steps before it succeeded and its ``if`` holds; a failed step fails the
    job. ``control[job]`` is the control step's (exit, go). Any other condition is refused."""
    result: dict[str, tuple[str, list[str]]] = {}
    for name, job in doc["jobs"].items():
        needs = job.get("needs", [])
        if job["if"] != MAIN or any(result[n][0] != "success" for n in needs):
            result[name] = ("skipped", [])
            continue
        ran, failed, outputs = [], False, {}
        for step in job["steps"]:
            cond = step.get("if")
            if cond is None:
                go = not failed
            elif cond == GATE:
                go = not failed and outputs.get("go") == "true"
            else:
                raise AssertionError("condition outside the model: %r" % cond)
            if not go:
                continue
            ran.append(step["name"])
            if step.get("id") == "control":
                code, flag = control[name]
                if code != 0:
                    failed = True
                else:
                    outputs["go"] = flag
        result[name] = ("failure" if failed else "success", ran)
    return result


class Gating(unittest.TestCase):
    def test_kill_switch_stops_every_job(self):
        doc = parse(committed())
        out = simulate(doc, {n: (1, "") for n in JOBS})
        self.assertEqual(out["cek"], ("failure", ["control"]))
        for name in JOBS[1:]:
            self.assertEqual(out[name], ("skipped", []))
        for name in JOBS:  # the switch turned on between jobs: the job that reads it runs nothing else
            flags = {n: (0, "true") for n in JOBS}
            flags[name] = (1, "")
            self.assertEqual(simulate(doc, flags)[name], ("failure", ["control"]))

    def test_paused_is_green_and_runs_nothing(self):
        out = simulate(parse(committed()), {n: (0, "false") for n in JOBS})
        self.assertEqual(out, {n: ("success", ["control"]) for n in JOBS})

    def test_go_runs_every_step(self):
        doc = parse(committed())
        out = simulate(doc, {n: (0, "true") for n in JOBS})
        for name in JOBS:
            self.assertEqual(out[name], ("success", [s["name"] for s in doc["jobs"][name]["steps"]]))


class Scope(unittest.TestCase):
    """``loop.job.scope``: the writer token's owner and repositories from the checkout's ``targets[]``."""

    def workspace(self, targets) -> str:
        root = tempfile.mkdtemp(prefix="t-scope-")
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        os.makedirs(os.path.join(root, "setup"))
        with open(os.path.join(root, "setup", "summary.json"), "w") as fh:
            fh.write(targets if isinstance(targets, str) else json.dumps({"targets": targets}))
        return root

    def scope(self, targets) -> str:
        from loop import job
        return job.scope({"GITHUB_WORKSPACE": self.workspace(targets)})

    def test_every_target_in_order(self):
        toy = {"id": "toy", "kind": "toy", "repo": "acme/toy-repo"}
        copy = {"id": "copy", "kind": "copy", "repo": "acme/copy-repo"}
        self.assertEqual(self.scope([toy, copy]), "owner=acme\nrepositories=toy-repo,copy-repo\n")
        self.assertEqual(self.scope([copy, toy]), "owner=acme\nrepositories=copy-repo,toy-repo\n")
        self.assertEqual(self.scope([toy]), "owner=acme\nrepositories=toy-repo\n")

    def test_unusable(self):
        from loop import job
        toy = {"id": "toy", "kind": "toy", "repo": "acme/toy-repo"}
        for bad in ([toy, {"id": "copy", "kind": "copy", "repo": "other/copy-repo"}],  # two owners
                    [dict(toy, repo="acme/../x")], [dict(toy, repo="acme")], [dict(toy, repo=None)],
                    [], [toy, toy], [dict(toy, kind="real")], [dict(toy, id="../x")], "{", '{"targets": {}}'):
            with self.subTest(bad=bad):
                with self.assertRaises(job.Unusable):
                    self.scope(bad)
        with self.assertRaises(job.Unusable):
            job.scope({})

    def test_command_appends_to_github_output(self):
        ws = self.workspace([{"id": "toy", "kind": "toy", "repo": "acme/toy-repo"}])
        out = os.path.join(ws, "gh-output")
        with open(out, "w") as fh:
            fh.write("go=true\n")
        base = {k: v for k, v in os.environ.items() if k in ("PATH", "HOME", "LANG", "SYSTEMROOT")}
        proc = subprocess.run([sys.executable, "-m", "loop.job", "scope"], cwd=REFEREE, capture_output=True,
                              env=dict(base, GITHUB_WORKSPACE=ws, GITHUB_OUTPUT=out))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        with open(out) as fh:
            self.assertEqual(fh.read(), "go=true\nowner=acme\nrepositories=toy-repo\n")
        proc = subprocess.run([sys.executable, "-m", "loop.job", "scope"], cwd=REFEREE, capture_output=True,
                              env=dict(base, GITHUB_WORKSPACE=ws))
        self.assertEqual(proc.returncode, 2)


def run_job(name: str, env: dict[str, str]) -> tuple[int, dict]:
    base = {k: v for k, v in os.environ.items() if k in ("PATH", "HOME", "LANG", "SYSTEMROOT")}
    proc = subprocess.run([sys.executable, "-m", "loop.job", "run", name], cwd=REFEREE, env=dict(base, **env),
                          capture_output=True)
    return proc.returncode, json.loads(proc.stdout.decode("utf-8"))


class JobEntry(unittest.TestCase):
    def test_code_job_refuses_a_secret(self):
        for name in CODE_JOBS:
            for var in ("CLAUDE_CODE_OAUTH_TOKEN", "WRITER_TOKEN", "GITHUB_TOKEN", "ACTIONS_ID_TOKEN_REQUEST_TOKEN",
                        "ACTIONS_ID_TOKEN_REQUEST_URL"):
                with self.subTest(job=name, var=var):
                    code, out = run_job(name, {var: "x"})
                    self.assertEqual((code, out["ok"], out["reason"]), (1, False, "secret_in_code_job:" + var))

    def test_every_job_has_an_entry(self):
        # no job stops at once any more: cek D1, getir D2, kos D3, cagir D4, yaz D5 (each job's own test file);
        # run from the command line without their inputs, each is no verdict (exit 2), never a green
        for name in JOBS:
            env = {"CLAUDE_CODE_OAUTH_TOKEN": "x"} if name == "cagir" else {}
            with self.subTest(job=name):
                code, out = run_job(name, env)
                self.assertEqual((code, out), (2, {"ok": False, "reason": None}))

    def test_unusable(self):
        for argv in (["run", "nope"], ["run"], [], ["render", "x"]):
            with self.subTest(argv=argv):
                proc = subprocess.run([sys.executable, "-m", "loop.job"] + argv, cwd=REFEREE, capture_output=True)
                self.assertEqual(proc.returncode, 2)
                self.assertEqual(json.loads(proc.stdout), {"ok": False, "reason": None})


if __name__ == "__main__":
    unittest.main()
