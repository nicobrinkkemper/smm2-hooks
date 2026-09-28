#!/usr/bin/env python3
"""Read the experimental UI probe log. This never sends game input.

These are sampled draw submissions, not an active-menu/focus API. Raw text
can contain formatting tags and controller glyphs; retain it for research.
"""
import argparse
import json
from pathlib import Path
import re
import struct
import time

HEADER = "UI_PROBE,6,303,draw_submission,mode="

def decode_row(line):
    fields = line.split(",")
    if len(fields) != 14 or fields[0] != "TEXT":
        raise ValueError("malformed TEXT row")
    _, address, encoding, length, capacity, flags, alpha, name, text, tick, order, root, path, geom = fields
    encoding, length, capacity, flags, alpha = map(int, (encoding,length,capacity,flags,alpha))
    if encoding not in (0,1) or not 0 < length < capacity <= 65535 or not 0 <= flags <= 255 or not 0 <= alpha <= 255:
        raise ValueError("invalid text metadata")
    pane = int(address, 16)
    if not 0 < pane < 2**64: raise ValueError("invalid pane address")
    name_bytes, raw = bytes.fromhex(name), bytes.fromhex(text)
    width = 1 if encoding else 2
    if len(name_bytes) != 24 or len(raw) != min(length*width,256):
        raise ValueError("invalid bounded text length")
    geom_bytes = bytes.fromhex(geom)
    if len(geom_bytes) != 0x60: raise ValueError("invalid geometry block")
    # pane+0x30..0x90 as 24 floats; the layout of this block is under study
    floats = struct.unpack("<24f", geom_bytes)
    ancestors = [bytes.fromhex(n).split(b"\0",1)[0].decode("ascii",errors="replace") for n in path.split("/") if n]
    codec = "utf-8" if encoding else "utf-16-le"
    malformed = False
    try: decoded = raw.decode(codec)
    except UnicodeDecodeError:
        malformed = True; decoded = raw.decode(codec, errors="replace")
    return {"pane_address":hex(pane), "pane_name":name_bytes.split(b"\0",1)[0].decode("ascii",errors="replace"),
        "text":decoded, "encoding":codec, "length_units":length, "capacity_units":capacity,
        "raw_hex":raw.hex(), "truncated":len(raw)<length*width, "malformed":malformed,
        "contains_controls":any(ord(c)<32 and c not in "\n\t" for c in decoded),
        "pane_flags":flags,"alpha":alpha,"tick":int(tick),"order":int(order),"root":hex(int(root,16)),
        "path":"/".join(reversed(ancestors)),"geom":[round(f,3) for f in floats],"visibility":"draw-submitted; final visibility unknown",
        "focus":None,"enabled":None}

def parse_samples(text, machines=None):
    """Complete samples; MACHINE lines (each machine's state names) go into `machines`."""
    machines={} if machines is None else machines
    samples=[]; current=None; errors=[]
    for line in text.splitlines():
        if line.startswith("BEGIN,"):
            try:
                _,seq,count,dropped,printed,tick=line.split(",")
                seq,count,dropped=int(seq),int(count),int(dropped)
                if seq<1 or not 0<=count<=128 or dropped<0: raise ValueError("invalid sample bounds")
                current={"sequence":seq,"tick":int(tick),"expected_rows":count,"dropped":dropped,"printed_pane":printed,"rows":[]}
            except ValueError as e: current=None; errors.append(str(e))
        elif line.startswith("TEXT,") and current is not None:
            try:
                current["rows"].append(decode_row(line))
                if len(current["rows"])>current["expected_rows"]: raise ValueError("too many rows")
            except ValueError as e: current=None; errors.append(str(e))
        elif line.startswith("MACHINE,"):
            _,machine,_count,names=line.split(",",3)
            machines[machine]=names.split("|")
        elif line.startswith("STATE,") and current is not None:
            _,machine,tick,caller,state,frames,rest=line.split(",",6)
            name,executed=rest.rsplit(",",1)
            current.setdefault("states",[]).append({"machine":machine,"tick":int(tick),
                "caller":"0x71%08x"%int(caller,16),"state":int(state),"frames":int(frames),"name":name,
                "executed":int(executed)})
        elif line.startswith("FOCUS,") and current is not None:
            _,focus_tick,focus_path=line.split(",",2)
            current["focus"]={"tick":int(focus_tick),"path":focus_path}
        elif line.startswith("SLOTS,") and current is not None:
            try: current["slots"]=[int(v) for v in line.split(",")[1:]]
            except ValueError as e: current=None; errors.append(str(e))
        elif line.startswith("END,") and current is not None:
            try:
                if int(line.split(",")[1])!=current["sequence"] or len(current["rows"])!=current["expected_rows"]:
                    raise ValueError("incomplete sample")
                samples.append(current)
            except (ValueError, IndexError) as e: errors.append(str(e))
            current=None
    return samples, errors, current is not None

