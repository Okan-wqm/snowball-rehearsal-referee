"""The parts of the bootstrap that only meet in production must agree: workflow, CLI, files, secrets, spec.

Nothing here runs a workflow. It reads `workflow/bootstrap.yml` the way a reviewer would and holds
every claim in it against the code and the spec, so that a renamed flag, a deleted file, a new secret
nobody documented or a stale instruction fails a test instead of the first real run.
"""

import io
import json
import os
import re
import shlex
import unittest
from pathlib import Path
from unittest import mock

from snowball_bootstrap import cli, rival, stages, vectors, wiring

from helpers import kos_part_count, workflow_job

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


def flat(text):
    """A page's text with its line breaks and runs of spaces read as one space (a sentence may wrap anywhere)."""
    return " ".join(text.split())


def paragraph(page, opening):
    """The flattened paragraph of ``page`` that starts with ``opening`` (a bold title such as ``**Durum.**``)."""
    blocks = [flat(b) for b in re.split(r"\n\s*\n", page)]
    found = [b for b in blocks if b.startswith(opening)]
    if len(found) != 1:
        raise AssertionError(f"expected one paragraph starting {opening!r}, found {len(found)}")
    return found[0]


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
        at most half the job that runs them, a part since E440, the rest is the controls', the Founder's tests' and
        module-less red's (E18 for those)."""
        minutes = int(re.search(r"timeout-minutes: ([0-9]+)", workflow_job("kos_parca")).group(1))
        self.assertLessEqual(vectors.BUDGET_S * 2, minutes * 60)


class KosPartsTest(unittest.TestCase):
    """E440: `kos` runs as N parts and one join. The matrix, the parts' outputs, the count each part is told and the
    artifacts the join reads, each by the hash its part's job named, must all be the same N parts: a part the join
    does not read would go unjudged, one it reads by another part's hash would not verify."""

    def test_the_matrix_the_outputs_and_the_join_name_the_same_parts(self):
        part, join, count = workflow_job("kos_parca"), workflow_job("kos"), kos_part_count()
        self.assertGreater(count, 1)
        self.assertIn(f"        part: {list(range(count))}", part)
        self.assertEqual(re.findall(r"(?m)^      (part_sha_[0-9]+): \$\{\{ steps\.pack\.outputs\.(part_sha_[0-9]+) \}\}$",
                                    part), [(f"part_sha_{k}", f"part_sha_{k}") for k in range(count)])
        for line in ("PART: ${{ matrix.part }}", "PARTS: ${{ strategy.job-total }}", 'run-part --part "$PART/$PARTS"',
                     '--out "part-$PART.tar" | sed -n "s/^sha256=/part_sha_${PART}=/p" >> "$GITHUB_OUTPUT"',
                     "name: run-part-${{ matrix.part }}", "path: part-${{ matrix.part }}.tar"):
            self.assertIn(line, part)
        self.assertEqual(re.findall(r"--part parts/part-([0-9]+)\.tar=\$\{\{ needs\.kos_parca\.outputs\.part_sha_([0-9]+) \}\}",
                                    join), [(str(k), str(k)) for k in range(count)])
        self.assertEqual(join.count("--part "), count)
        self.assertIn('pattern: "run-part-*", path: parts, merge-multiple: true', join)

    def test_the_join_fails_on_a_part_that_did_not_succeed_and_runs_no_brain_code(self):
        join = workflow_job("kos")
        self.assertIn("    needs: [cek, getir, kos_parca]\n", join)
        first = join[join.index("    steps:\n"):].split("      - ", 2)[1]
        self.assertEqual(first, "name: Every part finished\n        env:\n          RESULT: ${{ needs.kos_parca.result }}\n"
                                '        run: test "$RESULT" = success\n')
        self.assertIn("    permissions: {}\n", join)
        for word in ("docker", "secrets."):
            self.assertNotIn(word, join)
        self.assertEqual(set(re.findall(r"-m snowball_bootstrap ([a-z-]+)", join)), {"control", "join-parts", "pack"})


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

    def test_29b_asks_the_exit_for_the_tables_micro_features_and_no_lint_or_lock_of_the_referee(self):
        """The Founder's report seed-002 (E390): `29b` kept the text from before the narrowing, the exit asking
        `referee/`'s `spec.lint` and `gate.lock` and "30 mikro özellik", and the Founder's script for later exits. The
        referee asks every row of the table (`decide`: `not_all_micro_features_done`); the spec check and the lock
        are the seed's code (`asama-0/10`), and every exit's import is this package's (`25a` 1)."""
        from snowball_bootstrap import decide
        page = spec_page("tohum", "29b")
        self.assertEqual([n for n in map(int, re.findall(r"(\d+) mikro özellik", flat(page))) if n != self.TABLE.count],
                         [])
        exit_request = paragraph(page, "**Çıkış isteği")
        self.assertEqual(int(re.search(r"\(Aşama 0'da (\d+)\)", exit_request).group(1)), self.TABLE.count)
        self.assertIn("`not_all_micro_features_done`", exit_request)
        self.assertIn('missing.append("not_all_micro_features_done")', Path(decide.__file__).read_text(encoding="utf-8"))
        for tool in ("spec.lint", "gate.lock"):
            self.assertNotIn(f"python -m {tool}", page)
        self.assertEqual(re.findall(r"`(?:spec\.lint|gate\.lock)`[^;]*", exit_request),
                         ["`spec.lint` ve `gate.lock` (A)'da çağrılmaz, spec denetimi ve kilit tohumun kodudur (`29a`, "
                          "`asama-0/10`)"])
        intro = paragraph(page, "Aşama 0'da Kurucu hakemi yazar")
        self.assertIn("Her çıkıştaki aktarım bu paketin `import` komutudur (`25a` 1).", intro)
        self.assertNotIn("Kurucu'nun betiği", intro)

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

    def test_which_lock_entries_are_fetched_is_stated_on_29g_only(self):
        """spec-015 (E400): which entries of an npm lock, a workspaces lock included, `deps.fetch` fetches and checks
        is one rule, on `29g`. Two pages that restate it drift apart (a draft of this rule had `14` and `24` leave the
        workspace folder out while `29g` exempted it); `24` and `30c` point at `29g` instead. The changelog is history."""
        terms = ("çalışma alanı bağı", "çalışma alanı dizini")
        source = ROOT / "spec" / "tohum" / "29g-vektor-arayuzleri-devam.md"
        self.assertTrue(all(t in source.read_text(encoding="utf-8").lower() for t in terms))
        for page in sorted((ROOT / "spec").rglob("*.md")):
            if page == source or page.name.startswith("CHANGELOG"):
                continue
            text = page.read_text(encoding="utf-8").lower()
            with self.subTest(page=page.relative_to(ROOT).as_posix()):
                self.assertEqual([t for t in terms if t in text], [])
        for prefix in ("24", "30c"):
            self.assertIn("`29g`", spec_page("tohum", prefix))

    def test_every_page_has_its_index_row_and_the_referee_pages_are_on_the_task_map(self):
        """`tohum/15` 5: `INDEX.md` is the pages' headers, row for row. The pages the seed epoch of E390-E399 adds
        (`29e`, `29r`) are read when a referee component is written (`00b`), like `29b` and `29p`."""
        index = (ROOT / "spec" / "INDEX.md").read_text(encoding="utf-8")
        for page in sorted(p for p in (ROOT / "spec").rglob("*.md") if p.name != "INDEX.md"):
            lines = page.read_text(encoding="utf-8").splitlines()
            rel = page.relative_to(ROOT / "spec").as_posix()
            okunma = next(line.removeprefix("Okunma: ") for line in lines[:6] if line.startswith("Okunma: "))
            with self.subTest(page=rel):
                self.assertIn(f"| `{rel}` | {lines[0].removeprefix('# ')} | {okunma} |", index)
        task = next(line for line in spec_page("tohum", "00b").splitlines() if line.startswith("| Hakem bileşeni yazma"))
        for prefix in ("29b", "29e", "29p", "29r"):
            spec_page("tohum", prefix)
            self.assertIn(f"`{prefix}`", task)


