"""Seed epoch AG (2026-11-22, report desk): seed-097 (an agent run's cost), seed-098 (an organ's output) and seed-099 (the
rerun of a run-time candidate), with the launcher fixes the owner approved: the whole session's cost row and its wait
(E720), the rival's outage (E721), the weekly limit and the key file (E722). Only `spec/tohum` reaches the brain, so
each binding sentence is on a `tohum` page: new `26o` and `26p`; every item of the three reports has a line in
`CHANGELOG-16`. The launcher's own behaviour is tested in `test_founder_capsule` and `test_mirror`. The trailing comment
on a test names the mutants it kills (`local/mutate.py`)."""

import no_real_delays  # noqa: F401  (first: no test waits on a real delay, E751)
import json
import unittest
from pathlib import Path

BOOT = Path(__file__).resolve().parents[1]
ROOT = BOOT.parents[1]
TOHUM = ROOT / "spec" / "tohum"
REPORTS = ("seed-097-an-agent-runs-cost-is-shown-to-no-session",
           "seed-098-the-form-of-an-organs-output-is-on-no-page",
           "seed-099-the-rerun-of-a-run-time-candidate-leaves-its-form-and-bounds-unstated")


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
    return (TOHUM / "CHANGELOG-16.md").read_text(encoding="utf-8")


def items(report: str) -> list[str]:
    """The item lines `CHANGELOG-16` gives a report: the `  - ` lines under its `→` line, up to the next report."""
    lines = changelog().splitlines()
    start = next(i for i, line in enumerate(lines) if line.strip().startswith(f"`{report}` →"))
    out = []
    for line in lines[start + 1:]:
        if line.startswith("  - "):
            out.append(line[4:])
        elif line.startswith("    ") and out:
            out[-1] += " " + line.strip()
        else:
            break
    return out


