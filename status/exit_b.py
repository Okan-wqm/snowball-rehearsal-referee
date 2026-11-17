"""``status.exit_b``: the exit audit of (B), asama-0/10a's conditions against the code that judges them, and the
generated document ``docs/exit-b.md`` that states, for each, where it is judged and where (B)'s rehearsal stops.

**The page's conditions** (``page_rows``): each row of 10a's condition table (a line ``| <cell> | ... |`` whose
first cell is one or more ``#tag`` words and nothing else), in page order; a page with no such row, or a first cell
that holds anything but tags, is ``Unusable``: nothing is guessed.

**The places** (``places``): a tag is judged when it is a word of a key of ``harness.pass_row.CONDITIONS`` (machine
judged on the targets' ``brain/state``), not checked when it is a word of a key of ``harness.pass_row.NOT_CHECKED``
(with the place that holds its evidence, as that module states it), written when it is a key of ``WRITTEN`` (the
PASS row itself). One 10a row may be split across places (``#model #belirtec #prompt``: two judged, one not).

**The audit** (``problems``, sorted, unique; empty is the audit holding): ``unplaced:<tag>``, a 10a tag in no place;
``placed_twice:<tag>``, a tag in more than one key; ``not_on_page:<key>``, a key whose words are not all 10a tags (a
renamed or removed condition). So a 10a condition that nothing judges and no stated reason excuses cannot reach an
exit request unseen (f581).

**The document** (``render``): the register (``render_register``: each 10a row, each tag and its place) and one
section per rehearsal case (``render_case``: the run (B) stops at in ``tests/test_rehearsal.py``'s in-process world,
why it stops, the toy's gate reasons per judged condition at that run, or the run it ends at, the one whose ``yaz``
judged the toy's PASS row ``PASS``, with that judgement's reasons per condition; whether the copy was served, and the
open reports the stop waits for, with their state read from ``reports/``, or none: an end, a stop that is the case's
own input, an operator's secret not given or a set the seed's producer refuses). ``tests/test_exit_b.py`` checks the register
section current and the audit empty; ``tests/test_rehearsal.py`` checks each case's section against the records it
asserts; ``python tests/test_rehearsal.py --doc`` writes the file. Out of scope, stated: the rehearsal is a fake
world (no real runner, git, GitHub, Rekor or model; see that test's docstring), so "no reason" in a case's table means
the toy's state in that world gave the gate no reason, not that the live loop meets the condition.

Command line, from ``referee/``: ``python -m status.exit_b check`` prints ``{"ok", "problems"}`` (exit 0 when the
audit holds, 1 otherwise); ``python -m status.exit_b register`` prints the register section.
"""

from __future__ import annotations

import json
import os
import re
import sys

from harness import pass_row as PR
from ledger import founder
import cli

BRAIN = founder.BRAIN
PAGE = os.path.join(BRAIN, "spec", "asama-0", "10a-cikis-canli-dongu.md")
DOC = os.path.join(BRAIN, "docs", "exit-b.md")
WRITTEN = {"#pass": "`yaz` on the toy's cycle once the gate's row is held (`loop.job.yaz_pass`, `loop.write_cycle`), "
                     "after `harness.pass_row.judge` gave `PASS` on both states"}
ROW = re.compile(r"^\|\s*(#[^\s#|][^|]*?)\s*\|")  # a lone ``#`` is the header's column name
TAG = re.compile(r"#[^\s#|]+\Z")
CASE_MARK = "<!-- case:%s -->"


class Unusable(ValueError):
    pass


def page_rows(text: str) -> list[tuple[str, ...]]:
    """The tags of each 10a condition row, in page order (see the module docstring)."""
    rows = []
    for line in text.splitlines():
        m = ROW.match(line)
        if not m:
            continue
        tags = tuple(m.group(1).split())
        if not all(TAG.match(t) for t in tags):
            raise Unusable("10a row %r: its first cell is not only #tags" % m.group(1))
        rows.append(tags)
    if not rows:
        raise Unusable("10a holds no condition row")
    return rows


def _keys() -> list[tuple[str, str, str]]:
    """``(key, kind, place)`` for every key of the three places."""
    judged = [(k, "judged", "judged by `harness.pass_row` (`%s`)" % k) for k in PR.CONDITIONS]
    unchecked = [(k, "not_checked", "not checked: %s" % v) for k, v in PR.NOT_CHECKED.items()]
    return judged + unchecked + [(k, "written", "written: %s" % v) for k, v in WRITTEN.items()]


def places() -> dict[str, list[tuple[str, str, str]]]:
    """``{tag: [(key, kind, place), ...]}`` over the three places."""
    out: dict[str, list[tuple[str, str, str]]] = {}
    for key, kind, place in _keys():
        for tag in key.split():
            out.setdefault(tag, []).append((key, kind, place))
    return out


