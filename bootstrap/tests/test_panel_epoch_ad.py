"""Seed epoch AD (2026-11-22): the report desk's consensus on the report lifecycle (`26l`, E694; loosenings L-AD1,
L-AD2, L-AD3) and seed-087's residuals (`26j`, E695; the deferral E696). Only `spec/tohum` reaches the brain, so each
binding sentence is on a `tohum` page; the counting is `reportlife`'s, one rule for the referee (`decide`) and the
operator's launcher. The trailing comment on a test names the mutants it kills (`local/mutate.py`)."""

import hashlib
import io
import json
import re
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from snowball_bootstrap import cli, reportlife
from snowball_bootstrap.decide import decide

from test_rival_memory import NOW, meta2, state2

BOOT = Path(__file__).resolve().parents[1]
ROOT = BOOT.parents[1]
TOHUM = ROOT / "spec" / "tohum"
EPOCH = "e" * 40
EVIDENCE = {"epoch": EPOCH, "answered_by": ["26l:12-22", "asama-1/13d:19", "26i"], "check": "python3 -m unittest x",
            "check_kind": "read"}
OPEN_IDS = ("seed-070", "seed-072", "seed-073", "seed-074", "seed-075", "seed-076", "seed-077", "seed-078", "seed-079",
            "spec-071", "seed-081", "seed-082", "seed-084", "seed-085", "seed-087", "seed-088")
ROW_RE = re.compile(r"`((?:seed|spec|referee)-[0-9]{3}[\w-]*)` →")  # a CHANGELOG answer row (E527's form)


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
    return (TOHUM / "CHANGELOG-13.md").read_text(encoding="utf-8")


def tar_of(files: dict[str, bytes]) -> bytes:
    tar = io.BytesIO()
    with tarfile.open(fileobj=tar, mode="w") as t:
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            t.addfile(info, io.BytesIO(data))
    return tar.getvalue()


def read(*docs) -> list[dict]:
    """The reports as `pull` reads them (`cli.read_reports`): a document is a dict filed under `<its id>.json`, or a
    (file name, dict or bytes) pair."""
    files = {}
    for doc in docs:
        name, body = doc if isinstance(doc, tuple) else (f"{doc['id']}.json", doc)
        files[f"reports/{name}"] = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")
    return cli.read_reports(tar_of(files))


def report(rid: str, state=None, **fields) -> dict:
    doc = {"id": rid, "kind": "seed_issue", "ref": "spec/tohum/26c-semalar-asama-0.md:50"}
    if state is not None:
        doc["state"] = state
    doc.update(fields)
    return doc


class AnswersFile:
    """A seed answers file in a temporary directory, the shape `reportlife.load_answers` reads."""

    def __init__(self, test: unittest.TestCase, answers=(), carried=()):
        tmp = tempfile.TemporaryDirectory()
        test.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "answers.json"
        self.write({"schema": reportlife.ANSWERS_SCHEMA,
                    "answers": [{"id": i, "changelog": e, "kind": k} for i, e, k in answers],
                    "carried": {"brain": "b" * 40, "confirmed": [{"id": i, "sha256": s} for i, s in carried]}})

    def write(self, doc) -> None:
        self.path.write_text(json.dumps(doc), encoding="utf-8")

    def load(self) -> reportlife.Answers:
        return reportlife.load_answers(self.path)


