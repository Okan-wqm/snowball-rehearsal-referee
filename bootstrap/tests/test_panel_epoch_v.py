"""Seed epoch V, the first decided by the independent review panel (two reviewers, Opus and Sonnet) with the owner's
decisions of 2026-11-18: the Founder's reports seed-066 (declined, E634), seed-067 (E635), seed-068 (E636-E638) and
seed-069 (E639, E640) as `13`, `28`, `25a`, `29g`, `29j` and the runbook state them, each named by the changelog, the
revert drill's draw (E641, `26f`), the owner's temporary-structures rule (E642, `01`), hint (E643, `00b`) and
model-choice principle (E644, `00b`), and the reference MF5's reading of a bundled package (`29g`). The vectors
themselves run in `test_reference_brain`. The trailing comment on a test names the mutants it kills
(`local/mutate.py`)."""

import no_real_delays  # noqa: F401  (first: no test waits on a real delay, E751)
import base64
import hashlib
import importlib.util
import io
import json
import re
import tarfile
import tempfile
import unittest
from pathlib import Path

BOOT = Path(__file__).resolve().parents[1]
ROOT = BOOT.parents[1]


def page(prefix: str) -> str:
    found = sorted((ROOT / "spec" / "tohum").glob(f"{prefix}-*.md"))
    assert len(found) == 1, (prefix, found)
    return found[0].read_text(encoding="utf-8")


def flat(text: str) -> str:
    return re.sub(r"\s+", " ", text)


def lines(prefix: str, first: int, last: int) -> str:
    return flat(" ".join(page(prefix).splitlines()[first - 1:last]))


class ChainPagesTest(unittest.TestCase):
    def test_13_names_the_integration_head_a_chain_break(self):  # integration_head_break_unsaid
        text = flat(page("13").split("- **Zincir kırığı sert duruştur.**", 1)[1].split("- **Rekor'a yazılamama**", 1)[0])
        for words in ("son imzalı durum satırının adlandırdığı commit'ten başka bir `brain/integration` başı (E637)", "kurcalama kanıtıdır", "Gözcü sert duruş yazar (`28`)",
                      "bu kırığı (B)'de yalnız `25a` Başarısızlık onarır"):
            self.assertIn(words, text, words)

    def test_13_says_when_a_root_cannot_be_written(self):  # sign_calls_unbounded, second_entry_called_a_break
        text = flat(page("13").split("- **Rekor'a yazılamama** (sahip kararı, 2026-11-18, E636).", 1)[1]
                    .split("- **Geçmişe sorgu.**", 1)[0])
        for words in ("başarısız tek çağrısı henüz yazılamama değildir", "bir `yaz` işinde döngü onu en çok 3 kez",
                      "her çağrının sonucu `yaz`'ın çıktısında adlandırılır",
                      "aynı köke aynı kimlikle ikinci bir Rekor girdisi bırakabilir; bu zincir kırığı değildir",
                      "satırın `rekor_uuid`'si kullanılan girdiyi adlandırır",
                      "`29j` `verify` yalnız adlandırılan girdiyi okur",
                      "Hiçbir çağrı başarmazsa Rekor'a yazılamamadır ve sert duruştur"):
            self.assertIn(words, text, words)

    def test_28_points_its_trigger_at_13s_three_calls(self):  # hard_stop_on_one_failed_call
        self.assertIn("Rekor'a (`13`: bir `yaz` işinde üç çağrının hiçbiri başarmadıysa) ya da attestation'a "
                      "yazılamaması", flat(page("28")))

    def test_29j_states_the_second_entry_case(self):  # root_page_drops_the_second_entry_case
        self.assertIn("`verify_second_entry_same_root` ikinci girdi kırık değil.", flat(page("29j")))
        self.assertEqual(len(page("29j").splitlines()), 62)  # on line 30: `29j:59-60` (E631's answer) did not move


