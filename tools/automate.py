#!/usr/bin/env python3
"""
SMM2 Game Automation — navigate menus, load levels, control game state.

Uses:
  - input.bin injection for button presses
  - screenshot capture for screen detection (optional)
  - CSV hook data for game state awareness

Usage:
    python3 tools/automate.py <command> [options]

Commands:
    title-skip      Get past the title screen (ZL+ZR or A)
    load-test-level Full automation: title → coursebot → load test level → play
    main-menu       Exit Course Maker to main menu
    coursebot        Navigate from main menu to Coursebot
    course-maker    Navigate to Course Maker
    play            Enter play mode from editor (MINUS)
    make            Enter editor mode from play (MINUS)
    reset-level     Long-press rocket to reset level
    reposition      Long-press start to reposition Mario
    release         Release all buttons
    press <buttons> Press buttons (comma-separated: A,B,RIGHT,ZL,...)
    hold <buttons> <ms>  Hold buttons for duration
"""

import struct
import sys
import time
import os
import subprocess
try:
    from dotenv import load_dotenv
    _repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    load_dotenv(os.path.join(_repo_root, ".env"))
except ImportError:
    # python-dotenv not installed — fall back to manual .env parsing
    _repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    _env_path = os.path.join(_repo_root, ".env")
    if os.path.exists(_env_path):
        with open(_env_path) as _f:
            for _line in _f:
                _line = _line.strip()
                if _line and not _line.startswith('#') and '=' in _line:
                    _k, _v = _line.split('=', 1)
                    os.environ.setdefault(_k.strip(), _v.strip())

# Paths (all configurable via .env)
SD_BASE = os.environ.get("RYUJINX_SD_PATH", "")
if not SD_BASE:
    print("Error: RYUJINX_SD_PATH not set. Copy .env.example to .env and configure it.")
    sys.exit(1)
INPUT_BIN = os.path.join(SD_BASE, "input.bin")
SCREENSHOT_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "screenshot_ryujinx.ps1")
SCREENSHOT_OUT = os.environ.get("SCREENSHOT_OUT", "/mnt/c/temp/smm2_debug/capture.png")
WSL_DISTRO = os.environ.get("WSL_DISTRO", "Ubuntu")

# Button bitmasks (Pro Controller / HID)
BUTTONS = {
    "A":     0x01,
    "B":     0x02,
    "X":     0x04,
    "Y":     0x08,
    "L":     0x40,
    "R":     0x80,
    "ZL":    0x100,
    "ZR":    0x200,
    "PLUS":  0x400,
    "MINUS": 0x800,
    "LEFT":  0x1000,
    "UP":    0x2000,
    "RIGHT": 0x4000,
    "DOWN":  0x8000,
    "LSTICK": 0x20000,
    "RSTICK": 0x40000,
}


def write_input(buttons=0, stick_lx=0, stick_ly=0):
    """Write controller state to input.bin for the TAS plugin to read."""
    data = struct.pack('<Qii', buttons, stick_lx, stick_ly)
    with open(INPUT_BIN, 'wb') as f:
        f.write(data)


def parse_buttons(button_str):
    """Parse comma-separated button names into bitmask."""
    mask = 0
    for name in button_str.upper().split(','):
        name = name.strip()
        if name in BUTTONS:
            mask |= BUTTONS[name]
        else:
            print(f"Unknown button: {name}")
            print(f"Valid: {', '.join(sorted(BUTTONS.keys()))}")
            sys.exit(1)
    return mask


def press(buttons, duration_ms=100):
    """Press buttons for a duration, then release."""
    mask = buttons if isinstance(buttons, int) else parse_buttons(buttons)
    write_input(mask)
    time.sleep(duration_ms / 1000.0)
    write_input(0)


def hold(buttons, duration_ms):
    """Hold buttons for a longer duration (e.g., long press)."""
    mask = buttons if isinstance(buttons, int) else parse_buttons(buttons)
    write_input(mask)
    time.sleep(duration_ms / 1000.0)
    write_input(0)


def wait(ms):
    """Wait without pressing anything."""
    time.sleep(ms / 1000.0)


