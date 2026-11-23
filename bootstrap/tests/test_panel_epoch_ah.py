"""Seed epoch AH (2026-11-23, report desk): seed-100 (the form of a package's finding and its way into the registry) and
seed-101 (the run in the writer's findings file and the findings form of the two-file command). Only `spec/tohum` reaches
the brain, so each binding sentence is on a `tohum` page: new `26q`; `26m` "Puanlama" names the run's observation list
instead of the registry and points `rules_total` to `29za:9-22`; `26j` and `26k` point to `26q`. Every item of the two
reports has a line in `CHANGELOG-17`. The one loosening, L-AH1, is named on the page, in `26m`, in the register and in
`CHANGELOG-17`. The trailing comment on a test names the mutants it kills (`local/mutate.py`)."""

import json
import unittest
from pathlib import Path

BOOT = Path(__file__).resolve().parents[1]
ROOT = BOOT.parents[1]
TOHUM = ROOT / "spec" / "tohum"
REPORTS = ("seed-100-the-form-of-a-package-s-finding-and-its-way-into-the-registry-are-unstated",
           "seed-101-the-run-in-the-writer-s-findings-file-and-the-findings-form-of-the-two-file-command-are-unstated")


def page(prefix: str) -> str:
    found = sorted(TOHUM.glob(f"{prefix}-*.md"))
    assert len(found) == 1, (prefix, found)
    return found[0].read_text(encoding="utf-8")


def flat(text: str) -> str:
    return " ".join(text.split())


def section(prefix: str, start: str, end: str | None) -> str:
    text = flat(page(prefix))
    begin = text.index(flat(start))
    return text[begin:text.index(flat(end), begin)] if end else text[begin:]


def register_row(eid: str) -> str:
    rows = (ROOT / "docs" / "eksik-kaydi.md").read_text(encoding="utf-8").splitlines()
    return next(line for line in rows if line.startswith(f"| {eid} |"))


def changelog() -> str:
    return (TOHUM / "CHANGELOG-17.md").read_text(encoding="utf-8")


def items(report: str) -> list[str]:
    """The item lines `CHANGELOG-17` gives a report: the `  - ` lines under its `→` line (and the pages it names on the
    lines before the first item), up to the next report."""
    lines = changelog().splitlines()
    start = next(i for i, line in enumerate(lines) if line.strip().startswith(f"`{report}` →"))
    out = []
    for line in lines[start + 1:]:
        if line.startswith("  - "):
            out.append(line[4:])
        elif line.startswith("    ") and out:
            out[-1] += " " + line.strip()
        elif not out and line.startswith("  `26"):
            continue
        else:
            break
    return out


PACKAGE = ("**Paketin bulgusu ve kayda yolu**", "**Avcı koşusu ve gözlem listesi**")
RUN = ("**Avcı koşusu ve gözlem listesi**", None)


