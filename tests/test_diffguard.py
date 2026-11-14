"""Test 23 (asama-0/09) and group ``diffguard`` (tohum/29k): ``gate.diffguard``.

- every reason of asama-0/08 criterion 1, each with its clean counterpart: symlink and submodule by git
  mode (never by content), ``..`` and absolute paths, the profile's security and excluded paths, agent
  configuration in any case, lint/type/test configuration, manifest, lock files, ``.gitattributes`` and
  paths outside the unit's ``inputs``; every reason of a path is written, not only the first;
- which paths a block changes: B, A on deletion, both on rename, B on copy;
- the parser fails closed on anything ``git apply`` could read as a change the guard did not see;
- the command line: one JSON line, exit 0 / 1 / 2, stdin not read, never a traceback; an exit 2 is the
  module's own refusal, not ``cli.run``'s fault line (``refusal.assert_refused``).

The name lists are written here as tohum/29k and the measured rows state them, not read from the module: a
test that iterates the module's own table cannot see an entry dropped from it.

Diff texts below are ``git diff --cached --binary -M`` output (git 2.x) or edited copies of it.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest

REFEREE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REFEREE)

from gate import diffguard as G  # noqa: E402
import refusal  # noqa: E402
from profile import unit_verify as U  # noqa: E402

PROFILE = {"security_paths": ["pkg/ledger"], "excluded_dirs": ["pkg/vendored/"]}
RECIPE = {"unit_id": "pkg", "path": "pkg", "inputs": ["pkg/", "lib/shared.js"]}

# tohum/29k's lists, as written there.
SEED_CONFIG = (".eslintrc", ".eslintrc.json", ".eslintrc.js", ".eslintrc.cjs", ".eslintrc.yml", ".eslintrc.yaml",
               "eslint.config.js", "eslint.config.mjs", "eslint.config.cjs", "tsconfig.json", "jest.config.js",
               "jest.config.ts", "vitest.config.js", "vitest.config.ts", ".prettierrc", ".prettierrc.json",
               "biome.json")
SEED_LOCKS = ("package-lock.json", "npm-shrinkwrap.json", "yarn.lock", "pnpm-lock.yaml")

REAL_GIT = r'''diff --git a/pkg/a.js b/pkg/a.js
index de98044..7be73ce 100644
--- a/pkg/a.js
+++ b/pkg/a.js
@@ -1,3 +1,3 @@
 a
-b
+B
 c
diff --git a/pkg/bin.dat b/pkg/bin.dat
index bdc955b7b2e610ad5a72302b139a2e6cb325519a..350ed01038bfaa2fda2722ada23a75bdd971bd68 100644
GIT binary patch
literal 3
KcmZQzVg>*J3IGNG

literal 2
JcmZQz1ONa700IC2

diff --git a/pkg/link b/pkg/link
new file mode 120000
index 0000000..9b40195
--- /dev/null
+++ b/pkg/link
@@ -0,0 +1 @@
+../../etc/passwd
\ No newline at end of file
diff --git a/pkg/mode.sh b/pkg/mode.sh
old mode 100644
new mode 100755
diff --git a/pkg/old.js b/pkg/new.js
similarity index 100%
rename from pkg/old.js
rename to pkg/new.js
diff --git a/pkg/sp ace.js b/pkg/sp ace2.js
similarity index 100%
rename from pkg/sp ace.js
rename to pkg/sp ace2.js
diff --git a/pkg/sub b/pkg/sub
new file mode 160000
index 0000000..1111111
--- /dev/null
+++ b/pkg/sub
@@ -0,0 +1 @@
+Subproject commit 1111111111111111111111111111111111111111
diff --git "a/pkg/\303\274n\303\257.js" "b/pkg/\303\274n\303\257.js"
new file mode 100644
index 0000000..c600332
--- /dev/null
+++ "b/pkg/\303\274n\303\257.js"
@@ -0,0 +1 @@
+x
'''


def edit(path: str, mode: str = "100644") -> str:
    """A one-line modification of ``path`` as git writes it."""
    return ("diff --git a/{p} b/{p}\nindex 1111111..2222222 {m}\n--- a/{p}\n+++ b/{p}\n"
            "@@ -1 +1 @@\n-old\n+new\n").format(p=path, m=mode)


def new_file(path: str, mode: str, body: str) -> str:
    return ("diff --git a/{p} b/{p}\nnew file mode {m}\nindex 0000000..1111111\n--- /dev/null\n+++ b/{p}\n"
            "@@ -0,0 +1 @@\n+{b}\n\\ No newline at end of file\n").format(p=path, m=mode, b=body)


RENAME = "diff --git a/pkg/a b/pkg/b\nsimilarity index 100%\nrename from {a}\nrename to {b}\n"


def reasons(diff: str, profile=None, recipe=None) -> list[str]:
    return G.check(diff, PROFILE if profile is None else profile, RECIPE if recipe is None else recipe)


class Reasons(unittest.TestCase):
    def test_inside_inputs_plain_edit_passes(self):
        self.assertEqual(reasons(edit("pkg/a.js")), [])
        self.assertEqual(reasons(edit("lib/shared.js")), [])
        self.assertEqual(reasons(REAL_GIT), ["submodule:pkg/sub", "symlink:pkg/link"])

    def test_symlink_and_submodule_by_mode_not_content(self):
        target = "../../etc/passwd"
        self.assertEqual(reasons(new_file("pkg/l", "120000", target)), ["symlink:pkg/l"])
        self.assertEqual(reasons(new_file("pkg/l", "100644", target)), [])
        self.assertEqual(reasons(edit("pkg/l", "120000")), ["symlink:pkg/l"])
        type_change = "diff --git a/pkg/l b/pkg/l\nold mode 100644\nnew mode 120000\n"
        self.assertEqual(reasons(type_change), ["symlink:pkg/l"])
        sub = "Subproject commit " + "1" * 40
        self.assertEqual(reasons(new_file("pkg/s", "160000", sub)), ["submodule:pkg/s"])
        self.assertEqual(reasons(new_file("pkg/s", "100644", sub)), [])
        self.assertEqual(reasons(edit("pkg/s", "160000")), ["submodule:pkg/s"])
        # Stated boundary: the pre-image mode is not judged; a link turned into a file, or deleted, passes.
        to_file = "diff --git a/pkg/l b/pkg/l\nold mode 120000\nnew mode 100644\n"
        self.assertEqual(reasons(to_file), [])
        gone = "diff --git a/pkg/l b/pkg/l\ndeleted file mode 120000\nindex 1111111..0000000\n"
        self.assertEqual(reasons(gone), [])

    def test_path_escape_even_when_it_normalises_back(self):
        self.assertEqual(reasons(edit("pkg/../pkg/a.js")), ["path_escape:pkg/../pkg/a.js"])
        self.assertEqual(reasons(edit("pkg/x/..")), ["path_escape:pkg/x/.."])
        self.assertEqual(reasons(edit("/etc/passwd")), ["outside_inputs:/etc/passwd", "path_escape:/etc/passwd"])
        self.assertEqual(reasons(edit("pkg/..a/b..")), [])

    def test_agent_config_case_insensitive(self):
        for path in ("pkg/.claude/settings.json", "pkg/.Claude/x", "pkg/.VSCODE/settings.json",
                     "pkg/.devContainer/devcontainer.json", "pkg/CLAUDE.md", "pkg/claude.MD", "pkg/Agents.md",
                     "pkg/.MCP.json", "pkg/.EnvRC"):
            self.assertEqual(reasons(edit(path)), ["agent_config:" + path], path)
        for path in ("pkg/claude.md.bak", "pkg/myclaude/x", "pkg/claude", "pkg/.envrc.example"):
            self.assertEqual(reasons(edit(path)), [], path)

    def test_security_path_without_keyword(self):
        self.assertEqual(reasons(edit("pkg/ledger/post.js")), ["security_path:pkg/ledger/post.js"])
        self.assertEqual(reasons(edit("pkg/ledger")), ["security_path:pkg/ledger"])
        self.assertEqual(reasons(edit("pkg/ledger2/post.js")), [])
        self.assertEqual(reasons(edit("pkg/Ledger/post.js")), [])  # 29f coverage is case-sensitive

    def test_excluded_path(self):
        self.assertEqual(reasons(edit("pkg/vendored/x.js")), ["excluded_path:pkg/vendored/x.js"])
        self.assertEqual(reasons(edit("pkg/vendoredx.js")), [])

    def test_config_manifest_lock_gitattributes(self):
        for name in SEED_CONFIG + ("tsconfig.build.json", "tsconfig..json", "tsconfig.Build.json"):
            self.assertEqual(reasons(edit("pkg/sub/" + name)), ["config:pkg/sub/" + name], name)
        self.assertEqual(reasons(edit(".github/workflows/ci.yml")),
                         ["config:.github/workflows/ci.yml", "outside_inputs:.github/workflows/ci.yml"])
        self.assertEqual(reasons(edit("pkg/.github/notes.md")), [])  # only the root .github/
        self.assertEqual(reasons(edit(".githubx/a.md")), ["outside_inputs:.githubx/a.md"])  # the directory, not a prefix
        self.assertEqual(reasons(edit("pkg/package.json")), ["manifest:pkg/package.json"])
        for name in SEED_LOCKS:
            self.assertEqual(reasons(edit("pkg/" + name)), ["lockfile:pkg/" + name], name)
        self.assertEqual(reasons(edit("pkg/deep/.gitattributes")), ["gitattributes:pkg/deep/.gitattributes"])
        for path in ("pkg/tsconfig.js", "pkg/my-package.json", "pkg/package.json5", "pkg/yarn.lock.md",
                     "pkg/eslint.config.ts.md", "pkg/Package.json",
                     "pkg/TSCONFIG.build.json", "pkg/Biome.json"):
            self.assertEqual(reasons(edit(path)), [], path)

    def test_measured_tool_config_manifest_lock(self):
        """Names the target uses for lint, type and test configuration, Nx targets, the registry and
        toolchain version, and Rust/Python manifests and locks (missing_capability f111)."""
        for name in ("project.json", "nx.json", ".npmrc", ".nvmrc", ".node-version", "rust-toolchain.toml",
                     "rustfmt.toml", "deny.toml", "jest.config.cts", "jest.config.json", "jest.config.mjs",
                     "jest.e2e.config.ts", "jest-e2e.config.ts", "jest.integration.config.ts", "jest.preset.js",
                     "vite.config.ts", "vite.canvas.config.ts", "vitest.workspace.ts", "vitest.config.mts",
                     "playwright.config.ts", "playwright.messaging.config.ts", "babel.config.js", ".babelrc",
                     ".swcrc", ".mocharc.yml", ".eslintrc.mjs", "eslint.config.ts", ".prettierrc.yaml",
                     "prettier.config.cjs", "cypress.config.ts", "karma.config.js", "rust-toolchain",
                     "clippy.toml", ".clippy.toml", ".rustfmt.toml", "stylelint.config.mjs", ".stylelintrc.json",
                     "jest.config.json5", "vitest.config.jsonc", ".prettierrc.toml", "biome.config.cts",
                     "jest.e2e-ci.config.ts", "mocha.workspace.yaml"):
            self.assertEqual(reasons(edit("pkg/" + name)), ["config:pkg/" + name], name)
        for name in ("Cargo.toml", "pyproject.toml"):
            self.assertEqual(reasons(edit("pkg/" + name)), ["manifest:pkg/" + name], name)
        for name in ("Cargo.lock", "poetry.lock", "uv.lock"):
            self.assertEqual(reasons(edit("pkg/" + name)), ["lockfile:pkg/" + name], name)
        # Stated boundaries: application code named like configuration, imported config modules, setup files
        # and build-only tools pass; the shapes match whole base names only.
        for name in ("app.config.ts", "eslint.project-overrides.mjs", "jest.setup.ts", "vite-env.d.ts",
                     "postcss.config.js", "tailwind.config.js", "webpack.config.js", "jest.config.ts.snap",
                     "myjest.config.ts", "vitest-test-policy.js", "tailwind.config.d.ts", "Jest.config.ts",
                     "cargo.toml", "project.json.bak", "babelrc", "mocharc.yml", "x.eslintrc", ".eslintrc.md",
                     "jest.config.py"):
            self.assertEqual(reasons(edit("pkg/" + name)), [], name)

    def test_outside_inputs(self):
        self.assertEqual(reasons(edit("other/a.js")), ["outside_inputs:other/a.js"])
        self.assertEqual(reasons(edit("pkgx/a.js")), ["outside_inputs:pkgx/a.js"])
        self.assertEqual(reasons(edit("lib/shared.jsx")), ["outside_inputs:lib/shared.jsx"])

    def test_every_reason_of_a_path(self):
        path = ".github/../.Claude/package.json"
        profile = {"security_paths": [".github"], "excluded_dirs": [".github/"]}
        got = reasons(new_file(path, "120000", "x"), profile)
        self.assertEqual(got, ["%s:%s" % (r, path) for r in (
            "agent_config", "config", "excluded_path", "manifest", "outside_inputs", "path_escape",
            "security_path", "symlink")])

    def test_sorted_and_unique_across_blocks(self):
        got = reasons(edit("pkg/package.json") + edit("other/z.js") + edit("pkg/package.json"))
        self.assertEqual(got, ["manifest:pkg/package.json", "outside_inputs:other/z.js"])


class ChangedPaths(unittest.TestCase):
    def test_rename_changes_both_names(self):
        out = ("diff --git a/pkg/a.js b/other/a.js\nsimilarity index 100%\n"
               "rename from pkg/a.js\nrename to other/a.js\n")
        self.assertEqual(reasons(out), ["outside_inputs:other/a.js"])
        into = ("diff --git a/pkg/.claude/x b/pkg/x\nsimilarity index 100%\n"
                "rename from pkg/.claude/x\nrename to pkg/x\n")
        self.assertEqual(reasons(into), ["agent_config:pkg/.claude/x"])

    def test_deletion_changes_the_old_name(self):
        gone = ("diff --git a/pkg/package.json b/pkg/package.json\ndeleted file mode 100644\n"
                "index 1111111..0000000\n--- a/pkg/package.json\n+++ /dev/null\n@@ -1 +0,0 @@\n-{}\n")
        self.assertEqual(reasons(gone), ["manifest:pkg/package.json"])

    def test_copy_changes_the_new_name_only(self):
        copy = ("diff --git a/other/a.js b/pkg/b.js\nsimilarity index 100%\n"
                "copy from other/a.js\ncopy to pkg/b.js\n")
        self.assertEqual(reasons(copy), [])
        out = copy.replace("pkg/b.js", "other/b.js")
        self.assertEqual(reasons(out), ["outside_inputs:other/b.js"])

    def test_quoted_names_are_decoded(self):
        blocks = G.parse(REAL_GIT)
        self.assertEqual(blocks[-1]["changed"], ["pkg/ünï.js"])
        quoted = ('diff --git "a/pkg/\\303\\274/.CLAUDE/x" "b/pkg/\\303\\274/.CLAUDE/x"\n'
                  "old mode 100644\nnew mode 100755\n")
        self.assertEqual(reasons(quoted), ["agent_config:pkg/ü/.CLAUDE/x"])

    def test_every_quote_escape_git_writes(self):
        name = r'pkg/\a\b\t\n\v\f\r\"\\\101\303\274'
        diff = 'diff --git "a/%s" "b/%s"\nold mode 100644\nnew mode 100755\n' % (name, name)
        self.assertEqual(G.parse(diff)[0]["changed"], ['pkg/\a\b\t\n\v\f\r"\\Aü'])

    def test_one_side_quoted_rename(self):
        """git quotes each name on its own: a rename to a quoted name leaves the first name bare."""
        diff = ('diff --git a/pkg/x "b/pkg/\\303\\274"\nsimilarity index 100%\nrename from pkg/x\n'
                'rename to "pkg/\\303\\274"\n')
        self.assertEqual(G.parse(diff)[0]["changed"], ["pkg/x", "pkg/ü"])

    def test_empty_line_is_context(self):
        """An empty line inside a hunk is a context line whose leading space was stripped."""
        diff = edit("pkg/a.js").replace("@@ -1 +1 @@\n-old\n+new\n", "@@ -1,3 +1,3 @@\n a\n\n-b\n+c\n")
        self.assertEqual(G.parse(diff)[0]["hunks"][0]["lines"], [[" ", "a", True], [" ", "", True],
                                                                  ["-", "b", True], ["+", "c", True]])

    def test_block_fields_by_kind(self):
        fields = ("kind", "old", "new", "modes")
        gone = "diff --git a/pkg/a b/pkg/a\ndeleted file mode 100644\nindex 1111111..0000000\n"
        cases = ((edit("pkg/a"), ("modify", "pkg/a", "pkg/a", ["100644"])),
                 (new_file("pkg/a", "100755", "x"), ("create", None, "pkg/a", ["100755"])),
                 (gone, ("delete", "pkg/a", None, [])),
                 (RENAME.format(a="pkg/a", b="pkg/b"), ("rename", "pkg/a", "pkg/b", [])),
                 (RENAME.format(a="pkg/a", b="pkg/b").replace("rename", "copy"), ("copy", "pkg/a", "pkg/b", [])))
        for diff, want in cases:
            block = G.parse(diff)[0]
            self.assertEqual(tuple(block[f] for f in fields), want, diff)

    def test_names_with_spaces(self):
        self.assertEqual(G.parse(REAL_GIT)[5]["changed"], ["pkg/sp ace.js", "pkg/sp ace2.js"])
        spaced = ("diff --git a/pkg/a b/c b/pkg/a b/c\nindex 1111111..2222222 100644\n--- a/pkg/a b/c\t\n"
                  "+++ b/pkg/a b/c\t\n@@ -1 +1 @@\n-x\n+y\n")
        self.assertEqual(G.parse(spaced)[0]["changed"], ["pkg/a b/c"])


class FailsClosed(unittest.TestCase):
    """Each input below is unusable: no verdict, never ``ok``."""

    CASES = {
        "empty": "",
        "no_git_block": "--- a/pkg/a.js\n+++ b/pkg/a.js\n@@ -1 +1 @@\n-a\n+b\n",
        "text_before_block": "Subject: x\n\n" + edit("pkg/a.js"),
        "traditional_patch_after_hunk": edit("pkg/a.js") + "--- a/.claude/x\n+++ b/.claude/x\n@@ -1 +1 @@\n-a\n+b\n",
        "header_after_hunk": edit("pkg/a.js") + "new mode 120000\n",
        "hunk_shorter_than_counts": edit("pkg/a.js").replace("@@ -1 +1 @@", "@@ -1,2 +1,2 @@"),
        "hunk_longer_than_counts": edit("pkg/a.js").replace("+new\n", "+new\n+more\n"),
        "header_inside_hunk": edit("pkg/a.js").replace("-old\n", "-old\nrename to x\n"),
        "hunk_extra_removed_line": edit("pkg/a.js").replace("-old\n", "-old\n-extra\n"),
        "quoted_names_differ": ('diff --git "a/pkg/a.js" "b/.claude/a.js"\nold mode 100644\n'
                                "new mode 100755\n"),
        "unknown_header": edit("pkg/a.js").replace("index ", "mystery 1\nindex ", 1),
        "unknown_mode": edit("pkg/a.js", "100666"),
        "names_differ_without_rename": "diff --git a/pkg/a.js b/.claude/a.js\nold mode 100644\nnew mode 100755\n",
        "plus_name_disagrees": edit("pkg/a.js").replace("+++ b/pkg/a.js", "+++ b/.claude/a.js"),
        "minus_name_disagrees": edit("pkg/a.js").replace("--- a/pkg/a.js", "--- a/.claude/a.js"),
        "rename_disagrees_with_header": ("diff --git a/pkg/a.js b/pkg/b.js\nrename from pkg/a.js\n"
                                         "rename to .claude/b.js\n"),
        "rename_half": "diff --git a/pkg/a.js b/pkg/b.js\nrename from pkg/a.js\n",
        "no_prefix": "diff --git pkg/a.js pkg/a.js\nold mode 100644\nnew mode 100755\n",
        "repeated_header": "diff --git a/pkg/a b/pkg/a\nnew mode 100755\nnew mode 120000\n",
        "bad_binary_line": REAL_GIT.replace("KcmZQzVg>*J3IGNG", "Kcm ZQz"),
        "deletion_with_new_mode": ("diff --git a/pkg/a b/pkg/a\ndeleted file mode 100644\nnew mode 120000\n"),
        "unterminated_quote": 'diff --git "a/pkg/a b/pkg/a\nold mode 100644\nnew mode 100755\n',
        # Names. Each case below is refused by its own rule only: the rest of the block is what git writes.
        "unterminated_quote_in_rename": RENAME.format(a='"pkg/a', b="pkg/b"),
        "text_after_quoted_name": RENAME.format(a='"pkg/a"x', b="pkg/b"),
        "bad_escape": 'diff --git "a/pkg/\\q" "b/pkg/\\q"\nold mode 100644\nnew mode 100755\n',
        "octal_escape_above_377": 'diff --git "a/pkg/\\477" "b/pkg/\\477"\nold mode 100644\nnew mode 100755\n',
        "no_space_after_quoted_name": 'diff --git "a/pkg/a"Xb/pkg/a\nold mode 100644\nnew mode 100755\n',
        "names_split_without_space": "diff --git a/xyb/x\nold mode 100644\nnew mode 100755\n",
        "empty_names": "diff --git a/ b/\nold mode 100644\nnew mode 100755\n",
        "tab_after_name_without_space": edit("pkg/a.js").replace("--- a/pkg/a.js", "--- a/pkg/a.js\t"),
        "rename_empty_name": "diff --git a/ b/pkg/b\nrename from \nrename to pkg/b\n",
        "rename_and_copy": ("diff --git a/pkg/a b/pkg/b\nrename from pkg/a\nrename to pkg/b\ncopy from pkg/a\n"
                            "copy to pkg/b\n"),
        # Extended headers.
        "bad_index_line": edit("pkg/a.js").replace("index 1111111..2222222", "index zz..yy"),
        "upper_case_index": edit("pkg/a.js").replace("index 1111111..2222222", "index ABCDEF0..2222222"),
        "score_without_percent": RENAME.format(a="pkg/a", b="pkg/b").replace("100%", "100"),
        # '---'/'+++' and hunks.
        "minus_without_plus": edit("pkg/a.js").replace("+++ b/pkg/a.js", "XXXXb/pkg/a.js"),
        "sides_without_hunk": "diff --git a/pkg/a b/pkg/a\nindex 1111111..2222222 100644\n--- a/pkg/a\n+++ b/pkg/a\n",
        "combined_hunk_header": edit("pkg/a.js").replace("@@ -1 +1 @@", "@@@ -1 +1 @@"),
        "bad_hunk_header": edit("pkg/a.js").replace("@@ -1 +1 @@", "@@ -x +1 @@"),
        "hunk_header_inside_short_hunk": edit("pkg/a.js").replace(
            "@@ -1 +1 @@\n-old\n+new\n", "@@ -1,2 +1,2 @@\n-old\n+new\n@@ -5 +5 @@\n-c\n+d\n"),
        "context_beyond_new_count": edit("pkg/a.js").replace("@@ -1 +1 @@\n-old\n+new\n",
                                                             "@@ -1,2 +1 @@\n-old\n+new\n same\n"),
        "two_no_newline_markers": edit("pkg/a.js").replace(
            "+new\n", "+new\n\\ No newline at end of file\n\\ No newline at end of file\n"),
        # git apply joins a side's line after its '\ No newline' marker onto the marked line: 'x' and 'y' are
        # applied as one line 'xy' (git 2.x, measured), so the guard would read lines git does not write.
        "added_line_after_no_newline": ("diff --git a/pkg/z b/pkg/z\nnew file mode 100644\nindex 0000000..1111111\n"
                                        "--- /dev/null\n+++ b/pkg/z\n@@ -0,0 +1,2 @@\n+x\n"
                                        "\\ No newline at end of file\n+y\n"),
        "removed_line_after_no_newline": edit("pkg/a.js").replace(
            "@@ -1 +1 @@\n-old\n+new\n", "@@ -1,2 +1 @@\n-a\n\\ No newline at end of file\n-b\n+x\n"),
        "line_after_context_without_newline": edit("pkg/a.js").replace(
            "@@ -1 +1 @@\n-old\n+new\n", "@@ -1,2 +1,2 @@\n a\n\\ No newline at end of file\n-b\n+c\n"),
        "empty_hunk": edit("pkg/a.js").replace("@@ -1 +1 @@\n-old\n+new\n", "@@ -1,0 +1,0 @@\n"),
        "hunk_at_line_zero": edit("pkg/a.js").replace("@@ -1 +1 @@", "@@ -0,1 +0,1 @@"),
        "hunk_inside_an_insertion_point": edit("pkg/a.js").replace(
            "@@ -1 +1 @@\n-old\n+new\n", "@@ -2,0 +3 @@\n+x\n@@ -2 +3 @@\n-b\n+B\n"),
    }

    def test_each_case_is_unusable(self):
        for name, diff in self.CASES.items():
            with self.subTest(name):
                with self.assertRaises(G.DiffError):
                    G.check(diff, PROFILE, RECIPE)

    def test_unusable_profile_or_recipe(self):
        for profile, recipe in (({"security_paths": []}, RECIPE), ({"excluded_dirs": [], "security_paths": "x"}, RECIPE),
                                (PROFILE, {"inputs": "pkg/"}), (PROFILE, {"path": "pkg"}), ([], RECIPE),
                                ({"security_paths": [1], "excluded_dirs": []}, RECIPE),
                                (PROFILE, {"inputs": ["pkg/", None]})):
            with self.assertRaises(G.DiffError):
                G.check(edit("pkg/a.js"), profile, recipe)


class SharedRules(unittest.TestCase):
    """Agent configuration and coverage have one source, ``profile.derive``; MF6 and MF7 agree on them."""

    def test_recipe_and_diff_agree_on_agent_config(self):
        recipe = {"path": "pkg", "inputs": ["pkg"], "limits": {}, "env_image": "x", "services": []}
        policy = {"operating": {}}
        for path in ("pkg/.Claude/x", "pkg/AGENTS.md", "pkg/claude.md.bak", "pkg/x.envrc", "pkg/.vscode"):
            in_recipe = "input_excluded:" + path in U.vector_check(dict(recipe, inputs=["pkg", path]), policy)
            in_diff = "agent_config:" + path in reasons(edit(path))
            self.assertEqual(in_recipe, in_diff, path)


class CommandLine(unittest.TestCase):
    def run_cli(self, diff: str | bytes, profile=PROFILE, recipe=RECIPE, args=None):
        with tempfile.TemporaryDirectory() as tmp:
            files = []
            for name, content in (("d.patch", diff), ("profile.json", profile), ("recipe.json", recipe)):
                path = os.path.join(tmp, name)
                data = content if isinstance(content, (str, bytes)) else json.dumps(content)
                with open(path, "wb") as fh:
                    fh.write(data if isinstance(data, bytes) else data.encode("utf-8"))
                files.append(path)
            proc = subprocess.run([sys.executable, "-m", "gate.diffguard"] + (args or ["check"] + files),
                                  cwd=REFEREE, stdin=subprocess.DEVNULL, capture_output=True, text=True,
                                  timeout=60)
        lines = proc.stdout.splitlines()
        self.assertEqual(len(lines), 1, proc.stdout + proc.stderr)
        self.assertNotIn("Traceback", proc.stderr)
        self.stderr = proc.stderr
        return proc.returncode, json.loads(lines[0])

    def refused(self, diff, profile=PROFILE, recipe=RECIPE, args=None) -> str:
        """The module's own exit-2 refusal (not cli.run's fault line); its error text."""
        code, out = self.run_cli(diff, profile, recipe, args)
        refusal.assert_refused(self, G, args or ["check"], code, out, self.stderr)
        self.assertEqual(sorted(out), ["error", "ok"])
        self.assertIs(out["ok"], False)
        self.assertTrue(out["error"].startswith("unusable input: "), out)
        return out["error"]

    def test_exit_codes_and_output(self):
        self.assertEqual(self.run_cli(edit("pkg/a.js")), (0, {"ok": True, "reasons": []}))
        self.assertEqual(self.run_cli(REAL_GIT), (1, {"ok": False, "reasons": ["submodule:pkg/sub",
                                                                              "symlink:pkg/link"]}))

    def test_unusable_inputs_are_refused(self):
        self.refused("not a diff\n")  # DiffError
        self.refused(edit("pkg/a.js"), profile="{")  # ValueError: JSON
        self.refused(edit("pkg/a.js"), args=["check", "/nonexistent/d.patch", "p", "r"])  # OSError
        deep = {"security_paths": [], "excluded_dirs": [], "x": json.loads("[" * 200 + "]" * 200)}
        self.assertIn("nested too deeply", self.refused(edit("pkg/a.js"), profile=deep))  # cli.load's depth
        for args in (["scan"], ["check"], ["check", "d", "p", "r", "extra"], ["scan", "d", "p", "r"]):
            self.assertIn("usage:", self.refused(edit("pkg/a.js"), args=args), args)

    def test_non_utf8_hunk_content_is_usable(self):
        diff = edit("pkg/a.js").encode("utf-8").replace(b"+new", b"+n\xff\xfe")
        self.assertEqual(self.run_cli(diff), (0, {"ok": True, "reasons": []}))


if __name__ == "__main__":
    unittest.main()
