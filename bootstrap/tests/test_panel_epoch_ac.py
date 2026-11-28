"""Seed epoch AC (2026-11-21): the report desk's answer to seed-088 (who writes each finding state, `26k`), loosening
L-088, P1 MF12's contracts T1 and T2, and the owner's hint on the first agent (`00e`, E692). Only `spec/tohum` reaches
the brain, so each binding sentence is on a `tohum` page. The trailing comment on a test names the mutants it kills
(`local/mutate.py`)."""

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


def register_row(eid: str) -> str:
    rows = (ROOT / "docs" / "eksik-kaydi.md").read_text(encoding="utf-8").splitlines()
    return next(line for line in rows if line.startswith(f"| {eid} |"))


def changelog() -> str:
    return (TOHUM / "CHANGELOG-12.md").read_text(encoding="utf-8")


class FindingStatesTest(unittest.TestCase):
    """seed-088: `26k`."""

    def test_the_writers_of_each_state(self):
        # fixed_by_sentinel reobserved_open_writes_a_row revert_leaves_fixed revert_writes_unresolved
        # not_open_decision_stops_cycle verified_written_in_stage_1 l088_unlabelled
        text = flat(page("26k"))
        for words in ("(bağımsız inceleme ekibi kararı (2026-11-21), seed-088)",
                      "Her bulgu satırını hakem yazar (`findings.write`); bir öneri durum taşımaz",
                      "**`fixed`.** Kapının bulgu için verdiği merge kararı yazar: merge satırıyla aynı devirde ve aynı "
                      "`brain/state` commit'inde. Anlamı \"kapı bir düzeltmeyi merge etti\"dir, \"düzeltme hayatta "
                      "kaldı\" değildir", "Son satırı `open`, `reopened` ya da `blocked` olan bulgunun yeniden gözlemi "
                      "satır yazmaz", "`fixed` (ya da `verified`) bulgunun yeniden gözlemi `reopened` yazar; bulgunun "
                      "üçüncü yeniden açılışını bir `blocked` satırı izler",
                      "Bir merge geri alınınca aynı devir o merge'ün bulgusu için `reopened` yazar; üçe sayılır, bir "
                      "başarısız merge en çok bir yeniden açılıştır", "Geri alma `unresolved.jsonl` satırı yazmaz "
                      "(nedeni defterin `revert` satırıdır). Bir prova ekmesinin geri alınması bulgu satırı yazmaz.",
                      "Bilinmeyen ya da açık olmayan bir bulguyu adlandıran karar o adayın reddidir (`finding_unknown`, "
                      "`finding_not_open`); bulgu için hiçbir şey yazılmaz.",
                      "**`verified` ve `withdrawn`** Aşama 1'de yazılmaz (operatör kararı, sahibin yetkisiyle "
                      "(2026-11-21))", "`withdrawn`'ın tetiği Aşama 4'ün oracle'ıdır (`asama-4/07`)",
                      "İkisi de `26`'nın kapalı kümesinde geçerli değerler olarak kalır ve okunur"):
            self.assertIn(words, text, words)
        self.assertIn("Durumların yazıcıları `26k`'dedir (seed-088)", flat(page("26j")))
        thirteen = (ROOT / "spec" / "asama-1" / "13d-bulgu-ve-kosu-semasi.md").read_text(encoding="utf-8")
        self.assertIn("`verified` ve `withdrawn` Aşama 1'de yazılmaz (`tohum/26k`)", thirteen)

    def test_mf12s_contracts_and_the_loosening(self):  # t1_after_the_merge t2_cycle_unusable l088_unnamed l088_off_page
        text = flat(page("26k"))
        for words in ("**P1 MF12'nin sözleşmeleri.** MF12 (`26j`) bunları karşılar",
                      "T1: `finding_unknown` ve `finding_not_open` D5 nedenleridir ve merge seçilmeden önce verilir. Bir "
                      "merge, kaydın reddettiği bir bulgunun üstüne asla düşmez.",
                      "T2: hiçbir adayın içeriği devri kullanılamaz kılmaz. Bir bulgu için iki karar sonraki adayı "
                      "reddeder, devri asla geçersiz kılmaz."):
            self.assertIn(words, text, words)
        self.assertIn("MF12'nin sözleşmeleri T1 ve T2 `26k`'dedir (seed-088)", flat(page("26j")))
        self.assertIn("`asama-1/13d:19` bunları Aşama 1 durumu sayar; bu sayfa onu gevşetir (L-088).", text)
        row = register_row("E691")
        self.assertIn("bağımsız inceleme ekibi kararı (2026-11-21", row)
        self.assertIn("**Gevşetme** L-088 (operatör kararı, sahibin yetkisiyle, 2026-11-21", row)


