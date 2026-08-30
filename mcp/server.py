"""
smm2-hooks MCP server: drive Eden + the SMM2 hook mod from an agent without guessing.

Tools read the emulator's real configuration (mcp/eden.py), report one
truthful `mode`, install generated levels, navigate the game through the hook
mod's input file, take screenshots, and hold a single GDB session.
"""
from __future__ import annotations

import base64
import functools
import json
import os
import subprocess
import sys
import threading
import uuid
from pathlib import Path

import anyio

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
TOOLS = REPO / "tools"
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(TOOLS))

import eden  # noqa: E402
from gdbsession import GdbSession  # noqa: E402
from mcp.server.fastmcp import FastMCP, Image  # noqa: E402

P = eden.paths()
os.environ["EDEN_SD_PATH"] = P.sd_hooks_dir          # smm2.Game reads this
os.environ.setdefault("EDEN_EXE", P.exe)

mcp = FastMCP("smm2-hooks", instructions=(
    "Super Mario Maker 2 in the Eden emulator, with the smm2-hooks mod. Call eden_state first; "
    "its `mode` is the truth (off, launching_or_frozen, waiting_for_debugger_or_paused, title, "
    "editor, editor_play, coursebot_play, loading). edit_time = the Course Maker editor; run_time = "
    "editor_play or coursebot_play, the only modes where actors update and a player exists. "
    "GDB: hardware breakpoints/watchpoints only; the target must be stopped to send commands."
))
GDB = GdbSession()

_GAME_LOCK = threading.Lock()  # tools that write input.bin, launch/kill Eden or talk to GDB run one at a time


def tool(exclusive: bool = False):
    """Register a tool that runs in a worker thread.

    A plain function called on the server's event loop blocks the whole server
    for its duration: no pings, no cancellation, no other tool, and the host
    gives up on the channel. Eden navigation takes tens of seconds, so tools
    run off the loop. exclusive=True serialises the ones that drive the game,
    and refuses them while a game_boot navigation thread is still running
    after its pending reply (the thread outlives the lock).
    """
    def wrap(fn):
        @functools.wraps(fn)
        async def run(*args, **kwargs):
            def call():
                if not exclusive:
                    return fn(*args, **kwargs)
                with _GAME_LOCK:
                    if _nav_running():
                        return {"error": f"{fn.__name__} refused: game_boot is still navigating; poll game_status", "boot": _NAV.get("result")}
                    return fn(*args, **kwargs)
            return await anyio.to_thread.run_sync(call)
        return mcp.tool()(run)
    return wrap


def _game():
    from smm2 import Game  # noqa: WPS433
    return Game("eden")


@tool()
def eden_state() -> dict:
    """Everything about the emulator right now: mode, process, real GDB config, status.bin, paths, mods, log tail."""
    s = eden.state(P)
    s["gdb"]["session"] = {"attached": GDB.alive(), "running": GDB.running, "base": hex(GDB.base) if GDB.base else None}
    return s


@tool(exclusive=True)
def eden_launch(gdb: bool = False) -> dict:
    """Start Eden with the game. gdb=True enables the stub in the real ini; the game then stays paused until gdb_attach + gdb_continue."""
    if eden.process():
        return {"error": "Eden already running; call eden_kill first", "process": eden.process()}
    return eden.launch(P, gdb)


@tool(exclusive=True)
def eden_kill() -> dict:
    """Stop Eden (and drop the GDB session if any)."""
    if GDB.alive():
        try:
            GDB.detach()
        except Exception:
            pass
    return eden.kill()


@tool(exclusive=True)
def eden_patches(enable: str | None = None, disable: str | None = None) -> dict:
    """List the versioned pchtxt patches (repo patches/) and their deployed state; enable/disable one by name (next launch)."""
    result: dict = {}
    if enable:
        result["enable"] = eden.set_patch(P, enable, True)
    if disable:
        result["disable"] = eden.set_patch(P, disable, False)
    result["patches"] = eden.patches(P)
    return result


@tool(exclusive=True)
def eden_set_gdbstub(enabled: bool) -> dict:
    """Flip use_gdbstub in the real qt-config.ini (takes effect on the next launch)."""
    return {"changed": eden.set_gdbstub(P, enabled), **eden.gdb_config(P)}


@tool()
def eden_log(lines: int = 20, grep: str | None = None) -> dict:
    """Tail of Eden's current log file, optionally filtered by a regex."""
    return eden.log_tail(P, lines, grep)


