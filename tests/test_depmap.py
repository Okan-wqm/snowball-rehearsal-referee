"""``status.depmap`` (run with test 42, the generated views): the dependency drawings are generated from code, and
the brain's committed drawing is the one its code gives today.

- the brain: the committed ``docs/map/brain.md`` equals what ``referee/`` gives now (a stale drawing is red); every
  import form names the module the rules say (``import a.b``, ``from a import b`` as a submodule or as a name,
  relative levels, a function-local import, an import of no module under the root, a relative import above the
  top); ``tests/``, hidden directories and ``__pycache__`` are not read; a file that does not parse is listed;
- live: the roots are the modules a workflow starts with ``python -m``/``python3 -m``, a started module that is
  not under the root is external, live is reachability by imports plus the packages holding a live module;
- the register of the off-live: the brain's ``status/off_live.json`` has no problem; each problem
  (``off_live_unnamed``, ``named_but_live``, ``named_unknown``, ``entry_invalid``, ``register_unreadable``) on a
  tree made for it, an empty package (docstring only) not named and one with code named; the drawing's last column;
- the target: projects from the root's npm workspaces (globs, ``**``, negation), Nx ``project.json``, every Cargo
  ``[package]`` (an excluded one too; a virtual manifest is none) and ``pyproject.toml``; ``SKIP_DIRS`` and
  symbolic links not entered; arrows ``npm``, ``cargo`` (``path``, ``workspace = true``, ``[patch.crates-io]``,
  each through the workspace root Cargo finds: ``Cargo`` below), ``import`` (relative, bare workspace name and
  subpath, tsconfig alias exact and wildcard with ``baseUrl``, a commented tsconfig) and ``python``; the deepest
  project owns a file; the coverage counts each specifier's outcome and the Python files in no project;
- ``sys.path`` (``SysPath``): a directory a Python file inserts becomes a ``path`` box when no manifest's project
  holds it (nested ones both, a missing one none, one inside a project none), an import through it draws
  ``sys.path`` (a module file or a directory, before a ``pyproject.toml`` package), the coverage's ``sys_path`` and
  the drawing's line; ``RootPackages``: a package or namespace directory an import reaches through the root's
  insertion becomes a ``path`` box (a module file at the root, a directory a project holds: none), Python's finder
  order in ``sys_path_target`` (package, module, then namespace);
- ``TsConfig``: a directory holding a file ``jsimports.TSCONFIG`` names (``tsconfig.json``, ``tsconfig.<x>.json``;
  near names not) that no manifest's project holds is a ``tsconfig`` box (nested ones both, one inside a ``path``
  box too; one inside a manifest's project, the root and ``SKIP_DIRS`` none), alias and relative imports into it draw arrows, and the drawing's line;
- ``Docker``: a compose file's builds (a context relative to the compose file, ``.`` and ``Dockerfile`` by default,
  a pair named twice read once, unresolved: ``$``, ``/``, ``://``, leaving the root, a value not a string; missing: no such directory or
  file; a YAML file of another name not read), a directory holding a Dockerfile that no box holds is a ``docker``
  box (not the root, not inside a ``tsconfig`` box), each context source reaching the project holding its path and
  every project inside a directory (a glob segment by segment, ``.``, no arrow to itself, none from the root's),
  sources of a stage, a heredoc, a remote, a variable, leaving the context or matching nothing draw nothing, a
  Dockerfile built with two contexts resolved in each; the coverage (a Dockerfile not built stays in
  ``unread_code_files``) and the drawing's lines; ``WorkflowBuilds``: the same over GitHub Actions files (the files
  read, the file from the root, the matrix, the reasons, a file not read, a Dockerfile built with two contexts);
- the kinds of a file (``FileKinds``): ``file_kind``'s order (read, code by ``CODE_FILE_NAMES`` then by
  ``OTHER_CODE_EXTENSIONS``, ``NOT_CODE_EXTENSIONS``, unclassified, no extension), case as written, near names and
  a leading dot; the lists disjoint; ``unclassified_files`` and ``files_without_extension`` counted with three
  examples (a skipped directory not seen) and the drawing's line;
- the unread manifests: counted by the first ``MANIFESTS_NOT_READ`` pattern a file's name matches (case-sensitive,
  the name only, a near name not counted), a ``package.json`` outside the npm workspace projects (an Nx project's,
  an unparsed workspace's) counted and the root's not, ``SKIP_DIRS`` not entered; three examples in path order and
  the drawing's line;
- reading (``Reads``): ``_reads`` gives every file's ``_read`` in the files' order (one not UTF-8 and one missing
  ``None``), past ``READ_AHEAD`` files, never more than ``READ_AHEAD`` reads ahead of the file taken, on
  ``READERS`` threads at once;
- the helpers: segment globs (the tsconfig dialect and the aliases are profile.jsimports's, test_profile_jsimports);
- the command line: exits 0, 1 (``check`` with a problem) and 2.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from typing import Any

REFEREE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BRAIN = os.path.dirname(REFEREE)
sys.path.insert(0, REFEREE)

from status import depmap as D  # noqa: E402


def write(root: str, files: dict[str, str]) -> None:
    for rel, text in files.items():
        path = os.path.join(root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)


class Brain(unittest.TestCase):
    def test_committed_brain_drawing_is_current(self):
        with open(os.path.join(BRAIN, "docs", "map", "brain.md"), encoding="utf-8") as f:
            committed = f.read()
        self.assertEqual(D.render_brain(D.brain_map(REFEREE)), committed,
                         "docs/map/brain.md is stale: regenerate it with "
                         "'python -m status.depmap brain . > ../docs/map/brain.md' from referee/")

    def tree(self) -> str:
        root = tempfile.mkdtemp()
        write(root, {
            "pkg/__init__.py": "",
            "pkg/a.py": "import pkg.b\nimport os.path\n",
            "pkg/b.py": "from . import c\n",
            "pkg/c.py": "from .d import helper\nimport pkg.c\n",
            "pkg/d.py": "def f():\n    import top\n",
            "pkg/sub/__init__.py": "from .. import a\n",
            "pkg/sub/e.py": "from ..sub import f\nfrom pkg.sub.f import g\n",
            "pkg/sub/f.py": "from pkg import missing_name\n",
            "top.py": "from pkg import a, nothere\nfrom ... import x\n",
            "lone.py": "import json\nif __name__ == '__main__':\n    pass\n",
            "broken.py": "def (:\n",
            "tests/test_x.py": "import pkg.a\n",
            ".hidden/h.py": "import pkg.a\n",
            ".github/workflows/w.yml": "jobs:\n  a:\n    run: |\n      python3 -m pkg.a run\n"
                                       "      python -m outside.mod\n",
        })
        return root

    def test_import_forms(self):
        m = D.brain_map(self.tree())
        self.assertEqual(sorted(m["modules"]), ["broken", "lone", "pkg", "pkg.a", "pkg.b", "pkg.c", "pkg.d",
                                                 "pkg.sub", "pkg.sub.e", "pkg.sub.f", "top"])
        self.assertEqual(m["edges"], {
            "broken": [], "lone": [], "pkg": [],
            "pkg.a": ["pkg.b"],                    # import pkg.b; os.path is not under the root
            "pkg.b": ["pkg.c"],                    # from . import c: a submodule
            "pkg.c": ["pkg.d"],                    # from .d import helper: the module, not the name; itself: none
            "pkg.d": ["top"],                      # inside a function
            "pkg.sub": ["pkg.a"],                  # from .. in a package's __init__
            "pkg.sub.e": ["pkg.sub.f"],            # from ..sub import f; from pkg.sub.f import g
            "pkg.sub.f": ["pkg"],                  # a name of the package
            "top": ["pkg", "pkg.a"],               # a submodule and a name; from ... above the top is nothing
        })
        self.assertEqual(m["unparsed"], ["broken.py"])
        self.assertEqual(m["entry_points"], ["lone"])

    def test_live_roots_and_reachability(self):
        m = D.brain_map(self.tree())
        self.assertEqual(m["roots"], ["pkg.a"])
        self.assertEqual(m["external_roots"], ["outside.mod"])
        # pkg.a -> b -> c -> d -> top -> pkg; pkg is also live as the package holding pkg.a
        self.assertEqual(m["live"], ["pkg", "pkg.a", "pkg.b", "pkg.c", "pkg.d", "top"])
        self.assertEqual(m["off_live"], ["broken", "lone", "pkg.sub", "pkg.sub.e", "pkg.sub.f"])

    def test_package_of_a_live_module_is_live_without_an_arrow(self):
        root = tempfile.mkdtemp()
        write(root, {"p/__init__.py": "", "p/q/__init__.py": "", "p/q/r.py": "",
                     ".github/workflows/w.yaml": "run: python -m p.q.r\n"})
        m = D.brain_map(root)
        self.assertEqual(m["live"], ["p", "p.q", "p.q.r"])
        self.assertEqual(m["edges"], {"p": [], "p.q": [], "p.q.r": []})

    def test_drawing_marks_roots_and_lists_every_module(self):
        text = D.render_brain(D.brain_map(self.tree()), "a tree")
        self.assertIn("```mermaid", text)
        self.assertIn('[["pkg.a"]]', text)          # the root's double border
        self.assertIn("outside.mod", text)
        self.assertIn("broken.py", text)
        for line in ("| pkg.a | pkg/a.py | root |  | pkg.b | pkg.sub, top |  |",
                     "| lone | lone.py | no | yes |  |  |  |",
                     "| top | top.py | yes |  | pkg, pkg.a | pkg.d |  |"):
            self.assertIn(line, text)


class Register(unittest.TestCase):
    """The register of the off-live (``status/off_live.json``): every module off the live path is named with its
    reason, a named module is not live, and an empty package is not named."""

    def test_the_brains_register_has_no_problem(self):
        m = D.brain_map(REFEREE)
        self.assertEqual(D.register_problems(m), [])
        self.assertTrue(m["off_live"])      # the check is not vacuous today

    def tree(self, register: Any = None, raw: bytes | None = None) -> dict:
        root = tempfile.mkdtemp()
        write(root, {
            "pkg/__init__.py": "",
            "pkg/a.py": "import pkg.b\n",
            "pkg/b.py": "",
            "tool.py": "",
            "doc/__init__.py": '"""Only a docstring."""\n',
            "doc/m.py": "",
            "code/__init__.py": "X = 1\n",
            "code2/__init__.py": '"""A docstring, then code."""\nX = 1\n',
            "num/__init__.py": "1\n",
            "status/__init__.py": "",
            ".github/workflows/w.yml": "run: python -m pkg.a\n",
        })
        if raw is not None or register is not None:
            with open(os.path.join(root, "status", "off_live.json"), "wb") as f:
                f.write(raw if raw is not None else json.dumps(register).encode())
        return D.brain_map(root)

    OK = {"kind": "unwired", "why": "waits for its caller"}

    def test_off_live_modules_must_be_named_and_empty_packages_need_not(self):
        m = self.tree()
        self.assertEqual(m["empty_packages"], ["doc", "pkg", "status"])
        self.assertEqual(m["off_live"], ["code", "code2", "doc", "doc.m", "num", "status", "tool"])
        # absent file: an empty register; doc and status are empty packages; code, code2 (a docstring and code)
        # and num (a constant that is not a string) hold code
        self.assertEqual(D.register_problems(m), ["off_live_unnamed:code", "off_live_unnamed:code2",
                                                  "off_live_unnamed:doc.m", "off_live_unnamed:num",
                                                  "off_live_unnamed:tool"])
        named = {"code": self.OK, "code2": self.OK, "doc.m": self.OK, "num": self.OK,
                 "tool": {"kind": "session_tool", "why": "run by hand"}}
        self.assertEqual(D.register_problems(self.tree(named)), [])
        for missing in named:
            self.assertEqual(D.register_problems(self.tree({k: v for k, v in named.items() if k != missing})),
                             ["off_live_unnamed:%s" % missing])

    def test_named_but_live_unknown_and_empty_package(self):
        base = {"code": self.OK, "code2": self.OK, "doc.m": self.OK, "num": self.OK, "tool": self.OK}
        for name, problem in (("pkg.a", "named_but_live:pkg.a"), ("pkg.b", "named_but_live:pkg.b"),
                              ("pkg", "named_unknown:pkg"), ("gone", "named_unknown:gone"),
                              ("doc", "named_unknown:doc"), ("status", "named_unknown:status")):
            self.assertEqual(D.register_problems(self.tree(dict(base, **{name: self.OK}))), [problem], name)

    def test_entry_shape(self):
        base = {"code": self.OK, "code2": self.OK, "doc.m": self.OK, "num": self.OK}
        for entry in ("unwired", None, {"kind": "unwired"}, {"why": "x"}, dict(self.OK, extra=1),
                      {"kind": "package", "why": "x"}, {"kind": "Unwired", "why": "x"}, {"kind": "unwired", "why": ""},
                      {"kind": "unwired", "why": " \n\t"}, {"kind": "unwired", "why": 3}, {"kind": 1, "why": "x"}):
            self.assertEqual(D.register_problems(self.tree(dict(base, tool=entry))), ["entry_invalid:tool"], entry)
        # an invalid entry for a live or unknown name is reported twice, sorted
        self.assertEqual(D.register_problems(self.tree(dict(base, tool=self.OK, **{"pkg.a": None}))),
                         ["entry_invalid:pkg.a", "named_but_live:pkg.a"])

    def test_unreadable_register_stops_the_check(self):
        for raw in (b"[]", b"{", b"\xff\xfe", b"null", b'"x"', b"[" * 100000):
            self.assertEqual(D.register_problems(self.tree(raw=raw)), ["register_unreadable"], raw[:8])

    def test_drawing_shows_each_reason(self):
        m = self.tree({"code": self.OK, "code2": self.OK, "num": self.OK,
                       "doc.m": {"kind": "unwired", "why": "a | b\nc"},
                       "tool": {"kind": "session_tool", "why": "by hand"}})
        text = D.render_brain(m, "a tree")
        self.assertIn("Register problems: none.", text)
        for line in ("| tool | tool.py | no |  |  |  | session_tool: by hand |",
                     "| doc.m | doc/m.py | no |  |  |  | unwired: a \\| b c |",
                     "| doc | doc/__init__.py | no |  |  |  | empty package |",
                     "| pkg | pkg/__init__.py | yes |  |  |  |  |"):
            self.assertIn(line, text)
        self.assertIn("Register problems: off_live_unnamed:code, off_live_unnamed:code2, off_live_unnamed:doc.m, "
                      "off_live_unnamed:num, off_live_unnamed:tool.",
                      D.render_brain(self.tree(), "a tree"))


class Target(unittest.TestCase):
    def checkout(self) -> str:
        root = tempfile.mkdtemp()
        write(root, {
            "package.json": json.dumps({"workspaces": ["apps/*", "libs/**", "!libs/skip"]}),
            "apps/web/package.json": json.dumps({"name": "@t/web", "dependencies": {"@t/ui": "*", "react": "1"},
                                                 "devDependencies": {"x": "*"}}),
            "apps/web/src/main.ts": "\n".join([
                "import { u } from '@t/util';",
                'export * from "@t/feat/a";',
                "const y = require('../../../libs/deep/x/i');",
                "const r = import('react');",
                "import './local';",
                "import { b } from '@t/ui/button';",
                "import { z } from '@t/web-old';",
                "// import { c } from '@t/ui';",
                "const doc = \"import { d } from '@t/ui'\";",
                "import { gone } from '../../../../outside';",
                "import { s } from '../../../scripts/s';",
                ""]),
            "apps/web/src/local.ts": "export const l = 1;\n",
            "apps/web/project.json": json.dumps({"name": "web-nx"}),
            "apps/web/node_modules/q/index.js": "require('@t/ui')\n",
            "apps/web/dist/out.js": "require('@t/ui')\n",
            "libs/ui/package.json": json.dumps({"name": "@t/ui"}),
            "libs/ui/index.js": "module.exports = require('@t/web');\n",
            "libs/skip/package.json": json.dumps({"name": "skip"}),
            "libs/deep/x/package.json": json.dumps({"name": "x"}),
            "libs/deep/x/i.js": "",
            "libs/util/project.json": json.dumps({}),
            "libs/feat/a/project.json": json.dumps({"name": "feat-a"}),
            "libs/feat/a/src/inner/project.json": json.dumps({"name": "feat-a-inner"}),
            "tsconfig.base.json": "{\n  // aliases\n  \"compilerOptions\": {\n    \"baseUrl\": \".\",\n"
                                  "    /* the paths */\n    \"paths\": {\n"
                                  "      \"@t/util\": [\"libs/util/src/index.ts\"],\n"
                                  "      \"@t/feat/*\": [\"libs/feat/*/src\"],\n"
                                  "      \"@t/web-old\": [\"https://example.invalid/x\"],\n"
                                  "    },\n  },\n}\n",
            "scripts/s.ts": "import { u } from '@t/util';\n",
            "Cargo.toml": "[workspace]\nmembers = [\"crates/*\"]\nexclude = [\"crates/ex\"]\n"
                          "[workspace.dependencies]\nb = { path = \"crates/b\" }\nserde = \"1\"\n",
            "crates/a/Cargo.toml": "[package]\nname = \"a\"\n[dependencies]\nb = { path = \"../b\" }\nserde = \"1\"\n",
            "crates/b/Cargo.toml": "[package]\nname = \"b\"\n",
            "crates/c/Cargo.toml": "[package]\nname = \"c\"\n[target.'cfg(unix)'.dev-dependencies]\n"
                                   "b = { workspace = true }\n",
            "crates/ex/Cargo.toml": "[package]\nname = \"ex\"\n[dependencies]\nb = { path = \"../b\" }\n",
            "py/pyproject.toml": "[project]\nname = \"pyk\"\n",
            "py/src/pyk/__init__.py": "",
            "py/pyk2/__init__.py": "from pyk import core\nfrom . import rel\n",
            "libs/util/tool.py": "import pyk2.mod\nimport os\n",
            "scripts/run.py": "from pyk import z\n",
            "scripts/bad.py": "def (:\n",
            "scripts/run.sh": "echo\n",
            "crates/a/src/lib.rs": "",
            "tools/x.rs": "",
            "infra/main.tf": "module \"m\" { source = \"./m\" }\n",
            "db/001_init.sql": "create table t (id int);\n",
            "api/schema.graphql": "type T { id: ID }\n",
            "infra/README.md": "",
            "web/site.css": "",
            "ci.yaml": "",
            "Dockerfile": "FROM scratch\n",
        })
        os.symlink(os.path.join(root, "libs", "ui"), os.path.join(root, "libs", "link"))
        return root

    def test_projects(self):
        m = D.target_map(self.checkout())
        self.assertEqual([(p["dir"], p["name"], p["kinds"]) for p in m["projects"]], [
            ("apps/web", "@t/web", ["npm", "nx"]),
            ("crates/a", "a", ["cargo"]),
            ("crates/b", "b", ["cargo"]),
            ("crates/c", "c", ["cargo"]),
            ("crates/ex", "ex", ["cargo"]),             # excluded from the workspace, still a package
            ("libs/deep/x", "x", ["npm"]),              # ** reaches it
            ("libs/feat/a", "feat-a", ["nx"]),
            ("libs/feat/a/src/inner", "feat-a-inner", ["nx"]),
            ("libs/ui", "@t/ui", ["npm"]),              # libs/skip negated, libs/link a symbolic link
            ("libs/util", "util", ["nx"]),              # no name: the directory's last segment
            ("py", "pyk", ["python"]),
        ])

    def test_edges(self):
        m = D.target_map(self.checkout())
        self.assertEqual([(e["from"], e["to"], e["kinds"]) for e in m["edges"]], [
            ("apps/web", "libs/deep/x", ["import", "npm"]),  # a relative path; and devDependencies names x
            ("apps/web", "libs/feat/a", ["import"]),        # wildcard alias; the deepest project is feat/a
            ("apps/web", "libs/ui", ["import", "npm"]),     # manifest and a bare subpath import
            ("apps/web", "libs/util", ["import"]),          # exact alias, baseUrl
            ("crates/a", "crates/b", ["cargo"]),            # path
            ("crates/c", "crates/b", ["cargo"]),            # workspace = true, in a [target.*] table
            ("crates/ex", "crates/b", ["cargo"]),           # path, from a package that is its own root
            ("libs/ui", "apps/web", ["import"]),            # require of a workspace name
            ("libs/util", "py", ["python"]),                # pyk2 is a package of py (no src/)
        ])

    def test_coverage(self):
        cov = D.target_map(self.checkout())["coverage"]
        self.assertEqual(cov["projects_by_kind"], {"npm": 3, "nx": 4, "cargo": 4, "python": 1, "tsconfig": 0,
                                                   "path": 0, "docker": 0, "kustomize": 0})
        self.assertEqual(cov["source_files"], 5)       # main, local, libs/ui, i.js, scripts/s.ts; not dist, node_modules
        self.assertEqual(cov["source_files_outside_projects"], 1)
        self.assertEqual(cov["python_files"], 4)
        self.assertEqual(cov["python_files_outside_projects"], 1)  # scripts/run.py; bad.py is not parsed
        self.assertEqual(cov["python_files_unparsed"], 1)
        self.assertEqual(cov["unread_manifests"], {"package.json": {"count": 1, "examples": ["libs/skip/package.json"]}})
        self.assertEqual(cov["specifiers"], {
            "cross_project": 6,       # util, feat/a, deep/x, ui/button (main.ts); @t/web (ui); pyk2 (tool.py)
            "same_project": 2,        # ./local; pyk2's from pyk import core
            "external_package": 1,    # react
            "outside_projects": 4,    # @t/web-old (an alias to no project; the commented and quoted @t/ui are
                                      # not imports, jsimports.specifiers), main.ts into
                                      # scripts/, scripts/s.ts's import, scripts/run.py's pyk
            "leaves_root": 1,         # ../../../../outside
            "python_external": 1,     # os
            "python_relative": 1,     # from . import rel
        })
        # Terraform, SQL, GraphQL and a Dockerfile (by name) are code; Markdown, CSS and YAML are not
        self.assertEqual(cov["unread_code_files"],
                         {".graphql": 1, ".rs": 2, ".sh": 1, ".sql": 1, ".tf": 1, "Dockerfile": 1})
        self.assertEqual(cov["unread_code_files_outside_projects"],  # tools/x.rs, run.sh, infra/, db/, api/, Dockerfile
                         {".graphql": 1, ".rs": 1, ".sh": 1, ".sql": 1, ".tf": 1, "Dockerfile": 1})
        self.assertEqual(cov["unclassified_files"], {})
        self.assertEqual(cov["files_without_extension"], {"count": 0, "examples": []})

    def test_render_lists_every_project_and_arrow(self):
        text = D.render_target(D.target_map(self.checkout()), "a test checkout")
        self.assertIn("a test checkout", text)
        self.assertIn("| @t/web | apps/web | npm nx | x (import npm), feat-a (import), @t/ui (import npm), util (import) |",
                      text)
        self.assertEqual(text.count(" -->|"), 9)
        self.assertIn("SQL, GraphQL, protobuf, jq): .graphql 1 (1 in no project), .rs 2 (1 in no project), "
                      ".sh 1 (1 in no project), .sql 1 (1 in no project), .tf 1 (1 in no project), "
                      "Dockerfile 1 (1 in no project).", text)
        self.assertIn("`NOT_CODE_EXTENSIONS`): none; files with no extension and no `CODE_FILE_NAMES` name: none.",
                      text)
        self.assertIn("Python files read 4 (1 outside any project, 1 not parsed).", text)
        self.assertIn("workspaces): package.json 1 (libs/skip/package.json).", text)


class SysPath(unittest.TestCase):
    """A directory a Python file puts on ``sys.path`` (``profile.pypath``): a box of kind ``path`` when no manifest's
    project holds it, decided against those projects only; an import of a name an inserted directory of the same
    file holds resolves there (before a ``pyproject.toml`` package of the same name) and draws ``sys.path``."""

    HEAD = "import os\nimport sys\nfrom pathlib import Path\n"

    def checkout(self, extra: dict[str, str] | None = None) -> str:
        root = tempfile.mkdtemp()
        h = self.HEAD
        write(root, {
            "aria/pyproject.toml": "[project]\nname = \"aria\"\n",
            "aria/aria_k/__init__.py": "",
            "aria/tests/test_a.py": h + "_ROOT = Path(__file__).resolve().parents[2]\n"
                                    "sys.path.insert(0, str(_ROOT / 'tools' / 'poc'))\n"
                                    "import poc_mod\nimport aria_k\nimport json\n",
            "aria/tests/conf.py": h + "sys.path.insert(0, str(Path(__file__).parent))\nimport helper\n",
            "aria/tests/helper.py": "",
            "tools/poc/poc_mod.py": h + "sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'aria'))\n"
                                    "import aria_k.core\n",
            "tools/poc/sub/x.py": "import json\n",
            "tools/other/y.py": h + "sys.path.insert(0, str(Path(__file__).parent.parent))\nimport poc\n",
            "scripts/s.py": h + "sys.path.append(os.path.join(os.path.dirname(__file__), 'gone'))\n"
                                "sys.path.insert(0, os.getcwd())\n",
            "scripts/r.py": h + "sys.path.insert(0, str(Path(__file__).parents[1]))\nimport tools\n",
            "scripts/l.py": h + "sys.path.insert(0, str(Path(__file__).parents[5]))\n",
            **(extra or {}),
        })
        return root

    def test_boxes_and_arrows(self):
        m = D.target_map(self.checkout())
        self.assertEqual([(p["dir"], p["name"], p["kinds"]) for p in m["projects"]], [
            ("aria", "aria", ["python"]),
            ("tools", "tools", ["path"]),          # y.py's parent.parent; nested boxes do not hide each other
            ("tools/poc", "tools/poc", ["path"]),  # test_a.py's insertion; aria/tests is inside aria: no box
        ])
        self.assertEqual([(e["from"], e["to"], e["kinds"]) for e in m["edges"]], [
            ("aria", "tools/poc", ["sys.path"]),   # import poc_mod through tools/poc
            ("tools", "tools/poc", ["sys.path"]),  # import poc: a directory in an inserted directory
            ("tools/poc", "aria", ["sys.path"]),   # import aria_k.core through aria
        ])

    def test_coverage(self):
        cov = D.target_map(self.checkout())["coverage"]
        self.assertEqual(cov["sys_path"], {
            "calls": 8, "dirs": 6, "missing": 1, "leaves_root": 1, "unresolved": 1,
            "imports": 5,   # poc_mod, helper, aria_k.core, poc, tools (r.py: into the root's tools box)
            "unresolved_files": {"count": 1, "examples": ["scripts/s.py"]}})
        self.assertEqual(cov["projects_by_kind"]["path"], 2)
        self.assertEqual(cov["python_files_outside_projects"], 3)  # scripts/*.py; tools/** now in boxes
        sp = cov["specifiers"]
        self.assertEqual((sp["cross_project"], sp["same_project"], sp["outside_projects"]), (3, 2, 1))
        self.assertEqual(sp["python_external"], 23)  # os, sys and pathlib in 7 files, json in 2: in no inserted dir

    def test_an_inserted_directory_wins_over_a_package_and_a_missing_name_falls_through(self):
        m = D.target_map(self.checkout({"tools/poc/aria_k.py": ""}))
        edges = [(e["from"], e["to"], e["kinds"]) for e in m["edges"]]
        self.assertIn(("aria", "tools/poc", ["sys.path"]), edges)
        self.assertEqual(m["coverage"]["specifiers"]["same_project"], 1)  # aria_k now resolves in tools/poc

    def test_render(self):
        text = D.render_target(D.target_map(self.checkout()), "x")
        self.assertIn("Projects 3 (npm 0, nx 0, cargo 0, python 1, tsconfig 0, path 2, docker 0, kustomize 0), arrows 3.", text)
        self.assertIn("`sys.path` insertions in Python files: 8 calls; 6 directories resolved (1 not in the "
                      "checkout), 1 leaving the root, 1 calls or values not resolved (1 files: scripts/s.py); "
                      "5 imports resolved through them.", text)
        self.assertIn("| aria | aria | python | tools/poc (sys.path) |", text)
        self.assertIn("| tools/poc | tools/poc | path | aria (sys.path) |", text)


class RootPackages(unittest.TestCase):
    """A directory an import reaches through an inserted directory (``sys_path_target``, Python's finder order:
    package, then module, in the first directory holding one; else the first namespace directory) is a ``path``
    box when no project holds it, which only the root's insertion can give: the top-level packages."""

    HEAD = "import sys\nfrom pathlib import Path\nsys.path.insert(0, str(Path(__file__).resolve().parents[1]))\n"

    def checkout(self) -> str:
        root = tempfile.mkdtemp()
        write(root, {
            "app/pyproject.toml": "[project]\nname = \"app\"\n",
            "app/main.py": self.HEAD + "import tools.shared.x\nimport ns.a\nimport mod\nimport pkg\nimport both\n"
                                       "import lib\nimport app_k\nimport json\n",
            "app/app_k/__init__.py": "",
            "lib/pyproject.toml": "[project]\nname = \"lib\"\n",
            "lib/lib/__init__.py": "",
            "tools/__init__.py": "",
            "tools/shared/x.py": "import tools.shared\n",
            "tools/run.sh": "echo\n",
            "tools/poc/p.py": "",
            "ns/a.py": "",                  # a namespace package: a directory without __init__.py
            "mod.py": "",                   # a module file at the root: no box
            "pkg.py": "", "pkg/b.py": "",   # a module beats a namespace directory of the same name
            "both.py": "", "both/__init__.py": "",  # a package beats a module of the same name
            "other/o.py": "import sys\nsys.path.insert(0, '/abs')\nimport other\n",
            "scripts/s.py": "import sys\nfrom pathlib import Path\n"
                            "sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools' / 'poc'))\n",
        })
        return root

    def test_boxes_and_arrows(self):
        m = D.target_map(self.checkout())
        self.assertEqual([(p["dir"], p["kinds"]) for p in m["projects"]], [
            ("app", ["python"]), ("both", ["path"]), ("lib", ["python"]), ("ns", ["path"]), ("tools", ["path"]),
            ("tools/poc", ["path"]),  # s.py's insertion; the nested box stays its own
        ])
        self.assertEqual([(e["from"], e["to"], e["kinds"]) for e in m["edges"]], [
            ("app", "both", ["sys.path"]), ("app", "lib", ["sys.path"]), ("app", "ns", ["sys.path"]),
            ("app", "tools", ["sys.path"]),
        ])

    def test_files_join_the_box_and_the_rest_is_counted(self):
        cov = D.target_map(self.checkout())["coverage"]
        # tools/shared/x.py and tools/poc/p.py are in boxes; mod.py, pkg.py, pkg/b.py, both.py (both/ is the box,
        # not the module beside it), other/o.py and scripts/s.py are not
        self.assertEqual(cov["python_files_outside_projects"], 6)
        self.assertEqual(cov["sys_path"]["imports"], 6)  # tools, ns, mod, pkg, both, lib; not app_k, json, sys, pathlib
        sp = cov["specifiers"]
        # across: tools, ns, both, lib; outside: mod and pkg (module files at the root); inside: app_k, app's own
        # pyproject package (tools/shared/x.py's tools.shared, with no insertion, is no project's package)
        self.assertEqual((sp["cross_project"], sp["outside_projects"], sp["same_project"]), (4, 2, 1))

    def test_render(self):
        text = D.render_target(D.target_map(self.checkout()), "x")
        self.assertIn("Projects 6 (npm 0, nx 0, cargo 0, python 2, tsconfig 0, path 4, docker 0, kustomize 0), arrows 4.", text)
        self.assertIn("| app | app | python | both (sys.path), lib (sys.path), ns (sys.path), tools (sys.path) |", text)

    def test_finder_order(self):
        files = {"a/t/__init__.py", "a/t.py", "b/t.py", "c/t/x.py", "d/u.py"}
        dirs = {"a", "a/t", "b", "c", "c/t", "d"}
        self.assertEqual(D.sys_path_target("t", ["a", "b"], files, dirs), "a/t")      # package before module
        self.assertEqual(D.sys_path_target("t", ["b", "a"], files, dirs), "b/t.py")   # the first directory
        self.assertEqual(D.sys_path_target("t", ["c", "b"], files, dirs), "b/t.py")   # namespace last
        self.assertEqual(D.sys_path_target("t", ["d", "c"], files, dirs), "c/t")
        self.assertIsNone(D.sys_path_target("t", ["d"], files, dirs))
        self.assertEqual(D.sys_path_target("u", ["", "d"], {"u/__init__.py", "d/u.py"}, {"", "u", "d"}), "u")


