"""Seed epoch AM (2026-11-24): the report desk's answer to seed-103 (a revert that ended before its merge) and seed-104
(a candidate id whose branch stands), E745-E749, appended to the end of `07`, `28`, `26p`, `01b` and `26f`; and the
owner's hint E750 (the live loop's health first), appended to the end of `00g`. Each seed
fact is cited `page:line` and each citation is read here, so a cited line that moves turns this red; the brain's facts
are cited at the brain commit the page names (the brain is not read here). Only `spec/tohum` reaches the brain, so each
binding sentence is on a `tohum` page. The trailing comment on a test names the mutants it kills (`local/mutate.py`)."""

import no_real_delays  # noqa: F401  (first: no test waits on a real delay, E751)
import json
import unittest
from pathlib import Path

BOOT = Path(__file__).resolve().parents[1]
ROOT = BOOT.parents[1]
TOHUM = ROOT / "spec" / "tohum"
R103 = "seed-103-a-revert-that-ended-before-its-merge-has-no-rule-for-the-next-cycle-and-no-field-that-shows-it"
R104 = "seed-104-a-candidate-id-whose-branch-stands-from-an-earlier-merge-has-no-rule"


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


def changelog() -> str:
    return (TOHUM / "CHANGELOG-22.md").read_text(encoding="utf-8")


class RevertTakeUpTest(unittest.TestCase):
    """E745, seed-103 (1), (2): the end of `07` and `26f:80`."""

    def test_the_rule_and_each_citation(self):
        # am_103_head_unchecked am_103_29i_miscited am_103_refused_writes am_103_message_compared
        # am_103_closed_revert_ends am_103_green_writes am_103_ref_deleted am_103_field_added am_103_l2_unnamed
        # am_103_l3_unnamed am_103_integration_merges_on
        text = cited("07", 66, 80)
        self.assertTrue(text.startswith("**Yarım kalmış geri alma** (rapor masası uzlaşısı (2026-11-24), seed-103; "
                                        "kurulduğu gibi benimsendi, beyin `af708d9`)."))
        for words in ("Dal `brain/revert/<merge_sha>` yalnız başı tam olarak geri alma commit'iyse devralınır: ağacı ilk "
                      "ebeveynin ağacı, tek ebeveyni merge (`29i:20-23`, `asama-0/09` test 25); o baştan "
                      "`brain/integration`'a açık tek PR onunla devralınır, yoksa biri açılır.",
                      "Başka her şey hiçbir şey yazılmadan `revert_branch_differs` ile reddedilir: kırmızı merge "
                      "`brain/integration`'da kalır, nöbetçisi bitmediği için ondan sonra merge yapılmaz (`26f:20-22`).",
                      "Duran commit'in mesajı ve yazarı karşılaştırılmaz; satırın `cause`'u bu devrin `gate.revert` "
                      "kararıdır (`29j:53-58`).",
                      "Geri alma borçtur: geri almanın birleşmeden kapatılmış PR'ı onu bitirmez, aynı daldan yenisi açılır.",
                      "Nöbetçi kararı geri alma olmayan devir (`green`, `flaky`, `26f:12-15`) duran bir geri almaya hiçbir "
                      "şey yazmaz.",
                      "Dalın adı deneme başına değişmez ve hiçbir ref silinmez (`25a:33`).",
                      "satır `{merge_sha, head_sha}` kalır (`26f:17-18`). Kaç devir ya da gönderim sürdüğü defter olgusu "
                      "değildir: `yaz` işinin satırında ve hedefin geçmişindedir.",
                      "**Gevşetme L-AM2** (sahibe bildirilir): yazarın korumasına okuma yolu `GET commits/<sha>/pulls` "
                      "eklendi, yazma kuralı değişmez.",
                      "**Gevşetme L-AM3** (sahibe bildirilir): yazarın bu devirde yapmadığı duran commit, ağacı ve "
                      "ebeveynleri tam olarak işinki ise devralınır; mesajı karşılaştırılmaz."):
            self.assertIn(words, text, words)
        self.assertIn("`revert {repo, merge_sha, onto, ref}`", cited("29i", 20, 23))
        self.assertIn("parents: [onto'nun başı]}", cited("29i", 20, 23))
        self.assertIn("geri alma commit'inin ağacı merge'ün ilk ebeveyninin ağacıdır", flat(
            (ROOT / "spec" / "asama-0" / "09-harness-in-kendi-testleri.md").read_text(encoding="utf-8")))
        self.assertIn("Nöbetçisi bitmemiş merge varken kapı merge etmez", cited("26f", 20, 22))
        self.assertTrue(cited("29j", 53, 58).startswith("`python -m gate.revert cause`"))
        self.assertTrue(cited("26f", 12, 15).startswith("**Nöbetçinin sonu**"))
        self.assertIn("Yazar App'i dal silemez", cited("25a", 33))
        self.assertIn("`payload {merge_sha, head_sha}`", cited("26f", 17, 18))
        self.assertTrue(cited("07", 45, 48).startswith("**Geri almayı hakem yapar.**"))

    def test_26f_points_to_07_in_one_line(self):  # am_26f_pointer_dropped
        lines = page("26f").splitlines()
        self.assertEqual(len(lines), 80)
        self.assertEqual(lines[79], 'Bir geri almanın kaç devirde ya da gönderimde bittiği bu satırlarda değildir: `07` '
                                    '"Yarım kalmış geri alma" (seed-103).')


