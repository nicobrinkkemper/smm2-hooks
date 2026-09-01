# Patches (pchtxt)

IPS-style text patches for Slope 3.0.3 (`@nsobid-C2DC405AC414C37C8B1C50219C7A0F0C`)
live in `patches/*.pchtxt`, versioned. Eden applies every `*.pchtxt` inside a
mod's `exefs/` folder, so a patch is **enabled** when a copy sits next to the
deployed `subsdk4`. Nothing is edited by hand in Eden's `load/` directory.

```
python3 mcp/eden.py --patches               # on/off per patch (stale = deployed copy differs)
python3 mcp/eden.py --enable skip_intro     # copy into the mod's exefs/ (next launch)
python3 mcp/eden.py --disable skip_intro    # remove it
```

MCP: `eden_patches(enable=, disable=)`; `eden_state` lists them under
`mods.patches`.

| patch | effect |
|---|---|
| `skip_intro` | title boot phase 2 → 4: no intro cutscene (the title still shows; input is accepted from frame 1000) |
| `corruption_bypass` | `game::CourseDataValidator::validate` returns 0: Coursebot keeps a course it would delete; a footgun for real validation runs (`validate_slots.py` wants it off) |
| `botting` | the automation profile; currently only the same intro skip as `skip_intro` (loading-delay patches will join it here once known) |

A folder `load/<title>/exefs/` with patches at its root is not a mod layout
Eden reads; patches there are inactive. Add a patch by dropping the file in
`patches/`, then `--enable` it.
