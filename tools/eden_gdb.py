#!/usr/bin/env python3
"""
Eden GDB client for SMM2 debugging.

Structured interface to Eden's GDB stub. Handles connection management,
address translation, breakpoints, watchpoints, and memory access.

Usage:
    # Check connection
    python3 eden_gdb.py status

    # Read memory
    python3 eden_gdb.py read 0x80B19320 32

    # Disassemble
    python3 eden_gdb.py disasm 0x80B19320 8

    # Set breakpoint and wait for hit
    python3 eden_gdb.py break 0x80B19320

    # Set hardware watchpoint (Eden's killer feature)
    python3 eden_gdb.py watch 0x12345678 4    # 4-byte write watchpoint

    # Continue execution
    python3 eden_gdb.py continue

    # Read registers
    python3 eden_gdb.py regs

    # Translate ELF vaddr to Eden runtime addr
    python3 eden_gdb.py addr 0x71008B9320

    # Find text base (run once per session)
    python3 eden_gdb.py find-base
"""

import socket
import struct
import sys
import os
import json
import time

# Config
GDB_HOST = os.environ.get("EDEN_GDB_HOST", "172.19.32.1")
GDB_PORT = int(os.environ.get("EDEN_GDB_PORT", "6543"))
STATE_FILE = os.path.join(os.path.dirname(__file__), ".eden_state.json")
TMUX_SESSION = "eden-gdb"
TIMEOUT = 5

# Known from ELF analysis
ELF_TEXT_OFFSET = 0x888  # File offset where text segment starts
ELF_TEXT_SIZE = 0x1CBABE0
ELF_RODATA_VADDR = 0x1CBB000
ELF_DATA_VADDR = 0x27B6000
MOD0_SIGNATURE = b'\x4d\x4f\x44\x30'  # "MOD0"

# Key function signatures (position-independent bytes for searching)
FUNC_SIGNATURES = {
    'changeState': {
        'bytes': 'f657bda9 f44f01a9 fd7b02a9 fd830091 080840b9 f303012a',
        'elf_offset': 0x8b9320,
        'description': 'StateMachine::changeState(state_id)',
        'args': 'x0=StateMachine*, x1=state_id',
    },
    'procFrame_': {
        'bytes': 'f30f1ef8 fd7b01a9 fd430091 08084939',
        'elf_offset': 0x2abb50,
        'description': 'PlayerObject::procFrame_()',
        'args': 'x0=PlayerObject*',
    },
}


def load_state():
    """Load saved state (text_base etc) from disk."""
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    return {}


def save_state(state):
    """Save state to disk."""
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f, indent=2)


def gdb_checksum(data: bytes) -> str:
    return f"{sum(data) & 0xFF:02x}"


def gdb_send(sock, cmd: str) -> str:
    """Send a GDB RSP command and get response."""
    packet = f"${cmd}#{gdb_checksum(cmd.encode())}"
    sock.sendall(packet.encode())

    # Read response
    response = b""
    while True:
        chunk = sock.recv(4096)
        if not chunk:
            break
        response += chunk
        # Check if we have a complete packet
        if b'#' in response:
            # Find the packet boundaries
            start = response.find(b'$')
            end = response.find(b'#', start)
            if start != -1 and end != -1 and len(response) >= end + 3:
                break

    # Send ACK
    sock.sendall(b'+')

    # Parse response
    decoded = response.decode('latin-1')
    start = decoded.find('$')
    end = decoded.find('#', start)
    if start != -1 and end != -1:
        return decoded[start + 1:end]
    return decoded