@tool()
def eden_screenshot() -> Image:
    """Screenshot of the Eden window (PowerShell PrintWindow)."""
    path = Path(f"/mnt/c/temp/smm2_debug/capture-{uuid.uuid4().hex}.png")  # one file per call: concurrent calls never see each other's picture
    try:
        r = subprocess.run([sys.executable, str(TOOLS / "automate.py"), "--eden", "screenshot"], capture_output=True, text=True, timeout=30,
                           cwd=str(TOOLS), env={**os.environ, "SCREENSHOT_OUT": str(path)})
        if r.returncode != 0 or not path.exists():
            raise RuntimeError(f"screenshot failed: {r.stdout.strip()} {r.stderr.strip()}")
        return Image(data=path.read_bytes(), format="png")
    finally:
        path.unlink(missing_ok=True)


@tool()
def game_status() -> dict:
    """Decoded status.bin only (fast): frame, scene, edit_time/run_time, player. Carries 'boot' while/after a game_boot that returned pending."""
    out = eden.read_status(P) or {"status": None, "note": "no fresh status.bin (hooks not running or game not up)"}
    if _NAV.get("result"):
        out["boot"] = _NAV["result"]
    return out


@tool(exclusive=True)
def game_input(buttons: str, ms: int = 120) -> dict:
    """Press buttons through the hook mod, e.g. 'A', 'B', 'MINUS', 'L+R', 'RIGHT', 'B+MINUS'. Works in every scene."""
    g = _game()
    g.press(buttons, ms=ms)
    return {"pressed": buttons, "ms": ms, "status": eden.read_status(P)}


_NAV: dict = {}  # the navigation still running after game_boot returned pending, if any


def _nav_running() -> bool:
    t = _NAV.get("thread")
    return bool(t and t.is_alive())


@tool(exclusive=True)
def game_boot(target: str = "coursebot", slot: int | None = None, timeout: int = 45, budget: int = 100) -> dict:
    """Navigate from the title screen: target 'editor' (edit-time), 'editor_play' (test-play the editor course), or 'coursebot' with a slot. A slot the game lists starts Coursebot play (scene_mode 7); an empty slot only offers 'Make New Course', so it opens the editor with a default course and MINUS starts test-play (scene_mode 5) instead. Read scene_mode in the returned status. The call returns within `budget` seconds; if navigation is still going it returns pending=true and keeps going, game_status then carries the outcome under 'boot', and every tool that drives the game refuses until it is done. The final result reports 'registered' as save.dat stands after the visit (Coursebot may delete the slot on the way in)."""
    if target == "coursebot" and slot is None:
        return {"error": "slot required"}
    if target not in ("coursebot", "editor", "editor_play"):
        return {"error": f"unknown target {target}"}
    g = _game()

    def with_registration(result: dict) -> dict:
        registered = _registered_slots() if target == "coursebot" else None
        if registered is not None:
            result["registered"] = slot in registered
            if slot not in registered:
                result["note"] = "slot is not in save.dat, so this is editor test-play of a default course, not the installed level; level_install registers a slot (the course must pass validation)"
        return result

    def navigate():
        try:
            if target == "coursebot":
                ok = g.to_coursebot_play(slot=slot, timeout=timeout)
            elif target == "editor":
                ok = g.to_editor(timeout=timeout)
            else:
                ok = g.to_play(timeout=timeout)
            _NAV["result"] = with_registration({"ok": bool(ok), "pending": False, "status": eden.read_status(P)})
        except Exception as e:  # noqa: BLE001
            _NAV["result"] = {"ok": False, "pending": False, "error": repr(e)}

    t = threading.Thread(target=navigate, name="game_boot", daemon=True)
    _NAV.update(thread=t, result={"ok": False, "pending": True, "target": target, "slot": slot})
    t.start()
    t.join(budget)
    return dict(_NAV["result"])


def _registered_slots() -> set[int] | None:
    """Slots Coursebot lists: the used_flag per record in save.dat. The .bcd files on disk are not consulted by the game."""
    if not P.save_dir:
        return None
    path = Path(P.save_dir) / "save.dat"
    if not path.exists():
        return None
    import save_dat  # noqa: WPS433
    body = save_dat.decrypt(path.read_bytes())
    return {slot for slot, used in save_dat.records(body) if used}


