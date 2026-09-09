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
    
    def add_slope(self, x: int, y: int, width: int, height: int, steep: bool = False,
                  descending: bool = False):
        """Add a slope object.
        
        Slopes are objects (not ground tiles) with IDs 87 (slight) or 88 (steep).
        Coordinates are in tiles. Slopes need +0.5 tile offset (placed at tile centers).
        (x, y) is the box's bottom-left tile; the surface runs from the box's
        top corner to the opposite bottom corner, 1:1 steep and 1:2 slight
        (a steep slope is w x (w-1)). Without `descending` it rises to the
        right; with it, flag 0x100000 (uploaded courses: every slope of the
        SMB3 slide 4067530 carries it and descends).
        """
        self.objects.append({
            'id': OBJ_STEEP_SLOPE if steep else OBJ_SLIGHT_SLOPE,
            'x': x,
            'y': y,
            'width': width,
            'height': height,
            'flags': 0x06100040 if descending else 0x06000040,
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
    
    START_AREA_TILES = 7   # x 0..6 is the generated start area; Coursebot deletes a course with a track or object in it
    # The goal area is the course's last tiles: the pole stands 9.5 tiles from
    # the right edge and terrain reaching the tile under it or beyond gets
    # the course deleted (2026-09-09: a ground block to column 30 at width
    # 40, goal at 30.5, deleted; to column 26 at width 35, goal at 25.5,
    # deleted; to column 24 accepted). Objects and tracks have been accepted
    # up to column 27 at width 35 (the packed rows), so their bound is
    # looser; either way nothing generated goes past these columns.
    GOAL_AREA_TILES = 10          # terrain: column width - 10 and beyond
    GOAL_AREA_OBJECT_TILES = 7    # objects and tracks: column width - 7 and beyond

    def goal_area_start(self, objects: bool = False) -> int:
        return self.width - (self.GOAL_AREA_OBJECT_TILES if objects else self.GOAL_AREA_TILES)

    def preflight(self):
        """Refuse what Coursebot is known to delete, before an Eden round trip:
        a track piece (its 3x3 box) or an object inside the start area, and
        any object, tile, slope or track reaching the goal area."""
        bad = []
        g = self.goal_area_start()
        go = self.goal_area_start(objects=True)
        for t in getattr(self, 'tracks', []):
            if t['x'] >= go:
                bad.append(f"track ({t['x']}, {t['y']}) starts in the goal area (x >= {go})")
        for o in self.objects:
            right = o['x'] + max(1, int(o.get('width', 1))) - 1
            if right >= go:
                bad.append(f"object id {o['id']} at ({o['x']}, {o['y']}) w {o.get('width', 1)} reaches the goal area (x >= {go})")
        for (x, y, tile_id) in self.ground_tiles:
            if x >= g:
                bad.append(f"tile {tile_id:#x} at ({x}, {y}) is in the goal area (x >= {g})")
                break
        for t in getattr(self, 'tracks', []):
            if t['x'] < self.START_AREA_TILES:
                bad.append(f"track ({t['x']}, {t['y']}) box reaches into the start area (x < {self.START_AREA_TILES})")
        for o in self.objects:
            if o['x'] < self.START_AREA_TILES:
                bad.append(f"object id {o['id']} at ({o['x']}, {o['y']}) is in the start area (x < {self.START_AREA_TILES})")
        if bad:
            raise ValueError(f"{self.name}: " + "; ".join(bad))

    def build(self) -> bytes:
        """Build the course data."""
        self.preflight()
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
            struct.pack_into('<H', data, off + 0x08, obj.get('res', 0))
            data[off + 0x0A] = obj.get('width', 1)
            data[off + 0x0B] = obj.get('height', 1)
            struct.pack_into('<I', data, off + 0x0C, obj.get('flags', 0x06000040))
            struct.pack_into('<I', data, off + 0x10, obj.get('cflags', 0x06000040))
            struct.pack_into('<I', data, off + 0x14, obj.get('ex', 0))
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


@test_level(27, "Big Flat")
def level_big_flat() -> LevelBuilder:
    """Flat Ground with a free mushroom on the floor and the 3-tall block
    group Coursebot slot 0 carries at tiles 13..15, rows 8..11: measure Big
    Mario's box the way small Mario's was (head bump under the block from a
    running jump, wall pin against its faces at 208 and 256)."""
    b = LevelBuilder("Big Flat", "SMB1", "Ground")
    b.add_ground_block(7, 24, y_surface=4, height=5)
    b.add_ground_block(13, 15, y_surface=11, height=4)
    b.add_actor(OBJ_MUSHROOM, 9, 5)
    b.goal_y = 5
    return b


@test_level(28, "Long Run SMB3")
def level_long_run_smb3() -> LevelBuilder:
    """A 120-tile flat runway in the SMB3 style: room to hold run long
    enough for the P-meter, to see whether the 1.3x acceleration rows and
    the 4.0 cap in the physics block are the P-speed."""
    b = LevelBuilder("Long Run SMB3", "SMB3", "Ground")
    b.width = 120
    b.add_ground_block(7, 109, y_surface=4, height=5)
    b.goal_y = 5
    return b


@test_level(29, "Star Run")
def level_star_run() -> LevelBuilder:
    """The SMB1 runway with a Super Star (object 29) on the floor at tile 9:
    does invincibility switch the acceleration rows and the 4.0 cap?"""
    b = LevelBuilder("Star Run", "SMB1", "Ground")
    b.width = 120
    b.add_ground_block(7, 109, y_surface=4, height=5)
    b.add_actor(29, 9, 5)
    b.goal_y = 5
    return b


@test_level(30, "Slope Layout Only")
def level_slope_layout() -> LevelBuilder:
    """The Slope Course's ground and goal without the slope objects, to see
    which part Coursebot rejects."""
    b = LevelBuilder("Slope Layout", "SMB1", "Ground")
    b.add_ground_block(7, 10, y_surface=4, height=5)
    b.add_ground(21, 23, 10)
    b.start_y = 5
    b.goal_y = 10
    return b


@test_level(31, "One Steep Slope")
def level_one_slope() -> LevelBuilder:
    """Flat Ground with one steep slope object on the floor."""
    b = LevelBuilder("One Slope", "SMB1", "Ground")
    b.add_ground_block(7, 24, y_surface=4, height=5)
    b.add_slope(12, 5, width=4, height=4, steep=True)
    b.goal_y = 5
    return b


def _one_slope(name: str, flags: int = 0x06000040, ex: int = 0, cflags: int = 0x06000040, x: int = 12, y: int = 5, res: int = 0) -> LevelBuilder:
    """A flat floor with one steep slope object. Coursebot accepts only the
    default flags (0x06000040), the default child flags and ex 0 on a slope:
    flags 0x4, 0x8, 0x10, 0x18, 0x20, 0x40000, 0x400000, ex 1 and child
    flags 0x10 / 0x20 were each deleted (2026-09-03), so the slope's
    direction is not in those fields. Moving the anchor (x 15 keeps the tall
    face at the anchor column; y 8 floats the slope at rows 8..11) and the
    16-bit word after y (1 or 2, accepted and ignored) do not turn it
    either: x is the left column, y the bottom row, and the direction is not
    in the record's fields."""
    b = LevelBuilder(name, "SMB1", "Ground")
    b.add_ground_block(7, 24, y_surface=4, height=5)
    b.objects.append({'id': OBJ_STEEP_SLOPE, 'x': x, 'y': y, 'width': 4, 'height': 4,
                      'flags': flags, 'ex': ex, 'cflags': cflags, 'res': res, '_half_tile_offset': True})
    b.goal_y = 5
    return b


@test_level(33, "Steep Slope Up")
def level_steep_slope_up() -> LevelBuilder:
    """A steep slope rising to the right, drawn into the floor the way the
    editor does it: the floor under the slope's 4x4 footprint stops at row
    3, the slope object at (12, 4) supplies the surface row there (its foot
    tile is a full block, the diagonal rises over the next three columns),
    and a column at tiles 16..24 with its top at row 7 meets the ramp's
    top. A slope overlapping ground tiles is deleted by Coursebot."""
    b = LevelBuilder("Steep Slope Up", "SMB1", "Ground")
    b.add_ground_block(7, 11, y_surface=4, height=5)
    b.add_ground_block(12, 15, y_surface=3, height=4)
    b.objects.append({'id': OBJ_STEEP_SLOPE, 'x': 12, 'y': 4, 'width': 4, 'height': 4,
                      'flags': 0x06000040, '_half_tile_offset': True})
    b.add_ground_block(16, 24, y_surface=7, height=8)
    b.goal_y = 8
    return b


@test_level(34, "Steep Slope, nothing after")
def level_steep_slope_open() -> LevelBuilder:
    """The 4x4 steep slope drawn into the floor with nothing at its top:
    the floor beyond continues one row lower."""
    b = LevelBuilder("Steep Slope Open", "SMB1", "Ground")
    b.add_ground_block(7, 11, y_surface=4, height=5)
    b.add_ground_block(12, 24, y_surface=3, height=4)
    b.objects.append({'id': OBJ_STEEP_SLOPE, 'x': 12, 'y': 4, 'width': 4, 'height': 4,
                      'flags': 0x06000040, '_half_tile_offset': True})
    b.goal_y = 4
    return b


def _steep_slope(name: str, style: str) -> LevelBuilder:
    """A 5x5 steep slope drawn into the floor, meeting a column whose top
    is at the ramp's top row."""
    b = LevelBuilder(name, style, "Ground")
    b.add_ground_block(7, 11, y_surface=4, height=5)
    b.add_ground_block(12, 16, y_surface=3, height=4)
    b.objects.append({'id': OBJ_STEEP_SLOPE, 'x': 12, 'y': 4, 'width': 5, 'height': 5,
                      'flags': 0x06000040, '_half_tile_offset': True})
    b.add_ground_block(17, 24, y_surface=8, height=9)
    b.goal_y = 9
    return b


@test_level(35, "Steep Slope 5, column")
def level_steep_slope_5() -> LevelBuilder:
    return _steep_slope("Steep Slope 5", "SMB1")


@test_level(40, "Steep Slope SMB3")
def level_steep_slope_smb3() -> LevelBuilder:
    """The steep slope in the SMB3 style, where ducking on a slope slides."""
    return _steep_slope("Steep Slope 3", "SMB3")


def _gentle_slope(name: str, style: str) -> LevelBuilder:
    """A gentle slope (object 87, 8 wide, 4 tall) drawn into the floor like
    the steep ones: the floor under its footprint stops at row 3, the
    object sits at (12, 4), and a column from tile 20 with its top at row 7
    meets the ramp's top."""
    b = LevelBuilder(name, style, "Ground")
    b.add_ground_block(7, 11, y_surface=4, height=5)
    b.add_ground_block(12, 19, y_surface=3, height=4)
    b.objects.append({'id': OBJ_SLIGHT_SLOPE, 'x': 12, 'y': 4, 'width': 8, 'height': 4,
                      'flags': 0x06000040, '_half_tile_offset': True})
    b.add_ground_block(20, 24, y_surface=7, height=8)
    b.goal_y = 8
    return b


@test_level(36, "Gentle Slope 8x4")
def level_gentle_slope() -> LevelBuilder:
    return _gentle_slope("Gentle Slope", "SMB1")


@test_level(37, "Gentle Slope SMB3")
def level_gentle_slope_smb3() -> LevelBuilder:
    """The gentle slope in the SMB3 style, where ducking on a slope slides."""
    return _gentle_slope("Gentle Slope 3", "SMB3")


@test_level(38, "Gentle Slope SMW")
def level_gentle_slope_smw() -> LevelBuilder:
    return _gentle_slope("Gentle Slope W", "SMW")


@test_level(39, "Gentle Slope NSMBU")
def level_gentle_slope_nsmbu() -> LevelBuilder:
    return _gentle_slope("Gentle Slope U", "NSMBU")


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
    # Ground all the way to the goal area, like the other styles' flats (the
    # 3DW goal recording was made on a slot whose gap Nico had filled by hand).
    b.add_ground_block(7, 24, y_surface=4, height=5)
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


@test_level(55, "Castle Flat")
def level_castle_flat() -> LevelBuilder:
    """Flat ground in the castle theme: the goal is the axe and the bridge it drops."""
    b = LevelBuilder("Castle Flat", "SMB1", "Castle")
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


@test_level(41, "Angled Landing")
def level_angled_landing() -> LevelBuilder:
    """A note block riding RIGHT off the open end of a horizontal piece and
    falling in an arc onto a lower track: the landing comes in at an angle
    (0.75 sideways, about -2.5 down) instead of straight down as in Gap
    Catch. Upper piece at (x, 10): left cap, right end 0x104, so the block
    detaches one cell past the piece, at tile x+3, rail y 184. The lower
    rail sits at row 7 (y 120), 64 units down: about 51 frames of fall and
    38 units of drift, so the block arrives near the right edge of tile x+5.

        A (x 8)   lower H piece (x+4, 6), caps both ends: lands on a body cell
        B (x 15)  lower H piece (x+5, 6): lands on its left cap cell, 6 right of the centre
        C (x 22)  two H pieces (x+3, 6)+(x+5, 6): lands on their joint cell
        D (x 29)  vertical piece (x+4, 6), caps both ends: lands on a vertical rail from the side
    """
    N = 0x0104
    level = LevelBuilder("Angled Landing", style='SMB1', theme='Ground')
    level.width = 60   # the tracks reach tile 36; keep them clear of the goal area
    level.goal_y = 4
    level.add_ground_fill(7, level.width - 11, 4)
    for x in (8, 15, 22, 29):
        upper = level.add_track(x, 10, TRACK_SHAPE_HORIZONTAL, ends=(N, 0x70))
        level.add_note_block_on_track(upper, travel_left=False)
    level.add_track(12, 6, TRACK_SHAPE_HORIZONTAL, ends=(0x71, 0x70))
    level.add_track(20, 6, TRACK_SHAPE_HORIZONTAL, ends=(0x71, 0x70))
    level.add_track(25, 6, TRACK_SHAPE_HORIZONTAL, ends=(0x90, 0x70))
    level.add_track(27, 6, TRACK_SHAPE_HORIZONTAL, ends=(0x71, N))
    level.add_track(33, 6, TRACK_SHAPE_VERTICAL, ends=(0x72, 0x73))
    return level


@test_level(42, "Packed Row 3/4")
def level_packed_row_34() -> LevelBuilder:
    """Three note blocks delivered onto one horizontal rail 0.75 apart, one
    frame of travel: the smallest spacing whose hits land on distinct
    frames. Each column is a stack of vertical pieces (block on the top
    piece, open bottom end) over a shared delivery rail at row 6; the
    columns sit 3 tiles apart and their arrival frames differ by 65, so
    each block lands 0.75 ahead of the previous one (48 units of column
    offset against 48.75 of travel). Chosen with the sim (src-sim in
    smm2-decomp): single piece at row 20 (tile 16), three pieces from row 15
    (tile 13), five from row 11 (tile 10) land at frames 163, 228, 293 after
    a load at frame 65.
    """
    N = 0x0104
    level = LevelBuilder("Packed Row 3/4", style='SMB1', theme='Ground')
    level.goal_y = 4
    level.add_ground_fill(7, 23, 4)
    # the delivery rail starts at tile 8: Coursebot deletes a course with
    # track pieces inside the start area (rails from tile 2 and 6 were)
    for x in range(8, 24, 2):
        level.add_track(x, 6, TRACK_SHAPE_HORIZONTAL, ends=(0x71 if x == 22 else 0x90, 0x70 if x == 8 else N))
    # two tiles clear of the left cap: a block landing on the cell next to a
    # cap comes down 0.02 off (the sim), enough to spoil the row
    for x, y0, n in [(16, 20, 1), (13, 15, 3), (10, 11, 5)]:
        top = None
        for i in range(n):
            # each joint is owned by the piece below through its top end
            # (0x91), as the editor writes vertical chains; every bottom end
            # is 0x104, the bottom piece's being the open drop
            top = level.add_track(x, y0 + 2 * i, TRACK_SHAPE_VERTICAL,
                                  ends=(0x72 if i == n - 1 else 0x91, N))
        level.add_note_block_on_track(top, vertical=True)
    return level


@test_level(43, "Packed Row 1/4")
def level_packed_row_14() -> LevelBuilder:
    """Three note blocks delivered onto one rail 0.25 apart, the finest
    spacing the rail lattice allows (8-unit cell offsets against 0.75 per
    frame): columns 4 tiles apart whose arrival frames differ by 85 and 86
    (one, three and five pieces from row 10 at tiles 18, 14, 10: landings at
    116, 201, 287),
    so the middle block lands 0.25 ahead of the first and the third 0.25
    behind it. The hits of such a row collapse onto shared frames; the row
    exists only until the first cap, whose snap makes the blocks coincide.
    """
    N = 0x0104
    level = LevelBuilder("Packed Row 1/4", style='SMB1', theme='Ground')
    level.goal_y = 4
    level.add_ground_fill(7, 23, 4)
    for x in range(8, 24, 2):
        level.add_track(x, 6, TRACK_SHAPE_HORIZONTAL, ends=(0x71 if x == 22 else 0x90, 0x70 if x == 8 else N))
    for x, y0, n in [(18, 10, 1), (14, 10, 3), (10, 10, 5)]:
        top = None
        for i in range(n):
            # each joint is owned by the piece below through its top end
            # (0x91), as the editor writes vertical chains; every bottom end
            # is 0x104, the bottom piece's being the open drop
            top = level.add_track(x, y0 + 2 * i, TRACK_SHAPE_VERTICAL,
                                  ends=(0x72 if i == n - 1 else 0x91, N))
        level.add_note_block_on_track(top, vertical=True)
    return level


@test_level(44, "Vertical Chain")
def level_vertical_chain() -> LevelBuilder:
    """Coursebot control for a stacked vertical chain: two vertical pieces
    (joint owned by the lower piece's top end, 0x91), block on the top one,
    open bottom, a capped horizontal piece below to catch it.
    """
    N = 0x0104
    level = LevelBuilder("Vertical Chain", style='SMB1', theme='Ground')
    level.goal_y = 4
    level.add_ground_fill(7, 23, 4)
    lower = level.add_track(11, 10, TRACK_SHAPE_VERTICAL, ends=(0x91, N))
    upper = level.add_track(11, 12, TRACK_SHAPE_VERTICAL, ends=(0x72, N))
    level.add_note_block_on_track(upper, vertical=True)
    level.add_track(11, 6, TRACK_SHAPE_HORIZONTAL, ends=(0x71, 0x70))
    return level


def _packed_row_level(name, columns, rail_x1):
    """A planner row (tools/packed_row.py): columns as (tile, bottom row,
    vertical pieces, run pieces, row slot) over a delivery rail from tile 7 to rail_x1
    on row 6; a run is a TL curve at (x+1, top+2) into horizontal pieces on
    row top+3, the block starting on the last one travelling left."""
    N = 0x0104
    level = LevelBuilder(name, style='SMB1', theme='Ground')
    level.goal_y = 4
    level.add_ground_fill(7, 23, 4)
    for rx in range(7, rail_x1 + 1, 2):
        level.add_track(rx, 6, TRACK_SHAPE_HORIZONTAL, ends=(0x71 if rx == rail_x1 else 0x90, 0x70 if rx == 7 else N))
    starts = []
    for x, y0, n, h, slot in columns:
        top = y0 + 2 * (n - 1)
        piece = None
        for i in range(n):
            piece = level.add_track(x, y0 + 2 * i, TRACK_SHAPE_VERTICAL,
                                    ends=((0x91 if h else 0x72) if i == n - 1 else 0x91, N))
        if h:
            level.add_track(x + 1, top + 2, TRACK_SHAPE_CURVE_TL, ends=(0x90, N))
            for j in range(h):
                piece = level.add_track(x + 3 + 2 * j, top + 3, TRACK_SHAPE_HORIZONTAL, ends=(0x71 if j == h - 1 else 0x90, N))
        starts.append((slot, piece, bool(h)))
    # the stack draws in landing order, whatever the object order (Eden, 2026-09-04)
    for slot, piece, run in starts:
        if run:
            level.add_note_block_on_track(piece, travel_left=True)
        else:
            level.add_note_block_on_track(piece, vertical=True)
    return level


def _packed_row_level2(name, columns, rail_x1, right=False, width=None):
    """A planner row whose lead-in runs may step down through a diagonal:
    columns as (tile, bottom row, vertical pieces, low run pieces, high run
    pieces, row slot). The low run sits on row top+3 as before; with high
    pieces an ascending diagonal joins the last low piece's east end to a
    run two rows up, and the block starts on the last high piece travelling
    left. Joint words from the rail decomp's pair table: the low piece's
    east end owns the south-west junction (0xA5, pair north-east/west), the
    first high piece's west end owns the north-east one (0x9D, pair
    east/south-west); the diagonal's ends are 0x104."""
    N = 0x0104
    level = LevelBuilder(name, style='SMB1', theme='Ground')
    if width:
        level.width = width
    level.goal_y = 4
    level.add_ground_fill(7, min(rail_x1, level.width - 11), 4)
    for rx in range(7, rail_x1 + 1, 2):
        level.add_track(rx, 6, TRACK_SHAPE_HORIZONTAL, ends=(0x71 if rx == rail_x1 else 0x90, 0x70 if rx == 7 else N))
    starts = []
    for x, y0, n, h, hh, slot in columns:
        top = y0 + 2 * (n - 1)
        piece = None
        for i in range(n):
            piece = level.add_track(x, y0 + 2 * i, TRACK_SHAPE_VERTICAL,
                                    ends=((0x91 if h else 0x72) if i == n - 1 else 0x91, N))
        if h and not right:
            level.add_track(x + 1, top + 2, TRACK_SHAPE_CURVE_TL, ends=(0x90, N))
            low_row = top + 3
            for j in range(h):
                last_low = j == h - 1
                east = 0xA5 if (last_low and hh) else (0x71 if last_low else 0x90)
                piece = level.add_track(x + 3 + 2 * j, low_row, TRACK_SHAPE_HORIZONTAL, ends=(east, N))
            if hh:
                xl = x + 3 + 2 * (h - 1)
                level.add_track(xl + 2, low_row + 1, TRACK_SHAPE_ASC_DIAGONAL, ends=(N, N))
                for j in range(hh):
                    east = 0x71 if j == hh - 1 else 0x90
                    west = 0x9D if j == 0 else N
                    piece = level.add_track(xl + 4 + 2 * j, low_row + 2, TRACK_SHAPE_HORIZONTAL, ends=(east, west))
        elif h:
            # Mirrored for a row travelling right: a TR curve at (x-1, top+2)
            # into a run going left along row top+3 (the curve owns that
            # joint), and, with high pieces, a descending diagonal from the
            # last low piece's west end (0x9E, pair east/north-west) up to a
            # run two rows higher whose first piece's east end owns the
            # north-west junction (0xA6, pair west/south-east).
            level.add_track(x - 1, top + 2, TRACK_SHAPE_CURVE_TR, ends=(N, 0x90))
            low_row = top + 3
            for j in range(h):
                last_low = j == h - 1
                west = 0x9E if (last_low and hh) else (0x70 if last_low else 0x90)
                piece = level.add_track(x - 3 - 2 * j, low_row, TRACK_SHAPE_HORIZONTAL, ends=(N, west))
            if hh:
                xl = x - 3 - 2 * (h - 1)
                level.add_track(xl - 2, low_row + 1, TRACK_SHAPE_DESC_DIAGONAL, ends=(N, N))
                for j in range(hh):
                    east = 0xA6 if j == 0 else N
                    west = 0x70 if j == hh - 1 else 0x90
                    piece = level.add_track(xl - 4 - 2 * j, low_row + 2, TRACK_SHAPE_HORIZONTAL, ends=(east, west))
        starts.append((slot, piece, bool(h)))
    for slot, piece, run in starts:
        if run:
            level.add_note_block_on_track(piece, travel_left=not right)
        else:
            level.add_note_block_on_track(piece, vertical=True)
    return level


@test_level(54, "Packed Row R4")
def level_packed_row_r4() -> LevelBuilder:
    """Four blocks one frame (0.75 units) apart in a row travelling right, all
    loaded at course start. Every column feeds its vertical through a run
    from the left (a bare column's block bounces at its top cap and would land
    going left); the two right columns use a diagonal. Oracle: gaps 0.75 x3,
    row complete 532 frames after the first block activates."""
    return _packed_row_level2("Packed Row R4",
                              [(10, 8, 1, 1, 0, 0), (16, 8, 3, 2, 0, 0), (19, 15, 1, 2, 1, 0), (25, 15, 3, 3, 1, 0)],
                              60, right=True, width=80)


@test_level(53, "Diag Run R")
def level_diag_run_r() -> LevelBuilder:
    """Diag Run mirrored for a row travelling right: the descending diagonal
    and its two junction words, on a long rail in an 80-wide course."""
    return _packed_row_level2("Diag Run R", [(19, 10, 1, 1, 2, 0)], 60, right=True, width=80)


@test_level(51, "Diag Run")
def level_diag_run() -> LevelBuilder:
    """One column whose lead-in steps down through a diagonal: the frame cost
    of the diagonal and its two junctions, for the packed-row planner."""
    return _packed_row_level2("Diag Run", [(13, 10, 1, 1, 2, 0)], 27)


@test_level(52, "Packed Row x4d")
def level_packed_row_x4d() -> LevelBuilder:
    """Four note blocks one frame apart with a clean cascade, the first row
    the planner's vocabulary could not reach: the leftmost column's lead-in
    steps down through a diagonal (60 frames), which shifts its arrival off
    the 43-frame grid the others share. From the exhaustive sweep of the
    arrival model: x7 n2 y0=17 run 2+2 with the diagonal (start row 24),
    x13 n3 y0=12 run 2, x19 n1 y0=12 run 1, x25 n1 y0=10; arrivals 497,
    370, 243, 116 after the load, positions 0.75 apart, start rows 24, 19,
    15, 10 running one way so the stack cascades."""
    return _packed_row_level2("Packed Row x4d", [(7, 17, 2, 2, 2, 0), (13, 12, 3, 2, 0, 0), (19, 12, 1, 1, 0, 0), (25, 10, 1, 0, 0, 0)], 27)


@test_level(45, "Packed Row x5")
def level_packed_row_x5() -> LevelBuilder:
    """Five note blocks two frames (1.5 units) apart on one rail, the most
    tools/packed_row.py packs inside one screen (--gaps 0.75 x4 --slack 4
    --any-order): Eden gaps 1.500 x4, arrivals 128, 190, 250, 316, 386 after
    the load. The landing order is not the row order (slots 0, -2, -6, -4,
    +2) and the stack draws in landing order, so its outlines interleave;
    Packed Row x4 is the ordered one."""
    return _packed_row_level("Packed Row x5", [(25, 12, 1, 0, 0), (22, 16, 2, 0, -2), (19, 11, 4, 0, -6), (16, 19, 1, 2, -4), (13, 15, 4, 1, 2)], 27)


@test_level(46, "Packed Row x4")
def level_packed_row_x4() -> LevelBuilder:
    """Four note blocks with a one-way cascade of outlines: the stack draws
    by start height (the highest start in front), so the start rows run 12,
    17, 21, 23 from the right along the row (--gaps 0.75 x3 --slack 1
    --by-height --any-order --wide; columns six tiles apart give the runs
    room). The one two-frame gap sits between the first two landers, so the
    last block joins flush: sim gaps 0.750, 0.750, 1.500 from the left."""
    return _packed_row_level("Packed Row x4", [(25, 12, 1, 0, 0), (19, 14, 1, 1, 0), (13, 14, 3, 2, 0), (10, 10, 6, 1, 0)], 27)


def _piece_gallery(name, wings):
    """The Rail Trace loop lowered to rows 5..13 (rails y 6.5 / 12.5, x 9.5 /
    17.5) beside the Rail Diag2 bend at tiles 19..23, both riders starting
    rightwards, so one screen shows a block cross a straight, a curve and a
    diagonal. The guide's piece pictures are cropped from a play screenshot
    of this course with the rail probe's per-frame positions drawn on."""
    N = 0x0104
    level = LevelBuilder(name, style='SMB1', theme='Ground')
    level.goal_y = 4
    level.add_ground_fill(7, 23, 4)
    level.add_track(9, 6, TRACK_SHAPE_CURVE_BL, ends=(0x0090, 0x0091))
    loop_start = level.add_track(11, 5, TRACK_SHAPE_HORIZONTAL, ends=(0x0090, N))
    level.add_track(13, 5, TRACK_SHAPE_HORIZONTAL, ends=(0x0090, N))
    level.add_track(15, 6, TRACK_SHAPE_CURVE_BR, ends=(0x0091, N))
    level.add_track(16, 8, TRACK_SHAPE_VERTICAL, ends=(0x0091, N))
    level.add_track(15, 10, TRACK_SHAPE_CURVE_TR, ends=(N, N))
    level.add_track(13, 11, TRACK_SHAPE_HORIZONTAL, ends=(0x0090, N))
    level.add_track(11, 11, TRACK_SHAPE_HORIZONTAL, ends=(0x0090, N))
    level.add_track(9, 10, TRACK_SHAPE_CURVE_TL, ends=(0x0090, N))
    level.add_track(8, 8, TRACK_SHAPE_VERTICAL, ends=(0x0091, N))
    diag_start = level.add_track(19, 5, TRACK_SHAPE_HORIZONTAL, ends=(0x00A5, 0x0070))
    level.add_track(21, 6, TRACK_SHAPE_ASC_DIAGONAL, ends=(0x0077, N))
    level.add_note_block_on_track(loop_start, wings=wings, travel_left=False)
    level.add_note_block_on_track(diag_start, wings=wings, travel_left=False)
    return level


@test_level(49, "Piece Gallery")
def level_piece_gallery() -> LevelBuilder:
    """Straight, curve and diagonal under one non-winged block each (0.75 a frame)."""
    return _piece_gallery("Piece Gallery", wings=False)


@test_level(50, "Piece Gallery W")
def level_piece_gallery_w() -> LevelBuilder:
    """Piece Gallery with winged blocks (1.5 a frame)."""
    return _piece_gallery("Piece Gallery W", wings=True)


@test_level(24, "Gap Open")
def level_gap_open() -> LevelBuilder:
    """Gap Fall with the editor's open track ends instead of 0x104: 0x83 at
    the upper piece's bottom, 0x82 at the lower piece's top (Coursebot
    accepts 0x80..0x83; validate_slots 2026-09-02). The block lands at the
    open cap cell, the rail's nominal end, a tile earlier than in Gap Fall.
    Column D swaps the two open ids to show which faces which way: the
    upper 0x82 is passed through, the lower 0x83 faces away and the body
    cell below catches the block.
    """
    level = LevelBuilder("Gap Open", style='SMB1', theme='Ground')
    level.goal_y = 4
    level.add_ground_fill(7, 23, 4)
    for x, gap, upper_ends, lower_ends in [(8, 1, (0x72, 0x83), (0x82, 0x73)),
                                           (11, 2, (0x72, 0x83), (0x82, 0x73)),
                                           (14, 3, (0x72, 0x83), (0x82, 0x73)),
                                           (17, 1, (0x72, 0x82), (0x83, 0x73))]:
        upper = level.add_track(x, 10, TRACK_SHAPE_VERTICAL, ends=upper_ends)
        level.add_track(x, 8 - gap, TRACK_SHAPE_VERTICAL, ends=lower_ends)
        level.add_note_block_on_track(upper, vertical=True)
    return level


@test_level(25, "Gap Open W")
def level_gap_open_w() -> LevelBuilder:
    """Gap Open with winged note blocks (railmusic's wing type: the rider
    step runs them at 1.5 units per frame) and gaps of 1, 2, 3 and 4 tiles,
    for TrackConductor's wing gaps row. Upper pieces at y=11 so the
    four-tile column's lower piece clears the ground.
    """
    level = LevelBuilder("Gap Open W", style='SMB1', theme='Ground')
    level.goal_y = 4
    level.add_ground_fill(7, 23, 4)
    for x, gap in [(8, 1), (11, 2), (14, 3), (17, 4)]:
        upper = level.add_track(x, 11, TRACK_SHAPE_VERTICAL, ends=(0x72, 0x83))
        level.add_track(x, 9 - gap, TRACK_SHAPE_VERTICAL, ends=(0x82, 0x73))
        level.add_note_block_on_track(upper, wings=True, vertical=True)
    return level


@test_level(26, "Rider Flags")
def level_rider_flags() -> LevelBuilder:
    """Which way a note block starts riding, per record flag: four capped
    one-piece tracks (the block shuttles), the rider probe logs the first
    frames' velocity. A vertical piece without 0x100000 (col A) and with
    it (B); a horizontal piece without (C) and with (D). Recorded
    2026-09-02: A up, B down, C right, D left. 0x100000 is the negative
    direction on either axis, and add_note_block_on_track's default
    travel_left=True is why every Gap level's block rode down.
    """
    level = LevelBuilder("Rider Flags", style='SMB1', theme='Ground')
    level.goal_y = 4
    level.add_ground_fill(7, 23, 4)
    a = level.add_track(8, 8, TRACK_SHAPE_VERTICAL, ends=(0x72, 0x73))
    level.add_note_block_on_track(a, vertical=True, travel_left=False)
    b = level.add_track(11, 8, TRACK_SHAPE_VERTICAL, ends=(0x72, 0x73))
    level.add_note_block_on_track(b, vertical=True, travel_left=True)
    c = level.add_track(14, 8, TRACK_SHAPE_HORIZONTAL, ends=(0x71, 0x70))
    level.add_note_block_on_track(c, travel_left=False)
    d = level.add_track(17, 8, TRACK_SHAPE_HORIZONTAL, ends=(0x71, 0x70))
    level.add_note_block_on_track(d, travel_left=True)
    return level


@test_level(47, "Slope Walk")
def level_slope_walk() -> LevelBuilder:
    """The slope surface, for a walk recorded by the probe (feet y per x).

    A: from a plateau, a descending slight slope (4x2) into a descending
       steep slope (6x5) that overlaps it by two columns, over the staircase
       of ground an author draws under slopes (the SMB3 slide's junction,
       columns 18-25 there, moved to 13-20 here). The two surfaces disagree
       on the overlap: the slight one ends at y 13 - 2 = 11 at column 17
       while the steep one is already at 10 there.
    B: a descending slight slope with nothing under its box (ground only up
       to row 2): does the object carry its own body?
    C: a rising steep slope (4x3) over a staircase, then a plateau.
       The ground before it sits at the box's ledge height (row 4, surface
       5): the first cut had it two rows lower and the walker stopped at
       the box's wall. Ground under a slope stays a row under its line;
       Coursebot deleted a cut whose staircase touched it.
    D: a rising slight slope (4x2) over a staircase, then the goal ground.
       The level is 80 wide so D stays out of the goal zone (9.5 tiles
       before the right edge); at 60 Coursebot deleted it.
    """
    b = LevelBuilder("Slope Walk", "SMB1", "Ground")
    b.width = 80
    b.start_y = 13
    b.add_ground_block(7, 12, y_surface=12, height=13)
    # A: staircase tops per column under the two slopes.
    for x, top in [(13, 11), (14, 10), (15, 10), (16, 9), (17, 8), (18, 7), (19, 6), (20, 5)]:
        for y in range(0, top + 1):
            b.add_ground_fill(x, x, y)
    b.add_slope(13, 11, width=4, height=2, steep=False, descending=True)
    b.add_slope(15, 7, width=6, height=5, steep=True, descending=True)
    b.add_ground_block(21, 26, y_surface=5, height=6)
    # B: the slope box (rows 4-5) and row 3 stay empty; floor at row 2.
    for x in range(27, 31):
        for y in range(0, 3):
            b.add_ground_fill(x, x, y)
    b.add_slope(27, 4, width=4, height=2, steep=False, descending=True)
    b.add_ground_block(31, 38, y_surface=4, height=5)
    # C: rising steep 4x3 at (39,4): the line runs (40,5)->(42,7), column 39
    # is its ledge at 5, the plateau at 7.
    for x, top in [(39, 3), (40, 3), (41, 4), (42, 5)]:
        for y in range(0, top + 1):
            b.add_ground_fill(x, x, y)
    b.add_slope(39, 4, width=4, height=3, steep=True)
    b.add_ground_block(43, 48, y_surface=6, height=7)
    # D: rising slight 4x2 at (49,6): column 49 is its ledge at 7 (the
    # plateau height), the line runs (50,7)->(52,8), the goal ground at 8.
    for x, top in [(49, 5), (50, 5), (51, 5), (52, 6)]:
        for y in range(0, top + 1):
            b.add_ground_fill(x, x, y)
    b.add_slope(49, 6, width=4, height=2, steep=False)
    b.add_ground_block(53, 69, y_surface=7, height=8)
    b.goal_y = 8
    return b


@test_level(48, "Note Static")
def level_note_static() -> LevelBuilder:
    """Note Bounce without the track: one free-standing note block two
    tiles above the floor at column 11. The same probe log settles whether
    a block off a track bounces like the on-track one the fixtures measured,
    and it is the fixture for smm2-sim's static note blocks.
    """
    b = LevelBuilder("Note Static", "SMB1", "Ground")
    b.add_ground_block(7, 24, y_surface=4, height=5)
    b.objects.append({'id': OBJ_NOTE_BLOCK, 'x': 11, 'y': 6, 'width': 1, 'height': 1,
                      '_half_tile_offset': True})
    b.goal_y = 5
    return b


OBJ_LIFT = 11        # Lift (blue; the record's w byte is its length in tiles; two lifts may not overlap)
OBJ_SPIKE_BALL = 74


def _lift_tie(name: str, first_is_left: bool) -> LevelBuilder:
    """The guide's 'Conflicting priorities': two lifts of the same kind at the
    same height side by side (the validator deletes a course whose lifts
    overlap, 2026-09-09) and a spike ball dropped onto their seam, so both
    surfaces meet its foot at the same distance. The two variants differ
    only in which lift record comes first (the editor's delete + undo moves
    a record to the end); the recording shows which lift the foot picks at
    equal priority. A lift record's x is its centre tile (record 10 -> origin
    168, record 13 -> 216), its surface line spans the centre +-27, and both
    lifts move left 0.5 per frame from spawn; the ball lands 49 frames after
    spawn (frame-exact across runs), when the seam has moved from 192 to
    184, so the ball's origin goes to x = 184 (record 11 with the half-tile
    offset), two tiles up:
    its origin sits 16 under its record centre, so record y 9 put it inside
    the lifts and it fell through.
    """
    b = LevelBuilder(name, "SMB1", "Ground")
    b.add_ground_block(7, 24, y_surface=4, height=5)
    b.goal_y = 5
    left = {'id': OBJ_LIFT, 'x': 10, 'y': 8, 'width': 3, 'height': 1, '_half_tile_offset': True}
    right = {'id': OBJ_LIFT, 'x': 13, 'y': 8, 'width': 3, 'height': 1, '_half_tile_offset': True}
    b.objects += [left, right] if first_is_left else [right, left]
    b.objects.append({'id': OBJ_SPIKE_BALL, 'x': 11, 'y': 11, 'width': 1, 'height': 1,
                      'flags': 0x06000044, '_half_tile_offset': True})
    return b


@test_level(56, "Lift Tie LR")
def level_lift_tie_lr() -> LevelBuilder:
    return _lift_tie("Lift Tie LR", True)


@test_level(57, "Lift Tie RL")
def level_lift_tie_rl() -> LevelBuilder:
    return _lift_tie("Lift Tie RL", False)


@test_level(58, "Surface Kinds")
def level_surface_kinds() -> LevelBuilder:
    """The guide's 'Ground priority test' surfaces, one per column, each with
    a spike ball dropped on it from two tiles up: a note block (23), a
    conveyor belt (94), a donut block (21), the other donut id (82), a spike
    ball resting on the ground (74) and a one-tile ground column. The
    `surface` probe logs the kind word of the shape each ball lands on, which
    indexes the game's surface priority table (docs/re-notes/surfaces.md).
    """
    b = LevelBuilder("Surface Kinds", "SMB1", "Ground")
    b.add_ground_block(7, 24, y_surface=4, height=5)
    b.goal_y = 5
    cols = [(9, 23, 0x06000040), (12, 94, 0x06000040), (15, 21, 0x06000040), (18, 82, 0x06000040),
            (21, 74, 0x06000044)]
    for x, oid, flags in cols:
        b.objects.append({'id': oid, 'x': x, 'y': 6, 'width': 1, 'height': 1, 'flags': flags,
                          '_half_tile_offset': True})
        b.objects.append({'id': OBJ_SPIKE_BALL, 'x': x, 'y': 9, 'width': 1, 'height': 1,
                          'flags': 0x06000044, '_half_tile_offset': True})
    b.ground_tiles.append((23, 6, GROUND_FILL))
    b.objects.append({'id': OBJ_SPIKE_BALL, 'x': 23, 'y': 9, 'width': 1, 'height': 1,
                      'flags': 0x06000044, '_half_tile_offset': True})
    return b


@test_level(59, "Plant Gallery")
def level_plant_gallery() -> LevelBuilder:
    """Plain piranha plants (id 2, no flags) on every surface the guide's
    contraptions put them on, one per column, for the `plant` probe preset:
    on the ground (col 9), on a 3-wide blue lift (col 12, lift at row 8),
    on a 3-wide conveyor (id 53, col 16, belt at row 6) and in an upward
    pipe (2x2 at cols 20..21, row 5). A pipe's content is its own record
    with the in-pipe bit 0x1, placed 80 right of and 240 above the pipe's
    record point, sharing the pipe's link id, the pipe carrying flags
    0x060400C0 (read off Eternal's pipes, 2026-09-09). The ground stays at
    7..24 and the width at 35: a ground block reaching the goal area gets
    the course deleted.
    """
    b = LevelBuilder("Plant Gallery", "SMB1", "Ground")
    b.add_ground_block(7, 24, y_surface=4, height=5)
    b.goal_y = 5
    def plant(x, y, flags=0x06000040, half=True, lid=-1):
        return {'id': 2, 'x': x, 'y': y, 'width': 1, 'height': 1, 'flags': flags, 'lid': lid, '_half_tile_offset': half}
    b.objects.append(plant(9, 5))
    b.objects.append({'id': OBJ_LIFT, 'x': 12, 'y': 8, 'width': 3, 'height': 1, 'flags': 0x06000040, '_half_tile_offset': True})
    b.objects.append(plant(12, 9))
    b.objects.append({'id': 53, 'x': 16, 'y': 6, 'width': 3, 'height': 1, 'flags': 0x06000048, '_half_tile_offset': True})
    b.objects.append(plant(16, 7))
    b.objects.append({'id': 9, 'x': 20, 'y': 5, 'width': 2, 'height': 2, 'flags': 0x060400C0, 'lid': 1, '_half_tile_offset': True})
    b.objects.append(plant(21, 7, 0x06000041, half=False, lid=1))
    return b


@test_level(60, "Plant Pipe Near")
def level_plant_pipe_near() -> LevelBuilder:
    """One upward pipe with a piranha plant five tiles from the start (cols
    10..11, row 5) and nothing else, for the pipe plant's player-near rule
    (smm2-decomp docs/re-notes/piranha-plant.md).
    """
    b = LevelBuilder("Plant Pipe Near", "SMB1", "Ground")
    b.add_ground_block(7, 24, y_surface=4, height=5)
    b.goal_y = 5
    b.objects.append({'id': 9, 'x': 10, 'y': 5, 'width': 2, 'height': 2, 'flags': 0x060400C0, 'lid': 1, '_half_tile_offset': True})
    b.objects.append({'id': 2, 'x': 11, 'y': 7, 'width': 1, 'height': 1, 'flags': 0x06000041, 'lid': 1, '_half_tile_offset': False})
    return b


@test_level(61, "Order Column")
def level_order_column() -> LevelBuilder:
    """A column of movers for the `order` probe preset (the manager's
    per-frame walk, docs/re-notes/processing-order.md in the decomp): two
    3-wide blue lifts at rows 12 and 8 in column 12, the HIGHER one first in
    the record order so the load walk's position order and the record order
    disagree; a plain piranha plant (id 2) on the lower lift (row 9); a
    3-wide conveyor (id 53) at row 6 in column 16 with a plant on it (row
    7). The player starts on the floor and can stand under and beside the
    column. Ground 7..24, width 35 as in the Plant Gallery.
    """
    b = LevelBuilder("Order Column", "SMB1", "Ground")
    b.add_ground_block(7, 24, y_surface=4, height=5)
    b.goal_y = 5
    def plant(x, y):
        return {'id': 2, 'x': x, 'y': y, 'width': 1, 'height': 1, 'flags': 0x06000040, '_half_tile_offset': True}
    b.objects.append({'id': OBJ_LIFT, 'x': 12, 'y': 12, 'width': 3, 'height': 1, 'flags': 0x06000040, '_half_tile_offset': True})
    b.objects.append({'id': OBJ_LIFT, 'x': 12, 'y': 8, 'width': 3, 'height': 1, 'flags': 0x06000040, '_half_tile_offset': True})
    b.objects.append(plant(12, 9))
    b.objects.append({'id': 53, 'x': 16, 'y': 6, 'width': 3, 'height': 1, 'flags': 0x06000048, '_half_tile_offset': True})
    b.objects.append(plant(16, 7))
    return b


@test_level(62, "Placeholder Clip")
def level_placeholder_clip() -> LevelBuilder:
    """The guide's 'Placeholder clipping', three variants stacked above the
    view (the view's top is row 13.5, an actor activates when its box grown
    by a tile overlaps the view, so everything from row 16 up spawns at load
    as a placeholder; the player stands still on the floor). Each variant is
    a free 3-wide blue lift (shuttling 3 tiles left and back) with a spike
    ball resting on it. A record's link id is its track link (real courses:
    a free lift, a ball and a Blaster all carry -1; a linked record with no
    track gets the course deleted), so what rides a lift is a plain record
    placed on it.
    A (col 12, row 18): the lift and its ball alone.
    B (col 20, row 18): a Bill Blaster on the same lift, beside the ball.
    C (col 12, row 24): a Bill Blaster on a pillar of hard blocks at the
       lift's left bound, so the ball meets a solid that is not on its lift.
    """
    b = LevelBuilder("Placeholder Clip", "SMB1", "Ground")
    b.add_ground_block(7, 24, y_surface=4, height=5)
    b.goal_y = 5
    def lift(x, y):
        return {'id': OBJ_LIFT, 'x': x, 'y': y, 'width': 3, 'height': 1, 'flags': 0x06000040, '_half_tile_offset': True}
    def ball(x, y):
        return {'id': OBJ_SPIKE_BALL, 'x': x, 'y': y, 'width': 1, 'height': 1, 'flags': 0x06000044, '_half_tile_offset': True}
    def blaster(x, y):
        return {'id': 13, 'x': x, 'y': y, 'width': 1, 'height': 2, 'flags': 0x06000040, '_half_tile_offset': True}
    b.objects += [lift(12, 18), ball(12, 19)]
    b.objects += [lift(20, 18), ball(20, 19), blaster(21, 19)]
    b.objects += [lift(12, 24), ball(12, 25)]
    for row in range(19, 25):
        b.objects.append({'id': OBJ_HARD_BLOCK, 'x': 9, 'y': row, 'width': 1, 'height': 1, 'flags': 0x06000040, '_half_tile_offset': True})
    b.objects.append(blaster(9, 25))
    return b


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
