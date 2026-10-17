"""
Truthful Eden state for SMM2 debugging, read from where Eden actually keeps it.

Eden (yuzu family) runs "portable" when a `user/` directory sits next to
eden.exe; its qt-config.ini then names the NAND, SD and mod (`load`)
directories explicitly, which may still live under AppData. Everything here
derives from that ini, never from guesses in .env (only EDEN_EXE,
EDEN_GAME_PATH and EDEN_USER_DIR come from there).

Two hosts are supported, told apart by EDEN_EXE:
- **Windows Eden driven from WSL** (EDEN_EXE ends in `.exe`, the default):
  paths convert with win_to_wsl, the process is found and stopped through
  PowerShell, the GDB stub is on the Windows host's IP.
- **Native Linux Eden** (any other EDEN_EXE, e.g. an extracted AppImage or a
  launcher script): paths are used as they are, the process is found in /proc
  and stopped with signals, the stub is on 127.0.0.1. On Linux, Eden's
  portable directory is `./user` in its *working directory* (not next to the
  binary), so name it with EDEN_USER_DIR and start Eden from its parent (a
  launcher script can do the cd); without it Eden uses
  $XDG_DATA_HOME/eden and $XDG_CONFIG_HOME/eden.
"""
from __future__ import annotations

import os
import re
import signal
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


def native(exe: str | None = None) -> bool:
    """Is Eden a native (Linux) program here, rather than eden.exe driven from WSL?"""
    if exe is None:
        exe = os.environ.get("EDEN_EXE") or _dotenv().get("EDEN_EXE", DEFAULT_EXE)
    return not exe.lower().endswith(".exe")


def process_name() -> str:
    """The program name to look for: EDEN_PROCESS_NAME, else `eden`."""
    return os.environ.get("EDEN_PROCESS_NAME") or _dotenv().get("EDEN_PROCESS_NAME", "eden")


DEFAULT_EXE = "/mnt/c/Users/nico/Documents/eden/eden.exe"


def win_to_wsl(p: str) -> str:
    p = p.replace("\\", "/")
    m = re.match(r"^([A-Za-z]):/(.*)$", p)
    return f"/mnt/{m.group(1).lower()}/{m.group(2)}" if m else p


def wsl_to_win(p: str) -> str:
    m = re.match(r"^/mnt/([a-z])/(.*)$", p)
    return f"{m.group(1).upper()}:/{m.group(2)}" if m else p


def windows_host_ip() -> str:
    try:
        out = subprocess.run(["ip", "route"], capture_output=True, text=True).stdout
    except FileNotFoundError:   # no iproute2 (a bare container)
        return "127.0.0.1"
    for line in out.splitlines():
        if line.startswith("default"):
            return line.split()[2]
    return "127.0.0.1"


def gdb_host() -> str:
    """Where Eden's GDB stub listens: this machine for a native Eden, the Windows host from WSL."""
    return "127.0.0.1" if native() else windows_host_ip()


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


def _xdg(var: str, fallback: str) -> str:
    return os.environ.get(var) or str(Path.home() / fallback)


