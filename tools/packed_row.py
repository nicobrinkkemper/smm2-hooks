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
DROP = {  # ride frames from activation to the drop, by vertical pieces and run pieces (packed_row_sim, bottom row 10)
    1: {0: 20, 1: 135, 2: 177, 3: 220, 4: 263, 5: 305, 6: 348, 7: 391},
    2: {0: 63, 1: 178, 2: 220, 3: 263, 4: 306, 5: 348, 6: 391, 7: 434},
    3: {0: 105, 1: 220, 2: 262, 3: 305, 4: 348, 5: 390, 6: 433, 7: 476},
    4: {0: 148, 1: 263, 2: 305, 3: 348, 4: 391, 5: 433, 6: 476, 7: 519},
    5: {0: 191, 1: 306, 2: 348, 3: 391, 4: 434, 5: 476, 6: 519, 7: 562},
    6: {0: 233, 1: 348, 2: 390, 3: 433, 4: 476, 5: 518, 6: 561, 7: 604},
}

FALL = {10: 31, 11: 37, 12: 43, 13: 49, 14: 54, 15: 58, 16: 62, 17: 66, 18: 70, 19: 74, 20: 78}   # rail on row 6
RAIL_ROW = 6
RAIL_X0 = 7               # tile 7 is the first outside the start area
SPEED = 0.75
MAX_TOP = 21              # a column's top row; its run sits three rows higher and must stay under row 25
MAX_START_TILE = 25       # a block starting right of here never activates with a standing player (the spawn box)
COL_STEP = 3              # vertical pieces are 3x3 boxes


def arrival(n, y0, h):
    return LOAD + DROP[n][h] + FALL[y0]


def top_row(n, y0):
    return y0 + 2 * (n - 1)


def columns(max_h):
    """Every (n, y0, h) a column can have, with its table arrival."""
    out = []
    for n in DROP:
        for y0 in FALL:
            if top_row(n, y0) > MAX_TOP:
                continue
            for h in range(0, max_h + 1):
                if h and top_row(n, y0) + 3 > 24:
                    continue
                out.append((n, y0, h, arrival(n, y0, h)))
    return out


def fits(chain, k, n, y0, h, x):
    """Geometry against the right-hand neighbour: the curve box next to its
    vertical, runs over its top, runs over its run."""
    if k == 0:
        return True
    pn, py, ph, _, px = chain[k - 1]
    t, pt = top_row(n, y0), top_row(pn, py)
    if h == 0:
        return True                      # a plain column bothers nobody
    if t <= pt:
        return False                     # the curve box would meet the neighbour's vertical
    if ph:
        if h >= 2 and t < pt + 3:
            return False                 # runs overlapping in x need three rows between them
        if t < pt + 2:
            return False                 # the run's first piece over the neighbour's curve box
    return True


def plan(gaps, max_h=7, slack=None, ordered=False):
    """Columns for a row of len(gaps)+1 blocks, packed from the right:
    column k sits COL_STEP tiles left of column k-1 and, on the rail, block
    k's offset from block 0 is 0.75 * (a_k - a_0) - 48 k, so the integers
    m_k = (a_k - a_0) - 64 k are the row's positions in frames of travel.
    With slack None they must be consecutive (every gap one frame, 0.75);
    with slack S the row may span up to K-1+S frames, gaps of one or two
    frames, and the tightest span wins. Returns [(n, y0, h, arrival, tile)]
    from the rightmost column, or None."""
    K = len(gaps) + 1
    max_span = (K - 1) + (0 if slack is None else slack)
    cols = columns(max_h)
    best = None

    def rec(chain, ms):
        nonlocal best
        k = len(chain)
        if k == K:
            span = max(ms) - min(ms)
            srt = sorted(ms)
            if any(b - a > 2 for a, b in zip(srt, srt[1:])):
                return
            key = (span, chain[-1][3] - chain[0][3])
            if best is None or key < best[1]:
                best = (list(chain), key)
            return
        x = chain[0][4] - COL_STEP * k
        for n, y0, h, a in cols:
            if h and x + 3 + 2 * (h - 1) > MAX_START_TILE:
                continue
            m = (a - chain[0][3]) - 64 * k
            if m in ms or max(ms + [m]) - min(ms + [m]) > max_span:
                continue
            # ordered: every later block lands one or two frames further in
            # the same direction, so the row's order is the arrival order and
            # the stacked outlines cascade one way
            if ordered and k >= 1:
                d = m - ms[-1]
                if abs(d) > 2 or (k >= 2 and (d > 0) != (ms[-1] - ms[-2] > 0)):
                    continue
            if not fits(chain, k, n, y0, h, x):
                continue
            chain.append((n, y0, h, a, x)); ms.append(m)
            rec(chain, ms)
            chain.pop(); ms.pop()

    for n, y0, h, a in cols:
        # the block starts on the last run piece, or on the column itself: that piece's tile must not pass MAX_START_TILE
        x0 = MAX_START_TILE - (3 + 2 * (h - 1)) if h else MAX_START_TILE
        if x0 - COL_STEP * (K - 1) < RAIL_X0 + 2:
            continue
        rec([(n, y0, h, a, x0)], [0])
    return best[0] if best else None


