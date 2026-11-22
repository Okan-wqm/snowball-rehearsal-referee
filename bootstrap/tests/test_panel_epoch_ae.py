"""Seed epoch AE (2026-11-22): the owner's hint E697 (`00e`), a duty and not a recipe: the Founder makes its agents
under rules it writes and keeps in the brain, measures every run, finds the weak points itself and closes each class
with an architectural change to the rules; E692's guards 1-3 hold for every agent run. Only `spec/tohum` reaches the
brain, so each binding sentence is on a `tohum` page. The trailing comment on a test names the mutants it kills
(`local/mutate.py`)."""

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


def register_row(eid: str) -> str:
    rows = (ROOT / "docs" / "eksik-kaydi.md").read_text(encoding="utf-8").splitlines()
    return next(line for line in rows if line.startswith(f"| {eid} |"))


def changelog() -> str:
    return (TOHUM / "CHANGELOG-14.md").read_text(encoding="utf-8")


def hint() -> str:
    """E697's paragraph of `00e`, from its label to the end of the page."""
    text = flat(page("00e"))
    return text[text.index("**Sahibin ipucu (bu kez kural esnetildi; 2026-11-22, E697"):]


class AgentRulesHintTest(unittest.TestCase):
    """The owner's hint of 2026-11-22 (E697): the evidence, the duty and three binding guards; the design is the
    Founder's."""

    def test_00e_states_the_evidence(self):
        # rules_evidence_overclaimed rules_evidence_unrecorded rules_governing_lesson_unnamed rules_f1906_unnamed
        # rules_prompts_praised
        text = hint()
        for words in ("20261122T091521Z oturumunda ilk ajanlarını koştun: altı salt-okur `opus` ajanı (\"Judge report "
                      "answers A-F\"), yanıtlanan 16 raporu `26l`'ye göre kapatmak için (sonuç a74914f: 9 `confirmed`, 7 "
                      "`superseded`, 8 yeni rapor). Dilimleri ayrıktı: tek ortak istem, ajan başına rapor kimlikleri.",
                      "f1906 (7) altısını tek bir `decision` maddesinde yazar (general-purpose ajan, `opus`, çaba "
                      "ayarlanmamış, istemin sha256'sı, toplam 314994 token, her biri 72–132 s, maliyet gösterilmedi, üç "
                      "hükmü değiştirildi).",
                      "Koşu başına satır yok, maliyet yok; istemin gövdesi beyinde değil (yalnız kapsülün `/tmp`'sindeydi, "
                      "oturumla gitti); istemde ders yok; `agents/` altında tanım yok (`09`, E675).",
                      "E692'nin korkulukları \"ilk ajan\"ı adlandırır; bu ajanları yöneten tek şey f1909'un (2) temsilci "
                      "istemleri üzerine dersidir."):
            self.assertIn(words, text, words)
        for wrong in ("istemleri sıkıydı", "yalnız sonucu yazar", "hiçbir şey yönetmez"):  # the review of PR #34
            self.assertNotIn(wrong, text, wrong)

    def test_00e_states_the_duty_not_a_recipe(self):
        # rules_hint_unlabelled rules_design_prescribed rules_outside_the_brain rules_knowledge_dropped
        # rules_unmeasured_runs rules_never_revised rules_patch_per_case rules_weak_points_handed rules_not_falsifiable
        # rules_refuted_kept rules_lessons_verbatim
        text = hint()
        for words in ("**Sahibin ipucu (bu kez kural esnetildi; 2026-11-22, E697; görev, reçete değil; korkuluklar "
                      "bağlayıcıdır). Ajanlar senin yazdığın, ölçtüğün ve geliştirdiğin kurallarla.**",
                      "Görev (tasarım senindir): ajanlar, senin yazıp beyinde tuttuğun kurallarla kurulur:",
                      "bir ajana ne verildiği (görev, kapsam ve beynin tuttuğu bilgi: dersler, hafıza), çıktısının nasıl "
                      "denetlendiği, her koşunun başarımının nasıl ölçüldüğü, bir ajanın ya da bir kuralın ne zaman "
                      "yeniden tasarlandığı ya da emekli edildiği.",
                      "Ajanlarının zaaflarını ölçülen başarımlarından kendin bulursun ve her sınıfı vaka başına bir yamayla "
                      "değil, kurallarda mimari bir değişiklikle kapatırsın.",
                      "Kurallar yanlışlanabilir kayıtlardır (`00d`'nin sahip ilkesi, 2026-11-06): her kural ne beklediğini "
                      "söyler ve koşulara karşı yeniden sınanır; koşuların çürüttüğü kural yeniden yazılır."):
            self.assertIn(words, text, words)
        self.assertIn("Amaç: sahip ilkesi (2026-11-06) her dersin yeniden sınanan, yanlışlanabilir bir kayıt olmasıdır.",
                      flat(page("00d")))  # the principle the rules point at
        for recipe in ("kelimesi kelimesine", "satır kimlikleri", "istemine koy"):  # the duty hands over no design
            self.assertNotIn(recipe, text, recipe)

    def test_00e_states_the_guards(self):
        # rules_guards_first_agent_only rules_agent_lands_by_itself rules_run_unrecorded rules_new_kind
        # rules_catch_unproven rules_gate_changed rules_never_redesigned rules_diff_sha_dropped rules_guard5_unsaid
        text = hint()
        for words in ("Korkuluklar (sahibin koşulu; bağlayıcıdır):",
                      "1. E692'nin 1–3. korkulukları yalnız ilk ajana değil, her ajan koşusuna uygulanır: ajan yalnız bir "
                      "denetim ekler; her koşu bir `build` ya da `decision` satırıdır (kapalı küme, yeni tür yok), ajan "
                      "kimliği, model, çaba, tanım sha256'sı, diff'in sha'sı (koşu bir diff okuyorsa), token, maliyet, "
                      "duvar süresi, bulgular ve hangilerinin kullanıldığıyla; gerçek yakalama E692'nin dediği gibi "
                      "kanıtlanır.",
                      "E692'nin 5. korkuluğu ilk ajanın kalır; öteki ajanların tanımının nerede durduğu senin kuralındır "
                      "(`09`).",
                      "2. Önyükleme hakemi, rakip ve tam prepush değişmeden kalır.",
                      "3. Yanlışlanabilir: kurallarla geçen 5 oturumdan sonra ajan koşularında ölçülen bir iyileşme (gerçek "
                      "yakalama, yeniden iş, işe yarar bulgu başına maliyet) görünmezse, bunu kaydeder ve yeniden "
                      "tasarlarsın."):
            self.assertIn(words, text, words)
        raw = page("00e")
        raw = raw[raw.index("**Sahibin ipucu (bu kez kural esnetildi; 2026-11-22, E697"):]
        self.assertEqual(len(re.findall(r"(?m)^  [1-9]\. ", raw)), 3)  # three guards, each a list item
        self.assertIn("Sahibin 2026-11-21'den sonraki ipuçları (E692'den başlayarak) `00e`'dedir.", flat(page("00d")))


