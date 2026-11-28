"""Seed epoch AB (2026-11-21): the report desk's answers to seed-086 (findings.write), seed-087 (gate.allowlist) and
seed-085's open items, the operator's table correction that gives P1 the referee side of the run-time candidate path
(MF10-MF12, owner-approved), the `root_files` vector and the first-task list of `CHANGELOG-11`. Only `spec/tohum`
reaches the brain, so each binding sentence is on a `tohum` page; the seed's copies of `asama-1/13` and `06` are
aligned. The trailing comment on a test names the mutants it kills (`local/mutate.py`)."""

import no_real_delays  # noqa: F401  (first: no test waits on a real delay, E751)
import hashlib
import json
import re
import unittest
from pathlib import Path

from snowball_bootstrap import stages

BOOT = Path(__file__).resolve().parents[1]
ROOT = BOOT.parents[1]
TOHUM = ROOT / "spec" / "tohum"


def page(prefix: str) -> str:
    found = sorted(TOHUM.glob(f"{prefix}-*.md"))
    assert len(found) == 1, (prefix, found)
    return found[0].read_text(encoding="utf-8")


def stage1(name: str) -> str:
    return next((ROOT / "spec" / "asama-1").glob(f"{name}-*.md")).read_text(encoding="utf-8")


def flat(text: str) -> str:
    return " ".join(text.split())


def register_row(eid: str) -> str:
    rows = (ROOT / "docs" / "eksik-kaydi.md").read_text(encoding="utf-8").splitlines()
    return next(line for line in rows if line.startswith(f"| {eid} |"))


def changelog() -> str:
    return (TOHUM / "CHANGELOG-11.md").read_text(encoding="utf-8")


