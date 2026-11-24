"""Seed epoch AK (2026-11-23): the owner's four hints E739-E742 (new `00g`), each a duty and not a recipe, with its
measured facts; the mirror's `context` section (E742, `26o`); and the report desk's answer to seed-102 (E743, the end of
`29za`). Each seed fact is cited `page:line` and each citation is read here, so a cited line that moves turns this red;
the brain's facts are cited `file:line` at the brain commit the page names (the brain is not read here). Only
`spec/tohum` reaches the brain, so each binding sentence is on a `tohum` page. The trailing comment on a test names the
mutants it kills (`local/mutate.py`)."""

import json
import re
import unittest
from pathlib import Path

BOOT = Path(__file__).resolve().parents[1]
ROOT = BOOT.parents[1]
TOHUM = ROOT / "spec" / "tohum"
REPORT = "seed-102-where-a-running-referee-finds-a-target-s-census-rule-set-is-unstated"


def page(prefix: str) -> str:
    found = sorted(TOHUM.glob(f"{prefix}-*.md"))
    assert len(found) == 1, (prefix, found)
    return found[0].read_text(encoding="utf-8")


def flat(text: str) -> str:
    return " ".join(text.split())


def cited(prefix: str, first: int, last: int | None = None) -> str:
    """Lines FIRST..LAST of a page, as a `page:first-last` citation reads them."""
    return flat("\n".join(page(prefix).splitlines()[first - 1:last or first]))


def register_row(eid: str) -> str:
    rows = (ROOT / "docs" / "eksik-kaydi.md").read_text(encoding="utf-8").splitlines()
    return next(line for line in rows if line.startswith(f"| {eid} |"))


def hint(eid: str) -> str:
    """One hint of `00g`, from its label to the next hint or the guards."""
    text = flat(page("00g"))
    start = text.index(f"**Sahibin ipucu (bu kez kural esnetildi; 2026-11-23, {eid}; görev, reçete değil).")
    ends = [i for i in (text.find("**Sahibin ipucu", start + 10), text.find("- Korkuluklar", start)) if i > 0]
    return text[start:min(ends)]


def changelog() -> str:
    return (TOHUM / "CHANGELOG-20.md").read_text(encoding="utf-8")


class OrganHintTest(unittest.TestCase):
    """E739: a candidate is judged by the organ that produced it."""

    def test_the_facts_and_each_citation(self):
        # ak_h1_page_rule_dropped ak_h1_12_miscited ak_h1_26j_miscited ak_h1_allowlist_fact_dropped
        # ak_h1_index_fact_dropped ak_h1_rerun_fact_dropped
        text = hint("E739")
        for words in ('"Listede olmayan bir hash\'in ürettiği aday, içeriği ne olursa olsun reddedilir" (`12:15-18`; '
                      "ayrıca `01b:9-12`). Kapı paketten yalnız `organ_ids`'i okur (`26j:32`).",
                      '`referee/gate/allowlist.py:32` "Of the package only ``organ_ids`` is read"; '
                      "`referee/loop/decide.py:252` kararı `AL.reasons(cand.package, ...)` ile paketin adlandırdığı "
                      "organlara verir.",
                      "saklanan çıktısının hash'ini o organın girdisinde taşır (`referee/runner/kos.py:86-89`) ve paket "
                      "bu çıktılardan birinin dosyasıdır (`referee/runner/candidate_rerun.py:8-10`); yeniden koşu "
                      "çıktıları organ kimliği olmadan alır (`referee/runner/kos.py:512-513`)."):
            self.assertIn(words, text, words)
        self.assertIn("Listede olmayan bir hash'in ürettiği aday, içeriği ne olursa olsun reddedilir.", cited("12", 15, 18))
        self.assertIn("olmayan organın çıktısı reddedilir.", cited("01b", 9, 12))
        self.assertEqual(cited("26j", 32), "(`finding`, `diff`, `organ_ids`, `definition_sha256`). Kapı yalnız "
                                           "`organ_ids`'i okur.")
        self.assertIn("ilk kullanımı Aşama 1 MF6'dır.", cited("26j", 35, 36))
        self.assertTrue(cited("26j", 30).startswith("**İzin listesi, MF9**"))
        self.assertIn("Beyin olguları beynin `94517ab` commit'indendir.", flat(page("00g")))

    def test_the_duty(self):  # ak_h1_unlabelled ak_h1_self_claim_allowed ak_h1_test_dropped ak_h1_window_dropped
        text = hint("E739")
        self.assertTrue(text.startswith("**Sahibin ipucu (bu kez kural esnetildi; 2026-11-23, E739; görev, reçete "
                                        "değil). Aday, onu üreten organla yargılanır.**"))
        for words in ("- Görev: kapının kararı, adayı hangi organın ürettiğine hakemin kendi bildiğiyle dayanır, adayın "
                      "kendisi için söylediğiyle değil (`12:15-18`).",
                      "Bunu, paketi listelenmiş bir organı adlandıran ama listede olmayan bir organın ürettiği adayın "
                      "reddedildiği bir testle göster.",
                      "Zaman: ilk girişten (Aşama 1 MF6, `26j:35-36`) sonra ikinci bir organ çağrılmadan önce; kapı "
                      "P1'in MF9'udur (`26j:30`), P1 açıkken bu P1'in kodudur."):
            self.assertIn(words, text, words)


