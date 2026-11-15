"""cli's rule 9: every reader of archive bytes refuses malformed bytes by its own answer, never by a fault.

- ``Members``: each library error in ``cli.ARCHIVE_ERRORS`` is raised by its library for malformed bytes (a fixture
  each), so none is there by guess;
- ``Corpus``: every reader that names the tuple, run over the corpus of its archive kind (every byte flipped, three
  ways in a compressed archive, one in a plain tar; every third truncation; 300 seeded scrambles), reads or refuses each variant by its own answer:
  ``loop.accepted.unpack`` (zip), ``loop.treehash``'s command (tar and gzip tar), ``profile.derive.read_tree``,
  ``runner.deps_npm``'s two tarball readers, ``loop.pulled.extract_tree`` (tar), and ``profile.unit_verify.unpack``,
  whose handler is in ``install_deps``: there every exception is one that handler catches;
- ``Register``: outside ``cli.py``, no handler names one of the tuple's library errors itself (each reader had
  written its own list, and three missed one).
"""

from __future__ import annotations

import ast
import contextlib
import gzip
import io
import os
import random
import shutil
import sys
import tarfile
import tempfile
import unittest
import zipfile
import zlib

REFEREE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REFEREE)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import cli  # noqa: E402
from loop import accepted as A  # noqa: E402
from loop import pulled as P  # noqa: E402
from loop import treehash as T  # noqa: E402
from profile import derive as R  # noqa: E402
from profile import unit_verify as U  # noqa: E402
from runner import deps_npm as D  # noqa: E402
from test_cli import sources  # noqa: E402

FILES = (("package/package.json", b'{"name": "x", "version": "1.0.0"}'),
         ("package/index.js", b"module.exports = 1;\n" * 30),
         ("package/lib/a.js", random.Random(1).randbytes(300)))


