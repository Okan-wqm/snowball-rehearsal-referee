"""Seed epoch AA (2026-11-21): the report desk's answers to the Founder's reports seed-082 (drift baseline), seed-083
(primary evidence ref, the harness's policy values) and seed-084 (Gözcü), the items of seed-085 that seed-084's answer
already gives, the "first task" convention (the Founder's lesson f1741) and the delivery's recompute of
`drift.hashes.constitutional_sha256` (`test_deliver_epoch`). Only `spec/tohum` reaches the brain, so each binding
sentence is on a `tohum` page; the seed's copy of `asama-1/13d` is aligned. The policy fixtures' number form is in
`test_policyreads`. The trailing comment on a test names the mutants it kills (`local/mutate.py`)."""

import json
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


def key_rows(prefix: str) -> list[str]:
    """The full paths of the first cells of a page's key table, a bare sibling completed from the path before it."""
    paths: list[str] = []
    for line in page(prefix).splitlines():
        if line.startswith("| `"):
            for token in re.findall(r"`([^`]+)`", line.split(" | ")[0]):
                paths.append(token if "." in token else paths[-1].rsplit(".", 1)[0] + "." + token)
    return paths


class GozcuRowsTest(unittest.TestCase):
    """seed-084 and seed-085 (a, h): `26i` gives the `freeze` part's three rows; `freeze` and `lift` are the shapes
    the Founder built in P1 MF7, the `hard_stop` row is the consensus's addition."""

    def test_the_three_rows(self):  # gozcu_hard_stop_row_dropped gozcu_stop_lift_in_loop gozcu_lift_names_no_freeze
        text = flat(page("26i"))
        for words in ("(bağımsız inceleme ekibi kararı (2026-11-21), seed-084, seed-085)",
                      "`freeze` ve `lift` satırının biçimi Kurucu'nun P1 MF7'de kurduğu biçimdir (seed-085 a)",
                      "`kind: freeze`, `payload {trigger, scope, measurement, start}`",
                      "`trigger` ∈ {`regression`, `containment`, `budget_usd`, `budget_ci_minutes`}",
                      "ad bir sınıf kimliği (`K0`–`K8`) ya da `loop`'tur",
                      "`measurement` sayımların (JSON tamsayıları) nesnesidir; kayan nokta yoktur",
                      "`kind: lift`, `payload {trigger, scope, start}`: kaldırdığı dondurmanın bu üç alanı",
                      "Üçü bir dondurmayı tek başına adlandırır",
                      "hiçbir `lift` satırının adlandırmadığı dondurma yürürlüktedir",
                      "`kind: hard_stop`, `payload {trigger, evidence}` (seed-085 h)",
                      "`trigger` ∈ {`soft_freeze_limit`, `drift`, `chain_break`, `rekor`, `attestation`, `activation`, "
                      "`ref_change`, `kill_switch`}", "döngü bir sert duruş için `lift` satırı yazmaz",
                      "`drift.check` yalnız okur ve hiçbir şey yazmaz, duruşu Gözcü yazar"):
            self.assertIn(words, text, words)

    def test_the_scope_and_the_views(self):
        # gozcu_drill_reverts_counted gozcu_empty_views_unjudged gozcu_budget_scope_class
        text = flat(page("26i"))
        for words in ("Kapsamda `loop` varsa hiçbir aday merge edilmez; hakemin okuma işleri sürer",
                      "Regresyon dondurmasının kapsamı sayılan geri almaların sınıflarıdır, bütçe dondurmasınınki "
                      "`loop`'tur", "Yalnız sıradan bir `events`/`merge` satırının geri alınması sayılır",
                      "provanındır (`29m`) ve hiçbir görünümde sayılmaz (seed-085 i)",
                      "`ts`'si `now`'ın UTC takvim ayında olan `cost` satırlarının `usd_micros` toplamıdır",
                      "Görünümleri boştur, kuralları yine yargılanır ve devrin çıktısı onları ölçülmemiş olarak "
                      "adlandırır (seed-085 d, e)"):
            self.assertIn(words, text, words)

    def test_the_pages_point_to_26i_and_28a(self):  # schema_page_26i_unlisted gozcu_row_types_unlisted
        self.assertIn("devamları (`26b`, `26c`, `26d`, `26g`, `26i`)", flat(page("26")))
        self.assertIn("| `freeze` (satırları `26i`); `rival`, `accept`; `security` |", page("26"))
        row = next(line for line in page("26a").splitlines() if line.startswith("| `gozcu.evaluate` |"))
        self.assertIn("| defter görünümleri (`26i`), politika, `now` | dondurma, kalkış, sert duruş, işaret (`28a`) | "
                      "`freeze` bölümünün `freeze`, `lift`, `hard_stop` satırları (`26i`) |", row)
        self.assertIn("tetik, kapsam, ölçüm, başlangıç (biçimi `26i`; Aşama 1'i `28a`)", flat(page("28")))