class BootstrapStatePageTest(unittest.TestCase):
    """The Founder's report seed-040 (E342): the loop's `çek` (D1) reads the bootstrap referee's signed state and compares
    the accepted SHA's `referee/` tree hash, and the Founder reads only pages. What `29b` "Durum" and `26c` say of the
    artifact, its verifier, the identity and the hash rule is held to the code that does it, so neither can drift."""

    @staticmethod
    def flat(text):
        return " ".join(text.split())

    def test_29b_names_the_artifact_the_verifier_and_the_identity_the_workflow_passes(self):
        from unittest import mock
        from snowball_bootstrap import importer
        page = self.flat(spec_page("tohum", "29b"))
        identity = re.search(r'fetch-state[^\n]*\n(?:[^\n]*\n)*?\s*--identity "([^"]+)"', WORKFLOW).group(1)
        self.assertIn("${GITHUB_REPOSITORY}", identity)
        argv = []
        with mock.patch.object(importer.subprocess, "run",
                               side_effect=lambda a, **k: argv.extend(a) or mock.Mock(returncode=0, stderr="")):
            importer.verify_signature(Path("result.json"), Path("result.json.sigstore.json"),
                                      identity.replace("${GITHUB_REPOSITORY}", "<hakem reposu>"), "python")
        self.assertEqual(argv[:3], ["python", "-m", "sigstore"])
        self.assertIn(f"`{' '.join(argv[2:])}`", page)  # the page's command is the code's argv, word for word
        self.assertIn(f"--cert-oidc-issuer {importer.OIDC_ISSUER} ", page)
        self.assertIn(f"adı tam `{cli.STATE_ARTIFACT}`", page)
        self.assertIn("`result.json`, `result.json.sigstore.json`", page)  # what fetch-state unpacks from the zip
        self.assertIn('for name in ("result.json", "result.json.sigstore.json")', Path(cli.__file__).read_text(encoding="utf-8"))
        self.assertIn("`state.last_accepted_sha`", page)

    def test_26c_gives_the_referee_tree_hash_rule_and_its_vector_the_code_computes(self):
        import hashlib
        import io
        import tarfile
        from snowball_bootstrap import treehash
        page = self.flat(spec_page("tohum", "26c"))
        m = re.search(r"`/vec/(treehash/[\w.-]+\.tar)` → `([0-9a-f]{64})`", page)
        self.assertIsNotNone(m, "26c names no tree hash vector")
        tar = (BOOT / "vectors" / m.group(1)).read_bytes()
        self.assertEqual(treehash.tree_hash(tar, "referee"), m.group(2))
        # The page's rule, read literally: one line per regular file under referee/, content sha256, two spaces, the
        # path relative to referee/, LF; the lines in byte order; the sha256 of what they join to.
        lines = []
        with tarfile.open(fileobj=io.BytesIO(tar)) as t:
            for member in t.getmembers():
                if member.isfile() and member.name.startswith("referee/"):
                    content = t.extractfile(member).read()
                    lines.append(f"{hashlib.sha256(content).hexdigest()}  {member.name[len('referee/'):]}\n".encode())
        self.assertEqual(len(lines), 3)
        self.assertEqual(hashlib.sha256(b"".join(sorted(lines))).hexdigest(), m.group(2))
        self.assertIn("`referee_tree_sha256`: `brain_sha`'nın ağacında, blob baytlarıyla (git öznitelikleri, filtreler ve "
                      "satır sonu dönüşümü uygulanmadan), `referee/` altındaki", page)
        # A known-answer example, said so: no vector case applies it, the expected value is on the page alone.
        self.assertIn("bir vektör vakası değildir, hakem onu koşmaz", page)
        self.assertNotIn(m.group(1), (BOOT / "vectors" / "vectors.json").read_text(encoding="utf-8"))

    def test_26c_names_every_refusal_the_tree_hash_makes(self):
        """The page's refusals are the code's: anywhere in the archive, not only under referee/, a link, a special file
        or an unsafe name; under referee/ two names one on a case-insensitive file system, a reserved top name, no file."""
        import io
        import tarfile
        from snowball_bootstrap import treehash

        def tar(*entries):
            buf = io.BytesIO()
            with tarfile.open(fileobj=buf, mode="w") as t:
                for name, kind, data in entries:
                    info = tarfile.TarInfo(name)
                    if kind == "link":
                        info.type, info.linkname = tarfile.SYMTYPE, "x"
                    elif kind == "fifo":
                        info.type = tarfile.FIFOTYPE
                    else:
                        info.size = len(data)
                    t.addfile(info, io.BytesIO(data) if kind == "file" else None)
            return buf.getvalue()
        good = ("referee/a.py", "file", b"x\n")
        self.assertRegex(treehash.tree_hash(tar(good, ("docs/a.md", "file", b"")), "referee"), r"^[0-9a-f]{64}$")
        refused = {"a link outside referee/": (good, ("docs/l", "link", b"")),
                   "a special file outside referee/": (good, ("docs/p", "fifo", b"")),
                   "a colon": (good, ("docs/a:b.md", "file", b"")),
                   "a backslash": (good, ("docs/a\\b.md", "file", b"")),
                   "a control character": (good, ("docs/a\x01.md", "file", b"")),
                   "a .git component": (good, ("docs/.GIT/x", "file", b"")),
                   "a parent path": (good, ("../x", "file", b"")),
                   "two files, one name": (good, ("referee/A.py", "file", b"y\n")),
                   "two directories, one name": (("referee/d/a", "file", b""), ("referee/D/b", "file", b"")),
                   "an operator name at the top": (good, ("referee/Policy.json", "file", b"{}")),
                   "the bootstrap's name at the top": (good, ("referee/BOOTSTRAP/x", "file", b"")),
                   "no file under referee/": (("docs/a.md", "file", b""),)}
        for why, entries in refused.items():
            with self.assertRaises(treehash.TreeError, msg=why):
                treehash.tree_hash(tar(*entries), "referee")
        page = self.flat(spec_page("tohum", "26c"))
        for words in ("arşivin herhangi bir yerinde, yalnız `referee/` altında değil, bağ ya da özel dosya", "UTF-8 olmayan",
                      "kontrol karakteri", "ters bölü", "iki nokta", "mutlak, `..` ya da `.git` bileşenli",
                      "(casefold) tek ad olan iki yol ya da yol üstü iki dizin", "bir operatör adı ya da `bootstrap`",
                      "`referee/` altında hiç dosya yoksa"):
            self.assertIn(words, page)