def screenshot():
    """Take a screenshot and return the path."""
    # Convert WSL path to UNC for PowerShell
    ps_script = f"\\\\wsl.localhost\\{WSL_DISTRO}{SCREENSHOT_SCRIPT}"
    ps_out = SCREENSHOT_OUT.replace("/mnt/c/", "C:\\").replace("/", "\\")
    subprocess.run([
        "powershell.exe", "-File", ps_script,
        "-OutPath", ps_out
    ], capture_output=True)
    return SCREENSHOT_OUT


def read_status():
    """Read status.bin for real-time game state (updated every frame by hooks).
    Supports both 32-byte (v1) and 64-byte (v2) status blocks."""
    path = os.path.join(SD_BASE, "status.bin")
    if not os.path.exists(path):
        return None
    with open(path, 'rb') as f:
        data = f.read(64)
    if len(data) < 32:
        return None
    frame, phase, state, powerup = struct.unpack_from('<IIII', data, 0)
    pos_x, pos_y, vel_x, vel_y = struct.unpack_from('<ffff', data, 16)
    result = {
        'frame': frame, 'game_phase': phase,
        'player_state': state, 'powerup_id': powerup,
        'pos_x': pos_x, 'pos_y': pos_y,
        'vel_x': vel_x, 'vel_y': vel_y,
    }
    # Extended v2 fields (64-byte block)
    if len(data) >= 64:
        state_frames, flags_byte = struct.unpack_from('<IB', data, 32)
        in_water = flags_byte
        is_dead, is_goal, has_player = struct.unpack_from('<BBB', data, 37)
        facing, gravity, buffered, input_polls = struct.unpack_from('<ffII', data, 40)
        result.update({
            'state_frames': state_frames,
            'in_water': in_water,
            'is_dead': is_dead,
            'is_goal': is_goal,
            'has_player': has_player,
            'facing': facing,
            'gravity': gravity,
            'buffered_action': buffered,
            'input_polls': input_polls,
        })
    return result


def read_fields_csv():
    """Read latest line from fields.csv for game state."""
    path = os.path.join(SD_BASE, "fields.csv")
    if not os.path.exists(path):
        return None
    with open(path, 'r') as f:
        lines = f.readlines()
    if len(lines) < 2:
        return None
    last = lines[-1].strip().split(',')
    header = lines[0].strip().split(',')
    return dict(zip(header, last))


def wait_for_state(target_state, timeout_ms=10000):
    """Poll status.bin until player reaches target state."""
    deadline = time.time() + timeout_ms / 1000.0
    while time.time() < deadline:
        s = read_status()
        if s and s['player_state'] == target_state:
            return s
        time.sleep(0.05)  # 50ms poll
    return None


def is_playing():
    """Check if we're in gameplay (player state != 0)."""
    s = read_status()
    return s and s['player_state'] != 0


# ============================================================
# High-level automation commands
# ============================================================

def title_skip():
    """Skip title screen. Press A, wait, press A again."""
    print("Skipping title screen...")
    press("A", 100)
    wait(2000)
    press("A", 100)
    wait(1000)
    press("A", 100)
    print("Done — should be past title screen")


def course_maker():
    """Navigate to Course Maker from main menu.
    TODO: This needs screenshot-based navigation since menu layout varies.
    For now, assumes we're at the main menu.
    """
    print("Navigating to Course Maker...")
    # Main menu: Course Maker is typically the middle-right option
    # This sequence may need adjustment based on menu state
    press("A", 100)  # Select
    wait(3000)        # Loading
    print("Done — check screenshot to verify")


def enter_play():
    """Enter play mode from editor (plays in place, Mario stays where he is)."""
    print("Entering play mode (in place)...")
    press("MINUS", 100)
    wait(3000)
    print("In play mode")


def enter_play_reset():
    """Enter play mode from editor with Mario reset to start position."""
    print("Entering play mode (reset to start)...")
    hold("MINUS", 1500)  # Long press = reset + play
    wait(3000)
    print("In play mode (from start)")