def tar_bytes(files=FILES) -> bytes:
    """The members and the two zero blocks that end an archive, without tarfile's padding to a 10240-byte record."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w", format=tarfile.PAX_FORMAT) as tar:
        for name, data in files:
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
        end = tar.offset
    return buf.getvalue()[:end + 2 * tarfile.BLOCKSIZE]


def zip_bytes() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("result.json", b'{"state": {"last_accepted_sha": "' + b"a" * 40 + b'"}}' * 20)
        zf.writestr("result.json.sigstore.json", random.Random(2).randbytes(300))
    return buf.getvalue()


TAR = tar_bytes()
# a longer repeated text and 300 random bytes: the deflate stream then has the blocks whose corruption zlib itself
# refuses (measured over this corpus: 186 zlib.error among 2197 variants; with FILES' 30 lines, none)
TGZ = gzip.compress(tar_bytes((FILES[0], ("package/index.js", b"module.exports = 1;\n" * 300), FILES[2])), mtime=0)
ZIP = zip_bytes()


def variants(data: bytes, flips=(0x01, 0x80, 0xFF)):
    """Every byte xor-ed with each of ``flips``, every third truncation, 300 seeded scrambles of 4 bytes each."""
    for pos in range(len(data)):
        for bit in flips:
            out = bytearray(data)
            out[pos] ^= bit
            yield bytes(out)
    for n in range(0, len(data), 3):
        yield data[:n]
    rnd = random.Random(7)
    for _ in range(300):
        out = bytearray(data)
        for _ in range(4):
            out[rnd.randrange(len(out))] = rnd.randrange(256)
        yield bytes(out)


class Members(unittest.TestCase):
    def raises(self, kind, read, data: bytes) -> None:
        with self.assertRaises(kind):
            read(data)

    def test_each_error_is_raised_by_its_library(self):
        def tar(data):
            with tarfile.open(fileobj=io.BytesIO(data), mode="r:*") as t:
                for m in t:
                    if m.isreg():
                        t.extractfile(m).read()

        def zipped(data):
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                for info in zf.infolist():
                    zf.read(info)
        self.raises(tarfile.ReadError, tar, b"x" * 1024)
        crc = bytearray(TGZ)
        crc[-8] ^= 1  # the gzip trailer's CRC
        self.raises(gzip.BadGzipFile, gzip.decompress, bytes(crc))  # read to its end, as a reader past the tar may
        self.raises(EOFError, gzip.decompress, TGZ[:-12])  # a deflate stream cut before its end
        block = bytearray(TGZ)
        block[10] = 0xFF  # the first deflate block's type: 3 is reserved
        self.raises(zlib.error, lambda d: zlib.decompress(d[10:], -15), bytes(block))
        self.raises(zipfile.BadZipFile, zipped, ZIP.replace(b"PK\x03\x04", b"PK\x03\x05", 1))  # a member's magic
        self.assertEqual(set(cli.ARCHIVE_ERRORS), {tarfile.TarError, gzip.BadGzipFile, zlib.error, EOFError,
                                                   zipfile.BadZipFile})


class Corpus(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def path(self, data: bytes) -> str:
        path = os.path.join(self.tmp, "in")
        with open(path, "wb") as fh:
            fh.write(data)
        return path

    def each(self, data: bytes, read, refused) -> None:
        """``read`` over every variant of ``data``: returns, or raises one of ``refused``; else the test fails. A
        plain tar (no decoder of its own) has each byte flipped one way, a compressed archive three."""
        escaped = {}
        for variant in variants(data, (0xFF,) if data == TAR else (0x01, 0x80, 0xFF)):
            try:
                read(variant)
            except refused:
                pass
            except Exception as exc:  # noqa: BLE001 - the escapes are what this test counts
                escaped.setdefault(type(exc).__name__, variant)
        self.assertEqual(sorted(escaped), [])

    def test_accepted_unpack(self):
        self.each(ZIP, A.unpack, A.StateError)

    def test_treehash(self):
        # the corpus through of_tar, which raises to the command's handler: only what that handler catches
        for data in (TAR, TGZ):
            self.each(data, T.of_tar, (T.TreeHashError, *cli.ARCHIVE_ERRORS))
        # and the command over the first variant of each library error of_tar raises: its own line, exit 2
        first = {}
        for variant in variants(TGZ):
            try:
                T.of_tar(variant)
            except cli.ARCHIVE_ERRORS as exc:
                first.setdefault(type(exc), variant)
            except T.TreeHashError:
                pass
        self.assertEqual(set(first), {tarfile.ReadError, gzip.BadGzipFile, zlib.error, EOFError})
        for data in (b"x" * 1024, TAR[:600], *first.values()):
            out = io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
                code = T.main(["tar", self.path(data)])
            self.assertEqual((code, out.getvalue()), (2, '{"ok": false, "reasons": null}\n'))

    def test_derive_read_tree(self):
        self.each(TGZ, lambda d: R.read_tree(self.path(d)), R.DeriveError)

    def test_deps_npm_tarballs(self):
        self.each(TGZ, D.inspect_tarball, ())
        self.each(TGZ, lambda d: D._vector_tarball(d, "x"), D.DepsError)

    def test_pulled_extract_tree(self):
        def extract(data):
            dest = os.path.join(self.tmp, "tree")
            shutil.rmtree(dest, ignore_errors=True)
            P.extract_tree(self.path(data), dest)
        self.each(TAR, extract, P.PulledError)
        with self.assertRaises(P.PulledError) as ctx:  # its own context: a file it cannot open
            P.extract_tree(os.path.join(self.tmp, "absent.tar"), os.path.join(self.tmp, "tree2"))
        self.assertEqual(ctx.exception.reasons, ["tree_unreadable"])

    def test_unit_verify_unpack(self):
        def unpack(data):
            root = tempfile.mkdtemp(dir=self.tmp)
            try:
                U.unpack(data, root, "d", 10 ** 8)
            finally:
                shutil.rmtree(root)
        self.each(TGZ, unpack, (U._Unsafe, U._TooBig, *cli.ARCHIVE_ERRORS))


ERRORS = {("tarfile", "TarError"), ("tarfile", "ReadError"), ("tarfile", "CompressionError"),
          ("tarfile", "HeaderError"), ("gzip", "BadGzipFile"), ("zlib", "error"), ("zipfile", "BadZipFile"),
          ("zipfile", "BadZipfile"), (None, "EOFError")}


def own_archive_lists(source: str) -> list[str]:
    """Every handler in ``source`` naming one of the library errors of ``cli.ARCHIVE_ERRORS`` (``module.name`` or
    the builtin ``EOFError``) itself. Returns ``line: name``. Out of scope, stated: a name imported under another
    name, or bound to a variable first."""
    faults = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.ExceptHandler) or node.type is None:
            continue
        for part in ast.walk(node.type):
            if isinstance(part, ast.Attribute) and isinstance(part.value, ast.Name):
                key = (part.value.id, part.attr)
            elif isinstance(part, ast.Name):
                key = (None, part.id)
            else:
                continue
            if key in ERRORS:
                faults.append("%d: %s" % (node.lineno, ".".join(k for k in key if k)))
    return faults


class Register(unittest.TestCase):
    def test_no_reader_writes_its_own_list(self):
        found = {p: f for p, f in ((p, own_archive_lists(src)) for p, src in sources().items()) if f}
        self.assertEqual(found, {})

    def test_the_register_sees_a_list(self):
        for text in ("try:\n    pass\nexcept (tarfile.TarError, OSError):\n    pass\n",
                     "try:\n    pass\nexcept zlib.error as exc:\n    pass\n",
                     "try:\n    pass\nexcept (EOFError, ValueError):\n    pass\n",
                     "try:\n    pass\nexcept zipfile.BadZipFile:\n    pass\n"):
            with self.subTest(text=text):
                self.assertNotEqual(own_archive_lists(text), [])
        self.assertEqual(own_archive_lists("try:\n    pass\nexcept (*cli.ARCHIVE_ERRORS, OSError):\n    pass\n"
                                           "try:\n    pass\nexcept tarfile.FilterError:\n    pass\n"), [])


if __name__ == "__main__":
    unittest.main()
