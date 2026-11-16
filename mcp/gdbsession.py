"""A GDB session the server owns: one gdb-multiarch child on Eden's stub.

Every wait on the child has a timeout and ends in a RuntimeError the caller
can show: no prompt in time, or gdb gone. Nothing here blocks without one.
"""
from __future__ import annotations

import re
import signal

import pexpect

GDB = ["gdb-multiarch", "-nx", "-q"]
PROMPT = r"\(gdb\) (?:\x1b\[\?2004h)?\s*$"   # readline may append its bracketed-paste enable right after the prompt
FORBIDDEN = re.compile(r"^\s*(?:(?:b|br|bre|brea|break|tb|tbreak)(?:\s|$)|handle\s+SIGTRAP.*\bpass\b)", re.I)
ENDS_SESSION = re.compile(r"^\s*(?:detach|disconnect|k|kill|q|quit)\b", re.I)
CSV_BASE = 0x7100000000


def _clean(text: str | None) -> str:
    return re.sub(r"\x1b\[\?2004[hl]", "", text or "").replace("\r", "").strip()


class GdbSession:
    def __init__(self) -> None:
        self.child: pexpect.spawn | None = None
        self.running = False
        self.base: int | None = None
        self.log: list[str] = []

    # ── lifecycle ─────────────────────────────────────────────────────────
    def attach(self, host: str, port: int, timeout: float = 20) -> str:
        """Connect to the stub, which stops the game. Works again after detach
        in the same launch."""
        if self.alive():
            return "already attached"
        self.drop()
        self.child = pexpect.spawn(GDB[0], GDB[1:], encoding="utf-8", timeout=timeout, echo=False)
        try:
            self._prompt(timeout, "starting gdb")
            self._cmd("set confirm off", 5)
            self._cmd("set pagination off", 5)
            self._cmd(f"set tcp connect-timeout {max(1, int(timeout) - 5)}", 5)   # gdb gives up before we do, and says why
            out = self._cmd(f"target remote {host}:{port}", timeout)
        except RuntimeError:
            self.drop()
            raise
        if "Remote debugging using" not in out:
            self.drop()
            raise RuntimeError(
                f"Eden's stub at {host}:{port} did not take the connection: {out.splitlines()[-1] if out else 'no output'}. "
                "It listens only while Eden runs a game with the stub on (eden_launch gdb=true), and no longer after "
                "gdb's own `detach` or `quit`: eden_kill and launch again")
        self.running = False
        return out

    def detach(self, timeout: float = 10) -> str:
        """Leave the game running without a debugger; attach again any time.

        Eden's stub does not know gdb's `detach` ("Remote doesn't know how to
        detach"), and after gdb's `detach` + `quit` the game stays frozen and
        the stub stops listening, which is why a second attach used to time
        out. A client that just disappears is fine: the stub keeps listening
        and takes the next connection (measured on Eden v0.2.1, 2026-11-16:
        second attach in 0.4 s, with the game running or stopped). So: delete
        the watchpoints, resume, and end gdb without a goodbye."""
        if not self.child:
            return "not attached"
        note = "the game keeps running"
        try:
            if self.running:
                self.interrupt(timeout)
            self._cmd("delete", 5)
            self._cmd("continue &", 5)   # in the background: the prompt comes back once the resume is sent
        except RuntimeError as e:
            note = f"the watchpoints could not be deleted and the game resumed first: {e}"
        self.drop()
        return f"detached; {note}"

    def drop(self) -> None:
        """End gdb without a word to the stub. SIGKILL on purpose: `quit`
        detaches or kills the target, and SIGINT is gdb's Ctrl-C, which stops
        the game."""
        child, self.child = self.child, None
        self.running = False
        self.base = None
        if child is None:
            return
        try:
            if child.isalive():
                child.kill(signal.SIGKILL)
            child.close(force=True)
        except Exception:  # noqa: BLE001
            pass

    def alive(self) -> bool:
        return bool(self.child and self.child.isalive())

    def _live(self) -> pexpect.spawn:
        if not self.child:
            raise RuntimeError("not attached")
        if not self.child.isalive():
            raise self._died()
        return self.child

    def _died(self) -> RuntimeError:
        child = self.child
        last = _clean(child.before if child and isinstance(child.before, str) else "")[-300:]
        status = child.signalstatus or child.exitstatus if child else None
        self.drop()
        return RuntimeError(f"gdb exited (status {status}); the session is gone, gdb_attach again. Last output: {last or 'none'}")

    # ── commands ──────────────────────────────────────────────────────────
    def _prompt(self, timeout: float, what: str) -> str:
        """Everything gdb printed up to its next prompt."""
        child = self._live()
        try:
            child.expect(PROMPT, timeout=timeout)
        except pexpect.TIMEOUT:
            raise RuntimeError(f"no gdb prompt within {timeout:g} s of {what}") from None
        except (pexpect.EOF, OSError):
            raise self._died() from None
        return _clean(child.before)

    def _cmd(self, cmd: str, timeout: float) -> str:
        child = self._live()
        try:
            while True:   # what a command that timed out printed since must not pass for this one's answer
                child.read_nonblocking(4096, timeout=0)
        except (pexpect.TIMEOUT, pexpect.EOF, OSError):
            pass
        child.sendline(cmd)
        out = self._prompt(timeout, f"`{cmd}`")
        self.log.append(f"> {cmd}\n{out}")
        return out

    def cmd(self, cmd: str, timeout: float = 15) -> str:
        self._live()
        if FORBIDDEN.match(cmd):
            raise ValueError("software breakpoints and passing SIGTRAP are not allowed (a deleted `break` keeps trapping in Eden's "
                             "compiled code, and the stub has no hardware breakpoints); use watch/rwatch/awatch")
        if ENDS_SESSION.match(cmd):
            raise ValueError("gdb's own detach/quit/kill freeze or end Eden and close its stub; use gdb_detach (the game keeps running) or eden_kill")
        if self.running:
            raise RuntimeError("target is running; call gdb_interrupt or gdb_wait_stop first")
        if re.match(r"^\s*(c|cont|continue)\b", cmd):
            return self.continue_()
        return self._cmd(cmd, timeout)

    def continue_(self) -> str:
        child = self._live()
        if not self.running:
            child.sendline("c")
            self.running = True
        return "running"

    def interrupt(self, timeout: float = 10) -> str:
        child = self._live()
        if not self.running:
            return "already stopped"
        child.sendcontrol("c")
        try:
            out = self._prompt(timeout, "Ctrl-C")
        except RuntimeError as e:
            if self.child:   # gdb is still there: the game did not stop
                raise RuntimeError(f"{e}: the game did not report a stop and still counts as running. gdb_interrupt again, "
                                   "gdb_detach to drop the session, or eden_kill") from None
            raise
        self.running = False
        return out

    def wait_stop(self, timeout: float = 30) -> str:
        """Wait for a watchpoint hit."""
        child = self._live()
        if not self.running:
            return "already stopped"
        try:
            child.expect(PROMPT, timeout=timeout)
        except pexpect.TIMEOUT:
            return "still running (no hit within timeout)"
        except (pexpect.EOF, OSError):
            raise self._died() from None
        self.running = False
        return _clean(child.before)

    # ── addresses ─────────────────────────────────────────────────────────
    def module_base(self, timeout: float = 20) -> dict:
        """Main module base via `mon get info` (yuzu/eden stub), else by signature."""
        out = self._cmd("mon get info", timeout)
        mods = re.findall(r"(0x[0-9a-fA-F]+)\s*-\s*(0x[0-9a-fA-F]+)\s+(\S+)", out)
        main = [m for m in mods if re.search(r"main|Slope", m[2])]
        if main:
            self.base = int(main[0][0], 16)
            return {"base": hex(self.base), "modules": [{"start": a, "end": b, "name": n} for a, b, n in mods], "method": "mon get info"}
        # fallback: StateMachine::changeState prologue at csv offset 0x8b9320
        sig = "0xf6, 0x57, 0xbd, 0xa9, 0xf4, 0x4f, 0x01, 0xa9, 0xfd, 0x7b, 0x02, 0xa9, 0xfd, 0x83, 0x00, 0x91, 0x08, 0x08, 0x40, 0xb9, 0xf3, 0x03, 0x01, 0x2a"
        out2 = self._cmd(f"find /b 0x80800000, 0x82000000, {sig}", 60)
        m = re.search(r"0x[0-9a-fA-F]+", out2)
        if not m:
            return {"base": None, "raw": out + "\n" + out2, "method": "signature (not found)"}
        self.base = int(m.group(0), 16) - 0x8B9320
        return {"base": hex(self.base), "method": "signature changeState", "raw": out2}

    def to_runtime(self, csv_addr: int) -> int:
        if self.base is None:
            raise RuntimeError("base unknown; call gdb_module_base first")
        return self.base + (csv_addr - CSV_BASE)

    def to_csv(self, runtime_addr: int) -> int:
        if self.base is None:
            raise RuntimeError("base unknown; call gdb_module_base first")
        return CSV_BASE + (runtime_addr - self.base)
