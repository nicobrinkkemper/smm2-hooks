---
name: eden-debug
description: Drive a Super Mario Maker 2 debug session in the Eden emulator from WSL — launch Eden on the Windows side with the smm2-hooks mod, boot a test level, attach GDB in a persistent tmux session, find functions under ASLR by byte signature, find actors by vtable scan, set watchpoints, read hits, and tear down cleanly. Use for any runtime question about the game (who writes a field, what a function is called with, actor pointers), for verifying generated test levels in the editor, and whenever the user mentions Eden, GDB, hooks, watchpoints, or "run it in the emulator".
---

# Eden debug session

Prefer the **smm2-hooks MCP tools** (server: `mcp/server.py`, registered in
the agent's project `.mcp.json`, see `mcp/README.md`): `eden_state` is the truth about the emulator
(mode, real config, status, mods, log), `eden_launch/eden_kill`, `game_boot`,
`game_input`, `eden_screenshot`, `levels_list/level_install`, and the GDB tools
(`gdb_attach`, `gdb_continue`, `gdb_interrupt`, `gdb_wait_stop`, `gdb_cmd`,
`gdb_module_base`, `gdb_addr`, `gdb_detach`). The scripts below are what those
tools wrap; use them directly only when the server is not loaded.

Eden runs "portable" here: config and log are in `Documents/eden/user/`,
while NAND, SD and mods stay under `AppData/Roaming/eden` as named in that
config. `emu_session.py` toggles the wrong ini; `eden_state`/`eden_launch`
read and write the right one.

**Modes** (from `eden_state`): `off`; `launching_or_frozen`;
`waiting_for_debugger_or_paused` (stub enabled and listening, no fresh
status: attach and continue); `title`; `editor` (**edit-time**: the Course
Maker, no actors run, `has_player` 0); `editor_play` and `coursebot_play`
(**run-time**: actors update, player exists); `loading`. Only run-time is
worth a breakpoint.

Two things make this fragile, and every step below exists because of them:
Eden bakes software breakpoints into cached code pages (a `break` you forget
loops as SIGTRAP forever, across restarts), and a client attached during a
scene load has killed Eden twice. `docs/tooling-gaps.md` lists the failure
modes.

## Rules (non-negotiable)

- `watch`, `rwatch`, `awatch` only. **Never `break`.** Eden v0.2.0-rc1's stub
  answers EMPTY to `Z1`, so `hbreak` is accepted by GDB and then fails at the
  next continue ("Cannot insert hardware breakpoint ... too many"); to get an
  actor pointer without a breakpoint, scan the actor heap for its vtable
  (recipe in section 6).
- One persistent GDB inside tmux session `eden-gdb`. Never connect with
  `gdb -batch` or a second client; `tools/eden_gdb.py` opens its own socket and is
  only safe when no tmux GDB is attached.
- After every stop: `delete <n>` when done with it, then `c`. The game is
  frozen while GDB sits at the prompt; the status file stops updating.
- Never `handle SIGTRAP ... pass`: Eden's initial stop is a SIGTRAP and passing
  it into the guest on the first continue kills the game (seen 2026-08-27).
- Attach only when the scene you want is already running (run-time), not
  before a Coursebot load; the stub dropped the connection mid-load once.
- No breakpoints while a scene is loading (`scene_mode 0`).
- Narrate each step to the user and stop at the first surprise (unexpected
  scene, SIGTRAP storm, no status updates) instead of pushing through.

## 1. Preflight

    cd tools    # of this checkout
    python3 emu_session.py overview       # processes, hooks deployed?, gdb stub on?, tmux, status.bin
    ip route | awk '/default/ {print $3}' # Windows host IP; must equal EDEN_GDB_HOST in ../.env (edit if not)

If `overview` shows an Eden process or an `eden-gdb` tmux session from an older
run, kill both first: `python3 emu_session.py kill eden` and
`tmux kill-session -t eden-gdb`. If hooks are not deployed:
`ninja -C ../build && python3 emu_session.py deploy eden`.

## 2. Test level (optional)

    python3 gen_test_levels.py --list
    python3 gen_test_levels.py --slot N --target eden    # writes course_data_00N.bcd, backs up the old one

Prefer the MCP tool `level_install(slot, level)`: it also registers the slot.
A Coursebot slot is only kept if three things hold, and the game deletes the
slot on its next Coursebot visit otherwise: `used_flag` set in `save.dat`
(`tools/save_dat.py`), a valid `course_thumb_NNN.btl` and `course_replay_NNN.dat`
beside the `.bcd` (any registered slot's will do, contents need not match),
and a course the game accepts. Two things the game rejects that looked fine
on disk: `goal_x` not in tenths of a tile (the pole stands 9.5 tiles from the
right edge, 255 for a 35-wide course) and an on-track object that is not on
the rail (record `(x, y)` is the bottom-left of a 3x3 box; the rail runs
through its centre; the object starts at `(x + 1.5, y + 1.5)`).

Slot 10 is "Track Note": two joined horizontal pieces with a note block
riding them, for the rail-music work. Adding levels: `LevelBuilder` methods in
`gen_test_levels.py` (`add_track`, `add_note_block_on_track`, ...). Keep
custom content in `x >= 7 && x <= 23` (start and goal areas are auto-generated).

### Let the game judge a course (about a minute, four slots at a time)

    python3 validate_slots.py 5=a.bcd 6=b.bcd 7=c.bcd 8=d.bcd
    # installs each (borrowing thumb+replay from a registered slot), marks them used,
    # restarts Eden, walks title -> editor -> Coursebot, confirms any delete dialogs,
    # then reads save.dat: ACCEPTED / DELETED per slot.

This is the fastest theory-to-game loop there is for course-format questions:
one binary answer per slot per visit, no GDB, no screenshots. Bisect by
building variants of a file the game accepts (e.g. its own re-saved copy of a
slot) and of the one it rejects. Reading the same course in Coursebot play
afterwards (`game_boot`, then a screenshot) confirms geometry.

## 3. Launch and attach

    python3 emu_session.py launch eden --gdb    # sets the stub in qt-config.ini, starts eden.exe
    # With the stub on, Eden waits for a debugger: the guest is PAUSED until a
    # client connects and continues. Give the process ~15 s to come up, then:
    tmux new-session -d -s eden-gdb
    tmux send-keys -t eden-gdb "gdb-multiarch -nx -ex 'target remote $(ip route | awk '/default/ {print $3}'):6543' -ex 'set confirm off' -ex 'set pagination off'" Enter
    sleep 5; tmux send-keys -t eden-gdb "c" Enter          # releases the initial pause

Do NOT put `handle SIGTRAP ... pass` in the connect line. The initial stop is a
SIGTRAP; passing it into the guest on the first `c` killed Eden in the
2026-08-27 session (connection dropped within seconds, no status.bin). If
spurious SIGTRAP stops appear later, use `handle SIGTRAP nostop noprint nopass`
(never `pass`).

Read the pane at any time with `tmux capture-pane -t eden-gdb -p -S -40`.
Confirm the guest is actually running before touching anything else:
`python3 emu_session.py game-status` must show a frame counter that advances
and `scene_mode` 6 (title) within ~30 s of the `c`. If it does not, stop and
report; do not send more GDB commands.
Send commands with `tmux send-keys -t eden-gdb "<gdb command>" Enter`.
To interrupt a running game: `tmux send-keys -t eden-gdb C-c`.

Without GDB (input/status automation only): `python3 emu_session.py launch eden`.

## 4. Navigate

    python3 -c "from smm2 import Game; Game('eden').to_coursebot_play(slot=N)"   # title -> editor -> Coursebot -> play slot N
    # (boot_to_editor.py still presses a title-screen menu path that does not exist; L+R at the
    #  title opens the title-demo course in the editor. Use Game.to_coursebot_play / game_boot.)
    python3 emu_session.py game-status        # decoded status.bin: frame, scene, player pos/vel/state

Or from Python: `from smm2 import Game; g = Game('eden'); g.scene(); g.status(); g.press(...)`.
Scene modes: 0 loading, 1 editor, 5 editor play, 6 title, 7 Coursebot play.
Screenshot of the Eden window: `python3 automate.py --eden screenshot`
(prints the PNG path; PowerShell `PrintWindow` under the hood). Use it to
verify a generated level visually before doing anything with GDB.

Do the navigation with GDB at `c` (running). Never leave GDB stopped during a
scene change.

**Per-frame traces without GDB**: a probe (`docs/probe.md`) hooks a function
named in `sd:/smm2-hooks/probe.txt` and logs its arguments plus fields behind
`x0` on every call while the game runs at full speed. `python3 probe.py
preset rail > probe.txt`, `python3 probe.py install probe.txt --target eden`
(validates the addresses against main.elf), play, then `python3 probe.py
decode probe.log -o trace.csv`. Use it for anything that needs more than a
handful of stops; keep GDB for "who writes this".

## 5. ASLR: find the base once per launch

Addresses in `smm2-decomp/data/v3.0.3/functions.csv` are `0x7100000000 + offset`.
Eden loads the text somewhere in `0x80800000..0x82000000`. Find
`StateMachine::changeState` (offset `0x8b9320`) by its prologue bytes:

    find /b 0x80800000, 0x82000000, 0xf6, 0x57, 0xbd, 0xa9, 0xf4, 0x4f, 0x01, 0xa9, 0xfd, 0x7b, 0x02, 0xa9, 0xfd, 0x83, 0x00, 0x91, 0x08, 0x08, 0x40, 0xb9, 0xf3, 0x03, 0x01, 0x2a

    base    = found_address - 0x8b9320
    runtime = base + (csv_address - 0x7100000000)
    csv     = 0x7100000000 + (runtime - base)

Interrupt first (`C-c`), run `find`, then `c`. Record `base` in your notes; it
changes on every launch.

Signature for any other function (position-independent prologue words; stop
at the first ADRP/ADR/B/BL/CBZ/TBZ), from the decomp checkout:

    python3 - <<'PY'
    import struct; BASE=0x7100000000; va=0x71013951C0   # <- function
    d=open('data/v3.0.3/main.elf','rb').read(); off=va-BASE+0x888; out=[]
    for i in range(8):
        w=struct.unpack_from('<I',d,off+i*4)[0]
        if (w&0x1F000000)==0x10000000 or (w&0x7C000000)==0x14000000 or (w&0xFF000010)==0x54000000 or (w&0x7E000000) in (0x34000000,0x36000000): break
        out += struct.pack('<I',w)
    print(', '.join(f'0x{b:02x}' for b in out))
    PY

Prefer `find` on the signature over `base + offset` for the first breakpoint of
a session; if both agree, the base is right.

## 6. Recipes

**Actor pointer by vtable scan** (no breakpoints on this Eden build). The
vtable is a static address from the decomp (e.g. `OnpuBlock` `0x7102938410`);
actors sit in the same heap region as the player, below it:

    # player_ptr = u64 at status.bin+0x68; runtime vtable = base + (vtable - 0x7100000000)
    find /g <player_ptr - 0x8000000>, <player_ptr + 0x10000>, <runtime vtable>
    # one hit per live instance; confirm with x/2fw <hit + 0x230> (pos_x, pos_y)

128 MB takes about a minute over the stub. `mon get mappings` lists what is
mapped if `find` errors on an unmapped page.

**Who writes a field**: with the actor pointer `A` and the field offset
(`docs/OFFSETS.md`, e.g. `pos_x` = `+0x230`):

    watch *(int*)(A + 0x230)
    c
    # on hit:
    p/x $pc            # the writer; translate to csv with the formula above
    bt 8
    info reg x0 x1 x2 x3
    delete <n>
    c

`python3 eden_gdb_auto.py watch <addr> 4` wraps exactly this (30 s timeout) if a
tmux GDB session is at the prompt. `eden_gdb_auto.py get-player` finds the
player object via `changeState`.

**Read fields**: `x/1fw (A + 0x230)` (float), `x/1wx (A + 0x3F8)` (state id).

**Conditional watchpoints** (`watch ... if ...`) are not honoured by the stub;
loop `c` / read instead.

## 7. Teardown

    tmux send-keys -t eden-gdb "delete" Enter      # all breakpoints/watchpoints
    tmux send-keys -t eden-gdb "c" Enter
    tmux send-keys -t eden-gdb "detach" Enter
    tmux send-keys -t eden-gdb "quit" Enter
    tmux kill-session -t eden-gdb
    python3 emu_session.py kill eden
    python3 emu_session.py gdb-off                 # leave the config as you found it

## Timings (this machine, 2026-08-28)

- `eden_launch` to title (`scene_mode` 6): 10-30 s. Wait ~5 s after the title
  appears before the first input; earlier presses are dropped.
- title to editor 4-5 s; editor to the Coursebot grid ~8 s; grid to playing a
  slot ~10 s. Launch to a running course: 31 s best, ~55 s typical.
- A Coursebot validation verdict (`validate_slots.py`): 55-75 s for up to four
  slots.
- Eden hung at its own "Launching..." screen once in ~10 launches (0 FPS,
  `status.bin` frame 0): no title within 60 s means kill, wait 3 s, relaunch.
- Eden exited once at the very first injected input, ~30 s after launch; not
  reproduced in nine later launches. Every trace should carry
  `eden.process()`: a frozen `status.bin` means the game is gone, not the hooks.

## Iteration log

- 2026-08-28: "corrupt Track Note" was two unrelated things, found in ~2 h with
  four-slot validation runs: slots need a valid thumb+replay, and `goal_x` is
  tenths of a tile. The rail geometry came from one screenshot of an
  editor-saved course measured against its records (74 px per tile at this
  window size, ground line as the y reference). Screenshots served from disk
  after a failed capture cost the first 20 minutes; `eden_screenshot` now
  deletes the file first.

- 2026-08-27: launch --gdb, attach while paused with `handle SIGTRAP ... pass`
  on the connect line, `c` -> Eden exited within seconds. Hypothesis: SIGTRAP
  passed into the guest. Next attempt drops the handle command; level is
  validated first in a no-GDB launch.

## Troubleshooting

- SIGTRAP storm right after connecting, no breakpoints of yours: stale software
  breakpoints from an old session (`docs/tooling-gaps.md` #1). `handle SIGTRAP
  nostop noprint nopass` hides it (never `pass`, see Problem 7); if the game still stalls, Eden's code cache
  must be cleared (reinstall the game). Report; do not keep retrying.
- `target remote` refuses: wrong host IP (recheck `ip route`), stub disabled
  (`emu_session.py gdb-on`, needs a relaunch), or Eden not up yet (wait ~15 s).
- `status.bin` never appears: hooks not deployed, or wrong SD path in `.env`
  (`emu_session.py overview` shows both).
- `find` returns nothing: the pattern includes a position-dependent word, or the
  range is wrong; verify with `x/8xw <candidate>` against the ELF bytes.
- Never SIGTERM `gdb-multiarch` while it is attached: its quit path sends `k`
  to the stub and Eden shuts the game down (seen 2026-08-29). `kill -9` only
  drops the connection and the game keeps running.
- A tool call the host moved to the background (>120 s) wedges that MCP
  server's channel for every later call, even though the server is idle;
  the fix is a `/mcp` reconnect. Long waits go through tmux (section 3) or a
  background `tools/smm2.py` script, never through a blocking MCP call.
- `eden_launch(gdb=True)` needs `use_gdbstub\default=false` as well as
  `use_gdbstub=true` in the ini; with the `\default` flag set Eden ignores the
  value (fixed in `eden.set_gdbstub`).
- Watchpoint never hits: the object is not the one you think (check `getClassName`
  via the vtable slot 2), or the field is written by DMA-like memcpy; try `awatch`.
