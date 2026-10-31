"""The parts of the bootstrap that only meet in production must agree: workflow, CLI, files, secrets, spec.

Nothing here runs a workflow. It reads `workflow/bootstrap.yml` the way a reviewer would and holds
every claim in it against the code and the spec, so that a renamed flag, a deleted file, a new secret
nobody documented or a stale instruction fails a test instead of the first real run.
"""

import json
import re
import shlex
import unittest
from pathlib import Path

from snowball_bootstrap import cli, rival, stages, vectors

BOOT = Path(__file__).resolve().parents[1]
ROOT = BOOT.parents[1]
WORKFLOW = (BOOT / "workflow" / "bootstrap.yml").read_text(encoding="utf-8")
SETUP_DAY = (ROOT / "spec" / "tohum" / "25-kurulum-gunu.md").read_text(encoding="utf-8")
BS = chr(92)


def spec_page(folder, prefix):
    found = sorted((ROOT / "spec" / folder).glob(f"{prefix}-*.md"))
    if len(found) != 1:
        raise AssertionError(f"expected one spec/{folder}/{prefix}-*.md, found {len(found)}")
    return found[0].read_text(encoding="utf-8")


def run_blocks(text):
    """The shell text of every `run:` step, as a list of single commands (continuations joined)."""
    lines = text.splitlines()
    commands = []
    for i, line in enumerate(lines):
        m = re.match(r"^(\s*)(?:- )?run:\s*(.*)$", line)
        if not m:
            continue
        indent, rest = len(m.group(1)), m.group(2).strip()
        if rest not in ("|", ">"):
            commands.append(rest)
            continue
        body = []
        for follow in lines[i + 1:]:
            if follow.strip() and len(follow) - len(follow.lstrip()) <= indent + 1:
                break
            body.append(follow.strip())
        if rest == ">":
            commands.append(" ".join(b for b in body if b))
            continue
        joined, current = [], ""
        for b in body:
            if b.endswith(BS):
                current += b[:-1] + " "
            else:
                joined.append(current + b)
                current = ""
        commands.extend(c for c in joined if c)
    return commands


def bootstrap_invocations():
    found = []
    for command in run_blocks(WORKFLOW):
        m = re.search(r"python3 -m snowball_bootstrap ([^|]*?)(?: \| | >> |$)", command)
        if m:
            text = re.sub(r"\$\{\{.*?\}\}", "X", m.group(1))
            found.append(shlex.split(text))
    return found


