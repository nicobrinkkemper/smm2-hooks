# AGENTS.md — AI Agent Instructions

This file helps AI agents (Claude, GPT, etc.) work effectively with smm2-hooks.

## Overview

smm2-hooks is a LibHakkun-based mod for Super Mario Maker 2 (Switch) that:
- Injects button inputs from `input.bin`
- Reports game state to `status.bin`
- Hooks player state changes and other game functions

## Quick Start

```bash
# Build
ninja -C build

# Deploy to Eden emulator
cp build/exefs/subsdk4 /mnt/c/Users/nico/AppData/Roaming/eden/load/01009B90006DC000/smm2-hooks/exefs/

# Boot to play mode with specific level
cd tools && python3 boot_to_editor.py eden --slot 0
```

## Key Files

| Path | Purpose |
|------|---------|
| `tools/smm2.py` | Python API for game control (`Game('eden')`) |
| `tools/boot_to_editor.py` | Full boot automation with `--play` and `--slot` |
| `tools/emu_session.py` | Emulator process management |
| `src/status.cpp` | Status.bin writer (game state) |
| `src/tas.cpp` | Input injection from input.bin |
| `include/smm2/status.h` | StatusBlock struct definition |
| `docs/status-system-spec.md` | Scene modes and system architecture |
| `docs/automation-workflow.md` | Boot sequences and timings |

## Scene Modes

```
0 = Loading/transition (also Coursebot details popup)
1 = Editor (Course Maker)
5 = Editor play (test-play from editor)
6 = Title screen / menus
7 = Coursebot play (play-only mode)
```

## Common Tasks

### Read game state
```python
from smm2 import Game
g = Game('eden')
s = g.status()  # dict with frame, scene_mode, player state, etc.
```

### Send inputs
```python
g.press('A', 200)           # Press A for 200ms
g.hold('L+R', 1500)         # Hold L+R for 1.5s
g.press('DOWN', 150)        # D-pad
```

### Boot to specific course
```bash
python3 boot_to_editor.py eden --slot 0   # First saved course
python3 boot_to_editor.py eden --slot 75  # Slot 75 (test level)
```

### Add a hook
1. Declare trampoline in `include/smm2/hooks.h` (or relevant header)
2. Implement in `src/` with `HkTrampoline` and `installAtSym`
3. Add symbol to `syms/main.sym` if not `@sdk`
4. Call `init()` from `main.cpp`

## SD Card Paths

| Emulator | SD Card Path |
|----------|--------------|
| Eden | `/mnt/c/Users/nico/AppData/Roaming/eden/sdmc/smm2-hooks/` |
| Ryujinx | `/mnt/c/Users/nico/AppData/Roaming/Ryujinx/sdcard/smm2-hooks/` |

## Tips

- Scene mode 0 during Coursebot UI is normal — use frame advancement to check game is responsive
- Coursebot needs ~5s to load before inputs work
- Hold operations in Coursebot (like holding A) grab/move tiles — use press instead
- Player data in status.bin is only valid when `has_player=1` AND `scene_mode in (5, 7)`
