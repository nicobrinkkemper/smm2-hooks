#!/usr/bin/env python3
"""Read the experimental UI probe log. This never sends game input.

These are sampled draw submissions, not an active-menu/focus API. Raw text
can contain formatting tags and controller glyphs; retain it for research.
"""
import argparse
import json
from pathlib import Path
import struct
import time

HEADER = "UI_PROBE,3,303,draw_submission,mode="

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

def parse_samples(text):
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
    samples,errors,partial=parse_samples(tail)
    return {"status":"stale" if age>3 else "observed" if samples else "waiting",
        "provenance":"experimental draw-call window; not a current-screen snapshot",
        "file_age_s":round(age,3), "partial_tail":partial,"decode_errors":errors,
        "sample":samples[-1] if samples else None}

SCREEN_HALF_W, SCREEN_HALF_H = 640, 360

def screen(sample):
    """The rows a player can see, with the focused control marked.

    Global position is the pane's global matrix translation (pane+0x7C,
    +0x8C; 1280x720 with the origin at the centre). Panes outside that box
    were still drawn (the Coursebot details panel draws below the screen
    before it slides in), so they are dropped. Focus is the button whose
    global scale is above 1: the game's focus animation enlarges the focused
    control (1.03 dialog and details buttons, 1.05 course tiles, 1.08 main
    menu, measured 2026-09-28); nothing else on those screens was scaled up.

    Panes under a modal keep drawing (the grid behind the details panel, the
    details behind a dialog). ui2d draws back to front, so the rows drawn
    before the focused control's layout (its topmost ancestor) are marked
    background; the rest are the active layer. Rows from an older tick than
    the newest are dropped: they were not drawn in the latest frame.
    """
    newest=max((r["tick"] for r in sample["rows"]),default=0)
    rows=[]
    for r in sample["rows"]:
        g=r["geom"]; x,y,sx=g[19],g[23],g[16]
        if abs(x)>SCREEN_HALF_W or abs(y)>SCREEN_HALF_H or r["tick"]!=newest: continue
        rows.append({"root":r["root"],"order":r["order"],"path":r["path"]+"/"+r["pane_name"],
            "text":r["text"],"x":x,"y":y,"scale":sx,"focused":sx>1.001})
    rows.sort(key=lambda r:r["order"])
    focused=[r for r in rows if r["focused"]]
    focus=focused[0] if len(focused)==1 else None
    start=min((r["order"] for r in rows if focus and r["root"]==focus["root"]),default=0)
    for r in rows: r["background"]=r["order"]<start
    return {"rows":rows,"focused":focus,"focus_candidates":len(focused),
        "active":[r for r in rows if not r["background"]]}

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
        return
    if args.json: print(json.dumps(result,ensure_ascii=True,indent=2)); return
    print(result["status"]+": "+result.get("provenance",str(args.path)))
    sample=result.get("sample")
    if sample:
        print(f"window {sample['sequence']}, dropped {sample['dropped']}")
        for row in sample["rows"]:
            print(f"{row['path']}/{row['pane_name']}: {json.dumps(row['text'],ensure_ascii=False)}" + (" [truncated]" if row['truncated'] else ""))
if __name__=="__main__": main()