class WorkflowWiringTest(unittest.TestCase):
    def test_every_invocation_is_accepted_by_the_real_argument_parser(self):
        invocations = bootstrap_invocations()
        self.assertGreater(len(invocations), 10)
        commands = {argv[0] for argv in invocations}
        self.assertIn("rival", commands)
        for argv in invocations:
            try:
                cli.build_parser().parse_args(argv)
            except SystemExit:
                self.fail(f"bootstrap.yml calls `{' '.join(argv)}`, which the CLI refuses")

    def test_every_file_the_workflow_reads_exists(self):
        paths = set(re.findall(r"snap/bootstrap/([A-Za-z0-9_./-]+)", WORKFLOW))
        self.assertIn("requirements/claude-cli/package.json", paths)
        for rel in sorted(paths):
            if "node_modules" in rel:  # created by npm ci in the job
                continue
            self.assertTrue((BOOT / rel).exists(), f"bootstrap.yml names snap/bootstrap/{rel}, which does not exist")

    def test_every_secret_and_variable_is_documented_for_the_operator(self):
        names = set(re.findall(r"(?:secrets|vars)@BS@.([A-Z0-9_]+)".replace("@BS@", BS), WORKFLOW))
        self.assertEqual(names, {"CLAUDE_CODE_OAUTH_TOKEN"})  # the brain is public: nothing else is held
        for name in names:
            self.assertIn(name, SETUP_DAY, f"tohum/25 never tells the operator about {name}")

    def test_the_model_credential_reaches_only_the_rival_step(self):
        self.assertEqual(WORKFLOW.count("${{ secrets.CLAUDE_CODE_OAUTH_TOKEN }}"), 1)
        used = re.findall(r"\$\{\{\s*secrets\.([A-Za-z0-9_]+)\s*\}\}", WORKFLOW)
        self.assertEqual(used, ["CLAUDE_CODE_OAUTH_TOKEN"])  # no other way to read a secret
        self.assertNotIn("toJSON(secrets", WORKFLOW)
        self.assertNotIn("secrets[", WORKFLOW)
        self.assertNotIn("secrets: inherit", WORKFLOW)
        rival_step = WORKFLOW[WORKFLOW.index("name: Seed rival"):]
        rival_step = rival_step[:rival_step.index("- id: pack")]
        self.assertIn("${{ secrets.CLAUDE_CODE_OAUTH_TOKEN }}", rival_step)
        self.assertNotIn("ANTHROPIC_API_KEY", WORKFLOW.replace("No API key", ""))

    def test_the_rival_is_run_with_the_cli_that_was_installed_and_pinned(self):
        install = re.search(r"npm ci --prefix (snap/bootstrap/requirements/claude-cli)", WORKFLOW)
        self.assertIsNotNone(install)
        self.assertIn(f"--claude {install.group(1)}/node_modules/.bin/claude", WORKFLOW)
        self.assertNotIn("--ignore-scripts", WORKFLOW)  # the CLI's own install step links its binary

    def test_the_brain_is_read_without_any_identity(self):
        """Public brain: no App token step, no token handed to the pull or the poll, no auth header in the code."""
        self.assertNotIn("app-id", WORKFLOW)
        self.assertEqual(re.findall(r"BRAIN_[A-Z_]+", WORKFLOW), [])
        self.assertNotIn("steps.app.", WORKFLOW)
        gitio_source = (BOOT / "snowball_bootstrap" / "gitio.py").read_text(encoding="utf-8")
        for needle in ("extraheader", "AUTHORIZATION", "x-access-token"):
            self.assertNotIn(needle, gitio_source, f"gitio still knows how to send {needle}")

    def test_no_github_context_is_expanded_inside_a_shell_script(self):
        """E17: `${{ github.ref }}` pasted into bash runs a branch name chosen by whoever can dispatch."""
        for command in run_blocks(WORKFLOW):
            self.assertNotRegex(command, r"\$\{\{\s*(github|inputs)\.", command[:160])

    def test_only_runs_on_main_judge_and_sign_and_the_identity_is_mains(self):
        """E17: a dispatch from another branch must neither judge nor sign, and the state is verified as main's."""
        cek = WORKFLOW[WORKFLOW.index("  cek:"):WORKFLOW.index("  getir:")]
        yaz = WORKFLOW[WORKFLOW.index("  yaz:"):]
        for job in (cek, yaz):
            self.assertIn("github.ref == 'refs/heads/main'", job.split("steps:", 1)[0])
        identity = re.search(r'--identity "([^"]+)"', WORKFLOW).group(1)
        self.assertTrue(identity.endswith("/.github/workflows/bootstrap.yml@refs/heads/main"), identity)

    def test_the_job_outlives_the_cli_it_waits_for(self):
        job = WORKFLOW[WORKFLOW.index("  cagir:"):]
        minutes = int(re.search(r"timeout-minutes: ([0-9]+)", job).group(1))
        self.assertGreater(minutes * 60, rival.CLI_TIMEOUT_S + 300, "install and bookkeeping need room too")

    def test_the_vectors_leave_the_kos_job_half_its_time(self):
        """A vector run that outlives `kos` is booked as an outage the Founder never hears of: the vectors' budget is
        at most half the job, the rest is the controls', the Founder's tests' and module-less red's (E18 for those)."""
        job = WORKFLOW[WORKFLOW.index("  kos:"):WORKFLOW.index("  cagir:")]
        minutes = int(re.search(r"timeout-minutes: ([0-9]+)", job).group(1))
        self.assertLessEqual(vectors.BUDGET_S * 2, minutes * 60)


MF_COLUMNS = ["MF", "Mekanizma", "Test", "Vektör grubu", "Modül (`referee/` altında)", "Adım", "Kum"]