@tool()
def levels_list() -> dict:
    """Generated test levels (by name) and the Coursebot save slots. `registered` is what the game lists (save.dat); a .bcd on disk without it only offers 'Make New Course', so game_boot lands in editor test-play, not Coursebot play."""
    sys.argv = ["x"]
    import gen_test_levels as g  # noqa: WPS433
    import parse_course as pc  # noqa: WPS433
    gen = {slot: name for slot, (name, _) in sorted(g.TEST_LEVELS.items())}
    if not P.save_dir:
        return {"generators": gen, "save_dir": None, "registered": None, "slots": None}
    registered = _registered_slots()
    slots = []
    for i in range(180):
        path = Path(P.save_dir) / f"course_data_{i:03d}.bcd"
        if not path.exists():
            break
        entry = {"slot": i, "registered": (i in registered) if registered is not None else None}
        dec = pc.decrypt_course(str(path))
        if dec is None:
            entry["error"] = "cannot decrypt"
        else:
            h = pc.parse_header(dec)
            area = pc.parse_area(dec[0x200:0x200 + 0x2DEE0])
            entry.update(name=h["name"], style=h["style_name"], theme=area["theme_name"], actors=area["actor_count"])
        slots.append(entry)
    return {"generators": gen, "save_dir": P.save_dir,
            "registered": sorted(registered) if registered is not None else None, "slots": slots}


SLOT_FILES = ("course_data_{:03d}.bcd", "course_thumb_{:03d}.btl", "course_replay_{:03d}.dat")


def _slot_error(slot) -> dict | None:
    import save_dat  # noqa: WPS433
    if not isinstance(slot, int) or isinstance(slot, bool) or not 0 <= slot < save_dat.RECORD_COUNT:
        return {"error": f"slot {slot!r} is not a Coursebot slot (0..{save_dat.RECORD_COUNT - 1})"}
    return None


def _backup_once(path: Path, data: bytes) -> None:
    """Keep the first pre-install copy of a file as <name>.orig. Written through a temp file and
    renamed, so an interrupted write cannot leave a truncated .orig that later installs trust."""
    bak = path.with_name(path.name + ".orig")
    if bak.exists():
        return
    tmp = bak.with_name(bak.name + ".tmp")
    try:
        tmp.write_bytes(data)
        os.replace(tmp, bak)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise


def _install_slot(slot: int, course: bytes, companions_from: int | None) -> dict:
    """Write a course into a slot and give it what Coursebot checks on its next visit: a valid
    course_thumb + course_replay beside the .bcd (borrowed from a registered slot; the contents
    need not match) and used_flag set in save.dat. Nothing is written until every input exists;
    each of the three files is backed up once as .orig; a failure mid-way puts the files back."""
    import save_dat  # noqa: WPS433
    sd = Path(P.save_dir)
    save = sd / "save.dat"
    save_raw = save.read_bytes()
    body = bytearray(save_dat.decrypt(save_raw))
    registered = {s for s, f in save_dat.records(body) if f}
    donor = companions_from if companions_from is not None else next((s for s in sorted(registered) if s != slot), None)
    if donor is None:
        return {"error": "no registered slot to borrow course_thumb/course_replay from; pass companions_from"}
    if (err := _slot_error(donor)):
        return err
    sources = [course] + [sd / pattern.format(donor) for pattern in SLOT_FILES[1:]]
    missing = [str(src) for src in sources[1:] if not src.exists()]
    if missing:
        return {"error": f"donor slot {donor} is missing {', '.join(missing)}"}
    targets = [sd / pattern.format(slot) for pattern in SLOT_FILES]
    previous = {t: t.read_bytes() if t.exists() else None for t in targets}
    touched = []  # every file a write was attempted on, including the one that may have failed half-way
    try:
        for t, src in zip(targets, sources):
            if previous[t] is not None:
                _backup_once(t, previous[t])
            touched.append(t)
            t.write_bytes(src if isinstance(src, bytes) else src.read_bytes())
        body[save_dat.RECORDS + 8 * slot + 1] = 1
        _backup_once(save, save_raw)
        touched.append(save)
        save.write_bytes(save_dat.encrypt(bytes(body)))
    except Exception as e:  # noqa: BLE001
        previous[save] = save_raw
        unrestored = []
        for t in touched:
            try:
                if previous[t] is None:
                    t.unlink(missing_ok=True)
                else:
                    t.write_bytes(previous[t])
            except Exception:  # noqa: BLE001
                unrestored.append(str(t))
        if unrestored:
            return {"error": f"install failed: {e!r}; rollback could not restore {', '.join(unrestored)} (.orig backups are beside them; level_restore)"}
        return {"error": f"install failed and was rolled back: {e!r}"}
    return {"slot": slot, "files": [str(t) for t in targets], "companions_from": donor,
            "backups": [str(t.with_name(t.name + ".orig")) for t in targets if previous[t] is not None],
            "registered": sorted(registered | {slot})}


