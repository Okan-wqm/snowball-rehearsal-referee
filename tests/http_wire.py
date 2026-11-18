"""A stand-in for the socket under urllib's opener, shared by the tests of the HTTPS readers (no network in the
sandbox): the bytes of an answer are parsed by ``http.client.HTTPResponse`` as a socket's are, so the status line,
the headers and the body's framing (``Content-Length``, chunks) are judged by the standard library's own code."""

from __future__ import annotations

import http.client
import io
import urllib.request


def answer(status: int, body: bytes = b"", length: int | None = None, headers: tuple = ()) -> bytes:
    """The bytes of one HTTP/1.1 answer; ``length`` is the ``Content-Length`` written (the body's own by default)."""
    lines = ["HTTP/1.1 %d X" % status, "Content-Length: %d" % (len(body) if length is None else length)]
    return "\r\n".join(lines + list(headers) + ["", ""]).encode("ascii") + body


def chunked(status: int, *chunks: bytes, cut: int = 0) -> bytes:
    """The bytes of one chunked HTTP/1.1 answer: each chunk, then the last-chunk; ``cut`` bytes are taken off the
    end (so ``cut=7`` loses the last-chunk and the last two bytes of the last chunk's own line end)."""
    raw = b"HTTP/1.1 %d X\r\nTransfer-Encoding: chunked\r\n\r\n" % status
    raw += b"".join(b"%x\r\n%s\r\n" % (len(c), c) for c in chunks) + b"0\r\n\r\n"
    return raw[:len(raw) - cut]


class _Sock:
    def __init__(self, raw: bytes):
        self.raw = raw

    def makefile(self, *_args, **_kwargs):
        return io.BytesIO(self.raw)


class Wire(urllib.request.BaseHandler):
    """In place of the socket: each ``https_open`` takes the next step of ``script``, an exception (raised, as a
    failed connection is) or the bytes of an answer, which ``http.client.HTTPResponse`` parses as it parses a
    socket's and urllib's processors then judge (statuses, redirects)."""
    handler_order = 100

    def __init__(self, *script):
        self.script, self.seen = list(script), []

    def https_open(self, req):
        self.seen.append(req.full_url)
        step = self.script.pop(0)
        if isinstance(step, BaseException):
            raise step
        resp = http.client.HTTPResponse(_Sock(step), method=req.get_method(), url=req.full_url)
        resp.begin()
        resp.msg = resp.reason
        return resp
