#!/usr/bin/env python3
"""
Play the test level (NSMBU underwater).
Usage: python3 play.py [--watch] [--target-y 75]

Strategy:
- Hold RIGHT the entire time
- TAP A (press+release) to swim up — holding A does nothing after first frame
- 3 taps near wall (x=85-140) to gain altitude
- 1 safety tap near flagpole (x=180-225) if sinking below y=50
- Flagpole at x≈232, hitbox requires y>48
"""
import struct, time, sys, os, argparse
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / '.env')
SD = os.environ.get('RYUJINX_SD_PATH', '')
INPUT = os.path.join(SD, 'smm2-hooks', 'input.bin')
STATUS = os.path.join(SD, 'smm2-hooks', 'status.bin')

# Button constants
RIGHT = 0x4000
LEFT  = 0x1000
UP    = 0x2000
DOWN  = 0x8000
A     = 0x01
B     = 0x02
MINUS = 0x800

def write_input(buttons=0, lx=0, ly=0):
    with open(INPUT, 'wb') as f:
        f.write(struct.pack('<Qii', buttons, lx, ly))

def read_status():
    with open(STATUS, 'rb') as f:
        data = f.read(64)
    frame, mode, state, powerup = struct.unpack_from('<IIII', data, 0)
    px, py = struct.unpack_from('<ff', data, 16)
    vx, vy = struct.unpack_from('<ff', data, 24)
    is_dead, is_goal = struct.unpack_from('<BB', data, 37)
    polls = struct.unpack_from('<I', data, 52)[0]
    return {
        'frame': frame, 'mode': mode, 'state': state,
        'x': px, 'y': py, 'vx': vx, 'vy': vy,
        'is_dead': is_dead, 'is_goal': is_goal, 'polls': polls,
    }

def tap_a(hold=0.05, release=0.02):
    """Single A tap while holding RIGHT."""
    write_input(RIGHT | A)
    time.sleep(hold)
    write_input(RIGHT)
    time.sleep(release)

def wait_for_play_mode(timeout=30):
    """Wait until inputs are being polled and Mario can move."""
    print('Waiting for play mode...')
    deadline = time.time() + timeout
    while time.time() < deadline:
        p1 = read_status()['polls']
        time.sleep(0.15)
        s = read_status()
        if s['polls'] > p1:
            # Inputs active — verify we can actually move
            x0 = s['x']
            write_input(RIGHT)
            time.sleep(0.15)
            write_input(0)
            x1 = read_status()['x']
            if x1 > x0 + 0.1:
                print(f'  Play mode confirmed! x={x1:.0f}')
                return True
        time.sleep(0.3)
    print('  Timeout waiting for play mode')
    return False

def run_level(target_y=75, verbose=False):
    """Run the underwater test level with altitude-controlled swimming."""
    s = read_status()
    f0 = s['frame']
    taps = 0
    
    print(f'GO! Start x={s["x"]:.0f} y={s["y"]:.0f} target_y={target_y}')
    
    for i in range(500):
        s = read_status()
        x, y = s['x'], s['y']
        
        if s['is_goal']:
            elapsed = s['frame'] - f0
            print(f'GOAL! {elapsed}f ({elapsed/60:.1f}s) x={x:.0f} y={y:.0f} taps={taps}')
            return 'goal', elapsed
        
        if s['is_dead']:
            print(f'DIED at x={x:.0f} y={y:.0f}')
            return 'dead', 0
        
        if s['mode'] == 0:
            print(f'Editor mode detected at x={x:.0f} — stopping')
            return 'editor', 0
        
        # Tap A to swim: near wall area and safety near flagpole
        need_tap = (85 < x < 140 and taps < 3) or (180 < x < 225 and y < 50 and taps < 4)
        
        if need_tap:
            tap_a()
            taps += 1
            print(f'  TAP {taps} at x={x:.0f} y={y:.0f}')
        else:
            write_input(RIGHT)
            time.sleep(0.033)
        
        if verbose and i % 30 == 0:
            print(f'  x={x:.0f} y={y:.0f} vx={s["vx"]:.2f} vy={s["vy"]:.2f}')
    
    write_input(0)
    print(f'Timeout at x={x:.0f} y={y:.0f}')
    return 'timeout', 0

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--target-y', type=float, default=75)
    parser.add_argument('--verbose', '-v', action='store_true')
    parser.add_argument('--wait', action='store_true', help='Wait for play mode first')
    args = parser.parse_args()
    
    if args.wait:
        if not wait_for_play_mode():
            sys.exit(1)
    
    result, frames = run_level(target_y=args.target_y, verbose=args.verbose)
    write_input(0)
    
    if result == 'goal':
        print(f'Personal best tracking: {frames}f = {frames/60:.2f}s')
