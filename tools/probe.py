#!/usr/bin/env python3
"""Function probes for the smm2-hooks mod (docs/probe.md).

    python3 probe.py preset rail > probe.txt        # the RailMover trace
    python3 probe.py check probe.txt                # refuse addresses the trampoline cannot hook
    python3 probe.py install probe.txt --target eden
    python3 probe.py decode probe.log -o rail.csv   # typed CSV (floats decoded)

The mod reads sd:/smm2-hooks/probe.txt once at boot and appends rows to
sd:/smm2-hooks/probe.log. `check` reads the first instruction of every
hooked function from the decomp's main.elf: hakkun's trampoline copies that
instruction verbatim, so it must not be PC-relative.
"""
from __future__ import annotations

import argparse
import csv
import os
import struct
import sys
from pathlib import Path

MAIN_BASE = 0x7100000000
HERE = Path(__file__).resolve().parent
DECOMP = Path(os.environ.get("SMM2_DECOMP", HERE.parent.parent / "smm2-decomp"))
ELF = DECOMP / "data/v3.0.3/main.elf"
FUNCS = DECOMP / "data/v3.0.3/functions.csv"

MAX_FIELDS = 24  # keep in step with src/probe.cpp

PRESETS = {
    # The note block's per-frame rail applier; x0 = the block. Field paths are
    # from docs/re-notes/rail-follower.md in smm2-decomp (rider at +0x530,
    # RailMover at rider+8, StateMachine at rider+0xd8).
    "rail": """\
# RailMover trace: hook the block rail applier, read the mover behind Block+0x530
hook rail 0x710138C520
field rail pos_x   f32 0x230
field rail pos_y   f32 0x234
field rail mv_x    f32 0x530>0x28
field rail mv_y    f32 0x530>0x2c
field rail vel_x   f32 0x530>0x10
field rail vel_y   f32 0x530>0x14
field rail tgt_x   f32 0x530>0x60
field rail tgt_y   f32 0x530>0x64
field rail heading u32 0x530>0x88
field rail mode    u32 0x530>0x94
field rail axis    u32 0x530>0x98
field rail speed   f32 0x530>0xc8
field rail state   u32 0x530>0xe0
field rail counter u32 0x530>0xe4
field rail attached u8 0x530>0x120
# the camera's view slot 0 (global 0x7102C55080, views at +0x88): left x and the activation box's right edge
field rail view_l  f32 @0x7102C55080>0x88>0x0c
field rail act_r   f32 @0x7102C55080>0x88>0x5c
""",
    # The player's per-frame horizontal movement (sub_71015D3CC0, x0 = the
    # player actor). Per-frame and tear-free, unlike the polled status.bin
    # samples. vel_y offset confirmed by the gravity selector
    # (sub_71015D25F0 reads player+0x240).
    "player": """\
# Player trace: hook the horizontal movement step, x0 = player
hook player 0x71015D3CC0
field player pos_x f32 0x230
field player pos_y f32 0x234
field player vel_x f32 0x23C
field player vel_y f32 0x240
field player grav  f32 0x640
""",
}


# ── ELF ───────────────────────────────────────────────────────────────────

def _segments(data: bytes):
    phoff = struct.unpack_from("<Q", data, 0x20)[0]
    phentsize = struct.unpack_from("<H", data, 0x36)[0]
    phnum = struct.unpack_from("<H", data, 0x38)[0]
    for i in range(phnum):
        typ, _flags, off, vaddr, _paddr, filesz, _memsz = struct.unpack_from("<IIQQQQQ", data, phoff + i * phentsize)
        if typ == 1:
            yield vaddr, off, filesz


def read_word(vaddr: int) -> int:
    data = ELF.read_bytes()
    rel = vaddr - MAIN_BASE
    for seg_va, off, size in _segments(data):
        if seg_va <= rel < seg_va + size:
            return struct.unpack_from("<I", data, off + rel - seg_va)[0]
    raise ValueError(f"{vaddr:#x} not in main.elf")


def pc_relative(word: int) -> str | None:
    """Name of the PC-relative instruction class, or None."""
    if (word & 0x1F000000) == 0x10000000:
        return "adr/adrp"
    if (word & 0x7C000000) == 0x14000000:
        return "b/bl"
    if (word & 0xFF000010) == 0x54000000:
        return "b.cond"
    if (word & 0x7E000000) in (0x34000000, 0x36000000):
        return "cbz/cbnz/tbz/tbnz"
    if (word & 0x3B000000) == 0x18000000:
        return "ldr (literal)"
    return None


def function_name(vaddr: int) -> str:
    if not FUNCS.exists():
        return "?"
    with FUNCS.open() as f:
        for row in csv.DictReader(f):
            a, size = int(row["Address"], 16), int(row["Size"])
            if a <= vaddr < a + size:
                return row["Name"] + ("" if a == vaddr else f"+{vaddr - a:#x}")
    return "?"


# ── config ────────────────────────────────────────────────────────────────