class FailedWriteTest(unittest.TestCase):
    """E745 and E747, seed-103 (3): the end of `28`."""

    def test_an_interruption_not_a_hard_stop(self):
        # am_103_hard_stop am_103_kept am_103_job_word_hard_stop am_103_activation_dropped am_103_l1_unnamed
        # am_103_28_miscited am_103_first_write_excluded
        text = cited("28", 51, 60)
        for words in ("Bir `yaz` işinde hedefe başarısız olan bir GitHub yazımı (ilk yazımı da, sonrakiler de) bu "
                      "sayfanın sert duruşu değildir: tetikleri (`28:35-38`, `26i:24-25`'in kapalı kümesi) değişmez ve onu saymaz.",
                      "`28:19-20`'nin HTTP 429'u gibi bir kesintidir: iş biter ve hiçbir şey tutmaz (satır yok, "
                      "`status.md` duruşu yok, operatör adımı yok)",
                      "`yaz` işinin satırı bu sonu `hard_stop`'tan ayrı bir adla adlandırır; `hard_stop` yalnız bu "
                      "sayfanın sert duruşunu adlandırır (`26i:24`).",
                      "genesis devrinde başarısız yazım `activation`'dır (`28:37`, `25a` satır 7)",
                      "hedefe yazdıktan sonra kırmızı biten koşu yeniden tetiklenmez (`25a:44-46`)",
                      "P1'den önce `çek`'in zincir kırığı reddi (`13:56-57`) olduğu gibidir.",
                      "**Gevşetme L-AM1** (sahibe bildirilir): iki okumanın gevşeğidir; başarısız yazım operatör adımı "
                      "istemez."):
            self.assertIn(words, text, words)
        self.assertTrue(cited("28", 35, 38).startswith("- **Tetik:** bir pencerede"))
        self.assertIn("(HTTP 429) dondurma değil kesintidir", cited("28", 19, 20))
        self.assertIn("etkinleştirme ya da aktarım hatası (`25a`)", cited("28", 37))
        self.assertIn("`kind: hard_stop`, `payload {trigger, evidence}`", cited("26i", 24))
        self.assertIn("`kill_switch`}", cited("26i", 24, 25))
        self.assertIn("yeniden tetiklenmez", cited("25a", 44, 46))
        self.assertIn("ondan önce `çek` kırık bulursa döngüyü `hard_stop` ile reddeder", cited("13", 56, 57))