class LoopInputsPageTest(unittest.TestCase):
    """The Founder's report seed-041 (E490): where the loop finds the brain repository's name, which of `targets[]` a
    `loop.yml` run serves and which pinned Sigstore its jobs run. `29s` answers each with a file the operator's setup
    already writes and the import keeps, no variable and no touch per cycle; each sentence is held to the code."""

    @classmethod
    def setUpClass(cls):
        cls.raw = spec_page("tohum", "29s")
        cls.page = flat(cls.raw)

    def test_the_brain_is_bootstrap_jsons_brain_repo_which_the_import_keeps(self):  # loop_brain_name_moved
        import tempfile
        from snowball_bootstrap import config, importer
        self.assertIn("**Beyin reposu.** Hakem reposunun kökündeki `bootstrap.json`'un `brain_repo`'sudur: `owner/name`",
                      self.page)
        self.assertIn("`$RUNNER_TEMP/control/bootstrap.json`", self.page)
        self.assertIn('git -C "$RUNNER_TEMP/control" sparse-checkout set bootstrap', wiring.CONTROL_RUN)  # root files too
        self.assertIn("bootstrap.json", importer.KEEP_TOP)
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "bootstrap.json").write_text(json.dumps({"brain_branch": "main"}), encoding="utf-8")
            with self.assertRaisesRegex(config.ConfigError, "missing key 'brain_repo'"):
                config.load_bootstrap(Path(tmp))
        self.assertTrue(config.REPO_RE.match("Okan-wqm/snowball-rehearsal-brain"))
        self.assertIn("`bootstrap.json`, hakem reposu | operatör | önyükleme hakemi; döngünün `çek`'i (`brain_repo`, `29s`)",
                      spec_page("tohum", "27"))

    def test_a_run_serves_every_target_in_the_summarys_order(self):  # loop_targets_one_per_run
        from snowball_bootstrap import config
        self.assertIn("Bir `loop.yml` koşusu, işin checkout'undaki `setup/summary.json`'un `targets[]`'ındaki her girdiye "
                      "dizinin sırasıyla hizmet eder: her hedefte bir devir", self.page)
        self.assertIn("hedef seçen bir değişken ya da tetik girdisi yoktur", self.page)
        row = {"repo": "o/r", "kind": "toy", "base_sha": None, "identifiers": [], "excluded_paths": [],
               "unit_candidates": []}
        summary = {"seed_commit": "a" * 40, "seed_tree_sha256": "b" * 64,
                   "targets": [dict(row, id="toy"), dict(row, id="copy", kind="copy")]}
        self.assertEqual([t.id for t in config.summary_of(summary).targets], ["toy", "copy"])  # the file's order
        summary["targets"].append(dict(row, id="toy"))
        with self.assertRaisesRegex(config.ConfigError, "same id"):
            config.summary_of(summary)
        self.assertIn("döngünün her işi (`targets[]`, `29s`)", spec_page("tohum", "27"))

    def sigstore_step(self):
        block = re.search(r"```yaml\n(.*?)```", self.raw, re.S).group(1)
        self.assertTrue(block.startswith("      - name: sigstore\n        if: steps.control.outputs.go == 'true'\n"))
        return block

    def test_the_sigstore_step_installs_the_seeds_pins_as_the_bootstrap_does(self):  # loop_sigstore_step_unpinned
        """The step reads the control step's clone (`bootstrap/requirements/sign.txt`), with `bootstrap.yml`'s flags:
        hash-pinned binary wheels without dependencies, the seed's license gate before the install, no index then."""
        from snowball_bootstrap import importer
        script = [line.strip() for line in self.sigstore_step().split("run: |\n", 1)[1].splitlines()]
        self.assertEqual(script[:3], ["set -eu", 'cd "$RUNNER_TEMP/control/bootstrap"', 'python3 -m venv "$RUNNER_TEMP/sig"'])
        own = [c for c in run_blocks(WORKFLOW) if "sign.txt" in c or "snowball_bootstrap licenses" in c]
        self.assertEqual(own[3:], own[:3])  # `cek` and `yaz` install it alike
        norm = lambda c: " ".join(re.sub(r"\S*sign\.txt", "SIGN", re.sub(
            r'"?\$RUNNER_TEMP/sig/bin/pip"?|/tmp/sig/bin/pip', "PIP",
            re.sub(r'"?\$RUNNER_TEMP/sigw"?|/tmp/sigw', "WHEELS", c))).split())
        self.assertEqual([norm(c) for c in script[3:]],
                         [norm(c).replace("--root snap", "--root ..") for c in own[:3]])
        sign = (BOOT / "requirements" / "sign.txt").read_text(encoding="utf-8")
        pin = re.search(r"^sigstore==(\S+) ", sign, re.M).group(1)
        self.assertIn(f"`sigstore=={pin}`", self.page)
        self.assertIn("`bootstrap/requirements/sign.txt`", self.page)
        self.assertIn("CPython 3.12 manylinux x86_64", self.page)
        self.assertIn("# sigstore==4.5.0 for the write and pull jobs; CPython 3.12, manylinux x86_64", sign)
        calls = []
        with mock.patch.object(importer.subprocess, "run",
                               side_effect=lambda argv, **k: calls.append(argv) or mock.Mock(returncode=0)):
            importer.verify_signature("x", Path("b"), "id", "$RUNNER_TEMP/sig/bin/python")
        self.assertIn(f'Program `"{calls[0][0]}" {" ".join(calls[0][1:3])}`', self.page)  # the seed's own form

    def test_the_step_passes_29ps_rule_unchanged(self):  # loop_sigstore_step_ungated
        from helpers import LOOP_YML
        step = self.sigstore_step()
        self.assertEqual(wiring.check({"loop.yml": LOOP_YML.encode()}), [])
        with_step = LOOP_YML.replace("      - name: pull\n", step + "      - name: pull\n", 1)
        with_step = with_step.replace("      - name: write\n", step + "      - name: write\n", 1)
        self.assertEqual(with_step.count("- name: sigstore"), 2)
        self.assertEqual(wiring.check({"loop.yml": with_step.encode()}), [])
        ungated = with_step.replace("        if: steps.control.outputs.go == 'true'\n        run: |\n          set -eu\n"
                                    '          cd "$RUNNER_TEMP/control/bootstrap"',
                                    "        run: |\n          set -eu\n          cd \"$RUNNER_TEMP/control/bootstrap\"", 1)
        self.assertTrue(any(r.startswith("workflow_control_gate:cek") for r in wiring.check({"loop.yml": ungated.encode()})))

    def test_the_license_gate_reads_the_control_clones_policy(self):
        """`licenses --root ..` from the clone's `bootstrap/` reads the referee root's `policy.json`, the one file of
        the root it needs (the sparse clone holds the root's files, `29p`)."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            control = Path(tmp) / "control"
            (control / "bootstrap").mkdir(parents=True)
            (control / "wheels").mkdir()
            cwd = os.getcwd()
            os.chdir(control / "bootstrap")
            try:
                self.licenses_from_the_clone(control)
            finally:
                os.chdir(cwd)

    def licenses_from_the_clone(self, control):
        """From the clone's `bootstrap/`, as the step runs it."""
        argv = ["licenses", "--root", "..", "--wheels", str(control / "wheels")]
        self.assertEqual(cli.main(argv), 2)  # no policy.json in the root: stop
        (control / "policy.json").write_text(json.dumps({"constitutional": {
            "monthly_cap_usd": 1, "stage_params": {"rival_min_attempts": 1, "repeat_reject_limit": 1},
            "stage_budgets": {"asama_0": {"rival_usd": 1}}, "license_allowlist": ["MIT"],
            "license_exceptions": {}}}), encoding="utf-8")
        err = io.StringIO()
        with mock.patch("sys.stderr", err):
            self.assertEqual(cli.main(argv), 2)
        self.assertIn("license gate: no wheels found", err.getvalue())  # the policy was read; the gate ran

    def test_29p_points_here_and_the_changelog_names_the_report(self):  # changelog_drops_seed_041
        self.assertIn("Döngünün beyin reposu, hedefleri ve Sigstore'u (kontrol adımının klonundan kurulan pinli küme) "
                      "`29s`'tedir.", flat(spec_page("tohum", "29p")))
        entry = flat((ROOT / "spec" / "tohum" / "CHANGELOG.md").read_text(encoding="utf-8")[:6000])
        named = re.search(r"`seed-041-loop-run-inputs-unnamed` → `29s:(\d+)-(\d+)` \(beyin\), `29s:(\d+)-(\d+)` "
                          r"\(hedefler\), `29s:(\d+)-(\d+)` \(Sigstore\)", entry)
        self.assertIsNotNone(named, "the changelog does not name seed-041's answer")
        lines = self.raw.splitlines()
        spans = [(int(named.group(i)), int(named.group(i + 1))) for i in (1, 3, 5)]
        for (first, last), title in zip(spans, ("**Beyin reposu.**", "**Hedefler.**", "**Sigstore.**")):
            self.assertTrue(lines[first - 1].startswith(title), title)
            self.assertTrue(lines[last - 1].strip() and (last == len(lines) or not lines[last].strip()), title)


