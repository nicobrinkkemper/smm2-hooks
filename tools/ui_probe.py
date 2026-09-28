#!/usr/bin/env python3
"""What SMM2's menus show, which control has the focus, and whether they take input.

    python3 ui_probe.py <sd>/smm2-hooks/ui-screen.txt           # the active layer
    python3 ui_probe.py <sd>/smm2-hooks/ui-screen.txt --json    # as ui_screen returns it

Reads the snapshot the mod rewrites every few frames (docs/ui-probe.md).
This never sends game input.
"""
from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path

SAMPLE_FRAMES = 6            # the mod writes a snapshot every 6 frames (src/ui_probe.cpp)
SCREEN_HALF_W, SCREEN_HALF_H = 640, 360
STALE_S = 2.0

# Controller glyphs in the system font's private-use area. The block runs
# A B X Y L R from U+E0E0; checked on screen: E0E3 = Y (pause menu "Mario's
# Moves"), E0E4 = L and E0E5 = R (title "Press L + R"). Other private-use
# characters stay [U+XXXX] until a screen shows what they are.
GLYPHS = {0xE0E0: "A", 0xE0E1: "B", 0xE0E2: "X", 0xE0E3: "Y", 0xE0E4: "L", 0xE0E5: "R"}

# A state machine is named by a state only it has (the game's own names).
MACHINE_LABELS = [
    ("cTitleBack", "main_menu"), ("cToCourseRobot", "main_menu_flow"),
    ("cOpenConfirmDelete", "coursebot_list"), ("cConfirmClearCheck", "coursebot_upload_flow"),
    ("cConfirmFirstPlay", "coursebot_play_flow"), ("cYesBtn", "yes_no_dialog"),
    ("cRetryCourse", "pause_menu"), ("cPausePlay", "play_scene"), ("cLoadEnd", "loader"),
    ("cDecodeEnd", "decoder"), ("cDragScroll", "scroll"),
]
# States in which a screen is moving rather than taking input.
TRANSITIONS = {"cAppear", "cReadyAppear", "cDisappear", "cDisapear", "cDisappearWait", "cActivate",
               "cInactivate", "cHalfwayReentry", "cLoadWait", "cLoad", "cDecodeWait", "cDecode"}
TRANSITION_PREFIXES = ("cOpen", "cClose", "cTo")


def readable(text: str) -> str:
    """Text with controller glyphs as [A], [L], ... and unknown ones as [U+XXXX]."""
    return "".join(f"[{GLYPHS[ord(c)]}]" if ord(c) in GLYPHS
                   else f"[U+{ord(c):04X}]" if 0xE000 <= ord(c) <= 0xF8FF else c for c in text)


def parse(text: str) -> dict:
    """One snapshot; ValueError when it is torn (BEGIN and END disagree) or malformed."""
    lines = text.splitlines()
    if not lines:
        raise ValueError("empty")
    if lines[0].startswith("ERROR,"):
        raise RuntimeError(lines[0][6:])
    head = lines[0].split(",")
    if head[0] != "BEGIN" or len(head) != 5 or lines[-1] != f"END,{head[1]}":
        raise ValueError("torn snapshot")
    sample = {"sequence": int(head[1]), "tick": int(head[2]), "dropped": int(head[4]),
              "rows": [], "states": [], "focus": None, "focus_input": None,
              "input_on": 0, "input_off": 0, "buttons": 0, "buttons_tick": 0, "slots": []}
    for line in lines[1:-1]:
        kind, _, rest = line.partition(",")
        if kind == "TEXT":
            tick, order, root, x, y, scale, encoding, name, path, text_hex, length = rest.split(",")
            raw = bytes.fromhex(text_hex)
            codec = "utf-8" if encoding == "1" else "utf-16-le"
            sample["rows"].append({
                "tick": int(tick), "order": int(order), "root": root,
                "x": float(x), "y": float(y), "scale": float(scale),
                "path": path + name, "text": raw.decode(codec, errors="replace"),
                "truncated": len(raw) < int(length) * (1 if encoding == "1" else 2)})
        elif kind == "FOCUS":
            path, input_on = rest.rsplit(",", 1)
            sample["focus"], sample["focus_input"] = path, {"1": True, "0": False}.get(input_on)
        elif kind == "STATE":
            machine, executed, changed, frames, name, names = rest.split(",", 5)
            sample["states"].append({"machine": machine, "executed": int(executed), "changed": int(changed),
                                     "frames": int(frames), "name": name, "names": names.split("|")})
        elif kind == "INPUT":
            sample["input_on"], sample["input_off"] = (int(v) for v in rest.split(","))
        elif kind == "PAD":
            buttons, held = rest.split(",")
            sample["buttons"], sample["buttons_tick"] = int(buttons, 16), int(held)
        elif kind == "SLOTS":
            sample["slots"] = [int(v) for v in rest.split(",")]
        else:
            raise ValueError(f"unknown line {kind!r}")
    if len(sample["rows"]) != int(head[3]):
        raise ValueError("row count")
    return sample