class PackageFindingPageTest(unittest.TestCase):
    """`26q` "Paketin bulgusu ve kayda yolu" (seed-100, E730)."""

    def test_the_finding_and_its_fingerprint(self):
        # ah_finding_carries_id ah_extra_key_allowed ah_package_fingerprint_read ah_fingerprint_other_tree
        text = section("26q", *PACKAGE)
        for words in ("Paketin `finding`'i düzeltmenin ait olduğu bulgudur, önerilen biçimde: `findings.write`'ın 5. "
                      "kuralının nesnesi, yani `26`'nın bulgu alanları, `finding_id`, `fingerprint`, `state`, `trust` ve "
                      "`proposed_by` olmadan",
                      "Sıkılaştırma: bu beş alandan birini ya da başka bir anahtarı taşıyan `finding` paketi "
                      "`package_invalid` yapar",
                      "D5'in kayda sorduğu parmak izini hakem yapar: `findings.write`'ın tek fonksiyonu (`26m:59-61`), "
                      "devrin ağacında, adayın yeniden koşusunun karşılaştırıldığı ağaçta (`26p:64-66`).",
                      "Paketin parmak izi üstüne söylediği hiçbir şey okunmaz."):
            self.assertIn(words, text, words)

    def test_the_line_is_the_primary_reference_in_the_file(self):
        # ah_line_first_in_file ah_line_outside_file ah_gate_missing_value
        text = section("26q", *PACKAGE)
        for words in ("o satır birincil başvurununkidir (`evidence_refs[0]`, `26h:59`) ve o başvuru bulgunun "
                      "`file`'ındadır",
                      "K0–K2 isabeti (`26m:51-54`) aynı başvuruyu okur.",
                      "Birincil başvurusu başka bir yolda olan bulgunun satırı yoktur (`no_line`);",
                      "kapının bir değeri yoksa kapı adayı reddeder (`candidate_unusable`).",
                      "fark: kurulan, `file`'daki ilk başvuruyu okur."):
            self.assertIn(words, text, words)

    def test_t1_reads_the_registry_the_cycle_started_from(self):
        # ah_t1_after_proposals ah_same_cycle_fix ah_unknown_worked_around ah_t1_cost_duty
        text = section("26q", *PACKAGE)
        for words in ("T1 (`26k:34-35`) devrin başladığı kaydı okur: `yaz`'ın `brain/state`'ten çektiği "
                      "`findings.jsonl`'u, bu devrin önerileri uygulanmış hâlini değil.",
                      "Sıkılaştırma: hiçbir aday kendi devrinde önerilen bir bulguyu düzeltemez.",
                      "Organın önerilerinin dosyası `26p:28-30`'dadır",
                      "Bu tasarımdır, etrafından dolaşılmaz:"):
            self.assertIn(words, text, words)
        self.assertNotIn("bedelini", text)  # ah_t1_cost_duty: the lag is a fact, never a measuring duty

    def test_the_reason_names(self):
        # ah_reason_standing ah_reason_writes_unresolved ah_reasons_merged ah_decided_order_open ah_id_twice_first_wins
        # ah_registry_unusable_writes ah_package_extra_top_key ah_definition_sha_any
        text = section("26q", *PACKAGE)
        for words in ("yeniden koşunun verdiği paketin biçim denetimi: paket tam olarak `26a:66`'nın dört anahtarıdır, "
                      "fazla bir üst anahtar (ör. `fingerprint`) da `package_invalid`'dir; `organ_ids` "
                      "`gate.allowlist`'in okuduğu biçimdedir, `definition_sha256` 64 küçük onaltılık dizgilerdir, "
                      "`finding` (1)'in biçimidir.",
                      "hiçbiri duran neden değildir (`26j:43-46`), `cause`'u `unknown`'dır (`26:41-44`) ve "
                      "`unresolved` satırı yazmaz.",
                      "`koş`'un `package_unusable`'ından (`26p:47-48`) ayrı aşamadır, iki ad da durur.",
                      "`finding_decided`: bir bulgunun sonraki adayı; sıra aday kimliklerinin kod noktası sırasıdır.",
                      "`no_line`: bulgunun devrin ağacında parmak izi yok.",
                      "bir kimlik bir karar satırıdır (`c:<id>`): ikisi de reddedilir, hiçbiri yargılanmaz",
                      "`registry_unusable`: `findings.jsonl` geçerli bir zincir değil; o dosya D6'yı da durdurur, bu ad "
                      "hiçbir devri yazdırmaz."):
            self.assertIn(words, text, words)

    def test_the_closed_gate_and_the_genesis_cycle(self):
        # ah_closed_gate_counts ah_mixed_reject_not_decision ah_genesis_reads
        text = section("26q", *PACKAGE)
        for words in ("Kapalı kapının reddi (`26j:43-46`) bulgu üstüne bir karar değildir, T2'nin iki kararının ilki "
                      "sayılmaz",
                      "Duran bir nedenin yanında başka bir nedeni olan ret karardır.",
                      "Genesis devri çalışma-zamanı adayı okumaz (`26j:33-34`, `26a:66-68`)",
                      "Vektör: MF10–MF12'nin grubu yoktur (`26p:67`); test 58 bağlar."):
            self.assertIn(words, text, words)