class SessionCostPageTest(unittest.TestCase):
    """`26o` (E720): the cost row is the whole session's; a waiting row is readable; an agent run's cost is derived."""

    def test_the_cost_row_is_the_whole_sessions(self):
        # ag_turns_last_turn ag_tokens_last_usage ag_per_model_unsaid ag_pending_unread ag_old_rows_rewritten
        text = flat(page("26o"))
        for words in ("tur sayısı bütün `result` olaylarının `num_turns` toplamıdır (birinde yoksa `unknown`);",
                      "token toplamları son olayın `modelUsage`'ının modeller üzerinden toplamıdır;",
                      "`costUSD` mikro olarak (`cost_usd_micros`) ve CLI'nin `costBasis` sözcüğü (`basis`)",
                      "`payload` `{summary, refs}` kalır (`26`). Bu dönemden önce yazılmış satırlar eski "
                      "biçimlerindedir; defter yalnız eklenir.",
                      "her oturumun klasöründe `/work/logs/cost-pending.json`'dadır: `{pending: [{stamp, snapshot_id, "
                      "summary, refs}], written}`, en eskisi önce, bekleyen yoksa `[]`",
                      "Bu dönemden önce bekletilmiş bir satır yazılmadan önce oturum günlüğünden yeniden okunur."):
            self.assertIn(words, text, words)

    def test_an_agent_runs_cost_is_keyed_derived_and_honest_about_output(self):
        # ag_runs_unkeyed ag_cost_from_cli ag_output_from_log ag_exactness_dropped ag_not_measured_unsaid
        # ag_weighing_prescribed ag_foreground_last_unsaid
        text = flat(page("26o"))
        for words in ("çağrının `tool_use_id`'si `toolu_…` ile anahtarlı",
                      "`tokens` `{in, cache_read, cache_write_5m, cache_write_1h, out}`",
                      "Önde koşan bir koşunun son mesajı günlükte yoktur, kullanımı Agent çağrısının "
                      "`tool_use_result`'ındadır ve oradan sayılır.",
                      "Günlükteki bir mesajın `output_tokens`'ı akışın başladığı andaki sayıdır, son sayı değildir: "
                      "koşunun çıktı tokenı günlükten okunmaz.",
                      "koşu oturumda modelinin tek koşusuysa ve oturumun kendi modeli başkaysa o modelin kapanış "
                      "`modelUsage` `outputTokens`'ıdır (`out_from: cli_model_line`), değilse `null`.",
                      "`cost_usd_micros` türetilmiştir (`cost_basis: derived:price_table`): tokenlar çarpı operatörün "
                      "fiyat tablosu (`seed/founder/prices.json`",
                      "CLI'nin rakamı değildir.",
                      "`output_tokens_unlogged` (taban durur), `price_unknown:<model>` (tabloda satırı yok ya da oturumun "
                      "kapanış `modelUsage`'ı o modele bilinen bir `costBasis` vermiyor), `no_usage`, `usage_unreadable`.",
                      "Kesinlik: model başına rakam bir koşununkine yalnız oturum o ajanı o modelde bir kez koştuysa ve "
                      "oturumun kendi modeli başkaysa eşittir.",
                      "Değerin nasıl tartıldığı Kurucu'nundur (E692'nin 4. korkuluğu, E697)."):
            self.assertIn(words, text, words)
        for wrong in ("ajan başına maliyet satırı", "maliyeti CLI verir"):
            self.assertNotIn(wrong, text)

    def test_the_rivals_outage_and_the_weekly_limit(self):
        # ag_outage_a_rejection ag_outage_isolation_counted ag_outage_session_starts ag_outage_probe_counted
        # ag_limit_date_unread ag_limit_key_read ag_limit_mark_at_wait ag_outage_rule_as_referee ag_hold_unlogged
        text = flat(page("26o"))
        for words in ("(`rival_unresolved`, `ref`'i `api_error:` ile başlar ve yalıtım hatası `api_error:isolation_…` "
                      "değildir; ör. `api_error:http_429`) başı değerlendirmez: kesintidir, Kurucu'nun reddi değildir.",
                      "`verdict: null`, `evaluated: false`, `unjudged: {cause: \"outage\", owner: \"rival\"}`",
                      "Bu dönemden önce `rejected` diye yazılmış böyle bir satır da notta kesintidir.",
                      "`mirror.json` `per_model` onu `outages` altında sayar: hiçbir zaman bir kararda, "
                      "`rejected_rows_by_reason`'da ya da `repeats`'te değil.",
                      "En yeni sonuç böyle bir kesintiyken başlatıcı yeni oturum açmaz (`24a` 2): hakemi bir kez yoklar, "
                      "baş değerlendirilince sürer, değilse 30 dakika sonra yeniden yoklar; bu bekleyiş bir döngü sayılmaz.",
                      "\"resets Nov 25, 4pm (UTC)\" biçiminden (`<Ay> <gün>, <saat>[:dk](am|pm)`) de okur. O ana kadar "
                      "bekler (tarihli açılışta en çok 8 gün);",
                      "operatörün anahtar dosyasının değişme zamanı oturumun başından beri değiştiyse (oturum sürerken "
                      "konan anahtar da) bir dakika içinde sürer (dosyanın içeriği okunmaz).",
                      "Kural hakeminkinden dardır: hakem bir `api_error` nedeni olan her başı değerlendirmez (`29b`), ama "
                      "başka bir nedeni de olan sonuç kesinti değil, `evaluated: false` bir rettir;",
                      "Bekleyişin başını ve sonunu operatöre `pilot-log.md`'de birer satır söyler."):
            self.assertIn(words, text, words)

    def test_the_pages_that_point_to_26o(self):  # ag_24a_unpointed ag_26h_unpointed
        self.assertIn("park ya da kesinti (rakibinki dahil, `26o`) varsa başlatmaz", page("24a"))
        self.assertIn("(bütün oturumun model ve token toplamları dahil, yorumsuz; `26o`)", page("24a"))
        self.assertIn("koşularının maliyeti (`delegation`) ve rakip kesintileri (`outages`) `26o`'dadır.", page("26h"))