def read_log(path):
    path=Path(path)
    try:
        with path.open("rb") as file:
            header=file.readline(128).decode("ascii",errors="replace").strip()
            if not header.startswith(HEADER) or header[len(HEADER):] not in ("capture","print"):
                return {"status":"unsupported-schema", "path":str(path)}
            file.seek(0,2); size=file.tell()
            file.seek(max(0,size-2*1024*1024))
            tail=file.read(2*1024*1024).decode("ascii",errors="replace")
        age=max(0,time.time()-path.stat().st_mtime)
    except FileNotFoundError: return {"status":"unavailable", "path":str(path)}
    machines={}
    samples,errors,partial=parse_samples(tail,machines)
    return {"status":"stale" if age>3 else "observed" if samples else "waiting",
        "provenance":"experimental draw-call window; not a current-screen snapshot",
        "file_age_s":round(age,3), "partial_tail":partial,"decode_errors":errors,
        "sample":dict(samples[-1],machines=machines) if samples else None}

SCREEN_HALF_W, SCREEN_HALF_H = 640, 360

# Controller glyphs in the system font's private-use area. The block runs
# A B X Y L R from U+E0E0; checked on screen: E0E3 = Y (pause menu "Mario's
# Moves"), E0E4 = L and E0E5 = R (title "Press L + R"). Other private-use
# characters stay as [U+XXXX] until a screen shows what they are.
GLYPHS = {0xE0E0: "A", 0xE0E1: "B", 0xE0E2: "X", 0xE0E3: "Y", 0xE0E4: "L", 0xE0E5: "R"}

def readable(text):
    """Text with controller glyphs as [A], [L], ... and unknown ones as [U+XXXX]."""
    return "".join(f"[{GLYPHS[ord(c)]}]" if ord(c) in GLYPHS
                   else f"[U+{ord(c):04X}]" if 0xE000 <= ord(c) <= 0xF8FF else c for c in text)

def under(path, focus_path):
    """True when the pane path runs through every component of the focus path, in order."""
    parts=iter(path.split("/"))
    return all(any(p==want for p in parts) for want in focus_path.strip("/").split("/"))

def screen(sample):
    """The rows a player can see, with the focused control marked.

    Global position is the pane's global matrix translation (pane+0x7C,
    +0x8C; 1280x720 with the origin at the centre). Panes outside that box
    were still drawn (the Coursebot details panel draws below the screen
    before it slides in), so they are dropped.

    Focus is the game's: the mod records the pane path of the last button
    the game focused (sub_7101B615E0), and the focused rows are the text
    panes drawn under that path; with repeats, the last drawn (topmost).
    ui2d draws back to front, so the rows drawn before the focused
    control's layout (its topmost ancestor) are marked background. Rows from
    an older tick than the newest are dropped: they were not drawn in the
    latest frame.
    """
    newest=max((r["tick"] for r in sample["rows"]),default=0)
    focus_path=(sample.get("focus") or {}).get("path")
    rows=[]
    for r in sample["rows"]:
        g=r["geom"]; x,y,sx=g[19],g[23],g[16]
        if abs(x)>SCREEN_HALF_W or abs(y)>SCREEN_HALF_H or r["tick"]!=newest: continue
        path=r["path"]+"/"+r["pane_name"]
        rows.append({"root":r["root"],"order":r["order"],"path":path,"text":r["text"],"x":x,"y":y,
            "scale":sx,"focused":bool(focus_path) and under(path,focus_path)})
    rows.sort(key=lambda r:r["order"])
    focused=[r for r in rows if r["focused"]]
    focus=focused[-1] if focused else None
    for r in rows: r["focused"]=r is focus
    start=min((r["order"] for r in rows if focus and r["root"]==focus["root"]),default=0)
    for r in rows: r["background"]=r["order"]<start
    # The recorded focus is live while its layout is drawn. An empty Coursebot
    # tile draws no text, and a row of empty tiles none at all, so any drawn
    # instance of the layout counts (L_CourseDataList_02 by L_CourseDataList_01).
    live=False
    if focus_path:
        layout=re.sub(r"_\d+$","_",focus_path.strip("/").split("/")[0])
        live=any(c.startswith(layout) for r in rows for c in r["path"].split("/"))
    # Coursebot tile "/L_CourseDataList_0R/L_CourseBtn_0C" is entry 4R+C of the
    # game's tile table; the mod records the slot the game bound to each (-1
    # once the game empties the tile). An empty tile has no slot of its own:
    # it is taken from a bound tile of the same row, a row being 4 slots.
    # (The game binds empty slots too, so this is rarely needed.)
    slot=slot_source=None
    m=live and re.search(r"L_CourseDataList_0(\d)/L_CourseBtn_0(\d)",focus_path)
    slots=sample.get("slots") or []
    if m and len(slots)>=20:
        row_,col=int(m.group(1)),int(m.group(2))
        if slots[4*row_+col]>=0: slot,slot_source=slots[4*row_+col],"bound"
        else:
            bound=[(c,slots[4*row_+c]) for c in range(4) if slots[4*row_+c]>=0]
            if bound: slot,slot_source=bound[0][1]-bound[0][0]+col,"row"
    for r in rows: r["readable"]=readable(r["text"])
    return {"menu":menu_state(sample),"course_slot":slot,"course_slot_source":slot_source,"rows":rows,"focused":focus,
        "focus_path":focus_path if live else None,
        "active":[r for r in rows if not r["background"]]}

