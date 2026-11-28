"""Seed epoch AI (2026-11-23, report desk, the P1 exit epoch): seed-073 (a), (c), (d) and seed-087 (iv) (E696), the three
"P1 exit epoch" deferrals of E703, and the P3 table with the owner's fixer.llm brakes (E702). Only `spec/tohum` reaches
the brain, so each binding sentence is on a `tohum` page: new `26r` (the organ's file, its carriage and image) and `26s`
(P3's table on the page, tests 59 and 60, the brakes); `26j:79-80` and `26j:35` (no stage guard, the loosening L-P1E);
`26n` (the brakes decided, L-AF1 ended, the deferrals decided); `26h:44` (the K3+ branch is not P3's); `18a`, `24a`,
`29v` and `26e` point there. P3's machine copy is not part of this epoch. Every item of the two reports has a line in
`CHANGELOG-18`. The trailing comment on a test names the mutants it kills (`local/mutate.py`)."""

import no_real_delays  # noqa: F401  (first: no test waits on a real delay, E751)
import json
import re
import unittest
from pathlib import Path

from snowball_bootstrap import policyreads, stages

BOOT = Path(__file__).resolve().parents[1]
ROOT = BOOT.parents[1]
TOHUM = ROOT / "spec" / "tohum"
REPORTS = ("seed-073-organ-definition-layout-and-carriage-unstated",
           "seed-087-allowlist-package-layout-accept-trigger-and-run-ids-unstated")
BRAKES = ("constitutional.stage_params.fix_call_max_usd", "constitutional.stage_params.fix_call_max_s")


def page(prefix: str) -> str:
    found = sorted(TOHUM.glob(f"{prefix}-*.md"))
    assert len(found) == 1, (prefix, found)
    return found[0].read_text(encoding="utf-8")


def stage1(prefix: str) -> str:
    [found] = sorted((ROOT / "spec" / "asama-1").glob(f"{prefix}-*.md"))
    return found.read_text(encoding="utf-8")


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
    return (TOHUM / "CHANGELOG-18.md").read_text(encoding="utf-8")


def items(head: str) -> list[str]:
    """The item lines `CHANGELOG-18` gives under the line that starts with ``head``: its `  - ` lines (a wrapped item
    joined), up to the next head."""
    lines = changelog().splitlines()
    start = next(i for i, line in enumerate(lines) if line.strip().startswith(head))
    out = []
    for line in lines[start + 1:]:
        if line.startswith("  - "):
            out.append(line[4:])
        elif line.startswith("    ") and out:
            out[-1] += " " + line.strip()
        else:
            break
    return out


FILE = ("**Organın dosyası**", "**Taşınma**")
CARRIAGE = ("**Taşınma**", "**İmaj**")
IMAGE = ("**İmaj**", None)
TABLE = ("**Yeri.**", "**`fixer.llm`'in çağrı başı frenleri**")
BRAKE = ("**`fixer.llm`'in çağrı başı frenleri**", "**P3'te olmayanlar**")
NOT_P3 = ("**P3'te olmayanlar**", None)


