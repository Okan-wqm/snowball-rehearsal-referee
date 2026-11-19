"""``runner.test_results``: one test run's stdout and exit code as the ``tests`` list, each rule of the module's
docstring with its own test.

- TAP: ``node --test``'s real output (the toy's captured run) and the edge cases of a top-level line;
- jest's ``--json`` document: one entry per assertion that ran, the file in the id; a file that did not run is
  red by its own name; bytes before the document are read past; several documents are one failure; a stdout
  that does not end with the document is not jest's (near misses of the shape, text on its line, lines after);
- the exit entry, in both formats.

The jest documents here are written from the shape ``@jest/test-result`` 30.5.2's ``formatTestResults`` gives
(read from its code); they are not captured from a jest run, which this machine does not make.
"""

from __future__ import annotations

import copy
import json
import os
import sys
import unittest

REFEREE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BRAIN = os.path.dirname(REFEREE)
sys.path.insert(0, REFEREE)

from runner import test_results as T  # noqa: E402


def assertion(title: str, status: str = "passed", ancestors=("outbox",)) -> dict:
    return {"ancestorTitles": list(ancestors), "title": title, "status": status,
            "fullName": " ".join(list(ancestors) + [title]), "failureMessages": [], "duration": 3, "location": None}


def suite(name: str, status: str, assertions: list, message: str = "") -> dict:
    return {"name": name, "status": status, "message": message, "assertionResults": assertions, "startTime": 1,
            "endTime": 2, "summary": "", "coverage": {}}


def document(*files: dict) -> dict:
    return {"numTotalTests": sum(len(f["assertionResults"]) for f in files), "numTotalTestSuites": len(files),
            "numFailedTests": 0, "numPassedTests": 0, "numPendingTests": 0, "numRuntimeErrorTestSuites": 0,
            "success": True, "startTime": 0, "wasInterrupted": False, "openHandles": [], "snapshot": {},
            "testResults": list(files)}


def line(doc) -> bytes:
    """jest's write: the document as one line with a final newline."""
    return (json.dumps(doc) + "\n").encode()


A = "/work/libs/outbox/src/a.spec.ts"
B = "/work/libs/outbox/src/b.spec.ts"
GREEN = document(suite(A, "passed", [assertion("stores a row"), assertion("marks it sent", ancestors=("outbox", "relay"))]),
                 suite(B, "passed", [assertion("loads", ancestors=())]))
GREEN_TESTS = [{"id": "libs/outbox/src/a.spec.ts > outbox > stores a row", "status": "pass"},
               {"id": "libs/outbox/src/a.spec.ts > outbox > relay > marks it sent", "status": "pass"},
               {"id": "libs/outbox/src/b.spec.ts > loads", "status": "pass"}]


class Tap(unittest.TestCase):
    def test_node_test_real_output(self):
        with open(os.path.join(BRAIN, "tests", "fixtures", "toy-candidates", "bad-test.json")) as fh:
            got = json.load(fh)
        tests = T.read(got["test_stdout"].encode(), got["test_exit"])
        self.assertEqual(len(tests), 8)
        self.assertEqual([t["id"] for t in tests if t["status"] == "fail"],
                         ["slugify lowers, joins words with dashes and trims dashes"])

    def test_edges(self):
        out = ("ok 1 - a\n  ok 1 - sub\nnot ok 2 - b # TODO later\nok 3 - c # skip\nok 4\n"
               "ok 5 - x \\# y \\\\ z\nnot ok 6 - d # some other directive\nok 7 - e\r\n").encode()
        want = [{"id": "a", "status": "pass"}, {"id": "4", "status": "pass"}, {"id": "x # y \\ z", "status": "pass"},
                {"id": "d", "status": "fail"}, {"id": "e", "status": "pass"}]
        self.assertEqual(T.tap(out), want)
        self.assertEqual(T.read(out, 1), want)

    def test_exit_code_without_a_failing_line_is_a_failure(self):
        self.assertEqual(T.read(b"ok 1 - a\nBail out!\n", 1)[-1], {"id": "test_cmd exit 1", "status": "fail"})
        self.assertEqual(T.read(b"", None), [{"id": "test_cmd exit None", "status": "fail"}])
        self.assertEqual(T.read(b"", 0), [])
        self.assertEqual(T.read(b"ok 1 - a # SKIP\n", 0), [])


