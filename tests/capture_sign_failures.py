"""Capture of ``fixtures/sigstore-sign-failures.json``: what real ``sigstore sign`` prints and exits when a party it
needs does not answer (tests only; needs a virtual environment's python with ``sigstore`` installed, given as the
first argument, and the network once, for Sigstore's public trust configuration).

Four cases, each one run of ``<python> -m sigstore ... sign --rekor-version 1 --bundle <b> <file>``
(``loop.sign.sign_argv``'s form) as a GitHub Actions job would run it (``GITHUB_ACTIONS``, an ambient token URL),
with standard output and standard error in one pipe, as ``loop.program.run`` reads them:

- ``oidc_refused``: the ambient token URL refuses the connection;
- ``tuf_unreachable``: every connection is refused (a proxy on a closed port) with an empty home, so the trust
  root cannot be refreshed;
- ``fulcio_500``: the token is served by a local stand-in and the certificate authority answers 500;
- ``fulcio_refused``: the token is served and the certificate authority refuses the connection.

The last two pass ``--trust-config`` with the public production configuration whose service URLs are rewritten to
``127.0.0.1``: no public service gets a request with the stand-in's token (it is unsigned). No case reaches Rekor:
a failure there is not captured. Each case keeps ``{mode, exit, bundle_written, output}``. Run from ``referee/``:
``python tests/capture_sign_failures.py /path/to/venv/bin/python > tests/fixtures/sigstore-sign-failures.json``.
"""

import base64
import http.server
import json
import os
import subprocess
import sys
import tempfile
import threading
import time

CLOSED = "http://127.0.0.1:9"
TRUST = ("import json, sys\nfrom sigstore.models import ClientTrustConfig\n"
         "sys.stdout.write(ClientTrustConfig.production()._inner.to_json())\n")


def _b64(doc: dict) -> str:
    return base64.urlsafe_b64encode(json.dumps(doc).encode()).rstrip(b"=").decode()


def token() -> str:
    now = int(time.time())
    claims = {"iss": "https://token.actions.githubusercontent.com", "aud": "sigstore", "iat": now, "nbf": now - 5,
              "exp": now + 600, "sub": "repo:acme/referee:ref:refs/heads/main"}
    return ".".join([_b64({"alg": "none", "typ": "JWT"}), _b64(claims), "c2ln"])


class StandIn(http.server.BaseHTTPRequestHandler):
    """GET: the ambient token; POST (the certificate request): 500."""

    def log_message(self, *args):
        pass

    def _send(self, code: int, body: bytes) -> None:
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self._send(200, json.dumps({"value": token()}).encode())

    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length", 0)))
        self._send(500, b'{"code": 13, "message": "internal"}')


def case(python: str, mode: str, trust: dict, port: int, tmp: str) -> dict:
    home = os.path.join(tmp, "home-" + mode)
    env = dict(os.environ, GITHUB_ACTIONS="true", ACTIONS_ID_TOKEN_REQUEST_TOKEN="x", HOME=home,
               ACTIONS_ID_TOKEN_REQUEST_URL="http://127.0.0.1:%d/token" % port)
    options = []
    if mode == "oidc_refused":
        env["ACTIONS_ID_TOKEN_REQUEST_URL"] = CLOSED + "/token"
    elif mode == "tuf_unreachable":
        env.update(HTTPS_PROXY=CLOSED, HTTP_PROXY=CLOSED)
    else:
        made = json.loads(json.dumps(trust))
        config = made["signingConfig"]
        for ca in config["caUrls"]:
            ca["url"] = CLOSED if mode == "fulcio_refused" else "http://127.0.0.1:%d" % port
        for other in config["rekorTlogUrls"] + config.get("tsaUrls", []):
            other["url"] = CLOSED
        path = os.path.join(tmp, "trust-%s.json" % mode)
        with open(path, "w") as fh:
            json.dump(made, fh)
        options = ["--trust-config", path]
    payload, bundle = os.path.join(tmp, "root"), os.path.join(tmp, "bundle-%s.json" % mode)
    with open(payload, "w") as fh:
        fh.write("x")
    done = subprocess.run([python, "-m", "sigstore", *options, "sign", "--rekor-version", "1", "--bundle", bundle,
                           payload], env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT, timeout=600)
    return {"mode": mode, "exit": done.returncode, "bundle_written": os.path.exists(bundle),
            "output": done.stdout.decode("utf-8", "replace")}


def main(python: str) -> None:
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), StandIn)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    with tempfile.TemporaryDirectory() as tmp:
        env = dict(os.environ, HOME=os.path.join(tmp, "home-trust"))
        trust = json.loads(subprocess.run([python, "-c", TRUST], env=env, check=True, capture_output=True).stdout)
        cases = [case(python, mode, trust, server.server_address[1], tmp)
                 for mode in ("oidc_refused", "tuf_unreachable", "fulcio_500", "fulcio_refused")]
    version = subprocess.run([python, "-m", "sigstore", "--version"], capture_output=True, text=True).stdout.strip()
    json.dump({"sigstore": version, "python": "%d.%d" % sys.version_info[:2], "cases": cases}, sys.stdout, indent=1,
              sort_keys=True)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main(sys.argv[1])
