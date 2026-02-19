#!/usr/bin/env python3
"""gen_level.py — Generate minimal SMM2 test levels.

Creates a simple flat level with specified style/theme for testing.
Writes encrypted BCD to Eden save slot.

Usage:
    python3 gen_level.py --style SMB1 --theme Ground --slot 0
    python3 gen_level.py --style 3DW --theme Ghost --slot 1

VALIDATION RULES (from decomp CourseDataValidator):
- Objects must be on grid (positions in deci-pixels, 160 = 1 tile)
- Spawn exclusion zone: 3 tiles (48 pixels) from player spawn
- Player spawns at x=0 by default, y from header start_y field
- Goal is required (id=27), must be reachable
- Object positions must not overlap spawn area

OBJECT IDs (from bcd-format.ksy):
    0=goomba, 4=block, 5=question_block, 6=hard_block, 7=ground,
    8=coin, 9=pipe, 10=spring, 15=bob_omb, 20=super_mushroom,
    23=note_block, 27=goal, 33=one_up, 34=fire_flower, 35=super_star
"""

import struct
import zlib
import os
import argparse
from pathlib import Path
from Crypto.Cipher import AES

# Style/theme mappings
STYLES = {'SMB1': 0, 'SMB3': 1, 'SMW': 2, 'NSMBU': 3, '3DW': 4}
STYLE_CODES = {0: b'M1', 1: b'M3', 2: b'MW', 3: b'WU', 4: b'3W'}
THEMES = {
    'Ground': 0, 'Underground': 1, 'Castle': 2, 'Airship': 3, 'Underwater': 4,
    'Ghost': 5, 'Snow': 6, 'Desert': 7, 'Sky': 8, 'Forest': 9
}

# Crypto constants (same as parse_course.py)
COURSE_KEY_TABLE = [
    0x7AB1C9D2, 0xCA750936, 0x3003E59C, 0xF261014B,
    0x2E25160A, 0xED614811, 0xF1AC6240, 0xD59272CD,
    0xF38549BF, 0x6CF5B327, 0xDA4DB82A, 0x820C435A,
    0xC95609BA, 0x19BE08B0, 0x738E2B81, 0xED3C349A,
    0x045275D1, 0xE0A73635, 0x1DEBF4DA, 0x9924B0DE,
    0x6A1FC367, 0x71970467, 0xFC55ABEB, 0x368D7489,
    0x0CC97D1D, 0x17CC441E, 0x3528D152, 0xD0129B53,
    0xE12A69E9, 0x13D1BDB7, 0x32EAA9ED, 0x42F41D1B,
    0xAEA5F51F, 0x42C5D23C, 0x7CC742ED, 0x723BA5F9,
    0xDE5B99E3, 0x2C0055A4, 0xC38807B4, 0x4C099B61,
    0xC4E4568E, 0x8C29C901, 0xE13B34AC, 0xE7C3F212,
    0xB67EF941, 0x08038965, 0x8AFD1E6A, 0x8E5341A3,
    0xA4C61107, 0xFBAF1418, 0x9B05EF64, 0x3C91734E,
    0x82EC6646, 0xFB19F33E, 0x3BDE6FE2, 0x17A84CCA,
    0xCCDF0CE9, 0x50E4135C, 0xFF2658B2, 0x3780F156,
    0x7D8F5D68, 0x517CBED1, 0x1FCDDF0D, 0x77A58C94,
]

class SeadRandom:
    def __init__(self, s0, s1, s2, s3):
        self.state = [s0, s1, s2, s3]
    
    def u32(self):
        s = self.state
        temp = (s[0] ^ ((s[0] << 11) & 0xFFFFFFFF)) & 0xFFFFFFFF
        temp ^= temp >> 8
        temp ^= s[3]
        temp ^= s[3] >> 19
        s[0], s[1], s[2], s[3] = s[1], s[2], s[3], temp
        return temp
    
    def uint(self, max_val):
        return (self.u32() * max_val) >> 32


