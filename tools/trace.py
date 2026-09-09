#!/usr/bin/env python3
"""One-shot probe recording: direct-boot into a Coursebot course, play a scripted walk, decode.

    python3 trace.py --probe rail.txt --coursebot 5 --walk RIGHT:9 -o rail.csv
    python3 trace.py --probe spawn.txt --coursebot 5 --walk RIGHT:9,LEFT:22,RIGHT:14 -o persist.csv
    python3 trace.py --preset rail --coursebot 11 --wait 12 -o loop.csv          # no input, just watch

Writes sd:/smm2-hooks/boot.txt (docs/direct-boot.md; removed again right
after launch), installs the probe config, launches Eden, waits for
Coursebot play (scene mode 7), holds each button of --walk for its seconds
while sampling status.bin into <out>.player.csv, kills Eden, decodes
probe.log into <out>. Play starts about 16 s after launch with skip_intro
on; a whole run is under a minute plus the walk.

Known limit (2026-08-30): the direct boot plays the course that is resident
at the title, not the Coursebot entry, until the Coursebot's course-load
call is replayed too; see docs/direct-boot.md.
"""
from __future__ import annotations

import argparse
import csv
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "mcp"))

import eden  # noqa: E402
from smm2 import Game  # noqa: E402

COURSEBOT_PLAY = 7


def sd_dir(target: str) -> Path:
    from probe import sd_hooks_dir  # noqa: WPS433
    return sd_hooks_dir(target)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--probe", help="probe config file (docs/probe.md)")
    src.add_argument("--preset", help="probe preset name (probe.py preset)")
    ap.add_argument("--coursebot", type=int, required=True, help="Coursebot entry to boot into")
    ap.add_argument("--kind", type=int, default=4, help="transition kind (4 play, 3 editor)")
    ap.add_argument("--via-robo", action="store_true", help="two-phase boot through the Coursebot scene (experimental)")
    ap.add_argument("--menu", action="store_true", help="navigate the Coursebot menus to the slot (slower, but plays the chosen course)")
    ap.add_argument("--walk", default="", help="BUTTON:seconds[,BUTTON:seconds...] after a 2 s settle")
    ap.add_argument("--wait", type=float, default=0.0, help="seconds to watch with no input (after --walk)")
    ap.add_argument("--target", default="eden")
    ap.add_argument("-o", "--out", required=True, help="decoded CSV; the player samples go to <out>.player.csv")
    args = ap.parse_args()

    sd = sd_dir(args.target)
    if args.preset:
        cfg = sd / "probe.txt"
        cfg.write_text(subprocess.run([sys.executable, str(HERE / "probe.py"), "preset", args.preset],
                                      capture_output=True, text=True, check=True).stdout)
    else:
        subprocess.run([sys.executable, str(HERE / "probe.py"), "check", args.probe], check=True)
        subprocess.run([sys.executable, str(HERE / "probe.py"), "install", args.probe, "--target", args.target], check=True)
    boot = sd / "boot.txt"
    if args.menu:
        boot.unlink(missing_ok=True)
    else:
        keyword = "coursebot2" if args.via_robo else "coursebot"
        boot.write_text(f"{keyword} {args.coursebot} {args.kind}\n")
    log = sd / "probe.log"
    if log.exists():
        log.unlink()

    if eden.process():
        print("Eden already running; stopping it first")
        eden.kill()
        time.sleep(2)
    t0 = time.time()
    r = eden.launch(eden.paths(), gdb=False)
    if not r.get("process"):
        print("launch failed:", r)
        boot.unlink(missing_ok=True)
        return 1
    time.sleep(3)
    boot.unlink(missing_ok=True)   # read once at boot; a leftover would hijack the menu-driven scripts
    g = Game(args.target)
    if args.menu:
        # The Coursebot grid only holds registered slots; navigating to an
        # unused position lands in an arbitrary course (learned the hard way
        # on "slot 11" with ten used slots).
        import save_dat  # noqa: WPS433
        body = save_dat.decrypt((Path(eden.paths().save_dir) / "save.dat").read_bytes())
        used = [s for s, f in save_dat.records(body) if f]
        if args.coursebot not in used:
            print(f"slot {args.coursebot} is not registered in save.dat (used: {used}); refusing to navigate blind")
            eden.kill()
            return 1
        st = g.wait_for(lambda s: s["scene_mode"] == 6, timeout=120)
        if not st:
            print("no title within 120 s")
            eden.kill()
            return 1
        time.sleep(6)
        if not g.to_coursebot_play(slot=args.coursebot, timeout=90):
            print("menu navigation failed")
            eden.kill()
            return 1
        st = g.status()
    else:
        st = g.wait_for(lambda s: s["scene_mode"] == COURSEBOT_PLAY, timeout=120)
    if not st:
        print("no Coursebot play within 120 s; directboot.log:")
        print((sd / "directboot.log").read_text() if (sd / "directboot.log").exists() else "(none)")
        eden.kill()
        return 1
    print(f"play at {time.time() - t0:.0f} s, frame {st['frame']}, scene {st['scene_mode']} ({'Coursebot play' if st['scene_mode'] == COURSEBOT_PLAY else 'editor test-play'})")

    samples: list[tuple[int, float, float]] = []

    def sample(seconds: float) -> None:
        end = time.time() + seconds
        while time.time() < end:
            s = g.status()
            if s:
                samples.append((s["frame"], s["x"], s["y"]))
            time.sleep(0.01)

    sample(2.0)
    for step in filter(None, args.walk.split(",")):
        button, _, secs = step.partition(":")
        # No release between steps: the held set just changes, so combos like a
        # timed hop mid-run (RIGHT+Y then RIGHT+Y+B) stay unbroken. NONE holds
        # nothing for the step's duration.
        g._write_input(0 if button.upper() == "NONE" else g._parse_buttons(button), 0, 0)
        sample(float(secs or 1))
    g.release()
    if args.wait:
        sample(args.wait)
    time.sleep(5.5)  # the mod flushes every 300 frames
    eden.kill()
    time.sleep(1)

    out = Path(args.out)
    with open(f"{out}.player.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["frame", "player_x", "player_y"])
        w.writerows(samples)
    if not log.exists():
        print("no probe.log")
        return 1
    keep = out.with_suffix(".log")
    shutil.copyfile(log, keep)
    subprocess.run([sys.executable, str(HERE / "probe.py"), "decode", str(keep), "-o", str(out)], check=True)
    print(f"samples {len(samples)}, log {keep}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
