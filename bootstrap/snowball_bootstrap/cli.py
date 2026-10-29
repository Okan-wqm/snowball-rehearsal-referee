"""Command-line entry points: one subcommand per workflow step (`workflow/bootstrap.yml`)."""

from __future__ import annotations

import argparse
import datetime
import hashlib
import io
import json
import os
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path
from typing import Any

from . import canon, config, ghapi, gitio, licenses, stages, state as st
from .classify import SEED_DIRS, classify, is_founder_record, is_seed_path, spec_stage_dirs
from .container import DockerRunner
from .controls import run_controls
from .decide import OUTAGE_GIVE_UP_DAYS, OUTAGE_RETRY_LIMIT, decide, utc_now
from .importer import ImportErrorStop, run_import, verify_signature
from .manifest import ManifestError, check_stage0, parse_lockfile, parse_manifest
from .moduleless import run_module_less
from .reproduce import run_reproducers, run_state_reproducers
from .rival import (HIDDEN_DIRS, HIDDEN_NAMES, RivalOutcome, build_context, extract_seat_prompt, hidden, resolve_claude,
                    run_rival)
from .treehash import path_problem, TreeError, extract, is_utf8_name, iter_files, shown, tree_hash
from .vectors import fixtures, missing_groups, run_vectors

EXIT_FILE = "exit-request.json"
MANIFEST_FILE = "snowball-tests.json"
STATE_ARTIFACT = "bootstrap-state"
SEATS_FILE = "29-tohum-koltuklari.md"
PIP_PLATFORMS = ("manylinux_2_39_x86_64", "manylinux_2_34_x86_64", "manylinux_2_28_x86_64",
                 "manylinux_2_17_x86_64", "manylinux2014_x86_64", "any")
SPEC_PAGES = ("00-", "00a-", "02-", "03-")
CODE_PAGES = ("00-", "00a-", "04-", "04a-", "08-", "29a-", "29b-", "29c-")
CODE_STAGE_PAGES = ("asama-0/09-", "asama-0/14-")


# ---------------------------------------------------------------- helpers

def output(**values: Any) -> None:
    """Write step outputs for GitHub Actions and echo them."""
    path = os.environ.get("GITHUB_OUTPUT")
    lines = [f"{k}={str(v).lower() if isinstance(v, bool) else v}" for k, v in values.items()]
    if path:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")
    print("\n".join(lines))


def summary(markdown: str) -> None:
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(markdown + "\n")


def month_now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(canon.dump(value), encoding="utf-8")


def pack_dir(src: Path, out: Path) -> str:
    """Deterministic tar of a directory; returns its sha256."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:", format=tarfile.PAX_FORMAT) as tar:
        for path in sorted(p for p in src.rglob("*") if p.is_file() and not p.is_symlink()):
            data = path.read_bytes()
            info = tarfile.TarInfo(path.relative_to(src).as_posix())
            info.size, info.mtime, info.mode = len(data), 0, 0o644
            tar.addfile(info, io.BytesIO(data))
    out.write_bytes(buf.getvalue())
    return hashlib.sha256(buf.getvalue()).hexdigest()


def unpack(tar_path: Path, expected_sha: str, dest: Path) -> None:
    data = tar_path.read_bytes()
    actual = hashlib.sha256(data).hexdigest()
    if actual != expected_sha:
        raise SystemExit(f"artifact hash mismatch: {actual} != {expected_sha}")
    extract(data, dest, max_bytes=2_000_000_000)


def tar_file(tar_bytes: bytes, wanted: str) -> bytes | None:
    for path, content, _exec in iter_files(tar_bytes):
        if path.as_posix() == wanted:
            return content
    return None


def tar_page(tar_bytes: bytes, prefix: str) -> tuple[str, str] | None:
    for path, content, _exec in iter_files(tar_bytes):
        name = path.as_posix()
        if name.startswith(prefix) and name.endswith(".md"):
            return name, content.decode("utf-8", "replace")
    return None


def is_green(controls: list[dict], tests: list[dict], vectors: list[dict], lic: list[dict],
             module_less: list[dict] | None = None) -> bool:
    """Green means: controls behaved, at least one test ran, every test, vector and wheel passed, and no test
    stayed green without its micro-feature's module (nor did docker fail under one)."""
    return (all(c["ok"] for c in controls) and bool(tests) and all(t["ok"] for t in tests)
            and all(v["ok"] for v in vectors) and all(x["allowed"] for x in lic)
            and not any(m["stayed_green"] or m["runner_fault"] for m in module_less or []))


def remaining_budget(policy: config.Policy, prev: dict[str, Any]) -> int:
    return min(policy.monthly_cap_usd_micros - prev["month_spend_usd_micros"],
               policy.stage0_rival_usd_micros - prev["stage_spend_usd_micros"])


# ---------------------------------------------------------------- commands

def cmd_control(args: argparse.Namespace) -> int:
    root = Path(args.root)
    config.check_control(root)
    config.load_bootstrap(root)
    config.load_policy(root)
    config.load_summary(root)
    print("control ok: kill switch off, budget ok, operator files valid")
    return 0


def cmd_config_value(args: argparse.Namespace) -> int:
    boot = config.load_bootstrap(Path(args.root))
    output(image=boot.image)
    return 0


def _when(text: str) -> datetime.datetime:
    return datetime.datetime.fromisoformat(str(text).replace("Z", "+00:00"))


