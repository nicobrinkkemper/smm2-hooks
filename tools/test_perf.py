"""perf.py's flag file and eden.set_speed_limit, on a scratch SD folder and ini."""
import sys
import tempfile
import types
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "mcp"))
import eden  # noqa: E402
import perf  # noqa: E402

INI = b"[Core]\r\nuse_speed_limit\\default=true\r\nuse_speed_limit=true\r\nspeed_limit\\default=true\r\nspeed_limit=100\r\n"


class Perf(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        root = Path(self.dir.name)
        (root / "qt-config.ini").write_bytes(INI)
        self.p = types.SimpleNamespace(sd_hooks_dir=str(root), config_ini=str(root / "qt-config.ini"))

    def tearDown(self):
        self.dir.cleanup()

    def test_flag_is_off_without_the_file(self):
        self.assertFalse(perf.is_on(self.p))

    def test_on_writes_what_the_mod_reads_and_off_removes_it(self):
        perf.set_flag(self.p, True)
        self.assertEqual(perf.flag(self.p).read_bytes()[:2], b"on")   # src/perf.cpp compares the first two bytes
        self.assertTrue(perf.is_on(self.p))
        perf.set_flag(self.p, False)
        self.assertFalse(perf.flag(self.p).exists())
        perf.set_flag(self.p, False)   # off twice is fine

    def test_speed_limit_off_and_back_leaves_the_ini_as_it_was(self):
        ini = Path(self.p.config_ini)
        self.assertTrue(eden.set_speed_limit(self.p, False))
        self.assertEqual(ini.read_bytes(), INI.replace(b"use_speed_limit\\default=true", b"use_speed_limit\\default=false")
                                              .replace(b"use_speed_limit=true", b"use_speed_limit=false"))
        self.assertFalse(eden.set_speed_limit(self.p, False))   # already off: nothing to put back
        self.assertTrue(eden.set_speed_limit(self.p, True))
        self.assertEqual(ini.read_bytes(), INI)


if __name__ == "__main__":
    unittest.main()