class OutagePagesTest(unittest.TestCase):
    def text(self) -> str:
        return flat(page("25a").split("**Dış kesinti** (sahip kararı, 2026-11-17, E633).", 1)[1]
                    .split("**Her yeni", 1)[0])

    def test_25a_retriggers_only_a_run_that_wrote_no_target_ref(self):  # retrigger_after_a_target_write
        for words in ("Yeniden tetik yalnız kırmızı koşu hiçbir hedef ref'i yazmadıysa uygulanır (sahip kararı, "
                      "2026-11-18, E638)", "yazılmış ref'leri adlandıran bir `yaz` sert duruşu",
                      "yeniden tetiklenmez; Başarısızlık uygulanır"):
            self.assertIn(words, self.text(), words)

    def test_25a_counts_an_outage_unusable_input_as_an_outage(self):  # outage_unusable_input_is_brain_logic
        self.assertIn("(bir ret, kesintiden gelmeyen kullanılamaz girdi, böyle bir kesinti olmayan sert duruş; E635)",
                      self.text())

    def test_the_runbook_says_the_same(self):  # runbook_retriggers_after_a_target_write
        runbook = flat((ROOT / "seed" / "founder" / "ETKINLESTIRME.md").read_text(encoding="utf-8"))
        self.assertIn("kırmızı işin kendi çıktısında) ve koşu hiçbir hedef ref'i yazmadıysa, o devir için", runbook)
        self.assertIn("Hedefe yazdıktan sonra kırmızı koşu (yazılmış ref'leri adlandıran `yaz` sert duruşu; E638)",
                      runbook)
        self.assertIn("(bir ret, kesintiden gelmeyen kullanılamaz girdi, kesinti olmayan sert duruş)", runbook)
        self.assertIn("hedefe ref yazmamış bir döngü koşusu önce 7. adımın tek yeniden tetiğini alır", runbook)


class BundledPagesTest(unittest.TestCase):
    def test_29g_states_what_a_bundled_package_is(self):  # bundled_rule_unsaid, bundled_script_not_the_bundlers
        text = flat(page("29g").split("**Gömülü paketler** (seed-069, E639):", 1)[1].split("Çıktı:", 1)[0])
        for words in ("`package/node_modules/` altındaki paket dizinleri", "`bundleDependencies`",
                      "her derinlikte `node_modules/<ad>` ya da `node_modules/@<kapsam>/<ad>`",
                      "bütünlüğü onları kapsar, ayrı girdi değildirler, getirilmezler",
                      "`preinstall`, `install` ya da `postinstall`, ya da dizinde `binding.gyp`",
                      "gömen işaretli değilse `install_script_unmarked:<gömenin kilit yolu>`"):
            self.assertIn(words, text, words)

    def test_29g_records_the_in_bundle_row_as_a_fact(self):  # in_bundle_fact_unsaid
        text = flat(page("29g"))
        self.assertIn("`inBundle: true` taşıyan kilit girdisinin `resolved`'ı yoktur; bugün her girdi gibi "
                      "`registry_not_allowed` ile reddedilir, kabulü ona ihtiyaç duyan bir hedef kilidini bekler", text)
        self.assertIn("(kopyanın üç kilidinde böyle satır yok, 2026-11-18; E640)", text)

    def test_29g_states_both_cases(self):  # npmlock_page_drops_the_bundled_cases
        text = flat(page("29g"))
        self.assertIn("`bundled_install_script_unmarked` gömülü paketin işaretsiz `postinstall`'ı gömenin kilit yoluyla "
                      "ret", text)
        self.assertIn("`bundled_install_script_marked` gömen işaretliyse geçer, içerik adresi yalnız gömenindir, gömülü "
                      "paketin kendi `ad@sürüm`'ü gömeni işaretlemez", text)


