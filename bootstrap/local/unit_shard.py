"""One shard of the referee's unit tests, so a slow runner ends every shard inside the job's timeout (E501).
The suite is what `unittest discover -s tests` finds, `load_tests` included; its test classes are sorted by name and
dealt out in turn, so the shards are disjoint, their union is the whole suite, and a class's tests (and its
setUpClass) stay together. A test that fails to import is a class of its own and runs in some shard.
    cd seed/bootstrap && PYTHONPATH=.:tests python local/unit_shard.py K/N [--list]
Exit 0 means every test of the shard passed.
"""
from __future__ import annotations

import argparse
import sys
import unittest
from pathlib import Path

BOOT = Path(__file__).resolve().parents[1]


def flatten(suite: unittest.TestSuite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from flatten(item)
        else:
            yield item


def class_of(test: unittest.TestCase) -> str:
    return f"{type(test).__module__}.{type(test).__qualname__}"


def shards(n: int, suite: unittest.TestSuite | None = None) -> list[list[unittest.TestCase]]:
    """The suite's tests in n shards, a whole class to one shard, classes dealt in name order."""
    if n < 1:
        raise ValueError(f"shard count {n}: it must be at least 1")
    suite = unittest.defaultTestLoader.discover(str(BOOT / "tests"), top_level_dir=str(BOOT / "tests")) \
        if suite is None else suite
    by_class: dict[str, list[unittest.TestCase]] = {}
    for test in flatten(suite):
        by_class.setdefault(class_of(test), []).append(test)
    out: list[list[unittest.TestCase]] = [[] for _ in range(n)]
    for i, name in enumerate(sorted(by_class)):
        out[i % n].extend(by_class[name])
    return out


def parse(spec: str) -> tuple[int, int]:
    k, _, n = spec.partition("/")
    if not (k.isdigit() and n.isdigit()) or not 0 <= int(k) < int(n):
        raise SystemExit(f"stop: shard {spec!r} is not K/N with 0 <= K < N")
    return int(k), int(n)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("shard", help="K/N: the K-th of N shards, counted from 0")
    parser.add_argument("--list", action="store_true", help="print the shard's test ids and run nothing")
    args = parser.parse_args(argv)
    k, n = parse(args.shard)
    mine = shards(n)[k]
    if args.list:
        for test in mine:
            print(test.id())
        return 0
    result = unittest.TextTestRunner(verbosity=1).run(unittest.TestSuite(mine))
    return 0 if result.wasSuccessful() and result.testsRun else 1


if __name__ == "__main__":
    sys.exit(main())
