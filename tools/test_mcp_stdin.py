#!/usr/bin/env python3
"""The MCP server answers every request while a tool runs a Windows program.

Run: python3 tools/test_mcp_stdin.py      (WSL, needs powershell.exe; ~10 s)

A Windows program started from WSL reads its parent's stdin through the
interop relay. The server's stdin is the host's request stream, so a tool
that ran PowerShell (eden_state does, twice) could swallow requests that
arrived meanwhile; those never got a reply and the host hung on them. The
server now moves the stream off fd 0 (server.py, _keep_stdin_for_the_protocol).

This starts the server over stdio, calls eden_state three times and sends
60 pings 50 ms apart behind them, and requires a reply to every one. Without
the fix it lost 8 of the 64, both runs.
"""

import json
import os
import select
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
venv = ROOT / "mcp" / ".venv" / "bin" / "python"
python = str(venv) if venv.exists() else sys.executable

p = subprocess.Popen([python, str(ROOT / "mcp" / "server.py")], cwd=str(ROOT),
                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)


def send(msg: dict) -> None:
    p.stdin.write((json.dumps(msg) + "\n").encode())
    p.stdin.flush()


send({"jsonrpc": "2.0", "id": 1, "method": "initialize",
      "params": {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "test", "version": "1"}}})
send({"jsonrpc": "2.0", "method": "notifications/initialized"})
ids = [1]
for k in range(3):
    send({"jsonrpc": "2.0", "id": 100 + k, "method": "tools/call", "params": {"name": "eden_state", "arguments": {}}})
    ids.append(100 + k)
for i in range(60):
    send({"jsonrpc": "2.0", "id": 200 + i, "method": "ping"})
    ids.append(200 + i)
    time.sleep(0.05)

# Raw reads: select() on a buffered readline misses lines already buffered.
got, buf, fd, end = set(), b"", p.stdout.fileno(), time.time() + 60
while time.time() < end and len(got) < len(ids):
    if not select.select([fd], [], [], 1)[0]:
        continue
    chunk = os.read(fd, 65536)
    if not chunk:
        break
    buf += chunk
    *lines, buf = buf.split(b"\n")
    for line in lines:
        try:
            got.add(json.loads(line).get("id"))
        except ValueError:
            pass
p.kill()

missing = [i for i in ids if i not in got]
print(f"{len(ids) - len(missing)} of {len(ids)} requests answered" + (f"; missing {missing}" if missing else ""))
sys.exit(1 if missing else 0)
