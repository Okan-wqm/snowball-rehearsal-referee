"""``profile.docker`` (run with test 47): each rule of its docstring on a text made for it.

- ``instructions``: parser directives (``escape`` changes the continuation character, a non-directive line ends
  them, a directive after it is a comment), comments and blank lines (also inside a continuation), continuations
  joined, keywords upper-cased, the starting line; heredocs in ``RUN``/``COPY``/``ADD`` (plain, ``<<-`` with tabs,
  quoted, a file descriptor, several in one instruction, never closed) and what is none (``$((1<<2))``,
  ``a<<EOF``, a word starting with a digit, another instruction);
- ``copies``: flags removed, ``--from`` makes every source ``stage``, the JSON form and the fallback to blanks,
  each kind in its order, ``ADD`` read as ``COPY``, malformed counted;
- ``compose_builds`` over a file ``profile.yamlblock`` read: each service's ``build`` (a value, a mapping, a flow
  mapping, a value not a string kept as read, ``null`` none), defaults ``None``, a ``build`` merged from an
  ``x-`` extension, a ``build`` outside ``services`` and a document with no ``services`` mapping none;
- the names: ``is_dockerfile`` and ``is_compose`` by name only, case as written.
"""

from __future__ import annotations

import os
import sys
import unittest

REFEREE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REFEREE)

from profile import docker  # noqa: E402
from profile import yamlblock  # noqa: E402


class Instructions(unittest.TestCase):
    def test_keywords_lines_comments(self) -> None:
        text = "# a comment\nFROM base AS b\n\n  run echo hi\n# another\ncopy a b\n"
        self.assertEqual(docker.instructions(text),
                         [(2, "FROM", "base AS b"), (4, "RUN", "echo hi"), (6, "COPY", "a b")])

    def test_continuation_skips_comments_and_blanks(self) -> None:
        text = "RUN a \\\n# inside\n\n  b \\\n  c\nCOPY x y\n"
        self.assertEqual(docker.instructions(text), [(1, "RUN", "a   b   c"), (6, "COPY", "x y")])

    def test_continuation_at_end_of_file(self) -> None:
        self.assertEqual(docker.instructions("COPY a b \\"), [(1, "COPY", "a b")])

    def test_escape_directive(self) -> None:
        text = "# syntax=docker/dockerfile:1\n# escape=`\nCOPY a `\n  b\nRUN x \\\nCOPY c d\n"
        self.assertEqual(docker.instructions(text),
                         [(3, "COPY", "a   b"), (5, "RUN", "x \\"), (6, "COPY", "c d")])

    def test_directives_end_at_other_line(self) -> None:
        for first in ("# a plain comment\n", "\n", "FROM x\n"):
            with self.subTest(first=first):
                got = docker.instructions(first + "# escape=`\nRUN a \\\nCOPY b c\n")
                self.assertEqual([i[1] for i in got], [k for k in ("FROM",) if first.startswith("FROM")]
                                 + ["RUN"])
                self.assertEqual(got[-1][2], "a COPY b c")

    def test_heredocs(self) -> None:
        cases = {
            "RUN <<EOF\nCOPY no no\nEOF\nCOPY a b\n": [(1, "RUN", "<<EOF"), (4, "COPY", "a b")],
            "RUN <<-EOF\nCOPY no no\n\t\tEOF\nCOPY a b\n": [(1, "RUN", "<<-EOF"), (4, "COPY", "a b")],
            "RUN <<EOF\nCOPY no no\n\tEOF\nEOF\nCOPY a b\n": [(1, "RUN", "<<EOF"), (5, "COPY", "a b")],
            "RUN <<'END'\nCOPY no\nEND\nCOPY a b\n": [(1, "RUN", "<<'END'"), (4, "COPY", "a b")],
            'RUN 2<<"E_1" cat\nCOPY no\nE_1\nCOPY a b\n': [(1, "RUN", '2<<"E_1" cat'), (4, "COPY", "a b")],
            "COPY <<A <<B /d/\nx\nA\ny\nB\nCOPY a b\n": [(1, "COPY", "<<A <<B /d/"), (6, "COPY", "a b")],
            "add <<A /d\nx\nA\nCOPY a b\n": [(1, "ADD", "<<A /d"), (4, "COPY", "a b")],
            "RUN <<EOF\nCOPY no no\n": [(1, "RUN", "<<EOF")],
        }
        for text, want in cases.items():
            with self.subTest(text=text):
                self.assertEqual(docker.instructions(text), want)

    def test_not_heredocs(self) -> None:
        for args in ("echo $((1<<2))", "a<<EOF", "<<1EOF", "<<'EOF\"", "x << EOF"):
            with self.subTest(args=args):
                got = docker.instructions("RUN %s\nCOPY a b\nEOF\n" % args)
                self.assertEqual([i[1] for i in got], ["RUN", "COPY", "EOF"])
        for keyword in ("ENV X", "LABEL a", "CMD cat"):                     # only RUN, COPY and ADD take one
            with self.subTest(keyword=keyword):
                got = docker.instructions("%s <<EOF\nCOPY a b\nEOF\n" % keyword)
                self.assertEqual([i[1] for i in got], [keyword.split()[0], "COPY", "EOF"])