def micro_feature_rows(page):
    """The `asama-0/14` table, row by row: {mf: {column: cell}}."""
    header, rows = None, {}
    for line in page.splitlines():
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if cells[0] == "MF":
            header = cells
        elif header and cells[0].isdigit():
            if len(cells) != len(header):
                raise AssertionError(f"row {cells[0]} of asama-0/14 has {len(cells)} cells, not {len(header)}")
            rows[int(cells[0])] = dict(zip(header, cells))
    return header, rows


def page_groups(cell):
    """The vector groups a cell names: the backticked names it starts with (`chain`, `append`). A cell that starts
    otherwise (MF17: "tohumun `wiring` denetimi (vektör değil ...)") names none."""
    lead = re.match(r"(?:`[a-z0-9_]+`(?:, )?)+", cell)
    return re.findall(r"`([a-z0-9_]+)`", lead.group(0)) if lead else []


def page_calls(page, count):
    """The `calls` line (callee → callers; a chain `12 → 13 → 14`; "17 ve 18 hepsini çağırır": each calls every
    micro-feature before it), as {caller: callees}. A clause in any other form fails the test."""
    found = re.search(r"^`calls` \(çağrılan → çağıranlar\): (.*?)\n\n", page, re.S | re.M)
    if not found:
        raise AssertionError("asama-0/14 has no `calls` line")
    callees = {k: set() for k in range(1, count + 1)}
    for clause in " ".join(found.group(1).split()).rstrip(".").split("; "):
        every = re.fullmatch(r"(\d+(?: ve \d+)*) hepsini çağırır", clause)
        if every:
            for caller in map(int, every.group(1).split(" ve ")):
                callees[caller] |= set(range(1, caller))
            continue
        if not re.fullmatch(r"\d+(?:, \d+)*(?: → \d+(?:, \d+)*)+", clause):
            raise AssertionError(f"asama-0/14: cannot read the calls clause {clause!r}")
        segments = [[int(n) for n in part.split(", ")] for part in clause.split(" → ")]
        for called, callers in zip(segments, segments[1:]):
            for caller in callers:
                callees[caller] |= set(called)
    return callees


class StageTableMatchesTheSpecTest(unittest.TestCase):
    """`asama-0/14` "Makine kopyası": `stages/stage0.json` is the page's table and `calls` line, and every test it
    names is a §0.9 row whose "Ne zaman" is that micro-feature. When one changes, the others change in the same seed
    epoch; this test is what makes that so."""

    PAGE = spec_page("asama-0", "14")
    TESTS_PAGE = spec_page("asama-0", "09")
    TABLE = stages.load(0)

    def test_every_row_is_the_pages_row(self):
        header, rows = micro_feature_rows(self.PAGE)
        self.assertEqual(header, MF_COLUMNS)
        self.assertEqual(sorted(rows), list(range(1, self.TABLE.count + 1)))
        for feature in self.TABLE.mfs:
            row = rows[feature.mf]
            with self.subTest(mf=feature.mf):
                self.assertEqual(list(feature.tests), [int(n) for n in row["Test"].split(", ")])
                self.assertEqual(list(feature.groups), page_groups(row["Vektör grubu"]))
                self.assertEqual(f"`{feature.module}`", row["Modül (`referee/` altında)"])

    def test_calls_are_the_pages_calls_line(self):
        calls = page_calls(self.PAGE, self.TABLE.count)
        self.assertEqual({f.mf: set(f.calls) for f in self.TABLE.mfs}, calls)

    def test_every_test_is_a_section_09_row_of_its_micro_feature(self):
        when = {}
        for line in self.TESTS_PAGE.splitlines():
            row = re.match(r"^\| (\d+) \| .* \| ([^|]+) \|$", line)
            if row:
                when[int(row.group(1))] = row.group(2).strip()
        self.assertGreater(len(when), 40)
        stage0 = {(n, int(w[2:])) for n, w in when.items() if re.fullmatch(r"MF\d+", w)}
        self.assertEqual({(n, f.mf) for f in self.TABLE.mfs for n in f.tests}, stage0)
        counts = re.search(r"(\d+) MF'ye (\d+) test", self.TESTS_PAGE)
        self.assertEqual((int(counts.group(1)), int(counts.group(2))),
                         (self.TABLE.count, sum(len(f.tests) for f in self.TABLE.mfs)))

    def test_the_counts_the_exit_pages_name_are_the_tables(self):
        self.assertEqual(int(re.search(r"Çıkışta (\d+)'", self.PAGE).group(1)), self.TABLE.count)
        exit_page = spec_page("asama-0", "10")
        self.assertEqual(int(re.search(r"`stage0\.json`'daki (\d+) MF", exit_page).group(1)), self.TABLE.count)
        self.assertEqual(int(re.search(r"#modulsuz \| (\d+) MF", exit_page).group(1)), self.TABLE.count)

    def test_the_vector_groups_are_29ds_and_each_seed_group_has_its_owner(self):
        """`29d` names each group's micro-features; `vectors.json` says which stage or batch owns each group it has
        (`29a`): Stage 0's are exactly those the table names."""
        listed = {}
        for line in spec_page("tohum", "29d").splitlines():
            row = re.match(r"^\| `([a-z0-9_]+)` \| (\d+(?:, \d+)*) \|", line)
            if row:
                listed[row.group(1)] = {int(n) for n in row.group(2).split(", ")}
        named = {}
        for feature in self.TABLE.mfs:
            for group in feature.groups:
                named.setdefault(group, set()).add(feature.mf)
        self.assertEqual(listed, named)
        seed = json.loads((BOOT / "vectors" / "vectors.json").read_text(encoding="utf-8"))
        groups = {k: v for k, v in seed.items() if isinstance(v, dict)}
        own = {name for name, _fn in vectors.GROUPS}
        data = {name for name, group in groups.items() if group.get("runner") == vectors.DATA_RUNNER}
        self.assertEqual((set(groups), own & data), (own | data, set()))  # every group has exactly one judge
        for name, group in groups.items():
            self.assertEqual(group["owner"] == "asama-0", name in named, name)


