"""Seed epoch Y: answers to the Founder's ten open reports (seed-070, seed-072..079, spec-071), each an interface fact
on a seed page, decided by the independent review panel, the operator on the owner's delegation (seed-072) or the owner
(seed-079, spec-071's spending limits). Only `spec/tohum` reaches the brain, so each answer is on a `tohum` page; the
seed's copy of `asama-1` is aligned and the Founder reconciles its own (E180). The trailing comment on a test names the
mutants it kills (`local/mutate.py`)."""

import json
import re
import unittest
from pathlib import Path

from snowball_bootstrap import secretscan, vectors  # noqa: F401  (vectors: the comparison the vector runs use)

BOOT = Path(__file__).resolve().parents[1]
ROOT = BOOT.parents[1]


def page(prefix: str) -> str:
    found = sorted((ROOT / "spec" / "tohum").glob(f"{prefix}-*.md"))
    assert len(found) == 1, (prefix, found)
    return found[0].read_text(encoding="utf-8")


def flat(text: str) -> str:
    return " ".join(text.split())


def lines(prefix: str, first: int, last: int) -> str:
    return flat(" ".join(page(prefix).splitlines()[first - 1:last]))


def changelogs() -> str:
    return flat("\n".join(p.read_text(encoding="utf-8") for p in sorted((ROOT / "spec" / "tohum").glob("CHANGELOG*.md"))))


def register_row(eid: str) -> str:
    rows = (ROOT / "docs" / "eksik-kaydi.md").read_text(encoding="utf-8").splitlines()
    return next(line for line in rows if line.startswith(f"| {eid} |"))


class LoopRunsUnitTest(unittest.TestCase):
    def test_29y_says_the_unit_is_the_string(self):  # seed070_unit_unsaid
        text = lines("29y", 43, 45)
        self.assertIn("Birim dizedir (bağımsız inceleme ekibi kararı, 2026-11-20, seed-070): çok satırlı bir metin tek "
                      "dize olarak yazılırsa adı taşıyan tek satırı bütün dizeyi gizler; çok satırlı içerik ayrı dizeler "
                      "olarak yazılır.", text)

    def test_the_launcher_hides_string_by_string(self):
        """What the page says is what `loop_shown` does: in a list of lines only the naming one is hashed."""
        from test_founder_capsule import load_launch
        launch = load_launch()
        names = launch.target_names((launch.config.target({
            "id": "copy", "repo": "o/r", "kind": "copy", "base_sha": None, "identifiers": ["Zorbalix"],
            "excluded_paths": [], "unit_candidates": []}, "t"),))
        shown = launch.loop_shown({"output": ["lint exited 2", "cannot find package zorbalix-ui"]}, names)
        self.assertEqual(shown["output"][0], "lint exited 2")
        self.assertRegex(shown["output"][1], r"^sha256:[0-9a-f]{16}$")
        whole = launch.loop_shown({"output": "lint exited 2\ncannot find package zorbalix-ui"}, names)
        self.assertRegex(whole["output"], r"^sha256:[0-9a-f]{16}$")  # one string: all of it is hidden