class Jest(unittest.TestCase):
    def test_one_entry_per_assertion_with_its_file_and_titles(self):
        self.assertEqual(T.read(line(GREEN), 0), GREEN_TESTS)
        self.assertEqual(T.jest(line(GREEN)), GREEN_TESTS)

    def test_the_document_without_its_newline_and_pretty_printed_is_read(self):
        self.assertEqual(T.read(json.dumps(GREEN).encode(), 0), GREEN_TESTS)
        self.assertEqual(T.read(json.dumps(GREEN, indent=2).encode(), 0), GREEN_TESTS)

    def test_a_failed_assertion_is_fail_and_adds_no_file_entry(self):
        doc = document(suite(A, "failed", [assertion("stores a row"), assertion("marks it sent", "failed")]))
        self.assertEqual(T.read(line(doc), 1), [
            {"id": "libs/outbox/src/a.spec.ts > outbox > stores a row", "status": "pass"},
            {"id": "libs/outbox/src/a.spec.ts > outbox > marks it sent", "status": "fail"}])

    def test_tests_that_did_not_run_are_left_out(self):
        for status in T.JEST_NOT_RUN:
            with self.subTest(status=status):
                doc = document(suite(A, "focused", [assertion("runs"), assertion("waits", status)]))
                self.assertEqual(T.read(line(doc), 0),
                                 [{"id": "libs/outbox/src/a.spec.ts > outbox > runs", "status": "pass"}])
        self.assertEqual(sorted(T.JEST_NOT_RUN), ["disabled", "pending", "skipped", "todo"])

    def test_a_status_that_is_not_known_is_fail(self):
        for status in ("failed", "focused", "PASSED", "", "ok"):
            with self.subTest(status=status):
                doc = document(suite(A, "passed", [assertion("runs", status)]))
                self.assertEqual(T.read(line(doc), 0),
                                 [{"id": "libs/outbox/src/a.spec.ts > outbox > runs", "status": "fail"}])

    def test_a_file_that_did_not_run_is_red_by_its_name(self):
        # what jest reports for a file ts-jest could not compile: failed, a message, no assertion
        doc = document(suite(A, "failed", [], "TS2322: Type 'x' is not assignable"),
                       suite(B, "passed", [assertion("loads", ancestors=())]))
        self.assertEqual(T.read(line(doc), 1), [{"id": "libs/outbox/src/a.spec.ts", "status": "fail"},
                                                {"id": "libs/outbox/src/b.spec.ts > loads", "status": "pass"}])
        # also when its own assertions all passed (an error after them), and for a status jest does not have
        for status in ("failed", "errored"):
            with self.subTest(status=status):
                doc = document(suite(A, status, [assertion("runs")]))
                self.assertEqual(T.read(line(doc), 0), [
                    {"id": "libs/outbox/src/a.spec.ts > outbox > runs", "status": "pass"},
                    {"id": "libs/outbox/src/a.spec.ts", "status": "fail"}])

    def test_file_statuses_that_are_not_failures_add_no_entry(self):
        for status in T.JEST_FILE_OK:
            with self.subTest(status=status):
                self.assertEqual(T.read(line(document(suite(A, status, []))), 0), [])
        self.assertEqual(sorted(T.JEST_FILE_OK), ["focused", "passed", "skipped"])

    def test_a_name_outside_the_root_is_kept_as_written(self):
        for name in ("/elsewhere/a.spec.ts", "/work/../a.spec.ts", "a.spec.ts"):
            with self.subTest(name=name):
                doc = document(suite(name, "passed", [assertion("runs", ancestors=())]))
                self.assertEqual(T.read(line(doc), 0), [{"id": name + " > runs", "status": "pass"}])
        doc = document(suite("/srv/x/a.spec.ts", "passed", [assertion("runs", ancestors=())]))
        self.assertEqual(T.read(line(doc), 0, root="/srv/x"), [{"id": "a.spec.ts > runs", "status": "pass"}])

    def test_bytes_before_the_document_are_read_past(self):
        noise = b"[Nest] 41  - LOG [Outbox] started\n\xff\xfe not utf-8\nok 1 - a line that looks like TAP\n"
        self.assertEqual(T.read(noise + line(GREEN), 0), GREEN_TESTS)

    def test_several_documents_are_one_failure(self):
        self.assertEqual(T.read(line(GREEN) + line(GREEN), 0), [{"id": T.SEVERAL, "status": "fail"}])
        self.assertEqual(T.read(line(document()) + b"text\n" + line(GREEN), 0), [{"id": T.SEVERAL, "status": "fail"}])

    def test_stdout_that_does_not_end_with_the_document_is_not_jests(self):
        for name, out in (("text on its line", b"listening" + line(GREEN)),
                          ("a line after it", line(GREEN) + b"done\n"),
                          ("a blank line after it, below other bytes", b"x\n" + line(GREEN) + b"\n"),
                          ("not utf-8", line(GREEN)[:-2] + b"\xff}\n")):
            with self.subTest(name=name):
                self.assertIsNone(T.jest(out))
                self.assertEqual(T.read(out, 0), [])
                self.assertEqual(T.read(out, 1), [{"id": "test_cmd exit 1", "status": "fail"}])

    def test_near_misses_of_the_shape_are_not_jests(self):
        def without(path: list, value=None, drop=False):
            doc = copy.deepcopy(GREEN)
            node = doc
            for key in path[:-1]:
                node = node[key]
            if drop:
                del node[path[-1]]
            else:
                node[path[-1]] = value
            return doc

        self.assertTrue(T.shaped(GREEN))
        first, one = ["testResults", 0], ["testResults", 0, "assertionResults", 0]
        cases = [without(["numTotalTests"], drop=True), without(["numTotalTests"], "3"),
                 without(["numTotalTests"], True), without(["testResults"], drop=True), without(["testResults"], {}),
                 without(first, "a.spec.ts"), without(first + ["name"], drop=True), without(first + ["name"], 1),
                 without(first + ["status"], drop=True), without(first + ["status"], None),
                 without(first + ["assertionResults"], drop=True), without(first + ["assertionResults"], {}),
                 without(one, []), without(one + ["title"], drop=True), without(one + ["title"], 7),
                 without(one + ["status"], drop=True), without(one + ["status"], True),
                 without(one + ["ancestorTitles"], drop=True), without(one + ["ancestorTitles"], "outbox"),
                 without(one + ["ancestorTitles"], [1]), [GREEN], None, "x", 3]
        for i, doc in enumerate(cases):
            with self.subTest(case=i):
                self.assertFalse(T.shaped(doc))
                self.assertIsNone(T.jest(line(doc)))
                self.assertEqual(T.read(line(doc), 0), [])

    def test_the_exit_code_with_no_failed_test_is_a_failure(self):
        # a run jest fails for a reason no test carries (a coverage threshold)
        self.assertEqual(T.read(line(GREEN), 1), GREEN_TESTS + [{"id": "test_cmd exit 1", "status": "fail"}])
        doc = document(suite(A, "failed", [assertion("runs", "failed")]))
        self.assertEqual(len(T.read(line(doc), 1)), 1)

    def test_a_document_without_tests_is_zero_tests(self):
        self.assertEqual(T.read(line(document()), 0), [])


if __name__ == "__main__":
    unittest.main()
