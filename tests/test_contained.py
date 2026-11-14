"""Test 21 (asama-0/09) and group ``contained`` (asama-0/14): the contained run, with the fake runner.

- argv: the built argv carries ``--network none``, ``--cap-drop ALL``, ``--read-only`` and a non-root
  ``--user`` as adjacent tokens; ``check_argv`` refuses every argv outside the allowlist (each forbidden
  flag, each mandatory flag removed, each bad value), on the command line too.
- canary: a command tries to reach the network, write outside the container and read a host secret
  from its environment; all three fail, judged from outside: a listener that counts connections, hashes
  of files outside the run taken before and after, and a search of every output for the secret.
- fresh host directory per run, results hashed outside (symlinks not followed, FIFO not opened),
  ``operating`` limits, docker failure, a changed read-only input, the kill on timeout.

Temporary directories go under the first writable of TMPDIR, /tmp, /dev/shm (the referee's container
is read-only); with none writable the tests fail, they are never skipped. The fake runner is ``fake_docker.py``; what it does not emulate is listed there.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import unittest

REFEREE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REFEREE)

from runner import contained  # noqa: E402
import refusal  # noqa: E402
from fake_docker import FakeDocker, FixedRunner  # noqa: E402

PROBE = os.path.join(REFEREE, "tests", "fixtures", "probe.py")
IMAGE = "python:3.12-slim@sha256:" + "ab" * 32
MANDATORY_PAIRS = [("--network", "none"), ("--cap-drop", "ALL"), ("--user", "65534:65534")]


def operating(**over) -> dict:
    values = {"container_mem_bytes": 512 * 1024 * 1024, "kos_wall_s": 60, "worktree_bytes": 10 ** 7,
              "output_bytes": 10 ** 6}
    values.update(over)
    return {k: {"value": v, "band": [1, 10 ** 12]} for k, v in values.items()}


def writable_base() -> str:
    for cand in (os.environ.get("TMPDIR"), "/tmp", "/dev/shm"):
        if cand and os.path.isdir(cand):
            try:
                return tempfile.mkdtemp(prefix="t-contained-", dir=cand)
            except OSError:
                continue
    raise AssertionError("no writable temporary directory: test 21 cannot run, so it fails")


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def snapshot(top: str) -> dict:
    """Independent outside snapshot: relative path -> sha256 of a file, 'link:'+target, or 'dir'."""
    out = {}
    for dirpath, dirnames, filenames in os.walk(top):
        for name in dirnames + filenames:
            p = os.path.join(dirpath, name)
            rel = os.path.relpath(p, top)
            if os.path.islink(p):
                out[rel] = "link:" + os.readlink(p)
            elif os.path.isdir(p):
                out[rel] = "dir"
            else:
                with open(p, "rb") as fh:
                    out[rel] = sha(fh.read())
    return out


def good_argv(root: str = "/tmp/snowball-run-x", artifacts: bool = True) -> list[str]:
    return contained.build_argv(IMAGE, ["python3", "/work/t.py"], root, operating(), env={"LANG": "C.UTF-8"},
                                artifacts=artifacts, name="snowball-" + "0" * 32)


class Listener:
    def __init__(self) -> None:
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(8)
        self.sock.settimeout(0.2)
        self.port = self.sock.getsockname()[1]
        self.accepted = 0
        self.stop = False
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()

    def _loop(self) -> None:
        while not self.stop:
            try:
                conn, _ = self.sock.accept()
                self.accepted += 1
                conn.close()
            except OSError:
                continue

    def close(self) -> None:
        self.stop = True
        self.thread.join()
        self.sock.close()


class Base(unittest.TestCase):
    def setUp(self) -> None:
        self.base = writable_base()
        self.addCleanup(shutil.rmtree, self.base, True)
        self.tree = os.path.join(self.base, "tree")
        os.mkdir(self.tree)
        shutil.copy(PROBE, os.path.join(self.tree, "probe.py"))

    def job(self, *steps: str, artifacts: str | None = None, env: dict | None = None) -> dict:
        job = {"image": IMAGE, "cmd": ["python3", "/work/probe.py", *steps], "tree": self.tree}
        if artifacts:
            job["artifacts"] = artifacts
        if env:
            job["env"] = env
        return job


# ---------------------------------------------------------------- argv (group contained)

class ArgvTest(unittest.TestCase):
    def test_built_argv_has_mandatory_flags_as_adjacent_tokens(self):
        argv = good_argv()
        self.assertEqual(argv[:2], ["docker", "run"])
        for flag, value in MANDATORY_PAIRS:
            i = argv.index(flag)
            self.assertEqual(argv[i + 1], value)
        self.assertIn("--read-only", argv)
        self.assertEqual(argv[argv.index("--pull") + 1], "never")
        self.assertEqual(argv[argv.index("--memory") + 1], str(512 * 1024 * 1024))
        self.assertEqual(argv[-3:], [IMAGE, "python3", "/work/t.py"])
        self.assertEqual(contained.check_argv(argv), {"ok": True, "missing": [], "forbidden": []})

    def test_each_mandatory_flag_removed_is_missing(self):
        argv = good_argv()
        for flag in ("--network", "--cap-drop", "--user", "--memory", "--memory-swap", "--pull", "--security-opt",
                     "--name", "--workdir"):
            i = argv.index(flag)
            cut = argv[:i] + argv[i + 2:]
            rep = contained.check_argv(cut)
            self.assertFalse(rep["ok"], flag)
            self.assertIn(flag, rep["missing"], flag)
        for flag in ("--read-only", "--rm"):
            cut = [a for a in argv if a != flag]
            rep = contained.check_argv(cut)
            self.assertFalse(rep["ok"], flag)
            self.assertIn(flag, rep["missing"])

    def test_forbidden_insertions_are_refused(self):
        argv = good_argv()
        at = argv.index("--workdir")
        inserts = [
            ["--privileged"], ["--network", "host"], ["--net", "host"], ["--network=host"], ["--cap-add", "ALL"],
            ["--cap-add=SYS_ADMIN"], ["-v", "/var/run/docker.sock:/var/run/docker.sock"],
            ["--volume", "/:/host"], ["--pid", "host"], ["--ipc", "host"], ["--userns", "host"],
            ["--uts", "host"], ["--device", "/dev/sda"], ["--security-opt", "seccomp=unconfined"],
            ["--env-file", "/proc/self/environ"], ["--volumes-from", "x"], ["-p", "80:80"], ["--add-host", "a:1.2.3.4"],
            ["--env", "ACTIONS_RUNTIME_URL=x"], ["--env", "GITHUB_SHA=x"], ["--env", "runner_temp=x"],
            ["--env", "HOME"], ["--env", "1BAD=x"], ["-e", "A=b"], ["--read-only=false"], ["--rm=false"],
            ["--mount", "type=bind,src=/var/run/docker.sock,dst=/var/run/docker.sock"],
            ["--mount", "type=bind,src=/tmp/snowball-run-x/out,dst=/out"],
            ["--mount", "type=volume,src=v,dst=/work2"], ["--tmpfs", "/tmp"], ["--cgroupns", "host"], ["--"],
        ]
        for extra in inserts:
            rep = contained.check_argv(argv[:at] + extra + argv[at:])
            self.assertFalse(rep["ok"], extra)
            self.assertTrue(rep["forbidden"], extra)

    def test_bad_values_are_refused(self):
        argv = good_argv()

        def with_value(flag: str, value: str) -> list[str]:
            out = list(argv)
            out[out.index(flag) + 1] = value
            return out

        for flag, value in [("--network", "bridge"), ("--network", "none "), ("--cap-drop", "NET_RAW"),
                            ("--user", "0"), ("--user", "0:0"), ("--user", "root"), ("--user", "65534:0"),
                            ("--user", "0:65534"), ("--user", "65534"), ("--user", "nobody:nogroup"),
                            ("--memory", "1"), ("--memory", "-1"), ("--memory-swap", "-1"),
                            ("--memory-swap", str(1024 ** 3)), ("--pull", "always"),
                            ("--security-opt", "apparmor=unconfined"), ("--workdir", "/"),
                            ("--name", "other")]:
            rep = contained.check_argv(with_value(flag, value))
            self.assertFalse(rep["ok"], (flag, value))

    def test_image_must_be_pinned_and_command_present(self):
        argv = good_argv()
        i = argv.index(IMAGE)
        for image in ["python:3.12", "python@sha256:" + "ab" * 31, "python@sha256:" + "AB" * 32,
                      "python@sha512:" + "ab" * 64, "--privileged", "Python@sha256:" + "ab" * 32]:
            bad = list(argv)
            bad[i] = image
            self.assertFalse(contained.check_argv(bad)["ok"], image)
        self.assertIn("command", contained.check_argv(argv[: i + 1])["missing"])
        self.assertIn("image", contained.check_argv(argv[:i])["missing"])
        pinned = list(argv)
        pinned[i] = "ghcr.io:443/org/img_x:1.2@sha256:" + "0f" * 32
        self.assertTrue(contained.check_argv(pinned)["ok"])

    def test_mounts_one_root_fixed_targets(self):
        argv = good_argv()
        mounts = [i for i, a in enumerate(argv) if a == "--mount"]

        def with_mount(n: int, value: str) -> list[str]:
            out = list(argv)
            out[mounts[n] + 1] = value
            return out

        for n, value in [(0, "type=bind,src=/tmp/other/work,dst=/work"), (0, "type=bind,src=/tmp/snowball-run-x/out,dst=/work"),
                         (0, "type=bind,src=/tmp/snowball-run-x/work,dst=/work,readonly"),
                         (2, "type=bind,src=/tmp/snowball-run-x/in,dst=/in"),
                         (1, "type=bind,src=/tmp/snowball-run-x/out,dst=/out,bind-propagation=shared"),
                         (0, "type=bind,src=/tmp/../work,dst=/work"), (0, "type=bind,src=/work,dst=/work"),
                         (0, "type=bind,src=/tmp/a b/work,dst=/work"), (0, "type=bind,src=tmp/x/work,dst=/work"),
                         (0, "type=bind,src=/tmp//x/work,dst=/work"), (0, "type=bind,src=/tmp/x/./work,dst=/work"),
                         (0, 'type=bind,src="/tmp/x/work",dst=/work'), (0, "type=bind,source=/tmp/x/work,target=/work")]:
            self.assertFalse(contained.check_argv(with_mount(n, value))["ok"], value)
        no_out = argv[: mounts[1]] + argv[mounts[1] + 2:]
        self.assertIn("--mount /out", contained.check_argv(no_out)["missing"])
        self.assertTrue(contained.check_argv(good_argv(artifacts=False))["ok"])

    def test_prefix_and_shape(self):
        argv = good_argv()
        for bad in (["docker", "-H", "tcp://x:2375", "run"] + argv[2:], ["/usr/bin/docker"] + argv[1:],
                    ["podman"] + argv[1:], ["docker", "create"] + argv[2:], "docker run", None, [1, 2]):
            self.assertFalse(contained.check_argv(bad)["ok"], bad)

    def test_builder_refuses_what_check_would(self):
        root = "/tmp/snowball-run-x"
        for kwargs in [dict(uid=0), dict(gid=0), dict(env={"ACTIONS_CACHE_URL": "x"}),
                       dict(env={"GITHUB_SHA": "x"}), dict(env={"A": 1})]:
            with self.assertRaises(contained.ContainmentError, msg=kwargs):
                contained.build_argv(IMAGE, ["true"], root, operating(), **kwargs)
        for image, cmd, rroot, op in [("python:3.12", ["true"], root, operating()), (IMAGE, [], root, operating()),
                                      (IMAGE, ["true"], "/tmp/a,b", operating()), (IMAGE, ["true"], "", operating()),
                                      (IMAGE, ["true"], root, {}),
                                      (IMAGE, ["true"], root, {"container_mem_bytes": {"value": 10 ** 9, "band": [1, 10]}}),
                                      (IMAGE, ["true"], root, {"container_mem_bytes": {"value": 1024, "band": [1, 10 ** 9]}}),
                                      (IMAGE, ["true"], root, {"container_mem_bytes": {"value": True, "band": [0, 9]}})]:
            with self.assertRaises(contained.ContainmentError, msg=(image, cmd, rroot, op)):
                contained.build_argv(image, cmd, rroot, op)

    def test_command_line_check(self):
        argv = good_argv()
        for argv_in, code in [(argv, 0), (argv[:4] + ["--privileged"] + argv[4:], 1),
                              ([a for a in argv if a != "--read-only"], 1)]:
            p = subprocess.run([sys.executable, "-m", "runner.contained", "check"], cwd=REFEREE,
                               input=json.dumps(argv_in), capture_output=True, text=True)
            self.assertEqual(p.returncode, code, p.stdout)
            self.assertEqual(json.loads(p.stdout)["ok"], code == 0)
        p = subprocess.run([sys.executable, "-m", "runner.contained", "check"], cwd=REFEREE, input="not json",
                           capture_output=True, text=True)
        self.assertEqual(p.returncode, 2)

    def test_command_line_unusable_input_is_exit_2_never_traceback(self):
        deep = "[" * 200000
        run_file = os.path.join(tempfile.mkdtemp(prefix="t-cli-"), "run.json")
        self.addCleanup(shutil.rmtree, os.path.dirname(run_file), True)
        with open(run_file, "w") as fh:
            fh.write(deep)
        cases = ((["check"], deep), (["argv"], deep), (["run", run_file], ""), (["check"], "not json"),
                 (["run", run_file + ".missing"], ""), (["argv"], "[1]"))
        for args, stdin in cases:
            p = subprocess.run([sys.executable, "-m", "runner.contained", *args], cwd=REFEREE, input=stdin,
                               capture_output=True, text=True, timeout=60)
            line = json.loads(p.stdout.splitlines()[-1])
            refusal.assert_refused(self, contained, args, p.returncode, line, p.stderr)
            if args == ["argv"]:  # tohum/29f: {"ok": false} with a free reason
                self.assertIs(line["ok"], False, args)
                self.assertIsInstance(line["reason"], str, args)
            else:
                self.assertIn("error", line, args)

    def test_unexpected_exception_is_exit_2_not_refusal(self):
        """No module catch-all: the exception reaches ``cli.run``, which writes the type and never the message."""
        from unittest import mock
        import io
        from test_cli import MARK, run_boundary
        with mock.patch.object(contained, "check_argv", side_effect=AttributeError(MARK)), \
                mock.patch.object(contained.sys, "stdin", io.StringIO("[]")):
            got = run_boundary(contained.main, ["check"], contained.FAULT_LINE)
        self.assertEqual(got, (2, '{"error": "internal error"}\n', "internal error: AttributeError\n"))
        with mock.patch.object(contained, "request_argv", side_effect=AttributeError(MARK)), \
                mock.patch.object(contained.sys, "stdin", io.StringIO("{}")):
            got = run_boundary(contained.main, ["argv"], contained.FAULT_LINE)
        self.assertEqual(got, (2, '{"ok": false, "reason": "internal error"}\n', "internal error: AttributeError\n"))


# ---------------------------------------------------------------- the argv command (tohum/29f, group contained)

MiB = 1024 * 1024
IMAGE_2 = "ghcr.io/org/node:20@sha256:" + "0f" * 32
COMPARED = ("ok", "network", "cap_drop", "cap_add", "privileged", "read_only", "uid", "memory_bytes", "mounts",
            "env_names", "image")


def request(**over) -> dict:
    """argv_baseline's request. The paths do not exist: the command must not look at them."""
    req = {"image": IMAGE, "cmd": ["python3", "-m", "pytest", "-q"], "uid": 1000,
           "worktree": "/nonexistent/snowball-t/work", "outdir": "/nonexistent/snowball-t/out",
           "artefacts": ["/nonexistent/snowball-t/deps"], "env": {"LANG": "C.UTF-8", "CI": "true"},
           "services": [], "operating": operating(container_mem_bytes=512 * MiB)}
    req.update(over)
    return req