class RunAndDenominatorPageTest(unittest.TestCase):
    """`26q` "Avcı koşusu ve gözlem listesi" (seed-101, E731, E732) and the corrected `26m` "Puanlama"."""

    def test_a_run_and_its_observation_list(self):
        # ah_run_is_file ah_two_runs_one_list ah_reobservation_dropped ah_list_fingerprint_agent ah_foreign_row_skipped
        # ah_registry_is_run ah_l_ah1_26q_unqualified
        text = section("26q", *RUN)
        for words in ("Koşu, bir avcı organının bir snapshot üzerindeki bir koşusudur.",
                      "aynı snapshot'taki iki koşu iki ayrı listedir.",
                      "Koşunun gözlem listesini hakem kodu o koşu için yazar: koşunun her gözlemi, organın sırasıyla, "
                      "yeniden gözlemler ve hedefin kaydında zaten olan bulgular dahil (`asama-1/13e:24`)",
                      "her parmak izini `findings.write`'ın tek fonksiyonu o snapshot'ın ağacında yapar.",
                      "Snapshot'ı koşununki olmayan bir satır taşıyan liste kullanılamaz; satır sessizce atlanmaz.",
                      "Ne kendisi ne bir penceresi (bütün dosya ya da bir snapshot'ın satırları) bir koşudur; "
                      "puanlayıcının girdisi değildir.",
                      "Gevşetme değildir: puanlanan her parmak izini hâlâ yalnız hakem kodu yapar (L-AH1 dışında, (8))."):
            self.assertIn(words, text, words)

    def test_the_deferral_planted_runs_no_run_and_equal_lines(self):
        # ah_list_place_now ah_planted_in_registry ah_no_run_fail ah_equal_line_allowed ah_registry_other_tree
        text = section("26q", *RUN)
        for words in ("Listenin yeri, adı ve satır biçimi ertelendi: Aşama 1 MF1'i (`lint.discover`, ilk avcı) "
                      "getiren döneme (`26p:28-30`).",
                      "gözlemlerinin hiçbiri `findings.jsonl`'a ya da `unresolved.jsonl`'a yazılmaz",
                      "Kayda yalnız hedefin kendi ağacındaki bir koşunun gözlemleri, yazıcıdan geçerek girer.",
                      "hüküm ne `FAIL` ne `PASS`'tir (Aşama 1 MF1'e kadar).", "Sıkılaştırma: uydurulmuş kaçırma yoktur.",
                      "aynı dosyadaki başka bir ihlalle aynı parmak izini taşıyan vakayı reddeder"):
            self.assertIn(words, text, words)

    def test_the_two_file_command_and_the_loosening_l_ah1(self):
        # ah_two_file_writes ah_l_ah1_unlabelled ah_l_ah1_live ah_match_never_red
        text = section("26q", *RUN)
        for words in ("İki dosyalı komut (`29a:73-74`), kurulduğu gibi:",
                      "rapor ve hüküm yoktur, hiçbir şey yazmaz. Onu hiçbir iş koşmaz; hiçbir defter satırı, kapı ya da "
                      "hüküm onu okumaz.",
                      "**Gevşetme L-AH1** (kapsamlı; sahibe bildirilir): bu komut parmak izlerini verildiği gibi alır",
                      "kuralının istisnası yalnız bu vektör komutudur; canlı puanlama (dört dosyalı biçim, rapor ve "
                      "hüküm) hakemin yaptığı parmak izini tutar.",
                      "(`fp-f1` hash değildir; boş olmayan bir \"aynı bulgu\" etiketidir)",
                      "Orada kırmızı olabilir."):
            self.assertIn(words, text, words)

    def test_the_denominator(self):
        # ah_denominator_library ah_dropped_rule_smaller ah_outside_case_unscored ah_outside_adds_denominator
        # ah_no_vector_pass
        text = section("26q", *RUN)
        for words in ("Payda: `rules_total` hedefin `census` vektörünün kural kümesidir (`29za:9-22`;",
                      "ne kütüphanenin kuralları ne koşunun vakaları", "`26e:72-73` aynı kümeyi söyler.",
                      "Kütüphanenin üretemediği vektör kuralı paydada kalır, kırmızı nedendir (`29za:12-13`).",
                      "Kümenin dışındaki bir kuralın vakası `rules_total`'a ve `rules_covered`'a bir şey eklemez, yine "
                      "de vakadır: `n`'de, `recall`'da ve kaçırmalarda sayılır, kaçırması `FAIL`'dır",
                      "Vektörü olmayan hedefin (bugün kopya, `29za:19-22`) sayımı yoktur, hükmü asla `PASS` değildir."):
            self.assertIn(words, text, words)

    def test_26m_names_the_list_the_vector_and_l_ah1(self):
        # ah_26m_registry_read ah_26m_rules_total_library ah_26m_l_ah1_unnamed ah_26m_unpointed
        text = flat(page("26m"))
        self.assertIn("onu koşunun gözlem listesinden (`26q`; `findings.jsonl` değil) yazıldığı gibi okur", text)
        self.assertNotIn("hakemin yazıcısının dosyasından", text)
        self.assertIn("Sıkılaştırma; istisnası L-AH1.", text)
        self.assertIn("Bir koşuda (`26q`: bir avcı koşusu) birden çok görülen parmak izi tek bulgudur", text)
        self.assertIn("`rules_total`'ın (`29za:9-22`: hedefin `census` vektörünün kural kümesi, `26q`)", text)
        self.assertIn("Koşunun tanımı, gözlem listesi, payda ve iki dosyalı komutun gevşetmesi L-AH1 `26q`'dadır "
                      "(seed-101).", text)
        self.assertIn("(`29za:9-22`:", page("26m").splitlines()[66])

    def test_26e_and_26n_carry_no_second_reading(self):  # ah_26e_rules_total_library ah_l_ah1_26n_unqualified
        text = flat(page("26e"))
        self.assertIn("`rules_total` hedefin `census` vektörünün kural kümesidir (`29za:9-22`, `26q`)", text)
        self.assertNotIn("vaka üretilebilen kuralların sayısıdır", text)
        self.assertEqual(len(page("26e").splitlines()), 80)
        self.assertIn("bugün puanlanan her parmak izini hakemin kendi yazıcısı yapar (L-AH1 dışında, `26q`).",
                      flat(page("26n")))

    def test_26j_and_26k_point_to_26q(self):  # ah_26j_unpointed ah_26k_unpointed
        self.assertIn("MF12'nin sözleşmeleri T1 ve T2 `26k`'dedir (seed-088). Paketin bulgusu ve nedenleri `26q`'dadır "
                      "(seed-100).", flat(page("26j")))
        self.assertIn("T1'in okuduğu kayıt, parmak izini yapan ve nedenlerin adları `26q`'dadır (seed-100).",
                      flat(page("26k")))