class ClosedReadingTest(unittest.TestCase):
    """`26l` "Okuma kapalıdır": anything not shown closed counts as open."""

    def counts(self, docs, answers=(), carried=()):
        return reportlife.counts(read(*docs), AnswersFile(self, answers, carried).load())

    def test_an_unknown_or_missing_state_counts_open(self):  # reports_fail_open reports_count_only_exact_open
        for state in ("Open", "answered", "closed", "", None, 7, ["open"]):
            with self.subTest(state=state):
                self.assertEqual(self.counts([report("seed-900", state)]), (1, 0))
        self.assertEqual(self.counts([("seed-901.json", b"{not json"), report("seed-902", "open")]), (2, 0))

    def test_a_report_is_known_by_its_file_name(self):  # id_not_the_file_name
        withdrawn = report("seed-900", "withdrawn")
        self.assertEqual(self.counts([withdrawn]), (0, 0))
        answered = [("seed-900", "CHANGELOG-9", "answered")]
        for name, doc in {"no id": {"state": "withdrawn"}, "another id": dict(withdrawn, id="seed-900-x")}.items():
            with self.subTest(name):
                self.assertEqual(self.counts([("seed-900.json", doc)], answers=answered), (0, 1))
        self.assertEqual(self.counts([("seed-900.json", dict(report("seed-900", "confirmed", **EVIDENCE), id="x"))]),
                         (1, 0))

    def test_a_confirmation_needs_its_typed_evidence(self):
        # confirmed_without_evidence evidence_short_epoch evidence_empty_refs evidence_refs_any_text evidence_blank_check
        # evidence_any_check_kind reader_drops_evidence refs_unbounded ref_length_unbounded
        self.assertEqual(self.counts([report("seed-900", "confirmed", **EVIDENCE)]), (0, 0))
        self.assertEqual(self.counts([report("seed-900", "confirmed", **dict(EVIDENCE, check_kind="test"))]), (0, 0))
        self.assertEqual(self.counts([report("seed-900", "confirmed", **dict(EVIDENCE, answered_by=["26l"] * 50))]),
                         (0, 0))
        broken = {"no evidence": {}, "short epoch": dict(EVIDENCE, epoch="e" * 39), "upper epoch": dict(EVIDENCE, epoch="E" * 40),
                  "abbreviated epoch": dict(EVIDENCE, epoch="6b5966a"), "no refs": dict(EVIDENCE, answered_by=[]),
                  "51 refs": dict(EVIDENCE, answered_by=["26l"] * 51), "long ref": dict(EVIDENCE, answered_by=["a" * 501]),
                  "refs a string": dict(EVIDENCE, answered_by="26l:12"), "bad ref": dict(EVIDENCE, answered_by=["26l: 12"]),
                  "ref with a space": dict(EVIDENCE, answered_by=["26l:12", "see 26k"]),
                  "blank check": dict(EVIDENCE, check="   "), "empty check": dict(EVIDENCE, check=""),
                  "long check": dict(EVIDENCE, check="x" * 501), "other kind": dict(EVIDENCE, check_kind="build"),
                  "no kind": {k: v for k, v in EVIDENCE.items() if k != "check_kind"}}
        for name, fields in broken.items():
            with self.subTest(name):
                self.assertEqual(self.counts([report("seed-900", "confirmed", **fields)]), (1, 0))
                self.assertEqual(self.counts([report("seed-900", "confirmed", **fields)],
                                             answers=[("seed-900", "CHANGELOG-9", "answered")]), (0, 1))

    def test_a_decline_needs_the_operators_decline_and_its_evidence(self):
        # declined_without_operator_decline declined_without_evidence
        declined = report("seed-900", "declined", **EVIDENCE)
        self.assertEqual(self.counts([declined], answers=[("seed-900", "CHANGELOG-9", "declined")]), (0, 0))
        self.assertEqual(self.counts([declined], answers=[("seed-900", "CHANGELOG-9", "answered")]), (0, 1))
        self.assertEqual(self.counts([declined]), (1, 0))
        self.assertEqual(self.counts([report("seed-900", "declined")],
                                     answers=[("seed-900", "CHANGELOG-9", "declined")]), (0, 1))

    def test_a_supersession_closes_only_toward_a_real_successor(self):
        # superseded_successor_any superseded_to_withdrawn superseded_cycle_allowed reader_drops_successor
        # reader_drops_derived_from
        answered = [("seed-900", "CHANGELOG-9", "answered")]
        new = report("seed-901", "open", derived_from="seed-900")
        self.assertEqual(self.counts([report("seed-900", "superseded", superseded_by="seed-901"), new], answered), (1, 0))
        old = report("seed-001", "confirmed", **EVIDENCE)
        cases = {"missing successor": [report("seed-900", "superseded", superseded_by="seed-999"), new],
                 "itself": [report("seed-900", "superseded", superseded_by="seed-900", derived_from="seed-900"), new],
                 "none": [report("seed-900", "superseded"), new],
                 "unrelated report": [report("seed-900", "superseded", superseded_by="seed-001"), old],
                 "successor derived from another": [report("seed-900", "superseded", superseded_by="seed-901"),
                                                    dict(new, derived_from="seed-899")],
                 "withdrawn successor": [report("seed-900", "superseded", superseded_by="seed-901"),
                                         dict(new, state="withdrawn")]}
        for name, docs in cases.items():
            with self.subTest(name):
                owed, unconfirmed = self.counts(docs, answered)
                self.assertEqual(unconfirmed, 1, name)  # seed-900 is still the Founder's
        cycle = [report("seed-900", "superseded", superseded_by="seed-901", derived_from="seed-901"),
                 report("seed-901", "superseded", superseded_by="seed-900", derived_from="seed-900")]
        self.assertEqual(self.counts(cycle, answered), (1, 1))
        chain = [report("seed-900", "superseded", superseded_by="seed-901"),
                 report("seed-901", "superseded", superseded_by="seed-902", derived_from="seed-900"),
                 report("seed-902", "open", derived_from="seed-901")]
        self.assertEqual(self.counts(chain, answered), (1, 0))  # only the newest, which no epoch has named yet

    def test_withdrawal_only_before_an_epoch_names_the_report(self):  # withdrawn_after_naming
        self.assertEqual(self.counts([report("seed-900", "withdrawn")]), (0, 0))
        self.assertEqual(self.counts([report("seed-900", "withdrawn")],
                                     answers=[("seed-900", "CHANGELOG-9", "partial")]), (0, 1))

    def test_carried_confirmations_stay_closed_while_their_bytes_do(self):
        # carried_ignored carried_by_id_alone touched_carried_is_operators
        old = report("seed-008", "confirmed")
        digest = read(old)[0]["sha256"]
        self.assertEqual(digest, hashlib.sha256(json.dumps(old).encode("utf-8")).hexdigest())
        self.assertEqual(self.counts([old], carried=[("seed-008", digest)]), (0, 0))
        touched = dict(old, update_x="a note")
        self.assertEqual(self.counts([touched], carried=[("seed-008", digest)]), (0, 1))  # the Founder's, not owed
        self.assertEqual(self.counts([dict(touched, **EVIDENCE)], carried=[("seed-008", digest)]), (0, 0))

    def test_a_confirmation_after_the_snapshot_without_the_fields_is_unconfirmed(self):
        late = report("seed-900", "confirmed", update_2026_11_22="Confirmed by reading 26l")
        self.assertEqual(self.counts([late], answers=[("seed-900", "CHANGELOG-12", "answered")]), (0, 1))
        self.assertEqual(self.counts([dict(late, **EVIDENCE)], answers=[("seed-900", "CHANGELOG-12", "answered")]),
                         (0, 0))  # the fields added later, the state unchanged


