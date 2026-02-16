#!/usr/bin/env python3
"""
Emulator session manager. Single tool for all SMM2 emulator operations.

Usage:
    python3 emu_session.py overview          # Full state overview
    python3 emu_session.py status            # Show running emulators
    python3 emu_session.py launch eden       # Launch Eden (no GDB)
    python3 emu_session.py launch eden --gdb # Launch Eden with GDB stub
    python3 emu_session.py kill eden         # Kill Eden
    python3 emu_session.py kill all          # Kill all emulators
    python3 emu_session.py deploy eden       # Deploy hooks to Eden
    python3 emu_session.py gdb-on            # Enable GDB stub (no restart)
    python3 emu_session.py gdb-off           # Disable GDB stub (no restart)
    python3 emu_session.py game-status       # Read status.bin
    python3 emu_session.py game-status --raw # With hex offsets per field
    python3 emu_session.py hexdump           # Annotated hex dump of status.bin
    python3 emu_session.py cleanup           # Kill orphans, close stale tmux
"""

import subprocess
import sys
import os
import json
import time
import struct

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

EDEN_CONFIG = '/mnt/c/Users/nico/AppData/Roaming/eden/config/qt-config.ini'
EDEN_SD = ENV.get('EDEN_SD_PATH', '/mnt/c/Users/nico/AppData/Roaming/eden/sdmc/smm2-hooks')
EDEN_MODS = ENV.get('EDEN_MODS_PATH', '/mnt/c/Users/nico/Documents/eden/load/01009B90006DC000/smm2-hooks/exefs')
RYUJINX_SD = ENV.get('RYUJINX_SD_PATH', '')
HOOKS_BUILD = os.path.join(os.path.dirname(__file__), '..', 'build', 'smm2-hooks.nso')

EMULATORS = {
    'eden': {
        'exe_name': 'eden.exe',
        'cli_name': 'eden-cli.exe',
        'launch_cmd': lambda: [
            ENV.get('EDEN_EXE', '/mnt/c/Users/nico/Documents/eden/eden.exe'),
            '-g', ENV.get('EDEN_GAME_PATH', '')
        ],
        'sd_path': EDEN_SD,
        'mods_path': EDEN_MODS,
    },
    'ryujinx': {
        'exe_name': 'Ryujinx.exe',
        'launch_cmd': lambda: [
            ENV.get('RYUJINX_EXE', ''),
            ENV.get('GAME_NSP', '')
        ],
        'sd_path': RYUJINX_SD,
    },
}

GDB_TMUX_SESSION = 'eden-gdb'


# ─── Process management ───

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


def is_running(emu_name):
    """Check if emulator is running."""
    procs = get_processes()
    return len(procs.get(emu_name, [])) > 0


def get_pid(emu_name):
    """Get PID of running emulator, or None."""
    procs = get_processes()
    plist = procs.get(emu_name, [])
    if plist:
        # Prefer the one with most memory (actual game vs cli)
        return max(plist, key=lambda p: p['mem_kb'])
    return None


# ─── GDB config ───

def gdb_is_enabled():
    """Check if GDB stub is enabled in Eden config."""
    if not os.path.exists(EDEN_CONFIG):
        return None
    with open(EDEN_CONFIG) as f:
        content = f.read()
    # use_gdbstub\default=false AND use_gdbstub=true means enabled
    has_custom = 'use_gdbstub\\default=false' in content
    has_true = '\nuse_gdbstub=true' in content or content.startswith('use_gdbstub=true')
    return has_custom and has_true


def gdb_set(enabled):
    """Enable or disable GDB stub in Eden config."""
    if not os.path.exists(EDEN_CONFIG):
        print(f"❌ Config not found: {EDEN_CONFIG}")
        return False
    with open(EDEN_CONFIG) as f:
        content = f.read()
    if enabled:
        content = content.replace('use_gdbstub\\default=true', 'use_gdbstub\\default=false')
        content = content.replace('use_gdbstub=false', 'use_gdbstub=true')
    else:
        content = content.replace('use_gdbstub\\default=false', 'use_gdbstub\\default=true')
        content = content.replace('use_gdbstub=true', 'use_gdbstub=false')
    with open(EDEN_CONFIG, 'w') as f:
        f.write(content)
    print(f"GDB stub: {'✅ enabled' if enabled else '❌ disabled'}")
    return True


