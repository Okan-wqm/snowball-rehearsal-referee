"""seed-055 (E594): the rival's request size, its unit and the limit it is held to, stated once (`29b` "Rakip
çağrısı") and carried by every signed result's `rival` record, measured before the limit's check, so a session reads its
distance from the limit before a push instead of after a rejection."""

import json
import re
import unittest
from pathlib import Path

from snowball_bootstrap import cli, config, gitio, rival
from snowball_bootstrap.rival import RivalOutcome

from helpers import ok_result, submit
import test_boundaries

ROOT = Path(__file__).resolve().parents[3]
FIELDS = ("prompt_chars", "prompt_diff_chars", "prompt_max_chars")


def page(prefix):
    return next((ROOT / "spec" / "tohum").glob(f"{prefix}-*.md")).read_text(encoding="utf-8")


def flat(text):
    return " ".join(text.split())


class RecordedOnEveryPathTest(test_boundaries.FakeCliMixin, unittest.TestCase):
    def test_every_return_carries_the_size_and_the_limit_measured_before_the_check(self):
        # prompt_chars_not_recorded prompt_chars_recorded_after_the_check prompt_chars_omits_the_protocol
        # prompt_limit_not_recorded
        seat, context = "seat", "ctx " * 10
        size = len(seat) + len(rival.PROTOCOL) + len(context)
        token = "gh" + "p_" + "A" * 36
        cases = {"ok": dict(), "prompt_too_large": dict(max_chars=size - 1),
                 "secret": dict(context=context[:-len(token)] + token), "budget": dict(budget=0),
                 "no_cli": dict(claude_bin=None)}
        for label, kw in cases.items():
            with self.subTest(path=label):
                limit = kw.get("max_chars", 100_000)
                out = self.run_with({"calls": [submit()], "result": ok_result()}, seat=seat,
                                    context=kw.pop("context", context), **kw)
                self.assertEqual((out.prompt_chars, out.prompt_max_chars), (size, limit))
                self.assertEqual({k: out.as_dict()[k] for k in FIELDS},
                                 {"prompt_chars": size, "prompt_diff_chars": None, "prompt_max_chars": limit})
                self.assertEqual("prompt_too_large" in out.reasons, label == "prompt_too_large")

    def test_the_unit_is_the_code_point_and_the_limit_is_inclusive(self):
        # prompt_chars_counts_bytes prompt_limit_exclusive
        system = len("seat") + len(rival.PROTOCOL)
        context = "ıışğ" * 25  # 100 code points, 200 bytes in UTF-8
        out = self.run_with({"calls": [submit()], "result": ok_result()}, context=context, max_chars=system + 100)
        self.assertEqual((out.reasons, out.prompt_chars), ([], system + 100))
        out = self.run_with({"calls": [submit()], "result": ok_result()}, context=context + "ı",
                            max_chars=system + 100)
        self.assertEqual((out.reasons, out.prompt_chars), (["prompt_too_large"], system + 101))

    def test_what_was_not_measured_is_null_never_zero(self):  # prompt_unmeasured_written_as_zero
        self.assertEqual({k: RivalOutcome().as_dict()[k] for k in FIELDS}, dict.fromkeys(FIELDS))


class CmdRivalSizeTest(unittest.TestCase):
    setUp = test_boundaries.CmdRivalGaps.setUp  # the shipped flow's repositories and the fake CLI, not its tests
    run_cmd = test_boundaries.CmdRivalGaps.run_cmd

    def test_the_signed_record_carries_the_diff_the_request_and_the_configured_limit(self):
        # prompt_diff_chars_not_recorded prompt_diff_chars_is_the_whole_context prompt_fields_dropped_from_the_record
        diff = (self.pulled / "diff.patch").read_text(encoding="utf-8")
        _rc, record = self.run_cmd({"calls": [submit()], "result": ok_result()})
        stdin = json.loads((self.bin_dir / "seen.json").read_text())["stdin"]
        seat = rival.extract_seat_prompt((self.flow.referee / "seats" / cli.SEATS_FILE).read_text(encoding="utf-8"))
        self.assertEqual(record["prompt_diff_chars"], len(diff))
        self.assertGreater(len(diff), 0)
        self.assertEqual(record["prompt_chars"], len(seat) + len(rival.PROTOCOL) + len(stdin))
        self.assertGreater(record["prompt_chars"], record["prompt_diff_chars"])
        self.assertEqual(record["prompt_max_chars"], 600_000)
        doc = json.loads((self.flow.referee / "bootstrap.json").read_text())
        doc["limits"]["max_prompt_chars"] = 10
        (self.flow.referee / "bootstrap.json").write_text(json.dumps(doc))
        _rc, record = self.run_cmd({"calls": [submit()], "result": ok_result()})
        self.assertEqual((record["reasons"], record["prompt_max_chars"], record["prompt_diff_chars"]),
                         (["prompt_too_large"], 10, len(diff)))
        self.assertGreater(record["prompt_chars"], 10)


