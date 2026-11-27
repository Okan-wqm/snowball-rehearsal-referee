"""Seed epoch AL (2026-11-24): the copy target's `census` vector, the operator's open item of `29za:19-22` (E671, E744).
The vector is `vectors.json`'s `census_copy` group: the enabled ESLint rules at the copy's pinned `base_sha`, from
`eslint --print-config` on every lintable file of each unit (`local/census_copy.py`, its record `census_copy.json`);
the copy's set is the units' union, each rule carrying the units it is enabled in. `29za:1-57` do not move; the facts
are appended. The trailing comment on a test names the mutants it kills (`local/mutate.py`)."""

import hashlib
import importlib.util
import json
import sys
import unittest
from pathlib import Path

BOOT = Path(__file__).resolve().parents[1]
ROOT = BOOT.parents[1]
TOHUM = ROOT / "spec" / "tohum"
RECORD = BOOT / "local" / "census_copy.json"
BASE_SHA = "4f479013a42f4b750e0784cc2500bd17d932af1a"  # the referee's setup/summary.json, targets[kind=copy].base_sha
VECTOR_COMMIT = "e273244"  # the commit that adds the census_copy group, as 29za cites it
UNITS = ["platform/libs/outbox", "libs/storage", "web/modules/messaging-module", "web/modules/hr-module"]
TOY_RULES = {"dot-notation", "no-var", "object-shorthand", "operator-assignment", "prefer-const", "prefer-template",
             "yoda"}

SPEC = importlib.util.spec_from_file_location("census_copy", BOOT / "local" / "census_copy.py")
census_copy = importlib.util.module_from_spec(SPEC)
sys.modules["census_copy"] = census_copy
SPEC.loader.exec_module(census_copy)


def page(prefix: str) -> str:
    found = sorted(TOHUM.glob(f"{prefix}-*.md"))
    assert len(found) == 1, (prefix, found)
    return found[0].read_text(encoding="utf-8")


def flat(text: str) -> str:
    return " ".join(text.split())


def register_row(eid: str) -> str:
    rows = (ROOT / "docs" / "eksik-kaydi.md").read_text(encoding="utf-8").splitlines()
    return next(line for line in rows if line.startswith(f"| {eid} |"))


def record() -> dict:
    return json.loads(RECORD.read_text(encoding="utf-8"))


