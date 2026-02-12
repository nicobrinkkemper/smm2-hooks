# smm2-hooks

Runtime instrumentation framework for Super Mario Maker 2 (Switch v3.0.3). Built on [LibHakkun](https://github.com/fruityloops1/LibHakkun).

## What It Does

Hooks into SMM2 functions at runtime to capture game state — state transitions, physics values, player fields — and logs them to SD card for analysis.

Designed as a reusable base that other mods (like [MM2Chaos](https://github.com/nicobrinkkemper/MM2Chaos)) can build on.

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

## Adding Hooks

1. Add symbol address to `syms/v303.sym`
2. Create a hook with `HkTrampoline` + `installAtSym`
3. Use `smm2::log::Logger` for output
4. Init from `hkMain()` in `src/main.cpp`

## Credits

- [LibHakkun](https://github.com/fruityloops1/LibHakkun) by fruityloops1
- [MM2Chaos](https://github.com/nicobrinkkemper/MM2Chaos) — original framework this was extracted from
- Mario Possamodder — state enum names
- Abood (aboood40091) — NSMBU cross-references

## License

MIT
