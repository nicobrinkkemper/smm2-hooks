# Theme override

`sd:/smm2-hooks/theme.txt` holds one number, 0 to 255. Every course the game
loads then gets that theme in its main area. Without the file nothing is
hooked. The mod reads the file once at boot, so relaunch the game after
changing it.

The game's own themes are 0 to 9. A theme installed in slot 10 has no button
in the editor, and this is the way to reach it.

## How

`sub_7100E3BA90` copies the course file into the buffer at `[obj+0x28]`, file
header included, so the main area's theme byte sits at `+0x210` in that
copy. `src/theme_override.cpp` hooks the function, lets the copy run and
then writes the byte. The status block shows the result as `theme`
(`python3 mcp/ctl.py game_status`).

## Measured

Castle Flat (theme 2) in Coursebot play, Eden, v3.0.3:

| `theme.txt` | status theme | what the course looks like |
|---|---|---|
| absent | 2 | Castle: grey stone, lava |
| `9` | 9 | Forest: trees, and the lava is Forest's poison |
| `10` | 10 | brown ground, a black sky with twinkling stars, no lava; runs at 60 FPS |

Theme 10 does not crash the game with nothing installed there.

## Not covered and not tried

- The hook changes every course the game loads through this function,
  the editor's included. Saving a course while the override is on was not
  tried. The change lives in memory, so the file on disk stays as it was
  unless the game writes the modified copy back.
- Only the main area. The sub area's theme is the same field in the second
  area (`+0x2E0F0` in this copy).
- The file's CRC (header `+0x08`) is not updated. The game did not check it
  on this load.