@tool(exclusive=True)
def level_install(slot: int, level: str, companions_from: int | None = None) -> dict:
    """Write a generated level (name from levels_list) into Coursebot slot N and register it: copies a valid course_thumb + course_replay from another registered slot (or companions_from) and sets the slot's used flag in save.dat. Each replaced file is backed up once as .orig (level_restore puts all three back). Restart the game to see it; Coursebot deletes the slot on its next visit if the course itself is invalid."""
    if (err := _slot_error(slot)):
        return err
    sys.argv = ["x"]
    import gen_test_levels as g  # noqa: WPS433
    match = [(s, n, f) for s, (n, f) in g.TEST_LEVELS.items() if n == level]
    if not match:
        return {"error": f"unknown level {level!r}", "available": [n for _, (n, _) in g.TEST_LEVELS.items()]}
    _, name, builder = match[0]
    if not P.save_dir:
        return {"error": "no save dir found"}
    out = _install_slot(slot, g.encrypt_course(builder().build()), companions_from)
    return {"level": name, **out}


@tool(exclusive=True)
def level_restore(slot: int) -> dict:
    """Put back the .orig backups of a Coursebot slot's course, thumbnail and replay (whichever exist). The slot's used flag in save.dat is left as it is."""
    if (err := _slot_error(slot)):
        return err
    restored = []
    for pattern in SLOT_FILES:
        dst = Path(P.save_dir) / pattern.format(slot)
        bak = dst.with_name(dst.name + ".orig")
        if bak.exists():
            dst.write_bytes(bak.read_bytes())
            restored.append(str(dst))
    if not restored:
        return {"error": "no backups for this slot"}
    return {"restored": restored}


@tool(exclusive=True)
def gdb_attach() -> dict:
    """Attach gdb-multiarch to Eden's stub (real ini port, Windows host IP). Leaves the target stopped; call gdb_continue."""
    cfg = eden.gdb_config(P)
    out = GDB.attach(eden.windows_host_ip(), cfg["port"])
    return {"attached": GDB.alive(), "output": out, "port": cfg["port"]}


@tool(exclusive=True)
def gdb_continue() -> dict:
    """Resume the game. Use gdb_wait_stop to wait for a hit, gdb_interrupt to stop it."""
    return {"result": GDB.continue_()}


@tool(exclusive=True)
def gdb_interrupt() -> dict:
    """Stop the running game (Ctrl-C) so commands can be sent. Do not do this during a scene load."""
    return {"output": GDB.interrupt()}


@tool(exclusive=True)
def gdb_wait_stop(timeout: int = 30) -> dict:
    """Wait for a breakpoint/watchpoint hit; returns GDB's stop report."""
    return {"output": GDB.wait_stop(timeout)}


@tool(exclusive=True)
def gdb_cmd(command: str, timeout: int = 15) -> dict:
    """Run one GDB command on the stopped target (hbreak/watch/x/p/bt/info/delete/find/mon ...). 'break' is refused."""
    return {"output": GDB.cmd(command, timeout)}


@tool(exclusive=True)
def gdb_module_base() -> dict:
    """Find the main module's runtime base (mon get info, else signature). Needed for gdb_addr."""
    if GDB.running:
        return {"error": "target running; gdb_interrupt first"}
    return GDB.module_base()


@tool(exclusive=True)
def gdb_addr(csv_address: str | None = None, runtime_address: str | None = None) -> dict:
    """Translate between functions.csv addresses (0x71...) and runtime addresses using the known base."""
    if csv_address:
        return {"runtime": hex(GDB.to_runtime(int(csv_address, 16)))}
    if runtime_address:
        return {"csv": hex(GDB.to_csv(int(runtime_address, 16)))}
    return {"error": "give csv_address or runtime_address"}


@tool(exclusive=True)
def gdb_detach() -> dict:
    """Delete all breakpoints, detach and quit GDB. The game keeps running."""
    return {"result": GDB.detach()}


@tool()
def gdb_log(last: int = 10) -> dict:
    """The last GDB command/response pairs of this session."""
    return {"entries": GDB.log[-last:]}


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        print(json.dumps(anyio.run(eden_state), indent=1)[:1500])
    else:
        mcp.run()
