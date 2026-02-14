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
    goto <state>    Navigate to target state: playing, editor, coursebot, main_menu
    state           Show detected current state
    set-state <s>   Manually set current state (if detection is wrong)
    press <buttons> Press buttons (comma-separated: A,B,RIGHT,ZL,...)
    hold <buttons> <ms>  Hold buttons for duration
    release         Release all buttons
    status          Show status.bin data
    screenshot      Take a screenshot
    title-skip      Get past the title screen (ZL+ZR or A)
    play            Enter play mode from editor (MINUS)
    make            Enter editor mode from play (MINUS)
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
        facing, gravity, buffered, input_polls, real_phase = struct.unpack_from('<ffIIi', data, 40)
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
            'real_game_phase': real_phase,  # 0=title, 3=course maker, 4=story/coursebot, -1=loading
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
    """State-aware automation to get into the test level in play mode.
    
    Detects current game state and takes the shortest path:
    - Title screen (phase 0) → full navigation: L+R, A, RIGHT, A, A, A, hold MINUS
    - Course Maker (phase 3) with player → already in level, just hold MINUS to play
    - Course Maker (phase 3) no player → need to load from coursebot
    - Loading (phase -1) → wait
    
    The test level should be the first course in Coursebot "My Courses".
    """
    print("=== Smart level loader ===")
    
    s = read_status()
    phase = s.get('real_game_phase', -99) if s else -99
    has_player = s.get('has_player', False) if s else False
    state = s.get('player_state', 0) if s else 0
    
    print(f"  Current: phase={phase} player={has_player} state={state}")
    
    # Already in Course Maker with player in play mode?
    if phase == 3 and has_player and state not in (0, 43):
        print("  Already playing in Course Maker! Nothing to do.")
        print(f"=== Ready! Player at ({s['pos_x']:.0f}, {s['pos_y']:.0f}) state={state} ===")
        return
    
    # In Course Maker editor mode (state 43) — just play
    if phase == 3 and has_player and state == 43:
        print("  In editor mode — entering play...")
        hold("MINUS", 1500)
        wait(3000)
        s = read_status()
        if s and s.get('has_player'):
            print(f"=== Ready! Player at ({s['pos_x']:.0f}, {s['pos_y']:.0f}) state={s['player_state']} ===")
        return
    
    # Title screen (phase 0) or unknown — full navigation
    # Sequence: L+R (dismiss title) → PLUS (main menu) → A (coursebot) → A (select) → A (load) → hold MINUS (play)
    if phase == 0 or phase == -99:
        print("  Title screen — full navigation...")
        press("L,R", 200)
        wait(4000)
        press("PLUS", 100)
        wait(3000)
        press("A", 100)
        wait(4000)
        press("A", 100)
        wait(1500)
        press("A", 100)
        wait(4000)
        hold("MINUS", 1500)
        wait(3000)
    
    # Phase 3 but no player — in Course Maker without a level?
    elif phase == 3 and not has_player:
        print("  In Course Maker but no player — trying to enter play...")
        hold("MINUS", 1500)
        wait(3000)
    
    # Loading — wait for a real phase
    elif phase == -1:
        print("  Loading... waiting for game to finish booting...")
        for _ in range(30):  # up to 30s
            wait(1000)
            s = read_status()
            phase = s.get('real_game_phase', -1) if s else -1
            if phase != -1:
                print(f"  Game loaded! Phase={phase} — restarting navigation...")
                return full_load_test_level()  # recurse with new state
        print("  Timed out waiting for game to load")
        return
    
    else:
        print(f"  Phase {phase} — attempting full navigation...")
        press("L,R", 200)
        wait(4000)
        press("PLUS", 100)
        wait(3000)
        press("A", 100)
        wait(4000)
        press("A", 100)
        wait(1500)
        press("A", 100)
        wait(4000)
        hold("MINUS", 1500)
        wait(3000)
    
    s = read_status()
    if s and s.get('has_player'):
        print(f"=== Ready! Player at ({s['pos_x']:.0f}, {s['pos_y']:.0f}) state={s['player_state']} ===")
    else:
        print("=== Navigation may have failed — check screenshot ===")


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

###############################################################################
# State machine: detect current state and navigate to desired state
###############################################################################