# ─── tmux session management ───

def tmux_session_exists(name):
    """Check if a tmux session exists."""
    try:
        result = subprocess.run(['tmux', 'has-session', '-t', name],
                              capture_output=True, timeout=3)
        return result.returncode == 0
    except:
        return False


def tmux_list_sessions():
    """List all tmux sessions."""
    try:
        result = subprocess.run(['tmux', 'list-sessions'],
                              capture_output=True, text=True, timeout=3)
        if result.returncode == 0:
            return result.stdout.strip().splitlines()
    except:
        pass
    return []


def tmux_kill_session(name):
    """Kill a tmux session."""
    try:
        subprocess.run(['tmux', 'kill-session', '-t', name],
                      capture_output=True, timeout=3)
        return True
    except:
        return False


# ─── Hooks deployment ───

def hooks_deployed(emu_name='eden'):
    """Check if hooks NSO is deployed to emulator's mod directory."""
    info = EMULATORS.get(emu_name, {})
    mods = info.get('mods_path', '')
    if not mods:
        return None  # unknown
    subsdk = os.path.join(mods, 'subsdk4')
    return os.path.exists(subsdk)


def hooks_built():
    """Check if hooks NSO exists in build dir."""
    return os.path.exists(HOOKS_BUILD)


def deploy_hooks(emu_name='eden'):
    """Deploy built hooks to emulator mod directory."""
    if not hooks_built():
        print(f"❌ Hooks not built. Run: cd ~/code/smm2-hooks && cmake -B build && ninja -C build")
        return False
    info = EMULATORS.get(emu_name, {})
    mods = info.get('mods_path', '')
    if not mods:
        print(f"❌ No mods path configured for {emu_name}")
        return False
    os.makedirs(mods, exist_ok=True)
    import shutil
    shutil.copy2(HOOKS_BUILD, os.path.join(mods, 'subsdk4'))
    print(f"✅ Deployed hooks to {mods}/subsdk4")
    return True


# ─── Game status (status.bin) ───

# Single source of truth for StatusBlock layout.
# Must match include/smm2/status.h exactly!
# Format: (offset, size, type_char, name)
# type_char: I=uint32, i=int32, f=float, B=uint8
STATUS_FIELDS = [
    (0x00, 4, 'I', 'frame'),
    (0x04, 4, 'I', 'game_phase'),
    (0x08, 4, 'I', 'player_state'),
    (0x0C, 4, 'I', 'powerup_id'),
    (0x10, 4, 'f', 'pos_x'),
    (0x14, 4, 'f', 'pos_y'),
    (0x18, 4, 'f', 'vel_x'),
    (0x1C, 4, 'f', 'vel_y'),
    (0x20, 4, 'I', 'state_frames'),
    (0x24, 1, 'B', 'in_water'),
    (0x25, 1, 'B', 'is_dead'),
    (0x26, 1, 'B', 'is_goal'),
    (0x27, 1, 'B', 'has_player'),
    (0x28, 4, 'f', 'facing'),
    (0x2C, 4, 'f', 'gravity'),
    (0x30, 4, 'I', 'buffered_action'),
    (0x34, 4, 'I', 'input_poll_count'),
    (0x38, 4, 'i', 'real_game_phase'),
    (0x3C, 1, 'B', 'course_theme'),
    # 0x3D-0x3F: padding
    (0x40, 4, 'I', 'game_style'),
    (0x44, 4, 'I', 'scene_mode'),
    (0x48, 4, 'I', 'is_playing'),
    # 0x4C-0x63: gpm_inner[6] (research dump)
    (0x4C, 4, 'I', 'gpm_inner_0'),
    (0x50, 4, 'I', 'gpm_inner_1'),
    (0x54, 4, 'I', 'gpm_inner_2'),
    (0x58, 4, 'I', 'gpm_inner_3'),
    (0x5C, 4, 'I', 'gpm_inner_4'),
    (0x60, 4, 'I', 'gpm_inner_5'),
]