def record_sha256() -> str:
    """The record's sha256 as git stores it (LF; a Windows checkout may hold CRLF)."""
    return hashlib.sha256(RECORD.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def group() -> dict:
    return json.loads((BOOT / "vectors" / "vectors.json").read_text(encoding="utf-8"))["census_copy"]


def rule_of(case: dict) -> str:
    return case["cmd"].split()[-1]


class ReductionTest(unittest.TestCase):
    """`local/census_copy.py`: what enabled means, the union and the case names."""

    def test_enabled_is_warn_or_error(self):  # census_copy_off_enabled census_copy_array_unread
        on = census_copy.severity_on
        for value in (1, 2, "warn", "error", [1], [2, "always"], ["warn", {"x": 1}], ["error"]):
            self.assertTrue(on(value), value)
        for value in (0, "off", [0], ["off", "always"]):
            self.assertFalse(on(value), value)
        for value in ("on", 3, -1, True, False, None, [], ["on"], "Error", 1.5):
            with self.assertRaises(ValueError, msg=repr(value)):
                on(value)
        self.assertEqual(census_copy.enabled({"rules": {"b": [2], "a": "warn", "c": "off", "d": [0, "x"]}}), ["a", "b"])

    def test_the_union_carries_each_rules_units(self):  # census_copy_union_one_unit
        self.assertEqual(census_copy.union({"u2": ["a", "b"], "u1": ["b", "c"]}),
                         {"a": ["u2"], "b": ["u1", "u2"], "c": ["u1"]})
        self.assertEqual(list(census_copy.union({"u": ["z", "a"]})), ["a", "z"])

    def test_case_names_follow_29za(self):  # census_copy_name_keeps_at
        name = census_copy.case_name
        self.assertEqual([name(r) for r in ("dot-notation", "@typescript-eslint/no-explicit-any", "react-hooks/rules-of-hooks",
                                            "@nx/enforce-module-boundaries")],
                         ["dot_notation", "typescript_eslint_no_explicit_any", "react_hooks_rules_of_hooks",
                          "nx_enforce_module_boundaries"])


class CopyVectorTest(unittest.TestCase):
    """The group is the record's union, rule for rule; the record is the derivation at the pinned commit."""

    def test_the_record_is_the_derivation_at_base_sha(self):  # census_copy_record_other_commit
        rec = record()
        self.assertEqual((rec["schema"], rec["repo"], rec["base_sha"], rec["tool"]),
                         ("snowball-census-copy/2", "Okan-wqm/snowball-rehearsal-copy", BASE_SHA, "eslint"))
        versions = rec["versions"]  # read from the run, not written by hand: the pins the run must have used
        self.assertEqual((versions["node"], versions["npm"], versions["eslint"]), ("20.11.0", "10.2.4", "9.39.4"))
        self.assertEqual(list(rec["units"]), UNITS)
        for path in rec["files"]:
            self.assertTrue(any(path.startswith(unit + "/") for unit in UNITS), path)

    def test_the_units_rederive_from_the_committed_rules(self):  # census_copy_unit_rule_dropped
        rec = record()
        for key, rules in rec["rules"].items():
            self.assertEqual(census_copy.sha256(census_copy.canonical(rules)), key)
        per_unit = {}
        for unit in UNITS:
            found = set()
            for path, f in rec["files"].items():
                if not path.startswith(unit + "/") or not f["linted"]:
                    continue
                self.assertRegex(f["raw_sha256"], "^[0-9a-f]{64}$")
                rules = census_copy.enabled({"rules": rec["rules"][f["rules_sha256"]]})
                self.assertEqual(f["enabled"], len(rules), path)
                found.update(rules)
            self.assertEqual(rec["units"][unit]["enabled"], sorted(found), unit)
            per_unit[unit] = sorted(found)
        self.assertEqual(rec["union"], census_copy.union(per_unit))
        used = {f["rules_sha256"] for f in rec["files"].values() if f["linted"]}
        self.assertEqual(used, set(rec["rules"]))  # every committed rules object is some file's, none is missing
        linted = {path.rsplit(".", 1)[-1] for path, f in rec["files"].items() if f["linted"]}
        self.assertIn("json", linted)  # ESLint lints the units' JSON files (the copy's `files: ['**/*.json']`)
        self.assertFalse(any(f["linted"] for path, f in rec["files"].items() if path.endswith((".html", ".css"))))

    def test_the_group_is_the_union(self):  # census_copy_vector_drops_a_rule census_copy_units_unsaid
        g, union = group(), record()["union"]
        self.assertEqual((g["owner"], g["runner"], g["interface"]),
                         ("asama-1-cikis", "data", "spec/tohum/29zc-vektor-arayuzleri-kopyanin-census-vektoru.md"))
        self.assertIn(BASE_SHA, g["source"])
        self.assertEqual([rule_of(case) for case in g["cases"]], list(union))
        names = [census_copy.case_name(rule) for rule in union]
        self.assertEqual(len(names), len(set(names)))
        for case in g["cases"]:
            rule = rule_of(case)
            with self.subTest(rule=rule):
                self.assertEqual(case["id"], "census_copy." + census_copy.case_name(rule))
                self.assertFalse(case["id"].startswith("census."))  # the brain's toy test reads only `census.*`
                self.assertEqual(case["cmd"], f"python -m cases.build produce eslint {rule}")
                self.assertEqual(case["expect"], {"producible": True})
                self.assertEqual(case["changed"]["cmd"], "python -m cases.build produce eslint no-such-rule")
                self.assertEqual(case["changed"]["expect_not"], {"producible": True})
                self.assertTrue(case["purpose"].endswith("enabled in: " + ", ".join(union[rule]) + "."), case["purpose"])

    def test_never_the_toys_seven_nor_the_toy_group_changed(self):
        toy = [rule_of(case) for case in json.loads((BOOT / "vectors" / "vectors.json").read_text(encoding="utf-8"))
               ["census"]["cases"]]
        self.assertEqual(sorted(toy), sorted(TOY_RULES))
        self.assertNotEqual(set(record()["union"]), TOY_RULES)

    def test_no_table_runs_it(self):
        from snowball_bootstrap import stages
        tables = [stages.load(0)] + [stages.load(1, done=stages.BATCHES[1][:i]) for i in range(len(stages.BATCHES[1]))]
        self.assertFalse(any("census_copy" in f.groups for t in tables for f in t.mfs))


class PageTest(unittest.TestCase):
    """The interface page `29zc`: the derivation's facts, read against the record."""

    def test_29zc_states_the_derivation(self):  # census_copy_29zc_count_wrong census_copy_29zc_enabled_off census_copy_29zc_web_unsaid
        text, rec = flat(page("29zc")), record()
        linted = sum(1 for f in rec["files"].values() if f["linted"])
        for words in (f"`base_sha` `{BASE_SHA}`", "`targets[kind=copy].unit_candidates`",
                      "(9.39.4; Node 20.11.0, npm 10.2.4, sürümler koşudan okundu; `npm ci --ignore-scripts`)",
                      f"git'te izlenen {len(rec['files'])} dosyasının her birine soruldu; hangisini lint ettiğine "
                      "ESLint karar verir",
                      f"{linted} dosya, JSON dosyaları dahil; `.html` ve `.css` değil.",
                      'Etkin kural önem derecesi "warn", "error", 1 ya da 2 olandır (dizide ilk öğe); "off" ve 0 '
                      "değildir; başka bir değer türetmeyi durdurur.",
                      f"Kopyanın kümesi birleşimdir (`29za` sonu, E744): {len(rec['union'])} kural",
                      f"(sha256 `{record_sha256()}`)", f"({len(rec['rules'])} nesne)"):
            self.assertIn(words, text, words)
        for unit in UNITS:
            self.assertIn(f"`{unit}` {len(rec['units'][unit]['enabled'])}", text, unit)
        spread = [sum(1 for units in rec["union"].values() if len(units) == n) for n in (4, 3, 2, 1)]
        self.assertIn("(%d'i dört birimde, %d'i üçünde, %d'ü ikisinde, %d'si birinde)" % tuple(spread), text)
        web = [r for r, units in rec["union"].items() if all(u.startswith("web/modules/") for u in units)]
        self.assertIn(f"{len(web)} kural yalnız `web/modules/*` birimlerinde etkindir", text)
        self.assertIn("`29za:15-17`'nin koşulu onların vakalarını bu birimlerde ister.", text)


class RecordsTest(unittest.TestCase):
    """`29za`'s appended paragraph (no cited line moves), the register (E744 new, E671 closed by it), the changelog."""

    def test_29za_lines_stay_and_the_facts_are_appended(self):
        # census_copy_29za_line_moved census_copy_union_reason census_copy_status_unsaid
        lines = page("29za").splitlines()
        self.assertTrue(lines[21].endswith("Bugün açık bir operatör işidir."))  # 29za:22, as it was
        self.assertEqual(lines[56], "  taşır.")  # 29za:57, the end of E743's paragraph, as it was
        self.assertEqual(lines[57], "")
        text = flat("\n".join(lines[57:]))
        self.assertEqual(text.count("**Kopyanın `census` vektörü var**"), 1)
        for words in ("**Kopyanın `census` vektörü var** (tohum dönemi AL, 2026-11-24; E744).",
                      "`29za:22`'nin \"Bugün açık bir operatör işidir\" cümlesi 2026-11-20'nin durumudur.",
                      f"Vektör `vectors.json`'un `census_copy` grubudur (commit `{VECTOR_COMMIT}`), arayüzü `29zc`'dir",
                      f"Kopyanın `base_sha`'sı `{BASE_SHA}`'dır",
                      "kopyanın kümesi birim kümelerinin birleşimidir (operatör kararı, 2026-11-24: bir birime ekilen "
                      "vaka hangi birimde olursa olsun sayılmalıdır) ve her kural etkin olduğu birimleri taşır.",
                      f"Birleşim {len(record()['union'])} kuraldır; oyuncağın yedi kuralı değildir, Kurucu'nun "
                      "kataloğu da değildir.",
                      f"`seed/bootstrap/local/census_copy.json`'dur (sha256 `{record_sha256()}`)"):
            self.assertIn(words, text, words)

    def test_the_register_and_the_changelog(self):  # census_copy_e744_open census_copy_e671_open
        row, rec = register_row("E744"), record()
        self.assertTrue(row.endswith("| E671; E669; E743 | kapandı (tohum dönemi AL) |"), row)
        self.assertIn(f"`census_copy.json` (sha256 `{record_sha256()}`", row)
        self.assertIn("bir birime ekilen vaka hangi birimde olursa olsun sayılmalıdır", row)
        counts = ", ".join(str(len(rec["units"][unit]["enabled"])) for unit in UNITS)
        self.assertIn(f"Birim başına {counts} kural; birleşim {len(rec['union'])}", row)
        self.assertTrue(register_row("E671").endswith("| kapandı (tohum dönemi AL; E744) |"))
        entry = flat((TOHUM / "CHANGELOG-21.md").read_text(encoding="utf-8"))
        for words in ("- 2.2 (2026-11-24, E744; tohum dönemi AL;", "**İlk iş** (`25` 10b).",
                      "bu dönem bir vektör grubu ekler (`census_copy`), hiçbir tablo onu adlandırmaz ve bugün koşmaz",
                      "Gevşetme yok."):
            self.assertIn(words, entry, words)
        log = (TOHUM / "CHANGELOG.md").read_text(encoding="utf-8").splitlines()
        self.assertTrue(log[6].startswith("- 2.2 (2026-11-24, E744; tohum dönemi AL,"))  # the newest entry first
        self.assertTrue(log[6].endswith("`CHANGELOG-21.md`; başında **İlk iş**."))
        self.assertIn("| `tohum/CHANGELOG-21.md` | Değişiklik Günlüğü — Tohum, 2.2'nin Yirminci Kayıtları |",
                      (ROOT / "spec" / "INDEX.md").read_text(encoding="utf-8"))