def paths() -> EdenPaths:
    env = _dotenv()
    # The process environment wins over .env: a worktree has no .env.
    exe = os.environ.get("EDEN_EXE") or env.get("EDEN_EXE", DEFAULT_EXE)
    game = os.environ.get("EDEN_GAME_PATH") or env.get("EDEN_GAME_PATH", "")
    user_env = os.environ.get("EDEN_USER_DIR") or env.get("EDEN_USER_DIR", "")
    exe_dir = str(Path(exe).parent)
    if native(exe):
        # Linux Eden keeps everything under one dir only in portable mode
        # (./user in its working directory); otherwise config is apart from data.
        to_local = to_ini = lambda q: q  # noqa: E731
        if user_env:
            user_dir, portable = user_env, True
            ini = f"{user_dir}/config/qt-config.ini"
        else:
            user_dir, portable = f"{_xdg('XDG_DATA_HOME', '.local/share')}/eden", False
            ini = f"{_xdg('XDG_CONFIG_HOME', '.config')}/eden/qt-config.ini"
    else:
        to_local, to_ini = win_to_wsl, wsl_to_win
        portable_user = win_to_wsl(user_env) if user_env else f"{exe_dir}/user"
        portable = os.path.isdir(portable_user)
        user_dir = portable_user if portable else win_to_wsl(os.environ.get("EDEN_APPDATA", "C:/Users/nico/AppData/Roaming/eden"))
        ini = f"{user_dir}/config/qt-config.ini"
    vals = _read_ini(ini)
    nand = to_local(vals.get("nand_directory", f"{to_ini(user_dir)}/nand"))
    sdmc = to_local(vals.get("sdmc_directory", f"{to_ini(user_dir)}/sdmc"))
    load = to_local(vals.get("load_directory", f"{to_ini(user_dir)}/load"))
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
        # Windows Eden also looks next to eden.exe; a native one has no such copy.
        alt_mods_dir=f"{load}/{TITLE_ID}/smm2-hooks/exefs" if native(exe) else f"{exe_dir}/load/{TITLE_ID}/smm2-hooks/exefs",
    )


# ── config ────────────────────────────────────────────────────────────────

