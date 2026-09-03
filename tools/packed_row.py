#!/usr/bin/env python3
"""Plan a packed row of note blocks on one delivery rail, and build the course.

    python3 packed_row.py --gaps 0.75,0.75              # three blocks, one frame of travel apart
    python3 packed_row.py --gaps 0.25,0.25 --name "Row 1/4" --install 8
    python3 packed_row.py --gaps 0.75,0.75 --sim ../smm2-decomp/src-sim/packed_row_sim

Every block rides its own column of vertical track pieces (block on the top
piece, open bottom end) and drops onto a shared horizontal rail, where all of
them travel left at 0.75 units a frame. A block's arrival frame is the load
frame plus the ride down its column plus the fall to the rail, so the distance
between two blocks on the rail is a column offset (16 units per tile) against
0.75 times their arrival difference:

    gap = 0.75 * (arrival_b - arrival_a) - 16 * (tile_a - tile_b)

with b the later, further-left block. The reachable gaps form a lattice of
0.25 (8-unit cells against 0.75 per frame); 0.75, one frame of travel, is the
smallest whose hits land on distinct frames. See docs/re-notes/packed-row.md
in smm2-decomp.

Arrival frames come from the sim (packed_row_sim, exact) when --sim points at
it, else from the table below, which the sim produced: the ride is 20 frames
for one piece plus 42.67 per extra piece (32 units at 0.75, snapped), and the
fall from each bottom row is a measured count. Coursebot rules the builder
enforces: no track in the start area, joints owned from below, and a column
whose box tops row 22 falls through, so y0 + 2n <= 22.
"""
import argparse
import itertools
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

LOAD = 65                 # every column activates on the load frame
RIDE1 = 20                # one piece: centre to the open end, 16 units at 0.75
RIDE_PER_PIECE = 128 / 3  # 32 units per extra piece at 0.75
FALL = {10: 31, 11: 37, 12: 43, 13: 49, 14: 54, 15: 58, 16: 62, 17: 66, 18: 70, 19: 74, 20: 78}   # rail on row 6
RAIL_ROW = 6
RAIL_X0, RAIL_X1 = 8, 22
SPEED = 0.75
MAX_TOP = 22


def ride(n):
    return round(RIDE1 + RIDE_PER_PIECE * (n - 1))


def arrival(n, y0):
    return LOAD + ride(n) + FALL[y0]


def columns():
    """Every (n, y0) a column can have, with its table arrival."""
    out = []
    for n in range(1, 7):
        for y0 in FALL:
            if y0 + 2 * n <= MAX_TOP:
                out.append((n, y0, arrival(n, y0)))
    return out


def plan(gaps, dx_choices=(3, 4, 5, 6)):
    """Columns for a row whose sorted positions are `gaps` apart. Block 0 is
    the rightmost column; every next column sits dx tiles further left and
    lands later. A block's position relative to block 0, once all are on the
    rail, is 0.75 * (arrival - arrival_0) - 16 * (tile_0 - tile): a later
    block can land left or right of an earlier one, so the row's order is
    not the arrival order. Returns [(dx, n, y0, arrival, offset)], the
    earliest-finishing row."""
    cols = columns()
    span = sum(gaps)
    target = [round(v, 4) for v in itertools.accumulate([0.0] + list(gaps))]   # sorted positions from the leftmost
    best = None

    def rec(chain, dist):
        nonlocal best
        if len(chain) == len(gaps) + 1:
            offs = sorted(c[4] for c in chain)
            rel = [round(o - offs[0], 4) for o in offs]
            if rel == target and (best is None or chain[-1][3] < best[-1][3]):
                best = list(chain)
            return
        prev_a = chain[-1][3]
        for dx in dx_choices:
            for n, y0, a in cols:
                if a <= prev_a:
                    continue
                off = round(SPEED * (a - chain[0][3]) - 16 * (dist + dx), 4)
                # every position must stay within the row's span of block 0
                if abs(off) > span + 1e-9 or any(abs(off - c[4]) < 1e-9 for c in chain):
                    continue
                chain.append((dx, n, y0, a, off))
                rec(chain, dist + dx)
                chain.pop()

    for n, y0, a in cols:
        rec([(0, n, y0, a, 0.0)], 0)
    return best