class FirstAgentHintTest(unittest.TestCase):
    """The owner's hint of 2026-11-21 (E692): the evidence, the ask and five binding guards; the design is the Founder's."""

    def test_00e_states_the_hint_and_its_guards(self):
        # agent_hint_unlabelled agent_lands_by_itself agent_run_unrecorded agent_unmeasured agent_never_retired
        # agent_outside_agents agent_design_prescribed agent_on_sonnet agent_new_kind agent_catch_unproven
        # agent_hints_confounded agent_evidence_overclaimed
        text = flat(page("00e"))
        for words in ("**Sahibin ipucu (bu kez kural esnetildi; 2026-11-21, E692; ipucu, reçete değil; korkuluklar "
                      "bağlayıcıdır). İlk ajan: denetlenen ve ölçülen.**",
                      "f1735, f1748 ve f1799 E667'yi sıradaki işler arasında adlandırır ve yapmaz; f1844 ve f1853 \"alt "
                      "ajan kullanılmadı\" der",
                      "Defterin oturum başlangıç satırları rakibin `refutation_reproduced` ile reddettiği 18 push "
                      "adlandırır (f32'den f1777'ye); son beşinden üçü bir sayfa sözünün kaçağıdır: f1595",
                      "ilk ajan, push'tan önce koşan bir uyum denetçisi olsun; inceleme yaptığı için modeli `opus`'tur "
                      "(E643: `opus` ajanları analiz, inceleme ve planlama içindir", "Tasarım (istem, kapsam, ne zaman "
                      "koştuğu) senindir.",
                      "Korkuluklar (sahibin koşulu; bağlayıcıdır, kaliteden ödün verilmez)",
                      "1. Ajan kendiliğinden hiçbir şey sokmaz. Her değişiklik yine senin incelemenden, tam prepush'tan, "
                      "önyükleme hakeminden ve rakipten değişmeden geçer. Ajan bir denetim ekler, hiçbirinin yerini almaz.",
                      "2. Her ajan koşusu bir `founder` defter satırıdır, türü `build` ya da `decision` (türler kapalı "
                      "kümedir, `26`; yeni tür uydurulmaz); `summary`'si ajan kimliğini, modeli ve çabayı (E644), tanım "
                      "sha256'sını, diff'in sha'sını, bulguları, token ve maliyeti, duvar süresini taşır.",
                      "3. Ölçülür: gerçek yakalama, ajanın bir bulgusudur ki onu düzeltmesinden önce kırmızı, sonra yeşil "
                      "olan bir testle doğruladın ve satıra yazdın; rakibin ya da hakemin doğrulaması da sayılır. Yanlış "
                      "alarm, nedeniyle reddettiğin bulgudur.",
                      "E692 ve E693 yalnız oturum başına değil, bulgu başına ayrı ölçülür (atıf), birbirini karıştırmaz",
                      "4. Yanlışlanabilir emeklilik: ajanlı 5 oturumdan sonra gerçek yakalama 0 ise ya da maliyeti "
                      "kazandırdığı dakikaları aşıyorsa",
                      "5. Ajanın tanımı `agents/` altındadır ve kökeni gövdesindedir (`09`, E675); kapsülün araç kuralları "
                      "geçerlidir"):
            self.assertIn(words, text, words)
        self.assertIn("Sahibin 2026-11-21'den sonraki ipuçları (E692'den başlayarak) `00e`'dedir.", flat(page("00d")))
        row = register_row("E692")
        self.assertIn("sahibin ipucu (bu kez kural esnetildi", row)
        self.assertIn("\"Kurucu kendisi bulur\" kuralını bir kez daha esnetmeyi seçti", row)