def gdb_config(p: EdenPaths) -> dict:
    vals = _read_ini(p.config_ini)
    # Qt keeps `key\default=true` beside a value that is still at its default;
    # Eden then reads the default (false), whatever the value says.
    value_on = vals.get("use_gdbstub", "?") == "true"
    at_default = vals.get("use_gdbstub\\default", "false") == "true"
    return {
        "use_gdbstub": value_on and not at_default,
        "use_gdbstub_value": value_on,
        "use_gdbstub_default_marker": at_default,
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


def ensure_docked(p: EdenPaths) -> bool:
    """Force docked mode in the real ini. Returns True if changed.

    The input mod hooks only GetNpadStates(NpadFullKeyState*) — the Pro
    Controller path Eden uses when docked. In handheld mode the game polls the
    handheld Npad, that hook never fires, and injected input from input.bin is
    silently ignored in every scene (the game sits on the title screen no
    matter what we press). Guarantee docked before every launch.
    """
    b = Path(p.config_ini).read_bytes()
    new = re.sub(rb"use_docked_mode=\d", b"use_docked_mode=1", b, count=1)
    new = re.sub(rb"use_docked_mode\\default=(true|false)",
                 b"use_docked_mode\\\\default=true", new, count=1)
    if new != b:
        Path(p.config_ini).write_bytes(new)
        return True
    return False


# ── process ───────────────────────────────────────────────────────────────

def _proc_cmdline(pid: str) -> list[str]:
    try:
        raw = Path(f"/proc/{pid}/cmdline").read_bytes()
    except OSError:
        return []
    return [a.decode("utf-8", "replace") for a in raw.split(b"\0") if a]


def _is_eden(argv: list[str], name: str) -> bool:
    """argv of an Eden process: the program itself, or a dynamic loader running it.

    An extracted AppImage built with sharun runs Eden as
    `<appdir>/shared/lib/ld-linux-x86-64.so.2 --library-path ... <appdir>/shared/bin/eden`,
    so the process's own name is the loader's; look for the binary among its
    arguments then. Scripts that merely mention eden (eden.py, this server)
    have other basenames and never match.
    """
    if not argv:
        return False
    first = os.path.basename(argv[0])
    if first == name:
        return True
    return first.startswith("ld-") and any(os.path.basename(a) == name for a in argv[1:])


def native_pids(name: str | None = None) -> list[int]:
    """PIDs of native Eden processes (read from /proc; no pgrep needed)."""
    name = name or process_name()
    me = os.getpid()
    out = []
    for d in Path("/proc").iterdir():
        if d.name.isdigit() and int(d.name) != me and _is_eden(_proc_cmdline(d.name), name):
            out.append(int(d.name))
    return sorted(out)


def _native_process() -> dict | None:
    best = None
    try:
        boot = next(float(l.split()[1]) for l in Path("/proc/stat").read_text().splitlines() if l.startswith("btime "))
        hz = os.sysconf("SC_CLK_TCK")
    except (OSError, StopIteration, ValueError):
        boot, hz = None, 100
    for pid in native_pids():
        try:
            rss_kb = next(int(l.split()[1]) for l in Path(f"/proc/{pid}/status").read_text().splitlines() if l.startswith("VmRSS:"))
        except (OSError, StopIteration):
            rss_kb = 0
        started = None
        if boot is not None:
            try:
                stat = Path(f"/proc/{pid}/stat").read_text()
                ticks = int(stat.rsplit(")", 1)[1].split()[19])   # field 22, starttime
                started = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(boot + ticks / hz))
            except (OSError, IndexError, ValueError):
                pass
        cand = {"pid": pid, "mem_mb": rss_kb // 1024, "started": started}
        if best is None or cand["mem_mb"] > best["mem_mb"]:
            best = cand
    return best


def _native_listening(port: int) -> bool | None:
    """Is a TCP socket on this machine listening on `port`? (/proc/net/tcp*, state 0A.)"""
    seen = False
    for table in ("/proc/net/tcp", "/proc/net/tcp6"):
        try:
            lines = Path(table).read_text().splitlines()[1:]
        except OSError:
            continue
        seen = True
        for line in lines:
            parts = line.split()
            if len(parts) > 3 and parts[3] == "0A" and int(parts[1].rsplit(":", 1)[1], 16) == port:
                return True
    return False if seen else None


def process() -> dict | None:
    if native():
        return _native_process()
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
    """Is anything listening on the GDB port on Eden's side? (Never connects to it.)"""
    if native():
        return _native_listening(port)
    ps = "/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe"
    cmd = f"(Get-NetTCPConnection -LocalPort {port} -State Listen -ErrorAction SilentlyContinue | Measure-Object).Count"
    try:
        out = subprocess.run([ps, "-NoProfile", "-Command", cmd], capture_output=True, text=True, timeout=20).stdout.strip()
        return int(out or 0) > 0
    except Exception:
        return None


def launch(p: EdenPaths, gdb: bool) -> dict:
    if not p.game:
        # Eden given `-g ""` opens its game list, which looks like a hung boot.
        return {"error": "EDEN_GAME_PATH is not set (in .env or the environment); Eden would open its game list"}
    docked = ensure_docked(p)
    changed = set_gdbstub(p, gdb)
    status = Path(p.sd_hooks_dir) / "status.bin"
    if status.exists():
        status.unlink()
    if native(p.exe):
        # Own session: Eden outlives the tool that started it, as on Windows.
        subprocess.Popen([p.exe, "-g", p.game], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True)
    else:
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
            "docked_mode_forced": docked,
            "note": "paused until a debugger attaches and continues" if gdb else "booting to the title screen (~25 s)"}


def _native_kill(grace: float = 3.0) -> None:
    """SIGTERM every Eden process, then SIGKILL what is left after `grace` seconds
    (the Windows path is Stop-Process -Force, which does not wait either)."""
    for sig in (signal.SIGTERM, signal.SIGKILL):
        pids = native_pids()
        for pid in pids:
            try:
                os.kill(pid, sig)
            except ProcessLookupError:
                pass
        deadline = time.time() + grace
        while pids and time.time() < deadline:
            time.sleep(0.2)
            pids = native_pids()
        if not pids:
            return


def kill() -> dict:
    if native():
        _native_kill()
        return {"process": process()}
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


# ── patches (pchtxt) ──────────────────────────────────────────────────────
# Versioned in <repo>/patches/*.pchtxt. Eden applies every *.pchtxt inside a
# mod's exefs/ folder, so "enabled" means: a copy sits next to subsdk4.

