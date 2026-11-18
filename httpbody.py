"""One read of an HTTPS answer's body and one list of a failed exchange's errors, for every reader here.

The rule (bound by ``tests/test_http.py``): the body of an HTTPS answer is read by ``read(resp, cap)``, and the
handler that turns a failed exchange into the reader's own answer names ``ERRORS``: ``OSError``
(``urllib.error.URLError`` and ``HTTPError`` are ones; so are the socket's, TLS's and a timeout's errors) and
``http.client.HTTPException``, which is not an ``OSError`` (a status line that cannot be read, a body shorter than
the answer said).

``read`` judges a body the same way with and without a cap: without one it is ``resp.read()``; with one it reads
``cap + 1`` bytes at most, and when the body ended at ``cap`` bytes or fewer while http.client still expected bytes
of the answer's ``Content-Length`` (``resp.length``), it raises ``http.client.IncompleteRead`` as the uncapped read
does. A chunked body that ends inside a chunk or before the last chunk's size line raises that in http.client
itself, either way (what follows that size is not looked at).

Why: each reader had written its own read and its own list. Measured before this module (python 3.12, an answer of
``Content-Length: 7`` and three bytes, through urllib's opener): ``resp.read()`` raised ``IncompleteRead`` and
``resp.read(cap + 1)`` returned the three bytes, so ``runner.deps_npm`` read a cut tarball again only without a cap
and refused it as ``integrity_mismatch`` with one; and a chunked answer cut inside a chunk, or an answer with no
status line, escaped ``loop.accepted``'s readers and ``loop.rekor``'s as a fault (cli rule 3; their handlers named
``URLError`` and ``OSError``), where each has its own answer for an unreadable one.

Bound by ``HttpBody`` and ``HttpSites`` (each reader over the same failed exchanges, the answers parsed by
http.client itself) and by a register over every source file: a response opened through an opener made by
``urllib.request.build_opener`` names no read method of its own and is opened inside a ``try`` with a handler naming
``httpbody.ERRORS``; no source's code names ``urlopen`` or an ``HTTPSConnection``. This module opens nothing: it imports
``http.client`` for the two exception types (``tests/test_write.py``'s ``OneWay`` lists it for that).

Out of scope, stated: a body that is over the cap (``cap + 1`` bytes were read: the caller refuses it by its size,
whether it was complete is not looked at); a body with neither a ``Content-Length`` nor chunks, which ends where
the connection does (nothing says it was cut; a ``Content-Length`` http.client does not take as a number is none);
an object without http.client's ``length`` (not an ``HTTPResponse``: a test's stand-in) is read and not judged;
``target.write.HttpTransport``, which sends writes: it reads through ``read`` without a cap and has no handler of
its own, so a failed exchange there is its callers' (an ``OSError``) or a fault (an ``HTTPException``), unchanged
by this module and named in the register; an opener that reaches ``open`` a way the register does not follow (an
argument, a function's return value); ``resp.length`` is http.client's attribute, not a documented one: the tests
run it on the interpreter the referee runs (3.12).
"""

from __future__ import annotations

import http.client
from typing import Any

ERRORS = (OSError, http.client.HTTPException)


def read(resp: Any, cap: int | None = None) -> bytes:
    """The body of an HTTPS answer: all of it, or its first ``cap + 1`` bytes at most; a body that ended at ``cap``
    bytes or fewer, short of its ``Content-Length``, raises ``http.client.IncompleteRead``."""
    if cap is None:
        return resp.read()
    data = resp.read(cap + 1)
    left = getattr(resp, "length", None)
    if len(data) <= cap and left:
        raise http.client.IncompleteRead(data, left)
    return data