class StandingBranchTest(unittest.TestCase):
    """E746, seed-104: the end of `26p` and of `01b`."""

    def test_the_take_up_and_the_single_use_id(self):
        # am_104_branch_differs_ends_cycle am_104_tree_unchecked am_104_check_before_refusal am_104_id_reused
        # am_104_reason_renamed am_104_gate_reason am_104_branch_deleted am_104_26p_miscited
        text = cited("26p", 69, 80)
        for words in ("başı tam olarak bu commit'se (tek ebeveyni taban, ağacı adayın dosyasının tabanınkinde verdiği "
                      "ağaç) açık tek PR'ıyla devralınır, PR yoksa biri açılır.",
                      "Başka her şey PR açılmadan ve check gönderilmeden `branch_differs` ile reddedilir; ret yalnız o "
                      "adayındır, devir sürer (`26k:37-38` T2, `26p:47-48`), devri bitiren bir sert duruş değildir.",
                      "- Aday kimliği hedef başına iki genesis arasında tek merge içindir (kimlik aynı zamanda dalın "
                      "adıdır, `26p:38-39`).",
                      "`yaz` yalnız o kimlik için, kapı devrin merge'ünü seçmeden önce `candidate_id_used` ile reddeder; "
                      "`26p:53-55`'in nedenleri gibi hedef satırında adlandırılır, kapı nedeni ya da `cause` değildir.",
                      "Merge edilmiş adayın dalı silinmez: sonraki genesis'in silmesine kadar durur (`25a:29-33`, insan "
                      "dokunuşu)."):
            self.assertIn(words, text, words)
        self.assertTrue(cited("26k", 37, 38).startswith("- T2: hiçbir adayın içeriği devri kullanılamaz kılmaz."))
        self.assertIn("devir sürer (`26j:58`, `26k` T2)", cited("26p", 47, 48))
        self.assertIn("kimlik aynı zamanda `brain/c/<id>` dalının adıdır", cited("26p", 38, 39))
        self.assertIn("`package_missing` ya da `rerun_missing`", cited("26p", 53, 55))
        self.assertIn("(2) **Silme.**", cited("25a", 29, 33))

    def test_a_closed_pull_request_ends_the_fix(self):
        # am_104_second_pull am_104_revert_pull_ends am_104_cleanup_deletes am_104_01b_miscited am_104_read_unnamed
        text = cited("01b", 75, 80)
        for words in ("Bir düzeltme tek PR'dır (`01b:40-41`): adayın dalından birleşmeden kapatılmış bir PR o düzeltmeyi "
                      "bitirir; aday yalnız o kimlik için, hiçbir şey yazılmadan `pull_closed` ile reddedilir",
                      "Görmek yazarın korumasında kapalı PR'ların bir okumasını ister (yalnız GET; L-AM2, `07`).",
                      "Geri almanın PR'ı düzeltme değildir: kapatılmışı geri almayı bitirmez (`07`).",
                      "`01b:54-55`'in \"temizler\"i silme değildir: sonraki devir duran dalı devralır ya da reddeder, "
                      "hiçbir ref silmez (`25a:33`)."):
            self.assertIn(words, text, words)
        self.assertIn("Her düzeltme kendi `brain/c/<id>` dalından tek PR'dır.", cited("01b", 40, 41))
        self.assertIn("sonraki döngü önce onun aday dallarını ve kiralarını temizler.", cited("01b", 54, 55))