def connect():
    """Connect to Eden GDB stub."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(TIMEOUT)
    try:
        sock.connect((GDB_HOST, GDB_PORT))
        # Read initial stop reply or ack
        try:
            initial = sock.recv(1024)
        except socket.timeout:
            pass
        # Send ack
        sock.sendall(b'+')
        return sock
    except (ConnectionRefusedError, socket.timeout) as e:
        print(f"ERROR: Cannot connect to {GDB_HOST}:{GDB_PORT} — {e}")
        print("Is Eden running with GDB stub enabled?")
        sys.exit(1)


def cmd_status():
    """Check if Eden GDB stub is reachable and game is running."""
    try:
        sock = connect()
        # Query halt reason
        reply = gdb_send(sock, '?')
        print(f"Connected to Eden GDB stub at {GDB_HOST}:{GDB_PORT}")
        print(f"Stop reason: {reply}")

        # Get PC
        reply = gdb_send(sock, 'p20')  # x32 = PC in aarch64
        if reply and not reply.startswith('E'):
            # PC is register 32 (0x20)
            pc_bytes = bytes.fromhex(reply)
            pc = struct.unpack('<Q', pc_bytes)[0]
            print(f"PC: {pc:#018x}")

        state = load_state()
        if 'text_base' in state:
            print(f"Text base: {state['text_base']:#x} (saved)")
        else:
            print("Text base: unknown (run 'find-base' first)")

        sock.close()
    except Exception as e:
        print(f"ERROR: {e}")
        sys.exit(1)


def cmd_find_base():
    """Find the text segment base address by searching for MOD0."""
    sock = connect()

    # Strategy: probe memory in 0x1000 increments around likely ranges
    # Switch games typically load between 0x80000000-0x82000000
    print("Searching for MOD0 header...")

    # The text segment starts with: 00 00 00 00 08 00 00 00 4D 4F 44 30
    # MOD0 is at offset +8 from text start
    target = b'\x00\x00\x00\x00\x08\x00\x00\x00\x4d\x4f\x44\x30'

    # Try common bases first, then scan
    candidates = [0x80260000, 0x80004000, 0x80100000]

    for base in candidates:
        reply = gdb_send(sock, f'm{base:x},{len(target):x}')
        if reply and not reply.startswith('E'):
            data = bytes.fromhex(reply)
            if data == target:
                print(f"Found text base: {base:#x}")
                state = load_state()
                state['text_base'] = base
                save_state(state)
                sock.close()
                return base

    # Scan broader range
    for base in range(0x80000000, 0x82000000, 0x10000):
        reply = gdb_send(sock, f'm{base:x},{len(target):x}')
        if reply and not reply.startswith('E'):
            data = bytes.fromhex(reply)
            if data == target:
                print(f"Found text base: {base:#x}")
                state = load_state()
                state['text_base'] = base
                save_state(state)
                sock.close()
                return base

    print("ERROR: Could not find text base")
    sock.close()
    sys.exit(1)


def elf_to_runtime(elf_vaddr):
    """Convert ELF vaddr (0x71XXXXXXXXXX) to Eden runtime address."""
    state = load_state()
    if 'text_base' not in state:
        print("ERROR: text_base unknown. Run 'find-base' first.")
        sys.exit(1)

    text_base = state['text_base']
    # ELF vaddrs are 0x7100000000 + offset, or just raw offset
    if elf_vaddr >= 0x7100000000:
        offset = elf_vaddr - 0x7100000000
    else:
        offset = elf_vaddr

    runtime = text_base + offset
    return runtime


def cmd_addr(elf_vaddr_str):
    """Translate ELF vaddr to runtime address."""
    elf_vaddr = int(elf_vaddr_str, 0)
    runtime = elf_to_runtime(elf_vaddr)
    print(f"ELF:     {elf_vaddr:#018x}")
    print(f"Offset:  {elf_vaddr - 0x7100000000 if elf_vaddr >= 0x7100000000 else elf_vaddr:#x}")
    print(f"Runtime: {runtime:#018x}")


def cmd_read(addr_str, size_str="32"):
    """Read memory as hex dump."""
    addr = int(addr_str, 0)
    size = int(size_str, 0)

    sock = connect()
    reply = gdb_send(sock, f'm{addr:x},{size:x}')
    sock.close()

    if reply.startswith('E'):
        print(f"ERROR: Cannot read memory at {addr:#x}: {reply}")
        return

    data = bytes.fromhex(reply)
    # Print hex dump
    for i in range(0, len(data), 16):
        hex_part = ' '.join(f'{b:02x}' for b in data[i:i+16])
        ascii_part = ''.join(chr(b) if 32 <= b < 127 else '.' for b in data[i:i+16])
        print(f"{addr + i:#010x}  {hex_part:<48}  {ascii_part}")


def cmd_disasm(addr_str, count_str="8"):
    """Disassemble instructions (requires capstone)."""
    addr = int(addr_str, 0)
    count = int(count_str, 0)
    size = count * 4  # AArch64 = fixed 4-byte instructions

    sock = connect()
    reply = gdb_send(sock, f'm{addr:x},{size:x}')
    sock.close()

    if reply.startswith('E'):
        print(f"ERROR: Cannot read memory at {addr:#x}: {reply}")
        return

    data = bytes.fromhex(reply)

    try:
        from capstone import Cs, CS_ARCH_ARM64, CS_MODE_ARM
        md = Cs(CS_ARCH_ARM64, CS_MODE_ARM)
        for insn in md.disasm(data, addr):
            print(f"  {insn.address:#010x}:  {insn.mnemonic}\t{insn.op_str}")
    except ImportError:
        # Fallback: just show raw words
        print("(capstone not available, showing raw)")
        for i in range(0, len(data), 4):
            word = struct.unpack('<I', data[i:i+4])[0]
            print(f"  {addr + i:#010x}:  {word:#010x}")


def cmd_regs():
    """Read general-purpose registers."""
    sock = connect()

    reg_names = [f'x{i}' for i in range(31)] + ['sp', 'pc']
    for i, name in enumerate(reg_names):
        reply = gdb_send(sock, f'p{i:x}')
        if reply and not reply.startswith('E'):
            val = struct.unpack('<Q', bytes.fromhex(reply))[0]
            print(f"  {name:>3}: {val:#018x}")

    sock.close()


def cmd_break(addr_str):
    """Set a software breakpoint."""
    addr = int(addr_str, 0)
    sock = connect()

    # Z0 = software breakpoint, addr, kind (4 for aarch64)
    reply = gdb_send(sock, f'Z0,{addr:x},4')
    if reply == 'OK':
        print(f"Breakpoint set at {addr:#x}")
    else:
        print(f"ERROR setting breakpoint: {reply}")

    sock.close()


def cmd_watch(addr_str, size_str="4"):
    """Set a hardware write watchpoint (Eden's killer feature)."""
    addr = int(addr_str, 0)
    size = int(size_str, 0)

    sock = connect()

    # Z2 = write watchpoint
    reply = gdb_send(sock, f'Z2,{addr:x},{size:x}')
    if reply == 'OK':
        print(f"Write watchpoint set at {addr:#x} ({size} bytes)")
    elif reply == '':
        print("ERROR: Watchpoint not supported (empty reply)")
    else:
        print(f"ERROR setting watchpoint: {reply}")

    sock.close()


def cmd_rwatch(addr_str, size_str="4"):
    """Set a hardware read watchpoint."""
    addr = int(addr_str, 0)
    size = int(size_str, 0)

    sock = connect()
    reply = gdb_send(sock, f'Z3,{addr:x},{size:x}')
    if reply == 'OK':
        print(f"Read watchpoint set at {addr:#x} ({size} bytes)")
    else:
        print(f"ERROR setting watchpoint: {reply}")
    sock.close()


def cmd_awatch(addr_str, size_str="4"):
    """Set a hardware access (read+write) watchpoint."""
    addr = int(addr_str, 0)
    size = int(size_str, 0)

    sock = connect()
    reply = gdb_send(sock, f'Z4,{addr:x},{size:x}')
    if reply == 'OK':
        print(f"Access watchpoint set at {addr:#x} ({size} bytes)")
    else:
        print(f"ERROR setting watchpoint: {reply}")
    sock.close()


def cmd_delete(addr_str, kind="0"):
    """Remove a breakpoint/watchpoint. kind: 0=sw break, 2=write watch, 3=read watch, 4=access watch"""
    addr = int(addr_str, 0)
    sock = connect()
    reply = gdb_send(sock, f'z{kind},{addr:x},4')
    print(f"Delete reply: {reply}")
    sock.close()


def cmd_continue():
    """Continue execution (sends 'c' and waits for stop)."""
    sock = connect()
    # Send continue
    packet = f"$c#{gdb_checksum(b'c')}"
    sock.sendall(packet.encode())
    print("Continuing... (waiting for stop, Ctrl+C to abort)")

    try:
        sock.settimeout(30)
        response = b""
        while True:
            chunk = sock.recv(4096)
            if not chunk:
                break
            response += chunk
            if b'#' in response and b'$' in response:
                break

        decoded = response.decode('latin-1')
        start = decoded.find('$')
        end = decoded.find('#', start)
        if start != -1 and end != -1:
            reason = decoded[start + 1:end]
            print(f"Stopped: {reason}")

            # Read PC and registers
            sock.sendall(b'+')
            pc_reply = gdb_send(sock, 'p20')  # PC
            if pc_reply and not pc_reply.startswith('E'):
                pc = struct.unpack('<Q', bytes.fromhex(pc_reply))[0]
                print(f"PC: {pc:#018x}")

                state = load_state()
                if 'text_base' in state:
                    offset = pc - state['text_base']
                    elf_vaddr = 0x7100000000 + offset
                    print(f"ELF vaddr: {elf_vaddr:#018x}")

    except socket.timeout:
        print("Timeout waiting for stop (game still running)")
    except KeyboardInterrupt:
        print("\nAborted")
    finally:
        sock.close()


def cmd_step():
    """Single step one instruction."""
    sock = connect()
    packet = f"$s#{gdb_checksum(b's')}"
    sock.sendall(packet.encode())

    try:
        sock.settimeout(5)
        response = sock.recv(4096)
        sock.sendall(b'+')

        pc_reply = gdb_send(sock, 'p20')
        if pc_reply and not pc_reply.startswith('E'):
            pc = struct.unpack('<Q', bytes.fromhex(pc_reply))[0]
            print(f"Stepped to PC: {pc:#018x}")
    except socket.timeout:
        print("Timeout")
    finally:
        sock.close()


def cmd_interrupt():
    """Send interrupt (Ctrl+C) to stop the target."""
    sock = connect()
    sock.sendall(b'\x03')
    try:
        sock.settimeout(3)
        response = sock.recv(4096)
        print(f"Interrupted: {response.decode('latin-1', errors='replace')}")
    except socket.timeout:
        print("Sent interrupt, no immediate response")
    sock.close()


def cmd_bt():
    """Get backtrace (read LR + FP chain)."""
    sock = connect()

    # Read FP (x29) and LR (x30) and PC
    fp_reply = gdb_send(sock, 'p1d')  # x29
    lr_reply = gdb_send(sock, 'p1e')  # x30
    pc_reply = gdb_send(sock, 'p20')  # pc

    state = load_state()
    text_base = state.get('text_base', 0)

    if pc_reply and not pc_reply.startswith('E'):
        pc = struct.unpack('<Q', bytes.fromhex(pc_reply))[0]
        lr = struct.unpack('<Q', bytes.fromhex(lr_reply))[0]
        fp = struct.unpack('<Q', bytes.fromhex(fp_reply))[0]

        print(f"#0  PC={pc:#x}" + (f"  (elf {0x7100000000 + pc - text_base:#x})" if text_base else ""))
        print(f"#1  LR={lr:#x}" + (f"  (elf {0x7100000000 + lr - text_base:#x})" if text_base else ""))

        # Walk FP chain
        frame = 2
        cur_fp = fp
        while cur_fp and frame < 20:
            reply = gdb_send(sock, f'm{cur_fp:x},10')
            if reply.startswith('E'):
                break
            data = bytes.fromhex(reply)
            if len(data) < 16:
                break
            next_fp, ret_addr = struct.unpack('<QQ', data)
            elf_str = f"  (elf {0x7100000000 + ret_addr - text_base:#x})" if text_base else ""
            print(f"#{frame}  {ret_addr:#x}{elf_str}")
            cur_fp = next_fp
            frame += 1
            if next_fp == 0:
                break

    sock.close()


COMMANDS = {
    'status': (cmd_status, []),
    'find-base': (cmd_find_base, []),
    'addr': (cmd_addr, ['elf_vaddr']),
    'read': (cmd_read, ['addr', '[size=32]']),
    'disasm': (cmd_disasm, ['addr', '[count=8]']),
    'regs': (cmd_regs, []),
    'break': (cmd_break, ['addr']),
    'watch': (cmd_watch, ['addr', '[size=4]']),
    'rwatch': (cmd_rwatch, ['addr', '[size=4]']),
    'awatch': (cmd_awatch, ['addr', '[size=4]']),
    'delete': (cmd_delete, ['addr', '[kind=0]']),
    'continue': (cmd_continue, []),
    'step': (cmd_step, []),
    'interrupt': (cmd_interrupt, []),
    'bt': (cmd_bt, []),
}


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print("Eden GDB Client — SMM2 Debugging")
        print(f"\nUsage: {sys.argv[0]} <command> [args...]")
        print("\nCommands:")
        for name, (fn, args) in COMMANDS.items():
            args_str = ' '.join(args) if args else ''
            print(f"  {name:12s} {args_str}")
        print(f"\nState file: {STATE_FILE}")
        print(f"Target: {GDB_HOST}:{GDB_PORT}")
        sys.exit(0)

    cmd_name = sys.argv[1]
    fn, _ = COMMANDS[cmd_name]
    args = sys.argv[2:]
    fn(*args)


if __name__ == '__main__':
    main()