class CountsInTheSignedResultTest(unittest.TestCase):
    """`26l` "İki sayım": what the operator owes and what the Founder owes, warnings and never reasons."""

    def judge(self, meta_reports, answers=()):
        file = AnswersFile(self, answers)
        with mock.patch.object(reportlife, "ANSWERS_FILE", file.path):
            return decide(meta2("none", state2(), **meta_reports), None, None, None, {}, 2, 3, now=NOW)

    def test_the_two_counts_are_warnings(self):
        # owed_counts_answered unconfirmed_not_warned reports_counts_a_reason
        docs = [report("seed-900", "open"), report("seed-901", "open"), report("seed-902", "answered"),
                report("seed-903", "confirmed", **EVIDENCE), report("seed-904", "confirmed")]
        answers = [("seed-901", "CHANGELOG-9", "answered"), ("seed-902", "CHANGELOG-10", "partial"),
                   ("seed-902", "CHANGELOG-11", "answered"), ("seed-903", "CHANGELOG-9", "answered")]
        result = self.judge({"reports": read(*docs)}, answers)
        self.assertIn("reports_open:2", result["warnings"])  # seed-900 and the unproven seed-904
        self.assertIn("reports_unconfirmed:2", result["warnings"])  # seed-901 and seed-902
        quiet = self.judge({"reports": read(report("seed-903", "confirmed", **EVIDENCE))}, answers)
        self.assertFalse([w for w in quiet["warnings"] if w.startswith("reports_")])
        self.assertEqual((result["verdict"], result["reasons"]), (quiet["verdict"], quiet["reasons"]))
        self.assertEqual([sorted(r) for r in result["reports"]], [["id", "kind", "ref", "sha256", "state"]] * 5)

    def test_reports_past_the_cap_count_open(self):  # cap_drops_unread unread_reports_closed decide_ignores_unread
        files = {f"reports/seed-{i:04d}.json": json.dumps(report(f"seed-{i:04d}", "withdrawn")).encode("utf-8")
                 for i in range(cli.MAX_REPORTS + 3)}
        meta = cli.reports_meta(tar_of(files))
        self.assertEqual((len(meta["reports"]), meta["reports_unread"]), (cli.MAX_REPORTS, 3))
        self.assertEqual(sorted(cli.reports_meta(tar_of(dict(list(files.items())[:5])))), ["reports"])  # meta as before
        self.assertIn("reports_open:3", self.judge(meta)["warnings"])