def problems(text: str) -> list[str]:
    """The audit (see the module docstring)."""
    tags = {t for row in page_rows(text) for t in row}
    found = places()
    out = {"unplaced:" + t for t in tags if t not in found}
    out |= {"placed_twice:" + t for t, where in found.items() if len(where) > 1}
    out |= {"not_on_page:" + key for key, _, _ in _keys() if not set(key.split()) <= tags}
    return sorted(out)


def render_register(text: str) -> str:
    found = places()
    lines = ["## The register: each 10a condition and where it is judged", "",
             "From `spec/asama-0/10a-cikis-canli-dongu.md` and `referee/harness/pass_row.py` "
             "(`python -m status.exit_b register`).", "", "| 10a row | tag | where |", "|---|---|---|"]
    for row in page_rows(text):
        for tag in row:
            where = "; ".join(p for _, _, p in found.get(tag, [])) or "**unplaced**"
            lines.append("| %s | `%s` | %s |" % (" ".join("`%s`" % t for t in row), tag, where.replace("|", "\\|")))
    return "\n".join(lines) + "\n"


def _report_state(report_id: str, reports: dict[str, dict]) -> str:
    if report_id not in reports:
        raise Unusable("report %s: not in reports/" % report_id)
    return reports[report_id]["state"]


def render_case(name: str, title: str, records: list[dict], waits: list[str], reports: dict[str, dict],
                toy: str = "t1", copy: str = "c1") -> str:
    """One rehearsal case's section from its records (``tests/test_rehearsal.py``'s ``step`` of each run, the last
    being the stall, or the end: the run whose ``yaz`` judged the toy's PASS row ``PASS``)."""
    last, n = records[-1], len(records)
    stop = last.get("stopped")
    copy_state = "waiting (never served)" if copy in last.get("waiting", []) else "served"
    judged = (last.get(toy) or {}).get("pass")
    ended = not stop and bool(judged) and judged.get("verdict") == "PASS"
    if ended:
        conds = judged["conditions"]
        head = "(B) ends at run %d: `yaz` on `%s` judged its PASS row `PASS`. The copy: %s." % (n, toy, copy_state)
        column = "the PASS judgement's reasons at the end"
    else:
        why = ("`%s` stopped on `%s` (target `%s`)" % (stop["job"], stop["reason"], stop["target"]) if stop
               else "run %d repeats run %d" % (n, n - 1))
        gate = (last.get(toy) or {}).get("gate")
        conds = gate["conditions"] if gate else {}
        head = "(B) stops at run %d: %s. The toy's gate: %s. The copy: %s." % (
            n, why, gate["verdict"] if gate else "not judged in that run", copy_state)
        column = "the toy's gate reasons at the stop"
    lines = [CASE_MARK % name, "### %s" % title, "", head, "", "| judged condition | %s |" % column, "|---|---|"]
    for key in PR.CONDITIONS:
        reasons = conds.get(key, [])
        lines.append("| `%s` | %s |" % (key, ", ".join("`%s`" % r for r in reasons) or "no reason"))
    alone = "nothing (the case ends)" if ended else "no report (the stop is the case's own input)"
    lines += ["", "Waits for: " + (", ".join("`%s` (%s)" % (r, _report_state(r, reports)) for r in waits) or alone), ""]
    return "\n".join(lines) + "\n"


def render(text: str, cases: list[str]) -> str:
    """The whole document: a header, the register, then each case's section (``render_case``'s, in order)."""
    head = ["# (B): the exit audit and the rehearsal's stops", "",
            "Generated, never edited by hand: `python tests/test_rehearsal.py --doc` from `referee/` "
            "(`status.exit_b`). The register is checked current by `tests/test_exit_b.py`, each case by "
            "`tests/test_rehearsal.py`. The rehearsal is an in-process world (fake runner, git, GitHub, Rekor and "
            "model): \"no reason\" is the gate's answer there, not a measurement of the live loop.", ""]
    return "\n".join(head) + "\n" + render_register(text) + "\n## The rehearsal's stops\n\n" + "".join(cases)


def read_page(path: str = PAGE) -> str:
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def reports_by_id(directory: str = founder.REPORTS) -> dict[str, dict]:
    return {r["id"]: r for r in founder.read_reports(directory)}


USAGE = "usage: python -m status.exit_b check|register"


def main(argv: list[str]) -> int:
    try:
        return _main(argv)
    except (OSError, Unusable, founder.Unusable) as exc:
        print("unusable: %s" % cli.cause(exc), file=sys.stderr)
        return 2


def _main(argv: list[str]) -> int:
    if argv == ["check"]:
        found = problems(read_page())
        print(json.dumps({"ok": not found, "problems": found}, sort_keys=True))
        return 1 if found else 0
    if argv == ["register"]:
        sys.stdout.write(render_register(read_page()))
        return 0
    print(USAGE, file=sys.stderr)
    return 2


FAULT_LINE = cli.GENERIC_LINE


if __name__ == "__main__":
    sys.exit(cli.run(main, sys.argv[1:], FAULT_LINE))