class OrganFilePageTest(unittest.TestCase):
    """`26r` (seed-073 (a), (c), (d); E733): adopted as built, no tightening."""

    def test_the_organ_file(self):
        # ai_organ_path_moved ai_organ_id_dotless ai_26p_rule_for_organs ai_organ_extra_fields ai_entry_appended
        # ai_hash_takes_exec_bit ai_organ_entry_skipped ai_llm_fields_now ai_accept_push_record
        text = section("26r", *FILE)
        for words in ("Organ, önyükleme hakeminin kabul ettiği beyin SHA'sında beyin kökündeki `organs/<organ_id>.json` "
                      "dosyasıdır.", "`runner.kos.CANDIDATE_ID`'nin biçiminde: `[A-Za-z0-9][A-Za-z0-9._-]{0,127}` "
                      "(nokta olabilir).", "`26p:38`'in noktasız kuralı yalnız çalışma-zamanı aday kimlikleri içindir, "
                      "organ kimliği için değil.", "Dosya tam olarak `entry` ve `files` taşıyan bir JSON nesnesidir.",
                      "kapsayıcının yazıldığı gibi koştuğu komut, sonuna bir şey eklenmez.",
                      "çalıştırma biti ve `files`'ın sırası hash'e girmez.", "hiçbir girdi atlanmaz.",
                      "O SHA'da `organs` girdisi yoksa organ yoktur.", "Aşama 1'de dosyada başka alan yoktur.",
                      "LLM organının modeli ve araçları (`26e:62-63`) P3'ün 2. satırıyla tanımına girer (`26s`).",
                      "`organs/` tanımların dizinidir, kod değildir.",
                      "ikisi de veridir ve ikisinden birine dokunan push kod isteğidir (`29b:42`)."):
            self.assertIn(words, text, words)

    def test_the_carriage_and_the_two_lists(self):
        # ai_carriage_other_way ai_organs_json_declared ai_accepted_is_listed ai_unlisted_not_called
        text = section("26r", *CARRIAGE)
        for words in ("Organlar `koş`'a ve `yaz`'a yalnız `pulled`'da ulaşır:",
                      "`organs.json` (`{organ_id: definition_sha256}`, hakemin okuduğu dosyalardan kendi hesapladığı)",
                      "`organs/<organ_id>/entry.json` ve `organs/<organ_id>/files/<yol>`",
                      "`accept.json` (`null` ya da `{brain_sha, run_id, organ_ids}`)",
                      "\"Kabul edilmiş\" ile \"listelenmiş\" iki ayrı listedir.",
                      "Listede henüz olmayan bir organ çağrılır ve adayı `organ_not_listed:<id>` ile reddedilir: bu ret "
                      "Aşama 1 MF5'in kırmızı testidir (`asama-1/06:21-22`)."):
            self.assertIn(words, text, words)

    def test_the_image(self):
        # ai_image_unpinned ai_in_writable ai_network_on ai_organ_image_key ai_language_run_valid
        text = section("26r", *IMAGE)
        for words in ("birim tarifinin `@sha256` ile pinli `env_image`'ında",
                      "tanımın dosyaları `/in/<beyin yolu>` altında salt okunur, çıktısı `/out` altında (`26p:16`), ağsız, "
                      "yanında işin kırmızı kontrolüyle", "Aşama 1'de organa özgü imaj yoktur; tanımda imaj anahtarı yoktur.",
                      "dili o imajda olmayan organın koşusu geçerli değildir, nedeni koşununkidir.",
                      "Birimin lint aracı bir adaptere `26m:23-24`'ün söylediği gibi ulaşır"):
            self.assertIn(words, text, words)

    def test_the_pages_point_to_26r(self):  # ai_26e_unpointed ai_24a_layout_missing ai_24a_accept_missing
        self.assertIn("araç yüzeyidir). Organın dosyası, taşınması ve imajı `26r`'dedir (seed-073).",
                      page("26e").splitlines()[62])
        layout = page("24a")
        self.assertIn("\norgans/<id>.json                organ tanımları, veri (Aşama 1'den; `26r`)\n", layout)
        self.assertIn("\naccept.json                     giriş isteği, veri, yalnız bir organ girerken (`26j:68-72`, "
                      "`26r`)\n", layout)


