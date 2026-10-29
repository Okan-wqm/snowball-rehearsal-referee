import io
import json
import os
import tempfile
import threading
import unittest
import zipfile
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from snowball_bootstrap import cli, ghapi, state as st
from snowball_bootstrap.config import ConfigError, Summary

from helpers import commit, make_repo, posix_only


class _Api(BaseHTTPRequestHandler):
    seen: list = []
    artifacts: list = []
    zip_bytes = b""

    def do_GET(self):  # noqa: N802
        _Api.seen.append((self.path, self.headers.get("Authorization")))
        if self.path.startswith("/repos/o/r/actions/artifacts?"):
            body = json.dumps({"artifacts": _Api.artifacts}).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path.endswith("/zip"):
            self.send_response(302)
            self.send_header("Location", "https://storage.invalid/blob")
            self.end_headers()
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, *args):
        pass


class StateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "setup").mkdir()
        (self.root / "setup" / "summary.json").write_text(json.dumps(
            {"seed_commit": "a" * 40, "seed_tree_sha256": "b" * 64}))
        _Api.seen, _Api.artifacts = [], []
        self.server = HTTPServer(("127.0.0.1", 0), _Api)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.env = dict(os.environ)
        os.environ.update({"GITHUB_API_URL": f"http://127.0.0.1:{self.server.server_port}",
                           "GH_TOKEN": "tok", "GITHUB_REPOSITORY": "o/r"})
        os.environ.pop("GITHUB_OUTPUT", None)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.env)
        self.server.shutdown()
        self.server.server_close()
        self.tmp.cleanup()

    def fetch(self):
        return cli.main(["fetch-state", "--root", str(self.root), "--out", str(self.root / "state"),
                         "--identity", "id", "--sigstore-python", "/bin/false"])

    def test_first_run_starts_from_the_seed_commit(self):
        self.assertEqual(self.fetch(), 0)
        state = json.loads((self.root / "state" / "state.json").read_text())
        self.assertEqual(state["last_accepted_sha"], "a" * 40)
        self.assertEqual(state["origin"], "initial")

    def test_only_the_newest_unexpired_state_of_a_main_run_is_used(self):
        """E17 and T3: an artifact from another branch, an expired one or an older one is never chosen."""
        def art(i, created, branch="main", expired=False):
            return {"id": i, "name": "bootstrap-state", "expired": expired, "created_at": created,
                    "workflow_run": {"head_branch": branch}}
        _Api.artifacts = [art(1, "2026-10-01T00:00:00Z"), art(2, "2026-10-03T00:00:00Z"),
                          art(3, "2026-10-05T00:00:00Z", branch="evil"),
                          art(4, "2026-10-06T00:00:00Z", expired=True), art(5, "2026-10-02T00:00:00Z")]
        self.assertEqual(ghapi.latest_artifact("o/r", "bootstrap-state", "t")["id"], 2)
        _Api.artifacts = [art(3, "2026-10-05T00:00:00Z", branch="evil")]
        self.assertIsNone(ghapi.latest_artifact("o/r", "bootstrap-state", "t"))

    def test_token_is_not_sent_to_the_storage_redirect(self):
        _Api.artifacts = [{"id": 5, "name": "bootstrap-state", "expired": False, "workflow_run": {"head_branch": "main"},
                           "created_at": "2026-10-28T00:00:00Z"}]
        from snowball_bootstrap import ghapi
        import urllib.request
        captured = {}
        real_urlopen = urllib.request.urlopen

        def fake_urlopen(req, timeout=None):
            if isinstance(req, urllib.request.Request) and req.full_url.startswith("https://storage.invalid"):
                captured["auth"] = req.get_header("Authorization")
                buf = io.BytesIO()
                with zipfile.ZipFile(buf, "w") as zf:
                    zf.writestr("result.json", "{}")
                    zf.writestr("result.json.sigstore.json", "{}")
                return io.BytesIO(buf.getvalue())
            return real_urlopen(req, timeout=timeout)

        ghapi.urllib.request.urlopen = fake_urlopen
        try:
            data = ghapi.download_zip("o/r", 5, "tok")
        finally:
            ghapi.urllib.request.urlopen = real_urlopen
        self.assertTrue(zipfile.is_zipfile(io.BytesIO(data)))
        self.assertIsNone(captured["auth"])
        self.assertEqual(_Api.seen[-1][1], "Bearer tok")

    @posix_only
    def test_unverifiable_previous_state_stops_the_run(self):
        _Api.artifacts = [{"id": 5, "name": "bootstrap-state", "expired": False, "workflow_run": {"head_branch": "main"},
                           "created_at": "2026-10-28T00:00:00Z"}]
        from snowball_bootstrap import ghapi
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("result.json", "{}")
            zf.writestr("result.json.sigstore.json", "{}")
        original = ghapi.download_zip
        ghapi.download_zip = lambda repo, aid, token: buf.getvalue()
        try:
            self.assertEqual(self.fetch(), 2)  # /bin/false as sigstore: verification fails closed
        finally:
            ghapi.download_zip = original

    def test_poll_skips_only_a_head_it_has_already_seen(self):
        from snowball_bootstrap import ghapi
        brain = self.root / "brain"
        head = make_repo(brain, {"a.txt": "1\n"})
        (self.root / "bootstrap.json").write_text(json.dumps({
            "brain_repo": "owner/brain", "brain_branch": "main",
            "image": "docker.io/library/python:3.12-slim@sha256:" + "a" * 64,
            "rival": {"model": "claude-sonnet-5-5", "effort": "medium", "max_turns": 30,
                      "per_run_cap_usd_micros": 1},
            "limits": {"test_timeout_s": 1, "reproducer_timeout_s": 1, "max_prompt_chars": 1, "max_tree_bytes": 1}}))
        outputs = self.root / "outputs.txt"
        os.environ["GITHUB_OUTPUT"] = str(outputs)

        def poll() -> dict:
            outputs.write_text("")
            argv = ["poll", "--root", str(self.root), "--out", str(self.root / "p"), "--remote", str(brain)]
            self.assertEqual(cli.main(argv), 0)
            return dict(line.split("=", 1) for line in outputs.read_text().splitlines())

        self.assertEqual(poll()["skip"], "false")  # no state yet: evaluate
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("result.json", json.dumps({"state": {"last_accepted_sha": head, "last_evaluated_sha": None}}))
            zf.writestr("result.json.sigstore.json", "{}")
        _Api.artifacts = [{"id": 5, "name": "bootstrap-state", "expired": False, "workflow_run": {"head_branch": "main"},
                           "created_at": "2020-01-01T00:00:00Z"}]
        original = ghapi.download_zip
        ghapi.download_zip = lambda repo, aid, token: buf.getvalue()
        try:
            seen = poll()
            self.assertEqual((seen["skip"], seen["reupload"], seen["head"]), ("true", "true", head))
            commit(brain, {"a.txt": "2\n"}, "new")
            self.assertEqual(poll()["skip"], "false")
        finally:
            ghapi.download_zip = original

    def test_state_validation_and_rollover(self):
        s = st.initial(Summary("a" * 40, "b" * 64), "2026-10")
        s["month_spend_usd_micros"] = 5
        self.assertEqual(st.rollover(st.validate(s), "2026-11")["month_spend_usd_micros"], 0)
        self.assertEqual(st.rollover(s, "2026-10")["month_spend_usd_micros"], 5)
        for bad in (dict(s, rival_artifacts=["not-a-sha"]), dict(s, reject_streaks={"x": 0}),
                    dict(s, repeat_events=-1)):
            with self.assertRaises(ConfigError):
                st.validate(bad)


