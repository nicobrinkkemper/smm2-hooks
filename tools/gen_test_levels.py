#!/usr/bin/env python3
"""gen_test_levels.py — Generate test levels for physics validation.

Replaces demo level slots (0-9) with test levels for specific scenarios.
Each level is designed to test different physics mechanics.

Usage:
    python3 gen_test_levels.py              # Generate all test levels
    python3 gen_test_levels.py --dry-run    # Preview without writing
    python3 gen_test_levels.py --list       # List available test levels

Test Level Slots:
    0: Flat ground (basic walk/run)
    1: Jump platforms (vertical movement)
    2: Slope course (slope physics)
    3: Ice terrain (ice friction)
    4: Underwater (water physics)
    5: 3DW flat (3D World style)
    6: SMB3 flat (SMB3 style)
    7: SMW flat (Super Mario World style)
    8: NSMBU flat (New Super Mario Bros U style)
    9: Empty (minimal for custom tests)
"""

import struct
import zlib
import os
import argparse
from pathlib import Path
from typing import List, Tuple
from Crypto.Cipher import AES
from Crypto.Hash import CMAC
import random

# ═══════════════════════════════════════════════════════════════════════════
# Constants (from gen_level.py)
# ═══════════════════════════════════════════════════════════════════════════

STYLES = {'SMB1': 0, 'SMB3': 1, 'SMW': 2, 'NSMBU': 3, '3DW': 4}
STYLE_CODES = {0: b'M1', 1: b'M3', 2: b'MW', 3: b'WU', 4: b'3W'}
THEMES = {
    'Ground': 0, 'Underground': 1, 'Castle': 2, 'Airship': 3, 'Underwater': 4,
    'Ghost': 5, 'Snow': 6, 'Desert': 7, 'Sky': 8, 'Forest': 9
}

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

# Tile IDs (from level analysis)
# 0x003E appears to be generic ground fill
GROUND_FILL = 0x3E
GROUND_LEFT = 0x19
GROUND_MID = 0x1a
GROUND_RIGHT = 0x1b

# Connected ground block tile IDs (proper visual connection)
# Surface row (top of ground)
GROUND_SURFACE_MID = 59      # 0x3B - middle surface
GROUND_SURFACE_RIGHT = 60    # 0x3C - right edge surface
GROUND_SURFACE_PRE_GOAL = 9  # special tile before goal area
# Fill rows (below surface)
GROUND_FILL_MID = 62         # 0x3E - middle fill
# Right edge fill (varies by row)
GROUND_FILL_RIGHT_Y3 = 68    # right edge at y=3
GROUND_FILL_RIGHT_Y2 = 12    # right edge at y=2
GROUND_FILL_RIGHT_Y0 = 13    # right edge at y=0
# NOTE: No left edge tiles needed - start area auto-connects!

# Slope object IDs (slopes are objects, not ground tiles)
OBJ_SLIGHT_SLOPE = 87
OBJ_STEEP_SLOPE = 88
ICE_LEFT = 0x4D
ICE_MID = 0x4E
ICE_RIGHT = 0x4F

# Object IDs (from bcd-format.ksy)
OBJ_GOAL = 27
OBJ_GOOMBA = 0
OBJ_BLOCK = 4
OBJ_QUESTION = 5
OBJ_HARD_BLOCK = 6
OBJ_COIN = 8
OBJ_MUSHROOM = 20
OBJ_SLOPE_GENTLE = 44  # Gentle slope
OBJ_SLOPE_STEEP = 45   # Steep slope

# Unit conversions
TILE = 160  # deci-pixels per tile

# ═══════════════════════════════════════════════════════════════════════════
# Crypto
# ═══════════════════════════════════════════════════════════════════════════

class SeadRandom:
    def __init__(self, s0, s1, s2, s3):
        self.state = [s0, s1, s2, s3]
    
    def u32(self):
        s = self.state
        temp = (s[0] ^ ((s[0] << 11) & 0xFFFFFFFF)) & 0xFFFFFFFF
        temp ^= temp >> 8
        temp ^= s[3] ^ (s[3] >> 19)
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


