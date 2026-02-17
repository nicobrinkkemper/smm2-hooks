#!/usr/bin/env python3
"""Boot game and navigate to editor/play. Fully automated, rapid polling."""
import subprocess
import time
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from smm2 import Game

POLL_MS = 50  # 50ms = 20Hz polling

def wait_scene(g, target_mode, timeout=30):
    """Wait for scene_mode, polling every POLL_MS."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        s = g.status()
        if s and s['scene_mode'] == target_mode:
            return s
        time.sleep(POLL_MS / 1000)
    return None

def main():
    emu = sys.argv[1] if len(sys.argv) > 1 and sys.argv[1] in ('eden', 'ryujinx') else 'eden'
    target = 'play' if '--play' in sys.argv else 'editor'
    tools = Path(__file__).parent
    
    # Kill & launch
    subprocess.run(['python3', 'emu_session.py', 'kill', emu], capture_output=True, cwd=tools)
    time.sleep(0.5)
    subprocess.run(['python3', 'emu_session.py', 'launch', emu], capture_output=True, cwd=tools)
    
    g = Game(emu)
    
    # Wait for title (scene_mode=6) with enough frames loaded
    print("Waiting for title...")
    deadline = time.time() + 30
    while time.time() < deadline:
        s = g.status()
        if s and s['scene_mode'] == 6 and s['frame'] > 1000:
            break
        time.sleep(POLL_MS / 1000)
    else:
        print("ERROR: No title screen")
        return 1
    print(f"At title, frame={s['frame']}")
    
    # L+R to skip title animation, then A to enter
    print("L+R skip...")
    g.hold('L+R', 1500)
    print("Pressing A...")
    g.press('A', 300)
    
    # Wait for editor (scene_mode=1)
    print("Waiting for editor...")
    s = wait_scene(g, 1, timeout=10)
    if not s:
        # Debug: what scene are we at?
        s2 = g.status()
        print(f"ERROR: No editor (scene_mode={s2['scene_mode'] if s2 else '?'})")
        return 1
    print(f"In editor, frame={s['frame']}")
    
    if target == 'play':
        g.press('B', 100)
        time.sleep(0.1)
        g.press('MINUS', 200)
        s = wait_scene(g, 5, timeout=10)
        if not s:
            print("ERROR: No play")
            return 1
    
    print(f"OK: scene_mode={s['scene_mode']}")
    return 0

if __name__ == '__main__':
    sys.exit(main())
