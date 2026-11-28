"""Seed epoch AN (2026-11-28): no test of the seed waits on a real delay (E751). The seed's full mutation run without
hints was red on shard 19 on 2026-11-25, 2026-11-26 and in run 46072742202: mutant `manifest_read_retries` put the
accepted manifest's read back on `gh_read`'s retry delays, a test reached them unmocked and slept for real, and the
whole suite ran past `mutate.MUTANT_TIMEOUT_S` (a timeout, never a kill, E738). The class is closed in the tests'
own layer: `tests/no_real_delays.py`, which every test module imports first, turns a sleep of the seed's code into a
red at once. The rule is appended to the end of `tohum/04`. The trailing comment on a test names the mutants it kills
(`local/mutate.py`)."""

import no_real_delays  # noqa: F401  (first: no test waits on a real delay, E751)
import ast
import json
import re
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from no_real_delays import STDLIB, RealDelay
from test_founder_capsule import load_launch

BOOT = Path(__file__).resolve().parents[1]
ROOT = BOOT.parents[1]
TESTS = BOOT / "tests"
TOHUM = ROOT / "spec" / "tohum"
LAUNCH = ROOT / "seed" / "founder" / "launch.py"
A = "a" * 40


def page(prefix: str) -> str:
    found = sorted(TOHUM.glob(f"{prefix}-*.md"))
    assert len(found) == 1, (prefix, found)
    return found[0].read_text(encoding="utf-8")


def flat(text: str) -> str:
    return " ".join(text.split())


def cited(prefix: str, first: int, last: int | None = None) -> str:
    return flat("\n".join(page(prefix).splitlines()[first - 1:last or first]))


def register_row(eid: str) -> str:
    rows = (ROOT / "docs" / "eksik-kaydi.md").read_text(encoding="utf-8").splitlines()
    return next(line for line in rows if line.startswith(f"| {eid} |"))


def failing_gh(calls: list):
    def run(*args, **kw):
        calls.append(args)
        return subprocess.CompletedProcess(args, 4, b"", b"gh: not logged in")
    return run


def slept_for_real(seconds):
    raise AssertionError(f"a real sleep of {seconds} s went through the guard")


def sleep_as(path: Path, seconds: float) -> None:
    """time.sleep called from a frame whose file is `path`, as the guard reads its caller."""
    exec(compile(f"time.sleep({seconds!r})", str(path), "exec"), {"time": time})


class GuardTest(unittest.TestCase):
    """The guard holds the process's sleep and turns the seed's delay into a red at once."""

    def test_the_guard_holds_the_process_sleep(self):  # no_delay_guard_removed
        self.assertIs(time.sleep, no_real_delays.guarded_sleep)
        self.assertIsNot(no_real_delays.REAL_SLEEP, no_real_delays.guarded_sleep)

    def test_a_retry_delay_of_the_seed_is_red_at_once(self):
        # no_delay_guard_sleeps no_delay_everyone_may_sleep no_delay_guard_removed
        self.assertIs(time.sleep, no_real_delays.guarded_sleep)  # first: without the guard the call below waits
        launch = load_launch()
        calls = []
        started = time.monotonic()
        with mock.patch.object(launch, "run", failing_gh(calls)), \
                mock.patch.object(no_real_delays, "REAL_SLEEP", slept_for_real), \
                self.assertRaises(RealDelay) as caught:
            launch.gh_read("api", "repos/o/brain/contents/snowball-tests.json")  # the real GH_RETRY_DELAYS_S
        self.assertLess(time.monotonic() - started, 5)
        self.assertEqual(len(calls), 1)
        self.assertEqual(launch.GH_RETRY_DELAYS_S[0], 10)
        self.assertIn("launch.py would sleep 10 s for real in a test", str(caught.exception))

    def test_an_except_exception_does_not_swallow_it(self):  # no_delay_is_an_exception no_delay_guard_removed
        self.assertIs(time.sleep, no_real_delays.guarded_sleep)  # first: without the guard the call below waits
        self.assertFalse(issubclass(RealDelay, Exception))
        launch = load_launch()
        with mock.patch.object(launch, "run", failing_gh([])), \
                mock.patch.object(no_real_delays, "REAL_SLEEP", slept_for_real):
            try:
                launch.gh_read("api", "x")
            except Exception as exc:  # what a retry loop or a cycle's guard catches
                self.fail(f"an `except Exception` caught the guard's red: {exc!r}")
            except RealDelay:
                pass

    def test_the_tests_own_poll_and_the_standard_library_still_sleep(self):
        # no_delay_tests_cannot_poll no_delay_stdlib_cannot_sleep no_delay_zero_is_a_delay
        sleep_as(Path(__file__), 0.01)  # a test's own poll
        sleep_as(STDLIB[0] / "subprocess.py", 0.01)  # `subprocess`'s waits
        sleep_as(LAUNCH, 0)  # a zero sleep is no delay
        with self.assertRaises(RealDelay):
            sleep_as(LAUNCH, 0.01)
        with self.assertRaises(RealDelay):
            sleep_as(ROOT / "seed" / "founder" / "deliver_epoch.py", 15)