def enter_make():
    """Enter editor mode from play."""
    print("Entering editor mode...")
    press("MINUS", 100)
    wait(1000)
    print("In editor mode")


def wait_for_scene(target_scene, timeout_s=15):
    """Wait for a PlayReport scene change by polling status.bin.
    Scene map: -1=loading, 0=title, 2=main menu, 4=Course Maker/Coursebot.
    We detect scene changes via game_phase in status.bin:
    Phase 0=title/menu, 3=Course Maker, 4=Story/Coursebot playing.
    Since status.bin doesn't have scene directly, we use has_player and game_phase."""
    # For now just wait a fixed time — TODO: use console output parsing
    time.sleep(timeout_s)
    return read_status()


def wait_for_player(timeout_s=10):
    """Wait until has_player becomes true in status.bin."""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        s = read_status()
        if s and s.get('has_player'):
            return s
        time.sleep(0.2)
    return None


def navigate_to_main_menu():
    """From Course Maker (scene 4), go to main menu (scene 2).
    Press B to exit editor, then confirm."""
    print("Navigating to main menu...")
    # From Course Maker: press B to exit
    press("B", 100)
    wait(500)
    press("B", 100)
    wait(500)
    # Confirm exit dialog (if any) — press A
    press("A", 100)
    wait(3000)
    print("Should be at main menu now")


def navigate_to_coursebot():
    """From main menu (scene 2), navigate to Coursebot.
    Main menu layout (top to bottom, roughly):
    - Course Maker (center, default selection)
    - Story Mode (left)
    - Course World (right)  
    - Coursebot (bottom-right)
    
    From Course Maker selection, press DOWN then RIGHT to reach Coursebot,
    then A to enter."""
    print("Navigating to Coursebot...")
    # From main menu — Coursebot is typically accessed via DOWN
    press("DOWN", 100)
    wait(300)
    press("DOWN", 100)
    wait(300)
    press("A", 100)  # Enter Coursebot
    wait(3000)  # Wait for Coursebot to load
    print("Should be in Coursebot now")


def coursebot_load_test_level():
    """In Coursebot, navigate to "My Courses" and load the test level.
    The test level is called "test" — NSMBU Underwater, slot 75.
    
    Coursebot tabs: My Courses | Courses from Others | Liked Courses
    Default tab is "My Courses".
    Courses are shown in a grid. "test" may not be the first one.
    
    For now: navigate to the last page and look for it.
    TODO: use screenshot to find the exact position."""
    print("Loading test level from Coursebot...")
    # In Coursebot "My Courses" tab, courses are displayed in a grid
    # The most recently edited course should be near the top
    # Just press A on the first course to select it, then Play
    press("A", 100)  # Select first course
    wait(1000)
    # Course detail screen — "Play" button should be available
    press("A", 100)  # Press Play
    wait(3000)  # Wait for level to load
    print("Level should be loading...")


def full_load_test_level():
    """Full automation: from title screen to test level in play mode.
    Sequence: title-skip → main menu → coursebot → load test → play
    
    Uses console PlayReports for scene awareness (scene numbers in output).
    """
    print("=== Full level load automation ===")
    
    # Step 1: Skip title
    print("[1/5] Skipping title screen...")
    press("A", 100)
    wait(3000)
    press("A", 100) 
    wait(2000)
    
    # Step 2: We should be in Course Maker (scene 0→4)
    # Check if we have a player (= Course Maker loaded)
    s = read_status()
    if s and s.get('has_player'):
        print("[2/5] In Course Maker — exiting to main menu...")
        press("B", 100)
        wait(500)
        press("B", 100)  
        wait(500)
        press("A", 100)  # Confirm exit
        wait(3000)
    else:
        print("[2/5] Waiting for game to load...")
        wait(5000)
    
    # Step 3: Navigate to Coursebot from main menu
    print("[3/5] Navigating to Coursebot...")
    # Main menu: move selection to Coursebot
    press("DOWN", 100)
    wait(300)
    press("DOWN", 100)
    wait(300)
    press("A", 100)
    wait(4000)  # Coursebot loading
    
    # Step 4: Select and load a course
    print("[4/5] Selecting first course...")
    press("A", 100)  # Select course
    wait(1500)
    press("A", 100)  # Play/Edit
    wait(4000)  # Level loading
    
    # Step 5: Enter play mode
    print("[5/5] Entering play mode...")
    s = read_status()
    if s:
        print(f"  Status: frame={s['frame']} player={'yes' if s.get('has_player') else 'no'} state={s['player_state']}")
    
    # If we're in editor (state 43), enter play mode
    if s and s.get('has_player') and s['player_state'] == 43:
        hold("MINUS", 1500)  # Long press = reset + play
        wait(2000)
    
    s = read_status()
    if s and s.get('has_player'):
        print(f"=== Ready! Player at ({s['pos_x']:.0f}, {s['pos_y']:.0f}) state={s['player_state']} ===")
    else:
        print("=== Level loaded but no player yet — may need manual navigation ===")


