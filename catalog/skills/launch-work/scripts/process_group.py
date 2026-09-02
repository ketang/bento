"""Shared process-group containment for a `start_new_session=True` subprocess.

Used by both `wire-land-verifier.py` (validating a staged wrapper) and
`land-work-run-verifier.py` (running the installed verifier command at landing
time) so a future fix to a signal-handling edge case applies to both call
sites instead of drifting between two hand-copied implementations.
"""

from __future__ import annotations

import contextlib
import os
import signal
import subprocess


def kill_process_group(proc: subprocess.Popen) -> None:
    """Kill the whole process group `start_new_session=True` created, and reap it.

    Covers every exit from `communicate()`, not just a reported timeout: a
    KeyboardInterrupt or other interruption must still reach the group, or a
    gate that backgrounds work keeps running -- and can keep mutating the
    repo -- detached from this process after it's gone.
    """
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except ProcessLookupError:
        pass
    proc.communicate()  # reap; the group is dead so this cannot hang


@contextlib.contextmanager
def reap_group_on_sigterm(proc: subprocess.Popen):
    """Kill the process group on SIGTERM too, not just our own exceptions.

    `start_new_session=True` detaches `proc` into its own process group, so
    an external SIGTERM aimed only at *this* process's PID -- not a
    foreground Ctrl-C, which the terminal sends to the whole group -- never
    reaches it on its own. A Python exception handler cannot catch that
    either: the default SIGTERM disposition terminates the process before any
    `except`/`finally` gets a chance to run. Installing a handler for the
    duration of the call is what actually closes the gap.
    """

    def _on_term(signum: int, _frame: object) -> None:
        kill_process_group(proc)
        raise SystemExit(128 + signum)

    previous = signal.signal(signal.SIGTERM, _on_term)
    try:
        yield
    finally:
        signal.signal(signal.SIGTERM, previous)
