#!/usr/bin/env python3
"""Plan a packed row of note blocks on one delivery rail, and build the course.

    python3 packed_row.py --gaps 0.75,0.75              # three blocks, one frame of travel apart
    python3 packed_row.py --gaps 0.75,0.75,0.75 --slack 1 --sim ../smm2-decomp/src-sim/packed_row_sim
    python3 packed_row.py --gaps 0.75,0.75,0.75,0.75 --slack 4 --any-order --install 9

By default later blocks land a step further the same way every time, so the
row's order is the landing order and the stack's outlines cascade one way
(the game draws a later lander in front). --any-order drops that and packs
more, with interleaved outlines: five inside one screen instead of four.

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
    """Geometry against every column to the right: the curve box next to a
    vertical, runs over tops, runs over runs, by actual tile ranges."""
    if h == 0:
        return True                      # a plain column bothers nobody
    t = top_row(n, y0)
    curve = (x + 1, x + 3, t + 2, t + 4)             # x0, x1, row0, row1 (inclusive boxes)
    run = (x + 3, x + 3 + 2 * (h - 1) + 2, t + 3, t + 5)
    def overlap(a, b):
        return not (a[1] < b[0] or b[1] < a[0] or a[3] < b[2] or b[3] < a[2])
    for pn, py, ph, _, px in chain:
        pt = top_row(pn, py)
        boxes = [(px, px + 2, py, pt + 2)]                       # the vertical stack
        if ph:
            boxes.append((px + 1, px + 3, pt + 2, pt + 4))       # its curve
            boxes.append((px + 3, px + 3 + 2 * (ph - 1) + 2, pt + 3, pt + 5))   # its run
        for b in boxes:
            if overlap(curve, b) or overlap(run, b):
                return False
    return True


def start_row(n, y0, h):
    """The row a column's block starts on: its run's row, or its top piece."""
    return top_row(n, y0) + 3 if h else top_row(n, y0)


def plan(gaps, max_h=7, slack=None, ordered=False, by_height=False, steps=(3,)):
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
            if by_height:
                # the start rows must run one way along the ROW (sorted by
                # slot), whatever order the blocks landed in
                rows = [start_row(c[0], c[1], c[2]) for _, c in sorted(zip(ms, chain), key=lambda t: t[0])]
                diffs = [b - a for a, b in zip(rows, rows[1:])]
                if any(d == 0 for d in diffs) or (min(diffs) < 0 < max(diffs)):
                    return
            # tie-break: the last block to land should join flush, so the
            # wide gap (if any) sits away from it; then the shortest wait
            last_m = ms[-1]
            near = min(abs(last_m - m) for m in ms[:-1])
            key = (span, near, chain[-1][3] - chain[0][3])
            if best is None or key < best[1]:
                best = (list(chain), key)
            return
        for step in steps:
          x = chain[-1][4] - step
          if x < RAIL_X0 + 2:
              continue
          D = (chain[0][4] - x) // 3      # column offset in units of three tiles: 64 frames of travel each
          for n, y0, h, a in cols:
            if h and x + 3 + 2 * (h - 1) > MAX_START_TILE:
                continue
            m = (a - chain[0][3]) - 64 * D
            if m in ms or max(ms + [m]) - min(ms + [m]) > max_span:
                continue
            # ordered: every later block lands one or two frames further in
            # the same direction, so the row's order is the arrival order and
            # the stacked outlines cascade one way
            if ordered and k >= 1:
                d = m - ms[-1]
                if abs(d) > 2 or (k >= 2 and (d > 0) != (ms[-1] - ms[-2] > 0)):
                    continue
            # by_height: the stack draws by start height (the highest start in
            # front in Eden, 2026-09-04), so the start rows must all differ and
            # run one way along the row (checked at the end)
            if by_height and any(start_row(n, y0, h) == start_row(c[0], c[1], c[2]) for c in chain):
                continue
            if not fits(chain, k, n, y0, h, x):
                continue
            chain.append((n, y0, h, a, x)); ms.append(m)
            rec(chain, ms)
            chain.pop(); ms.pop()

    for n, y0, h, a in cols:
        # the block starts on the last run piece, or on the column itself: that piece's tile must not pass MAX_START_TILE
        x0 = MAX_START_TILE - (3 + 2 * (h - 1)) if h else MAX_START_TILE
        if x0 - min(steps) * (K - 1) < RAIL_X0 + 2:
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
    # The stack draws in landing order (a later lander in front), not in
    # object order: writing the blocks in row order changed nothing in Eden
    # (2026-09-04). A clean cascade therefore needs the arrival order to be
    # the row order, which is what --ordered (the default) searches for.
    for m, piece, run in starts:
        if run:
            level.add_note_block_on_track(piece, travel_left=True)
        else:
            level.add_note_block_on_track(piece, vertical=True)
    return level, placed, rail_x[-1]


def sim_check(sim, placed, rail_x1):
    args = [sim, f"rail={RAIL_X0}:{rail_x1}:{RAIL_ROW}", "frames=800"] + [f"{x}:{y0}:{n}:{h}" for x, y0, n, h, a in placed]
    out = subprocess.run(args, capture_output=True, text=True, check=True).stdout
    return out.strip().splitlines()[-1]



# ---- walk mode: the player walks right, the spawn box sweeps, blocks travel right ----

# activation frame by the block's start tile under a walk held from frame 0
# (packed_row_sim walk=0:800 dir=r): about 10.67 frames per tile
ACT = {27.5: 80, 28.5: 92, 29.5: 103, 30.5: 114, 31.5: 124, 32.5: 135, 33.5: 146, 34.5: 156, 35.5: 167, 36.5: 178,
       37.5: 188, 38.5: 199, 39.5: 210, 40.5: 220, 41.5: 231, 42.5: 242, 43.5: 252, 44.5: 263, 45.5: 274, 46.5: 284,
       47.5: 295, 48.5: 306, 49.5: 316, 50.5: 327, 51.5: 338, 52.5: 348, 53.5: 359, 54.5: 370, 55.5: 380, 56.5: 391,
       57.5: 402, 58.5: 412, 59.5: 423, 60.5: 434, 61.5: 444, 62.5: 455, 63.5: 466, 64.5: 476, 65.5: 487, 66.5: 498,
       67.5: 508, 68.5: 519, 69.5: 530, 70.5: 540, 71.5: 551, 72.5: 562, 73.5: 572, 74.5: 583}
RIDE_UP = 42   # a plain column's block first rides up to its cap when it travels right


def drop_r(n, h):
    return DROP[n][h] + (RIDE_UP if h == 0 else 0)


def start_tile_r(x, n, y0, h):
    """The tile the block starts on (its centre): the column, or the run's far piece to the left."""
    return (x - 3 - 2 * (h - 1) if h else x) + 1.5