class TsConfig(unittest.TestCase):
    """A directory holding a TypeScript configuration that no manifest's project holds is a ``tsconfig`` box."""

    def checkout(self) -> str:
        root = tempfile.mkdtemp()
        write(root, {
            "package.json": json.dumps({"workspaces": ["apps/*"]}),
            "tsconfig.base.json": json.dumps({"compilerOptions": {"paths": {"@t/cqrs": ["libs/cqrs/src/index.ts"]}}}),
            "apps/web/package.json": json.dumps({"name": "@t/web"}),
            "apps/web/tsconfig.app.json": "{}",                # inside a manifest's project: no box
            "apps/web/src/sub/tsconfig.json": "{}",            # inside one, deeper: no box either
            "apps/web/src/main.ts": "import { bus } from '@t/cqrs';\nimport { e } from '../../../e2e/suite/x';\n",
            "libs/cqrs/tsconfig.lib.json": "{}",               # only a tsconfig.<x>.json: a box
            "libs/cqrs/src/index.ts": "export * from './bus';\n",
            "libs/cqrs/src/bus.ts": "export const bus = 1;\n",
            "e2e/suite/tsconfig.json": "{}",                   # a test suite: a box
            "e2e/suite/x.ts": "import { bus } from '@t/cqrs';\n",
            "e2e/suite/inner/tsconfig.spec.json": "{}",        # nested in a tsconfig box: a box too
            "e2e/suite/inner/y.ts": "import { x } from '../x';\n",
            "tools/tsconfig-old.json": "{}",                   # near names are not a TypeScript configuration
            "tools/tsconfig.json.bak": "{}",
            "tools/xtsconfig.json": "{}",
            "tools/t.ts": "import { bus } from '@t/cqrs';\n",
            "apps/web/node_modules/m/tsconfig.json": "{}",     # SKIP_DIRS not entered
            "py/pyproject.toml": "[project]\nname = \"p\"\n",
            "py/tsconfig.json": "{}",                          # a Python project's directory: the manifest's box
            "pyt/run.py": "import sys\nfrom pathlib import Path\nsys.path.insert(0, str(Path(__file__).parent))\n",
            "pyt/lint/tsconfig.json": "{}",                    # inside a sys.path box (not a manifest's): a box
            "pyt/lint/rule.ts": "import { x } from '../../e2e/suite/x';\n",
        })
        return root

    def test_boxes_and_arrows(self):
        m = D.target_map(self.checkout())
        self.assertEqual([(p["dir"], p["name"], p["kinds"]) for p in m["projects"]], [
            ("apps/web", "@t/web", ["npm"]),
            ("e2e/suite", "e2e/suite", ["tsconfig"]),
            ("e2e/suite/inner", "e2e/suite/inner", ["tsconfig"]),
            ("libs/cqrs", "libs/cqrs", ["tsconfig"]),
            ("py", "p", ["python"]),
            ("pyt", "pyt", ["path"]),
            ("pyt/lint", "pyt/lint", ["tsconfig"]),
        ])
        self.assertEqual([(e["from"], e["to"], e["kinds"]) for e in m["edges"]], [
            ("apps/web", "e2e/suite", ["import"]),
            ("apps/web", "libs/cqrs", ["import"]),
            ("e2e/suite", "libs/cqrs", ["import"]),
            ("e2e/suite/inner", "e2e/suite", ["import"]),
            ("pyt/lint", "e2e/suite", ["import"]),
        ])

    def test_coverage(self):
        cov = D.target_map(self.checkout())["coverage"]
        self.assertEqual(cov["projects_by_kind"], {"npm": 1, "nx": 0, "cargo": 0, "python": 1, "tsconfig": 4,
                                                   "path": 1, "docker": 0, "kustomize": 0})
        self.assertEqual(cov["source_files_outside_projects"], 1)              # tools/t.ts
        self.assertEqual(cov["specifiers"]["outside_projects"], 1)             # its import
        self.assertEqual(cov["specifiers"]["cross_project"], 5)
        self.assertEqual(cov["specifiers"]["same_project"], 1)                 # index.ts's ./bus

    def test_render(self):
        text = D.render_target(D.target_map(self.checkout()), "x")
        self.assertIn("Projects 7 (npm 1, nx 0, cargo 0, python 1, tsconfig 4, path 1, docker 0, kustomize 0), arrows 5.", text)
        self.assertIn("of kind `tsconfig`: a directory holding a TypeScript configuration that no such project holds",
                      text)
        self.assertIn("| libs/cqrs | libs/cqrs | tsconfig |  |", text)

    def test_the_name_rule(self):
        from profile import jsimports as J
        for name in ("tsconfig.json", "tsconfig.lib.json", "tsconfig.base.json", "tsconfig.app.spec.json"):
            self.assertIsNotNone(J.TSCONFIG.fullmatch(name), name)
        for name in ("tsconfig-old.json", "tsconfig.json.bak", "xtsconfig.json", "tsconfig.jsonc", "jsconfig.json"):
            self.assertIsNone(J.TSCONFIG.fullmatch(name), name)