class LiveLoopHintTest(unittest.TestCase):
    """E750: the owner's hint, a duty and not a recipe; the end of `00g`."""

    def test_the_facts_the_duty_and_each_citation(self):
        # am_h_unlabelled am_h_runs_changed am_h_touch_called_a_fix am_h_transfer_fact_dropped am_h_01a_miscited
        # am_h_path_prescribed am_h_session_end_dropped am_h_loosened am_h_not_falsifiable am_h_00g_line_moved
        # am_h_transfer_owner_dropped am_h_order_conflict
        lines = page("00g").splitlines()
        self.assertEqual((lines[63], lines[64], len(lines)), ("  3. Yanlışlanabilir: E739 ve E740 kendi testleriyle; "
                                                             "E741 ve E742 5 oturumdan sonra aynanın ve defterin "
                                                             "sayılarıyla.", "", 80))
        text = cited("00g", 66, 80)
        self.assertTrue(text.startswith("**Sahibin ipucu (bu kez kural esnetildi; 2026-11-24, E750; görev, reçete "
                                        "değil). Canlı döngünün sağlığı önce gelir.**"))
        for words in ("hakem reposunun `loop` koşuları 2026-11-23 21:22Z'den (45268983995) 2026-11-24 10:42Z'ye "
                      "(45377326573) kadar 13 kez kırmızı bitti; `yaz` her birinde `hard_stop` ile bitti",
                      "2026-11-24'te sahip tarafı #162'yi kapattı ve dalını elle sildi: bir kerelik operatör "
                      "dokunuşudur, düzeltme değildir.",
                      "Canlı döngü aktarılmış hakemi koşar; onun ağacı aktarılan pinli SHA'nın `referee/` ağacıdır "
                      "(`01a:56-58`). `referee/` yalnız partilerle değişir (`26j:9-10`); parti, çıkış isteği (A), "
                      "operatör aktarımı ve (B) ile gelir (`02:46-49`, `asama-1/13`).",
                      "Kurulmuş düzeltmelerini canlı döngüye taşıyan yolu sen seçersin (sayfaların adlandırdığı yol "
                      "P1'in çıkış isteğidir) ve her oturumun `session_end` satırında o isteğin önünde neyin durduğunu "
                      "söylersin.",
                      "- Korkuluklar (bu ipucu için): hiçbir gevşetme yok, yeni hakem kuralı yok, bugünkü hiçbir push'u "
                      "kırmızı yapan bir şey yok.",
                      "Yanlışlanabilir: sonraki oturumlar ya P1'in çıkış isteğini yapar ya da onu engelleyeni madde "
                      "madde adlandırır.",
                      "Aktarılmış kodu Kurucu değiştirmez (`01a:60-61`); onu canlı döngüye taşımak aktarımdır."):
            self.assertIn(words, text, words)
        self.assertIn("beyin reposundaki pinli SHA'nın `referee/` ağacıyla aynı olmalıdır", cited("01a", 56, 58))
        self.assertIn("`referee/` yalnız partilerle değişir", cited("26j", 9, 10))
        self.assertIn("aktarılmış kodun değişikliğini şerit yazarı yazar (`29`): Kurucu değildir", cited("01a", 60, 61))
        self.assertIn("P1'in çıkış isteği MF1–MF12'nin hepsi bitmeden geçmez", flat(
            (TOHUM / "CHANGELOG-14.md").read_text(encoding="utf-8").splitlines()[9]))
        self.assertIn("Bu öncelik `CHANGELOG-14`'ün iş sırasıyla çelişmez: o sıra P1'in çıkış isteğiyle biter "
                      "(`CHANGELOG-14:10`)", flat(changelog()))
        self.assertTrue(cited("02", 46, 49).startswith("6. **Parti çıkışı.**"))
        self.assertIn("parti çıkış isteği (A), operatör aktarımı", cited("02", 46, 49))
        self.assertEqual([n for n, line in enumerate(lines, 1) if len(line) > 120], [])
        row = register_row("E750")
        for words in ("sahibin ipucu (bu kez kural esnetildi; 2026-11-24, Suderra sahip tarafı; panelsiz;",
                      "Görev, reçete değil", "hiçbir gevşetme yok, yeni hakem kuralı yok"):
            self.assertIn(words, row, words)
        self.assertTrue(row.endswith("| kapandı (tohum dönemi AM; yol Kurucu'nun) |"))
        self.assertIn("Sahibin ipucu (bu kez kural esnetildi; görev, reçete değil; `00g:66-80`)", flat(changelog()))


class PlacementTest(unittest.TestCase):
    def test_appended_only_and_the_pages_fit(self):  # am_07_line_moved am_26p_grown am_28_line_moved
        for prefix, last, total in (("07", "yeniden denenmez. Kredi kök neden başınadır (çakışan hunk ya da aynı sembol).", 80),
                                    ("28", "kuyruğu taşması Gözcü işaretidir: eylemi durdurmaz, şerit yazarına görev yazar.", 60),
                                    ("26p", "- Vektör: MF10–MF12'nin vektör grubu yoktur (`26e`); seed-098 ve seed-099 için "
                                            "vektör reddedildi, testler 56–58 bağlar.", 80),
                                    ("01b", "temiz bir duruştur.", 80)):
            lines = page(prefix).splitlines()
            old = {"07": 64, "28": 49, "26p": 67, "01b": 73}[prefix]
            self.assertTrue(lines[old - 1].endswith(last), prefix)
            self.assertEqual((lines[old], len(lines)), ("", total), prefix)
            self.assertEqual([n for n, line in enumerate(lines[old:], old + 1) if len(line) > 120], [], prefix)
        for p in TOHUM.glob("*.md"):
            self.assertLessEqual(len(p.read_text(encoding="utf-8").splitlines()), 80, p.name)