def arrival_r(x, n, y0, h):
    st = start_tile_r(x, n, y0, h)
    if st not in ACT:
        return None
    return ACT[st] + drop_r(n, h) + FALL[y0]


def boxes_r(x, n, y0, h):
    t = top_row(n, y0)
    out = [(x, x + 2, y0, t + 2)]
    if h:
        out.append((x - 1, x + 1, t + 2, t + 4))                       # TR curve
        out.append((x - 3 - 2 * (h - 1), x - 1, t + 3, t + 5))         # the run, to the left
    return out


def plan_walk(gaps, max_h=7, slack=None, by_height=True, steps=(3, 6), first_tiles=range(26, 40)):
    """Columns for a walk-activated row: block 0 is the LEFTMOST column (it
    activates first), every next column sits 3 or 6 tiles further right,
    all block starts beyond tile 26.5 (activated by the sweep, never at the
    load), blocks travel right. Block k's slot: m_k = 64 D_k - (a_k - a_0)
    with D_k the column offset in threes (positive: ahead, to the right)."""
    K = len(gaps) + 1
    max_span = (K - 1) + (0 if slack is None else slack)
    cands = []
    for n in DROP:
        for y0 in FALL:
            if top_row(n, y0) > MAX_TOP:
                continue
            for h in range(0, max_h + 1):
                if h and top_row(n, y0) + 3 > 24:
                    continue
                cands.append((n, y0, h))
    best = None

    def overlap(a, b):
        return not (a[1] < b[0] or b[1] < a[0] or a[3] < b[2] or b[3] < a[2])

    def rec(chain, ms):
        nonlocal best
        k = len(chain)
        if k == K:
            span = max(ms) - min(ms)
            srt = sorted(zip(ms, chain))
            if any(b[0] - a[0] > 2 for a, b in zip(srt, srt[1:])):
                return
            if by_height:
                rows = [start_row(c[0], c[1], c[2]) for _, c in srt]
                d = [b - a for a, b in zip(rows, rows[1:])]
                if any(v == 0 for v in d) or (min(d) < 0 < max(d)):
                    return
            near = min(abs(ms[-1] - m) for m in ms[:-1])
            key = (span, near, chain[-1][3] - chain[0][3])
            if best is None or key < best[1]:
                best = (list(chain), key)
            return
        for step in steps:
            x = chain[-1][4] + step
            D = (x - chain[0][4]) // 3
            for n, y0, h in cands:
                a = arrival_r(x, n, y0, h)
                if a is None or start_tile_r(x, n, y0, h) < 27.5:
                    continue
                m = 64 * D - (a - chain[0][3])
                if m in ms or max(ms + [m]) - min(ms + [m]) > max_span:
                    continue
                if by_height and any(start_row(n, y0, h) == start_row(c[0], c[1], c[2]) for c in chain):
                    continue
                mine = boxes_r(x, n, y0, h)
                if any(overlap(a_, b_) for c in chain for a_ in boxes_r(c[4], c[0], c[1], c[2]) for b_ in mine):
                    continue
                chain.append((n, y0, h, a, x)); ms.append(m)
                rec(chain, ms)
                chain.pop(); ms.pop()

    for x0 in first_tiles:
        for n, y0, h in cands:
            a = arrival_r(x0, n, y0, h)
            if a is None or start_tile_r(x0, n, y0, h) < 27.5:
                continue
            rec([(n, y0, h, a, x0)], [0])
    return best[0] if best else None