class Docker(unittest.TestCase):
    """``docker_edges``: a compose file's builds, each Dockerfile's context sources, the ``docker`` boxes and arrows,
    the coverage and the drawing's line (the reader's own rules: test_profile_docker)."""

    COMPOSE = ("services:\n"
               "  api:\n    build:\n      context: .\n      dockerfile: apps/api/Dockerfile\n"
               "  web:\n    build:\n      context: .\n      dockerfile: infra/docker/Dockerfile.web\n"
               "  web2:\n    build:\n      context: .\n      dockerfile: infra/docker/Dockerfile.web\n"
               "  tool:\n    build:\n      dockerfile: Dockerfile.tool\n"
               "  img:\n    build: ./tools/img\n"
               "  var:\n    build:\n      context: ${CTX}\n"
               "  abs:\n    build: /srv/x\n"
               "  num:\n    build: 7\n"
               "  remote:\n    build: https://example.invalid/a/b.git\n"
               "  up:\n    build: ../elsewhere\n"
               "  gone:\n    build: ./nothing\n"
               "  nofile:\n    build:\n      context: apps/web\n"
               "  ghost:\n    build:\n      context: nothing\n      dockerfile: ../Dockerfile.tool\n")

    def checkout(self) -> str:
        root = tempfile.mkdtemp()
        write(root, {
            "package.json": json.dumps({"workspaces": ["apps/*", "libs/*"]}),
            "apps/api/package.json": json.dumps({"name": "@t/api"}),
            "apps/api/Dockerfile": "FROM x\nCOPY /libs/core ./x\nCOPY apps/web/package.json /w\n",  # from its project
            "apps/web/package.json": json.dumps({"name": "@t/web"}),
            "libs/core/package.json": json.dumps({"name": "@t/core"}),
            "libs/core/deep/project.json": json.dumps({"name": "core-deep"}),
            "infra/docker/Dockerfile.web": ("FROM x AS b\n"
                                            "COPY apps/w*b ../outside missing/ $X/y https://e.invalid/x /dest/\n"
                                            "COPY --from=b libs/core /y\n"
                                            "COPY <<EOF /z\nCOPY apps/api /no\nEOF\n"
                                            "COPY onlyone\n"),
            "infra/docker/Dockerfile.unbuilt": "COPY apps/api /a\n",       # no build: not read
            "infra/docker/Dockerfile.rel": "COPY lib ../libs/core /l\n",  # the context is infra/
            "infra/docker/nginx.conf": "",
            "infra/compose/compose.yaml": "services:\n  r:\n    build:\n      context: ..\n"
                                          "      dockerfile: docker/Dockerfile.rel\n",
            "infra/lib/project.json": json.dumps({"name": "infra-lib"}),
            "Dockerfile.tool": "COPY libs/core /t\n",                       # the root's: no box, no arrow
            "tools/img/Dockerfile": "COPY . /app\n",
            "tools/img/sub/project.json": json.dumps({"name": "img-sub"}),
            "ts/tsconfig.json": "{}",                                      # a tsconfig box holds it: no docker box
            "ts/Dockerfile": "COPY libs/core /x\n",
            "ci/pipeline.yml": "build:\n  context: .\n  dockerfile: infra/docker/Dockerfile.unbuilt\n",
            "docker-compose.yml": self.COMPOSE,
        })
        return root

    def test_boxes_and_arrows(self):
        m = D.target_map(self.checkout())
        self.assertEqual([(p["dir"], p["kinds"]) for p in m["projects"]], [
            ("apps/api", ["npm"]), ("apps/web", ["npm"]), ("infra/docker", ["docker"]), ("infra/lib", ["nx"]),
            ("libs/core", ["npm"]), ("libs/core/deep", ["nx"]), ("tools/img", ["docker"]),
            ("tools/img/sub", ["nx"]), ("ts", ["tsconfig"])])
        self.assertEqual([(e["from"], e["to"], e["kinds"]) for e in m["edges"]], [
            ("apps/api", "apps/web", ["docker"]),           # a file: the project holding it
            ("apps/api", "libs/core", ["docker"]),          # a directory: its own project
            ("apps/api", "libs/core/deep", ["docker"]),     # and every project inside it
            ("infra/docker", "apps/web", ["docker"]),       # a glob, segment by segment
            ("infra/docker", "infra/lib", ["docker"]),      # a context relative to its compose file
            ("tools/img", "tools/img/sub", ["docker"]),     # "." is the whole context; no arrow to itself
        ])

    def test_coverage(self):
        cov = D.target_map(self.checkout())["coverage"]
        self.assertEqual(cov["docker"], {
            "dockerfiles": 7, "compose_files": 2, "compose_unreadable": {"count": 0, "examples": []}, "builds": 14, "builds_unresolved": 5, "builds_missing": 3,
            "dockerfiles_built": 5,
            "dockerfiles_not_built": {"count": 2, "examples": ["infra/docker/Dockerfile.unbuilt", "ts/Dockerfile"]},
            "sources": {"context": 9, "stage": 1, "heredoc": 1, "remote": 1, "variable": 1}, "malformed": 1,
            "context_sources": {"matched": 6, "no_match": 1, "leaves_context": 2},
            "workflows": {"files": 0, "unreadable": {"count": 0, "examples": []}, "steps": 0,
                          "steps_unresolved": {"matrix_dynamic": 0, "context": 0, "function": 0, "operator": 0,
                                               "syntax": 0},
                          "builds": 0, "builds_unresolved": 0, "builds_missing": 0}})
        self.assertEqual(cov["projects_by_kind"]["docker"], 2)
        self.assertEqual(cov["unread_code_files"], {"Dockerfile": 1, "Dockerfile.*": 1})   # the two not built
        self.assertEqual(cov["unread_code_files_outside_projects"], {})

    def test_two_contexts(self):
        root = tempfile.mkdtemp()
        write(root, {"a/project.json": "{}", "b/x/project.json": "{}", "b/a/project.json": "{}",
                     "img/Dockerfile": "COPY a /a\n",
                     "compose.yml": "services:\n  p:\n    build:\n      context: .\n      dockerfile: img/Dockerfile\n"
                                    "  q:\n    build:\n      context: b\n      dockerfile: ../img/Dockerfile\n"})
        m = D.target_map(root)
        self.assertEqual([(e["from"], e["to"]) for e in m["edges"]], [("img", "a"), ("img", "b/a")])
        self.assertEqual(m["coverage"]["docker"]["sources"]["context"], 1)      # read once
        self.assertEqual(m["coverage"]["docker"]["context_sources"]["matched"], 2)  # resolved per context

    def test_render(self):
        text = D.render_target(D.target_map(self.checkout()), "x")
        self.assertIn("Projects 9 (npm 3, nx 3, cargo 0, python 0, tsconfig 1, path 0, docker 2, kustomize 0), arrows 6.", text)
        self.assertIn("Dockerfiles 7: 5 built (by 14 `build:` entries of 2 compose files, 5 not resolved, 3 naming "
                      "no context or Dockerfile of the checkout; compose files not read: none; by 0 builds of 0 "
                      "`docker/build-push-action` steps "
                      "in 0 GitHub Actions files, 0 not resolved, 0 naming no context or Dockerfile of the checkout; "
                      "steps not resolved: none; Actions files not read: none), 2 not built by any "
                      "(infra/docker/Dockerfile.unbuilt, ts/Dockerfile); their `COPY`/`ADD` sources: 9 from the context (6 matched, 1 matching nothing, "
                      "2 leaving it), 1 from a stage or image, 1 heredocs, 1 remote, 1 holding a variable (not "
                      "resolved); 1 instructions malformed.", text)
        self.assertIn("or of kind `docker`: a directory holding a Dockerfile that no other box holds", text)
        self.assertIn("| infra/docker | infra/docker | docker | @t/web (docker), infra-lib (docker) |", text)