class OrganOutputPageTest(unittest.TestCase):
    """`26p` (E723, E724): an organ's output and the rerun of a run-time candidate."""

    def test_098_the_output_form_and_keep_rule(self):
        # ag_stdout_is_output ag_hash_per_file ag_invalid_kept ag_exit_drops_valid ag_special_skipped
        # ag_proposal_name_guessed ag_proposal_format_now ag_package_reading_old
        text = flat(page("26p"))
        for words in ("Organın çıktısı, kapsanmış koşusunun `/out` altında bıraktığı düzenli dosyalardır, her biri "
                      "oradaki yoluyla. Giriş noktasının stdout'u ve stderr'i çıktı değildir",
                      "Giriş noktası çıktısını `koş`'a yalnız `/out`'a dosya bırakarak verir.",
                      "Tek hash bütün çıktıyı kapsar: manifestinki, `{\"files\": {<yol>: <sha256>}}`",
                      "manifestin ve dosyaların baytları sonuçlarda `o/<sha256>` altındadır.",
                      "manifestte ya da bir dosyada değişmiş tek bayt bütün çıktıyı reddeder ve hiçbir parçası okunmaz.",
                      "çağrılmış bir organın geçerli koşusu, giriş noktasının çıkış kodu ne olursa olsun tutulur",
                      "Geçerli olmayan koşu (kırmızı kontrol yeşil kaldı, ya da bir sınır: `limit_hit:<anahtar>`) "
                      "hiçbir şey tutmaz.",
                      "host'un okuyamadığı bir dosya taşıyan çıktı da hiçbir şey tutmaz (`output_entry:<tür>`, "
                      "`output_entry:unreadable`). Her durumda organın girdisi nedeni adlandırır, devir sürer",
                      "listesi çıktısının kökündeki `findings.json` dosyasıdır (Kurucu'nun kodunun kullandığı ad). Satır "
                      "biçimi ilk yazıcısıyla, Aşama 1 MF1'i getiren dönemde gelir",
                      "seed-098'in \"sonuçlardaki o yolda bir dosya değil\" okuması seed-099'un okumasıyla değişti."):
            self.assertIn(words, text, words)

    def test_099_the_rerun(self):
        # ag_id_allows_dot ag_twice_writes_one ag_diff_any_encoding ag_unusable_stops_cycle ag_rerun_unbound
        # ag_unverified_counts_none ag_bound_mf6 ag_bound_interim_unsaid ag_base_other
        text = flat(page("26p"))
        for words in ("Aday kimliği `[A-Za-z0-9][A-Za-z0-9_-]{0,127}`'dir, noktasız",
                      "`package_id_twice` ile reddedilir, ikisi de yazılmaz; aynı baytlar iki kez tek pakettir.",
                      "Her ret yalnız o kimliği reddeder.",
                      "`diff` bir JSON dizgisidir; diff o dizginin UTF-8 baytlarıdır",
                      "yalnız o aday için `package_unusable` ile reddedilir; onun için bir şey koşmaz, devir sürer",
                      "`reruns.<id>` girdisi kararını, nedenlerini ve `package_sha256`'yı, koştuğu paket baytlarının "
                      "sha256'sını taşır: bağ budur",
                      "Fark: kararı `verified` olmayan yeniden koşu \"yok\" sayılmaz; aday kapıya ulaşır ve girdisinin her "
                      "nedeniyle `kos:<neden>` olarak reddedilir",
                      "Gevşetme değildir: iki yol da merge etmez.",
                      "(6) Bir koşunun paket sayısının sınırı ertelendi: Aşama 1 MF5'i (`candidate.publish`;",
                      "o MF'nin canlı koşusundan önce bandıyla bir `operating{}` sayı anahtarı ekler",
                      "`operating.output_bytes`'ıyla, bütün yeniden koşular `koş` işinin `operating.kos_wall_s`'iyle "
                      "sınırlıdır (`18a`)",
                      "(7) Yeniden koşu, işin taban koşusunun taban çalışma ağacının taze bir kopyasında koşar; hazır "
                      "adaylar aynı taban koşusunu kullanır",
                      "seed-098 ve seed-099 için vektör reddedildi, testler 56–58 bağlar."):
            self.assertIn(words, text, words)

    def test_26j_points_to_26p(self):  # ag_26j_unpointed
        text = page("26j")
        self.assertIn("(`26p`).", text.split("**Kap.**")[1].splitlines()[0])
        self.assertIn("değişmiş çıktı okunmaz. Çıktının biçimi ve tutma kuralı `26p`'dedir (seed-098).", text)
        self.assertIn("yeniden koşusu olmayan aday kapıya ulaşmaz. Ayrıntısı `26p`'dedir.", text)