class RecordsTest(unittest.TestCase):
    def test_the_register_rows(self):
        # e745_open e746_open e747_open e748_open e749_open am_loosening_unnamed_in_register
        for eid, words in (("E745", ("seed-103 (Kurucu raporu)", "`revert_branch_differs`", "(E747, L-AM1)")),
                           ("E746", ("seed-104 (Kurucu raporu)", "`candidate_id_used`", "`pull_closed`", "(E748, L-AM2)")),
                           ("E747", ("Gevşetme L-AM1:", "sahibe bildirilir")),
                           ("E748", ("Gevşetme L-AM2:", "`GET commits/<sha>/pulls`", "kapalı PR'ların okuması")),
                           ("E749", ("Gevşetme L-AM3:", "mesajı ve yazarı karşılaştırılmaz"))):
            row = register_row(eid)
            for w in words:
                self.assertIn(w, row, (eid, w))
            self.assertEqual(row.count("|"), 7, eid)
            self.assertRegex(row, r"\| kapandı \(tohum dönemi AM(; [^)]*)?\) \|$", eid)

    def test_this_entry_opens_with_its_first_task_and_carries_every_item(self):
        # am_first_task_not_first am_order_changed am_103_line_twice am_103_items_dropped am_104_items_dropped
        # am_loosenings_unnamed am_changelog_unindexed am_index_missing am_answers_missing
        entry = flat(changelog().split("\n- 2.2 (2026-11-24, E745–E750", 1)[1])
        self.assertIn("**İlk iş** (`25` 10b). Teslimden itibaren önyükleme hakeminin hiçbir denetimi kırmızı olmaz",
                      entry[:400])
        for words in ("Kurucu'nun bugünkü işi sürer, sırası `CHANGELOG-14`'ünkidir.",
                      "Raporların teyidi `26l`'nin kuralı olarak kalır, bu listenin bir maddesi değildir.",
                      "**Gevşetme L-AM1** (sahibe bildirilir;", "**Gevşetme L-AM2** (sahibe bildirilir;",
                      "**Gevşetme L-AM3** (sahibe bildirilir;", "Başka gevşetme yok."):
            self.assertIn(words, entry, words)
        log = changelog().splitlines()
        for report, labels in ((R103, ["(1)", "(1, başka kural)", "(2)", "(2, alan)", "(3)", "(3, soru)",
                                       "(3, bağımlılık)", "yapım", "(bulunan)"]),
                               (R104, ["(1)", "(2)", "(2, kim ve hangi nedenle)", "(2b)", "(3)", "(3, okuma yolu)",
                                       "soru", "not"])):
            starts = [n for n, line in enumerate(log) if line.strip().startswith(f"`{report}` →")]
            self.assertEqual(len(starts), 1, report)
            items = []
            for line in log[starts[0] + 1:]:
                if line.startswith("  `seed-"):
                    break
                if line.startswith("  - "):
                    items.append(line[4:].split(" ")[0] if not line[4:].startswith("(") else
                                 line[4:line.index(")") + 1])
            self.assertEqual(items, labels, report)
        index = (ROOT / "spec" / "INDEX.md").read_text(encoding="utf-8")
        self.assertIn("| `tohum/CHANGELOG-22.md` | Değişiklik Günlüğü — Tohum, 2.2'nin Yirmi Birinci Kayıtları |", index)
        top = (TOHUM / "CHANGELOG.md").read_text(encoding="utf-8").splitlines()
        mine = [line for line in top if line.startswith("- 2.2 (2026-11-24, E745–E750; tohum dönemi AM,")]
        self.assertEqual(len(mine), 1)
        self.assertTrue(mine[0].endswith("`CHANGELOG-22.md`; başında **İlk iş**."))
        answers = json.loads((BOOT / "reports" / "answers.json").read_text(encoding="utf-8"))["answers"]
        self.assertEqual([(a["id"], a["kind"]) for a in answers if a["changelog"] == "CHANGELOG-22"],
                         [(R103, "answered"), (R104, "answered")])
        self.assertLessEqual(len(log), 80)
        self.assertEqual([n for n, line in enumerate(log, 1) if len(line) > 120], [])


if __name__ == "__main__":
    unittest.main()