def _unsigned_rival_run(repo: str, token: str, head: str, signed_at: datetime.datetime,
                        now: datetime.datetime) -> bool:
    """E13, W4: the newest failed run judged this head with the rival (`cagir` succeeded) but never signed (`yaz`
    failed), and no state was signed since. Running it again would call the rival again, so it waits a day."""
    try:
        run = ghapi.latest_failed_run(repo, token)
        if run is None or _when(run["created_at"]) <= signed_at:
            return False
        if now - _when(run.get("updated_at") or run["created_at"]) >= datetime.timedelta(days=1):
            return False  # a day has passed: one more try
        jobs = ghapi.run_jobs(repo, run["id"], token)
        if jobs.get("cagir") != "success" or jobs.get("yaz") not in ("failure", "timed_out"):
            return False
        art = ghapi.run_artifact(repo, run["id"], "rival", token)
        if art is None:
            return False
        with zipfile.ZipFile(io.BytesIO(ghapi.download_zip(repo, art["id"], token))) as zf:
            rival_doc = json.loads(tar_file(zf.read("rival.tar"), "rival.json") or b"{}")
        return isinstance(rival_doc, dict) and rival_doc.get("head") == head
    except Exception as exc:  # the runs API only spares a rival call here: when it fails, judge as before
        print(f"::warning::poll could not read the previous failed run: {type(exc).__name__}")
        return False


def cmd_poll(args: argparse.Namespace) -> int:
    """Cheap first look: is there anything new to judge? Installs nothing and verifies nothing.

    The previous state is read unverified here only to decide whether to skip; skipping is the
    safe outcome. Anything that is evaluated goes through ``fetch-state``, which verifies it.
    A commit that keeps failing is parked (one retry a day), stops visibly after a week or at once after an
    isolation fault (E12); a run the operator starts by hand (`workflow_dispatch`) tries it anyway.
    """
    root, out = Path(args.root), Path(args.out)
    boot = config.load_bootstrap(root)
    token = os.environ["GH_TOKEN"]
    repo = os.environ["GITHUB_REPOSITORY"]
    remote = args.remote or f"https://github.com/{boot.brain_repo}.git"
    head = gitio.remote_head(remote, boot.brain_branch)
    art = ghapi.latest_artifact(repo, STATE_ARTIFACT, token)
    if art is None:
        output(skip=False, reupload=False, head=head)
        return 0
    prev_dir = out / "prev"
    prev_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(ghapi.download_zip(repo, art["id"], token))) as zf:
        for name in ("result.json", "result.json.sigstore.json"):
            (prev_dir / name).write_bytes(zf.read(name))
    now = datetime.datetime.now(datetime.timezone.utc)
    dispatched = os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch"  # the operator asked for this run
    try:
        prev = read_json(prev_dir / "result.json")["state"]
        seen = {prev["last_accepted_sha"], prev["last_evaluated_sha"]}
        failing = prev.get("outage_sha") == head
        parked = failing and int(prev.get("outage_count", 0)) >= OUTAGE_RETRY_LIMIT
        stopped = prev.get("outage_stop") if failing else None
        since = prev.get("outage_since")
        given_up = bool(parked and since and now - _when(since) >= datetime.timedelta(days=OUTAGE_GIVE_UP_DAYS))
    except (KeyError, TypeError, ValueError, AttributeError, json.JSONDecodeError):
        seen, parked, stopped, given_up = set(), False, None, False
    created = _when(art["created_at"])
    age = now - created
    reupload = age.days >= 7
    if head not in seen and not dispatched and (stopped or given_up):
        why = f"an isolation fault ({stopped})" if stopped else f"infrastructure failures for {OUTAGE_GIVE_UP_DAYS} days"
        print(f"::error title=Commit stopped for the operator::{head} stopped after {why}. Fix the cause, then run "
              "the workflow by hand (workflow_dispatch) to try it again.")
        output(skip=True, reupload=reupload, head=head)
        return 1
    waiting = parked and age < datetime.timedelta(days=1) and not dispatched  # parked: one retry a day
    if waiting:
        print(f"::notice title=Commit parked::{head} failed {OUTAGE_RETRY_LIMIT} times for infrastructure "
              "reasons and is retried once a day")
    unsigned = head not in seen and not waiting and not dispatched and _unsigned_rival_run(repo, token, head, created, now)
    if unsigned:
        print(f"::notice title=Result never signed::{head} was judged by the rival but `yaz` failed; it is retried "
              "once a day instead of calling the rival every hour")
    output(skip=head in seen or waiting or unsigned, reupload=reupload, head=head)
    return 0


def cmd_licenses(args: argparse.Namespace) -> int:
    """Check a directory of wheels against the license allowlist; stop on any violation."""
    policy = config.load_policy(Path(args.root))
    report = licenses.check_dir(Path(args.wheels), policy.license_allowlist, policy.license_exceptions)
    if args.out:
        write_json(Path(args.out), report)
    for r in report:
        print(f"{r['name']}=={r['version']}: {r['expression']} ({'allowed' if r['allowed'] else 'NOT ALLOWED'})")
    bad = licenses.violations(report)
    if not report or bad:
        print(f"stop: license gate: {', '.join(bad) or 'no wheels found'}", file=sys.stderr)
        return 2
    return 0


