#!/usr/bin/env python3
"""
Automated Eden GDB operations. Connects, does the job, disconnects.
Handles Eden's quirky GDB stub (stale breakpoints, SIGTRAP noise).

Usage:
    python3 eden_gdb_auto.py get-player       # Find player object pointer
    python3 eden_gdb_auto.py read-player ADDR  # Read player fields at ADDR
    python3 eden_gdb_auto.py watch ADDR SIZE   # Set hw watchpoint, wait for hit, report
    python3 eden_gdb_auto.py find-func         # Find changeState address
"""

import subprocess
import sys
import time
import re
import os
import json

TMUX_SESSION = "eden-gdb"
STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".eden_state.json")

# changeState byte signature (position-independent)
CHANGE_STATE_SIG = "0xf6, 0x57, 0xbd, 0xa9, 0xf4, 0x4f, 0x01, 0xa9, 0xfd, 0x7b, 0x02, 0xa9, 0xfd, 0x83, 0x00, 0x91, 0x08, 0x08, 0x40, 0xb9, 0xf3, 0x03, 0x01, 0x2a"


def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    return {}


def save_state(state):
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f, indent=2)


def tmux_send(cmd, wait=1.0):
    """Send command to eden-gdb tmux session."""
    subprocess.run(["tmux", "send-keys", "-t", TMUX_SESSION, cmd, "Enter"],
                   capture_output=True, timeout=5)
    time.sleep(wait)


def tmux_read(lines=30):
    """Read tmux pane output."""
    result = subprocess.run(
        ["tmux", "capture-pane", "-t", TMUX_SESSION, "-p", "-S", f"-{lines}"],
        capture_output=True, text=True, timeout=5
    )
    return result.stdout


def tmux_alive():
    """Check if tmux session exists."""
    result = subprocess.run(["tmux", "has-session", "-t", TMUX_SESSION],
                           capture_output=True)
    return result.returncode == 0


def gdb_at_prompt():
    """Check if GDB is at (gdb) prompt (not running)."""
    output = tmux_read(5)
    lines = output.strip().split('\n')
    return any(line.strip() == '(gdb)' for line in lines[-3:])


def ensure_gdb():
    """Ensure GDB is connected and at prompt."""
    if not tmux_alive():
        print("ERROR: No eden-gdb tmux session. Start one first:")
        print("  tmux new-session -d -s eden-gdb")
        print("  Then connect GDB manually or run with --connect")
        sys.exit(1)

    if not gdb_at_prompt():
        # Try interrupting
        subprocess.run(["tmux", "send-keys", "-t", TMUX_SESSION, "", "C-c"],
                       capture_output=True, timeout=5)
        time.sleep(2)
        if not gdb_at_prompt():
            print("ERROR: GDB not at prompt. Game might be running.")
            print("Interrupt with: tmux send-keys -t eden-gdb C-c")
            sys.exit(1)


def gdb_cmd(cmd, wait=1.0, expect_pattern=None, timeout=10):
    """Send GDB command and return new output."""
    before = tmux_read(50)
    tmux_send(cmd, wait)

    if expect_pattern:
        deadline = time.time() + timeout
        while time.time() < deadline:
            after = tmux_read(50)
            new = after[len(before):] if after.startswith(before[:20]) else after
            if re.search(expect_pattern, new):
                return new
            time.sleep(0.5)
        return tmux_read(50)

    return tmux_read(50)


def cmd_find_func():
    """Find changeState address via byte pattern search."""
    ensure_gdb()

    print("Searching for changeState...")
    output = gdb_cmd(
        f"find /b 0x80800000, 0x82000000, {CHANGE_STATE_SIG}",
        wait=5, expect_pattern=r"pattern found|Pattern not found", timeout=30
    )

    # Parse address from output
    for line in output.split('\n'):
        line = line.strip()
        if re.match(r'^0x[0-9a-f]+$', line):
            addr = int(line, 16)
            print(f"changeState: {addr:#x}")
            state = load_state()
            state['changeState'] = hex(addr)
            save_state(state)
            return addr

    print("ERROR: changeState not found")
    sys.exit(1)