def encrypt_course(data: bytes) -> bytes:
    """Encrypt course data and create full BCD file."""
    rand_state = bytes([random.randint(0, 255) for _ in range(16)])
    s0, s1, s2, s3 = struct.unpack('<4I', rand_state)
    
    rand = SeadRandom(s0, s1, s2, s3)
    key1 = create_key(rand, COURSE_KEY_TABLE, 16)
    iv = bytes([random.randint(0, 255) for _ in range(16)])
    
    if len(data) < 0x5BFC0:
        data = data + bytes(0x5BFC0 - len(data))
    
    aes = AES.new(key1, AES.MODE_CBC, iv)
    encrypted = aes.encrypt(data)
    
    key2 = create_key(rand, COURSE_KEY_TABLE, 16)
    mac = CMAC.new(key2, ciphermod=AES)
    mac.update(data)
    cmac = mac.digest()
    
    crc = zlib.crc32(data) & 0xFFFFFFFF
    
    header = bytearray(0x10)
    struct.pack_into('<I', header, 0x00, 1)
    struct.pack_into('<I', header, 0x04, 0x00010010)
    struct.pack_into('<I', header, 0x08, crc)
    header[0x0C:0x10] = b'SCDL'
    
    crypto_config = bytearray(0x30)
    crypto_config[0x00:0x10] = iv
    crypto_config[0x10:0x20] = rand_state
    crypto_config[0x20:0x30] = cmac
    
    return bytes(header) + encrypted + bytes(crypto_config)

# ═══════════════════════════════════════════════════════════════════════════
# Level Builder
# ═══════════════════════════════════════════════════════════════════════════