class LoopReportsPageTest(unittest.TestCase):
    """The Founder's reports seed-042 to seed-045 (E499): each answered on a page and held to the code, or declined in
    the changelog with its reason."""

    def test_the_canarys_cli_is_the_rivals_pinned_cli_installed_as_the_bootstrap_does(self):  # canary_cli_step_unpinned
        raw = spec_page("tohum", "29s")
        block = re.findall(r"```yaml\n(.*?)```", raw, re.S)[1]
        self.assertTrue(block.startswith("      - name: claude\n        if: steps.control.outputs.go == 'true'\n"))
        script = [line.strip() for line in block.split("run: |\n", 1)[1].splitlines()]
        self.assertEqual(script[:2], ["set -eu", 'C="$RUNNER_TEMP/control/bootstrap/requirements/claude-cli"'])
        step = re.search(r"- name: Claude CLI[^\n]*\n\s*run: \|\n((?:\s{10}.*\n)+)", workflow_job("cagir")).group(1)
        own = [line.strip() for line in step.splitlines()]  # bootstrap.yml's: the same checks, from its snapshot
        self.assertEqual(script[2], own[0])  # node 22 or later
        self.assertEqual(script[3].replace('"$C"', "D"), own[1].replace("snap/bootstrap/requirements/claude-cli", "D"))
        for words in ("package.json').dependencies['@anthropic-ai/claude-code']",
                      "/node_modules/.bin/claude\" --version | cut -d' ' -f1"):
            self.assertIn(words, " ".join(script[4:]))
        self.assertIn('dependencies["@anthropic-ai/claude-code"]', own[2])
        lock = json.loads((BOOT / "requirements" / "claude-cli" / "package-lock.json").read_text(encoding="utf-8"))
        self.assertTrue(lock["packages"]["node_modules/@anthropic-ai/claude-code"]["integrity"].startswith("sha512-"))
        page = flat(raw)
        self.assertIn("çalıştırılabilir dosyanın baytlarına ayrı bir pin yoktur", page)
        self.assertIn("Kanaryanın istediği model `bootstrap.json`'un `rival.model`'idir", page)
        from helpers import LOOP_YML
        with_step = LOOP_YML.replace("      - name: call\n", block + "      - name: call\n", 1)
        self.assertEqual(wiring.check({"loop.yml": with_step.encode()}), [])

    def test_26f_gives_the_sentinels_end_row_from_mf12s_fields(self):  # sentinel_end_row_moved
        from snowball_bootstrap import stagelock
        page = flat(spec_page("tohum", "26f"))
        self.assertIn("**Nöbetçinin sonu** (`part: events`, `kind: sentinel`): `payload {merge_sha, verdict: green|flaky, "
                      "red: [], flaky: [test kimliği]}`", page)
        mf12 = flat(spec_page("tohum", "29j"))
        self.assertIn("Çıktı `verdict` (`green` | `red` | `flaky` | `rerun`), sıralı `red` ve `flaky`", mf12)
        self.assertIn("**Geri alma** (`part: events`, `kind: revert`): üst düzey `cause`", page)
        self.assertIn("geri alma `part: events`, `kind: revert`, üst düzey `cause` (`26:41-44`), `payload {merge_sha}`",
                      flat(spec_page("tohum", "29m")))
        self.assertIn("(`events` `kind: merge` ya da `drill` `kind: plant`)", page)
        self.assertIn('row.get("kind") == "merge"', Path(stagelock.__file__).read_text(encoding="utf-8"))  # 26d's merge

    def test_26f_says_where_d8_runs_and_that_its_live_fixtures_are_not_here(self):  # drill_fixtures_said_present
        page = flat(spec_page("tohum", "26f"))
        row = next(line for line in spec_page("tohum", "26a").splitlines() if line.startswith("| `exit.drill` |"))
        self.assertEqual(row.split(" | ")[2], "`yaz`")
        self.assertIn("`exit.drill` `yaz`'da koşar (`26a`)", page)
        catalog = json.loads((BOOT / "vectors" / "revert_drill" / "catalog.json").read_text(encoding="utf-8"))
        patches = [i["patch"] for i in catalog["instances"]]
        self.assertEqual(sorted(patches), ["rd-build.patch", "rd-lint.patch", "rd-test.patch"])
        for name in patches:  # the page says their bytes are nowhere: it changes with the epoch that brings them
            self.assertEqual(list(ROOT.joinpath("seed").rglob(name)), [], name)
        self.assertIn("Tohumun canlı prova fikstürleri, oyuncağa ekilecek kötü merge'ler, bu tohumda yoktur", page)

    def test_the_changelog_names_each_report_answered_or_declined(self):  # changelog_drops_seed_042_045
        entry = flat((ROOT / "spec" / "tohum" / "CHANGELOG.md").read_text(encoding="utf-8")[:9000])
        for answered in ("`seed-042-d4-canary-inputs-unnamed` → `29s:", "`seed-043-sentinel-end-row-unnamed` → `26f:",
                         "`seed-045-drill-live-inputs-unnamed` → `26f:"):
            self.assertIn(answered, entry)
        self.assertIn("declined: `seed-044-revert-facts-producers`: `29j:53-60`", entry)
        self.assertIn("`build_ok`'un ve nöbetçinin lint toplamının üreticisini adlandırmaz", flat(spec_page("tohum", "29j")))

    def test_seed_046_is_answered_by_lines_that_say_it(self):  # changelog_drops_seed_046
        """E503: the Founder's seed-046 (the PASS row's part, kind and payload, its writer, the conditions it judges,
        a flaky sentinel end, a failed drill, #kapsama-kaydi's field) came after this epoch's commit was cut; every
        question has a seed line, and each line the answer names says what the answer says it does."""
        entry = flat((ROOT / "spec" / "tohum" / "CHANGELOG.md").read_text(encoding="utf-8")[:9000])
        self.assertIn("`seed-046-pass-row-unnamed` → `26d:36-47`", entry)
        pages = {"26d": ROOT / "spec" / "tohum" / "26d-semalar-pass-satiri.md",
                 "26f": ROOT / "spec" / "tohum" / "26f-semalar-nobetci-ve-prova.md",
                 "29s": next((ROOT / "spec" / "tohum").glob("29s-*.md")),
                 "10a": ROOT / "spec" / "asama-0" / "10a-cikis-canli-dongu.md"}
        says = {("26d", 36, 47): ("**PASS satırı**", "başka alan da", "copy_merge_row_hashes"),
                ("26d", 9, 9): ("PASS satırını döngü hakemi yazar",),
                ("29s", 19, 24): ("her girdiye dizinin", "sırasıyla hizmet eder"),
                ("10a", 44, 44): ("PASS bir imza değil, bu koşulların makine",),
                ("26f", 12, 14): ("verdict: green|flaky", "`flaky` kararı"),
                ("10a", 25, 25): ("#nobetci", "nöbetçi yeşil"),
                ("10a", 26, 26): ("#geri-alma", "her biri geri alınmış"),
                ("26d", 35, 35): ("**Merge satırı**", "serbest"),
                ("10a", 24, 24): ("#kapsama-kaydi", "kapılamaz")}
        for (page, first, last), words in says.items():
            ref = f"`{page}:{first}`" if first == last else f"`{page}:{first}-{last}`"
            self.assertIn(ref, entry[entry.index("seed-046"):], ref)
            lines = " ".join(" ".join(pages[page].read_text(encoding="utf-8").splitlines()[first - 1:last]).split())
            for word in words:
                self.assertIn(word, lines, ref)