class GozcuStageOneTest(unittest.TestCase):
    """seed-084: what Stage 1 judges (`28a`), its windows, its lifts and keys; L1-L3 are the operator's decision under
    the owner's delegation, named as loosenings in the register."""

    def test_the_rules_stage_1_judges(self):  # regression_rule_inverted gozcu_answer_unlabelled
        text = flat(page("28a"))
        for words in ("(bağımsız inceleme ekibi kararı (2026-11-21), seed-084, seed-085)",
                      "Gözcü, ölçüsü ve kaynağı bir sayfada olan her kuralı yargılar",
                      "`M` ≥ `min_merges` ise `R` > `revert_rate` × `M`, değilse `R` ≥ `min_reverts` bir yumuşak "
                      "dondurmadır", "Sayım bütün sınıfları birlikte sayar",
                      "`monthly_cap_usd` × 1.000.000 mikro USD'ye ulaşınca (≥) bütçe dondurması",
                      "kalkmış olsun olmasın ve bütçe dondurması dahil, bu çağrının başlattıklarıyla birlikte sayılır; "
                      "sayı `soft_freeze_limit`'ten büyükse sert duruştur",
                      "Gözcü kanıtlarını `hard_stop` satırına kopyalar",
                      "kuralları vardır ve yargılanır; görünümleri Aşama 1'de boştur"):
            self.assertIn(words, text, words)

    def test_windows_lifts_and_keys(self):  # window_closed_at_start regression_freeze_lifts_by_itself gozcu_absent_key_carries_on
        text = flat(page("28a"))
        for words in ("`d` günlük pencere `now − d·86400 < ts ≤ now` olan satırlardır: başında açık, `now`'da kapalı",
                      "Bütçe dondurması kendiliğinden kalkar", "Gözcü bir `lift` satırı yazar",
                      "Regresyon ve kapsayıcılık dondurması Aşama 1'de kalkmaz",
                      "(`revert_rate` `\"0.020000\"`)", "Aşama 1'in zorunlu yedi Gözcü yolu",
                      "politika kullanılamaz ve döngü ilk yazımından önce temiz durur (`29v` \"Döngüde eksik anahtar\"); "
                      "bu asla \"yargılanmadı, devam\" değildir",
                      "Aşama 1'in yargıladığı her kural sentetik girdide doğru dondurmayı, kalkışı ya da sert duruşu "
                      "verir. MF7'nin vektör grubu yoktur"):
            self.assertIn(words, text, words)

    def test_the_deferrals_and_their_loosenings(self):  # deferrals_unlabelled loosenings_unnamed minutes_counted_from_p1
        text = flat(page("28a"))
        for words in ("**Aşama 1'de olmayanlar** (operatör kararı, sahibin yetkisiyle (2026-11-21))",
                      "**L1, salınım birikimi.**", "**L2, Actions dakikasının kaynağı.**",
                      "Fren GitHub harcama sınırı olarak kalır", "**L3, sonda döngüsü ve kalkışı**",
                      "P3'ün tablosunun bir satırı olarak gelir"):
            self.assertIn(words, text, words)
        row = register_row("E680")
        self.assertIn("**Gevşetmeler** (operatör kararı, sahibin yetkisiyle, 2026-11-21", row)
        for words in ("L1 salınım birikimi", "L2 Actions dakikasının kaynağı", "L3 sonda döngüsü"):
            self.assertIn(words, row, words)
        minutes = flat(page("25"))
        self.assertIn("dakikanın okuması bir sayfada adlandırılınca Gözcü bunu bütçe dondurması sayar (`28a`)", minutes)
        self.assertNotIn("P1'den sonra Gözcü", minutes)

    def test_the_leaves_are_on_18a_and_18b(self):  # regression_leaves_unnamed genesis_leaves_unnamed revert_rate_written_as_float
        a, b = key_rows("18a"), key_rows("18b")
        for leaf in ("min_merges", "window_days", "revert_rate", "min_reverts"):
            self.assertIn(f"constitutional.regression_freeze.{leaf}", a)
        for leaf in ("per_window", "queue"):
            self.assertIn(f"performance.rules.genesis_drafts.{leaf}", b)
        self.assertIn("| 50, 30, `\"0.020000\"`, 2: ≥ 50 merge varken 30 günde geri alma > %2", page("18a"))
        self.assertIn("Pencere başına ≤ 3 taslak (`per_window` 3); kuyruk derinliği ≤ 10 (`queue` 10)", page("18b"))
        self.assertIn("| `constitutional.gate_rules.soft_freeze_limit` |", page("18a"))
        self.assertIn("| `constitutional.gate_rules.containment_freeze` |", page("18a"))