class DrillDrawPageTest(unittest.TestCase):
    """E641, the independent panel's decision with the owner's approval: the revert drill's commitment draws from the
    least-planted causes; the key, the commitment, `judge` and the #geri-alma gate do not change."""

    def test_26f_states_the_draw_from_the_least_planted_causes(self):
        # drill_draw_paragraph_removed, drill_draw_from_the_current_ledger, drill_draw_from_the_whole_catalog
        text = flat(page("26f").split("**Taahhüdün kataloğu** (bağımsız inceleme ekibi kararı, sahibin onayı, "
                                       "2026-11-18, E641).", 1)[1])
        for words in ("bütün katalogdan değil, en az ekilmiş nedenlerin örneklerinden çekilir",
                      "son genesis'ten sonra ve taahhüt satırının önündeki ekme satırlarından",
                      "`instance_id`'si katalogda o nedene eşlenenlerin sayısıdır; katalog dışı kimlik hiçbir şey saymaz",
                      "Hiç ekim yoksa her sayı sıfırdır ve çekiliş bugünkü gibidir",
                      "`commit` ve `reveal`'e verilen bu indirgenmiş katalogdur; anahtarın alanları, taahhüt ve `judge` "
                      "değişmez",
                      "o taahhüt satırından önceki satırlardan kurulur, güncel defterden asla",
                      "Kural çekilişi yönlendirir, kapıyı değil: #geri-alma yine her neden için PASS bir prova ister"):
            self.assertIn(words, text, words)

    def test_the_changelog_and_the_register_name_it(self):
        log = flat((ROOT / "spec" / "tohum" / "CHANGELOG.md").read_text(encoding="utf-8"))
        self.assertIn("Bağımsız inceleme ekibi kararı (E641, E544 (2) kapandı): `26f` \"Taahhüdün kataloğu\"", log)
        register = (ROOT / "docs" / "eksik-kaydi.md").read_text(encoding="utf-8").splitlines()
        row = next(line for line in register if line.startswith("| E641 |"))
        self.assertIn("Kabul edilen bedel: sıradaki neden ekimden önce açık defterden çıkarılabilir", row)
        self.assertIn("(2) kapandı (tohum dönemi V, E641", next(line for line in register if line.startswith("| E544 |")))

class TemporaryStructuresPageTest(unittest.TestCase):
    """The owner's decision of 2026-11-18 (E642), text only: what the Founder and its agents build for a job is removed
    when the job ends; evidence, archives and another's work are not temporary structures."""

    def test_01_states_what_is_removed_and_what_stays(self):  # temporary_structures_unsaid
        text = flat(page("01").split("**Geçici yapılar (sahip kararı, 2026-11-18).**", 1)[1].split("**En basit", 1)[0])
        for words in ("geçici olarak kurduklarını", "iş bittiğinde siler",
                      "kabul edildiğinde, bırakıldığında ya da yerine başka bir yol seçildiğinde bitmiş sayılır",
                      "Geriye yalnız repoya kaydedilmiş bilgi kalır", "Süren bir işin dalı iş bitene kadar durur",
                      "gerekçesi defterde kayıtlı olduktan sonra silinir",
                      "(defter satırları, `arsiv/` etiketleri, hakem sonuçları) ve başkasının işi geçici yapı değildir, "
                      "silinmez", "Kalıntılar sistemin ölçülen boyutuna sayılır"):
            self.assertIn(words, text, words)
        self.assertIn("Sahip kararı: `01` \"Geçici yapılar\" (E642)",
                      flat((ROOT / "spec" / "tohum" / "CHANGELOG.md").read_text(encoding="utf-8")))

class OwnerHintPageTest(unittest.TestCase):
    """The owner's hint of 2026-11-18 (E643), an explicit exception to no-feeding, text only: labelled a hint so that
    later measurement can tell hinted from discovered; `01` points at it."""

    def test_00b_carries_the_labelled_hint_and_01_points_at_it(self):  # owner_hint_unlabelled
        text = flat(page("00b").split("**Sahibin ipucu (2026-11-18, E643; ipucu, reçete değil).**", 1)[1])
        for words in ("beslememe kuralının istisnasıdır", "ölçüm ipucuyla bulunanı Kurucu'nun kendi bulduğundan ayırır",
                      "Kurucu (Fable) mimar ve yönetici olarak kalır", "`agents/` dizininde tanımladığı ajanlara verebilir",
                      "`model` alanıyla seçilir (`24a` \"Ajan ve skill tanımları\") ve `sonnet` ya da `opus`'tur",
                      "`haiku` şimdilik kullanılmaz (sahip kararı)", "karar varsayımla değil ölçümle verilir",
                      "Olgu: rakip `opus`'tur", "rakibin bağımsızlığını zayıflatır (`03` K5)",
                      "Sahibin tercihi (ipucu, denetim değil): hakeme giden kodu yazan ajanlar `sonnet`'tir",
                      "`opus` ajanları analiz, inceleme ve planlama içindir"):
            self.assertIn(words, text, words)
        self.assertIn("**Sahibin ipucu** (2026-11-18, E643):", page("01"))
        self.assertIn("`00b`'dedir", page("01"))