class SeedAnswersFileTest(unittest.TestCase):
    """The operator's typed answers, one source (`seed/bootstrap/reports/answers.json`)."""

    def test_the_shipped_file_names_the_sixteen_open_reports_from_their_changelogs(self):
        # seed_073_y_whole seed_088_wrong_epoch carried_brain_moved answer_dropped_for_a_row
        answers = json.loads(reportlife.ANSWERS_FILE.read_text(encoding="utf-8"))
        loaded = reportlife.load_answers()
        ids = sorted(loaded.kinds)
        self.assertEqual(len(ids), 16)
        self.assertEqual(sorted("-".join(i.split("-")[:2]) for i in ids), sorted(OPEN_IDS))
        for row in answers["answers"]:
            with self.subTest(row=row):
                log = (TOHUM / f"{row['changelog']}.md").read_text(encoding="utf-8")
                self.assertTrue(any(f"`{row['id']}` →" in line for line in log.splitlines()), row)  # one line (E527)
        kinds = {("-".join(r["id"].split("-")[:2]), r["changelog"]): r["kind"] for r in answers["answers"]}
        partial = {k for k, v in kinds.items() if v == "partial"}
        self.assertEqual(partial, {("seed-073", "CHANGELOG-9"), ("seed-085", "CHANGELOG-10"), ("seed-087", "CHANGELOG-11")})
        self.assertEqual(kinds[("seed-073", "CHANGELOG-13")], "answered")
        self.assertEqual(kinds[("seed-087", "CHANGELOG-13")], "answered")
        self.assertEqual(kinds[("seed-085", "CHANGELOG-11")], "answered")
        self.assertNotIn("declined", kinds.values())
        self.assertEqual(answers["carried"]["brain"], "6b5966a98027a6002d8685a6ad42d6a5042ae298")
        self.assertEqual(len(loaded.carried), 73)
        carried = {rid for rid, _ in loaded.carried}
        self.assertFalse(carried & set(ids))
        # the reverse: every report a CHANGELOG-9.. row answers is in the file under that log, or carried
        named = {(rid, row["changelog"]) for row in answers["answers"] for rid in [row["id"]]}
        for n in range(9, 14):
            for rid in ROW_RE.findall((TOHUM / f"CHANGELOG-{n}.md").read_text(encoding="utf-8")):
                with self.subTest(changelog=n, rid=rid):
                    self.assertTrue((rid, f"CHANGELOG-{n}") in named or rid in carried, rid)
        # every open report today is the Founder's to confirm: the operator owes none
        today = [{"stem": i, "id": i, "state": "open", "sha256": "0" * 64} for i in ids]
        self.assertEqual(reportlife.counts(today, loaded), (0, 16))

    def test_a_malformed_answers_file_is_an_error_not_an_empty_list(self):
        # answers_kind_unchecked answers_changelog_unchecked answers_repeat_allowed answers_duplicate_keys
        file = AnswersFile(self, [("seed-900", "CHANGELOG-9", "answered")], [("seed-008", "a" * 64)])
        good = json.loads(file.path.read_text(encoding="utf-8"))
        self.assertEqual(file.load().kinds, {"seed-900": frozenset({"answered"})})
        bad = {"unknown kind": [{"id": "seed-900", "changelog": "CHANGELOG-9", "kind": "confirmed"}],
               "not a log": [{"id": "seed-900", "changelog": "AD", "kind": "answered"}],
               "the old key": [{"id": "seed-900", "epoch": "CHANGELOG-9", "kind": "answered"}],
               "repeated": [{"id": "seed-900", "changelog": "CHANGELOG-9", "kind": "answered"}] * 2,
               "extra key": [{"id": "seed-900", "changelog": "CHANGELOG-9", "kind": "answered", "note": "x"}]}
        for name, rows in bad.items():
            with self.subTest(name):
                file.write(dict(good, answers=rows))
                with self.assertRaises(reportlife.AnswersError):
                    file.load()
        for name, carried in {"short sha": [{"id": "seed-008", "sha256": "a" * 63}],
                              "repeated id": [{"id": "seed-008", "sha256": "a" * 64}, {"id": "seed-008", "sha256": "b" * 64}],
                              "no brain": None}.items():
            with self.subTest(name):
                file.write(dict(good, carried={"brain": "b" * 40, "confirmed": carried} if carried else {"confirmed": []}))
                with self.assertRaises(reportlife.AnswersError):
                    file.load()
        file.path.write_text('{"schema": "x", "schema": "' + reportlife.ANSWERS_SCHEMA + '", "answers": [], '
                             '"carried": {"brain": "' + "b" * 40 + '", "confirmed": []}}', encoding="utf-8")
        with self.assertRaises(reportlife.AnswersError):
            file.load()  # a repeated key is refused, never "the last one wins"


