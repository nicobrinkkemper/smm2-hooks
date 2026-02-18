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
    
    # Wait for frame >= 500 (title ready to accept L+R)
    while True:
        s = g.status()
        if s and s['frame'] >= 500:
            break
        time.sleep(POLL_MS / 1000)
    
    # L+R (1.5s) then A - single attempt, no retry
    g.hold('L+R', 1500)
    g.press('A', 200)
    
    s = wait_scene(g, 1, timeout=3)
    if not s:
        print("ERROR: No editor")
        return 1
    print(f"Editor in {time.time()-t0:.1f}s")
    
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