def _parse_status_fields(data):
    """Parse status.bin bytes using STATUS_FIELDS layout."""
    result = {}
    for offset, size, fmt, name in STATUS_FIELDS:
        if offset + size > len(data):
            break
        if size == 1:
            result[name] = data[offset]
        else:
            result[name] = struct.unpack(f'<{fmt}', data[offset:offset+size])[0]
    return result

def read_status_bin(emu_name='eden'):
    """Read and parse status.bin from emulator's SD card."""
    info = EMULATORS.get(emu_name, {})
    sd = info.get('sd_path', '')
    if not sd:
        return None
    path = os.path.join(sd, 'status.bin')
    if not os.path.exists(path):
        return {'error': 'status.bin not found'}
    try:
        with open(path, 'rb') as f:
            data = f.read()
        if len(data) < 68:
            return {'error': f'status.bin too small ({len(data)} bytes)'}
        # Parse using shared STATUS_FIELDS layout (single source of truth)
        fields = _parse_status_fields(data)
        mtime = os.path.getmtime(path)
        age = time.time() - mtime
        # Build result dict with both raw field names and legacy aliases
        result = dict(fields)
        result['state'] = fields.get('player_state', 0)
        result['powerup'] = fields.get('powerup_id', 0)
        result['theme'] = fields.get('course_theme', 0xFF)
        result['phase'] = fields.get('real_game_phase', 0)
        result['style'] = fields.get('game_style', 0)
        result['is_playing_flag'] = fields.get('is_playing', 0)
        result['age_seconds'] = round(age, 1)
        result['stale'] = age > 5
        result['_raw_data'] = data  # keep raw bytes for hexdump
        result['_raw_size'] = len(data)
        return result
    except Exception as e:
        return {'error': str(e)}


def is_status_fresh(emu_name='eden', window=0.5):
    """Check if status.bin is being actively updated."""
    info = EMULATORS.get(emu_name, {})
    sd = info.get('sd_path', '')
    path = os.path.join(sd, 'status.bin') if sd else ''
    if not os.path.exists(path):
        return False
    try:
        s1 = read_status_bin(emu_name)
        time.sleep(window)
        s2 = read_status_bin(emu_name)
        return s1 and s2 and s1.get('frame', 0) != s2.get('frame', 0)
    except:
        return False


# ─── Commands ───

