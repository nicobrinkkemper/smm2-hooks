#!/usr/bin/env python3
"""Eden frames beside smm2-sim frames, one video frame per game frame (docs/frame-capture.md).

    python3 tools/side_by_side.py <eden dir> <sim dir> <out.mp4> <eden first frame> <count>
                                  [--sim-offset N] [--fps 60]

Eden frame `first + k` is shown with sim tick `k + sim-offset`. Stops at the first
missing frame on either side (a death: the hold is off until the next player).
"""
import argparse, io, subprocess
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

W, H, BAR = 960, 540, 28
EDEN_BOX = (0, 75, 1280, 795)      # the game picture inside a 1280-wide Eden window (menu bar above, status bar below)
SIM_BOX = (255, 233, 1021, 663)    # the camera rectangle in the sim's canvas at a 1280x900 viewport

a = argparse.ArgumentParser()
a.add_argument("eden", type=Path); a.add_argument("sim", type=Path); a.add_argument("out")
a.add_argument("first", type=int); a.add_argument("count", type=int)
a.add_argument("--sim-offset", type=int, default=0); a.add_argument("--fps", type=int, default=60)
args = a.parse_args()

font = ImageFont.load_default(size=20)
ff = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "image2pipe", "-framerate", str(args.fps), "-i", "-",
                       "-c:v", "libx264", "-crf", "16", "-pix_fmt", "yuv420p", args.out], stdin=subprocess.PIPE)
n = 0
for k in range(args.count):
    ef, sf = args.eden / f"{args.first + k:06d}.png", args.sim / f"{k + args.sim_offset:06d}.png"
    if not ef.exists() or not sf.exists():
        break
    frame = Image.new("RGB", (W * 2, H + BAR), (16, 16, 16))
    frame.paste(Image.open(ef).convert("RGB").crop(EDEN_BOX).resize((W, H), Image.NEAREST), (0, BAR))
    frame.paste(Image.open(sf).convert("RGB").crop(SIM_BOX).resize((W, H), Image.NEAREST), (W, BAR))
    d = ImageDraw.Draw(frame)
    d.text((8, 3), f"Eden  play frame {k}  (game frame {args.first + k})", fill=(255, 255, 255), font=font)
    d.text((W + 8, 3), f"smm2-sim  tick {k + args.sim_offset}", fill=(255, 255, 255), font=font)
    b = io.BytesIO(); frame.save(b, "PNG"); ff.stdin.write(b.getvalue())
    n += 1
ff.stdin.close(); ff.wait()
print(f"{n} frames -> {args.out}")