def second_request() -> dict:
    return {"image": IMAGE_2, "cmd": ["node", "test.js"], "uid": 2001,
            "worktree": "/srv/b/tree", "outdir": "/srv/b/results",
            "artefacts": ["/srv/cache/z-last", "/srv/cache/a-first"], "env": {"NODE_ENV": "test"},
            "services": [], "operating": {"container_mem_bytes": {"value": 1024 * MiB, "band": [64 * MiB, 4096 * MiB]},
                                          "kos_wall_s": {"value": 60, "band": [1, 600]}}}


BASELINE_EXPECT = {"ok": True, "network": "none", "cap_drop": ["ALL"], "cap_add": [], "privileged": False,
                   "read_only": True, "uid": 1000, "memory_bytes": 512 * MiB,
                   "mounts": [["/nonexistent/snowball-t/deps", "ro"], ["/nonexistent/snowball-t/out", "rw"],
                              ["/nonexistent/snowball-t/work", "rw"]],
                   "env_names": ["CI", "LANG"], "image": IMAGE}
SECOND_EXPECT = {"ok": True, "network": "none", "cap_drop": ["ALL"], "cap_add": [], "privileged": False,
                 "read_only": True, "uid": 2001, "memory_bytes": 1024 * MiB,
                 "mounts": [["/srv/b/results", "rw"], ["/srv/b/tree", "rw"], ["/srv/cache/a-first", "ro"],
                            ["/srv/cache/z-last", "ro"]],
                 "env_names": ["NODE_ENV"], "image": IMAGE_2}
