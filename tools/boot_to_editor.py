#!/usr/bin/env python3
"""Boot game and navigate to editor/play/coursebot. Fully automated, rapid polling."""
import argparse
import subprocess
import time
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from smm2 import Game

POLL_MS = 50  # 50ms = 20Hz polling
DEFAULT_FRAME_THRESHOLD = 400  # ~6.7s - intro animation must fully complete

def wait_scene(g, target_mode, timeout=30):
    """Wait for scene_mode, polling every POLL_MS."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        s = g.status()
        if s and s['scene_mode'] == target_mode:
            return s
        time.sleep(POLL_MS / 1000)
    return None

def nav_to_coursebot_slot(g, slot, verbose=True):
    """Navigate from title to Coursebot and load a specific slot.
    
    Title menu: L+R (skip), Right (to Play), A
    Play menu: Down twice (to Coursebot), A
    Coursebot: 4 slots per row, navigate to slot, A (details), A (play)
    """
    def step(msg):
        if verbose:
            s = g.status()
            print(f"  {msg} (scene={s['scene_mode'] if s else '?'})")
    
    # Title -> Play menu (L+R brings up menu, Right to Play, A to select)
    step("L+R to open menu")
    g.hold('L+R', 1500)
    time.sleep(0.3)
    step("RIGHT to Play")
    g.press('RIGHT', 150)
    time.sleep(0.2)
    step("A to select Play")
    g.press('A', 200)
    time.sleep(0.5)
    
    # Play menu -> Coursebot (down 3x from top)
    step("DOWN 1")
    g.press('DOWN', 150)
    time.sleep(0.2)
    step("DOWN 2")
    g.press('DOWN', 150)
    time.sleep(0.2)
    step("DOWN 3 to Coursebot")
    g.press('DOWN', 150)
    time.sleep(0.2)
    step("A to enter Coursebot")
    g.press('A', 200)
    step("Waiting for Coursebot to load...")
    time.sleep(5.0)  # Coursebot needs time to load
    
    # Navigate to slot (4 per row)
    row = slot // 4
    col = slot % 4
    if row > 0 or col > 0:
        step(f"Navigate to slot {slot} (row={row}, col={col})")
        for i in range(row):
            g.press('DOWN', 150)
            time.sleep(0.15)
        for i in range(col):
            g.press('RIGHT', 150)
            time.sleep(0.15)
        time.sleep(0.2)
    
    # Simple double-tap: A (open details), wait for slide, A (play)
    step("A to open details")
    g.press('A', 200)
    time.sleep(1.0)  # Wait for slide animation
    step("A to Play")
    g.press('A', 200)

def main():
    parser = argparse.ArgumentParser(description='Boot SMM2 to editor/play/coursebot')
    parser.add_argument('emu', nargs='?', default='eden', choices=['eden', 'ryujinx'])
    parser.add_argument('--play', action='store_true', help='Navigate to editor play mode')
    parser.add_argument('--slot', type=int, default=None, metavar='N',
                        help='Load course from Coursebot slot N (0-99)')
    parser.add_argument('--frame', type=int, default=DEFAULT_FRAME_THRESHOLD,
                        help=f'Frame threshold before input (default: {DEFAULT_FRAME_THRESHOLD})')
    args = parser.parse_args()
    
    emu = args.emu
    tools = Path(__file__).parent
    
    # Kill & launch with retry
    subprocess.run(['python3', 'emu_session.py', 'kill', emu], capture_output=True, cwd=tools)
    time.sleep(0.5)
    
    g = Game(emu)
    t0 = time.time()
    
    for launch_attempt in range(2):
        subprocess.run(['python3', 'emu_session.py', 'launch', emu], capture_output=True, cwd=tools)
        s = wait_scene(g, 6, timeout=20)
        if s:
            break
        # Launch failed, kill and retry
        subprocess.run(['python3', 'emu_session.py', 'kill', emu], capture_output=True, cwd=tools)
        time.sleep(1)
    else:
        print("ERROR: No title")
        return 1
    print(f"Title in {time.time()-t0:.1f}s")
    
    # Wait for frame threshold
    while True:
        s = g.status()
        if s and s['frame'] >= args.frame:
            break
        time.sleep(POLL_MS / 1000)
    print(f"Input at frame {s['frame']}")
    
    if args.slot is not None:
        # Coursebot path: Title -> Play menu -> Coursebot -> slot N -> Play
        nav_to_coursebot_slot(g, args.slot)
        # Monitor scene during load (scene 5 = editor play, scene 7 = coursebot play)
        print("  Waiting for play mode...")
        for i in range(120):  # 60 seconds
            s = g.status()
            if s:
                if i % 10 == 0:  # Print every 5 seconds
                    print(f"    scene={s['scene_mode']}, frame={s['frame']}")
                if s['scene_mode'] in (5, 7):  # Editor play or Coursebot play
                    break
            time.sleep(0.5)
        if not s or s['scene_mode'] not in (5, 7):
            print(f"ERROR: No play (coursebot), final scene={s['scene_mode'] if s else '?'}")
            return 1
        print(f"Playing slot {args.slot} in {time.time()-t0:.1f}s")
    else:
        # Editor path: Title -> Course Maker
        g.hold('L+R', 1500)
        g.press('A', 200)
        
        s = wait_scene(g, 1, timeout=3)
        if not s:
            print("ERROR: No editor")
            return 1
        print(f"Editor in {time.time()-t0:.1f}s")
        
        if args.play:
            # Hold B+MINUS to enter play mode (MINUS needs ~1s hold)
            g.hold('B', 200)
            g.hold('MINUS', 1000)  # Hold for 1 second
            s = wait_scene(g, 5, timeout=10)
            if not s:
                print("ERROR: No play")
                return 1
    
    print(f"OK: scene_mode={s['scene_mode']}")
    return 0

if __name__ == '__main__':
    sys.exit(main())
