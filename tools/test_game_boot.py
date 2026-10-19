"""mcp/server.py game_boot and game_input, without an emulator.

game_boot opens a course file straight in the editor, and backs up every slot
before a Coursebot visit, which deletes the courses it finds invalid. Needs
the MCP server's dependencies:
    mcp/.venv/bin/python -m unittest discover -s tools -p test_game_boot.py
"""
import dataclasses
import json
import sys
import tempfile
import types
import unittest
import zlib
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "mcp"))

import directboot_cfg as db  # noqa: E402
import gen_test_levels as g  # noqa: E402
import save_dat  # noqa: E402
import server  # noqa: E402

PLAIN = {name: getattr(server, name).__wrapped__ for name in ("game_boot", "game_input")}


class GameBoot(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.save, self.sd = self.root / "save", self.root / "sd"
        for d in (self.save, self.sd):
            d.mkdir()
        self.register(0, 3)
        for slot in (0, 3, 7):
            (self.save / f"course_data_{slot:03d}.bcd").write_bytes(b"course %d" % slot)
        paths = dataclasses.replace(server.P, save_dir=str(self.save), sd_hooks_dir=str(self.sd))
        self.patch(server, "P", paths)
        self.patch(server, "SLOT_BACKUPS", self.root / "slot-backups")
        self.patch(server.eden, "read_status", lambda _p: {"frame": 1})
        self.boots = []

        def directboot(image, **kw):
            self.boots.append((image, kw))
            return {"ok": True, "pending": False, "method": "directboot"}
        self.patch(server, "_directboot", directboot)

    def patch(self, target, attr, value):
        patcher = mock.patch.object(target, attr, value)
        patcher.start()
        self.addCleanup(patcher.stop)

    def register(self, *slots):
        body = bytearray(save_dat.BODY)
        for i in range(save_dat.RECORD_COUNT):
            body[save_dat.RECORDS + 8 * i] = i
        for slot in slots:
            body[save_dat.RECORDS + 8 * slot + 1] = 1
        (self.save / "save.dat").write_bytes(save_dat.encrypt(bytes(body)))

    def test_file_opens_in_the_editor(self):
        plain = g.LevelBuilder(name="Real", style="NSMBU", theme="Ground").build()
        course = self.root / "3002534.zlib"
        course.write_bytes(zlib.compress(plain))
        result = PLAIN["game_boot"](target="editor", file=str(course), budget=5)
        self.assertTrue(result["ok"])
        [(image, kw)] = self.boots
        self.assertEqual(image, db.boot_bin_from_body(plain))
        self.assertEqual((kw["kind"], kw["scene"], kw["slot"], kw["name"]), (3, 1, 0, "3002534.editor.boot.bin"))
        self.assertEqual(list((self.root / "slot-backups").glob("*")), [])   # no Coursebot, no backup

    def test_sub_area_swaps_the_areas(self):
        plain = g.LevelBuilder(name="Real", style="SMB1", theme="Ground").build()
        course = self.root / "c.zlib"
        course.write_bytes(zlib.compress(plain))
        PLAIN["game_boot"](target="editor", file=str(course), sub_area=True, budget=5)
        [(image, _kw)] = self.boots
        self.assertEqual(image, db.boot_bin_from_body(db.swap_areas(plain)))

    def test_slot_opens_in_the_editor(self):
        plain = g.LevelBuilder(name="Slot", style="SMW", theme="Ground").build()
        (self.save / "course_data_003.bcd").write_bytes(g.encrypt_course(plain))
        PLAIN["game_boot"](target="editor", slot=3, budget=5)
        [(image, kw)] = self.boots
        self.assertEqual(image, db.boot_bin_from_body(plain))
        self.assertEqual((kw["kind"], kw["scene"], kw["slot"], kw["name"]), (3, 1, 3, "course_003.boot.bin"))

    def test_direct_coursebot_boot_backs_up_first(self):
        plain = g.LevelBuilder(name="Slot", style="SMB3", theme="Ground").build()
        bcd = g.encrypt_course(plain)
        (self.save / "course_data_003.bcd").write_bytes(bcd)
        result = PLAIN["game_boot"](target="coursebot", slot=3, budget=5)
        [(image, kw)] = self.boots
        self.assertEqual(image, db.boot_bin_from_body(plain))
        self.assertEqual((kw["kind"], kw["scene"], kw["slot"], kw["name"]), (4, 7, 3, "course_003.boot.bin"))
        manifest = json.loads(Path(result["slot_backup"]).read_text())
        kept = self.root / "slot-backups" / "pool" / f"{manifest['slots']['3']}.bcd"
        self.assertEqual(kept.read_bytes(), bcd)
        self.assertNotIn("warning", result)

    def test_bad_file_is_refused_before_anything_runs(self):
        bad = self.root / "short.bin"
        bad.write_bytes(b"x")
        corrupt = self.root / "corrupt.zlib"
        corrupt.write_bytes(b"not zlib")
        for kwargs in ({"target": "editor", "file": str(bad)},
                       {"target": "editor", "file": str(corrupt)},
                       {"target": "editor", "file": str(self.root / "missing.zlib")},
                       {"target": "editor_play", "file": str(bad)},
                       {"target": "editor", "file": str(bad), "via_menu": True},
                       {"target": "coursebot", "slot": 3, "via_menu": True, "sub_area": True}):
            self.assertIn("error", PLAIN["game_boot"](budget=5, **kwargs), kwargs)
        self.assertEqual(self.boots, [])

    def test_coursebot_visit_reports_deleted_slots(self):
        def visit(slot, timeout):
            (self.save / "course_data_007.bcd").write_bytes(b"rewritten")   # the game's "corrupt data" pass
            self.register(0)
            return True
        game = types.SimpleNamespace(to_coursebot_play=visit)
        with mock.patch.object(server, "_game", lambda: game):
            result = PLAIN["game_boot"](target="coursebot", slot=0, via_menu=True, budget=5)
        self.assertEqual(result["slots_changed"], [7])
        self.assertEqual(result["slots_unregistered"], [3])
        manifest = json.loads(Path(result["slot_backup"]).read_text())
        self.assertEqual(manifest["registered"], [0, 3])
        kept = self.root / "slot-backups" / "pool" / f"{manifest['slots']['7']}.bcd"
        self.assertEqual(kept.read_bytes(), b"course 7")

    def test_quiet_coursebot_visit_only_names_the_backup(self):
        game = types.SimpleNamespace(to_coursebot_play=lambda slot, timeout: True)
        with mock.patch.object(server, "_game", lambda: game):
            result = PLAIN["game_boot"](target="coursebot", slot=0, via_menu=True, budget=5)
        self.assertIn("slot_backup", result)
        self.assertNotIn("warning", result)

    def test_stick(self):
        presses = []
        game = types.SimpleNamespace(press=lambda buttons, ms, lx, ly: presses.append((buttons, ms, lx, ly)))
        with mock.patch.object(server, "_game", lambda: game):
            PLAIN["game_input"](stick="0,32767", ms=6000)
            PLAIN["game_input"]("A")
        self.assertEqual(presses, [(0, 6000, 0, 32767), ("A", 120, 0, 0)])
        for bad in ("32767", "a,b", "0,40000"):
            self.assertIn("error", PLAIN["game_input"](stick=bad))
        self.assertEqual(len(presses), 2)


if __name__ == "__main__":
    unittest.main()