class HunterTest(unittest.TestCase):
    """seed-072: no tool-using run-time hunter in Stage 1; it comes with the first tool-using run-time agent."""

    def test_30f_and_the_pages_that_named_p2(self):  # hunter_back_in_stage_1
        self.assertIn("**Ne zaman gelir** (bağımsız inceleme ekibi kararı, 2026-11-20, seed-072): çalışma zamanında "
                      "araç kullanan ilk ajanla, en geç Aşama 4'te; Aşama 1'de koşmaz.", lines("30f", 9, 13))
        self.assertIn("sahibin saldırgan test seti (E648, `00c`) ve salt okunur inceleme (rakip, `29`) gözler",
                      lines("30f", 9, 13))
        self.assertIn("Aşama 1'de bunu P2'nin güvenlik profili (`30d`) yapar", lines("03", 46, 49))
        self.assertIn("ajan en geç Aşama 4'tedir; hakemin güvenlik avcısı (`30f`) ve dispatch kanaryası (test 22) "
                      "onunla gelir", lines("08", 60, 61))
        self.assertIn("güvenlik avcısı araç kullanan ilk çalışma-zamanı ajanıyla gelir", lines("09", 35, 36))
        for prefix in ("30f", "03", "08", "09", "26e"):
            self.assertNotRegex(flat(page(prefix)), r"P2 (partisiyle|aktarımında|aktarımından)", prefix)
        self.assertNotIn("P2'nin güvenlik avcısı", flat(page("09")))
        stage1 = (ROOT / "spec" / "asama-1")
        self.assertIn("Aşama 1'de yok", (stage1 / "04-roller.md").read_text(encoding="utf-8"))
        self.assertNotIn("| P2 | 2 |", (stage1 / "13-aktarim-partileri.md").read_text(encoding="utf-8"))
        table = json.loads((BOOT / "stages" / "stage1-P2.json").read_text(encoding="utf-8"))
        self.assertEqual([f["mf"] for f in table["mfs"]], [1])
        self.assertIn("sahibin devrettiği karar", register_row("E656"))


class StageOneInterfaceTest(unittest.TestCase):
    """seed-073..077: P1's interface facts on `26e`."""

    def section(self, title):
        text = flat(page("26e"))
        return text.split(f"**{title}**", 1)[1].split(" - **", 1)[0]

    def test_organ_hash(self):  # organ_hash_partial
        self.assertIn("organın okuyabildiği her beyin dosyasını kapsar; hakemde tek bir hash fonksiyonu vardır ve her "
                      "organ onu kullanır; LLM organı ayrıca prompt'unu, modelini ve araçlarını hash'e katar",
                      self.section("Organ tanımının hash'i"))
        self.assertIn("prompt hash + model + araç yüzeyi", flat(page("11")))

    def test_snapshot(self):  # placeholder_reveals_kind
        text = self.section("Snapshot")
        for words in ("yer tutucu snapshot'ın türünü (temiz ya da ekilmiş) ele vermez",
                      "Vaka listesi `26`'nın `case` şemasıdır", "Boş `finding_id_patterns` geçerlidir",
                      "\"Yorum satırı\"nın tanımı ertelenmiştir: bu tohum onu henüz tanımlamaz"):
            self.assertIn(words, text, words)
        self.assertIn("**case**: `case_id`", page("26"))

    def test_dev_cases(self):  # cases_rewritten_each_cycle
        text = self.section("Dev vaka seti")
        for words in ("`<state_root>/cases/`'e bir kez yazılır ve yalnız sonuna eklenir",
                      "değiştirilen dosyaya en yakın, paket manifesti taşıyan dizindir; öyle bir dizin yoksa birimin "
                      "köküdür (bu bir sıkılaştırmadır)", "Vakanın ihlal kuralı operatörün hedeflediği kuraldır",
                      "Döngü başına önerilen vaka sayısı Kurucu'nun seçimidir",
                      "inceleyicilerden biri sabit bir sayı istedi, muhalefet kayıtlıdır"):
            self.assertIn(words, text, words)

    def test_scoring(self):
        text = self.section("Puanlama")
        for words in ("test 6, bulgunun bir `evidence_refs` yolu snapshot manifestinde yoksa ya da o yolun baytlarının "
                      "hash'i manifesttekine uymuyorsa", "`rules_total` hedefin `census` vektörünün kural "
                      "kümesidir (`29za:9-22`, `26q`)", "yarım yukarı yuvarlar (`29a`)", "İmza `26a`'dadır",
                      "okunması zorunlu yollardır"):
            self.assertIn(words, text, words)
        row = next(line for line in page("26a").splitlines() if line.startswith("| `harness.score` |"))
        self.assertIn("bulgu ve vaka dosyaları; rapor için snapshot belgesi ve ağacı (`--snapshot`, `--tree`)", row)
        self.assertIn("iki dosyayla `{hits}` (`29a`); dördüyle harness raporu (`26b`)", row)

    def test_the_vector_comparison_rounds_half_up(self):  # vector_rounding_cuts
        """seed-076 (c): 0.962351 is (60, 60, 0.10)'s bound to six places; compared at the table's four it is 0,9624."""
        self.assertEqual(vectors._rounded("0.962351", "0.9624"), "0.9624")
        self.assertEqual(vectors._rounded("0.95005", "0.9501"), "0.9501")
        self.assertEqual(vectors._rounded("0.94995", "0.9500"), "0.9500")
        text = flat(page("29a"))
        self.assertIn("karşılaştırma çıktıyı tablodaki basamak sayısına yarım yukarı yuvarlayarak yapılır (seed-076)", text)
        self.assertIn("`python -m harness.stats cp_lower 60 60 0.10` → `{\"lb\": \"0.962351\"}`", text)
        self.assertIn("| (60, 60) | 0,9624 |", page("29a"))

    def test_test_9(self):  # test9_client_widened
        text = self.section("Test 9")
        for words in ("harness, `referee/harness/` paketi ve onun import kapanışıdır",
                      "model istemcisi `dispatcher/llm_call`'dur", "ağı `koş` kapatır",
                      "Test 11'in sözü (`01a`'nın boş oyuncak reposu, sıfırdan büyüyen `<state_root>`) gevşetilmez"):
            self.assertIn(words, text, words)
        frozen = (ROOT / "spec" / "asama-0" / "09-harness-in-kendi-testleri.md").read_text(encoding="utf-8")
        self.assertIn("| 11 | Genellik: oyuncak repoda `<state_root>` sıfırdan büyür.", frozen)  # unchanged