class PageTest(unittest.TestCase):
    def setUp(self):
        text = page("29b")
        start = text.index("**Rakip çağrısı.**")
        self.raw = text[start:text.index("\n\n", start)]
        self.text = flat(self.raw)
        self.lines = text.splitlines()

    def test_29b_states_what_is_counted_its_unit_the_limit_and_the_three_fields(self):
        # rival_page_drops_the_unit rival_page_drops_a_size_field rival_page_drops_the_limit_key
        # rival_page_drops_the_binary_diff
        self.assertIn("İstemin Unicode kod noktası sayısı `bootstrap.json` "
                      "`limits.max_prompt_chars`'ı aşarsa rakip çağrılmaz (`prompt_too_large`)", self.text)
        self.assertIn("max_prompt_chars", config.Limits.__dataclass_fields__)
        named = set(re.findall(r"`(prompt_[a-z_]+)`", self.text)) - {"prompt_too_large"}
        self.assertEqual(named, set(FIELDS))
        self.assertEqual(set(FIELDS) <= set(RivalOutcome().as_dict()), True)
        self.assertIn("sonucun `rival` kaydı her koşuda", self.text)
        self.assertIn("son kabulden bu yana `--binary` diff", self.text)
        self.assertIn('"--binary"', Path(gitio.__file__).read_text(encoding="utf-8"))
        for part in ("koltuk metni", "protokol", "değişen yollar", "ilgili sayfalar", "açık iddialar"):
            self.assertIn(part, self.text)

    def test_the_paragraph_kept_its_lines_and_what_points_into_it(self):
        self.assertEqual(len(self.raw.splitlines()), 9)
        self.assertEqual(len(self.lines), 80)
        self.assertTrue(self.lines[45].startswith("**Rakip çağrısı.**"))
        self.assertIn("`--max-budget-usd`", " ".join(self.lines[45:48]))  # `29m:68` cites `29b:46-48`
        self.assertIn("slash", " ".join(self.lines[45:48]))
        self.assertTrue(self.lines[53].endswith("Sır desenli metin: `29e`."))  # `CHANGELOG-4.md:42` cites `29b:54`
        self.assertIn("`prompt_too_large`", self.lines[60])  # the rejection memory (`29b:61`, seed-055's ref)
        self.assertTrue(all(len(line) <= 120 for line in self.raw.splitlines()))

    def test_what_left_the_paragraph_has_its_one_source(self):
        # identity_source_drops_the_token ledger_source_drops_the_rival
        """The rewrite took three restatements out; each fact stays where it is stated (E594)."""
        self.assertIn("iç kullanımda operatörün `CLAUDE_CODE_OAUTH_TOKEN`'ı, satışta API anahtarı", page("24"))
        self.assertIn("Rakip ikisini de görmez.", flat(page("29e")))
        self.assertIn("kimlik, kota (abonelik penceresi, HTTP 429), ağ hatası, zaman aşımı ve 5xx altyapı "
                      "arızasıdır: ret sayılmaz", page("24"))
        self.assertIn("Kurucu kayıtları: `29e`.", page("29b"))
        self.assertIn("`request_rejected`", " ".join(page("25").splitlines()[41:44]))


class AnsweredTest(unittest.TestCase):
    def test_the_changelog_names_seed_055_with_the_lines_that_answer_it(self):  # changelog_drops_seed_055
        from test_founder_capsule import load_launch
        launch = load_launch()
        rid = "seed-055-prompt-limit-not-stated"
        log = (ROOT / "spec" / "tohum" / "CHANGELOG-8.md").read_text(encoding="utf-8")  # moved by the cap (E634)
        self.assertTrue(any(f"`{rid}`" in line for line in log.splitlines()))  # whole, on one line
        entry = flat(log)
        self.assertIn(f"`{rid}` → `29b:47-50`", entry)
        lines = flat(" ".join(page("29b").splitlines()[46:50]))
        for phrase in ("İstem:", "Unicode kod noktası", "`limits.max_prompt_chars`", "`prompt_too_large`",
                       "`prompt_chars`", "`prompt_diff_chars`", "`prompt_max_chars`"):
            self.assertIn(phrase, lines, phrase)


if __name__ == "__main__":
    unittest.main()