class LifecyclePageTest(unittest.TestCase):
    """`26l`, and `00a`, `26c` and the Founder's prompt pointing at it."""

    def test_26l_states_the_lifecycle(self):
        # states_set_short operator_writes_reports terminal_reopens reading_fail_open withdrawn_any_time
        # answers_two_sources confirm_later confirm_waits_for_build evidence_short_commit l_ad1_unlabelled referee_runs_check
        # residual_in_place counts_are_reasons l_ad3_unlabelled l_ad2_unlabelled carry_by_id id_rule_unsaid
        # superseded_rule_unsaid snapshot_unsaid cap_unsaid changelog_key_epoch
        text = flat(page("26l"))
        for words in ("(rapor masası uzlaşısı (2026-11-22), operatör kararı, sahibin yetkisiyle)",
                      "**Durumlar** (kapalı küme): `open`, `confirmed`, `declined`, `superseded`, `withdrawn`. Hepsini "
                      "Kurucu `reports/<id>.json`'a yazar; operatör, teslim adımı, başlatıcı ve hakem `reports/`'a hiçbir "
                      "şey yazmaz.", "`withdrawn`: Kurucu kendi raporunu geri alır; yalnız hiçbir dönem raporu "
                      "adlandırmadan önce.", "sondur: durum onlardan çıkmaz.",
                      "kapanmamış bir `superseded` ve bir dönemin adlandırdığı `withdrawn` `open` sayılır.",
                      "Rapor dosya adıyla (`.json`'suz) anılır: `id`'si olmayan ya da dosya adından farklı rapor "
                      "`open`'dır.", "`superseded` yalnız ardılı beyindeyse, ardılın `derived_from`'u bu raporun "
                      "`id`'siyse, ardıl `withdrawn` değilse ve `superseded_by` zinciri kendine dönmüyorsa kapanır.",
                      "her yanıt bir girdi `{id, changelog, kind}`'dir. `changelog` dönemin günlüğüdür (`CHANGELOG-<n>`; "
                      "aşağıdaki kanıtın `epoch`'u bir commit'tir, bu değil)",
                      "Girdiyi yalnız operatör yazar; tek kaynaktır.",
                      "Bir girdinin adlandırdığı her rapor, o dönemin tesliminden sonraki ilk oturumda `confirmed`, "
                      "`declined` ya da eksik kalan için açılan yeni bir raporla `superseded` olur.",
                      "Yapım ilerlemesi raporu açık tutmanın nedeni değildir: teyit yanıtı yargılar, yapımı değil",
                      "`seed_epochs[]` satırının tam `commit`'i (40 küçük onaltılık)",
                      "`<sayfa>:<satır>` ya da `<sayfa>:<satır>-<satır>`", "en çok 500 karakter",
                      "ya da `read` (yalnız sayfaları okur, yanıt henüz kurulmamıştır; gevşetme L-AD1)",
                      "Hakem bu alanların biçimini okur, komutu koşmaz;",
                      "Alanlar sonradan da eklenebilir; durum değişmez.",
                      "`derived_from: <eski id>` taşıyan yeni bir rapordur; eski rapor `superseded` olur. Aynı `id` "
                      "içinde yeniden sorulmaz", "İkisi de imzalı sonucun uyarısıdır, hiçbir zaman ret nedeni değildir:",
                      "operatörün borcu (gevşetme L-AD3:", "bir girdinin adlandırdığı ya da taşınan raporlar; Kurucu'nun "
                      "borcu.", "Yol sırasıyla ilk 200 raporun ötesindekiler okunmaz ve `reports_open`'a sayılır.",
                      "**Eski teyitler** (gevşetme L-AD2). Beyin `6b5966a`'da `confirmed` olan 73 rapor tohum verisinde "
                      "`(id, sha256)` olarak taşınır.",
                      "Baytları değişmeyen taşınan rapor yeni kanıt alanları olmadan kapalı kalır; baytları değişen "
                      "taşınan rapor kanıt alanlarını ister, o zamana kadar `reports_unconfirmed`'a sayılır.",
                      "O commit'ten sonra yeni alanlar olmadan yazılan bir teyit taşınmaz: kanıt alanları eklenene kadar "
                      "`reports_unconfirmed`'dadır (bir uyarı)."):
            self.assertIn(words, text, words)
        self.assertEqual(cli.MAX_REPORTS, 200)
        self.assertIn("sen dönemin tesliminden sonraki ilk oturumda teyit edersin (durumlar, kanıt ve iki sayım "
                      "`26l`'dedir)", flat(page("00a")))
        said = flat(page("26c"))
        self.assertIn("açık olanlar `reports_open:<n>` ya da `reports_unconfirmed:<n>` uyarısıyla uyarır", said)
        self.assertIn("ile `reports_open` ve `reports_unconfirmed` sayımları `26l`'dedir.", said)

    def test_the_prompts_duty_points_at_26l(self):  # prompt_duty_d_old
        prompt = flat((ROOT / "seed" / "founder" / "prompt.md").read_text(encoding="utf-8"))
        self.assertIn("(d) bir tohum döneminin yanıtladığı raporunu dönemin tesliminden sonraki ilk oturumda `26l`'ye "
                      "göre kapat.", prompt)
        self.assertNotIn("kendi testinle teyit et", prompt)