class SpecPagesTest(unittest.TestCase):
    def test_no_page_is_over_80_lines(self):
        """`tohum/15` 1: a page over 80 lines is split. Every page under `spec/`, the changelog too, not only the vector
        pages (E252: the check held only `29f`-`29k`, and `29` reached 84 lines and the changelog 82 unseen);
        `INDEX.md` is generated (`tohum/15` 5) and exempt."""
        pages = sorted(p for p in (ROOT / "spec").rglob("*.md") if p != ROOT / "spec" / "INDEX.md")
        self.assertGreater(len(pages), 100)
        for page in pages:
            with self.subTest(page=page.relative_to(ROOT).as_posix()):
                self.assertLessEqual(len(page.read_text(encoding="utf-8").splitlines()), 80)


VECTOR_PAGES = ("29f", "29g", "29h", "29i", "29j", "29k", "29m", "29n", "29o")


class VectorInterfacePagesTest(unittest.TestCase):
    """`29f`-`29k` and `29m`-`29o` are what the Founder reads of the data groups (it never sees `vectors.json`): every
    group's command and every case's purpose are there, the expected values are not (`29a`: the vectors are a floor)."""

    SEED = json.loads((BOOT / "vectors" / "vectors.json").read_text(encoding="utf-8"))
    DATA = {n: g for n, g in SEED.items() if isinstance(g, dict) and g.get("runner") == vectors.DATA_RUNNER}

    def test_each_page_is_a_seed_page_and_29d_and_the_index_point_to_it(self):
        index, groups_page = (ROOT / "spec" / "INDEX.md").read_text(encoding="utf-8"), spec_page("tohum", "29d")
        for prefix in VECTOR_PAGES:
            page = spec_page("tohum", prefix)
            name = next((ROOT / "spec" / "tohum").glob(f"{prefix}-*.md")).name
            lines = page.splitlines()
            with self.subTest(page=name):
                self.assertRegex(lines[2], r"^Tarih: \d{4}-\d\d-\d\d · Sürüm: [\d.]+ · Durum: \w+ · Sahibi: operatör$")
                self.assertTrue(lines[3].startswith("Okunma: ") and lines[4].startswith("Çapa: "))
                self.assertIn(f"| `tohum/{name}` | {lines[0].removeprefix('# ')} | {lines[3].removeprefix('Okunma: ')} |",
                              index)
                self.assertIn(f"`{prefix}`", groups_page)

    def test_every_data_group_its_commands_and_every_case_are_on_its_page(self):
        self.assertEqual(set(self.DATA), {"secrets", "contained", "profile", "npmlock", "recipe", "diffguard",
                                          "k0map", "refs", "append", "root", "flaky", "cause", "revert_drill", "prompt",
                                          "status", "genesis"})
        for name, group in self.DATA.items():
            page = (ROOT / group["interface"]).read_text(encoding="utf-8")
            self.assertIn(f"`{name}`", page)
            for case in group["cases"]:
                with self.subTest(case=case["id"]):
                    for variant in (case, case["changed"]):
                        self.assertIn(" ".join(variant["cmd"].split()[:4]), page)  # python -m <module> <verb>
                    self.assertIn(f"`{case['id'].split('.', 1)[1]}`", page)

    def test_no_expected_value_is_on_a_page(self):
        pages = "".join(spec_page("tohum", p) for p in VECTOR_PAGES)
        for group in self.DATA.values():
            for case in group["cases"]:
                expect = case["expect"]
                self.assertNotIn(json.dumps(expect, separators=(",", ":"), sort_keys=True), pages)
                for atom in vectors.answer_atoms(expect):  # the rule `/vec` is held to (E244), one source
                    self.assertNotIn(atom, pages, case["id"])


