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
OBJ_NOTE_BLOCK = 23    # Note block (music block is the same id with a flag)

# Object flags (community BCD sheet, "Flags for Objects"). 0x40 and 0x6000000
# are set on every object; the generator's default 0x06000040 is exactly that.
FLAG_WINGS = 0x2
FLAG_ON_TRACK = 0x400
FLAG_TRACK_LEFT = 0x100000
FLAG_TRACK_VERTICAL = 0x200000

# Track record shapes ("Type - Shape" tab). Verified against an editor-saved
# course: the type byte is the shape alone; the trailing u16 pair encodes the
# two end words whose meaning is not decoded: the editor writes (0x90, 0x70) for a
# lone horizontal piece and (0x90, 0x70) then (0x71, 0x104) for a two-piece chain,
# and lone pieces carry 0x0104 as well. Copy the editor's values for the shape you need.
TRACK_SHAPE_HORIZONTAL = 0
TRACK_SHAPE_VERTICAL = 1
TRACK_SHAPE_DESC_DIAGONAL = 2
TRACK_SHAPE_ASC_DIAGONAL = 3
TRACK_SHAPE_CURVE_BL = 4
TRACK_SHAPE_CURVE_TR = 5
TRACK_SHAPE_CURVE_TL = 6
TRACK_SHAPE_CURVE_BR = 7
AREA_WIDTH = 35   # tiles; goal_x in the header is derived from it (Coursebot deletes a course whose goal sits inside the start area)
TRACK_END_FREE_H = (0x0090, 0x0070)   # lone horizontal piece, as the editor writes it; a chain is (0x90,0x70) then (0x71,0x104)

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
        self.width = AREA_WIDTH   # tiles; goal_x and the area size derive from it
        self.ground_tiles: List[Tuple[int, int, int]] = []
        self.start_y = 5  # tiles
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
        
        Uses style-specific tile patterns:
        - 2D styles (SMB1/SMB3/SMW/NSMBU): uniform fill
        - 3DW: detailed edges with texture variation
        """
        is_3dw = (self.style_id == 4)  # 3DW style
        
        # Surface row (top)
        for x in range(x_start, x_end + 1):
            if x == x_start:
                # Left edge: 3DW uses 10, 2D styles use 59 (no special left)
                tile_id = 10 if is_3dw else GROUND_SURFACE_MID
            elif x == x_end:
                tile_id = GROUND_SURFACE_RIGHT  # 60
            elif x == x_end - 1 and is_3dw:
                tile_id = 10  # 3DW has special pre-right tile
            else:
                tile_id = GROUND_SURFACE_MID  # 59
            self.ground_tiles.append((x, y_surface, tile_id))
        
        # Fill rows (below surface)
        import random
        random.seed(42)  # Deterministic but varied
        
        for y in range(y_surface - 1, y_surface - height, -1):
            if y < 0:
                break
            for x in range(x_start, x_end + 1):
                is_left = (x == x_start)
                is_right = (x == x_end)
                is_bottom = (y == 0)
                
                if is_right:
                    # Right edge
                    if y == y_surface - 1:
                        tile_id = GROUND_FILL_RIGHT_Y3  # 68
                    else:
                        tile_id = GROUND_FILL_MID  # 62
                elif is_3dw:
                    # 3DW: scatter variation tiles (12, 13)
                    if is_left and is_bottom:
                        tile_id = 12  # bottom-left corner
                    elif is_bottom and random.random() < 0.3:
                        tile_id = 12  # scattered on bottom
                    elif is_left and random.random() < 0.5:
                        tile_id = 12  # scattered on left edge
                    elif random.random() < 0.25:
                        tile_id = 12 if random.random() < 0.8 else 13
                    else:
                        tile_id = GROUND_FILL_MID  # 62
                else:
                    # 2D styles: uniform fill with edge specials
                    if is_right:
                        if y == y_surface - 2:
                            tile_id = GROUND_FILL_RIGHT_Y2  # 12
                        elif y == 0:
                            tile_id = GROUND_FILL_RIGHT_Y0  # 13
                        else:
                            tile_id = GROUND_FILL_MID
                    else:
                        tile_id = GROUND_FILL_MID  # 62
                
                self.ground_tiles.append((x, y, tile_id))
    
    def add_ice(self, x_start: int, x_end: int, y: int):
        """Add ice block objects from x_start to x_end.
        
        Ice terrain uses ice_block objects (id=63), NOT ground tiles!
        Ice blocks need +80 unit offset (half-tile) to align with grid.
        """
        OBJ_ICE_BLOCK = 63
        for x in range(x_start, x_end + 1):
            self.objects.append({
                'id': OBJ_ICE_BLOCK,
                'x': x,
                'y': y,
                'width': 1,
                'height': 1,
                '_half_tile_offset': True,  # Ice blocks need half-tile offset like slopes
            })
    
    def add_platform(self, x: int, y: int, width: int = 3):
        """Add a platform (hard blocks).
        
        Hard blocks need +80 unit offset (half-tile) to align with grid.
        """
        for dx in range(width):
            self.objects.append({
                'id': OBJ_HARD_BLOCK,
                'x': x + dx,
                'y': y,
                'width': 1,
                'height': 1,
                '_half_tile_offset': True,
            })
    
    def add_slope(self, x: int, y: int, width: int, height: int, steep: bool = False):
        """Add a slope object.
        
        Slopes are objects (not ground tiles) with IDs 87 (slight) or 88 (steep).
        Coordinates are in tiles. Slopes need +0.5 tile offset (placed at tile centers).
        """
        self.objects.append({
            'id': OBJ_STEEP_SLOPE if steep else OBJ_SLIGHT_SLOPE,
            'x': x,
            'y': y,
            'width': width,
            'height': height,
            '_half_tile_offset': True,  # Flag for build() to add +80 units
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
    
    def add_track(self, x: int, y: int, shape: int, ends: tuple = TRACK_END_FREE_H,
                  has_object: bool = False, lid: int = None) -> int:
        """Add one 12-byte track record (area +0x28624, count at +0x40) and
        return its 0-based index (what an object's link id refers to).

        Layout as the editor writes it: unk u16 = 0, flags u8 (1 = an object
        rides this piece), x u8, y u8, shape u8, own id u16 (sequential from
        1), then the two end words.
        """
        if not hasattr(self, 'tracks'):
            self.tracks = []
        self.tracks.append({'x': x, 'y': y, 'type': shape,
                            'lid': lid if lid is not None else len(self.tracks) + 1,
                            'has_object': has_object, 'tail': ends})
        return len(self.tracks) - 1

    def add_note_block_on_track(self, track_index: int, wings: bool = False,
                                travel_left: bool = True, vertical: bool = False):
        """A note block riding the track record with that 0-based index.

        A track record's (x, y) is the bottom-left of a 3x3 tile box and the
        rail runs through the box centre, so the block starts at
        (x + 1.5, y + 1.5); the editor writes exactly that for a block placed
        on a rail (course 'track': record (11, 6), block at (12.5, 7.5)).
        """
        tr = self.tracks[track_index]
        flags = 0x06000040 | FLAG_ON_TRACK
        if wings: flags |= FLAG_WINGS
        if travel_left: flags |= FLAG_TRACK_LEFT
        if vertical: flags |= FLAG_TRACK_VERTICAL
        self.objects.append({'id': OBJ_NOTE_BLOCK, 'x': tr['x'] + 1, 'y': tr['y'] + 1,
                             'flags': flags, 'lid': track_index, '_half_tile_offset': True})
        tr['has_object'] = True

    def add_note_block(self, x: int, y: int, wings: bool = False):
        """A free-standing note block (id 23), bottom-left tile at (x, y)."""
        flags = 0x06000040 | (FLAG_WINGS if wings else 0)
        self.objects.append({'id': OBJ_NOTE_BLOCK, 'x': x, 'y': y, 'flags': flags})

    def add_actor(self, actor_id: int, x, y, flags: int = 0x06000040,
                  lid: int = -1, half: bool = True):
        """Any actor record verbatim: position in tiles (half=True adds the
        usual +0.5 centre offset), flags and track link id as given."""
        self.objects.append({'id': actor_id, 'x': x, 'y': y, 'flags': flags,
                             'lid': lid, '_half_tile_offset': half})

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
        struct.pack_into('<h', data, 0x02, int((self.width - 9.5) * 10))  # tenths of a tile; the pole stands 9.5 tiles from the right edge
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
        struct.pack_into('<i', data, area + 0x08, self.width * 16)
        struct.pack_into('<i', data, area + 0x0C, 27 * 16)
        
        # NOTE: Do NOT add goal object - game auto-generates from header goal_x/goal_y
        
        # Write objects
        obj_base = area + 0x48
        for i, obj in enumerate(self.objects):
            off = obj_base + i * 0x20
            # Slopes need +0.5 tile offset (80 units) to align properly
            offset = 80 if obj.get('_half_tile_offset') else 0
            struct.pack_into('<i', data, off + 0x00, obj['x'] * TILE + offset)
            struct.pack_into('<i', data, off + 0x04, obj['y'] * TILE + offset)
            data[off + 0x0A] = obj.get('width', 1)
            data[off + 0x0B] = obj.get('height', 1)
            struct.pack_into('<I', data, off + 0x0C, obj.get('flags', 0x06000040))
            struct.pack_into('<I', data, off + 0x10, 0x06000040)
            struct.pack_into('<h', data, off + 0x18, obj['id'])
            struct.pack_into('<h', data, off + 0x1A, obj.get('contents', -1))
            struct.pack_into('<h', data, off + 0x1C, obj.get('lid', -1))
            struct.pack_into('<h', data, off + 0x1E, -1)
        
        # Write ground tiles
        ground_base = area + 0x247A4
        for i, (x, y, tile_id) in enumerate(self.ground_tiles):
            off = ground_base + i * 4
            data[off + 0] = x
            data[off + 1] = y
            struct.pack_into('<H', data, off + 2, tile_id)
        
        # Write track records (see add_track)
        tracks = getattr(self, 'tracks', [])
        track_base = area + 0x28624
        for i, tr in enumerate(tracks):
            off = track_base + i * 12
            struct.pack_into('<H', data, off + 0x0, 0)
            data[off + 0x2] = 1 if tr['has_object'] else 0
            data[off + 0x3] = tr['x']
            data[off + 0x4] = tr['y']
            data[off + 0x5] = tr['type']
            struct.pack_into('<H', data, off + 0x6, tr['lid'])
            struct.pack_into('<HH', data, off + 0x8, *tr['tail'])

        # Set counts
        struct.pack_into('<i', data, area + 0x1C, len(self.objects))
        struct.pack_into('<i', data, area + 0x3C, len(self.ground_tiles))
        struct.pack_into('<i', data, area + 0x40, len(tracks))
        
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
    The goal pole stands 9.5 tiles before the right edge (x 25.5 here); keep
    content at x <= 23 so the ground connects to the goal area.
    """
    b = LevelBuilder("Flat Ground", "SMB1", "Ground")
    # Ground from x=7 to x=24 (one more tile to connect with goal at x=27)
    b.add_ground_block(7, 24, y_surface=4, height=5)
    b.goal_y = 5
    return b


@test_level(1, "Jump Platforms")
def level_jump_platforms() -> LevelBuilder:
    """Platforms at different heights for jump testing."""
    b = LevelBuilder("Jump Test", "SMB1", "Ground")
    b.add_ground_block(7, 10, y_surface=4, height=5)  # Start at x=7
    b.add_platform(12, 6, 3)   # Low platform
    b.add_platform(16, 8, 3)   # Medium platform
    b.add_platform(20, 10, 3)  # High platform
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
    b.goal_y = 10
    return b


@test_level(3, "Ice Terrain")
def level_ice() -> LevelBuilder:
    """Ice surface for friction testing."""
    b = LevelBuilder("Ice Test", "SMB1", "Snow")
    # Normal ground at start
    b.add_ground_block(7, 12, y_surface=4, height=5)
    # Ice blocks section (objects, not ground tiles)
    b.add_ice(13, 22, 4)
    b.goal_y = 5
    return b


@test_level(4, "Underwater")
def level_underwater() -> LevelBuilder:
    """Underwater level for water physics."""
    b = LevelBuilder("Water Test", "SMB1", "Underwater")
    # Ground must start at x=7 (outside start area) and extend to x=24
    b.add_ground_block(7, 24, y_surface=4, height=5)
    b.start_y = 10
    b.goal_y = 5
    return b


@test_level(5, "Flat Ground (3DW)")
def level_3dw_flat() -> LevelBuilder:
    """3D World style flat ground with detailed edges."""
    b = LevelBuilder("3DW Flat", "3DW", "Ground")
    # 3DW: smaller level like Nico's example (x=7-13)
    b.add_ground_block(7, 13, y_surface=4, height=5)
    b.goal_y = 5
    return b


@test_level(6, "Flat Ground (SMB3)")
def level_smb3_flat() -> LevelBuilder:
    """SMB3 style flat ground."""
    b = LevelBuilder("SMB3 Flat", "SMB3", "Ground")
    b.add_ground_block(7, 24, y_surface=4, height=5)
    b.goal_y = 5
    return b


@test_level(7, "Flat Ground (SMW)")
def level_smw_flat() -> LevelBuilder:
    """Super Mario World style flat ground."""
    b = LevelBuilder("SMW Flat", "SMW", "Ground")
    b.add_ground_block(7, 24, y_surface=4, height=5)
    b.goal_y = 5
    return b


@test_level(14, "Camera Walk")
def level_camera_walk() -> LevelBuilder:
    """120 tiles of flat SMB1 ground and nothing else: room for the camera
    to scroll through a walk, a run, a turn-around and a few jumps while the
    probe logs the view rectangle every frame.
    """
    b = LevelBuilder("Camera Walk", "SMB1", "Ground")
    b.width = 120
    b.add_ground_block(7, b.width - 11, y_surface=4, height=5)   # ends 1.5 tiles before the pole, like Flat Ground
    b.goal_y = 5
    return b


@test_level(15, "Track Spawn")
def level_track_spawn() -> LevelBuilder:
    """Track Note moved out of the initial view: the same two-piece rail with
    a note block, but at x 40..44 on an 80-tile course, so the block spawns
    while the player walks right (view right edge + 55 units reaches it at
    view left ~201). Rail at y 11.5, block starts at (43.5, 11.5) tiles.
    """
    level = LevelBuilder("Track Spawn", style='SMB1', theme='Ground')
    level.width = 80
    level.goal_y = 4
    level.add_ground_fill(7, level.width - 11, 4)
    level.add_track(40, 10, TRACK_SHAPE_HORIZONTAL, ends=(0x0090, 0x0070))
    with_block = level.add_track(42, 10, TRACK_SHAPE_HORIZONTAL, ends=(0x0071, 0x0104))
    level.add_note_block_on_track(with_block)
    return level


@test_level(16, "Camera Stairs")
def level_camera_stairs() -> LevelBuilder:
    """Vertical camera: flat ground, then a staircase of one-tile steps up
    to y 16 (three tiles per step), a plateau, and a drop back to the floor.
    Walk right with a jump every step and the view bottom has to follow the
    player up and back down while the probe logs both.
    """
    b = LevelBuilder("Camera Stairs", "SMB1", "Ground")
    b.width = 120
    b.add_ground_block(7, 20, y_surface=4, height=5)
    x = 21
    for step in range(12):                       # surfaces y 5..16
        b.add_ground_block(x, x + 2, y_surface=5 + step, height=6 + step)
        x += 3
    b.add_ground_block(x, x + 12, y_surface=16, height=17)   # plateau x 57..69
    x += 13
    b.add_ground_block(x, b.width - 11, y_surface=4, height=5)   # floor again
    b.goal_y = 5
    return b


@test_level(17, "Camera Drop")
def level_camera_drop() -> LevelBuilder:
    """A long descent for the vertical camera: the course starts on a
    plateau at y 16 (start_y raised, ground under it), and at x 21 the floor
    drops twelve tiles to y 4 for the rest of an 80-tile course. Walk right
    and the view bottom has to follow the player down 192 units.
    """
    b = LevelBuilder("Camera Drop", "SMB1", "Ground")
    b.width = 80
    b.start_y = 16
    b.add_ground_block(7, 20, y_surface=15, height=16)   # x 0..6 is the generated start area; feet at row 16
    b.add_ground_block(21, b.width - 11, y_surface=4, height=5)
    b.goal_y = 5
    return b


@test_level(18, "Note Bounce")
def level_note_bounce() -> LevelBuilder:
    """A free-standing note block three tiles above the floor: jump on it
    and bounce while a probe logs the player and the block every frame,
    for the bounce velocity and the note frame (bead 8og0.5).
    """
    b = LevelBuilder("Note Bounce", "SMB1", "Ground")
    b.add_ground_block(7, 24, y_surface=4, height=5)
    # A capped one-piece track: the block shuttles one tile and stays put
    # enough to land on; the on-track actor (id 36) runs sub_71013951C0.
    t = b.add_track(11, 6, TRACK_SHAPE_HORIZONTAL, ends=(0x0071, 0x0070))   # end[0] -> right cell (right cap 0x71), end[1] -> left cell (left cap 0x70)
    b.add_note_block_on_track(t)
    b.goal_y = 5
    return b


@test_level(19, "Note Bounce W")
def level_note_bounce_w() -> LevelBuilder:
    """Note Bounce with wings on the block (railmusic's wing variant)."""
    b = LevelBuilder("Note Bounce W", "SMB1", "Ground")
    b.add_ground_block(7, 24, y_surface=4, height=5)
    t = b.add_track(11, 6, TRACK_SHAPE_HORIZONTAL, ends=(0x0071, 0x0070))
    b.add_note_block_on_track(t, wings=True)
    b.goal_y = 5
    return b


@test_level(20, "Note Bounce Water")
def level_note_bounce_water() -> LevelBuilder:
    """Note Bounce in the underwater theme (railmusic's water skin)."""
    b = LevelBuilder("Note Bounce Water", "SMB1", "Underwater")
    b.add_ground_block(7, 24, y_surface=4, height=5)
    t = b.add_track(11, 6, TRACK_SHAPE_HORIZONTAL, ends=(0x0071, 0x0070))
    b.add_note_block_on_track(t)
    b.goal_y = 5
    return b


@test_level(21, "Broken Track")
def level_broken_track() -> LevelBuilder:
    """Replica of the editor-made "Teleport music" (broken-track glitch):
    five detached note blocks whose parent halves survive with joint words
    pointing into removed pieces, plus the curve the teleport targets. Track
    records and actor records copied verbatim from that course's save."""
    b = LevelBuilder("Broken Track", "SMB1", "Ground")
    b.width = 57   # the track/actor records reach x=22; widen the area to hold them
    b.add_ground_block(7, 46, y_surface=3, height=4)   # start at x=7: leave x0-6 for the auto start zone
    for has, x, y, shape, lid, e0, e1 in [
        (0, 20,  9, 4,  2, 0x71, 0x72),
        (1, 17,  9, 0,  3, 0x90, 0x104),
        (1, 10,  6, 0,  1, 0x90, 0x104),
        (0, 12,  6, 0,  4, 0x90, 0x104),
        (0, 14,  6, 0,  5, 0x97, 0x104),
        (0,  9,  7, 1,  6, 0x91, 0x94),
        (0,  9,  9, 1,  7, 0x91, 0x104),
        (1,  9, 11, 1,  8, 0x95, 0x104),
        (0, 10, 12, 0,  9, 0x90, 0x104),
        (0, 15, 10, 4, 10, 0x90, 0x104),
        (1, 12, 12, 0, 11, 0x81, 0x104),
        (0, 14, 12, 1, 12, 0x72, 0x91),
        (1, 14,  7, 5, 13, 0x104, 0x70),
    ]:
        b.add_track(x, y, shape, ends=(e0, e1), has_object=bool(has), lid=lid)
    b.add_actor(23, 18, 10, 0x06000444, lid=3)
    b.add_actor(23, 11,  7, 0x06000444, lid=1)
    b.add_actor(23, 13, 13, 0x06000444, lid=11)
    b.add_actor(23, 16,  9, 0x06000444, lid=13, half=False)
    b.add_actor(74, 19, 11, 0x06000040)
    b.add_actor(23, 10, 12, 0x06200444, lid=8)
    b.goal_y = 4
    return b


@test_level(10, "Track Note")
def level_track_note() -> LevelBuilder:
    """Two joined horizontal track pieces with a note block riding them.

    For the rail-music decomp work: boot this slot with GDB attached, watch
    the note block's pos_x, and the writer's PC is the track traversal code.
    Mirrors the editor-saved course 'track' record for record: piece A ends
    (0x90, 0x70), piece B ends (0x71, 0x104) with the block; the rail runs
    from x 12.5 to 16.5 at y 11.5.
    """
    level = LevelBuilder("Track Note", style='SMB1', theme='Ground')
    level.goal_y = 4
    level.add_ground_fill(7, 23, 4)
    level.add_track(12, 10, TRACK_SHAPE_HORIZONTAL, ends=(0x0090, 0x0070))
    with_block = level.add_track(14, 10, TRACK_SHAPE_HORIZONTAL, ends=(0x0071, 0x0104))
    level.add_note_block_on_track(with_block)
    return level


@test_level(11, "Rail Trace")
def level_rail_trace() -> LevelBuilder:
    """A closed rectangular track loop, one note block riding it clockwise.

    Coursebot accepted it and the block rides every corner (probe trace
    2026-08-30: 544 frames per lap = 106 + 51 + 64 + 51, twice). Geometry:
    end points are cell centres of the 3x3 box, curves are quarter circles
    of radius 1.5 tiles: BL centre (x+2, y+2), BR (x+1, y+2), TR (x+1, y+1),
    TL (x+2, y+1). Words are (w1, w2) = (ends[1], ends[0]) per the EditRail
    tables: 0x104 = no tile (the other piece owns the joint), 0x90 = joint
    with the rail horizontal there, 0x91 = joint with the rail vertical
    opening up, 0x7x = closed cap (the mover reverses). Every joint has
    exactly one owner; 0x9f is the H-to-diagonal joint, not an H left join.

        TL (9,13)   H (11,14)  H (13,14)  TR (15,13)      rail y = 15.5
        V  (8,11)                         V  (16,11)      rail x = 9.5 / 17.5
        BL (9,9)    H (11,8)   H (13,8)   BR (15,9)       rail y = 9.5
    """
    N = 0x0104
    level = LevelBuilder("Rail Trace", style='SMB1', theme='Ground')
    level.goal_y = 4
    level.add_ground_fill(7, 23, 4)
    level.add_track(9, 9, TRACK_SHAPE_CURVE_BL, ends=(0x0090, 0x0091))
    with_block = level.add_track(11, 8, TRACK_SHAPE_HORIZONTAL, ends=(0x0090, N))
    level.add_track(13, 8, TRACK_SHAPE_HORIZONTAL, ends=(0x0090, N))
    level.add_track(15, 9, TRACK_SHAPE_CURVE_BR, ends=(0x0091, N))
    level.add_track(16, 11, TRACK_SHAPE_VERTICAL, ends=(0x0091, N))
    level.add_track(15, 13, TRACK_SHAPE_CURVE_TR, ends=(N, N))
    level.add_track(13, 14, TRACK_SHAPE_HORIZONTAL, ends=(0x0090, N))
    level.add_track(11, 14, TRACK_SHAPE_HORIZONTAL, ends=(0x0090, N))
    level.add_track(9, 13, TRACK_SHAPE_CURVE_TL, ends=(0x0090, N))
    level.add_track(8, 11, TRACK_SHAPE_VERTICAL, ends=(0x0091, N))
    level.add_note_block_on_track(with_block, travel_left=False)
    return level


@test_level(12, "Rail Diag")
def level_rail_diag() -> LevelBuilder:
    """A bent capped track: cap - H - 0x27 joint - ascending diagonal - cap,
    one note block riding it. Certifies the diagonal speed (0.5303 per
    axis), the junction transition and the diagonal cap reversal that the
    sim rider currently models analytically (smm2-decomp PR #135).

    Grid cells: cap (9,9), H body (10,9), joint 0x27 (11,9), asc body
    (12,10), cap (13,11) — the zoo2 first-track geometry with a rider.
    """
    level = LevelBuilder("Rail Diag", style='SMB1', theme='Ground')
    level.goal_y = 4
    level.add_ground_fill(7, 23, 4)
    with_block = level.add_track(9, 8, TRACK_SHAPE_HORIZONTAL, ends=(0x009F, 0x0070))
    level.add_track(11, 9, TRACK_SHAPE_ASC_DIAGONAL, ends=(0x0077, 0x0104))
    level.add_note_block_on_track(with_block, travel_left=False)
    return level


@test_level(13, "Rail Diag2")
def level_rail_diag2() -> LevelBuilder:
    """Rail Diag with the correct west-side joint: editor 0xA5 -> cell 0x2D,
    pair (northeast, west) per the dumped connection-pair table
    (smm2-decomp data/v3.0.3/rail_tables.json pair_2d). The mover should
    BEND at the joint onto the ascending diagonal and shuttle cap to cap;
    Rail Diag (slot 12, 0x9F) is the falling counterpart.
    """
    level = LevelBuilder("Rail Diag2", style='SMB1', theme='Ground')
    level.goal_y = 4
    level.add_ground_fill(7, 23, 4)
    with_block = level.add_track(9, 8, TRACK_SHAPE_HORIZONTAL, ends=(0x00A5, 0x0070))
    level.add_track(11, 9, TRACK_SHAPE_ASC_DIAGONAL, ends=(0x0077, 0x0104))
    level.add_note_block_on_track(with_block, travel_left=False)
    return level


@test_level(22, "Gap Fall")
def level_gap_fall() -> LevelBuilder:
    """Vertical sync tracks with a gap, the music-level way of delaying a note
    block: the block rides down a vertical piece, leaves its open bottom end,
    free-falls the gap and lands on the vertical piece below. Four columns
    in one recording (rail probe, one row per rider per frame):

        A (rail x 9.5)   gap 1 tile    B (12.5) gap 2    C (15.5) gap 3
        D (rail x 18.5)  gap 1 tile with the two closed-cap ids swapped

    Upper pieces sit at y=10 (rail 10.5..12.5, block starts at 11.5): the top
    end is a closed cap (0x72, as an editor-saved vertical piece carries) so
    a block that first rides up turns around; the open ends are 0x104, no
    cell. Coursebot deletes a course whose vertical ends use the 0x88..0x8F
    open-cap ids (0x8A/0x8B tried, validate_slots 2026-09-02); closed caps
    plus 0x104 pass.
    """
    N = 0x0104
    level = LevelBuilder("Gap Fall", style='SMB1', theme='Ground')
    level.goal_y = 4
    level.add_ground_fill(7, 23, 4)
    for x, gap, top_cap, bottom_cap in [(8, 1, 0x72, 0x73), (11, 2, 0x72, 0x73),
                                        (14, 3, 0x72, 0x73), (17, 1, 0x73, 0x72)]:
        upper = level.add_track(x, 10, TRACK_SHAPE_VERTICAL, ends=(top_cap, N))
        level.add_track(x, 8 - gap, TRACK_SHAPE_VERTICAL, ends=(N, bottom_cap))
        level.add_note_block_on_track(upper, vertical=True)
    return level


@test_level(23, "Gap Catch")
def level_gap_catch() -> LevelBuilder:
    """A note block falling off a vertical piece onto a HORIZONTAL track,
    the delivery track of a vertical music level. Four columns, upper piece
    as in Gap Fall (y=10, closed top cap, 0x104 bottom end):

        A (rail x 9.5)  lands on an H body cell, gap 1   H piece (8,8), caps both ends
        B (12.5)        lands on an H body cell, gap 3   H piece (11,6), caps both ends
        C (15.5)        lands on the joint cell of two H pieces, gap 1   (13,8)+(15,8)
        D (18.5)        lands on a closed-cap cell, gap 3   H piece (18,6), its left cap under the rail
    """
    N = 0x0104
    level = LevelBuilder("Gap Catch", style='SMB1', theme='Ground')
    level.goal_y = 4
    level.add_ground_fill(7, 23, 4)
    for x in (8, 11, 14, 17):
        upper = level.add_track(x, 10, TRACK_SHAPE_VERTICAL, ends=(0x72, N))
        level.add_note_block_on_track(upper, vertical=True)
    level.add_track(8, 8, TRACK_SHAPE_HORIZONTAL, ends=(0x71, 0x70))
    level.add_track(11, 6, TRACK_SHAPE_HORIZONTAL, ends=(0x71, 0x70))
    level.add_track(13, 8, TRACK_SHAPE_HORIZONTAL, ends=(0x90, 0x70))
    level.add_track(15, 8, TRACK_SHAPE_HORIZONTAL, ends=(0x71, N))
    level.add_track(18, 6, TRACK_SHAPE_HORIZONTAL, ends=(0x71, 0x70))
    return level


@test_level(8, "Flat Ground (NSMBU)")
def level_nsmbu_flat() -> LevelBuilder:
    """New Super Mario Bros U style flat ground."""
    b = LevelBuilder("NSMBU Flat", "NSMBU", "Ground")
    b.add_ground_block(7, 24, y_surface=4, height=5)
    b.goal_y = 5
    return b


@test_level(9, "Empty")
def level_empty() -> LevelBuilder:
    """Minimal empty level for custom tests - NO ground placed."""
    b = LevelBuilder("Empty", "SMB1", "Ground")
    # Don't place any ground - start/goal areas are auto-generated
    b.start_y = 5
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