class Seed087ResidualsPageTest(unittest.TestCase):
    """`26j` "İzin listesi, MF9: seed-087'nin kalanları"; `26h` points at it."""

    def test_26j_states_the_residuals(self):
        # accept_json_elsewhere accept_change_is_a_record accepted_sha_refusable run_id_local_usable stand_in_live
        # guard_now
        text = flat(page("26j"))
        for words in ("**İzin listesi, MF9: seed-087'nin kalanları** (rapor masası uzlaşısı (2026-11-22), operatör "
                      "kararı, sahibin yetkisiyle)", "**(i) Giriş isteği** beyin kökünde `accept.json`'dur",
                      "`{organ_ids: [farklı, boş olmayan dizgiler]}` taşıyan düz bir dosya; başka biçim `accept_invalid`",
                      "`accept_unknown:<id>` ile reddedilir", "Onu Kurucu commit'ler; kayıt da istek dosyası da değildir, "
                      "onu değiştiren push kod isteğidir (`29b`)",
                      "Önyükleme hakeminin kabul ettiği hiçbir SHA döngünün reddedeceği bir `accept.json` taşımaz.",
                      "imzalı sonucu `run: {id, attempt}` taşır, ikisi de ondalık rakam dizgisi",
                      "`evidence_run_ids` `[run.id]`'dir", "(`local`) sonuç `accept` satırına dayanak olamaz: giriş "
                      "isteği bir organ adlandırıyorsa devir kullanılamaz.",
                      "yalnız genesis merge'ünden koşar", "bu yer tutucu yalnız testlerdedir, canlı yoldan ulaşılamaz.",
                      "**(g)** Listelenmiş çift sonraki SHA'larda listede kalır (L1).",
                      "**(h)** Kapının tanımları kabul edilmiş SHA'daki organlardır (`26a`).",
                      "`accept.json` için aşama koruması yoktur: P1 çıkış dönemine ertelendi, seed-073'ün (a), (c), "
                      "(d)'siyle", "o zamana kadar Kurucu'nun okuması geçerlidir."):
            self.assertIn(words, text, words)
        self.assertIn("Aşama 1 MF5/MF6'dadır. seed-087'nin kalanları sayfanın sonundadır.", text)
        self.assertIn("Giriş isteği `accept.json` ve imzalı sonucun koşu kimliği `26j`'dedir (seed-087).", flat(page("26h")))
        lines = page("26j").splitlines()
        self.assertTrue(lines[66].startswith("**İzin listesi, MF9: seed-087'nin kalanları**"))  # CHANGELOG-13's 26j:67-80
        self.assertTrue(lines[78].startswith("- **(iv)**"))  # and 26j:79-80
        self.assertEqual(len(lines), 80)


