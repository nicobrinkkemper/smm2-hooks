"""smm2.py — Clean Python API for SMM2 game manipulation.

Usage:
    from smm2 import Game
    g = Game('eden')
    g.scene()        # → 'editor' | 'play' | 'title' | 'loading' | 'unknown'
    g.status()       # → dict with all status.bin fields
    g.press('A')     # press button for 100ms
    g.hold('A', 500) # hold for 500ms
    g.walk_to(200)   # walk right/left until x ≈ 200
    g.recover()      # from any state → play mode
    g.fresh()        # kill, boot, navigate to play
"""

import struct
import os
import time
import subprocess
from pathlib import Path

# Max age in seconds before status.bin is considered stale
STATUS_MAX_AGE = 5.0

# Button constants (nn::hid::NpadFullKeyState)
BTN = {
    'A': 0x01, 'B': 0x02, 'X': 0x04, 'Y': 0x08,
    'L': 0x40, 'R': 0x80, 'ZL': 0x100, 'ZR': 0x200,
    'PLUS': 0x400, 'MINUS': 0x800,
    'LEFT': 0x1000, 'UP': 0x2000, 'RIGHT': 0x4000, 'DOWN': 0x8000,
    'LSTICK': 0x20000, 'RSTICK': 0x40000,
}

# Scene mode values from GPM inner struct +0x14
SCENE_EDITOR = 1
SCENE_PLAY = 5      # Editor test-play
SCENE_TITLE = 6
SCENE_COURSEBOT = 7 # Coursebot play (game-only, no editing)

# Game style IDs (from GamePhaseManager inner+0x1C)
STYLE_SMB1  = 0
STYLE_SMB3  = 1
STYLE_SMW   = 2
STYLE_NSMBU = 3
STYLE_SM3DW = 4

STYLE_NAMES = {0: 'SMB1', 1: 'SMB3', 2: 'SMW', 3: 'NSMBU', 4: '3DW'}

# State names for common states
STATE_NAMES = {
    1: 'Walk', 2: 'Fall', 3: 'Jump', 4: 'Landing', 5: 'Crouch',
    6: 'CrouchEnd', 9: 'Damage', 10: 'Death', 23: 'TumbleLand',
    43: 'EditorIdle', 
    # Yoshi states — style-conditional (Possamodder's analysis)
    103: 'YoshiJumpWii',   # 0x67 — all styles except SMW
    104: 'YoshiJumpWorld', # 0x68 — SMW only
    113: 'Death2', 114: 'PostDeath',
    122: 'GoalPole', 124: 'GoalEnter',
}

DEATH_STATES = {9, 10, 113, 114}
GOAL_STATES = {122, 124}