class DocWithChangeTest(unittest.TestCase):
    """The owner's rule (2026-10-30): a change to the seed's behaviour lands with its document. CI runs
    `local/doc_with_change.py` over every push to `main`; this pins what it lets through."""

    def setUp(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("doc_with_change", BOOT / "local" / "doc_with_change.py")
        self.mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.mod)

    def test_a_behaviour_change_without_a_document_is_named(self):
        u = self.mod.undocumented
        self.assertEqual(u(["seed/bootstrap/snowball_bootstrap/decide.py"]), ["seed/bootstrap/snowball_bootstrap/decide.py"])
        self.assertEqual(u(["seed/founder/launch.py", "seed/bootstrap/tests/test_founder_capsule.py"]),
                         ["seed/founder/launch.py"])
        self.assertEqual(u(["seed/bootstrap/vectors/vectors.json"]), ["seed/bootstrap/vectors/vectors.json"])

    def test_a_documented_or_unguarded_change_passes(self):
        u = self.mod.undocumented
        self.assertEqual(u(["seed/bootstrap/snowball_bootstrap/decide.py", "docs/eksik-kaydi.md"]), [])
        self.assertEqual(u(["seed/founder/launch.py", "seed/founder/README.md"]), [])
        self.assertEqual(u(["seed/bootstrap/snowball_bootstrap/rival.py", "spec/tohum/29-tohum-koltuklari.md"]), [])
        self.assertEqual(u(["seed/bootstrap/local/mutate.py", "seed/bootstrap/tests/test_units.py"]), [])
        self.assertEqual(u(["README.md"]), [])
        self.assertEqual(u(["", "  "]), [])

    def test_ci_runs_it_on_every_push_to_main(self):
        ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        self.assertIn("python3 seed/bootstrap/local/doc_with_change.py", ci)


