# Direct boot

Boot straight into a Coursebot course, no title input, no menus.

```
# sd:/smm2-hooks/boot.txt   (read once at boot)
coursebot 5 4        # play Coursebot entry 5; 4 = cMyCourseToNormalPlay (3 = cRoboToEdit opens it in the editor)
```

Measured on Eden with `skip_intro` on: title at 8 s, Coursebot play at 16 s
after launch (the menu walk took until 53 s). The mod waits 150 frames of
title, then replays the Coursebot's Play button: the four calls of its
play-start `sub_71016E5C10`, ending in `SceneMgr::requestChangeScene`
(`sub_71006500C0`, manager `qword_7102A390D8`) for scene 4, the scene that
hosts both the title and normal play. It retries every 90 frames up to 8
times and logs to `sd:/smm2-hooks/directboot.log`:

```
config coursebot 5 kind 4
366,requested coursebot 5 kind 4 (try 1, go -> 1)
404,left title after 1 tries (scene mode 0)
```

**Known limit:** the entry index does not reach a loader yet. The
Coursebot's Play button acts on a course that was loaded into memory when
the entry was selected in its UI; the replayed transition switches scene 4
into play mode on whatever course is resident at the title (all entries
0–13 played the same course in a sweep). The missing call is the
Coursebot's course load for an entry; until it is replayed, the direct
boot is a fast way into *a* playable course, not into a chosen one.

Remove or empty `boot.txt` for a normal title boot (`tools/trace.py`
deletes it right after launch). The scene ids and the
transition-kind enum (`cNetworkError, cTitleToRobo, cTitleToNetwork,
cRoboToEdit, cMyCourseToNormalPlay, ...`, a string at `0x71022E03FB`) are
in the smm2-decomp notes; the entry index is the Coursebot entry (the slot
files are `course_data_NNN.bcd`).

## One-shot recordings

`tools/trace.py` puts it together: it writes `boot.txt`, installs a probe
config (or a preset), launches Eden, waits for Coursebot play, holds the
buttons of `--walk` while sampling `status.bin`, stops Eden and decodes the
log.

```
python3 tools/trace.py --preset rail --coursebot 5 --walk RIGHT:9 -o rail.csv
python3 tools/trace.py --probe spawn.txt --coursebot 5 --walk RIGHT:9,LEFT:22 -o persist.csv
```