class LevelBuilder:
    """Helper to build course data."""
    
    def __init__(self, name: str, style: str = 'SMB1', theme: str = 'Ground'):
        self.data = bytearray(0x5BFC0)
        self.name = name
        self.style_id = STYLES[style]
        self.theme_id = THEMES[theme]
        self.objects: List[dict] = []
        self.ground_tiles: List[Tuple[int, int, int]] = []
        self.start_y = 5  # tiles
        self.goal_x = 25  # tiles
        self.goal_y = None  # auto-calculated if None
        
    def add_ground(self, x_start: int, x_end: int, y: int):
        """Add ground tiles from x_start to x_end at height y."""
        for x in range(x_start, x_end + 1):
            if x == x_start:
                tile_id = GROUND_LEFT
            elif x == x_end:
                tile_id = GROUND_RIGHT
            else:
                tile_id = GROUND_MID
            self.ground_tiles.append((x, y, tile_id))
    
    def add_ground_fill(self, x_start: int, x_end: int, y: int):
        """Add solid ground fill (tile 0x3E) from x_start to x_end at height y."""
        for x in range(x_start, x_end + 1):
            self.ground_tiles.append((x, y, GROUND_FILL))
    
    def add_ground_block(self, x_start: int, x_end: int, y_surface: int, height: int = 5):
        """Add a connected ground block with proper tile visuals.
        
        Creates a 2D rectangle of tiles. NO left edge needed (start area auto-connects).
        Uses different tile IDs for surface vs fill rows, with special right-edge tiles.
        
        Args:
            x_start: Left edge X coordinate (no special tile - auto-connects to start)
            x_end: Right edge X coordinate
            y_surface: Top surface Y coordinate (player walks on this)
            height: How many rows tall (default 5 = surface + 4 fill rows)
        """
        # Surface row (top)
        for x in range(x_start, x_end + 1):
            if x == x_end:
                tile_id = GROUND_SURFACE_RIGHT
            elif x == x_end - 2:
                tile_id = GROUND_SURFACE_PRE_GOAL  # Special connector before goal
            else:
                tile_id = GROUND_SURFACE_MID
            self.ground_tiles.append((x, y_surface, tile_id))
        
        # Fill rows (below surface)
        for y in range(y_surface - 1, y_surface - height, -1):
            if y < 0:
                break
            for x in range(x_start, x_end + 1):
                if x == x_end:
                    # Right edge varies by row
                    if y == y_surface - 1:  # y=3 when surface=4
                        tile_id = GROUND_FILL_RIGHT_Y3
                    elif y == y_surface - 2:  # y=2
                        tile_id = GROUND_FILL_RIGHT_Y2
                    elif y == 0:
                        tile_id = GROUND_FILL_RIGHT_Y0
                    else:
                        tile_id = GROUND_FILL_MID
                else:
                    tile_id = GROUND_FILL_MID
                self.ground_tiles.append((x, y, tile_id))
    
    def add_ice(self, x_start: int, x_end: int, y: int):
        """Add ice tiles from x_start to x_end."""
        for x in range(x_start, x_end + 1):
            if x == x_start:
                tile_id = ICE_LEFT
            elif x == x_end:
                tile_id = ICE_RIGHT
            else:
                tile_id = ICE_MID
            self.ground_tiles.append((x, y, tile_id))
    
    def add_platform(self, x: int, y: int, width: int = 3):
        """Add a platform (hard blocks)."""
        for dx in range(width):
            self.objects.append({
                'id': OBJ_HARD_BLOCK,
                'x': x + dx,
                'y': y,
                'width': 1,
                'height': 1,
            })
    
    def add_slope(self, x: int, y: int, width: int, height: int, steep: bool = False):
        """Add a slope object.
        
        Slopes are objects (not ground tiles) with IDs 87 (slight) or 88 (steep).
        Coordinates are in tiles, converted to 160-unit sub-pixels internally.
        """
        self.objects.append({
            'id': OBJ_STEEP_SLOPE if steep else OBJ_SLIGHT_SLOPE,
            'x': x,
            'y': y,
            'width': width,
            'height': height,
        })
    
    def add_coin(self, x: int, y: int):
        """Add a coin."""
        self.objects.append({
            'id': OBJ_COIN,
            'x': x,
            'y': y,
            'width': 1,
            'height': 1,
        })
    
    def add_mushroom(self, x: int, y: int):
        """Add a mushroom in a ? block."""
        self.objects.append({
            'id': OBJ_QUESTION,
            'x': x,
            'y': y,
            'width': 1,
            'height': 1,
            'contents': OBJ_MUSHROOM,
        })
    
    def build(self) -> bytes:
        """Build the course data."""
        data = self.data
        
        # Header
        data[0x00] = self.start_y
        data[0x01] = self.goal_y if self.goal_y else self.start_y
        struct.pack_into('<h', data, 0x02, self.goal_x)
        struct.pack_into('<h', data, 0x04, 300)  # time
        struct.pack_into('<h', data, 0x08, 2026)
        data[0x0A] = 2
        data[0x0B] = 19
        data[0x0C] = 12
        struct.pack_into('<I', data, 0x14, 32)
        struct.pack_into('<I', data, 0x18, 65)
        struct.pack_into('<I', data, 0x20, 0xFFFFFFFF)
        struct.pack_into('<I', data, 0x24, 0xB5D5B58F)
        data[0xF0] = 0xFF
        data[0xF1:0xF3] = STYLE_CODES[self.style_id]
        name_bytes = self.name.encode('utf-16-le')[:64]
        data[0xF4:0xF4+len(name_bytes)] = name_bytes
        
        # Area header
        area = 0x200
        data[area + 0x00] = self.theme_id
        struct.pack_into('<i', data, area + 0x08, 35 * 16)
        struct.pack_into('<i', data, area + 0x0C, 27 * 16)
        
        # NOTE: Do NOT add goal object - game auto-generates from header goal_x/goal_y
        
        # Write objects
        obj_base = area + 0x48
        for i, obj in enumerate(self.objects):
            off = obj_base + i * 0x20
            struct.pack_into('<i', data, off + 0x00, obj['x'] * TILE)
            struct.pack_into('<i', data, off + 0x04, obj['y'] * TILE)
            data[off + 0x0A] = obj.get('width', 1)
            data[off + 0x0B] = obj.get('height', 1)
            struct.pack_into('<i', data, off + 0x0C, 0x06000040)
            struct.pack_into('<i', data, off + 0x10, 0x06000040)
            struct.pack_into('<h', data, off + 0x18, obj['id'])
            struct.pack_into('<h', data, off + 0x1A, obj.get('contents', -1))
            struct.pack_into('<h', data, off + 0x1C, -1)
            struct.pack_into('<h', data, off + 0x1E, -1)
        
        # Write ground tiles
        ground_base = area + 0x247A4
        for i, (x, y, tile_id) in enumerate(self.ground_tiles):
            off = ground_base + i * 4
            data[off + 0] = x
            data[off + 1] = y
            struct.pack_into('<H', data, off + 2, tile_id)
        
        # Set counts
        struct.pack_into('<i', data, area + 0x1C, len(self.objects))
        struct.pack_into('<i', data, area + 0x3C, len(self.ground_tiles))
        
        # Initialize subworld (Area 1) header
        area1 = 0x2E0E0
        data[area1 + 0x00] = self.theme_id  # Same theme as main
        data[area1 + 0x01] = 0  # Autoscroll
        data[area1 + 0x02] = 1  # Boundary flags (from original)
        data[area1 + 0x03] = 0  # Orientation
        data[area1 + 0x04] = 1  # liquid_end_height
        data[area1 + 0x05] = 0  # liquid_mode
        data[area1 + 0x06] = 0  # liquid_speed
        data[area1 + 0x07] = 1  # liquid_start_height (CRITICAL!)
        struct.pack_into('<i', data, area1 + 0x08, 84 * 16)  # Width: 1344 (84 tiles)
        struct.pack_into('<i', data, area1 + 0x0C, 27 * 16)  # Height: 432 (27 tiles)
        # Object and ground counts stay 0 for empty subworld
        
        return bytes(data)