def cmd_fetch_state(args: argparse.Namespace) -> int:
    root, out = Path(args.root), Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    summary_cfg = config.load_summary(root)
    token = os.environ["GH_TOKEN"]
    repo = os.environ["GITHUB_REPOSITORY"]
    art = ghapi.latest_artifact(repo, STATE_ARTIFACT, token)
    reupload = False
    if art is None:
        prev = st.initial(summary_cfg, month_now())
        summary("No previous bootstrap state artifact: starting from the setup summary's seed commit.")
    else:
        prev_dir = out / "prev"
        prev_dir.mkdir(exist_ok=True)
        with zipfile.ZipFile(io.BytesIO(ghapi.download_zip(repo, art["id"], token))) as zf:
            for name in ("result.json", "result.json.sigstore.json"):
                (prev_dir / name).write_bytes(zf.read(name))
        verify_signature(prev_dir / "result.json", prev_dir / "result.json.sigstore.json",
                         args.identity, args.sigstore_python)
        raw = read_json(prev_dir / "result.json")["state"]
        carried = st.migrate(raw, utc_now())  # an older schema is carried forward, never thrown away (`25`)
        if carried is not raw:
            summary(f"The previous state ({raw.get('schema')}) was carried forward to {st.SCHEMA}.")
        prev = st.rollover(st.validate(carried), month_now())
        created = datetime.datetime.fromisoformat(art["created_at"].replace("Z", "+00:00"))
        reupload = (datetime.datetime.now(datetime.timezone.utc) - created).days >= 7
    write_json(out / "state.json", prev)
    output(reupload=reupload)
    return 0


def cmd_pull(args: argparse.Namespace) -> int:
    root, out = Path(args.root), Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    boot = config.load_bootstrap(root)
    policy = config.load_policy(root)
    summary_cfg = config.load_summary(root)
    # The seed's stage table is loaded here, outside the content guard below: a broken table stops the run
    # (`29e` "Aşama ve parti tabloları") instead of turning into the Founder's `pull_error` rejection.
    table = stages.load(0)
    prev = read_json(Path(args.state))
    repo = Path(args.work) / "brain.git"
    remote = args.remote or f"https://github.com/{boot.brain_repo}.git"
    base = prev["last_accepted_sha"]
    head = gitio.fetch(repo, remote, boot.brain_branch, base)
    meta = _pull_meta(head, base, prev)
    if head in (base, prev["last_evaluated_sha"]):
        write_json(out / "meta.json", meta)
        output(skip=True, kind="none", head=head, run_tests=False, run_rival=False, repro=False)
        return 0
    if summary_cfg.epoch is not None:  # outside the content guard: a wrong row is the operator's to fix
        _check_epoch(repo, summary_cfg.epoch)
    waived = config.load_waivers(root)
    try:
        return _pull_classify(boot, policy, summary_cfg, table, prev, repo, base, head, meta, out, waived)
    except (ValueError, TypeError, KeyError, IndexError, AttributeError, RecursionError) as exc:
        # Content of the commit broke a step that should have named it. Rejecting it is the only safe
        # answer that does not wedge the referee: without a signed result the same head comes back every
        # hour and nothing is ever parked (E02). Git, network and operator-file errors still stop the run.
        print(f"::warning::pull could not classify {head}: {type(exc).__name__}: {str(exc)[:200]!r}")
        meta = _pull_meta(head, base, prev)
        meta.update(kind="rejected", pre_reasons=["pull_error"], waived=waived)
        write_json(out / "meta.json", meta)
        output(skip=False, kind="rejected", head=head, run_tests=False, run_rival=False, repro=False)
        return 0


def _pull_meta(head: str, base: str, prev: dict[str, Any]) -> dict[str, Any]:
    return {"schema": "snowball-bootstrap-pull/1", "head": head, "base": base, "state": prev,
            "kind": "none", "changed": [], "pre_reasons": [], "evaluate": True,
            "run_tests": False, "run_rival": False, "manifest": None, "exit_request": None, "exit_request_sha256": None,
            "referee_tree_sha256": None, "spec_dir_hashes": {}, "state_repro": [], "reuse_rival": False,
            "waived": [], "module_less": []}


def seed_trees(tar_bytes: bytes) -> tuple[str | None, str | None]:
    """The hashes of a brain tree's ``spec/tohum/`` and ``seed/`` (`26c` ``seed_epochs[]``); None for one with no files."""
    def one(prefix: str) -> str | None:
        try:
            return tree_hash(tar_bytes, prefix, forbid_operator_names=False)
        except TreeError:
            return None
    return one(SEED_DIRS[0]), one(SEED_DIRS[1])


def _check_epoch(repo: Path, epoch: config.SeedEpoch) -> None:
    """The last seed epoch names a brain commit and that commit's seed trees (`25` 10b). A row that is not its
    commit's is the operator's mistake: the run stops here, so no Founder push is judged against a seed that was
    never delivered."""
    if not gitio.has_commit(repo, epoch.commit):
        raise config.ConfigError(f"setup/summary.json: the last seed epoch's commit {epoch.commit} is not on the brain "
                                 "branch (push the delivery before writing its row)")
    if seed_trees(gitio.archive(repo, epoch.commit, SEED_DIRS)) != (epoch.spec_tohum_sha256, epoch.seed_sha256):
        raise config.ConfigError(f"setup/summary.json: the last seed epoch's hashes are not those of {epoch.commit} "
                                 "(print the row with `seed-epoch`)")


