# Frame capture: the game one frame at a time, beside the sim

A side-by-side video of a course in Eden and in smm2-sim, one video frame per
game frame. Screen recording cannot do this: Eden does not hold 60 fps under
a capture, and a recording cannot say which game frame each picture is.

## How the game is slowed down

The mod holds the game itself (`src/hold.cpp`). With `sd:/smm2-hooks/hold.txt`
present at boot, every frame ends, after everything else in the mod's
`procFrame_` hook, by:

1. writing the frame number to `sd:/smm2-hooks/held.bin`, then
2. sleeping in 1 ms steps until `sd:/smm2-hooks/ack.bin` (a u32) is at least
   that frame number.

The game's main thread is parked between two frames, so no game time passes.
Eden keeps showing the frame that was just drawn. The host grabs the window,
writes the frame number to `ack.bin`, and the game runs exactly one more frame.
The game runs as fast as the capture loop goes (about 10 frames per second).
Each picture is a different frame, with none skipped or repeated.

`hold.txt` reading `player` lets the game run free until this play's player is
first seen (`status::player_since`), so the capture starts on the play's first
frame however long the boot takes. When the player dies the hold is off again
until the restart's player appears, so a capture shows each attempt with a gap
between them. A missing `ack.bin` means run free. Remove `hold.txt` and relaunch
to turn it off. Without it, the mod behaves as before.

## Steps

1. Build and deploy the mod (`ninja -C build`, then copy `build/exefs/subsdk4`
   to the active mods dir from `eden_state`, `paths.mods_dir`).
2. Arm the hold (SD dir = `paths.sd_hooks_dir`):
   ```bash
   SD=/mnt/c/Users/<user>/AppData/Roaming/eden/sdmc/smm2-hooks
   printf 'player\n' > $SD/hold.txt; printf '\0\0\0\0' > $SD/ack.bin; rm -f $SD/held.bin
   ```
3. Start the capture loop **before** the boot, in the background (stdin from
   `/dev/null`: a Windows child reads WSL's stdin otherwise):
   ```bash
   cp tools/frame_capture.ps1 /mnt/c/temp/smm2_debug/
   cd /mnt/c/temp && powershell.exe -NoProfile -ExecutionPolicy Bypass \
     -File 'C:\temp\smm2_debug\frame_capture.ps1' \
     -Sd 'C:\Users\<user>\AppData\Roaming\eden\sdmc\smm2-hooks' \
     -Out 'C:\temp\smm2_debug\<name>-frames' -Count 1300 </dev/null
   ```
   It saves `<game frame>.png` (the whole client area: Eden's menu bar, the
   picture, the status bar) and writes ack = 0xFFFFFFFF when it is done, so the
   game runs free again.
4. Boot the course: `mcp/.venv/bin/python mcp/ctl.py game_boot '{"target":"coursebot","slot":<n>}'`
   (direct boot). The first held frame is the player's first frame.
5. Sim frames: serve a smm2-sim build (`npx vite build`, then
   `mcp/scripts/devserver.sh start-static <smm2-sim>/dist/static <port>` from
   mission-control). Only `slot-0..9` are prerendered, so the script opens
   slot-0 and calls `__sim.loadCourse(<slot>)`. Then `__sim.tick(0)` and a
   canvas screenshot per frame:
   ```bash
   PLAYWRIGHT_FROM=<a dir with node_modules/playwright> \
     node tools/sim_frames.mjs http://localhost:<port> <sim dir> 1300 <sim slot>
   ```
   The script sends no input. Courses where the player moves need the
   recording's inputs fed into `tick`.
6. Find the offset. The sim and the game do not start their actors on the same
   frame (Goomba Drop: the sim idles 66 ticks first). Track one object's height
   in both frame sets (a colour mask on a column of the picture) and match a
   stretch of its motion. A bounce's rise is a good one. Check it on a contact
   sheet before encoding.
7. Stitch (needs `ffmpeg` on PATH):
   ```bash
   python3 tools/side_by_side.py <eden dir> <sim dir> out.mp4 <first eden frame> <count> --sim-offset 66 --fps 60
   ```
   Use `--fps 15` for a copy that is easier to step through. The crop boxes in
   the script assume a 1280-wide Eden window and the sim at a 1280x900
   viewport; measure them again if either changes.
8. Clean up: `rm $SD/hold.txt $SD/ack.bin $SD/held.bin`.

## First use

Goomba Drop (smm2-sim slot 90, Coursebot slot 48), 2026-10-14: 1300 frames
from game frame 864, 579 frames to the first death (the winged Koopa, game
frame 1441), sim offset 66. Every capture differed from the one before it.
PrintWindow under Vulkan did not return stale pictures while the game was held.