class ChainNamingTest(unittest.TestCase):
    """seed-078 and seed-079 on `13`, `26f`, `26d` and `29m`."""

    def test_the_naming_row_and_stage_0(self):  # revert_payload_head_dropped no_watcher_writes
        text = lines("13", 51, 58)
        for words in ("merge satırının `merge_sha`'sı, geri alma satırının `head_sha`'sı (`26d`, `26f`) ya da hedefin "
                      "ilk merge'ünden önce kesim satırının `base_sha`'sı",
                      "Gözcü P1'le gelir; ondan önce `çek` kırık bulursa döngüyü `hard_stop` ile reddeder ve hiçbir şey "
                      "yazmaz"):
            self.assertIn(words, text, words)
        self.assertIn("`payload {merge_sha, head_sha}`; aynı satır biçimi", flat(page("26f")))
        self.assertIn("**Geri almanın `head_sha`'sı** (bağımsız inceleme ekibi kararı, 2026-11-20, seed-078): geri "
                      "almanın merge'ünün `brain/integration`'da bıraktığı baştır", flat(page("26f")))
        self.assertIn("- **Merge satırı**: `kind: merge`; `payload` en az `merge_sha`'yı", page("26d"))

    def test_the_sign_count_is_per_job(self):  # sign_count_per_root
        text = lines("13", 59, 62)
        self.assertIn("Sayaç iş başınadır (sahip kararı, 2026-11-20, seed-079: \"İş başına 3 kalsın\"): işin bütün "
                      "hedeflerinin kök imzaları aynı üç çağrıyı paylaşır; çağrı imzalama (`sign`) koşusudur, imzanın "
                      "doğrulama (`verify`) koşusu sayılmaz.", text)
        self.assertIn("sahip kararı (2026-11-20, \"İş başına 3 kalsın\")", register_row("E663"))


