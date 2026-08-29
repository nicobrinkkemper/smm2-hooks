"""
Truthful Eden state for SMM2 debugging, read from where Eden actually keeps it.

Eden (yuzu family) runs "portable" when a `user/` directory sits next to
eden.exe; its qt-config.ini then names the NAND, SD and mod (`load`)
directories explicitly, which may still live under AppData. Everything here
derives from that ini, never from guesses in .env (only EDEN_EXE and
EDEN_GAME_PATH come from there).
"""
from __future__ import annotations

import os
import re
import struct
import subprocess
import sys
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TOOLS = REPO / "tools"
TITLE_ID = "01009B90006DC000"

SCENE_NAMES = {0: "loading", 1: "editor", 5: "editor_play", 6: "title", 7: "coursebot_play"}
EDIT_TIME = {1}
RUN_TIME = {5, 7}
STATUS_MAX_AGE = 3.0


def _dotenv() -> dict[str, str]:
    out: dict[str, str] = {}
    env = REPO / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def win_to_wsl(p: str) -> str:
    p = p.replace("\\", "/")
    m = re.match(r"^([A-Za-z]):/(.*)$", p)
    return f"/mnt/{m.group(1).lower()}/{m.group(2)}" if m else p


def wsl_to_win(p: str) -> str:
    m = re.match(r"^/mnt/([a-z])/(.*)$", p)
    return f"{m.group(1).upper()}:/{m.group(2)}" if m else p


def windows_host_ip() -> str:
    out = subprocess.run(["ip", "route"], capture_output=True, text=True).stdout
    for line in out.splitlines():
        if line.startswith("default"):
            return line.split()[2]
    return "127.0.0.1"


@dataclass
class EdenPaths:
    exe: str
    game: str
    user_dir: str          # where config/ and log/ live
    portable: bool
    config_ini: str
    nand_dir: str
    sdmc_dir: str
    load_dir: str
    log_file: str
    save_dir: str | None   # .../nand/user/save/<uid>/<user>/<title>
    sd_hooks_dir: str      # <sdmc>/smm2-hooks (status.bin, input.bin)
    mods_dir: str          # <load>/<title>/smm2-hooks/exefs
    alt_mods_dir: str      # <exe dir>/load/<title>/smm2-hooks/exefs (portable variant)


def _read_ini(path: str) -> dict[str, str]:
    vals: dict[str, str] = {}
    try:
        for raw in Path(path).read_bytes().decode("utf-8", "replace").splitlines():
            line = raw.strip("\r")
            if "=" in line and not line.startswith("["):
                k, v = line.split("=", 1)
                vals[k.strip()] = v.strip()
    except FileNotFoundError:
        pass
    return vals


def paths() -> EdenPaths:
    env = _dotenv()
    exe = env.get("EDEN_EXE", "/mnt/c/Users/nico/Documents/eden/eden.exe")
    game = env.get("EDEN_GAME_PATH", "")
    exe_dir = str(Path(exe).parent)
    portable_user = f"{exe_dir}/user"
    portable = os.path.isdir(portable_user)
    user_dir = portable_user if portable else win_to_wsl(os.environ.get("EDEN_APPDATA", "C:/Users/nico/AppData/Roaming/eden"))
    ini = f"{user_dir}/config/qt-config.ini"
    vals = _read_ini(ini)
    nand = win_to_wsl(vals.get("nand_directory", f"{wsl_to_win(user_dir)}/nand"))
    sdmc = win_to_wsl(vals.get("sdmc_directory", f"{wsl_to_win(user_dir)}/sdmc"))
    load = win_to_wsl(vals.get("load_directory", f"{wsl_to_win(user_dir)}/load"))
    save_dir = None
    for p in Path(f"{nand}/user/save").glob(f"*/*/{TITLE_ID}"):
        save_dir = str(p)
        break
    return EdenPaths(
        exe=exe, game=game, user_dir=user_dir, portable=portable, config_ini=ini,
        nand_dir=nand, sdmc_dir=sdmc, load_dir=load,
        log_file=f"{user_dir}/log/eden_log.txt", save_dir=save_dir,
        sd_hooks_dir=f"{sdmc}/smm2-hooks",
        mods_dir=f"{load}/{TITLE_ID}/smm2-hooks/exefs",
        alt_mods_dir=f"{exe_dir}/load/{TITLE_ID}/smm2-hooks/exefs",
    )


# ── config ────────────────────────────────────────────────────────────────