class RecordsTest(unittest.TestCase):
    def test_the_register_row(self):  # e697_unlabelled e697_recipe e697_open e697_fact_old
        row = register_row("E697")
        for words in ("f1906 (7) altısını tek bir `decision` maddesinde yazar (general-purpose ajan, `opus`, çaba "
                      "ayarlanmamış, istemin sha256'sı, toplam 314994 token, her biri 72–132 s, maliyet gösterilmedi, üç "
                      "hükmü değiştirildi)", "bu ajanları yöneten tek şey f1909'un (2) temsilci istemleri üzerine dersidir",
                      "diff'in sha'sı (koşu bir diff okuyorsa)", "E692'nin 5. korkuluğu ilk ajanın kalır","sahibin ipucu (bu kez kural esnetildi; 2026-11-22, Suderra sahip tarafı; panelsiz; E692 ve E693 "
                      "gibi işaretli)", "\"Kurucu kendisi bulur\" kuralını bir kez daha esnetmeyi seçti",
                      "Görev, reçete değil; hiçbir tasarım verilmez.",
                      "(1) E692'nin 1–3. korkulukları her ajan koşusuna uygulanır",
                      "(2) önyükleme hakemi, rakip ve tam prepush değişmez",
                      "(3) kurallarla geçen 5 oturumdan sonra ajan koşularında ölçülen iyileşme"):
            self.assertIn(words, row, words)
        self.assertEqual(row.count("|"), 7)
        self.assertTrue(row.endswith("| kapandı (tohum dönemi AE; ölçüm Kurucu'nun) |"), row[-80:])

    def test_this_entry_opens_with_its_first_task_in_the_same_order(self):
        # ae_first_task_not_first ae_hints_before_mf9 ae_hint_is_a_duty ae_e697_not_applied ae_order_changed
        # ae_changelog_unindexed ae_index_missing ae_confirmations_a_task
        entry = flat(changelog().split("\n- 2.2 (2026-11-22, E697", 1)[1])
        self.assertIn("**İlk iş** (`25` 10b; Kurucu'nun dersi f1741). Teslimden itibaren önyükleme hakeminin hiçbir "
                      "denetimi kırmızı olmaz", entry[:400])
        first = entry.split("`00e`'ye sahibin ipucu")[0]
        for words in ("bu dönem ne bir tablo, ne bir vektör, ne bir zorunlu politika yolu, ne hakemin kodu değiştirir",
                      "İlk iş `CHANGELOG-13`'ün sırasıdır, değişmeden;",
                      "1. MF9, izin listesi ve `accept` yazıcısı (`26j`);",
                      "2. birinci maddeden hemen sonra, kırmızı görev değil, sahibin ipuçları (bu kez kural esnetildi; "
                      "`00e`): E693 ve E692, E697 uygulanarak: E692'nin ajanı da her ajan gibi Kurucu'nun yazdığı "
                      "kurallarla kurulur ve ölçülür;",
                      "3. MF10, MF11 ve MF12 (`26j`), MF12 sözleşmeleri T1 ve T2 ile (`26k`).",
                      "Raporların teyidi `26l`'nin kuralı olarak kalır, bu listenin bir maddesi değildir."):
            self.assertIn(words, first, words)
        self.assertEqual(len(re.findall(r" [1-9]\. ", first)), 3)
        self.assertLess(first.index("1. MF9"), first.index("2. birinci maddeden"))
        self.assertLess(first.index("2. birinci maddeden"), first.index("3. MF10"))
        self.assertLess(first.index("E693 ve E692"), first.index("E697 uygulanarak"))
        self.assertIn("Yanıtlanan rapor yok.", entry)
        index = (ROOT / "spec" / "INDEX.md").read_text(encoding="utf-8")
        self.assertIn("| `tohum/CHANGELOG-14.md` | Değişiklik Günlüğü — Tohum, 2.2'nin On Üçüncü Kayıtları |", index)
        log = flat((TOHUM / "CHANGELOG.md").read_text(encoding="utf-8"))
        self.assertIn("2.2 (2026-11-22, E697; tohum dönemi AE, sahibin ipucu: ajanlar Kurucu'nun kurallarıyla, `00e`): "
                      "`CHANGELOG-14.md`; başında **İlk iş**.", log)
        self.assertIn("E606–E611; Kurucu raporları, olgu, sahip kararı): `seed-061`, `seed-062`, `seed-063`: "
                      "`CHANGELOG-7.md`; yeni `26g`", log)  # the two lines merged for the 80-line cap
        for p in TOHUM.glob("*.md"):
            self.assertLessEqual(len(p.read_text(encoding="utf-8").splitlines()), 80, p.name)


if __name__ == "__main__":
    unittest.main()