def reset_level():
    """Long-press rocket to reset entire level."""
    print("Resetting level (long-press rocket)...")
    # Rocket is a UI element — need touch input or specific button combo
    # For now: PLUS opens pause, then navigate to reset?
    # Actually, in editor mode the rocket is clickable via touch
    # TODO: find the actual button shortcut for reset
    print("TODO: need to figure out button shortcut for rocket reset")
    print("For now, use screenshot + click approach")


def reposition_mario():
    """Long-press start to reposition Mario at cursor."""
    print("Repositioning Mario (long-press PLUS)...")
    hold("PLUS", 1500)  # Long press
    wait(500)
    print("Mario repositioned")


# ============================================================
# CLI
# ============================================================

def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "title-skip":
        title_skip()
    elif cmd == "load-test-level":
        full_load_test_level()
    elif cmd == "coursebot":
        navigate_to_coursebot()
    elif cmd == "main-menu":
        navigate_to_main_menu()
    elif cmd == "course-maker":
        course_maker()
    elif cmd == "play":
        enter_play()
    elif cmd == "play-reset":
        enter_play_reset()
    elif cmd == "make":
        enter_make()
    elif cmd == "reset-level":
        reset_level()
    elif cmd == "reposition":
        reposition_mario()
    elif cmd == "release":
        write_input(0)
        print("Released all buttons")
    elif cmd == "press":
        if len(sys.argv) < 3:
            print("Usage: automate.py press <buttons>")
            sys.exit(1)
        press(sys.argv[2])
        print(f"Pressed {sys.argv[2]}")
    elif cmd == "hold":
        if len(sys.argv) < 4:
            print("Usage: automate.py hold <buttons> <ms>")
            sys.exit(1)
        hold(sys.argv[2], int(sys.argv[3]))
        print(f"Held {sys.argv[2]} for {sys.argv[3]}ms")
    elif cmd == "screenshot":
        path = screenshot()
        print(f"Screenshot saved: {path}")
    elif cmd == "status":
        s = read_status()
        if s:
            print(f"Frame:   {s['frame']}")
            mode_str = {0: '(unknown)', 1: '(playing)', 2: '(goal)', 3: '(dead)'}.get(s['game_phase'], '')
            print(f"Mode:    {s['game_phase']} {mode_str}")
            print(f"State:   {s['player_state']}", end="")
            if s.get('is_dead'): print(" [DEAD]", end="")
            if s.get('is_goal'): print(" [GOAL]", end="")
            print()
            print(f"Powerup: {s['powerup_id']}")
            print(f"Pos:     ({s['pos_x']:.2f}, {s['pos_y']:.2f})")
            print(f"Vel:     ({s['vel_x']:.4f}, {s['vel_y']:.4f})")
            if 'state_frames' in s:
                print(f"StFrm:   {s['state_frames']}")
                print(f"Water:   {s['in_water']}  Facing: {s.get('facing', 0):.1f}  Gravity: {s.get('gravity', 0):.2f}")
                print(f"Player:  {'yes' if s.get('has_player') else 'no'}")
                print(f"Polls:   {s.get('input_polls', 0)}")
        else:
            print("No status data (game not running or hooks not active)")
    else:
        print(f"Unknown command: {cmd}")
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
