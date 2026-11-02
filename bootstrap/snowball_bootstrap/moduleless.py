"""Module-less red (`asama-0/14`; `tohum/04` 1, "Kasıtlı bozma"): a micro-feature's tests fail without it.

When a push adds micro-feature k to `done_mf` (at the exit: every micro-feature, `asama-0/10` #modulsuz), each
of k's tests runs again in the same sandbox on the pushed tree with k's module path (the stage table's `module`,
under `referee/`) deleted. A test that stays green there does not test that module ("geri alındığında yeşil
kalan test, test değildir"): `decide` rejects the push with `module_less_green:MFk`.

Deleting the module fails every test that imports it, so a red run shows that the tests import their module, not
that they test its behaviour. Each record keeps what the run printed, as a hash and a secret-scanned tail, so how
it went red (an import error or a failed assertion) can be read afterwards (E386).
"""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Iterable

from . import secretscan
from .container import Runner, RunResult
from .stages import StageTable
from .treehash import extract

DOCKER_ERROR = 125  # `docker run` failed itself; the command's own 125 is 1 since E01
TAIL_CHARS = 500
WITHHELD = "(withheld: the output matches a secret pattern)"


def output_record(res: RunResult) -> dict[str, str]:
    """The run's output (stdout, a newline, stderr) as a sha256 and its last 500 characters, withheld whole when the
    tail matches a secret pattern: the record is signed into the public result."""
    data = res.stdout + b"\n" + res.stderr
    tail = data.decode("utf-8", "replace")[-TAIL_CHARS:]
    return {"output_sha256": hashlib.sha256(data).hexdigest(),
            "output_tail": WITHHELD if secretscan.scan(tail) else tail}


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


def units(table: StageTable, mfs: Iterable[int], tests: list[dict[str, Any]]) -> list[tuple[int, dict[str, Any]]]:
    """Every module-less run of a push, in order: (micro-feature, test) for each declared test of each micro-feature in
    ``mfs``. A part of `kos` runs those whose place here is its own (E440)."""
    by_id = {t["id"]: t for t in tests if t["stage"] == table.stage}  # the table's own stage (`stage: 1` in Stage 1)
    found = []
    for k in mfs:
        for number in table.feature(k).tests:
            test = by_id.get(f"T{number}")
            if test is not None:  # `pull` refuses a manifest without it (`missing_test`): there is nothing to run
                found.append((k, test))
    return found


def run_module_less(make_runner: Callable[[Path], Runner], tar_bytes: bytes, work: Path, table: StageTable,
                    mfs: Iterable[int], tests: list[dict[str, Any]], timeout_s: int, max_bytes: int, *,
                    mine: Callable[[int], bool] = lambda place: True) -> list[dict[str, Any]]:
    """One result per test of each micro-feature in ``mfs``, run on its own module-less tree; with ``mine``, only the
    runs whose place in `units` it names (a part's share, E440)."""
    results: list[dict[str, Any]] = []
    todo = [(k, test) for place, (k, test) in enumerate(units(table, mfs, tests)) if mine(place)]
    for k in dict.fromkeys(k for k, _test in todo):
        feature = table.feature(k)
        tree = work / f"MF{k}"
        present = module_less_tree(tar_bytes, tree, feature.module_path, max_bytes)
        runner = make_runner(tree)
        for test in (test for mf, test in todo if mf == k):
            res = runner.run(test["cmd"], timeout_s=timeout_s)
            results.append({"mf": k, "test_id": test["id"], "module": feature.module_path,
                            "module_present": present, "exit": res.exit_code, "timed_out": res.timed_out,
                            "stayed_green": res.ok, "runner_fault": res.exit_code == DOCKER_ERROR,
                            **output_record(res)})
    return results
