"""Seed epoch Z (2026-11-20): the owner's decisions on Stage 1's first slice (O1) and on the release of the outside
review's three table corrections (O3), the operator's answer to seed-081, the independent review panel's answer to F13,
the owner's hint on reading by search (E676) and the mirror's page (E677); the code of the mirror is tested in
`test_mirror`, the operator's hash check of the summary's vectors and seats (`25`, E678) in `test_operator_hashes`. Only `spec/tohum` reaches the brain, so each binding sentence is on a `tohum` page;
the seed's copy of `asama-1` is aligned and the Founder reconciles its own (E180). The trailing comment on a test
names the mutants it kills (`local/mutate.py`)."""

import json
import re
import tempfile
import unittest
from pathlib import Path

from snowball_bootstrap import config, parts, stages
from snowball_bootstrap.container import RunResult

from helpers import definition, load_brain_defs, tree_repo

BOOT = Path(__file__).resolve().parents[1]
ROOT = BOOT.parents[1]


def page(prefix: str) -> str:
    found = sorted((ROOT / "spec" / "tohum").glob(f"{prefix}-*.md"))
    assert len(found) == 1, (prefix, found)
    return found[0].read_text(encoding="utf-8")


def stage1(name: str) -> str:
    return next((ROOT / "spec" / "asama-1").glob(f"{name}-*.md")).read_text(encoding="utf-8")


def flat(text: str) -> str:
    return " ".join(text.split())


def section(prefix: str, title: str) -> str:
    """The flattened paragraph of a page that starts with ``title`` in bold, up to the next bold paragraph."""
    text = flat(page(prefix))
    return text.split(f"**{title}**", 1)[1].split(" **", 1)[0]


def register_row(eid: str) -> str:
    rows = (ROOT / "docs" / "eksik-kaydi.md").read_text(encoding="utf-8").splitlines()
    return next(line for line in rows if line.startswith(f"| {eid} |"))


def changelogs() -> str:
    return flat("\n".join(p.read_text(encoding="utf-8") for p in sorted((ROOT / "spec" / "tohum").glob("CHANGELOG*.md"))))


