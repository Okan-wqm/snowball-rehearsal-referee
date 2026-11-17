"""The Founder's lessons (`tohum/26g`; the owner's decision of 2026-11-17, E609-E611).

A lesson is a `founder` ledger row of kind `lesson` whose payload is `{summary, refs[], recheck}` (E609). Before each
session the launcher writes `/work/logs/lessons.json`: the id and claim of the newest live lessons of the ledger at the
head the session starts from, and how many were left out (E610). It only reads and lists: no re-check runs, nothing is
ranked, the ledger is never written. A lesson is retired by a later row's `closes:<row_id>` ref (the capsule index's own
`unclosed` fold) or by a later `supersedes` naming its `row_hash` (`13`). The owner's goal (E611) is stated once, in
`tohum/01`, and the core points to it. Nothing reaches GitHub here.
"""

import gzip
import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from snowball_bootstrap import ledgercheck

from helpers import ledger_bytes, ledger_rows, quiet_pilot
from test_founder_capsule import load_launch

ROOT = Path(__file__).resolve().parents[3]
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "founder-ledger-4423ff3.jsonl.gz"
HEAD = "a" * 40


def flat(text):
    return " ".join(text.split())


def page(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


def paragraph(text, opening):
    blocks = [flat(b) for b in re.split(r"\n\s*\n", text)]
    found = [b for b in blocks if b.startswith(opening)]
    if len(found) != 1:
        raise AssertionError(f"expected one paragraph starting {opening!r}, found {len(found)}")
    return found[0]


def lesson(claim="A lesson.", refs=(), recheck="python3 -m unittest tests.test_x"):
    return {"kind": "lesson", "payload": {"summary": claim, "refs": list(refs), "recheck": recheck}}


def chain(edits, count=None):
    """Chained founder rows f1..fN (`helpers.ledger_rows`), row i (0-based) carrying ``edits[i]``."""
    return ledger_rows(count or (max(edits) + 1 if edits else 1), edits=edits)


class KindTest(unittest.TestCase):
    """E609: `lesson` is a founder kind; the referee checks a lesson row's structure as any founder row's, never its
    payload; and the kind is not `learning`, which the brain's accepted ledger already holds as closed rows."""

    def test_a_lesson_row_is_a_founder_row_and_its_payload_is_not_judged(self):  # lesson_kind_dropped
        self.assertIn("lesson", ledgercheck.FOUNDER_KINDS)
        for payload in ({"summary": "s", "refs": [], "recheck": "none: no command reads this"}, {"summary": "s"}, {}):
            rows = chain({1: {"kind": "lesson", "payload": payload}})
            with self.subTest(payload=payload):
                self.assertEqual(ledgercheck.check(ledger_bytes(rows), None, whole=True), [])
                self.assertEqual(ledgercheck.check(ledger_bytes(rows), ledger_bytes(rows[:1]), whole=False), [])

    def test_learning_stays_out_because_the_real_ledger_closed_rows_of_it(self):  # lesson_kind_named_learning
        """The brain's ledger (its `4423ff3` copy) holds six accepted `kind: learning` rows, each closed by a later
        `supersedes` (`13`): they close only while `learning` is no founder kind. Were it one, the six closers would
        name valid rows and keep the exit shut."""
        data = gzip.decompress(FIXTURE.read_bytes())
        reasons, closures = ledgercheck.judge(data, data, whole=True)
        self.assertEqual(reasons, [])
        self.assertEqual(len(closures), 6)
        self.assertNotIn("learning", ledgercheck.FOUNDER_KINDS)
        with mock.patch.object(ledgercheck, "FOUNDER_KINDS", ledgercheck.FOUNDER_KINDS + ("learning",)):
            reasons, _ = ledgercheck.judge(data, data, whole=True)
        self.assertEqual(len(reasons), 6)
        self.assertTrue(all(r.startswith(f"{ledgercheck.ACCEPTED_INVALID}:supersedes:") for r in reasons), reasons)


class IndexTest(unittest.TestCase):
    """E610: `lesson_index` lists live lessons only, the newest LESSONS_MAX in ledger order, each claim cut at
    LESSON_CLAIM_MAX characters, and counts what it left out."""

    @classmethod
    def setUpClass(cls):
        cls.launch = load_launch()

    def index(self, rows):
        return self.launch.lesson_index(ledger_bytes(rows), HEAD)

    def ids(self, rows):
        return [r["row_id"] for r in self.index(rows)["rows"]]

    def test_a_later_closes_ref_retires_a_lesson_and_an_earlier_one_does_not(self):  # lesson_closing_tag_drifts
        rows = chain({0: {"payload": {"summary": "s", "refs": ["closes:f3"]}}, 1: lesson("one"), 2: lesson("two"),
                      3: {"payload": {"summary": "s", "refs": ["closes:f2"]}}})
        self.assertEqual(self.ids(rows), ["f3"])  # f2 closed by f4; f3 named only by f1, before it
        note = self.index(rows)
        self.assertEqual((note["lessons"], note["live"], note["shown"], note["left_out"]), (2, 1, 1, 0))
        rows = chain({0: lesson("one"), 1: lesson("two", refs=["closes:f1"])})  # a lesson that replaces another
        self.assertEqual(self.ids(rows), ["f2"])

    def test_a_later_supersedes_retires_a_lesson_and_an_earlier_one_does_not(self):
        # lesson_supersedes_ignored lesson_supersedes_any_order
        rows = chain({0: lesson("one"), 1: lesson("two")}, count=3)
        later = ledger_rows(1, start=4, prev=rows[-1]["row_hash"], edits={0: {"supersedes": rows[0]["row_hash"]}})
        self.assertEqual(self.ids(rows + later), ["f2"])
        first = ledger_rows(1, edits={0: {"supersedes": "e" * 64}})
        rest = ledger_rows(1, start=2, prev=first[0]["row_hash"], edits={0: lesson("one")})
        self.assertEqual(self.ids(first + rest), ["f2"])
        # an earlier row naming the lesson's hash: impossible in a chain, so build it by hand on the index's input
        hand = [dict(r) for r in rest]
        before = dict(first[0], supersedes=rest[0]["row_hash"])
        self.assertEqual([r["row_id"] for r in self.launch.lesson_index(ledger_bytes([before] + hand), HEAD)["rows"]],
                         ["f2"])

    def test_the_newest_are_kept_in_ledger_order_and_the_rest_are_counted(self):
        # lessons_keep_the_oldest lessons_left_out_uncounted
        cap = self.launch.LESSONS_MAX
        rows = chain({i: lesson(f"claim {i + 1}") for i in range(cap + 5)})
        note = self.index(rows)
        self.assertEqual((note["lessons"], note["live"], note["shown"], note["left_out"]), (cap + 5, cap + 5, cap, 5))
        self.assertEqual([r["row_id"] for r in note["rows"]], [f"f{n}" for n in range(6, cap + 6)])
        self.assertEqual([r["line"] for r in note["rows"]], list(range(6, cap + 6)))
        note = self.index(chain({i: lesson() for i in range(3)}))
        self.assertEqual((note["shown"], note["left_out"]), (3, 0))

    def test_a_claim_is_cut_at_the_cap_and_says_so(self):  # lesson_claim_not_cut lesson_claim_cut_flag_off_by_one
        cap = self.launch.LESSON_CLAIM_MAX
        rows = chain({0: lesson("x" * cap), 1: lesson("y" * (cap + 1)), 2: {"kind": "lesson", "payload": {}}})
        got = self.index(rows)["rows"]
        self.assertEqual([(len(r["claim"] or ""), r["claim_cut"]) for r in got], [(cap, False), (cap, True), (0, False)])
        self.assertIsNone(got[2]["claim"])
        self.assertEqual(sorted(got[0]), ["claim", "claim_cut", "line", "row_id"])  # no recheck, no refs: the row has them

    def test_only_lesson_rows_count_and_the_read_is_described(self):  # lessons_count_every_row
        rows = chain({0: {"kind": "decision"}, 1: lesson(), 2: {"kind": "seed_issue"}, 3: lesson(), 4: {"row_id": 7,
                                                                                                    "kind": "lesson"}})
        data = ledger_bytes(rows) + b"not json\n"
        note = self.launch.lesson_index(data, HEAD)
        self.assertEqual((note["lessons"], note["live"]), (3, 2))  # a lesson without a string row_id is not listed
        self.assertEqual(self.ids(rows), ["f2", "f4"])
        import hashlib
        self.assertEqual(note["ledger"], {"commit": HEAD, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
                                          "rows": 5, "unreadable": 1})
        empty = self.launch.lesson_index(b"", HEAD)
        self.assertEqual((empty["lessons"], empty["rows"], empty["ledger"]["rows"]), (0, [], 0))

    def test_the_index_runs_nothing(self):
        """A recheck is a command; the launcher lists and never runs it."""
        target = Path(tempfile.mkdtemp()) / "ran"
        rows = chain({0: lesson(recheck=f"touch {target}")})
        with mock.patch("subprocess.run", side_effect=AssertionError("ran")), \
                mock.patch("subprocess.Popen", side_effect=AssertionError("ran")), \
                mock.patch.object(self.launch, "run", side_effect=AssertionError("ran")):
            self.assertEqual(self.ids(rows), ["f1"])
        self.assertFalse(target.exists())


class NoteTest(unittest.TestCase):
    """E610: the cycle writes the note before the session from the ledger at the head the session starts from; a
    ledger that cannot be read leaves no file and a warning, and never stops the session."""

    def setUp(self):
        self.launch = load_launch()

    def pilot(self, data, calls):
        launch = self.launch

        class Fake(quiet_pilot(launch)):
            pass

        def fake_run(*argv, **_kw):
            calls.append(argv[-1])
            return type("P", (), {"returncode": 0 if data is not None else 1, "stdout": data or b""})()
        return Fake(Path(tempfile.mkdtemp()), "o/brain", "o/referee", "target"), fake_run

    def test_the_ledger_is_read_once_per_head(self):  # ledger_read_not_kept ledger_read_kept_across_heads
        calls = []
        pilot, fake_run = self.pilot(ledger_bytes(chain({0: lesson("one")})), calls)
        with mock.patch.object(self.launch, "run", side_effect=fake_run):
            rows = pilot.ledger_rows(HEAD)
            pilot.lessons_note("20261117T000000Z", HEAD)
            pilot.ledger_rows("b" * 40)
        self.assertEqual([r["kind"] for r in rows], ["lesson"])
        self.assertEqual(calls, [f"repos/o/brain/contents/founder-ledger.jsonl?ref={HEAD}",
                                 f"repos/o/brain/contents/founder-ledger.jsonl?ref={'b' * 40}"])
        note = json.loads((pilot.session_logs("20261117T000000Z") / "lessons.json").read_text(encoding="utf-8"))
        self.assertEqual(([r["claim"] for r in note["rows"]], note["ledger"]["commit"]), (["one"], HEAD))

    def test_an_unread_ledger_or_a_failed_index_leaves_no_file_and_says_only_the_class(self):
        # lessons_failure_stops_the_cycle
        for data, broken in ((None, False), (ledger_bytes(chain({0: lesson("secret text")})), True)):
            calls = []
            pilot, fake_run = self.pilot(data, calls)
            with self.subTest(data=data is None), mock.patch.object(self.launch, "run", side_effect=fake_run), \
                    mock.patch.object(self.launch, "say") as said, \
                    mock.patch.object(self.launch, "lesson_index",
                                      side_effect=RuntimeError("secret text") if broken else self.launch.lesson_index):
                pilot.lessons_note("20261117T000000Z", HEAD)
            self.assertFalse((pilot.session_logs("20261117T000000Z") / "lessons.json").exists())
            text = " ".join(c.args[0] for c in said.call_args_list)
            self.assertIn("lessons.json not written", text)
            self.assertNotIn("secret text", text)
            self.assertIn("RuntimeError" if broken else "could not be read", text)

    def test_the_file_is_there_when_the_session_starts(self):  # lessons_note_not_called lessons_note_after_the_session
        launch = self.launch
        seen = {}
        data = ledger_bytes(chain({0: lesson("one"), 1: lesson("two", refs=["closes:f1"])}))

        class Fake(quiet_pilot(launch)):
            heads = [HEAD, HEAD]

            def fetch_result(self):
                return None

            def brain_head(self):
                return self.heads.pop(0)

            def ledger_bytes(self, sha):
                seen.setdefault("read", []).append(sha)
                return data

            def refresh_inputs(self):
                pass

            def session(self, stamp, *a):
                note = self.session_logs(stamp) / launch.LESSONS_NOTE
                seen["note"] = json.loads(note.read_text(encoding="utf-8")) if note.exists() else None
                return {"exit": 0, "minutes": 1, "timed_out": False}

            def write(self, text):
                pass

        pilot = Fake(Path(tempfile.mkdtemp()), "o/brain", "o/referee", "target")
        pilot.idle, pilot.seed = 0, HEAD
        args = type("Args", (), dict(model="m", max_turns=1, budget_usd=1, session_timeout=1, referee_timeout=1))
        with mock.patch.object(launch, "say"), \
                mock.patch.object(launch, "run", side_effect=AssertionError("the cycle reached gh")):
            pilot.cycle(1, args)
        self.assertEqual([r["row_id"] for r in seen["note"]["rows"]], ["f2"])
        self.assertEqual(seen["note"]["ledger"]["commit"], HEAD)


class PageTest(unittest.TestCase):
    """E609-E611: the pages say what the code does, the prompt states the file as a fact, the goal is said once."""

    @classmethod
    def setUpClass(cls):
        cls.launch = load_launch()
        cls.page = page("spec/tohum/26g-semalar-kurucu-dersi.md")
        cls.flat = flat(cls.page)

    def test_26_holds_the_kind_set_the_referee_checks(self):  # page_kind_set_drops_lesson
        text = flat(page("spec/tohum/26-semalar.md"))
        found = re.search(r"\*\*`founder` satırı:\*\* `kind` ∈ \{([^}]*)\}", text)
        self.assertEqual(set(re.findall(r"`([a-z_]+)`", found.group(1))), set(ledgercheck.FOUNDER_KINDS))
        self.assertIn("(`lesson`'ınki `{summary, refs[], recheck}`, `26g`)", text)

    def test_the_page_names_every_field_and_bound_the_file_writes(self):  # lesson_page_numbers_drift
        note = self.launch.lesson_index(ledger_bytes(chain({0: lesson()})), HEAD)
        for key in [*note, *note["ledger"], *note["rows"][0]]:
            self.assertIn(f"`{key}`", self.flat, key)
        for phrase in ("`/work/logs/lessons.json`", "en yeni 100'ü", "500 karakterde", "`closes:<row_id>`",
                       "`{summary, refs[], recheck}`", "`none: <neden>`", "`recheck`'i koşturmaz"):
            self.assertIn(phrase, self.flat, phrase)
        self.assertEqual((self.launch.LESSONS_MAX, self.launch.LESSON_CLAIM_MAX, self.launch.LESSONS_NOTE,
                          self.launch.LESSON_KIND, self.launch.LESSON_CLOSING_TAG),
                         (100, 500, "lessons.json", "lesson", "closes"))
        self.assertLessEqual(len(self.page.splitlines()), 80)

    def test_a_lesson_is_self_contained_and_its_recheck_runs_as_written(self):  # lesson_page_drops_self_contained
        text = self.flat
        for phrase in ("Kendi başına anlaşılır ve uygulanır: onu yazan oturum olmadan okunur",
                       "anlam için değil kanıt içindir", "beyin klonunun kökünden yazıldığı gibi koşan bir komut"):
            self.assertIn(phrase, text, phrase)

    def test_no_referee_check_and_no_how(self):
        hakem = paragraph(self.page, "**Hakem.**")
        self.assertIn("derslere özgü bir hakem denetimi yoktur", hakem)
        for hint in ("kullan", "meli", "malı", "gerekirse", "istersen"):
            self.assertNotIn(hint, self.flat.casefold(), hint)

    def test_the_prompt_states_the_file_as_a_fact(self):  # prompt_lessons_note_unnamed
        prompt = page("seed/founder/prompt.md")
        text = paragraph(prompt, "**Dersler (gözlem).**")
        self.assertIn("`/work/logs/lessons.json`'dadır (`spec/tohum/26g`)", text)
        for hint in ("kullan", "meli", "malı", "gerekirse", "istersen"):
            self.assertNotIn(hint, text.casefold(), hint)

    def test_the_page_is_indexed_and_on_the_task_map(self):  # lesson_page_not_indexed lesson_page_off_the_task_map
        index = page("spec/INDEX.md")
        title = self.page.splitlines()[0].removeprefix("# ")
        okunma = next(l for l in self.page.splitlines() if l.startswith("Okunma: ")).removeprefix("Okunma: ")
        self.assertIn(f"| `tohum/26g-semalar-kurucu-dersi.md` | {title} | {okunma} |", index)
        task = page("spec/tohum/00b-gorev-haritasi.md").splitlines()
        for row in ("| Hafıza, defter, ders |", "| Şema ve araç imzası |"):
            self.assertIn("`26g`", next(line for line in task if line.startswith(row)), row)

    def test_the_owners_goal_is_said_once_and_the_core_points_to_it(self):
        # owner_goal_pointer_gone owner_goal_names_a_model owner_goal_restated owner_goal_drops_complexity
        goal = paragraph(page("spec/tohum/01-hedef-sistem.md"), "**Sahibin hedefi (sahip kararı, 2026-11-17).**")
        for phrase in ("Amaç belirli bir model değil, kabul edilmiş sağlam değişiklik başına en düşük maliyettir",
                       "doğruluk ve güvenlik önce gelir (Y12)", "Sistemin bilgisi bir modelde değil repodadır",
                       "daha az token ve daha az yeniden denemeyle", "çok daha küçük ve ucuz bir model de",
                       "kullanılabilir ve güvenlidir", "(`26g`)", "ölçülen maliyet belirler",
                       "güçlü model bugün mimardır, sistemin gereği değildir",
                       "Karmaşıklık da sistemin taşıdığı bir maliyettir ve düşük tutulur (sahip kararı, 2026-11-17)",
                       "sistemin kendi boyutu (spec sayfaları, denetimler, CI süresi, mutantlar, araçlar) ölçülür ve "
                       "raporlanır", "yerini ölçülmüş bir ihtiyaçla hak etmeyen birleştirilir ya da kaldırılır",
                       "Yeni bir mekanizma yalnız ölçülmüş bir ihtiyaçtan doğar",
                       "aşırı karmaşıklık, aşılamayan kilitler, biçimi doğruluk sanmak, değer yerine canlılığı ölçmek"):
            self.assertIn(phrase, goal, phrase)
        self.assertIsNone(re.search(r"\b(Opus|Sonnet|Haiku|Fable|USD)\b", goal))
        core = page("spec/tohum/00-cekirdek.md")
        self.assertIn("Sahibin hedefi `01`'dedir: sistemin bilgisi bir modelde değil repodadır", flat(core))
        pages = sorted((ROOT / "spec" / "tohum").glob("*.md")) + [ROOT / "seed" / "founder" / "prompt.md"]
        said = [p.name for p in pages if not p.name.startswith("CHANGELOG")
                and "kabul edilmiş sağlam değişiklik başına" in flat(p.read_text(encoding="utf-8"))]
        self.assertEqual(said, ["01-hedef-sistem.md"])

    def test_the_changelog_names_the_page_and_its_rows(self):  # changelog_drops_epoch_t
        log = page("spec/tohum/CHANGELOG.md")
        self.assertIn("`26g` (E609, E610)", log)
        self.assertLessEqual(len(log.splitlines()), 80)


if __name__ == "__main__":
    unittest.main()