def cmd_overview():
    """Full state overview — everything at a glance."""
    print("═══ SMM2 Session Overview ═══\n")

    # Processes
    procs = get_processes()
    if procs:
        for name, plist in procs.items():
            for p in plist:
                mem_mb = p['mem_kb'] / 1024
                label = "🎮 RUNNING" if mem_mb > 100 else "⚠️  small"
                print(f"  {label}  {name}  PID {p['pid']}  {mem_mb:.0f} MB")
    else:
        print("  No emulators running.")

    # GDB config
    gdb = gdb_is_enabled()
    if gdb is not None:
        print(f"\n  GDB stub: {'✅ enabled' if gdb else '❌ disabled'}")

    # Hooks
    print(f"\n  Hooks built: {'✅' if hooks_built() else '❌'}")
    for emu in ['eden', 'ryujinx']:
        deployed = hooks_deployed(emu)
        if deployed is not None:
            print(f"  Hooks deployed ({emu}): {'✅' if deployed else '❌'}")

    # tmux sessions
    sessions = tmux_list_sessions()
    if sessions:
        print(f"\n  tmux sessions:")
        for s in sessions:
            print(f"    {s}")
    else:
        print(f"\n  tmux sessions: none")

    # Game status
    for emu in ['eden', 'ryujinx']:
        if procs.get(emu) or hooks_deployed(emu):
            status = read_status_bin(emu)
            if status and 'error' not in status:
                fresh = "🟢 live" if not status['stale'] else "🔴 stale"
                print(f"\n  Game state ({emu}): {fresh} (age: {status['age_seconds']}s)")
                print(f"    Frame:{status['frame']} State:{status['state']} "
                      f"Player:{status['has_player']} Phase:{status['phase']}")
                print(f"    Pos:({status['pos_x']:.1f}, {status['pos_y']:.1f}) "
                      f"Vel:({status['vel_x']:.1f}, {status['vel_y']:.1f})")
                print(f"    Powerup:{status['powerup']} Theme:{status['theme']} Style:{status['style']}")
            elif status:
                print(f"\n  Game state ({emu}): {status['error']}")

    print()


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
    p = get_pid(emu_name)
    if p and p['mem_kb'] > 100000:
        print(f"❌ {emu_name} already running (PID {p['pid']}, {p['mem_kb']//1024} MB)")
        print(f"   Kill first: emu_session.py kill {emu_name}")
        return

    # Check hooks deployed
    if not hooks_deployed(emu_name):
        print(f"⚠️  Hooks not deployed to {emu_name}. Run: emu_session.py deploy {emu_name}")

    # Clear stale status.bin
    sd = info.get('sd_path', '')
    if sd:
        status_path = os.path.join(sd, 'status.bin')
        if os.path.exists(status_path):
            os.remove(status_path)
            print("Cleared stale status.bin")

    # Set GDB config for Eden
    if emu_name == 'eden':
        gdb_set(gdb)

    # Launch
    cmd = info['launch_cmd']()
    print(f"Launching: {' '.join(cmd)}")
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # Wait for process to appear
    deadline = time.time() + 20
    win_pid = None
    while time.time() < deadline:
        p = get_pid(emu_name)
        if p and p['mem_kb'] > 50000:
            win_pid = p['pid']
            break
        time.sleep(1)

    if win_pid:
        # Save PID
        pid_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), f'.{emu_name}_pid')
        with open(pid_file, 'w') as f:
            f.write(str(win_pid))
        print(f"✅ {emu_name} running (PID {win_pid})")
        if gdb:
            print(f"⚠️  Game is PAUSED — connect GDB to port 6543 and send 'c' immediately!")
    else:
        print(f"❌ {emu_name} failed to start within 20s")


def cmd_deploy(emu_name='eden'):
    """Deploy hooks to emulator."""
    deploy_hooks(emu_name)


def cmd_hexdump(emu_name='eden'):
    """Show annotated hex dump of status.bin — every byte labeled with field name."""
    status = read_status_bin(emu_name)
    if not status or 'error' in status:
        print(f"❌ {status.get('error', 'no status')}" if status else "No status")
        return
    data = status.get('_raw_data', b'')
    print(f"status.bin: {len(data)} bytes (expect {100} for StatusBlock)")
    print(f"{'Offset':>6}  {'Hex':16}  {'Field':<20}  {'Value'}")
    print("-" * 70)
    # Build offset→field map
    field_at = {}
    for offset, size, fmt, name in STATUS_FIELDS:
        field_at[offset] = (size, fmt, name)
    i = 0
    while i < len(data):
        if i in field_at:
            size, fmt, name = field_at[i]
            raw = data[i:i+size]
            hex_str = raw.hex()
            if size == 1:
                val = raw[0]
            else:
                val = struct.unpack(f'<{fmt}', raw)[0]
            if isinstance(val, float):
                print(f"0x{i:04X}  {hex_str:<16}  {name:<20}  {val:.4f}")
            else:
                print(f"0x{i:04X}  {hex_str:<16}  {name:<20}  {val} (0x{val:X})" if isinstance(val, int) and val > 9 else f"0x{i:04X}  {hex_str:<16}  {name:<20}  {val}")
            i += size
        else:
            # padding byte
            print(f"0x{i:04X}  {data[i]:02x}{'':14}  {'(pad)':<20}  {data[i]}")
            i += 1