class NoGuardPageTest(unittest.TestCase):
    """`26j:79-80` and `26j:35` (seed-087 (iv); E733, E734): no stage guard; the loosening L-P1E."""

    def test_the_entry_is_the_order_of_work(self):  # ai_entry_is_check
        self.assertIn("- **Giriş.** İşin sırası, bir denetim değil ((iv)): P1'de hiçbir organ girmez.",
                      page("26j").splitlines()[34])

    def test_no_guard_and_the_loosening(self):
        # guard_now ai_order_unheld ai_l_p1e_unlabelled ai_l_p1e_unscoped ai_l_p1e_unseen
        lines = page("26j").splitlines()
        self.assertEqual(len(lines), 80)
        self.assertTrue(lines[78].startswith("- **(iv)**"))
        text = flat("\n".join(lines[78:80]))
        for words in ("`accept.json`'un aşama koruması yoktur, P1'de de sonra da: hiçbir hakem kodu bir giriş isteğini "
                      "okunduğu aşama için reddetmez (kurulduğu gibi benimsendi).",
                      "P1'de beyin ne organ ne `accept.json` taşır; ilk giriş Aşama 1 MF6'dır",
                      "MF5'ten MF6'ya sırayı kod değil, MF5'in kırmızı testi (`asama-1/06:21-22`) ve push'un incelemesi "
                      "tutar (kod isteği, `29b`).", "**Gevşetme L-P1E** (kapsamlı; sahibe bildirilir):",
                      "Kapsamı P1'dir, P1'in aktarımıyla biter.", "Görünürdür: beyin kökünde bugün `accept.json` yoktur."):
            self.assertIn(words, text, words)
        self.assertNotIn("P1 çıkış dönemine ertelendi", flat(page("26j")))


class P3TablePageTest(unittest.TestCase):
    """`26s` (E735): P3's table on the page, tests 59 and 60, no machine copy yet."""

    def test_the_rows(self):  # ai_p3_test_59_missing ai_p3_test_60_missing
        rows = [line for line in page("26s").splitlines() if line.startswith("| `P3` |")]
        self.assertEqual(rows, ["| `P3` | 1 | 52 | — | sayfada yok | — |", "| `P3` | 2 | 59 | — | sayfada yok | sayfada yok |",
                                "| `P3` | 3 | 60 | — | sayfada yok | — |"])
        self.assertIn("| Parti (`batch`) | MF | Test | Vektör grubu | Modül (`referee/` altında) | `calls` |", page("26s"))

    def test_59_and_60_are_the_next_free_numbers(self):
        frozen = (ROOT / "spec" / "asama-0" / "09-harness-in-kendi-testleri.md").read_text(encoding="utf-8")
        self.assertEqual(max(int(n) for n in re.findall(r"^\| (\d+) \|", frozen, re.M)), 52)
        used = {n for stage in (0, 1) for f in stages.load(stage).mfs for n in f.tests}
        self.assertEqual(max(used), 58)  # 53 30d's, 55 26h's, 56-58 26j's
        self.assertFalse({59, 60} & used)
        self.assertIn("Ertelenen P3'ün tablosu da öyle gelir (`26h`); sayfadaki satırları ve testleri 59 ve 60 `26s`'dedir.",
                      flat(page("26e")))

    def test_no_machine_copy_in_this_epoch(self):  # ai_p3_machine_copy_now ai_p3_opens_early
        self.assertEqual(stages.BATCHES[1], ("P1", "P2"))
        self.assertFalse((stages.STAGES_DIR / "stage1-P3.json").exists())
        text = section("26s", *TABLE)
        for words in ("Tablo P2'den sonra açılır.", "Bu tohum onun makine kopyasını taşımaz:",
                      "`stages/stage1-P3.json` yoktur"):
            self.assertIn(words, text, words)
        self.assertIn("Sayfadaki tablosu, testleri ve frenleri `26s`'dedir (P1 çıkış dönemi).", flat(page("26h")))
        self.assertIn("sayfadaki satırları ve testleri 59 ve 60 `26s`'dedir.", flat(page("26e")))

    def test_the_test_texts_are_the_pages_sentences(self):
        # ai_test59_untyped ai_test59_outside_range ai_test59_cap_edit ai_test59_red_silent ai_test60_one_probe
        # ai_test60_unclean_lifts ai_test52_out_of_band
        text = section("26s", *TABLE)
        for words in ("Test 59: tipli bir `fixer.llm` isteği `çağır`'dan geçer; yanıt yalnız bulgunun aralığına "
                      "uygulanır, aralığın dışındaki bir yanıt uygulanmaz; iki tavandan birini aşan çağrı düzenleme "
                      "vermez; tutmayan yolda worktree atılır ve bulgu `cause` ile `unresolved.jsonl`'a önerilir.",
                      "Test 60: üst üste iki temiz sonda döngüsü dondurmayı kaldırır ve kalkış bir satırdır",
                      "temiz olmayan bir sonda döngüsü kaldırmaz.",
                      "sınırı yalnız operatörün bandı içinde, iki yönde oynatır; bant dışı öneri reddedilir."):
            self.assertIn(words, text, words)
        self.assertIn("| P3 | 2 | Düzeltme gidiş-dönüşü `koş` → `çağır` → `koş` (§1.5 3; `tohum/26h`, `tohum/26s`) | 59 | — |",
                      stage1("13"))
        self.assertIn("| P3 | 3 | Sonda döngüsü ve kalkışı (`tohum/28`; `tohum/28a` L3, `tohum/26s`) | 60 | — |", stage1("13"))

    def test_what_is_not_p3(self):  # ai_k3_in_p3 ai_k3_in_p3_26s
        text = section("26s", *NOT_P3)
        for words in ("testleri 3 ve 5 \"K3 ile\"dir ve K3 Aşama 3'tedir; K3'ü getiren Aşama 3 partisiyle gelir ve P1 "
                      "MF4'ün modülünde kalır", "kendi sayfalarının adlandırdığı dönemlerle gelir, P3'le değil."):
            self.assertIn(words, text, words)
        self.assertIn("Düzeltme (P1 çıkış dönemi): K3+ dalı P3'te değildir; testleri 3 ve 5 \"K3 ile\"dir ve K3'ü getiren "
                      "Aşama 3 partisiyle gelir", flat(page("26h")))


