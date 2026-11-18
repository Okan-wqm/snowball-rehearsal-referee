"""``status.exit_b`` (f581's exit audit, f650's document): asama-0/10a's tags each in exactly one place of
``harness.pass_row`` (judged, not checked) or ``WRITTEN``, and ``docs/exit-b.md``'s register current.

The page as it is (the audit holds today, the register section is the one in the document); then made-up pages and
places, each breaking one rule of the audit; the case section's rendering; the command line."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from unittest import mock

REFEREE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REFEREE)

from harness import pass_row as PR  # noqa: E402
from status import exit_b as EB  # noqa: E402

PAGE = EB.read_page()


def page(*cells: str) -> str:
    """A 10a-shaped table: its header row, then one row per first cell."""
    return "\n".join(["| # | Koşul |", "|---|---|"] + ["| %s | x |" % c for c in cells]) + "\n"


def all_cells() -> list[str]:
    return [" ".join(row) for row in EB.page_rows(PAGE)]


class Page(unittest.TestCase):
    def test_the_audit_holds_on_10a(self):
        self.assertEqual(EB.problems(PAGE), [])

    def test_rows_are_read_in_page_order_with_their_tags(self):
        rows = EB.page_rows(PAGE)
        self.assertEqual(rows[0], ("#aktarim",))
        self.assertIn(("#model", "#belirtec", "#prompt"), rows)
        self.assertEqual(rows[-1], ("#pass",))
        self.assertEqual(len(rows), 18)

    def test_the_header_row_is_not_a_condition(self):
        self.assertEqual(EB.page_rows(page("#a #b")), [("#a", "#b")])

    def test_a_page_without_rows_is_unusable(self):
        with self.assertRaises(EB.Unusable):
            EB.page_rows("| # | Koşul |\n|---|---|\n")

    def test_a_first_cell_with_more_than_tags_is_unusable(self):
        with self.assertRaises(EB.Unusable):
            EB.page_rows(page("#genesis ve taban"))

    def test_the_register_in_the_document_is_current(self):
        with open(EB.DOC, encoding="utf-8") as fh:
            doc = fh.read()
        self.assertTrue(EB.render_register(PAGE) in doc,
                      "docs/exit-b.md is stale: regenerate it with 'python tests/test_rehearsal.py --doc' from referee/")


class Audit(unittest.TestCase):
    def test_a_new_10a_tag_nothing_places_is_unplaced(self):
        self.assertEqual(EB.problems(page(*all_cells(), "#yeni")), ["unplaced:#yeni"])

    def test_a_tag_added_to_a_row_is_unplaced(self):
        cells = [c + " #ek" if c == "#kok" else c for c in all_cells()]
        self.assertEqual(EB.problems(page(*cells)), ["unplaced:#ek"])

    def test_a_condition_removed_from_10a_is_not_on_page(self):
        cells = [c.replace(" #prompt", "") for c in all_cells()]
        self.assertEqual(EB.problems(page(*cells)), ["not_on_page:#prompt"])

    def test_a_judged_key_whose_tag_is_gone_is_not_on_page(self):
        cells = [c for c in all_cells() if c != "#durum"]
        self.assertEqual(EB.problems(page(*cells)), ["not_on_page:#durum"])

    def test_one_tag_of_a_two_tag_key_gone_is_not_on_page(self):
        cells = [c.replace(" #hayatta", "") for c in all_cells()]
        self.assertEqual(EB.problems(page(*cells)), ["not_on_page:#nobetci #hayatta"])

    def test_a_tag_both_judged_and_not_checked_is_placed_twice(self):
        with mock.patch.dict(PR.NOT_CHECKED, {"#merge": "somewhere"}):
            self.assertEqual(EB.problems(PAGE), ["placed_twice:#merge"])

    def test_a_tag_written_and_judged_is_placed_twice(self):
        with mock.patch.dict(EB.WRITTEN, {"#kok": "somewhere"}):
            self.assertEqual(EB.problems(PAGE), ["placed_twice:#kok"])

    def test_removing_the_pass_row_writer_leaves_pass_unplaced(self):
        with mock.patch.dict(EB.WRITTEN, {}, clear=True):
            self.assertEqual(EB.problems(PAGE), ["unplaced:#pass"])

    def test_each_tag_is_registered_with_its_place(self):
        reg = EB.render_register(PAGE)
        self.assertIn("| `#model` `#belirtec` `#prompt` | `#prompt` | not checked: %s |" % PR.NOT_CHECKED["#prompt"],
                      reg)
        self.assertIn("| `#nobetci` `#hayatta` | `#hayatta` | judged by `harness.pass_row` (`#nobetci #hayatta`) |",
                      reg)
        self.assertEqual(reg.count("\n| `"), sum(len(r) for r in EB.page_rows(PAGE)))


REPORTS = {"r-a": {"id": "r-a", "state": "open"}, "r-b": {"id": "r-b", "state": "confirmed"}}


def record(gate=None, stopped=None, waiting=("c1",)) -> dict:
    out = {"waiting": list(waiting), "t1": {"gate": gate}}
    if stopped:
        out["stopped"] = stopped
    return out


class Case(unittest.TestCase):
    def test_a_repeat_names_the_run_and_each_judged_condition(self):
        gate = {"verdict": "closed", "conditions": {"#geri-alma": ["toy:x", "toy:y"]}}
        got = EB.render_case("c", "Title", [record(), record(gate), record(gate)], ["r-a"], REPORTS)
        self.assertTrue(got.startswith(EB.CASE_MARK % "c" + "\n### Title\n"))
        self.assertIn("(B) stops at run 3: run 3 repeats run 2. The toy's gate: closed. The copy: waiting "
                      "(never served).", got)
        self.assertIn("| `#geri-alma` | `toy:x`, `toy:y` |", got)
        self.assertIn("| `#kok` | no reason |", got)
        self.assertEqual(got.count("| no reason |"), len(PR.CONDITIONS) - 1)
        self.assertIn("Waits for: `r-a` (open)", got)

    def test_a_stopped_job_and_a_served_copy(self):
        stop = {"job": "yaz", "target": "t1", "reason": "drill_fail", "reasons": []}
        got = EB.render_case("c", "T", [record(None, stop, waiting=())], ["r-b", "r-a"], REPORTS)
        self.assertIn("(B) stops at run 1: `yaz` stopped on `drill_fail` (target `t1`). The toy's gate: not judged "
                      "in that run. The copy: served.", got)
        self.assertIn("Waits for: `r-b` (confirmed), `r-a` (open)", got)

    def test_the_end_is_the_pass_judgement(self):
        judged = {"verdict": "PASS", "conditions": {}}
        last = {"waiting": [], "t1": {"gate": None, "pass": judged}}
        got = EB.render_case("c", "T", [record(), last], [], REPORTS)
        self.assertIn("(B) ends at run 2: `yaz` on `t1` judged its PASS row `PASS`. The copy: served.", got)
        self.assertIn("| judged condition | the PASS judgement's reasons at the end |", got)
        self.assertEqual(got.count("| no reason |"), len(PR.CONDITIONS))
        self.assertIn("Waits for: nothing (the case ends)", got)
        for not_the_end in ({"verdict": "FAIL", "conditions": {"#kok": ["toy:x"]}}, {"waiting": "copy_genesis"}):
            with self.subTest(judged=not_the_end):
                last = {"waiting": [], "t1": {"gate": None, "pass": not_the_end}}
                got = EB.render_case("c", "T", [record(), last], [], REPORTS)
                self.assertIn("(B) stops at run 2: run 2 repeats run 1.", got)
        stop = {"job": "yaz", "target": "t1", "reason": "drill_fail", "reasons": []}
        got = EB.render_case("c", "T", [dict(record(None, stop), t1={"gate": None, "pass": judged})], [], REPORTS)
        self.assertIn("(B) stops at run 1: `yaz` stopped on `drill_fail`", got)  # a stopped job is no end

    def test_a_report_not_in_reports_is_unusable(self):
        with self.assertRaises(EB.Unusable):
            EB.render_case("c", "T", [record()], ["r-z"], REPORTS)

    def test_the_document_holds_the_register_then_the_cases(self):
        doc = EB.render(PAGE, ["<!-- case:a -->\n", "<!-- case:b -->\n"])
        self.assertLess(doc.index(EB.render_register(PAGE)), doc.index("<!-- case:a -->\n<!-- case:b -->"))


class CommandLine(unittest.TestCase):
    def run_cli(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, "-m", "status.exit_b", *args], cwd=REFEREE, capture_output=True,
                              text=True)

    def test_check_prints_the_audit(self):
        got = self.run_cli("check")
        self.assertEqual((got.returncode, json.loads(got.stdout)), (0, {"ok": True, "problems": []}))

    def test_register_prints_the_section(self):
        self.assertEqual(self.run_cli("register").stdout, EB.render_register(PAGE))

    def test_other_arguments_are_refused(self):
        self.assertEqual(self.run_cli("nope").returncode, 2)


if __name__ == "__main__":
    unittest.main()