REFUSED = {"ok": False}


def as_json(obj) -> str:
    """tohum/29d: values compare as JSON (true is not 1, 1 is not 1.0, "1000" is not 1000)."""
    return json.dumps(obj, sort_keys=True)


class ArgvCommandTest(unittest.TestCase):
    def cli(self, stdin) -> tuple[int, dict]:
        if not isinstance(stdin, str):
            stdin = json.dumps(stdin)
        p = subprocess.run([sys.executable, "-m", "runner.contained", "argv"], cwd=REFEREE, input=stdin,
                           capture_output=True, text=True, timeout=60)
        self.assertNotIn("Traceback", p.stderr)
        lines = p.stdout.splitlines()
        self.assertTrue(lines, "no answer")
        return p.returncode, json.loads(lines[-1])

    def assertFields(self, line: dict, expect: dict) -> None:
        """The general runner's rule: only the fields expect names, each present, compared as JSON."""
        for key in expect:
            self.assertIn(key, line)
        self.assertEqual(as_json({k: line[k] for k in expect}), as_json(expect))

    def assertNotFields(self, line: dict, expect_not: dict) -> None:
        for key in expect_not:
            self.assertIn(key, line, "the changed vector must give the same fields")
        self.assertNotEqual(as_json({k: line[k] for k in expect_not}), as_json(expect_not))

    def test_argv_baseline(self):
        code, line = self.cli(request())
        self.assertEqual(code, 0, line)
        self.assertFields(line, BASELINE_EXPECT)
        argv = line["argv"]
        self.assertEqual(argv[:2], ["docker", "run"])
        for flag, value in (("--network", "none"), ("--cap-drop", "ALL"), ("--user", "1000:65534"),
                            ("--memory", str(512 * MiB))):
            self.assertEqual(argv[argv.index(flag) + 1], value, flag)
        self.assertIn("--read-only", argv)
        self.assertEqual(argv[-5:], [IMAGE, "python3", "-m", "pytest", "-q"])
        self.assertTrue(contained.check_argv(argv, layout="request")["ok"])
        self.assertFalse(contained.check_argv(argv)["ok"], "the run layout's check stays strict")
        self.assertFalse(os.path.exists("/nonexistent"), "nothing is made on disk")
        # changed: one field (the memory limit) changed must not give baseline's projection
        code, line = self.cli(request(operating=operating(container_mem_bytes=256 * MiB)))
        self.assertEqual(code, 0, line)
        self.assertNotFields(line, BASELINE_EXPECT)
        self.assertEqual(line["memory_bytes"], 256 * MiB)

    def test_argv_baseline_each_field_reaches_the_projection(self):
        for over, key, value in [(dict(uid=1001), "uid", 1001), (dict(env={"LANG": "C"}), "env_names", ["LANG"]),
                                 (dict(artefacts=[]), "mounts", [["/nonexistent/snowball-t/out", "rw"],
                                                                 ["/nonexistent/snowball-t/work", "rw"]]),
                                 (dict(image=IMAGE_2), "image", IMAGE_2)]:
            code, line = self.cli(request(**over))
            self.assertEqual(code, 0, (over, line))
            self.assertNotFields(line, BASELINE_EXPECT)
            self.assertEqual(as_json(line[key]), as_json(value), over)

    def test_argv_second_request(self):
        code, line = self.cli(second_request())
        self.assertEqual(code, 0, line)
        self.assertFields(line, SECOND_EXPECT)
        self.assertNotFields(line, BASELINE_EXPECT)  # a constant argv cannot satisfy both
        changed = second_request()
        changed["uid"] = 2002
        code, line = self.cli(changed)
        self.assertNotFields(line, SECOND_EXPECT)

    def refused(self, req: dict, fixed: dict) -> None:
        code, line = self.cli(req)
        self.assertEqual(code, 1, line)
        self.assertFields(line, REFUSED)
        self.assertIsInstance(line.get("reason"), str)
        self.assertNotIn("argv", line)
        code, line = self.cli(fixed)  # the changed vector: one field changed, must not be refused
        self.assertEqual(code, 0, (fixed, line))
        self.assertNotFields(line, REFUSED)

    def test_refuse_unpinned_image(self):
        for image in ("python:3.12-slim", "python:3.12-slim@sha256:" + "AB" * 32, "python@sha256:" + "ab" * 31,
                      "python@sha512:" + "ab" * 64, "python:3.12-slim@sha256:" + "ab" * 32 + " ", "@sha256:" + "ab" * 32):
            self.refused(request(image=image), request(image=IMAGE))

    def test_refuse_actions_env(self):
        for name in ("ACTIONS_RUNTIME_TOKEN", "ACTIONS_ID_TOKEN_REQUEST_URL", "actions_cache_url"):
            self.refused(request(env={"LANG": "C.UTF-8", name: "x"}),
                         request(env={"LANG": "C.UTF-8", "XACTIONS_" + name[8:]: "x"}))

    def test_refuse_docker_socket(self):
        base = request()
        for field, path, fixed in [
                ("worktree", "/var/run/docker.sock", "/var/run/dockerx"),
                ("outdir", "/var/run", "/var/runx"),
                ("outdir", "/run", "/srv/run"),
                ("worktree", "/var", "/srv/var"),
                ("worktree", "/home/u/.docker/run/docker.sock", "/home/u/.docker/run/docker.sockx"),
                ("worktree", "/srv/Docker.Sock/w", "/srv/Docker.Socks/w"),
                ("outdir", "/run/user/1000", "/srv/user/1000"),
                ("artefacts", ["/run/docker.sock"], ["/run/docker"]),
                ("artefacts", ["/opt/a", "/tmp/docker.sock"], ["/opt/a", "/tmp/docker.socket"])]:
            req, ok = dict(base), dict(base)
            req[field], ok[field] = path, fixed
            code, line = self.cli(req)
            self.assertEqual(code, 1, (field, path, line))
            self.assertIn("docker socket", line["reason"])
            self.refused(req, ok)

    def test_refuse_services(self):
        self.refused(request(services=["postgres:16"]), request(services=[]))
        self.refused(request(services=[{"image": IMAGE}]), request(services=[]))

    def test_refuse_missing_mem_limit(self):
        no_mem = {k: v for k, v in operating().items() if k != "container_mem_bytes"}
        self.refused(request(operating=no_mem), request(operating=operating()))
        self.refused(request(operating={}), request(operating={"container_mem_bytes": {"value": 64 * MiB,
                                                                                      "band": [MiB, 128 * MiB]}}))

    def test_other_refusals(self):
        for over in [dict(uid=0), dict(uid=-1), dict(env={"GITHUB_TOKEN": "x"}), dict(env={"1BAD": "x"}),
                     dict(operating=operating(container_mem_bytes=MiB)),
                     dict(operating={"container_mem_bytes": {"value": 10 ** 9, "band": [1, 10]}}),
                     dict(worktree="relative/work"), dict(outdir="/srv/o,readonly=false"), dict(outdir="/srv/a/../o"),
                     dict(worktree="/"), dict(outdir="/nonexistent/snowball-t/work"),
                     dict(artefacts=["/nonexistent/snowball-t/work/node_modules"]),
                     dict(artefacts=["/nonexistent"])]:
            code, line = self.cli(request(**over))
            self.assertEqual(code, 1, (over, line))
            self.assertFields(line, REFUSED)

    def test_unusable_input_is_exit_2(self):
        req = request()
        cases = ["not json", "", "[" * 200000, "[1]", json.dumps("x"), b"\xff".decode("latin-1")]
        for key, bad in [("image", 1), ("cmd", "python3"), ("cmd", []), ("cmd", ["a", 1]), ("uid", "1000"),
                         ("uid", True), ("uid", 1000.0), ("worktree", None), ("artefacts", "/a"), ("artefacts", [1]),
                         ("env", {"A": 1}), ("env", []), ("services", "postgres"), ("operating", [])]:
            cases.append(json.dumps(dict(req, **{key: bad})))
        for key in ("image", "cmd", "uid", "worktree", "outdir", "artefacts", "env", "services", "operating"):
            cases.append(json.dumps({k: v for k, v in req.items() if k != key}))
        for stdin in cases:
            code, line = self.cli(stdin)
            self.assertEqual(code, 2, (stdin[:200], line))
            self.assertFields(line, REFUSED)
            self.assertIsInstance(line.get("reason"), str)

    def test_projection_is_read_from_the_argv_not_the_request(self):
        """Whatever argv the builder hands over is what the line describes."""
        from unittest import mock
        import io
        weak = ["docker", "run", "--net", "bridge", "--network=host", "--privileged", "--cap-add", "SYS_ADMIN",
                "--cap-add=NET_ADMIN", "--cap-drop", "MKNOD", "-u", "0:0", "-m", "1g", "-e", "B=1", "--env", "A",
                "-v", "/var/run/docker.sock:/var/run/docker.sock", "-v", "/srv/x:/x:ro,z", "--tmpfs", "/tmp:size=1m",
                "--mount", "type=bind,source=/srv/y,target=/y,readonly", "--mount", "type=tmpfs,dst=/t",
                "--read-only=false", "img:latest", "sh"]
        out = io.StringIO()
        with mock.patch.object(contained, "request_argv", return_value=weak), \
                mock.patch.object(contained.sys, "stdin", io.StringIO(json.dumps(request()))), \
                mock.patch.object(contained.sys, "stdout", out):
            code = contained.main(["argv"])
        self.assertEqual(code, 0)
        line = json.loads(out.getvalue().splitlines()[-1])
        self.assertFields(line, {"ok": True, "network": "host", "cap_drop": ["MKNOD"],
                                 "cap_add": ["NET_ADMIN", "SYS_ADMIN"], "privileged": True, "read_only": False,
                                 "uid": 0, "memory_bytes": 1024 ** 3,
                                 "mounts": [["/srv/x", "ro"], ["/srv/y", "ro"], ["/var/run/docker.sock", "rw"],
                                            ["tmpfs:/t", "rw"], ["tmpfs:/tmp", "rw"]],
                                 "env_names": ["A", "B"], "image": "img:latest"})
        self.assertEqual(line["argv"], weak)
        bare = contained.project_argv(["docker", "run", "img", "true"])
        self.assertFields(bare, {"network": "default", "uid": None, "memory_bytes": None, "read_only": False,
                                 "mounts": [], "env_names": []})