class DriftBaselineTest(unittest.TestCase):
    """seed-082: `01c`'s reads, numbers and new field."""

    def test_the_policy_numbers(self):  # policy_fraction_any_decimals
        text = flat(page("01c"))
        for words in ("`policy.json` hash'lenen bir dosyadır (`18`, `29o`): `26` \"Sayılar\" ona da uyar ve hiçbir "
                      "yerinde kayan nokta yoktur", "Tamsayı olmayan her değer tam altı ondalıklı sabit ondalık dizgidir "
                      "(`\"0.900000\"`)", "o yolu okuyan okuyucu `policy_invalid:<yol>` ile reddeder",
                      "`constitutional_sha256`: `sha256(canonical(policy.json[\"constitutional\"]))`"):
            self.assertIn(words, text, words)
        for prefix in ("18a", "18b"):
            self.assertIn("Tablo kesri virgülle yazar; dosyada altı ondalıklı dizgidir (`01c`).", flat(page(prefix)))

    def test_the_baseline_form(self):  # drift_rules_branches_optional drift_future_check_accepted drift_stale_red_job
        text = flat(page("01c"))
        for words in ("`writer_app_permissions` (`GET /app`'in `permissions` nesnesi, olduğu gibi)",
                      "`rules` `brain/state`, `brain/integration` ve `main`'i adlandırır (öbür dallar da "
                      "karşılaştırılır), birini adlandırmayan özet kullanılamaz",
                      "Zamanlar yalnız `YYYY-MM-DDTHH:MM:SSZ`'dir; başka biçim ve işin saatinden sonraki "
                      "`operator_checked_at` kullanılamaz.",
                      "hiçbir şey yazılmaz, operatör görünür bir uyarı alır ve iş kırmızı değildir",
                      "öğeler `canonical(öğe)`'nin UTF-8 baytlarına göre sıralanır"):
            self.assertIn(words, text, words)
        self.assertNotIn("app_scope", text)

    def test_the_reads_and_reasons(self):
        # rulesets_read_from_branches drift_trees_from_brain activity_other_types_allowed visibility_only_targets_read
        text = flat(page("01c"))
        for words in ("Klasörler hakem reposunun kökündeki operatör dosyalarıdır (aktarım onları `main`'den korur, "
                      "`25a` 1), beyinden gelmez", "hakem reposunda `.gitattributes` yoktur",
                      "bağ ya da düzenli olmayan dosya reddedilir",
                      "Ruleset listesi `GET /repos/{r}/rulesets?per_page=100`'dür",
                      "kimlikler tabana küme olarak karşılaştırılır",
                      "`visibility` `GET /repos/{r}`'nin `visibility` alanıdır; harita her hedefin reposunu adlandırır, "
                      "özetin adlandırdığı her repo okunur ve karşılaştırılır",
                      "`writer_app_permissions` `GET /app`'in `permissions`'ıyla eşitlik olarak karşılaştırılır",
                      "`constitutional_hash_mismatch`, `vectors_hash_mismatch`, `seats_hash_mismatch`, "
                      "`rulesets_changed`, `visibility_changed:<repo>`, `writer_app_permissions_changed`",
                      "Aşama 1'de tabanın ve kural hash'inin vektörü yoktur",
                      "başlangıç satırı defterin bu döngününkinden önceki son `events`/`cycle_start` satırıdır (`29n`)",
                      "Okuma pencereyi başından gösteremezse", "Durma satırı Gözcü'nün `hard_stop` satırıdır (`26i`)",
                      "`GET /app`'in `slug`'ı ve ardından `[bot]` login'idir",
                      "push eder (`push`), dal açar (`branch_creation`) ve PR merge eder (`pr_merge`)",
                      "`operator_logins` yalnız dal siler (`branch_deletion`",
                      "başka her `activity_type` (`force_push`, `merge_queue_merge` dahil), `null` aktör ya da başka "
                      "bir login döngüyü durdurur"):
            self.assertIn(words, text, words)
        self.assertIn("biçimi `01c`'dedir (seed-080, seed-082)", flat(page("26c")))


