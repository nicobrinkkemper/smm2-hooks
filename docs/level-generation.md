# SMM2 Level Generation Guide

This documents how to generate valid test levels for SMM2, including common pitfalls.

## Level File Types

### Coursebot Saves (`course_data_XXX.bcd`)
- Location: `{save_dir}/course_data_000.bcd` through `course_data_059.bcd`
- Format: Encrypted BCD (header + AES-CBC encrypted data + CMAC)
- Tool: `gen_test_levels.py`
- Note: `save.dat` indexes these files; game must restart to reload

### Title Screen Demos (`title_course_data_XX.szs`)
- Location: `romfs/Course/title_course_data_00.szs` through `_09.szs`
- Format: Yaz0-compressed SARC archive containing encrypted BCD
- Tool: `replace_title_demo.py`
- Note: Game cycles through 10 demos on title screen

## Level Structure

### Auto-Generated Zones (DO NOT PLACE TILES/OBJECTS HERE)

**Start Area (x = 0 to 6, width = 7 tiles)**
- Arrow sign and spawn point
- Ground is auto-generated based on `start_y` header field
- The 7-tile width is fixed and can be moved vertically in editor

**Goal Area (x = goal_x - 3 to goal_x)**
- Flag pole auto-generated from `goal_x` and `goal_y` header fields
- Do NOT place a goal object (id=27) - game auto-generates it

### Safe Zone for Custom Content
```
x >= 7 AND x <= goal_x - 4
```

For a level with `goal_x = 27`:
- Safe zone: x = 7 to x = 22
- Start area: x = 0 to 6 (auto-generated)
- Goal area: x = 23 to 27 (auto-generated)

### True Flat Ground (No Custom Tiles)
For a simple flat ground level with no gaps:
- `goal_x = 11` (close to start)
- `goal_y = 4` (one tile DOWN from start_y=5)
- No custom ground tiles - auto-generated areas connect seamlessly
- The `goal_y` offset aligns the ground levels

### Subworld Initialization
Subworld (Area 1) at offset `0x2E0E0` must be initialized:
- Theme: same as main world
- Width: 1344 (84 tiles × 16px)  
- Height: 432 (27 tiles × 16px)
- Boundary flags at +0x02: 1
- Flag at +0x04: 1

If subworld is all zeros, pipes to subworld will crash/corrupt.

## Course Header Rules

The game runs every course through `CourseDataValidator::validate`, and
Coursebot deletes a course that breaks any of its header rules. Addresses,
error bits and the decomp port: smm2-decomp
`docs/re-notes/course-validator.md`, section "The header rules". Sizes are
in pixels (16 per tile) unless a row says tiles.

- **Start row** (`body+0x00`): 1..25, at least 2 in 3D World.
- **Goal row** (`body+0x01`): 1..15, at least 2 in 3D World.
- **Goal x** (`body+0x02`, i16, tenths of a tile): `(width - 9.5) * 10`. The
  pole stands 9.5 tiles from the overworld's right edge.
- **Timer** (`body+0x04`, u16): a multiple of 10 in 10..500.
- **Autoscroll**: overworld type (`area+0x01`) at most 4, speed
  (`body+0x0E`) at most 2, sub area type at most 3.
- **Theme** (`area+0x00`): below 10 in both areas. No night (area flags
  `+0x18` bit 1) in 3D World, in either area.
- **Orientation** (`area+0x03`): the overworld is never vertical; only the
  sub area can be.
- **Area size**: the overworld has top 432 (27 rows) and right 384..3840
  (24..240 tiles). A horizontal sub area the same. A vertical sub area has
  right 768 (48 tiles) and top 448..2688 (28..168 rows).
- **Left and bottom** (`+0x10`, `+0x14`): 0 in the overworld. A vertical sub
  area: left 0 and bottom 0..top - 216; a horizontal one: bottom 0 and left
  0..right - 384.
- **Liquid**: end (`+0x04`) and start (`+0x07`) rows within the area,
  `bottom / 16 .. top / 16`, two rows lower at the top for a horizontal area
  (so 0..25 at the usual height). Mode (`+0x05`) at most 2, speed (`+0x06`)
  at most 3.
