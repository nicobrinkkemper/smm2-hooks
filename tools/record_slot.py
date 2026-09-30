#!/usr/bin/env python3
"""Record a probe over a Coursebot slot, start to finish, and time each step.

    python3 tools/record_slot.py --slot 44 --level course.bcd --probe probe.txt --seconds 30 -o run.log

Installs the course (optional) and the probe config, kills any running Eden,
launches it straight into the game, waits for the title, boots the slot into
Coursebot play, lets it run --seconds, copies probe.log to -o and kills Eden.
Prints one line per step with the elapsed time, and the scene-change count at
the end: more than 4 means the course restarted (the player died).

Do not run IDA (tools/decompile.py, xrefs.py in the decomp) during a
recording: once, with an IDA batch running beside it, the game sat at
"loading" and the boot failed; alone, the same run passed.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "mcp"))

import ctl  # noqa: E402  (the MCP tools, unwrapped)
import eden  # noqa: E402
import probe  # noqa: E402
import server  # noqa: E402


def status() -> dict:
    s = ctl.plain("game_status")()
    s = s.get("status", s) if isinstance(s, dict) else {}
    return s or {}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--slot", type=int, required=True)
    ap.add_argument("--level", help="course file (.bcd, plain or encrypted) to install first")
    ap.add_argument("--probe", required=True, help="probe.txt to arm for this boot")
    ap.add_argument("--seconds", type=float, default=30)
    ap.add_argument("--input", default="", help="held once play starts, in order: BUTTONS:ms,... (e.g. RIGHT:1500)")
    ap.add_argument("-o", "--out", required=True)
    args = ap.parse_args()

    t0 = time.time()
    step = lambda what: print(f"{time.time() - t0:6.1f}s  {what}", flush=True)

    if probe.cmd_check(argparse.Namespace(config=args.probe)):
        print("probe config failed its check", file=sys.stderr)
        return 1
    sd = Path(server.P.sd_hooks_dir)
    shutil.copy(args.probe, sd / "probe.txt")
    step("probe armed")
    if args.level:
        r = ctl.plain("level_install")(slot=args.slot, level=args.level)
        if "error" in r:
            print(r, file=sys.stderr)
            return 1
        step(f"course installed in slot {args.slot}")

    proc = eden.process()
    if proc:
        subprocess.run(["taskkill.exe", "/F", "/PID", str(proc["pid"])], capture_output=True)
        time.sleep(2)
    r = ctl.plain("eden_launch")(gdb=False)
    if r.get("error"):
        print(r["error"], file=sys.stderr)
        return 1
    step("eden launched")

    for _ in range(100):
        s = status()
        if s.get("scene") == "title" and (s.get("frame") or 0) > 1500:
            break
        time.sleep(2)
    else:
        print(f"no title screen after {time.time() - t0:.0f}s (eden: {eden.process()})", file=sys.stderr)
        return 1
    step("title")

    r = ctl.plain("game_boot")(target="coursebot", slot=args.slot, budget=240, timeout=120)
    t = server._NAV.get("thread")
    if t is not None and t.is_alive():
        t.join()
        r = dict(server._NAV["result"])
    if not r.get("ok"):
        if "yes_no_dialog" in json.dumps(r):
            # The grid opens behind "Corrupt data was found so the course has
            # been deleted": the validator refused a course (usually the one
            # just installed) and cleared its slot's used flag.
            print(f"Coursebot deleted a course as corrupt (slot {args.slot} was just installed?)", file=sys.stderr)
        print(json.dumps(r)[:400], file=sys.stderr)
        return 1
    start = status()
    step(f"coursebot play at frame {start.get('frame')}")

    held = 0.0
    if args.input:
        from smm2 import Game
        game = Game("eden")
        for part in args.input.split(","):
            buttons, ms = part.rsplit(":", 1)
            game.hold(buttons, int(ms))
            held += int(ms) / 1000
        step(f"input done: {args.input}")
    time.sleep(max(0.0, args.seconds - held))
    end = status()
    time.sleep(6)  # the mod flushes probe.log every 300 frames
    shutil.copy(sd / "probe.log", args.out)
    proc = eden.process()
    if proc:
        subprocess.run(["taskkill.exe", "/F", "/PID", str(proc["pid"])], capture_output=True)
    restarts = (end.get("scene_change_count") or 0) - (start.get("scene_change_count") or 0)
    step(f"recorded to frame {end.get('frame')}, log {args.out}, scene changes during play {restarts}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
