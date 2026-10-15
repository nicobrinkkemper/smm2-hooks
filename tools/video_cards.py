#!/usr/bin/env python3
"""A clip between an intro card and an outro card, for the short videos on the channel.

    python3 tools/video_cards.py <clip> <out.mp4> --title "..." [--subtitle "..."]
                                 --goal "..." --made-by "<model id or name>"
                                 [--outro "line" ...] [--speed 0.5]
                                 [--intro-secs N] [--outro-secs N]

The outro shows the goal (or the --outro lines) over a line saying when and by whom the
video was made. <out>.json beside the video records the same, with the arguments, so a
folder of videos still says what each one was for.

The clip is fitted into a 1920x1080 frame at 30 fps. --speed 0.5 shows a 60 fps clip
at half speed with every frame kept. Each card holds long enough to read its words
(about four a second, at least 4 s) unless --intro-secs / --outro-secs say otherwise. Clip audio is kept (cards are silent).
"""
import argparse, json, subprocess, tempfile
from datetime import date
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

W, H, FPS, FADE = 1920, 1080, 30, 0.3
BG, FG, DIM = (16, 16, 16), (255, 255, 255), (170, 170, 170)
BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
REGULAR = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"

a = argparse.ArgumentParser()
a.add_argument("clip"); a.add_argument("out")
a.add_argument("--title", required=True); a.add_argument("--subtitle", default="")
a.add_argument("--goal", required=True, help="what the video shows, in a sentence")
a.add_argument("--made-by", required=True, help="the model id, or the person, that made it")
a.add_argument("--outro", action="append", default=[])
a.add_argument("--speed", type=float, default=1.0)
a.add_argument("--intro-secs", type=float); a.add_argument("--outro-secs", type=float)
args = a.parse_args()
reading = lambda *texts: max(4.0, 1.5 + len(" ".join(texts).split()) / 4)  # ~4 words a second, plus a beat
made = f"made {date.today().isoformat()} by {args.made_by}"
outro = args.outro or [args.goal]
if args.intro_secs is None: args.intro_secs = reading(args.title, args.subtitle)
if args.outro_secs is None: args.outro_secs = reading(*outro, made)

def card(path, lines):
    """lines: (text, font size, bold, colour), centred as one block."""
    im = Image.new("RGB", (W, H), BG); d = ImageDraw.Draw(im)
    def wrap(t, s, b, c):  # shrink a line by up to a quarter to fit with a margin, else break it at spaces
        font = lambda n: ImageFont.truetype(BOLD if b else REGULAR, n)
        for n in range(s, int(s * 0.75) - 1, -2):
            if d.textlength(t, font=font(n)) <= W - 160: return [(t, n, b, c)]  # keeps its own spacing
        s, f, out = n, font(n), [""]
        for w in t.split():
            if out[-1] and d.textlength(f"{out[-1]} {w}", font=f) > W - 160: out.append(w)
            else: out[-1] = f"{out[-1]} {w}".strip()
        return [(piece, s, b, c) for piece in out]
    lines = [piece for line in lines for piece in wrap(*line)]
    fonts = [ImageFont.truetype(BOLD if b else REGULAR, s) for _, s, b, _ in lines]
    heights = [d.textbbox((0, 0), t, font=f)[3] for (t, *_), f in zip(lines, fonts)]
    y = (H - sum(heights) - 30 * (len(lines) - 1)) // 2
    for (t, _, _, c), f, h in zip(lines, fonts, heights):
        d.text((W // 2, y), t, font=f, fill=c, anchor="ma"); y += h + 30
    im.save(path)

probe = json.loads(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type:format=duration",
                                   "-of", "json", args.clip], capture_output=True, check=True).stdout)
dur = float(probe["format"]["duration"]) / args.speed
audio = any(s["codec_type"] == "audio" for s in probe["streams"])

tmp = Path(tempfile.mkdtemp())
card(tmp / "intro.png", [(args.title, 96, True, FG)] + ([(args.subtitle, 48, False, DIM)] if args.subtitle else []))
card(tmp / "outro.png", [(t, 56, i == 0, FG if i == 0 else DIM) for i, t in enumerate(outro)] + [(made, 36, False, DIM)])

v = lambda i, d: f"fade=t=in:d={FADE},fade=t=out:st={d - FADE}:d={FADE},format=yuv420p,setsar=1[v{i}]"
f = [f"[0]fps={FPS},{v(0, args.intro_secs)}",
     f"[1:v]setpts=PTS/{args.speed},fps={FPS},scale={W}:{H}:force_original_aspect_ratio=decrease:flags=neighbor,"
     f"pad={W}:{H}:-1:-1:color=0x101010,{v(1, dur)}",
     f"[2]fps={FPS},{v(2, args.outro_secs)}"]
silence = lambda i, d: f"anullsrc=r=48000:cl=stereo,atrim=0:{d}[a{i}]"
if audio:
    f += [silence(0, args.intro_secs), f"[1:a]atempo={args.speed},aresample=48000[a1]", silence(2, args.outro_secs),
          "[v0][a0][v1][a1][v2][a2]concat=n=3:v=1:a=1[v][a]"]
else:
    f += ["[v0][v1][v2]concat=n=3:v=1:a=0[v]"]

subprocess.run(["ffmpeg", "-y", "-loglevel", "error",
                "-loop", "1", "-t", str(args.intro_secs), "-i", tmp / "intro.png", "-i", args.clip,
                "-loop", "1", "-t", str(args.outro_secs), "-i", tmp / "outro.png",
                "-filter_complex", ";".join(f), "-map", "[v]", *(["-map", "[a]", "-c:a", "aac"] if audio else []),
                "-c:v", "libx264", "-crf", "18", "-r", str(FPS), "-movflags", "+faststart", args.out], check=True)
total = args.intro_secs + dur + args.outro_secs
Path(args.out).with_suffix(".json").write_text(json.dumps({
    "goal": args.goal, "made": date.today().isoformat(), "made_by": args.made_by,
    "title": args.title, "subtitle": args.subtitle, "outro": outro, "clip": str(Path(args.clip).resolve()),
    "speed": args.speed, "intro_secs": args.intro_secs, "outro_secs": args.outro_secs, "seconds": round(total, 2),
}, indent=2) + "\n")
print(f"{total:.1f} s -> {args.out}")