class BudgetKeysTest(unittest.TestCase):
    """spec-071: Stage 1's thresholds and budgets have their keys in `18a`; each budget key is compared with the
    monthly cap alone."""

    def test_18a_names_the_keys_and_values(self):  # spending_limit_low
        text = flat(page("18a"))
        for words in ("| `constitutional.stage_params.fix_acceptance_min`, `live_merge_min` | 0,80",
                      "| `constitutional.stage_budgets.asama_1.rival_usd`, `founder_usd`, `runtime_llm_usd` | Her biri "
                      "10.000 USD",
                      "| `constitutional.monthly_cap_usd` | 10.000 USD",
                      "`rival_usd` 2026-11-19'dan beri 10.000'dir (hakem `33c01cb`",
                      "koşu başına rakip tavanı 3 USD kalır", "Aşama 1'de yoktur (`30f`)"):
            self.assertIn(words, text, words)
        fixture = json.loads((BOOT / "vectors" / "policy" / "policy.json").read_text(encoding="utf-8"))
        const = fixture["constitutional"]
        self.assertTrue({"fix_acceptance_min", "live_merge_min"} <= set(const["stage_params"]))
        self.assertTrue({"founder_usd", "runtime_llm_usd"} <= set(const["stage_budgets"]["asama_1"]))
        self.assertNotIn("security_hunter_usd", const["stage_budgets"]["asama_1"])

    def test_02_compares_each_key_with_the_cap(self):  # budget_compared_as_sum
        self.assertIn("- bütçenin her anahtarı tek başına `monthly_cap_usd`'nin altında ya da ona eşit, toplamları değil "
                      "(spec-071);", flat(page("02")))


class WeakPointHintsTest(unittest.TestCase):
    """The owner's hints of 2026-11-20 (E665-E667, "zayıf noktaları kapatalım"), labelled hints, text only, in `00d`."""

    def hint(self, eid, title):
        return flat(page("00d")).split(f"**Sahibin ipucu (2026-11-20, {eid}; ipucu, reçete değil). {title}**", 1)[1] \
            .split("**Sahibin ipucu", 1)[0]

    def test_a_batch_item_may_be_wrong_in_purpose(self):  # batch_purpose_hint_unlabelled
        text = self.hint("E665", "Partiler amaçta da yanlış olabilir.")
        for words in ("hiçbiri bir maddenin aşamasının amacına hizmet edip etmediğini sormadı",
                      "kanıtıyla ve bir öneriyle (çıkar, yeniden sırala, birleştir ya da ekle) bir `spec_issue` raporu "
                      "yaz (`26c`)", "Yanıtı operatör verir", "rapor bir izin değildir"):
            self.assertIn(words, text, words)
        kinds = re.search(r"\*\*reports/\*\.json\*\* \(beyin\): `\{id, kind: ([a-z_|]+),", flat(page("26c"))).group(1)
        self.assertIn("spec_issue", kinds.split("|"))  # the kind the hint names is the report schema's

    def test_a_lost_session_is_explained(self):  # lost_session_hint_unlabelled
        text = self.hint("E666", "Kaybolan oturum açıklanacak bir olgudur.")
        for words in ("20261120T011313Z oturumu 137 çıkış koduyla bitti", "nedeni okuyabildiğin kanıttan bul",
                      "yeniden sınamasıyla bir ders olarak yaz (`26g`); dışındaysa bir rapor yaz"):
            self.assertIn(words, text, words)

    def test_agents_or_a_falsifiable_reason(self):  # agents_hint_unlabelled
        text = self.hint("E667", "Ajanlar.")
        for words in ("E643 ajan istedi (`00b`)", "`delegation` sayısı 0'dır", "ya ilk ajanı tanımla",
                      "yanlışlanabilir bir koşulla kaydet"):
            self.assertIn(words, text, words)
        for eid in ("E665", "E666", "E667"):
            self.assertIn("sahip kararı, ipucu (2026-11-20, \"zayıf noktaları kapatalım\"", register_row(eid))


