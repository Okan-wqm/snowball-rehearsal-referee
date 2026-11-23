"""Seed epoch AF (2026-11-22): the report desk's consensus on seed-089 .. seed-096 (E698-E703). A confirmation's
`epoch` is the brain's delivery commit and both readers check it against the setup summary's epochs (`26l`, seed-096);
`13:54-56` names the comparison point before a target's first merge (seed-093); the built P1 rows' remaining interface
facts are on `26m` and `26n` (seed-089-092, seed-094); seed-095 is deferred to the epoch that brings `fixer.llm`. Every
item of each report as written has a line in `CHANGELOG-15` (the desk's rule of 2026-11-22). Only `spec/tohum`
reaches the brain, so each binding sentence is on a `tohum` page. The trailing comment on a test names the mutants it
kills (`local/mutate.py`)."""

import json
import re
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from snowball_bootstrap import cli, config, reportlife

import test_flow
import test_seed_epoch
from helpers import commit
from test_founder_capsule import load_launch
from test_panel_epoch_ad import EVIDENCE, AnswersFile, read, report, tar_of

BOOT = Path(__file__).resolve().parents[1]
ROOT = BOOT.parents[1]
TOHUM = ROOT / "spec" / "tohum"
GOOD, OTHER = "e" * 40, "f" * 40
REPORTS = {
    "seed-096-the-seed-epoch-commit-of-26l-is-readable-nowhere-in-a-session": ["soru", "dokuz teyide"],
    "seed-093-integration-comparison-point-before-the-toys-first-merge-is-open": ["soru"],
    "seed-089-snapshot-path-identity-manifest-form-adapter-tool-and-pattern-writer-unstated":
        ["(1)", "(2)", "(3)", "(4)", "yer tutucu notu", "vaka şeması notu"],
    "seed-090-dev-case-store-layout-carriage-and-two-validity-edges-unstated":
        ["(1)", "(2)", "(3)", "(4)", "(5)", "(6)", "\"(1)–(4) sayfaya gelene kadar\" notu", "`build.py`'nin grubu notu"],
    "seed-091-harness-score-fingerprint-hash-observation-verdict-and-k4-census-unstated": ["(1)", "(2)", "(3)", "(4)"],
    "seed-092-test-9-proof-online-reason-and-test-11-scope-unstated":
        ["(1)", "(2)", "(3)", "(4)", "boş olmayan prova oyuncağı notu"],
    "seed-094-drift-activity-reason-time-form-permission-and-stale-check-edges-unstated":
        ["(1)", "(2)", "(3)", "(4)", "(5)"],
    "seed-095-asama-1-per-finding-brakes-have-no-policy-key": ["soru"],
}


def page(prefix: str) -> str:
    found = sorted(TOHUM.glob(f"{prefix}-*.md"))
    assert len(found) == 1, (prefix, found)
    return found[0].read_text(encoding="utf-8")


def flat(text: str) -> str:
    return " ".join(text.split())


def changelog() -> str:
    return (TOHUM / "CHANGELOG-15.md").read_text(encoding="utf-8")


def register_row(eid: str) -> str:
    rows = (ROOT / "docs" / "eksik-kaydi.md").read_text(encoding="utf-8").splitlines()
    return next(line for line in rows if line.startswith(f"| {eid} |"))


def section(prefix: str, label: str, end: str) -> str:
    text = flat(page(prefix))
    return text[text.index(label):text.index(end, text.index(label))]