# ═══════════════════════════════════════════════════════════════════════════
# Test Level Definitions
# ═══════════════════════════════════════════════════════════════════════════

TEST_LEVELS = {}

def test_level(slot: int, name: str):
    """Decorator to register a test level."""
    def decorator(func):
        TEST_LEVELS[slot] = (name, func)
        return func
    return decorator


@test_level(0, "Flat Ground (SMB1)")
def level_flat_ground() -> LevelBuilder:
    """Basic flat ground for walk/run testing.
    
    NOTE: Start area is 7 tiles wide (x=0 to x=6).
    Goal area is ~4 tiles wide before goal_x.
    Safe zone: x >= 7 and x <= goal_x - 4
    Ground must extend to goal area for valid path!
    """
    b = LevelBuilder("Flat Ground", "SMB1", "Ground")
    # Ground from x=7 to x=23 (goal_x=27, so goal area starts ~x=23)
    # Connected ground block with proper surface + fill tiles
    b.add_ground_block(7, 23, y_surface=4, height=5)
    b.goal_x = 27
    b.goal_y = 5
    return b


@test_level(1, "Jump Platforms")
def level_jump_platforms() -> LevelBuilder:
    """Platforms at different heights for jump testing."""
    b = LevelBuilder("Jump Test", "SMB1", "Ground")
    b.add_ground(5, 10, 4)     # Start ground (safe zone)
    b.add_platform(12, 6, 3)   # Low platform
    b.add_platform(16, 8, 3)   # Medium platform
    b.add_platform(20, 10, 3)  # High platform
    # No end ground - goal area is auto-generated
    b.goal_x = 27
    b.goal_y = 5
    return b


@test_level(2, "Slope Course")
def level_slopes() -> LevelBuilder:
    """Slope physics testing using actual slope objects."""
    b = LevelBuilder("Slope Test", "SMB1", "Ground")
    # Start flat ground
    b.add_ground_block(7, 10, y_surface=4, height=5)
    # Steep slope going up (id=88)
    b.add_slope(8, 4, width=5, height=4, steep=True)
    # Slight slope going up (id=87) 
    b.add_slope(13, 7, width=8, height=4, steep=False)
    # End ground near goal
    b.add_ground(21, 23, 10)
    b.start_y = 5
    b.goal_x = 27
    b.goal_y = 10
    return b


@test_level(3, "Ice Terrain")
def level_ice() -> LevelBuilder:
    """Ice surface for friction testing."""
    b = LevelBuilder("Ice Test", "SMB1", "Snow")
    b.add_ground(5, 10, 4)  # Normal ground start (safe zone)
    b.add_ice(11, 20, 4)    # Ice section
    # No end ground - goal area is auto-generated
    b.goal_x = 27
    b.goal_y = 5
    return b


@test_level(4, "Underwater")
def level_underwater() -> LevelBuilder:
    """Underwater level for water physics."""
    b = LevelBuilder("Water Test", "SMB1", "Underwater")
    b.add_ground(5, 23, 2)  # Low floor (safe zone only)
    b.start_y = 10
    b.goal_x = 27
    b.goal_y = 3
    return b


@test_level(5, "Flat Ground (3DW)")
def level_3dw_flat() -> LevelBuilder:
    """3D World style flat ground."""
    b = LevelBuilder("3DW Flat", "3DW", "Ground")
    b.add_ground_block(7, 23, y_surface=4, height=5)
    b.goal_x = 27
    b.goal_y = 5
    return b