# ---------------------------------------------------------------- canary (test 21)

class CanaryTest(Base):
    def test_network_outside_write_and_host_secret_all_fail(self):
        outside = os.path.join(self.base, "outside")
        os.mkdir(outside)
        with open(os.path.join(outside, "keep.txt"), "w") as fh:
            fh.write("unchanged")
        artifacts = os.path.join(self.base, "artifacts")
        os.mkdir(artifacts)
        with open(os.path.join(artifacts, "dep.txt"), "w") as fh:
            fh.write("dependency")
        canary_name, canary = "SNOWBALL_CANARY_" + os.urandom(4).hex().upper(), os.urandom(16).hex()
        os.environ[canary_name] = canary
        self.addCleanup(os.environ.pop, canary_name, None)
        listener = Listener()
        self.addCleanup(listener.close)
        before = snapshot(outside)
        fake = FakeDocker()
        result = contained.run(self.job(
            "connect", "127.0.0.1", str(listener.port),
            "write", os.path.join(outside, "keep.txt"), "overwritten",
            "write", os.path.join(outside, "new.txt"), "planted",
            "write", "../escape.txt", "planted",
            "write", "/in/dep.txt", "overwritten",
            "env", "/out/env.json",
            "write", "/out/ok.txt", "inside", artifacts=artifacts), operating(), runner=fake, base=self.base)
        self.assertEqual(listener.accepted, 0)
        self.assertEqual(snapshot(outside), before)
        self.assertEqual(sorted(os.listdir(result["run_root"])), ["in", "out", "work"])
        with open(os.path.join(artifacts, "dep.txt")) as fh:
            self.assertEqual(fh.read(), "dependency")
        self.assertEqual(result["status"], "ok")
        # the secret reached neither the container nor docker's own process
        self.assertNotIn(canary_name, fake.calls[0]["env"])
        self.assertEqual(set(fake.calls[0]["env"]), {"PATH", "HOME"})
        for dirpath, _, files in os.walk(result["run_root"]):
            for name in files:
                with open(os.path.join(dirpath, name), "rb") as fh:
                    self.assertNotIn(canary.encode(), fh.read(), name)
        self.assertNotIn(canary.encode(), fake.calls[0]["stdout"])
        # the probe itself did run: its writes inside the container are there and hashed outside
        self.assertEqual(result["outputs"]["ok.txt"]["sha256"], sha(b"inside"))
        self.assertIn("out/ok.txt", result["paths_written"])
        steps = [json.loads(line) for line in fake.calls[0]["stdout"].decode().splitlines()]
        self.assertEqual([s["ok"] for s in steps], [False, False, False, False, False, True, True])

    def test_canary_catches_a_runner_without_the_flags(self):
        """The same probe under an argv without --network none / --read-only gets through: the canary can fail."""
        outside = os.path.join(self.base, "outside")
        os.mkdir(outside)
        listener = Listener()
        self.addCleanup(listener.close)
        root = contained.fresh_run_root(self.base)
        shutil.copy(PROBE, os.path.join(root, "work", "probe.py"))
        argv = contained.build_argv(IMAGE, ["python3", "/work/probe.py", "connect", "127.0.0.1", str(listener.port),
                                            "write", os.path.join(outside, "x.txt"), "planted"], root, operating())
        weak = [a for a in argv if a != "--read-only"]
        i = weak.index("--network")
        weak[i + 1] = "bridge"
        FakeDocker()(weak, {}, 30)
        self.assertEqual(listener.accepted, 1)
        self.assertTrue(os.path.exists(os.path.join(outside, "x.txt")))


