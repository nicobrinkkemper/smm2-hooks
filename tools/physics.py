#!/usr/bin/env python3
"""
Physics simulator for underwater NSMBU.
Predicts Mario's trajectory given tap timing.

Constants from decomp trace data:
- Gravity: -0.5 per frame (underwater, from vy at rest)  
- Swim tap boost: ~3.628 vy (from trace.csv delegate_Walk transition)
- Max fall speed: -0.5 (underwater terminal velocity)
- Horizontal speed: ~2.3-2.8 when holding RIGHT underwater
- Ground level: y=32

Usage: python3 physics.py [--taps 85,100,120,200]
"""
import argparse

# Constants from decomp/trace data
GRAVITY_UW = -0.12          # underwater gravity per frame (calibrated from fields.csv)
SWIM_TAP_BOOST = 1.7        # vy boost per A tap (avg from fields.csv: 1.58-2.49)
TERMINAL_VEL_UW = -0.5      # underwater max fall speed
GROUND_Y = 32.0
WALL_X = 216.0              # castle wall — blocks ground-level movement
SWIM_SPEED_X = 0.67         # average x speed holding RIGHT underwater (from fields.csv)
GOAL_X = 232.0
GOAL_Y_MIN = 48.0           # must be above this to trigger flagpole
FRAMES_PER_SEC = 60

def simulate(tap_positions, start_x=72, start_y=32, verbose=False):
    """
    Simulate Mario's trajectory with A taps at given x positions.
    Returns frame-by-frame positions and whether goal is reached.
    """
    x, y = float(start_x), float(start_y)
    vx, vy = 0.0, TERMINAL_VEL_UW
    taps_used = 0
    tap_set = list(tap_positions)
    trajectory = []
    
    for frame in range(600):  # 10 seconds max
        # Apply gravity
        vy += GRAVITY_UW
        if vy < TERMINAL_VEL_UW:
            vy = TERMINAL_VEL_UW
        
        # Check if we should tap A
        if tap_set and x >= tap_set[0]:
            vy = SWIM_TAP_BOOST
            taps_used += 1
            if verbose:
                print(f"  TAP {taps_used} at f={frame} x={x:.0f} y={y:.0f}")
            tap_set.pop(0)
        
        # Accelerate horizontally
        vx = SWIM_SPEED_X  # simplified: constant speed
        
        # Move
        x += vx
        y += vy
        
        # Floor collision
        if y < GROUND_Y:
            y = GROUND_Y
            vy = TERMINAL_VEL_UW
        
        trajectory.append((frame, x, y, vx, vy))
        
        # Goal check
        if abs(x - GOAL_X) < 5 and y > GOAL_Y_MIN:
            if verbose:
                print(f"  GOAL at f={frame} x={x:.0f} y={y:.0f} ({frame/FRAMES_PER_SEC:.2f}s)")
            return trajectory, True, frame, taps_used
        
        # Past level
        if x > 400:
            if verbose:
                print(f"  OVERSHOOT at f={frame} x={x:.0f} y={y:.0f}")
            return trajectory, False, frame, taps_used
    
    return trajectory, False, 600, taps_used

def optimize_taps(n_taps=4, start_x=72):
    """Brute-force search for optimal tap positions."""
    best_frames = 9999
    best_taps = None
    
    # Search space: tap between x=75 and x=225
    import itertools
    step = 5
    positions = list(range(75, 226, step))
    
    for combo in itertools.combinations(positions, n_taps):
        _, success, frames, _ = simulate(combo, start_x)
        if success and frames < best_frames:
            best_frames = frames
            best_taps = combo
    
    return best_taps, best_frames

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--taps', type=str, default='85,100,120,200',
                       help='Comma-separated x positions for A taps')
    parser.add_argument('--optimize', type=int, default=0,
                       help='Optimize for N taps (slow!)')
    parser.add_argument('--verbose', '-v', action='store_true')
    args = parser.parse_args()
    
    if args.optimize > 0:
        print(f"Optimizing for {args.optimize} taps...")
        taps, frames = optimize_taps(args.optimize)
        if taps:
            print(f"Best: taps at x={list(taps)}, {frames}f ({frames/60:.2f}s)")
            simulate(taps, verbose=True)
        else:
            print("No solution found")
    else:
        tap_positions = [float(x) for x in args.taps.split(',')]
        print(f"Simulating with taps at x={tap_positions}")
        traj, success, frames, taps = simulate(tap_positions, verbose=True)
        print(f"Result: {'GOAL' if success else 'MISS'} in {frames}f ({frames/60:.2f}s), {taps} taps")