PATCHES_DIR = Path(__file__).resolve().parent.parent / "patches"


def patches(p: EdenPaths) -> list[dict]:
    """Every versioned patch with its deployed state, plus unversioned ones found in the mod dir."""
    deployed = Path(p.mods_dir)
    out = []
    for f in sorted(PATCHES_DIR.glob("*.pchtxt")):
        d = deployed / f.name
        same = d.exists() and d.read_bytes() == f.read_bytes()
        out.append({"name": f.stem, "enabled": d.exists(), "stale": d.exists() and not same, "source": str(f)})
    for d in sorted(deployed.glob("*.pchtxt")):
        if not (PATCHES_DIR / d.name).exists():
            out.append({"name": d.stem, "enabled": True, "unversioned": True, "source": str(d)})
    return out


def set_patch(p: EdenPaths, name: str, enabled: bool) -> dict:
    """Copy a versioned patch into (or remove it from) the deployed mod's exefs/. Takes effect on the next launch."""
    src = PATCHES_DIR / f"{name}.pchtxt"
    if not src.exists():
        return {"error": f"no patches/{name}.pchtxt; known: {[f.stem for f in sorted(PATCHES_DIR.glob('*.pchtxt'))]}"}
    dst = Path(p.mods_dir) / src.name
    if enabled:
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(src.read_bytes())
    elif dst.exists():
        dst.unlink()
    return {"name": name, "enabled": enabled, "path": str(dst), "note": "takes effect on the next launch"}


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
        "patches": patches(p),
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


def hooks_ran_this_process(p: EdenPaths, proc: dict | None) -> bool:
    """Has the mod written status.bin since this Eden process started?

    Eden is a general Switch emulator: with no game booted it sits in its own
    game-selection UI, where no game code and so no hook runs. That looks the
    same from outside as a game that launched and hung, and the two want
    opposite responses (boot a game vs. kill Eden), so separate them by
    whether status.bin has been touched during this process's lifetime.
    """
    started = (proc or {}).get("started")
    if not started:
        return False
    f = Path(p.sd_hooks_dir) / "status.bin"
    if not f.exists():
        return False
    try:
        t0 = time.mktime(time.strptime(started, "%Y-%m-%dT%H:%M:%S"))
    except ValueError:
        return False
    return f.stat().st_mtime >= t0


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
    elif not hooks_ran_this_process(p, proc):
        mode = "eden_ui_no_game"
    else:
        mode = "launching_or_frozen"
    return {
        "mode": mode,
        "edit_time": bool(st and st["fresh"] and st["edit_time"]),
        "run_time": bool(st and st["fresh"] and st["run_time"]),
        "process": proc,
        "gdb": {**cfg, "stub_listening": listening, "host_ip": gdb_host()},
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
    argv = sys.argv[1:]
    if "--patches" in argv:
        for it in patches(paths()):
            flag = "on " if it["enabled"] else "off"
            extra = " (stale copy)" if it.get("stale") else (" (unversioned)" if it.get("unversioned") else "")
            print(f"{flag} {it['name']}{extra}")
        sys.exit(0)
    for flag, on in (("--enable", True), ("--disable", False)):
        if flag in argv:
            i = argv.index(flag) + 1
            if i >= len(argv) or argv[i].startswith("--"):
                print(f"usage: eden.py {flag} <patch>   (names: eden.py --patches)", file=sys.stderr)
                sys.exit(2)
            print(json.dumps(set_patch(paths(), argv[i], on)))
            sys.exit(0)
    if "--launch" in sys.argv[1:]:
        if process():
            print("Eden already running")
            sys.exit(1)
        r = launch(paths(), gdb=False)
        print(json.dumps(r))
        sys.exit(0 if r["process"] else 1)
    print(json.dumps(state(), indent=1))