# Game states (our abstraction over scenes + sub-states)
STATE_UNKNOWN = "unknown"
STATE_TITLE = "title"           # Title screen (scene 0)
STATE_MAIN_MENU = "main_menu"   # Main menu (scene 2)
STATE_EDITOR = "editor"         # Course Maker edit mode (scene 4, sub: editor)
STATE_PLAYING = "playing"       # Playing a level (scene 4, sub: playing)
STATE_COURSEBOT = "coursebot"    # Coursebot course list (scene 4, sub: coursebot)
STATE_PAUSE = "pause"           # Pause menu during play
STATE_LOADING = "loading"       # Loading screen (scene -1)

# Persistent state file — written after every navigation action
_STATE_FILE = os.path.join(SD_BASE, "nav_state.txt")

def _save_state(state):
    """Persist our believed current state."""
    with open(_STATE_FILE, 'w') as f:
        f.write(state)

def _load_state():
    """Load persisted state, or unknown."""
    if os.path.exists(_STATE_FILE):
        with open(_STATE_FILE, 'r') as f:
            return f.read().strip()
    return STATE_UNKNOWN

def detect_state():
    """Best-effort state detection using persisted nav state.
    
    status.bin is unreliable right now (s_player=NULL, stale data from dead instances).
    We rely on our own navigation state tracking instead.
    TODO: re-enable status.bin detection once player pointer is fixed.
    """
    return _load_state()

def goto(target):
    """Navigate from current state to target state. Returns True on success."""
    current = detect_state()
    print(f"goto: {current} → {target}")

    if current == target:
        print(f"Already at {target}")
        return True

    # Define transitions
    if target == STATE_PLAYING:
        return _goto_playing(current)
    elif target == STATE_EDITOR:
        return _goto_editor(current)
    elif target == STATE_COURSEBOT:
        return _goto_coursebot(current)
    elif target == STATE_MAIN_MENU:
        return _goto_main_menu(current)
    else:
        print(f"Don't know how to reach '{target}'")
        return False

def _goto_playing(current):
    """Get into play mode on the test level."""
    if current == STATE_EDITOR:
        # Two options:
        # 1. Play the CURRENT editor level: short/long MINUS
        # 2. Play the TEST level: go via coursebot
        # Default: play current level from start (long MINUS)
        print("  Editor → Playing (long MINUS for level start)")
        hold("MINUS", 1200)
        wait(3000)
        _save_state(STATE_PLAYING)
        return True
    elif current == STATE_PAUSE:
        # Unpause
        print("  Pause → Playing (short MINUS)")
        press("MINUS", 100)
        wait(1000)
        _save_state(STATE_PLAYING)
        return True
    elif current == STATE_COURSEBOT:
        # Already in coursebot — select test level → Play
        print("  Coursebot → select test → Play")
        press("A", 100)         # Select first course (test)
        wait(2000)
        # Now on course detail — cursor defaults to Make
        # Navigate to Play: DOWN x3
        for _ in range(3):
            press("DOWN", 100)
            wait(800)
        press("A", 100)         # Play (single press in coursebot)
        wait(4000)              # Wait for level load + title card
        _save_state(STATE_PLAYING)
        return True
    elif current == STATE_MAIN_MENU:
        # Main menu → Coursebot → Play
        if _goto_coursebot(current):
            return _goto_playing(STATE_COURSEBOT)
        return False
    elif current == STATE_TITLE:
        # Title → L+R skip → lands in Course Maker editor (NOT main menu)
        print("  Title → skip (L+R → editor)")
        hold("ZL,ZR", 500)
        wait(2000)
        press("A", 100)
        wait(5000)              # Editor takes a moment to load
        _save_state(STATE_EDITOR)
        # Editor has whatever level was last open — go via coursebot to load test level
        if _goto_coursebot(STATE_EDITOR):
            return _goto_playing(STATE_COURSEBOT)
        return False
    else:
        print(f"  Don't know how to go from {current} to playing")
        return False

def _goto_editor(current):
    """Get into Course Maker editor."""
    if current == STATE_PLAYING:
        # Long MINUS → pause menu: Start Over / Exit Course / Edit Course
        # Need DOWN x2 to reach Edit Course (DOWN x1 = Exit Course!)
        print("  Playing → Pause → Edit Course")
        hold("MINUS", 1200)
        wait(2000)              # Wait for pause menu to fully render
        press("DOWN", 100)
        wait(800)
        press("DOWN", 100)
        wait(800)
        press("A", 100)         # Edit Course
        wait(3000)              # Wait for editor to load
        _save_state(STATE_EDITOR)
        return True
    elif current == STATE_PAUSE:
        # Pause menu: Start Over / Exit Course / Edit Course
        print("  Pause → Edit Course (DOWN x2 → A)")
        press("DOWN", 100)
        wait(800)
        press("DOWN", 100)
        wait(800)
        press("A", 100)
        wait(3000)
        _save_state(STATE_EDITOR)
        return True
    elif current == STATE_COURSEBOT:
        # Select test → Make
        print("  Coursebot → select test → Make")
        press("A", 100)         # Select first course
        wait(2000)
        press("A", 100)         # Make (default selection)
        wait(3000)
        _save_state(STATE_EDITOR)
        return True
    elif current == STATE_MAIN_MENU:
        if _goto_coursebot(current):
            return _goto_editor(STATE_COURSEBOT)
        return False
    else:
        print(f"  Don't know how to go from {current} to editor")
        return False