class PackTest(unittest.TestCase):
    def test_pack_is_deterministic_and_unpack_checks_the_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "src"
            (src / "a").mkdir(parents=True)
            (src / "a" / "x.json").write_text("{}")
            first = cli.pack_dir(src, Path(tmp) / "1.tar")
            os.utime(src / "a" / "x.json", (1, 1))
            self.assertEqual(cli.pack_dir(src, Path(tmp) / "2.tar"), first)
            cli.unpack(Path(tmp) / "1.tar", first, Path(tmp) / "out")
            self.assertEqual((Path(tmp) / "out" / "a" / "x.json").read_text(), "{}")
            with self.assertRaises(SystemExit):
                cli.unpack(Path(tmp) / "1.tar", "0" * 64, Path(tmp) / "out2")


class ControlTest(unittest.TestCase):
    def test_kill_switch_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for control, expected in ([{"kill_switch": False, "budget_state": "ok"}, None],
                                      [{"kill_switch": True, "budget_state": "ok"}, "kill switch"],
                                      [{"budget_state": "ok"}, "kill switch"],
                                      [{"kill_switch": False, "budget_state": "exhausted"}, "budget"]):
                (root / "control.json").write_text(json.dumps(control))
                from snowball_bootstrap.config import check_control
                if expected is None:
                    check_control(root)
                else:
                    with self.assertRaises(ConfigError) as ctx:
                        check_control(root)
                    self.assertIn(expected, str(ctx.exception))


if __name__ == "__main__":
    unittest.main()


class OutageMemoryTest(unittest.TestCase):
    def test_an_artifact_of_an_unknown_bootstrap_version_is_refused_with_the_remedy(self):
        """A known older schema is migrated (`state.migrate`); a shape no migration knows still stops, and the
        message points at the recovery in tohum/25 instead of telling the operator to delete the state (E14)."""
        from snowball_bootstrap.config import ConfigError
        s = st.initial(Summary("a" * 40, "b" * 64), "2026-10")
        old = {k: v for k, v in s.items() if k not in ("outage_sha", "outage_count")}
        with self.assertRaises(ConfigError) as ctx:
            st.validate(st.migrate(old, "2026-10-29T00:00:00Z"))
        message = str(ctx.exception)
        self.assertIn("missing: outage_count, outage_sha", message)
        self.assertIn("tohum/25", message)
        self.assertNotIn("delete", message)

    def test_the_outage_fields_are_validated_and_required(self):
        from snowball_bootstrap.config import ConfigError
        s = st.initial(Summary("a" * 40, "b" * 64), "2026-10")
        self.assertEqual((s["outage_sha"], s["outage_count"]), (None, 0))
        st.validate(dict(s, outage_sha="c" * 40, outage_count=2))
        for bad in (dict(s, outage_sha="not-a-sha"), dict(s, outage_count=-1), dict(s, outage_count=True),
                    {k: v for k, v in s.items() if k != "outage_count"},
                    {k: v for k, v in s.items() if k != "outage_sha"}):
            with self.assertRaises(ConfigError):
                st.validate(bad)
