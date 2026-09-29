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
TITLE_READY_FRAME = 960 + 300   # cold boot: the title is up at ~960 and takes input ~5 s later
SCENE_COURSEBOT = 7 # Coursebot play (game-only, no editing)
COURSEBOT_SLOTS = 180   # save slots the game knows; save.dat has one record per slot

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

    # Ground movement from the decomp (smm2-decomp src-sim/game/player/PlayerConst.h):
    # walking accelerates 0.1 a frame up to 0.5 and 0.03 a frame up to 1.5;
    # released on the ground it slows by a flat 0.05 a frame.
    WALK_ACCEL = ((0.5, 0.1), (1.5, 0.03))
    GROUND_DECEL = 0.05
    # Frames between reading the position and the game acting on the input
    # written after it: 4 to 5 measured through status.bin from WSL, and it
    # varies, so the approach stops a little short and taps finish forward.
    INPUT_DELAY_FRAMES = 7

    @classmethod
    def glide(cls, speed):
        """Distance the player still covers after releasing at `speed` on flat ground."""
        dist = 0.0
        while speed > 1e-6:
            speed = max(0.0, speed - cls.GROUND_DECEL)
            dist += speed
        return dist

    @classmethod
    def tap_distance(cls, frames):
        """Distance a walk held for `frames` frames from standing covers, glide included."""
        speed = dist = 0.0
        for _ in range(frames):
            # "less or same": at exactly 0.5 the game still adds 0.1 (0.5 -> 0.6)
            accel = next((a for limit, a in cls.WALK_ACCEL if speed <= limit + 1e-6), 0.0)
            speed = min(1.5, speed + accel)
            dist += speed
        return dist + cls.glide(speed)

    def _wait_frames(self, n, timeout=2.0):
        """Wait until status.bin's frame counter has advanced `n` frames."""
        s = self.status()
        start, deadline = (s['frame'] if s else 0), time.time() + timeout
        while time.time() < deadline:
            s = self.status()
            if s and s['frame'] - start >= n:
                return s
            time.sleep(0.003)
        return self.status()

    def _settle(self, timeout=3.0):
        """Wait until the player stands still; returns the status."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            s = self._wait_frames(1)
            if s and abs(s['vx']) < 1e-4:
                return s
        return self.status()

    def walk_to(self, target_x, tolerance=1.0, timeout=20, use_analog=False):
        """Walk the player to `target_x` on flat ground, within `tolerance` units.

        Reads the position every frame and walks toward the target, letting go
        when the glide at the current speed (the game's 0.05 a frame ground
        deceleration, plus the input delay) would carry the player there; then
        closes the rest with taps held for a counted number of frames, the
        longest that does not pass the target. It does not run and does not
        walk past the target to come back. Slopes, belts and ice move the
        player differently; this is for flat ground.
        Returns True when the player stands within `tolerance`.
        """
        deadline = time.time() + timeout

        def hold(direction):
            if use_analog:
                self._write_input(0, 32767 * direction, 0)
            else:
                self._write_input(BTN['RIGHT'] if direction > 0 else BTN['LEFT'])

        while time.time() < deadline:
            s = self.status()
            if not s or not s['has_player'] or s['state'] in DEATH_STATES:
                self.release()
                return False
            dx = target_x - s['x']
            direction = 1 if dx > 0 else -1
            speed = abs(s['vx'])
            if speed > 1e-4:
                # Moving: hold on while the glide still falls short.
                toward = s['vx'] * direction > 0
                if toward and speed * self.INPUT_DELAY_FRAMES + self.glide(speed) < abs(dx):
                    hold(direction)
                else:
                    self.release()
                self._wait_frames(1)
                continue
            if abs(dx) <= tolerance:
                self.release()
                return True
            # Standing: the longest counted tap that stays short of the target,
            # at least one frame.
            # Aimed half a unit short: the tap's length varies a frame with the delay.
            frames = 1
            while frames < 90 and self.tap_distance(frames + 1) <= abs(dx) - 0.5:
                frames += 1
            hold(direction)
            self._wait_frames(frames)
            self.release()
            self._settle()

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

    def start_over(self, timeout=15):
        """Pause, Start Over: play the course again from its start.

        The game reloads the course for it: status.bin's scene_change_count
        goes up (by two) and the player is gone for about 1.5 s, so this
        waits for the count to have moved and a player to exist again. The
        player is still there for a few frames after the press, which is why
        a wait on the player alone returns before the restart.
        """
        s = self.status()
        if not s:
            return False
        before = s['scene_change_count']
        self._press('PLUS', focus=False)
        self.focus('Start Over')
        self._press('A')
        return self.wait_for(
            lambda s: s['scene_change_count'] > before and s['has_player'] and s['state'] not in DEATH_STATES,
            timeout=timeout) is not None

    def _coursebot_home(self, max_rows=24, gap=0.5, scroll_gap=1.2):
        """Put the Coursebot cursor on slot 0.

        The grid keeps its cursor between visits and nothing exposes it, so
        clamp instead: LEFT to column 0, UP past row 0 onto the "My Courses"
        tab (extra UPs stay there; never press LEFT/RIGHT on the tab, that
        switches tabs), then DOWN back into the grid, which lands on slot 0.
        The grid is 4 wide and an UP from a scrolled row animates the
        scroll, during which a press is dropped (a home from slot 70 with 16
        quick UPs stopped short and the boot played slot 13, 2026-09-15), so
        the UPs are one per row with a scroll's worth of spacing; 24 rows
        cover every test level (slots below 96).
        """
        for _ in range(3):
            self.press('LEFT', 100)
            time.sleep(gap)
        for _ in range(max_rows):
            self.press('UP', 100)
            time.sleep(scroll_gap)
        self.press('DOWN', 100)
        time.sleep(gap)

    def to_coursebot_play(self, slot=0, timeout=30, from_start=True):
        """Navigate: editor -> Coursebot -> select slot -> Play.

        Args:
            slot: course slot (0-based, grid is 4 wide, slot order)
            from_start: if the flow lands in the editor instead, hold MINUS
                (play from the course start) rather than tap it (play in place)

        A registered slot's detail screen opens with the cursor on "Make"
        (seen on every installed course, 2026-09-05), and A there opens the
        editor. The screen is a grid: Make, Upload, then Name / Description /
        delete, then Play Together / Play; UP from Make climbs to the tab bar
        and stays there, so the tab is the home: UP x3, DOWN to Make, DOWN,
        DOWN, RIGHT, DOWN lands on Play and A starts Coursebot play
        (scene_mode 7, game-only). An empty slot only offers "Make New
        Course", which opens the editor (scene_mode 1) with a default course;
        MINUS then starts editor test-play (scene_mode 5). Check scene_mode
        afterwards to know which one you got.
        """
        if not isinstance(slot, int) or not 0 <= slot < COURSEBOT_SLOTS:
            raise ValueError(f"slot {slot!r} is not a Coursebot slot (0..{COURSEBOT_SLOTS - 1})")
        # Already on the Coursebot grid (status.bin says scene 0 there, so
        # to_editor cannot start from it): only the UI probe can tell.
        now = self.ui()
        on_grid = now.get('status') == 'observed' and now.get('course_slot') is not None
        if on_grid:
            start_count = self._coursebot_play_observed(slot)
        elif not self.to_editor():
            return False

        if not on_grid and self._ui_observed():
            # Editor -> main menu -> Coursebot, each step on the game's word.
            # The main menu may be open already (status.bin still says editor).
            if not any(s.startswith('main_menu:') for s in self.ui().get('screens') or []):
                self.press('B', 100)  # drop whatever the editor has in hand
                self.wait_until(focus=False, what='the editor')
                self._press('PLUS', focus=False)
            # The Coursebot button draws its label only while focused, so it
            # cannot be steered to by text; it sits right of Course Maker.
            v = self.wait_until(what='the main menu')
            if v.get('focus') != '/L_LclBtn_00':
                v = self._press('RIGHT')
            if v.get('focus') != '/L_LclBtn_00':
                raise RuntimeError(f'main menu: RIGHT did not focus Coursebot: {v}')
            self._press('A')
            start_count = self._coursebot_play_observed(slot)
        elif not on_grid:
            # Clear any focus
            self.press('B', 100)
            time.sleep(0.3)

            # PLUS -> Main Menu
            self.press('PLUS', 150)
            time.sleep(1.5)  # wait for menu animation

            # RIGHT -> Coursebot icon
            self.press('RIGHT', 100)
            time.sleep(0.3)

            # A -> Enter Coursebot
            self.press('A', 100)
            time.sleep(3.0)  # wait for coursebot to load courses

            # The grid remembers its cursor across visits, so home it first.
            self._coursebot_home()

            # Navigate to slot. Presses during the scroll animation are dropped,
            # hence the generous spacing.
            row = slot // 4
            col = slot % 4
            for _ in range(col):
                self.press('RIGHT', 100)
                time.sleep(0.5)
            for i in range(row):
                self.press('DOWN', 100)
                # rows 0..3 are on screen; from row 3 on every DOWN scrolls the
                # list and a press during that animation is dropped (slot 19
                # landed on 15, 2026-09-09), so give the scroll time to finish
                time.sleep(1.6 if i >= 2 else 0.5)

            # A -> course details; home the cursor on the tab bar, walk it to
            # Play, A -> go. On an empty slot the same presses land on "Make New
            # Course" (the only button), which the editor fallback below handles.
            s = self.status()
            start_count = s['scene_change_count'] if s else 0
            self.press('A', 100)
            time.sleep(2.0)
            for button in ('UP', 'UP', 'UP', 'DOWN', 'DOWN', 'DOWN', 'RIGHT', 'DOWN'):
                self.press(button, 100)
                time.sleep(0.6)
            self.press('A', 100)

        s = self.wait_for(
            lambda s: (s['scene_mode'] == SCENE_COURSEBOT and (s['has_player'] or s['state'] > 0))
            or (s['scene_mode'] == SCENE_EDITOR and s['scene_change_count'] > start_count),
            timeout=timeout
        )
        if not s:
            return False
        if s['scene_mode'] == SCENE_COURSEBOT:
            return True

        # Editor: MINUS starts test-play once the editor accepts input, and
        # how long that takes varies, so retry a few times.
        for _ in range(4):
            time.sleep(2.0)
            self.press('MINUS', 1500 if from_start else 150)
            if self.wait_for(lambda s: s['scene_mode'] == SCENE_PLAY and s['has_player'], timeout=6):
                return True
        return False

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

            # A cold boot reaches the title at frame ~960 (the count is
            # deterministic across launches) and drops inputs for the first
            # seconds it is up; every first game_boot after a launch used to
            # fail on that and the second call succeed. Let the title settle
            # (5 s of frames) before pressing, and press twice if the first
            # try changes nothing.
            if start_count <= 1 and s['frame'] < TITLE_READY_FRAME:
                self.wait_for(lambda s: s['frame'] >= TITLE_READY_FRAME, timeout=10)
            for attempt in range(2):
                # L+R to skip title animation, then A to enter
                self.hold('L+R', 2000)
                self.press('A', 500)

                # Wait for scene change (instant detection via counter)
                result = self.wait_for(
                    lambda s: s['scene_change_count'] > start_count and s['scene_mode'] == SCENE_EDITOR,
                    timeout=10
                )
                if debug: print(f'to_editor: attempt {attempt} wait result={result}')
                if result is not None:
                    return True
            return False
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

    # -- menus, driven by what the game draws (tools/ui_probe.py) -----------

    def ui(self, full=False):
        """The menus now: active texts, focused control, ready, Coursebot course_slot.

        Needs sd:/smm2-hooks/ui-probe.txt = 'capture' at boot (docs/ui-probe.md).
        full=True returns ui_probe.screen(): every visible row with its position
        (x right, y up) and layer.
        """
        import ui_probe
        path = Path(self.sd) / 'ui-screen.txt'
        if not full:
            return ui_probe.observe(path)
        sample = ui_probe.read(path).get('sample')
        return ui_probe.screen(sample) if sample else None

    def wait_until(self, condition=lambda v: True, what='the menus to settle', focus=True,
                   after=None, hang=30.0):
        """Wait for the game, not the clock: until the menus are ready and `condition` holds.

        Ready is the game's own screen state (ui_probe.menu_state): a screen in
        a Disp* state and none appearing, disappearing, opening, closing,
        leaving or loading. focus=True also waits for the game to focus a
        control and switch that control's input on. `after` skips snapshots up to that game tick. `hang` only
        guards against a game that never gets there; it raises with the
        screens and transitions it was stuck in.
        """
        deadline = time.time() + hang
        while True:
            v = self.ui()
            # A stale snapshot is an old screen (the game is gone or the mod did not load).
            fresh = v.get('status') == 'observed' and (after is None or (v.get('tick') or 0) > after)
            takes_input = v.get('focus') and v.get('input') is not False
            if fresh and v.get('ready') and (not focus or takes_input) and condition(v):
                return v
            if time.time() >= deadline:
                raise RuntimeError(f'waited {hang:.0f} s for {what}: screens {v.get("screens")}, '
                                   f'transitions {v.get("transitions")}, focus {v.get("focused")!r}')
            time.sleep(0.05)

    # Frames of settled menus after a press with nothing changed: the game ignored it.
    IGNORED_AFTER_FRAMES = 30

    def _press(self, button, focus=True):
        """Press once the menus take input, and return the game's answer.

        The answer is the first settled snapshot after the game read the button
        that shows the focus or the slot moved, or, when nothing moves, the
        one IGNORED_AFTER_FRAMES game frames after that read: the game ignored
        the press. (Injected input reaches the game some frames after it is
        written; the mod reports the last frame the game read a button held.)
        """
        before = self.wait_until(focus=focus, what=f'input before {button}')
        self.press(button, 100)
        key = lambda v: (v.get('focus'), v.get('course_slot'))
        seen = lambda v: v.get('buttons_tick', 0) > before['tick']
        # The answer needs no focus: a press that closes the menu (Start Over,
        # a dialog's No) leaves nothing focused, and that is the answer.
        return self.wait_until(
            lambda v: seen(v) and (key(v) != key(before) or v['tick'] >= v['buttons_tick'] + self.IGNORED_AFTER_FRAMES),
            focus=False, after=before['tick'], what=f'the game to answer {button}')

    def focus(self, text, max_presses=12):
        """Move the menu focus onto the active control labelled `text`.

        Steps toward the target's drawn position, one press at a time, and
        checks the game's focus after each; a press the game ignored (a
        button still animating its last focus change does) is pressed again.
        Returns the final ui() view, or raises when the label is not on the
        active layer, is not unique, or is not reached within max_presses.
        """
        for _ in range(max_presses):
            view = self.ui(full=True)
            if view is None:
                raise RuntimeError(f'no UI snapshot: {self.ui()}')
            if not view['focused']:
                # A freshly opened menu such as the pause menu focuses
                # nothing: the game makes no focus call until the first
                # direction press, which lands on the menu's first control.
                # That press counts once the screen has switched its input on.
                self.wait_until(lambda v: v.get('screen_input'), focus=False, what='the menu to take input')
                self._press('DOWN', focus=False)
                continue
            if text in (view['focused']['text'], view['focused']['readable']):
                return self.ui()
            targets = [r for r in view['active'] if text in (r['text'], r['readable'])]
            if len(targets) != 1:
                raise RuntimeError(f'{text!r} is on the active layer {len(targets)} times: {[r["text"] for r in view["active"]]}')
            dx = targets[0]['x'] - view['focused']['x']
            dy = targets[0]['y'] - view['focused']['y']
            self._press(('RIGHT' if dx > 0 else 'LEFT') if abs(dx) > abs(dy) else ('UP' if dy > 0 else 'DOWN'))
        raise RuntimeError(f'focus did not reach {text!r} in {max_presses} presses: {self.ui()}')

    def _ui_observed(self, timeout=5.0):
        """True when the UI probe is writing fresh snapshots (the mod read ui-probe.txt at boot)."""
        deadline = time.time() + timeout
        while True:
            if self.ui().get('status') == 'observed':
                return True
            if time.time() >= deadline:
                return False
            time.sleep(0.25)

    def _coursebot_play_observed(self, slot):
        """Grid -> slot -> details -> Play by the game's own focus; returns the scene count before A."""
        self.select_slot(slot)
        s = self.status()
        start_count = s['scene_change_count'] if s else 0
        self.press('A', 100)
        # A registered slot's details offer Play; an empty one only "Make New Course".
        v = self.wait_until(lambda v: 'Play' in (v.get('texts') or [])
                            or any(t.startswith('Make New') for t in v.get('texts') or []),
                            what='the course details')
        self.focus('Play' if 'Play' in v['texts'] else next(t for t in v['texts'] if t.startswith('Make New')))
        self.wait_until(what='input before A')
        self.press('A', 100)
        return start_count

    def select_slot(self, slot, max_presses=60):
        """On the Coursebot grid, move the focus to course `slot` (4 per row).

        Waits for the grid itself: its courses load (the loader machines
        reach LoadEnd) and the game focuses a tile, which reports the slot the
        game bound to it. Each move waits for the game's answer.
        """
        if not isinstance(slot, int) or not 0 <= slot < COURSEBOT_SLOTS:
            raise ValueError(f'slot {slot!r} is not a Coursebot slot (0..{COURSEBOT_SLOTS - 1})')
        v = self.wait_until(lambda v: v.get('course_slot') is not None, what='the Coursebot grid')
        for _ in range(max_presses):
            cur = v.get('course_slot')
            if cur is None:
                raise RuntimeError(f'the Coursebot grid lost focus: {v}')
            if cur == slot:
                return v
            if cur % 4 != slot % 4:
                button = 'RIGHT' if slot % 4 > cur % 4 else 'LEFT'
            else:
                button = 'DOWN' if slot > cur else 'UP'
            v = self._press(button)
        raise RuntimeError(f'slot {slot} not reached in {max_presses} presses')

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