def build_walk(chain, name, rail_x1):
    import gen_test_levels as g
    N = 0x0104
    level = g.LevelBuilder(name, style='SMB1', theme='Ground')
    level.width = max(35, rail_x1 + 12)
    level.goal_y = 4
    level.add_ground_fill(7, level.width - 11, 4)
    rail_x = list(range(RAIL_X0, rail_x1 + 1, 2))
    for rx in rail_x:
        level.add_track(rx, RAIL_ROW, g.TRACK_SHAPE_HORIZONTAL,
                        ends=(0x71 if rx == rail_x[-1] else 0x90, 0x70 if rx == rail_x[0] else N))
    placed = []
    for n, y0, h, a, x in chain:
        top = top_row(n, y0)
        piece = None
        for i in range(n):
            piece = level.add_track(x, y0 + 2 * i, g.TRACK_SHAPE_VERTICAL,
                                    ends=((0x91 if h else 0x72) if i == n - 1 else 0x91, N))
        if h:
            level.add_track(x - 1, top + 2, g.TRACK_SHAPE_CURVE_TR, ends=(N, 0x90))
            for j in range(h):
                piece = level.add_track(x - 3 - 2 * j, top + 3, g.TRACK_SHAPE_HORIZONTAL,
                                        ends=(N, 0x70 if j == h - 1 else 0x90))
            level.add_note_block_on_track(piece, travel_left=False)
        else:
            level.add_note_block_on_track(piece, vertical=True, travel_left=False)
        placed.append((x, y0, n, h, a))
    return level, placed


