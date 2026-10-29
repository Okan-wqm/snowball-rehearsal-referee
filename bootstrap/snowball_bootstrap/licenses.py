"""License gate for downloaded wheels (`tohum/24`, "Lisans").

Every wheel the brain installs must carry a license the operator allows for commercial use
(`policy.json` ``constitutional.license_allowlist``). The license is read from the wheel itself,
from every place it can be stated: the ``License-Expression`` field, the ``License`` field, the
``License ::`` classifiers and the license files under ``*.dist-info/``. A wheel passes only when
at least one place names a license and every place that names one is allowed; a package whose
license cannot be found is refused. The operator can record a reviewed expression for one exact
``name==version`` (``license_exceptions``); the recorded expression must itself be allowed.
"""

from __future__ import annotations

import re
import zipfile
from email.parser import HeaderParser
from pathlib import Path
from typing import Any

MAX_READ = 1_000_000

# Classifiers that name exactly one license. Ambiguous ones ("BSD License", bare "OSI Approved")
# say nothing and are skipped; another place must name the license.
CLASSIFIERS = {
    "License :: OSI Approved :: MIT License": "MIT",
    "License :: OSI Approved :: MIT No Attribution License (MIT-0)": "MIT-0",
    "License :: OSI Approved :: Apache Software License": "Apache-2.0",
    "License :: OSI Approved :: ISC License (ISCL)": "ISC",
    "License :: OSI Approved :: Python Software Foundation License": "PSF-2.0",
    "License :: OSI Approved :: The Unlicense (Unlicense)": "Unlicense",
    "License :: OSI Approved :: zlib/libpng License": "Zlib",
    "License :: OSI Approved :: Mozilla Public License 2.0 (MPL 2.0)": "MPL-2.0",
    "License :: OSI Approved :: GNU General Public License (GPL)": "GPL-2.0-or-later",
    "License :: OSI Approved :: GNU General Public License v2 (GPLv2)": "GPL-2.0-only",
    "License :: OSI Approved :: GNU General Public License v2 or later (GPLv2+)": "GPL-2.0-or-later",
    "License :: OSI Approved :: GNU General Public License v3 (GPLv3)": "GPL-3.0-only",
    "License :: OSI Approved :: GNU General Public License v3 or later (GPLv3+)": "GPL-3.0-or-later",
    "License :: OSI Approved :: GNU Lesser General Public License v2 (LGPLv2)": "LGPL-2.0-only",
    "License :: OSI Approved :: GNU Lesser General Public License v2 or later (LGPLv2+)": "LGPL-2.0-or-later",
    "License :: OSI Approved :: GNU Lesser General Public License v3 (LGPLv3)": "LGPL-3.0-only",
    "License :: OSI Approved :: GNU Lesser General Public License v3 or later (LGPLv3+)": "LGPL-3.0-or-later",
    "License :: OSI Approved :: GNU Library or Lesser General Public License (LGPL)": "LGPL-2.0-or-later",
    "License :: OSI Approved :: GNU Affero General Public License v3": "AGPL-3.0-only",
    "License :: OSI Approved :: GNU Affero General Public License v3 or later (AGPLv3+)": "AGPL-3.0-or-later",
    "License :: OSI Approved :: European Union Public Licence 1.2 (EUPL 1.2)": "EUPL-1.2",
    "License :: Other/Proprietary License": "LicenseRef-Proprietary",
    "License :: Free for non-commercial use": "LicenseRef-NonCommercial",
    "License :: Public Domain": "LicenseRef-PublicDomain",
}

# Free-text values of the ``License`` field, compared after collapsing case and spaces.
ALIASES = {
    "mit": "MIT", "mit license": "MIT", "the mit license": "MIT", "mit-0": "MIT-0",
    "apache 2.0": "Apache-2.0", "apache-2.0": "Apache-2.0", "apache license 2.0": "Apache-2.0",
    "apache license, version 2.0": "Apache-2.0", "apache software license": "Apache-2.0",
    "apache license version 2.0": "Apache-2.0", "bsd-2-clause": "BSD-2-Clause", "bsd-3-clause": "BSD-3-Clause",
    "isc": "ISC", "isc license": "ISC", "mpl-2.0": "MPL-2.0", "mpl 2.0": "MPL-2.0",
    "unlicense": "Unlicense", "the unlicense": "Unlicense", "psf-2.0": "PSF-2.0", "psf": "PSF-2.0",
    "zlib": "Zlib", "0bsd": "0BSD", "cc0-1.0": "CC0-1.0",
}

