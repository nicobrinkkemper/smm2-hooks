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

# ── stub boot with hang detection ─────────────────────────────────────────
# With the gdb stub on, Eden sometimes hangs at the launch screen: the stub
# accepts the attach and the continue, but the guest never starts (the frame
# counter in status.bin stays absent/frozen; on screen the launch logo just
# sits there). A blind wait for the title cannot tell that apart from a slow
# boot, so this helper verifies frames ADVANCE after the continue, re-sends
# the continue once, and kills/relaunches once before failing loudly.

def _frames() -> int | None:
    try:
        with open(STATUS_BIN, "rb") as f:
            return struct.unpack("<I", f.read(4))[0]
    except Exception:
        return None


def _frames_advancing(seconds: float = 20.0) -> bool:
    start = _frames()
    deadline = time.time() + seconds
    while time.time() < deadline:
        time.sleep(1.0)
        now = _frames()
        if now is not None and start is not None and now > start:
            return True
        if now is not None and start is None:
            start = now
    return False


def _gateway() -> str:
    out = subprocess.run(["sh", "-c", "ip route | awk '/default/ {print $3}'"],
                         capture_output=True, text=True).stdout.strip()
    return out or "127.0.0.1"


def boot_stub(max_relaunches: int = 1) -> bool:
    """Launch Eden with the stub, attach, continue, and verify the guest runs.

    Returns True once frames advance. On a launch hang: re-sends the
    continue, then kills and relaunches (up to max_relaunches). Prints what
    it saw either way — a hang is a loud failure, not a long wait.
    """
    sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent / "mcp"))
    import eden  # noqa: WPS433

    for attempt in range(max_relaunches + 1):
        eden.kill()
        subprocess.run(["tmux", "kill-session", "-t", SESSION], capture_output=True)
        time.sleep(2)
        r = eden.launch(eden.paths(), gdb=True)
        if not r.get("process"):
            print(f"boot_stub: launch failed: {r}")
            return False
        time.sleep(15)
        subprocess.run(["tmux", "new-session", "-d", "-s", SESSION], check=True)
        subprocess.run(["tmux", "send-keys", "-t", SESSION,
                        f"gdb-multiarch -nx -ex 'target remote {_gateway()}:6543' "
                        "-ex 'set confirm off' -ex 'set pagination off'", "Enter"], check=True)
        time.sleep(8)
        cont()
        if _frames_advancing(20):
            print(f"boot_stub: guest running (attempt {attempt + 1})")
            return True
        print(f"boot_stub: frames frozen after continue (attempt {attempt + 1}); re-sending c")
        cont()
        if _frames_advancing(15):
            print("boot_stub: guest running after the second continue")
            return True
        print("boot_stub: LAUNCH HANG — the stub accepted the attach but the guest never started")
    eden.kill()
    subprocess.run(["tmux", "kill-session", "-t", SESSION], capture_output=True)
    return False