class RecordsTest(unittest.TestCase):
    """CHANGELOG-17 (its first task, L-AH1 and a line for every item), the register, INDEX and the answers file."""

    def test_the_first_task_keeps_the_order_and_places_the_answers(self):
        # ah_first_task_not_first ah_order_changed ah_101_after_exit ah_l_ah1_not_in_changelog ah_changelog_26e_unsaid
        text = flat(changelog())
        self.assertIn("**İlk iş** (`25` 10b).", text)
        self.assertIn("Kurucu'nun bugünkü işi sürer, sırası `CHANGELOG-14`'ünkidir.", text)
        self.assertIn("P1'in çıkış isteğinden önce kurulmuş `harness.score` seed-101'in yanıtına uyar", text)
        self.assertIn("Raporların teyidi `26l`'nin kuralı olarak kalır, bu listenin bir maddesi değildir.", text)
        self.assertIn("**Gevşetme L-AH1** (kapsamlı; sahibe bildirilir; `26q:64-70`): iki dosyalı vektör komutu "
                      "(`29a:73-74`) parmak izlerini verildiği gibi alır; yalnız o komut; canlı puanlama hakemin yaptığı "
                      "parmak izini tutar. Başka gevşetme yok.", text)
        self.assertIn("`26e:72-73` yerinde düzeltildi: `rules_total` hedefin `census` vektörünün kural kümesidir", text)
        self.assertIn("listeyi kullanılamaz kılar (`26q:51-52`; masanın kararı: Kurucu'nun süzgeci bir ret olarak okunur",
                      text)

    def test_every_item_of_each_report_has_its_line(self):
        # ah_item_100_dropped ah_item_101_dropped ah_item_101_deferral_unnamed ah_item_unmarked
        expected = {REPORTS[0]: 16, REPORTS[1]: 15}
        for report, count in expected.items():
            with self.subTest(report=report):
                lines = items(report)
                self.assertEqual(len(lines), count, lines)
                for line in lines:
                    self.assertRegex(line, r": (yanıtlandı|ertelendi|reddedildi)", line)
        labels = [line.split(" ", 1)[0] for line in items(REPORTS[0])[:11]]
        self.assertEqual(labels, ["(1)", "(2)", "(3)", "(3,", "(3,", "(4)", "(4)", "(4)", "(4)", "(5)", "(6)"])
        labels = [line.split(" ", 1)[0] for line in items(REPORTS[1])[:7]]
        self.assertEqual(labels, ["(1)", "(1,", "(2)", "(3)", "(3,", "(4)", "(4,"])
        self.assertIn("ertelendi: Aşama 1 MF1'i (`lint.discover`) getiren döneme", items(REPORTS[1])[1])
        self.assertIn("gevşetme L-AH1, yalnız o komut", items(REPORTS[1])[3])
        self.assertEqual(sum(line.startswith("güncelleme") for line in items(REPORTS[1])), 4)

    def test_the_register_rows(self):  # ah_rows_open ah_e732_unscoped ah_e731_cause_dropped ah_e731_foreign_row
        for eid in ("E730", "E731", "E732"):
            with self.subTest(eid=eid):
                self.assertTrue(register_row(eid).endswith("|"))
                self.assertIn("kapandı (tohum dönemi AH", register_row(eid))
        self.assertIn("Gevşetme L-AH1", register_row("E732"))
        self.assertIn("kapsamı yalnız o komuttur", register_row("E732"))
        self.assertIn("gevşetme L-AH1 (E732)", register_row("E731"))
        self.assertIn("Neden: AF'nin `26m`'si \"bir koşuda\" puanladı ama koşuyu tanımlamadı", register_row("E731"))
        self.assertIn("Gevşetme yok.", register_row("E730"))
        self.assertIn("başka snapshot'ın satırı listeyi kullanılamaz kılar, sessizce atlanmaz", register_row("E731"))
        self.assertIn("paket de tam olarak `26a:66`'nın dört anahtarıdır", register_row("E730"))

    def test_the_indexes_and_the_answers(self):  # ah_index_missing ah_changelog_unindexed ah_answers_missing
        index = (ROOT / "spec" / "INDEX.md").read_text(encoding="utf-8")
        for name in ("tohum/26q-semalar-paket-bulgusu-ve-kosu.md", "tohum/CHANGELOG-17.md"):
            self.assertIn(f"| `{name}` |", index)
        self.assertIn("`CHANGELOG-17.md`; başında **İlk iş**.", (TOHUM / "CHANGELOG.md").read_text(encoding="utf-8"))
        answers = json.loads((BOOT / "reports" / "answers.json").read_text(encoding="utf-8"))["answers"]
        mine = [(a["id"], a["kind"]) for a in answers if a["changelog"] == "CHANGELOG-17"]
        self.assertEqual(mine, [(r, "answered") for r in REPORTS])
        for report in REPORTS:
            self.assertEqual(sum(1 for line in changelog().splitlines() if line.strip().startswith(f"`{report}` →")), 1)

    def test_the_pages_fit(self):
        for prefix in ("26q", "26m", "26j", "26k", "26e", "26n"):
            self.assertLessEqual(len(page(prefix).splitlines()), 80, prefix)
        self.assertLessEqual(len(changelog().splitlines()), 80)


if __name__ == "__main__":
    unittest.main()
