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

## A course file into the editor

`game_boot(target="editor", file=<course>)` boots any course straight into the
editor (kind 3, scene_mode 1, ~15 s): a `.bcd`, the sim dataset's `.zlib`, or a
plain body. It never passes Coursebot, so nothing is installed into a slot and
nothing can be deleted as invalid. The editor opens as Coursebot entry `slot`
(0 without one), so leave without saving. `sub_area=true` swaps the two areas
(`0x2DEE0` each at body `+0x200`) so the sub area opens. In the editor, press X
for the finger cursor, then hold the stick to scroll:
`game_input(stick="0,32767", ms=5000)` scrolls up.

A real uploaded course passes the game's own checks. `tools/hf_course.py
<data_id> -o <dir>` fetches one from the TheGreatRambler/mm2_level dataset
(26.6M courses, through 2022) by binary search over huggingface's
datasets-server, with no dump to download.

## Slot backups around Coursebot

A Coursebot visit deletes the installed courses it finds invalid ("Corrupt data
was found"), registered or not, the one you asked for or another. Before every
`game_boot(target="coursebot")` every slot's `course_data_NNN.bcd` is copied to
`~/.cache/smm2-hooks/slot-backups/pool/<sha1>.bcd` (each content once), with
`<stamp>.json` mapping slots to files. The result names that manifest, and
`slots_changed` / `slots_unregistered` plus a `warning` appear when a slot
changed by the time the boot finished. A deletion later, when play returns to
the Coursebot list, is not in that result; the manifest still has the files.

## One-shot recordings

`tools/trace.py` writes `boot.txt` (+ `file` from the slot's `.bcd` when
present), installs a probe, launches Eden, waits for Coursebot play, holds
`--walk` while sampling `status.bin`, stops Eden and decodes the log.

```
python3 tools/trace.py --preset rail --coursebot 5 --walk RIGHT:9 -o rail.csv
python3 tools/trace.py --probe spawn.txt --coursebot 5 --walk RIGHT:9,LEFT:22 -o persist.csv
python3 tools/trace.py --preset rail --coursebot 5 --menu -o rail.csv   # TAS UI instead
```
