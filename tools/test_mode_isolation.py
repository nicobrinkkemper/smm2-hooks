#!/usr/bin/env python3
"""
Test script for mode isolation in status.bin.

Verifies that player data is only provided when scene_mode == 5 (play mode).
This prevents stale data from contaminating reads when switching between
editor and play modes.

Usage: python3 test_mode_isolation.py
"""

import sys
import time
from smm2 import Game

def test_mode_isolation():
    print("=" * 60)
    print("Mode Isolation Test")
    print("=" * 60)
    
    # Check if Eden is running
    g = Game('eden')
    
    print("\n[1] Checking initial state...")
    s = g.status()
    if s is None:
        print("ERROR: Could not read status.bin - is the game running?")
        return False
    
    print(f"    scene_mode: {s['scene_mode']} (1=editor, 5=play, 6=title)")
    print(f"    has_player: {s['has_player']}")
    print(f"    style: {s['style']}")
    
    # If in play mode, exit to editor first
    if s['scene_mode'] == 5:
        print("\n[2] Currently in play mode, exiting to editor...")
        g.press('MINUS')
        time.sleep(2)
        s = g.status()
    
    # Verify we're in editor
    print("\n[2] Verifying editor mode...")
    s = g.status()
    if s['scene_mode'] != 1:
        print(f"    WARNING: Expected scene_mode=1 (editor), got {s['scene_mode']}")
        if s['scene_mode'] == 6:
            print("    On title screen - need to enter Course Maker first")
            return False
    else:
        print(f"    OK: scene_mode=1 (editor)")
    
    # KEY TEST: In editor mode, has_player should be 0
    print("\n[3] Testing editor mode player data...")
    s = g.status()
    if s['has_player'] == 0:
        print("    OK: has_player=0 (no player data in editor)")
        print(f"    state={s['state']}, x={s['x']}, y={s['y']} (should all be 0)")
        if s['state'] == 0 and s['x'] == 0.0 and s['y'] == 0.0:
            print("    OK: Player fields are zeroed")
        else:
            print("    WARNING: Player fields not zeroed!")
    else:
        print(f"    FAIL: has_player={s['has_player']} (expected 0 in editor)")
        print(f"    Stale data: state={s['state']}, x={s['x']}, y={s['y']}")
        return False
    
    # Enter play mode
    print("\n[4] Entering play mode...")
    g.press('B')  # Clear any panel focus
    time.sleep(0.3)
    g.press('MINUS')  # Enter play
    time.sleep(2)
    
    # Verify play mode
    print("\n[5] Verifying play mode...")
    s = g.status()
    if s['scene_mode'] != 5:
        print(f"    FAIL: Expected scene_mode=5 (play), got {s['scene_mode']}")
        return False
    print(f"    OK: scene_mode=5 (play)")
    
    # KEY TEST: In play mode, has_player should be 1 with valid data
    print("\n[6] Testing play mode player data...")
    s = g.status()
    if s['has_player'] == 1:
        print("    OK: has_player=1")
        print(f"    state={s['state']}, x={s['x']:.1f}, y={s['y']:.1f}")
        print(f"    style={s['style']}, theme={s['theme']}")
        if s['x'] > 0 or s['y'] > 0:
            print("    OK: Player position is valid")
        else:
            print("    WARNING: Player position is (0,0) - might be at origin")
    else:
        print(f"    FAIL: has_player={s['has_player']} (expected 1 in play)")
        return False
    
    # Do a quick action to prove player is active
    print("\n[7] Testing player responsiveness...")
    start_x = s['x']
    g.press('RIGHT', ms=300)
    time.sleep(0.2)
    s = g.status()
    end_x = s['x']
    if end_x > start_x:
        print(f"    OK: Player moved ({start_x:.1f} -> {end_x:.1f})")
    else:
        print(f"    WARNING: Player didn't move (x={end_x:.1f})")
    
    # Exit play mode
    print("\n[8] Exiting play mode...")
    g.press('MINUS')
    time.sleep(2)
    
    # Verify back in editor
    print("\n[9] Verifying editor mode again...")
    s = g.status()
    if s['scene_mode'] != 1:
        print(f"    WARNING: Expected scene_mode=1, got {s['scene_mode']}")
    else:
        print(f"    OK: scene_mode=1 (editor)")
    
    # KEY TEST: After exiting play, player data should be cleared
    print("\n[10] Testing player data cleared after exit...")
    s = g.status()
    if s['has_player'] == 0:
        print("    OK: has_player=0 (player data cleared)")
        if s['state'] == 0 and s['x'] == 0.0 and s['y'] == 0.0:
            print("    OK: Player fields are zeroed")
        else:
            print(f"    WARNING: Fields not zeroed: state={s['state']}, x={s['x']}, y={s['y']}")
    else:
        print(f"    FAIL: has_player={s['has_player']} (stale data!)")
        print(f"    Stale: state={s['state']}, x={s['x']}, y={s['y']}")
        return False
    
    print("\n" + "=" * 60)
    print("TEST PASSED: Mode isolation working correctly")
    print("=" * 60)
    return True


if __name__ == "__main__":
    try:
        success = test_mode_isolation()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"\nERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