# ---------------------------------------------------------------- the run

class RunTest(Base):
    def test_fresh_root_per_run(self):
        fake = FakeDocker()
        first = contained.run(self.job("write", "/work/left.txt", "first", "listdir", "/out", "/work/seen.json"),
                              operating(), runner=fake, base=self.base)
        second = contained.run(self.job("listdir", "/work", "/out/seen.json"), operating(), runner=fake,
                               base=self.base)
        self.assertNotEqual(first["run_root"], second["run_root"])
        with open(os.path.join(second["run_root"], "out", "seen.json")) as fh:
            self.assertEqual(json.load(fh), ["probe.py"])
        with open(os.path.join(first["run_root"], "work", "seen.json")) as fh:
            self.assertEqual(json.load(fh), [])
        self.assertTrue(os.path.exists(os.path.join(first["run_root"], "work", "left.txt")))
        self.assertEqual(oct(os.stat(first["run_root"]).st_mode & 0o777), "0o700")
        for r in (first, second):
            self.assertTrue(contained.check_argv(r["argv"])["ok"])
            self.assertIn(r["run_root"] + "/work,dst=/work", " ".join(r["argv"]))

    def test_outputs_hashed_outside_without_following(self):
        target = os.path.join(self.base, "host-file")
        with open(target, "wb") as fh:
            fh.write(b"host secret file")
        result = contained.run(self.job("write", "/out/a/data.txt", "x", "write", "/out/data.txt", "payload",
                                        "symlink", target, "/out/link", "mkfifo", "/out/fifo",
                                        "write", "/work/new.txt", "w"), operating(), runner=FakeDocker(),
                               base=self.base)
        out = result["outputs"]
        self.assertEqual(out["data.txt"], {"type": "file", "sha256": sha(b"payload"), "size": 7})
        self.assertEqual(out["link"], {"type": "symlink", "target": target})
        self.assertEqual(out["fifo"]["type"], "other")
        self.assertNotIn("a/data.txt", out)  # the probe could not create a/ (no mkdir step): nothing invented
        self.assertNotIn(sha(b"host secret file"), json.dumps(out))
        self.assertEqual(result["paths_written"], ["out/data.txt", "out/fifo", "out/link", "work/new.txt"])
        expected = hashlib.sha256(json.dumps(out, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        self.assertEqual(result["outputs_sha256"], expected)

    def test_unreadable_output_is_not_valid(self):
        if os.geteuid() == 0:
            self.skipTest("root reads mode 000 files")

        def lock(argv):
            root = argv[argv.index("--mount") + 1].split("src=")[1].split(",")[0][: -len("/work")]
            p = os.path.join(root, "out", "locked")
            with open(p, "w") as fh:
                fh.write("x")
            os.chmod(p, 0)

        result = contained.run(self.job(), operating(), runner=FixedRunner(0, action=lock), base=self.base)
        self.assertEqual(result["status"], "unreadable_output")
        self.assertFalse(result["valid"])

        def lock_dir(argv):  # a directory the host can list but not enter, and one it cannot list
            root = argv[argv.index("--mount") + 1].split("src=")[1].split(",")[0][: -len("/work")]
            for name, mode in (("noexec", 0o444), ("noread", 0o311)):
                d = os.path.join(root, "out", name)
                os.mkdir(d)
                with open(os.path.join(d, "f"), "w") as fh:
                    fh.write("x")
                os.chmod(d, mode)
                self.addCleanup(os.chmod, d, 0o755)

        result = contained.run(self.job(), operating(), runner=FixedRunner(0, action=lock_dir), base=self.base)
        self.assertEqual(result["status"], "unreadable_output")
        self.assertTrue(result["outputs"]["noexec/f"]["unreadable"])
        self.assertTrue(result["outputs"]["noread"]["unreadable"])

    def test_limits(self):
        r = contained.run(self.job("write", "/out/o.txt", "x" * 10), operating(output_bytes=10), runner=FakeDocker(),
                          base=self.base)
        self.assertEqual(r["status"], "ok")
        r = contained.run(self.job("write", "/out/o.txt", "x" * 11), operating(output_bytes=10), runner=FakeDocker(),
                          base=self.base)
        self.assertEqual(r["status"], "limit_hit:output_bytes")
        self.assertFalse(r["valid"])
        size = os.path.getsize(os.path.join(self.tree, "probe.py"))
        never = FixedRunner(0)
        r = contained.run(self.job(), operating(worktree_bytes=size - 1), runner=never, base=self.base)
        self.assertEqual((r["status"], never.calls), ("limit_hit:worktree_bytes", []))
        r = contained.run(self.job(), operating(worktree_bytes=size), runner=FixedRunner(0), base=self.base)
        self.assertEqual(r["status"], "ok")
        r = contained.run(self.job("write", "/work/grow.txt", "x"), operating(worktree_bytes=size), runner=FakeDocker(),
                          base=self.base)
        self.assertEqual(r["status"], "limit_hit:worktree_bytes")
        fake = FakeDocker()
        r = contained.run(self.job("sleep", "20"), operating(kos_wall_s=1), runner=fake, base=self.base)
        self.assertEqual((r["status"], r["timed_out"], r["valid"]), ("limit_hit:kos_wall_s", True, False))
        self.assertTrue(fake.calls[0]["killed"])
        zero_min = {k: {"value": v["value"], "band": [0, v["band"][1]]} for k, v in operating().items()}
        self.assertEqual(contained.run(self.job(), zero_min, runner=FixedRunner(0), base=self.base)["status"], "ok")
        for bad in ({}, operating(kos_wall_s=0), {k: v for k, v in operating().items() if k != "output_bytes"},
                    dict(operating(), output_bytes={"value": 5, "band": [6, 9]}),
                    dict(operating(), output_bytes={"value": 5, "band": [-1, 9]}),
                    dict(operating(), output_bytes={"value": 5})):
            with self.assertRaises(contained.ContainmentError):
                contained.run(self.job(), bad, runner=FixedRunner(0), base=self.base)

    def test_docker_failure_and_changed_input(self):
        r = contained.run(self.job(), operating(), runner=FixedRunner(125), base=self.base)
        self.assertEqual((r["status"], r["valid"]), ("runner_fault", False))
        r = contained.run(self.job(), operating(), runner=FixedRunner(1), base=self.base)
        self.assertEqual((r["status"], r["valid"], r["exit"]), ("ok", True, 1))
        artifacts = os.path.join(self.base, "artifacts")
        os.mkdir(artifacts)
        with open(os.path.join(artifacts, "dep.txt"), "w") as fh:
            fh.write("dependency")

        def tamper(argv):  # a runner whose read-only mount did not hold
            src = [a for a in argv if a.endswith("dst=/in,readonly")][0].split("src=")[1].split(",")[0]
            with open(os.path.join(src, "dep.txt"), "w") as fh:
                fh.write("changed")

        r = contained.run(self.job(artifacts=artifacts), operating(), runner=FixedRunner(0, action=tamper),
                          base=self.base)
        self.assertEqual((r["status"], r["valid"]), ("breach:in_changed", False))

    def test_mount_sources_must_be_real_directories(self):
        root = contained.fresh_run_root(self.base)
        contained._sources_real(root, True)
        os.rmdir(os.path.join(root, "out"))
        os.symlink("/", os.path.join(root, "out"))
        with self.assertRaises(contained.ContainmentError):
            contained._sources_real(root, True)

    def test_docker_runner_kills_container_by_name_on_timeout(self):
        calls = []

        class Proc:
            def __init__(self):
                self.n = 0
                self.returncode = None

            def communicate(self, timeout=None):
                self.n += 1
                if self.n == 1:
                    raise subprocess.TimeoutExpired("docker", timeout)
                return b"o", b"e"

        class Sub:
            PIPE = DEVNULL = None
            TimeoutExpired = subprocess.TimeoutExpired

            def Popen(self, argv, **kw):
                calls.append(("popen", argv, kw["env"]))
                return Proc()

            def run(self, argv, **kw):
                calls.append(("run", argv, kw["env"]))

        real = contained.subprocess
        contained.subprocess = Sub()
        try:
            argv = good_argv()
            res = contained.docker_runner(argv, {"PATH": "/bin"}, 5)
        finally:
            contained.subprocess = real
        self.assertTrue(res.timed_out)
        self.assertEqual(calls[1], ("run", ["docker", "kill", "snowball-" + "0" * 32], {"PATH": "/bin"}))


if __name__ == "__main__":
    unittest.main()