class HarnessValuesTest(unittest.TestCase):
    """seed-083: `26h`'s harness values and primary ref; `29v`'s clean stop on an absent key."""

    def test_the_primary_ref_and_the_values(self):
        # primary_ref_any confidence_float_accepted stage_param_zero_accepted copy_13d_primary_unnamed
        text = flat(page("26h"))
        for words in ("(bağımsız inceleme ekibi kararı (2026-11-21), seed-083)",
                      "Birincil ref bulgunun `evidence_refs[0]`'ıdır ve yalnız o `stage_params.evidence_ref_max_lines` "
                      "ile sınırlıdır (`line_end − line_start + 1` satır, iki uç dahil)",
                      "Öbür ref'lerin uzunluk sınırı yoktur",
                      "`18a`'nın 0,90'ı `\"0.900000\"`'dır ve tek yönlü kullanılır (`19`); `alpha` = 1 − değer, tam "
                      "ondalık aritmetikle", "JSON kayan noktası, tamsayı, başka biçimde dizgi ya da nesne "
                      "`policy_invalid:constitutional.confidence_level`'dır",
                      "1 ya da daha büyük JSON tamsayılarıdır; 0, boolean, kayan nokta ya da dizgi `policy_invalid:<yol>`",
                      "Hiçbir sayfada üst sınırları yoktur"):
            self.assertIn(words, text, words)
        self.assertIn("birincil ref `evidence_refs[0]`'dır", flat((ROOT / "spec" / "asama-1" /
                                                                   "13d-bulgu-ve-kosu-semasi.md").read_text(encoding="utf-8")))
        self.assertIn("Birincil ref (`evidence_refs[0]`, `26h`) ≤ 30 satır", page("18a"))
        self.assertIn("0,90, tek yönlü (dosyada `\"0.900000\"`, `26h`)", page("18a"))

    def test_census_planted_and_absent_keys(self):  # dev_report_group_floor planted_cases_effective absent_key_defaulted
        text = flat(page("26h"))
        for words in ("`census_min_groups`'un okuyucusu `exit.sample`'dır", "Dev raporunun hiçbir sayfada grup tabanı "
                      "yoktur.", "`planted_max_cases` ekilmiş bir snapshot var olana kadar hiçbir çıktıyı değiştirmez"):
            self.assertIn(words, text, words)
        rule = flat(page("29v"))
        for words in ("**Döngüde eksik anahtar** (bağımsız inceleme ekibi kararı (2026-11-21), seed-083, seed-084)",
                      "politika kullanılamaz: döngü ilk yazımından önce temiz durur, yolu adlandırır ve hiçbir şey yazmaz",
                      "Olmayan yol tüketicisine asla `None` ya da varsayılan olarak verilmez; asla \"yargılanmadı, "
                      "devam\" değildir"):
            self.assertIn(words, rule, words)


class FirstTaskTest(unittest.TestCase):
    """The convention from the Founder's lesson f1741 (`25` 10b), applied to this epoch's own entry."""

    def test_the_convention_and_this_entry(self):  # first_task_unnamed first_task_not_first first_task_reads_short
        self.assertIn("Teslimden itibaren bir şeyi kırmızı yapan dönem onu tohum CHANGELOG girdisinin en başında "
                      "\"İlk iş\" olarak adlandırır (Kurucu'nun dersi f1741)", flat(page("25")))
        entry = flat((TOHUM / "CHANGELOG-10.md").read_text(encoding="utf-8").split("\n- 2.2 (2026-11-21, E680–E684", 1)[1])
        self.assertTrue(entry.startswith("; tohum dönemi AA; bağımsız inceleme ekibi kararı, sahibin yetkisiyle operatör "
                                         "kararı). **İlk iş** (`25` 10b; Kurucu'nun dersi f1741)."), entry[:200])
        for words in ("önyükleme hakeminin hiçbir denetimi kırmızı olmaz", "beynin 7757204'teki politika okuması iki fikstürde de "
                      "hepsini adlandırır", "`freeze` ve `lift` satırının biçimi Kurucu'nun MF7'de kurduğu biçimdir ve "
                      "değişmez"):
            self.assertIn(words, entry, words)
        self.assertEqual(len(re.findall(r" [1-9]\. ", entry.split("`freeze` ve `lift` satırının")[0])), 3)
        self.assertIn("`constitutional.confidence_level`, `constitutional.regression_freeze.revert_rate`, "
                      "`performance.rules.drift_bound` ve `performance.rules.seat_similarity`", entry)
        self.assertNotIn("ölçüldü", entry)
        self.assertIn("girdinin başında **İlk iş** listesi vardır", flat((TOHUM / "CHANGELOG.md").read_text(encoding="utf-8")))


