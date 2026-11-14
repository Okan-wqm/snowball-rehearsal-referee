"""``profile.kustomize`` (run with test 47): each rule of its docstring on a document made for it.

- the file names; ``host_like``; every path field in ``FIELDS`` order and list order; ``files`` entries' ``key=path``;
- each kind (``path``, ``remote`` two ways, ``inline`` as text with a line break and as a mapping,
  ``not_a_path``); a field that is not a list, an entry that is not a mapping, a document that is not a mapping;
- the fields stated as not read give nothing.
"""

from __future__ import annotations

import os
import sys
import unittest

REFEREE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REFEREE)

from profile import kustomize as K  # noqa: E402
from profile import yamlblock as Y  # noqa: E402


class Names(unittest.TestCase):
    def test_names(self):
        for name in ("kustomization.yaml", "kustomization.yml", "Kustomization"):
            self.assertTrue(K.is_kustomization(name), name)
        for name in ("kustomization.json", "Kustomization.yaml", "kustomization.yaml.bak", "kustomize.yaml"):
            self.assertFalse(K.is_kustomization(name), name)


class References(unittest.TestCase):
    DOC = """\
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
configMapGenerator:
- name: a
  files:
  - app.conf
  - key=dir/b.conf
  envs:
  - x.env
  env: y.env
  literals:
  - K=V
secretGenerator:
- name: s
  files: [k=s.txt]
openapi:
  path: schema.json
patchesJson6902:
- target: {kind: Deployment}
  path: j.yaml
patches:
- path: p.yaml
- patch: |-
    kind: Deployment
- target: {kind: Service}
configurations: [c.yaml]
validators: [v.yaml]
generators: [g.yaml]
transformers:
- t.yaml
- apiVersion: builtin
  kind: LabelTransformer
patchesStrategicMerge:
- sm.yaml
- |-
  kind: Deployment
crds: [crd.yaml]
components: [../comp]
bases: [../old]
resources:
- ../base
- https://example.invalid/o/r//k?ref=v1
- git@example.invalid:o/r.git
- example.invalid/o/r/k
- 7
-
images:
- name: x
  newTag: y
helmCharts:
- name: c
  valuesFile: values.yaml
replacements:
- path: r.yaml
"""

    def test_every_field_in_order(self):
        got = K.references(Y.load(self.DOC))
        self.assertEqual([(f, v if not isinstance(v, dict) else "{}", k) for f, v, k in got], [
            ("resources", "../base", "path"),
            ("resources", "https://example.invalid/o/r//k?ref=v1", "remote"),
            ("resources", "git@example.invalid:o/r.git", "remote"),
            ("resources", "example.invalid/o/r/k", "path"),
            ("resources", 7, "not_a_path"),
            ("resources", None, "not_a_path"),
            ("bases", "../old", "path"),
            ("components", "../comp", "path"),
            ("crds", "crd.yaml", "path"),
            ("patchesStrategicMerge", "sm.yaml", "path"),
            ("patchesStrategicMerge", "kind: Deployment", "inline"),
            ("transformers", "t.yaml", "path"),
            ("transformers", "{}", "inline"),
            ("generators", "g.yaml", "path"),
            ("validators", "v.yaml", "path"),
            ("configurations", "c.yaml", "path"),
            ("patches", "p.yaml", "path"),
            ("patchesJson6902", "j.yaml", "path"),
            ("openapi", "schema.json", "path"),
            ("configMapGenerator", "app.conf", "path"),
            ("configMapGenerator", "dir/b.conf", "path"),
            ("configMapGenerator", "x.env", "path"),
            ("configMapGenerator", "y.env", "path"),
            ("secretGenerator", "s.txt", "path"),
        ])

    def test_inline_text_has_a_line_break(self):
        doc = {"patchesStrategicMerge": ["kind: A\nmetadata: {}\n", "a.yaml"]}
        self.assertEqual(K.references(doc), [("patchesStrategicMerge", "kind: A\nmetadata: {}\n", "inline"),
                                             ("patchesStrategicMerge", "a.yaml", "path")])

    def test_kinds(self):
        self.assertEqual([K.kind(v) for v in ("a/b", "http://x", "git@h:o/r", "h.example/o", "a\nb", "k: v", {}, [], 1,
                                              None, True)],
                         ["path", "remote", "remote", "path", "inline", "inline", "inline", "inline", "not_a_path",
                          "not_a_path", "not_a_path"])

    def test_host_like(self):
        for value in ("example.invalid/o/r", "h.io/o", "a.b/c/d?ref=x"):
            self.assertTrue(K.host_like(value), value)
        for value in ("../base", "./h.io/x", "base", "conf.d", "dir/h.io/x", ".hidden.d/x", "a.yaml"):
            self.assertFalse(K.host_like(value), value)

    def test_only_env_files_split_on_equals(self):
        doc = {"configMapGenerator": [{"files": ["k=v.txt", "plain.txt"], "envs": ["a=b.env"]}]}
        self.assertEqual([v for _f, v, _k in K.references(doc)], ["v.txt", "plain.txt", "a=b.env"])

    def test_shapes_not_read(self):
        self.assertEqual(K.references(["resources"]), [])
        self.assertEqual(K.references(None), [])
        self.assertEqual(K.references({"resources": "a.yaml", "patches": ["p.yaml", {"path": "q.yaml"}],
                                       "openapi": "x.json", "configMapGenerator": ["a", {"files": "f"},
                                                                                   {"env": "e.env"}]}),
                         [("patches", "q.yaml", "path"), ("configMapGenerator", "e.env", "path")])


if __name__ == "__main__":
    unittest.main()