def _seed_update(repo: Path, base: str, head: str, meta: dict[str, Any], out: Path, waived: list[str]) -> int:
    """The operator's seed delivery itself (`25` 10b): nothing in it is the Founder's, so nothing is judged (E88)."""
    changed = gitio.changed_paths(repo, base, head) if gitio.has_commit(repo, base) else []
    meta.update(kind="seed_update", changed=[shown(p) for p in changed], waived=waived)
    write_json(out / "meta.json", meta)
    output(skip=False, kind="seed_update", head=head, run_tests=False, run_rival=False, repro=False)
    return 0


def _well_formed_exit_request(req: Any) -> bool:
    return (isinstance(req, dict) and set(req) == {"stage", "sha", "spec_sha256"}
            and isinstance(req["stage"], int) and not isinstance(req["stage"], bool) and 0 <= req["stage"] <= 1000
            and isinstance(req["sha"], str) and bool(config.SHA_RE.match(req["sha"]))
            and isinstance(req["spec_sha256"], str) and bool(config.HEX64_RE.match(req["spec_sha256"])))


def _base_done(repo: Path, base: str) -> set[int]:
    """The micro-features the last accepted commit had finished; none when it had no readable manifest (then every
    finished one is new, and module-less red runs for all of them)."""
    raw = gitio.file_at(repo, base, MANIFEST_FILE)
    try:
        return set(parse_manifest(raw.decode("utf-8")).done_mf) if raw is not None else set()
    except (ManifestError, UnicodeDecodeError):
        return set()