def cmd_game_status(emu_name='eden', raw=False):
    """Read and display game status from status.bin."""
    status = read_status_bin(emu_name)
    if not status:
        print(f"No status available for {emu_name}")
        return
    if 'error' in status:
        print(f"❌ {status['error']}")
        return

    STATES = {0:'None', 1:'Walk', 2:'Fall', 3:'Jump', 4:'Landing', 5:'Crouch',
              6:'CrouchEnd', 16:'Swim', 113:'Death', 114:'Goal'}
    THEMES = {0:'Ground', 1:'Underground', 2:'Castle', 3:'Airship',
              4:'Water', 5:'GhostHouse', 6:'Snow', 7:'Desert', 8:'Sky', 9:'Forest', 0xFF:'Unknown'}
    # game_style from BCD header or noexes pointer chain
    STYLES = {
        0x314D: 'SMB1', 0x334D: 'SMB3', 0x574D: 'SMW', 0x5557: 'NSMBU', 0x5733: '3DW',
        # Also accept simple index values
        0: 'SMB1', 1: 'SMB3', 2: 'SMW', 3: 'NSMBU', 4: '3DW',
    }
    POWERUPS = {0:'Normal', 1:'Super', 2:'Fire', 3:'Propeller', 4:'Mant', 5:'Sippo',
                6:'Mega', 7:'Neko', 8:'Builder', 9:'SuperBall', 10:'Link', 11:'Frog',
                12:'Balloon', 13:'Flying', 14:'Boomerang', 15:'USA'}

    fresh = "🟢" if not status['stale'] else "🔴"
    state_name = STATES.get(status['state'], f"#{status['state']}")
    theme_name = THEMES.get(status['theme'], f"#{status['theme']}")
    style_name = STYLES.get(status['game_style'], f"#{status['game_style']:#x}")
    powerup_name = POWERUPS.get(status['powerup'], f"#{status['powerup']}")

    print(f"{fresh} Frame:{status['frame']} Age:{status['age_seconds']}s")
    print(f"  Player:{status['has_player']} State:{state_name}({status['state']}) Phase:{status['real_game_phase']}")
    print(f"  Pos:({status['pos_x']:.1f}, {status['pos_y']:.1f}) Vel:({status['vel_x']:.2f}, {status['vel_y']:.2f})")
    print(f"  Gravity:{status['gravity']:.2f} Powerup:{powerup_name}({status['powerup']})")
    SCENES = {0: '???', 1: 'Editor', 5: 'Play', 6: 'Title/Menu'}
    scene = SCENES.get(status.get('scene_mode', 0), f"#{status.get('scene_mode', 0)}")
    print(f"  Theme:{theme_name} Style:{style_name} Scene:{scene}")
    if status.get('state_frames'):
        print(f"  StateFrames:{status['state_frames']} Facing:{status['facing']:.1f}")
    if raw:
        print("\n  Raw field dump (offset → value):")
        for offset, size, fmt, name in STATUS_FIELDS:
            val = status.get(name, '?')
            if isinstance(val, float):
                print(f"    0x{offset:04X} {name:<20} = {val:.4f}")
            else:
                print(f"    0x{offset:04X} {name:<20} = {val}")


def _write_input(buttons=0, stick_lx=0, stick_ly=0):
    """Write controller state to input.bin (buttons + analog sticks).
    
    Analog stick range: -32768 to 32767. 3DW requires analog for movement.
    """
    info = EMULATORS.get('eden', {})
    sd = info.get('sd_path', '')
    if not sd:
        return
    path = os.path.join(sd, 'input.bin')
    data = struct.pack('<Qii', buttons, stick_lx, stick_ly)
    with open(path, 'wb') as f:
        f.write(data)


def _press(buttons, duration_ms=100):
    """Press buttons for a duration then release."""
    _write_input(buttons)
    time.sleep(duration_ms / 1000.0)
    _write_input(0)