class ThreadTest(unittest.TestCase):
    """A RealDelay in a worker thread ends only that thread; the test it ran in still ends with the error."""

    def test_a_delay_in_a_worker_thread_fails_its_test(self):  # no_delay_thread_unseen no_delay_thread_unrecorded
        class Inner(unittest.TestCase):
            def test_it(self):
                worker = threading.Thread(target=sleep_as, args=(LAUNCH, 0.01))
                worker.start()
                worker.join()

        result = unittest.TestResult()
        with mock.patch("sys.stderr"):  # the thread's traceback, printed by the default hook
            Inner("test_it").run(result)
        self.assertEqual(len(result.errors), 1, result.errors)
        self.assertIn("RealDelay", result.errors[0][1])
        self.assertEqual(no_real_delays.THREAD_DELAYS, [])


class LivePathTest(unittest.TestCase):
    """The failing mutant: the accepted manifest's read back on the retry delays is red at once, with no mock of
    `time.sleep` (only the guard)."""

    def test_the_accepted_manifest_read_never_waits(self):  # manifest_read_retries
        launch = load_launch()
        pilot = launch.Pilot(Path(tempfile.mkdtemp()), "o/brain", "o/referee", "target")
        calls = []
        started = time.monotonic()
        with mock.patch.object(launch, "run", failing_gh(calls)), mock.patch.object(launch, "say"):
            self.assertEqual(pilot.accepted_manifest({"state": {"last_accepted_sha": A}}),
                             {"error": "GitHubUnavailable"})
        self.assertEqual(len(calls), 1)
        self.assertLess(time.monotonic() - started, 5)


class EveryModuleTest(unittest.TestCase):
    """Each test module imports the guard first, so a hint's test run alone is guarded too. No seed code binds `sleep`
    by name: a test that mocks `time.sleep` (`mock.patch.object(launch.time, "sleep", ...)`) does not reach a name
    bound at import, so its call would meet the guard instead of the mock."""

    def test_every_test_module_imports_the_guard_first(self):  # no_delay_module_unguarded
        modules = sorted(TESTS.glob("test_*.py"))
        self.assertGreater(len(modules), 50)
        for path in modules:
            tree = ast.parse(path.read_text(encoding="utf-8"))
            imports = [node for node in tree.body if isinstance(node, (ast.Import, ast.ImportFrom))
                       and not (isinstance(node, ast.ImportFrom) and node.module == "__future__")]
            self.assertTrue(imports, path.name)
            self.assertIsInstance(imports[0], ast.Import, path.name)
            self.assertEqual([alias.name for alias in imports[0].names], ["no_real_delays"], path.name)

    def test_no_seed_code_binds_sleep_by_name(self):  # no_delay_sleep_bound_by_name
        bound = re.compile(r"^\s*from\s+time\s+import\s+[^\n]*\bsleep\b", re.M)
        found = [str(p.relative_to(ROOT)) for p in (ROOT / "seed").rglob("*.py")
                 if TESTS not in p.parents and bound.search(p.read_text(encoding="utf-8", errors="replace"))]
        self.assertEqual(found, [])