class ReportAnswerPagesTest(unittest.TestCase):
    """The answers a seed epoch gives the Founder's reports (E390-E399) are interface facts the referee's code holds:
    each page sentence here is tied to the constant, string or behaviour it states, so neither can drift."""

    def test_27_has_a_reader_row_for_every_brain_path_the_referee_reads(self):
        """Seed-003 (E156): `asama-0/10` #okuyucu asks a reader in `27` or `27a` for every file; the toy target's
        content had none. Every path of the brain the seed reads on `pull` or at the exit is in the table's first
        column, the toy's row names the hash the signed result carries, and the exit's unchecked #spec no longer
        names the missing reader."""
        from snowball_bootstrap import classify, decide, exitchecks
        table = spec_page("tohum", "27").split("## Okuyucular", 1)[1]
        rows = {line: re.findall(r"`([^`]+)`", line.split(" | ")[0]) for line in table.splitlines() if line.startswith("| `")}
        named = {name for names in rows.values() for name in names}
        for path in (exitchecks.TOY_DIR + "/", classify.LEDGER_FILE, classify.REPORTS_DIR, cli.EXIT_FILE,
                     cli.MANIFEST_FILE, "referee/"):
            self.assertTrue(any(n == path or n.startswith(path) for n in named), f"27 has no reader row for {path}")
        toy = next(line for line, names in rows.items() if exitchecks.TOY_DIR + "/" in names)
        self.assertIn("`toy_tree_sha256`", toy)
        self.assertIn('exit_block["toy_tree_sha256"]', Path(decide.__file__).read_text(encoding="utf-8"))
        self.assertNotIn("E156", decide.EXIT_NOT_CHECKED["spec"])

    def test_29e_defines_the_founders_records_by_the_paths_the_classifier_uses(self):
        """Seed-005 (E391, E148's text): what a push of the Founder's records is, said where `29b` "Çıkıştan sonra"
        uses the term."""
        from snowball_bootstrap import classify, decide
        records = paragraph(spec_page("tohum", "29e"), "**Kurucu kayıtları.**")
        self.assertIn(f"Kökteki `{classify.LEDGER_FILE}` ve kökteki `{classify.REPORTS_DIR}` altındaki dosyalar "
                      "Kurucu kayıtlarıdır", records)
        self.assertTrue(classify.is_founder_record(classify.LEDGER_FILE))
        self.assertTrue(classify.is_founder_record(classify.REPORTS_DIR + "a.json"))
        self.assertIn("(iç içe bir `reports/` dizini koddur)", records)
        self.assertFalse(classify.is_founder_record("referee/" + classify.REPORTS_DIR + "a.json"))
        self.assertEqual(classify.classify(["spec/asama-0/a.md", classify.LEDGER_FILE]), ("spec", []))
        self.assertEqual(classify.classify([classify.LEDGER_FILE, classify.REPORTS_DIR + "a.json"]), ("none", []))
        self.assertIn("none", decide.NOTHING_TO_JUDGE)
        self.assertIn("sonuç `noop`'tur", records)
        self.assertIn('verdict = "noop"', Path(decide.__file__).read_text(encoding="utf-8"))
        self.assertIn("(`founder_ledger_invalid`, `asama-0/10` #kurucu-defteri)", records)
        push_kinds = paragraph(spec_page("tohum", "29b"), "**Üç tür push.**")
        self.assertIn("Kurucu kayıtları: `29e`.", push_kinds)

    def test_29e_names_what_the_referee_writes_for_secret_shaped_text(self):
        """Seed-009 and seed-010 (E392): the two rejections a secret-shaped string makes, the paths it names, and that
        a rival-side failure leaves the commit to be reviewed again; `29b` counts `secret_in_prompt` among what the
        Founder can fix and `secret_in_verdict` among the rival's failures (`decide.FOUNDERS_RIVAL_REASONS`)."""
        from snowball_bootstrap import decide
        text = paragraph(spec_page("tohum", "29e"), "**Sır desenli metin.**")
        rival_src = Path(rival.__file__).read_text(encoding="utf-8")
        decide_src = Path(decide.__file__).read_text(encoding="utf-8")
        for prefix in ("secret_in_prompt", "secret_in_verdict"):
            self.assertIn(f'out.reasons.append("{prefix}:" + ",".join(leaked))', rival_src)
            self.assertIn(f"`{prefix}:<kural>[,<kural>…]`", text)
        self.assertIn(f"(en çok {rival.MAX_SECRET_PATHS})", text)
        token = "gh" + "p_" + "A" * 36  # built at run time, never written
        context = f"note {token}\ndiff --git a/x.py b/x.py\n+{token}\ndiff --git a/y.py b/y.py\n+clean\n"
        self.assertEqual(rival.secret_paths(context), ["(request text)", "x.py"])
        self.assertIn("`(request text)`", text)
        self.assertIn('"secret_paths": list(self.secret_paths)', rival_src)
        self.assertIn("`rival.secret_paths`", text)
        for warning in ("rival_side_retry", "rival_side_streak"):
            self.assertIn(f'f"{warning}:{{state[', decide_src)
            self.assertIn(f"`{warning}:<n>`", text)
        self.assertEqual(decide.RIVAL_SIDE_WARN, 3)
        self.assertIn("üst üste üçüncü", text)
        self.assertEqual(decide.RIVAL_SIDE_FINAL, ("budget", "request_rejected"))
        self.assertIn("(bütçe ve `request_rejected` dışında)", text)
        page = spec_page("tohum", "29b")
        memory = paragraph(page, "**Ret hafızası.**")
        founders = memory.split("Rakibin hataları", 1)[0]
        for reason in decide.FOUNDERS_RIVAL_REASONS:
            self.assertIn(f"`{reason}`", founders)
        self.assertIn("`secret_in_verdict`", memory.split("Rakibin hataları", 1)[1].split(")", 1)[0])
        self.assertIn("Sır desenli metin: `29e`.", paragraph(page, "**Rakip çağrısı.**"))

    def test_29d_says_what_the_chain_judge_reads(self):
        """Seed-007 (E159): `chain` has its own judge, and what it compares was only in the code."""
        import inspect
        page = flat(spec_page("tohum", "29d"))
        self.assertIn("`chain`'in yargıcı da stdout'un son JSON satırını okur, çıkış kodunu karşılaştırmaz", page)
        judge = inspect.getsource(vectors._chain)
        for field in ("row_hash", "valid", "broken_row"):
            self.assertIn(f'.get("{field}")', judge)
            self.assertIn(f"`{field}`", page)
        self.assertNotIn("exit", judge)
        seed = json.loads((BOOT / "vectors" / "vectors.json").read_text(encoding="utf-8"))
        self.assertIn(f"`broken_row`'a (`{seed['chain']['v3_broken_row']}`, `29a`)", page)
        self.assertIn("Kırık zincirin çıkış kodunu ve `row_id`'si olmayan satırın `broken_row` değerini tohum "
                      "sabitlemez", page)

    def test_29k_says_the_diffguard_lists_are_the_floor_of_01bs_rule(self):
        """Seed-017 (E393): `29k`'s closed name lists read as the whole rule; the rule is `01b`'s ret list."""
        page = flat(spec_page("tohum", "29k"))
        self.assertIn("`config`, `manifest` ve `lockfile` listeleri vektörlerin tabanıdır; kural `01b`'nin ret "
                      "listesidir (lint, tip ve test yapılandırmaları, bağımlılık manifestleri ve kilitler), Kurucu "
                      "fazlasını tanıyabilir (`29a`)", page)
        self.assertIn("lint, tip ve test yapılandırmaları, bağımlılık manifestleri ve lockfile'lar",
                      flat(spec_page("tohum", "01b")))

    def test_26a_says_calls_is_read_for_the_order_alone_and_the_code_reads_it_so(self):
        """Spec-019 (E397; spec-014 (2), spec-021, spec-032): the frozen `calls` line names fewer edges than the
        tools' callers. The bootstrap referee reads `calls` only while loading the table, for the order; nothing
        compares the brain's imports with it."""
        import ast
        page = flat(spec_page("tohum", "26a"))
        self.assertIn("Önyükleme hakemi `calls`'u yalnız tabloyu yüklerken okur ve yalnız sırayı denetler", page)
        self.assertIn("Beyin ağacındaki içe aktarmaları ya da çağrıları `calls`'la karşılaştırmaz", page)
        self.assertIn("(`calls`'un okunuşu: `26a`)", flat(spec_page("tohum", "26c")))
        readers = []
        for path in sorted((BOOT / "snowball_bootstrap").glob("*.py")):
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if isinstance(node, ast.Attribute) and node.attr == "calls":
                    readers.append(path.stem)
                elif isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant) \
                        and node.slice.value == "calls":
                    readers.append(path.stem)
        self.assertEqual(readers, ["stages"])  # parse_table's order check, the one reader
        with self.assertRaisesRegex(Exception, "must come before its caller"):
            stages.parse_table(json.dumps({"stage": 0, "mfs": [
                {"mf": 1, "tests": [1], "groups": [], "module": "a.py", "calls": [2]},
                {"mf": 2, "tests": [2], "groups": [], "module": "b.py", "calls": []}]}), 0)

    def test_every_tool_in_26a_is_called_only_by_later_micro_features(self):
        """Spec-021, spec-026, spec-028, spec-032 (E398, E234): a tool's "Çağıran" that is itself a micro-feature's
        tool comes after it (`asama-0/14` "Sıra"; `gate.check` is MF8's pure decision, MF10's append calls MF11's
        anchor, not the other way). An item that is a tool's name alone is a caller; words beside it (a job, an
        event such as "`sentinel.run` kırmızısı") describe when, not who."""
        page = spec_page("tohum", "26a")
        mf, callers = {}, {}
        for line in page.splitlines():
            cells = [c.strip() for c in line.strip().strip("|").split(" | ")]
            if len(cells) != 8 or not cells[0].startswith("`"):
                continue
            number = re.match(r"(?:Aşama 0 )?MF(\d+)", cells[7])
            for tool in re.findall(r"`([a-z_.]+)`", cells[0]):
                callers[tool] = cells[6]
                if number:
                    mf[tool] = int(number.group(1))
        self.assertEqual(len(mf), 18)
        wrong = []
        for tool, cell in callers.items():
            items = [i.strip() for i in re.split(r"[,;](?![^()]*\))", cell)]
            for item in items:
                alone = re.fullmatch(r"`([a-z_.]+)`(?: \([^)]*\))?", item)
                if alone and alone.group(1) in mf and tool in mf and mf[alone.group(1)] <= mf[tool]:
                    wrong.append(f"{tool} (MF{mf[tool]}) <- {alone.group(1)} (MF{mf[alone.group(1)]})")
        self.assertEqual(wrong, [])
        write = next(line for line in page.splitlines() if line.startswith("| `target.write` |"))
        cells = [c.strip() for c in write.strip().strip("|").split(" | ")]
        self.assertIn("`brain/state` commit'i", cells[3])  # 26a's last paragraph: every write to brain/state is its
        self.assertIn("`exit.drill`", cells[6])  # MF14 plants the drill's bad merge through it (`22a`)
        self.assertIn("`yaz` işi (`gate.check`'in merge kararıyla)", cells[6])

    def test_25a_names_the_required_check_the_genesis_vectors_record(self):
        """Spec-021 (b) (E398): the loop's check-run must carry the name `brain/integration`'s ruleset requires."""
        row = next(line for line in spec_page("tohum", "25a").splitlines() if line.startswith("| 3 |"))
        name = re.search(r"zorunlu kontrol \(adı `([^`]+)`", row)
        self.assertIsNotNone(name, "25a row 3 names no required check")
        contexts = set()
        for path in sorted((BOOT / "vectors" / "genesis").glob("api*.json")):
            for rules in json.loads(path.read_text(encoding="utf-8")).values():
                for rule in rules if isinstance(rules, list) else []:
                    if isinstance(rule, dict) and rule.get("type") == "required_status_checks":
                        contexts |= {c["context"] for c in rule["parameters"]["required_status_checks"]}
        self.assertEqual(contexts, {name.group(1)})

    def test_26c_says_which_reason_expect_json_names_and_when_ret_holds(self):
        """Spec-038 (E399): `expect.json`'s `reason` is a gate reason, not the row's `cause`, and #ret holds when the
        candidate's gate decision's reasons are exactly `[reason]`."""
        ready = paragraph(spec_page("tohum", "26c"), "**Hazır aday**")
        example = re.search(r"ör\. `([a-z_]+)`", ready).group(1)
        gate_reasons = set(re.findall(r"`([a-z_]+)` \(", paragraph(spec_page("tohum", "29h"), "`python -m gate.check map")))
        self.assertIn(example, gate_reasons)
        self.assertIn("satırın `cause`'u değil", ready)
        self.assertIn("adayın kapı kararındaki sıralı, tekil nedenler tam olarak `[reason]` olduğunda tutar", ready)


def bullet(page, opening):
    """The flattened bullet of ``page`` that starts with ``opening`` (``- **Title.**``), up to the next bullet or blank."""
    found, current = [], None
    for line in page.splitlines():
        if line.startswith("- ") or not line.strip():
            if current is not None:
                found.append(flat(" ".join(current)))
            current = [line] if line.startswith(opening) else None
        elif current is not None:
            current.append(line)
    if current is not None:
        found.append(flat(" ".join(current)))
    if len(found) != 1:
        raise AssertionError(f"expected one bullet starting {opening!r}, found {len(found)}")
    return found[0]