class WorkflowBuilds(unittest.TestCase):
    """``docker_edges`` over GitHub Actions files: which files are read (the root's ``.github/workflows`` directly,
    ``action.yml`` anywhere), each step's pairs placed from the root (``file`` not relative to the context), the
    matrix expanded, a step not resolved counted by its reason, a file not read counted (a compose file too), ``unresolved`` and
    ``missing`` builds, a Dockerfile built with two contexts, the coverage and the drawing's line (the readers' own
    rules: test_profile_ghactions, test_profile_yamlblock)."""

    WORKFLOW = ("name: x\non: [push]\njobs:\n"
                "  one:\n    runs-on: ubuntu-latest\n    steps:\n"
                "      - uses: actions/checkout@v4\n"
                "      - uses: Docker/Build-Push-Action@v6\n        with:\n          context: .\n"
                "          file: img/Dockerfile\n"
                "  two:\n    strategy:\n      matrix:\n        include:\n          - f: img/Dockerfile.b\n"
                "          - f: ./img2/Dockerfile\n    steps:\n"
                "      - uses: docker/build-push-action@0123abc # v6\n        with:\n"
                "          file: ${{ matrix.f }}\n"
                "  three:\n    strategy:\n      matrix: ${{ fromJson(needs.x.outputs.m) }}\n    steps:\n"
                "      - uses: docker/build-push-action@v6\n        with: {file: img/Dockerfile}\n"
                "  four:\n    steps:\n"
                "      - uses: docker/build-push-action@v6\n        with:\n          context: ${{ inputs.ctx }}\n"
                "      - uses: docker/build-push-action@v6\n        with:\n          context: img\n"
                "          file: Dockerfile\n"
                "      - uses: docker/build-push-action@v6\n        with:\n          context: img\n"
                "      - uses: docker/build-push-action@v6\n        with:\n          file: /abs/Dockerfile\n"
                "      - uses: docker/build-push-action@v6\n        with:\n          context: b\n"
                "          file: img/Dockerfile.w\n"
                "      - uses: docker/setup-buildx-action@v3\n")

    def checkout(self) -> str:
        root = tempfile.mkdtemp()
        write(root, {
            "a/project.json": "{}", "b/project.json": "{}", "c/project.json": "{}",
            "img/Dockerfile": "COPY a /a\n",
            "img/Dockerfile.b": "COPY b /b\n",
            "img/Dockerfile.c": "COPY c /c\n",
            "img/Dockerfile.n": "COPY a /a\n",                     # named only by a workflow not read
            "img/Dockerfile.w": "COPY sub /s\n",                   # built with the context b
            "b/sub/project.json": "{}",
            "img2/Dockerfile": "COPY c /c\n",
            ".github/workflows/b.yml": self.WORKFLOW,
            ".github/workflows/bad.yml": "jobs:\n\tx: 1\n",
            "docker-compose.yml": "services:\n\tx: 1\n",
            ".github/workflows/nested/w.yml": "jobs:\n  n:\n    steps:\n"
                                              "      - uses: docker/build-push-action@v6\n"
                                              "        with:\n          file: img/Dockerfile.n\n",
            ".github/actions/build/action.yml": "runs:\n  using: composite\n  steps:\n"
                                                "    - uses: docker/build-push-action@v5\n"
                                                "      with:\n        file: img/Dockerfile.c\n",
        })
        return root

    def test_arrows(self):
        m = D.target_map(self.checkout())
        self.assertEqual([(p["dir"], p["kinds"]) for p in m["projects"]], [
            ("a", ["nx"]), ("b", ["nx"]), ("b/sub", ["nx"]), ("c", ["nx"]), ("img", ["docker"]),
            ("img2", ["docker"])])
        self.assertEqual([(e["from"], e["to"], e["kinds"]) for e in m["edges"]], [
            ("img", "a", ["docker"]),       # a literal step, the file from the root
            ("img", "b", ["docker"]),       # a matrix combination
            ("img", "b/sub", ["docker"]),   # the file from the root, its sources from the context
            ("img", "c", ["docker"]),       # a composite action's step
            ("img2", "c", ["docker"]),      # the other combination, "./" removed
        ])

    def test_coverage(self):
        dk = D.target_map(self.checkout())["coverage"]["docker"]
        self.assertEqual(dk["workflows"], {
            "files": 3, "unreadable": {"count": 1, "examples": [".github/workflows/bad.yml"]}, "steps": 9,
            "steps_unresolved": {"matrix_dynamic": 1, "context": 1, "function": 0, "operator": 0, "syntax": 0},
            "builds": 8, "builds_unresolved": 1, "builds_missing": 1})
        self.assertEqual((dk["dockerfiles"], dk["dockerfiles_built"], dk["dockerfiles_not_built"]),
                         (6, 5, {"count": 1, "examples": ["img/Dockerfile.n"]}))
        # img/Dockerfile is built with "" and with "img": its one source read once, resolved in each
        self.assertEqual(dk["sources"]["context"], 5)
        self.assertEqual(dk["context_sources"], {"matched": 5, "no_match": 1, "leaves_context": 0})

    def test_render(self):
        text = D.render_target(D.target_map(self.checkout()), "x")
        self.assertIn("Dockerfiles 6: 5 built (by 0 `build:` entries of 1 compose files, 0 not resolved, 0 naming "
                      "no context or Dockerfile of the checkout; compose files not read: 1 (docker-compose.yml); "
                      "by 8 builds of 9 `docker/build-push-action` steps "
                      "in 3 GitHub Actions files, 1 not resolved, 1 naming no context or Dockerfile of the checkout; "
                      "steps not resolved: matrix_dynamic 1, context 1; Actions files not read: 1 "
                      "(.github/workflows/bad.yml)), 1 not built by any (img/Dockerfile.n);", text)


