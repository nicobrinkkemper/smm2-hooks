# smm2-hooks

Runtime instrumentation framework for Super Mario Maker 2 (Switch v3.0.3). Built on [LibHakkun](https://github.com/fruityloops1/LibHakkun).

## What It Does

Hooks into SMM2 functions at runtime to capture game state — state transitions, physics values, player fields — and logs them to SD card for analysis.

Designed as a reusable base that other mods (like [MM2Chaos](https://github.com/waluigi3/MM2Chaos)) can build on.

## Current Plugins

### State Logger
Hooks `StateMachine::changeState` and logs every state transition to `sd:/smm2-hooks/states.csv`:
```
frame,old_state,new_state,sm_ptr
120,1,3,0x2121609040
135,3,2,0x2121609040
```

## Project Structure

```
include/
  smm2/
    frame.h       - Per-frame callback hook
    log.h         - SD card logging utility
    player.h      - PlayerObject field offsets & state IDs
    hooks.h       - Top-level init
src/
  frame.cpp       - procFrame_ trampoline
  state_logger.cpp - StateMachine::changeState hook
  main.cpp        - Entry point (hkMain)
syms/
  v303.sym        - SMM2 v3.0.3 symbol addresses
config/           - LibHakkun build config
sys/              - LibHakkun (submodule)
```

## Build

Requires `clang`, `lld`, and `llvm-ar` (cross-compiles to AArch64 natively — no devkitPro needed).

On Ubuntu/WSL:
```bash
sudo apt install clang lld llvm ninja-build cmake
```

```bash
git submodule update --init --recursive
cmake -B build -DCMAKE_BUILD_TYPE=Release -GNinja
ninja -C build
```

Output: `build/smm2-hooks.nso` → install as ExeFS `subsdk4`.

## Driving the game from an agent

- `mcp/` — an MCP server (`mcp/server.py`, see `mcp/README.md`) that reports one
  truthful emulator state (`eden_state`: mode, real config, `status.bin`, mods,
  log), launches/kills Eden, installs generated levels, navigates the game,
  takes screenshots, and owns a single GDB session with hardware
  breakpoints/watchpoints only.
- `.claude/skills/eden-debug/` — the procedure around those tools: what each
  mode means (edit-time vs run-time), when to attach GDB, how to find the
  ASLR base, teardown.
- `tools/` — the scripts the server wraps (`emu_session.py`, `smm2.py`,
  `boot_to_editor.py`, `automate.py`, `gen_test_levels.py`, `parse_course.py`).

Eden here runs portable: its config and log live in `Documents/eden/user/`,
while NAND, SD and mods sit under `AppData/Roaming/eden` as named in that
config. The MCP reads the config; `emu_session.py` still edits the AppData ini
and is wrong about the GDB stub until it is switched to `mcp/eden.py`.

## Docs

| Doc | What |
|-----|------|
| `docs/status-system-spec.md` | `status.bin` fields, scene modes, requirements |
| `docs/probe.md` | function probes: `probe.txt` hooks + field paths → `probe.log` (Eden has no hardware breakpoints) |
| `docs/automation-workflow.md` | Boot sequences and timings |
| `docs/eden-gdb-workflow.md` | GDB against Eden's stub |
| `docs/level-generation.md` / `docs/level-modification.md` | Test levels, BCD layout |
| `docs/tooling-gaps.md` | What keeps breaking, and what is fixed |
| `docs/botting-patches.md` | Patches used by the automation |
| `docs/direct-boot.md` | `boot.txt`: boot straight into a Coursebot course (play at 16 s); `tools/trace.py` records a probe run in one command |

## Adding Hooks

1. Add symbol address to `syms/v303.sym`
2. Create a hook with `HkTrampoline` + `installAtSym`
3. Use `smm2::log::Logger` for output
4. Init from `hkMain()` in `src/main.cpp`

## Credits

- [LibHakkun](https://github.com/fruityloops1/LibHakkun) by fruityloops1
- [MM2Chaos](https://github.com/waluigi3/MM2Chaos) by waluigi3 — original framework this was extracted from
- Mario Possamodder — state enum names
- Abood (aboood40091) — NSMBU cross-references

## License

MIT