def changelog_entry(page, first_words):
    """The flattened changelog entry (a ``- 2.2 (`` bullet) that starts with ``first_words``."""
    return bullet(page, "- 2.2 (" + first_words)


class OwnerDecisionPagesTest(unittest.TestCase):
    """The owner's decisions the operator wrote with the owner's authority on 2026-11-01 (E421-E436; the owner can
    take each back). Each is a rule or an interface fact on one page, held here against the code that applies it, and
    the Founder's reports this epoch answers are named in its changelog entry."""

    def spec_pages(self):
        return [p for p in sorted((ROOT / "spec").rglob("*.md")) if not p.name.startswith("CHANGELOG")]

    def test_physical_safety_is_one_rule_on_05_and_every_other_page_points_there(self):
        """Item 1 (E421): code that drives, stops, raises an alarm for or protects a physical process is on the
        security tier. One page states it (`05`); the class ladder, the derivation, setup day, the schema and the
        catalogue point at it, so no second wording can drift (the `29g` lesson, E400)."""
        rule = bullet(spec_page("tohum", "05"), "- **Fiziksel güvenlik.**")
        for words in ("Fiziksel bir süreci süren, durduran, onun için alarm veren ya da onu koruyan kod",
                      "eşikleri ve eskalasyonu dahil) güvenlik yoludur", "risk ağırlıklıdır (`20`)",
                      "K6 canlı olana kadar hiç, sonra yalnız K6 kapısından dokunulur, biçimleyici ve `--fix` dahil",
                      "Bu yolları sistem hedeften türetir (`14`)", "`targets[].safety_paths`",
                      "türetmeyi yalnız genişletir, hiçbir öneri daraltamaz",
                      "K6 canlı olana kadar birim seçimi güvenlik yollarını dışlar", "Aşama 1'in ilk birimi de"):
            self.assertIn(words, rule)
        self.assertNotIn("/", rule.replace("`--fix`", ""))  # a rule, not a product path
        source = next((ROOT / "spec" / "tohum").glob("05-*.md"))
        for page in self.spec_pages():
            text = flat(page.read_text(encoding="utf-8")).lower()
            with self.subTest(page=page.relative_to(ROOT).as_posix()):
                self.assertEqual("fiziksel bir süreci" in text, page == source)
        k6 = next(line for line in spec_page("tohum", "03").splitlines() if line.startswith("| K6 |"))
        self.assertIn("fiziksel güvenlik (`05`)", k6)
        for prefix in ("14", "25", "26c", "30"):
            self.assertIn('`05` "Fiziksel güvenlik"', flat(spec_page("tohum", prefix)), prefix)
        self.assertIn("safety_paths[]?}", flat(spec_page("tohum", "26c")))

    def test_the_referee_reads_the_owners_safety_paths_as_26c_names_them(self):
        """E421: `26c` makes `targets[].safety_paths` optional; the referee reads `targets[]` strictly, so a summary
        that carries the owner's list must load, and a malformed one must stop the run like any other list."""
        import tempfile
        from snowball_bootstrap import config
        self.assertEqual(config.TARGET_OPTIONAL_KEYS, frozenset({"safety_paths"}))
        row = {"id": "copy", "repo": "owner/copy", "kind": "copy", "base_sha": "c" * 40, "identifiers": ["X"],
               "excluded_paths": [], "unit_candidates": ["packages/api"]}
        base = {"seed_commit": "a" * 40, "seed_tree_sha256": "b" * 64}

        def load(*rows):
            with tempfile.TemporaryDirectory() as tmp:
                (Path(tmp) / "setup").mkdir()
                (Path(tmp) / "setup" / "summary.json").write_text(json.dumps(dict(base, targets=list(rows))))
                return config.load_summary(Path(tmp))

        self.assertEqual(len(load(row, dict(row, id="c2", safety_paths=["units/a", "units/b/c.py"])).targets), 2)
        self.assertEqual(len(load(dict(row, safety_paths=[])).targets), 1)
        for bad in (dict(row, safety_paths=["", "x"]), dict(row, safety_paths="units/a"), dict(row, safety_paths=[1]),
                    dict(row, safety_path=["units/a"])):
            with self.assertRaises(config.ConfigError, msg=repr(bad)):
                load(bad)

    def test_05_blocks_a_change_whose_consumers_the_gate_cannot_count(self):
        """Item 2 (E422): an unseen consumer is assumed, never ruled out (fail-closed)."""
        rule = bullet(spec_page("tohum", "05"), "- **Görünmeyen tüketici.**")
        self.assertEqual(rule, "- **Görünmeyen tüketici.** Kapının tüketicilerini sayamadığı değişiklik görünmeyen bir "
                               "tüketiciye dokunmuş sayılır ve `blocked`'dır (kapalıya düşüş).")

    def test_03_says_what_k0_is_in_an_ecosystem_without_a_rule_id_linter(self):
        """Item 7 (E423)."""
        k0 = next(line for line in spec_page("tohum", "03").splitlines() if line.startswith("| K0 |"))
        self.assertIn("ekosistemin kimlik ve konum veren ilk mekanik denetimi (kural kimliği veren linter yoksa da)", k0)

    def test_04_keeps_module_less_red_and_names_the_mutation_floor_but_not_its_value(self):
        """Item 10 (E424, E386): the measure is named (kills by non-import failures on the changed lines of the
        Founder's own code), never how to reach it; the floor's value is the owner's and not on the page."""
        rule = flat(spec_page("tohum", "04")).split("1. **Kasıtlı bozma.**", 1)[1].split("2. **Canlı yol.**", 1)[0]
        self.assertIn("**Modülsüz kırmızı:**", rule)
        self.assertIn("Modülsüz kırmızı şimdilik kalır.", rule)
        floor = rule.split("**Mutant öldürme tabanı:**", 1)[1]
        for words in ("Aşama 1'in çıkışından başlayarak her aşama çıkışı",
                      "Kurucu'nun kendi kodunun değişen satırlarında bir mutant öldürme tabanı ister",
                      "bir mutant ancak içe aktarma ya da sözdizimi hatası olmayan bir kırmızıyla öldürülmüş sayılır",
                      "Taban değeri aşama çıkışından önce sahip koyar."):
            self.assertIn(words, floor)
        self.assertEqual(re.findall(r"\d+", floor), ["1"])  # the stage, and no floor value
        self.assertNotIn("%", floor)

    def test_08_limits_processes_and_cpu_in_every_sandbox_that_runs_the_targets_tests(self):
        """Item 13 (E425)."""
        rule = flat(spec_page("tohum", "08")).split("2. **Konteyner.**", 1)[1].split("3. **Kırmızı kontrol.**", 1)[0]
        self.assertIn("Hedefin test paketini koşan her kum havuzu, kimin kodunda kurulursa kurulsun (Kurucu'nunki "
                      "dahil), süreç sayısı ve CPU sınırıyla koşar.", rule)

    def test_seed_001_the_founder_writes_its_ledger_and_the_brain_gets_spec_tohum_alone(self):
        """Seed-001 (E150), option (a): no seed ledger tool exists and no `seed/` reaches the brain. The six places
        that said otherwise say what the code does: the Founder appends its rows with its own code under `26`'s
        chain rule, the launcher appends the `cost` row, the brain receives `spec/tohum` alone."""
        import argparse
        # The seed's pages; the frozen `asama-0/03` and `asama-0/13` keep their words, the seed prevails (`02`).
        for page in self.spec_pages():
            if page.parent.name != "tohum":
                continue
            text = flat(page.read_text(encoding="utf-8"))
            with self.subTest(page=page.relative_to(ROOT).as_posix()):
                for stale in ("founder-ledger append", "defter aracı", "tohumun aracıyla", "seed/` varsa"):
                    self.assertNotIn(stale, text)
        sub = next(a for a in cli.build_parser()._actions if isinstance(a, argparse._SubParsersAction))
        self.assertEqual([c for c in sub.choices if "ledger" in c or "append" in c], [])  # the tool is not there
        ledger = bullet(spec_page("tohum", "00a"), "- **Durum defteri.**")
        self.assertIn("satırı kendi kodun `26`'nın zincir kuralıyla ekler, oturumun `cost` satırını başlatıcı yazar "
                      "(`24a` 4)", ledger)
        self.assertIn("yalnız-eklemeyi yargıladığı her push'ta denetler (`29b`)", ledger)
        launcher = (ROOT / "seed" / "founder" / "launch.py").read_text(encoding="utf-8")
        self.assertIn('"part": "founder", "kind": "cost"', launcher)  # the launcher's row, chained by `26`
        self.assertIn("row_hash", launcher)
        layout = spec_page("tohum", "24a").split("```", 2)[1]
        self.assertEqual([line for line in layout.splitlines() if line.startswith("seed/")], [])
        self.assertIn("spec/tohum (beyne gelen tek tohum)", layout)
        self.assertIn("Kurucu'nun koduyla zincirli (`26`); `cost` satırı başlatıcının", layout)
        founder = next(line for line in spec_page("tohum", "26").splitlines() if line.startswith("| `founder` |"))
        self.assertIn("Kurucu, kendi koduyla (zincir kuralı aşağıda); `cost` satırını başlatıcı (`24a` 4)", founder)
        reader = next(line for line in spec_page("tohum", "27").splitlines()
                      if line.startswith("| `founder-ledger.jsonl`"))
        self.assertIn("Kurucu, kendi koduyla (`26`'nın zincir kuralı); başlatıcı (`cost`)", reader)
        epoch = next(line for line in SETUP_DAY.splitlines() if line.startswith("| 10b |"))
        self.assertIn("aynı `spec/tohum`'u beyin `main`'ine tek commit'le it (beyne yalnız `spec/tohum` gelir, tohum "
                      "kodu gelmez: satırın `seed_sha256`'sı `null`)", epoch)
        runbook = flat((ROOT / "seed" / "founder" / "README.md").read_text(encoding="utf-8"))
        self.assertIn("beyne tohum kodu (`seed/`) gitmez", runbook)
        self.assertNotIn("beyinde `seed/` varsa", runbook)

    def test_seed_027_13_says_from_which_stage_the_root_record_binds_five_things(self):
        """Seed-027 (g), option (b) (E427): `13` names five bindings `29j`'s Stage 0 row does not carry; `13` says when
        they start and the Stage 0 row stays `29j`'s."""
        root = bullet(spec_page("tohum", "13"), "- **Kök ve dış günlük.**")
        self.assertIn("`policy.json` hash'ini bağlar; bu beş bağ Aşama 1'den başlar, Aşama 0'ın kök satırı `29j`'nin "
                      "`root` satırıdır.", root)
        self.assertIn("(zincirli `{row_id, ts, root, rekor_uuid, prev_hash, row_hash}` satırları, `27a`)",
                      flat(spec_page("tohum", "29j")))

    def test_seed_030_29j_names_where_the_inputs_are_made_and_promises_no_later_answer(self):
        """Seed-030 (E231), option (a): `29j` said the spec did not name the producers "yet", a promise the Founder
        would wait on (seed-040's lesson). The inputs are made in the Founder's referee code."""
        for page in sorted((ROOT / "spec" / "tohum").glob("29*.md")):
            with self.subTest(page=page.name):
                self.assertNotIn("henüz adlandırmaz", flat(page.read_text(encoding="utf-8")))
        self.assertIn("girdileri grubun dışında, Kurucu'nun hakem kodunda üretilir; tohum `build_ok`'un ve nöbetçinin "
                      "lint toplamının üreticisini adlandırmaz.", flat(spec_page("tohum", "29j")))

    def test_referee_016_the_rule_is_in_force_and_no_record_says_it_waits(self):
        """Referee-016 (E260): in the seed since 3a; the changelog and the register still said "karar bekliyor"."""
        for page in sorted((ROOT / "spec" / "tohum").glob("CHANGELOG*.md")):
            for line in page.read_text(encoding="utf-8").splitlines():
                if "E260" in line:
                    self.assertNotIn("karar bekliyor", line, page.name)
        row = next(line for line in (ROOT / "docs" / "eksik-kaydi.md").read_text(encoding="utf-8").splitlines()
                   if line.startswith("| E260 |"))
        self.assertTrue(row.split(" | ")[-1].startswith("kapandı"), row[-200:])

    def test_this_epochs_changelog_entry_names_every_report_it_answers(self):
        """E342's rule: a seed epoch's changelog entry names each report it answers or declines, in whichever
        changelog file the 80-line cap has moved the entry to (E507 moved this one to `CHANGELOG-4.md`)."""
        pages = "\n".join(p.read_text(encoding="utf-8") for p in sorted((ROOT / "spec" / "tohum").glob("CHANGELOG*.md")))
        entry = changelog_entry(pages, "2026-11-01, E421")
        for report in ("seed-001-seed-dir-missing", "referee-016-reproducer-polarity", "seed-027-root-choices",
                       "seed-030-cause-choices"):
            self.assertRegex(entry, re.escape(f"`{report}` → `") + r"\d\d[a-z]?:\d")
        for report in ("seed-023-run-record-producer", "spec-036-cycle-composition-unowned"):
            self.assertIn(f"`{report}` → declined: ", entry)
        self.assertIn("sahibin yetkisiyle operatör kararı (2026-11-01); sahip geri alabilir", entry)

    def test_29e_states_the_exam_fault_rule_the_referee_applies(self):
        """Item 14 (E426, E53): the operator's confirmed exam fault takes the streak entry it caused back. The page
        names the file, its fields and what changes; the code reads those fields and the result names them."""
        from snowball_bootstrap import config, decide
        rule = paragraph(spec_page("tohum", "29e"), "**Sınav hatası** (E53).")
        for words in ("`control.json` `exam_faults`'a `{head, signature}` olarak yazar",
                      "imzalı durumun `reject_streaks` anahtarı", "çürütmede `refutation:<anahtar>`",
                      "son tohum döneminin commit'i (dönem yoksa kurulum tohumununki) adlandırdığı başın atası olduğu "
                      "sürece", "sonraki tohum dönemi onu kendiliğinden kapatır",
                      "imzalı durumdaki seri girdisi geri alınır, imza `repeated`, `not_learning` ve "
                      "`repeat_events`'e girmez, başka nedeni olmayan ret seriler için kabul gibidir", "Ret kalır", "Geçerli imzalar sonucun `exam_faults`'undadır",
                      "Biçimsiz liste ya da beyinde olmayan baş koşuyu durdurur"):
            self.assertIn(words, rule)
        self.assertEqual(config.EXAM_FAULT_KEYS, frozenset({"head", "signature"}))
        self.assertEqual(decide.signature({"kind": "refutation_reproduced", "ref": "repro:" + "a" * 16}),
                         "refutation:" + "a" * 16)
        self.assertIn('"exam_faults": sorted(exam_faults)', Path(decide.__file__).read_text(encoding="utf-8"))
        self.assertIn("reverted_exits?, exam_faults?}", flat(spec_page("tohum", "26c")))
        self.assertIn("Sınav hatası: `29e`.", paragraph(spec_page("tohum", "29b"), "**Ret hafızası.**"))