class BrakesTest(unittest.TestCase):
    """The owner's fixer.llm brakes (2026-11-23): `26s`, `26n`, `18a`, `29v`, `asama-1/10`; L-AF1 ends (E702)."""

    def test_the_keys_and_their_form(self):
        # ai_brake_usd_float ai_brake_seconds_any ai_brake_in_stage_budgets ai_brake_reader_unnamed
        text = section("26s", *BRAKE)
        for words in ("`constitutional.stage_params.fix_call_max_usd` `\"0.500000\"` (`01c`'nin altı ondalıklı dizgisi, "
                      "0'dan büyük)", "`constitutional.stage_params.fix_call_max_s` `300` (1 ya da daha büyük JSON "
                      "tamsayısı); başka biçim `policy_invalid:<yol>`'dur.",
                      "İkisi `18a`'nın anayasal tablosunun satırlarıdır, `stage_budgets` değildir",
                      "Okuyucuları P3 MF2'de `fixer.llm` adına `llm.call`'dır (`26a:39`).",
                      "300 saniyelik tavanı kimin uyguladığını P3 MF2 adlandırır"):
            self.assertIn(words, text, words)

    def test_29v_keeps_its_cited_lines(self):  # ai_29v_cited_lines_moved
        """CHANGELOG-10 and the brain's confirmed seed-084 and seed-085 cite `29v:52-61` and `29v:58-61`: the P3
        paragraph is the page's last, so no cited line moves."""
        lines = page("29v").splitlines()
        self.assertTrue(lines[57].startswith("**Döngüde eksik anahtar**"), lines[57])
        self.assertTrue(lines[51].startswith("**Gözcü'nün yolları**"), lines[51])
        self.assertTrue(lines[62].startswith("**Okunuş.**"), lines[62])
        self.assertEqual([i for i, line in enumerate(lines) if line.startswith("**P3'ün yolları**")], [66])

    def test_required_only_when_p3_opens(self):  # ai_brakes_required_now ai_29v_p3_required_now ai_fixture_brake_missing
        text = section("26s", *BRAKE)
        self.assertIn("P3'ün tablosu açılınca okunması zorunlu yollar olur (`29v`), bu dönemin tesliminde değil;", text)
        self.assertIn("`performance.rules.probe_cycle` P3'ün tablosu açılınca okunması zorunlu yollar olur, bu dönemin "
                      "tesliminde değil: o zamana kadar `required.json`'da değildir", flat(page("29v")))
        fixtures = BOOT / "vectors" / policyreads.FIXTURE_DIR
        required = json.loads((fixtures / policyreads.REQUIRED).read_text(encoding="utf-8"))
        for path in BRAKES + ("performance.rules.probe_cycle",):
            self.assertFalse(any(path in rows for rows in required.values()), path)
        for name in (policyreads.FULL, policyreads.HOISTED):
            doc = json.loads((fixtures / name).read_text(encoding="utf-8"))
            usd, seconds = (policyreads.at(doc, path.split(".")) for path in BRAKES)
            self.assertRegex(usd, r"\A(0|[1-9][0-9]*)\.[0-9]{6}\Z", name)
            self.assertNotEqual(usd, "0.000000", name)
            self.assertIs(type(seconds), int, name)
            self.assertGreaterEqual(seconds, 1, name)

    def test_l_af1_ends(self):
        # l_af1_unlabelled ai_l_af1_exempt ai_brakes_deferred_again ai_18a_still_deferred ai_18a_brake_reader_stage0
        text = section("26n", "**Aşama 1'in bulgu başı frenleri**", "**Açıkça ertelenenler**")
        for words in ("sahip kararı (2026-11-23), P1 çıkış dönemi). Karar verildi (E702 kapandı):",
                      "**L-AF1 bitti** (bu dönemle): `02:22`'nin eşik maddesi (\"her eşik ya `policy.json`'a ya da anayasal "
                      "tabana atıf\") bu hücreye de uygulanır ve hiçbir `spec.lint` bu hücreyi muaf tutmaz."):
            self.assertIn(words, text, words)
        for words in ("Gevşetme L-AF1** (geçici)", "o döneme kadar uygulanmaz", "Ertelendi:"):
            self.assertNotIn(words, text, words)
        lines = page("26n").splitlines()
        self.assertTrue(lines[70].startswith("- Bulgu başı frenlerin anahtarları (seed-095)"))  # 26n:71, as it was
        self.assertEqual(lines[71], "")  # epoch AN appends after 26n:71
        self.assertTrue(page("26n").splitlines()[54].startswith("**Açıkça ertelenenler**"))  # 26n:55 did not move
        self.assertIn("- Bulgu başı frenlerin anahtarları (seed-095) → P1 çıkış döneminde karar verildi (yukarıda, `26s`).",
                      page("26n"))
        row = next(line for line in page("18a").splitlines() if line.startswith("| `constitutional.stage_params.fix_call"))
        self.assertTrue(row.startswith("| `constitutional.stage_params.fix_call_max_usd`, `fix_call_max_s` | Çağrı başına "
                                       "0,50 USD (dosyada `\"0.500000\"`, 0'dan büyük) ve 300 sn"), row)
        self.assertTrue(row.endswith("| P3 MF2: `fixer.llm` adına `llm.call` (`26s`) |"), row)
        self.assertIn("bulgu başı frenlerinin anahtarları aşağıdaki satırdadır (karar verildi, `26n`, seed-095)", page("18a"))
        self.assertIn("Anahtarları çağrı başınadır: `constitutional.stage_params.fix_call_max_usd` (`\"0.500000\"`) ve "
                      "`constitutional.stage_params.fix_call_max_s` (`300`)", stage1("10"))