class RecordsTest(unittest.TestCase):
    def test_register_changelog_index_caps_and_no_leak(self):
        # held_finding_leaks readme_policy_duty_dropped readme_permissions_added_now
        for eid, decided in (("E680", "bağımsız inceleme ekibi kararı (2026-11-21"),
                             ("E681", "bağımsız inceleme ekibi kararı (2026-11-21"),
                             ("E682", "bağımsız inceleme ekibi kararı (2026-11-21"),
                             ("E683", "rapor masasının uzlaşısı (2026-11-21)"), ("E684", "operatör kararı (2026-11-21)")):
            with self.subTest(eid=eid):
                self.assertIn(decided, register_row(eid))
        self.assertIn("**Teslimde operatör**", register_row("E681"))
        log = (TOHUM / "CHANGELOG-10.md").read_text(encoding="utf-8")
        for rid in ("seed-082-drift-baseline-fields-without-a-read-or-a-computable-recipe",
                    "seed-083-primary-evidence-ref-and-harness-policy-value-forms-unstated",
                    "seed-084-gozcu-triggers-thresholds-and-row-shapes-unstated",
                    "seed-085-gozcu-wiring-what-a-freeze-closes-and-what-a-cycle-measures"):
            self.assertTrue(any(f"`{rid}` →" in line for line in log.splitlines()), rid)  # one line (E527)
        self.assertIn("(b) bütçe dondurmasının harcamadan önce okunduğu adım, (c) birden çok hedefte ayın harcamasının nerede "
                      "toplandığı, (f) "
                      "merge satırında sınıf ve (j) kapanmış kapının `cause`'u yanıtsızdır", flat(log))
        index = (ROOT / "spec" / "INDEX.md").read_text(encoding="utf-8")
        for name, title in (("26i-semalar-gozcu.md", "Şemalar, Devam: Gözcü'nün Satırları ve Görünümleri"),
                            ("28a-dondurma-asama-1.md", "Dondurma, Devam: Aşama 1'de Gözcü"),
                            ("CHANGELOG-10.md", "Değişiklik Günlüğü — Tohum, 2.2'nin Dokuzuncu Kayıtları")):
            self.assertIn(f"| `tohum/{name}` | {title} |", index)
        for p in list(TOHUM.glob("*.md")) + list((ROOT / "spec" / "asama-1").glob("*.md")):
            self.assertLessEqual(len(p.read_text(encoding="utf-8").splitlines()), 80, p.name)
        for name in ("01c", "26h", "26i", "28a", "29v", "CHANGELOG-10"):
            text = (log if name == "CHANGELOG-10" else page(name)).lower()
            prefix = name
            for word in ("app_scope", "thaw", "çözülme", "tutulan bulgu", "bekleyen bulgu", "held"):
                self.assertNotIn(word, text, (prefix, word))
        readme = flat((ROOT / "seed" / "founder" / "README.md").read_text(encoding="utf-8"))
        for words in ("**AA döneminin operatör işleri** (seed-082, seed-083, seed-084; tohum sayfası değil)",
                      "`constitutional.confidence_level` `0.9` → `\"0.900000\"`",
                      "`drift.hashes.constitutional_sha256`'yı da hakem klonunun o anki `policy.json`'undan",
                      "Politikayı yeniden yazmak ve teslim aynı oturumda yapılır",
                      "`writer_app_permissions` bu teslimde **eklenmez**", "`visibility` canlı tabanda zaten vardır",
                      "from snowball_bootstrap.canon import canonical", "(asla `json.dumps` ile değil)"):
            self.assertIn(words, readme, words)


if __name__ == "__main__":
    unittest.main()