class Copies(unittest.TestCase):
    def test_kinds_in_order(self) -> None:
        text = ("COPY --chown=a:b --link a /b/c <<EOF http://h/x git@h:r.git $V/x <<$V https://$H/x d ./dest/\n"
                "x\nEOF\n"
                "ADD --from=stage http://h/x a $V dest\n")
        self.assertEqual(docker.copies(text), ([
            (1, "COPY", "a", "context"), (1, "COPY", "/b/c", "context"), (1, "COPY", "<<EOF", "heredoc"),
            (1, "COPY", "http://h/x", "remote"), (1, "COPY", "git@h:r.git", "remote"),
            (1, "COPY", "$V/x", "variable"), (1, "COPY", "<<$V", "heredoc"), (1, "COPY", "https://$H/x", "remote"),
            (1, "COPY", "d", "context"),
            (4, "ADD", "http://h/x", "stage"), (4, "ADD", "a", "stage"), (4, "ADD", "$V", "stage")], 0))

    def test_json_form_and_fallback(self) -> None:
        self.assertEqual(docker.copies('COPY ["a b", "c", "/d"]\n')[0],
                         [(1, "COPY", "a b", "context"), (1, "COPY", "c", "context")])
        self.assertEqual(docker.copies('COPY --chmod=644 ["x", "/d"]\n')[0], [(1, "COPY", "x", "context")])
        self.assertEqual(docker.copies("COPY [a] /d\n")[0], [(1, "COPY", "[a]", "context")])
        self.assertEqual(docker.copies('COPY [1, "a"] d\n')[0],
                         [(1, "COPY", "[1,", "context"), (1, "COPY", '"a"]', "context")])

    def test_flags_only_at_start(self) -> None:
        self.assertEqual(docker.copies("COPY a --link d\n")[0],
                         [(1, "COPY", "a", "context"), (1, "COPY", "--link", "context")])
        self.assertEqual(docker.copies("COPY --from=x\n"), ([], 1))
        self.assertEqual(docker.copies("COPY --x:y a d\n")[0],              # not a flag: a word of its own
                         [(1, "COPY", "--x:y", "context"), (1, "COPY", "a", "context")])

    def test_malformed_and_others_ignored(self) -> None:
        self.assertEqual(docker.copies("COPY onlyone\nADD\nCOPY []\nRUN cp a b\nFROM a\n"), ([], 3))

    def test_continued_copy(self) -> None:
        self.assertEqual(docker.copies("COPY a \\\n  b \\\n  /d\n")[0],
                         [(1, "COPY", "a", "context"), (1, "COPY", "b", "context")])


class ComposeBuilds(unittest.TestCase):
    def builds(self, text: str):
        return docker.compose_builds(yamlblock.load(text))

    def test_one_value_and_mapping(self) -> None:
        text = ("services:\n  a:\n    build: ./a  # here\n  b:\n    build: '../b'\n  c:\n    build: # none\n"
                "  d:\n    build:\n      context: \"..\"\n      args:\n        context: no\n"
                "      dockerfile: infra/Dockerfile.d # c\n    image: x\n    dockerfile: no\n"
                "  e:\n    build:\n      dockerfile: Dockerfile.e\n  f:\n    build: {context: f, dockerfile: F}\n"
                "  g:\n    image: only\n  h:\n    build: 7\n")
        self.assertEqual(self.builds(text), [("a", "./a", None), ("b", "../b", None), ("d", "..", "infra/Dockerfile.d"),
                                             ("e", None, "Dockerfile.e"), ("f", "f", "F"), ("h", 7, None)])

    def test_merged_from_an_extension(self) -> None:
        text = ("x-base: &base\n  build:\n    context: shared\n    dockerfile: D\nbuild: top\n"
                "services:\n  a:\n    <<: *base\n  b:\n    <<: *base\n    build: own\n")
        self.assertEqual(self.builds(text), [("a", "shared", "D"), ("b", "own", None)])

    def test_no_services(self) -> None:
        for text in ("build: a\n", "services: x\n", "services:\n  a: x\n  b:\n", "- a\n",
                     "x:\n  rebuild: a\n  build_x: b\n"):
            with self.subTest(text=text):
                self.assertEqual(self.builds(text), [])


class Names(unittest.TestCase):
    def test_dockerfile_names(self) -> None:
        for name in ("Dockerfile", "Dockerfile.api", "api.Dockerfile", "api.dockerfile", "Containerfile"):
            self.assertTrue(docker.is_dockerfile(name), name)
        for name in ("dockerfile", "Dockerfiles", "x/Dockerfile.y/z", "Containerfile.x", "DockerfileX"):
            self.assertFalse(docker.is_dockerfile(name), name)

    def test_compose_names(self) -> None:
        for name in ("compose.yaml", "compose.yml", "compose.dev.yaml", "docker-compose.yml",
                     "docker-compose.yaml", "docker-compose.prod.yml", "docker-compose.x.yaml"):
            self.assertTrue(docker.is_compose(name), name)
        for name in ("Compose.yml", "docker-compose.json", "my-compose.yml", "compose.yml.bak", "compose"):
            self.assertFalse(docker.is_compose(name), name)


if __name__ == "__main__":
    unittest.main()
