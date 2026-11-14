"""What a contained command tries, for tests 20 and 21. argv is a list of steps, each OP and its arguments:

    write PATH DATA | connect HOST PORT | env PATH | symlink TARGET PATH | mkfifo PATH | listdir DIR PATH
    sleep SECONDS | exit CODE

Each step's outcome is printed as one JSON line; a refused step is recorded and the next one runs. The
probe's own report is only a hint: tests judge by what they measure outside the container.
"""

import json
import os
import socket
import sys
import time

ARITY = {"write": 2, "connect": 2, "env": 1, "symlink": 2, "mkfifo": 1, "listdir": 2, "sleep": 1, "exit": 1}


def step(op, args):
    if op == "write":
        with open(args[0], "w") as fh:
            fh.write(args[1])
    elif op == "connect":
        with socket.create_connection((args[0], int(args[1])), timeout=3) as s:
            s.sendall(b"canary")
    elif op == "env":
        with open(args[0], "w") as fh:
            json.dump(dict(os.environ), fh)
    elif op == "symlink":
        os.symlink(args[0], args[1])
    elif op == "mkfifo":
        os.mkfifo(args[0])
    elif op == "listdir":
        with open(args[1], "w") as fh:
            json.dump(sorted(os.listdir(args[0])), fh)
    elif op == "sleep":
        time.sleep(float(args[0]))
    elif op == "exit":
        sys.stdout.flush()
        os._exit(int(args[0]))


argv = sys.argv[1:]
while argv:
    op, args, argv = argv[0], argv[1:1 + ARITY[argv[0]]], argv[1 + ARITY[argv[0]]:]
    try:
        step(op, args)
        print(json.dumps({"op": op, "ok": True}))
    except OSError as exc:
        print(json.dumps({"op": op, "ok": False, "errno": exc.errno}))