class ToolHintTest(unittest.TestCase):
    """E740: an organ reaches the tools its page promises."""

    def test_the_facts_the_duty_and_each_citation(self):
        # ak_h2_unlabelled ak_h2_26m_miscited ak_h2_deps_fact_dropped ak_h2_network_fact_dropped
        # ak_h2_no_page_fact_dropped ak_h2_untested ak_h2_after_the_run
        text = hint("E740")
        self.assertTrue(text.startswith("**Sahibin ipucu (bu kez kural esnetildi; 2026-11-23, E740; görev, reçete "
                                        "değil). Organ, sayfasının söz verdiği araca ulaşır.**"))
        for words in ("adapter birimin lint aracına snapshot'tan değil, birimin tarifinden Aşama 0'ın `deps.fetch`'iyle "
                      "`koş` koşusunda ulaşır; snapshot'ın hariç tutmaları değişmez (`26m:23-24`).",
                      '`koş` organı snapshot üzerinde koşar, "no installed dependency is in it" '
                      "(`referee/runner/kos.py:79-82`); organın çağrısına imaj, ağaç ve ortam verilir, `deps` verilmez "
                      "(`referee/runner/kos.py:324-325`); kap ağsızdır (`referee/runner/organs.py:6`).",
                      "Aynı modül adapter'ın aracına nasıl ulaştığını hiçbir sayfanın söylemediğini yazar "
                      "(`referee/runner/kos.py:97-99`, seed-074); `26m:23-24` bunu söyler.",
                      "- Görev: Aşama 1 MF1'in ilk canlı koşusundan önce bir organın koşusunun `26m:23-24`'ün söylediğine "
                      "ulaşıp ulaşmadığını sına. Ulaşmıyorsa boşluk `koş`'u taşıyan partide, araç ulaşılamazsa kırmızı "
                      "olan bir testle kapanır."):
            self.assertIn(words, text, words)
        self.assertIn("birimin tarifinden Aşama 0'ın `deps.fetch`'iyle (`asama-0/06`) `koş` koşusunda ulaşır; "
                      "snapshot'ın hariç tutmaları (`13c:14-15`) değişmez.", cited("26m", 23, 24))


class LessonHintTest(unittest.TestCase):
    """E741: lessons scale: retrieval and recheck."""

    def test_the_facts_the_duty_and_each_citation(self):
        # ak_h3_unlabelled ak_h3_count_changed ak_h3_scope_fact_dropped ak_h3_22_miscited ak_h3_26g_miscited
        # ak_h3_recheck_fact_dropped ak_h3_rerun_row_dropped ak_h3_grows_with_the_set ak_h3_design_prescribed ak_h3_not_falsifiable
        text = hint("E741")
        self.assertTrue(text.startswith("**Sahibin ipucu (bu kez kural esnetildi; 2026-11-23, E741; görev, reçete "
                                        "değil). Dersler büyür: bulma ve yeniden sınama.**"))
        for words in ("81 `lesson` satırı; 81'inin `recheck`'i var, hiçbirinin `scope`'u yok.",
                      "İlk ders satırı 2026-11-18'dedir (`f1503`); o günün sonunda 9 ders vardı.",
                      "Dersin alanları `22:25-33`'tedir (`scope` `22:29`); satırın yükü `{summary, refs[], recheck}`'tir "
                      "(`26g:12`); başlatıcı en yeni 100 dersi listeler (`26g:48`).",
                      "`tests/lesson_recheck.py` yürürlükteki her dersin `recheck`'ini koşar, birer birer, defter "
                      "sırasıyla (`tests/lesson_recheck.py:1`, `:25`). 20261123T201159Z oturumunda bu koşu oturumun "
                      "kendi 25 dakikalık sınırına sığmadı, `f1972`'de durdu ve yeniden koşuldu (commit `0fa9ef6`'nın mesajı; defter "
                      "satırı `f2082`).",
                      "- Görev: dersler büyüdükçe onları okumanın ve yeniden sınamanın maliyeti her oturumda bütün "
                      "kümeyle büyümez, ve bir ders ilgili olduğu işe ulaşır. Nasıl olacağını sen tasarlarsın",
                      "Yanlışlanabilir: bu görevle geçen 5 oturumdan sonra."):
            self.assertIn(words, text, words)
        self.assertTrue(cited("22", 25, 33).startswith("| Alan | Anlamı |"))
        self.assertIn("| `derived_from` |", cited("22", 25, 33))
        self.assertTrue(cited("22", 29).startswith("| `scope` |"))
        self.assertIn("Yükü `{summary, refs[], recheck}`'tir", cited("26g", 12))
        self.assertIn("`rows` yürürlükteki derslerin en yeni 100'ü", cited("26g", 48))