def _pull_classify(boot: config.Bootstrap, policy: config.Policy, summary_cfg: config.Summary,
                   table: stages.StageTable, prev: dict[str, Any], repo: Path, base: str, head: str,
                   meta: dict[str, Any], out: Path, waived: list[str]) -> int:
    epoch = summary_cfg.epoch
    if epoch is not None and head == epoch.commit:
        return _seed_update(repo, base, head, meta, out, waived)
    pre: list[str] = []
    base_ok = gitio.has_commit(repo, base)
    if not base_ok:
        pre.append("base_unreachable")
    elif not gitio.is_ancestor(repo, base, head):
        pre.append("history_rewritten")
    changed = gitio.changed_paths(repo, base, head) if base_ok else []
    names = changed + gitio.tree_paths(repo, head)
    if not all(map(is_utf8_name, names)):
        pre.append("non_utf8_path")  # canonical JSON cannot hold such a name: keep it out of meta.json, say so once
    elif any(path_problem(p) for p in names):
        pre.append("unsafe_path")  # a control character, a .git component, ':' or '\\' (E03, E04)
    changed = [shown(p) for p in changed]
    tar_bytes = gitio.archive(repo, head)
    readable = not {"non_utf8_path", "unsafe_path"} & set(pre)
    trees = seed_trees(tar_bytes) if readable else (None, None)
    # While the head's seed is the last epoch's commit's, the seed paths in the diff from the last accepted commit are
    # the operator's delivery, not the Founder's change (`25` 10b, E88); any other seed is checked below. Git compares
    # them: a mode change counts (the tree hashes leave the executable bit out) and an unreadable tree is no excuse
    # to charge the delivery to the Founder (E184).
    epoch_seed = epoch is not None and gitio.same_under(repo, epoch.commit, head, SEED_DIRS)
    own = [p for p in changed if not (epoch_seed and is_seed_path(p))]
    exit_raw = gitio.file_at(repo, head, EXIT_FILE)  # from its blob: readable even when another name is not
    exit_sha = hashlib.sha256(exit_raw).hexdigest() if exit_raw is not None else None
    judged = [p for p in own if not is_founder_record(p)]  # the Founder's ledger rows may ride along
    if judged == [EXIT_FILE]:
        kind = "exit"  # the same bytes asked for again alone are a request again, judged again
    else:
        # In a code push, a file byte for byte a request the referee rejected is ignored (`asama-0/10`, `26c`, E97):
        # left in place it does not make the push "not alone".
        left_in_place = exit_sha is not None and exit_sha == prev.get("rejected_exit_request")
        if left_in_place:
            own = [p for p in own if p != EXIT_FILE]
        kind, reasons = classify(own)
        pre += reasons
        if EXIT_FILE in judged and not left_in_place:
            pre.append("exit_request_not_alone")
    if {"base_unreachable", "history_rewritten", "non_utf8_path", "unsafe_path"} & set(pre):  # nothing can be read safely
        kind = "rejected"
    pre += [f"not_regular_file:{x}" for x in gitio.special_entries(repo, head)][:20]
    if len(tar_bytes) > boot.limits.max_tree_bytes:
        pre.append("tree_too_large")
    if readable:
        if trees[0] is None:
            pre.append("seed_tree_missing")
        elif not (epoch_seed if epoch is not None else trees[0] == summary_cfg.seed_tree_sha256):
            pre.append("seed_tree_mismatch")  # the head's seed is not the one the summary names (`29b`)

    manifest = None
    if kind in ("code", "exit"):
        frozen = prev["frozen_specs"].get("spec/asama-0")
        try:
            current = tree_hash(tar_bytes, "spec/asama-0", forbid_operator_names=False)
        except TreeError:
            current = None
        if frozen is None:
            pre.append("spec_not_frozen")
        elif frozen != current:
            pre.append("spec_changed_after_freeze")
        raw = tar_file(tar_bytes, MANIFEST_FILE)
        if raw is None:
            pre.append("manifest_missing")
        else:
            try:
                manifest = parse_manifest(raw.decode("utf-8"))
                pre += check_stage0(manifest, table)
                for lock in manifest.lockfiles:
                    content = tar_file(tar_bytes, lock)
                    if content is None:
                        pre.append(f"lockfile_missing:{lock}")
                    else:
                        parse_lockfile(content.decode("utf-8"))
            except (ManifestError, UnicodeDecodeError) as exc:
                pre.append(f"manifest_invalid:{str(exc)[:200]}")
        meta["manifest"] = None if manifest is None else {
            "tests": [{"id": t.id, "cmd": t.cmd, "stage": t.stage} for t in manifest.tests],
            "done_mf": list(manifest.done_mf), "lockfiles": list(manifest.lockfiles)}
        if manifest is not None and base_ok:
            # Module-less red (`asama-0/14`): for the micro-features this push finishes, and at the exit for all.
            before = set() if kind == "exit" else _base_done(repo, base)
            meta["module_less"] = [k for k in manifest.done_mf if k not in before]

    if kind == "exit":
        meta["exit_request_sha256"] = exit_sha  # rejected, these bytes are ignored in later pushes (E97)
        try:
            req = json.loads((exit_raw or b"").decode("utf-8"))
        except (ValueError, RecursionError):  # bad UTF-8 or JSON, or nested deeper than the parser goes
            req = None
        if not _well_formed_exit_request(req):
            pre.append("exit_request_malformed")
        else:
            meta["exit_request"] = req
            if req["stage"] != 0:
                pre.append("exit_request_wrong_stage")
            if req["sha"] != base:
                pre.append("exit_request_sha_is_not_last_accepted")
            if req["spec_sha256"] != prev["frozen_specs"].get("spec/asama-0"):
                pre.append("exit_request_spec_hash_mismatch")
        try:
            meta["referee_tree_sha256"] = tree_hash(tar_bytes, "referee")
        except TreeError as exc:
            pre.append(f"referee_tree:{exc}")

    if kind == "spec":
        for d in spec_stage_dirs(own):
            try:
                meta["spec_dir_hashes"][d] = tree_hash(tar_bytes, d, forbid_operator_names=False)
            except TreeError:
                pre.append(f"spec_dir_empty:{d}")

    needs_rival = kind in ("spec", "code")
    # A valid rival result whose reproducers never ran is reused for the same head, not asked for again (E20).
    pending = prev.get("pending_rival")
    reuse = needs_rival and isinstance(pending, dict) and pending.get("sha") == head
    if needs_rival and not reuse and remaining_budget(policy, prev) <= 0:
        # Recorded once for this commit; re-evaluating it every poll would only churn signatures.
        # The founder pushes again after the month or the stage budget changes.
        pre.append("budget")
    meta.update(kind=kind, changed=own, pre_reasons=sorted(set(pre)), waived=waived)
    meta["run_tests"] = kind in ("code", "exit") and not pre
    meta["run_rival"] = needs_rival and not pre and not reuse
    meta["reuse_rival"] = reuse and not pre
    # Every code head (an exit request too) is checked again for the proven defects and open claims the state
    # keeps (E07, E08): the `yeniden` job runs them even when the rival finds nothing or is not called.
    if meta["run_tests"]:
        meta["state_repro"] = ([e["key"] for e in prev.get("open_refutations", []) if e["key"] not in waived]
                               + [c["id"] for c in prev.get("open_claims", []) if c["reproducer"] is not None])
    repro = bool(meta["state_repro"]) or (meta["reuse_rival"] and any("reproducer" in a for a in pending["rival"]["attempts"]))
    write_json(out / "meta.json", meta)
    (out / "brain.tar").write_bytes(tar_bytes)
    # The rival's diff holds neither the Founder's ledger and reports (E10, E153) nor a delivered seed: a seed path
    # still in it here is the epoch's (any other seed change is rejected before the rival), not the Founder's (E88).
    (out / "diff.patch").write_text(gitio.diff_text(repo, base, head, exclude=HIDDEN_NAMES, exclude_dirs=HIDDEN_DIRS + SEED_DIRS)
                                    if base_ok else "", encoding="utf-8")
    output(skip=False, kind=kind, head=head, run_tests=meta["run_tests"], run_rival=meta["run_rival"], repro=repro)
    return 0


def cmd_fetch_deps(args: argparse.Namespace) -> int:
    pulled, out = Path(args.pulled), Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    meta = read_json(pulled / "meta.json")
    tar_bytes = (pulled / "brain.tar").read_bytes()
    locks = (meta.get("manifest") or {}).get("lockfiles", [])
    scratch = Path(args.work)
    scratch.mkdir(parents=True, exist_ok=True)
    for i, lock in enumerate(locks):
        content = tar_file(tar_bytes, lock)
        if content is None:
            raise SystemExit(f"lock file {lock} disappeared")
        parse_lockfile(content.decode("utf-8"))
        lock_path = scratch / f"lock-{i}.txt"
        lock_path.write_bytes(content)
        argv = [sys.executable, "-m", "pip", "download", "--no-deps", "--only-binary=:all:", "--require-hashes",
                "--python-version", "3.12", "--implementation", "cp",
                "--abi", "cp312", "--abi", "abi3", "--abi", "none"]
        for plat in PIP_PLATFORMS:
            argv += ["--platform", plat]
        argv += ["--index-url", "https://pypi.org/simple", "--dest", str(out), "-r", str(lock_path)]
        proc = subprocess.run(argv, capture_output=True, text=True, check=False)
        if proc.returncode != 0:
            raise SystemExit(f"pip download failed for {lock}: {proc.stderr[-1000:]}")
    wheels = {p.name: canon.sha256_file(str(p)) for p in sorted(out.glob("*.whl"))}
    write_json(out / "wheels.json", wheels)
    return 0


