"""No test of the seed waits on a real delay (E751). Every test module of this folder imports this module first.

A retry, backoff or poll delay the seed's own code sleeps (`launch.gh_read`'s GH_RETRY_DELAYS_S, the launcher's
waits, `deliver_epoch`'s polls) is the clock of the outside world, which a test mocks (`tohum/04:38`). A test that
reached one unmocked slept for real: with the accepted manifest's read back on its retry delays (mutant
`manifest_read_retries`) the whole suite ran past `mutate.MUTANT_TIMEOUT_S` and the mutant was recorded as timed out,
not killed (E679, E738). Importing this module replaces `time.sleep` for the whole process with `guarded_sleep`: a
positive sleep called from a file outside this folder and outside the standard library raises RealDelay at once, so
the test is red in its first second instead of waiting. A test's own short poll (a file of this folder) and the
standard library's (`subprocess`'s waits) still sleep; a test that mocks `time.sleep` replaces the guard only inside
its patch. In a worker thread RealDelay ends only that thread; `threading.excepthook` records it and the test it
happened in ends with that error (`TestResult.stopTest`), so a thread cannot turn the red into a pass.

What it does not see: a wait that is not `time.sleep` (`threading.Event.wait`, `Condition.wait`, `select`, a
`Popen.wait` or `communicate` timeout); a `time.sleep` the standard library makes on the seed's behalf (`sched`,
`subprocess`), since its caller is the standard library; a child process (`sys.executable` children do not import
this module); and code installed under the standard library's path, which counts as standard library (on CI's
setup-python, with no virtual environment, `site-packages` lies under `lib/python3.12`). Today the seed has none of
these delays (its one thread, `rival.py`'s pump, never sleeps; its one `Event.wait` is a 0.05 s poll on a live child).
"""
from __future__ import annotations

import sys
import sysconfig
import threading
import time
import unittest
from pathlib import Path

TESTS = Path(__file__).resolve().parent
STDLIB = tuple({Path(sysconfig.get_paths()[key]).resolve() for key in ("stdlib", "platstdlib")})
REAL_SLEEP = getattr(time.sleep, "real_sleep", time.sleep)  # the real one, even if this module is loaded twice
THREAD_DELAYS: list[BaseException] = []  # RealDelay raised in a worker thread, until the running test ends


class RealDelay(BaseException):
    """A sleep the code under test would wait for real. A BaseException, not an Exception: a retry loop or a cycle's
    `except Exception` cannot swallow it, and unittest reports it as the test's error."""


def may_sleep(path: Path) -> bool:
    """A file of this folder (the test's own poll) or of the standard library (`subprocess`'s waits)."""
    return path.is_relative_to(TESTS) or any(path.is_relative_to(root) for root in STDLIB)


def guarded_sleep(seconds: float) -> None:
    caller = sys._getframe(1).f_code.co_filename
    if seconds > 0 and not may_sleep(Path(caller).resolve()):
        raise RealDelay(f"{caller} would sleep {seconds} s for real in a test: mock its clock (E751)")
    REAL_SLEEP(seconds)


def thread_hook(args, _next=threading.excepthook) -> None:
    if isinstance(args.exc_value, RealDelay):
        THREAD_DELAYS.append(args.exc_value)
    _next(args)


def stop_test(self, test, _next=unittest.TestResult.stopTest) -> None:
    """The test ends with the RealDelay a worker thread raised while it ran."""
    while THREAD_DELAYS:
        exc = THREAD_DELAYS.pop(0)
        self.addError(test, (type(exc), exc, exc.__traceback__))
    _next(self, test)


guarded_sleep.real_sleep = REAL_SLEEP
time.sleep = guarded_sleep
if not getattr(threading.excepthook, "guards_delays", False):
    thread_hook.guards_delays = True
    threading.excepthook = thread_hook
    unittest.TestResult.stopTest = stop_test
