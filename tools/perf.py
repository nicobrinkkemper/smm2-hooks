#!/usr/bin/env python3
"""Performance mode of the smm2-hooks mod (docs/perf.md).

    python3 perf.py on | off | status          # sd:/smm2-hooks/perf.txt
    python3 perf.py fps course.bcd             # frames per second with the flag off, then on

`on` and `off` reach a running game at its next scene change (a course
start, Start Over) and any later launch. `fps` boots the course twice from
the title (docs/direct-boot.md), with Eden's speed limit lifted, and counts
the mod's frame counter against the clock while the course plays with no
input. It stops a running Eden first, and puts the speed limit, perf.txt and
boot.txt back as they were.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "mcp"))

import eden  # noqa: E402
from directboot_cfg import write_slot_boot  # noqa: E402

BOOT_NAME = "perf.boot.bin"


def flag(p) -> Path:
    return Path(p.sd_hooks_dir) / "perf.txt"


def set_flag(p, on: bool) -> None:
    if on:
        flag(p).write_text("on\n")
    else:
        flag(p).unlink(missing_ok=True)


def is_on(p) -> bool:
    return flag(p).exists() and flag(p).read_text().startswith("on")


def measure(p, course: Path, on: bool, seconds: float, settle: float) -> dict:
    """One launch: frames per second of `course` in Coursebot play."""
    set_flag(p, on)
    sd = Path(p.sd_hooks_dir)
    boot, image = write_slot_boot(sd, course, slot=0, boot_name=BOOT_NAME)
    try:
        t0 = time.time()
        launched = eden.launch(p, gdb=False)
        if not launched.get("process"):
            raise SystemExit(f"launch failed: {launched}")
        status = None
        while time.time() - t0 < 120:
            status = eden.read_status(p)
            if status and status["scene"] == "coursebot_play" and status["has_player"]:
                break
            time.sleep(0.5)
        else:
            raise SystemExit(f"no Coursebot play within 120 s (last status: {status})")
        play_at = time.time() - t0
        time.sleep(settle)
        first, t1 = eden.read_status(p), time.time()
        time.sleep(seconds)
        last, t2 = eden.read_status(p), time.time()
        if not first or not last:
            raise SystemExit("status.bin went stale during the measurement: the game stopped")
        return {"perf": "on" if on else "off", "play_after_s": round(play_at, 1),
                "frames": last["frame"] - first["frame"], "seconds": round(t2 - t1, 2),
                "fps": round((last["frame"] - first["frame"]) / (t2 - t1), 1)}
    finally:
        eden.kill()
        boot.unlink(missing_ok=True)
        image.unlink(missing_ok=True)


def cmd_fps(args) -> int:
    p = eden.paths()
    course = Path(args.course)
    was_on = is_on(p)
    if eden.process():
        print("Eden is running; stopping it first")
        eden.kill()
    unlimited = eden.set_speed_limit(p, False)
    try:
        results = [measure(p, course, on, args.seconds, args.settle) for on in (False, True)]
    finally:
        if unlimited:
            eden.set_speed_limit(p, True)
        set_flag(p, was_on)
    print(f"{course.name}, {args.seconds:g} s of play with no input, Eden's speed limit off")
    for r in results:
        print(f"  perf {r['perf']:<3}  {r['fps']:7.1f} frames/s  ({r['frames']} frames in {r['seconds']} s; play {r['play_after_s']} s after launch)")
    print(f"  ratio    {results[1]['fps'] / results[0]['fps']:.2f}x")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("on", "off", "status"):
        sub.add_parser(name)
    f = sub.add_parser("fps", help="measure frames per second of a course with the flag off and on")
    f.add_argument("course", help="a course .bcd (a Coursebot slot's file or a test level)")
    f.add_argument("--seconds", type=float, default=20.0, help="length of each measurement")
    f.add_argument("--settle", type=float, default=5.0, help="wait after play starts before counting")
    args = ap.parse_args()
    if args.cmd == "fps":
        return cmd_fps(args)
    p = eden.paths()
    if args.cmd != "status":
        set_flag(p, args.cmd == "on")
    print(f"performance mode {'on' if is_on(p) else 'off'} ({flag(p)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