class ModelChoicePrinciplePageTest(unittest.TestCase):
    """The owner's principle of 2026-11-19 (E644), text only: a model is chosen by purpose and measured cost per
    accepted result, labelled a principle (not a hint)."""

    def test_00b_states_the_principle(self):  # model_choice_by_token_price, measurement_carried_across_versions
        text = flat(page("00b").split("**Model seçimi amaçla ve ölçümle (sahip ilkesi, 2026-11-19, E644; ilke, ipucu "
                                      "değil).**", 1)[1])
        for words in ("neden çağrıldığını (amacını) ve onu yargılayan kalite denetimini adlandırır",
                      "bazen tekniktir (test, derleme, hakem kararı), bazen kullanıcı deneyimine bağlıdır",
                      "amaç başına, kabul edilmiş sonuç başına ölçülen toplam maliyetle seçilir",
                      "yeniden denemeler, inceleme ve hakem koşuları bu maliyete dahildir", "Token fiyatı ölçü değildir",
                      "100 işin 10'unu, pahalısı 90'ını geçiriyorsa ucuz olan pahalıya gelir",
                      "Yeni bir model çıktı diye görev ona bağlanmaz",
                      "aynı işlerde mevcut modelle ölçülü bir denemeden geçerek girer",
                      "Her ölçüm ve öğrenim kaydı modelin tam sürümünü taşır: model kimliği (ör. `claude-sonnet-5-5`) "
                      "ve effort", "Bir modelin başarısı yalnız o sürüm için geçerlidir",
                      "sürüm değişince eski ölçüm yeni sürüme taşınmaz, yeni sürüm yeniden ölçülür",
                      "defterde sürümüyle birlikte durur",
                      "Bu fikri geliştirmek Snowball'un işidir; ilke yalnız yönü verir"):
            self.assertIn(words, text, words)

class ReadTheImportedResultHintPageTest(unittest.TestCase):
    """The owner's hint of 2026-11-19 (E645), labelled a hint, text only: `çek` reads the imported brain SHA's result."""

    def test_00b_carries_the_labelled_hint(self):  # imported_result_hint_unlabelled
        text = flat(page("00b").split("**Sahibin ipucu (2026-11-19, E645; ipucu, reçete değil).**", 1)[1])
        for words in ("koşu 44094922317, `referee_tree_mismatch`", "en yeni önyükleme sonucunu okuyor",
                      "her (B) boyunca `STOP` koyuyor", "1–1,5 saat boş kalıyor",
                      "`çek` aktarılan beyin SHA'sının sonucunu okusun",
                      "aktarım satırında (`result_sha256`, `26c`) zaten var",
                      "Tasarım Kurucu'nundur ve hakemin denetimini gevşetmez",
                      "çalışan kod yine yalnız kabul edilmiş ve aktarılmış koddur"):
            self.assertIn(words, text, words)
        self.assertIn("result_sha256", flat(page("26c")))

class AdversarialGateHintPageTest(unittest.TestCase):
    """The owner's hint of 2026-11-19 (E648), labelled a hint, text only: before a real product repository the
    gates pass an adversarial set the referee runs; the design is the Founder's."""

    def test_00b_carries_the_labelled_hint(self):  # adversarial_hint_unlabelled adversarial_hint_drops_a_class
        text = flat(page("00b").split("**Sahibin ipucu (2026-11-19, E648; ipucu, reçete değil).**", 1)[1])
        for words in ("bir dosyanın içine yazılmış bir talimat (prompt injection)",
                      "(`30a`) hedefin kendi enjeksiyon açıklarını anlatır, modele yöneleni anlatmaz",
                      "Snowball gerçek ürün reposunda çalışmadan önce, kapılar saldırgan bir test setinden kanıtla",
                      "hedef dosyalara gömülü prompt injection, diff denetiminden kaçmaya çalışan değişiklikler, "
                      "gizlenmiş ya da kodlanmış secret'lar", "Seti hakem koşar", "Tasarım Kurucu'nundur."):
            self.assertIn(words, text, words)
        self.assertNotIn("prompt injection", flat(page("30a")).casefold())
        self.assertLessEqual(len(page("00b").splitlines()), 80)
        logs = sorted((ROOT / "spec" / "tohum").glob("CHANGELOG*.md"))  # wherever the 80-line cap moved it (E651)
        self.assertIn("Sahibin ipucu (E648; ipucu olarak işaretli): `00b`",
                      flat("\n".join(p.read_text(encoding="utf-8") for p in logs)))
        self.assertTrue(all(len(p.read_text(encoding="utf-8").splitlines()) <= 80 for p in logs))
        register = (ROOT / "docs" / "eksik-kaydi.md").read_text(encoding="utf-8").splitlines()
        self.assertIn("sahip kararı, ipucu (2026-11-19",
                      next(line for line in register if line.startswith("| E648 |")))

