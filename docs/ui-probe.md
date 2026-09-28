# UI probe (`ui-probe.txt` → `ui-probe.log`)

Reads the menu text the game draws, which control has the focus, and on the
Coursebot grid which course slot that is. v3.0.3 only. Read-only: no
game state is written unless the `print=` test mode below is used.

## Setup

Write `capture` into `sd:/smm2-hooks/ui-probe.txt` and (re)launch the
game; the file is read once at boot. Without it the probe installs nothing.

```
python3 tools/ui_probe.py <sd>/smm2-hooks/ui-probe.log --screen   # what is on screen now
```

MCP: `ui_screen` (and every `game_input` returns the same view after its
press). Python: `Game.ui()`, `Game.focus(label)`, `Game.select_slot(n)`;
`Game.to_coursebot_play` uses them when the probe is running.

## What it reads

| Fact | Where it comes from |
|---|---|
| text | every `nn::ui2d::TextBox` drawn (hook on `TextBox::DrawSelf`, 0x71004C38B0): UTF-16 at +0xD8, length u16 +0x112 |
| identity | pane name `char[24]` +0xB0 and the names of its ancestors (parent +0x18), e.g. `RootPane/N_All_00/N_Content_00/N_Message_00/T_Message_00` |
| on screen | global matrix at +0x70 (x = f32 +0x7C, y = f32 +0x8C, 1280x720, origin at the centre); panes outside it are drawn but not visible (the course details panel waits below the screen) |
| focus | the game's own focus change: `sub_7101B615E0(button, 0, ...)` runs on the button gaining focus (and `sub_7101B61810(button, 1, ...)` on the one losing it); the button's pane path, e.g. `/L_CourseDataList_01/L_CourseBtn_01`, is an inline string at `*(button+0x58)+0xA0`. The focused text is the drawn pane under that path |
| active layer | ui2d draws back to front, so what was drawn before the focused control's layout is under it (the grid behind the details, the details behind a dialog) |
| course slot | hook on `sub_7101897360(screen, tile, slot)`, which binds course `slot` to tile `tile` of the Coursebot table at 0x7102CC0E78; tile 4R+C is `/L_CourseDataList_0R/L_CourseBtn_0C` |
| glyphs | U+E0E0.. A B X Y L R (Y, L, R seen on screen); other private-use characters stay `[U+XXXX]` |

## Menus it was checked on

Main menu, Coursebot grid (scrolled both ways), course details and its
tab bar, the upload dialog ("You need to clear your course before
uploading it."), the Coursebot pause menu. The pause menu opens with
nothing focused: the game makes no focus call until the first direction
press, which lands on its first control; `focus()` makes that press.

## Log format

```
UI_PROBE,4,303,draw_submission,mode=capture
INSTALLED
BEGIN,<seq>,<rows>,<dropped>,<print pane>,<tick>
TEXT,<pane>,<enc>,<len>,<cap>,<flags>,<alpha>,<name hex>,<text hex>,<tick>,<order>,<root>,<ancestor names hex, nearest first, '/'>,<pane+0x30..0x90 hex>
FOCUS,<tick of the focus call>,<button pane path>
SLOTS,<slot of tile 0>,...,<slot of tile 19>
END,<seq>
```

One sample every 30 frames; a row belongs to the current frame when its
tick equals the newest tick in the sample.

## Print test

`print=<pane name>` and `expect=<current ASCII text>` on two lines replace
that one label with `UI PROBE OK` through the game's own setter
(0x71004C3BB0). A normal boot restores it.
