# Status System Spec

## Scene Modes (GPM inner+0x14)

| Mode | Name | Description |
|------|------|-------------|
| 0 | Loading/Transition | Loading screens, UI transitions, Coursebot details popup |
| 1 | Editor | Course Maker edit mode |
| 5 | Editor Play | Test-play from Course Maker (B+MINUS) |
| 6 | Title | Title screen, main menu, Play menu |
| 7 | Coursebot Play | Playing a course from Coursebot (play-only, no editing) |

**Note**: Scene mode 0 can persist during UI animations and loading. Use frame advancement to verify game is responsive.

## Requirements

### status.bin must ALWAYS reflect reality
1. **Frame counter must advance in ALL scenes** — title, menu, editor, play, loading
2. **`has_player` must be 0 when there is no valid player** — in editor, menu, loading
3. **`has_player` must be 1 only when actively reading a live player** — in play mode
4. **Player data (state, pos, vel) must reflect the CURRENT player** — not a stale pointer from a previous scene

### Input injection must work in ALL scenes
1. Buttons (A, B, MINUS, L+R, D-pad) must work in play mode AND editor AND menus
2. Analog stick must work in play mode (required for 3DW)
3. Input file: 16 bytes `buttons(u64) + stick_lx(i32) + stick_ly(i32)`

### Navigation must be verifiable
1. After any navigation action (MINUS, A, L+R), we must be able to CONFIRM what screen we're on
2. Detection must NOT rely on player state (title screen has a real player too)
3. Detection SHOULD use: frame advancement + screenshot + known UI markers

## Current Bugs

### Bug 1: Stale player pointer (CRITICAL)
**Symptom**: After death→editor transition, status.bin keeps reporting state=113 and the dead player's position forever.
**Cause**: `s_player` is set by changeState hook. After death, the PlayerObject is destroyed but `s_player` still points to freed memory. The memory happens to retain the last values.
**Fix**: Clear `s_player` when state_frames stops advancing (stale detection). Already partially implemented — needs testing.

### Bug 2: procFrame_ doesn't fire in editor
**Symptom**: status.bin frame counter freezes when in editor mode.
**Cause**: `procFrame_` (0x71002ABB50) only fires during gameplay scenes.
**Fix**: Fallback update from NpadStates hook. Already implemented — `update_from_input_poll()` fires in all scenes.

### Bug 3: automate.py reads wrong SD path when imported as module
**Symptom**: `read_status()` returns stale data from Ryujinx path instead of Eden.
**Cause**: `--eden` flag is checked via `sys.argv` at module load time. When importing as a module, it's not set.
**Fix**: Make `SD_BASE` configurable via function call, not just argv.

### Bug 4: Navigation can't distinguish title screen from gameplay
**Symptom**: `fresh` thinks it's in play mode when it's actually on the title screen demo.
**Cause**: Title screen has a real PlayerObject (state=1, has_player=1). `fresh` checks for has_player=1 to confirm play mode.
**Fix**: Use screenshot + phase + frame behavior to detect screen. Or: after L+R, wait for the title screen to disappear (phase change, or frame counter reset).

## Architecture

```
[Game Process]
  procFrame_ hook → status::update(frame)     // gameplay only
  NpadStates hook → status::update_from_input_poll()  // ALL scenes (fallback)
  changeState hook → captures s_player pointer // only on state transitions

[status.bin] (100 bytes, written every frame)
  frame, phase, player data, theme, style, GPM inner dump

[Host: automate.py / emu_session.py]
  Reads status.bin for game state
  Writes input.bin for button/stick injection
  Takes screenshots for visual verification
```
