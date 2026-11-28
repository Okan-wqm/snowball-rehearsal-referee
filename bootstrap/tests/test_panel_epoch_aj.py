"""Seed epoch AJ (2026-11-23): the owner's hint E736 (new `00f`), a duty and not a recipe: E697's class rule holds for
all of the Founder's work, not only its agents; a cause that comes back is closed at the layer where it arises with a
check that fails if it returns; nothing is closed by covering it up; falsifiable after 5 sessions against the mirror.
The facts it states are cited `page:line`, and each citation is read here, so a cited line that moves turns this red.
Only `spec/tohum` reaches the brain, so each binding sentence is on a `tohum` page. The trailing comment on a test
names the mutants it kills (`local/mutate.py`)."""

import no_real_delays  # noqa: F401  (first: no test waits on a real delay, E751)
import re
import unittest
from pathlib import Path

BOOT = Path(__file__).resolve().parents[1]
ROOT = BOOT.parents[1]
TOHUM = ROOT / "spec" / "tohum"


def page(prefix: str) -> str:
    found = sorted(TOHUM.glob(f"{prefix}-*.md"))
    assert len(found) == 1, (prefix, found)
    return found[0].read_text(encoding="utf-8")


def flat(text: str) -> str:
    return " ".join(text.split())


def cited(prefix: str, first: int, last: int) -> str:
    """Lines FIRST..LAST of a page, as a `page:first-last` citation reads them."""
    return flat("\n".join(page(prefix).splitlines()[first - 1:last]))


def register_row(eid: str) -> str:
    rows = (ROOT / "docs" / "eksik-kaydi.md").read_text(encoding="utf-8").splitlines()
    return next(line for line in rows if line.startswith(f"| {eid} |"))


def hint() -> str:
    """E736's paragraph of `00f`, from its label to the end of the page."""
    text = flat(page("00f"))
    return text[text.index("**Sahibin ipucu (bu kez kural esnetildi; 2026-11-23, E736"):]


