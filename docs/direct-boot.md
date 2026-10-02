# Direct boot

Boot straight into a chosen course from the title — no TAS menu walk.

```
# sd:/smm2-hooks/boot.txt   (read once at boot)
coursebot 5 4
file sd:/smm2-hooks/course_045.boot.bin
```

- `coursebot <index> [kind]` — fire the Coursebot Play transition
  (`4` = `cMyCourseToNormalPlay`, `3` = `cRoboToEdit`). The index alone does
  **not** load that Coursebot entry's bytes; play uses whatever sits in the
  play buffer.
- `file <sd path>` — before the request, copy that image into the play buffer
  (`[[0x7102A39088]+0x20]+0x6C000`). The file is a `.bcd`'s 0x10-byte header
  plus its decrypted body (`0x5BFC0` bytes), with `SCDL` at `+0xC`. Helpers:
  `tools/directboot_cfg.py` (`write_slot_boot` from a Coursebot `.bcd`).

Measured on Eden with `skip_intro` on: title at ~8 s, Coursebot play at ~16 s
after launch (the menu walk took until ~53 s). The mod waits 150 frames of
title, then replays the four calls of Coursebot Play-start
`sub_71016E5C10`, ending in `SceneMgr::requestChangeScene` for scene 4. It
retries every 90 frames up to 8 times and logs to
`sd:/smm2-hooks/directboot.log`.

Verified (hooks #50): with `file` naming a melody-loop course (SMB1 forest)
then an SMW course, Eden boots from the title straight into each file's
course (scene mode 7, that file's style/theme/start). Without `file`, the
same request plays the resident title course.

Remove or empty `boot.txt` for a normal title boot (`tools/trace.py` and
`game_boot` delete it right after launch). `mcp/server.py` `game_boot`
(coursebot, default) writes the pair and relaunches Eden; pass
`via_menu=true` for the old button-injection walk.

## One-shot recordings

`tools/trace.py` writes `boot.txt` (+ `file` from the slot's `.bcd` when
present), installs a probe, launches Eden, waits for Coursebot play, holds
`--walk` while sampling `status.bin`, stops Eden and decodes the log.

```
python3 tools/trace.py --preset rail --coursebot 5 --walk RIGHT:9 -o rail.csv
python3 tools/trace.py --probe spawn.txt --coursebot 5 --walk RIGHT:9,LEFT:22 -o persist.csv
python3 tools/trace.py --preset rail --coursebot 5 --menu -o rail.csv   # TAS UI instead
```