def gdb_config(p: EdenPaths) -> dict:
    vals = _read_ini(p.config_ini)
    return {
        "use_gdbstub": vals.get("use_gdbstub", "?") == "true",
        "port": int(vals.get("gdbstub_port", "6543") or 6543),
        "ini": p.config_ini,
    }


def set_gdbstub(p: EdenPaths, enabled: bool) -> bool:
    """Flip use_gdbstub in the real ini, preserving CRLF. Returns True if changed.

    Eden's ini is yuzu-style: `key\\default=true` means "at the default", and the
    value line is ignored while it is set. Enabling the stub must clear that
    flag as well, or Eden boots with the stub off and rewrites the value back.
    """
    b = Path(p.config_ini).read_bytes()
    value = b"true" if enabled else b"false"
    new = re.sub(rb"use_gdbstub=(true|false)", b"use_gdbstub=" + value, b, count=1)
    flag = b"false" if enabled else b"true"
    new = re.sub(rb"use_gdbstub\\default=(true|false)", lambda _: b"use_gdbstub\\default=" + flag, new, count=1)
    if new != b:
        Path(p.config_ini).write_bytes(new)
        return True
    return False


# ── process ───────────────────────────────────────────────────────────────

def process() -> dict | None:
    ps = "/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe"
    cmd = ("Get-Process eden -ErrorAction SilentlyContinue | Select-Object Id,WorkingSet64,"
           "@{n='Start';e={$_.StartTime.ToString('yyyy-MM-ddTHH:mm:ss')}} | ConvertTo-Json -Compress")
    try:
        out = subprocess.run([ps, "-NoProfile", "-Command", cmd], capture_output=True, text=True, timeout=20).stdout.strip()
    except Exception:
        return None
    if not out:
        return None
    import json
    data = json.loads(out)
    if isinstance(data, list):
        data = max(data, key=lambda d: d.get("WorkingSet64", 0))
    return {"pid": data.get("Id"), "mem_mb": int(data.get("WorkingSet64", 0) // (1024 * 1024)),
            "started": data.get("Start")}


def stub_listening(port: int) -> bool | None:
    """Is anything listening on the GDB port on the Windows side? (Never connects to it.)"""
    ps = "/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe"
    cmd = f"(Get-NetTCPConnection -LocalPort {port} -State Listen -ErrorAction SilentlyContinue | Measure-Object).Count"
    try:
        out = subprocess.run([ps, "-NoProfile", "-Command", cmd], capture_output=True, text=True, timeout=20).stdout.strip()
        return int(out or 0) > 0
    except Exception:
        return None


def launch(p: EdenPaths, gdb: bool) -> dict:
    changed = set_gdbstub(p, gdb)
    status = Path(p.sd_hooks_dir) / "status.bin"
    if status.exists():
        status.unlink()
    game_win = p.game if re.match(r"^[A-Za-z]:", p.game) else wsl_to_win(p.game)
    subprocess.Popen([p.exe, "-g", game_win], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    deadline = time.time() + 25
    proc = None
    while time.time() < deadline:
        proc = process()
        if proc and proc["mem_mb"] > 50:
            break
        time.sleep(1)
    return {"process": proc, "gdbstub_config_changed": changed, "gdb": gdb,
            "note": "paused until a debugger attaches and continues" if gdb else "booting to the title screen (~25 s)"}


def kill() -> dict:
    ps = "/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe"
    subprocess.run([ps, "-NoProfile", "-Command", "Stop-Process -Name eden -Force -ErrorAction SilentlyContinue"], capture_output=True, timeout=20)
    time.sleep(1)
    return {"process": process()}


# ── status.bin ────────────────────────────────────────────────────────────

def read_status(p: EdenPaths) -> dict | None:
    f = Path(p.sd_hooks_dir) / "status.bin"
    if not f.exists():
        return None
    age = time.time() - f.stat().st_mtime
    d = f.read_bytes()
    if len(d) < 0x4C:
        return None
    u32 = lambda o: struct.unpack_from("<I", d, o)[0]
    f32 = lambda o: struct.unpack_from("<f", d, o)[0]
    scene = u32(0x44)
    return {
        "age_s": round(age, 1),
        "fresh": age <= STATUS_MAX_AGE,
        "frame": u32(0x00),
        "game_phase": u32(0x04),
        "real_phase": struct.unpack_from("<i", d, 0x38)[0],
        "scene_mode": scene,
        "scene": SCENE_NAMES.get(scene, f"unknown({scene})"),
        "edit_time": scene in EDIT_TIME,
        "run_time": scene in RUN_TIME,
        "is_playing": u32(0x48),
        "has_player": d[0x27],
        "player": {
            "state": u32(0x08), "state_frames": u32(0x20), "powerup": u32(0x0C),
            "x": round(f32(0x10), 2), "y": round(f32(0x14), 2), "vx": round(f32(0x18), 3), "vy": round(f32(0x1C), 3),
            "facing": f32(0x28), "gravity": f32(0x2C), "in_water": d[0x24], "is_dead": d[0x25], "is_goal": d[0x26],
        } if d[0x27] else None,
        "theme": d[0x3C], "style": u32(0x40),
        "scene_change_count": u32(0x8C) if len(d) >= 0x90 else None,
    }


# ── mods and log ──────────────────────────────────────────────────────────

def mods(p: EdenPaths) -> dict:
    def info(d: str) -> dict | None:
        f = Path(d) / "subsdk4"
        if not f.exists():
            return None
        return {"path": str(f), "size": f.stat().st_size, "mtime": time.strftime("%Y-%m-%d %H:%M", time.localtime(f.stat().st_mtime))}
    return {
        "active_load_dir": p.load_dir,
        "deployed": info(p.mods_dir),
        "other_copy_next_to_exe": info(p.alt_mods_dir) if p.alt_mods_dir != p.mods_dir else None,
    }


def log_tail(p: EdenPaths, n: int = 12, grep: str | None = None) -> dict:
    f = Path(p.log_file)
    if not f.exists():
        return {"file": p.log_file, "exists": False}
    lines = f.read_text(errors="replace").splitlines()
    if grep:
        lines = [l for l in lines if re.search(grep, l, re.I)]
    return {"file": p.log_file, "mtime": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(f.stat().st_mtime)),
            "lines": [l[:200] for l in lines[-n:]]}


# ── the one call ──────────────────────────────────────────────────────────

def state(p: EdenPaths | None = None) -> dict:
    p = p or paths()
    proc = process()
    cfg = gdb_config(p)
    st = read_status(p)
    listening = stub_listening(cfg["port"]) if proc else False
    if not proc:
        mode = "off"
    elif st and st["fresh"]:
        mode = st["scene"]
    elif cfg["use_gdbstub"] and listening:
        mode = "waiting_for_debugger_or_paused"
    else:
        mode = "launching_or_frozen"
    return {
        "mode": mode,
        "edit_time": bool(st and st["fresh"] and st["edit_time"]),
        "run_time": bool(st and st["fresh"] and st["run_time"]),
        "process": proc,
        "gdb": {**cfg, "stub_listening": listening, "host_ip": windows_host_ip()},
        "status": st,
        "paths": asdict(p),
        "mods": mods(p),
        "log": log_tail(p, 5),
    }


def brief(p: EdenPaths | None = None) -> tuple[str, bool]:
    """One line for an external monitor, and whether Eden is up.

    'pid 1234 · 1.8 GB · since 16:20:01 · title · frame 1805'. Reads the process
    and status.bin only (no GDB port probe), so it is cheap enough to poll.
    """
    p = p or paths()
    proc = process()
    if not proc:
        return "off", False
    mem = f"{proc['mem_mb'] / 1024:.1f} GB" if proc["mem_mb"] >= 1024 else f"{proc['mem_mb']} MB"
    parts = [f"pid {proc['pid']}", mem]
    if proc.get("started"):
        parts.append(f"since {proc['started'][11:19]}")
    st = read_status(p)
    if st and st["fresh"]:
        parts += [st["scene"], f"frame {st['frame']}"]
    elif st:
        parts.append(f"status stale {st['age_s']:.0f}s (last {st['scene']})")
    else:
        parts.append("no status.bin")
    return " · ".join(parts), True


if __name__ == "__main__":
    import json
    if "--brief" in sys.argv[1:]:
        line, up = brief()
        print(line)
        sys.exit(0 if up else 1)
    if "--kill" in sys.argv[1:]:
        r = kill()
        print(json.dumps(r))
        sys.exit(0 if r["process"] is None else 1)
    if "--launch" in sys.argv[1:]:
        if process():
            print("Eden already running")
            sys.exit(1)
        r = launch(paths(), gdb=False)
        print(json.dumps(r))
        sys.exit(0 if r["process"] else 1)
    print(json.dumps(state(), indent=1))