class PageTest(unittest.TestCase):
    """The rule is a fact at the end of `04`; `04:1-48` stay where they were."""

    def test_the_rule_and_each_citation(self):  # an_04_rule_unsaid an_04_layer_unsaid an_04_kill_unsaid
        text = cited("04", 50, 59)
        for words in ("**Tohumun kendi testleri gerçek bir gecikme beklemez** (E751).",
                      "`seed/bootstrap/tests`'in her test modülü önce `no_real_delays`'i içe aktarır",
                      "`RealDelay` yükseltir", "`except Exception`'ı onu yutamaz",
                      "zaman aşımıyla değil, bir kırmızıyla öldürülür", "(`04:28-29`; E679, E738)",
                      "saati mock'lar (`04:38`)",
                      "Muhafız yalnız test sürecinin `time.sleep`'ini görür: alt süreçler, `threading.Event.wait`",
                      "bir işçi iş parçacığındaki uyku testi bitişinde kırmızı yapar."):
            self.assertIn(words, text, words)
        self.assertTrue(cited("04", 28, 29).endswith("bir mutant ancak içe aktarma ya da sözdizimi hatası olmayan "
                                                     "bir kırmızıyla öldürülmüş sayılır. Taban değeri aşama "
                                                     "çıkışından önce sahip koyar."))
        self.assertTrue(cited("04", 38).startswith("Mock yalnız dış dünya için kullanılır: ağ, LLM sağlayıcısı, saat"))

    def test_appended_only_and_the_page_fits(self):  # an_04_line_moved
        lines = page("04").splitlines()
        self.assertEqual(lines[47], "sonuçlarıyla birlikte geçersizdir: ölçüm aracı ölçmüyordur.")  # 04:48, as it was
        self.assertEqual(lines[48], "")
        self.assertLessEqual(len(lines), 80)
        self.assertEqual([n for n, line in enumerate(lines, 1) if len(line) > 120], [])


class RecordsTest(unittest.TestCase):
    def test_the_register_row(self):  # an_e751_open
        row = register_row("E751")
        for words in ("`manifest_read_retries`", "46072742202", "`seed/bootstrap/tests/no_real_delays.py`", "`RealDelay`", "`04:50-59`"):
            self.assertIn(words, row, words)
        self.assertEqual(row.count("|"), 7)
        self.assertTrue(row.endswith("| kapandı (tohum dönemi AN) |"))

    def test_this_entry_opens_with_its_first_task(self):  # an_first_task_not_first an_changelog_unindexed
        log = (TOHUM / "CHANGELOG-23.md").read_text(encoding="utf-8")
        entry = flat(log.split("\n- 2.2 (2026-11-28, E751", 1)[1])
        self.assertIn("**İlk iş** (`25` 10b). Teslimden itibaren önyükleme hakeminin hiçbir denetimi kırmızı olmaz",
                      entry[:400])
        for words in ("Kurucu'nun bugünkü işi sürer, sırası `CHANGELOG-14`'ünkidir.", "Gevşetme yok."):
            self.assertIn(words, entry, words)
        index = (ROOT / "spec" / "INDEX.md").read_text(encoding="utf-8")
        self.assertIn("| `tohum/CHANGELOG-23.md` | Değişiklik Günlüğü — Tohum, 2.2'nin Yirmi İkinci Kayıtları |", index)
        top = (TOHUM / "CHANGELOG.md").read_text(encoding="utf-8").splitlines()
        self.assertTrue(top[6].startswith("- 2.2 (2026-11-28, E751–E752; tohum dönemi AN,"))  # the newest entry
        self.assertTrue(top[6].endswith("`CHANGELOG-23.md`; başında **İlk iş**."))
        self.assertLessEqual(len(log.splitlines()), 80)
        self.assertEqual([n for n, line in enumerate(log.splitlines(), 1) if len(line) > 120], [])


# ---- seed-105 (report desk, 2026-11-28): which names are a package manifest for a case's group (E752)
R105 = "seed-105-which-names-are-a-paket-manifesti-for-a-case-s-group"


