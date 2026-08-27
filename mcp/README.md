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

GDB rules enforced by the server: no software breakpoints (`break` is refused),
no `handle SIGTRAP ... pass`, one session, commands only while stopped.

Register in a Claude Code project `.mcp.json`:

    "smm2-hooks": { "command": "/home/nico/code/smm2-hooks/mcp/.venv/bin/python",
                    "args": ["/home/nico/code/smm2-hooks/mcp/server.py"] }