class Game:
    """High-level SMM2 game controller."""

    def __init__(self, emu='eden'):
        self.emu = emu
        # Load .env
        env_path = Path(__file__).parent.parent / '.env'
        if env_path.exists():
            for line in env_path.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    k, v = line.split('=', 1)
                    os.environ.setdefault(k.strip(), v.strip())

        if emu == 'eden':
            self.sd = os.environ.get('EDEN_SD_PATH', '')
        else:
            self.sd = os.environ.get('RYUJINX_SD_PATH', '')

        if not self.sd:
            raise ValueError(f"SD path not configured for {emu}. Set {'EDEN' if emu == 'eden' else 'RYUJINX'}_SD_PATH in .env")

        self.status_path = os.path.join(self.sd, 'status.bin')
        self.input_path = os.path.join(self.sd, 'input.bin')

    # ── Process Detection ───────────────────────────────────

    def is_running(self):
        """Check if the emulator process is actually running."""
        proc_name = 'eden' if self.emu == 'eden' else 'Ryujinx'
        try:
            result = subprocess.run(
                ['tasklist.exe'],
                capture_output=True, text=True, timeout=5
            )
            return proc_name.lower() in result.stdout.lower()
        except Exception:
            return False

    def _status_age(self):
        """Get age of status.bin in seconds, or None if missing."""
        try:
            mtime = os.path.getmtime(self.status_path)
            return time.time() - mtime
        except (FileNotFoundError, OSError):
            return None

    # ── Status ──────────────────────────────────────────────

    def status(self, allow_stale=False):
        """Read status.bin → dict. Returns None if unavailable or stale.
        
        Args:
            allow_stale: If False (default), returns None when file is older
                        than STATUS_MAX_AGE seconds (game not running).
        """
        # Check file freshness first
        if not allow_stale:
            age = self._status_age()
            if age is None or age > STATUS_MAX_AGE:
                return None
        
        for attempt in range(3):
            try:
                with open(self.status_path, 'rb') as f:
                    d = f.read()
                break
            except (FileNotFoundError, PermissionError):
                if attempt == 2:
                    return None
                time.sleep(0.01)
        if len(d) < 100:
            return None

        return {
            'frame':       struct.unpack_from('<I', d, 0x00)[0],
            'game_phase':  struct.unpack_from('<I', d, 0x04)[0],
            'state':       struct.unpack_from('<I', d, 0x08)[0],
            'powerup':     struct.unpack_from('<I', d, 0x0C)[0],
            'x':           struct.unpack_from('<f', d, 0x10)[0],
            'y':           struct.unpack_from('<f', d, 0x14)[0],
            'vx':          struct.unpack_from('<f', d, 0x18)[0],
            'vy':          struct.unpack_from('<f', d, 0x1C)[0],
            'state_frames': struct.unpack_from('<I', d, 0x20)[0],
            'in_water':    d[0x24],
            'is_dead':     d[0x25],
            'is_goal':     d[0x26],
            'has_player':  d[0x27],
            'facing':      struct.unpack_from('<f', d, 0x28)[0],
            'gravity':     struct.unpack_from('<f', d, 0x2C)[0],
            'buffered':    struct.unpack_from('<I', d, 0x30)[0],
            'polls':       struct.unpack_from('<I', d, 0x34)[0],
            'real_phase':  struct.unpack_from('<i', d, 0x38)[0],
            'theme':       d[0x3C],
            'style':       struct.unpack_from('<I', d, 0x40)[0],
            'scene_mode':  struct.unpack_from('<I', d, 0x44)[0],
            'is_playing':  struct.unpack_from('<I', d, 0x48)[0],
            'scene_change_count': struct.unpack_from('<I', d, 0x8C)[0] if len(d) >= 0x90 else 0,
            # Collision data (from decomp discovery)
            'collision_index': struct.unpack_from('<i', d, 0x90)[0] if len(d) >= 0xA0 else -1,
            'collision_normal': d[0x94] if len(d) >= 0xA0 else 0,
            'collision_slope': struct.unpack_from('<i', d, 0x98)[0] if len(d) >= 0xA0 else 0,
        }

    def scene(self):
        """Current screen: 'editor', 'play', 'coursebot', 'title', 'loading', or 'unknown'."""
        s = self.status()
        if not s:
            return 'unknown'
        sc = s['scene_mode']
        if sc == SCENE_EDITOR:
            return 'editor'
        elif sc == SCENE_PLAY:
            return 'play'
        elif sc == SCENE_COURSEBOT:
            return 'coursebot'
        elif sc == SCENE_TITLE:
            return 'title'
        elif s['real_phase'] == -1:
            return 'loading'
        return 'unknown'

    def alive(self):
        """Is the game process running and hooks active?"""
        # Quick check: is status fresh?
        s = self.status()
        if not s:
            return False
        # Double-check: frame counter advancing?
        f1 = s['frame']
        time.sleep(0.35)
        s2 = self.status()
        return s2 and s2['frame'] > f1

    def is_dead(self):
        """Is Mario in a death state?"""
        s = self.status()
        return s and s['state'] in DEATH_STATES

    def is_goal(self):
        """Did Mario reach the goal?"""
        s = self.status()
        return s and s['state'] in GOAL_STATES

    # ── Input ───────────────────────────────────────────────

    def _write_input(self, buttons=0, lx=0, ly=0):
        """Write raw input to input.bin. Retries on permission error (NTFS lock)."""
        data = struct.pack('<Qii', buttons, lx, ly)
        for attempt in range(5):
            try:
                with open(self.input_path, 'wb') as f:
                    f.write(data)
                return
            except PermissionError:
                time.sleep(0.01)  # 10ms retry

    def _parse_buttons(self, buttons):
        """Parse button string or int to bitmask."""
        if isinstance(buttons, int):
            return buttons
        mask = 0
        for name in buttons.upper().replace('+', ',').split(','):
            name = name.strip()
            if name in BTN:
                mask |= BTN[name]
            else:
                raise ValueError(f"Unknown button: {name}. Valid: {', '.join(sorted(BTN))}")
        return mask

    def press(self, buttons, ms=100):
        """Press button(s) for duration then release. Accepts 'A', 'L+R', 0x4000, etc."""
        mask = self._parse_buttons(buttons)
        self._write_input(mask)
        time.sleep(ms / 1000)
        self._write_input(0)

    def hold(self, buttons, ms=1000):
        """Hold button(s) for duration then release."""
        self.press(buttons, ms)

    def stick(self, lx=0, ly=0, ms=100):
        """Push analog stick for duration."""
        self._write_input(0, lx, ly)
        time.sleep(ms / 1000)
        self._write_input(0)

    def release(self):
        """Release all inputs."""
        self._write_input(0)

    # ── Movement ────────────────────────────────────────────

    def walk_to(self, target_x, timeout=10, use_analog=False):
        """Walk Mario to target x position. Returns True if reached.
        
        Args:
            target_x: target x coordinate
            timeout: max seconds
            use_analog: use analog stick (required for 3DW)
        """
        deadline = time.time() + timeout
        tolerance = 4.0
        last_dir = 0

        while time.time() < deadline:
            s = self.status()
            if not s or not s['has_player']:
                self.release()
                return False
            if s['state'] in DEATH_STATES:
                self.release()
                return False

            dx = target_x - s['x']
            if abs(dx) < tolerance:
                self.release()
                return True

            # Only re-write input when direction changes (reduces file I/O contention)
            new_dir = 1 if dx > 0 else -1
            if new_dir != last_dir:
                if use_analog:
                    self._write_input(0, 32767 * new_dir, 0)
                else:
                    btn = BTN['RIGHT'] if new_dir > 0 else BTN['LEFT']
                    self._write_input(btn)
                last_dir = new_dir

            time.sleep(0.15)

        self.release()
        return False

    def jump(self, hold_ms=200):
        """Jump. hold_ms controls height."""
        self.press('A', hold_ms)

    def wait_for(self, condition, timeout=10, poll_interval=0.1):
        """Wait until condition(status) is True. Returns status or None."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            s = self.status()
            if s and condition(s):
                return s
            time.sleep(poll_interval)
        return None

    # ── Navigation ──────────────────────────────────────────

    def recover(self, timeout=30, mode='edit'):
        """From any state, get back to play mode. Returns True on success.
        
        Args:
            mode: 'edit' = edit/play mode (MINUS toggle, death → editor)
                  'game' = game-only mode (Coursebot Play, death → restart)
        """
        sc = self.scene()

        if sc == 'play':
            s = self.status()
            if s and s['state'] not in DEATH_STATES:
                return True
            if mode == 'edit':
                # Death in edit/play → returns to editor automatically
                self.wait_for(lambda s: s['scene_mode'] == SCENE_EDITOR, timeout=timeout)
                sc = 'editor'
            else:
                # Death in game-only → auto-restarts, just wait for Walk state
                result = self.wait_for(
                    lambda s: s['scene_mode'] == SCENE_PLAY and s['state'] not in DEATH_STATES and s['has_player'],
                    timeout=timeout
                )
                return result is not None

        if sc == 'editor':
            # Clear any UI focus, then MINUS to play
            self.press('B', 100)
            time.sleep(0.3)
            self.press('X', 100)
            time.sleep(0.3)
            self.press('MINUS', 200)
            result = self.wait_for(lambda s: s['scene_mode'] == SCENE_PLAY, timeout=10)
            return result is not None

        if sc == 'title':
            # L+R → A → editor → play
            self.hold('L+R', 1500)
            time.sleep(2)
            self.press('A', 300)
            if not self.wait_for(lambda s: s['scene_mode'] == SCENE_EDITOR, timeout=15):
                return False
            time.sleep(1)
            return self.recover(mode=mode)  # recurse from editor

        return False

    def start_over(self):
        """In game-only play: PLUS → Start Over (first menu option) → A.
        Resets level from beginning without returning to editor/coursebot."""
        self.press('PLUS', 200)
        time.sleep(1)
        # "Start Over" is first option in pause menu
        self.press('A', 200)
        time.sleep(2)
        return self.wait_for(
            lambda s: s['scene_mode'] == SCENE_PLAY and s['has_player'] and s['state'] not in DEATH_STATES,
            timeout=10
        ) is not None

    def to_coursebot_play(self, slot=0, timeout=30):
        """Navigate: editor → Coursebot → select level → Play (game-only mode).
        
        Args:
            slot: course slot to select (0 = first/top, supports 0-based index)
            
        Flow: Editor → PLUS (menu) → RIGHT (coursebot) → A (enter) → 
              navigate to slot → A (select) → DOWN×3 (Play) → A (start)
              
        Note: Coursebot play is scene_mode=7 (not 5 like editor test-play)
        """
        # First get to editor
        if not self.to_editor():
            return False
        
        # Clear any focus
        self.press('B', 100)
        time.sleep(0.3)
        
        # PLUS → Main Menu
        self.press('PLUS', 150)
        time.sleep(1.5)  # wait for menu animation
        
        # RIGHT → Coursebot icon
        self.press('RIGHT', 100)
        time.sleep(0.3)
        
        # A → Enter Coursebot
        self.press('A', 100)
        time.sleep(3.0)  # wait for coursebot to load courses
        
        # Navigate to slot (grid is 4 columns wide)
        # slot 0 is already selected, navigate for others
        row = slot // 4
        col = slot % 4
        for _ in range(col):
            self.press('RIGHT', 100)
            time.sleep(0.2)
        for _ in range(row):
            self.press('DOWN', 100)
            time.sleep(0.2)
        
        # A → Select course
        self.press('A', 100)
        time.sleep(2.0)  # wait for course details
        
        # Navigate to "Play" option (4th option: Make, Upload, Play Together, Play)
        for _ in range(3):
            self.press('DOWN', 100)
            time.sleep(0.2)
        
        # A → Start playing
        self.press('A', 100)
        
        # Wait for coursebot play mode (scene 7)
        # Note: has_player may be 0 in coursebot mode, check state + position instead
        result = self.wait_for(
            lambda s: s['scene_mode'] == SCENE_COURSEBOT and s['state'] > 0,
            timeout=timeout
        )
        return result is not None

    def to_editor(self, timeout=30, debug=False):
        """Navigate to editor. Returns True on success."""
        # Wait for valid scene first
        s = self.wait_for(lambda s: s['scene_mode'] in (SCENE_EDITOR, SCENE_PLAY, SCENE_TITLE), timeout=15)
        if not s:
            if debug: print(f'to_editor: wait_for valid scene returned None')
            return False
        
        scene_mode = s['scene_mode']
        if debug: print(f'to_editor: scene_mode={scene_mode}')
        
        if scene_mode == SCENE_EDITOR:
            return True
        if scene_mode == SCENE_PLAY:
            self.press('MINUS', 200)
            return self.wait_for(lambda s: s['scene_mode'] == SCENE_EDITOR, timeout=timeout) is not None
        if scene_mode == SCENE_TITLE:
            start_count = s['scene_change_count']
            if debug: print(f'to_editor: title, start_count={start_count}')
            
            # L+R to skip title animation, then A to enter
            self.hold('L+R', 2000)
            self.press('A', 500)
            
            # Wait for scene change (instant detection via counter)
            result = self.wait_for(
                lambda s: s['scene_change_count'] > start_count and s['scene_mode'] == SCENE_EDITOR,
                timeout=10
            )
            if debug: print(f'to_editor: wait result={result}')
            return result is not None
        if debug: print(f'to_editor: unknown scene_mode {scene_mode}')
        return False

    def to_play(self, timeout=15):
        """Navigate to play mode. Returns True on success."""
        sc = self.scene()
        if sc == 'play':
            s = self.status()
            if s and s['state'] not in DEATH_STATES:
                return True
        if sc != 'editor':
            if not self.to_editor():
                return False
        # From editor: clear focus, MINUS
        self.press('B', 100)
        time.sleep(0.3)
        self.press('MINUS', 200)
        return self.wait_for(lambda s: s['scene_mode'] == SCENE_PLAY, timeout=timeout) is not None

    def fresh(self, timeout=120):
        """Kill emulator, restart, navigate to play. Returns True on success."""
        tools_dir = Path(__file__).parent
        result = subprocess.run(
            ['python3', str(tools_dir / 'emu_session.py'), 'fresh', self.emu, '--no-gdb'],
            capture_output=True, text=True, timeout=timeout
        )
        return result.returncode == 0

    def screenshot(self, out_path='/mnt/c/temp/smm2_debug/capture.png'):
        """Take screenshot of emulator window."""
        tools_dir = Path(__file__).parent
        result = subprocess.run(
            ['python3', str(tools_dir / 'automate.py'), f'--{self.emu}', 'screenshot'],
            capture_output=True, text=True, timeout=10
        )
        return out_path if result.returncode == 0 else None

    # ── Quick Reset ──────────────────────────────────────────

    def reset(self, timeout=5):
        """Quick reset: play → editor → play. Much faster than reboot."""
        s = self.status()
        if not s or s['scene_mode'] != 5:
            return self.to_play(timeout)
        
        # play → editor
        self.press('MINUS', 200)
        if not self.wait_for(lambda s: s['scene_mode'] == 1, timeout=timeout):
            return False
        
        # editor → play
        self.press('B', 100)
        time.sleep(0.1)
        self.press('MINUS', 200)
        return self.wait_for(lambda s: s['scene_mode'] == 5, timeout=timeout) is not None

    # ── Display ─────────────────────────────────────────────

    def __repr__(self):
        s = self.status()
        if not s:
            age = self._status_age()
            if age is not None:
                return f"Game({self.emu}) [stale: {age:.0f}s old, game not running]"
            return f"Game({self.emu}) [no status file]"
        sc = self.scene()
        state_name = STATE_NAMES.get(s['state'], f"#{s['state']}")
        return (
            f"Game({self.emu}) scene={sc} state={state_name} "
            f"pos=({s['x']:.0f},{s['y']:.0f}) vel=({s['vx']:.1f},{s['vy']:.1f})"
        )


if __name__ == '__main__':
    g = Game('eden')
    print(repr(g))
    print(f"Scene: {g.scene()}")
    print(f"Alive: {g.alive()}")