class RecordsTest(unittest.TestCase):
    """CHANGELOG-16 (its first task and a line for every item), the register, INDEX and the answers file."""

    def test_the_first_task_keeps_the_order_and_places_the_answers(self):
        # ag_first_task_not_first ag_order_changed ag_answers_after_mf12 ag_answers_after_fifth ag_confirm_a_task
        text = flat(changelog())
        self.assertIn("**İlk iş** (`25` 10b; Kurucu'nun dersi f1741).", text)
        self.assertIn("Kurucu'nun bugünkü işi sürer, sırası `CHANGELOG-14`'ünkidir.", text)
        self.assertIn("MF12 sayılmadan önce MF10 ve MF11'in kurulmuş satırları `26p`'ye uyar", text)
        self.assertIn("push-reviewer'ın ajanlı beşinci oturumundan önce E692'nin 4. korkuluğu bir koşunun maliyetini "
                      "`26o`'dan okur (seed-097)", text)
        self.assertIn("Raporların teyidi `26l`'nin kuralı olarak kalır, bu listenin bir maddesi değildir.", text)
        self.assertIn("Gevşetme yok.", text)

    def test_every_item_of_each_report_has_its_line(self):
        # ag_item_097_dropped ag_item_098_dropped ag_item_099_dropped ag_item_unmarked
        expected = {REPORTS[0]: 12, REPORTS[1]: 12, REPORTS[2]: 10}
        for report, count in expected.items():
            with self.subTest(report=report):
                lines = items(report)
                self.assertEqual(len(lines), count, lines)
                for line in lines:
                    self.assertRegex(line, r": (yanıtlandı|ertelendi|reddedildi|ad yanıtlandı|ilk altısı|kurulduğu)",
                                     line)
        labels = [line.split(" ", 1)[0] for line in items(REPORTS[1])[:9]]
        self.assertEqual(labels, ["(a)", "(b)", "(c)", "(d)", "(e)", "(f)", "(g)", "(h)", "(i)"])
        labels = [line.split(" ", 1)[0] for line in items(REPORTS[2])[:7]]
        self.assertEqual(labels, [f"({n})" for n in range(1, 8)])
        self.assertIn("ertelendi: Aşama 1 MF1'i getiren döneme", items(REPORTS[1])[1])
        self.assertIn("ertelendi: Aşama 1 MF5'i (`candidate.publish`) getiren döneme", items(REPORTS[2])[5])
        self.assertTrue(any(line.startswith("operatörün maddesi") for line in items(REPORTS[0])))

    def test_the_register_rows(self):  # ag_rows_open ag_e721_rejection
        for eid in ("E720", "E721", "E722", "E723", "E724"):
            with self.subTest(eid=eid):
                self.assertTrue(register_row(eid).endswith("|"))
                self.assertIn("kapandı (tohum dönemi AG", register_row(eid))
        self.assertIn("günlükteki her mesajın `output_tokens`'ı akışın başındaki sayıdır, son sayı değildir",
                      register_row("E720"))
        self.assertIn("İmzalı sonucun `rejected` sözcüğü değişmez", register_row("E721"))
        self.assertIn("içerik hiç okunmaz", register_row("E722"))
        self.assertIn("masa MF5 ile MF6'yı doğruladı", register_row("E724"))

    def test_the_indexes_and_the_answers(self):  # ag_index_missing ag_changelog_unindexed ag_answers_missing
        index = (ROOT / "spec" / "INDEX.md").read_text(encoding="utf-8")
        for name in ("tohum/26o-semalar-ajan-maliyeti-ve-kesinti.md", "tohum/26p-semalar-organ-ciktisi-ve-yeniden-kosu.md",
                     "tohum/CHANGELOG-16.md"):
            self.assertIn(f"| `{name}` |", index)
        self.assertIn("`CHANGELOG-16.md`; başında **İlk iş**.", (TOHUM / "CHANGELOG.md").read_text(encoding="utf-8"))
        answers = json.loads((BOOT / "reports" / "answers.json").read_text(encoding="utf-8"))["answers"]
        mine = [(a["id"], a["kind"]) for a in answers if a["changelog"] == "CHANGELOG-16"]
        self.assertEqual(mine, [(r, "answered") for r in REPORTS])
        for report in REPORTS:
            self.assertEqual(sum(1 for line in changelog().splitlines() if line.strip().startswith(f"`{report}` →")), 1)

    def test_the_new_pages_fit_and_the_price_table_is_the_operators(self):  # ag_prices_unsourced
        for prefix in ("26o", "26p", "24a", "26j", "26h"):
            self.assertLessEqual(len(page(prefix).splitlines()), 80, prefix)
        self.assertLessEqual(len(changelog().splitlines()), 80)
        prices = json.loads((ROOT / "seed" / "founder" / "prices.json").read_text(encoding="utf-8"))
        self.assertTrue(prices["source"].startswith("the operator"))
        self.assertRegex(prices["as_of"], r"^2026-11-22$")
        self.assertEqual(prices["models"]["claude-opus-5-5"], {"in": 4_000_000, "out": 20_000_000, "cache_read": 200_000,
                                                              "cache_write_5m": 5_000_000, "cache_write_1h": 8_000_000})


if __name__ == "__main__":
    unittest.main()