- **Per-area counts**: objects (`+0x1C`) 2600, ground tiles (`+0x3C`) 4000,
  tracks (`+0x40`) 1500, ice (`+0x44`) 300, clear pipes (`+0x28`) 200, snake
  blocks (`+0x24`) 5, piranha creepers, ! blocks and track blocks
  (`+0x2C`, `+0x30`, `+0x34`) 10 each; sound effects (`+0x20`) plus linked
  objects 300.
- **Per-kind counters**: each object kind also counts against a limit (doors
  8, checkpoint flags 1, Bowser and Bowser Jr. 3, ...); the table is in the
  re-note's "The leaves".
- **Clear condition** (`body+0x10`): must be one the game knows.
- **`body+0xF0`**: 0xFF or below 0x38.

`LevelBuilder.preflight` in `tools/gen_test_levels.py` refuses a level that
breaks any of these the builder can produce, naming the rule's error bit
(`header rule 0x400 (start row): ...`); `header_errors` lists the ones it
leaves out and why. `python3 -m unittest tools/test_course_header.py`
checks every generated level and each refused rule.

## Common Mistakes

### ❌ Placing Ground Over Start Area
```python
# WRONG - overlaps start area (x=0 to 6)
b.add_ground(0, 30, 4)
b.add_ground(5, 23, 4)

# CORRECT - starts after start area
b.add_ground(7, 22, 4)
```

### ❌ Placing Goal Object
```python
# WRONG - creates duplicate flag pole
self.objects.append({'id': OBJ_GOAL, 'x': goal_x, ...})

# CORRECT - don't add goal, it's auto-generated from header
# Just set b.goal_x and b.goal_y
```

### ❌ Placing 4x4 Objects Near Spawn
Note blocks, music blocks, and other 4x4 objects near the spawn area will block Mario.

### ❌ Not Restarting Emulator
Both Eden and Ryujinx cache save data in memory. After generating new levels:
1. Kill the emulator completely
2. Regenerate levels
3. Start emulator fresh

## Title Demo Behavior

When Eden starts:
1. Frame 0: Black screen (normal)
2. Circle mask animation reveals demo level
3. Demo plays in "play mode" with "Press L+R" overlay
4. Status reports `scene_mode` as play, but no input works (demo mode)

## File Format Details

### BCD Encryption
- Header: 0x10 bytes (version, CRC, "SCDL" magic)
- Encrypted data: 0x5BFC0 bytes (AES-128-CBC)
- Crypto config: 0x30 bytes (IV + rand_state + CMAC)
- Total: 0x5C000 bytes (376832)

### Key Derivation
Uses PRNG seeded from `rand_state` to derive:
1. AES-CBC key (16 bytes)
2. CMAC key (16 bytes) - CONTINUE PRNG state after key 1

### SARC Archive (for title demos)
- Yaz0 compressed
- Contains single file: `title_course_data_XX.bcd`
- Use `libyaz0` for proper compression

## Tools

### gen_test_levels.py
```bash
python3 gen_test_levels.py              # Generate all 10 test levels
python3 gen_test_levels.py --slot 0     # Generate specific slot
python3 gen_test_levels.py --list       # List available levels
```

### replace_title_demo.py
```bash
python3 replace_title_demo.py           # Replace all 10 title demos
python3 replace_title_demo.py --slot 0  # Replace specific demo
python3 replace_title_demo.py --restore # Remove mods, restore originals
```

### Verification
```bash
# Start Eden and verify title demo
cd ~/code/smm2-hooks/tools
python3 emu_session.py fresh eden --no-nav

# Take screenshot after game loads
sleep 5
python3 automate.py --eden screenshot
```

## Troubleshooting

### Black Screen on Title
- Normal at frame 0 - wait for circle mask animation
- If persists: level data is corrupted, check encryption

### Note Blocks Blocking Mario  
- Check if you placed objects in start area (x < 7)
- Title demos were previously modded with bad data
- Fix: `python3 replace_title_demo.py --restore` then regenerate

### Ground Tiles Over Start/Goal Area
- Start area: 7 tiles wide (x = 0-6)
- Goal area: ~4 tiles before goal_x
- Only place ground in safe zone (x >= 7, x <= goal_x - 4)

### Level Not Loading in Coursebot
- `save.dat` indexes courses and may have stale metadata
- Title demos are separate files in romfs, not affected by save.dat

### Input Injection Not Working
- Eden uses different controller type than Pro Controller hook
- Physics capture works, but navigation requires manual input
- Use keyboard on Eden window for testing