class ContextHintTest(unittest.TestCase):
    """E742: context is a measured resource; the mirror's facts, and the Founder decides."""

    def test_the_facts_the_duty_and_each_citation(self):
        # ak_h4_unlabelled ak_h4_00d_miscited ak_h4_counts_changed ak_h4_tokens_dropped ak_h4_mirror_unnamed
        # ak_h4_design_given ak_h4_not_falsifiable
        text = hint("E742")
        self.assertTrue(text.startswith("**Sahibin ipucu (bu kez kural esnetildi; 2026-11-23, E742; görev, reçete "
                                        "değil). Bağlam ölçülen bir kaynaktır.**"))
        for words in ("E676 (`00d:41-50`, 2026-11-20) arama tabanlı okumayı önerdi; beyinde onu kuran bir araç ve "
                      "E676'yı adlandıran bir defter satırı yok.",
                      "20261123T125013Z oturumu 2, 20261123T152245Z oturumu 3 kez sıkıştırıldı; ilk sıkıştırma "
                      "oturumun damgasından 9,7 ve 3,6 dakika sonradır; her sıkıştırmadan önce bağlam 166.725 ile "
                      "174.293 giriş tokenı arasındaydı (transkriptin `compact_boundary` olayı, "
                      "`compact_metadata.pre_tokens`).",
                      "Bu dönemden itibaren `mirror.json`'un `context` bölümü onları oturum başına verir (`26o` "
                      '"Bağlam ve sıkıştırma").',
                      "- Görev: bu olguları okursun ve kararı sen verirsin; hiçbir tasarım verilmez. Yanlışlanabilir: bu "
                      "görevle geçen 5 oturumdan sonra aynanın `context` sayılarıyla."):
            self.assertIn(words, text, words)
        self.assertTrue(cited("00d", 41, 50).startswith("**Sahibin ipucu (2026-11-20, E676;"))
        self.assertIn("- Ölçülür:", cited("00d", 41, 50))
        self.assertTrue(cited("26h", 50, 55).startswith("**Ölçüm aynası**"))

    def test_26o_states_the_mirrors_fields_as_the_code_names_them(self):
        # ak_26o_paragraph_dropped ak_26o_subagent_counted ak_26o_cap_changed ak_26o_not_measured_unsaid
        text = flat(page("26o"))
        para = text[text.index('**Bağlam ve sıkıştırma** (E742, sahibin ipucu, `00g`).'):]
        for words in ("`mirror.json`'un `context` bölümüne en yeni 20 oturumun her biri için",
                      "`compact_boundary` olaylarından (bir alt ajanınki sayılmaz)",
                      "`compactions` (sayı), `first_compaction_min` (ilkinin dakikası) ve `each`",
                      "`input_tokens_before` (olayın `compact_metadata.pre_tokens`'ı; yoksa oturumun ondan önceki son "
                      "kendi mesajının giriş, önbellek okuma ve önbellek yazma tokenları) ve `tokens_from` (`pre_tokens` "
                      "ya da `last_usage`)",
                      "oturum başına en çok 20, kalanı `each_left_out`.",
                      "Olmayan değer `null`'dır ve nedeni `not_measured`'dadır",
                      "Yalnız olgudur; tanımı `seed/founder/mirror.py`'nin `SOURCES`'undadır."):
            self.assertIn(words, para, words)
        mirror = (ROOT / "seed" / "founder" / "mirror.py").read_text(encoding="utf-8")
        for words in ("COMPACTIONS_MAX = 20", "SESSIONS_MAX = 20", '"context": lambda: context(logs, before()),',
                      '"tokens_from": "pre_tokens" if pre is not None else "last_usage"'):
            self.assertIn(words, mirror, words)
        self.assertEqual(len(page("26o").splitlines()), 79)
        self.assertIn("`rejected_rows_by_reason`'da ya da `repeats`'te değil.", cited("26o", 59, 60))  # E736's citation
        readme = flat((ROOT / "seed" / "founder" / "README.md").read_text(encoding="utf-8"))
        self.assertIn("ve tohum dönemi AK'den (E742, `tohum/26o`) son 20 oturumun `context`'i", readme)