# License texts. A refusing license is recognised by its own title block, not by a mention (the
# PSF license, for one, mentions the GPL). Refusing texts are checked first, so a file that also
# carries an allowed text is still refused; the first allowing match names the file.
REFUSING_TEXTS = (
    (re.compile(r"gnu affero general public license version 3"), "AGPL-3.0-only"),
    (re.compile(r"gnu lesser general public license version 3"), "LGPL-3.0-only"),
    (re.compile(r"gnu lesser general public license version 2\.1"), "LGPL-2.1-only"),
    (re.compile(r"gnu library general public license version 2"), "LGPL-2.0-only"),
    (re.compile(r"gnu general public license version 3, "), "GPL-3.0-only"),
    (re.compile(r"gnu general public license version [12], "), "GPL-2.0-only"),
    (re.compile(r"server side public license version 1"), "SSPL-1.0"),
    (re.compile(r"business source license 1\.1"), "BUSL-1.1"),
    (re.compile(r"elastic license 2\.0"), "Elastic-2.0"),
    (re.compile(r"\"commons clause\" license condition"), "LicenseRef-Commons-Clause"),
    (re.compile(r"attribution-noncommercial"), "LicenseRef-NonCommercial"),
    (re.compile(r"all advertising materials mentioning features"), "BSD-4-Clause"),
)


def _text_license(text: str) -> str | None:
    t = " ".join(text.lower().split())
    for pattern, spdx in REFUSING_TEXTS:
        if pattern.search(t):
            return spdx
    if re.search(r"mozilla public license,? (version|v\.) 2\.0", t):
        return "MPL-2.0"
    if "apache license" in t and "version 2.0" in t:
        return "Apache-2.0"
    if "permission is hereby granted, free of charge, to any person obtaining a copy" in t:
        return "MIT" if "shall be included in all copies" in t else "MIT-0"
    if "python software foundation license version 2" in t:
        return "PSF-2.0"
    if "permission to use, copy, modify, and/or distribute this software for any purpose" in t:
        return "ISC" if "provided that the above copyright notice" in t else "0BSD"
    if "redistribution and use in source and binary forms" in t:
        return "BSD-3-Clause" if ("neither the name" in t or "endorse or promote" in t) else "BSD-2-Clause"
    if "this is free and unencumbered software released into the public domain" in t:
        return "Unlicense"
    if "cc0 1.0 universal" in t:
        return "CC0-1.0"
    if "altered source versions must be plainly marked" in t:
        return "Zlib"
    return None


# ---------------------------------------------------------------- SPDX expressions

TOKEN_RE = re.compile(r"\s*(\(|\)|[A-Za-z0-9.+:-]+)")


class ExpressionError(ValueError):
    pass


def _tokens(expr: str) -> list[str]:
    out, pos = [], 0
    while pos < len(expr):
        m = TOKEN_RE.match(expr, pos)
        if not m:
            if expr[pos:].strip():
                raise ExpressionError(f"unreadable license expression: {expr!r}")
            break
        out.append(m.group(1))
        pos = m.end()
    if not out:
        raise ExpressionError("empty license expression")
    return out


def allowed(expr: str, allowlist: frozenset[str]) -> bool:
    """SPDX semantics: ``OR`` needs one allowed side, ``AND`` needs both. ``X WITH exception`` is
    judged as ``X``: an exception only adds permissions. ``X+`` is judged as ``X``."""
    lower = {a.lower() for a in allowlist}
    toks = _tokens(expr)
    pos = 0

    def peek() -> str | None:
        return toks[pos] if pos < len(toks) else None

    def take() -> str:
        nonlocal pos
        if pos >= len(toks):
            raise ExpressionError(f"license expression ends early: {expr!r}")
        pos += 1
        return toks[pos - 1]

    def atom() -> bool:
        tok = take()
        if tok == "(":
            value = disjunction()
            if take() != ")":
                raise ExpressionError(f"unbalanced parentheses: {expr!r}")
            return value
        if tok.upper() in ("AND", "OR", "WITH") or tok == ")":
            raise ExpressionError(f"operator where a license was expected: {expr!r}")
        value = tok.removesuffix("+").lower() in lower
        if (peek() or "").upper() == "WITH":
            take()
            take()
        return value

    def conjunction() -> bool:
        value = atom()
        while (peek() or "").upper() == "AND":
            take()
            value = atom() and value
        return value

    def disjunction() -> bool:
        value = conjunction()
        while (peek() or "").upper() == "OR":
            take()
            value = conjunction() or value
        return value

    result = disjunction()
    if pos != len(toks):
        raise ExpressionError(f"trailing tokens in license expression: {expr!r}")
    return result


