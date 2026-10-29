"""Local end-to-end run of the bootstrap referee against a real container runtime.

It builds a throwaway brain repository from the reference brain in ``reference_brain/`` (a real,
tested implementation of micro-feature 1, the hash-chained ledger, and nothing it does not have), writes
operator files for a throwaway referee, and runs the same steps the workflow runs: pull -> fetch-deps
-> run-tests (real docker, no network) -> decide. Sigstore signing is not run (it needs a workflow's
OIDC identity). The reference brain uses the standard library only, so fetch-deps has nothing to fetch;
the real hash-pinned download and the licence gate run in the workflow's own Sigstore step.

    cd seed/bootstrap && python3 local/e2e.py [--keep DIR] [--rival]

Without ``--rival`` the rival's verdict is stubbed. With it the real rival judges the code push (the spec
push stays stubbed) through the
``claude`` CLI on PATH, signed in as whoever runs this (no API key; one call is capped at the
``per_run_cap_usd_micros`` below, a list-price estimate) and its reproducers run in the container.

Exit 0 means: the red controls behaved, the brain's tests ran offline in the pinned image, every
seed vector of the micro-features it declares done passed, its tests failed on the tree without
micro-feature 1's module (module-less red, `asama-0/14`) and the push was accepted. Exit 3 means the rival could not run (an outage of the CLI or its login, not a verdict).
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

from snowball_bootstrap import cli, gitio, state as st  # noqa: E402
from snowball_bootstrap.config import Summary  # noqa: E402
from snowball_bootstrap.decide import decide  # noqa: E402
from snowball_bootstrap.rival import RivalOutcome  # noqa: E402
from snowball_bootstrap.treehash import tree_hash  # noqa: E402

IMAGE = "docker.io/library/python:3.12-slim@sha256:aa943ce411423c7582288f18707ff66eddcbaeb510502d747a72aeb34f30d159"
BRAIN = HERE / "reference_brain"


def sh(cwd: Path, *argv: str) -> str:
    return subprocess.run(argv, cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def commit(repo: Path, files: dict[str, str], message: str) -> str:
    for rel, content in files.items():
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text(content, encoding="utf-8", newline="\n")
    sh(repo, "git", "add", "-A")
    sh(repo, "git", "-c", "user.email=e2e@example.invalid", "-c", "user.name=e2e", "commit", "-q", "-m", message)
    return sh(repo, "git", "rev-parse", "HEAD")


def brain_files() -> dict[str, str]:
    """The reference brain's files, keyed by their path in the brain repository."""
    return {p.relative_to(BRAIN).as_posix(): p.read_text(encoding="utf-8") for p in sorted(BRAIN.rglob("*"))
            if p.is_file() and "__pycache__" not in p.parts}


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

    state = st.initial(Summary(seed_sha, "0" * 64), cli.month_now())

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

    commit(brain, brain_files(), "stage 0: micro-feature 1, the hash-chained ledger")
    meta, pulled = pull(2)
    assert meta["kind"] == "code" and meta["run_tests"], meta
    print("2/4 code push classified; manifest accepted (done_mf", meta["manifest"]["done_mf"], ", module-less red for",
          meta["module_less"], ")")

    deps = work / "deps"
    rc = cli.main(["fetch-deps", "--pulled", str(pulled), "--work", str(work / "dl"), "--out", str(deps)])
    assert rc == 0, "fetch-deps failed"
    print("3/4 wheels downloaded:", ", ".join(p.name for p in deps.glob("*.whl")) or "none (no lock files)")

    run_dir = work / "run"
    started = time.monotonic()
    cli.main(["run-tests", "--root", str(referee), "--pulled", str(pulled), "--deps", str(deps),
                   "--work", str(work / "src"), "--out", str(run_dir)])
    run = json.loads((run_dir / "run.json").read_text())
    bad = ([c for c in run["controls"] if not c["ok"]] + [t for t in run["tests"] if not t["ok"]]
           + [v for v in run["vectors"] if not v["ok"]] + [x for x in run["licenses"] if not x["allowed"]]
           + [m for m in run["module_less"] if m["stayed_green"] or m["runner_fault"]])
    print(f"4/4 run-tests in docker ({time.monotonic() - started:.0f} s): controls {len(run['controls'])}, "
          f"tests {len(run['tests'])}, vectors {len(run['vectors'])}, wheels {len(run['licenses'])}, "
          f"module-less red {[(m['test_id'], m['exit']) for m in run['module_less']]}, green={run['green']}")
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