class GuardsTest(unittest.TestCase):
    def test_00g_states_the_guards_and_hands_over_no_design(self):
        # ak_referee_loosened ak_new_referee_rule ak_rework_demanded ak_guards_not_falsifiable ak_guards_partial
        text = flat(page("00g"))
        guards = text[text.index("- Korkuluklar (sahibin koşulu; dördü için bağlayıcıdır):"):]
        for words in ("1. Bu ipuçları hiçbir hakemi ya da denetimi gevşetmez ve tohumdan yeni bir hakem kuralı "
                      "getirmez: E739 ve E740 senin kendi kodunu var olan sayfalarla (`12:15-18`, `26m:23-24`) hizalar.",
                      "2. Teslimde, E739 ve E740'ın sayfaların zaten istediği işin ötesinde hiçbir yeniden yapım "
                      "istenmez; işin sırası `CHANGELOG-14`'ünkidir.",
                      "3. Yanlışlanabilir: E739 ve E740 kendi testleriyle; E741 ve E742 5 oturumdan sonra aynanın ve "
                      "defterin sayılarıyla."):
            self.assertIn(words, guards, words)
        raw = page("00g")
        self.assertEqual(len(re.findall(r"(?m)^  [1-9]\. ", raw[raw.index("- Korkuluklar"):])), 3)
        self.assertEqual(re.findall(r"E7[0-9]{2}; görev, reçete değil\)", raw),
                         [f"E{n}; görev, reçete değil)" for n in (739, 740, 741, 742)])  # four hints, in order
        for recipe in ("şablon", "şu adımlarla", "operatör yazar"):
            self.assertNotIn(recipe, raw, recipe)

    def test_00f_points_to_00g_and_keeps_its_lines(self):  # ak_00f_pointer_dropped ak_00f_line_moved
        lines = page("00f").splitlines()
        self.assertEqual(lines[-1], "Sahibin E739'dan başlayarak ipuçları `00g`'dedir.")
        self.assertEqual((lines[-2], len(lines)), ("", 40))
        self.assertEqual(lines[25], "     Kaydın biçimi senindir.")  # 00f:26, as epoch AJ left it
        self.assertTrue(lines[37].startswith("  2. Teslimde hiçbir yeniden yapım istenmez"))  # 00f:38