class DriftBaselineTest(unittest.TestCase):
    """seed-080 (independent review panel, 2026-11-20): `01c` gives `drift.check` its reads and its baseline."""

    def test_01c_states_the_reads_the_baseline_and_the_window(self):  # drift_stale_hard_stop drift_kind_read_as_copy
        text = flat(page("01c"))
        for words in ("Hash yalnız etkin kural içeriğini kapsar; `updated_at`, `_links` ya da kimin okuduğuna bağlı "
                      "alanlar asla girmez", "anayasal politikanın, vektör ağacının ve koltukların hash'leri",
                      "kullanıcıya ait bir repoda bunun REST okuması yoktur",
                      "`operator_checked_at` 7 günden eskiyse döngü sert duruşla değil, temiz bir duruşla biter",
                      "Üst düzeydedir, asla `targets[]`'in içinde değildir",
                      "`targets.<id>.{rulesets: [kimlik], rules: {<dal>: etkin kural içeriğinin sha256'sı}}`",
                      "`activity: {operator_logins: [login], not_before: ISO-8601 UTC}`",
                      "`hashes: {constitutional_sha256, vectors_sha256 (ağaç hash'i), seats_sha256}`",
                      "`visibility: {<repo>: public|private}`", "`operator_checked_at: ISO-8601 UTC`",
                      "`GET /repos/{r}/activity?per_page=100`, süzgeçsiz",
                      "başlangıç satırının `ts`'sinden 10 dakika öncesinin geç olanından başlar",
                      "dal silemez, force-push yapamaz", "`operator_logins` yalnız dal siler",
                      "`null` aktör ya da başka bir login döngüyü durdurur",
                      "ve asla `copy` diye okunmaz"):
            self.assertIn(words, text, words)
        for dropped in ("`apps[]` (hiçbir okuma onu karşılaştıramaz)", "`referee_workflow_permission` (o denetim"):
            self.assertIn(dropped, text)
        self.assertNotIn("app_scope", text)

    def test_the_facts_01c_leans_on(self):
        from snowball_bootstrap import config
        self.assertEqual(config.TARGET_KINDS, ("toy", "copy"))  # "toy ve copy dışındaki tür kullanılamaz girdidir"
        self.assertIn("`policy_sha256`", flat(page("29o")))  # why the policy key is constitutional_sha256
        self.assertIn("`targets[]` `{id, repo, kind: toy|copy,", flat(page("26c")))
        self.assertIn("`drift` (üst düzey, `targets[]`'in içinde değil): `drift.check`'in tabanı, biçimi `01c`'dedir",
                      flat(page("26c")))
        self.assertIn("ve operatörün dönemsel denetimi `01c`'dedir (bağımsız inceleme ekibi kararı, 2026-11-20, "
                      "seed-080)", flat(page("01b")))
        self.assertIn("`01c`", next(l for l in page("00b").splitlines() if l.startswith("| Hakem bileşeni yazma")))
        self.assertIn("bağımsız inceleme ekibi kararı (2026-11-20", register_row("E668"))