KNOWN_IDS = frozenset(v.lower() for v in (*CLASSIFIERS.values(), *ALIASES.values()))


def _known_ids(expr: str) -> bool:
    """True when ``expr`` reads as an SPDX expression made only of identifiers this module knows."""
    try:
        toks = _tokens(expr)
    except ExpressionError:
        return False
    ids = [t for t in toks if t not in "()" and t.upper() not in ("AND", "OR", "WITH")]
    return bool(ids) and all(t.removesuffix("+").lower() in KNOWN_IDS for t in ids)


# ---------------------------------------------------------------- wheels


def _norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _read(zf: zipfile.ZipFile, info: zipfile.ZipInfo) -> str:
    if info.file_size > MAX_READ:
        return ""
    return zf.read(info).decode("utf-8", "replace")


def inspect_wheel(path: Path) -> dict[str, Any]:
    """Every license statement in one wheel: ``{name, version, sources: [{from, expression}]}``."""
    with zipfile.ZipFile(path) as zf:
        infos = zf.infolist()
        metas = [i for i in infos if re.fullmatch(r"[^/]+\.dist-info/METADATA", i.filename)]
        if len(metas) != 1:
            return {"name": path.name, "version": "", "sources": [], "error": "metadata_missing"}
        dist_info = metas[0].filename.rsplit("/", 1)[0]
        meta = HeaderParser().parsestr(_read(zf, metas[0]))
        sources: list[dict[str, str]] = []
        if meta.get("License-Expression"):
            sources.append({"from": "License-Expression", "expression": meta["License-Expression"].strip()})
        field = (meta.get("License") or "").strip()
        if field:
            spdx = ALIASES.get(" ".join(field.lower().split()))
            if spdx is None and "\n" not in field and _known_ids(field):
                spdx = field
            if spdx is None:
                spdx = _text_license(field)
            if spdx:
                sources.append({"from": "License", "expression": spdx})
        for classifier in meta.get_all("Classifier") or []:
            spdx = CLASSIFIERS.get(classifier.strip())
            if spdx:
                sources.append({"from": "Classifier", "expression": spdx})
        for info in infos:
            name = info.filename
            if not name.startswith(dist_info + "/") or name.endswith("/") or name.endswith("/METADATA"):
                continue
            base = name.rsplit("/", 1)[1].upper()
            if "/licenses/" in name or base.startswith(("LICENSE", "LICENCE", "COPYING")):
                spdx = _text_license(_read(zf, info))
                if spdx:
                    sources.append({"from": name.split("/", 1)[1], "expression": spdx})
    return {"name": _norm(meta.get("Name") or path.name), "version": (meta.get("Version") or "").strip(),
            "sources": sources}


def judge(found: dict[str, Any], allowlist: frozenset[str], exceptions: dict[str, str]) -> dict[str, Any]:
    key = f"{found['name']}=={found['version']}"
    if key in exceptions:
        expr = exceptions[key]
        return dict(found, expression=expr, basis="exception", allowed=allowed(expr, allowlist))
    if not found["sources"]:
        return dict(found, expression="unknown", basis="none", allowed=False)
    verdicts = []
    for src in found["sources"]:
        try:
            verdicts.append(allowed(src["expression"], allowlist))
        except ExpressionError:
            verdicts.append(False)
    return dict(found, expression=found["sources"][0]["expression"], basis="detected", allowed=all(verdicts))


def check_dir(wheel_dir: Path, allowlist: frozenset[str], exceptions: dict[str, str]) -> list[dict[str, Any]]:
    return [dict(judge(inspect_wheel(p), allowlist, exceptions), wheel=p.name)
            for p in sorted(wheel_dir.glob("*.whl"))]


def violations(report: list[dict[str, Any]]) -> list[str]:
    return [f"{r['name']}=={r['version']}:{r['expression']}" for r in report if not r["allowed"]]