class EpochIsASummaryEpochTest(unittest.TestCase):
    """`26l` "Teyidin kanıtı" (seed-096, tightening): the `epoch` is one of `seed_epochs[].commit`."""

    def test_the_evidence_reads_the_epoch_against_the_summarys(self):
        # epoch_membership_ignored read_row_drops_epochs epoch_commits_any_text
        doc = report("seed-900", "confirmed", **EVIDENCE)
        self.assertTrue(reportlife.evidence(doc))  # without the summary: the form alone, as before
        self.assertTrue(reportlife.evidence(doc, frozenset({GOOD, OTHER})))
        self.assertFalse(reportlife.evidence(doc, frozenset({OTHER})))
        self.assertFalse(reportlife.evidence(doc, frozenset()))
        self.assertFalse(reportlife.evidence(dict(doc, epoch=GOOD[:7]), frozenset({GOOD[:7]})))  # the form still holds
        raw = json.dumps(doc).encode("utf-8")
        self.assertTrue(reportlife.read_row("seed-900.json", raw, frozenset({GOOD}))["evidence"])
        self.assertFalse(reportlife.read_row("seed-900.json", raw, frozenset({OTHER}))["evidence"])
        rows = [{"commit": GOOD}, {"commit": GOOD[:7]}, {"commit": "E" * 40}, {"commit": None}, "x", {"commit": OTHER}]
        self.assertEqual(reportlife.epoch_commits({"seed_epochs": rows}), frozenset({GOOD, OTHER}))
        for summary in ({}, {"seed_epochs": None}, {"seed_epochs": {"commit": GOOD}}, [], None):
            self.assertEqual(reportlife.epoch_commits(summary), frozenset(), summary)

    def test_a_confirmation_of_another_epoch_counts_open(self):  # read_reports_drops_epochs
        named = AnswersFile(self, [("seed-900", "CHANGELOG-15", "answered")]).load()
        files = {"reports/seed-900.json": json.dumps(report("seed-900", "confirmed", **EVIDENCE)).encode("utf-8")}
        self.assertEqual(reportlife.counts(cli.read_reports(tar_of(files), frozenset({GOOD})), named), (0, 0))
        self.assertEqual(reportlife.counts(cli.read_reports(tar_of(files), frozenset({OTHER})), named), (0, 1))
        self.assertEqual(reportlife.counts(cli.read_reports(tar_of(files), frozenset({OTHER})),
                                           AnswersFile(self).load()), (1, 0))
        meta = cli.reports_meta(tar_of(files), frozenset({OTHER}))
        self.assertEqual(sorted(meta), ["reports"])  # the meta keeps its shape (`test_stage0_unchanged`)
        self.assertFalse(meta["reports"][0]["evidence"])
        self.assertEqual(read(report("seed-900", "confirmed", **EVIDENCE))[0]["evidence"], True)

    def test_cli_names_the_summarys_epochs(self):  # cli_epoch_commits_empty
        summary = config.summary_of({"seed_commit": "a" * 40, "seed_tree_sha256": "b" * 64, "seed_epochs": [
            {"commit": GOOD, "spec_tohum_sha256": "c" * 64, "seed_sha256": None, "bootstrap_sha256": "d" * 64},
            {"commit": OTHER, "spec_tohum_sha256": "c" * 64, "seed_sha256": None, "bootstrap_sha256": "d" * 64}]})
        self.assertEqual(cli.epoch_commits(summary), frozenset({GOOD, OTHER}))
        self.assertEqual(cli.epoch_commits(config.summary_of({"seed_commit": "a" * 40, "seed_tree_sha256": "b" * 64})),
                         frozenset())