class CaseGroupTest(unittest.TestCase):
    """E752: the answer appended to the end of `26m` (77-80) and `26n` (73-78); each citation is read at its line."""

    def test_the_names_and_the_walk(self):
        # an_105_project_json_counts an_105_29k_miscited an_105_walk_above_unit an_105_fallback_dropped
        text = cited("26m", 77, 80)
        for words in ("**Vakanın grubu** (`26e:68-69`; seed-105; devamı `26n:73-78`).",
                      "Paket manifesti temel adı `package.json` olan düzenli dosyadır (`29k:51`'in `manifest`'i), başka "
                      "hiçbir şey değildir: Nx'in `project.json`'ı da, `pyproject.toml`, `Cargo.toml` ya da `go.mod` da "
                      "grup işaretlemez.",
                      "Arama değiştirilen dosyanın dizininden birimin köküne kadardır, kök dahil, üstüne çıkmaz;",
                      "yolda manifest yoksa grup birimin köküdür.", "Sıkılaştırma: grup birimin kökü ya da altındadır."):
            self.assertIn(words, text, words)
        self.assertIn("`manifest` (temel adı `package.json`)", cited("29k", 51))
        self.assertIn("paket manifesti taşıyan dizindir; öyle bir dizin yoksa birimin köküdür (bu bir sıkılaştırmadır)",
                      cited("26e", 68, 69))
        self.assertIn("bağımlılık manifestleri", cited("01b", 17))

    def test_the_rest_and_each_citation(self):
        # an_105_profile_names an_105_brain_miscited an_105_rows_edited an_105_loosened an_105_undecided_kept
        text = cited("26n", 73, 78)
        for words in ("**Vakanın grubu, devam** (seed-105; `26m:77-80`).", "Aşama 1'in tek aracı `eslint`'tir (`29za:25`).",
                      "kendi sayfasında veri olarak getirir (`31c:23-27`); adları ne profil ne Kurucu koyar.",
                      "okunmayan manifest (bağ, dizin) işaretlemez, ağacın kökü `.`'dır.",
                      "Beynin `6f36fba`'sında arama birimin kökünün üstüne çıkar (`referee/cases/build.py:484-493`; "
                      "`referee/tests/test_cases.py:903-904` onu sabitler).",
                      "Açık grup kalmadı: `group_undecided` ara çözümünün yerini bu yanıt alır",
                      "Yazılmış satır durur (`26m:35-36`).", "Vektör değişmez; gevşetme yok."):
            self.assertIn(words, text, words)
        self.assertIn("Araç `eslint`'tir.", cited("29za", 25))
        self.assertTrue(cited("31c", 23, 27).startswith("**Yeni ekosistem kuralı.** Yeni bir ekosistem"))
        self.assertIn("manifest ve kilit dosyası desenleri", cited("31c", 23, 27))
        self.assertIn("dosyadaki bir kimlik yeniden yazılmaz", cited("26m", 35, 36))
        self.assertIn("Bilinmeyen ekosistem kapalıya düşer", cited("31g", 35))
        self.assertIn("dev/held-out bölmesi modül grubu bazındadır", cited("19", 69))
        self.assertIn("census_min_groups", cited("18a", 51))

    def test_appended_only_and_the_pages_fit(self):  # an_105_26m_line_moved an_105_26n_grown an_105_26e_touched
        m, n = page("26m").splitlines(), page("26n").splitlines()
        self.assertTrue(m[74].endswith("`26q`'dadır (seed-101)."))  # 26m:75, as it was
        self.assertEqual((m[75], len(m)), ("", 80))
        self.assertTrue(n[70].endswith("(yukarıda, `26s`)."))  # 26n:71, as it was
        self.assertEqual((n[71], len(n)), ("", 78))
        for lines, first in ((m, 76), (n, 72)):
            self.assertEqual([k for k, line in enumerate(lines[first:], first + 1) if len(line) > 120], [])
        self.assertEqual(len(page("26e").splitlines()), 80)

    def test_the_register_row_the_changelog_and_the_answer(self):
        # an_e752_open an_105_items_dropped an_105_answers_missing an_105_both_panels_unsaid
        row = register_row("E752")
        for words in ("seed-105 (Kurucu raporu)", "`26m:77-80`, `26n:73-78`", "Opus ve Sonnet paneli",
                      "`referee/cases/build.py:134-136`", "Gevşetme yok"):
            self.assertIn(words, row, words)
        self.assertEqual(row.count("|"), 7)
        self.assertRegex(row, r"\| kapandı \(tohum dönemi AN(; [^)]*)?\) \|$")
        log = (TOHUM / "CHANGELOG-23.md").read_text(encoding="utf-8").splitlines()
        starts = [k for k, line in enumerate(log) if line.strip().startswith(f"`{R105}` →")]
        self.assertEqual(len(starts), 1)
        items = []
        for line in log[starts[0] + 1:]:
            if not line.startswith("  - ") and not line.startswith("    "):
                break
            if line.startswith("  - "):
                items.append(line[4:line.index(")") + 1] if line[4:].startswith("(") else line[4:].split(" ")[0])
        self.assertEqual(items, ["(1)", "(1, olgu)", "(1, hedef)", "(1, hiç düzenlenmez)", "(1, yapım)", "(2)",
                                 "(2, yapım)", "soru", "(kendi okumaları)", "not"])
        self.assertIn("Opus ve Sonnet paneli, iki panelin madde satırları birleşik", flat("\n".join(log)))
        answers = json.loads((BOOT / "reports" / "answers.json").read_text(encoding="utf-8"))["answers"]
        self.assertEqual([(a["id"], a["kind"]) for a in answers if a["changelog"] == "CHANGELOG-23"],
                         [(R105, "answered")])


if __name__ == "__main__":
    unittest.main()
