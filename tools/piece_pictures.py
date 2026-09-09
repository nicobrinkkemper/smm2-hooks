#!/usr/bin/env python3
"""Pictures of one track piece each with a tick per recorded frame of the
block riding it, for the guide's chapter on how tracks move.

    python3 piece_pictures.py gallery.csv shots/ out/

`gallery.csv` is the decoded `rail` probe of the Piece Gallery and Piece
Gallery W courses (levels 49 and 50), one run each. `shots/` holds play
screenshots of the plain course named play_p_<n>.png; the piece crops name
the shot they use. Course units map to pixels by fitting the loop's four
rails in each screenshot, so the ticks land on the drawn rail without any
knowledge of the window size.
"""
from __future__ import annotations

import csv
import math
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

SCALE = 3
PLAIN, WINGS = (200, 40, 40), (30, 80, 210)
FONT = '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'

# piece: (screenshot, crop in tiles x0 y0 x1 y1, rider, segment picker)
PIECES = {
    'straight': ('play_p_1.png', (12.6, 5.6, 16.0, 7.4), 'loop'),
    'curve': ('play_p_2.png', (14.6, 5.6, 18.4, 9.2), 'loop'),
    'diagonal': ('play_p_5.png', (21.1, 5.6, 23.95, 9.2), 'diag'),
}


def dark_centre(arr, lo, hi):
    idx = np.where(arr[lo:hi] < 70)[0]
    return lo + idx.mean() if len(idx) else None


def median(vals):
    vals = [v for v in vals if v is not None]
    return float(np.median(vals)) if vals else None


def calibrate(path):
    """Course units -> pixels from the loop's rails (x 152 / 280, y 104 / 200)."""
    im = np.asarray(Image.open(path).convert('L')).astype(float)
    sx0, ox0, sy0, oy0 = 6.133, 113.0, 6.133, 1380.0  # first guess for a 2576x1408 window
    px = lambda x: ox0 + x * sx0
    py = lambda y: oy0 - y * sy0
    xs = [median([dark_centre(im[int(py(y))], int(px(x)) - 20, int(px(x)) + 20) for y in range(120, 185, 3)]) for x in (152, 280)]
    ys = [median([dark_centre(im[:, int(px(x))], int(py(y)) - 20, int(py(y)) + 20) for x in range(170, 265, 3)]) for y in (104, 200)]
    sx = (xs[1] - xs[0]) / (280 - 152)
    sy = (ys[0] - ys[1]) / (200 - 104)
    return sx, xs[0] - 152 * sx, sy, ys[0] + 104 * sy


def runs(rows):
    out, cur = [], []
    for r in rows:
        if cur and int(r['frame']) != int(cur[-1]['frame']) + 1:
            out.append(cur)
            cur = []
        cur.append(r)
    if cur:
        out.append(cur)
    return out


def riders(path):
    """{(rider, speed): [(x, y) per frame]} from the longest gapless run of each block."""
    by = {}
    for r in csv.DictReader(open(path)):
        if r['hook'] == 'rail' and r['speed'] in ('0.75', '1.5'):
            by.setdefault((r['x0'], r['speed']), []).append(r)
    out = {}
    for (x0, speed), rs in by.items():
        pts = [(float(r['mv_x']), float(r['mv_y'])) for r in max(runs(rs), key=len)]
        out[('loop' if pts[0][0] < 260 else 'diag', speed)] = pts
    return out


def straight(pts):
    """The loop's second bottom piece: rail y 104, x 216..248, first pass."""
    i = next(k for k, (x, y) in enumerate(pts) if x > 216 and y == 104)
    j = next(k for k in range(i, len(pts)) if pts[k][0] > 248)
    return pts[i:j]


def curve(pts):
    """The bottom-right curve from its horizontal end (248, 104) to its vertical end (280, 136)."""
    i = next(k for k, (x, y) in enumerate(pts) if x > 248 and y == 104)
    j = next(k for k in range(i, len(pts)) if pts[k][1] >= 136)
    return pts[i:j + 1]


def diagonal(pts):
    """The ascending diagonal from the joint (344, 104) to the cap (376, 136), first pass."""
    i = next(k for k, (x, y) in enumerate(pts) if x > 344)
    j = next(k for k in range(i, len(pts)) if pts[k][0] >= 376 or pts[k + 1][0] < pts[k][0])
    return pts[i:j + 1]


SEGMENTS = {'straight': straight, 'curve': curve, 'diagonal': diagonal}


def ticks(draw, pts, to_px, side, colour, length=16, gap=26):
    for k, p in enumerate(pts):
        a, b = pts[max(k - 1, 0)], pts[min(k + 1, len(pts) - 1)]
        dx, dy = b[0] - a[0], b[1] - a[1]
        n = math.hypot(dx, dy) or 1.0
        nx, ny = -dy / n * side, -dx / n * side  # course y is up, image y is down
        x, y = to_px(p)
        draw.line([(x + nx * gap, y + ny * gap), (x + nx * (gap + length), y + ny * (gap + length))], fill=colour, width=3)
    x, y = to_px(pts[-1])
    draw.ellipse([x - 6, y - 6, x + 6, y + 6], outline=colour, width=3)


def main(argv):
    if len(argv) != 3:
        print(__doc__)
        return 2
    table, shots, out = Path(argv[0]), Path(argv[1]), Path(argv[2])
    out.mkdir(parents=True, exist_ok=True)
    rs = riders(table)
    font = ImageFont.truetype(FONT, 20)
    for name, (shot, (x0, y0, x1, y1), rider) in PIECES.items():
        sx, ox, sy, oy = calibrate(shots / shot)
        box = (int(ox + x0 * 16 * sx), int(oy - y1 * 16 * sy), int(ox + x1 * 16 * sx), int(oy - y0 * 16 * sy))
        im = Image.open(shots / shot).convert('RGB').crop(box)
        im = im.resize((im.width * SCALE, im.height * SCALE), Image.NEAREST)
        draw = ImageDraw.Draw(im)
        to_px = lambda p: ((ox + p[0] * sx - box[0]) * SCALE, (oy - p[1] * sy - box[1]) * SCALE)
        counts = {}
        for speed, side, colour in (('0.75', +1, PLAIN), ('1.5', -1, WINGS)):
            seg = SEGMENTS[name](rs[(rider, speed)])
            counts[speed] = len(seg)
            ticks(draw, seg, to_px, side, colour)
        w, h = im.size
        draw.rectangle([0, h - 58, w, h], fill=(255, 255, 255))
        draw.text((10, h - 54), f'no wings   0.75 per frame   {counts["0.75"]} frames, one tick each', fill=PLAIN, font=font)
        draw.text((10, h - 28), f'wings   1.5 per frame   {counts["1.5"]} frames', fill=WINGS, font=font)
        im.save(out / f'piece_{name}.png')
        print(name, im.size, counts)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
