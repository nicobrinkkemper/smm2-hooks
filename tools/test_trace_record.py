"""mcp/server.py trace_record: stop saves the course(s) the recording played.

Drives start bookkeeping and the stop path against a fake save dir and a fake
sd:/smm2-hooks dir; no emulator. Needs the MCP server's dependencies:
    mcp/.venv/bin/python -m unittest discover -s tools -p test_trace_record.py
"""
import dataclasses
import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "mcp"))

import save_dat  # noqa: E402
import server  # noqa: E402

PLAIN = {name: getattr(server, name).__wrapped__ for name in ("trace_record", "game_boot")}


class FakeProbe:
    PRESETS = {"player": "player\n"}

    @staticmethod
    def decode_log(log, fixture, inputs):
        Path(fixture).write_text("frame\n")
        Path(inputs).write_text("frame,buttons\n")
        return {"rows": 1}


class TraceRecordCourses(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        self.save, self.sd, self.out = root / "save", root / "sd", root / "fixtures"
        for d in (self.save, self.sd):
            d.mkdir()
        (self.sd / "probe.log").write_bytes(b"x")
        self.register(0, 3, 7)
        for slot in (0, 3, 7, 9):
            self.course(slot, b"course %d" % slot)
        paths = dataclasses.replace(server.P, save_dir=str(self.save), sd_hooks_dir=str(self.sd))
        self.patch(server, "P", paths)
        self.patch(server.time, "sleep", lambda _s: None)
        self.patch(server, "_probe_module", lambda: FakeProbe)
        self.patch(server.eden, "read_status", lambda _p: {"frame": 1, "scene": "coursebot_play"})

    def patch(self, target, attr, value):
        patcher = mock.patch.object(target, attr, value)
        patcher.start()
        self.addCleanup(patcher.stop)

    def register(self, *slots):
        body = bytearray(save_dat.BODY)
        for i in range(save_dat.RECORD_COUNT):   # each record: slot number, used flag, ...
            body[save_dat.RECORDS + 8 * i] = i
        for slot in slots:
            body[save_dat.RECORDS + 8 * slot + 1] = 1
        (self.save / "save.dat").write_bytes(save_dat.encrypt(bytes(body)))

    def course(self, slot, data, mtime_ns=None):
        path = self.save / f"course_data_{slot:03d}.bcd"
        path.write_bytes(data)
        if mtime_ns is not None:
            os.utime(path, ns=(mtime_ns, mtime_ns))
        return path

    def start(self, name="walk"):
        """What action=start leaves in record.json, without the probe check and the relaunch."""
        state = {"name": name, "presets": ["player"], "started": "now", "out_dir": str(self.out),
                 "config": "player\n", "course_mtimes": server._course_mtimes()}
        (self.sd / server.RECORD_FILE).write_text(json.dumps(state))

    def stop(self, **kwargs):
        return PLAIN["trace_record"](action="stop", **kwargs)

    def sidecar(self, name="walk"):
        return json.loads((self.out / f"{name}_eden.json").read_text())

    def test_game_boot_slot_is_saved(self):
        self.start()
        game = types.SimpleNamespace(to_coursebot_play=lambda slot, timeout: True)
        with mock.patch.object(server, "_game", lambda: game):
            PLAIN["game_boot"](target="coursebot", slot=3, budget=5)
        self.course(7, b"saved over during the session")   # another slot changing does not count
        result = self.stop()
        saved = self.out / "walk_course_003.bcd"
        self.assertEqual(result["saved"]["courses"], {"003": str(saved)})
        self.assertEqual(saved.read_bytes(), b"course 3")
        self.assertNotIn("courses_unknown", result)
        meta = self.sidecar()
        self.assertEqual(meta["files"]["courses"], {"003": "walk_course_003.bcd"})
        self.assertEqual([p["slot"] for p in meta["played"]], [3])
        self.assertNotIn("course_mtimes", meta)
        self.assertNotIn(str(self.save), json.dumps(meta))   # no machine paths in the committed sidecar
        self.assertFalse((self.sd / server.RECORD_FILE).exists())

    def test_slot_named_on_stop_and_mark(self):
        self.start()
        PLAIN["trace_record"](action="mark", name="door", slot=0)
        result = self.stop(slot=7)
        self.assertEqual(sorted(result["saved"]["courses"]), ["000", "007"])
        self.assertEqual((self.out / "walk_course_007.bcd").read_bytes(), b"course 7")

    def test_unregistered_slot_is_not_saved(self):
        self.start()
        result = self.stop(slot=9)
        self.assertEqual(result["saved"]["courses"], {})
        self.assertTrue(any("slot 9" in n for n in result["notes"]))

    def test_bad_slot_is_refused(self):
        self.start()
        self.assertIn("error", self.stop(slot=999))
        self.assertTrue((self.sd / server.RECORD_FILE).exists())

    def test_course_changed_after_play_is_flagged(self):
        self.start()
        PLAIN["trace_record"](action="mark", slot=3)
        self.course(3, b"replaced", mtime_ns=1_000_000_000)
        result = self.stop()
        self.assertEqual((self.out / "walk_course_003.bcd").read_bytes(), b"replaced")
        self.assertTrue(any("changed after it was played" in n for n in result["notes"]))

    def test_unknown_slot_falls_back_to_changed_registered_courses(self):
        self.course(0, b"course 0", mtime_ns=1_000_000_000)
        self.course(9, b"course 9", mtime_ns=1_000_000_000)
        self.start()
        self.course(0, b"edited during the session", mtime_ns=2_000_000_000)
        self.course(9, b"unregistered, edited", mtime_ns=2_000_000_000)
        result = self.stop()
        self.assertEqual(list(result["saved"]["courses"]), ["000"])
        self.assertIn("unknown", result["courses_unknown"])
        self.assertIn("courses_unknown", self.sidecar())

    def test_unknown_slot_and_nothing_changed(self):
        self.start()
        result = self.stop()
        self.assertEqual(result["saved"]["courses"], {})
        self.assertIn("none", result["courses_unknown"])


if __name__ == "__main__":
    unittest.main()