class Kustomize(unittest.TestCase):
    """``kustomize_edges``: the ``kustomize`` boxes and arrows, each reference outcome, the manifests read with
    every document, the unreferenced YAML files, an unreadable file (not UTF-8, two documents) and the drawing's
    line (the reader's own rules: test_profile_kustomize, test_profile_yamlblock)."""

    def checkout(self) -> str:
        root = tempfile.mkdtemp()
        write(root, {
            "package.json": json.dumps({"workspaces": ["apps/*"]}),
            "apps/api/package.json": json.dumps({"name": "@t/api"}),
            "apps/api/k8s/kustomization.yaml": "resources:\n- ../../../deploy/base\n",  # in a project: no box
            "deploy/base/kustomization.yaml": ("resources:\n- ns.yaml\n- dep.yaml\n- missing.yaml\n- gone/\n"
                                               "configMapGenerator:\n- name: c\n  files: [k=cfg/app.conf]\n"),
            "deploy/base/ns.yaml": "kind: Namespace\n---\nkind: 3\n---\n",
            "deploy/base/dep.yaml": "---\nkind: Deployment\n",
            "deploy/base/cfg/app.conf": "x\n",
            "deploy/base/stale.yaml": "apiVersion: v1\nkind: Service\n",       # no kustomization names it
            "deploy/base/values.yaml": "kind: Values\n",                      # named by none, no Kubernetes object
            "deploy/base/two.yml": "a: 1\n---\napiVersion: v1\nkind: Secret\n",  # its second document is one
            "deploy/base/notes.txt": "",
            "deploy/prod/kustomization.yml": ("resources:\n- ../base\n- hpa.yaml\n- ../../../outside\n- /abs\n"
                                              "- https://example.invalid/k\n- 7\n- example.invalid/o/r\ncomponents: [../comp]\n"
                                              "patches:\n- path: p.yaml\n- patch: |-\n    kind: X\n"),
            "deploy/prod/hpa.yaml": "a:\n\tb: 1\n",                           # a tab: not read
            "deploy/prod/p.yaml": "kind: Deployment\n",                       # a patch: named, not a manifest
            "deploy/comp/x.yaml": "kind: Component\n",                        # no kustomization file here
            "kustomization.yaml": "resources:\n- deploy/prod\n",              # the root's: no box, no arrow
            "bad/kustomization.yaml": "a: 1\n---\nb: 2\n",
            "two/compose.yaml": "services: {}\n---\nservices: {}\n",           # two documents: not read
        })
        os.makedirs(os.path.join(root, "bad2"))
        with open(os.path.join(root, "bad2", "Kustomization"), "wb") as f:
            f.write(b"\xff\xferesources: []\n")
        with open(os.path.join(root, "compose.yaml"), "wb") as f:  # beside the root's kustomization, not read
            f.write(b"services:\n  a:\n    build: \xff\n")
        return root

    def test_boxes_and_arrows(self):
        m = D.target_map(self.checkout())
        self.assertEqual([(p["dir"], p["kinds"]) for p in m["projects"]],
                         [("apps/api", ["npm"]), ("bad", ["kustomize"]), ("bad2", ["kustomize"]),
                          ("deploy/base", ["kustomize"]), ("deploy/prod", ["kustomize"])])
        self.assertEqual(m["edges"], [{"from": "apps/api", "to": "deploy/base", "kinds": ["kustomize"]},
                                      {"from": "deploy/prod", "to": "deploy/base", "kinds": ["kustomize"]}])

    def test_coverage(self):
        cov = D.target_map(self.checkout())["coverage"]
        kz = cov["kustomize"]
        self.assertEqual(kz["files"], 6)
        self.assertEqual(kz["unreadable"], {"count": 2, "examples": ["bad/kustomization.yaml", "bad2/Kustomization"]})
        self.assertEqual(kz["references"], {"path": 14, "remote": 1, "inline": 0, "not_a_path": 1})
        self.assertEqual(kz["paths"], {"resolved": 8, "missing": 2, "remote": 1, "no_kustomization": 1,
                                       "leaves_root": 2})
        self.assertEqual(kz["missing_files"], {"count": 1, "examples": ["deploy/base/kustomization.yaml"]})
        self.assertEqual(kz["no_kustomization_files"], {"count": 1, "examples": ["deploy/prod/kustomization.yml"]})
        self.assertEqual(kz["manifests"], {"files": 3, "unreadable": {"count": 1, "examples": ["deploy/prod/hpa.yaml"]},
                                           "documents": 3, "empty_documents": 1,
                                           "kinds": {"Deployment": 1, "Namespace": 1, "no_kind": 1}})
        self.assertEqual(kz["unreferenced"], {"count": 2, "examples": ["deploy/base/stale.yaml", "deploy/base/two.yml"]})
        self.assertEqual(cov["projects_by_kind"]["kustomize"], 4)
        # a compose file that is not UTF-8 is not read, not an empty one
        self.assertEqual(cov["docker"]["compose_unreadable"], {"count": 2, "examples": ["compose.yaml",
                                                                                     "two/compose.yaml"]})

    def test_drawing(self):
        root = self.checkout()
        text = D.render_target(D.target_map(root), "x")
        self.assertIn("kustomize 4), arrows 2.", text)
        self.assertIn("Kustomization files 6 (not read: 2 (bad/kustomization.yaml, bad2/Kustomization)): path "
                      "references 14 (8 resolved, 2 naming nothing of the checkout (files: "
                      "deploy/base/kustomization.yaml), 1 naming a directory with no kustomization file (files: "
                      "deploy/prod/kustomization.yml), 2 leaving the root, 1 a "
                      "repository's path), 1 remote, 0 inline, 1 not a path; "
                      "manifests they deploy (`resources`, `bases`, `crds`): 3 files (not read: 1 "
                      "(deploy/prod/hpa.yaml)), 3 documents (Deployment 1, Namespace 1, no_kind 1), 1 empty; "
                      "Kubernetes manifests beside a kustomization file that none names: 2 (deploy/base/stale.yaml, "
                      "deploy/base/two.yml).", text)