def build(chain, name):
    import gen_test_levels as g
    N = 0x0104
    level = g.LevelBuilder(name, style='SMB1', theme='Ground')
    level.goal_y = 4
    level.add_ground_fill(7, 23, 4)
    x1 = chain[0][4] + 2 if chain[0][4] % 2 else chain[0][4] + 1
    for rx in range(RAIL_X0 + (RAIL_X0 % 2 != x1 % 2), x1 + 1, 2):
        pass
    rail_x = list(range(RAIL_X0, x1 + 1, 2))
    if rail_x[-1] < chain[0][4]:
        rail_x.append(rail_x[-1] + 2)
    for rx in rail_x:
        level.add_track(rx, RAIL_ROW, g.TRACK_SHAPE_HORIZONTAL,
                        ends=(0x71 if rx == rail_x[-1] else 0x90, 0x70 if rx == rail_x[0] else N))
    placed = []
    starts = []   # (row slot, the piece the block starts on, run?)
    a0 = chain[0][3]
    for k, (n, y0, h, a, x) in enumerate(chain):
        top = top_row(n, y0)
        piece = None
        for i in range(n):
            piece = level.add_track(x, y0 + 2 * i, g.TRACK_SHAPE_VERTICAL,
                                    ends=((0x91 if h else 0x72) if i == n - 1 else 0x91, N))
        if h:
            level.add_track(x + 1, top + 2, g.TRACK_SHAPE_CURVE_TL, ends=(0x90, N))
            for j in range(h):
                piece = level.add_track(x + 3 + 2 * j, top + 3, g.TRACK_SHAPE_HORIZONTAL,
                                        ends=(0x71 if j == h - 1 else 0x90, N))
        starts.append(((a - a0) - 64 * k, piece, bool(h)))
        placed.append((x, y0, n, h, a))
    # The game draws later objects in front. Written in row order (leftmost
    # first), the stacked outlines cascade one way whatever the arrival
    # order: the rightmost block is in front and each one further left peeks
    # out on the left.
    for m, piece, run in sorted(starts, key=lambda t: t[0]):
        if run:
            level.add_note_block_on_track(piece, travel_left=True)
        else:
            level.add_note_block_on_track(piece, vertical=True)
    return level, placed, rail_x[-1]


def sim_check(sim, placed, rail_x1):
    args = [sim, f"rail={RAIL_X0}:{rail_x1}:{RAIL_ROW}", "frames=800"] + [f"{x}:{y0}:{n}:{h}" for x, y0, n, h, a in placed]
    out = subprocess.run(args, capture_output=True, text=True, check=True).stdout
    return out.strip().splitlines()[-1]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--gaps", required=True, help="comma-separated gaps in units between consecutive blocks (multiples of 0.25)")
    ap.add_argument("--name", default="Packed Row")
    ap.add_argument("--max-run", type=int, default=7, help="longest lead-in run in pieces")
    ap.add_argument("--ordered", action="store_true", help="row order = arrival order (each later block a step further the same way), for a clean cascade of outlines")
    ap.add_argument("--slack", type=int, help="allow the row to span this many extra frames of travel (gaps of two frames where one does not line up)")
    ap.add_argument("--sim", help="path to packed_row_sim (smm2-decomp/src-sim) to confirm the row")
    ap.add_argument("--out", help="write the encrypted course here")
    ap.add_argument("--install", type=int, help="install into this Coursebot slot through validate_slots (Coursebot judges it on the way)")
    args = ap.parse_args()
    gaps = [float(v) for v in args.gaps.split(",")]
    chain = plan(gaps, max_h=args.max_run, slack=args.slack, ordered=args.ordered)
    if not chain:
        print("no column set packs that row inside one screen (tiles 7..26, tops to row 21, runs to row 24)")
        return 1
    level, placed, rail_x1 = build(chain, args.name)
    print(f"{args.name}: rail row {RAIL_ROW}, tiles {RAIL_X0}..{rail_x1}; blocks travel left; {len(placed)} blocks")
    a0 = placed[0][4]
    for k, (x, y0, n, h, a) in enumerate(placed):
        m = (a - a0) - 64 * k
        run = f" + a run of {h} piece{'s' if h > 1 else ''} at row {top_row(n, y0) + 3}" if h else ""
        print(f"  block {k}: tile {x}, {n} piece{'s' if n > 1 else ''} from row {y0}{run}; arrives frame {a}; row slot {m:+d} (x {m * 0.75:+.2f} from block 0)")
    if args.sim:
        print("sim:", sim_check(args.sim, placed, rail_x1))
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