class CensusDenominatorTest(unittest.TestCase):
    """The owner's constitutional decision of 2026-11-20: the K0 census denominator is the seed's `census` vector, not
    the Founder's catalog; a catalog that drops a vector rule is red."""

    TOY_RULES = ["dot-notation", "no-var", "object-shorthand", "operator-assignment", "prefer-const", "prefer-template",
                 "yoda"]  # textkit/eslint.config.js of the toy target at de5b57c

    @classmethod
    def setUpClass(cls):
        cls.group = json.loads((BOOT / "vectors" / "vectors.json").read_text(encoding="utf-8"))["census"]

    def test_the_vector_is_the_toys_enabled_rules(self):  # census_vector_drops_a_rule
        group = self.group
        self.assertEqual((group["owner"], group["runner"], group["interface"]),
                         ("asama-1-cikis", "data", "spec/tohum/29za-vektor-arayuzleri-asama-1-cikisi.md"))
        rules = [case["cmd"].split()[-1] for case in group["cases"]]
        self.assertEqual(sorted(rules), self.TOY_RULES)
        for case in group["cases"]:
            self.assertEqual(case["cmd"], f"python -m cases.build produce eslint {case['cmd'].split()[-1]}")
            self.assertEqual(case["expect"], {"producible": True})
            self.assertEqual(case["changed"]["expect_not"], {"producible": True})
            self.assertTrue(case["changed"]["cmd"].endswith(" no-such-rule"))
        from snowball_bootstrap import stages
        tables = [stages.load(0)] + [stages.load(1, done=stages.BATCHES[1][:i]) for i in range(len(stages.BATCHES[1]))]
        self.assertFalse(any("census" in f.groups for t in tables for f in t.mfs))  # the exit batch's table runs it

    def test_a_catalog_that_drops_a_rule_is_red(self):
        class Run:
            def __init__(self, producible):
                self.producible, self.results = producible, []

            def call(self, cmd, stdin=b""):
                return {"producible": cmd.split()[-1] in self.producible}

            def record(self, name, ok, detail=""):
                self.results.append((name, ok))

        whole = Run(set(self.TOY_RULES))
        vectors._data(whole, self.group)
        self.assertTrue(all(ok for _name, ok in whole.results))
        thin = Run(set(self.TOY_RULES) - {"yoda"})
        vectors._data(thin, self.group)
        self.assertEqual([name for name, ok in thin.results if not ok], ["census.yoda"])

    def test_29za_fixes_the_denominator_on_the_referee_side(self):  # census_drop_shrinks_denominator
        text = flat(page("29za"))
        for words in ("**K0 sayımının paydası hakemin tarafında sabittir** (sahip kararı, anayasal, 2026-11-20)",
                      "Kurucu'nun mutasyon kataloğu değil, tohumun `census` vektör grubunun kural kümesidir",
                      "vektördeki bir kuralı düşüren katalog daha küçük bir payda değil, kırmızı bir nedendir",
                      "`exit.sample` ve `cases.build` tek bir mutasyon operatörü kütüphanesini paylaşır",
                      "Test 27'nin tanımı (`asama-0/09`, donmuş tablo) böyle okunur"):
            self.assertIn(words, text, words)
        self.assertIn("paydası hedefin tohumdaki `census` vektörü, oyuncağınki var, kopyanınki operatörün açık işi",
                      flat(page("26a")))
        self.assertIn("`produce <araç> <kural>` (`29za`)",
                      next(l for l in page("26a").splitlines() if l.startswith("| `cases.build` |")))
        self.assertIn("sahip kararı (anayasal", register_row("E669"))