def parse_config(text: str):
    hooks, fields = [], []
    for ln, raw in enumerate(text.splitlines(), 1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        parts = line.split()
        if parts[0] == "hook" and len(parts) >= 3:
            hooks.append({"line": ln, "name": parts[1], "vaddr": int(parts[2], 16), "opts": parts[3:]})
        elif parts[0] == "field" and len(parts) == 5:
            fields.append({"line": ln, "hook": parts[1], "label": parts[2], "type": parts[3], "path": parts[4]})
        else:
            raise SystemExit(f"probe.txt:{ln}: cannot parse: {raw}")
    return hooks, fields


def cmd_check(args) -> int:
    hooks, fields = parse_config(Path(args.config).read_text())
    if len(hooks) > 8:
        print(f"too many hooks: {len(hooks)} (max 8)")
        return 1
    rc = 0
    names = {h["name"] for h in hooks}
    for h in hooks:
        try:
            word = read_word(h["vaddr"])
        except ValueError as e:
            print(f"line {h['line']}: {e}")
            rc = 1
            continue
        kind = pc_relative(word)
        fn = function_name(h["vaddr"])
        if kind:
            print(f"line {h['line']}: {h['name']} {h['vaddr']:#x} ({fn}): first instruction {word:08x} is {kind}; the trampoline cannot relocate it")
            rc = 1
        elif "+" in fn:
            print(f"line {h['line']}: {h['name']} {h['vaddr']:#x} is {fn}: not a function start")
            rc = 1
        else:
            print(f"ok   {h['name']} {h['vaddr']:#x} {fn} first word {word:08x}")
    per_hook: dict[str, int] = {}
    for f in fields:
        if f["hook"] not in names:
            print(f"line {f['line']}: field {f['label']}: unknown hook {f['hook']}")
            rc = 1
        if f["type"] not in ("u8", "u16", "u32", "u64", "f32"):
            print(f"line {f['line']}: field {f['label']}: bad type {f['type']}")
            rc = 1
        steps = f["path"].split(">")
        if len(steps) > 4:
            print(f"line {f['line']}: field {f['label']}: path deeper than 4")
            rc = 1
        try:
            [int(s[1:] if i == 0 and s.startswith("@") else s, 16) for i, s in enumerate(steps)]
        except ValueError:
            print(f"line {f['line']}: field {f['label']}: bad path {f['path']}")
            rc = 1
        per_hook[f["hook"]] = per_hook.get(f["hook"], 0) + 1
    for name, n in per_hook.items():
        if n > MAX_FIELDS:
            print(f"hook {name}: {n} fields (max {MAX_FIELDS})")
            rc = 1
    return rc


def sd_hooks_dir(target: str) -> Path:
    if target != "eden":
        raise SystemExit("only --target eden is known")
    sys.path.insert(0, str(HERE.parent / "mcp"))
    import eden  # type: ignore

    return Path(eden.paths().sd_hooks_dir)


def cmd_install(args) -> int:
    if cmd_check(args):
        return 1
    dst = sd_hooks_dir(args.target) / "probe.txt"
    dst.write_bytes(Path(args.config).read_bytes())
    print(f"installed {dst} (read by the mod at the next launch)")
    return 0


def cmd_preset(args) -> int:
    sys.stdout.write(PRESETS[args.name])
    return 0


# ── decode ────────────────────────────────────────────────────────────────

def decode_value(hexval: str, typ: str):
    if hexval == "-":
        return ""
    v = int(hexval, 16)
    if typ == "f32":
        return struct.unpack("<f", struct.pack("<I", v & 0xFFFFFFFF))[0]
    return v


def cmd_decode(args) -> int:
    hooks: dict[int, dict] = {}
    rows = []
    for raw in Path(args.log).read_text().splitlines():
        parts = raw.split(",")
        if parts[0] == "H":
            idx = int(parts[1])
            fields = [p.split(":") for p in parts[5:]]
            hooks[idx] = {"name": parts[2], "vaddr": int(parts[3], 16), "status": parts[4], "fields": fields}
        elif parts[0] == "R":
            rows.append(parts)
        elif parts[0] == "E":
            print("mod error:", ",".join(parts[1:]), file=sys.stderr)
    if not hooks:
        print("no H lines: the mod did not read a probe.txt", file=sys.stderr)
        return 1
    for idx, h in hooks.items():
        if h["status"] != "ok":
            print(f"hook {h['name']} {h['vaddr']:#x}: install {h['status']}", file=sys.stderr)
    out = open(args.out, "w", newline="") if args.out else sys.stdout
    w = csv.writer(out)
    labels = sorted({lab for h in hooks.values() for lab, _ in h["fields"]})
    w.writerow(["frame", "hook"] + [f"x{i}" for i in range(8)] + labels)
    for parts in rows:
        idx = int(parts[2])
        h = hooks.get(idx)
        if not h:
            continue
        regs = [f"0x{int(x, 16):x}" for x in parts[3:11]]
        vals = {lab: decode_value(hv, typ) for (lab, typ), hv in zip(h["fields"], parts[11:])}
        w.writerow([int(parts[1]), h["name"]] + regs + [vals.get(lab, "") for lab in labels])
    if args.out:
        out.close()
        print(f"wrote {args.out}: {len(rows)} rows, hooks {[h['name'] for h in hooks.values()]}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("check", help="validate a probe.txt against main.elf")
    p.add_argument("config")
    p.set_defaults(fn=cmd_check)
    p = sub.add_parser("install", help="check, then copy probe.txt to the emulator's SD hooks dir")
    p.add_argument("config")
    p.add_argument("--target", default="eden")
    p.set_defaults(fn=cmd_install)
    p = sub.add_parser("preset", help="print a ready-made probe.txt")
    p.add_argument("name", choices=sorted(PRESETS))
    p.set_defaults(fn=cmd_preset)
    p = sub.add_parser("decode", help="probe.log -> typed CSV")
    p.add_argument("log")
    p.add_argument("-o", "--out")
    p.set_defaults(fn=cmd_decode)
    args = ap.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