@test_level(6, "Flat Ground (SMB3)")
def level_smb3_flat() -> LevelBuilder:
    """SMB3 style flat ground."""
    b = LevelBuilder("SMB3 Flat", "SMB3", "Ground")
    b.add_ground_block(7, 23, y_surface=4, height=5)
    b.goal_x = 27
    b.goal_y = 5
    return b


@test_level(7, "Flat Ground (SMW)")
def level_smw_flat() -> LevelBuilder:
    """Super Mario World style flat ground."""
    b = LevelBuilder("SMW Flat", "SMW", "Ground")
    b.add_ground_block(7, 23, y_surface=4, height=5)
    b.goal_x = 27
    b.goal_y = 5
    return b


@test_level(8, "Flat Ground (NSMBU)")
def level_nsmbu_flat() -> LevelBuilder:
    """New Super Mario Bros U style flat ground."""
    b = LevelBuilder("NSMBU Flat", "NSMBU", "Ground")
    b.add_ground_block(7, 23, y_surface=4, height=5)
    b.goal_x = 27
    b.goal_y = 5
    return b


@test_level(9, "Empty")
def level_empty() -> LevelBuilder:
    """Minimal empty level for custom tests - NO ground placed."""
    b = LevelBuilder("Empty", "SMB1", "Ground")
    # Don't place any ground - start/goal areas are auto-generated
    b.start_y = 5
    b.goal_x = 27
    b.goal_y = 5
    return b


# ═══════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════

def get_save_paths():
    """Get Ryujinx and Eden save paths."""
    paths = {}
    
    # Ryujinx
    ryujinx = Path("/mnt/c/Users/nico/AppData/Roaming/Ryujinx/bis/user/save/0000000000000001/0")
    if ryujinx.exists():
        paths['ryujinx'] = ryujinx
    
    # Eden
    eden_base = Path("/mnt/c/Users/nico/AppData/Roaming/eden/nand/user/save")
    for p in eden_base.rglob("course_data_000.bcd"):
        paths['eden'] = p.parent
        break
    
    return paths


def main():
    parser = argparse.ArgumentParser(description='Generate SMM2 test levels')
    parser.add_argument('--dry-run', action='store_true', help="Preview only")
    parser.add_argument('--list', action='store_true', help="List test levels")
    parser.add_argument('--slot', type=int, help="Generate only this slot")
    parser.add_argument('--target', choices=['ryujinx', 'eden', 'both'], 
                        default='both', help="Target emulator")
    args = parser.parse_args()
    
    if args.list:
        print("Available test levels:")
        for slot, (name, _) in sorted(TEST_LEVELS.items()):
            print(f"  {slot}: {name}")
        return 0
    
    save_paths = get_save_paths()
    if not save_paths:
        print("Error: No save paths found!")
        return 1
    
    print("Target save directories:")
    for emu, path in save_paths.items():
        print(f"  {emu}: {path}")
    
    targets = []
    if args.target == 'both':
        targets = list(save_paths.keys())
    elif args.target in save_paths:
        targets = [args.target]
    else:
        print(f"Error: {args.target} save not found")
        return 1
    
    # Generate levels
    slots = [args.slot] if args.slot is not None else sorted(TEST_LEVELS.keys())
    
    for slot in slots:
        if slot not in TEST_LEVELS:
            print(f"Slot {slot}: not defined, skipping")
            continue
        
        name, builder_func = TEST_LEVELS[slot]
        print(f"\nSlot {slot}: {name}")
        
        builder = builder_func()
        course_data = builder.build()
        bcd = encrypt_course(course_data)
        
        for emu in targets:
            path = save_paths[emu]
            out_file = path / f"course_data_{slot:03d}.bcd"
            
            if args.dry_run:
                print(f"  [{emu}] Would write {out_file.name}")
            else:
                # Backup
                if out_file.exists():
                    backup = out_file.with_suffix('.bcd.orig')
                    if not backup.exists():
                        import shutil
                        shutil.copy(out_file, backup)
                
                out_file.write_bytes(bcd)
                print(f"  [{emu}] Written {out_file.name}")
    
    if not args.dry_run:
        print("\n✓ Test levels generated!")
        print("  Load slot 0-9 in Coursebot to access them.")
    
    return 0


if __name__ == '__main__':
    exit(main())