class AdversarialExitRowTest(unittest.TestCase):
    """The owner's constitutional decision of 2026-11-20: E648's adversarial set is a Stage 1 exit row, the exit cannot
    pass without it, and the exit batch's snapshot canary moves to Stage 4."""

    def test_29za_names_the_row_its_test_and_its_weight(self):  # adversarial_not_required
        text = flat(page("29za")).split("**Saldırgan set: `exit.adversarial`**", 1)[1]
        for words in ("(sahip kararı, anayasal, 2026-11-20; E648'in sahip şartının parti satırı)",
                      "düzeltici istemi (hedef dosyalara gömülü prompt injection), diff denetiminden kaçmaya çalışan "
                      "diff'ler ve gizlenmiş ya da kodlanmış sırlar", "Testi 54'tür",
                      "Aşama 1 çıkışı `exit.adversarial` yeşil olmadan geçmez",
                      "snapshot kanaryası (test 16) Aşama 4'e taşınır"):
            self.assertIn(words, text, words)
        frozen = (ROOT / "spec" / "asama-0" / "09-harness-in-kendi-testleri.md").read_text(encoding="utf-8")
        numbered = [int(n) for n in re.findall(r"^\| (\d+) \|", frozen, re.M)]
        self.assertEqual(max(numbered), 52)  # 53 is 30d's, 54 is this row's: neither is reused
        self.assertIn("devamı olarak 53", flat(page("30d")))
        stage4 = next((ROOT / "spec" / "asama-4").glob("13-*.md")).read_text(encoding="utf-8")
        self.assertIn("Snapshot kanaryası", stage4)
        row = next(l for l in page("26a").splitlines() if l.startswith("| `exit.adversarial` |"))
        self.assertIn("Aşama 1 çıkışı (`29za`, test 54)", row)
        self.assertIn("`exit.adversarial` 54; `29za`", flat(page("26e")))
        stage1 = (ROOT / "spec" / "asama-1" / "13-aktarim-partileri.md").read_text(encoding="utf-8")
        self.assertIn("| Aşama 1 çıkışı | 3 | `exit.adversarial`", stage1)
        self.assertNotIn("ve snapshot kanaryası | 27, 16 |", stage1)
        self.assertIn("sahip kararı (anayasal", register_row("E670"))


class ReviewFixesTest(unittest.TestCase):
    """The adversarial review of epoch Y (2026-11-20): the census is the toy's, the copy's vector is the operator's open
    item; producible alone is not a case; no drift is unusable with one reading; the pages no longer put agent.dispatch
    in P2 nor the snapshot canary in the Stage 1 exit; the budget loosening and the delivery values are recorded."""

    def test_the_census_is_scoped_to_the_toy_and_the_copy_waits_for_its_vector(self):
        # census_copy_from_toy
        text = flat(page("29za"))
        for words in ("Oyuncak hedefte kural sayımının paydası",
                      "Çıkışta `producible` cevabı tek başına yetmez, o Kurucu'nun kendi cevabıdır: vektörün her kuralının "
                      "en az bir geçerli `asama-1/13a` vakası olmalıdır",
                      "**Kopya hedefin vektörü** (operatör kararı, 2026-11-20)",
                      "kopyanın sabitlenmiş `base_sha`'sındaki etkin ESLint kural kümesidir",
                      "her birim üzerinde `eslint --print-config` ile üretir ve tohum vektörü olarak commit'ler",
                      "O vektör var olana kadar kopyanın sayımı Aşama 1 çıkışını geçemez",
                      "asla Kurucu'nun kataloğu değildir, asla oyuncağın yedi kuralı da değildir"):
            self.assertIn(words, text, words)
        self.assertTrue(register_row("E671").endswith("| açık (operatörün işi) |"))

    def test_a_summary_without_drift_has_one_reading(self):  # drift_missing_falls_back
        text = flat(page("01c"))
        self.assertIn("`drift`'siz bir özet kullanılamaz girdidir ve döngü durur; `drift.check` bugünkü nedenlerine asla "
                      "geri düşmez.", text)
        self.assertNotIn("taban olarak kalır", text)

    def test_the_pages_agree_with_e656_and_e670(self):
        row = next(l for l in page("26a").splitlines() if l.startswith("| `agent.dispatch` |"))
        self.assertTrue(row.endswith("| Araç kullanan ilk çalışma-zamanı ajanı, en geç Aşama 4 (`30f`) |"))
        work = flat(page("24"))
        self.assertIn("`agent.dispatch`'i araç kullanan ilk çalışma-zamanı ajanıyla, en geç Aşama 4'te gelir", work)
        self.assertIn("`exit.sample`, `spec.lint`, `exit.adversarial` (Aşama 1 çıkışı)", work)
        self.assertNotIn("`agent.dispatch`, `security.*` (P2)", work)
        snapshot = (ROOT / "spec" / "asama-1" / "13c-snapshot-uretimi.md").read_text(encoding="utf-8")
        self.assertIn("snapshot kanaryası Aşama 4'e taşındı", flat(snapshot))
        for prefix in ("24", "26a", "30f", "03", "08", "09"):
            self.assertNotIn("P2 partisiyle", flat(page(prefix)), prefix)

    def test_13_no_longer_leaves_the_toys_first_comparison_point_open(self):
        # Y left it open (`29o`); seed epoch AF names it (seed-093, `test_panel_epoch_af`)
        self.assertNotIn("karşılaştırma noktası henüz adlandırılmamıştır", flat(page("13")))

    def test_the_budget_loosening_and_the_delivery_values_are_recorded(self):
        row = register_row("E664")
        for words in ("sahibin bütçe kararından çıkan adı konmuş bir gevşetmedir",
                      "`stage_budgets.asama_1.founder_usd` 10000, `stage_budgets.asama_1.runtime_llm_usd` 10000, "
                      "`stage_params.fix_acceptance_min` 0,80 ve `stage_params.live_merge_min` 10 yazar",
                      "(hakem commit'i: 0aa2bad;"):
            self.assertIn(words, row, words)
        for eid in ("E669", "E670"):
            self.assertIsNone(re.search(r"Opus H\d|Sonnet F\d|\(Y6\)", register_row(eid)), eid)

    def test_29v_and_26e_say_the_five_are_required_from_y(self):
        self.assertIn("Y döneminin tesliminden Aşama 1'in beş yolu okunması zorunlu yollardır: beynin politika okuması "
                      "onları adlandırana kadar üzerlerindeki `policy_reads_required_absent` kırmızıdır", flat(page("29v")))
        self.assertIn("anahtarları Y'nin tesliminden okunması zorunlu yollardır: beynin politika okuması onları "
                      "adlandırana kadar üzerlerindeki `policy_reads_required_absent` kırmızıdır (`29v`)",
                      flat(page("26e")))