class FileKinds(unittest.TestCase):
    """Every file is of one kind, decided in file_kind's order: read, code by name, code by extension, not code,
    unclassified, no extension; the coverage counts the last two with examples."""

    def test_each_rule_in_order(self):
        cases = {
            "a/m.py": ("read", ".py"), "a/m.tsx": ("read", ".tsx"),
            "Dockerfile.py": ("read", ".py"),                        # read wins over a name pattern
            "infra/Dockerfile": ("code", "Dockerfile"),
            "infra/Dockerfile.backend.dev": ("code", "Dockerfile.*"),  # the name wins over the suffix .dev
            "infra/Dockerfile.sql": ("code", "Dockerfile.*"),       # and over a code suffix
            "infra/api.Dockerfile": ("code", "*.Dockerfile"), "Makefile": ("code", "Makefile"),
            "x/run.sh": ("code", ".sh"), "q/select.jq": ("code", ".jq"),
            "README.md": ("not_code", ".md"), "a/b.json": ("not_code", ".json"), "f.woff2": ("not_code", ".woff2"),
            "x/a.service": ("unclassified", ".service"), ".env.example": ("unclassified", ".example"),
            "README.MD": ("unclassified", ".MD"), "x/run.SH": ("unclassified", ".SH"),  # case as written
            "x/dockerfile": ("no_extension", ""), "Dockerfiles": ("no_extension", ""),  # near names
            ".gitattributes": ("no_extension", ""), "LICENSE": ("no_extension", ""),  # a leading dot is no suffix
        }
        for rel, want in cases.items():
            self.assertEqual(D.file_kind(rel), want, rel)
            self.assertIn(want[0], D.FILE_KINDS)

    def test_the_lists_are_disjoint_and_names_only(self):
        self.assertFalse(D.OTHER_CODE_EXTENSIONS & D.NOT_CODE_EXTENSIONS)
        from profile import jsimports as J
        for listed in (D.OTHER_CODE_EXTENSIONS, D.NOT_CODE_EXTENSIONS):
            self.assertFalse(listed & (J.SOURCE_EXTENSIONS | {".py"}))
            for ext in listed:
                self.assertRegex(ext, r"^\.[^./]+$")
        self.assertEqual(len(D.CODE_FILE_NAMES), len(set(D.CODE_FILE_NAMES)))
        for p in D.CODE_FILE_NAMES:
            self.assertNotIn("/", p)

    def tree(self, files: dict[str, str]) -> dict:
        root = tempfile.mkdtemp()
        write(root, files)
        return D.target_map(root)

    def test_coverage_counts_the_unknown_with_examples(self):
        m = self.tree({
            "svc/a.service": "", "svc/b.service": "", "svc/c.service": "", "x/d.service": "",
            "deploy/s.yaml.template": "", ".dockerignore": "", "bin/tool": "", "LICENSE": "",
            "Dockerfile.api": "", "README.md": "", "a.py": "", "w.ts": "",
            "node_modules/p/z.service": "",                        # a skipped directory is not seen
        })
        cov = m["coverage"]
        self.assertEqual(cov["unclassified_files"], {
            ".service": {"count": 4, "examples": ["svc/a.service", "svc/b.service", "svc/c.service"]},
            ".template": {"count": 1, "examples": ["deploy/s.yaml.template"]},
        })
        self.assertEqual(cov["files_without_extension"],
                         {"count": 3, "examples": [".dockerignore", "LICENSE", "bin/tool"]})
        self.assertEqual(cov["unread_code_files"], {"Dockerfile.*": 1})
        self.assertIn("`NOT_CODE_EXTENSIONS`): .service 4 (svc/a.service, svc/b.service, svc/c.service, ...); "
                      ".template 1 (deploy/s.yaml.template); files with no extension and no `CODE_FILE_NAMES` "
                      "name: 3 (.dockerignore, LICENSE, bin/tool).", D.render_target(m, "x"))


class UnreadManifests(unittest.TestCase):
    """Manifests of ecosystems the map does not read are counted by MANIFESTS_NOT_READ's patterns; a package.json
    is counted when it is not an npm workspace project's (the root's is read for its workspaces)."""

    def tree(self, files: dict[str, str]) -> dict:
        root = tempfile.mkdtemp()
        write(root, files)
        return D.target_map(root)

    def test_patterns_count_by_file_name(self):
        cov = self.tree({
            "package.json": json.dumps({"workspaces": ["apps/*"]}),
            "apps/a/package.json": json.dumps({"name": "a"}),          # a workspace: read
            "e2e/package.json": json.dumps({"name": "e"}),             # an Nx project's own: not read
            "e2e/project.json": json.dumps({"name": "e2e"}),
            "tools/sup/package.json": "{}",                            # in no workspace
            "svc/one/go.mod": "", "svc/two/go.mod": "", "svc/three/go.mod": "", "svc/four/go.mod": "",
            "requirements-dev.txt": "", "py/requirements.txt": "", "py/setup.py": "",
            "net/App.csproj": "", "jvm/build.gradle.kts": "", "rb/Gemfile": "",
            "svc/go.mod.bak": "", "Requirements.txt": "", "py/notrequirements.txt": "",  # no pattern matches
            "py/pyproject.toml": "[project]\nname = \"p\"\n", "Cargo.toml": "[workspace]\n",  # read manifests
        })["coverage"]
        self.assertEqual(cov["unread_manifests"], {
            "*.csproj": {"count": 1, "examples": ["net/App.csproj"]},
            "Gemfile": {"count": 1, "examples": ["rb/Gemfile"]},
            "build.gradle.kts": {"count": 1, "examples": ["jvm/build.gradle.kts"]},
            "go.mod": {"count": 4, "examples": ["svc/four/go.mod", "svc/one/go.mod", "svc/three/go.mod"]},
            "package.json": {"count": 2, "examples": ["e2e/package.json", "tools/sup/package.json"]},
            "requirements*.txt": {"count": 2, "examples": ["py/requirements.txt", "requirements-dev.txt"]},
            "setup.py": {"count": 1, "examples": ["py/setup.py"]},
        })
        self.assertEqual(cov["python_files"], 1)
        self.assertEqual(cov["python_files_outside_projects"], 0)  # py/setup.py lies in the py project

    def test_an_unparsed_workspace_manifest_is_unread_and_a_skipped_directory_is_not_entered(self):
        cov = self.tree({
            "package.json": json.dumps({"workspaces": ["apps/*"]}),
            "apps/a/package.json": "{",
            "apps/a/node_modules/dep/package.json": "{}",
            "apps/a/node_modules/dep/go.mod": "",
        })["coverage"]
        self.assertEqual(cov["unparsed_manifests"], ["apps/a/package.json"])
        self.assertEqual(cov["unread_manifests"], {"package.json": {"count": 1, "examples": ["apps/a/package.json"]}})

    def test_a_manifest_nested_deeper_than_the_parser_goes_is_unparsed_not_a_fault(self):
        m = self.tree({"package.json": json.dumps({"workspaces": ["apps/*"]}),
                       "apps/a/package.json": "[" * 200000, "apps/b/package.json": json.dumps({"name": "b"})})
        self.assertEqual(m["coverage"]["unparsed_manifests"], ["apps/a/package.json"])
        self.assertEqual([p["dir"] for p in m["projects"]], ["apps/b"])

    def test_render_names_each_with_its_examples_and_none(self):
        m = self.tree({"a/go.mod": "", "b/go.mod": "", "c/go.mod": "", "d/go.mod": "", "e/pom.xml": ""})
        text = D.render_target(m, "x")
        self.assertIn("workspaces): go.mod 4 (a/go.mod, b/go.mod, c/go.mod, ...); pom.xml 1 (e/pom.xml).", text)
        self.assertIn("workspaces): none.", D.render_target(self.tree({"a.py": ""}), "x"))
        self.assertIn("Python files read 1 (1 outside any project, 0 not parsed).",
                      D.render_target(self.tree({"a.py": ""}), "x"))

    def test_the_list_is_names_only_and_distinct(self):
        self.assertEqual(len(D.MANIFESTS_NOT_READ), len(set(D.MANIFESTS_NOT_READ)))
        for p in D.MANIFESTS_NOT_READ:
            self.assertNotIn("/", p)
            self.assertNotIn(p, ("package.json", "project.json", "Cargo.toml", "pyproject.toml"))


