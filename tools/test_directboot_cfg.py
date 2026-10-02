#!/usr/bin/env python3
"""Unit tests for tools/directboot_cfg.py — boot.bin shape for directboot `file`."""
from __future__ import annotations

import struct
import sys
import tempfile
import zlib
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import directboot_cfg as db  # noqa: E402
import gen_test_levels as g  # noqa: E402


def main() -> int:
    # Minimal encrypted .bcd from a generated empty-ish course.
    plain = g.LevelBuilder(name="Boot Test", style="SMB1", theme="Ground").build()
    assert len(plain) == db.COURSE_BODY
    bcd = g.encrypt_course(plain)
    with tempfile.TemporaryDirectory() as tmp:
        bcd_path = Path(tmp) / "course_data_007.bcd"
        bcd_path.write_bytes(bcd)
        image = db.boot_bin_from_bcd(bcd_path)
        assert len(image) == db.COURSE_BYTES, len(image)
        assert image[0x0C:0x10] == b"SCDL"
        assert image[0x10:] == plain
        crc = struct.unpack_from("<I", image, 0x08)[0]
        assert crc == (zlib.crc32(plain) & 0xFFFFFFFF)

        sd = Path(tmp) / "sd"
        boot_txt, boot_bin = db.write_slot_boot(sd, bcd_path, slot=7, kind=4)
        assert boot_bin.read_bytes() == image
        text = boot_txt.read_text()
        assert "coursebot 7 4" in text
        assert "file sd:/smm2-hooks/course_007.boot.bin" in text
    print("ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