class DeferralsTest(unittest.TestCase):
    """E703's three "P1 exit epoch" deferrals (`26n:57-60`), decided in this epoch."""

    def test_each_is_decided(self):  # ai_chain_in_p3 ai_rederive_declined_now ai_test11_list_now
        lines = page("26n").splitlines()
        self.assertTrue(lines[56].startswith("- `cases/dev.jsonl`'un hash zinciri (seed-090 (1)) → Aşama 1 çıkış partisi "
                                             "(P1 çıkış döneminde karar)"), lines[56])
        self.assertIn("(seed-091 (1)) → ilk LLM avcısını getiren dönem, en geç Aşama 4 partisi", lines[57])
        self.assertTrue(lines[59].startswith("- Test 11'in tam yol listesi (seed-092 (4)) → reddedildi (P1 çıkış "
                                             "döneminde karar): listenin tanımı `26n:22-25`'tir"), lines[59])
        text = flat(page("26n"))
        self.assertNotIn("→ P1 çıkış dönemi:", text)
        self.assertIn("bugün puanlanan her parmak izini hakemin kendi yazıcısı yapar (L-AH1 dışında, `26q`).", text)
        # delivered pages cite asama-1/13 by its rows: the brain's copy of asama-1 is the Founder's (E180)
        self.assertIn("ilk hüküm `exit.sample`'dır (test 27, `asama-1/13`'ün \"Aşama 1 çıkışı\" satırı)", text)
        self.assertIn("(`asama-1/13`'ün \"Aşama 4\" partisi, \"ilk LLM avcısından önce\"; P1 çıkış döneminde karar)", text)
        self.assertIn("P3 `asama-1/13`'ün \"P3 ertelenenler\" satırının sırasıyla", flat(page("26s")))
        for prefix in ("26n", "26s", "26r"):
            self.assertNotRegex(page(prefix), r"asama-1/13:[0-9]", prefix)
        self.assertNotRegex(changelog(), r"asama-1/13:[0-9]")
        thirteen = stage1("13")
        for row in ("| P3 ertelenenler |", "| Aşama 1 çıkışı | 1 | `exit.sample`", "| Aşama 4 | ilk LLM avcısından önce |"):
            self.assertIn(row, thirteen, row)


