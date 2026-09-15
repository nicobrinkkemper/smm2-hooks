# smm2-hooks MCP

An MCP server so an agent can drive Eden + the hook mod without guessing paths or modes.

    mcp/.venv/bin/python mcp/server.py          # stdio server
    mcp/.venv/bin/python mcp/server.py --selftest

Setup: `python3 -m venv mcp/.venv && mcp/.venv/bin/pip install -r mcp/requirements.txt`.
Needs `gdb-multiarch` on PATH for the GDB tools.

`mcp/eden.py` is the state model. It finds Eden's real user directory (portable
`user/` next to `eden.exe`, else AppData), reads `qt-config.ini` for the NAND,
SD and `load` directories and the GDB stub setting, and derives everything else
(save slots, `status.bin`, deployed mod, log file). `eden_state` returns one
`mode`:

| mode | meaning |
|------|---------|
| `off` | no eden.exe |
| `launching_or_frozen` | process up, no fresh `status.bin` |
| `waiting_for_debugger_or_paused` | stub enabled and listening, no fresh status: attach GDB and continue |
| `title` / `editor` / `editor_play` / `coursebot_play` / `loading` | from `status.bin` `scene_mode` |

`edit_time` is the Course Maker editor (no actors run, no player); `run_time` is
`editor_play` or `coursebot_play` (actors update, `has_player` is meaningful).

`eden.py` also runs standalone, for shells and external monitors:

    python3 mcp/eden.py            # full state as JSON
    python3 mcp/eden.py --brief    # one line: pid, memory, start time, scene, frame; exit 1 when off
    python3 mcp/eden.py --kill     # Stop-Process eden; exit 1 if it is still there afterwards
    python3 mcp/eden.py --launch   # start Eden with the game (no GDB stub); exit 1 if already running or it never came up

`--brief` reads only the process list and `status.bin` (no GDB port probe), so
it is cheap enough to poll every few seconds.

GDB rules enforced by the server: no software breakpoints (`break` is refused),
no `handle SIGTRAP ... pass`, one session, commands only while stopped.

Register it for Claude Code on the machine that has Eden and the game (local
scope: this project on this machine, not the project's shared `.mcp.json`):

    claude mcp add -s local smm2-hooks -- "$PWD/mcp/.venv/bin/python" "$PWD/mcp/server.py"

## The panel

`mcp/panel.py` serves `mcp/panel.html`, the same tools as buttons: launch or
kill the emulator, the live mode, install and restore Coursebot slots, boot a
slot, record a play session, export a slot to the sim app. Every button runs
one tool through `ctl.py`, so the page and the agent see one truth.

    mcp/.venv/bin/python mcp/panel.py --port 5199      # http://127.0.0.1:5199/

Export writes into `$SMM2_SIM_DIR`, else the sibling `../smm2-sim`. A dashboard
that embeds pages (mission-control's Shells rail) points at the URL and uses
that command line to start it.
