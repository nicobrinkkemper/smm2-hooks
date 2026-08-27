---
name: eden-debug
description: Drive a Super Mario Maker 2 debug session in the Eden emulator from WSL — launch Eden on the Windows side with the smm2-hooks mod, boot a test level, attach GDB in a persistent tmux session, find functions under ASLR by byte signature, set hardware breakpoints/watchpoints, read hits, and tear down cleanly. Use for any runtime question about the game (who writes a field, what a function is called with, actor pointers), for verifying generated test levels in the editor, and whenever the user mentions Eden, GDB, hooks, watchpoints, or "run it in the emulator".
---

# Eden debug session

Everything runs from WSL; Eden itself is a Windows process (`eden.exe`, started via
`/mnt/c/...`). The scripts live in `smm2-hooks/tools/` (this repo, or the sibling
`$GEITJE_CODE_ROOT/smm2-hooks` from mission control). Run them from that `tools/`
directory; they read `smm2-hooks/.env` (paths only, no secrets).

Two things make this fragile, and every step below exists because of them:
Eden bakes software breakpoints into cached code pages (a `break` you forget
loops as SIGTRAP forever, across restarts), and the Windows host IP for the GDB
stub changes per WSL boot. `docs/tooling-gaps.md` lists the failure modes.

## Rules (non-negotiable)

- `hbreak`, `watch`, `rwatch`, `awatch` only. **Never `break`.**
- One persistent GDB inside tmux session `eden-gdb`. Never connect with
  `gdb -batch` or a second client; `tools/eden_gdb.py` opens its own socket and is
  only safe when no tmux GDB is attached.
- After every stop: `delete <n>` when done with it, then `c`. The game is
  frozen while GDB sits at the prompt; the status file stops updating.
- No breakpoints while a scene is loading (`scene_mode 0`).
- Narrate each step to the user and stop at the first surprise (unexpected
  scene, SIGTRAP storm, no status updates) instead of pushing through.

## 1. Preflight

    cd $GEITJE_CODE_ROOT/smm2-hooks/tools
    python3 emu_session.py overview       # processes, hooks deployed?, gdb stub on?, tmux, status.bin
    ip route | awk '/default/ {print $3}' # Windows host IP; must equal EDEN_GDB_HOST in ../.env (edit if not)

If `overview` shows an Eden process or an `eden-gdb` tmux session from an older
run, kill both first: `python3 emu_session.py kill eden` and
`tmux kill-session -t eden-gdb`. If hooks are not deployed:
`ninja -C ../build && python3 emu_session.py deploy eden`.

## 2. Test level (optional)

    python3 gen_test_levels.py --list
    python3 gen_test_levels.py --slot N --target eden    # writes course_data_00N.bcd, backs up the old one

Slots are Coursebot saves; the game must be (re)started to reload `save.dat`.
Slot 10 is "Track Note": one horizontal track with a winged note block, for the
rail-music work. Adding levels: `LevelBuilder` methods in `gen_test_levels.py`
(`add_track`, `add_note_block_on_track`, ...). Keep custom content in
`x >= 7 && x <= goal_x - 4` (start and goal areas are auto-generated).

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

    python3 boot_to_editor.py eden --slot N   # title -> Coursebot -> play slot N (scene_mode 7)
    python3 boot_to_editor.py eden            # title -> editor demo (scene_mode 1); add --play for test play (5)
    python3 emu_session.py game-status        # decoded status.bin: frame, scene, player pos/vel/state

Or from Python: `from smm2 import Game; g = Game('eden'); g.scene(); g.status(); g.press(...)`.
Scene modes: 0 loading, 1 editor, 5 editor play, 6 title, 7 Coursebot play.
Screenshot of the Eden window: `python3 automate.py --eden screenshot`
(prints the PNG path; PowerShell `PrintWindow` under the hood). Use it to
verify a generated level visually before doing anything with GDB.

Do the navigation with GDB at `c` (running). Never leave GDB stopped during a
scene change.

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

**Actor pointer from a function it runs on** (e.g. the note block's `execute`,
`sub_71013951C0`, offset `0x13951c0`):

    hbreak *<runtime address>
    c
    # on hit (only while scene_mode is 5/7):
    p/x $x0            # this
    delete <n>
    c

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

## 7. Teardown

    tmux send-keys -t eden-gdb "delete" Enter      # all breakpoints/watchpoints
    tmux send-keys -t eden-gdb "c" Enter
    tmux send-keys -t eden-gdb "detach" Enter
    tmux send-keys -t eden-gdb "quit" Enter
    tmux kill-session -t eden-gdb
    python3 emu_session.py kill eden
    python3 emu_session.py gdb-off                 # leave the config as you found it

## Iteration log

- 2026-08-27: launch --gdb, attach while paused with `handle SIGTRAP ... pass`
  on the connect line, `c` -> Eden exited within seconds. Hypothesis: SIGTRAP
  passed into the guest. Next attempt drops the handle command; level is
  validated first in a no-GDB launch.

## Troubleshooting

- SIGTRAP storm right after connecting, no breakpoints of yours: stale software
  breakpoints from an old session (`docs/tooling-gaps.md` #1). `handle SIGTRAP
  nostop noprint pass` hides it; if the game still stalls, Eden's code cache
  must be cleared (reinstall the game). Report; do not keep retrying.
- `target remote` refuses: wrong host IP (recheck `ip route`), stub disabled
  (`emu_session.py gdb-on`, needs a relaunch), or Eden not up yet (wait ~15 s).
- `status.bin` never appears: hooks not deployed, or wrong SD path in `.env`
  (`emu_session.py overview` shows both).
- `find` returns nothing: the pattern includes a position-dependent word, or the
  range is wrong; verify with `x/8xw <candidate>` against the ELF bytes.
- Watchpoint never hits: the object is not the one you think (check `getClassName`
  via the vtable slot 2), or the field is written by DMA-like memcpy; try `awatch`.
