"""Seed epoch U's pages: the own-head exit request (E630) as `29b` and `26c` state it, and the facts the Founder's
reports seed-064 (E632, `24a`) and seed-065 (E631, `07`) were answered with, each named by the changelog, and the owner's outage re-trigger (E633, `25a`). The
behaviour itself is `test_flow`'s (`Flow.test_an_own_head_request_*`, `test_only_a_request_on_top_of_its_own_code_*`)."""

import re
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


class OneRoundExitPagesTest(unittest.TestCase):
    def test_29b_says_which_commit_an_own_head_request_names_and_how_it_is_judged(self):  # own_head_page_unsaid
        text = flat(page("29b").split("**Kendi başını adlandıran istek** (E630)", 1)[1])
        for words in ("bir commit kendi SHA'sını taşıyamaz", "istek başın atası olan ve ondan başa",
                      "yalnız `exit-request.json`'un değiştiği", "Push önce kod push'u olarak yargılanır",
                      "Kod kabul edilmezse çıkış yargılanmaz", "`code_not_accepted`", "çıkış SHA'sı baştır",
                      "`exit.reasons`", "karar kodunkidir", "`exit.pinned_sha` isteğin `sha`'sıdır",
                      "Son kabul edilmiş SHA'yı adlandıran istek eskisi gibidir", "`exit_request_not_alone`"):
            self.assertIn(words, text, words)
        self.assertEqual(len(page("29b").splitlines()), 80)  # appended to line 73: no reference below it moved

    def test_26c_names_the_own_head_form_in_the_request_schema(self):  # own_head_schema_unsaid
        lines = page("26c").splitlines()
        text = flat(" ".join(lines[13:16]))
        self.assertIn("(ya da başın altındaki kendi kodu, `29b` \"Çıkış isteği\", E630)", text)
        self.assertIn("kendi kodunun üstündeki commit'te gelen istek kod push'udur", text)
        self.assertIn("`batch` alanıyla", lines[16])  # line 17 is still the batch's (`26c:17`)


class ReportAnswersTest(unittest.TestCase):
    def test_24a_states_how_the_capsule_image_is_built_and_what_the_referee_runs(self):  # capsule_page_unsaid
        line = page("24a").splitlines()[18]
        for words in ("`seed/founder/Dockerfile`'dır (seed-064, E632)", "özetle sabitli `python:3.12-slim`",
                      "tabanın kendi derlemesi standart kütüphanenin her `*.pyc`'sini siler", "`compileall` ile derler",
                      "`PYTHONDONTWRITEBYTECODE=1`", "`/tmp`, `/home/founder` ve `/work/brain` tmpfs'leridir",
                      "standart kütüphaneyi derlemeden", "bu dönem onu değiştirmez"):
            self.assertIn(words, line, words)
        image = re.search(r"(?m)^FROM (docker\.io/library/python:3\.12-slim@sha256:[0-9a-f]{64})$",
                          (ROOT / "seed" / "founder" / "Dockerfile").read_text(encoding="utf-8"))
        self.assertIsNotNone(image)

    def test_07_states_what_starts_a_revert(self):  # revert_trigger_red_only
        text = flat(" ".join(page("07").splitlines()[34:39]))
        for words in ("Geri almayı başlatan nöbetçinin baştaki kararıdır (seed-065, E631)", "`unknown` dışında",
                      "kırmızı test olmadan da `build_break` ve `lint_regression` geri alınır",
                      "flaky dediği test doğrulanmış kırmızı değildir", "(`rerun`) bir koşu henüz hiçbir şeyi geri almaz"):
            self.assertIn(words, text, words)
        rules = flat(page("29j"))
        self.assertIn("Tutan ilk kural: `build_break` (`build_ok` yanlış); `lint_regression`", rules)
        self.assertIn("`lint_regression` test ve derleme temiz", rules)

    def test_the_changelog_names_both_reports_by_lines_that_say_them(self):  # changelog_drops_seed_064/065
        log = flat((ROOT / "spec" / "tohum" / "CHANGELOG.md").read_text(encoding="utf-8"))
        says = {"seed-064-capsule-stdlib-has-no-bytecode": ("24a", 19, 19, "`compileall` ile derler"),
                "seed-065-revert-trigger-without-red-test-unstated": ("07", 35, 39, "`unknown` dışında")}
        for report, (prefix, first, last, words) in says.items():
            ref = f"`{prefix}:{first}`" if first == last else f"`{prefix}:{first}-{last}`"
            self.assertIn(f"`{report}` → {ref}", log, report)
            self.assertIn(words, flat(" ".join(page(prefix).splitlines()[first - 1:last])), report)
        self.assertIn("`29j:59-60` (`build_ok`'un ve lint toplamının üreticisi Kurucu'nun hakem kodudur)", log)
        # changelog_drops_e633: the owner's decision is named with its page
        self.assertIn("Sahip kararı: `25a` \"Dış kesinti\" (E633; `ETKINLESTIRME.md` 7. adım)", log)
        self.assertIn("üreticisini adlandırmaz", flat(" ".join(page("29j").splitlines()[58:60])))
        raw = (ROOT / "spec" / "tohum" / "CHANGELOG.md").read_text(encoding="utf-8").splitlines()
        for report in says:  # the launcher reads added lines one by one: each id sits whole on one line
            self.assertTrue(any(report in line for line in raw), report)


class OutageRetriggerTest(unittest.TestCase):
    """The owner's decision of 2026-11-17 (E633): a live (B) loop run red only from a named external outage may be
    re-triggered once for that cycle before the failure procedure; operator procedure only, no code check."""

    def test_25a_states_the_one_retrigger_and_when_the_failure_procedure_applies(self):  # outage_retrigger_unsaid
        text = flat(page("25a").split("**Dış kesinti** (sahip kararı, 2026-11-17, E633).", 1)[1].split("**Her yeni", 1)[0])
        for words in ("yalnız adı konmuş bir dış kesinti", "HTTP 5xx ya da bağlantı hatası",
                      "Rekor/Sigstore, npm kayıt deposu, GitHub API'si ya da Actions",
                      "kırmızı işin kendi çıktısında görünür", "o devir için koşuyu Başarısızlık'tan önce bir kez",
                      "Yeniden tetik bir insan dokunuşudur ve kaydedilir", "iki koşunun kimliği",
                      "Yeniden tetiklenen koşu yine kırmızıysa", "beynin kendi mantığından",
                      "Başarısızlık bugünkü gibi uygulanır"):
            self.assertIn(words, text, words)

    def test_the_runbook_audit_of_step_7_carries_it(self):  # outage_retrigger_runbook_unsaid
        runbook = flat((ROOT / "seed" / "founder" / "ETKINLESTIRME.md").read_text(encoding="utf-8"))
        self.assertIn("o devir için yukarıdaki tetikle bir kez yeniden tetikle; bu bir insan dokunuşudur, `pilot-log.md`'ye "
                      "iki koşunun kimliğiyle yaz (`25a` \"Dış kesinti\", E633)", runbook)
        self.assertIn("önce 7. adımın tek yeniden tetiğini alır", runbook)


if __name__ == "__main__":
    unittest.main()