class SystemMapTest(unittest.TestCase):
    """The owner's rule E301: `docs/harita.md`, the map of what connects to what, is drawn from the code by
    `local/system_map.py` and never by hand. A module, job, dependency or link changed without regenerating the
    map turns this red."""

    def setUp(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("system_map", BOOT / "local" / "system_map.py")
        self.mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.mod)

    def test_the_committed_map_is_what_the_code_draws(self):
        drawn = self.mod.render().encode("utf-8")
        committed = (ROOT / "docs" / "harita.md").read_bytes()
        if committed != drawn:
            old, new = committed.decode("utf-8", "replace").split("\n"), drawn.decode("utf-8").split("\n")
            line = next((i for i, (a, b) in enumerate(zip(old, new)) if a != b), min(len(old), len(new)))
            self.fail(f"docs/harita.md is stale from line {line + 1}: run `python3 local/system_map.py` "
                      "from seed/bootstrap and commit the page")

    def test_it_sees_every_module_and_every_job(self):
        src = self.mod.Sources()
        self.assertEqual(set(self.mod.module_graph(src)), {p.stem for p in (BOOT / "snowball_bootstrap").glob("*.py")})
        jobs = self.mod.workflow_jobs(WORKFLOW)
        listed = re.findall(r"^  ([A-Za-z_][A-Za-z0-9_-]*):[ \t]*$", WORKFLOW.split("\njobs:\n", 1)[1], re.M)
        self.assertEqual(list(jobs), listed)
        self.assertEqual(jobs["yaz"].needs, ["cek", "getir", "kos", "cagir", "yeniden"])
        self.assertEqual(jobs["getir"].needs, ["cek"])
        ran = {c for job in jobs.values() for c in job.commands}
        self.assertLessEqual({argv[0] for argv in bootstrap_invocations()}, ran)
        self.assertIn("fetch-deps", ran)  # run by the venv's python, not `python3`
        import argparse
        sub = next(a for a in cli.build_parser()._actions if isinstance(a, argparse._SubParsersAction))
        self.assertEqual(set(self.mod.cli_commands(self.mod.module_graph(src)["cli"])), set(sub.choices))
        page = self.mod.render(src)
        for name in list(jobs) + [p.stem for p in (BOOT / "snowball_bootstrap").glob("*.py")]:
            self.assertIn(f"`{name}`", page)

    def test_a_new_job_or_dependency_shows_up_by_regeneration(self):
        extra = "  audit:\n    needs: [yaz]\n    steps:\n      - run: python3 -m snowball_bootstrap control --root snap\n"
        rel = self.mod.WORKFLOW
        page = self.mod.render(self.mod.Sources(overrides={rel: WORKFLOW.rstrip("\n") + "\n\n" + extra}))
        self.assertIn('job_audit["job audit<br/>control"]', page)
        self.assertIn("job_yaz --> job_audit", page)
        self.assertIn("| `audit` | `yaz` | `control` |", page)

    def test_a_link_whose_evidence_is_gone_stops_the_drawing(self):
        launcher = (ROOT / self.mod.LAUNCHER).read_text(encoding="utf-8").replace('"gh", "workflow", "run"', '"gh"')
        with self.assertRaisesRegex(ValueError, "dispatch: gh workflow run"):
            self.mod.render(self.mod.Sources(overrides={self.mod.LAUNCHER: launcher}))
        with self.assertRaisesRegex(ValueError, "not a subcommand"):
            self.mod.render(self.mod.Sources(overrides={self.mod.WORKFLOW: WORKFLOW.replace(" pack --dir", " packs --dir")}))


class NothingStaleTest(unittest.TestCase):
    STALE = ("call.txt", "secrets.ANTHROPIC", "import anthropic", "anthropic==", "/tmp/call", "Anthropic SDK",
             "model SDK", "price_micros_per_mtok", "READER_APP", "BRAIN_TOKEN", "create-github-app-token")

    def test_the_old_api_design_has_left_no_trace(self):
        here = Path(__file__).resolve()
        files = [p for base in (BOOT, ROOT / "spec" / "tohum", ROOT / "README.md") for p in
                 ([base] if base.is_file() else base.rglob("*"))
                 if p.is_file() and p != here and "node_modules" not in p.parts and "__pycache__" not in p.parts
                 and p.suffix in (".py", ".md", ".yml", ".json", ".txt")]
        self.assertGreater(len(files), 50)
        for path in files:
            if path.name == "package-lock.json" or path.name.startswith("CHANGELOG"):
                continue  # the changelog (every page of it, `tohum/15` 1) is history
            text = path.read_text(encoding="utf-8", errors="replace")
            for term in self.STALE:
                if path.name == "config.py" and term == "price_micros_per_mtok":
                    continue  # named on purpose, to tell an operator the key was removed
                if path.name == "test_units.py" and term == "price_micros_per_mtok":
                    continue
                self.assertNotIn(term, text, f"{path.relative_to(ROOT)} still says {term!r}")


if __name__ == "__main__":
    unittest.main()
