#!/usr/bin/env python3
"""verify_docs.py — Verify unverified claims in RE docs using automation.

Runs through different game styles and states, logging what we find
and comparing against documented values.

Usage:
    python3 verify_docs.py --style SMB1    # test specific style
    python3 verify_docs.py --all           # test all styles
    python3 verify_docs.py --fields        # verify field offsets
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path
from datetime import datetime

# Add tools dir to path
sys.path.insert(0, str(Path(__file__).parent))
from smm2 import Game, STYLE_NAMES, STATE_NAMES

# Documented game style values (from player-field-map.md)
# Says "only SMB1=5 confirmed" but smm2.py says 0-4
# Need to verify which is correct
DOC_STYLES = {
    'SMB1': 5,   # documented as "5 = SMB1 (confirmed)" in player-field-map.md
    'SMB3': None,  # TODO
    'SMW': None,
    'NSMBU': None,
    '3DW': None,
}

# smm2.py says these values
CODE_STYLES = {
    'SMB1': 0,
    'SMB3': 1,
    'SMW': 2,
    'NSMBU': 3,
    '3DW': 4,
}

# States we expect to see in each style
EXPECTED_STATES = {
    'SMB1': [1, 2, 3, 4, 5],  # walk, fall, jump, land, crouch
    'SMB3': [1, 2, 3, 4, 5, 90, 91, 92, 93],  # + shoe states
    'SMW': [1, 2, 3, 4, 5, 103, 104],  # + yoshi states (104 = SMW only?)
    'NSMBU': [1, 2, 3, 4, 5],
    '3DW': [1, 2, 3, 4, 5, 13, 14, 19, 20, 23],  # + roll, longjump, hipattack, wallslide
}


def verify_game_style(g: Game):
    """Verify what game_style value the game reports."""
    status = g.status()
    if not status:
        return None, "Could not read status"
    
    game_style = status.get('game_style')
    scene = status.get('scene_mode')
    
    return {
        'game_style': game_style,
        'game_style_name': STYLE_NAMES.get(game_style, f'UNKNOWN({game_style})'),
        'scene_mode': scene,
        'has_player': status.get('has_player'),
    }


def collect_states(g: Game, duration_sec=30):
    """Collect all states seen during play."""
    states_seen = set()
    state_counts = {}
    physics_samples = []
    
    print(f"Collecting states for {duration_sec}s...")
    print("Press buttons to trigger different states!")
    
    start = time.time()
    last_state = None
    
    while time.time() - start < duration_sec:
        status = g.status()
        if not status or not status.get('has_player'):
            time.sleep(0.1)
            continue
        
        state = status.get('player_state')
        if state is not None:
            states_seen.add(state)
            state_counts[state] = state_counts.get(state, 0) + 1
            
            if state != last_state:
                name = STATE_NAMES.get(state, f'State{state}')
                print(f"  → {state:3d} ({name})")
                last_state = state
        
        # Sample physics occasionally
        if len(physics_samples) < 100:
            physics_samples.append({
                'state': state,
                'vel_x': status.get('vel_x'),
                'vel_y': status.get('vel_y'),
                'gravity': status.get('gravity'),
                'pos_x': status.get('pos_x'),
                'pos_y': status.get('pos_y'),
            })
        
        time.sleep(0.05)
    
    return {
        'states_seen': sorted(states_seen),
        'state_counts': state_counts,
        'physics_samples': physics_samples,
    }


def auto_trigger_states(g: Game):
    """Automatically trigger common states via inputs."""
    print("\nAuto-triggering states...")
    
    states_log = []
    
    def log_state():
        s = g.status()
        if s and s.get('has_player'):
            state = s.get('player_state')
            states_log.append(state)
            return state
        return None
    
    # Walk right
    print("  Walking right...")
    g.hold('RIGHT', 1000)
    log_state()
    
    # Jump
    print("  Jumping...")
    g.press('B')
    time.sleep(0.1)
    log_state()  # should be jump
    time.sleep(0.5)
    log_state()  # should be fall or land
    
    # Crouch
    print("  Crouching...")
    g.press('DOWN')
    time.sleep(0.2)
    log_state()
    
    # Run + jump (long jump in 3DW)
    print("  Run + jump...")
    g.hold('Y', 500)  # start running
    g.press('B')
    time.sleep(0.3)
    log_state()
    time.sleep(0.5)
    
    # Ground pound / hip attack (3DW)
    print("  Jump + down (ground pound)...")
    g.press('B')
    time.sleep(0.2)
    g.press('DOWN')
    time.sleep(0.3)
    log_state()
    
    return list(set(states_log))


def verify_style(g: Game, style_name: str, results: dict):
    """Verify a single game style."""
    print(f"\n{'='*60}")
    print(f"Verifying {style_name}")
    print('='*60)
    
    # Get current game style from status
    style_info = verify_game_style(g)
    if not style_info:
        print("ERROR: Could not get game status")
        return
    
    print(f"Game reports: style={style_info['game_style']} ({style_info['game_style_name']})")
    print(f"Scene mode: {style_info['scene_mode']}, has_player: {style_info['has_player']}")
    
    # Compare against docs
    doc_value = DOC_STYLES.get(style_name)
    code_value = CODE_STYLES.get(style_name)
    actual_value = style_info['game_style']
    
    print(f"\nStyle value comparison:")
    print(f"  Documented (player-field-map.md): {doc_value}")
    print(f"  In code (smm2.py):                {code_value}")
    print(f"  Actual runtime:                   {actual_value}")
    
    if doc_value is not None and actual_value != doc_value:
        print(f"  ⚠️  MISMATCH with docs!")
    if actual_value == code_value:
        print(f"  ✅ Matches code")
    
    results[style_name] = {
        'style_value': actual_value,
        'doc_value': doc_value,
        'code_value': code_value,
        'matches_code': actual_value == code_value,
        'matches_doc': actual_value == doc_value if doc_value else None,
    }
    
    # Auto-trigger some states
    if style_info['has_player']:
        triggered = auto_trigger_states(g)
        print(f"\nStates triggered: {triggered}")
        results[style_name]['triggered_states'] = triggered
        
        # Collect more states passively
        collected = collect_states(g, duration_sec=15)
        results[style_name]['states_seen'] = collected['states_seen']
        results[style_name]['state_counts'] = collected['state_counts']
        
        print(f"\nAll states seen: {collected['states_seen']}")
        
        # Check expected states
        expected = EXPECTED_STATES.get(style_name, [])
        missing = set(expected) - set(collected['states_seen'])
        if missing:
            print(f"⚠️  Expected but not seen: {sorted(missing)}")
        
        unexpected = set(collected['states_seen']) - set(expected) - {43}  # 43=EditorIdle is common
        if unexpected:
            print(f"ℹ️  Additional states seen: {sorted(unexpected)}")


def main():
    parser = argparse.ArgumentParser(description='Verify RE doc claims')
    parser.add_argument('--style', type=str, help='Test specific style (SMB1/SMB3/SMW/NSMBU/3DW)')
    parser.add_argument('--all', action='store_true', help='Test all styles')
    parser.add_argument('--fields', action='store_true', help='Verify field offsets')
    parser.add_argument('--emu', default='eden', help='Emulator (eden/ryujinx)')
    args = parser.parse_args()
    
    print("SMM2 Doc Verification Tool")
    print(f"Time: {datetime.now().isoformat()}")
    print(f"Emulator: {args.emu}")
    
    g = Game(args.emu)
    
    if not g.is_running():
        print("\nERROR: Emulator not running!")
        print("Start the game first, then run this script.")
        return 1
    
    results = {}
    
    # Quick style check
    style_info = verify_game_style(g)
    if style_info:
        print(f"\nCurrent game state:")
        print(f"  Style: {style_info['game_style_name']} (value={style_info['game_style']})")
        print(f"  Scene: {style_info['scene_mode']}")
        print(f"  Has player: {style_info['has_player']}")
    
    if args.style:
        verify_style(g, args.style.upper(), results)
    elif args.all:
        print("\n⚠️  --all requires manual style changes")
        print("Will verify current style only. Change style and re-run.")
        current = style_info['game_style_name'] if style_info else 'UNKNOWN'
        verify_style(g, current, results)
    else:
        # Default: just report current state
        current = style_info['game_style_name'] if style_info else 'UNKNOWN'
        verify_style(g, current, results)
    
    # Save results
    out_path = Path(__file__).parent.parent / 'data' / 'verification_results.json'
    out_path.parent.mkdir(exist_ok=True)
    with open(out_path, 'w') as f:
        json.dump(results, f, indent=2)
    print(f"\nResults saved to: {out_path}")
    
    return 0


if __name__ == '__main__':
    sys.exit(main())