class EpochInThePullTest(unittest.TestCase):
    """The referee's `pull` reads the reports with its own summary's epochs, on a Founder push and on the delivery."""
    setUp = test_flow.Flow.setUp
    tearDown = test_flow.Flow.tearDown
    pull = test_flow.Flow.pull
    finish = test_flow.Flow.finish
    summary_path = test_seed_epoch.SeedEpochFlow.summary_path
    epoch_row = test_seed_epoch.SeedEpochFlow.epoch_row
    deliver = test_seed_epoch.SeedEpochFlow.deliver

    def test_a_confirmation_names_a_delivery_commit(self):  # pull_drops_epochs seed_update_drops_epochs
        first = self.deliver()
        self.finish(self.pull())
        docs = {"seed-900": dict(report("seed-900", "confirmed", **EVIDENCE), epoch=first),
                "seed-901": dict(report("seed-901", "confirmed", **EVIDENCE), epoch=OTHER)}
        commit(self.brain, {f"reports/{rid}.json": json.dumps(doc) + "\n" for rid, doc in docs.items()}, "reports")
        meta = self.pull()
        self.assertEqual({r["stem"]: r["evidence"] for r in meta["reports"]}, {"seed-900": True, "seed-901": False})
        self.finish(meta)
        second = self.deliver({"spec/tohum/00-cekirdek.md": "# core, epoch three\n",
                               "seed/bootstrap/snowball_bootstrap/__init__.py": "VERSION = 3\n"})
        meta = self.pull()
        self.assertEqual((meta["head"], meta["kind"]), (second, "seed_update"))
        self.assertEqual({r["stem"]: r["evidence"] for r in meta["reports"]}, {"seed-900": True, "seed-901": False})


class LauncherReadsTheSameEpochsTest(unittest.TestCase):
    def test_the_launcher_reads_the_summarys_epochs_at_preflight_and_reads_with_them(self):
        # launcher_epochs_unread launcher_reader_drops_epochs
        launch = load_launch()
        work = Path(tempfile.mkdtemp())
        (work / "snowball-founder.env").write_text("x" * 64, encoding="utf-8")
        (work / "target").mkdir()
        pilot = launch.Pilot(work, "o/brain", "o/referee", "target")
        self.assertIsNone(pilot.epochs)
        ok = subprocess.CompletedProcess([], 0, b"", b"")
        summary = {"seed_commit": "a" * 40, "targets": [], "seed_epochs": [{"commit": GOOD}, {"commit": "x"}]}
        with mock.patch.object(launch, "run", return_value=ok), \
                mock.patch.object(launch.Pilot, "summary", return_value=summary):
            pilot.preflight()
        self.assertEqual(pilot.epochs, frozenset({GOOD}))

        def blob(doc):
            import hashlib
            data = json.dumps(doc).encode("utf-8")
            return {"text": data.decode("utf-8"), "isTruncated": False,
                    "oid": hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()}
        tree = [{"name": "seed-900.json", "object": blob(report("seed-900", "confirmed", **EVIDENCE))},
                {"name": "seed-901.json", "object": blob(dict(report("seed-901", "confirmed", **EVIDENCE), epoch=OTHER))}]
        with mock.patch.object(pilot, "tree_blobs", return_value=tree):
            rows = pilot.open_reports("b" * 40)
        self.assertEqual([r["evidence"] for r in rows], [True, False])


class EpochPagesTest(unittest.TestCase):
    """seed-096: which repository and which commit, on `26l`, `26c` and `27`."""

    def test_26l_names_the_brains_delivery_commit_and_the_check(self):
        # epoch_repo_unsaid epoch_read_place_unsaid epoch_check_unsaid epoch_check_a_reason
        text = flat(page("26l"))
        for words in ("satırının tam `commit`'i (40 küçük onaltılık). Bu commit beyin reposunundur (seed-096): dönemin "
                      "`spec/tohum`'unu beynin `main`'ine getiren teslim commit'i (`25` 10b), konusu `Tohum dönemi: "
                      "snowball-mcp <7 hane>`, değişikliği yalnız `spec/tohum/` altında; hiçbir zaman bir `snowball-mcp` "
                      "commit'i değildir",
                      "Oturum onu kendi beyin klonunun geçmişinden okur: yanıtı getiren dönemin teslim commit'inin tam "
                      "SHA'sıdır; teslimden sonraki ilk oturumda bu, oturumun başladığı beyin başının geçmişindeki en yeni "
                      "`Tohum dönemi:` commit'idir (dönem AD'ninki `d5114fe85095b9626b3903c2792ec81066da9872`). Yeni bir "
                      "okuma yeri gerekmez;",
                      "Dönem AF'den (seed-096, sıkılaştırma) hakem ve başlatıcı `epoch`'un özetin `seed_epochs[].commit` "
                      "değerlerinden biri olduğunu da denetler: olmayan `epoch` teyidi kapatmaz, rapor `open` sayılır "
                      "(aşağıdaki sayımlarda; uyarı, hiçbir zaman neden değil)."):
            self.assertIn(words, text, words)

    def test_26c_and_27_say_which_repository(self):  # epoch_26c_unsaid epoch_27_unsaid
        self.assertIn("`{commit, spec_tohum_sha256, seed_sha256, bootstrap_sha256}` (`commit` beynin teslim commit'idir, "
                      "`Tohum dönemi: snowball-mcp <7 hane>`, asla `snowball-mcp`'nin değil; `26l`)", flat(page("26c")))
        row = next(line for line in page("27").splitlines() if line.startswith("| Tohum dönemi |"))
        self.assertIn("beyin reposunun, dönemin `spec/tohum`'unu `main`'e getiren teslim commit'i (konusu `Tohum dönemi: "
                      "snowball-mcp <7 hane>`); hiçbir zaman bir `snowball-mcp` commit'i değil (`26l`)", row)


