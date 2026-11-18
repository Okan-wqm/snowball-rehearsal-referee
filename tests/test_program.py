"""Test 40 (asama-0/09, MF11's signature): ``loop.program``, the loop's one runner of the Sigstore program.

- ``run`` on real processes: the exit code; 127 for a program that cannot start; no standard input reaches the
  program; what it writes to standard output and to standard error both reach this process's file descriptor 2,
  in the order written; ``signs`` is read from what it wrote, is empty for exit 0 whatever it wrote, and reads only
  the last ``TAIL`` bytes;
- ``signs_of`` on the four real outputs of ``sigstore`` 4.5.0's ``sign`` (``fixtures/sigstore-sign-failures.json``:
  each exits 1 and writes no bundle), each rule alone: a phrase wrapped at a word boundary, a phrase inside a word
  is not found, the traceback's last line with and without a message, a line of another form, a type that is too
  long, no traceback; no text of the output but the names comes back;
- the modules of ``loop/`` that name ``subprocess`` are this one and the two that run ``git`` (``fetch``,
  ``gitobj``): a new one that starts a process is seen here.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest

REFEREE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, REFEREE)

from loop import program as PG  # noqa: E402

with open(os.path.join(HERE, "fixtures", "sigstore-sign-failures.json"), encoding="utf-8") as _fh:
    REAL = json.load(_fh)
CASES = {case["mode"]: case for case in REAL["cases"]}
TB = "Traceback (most recent call last):\n  File \"x.py\", line 1, in <module>\n"


def py(code: str) -> list[str]:
    return [sys.executable, "-c", code]


def with_fd2(call):
    """``call()``'s answer and the bytes written to file descriptor 2 meanwhile."""
    with tempfile.TemporaryFile() as kept:
        saved = os.dup(2)
        os.dup2(kept.fileno(), 2)
        try:
            answer = call()
        finally:
            os.dup2(saved, 2)
            os.close(saved)
        kept.seek(0)
        return answer, kept.read()


class Run(unittest.TestCase):
    def test_the_exit_code(self):
        for code in (0, 1, 2, 3):
            answer = PG.run(py("import sys; sys.exit(%d)" % code))
            self.assertEqual((answer, type(answer), answer.signs), (code, PG.Exit, ()))

    def test_a_program_that_cannot_start(self):
        with tempfile.TemporaryDirectory() as tmp:
            answer = PG.run([os.path.join(tmp, "absent")])
        self.assertEqual((answer, type(answer), answer.signs), (127, PG.Exit, ()))

    def test_the_program_reads_no_input(self):
        # the caller's stdin holds bytes; the program gets none (its exit code is how many it read)
        read, write = os.pipe()
        os.write(write, b"xyz")
        os.close(write)
        saved = os.dup(0)
        os.dup2(read, 0)
        try:
            code = PG.run(py("import sys; sys.exit(len(sys.stdin.buffer.read()))"))
        finally:
            os.dup2(saved, 0)
            os.close(saved)
            os.close(read)
        self.assertEqual(code, 0)

    def test_both_streams_reach_fd_2_in_order(self):
        code = ("import os, sys\nos.write(1, b'one\\n'); os.write(2, b'two\\n'); os.write(1, b'three\\n')\n"
                "sys.exit(%d)")
        for exit_code in (0, 4):
            answer, seen = with_fd2(lambda: PG.run(py(code % exit_code)))
            self.assertEqual((answer, seen), (exit_code, b"one\ntwo\nthree\n"))

    def test_signs_are_read_from_either_stream(self):
        for fd in (1, 2):
            answer, _ = with_fd2(lambda: PG.run(py(
                "import os, sys; os.write(%d, b'A network issue occurred.\\n'); sys.exit(1)" % fd)))
            self.assertEqual((answer, answer.signs), (1, ("network",)))

    def test_a_real_uncaught_exception(self):
        answer, seen = with_fd2(lambda: PG.run(py("raise KeyError('secret-text')")))
        self.assertEqual((answer, answer.signs), (1, ("raised:KeyError",)))
        self.assertIn(b"secret-text", seen)  # the output is passed on whole; the signs hold none of it

    def test_success_has_no_signs(self):
        answer, _ = with_fd2(lambda: PG.run(py("print('A network issue occurred.')")))
        self.assertEqual((answer, answer.signs), (0, ()))

    def test_only_the_tail_is_read(self):
        phrase = "A network issue occurred."
        code = "import sys; sys.stdout.write(%r + 'x' * %d); sys.stdout.flush(); sys.exit(1)"
        answer, seen = with_fd2(lambda: PG.run(py(code % (phrase, PG.TAIL - len(phrase)))))
        self.assertEqual((answer.signs, len(seen)), (("network",), PG.TAIL))
        answer, seen = with_fd2(lambda: PG.run(py(code % (phrase, PG.TAIL - len(phrase) + 1))))
        self.assertEqual((answer.signs, len(seen)), ((), PG.TAIL + 1))  # cut by one byte; still passed on whole