def read(path) -> dict:
    """The newest snapshot, with its status: observed, stale, error or unavailable."""
    path = Path(path)
    for _ in range(5):  # a read that lands mid-write sees a torn file: read again
        try:
            text = path.read_text(encoding="ascii", errors="replace")
            age = max(0.0, time.time() - path.stat().st_mtime)
        except FileNotFoundError:
            return {"status": "unavailable", "path": str(path)}
        try:
            sample = parse(text)
        except RuntimeError as error:
            return {"status": "error", "error": str(error), "path": str(path)}
        except ValueError:
            time.sleep(0.02)
            continue
        return {"status": "stale" if age > STALE_S else "observed", "age_s": round(age, 3), "sample": sample}
    return {"status": "unreadable", "path": str(path)}


def under(path: str, focus: str) -> bool:
    """True when the pane path runs through every component of the focus path, in order."""
    parts = iter(path.split("/"))
    return all(any(p == want for p in parts) for want in focus.strip("/").split("/"))


def menu_state(sample: dict) -> dict:
    """The menu screens' own state machines: which run, and whether input lands.

    Each state is one Lp::Utl::StateMachine of a menu screen or loader. It is
    running when the game executed it within the last two snapshots (a dormant
    one keeps its last state). `ready`: some running screen is in a Disp*
    state (the game shows it and handles input) and none is appearing,
    disappearing, opening, closing, leaving (To*) or loading.
    """
    screens = []
    for m in sample["states"]:
        name = m["name"]
        kind = ("input" if name.startswith("cDisp")
                else "transition" if name in TRANSITIONS or name.startswith(TRANSITION_PREFIXES)
                else "other")
        label = next((l for state, l in MACHINE_LABELS if state in m["names"]), "machine@" + m["machine"][-6:])
        screens.append({"screen": label, "state": name[1:], "frames": m["frames"], "kind": kind,
                        "changed": m["changed"], "running": sample["tick"] - m["executed"] < 2 * SAMPLE_FRAMES})
    live = sorted((s for s in screens if s["running"]), key=lambda s: s["frames"])
    ready = any(s["kind"] == "input" for s in live) and not any(s["kind"] == "transition" for s in live)
    # A screen switches its buttons' input on after it enters Disp (the pause
    # menu in the same frame, the main menu two frames later).
    entered = max((s["changed"] for s in live if s["kind"] == "input"), default=None)
    screen_input = entered is not None and sample["input_on"] >= entered
    return {"ready": ready, "screen_input": screen_input, "screens": live,
            "transitions": [f'{s["screen"]}:{s["state"]}' for s in live if s["kind"] == "transition"]}


def course_slot(sample: dict, focus: str | None):
    """The Coursebot slot of the focused tile, and where it came from.

    Tile "/L_CourseDataList_0R/L_CourseBtn_0C" is entry 4R+C of the game's
    tile table; the mod records the slot the game bound to each, empty slots
    included (-1 once the game empties a tile). A tile left at -1 takes its
    slot from a bound tile of the same row, a row being 4 slots.
    """
    m = focus and re.search(r"L_CourseDataList_0(\d)/L_CourseBtn_0(\d)", focus)
    slots = sample["slots"]
    if not m or len(slots) < 20:
        return None, None
    row, col = int(m.group(1)), int(m.group(2))
    if slots[4 * row + col] >= 0:
        return slots[4 * row + col], "bound"
    bound = [(c, slots[4 * row + c]) for c in range(4) if slots[4 * row + c] >= 0]
    return (bound[0][1] - bound[0][0] + col, "row") if bound else (None, None)


