"""`25` (E678, the operator's gap, izleme 28): the bootstrap referee writes the hashes of the setup summary, `vectors/`,
`seats/` and `policy.json` into every signed result, and stops when the vectors' or the seats' hash differs from the
summary's `drift.hashes` (`01c`). The trailing comment on a test names the mutants it kills (`local/mutate.py`)."""

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from snowball_bootstrap import cli, config, gitio
from snowball_bootstrap.treehash import TreeError, dir_hash, tree_hash

from helpers import make_repo

ROOT = Path(__file__).resolve().parents[3]


def page(prefix: str) -> str:
    found = sorted((ROOT / "spec" / "tohum").glob(f"{prefix}-*.md"))
    assert len(found) == 1, (prefix, found)
    return found[0].read_text(encoding="utf-8")


def flat(text: str) -> str:
    return " ".join(text.split())


class OperatorHashesTest(unittest.TestCase):
    """`25`: every signed result carries the hashes of the summary, the vectors, the seats and the policy; a vectors or
    seats hash that differs from the summary's `drift.hashes` (`01c`) stops the run, with the reason named; a summary
    without `drift` stays usable and the result says nothing was compared."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        for rel, data in {"vectors/vectors.json": b"{}\n", "vectors/x/a.json": b"[1]\n", "seats/29.md": b"# seats\n",
                          "policy.json": b'{"constitutional": {}}\n'}.items():
            (self.root / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.root / rel).write_bytes(data)
        self.base = {"seed_commit": "a" * 40, "seed_tree_sha256": "b" * 64}

    def summary(self, extra=None):
        data = dict(self.base, **(extra or {}))
        (self.root / "setup").mkdir(exist_ok=True)
        (self.root / "setup" / "summary.json").write_text(json.dumps(data), encoding="utf-8")
        return config.load_summary(self.root)

    def drift(self, vectors=None, seats=None):
        return {"drift": {"hashes": {"constitutional_sha256": "c" * 64,
                                     "vectors_sha256": vectors or dir_hash(self.root / "vectors"),
                                     "seats_sha256": seats or dir_hash(self.root / "seats")}}}

    def test_the_check_and_the_operators_baseline_agree(self):  # dir_hash_drops_folders
        """01c: the operator writes `drift.hashes` with `tree_hash` over `git archive HEAD vectors` (and `seats`); the
        check hashes the run's copy of the checkout. On the same tree the two are one value (verified on the referee's
        main at 0564356 on 2026-11-20: both 6ce4701e... and 7a3073ce..., as its summary says)."""
        repo = Path(tempfile.mkdtemp()) / "referee"
        make_repo(repo, {"vectors/vectors.json": b"{}\n", "vectors/x/y/a.json": b"[1]\n", "seats/29.md": b"# s\n",
                         "policy.json": b"{}\n"})
        for folder in ("vectors", "seats"):
            tar = gitio.archive(repo, "HEAD", (folder,))
            self.assertEqual(dir_hash(repo / folder), tree_hash(tar, folder, forbid_operator_names=False), folder)

    def test_the_hash_is_25a_1s_recipe_over_the_folder(self):  # dir_hash_drops_folders dir_hash_follows_links
        lines = sorted(f"{hashlib.sha256(d).hexdigest()}  {r}\n" for r, d in (("vectors.json", b"{}\n"),
                                                                              ("x/a.json", b"[1]\n")))
        self.assertEqual(dir_hash(self.root / "vectors"), hashlib.sha256("".join(lines).encode()).hexdigest())
        self.assertIsNone(dir_hash(self.root / "nowhere"))
        link = self.root / "seats" / "link.md"
        try:
            link.symlink_to(self.root / "policy.json")
        except OSError:
            self.skipTest("no symbolic links here")
        with self.assertRaises(TreeError):
            dir_hash(self.root / "seats")

    def test_without_drift_nothing_is_compared_and_the_hashes_are_written(self):  # hashes_not_in_result drift_absent_stops
        found = cli.operator_hashes(self.root, self.summary())
        self.assertEqual(found["compared"], [])
        self.assertEqual(found["vectors_sha256"], dir_hash(self.root / "vectors"))
        self.assertEqual(found["seats_sha256"], dir_hash(self.root / "seats"))
        self.assertEqual(found["policy_sha256"], hashlib.sha256(b'{"constitutional": {}}\n').hexdigest())
        self.assertEqual(found["summary_sha256"],
                         hashlib.sha256((self.root / "setup" / "summary.json").read_bytes()).hexdigest())
        from snowball_bootstrap.decide import decide
        result = decide(self.meta(found), None, None, None, {}, 2, 3, now="2026-11-20T00:00:00Z")
        self.assertEqual(result["operator_hashes"], found)

    def meta(self, hashes):
        from snowball_bootstrap import state as st
        prev = st.initial(config.Summary("a" * 40, "b" * 64), "2026-11")
        meta = cli._pull_meta("c" * 40, "a" * 40, prev, hashes)
        meta.update(kind="none", evaluate=False)
        return meta

    def test_equal_hashes_pass_and_a_differing_one_stops_with_its_reason(self):  # hash_mismatch_passes seats_unchecked
        found = cli.operator_hashes(self.root, self.summary(self.drift()))
        self.assertEqual(found["compared"], ["vectors_sha256", "seats_sha256"])
        for key, extra in (("vectors", self.drift(vectors="d" * 64)), ("seats", self.drift(seats="d" * 64))):
            with self.subTest(key=key), self.assertRaises(config.ConfigError) as caught:
                cli.operator_hashes(self.root, self.summary(extra))
            self.assertTrue(str(caught.exception).startswith(f"{key}_hash_mismatch:"), str(caught.exception))
        (self.root / "seats" / "29.md").write_bytes(b"# seats, edited\n")  # the folder moved, the summary did not
        with self.assertRaises(config.ConfigError):
            cli.operator_hashes(self.root, self.summary(self.drift(seats=found["seats_sha256"])))

    def test_half_a_baseline_stops_and_a_missing_one_does_not(self):  # drift_hash_form_unchecked
        for drift in ({}, {"hashes": {"vectors_sha256": "a" * 64}}, {"hashes": {"vectors_sha256": "A" * 64,
                                                                               "seats_sha256": "a" * 64}}, []):
            with self.subTest(drift=drift), self.assertRaises(config.ConfigError):
                self.summary({"drift": drift})
        self.assertIsNone(self.summary().drift_hashes)

    def test_pull_stops_before_any_head_is_judged(self):  # pull_skips_hash_check
        self.summary(self.drift(vectors="d" * 64))
        args = type("A", (), {"root": str(self.root), "out": str(self.root / "out")})()
        with mock.patch.object(config, "load_bootstrap"), mock.patch.object(config, "load_policy"), \
                mock.patch.object(cli.gitio, "fetch", side_effect=AssertionError("a head was fetched")), \
                mock.patch.object(cli.stagelock, "open_table", side_effect=AssertionError("the table was read")):
            with self.assertRaises(config.ConfigError) as caught:
                cli.cmd_pull(args)
            self.assertTrue(str(caught.exception).startswith("vectors_hash_mismatch:"))
            self.assertEqual(cli.main(["pull", "--root", str(self.root), "--state", "s", "--work", "w", "--out",
                                       str(self.root / "o")]), 2)

    def test_the_pages_name_the_reference(self):  # hash_reference_unnamed
        text = flat(page("25"))
        for words in ("(sonucun `operator_hashes`'i; böylece Rekor'a girerler)",
                      "**Karşılaştırmanın tabanı** (operatör kararı, 2026-11-20): özetin `drift.hashes.vectors_sha256` "
                      "ve `seats_sha256`'sıdır (`01c`, tek yer)", "(`vectors_hash_mismatch`, `seats_hash_mismatch`), "
                      "Kurucu'ya ret sayılmaz", "`drift`'i henüz yazılmamış özet kullanılabilir kalır",
                      "`compared: []` ile söyler", "`drift` varsa ve iki hash'ten biri yoksa ya da biçimsizse koşu durur"):
            self.assertIn(words, text, words)
        self.assertIn("Önyükleme hakemi `vectors_sha256` ve `seats_sha256`'yı bir başı yargılayan her `pull`'da kendi "
                      "hash'leriyle karşılaştırır, farkta durur (`25`)", flat(page("01c")))


if __name__ == "__main__":
    unittest.main()