class Cargo(unittest.TestCase):
    """Cargo packages anywhere, each dependency resolved through the workspace root Cargo finds for its package."""

    def tree(self, files: dict[str, str]) -> dict:
        root = tempfile.mkdtemp()
        write(root, files)
        m = D.target_map(root)
        return {"projects": [(p["dir"], p["name"]) for p in m["projects"]],
                "edges": [(e["from"], e["to"]) for e in m["edges"]], "unparsed": m["coverage"]["unparsed_manifests"]}

    ROOT_WS = ("[workspace]\nmembers = [\"crates/*\"]\nexclude = [\"crates/ex\", \"gw\"]\n"
               "[workspace.dependencies]\nb = { path = \"crates/b\" }\nq = \"1\"\n"
               "r = { version = \"1\", package = \"real-r\" }\ng = { git = \"https://example.invalid/g\" }\n"
               "[patch.crates-io]\nq = { path = \"vendor/q\" }\nreal-r = { path = \"vendor/r\" }\n"
               "s = { path = \"vendor/s\" }\n")

    def test_every_package_is_a_project_and_a_virtual_manifest_is_none(self):
        got = self.tree({"Cargo.toml": self.ROOT_WS,
                         "crates/a/Cargo.toml": "[package]\nname = \"a\"\n",
                         "crates/ex/Cargo.toml": "[package]\nname = \"ex\"\n",
                         "crates/nameless/Cargo.toml": "[package]\nversion = \"1\"\n",
                         "virtual/Cargo.toml": "[workspace]\nmembers = []\n",
                         "broken/Cargo.toml": "[package\n",
                         "fixtures/deep/k/Cargo.toml": "[package]\nname = \"k-fixture\"\n"})
        self.assertEqual(got["projects"], [("crates/a", "a"), ("crates/ex", "ex"), ("crates/nameless", "nameless"),
                                           ("fixtures/deep/k", "k-fixture")])
        self.assertEqual(got["unparsed"], ["broken/Cargo.toml"])

    def test_a_root_package_is_no_project_and_still_the_workspace_root(self):
        got = self.tree({"Cargo.toml": "[package]\nname = \"top\"\n[workspace]\n"
                                       "[patch.crates-io]\nq = { path = \"vendor/q\" }\n",
                         "vendor/q/Cargo.toml": "[package]\nname = \"q\"\n",
                         "a/Cargo.toml": "[package]\nname = \"a\"\n[dependencies]\nq = \"1\"\n"})
        self.assertEqual(got["projects"], [("a", "a"), ("vendor/q", "q")])
        self.assertEqual(got["edges"], [("a", "vendor/q")])

    def test_patch_and_workspace_dependencies_resolve_from_the_root(self):
        got = self.tree({"Cargo.toml": self.ROOT_WS,
                         "vendor/q/Cargo.toml": "[package]\nname = \"q\"\n",
                         "vendor/r/Cargo.toml": "[package]\nname = \"real-r\"\n",
                         "vendor/s/Cargo.toml": "[package]\nname = \"s\"\n",
                         "crates/b/Cargo.toml": "[package]\nname = \"b\"\n",
                         # a plain version, a renamed one and an inherited version string are patched
                         "crates/a/Cargo.toml": "[package]\nname = \"a\"\n[dependencies]\nq = \"1\"\n"
                                                "[dev-dependencies]\nalias = { version = \"1\", package = \"s\" }\n",
                         "crates/c/Cargo.toml": "[package]\nname = \"c\"\n[dependencies]\nq = { workspace = true }\n"
                                                "r = { workspace = true }\nb = { workspace = true }\n",
                         # a git, a registry and a missing workspace entry are not patched
                         "crates/d/Cargo.toml": "[package]\nname = \"d\"\n[dependencies]\n"
                                                "q = { git = \"https://example.invalid/q\" }\n"
                                                "s = { version = \"1\", registry = \"other\" }\n"
                                                "g = { workspace = true }\n",
                         # s is patched but no [workspace.dependencies] entry: Cargo refuses, nothing is drawn
                         "crates/e/Cargo.toml": "[package]\nname = \"e\"\n[dependencies]\ns = { workspace = true }\n"})
        self.assertEqual(got["edges"], [("crates/a", "vendor/q"), ("crates/a", "vendor/s"),
                                        ("crates/c", "crates/b"), ("crates/c", "vendor/q"), ("crates/c", "vendor/r")])

    def test_an_excluded_package_and_a_nested_workspace_are_their_own_roots(self):
        got = self.tree({"Cargo.toml": self.ROOT_WS,
                         "vendor/q/Cargo.toml": "[package]\nname = \"q\"\n",
                         "own/q/Cargo.toml": "[package]\nname = \"q\"\n",
                         # excluded, at and below the excluded path: the root's patch does not reach them
                         "crates/ex/Cargo.toml": "[package]\nname = \"ex\"\n[dependencies]\nq = \"1\"\n",
                         "crates/ex/sub/Cargo.toml": "[package]\nname = \"sub\"\n[dependencies]\nq = \"1\"\n",
                         # a nested workspace's own patch, written from its own directory
                         "gw/Cargo.toml": "[package]\nname = \"gw\"\n[workspace]\n[dependencies]\nq = \"1\"\n"
                                          "[patch.crates-io]\nq = { path = \"../own/q\" }\n",
                         "gw/fuzz/Cargo.toml": "[package]\nname = \"fz\"\n[dependencies]\nq = \"1\"\n"
                                               "gw = { path = \"..\" }\n",
                         # a member's own [patch] is ignored (Cargo reads it from the root only)
                         "crates/m/Cargo.toml": "[package]\nname = \"m\"\n[dependencies]\nq = \"1\"\n"
                                                "[patch.crates-io]\nq = { path = \"../../own/q\" }\n"})
        self.assertEqual(got["edges"], [("crates/m", "vendor/q"), ("gw", "own/q"), ("gw/fuzz", "gw"),
                                        ("gw/fuzz", "own/q")])

    def test_package_workspace_names_the_root(self):
        got = self.tree({"ws/Cargo.toml": "[workspace]\n[patch.crates-io]\nq = { path = \"../vendor/q\" }\n",
                         "vendor/q/Cargo.toml": "[package]\nname = \"q\"\n",
                         "far/p/Cargo.toml": "[package]\nname = \"p\"\nworkspace = \"../../ws\"\n"
                                             "[dependencies]\nq = \"1\"\n",
                         "far/n/Cargo.toml": "[package]\nname = \"n\"\nworkspace = \"../nowhere\"\n"
                                             "[dependencies]\nq = \"1\"\n"})
        self.assertEqual(got["edges"], [("far/p", "vendor/q")])

    def test_cargo_workspace_finds_the_root_as_cargo_does(self):
        roots = {"": {"workspace": {"exclude": ["x", 3]}}, "x/y": {"workspace": {}}}
        self.assertEqual(D.cargo_workspace("a/b", {"package": {}}, roots), "")
        self.assertIsNone(D.cargo_workspace("x", {"package": {}}, roots))
        self.assertIsNone(D.cargo_workspace("x/z", {"package": {}}, roots))
        self.assertEqual(D.cargo_workspace("xz", {"package": {}}, roots), "")   # a prefix by segments, not text
        self.assertEqual(D.cargo_workspace("x/y/z", {"package": {}}, roots), "x/y")
        self.assertEqual(D.cargo_workspace("x/y", {"package": {}}, roots), "x/y")
        self.assertIsNone(D.cargo_workspace("a", {"package": {}}, {}))


class Reads(unittest.TestCase):
    def test_order_contents_and_unreadable_files(self):
        with tempfile.TemporaryDirectory() as root:
            n = D.READ_AHEAD * 2 + 7
            rels = ["d%d/f%03d.py" % (i % 5, i) for i in range(n)]
            write(root, {rel: "text %s" % rel for rel in rels})
            with open(os.path.join(root, rels[3]), "wb") as f:
                f.write(b"\xff\xfe not utf-8")
            got = list(D._reads(root, rels + ["missing.py"]))
            self.assertEqual([r for r, _t in got], rels + ["missing.py"])
            self.assertEqual([t for _r, t in got],
                             ["text %s" % r if i != 3 else None for i, r in enumerate(rels)] + [None])
            self.assertEqual(list(D._reads(root, [])), [])

    def test_bounded_read_ahead_on_threads(self):
        import threading
        import time
        n = D.READ_AHEAD * 3
        started: list[str] = []
        at_once = [0, 0]
        lock = threading.Lock()

        def slow(root, rel):
            with lock:
                started.append(rel)
                at_once[0] += 1
                at_once[1] = max(at_once)
            time.sleep(0.001)
            with lock:
                at_once[0] -= 1
            return rel.upper()
        real = D._read
        D._read = slow
        try:
            taken = 0
            for rel, text in D._reads("/nowhere", ["f%d" % i for i in range(n)]):
                self.assertEqual(text, rel.upper())
                taken += 1
                if taken in (1, D.READ_AHEAD + 5):
                    time.sleep(0.3)  # the readers have time to run ahead; they stop at the window
                    with lock:
                        self.assertEqual(len(started), taken + D.READ_AHEAD)
                with lock:
                    self.assertLessEqual(len(started), taken + D.READ_AHEAD)
        finally:
            D._read = real
        self.assertEqual(taken, n)
        self.assertGreater(at_once[1], 1)
        self.assertLessEqual(at_once[1], D.READERS)


class Helpers(unittest.TestCase):
    def test_globs(self):
        dirs = ["apps", "apps/a", "apps/a/b", "libs/x", "abc/d", "axc/d", "a.b/c"]
        self.assertEqual(D.glob_dirs(["apps/*"], dirs), ["apps/a"])
        self.assertEqual(D.glob_dirs(["apps/**"], dirs), ["apps", "apps/a", "apps/a/b"])
        self.assertEqual(D.glob_dirs(["**/d"], dirs), ["abc/d", "axc/d"])
        self.assertEqual(D.glob_dirs(["a?c/*", "!axc/*"], dirs), ["abc/d"])
        self.assertEqual(D.glob_dirs(["a.b/*"], dirs + ["axb/c"]), ["a.b/c"])
        self.assertEqual(D.glob_dirs(["./libs/*/"], dirs), ["libs/x"])


def node(d: str, name: str | None = None, kinds: tuple[str, ...] = ("npm",)) -> dict[str, Any]:
    return {"dir": d, "name": name or d, "kinds": list(kinds)}


def arrow(a: str, b: str, kinds: tuple[str, ...] = ("import",)) -> dict[str, Any]:
    return {"from": a, "to": b, "kinds": list(kinds)}


def nest(depth: int) -> dict[str, Any]:
    """An object ``depth`` objects deep (``{"k": {"k": ... 1}}``), built without recursion."""
    value: Any = 1
    for _ in range(depth):
        value = {"k": value}
    return value


