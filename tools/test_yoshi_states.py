#!/usr/bin/env python3
"""Test Yoshi state style-conditional behavior.

Based on Possamodder's analysis (smm2-decomp PR #25):
- SMW (style==2) should use state 104 (YoshiJumpWorld)
- All other styles should use state 103 (YoshiJumpWii)

Prerequisites:
- Eden running with smm2-hooks deployed
- Level with Yoshi placed
- Navigate to play mode, mount Yoshi, then run this script

Usage:
    python3 tools/test_yoshi_states.py
    
    # With manual mode (prompts for actions):
    python3 tools/test_yoshi_states.py --manual
"""

import sys
import time
from smm2 import Game, STATE_NAMES, STYLE_NAMES, STYLE_SMW

# Expected Yoshi jump states by style
YOSHI_JUMP_WII = 103    # 0x67 — all styles except SMW  
YOSHI_JUMP_WORLD = 104  # 0x68 — SMW only


def main():
    manual = '--manual' in sys.argv
    
    g = Game('eden')
    print(f"Connecting to Eden: {repr(g)}")
    
    if not g.status():
        print("\n❌ Game not running or status stale. Start Eden with hooks first.")
        return 1
    
    s = g.status()
    style = s['style']
    style_name = STYLE_NAMES.get(style, f'Unknown({style})')
    expected_state = YOSHI_JUMP_WORLD if style == STYLE_SMW else YOSHI_JUMP_WII
    expected_name = STATE_NAMES.get(expected_state, f'#{expected_state}')
    
    print(f"\n📊 Current game style: {style_name} (id={style})")
    print(f"   Expected Yoshi jump state: {expected_state} ({expected_name})")
    
    if manual:
        input("\n▶ Mount Yoshi and press Enter when ready...")
        input("▶ Jump while on Yoshi and press Enter immediately...")
    else:
        print("\n⏳ Monitoring for Yoshi jump states...")
        print("   Mount Yoshi and jump to trigger detection.")
        print("   Press Ctrl-C to stop.\n")
    
    seen_states = set()
    yoshi_states_seen = []
    
    try:
        while True:
            s = g.status()
            if not s:
                print("⚠ Lost connection to game")
                break
                
            state = s['state']
            
            # Track all states we see
            if state not in seen_states:
                seen_states.add(state)
                state_name = STATE_NAMES.get(state, f'#{state}')
                
                # Highlight Yoshi states
                if state in (YOSHI_JUMP_WII, YOSHI_JUMP_WORLD):
                    yoshi_states_seen.append(state)
                    is_expected = state == expected_state
                    status = "✅ CORRECT" if is_expected else "❌ UNEXPECTED"
                    print(f"🦖 YOSHI STATE: {state} ({state_name}) — {status}")
                    
                    if not is_expected:
                        print(f"   Style {style_name} should use {expected_state}, got {state}!")
                else:
                    print(f"   State: {state} ({state_name})")
            
            if manual and yoshi_states_seen:
                break
                
            time.sleep(0.05)  # 50ms poll
            
    except KeyboardInterrupt:
        print("\n")
    
    # Summary
    print("\n" + "="*50)
    print("SUMMARY")
    print("="*50)
    print(f"Style: {style_name}")
    print(f"Expected Yoshi state: {expected_state} ({expected_name})")
    print(f"Yoshi states seen: {yoshi_states_seen if yoshi_states_seen else 'None'}")
    
    if yoshi_states_seen:
        all_correct = all(s == expected_state for s in yoshi_states_seen)
        if all_correct:
            print("\n✅ TEST PASSED: Yoshi states match expected for this style")
            return 0
        else:
            print("\n❌ TEST FAILED: Unexpected Yoshi states detected")
            return 1
    else:
        print("\n⚠ No Yoshi states detected. Did you mount and jump?")
        return 2


if __name__ == '__main__':
    sys.exit(main())
