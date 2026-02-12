#!/usr/bin/env python3
"""
Build a level map from fields.csv data.
Detects walls, floors, ceilings from position/velocity patterns.

Usage: python3 map_level.py [fields.csv]
"""
import csv, sys, os
from pathlib import Path
from collections import defaultdict
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / '.env')
SD = os.environ.get('RYUJINX_SD_PATH', '')

def load_fields(path=None):
    if path is None:
        path = os.path.join(SD, 'smm2-hooks', 'fields.csv')
    rows = []
    with open(path, 'r', errors='replace') as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                rows.append({
                    'frame': int(row['frame']),
                    'state': int(row['state']),
                    'x': float(row['pos_x']),
                    'y': float(row['pos_y']),
                    'vx': float(row['vel_x']),
                    'vy': float(row['vel_y']),
                })
            except (ValueError, KeyError):
                continue
    return rows

def find_walls(rows):
    """Find x positions where vx drops to 0 while pressing right/left."""
    walls = defaultdict(int)
    for i in range(1, len(rows)):
        prev, cur = rows[i-1], rows[i]
        # Moving right then stopped
        if prev['vx'] > 0.5 and abs(cur['vx']) < 0.1 and abs(cur['x'] - prev['x']) < 2:
            wx = round(cur['x'])
            walls[wx] += 1
        # Moving left then stopped
        if prev['vx'] < -0.5 and abs(cur['vx']) < 0.1 and abs(cur['x'] - prev['x']) < 2:
            wx = round(cur['x'])
            walls[wx] += 1
    return {x: c for x, c in walls.items() if c >= 2}  # at least 2 hits

def find_floors(rows):
    """Find y positions where vy becomes ~-0.5 (gravity-settled on ground)."""
    floors = defaultdict(int)
    for r in rows:
        if -0.6 < r['vy'] < -0.4:  # settled at terminal velocity on ground
            fy = round(r['y'])
            floors[fy] += 1
    return {y: c for y, c in floors.items() if c >= 10}

def find_bounds(rows):
    """Find level boundaries from min/max positions."""
    xs = [r['x'] for r in rows if r['state'] not in (0, 16)]
    ys = [r['y'] for r in rows if r['state'] not in (0, 16)]
    if not xs:
        return None
    return {
        'x_min': min(xs), 'x_max': max(xs),
        'y_min': min(ys), 'y_max': max(ys),
    }

def find_goal(rows):
    """Find where goal triggered (state 122)."""
    for r in rows:
        if r['state'] == 122:
            return r['x'], r['y']
    return None

def find_swim_taps(rows):
    """Find A-tap effects: where vy suddenly jumps positive."""
    taps = []
    for i in range(1, len(rows)):
        prev, cur = rows[i-1], rows[i]
        if cur['vy'] - prev['vy'] > 2.0:  # sudden upward burst
            taps.append({
                'frame': cur['frame'],
                'x': cur['x'], 'y': cur['y'],
                'vy_before': prev['vy'], 'vy_after': cur['vy'],
                'boost': cur['vy'] - prev['vy'],
            })
    return taps

if __name__ == '__main__':
    path = sys.argv[1] if len(sys.argv) > 1 else None
    rows = load_fields(path)
    print(f"Loaded {len(rows)} field samples")
    
    bounds = find_bounds(rows)
    if bounds:
        print(f"\nLevel bounds:")
        print(f"  X: {bounds['x_min']:.0f} — {bounds['x_max']:.0f}")
        print(f"  Y: {bounds['y_min']:.0f} — {bounds['y_max']:.0f}")
    
    walls = find_walls(rows)
    if walls:
        print(f"\nWalls detected (x → hit count):")
        for x in sorted(walls):
            print(f"  x={x}: {walls[x]} hits")
    
    floors = find_floors(rows)
    if floors:
        print(f"\nFloors (y → sample count):")
        for y in sorted(floors):
            print(f"  y={y}: {floors[y]} samples")
    
    goal = find_goal(rows)
    if goal:
        print(f"\nGoal: x={goal[0]:.0f} y={goal[1]:.0f}")
    
    taps = find_swim_taps(rows)
    if taps:
        print(f"\nSwim taps detected ({len(taps)}):")
        for t in taps[:10]:
            print(f"  f={t['frame']} x={t['x']:.0f} y={t['y']:.0f} "
                  f"vy: {t['vy_before']:.2f} → {t['vy_after']:.2f} (boost={t['boost']:.2f})")