def _runner(boot: config.Bootstrap, src: Path, deps: Path, vectors: Path, lockfiles: list[str]) -> DockerRunner:
    return DockerRunner(image=boot.image, src_dir=str(src.resolve()), deps_dir=str(deps.resolve()),
                        vectors_dir=str(vectors.resolve()), lockfiles=tuple(lockfiles))


def cmd_run_tests(args: argparse.Namespace) -> int:
    root, pulled, out = Path(args.root), Path(args.pulled), Path(args.out)
    boot = config.load_bootstrap(root)
    policy = config.load_policy(root)
    table = stages.load(0)
    meta = read_json(pulled / "meta.json")
    tar_bytes = (pulled / "brain.tar").read_bytes()
    src = Path(args.work) / "src"
    extract(tar_bytes, src, boot.limits.max_tree_bytes)
    manifest = meta["manifest"]
    done = tuple(manifest["done_mf"])
    lic = licenses.check_dir(Path(args.deps), policy.license_allowlist, policy.license_exceptions)
    vec = fixtures(root / "vectors", Path(args.work) / "vec")  # `/vec` without the expected values
    runner = _runner(boot, src, Path(args.deps), vec, manifest["lockfiles"])
    controls = run_controls(runner)
    tests: list[dict[str, Any]] = []
    vectors: list[dict[str, Any]] = []
    module_less: list[dict[str, Any]] = []
    if all(c["ok"] for c in controls):
        for t in (x for x in manifest["tests"] if x["stage"] == 0):
            res = runner.run(t["cmd"], timeout_s=boot.limits.test_timeout_s)
            tail = (res.stdout + b"\n" + res.stderr).decode("utf-8", "replace")[-4000:]
            tests.append({"id": t["id"], "cmd_sha256": hashlib.sha256(t["cmd"].encode()).hexdigest(),
                          "exit": res.exit_code, "timed_out": res.timed_out, "duration_ms": res.duration_ms,
                          "stdout_sha256": hashlib.sha256(res.stdout).hexdigest(),
                          "stderr_sha256": hashlib.sha256(res.stderr).hexdigest(),
                          "ok": res.ok, "output_tail": tail})
        vectors = run_vectors(runner, root / "vectors", done, table=table, tree=src)
        if is_green(controls, tests, vectors, lic):  # a red push is rejected anyway: spare the containers
            module_less = run_module_less(
                lambda tree: _runner(boot, tree, Path(args.deps), vec, manifest["lockfiles"]),
                tar_bytes, Path(args.work) / "module-less", table, meta.get("module_less") or [],
                manifest["tests"], boot.limits.test_timeout_s, boot.limits.max_tree_bytes)
    green = is_green(controls, tests, vectors, lic, module_less)
    write_json(out / "run.json", {"controls": controls, "tests": tests, "vectors": vectors, "licenses": lic,
                                  "module_less": module_less,
                                  "vector_groups_missing": missing_groups(root / "vectors", done, table, tree=src),
                                  "green": green})
    output(green=green)
    return 0


def _pages(tar_bytes: bytes, kind: str) -> dict[str, str]:
    pages: dict[str, str] = {}
    prefixes = [f"spec/tohum/{p}" for p in (SPEC_PAGES if kind == "spec" else CODE_PAGES)]
    if kind != "spec":
        prefixes += [f"spec/{p}" for p in CODE_STAGE_PAGES]
    for prefix in prefixes:
        found = tar_page(tar_bytes, prefix)
        if found:
            pages[found[0]] = found[1]
    return pages


def cmd_rival(args: argparse.Namespace) -> int:
    root, pulled, out = Path(args.root), Path(args.pulled), Path(args.out)
    boot = config.load_bootstrap(root)
    policy = config.load_policy(root)
    meta = read_json(pulled / "meta.json")
    tar_bytes = (pulled / "brain.tar").read_bytes()
    tree = Path(args.work) / "tree"
    extract(tar_bytes, tree, boot.limits.max_tree_bytes)
    seat = extract_seat_prompt((root / "seats" / SEATS_FILE).read_text(encoding="utf-8"))
    changed = [p for p in meta["changed"] if not hidden(p)]  # the Founder's ledger is not the rival's to see (E10)
    context = build_context(meta["kind"], meta["base"], meta["head"], changed,
                            (pulled / "diff.patch").read_text(encoding="utf-8"), _pages(tar_bytes, meta["kind"]),
                            open_claims=meta["state"].get("open_claims", []))
    outcome = RivalOutcome()
    try:
        run_rival(boot.rival, claude_bin=resolve_claude(args.claude), seat_prompt=seat, context=context,
                  tree_root=tree, budget_usd_micros=remaining_budget(policy, meta["state"]),
                  max_prompt_chars=boot.limits.max_prompt_chars, out=outcome)
    finally:  # on every path, an interrupt too: what the run spent must reach `decide` (E13)
        result = outcome.as_dict()
        result["head"] = meta["head"]  # `poll` reads it from a run whose result was never signed
        write_json(out / "rival.json", result)
    output(has_repro=result["reproducer_count"] > 0 and result["verdict"] in ("refuted", "not_refuted"))
    outage = [r for r in result["reasons"] if str(r).startswith("api_error")]
    if outage:  # the job stays green so rival.json reaches `decide`, which books the cost and retries the commit
        print(f"::warning title=The seed rival could not run::{', '.join(outage)}")
    rejected = [r for r in result["reasons"] if str(r).startswith("request_rejected")]
    if rejected:
        print(f"::warning title=The API rejected the rival's request::{', '.join(rejected)}")
    return 0


