#!/usr/bin/env python3
"""test.py — Quick physics test runner.

Navigates to editor play mode for physics testing. Uses current editor level.
For specific test levels, use --regen to generate them first, then load via
Coursebot manually (requires emulator restart to see new saves).

Usage:
    python3 test.py                  # Navigate to editor play mode
    python3 test.py --fresh          # Kill/restart emulator, then play
    python3 test.py --regen          # Regenerate test level files (needs restart)

Note: Test levels (gen_test_levels.py) write to save files. Emulator must be
restarted to load new saves. For quick iteration, use editor test-play with
whatever level is currently loaded.
"""

import sys
import argparse
from pathlib import Path

tools_dir = Path(__file__).parent
sys.path.insert(0, str(tools_dir))

from smm2 import Game


def main():
    parser = argparse.ArgumentParser(
        description='Quick physics test runner',
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument('--regen', action='store_true',
                        help='Regenerate test level files (needs emu restart)')
    parser.add_argument('--fresh', action='store_true',
                        help='Kill and restart emulator first')
    parser.add_argument('--emu', choices=['eden', 'ryujinx'], default='eden',
                        help='Emulator (default: eden)')
    parser.add_argument('--edit', action='store_true',
                        help='Stop at editor instead of play mode')
    args = parser.parse_args()

    # Regenerate test levels if requested
    if args.regen:
        print("Regenerating test level files...")
        import subprocess
        result = subprocess.run(
            ['python3', str(tools_dir / 'gen_test_levels.py')],
            capture_output=True, text=True
        )
        if result.returncode != 0:
            print(f"Error: {result.stderr}")
            return 1
        print("✓ Test levels written to save files")
        print("  Note: Restart emulator to load new saves")
        if not args.fresh:
            return 0

    g = Game(args.emu)

    # Fresh start if requested — this already navigates to play mode
    if args.fresh:
        print(f"Restarting {args.emu}...")
        if not g.fresh():
            print("Error: fresh restart failed")
            return 1
        print(f"✓ {args.emu} restarted and playing")
        
        if args.edit:
            # Go back to editor
            g.press('MINUS', 200)
            g.wait_for(lambda s: s['scene_mode'] == 1, timeout=5)
            print("✓ At editor")
            return 0
    else:
        # Navigate to editor then play
        print("Navigating to play mode...")
        if not g.to_play(timeout=20):
            if not g.to_editor(timeout=15):
                print("Error: failed to reach editor")
                return 1
            if args.edit:
                print("✓ At editor")
                return 0
            if not g.to_play(timeout=10):
                print("Error: failed to start play")
                return 1

    s = g.status()
    if s:
        print(f"✓ Ready! pos=({s['x']:.0f}, {s['y']:.0f}) state={s['state']} style={s['style']}")
    else:
        print("✓ Ready!")

    return 0


if __name__ == '__main__':
    sys.exit(main())