class YamlSubsetPageTest(unittest.TestCase):
    """Seed-035 (E281): `asama-0/10` #is-akisi reads `loop.yml` with "the seed's restricted YAML subset", which only
    `wiring.py` defined. `29r` is the subset; every reason, bound and known-answer example on it is the parser's."""

    @classmethod
    def setUpClass(cls):
        from snowball_bootstrap import wiring
        cls.wiring = wiring
        cls.page = flat(spec_page("tohum", "29r"))

    def why(self, data):
        with self.assertRaises(self.wiring.Unparseable) as caught:
            self.wiring.parse(data)
        return caught.exception.why

    def test_every_reason_the_parser_gives_is_on_the_page_and_no_other(self):
        listed = re.search(r"Nedenler: ((?:`[a-z0-9_]+`(?:, )?)+)\.", self.page)
        self.assertIsNotNone(listed, "29r lists no reasons")
        src = Path(self.wiring.__file__).read_text(encoding="utf-8")
        code = set(re.findall(r'Unparseable\([^,()]+, "([a-z0-9_]+)"\)', src))
        chars = re.search(r'why = \{(.*?)\}\.get\(bad, "([a-z0-9_]+)"\)', src)
        code |= set(re.findall(r'"([a-z0-9_]+)"', chars.group(1))) | {chars.group(2)}
        named = re.findall(r"`([a-z0-9_]+)`", listed.group(1))
        self.assertEqual(len(named), len(set(named)))
        self.assertEqual(set(named), code)
        self.assertEqual(len(code), 20)

    def test_the_known_answer_examples_give_their_reason(self):
        examples = re.findall(r"`([^`]+)` → `([a-z_]+)`", self.page.split("Bilinen cevaplı örnekler", 1)[1])
        self.assertEqual(len(examples), 4)
        for text, why in examples:
            with self.subTest(text=text):
                self.assertEqual(self.why(text.encode("utf-8") + b"\n"), why)
        self.assertIn("CRLF satır sonu → `carriage_return`", self.page)
        self.assertEqual(self.why(b"on: push\r\n"), "carriage_return")

    def test_the_bounds_the_format_and_the_plain_scalar_indicators_are_the_parsers(self):
        self.assertIn(f"en çok {self.wiring.MAX_BYTES} bayt", self.page)
        self.assertIn(f"iç içelik en çok {self.wiring.MAX_DEPTH} düzeydir", self.page)
        start = self.page.split("Düz skaler ", 1)[1].split(" ile ya da ", 1)[0]
        named = set(re.findall(r"`(.)`", start)) | ({"`"} if "ters tırnak" in start else set())
        self.assertEqual(named, self.wiring.INDICATORS)
        self.assertIn(f"`workflow_unparseable:{self.wiring.WORKFLOW_FILE}:L<satır>:<neden>`", self.page)
        self.assertEqual(self.wiring.check({"loop.yml": b"- a\n"}), ["workflow_unparseable:loop.yml:L1:not_a_mapping"])
        self.assertIn("kök bir blok dizisiyse `L1:not_a_mapping`", self.page)
        self.assertEqual(self.wiring.check({"loop.yml": b""}), ["workflow_unparseable:loop.yml:L0:empty"])
        self.assertEqual(self.wiring.parse(b"a: |\n  x\n  y\n\n\nb: c\n"), {"a": "x\ny\n", "b": "c"})  # one final LF
        self.assertEqual(self.why(b"a:\n- x\n"), "not_a_key")  # an entry sits deeper than its key
        self.assertEqual(self.wiring.parse(b"a: false\nb: 1\nc: {}\nd: []\n"), {"a": "false", "b": "1", "c": {}, "d": []})
        self.assertIn("`29r`", flat(spec_page("tohum", "29p")))


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
        """E383: in its own workflow, which nothing cancels. In ci.yml a second push within a minute cancelled the
        first run (cancel-in-progress) and the next run checked only its own range: a push went unchecked."""
        command = "python3 seed/bootstrap/local/doc_with_change.py"
        flows = {p.name: p.read_text(encoding="utf-8") for p in sorted((ROOT / ".github" / "workflows").glob("*.y*ml"))}
        self.assertEqual([name for name, text in flows.items() if command in text], ["doc-with-change.yml"])
        floor = flows["doc-with-change.yml"]
        self.assertNotIn("concurrency", floor)
        self.assertNotIn("cancel-in-progress", floor)
        self.assertRegex(floor, r"(?m)^on:\n  push:\n    branches: \[main\]\n")
        self.assertNotRegex(floor, r"(?m)^\s*if:")  # every push to main, with no condition that could skip one
        self.assertIn('git diff --name-only "$BEFORE" "$AFTER" | ' + command, floor)  # the whole pushed range