def create_key(rand, table, size):
    key = b''
    for _ in range(size // 4):
        value = 0
        for _ in range(4):
            index = rand.uint(len(table))
            shift = rand.uint(4) * 8
            byte = (table[index] >> shift) & 0xFF
            value = (value << 8) | byte
        key += struct.pack('<I', value)
    return key


def create_minimal_course(style_id: int, theme_id: int) -> bytes:
    """Create minimal valid course data (decrypted, 0x5BFC0 bytes)."""
    
    # Course data is 0x5BFC0 bytes
    data = bytearray(0x5BFC0)
    
    # === Header (0x000 - 0x1FF) ===
    # For flat ground with walkable path to goal
    # Minimum level width is 24 tiles
    data[0x00] = 5   # start_y (tiles from bottom)
    data[0x01] = 4   # goal_y - ONE TILE DOWN to align ground levels  
    struct.pack_into('<h', data, 0x02, 24)   # goal_x - minimum level size (24 tiles)
    struct.pack_into('<h', data, 0x04, 300)  # time_limit (seconds)
    struct.pack_into('<h', data, 0x06, 0)    # clear_condition_magnitude
    
    # Creation date
    struct.pack_into('<h', data, 0x08, 2026)  # year
    data[0x0A] = 2   # month
    data[0x0B] = 18  # day
    data[0x0C] = 12  # hour
    data[0x0D] = 0   # minute
    
    data[0x0E] = 0   # autoscroll_speed
    data[0x0F] = 0   # clear_condition_category
    struct.pack_into('<i', data, 0x10, 0)    # clear_condition
    struct.pack_into('<I', data, 0x14, 32)   # unk_gamever (valid course has 32)
    struct.pack_into('<I', data, 0x18, 65)   # unk_management_flags (valid course has 65)
    struct.pack_into('<i', data, 0x1C, 0)    # clear_attempts
    struct.pack_into('<I', data, 0x20, 0xFFFFFFFF)  # clear_time (demo has -1)
    struct.pack_into('<I', data, 0x24, 0xB5D5B58F)  # unk_creation_id (copied from valid course)
    struct.pack_into('<q', data, 0x28, 0)    # unk_upload_id
    struct.pack_into('<i', data, 0x30, 0)    # game_version (demo has 0)
    
    # Byte before style (0xF0) - demo has 0xFF
    data[0xF0] = 0xFF
    
    # Style code at 0xF1 (2 bytes as little-endian)
    style_code = STYLE_CODES.get(style_id, b'M1')
    data[0xF1:0xF3] = style_code
    
    # Course name at 0xF4 (UTF-16LE, max 66 bytes = 33 chars)
    name = f"Test {['SMB1','SMB3','SMW','NSMBU','3DW'][style_id]}"
    name_bytes = name.encode('utf-16-le')[:64]
    data[0xF4:0xF4+len(name_bytes)] = name_bytes
    
    # === Area 1 (Overworld) at 0x200 ===
    # Full area header per bcd-format.ksy
    area = 0x200
    data[area + 0x00] = theme_id     # theme
    data[area + 0x01] = 0            # autoscroll_type
    data[area + 0x02] = 0            # boundary_type
    data[area + 0x03] = 0            # orientation (horizontal)
    data[area + 0x04] = 0            # liquid_end_height
    data[area + 0x05] = 0            # liquid_mode
    data[area + 0x06] = 0            # liquid_speed
    data[area + 0x07] = 0            # liquid_start_height
    
    # Boundaries (in pixels, not deci-pixels)
    struct.pack_into('<i', data, area + 0x08, 35 * 16)   # boundary_right (560 pixels = 35 tiles)
    struct.pack_into('<i', data, area + 0x0C, 27 * 16)   # boundary_top (432 pixels = 27 tiles)
    struct.pack_into('<i', data, area + 0x10, 0)         # boundary_left
    struct.pack_into('<i', data, area + 0x14, 0)         # boundary_bottom
    struct.pack_into('<i', data, area + 0x18, 0)         # unk_flag
    
    # === Ground tiles at area + 0x247A4 ===
    # Place ground ONLY in safe zone: x >= 7 AND x <= goal_x - 4
    # This connects start area to goal area so Mario can walk straight through
    ground_base = area + 0x247A4
    ground_count = 0
    
    # Get goal_x from header (we set it to 11)
    goal_x = struct.unpack_from('<h', data, 0x02)[0]
    
    # Safe zone: start at x=7 (after 7-tile start area), end at goal_x - 7
    # Using -7 instead of -4 leaves cleaner visual gap before goal
    safe_start = 7
    safe_end = goal_x - 7  # Leave extra visual space before goal area
    ground_y = 4  # Same level as start area ground (start_y - 1)
    
    GROUND_FILL = 0x3E  # Solid ground tile
    
    if safe_end >= safe_start:
        for x in range(safe_start, safe_end + 1):
            offset = ground_base + ground_count * 4
            data[offset + 0] = x
            data[offset + 1] = ground_y
            struct.pack_into('<H', data, offset + 2, GROUND_FILL)
            ground_count += 1
    
    # Set counts in area header
    struct.pack_into('<i', data, area + 0x1C, 0)  # object_count (no objects - goal auto-generated)
    struct.pack_into('<i', data, area + 0x3C, ground_count)  # ground_count
    struct.pack_into('<i', data, area + 0x20, 0)  # sound_effect_count
    struct.pack_into('<i', data, area + 0x24, 0)  # snake_block_count
    struct.pack_into('<i', data, area + 0x28, 0)  # clear_pipe_count
    struct.pack_into('<i', data, area + 0x2C, 0)  # piranha_creeper_count
    struct.pack_into('<i', data, area + 0x30, 0)  # exclamation_mark_block_count
    struct.pack_into('<i', data, area + 0x34, 0)  # track_block_count
    struct.pack_into('<i', data, area + 0x38, 0)  # unk1
    # ground_count already set above after placing tiles
    struct.pack_into('<i', data, area + 0x40, 0)  # track_count
    struct.pack_into('<i', data, area + 0x44, 0)  # ice_count
    
    # === Objects at area+0x48 ===
    # DO NOT place goal object - it's auto-generated from header goal_x/goal_y
    # If objects are needed: place in safe zone (x >= 7 AND x <= goal_x - 4)
    # and outside spawn exclusion (3 tiles from player spawn at x=0)
    
    # === Subworld (Area 1) at 0x2E0E0 ===
    # Must be initialized exactly like original, or causes glitched tiles
    area1 = 0x2E0E0
    data[area1 + 0x00] = theme_id  # Theme (same as main)
    data[area1 + 0x01] = 0         # Autoscroll
    data[area1 + 0x02] = 1         # Boundary type
    data[area1 + 0x03] = 0         # Orientation
    data[area1 + 0x04] = 1         # liquid_end_height
    data[area1 + 0x05] = 0         # liquid_mode
    data[area1 + 0x06] = 0         # liquid_speed
    data[area1 + 0x07] = 1         # liquid_start_height (CRITICAL - was missing!)
    struct.pack_into('<i', data, area1 + 0x08, 84 * 16)   # Width: 1344 (84 tiles)
    struct.pack_into('<i', data, area1 + 0x0C, 27 * 16)   # Height: 432 (27 tiles)
    
    return bytes(data)


def encrypt_course(data: bytes) -> bytes:
    """Encrypt course data and create full BCD file."""
    from Crypto.Hash import CMAC
    
    # Generate random state (16 bytes)
    import random
    random.seed()
    rand_state = bytes([random.randint(0, 255) for _ in range(16)])
    
    # Parse random state as 4 uint32s
    s0 = struct.unpack_from('<I', rand_state, 0)[0]
    s1 = struct.unpack_from('<I', rand_state, 4)[0]
    s2 = struct.unpack_from('<I', rand_state, 8)[0]
    s3 = struct.unpack_from('<I', rand_state, 12)[0]
    
    # Derive FIRST key for encryption
    rand = SeadRandom(s0, s1, s2, s3)
    key1 = create_key(rand, COURSE_KEY_TABLE, 16)
    
    # Generate random IV
    iv = bytes([random.randint(0, 255) for _ in range(16)])
    
    # Pad data to 0x5BFC0 if needed
    if len(data) < 0x5BFC0:
        data = data + bytes(0x5BFC0 - len(data))
    
    # Encrypt with first key
    aes = AES.new(key1, AES.MODE_CBC, iv)
    encrypted = aes.encrypt(data)
    
    # Derive SECOND key for CMAC (continue PRNG state)
    key2 = create_key(rand, COURSE_KEY_TABLE, 16)
    
    # Compute CMAC of decrypted data using second key
    mac = CMAC.new(key2, ciphermod=AES)
    mac.update(data)
    cmac = mac.digest()
    
    # Calculate CRC of decrypted data
    crc = zlib.crc32(data) & 0xFFFFFFFF
    
    # Build header (0x10 bytes)
    header = bytearray(0x10)
    struct.pack_into('<I', header, 0x00, 1)           # version
    struct.pack_into('<I', header, 0x04, 0x00010010)  # flags/size
    struct.pack_into('<I', header, 0x08, crc)         # CRC32
    header[0x0C:0x10] = b'SCDL'                       # magic
    
    # Build crypto config (0x30 bytes): IV + rand_state + CMAC
    crypto_config = bytearray(0x30)
    crypto_config[0x00:0x10] = iv
    crypto_config[0x10:0x20] = rand_state
    crypto_config[0x20:0x30] = cmac
    
    return bytes(header) + encrypted + bytes(crypto_config)


def get_eden_save_path():
    """Get Eden's SMM2 save path."""
    base = Path("/mnt/c/Users/nico/AppData/Roaming/eden/nand/user/save")
    # Find the save directory with course files
    for p in base.rglob("course_data_000.bcd"):
        return p.parent
    # Return expected path if not found
    return base / "0000000000000000" / "D080642459E491EFC36078212D94171B" / "01009B90006DC000"


def main():
    parser = argparse.ArgumentParser(description='Generate SMM2 test level')
    parser.add_argument('--style', type=str, default='SMB1',
                        choices=list(STYLES.keys()), help='Game style')
    parser.add_argument('--theme', type=str, default='Ground',
                        choices=list(THEMES.keys()), help='Course theme')
    parser.add_argument('--slot', type=int, default=0, choices=[0, 1, 2],
                        help='Save slot (0-2)')
    parser.add_argument('--dry-run', action='store_true',
                        help="Don't write, just show what would be done")
    args = parser.parse_args()
    
    style_id = STYLES[args.style]
    theme_id = THEMES[args.theme]
    
    print(f"Generating {args.style} {args.theme} level for slot {args.slot}")
    
    # Create course data
    course_data = create_minimal_course(style_id, theme_id)
    print(f"  Course data: {len(course_data)} bytes")
    
    # Encrypt
    bcd = encrypt_course(course_data)
    print(f"  Encrypted BCD: {len(bcd)} bytes")
    
    # Find save path
    save_path = get_eden_save_path()
    out_file = save_path / f"course_data_{args.slot:03d}.bcd"
    
    print(f"  Target: {out_file}")
    
    if args.dry_run:
        print("  (dry run - not writing)")
        return 0
    
    # Backup existing file
    if out_file.exists():
        backup = out_file.with_suffix('.bcd.bak')
        print(f"  Backing up to {backup.name}")
        import shutil
        shutil.copy(out_file, backup)
    
    # Write new file
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_bytes(bcd)
    print(f"  Written!")
    
    return 0


if __name__ == '__main__':
    exit(main())