class Signs(unittest.TestCase):
    def test_the_real_outputs(self):
        self.assertEqual((REAL["sigstore"], sorted(CASES)), ("sigstore 4.5.0", [
            "fulcio_500", "fulcio_refused", "oidc_refused", "tuf_unreachable"]))
        expected = {"oidc_refused": ("ambient_credential",),
                    "tuf_unreachable": ("network", "tuf_refresh"),
                    "fulcio_500": ("raised:sigstore._internal.fulcio.client.FulcioClientError",),
                    "fulcio_refused": ("raised:requests.exceptions.ConnectionError",)}
        for mode, signs in expected.items():
            with self.subTest(mode=mode):
                case = CASES[mode]
                self.assertEqual((case["exit"], case["bundle_written"]), (1, False))
                self.assertEqual(PG.signs_of(case["output"].encode()), signs)

    def test_the_real_outputs_say_what_the_rules_read(self):
        # the fixtures are not bent to the rules: the real texts hold the wrapped phrase and the bare last line
        self.assertNotIn("An issue occurred with ambient credential detection.", CASES["oidc_refused"]["output"])
        self.assertRegex(CASES["oidc_refused"]["output"], r"with ambient +\n +credential detection\.")
        self.assertTrue(CASES["fulcio_500"]["output"].endswith(
            "\nsigstore._internal.fulcio.client.FulcioClientError\n"))
        self.assertIn("\nrequests.exceptions.ConnectionError: HTTPConnectionPool(", CASES["fulcio_refused"]["output"])

    def test_every_phrase_alone(self):
        for name, phrase in PG.PHRASES:
            with self.subTest(name=name):
                self.assertEqual(PG.signs_of(("x %s y" % phrase).encode()), (name,))
                self.assertEqual(PG.signs_of(phrase.replace(" ", " \n\t ").encode()), (name,))
                self.assertEqual(PG.signs_of(phrase.replace(" ", "").encode()), ())
                self.assertEqual(PG.signs_of((phrase[:5] + "-\n" + phrase[5:]).encode()), ())
        self.assertEqual(len({name for name, _ in PG.PHRASES}), len(PG.PHRASES))

    def test_phrases_come_in_the_table_s_order(self):
        text = " ".join(phrase for _, phrase in reversed(PG.PHRASES))
        self.assertEqual(PG.signs_of(text.encode()), tuple(name for name, _ in PG.PHRASES))

    def test_the_traceback_s_last_line(self):
        for last, signs in (("KeyError: 'k'", ("raised:KeyError",)),
                            ("a.b.CError", ("raised:a.b.CError",)),
                            ("a.b.CError: m\n", ("raised:a.b.CError",)),
                            ("_x.Y9Exception: m", ("raised:_x.Y9Exception",)),
                            ("SystemExit: 3", ("raised:SystemExit",)),
                            ("KeyboardInterrupt", ("raised:KeyboardInterrupt",)),
                            ("ValueError: m\nnote: more\n  indented", ("raised:ValueError",)),
                            ("AError: 1\n\nDuring handling\nb.BError: 2", ("raised:b.BError",)),
                            ("ghs_0123456789abcdef", ("traceback",)),
                            ("eyJhbGci.eyJzdWIi.c2ln", ("traceback",)),
                            ("a.b.CError m", ("traceback",)),
                            ("a.b.CErrors: m", ("traceback",)),
                            (" KeyError: m", ("traceback",)),
                            ("a..KeyError: m", ("traceback",)),
                            ("a-b.KeyError: m", ("traceback",)),
                            ("9a.KeyError: m", ("traceback",)),
                            ("é.KeyError: m", ("traceback",)),
                            ("", ("traceback",))):
            with self.subTest(last=last):
                self.assertEqual(PG.signs_of((TB + last).encode()), signs)

    def test_a_type_too_long(self):
        fits = "a" * (PG.MAX_TYPE - 5) + "Error"
        self.assertEqual(PG.signs_of((TB + fits + ": m").encode()), ("raised:" + fits,))
        self.assertEqual(PG.signs_of((TB + "a" + fits + ": m").encode()), ("traceback",))
        self.assertEqual(PG.signs_of((TB + "KeyError: m\na" + fits + ": m").encode()), ("raised:KeyError",))

    def test_no_traceback_no_type(self):
        self.assertEqual(PG.signs_of(b"KeyError: m\n"), ())
        self.assertEqual(PG.signs_of(b"traceback (most recent call last):\nKeyError: m\n"), ())
        self.assertEqual(PG.signs_of(b""), ())
        self.assertEqual(PG.signs_of(b"\xff\xfe"), ())

    def test_a_phrase_and_a_traceback(self):
        text = "A network issue occurred.\n" + TB + "KeyError: m"
        self.assertEqual(PG.signs_of(text.encode()), ("network", "raised:KeyError"))

    def test_no_text_of_the_output_but_the_names(self):
        for case in REAL["cases"]:
            for sign in PG.signs_of(case["output"].encode()):
                self.assertRegex(sign, r"\A([a-z_]+|raised:[A-Za-z0-9_.]{1,%d})\Z" % PG.MAX_TYPE)


class OneRunner(unittest.TestCase):
    def test_which_loop_modules_start_a_process(self):
        loop = os.path.join(REFEREE, "loop")
        starters = []
        for name in sorted(os.listdir(loop)):
            if name.endswith(".py"):
                with open(os.path.join(loop, name), encoding="utf-8") as fh:
                    if "subprocess" in fh.read():
                        starters.append(name)
        self.assertEqual(starters, ["fetch.py", "gitobj.py", "program.py"])  # the first two run ``git``


if __name__ == "__main__":
    unittest.main()