class ClassRuleHintTest(unittest.TestCase):
    """The owner's hint of 2026-11-23 (E736): the facts, four duty items and two binding guards; the design is the
    Founder's."""

    def test_00f_states_the_facts_and_each_citation_holds(self):
        # classrule_successes_unsaid classrule_e697_miscited classrule_mirror_miscited classrule_02_miscited
        # classrule_cited_lesson_line_moved classrule_no_page_claim_dropped
        text = hint()
        for words in ("Dersler başarısızlıktan da başarıdan da doğar: ilk ham ders satırı geri alınan ilk düzeltmenin "
                      "`cause`'uyla doğar, hayatta kalan başarılar da satır doğurur (`22:62-63`).",
                      "E697 ajanlar için der ki: zaafları ölçülen başarımdan kendin bulursun ve her sınıfı vaka başına bir "
                      "yamayla değil, kurallarda mimari bir değişiklikle kapatırsın; kurallar yanlışlanabilir kayıtlardır "
                      "(`00e:58-60`).",
                      "`/work/logs/mirror.json`'da `per_model` model sürümü başına `rejected_rows_by_reason`'ı, `repeats` 14 "
                      "günlük penceresinde birden çok reddedilmiş ya da dondurulmuş satırın ya da döngü koşusunun taşıdığı "
                      "ret nedeni ve kırmızı iş sınıflarını, sayı ve tarihleriyle verir (alanlar `26o:59-60`; tanımları "
                      "`seed/founder/mirror.py`'nin `SOURCES`'undadır, `26h:50-55`).",
                      "Geçmiş bir kararı gevşeten değişiklik reddedilir (`02:79-80`).",
                      "Sınıf kuralını ajanların ötesine, senin bütün işine taşıyan bir sayfa henüz yok."):
            self.assertIn(words, text, words)
        # each citation reads what the hint says it reads
        self.assertIn("geri alınan ilk düzeltmenin `cause`'uyla doğar; hayatta kalan başarılar da satır doğurur.",
                      cited("22", 62, 63))
        self.assertIn("Aynı `cause` üç kez tekrarlanınca genesis derslerden bir skill ya da dedektör taslaklar",
                      cited("22", 64, 65))
        self.assertIn("Ajanlarının zaaflarını ölçülen başarımlarından kendin bulursun ve her sınıfı vaka başına bir yamayla "
                      "değil, kurallarda mimari bir değişiklikle kapatırsın. Kurallar yanlışlanabilir kayıtlardır",
                      cited("00e", 58, 60))
        self.assertIn("`rejected_rows_by_reason`'da ya da `repeats`'te değil.", cited("26o", 59, 60))
        self.assertTrue(cited("26h", 50, 55).startswith("**Ölçüm aynası**"))
        self.assertIn("tanımları `seed/founder/mirror.py`'nin `SOURCES`'undadır.", cited("26h", 50, 55))
        self.assertIn("Geçmiş bir kararı gevşeten değişiklik reddedilir.", cited("02", 79, 80))
        self.assertTrue(cited("23", 12, 15).startswith("**Test sorusu.**"))
        # the mirror's window and fields are the code's
        mirror = (ROOT / "seed" / "founder" / "mirror.py").read_text(encoding="utf-8")
        self.assertIn("WINDOW_DAYS = 14  # the window of `repeats`", mirror)
        self.assertIn('"rejected_rows_by_reason": dict(g["reasons"]),', mirror)
        self.assertIn('"repeats": "rejection reason kinds of rejected and frozen rows in pilot-metrics.jsonl, and red '
                      'job classes "', mirror)

    def test_00f_states_the_duty_not_a_recipe(self):
        # classrule_hint_unlabelled classrule_agents_only classrule_successes_dropped classrule_design_prescribed
        # classrule_second_patch classrule_no_return_check classrule_layer_dropped classrule_genesis_rule_changed
        # classrule_tests_weakened classrule_threshold_lowered classrule_silent_deferral classrule_02_loosened
        # classrule_not_falsifiable classrule_growth_ignored classrule_decision_unnamed classrule_check_unrequired
        text = hint()
        for words in ("**Sahibin ipucu (bu kez kural esnetildi; 2026-11-23, E736; görev, reçete değil; korkuluklar "
                      "bağlayıcıdır). Doğrudan da yanlıştan da öğren; her sorunu bir sınıf olarak kapat; hiçbirinin "
                      "üstünü örtme.**",
                      "- Görev (tasarım senindir):",
                      "1. E697'nin sınıf kuralı yalnız ajanlarına değil, bütün işine uygulanır: bir ret, rakibin bir "
                      "çürütmesi, kendi denetimlerinin ya da ajanlarının yakaladığı bir hata ve işe yarayan kabul edilmiş "
                      "bir değişiklik, her biri yanlışlanabilir bir kaydın kaynağıdır (`22`'nin ders satırları). Kaydın "
                      "biçimi senindir.",
                      "2. Geri gelen bir neden (aynı sınıf iki kez) doğduğu katmanda, dönerse kırmızı olan bir denetimle "
                      "kapanır; ikinci bir vaka başına düzeltmeyle değil (`23`'ün test sorusu, `23:12-15`). `22:64-65`'in "
                      "genesis kuralı olduğu gibi kalır.",
                      "3. Hiçbir şey üstü örtülerek kapanmaz: zayıflatılmış, atlanmış ya da silinmiş test ya da denetim "
                      "yok, düşürülmüş eşik yok; neyin açık kaldığını ve ne zaman yeniden sınandığını adlandıran bir neden "
                      "satırı olmadan erteleme ya da muafiyet yok. `02:79-80`'in kuralı olduğu gibi kalır; bu madde onun "
                      "senin kendi işindeki yüzüdür.",
                      "4. Yanlışlanabilir: bu görevle geçen 5 oturumdan sonra aynanın pencere başına tekrar eden sınıfları "
                      "artmaz ve kapanan her sınıfın dönüşünü yakalayacak denetimi vardır. Artarlarsa yaklaşımını (kendi "
                      "kuralını) yeniden yazarsın, kanıtı adlandıran bir `decision` satırıyla."):
            self.assertIn(words, text, words)
        duty = text[text.index("- Görev (tasarım senindir):"):text.index("- Korkuluklar")]
        self.assertEqual(re.findall(r" ([1-9])\. ", duty), ["1", "2", "3", "4"])  # four duty items, in order
        for recipe in ("şablon", "şu adımlarla", "operatör yazar"):  # the duty hands over no design
            self.assertNotIn(recipe, text, recipe)

    def test_00f_keeps_its_line_count(self):  # classrule_00f_lines_shifted
        """The review of PR #39 (D1) shortened duty 1's last sentence in place: 00f keeps 38 lines and its duty items
        their lines, so nothing that cites 00f moves."""
        lines = page("00f").splitlines()
        self.assertEqual(len(lines), 40)  # epoch AK appended a pointer to 00g after line 38 (test_panel_epoch_ak)
        self.assertEqual(lines[25], "     Kaydın biçimi senindir.")  # 00f:26
        self.assertTrue(lines[26].startswith("  2. Geri gelen bir neden"))  # 00f:27

    def test_00f_states_the_guards(self):  # classrule_referee_loosened classrule_new_referee_rule classrule_rework_demanded
        text = hint()
        for words in ("- Korkuluklar (sahibin koşulu; bağlayıcıdır):",
                      "1. Bu ipucu hiçbir hakemi ya da denetimi gevşetmez ve yeni bir hakem kuralı getirmez: önyükleme "
                      "hakemi, rakip ve tam prepush değişmeden kalır.",
                      "2. Teslimde hiçbir yeniden yapım istenmez: görev bundan sonraki işine uygulanır; işin sırası "
                      "`CHANGELOG-14`'ünkidir."):
            self.assertIn(words, text, words)
        raw = page("00f")
        guards = raw[raw.index("- Korkuluklar (sahibin koşulu; bağlayıcıdır):"):]
        self.assertEqual(len(re.findall(r"(?m)^  [1-9]\. ", guards)), 2)  # two guards, each a list item

    def test_00e_points_to_00f_and_keeps_its_lines(self):  # classrule_00e_pointer_dropped classrule_00e_line_moved
        lines = page("00e").splitlines()
        self.assertEqual(lines[-1], "Sahibin 2026-11-23'ten sonraki ipuçları (E736'dan başlayarak) `00f`'dedir.")
        self.assertEqual(lines[-2], "")
        self.assertEqual(len(lines), 71)  # appended after line 69: nothing cited on `00e` moves
        self.assertTrue(lines[44].startswith("**Sahibin ipucu (bu kez kural esnetildi; 2026-11-22, E697"))  # 00e:45


