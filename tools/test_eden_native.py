"""mcp/eden.py on a native (Linux) Eden: paths from EDEN_USER_DIR, the process
found in /proc and stopped with signals, the stub probed in /proc/net/tcp. The
Windows-from-WSL path must stay as it was.

No emulator: the "Eden" here is a copy of `sleep` named eden, run directly and
through the dynamic loader (how an extracted sharun AppImage runs it). Linux only.

    python3 -m unittest tools/test_eden_native.py      (from the repo root)
"""
from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "mcp"))

import eden  # noqa: E402

LOADER = next((p for p in ("/lib64/ld-linux-x86-64.so.2", "/lib/ld-linux-aarch64.so.1") if os.path.exists(p)), None)


# The fakes' program name. eden.process() and eden.kill() match by name, so
# with the real one ("eden") the tests would find, and kill, an Eden that is
# running on the machine.
FAKE = f"edenfake{os.getpid()}"


def _env(**kw):
    """Environment with only the given EDEN_* variables (and no .env in play);
    the process name is the fakes' unless a test names one."""
    base = {k: v for k, v in os.environ.items() if not k.startswith("EDEN_")}
    return mock.patch.dict(os.environ, {**base, "EDEN_PROCESS_NAME": FAKE, **kw}, clear=True)


@unittest.skipUnless(sys.platform.startswith("linux"), "Linux only")
class Native(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        dotenv = mock.patch.object(eden, "_dotenv", return_value={})
        dotenv.start()
        self.addCleanup(dotenv.stop)
        self.procs: list[subprocess.Popen] = []
        self.addCleanup(self._reap)

    def _reap(self):
        for p in self.procs:
            if p.poll() is None:
                p.kill()
            p.wait()

    def _fake_eden(self, via_loader=False, name=FAKE) -> subprocess.Popen:
        exe = self.tmp / "bin" / name
        exe.parent.mkdir(exist_ok=True)
        shutil.copy(shutil.which("sleep"), exe)
        argv = [str(exe), "30"]
        if via_loader:
            argv = [LOADER, "--library-path", "/nonexistent", str(exe), "30"]
        p = subprocess.Popen(argv)
        self.procs.append(p)
        time.sleep(0.2)
        return p

    def test_native_is_decided_by_the_exe(self):
        self.assertFalse(eden.native("/mnt/c/Users/x/Documents/eden/eden.exe"))
        self.assertFalse(eden.native("C:/eden/EDEN.EXE"))
        self.assertTrue(eden.native("/home/x/toolchain/bin/eden"))
        with _env():
            self.assertFalse(eden.native(), "the default EDEN_EXE is the Windows one")

    def test_paths_from_user_dir(self):
        user = self.tmp / "state" / "user"
        (user / "config").mkdir(parents=True)
        save = user / "nand" / "user" / "save" / "0000000000000000" / "ABCD" / eden.TITLE_ID
        save.mkdir(parents=True)
        (user / "config" / "qt-config.ini").write_text(
            f"[Data%20Storage]\nnand_directory={user}/nand\nsdmc_directory={user}/sd\n")
        with _env(EDEN_EXE="/opt/eden/eden", EDEN_USER_DIR=str(user), EDEN_GAME_PATH="/rom/g.xci"):
            p = eden.paths()
        self.assertTrue(p.portable)
        self.assertEqual(p.user_dir, str(user))
        self.assertEqual(p.config_ini, f"{user}/config/qt-config.ini")
        self.assertEqual(p.sdmc_dir, f"{user}/sd")             # from the ini, unconverted
        self.assertEqual(p.load_dir, f"{user}/load")           # the default under the user dir
        self.assertEqual(p.sd_hooks_dir, f"{user}/sd/smm2-hooks")
        self.assertEqual(p.mods_dir, f"{user}/load/{eden.TITLE_ID}/smm2-hooks/exefs")
        self.assertEqual(p.save_dir, str(save))
        self.assertEqual(p.log_file, f"{user}/log/eden_log.txt")
        self.assertEqual(p.game, "/rom/g.xci")

    def test_paths_without_user_dir_follow_xdg(self):
        with _env(EDEN_EXE="/opt/eden/eden"), mock.patch.dict(
                os.environ, {"XDG_DATA_HOME": str(self.tmp / "d"), "XDG_CONFIG_HOME": str(self.tmp / "c")}):
            p = eden.paths()
        self.assertFalse(p.portable)
        self.assertEqual(p.user_dir, str(self.tmp / "d" / "eden"))
        self.assertEqual(p.config_ini, str(self.tmp / "c" / "eden" / "qt-config.ini"))
        self.assertEqual(p.sdmc_dir, str(self.tmp / "d" / "eden" / "sdmc"))

    def test_windows_paths_unchanged(self):
        # The portable check looks at the real disk; hold it to "no user/ dir"
        # so the test reads the same on a machine that has one.
        with _env(EDEN_EXE="/mnt/c/Users/nico/Documents/eden/eden.exe"), \
                mock.patch("os.path.isdir", return_value=False):
            p = eden.paths()
        self.assertEqual(p.user_dir, "/mnt/c/Users/nico/AppData/Roaming/eden")   # no portable dir here
        self.assertEqual(p.sdmc_dir, "/mnt/c/Users/nico/AppData/Roaming/eden/sdmc")

    def test_is_eden(self):
        self.assertTrue(eden._is_eden(["/a/eden", "-g", "x"], "eden"))
        self.assertTrue(eden._is_eden(["/a/shared/lib/ld-linux-x86-64.so.2", "--library-path", "/l",
                                       "/a/shared/bin/eden", "-g", "x"], "eden"))
        self.assertFalse(eden._is_eden(["python3", "mcp/eden.py", "--brief"], "eden"))
        self.assertFalse(eden._is_eden(["sleep", "30", "eden"], "eden"))
        self.assertFalse(eden._is_eden(["/a/eden-cli"], "eden"))
        self.assertFalse(eden._is_eden([], "eden"))

    def test_process_found_and_killed(self):
        with _env(EDEN_EXE="/opt/eden/eden"):
            self.assertIsNone(eden.process())
            p = self._fake_eden()
            proc = eden.process()
            self.assertIsNotNone(proc)
            self.assertEqual(proc["pid"], p.pid)
            self.assertRegex(proc["started"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d$")
            self.assertEqual(eden.kill(), {"process": None})
            self.assertIsNotNone(p.poll(), "the process is gone")

    @unittest.skipUnless(LOADER, "no dynamic loader at a known path")
    def test_process_run_through_the_loader(self):
        with _env(EDEN_EXE="/opt/eden/eden"):
            p = self._fake_eden(via_loader=True)
            self.assertEqual((eden.process() or {}).get("pid"), p.pid)
            eden.kill()
            self.assertIsNotNone(p.poll())

    def test_other_names_ignored(self):
        with _env(EDEN_EXE="/opt/eden/eden"):
            self._fake_eden(name="eden-cli")
            self.assertIsNone(eden.process())
        with _env(EDEN_EXE="/opt/eden/eden", EDEN_PROCESS_NAME="eden-cli"):
            self.assertIsNotNone(eden.process())

    def test_stub_listening(self):
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        with _env(EDEN_EXE="/opt/eden/eden"):
            self.assertFalse(eden.stub_listening(port))
            s.listen(1)
            self.assertTrue(eden.stub_listening(port))
            s.close()
            self.assertFalse(eden.stub_listening(port))
            self.assertEqual(eden.gdb_host(), "127.0.0.1")

    def test_launch_runs_the_exe_with_the_game(self):
        user = self.tmp / "user"
        (user / "config").mkdir(parents=True)
        (user / "config" / "qt-config.ini").write_text(
            "[Debugging]\nuse_gdbstub\\default=true\nuse_gdbstub=false\n"
            "[System]\nuse_docked_mode\\default=false\nuse_docked_mode=0\n")
        args = self.tmp / "args.txt"
        exe = self.tmp / "eden"
        # a stand-in that records its argv, then becomes a long-lived "eden"
        exe.write_text(f'#!/bin/bash\necho "$@" > {args}\nexec -a {FAKE} {shutil.which("sleep")} 30\n')
        exe.chmod(0o755)
        with _env(EDEN_EXE=str(exe), EDEN_USER_DIR=str(user), EDEN_GAME_PATH="/mnt/d/roms/g.xci"), \
                mock.patch.object(eden, "process", side_effect=lambda: {"pid": 1, "mem_mb": 99, "started": None}):
            r = eden.launch(eden.paths(), gdb=True)
        try:
            self.assertTrue(r["gdbstub_config_changed"])
            ini = (user / "config" / "qt-config.ini").read_text()
            self.assertIn("use_gdbstub=true", ini)
            self.assertIn("use_gdbstub\\default=false", ini)
            self.assertIn("use_docked_mode=1", ini)
            for _ in range(50):
                if args.exists():
                    break
                time.sleep(0.1)
            self.assertEqual(args.read_text().strip(), "-g /mnt/d/roms/g.xci")   # no wsl_to_win (D:/roms/...)
        finally:
            with _env(EDEN_EXE=str(exe)):
                eden.kill()


if __name__ == "__main__":
    unittest.main()
