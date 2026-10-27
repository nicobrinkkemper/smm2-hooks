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
import time
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


def _save_dir() -> str | None:
    """The save directory, looked up again while it is missing: the game
    creates it on its first boot, which may come after this server started
    (a fresh Eden user dir)."""
    global P
    if not P.save_dir:
        P = eden.paths()
    return P.save_dir
os.environ["EDEN_SD_PATH"] = P.sd_hooks_dir          # smm2.Game reads this
os.environ.setdefault("EDEN_EXE", P.exe)

mcp = FastMCP("smm2-hooks", instructions=(
    "Super Mario Maker 2 in the Eden emulator, with the smm2-hooks mod. Call eden_state first; "
    "its `mode` is the truth (off, eden_ui_no_game, launching_or_frozen, "
    "waiting_for_debugger_or_paused, title, "
    "editor, editor_play, coursebot_play, loading). edit_time = the Course Maker editor; run_time = "
    "editor_play or coursebot_play, the only modes where actors update and a player exists. "
    "To look at a course, open it in the editor with game_boot(target='editor', file=...): no Coursebot "
    "visit, so nothing is deleted as invalid (it opens as slot 0: leave without saving); tools/hf_course.py fetches real uploaded courses. "
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
    """Screenshot of the Eden window (PowerShell PrintWindow from WSL; X11 on a native Eden)."""
    if eden.native():
        import x11shot  # noqa: WPS433
        return Image(data=x11shot.grab_window_png(eden.native_pids()), format="png")
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


def _ui_screen() -> Path:
    return Path(P.sd_hooks_dir) / "ui-screen.txt"


@tool()
def ui_screen(full: bool = False) -> dict:
    """What the menus show now, read from the game (needs sd:/smm2-hooks/ui-probe.txt = 'capture' at boot).

    ready: a menu screen takes input (its state machine is in a Disp* state) and none is appearing,
    closing, leaving or loading; screens and transitions name them with their states. texts: the
    active layer in draw order (panes off-screen or under a modal are left out); focused: the control
    the game focused, and input whether that button takes input yet; course_slot: the Coursebot slot
    of the focused tile.
    full=True adds every visible row with its pane path, position and layer."""
    import ui_probe  # noqa: WPS433
    if not full:
        return ui_probe.observe(_ui_screen())
    result = ui_probe.read(_ui_screen())
    if not result.get("sample"):
        return result
    view = ui_probe.screen(result["sample"])
    return {**ui_probe.summary(view), "status": result["status"], "rows": view["rows"]}


@tool(exclusive=True)
def edit_records(type: int | None = None, timeout: float = 5.0) -> dict:
    """The course's records as the editor holds them now (scene mode 1, the editor, also during
    its test play), without saving: per area (0 main, 1 sub) each record's type, x, y (the .bcd's
    tenths / 10), w, h (tiles), flags, cflags (a contained object's flags), ext, ctype (the
    contained object's type, -1 none), lid (link id) and sid. type= keeps one record type. The
    mod walks the editor's record list (src/course_data.cpp, poll_records) when
    sd:/smm2-hooks/edit_records.req appears, and removes the request once the file is whole."""
    import struct  # noqa: WPS433
    sd = Path(P.sd_hooks_dir)
    req, out = sd / "edit_records.req", sd / "edit_records.bin"
    out.unlink(missing_ok=True)
    req.touch()
    deadline = time.time() + timeout
    while req.exists():
        if time.time() > deadline:
            req.unlink(missing_ok=True)
            return {"error": f"the mod did not answer within {timeout} s (is the game running with this mod?)"}
        time.sleep(0.05)
    if not out.exists():
        return {"error": "the mod could not write edit_records.bin"}
    data = out.read_bytes()
    (status,) = struct.unpack_from("<I", data, 0)
    if status:
        return {"error": {1: "not in the editor (scene mode 1)", 2: "no course loaded"}.get(status, f"status {status}")}
    areas, at = [], 4
    for _ in range(2):
        listed, written = struct.unpack_from("<II", data, at)
        at += 8
        if len(data) < at + written * 0x28:
            return {"error": f"edit_records.bin is {len(data)} bytes, short of {written} records"}
        records = []
        for _ in range(written):
            x, y, _unk, w, h, flags, cflags, ext, t, ct, lid, sid = struct.unpack_from("<fffffIIIhhhh", data, at)
            at += 0x28
            if type is None or t == type:
                records.append({"type": t, "x": x, "y": y, "w": w, "h": h, "flags": f"0x{flags:08x}",
                                "cflags": f"0x{cflags:08x}", "ext": f"0x{ext:x}", "ctype": ct, "lid": lid, "sid": sid})
        area = {"count": listed, "records": records}
        if written < listed:
            area["truncated"] = written
        areas.append(area)
    return {"areas": areas}


@tool(exclusive=True)
def game_input(buttons: str = "", ms: int = 120, stick: str = "") -> dict:
    """Press buttons through the hook mod, e.g. 'A', 'B', 'MINUS', 'L+R', 'RIGHT', 'B+MINUS', and/or hold the left stick at stick='lx,ly' (each -32767..32767; '32767,0' is full right; in the editor, X first gives the finger cursor that the stick scrolls). Works in every scene. 'ui' is ui_screen from the first snapshot taken after the press was released."""
    import ui_probe  # noqa: WPS433
    try:
        lx, ly = (int(v) for v in stick.split(",")) if stick else (0, 0)
    except ValueError:
        return {"error": f"stick {stick!r}: want 'lx,ly', e.g. '32767,0'"}
    if not (-32767 <= lx <= 32767 and -32767 <= ly <= 32767):
        return {"error": f"stick {stick!r}: each axis is -32767..32767"}
    before = ui_probe.observe(_ui_screen())
    g = _game()
    g.press(buttons or 0, ms=ms, lx=lx, ly=ly)
    ui = None
    if before.get("tick") is not None:
        released = before["tick"] + ms * 60 // 1000
        deadline = time.time() + 2.0  # only if the game stops writing snapshots
        while time.time() < deadline:
            ui = ui_probe.observe(_ui_screen())
            if (ui.get("tick") or 0) > released:
                break
            time.sleep(0.05)
    return {"pressed": buttons, "stick": stick or None, "ms": ms, "status": eden.read_status(P), "ui": ui}


@tool(exclusive=True)
def game_sequence(steps: list[dict]) -> dict:
    """Run input steps back to back with no round trip between them, each held until conditions on the live status hold: [{"buttons": "RIGHT", "until": "x>=134", "max_s": 5}, {"buttons": "A+RIGHT", "until": "state==62", "max_s": 1.5}, {"buttons": "", "max_s": 0.4}]. `until` joins `<field> <op> <number>` with '&' over game_status fields (frame, scene_mode, has_player, state, powerup, x, y, vx, vy, ...); without it a step holds for max_s. Use it when timing matters (a cloud that blinks away, a jump onto a moving lift); game_input costs seconds per call. Returns one row per step: hit or time, and where it ended."""
    try:
        rows = _game().sequence(steps)
    except ValueError as e:
        return {"error": str(e)}
    return {"steps": rows, "status": eden.read_status(P)}


_NAV: dict = {}  # the navigation still running after game_boot returned pending, if any


def _nav_running() -> bool:
    t = _NAV.get("thread")
    return bool(t and t.is_alive())


def _directboot(image: bytes, *, slot: int, kind: int, scene: int, name: str, timeout: int) -> dict:
    """Relaunch Eden with boot.txt so the mod loads `image` into the play
    buffer and fires the transition `kind` from the title: 4 starts Coursebot
    play (scene_mode 7), 3 opens the editor (scene_mode 1) — no TAS menu walk
    (docs/direct-boot.md)."""
    from directboot_cfg import write_boot  # noqa: WPS433

    sd = Path(P.sd_hooks_dir)
    boot_txt, boot_bin = write_boot(sd, image, slot=slot, kind=kind, boot_name=name)

    if eden.process():
        eden.kill()
        time.sleep(2)
    launched = eden.launch(P, gdb=False)
    if not launched.get("process"):
        boot_txt.unlink(missing_ok=True)
        return {"ok": False, "pending": False, "error": "eden_launch failed", "launch": launched}
    # Mod reads boot.txt once at init; leave no leftover for later menu tools.
    time.sleep(3)
    boot_txt.unlink(missing_ok=True)

    g = _game()
    # Cold boot: title ~8 s, play ~16 s with skip_intro (docs/direct-boot.md).
    wait = max(timeout, 90)
    st = g.wait_for(lambda s: s and s.get("scene_mode") == scene, timeout=wait)
    if not st:
        log = sd / "directboot.log"
        return {
            "ok": False,
            "pending": False,
            "error": f"no scene_mode {scene} within {wait} s",
            "directboot_log": log.read_text() if log.exists() else None,
            "boot_bin": str(boot_bin),
            "status": eden.read_status(P),
        }
    return {
        "ok": True,
        "pending": False,
        "method": "directboot",
        "boot_bin": str(boot_bin),
        "status": eden.read_status(P),
    }


def _boot_image(target: str, slot: int | None, file: str | None, sub_area: bool) -> tuple[bytes, str] | dict:
    """The boot.bin image and its name for a direct boot: `file` (a .bcd, a
    .zlib or a plain body), else the slot's .bcd."""
    import directboot_cfg as db  # noqa: WPS433

    if file:
        path = Path(file)
    else:
        if not _save_dir():
            return {"ok": False, "pending": False, "error": "no save dir found"}
        path = Path(P.save_dir) / SLOT_FILES[0].format(slot)
    if not path.exists():
        return {"ok": False, "pending": False, "error": f"no course file {path}"}
    try:
        plain = db.course_body(path)
    except ValueError as e:
        return {"ok": False, "pending": False, "error": str(e)}
    if sub_area:
        plain = db.swap_areas(plain)
    name = f"{path.stem}.{target}.boot.bin" if file else f"course_{slot:03d}.boot.bin"
    return db.boot_bin_from_body(plain), name


SLOT_BACKUPS = Path.home() / ".cache" / "smm2-hooks" / "slot-backups"


def _backup_slots() -> dict | None:
    """Copy every slot's course file before a Coursebot visit, which deletes
    the courses it finds invalid (registered or not). Files are kept once per
    content under pool/<sha1>.bcd; <stamp>.json maps slots to them."""
    import hashlib  # noqa: WPS433

    if not _save_dir():
        return None
    pool = SLOT_BACKUPS / "pool"
    pool.mkdir(parents=True, exist_ok=True)
    slots = {}
    for bcd in sorted(Path(P.save_dir).glob("course_data_[0-9][0-9][0-9].bcd")):
        data = bcd.read_bytes()
        digest = hashlib.sha1(data).hexdigest()
        kept = pool / f"{digest}.bcd"
        if not kept.exists():
            kept.write_bytes(data)
        slots[int(bcd.stem[-3:])] = digest
    registered = _registered_slots()
    manifest = SLOT_BACKUPS / f"{time.strftime('%Y%m%d-%H%M%S')}-{time.time_ns() % 10**9:09d}.json"
    manifest.write_text(json.dumps({"save_dir": P.save_dir, "slots": slots,
                                    "registered": sorted(registered) if registered is not None else None}, indent=1))
    return {"manifest": manifest, "slots": slots, "registered": registered}


def _slots_lost(before: dict) -> dict:
    """Slots a Coursebot visit changed or unregistered since `before` (_backup_slots)."""
    import hashlib  # noqa: WPS433

    changed = []
    for slot, digest in before["slots"].items():
        bcd = Path(P.save_dir) / SLOT_FILES[0].format(slot)
        if not bcd.exists() or hashlib.sha1(bcd.read_bytes()).hexdigest() != digest:
            changed.append(slot)
    registered = _registered_slots()
    unregistered = sorted(before["registered"] - registered) if before["registered"] is not None and registered is not None else []
    out = {"slot_backup": str(before["manifest"])}
    if changed or unregistered:
        out["slots_changed"] = changed
        out["slots_unregistered"] = unregistered
        out["warning"] = (f"the visit changed or unregistered slots {sorted(set(changed) | set(unregistered))}; "
                          f"the files before it are in {before['manifest']} (pool/<sha1>.bcd)")
    return out


@tool(exclusive=True)
def game_boot(
    target: str = "coursebot",
    slot: int | None = None,
    timeout: int = 45,
    budget: int = 120,
    via_menu: bool = False,
    file: str | None = None,
    sub_area: bool = False,
) -> dict:
    """Boot into play or the editor.

    target 'coursebot' with a slot: by default writes boot.txt + a boot.bin from
    that slot's .bcd, relaunches Eden, and lets the mod start Coursebot play from
    the title (scene_mode 7) — no TAS Coursebot UI walk. Pass via_menu=true to
    keep the old button-injection navigation (slower; needs a live session already
    past the title). target 'editor' with a `file` (a .bcd, the sim dataset's
    .zlib, or a plain body) or a slot opens that course straight in the editor
    the same way (scene_mode 1): no Coursebot list, no slot to install, nothing
    the game can delete. sub_area=true swaps the areas first so the sub area
    opens. The editor is opened as Coursebot entry `slot` (0 without one), so
    saving there can write that slot: leave without saving. 'editor' without
    a file or slot, and 'editor_play', navigate the menus.
    Before a Coursebot boot every slot's course file is backed up
    (~/.cache/smm2-hooks/slot-backups); the result names the backup and warns
    when a slot changed or was unregistered by the time the boot finished (a
    deletion when play later returns to the Coursebot list comes after that:
    compare against the manifest).
    The call returns within `budget` seconds; if work is still going it returns
    pending=true and game_status carries the outcome under 'boot'. The final
    result reports 'registered' as save.dat stands after the visit.
    """
    if target not in ("coursebot", "editor", "editor_play"):
        return {"error": f"unknown target {target}"}
    if target == "coursebot" and slot is None:
        return {"error": "slot required"}
    if (file or sub_area) and (via_menu or target == "editor_play"):
        return {"error": "file and sub_area need a direct boot: target 'coursebot' or 'editor', via_menu false"}
    direct_editor = target == "editor" and (file is not None or slot is not None)
    image = None
    if target == "coursebot" and not via_menu or direct_editor:
        image = _boot_image(target, slot, file, sub_area)
        if isinstance(image, dict):
            return image
    g = _game()
    backup = None
    if target == "coursebot":
        _note_played(slot, "game_boot")
        backup = _backup_slots()

    def with_registration(result: dict) -> dict:
        registered = _registered_slots() if target == "coursebot" else None
        if registered is not None:
            result["registered"] = slot in registered
            if slot not in registered and result.get("method") != "directboot":
                result["note"] = "slot is not in save.dat, so this is editor test-play of a default course, not the installed level; level_install registers a slot (the course must pass validation)"
        if backup:
            result.update(_slots_lost(backup))
        return result

    def navigate():
        try:
            if image is not None:
                data, name = image
                kind, scene = (4, 7) if target == "coursebot" else (3, 1)
                _NAV["result"] = with_registration(
                    _directboot(data, slot=slot or 0, kind=kind, scene=scene, name=name, timeout=timeout))
                return
            if target == "coursebot":
                ok = g.to_coursebot_play(slot=slot, timeout=timeout)
            elif target == "editor":
                ok = g.to_editor(timeout=timeout)
            else:
                ok = g.to_play(timeout=timeout)
            _NAV["result"] = with_registration(
                {"ok": bool(ok), "pending": False, "method": "menu", "status": eden.read_status(P)}
            )
        except Exception as e:  # noqa: BLE001
            _NAV["result"] = {"ok": False, "pending": False, "error": repr(e)}

    t = threading.Thread(target=navigate, name="game_boot", daemon=True)
    _NAV.update(
        thread=t,
        result={"ok": False, "pending": True, "target": target, "slot": slot, "file": file, "via_menu": via_menu},
    )
    t.start()
    # Plain join: @tool runs this in a worker thread, so waiting here does not
    # block the event loop. Keep `budget` under the host's per-call limit
    # (this client backgrounds a call after 120 s) and read game_status for
    # the outcome of a pending navigation.
    t.join(budget)
    return dict(_NAV["result"])

def _registered_slots() -> set[int] | None:
    """Slots Coursebot lists: the used_flag per record in save.dat. The .bcd files on disk are not consulted by the game."""
    if not _save_dir():
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
    import importlib, gen_test_levels as g  # noqa: WPS433
    g = importlib.reload(g)   # levels added since the server started must show up
    import parse_course as pc  # noqa: WPS433
    gen = {slot: name for slot, (name, _) in sorted(g.TEST_LEVELS.items())}
    if not _save_dir():
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
    """Write a generated level (name from levels_list) or a course file (a path: the sim dataset's .zlib, or a .bcd) into Coursebot slot N and register it: copies a valid course_thumb + course_replay from another registered slot (or companions_from) and sets the slot's used flag in save.dat. Each replaced file is backed up once as .orig (level_restore puts all three back). Restart the game to see it; Coursebot deletes the slot on its next visit if the course itself is invalid."""
    if (err := _slot_error(slot)):
        return err
    sys.argv = ["x"]
    import importlib, gen_test_levels as g  # noqa: WPS433
    g = importlib.reload(g)   # levels added since the server started must show up
    if not _save_dir():
        return {"error": "no save dir found"}
    path = Path(level)
    if path.suffix in (".zlib", ".bcd") and path.exists():
        # A course file: the sim's dataset keeps decrypted course data zlib-
        # compressed (public/courses/hf/<id>.zlib); a .bcd is taken as is
        # when it decrypts, else as decrypted data to encrypt.
        import directboot_cfg as db  # noqa: WPS433
        import parse_course as pc  # noqa: WPS433
        try:
            plain = db.course_body(path)
        except ValueError as e:
            return {"error": str(e)}
        encrypted = path.suffix == ".bcd" and pc.decrypt_course(str(path)) is not None
        course = path.read_bytes() if encrypted else g.encrypt_course(plain)
        out = _install_slot(slot, course, companions_from)
        return {"level": pc.parse_header(plain)["name"], "file": str(path), **out}
    match = [(s, n, f) for s, (n, f) in g.TEST_LEVELS.items() if n == level]
    if not match:
        return {"error": f"unknown level {level!r}", "available": [n for _, (n, _) in g.TEST_LEVELS.items()]}
    _, name, builder = match[0]
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
    """Attach gdb-multiarch to Eden's stub (real ini port; the Windows host IP from WSL, 127.0.0.1 for a native Eden). Leaves the target stopped; call gdb_continue."""
    cfg = eden.gdb_config(P)
    out = GDB.attach(eden.gdb_host(), cfg["port"])
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



# ── recording ─────────────────────────────────────────────────────────────
# A play session as a fixture: the probe (tools/probe.py presets) traces the
# actors per frame and the mod logs the pad it saw on the same frame counter;
# stop decodes both into <name>_eden.csv + <name>_eden_inputs.csv (the mod's
# tas.csv script) + <name>_eden.json in the sim's fixtures directory.
RECORD_FILE = "record.json"


def _course_mtimes() -> dict[str, int]:
    """mtime_ns of every course_data_NNN.bcd in the save dir, keyed by slot."""
    if not _save_dir():
        return {}
    import save_dat  # noqa: WPS433
    out = {}
    for slot in range(save_dat.RECORD_COUNT):
        path = Path(P.save_dir) / SLOT_FILES[0].format(slot)
        if path.exists():
            out[str(slot)] = path.stat().st_mtime_ns
    return out


def _note_played(slot: int, via: str) -> dict | None:
    """Add a Coursebot slot to the recording in progress, if there is one: stop saves its course."""
    rec = Path(P.sd_hooks_dir) / RECORD_FILE
    if not rec.exists():
        return None
    state = json.loads(rec.read_text())
    registered = _registered_slots()
    entry = {"slot": slot, "via": via, "at": time.strftime("%H:%M:%S"),
             "registered": (slot in registered) if registered is not None else None}
    path = Path(P.save_dir) / SLOT_FILES[0].format(slot) if P.save_dir else None
    if path and path.exists():
        entry["mtime_ns"] = path.stat().st_mtime_ns
    state.setdefault("played", []).append(entry)
    rec.write_text(json.dumps(state, indent=1))
    return entry


def _save_courses(state: dict, stem: Path) -> dict:
    """Copy the course file(s) of the slots the recording played next to the fixture, as
    <stem>_course_NNN.bcd. The played slots are the ones game_boot navigated to during the
    recording or that were named with `slot`. With none known, the registered slots whose
    course file changed since start are copied and `courses_unknown` says so."""
    out: dict = {"courses": [], "notes": []}
    if not _save_dir():
        out["courses_unknown"] = "no save dir found; no course saved"
        return out
    sd = Path(P.save_dir)
    played = state.get("played", [])
    slots = []
    for entry in played:
        if entry["slot"] in slots:
            continue
        if entry.get("registered") is False:
            out["notes"].append(f"slot {entry['slot']} was not registered when played: the game test-played "
                                "a default editor course, not that slot's file; not saved")
            continue
        slots.append(entry["slot"])
    if not played:
        registered = _registered_slots() or set()
        before = state.get("course_mtimes", {})
        now = _course_mtimes()
        slots = sorted(int(k) for k, v in now.items() if int(k) in registered and before.get(k) != v)
        out["courses_unknown"] = (
            "the played slot is unknown (no game_boot to a Coursebot slot during the recording and no slot "
            "given); saved the registered slots whose course file changed since start: "
            f"{slots if slots else 'none'}. Pass slot=N to stop to name the course that was played")
    import shutil  # noqa: WPS433
    for slot in slots:
        src = sd / SLOT_FILES[0].format(slot)
        if not src.exists():
            out["notes"].append(f"slot {slot}: {src.name} is gone; not saved")
            continue
        changed = [e for e in played if e["slot"] == slot and e.get("mtime_ns") not in (None, src.stat().st_mtime_ns)]
        if changed:
            out["notes"].append(f"slot {slot}: {src.name} changed after it was played; saved as it is now")
        dst = Path(f"{stem}_course_{slot:03d}.bcd")
        shutil.copyfile(src, dst)
        out["courses"].append({"slot": slot, "path": str(dst)})
    return out


def _fixtures_dir() -> Path:
    root = HERE.parents[1]
    for name in ("smm2-decomp-integration", "smm2-decomp"):
        d = root / name / "src-sim" / "test" / "fixtures"
        if d.is_dir():
            return d
    return root / "smm2-decomp" / "src-sim" / "test" / "fixtures"


def _probe_module():
    tools_dir = str(HERE.parent / "tools")
    if tools_dir not in sys.path:
        sys.path.insert(0, tools_dir)
    import probe  # noqa: WPS433
    return probe


def _deploy_built_mod() -> dict:
    """The built nso into the active mods dir when it is newer than what is deployed."""
    built = HERE.parent / "build" / "smm2-hooks.nso"
    target = Path(P.mods_dir) / "subsdk4"
    if not built.exists():
        return {"deployed": False, "reason": "build/smm2-hooks.nso missing (ninja -C build)"}
    if target.exists() and target.stat().st_mtime >= built.stat().st_mtime:
        return {"deployed": False, "reason": "already current"}
    import shutil  # noqa: WPS433
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(built, target)
    return {"deployed": True, "path": str(target)}


@tool(exclusive=True)
def trace_record(action: str = "status", name: str = "", presets: str = "player,rail", out_dir: str | None = None,
                 slot: int | None = None) -> dict:
    """Record a play session as a sim fixture. action=start: install the probe presets (comma list of
    tools/probe.py PRESETS: player, rail, note, camera), deploy a newer mod build, relaunch Eden (the
    probe is read at boot) and remember the recording; then play. action=stop: wait for the mod's
    flush, decode probe.log into <out_dir>/<name>_eden.csv (actor rows with the pad columns),
    <name>_eden_inputs.csv (the pad as a tas.csv script) and <name>_eden.json (what was recorded, with the
    marks); out_dir defaults to smm2-decomp's src-sim/test/fixtures. stop also copies the course file of
    each Coursebot slot played into <name>_course_NNN.bcd: a game_boot to a slot during the recording
    counts as played, and `slot` (on mark or stop) names one navigated to by hand; with neither, it
    copies the registered slots whose course changed since start and says so under courses_unknown.
    action=mark: stamp the game's current frame with `name` as a label (a milestone: "reached door A")
    into the recording in progress. action=status: the recording in progress."""
    sd = Path(P.sd_hooks_dir)
    rec = sd / RECORD_FILE
    state = json.loads(rec.read_text()) if rec.exists() else None
    if action == "status":
        log = sd / "probe.log"
        return {"recording": state, "probe_log_bytes": log.stat().st_size if log.exists() else 0, "eden": eden.process()}
    if action == "start":
        if not name.strip():
            return {"error": "name the recording (it names the fixture files)"}
        name = name.strip()
        probe = _probe_module()
        keys = [k.strip() for k in presets.split(",") if k.strip()]
        unknown = [k for k in keys if k not in probe.PRESETS]
        if unknown:
            return {"error": f"unknown presets {unknown}; known: {sorted(probe.PRESETS)}"}
        config = probe.merge_presets(keys)   # presets hooking one function share the hook
        sd.mkdir(parents=True, exist_ok=True)
        cfg = sd / "probe.txt"
        cfg.write_text(config)
        import types  # noqa: WPS433
        import contextlib, io  # noqa: WPS433
        report = io.StringIO()
        with contextlib.redirect_stdout(report):
            failed = probe.cmd_check(types.SimpleNamespace(config=str(cfg)))
        if failed:
            problems = [ln for ln in report.getvalue().splitlines() if not ln.startswith("ok ")]
            return {"error": "the probe config failed its check against main.elf", "problems": problems}
        deployed = _deploy_built_mod()
        killed = None
        if eden.process():
            killed = eden.kill()
        launched = eden.launch(P, False)
        state = {"name": name, "presets": keys, "started": time.strftime("%Y-%m-%d %H:%M:%S"),
                 "out_dir": str(Path(out_dir) if out_dir else _fixtures_dir()), "config": config,
                 "course_mtimes": _course_mtimes()}
        rec.write_text(json.dumps(state, indent=1))
        return {"recording": state, "mod": deployed, "killed": killed, "launch": launched,
                "note": "the probe is armed for this boot: navigate to the course and play; stop when done"}
    if action in ("mark", "stop") and state and slot is not None:
        if (err := _slot_error(slot)):
            return err
        _note_played(slot, "slot")
        state = json.loads(rec.read_text())
    if action == "mark":
        if not state:
            return {"error": "no recording in progress (start one first)"}
        status = eden.read_status(P)
        mark = {"label": name.strip() or f"mark {len(state.get('marks', [])) + 1}",
                "frame": status["frame"] if status else None,
                "scene": status["scene"] if status else None,
                "player": (status or {}).get("player"), "at": time.strftime("%H:%M:%S")}
        state.setdefault("marks", []).append(mark)
        rec.write_text(json.dumps(state, indent=1))
        return {"mark": mark, "marks": state["marks"]}
    if action == "stop":
        if not state:
            return {"error": "no recording in progress (start one first)"}
        time.sleep(6)   # the mod flushes probe.log every 300 frames or 8 KB
        log = sd / "probe.log"
        if not log.exists():
            return {"error": f"{log} missing: was Eden launched after start?", "recording": state}
        probe = _probe_module()
        out = Path(out_dir) if out_dir else Path(state["out_dir"])
        out.mkdir(parents=True, exist_ok=True)
        base = out / f"{state['name']}_eden"
        fixture, inputs, sidecar = f"{base}.csv", f"{base}_inputs.csv", f"{base}.json"
        try:
            decoded = probe.decode_log(str(log), fixture, inputs)
        except SystemExit as e:
            return {"error": str(e), "recording": state}
        status = eden.read_status(P)
        courses = _save_courses(state, out / state["name"])
        # The sidecar is committed next to its CSVs: names only, no paths from this machine.
        recorded = {k: v for k, v in state.items() if k not in ("out_dir", "course_mtimes")}
        meta = {**recorded, "stopped": time.strftime("%Y-%m-%d %H:%M:%S"), "decoded": decoded,
                "status_at_stop": status, "files": {"fixture": Path(fixture).name, "inputs": Path(inputs).name,
                                                    "courses": {f"{c['slot']:03d}": Path(c["path"]).name for c in courses["courses"]}}}
        extra = {k: courses[k] for k in ("courses_unknown", "notes") if courses.get(k)}
        meta.update(extra)
        Path(sidecar).write_text(json.dumps(meta, indent=1))
        rec.unlink()
        saved = {"fixture": fixture, "inputs": inputs, "sidecar": sidecar,
                 "courses": {f"{c['slot']:03d}": c["path"] for c in courses["courses"]}}
        return {"saved": saved, **extra, "decoded": decoded, "status_at_stop": status}
    return {"error": f"unknown action {action}; start, stop or status"}


def _keep_stdin_for_the_protocol() -> None:
    """Move the JSON-RPC stream off fd 0 and put /dev/null there.

    A Windows program started from WSL (eden.exe, powershell.exe, and any
    tool module that runs one) is given the parent's stdin through the
    interop relay, and the relay READS it: a PowerShell child took every
    byte waiting on a piped stdin (2000 of 2000, and none with stdin
    redirected). In this server stdin is the host's request stream, so a
    tool that ran PowerShell or launched Eden could swallow the next
    request; its reply never came and the host's later calls hung too.
    With fd 0 on /dev/null every child, in this module or a tool it
    imports, inherits nothing to read, and the transport reads its own
    duplicate of the pipe.
    """
    proto = os.dup(0)
    null = os.open(os.devnull, os.O_RDONLY)
    os.dup2(null, 0)
    os.close(null)
    sys.stdin = os.fdopen(proto, "r", encoding="utf-8", errors="replace")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        print(json.dumps(anyio.run(eden_state), indent=1)[:1500])
    else:
        _keep_stdin_for_the_protocol()
        mcp.run()