class LearningAndPreventionHintsPageTest(unittest.TestCase):
    """The owner's hints of 2026-11-19 (E649 learning, E650 prevention and structure), labelled hints, text only, in
    `00c`, where `00b` continues past its 80 lines (`15` 1)."""

    def test_00c_carries_both_labelled_hints_and_00b_points_at_it(self):
        # learning_hint_unlabelled prevention_hint_unlabelled
        text = flat(page("00c"))
        learning = text.split("**Öğrenme (sahibin ipucu, 2026-11-19, E649; ipucu, reçete değil).**", 1)[1]
        for words in ("20 `lesson` satırı var; 9'una sonraki kararlarda adıyla atıf var, 11'ine hiç yok",
                      "Hiçbirinde `scope` yok (`22`", "eski kodu yeni derse göre yeniden okuyan olmadı",
                      "geçerli olduğu iş geldiğinde bulunabilir olmalı", "ondan önce yazılmış kodu da kapsamalı",
                      "`superseded_at` almalı", "model sürümüne bağlı dersler de buna dahil olmalı (E644)"):
            self.assertIn(words, learning, words)
        prevention = text.split("**Önleme ve yapı (sahibin ipucu, 2026-11-19, E650; ipucu, reçete değil).**", 1)[1]
        for words in ("(f1538, f1546, f1553, f1560, f1567); hiçbiri kurulmadı", "`/work/logs/mirror.json`",
                      "`cli`'yı 45 modül içe aktarır, `loop.job` 36 modülü içe aktarır",
                      "`@nx/enforce-module-boundaries`", "en az biri kurulup ölçülsün",
                      "Yapı da ölçülerek sadeleşsin", "hiçbiri sessizce atlanmamalı"):
            self.assertIn(words, prevention, words)
        self.assertIn("(E649 öğrenme, E650 önleme ve yapı) `00c`'dedir", flat(page("00b")))
        self.assertIn("`scope`", flat(page("22")))
        register = (ROOT / "docs" / "eksik-kaydi.md").read_text(encoding="utf-8").splitlines()
        for row in ("| E649 |", "| E650 |"):
            self.assertIn("sahip kararı, ipucu (2026-11-19", next(line for line in register if line.startswith(row)))

class ConsistentGrowthPrinciplePageTest(unittest.TestCase):
    """The owner's principle of 2026-11-19 (E653), labelled a principle, not a hint, text only, before E651 in `00c`."""

    def test_00c_states_the_principle_before_the_mvp_request(self):  # consistent_growth_relabelled_a_hint
        raw = flat(page("00c"))
        head = "**Tutarlı gelişim (sahip ilkesi, 2026-11-19, E653; ilke, ipucu değil).**"
        self.assertLess(raw.index(head), raw.index("E651; ipucu, reçete değil)"))
        text = raw.split(head, 1)[1].split("**Sahibin ipucu (2026-11-19, E651", 1)[0]
        for words in ("kod, hakem, hafıza ve dersler, ajanlar ve skill'ler, araçlar, ölçüm, belgeler",
                      "Yeni bir parça var olanla çelişmez ve onu tekrar etmez", "Aynı işi yapan iki yol bırakılmaz",
                      "Tek doğruluk kaynağı korunur", "Eski kod yeni derse göre yeniden okunur",
                      "Her değişiklik ölçülür ve belgesiyle birlikte gelir",
                      "Tutarsızlık bulunduğunda kayda geçer ve kapatılır; susularak geçilmez."):
            self.assertIn(words, text, words)
        register = (ROOT / "docs" / "eksik-kaydi.md").read_text(encoding="utf-8").splitlines()
        self.assertIn("sahip kararı, ilke (2026-11-19", next(line for line in register if line.startswith("| E653 |")))