def screen(sample: dict) -> dict:
    """The rows a player can see, the focused control, and the menus' state.

    Global position is the pane's global matrix translation (1280x720, origin
    at the centre). Panes outside it were still drawn (the Coursebot details
    panel draws below the screen before it slides in), so they are dropped,
    as are rows not drawn in the newest frame of the snapshot.

    The focus is the game's: the path of the last button it focused, and
    whether that button's input is switched on (None: not seen). It is
    live while any instance of that button's layout is drawn (an empty
    Coursebot tile draws no text); the focused row is the last drawn text
    under it. ui2d draws back to front, so rows drawn before the focused
    control's layout are under it: background.
    """
    newest = max((r["tick"] for r in sample["rows"]), default=0)
    rows = sorted((dict(r, readable=readable(r["text"])) for r in sample["rows"]
                   if r["tick"] == newest and abs(r["x"]) <= SCREEN_HALF_W and abs(r["y"]) <= SCREEN_HALF_H),
                  key=lambda r: r["order"])
    focus = sample["focus"]
    if focus:
        layout = re.sub(r"_\d+$", "_", focus.strip("/").split("/")[0])
        if not any(c.startswith(layout) for r in rows for c in r["path"].split("/")):
            focus = None  # a menu that just opened focuses nothing; the path is from an earlier screen
    focused = next((r for r in reversed(rows) if focus and under(r["path"], focus)), None)
    start = min((r["order"] for r in rows if focused and r["root"] == focused["root"]), default=0)
    for r in rows:
        r["focused"] = r is focused
        r["background"] = r["order"] < start
    slot, source = course_slot(sample, focus)
    return {"rows": rows, "active": [r for r in rows if not r["background"]], "focused": focused,
            "focus": focus, "input": sample["focus_input"] if focus else None,
            "course_slot": slot, "course_slot_source": source, "menu": menu_state(sample)}


def summary(view: dict) -> dict:
    """The active layer as an agent needs it."""
    f = view["focused"]
    return {"ready": view["menu"]["ready"], "screen_input": view["menu"]["screen_input"],
            "transitions": view["menu"]["transitions"],
            "screens": [f'{s["screen"]}:{s["state"]}' for s in view["menu"]["screens"]],
            "focused": f["readable"] if f else None, "focused_pane": f["path"] if f else None,
            "focus": view["focus"], "input": view["input"], "course_slot": view["course_slot"],
            "course_slot_source": view["course_slot_source"],
            "texts": [r["readable"] for r in view["active"]],
            "background_texts": sum(r["background"] for r in view["rows"])}


def observe(path) -> dict:
    """summary() of the newest snapshot, with its status, sequence and tick."""
    result = read(path)
    sample = result.get("sample")
    if not sample:
        return result
    return {**summary(screen(sample)), "status": result["status"],
            "sequence": sample["sequence"], "tick": sample["tick"],
            "buttons": sample["buttons"], "buttons_tick": sample["buttons_tick"],
            "input_on": sample["input_on"], "input_off": sample["input_off"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("path", type=Path, help="<sd>/smm2-hooks/ui-screen.txt")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    if args.json:
        print(json.dumps(observe(args.path), ensure_ascii=False, indent=2))
        return
    result = read(args.path)
    if not result.get("sample"):
        print(result)
        return
    view = screen(result["sample"])
    screens = [f'{s["screen"]}:{s["state"]}' for s in view["menu"]["screens"]]
    print(f'{result["status"]}; ready={view["menu"]["ready"]}; screens {screens}')
    for r in view["rows"]:
        mark = ">" if r["focused"] else "." if r["background"] else " "
        print(f"{mark} {r['readable']!r}  [{r['path']}]")
    if view["course_slot"] is not None:
        print(f"course slot {view['course_slot']}")


if __name__ == "__main__":
    main()
