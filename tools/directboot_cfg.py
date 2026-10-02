"""Helpers for sd:/smm2-hooks/boot.txt — boot straight into a course.

The mod's directboot (src/directboot.cpp, docs/direct-boot.md) reads boot.txt
once at launch. `coursebot <slot> <kind>` fires the Coursebot Play transition;
`file <sd path>` loads that course into the play buffer first (the transition
itself does not pick the Coursebot entry's bytes). The file is a .bcd's
0x10-byte header plus its decrypted body (0x5BFC0 bytes), with SCDL at +0xC.
"""
from __future__ import annotations

import struct
import zlib
from pathlib import Path

COURSE_BODY = 0x5BFC0
COURSE_BYTES = 0x10 + COURSE_BODY  # header + decrypted body


def boot_bin_from_bcd(bcd: Path) -> bytes:
    """Build the play-buffer image directboot's `file` line expects."""
    import parse_course as pc  # noqa: WPS433

    path = Path(bcd)
    raw = path.read_bytes()
    plain = pc.decrypt_course(str(path))
    if plain is None:
        raise ValueError(f"cannot decrypt {path}")
    if len(plain) != COURSE_BODY:
        raise ValueError(f"decrypted body is {len(plain)} bytes, want {COURSE_BODY}")
    # Rebuild the header so the CRC matches the plaintext we load (same shape
    # as gen_test_levels.encrypt_course's header).
    header = bytearray(0x10)
    struct.pack_into("<I", header, 0x00, 1)
    struct.pack_into("<I", header, 0x04, 0x00010010)
    struct.pack_into("<I", header, 0x08, zlib.crc32(plain) & 0xFFFFFFFF)
    header[0x0C:0x10] = b"SCDL"
    # Prefer the on-disk header when its CRC already matches the plaintext.
    if (
        len(raw) >= 0x10
        and raw[0x0C:0x10] == b"SCDL"
        and raw[0x08:0x0C] == header[0x08:0x0C]
    ):
        return raw[:0x10] + plain
    return bytes(header) + plain


def write_slot_boot(
    sd_dir: Path,
    bcd: Path,
    *,
    slot: int,
    kind: int = 4,
    boot_name: str | None = None,
    two_phase: bool = False,
) -> tuple[Path, Path]:
    """Write boot.txt + a boot.bin for `slot` under sd_dir. Returns (boot.txt, boot.bin)."""
    sd = Path(sd_dir)
    sd.mkdir(parents=True, exist_ok=True)
    name = boot_name or f"course_{slot:03d}.boot.bin"
    boot_bin = sd / name
    boot_bin.write_bytes(boot_bin_from_bcd(bcd))
    # Mod paths are Switch SD paths; the host tree is mirrored under sdmc.
    sd_path = f"sd:/smm2-hooks/{name}"
    boot_txt = sd / "boot.txt"
    keyword = "coursebot2" if two_phase else "coursebot"
    boot_txt.write_text(f"{keyword} {slot} {kind}\nfile {sd_path}\n")
    return boot_txt, boot_bin