class IntegrationComparisonPointTest(unittest.TestCase):
    def test_13_names_the_cut_rows_base_and_the_null_rule(self):  # cut_point_open_again cut_null_rule_dropped
        text = flat(page("13"))
        self.assertIn("ya da hedefin ilk merge'ünden önce kesim satırının `base_sha`'sı (oyuncakta API'deki `main`'in "
                      "`object.sha`'sı, `29o:45`; seed-093); `null` ise dal yok demektir, her `brain/integration` başı "
                      "kırıktır.", text)
        self.assertNotIn("henüz adlandırılmamıştır", text)
        self.assertIn("Adlandıran satırı olmayan doğrulanmış defter reddedilir (`integration_unnamed`, kurulduğu gibi "
                      "benimsendi).", text)
        self.assertIn("`toy`: API'deki `main`'in `object.sha`'sı, özettekini okumaz", flat(page("29o")))


class SnapshotCasesScorePageTest(unittest.TestCase):
    """`26m`: seed-089, seed-090, seed-091."""

    def test_the_snapshot_items(self):
        # identity_renamed snapshot_id_without_links serialization_unadopted adapter_tool_from_snapshot
        # patterns_writer_invented case_field_added
        text = section("26m", "**Snapshot**", "**Dev vaka seti**")
        for words in ("bir dosyanın yolunda, bir bağın yolunda ya da hedefinde geçiyorsa o vakanın snapshot'ı üretilmez "
                      "ve vaka çıktıda adlandırılır; yol yeniden adlandırılmaz",
                      "Sıkılaştırma; ret kurulduğu gibi benimsendi (`identifier_in_path`).",
                      "bir dosya baytı, dosya yolu, bağ yolu, bağ hedefi ya da çalıştırma biti değişince değişir",
                      "Serileştirme kurulduğu gibi benimsendi (`{files, links, exec}`, sıralı JSON olarak hash'lenir).",
                      "Sayfada zaten vardır: `asama-1/13c:31`. Adapter birimin lint aracına snapshot'tan değil, birimin "
                      "tarifinden", "Sayfada zaten vardır: `01b:36`, `27a:14`.",
                      "Aşama 1'de bu alanın türetme kuralı yoktur: liste boştur", "Hiçbir vaka alanı eklenmez:"):
            self.assertIn(words, text, words)
        self.assertIn("| `profile.json` | Hakem profili hedeften yeniden türetir", page("01b").splitlines()[35])
        self.assertIn("| `profile.json` (`units[]` dahil) | `profile.derive`", page("27a").splitlines()[13])
        self.assertIn("**Bağımlılık.** Birimin tarifindeki bağımlılıklar Aşama 0'ın `deps.fetch`'iyle gelir",
                      (ROOT / "spec" / "asama-1" / "13c-snapshot-uretimi.md").read_text(encoding="utf-8").splitlines()[30])

    def test_the_case_store_items(self):
        # cases_rewrite_allowed cases_not_carried case_rebased cases_founder_writes
        # outside_region_allowed hit_any_reference
        text = section("26m", "**Dev vaka seti**", "**Puanlama**")
        for words in ("`<state_root>/cases/dev.jsonl`: tek JSON-lines dosyası",
                      "dosyadaki bir kimlik yeniden yazılmaz; aynı kimlikle başka içerik reddedilir, düzenleme değildir.",
                      "`yaz` onu devrin tek `brain/state` commit'inde (D6) yazar; sonraki devrin `çek`'i onu `brain/state` "
                      "başından okur ve `pulled`'da taşır",
                      "entegrasyon başının ilerlemesi onu ne geçersiz kılar ne yeniden tabanlar",
                      "Taban commit'i okunamayan vaka puanlanmaz, raporda adlandırılır, sessizce düşmez.",
                      "`cases/` önerisini (`26a:43`) Kurucu kabul etmez ve yazmaz: vaka satırını yalnız `yaz` (hakem "
                      "kodu) yazar, yalnız `cases.build`'in yargısından",
                      "yeni bir (kural, satır) ihlali bırakan mutasyon reddedilir",
                      "bulgunun birincil başvurusu (`evidence_refs[0]`) vakanın aynı `path`'teki bir hunk'ının tamamen "
                      "içindedir", "Hunk'tan geniş başvuru isabet değildir.",
                      "K3 ve üstü \"başvurulardan biri\" kalır"):
            self.assertIn(words, text, words)

    def test_the_scoring_items(self):
        # fingerprint_from_an_agent observation_last pass_without_coverage dev_floor_invented k4_census_built
        text = section("26m", "**Puanlama**", "Açıkça ertelenenler")
        for words in ("Parmak izini yalnız hakem kodu yapar",
                      "bir ajanın dosyasındaki parmak izini hiçbir zaman almaz",
                      "listenin sırasındaki ilk gözlem puanlanır; sonrakiler raporda sayılan yeniden gözlemlerdir, ne "
                      "isabet ne yanlış pozitif",
                      "yoksa `rules_total`'ın (`29za:9-22`: hedefin `census` vektörünün kural kümesi, `26q`) koşuda "
                      "vakası olmayan bir kuralı varsa `UNMEASURABLE`; yoksa `PASS`.",
                      "Dev raporunun grup tabanı yoktur (`26h:67-68`).",
                      "verilmezse çıkış hükmü `PASS` olmaz",
                      "K4'ün sayımı Aşama 3'e ertelendi"):
            self.assertIn(words, text, words)