class CensusAnswerTest(unittest.TestCase):
    """E743, seed-102: where a running referee finds a target's census rule set; the end of `29za`."""

    @staticmethod
    def answer() -> str:
        text = flat(page("29za"))
        return text[text.index("**Koşan hakem bir hedefin `census` kümesini nerede bulur**"):]

    def test_the_items_and_each_citation(self):
        # ak_102_set_read_at_run_time ak_102_kind_miscited ak_102_caller_set_counted ak_102_copy_counted
        # ak_102_two_tools_counted ak_102_enabled_read_again ak_102_lists_unnamed ak_102_score_fact_dropped
        text = self.answer()
        for words in ("(rapor masası uzlaşısı (2026-11-23), seed-102; kurulduğu gibi benimsendi; gevşetme yok).",
                      "- (1) Küme hakemin kendisinindir: hakem onu kendi ağacında hedefin `kind`'ıyla anahtarlı tutar "
                      "(`setup/summary.json`'un `targets[].kind`'ı, `26c:30-31`; `29z:25`); koşuda tohumun vektör "
                      "dosyalarından, politikadan, `state_root`'tan ya da hedeften okumaz (`29za:9` \"hakemin tarafında "
                      "sabittir\", `29za:28-29`, `26q:74-80`).",
                      "Hiçbir dosya okunmadığı için dosya ya da anahtar adı yoktur: tohumun `census` vektörü kümenin "
                      "dayanağı ve test girdisidir, koşu girdisi değildir.",
                      "- (1) Koşuda puanlama (döngü ya da çıkış) hedefin türü için hakemin kendi kümesi üzerinden sayar, "
                      "asla çağıranın verdiği bir küme üzerinden değil; puanlayıcının çağırandan aldığı `--census` "
                      "girdisi (beynin `94517ab`'sında `referee/harness/score.py:427`, `:460`) yalnız iki dosyalı "
                      "vektör komutunundur.",
                      "- (1) Kopyanın kümesi, kopyanın `census` vektörünü commit'leyen tohum dönemine ertelendi "
                      "(operatörün açık işi, `29za:19-22`; Aşama 1 çıkışından önce var olmalıdır, `29za:21`); o güne "
                      "kadar kopyanın sayımı yoktur, hükmü asla `PASS` değildir.",
                      "- (2) Bir `census` kümesi tek aracın kurallarıdır (`29za:24-25` \"Araç `eslint`'tir\"): \"araç "
                      "başına\" kuruluştan tutar ve `26b`'nin tek `census` nesnesi (`26b:43`) o kümenin sayımıdır; iki "
                      "araçlı, kuralsız ya da bir kuralı iki kez taşıyan küme reddedilir (`census_invalid`), sayılmaz, "
                      "hükmü asla `PASS` değildir",
                      "İki aracın rapor biçimi ikinci bir aracın ilk `census` vektörüne ertelendi (K4'ün sayımı Aşama "
                      "3'tedir, `26m:72`).",
                      "- (3) `29za:11-12`'nin kural başı raporunda \"etkin\" sabitlenmiş commit'teki vektörün kümesidir "
                      "(oyuncakta `de5b57c`, kopyada `base_sha`), koşuda yeniden okunan hedef yapılandırması değil; "
                      "\"üretilebilir\" `cases.build produce`'un cevabıdır; çıkışta puanlayıcının kural başı listeleri "
                      "(`uncased_rules`, `missed_rules`) `29za:15-17`'nin koşulunu taşır."):
            self.assertIn(words, text, words)
        self.assertIn("`targets[]` `{id, repo, kind: toy|copy, base_sha,", cited("26c", 30, 31))
        self.assertIn("`setup/summary.json`'da `kind: toy` olan tek hedefin", cited("29z", 25))
        self.assertIn("**K0 sayımının paydası hakemin tarafında sabittir**", cited("29za", 9))
        self.assertIn("o güne kadar kural kümesi bu sayfadadır.", cited("29za", 28, 29))
        self.assertTrue(cited("26q", 74, 80).startswith("- (10) Payda: `rules_total` hedefin `census` vektörünün"))
        self.assertTrue(cited("29za", 19, 22).startswith("**Kopya hedefin vektörü**"))
        self.assertIn("O vektör var olana kadar kopyanın sayımı Aşama 1 çıkışını geçemez.", cited("29za", 21))
        self.assertIn("Araç `eslint`'tir.", cited("29za", 24, 25))
        self.assertIn("`census` `{rules_total, rules_covered, misses}`", cited("26b", 43))
        self.assertIn("(4) K4'ün sayımı Aşama 3'e ertelendi", cited("26m", 72))
        self.assertIn("Hakem her kural için etkin ile üretilebilir olanı vektöre karşı raporlar", cited("29za", 11, 12))
        self.assertIn("en az bir geçerli `asama-1/13a` vakası olmalıdır.", cited("29za", 15, 17))

    def test_no_cited_line_moves(self):  # ak_102_29za_line_moved ak_102_26q_grown
        lines = page("29za").splitlines()
        self.assertTrue(lines[35].startswith("snapshot kanaryası (test 16) Aşama 4'e taşınır"))  # 29za:36, as it was
        self.assertEqual((lines[36], len(lines)), ("", 57))
        self.assertEqual(len(page("26q").splitlines()), 80)


