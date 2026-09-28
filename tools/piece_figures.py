#!/usr/bin/env python3
"""The guide's track-piece figures: a play screenshot with one tick per frame.

A block riding a rail moves a fixed distance every frame, so its recorded
positions ARE the picture: drop a tick at each one and the spacing is the
speed, the count is the duration. Non-winged ticks go on one side of the rail,
winged on the other, so one crop says both.

Measured on Piece Gallery (gen_test_levels.py slots 49 and 50): the Rail Trace
loop beside the Rail Diag2 bend, so a straight, a curve and a diagonal all sit
on one screen. Slot 49 rides at 0.75 a frame, slot 50 (winged) at 1.5.

The figures live in the guide's Google Doc, not in a repo -- a decomp
checkout carries the words, the Doc carries the pictures. This script is here
so they can be remade, not so their output can be committed.

Recipe:

    # 1. the two courses, and a rail recording of each
    ctl.py level_install '{"slot": 49, "level": "Piece Gallery"}'
    ctl.py level_install '{"slot": 50, "level": "Piece Gallery W"}'
    ctl.py trace_record '{"action": "start", "probe": "rail"}'   # play slot 49
    ctl.py trace_record '{"action": "stop", "out": "gallery49.csv"}'
    # ... the same for slot 50 -> gallery50.csv, then concatenate them:
    #     both speeds must reach this script in one file.

    # 2. a screenshot of each piece on screen during play
    ctl.py eden_screenshot   # -> play_p_1 (straight), _2 (curve), _5 (diagonal)

    # 3. the figures
    python3 tools/piece_figures.py --gallery gallery.csv --shots . --out .

Needs Pillow and numpy (see mcp/requirements.txt).
"""
from __future__ import annotations

import argparse
import csv
import math
import sys
from pathlib import Path

try:
    import numpy as np
    from PIL import Image, ImageDraw, ImageFont
except ImportError:  # pragma: no cover - a clear word beats a traceback
    sys.exit("piece_figures needs Pillow and numpy: pip install pillow numpy")

SCALE = 3
RED, BLUE = (200, 40, 40), (30, 80, 210)
FONTS = ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
         "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf")

# Which screenshot each piece is cropped from, and the crop in course tiles.
# These reproduce the three figures that are in the guide byte for byte; the
# diagonal starts at 21.1 rather than on the tile, to cut the sliver of the
# horizontal piece feeding into it.
CROPS = {"straight": ("play_p_1.png", (12.6, 5.6, 16.0, 7.4)),
         "curve":    ("play_p_2.png", (14.6, 5.6, 18.4, 9.2)),
         "diagonal": ("play_p_5.png", (21.1, 5.6, 23.95, 9.2))}


# ── calibration ───────────────────────────────────────────────────────────
# The camera's scale and offset are not assumed: the loop's own rails are
# found in the screenshot and course units are fitted to pixels from them, so
# a shot taken at any scroll position still lands its ticks on the rail.

def _dark_centre(arr, lo, hi):
    idx = np.where(arr[lo:hi] < 70)[0]
    return lo + idx.mean() if len(idx) else None


def _median(vals):
    vals = [v for v in vals if v is not None]
    return float(np.median(vals)) if vals else None


def calibrate(path: str):
    """Fit course units -> pixels from the loop's rails. (sx, ox, sy, oy)."""
    im = np.asarray(Image.open(path).convert("L")).astype(float)
    sx0, ox0, sy0, oy0 = 6.133, 113.0, 6.133, 1380.0   # a seed, then refined
    px = lambda x: ox0 + x * sx0
    py = lambda y: oy0 - y * sy0
    # vertical rails x=152 and 280, sampled on rows between the horizontal ones
    xs = [_median([_dark_centre(im[int(py(y))], int(px(x)) - 20, int(px(x)) + 20)
                   for y in range(120, 185, 3)]) for x in (152, 280)]
    # horizontal rails y=104 and 200, sampled on columns between the vertical ones
    ys = [_median([_dark_centre(im[:, int(px(x))], int(py(y)) - 20, int(py(y)) + 20)
                   for x in range(170, 265, 3)]) for y in (104, 200)]
    if None in xs or None in ys:
        raise SystemExit(f"{path}: could not find the loop's rails to calibrate against")
    sx = (xs[1] - xs[0]) / (280 - 152)
    sy = (ys[0] - ys[1]) / (200 - 104)
    return sx, xs[0] - 152 * sx, sy, ys[0] + 104 * sy


# ── the recording ─────────────────────────────────────────────────────────

def _runs(rows):
    """Split a rider's rows into contiguous-frame runs."""
    out, cur = [], []
    for r in rows:
        if cur and int(r["frame"]) != int(cur[-1]["frame"]) + 1:
            out.append(cur)
            cur = []
        cur.append(r)
    if cur:
        out.append(cur)
    return out