def build(chain, name, rightmost_x=None):
    import gen_test_levels as g
    N = 0x0104
    level = g.LevelBuilder(name, style='SMB1', theme='Ground')
    level.goal_y = 4
    level.add_ground_fill(7, 23, 4)
    span = sum(c[0] for c in chain)
    x = rightmost_x if rightmost_x is not None else 10 + span   # leftmost column two tiles clear of the rail's cap
    x1 = max(RAIL_X1, x + 6)
    for rx in range(RAIL_X0, x1 + 1, 2):
        level.add_track(rx, RAIL_ROW, g.TRACK_SHAPE_HORIZONTAL,
                        ends=(0x71 if rx == x1 else 0x90, 0x70 if rx == RAIL_X0 else N))
    placed = []
    for dx, n, y0, a, off in chain:
        x -= dx
        top = None
        for i in range(n):
            top = level.add_track(x, y0 + 2 * i, g.TRACK_SHAPE_VERTICAL, ends=(0x72 if i == n - 1 else 0x91, N))
        level.add_note_block_on_track(top, vertical=True)
        placed.append((x, y0, n, a))
    return level, placed


def sim_check(sim, placed):
    args = [sim, f"rail={RAIL_X0}:{max(RAIL_X1, placed[0][0] + 6)}:{RAIL_ROW}", "frames=500"] + [f"{x}:{y0}:{n}" for x, y0, n, a in placed]
    out = subprocess.run(args, capture_output=True, text=True, check=True).stdout
    return out.strip().splitlines()[-1]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--gaps", required=True, help="comma-separated gaps in units between consecutive blocks (multiples of 0.25)")
    ap.add_argument("--name", default="Packed Row")
    ap.add_argument("--sim", help="path to packed_row_sim (smm2-decomp/src-sim) to confirm the row")
    ap.add_argument("--out", help="write the encrypted course here")
    ap.add_argument("--install", type=int, help="install into this Coursebot slot through validate_slots (Coursebot judges it on the way)")
    args = ap.parse_args()
    gaps = [float(v) for v in args.gaps.split(",")]
    chain = plan(gaps)
    if not chain:
        print("no column set reaches those gaps with vertical columns alone (up to six pieces, rows 10..20); "
              "longer or finer rows need lead-up geometry (curves at 51 frames, straights at 21/22)")
        return 1
    level, placed = build(chain, args.name)
    print(f"{args.name}: rail row {RAIL_ROW}, tiles {RAIL_X0}..{max(RAIL_X1, placed[0][0] + 6)}; blocks travel left")
    for k, (x, y0, n, a) in enumerate(placed):
        off = chain[k][4]
        print(f"  block {k}: column at tile {x}, {n} piece{'s' if n > 1 else ''} from row {y0}, arrives frame {a}, "
              f"settles {abs(off):.2f} {'left' if off > 0 else 'right'} of block 0" if k else
              f"  block {k}: column at tile {x}, {n} piece{'s' if n > 1 else ''} from row {y0}, arrives frame {a}")
    order = sorted(range(len(chain)), key=lambda k: chain[k][4])
    print("  row, left to right: " + "  ".join(f"block {k}" + (f"  +{chain[k][4]-chain[order[j-1]][4]:.2f}" if j else "") for j, k in enumerate(order)))
    if args.sim:
        print("sim:", sim_check(args.sim, placed))
    if args.out:
        import gen_test_levels as g
        open(args.out, "wb").write(g.encrypt_course(level.build()))
        print("wrote", args.out)
    if args.install is not None:
        out = args.out or os.path.join(HERE, f"packed_row_{args.install}.bcd")
        if not args.out:
            import gen_test_levels as g
            open(out, "wb").write(g.encrypt_course(level.build()))
        print(subprocess.run([sys.executable, os.path.join(HERE, "validate_slots.py"), f"{args.install}={out}"],
                             capture_output=True, text=True).stdout.strip().splitlines()[-1])
    return 0


if __name__ == "__main__":
    sys.exit(main())
