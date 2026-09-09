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
    # the bounce sub_7101290900 (slot 63) the frame the impulse lands.
    "dossun": """\
# Thwomp (GameEnemyDossun, vtable 0x71028C6B28): which virtual runs per frame
# with x0 = the actor. Candidates: +0x38/+0x40 (EnemyUber's), the Dossun
# overrides +0x18/+0x20/+0x58.
hook v38 0x710128A090
field v38 pos_x  f32 0x230
field v38 pos_y  f32 0x234
field v38 vel_y  f32 0x240
field v38 st     u32 0x400
hook v40 0x710128A2D0
field v40 pos_x  f32 0x230
field v40 pos_y  f32 0x234
field v40 vel_y  f32 0x240
field v40 st     u32 0x400
hook v18 0x71010CC0C0
field v18 pos_x  f32 0x230
field v18 pos_y  f32 0x234
hook v20 0x71010CC130
field v20 pos_x  f32 0x230
field v20 pos_y  f32 0x234
hook v58 0x71010CC1B0
field v58 pos_x  f32 0x230
field v58 pos_y  f32 0x234
field v58 vel_y  f32 0x240
# Note-block hit registered on the enemy (x0 = enemy)
hook resp 0x710128CD40
field resp pos_x   f32 0x230
field resp pos_y   f32 0x234
field resp f524    u32 0x524
# The enemy's bounce off the block (x0 = enemy); who calls it
hook bounce 0x7101290900 callers=2
field bounce pos_x f32 0x230
field bounce pos_y f32 0x234
field bounce vel_y f32 0x240
field bounce f658  u32 0x658
""",
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
    # The camera beside the player: hook the player's movement step and read
    # view slot 0 of the camera global (docs/re-notes/camera-follow.md in
    # smm2-decomp): left/bottom/right/top at +0x0C..+0x18, centre at +0x1C,
    # activation box at +0x54..+0x60; facing = player+0x26C (0 right, 1 left).
    "camera": """\
# Camera trace: hook the player's horizontal movement step (per frame, x0 =
# player) and read the area's camera view beside it. View slot 0 of the
# camera global 0x7102C55080 (+0x88 holds the view pointers; activation.md):
# the spawner reads +0x0C..+0x18 as left, bottom, right, top.
hook cam 0x71015D3CC0
field cam pos_x  f32 0x230
field cam pos_y  f32 0x234
field cam vel_x  f32 0x23C
field cam vel_y  f32 0x240
field cam st_e   u32 0x400
field cam facing u32 0x26C
field cam left   f32 @0x7102C55080>0x88>0x0c
field cam bottom f32 @0x7102C55080>0x88>0x10
field cam right  f32 @0x7102C55080>0x88>0x14
field cam top    f32 @0x7102C55080>0x88>0x18
field cam half_w f32 @0x7102C55080>0x88>0x1c
field cam half_h f32 @0x7102C55080>0x88>0x20
field cam v24    f32 @0x7102C55080>0x88>0x24
field cam v28    f32 @0x7102C55080>0x88>0x28
field cam v2c    f32 @0x7102C55080>0x88>0x2c
field cam v30    f32 @0x7102C55080>0x88>0x30
field cam v34    f32 @0x7102C55080>0x88>0x34
field cam v38    f32 @0x7102C55080>0x88>0x38
field cam v3c    f32 @0x7102C55080>0x88>0x3c
field cam v40    f32 @0x7102C55080>0x88>0x40
field cam act_l  f32 @0x7102C55080>0x88>0x54
field cam act_r  f32 @0x7102C55080>0x88>0x5c
""",
    # The note block's bound and rider record beside the player (the
    # centred-hit recording in smm2-decomp, docs/re-notes/note-block.md):
    # x0 = the block in the rail applier; the first machine's state word,
    # the bound mode/vy/displacement and the rider record at +0x550.
    "note": """\
# Note block: the bound (+0x478 state, +0x4BC mode, +0x4C0 vy, +0x4CC displacement)
# and the rider record (+0x550: phase, countdown, hit masks, player slot 0)
# beside the player's per-frame movement step.
hook rail 0x710138C520
field rail pos_x   f32 0x230
field rail pos_y   f32 0x234
field rail vel_x   f32 0x530>0x10
field rail state   u32 0x478
field rail b_mode  u32 0x4BC
field rail b_vy    f32 0x4C0
field rail b_disp  f32 0x4CC
field rail r_phase u32 0x550>0x8
field rail r_cnt   u32 0x550>0xC
field rail r_hit   u32 0x550>0x10
field rail r_last  u32 0x550>0x14
field rail r_jump  u32 0x550>0x18
field rail r_on    u32 0x550>0x1C
field rail r_slot0 u32 0x550>0x20
hook player 0x71015D3CC0
field player pos_x f32 0x230
field player pos_y f32 0x234
field player vel_x f32 0x23C
field player vel_y f32 0x240
field player st_e  u32 0x400
""",
    # What an enemy's foot stands on, read from its bg-check object, which is
    # embedded 0x10 into the physics sub-object at actor+0x650 (so every
    # path below is 0x650 > bg offset + 0x10; docs/re-notes/surfaces.md in
    # smm2-decomp): the per-side flags at bg+0x394 (12 per side), the chosen
    # kind slot per side at bg+0x3C4, the slot tables at bg+0x3E8 + 392*side
    # (7 slots of 56 bytes: +0 valid, +0x14/+0x18 the hit point, +0x28 the
    # surface shape, +0x30 its kind word; lifts file under kind slot 2, the
    # terrain under 5, measured 2026-09-09), the attached owner handles at
    # bg+0x330.., the attach list head at bg+0xA0 (= shape + 0x300), the
    # actor's surface ref at +0x338. Through a
    # shape: +0x278 its owner actor, +0x364 its kind word, the owner's
    # position at +0x230. x0 = the enemy (EnemyUber +0x40 per frame). The
    # `lift` hook is the plain Actor per-frame (vtable +0x40 of every actor
    # that does not override it: lifts, blocks, ...), x0 = the actor.
    "surface": """\
hook foot 0x710128A2D0
field foot pos_x   f32 0x230
field foot pos_y   f32 0x234
field foot vel_y   f32 0x240
field foot id      u32 0x40
field foot sref    u64 0x338
field foot bgfl    u32 0x650>0x2C8
field foot sf3     u32 0x650>0x3C8
field foot k3      u32 0x650>0x3E0
field foot v3      u8  0x650>0x890
field foot h3      u64 0x650>0x358
field foot glist   u64 0x650>0xB0
field foot s2hx    f32 0x650>0x914
field foot s2hy    f32 0x650>0x918
field foot s2sh    u64 0x650>0x928
field foot s2kind  u32 0x650>0x928>0x364
field foot s2ox    f32 0x650>0x928>0x278>0x230
field foot s2oy    f32 0x650>0x928>0x278>0x234
field foot sf2     u32 0x650>0x3BC
field foot k2      u32 0x650>0x3DC
field foot v2      u8  0x650>0x708
field foot h2      u64 0x650>0x350
field foot sf0     u32 0x650>0x3A4
field foot k0      u32 0x650>0x3D4
field foot v0      u8  0x650>0x3F8
# The same actor's move step (EnemyUber vtable +0x48): the foot side's seven
# kind slots (valid byte and kind word each) and the wall handles.
hook foot2 0x710128ACC0
field foot2 pos_x  f32 0x230
field foot2 st     u32 0x400
field foot2 h0     u64 0x650>0x340
field foot2 h1     u64 0x650>0x348
field foot2 va0    u8  0x650>0x890
field foot2 va1    u8  0x650>0x8C8
field foot2 va2    u8  0x650>0x900
field foot2 va3    u8  0x650>0x938
field foot2 va4    u8  0x650>0x970
field foot2 va5    u8  0x650>0x9A8
field foot2 va6    u8  0x650>0x9E0
field foot2 kw0    u32 0x650>0x8C0
field foot2 kw1    u32 0x650>0x8F8
field foot2 kw2    u32 0x650>0x930
field foot2 kw3    u32 0x650>0x968
field foot2 kw4    u32 0x650>0x9A0
field foot2 kw5    u32 0x650>0x9D8
field foot2 kw6    u32 0x650>0xA10
field foot2 sh5    u64 0x650>0x9D0
hook lift 0x71008DB240
field lift pos_x   f32 0x230
field lift pos_y   f32 0x234
field lift id      u32 0x40
field lift h48     u64 0x30
""",
    # A plain piranha plant (GameEnemyPakkun, an EnemyUber): x0 = the actor
    # at its per-frame. The Basic handler sits at actor+0x440 with its own
    # machine at +0x20 (state id at +0x28: 0 None, 1 Wait, 2 Stick, 3 Jump,
    # 4 Floating, 5 Fall, 6 Down, 7 OnpuJump, 8 TornadoFloat); the plant
    # component is embedded at actor+0xD20 (+8 direction 0..3, +0x18 timer);
    # speed +0x274, accel +0x280, wait timer +0x53C; the foot's chosen kind
    # slot and owner handle from the bg-check object (surfaces.md).
    # The actor manager's per-frame walk (docs/re-notes/processing-order.md
    # in the decomp): Actor's slot-8 base sub_71008D7C70 runs once per actor
    # per frame in execution order (every class chains to it: the player's
    # sub_710158A3F0, EnemyUber's sub_710128A2D0, the lifts' sub_71008DB240),
    # and lr0 names the override that called it. The order pass
    # sub_7100D5F1F0 (x0 = the manager item) closes each frame's group.
    "order": """\
hook calc 0x71008D7C70 callers=1
field calc id    u32 0x40
field calc pos_x f32 0x230
field calc pos_y f32 0x234
field calc vt    u64 0x0
field calc h30   u64 0x30
hook walk 0x7100D5F1F0
field walk item  u32 0x20
field walk nact  u32 0x88
field walk nord  u32 0xD8
field walk ysort u8  0x138
field walk thr   u32 0x148
field walk nring u32 0x160
""",
    # The placeholder (docs/re-notes/placeholder.md in the decomp): every
    # enemy's per-frame with its activation flags (+0x52C: 0x20000 offscreen,
    # 0x40000 activated), the ground-contact activation bit (+0x658 bit 29),
    # its record link (+0x4E4) and the owner handle of the body under its
    # foot; the lifts with their own link (+0x350); the surface walk that
    # sets the activation bit, with who called it.
    "placeholder": """\
hook enemy 0x710128A2D0
field enemy id    u32 0x40
field enemy pos_x f32 0x230
field enemy pos_y f32 0x234
field enemy vel_y f32 0x240
field enemy f52C  u32 0x52C
field enemy f658  u64 0x658
field enemy link  u32 0x4E4
field enemy own   u32 0x350
field enemy h30   u64 0x30
field enemy bgown u64 0x650>0x358
field enemy sysst u32 0x400
hook lift 0x71008DB240
field lift id    u32 0x40
field lift pos_x f32 0x230
field lift pos_y f32 0x234
field lift own   u32 0x350
field lift h30   u64 0x30
hook activate 0x7100D81E60 callers=2
field activate id    u32 0x40
field activate pos_x f32 0x230
field activate pos_y f32 0x234
""",
    "plant": """\
hook plant 0x710128A2D0
field plant pos_x   f32 0x230
field plant pos_y   f32 0x234
field plant vel_x   f32 0x23C
field plant vel_y   f32 0x240
field plant id      u32 0x40
field plant sysst   u32 0x400
field plant hst     u32 0x440>0x28
field plant dir     u32 0xD28
field plant ctimer  u32 0xD38
field plant speed   f32 0x274
field plant accel   f32 0x280
field plant wait    u32 0x53C
field plant f520    u32 0x520
field plant f524    u32 0x524
field plant f530    u32 0x530
field plant f658    u32 0x658
field plant bgfl    u32 0x650>0x2C8
field plant k3      u32 0x650>0x3E0
field plant h3      u64 0x650>0x358
field plant s2kind  u32 0x650>0x928>0x364
field plant s5kind  u32 0x650>0x9D0>0x364
# The Dokan handler (system state 5) at actor+0x468: its machine's state at +0x28, its wait count at +0x84
field plant dst     u32 0x468>0x28
field plant dwait   u32 0x468>0x84
field plant f523    u8  0x523
# The player as the pipe's near check sees it, and the pipe itself at that
# check (sub_71012AA800: x0 = the pipe actor; pos = the mouth's centre)
hook player 0x71015D3CC0
field player pos_x f32 0x230
field player pos_y f32 0x234
field player vel_x f32 0x23C
field player vel_y f32 0x240
field player st_e  u32 0x400
hook pipe 0x71012AA800
field pipe pos_x f32 0x230
field pipe pos_y f32 0x234
field pipe dir   u32 0x26C
hook lift 0x71008DB240
field lift pos_x   f32 0x230
field lift pos_y   f32 0x234
field lift id      u32 0x40
field lift h48     u64 0x30
""",
    "player": """\
# Player trace: hook the horizontal movement step, x0 = player
hook player 0x71015D3CC0
field player pos_x f32 0x230
field player pos_y f32 0x234
field player vel_x f32 0x23C
field player vel_y f32 0x240
field player grav  f32 0x640
# The state machine is embedded at PlayerObject+0x3F0 (confirmed-states.md):
# the current state id at +0x3F8, its frame counter at +0x3FC, and the
# previous state id at +0x400. Recordings made before 2026-09-03 carried
# +0x400 as "st_e": read those as the previous state.
field player state  u32 0x3F8
field player stfr   u32 0x3FC
field player prev   u32 0x400
# The pad object at player+0x550 (the gravity selector reads +22/+30 to
# pick the held table): a spread of its bytes around those flags.
field player pad14 u8 0x550>0x14
field player pad15 u8 0x550>0x15
field player pad16 u8 0x550>0x16
field player pad17 u8 0x550>0x17
field player pad1c u8 0x550>0x1C
field player pad1d u8 0x550>0x1D
field player pad1e u8 0x550>0x1E
field player pad1f u8 0x550>0x1F
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
            [int(s.lstrip("@") if i == 0 and s.startswith("@") else s, 16) for i, s in enumerate(steps)]
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


PAD_COLUMNS = ["pad_buttons", "pad_lx", "pad_ly"]


def parse_log(text: str):
    """The mod's probe.log: hooks by index, R rows, and the pad by frame (P rows)."""
    hooks: dict[int, dict] = {}
    rows = []
    pad: dict[int, tuple[int, int, int]] = {}
    errors = []
    for raw in text.splitlines():
        parts = raw.split(",")
        if parts[0] == "H":
            idx = int(parts[1])
            fields = [p.split(":") for p in parts[5:]]
            hooks[idx] = {"name": parts[2], "vaddr": int(parts[3], 16), "status": parts[4], "fields": fields}
        elif parts[0] == "R":
            rows.append(parts)
        elif parts[0] == "P" and len(parts) >= 5:
            pad[int(parts[1])] = (int(parts[2], 16), int(parts[3]), int(parts[4]))
        elif parts[0] == "E":
            errors.append(",".join(parts[1:]))
    return hooks, rows, pad, errors