class FindingsWriterTest(unittest.TestCase):
    """seed-086: `26j` "Bulgu yazıcısı, MF8"."""

    def test_root_adopted_shapes_and_decisions(self):
        # root_key_for_empty_file unresolved_snapshot_is_the_findings new_base_counts_as_reopened twins_split
        # unknown_finding_stops_cycle proposed_by_from_the_list mf8_done_without_wiring
        text = flat(page("26j"))
        for words in ("**Bulgu yazıcısı, MF8** (bağımsız inceleme ekibi kararı (2026-11-21), seed-086)",
                      "`tips`'e satırı olan her zincirli durum dosyası için bir anahtar eklenir: anahtar dosyanın adıdır "
                      "(`findings.jsonl`, `unresolved.jsonl`), değeri son satırının saklı `row_hash`'idir",
                      "Olmayan ya da satırsız dosya anahtar eklemez: `29j`'nin vektörleri ve bugünkü her kök değişmez",
                      "Vektörü MF8'in `root_files` grubudur (`29zb`)",
                      "`unresolved.jsonl` satırı `{finding_id, fingerprint, cause, reasons, snapshot_id}`",
                      "`normalize` her Unicode boşluk dizisini tek boşluk yapar ve uçları kırpar, büyük-küçük harf ve "
                      "noktalama kalır", "`finding_id` `f-` ve parmak izidir",
                      "sembolsüz parmak izi her zaman dosyayı kullanır",
                      "üç `reopened` bulgunun bütün ömrü üzerinden sayılır; Aşama 1'de `blocked` son durumdur",
                      "`unresolved` satırının `snapshot_id`'si kararın verildiği tabandır",
                      "başka bir tabanda gözlenince bir `open` satırıyla yeniden açılır (`reopened` sayılmaz); aynı "
                      "tabanda hiçbir şey yazılmaz", "Bir dosyanın eşit iki satırı aynı kuralı çiğniyorsa tek bulgudur",
                      "Bilinmeyen bir bulguyu adlandıran karar o adayın reddidir, devrin değil",
                      "Önerinin kabı organın çıktı listesidir: koşu sonuçlarında (`results`) tutulur, `yaz` onu "
                      "hash'iyle okur", "`proposed_by` hakemin o çağrıya dair kendi kaydındaki organ kimliğidir, "
                      "listenin bir alanı değildir", "MF8, `yaz`'a bağlandığında ve her canlı devirde boş girdiyle "
                      "koştuğunda biter; ilk gerçek girdi Aşama 1 MF1'dir"):
            self.assertIn(words, text, words)

    def test_the_root_files_vector_is_computed_and_mf8s(self):  # root_files_group_dropped root_files_expect_moved
        seed = json.loads((BOOT / "vectors" / "vectors.json").read_text(encoding="utf-8"))
        group = seed["root_files"]
        self.assertEqual((group["owner"], group["runner"], group["interface"]),
                         ("P1", "data", "spec/tohum/29zb-vektor-arayuzleri-p1-durum-dosyalari.md"))
        self.assertEqual(stages.load(1).feature(8).groups, ("root_files",))
        parts = next(c for c in seed["root"]["cases"] if c["id"] == "root.part_tips")["expect"]

        def last_hash(rel):
            lines = (BOOT / "vectors" / rel).read_text(encoding="utf-8").splitlines()
            return json.loads(lines[-1])["row_hash"] if lines else None

        def root(tips):  # 13's root: sha256 of the RFC 8785 bytes, here ASCII keys sorted and compact
            return hashlib.sha256(json.dumps(tips, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        keyed, empty = group["cases"]
        self.assertEqual(keyed["id"], "root_files.state_files_keyed")
        tips = dict(parts["tips"], **{"findings.jsonl": last_hash("root_files/two/findings.jsonl"),
                                      "unresolved.jsonl": last_hash("root_files/two/unresolved.jsonl")})
        self.assertEqual(keyed["expect"], {"root": root(tips), "tips": tips})
        self.assertEqual(empty["id"], "root_files.empty_file_adds_nothing")
        self.assertIsNone(last_hash("root_files/empty/findings.jsonl"))
        self.assertEqual(empty["expect"], parts)  # a file with no row: the ledger's root, unchanged
        short = dict(parts["tips"], **{"findings.jsonl": last_hash("root_files/short/findings.jsonl")})
        self.assertNotEqual(root(short), parts["root"])
        for case in group["cases"]:
            self.assertTrue(case["cmd"].startswith("python -m ledger.anchor root /vec/root/ledger_plus.jsonl "))
        self.assertIn("seed/bootstrap/vectors/root_files/** -text", (ROOT / ".gitattributes").read_text(encoding="utf-8"))
        self.assertIn("`cp_lower`, `mcnemar`, `match` ve `root_files` (MF8, arayüz `29zb`, `26j`) P1'indir", flat(page("29d")))
        self.assertIn("## `root_files` (P1 MF8, `ledger/anchor.py`)", page("29zb"))
        self.assertIn("Satırı olan her dosya `tips`'e adıyla (`findings.jsonl`, `unresolved.jsonl`) ve son satırının "
                      "saklı `row_hash`'iyle girer; satırsız dosya anahtar eklemez", flat(page("29zb")))


class AllowlistTest(unittest.TestCase):
    """seed-087: `26j` "İzin listesi, MF9"."""

    def test_package_entry_row_and_done(self):
        # package_path_other gate_reads_declared_hashes ready_candidates_exempt entry_by_referee_code
        # evidence_runs_empty keyed_by_hash_alone removal_loosening_unnamed mf9_done_without_refusal package_path_26a
        text = flat(page("26j"))
        for words in ("**İzin listesi, MF9** (bağımsız inceleme ekibi kararı (2026-11-21), seed-087)",
                      "Çalışma-zamanı adayı `koş`un çıktı ağacında `candidates/<id>/package.json`'dur",
                      "(`finding`, `diff`, `organ_ids`, `definition_sha256`). Kapı yalnız `organ_ids`'i okur.",
                      "Aşama 0'ın hazır adayları P1'in aktarımıyla biter: organ adlandırmayan aday `no_organ` ile "
                      "reddedilir. Etkinleştirme (genesis) devri Aşama 0'ın kuralını korur.",
                      "P1'de hiçbir organ girmez. Giriş tetiği hakem kodu değil veridir: önyükleme hakeminin kabul "
                      "ettiği beyin SHA'sında commit'lenmiş bir organ beyanı, giriş isteği `{organ_ids}`; ilk kullanımı "
                      "Aşama 1 MF6'dır", "`evidence_run_ids`, `yaz`'ın dayandığı imzalı sonucun önyükleme koşusunun "
                      "kimliğidir, tek elemanlı liste", "Liste `(organ_id, definition_sha256)` çiftiyle anahtarlanır",
                      "Aşama 1'de listeden çıkaran satır yoktur (gevşetme L1, seed-087)",
                      "`accept` satır türü P1'den defter şemasındadır",
                      "MF9, kuralları ve bağlantısı kanıtlandığında ve ret canlı koştuğunda biter; ilk gerçek `accept` "
                      "satırı Aşama 1 MF5/MF6'dadır"):
            self.assertIn(words, text, words)
        self.assertIn("`candidates/<id>/package.json`'a (`26j`) yazılır", flat(page("26a")))
        row = register_row("E686")
        self.assertIn("**Gevşetme** (adı konmuş): L1, Aşama 1'de listeden çıkaran satır yok", row)


class Seed085Test(unittest.TestCase):
    """seed-085's open items as decided (operator; L-b, L-c, L-j the owner's)."""

    def test_the_five_items(self):
        # cagir_calls_under_freeze kos_stops_under_freeze freeze_stops_reverts spend_summed_per_target
        # class_field_added restart_resets_count restart_row_unnamed loosenings_085_unlabelled
        text = flat(page("28a"))
        for words in ("**seed-085'in açık maddeleri** (operatör kararı (2026-11-21); gevşetmeler L-b, L-c ve L-j "
                      "sahip kararı (2026-11-21))",
                      "`çağır` kapsamında `loop` olan bir dondurma yürürlükteyken hiçbir çağrı yapmaz; bütçe "
                      "dondurmasının kapsamı `loop`'tur (`26i`)", "Dondurma yalnız adayların merge'ünü kapatır; geri almalar, prova "
                      "ekmeleri ve satırlar sürer", "`koş` her dondurmada koşmayı sürdürür (gevşetme L-b)",
                      "`yaz` işinin sunduğu her hedefin defteri üzerinden toplanır ve tek tavanla bir kez yargılanır "
                      "(gevşetme L-c: işin sunmadığı hedefin harcaması o işte sayılmaz)",
                      "Aşama 1'de her merge ve geri alma K0'dır (`asama-1/13b`, `26i`); merge satırında sınıf alanı yoktur",
                      "`setup/imports.jsonl`'da bitirdiği `hard_stop` satırını adlandıran bir satırdır (`26i`). "
                      "`soft_freeze_limit` sayımını sıfırlamaz",
                      "Kapalı kapının reddi `cause` taşımaz ve bulgusunu olduğu durumda bırakır (`26j`; gevşetme L-j)"):
            self.assertIn(words, text, words)
        self.assertNotIn("ücretli çağrı", text)
        self.assertIn("insan dokunuşu sayacı; aktarım dışı yeniden başlatma satırı da buradadır (`26i`)",
                      flat(page("26c")))
        for words in ():
            self.assertIn(words, text, words)
        gozcu = flat(page("26i"))
        for words in ("Dondurma yalnız adayların merge'ünü kapatır: geri almalar, prova ekmeleri ve satırlar her "
                      "dondurmada sürer (`28a`)", "toplam `yaz` işinin sunduğu her hedefin defteri üzerindendir "
                      "(seed-085 c, `28a`)", "**Yeniden başlatma satırı** (seed-085 h; `28a`)",
                      "`{ts, stage, touch: \"restart\", target, hard_stop, note}`",
                      "`hard_stop` bitirdiği `freeze`/`hard_stop` satırının `row_hash`'idir"):
            self.assertIn(words, gozcu, words)

    def test_the_closed_gate_reject(self):  # closed_gate_reject_has_cause standing_reasons_short loosenings_085_unnamed
        text = flat(page("26j"))
        self.assertIn("**Kapalı kapının reddi** (seed-085 j; sahip kararı (2026-11-21), gevşetme L-j). Bütün nedenleri "
                      "duran nedenlerden olan ret (`frozen:<trigger>`, `merge_paused`, `sentinel_pending`, `no_organ`, "
                      "`organ_unknown:<id>`, `organ_not_listed:<id>`) `cause` taşımaz, `unresolved` satırı yazmaz ve "
                      "bulgusunu olduğu durumda bırakır. Başka bir nedeni olan ret `cause`'unu o nedenlerden alır.", text)
        row = register_row("E687")
        self.assertIn("**Gevşetmeler** (sahip kararı (2026-11-21)): L-b", row)
        for words in ("L-c işin sunmadığı hedefin harcaması", "L-j kapalı kapının reddi"):
            self.assertIn(words, row, words)


class TableCorrectionTest(unittest.TestCase):
    """The operator's table correction (owner-approved 2026-11-21): P1 MF10-MF12, before P1's exit."""

    def test_the_table_and_its_pages(self):  # p1_new_row_dropped p1_new_row_test_reused asama1_13_new_rows_missing
        table = stages.load(1)
        self.assertEqual([f.mf for f in table.mfs], list(range(1, 13)))
        self.assertEqual([(f.tests, f.module) for f in table.mfs[9:]],
                         [((56,), "runner/organ_output.py"), ((57,), "runner/candidate_rerun.py"),
                          ((58,), "loop/candidates.py")])
        self.assertEqual([f.module for f in table.mfs[:9]],
                         ["runner/organs.py", "snapshot/make.py", "cases/build.py", "harness/score.py",
                          "harness/offline.py", "drift/check.py", "gozcu/evaluate.py", "findings/write.py",
                          "gate/allowlist.py"])  # no accepted or earlier MF changes meaning
        frozen = (ROOT / "spec" / "asama-0" / "09-harness-in-kendi-testleri.md").read_text(encoding="utf-8")
        self.assertEqual(max(int(n) for n in re.findall(r"^\| (\d+) \|", frozen, re.M)), 52)
        for mf, test, words in ((10, 56, "`koş` bir organın çıktısını koşu sonuçlarında tutar"),
                                (11, 57, "`koş` bir çalışma-zamanı adayını kapıdan önce yeniden koşar"),
                                (12, 58, "`yaz` `candidates/<id>/`'yi sonuçlardan hash'iyle okur")):
            self.assertIn(f"| P1 | {mf} | {words} (`tohum/26j`) | {test} | — |", stage1("13"))
        self.assertIn("MF12'ye kadar: bulgu yazıcısı, izin listesi ve çalışma-zamanı aday yolu dahil", flat(stage1("06")))

    def test_the_rows_and_their_tests(self):
        # table_correction_unlabelled rows_after_the_exit organ_output_unhashed rerun_skipped package_bad_stops_cycle
        # p1_order_ends_at_mf9 p26e_tests_unpointed
        text = flat(page("26j"))
        for words in ("**P1'in üç yeni satırı** (operatörün tablo düzeltmesi, sahip onayı (2026-11-21): seed-086 ve "
                      "seed-087'yi yanıtlayan iki inceleyicinin bulduğu eksiktir, Kurucu'nun bir raporundan gelmez)",
                      "Çalışma-zamanı aday yolunun hakem tarafı P1'in çıkışından öncedir: Aşama 1 MF1, MF5 ve MF6 hakem "
                      "değişikliği olmadan canlı koşar. MF1–MF9'un numaraları değişmez.",
                      "**MF10, organ çıktısının tutulması** (modül `runner/organ_output.py`; test 56)",
                      "Test 56: organın çıktısı sonuçlarda hash'iyle durur ve `yaz` onu o hash'le okur; bir baytı "
                      "değişmiş çıktı okunmaz.",
                      "**MF11, çalışma-zamanı adayının yeniden koşusu** (modül `runner/candidate_rerun.py`; test 57)",
                      "Test 57: aday hazır aday gibi koşar (üç lint koşusu, test koşusu, kırmızı kontrol); yeniden "
                      "koşusu olmayan aday kapıya ulaşmaz.",
                      "**MF12, `yaz`'ın aday okuması** (modül `loop/candidates.py`; test 58)",
                      "Test 58: `organ_ids` kapıya, `finding` bulgu yazıcısına gider; biçimsiz paket yalnız o adayı "
                      "reddeder."):
            self.assertIn(words, text, words)
        self.assertIn("Sıra: P1 partisi (MF12'ye kadar)", flat(page("26h")))
        self.assertIn("56–58 de devamdır, tanımları `26j`'de", flat(page("26e")))
        self.assertIn("MF10–MF12 operatörün tablo düzeltmesidir (`26j`)", flat(page("26e")))


class ModuleNameRuleTest(unittest.TestCase):
    """The review of PR #31: two rules of `26e` the compression dropped are stated again (the code's are stages.py's)."""

    def test_the_stdlib_rule_and_the_batch_column(self):  # cprofile_rule_dropped batch_column_unnamed
        text = flat(page("26j"))
        self.assertIn("**Modül adı** (`26e`'nin kuralı). Modülün ilk adı (paketi ya da `.py`'siz dosyası) Python'un "
                      "standart kütüphanesinde bir modülün adı olamaz (`sys.stdlib_module_names`; `profile/` varken "
                      "`import cProfile` düşer): böyle satırı olan tablo yüklenmez.", text)
        self.assertIn("Hakem komutu `referee/`'yi `sys.path`'te önde koşar; Aşama 0'ın donmuş `profile`'ı o tablo yeniden "
                      "açılana kadar kalır ve hakemin hiçbir komutu `cProfile`'ı çağırmaz (`26e`).", text)
        self.assertEqual(stages.STDLIB_KEPT, {0: frozenset({"profile"})})  # the code keeps the same rule
        said = flat(page("26e"))
        self.assertIn("`batch` bu tablonun ilk sütunudur ve açık partininki olmalıdır, değilse `exit_request_wrong_batch`",
                      said)
        self.assertIn("Modülün ilk adı standart kütüphanede bir modülün adı olamaz (`sys.stdlib_module_names`; ayrıntısı "
                      "`26j`'de)", said)
        self.assertTrue(all(len(line) <= 126 for line in page("26e").splitlines()[31:40]))


class FirstTaskTest(unittest.TestCase):
    def test_this_entry_opens_with_its_first_task(self):  # ab_first_task_not_first ab_first_task_row_dropped
        entry = flat(changelog().split("\n- 2.2 (2026-11-21, E685–E690", 1)[1])
        self.assertTrue(entry.startswith("; tohum dönemi AB; bağımsız inceleme ekibi kararı, operatör ve sahip kararları). "
                                         "**İlk iş** (`25` 10b; Kurucu'nun dersi f1741)."), entry[:160])
        first = entry.split("Yeni `26j`")[0]
        for words in ("önyükleme hakeminin hiçbir denetimi kırmızı olmaz", "yeni `root_files` grubu yalnız MF8 bitince koşar",
                      "İlk iş P1'in üç yeni satırıdır", "`done_mf` önek kaldığı için MF8 ve MF9'dan sonra kurulur",
                      "P1'in çıkış isteği MF1–MF12'nin hepsi bitmeden geçmez",
                      "1. MF10, organ çıktısının tutulması (`runner/organ_output.py`, test 56);",
                      "2. MF11, çalışma-zamanı adayının yeniden koşusu (`runner/candidate_rerun.py`, test 57);",
                      "3. MF12, `yaz`'ın aday okuması (`loop/candidates.py`, test 58)."):
            self.assertIn(words, first, words)
        self.assertIn("başında **İlk iş**", flat((TOHUM / "CHANGELOG.md").read_text(encoding="utf-8")))
        self.assertIn("Kırmızı görev olmayan iki sahip ipucu (bu kez kural esnetildi; `00d`) İlk iş'in birinci "
                      "maddesinden sonra gelir, bütün P1'i beklemez: E689 Kurucu'nun kendi önerisi (f1766), prepush'ın "
                      "hızlı geçişi; E690 bellekten yazılan adı defter satırı eklenmeden önce ağaca karşı denetlemek; "
                      "ikisi de ölçülerek.", first)
        self.assertIn("`26i:36-37`, `26i:45-46`", changelog())


class MemoryNameHintTest(unittest.TestCase):
    """The owner's second hint of 2026-11-21 (E690): a recurring class, its evidence and a measurement; no recipe."""

    def test_00d_names_the_class_and_the_evidence(self):  # memory_hint_unlabelled memory_hint_recipe memory_hint_unmeasured
        text = flat(page("00d"))
        for words in ("**Sahibin ipucu (bu kez kural esnetildi; 2026-11-21, E690; ipucu, reçete değil). Bellekten "
                      "yazılan ad.**", "defter satırına bir dosya ya da sayfa adı bellekten yazılıyor ve satır "
                      "eklendikten sonra düzeltiliyor", "f1698'in f1704'teki düzeltmesi", "f1795'in f1800'deki düzeltmesi",
                      "Kendi derslerin sınıfı adlandırıyor, sınıf yine de tekrarlıyor",
                      "defter satırı eklenmeden önce koşan ve ağaçta olmayan bir referansı reddeden bir denetim",
                      "Ölç: bu tür düzeltmelerin sayısı, önce ve sonra.", "Nasıl kurulacağı senindir."):
            self.assertIn(words, text, words)
        self.assertEqual(text.count("Nasıl kurulacağı senindir."), 2)
        row = register_row("E690")
        self.assertIn("sahibin ipucu (bu kez kural esnetildi", row)
        self.assertIn("\"Kurucu kendisi bulur\" kuralını bir kez esnetmeyi seçti", row)


class PrepushHintTest(unittest.TestCase):
    """The owner's hint of 2026-11-21 (E689): the Founder's own proposal, its evidence and a measurement; no recipe."""

    def test_00d_names_the_proposal_and_the_evidence(self):  # prepush_hint_unlabelled prepush_hint_recipe prepush_hint_unmeasured
        text = flat(page("00d"))
        for words in ("**Sahibin ipucu (bu kez kural esnetildi; 2026-11-21, E689; ipucu, reçete değil). Prepush'ın hızlı "
                      "geçişi.**", "20261121T014159Z oturumunun iyileştirme önerisi (f1766, senin, kurulmadı)",
                      "son damgadan beri değişen bir modülü import eden dosyaların bildirim komutlarını koşsun",
                      "İçe aktarma grafiği `status.depmap`'inkidir ve kökteki `tests/` dizinini kapsamalıdır; damgayı "
                      "yalnız bütün koşu basar", "\"`referee/` dışındaki bir çağıran atlandı\" (dersler f1812 ve f1829 "
                      "dahil)", "kırmızı bir T46'ya mal oldu",
                      "İlk iş'inin birinci maddesinden sonraki işin olarak kur ve ölç: kazanılan dakikalar ve atlanan "
                      "çağıran sınıfını yakalayıp yakalamadığı",
                      "Nasıl kurulacağı senindir."):
            self.assertIn(words, text, words)
        row = register_row("E689")
        self.assertIn("sahibin ipucu (bu kez kural esnetildi", row)
        self.assertIn("\"Kurucu kendisi bulur\" kuralını bir kez esnetmeyi seçti", row)


class RecordsTest(unittest.TestCase):
    def test_register_changelog_index_caps_and_no_owner_item(self):  # owner_item_leaks
        for eid, decided in (("E685", "bağımsız inceleme ekibi kararı (2026-11-21"),
                             ("E686", "bağımsız inceleme ekibi kararı (2026-11-21"),
                             ("E687", "operatör kararı (2026-11-21"),
                             ("E688", "operatörün tablo düzeltmesi, sahip onayı (2026-11-21")):
            with self.subTest(eid=eid):
                self.assertIn(decided, register_row(eid))
        log = changelog()
        for rid in ("seed-085-gozcu-wiring-what-a-freeze-closes-and-what-a-cycle-measures",
                    "seed-086-findings-write-root-coverage-row-shapes-and-triggers-unstated",
                    "seed-087-allowlist-package-layout-accept-trigger-and-run-ids-unstated"):
            self.assertTrue(any(f"`{rid}` →" in line for line in log.splitlines()), rid)  # one line (E527)
        index = (ROOT / "spec" / "INDEX.md").read_text(encoding="utf-8")
        for name, title in (("26j-semalar-p1-bulgu-izin-aday.md",
                             "Şemalar, Devam: P1'in Bulgu Yazıcısı, İzin Listesi ve Aday Yolu"),
                            ("CHANGELOG-11.md", "Değişiklik Günlüğü — Tohum, 2.2'nin Onuncu Kayıtları")):
            self.assertIn(f"| `tohum/{name}` | {title} |", index)
        for p in list(TOHUM.glob("*.md")) + list((ROOT / "spec" / "asama-1").glob("*.md")):
            self.assertLessEqual(len(p.read_text(encoding="utf-8").splitlines()), 80, p.name)
        for text in (page("26j"), page("26i"), page("28a"), log):  # the desk's owner-only items stay out of the seed
            for word in ("job.py", "status.block", "app_scope", "iddiadır"):
                self.assertNotIn(word, text)


if __name__ == "__main__":
    unittest.main()
