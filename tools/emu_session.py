#!/usr/bin/env python3
"""
Emulator session manager. Tracks running game instances,
launches/kills them, and prevents orphaned processes.

Usage:
    python3 emu_session.py status          # Show running emulators
    python3 emu_session.py launch eden     # Launch Eden with SMM2
    python3 emu_session.py launch ryujinx  # Launch Ryujinx with SMM2
    python3 emu_session.py kill eden       # Kill Eden
    python3 emu_session.py kill all        # Kill all emulators
"""

import subprocess
import sys
import os
import json
import time

TASKLIST = "/mnt/c/Windows/System32/tasklist.exe"
TASKKILL = "/mnt/c/Windows/System32/taskkill.exe"

# Load .env
ENV = {}
env_path = os.path.join(os.path.dirname(__file__), '..', '.env')
if os.path.exists(env_path):
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                k, v = line.split('=', 1)
                ENV[k.strip()] = v.strip()

EMULATORS = {
    'eden': {
        'exe_name': 'eden.exe',
        'cli_name': 'eden-cli.exe',
        'launch_cmd': lambda gdb=False: [
            ENV.get('EDEN_EXE', '/mnt/c/Users/nico/Documents/eden/eden.exe'),
            '-g', ENV.get('EDEN_GAME_PATH', '')
        ],
        'config_path': '/mnt/c/Users/nico/AppData/Roaming/eden/config/qt-config.ini',
    },
    'ryujinx': {
        'exe_name': 'Ryujinx.exe',
        'launch_cmd': lambda gdb=False: [
            ENV.get('RYUJINX_EXE', ''),
            ENV.get('GAME_NSP', '')
        ],
    },
}


def is_running(emu_name):
    """Quick check if emulator is running using saved PID."""
    pid_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), f'.{emu_name}_pid')
    if not os.path.exists(pid_file):
        # Fall back to process scan
        procs = get_processes()
        return len(procs.get(emu_name, [])) > 0
    with open(pid_file) as f:
        pid = f.read().strip()
    # Check if PID is still alive via tasklist
    try:
        result = subprocess.run(
            ['tasklist.exe', '/FI', f'PID eq {pid}', '/NH'],
            capture_output=True, text=True, timeout=3)
        return emu_name in result.stdout.lower()
    except:
        return False


def get_processes():
    """Get running emulator processes from Windows."""
    try:
        result = subprocess.run([TASKLIST], capture_output=True, text=True, timeout=5)
        processes = {}
        for line in result.stdout.splitlines():
            for name, info in EMULATORS.items():
                for exe in [info['exe_name'], info.get('cli_name', '')]:
                    if exe and exe.lower() in line.lower():
                        parts = line.split()
                        pid = int(parts[1])
                        mem = parts[-2].replace('.', '').replace(',', '')
                        processes.setdefault(name, []).append({
                            'pid': pid,
                            'exe': parts[0],
                            'mem_kb': int(mem) if mem.isdigit() else 0,
                        })
        return processes
    except Exception as e:
        print(f"ERROR: {e}")
        return {}


def cmd_status():
    """Show running emulator sessions."""
    procs = get_processes()
    if not procs:
        print("No emulator processes running.")
        return

    for name, plist in procs.items():
        print(f"\n{name}:")
        for p in plist:
            mem_mb = p['mem_kb'] / 1024
            label = "🎮 GAME" if mem_mb > 100 else "  stale"
            print(f"  {label}  PID {p['pid']:>6}  {p['exe']:<20}  {mem_mb:.0f} MB")


def cmd_kill(target):
    """Kill emulator processes."""
    procs = get_processes()
    targets = list(EMULATORS.keys()) if target == 'all' else [target]

    killed = 0
    for name in targets:
        for p in procs.get(name, []):
            try:
                subprocess.run([TASKKILL, '/PID', str(p['pid']), '/F'],
                             capture_output=True, timeout=5)
                print(f"Killed {p['exe']} PID {p['pid']}")
                killed += 1
            except Exception as e:
                print(f"Failed to kill PID {p['pid']}: {e}")

    if killed == 0:
        print(f"No {target} processes to kill.")


def cmd_launch(emu_name, gdb=False):
    """Launch an emulator with the game."""
    if emu_name not in EMULATORS:
        print(f"Unknown emulator: {emu_name}")
        sys.exit(1)

    info = EMULATORS[emu_name]

    # Check if already running
    procs = get_processes()
    game_procs = [p for p in procs.get(emu_name, []) if p['mem_kb'] > 100000]
    if game_procs:
        print(f"{emu_name} already running (PID {game_procs[0]['pid']}, {game_procs[0]['mem_kb']//1024} MB)")
        print("Kill it first with: emu_session.py kill " + emu_name)
        return

    # Enable/disable GDB stub for Eden
    if emu_name == 'eden' and 'config_path' in info:
        config = info['config_path']
        if os.path.exists(config):
            with open(config) as f:
                content = f.read()
            if gdb:
                content = content.replace('use_gdbstub\\default=true', 'use_gdbstub\\default=false')
                content = content.replace('use_gdbstub=false', 'use_gdbstub=true')
            else:
                content = content.replace('use_gdbstub\\default=false', 'use_gdbstub\\default=true')
                content = content.replace('use_gdbstub=true', 'use_gdbstub=false')
            with open(config, 'w') as f:
                f.write(content)
            print(f"GDB stub: {'enabled' if gdb else 'disabled'}")

    cmd = info['launch_cmd'](gdb)
    print(f"Launching: {' '.join(cmd)}")
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print(f"Started {emu_name}, WSL PID {proc.pid}")

    # Poll for Windows process to appear (much faster than blind sleep)
    import time as _time
    deadline = _time.time() + 15
    win_pid = None
    while _time.time() < deadline:
        procs = get_processes()
        game_procs = [p for p in procs.get(emu_name, []) if p['mem_kb'] > 50000]
        if game_procs:
            win_pid = game_procs[0]['pid']
            break
        _time.sleep(1)

    if win_pid:
        # Save PID for quick checks later
        pid_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), f'.{emu_name}_pid')
        with open(pid_file, 'w') as f:
            f.write(str(win_pid))
        mem_mb = game_procs[0]['mem_kb'] // 1024
        print(f"✅ {emu_name} running (PID {win_pid}, {mem_mb} MB)")
    else:
        print(f"❌ {emu_name} failed to start within 15s")


def main():
    if len(sys.argv) < 2:
        print("Emulator Session Manager")
        print(f"\nUsage: {sys.argv[0]} <command> [args]")
        print("\nCommands:")
        print("  status              Show running emulators")
        print("  launch <emu>        Launch emulator (eden/ryujinx)")
        print("  launch <emu> --gdb  Launch with GDB stub enabled")
        print("  kill <emu|all>      Kill emulator processes")
        sys.exit(0)

    cmd = sys.argv[1]
    if cmd == 'status':
        cmd_status()
    elif cmd == 'kill':
        cmd_kill(sys.argv[2] if len(sys.argv) > 2 else 'all')
    elif cmd == 'launch':
        emu = sys.argv[2] if len(sys.argv) > 2 else 'eden'
        gdb = '--gdb' in sys.argv
        cmd_launch(emu, gdb)
    else:
        print(f"Unknown command: {cmd}")


if __name__ == '__main__':
    main()