# A machine is named by a state only it has (the game's own names).
MACHINE_LABELS = [("cTitleBack","main_menu"), ("cToCourseRobot","main_menu_flow"),
    ("cOpenConfirmDelete","coursebot_list"), ("cConfirmClearCheck","coursebot_upload_flow"),
    ("cConfirmFirstPlay","coursebot_play_flow"), ("cYesBtn","yes_no_dialog"),
    ("cRetryCourse","pause_menu"), ("cPausePlay","play_scene"), ("cLoadEnd","loader"),
    ("cDecodeEnd","decoder"), ("cDragScroll","scroll")]
TRANSITIONS = ("cAppear","cReadyAppear","cDisappear","cDisapear","cDisappearWait","cActivate",
    "cInactivate","cHalfwayReentry","cLoadWait","cLoad","cDecodeWait","cDecode")

def label(names, machine):
    for state,name in MACHINE_LABELS:
        if state in names: return name
    return "machine@"+machine[-6:]

def menu_state(sample):
    """The menu screens' own state machines: which are running, and whether input lands.

    Each row is one Lp::Utl::StateMachine the mod saw change state, with the
    state it is in and how long. A machine is running when the game executed
    it in the last 30 frames (a dormant one keeps its last state).
    `ready` is True when some running screen is in a Disp* state (the game
    shows it and handles input) and none is in a transition (Appear,
    Disappear, Open*, Close*, To*, a load or decode).
    """
    now=sample.get("tick",0)
    machines=sample.get("machines") or {}
    out=[]
    for m in sample.get("states") or []:
        running=now-m["executed"]<30
        name=m["name"]
        kind=("input" if name.startswith("cDisp") else
              "transition" if name in TRANSITIONS or name.startswith(("cOpen","cClose","cTo")) else "other")
        out.append({"screen":label(machines.get(m["machine"],[]),m["machine"]),"state":name[1:] if name.startswith("c") else name,
            "frames":m["frames"],"running":running,"kind":kind,"machine":m["machine"]})
    live=[m for m in out if m["running"]]
    ready=any(m["kind"]=="input" for m in live) and not any(m["kind"]=="transition" for m in live)
    return {"ready":ready,"screens":sorted(live,key=lambda m:m["frames"]),
        "transitions":[f'{m["screen"]}:{m["state"]}' for m in live if m["kind"]=="transition"]}

def compact(view):
    """The active layer as an agent needs it: texts, the focused one, the slot."""
    f=view["focused"]
    return {"focused":readable(f["text"]) if f else None,"focused_path":f["path"] if f else None,
        # the game's last focused button while its layout is drawn (a menu
        # that just opened focuses nothing, and the path is then stale)
        "focus_path":view["focus_path"],"course_slot_source":view["course_slot_source"],
        "ready":view["menu"]["ready"],"transitions":view["menu"]["transitions"],
        "screens":[f'{m["screen"]}:{m["state"]}' for m in view["menu"]["screens"]],
        "course_slot":view["course_slot"],"texts":[readable(r["text"]) for r in view["active"]],
        "background_texts":sum(r["background"] for r in view["rows"])}

def observe(path, after=None, timeout=2.0):
    """The newest complete sample, waiting for one written after sample `after`.

    A press shows up in the next sample at the earliest (the mod writes one
    every 30 frames), so callers pass the sequence they saw before pressing.
    """
    deadline=time.time()+timeout
    while True:
        result=read_log(path); sample=result.get("sample")
        fresh=sample and (after is None or sample["sequence"]>after+1)
        if fresh or time.time()>=deadline:
            if not sample: return {"status":result["status"],"path":str(path)}
            out=compact(screen(sample)); out.update(status=result["status"] if fresh else "not-updated",
                sequence=sample["sequence"])
            return out
        time.sleep(0.1)

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path",type=Path,help="SD smm2-hooks/ui-probe.log")
    parser.add_argument("--json",action="store_true")
    parser.add_argument("--screen",action="store_true",help="on-screen rows and the focused control")
    args=parser.parse_args(); result=read_log(args.path)
    if args.screen and result.get("sample"):
        view=screen(result["sample"])
        if args.json: print(json.dumps(view,ensure_ascii=False,indent=2)); return
        for r in view["rows"]:
            mark=">" if r["focused"] else "." if r["background"] else " "
            print(f"{mark} {r['text']!r}  [{r['path']}]")
        if view["course_slot"] is not None: print(f"course slot {view['course_slot']}")
        return
    if args.json: print(json.dumps(result,ensure_ascii=True,indent=2)); return
    print(result["status"]+": "+result.get("provenance",str(args.path)))
    sample=result.get("sample")
    if sample:
        print(f"window {sample['sequence']}, dropped {sample['dropped']}")
        for row in sample["rows"]:
            print(f"{row['path']}/{row['pane_name']}: {json.dumps(row['text'],ensure_ascii=False)}" + (" [truncated]" if row['truncated'] else ""))
if __name__=="__main__": main()