class RecordsTest(unittest.TestCase):
    def test_the_register_rows(self):  # e736_unlabelled e736_open e736_recipe e737_open e737_bound_kept e738_open
        # e738_kill_claimed
        row = register_row("E736")
        for words in ("sahibin ipucu (bu kez kural esnetildi; 2026-11-23, Suderra sahip tarafı; panelsiz; E697 gibi "
                      "işaretli)", "Görev, reçete değil: hiçbir tasarım verilmez.",
                      "(1) E697'nin sınıf kuralı Kurucu'nun bütün işine uygulanır",
                      "(2) aynı sınıf iki kez gelince doğduğu katmanda, dönerse kırmızı olan bir denetimle kapanır",
                      "(3) hiçbir şey üstü örtülerek kapanmaz",
                      "(4) 5 oturumdan sonra aynanın pencere başına tekrar eden sınıfları artmaz",
                      "hiçbir hakem ya da denetim gevşemez, yeni hakem kuralı yok; teslimde yeniden yapım yok"):
            self.assertIn(words, row, words)
        self.assertEqual(row.count("|"), 7)
        self.assertTrue(row.endswith("| kapandı (tohum dönemi AJ; ölçüm Kurucu'nun) |"), row[-80:])
        row = register_row("E737")
        for words in ("`mutate.shard_count`", "en az 24", "256", "`test_wiring.MutationShardTest`",
                      "`mutation-complete`", "`mutate.py --check-plan`", "planı borusuz bir dosyaya yazar"):
            self.assertIn(words, row, words)
        self.assertEqual(row.count("|"), 7)
        self.assertTrue(row.endswith("| kapandı (tohum dönemi AJ) |"), row[-80:])
        row = register_row("E738")
        for words in ("45180563969", "`04:28-29`", "`MUTANT_TIMEOUT_S` (900)", "hiçbir zaman öldürme değildir",
                      "132 + 9, 180 dakikanın", "`MutantTimeoutTest`"):
            self.assertIn(words, row, words)
        self.assertEqual(row.count("|"), 7)
        self.assertTrue(row.endswith("| kapandı (tohum dönemi AJ) |"), row[-80:])
        self.assertIn("bir mutant ancak içe aktarma ya da sözdizimi hatası olmayan bir kırmızıyla öldürülmüş sayılır",
                      cited("04", 26, 29))  # E738's cited rule

    def test_this_entry_opens_with_its_first_task(self):
        # aj_first_task_not_first aj_order_changed aj_rework_demanded aj_changelog_unindexed aj_index_missing
        entry = flat((TOHUM / "CHANGELOG-19.md").read_text(encoding="utf-8").split("\n- 2.2 (2026-11-23, E736", 1)[1])
        self.assertIn("**İlk iş** (`25` 10b). Teslimden itibaren önyükleme hakeminin hiçbir denetimi kırmızı olmaz",
                      entry[:200])
        for words in ("bu dönem ne bir tablo, ne bir vektör, ne bir zorunlu politika yolu, ne hakemin kodu değiştirir; "
                      "yalnız sayfadır.",
                      "Kurucu'nun bugünkü işi sürer, sırası `CHANGELOG-14`'ünkidir; E736 bir görevdir, kırmızı bir görev "
                      "değil, ve hiçbir yeniden yapım istemez.",
                      "Raporların teyidi `26l`'nin kuralı olarak kalır, bu listenin bir maddesi değildir.",
                      "Yanıtlanan rapor yok."):
            self.assertIn(words, entry, words)
        index = (ROOT / "spec" / "INDEX.md").read_text(encoding="utf-8")
        self.assertIn("| `tohum/CHANGELOG-19.md` | Değişiklik Günlüğü — Tohum, 2.2'nin On Sekizinci Kayıtları |", index)
        self.assertIn("| `tohum/00f-gorev-haritasi-sahibin-ipuclari-4.md` | Görev Haritası, Devam: Sahibin İpuçları IV |",
                      index)
        log = (TOHUM / "CHANGELOG.md").read_text(encoding="utf-8").splitlines()
        self.assertEqual(log[10], "- 2.2 (2026-11-23, E736; tohum dönemi AJ, sahibin ipucu: doğrudan da yanlıştan da "
                                 "öğrenmek, her sorunu sınıf olarak kapatmak, üstünü örtmemek; yeni `00f`): "
                                 "`CHANGELOG-19.md`; başında **İlk iş**.")  # under epochs AN's, AL's, AM's and AK's entries (log[6]-log[9])
        for p in TOHUM.glob("*.md"):
            self.assertLessEqual(len(p.read_text(encoding="utf-8").splitlines()), 80, p.name)


if __name__ == "__main__":
    unittest.main()
