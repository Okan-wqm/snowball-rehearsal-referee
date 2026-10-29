"""Module-less red (`asama-0/14`; `tohum/04` 1, "Kasıtlı bozma"): a micro-feature's tests fail without it.

When a push adds micro-feature k to `done_mf` (at the exit: every micro-feature, `asama-0/10` #modulsuz), each
of k's tests runs again in the same sandbox on the pushed tree with k's module path (the stage table's `module`,
under `referee/`) deleted. A test that stays green there does not test that module ("geri alındığında yeşil
kalan test, test değildir"): `decide` rejects the push with `module_less_green:MFk`.
"""

from __future__ import annotations

import shutil
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Iterable

from .container import Runner
from .stages import StageTable
from .treehash import extract

DOCKER_ERROR = 125  # `docker run` failed itself; the command's own 125 is 1 since E01


def module_less_tree(tar_bytes: bytes, dest: Path, module_path: str, max_bytes: int) -> bool:
    """Extract the pushed tree into ``dest`` without ``module_path``; True when there was something to delete."""
    extract(tar_bytes, dest, max_bytes)
    target = dest.joinpath(*PurePosixPath(module_path).parts)
    if target.is_dir():
        shutil.rmtree(target)
        return True
    if target.exists():
        target.unlink()
        return True
    return False


def run_module_less(make_runner: Callable[[Path], Runner], tar_bytes: bytes, work: Path, table: StageTable,
                    mfs: Iterable[int], tests: list[dict[str, Any]], timeout_s: int,
                    max_bytes: int) -> list[dict[str, Any]]:
    """One result per test of each micro-feature in ``mfs``, run on its own module-less tree."""
    by_id = {t["id"]: t for t in tests if t["stage"] == 0}
    results: list[dict[str, Any]] = []
    for k in mfs:
        feature = table.feature(k)
        tree = work / f"MF{k}"
        present = module_less_tree(tar_bytes, tree, feature.module_path, max_bytes)
        runner = make_runner(tree)
        for number in feature.tests:
            test = by_id.get(f"T{number}")
            if test is None:  # `pull` refuses such a manifest (`missing_test`): there is nothing to run
                continue
            res = runner.run(test["cmd"], timeout_s=timeout_s)
            results.append({"mf": k, "test_id": test["id"], "module": feature.module_path,
                            "module_present": present, "exit": res.exit_code, "timed_out": res.timed_out,
                            "stayed_green": res.ok, "runner_fault": res.exit_code == DOCKER_ERROR})
    return results
