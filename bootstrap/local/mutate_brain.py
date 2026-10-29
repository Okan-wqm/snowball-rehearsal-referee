"""Mutation check of the reference brain's own tests: break its code on purpose, expect its tests to notice.

The reference brain (``local/reference_brain/``) is the small, real brain the end-to-end run and the GitHub
rehearsal push to the referee. A test that stays green when the code under it is wrong is what the rival
refutes a push for ("the tests do not exercise the mechanism"), so every mutant here is one change a careless
edit of ``ledger/chain.py`` could plausibly make, and the brain's tests must fail on it. An anchor that no
longer matches fails loudly, so the list cannot rot while the code moves on.

    cd seed/bootstrap && python3 local/mutate_brain.py [--only NAME] [--list]

Exit 0 means every mutant was killed.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REFEREE = Path(__file__).resolve().parent / "reference_brain" / "referee"
TARGET = "ledger/chain.py"
BS = chr(92)

# (name, text found exactly once in chain.py, replacement, what the mutant stands for)
MUTANTS = [
    ("keys_sorted_by_code_point", "sorted(value, key=_utf16)", "sorted(value)",
     "json.dumps(sort_keys=True) order: an emoji key sorts after a Hebrew one"),
    ("small_numbers_in_decimals_too_long", "elif -6 < n <= 0:", "elif -7 < n <= 0:",
     "1e-7 printed as 0.0000001"),
    ("big_numbers_in_decimals_too_long", "if k <= n <= 21:", "if k <= n <= 22:", "1e21 printed as 1000000000000000000000"),
    ("control_character_left_raw", "elif code < 0x20:", "elif code < 0x1f:", "U+001F reaches the output unescaped"),
    ("short_escape_dropped", '0x0C: "' + BS + BS + 'f", ', "", "a form feed is written as \\u000c"),
    ("true_is_one", "elif value is True:", "elif False:", "a boolean is hashed as a number"),
    ("nan_allowed", "if not math.isfinite(number):", "if False:", "NaN reaches the hash"),
    ("inexact_integer_allowed", "if int(number) != value:", "if False:", "2**53 + 1 is silently rounded"),
    ("lone_surrogate_not_refused", "except UnicodeEncodeError as exc:", "except ZeroDivisionError as exc:",
     "a string no UTF-8 encoder accepts crashes instead of being refused"),
    ("prev_hash_suffix_missing", 'hashlib.sha256(canonical(body) + prev.encode("ascii")).hexdigest()',
     "hashlib.sha256(canonical(body)).hexdigest()", "the hash does not end with the previous hash"),
    ("stored_hash_inside_the_hash", 'body = {key: value for key, value in row.items() if key != "row_hash"}',
     "body = dict(row)", "the row hash covers itself"),
    ("genesis_one_zero_short", 'ZERO_HASH = "0" * 64', 'ZERO_HASH = "0" * 63', "the first previous hash is not 64 zeros"),
    ("previous_link_unchecked", 'if row.get("prev_hash") != expected_prev:', "if False:",
     "a deleted or swapped row goes unnoticed because each row still hashes to itself"),
    ("row_hash_unchecked", 'if row.get("row_hash") != computed:', "if False:", "an edited row goes unnoticed"),
    ("repeated_id_allowed", "if row_id in seen:", "if False:", "two rows with one id, hashes forged to agree"),
    ("missing_id_allowed", "if not isinstance(row_id, str) or not row_id:", "if False:",
     "a row without a usable id cannot be named and is let through"),
    ("duplicate_keys_allowed", "if len(keys) != len(set(keys)):", "if False:",
     "an object that says one thing twice shows the last value and hashes the first"),
    ("nan_literal_allowed", 'raise ValueError(f"{name} is not JSON")', "return 0", "NaN is read as a number"),
    ("earlier_file_ignored", "problem = _not_append_only(rows, earlier)", "problem = None",
     "the finding of the first rehearsal: verify ignores --previous"),
    ("append_only_by_id_only", "if canonical(rows[index]) != canonical(before):",
     'if rows[index].get("row_id") != before["row_id"]:', "a rewrite that keeps the ids passes"),
    ("lost_rows_allowed", 'return before["row_id"], "the file lost this row"', "break",
     "a file that lost its tail passes the append-only check"),
    ("broken_earlier_file_compared_anyway", "if before is not None:", "if False:",
     "a broken earlier file is trusted as the reference"),
    ("unreadable_line_hides_an_earlier_break",
     "problem = _chain_break(rows) or unreadable" + chr(10) + "    if problem is None and previous",
     "problem = unreadable or _chain_break(rows)" + chr(10) + "    if problem is None and previous",
     "the first problem in the file is not the one reported"),
    ("broken_chain_extended", 'raise ChainError(f"refusing to extend a broken chain: {problem[0]}: {problem[1]}")',
     "pass", "the writer adds a row to a chain that no longer verifies"),
    ("writer_accepts_its_own_fields", 'if "prev_hash" in row or "row_hash" in row:', "if False:",
     "a caller chooses the hashes the writer is there to set"),
    ("cut_line_extended", 'if content and not content.endswith(b"' + BS + 'n"):', "if False:",
     "the writer glues a row onto a half-written line"),
    ("verify_always_exits_zero", 'code = 0 if result["valid"] else 1', "code = 0",
     "a broken chain looks fine to a shell script"),
]


def run_tests(workdir: Path) -> tuple[int, str]:
    proc = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-f"], cwd=workdir,
                          env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"), capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=600)
    killers = [line.split(" ")[1] for line in (proc.stdout + proc.stderr).splitlines()
               if line.startswith(("FAIL: ", "ERROR: "))]
    return proc.returncode, (killers[0] if killers else "(no test named)")


def run_mutant(mutant: tuple[str, str, str, str] | None) -> tuple[bool, str, float]:
    """Apply one mutant (or none: the baseline) to a fresh copy of the brain and run its tests there."""
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="brain-mutant-") as tmp:
        work = Path(tmp) / "referee"
        shutil.copytree(REFEREE, work, ignore=shutil.ignore_patterns("__pycache__"))
        if mutant is not None:
            _name, old, new, _why = mutant
            target = work / TARGET
            text = target.read_text(encoding="utf-8")
            if text.count(old) != 1:
                return False, f"ANCHOR MISSING in {TARGET} (found {text.count(old)}x): update the mutant", 0.0
            target.write_bytes(text.replace(old, new).encode("utf-8"))
        code, killer = run_tests(work)
    return code != 0, killer, time.monotonic() - started


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", help="run only the mutant with this name")
    parser.add_argument("--list", action="store_true", help="list the mutants and what each stands for")
    args = parser.parse_args()
    chosen = [m for m in MUTANTS if not args.only or m[0] == args.only]
    if not chosen:
        print("no such mutant", file=sys.stderr)
        return 2
    if args.list:
        for name, _old, _new, why in chosen:
            print(f"{name:40} {why}")
        return 0
    failed, detail, _ = run_mutant(None)  # without this a failing environment makes every mutant "killed"
    if failed:
        print(f"the unmutated brain already fails its tests ({detail}); fix that first", file=sys.stderr)
        return 2
    survivors = []
    for mutant in chosen:
        killed, detail, seconds = run_mutant(mutant)
        print(f"{'killed  ' if killed else 'SURVIVED'} {mutant[0]:40} {seconds:5.1f}s  {detail}", flush=True)
        if not killed:
            survivors.append(mutant[0])
    print(f"\n{len(chosen) - len(survivors)}/{len(chosen)} mutants killed")
    if survivors:
        print("not measured by any test:", ", ".join(survivors))
    return 1 if survivors else 0


if __name__ == "__main__":
    sys.exit(main())