class OfflineDriftBrakesPageTest(unittest.TestCase):
    """`26n`: seed-092, seed-094, seed-095 and the named deferrals."""

    def test_tests_9_and_11(self):
        # test9_static_alone guard_logging_enough harness_online_writes_a_row test11_needs_code test11_preseeded
        text = section("26n", "**Test 9 ve test 11**", "**Sürükleme etkinliği**")
        for words in ("Statik okuma tek başına satırı karşılamaz.",
                      "sayılması için bir ağ denemesi testi kırmızı yapmalıdır",
                      "`yaz` devri reddeder ve hiçbir şey yazmaz; defter satırı yoktur",
                      "Test 11 döngünün kurulduğu hâliyle bir testidir, `harness/offline.py`'de kod istemez.",
                      "hiçbiri önceden konmaz, hiçbir şey var olmadan okunmaz.",
                      "Test 11'in sözü gevşetilmez (`26e:78-80`)"):
            self.assertIn(words, text, words)

    def test_the_drift_activity_edges(self):
        # activity_time_any_form stale_job_red
        text = section("26n", "**Sürükleme etkinliği**", "**Aşama 1'in bulgu başı frenleri**")
        for words in ("Aykırı bir etkinlik girdisinin nedeni `ref_change`'tir", "ikinci bir ad yoktur",
                      "`YYYY-MM-DDTHH:MM:SSZ`; başka biçim kullanılamaz girdidir.",
                      "tabanın `writer_app_permissions`'ının (`01c:59-60`) tutmadığı bir izni hiçbir zaman istemez",
                      "O duruşta hiçbir şey yazılmaz (`01c:24`), kanal yalnız koşudur",
                      "Arayüz: iş kırmızı bitmez, hiçbir şey yazılmaz"):
            self.assertIn(words, text, words)
        self.assertIn("(uyarının kanalı ve komutun satırı `26n`)", flat(page("01c")))
        self.assertIn("Etkinlik okumasının kalanları (seed-094: zaman biçimi, izin, eski denetim) `26n`'dedir.",
                      flat(page("26i")))

    def test_the_brakes_are_deferred_to_the_owner_at_fixer_llm(self):
        # brakes_keys_required_now brakes_owner_unnamed
        """AF deferred the keys to the owner; the P1 exit epoch (AI, E735) carries the owner's decision of 2026-11-23:
        the keys are named, and required only when P3's table opens."""
        text = section("26n", "**Aşama 1'in bulgu başı frenleri**", "**Açıkça ertelenenler**")
        for words in ("(`asama-1/10:16`; seed-095; sahip kararı (2026-11-23), P1 çıkış dönemi). Karar verildi",
                      "P3'ün tablosu açılınca okunması zorunlu yollardır (`29v`), bu dönemin tesliminde değil.",
                      "`constitutional.stage_params.fix_call_max_usd` `\"0.500000\"`",
                      "`constitutional.stage_params.fix_call_max_s` `300`", "`stage_budgets` değil:"):
            self.assertIn(words, text, words)
        self.assertIn("anahtarları aşağıdaki satırdadır (karar verildi, `26n`, seed-095)", page("18a"))

    def test_the_suspended_threshold_item_is_labelled_l_af1(self):  # l_af1_unlabelled
        """L-AF1 was AF's loosening until the owner decided the keys; it ends with the P1 exit epoch (AI)."""
        text = section("26n", "**Aşama 1'in bulgu başı frenleri**", "**Açıkça ertelenenler**")
        self.assertIn("**L-AF1 bitti** (bu dönemle): `02:22`'nin eşik maddesi (\"her eşik ya `policy.json`'a ya da anayasal "
                      "tabana atıf\") bu hücreye de uygulanır ve hiçbir `spec.lint` bu hücreyi muaf tutmaz.", text)
        self.assertNotIn("o döneme kadar uygulanmaz", text)
        self.assertIn("Gevşetme L-AF1 (geçici; `26n:51-53`; sahibe bildirilir)", register_row("E702"))
        self.assertIn("**L-AF1 bitti**", page("26n").splitlines()[50])

    def test_each_deferral_names_its_epoch_and_reason(self):  # deferral_unnamed_epoch
        text = flat(page("26n").split("**Açıkça ertelenenler**", 1)[1])
        for words in ("K4'ün sayımı (seed-091 (4)) → Aşama 3: K4 orada gelir",
                      # the three "P1 exit epoch" deferrals, decided by that epoch (AI, E735)
                      "`cases/dev.jsonl`'un hash zinciri (seed-090 (1)) → Aşama 1 çıkış partisi",
                      "(seed-091 (1)) → ilk LLM avcısını getiren dönem",
                      "Test 11'in tam yol listesi (seed-092 (4)) → reddedildi",
                      "(seed-094 (3)) → ilk özel hedefin dönemi:",
                      "aşama sınırının yerine kapı: bu okumanın kimliği bir sayfada adlandırılmadan hiçbir özel hedef "
                      "bağlanmaz.", "Sayfalar özel hedefe bir aşama vermez (`01a:23-25`",
                      "`system_tp` vakası üreten ilk partinin dönemi, en geç Aşama 4 (`asama-4/07:29`: panelin TP'si "
                      "`system_tp` vaka adayıdır; bunu o sayfa belirler)", "(seed-090 (3)) → Aşama 2: Aşama 1'de yazıcısı yoktur",
                      "(seed-089 (4)) → \"yorum satırı\"nın tanımıyla aynı dönem",
                      "(seed-089) → `system_tp` vakası üreten ilk partinin dönemi, en geç",
                      "(seed-095) → P1 çıkış döneminde karar verildi"):
            self.assertIn(words, text, words)
        self.assertIn("Kalanları (seed-089–092, seed-094; rapor masası uzlaşısı, 2026-11-22) `26m` ve `26n`'dedir.",
                      flat(page("26e")))


