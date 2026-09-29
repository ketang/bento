"""Test-suite guard: tests must never read the runner's stdin.

If the runner's stdin is an open never-EOF stream (agent shells, sockets),
any test that reads sys.stdin or spawns a child that inherits fd 0 hangs
forever. Replace sys.stdin with an empty stream and default subprocess stdin
to DEVNULL; tests needing input pass it explicitly (input=... / stdin=PIPE).
"""
import io
import subprocess
import sys

sys.stdin = io.StringIO("")

_orig_popen_init = subprocess.Popen.__init__


def _popen_init(self, *args, **kwargs):
    if kwargs.get("stdin") is None and len(args) < 3:
        kwargs["stdin"] = subprocess.DEVNULL
    _orig_popen_init(self, *args, **kwargs)


subprocess.Popen.__init__ = _popen_init