class MvpRequestHintPageTest(unittest.TestCase):
    """The owner's hint of 2026-11-19 (E651), labelled a hint, text only: the owner asks for an MVP; what it is, what it
    proves and in which order is the Founder's, written as a proposal for the owner's approval; no recipe."""

    def test_00c_carries_the_labelled_request_and_no_recipe(self):  # mvp_hint_unlabelled
        text = flat(page("00c")).split("**Sahibin ipucu (2026-11-19, E651; ipucu, reçete değil). MVP isteği.**", 1)[1]
        for words in ("dışarıdan değerlendirecek birine göstermek ve yatırım başvurusunda kullanmak için bir MVP",
                      "bir yatırımcı ya da ilk pilot müşteri olabilir",
                      "neyi kanıtlayacağına ve hangi sırayla geleceğine Kurucu karar verir",
                      "ölçülebilir kanıtlarıyla bir öneri olarak yazar", "sahibin onayına gider",
                      "gerçek ürün reposu için sahip şartları (E648)", "merge'ü sahibin yapması",
                      "her merge'ün geri alınabilir olması", "aşama merdiveni ve hakem kuralları",
                      "ölçüm aynasının sayılarıyla izlenebilir"):
            self.assertIn(words, text, words)
        for recipe in ("içermeli", "içermelidir", "şunları", "özellikleri", "demo"):
            self.assertNotIn(recipe, text.casefold(), recipe)
        logs = sorted((ROOT / "spec" / "tohum").glob("CHANGELOG*.md"))
        self.assertIn("2.2 (2026-11-19, E651–E653; sahibin ipuçları ve ilkesi): `00c`. Sahip ilkesi (E653, ilke)",
                      flat("\n".join(p.read_text(encoding="utf-8") for p in logs)))  # wherever the cap moved it
        self.assertTrue(all(len(p.read_text(encoding="utf-8").splitlines()) <= 80 for p in logs))
        self.assertLessEqual(len(page("00c").splitlines()), 80)
        register = (ROOT / "docs" / "eksik-kaydi.md").read_text(encoding="utf-8").splitlines()
        self.assertIn("sahip kararı, ipucu (2026-11-19", next(line for line in register if line.startswith("| E651 |")))

class LearnFromOtherReposHintPageTest(unittest.TestCase):
    """The owner's hint of 2026-11-19 (E652), labelled a hint, text only: memory may also learn from well-known trusted
    open-source projects; the system is the Founder's; the owner's limits are stated."""

    def test_00c_carries_the_labelled_hint_and_its_limits(self):  # other_repos_hint_unlabelled
        text = flat(page("00c")).split(
            "**Sahibin ipucu (2026-11-19, E652; ipucu, reçete değil). Başka repolardan öğrenme.**", 1)[1]
        for words in ("iyi bilinen ve güvenilir açık kaynak projelerden de öğrenebilir",
                      "Bunu yapacak sistemi Kurucu tasarlar: hangi repo, ne okunur, nasıl saklanır, nasıl ölçülür",
                      "genelliği gösterir (`21`)", "okuma salt okunurdur, sürüm commit'e ve hash'e sabitlenir",
                      "Yalnız izin verici lisanslı repolar okunur; kod kopyalanmaz, kalıp ve fikir öğrenilir",
                      "`21a`'daki gibi hipotezdir", "kendi hedefimizde kanıtlanana kadar karar vermez",
                      "E648'in saldırgan test seti bu okumaya da uygulanır",
                      "kabul edilen iş başına maliyet okumalı ve okumasız karşılaştırılır (E644)",
                      "daha küçük ve ucuz modeller Snowball'da çalıştığında onlara yol gösteren hipotezler olsun",
                      "Bilgi modelde değil repoda durur (`01` sahibin hedefi)",
                      "yazıldığı gibi koşan bir kontrolüyle birlikte tutulur (`26g`)",
                      "şirketin kendi `tromso-mvp` reposudur (Python/Django, özel; çiftlik yazılımı)",
                      "operatörün kuracağı özel bir kopyası üzerinden okur ya da onda çalışır",
                      "(`snowball-rehearsal-copy` gibi bir kopya, ama özel)",
                      "Şirketin kendi repoları bu lisans kuralının dışındadır; hakları şirkettedir.",
                      "hakemin bugünkü desteği (npm) yetmez"):
            self.assertIn(words, text, words)
        self.assertTrue(text.lstrip().startswith("- Amaç:"), text[:40])
        # other_repos_compass_made_a_recipe other_repos_criteria_dropped
        for words in ("Kaynak türleri, güçlüden zayıfa. Operatörün önerisi (bağlayıcı değil; Kurucu kabul eder, "
                      "değiştirir ya da reddeder, gerekçesini yazar).",
                      "Amaç, Kurucu'nun kendi öğrenme sistemini kurmasıdır. Bu liste yalnız bir başlangıç önerisidir.",
                      "1. Snowball'un kendi sonuçları: hakem kararları ve dersler",
                      "OSV / GitHub Advisory (açıklı ve düzeltilmiş kod çiftleri)", "(güvenlik, K6)",
                      "(mantık hataları, K5)", "öğrenmekten çok bağımsız sınav olarak kullanılır",
                      "hipotez olarak tutulur, kural olarak değil",
                      "Kaçınılacaklar: rastgele popüler repolar; doğrulanamayan forum veya blog tavsiyeleri",
                      "Seçim ölçütleri: otoriter mi; izin verici lisanslı mı; içinde bir doğrulama (test, kural) taşıyor "
                      "mu; sürümü sabitlenebilir mi; o aşamanın hata sınıfına uygun mu; etkisi ölçülebilir mi."):
            self.assertIn(words, text, words)
        self.assertIn("Mantık hataları", flat(page("03")))
        self.assertNotIn("pusula", text)
        self.assertIn("**İthal bilgi hipotezdir.**", page("21a"))
        self.assertLessEqual(len(page("00c").splitlines()), 80)
        self.assertLessEqual(len((ROOT / "spec" / "tohum" / "CHANGELOG.md").read_text(encoding="utf-8").splitlines()), 80)
        register = (ROOT / "docs" / "eksik-kaydi.md").read_text(encoding="utf-8").splitlines()
        self.assertIn("sahip kararı, ipucu (2026-11-19", next(line for line in register if line.startswith("| E652 |")))

