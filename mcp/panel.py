#!/usr/bin/env python3
# run with mcp/.venv/bin/python (the MCP server's environment)
"""The emulator control panel: one web page of buttons over the ctl.py tools.

    mcp/.venv/bin/python mcp/panel.py            # http://127.0.0.1:5199/
    mcp/.venv/bin/python mcp/panel.py --port 5200

Every button runs one tool through ctl.py in a fresh process, the same code
the agent's MCP tools run, so the panel and the agent see one truth
(eden_state's `mode`). Three composite actions live here because they span
several tools: play a Coursebot slot from any state, export a slot to the sim
app, and launch or kill Ryujinx (tools/emu_session.py, start and stop only).

The sim app checkout the export writes into is `$SMM2_SIM_DIR`, else the
sibling `../smm2-sim`.

Standard library only; nothing here holds state between requests.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import zlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

HERE = Path(__file__).resolve().parent
HOOKS = HERE.parent
CTL = HERE / "ctl.py"
PAGE = HERE / "panel.html"

# Tool -> how long a call may take, in seconds. game_boot navigates the title
# screen and Coursebot for tens of seconds; everything else answers in seconds.
TOOLS = {
    "eden_state": 20,
    "eden_launch": 60,
    "eden_kill": 30,
    "eden_unpause": 40,
    "eden_set_gdbstub": 15,
    "eden_log": 15,
    "game_status": 15,
    "game_boot": 200,
    "game_input": 20,
    "levels_list": 30,
    "level_install": 30,
    "level_restore": 15,
    "trace_record": 90,
}


def sim_dir() -> Path:
    return Path(os.environ.get("SMM2_SIM_DIR") or HOOKS.parent / "smm2-sim")


def run(args: list[str], timeout: int, cwd: Path = HOOKS) -> tuple[int | None, str, str]:
    """The interpreter running this panel, on `args`; (exit code, stdout, stderr)."""
    try:
        p = subprocess.run([sys.executable, *args], cwd=cwd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as e:
        return None, str(e.stdout or ""), f"timed out after {timeout}s"
    return p.returncode, p.stdout, p.stderr


def tool(name: str, args: dict | None = None) -> dict:
    """One ctl.py tool; the same result shape for every endpoint."""
    started = time.time()
    timeout = TOOLS.get(name)
    if timeout is None:
        return {"ok": False, "tool": name, "error": f"unknown tool {name}", "ms": 0}
    code, out, err = run([str(CTL), name, json.dumps(args or {})], timeout)
    ms = int((time.time() - started) * 1000)
    last = out.strip().split("\n")[-1] if out.strip() else "null"
    try:
        data = json.loads(last)
    except ValueError:
        return {"ok": False, "tool": name, "error": f"bad JSON from ctl.py: {(err or out)[-500:]}", "ms": ms}
    if isinstance(data, dict) and data.get("error"):
        return {"ok": False, "tool": name, "data": data, "error": str(data["error"]), "ms": ms}
    if code != 0:
        return {"ok": False, "tool": name, "data": data, "error": (err or out or f"exit {code}").strip()[-2000:], "ms": ms}
    return {"ok": True, "tool": name, "data": data, "ms": ms}


def mode() -> str:
    data = tool("eden_state").get("data") or {}
    return str(data.get("mode", "off")) if isinstance(data, dict) else "off"


def play_slot(slot: int) -> dict:
    """Coursebot play of a slot from any state: kill a game that is not at the
    title, launch, wait for the title to settle, then navigate."""
    started = time.time()
    steps: list[str] = []
    m = mode()
    steps.append(f"state {m}")
    if m != "title":
        if m != "off":
            tool("eden_kill")
            steps.append("killed")
            time.sleep(3)
        launched = tool("eden_launch", {"gdb": False})
        if not launched["ok"]:
            return {**launched, "tool": "play slot", "data": {"steps": steps}}
        steps.append("launched")
        deadline = time.time() + 150
        while time.time() < deadline:
            time.sleep(3)
            m = mode()
            if m == "title":
                break
        if m != "title":
            return {"ok": False, "tool": "play slot", "error": f"no title screen after launch (mode {m})",
                    "data": {"steps": steps}, "ms": int((time.time() - started) * 1000)}
        time.sleep(5)   # the title needs a moment before it takes input
        steps.append("title")
    boot = tool("game_boot", {"target": "coursebot", "slot": slot})
    data = boot.get("data") if isinstance(boot.get("data"), dict) else {}
    return {**boot, "tool": "play slot", "data": {**data, "steps": steps}}


def export_slot(slot: int) -> dict:
    """A Coursebot slot into the sim app: the course decrypted and zlib-compressed
    to the dataset layout under public/courses/hf, and an entry put at the
    front of the index its "Uploaded levels" menu reads."""
    started = time.time()
    sim = sim_dir()
    hf = sim / "public" / "courses" / "hf"
    if not hf.is_dir():
        return {"ok": False, "tool": "export slot", "error": f"{hf} not found (set SMM2_SIM_DIR)", "ms": 0}
    listed = tool("levels_list")
    save_dir = (listed.get("data") or {}).get("save_dir") if isinstance(listed.get("data"), dict) else None
    if not save_dir:
        return {"ok": False, "tool": "export slot", "error": listed.get("error") or "levels_list gave no save_dir",
                "ms": int((time.time() - started) * 1000)}
    sys.path.insert(0, str(HOOKS / "tools"))
    from parse_course import decrypt_course  # noqa: E402

    raw = decrypt_course(str(Path(save_dir) / f"course_data_{slot:03d}.bcd"))
    if raw is None:
        return {"ok": False, "tool": "export slot", "error": "decrypt failed (missing slot or bad CRC)",
                "ms": int((time.time() - started) * 1000)}
    name = raw[0xF4:0xF4 + 0x42].decode("utf-16-le").rstrip("\0")
    data_id = 900_000_000 + slot     # synthetic dataset id; the sim loads /courses/hf/<id>.zlib
    out = hf / f"{data_id}.zlib"
    out.write_bytes(zlib.compress(raw))
    index_path = hf / "index.json"
    try:
        index = json.loads(index_path.read_text())
    except (OSError, ValueError):
        index = []
    index = [e for e in index if e.get("data_id") != data_id]
    index.insert(0, {"data_id": data_id, "course_id": f"slot-{slot}", "name": f"{name or f'slot {slot}'} (slot {slot})",
                     "style": "", "theme": "", "likes": 0,
                     "source": "Coursebot slot exported from the Eden save, decrypted and zlib-compressed"})
    index_path.write_text(json.dumps(index, indent=2) + "\n")
    return {"ok": True, "tool": "export slot", "ms": int((time.time() - started) * 1000),
            "data": {"name": name, "file": str(out), "url": f"/courses/hf/{data_id}.zlib", "sim": str(sim)}}


def emulator(which: str, action: str, gdb: bool = False) -> dict:
    """Launch or kill an emulator. Eden goes through the hooks bridge; Ryujinx
    only has the older tools/emu_session.py launcher: start and stop, no state."""
    if which == "eden":
        return tool("eden_launch", {"gdb": gdb}) if action == "launch" else tool("eden_kill")
    started = time.time()
    script = HOOKS / "tools" / "emu_session.py"
    if not script.exists():
        return {"ok": False, "tool": f"{action} ryujinx", "error": f"{script} not found", "ms": 0}
    code, out, err = run([str(script), action, "ryujinx"], 60)
    return {"ok": code == 0, "tool": f"{action} ryujinx", "data": {"output": (out + err).strip()[-2000:]},
            "error": None if code == 0 else f"exit {code}", "ms": int((time.time() - started) * 1000)}


def dispatch(path: str, body: dict) -> dict:
    if path == "/api/tool":
        return tool(str(body.get("tool", "")), body.get("args") or {})
    if path == "/api/play-slot":
        return play_slot(int(body.get("slot", 0)))
    if path == "/api/export-slot":
        return export_slot(int(body.get("slot", 0)))
    if path == "/api/emulator":
        return emulator(str(body.get("emulator", "eden")), str(body.get("action", "launch")), bool(body.get("gdb", False)))
    return {"ok": False, "tool": path, "error": "no such endpoint", "ms": 0}


class Handler(BaseHTTPRequestHandler):
    def _send(self, status: int, body: bytes, ctype: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, result: dict) -> None:
        self._send(200, json.dumps(result, default=str).encode(), "application/json")

    def do_GET(self) -> None:  # noqa: N802
        url = urlparse(self.path)
        if url.path in ("/", "/index.html"):
            self._send(200, PAGE.read_bytes(), "text/html; charset=utf-8")
        elif url.path.startswith("/api/tool/"):
            args = parse_qs(url.query).get("args", ["{}"])[0]
            self._json(tool(url.path[len("/api/tool/"):], json.loads(args)))
        else:
            self._send(404, b"not found", "text/plain")

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            self._json({"ok": False, "tool": self.path, "error": "bad JSON body", "ms": 0})
            return
        self._json(dispatch(urlparse(self.path).path, body if isinstance(body, dict) else {}))

    def log_message(self, fmt: str, *args) -> None:
        sys.stderr.write("%s %s\n" % (time.strftime("%H:%M:%S"), fmt % args))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=5199)
    ap.add_argument("--host", default="127.0.0.1")
    a = ap.parse_args()
    if not CTL.exists():
        print(f"{CTL} not found", file=sys.stderr)
        return 1
    srv = ThreadingHTTPServer((a.host, a.port), Handler)
    print(f"smm2-hooks panel: http://{a.host}:{a.port}/  (sim: {sim_dir()})", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