class UnitShardTest(unittest.TestCase):
    """E501: on 2026-11-01 (run 41362049865) the referee's unit suite outgrew the Windows job's 20 minutes (the git
    tests of the activation tooling take minutes there; it had run in 6 to 8) and the job was cancelled, so main was
    not green. The Windows job runs the suite in shards (`local/unit_shard.py`); a shard that dropped a test, a test
    run twice, or a matrix that names other shards than the runner's K/N would hide that."""

    @staticmethod
    def runner():
        import importlib.util
        spec = importlib.util.spec_from_file_location("unit_shard", BOOT / "local" / "unit_shard.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_the_windows_matrix_and_the_runner_name_the_same_shards(self):
        ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        job = re.search(r"(?ms)^  unit-windows:\n(.*?)(?=^  \S|\Z)", ci).group(1)
        shards = json.loads(re.search(r"(?m)^        shard: (\[[0-9, ]+\])$", job).group(1))
        count = int(re.search(r'local/unit_shard\.py "\$SHARD/([0-9]+)"', job).group(1))
        self.assertEqual(shards, list(range(count)), "the matrix and K/N name different shards")
        self.assertIn("timeout-minutes: 20", job)
        self.assertIn("fail-fast: false", job)
        self.assertNotIn("unittest discover -s tests\n", job.split("Drill judge tests")[0])  # no unsharded run left
        self.assertIn("if: matrix.shard == 0", job.split("Drill judge tests")[1])  # the drill judge runs once

    def test_the_shards_are_the_whole_suite_once_with_each_class_whole(self):  # unit_shard_overwrites_a_class, unit_shard_all_in_one
        unit_shard = self.runner()
        suite = unittest.defaultTestLoader.discover(str(BOOT / "tests"), top_level_dir=str(BOOT / "tests"))
        every = sorted(t.id() for t in unit_shard.flatten(suite))
        self.assertGreater(len(every), 500)
        for n in (1, 4, 7):
            parts = unit_shard.shards(n, suite)
            self.assertEqual(len(parts), n)
            ids = [t.id() for part in parts for t in part]
            self.assertEqual(sorted(ids), every, n)  # nothing dropped, nothing twice
            homes = {}
            for k, part in enumerate(parts):
                for test in part:
                    self.assertEqual(homes.setdefault(unit_shard.class_of(test), k), k, test.id())
        self.assertTrue(all(unit_shard.shards(4, suite)))  # no empty shard: each job runs tests

    def test_a_module_that_fails_to_import_is_still_run(self):
        unit_shard = self.runner()
        broken = unittest.defaultTestLoader.loadTestsFromName("no_such_test_module_e501")
        suite = unittest.TestSuite([broken, unittest.defaultTestLoader.loadTestsFromTestCase(UnitShardTest)])
        ids = [t.id() for part in unit_shard.shards(4, suite) for t in part]
        self.assertIn("unittest.loader._FailedTest.no_such_test_module_e501", ids)

    def test_a_bad_shard_spec_stops(self):  # unit_shard_accepts_k_past_n
        unit_shard = self.runner()
        for spec in ("4/4", "-1/4", "a/4", "1", "1/0"):
            with self.assertRaises(SystemExit, msg=spec):
                unit_shard.parse(spec)
        self.assertEqual(unit_shard.parse("3/4"), (3, 4))
        with self.assertRaises(ValueError):
            unit_shard.shards(0, unittest.TestSuite())


class MutationShardTest(unittest.TestCase):
    """E410: the referee's mutants run in CI shards under one timeout. On 2026-11-01 (run 41267568917, 560 mutants in
    8 shards, 70 a shard) a mutant took 41 to more than 51 seconds on a standard runner; three shards ended in 46 to
    50 minutes and five hit the 60-minute timeout, so the run was cancelled and no commit of that day was green. A
    mutant added without more shards drifts into that again; this turns it red here first. E502: on 2026-11-02 (run
    41366571302, 931 mutants in 24 shards, 39 a shard) the suite had grown and a mutant took up to 177 seconds; eight
    shards hit the timeout. The bound is now set by the worst mutant seen, three minutes."""

    PER_SHARD = 15  # at three minutes a mutant, the worst seen (E502), a shard ends in 45 of its 60 minutes

    def test_the_shards_hold_every_mutant_inside_the_timeout(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("mutate", BOOT / "local" / "mutate.py")
        mutate = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mutate)
        ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        job = re.search(r"(?ms)^  mutation:\n(.*?)(?=^  \S|\Z)", ci).group(1)
        shards = json.loads(re.search(r"(?m)^        shard: (\[[0-9, ]+\])$", job).group(1))
        count = int(re.search(r'--shard "\$SHARD/([0-9]+)"', job).group(1))
        self.assertEqual(shards, list(range(count)), "the matrix and --shard K/N name different shards")
        self.assertIn("timeout-minutes: 60", job)
        self.assertLessEqual(-(-len(mutate.MUTANTS) // count), self.PER_SHARD,
                             f"{len(mutate.MUTANTS)} mutants in {count} shards: add shards to ci.yml")

    def test_each_mutant_a_test_names_is_one(self):
        """E486 (the eighth skeptic: three tests named mutants that no longer were, sixteen more were found): the
        trailing comment on a test names the mutants it kills (`local/mutate.py`); a name there that is no mutant's
        claims a measurement nothing makes."""
        import importlib.util
        spec = importlib.util.spec_from_file_location("mutate", BOOT / "local" / "mutate.py")
        mutate = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mutate)
        names = {m[0] for m in mutate.MUTANTS}
        dead = []
        for path in sorted((BOOT / "tests").glob("*.py")):
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
                found = re.search(r"def test_\w+\(self[^)]*\):[ \t]+#(.*)", line)
                for word in found.group(1).split() if found else ():
                    if re.fullmatch(r"[A-Za-z][A-Za-z0-9]*_[A-Za-z0-9_]+", word) and word not in names:
                        dead.append(f"{path.name}:{number} {word}")
        self.assertEqual(dead, [], "a test names a mutant local/mutate.py does not have")

    def test_a_stale_anchor_is_seen_before_any_mutant_runs(self):  # mutate_stale_anchor_unseen
        """E504: on 2026-11-02 (run 41376835109) E502 rewrote the shard list a mutant's anchor quoted; the anchor was
        found 0 times, and only its one shard of 64 said so, after the whole run. Each shard now checks every anchor
        first: one missing or found twice is named, a file that is gone too."""
        import importlib.util
        import tempfile
        spec = importlib.util.spec_from_file_location("mutate", BOOT / "local" / "mutate.py")
        mutate = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mutate)
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "a.py").write_text("x = 1\ny = 2\ny = 2\n", encoding="utf-8")
            mutants = [("fresh", "a.py", "x = 1\n", "x = 0\n", ""), ("gone", "a.py", "z = 3\n", "z = 0\n", ""),
                       ("twice", "a.py", "y = 2\n", "y = 0\n", ""), ("no_file", "b.py", "x", "y", "")]
            self.assertEqual(mutate.stale_anchors(Path(tmp), mutants),
                             ["gone (a.py: found 0x)", "twice (a.py: found 2x)", "no_file (b.py: found 0x)"])


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