class RecordsTest(unittest.TestCase):
    def test_the_register_rows(self):
        # e739_open e739_recipe e740_open e741_open e741_recipe e742_open e742_mirror_unsaid e743_open
        # e743_score_fact_dropped
        for eid, words in (("E739", ("sahibin ipucu (bu kez kural esnetildi; 2026-11-23, Suderra sahip tarafı; panelsiz; "
                                     "E736 gibi işaretli): görev, reçete değil: hiçbir tasarım verilmez.",
                                     "`referee/gate/allowlist.py:32`", "hiçbir hakem ya da denetim gevşemez")),
                           ("E740", ("`referee/runner/kos.py:324-325`", "görev, reçete değil.")),
                           ("E741", ("81 `lesson` satırı", "tasarım Kurucu'nundur", "5 oturumdan sonra yanlışlanabilir")),
                           ("E742", ("Başlatıcının aynası (yalnız olgu): `mirror.py` yeni `context` bölümü",
                                     "başlatıcının başka hiçbir şeyi değişmez", "`test_mirror.ContextTest`")),
                           ("E743", ("seed-102 (Kurucu raporu)", "`referee/harness/score.py:427`, `:460`",
                                     "Gevşetme yok, sahip kararı yok.", "`29za`'nın 36 satırından hiçbiri yer "
                                     "değiştirmedi"))):
            row = register_row(eid)
            for w in words:
                self.assertIn(w, row, (eid, w))
            self.assertEqual(row.count("|"), 7, eid)
            self.assertRegex(row, r"\| kapandı \(tohum dönemi AK(; (test|ölçüm) Kurucu'nun)?\) \|$", eid)

    def test_this_entry_opens_with_its_first_task_and_answers_seed_102(self):
        # ak_first_task_not_first ak_order_changed ak_rework_demanded ak_102_line_twice ak_102_items_dropped
        # ak_changelog_unindexed ak_index_missing ak_answers_missing
        entry = flat(changelog().split("\n- 2.2 (2026-11-23, E739–E743", 1)[1])
        self.assertIn("**İlk iş** (`25` 10b). Teslimden itibaren önyükleme hakeminin hiçbir denetimi kırmızı olmaz",
                      entry[:300])
        for words in ("Kurucu'nun bugünkü işi sürer, sırası `CHANGELOG-14`'ünkidir; E739–E742 görevdir, kırmızı bir "
                      "görev değil, ve sayfaların zaten istediğinin ötesinde hiçbir yeniden yapım istemez.",
                      "Raporların teyidi `26l`'nin kuralı olarak kalır, bu listenin bir maddesi değildir.",
                      "Yalnız olgudur; başlatıcının başka hiçbir şeyi değişmez.", "Gevşetme yok."):
            self.assertIn(words, entry, words)
        items = [line.strip() for line in changelog().splitlines() if line.strip().startswith("- (")]
        self.assertEqual([i.split(")")[0] + ")" for i in items],
                         ["- (1)", "- (1, devamı)", "- (1, kopya)", "- (1, operatörün eki)", "- (2)", "- (3)"])
        self.assertEqual(sum(1 for line in changelog().splitlines() if line.strip().startswith(f"`{REPORT}` →")), 1)
        index = (ROOT / "spec" / "INDEX.md").read_text(encoding="utf-8")
        self.assertIn("| `tohum/CHANGELOG-20.md` | Değişiklik Günlüğü — Tohum, 2.2'nin On Dokuzuncu Kayıtları |", index)
        self.assertIn("| `tohum/00g-gorev-haritasi-sahibin-ipuclari-5.md` | Görev Haritası, Devam: Sahibin İpuçları V | "
                      "her oturumda, görev seçilirken (`00f`'nin devamı) |", index)
        log = (TOHUM / "CHANGELOG.md").read_text(encoding="utf-8").splitlines()
        self.assertTrue(log[6].startswith("- 2.2 (2026-11-23, E739–E743; tohum dönemi AK,"))  # the newest entry first
        self.assertTrue(log[6].endswith("`CHANGELOG-20.md`; başında **İlk iş**."))
        answers = json.loads((BOOT / "reports" / "answers.json").read_text(encoding="utf-8"))["answers"]
        self.assertEqual([(a["id"], a["kind"]) for a in answers if a["changelog"] == "CHANGELOG-20"],
                         [(REPORT, "answered")])

    def test_the_pages_fit(self):
        for p in TOHUM.glob("*.md"):
            self.assertLessEqual(len(p.read_text(encoding="utf-8").splitlines()), 80, p.name)
        for prefix in ("00g", "29za"):
            self.assertEqual([n for n, line in enumerate(page(prefix).splitlines(), 1) if len(line) > 120], [], prefix)


if __name__ == "__main__":
    unittest.main()
