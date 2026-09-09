#!/usr/bin/env python3
# run with mcp/.venv/bin/python (the MCP server's environment)
"""One smm2-hooks tool from the command line, for a GUI or a script that is
not an MCP client:

    python3 mcp/ctl.py eden_state
    python3 mcp/ctl.py eden_launch '{"gdb": false}'
    python3 mcp/ctl.py level_install '{"slot": 3, "level": "Packed Row R4"}'
    python3 mcp/ctl.py eden_unpause

Runs the same functions the MCP server registers (server.py, unwrapped), in a
fresh process, and prints the result as one JSON line. Anything that holds
state across calls in the server (the GDB session) is composed here into a
single call: eden_unpause = attach, continue, detach. game_boot waits for the
whole navigation, not just the server's reply budget, since the thread would
die with this process.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import server  # noqa: E402  (imports eden, the tools and FastMCP; does not serve)

TOOLS = {
    "eden_state", "eden_launch", "eden_kill", "eden_set_gdbstub", "eden_log",
    "game_status", "game_boot", "game_input", "levels_list", "level_install", "level_restore",
    "trace_record",
}


def plain(name: str):
    """The tool's underlying function (the @tool wrapper keeps it as __wrapped__)."""
    fn = getattr(server, name)
    return getattr(fn, "__wrapped__", fn)


def eden_unpause() -> dict:
    """A game left waiting for a debugger (the GDB stub on): attach, continue, detach."""
    attached = plain("gdb_attach")()
    if attached.get("error"):
        return {"error": f"attach failed: {attached['error']}", "attach": attached}
    resumed = plain("gdb_continue")()
    detached = plain("gdb_detach")()
    return {"attach": attached, "continue": resumed, "detach": detached}


def main(argv: list[str]) -> int:
    if len(argv) < 2 or argv[1] in ("-h", "--help"):
        print(__doc__)
        return 2
    name = argv[1]
    args = json.loads(argv[2]) if len(argv) > 2 and argv[2].strip() else {}
    if name == "eden_unpause":
        result = eden_unpause()
    elif name in TOOLS:
        if name == "game_boot":
            args.setdefault("budget", 170)
        result = plain(name)(**args)
        if name == "game_boot":
            t = server._NAV.get("thread")
            if t is not None and t.is_alive():
                t.join()
                result = dict(server._NAV["result"])
    else:
        result = {"error": f"unknown tool {name!r}", "tools": sorted(TOOLS | {"eden_unpause"})}
    print(json.dumps(result, default=str))
    return 1 if isinstance(result, dict) and result.get("error") else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
