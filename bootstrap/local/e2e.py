"""Local end-to-end run of the bootstrap referee against a real container runtime.

It builds a throwaway brain repository whose ``referee/`` answers the seed-vector interface with
reference implementations, writes operator files for a throwaway referee, and runs the same steps
the workflow runs: pull -> fetch-deps (real PyPI download) -> run-tests (real docker, no network)
-> decide. Sigstore signing is not run (it needs a workflow's OIDC identity).

    cd seed/bootstrap && python3 local/e2e.py [--keep DIR] [--rival]

Without ``--rival`` the rival's verdict is stubbed. With it the real rival judges the code push (the spec
push stays stubbed) through the
``claude`` CLI on PATH, signed in as whoever runs this (no API key; one call is capped at the
``per_run_cap_usd_micros`` below, a list-price estimate) and its reproducers run in the container.

Exit 0 means: the red controls behaved, the founder-style tests ran offline in the pinned image,
every seed vector passed (including the drill group), the licence gate passed and the push was
accepted. Exit 3 means the rival could not run (an outage of the CLI or its login, not a verdict).
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
BOOT = HERE.parent
SEED = BOOT.parent
sys.path.insert(0, str(BOOT))

from snowball_bootstrap import cli, gitio  # noqa: E402
from snowball_bootstrap.decide import decide  # noqa: E402
from snowball_bootstrap.manifest import STAGE0_MF_TESTS  # noqa: E402
from snowball_bootstrap.rival import RivalOutcome  # noqa: E402
from snowball_bootstrap.treehash import tree_hash  # noqa: E402

IMAGE = "docker.io/library/python:3.12-slim@sha256:aa943ce411423c7582288f18707ff66eddcbaeb510502d747a72aeb34f30d159"
DONE = list(range(1, 19))  # micro-features 1-18: chain, statistics and match, and the drill judge

CANON = '''
import hashlib, json, sys
def canonical(v):
    return json.dumps(v, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
def row_hash(row):
    body = {k: v for k, v in row.items() if k != "row_hash"}
    return hashlib.sha256(canonical(body) + row["prev_hash"].encode()).hexdigest()
'''

CHAIN = CANON + '''
def main(argv):
    if argv[0] == "hash":
        print(json.dumps({"row_hash": row_hash(json.loads(sys.stdin.read()))}))
        return
    prev = "0" * 64
    for line in open(argv[1]).read().splitlines():
        row = json.loads(line)
        if row["prev_hash"] != prev or row_hash(row) != row["row_hash"]:
            print(json.dumps({"valid": False, "broken_row": row["row_id"]}))
            return
        prev = row["row_hash"]
    print(json.dumps({"valid": True}))
if __name__ == "__main__":
    main(sys.argv[1:])
'''

STATS = '''
import json, math, sys
def beta_cdf(a, b, x, steps=4000):
    if x <= 0: return 0.0
    if x >= 1: return 1.0
    lb = math.lgamma(a) + math.lgamma(b) - math.lgamma(a + b)
    f = lambda t: 0.0 if t <= 0 or t >= 1 else math.exp((a - 1) * math.log(t) + (b - 1) * math.log(1 - t) - lb)
    h = x / steps
    s = f(0) + f(x) + sum((4 if i % 2 else 2) * f(i * h) for i in range(1, steps))
    return s * h / 3
def cp_lower(x, n, alpha):
    if x <= 0: return 0.0
    if x >= n: return alpha ** (1 / n)
    lo, hi = 0.0, 1.0
    for _ in range(60):
        mid = (lo + hi) / 2
        if beta_cdf(x, n - x + 1, mid) > alpha: hi = mid
        else: lo = mid
    return lo
def mcnemar(b, c):
    m = b + c
    return sum(math.comb(m, k) for k in range(c, m + 1)) / 2 ** m
if __name__ == "__main__":
    a = sys.argv[1:]
    if a[0] == "cp_lower":
        print(json.dumps({"lb": f"{cp_lower(float(a[1]), int(a[2]), float(a[3])):.6f}"}))
    else:
        print(json.dumps({"p": f"{mcnemar(int(a[1]), int(a[2])):.6f}"}))
'''

SCORE = '''
import json, sys
def score(findings, cases):
    hits, used = 0, set()
    for case in cases:
        for i, f in enumerate(findings):
            if i in used: continue
            if (f.get("tool") == case.get("tool") and f.get("rule_id") == case.get("rule_id")
                    and any(ref["path"] == tp["path"] and any(h["start"] <= ref["line_start"] <= h["end"]
                            for h in tp["hunks"]) for ref in f["evidence_refs"] for tp in case["touched_paths"])):
                hits += 1; used.add(i); break
    return hits
if __name__ == "__main__":
    print(json.dumps({"hits": score(json.load(open(sys.argv[1])), json.load(open(sys.argv[2])))}))
'''

DRILL = '''
import json, sys
from harness import drill_judge
if __name__ == "__main__" and sys.argv[1] == "judge":
    out = drill_judge.judge(json.load(open(sys.argv[2])))
    print(json.dumps({"drill": out["drill"], "verdicts": out["verdicts"]}))
'''


def sh(cwd: Path, *argv: str) -> str:
    return subprocess.run(argv, cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def commit(repo: Path, files: dict[str, str], message: str) -> str:
    for rel, content in files.items():
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text(content)
    sh(repo, "git", "add", "-A")
    sh(repo, "git", "-c", "user.email=e2e@example.invalid", "-c", "user.name=e2e", "commit", "-q", "-m", message)
    return sh(repo, "git", "rev-parse", "HEAD")


def manifest() -> str:
    # Test commands run from the repository root (`tohum/26b`); vectors run from referee/.
    cmd = "cd referee && python -c 'import annotated_types, ledger.chain, harness.stats'"
    tests = [{"id": f"T{n}", "cmd": cmd, "stage": 0}
             for mf in DONE for n in STAGE0_MF_TESTS[mf]]
    return json.dumps({"tests": tests, "done_mf": DONE, "lockfiles": ["requirements.lock"]})


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--keep", help="work directory (default: a new temporary one; either way it is left "
                                       "in place for inspection and its path is printed at the end)")
    parser.add_argument("--rival", action="store_true", help="run the real rival through your claude CLI login")
    parser.add_argument("--model", default="claude-sonnet-5-5", help="rival model when --rival is set")
    args = parser.parse_args()
    work = Path(args.keep) if args.keep else Path(tempfile.mkdtemp(prefix="snowball-e2e-"))
    work.mkdir(parents=True, exist_ok=True)
    brain, referee = work / "brain", work / "referee"

    # Brain repository: seed, then a spec push, then the referee code.
    brain.mkdir()
    sh(brain, "git", "init", "-q", "-b", "main")
    seed_sha = commit(brain, {"spec/tohum/00-cekirdek.md": "# core\n", "spec/asama-0/00-ozet.md": "# stage 0\n"},
                      "seed")
    seed_tree = tree_hash(gitio.archive(brain, seed_sha), "spec/tohum", forbid_operator_names=False)

    # Throwaway referee: operator files and vectors.
    (referee / "setup").mkdir(parents=True)
    shutil.copytree(BOOT / "vectors", referee / "vectors")
    (referee / "seats").mkdir()
    shutil.copy(SEED.parent / "spec" / "tohum" / "29-tohum-koltuklari.md", referee / "seats")
    (referee / "setup" / "summary.json").write_text(json.dumps({"seed_commit": seed_sha,
                                                                 "seed_tree_sha256": seed_tree}))
    (referee / "control.json").write_text(json.dumps({"kill_switch": False, "budget_state": "ok"}))
    (referee / "bootstrap.json").write_text(json.dumps({
        "brain_repo": "local/brain", "brain_branch": "main", "image": IMAGE,
        "rival": {"model": args.model, "effort": "medium", "max_turns": 30, "per_run_cap_usd_micros": 3_000_000},
        "limits": {"test_timeout_s": 600, "reproducer_timeout_s": 120, "max_prompt_chars": 600_000,
                   "max_tree_bytes": 50_000_000}}))
    allow = ["MIT", "MIT-0", "BSD-2-Clause", "BSD-3-Clause", "0BSD", "Apache-2.0", "ISC", "PSF-2.0",
             "Python-2.0", "Unlicense", "CC0-1.0", "Zlib", "MPL-2.0"]
    (referee / "policy.json").write_text(json.dumps({"constitutional": {
        "monthly_cap_usd": 300, "stage_params": {"rival_min_attempts": 5, "repeat_reject_limit": 3},
        "stage_budgets": {"asama_0": {"rival_usd": 30}}, "license_allowlist": allow, "license_exceptions": {}}}))

    state = json.loads(json.dumps({"schema": "snowball-bootstrap-state/1", "origin": "initial",
                                   "last_accepted_sha": seed_sha, "last_evaluated_sha": None, "frozen_specs": {},
                                   "rival_artifacts": [], "month": cli.month_now(), "month_spend_usd_micros": 0,
                                   "stage_spend_usd_micros": 0, "runs": 0, "reject_streaks": {},
                                   "repeat_events": 0, "outage_sha": None, "outage_count": 0}))

    def pull(n: int) -> tuple[dict, Path]:
        (work / f"state{n}.json").write_text(json.dumps(state))
        out = work / f"pulled{n}"
        rc = cli.main(["pull", "--root", str(referee), "--state", str(work / f"state{n}.json"),
                       "--work", str(work / "git"), "--out", str(out), "--remote", str(brain)])
        assert rc == 0, "pull failed"
        return json.loads((out / "meta.json").read_text()), out

    commit(brain, {"spec/asama-0/00-ozet.md": "# stage 0, frozen by the e2e run\n"}, "spec")
    meta, _ = pull(1)
    assert meta["kind"] == "spec" and not meta["pre_reasons"], meta
    rival_ok = RivalOutcome(verdict="not_refuted", model_requested=args.model).as_dict()
    state = decide(meta, None, rival_ok, None, {"cagir": "success"}, 5, 3)["state"]
    print("1/4 spec push frozen (rival result stubbed; --rival runs the real one through your claude CLI)")

    pins = (BOOT / "requirements" / "sign.txt").read_text(encoding="utf-8").splitlines()
    first = next(n for n, line in enumerate(pins) if line.startswith("annotated-types=="))
    lock = "\n".join(pins[first:first + 2])  # the pin and its --hash line
    judge_src = (SEED / "drill" / "snowball_drill" / "judge.py").read_text()
    commit(brain, {
        "referee/ledger/__init__.py": "", "referee/ledger/chain.py": CHAIN,
        "referee/harness/__init__.py": "", "referee/harness/stats.py": STATS, "referee/harness/score.py": SCORE,
        "referee/harness/drill.py": DRILL, "referee/harness/drill_judge.py": judge_src,
        "requirements.lock": lock + "\n", "snowball-tests.json": manifest()}, "stage 0 through MF18")
    meta, pulled = pull(2)
    assert meta["kind"] == "code" and meta["run_tests"], meta
    print("2/4 code push classified; manifest and lock file accepted")

    deps = work / "deps"
    rc = cli.main(["fetch-deps", "--pulled", str(pulled), "--work", str(work / "dl"), "--out", str(deps)])
    assert rc == 0 and list(deps.glob("*.whl")), "fetch-deps downloaded nothing"
    print("3/4 wheels downloaded:", ", ".join(p.name for p in deps.glob("*.whl")))

    run_dir = work / "run"
    started = time.monotonic()
    cli.main(["run-tests", "--root", str(referee), "--pulled", str(pulled), "--deps", str(deps),
                   "--work", str(work / "src"), "--out", str(run_dir)])
    run = json.loads((run_dir / "run.json").read_text())
    bad = ([c for c in run["controls"] if not c["ok"]] + [t for t in run["tests"] if not t["ok"]]
           + [v for v in run["vectors"] if not v["ok"]] + [x for x in run["licenses"] if not x["allowed"]])
    print(f"4/4 run-tests in docker ({time.monotonic() - started:.0f} s): controls {len(run['controls'])}, "
          f"tests {len(run['tests'])}, vectors {len(run['vectors'])}, wheels {len(run['licenses'])}, "
          f"green={run['green']}")
    for item in bad:
        print("   NOT OK:", json.dumps(item)[:300])
    rival, repro, jobs = rival_ok, [], {"getir": "success", "kos": "success", "cagir": "success",
                                        "yeniden": "skipped"}
    if args.rival and run["green"]:
        cli.main(["rival", "--root", str(referee), "--pulled", str(pulled), "--work", str(work / "rv"),
                  "--out", str(work / "rival")])
        rival = json.loads((work / "rival" / "rival.json").read_text())
        print("rival:", rival["verdict"], "served", rival.get("model_served"), "cost (list-price estimate, micros)",
              rival.get("cost_usd_micros"), "reasons", rival.get("reasons"))
        outage = [r for r in rival.get("reasons", []) if str(r).startswith("api_error")]
        if outage:  # the referee would retry this commit later: that is not a verdict on the push
            print("the rival could not run (an outage, not a rejection):", ", ".join(outage))
            print("work directory:", work)
            return 3
        if rival["verdict"] in ("refuted", "not_refuted") and rival.get("reproducer_count"):
            cli.main(["reproduce", "--root", str(referee), "--pulled", str(pulled), "--deps", str(deps),
                      "--rival", str(work / "rival"), "--work", str(work / "rp"), "--out", str(work / "repro")])
            repro = json.loads((work / "repro" / "repro.json").read_text())["results"]
            jobs["yeniden"] = "success"
            print("reproducers:", repro)
    result = decide(meta, run, rival, repro, jobs, 5, 3)
    print("decide:", result["verdict"], [r["kind"] for r in result["reasons"]])
    print("work directory:", work)
    return 0 if run["green"] and result["verdict"] == "accepted" else 1


if __name__ == "__main__":
    sys.exit(main())