def load(path: str):
    """Rail rows as {(which, speed): [(x, y), ...]}, longest unbroken run each.

    Riders are told apart by their actor handle (x0) and speed, and placed by
    where they start: the loop sits left of x 260, the diagonal right of it.
    """
    with open(path) as fh:
        rows = [r for r in csv.DictReader(fh)
                if r["hook"] == "rail" and r["speed"] in ("0.75", "1.5")]
    by: dict = {}
    for r in rows:
        by.setdefault((r["x0"], r["speed"]), []).append(r)
    riders = {}
    for (_handle, speed), rs in by.items():
        run = max(_runs(rs), key=len)
        pts = [(float(r["mv_x"]), float(r["mv_y"])) for r in run]
        riders[("loop" if pts[0][0] < 260 else "diag", speed)] = pts
    return riders


# The stretch of each rider's path that is the piece in question.
def _straight(pts):
    i = next(k for k, (x, y) in enumerate(pts) if x > 216 and y == 104)
    j = next(k for k in range(i, len(pts)) if pts[k][0] > 248)
    return pts[i:j]


def _curve(pts):
    i = next(k for k, (x, y) in enumerate(pts) if x > 248 and y == 104)
    j = next(k for k in range(i, len(pts)) if pts[k][1] >= 136)
    return pts[i:j + 1]


def _diagonal(pts):
    i = next(k for k, (x, y) in enumerate(pts) if x > 344)
    j = next(k for k in range(i, len(pts))
             if pts[k][0] >= 376 or pts[k + 1][0] < pts[k][0])
    return pts[i:j + 1]


SEGS = {"straight": _straight, "curve": _curve, "diagonal": _diagonal}


# ── drawing ───────────────────────────────────────────────────────────────

def ticks(draw, pts, to_px, side, colour, length=16, gap=26):
    """One mark per point, square to the path, offset to one side of the rail."""
    for k, p in enumerate(pts):
        a = pts[max(k - 1, 0)]
        b = pts[min(k + 1, len(pts) - 1)]
        dx, dy = b[0] - a[0], b[1] - a[1]
        n = math.hypot(dx, dy) or 1.0
        # course y is up, image y is down: the normal flips with it
        nx, ny = -dy / n * side, -dx / n * side
        x, y = to_px(p)
        draw.line([(x + nx * gap, y + ny * gap),
                   (x + nx * (gap + length), y + ny * (gap + length))],
                  fill=colour, width=3)
    x, y = to_px(pts[-1])
    draw.ellipse([x - 6, y - 6, x + 6, y + 6], outline=colour, width=3)


def font(size=20):
    for path in FONTS:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def compose(gallery: str, shots: Path, out: Path) -> None:
    riders = load(gallery)
    face = font()
    out.mkdir(parents=True, exist_ok=True)
    for name, (shot, (x0, y0, x1, y1)) in CROPS.items():
        path = str(shots / shot)
        sx, ox, sy, oy = calibrate(path)
        im = Image.open(path).convert("RGB")
        box = (int(ox + x0 * 16 * sx), int(oy - y1 * 16 * sy),
               int(ox + x1 * 16 * sx), int(oy - y0 * 16 * sy))
        crop = im.crop(box).resize(((box[2] - box[0]) * SCALE,
                                    (box[3] - box[1]) * SCALE), Image.NEAREST)
        draw = ImageDraw.Draw(crop)
        to_px = lambda p: ((ox + p[0] * sx - box[0]) * SCALE,
                           (oy - p[1] * sy - box[1]) * SCALE)
        which = "diag" if name == "diagonal" else "loop"
        counts = {}
        for speed, side, colour in (("0.75", +1, RED), ("1.5", -1, BLUE)):
            key = (which, speed)
            if key not in riders:
                raise SystemExit(f"{gallery}: no {which} rider at {speed} a frame "
                                 "(both galleries must reach this script in one file)")
            seg = SEGS[name](riders[key])
            counts[speed] = len(seg)
            ticks(draw, seg, to_px, side, colour)
        w, h = crop.size
        draw.rectangle([0, h - 58, w, h], fill=(255, 255, 255))
        draw.text((10, h - 54), f'no wings   0.75 per frame   {counts["0.75"]} frames, one tick each', fill=RED, font=face)
        draw.text((10, h - 28), f'wings   1.5 per frame   {counts["1.5"]} frames', fill=BLUE, font=face)
        dest = out / f"piece_{name}.png"
        crop.save(dest)
        print(f"{dest}  {crop.size[0]}x{crop.size[1]}  "
              f"{counts['0.75']} / {counts['1.5']} frames")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--gallery", default="gallery.csv",
                    help="rail recording holding BOTH galleries (slots 49 and 50)")
    ap.add_argument("--shots", type=Path, default=Path("."),
                    help="directory holding play_p_1/_2/_5.png")
    ap.add_argument("--out", type=Path, default=Path("."), help="where to write the figures")
    a = ap.parse_args()
    compose(a.gallery, a.shots, a.out)


if __name__ == "__main__":
    main()
