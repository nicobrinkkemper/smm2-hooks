# UI probe (`ui-probe.txt` → `ui-screen.txt`)

Reads what SMM2's menus show, which control has the focus, which state each
menu screen is in, and on the Coursebot grid which course slot is focused.
Read-only; v3.0.3 only.

## Setup

Write `capture` into `sd:/smm2-hooks/ui-probe.txt` and (re)launch the
game; the file is read once at boot. Without it the probe installs nothing.
The mod then rewrites `sd:/smm2-hooks/ui-screen.txt` every 6 frames.

```
python3 tools/ui_probe.py <sd>/smm2-hooks/ui-screen.txt          # what is on screen now
python3 tools/ui_probe.py <sd>/smm2-hooks/ui-screen.txt --json   # as ui_screen returns it
```

MCP: `ui_screen`; every `game_input` also returns it as it stands after the
press. Python: `Game.ui()`, `Game.wait_until(condition)`, `Game.focus(label)`,
`Game.select_slot(n)`; `Game.to_coursebot_play` uses them when the probe is
running.

Navigation waits on the game, not the clock. A press goes in once the
menus are `ready` and the focused button's input is switched on. Its answer
is the first settled snapshot after the game read the button that shows the
focus or the slot moved, or, when nothing moves, the one 30 game frames
after that read: the game ignored the press, and the navigation presses
again. The only timeout is a hang guard that raises with the screens and
transitions it was stuck in.

Not modelled yet: a button still animating its last focus change ignores
the next direction (the focus methods check the button's animation
controller at button+0x280 for state 3, `sub_7100690AA0` runs it). Those
presses come back as ignored and are pressed again.

## What it reads

| Fact | Where it comes from |
|---|---|
| text | every `nn::ui2d::TextBox` drawn (hook on `TextBox::DrawSelf`, 0x71004C38B0): UTF-16 at +0xD8, length u16 +0x112 |
| identity | pane name `char[24]` +0xB0 and the names of its ancestors (parent +0x18), e.g. `RootPane/N_All_00/N_Content_00/N_Message_00/T_Message_00` |
| on screen | global matrix at +0x70 (x = f32 +0x7C, y = f32 +0x8C, 1280x720, origin at the centre). Panes outside it are drawn but not visible (the course details panel waits below the screen) |
| focus | the game's own focus change: `sub_7101B615E0(button, 0, ...)` runs on the button gaining focus and `sub_7101B61810(button, 1, ...)` on the one losing it. The button's pane path, e.g. `/L_CourseDataList_01/L_CourseBtn_01`, is an inline string at `*(button+0x58)+0xA0`; the focused text is the drawn pane under it |
| active layer | ui2d draws back to front, so what was drawn before the focused control's layout is under it (the grid behind the details, the details behind a dialog) |
| course slot | `sub_7101897360(screen, tile, slot)` binds course `slot` to tile `tile` of the Coursebot table at 0x7102CC0E78, empty slots included; `sub_7101897190(screen, tile)` empties a tile. Tile 4R+C is `/L_CourseDataList_0R/L_CourseBtn_0C` |
| screen state | the menus run `Lp::Utl::StateMachine` like the actors. Hooks on `changeState` (0x71008B9320), the per-frame execute (`sub_71008B9490`) and `finalize` (0x71008B8F40) keep the machines with an `Appear`, `Disp` or `LoadEnd` state: current state (+0x08), frames in it (+0x0C), and the state names (array at +0x40, 16 bytes each, char* at +8, count at +0x38). Machines are read only inside those calls, never after `finalize`. A machine is named by a state only it has: `TitleBack` main menu, `OpenConfirmDelete` Coursebot list, `YesBtn` yes/no dialog, `RetryCourse` pause menu, `LoadEnd` loader |
| ready | some running screen is in a `Disp*` state and none is appearing, disappearing, opening, closing, leaving (`To*`) or loading; a machine is running when the game executed it in the last 12 frames |
| input | a screen switches its buttons' input on and off with `sub_7100761190(button, player, on)` (the enable byte of player 1's handler, at +0x3A in the list at button+0x228). The main menu's `Disp` does it two frames in, the pause menu in the same frame, so `Disp` alone is not enough. `input` is the focused button's switch (read from the button when the game focuses it, then followed); `screen_input` says a switch-on came after the newest screen entered `Disp*`, for a menu that opens with nothing focused |
| buttons read | the Pro Controller buttons the game last read, injected ones included (`tas::seen_buttons()`), and the last frame one was held: a press is answered from the frame the game saw it |
| glyphs | U+E0E0.. A B X Y L R (Y, L, R seen on screen); other private-use characters stay `[U+XXXX]` |

## Where it was checked

Eden v0.2.0-rc1 and Ryujinx 1.3.3, SMM2 v3.0.3 in both: title to the main
menu, the Coursebot grid (scrolled both ways, empty slots), course details
and its tab bar, the upload dialog ("You need to clear your course before
uploading it."), Coursebot play, the pause menu, Exit Course and back.

The pause menu opens with nothing focused: the game makes no focus call
until the first direction press, which lands on its first control;
`focus()` makes that press. Opened again, it draws the same layout as before,
so a focus only counts when the game made it after the screen last entered
an `Appear` state. An empty Coursebot tile draws no text; its
focus and slot are still reported while the grid is drawn.

## `ui-screen.txt`

Rewritten in place like `status.bin`; `BEGIN` and `END` carry the same
sequence, so a read that lands mid-write is seen as torn and read again.

```
BEGIN,<sequence>,<tick>,<rows>,<draws dropped>
TEXT,<tick drawn>,<draw order>,<root pane>,<x>,<y>,<scale>,<0 utf-16|1 bytes>,<pane name>,<ancestor names root first, each followed by '/'>,<text hex>,<length>
FOCUS,<button pane path>,<its input: 1 on, 0 off, -1 not seen>,<tick of the focus call>
INPUT,<tick of the last switch on>,<tick of the last switch off>
PAD,<buttons the game read last, hex>,<tick a button was last held>
STATE,<machine>,<tick last executed>,<tick last changed>,<tick it last entered an Appear state>,<frames in state>,<state name>,<all state names joined by '|'>
SLOTS,<slot of tile 0>,...,<slot of tile 19>
END,<sequence>
```

`tick` counts frames since boot. A row belongs to the latest frame when its
tick equals the newest tick among the rows. A failed setup writes a single
`ERROR,<reason>` line instead.
