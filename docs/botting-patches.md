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

## TODO: Find patches for

- [ ] Skip autosave delays
- [ ] Force game style (SMB1 fastest)
- [ ] Skip title screen
- [ ] Disable network handshake
- [ ] Auto-load specific course slot