class SmartCheckHintTest(unittest.TestCase):
    """The owner's hint of 2026-11-21 (E693): scoped checks during a session, the full run once, the gate unchanged."""

    def test_00e_states_the_evidence_and_the_duty(self):
        # smart_hint_unlabelled smart_full_run_every_time smart_gate_weakened smart_unmeasured smart_never_widens
        text = flat(page("00e"))
        for words in ("**Sahibin ipucu (bu kez kural esnetildi; 2026-11-21, E693; ipucu, reçete değil). Akıllı "
                      "doğrulama, aynı güç.**", "bütün mutant tablolarını (`tests/mutate.py -j 4`) ve bütün unittest "
                      "keşiflerini oturum başına birkaç kez koşuyorsun", "20261121T211913Z oturumunda kapsayıcı %100 "
                      "CPU'da kaldı (operatörün ölçümü)", "%72–87'sinin kendi denetimlerini beklemekle geçtiğini ölçtü (E677)",
                      "Oturum içinde yalnız değişikliğin etkileyebileceğini koş: E689'un hızlı geçişi ve `04`'ün zaten "
                      "tanımladığı değişen satırların mutant seçimi",
                      "Bütün bildirimi ve bütün mutant tablolarını bir kez, push'tan önceki son prepush'ta koş",
                      "Önyükleme hakemi ve rakip her push'ta yine her şeyi, değişmeden koşar; kapının gücü düşmez",
                      "oturum başına CPU dakikası ve duvar süresi, önce ve sonra; kaçaklar",
                      "Kaçak görülürse kapsamı genişletirsin. Nasıl kurulacağı senindir."):
            self.assertIn(words, text, words)
        self.assertIn("mutant öldürme tabanı", flat(page("04")))  # the changed-line selection the hint points at
        row = register_row("E693")
        self.assertIn("sahibin ipucu (bu kez kural esnetildi", row)
        self.assertIn("\"Kurucu kendisi bulur\" kuralını bir kez daha esnetmeyi seçti", row)
        self.assertIn("E693 oturum içinde kapsamlı doğrulama, E689'un hızlı geçişiyle, tam koşu bir kez son prepush'ta",
                      flat(changelog()))


class FirstTaskTest(unittest.TestCase):
    def test_this_entry_opens_with_its_first_task(self):  # ac_first_task_not_first ac_t1_t2_unnamed ac_hint_is_a_duty ac_hints_wait_for_p1 ac_order_not_superseding
        entry = flat(changelog().split("\n- 2.2 (2026-11-21, E691–E693", 1)[1])
        self.assertIn("**İlk iş** (`25` 10b; Kurucu'nun dersi f1741). Teslimden itibaren önyükleme hakeminin hiçbir "
                      "denetimi kırmızı olmaz", entry[:400])
        first = entry.split("Yeni `26k`")[0]
        for words in ("bu dönem ne bir tablo, ne bir vektör, ne bir zorunlu politika yolu değiştirir",
                      "1. MF9, izin listesi ve `accept` yazıcısı (`26j`);",
                      "2. birinci maddeden hemen sonra, kırmızı görev değil, sahibin ipuçları (bu kez kural esnetildi; "
                      "`00e`): E693 oturum içinde kapsamlı doğrulama, E689'un hızlı geçişiyle, tam koşu bir kez son "
                      "prepush'ta; E692 ilk ajan olarak push'tan önce koşan bir uyum denetçisi",
                      "3. MF10, organ çıktısının tutulması; MF11",
                      "4. MF12, `yaz`'ın aday okuması (`26j`), sözleşmeleri T1 ve T2 ile (`26k`)"):
            self.assertIn(words, first, words)
        self.assertEqual(len(re.findall(r" [1-9]\. ", first)), 4)
        self.assertLess(first.index("1. MF9"), first.index("2. birinci maddeden"))  # the hints right after MF9
        self.assertLess(first.index("2. birinci maddeden"), first.index("3. MF10"))
        self.assertIn("Bu sıra `CHANGELOG-11`'in E689 ve E690 yerleşiminin yerini alır: E689'un hızlı geçişi artık E693'le "
                      "birlikte MF9'dan hemen sonradır.", first)
        self.assertEqual(register_row("E692").count("birinci maddeden (MF9) hemen sonra"), 1)
        self.assertEqual(register_row("E693").count("birinci maddeden (MF9) hemen sonra"), 1)
        self.assertTrue(any("`seed-088-finding-states-fixed-verified-withdrawn-have-no-named-writer` →" in line
                            for line in changelog().splitlines()))
        index = (ROOT / "spec" / "INDEX.md").read_text(encoding="utf-8")
        for name, title in (("26k-semalar-bulgu-durumlari.md", "Şemalar, Devam: Bulgu Durumlarının Yazıcıları"),
                            ("00e-gorev-haritasi-sahibin-ipuclari-3.md", "Görev Haritası, Devam: Sahibin İpuçları III"),
                            ("CHANGELOG-12.md", "Değişiklik Günlüğü — Tohum, 2.2'nin On Birinci Kayıtları")):
            self.assertIn(f"| `tohum/{name}` | {title} |", index)
        self.assertIn("`CHANGELOG-12.md`; başında **İlk iş**", flat((TOHUM / "CHANGELOG.md").read_text(encoding="utf-8")))
        for p in list(TOHUM.glob("*.md")) + list((ROOT / "spec" / "asama-1").glob("*.md")):
            self.assertLessEqual(len(p.read_text(encoding="utf-8").splitlines()), 80, p.name)
        for word in ("write_cycle.py", "write.py:", "Held", "26:41"):  # the desk's owner-only items stay out
            self.assertNotIn(word, page("26k") + changelog())


if __name__ == "__main__":
    unittest.main()
