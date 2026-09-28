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
press). Python: `Game.ui()`, `Game.wait_until(condition)`, `Game.focus(label)`,
`Game.select_slot(n)`; `Game.to_coursebot_play` uses them when the probe is
running. Navigation waits on the game, not the clock: a press goes in once
the menus are `ready` and a control is focused, and its result is the next
settled sample that shows the focus moved, or two settled samples (60
frames) without a change, meaning the game ignored it. The only timeout is
a hang guard that raises with the screens and transitions it was stuck in.

## What it reads

| Fact | Where it comes from |
|---|---|
| text | every `nn::ui2d::TextBox` drawn (hook on `TextBox::DrawSelf`, 0x71004C38B0): UTF-16 at +0xD8, length u16 +0x112 |
| identity | pane name `char[24]` +0xB0 and the names of its ancestors (parent +0x18), e.g. `RootPane/N_All_00/N_Content_00/N_Message_00/T_Message_00` |
| on screen | global matrix at +0x70 (x = f32 +0x7C, y = f32 +0x8C, 1280x720, origin at the centre); panes outside it are drawn but not visible (the course details panel waits below the screen) |
| focus | the game's own focus change: `sub_7101B615E0(button, 0, ...)` runs on the button gaining focus (and `sub_7101B61810(button, 1, ...)` on the one losing it); the button's pane path, e.g. `/L_CourseDataList_01/L_CourseBtn_01`, is an inline string at `*(button+0x58)+0xA0`. The focused text is the drawn pane under that path |
| active layer | ui2d draws back to front, so what was drawn before the focused control's layout is under it (the grid behind the details, the details behind a dialog) |
| course slot | hook on `sub_7101897360(screen, tile, slot)`, which binds course `slot` to tile `tile` of the Coursebot table at 0x7102CC0E78 (empty slots too), and on `sub_7101897190(screen, tile)`, which empties a tile; tile 4R+C is `/L_CourseDataList_0R/L_CourseBtn_0C` |
| screen state | the menus run `Lp::Utl::StateMachine` like the actors. Hooks on `changeState` (0x71008B9320), the per-frame execute (`sub_71008B9490`) and `finalize` (0x71008B8F40) keep the machines that have an `Appear`, `Disp` or `LoadEnd` state: current state (+0x08), frames in it (+0x0C), and every state name (array at +0x40, 16 bytes each, char* at +8, count at +0x38). A machine is named by a state only it has, e.g. `TitleBack` = main menu, `OpenConfirmDelete` = Coursebot list, `YesBtn` = yes/no dialog, `RetryCourse` = pause menu, `LoadEnd` = loader |
| ready | some running screen is in a `Disp*` state and none is appearing, disappearing, opening, closing, leaving (`To*`) or loading; a machine is running when the game executed it in the last 30 frames |
| glyphs | U+E0E0.. A B X Y L R (Y, L, R seen on screen); other private-use characters stay `[U+XXXX]` |

## Menus it was checked on

Eden v0.2.0-rc1 and Ryujinx 1.3.3, SMM2 v3.0.3 in both.

Main menu, Coursebot grid (scrolled both ways), course details and its
tab bar, the upload dialog ("You need to clear your course before
uploading it."), the Coursebot pause menu. The pause menu opens with
nothing focused: the game makes no focus call until the first direction
press, which lands on its first control; `focus()` makes that press. An
empty Coursebot tile draws no text: the focus is still reported (with its
slot) while any tile of the grid is drawn, and `focused` is then None.

## Log format

```
UI_PROBE,6,303,draw_submission,mode=capture
INSTALLED
BEGIN,<seq>,<rows>,<dropped>,<print pane>,<tick>
TEXT,<pane>,<enc>,<len>,<cap>,<flags>,<alpha>,<name hex>,<text hex>,<tick>,<order>,<root>,<ancestor names hex, nearest first, '/'>,<pane+0x30..0x90 hex>
MACHINE,<machine>,<state count>,<name 0>|<name 1>|...     (once per machine)
STATE,<machine>,<tick of last change>,<changeState caller offset>,<state>,<frames in state>,<state name>,<tick last executed>
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
