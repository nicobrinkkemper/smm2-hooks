#!/usr/bin/env python3
"""Boot game and navigate to editor/play. Fully automated.

Usage:
    python3 boot_to_editor.py [eden|ryujinx] [--play]
"""
import subprocess
import time
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from smm2 import Game

def main():
    emu = 'eden'
    target = 'editor'
    
    for arg in sys.argv[1:]:
        if arg in ('eden', 'ryujinx'):
            emu = arg
        elif arg == '--play':
            target = 'play'
    
    tools = Path(__file__).parent
    
    # Kill existing
    subprocess.run(['python3', 'emu_session.py', 'kill', emu], 
                   capture_output=True, cwd=tools)
    time.sleep(1)
    
    # Launch
    print(f"Launching {emu}...")
    subprocess.run(['python3', 'emu_session.py', 'launch', emu],
                   capture_output=True, cwd=tools)
    
    # Wait for hooks to initialize
    g = Game(emu)
    print("Waiting for game...")
    for i in range(60):
        s = g.status()
        if s and s['frame'] > 100:
            break
        time.sleep(1)
    else:
        print("ERROR: Game didn't start")
        return 1
    
    # Navigate to editor (handles title screen automatically)
    print(f"Navigating to {target}...")
    if not g.to_editor(timeout=45):
        print("ERROR: Failed to reach editor")
        return 1
    
    if target == 'play':
        if not g.to_play():
            print("ERROR: Failed to enter play")
            return 1
    
    print(f"OK: {g.scene()}")
    return 0

if __name__ == '__main__':
    sys.exit(main())
