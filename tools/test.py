#!/usr/bin/env python3
"""test.py — Quick test level runner.

Combines gen_test_levels.py + smm2.py Game API for one-command test runs.

Usage:
    python3 test.py                  # Play flat ground (slot 0)
    python3 test.py 2                # Play slope course (slot 2)
    python3 test.py --regen          # Regenerate all test levels first
    python3 test.py --list           # List available test levels
    python3 test.py --fresh          # Kill/restart emulator first

Test Levels:
    0: Flat Ground (SMB1)    5: Flat Ground (3DW)
    1: Jump Platforms        6: Flat Ground (SMB3)
    2: Slope Course          7: Flat Ground (SMW)
    3: Ice Terrain           8: Flat Ground (NSMBU)
    4: Underwater            9: Empty (custom)
"""

import sys
import argparse
from pathlib import Path

# Add tools dir to path
tools_dir = Path(__file__).parent
sys.path.insert(0, str(tools_dir))

from smm2 import Game


TEST_LEVEL_NAMES = {
    0: "Flat Ground (SMB1)",
    1: "Jump Platforms",
    2: "Slope Course",
    3: "Ice Terrain",
    4: "Underwater",
    5: "Flat Ground (3DW)",
    6: "Flat Ground (SMB3)",
    7: "Flat Ground (SMW)",
    8: "Flat Ground (NSMBU)",
    9: "Empty",
}


def main():
    parser = argparse.ArgumentParser(
        description='Quick test level runner',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    parser.add_argument('slot', type=int, nargs='?', default=0,
                        help='Test level slot (0-9)')
    parser.add_argument('--regen', action='store_true',
                        help='Regenerate test levels before playing')
    parser.add_argument('--list', action='store_true',
                        help='List available test levels')
    parser.add_argument('--fresh', action='store_true',
                        help='Kill and restart emulator first')
    parser.add_argument('--emu', choices=['eden', 'ryujinx'], default='eden',
                        help='Emulator (default: eden)')
    parser.add_argument('--edit', action='store_true',
                        help='Stop at editor instead of play mode')
    args = parser.parse_args()

    if args.list:
        print("Test Levels:")
        for slot, name in sorted(TEST_LEVEL_NAMES.items()):
            print(f"  {slot}: {name}")
        return 0

    slot = args.slot
    if slot not in TEST_LEVEL_NAMES:
        print(f"Error: slot {slot} not valid (0-9)")
        return 1

    print(f"Test Level: {slot} - {TEST_LEVEL_NAMES[slot]}")

    # Regenerate if requested
    if args.regen:
        print("Regenerating test levels...")
        import subprocess
        result = subprocess.run(
            ['python3', str(tools_dir / 'gen_test_levels.py')],
            capture_output=True, text=True
        )
        if result.returncode != 0:
            print(f"Error: {result.stderr}")
            return 1
        print("✓ Test levels regenerated")

    # Fresh start if requested
    g = Game(args.emu)
    if args.fresh:
        print(f"Restarting {args.emu}...")
        if not g.fresh():
            print("Error: fresh restart failed")
            return 1
        print(f"✓ {args.emu} restarted")

    # Navigate to test level
    print(f"Loading slot {slot} via Coursebot...")
    if not g.to_coursebot_play(slot):
        print("Error: navigation failed")
        return 1

    if args.edit:
        print("Returning to editor...")
        g.press('MINUS', 200)
        g.wait_for(lambda s: s['scene_mode'] == 1, timeout=5)

    s = g.status()
    if s:
        print(f"✓ Ready! pos=({s['x']:.0f}, {s['y']:.0f}) state={s['state']}")
    else:
        print("✓ Ready!")

    return 0


if __name__ == '__main__':
    sys.exit(main())