def sim_check_walk(sim, placed, rail_x1, walk_to):
    args = [sim, f"rail={RAIL_X0}:{rail_x1}:{RAIL_ROW}", f"width={rail_x1 + 12}", "frames=1400", f"walk=0:{walk_to}", "dir=r"] + \
           [f"{x}:{y0}:{n}:{h}" for x, y0, n, h, a in placed]
    out = subprocess.run(args, capture_output=True, text=True, check=True).stdout
    return out.strip().splitlines()[-1]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--gaps", required=True, help="comma-separated gaps in units between consecutive blocks (multiples of 0.25)")
    ap.add_argument("--name", default="Packed Row")
    ap.add_argument("--max-run", type=int, default=7, help="longest lead-in run in pieces")
    ap.add_argument("--walk", action="store_true", help="walk-activated row: columns beyond the initial spawn box, the player walks right, blocks travel right (any length)")
    ap.add_argument("--wide", action="store_true", help="let a column sit six tiles from its neighbour instead of three")
    ap.add_argument("--by-height", action="store_true", help="the start rows must run one way along the row (the stack draws by start height: in slot 7 the highest start was in front)")
    ap.add_argument("--any-order", action="store_true", help="let later blocks land on either side of earlier ones (more blocks fit, but the stack draws in landing order and the outlines interleave)")
    ap.add_argument("--slack", type=int, help="allow the row to span this many extra frames of travel (gaps of two frames where one does not line up)")
    ap.add_argument("--sim", help="path to packed_row_sim (smm2-decomp/src-sim) to confirm the row")
    ap.add_argument("--out", help="write the encrypted course here")
    ap.add_argument("--install", type=int, help="install into this Coursebot slot through validate_slots (Coursebot judges it on the way)")
    args = ap.parse_args()
    gaps = [float(v) for v in args.gaps.split(",")]
    if args.walk:
        chain = plan_walk(gaps, max_h=args.max_run, slack=args.slack, by_height=args.by_height)
        if not chain:
            print("no walk-activated column set packs that row (columns from tile 26, starts to tile 74)")
            return 1
        last_x = chain[-1][4]
        # the row forms ahead of the columns: rail to where the first block gets by the last landing, plus a screen
        a0, aN = chain[0][3], chain[-1][3]
        row_x = (chain[0][4] + 1.5) * 16 + SPEED * (aN - a0)
        rail_x1 = int(row_x / 16) + 30
        rail_x1 += rail_x1 % 2
        level, placed = build_walk(chain, args.name, rail_x1)
        walk_to = max(ACT[start_tile_r(x, n, y0, h)] for x, y0, n, h, a in placed) + 60
        print(f"{args.name}: walk right for {walk_to} frames ({walk_to / 60:.1f} s), rail tiles {RAIL_X0}..{rail_x1}, level {level.width} tiles wide; blocks travel right; {len(placed)} blocks")
        for k, (x, y0, n, h, a) in enumerate(placed):
            m = 64 * ((x - chain[0][4]) // 3) - (a - a0)
            run = f" + a run of {h} piece{'s' if h > 1 else ''} to the left at row {top_row(n, y0) + 3}" if h else ""
            print(f"  block {k}: tile {x}, {n} piece{'s' if n > 1 else ''} from row {y0}{run}; starts on row {start_row(n, y0, h)}, activates {ACT[start_tile_r(x, n, y0, h)]}, arrives {a}; slot {m:+d}")
        print(f"  row forms about frame {aN + 2} near x {row_x:.0f} (tile {row_x / 16:.1f})")
        if args.sim:
            print("sim:", sim_check_walk(args.sim, placed, rail_x1, walk_to))
        if args.out:
            import gen_test_levels as g
            open(args.out, "wb").write(g.encrypt_course(level.build()))
            print("wrote", args.out)
        return 0
    chain = plan(gaps, max_h=args.max_run, slack=args.slack, ordered=not args.any_order, by_height=args.by_height, steps=(3, 6) if args.wide else (3,))
    if not chain:
        print("no column set packs that row inside one screen (tiles 7..26, tops to row 21, runs to row 24)")
        return 1
    level, placed, rail_x1 = build(chain, args.name)
    print(f"{args.name}: rail row {RAIL_ROW}, tiles {RAIL_X0}..{rail_x1}; blocks travel left; {len(placed)} blocks")
    a0, x0 = placed[0][4], placed[0][0]
    for k, (x, y0, n, h, a) in enumerate(placed):
        m = (a - a0) - 64 * ((x0 - x) // 3)
        run = f" + a run of {h} piece{'s' if h > 1 else ''} at row {top_row(n, y0) + 3}" if h else ""
        start = f"; starts on row {start_row(n, y0, h)}"
        print(f"  block {k}: tile {x}, {n} piece{'s' if n > 1 else ''} from row {y0}{run}{start}; arrives frame {a}; row slot {m:+d} (x {m * 0.75:+.2f} from block 0)")
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
