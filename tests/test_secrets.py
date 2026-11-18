"""Test 38 (asama-0/09): a fake secret embedded in a diff, a ledger row and a prompt is caught; a match
invalidates the run and the prompt is not sent.

Every command case drives ``python -m gate.secrets`` from ``referee/`` in a subprocess, the way the
referee runs it; input goes through stdin or a pipe (``/dev/fd/N``), except for the seed's vector form
(class Vector, ``scan KIND FILE``), whose fixtures are files written to a temporary directory. No fake secret is written literally in this file: each is
assembled at run time from split parts, so the file itself (and the diff that carries it to the
rival's prompt) holds no secret-shaped text. Expected fingerprints are computed here with hashlib.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import unittest

REFEREE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BRAIN = os.path.dirname(REFEREE)
ALNUM = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
UPPER32 = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567"
KINDS = ("diff", "row", "prompt")


def body(seed: str, n: int, alphabet: str = ALNUM) -> str:
    """A deterministic random-looking string of ``n`` characters from ``alphabet``."""
    out, counter = [], 0
    while len(out) < n:
        for byte in hashlib.sha256(("%s/%d" % (seed, counter)).encode()).digest():
            out.append(alphabet[byte % len(alphabet)])
        counter += 1
    return "".join(out[:n])


def j(*parts: str) -> str:
    return "".join(parts)


# rule name -> a fake token of that shape (assembled, never literal)
FAKES = {
    "anthropic-key": j("sk-", "ant-", "oat01-", body("ant", 60, ALNUM + "_-")),
    "github-token": j("gh", "p_", body("ghp", 36)),
    "github-pat": j("github", "_pat_", body("pat", 82, ALNUM + "_")),
    "aws-access-key-id": j("AK", "IA", body("aws", 16, UPPER32)),
    "google-api-key": j("AI", "za", body("goog", 35, ALNUM + "_-")),
    "slack-token": j("xo", "xb-", body("slack", 24, ALNUM + "-")),
    "stripe-key": j("sk", "_live_", body("stripe", 24)),
    "npm-token": j("np", "m_", body("npm", 36)),
    "gitlab-token": j("gl", "pat-", body("gitlab", 20)),
    "openai-key": j("sk-", "proj-", body("oa1", 24), "T3Blbk", "FJ", body("oa2", 24)),
    "private-key": j("-----", "BEGIN RSA ", "PRIVATE KEY", "-----"),
    "jwt": j("ey", "J", body("jwt1", 20), ".ey", "J", body("jwt2", 20), ".", body("jwt3", 30)),
}
AWS_SECRET_VALUE = body("awssecret", 40, ALNUM + "/+")
ASSIGNED_VALUE = body("assigned", 32)
URL_PASSWORD = body("urlpw", 14)

# A broader shape than the scanner's own assignment rule: no template, placeholder or code exclusion,
# and a value cut only at whitespace or a quote. The scanner lets placeholders and code through on
# purpose; the seed keeps any such text out of the rival's prompt (29b:26), so the files this repo
# pushes must not hold it at all.
BROAD = [
    ("assignment", re.compile(
        r"(?i)(?:passw(?:or)?d|passphrase|pwd|secret|token|api[_\-]?key|access[_\-]?key|private[_\-]?key|"
        r"credential|auth)[A-Za-z0-9_\-]*[\"'`]?\]?[ \t]*(?:===?|!==?|:=|=>|[:=])[ \t]*[\"'`]?([^\s\"'`]{8,})")),
    ("url-userinfo", re.compile(r"://[^\s/@\"']+:[^\s/@\"']+@")),
    ("key-block", re.compile(r"BEGIN [A-Z ]*PRIVATE KEY")),
]
PUSHED = ("referee/gate/secrets.py", "referee/tests/test_secrets.py", "referee/ledger/chain.py",
          "referee/tests/test_chain.py", "snowball-tests.json")


def broad_hits(text: str) -> list:
    return [(n, name, m.group(0)[:40]) for n, line in enumerate(text.splitlines(), 1)
            for name, pattern in BROAD for m in pattern.finditer(line)]


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def run_secrets(args: list, stdin: bytes = b"", env_extra: dict | None = None):
    """Run ``python -m gate.secrets`` from referee/; each bytes value in ``args`` is served as a pipe."""
    fds, writers, argv = [], [], []
    for arg in args:
        if isinstance(arg, bytes):
            r, w = os.pipe()
            fds.append(r)
            writers.append((w, arg))
            argv.append("/dev/fd/%d" % r)
        else:
            argv.append(arg)

    def feed(fd: int, data: bytes) -> None:
        with os.fdopen(fd, "wb") as fh:
            try:
                fh.write(data)
            except BrokenPipeError:
                pass

    threads = [threading.Thread(target=feed, args=wd) for wd in writers]
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", **(env_extra or {}))
    proc = subprocess.Popen([sys.executable, "-m", "gate.secrets", *argv], cwd=REFEREE, env=env,
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            pass_fds=fds)
    for fd in fds:
        os.close(fd)
    for t in threads:
        t.start()
    out, err = proc.communicate(stdin, timeout=60)
    for t in threads:
        t.join()
    lines = out.decode().splitlines()
    result = json.loads(lines[0]) if len(lines) == 1 else None
    return proc.returncode, result, out + err


def scan(kind: str, text: str, **kw):
    return run_secrets(["scan", "--kind", kind], stdin=text.encode("utf-8"), **kw)


def diff_with(line: str, sign: str = "+", path: str = "app/config.py") -> str:
    return "\n".join([
        "diff --git a/%s b/%s" % (path, path),
        "index 1111111..2222222 100644",
        "--- a/%s" % path,
        "+++ b/%s" % path,
        "@@ -1,3 +1,4 @@",
        " import os",
        "%s%s" % (sign, line),
        " DEBUG = False",
        "",
    ])


def row_with(text: str) -> str:
    row = {"row_id": "f1", "ts": "2026-10-29T00:00:00Z", "part": "founder", "kind": "decision",
           "payload": {"summary": text, "refs": []}, "derivation": "llm_inference", "trust": "inferred",
           "snapshot_id": "s0", "evidence_refs": [], "prev_hash": "0" * 64, "row_hash": sha("x")}
    return json.dumps(row, separators=(",", ":"))


def prompt_with(text: str) -> str:
    return "You review a diff.\n\nContext:\n%s\n\nAnswer with a verdict.\n" % text


SENDER = ("import sys; data = sys.stdin.read(); "
          "sys.stdout.write('SENDER-RAN bytes=%d\\n' % len(data.encode('utf-8')))")


class Asserts:
    """The scan assertions the test classes share: caught by rule and fingerprint, or clean."""

    def assert_caught(self, kind: str, text: str, rule: str, value: str, line: int | None = None):
        code, result, raw = scan(kind, text)
        self.assertEqual(code, 1, raw)
        self.assertFalse(result["clean"])
        self.assertFalse(result["run_valid"])
        self.assertEqual(result["kind"], kind)
        hits = [m for m in result["matches"] if m["rule"] == rule]
        self.assertTrue(hits, "%s not reported for %s: %s" % (rule, kind, result))
        self.assertIn(sha(value), {m["sha256"] for m in hits})
        if line is not None:
            self.assertIn(line, {m["line"] for m in hits})
        self.assertNotIn(value.encode(), raw, "the secret value leaked into the output")
        return result

    def assert_all_caught(self, cases: list, rule: str = "secret-assignment"):
        """One scan per kind holding every case on its own line (one row per line for rows); each value
        must be reported under ``rule`` by its own fingerprint and none may leak into the output."""
        texts = [text for text, _ in cases]
        for kind, wrapped in (("prompt", prompt_with("\n\n".join(texts))),
                              ("row", "\n".join(row_with(text) for text in texts)),
                              ("diff", diff_with("\n+".join(texts)))):
            code, result, raw = scan(kind, wrapped)
            self.assertEqual(code, 1, raw)
            found = {m["sha256"] for m in result["matches"] if m["rule"] == rule}
            for text, value in cases:
                with self.subTest(text=text, kind=kind):
                    self.assertIn(sha(value), found)
                    self.assertNotIn(value.encode(), raw)

    def assert_clean(self, kind: str, text: str):
        code, result, raw = scan(kind, text)
        self.assertEqual(code, 0, raw)
        self.assertEqual(result, {"clean": True, "kind": kind, "run_valid": True, "matches": []})


class Detection(Asserts, unittest.TestCase):
    def test_every_rule_in_diff_row_and_prompt(self):
        for rule, token in FAKES.items():
            with self.subTest(rule=rule, kind="diff"):
                self.assert_caught("diff", diff_with('KEY = "%s"' % token), rule, token, line=7)
            with self.subTest(rule=rule, kind="row"):
                self.assert_caught("row", row_with("found %s in config" % token), rule, token, line=1)
            with self.subTest(rule=rule, kind="prompt"):
                self.assert_caught("prompt", prompt_with("value: %s" % token), rule, token, line=4)

    def test_token_glued_to_word_characters_is_caught(self):
        """A token right after or before "_", a letter or a digit has no word boundary; it still leaks.

        Rejection of 1c83fb7 (repro f1a0971b4ed0529f): x_ plus a GitHub token was reported clean.
        """
        glued = [("x_", ""), ("A", ""), ("9", ""), ("", "_x"), ("", "Z"), ("", "7"), ("see_x_", "_end")]
        for rule, token in FAKES.items():
            for before, after in glued:
                with self.subTest(rule=rule, before=before, after=after):
                    text = j(before, token, after)
                    for kind, wrapped in (("prompt", prompt_with("see %s" % text)), ("row", row_with(text)),
                                          ("diff", diff_with('KEY = "%s"' % text))):
                        code, result, raw = scan(kind, wrapped)
                        self.assertEqual(code, 1, raw)
                        self.assertIn(rule, {m["rule"] for m in result["matches"]}, (kind, result))
                        self.assertNotIn(token.encode(), raw)
        url = j("_postgres://admin:", URL_PASSWORD, "@db.internal/app")
        code, result, raw = scan("prompt", prompt_with(url))
        self.assertIn("url-credentials", {m["rule"] for m in result["matches"]}, raw)
        aws = "aws_secret_access_key = %sQ" % AWS_SECRET_VALUE
        code, result, raw = scan("prompt", prompt_with(aws))
        self.assertIn("aws-secret-key", {m["rule"] for m in result["matches"]}, raw)

    def test_aws_secret_assignment_url_credentials_and_quoted_assignment(self):
        line = "aws_secret_access_key = %s" % AWS_SECRET_VALUE
        code, result, raw = scan("diff", diff_with(line))
        self.assertEqual(code, 1, raw)
        self.assertIn("aws-secret-key", {m["rule"] for m in result["matches"]})
        self.assertNotIn(AWS_SECRET_VALUE.encode(), raw)

        url = j("postgres://admin:", URL_PASSWORD, "@db.internal:5432/app")
        code, result, raw = scan("prompt", prompt_with(url))
        self.assertEqual(code, 1, raw)
        self.assertIn("url-credentials", {m["rule"] for m in result["matches"]})
        self.assertNotIn(URL_PASSWORD.encode(), raw)

        self.assert_caught("diff", diff_with('client_secret = "%s"' % ASSIGNED_VALUE), "secret-assignment",
                           ASSIGNED_VALUE, line=7)
        # no upper length cap: a long random value is still a secret
        long_value = body("assigned-long", 300)
        self.assert_caught("prompt", prompt_with('client_secret = "%s"' % long_value), "secret-assignment",
                           long_value)

    def test_bare_and_weak_assigned_values_are_caught(self):
        """A value after a secret-named key leaks whether it is quoted, bare, random or weak.

        Rejection of 99278a5 (the rival's verdict was withheld for holding a bare assignment): the
        assignment rule only took quoted, random-looking values, so an unquoted one scanned clean. In a
        JSON row the quotes around a value are escaped; they are decoded before the scan.
        """
        pw, tok, sec = j("pass", "word"), j("to", "ken"), j("sec", "ret")
        weak = j("hunter", "22")
        random_value = body("bare", 20)
        cases = [
            ("DB_%s=%s" % (pw.upper(), random_value), random_value),
            ("DB_%s=%s" % (pw.upper(), weak), weak),
            ("x_%s: %s" % (tok, random_value), random_value),
            ('%s = "%s"' % (pw, weak), weak),
            ('{"client_%s": "%s"}' % (sec, weak), weak),
            ("export API_%s=%s;" % (tok.upper(), random_value), random_value),
            ("the %s is %s=%s." % (pw, pw, weak), weak),
            ("%s := `%s`" % (tok, weak), weak),
        ]
        for text, value in cases:
            for kind, wrapped in (("prompt", prompt_with(text)), ("row", row_with(text)),
                                  ("diff", diff_with(text))):
                with self.subTest(text=text, kind=kind):
                    self.assert_caught(kind, wrapped, "secret-assignment", value)

    def test_only_a_whole_template_is_skipped(self):
        """Rejection of 6e29850 (refutation fff7b2af3d2f6053): a value that started with $, <, { or %,
        or held "(", was taken for a template, so a real password beginning with a dollar sign scanned
        clean. Now only a value that is a template as a whole is skipped; a quoted value may hold spaces.
        """
        pw, tok, sec = j("pass", "word"), j("to", "ken"), j("sec", "ret")
        values = [j("$uper", "S3cretVal9"), j("<b>", "Secret99"), j("{x}", "Secret99"), j("%", "Secret99x"),
                  j("f(x)", "Secret9"), j("abc${X}", "def99"), j("Correct.", "Horse9"), j("Correct.", "Horse"),
                  j("correct horse ", "battery staple")]
        for value in values:
            for text in ('%s="%s"' % (pw, value), "%s: '%s'" % (sec, value), '{"client_%s": "%s"}' % (sec, value)):
                for kind, wrapped in (("prompt", prompt_with(text)), ("row", row_with(text)),
                                      ("diff", diff_with(text))):
                    with self.subTest(text=text, kind=kind):
                        self.assert_caught(kind, wrapped, "secret-assignment", value)
        # unquoted: a dollar sign before a lower-case or mixed name is not an environment variable
        bare = j("$uper", "S3cretVal9")
        self.assert_caught("prompt", prompt_with("%s=%s" % (tok, bare)), "secret-assignment", bare)

    def test_value_runs_to_whitespace_not_to_punctuation(self):
        """Rejection of 8265299 (refutation 8d96fe1aafd87a0e): an unquoted value was cut at the first
        , ; ( ) [ ] { }, so a key followed by ab;cd;ef;gh;ij scanned clean. Now an unquoted value runs to
        the first whitespace outside brackets; only one trailing , ; . : and unmatched closers are syntax.
        """
        pw, tok = j("pass", "word"), j("to", "ken")
        values = [j("ab;cd", ";ef;gh;ij"), j("ab,cd", ",ef,gh"), j("Xy7(k9", "!pQ)"), j("ab[cd]", "ef9"),
                  j("ab{cd}", "ef9"), j("ab)cd", "efgh"), j("p@ss;", "w0rd;x")]
        forms = ("%s=%%s" % pw, "%s: %%s" % tok, "export DB_%s=%%s;" % pw.upper(), "f(%s=%%s)" % pw,
                 "{%s: %%s}," % tok)
        # every case has its own value, so one line's match cannot stand in for another's
        cases = [(form % (value + str(n)), value + str(n)) for value in values for n, form in enumerate(forms)]
        self.assert_all_caught(cases)
        # the rival's reproducer, alone, as the referee ran it
        self.assert_caught("prompt", "%s=%s\n" % (pw, values[0]), "secret-assignment", values[0])

    def test_caller_closer_and_bracketed_literals_still_report_their_value(self):
        """Own defects f173 and f195 (false positives on the referee's own code) narrowed two readings; what
        a secret still looks like under them is caught. A closer that ends the value leaves the value before
        it; a closer followed by a letter, a digit or other punctuation stays part of the value; a literal
        reports its long item by that item's own fingerprint, at any depth, glued strings as one item, and
        on a line where it does not close; a literal followed by more value is read whole."""
        pw, tok, sec, keys = j("pass", "word"), j("to", "ken"), j("sec", "ret"), j("signing", "_keys")

        def value(n: int) -> str:
            return body("literal%d" % n, 12)

        cases = [
            ("login(%s=%s).send()" % (pw, value(1)), value(1)),
            ("f(%s=%s), g()" % (tok, value(2)), value(2)),
            ("%s=%s" % (pw, j("ab)cd", "!efgh")), j("ab)cd", "!efgh")),
            ("%s=%s" % (pw, j("ab)9", "cdefg")), j("ab)9", "cdefg")),
            ('%s = ("abc", "%s")' % (sec, value(3)), value(3)),
            ("%s = [abc, %s]" % (tok, value(4)), value(4)),
            ('%s = {"db": {"main": "%s"}}' % (sec, value(5)), value(5)),
            ('%s = ("%s" "%s")' % (pw, "hunter", "22abc"), "hunter 22abc"),
            ('%s = ("abc")"%s"' % (pw, value(7)), value(7)),
            # read as a whole template once its quotes were removed, this one was skipped before
            ('%s = {"%s"}' % (pw, value(8)), value(8)),
            # a nested group that is not its whole item is no literal: the item is read whole
            ("%s = [(abc) %s]" % (tok, value(10)), "(abc) " + value(10)),
            ('%s = [1, ("abc")"%s"]' % (sec, value(11)), value(11)),
            ('%s = [("abc")"de" %s]' % (pw, value(12)), "(abc)de " + value(12)),
            ('%s = ("abc", "def").%s()' % (pw, j("jo", "in")), j("(abc, def).", "join()")),
            ("%s = (abc)%s" % (tok, "defgh"), "(abc)defgh"),
        ]
        self.assert_all_caught(cases)
        rows = "\n".join(row_with(text) for text, _ in cases).encode()
        code, result, raw = run_secrets(["scan", "row", rows])
        self.assertEqual((code, result), (1, {"clean": False, "lines": list(range(1, len(cases) + 1))}), raw)
        # a literal that does not close on its line: the item is the value in a diff and a prompt; in a
        # row's JSON text the line goes on past the string, so the row is checked by its line
        unclosed = '%s = ["abc", %s' % (keys, value(6))
        self.assert_caught("diff", diff_with(unclosed), "secret-assignment", value(6), line=7)
        self.assert_caught("prompt", prompt_with(unclosed), "secret-assignment", value(6), line=4)
        code, result, raw = scan("row", row_with(unclosed))
        self.assertEqual((code, {m["line"] for m in result["matches"]}), (1, {1}), raw)
        self.assertEqual(run_secrets(["scan", "row", row_with(unclosed).encode()])[:2],
                         (1, {"clean": False, "lines": [1]}))
        # nesting deeper than Python's recursion limit is judged too (no RecursionError, no crash)
        deep = "%s = %s%s%s" % (sec, "[" * 20000, value(9), "]" * 20000)
        self.assert_caught("prompt", prompt_with(deep), "secret-assignment", value(9), line=4)
        token = FAKES["github-token"]
        self.assert_caught("prompt", prompt_with('%s = ("a", "%s")' % (keys, token)), "github-token", token)

    def test_quoted_values_hold_escaped_quotes_glued_tails_and_no_close(self):
        pw, sec = j("pass", "word"), j("sec", "ret")
        cases = [
            ('%s="%s"' % (pw, j("ab\\", '"cdefghij')), j("ab\\", '"cdefghij')),
            ('%s="%s"%s' % (pw, "abc", "defghij"), "abcdefghij"),
            ('%s="%s' % (pw, j("hunter", "22a")), j("hunter", "22a")),
            ("%s = b'%s'" % (sec, j("hunter", "22b")), j("hunter", "22b")),
            ('%s = f"%s{x}"' % (sec, j("hunter", "22c")), j("hunter", "22c{x}")),
        ]
        self.assert_all_caught(cases)

    def test_names_code_and_example_values_are_caught(self):
        """Rejection of d02c924 (refutation e0cbb7117d7d11d4): an unquoted value that was a letters-only
        dotted or underscored name was skipped as code, so a passphrase spelled correct_horse_battery
        scanned clean. The class is every value exclusion a real secret can also be: names, dotted names,
        calls, subscripts, placeholder words, one repeated character, and the quoted part glued after an
        unquoted one. None of them is skipped any more; only whole templates and NON_VALUES are."""
        pw, tok, sec, key = j("pass", "word"), j("to", "ken"), j("sec", "ret"), j("api", "_key")
        cases = [
            ("%s=%s" % (pw, j("correct_horse", "_battery")), j("correct_horse", "_battery")),
            ("%s=%s" % (pw, j("correct.horse", ".staple")), j("correct.horse", ".staple")),
            ("%s = %s" % (sec, j("CorrectHorse", "Battery")), j("CorrectHorse", "Battery")),
            ("%s = %s" % (tok, j("self.", tok)), j("self.", tok)),
            ("%s = %s" % (pw, j("request.", "form")), j("request.", "form")),
            ("%s = %s" % (sec, j(sec, "_value")), j(sec, "_value")),
            ("%s = %s" % (sec, j("SECRET", "_KEY")), j("SECRET", "_KEY")),
            ("%s = get_%s(request)" % (tok, tok), j("get_", tok, "(request)")),
            ("%s=%s" % (pw, j("abc(", "defgh)")), j("abc(", "defgh)")),
            ('%s = os.environ["%s"]' % (key, key.upper()), j('os.environ[', key.upper(), ']')),
            ("%s = %s" % (tok, j("expected_", tok)), j("expected_", tok)),
            ("%s_name = %s" % (tok, j("change", "me")), j("change", "me")),
            ('%s = "%s"' % (pw, j("pass", "word1")), j("pass", "word1")),
            ("%s=%s" % (sec, j("exam", "ple1")), j("exam", "ple1")),
            ('%s = "%s"' % (tok, "a" * 24), "a" * 24),
            ("%s: %s" % (pw, "z" * 9), "z" * 9),
            ('%s=%s"%s"' % (pw, "abc", j("defg", "hij")), j("abcdefg", "hij")),
        ]
        self.assert_all_caught(cases)
        # the rival's reproducer, alone, as the referee ran it
        self.assert_caught("prompt", "%s=%s\n" % (pw, j("correct_horse", "_battery")), "secret-assignment",
                           j("correct_horse", "_battery"))
        # a URL password is reported whatever word it is, unless it is a whole template
        for word in (pw, j("change", "me"), "x" * 6):
            with self.subTest(url_password=word):
                code, result, raw = scan("prompt", prompt_with(j("https://user:", word, "@example.com/")))
                self.assertEqual(code, 1, raw)
                self.assertIn("url-credentials", {m["rule"] for m in result["matches"]})

    def test_every_assignment_form_is_caught(self):
        """Forms the old pattern missed: a subscripted key, a comparison, a type annotation, the Go
        string type, a command-line flag, an authorization scheme word, a keyword argument, a JSON array."""
        pw, tok, auth = j("pass", "word"), j("to", "ken"), j("Auth", "orization")

        def weak(n: int) -> str:  # one value per case, so no case is found by another's line
            return j("hunter", "22x", str(n))

        def opaque(n: int) -> str:
            return body("opaque%d" % n, 32)

        cases = [
            ('config["%s"] = "%s"' % (pw, weak(1)), weak(1)),
            ("os.environ['DB_%s'] = '%s'" % (pw.upper(), weak(2)), weak(2)),
            ('if %s == "%s":' % (pw, weak(3)), weak(3)),
            ("if (%s !== '%s') {" % (tok, weak(4)), weak(4)),
            ('%s: str = "%s"' % (pw, weak(5)), weak(5)),
            ('%s: Optional[str] = "%s"' % (pw, weak(6)), weak(6)),
            ('var %s string = "%s"' % (pw, weak(7)), weak(7)),
            ("mysql --%s %s db" % (pw, weak(8)), weak(8)),
            ("curl --oauth2-bearer-%s %s" % (tok, opaque(9)), opaque(9)),
            ("%s: Bearer %s" % (auth, opaque(10)), opaque(10)),
            ('{"%s": "Basic %s"}' % (auth, opaque(11)), opaque(11)),
            ("login(user, %s=%s)" % (pw, weak(12)), weak(12)),
            ('[{"%s": "%s"},{"user": "bob"}]' % (pw, weak(13)), weak(13)),
        ]
        self.assert_all_caught(cases)
        # a URL password of any length (the rule took 6 or more characters)
        for short in (j("ab", "c12"), "ab"):
            with self.subTest(url_password=short):
                code, result, raw = scan("prompt", prompt_with(j("postgres://admin:", short, "@db.internal/app")))
                self.assertEqual(code, 1, raw)
                self.assertIn("url-credentials", {m["rule"] for m in result["matches"]})

    def test_every_secret_named_key_is_caught(self):
        """Each rule of _secret_key on its own value: a part anywhere in a word (DB_PASS, DBPASS), a name
        word, a word ending in key, session id, words split at _ - . and camelCase, PLAIN_WORDS not hiding
        another word, and the R arrow and Dockerfile ENV forms."""
        def value(n: int) -> str:  # one random 12-character value per case, like Zq8xLm2Pv9Rt
            return body("named%d" % n, 12)

        keys = [j("DB_", "PASS"), j("db", "Pass"), j("DB", "PASS"), j("db.", "pass"), j("MYSQL_", "PWD"),
                j("user_", "pin"), j("OTP_", "SEED"), j("app_", "creds"), j("session", "_id"), j("SESSION", "ID"),
                j("STRIPE_", "KEY"), j("api", "Key"), j("master", "key"), j("X-Api", "-Key"), j("jwt.sec", "ret.key"),
                j("spring.datasource.pass", "word"), j("o", "auth_client"), j("COOK", "IE"), j("bypass_", "pass"),
                j("ş", "ifre"), j("par", "ola"), j("kenn", "wort"), j("signing_", "keys"), j("auth", "Token")]
        cases = [("%s=%s" % (key, value(n)), value(n)) for n, key in enumerate(keys)]
        cases += [
            ("%s <- '%s'" % (j("db_", "pass"), value(100)), value(100)),
            ("ENV %s %s" % (j("DB_", "PASS"), value(101)), value(101)),
            ("%s: %s" % (j("X-Api", "-Key"), value(102)), value(102)),
            ("--%s %s" % (j("db-", "pass"), value(103)), value(103)),
        ]
        self.assert_all_caught(cases)

    def test_split_and_encoded_tokens_are_caught(self):
        """A token split over two lines, base64-encoded or percent-encoded still leaks."""
        token = FAKES["github-token"]
        half = len(token) // 2
        split = "see %s\n    %s please" % (token[:half], token[half:])
        self.assert_caught("prompt", prompt_with(split), "github-token", token)
        code, result, raw = scan("diff", diff_with("x = '%s\\\n+%s'" % (token[:half], token[half:])))
        self.assertEqual(code, 1, raw)
        self.assertIn(sha(token), {m["sha256"] for m in result["matches"]})
        for name, encoded in (("base64", base64.b64encode(("t=" + token).encode()).decode()),
                              ("base64url", base64.urlsafe_b64encode(token.encode()).decode().rstrip("=")),
                              ("percent", "".join("%%%02X" % ord(c) for c in token))):
            for kind, wrapped in (("prompt", prompt_with("blob " + encoded)), ("row", row_with(encoded)),
                                  ("diff", diff_with("B = '%s'" % encoded))):
                with self.subTest(name=name, kind=kind):
                    self.assert_caught(kind, wrapped, "github-token", token)
        # a value on the line after its key (YAML), in a prompt and a diff
        pw, weak = j("pass", "word"), j("hunter", "22")
        self.assert_caught("prompt", prompt_with("db:\n  %s:\n    %s\n" % (pw, weak)), "secret-assignment", weak)
        self.assert_caught("diff", diff_with("%s:\n+  %s" % (pw, weak)), "secret-assignment", weak)

    def test_diff_reports_path_and_scans_removed_lines(self):
        token = FAKES["github-token"]
        result = self.assert_caught("diff", diff_with('T = "%s"' % token, sign="-", path="svc/old.py"),
                                    "github-token", token, line=7)
        self.assertEqual({m.get("path") for m in result["matches"]}, {"svc/old.py"})

    def test_hidden_spellings_are_caught(self):
        token = FAKES["github-token"]
        escaped = "".join("\\u%04x" % ord(c) for c in token)
        # JSON escapes in a row: the raw text has no token, the decoded string does
        code, result, raw = scan("row", '{"row_id":"f1","payload":{"summary":"%s"}}' % escaped)
        self.assertEqual(code, 1, raw)
        self.assertIn(sha(token), {m["sha256"] for m in result["matches"]})
        # zero-width space inside the token
        hidden = token[:10] + "\u200b" + token[10:]
        self.assert_caught("prompt", prompt_with(hidden), "github-token", token)
        # full-width letters fold to ASCII under NFKC
        wide = "".join(chr(ord(c) + 0xFEE0) if c.isalnum() else c for c in token)
        self.assert_caught("prompt", prompt_with(wide), "github-token", token)

    def test_invalid_utf8_around_a_secret_is_still_scanned(self):
        token = FAKES["aws-access-key-id"]
        data = b"\xff\xfe junk " + token.encode() + b" \xc3\x28\n"
        code, result, raw = run_secrets(["scan", "--kind", "prompt"], stdin=data)
        self.assertEqual(code, 1, raw)
        self.assertIn(sha(token), {m["sha256"] for m in result["matches"]})

    def test_file_argument(self):
        token = FAKES["npm-token"]
        code, result, raw = run_secrets(["scan", "--kind", "diff", diff_with(token).encode()])
        self.assertEqual(code, 1, raw)
        self.assertEqual(result["matches"][0]["rule"], "npm-token")

    def test_known_values_from_the_environment(self):
        value = body("referee-own-secret", 40)
        env = {"SB_TEST_KNOWN": value, "SB_TEST_SHORT": "abc"}
        code, result, raw = run_secrets(["scan", "--kind", "prompt", "--known-env", "SB_TEST_KNOWN",
                                         "--known-env", "SB_TEST_SHORT"],
                                        stdin=prompt_with("plain words %s abc" % value).encode(), env_extra=env)
        self.assertEqual(code, 1, raw)
        self.assertEqual({m["rule"] for m in result["matches"]}, {"known:SB_TEST_KNOWN"})
        self.assertNotIn(value.encode(), raw)
        # without naming the variable the plain value is not a pattern match
        code, result, raw = run_secrets(["scan", "--kind", "prompt"],
                                        stdin=prompt_with("plain words %s" % value).encode(), env_extra=env)
        self.assertEqual((code, result["matches"]), (0, []), raw)


class Clean(Asserts, unittest.TestCase):
    def test_one_changed_byte_is_no_longer_a_token(self):
        """The changed input of each fake (one character cut, or prefix broken) gives no match."""
        changed = {
            "github-token": FAKES["github-token"][:-1],
            "aws-access-key-id": FAKES["aws-access-key-id"][:-1],
            "google-api-key": FAKES["google-api-key"][:-1],
            "npm-token": FAKES["npm-token"][:-1],
            "stripe-key": FAKES["stripe-key"].replace("_live_", "_lime_"),
            "anthropic-key": FAKES["anthropic-key"].replace("sk-ant", "sk-and"),
            "private-key": FAKES["private-key"].replace("PRIVATE", "PUBLIC"),
        }
        for rule, text in changed.items():
            with self.subTest(rule=rule):
                self.assert_clean("prompt", prompt_with("value %s" % text))

    def test_templates_null_words_and_short_values(self):
        # key names are assembled too: a literal quoted value after a secret-named key is the shape the
        # seed keeps out of the rival's prompt, placeholder or not (see BROAD below)
        tok, pw, key, sec = j("to", "ken"), j("pass", "word"), j("api", "_key"), j("sec", "ret")
        lines = [
            '%s = "<placeholder>"' % pw,
            '%s = "${%s_FROM_ENV}"' % (sec, sec.upper()),
            "commit 632a84cc3e7e70741607457a4060e375caa0e3a4",
            "row_hash 3bae91580aca99362572e9f5f41b3e46c2bc0c29236f72e867faa5cd46ca603a",
            "id 123e4567-e89b-12d3-a456-426614174000",
            "-----BEGIN PUBLIC KEY-----",
            # whole templates, quoted or bare, also behind a scheme word and inside a URL
            "%s=${DB_%s}" % (pw, pw.upper()),
            "%s=$DB_%s" % (pw, pw.upper()),
            '%s: "{{ db_%s }}"' % (pw, pw),
            "%s = '%%(%s)s'" % (sec, sec),
            "%s=%%API_%s%%" % (tok, tok.upper()),
            '%s = "<your-api-%s>"' % (tok, tok),
            'headers = {"%s": f"Bearer {%s}"}' % (j("Auth", "orization"), tok),
            "%s = `Bearer ${%s}`" % (j("au", "th"), tok),
            j("url = 'https://user:", "${DB_%s}" % pw.upper(), "@example.com/'"),
            # NON_VALUES in any case, values under 8 characters, a key that is not secret-named
            "%s = None" % tok,
            "%s: null" % pw,
            "%s = Undefined" % sec,
            "%s = %s" % (tok, j("get", "(x)")),
            "%s = %s" % (pw, j("load", "(")),
            "if %s == %s:" % (tok, j("other", "s")),
            '%s = "%s"' % (key, "a" * 7),
            "the %s budget: unlimited" % tok,
            # consecutive hashes and base64 of plain words: no split or decoded token
            "3bae91580aca99362572e9f5f41b3e46c2bc0c29236f72e867faa5cd46ca603a",
            "640eae94a77d1a73c0676cf52e681cb3aa0593f607f6feab6ca9a43a8f094460",
            base64.b64encode(b"plain words, nothing to hide here").decode(),
            # a JSON row's closing quote ends a short value; the glued reading holds no more text
            '{"summary": "%s=abc"}' % pw,

            "the next line starts a word",
            "whatever comes next",
        ]
        self.assert_clean("diff", diff_with("\n+".join(lines)))
        self.assert_clean("prompt", prompt_with("\n".join(lines)))
        self.assert_clean("prompt", "")

    def test_caller_closers_literals_and_github_expressions_are_not_values(self):
        """Own defects f173 and f195: the referee's own lines were reported. A closer with no opener that
        closes the caller's bracket ends the value (json.dumps with its sort keyword and a .encode after it
        read on into the call's tail); a bracketed literal of short items is judged item by item, not as one
        long value; a GitHub expression that is a dotted name is a whole template. The stated boundaries
        are here too: short items of a literal, and the text after a closer that ends a value."""
        tok, pw, sec, keys = j("to", "ken"), j("pass", "word"), j("sec", "ret"), j("sort", "_keys")
        lines = [
            'request = json.dumps({"rows": planned["rows"]}, %s=True).encode("utf-8")' % keys,
            'line = json.dumps(record, %s=True).encode("utf-8") + b"\\n"' % keys,
            "f(%s=abc)" % tok,
            "if check(%s=None): pass" % pw,
            "go(%s=x)]" % tok,
            "%s: {value, band}" % j("anah", "tar"),
            '%s = ("abc", "def",' % j("ROW_", "KEYS"),
            '%s = ["abc", "defgh"]' % pw,
            "%s = {abc: {de: fgh}}" % sec,
            "%s = ()" % tok,
            "%s=ab).%s" % (pw, j("cdef", "ghij")),
            "%s: ${{ secrets.%s }}" % (j("CLAUDE_CODE_OAUTH_", "TOKEN"), j("CLAUDE_CODE_OAUTH_", "TOKEN")),
            "%s: ${{ steps.app.outputs.%s }}" % (j("WRITER_", "TOKEN"), tok),
            '"%s": "${{ secrets.%s }}",' % (j("private", "-key"), j("WRITER_APP_PRIVATE_", "KEY")),
            # a template as written is not a literal: JSX attributes and format fields (the target's lines)
            "<input onKeyDown={handleKeyDown} />",
            'raise E(f"%s_missing:{self.purpose}")' % j("hmac_", "key"),
            "%s = {{ %s }}" % (j("api", "Key"), j("config.api", "Key")),
        ]
        self.assert_clean("diff", diff_with("\n+".join(lines)))
        self.assert_clean("prompt", prompt_with("\n".join(lines)))
        # rows reach the scanner decoded (ledger.append calls match_lines, the seed's vector form)
        code, result, raw = run_secrets(["scan", "row", "\n".join(row_with(line) for line in lines).encode()])
        self.assertEqual((code, result), (0, {"clean": True, "lines": []}), raw)
        # only a whole GitHub expression is a template; a value around one or a non-name one is reported
        for text, value in (("%s: ${{ x }}%s" % (tok, "tail9999"), "${{ x }}tail9999"),
                            ("%s: ${{ a || b }}" % tok, "${{ a || b }}")):
            with self.subTest(text=text):
                code, result, raw = scan("prompt", prompt_with(text))
                self.assertEqual(code, 1, raw)
                self.assertIn(sha(value), {m["sha256"] for m in result["matches"]})

    def test_keys_that_are_not_secret_named(self):
        """The stated boundaries and exclusions of _secret_key: the bare word key alone, PLAIN_WORDS, a
        file name, a key none of whose words is secret-named, and a Python if-line ending in a colon
        (only a key that starts its line takes its value from the next line)."""
        def value(n: int) -> str:
            return body("plain%d" % n, 12)

        lines = ["%s=%s" % (key, value(n)) for n, key in enumerate(
            ["key", "KEY", "keys", "compass", "bypass", "author", "tokenizer", "monkey_name", "passenger",
             "DB_CONN", "LOGIN", "pinned", "keyboard"])]
        lines += [
            "sorted(rows, key=%s)" % value(50),
            "%s: %s" % (j("test_sec", "rets.py"), value(51)),
            "%s: %s" % (j("notes/to", "ken.md"), value(52)),
            "if word in %s:" % j("TO", "KENS"),
            "    continue",
        ]
        self.assert_clean("diff", diff_with("\n+".join(lines)))
        self.assert_clean("prompt", prompt_with("\n".join(lines)))

    def test_broad_shape_catches_what_the_scanner_lets_through(self):
        """BROAD is stricter than the scanner: placeholders after a secret-named key are flagged."""
        tok, pw = j("to", "ken"), j("pass", "word")
        for text in ('%s = "%s"' % (tok, "a" * 24), "%s = get_%s(request)" % (tok, tok), '%s: "<placeholder>"' % pw, "%s=%s" % (pw, "hunter22"),
                     j("https://user", ":%s@example.com/" % pw), j("-----BEGIN RSA ", "PRIVATE KEY-----")):
            with self.subTest(text=text):
                self.assertTrue(broad_hits(text))
        for text in ("row_hash: 3bae9158", "key = None", "-----BEGIN PUBLIC KEY-----"):
            with self.subTest(text=text):
                self.assertEqual(broad_hits(text), [])

    def test_pushed_files_hold_no_assignment_shaped_text(self):
        """No pushed file, nor any report, holds text the seed would keep out of the rival's prompt."""
        reports = os.path.join(BRAIN, "reports")
        paths = list(PUSHED) + ["reports/" + n for n in sorted(os.listdir(reports)) if n.endswith(".json")]
        for rel in paths:
            with self.subTest(path=rel):
                with open(os.path.join(BRAIN, rel), encoding="utf-8") as fh:
                    self.assertEqual(broad_hits(fh.read()), [])

    def test_the_real_ledger_and_this_push_are_clean(self):
        """Every ledger row from f59 on (the rows this scanner guards since code is no longer skipped)
        and the scanner's own files are clean. Rows before f59 were checked by the scanner of their day;
        four of them quote a referee reason code (a secret-named prefix, a colon, a word) that is now
        reported, and the chain keeps them as written. test_secrets.py holds fixtures assigned to
        secret-named keys by code, so it is checked by BROAD only."""
        with open(os.path.join(BRAIN, "founder-ledger.jsonl"), encoding="utf-8") as fh:
            rows = [line for line in fh.read().splitlines()
                    if int(json.loads(line)["row_id"].lstrip("f")) >= 59]
        self.assertTrue(rows)
        self.assert_clean("row", "\n".join(rows))
        for rel in ("referee/gate/secrets.py", "referee/ledger/chain.py", "snowball-tests.json"):
            with self.subTest(path=rel):
                with open(os.path.join(BRAIN, rel), encoding="utf-8") as fh:
                    self.assert_clean("prompt", fh.read())


class StatedRules(Asserts, unittest.TestCase):
    """Rules the module states that no case above pinned, each found by a kept mutant that survived
    (tests/mutants/secrets.json): a token prefix of each provider shape, an operator, a scheme word, a
    value reading, a key split, a clean boundary, a hidden spelling and the shape of a match."""

    def test_every_prefix_of_a_token_shape(self):
        """Each alternative a rule names is a token of its own (the GitHub prefixes gh[pousr]_, the AWS key
        id prefixes, Stripe's rk_ and test keys, a PGP private key block, the Slack webhook, a URL scheme
        holding + . - and the AWS secret key in any case)."""
        cases = [("github-token", j("gh", p, "_", body("gh" + p, 36))) for p in "ousr"]
        cases += [("aws-access-key-id", j(prefix, body("aws" + prefix, 16, UPPER32)))
                  for prefix in ("AS" + "IA", "AB" + "IA", "AC" + "CA", "A3" + "TX")]
        cases += [("stripe-key", j("rk", "_live_", body("rk", 24))), ("stripe-key", j("sk", "_test_", body("skt", 24))),
                  ("private-key", j("-----BEGIN PGP ", "PRIVATE KEY", " BLOCK-----")),
                  ("slack-webhook", j("hooks.slack", ".com/services/T", body("st", 9), "/B", body("sb", 9),
                                      "/", body("sw", 24))),
                  ("aws-secret-key", j("AWS_SECRET", "_ACCESS_KEY=", AWS_SECRET_VALUE)),
                  ("aws-secret-key", j("AwsSecret", "Key: ", AWS_SECRET_VALUE))]
        for scheme in ("git+ssh", "svn+ssh", "x-y.z"):
            cases.append(("url-credentials", j(scheme, "://user:", URL_PASSWORD, "@host.internal/repo")))
        for rule, text in cases:
            with self.subTest(rule=rule, text=text[:12]):
                code, result, raw = scan("prompt", prompt_with("see %s here" % text))
                self.assertEqual(code, 1, raw)
                self.assertIn(rule, {m["rule"] for m in result["matches"]}, raw)
                if rule not in ("aws-secret-key", "url-credentials"):
                    self.assertIn(sha(text), {m["sha256"] for m in result["matches"] if m["rule"] == rule})

    def test_operators_scheme_words_and_value_readings(self):
        """The fat arrow, the Bot scheme word, one trailing , ; . : only, a two-letter string prefix, only
        the first quoted part glued after an unquoted one, and a backslash escaping a single quote."""
        pw, sec, auth = j("pass", "word"), j("sec", "ret"), j("Auth", "orization")

        def value(n: int) -> str:
            return body("stated%d" % n, 12)

        cases = [
            ("'%s' => '%s'" % (pw, value(1)), value(1)),
            ("%s: Bot %s" % (auth, value(2)), value(2)),
            ("%s=%s;;" % (pw, value(3)), value(3) + ";"),
            ("%s = rb'%s'" % (sec, value(4)), value(4)),
            ('%s=abc"%s"hij"klmn"' % (pw, value(5)), j("abc", value(5), "hij")),
            ("%s = '\\' %s'" % (sec, value(6)), "\\' " + value(6)),
        ]
        self.assert_all_caught(cases)

    def test_stated_boundaries_are_clean(self):
        """A value of templates only is skipped however many it holds; ENV is the Dockerfile's only in
        upper case; camelCase and acronym humps split a key into words, so author in authorName or
        HTTPAuthorName is an ordinary word, not auth."""
        pw = j("pass", "word")
        value = body("boundary", 12)
        lines = [
            "%s=${DB_USER}${DB_%s}" % (pw, pw.upper()),
            "env %s %s" % (j("DB_", "PASS"), value),
            "%s = %s" % (j("author", "Name"), value),
            "%s: %s" % (j("HTTPAuthor", "Name"), value),
        ]
        self.assert_clean("diff", diff_with("\n+".join(lines)))
        self.assert_clean("prompt", prompt_with("\n".join(lines)))

    def test_escaped_folded_and_url_safe_base64_spellings(self):
        """A zero-width space written as a \\\\u escape (unescaped, then folded), a URL-safe base64 run that
        holds - or _, and base64 of a full-width token (decoded, then folded)."""
        token = FAKES["github-token"]
        self.assert_caught("prompt", prompt_with(token[:10] + "\\u200b" + token[10:]), "github-token", token)
        urlsafe = next(e for e in (base64.urlsafe_b64encode((pad + token).encode()).decode()
                                   for pad in ("", "t=", ">", "?>", "~", "~~", "~~~")) if "-" in e or "_" in e)
        self.assert_caught("prompt", prompt_with("blob " + urlsafe), "github-token", token)
        wide = "".join(chr(ord(c) + 0xFEE0) if c.isalnum() else c for c in token)
        self.assert_caught("prompt", prompt_with("blob " + base64.b64encode(wide.encode()).decode()),
                           "github-token", token)

    def test_match_shape_one_hit_per_line_and_joined_text(self):
        """A match holds rule, line and sha256 (and path in a diff) and nothing else; one value twice on a
        line is one match; a hit of two joined lines whose text one line holds whole is not the first
        line's."""
        token = FAKES["github-token"]
        code, result, raw = scan("prompt", prompt_with("%s and %s" % (token, token)))
        self.assertEqual(result["matches"], [{"rule": "github-token", "line": 4, "sha256": sha(token)}], raw)
        code, result, raw = scan("diff", diff_with('T = "%s"' % token))
        self.assertEqual(result["matches"], [{"rule": "github-token", "line": 7, "sha256": sha(token),
                                              "path": "app/config.py"}], raw)
        first = token + "Q"
        code, result, raw = scan("prompt", "%s\n%s%s\n" % (first, first, token))
        self.assertEqual({m["sha256"] for m in result["matches"] if m["line"] == 1}, {sha(first)}, raw)


class Send(unittest.TestCase):
    def test_clean_prompt_is_sent(self):
        prompt = prompt_with("nothing secret here")
        code, result, raw = run_secrets(["send", "--", sys.executable, "-c", SENDER], stdin=prompt.encode())
        self.assertEqual(code, 0, raw)
        self.assertEqual(result, {"clean": True, "run_valid": True, "sent": True, "sender_exit": 0, "matches": []})
        self.assertIn(b"SENDER-RAN bytes=%d" % len(prompt.encode()), raw)

    def test_clean_prompt_exits_0_and_carries_the_sender_exit(self):
        code, result, raw = run_secrets(["send", "--", sys.executable, "-c", SENDER + "; sys.exit(3)"],
                                        stdin=prompt_with("nothing secret here").encode())
        self.assertEqual((code, result["sent"], result["sender_exit"]), (0, True, 3), raw)

    def test_prompt_with_secret_is_not_sent_and_run_is_invalid(self):
        for rule in ("anthropic-key", "github-token", "private-key"):
            with self.subTest(rule=rule):
                prompt = prompt_with("leak %s" % FAKES[rule])
                code, result, raw = run_secrets(["send", "--", sys.executable, "-c", SENDER], stdin=prompt.encode())
                self.assertEqual(code, 1, raw)
                self.assertFalse(result["sent"])
                self.assertFalse(result["run_valid"])
                self.assertIsNone(result["sender_exit"])
                self.assertEqual({m["rule"] for m in result["matches"]}, {rule})
                self.assertNotIn(b"SENDER-RAN", raw)

    def test_known_env_value_blocks_send(self):
        value = body("oauth", 48)
        code, result, raw = run_secrets(["send", "--known-env", "SB_TEST_OAUTH", "--", sys.executable, "-c", SENDER],
                                        stdin=prompt_with(value).encode(), env_extra={"SB_TEST_OAUTH": value})
        self.assertEqual((code, result["sent"]), (1, False), raw)
        self.assertNotIn(b"SENDER-RAN", raw)


class Library(unittest.TestCase):
    """The in-process API the callers (llm.call, gate.check, ledger.append) use."""

    def setUp(self):
        sys.path.insert(0, REFEREE)
        self.addCleanup(sys.path.remove, REFEREE)
        from gate import secrets
        self.secrets = secrets

    def test_send_if_clean_never_calls_send_on_a_match(self):
        calls = []
        with self.assertRaises(self.secrets.SecretFound) as ctx:
            self.secrets.send_if_clean(prompt_with(FAKES["jwt"]), calls.append)
        self.assertEqual(calls, [])
        self.assertEqual(ctx.exception.matches[0]["rule"], "jwt")
        self.assertEqual(self.secrets.send_if_clean("hello", lambda p: p.upper()), "HELLO")

    def test_require_clean_and_bad_kind(self):
        self.secrets.require_clean(row_with("fine"), "row")
        with self.assertRaises(self.secrets.SecretFound):
            self.secrets.require_clean(row_with(FAKES["slack-token"]), "row")
        with self.assertRaises(self.secrets.ScanError):
            self.secrets.scan("x", "email")
        with self.assertRaises(self.secrets.ScanError):
            self.secrets.match_lines(b"x", "email")


UPPER_DIGITS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
AWS_ID = j("AK", "IA", "0189", body("vec-aws", 12, UPPER_DIGITS))  # holds 0 1 8 9: the base is [A-Z0-9]
NEAR_GH = j("gh", "q_", body("vec-ghq", 36))
NEAR_ID = j("AK", "IA", body("vec-near", 15, UPPER_DIGITS[:26]))


def run_vector(kind: str, data: bytes, stdin: bytes = b""):
    """Run the seed's vector form ``python -m gate.secrets scan KIND FILE`` from referee/ on a fixture
    written to a temporary directory; return the exit code, the last stdout line decoded and all output."""
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "input")
        with open(path, "wb") as fh:
            fh.write(data)
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
        proc = subprocess.run([sys.executable, "-m", "gate.secrets", "scan", kind, path], cwd=REFEREE, env=env,
                              input=stdin, capture_output=True, timeout=60)
    lines = proc.stdout.decode().splitlines()
    return proc.returncode, json.loads(lines[-1]) if lines else None, proc.stdout + proc.stderr


class Vector(unittest.TestCase):
    """The seed's vector interface (tohum/29f, secrets): each named case with its expected exit code and
    last-line fields, and a changed input (one byte or one field) that must not give the same result.
    Every output is checked to hold none of the fake values."""

    PLANTED = (FAKES["github-token"], AWS_ID, NEAR_GH, NEAR_ID)

    def check(self, kind: str, data: bytes, code: int, expect: dict, changed: bytes | None = None,
              changed_code: int | None = None, changed_expect: dict | None = None):
        """Like the seed's runner, only the fields ``expect`` names are compared, as JSON values (True is
        not 1); the line may carry nothing but clean, lines and an error."""
        def result(data: bytes, fields: dict):
            got_code, last, raw = run_vector(kind, data)
            self.assertLessEqual(set(last), {"clean", "lines", "error"}, raw)
            for value in self.PLANTED:
                self.assertNotIn(value.encode(), raw, "a scanned value leaked into the output")
            self.assertLessEqual(set(fields), set(last), raw)  # a missing field is red
            return got_code, json.dumps({name: last[name] for name in fields}, sort_keys=True), raw

        want = (code, json.dumps(expect, sort_keys=True))
        got = result(data, expect)
        self.assertEqual(got[:2], want, got[2])
        if changed is None:
            return
        self.assertNotEqual(changed, data)
        got = result(changed, expect)
        self.assertNotEqual(got[:2], want, "the changed input gave the expected result")
        got = result(changed, changed_expect)
        self.assertEqual(got[:2], (changed_code, json.dumps(changed_expect, sort_keys=True)), got[2])

    def test_diff_added_line(self):
        fake = FAKES["github-token"]
        self.check("diff", diff_with('T = "%s"' % fake).encode(), 1, {"clean": False, "lines": [7]},
                   diff_with('T = "%s"' % fake[:-1]).encode(), 0, {"clean": True, "lines": []})

    def test_diff_context_line(self):
        text = diff_with("x = 1").replace(" import os", " ID = %s" % AWS_ID)
        self.check("diff", text.encode(), 1, {"clean": False, "lines": [6]},
                   text.replace(AWS_ID, AWS_ID[:-1]).encode(), 0, {"clean": True, "lines": []})

    def test_row_json_escape(self):
        escaped = "".join("\\u%04x" % ord(c) for c in AWS_ID)
        rows = [row_with("first"), row_with("ESCAPED"), row_with("third")]
        text = "\n".join(rows).replace("ESCAPED", escaped) + "\n"
        self.assertNotIn(AWS_ID, text)
        self.check("row", text.encode(), 1, {"clean": False, "lines": [2]},
                   text.replace(escaped[:12], escaped[:6] + "4c").encode(), 0, {"clean": True, "lines": []})

    def test_row_keys_and_values_are_decoded_and_scanned(self):
        """A token cut by a JSON \\n escape is no token in the row as written; decoded, its two lines join
        back into one. It is caught as an object key and as a value, nested or not."""
        fake = FAKES["github-token"]
        cut = fake[:10] + "\\n" + fake[10:]
        rows = [row_with("first"), '{"payload": {"%s": 1}}' % cut, row_with("third"), '{"a": ["%s"]}' % cut]
        self.check("row", "\n".join(rows).encode(), 1, {"clean": False, "lines": [2, 4]},
                   "\n".join(rows[:3] + [row_with("fourth")]).encode(), 1, {"clean": False, "lines": [2]})
        repeated = '{"a": "%s", "a": "x"}' % cut  # a repeated key hides no value
        self.check("row", repeated.encode(), 1, {"clean": False, "lines": [1]},
                   repeated.replace(cut, "plain").encode(), 0, {"clean": True, "lines": []})

    def test_prompt(self):
        fake = FAKES["github-token"]
        self.check("prompt", prompt_with("leak %s" % fake).encode(), 1, {"clean": False, "lines": [4]},
                   prompt_with("leak %s" % fake.replace("p_", "q_", 1)).encode(), 0, {"clean": True, "lines": []})

    def test_prompt_clean(self):
        self.check("prompt", prompt_with("nothing secret here").encode(), 0, {"clean": True, "lines": []},
                   prompt_with("nothing secret %s" % AWS_ID).encode(), 1, {"clean": False, "lines": [4]})

    def test_glued_token(self):
        fake = FAKES["github-token"]
        text = "see x_%s now\nplain\nid_%s_x\n" % (fake, AWS_ID)
        self.check("prompt", text.encode(), 1, {"clean": False, "lines": [1, 3]},
                   text.replace("x_gh" + "p_", "x_gh" + "q_").encode(), 1, {"clean": False, "lines": [3]})

    def test_clean_near_miss(self):
        """ghq_ plus 36, a 15-character key id and the words FAKE and EXAMPLE, alone, in prose and on the
        line before a word (the joined-line boundary) are not matches. No secret-named key assigns them
        here: after one they are reported (test_assignment_value_shape_never_exempts)."""
        lines = ["token %s is not real" % NEAR_GH, "id %s" % NEAR_ID, "FAKE", "EXAMPLE", NEAR_GH,
                 NEAR_ID, "FAKE", "x_%s_y" % NEAR_ID]
        text = "\n".join(lines) + "\n"
        self.check("prompt", text.encode(), 0, {"clean": True, "lines": []},
                   text.replace("gh" + "q_", "gh" + "p_", 1).encode(), 1, {"clean": False, "lines": [1]})
        self.check("diff", diff_with("\n+".join(lines)).encode(), 0, {"clean": True, "lines": []},
                   diff_with("\n+".join(lines + [NEAR_ID + "Q"])).encode(), 1, {"clean": False, "lines": [15]})
        rows = "\n".join(row_with(line) for line in lines)
        self.check("row", rows.encode(), 0, {"clean": True, "lines": []},
                   rows.replace(NEAR_ID, NEAR_ID + "Q", 1).encode(), 1, {"clean": False, "lines": [2]})

    def test_assignment_value_shape_never_exempts(self):
        """Refutation 04585388fd8833de: a value that looks like a near miss of a provider token (AKIA or
        ASIA plus fewer than 16, gh<letter>_ plus anything) after a secret-named key is reported like any
        other value of 8 or more characters, quoted or bare, on one line or split after the key, in all
        three kinds. The same line with the key renamed to a word that is not secret-named is clean, so
        the key is what reports it."""
        pw, tok, sec = j("pass", "word"), j("to", "ken"), j("sec", "ret")
        gh_name, aws_name = j("GITHUB_TO", "KEN"), j("AWS_ACCESS_KEY", "_ID")
        cases = [
            ('%s = "%s"' % (pw, j("AK", "IA", "HUNTER2PASSWD")), pw),
            ("%s=%s" % (gh_name, NEAR_GH), gh_name),
            ('%s = "%s"' % (aws_name, NEAR_ID), aws_name),
            ("%s: %s" % (sec, j("AS", "IA", "QWERTY12")), sec),
            ("--%s %s" % (pw, j("gh", "x_", "abcdefgh")), pw),
            ("%s:\n  %s" % (tok, NEAR_GH), tok),
        ]
        for line, key in cases:
            with self.subTest(line=line):
                text = line + "\n"
                plain = text.replace(key, "colour")
                self.check("prompt", text.encode(), 1, {"clean": False, "lines": [1]},
                           plain.encode(), 0, {"clean": True, "lines": []})
                body_lines = line.split("\n")
                self.check("diff", diff_with("\n+".join(body_lines)).encode(), 1, {"clean": False, "lines": [7]},
                           diff_with("\n+".join(plain.rstrip("\n").split("\n"))).encode(), 0,
                           {"clean": True, "lines": []})
                if "\n" not in line:
                    self.check("row", row_with(line).encode(), 1, {"clean": False, "lines": [1]},
                               row_with(plain.rstrip("\n")).encode(), 0, {"clean": True, "lines": []})

    def test_row_member_under_secret_named_key(self):
        """Claim 87c088321252: in a decoded row, an object member whose key is secret-named is an
        assignment, so a string of 8 or more characters it holds (directly, in an array, or as a nested
        object's value, at any depth; the key escaped or fullwidth) reports the line. Each case with the
        key renamed to a word that is not secret-named is clean, so the key is what reports it."""
        kp, kt = j("pass", "word"), j("to", "ken")
        held = body("member", 14)
        fullwidth = "".join(chr(ord(c) + 0xFEE0) for c in kp)
        cases = [
            ({"row_id": "r1", kp: held}, kp),
            ({"payload": {"env": {j("DB_PASS", "WORD"): held}}}, j("DB_PASS", "WORD")),
            ({j("to", "kens"): ["short", held]}, j("to", "kens")),
            ({j("cred", "entials"): {"user": held}}, j("cred", "entials")),
            ({j("Auth", "orization"): "Bearer " + held}, j("Auth", "orization")),
            ({fullwidth: held}, fullwidth),
        ]
        for obj, key in cases:
            with self.subTest(key=key):
                text = json.dumps(obj) + "\n"
                plain = text.replace(json.dumps(key)[1:-1], "colour")
                self.assertNotEqual(plain, text)
                self.check("row", text.encode(), 1, {"clean": False, "lines": [1]},
                           plain.encode(), 0, {"clean": True, "lines": []})
        escaped = '{"\\u0070%s": "%s"}\n' % (kp[1:], held)  # the key spelled with a \\u escape
        self.check("row", escaped.encode(), 1, {"clean": False, "lines": [1]},
                   escaped.replace(kp[1:], "olour").encode(), 0, {"clean": True, "lines": []})
        # the member rule's stated boundaries: the same skips as an assignment in text (a whole template,
        # a null word, fewer than 8 characters after the scheme word), and numbers, booleans and null
        clean = [{kp: "${DB_%s}" % kp.upper()}, {kt: "null"}, {kp: "abc1234"}, {kt: "Bearer abc1234"},
                 {j("tokens", "_in"): 123456789012}, {kp: True}, {kp: None}, {kp: []},
                 {"name": kp, "value": "plain words here"}]
        rows = "\n".join(json.dumps(obj) for obj in clean) + "\n"
        self.check("row", rows.encode(), 0, {"clean": True, "lines": []},
                   rows.replace("abc1234", "abc12345").encode(), 1, {"clean": False, "lines": [3, 4]})

    def test_row_unusable_fails_closed(self):
        good = row_with("first")
        for bad in ("not json", "", "[1]", '"text"', "{", "null"):
            with self.subTest(bad=bad):
                text = "\n".join([good, bad, row_with("third")]) + "\n"
                fixed = "\n".join([good, row_with("second"), row_with("third")]) + "\n"
                self.check("row", text.encode(), 2, {"clean": False}, fixed.encode(), 0, {"clean": True})
        # a blank line at the end is a line; the empty piece after the last LF is not
        self.check("row", (good + "\n\n").encode(), 2, {"clean": False})
        self.check("row", (good + "\n").encode(), 0, {"clean": True, "lines": []})
        self.check("row", b"", 0, {"clean": True, "lines": []})

    def test_not_utf8_is_unusable(self):
        for kind in KINDS:
            text = json.dumps({"summary": "café"}, ensure_ascii=False) if kind == "row" else "café %s\n" % AWS_ID
            data = text.encode("utf-8")
            with self.subTest(kind=kind):
                self.check(kind, data.replace(b"\xc3\xa9", b"\xe9"), 2, {"clean": False}, data,
                           0 if kind == "row" else 1,
                           {"clean": True, "lines": []} if kind == "row" else {"clean": False, "lines": [1]})

    def test_lines_are_sorted_unique_and_counted_by_lf(self):
        """Two matches on one line give it once; lines 3 and 10 come out in order; a form feed, a CR
        and a Unicode line separator split nothing that is reported."""
        fake = FAKES["github-token"]
        lines = ["plain"] * 10
        lines[2] = "%s and %s" % (fake, AWS_ID)
        lines[9] = "again %s" % AWS_ID
        lines[0] = "a\x0cb\rc d"
        text = "\n".join(lines)  # no final LF: the last piece is still a line
        self.check("prompt", text.encode(), 1, {"clean": False, "lines": [3, 10]},
                   text.replace(AWS_ID, "x").encode(), 1, {"clean": False, "lines": [3]})

    def test_stdin_is_not_read_and_usage(self):
        for data in (b"plain\n", b""):
            code, last, raw = run_vector("prompt", data, stdin=FAKES["github-token"].encode())
            self.assertEqual((code, last), (0, {"clean": True, "lines": []}), raw)
        for args in (["scan", "email", "/dev/null"], ["scan", "prompt"], ["scan", "prompt", "/nonexistent/x"],
                     ["scan", "prompt", "/dev/null", "extra"]):
            with self.subTest(args=args):
                proc = subprocess.run([sys.executable, "-m", "gate.secrets", *args], cwd=REFEREE,
                                      env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"), capture_output=True,
                                      timeout=60)
                self.assertEqual(proc.returncode, 2, proc.stderr)
                self.assertIs(json.loads(proc.stdout.decode().splitlines()[-1])["clean"], False)


class Usage(unittest.TestCase):
    def test_unusable_input_is_exit_2_never_clean(self):
        sys.path.insert(0, REFEREE)  # as Library: the module and tests/refusal.py, imported here only
        self.addCleanup(sys.path.remove, REFEREE)
        from gate import secrets as S
        import refusal
        cases = [
            ["scan"],
            ["scan", "--kind", "email"],
            ["scan", "--kind", "diff", "/nonexistent/secrets-input"],
            ["send"],
            ["send", "--", "/nonexistent/sender"],
            ["frobnicate"],
        ]
        for args in cases:
            with self.subTest(args=args):
                code, result, raw = run_secrets(args, stdin=b"hello\n")
                refusal.assert_refused(self, S, args, code, result, raw)
                self.assertIn("error", result)
                self.assertNotIn("clean", result)


if __name__ == "__main__":
    unittest.main()
