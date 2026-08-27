# Tooling Gaps — What Keeps Breaking

Status as of 2026-08-27. Problems 2–6 are addressed by `mcp/eden.py` +
`mcp/server.py` (`eden_state` is the overview; `eden_launch` toggles the real
ini; `mods` reports deployment; paths come from the config). Problem 1 is
open. Problems 7–10 are new.

## Problem 1: Eden GDB stale breakpoints
**Symptom**: SIGTRAP loops after any session that used `break`. Persists across restarts.
**Root cause**: Eden bakes software breakpoints into code memory. Running without GDB doesn't clear them — the modified code pages are cached.
**Fix needed**: Never use `break`. Only `watch`. But past sessions already left stale traps.
**Workaround**: Need to either clear Eden's code cache or reinstall the game.

## Problem 2: No single session manager — addressed (`eden_state`)
**Symptom**: Orphaned eden.exe processes, stale tmux sessions, GDB config left in wrong state.
**What exists**: `emu_session.py` — basic launch/kill/status. Doesn't manage GDB config or tmux.
**What's needed**: One tool that tracks ALL state:
- Is Eden running? PID? Memory usage?
- Is GDB stub enabled in config?
- Is tmux `eden-gdb` session alive? Connected?
- Is status.bin being updated? (hooks working?)
- What's on screen? (frame counter advancing?)

## Problem 3: Config toggling is manual — addressed (`eden_launch(gdb)`, `eden_set_gdbstub`); `emu_session.py gdb-on/off` still edits the AppData ini, which Eden does not read
**Symptom**: I edit qt-config.ini with sed every time I need to enable/disable GDB.
**Fix needed**: `emu_session.py gdb-on` / `emu_session.py gdb-off`

## Problem 4: No hook deployment check — addressed (`eden_state.mods`)
**Symptom**: Launched Eden, wondered why no status.bin — hooks weren't deployed.
**Fix needed**: `emu_session.py deploy` should verify deployment, `emu_session.py status` should check if hooks are deployed.

## Problem 5: status.bin path confusion — root cause found: Eden is portable (config in `Documents/eden/user`), data dirs in AppData as named by that config; `mcp/eden.py` reads the config
**Symptom**: Looked in wrong directory for status.bin (Documents vs AppData).
**Fix needed**: Single source of truth from .env, all tools use it consistently.

## Problem 6: No "what's running" overview — addressed (`eden_state`)
**Symptom**: Start of every session, I don't know what state things are in.
**Fix needed**: `emu_session.py overview` that shows everything at a glance.

## Problem 7: `handle SIGTRAP ... pass` kills the guest
**Symptom**: Eden exits seconds after the first `c` when GDB was configured with `handle SIGTRAP nostop noprint pass` at connect.
**Root cause**: Eden's initial stop is a SIGTRAP; `pass` delivers it into the game.
**Fix**: never `pass` SIGTRAP; the MCP refuses it. Use `nopass` if spurious stops need hiding.

## Problem 8: Attached client during a scene load drops the connection
**Symptom**: With GDB attached (no breakpoints), entering Coursebot from the title killed Eden (`Error detected on fd`).
**Status**: open. Workaround: navigate to run-time first, attach after.

## Problem 9: `parse_course.py` object id table is wrong
**Symptom**: id 23 shown as "SuperMushroom", 24 as "Note", 86 as "Track".
**Truth** (decomp `bcd-format.ksy`, community sheet, editor-saved course): 23 = Note Block, 59 = Track, 85 = Track Block. Fix the table.

## Problem 10: Two copies of the mod
**Symptom**: `Documents/eden/load/.../subsdk4` (Feb 16) and `AppData/Roaming/eden/load/.../subsdk4` (Apr 30). Only the AppData one is loaded (config `load_directory`).
**Fix needed**: delete the stale copy next to the exe so a wrong `load_directory` can never load it silently.