class FirstSliceTest(unittest.TestCase):
    """O1, the owner's decision of 2026-11-20: Stage 1's first slice is deterministic and its referee rows are owned."""

    def test_the_slice_has_no_llm_and_keeps_the_numbers(self):  # slice_llm_first slice_mf4_before_merge
        text = section("26h", "İlk dilim deterministiktir")
        for words in ("(sahip kararı (2026-11-20))", "İlk düzeltme yolunda LLM yoktur",
                      "sonra Aşama 1'in kendi MF1'i `lint.discover`, MF2'si taban, MF3'ü `fixer.range`, MF5'i "
                      "`candidate.publish` ve MF6'sı izin listesi girişi",
                      "Aşama 1'in MF'leri numaralarını korur; MF4 `fixer.llm` ilk organ merge'ünden sonradır"):
            self.assertIn(words, text, words)
        order = flat(stage1("06"))
        positions = [order.index(f"- MF{k}.") for k in (1, 2, 3, 5, 6)]
        self.assertEqual(positions, sorted(positions))
        self.assertLess(order.index("- MF6."), order.index("**Sonra: P3 partisi**"))
        self.assertLess(order.index("**Sonra: P3 partisi**"), order.index("- MF4. `fixer.llm`"))
        self.assertIn("ilk dilim deterministiktir, ilk düzeltme yolunda LLM yoktur", order)

    def test_p1_owns_the_findings_writer_and_the_allowlist(self):  # findings_writer_unowned allowlist_trusts_package
        text = section("26h", "P1'in iki yeni satırı")
        for words in ("İkisi de hakem kodudur, bu yüzden oyuncu MF'si değil parti satırıdır",
                      "Gözcü (P1 MF7) önlerinde kalır; üçü de ilk organ merge'ünden öncedir",
                      "MF1–MF7'nin numaraları değişmez"):
            self.assertIn(words, text, words)
        rows = flat(page("26h"))
        for words in ("**MF8, bulgu yazıcısı** (`findings.write`; modül `findings/write.py`; test 12)",
                      "`<state_root>/findings.jsonl`'u adapter önerisinden, `<state_root>/unresolved.jsonl`'u kapı "
                      "kararından hakem yazar (`26`)", "Parmak izi `asama-1/13d` ve `07`'deki gibidir, satır girmez",
                      "Test 12 MF4'ten buraya taşındı; numarası korunur",
                      "**MF9, izin listesi ve `accept` yazıcısı** (`gate.allowlist`; modül `gate/allowlist.py`; test 55)",
                      "Kapı, tanım hash'i hiçbir `accept` satırında olmayan organın adayını reddeder",
                      "Karşılaştırılan hash, hakemin kabul edilmiş SHA'daki organ dosyalarından tek hash fonksiyonuyla "
                      "kendi hesapladığıdır (`26e` \"Organ tanımının hash'i\"), aday paketinin `definition_sha256[]` "
                      "beyanı değildir", "adayın beyan ettiği hash kararı değiştirmez",
                      "§0.9'un donmuş tablosunda 52'nin partisi `P1` yazılı kalır; bu sayfa ondan üstündür (`02`)"):
            self.assertIn(words, rows, words)

    def test_the_table_carries_the_two_rows_and_test_12_moved(self):  # p1_test12_left_in_score p1_mf9_dropped mcnemar_withdrawn
        table = stages.load(1)
        self.assertEqual((table.count, [f.mf for f in table.mfs]), (12, list(range(1, 13))))  # MF10-MF12: E688
        self.assertEqual((table.feature(8).tests, table.feature(8).module), ((12,), "findings/write.py"))
        self.assertEqual((table.feature(9).tests, table.feature(9).module), ((55,), "gate/allowlist.py"))
        self.assertEqual(table.feature(4).tests, (1, 6, 7, 28))
        self.assertEqual(table.feature(4).groups, ("match", "cp_lower", "mcnemar"))  # accepted with MF4, kept
        self.assertEqual([f.module for f in table.mfs[:7]], ["runner/organs.py", "snapshot/make.py", "cases/build.py",
                                                            "harness/score.py", "harness/offline.py", "drift/check.py",
                                                            "gozcu/evaluate.py"])  # MF1-MF7 as accepted
        self.assertNotIn(52, [n for f in table.mfs for n in f.tests])
        frozen = (ROOT / "spec" / "asama-0" / "09-harness-in-kendi-testleri.md").read_text(encoding="utf-8")
        numbered = [int(n) for n in re.findall(r"^\| (\d+) \|", frozen, re.M)]
        self.assertEqual(max(numbered), 52)  # 55 is a new number: 53 is 30d's, 54 29za's
        self.assertTrue(re.search(r"^\| 52 \| .* \| P1 \|$", frozen, re.M))  # frozen, and 26h prevails
        for line in ("| `findings.write` | Hakem | `yaz` |", "| `gate.allowlist` | Hakem | `yaz` |"):
            self.assertIn(line, page("26a"))
        self.assertIn("| — (bulgu satırları) | `<state_root>/findings.jsonl` | Hakem, adapter önerisinden "
                      "(`findings.write`) | P1 MF8 (`26h`) |", page("26"))
        self.assertIn("| P1; P1 MF9, ilk satırı Aşama 1 MF6'da (`26h`); P2 (`asama-1/13`) |", page("26"))

    def test_what_waits_for_the_first_organ_merge(self):  # operating_tuned_in_p1 round_trip_in_p1 p3_rows_in_p1
        text = section("26h", "İlk organ merge'ünden sonraya ertelenenler")
        for words in ("Ertelenenler P3 partisidir: Aşama 1 MF6'dan ve P2'den sonra, MF4 `fixer.llm`'in canlı "
                      "koşusundan önce", "P3'ün tablosu bir tohum döneminde gelir; bu tohum onu taşımaz"):
            self.assertIn(words, text, words)
        rest = flat(page("26h"))
        for words in ("**Eski P1 MF8**, `operating{}` sınırlarının bant içinde ayarı (test 52): sahip kararıyla "
                      "ertelendi.", "**Düzeltme gidiş-dönüşü** `koş` → `çağır` → `koş`",
                      "Bugün `çağır` yalnız (B)'nin kanaryasını çağırır (`asama-0/01`)",
                      "`fixer.llm` (MF4) bu satırla birlikte gelir",
                      "P1 K0 dalını uygular: `match` vektörleri K0'dır, testler 3 ve 5 \"K3 ile\"dir",
                      "`mcnemar` grubu MF4'le kabul edildi ve MF4'ün satırında kalır",
                      "İlk organ merge'ünden önce McNemar'ın yeni bir işi ya da okuyucusu yoktur"):
            self.assertIn(words, rest, words)
        self.assertEqual(stages.BATCHES[1], ("P1", "P2"))  # P3 has no table in this seed
        self.assertFalse((stages.STAGES_DIR / "stage1-P3.json").exists())
        self.assertIn("ayarı P3'le gelir (`26h`)", flat(page("18a")))
        self.assertIn("bant içinde ayar P3'le gelir (`26h`)", flat(page("26c")))
        thirteen = stage1("13")
        self.assertIn("| P3 | 1 | `operating{}` sınırlarının bant içinde ayarı", thirteen)
        self.assertIn("| P3 | 2 | Düzeltme gidiş-dönüşü `koş` → `çağır` → `koş`", thirteen)
        self.assertIn("ilk organ merge'üne kadar düzeltme yolunda LLM yoktur", flat(stage1("05")))
        self.assertIn("Yazıcısı `findings.write`, P1 MF8'dir (`tohum/26h`)", flat(stage1("13d")))

    def test_26e_points_at_26h(self):  # p1_rows_unpointed
        text = flat(page("26e"))
        self.assertIn("53 ve 55 onun numaralarının devamıdır", text)
        self.assertIn("55'inki `26h`'dedir", text)
        self.assertIn("P1'in MF8'i ve MF9'u ve ilk dilimin sırası `26h`'dedir (sahip kararı (2026-11-20))", text)
        self.assertIn("Ertelenen P3'ün tablosu da öyle gelir (`26h`)", text)