class RecordsTest(unittest.TestCase):
    def test_register_names_the_loosenings_the_prompt_and_the_deferral(self):
        # l_ad_unnamed e696_closed prompt_change_unrecorded readme_old_counts
        row = register_row("E694")
        self.assertIn("rapor masası uzlaşısı (2026-11-22; Opus ve Sonnet paneli; operatör kararı, sahibin yetkisiyle", row)
        self.assertIn("**Gevşetmeler** (sahibin yetkisiyle operatör kararı; hiçbiri anayasal değil): L-AD1", row)
        for name in ("L-AD1", "L-AD2", "L-AD3"):
            self.assertEqual(row.count(name), 1, name)
        self.assertIn("`prompt_sha256` değişir, değişiklik AD'nin teslimiyle tek sınırda gelir (yeniden başlatmada tek "
                      "`intervention` satırı)", row)
        self.assertIn("başlatıcı (`seed/founder/launch.py`) aynı okuyucuyu ve aynı `split`'i kullanır", row)
        self.assertIn("kapandı (tohum dönemi AD; teyitler Kurucu'nun", row)
        self.assertTrue(register_row("E696").endswith("| açık (operatörün işi, P1 çıkış dönemi) |"))
        log = flat(changelog())
        for name in ("L-AD1", "L-AD2", "L-AD3"):
            self.assertIn(name, log)
        self.assertIn("istemin `prompt_sha256`'sı değişir ve bu değişiklik AD'nin teslimiyle tek sınırda gelir (yeniden "
                      "başlatmada tek `intervention` satırı)", log)
        readme = flat((ROOT / "seed" / "founder" / "README.md").read_text(encoding="utf-8"))
        self.assertIn("(`reports_open`, `reports_unconfirmed`; hakemin kuralıyla, `26l`, E694; okunamayınca `null`)", readme)
        self.assertNotIn("reports_unanswered", readme)

    def test_this_entry_opens_with_its_first_task_and_states_the_rule(self):
        # ad_first_task_not_first ad_confirmations_a_task ad_hints_before_mf9 ad_rule_unsaid
        entry = flat(changelog().split("\n- 2.2 (2026-11-22, E694–E696", 1)[1])
        self.assertIn("**İlk iş** (`25` 10b; Kurucu'nun dersi f1741). Teslimden itibaren önyükleme hakeminin hiçbir "
                      "denetimi kırmızı olmaz", entry[:400])
        first = entry.split("Yeni `26l`")[0]
        self.assertEqual(len(re.findall(r" [1-9]\. ", first)), 3)
        self.assertLess(first.index("1. MF9, izin listesi"), first.index("2. birinci maddeden hemen sonra"))
        self.assertLess(first.index("2. birinci maddeden hemen sonra"), first.index("3. MF10, MF11 ve MF12"))
        self.assertIn("yeni `reports_unconfirmed` bir uyarıdır, hiçbir zaman neden değildir", first)
        self.assertIn("Raporların teyidi bu listenin bir maddesi değildir, `26l`'nin kuralıdır: bir dönemin yanıtladığı "
                      "her rapor, o dönemin tesliminden sonraki ilk oturumda `confirmed`, `declined` ya da eksik kalan "
                      "için açılan yeni bir raporla `superseded` olur", first)
        rows = changelog().splitlines()
        for rid in ("seed-087-allowlist-package-layout-accept-trigger-and-run-ids-unstated",
                    "seed-073-organ-definition-layout-and-carriage-unstated"):
            self.assertTrue(any(f"`{rid}` →" in line for line in rows), rid)  # one line (E527)
        index = (ROOT / "spec" / "INDEX.md").read_text(encoding="utf-8")
        for name, title in (("26l-semalar-rapor-yasam-dongusu.md", "Şemalar, Devam: Raporların Yaşam Döngüsü"),
                            ("CHANGELOG-13.md", "Değişiklik Günlüğü — Tohum, 2.2'nin On İkinci Kayıtları")):
            self.assertIn(f"| `tohum/{name}` | {title} |", index)
        self.assertIn("`CHANGELOG-13.md`; başında **İlk iş**", flat((TOHUM / "CHANGELOG.md").read_text(encoding="utf-8")))
        for p in list(TOHUM.glob("*.md")) + list((ROOT / "spec" / "asama-1").glob("*.md")):
            self.assertLessEqual(len(p.read_text(encoding="utf-8").splitlines()), 80, p.name)


if __name__ == "__main__":
    unittest.main()
