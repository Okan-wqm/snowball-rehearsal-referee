"""Secret patterns checked before any text leaves for the model provider (`tohum/08` 11).

Every pattern must stay linear in the text it scans: the diff, a whole file and a verdict reach it
unbounded, and a pattern with two open-ended repeats around a keyword once took minutes on a long line.
"""

from __future__ import annotations

import re

_L = r"(?<![A-Za-z0-9])"  # for the prefixes that are common inside words (sk-, AIza ...): not glued to a letter or digit
# A credential-like keyword anywhere in a name (GITHUB_TOKEN, db_password, aws_secret_access_key ...) and the
# rest of that name, which is bounded: an unbounded tail made the scan quadratic on a long run of letters.
_NAME = r"(?i)(?:api[_-]?key|secret|password|passwd|token)[A-Za-z0-9_]{0,80}"

PATTERNS: dict[str, re.Pattern[str]] = {
    "private_key": re.compile(r"-----BEGIN (?:[A-Z0-9 ]+ )?PRIVATE KEY(?: BLOCK)?-----"),
    "github_token": re.compile(r"(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{36,}"),
    "github_pat": re.compile(r"github_pat_[A-Za-z0-9_]{60,}"),
    "anthropic_key": re.compile(r"sk-ant-[A-Za-z0-9_\-]{20,}"),
    "aws_access_key": re.compile(r"(?<![A-Z0-9])(?:AKIA|ASIA)[0-9A-Z]{16}(?![A-Za-z0-9])"),
    "slack_token": re.compile(r"xox[abprs]-[A-Za-z0-9-]{10,}"),
    "openai_key": re.compile(_L + r"sk-(?!ant-)(?:proj-|svcacct-)?[A-Za-z0-9_\-]{32,}"),
    "stripe_key": re.compile(_L + r"[sr]k_(?:live|test)_[A-Za-z0-9]{16,}"),
    "google_api_key": re.compile(_L + r"AIza[0-9A-Za-z_\-]{35}"),
    "npm_token": re.compile(r"npm_[A-Za-z0-9]{36}(?![A-Za-z0-9])"),
    # Not preceded by `-` or `_` either: they are part of the pattern's own alphabet, so every `eyJ` in a long
    # `eyJ-eyJ-...` run would start a scan of the whole run.
    "jwt": re.compile(r"(?<![A-Za-z0-9_\-])eyJ[A-Za-z0-9_\-]{10,}\.eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}"),
    # user:password@host in a URL (a database or a git remote): a password of 10 or more characters with
    # a letter and a digit, so `postgres://user:password@localhost` in a document is not one.
    "url_credentials": re.compile(
        r"[A-Za-z][A-Za-z0-9+.\-]{1,20}://[^/\s:@'\"]{1,64}:"
        r"(?=[^@\s'\"]{0,128}[0-9])(?=[^@\s'\"]{0,128}[A-Za-z])[^@\s'\"]{10,128}@"
    ),
    # A credential-like name assigned a quoted value, as in code, YAML and (the closing quote of the key) JSON ...
    "generic_assignment": re.compile(_NAME + r"['\"]?\s*[:=]\s*['\"][A-Za-z0-9/+_\-]{24,}['\"]"),
    # ... or an unquoted value that looks random: letters of both cases and a digit (a snake_case identifier,
    # a plain number or a lower-case word does not), or a long hex string.
    "generic_assignment_bare": re.compile(
        _NAME + r"\s*[:=]\s*"
        r"(?:(?-i:(?=[A-Za-z0-9/+_\-]*[a-z])(?=[A-Za-z0-9/+_\-]*[A-Z])(?=[A-Za-z0-9/+_\-]*[0-9])"
        r"[A-Za-z0-9/+_\-]{20,})|[0-9a-f]{32,})(?![A-Za-z0-9/+_\-])"
    ),
}


def scan(text: str) -> list[str]:
    """Return the names of the patterns that match ``text``."""
    return sorted(name for name, pattern in PATTERNS.items() if pattern.search(text))