class Delta(unittest.TestCase):
    BASE = {"projects": [node("a"), node("b"), node("c")],
            "edges": [arrow("a", "b"), arrow("b", "c"), arrow("c", "a")],
            "coverage": {"files": 3}}

    def delta(self, **head: Any) -> dict[str, Any]:
        return D.map_delta(self.BASE, dict(self.BASE, **head))

    def test_depth_bound(self):
        # the map is the first level and coverage the outermost of nest's objects: nest(63) is a map 64 deep
        for depth, usable in ((63, True), (64, False), (5000, False)):
            m = dict(self.BASE, coverage=nest(depth))
            self.assertEqual(D._depth(m), depth + 1)
            if usable:
                D.check_map(m)
                self.assertEqual(D.map_delta(m, dict(m, coverage=nest(depth - 1)))["coverage"][0]["path"],
                                 ["k"] * (depth - 1))
            else:
                with self.assertRaisesRegex(D.MapUnusable, "^map nests deeper than 64$"):
                    D.check_map(m)
        # every list and object counts, under any key, not only coverage's objects
        self.assertEqual(D._depth({"x": [[[]]], "y": 1}), 4)
        self.assertEqual(D._depth([]), 1)
        self.assertEqual(D._depth("s"), 0)
        with self.assertRaisesRegex(D.MapUnusable, "deeper"):
            D.check_map(dict(self.BASE, other=nest(70)))

    def test_same(self):
        d = self.delta()
        self.assertEqual(d, {"projects": {"added": [], "removed": [], "changed": []},
                             "edges": {"added": [], "removed": [], "changed": []}, "coverage": [], "same": True})

    def test_projects_by_dir(self):
        d = self.delta(projects=[node("c", kinds=("cargo", "npm")), node("b", "B"), node("e"), node("d")])
        self.assertEqual(d["projects"], {"added": [node("d"), node("e")], "removed": [node("a")],
                                         "changed": [{"dir": "b", "base": node("b"), "head": node("b", "B")},
                                                     {"dir": "c", "base": node("c"),
                                                      "head": node("c", kinds=("cargo", "npm"))}]})
        self.assertFalse(d["same"])
        self.assertEqual(d["edges"], {"added": [], "removed": [], "changed": []})

    def test_edges_by_pair(self):
        d = self.delta(edges=[arrow("c", "a", ("import", "npm")), arrow("a", "c"), arrow("b", "c"), arrow("a", "d")])
        self.assertEqual(d["edges"], {"added": [arrow("a", "c"), arrow("a", "d")], "removed": [arrow("a", "b")],
                                      "changed": [{"from": "c", "to": "a", "base": arrow("c", "a"),
                                                   "head": arrow("c", "a", ("import", "npm"))}]})
        self.assertFalse(d["same"])
        # the pair is the key, not its order: b -> a is not a -> b
        self.assertEqual(self.delta(edges=[arrow("b", "a"), arrow("b", "c"), arrow("c", "a")])["edges"],
                         {"added": [arrow("b", "a")], "removed": [arrow("a", "b")], "changed": []})

    def test_coverage_leaves(self):
        base = {"files": 3, "sys_path": {"calls": 1, "dirs": 2}, "unclassified_files": {
                    ".utf8": {"count": 2, "examples": ["x.utf8", "y.utf8"]}, ".tpl": {"count": 1, "examples": ["t.tpl"]}},
                "kinds": {"npm": 1}, "list": [1, 2], "gone": {"deep": 1}, "flag": 1, "real": 1}
        head = {"files": 4, "sys_path": {"calls": 1, "dirs": 3}, "unclassified_files": {
                    ".utf8": {"count": 2, "examples": ["x.utf8", "z.utf8"]}, ".service": {"count": 1, "examples": ["s.service"]}},
                "kinds": 1, "list": [2, 1], "new": 0, "flag": True, "real": 1.0}
        d = D.map_delta(dict(self.BASE, coverage=base), dict(self.BASE, coverage=head))
        self.assertEqual(d["coverage"], [
            {"path": ["files"], "base": 3, "head": 4},
            {"path": ["flag"], "base": 1, "head": True},
            {"path": ["gone"], "base": {"deep": 1}},
            {"path": ["kinds"], "base": {"npm": 1}, "head": 1},
            {"path": ["list"], "base": [1, 2], "head": [2, 1]},
            {"path": ["new"], "head": 0},
            {"path": ["real"], "base": 1, "head": 1.0},
            {"path": ["sys_path", "dirs"], "base": 2, "head": 3},
            {"path": ["unclassified_files", ".service"], "head": {"count": 1, "examples": ["s.service"]}},
            {"path": ["unclassified_files", ".tpl"], "base": {"count": 1, "examples": ["t.tpl"]}},
            {"path": ["unclassified_files", ".utf8", "examples"], "base": ["x.utf8", "y.utf8"],
             "head": ["x.utf8", "z.utf8"]}])
        self.assertFalse(d["same"])
        # an equal nested object gives nothing
        self.assertEqual(D.map_delta(dict(self.BASE, coverage=base), dict(self.BASE, coverage=dict(base)))["coverage"],
                         [])

    def test_same_needs_every_part_empty(self):
        for head in ({"coverage": {"files": 4}}, {"edges": self.BASE["edges"][1:]},
                     {"projects": self.BASE["projects"][:2] + [node("c", "C")]}):
            self.assertFalse(self.delta(**head)["same"], head)

    def test_usable_maps(self):
        D.check_map(dict(self.BASE, other=[1]))  # other keys are not read
        bad = [[], {"edges": [], "coverage": {}}, dict(self.BASE, projects={}), dict(self.BASE, edges=None),
               dict(self.BASE, coverage=[]), dict(self.BASE, projects=[{"dir": "a", "kinds": []}]),
               dict(self.BASE, projects=[{"dir": 1, "name": "a", "kinds": []}]),
               dict(self.BASE, projects=[{"dir": "a", "name": "a", "kinds": [1]}]),
               dict(self.BASE, projects=[{"dir": "a", "name": "a", "kinds": "npm"}]),
               dict(self.BASE, projects=["a"]), dict(self.BASE, edges=[{"from": "a", "kinds": []}]),
               dict(self.BASE, projects=[node("a"), node("a", "other")]),
               dict(self.BASE, edges=[arrow("a", "b"), arrow("a", "b", ("npm",))])]
        for m in bad:
            with self.assertRaises(D.MapUnusable, msg=m):
                D.check_map(m)

    def test_target_maps(self):
        """Two checkouts of a target through ``target_map``: a new workspace and its import show in the delta."""
        root = tempfile.mkdtemp()
        write(root, {"package.json": json.dumps({"workspaces": ["p/*"]}),
                     "p/a/package.json": json.dumps({"name": "a"}), "p/a/i.ts": "export const x = 1;\n"})
        base = D.target_map(root)
        self.assertTrue(D.map_delta(base, D.target_map(root))["same"])
        write(root, {"p/b/package.json": json.dumps({"name": "b"}), "p/b/i.ts": "import { x } from 'a';\n"})
        d = D.map_delta(base, D.target_map(root))
        self.assertEqual(d["projects"]["added"], [{"dir": "p/b", "name": "b", "kinds": ["npm"]}])
        self.assertEqual(d["edges"]["added"], [{"from": "p/b", "to": "p/a", "kinds": ["import"]}])
        self.assertIn({"path": ["files"], "base": 3, "head": 5}, d["coverage"])


class CommandLine(unittest.TestCase):
    def run_cli(self, *argv: str) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, "-m", "status.depmap", *argv], cwd=REFEREE, capture_output=True,
                              text=True)

    def test_exits(self):
        root = tempfile.mkdtemp()
        write(root, {"a.py": "import b\n", "b.py": ""})
        ok = self.run_cli("brain", root)
        self.assertEqual(ok.returncode, 0)
        self.assertIn("| a | a.py | no |  | b |  |", ok.stdout)
        cov = self.run_cli("coverage", root)
        self.assertEqual(cov.returncode, 0)
        self.assertEqual(json.loads(cov.stdout)["files"], 2)
        self.assertEqual(self.run_cli("target", root, "--source", "x").returncode, 0)
        bad = self.run_cli("check", root)
        self.assertEqual((bad.returncode, json.loads(bad.stdout)),
                         (1, {"ok": False, "problems": ["off_live_unnamed:a", "off_live_unnamed:b"]}))
        write(root, {"status/off_live.json": json.dumps({n: {"kind": "unwired", "why": "w"} for n in "ab"})})
        good = self.run_cli("check", root)
        self.assertEqual((good.returncode, json.loads(good.stdout)), (0, {"ok": True, "problems": []}))
        for argv in ([], ["brain"], ["check"], ["map"], ["map", root, "x"], ["delta", root], ["delta", "a", "b", "c"], ["check", root, "extra"], ["brain", os.path.join(root, "nope")], ["target", root], ["other", root],
                     ["brain", root, "extra"]):
            self.assertEqual(self.run_cli(*argv).returncode, 2, argv)


    def test_map_and_delta(self):
        root = tempfile.mkdtemp()
        write(root, {"package.json": json.dumps({"workspaces": ["p/*"]}), "p/a/package.json": json.dumps({"name": "a"})})
        out = self.run_cli("map", root)
        self.assertEqual((out.returncode, json.loads(out.stdout)), (0, D.target_map(root)))
        base = os.path.join(root, "base.json")
        with open(base, "w", encoding="utf-8") as f:
            f.write(out.stdout)
        same = self.run_cli("delta", base, base)
        self.assertEqual((same.returncode, json.loads(same.stdout)["same"]), (0, True))
        write(root, {"p/b/package.json": json.dumps({"name": "b"})})
        head = os.path.join(root, "head.json")
        with open(head, "w", encoding="utf-8") as f:
            f.write(self.run_cli("map", root).stdout)
        moved = self.run_cli("delta", base, head)
        self.assertEqual(moved.returncode, 1)
        self.assertEqual(json.loads(moved.stdout), D.map_delta(D.read_map(base), D.read_map(head)))
        self.assertEqual(json.loads(moved.stdout)["projects"]["added"], [{"dir": "p/b", "name": "b", "kinds": ["npm"]}])

    def test_delta_unusable(self):
        root = tempfile.mkdtemp()
        good = os.path.join(root, "good.json")
        files = {"good.json": json.dumps(Delta.BASE), "bad.json": "{", "list.json": "[]", "deep.json": "[" * 200000,
                 "nested.json": json.dumps(dict(Delta.BASE, coverage=nest(100))),  # past MAP_DEPTH, within cli.DEPTH
                 "nested_far.json": json.dumps(dict(Delta.BASE, coverage=nest(5000))),  # past cli.DEPTH: the parse
                 "shape.json": json.dumps(dict(Delta.BASE, coverage=None))}
        write(root, files)
        extra = self.run_cli("delta", good, good, good)
        self.assertEqual((extra.returncode, extra.stdout, extra.stderr.strip()), (2, "", D.USAGE))
        latin = os.path.join(root, "latin.json")
        with open(latin, "wb") as f:
            f.write(b'{"projects": "\xe9"}')
        for name, error in (("bad.json", "JSONDecodeError at line 1 column 2"), ("list.json", "map is not an object"),
                            ("shape.json", "coverage is not an object"),
                            ("latin.json", "UnicodeDecodeError at position 14 (utf-8)"),
                            ("none.json", "No such file or directory"),
                            ("deep.json", "JSON nested too deeply"), ("nested.json", "map nests deeper than 64"),
                            ("nested_far.json", "JSON nested too deeply")):
            path = os.path.join(root, name)
            for argv in (("delta", good, path), ("delta", path, good)):
                r = self.run_cli(*argv)
                self.assertEqual((r.returncode, json.loads(r.stdout)), (2, {"ok": False, "error": "%s: %s" % (path, error)}),
                                 argv)


if __name__ == "__main__":
    unittest.main()