class RecordsTest(unittest.TestCase):
    def test_every_item_of_every_report_has_a_line_whose_cite_holds_it(self):
        # af_item_dropped af_item_cite_moved
        entry = changelog().split("Yanıtlanan raporlar;", 1)[1].splitlines()
        rows = [i for i, line in enumerate(entry) if re.match(r"  `seed-0\d\d-", line)]
        self.assertEqual(len(rows), len(REPORTS))
        for start, end in zip(rows, rows[1:] + [len(entry)]):
            rid = re.match(r"  `([\w-]+)` →", entry[start]).group(1)
            items = [line for line in entry[start + 1:end] if line.startswith("  - ")]
            labels = REPORTS[rid]
            with self.subTest(rid=rid):
                self.assertEqual([lab for lab in labels if not any(it[4:].startswith(lab) for it in items)], [])
                self.assertEqual(len(items), len(labels))  # one line an item, nothing merged
                for item in items:
                    self.assertRegex(item, r"(yanıtlandı|ertelendi: .+|reddedildi) \(")
                    for prefix, first in re.findall(r"`(26[mn]):(\d+)", item)[:1]:
                        label = item[4:7]
                        line = page(prefix).splitlines()[int(first) - 1]
                        if label.startswith("("):
                            self.assertIn(label, line, (rid, item))
        self.assertIn("`26l:41-47`, `26c:30-31`, `27:18`", changelog())
        self.assertIn("Bu", page("26l").splitlines()[40])
        self.assertIn("(seed-096, sıkılaştırma)", page("26l").splitlines()[53])
        self.assertIn("Alanlar sonradan da eklenebilir", page("26l").splitlines()[55])
        self.assertIn("ilk merge'ünden önce kesim satırının", page("13").splitlines()[53])
        self.assertIn("`integration_unnamed`", page("13").splitlines()[55])

    def test_the_answers_file_names_the_eight_from_changelog_15(self):  # af_answer_partial
        answers = json.loads(reportlife.ANSWERS_FILE.read_text(encoding="utf-8"))["answers"]
        af = {r["id"]: r["kind"] for r in answers if r["changelog"] == "CHANGELOG-15"}
        self.assertEqual(af, {rid: "answered" for rid in REPORTS})
        for rid in REPORTS:
            self.assertIn(f"`{rid}` →", changelog())
        loaded = reportlife.load_answers()
        today = [{"stem": i, "id": i, "state": "open", "sha256": "0" * 64} for i in REPORTS]
        self.assertEqual(reportlife.counts(today, loaded), (0, 8))

    def test_this_entry_opens_with_its_first_task_and_the_exit_after_it(self):
        # af_exit_before_mf12 af_changelog_unindexed
        entry = flat(changelog().split("\n- 2.2 (2026-11-22, E698", 1)[1])
        self.assertIn("**İlk iş** (`25` 10b; Kurucu'nun dersi f1741). Teslimden itibaren önyükleme hakeminin hiçbir "
                      "denetimi kırmızı olmaz", entry[:400])
        first = entry.split("Raporların teyidi")[0]
        for words in ("İlk iş `CHANGELOG-14`'ün sırasıdır, değişmeden; Kurucu'nun bugünkü işi sürer:",
                      "1. MF9, izin listesi ve `accept` yazıcısı (`26j`);",
                      "2. birinci maddeden hemen sonra, kırmızı görev değil, sahibin ipuçları (bu kez kural esnetildi; "
                      "`00e`): E693 ve E692, E697 uygulanarak;",
                      "3. MF10, MF11 ve MF12 (`26j`), MF12 sözleşmeleri T1 ve T2 ile (`26k`);",
                      "4. sonra P1'in çıkış isteği. Bu dönemin yanıtları ondan önce yerindedir:"):
            self.assertIn(words, first, words)
        self.assertEqual(len(re.findall(r" [1-9]\. ", first)), 4)
        positions = [first.index(f"{n}. ") for n in (1, 2, 3, 4)]
        self.assertEqual(positions, sorted(positions))
        self.assertIn("Bir gevşetme, geçici: L-AF1 (`26n:51-53`; `02:22`'nin eşik maddesi `asama-1/10:16`'nın bulgu başı "
                      "fren hücresine `fixer.llm`'in (MF4) dönemine kadar uygulanmaz; o dönemde sahip anahtarlara karar "
                      "verince biter)", entry)
        self.assertNotIn("Gevşetme yok", entry)
        index = (ROOT / "spec" / "INDEX.md").read_text(encoding="utf-8")
        for row in ("| `tohum/CHANGELOG-15.md` | Değişiklik Günlüğü — Tohum, 2.2'nin On Dördüncü Kayıtları |",
                    "| `tohum/CHANGELOG-arsiv.md` | Değişiklik Günlüğü — Tohum, Dizinin Arşivi |",
                    "| `tohum/26m-semalar-p1-kalanlar.md` |", "| `tohum/26n-semalar-p1-kalanlar-devam.md` |"):
            self.assertIn(row, index)
        log = (TOHUM / "CHANGELOG.md").read_text(encoding="utf-8")
        af = next(line for line in log.splitlines() if "E698–E703" in line)  # a later epoch's line comes above it (AG)
        self.assertIn("`CHANGELOG-15.md`; başında **İlk iş**.", af)
        self.assertIn("`CHANGELOG-arsiv.md`", log.splitlines()[-1])
        archive = (TOHUM / "CHANGELOG-arsiv.md").read_text(encoding="utf-8")
        for moved in ("- 2.2 (2026-11-14 – 2026-11-15, E585–E599)", "- 2.1 ve öncesi (2026-10-28): `CHANGELOG-1.md`."):
            self.assertIn(moved, archive)
            self.assertNotIn(moved, log)
        self.assertLessEqual(len(log.splitlines()), 70)  # room for the next epochs

    def test_the_register_rows(self):  # e702_closed
        self.assertIn("`reportlife.evidence` `epoch`'u özetin `seed_epochs[].commit` değerlerine karşı da okur",
                      register_row("E698"))
        self.assertTrue(register_row("E698").endswith("| kapandı (tohum dönemi AF) |"))
        self.assertIn("`null` `base_sha`'lı kesim satırı (etkinleştirmede boş `main`) dal yok demektir", register_row("E699"))
        for eid in ("E700", "E701"):
            self.assertIn("kapandı (tohum dönemi AF", register_row(eid))
        self.assertIn("ertelendi, `fixer.llm`'i (Aşama 1 MF4) getiren döneme", register_row("E702"))
        self.assertTrue(register_row("E702").endswith("| kapandı (tohum dönemi AI) |"))  # the owner decided (AI)
        self.assertIn("Aşama 3 (K4 orada gelir); P1 çıkış dönemi", register_row("E703"))
        self.assertTrue(register_row("E703").endswith("| açık (operatörün işi, adlı dönemlerde) |"))
        for eid in ("E698", "E699", "E700", "E701", "E702", "E703"):
            self.assertEqual(register_row(eid).count("|"), 7, eid)


if __name__ == "__main__":
    unittest.main()
