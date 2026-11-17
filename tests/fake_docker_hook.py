"""Child side of ``fake_docker``: block what the container flags forbid, then run the Python command.

argv: CONFIG_JSON SCRIPT [ARG ...]; CONFIG_JSON is {network, read_only, rw: [host dirs], ro: [host dirs]}.
"""

import errno
import json
import os
import runpy
import sys

CFG = json.loads(sys.argv[1])
RW = [os.path.realpath(p) for p in CFG["rw"]]
RO = [os.path.realpath(p) for p in CFG["ro"]]
WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND
PATH_EVENTS = {"os.remove": (0,), "os.rmdir": (0,), "os.mkdir": (0,), "os.chmod": (0,), "os.truncate": (0,),
               "os.utime": (0,), "os.rename": (0, 1), "os.symlink": (1,), "os.link": (1,), "os.mkfifo": (0,),
               "os.mknod": (0,), "os.chown": (0,)}


def _under(path, roots):
    return any(path == r or path.startswith(r + os.sep) for r in roots)


def _writable(path):
    if isinstance(path, bytes):
        path = os.fsdecode(path)
    real = os.path.realpath(path)
    if _under(real, RO):
        return False
    if _under(real, RW):
        return True
    return not CFG["read_only"]


def _deny(path):
    raise PermissionError(errno.EROFS, "Read-only file system", path)


def hook(event, args):
    if event == "open":
        path, mode, flags = args
        if isinstance(path, int) or path is None:
            return
        wants = (isinstance(mode, str) and any(c in mode for c in "wax+")) or bool((flags or 0) & WRITE_FLAGS)
        if wants and not _writable(path):
            _deny(path)
    elif event in PATH_EVENTS:
        for i in PATH_EVENTS[event]:
            if i < len(args) and isinstance(args[i], (str, bytes)) and not _writable(args[i]):
                _deny(args[i])
    elif event == "socket.connect" and CFG["network"] == "none":
        raise OSError(errno.ENETUNREACH, "Network is unreachable")


sys.addaudithook(hook)
sys.argv = sys.argv[2:]
runpy.run_path(sys.argv[0], run_name="__main__")
