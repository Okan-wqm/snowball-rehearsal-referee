"""Snowball bootstrap referee.

The seed-shipped judge of Stage 0 (spec `tohum/29b`). It is written by an author other than the
founder, installed by the operator into the referee repository at setup, and retired when the
founder-built referee is imported at the Stage 0 exit.

Everything here is standard-library Python, except the Rekor signature (`sigstore`), which runs in
its own job from a hash-pinned requirement file. The rival is not a Python dependency: it is the
`claude` CLI, pinned by `requirements/claude-cli/package-lock.json` and run as the operator.
"""

__version__ = "1.0.0"
