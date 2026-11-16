"""mcp/gdbsession.py against a stand-in gdb, without an emulator.

Every wait on gdb ends within its timeout, a gdb that exited is an error on
the next call, and detach ends the session the one way Eden's stub survives:
watchpoints deleted, the game resumed, no `detach` or `quit` sent.
    mcp/.venv/bin/python -m unittest discover -s tools -p test_gdbsession.py
"""
import os
import signal
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "mcp"))

import gdbsession  # noqa: E402

# Speaks just enough gdb: a prompt, `target remote`, a foreground `c` that
# ends on Ctrl-C. FAKE_GDB picks a fault: refuse (no stub), hang (the stub
# never answers), deaf (the game never stops on Ctrl-C).
FAKE_GDB = r'''
import os, signal, sys, time
mode = os.environ.get("FAKE_GDB", "")
log = open(os.environ["FAKE_GDB_LOG"], "a")
interrupted = False
def on_interrupt(*_):
    global interrupted
    interrupted = mode != "deaf"
signal.signal(signal.SIGINT, on_interrupt)
while True:
    sys.stdout.write("(gdb) "); sys.stdout.flush()
    line = sys.stdin.readline().strip()
    log.write(line + "\n"); log.flush()
    if line.startswith("target remote"):
        if mode == "hang":
            time.sleep(60)
        print("could not connect: Connection timed out." if mode == "refuse" else "Remote debugging using 127.0.0.1:1\n0x80000000 in ?? ()")
    elif line == "c":
        print("Continuing."); sys.stdout.flush()
        while not interrupted:
            time.sleep(0.01)
        interrupted = False
        print('\nThread 1 "MainThread" received signal SIGINT, Interrupt.')
    elif line == "p 1":
        print("$1 = 1")
'''


class Session(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        fake = Path(tmp.name) / "fake_gdb.py"
        fake.write_text(FAKE_GDB)
        self.sent = Path(tmp.name) / "sent.log"
        self.env = {"FAKE_GDB_LOG": str(self.sent), "FAKE_GDB": ""}
        for patcher in (mock.patch.object(gdbsession, "GDB", [sys.executable, str(fake)]), mock.patch.dict(os.environ, self.env)):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.gdb = gdbsession.GdbSession()
        self.addCleanup(self.gdb.drop)

    def fault(self, mode):
        os.environ["FAKE_GDB"] = mode

    def commands(self):
        return self.sent.read_text().split("\n")[:-1]

    def within(self, seconds, fn, *args):
        """fn raises RuntimeError, and does so in time."""
        t = time.time()
        with self.assertRaises(RuntimeError) as raised:
            fn(*args)
        self.assertLess(time.time() - t, seconds)
        return str(raised.exception)

    def test_detach_resumes_and_a_second_attach_connects(self):
        self.assertIn("Remote debugging using", self.gdb.attach("127.0.0.1", 1))
        self.gdb.continue_()
        self.assertEqual(self.gdb.detach(), "detached; the game keeps running")
        self.assertFalse(self.gdb.alive())
        self.assertEqual(self.commands()[-3:], ["c", "delete", "continue &"])   # Ctrl-C stopped it in between
        self.assertIn("Remote debugging using", self.gdb.attach("127.0.0.1", 1))
        self.assertFalse(self.gdb.running)
        for word in ("detach", "quit", "kill", "disconnect"):
            self.assertNotIn(word, self.commands())

    def test_a_stub_that_does_not_take_the_connection_is_an_error(self):
        self.fault("refuse")
        error = self.within(5, self.gdb.attach, "127.0.0.1", 1)
        self.assertIn("did not take the connection: could not connect", error)
        self.assertFalse(self.gdb.alive())

    def test_a_stub_that_never_answers_ends_at_the_timeout(self):
        self.fault("hang")
        self.assertIn("no gdb prompt within 1 s of `target remote", self.within(4, self.gdb.attach, "127.0.0.1", 1, 1))
        self.assertFalse(self.gdb.alive())

    def test_interrupt_gives_up_at_its_timeout(self):
        self.fault("deaf")
        self.gdb.attach("127.0.0.1", 1)
        self.gdb.continue_()
        self.assertIn("did not report a stop", self.within(3, self.gdb.interrupt, 1))
        self.assertTrue(self.gdb.running)
        self.assertIn("could not be deleted", self.gdb.detach(1))   # the way out still works
        self.assertFalse(self.gdb.alive())

    def test_interrupt_and_wait_stop(self):
        self.gdb.attach("127.0.0.1", 1)
        self.assertEqual(self.gdb.interrupt(), "already stopped")
        self.gdb.continue_()
        self.assertEqual(self.gdb.wait_stop(0.3), "still running (no hit within timeout)")
        with self.assertRaises(RuntimeError):
            self.gdb.cmd("p 1")
        self.assertIn("SIGINT", self.gdb.interrupt(5))
        self.assertEqual(self.gdb.cmd("p 1"), "$1 = 1")

    def test_a_gdb_that_exited_is_an_error_on_the_next_call(self):
        for call in (lambda: self.gdb.cmd("p 1"), self.gdb.interrupt, self.gdb.wait_stop, self.gdb.continue_):
            self.gdb.attach("127.0.0.1", 1)
            self.gdb.continue_() if call in (self.gdb.interrupt, self.gdb.wait_stop) else None
            os.kill(self.gdb.child.pid, signal.SIGKILL)
            self.gdb.child.wait()
            self.assertIn("gdb exited", self.within(3, call))
            self.assertEqual(self.within(1, call), "not attached")

    def test_commands_that_break_eden_are_refused(self):
        self.gdb.attach("127.0.0.1", 1)
        before = self.commands()
        for cmd in ("break *0x80000000", "tb main", "handle SIGTRAP nostop pass", "detach", "quit", "kill", "disconnect"):
            with self.assertRaises(ValueError, msg=cmd):
                self.gdb.cmd(cmd)
        self.assertEqual(self.commands(), before)


if __name__ == "__main__":
    unittest.main()
