# Function probes (`probe.txt` → `probe.log`)

Eden's GDB stub has no hardware breakpoints, and a paused game cannot be
traced. A probe is the mod's replacement: it hooks a function at boot, lets
it run unchanged, and appends one row per call with the integer argument
registers and any fields you ask for behind `x0`. The game keeps running at
full speed; the result is a CSV that `tests/bridge` in the decomp can replay.

## Files

| Path (SD card) | Role |
|---|---|
| `sd:/smm2-hooks/probe.txt` | config, read **once at boot** (relaunch after editing) |
| `sd:/smm2-hooks/probe.log` | output, truncated at boot, flushed every 300 frames and when its 8 KB buffer fills |

Host side: `tools/probe.py` (`preset`, `check`, `install --target eden`,
`decode`).

## Config format

```
# comment
hook  <name> <0x71 address> [every=N]
field <hook-name> <label> <type> <path>
```

- `hook`: a function start from `functions.csv`. Up to 8. `every=N` logs one
  call in N.
- `field`: read after the call, relative to the hook's `x0`. Up to 16 per
  hook. `type` is `u8 u16 u32 u64 f32`. `path` is hex offsets joined by `>`;
  every step but the last dereferences a pointer: `0x230` is `*(x0+0x230)`,
  `0x530>0x28` is `*(*(x0+0x530)+0x28)`. Depth 4 max.

`python3 tools/probe.py preset rail` prints the RailMover trace config
(block rail applier `sub_710138C520`, mover fields from the decomp's
`docs/re-notes/rail-follower.md`).

## Rules

- **First instruction must not be PC-relative.** hakkun's trampoline copies
  the function's first instruction into the backup verbatim; `adrp`, `b`,
  `bl`, `b.cond`, `cbz`, `tbz` and literal loads would execute from the wrong
  address. `probe.py check` reads the word from `main.elf` and refuses those.
  Normal prologues (`stp`, `sub sp`, `str x19, [sp, #-0x20]!`) are fine.
- **Hook functions that do not return a float.** The probe runs after the
  original and formats text; that can clobber `s0`. Integer/pointer/void
  returns are passed back unchanged (`x0`).
- **A wrong path can crash the game.** Pointers are range-checked
  (`0x8000000 .. 0x8000000000`, aligned) but not for mapping. A field that
  fails the check logs `-`; one that passes and points into an unmapped page
  faults the guest.
- Hooks are installed at boot on the main module; a `failed` status in the
  `H` line means the address was outside it or the trampoline pool is full.

## Log format

```
V,1
H,<idx>,<name>,<vaddr>,<ok|failed>,<label:type>,...
R,<frame>,<idx>,<x0>,...,<x7>,<field>,...        hex; `-` = unreadable
E,<message>                                       config errors
```

`python3 tools/probe.py decode probe.log -o rail.csv` joins the `H` line's
types with the rows and writes `frame,hook,x0..x7,<labels>` with floats
decoded. The `frame` column is the mod's frame counter (same as
`status.bin`).

## Workflow (RailMover example)

```
python3 tools/probe.py preset rail > probe.txt
python3 tools/probe.py install probe.txt --target eden   # runs `check` first
python3 tools/gen_test_levels.py --slot 11 --target eden   # "Rail Trace" (unvalidated: validate_slots first)
# launch Eden, play the level, quit
python3 tools/probe.py decode <sd>/smm2-hooks/probe.log -o rail_trace.csv
```

The CSV is the oracle for the decomp's `tests/bridge/test_rail_mover_replay.py`:
the reference model there must reproduce every frame.
