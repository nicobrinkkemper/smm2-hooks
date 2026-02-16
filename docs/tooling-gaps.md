# Tooling Gaps — What Keeps Breaking

## Problem 1: Eden GDB stale breakpoints
**Symptom**: SIGTRAP loops after any session that used `break`. Persists across restarts.
**Root cause**: Eden bakes software breakpoints into code memory. Running without GDB doesn't clear them — the modified code pages are cached.
**Fix needed**: Never use `break`. Only `watch`. But past sessions already left stale traps.
**Workaround**: Need to either clear Eden's code cache or reinstall the game.

## Problem 2: No single session manager
**Symptom**: Orphaned eden.exe processes, stale tmux sessions, GDB config left in wrong state.
**What exists**: `emu_session.py` — basic launch/kill/status. Doesn't manage GDB config or tmux.
**What's needed**: One tool that tracks ALL state:
- Is Eden running? PID? Memory usage?
- Is GDB stub enabled in config?
- Is tmux `eden-gdb` session alive? Connected?
- Is status.bin being updated? (hooks working?)
- What's on screen? (frame counter advancing?)

## Problem 3: Config toggling is manual
**Symptom**: I edit qt-config.ini with sed every time I need to enable/disable GDB.
**Fix needed**: `emu_session.py gdb-on` / `emu_session.py gdb-off`

## Problem 4: No hook deployment check
**Symptom**: Launched Eden, wondered why no status.bin — hooks weren't deployed.
**Fix needed**: `emu_session.py deploy` should verify deployment, `emu_session.py status` should check if hooks are deployed.

## Problem 5: status.bin path confusion
**Symptom**: Looked in wrong directory for status.bin (Documents vs AppData).
**Fix needed**: Single source of truth from .env, all tools use it consistently.

## Problem 6: No "what's running" overview
**Symptom**: Start of every session, I don't know what state things are in.
**Fix needed**: `emu_session.py overview` that shows everything at a glance.