def _goto_coursebot(current):
    """Get to the Coursebot course list."""
    if current == STATE_MAIN_MENU:
        print("  Main menu → Coursebot (RIGHT → A)")
        # From main menu, Course Maker is selected. Coursebot is RIGHT.
        press("RIGHT", 100)
        wait(800)
        press("A", 100)
        wait(3000)              # Coursebot load animation
        _save_state(STATE_COURSEBOT)
        return True
    elif current == STATE_EDITOR:
        # Editor → PLUS → main menu → RIGHT → coursebot
        print("  Editor → Main menu (PLUS)")
        press("PLUS", 100)
        wait(2000)
        _save_state(STATE_MAIN_MENU)
        return _goto_coursebot(STATE_MAIN_MENU)
    elif current == STATE_PLAYING:
        # Playing → pause → Exit Course (DOWN x1) → main menu → coursebot
        print("  Playing → Pause → Exit Course")
        hold("MINUS", 1200)
        wait(2000)
        press("DOWN", 100)      # Start Over → Exit Course
        wait(800)
        press("A", 100)         # Exit Course
        wait(3000)
        _save_state(STATE_MAIN_MENU)
        return _goto_coursebot(STATE_MAIN_MENU)
    else:
        print(f"  Don't know how to go from {current} to coursebot")
        return False

def _goto_main_menu(current):
    """Get to the main menu."""
    if current == STATE_EDITOR:
        print("  Editor → Main menu (PLUS)")
        press("PLUS", 100)
        wait(2000)
        _save_state(STATE_MAIN_MENU)
        return True
    elif current == STATE_PLAYING:
        print("  Playing → Pause → Exit Course")
        hold("MINUS", 1200)
        wait(1500)
        press("DOWN", 100)      # Exit Course
        wait(500)
        press("A", 100)
        wait(3000)
        _save_state(STATE_MAIN_MENU)
        return True
    elif current == STATE_COURSEBOT:
        print("  Coursebot → B to exit")
        press("B", 100)
        wait(2000)
        _save_state(STATE_MAIN_MENU)
        return True
    elif current == STATE_TITLE:
        # L+R skip goes to editor, then PLUS to main menu
        print("  Title → skip → editor → PLUS → main menu")
        hold("ZL,ZR", 500)
        wait(2000)
        press("A", 100)
        wait(5000)
        _save_state(STATE_EDITOR)
        return _goto_main_menu(STATE_EDITOR)
    else:
        print(f"  Don't know how to go from {current} to main_menu")
        return False


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
    elif cmd == "goto":
        if len(sys.argv) < 3:
            print("Usage: automate.py goto <state>")
            print(f"States: playing, editor, coursebot, main_menu")
            sys.exit(1)
        target = sys.argv[2]
        aliases = {"play": STATE_PLAYING, "playing": STATE_PLAYING,
                   "edit": STATE_EDITOR, "editor": STATE_EDITOR,
                   "coursebot": STATE_COURSEBOT, "menu": STATE_MAIN_MENU,
                   "main_menu": STATE_MAIN_MENU}
        target = aliases.get(target, target)
        if not goto(target):
            sys.exit(1)
    elif cmd == "state":
        st = detect_state()
        print(f"Current state: {st}")
    elif cmd == "set-state":
        if len(sys.argv) < 3:
            print("Usage: automate.py set-state <state>")
            sys.exit(1)
        _save_state(sys.argv[2])
        print(f"State set to: {sys.argv[2]}")
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
                phase = s.get('real_game_phase', -99)
                phase_str = {-1: 'loading', 0: 'title', 3: 'course maker', 4: 'story/coursebot'}.get(phase, f'unknown({phase})')
                print(f"Phase:   {phase} ({phase_str})")
        else:
            print("No status data (game not running or hooks not active)")
    else:
        print(f"Unknown command: {cmd}")
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