class ReleaseAndProducerTest(unittest.TestCase):
    """O3: H1-H3 labelled as the outside review's table corrections; what is held stays out of the seed."""

    def test_h1_h3_are_table_corrections_the_review_found(self):  # release_unlabelled
        text = section("26h", "Bırakma")
        for words in ("(sahip kararı (2026-11-20))", "P1 MF8 (H1), P1 MF9 (H2) ve düzeltme gidiş-dönüşü (H3)",
                      "dış göz incelemesinin (2026-11-20, iki inceleyicinin uzlaşısı) bulduğu tablo düzeltmeleridir",
                      "Kurucu'nun bir raporundan gelmezler"):
            self.assertIn(words, text, words)
        whole = flat(page("26h"))  # held for measurement, never delivered (the 2026-11-20 review of epoch Z)
        for held in ("E665", "beklemesi", "üreticisi olmayan", "Üreticisi olmayan", "çıkış satırı, ölçüsünü"):
            self.assertNotIn(held, whole, held)


class ManifestTimeLimitTest(unittest.TestCase):
    """seed-081: the time limit of a manifest command, on the page that describes `koş` (`29b`)."""

    def test_29b_names_the_limit_and_where_it_is(self):  # seed081_limit_shared seed081_runner_assumes
        row = next(line for line in page("29b").splitlines() if line.startswith("| `koş` |"))
        text = flat(row)
        for words in ("**Bildirim komutunun süresi** (operatör yanıtı, arayüz olgusu, seed-081)",
                      "`snowball-tests.json`'un her komutu ayrı ayrı, paylaşmadan en çok hakem reposunun operatör "
                      "dosyası `bootstrap.json`'un `limits.test_timeout_s` saniyesi koşar (bugün 600; dosya operatörün "
                      "ve herkese açıktır)", "aşan komut öldürülür, satırı `exit` 124 ve `timed_out: true` taşır ve test "
                      "kırmızıdır", "sonucun her test satırı `duration_ms`'i ve `timed_out`'u yazar",
                      "Komutlar yere göre dört parçaya bölünür, her parçanın işi en çok 60 dakikadır",
                      "Yerel bir koşucu bu sınırı dosyadan okur, varsaymaz"):
            self.assertIn(words, text, words)

    def test_the_facts_29b_states(self):
        """Each command runs with the limit alone (never a shared budget), a timed-out one is red with exit 124, and the
        record carries its duration; the key is the operator file's; the parts' job has 60 minutes."""
        self.assertIn("test_timeout_s", config.Limits.__dataclass_fields__)
        seen = []

        class Runner:
            def run(self, cmd, timeout_s, **kw):
                seen.append(timeout_s)
                return RunResult(124, b"", b"", 600_162, timed_out=True)
        record = parts.test_record({"id": "T46", "cmd": "x"}, Runner().run("x", timeout_s=600))
        self.assertEqual((record["exit"], record["timed_out"], record["duration_ms"], record["ok"]),
                         (124, True, 600_162, False))
        workflow = (BOOT / "workflow" / "bootstrap.yml").read_text(encoding="utf-8")
        job = re.search(r"(?ms)^  kos_parca:\n(.*?)(?=^  \S)", workflow).group(1)
        self.assertIn("timeout-minutes: 60", job)
        self.assertIn("part: [0, 1, 2, 3]", job)
        source = (BOOT / "snowball_bootstrap" / "parts.py").read_text(encoding="utf-8")
        self.assertIn("runner.run(t[\"cmd\"], timeout_s=test_timeout_s)", source)  # per command, the same limit


