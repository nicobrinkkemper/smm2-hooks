# Botting Patches

Patches to speed up automated testing.

## Skip Intro Cutscene

From comex/domthewiz/possamato:

```
Address: 017E432C
Original: 41008052  // mov w1, #2 (cutscene phase)
Patched:  81008052  // mov w1, #4 (playing phase)
```

The intro cutscene masks loading but isn't required. This jumps straight to gameplay.

## Useful Addresses

From noexes-patches.md:

| Address | Description |
|---------|-------------|
| `[main+02A67B70]+28]+210` | Course theme (main area) |
| `[main+02A67B70]+28]+228` | Hour type (day/night) |
| `qword_7102C57D58->field_30->field_1C` | Game style index |

## Bypass Level Corruption Checks

From Mario Possamato (Discord 2025-10-14):

```
@nsobid-C2DC405AC414C37C8B1C50219C7A0F0C
#Slope (Super Mario Maker 2) version 3.0.3
@flag offset_shift 0x100

// Stub sub_7100FCAB10 (corruption validator)
// Returns 0 = valid for all levels
@enabled
00FCAB10 E0031F2A  // MOV W0, WZR
00FCAB14 C0035FD6  // RET
```

This bypasses ALL corruption checks: Coursebot, uploading, playing, downloading.
Function `sub_7100FCAB10` is the main validator — returns 0 for valid, non-zero for corrupt.

Useful for:
- Testing generated/modified levels
- Automation without worrying about level validation
- Understanding what fields the validator checks

## TODO: Find patches for

- [x] Bypass corruption checks
- [ ] Skip autosave delays
- [ ] Force game style (SMB1 fastest)
- [ ] Skip title screen (partially done: skip_intro.pchtxt)
- [ ] Disable network handshake
- [ ] Auto-load specific course slot