def cmd_reproduce(args: argparse.Namespace) -> int:
    """The rival's reproducers (of this run, or of the pending result a retry reuses, E20) and the state's
    (proven defects and open claims, E07 E08), each on the head and, if it showed, on an empty tree (E09)."""
    root, pulled, out = Path(args.root), Path(args.pulled), Path(args.out)
    boot = config.load_bootstrap(root)
    meta = read_json(pulled / "meta.json")
    state = meta.get("state") or {}
    rival_file = Path(args.rival) / "rival.json"
    rival = read_json(rival_file) if rival_file.exists() else None
    if rival is None and meta.get("reuse_rival"):
        rival = (state.get("pending_rival") or {}).get("rival")
    attempts = rival["attempts"] if rival and rival.get("verdict") in ("refuted", "not_refuted") else []
    work = Path(args.work)
    src = work / "src"
    extract((pulled / "brain.tar").read_bytes(), src, boot.limits.max_tree_bytes)
    work.mkdir(parents=True, exist_ok=True)
    empty = Path(tempfile.mkdtemp(prefix="control-", dir=work))  # the control tree: nothing in it at all
    empty.chmod(0o755)  # mkdtemp makes it 0700; the container's user (65534) must be able to copy it like /src
    locks = (meta.get("manifest") or {}).get("lockfiles", [])
    vec = fixtures(root / "vectors", work / "vec")  # `/vec` without the expected values, as in run-tests
    runner = _runner(boot, src, Path(args.deps), vec, locks)
    control = _runner(boot, empty, Path(args.deps), vec, [])
    timeout = boot.limits.reproducer_timeout_s
    repro = run_reproducers(runner, attempts, timeout, control=control)
    wanted = set(meta.get("state_repro") or [])
    entries = ([{"key": e["key"], "source": "refutation", "reproducer": e["reproducer"]}
                for e in state.get("open_refutations", []) if e["key"] in wanted]
               + [{"key": c["id"], "source": "claim", "reproducer": c["reproducer"]}
                  for c in state.get("open_claims", []) if c["id"] in wanted and c["reproducer"] is not None])
    state_results = run_state_reproducers(runner, entries, timeout, control=control)
    write_json(out / "repro.json", {"results": repro, "state": state_results})
    return 0


def cmd_decide(args: argparse.Namespace) -> int:
    root, pulled, out = Path(args.root), Path(args.pulled), Path(args.out)
    policy = config.load_policy(root)
    meta = read_json(pulled / "meta.json")

    def optional(path: str | None, name: str) -> Any:
        if not path:
            return None
        p = Path(path) / name
        return read_json(p) if p.exists() else None

    run = optional(args.run, "run.json")
    rival = optional(args.rival, "rival.json")
    repro_doc = optional(args.repro, "repro.json")
    jobs = dict(item.split("=", 1) for item in args.job or [])
    result = decide(meta, run, rival, None if repro_doc is None else repro_doc["results"], jobs,
                    policy.rival_min_attempts, policy.repeat_reject_limit,
                    state_repro=None if repro_doc is None else repro_doc.get("state", []), now=utc_now())
    result["run"] = {"id": os.environ.get("GITHUB_RUN_ID", "local"),
                     "attempt": os.environ.get("GITHUB_RUN_ATTEMPT", "1")}
    write_json(out / "result.json", result)
    lines = [f"## Bootstrap referee: {result['verdict']}", "",
             f"- kind: `{result['kind']}`", f"- head: `{result['head']}`", f"- base: `{result['base']}`"]
    for r in result["reasons"]:
        lines.append(f"- reason: `{r['kind']}` {r.get('test_id', '')} `{r['ref']}`")
    for sig in result["learning"]["not_learning"]:
        lines.append(f"- **not learning**: `{sig}` rejected {policy.repeat_reject_limit} or more times in a row")
    for warning in result["warnings"]:
        lines.append(f"- **warning**: `{warning}`")
    if result["exit"].get("transferable"):
        lines.append(f"- **transferable**: referee tree `{result['exit']['referee_tree_sha256']}`")
    summary("\n".join(lines))
    # What only the operator can act on is said where GitHub shows it; the run itself stays green and signs.
    streak = [w for w in result["warnings"] if w.startswith("rival_side_streak")]
    if streak:
        print(f"::warning title=Rival-side failures::{streak[0]}: the rival itself failed on consecutive pushes "
              "(model, verdict, refusal, budget); none of it counts against the Founder")
    rejected = [w for w in result["warnings"] if w.startswith("request_rejected")]
    if rejected:
        print(f"::warning title=Request rejected by the API::{', '.join(rejected)}")
    groups = [w.split(":", 1)[1] for w in result["warnings"] if w.startswith("vector_group_missing:")]
    if groups:
        print(f"::warning title=Seed vector groups missing::{', '.join(groups)}: a finished micro-feature owns them "
              "but the seed has no vectors yet; the exit waits for them (a seed epoch adds them, not the Founder)")
    if result["state"].get("outage_stop"):
        print(f"::error title=Stopped for the operator::{result['state']['outage_stop']} on {result['head']}: the "
              "referee will not retry it by itself")
    output(verdict=result["verdict"])
    return 0