def write_inputs(pad: dict[int, tuple[int, int, int]], path: str) -> int:
    """The pad rows as the mod's own tas.csv script (frame,buttons,stick_lx,
    stick_ly; only the frames where the input changes), replayable by copying
    it to sd:/smm2-hooks/tas.csv. Returns the number of keyframes."""
    n = 0
    with open(path, "w", newline="") as f:
        f.write("frame,buttons,stick_lx,stick_ly\n")
        last = None
        for frame in sorted(pad):
            cur = pad[frame]
            if cur == last:
                continue
            f.write(f"{frame},0x{cur[0]:x},{cur[1]},{cur[2]}\n")
            last = cur
            n += 1
    return n


def decode_log(log: str, out: str | None, inputs: str | None = None) -> dict:
    hooks, rows, pad, errors = parse_log(Path(log).read_text())
    for e in errors:
        print("mod error:", e, file=sys.stderr)
    if not hooks and not pad:
        raise SystemExit("no H or P lines: the mod did not read a probe.txt and logged no pad")
    for idx, h in hooks.items():
        if h["status"] != "ok":
            print(f"hook {h['name']} {h['vaddr']:#x}: install {h['status']}", file=sys.stderr)
    fh = open(out, "w", newline="") if out else sys.stdout
    w = csv.writer(fh)
    labels = sorted({lab for h in hooks.values() for lab, _ in h["fields"]})
    w.writerow(["frame", "hook"] + [f"x{i}" for i in range(8)] + labels + (PAD_COLUMNS if pad else []))
    for parts in rows:
        idx = int(parts[2])
        h = hooks.get(idx)
        if not h:
            continue
        frame = int(parts[1])
        regs = [f"0x{int(x, 16):x}" for x in parts[3:11]]
        vals = {lab: decode_value(hv, typ) for (lab, typ), hv in zip(h["fields"], parts[11:])}
        padrow = []
        if pad:
            pv = pad.get(frame)
            padrow = [f"0x{pv[0]:x}", pv[1], pv[2]] if pv else ["", "", ""]
        w.writerow([frame, h["name"]] + regs + [vals.get(lab, "") for lab in labels] + padrow)
    if out:
        fh.close()
    keyframes = write_inputs(pad, inputs) if inputs and pad else 0
    return {"rows": len(rows), "hooks": [h["name"] for h in hooks.values()], "pad_frames": len(pad),
            "keyframes": keyframes, "errors": errors}


def cmd_decode(args) -> int:
    r = decode_log(args.log, args.out, args.inputs)
    if args.out:
        print(f"wrote {args.out}: {r['rows']} rows, hooks {r['hooks']}, pad frames {r['pad_frames']}"
              + (f", {r['keyframes']} input keyframes -> {args.inputs}" if args.inputs else ""))
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
    p = sub.add_parser("decode", help="probe.log -> typed CSV (with the pad columns when the mod logged P rows)")
    p.add_argument("log")
    p.add_argument("-o", "--out")
    p.add_argument("--inputs", help="also write the pad as a tas.csv input script (frame,buttons,stick_lx,stick_ly)")
    p.set_defaults(fn=cmd_decode)
    args = ap.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