class RecordsTest(unittest.TestCase):
    def test_every_report_is_named_whole_on_one_line_with_its_lines(self):
        raw = "\n".join(p.read_text(encoding="utf-8") for p in sorted((ROOT / "spec" / "tohum").glob("CHANGELOG*.md")))
        reports = ("seed-070-red-b-on-the-copy-base-lint-cause-not-on-the-line",
                   "seed-072-p2-hunter-tool-using-runtime-agent",
                   "seed-073-organ-definition-layout-and-carriage-unstated",
                   "seed-074-snapshot-case-list-and-comment-lines-unstated",
                   "seed-075-dev-case-store-group-and-validity-edges-unstated",
                   "seed-076-harness-score-inputs-identity-and-policy-keys-unstated",
                   "seed-077-harness-offline-client-network-and-state-growth-unstated",
                   "seed-078-revert-row-does-not-name-its-commit-and-stage-0-has-no-watcher",
                   "seed-079-three-sign-calls-per-yaz-job-or-per-root",
                   "spec-071-asama-1-thresholds-without-policy-keys",
                   "seed-080-drift-check-has-no-recorded-baseline-in-the-summary")
        for report in reports:
            with self.subTest(report=report):
                self.assertTrue(any(f"`{report}` → `" in line for line in raw.splitlines()), report)
        for eid in ("E655", "E657", "E658", "E659", "E660", "E661", "E662"):
            self.assertIn("bağımsız inceleme ekibi kararı (2026-11-20)", register_row(eid))
        for p in (ROOT / "spec" / "tohum").glob("*.md"):
            self.assertLessEqual(len(p.read_text(encoding="utf-8").splitlines()), 80, p.name)
        self.assertIn("`CHANGELOG-9.md`", flat((ROOT / "spec" / "tohum" / "CHANGELOG.md").read_text(encoding="utf-8")))
        self.assertIn("2.2 (2026-11-20, E655–E664", changelogs())
        self.assertFalse(secretscan.scan(changelogs()))


if __name__ == "__main__":
    unittest.main()