class LessonRecheckHintPageTest(unittest.TestCase):
    """The owner's hint of 2026-11-20 (E654), labelled a hint, text only, in `00d` (`00c` continued): lessons re-checked
    automatically and regularly, the result written back; the design is the Founder's; 26g is unchanged."""

    def test_00d_carries_the_labelled_hint_and_00c_points_at_it(self):  # lesson_recheck_hint_unlabelled
        text = flat(page("00d")).split(
            "**Sahibin ipucu (2026-11-20, E654; ipucu, reçete değil). Derslerin kendiliğinden yeniden sınanması.**", 1)[1]
        for words in ("defterde 26 `lesson` satırı var", "hepsi `trust: inferred`",
                      "hiçbiri bağımsız olarak yeniden koşturulmadı",
                      "`26g` gereği başlatıcı ve hakem `recheck`'i koşturmaz",
                      "sahip ilkesi (2026-11-06) her dersin yeniden sınanan, yanlışlanabilir bir kayıt olmasıdır",
                      "dersler otomatik ve düzenli olarak yeniden sınansın; sonucu derse geri yazılsın",
                      "`closes:` ile kapanma", "Kurucu'nun tasarımıdır", "Kurucu bunu bir rapor olarak önerir",
                      "kaç ders yeniden sınandı, kaçı tuttu, kaçı kapandı"):
            self.assertIn(words, text, words)
        self.assertIn("`recheck`'i koşturmaz", flat(page("26g")))  # the seed's rule the hint does not change
        self.assertIn("(E654'ten başlayarak) `00d`'dedir", flat(page("00c")))
        for prefix in ("00c", "00d"):
            self.assertLessEqual(len(page(prefix).splitlines()), 80)
        log = flat((ROOT / "spec" / "tohum" / "CHANGELOG.md").read_text(encoding="utf-8"))
        self.assertIn("2.2 (2026-11-20, E654; sahibin ipucu): yeni `00d`", log)
        register = (ROOT / "docs" / "eksik-kaydi.md").read_text(encoding="utf-8").splitlines()
        self.assertIn("sahip kararı, ipucu (2026-11-20", next(line for line in register if line.startswith("| E654 |")))