def cmd_pack(args: argparse.Namespace) -> int:
    output(sha256=pack_dir(Path(args.dir), Path(args.out)))
    return 0


def cmd_unpack(args: argparse.Namespace) -> int:
    unpack(Path(args.tar), args.sha256, Path(args.out))
    return 0


def cmd_seed_hash(args: argparse.Namespace) -> int:
    tar_bytes = gitio.archive(Path(args.brain), args.commit)
    print(tree_hash(tar_bytes, "spec/tohum", forbid_operator_names=False))
    return 0


def cmd_seed_epoch(args: argparse.Namespace) -> int:
    """The ``seed_epochs[]`` row of a seed delivery (`25` 10b, `26c`): the delivered brain commit with its seed trees,
    and the ``seed/bootstrap/`` the referee runs (read from ``--source``, by default the brain commit itself)."""
    brain = Path(args.brain)
    commit = gitio.git(brain, "rev-parse", "--verify", f"{args.commit}^{{commit}}").decode().strip()
    spec_tohum, seed = seed_trees(gitio.archive(brain, commit, SEED_DIRS))
    if spec_tohum is None:
        raise TreeError(f"no files under spec/tohum/ at {commit}: that is not a seed delivery")
    source = Path(args.source) if args.source else brain
    bootstrap = tree_hash(gitio.archive(source, args.source_commit or commit, ("seed/bootstrap",)), "seed/bootstrap",
                          forbid_operator_names=False)
    print(canon.dump({"commit": commit, "spec_tohum_sha256": spec_tohum, "seed_sha256": seed,
                      "bootstrap_sha256": bootstrap}), end="")
    return 0


def cmd_import(args: argparse.Namespace) -> int:
    log = run_import(Path(args.result), Path(args.bundle), args.identity, args.sigstore_python,
                     Path(args.brain), Path(args.referee), Path(args.toy) if args.toy else None)
    print(json.dumps(log, indent=2, sort_keys=True))
    print("Review `git status` in the referee and toy checkouts, then commit and push them yourself.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="snowball_bootstrap")
    sub = parser.add_subparsers(dest="command", required=True)

    def add(name: str, fn, *opts: tuple[str, dict]) -> None:
        p = sub.add_parser(name)
        for flag, kw in opts:
            p.add_argument(flag, **kw)
        p.set_defaults(fn=fn)

    root = ("--root", {"default": "."})
    req = {"required": True}
    add("control", cmd_control, root)
    add("config-value", cmd_config_value, root)
    add("poll", cmd_poll, root, ("--out", req), ("--remote", {}))
    add("licenses", cmd_licenses, root, ("--wheels", req), ("--out", {}))
    add("fetch-state", cmd_fetch_state, root, ("--out", req), ("--identity", req), ("--sigstore-python", req))
    add("pull", cmd_pull, root, ("--state", req), ("--work", req), ("--out", req), ("--remote", {}))
    add("fetch-deps", cmd_fetch_deps, ("--pulled", req), ("--work", req), ("--out", req))
    add("run-tests", cmd_run_tests, root, ("--pulled", req), ("--deps", req), ("--work", req), ("--out", req))
    add("rival", cmd_rival, root, ("--pulled", req), ("--work", req), ("--out", req),
        ("--claude", {"help": "path of the claude CLI (default: the one on PATH)"}))
    add("reproduce", cmd_reproduce, root, ("--pulled", req), ("--deps", req), ("--rival", req),
        ("--work", req), ("--out", req))
    add("decide", cmd_decide, root, ("--pulled", req), ("--run", {}), ("--rival", {}), ("--repro", {}),
        ("--job", {"action": "append"}), ("--out", req))
    add("pack", cmd_pack, ("--dir", req), ("--out", req))
    add("unpack", cmd_unpack, ("--tar", req), ("--sha256", req), ("--out", req))
    add("seed-hash", cmd_seed_hash, ("--brain", req), ("--commit", req))
    add("seed-epoch", cmd_seed_epoch, ("--brain", req), ("--commit", req),
        ("--source", {"help": "repository whose seed/bootstrap/ the referee runs (default: the brain)"}),
        ("--source-commit", {"help": "commit of --source (default: --commit)"}))
    add("import", cmd_import, ("--result", req), ("--bundle", req), ("--identity", req),
        ("--sigstore-python", req), ("--brain", req), ("--referee", req), ("--toy", {}))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.fn(args)
    except (config.ConfigError, ImportErrorStop, gitio.GitError, TreeError) as exc:
        print(f"stop: {exc}", file=sys.stderr)
        return 2