class RecordsTest(unittest.TestCase):
    """CHANGELOG-18 (its first task, L-P1E, a line for every item), the register, INDEX and the answers file."""

    def test_the_first_task(self):  # ai_first_task_not_first ai_order_changed ai_l_p1e_not_in_changelog
        text = flat(changelog())
        for words in ("**İlk iş** (`25` 10b).", "Kurucu'nun bugünkü işi sürer, sırası `CHANGELOG-14`'ünkidir.",
                      "Bu dönem P1 çıkışının parçasıdır ve hiçbir yanıtı yeniden yapım istemez",
                      "Raporların teyidi `26l`'nin kuralı olarak kalır, bu listenin bir maddesi değildir.",
                      "**Gevşetme L-P1E** (kapsamlı; sahibe bildirilir; `26j:80`)", "**L-AF1 bitti** (`26n:44-53`)",
                      "Başka gevşetme yok; sıkılaştırma yok.",
                      "P3'ün makine kopyası (`stages/stage1-P3.json`) bu dönemde değildir."):
            self.assertIn(words, text, words)

    def test_every_item_has_its_line(self):  # ai_item_073_dropped ai_item_087_dropped ai_item_unmarked ai_e703_row_dropped
        expected = {f"`{REPORTS[0]}` →": 9, f"`{REPORTS[1]}` →": 13, "E703'ün \"P1 çıkış dönemi\" ertelemeleri": 3}
        for head, count in expected.items():
            with self.subTest(head=head):
                lines = items(head)
                self.assertEqual(len(lines), count, lines)
                for line in lines:
                    self.assertRegex(line, r": (yanıtlandı|ertelendi|reddedildi)", line)
        labels = [line.split(" ", 1)[0] for line in items(f"`{REPORTS[0]}` →")]
        self.assertEqual(labels, ["(a)", "(b)", "(c)", "(d)", "soru", "soru", "soru", "soru", "soru"])
        labels = [line.split(" ", 1)[0] for line in items(f"`{REPORTS[1]}` →")]
        self.assertEqual(labels, ["(a)", "(b)", "(c)", "(d)", "(e)", "(f)", "(g)", "(h)", "(i)", "(ii)", "(iii)",
                                  "update_part_1'in", "(iv)"])
        self.assertIn("(iv) `accept.json` için aşama koruması: yanıtlandı (koruma yok", items(f"`{REPORTS[1]}` →")[12])
        deferrals = items("E703'ün \"P1 çıkış dönemi\" ertelemeleri")
        self.assertIn("ertelendi: Aşama 1 çıkış partisine", deferrals[0])
        self.assertIn("ertelendi: ilk LLM avcısını getiren döneme, en geç Aşama 4 partisi", deferrals[1])
        self.assertIn("reddedildi (`26n:22-25` listenin tanımıdır", deferrals[2])

    def test_the_register_rows(self):
        # ai_rows_open ai_e734_unscoped ai_e696_open ai_e702_open ai_e703_closed ai_e734_risk_dropped
        for eid in ("E733", "E734", "E735", "E696", "E702"):
            with self.subTest(eid=eid):
                self.assertIn("| kapandı (tohum dönemi AI", register_row(eid))
                self.assertEqual(register_row(eid).count("|"), 7, eid)
        self.assertIn("Gevşetme L-P1E", register_row("E734"))
        self.assertIn("Kapsamı P1'dir, P1'in aktarımıyla biter", register_row("E734"))
        for words in ("MF9'un kendi kanıtı canlı rettir (`26j:40-41`) ve bir koruma onu engellemezdi",
                      "erken bir giriş güvenliğe değil MF5'in reddinin kanıtına mal olur"):
            self.assertIn(words, register_row("E734"), words)
        self.assertIn("erken bir giriş güvenliğe değil MF5'in reddinin kanıtına mal olur", flat(changelog()))
        self.assertIn("Sıkılaştırma yok.", register_row("E733"))
        self.assertIn("L-AF1 bitti", register_row("E702"))
        self.assertTrue(register_row("E703").endswith("| açık (operatörün işi, adlı dönemlerde) |"))
        self.assertIn("test 11'in tam yol listesi reddedildi", register_row("E703"))

    def test_the_indexes_and_the_answers(self):  # ai_index_missing ai_changelog_unindexed ai_answers_missing
        index = (ROOT / "spec" / "INDEX.md").read_text(encoding="utf-8")
        for name in ("tohum/26r-semalar-organ-dosyasi.md", "tohum/26s-semalar-p3-tablosu.md", "tohum/CHANGELOG-18.md"):
            self.assertIn(f"| `{name}` |", index)
        self.assertIn("`CHANGELOG-18.md`; başında **İlk iş**.", (TOHUM / "CHANGELOG.md").read_text(encoding="utf-8"))
        answers = json.loads((BOOT / "reports" / "answers.json").read_text(encoding="utf-8"))["answers"]
        mine = [(a["id"], a["kind"]) for a in answers if a["changelog"] == "CHANGELOG-18"]
        self.assertEqual(mine, [(r, "answered") for r in REPORTS])

    def test_the_pages_fit(self):
        for prefix in ("26r", "26s", "26j", "26e", "26n", "26h", "18a", "24a", "29v"):
            self.assertLessEqual(len(page(prefix).splitlines()), 80, prefix)
        self.assertEqual(len(page("26e").splitlines()), 80)  # appended to line 63: no reference below it moved
        self.assertLessEqual(len(changelog().splitlines()), 80)


if __name__ == "__main__":
    unittest.main()