class ReferenceBundledReadingTest(unittest.TestCase):
    """The reference MF5 (`local/reference_brain/referee/runner/deps_npm.py`) reads `29g`'s package directories: a
    scoped one, a nested one, a `binding.gyp`, and not a package.json that only sits deeper in a bundled package."""

    @classmethod
    def setUpClass(cls):
        path = BOOT / "local" / "reference_brain" / "referee" / "runner" / "deps_npm.py"
        spec = importlib.util.spec_from_file_location("reference_deps_npm_v", path)
        cls.mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.mod)

    def fetch(self, members: dict[str, bytes], marks: list[str]) -> dict:
        raw = io.BytesIO()
        with tarfile.open(fileobj=raw, mode="w:gz") as tar:
            for name, data in {"package/package.json": b'{"name": "x", "version": "1.0.0"}', **members}.items():
                info = tarfile.TarInfo(name)
                info.size = len(data)
                tar.addfile(info, io.BytesIO(data))
        tgz = raw.getvalue()
        url = "https://registry.npmjs.org/x/-/x-1.0.0.tgz"
        lock = {"lockfileVersion": 3, "packages": {"": {}, "node_modules/x": {
            "resolved": url, "integrity": "sha512-" + base64.b64encode(hashlib.sha512(tgz).digest()).decode()}}}
        with tempfile.TemporaryDirectory() as mirror:
            target = Path(mirror) / "registry.npmjs.org" / "x" / "-" / "x-1.0.0.tgz"
            target.parent.mkdir(parents=True)
            target.write_bytes(tgz)
            return self.mod.fetch(lock, mirror, {"registry_egress": ["https://registry.npmjs.org/"],
                                                 "install_scripts_required": marks})

    def test_every_package_directory_of_the_bundle_is_read(self):
        # reference_bundled_gyp_ignored, reference_bundled_scope_ignored, reference_bundled_first_level_only
        hook = json.dumps({"name": "y", "version": "1.0.0", "scripts": {"install": "node-gyp rebuild"}}).encode()
        for name, members in (
                ("binding.gyp", {"package/node_modules/y/binding.gyp": b"{}"}),
                ("scoped", {"package/node_modules/@s/y/package.json": hook}),
                ("nested", {"package/node_modules/y/node_modules/@s/z/package.json": hook})):
            with self.subTest(name):
                self.assertEqual(self.fetch(members, [])["rejected"], ["install_script_unmarked:node_modules/x"])
                self.assertTrue(self.fetch(members, ["node_modules/x"])["ok"])

    def test_a_file_deeper_in_a_bundled_package_is_no_package_directory(self):  # reference_bundled_any_depth_file
        hook = json.dumps({"scripts": {"postinstall": "x"}}).encode()
        self.assertTrue(self.fetch({"package/node_modules/y/dist/package.json": hook}, [])["ok"])


class ReportAnswersTest(unittest.TestCase):
    def test_the_changelog_names_each_report_with_the_lines_that_answer_it(self):
        # changelog_drops_seed_066, changelog_drops_seed_067, changelog_drops_seed_068, changelog_drops_seed_069
        raw = (ROOT / "spec" / "tohum" / "CHANGELOG.md").read_text(encoding="utf-8")
        log = flat(raw)
        self.assertIn("bağımsız inceleme ekibi kararı", log)
        self.assertIn("`seed-066-cek-running-tree-unexercised` → declined: `29u:30-33` ve E591", log)
        self.assertIn("SHA'daki `referee/`'nin aktarılandan farklı olması durdurma nedeni değildir",
                      lines("29u", 30, 33))
        says = {"seed-067-loop-outage-and-red-condition-not-separated": ("25a", 41, 49, "kesintiden gelmeyen"),
                "seed-068-one-failed-sign-call-and-the-target-written-before-it": ("13", 56, 64, "en çok 3 kez"),
                "seed-069-bundled-packages-in-a-lock-and-in-a-tarball": ("29g", 31, 37, "**Gömülü paketler**")}
        for report, (prefix, first, last, words) in says.items():
            self.assertIn(f"`{report}` → `{prefix}:{first}-{last}`", log, report)
            self.assertIn(words, lines(prefix, first, last), report)
        self.assertIn("`25a:41-49` (hedefe yazmış koşu yeniden tetiklenmez)", log)
        self.assertIn("hiçbir hedef ref'i yazmadıysa", lines("25a", 41, 49))
        self.assertIn("`29j:30` (E636–E638)", log)
        self.assertIn("`verify_second_entry_same_root`", lines("29j", 30, 30))
        self.assertIn("`29g:60-62`", log)
        self.assertIn("`bundled_install_script_marked`", lines("29g", 60, 62))
        for report in says:  # the launcher reads added lines one by one: each id sits whole on one line
            self.assertTrue(any(report in line for line in raw.splitlines()), report)
        self.assertLessEqual(len(raw.splitlines()), 80)


if __name__ == "__main__":
    unittest.main()