class ProvenanceTest(unittest.TestCase):
    """F13 (independent review panel, 2026-11-20): an agent's or a skill's provenance is in its body; the loader's rule
    that only known front-matter keys are taken stands."""

    def test_09_says_where_provenance_lives(self):  # provenance_in_frontmatter
        text = section("09", "Kökenin yeri")
        for words in ("(bağımsız inceleme ekibi kararı, 2026-11-20)",
                      "Ajan ya da skill dosyası kökenini (boşluk, ölçüm, aşama) gövdesinde, ön maddeden sonraki metinde "
                      "yazar", "bu kural değişmez, köken ön maddeye yazılmaz",
                      "Bir dosya kendi hash'ini taşıyamaz: \"tanım hash'ini taşır\" dosyanın dışındaki kaydıdır",
                      "yükleme kaydının (`/work/logs/brain-definitions.json`) kaynak sha256'sıdır, organlarda "
                      "`accept` satırıdır (`26h`)"):
            self.assertIn(words, text, words)

    def test_a_body_carries_provenance_and_a_key_does_not(self):
        """What the page says is what the loader does: provenance in the body loads; a provenance key drops it."""
        defs = load_brain_defs()
        tmp = Path(tempfile.mkdtemp())
        body = "Köken: boşluk X, ölçüm Y, Aşama 1.\nYou review.\n"
        tree_repo(tmp / "brain", {"agents/reviewer.md": definition("reviewer", body=body),
                                  "agents/tagged.md": definition("tagged", extra={"provenance": "gap X"}),
                                  "skills/probe/SKILL.md": definition("probe", body=body)})
        record = defs.build(tmp / "brain", tmp / "plugin").record()
        self.assertEqual([a["name"] for a in record["agents"]], ["reviewer"])
        self.assertEqual([s["name"] for s in record["skills"]], ["probe"])
        self.assertIn("Köken: boşluk X", (tmp / "plugin" / "agents" / "reviewer.md").read_text(encoding="utf-8"))
        self.assertEqual(record["skipped"], [{"path": "agents/tagged.md", "reasons": ["key_not_allowed:provenance"]}])
        self.assertRegex(record["agents"][0]["sha256"], r"^[0-9a-f]{64}$")  # the record outside the file


class SearchReadingHintTest(unittest.TestCase):
    """The owner's hint of 2026-11-20 (E676), labelled, text only, in `00d`."""

    def test_the_hint_is_labelled_and_leaves_the_design_open(self):  # search_hint_prescribes
        text = flat(page("00d")).split("**Sahibin ipucu (2026-11-20, E676; ipucu, reçete değil). Arama ile okuma.**", 1)[1]
        for words in ("2.500'den fazla API uç noktasını iki araçla, arama ve çalıştırma ile, yaklaşık 1.000 belirteçte "
                      "sunar; hepsini yüklemek yaklaşık 1,17 milyon belirteç tutardı",
                      "en az bir sıkıştırma (compaction) var (transkriptin `compact_boundary` olayı)",
                      "İpucu: her model için arama tabanlı okuma", "Bunu kurarsa tasarım Kurucu'nundur",
                      "kurarsa kendisi ölçer: oturum başına bağlam, sıkıştırma sayısı ve doğruluk, onunla ve onsuz"):
            self.assertIn(words, text, words)
        self.assertIn("sahip kararı, ipucu (2026-11-20", register_row("E676"))


class MirrorPageTest(unittest.TestCase):
    def test_26h_names_the_mirrors_new_facts(self):  # mirror_page_advises
        text = section("26h", "Ölçüm aynası")
        for words in ("(operatör kararı, 2026-11-20)", "`session_time` bölümü oturum başına `wall_s`, `api_s`, "
                      "`blocked_on_own_checks_s`", "`path` bölümü bu dilimin henüz kabul edilmemiş MF'lerini "
                      "(`path_mfs_left`) ve `organ_merges_copy`'yi verir", "Yalnız olgudur",
                      "Türetilemeyen değer `null`'dır ve nedeni yazılıdır"):
            self.assertIn(words, text, words)


class RecordsTest(unittest.TestCase):
    def test_register_changelog_index_and_caps(self):
        for eid, decided in (("E672", "sahip kararı (2026-11-20"), ("E673", "sahip kararı (2026-11-20"),
                             ("E674", "operatör yanıtı"), ("E675", "bağımsız inceleme ekibi kararı (2026-11-20"),
                             ("E677", "operatör kararı (2026-11-20"), ("E678", "operatör kararı (2026-11-20")):
            with self.subTest(eid=eid):
                self.assertIn(decided, register_row(eid))
        self.assertIn("`seed-081-the-time-limit-of-a-manifest-command-is-on-no-page` → `29b:24`", changelogs())
        self.assertIn("2.2 (2026-11-20, E672–E678", changelogs())
        index = (ROOT / "spec" / "INDEX.md").read_text(encoding="utf-8")
        self.assertIn("| `tohum/26h-semalar-asama-1-ilk-dilim.md` | Şemalar, Devam: Aşama 1'in İlk Dilimi |", index)
        for p in list((ROOT / "spec" / "tohum").glob("*.md")) + list((ROOT / "spec" / "asama-1").glob("*.md")):
            self.assertLessEqual(len(p.read_text(encoding="utf-8").splitlines()), 80, p.name)


if __name__ == "__main__":
    unittest.main()
