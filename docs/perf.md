# Performance mode (`perf.txt`)

For runs nobody watches: the game logic at full speed on a picture that is
not drawn. With the flag on, the mod makes seven functions do nothing, the
set [MM2Chaos](https://github.com/waluigi3/MM2Chaos) stubs for a simulator on a
cheap CPU (`src/perf.cpp`, symbols in `syms/main.sym`):

| function | what stops |
|---|---|
| `trySetLayoutMsg` | the recursive text layout (reports "not set") |
| `drawRenderStep_` | drawing |
| `calcLayerDL_`, `calcSubLayerDL_` | the layers' display lists |
| `pushBackToJobQueue_` | the model job queue |
| `xlink_calc` | sound and effect links |
| `SnapshotTextureMgr_update` | the course thumbnail snapshot |

It is off by default: without the flag none of the seven is hooked.

One function takes one hook. A probe (docs/probe.md) on one of the seven
reads `hooked` in its `H` line while the flag is on, and a function a probe
already holds when the flag comes on keeps the probe and is not stubbed.

## The flag

`sd:/smm2-hooks/perf.txt` reading `on`. Any other content, or no file, is off.

```
python3 tools/perf.py on        # writes the file
python3 tools/perf.py off       # removes it
python3 tools/perf.py status
```

The mod reads it at boot and again at every scene change, like `probe.txt`
(docs/probe.md), so it reaches a running game when the course next starts.

With the flag on the window is black and the pause menu does not open, so
Start Over is not there to make that scene change. A death is: drop the
player with `printf 'place 72 -300 5\n' > <sd>/smm2-hooks/ctl.txt`
(docs/direct-boot.md) and the course restarts, which loads a changed
`perf.txt` and `probe.txt`. Turned off that way on Eden, the picture came
back whole. Runs that need the menus (`game_boot` through Coursebot,
`Game.start_over`) want the flag off; a direct boot with a `tas.csv` script
does not care.

## What it does to the game

Nothing a recording can see. The same scripted run (the `bump-wall` course by
direct boot, an anchored `tas.csv`: right for 82 frames, a jump at 204)
recorded with `trace_record` and the `player` preset gave the same 400 player
rows, every field, with the flag off and on, and the flag-off rows equal
those of the mod before this mode existed.

## Frame rate

```
$ python3 tools/perf.py fps ../smm2-decomp/src-sim/test/fixtures/bump-wall_course_052.bcd
bump-wall_course_052.bcd, 20 s of play with no input, Eden's speed limit off
  perf off    197.7 frames/s  (3957 frames in 20.01 s; play 15.1 s after launch)
  perf on     265.1 frames/s  (5306 frames in 20.01 s; play 14.6 s after launch)
  ratio    1.34x
```

One run of each on Eden v0.2.1 (Vulkan, Windows, driven from WSL), 2026-11-16.
`fps` boots the course from the title twice (docs/direct-boot.md), lifts
Eden's speed limit for the two launches (`use_speed_limit` in its
`qt-config.ini`, put back afterwards) and counts the mod's frame counter in
`status.bin` against the clock. It stops a running Eden first. The figure is
the emulator's whole frame, GPU presentation included; a host without a GPU
has more to gain from the stubs than this one.
