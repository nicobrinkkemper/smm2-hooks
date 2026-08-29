"""A GDB session the server owns: one gdb-multiarch child, hardware breakpoints only."""
from __future__ import annotations

import re
import pexpect

PROMPT = r"\(gdb\) $"
FORBIDDEN = re.compile(r"^\s*((b|br|bre|brea|break|tb|tbreak)(\s|$)|handle\s+SIGTRAP.*\bpass\b)", re.I)
CSV_BASE = 0x7100000000


class GdbSession:
    def __init__(self) -> None:
        self.child: pexpect.spawn | None = None
        self.running = False
        self.base: int | None = None
        self.log: list[str] = []

    # ── lifecycle ─────────────────────────────────────────────────────────
    def attach(self, host: str, port: int, timeout: float = 20) -> str:
        if self.child and self.child.isalive():
            return "already attached"
        self.child = pexpect.spawn("gdb-multiarch", ["-nx", "-q"], encoding="utf-8", timeout=timeout, echo=False)
        self.child.expect(PROMPT)
        out = self._cmd(f"target remote {host}:{port}", timeout)
        self._cmd("set confirm off", 5)
        self._cmd("set pagination off", 5)
        self.running = False
        return out

    def detach(self) -> str:
        if not self.child:
            return "not attached"
        try:
            if self.running:
                self.interrupt(5)
            self._cmd("delete", 5)
            self._cmd("detach", 10)
        finally:
            try:
                self.child.sendline("quit")
                self.child.close(force=True)
            except Exception:
                pass
            self.child = None
            self.running = False
            self.base = None
        return "detached"

    def alive(self) -> bool:
        return bool(self.child and self.child.isalive())

    # ── commands ──────────────────────────────────────────────────────────
    def _cmd(self, cmd: str, timeout: float) -> str:
        assert self.child
        self.child.sendline(cmd)
        self.child.expect(PROMPT, timeout=timeout)
        out = self.child.before or ""
        out = out.replace("\r", "").strip()
        self.log.append(f"> {cmd}\n{out}")
        return out

    def cmd(self, cmd: str, timeout: float = 15) -> str:
        if not self.alive():
            raise RuntimeError("not attached")
        if FORBIDDEN.match(cmd):
            raise ValueError("software breakpoints and passing SIGTRAP are not allowed (Eden bakes them into its code cache); use hbreak/watch")
        if self.running:
            raise RuntimeError("target is running; call gdb_interrupt or gdb_wait_stop first")
        if re.match(r"^\s*(c|cont|continue)\b", cmd):
            return self.continue_()
        return self._cmd(cmd, timeout)

    def continue_(self) -> str:
        if not self.alive():
            raise RuntimeError("not attached")
        assert self.child
        self.child.sendline("c")
        self.running = True
        return "running"

    def interrupt(self, timeout: float = 10) -> str:
        if not self.alive():
            raise RuntimeError("not attached")
        assert self.child
        if not self.running:
            return "already stopped"
        self.child.sendcontrol("c")
        self.child.expect(PROMPT, timeout=timeout)
        self.running = False
        return (self.child.before or "").replace("\r", "").strip()

    def wait_stop(self, timeout: float = 30) -> str:
        """Wait for a breakpoint/watchpoint hit (or the connection to drop)."""
        if not self.alive():
            raise RuntimeError("not attached")
        assert self.child
        if not self.running:
            return "already stopped"
        try:
            self.child.expect(PROMPT, timeout=timeout)
        except pexpect.TIMEOUT:
            return "still running (no hit within timeout)"
        except pexpect.EOF:
            self.running = False
            return "gdb exited (connection dropped?)"
        self.running = False
        return (self.child.before or "").replace("\r", "").strip()

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