def _wait_frames(emu_name, target_field, target_check, timeout=15, label=""):
    """Wait until a status field meets a condition. Returns status or None."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        s = read_status_bin(emu_name)
        if s and 'error' not in s and target_check(s):
            return s
        time.sleep(0.5)
    return None


# Button constants
BTN_A     = 0x01
BTN_B     = 0x02
BTN_L     = 0x40
BTN_R     = 0x80
BTN_MINUS = 0x800


def _boot_and_verify(emu_name, gdb=False):
    """Boot emulator and verify hooks are working. Returns True/False."""
    info = EMULATORS.get(emu_name, {})

    # Deploy hooks if needed
    if not hooks_deployed(emu_name):
        print("  Deploying hooks...", end=' ')
        if not deploy_hooks(emu_name):
            print("❌")
            return False
        print("✅")

    # Clear stale status.bin
    sd = info.get('sd_path', '')
    if sd:
        for f in ['status.bin', 'input.bin']:
            p = os.path.join(sd, f)
            if os.path.exists(p):
                os.remove(p)

    # Set GDB config
    if emu_name == 'eden':
        gdb_set(gdb)

    # Launch
    launch_cmd = info['launch_cmd']()
    subprocess.Popen(launch_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # Wait for process (>500MB = loaded)
    print("  Waiting for process...", end='', flush=True)
    deadline = time.time() + 30
    win_pid = None
    while time.time() < deadline:
        p = get_pid(emu_name)
        if p and p['mem_kb'] > 500000:
            win_pid = p['pid']
            break
        print('.', end='', flush=True)
        time.sleep(2)
    print()

    if not win_pid:
        print("  ❌ Process didn't start.")
        return False

    # Save PID
    pid_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), f'.{emu_name}_pid')
    with open(pid_file, 'w') as f:
        f.write(str(win_pid))

    if gdb:
        print("  ⚠️  Game PAUSED — connect GDB and send 'c'!")
        return True

    # Wait for hooks
    print("  Waiting for hooks...", end='', flush=True)
    deadline = time.time() + 30
    while time.time() < deadline:
        s = read_status_bin(emu_name)
        if s and 'error' not in s and s.get('frame', 0) > 0:
            break
        print('.', end='', flush=True)
        time.sleep(2)
    print()

    s = read_status_bin(emu_name)
    if not s or 'error' in s:
        print(f"  ❌ Hooks not responding.")
        return False

    # Verify frames advancing
    f1 = s['frame']
    time.sleep(0.5)
    s2 = read_status_bin(emu_name)
    f2 = s2.get('frame', f1) if s2 and 'error' not in s2 else f1
    if f2 <= f1:
        print(f"  ❌ Frames not advancing.")
        return False

    print(f"  ✅ Hooks live, {(f2-f1)*2} fps")
    return True


def _is_alive(emu_name):
    """Quick check: process alive AND frames advancing."""
    if not is_running(emu_name):
        return False
    s1 = read_status_bin(emu_name)
    if not s1 or 'error' in s1:
        return False
    f1 = s1.get('frame', 0)
    time.sleep(0.3)
    s2 = read_status_bin(emu_name)
    if not s2 or 'error' in s2:
        return False
    return s2.get('frame', 0) > f1


def _navigate_to_playing(emu_name):
    """Navigate from title screen to play mode. Returns True/False.

    Flow: Title → L+R (menu) → A (editor) → MINUS (play)
    """
    print("  Navigating to play mode...")

    # Wait for title screen (frame > 200 = animation done, L+R banner visible)
    print("    Waiting for title animation...", end='', flush=True)
    s = _wait_frames(emu_name, 'frame', lambda s: s['frame'] > 200, timeout=15)
    if not s:
        print(" ❌ timeout")
        return False
    print(f" frame {s['frame']} ✅")

    # Check alive before each step
    if not _is_alive(emu_name):
        print("    ❌ Game died")
        return False

    # L+R to skip title → Make/Play menu (hold 1.5s, retry up to 3 times)
    for attempt in range(3):
        print(f"    L+R (title skip, attempt {attempt+1})...", end=' ', flush=True)
        _press(BTN_L | BTN_R, 1500)
        time.sleep(2)
        # Verify: scene_mode should still be 6 (title) but we should see a menu
        # The Make/Play menu appears as an overlay on the title — scene_mode stays 6
        # but pressing A should now enter editor. We verify by checking if A works.
        if not _is_alive(emu_name):
            print("❌ crashed")
            return False
        print("✅")
        break  # Can't verify L+R separately — proceed to A and check scene_mode there

    # A to enter Course Maker (Make is default selection)
    # If L+R didn't work, A does nothing and scene_mode stays 6.
    # Retry the whole L+R → A sequence if scene_mode doesn't reach 1.
    for enter_attempt in range(3):
        print(f"    A (enter editor)...", end=' ', flush=True)
        _press(BTN_A, 300)
        loaded = _wait_frames(emu_name, 'scene_mode', lambda s: s.get('scene_mode') == 1, timeout=15)
        if loaded:
            print("✅")
            break
        if not _is_alive(emu_name):
            print("❌ crashed during load")
            return False
        # scene_mode still 6 — L+R probably didn't register. Retry L+R → A.
        print(f"⚠️ still on title (scene_mode=6), retrying L+R...")
        _press(BTN_L | BTN_R, 1500)
        time.sleep(3)
    else:
        print("    ❌ Could not enter editor after 3 attempts")
        return False

    time.sleep(1)
    if not _is_alive(emu_name):
        print("    ❌ Game died after editor load")
        return False

    # B to clear any panel focus, then MINUS to enter play mode
    _press(BTN_B, 100)
    time.sleep(0.3)
    print("    MINUS (play mode)...", end=' ', flush=True)
    _press(BTN_MINUS, 200)
    # Wait for scene_mode to change from 1 (editor) to 5 (play)
    playing = _wait_frames(emu_name, 'scene_mode', lambda s: s.get('scene_mode') == 5, timeout=10)
    if not playing:
        if not _is_alive(emu_name):
            print("❌ crashed")
            return False
        print("⚠️ scene_mode not 5")
    else:
        s = read_status_bin(emu_name)
        if s and 'error' not in s:
            print(f"✅ State:{s['state']} Pos:({s['pos_x']:.0f},{s['pos_y']:.0f})")
        else:
            print("✅")

    return True


def cmd_fresh(emu_name='eden', gdb=False, navigate=True, max_retries=3):
    """Full clean restart: kill → deploy → launch → navigate → verify.
    Auto-retries on crash."""
    print(f"═══ Fresh start: {emu_name} ═══\n")

    for attempt in range(1, max_retries + 1):
        if attempt > 1:
            print(f"\n🔄 Retry {attempt}/{max_retries}...\n")

        # Kill everything
        procs = get_processes()
        if procs.get(emu_name):
            print("① Killing existing instance...")
            cmd_kill(emu_name)
            time.sleep(2)

        if tmux_session_exists(GDB_TMUX_SESSION):
            tmux_kill_session(GDB_TMUX_SESSION)

        # Boot and verify
        print("② Booting...")
        if not _boot_and_verify(emu_name, gdb):
            print(f"  ❌ Boot failed (attempt {attempt})")
            continue

        if gdb:
            print("\n✅ Ready (GDB mode — connect and send 'c').")
            return True

        # Navigate to play mode
        if navigate:
            print("③ Navigating to play mode...")
            if not _navigate_to_playing(emu_name):
                print(f"  ❌ Navigation failed (attempt {attempt})")
                # Check if process is still alive
                if not is_running(emu_name):
                    print("  Process crashed — will retry.")
                    continue
                else:
                    print("  Process alive but navigation stuck.")
                    # Try continuing anyway
                    pass

        # Final status
        print()
        s = read_status_bin(emu_name)
        if s and 'error' not in s and s.get('frame', 0) > 0:
            cmd_game_status(emu_name)
            state = s.get('state', 0)
            has_player = s.get('has_player', 0)
            if navigate and has_player:
                print(f"\n✅ {emu_name} ready! In play mode.")
            elif navigate:
                print(f"\n⚠️  {emu_name} running but player not detected yet.")
            else:
                print(f"\n✅ {emu_name} running (no navigation requested).")
            return True
        else:
            print(f"  ❌ No valid game state after navigation.")
            continue

    print(f"\n❌ Failed after {max_retries} attempts.")
    return False


def cmd_cleanup():
    """Kill orphaned processes and stale tmux sessions."""
    # Kill orphaned emulator processes
    procs = get_processes()
    for name, plist in procs.items():
        for p in plist:
            if p['mem_kb'] < 100000:  # small = probably stale
                try:
                    subprocess.run([TASKKILL, '/PID', str(p['pid']), '/F'],
                                 capture_output=True, timeout=5)
                    print(f"Killed orphaned {p['exe']} PID {p['pid']} ({p['mem_kb']//1024} MB)")
                except:
                    pass

    # List tmux sessions for manual review
    sessions = tmux_list_sessions()
    gdb_sessions = [s for s in sessions if 'gdb' in s.lower()]
    if gdb_sessions:
        print(f"\nGDB tmux sessions found:")
        for s in gdb_sessions:
            print(f"  {s}")
        print(f"Kill with: tmux kill-session -t {GDB_TMUX_SESSION}")

    # Clean up PID files for dead processes
    for emu in EMULATORS:
        pid_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), f'.{emu}_pid')
        if os.path.exists(pid_file) and not is_running(emu):
            os.remove(pid_file)
            print(f"Cleaned stale PID file for {emu}")


def main():
    if len(sys.argv) < 2:
        print("SMM2 Emulator Session Manager")
        print(f"\nUsage: {sys.argv[0]} <command> [args]")
        print("\nCommands:")
        print("  fresh [emu] [--gdb] [--no-nav]  Full cycle: kill → launch → play (USE THIS)")
        print("  overview              Full state overview")
        print("  status                Show running emulators")
        print("  launch <emu> [--gdb]  Launch emulator (eden/ryujinx)")
        print("  kill <emu|all>        Kill emulator processes")
        print("  deploy <emu>          Deploy hooks to emulator")
        print("  gdb-on                Enable GDB stub in config")
        print("  gdb-off               Disable GDB stub in config")
        print("  game-status [emu]     Read game state from status.bin")
        print("  cleanup               Kill orphans, clean stale state")
        sys.exit(0)

    cmd = sys.argv[1]
    if cmd == 'fresh':
        emu = sys.argv[2] if len(sys.argv) > 2 and not sys.argv[2].startswith('-') else 'eden'
        gdb = '--gdb' in sys.argv
        nav = '--no-nav' not in sys.argv
        cmd_fresh(emu, gdb, navigate=nav)
    elif cmd == 'overview':
        cmd_overview()
    elif cmd == 'status':
        cmd_status()
    elif cmd == 'kill':
        cmd_kill(sys.argv[2] if len(sys.argv) > 2 else 'all')
    elif cmd == 'launch':
        emu = sys.argv[2] if len(sys.argv) > 2 else 'eden'
        gdb = '--gdb' in sys.argv
        cmd_launch(emu, gdb)
    elif cmd == 'deploy':
        emu = sys.argv[2] if len(sys.argv) > 2 else 'eden'
        cmd_deploy(emu)
    elif cmd == 'gdb-on':
        gdb_set(True)
    elif cmd == 'gdb-off':
        gdb_set(False)
    elif cmd == 'game-status':
        emu = sys.argv[2] if len(sys.argv) > 2 else 'eden'
        raw = '--raw' in sys.argv
        cmd_game_status(emu, raw=raw)
    elif cmd == 'hexdump':
        emu = sys.argv[2] if len(sys.argv) > 2 else 'eden'
        cmd_hexdump(emu)
    elif cmd == 'cleanup':
        cmd_cleanup()
    else:
        print(f"Unknown command: {cmd}")
        print("Run without args for help.")


if __name__ == '__main__':
    main()
