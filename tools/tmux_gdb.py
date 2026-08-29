#!/usr/bin/env python3
"""Drive the persistent `eden-gdb` tmux GDB session from a script.

The MCP GDB tools are fine for single commands, but a call the host moves
to the background (>120 s) wedges that server's channel for the rest of
the session. Loops of "continue, wait for the watchpoint, read fields" go
through tmux instead: `cmd` sends one GDB command and returns its output
once the `(gdb)` prompt is back.

    from tmux_gdb import cmd, interrupt, cont_and_wait, player_ptr
    interrupt()
    cmd('watch *(int*)0x2194285d58')
    for _ in range(10):
        stop = cont_and_wait(30)          # None on timeout (game still running)
        print(cmd('x/2fw 0x2194285d58'))
    cmd('delete'); cont()

CLI: python3 tmux_gdb.py cmd "x/2fw 0x..."   |  interrupt  |  cont  |  wait [secs]
Assumes the session exists (SKILL.md section 3). Never send `break`.
"""
from __future__ import annotations

import struct
import subprocess
import sys
import time

SESSION = "eden-gdb"
STATUS_BIN = "/mnt/c/Users/nico/AppData/Roaming/eden/sdmc/smm2-hooks/status.bin"


def pane() -> str:
    return subprocess.run(["tmux", "capture-pane", "-t", SESSION, "-p", "-S", "-200"],
                          capture_output=True, text=True).stdout


def at_prompt() -> bool:
    lines = pane().rstrip("\n").split("\n")
    return bool(lines) and lines[-1].strip() == "(gdb)"


def _send(keys: str, enter: bool = True) -> None:
    args = ["tmux", "send-keys", "-t", SESSION, keys]
    if enter:
        args.append("Enter")
    subprocess.run(args, check=True)


def cmd(command: str, timeout: float = 30) -> str:
    """Send one GDB command; return its output (text between the echo and the next prompt)."""
    if command.strip().split()[0] in ("b", "br", "bre", "brea", "break", "tb", "tbreak"):
        raise ValueError("software breakpoints bake into Eden's code cache; use watch")
    before = pane()
    _send(command)
    t0 = time.time()
    while time.time() - t0 < timeout:
        time.sleep(0.3)
        if at_prompt():
            p = pane()
            idx = p.rfind("(gdb) " + command)
            out = p[idx + len("(gdb) " + command):] if idx >= 0 else p[len(before):]
            return out.strip().rsplit("(gdb)", 1)[0].strip()
    return "TIMEOUT: " + pane()[-600:]


def interrupt(timeout: float = 15) -> bool:
    _send("C-c", enter=False)
    t0 = time.time()
    while time.time() - t0 < timeout:
        time.sleep(0.3)
        if at_prompt():
            return True
    return False


def cont() -> None:
    _send("c")


def cont_and_wait(timeout: float = 30) -> str | None:
    """Continue and wait for a stop; None if the game is still running at the timeout."""
    _send("c")
    t0 = time.time()
    while time.time() - t0 < timeout:
        time.sleep(0.2)
        if at_prompt():
            p = pane()
            idx = p.rfind("(gdb) c\n")
            return p[idx + 8:].rsplit("(gdb)", 1)[0].strip()
    return None


def player_ptr() -> int:
    """PlayerObject* the hooks last saw (status.bin+0x68)."""
    return struct.unpack_from("<Q", open(STATUS_BIN, "rb").read(), 0x68)[0]


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    if argv[0] == "cmd":
        print(cmd(" ".join(argv[1:])))
    elif argv[0] == "interrupt":
        print("stopped" if interrupt() else "no prompt")
    elif argv[0] == "cont":
        cont()
    elif argv[0] == "wait":
        print(cont_and_wait(float(argv[1]) if len(argv) > 1 else 30) or "still running")
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