def cmd_get_player(max_attempts=5):
    """Set breakpoint on changeState, get player pointer, clean up."""
    state = load_state()
    cs_addr = state.get('changeState')
    if not cs_addr:
        cs_addr = hex(cmd_find_func())
    else:
        print(f"Using cached changeState: {cs_addr}")

    ensure_gdb()

    print(f"Setting HW breakpoint at {cs_addr}...")
    # MUST use hbreak — Eden's GDB stub doesn't remove software breakpoints properly!
    gdb_cmd(f"hbreak *{cs_addr}", wait=0.5)

    print("Continuing... (need gameplay state change)")
    gdb_cmd("c", wait=0.5)

    # Wait for breakpoint hit on MainThread
    deadline = time.time() + 30
    player = None
    attempt = 0

    while time.time() < deadline and attempt < max_attempts:
        time.sleep(2)
        output = tmux_read(20)

        if 'hit Breakpoint' in output or 'SIGTRAP' in output:
            attempt += 1
            # Check if we're at prompt
            if not gdb_at_prompt():
                time.sleep(1)
                if not gdb_at_prompt():
                    continue

            # Read registers
            gdb_cmd("p/x $x0", wait=0.3)
            gdb_cmd("p/x $x1", wait=0.3)
            output = tmux_read(10)

            # Parse x0 and x1
            x0_match = re.search(r'\$\d+ = (0x[0-9a-f]+)', output)
            x1_match = re.findall(r'\$\d+ = (0x[0-9a-f]+)', output)

            if x0_match and len(x1_match) >= 2:
                x0 = int(x0_match.group(1), 16)
                x1 = int(x1_match[1], 16)

                # Player states are 1-143. If state > 143, this isn't the player's SM
                if x1 <= 143:
                    player = x0 - 0x3F0
                    print(f"StateMachine: {x0:#x}, state: {x1}, PlayerObject: {player:#x}")
                    state['player_object'] = hex(player)
                    state['state_machine'] = hex(x0)
                    save_state(state)
                    break
                else:
                    print(f"  attempt {attempt}: state {x1} > 143, not player SM. Continuing...")

            # Continue to next hit
            gdb_cmd("c", wait=0.5)

    # Clean up: delete breakpoint, continue
    print("Cleaning up...")
    gdb_cmd(f"delete", wait=0.3)
    gdb_cmd("c", wait=0.5)

    # Verify game is running
    time.sleep(1)
    output = tmux_read(5)
    if 'SIGTRAP' in output and gdb_at_prompt():
        # Stale breakpoint hit — step past and continue
        print("Clearing stale breakpoint...")
        gdb_cmd("si", wait=0.3)
        gdb_cmd("c", wait=0.5)

    if player:
        print(f"\n✅ PlayerObject: {player:#x}")
        print(f"   current_state: {player:#x} + 0x3F8 = {player + 0x3F8:#x}")
        print(f"   pos_x:         {player:#x} + 0x230 = {player + 0x230:#x}")
        print(f"   powerup_id:    {player:#x} + 0x4A8 = {player + 0x4A8:#x}")
    else:
        print("❌ Could not find player object. Is Mario active in gameplay?")

    return player


def cmd_read_player(addr_str):
    """Read player fields at given address."""
    addr = int(addr_str, 0)
    ensure_gdb()

    fields = [
        (0x230, 'f', 'pos_x'),
        (0x234, 'f', 'pos_y'),
        (0x238, 'f', 'pos_z'),
        (0x3F8, 'w', 'current_state'),
        (0x3FC, 'w', 'state_frames'),
        (0x4A8, 'w', 'powerup_id'),
    ]

    print(f"Reading PlayerObject at {addr:#x}:")
    for offset, fmt, name in fields:
        field_addr = addr + offset
        if fmt == 'f':
            gdb_cmd(f"x/1fw {field_addr:#x}", wait=0.3)
        else:
            gdb_cmd(f"x/1wx {field_addr:#x}", wait=0.3)

    output = tmux_read(20)
    print(output)


def cmd_watch(addr_str, size_str="4"):
    """Set hardware watchpoint, wait for hit, show backtrace."""
    addr = int(addr_str, 0)
    size = int(size_str)
    ensure_gdb()

    print(f"Setting write watchpoint on {addr:#x} ({size} bytes)...")
    gdb_cmd(f"watch *{addr:#x}", wait=0.5)
    output = tmux_read(5)

    if 'Hardware watchpoint' not in output:
        print("ERROR: Watchpoint not set. Output:")
        print(output)
        return

    print("Continuing... waiting for watchpoint hit (30s timeout)")
    gdb_cmd("c", wait=0.5)

    deadline = time.time() + 30
    while time.time() < deadline:
        time.sleep(1)
        if gdb_at_prompt():
            output = tmux_read(20)
            if 'watchpoint' in output.lower() or 'SIGTRAP' in output:
                print("Watchpoint hit!")
                # Read PC and backtrace
                gdb_cmd("p/x $pc", wait=0.3)
                gdb_cmd("bt 10", wait=0.5)
                gdb_cmd("info reg x0 x1 x2 x3", wait=0.3)
                result = tmux_read(30)
                print(result)

                # Clean up
                gdb_cmd("delete", wait=0.3)
                gdb_cmd("c", wait=0.5)
                return

    print("Timeout — no watchpoint hit in 30s")
    gdb_cmd("delete", wait=0.3)
    gdb_cmd("c", wait=0.5)


COMMANDS = {
    'find-func': (cmd_find_func, []),
    'get-player': (cmd_get_player, []),
    'read-player': (cmd_read_player, ['addr']),
    'watch': (cmd_watch, ['addr', '[size=4]']),
}


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print("Eden GDB Automation")
        print(f"\nUsage: {sys.argv[0]} <command> [args]")
        print("\nCommands:")
        for name, (fn, args) in COMMANDS.items():
            print(f"  {name:15s} {' '.join(args)}")
        print(f"\nRequires tmux session '{TMUX_SESSION}' with GDB connected.")
        sys.exit(0)

    cmd = sys.argv[1]
    fn, _ = COMMANDS[cmd]
    fn(*sys.argv[2:])


if __name__ == '__main__':
    main()
